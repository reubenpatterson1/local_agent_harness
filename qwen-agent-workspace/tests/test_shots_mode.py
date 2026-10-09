"""Tests for shots mode (spec docs/superpowers/specs/2026-10-06-shots-mode-design.md
Section 10, S1-S72) and shots rules v2 (docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md
Section 8: S21, S54-S59, S80-S99).

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
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium shot of the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing in the centre of a mossy cedar trail and facing right. Far behind her on the left, small in the frame, the bearded robber watches from the ferns. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The woman in grey turns her head slowly toward the ferns on her right. The camera stays static.
Narration: She senses she is not alone.

## Panel 2 — The Robber
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing left. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The bearded robber lunges forward out of the ferns with his short knife raised. The camera stays static.
Narration: A robber springs from cover.

## Panel 3 — The Ronin
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium shot of the ronin, a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori, and the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing an arm's length apart on the mossy cedar trail, the ronin on the left facing right. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
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
        + '- "the ronin": ' + DESC_R + "." + "\n" + lib.SHOTS_IDENTITY_HEADER + "\n"
        + "- The woman in grey is " + DESC_K + "." + "\n" + "- The ronin is " + DESC_R + "."
        + "\n" + lib.SHOTS_CAST_BLOCK_RULES)
    continuous = (lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
                  + '- "the ronin": ' + DESC_R + "." + "\n" + lib.CAST_BLOCK_RULES)
    assert lib.build_cast_block(m) == continuous
    assert lib.build_cast_block(m, shots=False) == continuous
    rules = lib.SHOTS_CAST_BLOCK_RULES
    assert "{" not in rules and "}" not in rules and "%" not in rules
    assert rules.count("word for word") == 2
    for fragment in ("at most two of these characters", "a medium shot or closer",
                     "never within arm's reach", "show it by cutting",
                     "identity sentence from the list above, copied word for word",
                     'says "far in the background"', "not even in a possessive",
                     "they never touch -- no taken hand, no hand-off",
                     "An animal, such as a horse that a character rides, is not a person",
                     "has none of these extra rules"):
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


PANEL_2_IMAGE = ("Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, "
                 "the ground soft with moss, under soft overcast light. A medium close-up of the bearded robber, a stocky man with a black beard in "
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
        "panel 3: S5 one action: Motion: chains actions with 'then'",
        "panel 3: S8 contact: Motion: 'pulls' acts on 'the woman in grey'; two people touching on "
        "screen"]


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
        "character's reaction",
        "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'; two people touching "
        "on screen"]
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
    assert advise(_variant("grey kimono, standing in the centre", "grey robe, standing in the centre")) == []
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
WIDE = _variant("A medium shot of the woman in grey", "A wide shot of the woman in grey")
WIDE_WARNING = ("Warning: panel 1: shows cast character(s) kyra but its Image: shot type is wide "
                "shot; a shot with a cast character should be a medium shot or closer")
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
                                      "moving it to %s and asking for rewrite 1 of 2:"
                                      % rejected[0]))
    assert lines[warning + 1:warning + 3] == ["  - " + v for v in BAD_VIOLATIONS]


def test_s37_third_failure_exits_2(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD, BAD])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert len(agent.calls) == 3
    assert "Error: story.md still breaks the shot rules after 2 rewrites:" in err
    for v in BAD_VIOLATIONS:
        assert "  - " + v in err.splitlines()
    rejected = _rejected(directory)
    assert len(rejected) == 2
    kept = next(line for line in err.splitlines()
                if line.startswith("The rejected drafts are kept at "))
    assert sorted(kept[len("The rejected drafts are kept at "):].split(". Hand-edit ")[0]
                  .split(", ")) == rejected
    for path in rejected:
        with open(path, encoding="utf-8") as f:
            assert f.read() == BAD
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
    assert "Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept at " in err
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
    assert "Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept at " in err


def test_s40_advisories_are_not_fatal(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [WIDE])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert WIDE_WARNING in capsys.readouterr().out.splitlines()
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, WIDE])
    gate = []
    monkeypatch.setattr("builtins.input", lambda prompt="": gate.append(prompt) or "")
    argv = [a for a in SHOTS_ARGV if a != "--no-review"] + ["--force-story"]
    assert ltx_movie.phase1_story(_shots_args(*argv)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    assert gate == ["Review story.md above. Enter to continue, Ctrl-C to abort: "]
    dump = out.index("=== story.md ===\n" + WIDE)
    assert out.index(WIDE_WARNING) > dump


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


def test_s44_failing_group_does_not_stop_phase2(monkeypatch, movie_ws, lib_dir, capsys):
    args = _group_args(movie_ws, lib_dir)
    images_dir = os.path.join(str(movie_ws), "generated", "stories", "groups", "images")
    log2, log4 = (os.path.join(images_dir, "stills-group-%02d.log" % k) for k in (2, 4))
    hint = ("Stills already written are kept. If a log shows \"panel N BLOCKED\", edit that "
            "panel's Image: line in story.md first -- the stills seed is pinned, so a rerun alone "
            "reproduces the block. Then rerun the same command to continue -- groups whose stills "
            "all exist are skipped.\n")
    runner = _StillsRunner(monkeypatch, returncodes=[0, 1, 0, 2])
    assert ltx_movie.phase2_stills(args) == 1
    assert [cmd[cmd.index("--only") + 1] for cmd, _log in runner.runs] == ["4", "1,5", "2", "3"]
    assert capsys.readouterr().err == (
        "Error: ltx-story-images exited nonzero for 2 of 4 stills groups:\n"
        "  - stills group 2/4 (kyra; panels 1,5) exited 1 -- see %s\n"
        "  - stills group 4/4 (kyra, ronin; panels 3) exited 2 -- see %s\n" % (log2, log4)
        + hint)
    assert sorted(f for f in os.listdir(images_dir) if f.endswith(".png")) == [
        "panel_02.png", "panel_04.png"]
    runner.returncodes = [2]
    del runner.runs[:]
    assert ltx_movie.phase2_stills(args) == 1
    assert [cmd[cmd.index("--only") + 1] for cmd, _log in runner.runs] == ["1,5", "3"]
    out, err = capsys.readouterr()
    assert out.count("every still exists; skipped") == 2
    assert err == ("Error: ltx-story-images exited nonzero for 1 of 4 stills groups:\n"
                   "  - stills group 2/4 (kyra; panels 1,5) exited 2 -- see %s\n" % log2 + hint)
    del runner.runs[:]
    assert ltx_movie.phase2_stills(args) == 0
    assert [cmd[cmd.index("--only") + 1] for cmd, _log in runner.runs] == ["1,5"]
    assert capsys.readouterr().err == ""


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


# --- S46-S53: --redo, Phase 3, Phase 4 and the dry run (spec 5.6-5.8) --------------------
def _record_runs(monkeypatch):
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0))
    return runs


def test_s46_phase3_passes_shots_and_every_still(monkeypatch, movie_ws, capsys):
    _story_dir_with(movie_ws, "s46")
    args = _shots_args("n", "--story-id", "s46", "--shots", "--panels", "14", "--no-review")
    runs = _record_runs(monkeypatch)
    assert ltx_movie.phase3_manifest(args) == 0
    manifest_cmd = runs[0]
    assert "ltx-story-manifest" in manifest_cmd[1]
    images = os.path.join(str(movie_ws), "generated", "stories", "s46", "images")
    expected = []
    for i in range(1, 15):
        expected += ["--image", os.path.join(images, "panel_%02d.png" % i)]
    at = manifest_cmd.index("--shots")
    assert manifest_cmd[at + 1:at + 29] == expected
    assert manifest_cmd.count("--image") == 14
    assert "--chain" not in manifest_cmd
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "s46", "--shots", "--panels", "14", "--dry-run",
                           "--no-review"]) == 0
    assert "Command: %s" % ltx_movie.shlex.join(manifest_cmd) in capsys.readouterr().out.splitlines()


def test_s47_phase4_failure_policy(tmp_path, monkeypatch, capsys):
    def policy(*extra):
        flags = ltx_movie._phase4_flags(_movie_args("n", "--story-id", "x", *extra))
        return flags[flags.index("--on-panel-failure") + 1]

    assert policy("--shots") == "skip"
    assert policy() == "stop"
    assert policy("--no-stills") == "skip"
    # The Phase 2 stills groups and the Phase 4 render run through _stream_and_tee with
    # PYTHONUNBUFFERED=1, so their logs are written live and survive a hard crash.
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    log = tmp_path / "tee.log"
    assert ltx_movie._stream_and_tee(
        [sys.executable, "-c", "import os; print(os.environ.get('PYTHONUNBUFFERED'))"],
        str(log)) == 0
    assert log.read_text() == "1\n"
    assert capsys.readouterr().out == "1\n"


def test_s48_phase_sequence_with_redo():
    def names(**kwargs):
        return tuple(f.__name__ for f in ltx_movie._phase_sequence(types.SimpleNamespace(**kwargs)))

    assert names(no_stills=False, story_server_stop_after_story=True, redo_panels=[3]) == (
        "phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills",
        "phase3_manifest", "phase4_render")
    assert names(no_stills=False, story_server_stop_after_story=True, redo_panels=[]) == (
        "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
        "phase4_render")
    l41 = [
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
          "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills",
          "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server", "phase3_manifest",
          "phase4_render")),
    ]
    for kwargs, expected in l41:
        assert names(**kwargs) == expected, kwargs


def _redo_tree(movie_ws, story_id, clip_panels=(1, 2, 3)):
    """A shots story dir: SHOTS_OK as story.md, images/panel_0{1,2,3}.png, clips/panel_0N.mp4
    (+ .provenance.json) for clip_panels, and movie.mp4, each with distinct bytes."""
    directory = _story_dir_with(movie_ws, story_id, SHOTS_OK)
    (directory / "images").mkdir()
    (directory / "clips").mkdir()
    for i in (1, 2, 3):
        (directory / "images" / ("panel_%02d.png" % i)).write_bytes(b"still %d" % i)
        if i in clip_panels:
            (directory / "clips" / ("panel_%02d.mp4" % i)).write_bytes(b"clip %d" % i)
            (directory / "clips" / ("panel_%02d.mp4.provenance.json" % i)).write_bytes(
                b"provenance %d" % i)
    (directory / "movie.mp4").write_bytes(b"movie")
    return str(directory)


def _snapshot(directory):
    out = {}
    for path in _all_files(directory):
        with open(path, "rb") as f:
            out[path] = (f.read(), os.stat(path).st_mtime_ns)
    return out


def _redo_pairs(directory, archive, panel, clip=True):
    j = os.path.join
    pairs = [(j(directory, "images", "panel_%02d.png" % panel),
              j(archive, "images", "panel_%02d.png" % panel))]
    if clip:
        pairs += [(j(directory, "clips", "panel_%02d.mp4" % panel),
                   j(archive, "clips", "panel_%02d.mp4" % panel)),
                  (j(directory, "clips", "panel_%02d.mp4.provenance.json" % panel),
                   j(archive, "clips", "panel_%02d.mp4.provenance.json" % panel))]
    return pairs + [(j(directory, "movie.mp4"), j(archive, "movie.mp4"))]


def test_s49_redo_moves_only_the_named_panels(movie_ws, capsys, monkeypatch):
    directory = _redo_tree(movie_ws, "s49")
    before = _snapshot(directory)
    args = _shots_args("n", "--story-id", "s49", "--shots", "--redo", "2", "--panels", "3")
    assert ltx_movie.phase_redo_shots(args) == 0
    archives = glob.glob(os.path.join(directory, "redo", "*"))
    assert len(archives) == 1
    assert re.fullmatch(r"\d{8}T\d{6}Z-%d" % os.getpid(), os.path.basename(archives[0]))
    pairs = _redo_pairs(directory, archives[0], 2)
    for src, dst in pairs:
        assert not os.path.lexists(src)
        with open(dst, "rb") as f:
            assert f.read() == before[src][0]
    after = _snapshot(directory)
    moved = {src for src, _dst in pairs}
    for path, value in before.items():
        if path not in moved:
            assert after[path] == value, path
    assert len(after) == len(before)
    assert [l for l in capsys.readouterr().out.splitlines() if l.startswith("redo: moved ")] == [
        "redo: moved %s -> %s" % pair for pair in pairs]
    directory = _redo_tree(movie_ws, "s49b", clip_panels=(1, 2))
    args = _shots_args("n", "--story-id", "s49b", "--shots", "--redo", "3", "--panels", "3")
    assert ltx_movie.phase_redo_shots(args) == 0
    archives = glob.glob(os.path.join(directory, "redo", "*"))
    assert len(archives) == 1
    assert [l for l in capsys.readouterr().out.splitlines() if l.startswith("redo: moved ")] == [
        "redo: moved %s -> %s" % pair for pair in _redo_pairs(directory, archives[0], 3,
                                                               clip=False)]
    # E-S13: a failed move returns 1 with one Error: line on stderr; the earlier move stays in
    # the archive (printed), and the failed and later files stay where they were.
    directory = _redo_tree(movie_ws, "s49c")
    before = _snapshot(directory)
    real_replace = os.replace

    def replace(src, dst):
        if src.endswith(os.path.join("clips", "panel_02.mp4")):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(ltx_movie.os, "replace", replace)
    try:
        args = _shots_args("n", "--story-id", "s49c", "--shots", "--redo", "2", "--panels", "3")
        assert ltx_movie.phase_redo_shots(args) == 1
    finally:
        monkeypatch.setattr(ltx_movie.os, "replace", real_replace)
    archives = glob.glob(os.path.join(directory, "redo", "*"))
    assert len(archives) == 1
    (still, still_dst), (clip, clip_dst) = _redo_pairs(directory, archives[0], 2)[:2]
    captured = capsys.readouterr()
    assert [l for l in captured.out.splitlines() if l.startswith("redo: moved ")] == [
        "redo: moved %s -> %s" % (still, still_dst)]
    assert captured.err.splitlines() == [
        "Error: --redo could not move %s to %s: [Errno 28] No space left on device"
        % (clip, clip_dst)]
    with open(still_dst, "rb") as f:
        assert f.read() == before[still][0]
    after = _snapshot(directory)
    assert len(after) == len(before)
    for path, value in before.items():
        if path != still:
            assert after[path] == value, path


def test_s50_dry_run_new_shots_story(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_id = "shots-s50-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
        cwd=WS, env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir, STORY_PIPELINE_LOGGED="1"),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    lines = out.splitlines()
    assert "sequence of separate shots joined by cuts" in out
    assert "at most two of these characters" in out
    assert any(l.startswith("Stills groups: computed from story.md after Phase 1") for l in lines)
    phase2 = [l for l in lines if l.startswith("Command: ") and "ltx-story-images" in l]
    assert len(phase2) == 1
    assert "--only '<PANELS>'" in phase2[0] and phase2[0].endswith(" --shots")
    manifest = [l for l in lines if l.startswith("Command: ") and "ltx-story-manifest" in l]
    assert len(manifest) == 1
    assert "--shots" in manifest[0].split() and manifest[0].split().count("--image") == 4
    assert "--on-panel-failure skip" in out
    assert not os.path.exists(story_dir)


def test_s51_dry_run_existing_story_with_redo(movie_ws, lib_dir, capsys):
    _kyra(lib_dir)
    _ronin(lib_dir)
    directory = _redo_tree(movie_ws, "s51")
    before = _snapshot(directory)
    assert ltx_movie.main(["n", "--story-id", "s51", "--shots", "--redo", "2", "--panels", "3",
                           "--dry-run", "--no-review", "--character", "kyra",
                           "--character", "ronin"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "--- Redo: panels 2 ---" in lines
    archive = os.path.join(directory, "redo", "<UTC stamp>-<pid>")
    assert [l for l in lines if l.startswith("Would move ")] == [
        "Would move %s -> %s" % pair for pair in _redo_pairs(directory, archive, 2)]
    groups = [i for i, l in enumerate(lines) if l.startswith("stills group ")]
    assert [lines[i] for i in groups] == [
        "stills group 1/3 (no character LoRAs; panels 2)",
        "stills group 2/3 (kyra; panels 1) -- would be skipped: every still exists",
        "stills group 3/3 (kyra, ronin; panels 3) -- would be skipped: every still exists"]
    for i, only in zip(groups, ("2", "1", "3")):
        assert lines[i + 1].startswith("Command: ") and "ltx-story-images" in lines[i + 1]
        assert " --only %s " % only in lines[i + 1] and lines[i + 1].endswith(" --shots")
    assert _snapshot(directory) == before
    assert not os.path.exists(os.path.join(directory, "redo"))
    # --force-story: story.md is about to be rewritten, so the groups are not read from it.
    assert ltx_movie.main(["n", "--story-id", "s51", "--shots", "--force-story", "--panels", "3",
                           "--dry-run", "--no-review", "--character", "kyra",
                           "--character", "ronin"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(l.startswith("Stills groups: computed from story.md after Phase 1") for l in lines)
    assert not [l for l in lines if l.startswith("stills group ")]
    assert _snapshot(directory) == before


def test_s52_non_shots_outputs_are_byte_identical(tmp_path, movie_ws, capsys):
    regression = _load("casting_regression_for_s52", "tests/test_casting_regression.py")
    for text, golden in ((regression.b1_text(), regression.GOLDEN_B1),
                         (regression.b2_text(str(tmp_path)), regression.GOLDEN_B2),
                         (regression.b3_text(), regression.GOLDEN_B3)):
        with open(golden, encoding="utf-8") as f:
            assert text == f.read(), golden
    args = _movie_args("n", "--story-id", "x")
    flags = ltx_movie._phase4_flags(args)
    assert "--shots" not in flags
    assert "--shots" not in ltx_movie._render_flags(args)
    assert flags[flags.index("--on-panel-failure") + 1] == "stop"
    assert ltx_movie.main(["n", "--story-id", "x", "--dry-run", "--no-review"]) == 0
    out = capsys.readouterr().out
    assert "--shots" not in out.split()
    manifest = next(l for l in out.splitlines()
                    if l.startswith("Command: ") and "ltx-story-manifest" in l)
    assert "--chain" in manifest.split()


def test_s53_uncast_shots_dry_run_never_loads_character_lib():
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review', '--shots'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    lines = proc.stdout.splitlines()
    assert "RC=0" in lines, proc.stderr
    assert "CHARACTER_LIB_LOADED=False" in lines


# --- shots rules v2 (docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md, Section 8) ----
FIXTURES_V2 = os.path.join(WS, "tests", "fixtures", "shots_rules_v2")
FIXTURE_SHA256 = {
    "windup.md": "b52b17348d7ff9add08a7202ff49632cbc6043ac994062cd69d33848cdacec85",
    "rules-as-generated.md": "b21ba27f8c0dfe31510a8dbe8024ea7047cfd8418cd283ef279fe815f1a33a63",
    "rules-edited.md": "88dda540b2fb8da4800d35ce28264592ba27b4640b41aace3fc19912de455753",
    "full20.md": "f4ea6f71f7055f6b49c6bdd98636bc5676c118b1062f43eb1cda3a001027e7b6",
    "ls1.md": "b2c97fa050e87b2da8a483a1550ebc74c197f4777c2bc6b64440b97effd632d9",
}
WINDUP_V2_SHA256 = "1a3d891d0442db0a9ddd1c6819cf3cf6506f1425dd98a815cb39ee6040dcd085"
WINDUP_V2_EDITS = (
    ("facing left toward an attacker just outside the frame, her eyes wide", "facing left, her eyes wide"),
    ("her eyes fixed on the attacker outside the frame.", "her eyes fixed on the left of the frame."),
    ("his eyes hard and fixed on the robber outside the frame.", "his eyes hard and fixed on the left of the frame."),
)
DESC_K_LIVE = ("a young East Asian woman with fair skin, long black hair pinned up with three jade "
               "hairpins, wearing a pale grey silk kimono with a silver obi")
DESC_R_LIVE = ("a lean man in his late thirties with a topknot and a scarred brow, wearing a faded "
               "indigo haori and dark hakama")
HUM = ["the woman in grey", "the ronin", "the bearded robber"]
ANI = ["the dark bay horse"]
DES = [DESC_K, DESC_R, "a stocky man with a black beard in a ragged brown jacket"]
P1_SENT = "Far behind her on the left, small in the frame, the bearded robber watches from the ferns."
P2_MOTION = ("Motion: The bearded robber lunges forward out of the ferns with his short knife raised. "
             "The camera stays static.")
M1_MOTION = "Motion: The woman in grey turns her head slowly toward the ferns on her right."
SET = ("The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft "
       "with moss, under soft overcast light. ")
REST_2 = ("A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown "
          "jacket, crouching among ferns on a mossy cedar trail and facing left.")
IMG_2 = "crouching among ferns on a mossy cedar trail and facing left."
ROSTER_HORSE = _variant('- "the bearded robber":',
                        '- "the dark bay horse": a dark bay horse with a white blaze\n'
                        '- "the bearded robber":')
ROSTER_RIDER = _variant('- "the bearded robber":',
                        '- "the rider": a young man in a straw hat\n'
                        '- "the rider\'s horse": a grey mare with a rope bridle\n'
                        '- "the bearded robber":')
S7_LINE_1 = ("panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the "
             "bearded robber'; show the other character's action in its own shot, then cut to the "
             "cast character's reaction")
S8_TAIL = "; two people touching on screen"
S9_KYRA_1 = ("panel 1: S9 cast description: Image: names 'the woman in grey' without character "
             "kyra's description word for word; copy in this sentence: The woman in grey is "
             + DESC_K + ".")
S10_TAIL = ', without "far in the background" or another distance cue in that sentence'
S11_TAIL = "; use left and right screen direction instead"
S12_LINE = ('S12 setting sentence: Image: has no setting sentence of at least 12 words starting '
            '"The setting is"')
CORPUS_PROJ = {
    'windup.md': (6,
        '2:S10 2:S11 3:S10 3:S11 5:S10 5:S11'),
    'windup-v2': (0,
        ''),
    'rules-as-generated.md': (41,
        '1:S9 2:S9 3:S9 4:S9 6:S9 6:S10 7:S8 7:S9 7:S10 8:S9 8:S10 9:S9 9:S10 11:S8 11:S8 11:S9 11:S10 12:S9 12:S10 13:S9 13:S9 14:S8 14:S8 14:S9 14:S9 15:S9 15:S9 16:S9 16:S9 16:S10 17:S9 17:S10 18:S7 18:S8 18:S8 18:S9 18:S10 19:S9 19:S10 20:S9 20:S10'),
    'rules-edited.md': (39,
        '1:S9 2:S9 3:S9 4:S9 6:S9 6:S10 7:S8 7:S9 7:S10 8:S9 8:S10 9:S9 9:S10 11:S8 11:S8 11:S9 11:S10 12:S9 12:S10 13:S9 13:S9 14:S8 14:S8 14:S9 14:S9 15:S9 15:S9 16:S9 16:S9 16:S10 17:S9 17:S10 18:S8 18:S9 18:S10 19:S9 19:S10 20:S9 20:S10'),
    'full20.md': (52,
        '1:S9 1:S12 2:S9 2:S12 3:S12 4:S9 4:S12 5:S9 5:S12 6:S12 7:S9 7:S10 7:S10 7:S12 8:S9 8:S10 8:S10 8:S12 9:S9 9:S10 9:S10 9:S12 10:S9 10:S10 10:S12 11:S9 11:S9 11:S10 11:S10 11:S12 12:S9 12:S9 12:S12 13:S9 13:S9 13:S12 14:S12 15:S12 16:S9 16:S10 16:S12 17:S9 17:S10 17:S12 18:S12 19:S9 19:S10 19:S10 19:S12 20:S9 20:S10 20:S12'),
    'ls1.md': (25,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S8 11:S9 11:S10 11:S10 11:S12 12:S12 13:S8 13:S10 13:S12 14:S8 14:S9 14:S12'),
}
REPAIRED_PROJ = {
    'windup.md': (6, 0,
        '2:S10 2:S11 3:S10 3:S11 5:S10 5:S11'),
    'windup-v2': (0, 0,
        ''),
    'rules-as-generated.md': (19, 22,
        '6:S10 7:S8 7:S10 8:S10 9:S10 11:S8 11:S8 11:S10 12:S10 14:S8 14:S8 16:S10 17:S10 18:S7 18:S8 18:S8 18:S10 19:S10 20:S10'),
    'rules-edited.md': (17, 22,
        '6:S10 7:S8 7:S10 8:S10 9:S10 11:S8 11:S8 11:S10 12:S10 14:S8 14:S8 16:S10 17:S10 18:S8 18:S10 19:S10 20:S10'),
    'full20.md': (34, 18,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S10 7:S10 7:S12 8:S10 8:S10 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S10 11:S10 11:S12 12:S12 13:S12 14:S12 15:S12 16:S10 16:S12 17:S10 17:S12 18:S12 19:S10 19:S10 19:S12 20:S10 20:S12'),
    'ls1.md': (23, 2,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S8 11:S10 11:S10 11:S12 12:S12 13:S8 13:S10 13:S12 14:S8 14:S12'),
}
S96_LINES = [
    ('rules-as-generated.md',
     "panel 7: S8 contact: Image: 'strikes' acts on 'robber leader'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 11: S8 contact: Motion: 'disarming' acts on 'robber'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 11: S8 contact: Image: 'disarms' acts on 'robber'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 14: S8 contact: Motion: 'takes' acts on 'the ronin'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 14: S8 contact: Image: 'taking' acts on 'the ronin'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 18: S7 cast and extra: Motion: names 'the ronin' together with 'shogun'; show the other character's action in its own shot, then cut to the cast character's reaction"),
    ('rules-as-generated.md',
     'panel 6: S10 extra in cast shot: Image: names \'robber leader\' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence'),
    ('rules-as-generated.md',
     'panel 17: S10 extra in cast shot: Image: names \'shogun\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('rules-as-generated.md',
     "panel 1: S9 cast description: Image: names 'the ronin' without character ronin's description word for word; copy in this sentence: The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama."),
    ('ls1.md',
     'panel 9: S10 extra in cast shot: Image: names \'woman\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 9: S10 extra in cast shot: Image: names \'robbers\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 10: S10 extra in cast shot: Image: names \'stocky bearded robber\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 13: S8 contact: Motion: \'cuts\' acts on "robber\'s"; two people touching on screen'),
    ('ls1.md',
     "panel 14: S8 contact: Motion: 'help' acts on 'her'; two people touching on screen"),
    ('windup.md',
     'panel 2: S10 extra in cast shot: Image: names \'attacker\' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence'),
    ('windup.md',
     "panel 2: S11 off-screen wording: Image: says 'outside the frame'; use left and right screen direction instead"),
    ('full20.md',
     'panel 19: S10 extra in cast shot: Image: names \'shogun\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('full20.md',
     'panel 19: S10 extra in cast shot: Image: names \'woman\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('full20.md',
     'panel 1: S12 setting sentence: Image: has no setting sentence of at least 12 words starting "The setting is"'),
]


def _p1(new, text=None):
    return _variant(P1_SENT, new, text)


def _v(tmp_path, text, members):
    return character_lib.shots_violations(text, _panels(tmp_path, text), 3, members)


def _proj(violations):
    """'N:Sx' per panel violation, space-joined (shots rules v2 spec 8.4)."""
    assert all(v.startswith("panel ") for v in violations)
    return " ".join(re.match(r"panel (\d+): (S\d+) ", v).expand(r"\1:\2") for v in violations)


def _live_members(lib_dir):
    make_character(lib_dir, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K_LIVE)
    make_character(lib_dir, "ronin", "roninmn", "the ronin", "man", DESC_R_LIVE)
    return _members("kyra", "ronin")


def _corpus():
    """{name: text} for the five fixture stories and windup-v2 (spec 8.1)."""
    texts = {}
    for name, digest in FIXTURE_SHA256.items():
        with open(os.path.join(FIXTURES_V2, name), "rb") as f:
            raw = f.read()
        assert hashlib.sha256(raw).hexdigest() == digest, name
        texts[name] = raw.decode("utf-8")
    windup = texts["windup.md"]
    for old, new in WINDUP_V2_EDITS:
        assert windup.count(old) == 1, old
        windup = windup.replace(old, new)
    assert hashlib.sha256(windup.encode("utf-8")).hexdigest() == WINDUP_V2_SHA256
    texts["windup-v2"] = windup
    return texts


def _corpus_violations(tmp_path, text, members):
    panels = _panels(tmp_path, text)
    return character_lib.shots_violations(text, panels, len(panels), members)


def test_s21_repair_cast_descriptions(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    repair = character_lib.repair_cast_descriptions
    assert repair(SHOTS_OK, members) == (SHOTS_OK, [])
    fixed, repaired = repair(PARAPHRASED, members)
    assert repaired == [(1, "kyra")]
    assert fixed == _variant("facing right. Far behind her",
                             "facing right. The woman in grey is " + DESC_K + ". Far behind her",
                             PARAPHRASED)
    assert _v(tmp_path, fixed, members) == []
    assert repair(PARAPHRASED, []) == (PARAPHRASED, [])
    both = _variant("a lean man in his late thirties with a topknot and a scarred brow wearing an "
                    "indigo haori, and the woman in grey, a young woman with long black hair pinned "
                    "up with jade hairpins wearing a grey kimono, standing",
                    "a lean man, and the woman in grey standing")
    fixed, repaired = repair(both, members)
    assert repaired == [(3, "kyra"), (3, "ronin")]
    assert fixed == _variant("the ronin on the left facing right.",
                             "the ronin on the left facing right. The ronin is " + DESC_R
                             + ". The woman in grey is " + DESC_K + ".", both)
    no_end = _variant("A medium close-up of the bearded robber, a stocky man with a black beard in a "
                      "ragged brown jacket, crouching among ferns on a mossy cedar trail and facing "
                      "left. Soft overcast light, muted green palette, eye-level camera, "
                      "photorealistic film still.",
                      "A medium close-up of the bearded robber facing the ronin")
    fixed, repaired = repair(no_end, members)
    assert repaired == [(2, "ronin")]
    assert "facing the ronin. The ronin is " + DESC_R + ".\nMotion: The bearded robber" in fixed
    split = _variant("A medium shot of the woman in grey, a young woman with long black hair pinned "
                     "up with jade hairpins wearing a grey robe,",
                     "A medium shot of the woman\nin grey,", PARAPHRASED)
    assert repair(split, members) == (split, [])
    assert [v for v in _v(tmp_path, split, members) if " S9 " in v] == [
        "panel 1: S9 cast description: Image: names 'the woman in grey' without character kyra's "
        "description word for word; copy in this sentence: The woman in grey is " + DESC_K + "."]
    continued = _variant("under soft overcast light. A medium shot of the woman in grey",
                         "under soft overcast light.\nA medium shot of the woman in grey",
                         PARAPHRASED)
    fixed, repaired = repair(continued, members)
    assert repaired == [(1, "kyra")]
    assert fixed == _variant("facing right. Far behind her",
                             "facing right. The woman in grey is " + DESC_K + ". Far behind her",
                             continued)
    motion_only = _variant("Motion: The bearded robber lunges forward",
                           "Motion: The bearded robber lunges at the ronin")
    assert repair(motion_only, members) == (motion_only, [])
    crlf = PARAPHRASED.replace("\n", "\r\n")
    fixed, repaired = repair(crlf, members)
    assert repaired == [(1, "kyra")] and fixed.count("\r\n") == crlf.count("\r\n")
    crlf2 = no_end.replace("\n", "\r\n")
    fixed, repaired = repair(crlf2, members)
    assert repaired == [(2, "ronin")] and fixed.count("\r\n") == crlf2.count("\r\n")


def test_s54_phase1_repairs_s9_in_place(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 1
    kept = sorted(glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")))
    assert len(kept) == 1
    assert re.fullmatch(r"story\.pre-repair-\d{8}T\d{6}Z-%d\.md" % os.getpid(),
                        os.path.basename(kept[0]))
    with open(kept[0], "rb") as f:
        assert f.read() == PARAPHRASED.encode("utf-8")
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            PARAPHRASED, _members("kyra", "ronin"))[0]
    assert ("Repaired S9 on panels 1: inserted 1 missing cast identity sentence(s); the unrepaired "
            "draft is kept at %s" % kept[0]) in out.splitlines()
    assert _rejected(directory) == []
    assert not os.path.exists(story_md + ".repair.tmp")


def test_s55_repair_runs_before_the_rewrite_block(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    first = _variant("Motion: The bearded robber lunges forward out of the ferns with his short "
                     "knife raised. The camera stays static.",
                     "Motion: The bearded robber lunges then slashes.", PARAPHRASED)
    agent = _FakeStoryAgent(monkeypatch, story_md, [first, PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 2
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            PARAPHRASED, _members("kyra", "ronin"))[0]
    assert agent.calls[1]["cmd"][-1] == (agent.calls[0]["cmd"][-1] + "\n\n"
                                         + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3))
    rejected = _rejected(directory)
    assert len(rejected) == 1
    with open(rejected[0], encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            first, _members("kyra", "ronin"))[0]
    kept = glob.glob(os.path.join(str(directory), "story.pre-repair-*.md"))
    assert sorted(open(path, encoding="utf-8").read() for path in kept) == sorted([first,
                                                                                  PARAPHRASED])


def test_s56_second_rewrite_lists_only_the_remaining_violations(monkeypatch, movie_ws, lib_dir,
                                                                capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    bad2 = _variant(PANEL_3_MOTION, "Motion: The ronin offers his hand then pulls the woman in grey "
                                    "to her feet on the trail.")
    bad2_violations = ["panel 3: S5 one action: Motion: chains actions with 'then'",
                       "panel 3: S8 contact: Motion: 'pulls' acts on 'the woman in grey'" + S8_TAIL]
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, bad2, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 3
    first, second, third = (c["cmd"] for c in agent.calls)
    assert second[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3)
    assert third[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(bad2_violations, 3)
    assert first[:-1] == second[:-1] == third[:-1]
    assert agent.calls[2]["existed"] is False
    assert (directory / "story_prompt.rewrite.txt").read_text(encoding="utf-8") == second[-1]
    assert (directory / "story_prompt.rewrite-2.txt").read_text(encoding="utf-8") == third[-1]
    rejected = _rejected(directory)
    assert len(rejected) == 2
    contents = sorted(open(path, encoding="utf-8").read() for path in rejected)
    assert contents == sorted([BAD, bad2])
    lines = out.splitlines()
    second_warning = next(i for i, line in enumerate(lines)
                          if line.startswith("Warning: rewrite 1 still breaks the shot rules; "
                                             "moving it to "))
    assert lines[second_warning].endswith(" and asking for rewrite 2 of 2:")
    assert lines[second_warning + 1:second_warning + 3] == ["  - " + v for v in bad2_violations]
    assert "=== Phase 1: story (rewrite 1 of 2) ===" in lines
    assert "=== Phase 1: story (rewrite 2 of 2) ===" in lines
    runs = [line.split(":")[0] for line in lines if line.startswith("Running (timeout ")]
    assert len(runs) == 3 and len(set(runs)) == 1


def test_s57_second_rewrite_agent_failure(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD, None], returncodes=[0, 0, 1])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 3
    rejected = _rejected(directory)
    assert len(rejected) == 2
    line = next(l for l in err.splitlines()
                if l.startswith("Error: shots rewrite 2 of 2 failed; the rejected draft(s) are kept "
                                "at "))
    assert sorted(line.split(" are kept at ")[1].split(", ")) == rejected


def test_s58_failed_rewrite_moves_its_story_aside(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, PARAPHRASED])
    real = agent.__call__
    calls = {"n": 0}

    def call(cmd, **kwargs):
        proc = real(cmd, **kwargs)
        calls["n"] += 1
        if calls["n"] == 2:
            state = {"first": True}

            def communicate(timeout=None):
                if state["first"]:
                    state["first"] = False
                    raise subprocess.TimeoutExpired(cmd, timeout)
                return ("", None)
            proc.communicate = communicate
            proc.kill = lambda: None
        return proc
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", call)
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert calls["n"] == 2
    assert not os.path.exists(story_md)
    rejected = _rejected(directory)
    assert len(rejected) == 2
    assert sorted(open(path, encoding="utf-8").read() for path in rejected) == sorted([BAD,
                                                                                      PARAPHRASED])
    line = next(l for l in err.splitlines()
                if l.startswith("Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept "
                                "at "))
    assert sorted(line.split(" are kept at ")[1].split(", ")) == rejected
    assert "Error: qwen-agent timed out after " in err


def test_s59_force_story_without_a_write_never_repairs(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir, story=PARAPHRASED)
    agent = _FakeStoryAgent(monkeypatch, story_md, [None])
    assert ltx_movie.phase1_story(_shots_args(*(SHOTS_ARGV + ["--force-story"]))) == 1
    captured = capsys.readouterr()
    assert len(agent.calls) == 1
    assert ("Error: qwen-agent did not write %s; the existing file is unchanged since before "
            "Phase 1 and was neither validated nor repaired. Rerun the same command to try "
            "again." % story_md) in captured.err.splitlines()
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == PARAPHRASED
    assert glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")) == []
    assert _rejected(directory) == []
    assert "Repaired S9" not in captured.out


def test_s80_constants_and_word_lists():
    lib = character_lib
    assert lib.SHOTS_MAX_REWRITES == 2
    assert lib.SHOTS_SETTING_MIN_WORDS == 12
    assert lib.SHOTS_REWRITE_MAX_LISTED == 40
    assert lib._CAMERA_SHORT_MAX_WORDS == 4
    assert len(lib.SHOTS_CONTACT_VERBS) == 158
    assert len(lib.SHOTS_HANDOFF_VERBS) == 12
    assert len(lib.SHOTS_TAKE_VERBS) == 17
    assert len(lib.SHOTS_PERSON_NOUNS) == 88
    assert len(lib.SHOTS_ANIMAL_NOUNS) == 113
    verbs = (lib.SHOTS_CONTACT_VERBS, lib.SHOTS_HANDOFF_VERBS, lib.SHOTS_TAKE_VERBS)
    for a in range(3):
        for b in range(a + 1, 3):
            assert not verbs[a] & verbs[b]
    assert not lib.SHOTS_PERSON_NOUNS & lib.SHOTS_ANIMAL_NOUNS
    assert {"disarming", "shoulder-charges", "strikes", "help", "parries"} <= lib.SHOTS_CONTACT_VERBS
    assert {"hands", "gave", "returns", "returned"} <= lib.SHOTS_HANDOFF_VERBS
    assert {"snatches", "takes", "accepts"} <= lib.SHOTS_TAKE_VERBS
    for word in ("offer offers extend extends lift lifts grip grips clutch clutches hold holds "
                 "throw throws carry carrying pass passes hand wound pierce shoot shot charge "
                 "charges lunge lunges aim reach").split():
        assert all(word not in s for s in verbs), word
    assert {"robber", "attacker", "woman", "soldiers", "ronin"} <= lib.SHOTS_PERSON_NOUNS
    assert not {"guard", "guards", "general"} & lib.SHOTS_PERSON_NOUNS
    assert {"horse", "mare", "snake", "mount"} <= lib.SHOTS_ANIMAL_NOUNS
    assert tuple(r for r, _ in lib.SHOTS_RULE_GUIDANCE) == (
        "S1 panel count", "S2 characters list", "S3 fields", "S4 motion length", "S5 one action",
        "S6 cast count", "S7 cast and extra", "S8 contact", "S9 cast description",
        "S10 extra in cast shot", "S11 off-screen wording", "S12 setting sentence")
    for rule, line in lib.SHOTS_RULE_GUIDANCE:
        assert line.startswith(rule + " -- ") and line.endswith(":"), rule


def test_s81_is_animal_phrase():
    for phrase in ("horse", "the dark bay horse", "the grey mare", "snake", "the falcon's"):
        assert character_lib.is_animal_phrase(phrase) is True, phrase
    for phrase in ("the horseman", "robber leader", "the woman in grey", "the dog-faced bandit",
                   "shogun"):
        assert character_lib.is_animal_phrase(phrase) is False, phrase


def test_s82_person_refs():
    refs = character_lib._person_refs
    assert refs("The woman in grey watches the stocky man.", HUM, ANI, DES) == [
        (0, 17, "the woman in grey"), (37, 40, "man")]
    assert refs("A medium shot of the bearded robber, a stocky man with a black beard in a ragged "
                "brown jacket, facing left.", HUM, ANI, DES) == [(17, 35, "the bearded robber")]
    assert [r[2] for r in refs("The robbers' leader shoves him toward them, and her.",
                               HUM, ANI, DES)] == ["robbers", "leader", "him", "them", "her"]
    assert refs("She raises her blade toward the dark bay horse.", HUM, ANI, DES) == []
    assert [r[2] for r in refs("They face each other; one another.", HUM, ANI, DES)] == [
        "each other", "each other"]
    assert refs("Her figure is small against the trees, and his men wait.", HUM, ANI, DES) == []


S83_HITS = [
    ("The ronin strikes the bearded robber across the arm.", ("strikes", "the bearded robber")),
    ('"the ronin" swings his sword, disarming the robber.', ("disarming", "robber")),
    ("The bearded robber grabs her by the wrist.", ("grabs", "her")),
    ("The ronin pulls her to her feet.", ("pulls", "her")),
    ("The bearded robber shoves him.", ("shoves", "him")),
    ("Two robbers grapple with each other in the mud.", ("grapple", "each other")),
    ("The woman in grey strikes at the bearded robber's sword with a staff.",
     ("strikes", "the bearded robber")),
    ("The ronin slips the club's swing and cuts the robber's forearm.", ("cuts", "robber's")),
    ("The shogun hands the scroll to the ronin.", ("hands", "the ronin")),
    ("The woman in grey takes the ronin's hand.", ("takes", "the ronin")),
    ('"the woman in grey" takes "the ronin"\'s hand.', ("takes", "the ronin")),
    ("The woman in grey takes his hand.", ("takes", "his hand")),
    ("The ronin takes the scroll from the old man.", ("takes", "man")),
    ("The ronin extends his hand to help her up.", ("help", "her")),
    ("The ronin shoulder-charges the bearded robber off the trail.",
     ("shoulder-charges", "the bearded robber")),
    ("He is mid-swing, his katana cutting into the bearded robber's shoulder.",
     ("cutting", "the bearded robber")),
    ("The ronin swings his katana at the young bandit.", ("swings", "bandit")),
    ("The young bandit snatches the letter from the woman in grey.",
     ("snatches", "the woman in grey")),
    ("The ronin returns the letter to her.", ("returns", "her")),
]
S84_MISSES = [
    "The ronin offers his open hand to the woman in grey.",
    "The ronin extends his hand toward the woman in grey.",
    "The robber leader swings his blade downward, aiming for her neck.",
    "The woman in grey flinches backward, throwing her arm up to shield her face.",
    "The robber leader staggers backward, clutching his cut forearm against his chest.",
    "He deflects the bamboo spear with a swift, precise cut.",
    "The camera pushes in past him.",
    "The camera pushes in on him.",
    "The ronin kicks the dark bay horse forward.",
    "The ronin takes a step toward her.",
    "The woman in grey draws the dagger back to her hip, her eyes fixed on the attacker.",
    "The ronin strikes, his eyes on the bearded robber.",
    "The ronin's strike lands on the bearded robber.",
    "The woman in grey catches her breath.",
    "The ronin cuts the rope with his knife, freeing her.",
    "The ronin cuts through the air above the ronin's head.",
    "The ronin lifts the woman in grey's fallen hairpin from the moss.",
    "His strike lands hard on the bearded robber's shoulder.",
    "The shogun gives the ronin a scroll.",
    "The woman in grey pulls her shawl tight around her.",
    "The ronin drags his sword behind him.",
    "The ronin catches sight of the young bandit.",
    "The ronin catches up with the young bandit.",
    "The ronin pulls back from the scarred bandit.",
    "The ronin drives forward toward the scarred bandit.",
    "The scarred bandit steps out of the pines to block the stone path in front of the woman in "
    "grey.",
    "The ronin strikes a pose before the robbers.",
    "The ronin hits the ground beside the bandits.",
    "The ronin returns to the temple gate.",
    "The young bandit snatches the letter from her sash.",
]


def test_s83_find_contact_hits():
    for sentence, want in S83_HITS:
        assert character_lib.find_contact(sentence, HUM, ANI, DES) == want, sentence


def test_s84_find_contact_misses():
    for sentence in S84_MISSES:
        assert character_lib.find_contact(sentence, HUM, ANI, DES) is None, sentence


def test_s85_s8_in_shots_violations(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    a = _variant(P2_MOTION, "Motion: The bearded robber slashes at the woman in grey with his short "
                            "knife. The camera stays static.")
    motion_line = "panel 2: S8 contact: Motion: 'slashes' acts on 'the woman in grey'" + S8_TAIL
    image_line = "panel 2: S8 contact: Image: 'grabs' acts on 'the woman in grey'" + S8_TAIL
    assert _v(tmp_path, a, []) == [motion_line]
    assert _v(tmp_path, a, members) == [
        "panel 2: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction",
        motion_line,
        "panel 2: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "kyra" + S10_TAIL]
    grab = IMG_2 + " He grabs the woman in grey by the sleeve."
    assert _v(tmp_path, _variant(IMG_2, grab), []) == [image_line]
    assert _v(tmp_path, _variant(IMG_2, grab, a), []) == [motion_line, image_line]
    two = _variant(IMG_2, grab + " He shoves the ronin.")
    assert _v(tmp_path, two, []) == [image_line]
    assert _v(tmp_path, SHOTS_OK, []) == []
    assert _v(tmp_path, SHOTS_OK, members) == []


def test_s86_s9_cast_description(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _v(tmp_path, PARAPHRASED, members) == [S9_KYRA_1]
    assert _v(tmp_path, PARAPHRASED, []) == []
    assert _v(tmp_path, _variant("hairpins wearing a grey kimono, standing in the centre",
                                 "hairpins   WEARING a grey kimono, standing in the centre"),
              members) == []
    ident = _variant("the woman in grey, a young woman with long black hair pinned up with jade "
                     "hairpins wearing a grey kimono, standing in the centre",
                     "the woman in grey standing in the centre")
    ident = _variant("Far behind her on the left", "The woman in grey is " + DESC_K
                     + ". Far behind her on the left", ident)
    assert _v(tmp_path, ident, members) == []


def test_s87_s10_extra_in_cast_shot(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    robber = ("panel 1: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that "
              "shows kyra" + S10_TAIL)
    assert _v(tmp_path, _p1("On the left the bearded robber watches from the ferns."),
              members) == [robber]
    for cue in ("far in the background", "in the far background", "far behind", "far back",
                "far away", "far off", "far-off", "in the distance", "in the far distance",
                "far in the distance", "distant", "small in the frame", "tiny in the frame",
                "Far In The Background"):
        assert _v(tmp_path, _p1("On the left, %s, the bearded robber watches from the ferns."
                                % cue), members) == [], cue
    assert _v(tmp_path, _p1("In the background the bearded robber watches from the ferns."),
              members) == [robber]
    assert _v(tmp_path, _p1("On the left two robbers watch from the ferns."), members) == [
        "panel 1: S10 extra in cast shot: Image: names 'robbers' in a shot that shows kyra"
        + S10_TAIL]
    assert _v(tmp_path, _p1("She looks toward him and them."), members) == []
    assert _v(tmp_path, _p1("Far behind her is a ridge. The bearded robber watches from the ferns."),
              members) == [
        "panel 1: S10 extra in cast shot: Image: names 'The bearded robber' in a shot that shows "
        "kyra" + S10_TAIL]
    assert _v(tmp_path, _p1("On the left the bearded robber watches. The bearded robber grins."),
              members) == [robber]
    assert _v(tmp_path, _p1("On the left the dark bay horse grazes beside the ferns.",
                            ROSTER_HORSE), members) == []
    assert _v(tmp_path, S7_BAD, members) == [
        "panel 2: S7 cast and extra: Motion: names 'the ronin' together with 'the bearded robber'; "
        "show the other character's action in its own shot, then cut to the cast character's "
        "reaction",
        "panel 2: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "ronin" + S10_TAIL]
    assert _v(tmp_path, _p1("Beside her stands a stocky man with a black beard in a ragged brown "
                            "jacket."), members) == [
        "panel 1: S10 extra in cast shot: Image: names 'man' in a shot that shows kyra" + S10_TAIL]
    assert _v(tmp_path, _variant("standing an arm's length apart on the mossy cedar trail",
                                 "standing an arm's length apart on the mossy cedar trail beside "
                                 "a wiry young man"), members) == [
        "panel 3: S10 extra in cast shot: Image: names 'man' in a shot that shows kyra, ronin"
        + S10_TAIL]
    assert _v(tmp_path, _p1("Her figure is small against the ferns."), members) == []


def test_s88_s11_off_screen_wording(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    for phrase, shown in (("just outside the frame", "outside the frame"),
                          ("outside of the frame", "outside of the frame"),
                          ("outside the shot", "outside the shot"),
                          ("off-screen", "off-screen"), ("off  Screen", "off screen"),
                          ("offscreen", "offscreen"), ("out of frame", "out of frame"),
                          ("out of the frame", "out of the frame"), ("out of shot", "out of shot"),
                          ("out of view", "out of view"), ("out of sight", "out of sight"),
                          ("off camera", "off camera"), ("off-camera", "off-camera"),
                          ("beyond the frame", "beyond the frame"),
                          ("beyond the edge of the frame", "beyond the edge of the frame"),
                          ("unseen", "unseen"),
                          ("beyond the frame of the temple gate", "beyond the frame")):
        assert _v(tmp_path, _p1(P1_SENT + " Wind stirs the ferns %s." % phrase), members) == [
            "panel 1: S11 off-screen wording: Image: says '%s'" % shown + S11_TAIL], phrase
    assert _v(tmp_path, _variant(P2_MOTION, "Motion: The bearded robber lunges out of frame with his "
                                            "short knife raised. The camera stays static."),
              members) == ["panel 2: S11 off-screen wording: Motion: says 'out of frame'"
                           + S11_TAIL]
    both = _p1(P1_SENT + " Wind stirs the ferns off-screen.",
               _variant(M1_MOTION, "Motion: The woman in grey turns her head slowly toward the "
                                   "ferns off-screen."))
    assert _v(tmp_path, both, members) == [
        "panel 1: S11 off-screen wording: Image: says 'off-screen'" + S11_TAIL,
        "panel 1: S11 off-screen wording: Motion: says 'off-screen'" + S11_TAIL]
    for ok in ("on the left of the frame", "framed by tall ferns", "an offset stone lantern"):
        assert _v(tmp_path, _p1(P1_SENT + " Ferns stand %s." % ok), members) == [], ok


def test_s89_s12_setting_sentence(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    missing = ["panel 2: " + S12_LINE]
    assert _v(tmp_path, _variant(SET + REST_2, REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, REST_2 + " " + SET.strip()), members) == []
    assert _v(tmp_path, _variant(SET + REST_2, SET.replace("The setting", "the setting") + REST_2),
              members) == []
    assert _v(tmp_path, _variant(SET + REST_2, '"' + SET.strip() + '" ' + REST_2), members) == []
    assert _v(tmp_path, _variant(SET + REST_2, "Setting: a mossy cedar trail in feudal Japan. "
                                 + REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, "The setting is the same as before. " + REST_2),
              members) == missing
    eleven = "The setting is a mossy cedar trail in feudal Japan today. "
    twelve = "The setting is a mossy cedar trail in feudal Japan at dusk. "
    assert len(eleven.split()) == 11 and len(twelve.split()) == 12
    assert _v(tmp_path, _variant(SET + REST_2, eleven + REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, twelve + REST_2), members) == []
    assert _v(tmp_path, _variant(PANEL_2_IMAGE, ""), members) == [
        "panel 2: S3 fields: missing/empty Image: field"]


def test_s90_s7_animal_exemption(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey urges the dark bay horse "
                                            "forward along the mossy trail.", ROSTER_HORSE),
              members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey kicks the dark bay horse "
                                            "forward along the mossy trail.", ROSTER_HORSE),
              members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey pats the rider's horse gently "
                                            "on its neck.", ROSTER_RIDER), members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey waves slowly to the rider "
                                            "across the mossy trail.", ROSTER_RIDER), members) == [
        "panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the rider'; "
        "show the other character's action in its own shot, then cut to the cast character's "
        "reaction"]


def test_s91_camera_sentence_fold_in():
    bow = "The ronin bows his head low before the small shrine. "
    for tail in ("Static camera.", "Slow push-in.", "Handheld, slow pan left.", "He stays static."):
        assert character_lib.motion_problems(bow + tail) == [], tail
    for tail in ("He kneels.", "The robber takes the shot."):
        assert character_lib.motion_problems(bow + tail) == [
            ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                              "followed by a camera sentence")], tail


def test_s92_rule_order_in_one_panel(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(SET + "A medium shot of the woman in grey", "A medium shot of the woman in grey",
                    PARAPHRASED)
    text = _variant(P1_SENT, "On the left the bearded robber stands just outside the frame.", text)
    text = _variant("Motion: The woman in grey turns her head slowly toward the ferns on her right. "
                    "The camera stays static.",
                    "Motion: The woman in grey pushes the bearded robber off-screen; then she runs.",
                    text)
    assert _v(tmp_path, text, members) == [
        "panel 1: S5 one action: Motion: contains a semicolon",
        "panel 1: S5 one action: Motion: chains actions with 'then'",
        S7_LINE_1,
        "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'" + S8_TAIL,
        S9_KYRA_1,
        "panel 1: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "kyra" + S10_TAIL,
        "panel 1: S11 off-screen wording: Image: says 'outside the frame'" + S11_TAIL,
        "panel 1: S11 off-screen wording: Motion: says 'off-screen'" + S11_TAIL,
        "panel 1: " + S12_LINE]


def test_s93_identity_sentence_and_shots_cast_block(lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    lib = character_lib
    assert lib.identity_sentence(members[0]) == "The woman in grey is " + DESC_K + "."
    leader = lib.CastMember("x", "robber leader", "t", "man", "a man with a beard here ok", "/v",
                            None, None, None)
    assert lib.identity_sentence(leader) == "Robber leader is a man with a beard here ok."
    assert lib.SHOTS_IDENTITY_HEADER == ("Identity sentences -- copy the one for each of these "
                                         "characters, word for word, into every Image: field that "
                                         "shows them:")
    assert "Identity sentences" not in lib.build_cast_block(members)


S94_VV = [
    "story: S1 panel count: expected exactly 4 panels, found 3",
    "panel 2: S9 cast description: Image: names 'the ronin' without X",
    "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'; two people touching on "
    "screen",
    "panel 5: S9 cast description: Image: names 'the ronin' without X",
    'panel 3: S12 setting sentence: Image: has no sentence starting "The setting is"',
    'panel 4: S12 setting sentence: Image: has no sentence starting "The setting is"',
    "story: cannot read story.md: boom",
    "panel 2: S9 cast description: Image: names 'the woman in grey' without Y"]


def test_s94_rewrite_block_grouping_merging_cap(monkeypatch):
    lib = character_lib
    g = dict(lib.SHOTS_RULE_GUIDANCE)
    listing = "\n".join([
        g["S1 panel count"], "- story: expected exactly 4 panels, found 3",
        g["S8 contact"],
        "- panel 1: Motion: 'pushes' acts on 'the bearded robber'; two people touching on screen",
        g["S9 cast description"], "- panels 2, 5: Image: names 'the ronin' without X",
        "- panel 2: Image: names 'the woman in grey' without Y",
        g["S12 setting sentence"], '- panels 3, 4: Image: has no sentence starting "The setting is"',
        "- story: cannot read story.md: boom"])
    assert lib.shots_rewrite_block(S94_VV, 4) == lib.SHOTS_REWRITE_TEMPLATE % (listing, 4)
    monkeypatch.setattr(lib, "SHOTS_REWRITE_MAX_LISTED", 3)
    capped = "\n".join([
        g["S1 panel count"], "- story: expected exactly 4 panels, found 3",
        g["S8 contact"],
        "- panel 1: Motion: 'pushes' acts on 'the bearded robber'; two people touching on screen",
        g["S9 cast description"], "- panels 2, 5: Image: names 'the ronin' without X",
        "- ... and 4 more"])
    assert lib.shots_rewrite_block(S94_VV, 4) == lib.SHOTS_REWRITE_TEMPLATE % (capped, 4)


def test_s95_corpus_projections(tmp_path, lib_dir):
    members = _live_members(lib_dir)
    texts = _corpus()
    assert sorted(texts) == sorted(CORPUS_PROJ)
    for name, (count, proj) in CORPUS_PROJ.items():
        violations = _corpus_violations(tmp_path, texts[name], members)
        assert len(violations) == count, name
        assert _proj(violations) == proj, name
    for name, (count, repaired, proj) in REPAIRED_PROJ.items():
        fixed, done = character_lib.repair_cast_descriptions(texts[name], members)
        assert len(done) == repaired, name
        violations = _corpus_violations(tmp_path, fixed, members)
        assert len(violations) == count, name
        assert _proj(violations) == proj, name


def test_s96_corpus_exact_lines_uncast_and_block_shape(tmp_path, lib_dir):
    members = _live_members(lib_dir)
    texts = _corpus()
    found = {name: _corpus_violations(tmp_path, text, members) for name, text in texts.items()}
    for name, line in S96_LINES:
        assert line in found[name], (name, line)
    asgen = found["rules-as-generated.md"]
    assert _corpus_violations(tmp_path, texts["rules-as-generated.md"], []) == [
        v for v in asgen if " S8 contact: " in v]
    assert _corpus_violations(tmp_path, texts["windup-v2"], []) == []
    ls1 = _corpus_violations(tmp_path, texts["ls1.md"], [])
    assert _proj(ls1) == ("1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S12 10:S12 11:S8 "
                          "11:S12 12:S12 13:S8 13:S12 14:S8 14:S12")
    g = dict(character_lib.SHOTS_RULE_GUIDANCE)
    block = character_lib.shots_rewrite_block(asgen, 20)
    lines = block.splitlines()
    assert sum(1 for line in lines if line.startswith("- ")) == 16
    assert [line for line in lines if line in g.values()] == [
        g["S7 cast and extra"], g["S8 contact"], g["S9 cast description"],
        g["S10 extra in cast shot"]]
    assert ("- panels 1, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20: Image: names 'the ronin' "
            "without character ronin's description word for word; copy in this sentence: The "
            "ronin is " + DESC_R_LIVE + ".") in lines
    assert ("- panels 2, 3, 4, 6, 7, 13, 14, 15, 16: Image: names 'the woman in grey' without "
            "character kyra's description word for word; copy in this sentence: The woman in grey "
            "is " + DESC_K_LIVE + ".") in lines
    advisories = character_lib.shots_advisories(_panels(tmp_path, texts["rules-as-generated.md"]),
                                                members)
    assert [a.split(":")[0] for a in advisories] == ["panel 12", "panel 16", "panel 20"]
    assert all("Image: shot type is wide shot" in a for a in advisories)


def test_s97_template_v2():
    template = ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS
    assert {f for _, f, _, _ in string.Formatter().parse(template) if f} == {
        "story_id", "narrative", "seconds", "panels"}
    assert template.count("\n\nHow this movie is made:") == 1
    assert len(template.split()) == 922
    for fragment in ("sequence of separate shots joined by cuts", "## Characters", "10-25 words",
                     "ONE physical action", "never use a semicolon",
                     "EXACTLY {panels} panel sections",
                     "the setting sentence of this shot's location, copied word for word",
                     'one sentence made of their referring phrase, the word "is" and their full '
                     'description',
                     '"The setting is a dense cedar forest in feudal Japan, tall trunks and ferns '
                     'behind, the ground covered in leaf litter, under flat overcast grey light."',
                     "Fights and touch. Two people never touch on screen.",
                     "Show a hand-off, a taken hand or a helping hand the same way",
                     'Screen direction. Never write "outside the frame", "off-screen", "out of '
                     'frame"',
                     "never name a person who is not in the shot"):
        assert fragment in template, fragment
    assert "just outside the frame" not in template
    order = [template.index(s) for s in ("Setting sentences.", "Fights and touch.",
                                         "Screen direction.", "Give the story a narrative arc")]
    assert order == sorted(order)


def test_s98_phase1_with_v2_rules(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    first = _variant(PANEL_1_MOTION, "Motion: The woman in grey pushes the bearded robber away from "
                                     "her with both hands.")
    v2 = [S7_LINE_1, "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'" + S8_TAIL]
    agent = _FakeStoryAgent(monkeypatch, story_md, [first, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    capsys.readouterr()
    block = character_lib.shots_rewrite_block(v2, 3)
    assert agent.calls[1]["cmd"][-1] == agent.calls[0]["cmd"][-1] + "\n\n" + block
    assert ("\n" + dict(character_lib.SHOTS_RULE_GUIDANCE)["S8 contact"] + "\n- panel 1: Motion: "
            "'pushes' acts on 'the bearded robber'; two people touching on screen\n") in block
    assert (character_lib.SHOTS_IDENTITY_HEADER + "\n- The woman in grey is " + DESC_K + "."
            in agent.calls[0]["cmd"][-1])
    (directory / "story.md").write_text(PARAPHRASED, encoding="utf-8")
    agent = _FakeStoryAgent(monkeypatch, story_md, [])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert agent.calls == []
    assert err.splitlines()[:2] == ["Error: story.md breaks the shot rules:", "  - " + S9_KYRA_1]
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == PARAPHRASED
    assert glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")) == []


def test_s99_dry_run_shows_the_v2_prompt(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_id = "shots-s99-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
        cwd=WS, env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir, STORY_PIPELINE_LOGGED="1"),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert character_lib.SHOTS_IDENTITY_HEADER in out
    assert "\n- The woman in grey is " + DESC_K + ".\n- The ronin is " + DESC_R + ".\n" in out
    assert ('"The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the '
            'ground covered in leaf litter, under flat overcast grey light."') in out
    assert "Fights and touch. Two people never touch on screen." in out
    assert not os.path.exists(story_dir)
