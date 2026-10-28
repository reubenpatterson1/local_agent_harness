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
]


def test_sat2_extraction_table():
    assert len(SAT2_ROWS) == 42
    for text, cast, want in SAT2_ROWS:
        assert se.line_speakers(text, cast) == want, text
        assert len(want) == len(se.spoken_lines(text)), text


# --- SAT9: the plan prompt (SA6, SK8) ----------------------------------------------------------

def _plan_prompt(ws, **kw):
    """(plan prompt, filled LINES_RULE) of make_ctx(**kw), with no catalog and no pins."""
    ctx = seu.make_ctx(se, ws, **kw)
    cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))
    return se.build_plan_prompt(ctx, [], []), se.LINES_RULE.replace("@@LINE_WORDS@@", cap)


def test_sat9_plan_prompt(ws, story_env):
    members = _members(story_env)
    both = SENTENCE("line 1 to c1 and line 2 to c1")
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=LINES_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + both + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=LINES_NARRATIVE)
    assert rule + both + "\nloras: " in prompt
    prompt, rule = _plan_prompt(ws, mode="shots", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + se.LINES_PINNED_SENTENCE + "\nloras: " in prompt
    assert "The narrative gives these lines" not in prompt
    prompt, rule = _plan_prompt(ws, mode="chained", members=members, narrative=PRONOUN_NARRATIVE)
    assert rule + "\nloras: " in prompt
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
