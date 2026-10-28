"""Tests for pinned cast presence (docs/superpowers/specs/2026-10-27-pinned-cast-presence-
design.md, Section 4.1: PT1-PT18, and the plan's Review Focus 1-5): every --character is in some
beat's cast (P16: a hard plan check, retried by the plan call and fatal when the retries run
out), the planner is told so by library name, a chained speaking beat keeps its library co-stars
in frame and silent, and speech stays with the speaker.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog). The fixtures
under tests/fixtures/pinned_cast/ are byte-exact plan prompts of three uncast runs, generated at
0c0160d before any edit to story_engine.py (spec 4.2).
"""

import copy
import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIX = os.path.join(WS, "tests", "fixtures", "pinned_cast")
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_pinned", "character_lib.py")
se = _load("story_engine_for_pinned", "story_engine.py")
ltx_movie = _load("ltx_movie_for_pinned", os.path.join("bin", "ltx-movie"))


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check (the
    movie fixture of test_story_engine.py)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


KYRA = "the woman in grey"
RONIN = "the ronin"
CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"},
         {"id": "c2", "phrase": "y", "descriptor": "a man"}]
LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')
# test_story_engine.NARRATIVE: no quoted lines, so a plan needs no lines.
NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."


def _members(story_env):
    """kyra (c1, "the woman in grey") and ronin (c2, "the ronin") from the test library."""
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    return lib.resolve_cast([(None, "kyra"), (None, "ronin")])


def _raw(mode, n, casts, speakers=None):
    """A plan reply for n beats with CAST2 (normalisation replaces both entries with the
    members): beat k gets cast casts[k - 1] and, when speakers is given, speaker
    speakers[k - 1]."""
    raw = seu.plan_json(mode, n, cast=copy.deepcopy(CAST2))
    for k, beat in enumerate(raw["beats"], start=1):
        beat["cast"] = list(casts[k - 1])
        if speakers is not None:
            beat["speaker"] = speakers[k - 1]
    return raw


def P16(cid, phrase, name, mode, narration):
    """The PC1 message, with the speaker suffix exactly when mode != "chained" and narration is
    not False."""
    message = ("plan: P16 cast presence: %s '%s' (library character %s) is in no beat's cast; "
               "every already-cast character must be on screen, so put %s in the cast of at "
               "least one beat" % (cid, phrase, name, cid))
    if mode != "chained" and narration is not False:
        message += ("; a beat with a speaker shows only the speaker, so that beat has no speaker "
                    "or %s is its speaker" % cid)
    return message


def _prompt(ws, **kw):
    """The plan prompt of make_ctx(**kw), with no catalog and no pins."""
    return se.build_plan_prompt(seu.make_ctx(se, ws, **kw), [], [])


# --- PT1: the plan constants, and the literals that keep their text (PC3-PC6) -----------------

CAST_FIXED_INTRO = (" The following characters are already cast; list them first in cast with "
                    "exactly these ids, phrases and descriptors, and give your own characters "
                    "the next ids. Every one of them is in this movie: put each one's id in the "
                    "cast of at least one beat. When the narrative calls one of them by their "
                    "name, it means that character, whom the movie names only by their phrase:")
CAST_FIXED_LINE = '\n- id c%d, name "%s", phrase "%s", descriptor "%s"'
SEED_CAST_SENTENCE = (" The already-cast characters listed below are not invented: each of them "
                      "is in this movie even when the image does not show them.")
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, and the camera may stay static, push in, pull back or track them, "
    "as long as their face stays in frame and lit while they speak.")
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker, even when two consecutive lines must then share a beat.")
UNCHANGED = {
    "SPEAKER_RULE": (
        " speaker is the id of the one character who says something aloud on screen during the "
        "beat, or an empty string when nobody speaks; give a speaker only where a spoken line "
        "moves the story. A beat with a speaker shows only that character (its cast is just "
        "their id), facing the camera, in a medium shot, medium close-up or close-up; the "
        "speaker may move during the beat, and the camera may stay static, push in, pull back or "
        "track them, as long as their face stays in frame and lit while they speak."),
    "LINES_RULE": (
        " lines is the list of the numbers of the spoken lines above that the speaker says aloud "
        "during the beat, in order, or an empty list. Every spoken line belongs to exactly one "
        "beat, in the narrative's order: give each line to the beat whose action surrounds it in "
        "the narrative, and give a speaker to every beat with lines and to no other beat. A beat "
        "may hold two or more consecutive lines only when together they are at most "
        "@@LINE_WORDS@@ words. Give each line its own beat whenever there are at least as many "
        "beats as lines."),
    "SEED_PARAGRAPH": (
        "An image is attached to this message. It IS the first frame of this movie. Describe "
        "every person it shows faithfully in cast -- each one's apparent age group, build, skin "
        "tone, hair, clothing and accessories as actually visible -- invent no person who is not "
        "visible, and make beat 1 start from the exact scene it shows.\n\n"),
    "SPEAKING_IMAGE_SENTENCE": (" @@SPEAKER@@ is the only person in the foreground, facing the "
                                "camera; any crowd stays in the background."),
    "SPEAKING_CHAINED_MOTION_SENTENCE": (
        " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after "
        "the first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
        "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it "
        "(if the dialogue comes before they do anything, it is how they turn or step toward the "
        "camera; never write only that they face it); only when the beat has them act after the "
        "dialogue, write what they do then as a second sentence. Begin each of these sentences "
        "with @@SPEAKER@@, word for word, and write nothing about anyone else before the first "
        "one. The action before the dialogue and the action after it are the two parts of this "
        "one motion: never put an action from before the dialogue and one from after it in the "
        "same sentence, and do not write the spoken words or a speaking verb; the pipeline adds "
        "them."),
}


def test_pt1_plan_constants():
    assert se.CAST_FIXED_INTRO == CAST_FIXED_INTRO
    assert se.CAST_FIXED_LINE == CAST_FIXED_LINE
    assert se.SEED_CAST_SENTENCE == SEED_CAST_SENTENCE
    assert se.SPEAKER_RULE_KEEP_CAST == SPEAKER_RULE_KEEP_CAST
    assert se.LINES_PINNED_SENTENCE == LINES_PINNED_SENTENCE
    for name, text in UNCHANGED.items():
        assert getattr(se, name) == text, name
    for text in (CAST_FIXED_INTRO, CAST_FIXED_LINE, SEED_CAST_SENTENCE, SPEAKER_RULE_KEEP_CAST,
                 LINES_PINNED_SENTENCE):
        assert re.findall(r"@@[A-Z_]+@@", text) == [], text[:40]


# --- PT2-PT5: the plan prompt (PC3-PC6) --------------------------------------------------------

FIXTURE_CASES = {
    "uncast_chained_lines.txt": dict(mode="chained", narration="speech", narrative=LINES_NARRATIVE),
    "uncast_shots_lines.txt": dict(mode="shots", panels=4, narration="speech",
                                   narrative=LINES_NARRATIVE),
    "uncast_chained_seed.txt": dict(mode="chained", seed_agent_image="/s/seed.png"),
}


def test_pt2_fixed_cast_block_and_uncast_byte_identity(ws, story_env):
    # The fixtures first: once the library holds kyra and ronin, an uncast prompt also lists
    # them as names never to use (Plan decision 5).
    for name in sorted(FIXTURE_CASES):
        with open(os.path.join(FIX, name), encoding="utf-8") as f:
            expected = f.read()
        assert _prompt(ws, **FIXTURE_CASES[name]) == expected, name
    members = _members(story_env)
    block = (se.CAST_FIXED_INTRO
             + '\n- id c1, name "kyra", phrase "the woman in grey", descriptor "%s"' % seu.DESC_K
             + '\n- id c2, name "ronin", phrase "the ronin", descriptor "%s"' % seu.DESC_R)
    for mode in ("chained", "shots"):
        prompt = _prompt(ws, mode=mode, members=members)
        assert block in prompt, mode
        assert '\n- id c1, phrase "' not in prompt, mode


def test_pt3_seed_carve_out(ws, story_env):
    members = _members(story_env)
    seeded = _prompt(ws, members=members, seed_agent_image="/s/seed.png")
    assert se.SEED_PARAGRAPH[:-2] + se.SEED_CAST_SENTENCE + "\n\n" in seeded
    uncast = _prompt(ws, seed_agent_image="/s/seed.png")
    assert se.SEED_PARAGRAPH in uncast and se.SEED_CAST_SENTENCE not in uncast
    assert se.SEED_CAST_SENTENCE not in _prompt(ws, members=members)


def test_pt4_speaker_rule_variants(ws, story_env):
    members = _members(story_env)
    chained = _prompt(ws, mode="chained", members=members)
    assert se.SPEAKER_RULE_KEEP_CAST in chained and se.SPEAKER_RULE not in chained
    for where, prompt in (("shots", _prompt(ws, mode="shots", members=members)),
                          ("chained uncast", _prompt(ws, mode="chained"))):
        assert se.SPEAKER_RULE in prompt and se.SPEAKER_RULE_KEEP_CAST not in prompt, where
    silent = _prompt(ws, mode="chained", members=members, narration=False)
    assert se.SILENT_SPEAKER_RULE in silent
    assert se.SPEAKER_RULE not in silent and se.SPEAKER_RULE_KEEP_CAST not in silent


def test_pt5_lines_sentence_variants(ws, story_env):
    members = _members(story_env)

    def build(**kw):
        ctx = seu.make_ctx(se, ws, **kw)
        cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))
        return se.build_plan_prompt(ctx, [], []), se.LINES_RULE.replace("@@LINE_WORDS@@", cap)

    for mode in ("shots", "no_stills"):
        prompt, rule = build(mode=mode, members=members, narrative=LINES_NARRATIVE)
        assert rule + se.LINES_PINNED_SENTENCE in prompt, mode
    for where, kw in (("chained", dict(mode="chained", members=members)),
                      ("shots uncast", dict(mode="shots"))):
        prompt, rule = build(narrative=LINES_NARRATIVE, **kw)
        assert rule in prompt and se.LINES_PINNED_SENTENCE not in prompt, where
    for mode in ("chained", "shots", "no_stills"):
        prompt, rule = build(mode=mode, members=members)
        assert rule not in prompt and se.LINES_PINNED_SENTENCE not in prompt, mode
