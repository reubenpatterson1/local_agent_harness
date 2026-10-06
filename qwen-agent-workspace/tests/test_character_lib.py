"""Tests for character_lib.py (spec docs/superpowers/specs/2026-10-05-character-library-design.md
Section 9.2, C1-C41).

Run from the workspace root: python3 -m pytest tests/test_character_lib.py
Plain pytest asserts only (no check() helper). No network, no GPU. Every library lives
under tmp_path through $CHARACTER_LIBRARY_DIR.
"""

import ast
import copy
import hashlib
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402

# The exception classes are looked up on the module at call time, never bound with
# "from character_lib import ...": bin/ltx-movie, bin/ltx-story-manifest and
# bin/ltx-story-images load character_lib.py by path into the same sys.modules entry,
# which re-creates its classes, so a class bound at import time would go stale when this
# file shares a pytest session with tests/test_casting_pipeline.py.

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


def member(name, phrase, trigger, strength=None):
    """A CastMember with dummy paths, for the pure matching tests (spec 9.1)."""
    return character_lib.CastMember(name, phrase, trigger, "woman", DESCRIPTOR,
                                    "/lib/%s/lora/video.safetensors" % name, None, None,
                                    strength)


KYRA = member("kyra", "the woman in grey", "kyrawmn")
RONIN = member("ronin", "the ronin", "roninmn")


def _raises(fn, *args, **kwargs):
    with pytest.raises(character_lib.CharacterError) as info:
        fn(*args, **kwargs)
    return str(info.value)


def _raises_unusable(fn, *args, **kwargs):
    """(message, is it an UnusableCharacterError) for a call that must raise CharacterError."""
    with pytest.raises(character_lib.CharacterError) as info:
        fn(*args, **kwargs)
    return str(info.value), isinstance(info.value, character_lib.UnusableCharacterError)


# --- C1-C7: names, triggers, phrases, auto_trigger (spec 2.4, 3.1, 3.2) -----------------
def test_c1_validate_name():
    for ok in ("kyra", "ab", "a-1", "x" * 24):
        character_lib.validate_name(ok)
    for bad in ("A", "a", "1ab", "ab_c", "a" * 25, None):
        message = _raises(character_lib.validate_name, bad)
        assert message == "character name must match [a-z][a-z0-9-]{1,23}, got %r" % (bad,)


def test_c2_validate_trigger():
    for ok in ("kyrawmn", "abcd", "a" + "b" * 15):
        character_lib.validate_trigger(ok)
    for bad in ("abc", "Kyra", "1abc", "ab-cd", "a" * 17):
        message = _raises(character_lib.validate_trigger, bad)
        assert message == "trigger must match [a-z][a-z0-9]{3,15}, got %r" % (bad,)


def test_c3_normalize_phrase_collapses_whitespace():
    assert character_lib.normalize_phrase("  the   woman in\ngrey ") == "the woman in grey"


def test_c4_normalize_phrase_rejects():
    for bad in ("", "a b c d e f g", "the", "An", "the ronin=", "the (ronin)", 5):
        _raises(character_lib.normalize_phrase, bad)


def test_c5_normalize_phrase_keeps_apostrophes_and_hyphens():
    for ok in ("the ronin's ally", "o'brien", "half-elf"):
        assert character_lib.normalize_phrase(ok) == ok


def test_c6_auto_trigger_table():
    assert character_lib.auto_trigger("kyra", "woman", set()) == "kyrawmn"
    assert character_lib.auto_trigger("ronin", "man", set()) == "roninmn"
    assert character_lib.auto_trigger("kyra", "woman", {"kyrawmn"}) == "kyrawmn2"
    assert character_lib.auto_trigger("kyra", "woman", {"kyrawmn", "kyrawmn2"}) == "kyrawmn3"
    assert character_lib.auto_trigger("a1", "man", set()) == "amnx"
    assert character_lib.auto_trigger("ab-cd", "person", set()) == "abcdprs"


def test_c7_auto_trigger_avoids_phrase_words():
    assert character_lib.auto_trigger("ronin", "man", set(), avoid=["the", "roninmn"]) == "roninmn2"


# --- C8-C15: validate_character (spec 2.3) ----------------------------------------------
def test_c8_valid_for_every_status(lib_dir):
    for status in ("dataset", "untrained", "trained"):
        data = make_character(lib_dir, name="c-%s" % status, status=status)
        if status == "dataset":
            assert data["dataset"] is None
        character_lib.validate_character(data)
        character_lib.validate_character(data, name="c-%s" % status)


def test_c9_exact_top_level_keys(lib_dir):
    data = make_character(lib_dir)
    assert len(data) == 14
    for key in list(data):
        broken = copy.deepcopy(data)
        del broken[key]
        assert key in _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["extra_key"] = 1
    assert "extra_key" in _raises(character_lib.validate_character, broken)


def test_c10_status_consistency(lib_dir):
    data = make_character(lib_dir)
    broken = copy.deepcopy(data)
    broken["loras"]["video"] = None
    _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["status"] = "untrained"
    _raises(character_lib.validate_character, broken)
    untrained = make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin",
                               class_noun="man", status="untrained")
    untrained["dataset"]["kept"] = 11
    _raises(character_lib.validate_character, untrained)


def test_c11_lora_entry_rules(lib_dir):
    data = make_character(lib_dir)
    for key, value in (("alpha", 16), ("sha256", "ABC"), ("path", "lora/video.safetensors"),
                       ("rank", True)):
        broken = copy.deepcopy(data)
        broken["loras"]["video"][key] = value
        _raises(character_lib.validate_character, broken)


def test_c12_strength(lib_dir):
    data = make_character(lib_dir)
    for bad in (0, 1.5, True, "0.8"):
        broken = copy.deepcopy(data)
        broken["strength"] = bad
        _raises(character_lib.validate_character, broken)
    for ok in (None, 0.6, 1):
        good = copy.deepcopy(data)
        good["strength"] = ok
        character_lib.validate_character(good)


def test_c13_trigger_collisions(lib_dir):
    data = make_character(lib_dir)
    broken = copy.deepcopy(data)
    broken["trigger"] = "woman"
    _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["trigger"] = "ronin"
    broken["referring_phrase"] = "the Ronin"
    _raises(character_lib.validate_character, broken)


def test_c14_source(lib_dir):
    data = make_character(lib_dir)
    for bad in ({"type": "seed_image"}, {"type": "descriptor", "path": "/x"}, {"type": "web"}):
        broken = copy.deepcopy(data)
        broken["source"] = bad
        _raises(character_lib.validate_character, broken)
    good = copy.deepcopy(data)
    good["source"] = {"type": "descriptor"}
    character_lib.validate_character(good)


def test_c15_descriptor(lib_dir):
    data = make_character(lib_dir)
    for bad in (DESCRIPTOR + ".", "The" + DESCRIPTOR[1:], "a young woman with long black hair",
                "a " + " ".join(["word"] * 60)):
        broken = copy.deepcopy(data)
        broken["descriptor"] = bad
        assert _raises(character_lib.validate_character, broken).startswith("descriptor: ")


# --- C16-C20: load, write, list, triggers (spec 3.1) ------------------------------------
def test_c16_unknown_character(lib_dir):
    message = _raises(character_lib.load_character, "ghost")
    assert message == "unknown character: ghost (no %s)" % os.path.join(
        lib_dir, "ghost", "character.json")


def test_c17_invalid_json(lib_dir):
    make_character(lib_dir)
    path = os.path.join(lib_dir, "kyra", "character.json")
    with open(path, "w") as f:
        f.write("{bad")
    assert _raises(character_lib.load_character, "kyra").startswith(
        "invalid character.json for kyra: ")
    with open(path, "w") as f:
        json.dump({"name": "kyra"}, f)
    assert _raises(character_lib.load_character, "kyra").startswith(
        "invalid character.json for kyra: ")


def test_c18_write_round_trip_and_atomicity(lib_dir):
    data = make_character(lib_dir)
    data["strength"] = 0.7
    character_lib.write_character(data)
    assert character_lib.load_character("kyra") == data
    path = os.path.join(lib_dir, "kyra", "character.json")
    with open(path, "rb") as f:
        before = f.read()
    broken = copy.deepcopy(data)
    broken["seed"] = -1
    _raises(character_lib.write_character, broken)
    with open(path, "rb") as f:
        assert f.read() == before
    assert [n for n in os.listdir(os.path.join(lib_dir, "kyra")) if n.endswith(".tmp")] == []


def test_c19_list_names(tmp_path, lib_dir):
    assert character_lib.list_names() == []
    make_character(lib_dir)
    os.makedirs(os.path.join(lib_dir, "bad"))
    for hidden in (".hidden", "Upper"):
        os.makedirs(os.path.join(lib_dir, hidden))
        with open(os.path.join(lib_dir, hidden, "character.json"), "w") as f:
            f.write("{}")
    with open(os.path.join(lib_dir, ".triggers"), "w") as f:
        f.write("kyrawmn kyra\n")
    assert character_lib.list_names() == ["kyra"]


def test_c20_registered_triggers(lib_dir):
    os.makedirs(os.path.join(lib_dir, "ghost"))
    with open(os.path.join(lib_dir, ".triggers"), "w") as f:
        f.write("kyrawmn kyra\ngarbage\nroninmn ronin\n")
    with open(os.path.join(lib_dir, "ghost", "character.json"), "w") as f:
        json.dump({"trigger": "ghosttt"}, f)
    assert character_lib.registered_triggers() == {
        "kyrawmn": "kyra", "roninmn": "ronin", "ghosttt": "ghost"}
    character_lib.register_trigger("newtrig", "newbie")
    assert character_lib.registered_triggers()["newtrig"] == "newbie"


# --- C21-C22: --cast parsing (spec 3.4) ---------------------------------------------------
def test_c21_parse_cast_arg():
    assert character_lib.parse_cast_arg("the woman in grey=kyra") == ("the woman in grey", "kyra")
    _raises(character_lib.parse_cast_arg, "a=b=kyra")
    assert character_lib.parse_cast_arg("the ronin = ronin") == ("the ronin", "ronin")


def test_c22_parse_cast_arg_rejects():
    assert _raises_unusable(character_lib.parse_cast_arg, "the ronin") == (
        "--cast must be PHRASE=NAME, got 'the ronin'", False)
    assert _raises_unusable(character_lib.parse_cast_arg, "the ronin=Bad Name") == (
        "character name must match [a-z][a-z0-9-]{1,23}, got 'Bad Name'", True)


# --- C23-C34: matching and trigger insertion (spec 3.6) ---------------------------------


def test_c23_article_case_kept():
    assert character_lib.cast_text("The woman in grey rides.", [KYRA]) == (
        "The kyrawmn woman in grey rides.", ["kyra"])


def test_c24_every_occurrence():
    assert character_lib.cast_text(
        "He bows to the woman in grey; the woman in grey nods.", [KYRA]) == (
        "He bows to the kyrawmn woman in grey; the kyrawmn woman in grey nods.", ["kyra"])


def test_c25_possessives():
    assert character_lib.cast_text("the ronin's blade", [RONIN]) == (
        "the roninmn ronin's blade", ["ronin"])
    assert character_lib.cast_text("the ronin's blade", [RONIN]) == (
        "the roninmn ronin's blade", ["ronin"])


def test_c26_word_boundaries():
    for text in ("the ronins", "the ronin-like", "bathe ronin", "theronin"):
        assert character_lib.cast_text(text, [RONIN]) == (text, [])
    assert character_lib.cast_text("the woman in grey-blue robe", [KYRA]) == (
        "the woman in grey-blue robe", [])


def test_c27_longest_phrase_first():
    x = member("x", "the woman", "xtrig")
    assert character_lib.cast_text("the woman in grey and the woman", [x, KYRA]) == (
        "the kyrawmn woman in grey and the xtrig woman", ["kyra", "x"])


def test_c28_no_article_prefixes():
    named = member("kyra", "Kyra", "kyrawmn")
    assert character_lib.cast_text("Kyra smiles at kyra.", [named]) == (
        "kyrawmn Kyra smiles at kyrawmn kyra.", ["kyra"])


def test_c29_idempotent():
    x = member("x", "the woman", "xtrig")
    named = member("kyra", "Kyra", "kyrawmn")
    cases = [("The woman in grey rides.", [KYRA]),
             ("He bows to the woman in grey; the woman in grey nods.", [KYRA]),
             ("the ronin's blade", [RONIN]), ("the ronin's blade", [RONIN]),
             ("the ronins", [RONIN]), ("the ronin-like", [RONIN]), ("bathe ronin", [RONIN]),
             ("the woman in grey-blue robe", [KYRA]), ("theronin", [RONIN]),
             ("the woman in grey and the woman", [x, KYRA]),
             ("Kyra smiles at kyra.", [named])]
    for text, members in cases:
        once = character_lib.cast_text(text, members)
        assert character_lib.cast_text(once[0], members) == once


def test_c30_whitespace_runs():
    assert character_lib.cast_text("the woman\n in  grey", [KYRA]) == (
        "the kyrawmn woman\n in  grey", ["kyra"])


def test_c31_case_insensitive():
    assert character_lib.cast_text("THE RONIN draws.", [RONIN]) == (
        "THE roninmn RONIN draws.", ["ronin"])


def test_c32_article_a():
    stranger = member("stranger", "a stranger", "strgrmn")
    assert character_lib.cast_text("A stranger waits.", [stranger]) == (
        "A strgrmn stranger waits.", ["stranger"])


def test_c33_two_characters():
    assert character_lib.cast_text("The ronin shields the woman in grey.", [KYRA, RONIN]) == (
        "The roninmn ronin shields the kyrawmn woman in grey.", ["kyra", "ronin"])


def test_c34_phrase_occurs():
    assert character_lib.phrase_occurs("## Panel 1 — x\nMotion: The Ronin runs.", "the ronin")
    assert not character_lib.phrase_occurs("the ronins", "the ronin")


# --- C35-C38: resolve_cast and strengths (spec 3.5, 3.7) --------------------------------
def _two(lib_dir, ronin_strength=None):
    make_character(lib_dir)
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin",
                   class_noun="man", strength=ronin_strength)


def test_c35_resolve_cast_happy_path(lib_dir):
    _two(lib_dir)
    members = character_lib.resolve_cast([(None, "kyra"), ("the swordsman", "ronin")])
    assert [m.name for m in members] == ["kyra", "ronin"]
    assert members[0].phrase == "the woman in grey"
    assert members[1].phrase == "the swordsman"
    assert members[0].video_lora == os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    assert os.path.isabs(members[0].video_lora)
    assert members[0].stills_lora is None
    assert members[0].trigger == "kyrawmn" and members[1].class_noun == "man"


def test_c36_single_character_is_full_strength(lib_dir):
    _two(lib_dir)
    members = character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    assert character_lib.panel_strengths(["kyra"], members, 0.8) == {"kyra": 1.0}


def test_c37_override_and_default(lib_dir):
    _two(lib_dir, ronin_strength=0.6)
    members = character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    assert character_lib.panel_strengths(["kyra", "ronin"], members, 0.8) == {
        "kyra": 0.8, "ronin": 0.6}


def test_c38_resolve_cast_errors(lib_dir):
    resolve = character_lib.resolve_cast
    make_character(lib_dir)
    assert _raises_unusable(resolve, [(None, "ghost")]) == (
        "unknown character: ghost (no %s)" % os.path.join(lib_dir, "ghost", "character.json"),
        True)
    make_character(lib_dir, name="raw", trigger="rawtrig", status="untrained")
    assert _raises_unusable(resolve, [(None, "raw")]) == (
        "character raw is not trained (status untrained); run bin/character train raw", True)
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    os.remove(video)
    assert _raises_unusable(resolve, [(None, "kyra")]) == (
        "character kyra's video LoRA is missing or empty: %s" % video, True)
    open(video, "wb").close()
    assert _raises_unusable(resolve, [(None, "kyra")]) == (
        "character kyra's video LoRA is missing or empty: %s" % video, True)
    os.makedirs(os.path.join(lib_dir, "broken"))
    with open(os.path.join(lib_dir, "broken", "character.json"), "w") as f:
        f.write("{bad")
    message, unusable = _raises_unusable(resolve, [(None, "broken")])
    assert message.startswith("invalid character.json for broken: ") and unusable
    assert _raises_unusable(resolve, [(None, "Bad")]) == (
        "character name must match [a-z][a-z0-9-]{1,23}, got 'Bad'", True)
    make_character(lib_dir, name="sti", trigger="stitrig", stills=True)
    stills = os.path.join(lib_dir, "sti", "lora", "stills.safetensors")
    os.remove(stills)
    assert _raises_unusable(resolve, [(None, "sti")]) == (
        "character sti's stills LoRA is missing or empty: %s" % stills, False)
    make_character(lib_dir)
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man")
    assert _raises_unusable(resolve, [(None, "kyra"), ("the lady", "kyra")]) == (
        "character kyra is cast more than once", False)
    assert _raises_unusable(resolve, [("the ronin", "kyra"), ("The Ronin", "ronin")]) == (
        "cast phrase 'The Ronin' is used for both kyra and ronin", False)
    make_character(lib_dir, name="twin", trigger="kyrawmn", phrase="the twin")
    assert _raises_unusable(resolve, [(None, "kyra"), (None, "twin")]) == (
        "characters kyra and twin share the trigger kyrawmn", False)
    assert _raises_unusable(resolve, [("the kyrawmn", "kyra")]) == (
        "character kyra's trigger kyrawmn is a word of its cast phrase 'the kyrawmn'", False)


# --- C39-C41: the Cast block and the import rule (spec 1.2, 3.8) -------------------------
def test_c39_build_cast_block():
    assert character_lib.build_cast_block([KYRA, RONIN]) == (
        character_lib.CAST_BLOCK_HEADER + "\n"
        + '- "the woman in grey": ' + DESCRIPTOR + "." + "\n"
        + '- "the ronin": ' + DESCRIPTOR + "." + "\n"
        + character_lib.CAST_BLOCK_RULES)


def test_c40_cast_block_text():
    text = character_lib.CAST_BLOCK_HEADER + character_lib.CAST_BLOCK_RULES
    assert "{" not in text and "}" not in text
    assert text.count("word for word") == 2
    assert "longer than four words" in text


# --- C42-C46: cast discovery (spec 3.9, amendment) --------------------------------------
def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man",
                   status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def test_c42_format_available_line():
    assert character_lib.format_available_line([]) == (
        "available characters: none (create one with bin/character create)")
    assert character_lib.format_available_line(
        [("kyra", "the woman in grey"), ("ronin", "the ronin")]) == (
        "available characters: kyra (the woman in grey), ronin (the ronin)")


def test_c43_usable_characters(lib_dir):
    assert character_lib.usable_characters() == []
    make_character(lib_dir, name="zed", trigger="zedtrig", phrase="the zed", status="untrained")
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man")
    os.makedirs(os.path.join(lib_dir, "bad"))
    with open(os.path.join(lib_dir, "bad", "character.json"), "w") as f:
        f.write("{bad")
    make_character(lib_dir, name="gone", trigger="gonetrig", phrase="the gone")
    os.remove(os.path.join(lib_dir, "gone", "lora", "video.safetensors"))
    make_character(lib_dir, name="stl", trigger="stltrig", phrase="the stl", stills=True)
    os.remove(os.path.join(lib_dir, "stl", "lora", "stills.safetensors"))
    make_character(lib_dir)
    assert character_lib.usable_characters() == [("kyra", "the woman in grey"),
                                                 ("ronin", "the ronin")]


def test_c44_table_for_an_empty_library(lib_dir):
    assert character_lib.character_table_lines() == ["no characters in %s" % lib_dir]


def test_c45_table_rows(lib_dir):
    _c45_library(lib_dir)
    with pytest.raises(character_lib.CharacterError) as info:
        character_lib.load_character("bad")
    row = character_lib.LIST_ROW_FORMAT
    assert character_lib.character_table_lines() == [
        row % ("NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS", "PHRASE"),
        "%-16s (invalid: %s)" % ("bad", info.value),
        row % ("kyra", "kyrawmn", "trained", "yes", "no", "the woman in grey"),
        row % ("ronin", "roninmn", "untrained", "no", "no", "the ronin")]


def test_c46_unusable_is_a_character_error():
    assert issubclass(character_lib.UnusableCharacterError, character_lib.CharacterError)


def test_c41_stdlib_only_imports():
    path = os.path.join(WS, "character_lib.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    roots = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.append((node.module or "").split(".")[0])
    assert roots and set(roots) <= {"collections", "datetime", "json", "os", "re", "uuid"}
