"""Tests for the seeded-no-identity change (docs/superpowers/specs/2026-11-07-seeded-no-identity-
sentence-design.md: SIT1-SIT10): with a seed image in chained or shots mode, the Image: of chained
panel 1 and of every shots panel leaves out the cast identity sentences, so the seed's
description is not repeated in every still's prompt.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seeded_no_identity.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a model server: every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog)
and builds prompts and story.md text in memory or under tmp_path.
"""

import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_seeded_no_identity", "story_engine.py")
lib = _load("character_lib_for_seeded_no_identity", "character_lib.py")
ltx_movie = _load("ltx_movie_for_seeded_no_identity", os.path.join("bin", "ltx-movie"))

SEED = dict(seed_image="/s/seed.png", seed_agent_image="/s/seed-agent.png")
COURIER_ID = "The courier is " + seu.COURIER + "."
MONK_ID = "The old monk is " + seu.MONK + "."
MEDIUM = "The shot is a medium shot."
WIDE = "The shot is a wide shot."
FACING = "The courier faces the camera."


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _ctx(ws, mode, seeded, n=3, **kw):
    fields = dict(SEED) if seeded else {}
    fields.update(kw)
    return seu.make_ctx(se, ws, mode=mode, panels=n, **fields)


def _plan(ctx, n=3, speaker_beat=None, two_cast_beat=None):
    raw = seu.plan_json(ctx.mode, n)
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = raw["cast"][0]["id"]
    if two_cast_beat:
        raw["beats"][two_cast_beat - 1]["cast"] = ["c1", "c2"]
    return se.normalize_plan(ctx, raw)[0]


def _parts(ctx, plan, n=3, image=None):
    """Parsed writer parts of panel_json replies; image replaces every image reply."""
    parts = []
    for k in range(1, n + 1):
        reply = seu.panel_json(ctx.mode, k, plan["cast"][0]["phrase"])
        if image is not None and "image" in reply:
            reply["image"] = image
        if "dialogue" in se.panel_keys(ctx, plan, k):
            reply["dialogue"] = "The letter is here."
        parts.append(se.parse_panel_reply(ctx, plan, k, json.dumps(reply)))
    return parts


def _image(ctx, plan, parts, k):
    return dict(se.panel_fields(ctx, plan, parts, k))["Image"]


def _write(ctx, text, name="check.md"):
    path = os.path.join(ctx.story_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# --- SIT1: the condition (SI1) ------------------------------------------------------------------

def test_sit1_seed_omits_identities_only_for_a_seeded_chained_or_shots_movie(ws):
    cases = ((dict(mode="shots", **SEED), True), (dict(mode="chained", **SEED), True),
             (dict(mode="shots", seed_image="/s/seed.png"), True),
             (dict(mode="no_stills", **SEED), False),
             (dict(mode="shots", seed_agent_image="/s/seed-agent.png"), False),
             (dict(mode="chained", seed_agent_image="/s/seed-agent.png"), False),
             (dict(mode="shots"), False), (dict(mode="chained"), False))
    for kw, expected in cases:
        assert se.seed_omits_identities(seu.make_ctx(se, ws, **kw)) is expected, kw


# --- SIT2: a seeded shots Image: (SI1, SI2) -----------------------------------------------------

def test_sit2_seeded_shots_image_has_setting_facing_and_shot_but_no_identity(ws):
    ctx = _ctx(ws, "shots", True)
    plan = _plan(ctx, speaker_beat=1)
    assert se.pasted_pieces(ctx, plan, 1)["image"] == [seu.HARBOUR, FACING, MEDIUM]
    assert se.pasted_pieces(ctx, plan, 2)["image"] == [seu.HARBOUR, WIDE]
    parts = _parts(ctx, plan)
    for k, writer, tail in ((1, parts[0]["image"], FACING + " " + MEDIUM),
                            (2, parts[1]["image"], WIDE), (3, parts[2]["image"], MEDIUM)):
        image = _image(ctx, plan, parts, k)
        assert image == seu.HARBOUR + " " + writer + " " + tail, k
        assert seu.COURIER not in image and "The courier is " not in image, k


# --- SIT3: seeded chained panel 1, and later panels unchanged (SI1, SI2) ------------------------

def test_sit3_seeded_chained_panel_1_has_no_identity_and_later_panels_are_unchanged(ws):
    seeded, plain = _ctx(ws, "chained", True), _ctx(ws, "chained", False)
    splan, pplan = _plan(seeded, speaker_beat=1), _plan(plain, speaker_beat=1)
    assert se.pasted_pieces(seeded, splan, 1)["image"] == [seu.HARBOUR, FACING, MEDIUM]
    assert se.pasted_pieces(plain, pplan, 1)["image"] == [seu.HARBOUR, COURIER_ID, FACING, MEDIUM]
    assert (se.pasted_pieces(seeded, splan, 1)["motion"]
            == se.pasted_pieces(plain, pplan, 1)["motion"])
    for k in (2, 3):
        assert se.pasted_pieces(seeded, splan, k) == se.pasted_pieces(plain, pplan, k), k
    parts = _parts(seeded, splan)
    image = _image(seeded, splan, parts, 1)
    assert image == seu.HARBOUR + " " + parts[0]["image"] + " " + FACING + " " + MEDIUM
    for k in (2, 3):
        assert (se.panel_fields(seeded, splan, parts, k)
                == se.panel_fields(plain, pplan, parts, k)), k


# --- SIT4: unseeded and seed_agent_image-only runs are unchanged (SI5) --------------------------

def test_sit4_unseeded_images_keep_every_identity_sentence(ws):
    for mode in ("shots", "chained"):
        plain = _ctx(ws, mode, False)
        agent_only = _ctx(ws, mode, False, seed_agent_image="/s/seed-agent.png")
        plan = _plan(plain, two_cast_beat=1)
        assert se.pasted_pieces(plain, plan, 1)["image"] == [seu.HARBOUR, COURIER_ID, MONK_ID,
                                                             MEDIUM], mode
        parts = _parts(plain, plan)
        assert se.assemble(agent_only, plan, parts) == se.assemble(plain, plan, parts), mode
        assert COURIER_ID in _image(plain, plan, parts, 1), mode


# --- SIT5: no_stills keeps its identities, seeded or not (SI2) ----------------------------------

def test_sit5_no_stills_prompt_keeps_identities_even_with_a_seed(ws):
    seeded, plain = _ctx(ws, "no_stills", True), _ctx(ws, "no_stills", False)
    splan, pplan = _plan(seeded), _plan(plain)
    for k in (1, 2, 3):
        assert se.pasted_pieces(seeded, splan, k) == se.pasted_pieces(plain, pplan, k), k
        assert se.pasted_pieces(seeded, splan, k)["prompt"][0] == COURIER_ID, k
        assert se.writer_targets(seeded, splan, k) == se.writer_targets(plain, pplan, k), k


# --- SIT6: what follows from pasted_pieces (SI2) ------------------------------------------------

def test_sit6_writer_targets_cleanup_and_plan_budget_follow_pasted_pieces(ws):
    used = se._words(COURIER_ID)
    assert used == 22
    for mode, k, unseeded, seeded_targets in (("shots", 1, (32, 122), (54, 144)),
                                              ("chained", 1, (72, 122), (94, 144))):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        splan, pplan = _plan(seeded), _plan(plain)
        assert se.writer_targets(plain, pplan, k)["image"] == unseeded, mode
        assert se.writer_targets(seeded, splan, k)["image"] == seeded_targets, mode
        assert (se.writer_targets(seeded, splan, k)["motion"]
                == se.writer_targets(plain, pplan, k)["motion"]), mode
        assert "image: %d to %d words" % seeded_targets in se.build_panel_prompt(
            seeded, splan, _parts(seeded, splan), k), mode
        # cleanup_pieces: a writer image that copies the identity sentence keeps it when seeded.
        writer = COURIER_ID + " " + seu.panel_json(mode, k)["image"]
        assert COURIER_ID not in _parts(plain, pplan, image=writer)[0]["image"], mode
        assert _parts(seeded, splan, image=writer)[0]["image"].startswith(COURIER_ID), mode
    # Plan-scope P10: two long descriptors leave the writer too few image words unseeded only.
    long_desc = "a " + " ".join(["tall"] * 68) + " man"
    cast = [{"id": "c1", "phrase": "the courier", "descriptor": long_desc},
            {"id": "c2", "phrase": "the old monk", "descriptor": long_desc}]
    for seeded_run, expected in ((False, 1), (True, 0)):
        ctx = _ctx(ws, "shots", seeded_run)
        raw = seu.plan_json("shots", 3, cast=cast)
        raw["beats"][0]["cast"] = ["c1", "c2"]
        plan, shape = se.normalize_plan(ctx, raw)
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert len([m for m in hard + advisory if m.startswith("beat 1: P10 ")]) == expected


# --- SIT7: N6 is silent for a seeded Image: and still fires unseeded (SI3) ----------------------

def test_sit7_n6_skips_a_seeded_image(ws):
    bare = seu.HARBOUR + " The courier stands on the left of the frame. " + MEDIUM
    for mode in ("shots", "chained"):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        plan = _plan(plain)
        lib_ = se._character_lib(ws)
        args = (1, "t", [("Image", bare)], {"Image": bare}, ("N6",), ())
        assert se._field_checks(plain, lib_, plan, *args) == (
            [], ["panel 1: N6 description: Image: lacks c1's description word for word"]), mode
        assert se._field_checks(seeded, lib_, plan, *args) == ([], []), mode
        splan = _plan(seeded, two_cast_beat=1)
        parts = _parts(seeded, splan)
        text = se.assemble(seeded, splan, parts)
        hard, advisory = se.panel_checks(seeded, splan, parts, text, _write(seeded, text))
        assert [m for m in hard + advisory if " N6 " in m] == [], mode
    no_stills = _ctx(ws, "no_stills", True)
    plan = _plan(no_stills)
    prompt = seu.HARBOUR + " The courier pedals along the quay. " + MEDIUM
    assert se._field_checks(no_stills, se._character_lib(ws), plan, 1, "t", [("Prompt", prompt)],
                            {"Prompt": prompt}, ("N6",), ()) == (
        [], ["panel 1: N6 description: Prompt: lacks c1's description word for word"])


# --- SIT8: S9 is left out for a seeded shots story with library characters (SI4) ----------------

def _pinned_story(ws, story_env, seeded):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    ctx = _ctx(ws, "shots", seeded, n=4, members=members)
    raw = seu.plan_json("shots", 4)
    raw["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
                   {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    raw["beats"][2]["cast"] = ["c2"]
    plan = se.normalize_plan(ctx, raw)[0]
    parts = [se.parse_panel_reply(ctx, plan, k, json.dumps(
        seu.panel_json("shots", k, "the woman in grey"))) for k in range(1, 5)]
    return ctx, plan, parts, se.assemble(ctx, plan, parts)


def test_sit8_s9_is_left_out_of_a_seeded_shots_story(ws, story_env):
    ctx, plan, parts, text = _pinned_story(ws, story_env, True)
    path = _write(ctx, text)
    assert "The woman in grey is " not in text and '- "the woman in grey": ' in text
    panels = se._story_manifest(ws)._parse_prompts_md(path)[1]
    raw = lib.shots_violations(text, panels, 4, ctx.members, True, ignore_facing=True,
                               speaking_actions=2)
    s9 = [v for v in raw if " S9 " in v]
    assert [v.split(":")[0] for v in s9] == ["panel 1", "panel 4"]
    assert [v for v in se.split_shots(raw, ctx)[1] if " S9 " in v] == []
    assert [v for v in se.split_shots(raw)[1] if " S9 " in v] == s9
    assert se.split_shots(raw, ctx)[0] == se.split_shots(raw)[0]
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert [m for m in hard + advisory if " S9 " in m or " N6 " in m] == []
    plain_ctx, _plain_plan, _plain_parts, plain_text = _pinned_story(ws, story_env, False)
    assert "The woman in grey is %s." % seu.DESC_K in plain_text
    assert [v for v in se.split_shots(raw, plain_ctx)[1] if " S9 " in v] == s9


def test_sit8_recheck_of_a_seeded_shots_story_reports_no_s9(ws, story_env, monkeypatch, tmp_path,
                                                             capsys):
    seu.script_agent(monkeypatch, tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, _parts_, text = _pinned_story(ws, story_env, True)
    _write(ctx, text, "story.md")
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert [m for m in advisories if " S9 " in m] == []
    os.remove(os.path.join(ctx.story_dir, "plan.json"))     # the plan-free re-check path
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert [m for m in advisories if " S9 " in m] == []
    assert capsys.readouterr().err == ""


# --- SIT9: a seeded two-person shot still names both people (Review Focus 1) --------------------

def test_sit9_seeded_two_person_shot_names_both_phrases(ws):
    ctx = _ctx(ws, "shots", True)
    plan = _plan(ctx, two_cast_beat=1)
    writer = ("The courier stands on the left of the frame and faces right toward the old monk. "
              "The old monk stands on the right of the frame and faces left. "
              + seu.panel_json("shots", 1)["image"])
    parts = _parts(ctx, plan, image=writer)
    image = _image(ctx, plan, parts, 1)
    assert image == seu.HARBOUR + " " + writer + " " + MEDIUM
    assert "the courier" in image.lower() and "the old monk" in image.lower()
    assert COURIER_ID not in image and MONK_ID not in image
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert ('Characters on screen in this panel, named only by these exact referring phrases: '
            '"the courier"; "the old monk"\n') in prompt
    assert "where each character stands and which way they face" in prompt


# --- SIT10: a seeded story.md is the unseeded one without identity sentences (SI1, SI6) ---------

def test_sit10_seeded_story_md_is_unseeded_text_minus_identity_sentences(ws):
    for mode in ("shots", "chained"):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        plan = _plan(plain, speaker_beat=2, two_cast_beat=1)
        parts = _parts(plain, plan)
        plain_text = se.assemble(plain, plan, parts)
        seeded_text = se.assemble(seeded, plan, parts)
        assert plain_text.count(" " + COURIER_ID) == (3 if mode == "shots" else 1), mode
        assert plain_text.count(" " + MONK_ID) == 1, mode
        assert seeded_text == plain_text.replace(" " + COURIER_ID, "").replace(" " + MONK_ID, "")
        if mode == "shots":
            assert ('## Characters\n- "the courier": %s.\n- "the old monk": %s.\n'
                    % (seu.COURIER, seu.MONK)) in seeded_text
            images = [l for l in seeded_text.split("\n") if l.startswith("Image: ")]
            assert len(images) == 3 and all(l.startswith("Image: " + seu.HARBOUR + " ")
                                            for l in images)
            assert images[1].endswith(" " + FACING + " " + se.shot_sentence(plan["beats"][1]))
