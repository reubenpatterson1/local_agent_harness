"""Tests for shots mode (spec docs/superpowers/specs/2026-10-06-shots-mode-design.md
Section 10, S1-S72).

Run from the workspace root: python3 -m pytest tests/test_shots_mode.py
Plain pytest asserts only (no check() helper). No network, GPU, VLM, Z-Image or LTX: the
story model is a fake subprocess.Popen, the stills runner a fake _stream_and_tee, Z-Image
runs against fake torch/z_image_skill/content_safety modules, the render goes through a
stubbed generate_video, and every character library lives under tmp_path through
$CHARACTER_LIBRARY_DIR.
"""

import ast
import contextlib
import glob
import hashlib
import importlib.machinery
import io
import json
import os
import re
import string
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


ltx_movie = _load("ltx_movie_shots", "bin/ltx-movie")
story_manifest = _load("ltx_story_manifest_shots", "bin/ltx-story-manifest")
story_images = _load("ltx_story_images_shots", "bin/ltx-story-images")
render = _load("ltx_mlx_render_shots", "bin/ltx-mlx-render")

# The character_lib exception classes are looked up on the module at call time, never bound
# with "from character_lib import ...": the pipeline tools load character_lib.py by path into
# the same sys.modules entry, which re-creates its classes.

# --- shared fixtures (spec 10.1, 10.2) -------------------------------------------------
DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"
DESC_M = "an old bald man with a white beard wearing a saffron robe and wooden prayer beads"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True, strength=None):
    """Write a valid trained character.json (casting spec 2.2 shape) under lib/name and return
    the dict: a 16-byte lora/video.safetensors, plus a 16-byte lora/stills.safetensors when
    stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
               "face_height": 0.38,
               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video_path = os.path.join(cdir, "lora", "video.safetensors")
    with open(video_path, "wb") as f:
        f.write(VIDEO_BYTES)
    video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
             "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
             "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
             "sample_path": None, "control_path": None}
    stills_entry = None
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
            "referring_phrase": phrase, "descriptor": descriptor, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": "trained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _kyra(lib, **kw):
    return make_character(lib, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K, **kw)


def _ronin(lib, **kw):
    return make_character(lib, "ronin", "roninmn", "the ronin", "man", DESC_R, **kw)


def _monk(lib, **kw):
    return make_character(lib, "monk", "monkmn", "the monk", "man", DESC_M, **kw)


def _members(*names):
    return character_lib.resolve_cast([(None, n) for n in names])


SHOTS_OK = """# Forest Rescue

A ronin saves a woman from a robber on a forest trail.

## Characters
- "the woman in grey": a young woman with long black hair pinned up with jade hairpins wearing a grey kimono
- "the ronin": a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori
- "the bearded robber": a stocky man with a black beard in a ragged brown jacket

## Panel 1 — The Trail
Image: A medium shot of the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing in the centre of a mossy cedar trail and facing right. Far behind her on the left, small in the frame, the bearded robber watches from the ferns. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The woman in grey turns her head slowly toward the ferns on her right. The camera stays static.
Narration: She senses she is not alone.

## Panel 2 — The Robber
Image: A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing left. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The bearded robber lunges forward out of the ferns with his short knife raised. The camera stays static.
Narration: A robber springs from cover.

## Panel 3 — The Ronin
Image: A medium shot of the ronin, a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori, and the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing an arm's length apart on the mossy cedar trail, the ronin on the left facing right. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The ronin offers his open hand to the woman in grey. The camera stays static.
Narration: Help arrives.
"""
ROSTER_BLOCK = SHOTS_OK[SHOTS_OK.index("## Characters\n"):SHOTS_OK.index("## Panel 1")]


def _variant(old, new, text=None):
    """SHOTS_OK (or text) with the unique string old replaced by new."""
    text = SHOTS_OK if text is None else text
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _panels(tmp_path, text):
    """bin/ltx-story-manifest _parse_prompts_md panels for text."""
    path = tmp_path / "parse-me.md"
    path.write_text(text, encoding="utf-8")
    return story_manifest._parse_prompts_md(str(path))[1]


# --- S1-S20: character_lib (spec 3, 4) --------------------------------------------------
def test_s1_constants():
    assert character_lib.SHOTS_CHARACTER_STRENGTH == 0.8
    assert character_lib.SHOTS_MOTION_MIN_WORDS == 10
    assert character_lib.SHOTS_MOTION_MAX_WORDS == 25
    assert character_lib.SHOTS_MAX_CAST_PER_PANEL == 2
    assert character_lib.SHOTS_REWRITE_MAX_LISTED == 40
    assert character_lib.SHOTS_CLOSE_SHOT_TYPES == (
        "medium shot", "medium close-up", "close-up", "extreme close-up")


def test_s2_panel_strengths_in_shots_mode(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir, strength=0.6)
    m = _members("kyra", "ronin")
    strengths = character_lib.panel_strengths
    assert strengths(["kyra"], m, 0.8, shots=True) == {"kyra": 0.8}
    assert strengths(["kyra"], m, 0.7, shots=True) == {"kyra": 0.7}
    assert strengths(["ronin"], m, 0.8, shots=True) == {"ronin": 0.6}
    assert strengths(["kyra", "ronin"], m, 0.8, shots=True) == {"kyra": 0.8, "ronin": 0.6}
    assert strengths(["kyra"], m, 0.8) == {"kyra": 1.0}
    assert strengths([], m, 0.8, shots=True) == {}


def test_s3_shots_cast_block(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    m = _members("kyra", "ronin")
    lib = character_lib
    assert lib.build_cast_block(m, shots=True) == (
        lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
        + '- "the ronin": ' + DESC_R + "." + "\n" + lib.SHOTS_CAST_BLOCK_RULES)
    continuous = (lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
                  + '- "the ronin": ' + DESC_R + "." + "\n" + lib.CAST_BLOCK_RULES)
    assert lib.build_cast_block(m) == continuous
    assert lib.build_cast_block(m, shots=False) == continuous
    rules = lib.SHOTS_CAST_BLOCK_RULES
    assert "{" not in rules and "}" not in rules and "%" not in rules
    assert rules.count("word for word") == 2
    for fragment in ("at most two of these characters", "a medium shot or closer",
                     "never within arm's reach", "show it by cutting",
                     "an offered hand or a hand on an arm", "has none of these extra rules"):
        assert fragment in rules, fragment


def test_s4_find_phrases():
    find = character_lib.find_phrases
    assert find("The woman in grey nods to the woman.", ["the woman", "the woman in grey"]) == [
        "the woman in grey", "the woman"]
    assert find("THE RONIN bows.", ["the ronin"]) == ["the ronin"]
    assert find("the ronin's blade", ["the ronin"]) == ["the ronin"]
    assert find("the ronin-like man", ["the ronin"]) == []
    assert find("the bearded robber grabs the ronin; the ronin",
                ["the ronin", "the bearded robber"]) == ["the bearded robber", "the ronin"]
    assert find("", ["the ronin"]) == []


def _roster(*lines):
    """A minimal story whose Characters section holds lines, then one panel."""
    return ("# T\n\nA summary.\n\n## Characters\n" + "".join(l + "\n" for l in lines)
            + "\n## Panel 1 — A\nImage: x\n")


def test_s5_parse_character_roster():
    parse = character_lib.parse_character_roster
    entries = [("the woman in grey", DESC_K), ("the ronin", DESC_R),
               ("the bearded robber", "a stocky man with a black beard in a ragged brown jacket")]
    assert parse(SHOTS_OK) == (entries, [])
    assert parse(_roster("- “the ronin”: a man")) == ([("the ronin", "a man")], [])
    assert parse(_roster('* "the ronin": a man')) == ([("the ronin", "a man")], [])
    assert parse("# T\n\nA summary.\n\n## Panel 1 — A\nImage: x\n") == (
        [], ['no "## Characters" section'])
    assert parse(_roster('- "the monk": a man', "- the ronin: a man")) == (
        [("the monk", "a man")],
        ['line \'- the ronin: a man\' is not - "<referring phrase>": <description>'])
    with pytest.raises(character_lib.CharacterError) as info:
        character_lib.normalize_phrase("a b c d e f g")
    assert parse(_roster('- "the ronin": a man', '- "a b c d e f g": x')) == (
        [("the ronin", "a man")], [str(info.value)])
    assert parse(_roster('- "the ronin": a man', '- "The Ronin": a tall man')) == (
        [("the ronin", "a man")], ["phrase 'The Ronin' is listed more than once"])
    assert parse(_roster('- "the ronin": a man', "", '- "the monk": an old man')) == (
        [("the ronin", "a man"), ("the monk", "an old man")], [])
    assert parse(_roster('- "the ronin": a man') + '\n- "x y": z\n') == (
        [("the ronin", "a man")], [])
    assert parse("# T\n\nA summary.\n\n## Characters\n\n## Panel 1 — A\nImage: x\n") == (
        [], ['the "## Characters" section lists no characters'])
    late = _variant("A ronin saves a woman from a robber on a forest trail.",
                    "Three characters meet on a forest trail.",
                    SHOTS_OK.replace(ROSTER_BLOCK, "")) + "\n" + ROSTER_BLOCK
    assert late.index("## Characters") > late.index("## Panel 3")
    assert parse(late) == (entries, [])


TEN_WORDS = "The ronin slowly lowers his katana toward the mossy ground."
TWENTY_FIVE_WORDS = ("The ronin slowly lowers his curved katana toward the soft mossy ground beside "
                     "the old stone lantern near the quiet shrine at the trail's end.")


def test_s6_motion_problems_pass(tmp_path):
    assert len(TEN_WORDS.split()) == 10 and len(TWENTY_FIVE_WORDS.split()) == 25
    texts = [p["motion"] for p in _panels(tmp_path, SHOTS_OK)] + [
        "The ronin draws his katana from its scabbard in one smooth motion. The camera stays "
        "static.",
        "The woman in grey swings the cedar branch at the robber's knife hand.",
        TEN_WORDS,
        TWENTY_FIVE_WORDS,
        "Camera holds. The ronin kneels beside the fallen branch on the trail."]
    assert len(texts) == 8
    for text in texts:
        assert character_lib.motion_problems(text) == [], text


def test_s7_motion_problems_fail():
    problems = character_lib.motion_problems
    nine = "The ronin slowly lowers his katana toward the ground."
    twenty_six = TWENTY_FIVE_WORDS.replace("his curved", "his long curved")
    assert len(nine.split()) == 9 and len(twenty_six.split()) == 26
    assert problems(nine) == [("S4 motion length", "Motion: is 9 words; it must be 10-25")]
    assert problems(twenty_six) == [("S4 motion length", "Motion: is 26 words; it must be 10-25")]
    assert problems("The ronin draws his sword. The ronin strikes the bearded robber hard.") == [
        ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]
    assert problems("The ronin draws his sword; he strikes the bearded robber across the arm.") == [
        ("S5 one action", "Motion: contains a semicolon")]
    for word, shown in (("then", "then"), ("While", "while"), ("meanwhile", "meanwhile"),
                        ("simultaneously", "simultaneously"), ("afterwards", "afterwards"),
                        ("followed  by", "followed by"), ("as soon as", "as soon as")):
        if word == "While":
            text = ("While the ronin raises his katana the bearded robber stumbles back across "
                    "the mossy trail.")
        else:
            text = ("The ronin raises his katana %s the bearded robber stumbles back across the "
                    "mossy trail." % word)
        assert len(text.split()) == 14 + len(word.split()), text
        assert problems(text) == [("S5 one action", "Motion: chains actions with '%s'" % shown)], text
    assert problems("The ronin sprints in, and he draws his katana toward the robber.") == [
        ("S5 one action", "Motion: chains actions with ', and'")]
    assert problems("The camera pans slowly across the empty clearing toward the cedar trees.") == [
        ("S5 one action", "Motion: has 0 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]


def test_s8_motion_negative_controls():
    for text in ("The ronin crosses the strengthened rope bridge above the river gorge slowly.",
                 "The woman in grey kneels before the shrine and lowers her head."):
        assert character_lib.motion_problems(text) == [], text


def _cast_kyra_ronin(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    return _members("kyra", "ronin")


def _violations(tmp_path, text, members, expected_panels=3):
    return character_lib.shots_violations(text, _panels(tmp_path, text), expected_panels, members)


def test_s9_shots_ok_is_valid(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, SHOTS_OK, members) == []
    assert _violations(tmp_path, SHOTS_OK, []) == []


def test_s10_s1_panel_count(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, SHOTS_OK, members, expected_panels=4) == [
        "story: S1 panel count: expected exactly 4 panels, found 3"]


def test_s11_s2_roster_presence(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = SHOTS_OK.replace(ROSTER_BLOCK, "")
    assert "## Characters" not in text
    assert _violations(tmp_path, text, members) == [
        'story: S2 characters list: no "## Characters" section',
        "story: S2 characters list: cast phrase 'the woman in grey' (character kyra) is not listed",
        "story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]
    assert _violations(tmp_path, text, []) == []


def test_s12_s2_cast_phrase_missing(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant('- "the ronin": ' + DESC_R + "\n", "")
    assert _violations(tmp_path, text, members) == [
        "story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]


PANEL_2_IMAGE = ("Image: A medium close-up of the bearded robber, a stocky man with a black beard in "
                 "a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing "
                 "left. Soft overcast light, muted green palette, eye-level camera, photorealistic "
                 "film still.\n")


def test_s13_s3_fields(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, _variant(PANEL_2_IMAGE, ""), members) == [
        "panel 2: S3 fields: missing/empty Image: field"]
    text = _variant("Narration: Help arrives.\n", "Narration: Help arrives.\nPrompt: x\n")
    assert _violations(tmp_path, text, members) == [
        "panel 3: S3 fields: has a Prompt: field; shots mode expects Image:, Motion: and "
        "Narration:"]


PANEL_3_MOTION = "Motion: The ronin offers his open hand to the woman in grey. The camera stays static."


def test_s14_violations_name_panel_and_rule(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_3_MOTION, "Motion: The ronin offers his hand then pulls the woman in "
                                    "grey to her feet on the trail.")
    assert _violations(tmp_path, text, members) == [
        "panel 3: S5 one action: Motion: chains actions with 'then'"]


def test_s15_s6_cast_count(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    _monk(lib_dir)
    three = _members("kyra", "ronin", "monk")
    roster = _variant('- "the bearded robber":',
                      '- "the monk": ' + DESC_M + '\n- "the bearded robber":')
    in_image = _variant("eye-level camera, photorealistic film still.\nMotion: The ronin offers",
                        "eye-level camera, photorealistic film still. The monk, an old bald man "
                        "with a white beard wearing a saffron robe and wooden prayer beads, stands "
                        "behind them.\nMotion: The ronin offers", roster)
    s6 = ["panel 3: S6 cast count: the shot names 3 cast characters (kyra, monk, ronin); at most 2"]
    assert _violations(tmp_path, in_image, three) == s6
    in_motion = _variant(PANEL_3_MOTION, "Motion: The monk raises his hand toward the ronin and "
                                         "the woman in grey.", roster)
    assert _violations(tmp_path, in_motion, three) == s6
    assert _violations(tmp_path, SHOTS_OK, members) == []


PANEL_1_MOTION = ("Motion: The woman in grey turns her head slowly toward the ferns on her right. "
                  "The camera stays static.")


def test_s16_s7_cast_and_extra(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_1_MOTION, "Motion: The woman in grey pushes the bearded robber away from "
                                    "her with both hands.")
    assert _violations(tmp_path, text, members) == [
        "panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction"]
    assert _violations(tmp_path, SHOTS_OK, members) == []


def test_s17_s7_longest_phrase_claims_the_span(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant('- "the bearded robber": a stocky man with a black beard in a ragged brown '
                    'jacket\n',
                    '- "the bearded robber": a stocky man with a black beard in a ragged brown '
                    'jacket\n- "the woman": an old woman in a straw hat\n')
    text = _variant(PANEL_1_MOTION, "Motion: The woman in grey bows her head to the trail shrine "
                                    "slowly. The camera stays static.", text)
    assert character_lib.parse_character_roster(text)[0][-1] == (
        "the woman", "an old woman in a straw hat")
    assert _violations(tmp_path, text, members) == []


def test_s18_shots_advisories(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)

    def advise(text, cast=members):
        return character_lib.shots_advisories(_panels(tmp_path, text), cast)

    assert advise(SHOTS_OK) == []
    assert advise(_variant("grey kimono, standing in the centre", "grey robe, standing in the centre")) == [
        "panel 1: Image: names 'the woman in grey' but does not repeat character kyra's Cast "
        "description word for word; that still relies on the phrase and the stills LoRA alone"]
    assert advise(_variant("hairpins wearing a grey kimono, standing in the centre",
                           "hairpins   WEARING a grey kimono, standing in the centre")) == []
    assert advise(_variant("A medium shot of the woman in grey", "A wide shot of the woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is wide shot; a shot with "
        "a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium shot of the woman in grey", "The woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is not stated; a shot "
        "with a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium close-up of the bearded robber",
                           "A wide shot of the bearded robber")) == []
    assert advise(SHOTS_OK, cast=[]) == []


def test_s19_shots_rewrite_block():
    lib = character_lib
    block = lib.shots_rewrite_block(["a", "b", "c"], 14)
    assert block == lib.SHOTS_REWRITE_TEMPLATE % ("- a\n- b\n- c", 14)
    assert "Keep EXACTLY 14 panel sections." in block
    many = ["v%d" % i for i in range(1, 46)]
    listed = "\n".join(["- v%d" % i for i in range(1, 41)] + ["- ... and 5 more"])
    assert lib.shots_rewrite_block(many, 3) == lib.SHOTS_REWRITE_TEMPLATE % (listed, 3)
    assert lib.SHOTS_REWRITE_TEMPLATE.count("%") == 2


def test_s20_character_lib_imports():
    with open(os.path.join(WS, "character_lib.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names == {"collections", "datetime", "json", "os", "re", "uuid"}


# --- S60-S65: bin/ltx-story-manifest --shots (spec 5.9) ---------------------------------
S61_STORY = """# Shots cast test

The woman in grey meets the ronin on a forest trail.

## Characters
- "the woman in grey": %s
- "the ronin": %s

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a mossy cedar trail and facing right.
Motion: The woman in grey turns her head slowly toward the ferns on her right.
Narration: She listens.

## Panel 2 — Two
Image: A medium shot of the woman in grey and the ronin standing apart on the mossy trail.
Motion: The ronin bows his head slowly to her across the mossy trail.
Narration: He greets her.

## Panel 3 — Three
Image: A medium close-up of the woman in grey kneeling beside a small trail shrine.
Motion: She bows her head low to the shrine on the trail.
Narration: She prays.

## Panel 4 — Four
Image: A wide shot of the empty mossy cedar trail under grey clouds.
Motion: Leaves drift slowly across the empty trail in the cold wind.
Narration: The forest is quiet.
""" % (DESC_K, DESC_R)


def _shots_manifest_env(tmp_path, monkeypatch, text=SHOTS_OK, images=None):
    """A workspace root under tmp_path for bin/ltx-story-manifest (its module WS is patched),
    with character_lib.py symlinked in so _character_lib() loads the real module, the
    story.md, and one 64x64 PNG per panel (or images PNGs). Returns (story_md, [image], ws)."""
    from PIL import Image
    ws = tmp_path / "ws"
    ws.mkdir()
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / "story.md"
    story_md.write_text(text, encoding="utf-8")
    count = images if images is not None else len(_panels(tmp_path, text))
    paths = []
    for i in range(1, count + 1):
        path = str(tmp_path / ("panel_%02d.png" % i))
        Image.new("RGB", (64, 64), (20 * i, 90, 90)).save(path)
        paths.append(path)
    return str(story_md), paths, str(ws)


def _shots_manifest_argv(story_id, story_md, images, *extra):
    argv = ["--story-id", story_id, "--prompts-md", story_md, "--shots"]
    for image in images:
        argv += ["--image", image]
    return argv + ["--fps", "24", "--target-seconds", repr(145 * len(images) / 24.0),
                   "--min-frames", "145", "--max-frames", "145", "--force"] + list(extra)


def _shots_manifest(ws, story_id):
    path = os.path.join(ws, "generated", "stories", story_id, "manifest.json")
    with open(path) as f:
        return json.load(f)


def _names_strengths(panel):
    return [(c["name"], c["strength"]) for c in panel["characters"]]


def test_s60_shots_manifest_uncast(tmp_path, monkeypatch, capsys):
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_shots_manifest_argv("s60", story_md, images)) == 0
    out = capsys.readouterr().out
    manifest = _shots_manifest(ws, "s60")
    parsed = _panels(tmp_path, SHOTS_OK)
    assert manifest["schema_version"] == 3
    assert len(manifest["panels"]) == 3
    for panel, image, pt in zip(manifest["panels"], images, parsed):
        assert panel["conditioning"] == "still"
        assert panel["image_path"] == os.path.abspath(image)
        assert panel["panel_text"] == pt["image"]
        assert panel["motion_prompt"] == pt["motion"]
        assert "characters" not in panel
    assert "(chained)" not in out


def test_s61_shots_cast_names_come_from_image_and_motion(tmp_path, monkeypatch, capsys, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    assert story_manifest.main(_shots_manifest_argv("uncast", story_md, images)) == 0
    capsys.readouterr()
    assert story_manifest.main(_shots_manifest_argv(
        "cast", story_md, images, "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8")) == 0
    out = capsys.readouterr().out
    cast, uncast = _shots_manifest(ws, "cast")["panels"], _shots_manifest(ws, "uncast")["panels"]
    assert [_names_strengths(p) for p in cast] == [
        [("kyra", 0.8)], [("kyra", 0.8), ("ronin", 0.8)], [("kyra", 0.8)], []]
    assert "the kyrawmn woman in grey" in cast[0]["motion_prompt"].lower()
    assert "the roninmn ronin" in cast[1]["motion_prompt"].lower()
    assert "kyrawmn" not in cast[1]["motion_prompt"]
    assert cast[2]["motion_prompt"] == "She bows her head low to the shrine on the trail."
    assert [p["panel_text"] for p in cast] == [p["panel_text"] for p in uncast]
    assert "cast: panel 1: kyra@0.8" in out.splitlines()


def test_s62_shots_strength_overrides(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir, strength=0.5)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    cast = ["--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin"]
    assert story_manifest.main(_shots_manifest_argv(
        "s06", story_md, images, *(cast + ["--character-strength", "0.6"]))) == 0
    panels = _shots_manifest(ws, "s06")["panels"]
    assert _names_strengths(panels[0]) == [("kyra", 0.6)]
    assert _names_strengths(panels[1]) == [("kyra", 0.6), ("ronin", 0.5)]
    assert story_manifest.main(_shots_manifest_argv("default", story_md, images, *cast)) == 0
    assert _names_strengths(_shots_manifest(ws, "default")["panels"][0]) == [("kyra", 0.8)]
    chain = ["--story-id", "chain", "--prompts-md", story_md, "--chain", "--image", images[0],
             "--fps", "24", "--target-seconds", repr(145 * 4 / 24.0), "--min-frames", "145",
             "--max-frames", "145", "--force"] + cast
    assert story_manifest.main(chain) == 0
    assert _names_strengths(_shots_manifest(ws, "chain")["panels"][0]) == [("kyra", 1.0)]


def test_s63_shots_manifest_errors(tmp_path, monkeypatch, capsys):
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    manifest = os.path.join(ws, "generated", "stories", "bad", "manifest.json")
    exclusive = "--shots is mutually exclusive with --chain, --glob and --no-images"
    for extra in (["--chain"], ["--no-images"], ["--glob", "panel_*.png"]):
        with pytest.raises(SystemExit) as info:
            story_manifest.main(_shots_manifest_argv("bad", story_md, images, *extra))
        assert info.value.code == 2
        assert exclusive in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--shots", "--image", images[0]])
    assert info.value.code == 2
    assert "--shots requires --prompts-md" in capsys.readouterr().err
    assert story_manifest.main(_shots_manifest_argv("bad", story_md, images[:2])) == 2
    assert capsys.readouterr().err == (
        "Error: prompts.md has 3 panels but 2 images were selected\n")
    cases = [
        (_variant(PANEL_2_IMAGE, ""),
         "Error: --shots requires every panel to have a non-empty Image: field; panel 2 has none\n"),
        (_variant(PANEL_3_MOTION + "\n", ""),
         "Error: --shots requires every panel to have a non-empty Motion: field; panel 3 has none\n"),
        (_variant("Narration: She senses she is not alone.\n",
                  "Narration: She senses she is not alone.\nPrompt: x\n"),
         "Error: --shots does not accept Prompt: fields; panel 1 has one\n"),
    ]
    for text, message in cases:
        with open(story_md, "w", encoding="utf-8") as f:
            f.write(text)
        assert story_manifest.main(_shots_manifest_argv("bad", story_md, images)) == 2
        assert capsys.readouterr().err == message
    assert not os.path.exists(manifest)


def test_s64_cast_requires_chain_or_shots(tmp_path, monkeypatch, capsys, lib_dir):
    _kyra(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--prompts-md", story_md, "--image", images[0],
                             "--cast", "the woman in grey=kyra"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "--cast requires --chain or --shots" in err
    assert "--cast requires --chain" in err


def test_s65_unused_cast_phrase_warning_names_image_and_motion(tmp_path, monkeypatch, capsys,
                                                               lib_dir):
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_shots_manifest_argv(
        "s65", story_md, images, "--cast", "the stranger=ronin")) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Image: or "
            "Motion: text; that character gets no LoRA") in capsys.readouterr().out
    chain = ["--story-id", "s65c", "--prompts-md", story_md, "--chain", "--image", images[0],
             "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
             "--max-frames", "145", "--force", "--cast", "the stranger=ronin"]
    assert story_manifest.main(chain) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Motion: "
            "text; that character gets no LoRA") in capsys.readouterr().out


# --- S70-S72: bin/ltx-story-images --shots (spec 5.10) ----------------------------------
class _FakeContentSafetyError(Exception):
    pass


def _fake_zimage_shots(monkeypatch):
    """Fake torch, z_image_skill and content_safety modules in sys.modules (a fresh copy of
    the tests/test_casting_pipeline.py P30 harness). Returns (calls, seeds): the
    (prompt, kwargs) of every generate_image call and every manual_seed(n) value."""
    calls, seeds = [], []

    class _Generator(object):
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            seeds.append(seed)
            return self

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = lambda prompt, **kwargs: calls.append((prompt, kwargs))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _FakeContentSafetyError
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    return calls, seeds


def _images_story(tmp_path):
    story_md = tmp_path / "story.md"
    story_md.write_text(SHOTS_OK, encoding="utf-8")
    return str(story_md)


def _images_json(out_dir):
    with open(os.path.join(out_dir, "images.json")) as f:
        return json.load(f)


def test_s70_lone_stills_lora_is_0_8_in_shots_mode(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    calls, _seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    out_dir = str(tmp_path / "shots")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra", "--shots"]) == 0
    assert len(calls) == 1
    assert calls[0][1]["loras"] == [(stills, 0.8)]
    assert _images_json(out_dir)["panels"][0]["loras"][0]["strength"] == 0.8
    out_dir = str(tmp_path / "chained")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    assert calls[1][1]["loras"] == [(stills, 1.0)]
    assert _images_json(out_dir)["panels"][0]["loras"][0]["strength"] == 1.0


def test_s71_shots_pins_the_seed(tmp_path, monkeypatch):
    _calls, seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    assert _panels(tmp_path, SHOTS_OK)[0]["style"] == ""
    assert story_images.main(["--story-md", story_md, "--out-dir", str(tmp_path / "a"),
                              "--only", "2,3", "--seed", "0", "--shots"]) == 0
    assert seeds == [0, 0]
    del seeds[:]
    assert story_images.main(["--story-md", story_md, "--out-dir", str(tmp_path / "b"),
                              "--only", "2,3", "--seed", "0"]) == 0
    assert seeds == [2, 3]


def test_s72_shots_without_cast(tmp_path, monkeypatch):
    calls, seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    out_dir = str(tmp_path / "images")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2",
                              "--seed", "7", "--shots"]) == 0
    assert len(calls) == 2
    assert all("loras" not in kwargs for _prompt, kwargs in calls)
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])
    assert seeds == [7, 7]


# --- S66: bin/ltx-mlx-render renders a shots manifest unchanged (spec 1.2) ---------------
class _ShotsRenderHarness(object):
    """render.main() in-process with generate_video, probe_streams, assert_clips_uniform,
    build_concat_command and clip_frame_count stubbed and the story dir under tmp_path (a
    fresh copy of the tests/test_casting_pipeline.py P9 harness). generate_video raises
    Ltx2MlxError for every panel in fail; every other stub render writes 128 bytes unique to
    that call."""

    def __init__(self, monkeypatch, directory, manifest, fail=()):
        self.dir = str(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.manifest = manifest
        self.received = []
        self.renders = [0]
        self.model = os.path.join(self.dir, "model-fixture")
        os.makedirs(self.model, exist_ok=True)
        with open(os.path.join(self.model, "split_model.json"), "w") as f:
            json.dump({"recipe": "ltx-2.5"}, f)
        self.clips = os.path.join(self.dir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(self.dir, "movie.mp4")
        fake_bin = os.path.join(self.dir, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.renders[0] += 1
            index = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            harness.received.append((index, image_path, kw))
            if index in fail:
                raise SKILL.Ltx2MlxError("stub failure for panel %d" % index, returncode=1)
            with open(output_path, "wb") as f:
                f.write(("render %d" % harness.renders[0]).encode().ljust(128, b"\0"))
            return os.path.abspath(output_path)

        monkeypatch.setattr(render.SKILL, "generate_video", _gen)
        monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
        monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
        monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
        monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out])
        monkeypatch.setattr(render, "clip_frame_count", lambda p: 241)
        monkeypatch.setattr(render, "story_dir_for",
                            lambda sid: os.path.join(harness.dir, "stories", sid))

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model, "--width", "512",
                            "--height", "512"] + list(extra))

    def newest_summary(self, story_id):
        paths = glob.glob(os.path.join(self.dir, "stories", story_id, "runs", "*",
                                       "story_summary.json"))
        with open(max(paths, key=os.path.getmtime)) as f:
            return json.load(f)


def test_s66_render_accepts_the_shots_manifest(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    assert story_manifest.main(_shots_manifest_argv(
        "cast", story_md, images, "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8")) == 0
    path = os.path.join(ws, "generated", "stories", "cast", "manifest.json")
    manifest = render.load_manifest(path)
    units = render.build_units(manifest["panels"], 0, str(tmp_path / "clips"))
    assert [u["conditioning"] for u in units] == ["still"] * 4
    assert [u["chain_source"] for u in units] == [None] * 4
    assert [u["image_path"] for u in units] == [os.path.abspath(i) for i in images]
    h = _ShotsRenderHarness(monkeypatch, tmp_path / "run", path, fail=(2,))
    assert h.run("--on-panel-failure", "skip", "--retry-failed", "0") == 1
    assert [index for index, _image, _kw in h.received] == [1, 2, 3, 4]
    assert [image for _index, image, _kw in h.received] == [os.path.abspath(i) for i in images]
    summary = h.newest_summary("cast")
    assert [u["status"] for u in summary["units"]] == ["ok", "error", "ok", "ok"]
    assert summary["stopped_reason"] is None
    assert summary["skipped_panels"] == [2]
    assert [os.path.basename(c) for c in summary["clips"]] == [
        "panel_01.mp4", "panel_03.mp4", "panel_04.mp4"]


# --- S30-S34: bin/ltx-movie arguments, _resolve_shots, the template (spec 5.1-5.3) -------
ANCHOR = "\n\nHow this movie is made:"


@pytest.fixture
def movie_ws(tmp_path, monkeypatch):
    """ltx_movie.WS -> tmp_path/ws (spec 10.1). bin/ and character_lib.py are symlinked to the
    real workspace, so the sub-tool commands and the character_lib loader in bin/ltx-movie still
    read the real files while every story dir lands under tmp_path/ws/generated/stories.
    ltx_image_fit.py and ltx2_mlx_video_skill.py are not linked: --seed-image and --lora fail here."""
    ws = tmp_path / "ws"
    (ws / "generated" / "stories").mkdir(parents=True)
    os.symlink(os.path.join(WS, "bin"), str(ws / "bin"))
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(ltx_movie, "WS", str(ws))
    return ws


def _story_dir_with(movie_ws, story_id, text=None):
    """<ws>/generated/stories/<story_id>, created, with story.md = text when given."""
    directory = movie_ws / "generated" / "stories" / story_id
    directory.mkdir(parents=True, exist_ok=True)
    if text is not None:
        (directory / "story.md").write_text(text, encoding="utf-8")
    return directory


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    return args


def _shots_args(*argv):
    """parse_args, then _resolve_shots and _resolve_casting exactly as main() runs them (both
    must return 0), with main()'s default 704x448 geometry."""
    args = _movie_args(*argv)
    assert ltx_movie._resolve_shots(args) == 0
    assert ltx_movie._resolve_casting(args) == 0
    return args


def _all_files(root):
    return sorted(os.path.join(d, f) for d, _dirs, files in os.walk(str(root)) for f in files)


def test_s30_parser_flags():
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"])
    assert args.shots is False
    assert args.redo is None
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x", "--shots", "--redo", "3,1"])
    assert args.shots is True
    assert args.redo == "3,1"
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    assert "--shots" in helptext and "--redo" in helptext
    for fragment in ("145 frames @ 24 fps = 6.04s per clip.", "6.04s per panel at the defaults",
                     "number of chained clips; panel 1 also gets the movie's one still image; "
                     "mutually exclusive with --length",
                     "every clip after the first continues from the previous clip's last frame"):
        assert fragment in helptext, fragment


def test_s31_shots_story_prompt():
    template = ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS
    plain = ltx_movie.build_story_prompt("N", "sid", 14, seconds="6", shots=True)
    assert plain == template.format(narrative="N", story_id="sid", panels=14, seconds="6")
    cast = ltx_movie.build_story_prompt("N", "sid", 14, seconds="6", cast_block="CAST", shots=True)
    assert cast == plain.replace(ANCHOR, "\n\nCAST" + ANCHOR)
    assert "\n\nCAST" + ANCHOR in cast
    fields = {f for _text, f, _spec, _conv in string.Formatter().parse(template) if f is not None}
    assert fields == {"story_id", "narrative", "seconds", "panels"}
    assert template.count(ANCHOR) == 1
    for fragment in ("sequence of separate shots joined by cuts", "## Characters", "10-25 words",
                     "ONE physical action", "never use a semicolon",
                     "EXACTLY {panels} panel sections"):
        assert fragment in template, fragment


def test_s32_non_shots_prompts_are_unchanged():
    build = ltx_movie.build_story_prompt
    for no_stills in (False, True):
        for seed_image in (False, True):
            assert build("N", "sid", 14, no_stills, seed_image, seconds="6", shots=False) == build(
                "N", "sid", 14, no_stills, seed_image, seconds="6")
    assert build("N", "sid", 14, seconds="6") == ltx_movie.STORY_PROMPT_TEMPLATE.format(
        narrative="N", story_id="sid", panels=14, seconds="6")


def test_s33_resolve_shots_errors(tmp_path, movie_ws, capsys):
    seed = tmp_path / "seed.png"
    seed.write_bytes(b"png")
    _story_dir_with(movie_ws, "has-story", SHOTS_OK)
    missing = os.path.join(str(movie_ws), "generated", "stories", "no-story", "story.md")
    base = ["n", "--story-id", "has-story", "--panels", "14"]
    malformed = "Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; got %r"
    cases = [
        (base + ["--redo", "3"], "Error: --redo requires --shots"),
        (base + ["--shots", "--no-stills"],
         "Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills"),
        (base + ["--shots", "--seed-image", str(seed)],
         "Error: --shots is not supported with --seed-image: the seed image can be only panel 1's "
         "still, and the seed-image story preface describes the chained flow"),
        (base + ["--shots", "--redo", "x"], malformed % "x"),
        (base + ["--shots", "--redo", "3.0"], malformed % "3.0"),
        (base + ["--shots", "--redo", ""], malformed % ""),
        (base + ["--shots", "--redo", ","], malformed % ","),
        (base + ["--shots", "--redo", "0"], "Error: --redo panel 0 is out of range (1..14)"),
        (base + ["--shots", "--redo", "15"], "Error: --redo panel 15 is out of range (1..14)"),
        (base + ["--shots", "--redo", "-1"], "Error: --redo panel -1 is out of range (1..14)"),
        (base + ["--shots", "--redo", "2", "--force-story"],
         "Error: --redo cannot be combined with --force-story: --force-story writes a new "
         "story.md, so every panel changes"),
        (base + ["--shots", "--redo", "2", "--story-only"],
         "Error: --redo cannot be combined with --story-only: --story-only stops before the "
         "stills and clips that --redo re-renders"),
        (base + ["--shots", "--redo", "x", "--force-story"],
         "Error: --redo cannot be combined with --force-story: --force-story writes a new "
         "story.md, so every panel changes"),
        (base + ["--shots", "--redo", "99", "--story-only"],
         "Error: --redo cannot be combined with --story-only: --story-only stops before the "
         "stills and clips that --redo re-renders"),
        (["n", "--story-id", "no-story", "--panels", "14", "--shots", "--redo", "2"],
         "Error: --redo needs an existing story.md: %s" % missing),
    ]
    before = _all_files(tmp_path)
    for argv, message in cases:
        args = _movie_args(*argv)
        assert ltx_movie._resolve_shots(args) == 2, argv
        assert capsys.readouterr().err == message + "\n", argv
        assert args.redo_panels == []
    args = _movie_args(*(base + ["--shots", "--redo", "3, 1,3"]))
    assert ltx_movie._resolve_shots(args) == 0
    assert args.redo_panels == [1, 3]
    args = _movie_args(*(base + ["--shots"]))
    assert ltx_movie._resolve_shots(args) == 0
    assert args.redo_panels == []
    assert capsys.readouterr().err == ""
    assert _all_files(tmp_path) == before


def test_s34_resolve_casting_in_shots_mode(movie_ws, lib_dir, monkeypatch, capsys):
    _kyra(lib_dir)
    members = _members("kyra")
    args = _shots_args("n", "--story-id", "new", "--shots", "--character", "kyra")
    assert args.character_strength == 0.8
    assert args.cast_block == character_lib.build_cast_block(members, shots=True)
    assert args.cast_block.endswith("\n" + character_lib.SHOTS_CAST_BLOCK_RULES)
    args = _shots_args("n", "--story-id", "new", "--character", "kyra")
    assert args.cast_block == character_lib.build_cast_block(members)
    # main() runs _resolve_shots before _resolve_casting (spec 5.1), and both
    # build_story_prompt call sites pass shots= (spec 5.2).
    assert ltx_movie.main(["n", "--story-id", "w1", "--shots", "--no-stills", "--character",
                           "kyra", "--dry-run", "--no-review"]) == 2
    assert capsys.readouterr().err == ("Error: --shots needs Phase 2's per-panel stills; it "
                                       "cannot be combined with --no-stills\n")
    assert ltx_movie.main(["n", "--story-id", "w2", "--shots", "--panels", "4", "--dry-run",
                           "--no-review"]) == 0
    assert "sequence of separate shots joined by cuts" in capsys.readouterr().out
    assert ltx_movie.main(["n", "--story-id", "w2", "--panels", "4", "--dry-run",
                           "--no-review"]) == 0
    assert "sequence of separate shots joined by cuts" not in capsys.readouterr().out
    # The shots branch of the default strength, made visible while
    # SHOTS_CHARACTER_STRENGTH == DEFAULT_CHARACTER_STRENGTH.
    real_lib = ltx_movie._character_lib

    def lib_with_distinct_shots_strength():
        lib = real_lib()
        monkeypatch.setattr(lib, "SHOTS_CHARACTER_STRENGTH", 0.6)
        return lib

    monkeypatch.setattr(ltx_movie, "_character_lib", lib_with_distinct_shots_strength)
    assert _shots_args("n", "--story-id", "w4", "--shots", "--character",
                       "kyra").character_strength == 0.6
    assert _shots_args("n", "--story-id", "w4", "--character", "kyra").character_strength == 0.8
    monkeypatch.setattr(ltx_movie, "_character_lib", real_lib)

    class Stop(Exception):
        pass

    seen = []

    def record(*_args, **kwargs):
        seen.append(kwargs.get("shots"))
        raise Stop

    _story_dir_with(movie_ws, "w3")
    monkeypatch.setattr(ltx_movie, "build_story_prompt", record)
    with pytest.raises(Stop):
        ltx_movie.phase1_story(_shots_args("n", "--story-id", "w3", "--shots"))
    with pytest.raises(Stop):
        ltx_movie.phase1_story(_shots_args("n", "--story-id", "w3"))
    assert seen == [True, False]


# --- S35-S41: shots-mode Phase 1 and the one rewrite (spec 5.4) --------------------------
BAD = _variant("Motion: The bearded robber lunges forward out of the ferns with his short knife "
               "raised. The camera stays static.", "Motion: The bearded robber lunges then slashes.")
BAD_VIOLATIONS = ["panel 2: S4 motion length: Motion: is 6 words; it must be 10-25",
                  "panel 2: S5 one action: Motion: chains actions with 'then'"]
PARAPHRASED = _variant("grey kimono, standing in the centre", "grey robe, standing in the centre")
S7_BAD = _variant("Motion: The bearded robber lunges forward out of the ferns with his short knife "
                  "raised.", "Motion: The ronin lunges forward out of the ferns toward the bearded "
                  "robber with his katana raised.")
SHOTS_ARGV = ["n", "--story-id", "shots", "--shots", "--character", "kyra", "--character",
              "ronin", "--panels", "3", "--no-review"]


class _FakeStoryAgent(object):
    """subprocess.Popen stand-in for bin/qwen-agent (spec 10.1): records each cmd and whether
    story.md existed at call time, writes the next queued story text to story.md (None writes
    nothing), and exits with the next queued return code (default 0). An unexpected extra
    call pops an empty queue and raises IndexError."""

    def __init__(self, monkeypatch, story_md, stories, returncodes=()):
        self.story_md = story_md
        self.stories = list(stories)
        self.returncodes = list(returncodes)
        self.calls = []
        monkeypatch.setattr(ltx_movie.subprocess, "Popen", self)

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), "existed": os.path.exists(self.story_md)})
        text = self.stories.pop(0)
        if text is not None:
            with open(self.story_md, "w", encoding="utf-8") as f:
                f.write(text)
        proc = types.SimpleNamespace(
            returncode=self.returncodes.pop(0) if self.returncodes else 0,
            communicate=lambda timeout=None: ("", None))
        return proc


def _phase1_env(movie_ws, lib_dir, story=None):
    """kyra and ronin in the library and the story dir "shots" (with story.md = story when
    given). Returns (story dir, story.md path)."""
    _kyra(lib_dir)
    _ronin(lib_dir)
    directory = _story_dir_with(movie_ws, "shots", story)
    return directory, str(directory / "story.md")


def _rejected(directory):
    return sorted(glob.glob(os.path.join(str(directory), "story.rejected-*.md")))


def test_s35_valid_first_draft(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert _rejected(directory) == []
    assert "has an Image: field, which is ignored" not in capsys.readouterr().out


def test_s36_one_rewrite(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    first, second = agent.calls[0]["cmd"], agent.calls[1]["cmd"]
    assert agent.calls[1]["existed"] is False
    assert second[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3)
    assert second[:-1] == first[:-1]
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert re.fullmatch(r"story\.rejected-\d{8}T\d{6}Z-%d\.md" % os.getpid(),
                        os.path.basename(rejected[0]))
    with open(rejected[0], encoding="utf-8") as f:
        assert f.read() == BAD
    assert (directory / "story_prompt.rewrite.txt").read_text(encoding="utf-8") == second[-1]
    assert (directory / "story_prompt.txt").read_text(encoding="utf-8") == first[-1]
    lines = out.splitlines()
    runs = [line.split(":")[0] for line in lines if line.startswith("Running (timeout ")]
    assert len(runs) == 2 and runs[0] == runs[1]
    warning = next(i for i, line in enumerate(lines)
                   if line.startswith("Warning: the story model's draft broke the shot rules; "
                                      "moving it to %s and asking for one rewrite:" % rejected[0]))
    assert lines[warning + 1:warning + 3] == ["  - " + v for v in BAD_VIOLATIONS]


def test_s37_second_failure_exits_2(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: story.md still breaks the shot rules after one rewrite:" in err
    for v in BAD_VIOLATIONS:
        assert "  - " + v in err.splitlines()
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert rejected[0] in err
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == BAD


def test_s38_existing_story_is_never_rewritten(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir, story=BAD)
    agent = _FakeStoryAgent(monkeypatch, story_md, [])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert agent.calls == []
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == BAD
    assert _rejected(directory) == []
    assert err.startswith("Error: story.md breaks the shot rules:\n")
    assert "pass --force-story" in err
    assert err.splitlines()[1:3] == ["  - " + v for v in BAD_VIOLATIONS]
    (directory / "story.md").write_text(S7_BAD, encoding="utf-8")
    assert ltx_movie.phase1_story(_shots_args(*(SHOTS_ARGV[:-2] + ["4", "--no-review"]))) == 2
    err = capsys.readouterr().err
    assert err.splitlines()[1:3] == [
        "  - story: S1 panel count: expected exactly 4 panels, found 3",
        "  - panel 2: S7 cast and extra: Motion: names 'the ronin' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction"]
    assert agent.calls == []


def test_s39_rewrite_agent_failure(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, None], returncodes=[0, 1])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: qwen-agent exited 1 while authoring story.md" in err
    assert "Error: the shots rewrite failed; the rejected first draft is kept at " in err
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert os.path.isfile(rejected[0])
    agent = _FakeStoryAgent(monkeypatch, story_md, [None])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    assert "Error: qwen-agent exited 0 without writing %s" % story_md in capsys.readouterr().err
    assert _rejected(directory) == rejected
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, None])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: qwen-agent exited 0 without writing %s" % story_md in err
    assert "Error: the shots rewrite failed; the rejected first draft is kept at " in err


def test_s40_advisories_are_not_fatal(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert ("Warning: panel 1: Image: names 'the woman in grey' but does not repeat"
            in capsys.readouterr().out)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, PARAPHRASED])
    gate = []
    monkeypatch.setattr("builtins.input", lambda prompt="": gate.append(prompt) or "")
    argv = [a for a in SHOTS_ARGV if a != "--no-review"] + ["--force-story"]
    assert ltx_movie.phase1_story(_shots_args(*argv)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    assert gate == ["Review story.md above. Enter to continue, Ctrl-C to abort: "]
    dump = out.index("=== story.md ===\n" + PARAPHRASED)
    assert out.index("Warning: panel 1: Image: names 'the woman in grey' but does not repeat") > dump


CHAINED_STORY = """# Chained

A continuous take.

## Panel 1 — One
Image: A medium shot of a woman standing on a forest trail and facing right.
Motion: She turns her head slowly toward the trees.
Narration: She listens.

## Panel 2 — Two
Motion: She draws then strikes; then he falls.
Narration: It is over.
"""


def test_s41_continuous_mode_unaffected(monkeypatch, movie_ws):
    directory = _story_dir_with(movie_ws, "chained", CHAINED_STORY)
    agent = _FakeStoryAgent(monkeypatch, str(directory / "story.md"), [])
    args = _shots_args("n", "--story-id", "chained", "--panels", "2", "--no-review")
    assert ltx_movie.phase1_story(args) == 0
    assert agent.calls == []


# --- S42-S45: shots-mode Phase 2 stills groups (spec 5.5) ---------------------------------
GROUP_STORY = """# Groups

Five shots on a forest trail.

## Characters
- "the woman in grey": %s
- "the ronin": %s

## Panel 1 — One
Image: A medium shot of the woman in grey standing on the mossy trail.
Motion: The woman in grey turns her head slowly toward the ferns on her right.
Narration: One.

## Panel 2 — Two
Image: A medium shot of the ronin standing under a tall cedar.
Motion: The ronin turns his head slowly toward the ferns on his left side.
Narration: Two.

## Panel 3 — Three
Image: A medium shot of the woman in grey and the ronin standing apart on the trail.
Motion: The ronin offers his open hand to the woman in grey on the trail.
Narration: Three.

## Panel 4 — Four
Image: A wide shot of the empty mossy trail under grey clouds.
Motion: The ronin walks slowly along the empty trail toward the distant shrine.
Narration: Four.

## Panel 5 — Five
Image: A close-up of the woman in grey under the cedars.
Motion: The woman in grey closes her eyes slowly and lowers her chin a little.
Narration: Five.
""" % (DESC_K, DESC_R)
GROUPS = [((), [4]), (("kyra",), [1, 5]), (("ronin",), [2]), (("kyra", "ronin"), [3])]


class _StillsRunner(object):
    """ltx_movie._stream_and_tee stand-in (spec 10.1): records (cmd, log_path), writes a 1x1
    PNG for every --only panel when the queued rc is 0 and write_pngs is true, and returns
    the next queued rc (default 0). It asserts the log's directory already exists, as the real
    _stream_and_tee needs. It also makes any real subprocess call from bin/ltx-movie
    fail the test, so no Z-Image process can ever start."""

    def __init__(self, monkeypatch, returncodes=(), write_pngs=True):
        self.returncodes = list(returncodes)
        self.write_pngs = write_pngs
        self.runs = []

        def _forbidden(*args, **kwargs):
            raise AssertionError("Phase 2 made a real subprocess call")

        monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)
        monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
        monkeypatch.setattr(ltx_movie, "_stream_and_tee", self)

    def __call__(self, cmd, log_path):
        from PIL import Image
        assert os.path.isdir(os.path.dirname(log_path)), log_path
        self.runs.append((list(cmd), log_path))
        rc = self.returncodes.pop(0) if self.returncodes else 0
        if rc == 0 and self.write_pngs:
            out_dir = cmd[cmd.index("--out-dir") + 1]
            os.makedirs(out_dir, exist_ok=True)
            for i in cmd[cmd.index("--only") + 1].split(","):
                Image.new("RGB", (1, 1), (0, 0, 0)).save(
                    os.path.join(out_dir, "panel_%02d.png" % int(i)))
        return rc


def _group_args(movie_ws, lib_dir, story_id="groups"):
    """kyra and ronin (both with stills LoRAs), the GROUP_STORY story dir, and resolved args for
    --shots --character kyra --character ronin --panels 5."""
    _kyra(lib_dir)
    _ronin(lib_dir)
    _story_dir_with(movie_ws, story_id, GROUP_STORY)
    return _shots_args("n", "--story-id", story_id, "--shots", "--character", "kyra",
                       "--character", "ronin", "--panels", "5", "--no-review")


def _plain_phase2_cmd(monkeypatch, args):
    """The non-shots Phase 2 command for the same args (spec S43), recorded from
    phase2_stills with args.shots False and subprocess.run stubbed."""
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0))
    args.shots = False
    try:
        assert ltx_movie.phase2_stills(args) == 0
    finally:
        args.shots = True
    assert len(runs) == 1
    return runs[0]


def _stills_path(lib_dir, name):
    return os.path.join(lib_dir, name, "lora", "stills.safetensors")


def test_s42_stills_groups(tmp_path, movie_ws, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story = _story_dir_with(movie_ws, "groups", GROUP_STORY) / "story.md"
    assert ltx_movie._shots_stills_groups(str(story), _members("kyra", "ronin")) == GROUPS
    assert ltx_movie._shots_stills_groups(str(story), []) == [((), [1, 2, 3, 4, 5])]
    _ronin(lib_dir, stills=False)
    assert ltx_movie._shots_stills_groups(str(story), _members("kyra", "ronin")) == [
        ((), [2, 4]), (("kyra",), [1, 3, 5])]
    make_character(lib_dir, "mira", "miragrl", "the woman", "girl",
                   "an old woman with grey hair in a straw hat and a brown travelling cloak",
                   stills=False)
    nested = _story_dir_with(movie_ws, "nested", (
        "# Nested\n\nTwo shots.\n\n## Panel 1 — One\nImage: A medium shot of the woman in grey.\n"
        "Motion: The woman in grey turns her head slowly toward the ferns on her right.\n"
        "Narration: One.\n\n## Panel 2 — Two\nImage: A medium shot of the woman.\n"
        "Motion: The woman turns her head slowly toward the ferns on her right side.\n"
        "Narration: Two.\n")) / "story.md"
    assert ltx_movie._shots_stills_groups(str(nested), _members("kyra", "mira")) == [
        ((), [2]), (("kyra",), [1])]


def test_s43_phase2_runs_one_process_per_group(monkeypatch, movie_ws, lib_dir, capsys):
    args = _group_args(movie_ws, lib_dir)
    base = _plain_phase2_cmd(monkeypatch, args)
    assert base[-4:] == ["--cast", "the ronin=ronin", "--character-strength", "0.8"]
    runner = _StillsRunner(monkeypatch)
    assert ltx_movie.phase2_stills(args) == 0
    at = base.index("--only") + 1
    images_dir = os.path.join(str(movie_ws), "generated", "stories", "groups", "images")
    assert [cmd for cmd, _log in runner.runs] == [
        base[:at] + [only] + base[at + 1:] + ["--shots"] for only in ("4", "1,5", "2", "3")]
    assert [log for _cmd, log in runner.runs] == [
        os.path.join(images_dir, "stills-group-%02d.log" % k) for k in (1, 2, 3, 4)]
    capsys.readouterr()
    del runner.runs[:]
    assert ltx_movie.phase2_stills(args) == 0
    assert runner.runs == []
    out = capsys.readouterr().out
    assert out.count("every still exists; skipped") == 4
    assert "stills group 1/4 (no character LoRAs; panels 4): every still exists; skipped\n" in out
    assert "will be reused as-is" not in out
    os.remove(os.path.join(images_dir, "panel_02.png"))
    assert ltx_movie.phase2_stills(args) == 0
    assert len(runner.runs) == 1
    cmd = runner.runs[0][0]
    assert cmd[cmd.index("--only") + 1] == "2"
    del runner.runs[:]
    os.remove(os.path.join(images_dir, "panel_05.png"))
    assert ltx_movie.phase2_stills(args) == 0
    assert [c[c.index("--only") + 1] for c, _log in runner.runs] == ["1,5"]


def test_s44_failing_group_stops_phase2(monkeypatch, movie_ws, lib_dir, capsys):
    args = _group_args(movie_ws, lib_dir)
    runner = _StillsRunner(monkeypatch, returncodes=[0, 1])
    assert ltx_movie.phase2_stills(args) == 1
    err = capsys.readouterr().err
    assert len(runner.runs) == 2
    assert "for stills group 2/4" in err
    assert "stills-group-02.log" in err
    assert "rerun the same command to continue" in err
    images_dir = os.path.join(str(movie_ws), "generated", "stories", "groups", "images")
    assert os.path.isfile(os.path.join(images_dir, "panel_04.png"))
    runner.returncodes = [2]
    del runner.runs[:]
    assert ltx_movie.phase2_stills(args) == 1
    assert [cmd[cmd.index("--only") + 1] for cmd, _log in runner.runs] == ["1,5"]
    assert capsys.readouterr().err == (
        "Error: ltx-story-images exited 2 for stills group 2/4 (kyra; panels 1,5); log: %s. "
        "Stills already written are kept; rerun the same command to continue -- every existing "
        "panel_NN.png is reused.\n" % os.path.join(images_dir, "stills-group-02.log"))


def test_s45_each_group_is_one_lora_set_end_to_end(monkeypatch, movie_ws, lib_dir):
    args = _group_args(movie_ws, lib_dir)
    runner = _StillsRunner(monkeypatch, write_pngs=False)
    assert ltx_movie.phase2_stills(args) == 0
    assert len(runner.runs) == 4
    calls, _seeds = _fake_zimage_shots(monkeypatch)
    for (cmd, _log), (names, panels) in zip(runner.runs, GROUPS):
        del calls[:]
        assert story_images.main(cmd[2:]) == 0, names
        assert len(calls) == len(panels)
        for _prompt, kwargs in calls:
            if names:
                assert kwargs["loras"] == [(_stills_path(lib_dir, n), 0.8) for n in names]
            else:
                assert "loras" not in kwargs
