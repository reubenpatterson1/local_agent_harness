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
import importlib.machinery
import json
import os
import re
import sys
import types

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

ld = importlib.machinery.SourceFileLoader(
    "location_dataset_for_tests", os.path.join(WS, "location_dataset.py")).load_module()
ll = ld.location_lib


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


# --- Task 4 helpers: the create/regenerate fakes (spec 6.2) ---------------------------------

PASS = {"match_score": 9, "people_visible": False, "shot": "wide shot", "time_of_day": "dusk",
        "weather": "fog"}


class _Fakes(object):
    """The spec 6.2 fakes for create, regenerate and edit: a VLM that answers describe replies in
    order and check replies by still number (replies[n] is a dict, a string sent as is, an
    exception raised, or a list of those, one per attempt; default PASS), the story server, every
    gate, and image children that write 1024x640 solid PNGs for their jobs (except the 1-based
    job numbers in skip, which are blocked) or raise child_error. image_data_url is replaced by
    "file:<path>", so a check call names its still."""

    def __init__(self, monkeypatch, replies=None, describe=(), skip=(), child_error=None,
                 missing=(), vlm_up=True):
        self.replies, self.describe = dict(replies or {}), list(describe)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error, self.missing = set(skip), child_error, list(missing)
        self.attempt = 0
        fakes = self

        def _vlm(parts, max_tokens=600):
            fakes.vlm_calls.append(parts)
            if _kind(parts) == "describe":
                return fakes.describe.pop(0)
            fakes.attempt = fakes.attempt + 1 if _kind(parts) == "retry" else 0
            url = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"][-1]
            reply = fakes.replies.get(int(re.search(r"loc_(\d+)\.png$", url).group(1)), PASS)
            if isinstance(reply, list):
                reply = reply[min(fakes.attempt, len(reply) - 1)]
            if isinstance(reply, Exception):
                raise reply
            return reply if isinstance(reply, str) else json.dumps(reply)

        def _child(spec, loc_dir, step):
            fakes.child_specs.append((json.loads(json.dumps(spec)), step))
            if fakes.child_error is not None:
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                if i in fakes.skip:
                    jobs.append({"output_path": job["output_path"], "status": "blocked",
                                 "seconds": 0.0})
                    continue
                if "image" in job:
                    assert os.path.isfile(job["image"]), job["image"]
                Image.new("RGB", (job["width"], job["height"]), (60, 90, 120)).save(
                    job["output_path"])
                jobs.append({"output_path": job["output_path"], "status": "ok", "seconds": 1.0})
            return {"jobs": jobs, "injected_lora_modules": None}

        monkeypatch.setattr(character_dataset, "image_data_url",
                            lambda path, max_side=768: "file:" + path)
        monkeypatch.setattr(character_dataset, "vlm_call", _vlm)
        monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
        monkeypatch.setattr(character_dataset, "run_edit_child", _child)
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: list(fakes.missing))
        monkeypatch.setattr(character_dataset, "restore_story_server",
                            lambda wait=False: fakes.server_calls.append(
                                "restore-wait" if wait else "restore") or 0)
        monkeypatch.setattr(character_dataset, "story_server",
                            lambda cmd: fakes.server_calls.append(cmd) or 0)
        monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
        monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
        monkeypatch.setattr(character_dataset, "vlm_ready", lambda: vlm_up)
        monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
        monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
        monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)

    def checks(self):
        """The first attempt of every check call, in order: (prompt text, image urls)."""
        out = []
        for parts in self.vlm_calls:
            if _kind(parts) == "check":
                out.append((parts[0]["text"],
                            [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]))
        return out


def _kind(parts):
    """"describe" (a describe or shorten call), "retry" (a check retry) or "check"."""
    text = parts[0]["text"]
    if text == ld.DESCRIBE_PROMPT or text.startswith("Shorten this place description"):
        return "describe"
    if parts[-1]["type"] == "text" and parts[-1]["text"].startswith(
            "Your previous reply was rejected"):
        return "retry"
    return "check"


def _create_args(name="harbour-street", **kw):
    args = dict(command="create", name=name, description=None, photos=None, trigger=None,
                seed=None, force=False, regenerate=False, new_seed=False)
    args.update(kw)
    return argparse.Namespace(**args)


def _photos(tmp_path, count, size=(800, 500), start=0):
    """count distinct solid photos (each a different colour), as absolute paths."""
    out = []
    for k in range(start, start + count):
        path = str(tmp_path / ("photo_in_%02d.png" % k))
        Image.new("RGB", size, (k * 9 % 256, 255 - k * 7 % 256, 40)).save(path)
        out.append(path)
    return out


def _record(env, name="harbour-street"):
    return ll.load_location(name)


def _manifest(env, name="harbour-street"):
    with open(os.path.join(env["locations"], name, "manifest.json")) as f:
        return json.load(f)


def _err_line(capsys):
    return capsys.readouterr().err.strip().splitlines()[-1]


# --- LD1, LD2, LD3: the literals and the check validator (L1.5-L1.9) ------------------------

def test_ld1_the_24_variants_and_gen_prompt():
    views = ["Extreme wide establishing shot", "Wide shot from a high vantage point",
             "Ground-level view looking along the length", "Low-angle upward view",
             "Medium shot of a single detail", "Close-up of a surface texture or sign"]
    times = [("dawn", "clear"), ("midday", "overcast"), ("golden hour", "fog"), ("night", "fog"),
             ("midday", "clear"), ("dusk", "overcast"), ("dawn", "fog"), ("night", "rain"),
             ("golden hour", "clear"), ("midday", "rain"), ("dusk", "fog"), ("night", "clear"),
             ("midday", "overcast"), ("dawn", "overcast"), ("dusk", "rain"), ("golden hour", "fog"),
             ("midday", "overcast"), ("golden hour", "rain"), ("night", "clear"), ("dawn", "rain"),
             ("dawn", "clear"), ("dusk", "fog"), ("golden hour", "overcast"), ("night", "rain")]
    assert ld.VARIANTS == [(views[k // 4],) + times[k] for k in range(24)]
    counts = dict((t, sum(1 for v in ld.VARIANTS if v[1] == t)) for t in ld.TIMES)
    assert counts == {"dawn": 5, "midday": 5, "golden hour": 5, "dusk": 4, "night": 5}
    assert dict((w, sum(1 for v in ld.VARIANTS if v[2] == w)) for w in ld.WEATHERS) == {
        "clear": 6, "overcast": 6, "rain": 6, "fog": 6, "snow": 0}
    for view in views:
        assert len(set(v[1] for v in ld.VARIANTS if v[0] == view)) == 4
    assert ld.TIMES == ("dawn", "midday", "golden hour", "dusk", "night")
    assert ld.WEATHERS == ("clear", "overcast", "rain", "fog", "snow")
    assert ld.STYLE == "photorealistic live-action film still, natural light"
    d = lt.HARBOUR_DESC
    assert ld.gen_prompt(*(ld.VARIANTS[0] + (d,))) == (
        "Extreme wide establishing shot of %s, at dawn, under a clear sky, empty of people. "
        "photorealistic live-action film still, natural light." % d)
    assert ld.gen_prompt(*(ld.VARIANTS[10] + (d,))) == (
        "Ground-level view looking along the length of %s, at dusk, in fog, empty of people. "
        "photorealistic live-action film still, natural light." % d)
    assert ld.gen_prompt(*(ld.VARIANTS[23] + (d,))) == (
        "Close-up of a surface texture or sign of %s, at night, in the rain, empty of people. "
        "photorealistic live-action film still, natural light." % d)


def test_ld2_the_section_2_literals():
    assert ld.EDIT_PROMPT == (
        "Keep this exact place and viewpoint: the same buildings, structures, ground, signs, "
        "materials and colours, seen from the same camera position with the same framing. Change "
        "only the time of day and the conditions: show it %s, %s. No people anywhere in the "
        "image. Photorealistic live-action film still, natural light.")
    assert ld.EDIT_CONDITIONS == [
        ("at dusk", "under a clear sky"), ("at night", "in light rain"),
        ("at dawn", "in thick fog"), ("at midday", "under an overcast sky"),
        ("at golden hour", "under a clear sky"), ("at night", "under a clear sky"),
        ("at midday", "in winter with fresh snow on the ground"), ("at dusk", "in heavy rain"),
        ("at dawn", "under an overcast sky"),
        ("at golden hour", "in autumn with fallen leaves on the ground"),
        ("at midday", "in light fog"), ("at night", "in fog"), ("at dawn", "under a clear sky"),
        ("at dusk", "under an overcast sky"), ("at midday", "in the rain"),
        ("at golden hour", "in light haze"), ("at night", "in winter with snow falling"),
        ("at dawn", "in light rain"), ("at midday", "in summer under a clear sky"),
        ("at dusk", "in fog"), ("at golden hour", "under an overcast sky"),
        ("at night", "in heavy rain"), ("at midday", "in spring under a clear sky")]
    assert len(ld.EDIT_CONDITIONS) == 23
    assert ld.DESCRIBE_PROMPT == (
        'These photos show one place. Describe it for an image generator that must redraw the '
        'same place recognisably from many viewpoints, at any time of day and in any weather. '
        'Reply with only a JSON object with one key. "description": one noun phrase of 15 to 40 '
        'words that starts with "a", "an" or "the" and captures only the place\'s persistent '
        'features: its architecture and structures, materials and surfaces, signage, colour '
        'palette, era and the ground. Leave out people, vehicles, animals, the time of day, the '
        'weather, the lighting, the season, the camera and the image style. Use commas, not full '
        'stops.')
    assert ld.DESCRIBE_SHORTEN == (
        'Shorten this place description to one noun phrase of 20 to 35 words that starts with '
        '"a", "an" or "the". Keep the architecture, materials, signage, palette, era and ground; '
        'drop repetition and the least distinctive details; use commas and no full stops. Reply '
        'with only a JSON object with one key, "description": the shortened phrase.\n\n'
        'Description: %s')
    assert ld.DESCRIBE_RETRY == (
        'Your previous reply was rejected: %s. Previous reply: %s\n'
        'Reply again with only the JSON object. Keep "description" one noun phrase of 15 to 40 '
        'words starting with "a", "an" or "the", with commas and no full stops.')
    keys = ('"people_visible": true when any person or part of a person is visible anywhere in '
            'the image, else false. "shot": exactly one of extreme wide shot, wide shot, medium '
            'shot, medium close-up, close-up, extreme close-up. "time_of_day": exactly one of '
            'dawn, midday, golden hour, dusk, night. "weather": exactly one of clear, overcast, '
            'rain, fog, snow.')
    assert ld.CHECK_TEXT_PROMPT == (
        'The image is a candidate picture of this place: @@DESCRIPTION@@. Reply with only a JSON '
        'object with five keys. "match_score": an integer from 1 to 10 for how clearly the image '
        'shows this place, with its architecture, materials, signage, palette, era and ground, '
        'where 10 is unmistakably this place and 1 is a different place. ' + keys)
    assert ld.CHECK_PHOTO_PROMPT == (
        'The first image shows the reference place. The second image is a candidate picture, '
        'which may show the same place from another viewpoint, at another time of day, in other '
        'weather or in another season. Reply with only a JSON object with five keys. '
        '"match_score": an integer from 1 to 10 for how clearly the candidate shows the same '
        'place as the reference, comparing its architecture, materials, signage, palette and '
        'ground and ignoring the time of day, weather and season, where 10 is unmistakably the '
        'same place and 1 is a different place. ' + keys)
    assert ld.TAG_PROMPT == 'Reply with only a JSON object with four keys describing this image. ' + keys
    assert ld.CHECK_RETRY == (
        'Your previous reply was rejected: %s. Previous reply: %s\n'
        'Reply again with only the JSON object, using exactly the listed values for "shot", '
        '"time_of_day" and "weather" and true or false for "people_visible"%s.')
    assert ld.SCORE_RETRY_EXTRA == ', and an integer from 1 to 10 for "match_score"'
    assert ld.TIME_ALIASES == {"noon": "midday", "day": "midday", "daytime": "midday",
                               "sunrise": "dawn", "sunset": "golden hour", "evening": "dusk",
                               "twilight": "dusk"}
    assert ld.WEATHER_ALIASES == {"sunny": "clear", "cloudy": "overcast", "rainy": "rain",
                                  "foggy": "fog", "mist": "fog", "misty": "fog", "haze": "fog",
                                  "hazy": "fog", "snowy": "snow"}


def test_ld3_validate_location_check():
    v = ld.validate_location_check
    assert v(PASS, True) == PASS
    assert v({"people_visible": True, "shot": " Full Shot ", "time_of_day": "Sunset",
              "weather": "misty"}, False) == {"match_score": None, "people_visible": True,
                                              "shot": "wide shot", "time_of_day": "golden hour",
                                              "weather": "fog"}
    for alias, value in ld.TIME_ALIASES.items():
        assert v(dict(PASS, time_of_day=alias), True)["time_of_day"] == value
    for alias, value in ld.WEATHER_ALIASES.items():
        assert v(dict(PASS, weather=alias), True)["weather"] == value
    assert v(dict(PASS, weather="snow"), True)["weather"] == "snow"
    for bad, scored in ((dict(PASS, match_score=True), True), (dict(PASS, match_score=11), True),
                        (dict(PASS, match_score="9"), True), (dict(PASS, match_score=0), True),
                        ({k: PASS[k] for k in PASS if k != "match_score"}, True),
                        (dict(PASS, people_visible="no"), False), (dict(PASS, shot="aerial"), False),
                        (dict(PASS, time_of_day="afternoon"), False),
                        (dict(PASS, weather="storm"), False), (dict(PASS, shot=3), False)):
        with pytest.raises(ValueError):
            v(bad, scored)


def test_ld4_check_retries_quote_the_rejection(env, monkeypatch, tmp_path):
    png = str(tmp_path / "loc_01.png")
    Image.new("RGB", (64, 40)).save(png)
    fakes = _Fakes(monkeypatch, replies={1: ["not json", json.dumps(PASS)]})
    check, reason = ld.check_still(ld.TAG_PROMPT, [png], False)
    assert reason is None and check["shot"] == "wide shot"
    first, second = fakes.vlm_calls
    assert len(first) == 2 and len(second) == 3
    assert second[-1]["text"] == ld.CHECK_RETRY % ("no JSON object found in text", "not json", "")
    fakes = _Fakes(monkeypatch, replies={1: ["nope", "nope", json.dumps(dict(PASS, shot="x"))]})
    check, reason = ld.check_still(ld.CHECK_TEXT_PROMPT, [png], True)
    assert check is None and reason.startswith("unparseable: shot 'x' is not one of ")
    assert fakes.vlm_calls[1][-1]["text"].endswith(ld.SCORE_RETRY_EXTRA + ".")
    assert len(fakes.vlm_calls) == 3
    _Fakes(monkeypatch, replies={1: RuntimeError("VLM request failed: boom")})
    with pytest.raises(RuntimeError):
        ld.check_still(ld.TAG_PROMPT, [png], False)


# --- LD5: a text create (LK6) ---------------------------------------------------------------

def test_ld5_a_text_create(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, replies=dict((n, dict(PASS, match_score=3)) for n in range(21, 25)))
    assert ld.create(_create_args(description="The " + lt.HARBOUR_DESC[2:] + ".", seed=7)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    ((spec, step),) = fakes.child_specs
    description = "the " + lt.HARBOUR_DESC[2:]
    assert step == "generate" and spec["loras"] is None
    assert spec["jobs"] == [{"prompt": ld.gen_prompt(view, time, weather, description),
                             "output_path": os.path.join(ldir, "stills", "loc_%02d.png" % n),
                             "seed": 7, "width": 1024, "height": 640}
                            for n, (view, time, weather) in enumerate(ld.VARIANTS, start=1)]
    assert fakes.server_calls == ["stop", "restore-wait"]
    stills = os.path.join(ldir, "stills")
    assert fakes.checks() == [(ld.CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", description),
                               ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
                              for n in range(1, 25)]
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"], data["dataset"]["total"]) == ("untrained", 20, 24)
    assert (data["source"], data["photos"], data["trigger"], data["seed"]) == ("text", [], "harboplc", 7)
    assert data["dataset"]["contact_sheet"] == os.path.join(ldir, "contact_sheet.jpg")
    out = capsys.readouterr().out
    assert "dataset: 20/24 stills kept (minimum 12) in %s\n" % ldir in out
    assert out.endswith("next: review the contact sheet, then run bin/location train "
                        "harbour-street\n")
    assert sorted(os.listdir(os.path.join(ldir, "captions"))) == ["loc_%02d.txt" % n
                                                                  for n in range(1, 21)]
    assert sorted(os.listdir(os.path.join(ldir, "videos"))) == ["loc_%02d.mp4" % n
                                                                for n in range(1, 21)]
    with open(os.path.join(env["locations"], ".triggers")) as f:
        assert f.read() == "harboplc harbour-street\n"


# --- LD6-LD10: photo mode (L1.6, L1.7, L1.8) ------------------------------------------------

def test_ld6_a_photo_is_fitted_and_copied_oriented(env, monkeypatch, tmp_path):
    from PIL import ImageOps
    path = str(tmp_path / "rotated.jpg")
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (4000, 3000), (200, 120, 40)).save(path, exif=exif)
    import ltx_image_fit
    oriented = ltx_image_fit.load_oriented_rgb(path)
    assert oriented.size == (3000, 4000)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(photos=[path], description=lt.HARBOUR_DESC)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    with Image.open(os.path.join(ldir, "photos", "photo_01.png")) as copy:
        assert copy.size == (3000, 4000) and copy.tobytes() == oriented.tobytes()
    with Image.open(os.path.join(ldir, "stills", "loc_01.png")) as still:
        expected = ImageOps.fit(oriented, (1024, 640), Image.LANCZOS, centering=(0.5, 0.5))
        assert still.size == (1024, 640) and still.tobytes() == expected.tobytes()
    data = _record(env)
    assert data["photos"] == [{"path": path, "sha256": ld._sha256(path)}]
    assert data["source"] == "photos"


def test_ld7_the_photo_size_rule(env, monkeypatch, tmp_path, capsys):
    _Fakes(monkeypatch, vlm_up=False)
    ok = _photos(tmp_path, 1, size=(768, 480))
    assert ld.create(_create_args(photos=ok, description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys).startswith("Error: the vision model ")
    for size, crop in (((767, 480), "767x479"), ((2000, 479), "766x479")):
        path = _photos(tmp_path, 1, size=size, start=size[0])[0]
        assert ld.create(_create_args(photos=[path], description=lt.HARBOUR_DESC)) == 2
        assert _err_line(capsys) == (
            "Error: --photo %s is %dx%d; its centred 16:10 crop is %s, smaller than the 768x480 "
            "minimum" % (path, size[0], size[1], crop))
    assert os.listdir(env["locations"]) == []


def test_ld8_the_drafted_description(env, monkeypatch, tmp_path, capsys):
    paths = _photos(tmp_path, 6)
    long_text = "the " + " ".join("stone%d" % k for k in range(44))
    short_text = "a quay with boats"
    fakes = _Fakes(monkeypatch, describe=[json.dumps({"description": long_text}),
                                          json.dumps({"description": short_text}),
                                          json.dumps({"description": "The " + lt.HARBOUR_DESC[2:]
                                                      + "."})])
    assert ld.create(_create_args(photos=paths)) == 0
    first, second, third = fakes.vlm_calls[:3]
    assert first[0]["text"] == ld.DESCRIBE_PROMPT
    assert [p["image_url"]["url"] for p in first[1:]] == ["file:" + p for p in paths[:5]]
    assert second == [{"type": "text", "text": ld.DESCRIBE_SHORTEN % long_text}]
    assert third[:6] == first and third[6]["text"] == ld.DESCRIBE_RETRY % (
        "description: must be 15-40 words, got 4", json.dumps({"description": short_text}))
    assert _record(env)["description"] == "the " + lt.HARBOUR_DESC[2:]
    assert ("description (drafted by the vision model; change it with bin/location edit "
            "harbour-street --description TEXT): the " + lt.HARBOUR_DESC[2:]) in capsys.readouterr().out
    _Fakes(monkeypatch, describe=["no json"] * 3)
    assert ld.create(_create_args(name="old-mill", photos=paths)) == 1
    assert _err_line(capsys).startswith(
        "Error: describe failed: no JSON object found in text; last reply: 'no json'")
    assert not os.path.exists(os.path.join(env["locations"], "old-mill"))


@pytest.mark.parametrize("count", [1, 3, 5, 24])
def test_ld9_the_round_robin_top_up(env, monkeypatch, tmp_path, count):
    paths = _photos(tmp_path, count, size=(768, 480))
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(photos=paths, description=lt.HARBOUR_DESC, seed=3)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    stills = os.path.join(ldir, "stills")
    assert sorted(os.listdir(stills)) == ["loc_%02d.png" % n for n in range(1, 25)]
    if count == 24:
        assert fakes.child_specs == [] and fakes.server_calls == []
        assert _manifest(env)["generator"] == "photos only"
        return
    ((spec, step),) = fakes.child_specs
    assert step == "edit" and spec["skill"] == "location_edit"
    assert spec["image"] == os.path.join(stills, "loc_01.png")
    assert (spec["model"], spec["lora_repo"], spec["lora_file"], spec["steps"], spec["true_cfg"]) == (
        character_dataset.EDIT_MODEL, character_dataset.EDIT_LORA_REPO,
        character_dataset.EDIT_LORA_FILE, 8, 1.0)
    assert spec["jobs"] == [{"image": os.path.join(stills, "loc_%02d.png" % (((j - 1) % count) + 1)),
                             "prompt": ld.EDIT_PROMPT % ld.EDIT_CONDITIONS[j - 1],
                             "output_path": os.path.join(stills, "loc_%02d.png" % (count + j)),
                             "seed": 3, "width": 1024, "height": 640}
                            for j in range(1, 25 - count)]
    assert fakes.server_calls == ["stop", "restore-wait"]
    ref = "file:" + os.path.join(stills, "loc_01.png")
    assert fakes.checks() == (
        [(ld.TAG_PROMPT, ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
         for n in range(1, count + 1)]
        + [(ld.CHECK_PHOTO_PROMPT, [ref, "file:" + os.path.join(stills, "loc_%02d.png" % n)])
           for n in range(count + 1, 25)])


def test_ld10_the_edit_model_gate(env, monkeypatch, tmp_path, capsys):
    fakes = _Fakes(monkeypatch, missing=["Qwen/Qwen-Image-Edit-2511"])
    assert ld.create(_create_args(photos=_photos(tmp_path, 2), description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys) == (
        "Error: the photo editor is not downloaded: Qwen/Qwen-Image-Edit-2511; download it with: "
        "hf download Qwen/Qwen-Image-Edit-2511")
    assert fakes.vlm_calls == [] and os.listdir(env["locations"]) == []


# --- LD11-LD15: keep rules, captions, manifest, contact sheet, too few (L1.9-L1.11) ---------

def test_ld11_the_keep_rules(env, monkeypatch, tmp_path):
    _Fakes(monkeypatch, replies={2: dict(PASS, match_score=6),
                                 3: dict(PASS, people_visible=True), 5: ["x", "x", "x"]}, skip=[4])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    items = _manifest(env)["items"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, True, None), (2, False, "score 6"), (3, False, "people visible"),
        (4, False, "blocked by the content screen"),
        (5, False, "unparseable: no JSON object found in text")]
    paths = _photos(tmp_path, 3)
    replies = {1: dict(PASS, people_visible=True), 2: ["x", "x", "x"],
               4: dict(PASS, people_visible=True), 5: dict(PASS, match_score=6)}
    _Fakes(monkeypatch, replies=replies)
    assert ld.create(_create_args(name="dock-one", photos=paths, description=lt.MILL_DESC)) == 0
    items = _manifest(env, "dock-one")["items"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, False, "people visible (pass --force to keep it)"),
        (2, False, "unparseable: no JSON object found in text (pass --force to keep it)"),
        (3, True, None), (4, False, "people visible"), (5, False, "score 6")]
    _Fakes(monkeypatch, replies=replies)
    assert ld.create(_create_args(name="dock-two", photos=paths, description=lt.MILL_DESC,
                                  force=True)) == 0
    items = _manifest(env, "dock-two")["items"]
    trigger = _record(env, "dock-two")["trigger"]
    assert [(i["n"], i["kept"], i["reason"]) for i in items[:5]] == [
        (1, True, "kept by --force: people visible"),
        (2, True, "kept by --force: unparseable: no JSON object found in text"),
        (3, True, None), (4, False, "people visible"), (5, False, "score 6")]
    assert items[1]["caption"] == trigger + ", " + ld.STYLE + "."


def test_ld12_captions():
    assert ld.caption("harboplc", PASS) == (
        "harboplc, wide shot, dusk, fog, empty of people, photorealistic live-action film still, "
        "natural light.")
    assert ld.caption("harboplc", dict(PASS, people_visible=True)) == (
        "harboplc, wide shot, dusk, fog, photorealistic live-action film still, natural light.")
    assert ld.caption("harboplc", None) == (
        "harboplc, photorealistic live-action film still, natural light.")


def test_ld13_the_manifest(env, monkeypatch, tmp_path):
    _Fakes(monkeypatch, skip=[3])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=4)) == 0
    manifest = _manifest(env)
    assert {k: manifest[k] for k in manifest if k != "items"} == {
        "source": "text", "trigger": "harboplc", "description": lt.HARBOUR_DESC, "seed": 4,
        "min_score": 7, "reference": None, "generator": "Z-Image"}
    first, blocked = manifest["items"][0], manifest["items"][2]
    assert first == {"n": 1, "source": "generated", "photo": None,
                     "prompt": ld.gen_prompt(*(ld.VARIANTS[0] + (lt.HARBOUR_DESC,))),
                     "match_score": 9, "people_visible": False, "shot": "wide shot",
                     "time_of_day": "dusk", "weather": "fog", "kept": True, "reason": None,
                     "caption": ld.caption("harboplc", PASS)}
    assert blocked == {"n": 3, "source": "generated", "photo": None,
                       "prompt": ld.gen_prompt(*(ld.VARIANTS[2] + (lt.HARBOUR_DESC,))),
                       "match_score": None, "people_visible": None, "shot": "", "time_of_day": "",
                       "weather": "", "kept": False, "reason": "blocked by the content screen",
                       "caption": None}
    _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 2),
                                  description=lt.MILL_DESC)) == 0
    manifest = _manifest(env, "old-mill")
    assert (manifest["source"], manifest["reference"], manifest["generator"]) == (
        "photos", "loc_01", "Qwen/Qwen-Image-Edit-2511 + "
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    photo, edit = manifest["items"][1], manifest["items"][2]
    assert (photo["source"], photo["photo"], photo["prompt"], photo["match_score"]) == (
        "photo", 2, None, None)
    assert (edit["source"], edit["photo"], edit["prompt"], edit["match_score"]) == (
        "edit", 1, ld.EDIT_PROMPT % ld.EDIT_CONDITIONS[0], 9)
    assert list(edit) == ["n", "source", "photo", "prompt", "match_score", "people_visible",
                          "shot", "time_of_day", "weather", "kept", "reason", "caption"]


def test_ld14_the_contact_sheet(tmp_path, monkeypatch):
    stills = tmp_path / "stills"
    stills.mkdir()
    items = []
    for n in range(1, 25):
        if n != 7:
            Image.new("RGB", (1024, 640), (0, 200, 0)).save(str(stills / ("loc_%02d.png" % n)))
        kept = n not in (2, 7)
        items.append({"n": n, "source": "photo" if n == 1 else "generated",
                      "match_score": None if n in (1, 7) else 9 - (n == 2) * 3, "kept": kept,
                      "reason": None if kept else ("score 6" if n == 2 else
                                                   "blocked by the content screen")})
    texts = []
    real_text = ld.ImageDraw.ImageDraw.text
    monkeypatch.setattr(ld.ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, **kw: texts.append((xy, text)) or real_text(
                            self, xy, text, **kw))
    out = str(tmp_path / "sheet.jpg")
    ld.write_contact_sheet(items, str(stills), out)
    assert texts[0] == ((4, 6), "kept 22 of 24 (need 12)")
    assert [t for _xy, t in texts[1:4]] == ["01 P s- kept", "02 G s6 score 6",
                                            "03 G s9 kept"]
    assert texts[7] == ((256 + 4, 24 + 180 + 160 + 3), "07 G s- blocked by the content scree")
    with Image.open(out) as sheet:
        assert sheet.size == (5 * 256, 24 + 5 * 180)
        assert sheet.getpixel((256 + 1, 24 + 1))[0] > 200 and sheet.getpixel((256 + 1, 24 + 1))[1] < 80
        assert sheet.getpixel((128, 24 + 80))[1] > 150
        assert sheet.getpixel((128, 24 + 1))[0] < 80
        assert max(sheet.getpixel((256 + 128, 180 + 24 + 80))) < 40


def test_ld15_too_few_stills_exit_3(env, monkeypatch, tmp_path, capsys):
    replies = dict((n, dict(PASS, people_visible=True)) for n in range(12, 17))
    replies.update((n, dict(PASS, match_score=3)) for n in range(17, 21))
    replies.update((n, ["x", "x", "x"]) for n in (23, 24))
    _Fakes(monkeypatch, replies=replies, skip=[21, 22])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 3
    ldir = os.path.join(env["locations"], "harbour-street")
    assert _err_line(capsys) == (
        "Error: only 11/24 stills kept (need 12): 5 people visible, 4 score below 7, 2 blocked by "
        "the content screen, 2 unparseable; the dataset is kept in %s; run bin/location create "
        "harbour-street --regenerate --new-seed, or --regenerate --description TEXT with a "
        "clearer description" % ldir)
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("dataset", 11)
    assert os.path.isfile(os.path.join(ldir, "contact_sheet.jpg"))
    _Fakes(monkeypatch, replies=dict((n, dict(PASS, match_score=2)) for n in range(2, 25)))
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 1),
                                  description=lt.MILL_DESC)) == 3
    assert _err_line(capsys).endswith(
        "; create a new location with more photos that show no people, or run bin/location "
        "create old-mill --regenerate --new-seed (--force keeps photos that show people)")


# --- LD16, LD17: a failing or interrupted image child (L5.1) --------------------------------

def test_ld16_a_failed_child_restores_the_server(env, monkeypatch, capsys):
    error = character_dataset.DatasetError("Z-Image child process exited -9; log: /x/logs/g.log")
    fakes = _Fakes(monkeypatch, child_error=error)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert _err_line(capsys) == "Error: Z-Image child process exited -9; log: /x/logs/g.log"
    assert _record(env)["status"] == "dataset" and fakes.vlm_calls == []
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: False)
    assert ld.create(_create_args(name="old-mill", description=lt.MILL_DESC)) == 1
    assert _err_line(capsys) == ("Error: timed out waiting for 20 GiB available memory after "
                                 "stopping the story server")
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
    monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: False)
    fakes.child_error = None
    assert ld.create(_create_args(name="dock-one", description=lt.TEMPLE_DESC)) == 1
    assert _err_line(capsys) == "Error: timed out waiting for the vision server to come back"


def test_ld17_an_interrupt_restores_detached(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, child_error=KeyboardInterrupt())
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore"]
    ldir = os.path.join(env["locations"], "harbour-street")
    assert _err_line(capsys) == (
        "Error: aborted; the stills made so far are kept in %s; run bin/location create "
        "harbour-street --regenerate to start again" % ldir)
    assert _record(env)["status"] == "dataset"


# --- LD24: regenerate (L1.12) ----------------------------------------------------------------

def _text_location(env, monkeypatch, **kw):
    _Fakes(monkeypatch)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, **kw)) == 0
    return os.path.join(env["locations"], "harbour-street")


def _train_record(ldir):
    """Mark the location trained, with a video LoRA, test clips and a train/ dir."""
    data = ll.load_location("harbour-street")
    for sub in ("lora", "tests", "train"):
        os.makedirs(os.path.join(ldir, sub), exist_ok=True)
    with open(os.path.join(ldir, "lora", "video.safetensors"), "wb") as f:
        f.write(lt.VIDEO_BYTES)
    data["loras"]["video"] = {"path": os.path.join(ldir, "lora", "video.safetensors"),
                              "sha256": ld._sha256(os.path.join(ldir, "lora", "video.safetensors")),
                              "base_model": "dgrauet/ltx-2.3-mlx-q8", "rank": 32, "alpha": 32,
                              "steps": 1000}
    data["status"], data["trained_at"] = "trained", "2026-10-29T12:00:00Z"
    data["stills_skip_reason"] = "mflux-train not found at /x"
    ll.write_location(data)


def test_ld24_regenerate(env, monkeypatch, tmp_path, capsys):
    ldir = _text_location(env, monkeypatch, seed=5)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 0
    assert _record(env)["seed"] == 6 and "seed: 5 -> 6" in capsys.readouterr().out
    assert ld.create(_create_args(regenerate=True, seed=40)) == 0
    assert _record(env)["seed"] == 40
    data = _record(env)
    data["seed"] = 2147483647
    ll.write_location(data)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 0
    assert _record(env)["seed"] == 0
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, description=lt.MILL_DESC.replace(
        "an old", "An old") + ".")) == 0
    assert _record(env)["description"] == lt.MILL_DESC
    assert fakes.child_specs[0][0]["jobs"][0]["prompt"] == ld.gen_prompt(
        *(ld.VARIANTS[0] + (lt.MILL_DESC,)))
    # A refused run leaves location.json byte for byte as it was (the seed is persisted only
    # after every preflight passed).
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        before = f.read()
    _Fakes(monkeypatch, vlm_up=False)
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 2
    with open(os.path.join(ldir, "location.json"), "rb") as f:
        assert f.read() == before
    _train_record(ldir)
    _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True)) == 2
    assert _err_line(capsys) == (
        "Error: location harbour-street is trained; regenerating its dataset deletes its LoRAs. "
        "Pass --force to regenerate it anyway")
    os.makedirs(os.path.join(ldir, "logs"), exist_ok=True)
    with open(os.path.join(ldir, "logs", "keep.log"), "w") as f:
        f.write("x")
    assert ld.create(_create_args(regenerate=True, force=True)) == 0
    data = _record(env)
    assert data["loras"] == {"video": None, "stills": None}
    assert (data["status"], data["trained_at"], data["stills_skip_reason"]) == (
        "untrained", None, None)
    for sub in ("lora", "tests", "train"):
        assert not os.path.exists(os.path.join(ldir, sub)), sub
    assert os.path.isfile(os.path.join(ldir, "logs", "keep.log"))
    _Fakes(monkeypatch)
    paths = _photos(tmp_path, 2)
    assert ld.create(_create_args(name="old-mill", photos=paths, description=lt.MILL_DESC)) == 0
    mdir = os.path.join(env["locations"], "old-mill")
    assert ld.create(_create_args(name="old-mill", regenerate=True,
                                  description=lt.HARBOUR_DESC)) == 2
    assert _err_line(capsys) == (
        "Error: a photo location's stills come from its photos; change its description with "
        "bin/location edit old-mill --description TEXT")
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", regenerate=True, new_seed=True)) == 0
    assert sorted(os.listdir(os.path.join(mdir, "photos"))) == ["photo_01.png", "photo_02.png"]
    assert fakes.child_specs[0][0]["jobs"][0]["image"] == os.path.join(mdir, "stills", "loc_01.png")
