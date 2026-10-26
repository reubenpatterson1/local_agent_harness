"""Tests for bin/character end to end (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.4, K1-K18).

Run from the workspace root: python3 -m pytest tests/test_character_tool.py
Plain pytest asserts only (no check() helper). The VLM, the story server, the memory and
disk probes and the Z-Image child are fakes (spec 9.1); real ffmpeg/ffprobe wrap and verify
the kept stills. Every library lives under tmp_path through $CHARACTER_LIBRARY_DIR.
"""

import hashlib
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import character_lib  # noqa: E402

TOOL_PATH = os.path.join(WS, "bin", "character")
tool = importlib.machinery.SourceFileLoader("character_tool", TOOL_PATH).load_module()

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


RONIN_DESCRIPTOR = ("a lean man in his late thirties with a topknot and a scarred brow, wearing a "
                    "faded indigo haori and dark hakama")
CHECK_REPLY = {"shot": "medium shot", "pose": "standing on a trail", "setting": "a forest"}


class _Fakes(object):
    """The spec 9.1 fakes for create/train: a VLM dispatching on the prompt text, the story
    server, the memory/disk/process probes, and a Z-Image child that writes 1024x640 solid
    PNGs for its jobs (except the job numbers in skip, or raising child_error)."""

    def __init__(self, monkeypatch, face=None, describe=None, scores=(), skip=(),
                 child_error=None):
        self.face, self.describe, self.scores = face, describe, list(scores)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error = set(skip), child_error
        fakes = self

        def _vlm(content_parts, max_tokens=600):
            text = content_parts[0]["text"]
            if text == character_dataset.FACE_PROMPT:
                fakes.vlm_calls.append("face")
                return json.dumps({"face_box": fakes.face})
            if text == character_dataset.DESCRIBE_PROMPT:
                fakes.vlm_calls.append("describe")
                return json.dumps(fakes.describe)
            assert text == character_dataset.CHECK_PROMPT
            fakes.vlm_calls.append("check")
            return json.dumps(dict(CHECK_REPLY, identity_score=fakes.scores.pop(0)))

        def _child(spec, char_dir, step):
            fakes.child_specs.append((spec, step))
            if fakes.child_error is not None:
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                if i in fakes.skip:
                    jobs.append({"output_path": job["output_path"], "status": "blocked",
                                 "seconds": 0.0})
                    continue
                Image.new("RGB", (job["width"], job["height"]), (60, 90, 120)).save(
                    job["output_path"])
                jobs.append({"output_path": job["output_path"], "status": "ok", "seconds": 1.0})
            return {"jobs": jobs, "injected_lora_modules": None}

        monkeypatch.setattr(character_dataset, "vlm_call", _vlm)
        monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
        monkeypatch.setattr(character_dataset, "run_edit_child", _child)
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
        monkeypatch.setattr(character_dataset, "restore_story_server",
                            lambda wait=False: fakes.server_calls.append(
                                "restore-wait" if wait else "restore") or 0)
        monkeypatch.setattr(character_dataset, "story_server",
                            lambda cmd: fakes.server_calls.append(cmd) or 0)
        monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
        monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
        monkeypatch.setattr(character_dataset, "vlm_ready", lambda: True)
        monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
        monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
        monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)


def _seed_image(tmp_path):
    path = str(tmp_path / "seed.png")
    Image.new("RGB", (800, 600), (200, 180, 160)).save(path)
    return path


def _tree(lib):
    return sorted(os.listdir(lib)) if os.path.isdir(lib) else []


def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man",
                   status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def _ronin_create(*extra):
    return ["create", "ronin", "--phrase", "the ronin", "--descriptor", RONIN_DESCRIPTOR,
            "--class", "man"] + list(extra)


# --- K1-K3: argument errors, list, show (spec 4.2, 4.3) ----------------------------------
def test_k1_usage_errors():
    for argv in ([], ["create"], ["train"], ["show"]):
        with pytest.raises(SystemExit) as info:
            tool.main(argv)
        assert info.value.code == 2, argv


def test_k2_list(lib_dir, capsys):
    assert tool.main(["list"]) == 0
    assert capsys.readouterr().out == "no characters in %s\n" % lib_dir
    _c45_library(lib_dir)
    assert tool.main(["list"]) == 0
    out = capsys.readouterr().out
    assert out == "\n".join(character_lib.character_table_lines()) + "\n"
    assert out.splitlines()[0].split() == ["NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS",
                                           "PHRASE"]
    assert out.splitlines()[1].startswith("bad              (invalid: ")


def test_k3_show(lib_dir, capsys):
    data = make_character(lib_dir)
    sample = os.path.join(lib_dir, "kyra", "tests", "video_lora.mp4")
    data["loras"]["video"]["sample_path"] = sample
    character_lib.write_character(data)
    assert tool.main(["show", "kyra"]) == 0
    files = [("MISSING", os.path.join(lib_dir, "kyra", "seed.png")),
             ("MISSING", data["dataset"]["contact_sheet"]),
             ("ok", data["loras"]["video"]["path"]),
             ("MISSING", sample)]
    assert capsys.readouterr().out == (
        json.dumps(data, indent=2, ensure_ascii=False) + "\nfiles:\n"
        + "".join("  %-8s %s\n" % f for f in files))
    assert tool.main(["show", "ghost"]) == 2
    assert capsys.readouterr().err == "Error: unknown character: ghost (no %s)\n" % (
        os.path.join(lib_dir, "ghost", "character.json"))


# --- K4-K8: create's argument checks, preflights and face gate (spec 4.4, 7.1) ------------
def test_k4_create_argument_errors(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch)
    make_character(lib_dir)
    character_lib.register_trigger("roninmn", "ronin")
    not_image = tmp_path / "notes.png"
    not_image.write_text("not an image")
    missing = str(tmp_path / "missing.png")
    base = ["create", "nova", "--phrase", "the nova"]
    desc = ["--descriptor", RONIN_DESCRIPTOR, "--class", "man"]
    cases = [
        (["create", "Bad"], "Error: character name must match [a-z][a-z0-9-]{1,23}, got 'Bad'"),
        (["create", "kyra", "--phrase", "the woman in grey"] + desc,
         "Error: character kyra already exists (%s); use --regenerate to rebuild its dataset"
         % os.path.join(lib_dir, "kyra")),
        (["create", "nova"] + desc, "Error: create needs --phrase"),
        (["create", "nova", "--phrase", "the"] + desc,
         "Error: --phrase: phrase must not be a lone article: 'the'"),
        (base, "Error: create needs --seed-image or --descriptor"),
        (base + desc + ["--seed-image", missing], "Error: --seed-image not found: %s" % missing),
        (base + ["--descriptor", RONIN_DESCRIPTOR, "--seed-image", missing],
         "Error: --descriptor needs --class NOUN (the seed image is not described when "
         "--descriptor is given)"),
        (base + ["--descriptor", RONIN_DESCRIPTOR],
         "Error: --descriptor needs --class NOUN (there is no image to take it from)"),
        (base + ["--descriptor", RONIN_DESCRIPTOR, "--class", "Man"],
         "Error: class noun must match [a-z]{3,12}, got 'Man'"),
        (base + ["--descriptor", "a short one", "--class", "man"],
         "Error: --descriptor: descriptor word count must be 8-70, got 3"),
        (base + ["--seed-image", missing], "Error: --seed-image not found: %s" % missing),
        (base + desc + ["--trigger", "AB"],
         "Error: trigger must match [a-z][a-z0-9]{3,15}, got 'AB'"),
        (base + desc + ["--trigger", "roninmn"],
         "Error: trigger roninmn is already used by character ronin; triggers are never reused"),
        (base + desc + ["--trigger", "nova"],
         "Error: trigger nova must not be a word of the phrase or the class noun"),
        (base + ["--descriptor", RONIN_DESCRIPTOR, "--class", "mann", "--trigger", "mann"],
         "Error: trigger mann must not be a word of the phrase or the class noun"),
        (base + desc + ["--seed", "-1"], "Error: --seed must be between 0 and 2147483647"),
        (base + desc + ["--seed", "2147483648"], "Error: --seed must be between 0 and 2147483647"),
    ]
    before = _tree(lib_dir)
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == message + "\n", argv
        assert _tree(lib_dir) == before
    assert tool.main(base + ["--seed-image", str(not_image)]) == 2
    assert capsys.readouterr().err.startswith(
        "Error: --seed-image is not a readable image: %s: " % not_image)
    assert _tree(lib_dir) == before
    assert fakes.vlm_calls == []


def test_k5_regenerate_refusals(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    make_character(lib_dir)
    json_path = os.path.join(lib_dir, "kyra", "character.json")
    cases = [
        (["create", "kyra", "--regenerate", "--phrase", "the lady"],
         "Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger "
         "or --force (only --seed N or --new-seed); edit %s instead" % json_path),
        (["create", "kyra", "--regenerate", "--force"],
         "Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger "
         "or --force (only --seed N or --new-seed); edit %s instead" % json_path),
        (["create", "ghost", "--regenerate"],
         "Error: unknown character: ghost (no %s)" % os.path.join(lib_dir, "ghost",
                                                                  "character.json")),
        (["create", "kyra", "--regenerate"],
         "Error: character kyra is trained; regenerating its dataset would orphan its LoRAs. "
         "Create a new character instead"),
    ]
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == message + "\n"


def test_k6_create_preflights(lib_dir, monkeypatch, capsys):
    argv = _ronin_create()
    lock = os.path.join(lib_dir, ".lock")
    os.makedirs(lib_dir)

    def _case(setup, message):
        with monkeypatch.context() as m:
            _Fakes(m)
            setup(m)
            assert tool.main(argv) == 2
        assert capsys.readouterr().err == message + "\n"
        assert not os.path.exists(os.path.join(lib_dir, "ronin"))

    def _hold(m):
        with open(lock, "w") as f:
            f.write(str(os.getppid()))

    _case(_hold, "Error: another bin/character create/train is running (pid %d); run one at a "
          "time" % os.getppid())
    os.remove(lock)
    _case(lambda m: m.setattr(character_dataset, "busy_process",
                              lambda: (4242, "python3 bin/ltx-movie n")),
          "Error: a render or training process is running (pid 4242: python3 bin/ltx-movie n); "
          "bin/character never trains or generates concurrently with a render")
    _case(lambda m: m.setattr(character_dataset, "free_gib", lambda path: 1.5),
          "Error: only 1.5 GiB free at %s; create needs 2 GiB" % lib_dir)
    _case(lambda m: m.setattr(character_dataset, "vlm_ready", lambda: False),
          "Error: the vision model auto is not being served at "
          "http://127.0.0.1:8177/v1/models; start it with: bin/story-server mlx-vision")
    assert not os.path.exists(lock)


def test_k7_small_face_refused(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[400, 100, 600, 220])
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path), "--no-review"]) == 2
    assert capsys.readouterr().err == (
        "Error: the main character's face fills only 12% of the seed image's height (minimum "
        "15%); a small face makes a weak identity reference. Use a closer crop of the character, "
        "or pass --force to proceed anyway.\n")
    assert not os.path.exists(os.path.join(lib_dir, "kyra"))
    assert not os.path.exists(os.path.join(lib_dir, ".triggers"))
    assert fakes.vlm_calls == ["face"]


KYRA_DESCRIBE = {"class_noun": "woman",
                 "descriptor": "A young East Asian woman with long black hair and a grey kimono."}


def test_k8_small_face_with_force(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, face=[400, 100, 600, 220], describe=KYRA_DESCRIBE, scores=[9] * 25)
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path), "--force", "--no-review"]) == 0
    assert ("Warning: the main character's face fills only 12% of the seed image's height "
            "(minimum 15%); a small face makes a weak identity reference; proceeding (--force)"
            in capsys.readouterr().err)
    assert character_lib.load_character("kyra")["dataset"]["face_height"] == 0.12


# --- K9-K14: create end to end (spec 4.4-4.7) ---------------------------------------------
def test_k9_seed_mode_happy_path(tmp_path, lib_dir, monkeypatch, capsys):
    scores = [9] * 25
    scores[5] = 4
    scores[6] = 7
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=scores)
    seed = _seed_image(tmp_path)
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey",
                      "--seed-image", seed, "--no-review"]) == 0
    cdir = os.path.join(lib_dir, "kyra")
    data = character_lib.load_character("kyra")
    assert data["status"] == "untrained"
    assert data["class_noun"] == "woman"
    assert data["descriptor"] == "a young East Asian woman with long black hair and a grey kimono"
    assert data["trigger"] == "kyrawmn"
    assert data["source"] == {"type": "seed_image", "path": seed}
    assert data["dataset"] == {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                               "face_height": 0.4,
                               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    captions = sorted(os.listdir(os.path.join(cdir, "dataset", "captions")))
    videos = sorted(os.listdir(os.path.join(cdir, "dataset", "videos")))
    assert len(captions) == 24 and len(videos) == 24
    assert "char_05.txt" not in captions
    for name in videos:
        character_dataset.verify_ffprobe(os.path.join(cdir, "dataset", "videos", name))
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "kyrawmn kyra\n"
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert os.path.isfile(os.path.join(cdir, "seed.png"))
    with open(os.path.join(cdir, "seed_face.json")) as f:
        assert json.load(f) == {"face_box": [350, 100, 650, 500]}
    with open(os.path.join(cdir, "dataset", "description.json")) as f:
        assert json.load(f)["class_noun"] == "woman"
    with open(os.path.join(cdir, "dataset", "manifest.json")) as f:
        manifest = json.load(f)
    assert [item["n"] for item in manifest["items"]] == list(range(25))
    assert manifest["reference"] == "char_00" and manifest["face_height"] == 0.4
    assert capsys.readouterr().out.splitlines()[-3:] == [
        "dataset: 24/25 stills kept (minimum 12) in %s" % os.path.join(cdir, "dataset"),
        "contact sheet: %s" % os.path.join(cdir, "dataset", "contact_sheet.jpg"),
        'next: review the contact sheet. For different stills, run '
        'bin/character create kyra --regenerate --new-seed; otherwise run bin/character train kyra']


def test_k10_descriptor_mode(lib_dir, monkeypatch):
    scores = [3] + [9] * 23
    fakes = _Fakes(monkeypatch, scores=scores)
    assert tool.main(_ronin_create()) == 0
    assert "face" not in fakes.vlm_calls and "describe" not in fakes.vlm_calls
    data = character_lib.load_character("ronin")
    assert data["source"] == {"type": "descriptor"}
    assert data["trigger"] == "roninmn"
    assert data["dataset"]["reference"] == "char_01"
    assert data["dataset"]["face_height"] is None
    assert (data["dataset"]["kept"], data["dataset"]["total"]) == (24, 24)
    with open(os.path.join(lib_dir, "ronin", "dataset", "manifest.json")) as f:
        items = json.load(f)["items"]
    assert [item["n"] for item in items] == list(range(1, 25))
    assert items[0]["identity_score"] == 3 and items[0]["kept"] is True
    assert not os.path.exists(os.path.join(lib_dir, "ronin", "seed.png"))


def test_k11_too_few_kept(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[3] * 14 + [9] * 10)
    assert tool.main(_ronin_create()) == 3
    cdir = os.path.join(lib_dir, "ronin")
    assert capsys.readouterr().err == (
        'Error: only 11/24 stills kept (need 12); the dataset is kept in %s; edit "descriptor" in '
        '%s and run bin/character create ronin --regenerate (add --new-seed for different '
        'stills)\n'
        % (os.path.join(cdir, "dataset"), os.path.join(cdir, "character.json")))
    data = character_lib.load_character("ronin")
    assert data["status"] == "dataset"
    assert data["dataset"]["kept"] == 11
    assert os.path.isfile(os.path.join(cdir, "dataset", "manifest.json"))
    assert os.path.isfile(os.path.join(cdir, "dataset", "contact_sheet.jpg"))


def test_k12_regenerate_rebuilds_from_the_edited_descriptor(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[3] * 14 + [9] * 10)
    assert tool.main(_ronin_create()) == 3
    cdir = os.path.join(lib_dir, "ronin")
    json_path = os.path.join(cdir, "character.json")
    with open(json_path) as f:
        data = json.load(f)
    edited = ("a lean man in his late thirties with a long topknot and a scarred brow, wearing "
              "a faded indigo haori")
    data["descriptor"] = edited
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    stale = os.path.join(cdir, "dataset", "stale.txt")
    with open(stale, "w") as f:
        f.write("old")
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    assert tool.main(["create", "ronin", "--regenerate"]) == 0
    assert not os.path.exists(stale)
    assert fakes.vlm_calls == ["check"] * 24
    assert all(edited in job["prompt"] for job in fakes.child_specs[0][0]["jobs"])
    saved = character_lib.load_character("ronin")
    assert saved["trigger"] == "roninmn"
    assert (saved["status"], saved["dataset"]["kept"]) == ("untrained", 24)
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "roninmn ronin\n"


def test_k13_generation_failure_restarts_the_vision_server(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, child_error=character_dataset.DatasetError(
        "Z-Image child process exited 1; log: /x.log"))
    assert tool.main(_ronin_create()) == 1
    assert capsys.readouterr().err == "Error: Z-Image child process exited 1; log: /x.log\n"
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert character_lib.load_character("ronin")["status"] == "dataset"


def test_k14_blocked_reference_still(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[9] * 24, skip=[1])
    assert tool.main(_ronin_create()) == 1
    assert capsys.readouterr().err == (
        "Error: the reference still char_01 was blocked by the content screen; edit the "
        "descriptor in %s and run bin/character create ronin --regenerate\n"
        % os.path.join(lib_dir, "ronin", "character.json"))


def test_k15_registered_trigger_is_never_reused(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    character_lib.register_trigger("kyrawmn", "kyra")
    assert tool.main(["create", "kyra2", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path), "--trigger", "kyrawmn"]) == 2
    assert capsys.readouterr().err == (
        "Error: trigger kyrawmn is already used by character kyra; triggers are never reused\n")


# --- K16-K18: train delegation and the list import rule (spec 1.2, 4.11) -----------------
def test_k16_train_refuses_a_dataset_character(lib_dir, capsys):
    make_character(lib_dir, status="dataset")
    assert tool.main(["train", "kyra"]) == 2
    assert capsys.readouterr().err == (
        "Error: character kyra has no accepted dataset (status dataset); fix it with "
        "bin/character create kyra --regenerate\n")


def test_k17_train_exit_code_is_propagated(lib_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(character_dataset, "train", lambda args: calls.append(args.name) or 1)
    assert tool.main(["train", "kyra"]) == 1
    assert calls == ["kyra"]


def test_k18_list_imports_neither_pil_psutil_nor_character_dataset(lib_dir):
    make_character(lib_dir)
    script = (
        "import sys\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('character_tool', %r).load_module()\n"
        "rc = m.main(['list'])\n"
        "print(sorted(n for n in ('PIL', 'psutil', 'character_dataset') if n in sys.modules))\n"
    ) % TOOL_PATH
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "[]"


# --- K19-K24: seed-image datasets edit the seed (seed-edit spec E1-E10) -------------------
def _kyra_seed_create(tmp_path, *extra):
    return ["create", "kyra", "--phrase", "the woman in grey", "--seed-image",
            _seed_image(tmp_path)] + list(extra)


def test_k19_seed_create_edits_the_seed(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE,
                   scores=[9] * 25)
    zimage = []
    monkeypatch.setattr(character_dataset, "run_zimage_child",
                        lambda spec, char_dir, step: zimage.append(step))
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review")) == 0
    assert zimage == []
    assert [step for _, step in fakes.child_specs] == ["edit"]
    spec = fakes.child_specs[0][0]
    cdir = os.path.join(lib_dir, "kyra")
    assert spec["image"] == os.path.join(cdir, "seed.png")
    assert (spec["model"], spec["lora_repo"], spec["lora_file"], spec["steps"], spec["true_cfg"]) == (
        "Qwen/Qwen-Image-Edit-2511", "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", 8, 1.0)
    order = [int(os.path.basename(j["output_path"])[5:7]) for j in spec["jobs"]]
    assert order == [1, 3, 8, 10, 12, 21] + [n for n in range(1, 25)
                                             if n not in (1, 3, 8, 10, 12, 21)]
    shot, pose, setting = character_dataset.VARIANTS[0]
    assert spec["jobs"][0]["prompt"] == character_dataset.edit_prompt(shot, pose, setting)
    assert all(KYRA_DESCRIBE["descriptor"].lower()[2:] not in j["prompt"] for j in spec["jobs"])
    assert fakes.vlm_calls == ["face", "describe"] + ["check"] * 25
    with open(os.path.join(cdir, "dataset", "manifest.json")) as f:
        manifest = json.load(f)
    assert manifest["generator"].startswith("Qwen/Qwen-Image-Edit-2511 + ")
    assert [item["n"] for item in manifest["items"]] == list(range(25))
    assert "=== edit: 24 stills ===" in capsys.readouterr().out


def test_k20_preview_stop(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE,
                   scores=[9] * 25)
    prompts = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "")
    assert tool.main(_kyra_seed_create(tmp_path)) == 0
    assert [(step, len(spec["jobs"])) for spec, step in fakes.child_specs] == [
        ("edit-preview", 6), ("edit", 18)]
    sheet = os.path.join(lib_dir, "kyra", "dataset", "preview_sheet.jpg")
    assert os.path.isfile(sheet)
    assert prompts == ["Review the preview stills in %s. Enter to edit the remaining 18, Ctrl-C "
                       "to abort: " % sheet]
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert character_lib.load_character("kyra")["status"] == "untrained"


def test_k21_ctrl_c_at_the_preview_stop(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    def _interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)
    assert tool.main(_kyra_seed_create(tmp_path)) == 1
    assert [step for _, step in fakes.child_specs] == ["edit-preview"]
    # An interrupt restores the server detached instead of waiting for it (clean-stop S3).
    assert fakes.server_calls == ["stop", "restore"]
    assert "check" not in fakes.vlm_calls
    assert capsys.readouterr().err.endswith(
        "Error: aborted; the stills made so far are kept in %s; run bin/character create kyra "
        "--regenerate to start again\n" % os.path.join(lib_dir, "kyra", "dataset"))
    assert character_lib.load_character("kyra")["status"] == "dataset"


def test_k22_review_needs_a_terminal(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    message = ("Error: the seed-image preview review needs an interactive terminal; run this "
               "interactively, or pass --no-review for unattended operation\n")
    assert tool.main(_kyra_seed_create(tmp_path)) == 2
    assert capsys.readouterr().err == message
    assert fakes.vlm_calls == [] and not os.path.exists(os.path.join(lib_dir, "kyra"))
    make_character(lib_dir, status="untrained")
    assert tool.main(["create", "kyra", "--regenerate"]) == 2
    assert capsys.readouterr().err == message
    # A descriptor character has no preview stop, so it needs no terminal.
    fakes.scores = [9] * 24
    assert tool.main(_ronin_create()) == 0


def test_k23_missing_editor_is_refused(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE)
    monkeypatch.setattr(character_dataset, "edit_models_missing",
                        lambda: ["Qwen/Qwen-Image-Edit-2511"])
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review")) == 2
    assert capsys.readouterr().err == (
        "Error: the seed-image editor is not downloaded: Qwen/Qwen-Image-Edit-2511; download it "
        "with: hf download Qwen/Qwen-Image-Edit-2511\n")
    assert fakes.vlm_calls == []


def test_k24_seed_image_with_a_given_descriptor(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], scores=[9] * 25)
    assert tool.main(_kyra_seed_create(tmp_path, "--descriptor", DESCRIPTOR, "--class", "woman",
                                       "--no-review")) == 0
    assert fakes.vlm_calls == ["face"] + ["check"] * 25
    data = character_lib.load_character("kyra")
    assert (data["descriptor"], data["class_noun"]) == (DESCRIPTOR, "woman")
    assert data["source"]["type"] == "seed_image"
    assert not os.path.exists(os.path.join(lib_dir, "kyra", "dataset", "description.json"))


# --- VLC1: the generate phase restores through story-server-restore --wait (VLM lifecycle VC1) --
def test_vlc1_create_restores_with_wait(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    assert tool.main(_ronin_create()) == 0
    assert fakes.server_calls == ["stop", "restore-wait"]
    with open(character_dataset.__file__, encoding="utf-8") as f:
        assert "story_server(VLM_SERVE_MODE)" not in f.read()
    assert "warning: story-server-restore" not in capsys.readouterr().err


def test_vlc1_a_failed_restore_warns(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    monkeypatch.setattr(character_dataset, "restore_story_server",
                        lambda wait=False: fakes.server_calls.append(
                            "restore-wait" if wait else "restore") or 1)
    assert tool.main(_ronin_create()) == 0
    assert fakes.server_calls == ["stop", "restore-wait"]
    assert ("warning: story-server-restore mlx-vision --wait returned 1\n"
            in capsys.readouterr().err)


def test_vlc1_restore_story_server_argv(monkeypatch, capsys):
    seen = []

    class _Done(object):
        returncode = 3

    def _run(argv, timeout=None):
        seen.append((argv, timeout))
        return _Done()

    monkeypatch.setattr(character_dataset.subprocess, "run", _run)
    restore = os.path.join(WS, "bin", "story-server-restore")
    assert character_dataset.restore_story_server(wait=True) == 3
    assert character_dataset.restore_story_server() == 3
    assert seen == [([restore, "mlx-vision", "--wait"], None), ([restore, "mlx-vision"], 60)]

    def _fail(argv, timeout=None):
        raise OSError("no such file")

    monkeypatch.setattr(character_dataset.subprocess, "run", _fail)
    assert character_dataset.restore_story_server(wait=True) == 1
    assert capsys.readouterr().err == ("warning: story-server-restore failed: no such file; run "
                                       "bin/story-server mlx-vision\n")


# --- regenerate with a new seed (seed-spec) -----------------------------------------------
def _ronin_dataset(lib_dir, monkeypatch, seed=None):
    """A descriptor-mode ronin whose first build kept too few stills (status dataset); returns
    its character.json path after storing seed, when given."""
    _Fakes(monkeypatch, scores=[3] * 14 + [9] * 10)
    assert tool.main(_ronin_create()) == 3
    path = os.path.join(lib_dir, "ronin", "character.json")
    if seed is not None:
        with open(path) as f:
            data = json.load(f)
        data["seed"] = seed
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    return path


def _regen(monkeypatch, capsys, *extra):
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    code = tool.main(["create", "ronin", "--regenerate"] + list(extra))
    return code, capsys.readouterr(), fakes


def test_seed_regenerate_with_seed_records_it(lib_dir, monkeypatch, capsys):
    _ronin_dataset(lib_dir, monkeypatch)
    capsys.readouterr()
    code, out, fakes = _regen(monkeypatch, capsys, "--seed", "7")
    assert code == 0
    assert "seed: 0 -> 7" in out.out.splitlines()
    assert character_lib.load_character("ronin")["seed"] == 7
    assert all(job["seed"] == 7 for job in fakes.child_specs[0][0]["jobs"])


def test_seed_regenerate_new_seed_increments(lib_dir, monkeypatch, capsys):
    _ronin_dataset(lib_dir, monkeypatch, seed=41)
    capsys.readouterr()
    code, out, _ = _regen(monkeypatch, capsys, "--new-seed")
    assert code == 0
    assert "seed: 41 -> 42" in out.out.splitlines()
    assert character_lib.load_character("ronin")["seed"] == 42


def test_seed_regenerate_new_seed_wraps_to_zero(lib_dir, monkeypatch, capsys):
    _ronin_dataset(lib_dir, monkeypatch, seed=2147483647)
    capsys.readouterr()
    code, out, _ = _regen(monkeypatch, capsys, "--new-seed")
    assert code == 0
    assert "seed: 2147483647 -> 0" in out.out.splitlines()
    assert character_lib.load_character("ronin")["seed"] == 0


def test_seed_regenerate_seed_persisted_before_generation(lib_dir, monkeypatch, capsys):
    _ronin_dataset(lib_dir, monkeypatch, seed=5)
    capsys.readouterr()
    fakes = _Fakes(monkeypatch, scores=[9] * 24, child_error=character_dataset.DatasetError("boom"))
    assert tool.main(["create", "ronin", "--regenerate", "--new-seed"]) == 1
    assert fakes.child_specs
    assert character_lib.load_character("ronin")["seed"] == 6


def test_seed_regenerate_plain_is_unchanged(lib_dir, monkeypatch, capsys):
    path = _ronin_dataset(lib_dir, monkeypatch, seed=9)
    capsys.readouterr()
    writes = []
    real_write = character_lib.write_character
    monkeypatch.setattr(character_lib, "write_character",
                        lambda data: writes.append(data["seed"]) or real_write(data))
    code, out, fakes = _regen(monkeypatch, capsys)
    assert code == 0
    assert "seed: 9 (unchanged)" in out.out.splitlines()
    assert all(job["seed"] == 9 for job in fakes.child_specs[0][0]["jobs"])
    # The seed step itself never rewrote the file; the build's own status write happened later.
    assert writes and all(w == 9 for w in writes)
    assert character_lib.load_character("ronin")["seed"] == 9


def test_seed_regenerate_same_seed_does_not_rewrite(lib_dir, monkeypatch, capsys):
    path = _ronin_dataset(lib_dir, monkeypatch, seed=9)
    capsys.readouterr()
    before = open(path).read()
    # stop before generation: the vision model is "not served"
    _Fakes(monkeypatch)
    monkeypatch.setattr(character_dataset, "vlm_ready", lambda: False)
    os.utime(path, (1000000000, 1000000000))
    assert tool.main(["create", "ronin", "--regenerate", "--seed", "9"]) == 2
    out = capsys.readouterr().out
    assert "seed: 9 (unchanged)" in out.splitlines()
    assert open(path).read() == before and os.stat(path).st_mtime == 1000000000
    assert tool.main(["create", "ronin", "--regenerate"]) == 2
    assert "seed: 9 (unchanged)" in capsys.readouterr().out.splitlines()
    assert open(path).read() == before and os.stat(path).st_mtime == 1000000000


@pytest.mark.parametrize("extra,message", [
    (["--seed", "-1"], "--seed must be between 0 and 2147483647"),
    (["--seed", "2147483648"], "--seed must be between 0 and 2147483647"),
    (["--seed", "3", "--new-seed"], "give --seed or --new-seed, not both"),
])
def test_seed_regenerate_bad_flags(lib_dir, monkeypatch, capsys, extra, message):
    path = _ronin_dataset(lib_dir, monkeypatch, seed=9)
    capsys.readouterr()
    before = open(path).read()
    _Fakes(monkeypatch)
    assert tool.main(["create", "ronin", "--regenerate"] + extra) == 2
    assert capsys.readouterr().err == "Error: %s\n" % message
    assert open(path).read() == before


def test_seed_new_seed_needs_regenerate(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    assert tool.main(_ronin_create("--new-seed")) == 2
    assert capsys.readouterr().err == "Error: --new-seed needs --regenerate\n"
    assert not os.path.exists(os.path.join(lib_dir, "ronin"))


def test_seed_regenerate_still_refuses_other_flags(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    make_character(lib_dir)
    json_path = os.path.join(lib_dir, "kyra", "character.json")
    assert tool.main(["create", "kyra", "--regenerate", "--new-seed", "--phrase", "x"]) == 2
    assert capsys.readouterr().err == (
        "Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger "
        "or --force (only --seed N or --new-seed); edit %s instead\n" % json_path)


def test_seed_guidance_names_new_seed(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=[3] * 20 + [9] * 5)
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review")) == 3
    assert capsys.readouterr().err == (
        "Error: only 6/25 stills kept (need 12); the dataset is kept in %s; run "
        "bin/character create kyra --regenerate --new-seed\n" % os.path.join(lib_dir, "kyra", "dataset"))
