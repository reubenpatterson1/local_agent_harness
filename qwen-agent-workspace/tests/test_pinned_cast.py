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


# --- PT6, PT7: P16 cast presence (PC1, PK4) ---------------------------------------------------

NAMES = {"c1": (KYRA, "kyra"), "c2": (RONIN, "ronin")}


def _p16(ctx, raw):
    """The P16 messages of plan_checks' hard list for the normalised raw reply."""
    plan, shape = se.normalize_plan(ctx, raw)
    return [m for m in se.plan_checks(ctx, plan, shape)[0] if " P16 " in m]


def test_pt6_p16_matrix(ws, story_env):
    members = _members(story_env)
    complete = {"chained": [["c1", "c2"]] * 3, "shots": [["c1"], ["c2"], ["c1", "c2"]],
                "no_stills": [["c1"], ["c2"], ["c1", "c2"]]}
    for mode in ("chained", "shots", "no_stills"):
        for narration in (True, "speech", False):
            ctx = seu.make_ctx(se, ws, mode=mode, members=members, narration=narration)
            for missing in (("c1",), ("c2",), ("c1", "c2")):
                cast = [c for c in ("c1", "c2") if c not in missing]
                found = _p16(ctx, _raw(mode, 3, [cast] * 3))
                where = (mode, narration, missing)
                assert found == [P16(c, NAMES[c][0], NAMES[c][1], mode, narration)
                                 for c in missing], where
                for message in found:
                    v = se.parse_violation(message)
                    assert (v["id"], v["name"], v["scope"]) == (
                        "P16", "cast presence", "plan"), where
            assert _p16(ctx, _raw(mode, 3, complete[mode])) == [], (mode, narration)


def test_pt7_p16_scope(ws, story_env):
    for mode in ("chained", "shots", "no_stills"):
        assert _p16(seu.make_ctx(se, ws, mode=mode), seu.plan_json(mode, 3)) == [], mode
    members = _members(story_env)
    raw = _raw("chained", 3, [["c1", "c2"]] * 3)
    raw["cast"].append({"id": "c3", "phrase": "the porter", "descriptor": "a man"})
    assert _p16(seu.make_ctx(se, ws, members=members), raw) == []
    one = seu.make_ctx(se, ws, members=lib.resolve_cast([(None, "kyra")]))
    raw = seu.plan_json("chained", 3, cast=[
        {"id": "c1", "phrase": "x", "descriptor": "a woman"},
        {"id": "c2", "phrase": "the porter", "descriptor": "a man"}])
    for beat in raw["beats"]:
        beat["cast"] = ["c2"]
    assert _p16(one, raw) == [P16("c1", KYRA, "kyra", "chained", True)]


# --- PT14, PT15, PT18, Review Focus 1: the plan retry and the fatal exit (PC2, PK5) ----------

def _panel_script(n, phrase=KYRA):
    """{"<k>": [one valid chained reply naming phrase]} for panels 1 to n."""
    return dict((str(k), [seu.answer(seu.panel_json("chained", k, phrase))])
                for k in range(1, n + 1))


def _read_json(story_dir, name):
    with open(os.path.join(story_dir, name), encoding="utf-8") as f:
        return json.load(f)


def _fatal_err(message_lines, ctx):
    return ("Error: the story model did not return a usable plan after 2 call(s)\n"
            + "".join("  - %s\n" % m for m in message_lines)
            + "Raw replies are kept in %s. Rerun the same command to try again.\n"
            % os.path.join(ctx.story_dir, "story_rounds", "round_0"))


def test_pt14_e2e_retry(movie, tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    log = seu.script_agent(
        monkeypatch, tmp_path,
        plan=[seu.answer(_raw("chained", 3, [["c1"]] * 3)),
              seu.answer(_raw("chained", 3, [["c1"], ["c1", "c2"], ["c1", "c2"]]))],
        panel=_panel_script(3))
    rc = ltx_movie.main([NARRATIVE, "--story-id", "pc1", "--panels", "3", "--character", "kyra",
                         "--character", "ronin", "--story-only", "--no-review"])
    log = seu.agent_log(log)
    assert rc == 0
    assert [r["stage"] for r in log][:3] == ["plan", "plan", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- "
            + P16("c2", RONIN, "ronin", "chained", True) + "\n") in log[1]["argv"][-1]
    story_dir = os.path.join(movie, "generated", "stories", "pc1")
    plan = _read_json(story_dir, "plan.json")
    assert ["c2" in beat["cast"] for beat in plan["beats"]] == [False, True, True]
    assert _read_json(story_dir, "story_checks.json")["hard"] == []


def test_pt15_e2e_exhausted(ws, tmp_path, monkeypatch, capsys, story_env):
    members = _members(story_env)
    bad = seu.answer(_raw("chained", 3, [["c1"]] * 3))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[bad, bad])
    ctx = seu.make_ctx(se, ws, story_id="pc2", members=members)
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    assert capsys.readouterr().err == _fatal_err([P16("c2", RONIN, "ronin", "chained", True)],
                                                 ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_pt18_seed_and_two_pinned_retried(ws, tmp_path, monkeypatch, story_env):
    members = _members(story_env)
    log = seu.script_agent(
        monkeypatch, tmp_path,
        plan=[seu.answer(_raw("chained", 3, [["c1"]] * 3)),
              seu.answer(_raw("chained", 3, [["c1"], ["c1", "c2"], ["c1", "c2"]]))],
        panel=_panel_script(3))
    ctx = seu.make_ctx(se, ws, story_id="pc3", members=members, seed_agent_image="/s/seed.png")
    rc, _advisories = se.run(ctx)
    assert rc == 0
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_prompt.txt"),
              encoding="utf-8") as f:
        assert se.SEED_CAST_SENTENCE in f.read()
    plans = [r for r in seu.agent_log(log) if r["stage"] == "plan"]
    assert len(plans) == 2
    for call in plans:
        assert call["argv"][call["argv"].index("--image") + 1] == "/s/seed.png"
    assert "- " + P16("c2", RONIN, "ronin", "chained", True) + "\n" in plans[1]["argv"][-1]


def test_review_focus_1_an_exhausted_plan_lists_every_fatal_problem(ws, tmp_path, monkeypatch,
                                                                     capsys, story_env):
    members = _members(story_env)
    short = seu.answer(_raw("chained", 2, [["c1"]] * 2))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[short, short])
    ctx = seu.make_ctx(se, ws, story_id="pc4", members=members)
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    assert capsys.readouterr().err == _fatal_err(
        ["plan: P1 beat count: expected exactly 3 beats, found 2",
         P16("c2", RONIN, "ronin", "chained", True)], ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


# --- Review Focus 2: a beat cast that names a pinned member by phrase (PC1) -------------------

def test_review_focus_2_a_beat_cast_that_names_a_member_by_phrase(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members)
    plan, shape = se.normalize_plan(ctx, _raw("chained", 3, [["c1"], ["c1", "the ronin"], ["c1"]]))
    hard = se.plan_checks(ctx, plan, shape)[0]
    assert "beat 2: P2 structure: cast id 'the ronin' is not defined" in hard
    assert hard[-1] == P16("c2", RONIN, "ronin", "chained", True)


# --- PT8-PT10, Review Focus 3: the speaking-beat coercion (PC7, PK7) --------------------------

PORTER = {"id": "c3", "phrase": "the porter", "descriptor": "a man"}
KEEP_NOTE = ("beat 2: P14 speaking beat: cast [%s] changed to [%s]: the speaker, and the library "
             "character(s) c2, who stay in frame without speaking")
ALONE_NOTE = ("beat 2: P14 speaking beat: cast [%s] changed to [%s] so the speaker is alone on "
              "screen")


def _cast_notes(plan):
    return [n for n in plan["speech_notes"] if n.startswith("beat 2: P14 speaking beat: cast ")]


def test_pt8_chained_coercion_keeps_library_co_stars(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    cases = [(["c1", "c2", "c3"], "c1", ["c1", "c2"], KEEP_NOTE % ("c1, c2, c3", "c1, c2")),
             (["c2", "c1"], "c1", ["c2", "c1"], None),
             (["c2"], "c1", ["c1", "c2"], KEEP_NOTE % ("c2", "c1, c2")),
             (["c1", "c1"], "c1", ["c1"], ALONE_NOTE % ("c1, c1", "c1")),
             (["c1", "c2", "c3"], "c3", ["c1", "c2", "c3"], None)]
    for cast, speaker, expected, note in cases:
        raw = _raw("chained", 3, [["c1"], cast, ["c1", "c2"]], ["", speaker, ""])
        raw["cast"].append(dict(PORTER))
        plan, shape = se.normalize_plan(ctx, raw)
        where = (cast, speaker)
        assert plan["beats"][1]["speaker"] == speaker, where
        assert plan["beats"][1]["cast"] == expected, where
        assert _cast_notes(plan) == ([note] if note else []), where
        ids = [se.parse_violation(m)["id"] for m in se.plan_checks(ctx, plan, shape)[0]]
        assert "P16" not in ids and "P2" not in ids, (where, ids)


def test_pt9_shots_coercion_is_unchanged_with_members(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, mode="shots", members=members)
    plan, shape = se.normalize_plan(ctx, _raw("shots", 3, [["c1"], ["c1", "c2"], ["c1"]],
                                              ["", "c1", ""]))
    assert plan["beats"][1]["cast"] == ["c1"]
    assert plan["speech_notes"][0] == ALONE_NOTE % ("c1, c2", "c1")
    assert P16("c2", RONIN, "ronin", "shots", True) in se.plan_checks(ctx, plan, shape)[0]
    plan, shape = se.normalize_plan(ctx, _raw("shots", 3, [["c1"], ["c1", "c2"], ["c2"]],
                                              ["", "c1", ""]))
    assert [m for m in se.plan_checks(ctx, plan, shape)[0] if " P16 " in m] == []


def test_pt10_chained_k1_shot_with_co_stars(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")

    def coerced(k, cast, shot):
        casts = [["c1", "c2"], ["c1", "c2"], ["c1", "c2"]]
        casts[k - 1] = cast
        speakers = ["", "", ""]
        speakers[k - 1] = "c1"
        raw = _raw("chained", 3, casts, speakers)
        raw["beats"][k - 1]["shot"] = shot
        return se.normalize_plan(ctx, raw)[0]["beats"][k - 1]["shot"]

    for shot in ("wide shot", "extreme wide shot", "extreme close-up"):
        assert coerced(1, ["c1", "c2"], shot) == "medium shot", shot
    for shot in ("medium close-up", "close-up", "medium shot"):
        assert coerced(1, ["c1", "c2"], shot) == shot, shot
    assert coerced(1, ["c1"], "wide shot") == "medium close-up"
    assert coerced(1, ["c1"], "extreme close-up") == "close-up"
    assert coerced(2, ["c1", "c2"], "wide shot") == "wide shot"


def test_review_focus_3_a_speaker_named_by_phrase_and_a_repeated_co_star(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    plan, shape = se.normalize_plan(ctx, _raw("chained", 3, [["c1"], ["c2", "c2", "c1"], ["c1"]],
                                              ["", "The Woman in Grey", ""]))
    beat = plan["beats"][1]
    assert (beat["speaker"], beat["cast"]) == ("c1", ["c2", "c1"])
    assert _cast_notes(plan) == [
        "beat 2: P14 speaking beat: cast [c2, c2, c1] changed to [c2, c1]: the speaker, and the "
        "library character(s) c2, who stay in frame without speaking"]
    assert se.plan_checks(ctx, plan, shape)[0] == []


# --- PT1 (writer half): the writer constants and _and_list (PC8) ------------------------------

SILENT_CAST_MOTION_SENTENCE = (" Also in frame in this panel, and silent: @@SILENT@@. Only "
                               "@@SPEAKER@@ speaks: mention each of the others by their referring "
                               "phrase, word for word, only inside the sentences that begin with "
                               "@@SPEAKER@@, and never give them a speaking verb.")
SPEAKING_IMAGE_SILENT_SENTENCE = (" @@SPEAKER@@ is in the foreground, facing the camera; also in "
                                  "frame, and silent: @@SILENT@@; any crowd stays in the "
                                  "background.")


def test_pt1_writer_constants_and_and_list():
    assert se.SILENT_CAST_MOTION_SENTENCE == SILENT_CAST_MOTION_SENTENCE
    assert se.SPEAKING_IMAGE_SILENT_SENTENCE == SPEAKING_IMAGE_SILENT_SENTENCE
    for text in (SILENT_CAST_MOTION_SENTENCE, SPEAKING_IMAGE_SILENT_SENTENCE):
        assert set(re.findall(r"@@[A-Z_]+@@", text)) <= {"@@SPEAKER@@", "@@SILENT@@"}, text[:40]
    assert se._and_list(["a"]) == '"a"'
    assert se._and_list(["a", "b"]) == '"a" and "b"'
    assert se._and_list(["a", "b", "c"]) == '"a", "b" and "c"'


# --- PT11-PT13, Review Focus 4, 5: the writer prompt, N17 and the speech (PC8, PC9, PK8) ------

def _fill(text, silent='"the ronin"'):
    return text.replace("@@SPEAKER@@", '"the woman in grey"').replace("@@SILENT@@", silent)


def _key_line(prompt, key):
    """The first line of a panel prompt that starts with "<key>: " (its key line)."""
    return [line for line in prompt.split("\n") if line.startswith(key + ": ")][0]


def _speaking_plan(ctx, beat2_cast=("c1", "c2")):
    """PT11's normalised plan: beats 1 and 2 spoken by c1, beat 3 silent, every beat cast
    ["c1", "c2"] except beat 2's beat2_cast."""
    raw = _raw("chained", 3, [["c1", "c2"], list(beat2_cast), ["c1", "c2"]], ["c1", "c1", ""])
    return se.normalize_plan(ctx, raw)[0]


def _prompts(ctx, plan, fix=None):
    parts = [se.empty_parts("chained", k, plan, ctx) for k in (1, 2, 3)]
    return [se.build_panel_prompt(ctx, plan, parts, k, fix=fix) for k in (1, 2, 3)]


ON_SCREEN_LINE = ('Characters on screen in this panel, named only by these exact referring '
                  'phrases: "the woman in grey"; "the ronin"\n')


def test_pt11_writer_prompt(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    prompts = _prompts(ctx, _speaking_plan(ctx))
    assert _key_line(prompts[0], "image").endswith(
        se.SPEECH_FRAMING_SENTENCE + _fill(se.SPEAKING_IMAGE_SILENT_SENTENCE))
    assert _key_line(prompts[1], "motion").endswith(
        _fill(se.SPEAKING_CHAINED_MOTION_SENTENCE + se.SILENT_CAST_MOTION_SENTENCE))
    assert ON_SCREEN_LINE in prompts[0] and ON_SCREEN_LINE in prompts[1]
    for text in (se.SILENT_CAST_MOTION_SENTENCE, se.SPEAKING_IMAGE_SILENT_SENTENCE):
        assert text not in prompts[2] and _fill(text) not in prompts[2]
    assert "and silent:" not in prompts[2]
    alone = _prompts(ctx, _speaking_plan(ctx, beat2_cast=("c1",)))
    motion = _key_line(alone[1], "motion")
    assert motion.endswith(se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@",
                                                                       '"the woman in grey"'))
    assert "silent" not in motion
    for prompt in prompts + alone:
        assert "@@" not in prompt


N17_FIELDS = [("Motion", "The woman in grey steps toward the camera. The woman in grey faces the "
                         "camera. The camera stays static."),
              ("Dialogue", "the woman in grey: Stay close to me.")]
N17_WRITERS = {"Motion": "The woman in grey steps toward the camera."}
ONLY_THE_SPEAKER = "a speaking shot shows only the speaker"


def test_pt12_n17(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    hard, advisory = se._field_checks(ctx, lib, _speaking_plan(ctx), 2, "T", N17_FIELDS,
                                      N17_WRITERS, ("N17",), [])
    assert [m for m in hard + advisory if ONLY_THE_SPEAKER in m] == []
    shots = seu.make_ctx(se, ws, mode="shots", members=members, narration="speech")
    plan = se.normalize_plan(shots, _raw("shots", 3, [["c1"], ["c1"], ["c2"]], ["", "c1", ""]))[0]
    plan["beats"][1]["cast"] = ["c1", "c2"]
    hard, advisory = se._field_checks(shots, lib, plan, 2, "T", N17_FIELDS, N17_WRITERS,
                                      ("N17",), [])
    assert [m for m in advisory if ONLY_THE_SPEAKER in m] == [
        "panel 2: N17 speaking shot: Dialogue: 'the woman in grey' speaks in a shot that also "
        "shows 'the ronin'; a speaking shot shows only the speaker"]


def test_pt13_speech_stays_with_the_speaker():
    say = lib.speech_text(KYRA, "Stay close to me.", "beats")
    first = "The woman in grey steps toward the camera as the ronin waits beside her."
    second = "The woman in grey walks under the gate, the ronin a pace behind her."
    tail = "The woman in grey faces the camera. The camera stays static."
    one = lib.insert_speech(first + " " + tail, say, [KYRA], first_action=True)
    assert one == (first + " The woman in grey faces the camera. " + say
                   + " The camera stays static.")
    two = lib.insert_speech(first + " " + second + " " + tail, say, [KYRA], first_action=True)
    assert two == (first + " The woman in grey faces the camera. " + say + " " + second
                   + " The camera stays static.")
    for text in (one, two):
        assert "the ronin says" not in text


def test_review_focus_4_a_writer_re_ask_keeps_one_silent_sentence(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    plan = _speaking_plan(ctx)
    parts = [se.empty_parts("chained", k, plan, ctx) for k in (1, 2, 3)]
    parts[1]["motion"] = "The woman in grey turns, then steps toward the camera."
    problem = "panel 2: N12 one action: Motion: chains actions with 'then'"
    first = se.build_panel_prompt(ctx, plan, parts, 2)
    again = se.build_panel_prompt(ctx, plan, parts, 2, fix=[problem])
    assert "\n" + _key_line(first, "motion") + "\n" in again
    silent = _fill(se.SILENT_CAST_MOTION_SENTENCE)
    assert first.count(silent) == 1 and again.count(silent) == 1
    assert "- " + problem + "\n" in again
    assert "\nmotion: The woman in grey turns, then steps toward the camera.\n" in again
    assert "@@" not in again


DESC_A = "a tall young woman with short red hair wearing a green hunting cloak and leather boots"


def test_review_focus_5_three_library_characters_in_one_speaking_panel(ws, story_env):
    _members(story_env)
    seu.make_character(story_env["lib"], "hana", "hanawmn", "the archer", "woman", DESC_A)
    members = lib.resolve_cast([(None, "kyra"), (None, "ronin"), (None, "hana")])
    ctx = seu.make_ctx(se, ws, members=members, narration="speech")
    raw = seu.plan_json("chained", 3, cast=copy.deepcopy(CAST2) + [
        {"id": "c3", "phrase": "z", "descriptor": "a woman"}])
    for beat in raw["beats"]:
        beat["cast"] = ["c2", "c1", "c3"]
    raw["beats"][1]["speaker"] = "c1"
    plan, shape = se.normalize_plan(ctx, raw)
    assert plan["beats"][1]["cast"] == ["c2", "c1", "c3"]
    assert [m for m in se.plan_checks(ctx, plan, shape)[0] if " P16 " in m] == []
    prompt = _prompts(ctx, plan)[1]
    assert _key_line(prompt, "motion").endswith(
        _fill(se.SILENT_CAST_MOTION_SENTENCE, silent='"the ronin" and "the archer"'))
    assert ('Characters on screen in this panel, named only by these exact referring phrases: '
            '"the ronin"; "the woman in grey"; "the archer"\n') in prompt


# --- PT16, PT17: the reported case end to end, and the back-compat re-check (PK8, PK9) --------

def _pt16_run(ws, tmp_path, monkeypatch, story_env):
    """(rc, ctx, agent log) of PT16's engine run: chained, kyra and ronin pinned, --speech-only,
    LINES_NARRATIVE, every beat cast ["c1", "c2"], beats 2 and 3 spoken by c1."""
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, story_id="pc5", members=members, narration="speech",
                       narrative=LINES_NARRATIVE)
    raw = _raw("chained", 3, [["c1", "c2"]] * 3)
    raw["beats"][1].update(speaker="c1", lines=[1])
    raw["beats"][2].update(speaker="c1", lines=[2])
    panel = {
        "1": [seu.answer({"title": "The Temple Steps",
                          "image": seu.panel_json("chained", 1, KYRA)["image"],
                          "motion": "The woman in grey climbs the stone steps as the ronin "
                                    "follows one step behind her."})],
        "2": [seu.answer({"title": "Near The Top",
                          "motion": "The woman in grey turns and steps toward the camera, the "
                                    "ronin a pace behind her.",
                          "dialogue": "We reach the gate before dark."})],
        "3": [seu.answer({"title": "Through The Gate",
                          "motion": "The woman in grey walks under the gate toward the camera, "
                                    "the ronin beside her.",
                          "dialogue": "Stay close to me."})]}
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)], panel=panel)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def test_pt16_two_pinned_chained_every_line_spoken_by_c1(ws, tmp_path, monkeypatch, story_env):
    rc, ctx, log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [beat["cast"] for beat in plan["beats"]][1:] == [["c1", "c2"], ["c1", "c2"]]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    image = [line for line in lines if line.startswith("Image: ")][0]
    assert "The woman in grey is " + seu.DESC_K + "." in image
    assert "The ronin is " + seu.DESC_R + "." in image
    assert [line for line in lines if line.startswith("Dialogue: ")] == [
        "Dialogue: the woman in grey: We reach the gate before dark.",
        "Dialogue: the woman in grey: Stay close to me."]
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["hard"] == []
    assert [a for a in checks["advisory"] if ONLY_THE_SPEAKER in a["message"]] == []


def test_pt17_back_compat_recheck(ws, tmp_path, monkeypatch, story_env):
    rc, ctx, _log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    plan = _read_json(ctx.story_dir, "plan.json")
    for beat in plan["beats"]:
        beat["cast"] = ["c1"]
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not call plan_checks")

    monkeypatch.setattr(se, "plan_checks", refuse)
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["source"] == "recheck"
    assert [e["message"] for e in checks["hard"] + checks["advisory"]
            if " P16 " in e["message"]] == []


def test_final_i1_speaker_given_by_library_name(ws, story_env):
    members = _members(story_env)
    ctx = seu.make_ctx(se, ws, mode="chained", panels=3, members=members, narration="speech",
                       narrative=LINES_NARRATIVE)

    def planned(speakers, lines):
        raw = _raw("chained", 3, [["c1", "c2"]] * 3, speakers)
        for beat, beat_lines in zip(raw["beats"], lines):
            beat["lines"] = beat_lines
        return se.normalize_plan(ctx, raw)

    plan, shape = planned(["", "kyra", "  Kyra "], [[], [1], [2]])
    assert [b["speaker"] for b in plan["beats"][1:]] == ["c1", "c1"]
    assert [b["lines"] for b in plan["beats"][1:]] == [[1], [2]]
    for beat in plan["beats"]:
        assert "c1" in beat["cast"] and "c2" in beat["cast"]
    assert not [n for n in plan["speech_notes"] if "is not a cast id" in n]
    assert not [n for n in plan["speech_notes"] if "dropped: the beat has no speaker" in n]
    assert se.plan_checks(ctx, plan, shape)[0] == []

    plan, shape = planned(["", "ronin", ""], [[], [1], []])
    assert plan["beats"][1]["speaker"] == "c2"
