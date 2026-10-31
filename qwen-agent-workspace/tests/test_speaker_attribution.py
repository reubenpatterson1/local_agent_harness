"""Tests for speaker attribution (docs/superpowers/specs/2026-10-28-speaker-attribution-
design.md, Section 4.1: SAT1-SAT10, and the plan's Review Focus 1-5): a quoted line keeps the
speaker the narrative names. line_speakers extracts the attribution, P17 "line speaker" is a hard
plan check (retried by the plan call, fatal when the retries run out), assign_missing_lines and
q1_dialogue_patch never give an attributed line to another speaker, and the plan prompt tells
the planner which lines belong to already-cast characters.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_speaker_attribution.py
Stdlib plus pytest. No test renders, reads the real HOME, or contacts a model server, a daemon or
the Anthropic API: every model call goes to the fake bin/qwen-agent of a temp workspace
(story_engine_testutil.make_ws), every ctx lives under tmp_path, and every test runs under the
autouse story_env fixture (a temporary HOME, character library and LoRA catalog). The fixture
tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt is a byte-exact copy of the plan
reply of the live pin-sh2 run at e254e65 (spec G3).
"""

import copy
import hashlib
import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIX = os.path.join(WS, "tests", "fixtures", "speaker_attribution", "pin_sh2_plan_reply_1.txt")
FIX_SHA256 = "4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374"
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


lib = _load("character_lib_for_attribution", "character_lib.py")
se = _load("story_engine_for_attribution", "story_engine.py")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


# --- Copied verbatim from tests/test_pinned_cast.py (spec 4.1) ---------------------------------

KYRA = "the woman in grey"
RONIN = "the ronin"
CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"},
         {"id": "c2", "phrase": "y", "descriptor": "a man"}]
LINES_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                   'one step behind her. Near the top Kyra turns and says, "We reach the gate '
                   'before dark." They pass under the gate together, and Kyra says, "Stay close '
                   'to me."')


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


def _read_json(story_dir, name):
    with open(os.path.join(story_dir, name), encoding="utf-8") as f:
        return json.load(f)


def _fatal_err(message_lines, ctx):
    return ("Error: the story model did not return a usable plan after 2 call(s)\n"
            + "".join("  - %s\n" % m for m in message_lines)
            + "Raw replies are kept in %s. Rerun the same command to try again.\n"
            % os.path.join(ctx.story_dir, "story_rounds", "round_0"))


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


# --- Extra helpers (spec 4.1) ----------------------------------------------------------------

CAST3 = [{"id": "c1", "phrase": KYRA, "cast_name": "kyra"},
         {"id": "c2", "phrase": RONIN, "cast_name": "ronin"},
         {"id": "c3", "phrase": "the old monk", "cast_name": None}]
PRONOUN_NARRATIVE = (LINES_NARRATIVE.replace("Near the top Kyra turns", "Near the top she turns")
                     .replace("and Kyra says", "and she says"))
MONK_NARRATIVE = 'The courier reaches the temple gate, and the old monk says, "Enter."'


def P17(k, n, line, want, want_phrase, got, got_phrase):
    """The SA2 message for beat k and spoken line n."""
    return ("beat %d: P17 line speaker: the narrative gives spoken line %d \"%s\" to %s '%s', but "
            "this beat's speaker is %s '%s'; put line %d in the lines of a beat whose speaker is "
            "%s (consecutive lines may share a beat), and never give it to another character"
            % (k, n, line, want, want_phrase, got, got_phrase, n, want))


def SENTENCE(items):
    """LINE_SPEAKERS_SENTENCE filled with the joined items text."""
    return se.LINE_SPEAKERS_SENTENCE % items


def _shots2(ws, story_env, **kw):
    """The pin-sh2 ctx: shots, 2 panels, kyra and ronin pinned, --speech-only, LINES_NARRATIVE."""
    return seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env),
                        narration="speech", narrative=LINES_NARRATIVE, **kw)


def _fix_text():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


# --- SAT1: the constants (SA1, SA6) ------------------------------------------------------------

ATTRIBUTION_VERBS = frozenset("""
    says said asks asked replies replied answers answered shouts shouted yells yelled
    screams screamed cries cried whispers whispered murmurs murmured mutters muttered
    exclaims exclaimed announces announced declares declared tells told""".split())
CALL_OUT_VERBS = frozenset(("calls", "called"))
GAP_BLOCK_WORDS = frozenset("""
    the a an this that these those his her its their my our your he she they it him them we
    you i who whom which whose someone somebody everyone everybody nobody one as while when
    whenever before after until because since if though although whereas""".split())
OBJECT_WORDS = frozenset("""
    to at toward towards beside behind with of for from near by past around under over like
    than without into onto upon about besides""".split())
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")


def test_sat1_constants():
    assert se.ATTRIBUTION_VERBS == ATTRIBUTION_VERBS
    assert se.CALL_OUT_VERBS == CALL_OUT_VERBS
    assert se.GAP_BLOCK_WORDS == GAP_BLOCK_WORDS
    assert se.OBJECT_WORDS == OBJECT_WORDS
    assert se.LINE_SPEAKERS_SENTENCE == LINE_SPEAKERS_SENTENCE
    assert se.LINE_SPEAKERS_SENTENCE.count("%s") == 1
    assert re.findall(r"@@[A-Z_]+@@", se.LINE_SPEAKERS_SENTENCE) == []
    assert se.ATTRIBUTION_VERBS <= se.SPEECH_VERBS


# --- SAT2: the extraction table (SA1, SK4) -----------------------------------------------------

SAT2_ROWS = [
    (LINES_NARRATIVE, CAST3, ["c1", "c1"]),
    (PRONOUN_NARRATIVE, CAST3, [None, None]),
    ('Kyra says, "Go."', CAST3, ["c1"]),
    ('"Go," says the ronin.', CAST3, ["c2"]),
    ('“Go,” says the ronin.', CAST3, ["c2"]),
    ('"Go," the ronin says.', CAST3, ["c2"]),
    ('"Go," Kyra said quietly.', CAST3, ["c1"]),
    ('"Go!" yells Kyra.', CAST3, ["c1"]),
    ('"Go!" Kyra yells.', CAST3, [None]),
    ('She says, "Go."', CAST3, [None]),
    ('Kyra turns to the ronin, and she says, "Go."', CAST3, [None]),
    ('The ronin nods as Kyra says, "Go."', CAST3, ["c1"]),
    ('Kyra nods as the ronin says, "Go."', CAST3, ["c2"]),
    ('The ronin watches Kyra and says, "Go."', CAST3, [None]),
    ('Kyra asks the ronin, "Ready?"', CAST3, ["c1"]),
    ('The ronin and Kyra said, "Go."', CAST3, [None]),
    ('The monk beside Kyra says, "Go."', CAST3, [None]),
    ("Kyra's brother says, \"Go.\"", CAST3, [None]),
    ('The old monk says, "Go."', CAST3, ["c3"]),
    ('The monk says, "Go."', CAST3, [None]),
    ('"Go," says Kyra, "now."', CAST3, ["c1", "c1"]),
    ('Kyra says, "Go." The ronin says, "Fine."', CAST3, ["c1", "c2"]),
    ('Kyra says, "Go," and the ronin replies, "Fine."', CAST3, ["c1", "c2"]),
    ('Kyra calls out, "Wait!"', CAST3, ["c1"]),
    ('Kyra quietly says, "Wait."', CAST3, ["c1"]),
    ('Kyra smiles and then says, "Wait."', CAST3, ["c1"]),
    ('Kyra waits and Jiro says, "Wait."', CAST3, [None]),
    ('Kyra whispers to the ronin, "Wait."', CAST3, ["c1"]),
    ('The crowd shouts, "Kyra!"', CAST3, []),
    ('A sign reads "Closed".', CAST3, []),
    ('"Go," Kyra says to the ronin, who answers, "Fine."', CAST3, ["c1", None]),
    ('Kyra says, "Go," the ronin says.', CAST3, [None]),
    ('They pass under the gate together and Kyra says, "Stay close to me."', CAST3, [None]),
    ('The woman in grey says, "Go."', CAST3, ["c1"]),
    ('Ronin says, "Go."', CAST3, ["c2"]),
    ('"Go," Kyra says, "now."', CAST3, ["c1", "c1"]),
    ('The ronin hands Kyra rice and says, "Eat."', CAST3, [None]),
    ('Then says Kyra: "Go."', CAST3, ["c1"]),
    ('Kyra says, "Go."', [], [None]),
    ('"Go," says Kyra and the ronin.', CAST3, [None]),
    ('Kyra, the old monk, and the ronin said, "Go."', CAST3, [None]),
    ('They pass under the gate together, and the ronin says, "Go."', CAST3, ["c2"]),
    # SA1-A2: a lead word or a relative clause makes the mention no subject.
    ('The man facing Kyra says, "Go."', CAST3, [None]),
    ('The boy following Kyra says, "Go."', CAST3, [None]),
    ('Everyone except Kyra says, "Go."', CAST3, [None]),
    ('The man opposite Kyra says, "Go."', CAST3, [None]),
    ('A stranger among the ronin says, "Go."', CAST3, [None]),
    ('A second ronin says, "Halt."', CAST3, [None]),
    ('Another ronin steps forward and says, "Halt."', CAST3, [None]),
    ('A ronin says, "Halt."', CAST3, [None]),
    ('One ronin says, "Halt."', CAST3, [None]),
    ('The other ronin says, "Halt."', CAST3, [None]),
    ('The stranger who saved Kyra says, "Go."', CAST3, [None]),
    ('Every ronin shouts, "Banzai!"', CAST3, [None]),
    # SA1-A3: only a comma piece that is exactly a cast mention makes a compound subject.
    ('"Go," said Kyra, and the ronin replied, "Fine."', CAST3, ["c1", "c2"]),
    ('Kyra nods to the ronin, and the old monk says, "Go."', CAST3, ["c3"]),
    ('The old monk, Kyra, and the ronin said, "Go."', CAST3, [None]),
]


def test_sat2_extraction_table():
    assert len(SAT2_ROWS) == 57
    for text, cast, want in SAT2_ROWS:
        assert se.line_speakers(text, cast) == want, text
        assert len(want) == len(se.spoken_lines(text)), text


# --- SAT9: the plan prompt (SA6, SK8) ----------------------------------------------------------

def _plan_prompt(ws, **kw):
    """(plan prompt, filled LINES_RULE) of make_ctx(**kw), with no catalog and no pins."""
    ctx = seu.make_ctx(se, ws, **kw)
    cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))
    return se.build_plan_prompt(ctx, [], []), se.LINES_RULE.replace(
        "@@LINE_WORDS@@", cap).replace("@@MIN_BEATS@@", str(se.panel_range(ctx)[0]))


def test_sat9_plan_prompt(ws, story_env):
    members = _members(story_env)
    both = SENTENCE("line 1 to c1 and line 2 to c1")
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=LINES_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + both + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=LINES_NARRATIVE)
    assert rule + both + se.END_FRAME_RULE + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + "\nloras: " in prompt
    assert "The narrative gives these lines" not in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + se.END_FRAME_RULE + "\nloras: " in prompt
    assert "The narrative gives these lines" not in prompt
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narrative=(
        'Kyra climbs the steps, and the ronin follows. She says, "Wait." The ronin says, "Go."'))
    assert SENTENCE("line 2 to c2") in prompt
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narrative=(
        'Kyra says, "Go." The ronin says, "Why?" Kyra says, "Now."'))
    assert SENTENCE("line 1 to c1, line 2 to c2 and line 3 to c1") in prompt
    for narrative in (LINES_NARRATIVE, MONK_NARRATIVE):
        prompt, _rule = _plan_prompt(ws, mode="chained", narrative=narrative)
        assert "The narrative gives these lines" not in prompt, narrative
    prompt, _rule = _plan_prompt(ws, mode="chained", members=members, narration=False,
                                 narrative=LINES_NARRATIVE)
    assert "The narrative gives these lines" not in prompt


# --- SAT3, SAT4: P17 line speaker (SA2, SK5) ---------------------------------------------------

def _p17(ctx, raw):
    """The P17 messages of plan_checks' hard list for the normalised raw reply."""
    plan, shape = se.normalize_plan(ctx, raw)
    return [m for m in se.plan_checks(ctx, plan, shape)[0] if " P17 " in m]


def _lines(raw, lines):
    """raw with beat k's lines set to lines[k - 1]; returns raw."""
    for beat, numbers in zip(raw["beats"], lines):
        beat["lines"] = list(numbers)
    return raw


def _bad(mode):
    """SAT3's plan that gives line 2 (Kyra's) to the ronin in beat 3."""
    if mode == "chained":
        raw = _raw("chained", 3, [["c1", "c2"]] * 3)
        raw["beats"][1].update(speaker="c1", lines=[1])
        raw["beats"][2].update(speaker="c2", lines=[2])
        return raw
    return _lines(_raw(mode, 3, [["c1"], ["c1"], ["c2"]], ["c1", "", "c2"]), [[1], [], [2]])


def _corrected(mode):
    """SAT3's corrected plan: both lines spoken by c1, the ronin on screen."""
    if mode == "chained":
        raw = _bad("chained")
        raw["beats"][2]["speaker"] = "c1"
        return raw
    return _lines(_raw(mode, 3, [["c1"], ["c2"], ["c1"]], ["c1", "", "c1"]), [[1], [], [2]])


def test_sat3_p17_matrix(ws, story_env):
    members = _members(story_env)
    want = [P17(3, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]
    for mode in ("chained", "shots", "no_stills"):
        for narration in (True, "speech"):
            where = (mode, narration)
            ctx = seu.make_ctx(se, ws, mode=mode, panels=3, members=members, narration=narration,
                               narrative=LINES_NARRATIVE)
            found = _p17(ctx, _bad(mode))
            assert found == want, where
            v = se.parse_violation(found[0])
            assert (v["id"], v["name"], v["scope"], v["index"]) == (
                "P17", "line speaker", "beat", 3), where
            assert _p17(ctx, _corrected(mode)) == [], where
            pronoun = seu.make_ctx(se, ws, mode=mode, panels=3, members=members,
                                   narration=narration, narrative=PRONOUN_NARRATIVE)
            assert _p17(pronoun, _bad(mode)) == [], where
            uncast = seu.make_ctx(se, ws, mode=mode, panels=3, narration=narration,
                                  narrative=MONK_NARRATIVE)
            raw = _lines(seu.plan_json(mode, 3), [[1], [], []])
            raw["beats"][0]["speaker"] = "c1"
            assert _p17(uncast, raw) == [
                P17(1, 1, "Enter.", "c2", "the old monk", "c1", "the courier")], where
            raw["beats"][0].update(cast=["c2"], speaker="c2")
            assert _p17(uncast, raw) == [], where
        silent = seu.make_ctx(se, ws, mode=mode, panels=3, members=members, narration=False,
                              narrative=LINES_NARRATIVE)
        assert _p17(silent, _bad(mode)) == [], mode


def test_sat4_pin_sh2_fixture(ws, story_env):
    with open(FIX, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == FIX_SHA256
    ctx = _shots2(ws, story_env)
    plan, shape = se.normalize_plan(ctx, se.extract_json(_fix_text()))
    assert se.plan_checks(ctx, plan, shape)[0] == [
        P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]


# --- SAT5, SAT6, SAT10: the plan retry, the fatal exit and the re-check (SA3, SK6, SK9) -------

SHOTS2_PANELS = {"1": [seu.answer(seu.panel_json("shots", 1, KYRA))],
                 "2": [seu.answer(seu.panel_json("shots", 2, RONIN))]}


def test_sat5_e2e_exhausted(ws, tmp_path, monkeypatch, capsys, story_env):
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(_fix_text())] * 2)
    ctx = _shots2(ws, story_env, story_id="sa1")
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    assert capsys.readouterr().err == _fatal_err(
        [P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)], ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_sat6_e2e_retry(ws, tmp_path, monkeypatch, story_env):
    bad = json.loads(_fix_text())
    good = copy.deepcopy(bad)
    good["beats"][0]["lines"] = [1, 2]
    good["beats"][1].update(speaker="", lines=[])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(bad), seu.answer(good)],
                           panel=SHOTS2_PANELS)
    ctx = _shots2(ws, story_env, story_id="sa2")
    rc, _advisories = se.run(ctx)
    log = seu.agent_log(log)
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- "
            + P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN) + "\n") in log[1]["argv"][-1]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1, 2]), (["c2"], "", [])]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        dialogue = [line for line in f.read().splitlines() if line.startswith("Dialogue: ")]
    assert dialogue == [
        "Dialogue: the woman in grey: We reach the gate before dark. Stay close to me."]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_prompt.txt"),
              encoding="utf-8") as f:
        assert (se.LINES_PINNED_SENTENCE + SENTENCE("line 1 to c1 and line 2 to c1")
                + "\nloras: ") in f.read()


def test_sat10_back_compat_recheck(ws, tmp_path, monkeypatch, story_env):
    rc, ctx, _log = _pt16_run(ws, tmp_path, monkeypatch, story_env)
    assert rc == 0
    plan = _read_json(ctx.story_dir, "plan.json")
    plan["beats"][2]["speaker"] = "c2"
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    def refuse(*args, **kwargs):
        raise AssertionError("recheck must not call plan_checks or line_speakers")

    monkeypatch.setattr(se, "plan_checks", refuse)
    monkeypatch.setattr(se, "line_speakers", refuse)
    rc, _advisories = se.recheck(ctx, lambda path, panels, no_stills=False: [])
    assert rc == 0
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert checks["hard"] == []
    assert [e["message"] for e in checks["hard"] + checks["advisory"]
            if " P17 " in e["message"]] == []


# --- Review Focus 1-4: the inputs most likely to reach a real run first (SA2, SA3) ------------

def test_review_focus_1_an_exhausted_plan_lists_p16_then_every_p17(ws, tmp_path, monkeypatch,
                                                                    capsys, story_env):
    raw = _lines(_raw("shots", 2, [["c2"], ["c2"]], ["c2", ""]), [[1, 2], []])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2)
    ctx = _shots2(ws, story_env, story_id="sa3")
    capsys.readouterr()
    rc, _advisories = se.run(ctx)
    assert rc == 1
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan"]
    p16 = ("plan: P16 cast presence: c1 'the woman in grey' (library character kyra) is in no "
           "beat's cast; every already-cast character must be on screen, so put c1 in the cast "
           "of at least one beat; a beat with a speaker shows only the speaker, so that beat has "
           "no speaker or c1 is its speaker")
    assert capsys.readouterr().err == _fatal_err(
        [p16, P17(1, 1, "We reach the gate before dark.", "c1", KYRA, "c2", RONIN),
         P17(1, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)], ctx)
    for name in ("story.md", "plan.json"):
        assert not os.path.exists(os.path.join(ctx.story_dir, name)), name


def test_review_focus_2_a_speaker_written_as_a_name_is_checked_after_coercion(ws, story_env):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=LINES_NARRATIVE)
    raw = _lines(_raw("shots", 3, [["c1"], ["c2"], ["c2"]], ["Kyra", "", "RONIN"]),
                 [[1], [], [2]])
    assert _p17(ctx, raw) == [P17(3, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]
    raw["beats"][2].update(cast=["c1"], speaker="The Woman in Grey")
    plan, shape = se.normalize_plan(ctx, raw)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("", []), ("c1", [2])]
    assert se.plan_checks(ctx, plan, shape)[0] == []


def test_review_focus_3_a_quote_that_is_not_spoken_keeps_the_line_numbers(ws, story_env):
    members = _members(story_env)
    narrative = 'A sign reads "Closed". Kyra says, “Go.” The ronin says, "Fine."'
    assert se.spoken_lines(narrative) == ["Go.", "Fine."]
    assert se.line_speakers(narrative, CAST3) == ["c1", "c2"]
    ctx = seu.make_ctx(se, ws, mode="chained", panels=3, members=members, narrative=narrative)
    assert SENTENCE("line 1 to c1 and line 2 to c2") in se.build_plan_prompt(ctx, [], [])
    raw = _raw("chained", 3, [["c1", "c2"]] * 3)
    raw["beats"][1].update(speaker="c1", lines=[1])
    raw["beats"][2].update(speaker="c1", lines=[2])
    assert _p17(ctx, raw) == [P17(3, 2, "Fine.", "c2", RONIN, "c1", KYRA)]
    raw["beats"][2]["speaker"] = "c2"
    assert _p17(ctx, raw) == []


def test_review_focus_4_an_invented_speaker_in_a_pinned_run(ws, story_env):
    members = _members(story_env)
    narrative = 'Kyra says, "Go." The old monk says, "Enter."'
    ctx = seu.make_ctx(se, ws, mode="chained", panels=3, members=members, narrative=narrative)
    prompt = se.build_plan_prompt(ctx, [], [])
    assert SENTENCE("line 1 to c1") in prompt and "line 2 to" not in prompt
    raw = _raw("chained", 3, [["c1", "c2"], ["c1", "c3"], ["c1", "c2"]])
    raw["cast"].append({"id": "c3", "phrase": "the old monk", "descriptor": seu.MONK})
    raw["beats"][0].update(speaker="c1", lines=[1])
    raw["beats"][1].update(speaker="c1", lines=[2])
    assert _p17(ctx, raw) == [P17(2, 2, "Enter.", "c3", "the old monk", "c1", KYRA)]
    raw["beats"][1].update(cast=["c3"], speaker="c3")
    assert _p17(ctx, raw) == []


# --- SAT7, SAT8, Review Focus 5: the pipeline never misattributes (SA4, SA5, SK7) -------------

ASSIGNED = ("beat %d: P14 speaking beat: line 2 given to this beat by the pipeline, because the "
            "plan gave it to no beat")


def _sat7_plan(ws, story_env, narrative):
    """(ctx, plan) of SAT7: shots, 3 panels, kyra and ronin pinned, --speech-only, beats cast
    [c1], [c2], [c1], beat 1 spoken by c1 with line 1, line 2 in no beat; normalised only."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=narrative)
    raw = _lines(_raw("shots", 3, [["c1"], ["c2"], ["c1"]], ["c1", "", ""]), [[1], [], []])
    return ctx, se.normalize_plan(ctx, raw)[0]


def test_sat7_assign_missing_lines(ws, story_env):
    ctx, plan = _sat7_plan(ws, story_env, LINES_NARRATIVE)
    assert se.assign_missing_lines(ctx, plan) == [ASSIGNED % 3]
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("", []), ("c1", [2])]
    assert [m for m in se.plan_checks(ctx, plan)[0] if " P17 " in m] == []
    ctx, plan = _sat7_plan(ws, story_env, PRONOUN_NARRATIVE)
    notes = se.assign_missing_lines(ctx, plan)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c1", [1]), ("c2", [2]), ("", [])]
    assert notes[0] == ASSIGNED % 2


def test_sat8_q1_dialogue_patch(ws, story_env):
    ctx, plan = _sat7_plan(ws, story_env, LINES_NARRATIVE)
    fresh = copy.deepcopy(plan)
    parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 2, "the ronin: Stay close to me.") == (
        True, "the narrative gives spoken line 2 to 'the woman in grey', so a spoken-line patch "
              "never gives it to 'the ronin'")
    assert (plan["beats"][1]["speaker"], plan["beats"][1]["lines"]) == ("", [])
    parts = [se.empty_parts("shots", k, fresh, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, fresh, parts, 3,
                                "the woman in grey: Stay close to me.") == (True, None)
    ctx, plan = _sat7_plan(ws, story_env, PRONOUN_NARRATIVE)
    parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 2, "the ronin: Stay close to me.") == (
        True, None)


def test_review_focus_5_the_pin_sh2_shape_with_line_2_left_out(ws, tmp_path, monkeypatch,
                                                               story_env):
    raw = _lines(_raw("shots", 2, [["c1"], ["c2"]], ["c1", ""]), [[1], []])
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2,
                           panel=SHOTS2_PANELS)
    ctx = _shots2(ws, story_env, story_id="sa4")
    rc, _advisories = se.run(ctx)
    assert rc == 0
    assert [r["stage"] for r in seu.agent_log(log)] == ["plan", "plan", "panel", "panel"]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1, 2]), (["c2"], "", [])]
    assert ASSIGNED % 1 in plan["speech_notes"]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        dialogue = [line for line in f.read().splitlines() if line.startswith("Dialogue: ")]
    assert dialogue == [
        "Dialogue: the woman in grey: We reach the gate before dark. Stay close to me."]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []


# --- Final whole-branch review: SA1-A2, SA5-A1, Q1-A1 (spec Amendment 2026-10-28) -------------

NON_SPEAKER_LEAD_WORDS = frozenset("""
    a an another other second one every each some any no among amid amongst between against
    opposite across along alongside beyond inside outside within below above beneath underneath
    except unlike including through throughout via facing following""".split())
RELATIVE_WORDS = frozenset(("who", "whom", "whose", "that", "which"))
Q1_SPEAKER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken by %s in "
              "panel %d's Dialogue:, but the narrative gives it to %s; give it word for word to a "
              "panel whose Dialogue: speaker is %s (Dialogue: %s: <the line>)")
SA5_LINE_1 = ("the narrative gives spoken line 1 to 'the woman in grey', so a spoken-line patch "
              "never gives it to 'the ronin'")
SA5_LINE_2 = ("the narrative gives spoken line 2 to 'the woman in grey', so a spoken-line patch "
              "never gives it to 'the ronin'")


def test_sa1_a2_constants():
    assert se.NON_SPEAKER_LEAD_WORDS == NON_SPEAKER_LEAD_WORDS
    assert se.RELATIVE_WORDS == RELATIVE_WORDS
    assert se.Q1_SPEAKER == Q1_SPEAKER


def _widened(ws, story_env, narrative):
    """(ctx, plan, parts) of the SA5-A1 case: shots, 3 panels, kyra and ronin pinned,
    --speech-only, beat 1 cast [c2] spoken by c2 with no lines, and panel 1's Dialogue already
    saying line 1 as free dialogue."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=narrative)
    raw = _lines(_raw("shots", 3, [["c2"], ["c1"], ["c1"]], ["c2", "", ""]), [[], [], []])
    plan = se.normalize_plan(ctx, raw)[0]
    parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]
    parts[0]["dialogue"] = "We reach the gate before dark."
    return ctx, plan, parts


def test_sa5_a1_a_line_the_panel_already_says_is_checked(ws, story_env):
    mixed = LINES_NARRATIVE.replace("and Kyra says", "and she says")
    ctx, plan, parts = _widened(ws, story_env, mixed)
    assert se.line_speakers(ctx.narrative, plan["cast"]) == ["c1", None]
    assert [m for m in se.plan_checks(ctx, plan)[0] if " P17 " in m] == []
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 1, "the ronin: Stay close to me.") == (
        True, SA5_LINE_1)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c2", []), ("", []), ("", [])]
    assert parts[0]["dialogue"] == "We reach the gate before dark."
    assert [m for m in se.plan_checks(ctx, plan)[0] if " P17 " in m] == []
    ctx, plan, parts = _widened(ws, story_env, PRONOUN_NARRATIVE)
    assert se.q1_dialogue_patch(ctx, lib, plan, parts, 1, "the ronin: Stay close to me.") == (
        True, None)
    assert [(b["speaker"], b["lines"]) for b in plan["beats"]] == [
        ("c2", [1, 2]), ("", []), ("", [])]


def test_q1_a1_spoken_line_problems(ws, story_env):
    ctx = _shots2(ws, story_env)
    line1, line2 = "We reach the gate before dark.", "Stay close to me."
    wrong = Q1_SPEAKER % (2, line2, "'the ronin'", 2, "'the woman in grey'",
                          "'the woman in grey'", KYRA)

    def q1(dialogues, speakers=None):
        return se.spoken_line_problems(ctx, lib, [KYRA, RONIN], dialogues, speakers)

    split = [KYRA + ": " + line1, RONIN + ": " + line2]
    assert se.spoken_line_problems(ctx, lib, [KYRA, RONIN], split) == []
    assert q1(split) == []
    assert q1(split, [None, None]) == []
    assert q1(split, [KYRA, None]) == []
    assert q1(split, [KYRA, KYRA]) == [wrong]
    assert se.parse_violation(wrong)["id"] == "Q1"
    assert se.parse_violation(wrong)["scope"] == "story"
    assert q1([KYRA + ": " + line1 + " " + line2, ""], [KYRA, KYRA]) == []
    assert q1([KYRA + ": " + line1, KYRA + ": " + line2], [KYRA, KYRA]) == []
    assert q1([RONIN + ": " + line1 + " " + line2, ""], [KYRA, KYRA]) == [
        Q1_SPEAKER % (1, line1, "'the ronin'", 1, "'the woman in grey'", "'the woman in grey'",
                      KYRA),
        Q1_SPEAKER % (2, line2, "'the ronin'", 1, "'the woman in grey'", "'the woman in grey'",
                      KYRA)]
    assert q1([KYRA + ": " + line1, ""], [KYRA, KYRA]) == [se.Q1_MISSING % (2, line2)]
    assert q1([KYRA + ": " + line2, KYRA + ": " + line1], [KYRA, KYRA]) == [
        se.Q1_ORDER % (2, line2)]
    assert q1([KYRA + ": " + line2, KYRA + ": " + line1, RONIN + ": " + line2],
              [KYRA, KYRA]) == [se.Q1_ORDER % (2, line2)]


FREE_NARRATIVE = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks '
                  'one step behind her. Near the top Kyra turns and says, "We will reach the old '
                  'gate before it is dark." They pass under the gate together, and Kyra says, '
                  '"Stay very close to me now."')
FREE_LINE_2 = "Stay very close to me now."
RONIN_PATCH = {"target": "panel", "index": 2, "field": "dialogue", "reason": "r",
               "replacement": "the ronin: Stay very close to me now."}


def _free_run(ws, tmp_path, monkeypatch, story_env, narrative, story_id):
    """(rc, ctx, agent log) of the final review's I1 run: shots, 2 panels, kyra and ronin
    pinned, --speech-only; the plan (both replies) has beat 1 [c1] speaking line 1 and beat 2
    [c2] spoken by c2 with no lines; panel 2's writer says line 2 as free dialogue; the critic
    (both rounds) gives line 2 to the ronin."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env),
                       narration="speech", narrative=narrative, story_id=story_id)
    raw = _lines(_raw("shots", 2, [["c1"], ["c2"]], ["c1", "c2"]), [[1], []])
    panel_2 = seu.panel_json("shots", 2, RONIN)
    panel_2["dialogue"] = FREE_LINE_2
    critic = seu.answer(seu.critic_json((7, 6, 6), "revise", [RONIN_PATCH]))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2,
                           panel={"1": [seu.answer(seu.panel_json("shots", 1, KYRA))],
                                  "2": [seu.answer(panel_2)]},
                           critic=[critic, critic])
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def test_q1_a1_a_free_line_under_the_wrong_speaker_ends_exit_2(ws, tmp_path, monkeypatch,
                                                               capsys, story_env):
    capsys.readouterr()
    rc, ctx, log = _free_run(ws, tmp_path, monkeypatch, story_env, FREE_NARRATIVE, "sa5")
    err = capsys.readouterr().err
    wrong = Q1_SPEAKER % (2, FREE_LINE_2, "'the ronin'", 2, "'the woman in grey'",
                          "'the woman in grey'", KYRA)
    assert rc == 2
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel", "critic", "critic"]
    assert ("  - " + wrong + "\n") in err
    assert ("  - " + FREE_WRONG + "\n") in err
    checks = _read_json(ctx.story_dir, "story_checks.json")
    # Q1-A2: the panel 2 N18 joins the story Q1 (FREE_WRONG is defined with the Q1-A2 tests).
    assert [(v["id"], v["message"]) for v in checks["hard"]] == [("Q1", wrong),
                                                                 ("N18", FREE_WRONG)]
    critic_1 = _read_json(os.path.join(ctx.story_dir, "story_rounds", "round_1"), "critic.json")
    assert critic_1["applied"] == []
    assert critic_1["rejected"] == [{"patch": RONIN_PATCH, "reason": SA5_LINE_2}]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1]), (["c2"], "c2", [])]
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        assert "Dialogue: the ronin: " + FREE_LINE_2 + "\n" in f.read()


def test_q1_a1_an_unattributed_free_line_keeps_any_speaker(ws, tmp_path, monkeypatch,
                                                           story_env):
    narrative = FREE_NARRATIVE.replace("and Kyra says", "and she says")
    rc, ctx, log = _free_run(ws, tmp_path, monkeypatch, story_env, narrative, "sa6")
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel"]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        assert "Dialogue: the ronin: " + FREE_LINE_2 + "\n" in f.read()


# --- Re-review residual: Q1-A2 (spec Amendment 2026-10-28) -------------------------------------

N18_LINE_SPEAKER = ("panel %d: N18 dialogue: Dialogue: has %s say the narrative's spoken line %d "
                    "\"%s\", which the narrative gives to %s; do not have %s say it: write a "
                    "different line for this panel")
FREE_LINE_1 = "We will reach the old gate before it is dark."
FREE_WRONG = N18_LINE_SPEAKER % (2, "'the ronin'", 2, FREE_LINE_2, "'the woman in grey'",
                                 "'the ronin'")
GUARD_LINE = "I will guard the gate."
GUARD_PATCH = {"target": "panel", "index": 2, "field": "dialogue", "reason": "r",
               "replacement": GUARD_LINE}
PROBE2_CASTS = [["c1"], ["c2"], ["c1"]]
KYRA_SAYS = ["Dialogue: the woman in grey: " + FREE_LINE_1,
             "Dialogue: the woman in grey: " + FREE_LINE_2]


def test_q1_a2_constants():
    assert se.N18_LINE_SPEAKER == N18_LINE_SPEAKER
    assert se.REPAIR_IDS == ("N7", "N11", "N18", "N20", "N21", "N22", "T1", "T2", "T3")
    assert se.NON_BLOCKING_IDS == ("T2", "T3")
    violation = se.parse_violation(FREE_WRONG)
    assert (violation["scope"], violation["index"], violation["id"]) == ("panel", 2, "N18")


def _free3_plan(ws, story_env, narrative, casts, lines):
    """(ctx, plan) of a shots, 3-panel, --speech-only story with kyra and ronin pinned: beat k
    has cast casts[k - 1], spoken by its one member, and lines lines[k - 1]."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=narrative)
    raw = _lines(_raw("shots", 3, casts, [cast[0] for cast in casts]), lines)
    return ctx, se.normalize_plan(ctx, raw)[0]


def test_q1_a2_free_line_problems(ws, story_env):
    ctx, plan = _free3_plan(ws, story_env, FREE_NARRATIVE, PROBE2_CASTS, [[1], [], [2]])
    assert se.line_speakers(ctx.narrative, plan["cast"]) == ["c1", "c1"]

    def free(says, speakers=(KYRA, KYRA), first=KYRA + ": " + FREE_LINE_1):
        dialogues = [first, RONIN + ": " + says, KYRA + ": " + FREE_LINE_2]
        return se.free_line_problems(ctx, lib, plan, dialogues, list(speakers))

    assert free(FREE_LINE_2) == [FREE_WRONG]
    assert free("Fine. " + FREE_LINE_2) == [FREE_WRONG]
    assert free("stay VERY close to me now!") == [FREE_WRONG]
    assert free(FREE_LINE_1 + " " + FREE_LINE_2) == [
        N18_LINE_SPEAKER % (2, "'the ronin'", 1, FREE_LINE_1, "'the woman in grey'",
                            "'the ronin'"), FREE_WRONG]
    assert free("Stay very close to me now, Kyra.") == []
    assert free("I said stay very close to me now.") == []
    assert free(GUARD_LINE) == []
    assert free(FREE_LINE_2, (None, None)) == []
    assert free(FREE_LINE_2, (KYRA, None)) == []
    assert free(FREE_LINE_2, (KYRA, RONIN)) == []
    assert free(GUARD_LINE, first=RONIN + ": " + FREE_LINE_2) == []
    go = 'At the gate Kyra says, "Go." The ronin waits beside her.'
    ctx, plan = _free3_plan(ws, story_env, go, PROBE2_CASTS, [[1], [], []])
    assert se.line_speakers(ctx.narrative, plan["cast"]) == ["c1"]
    go_wrong = N18_LINE_SPEAKER % (2, "'the ronin'", 1, "Go.", "'the woman in grey'",
                                   "'the ronin'")

    def go_says(says):
        dialogues = [KYRA + ": Go.", RONIN + ": " + says, ""]
        return se.free_line_problems(ctx, lib, plan, dialogues, [KYRA])

    assert go_says("Let us go.") == []
    assert go_says("Go, now.") == []
    assert go_says("We go at dawn.") == []
    assert go_says("Go.") == [go_wrong]
    assert go_says("Wait. Go!") == [go_wrong]
    twice = 'At the gate Kyra says, "Go." The ronin says, "Go."'
    ctx, plan = _free3_plan(ws, story_env, twice, PROBE2_CASTS, [[1], [], []])
    assert se.line_speakers(ctx.narrative, plan["cast"]) == ["c1", "c2"]
    assert se.free_line_problems(ctx, lib, plan, [KYRA + ": Go.", RONIN + ": Go.", ""],
                                 [KYRA, RONIN]) == []


def _free3_run(ws, tmp_path, monkeypatch, story_env, narrative, story_id, casts, lines, critic,
               rewrites=()):
    """(rc, ctx, agent log) of the re-review's probe2 run ($S/rr/test_rr_probe2.py): shots,
    3 panels, kyra and ronin pinned, --speech-only; the plan (both replies) gives beat k cast
    casts[k - 1], spoken by its one member, and lines lines[k - 1]; panel 2's writer says line 2
    as free dialogue, and its later replies say each of rewrites instead; critic is the list of
    critic replies."""
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, members=_members(story_env),
                       narration="speech", narrative=narrative, story_id=story_id)
    raw = _lines(_raw("shots", 3, casts, [cast[0] for cast in casts]), lines)
    phrase = {"c1": KYRA, "c2": RONIN}
    panel = {str(k): [seu.answer(seu.panel_json("shots", k, phrase[casts[k - 1][0]]))]
             for k in (1, 3)}
    panel["2"] = []
    for line in (FREE_LINE_2,) + tuple(rewrites):
        reply = seu.panel_json("shots", 2, phrase[casts[1][0]])
        reply["dialogue"] = line
        panel["2"].append(seu.answer(reply))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)] * 2, panel=panel,
                           critic=list(critic))
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _dialogue_lines(ctx):
    with open(os.path.join(ctx.story_dir, "story.md"), encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.startswith("Dialogue: ")]


def test_q1_a2_the_probe2_shape_ends_exit_2_when_nothing_repairs_it(ws, tmp_path, monkeypatch,
                                                                    capsys, story_env):
    capsys.readouterr()
    nothing = seu.answer(seu.critic_json((7, 6, 6), "revise", []))
    rc, ctx, log = _free3_run(ws, tmp_path, monkeypatch, story_env, FREE_NARRATIVE, "sa7",
                              PROBE2_CASTS, [[1], [], []], [nothing, nothing])
    err = capsys.readouterr().err
    assert rc == 2
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel", "panel", "critic",
                                         "critic"]
    assert ("  - " + FREE_WRONG + "\n") in err
    checks = _read_json(ctx.story_dir, "story_checks.json")
    assert [(v["id"], v["message"]) for v in checks["hard"]] == [("N18", FREE_WRONG)]
    plan = _read_json(ctx.story_dir, "plan.json")
    assert [(b["cast"], b["speaker"], b["lines"]) for b in plan["beats"]] == [
        (["c1"], "c1", [1]), (["c2"], "c2", []), (["c1"], "c1", [2])]
    assert _dialogue_lines(ctx) == [KYRA_SAYS[0], "Dialogue: the ronin: " + FREE_LINE_2,
                                    KYRA_SAYS[1]]


def test_q1_a2_the_critic_replaces_the_free_line(ws, tmp_path, monkeypatch, story_env):
    critic = seu.answer(seu.critic_json((7, 6, 6), "revise", [GUARD_PATCH]))
    rc, ctx, log = _free3_run(ws, tmp_path, monkeypatch, story_env, FREE_NARRATIVE, "sa8",
                              PROBE2_CASTS, [[1], [], []], [critic])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "plan", "panel", "panel", "panel", "critic"]
    round_0 = _read_json(os.path.join(ctx.story_dir, "story_rounds", "round_0"),
                         "story_checks.json")
    assert [(v["id"], v["message"]) for v in round_0["hard"]] == [("N18", FREE_WRONG)]
    critic_1 = _read_json(os.path.join(ctx.story_dir, "story_rounds", "round_1"), "critic.json")
    assert (critic_1["applied"], critic_1["rejected"]) == ([GUARD_PATCH], [])
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    assert _dialogue_lines(ctx) == [KYRA_SAYS[0], "Dialogue: the ronin: " + GUARD_LINE,
                                    KYRA_SAYS[1]]


def test_q1_a2_a_code_only_round_asks_the_writer_again(ws, tmp_path, monkeypatch, story_env):
    bad = seu.answer("not json")
    rc, ctx, log = _free3_run(ws, tmp_path, monkeypatch, story_env, FREE_NARRATIVE, "sa9",
                              PROBE2_CASTS, [[1], [], []], [bad, bad], rewrites=(GUARD_LINE,))
    assert rc == 0
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3),
        ("critic", None), ("critic", None), ("panel", 2)]
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_1", "panel_02_prompt_2.txt"),
              encoding="utf-8") as f:
        assert "\n- " + FREE_WRONG + "\n" in f.read()
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    assert _dialogue_lines(ctx) == [KYRA_SAYS[0], "Dialogue: the ronin: " + GUARD_LINE,
                                    KYRA_SAYS[1]]


def test_q1_a2_an_unattributed_or_own_free_line_is_unchanged(ws, tmp_path, monkeypatch,
                                                              story_env):
    she = FREE_NARRATIVE.replace("and Kyra says", "and she says")
    rc, ctx, log = _free3_run(ws, tmp_path, monkeypatch, story_env, she, "sa10", PROBE2_CASTS,
                              [[1], [], [2]], [])
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    assert _dialogue_lines(ctx) == [KYRA_SAYS[0], "Dialogue: the ronin: " + FREE_LINE_2,
                                    KYRA_SAYS[1]]
    own = FREE_NARRATIVE.replace("and Kyra says", "and the ronin says")
    rc, ctx, log = _free3_run(ws, tmp_path, monkeypatch, story_env, own, "sa11",
                              [["c1"], ["c2"], ["c2"]], [[1], [], [2]], [])
    assert se.line_speakers(ctx.narrative, se.load_plan(ctx)["cast"]) == ["c1", "c2"]
    assert rc == 0
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel"]
    assert _read_json(ctx.story_dir, "story_checks.json")["hard"] == []
    assert _dialogue_lines(ctx) == [KYRA_SAYS[0], "Dialogue: the ronin: " + FREE_LINE_2,
                                    "Dialogue: the ronin: " + FREE_LINE_2]
