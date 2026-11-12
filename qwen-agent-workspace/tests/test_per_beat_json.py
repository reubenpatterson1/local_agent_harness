"""Tests for the per_beat JSON fix (docs/superpowers/specs/2026-11-10-per-beat-json-design.md,
PJ1-PJ6: PJT1-PJT6): the plan prompt names the per_beat key of beat 1, extract_json repairs a
per_beat key written "string": "N": only when the reply does not parse, and the retry after a
reply that is not one JSON object names where the JSON parser stopped.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_per_beat_json.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws). No test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_per_beat_json", os.path.join(WS, "story_engine.py")).load_module()

PICK = {"id": "fast-motion", "strength": 0.8}
CLAUSE = ("per_beat maps each beat number to a list of picks for that beat only, taken only "
          "from the LoRAs that may be per-beat picks, and each key is the beat number alone in "
          'double quotes: the key of beat 1 is "1";')
QUOTED = 'the old prompt made it write "string": "1": [ before every pick'


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _catalog(tmp_path):
    entry = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "fast"), "fast-motion")
    return {"schema_version": 1, "entries": [entry]}


def _picked_plan(mode, n, **overrides):
    """seu.plan_json(mode, n) with one fast-motion pick on every beat."""
    loras = {"global": [], "per_beat": dict((str(k), [dict(PICK)]) for k in range(1, n + 1)),
             "stills": []}
    return seu.plan_json(mode, n, loras=loras, **overrides)


def _string_keyed(text):
    """text with every per_beat key "N": written "string": "N":, as in the reported reply."""
    head, tail = text.split('"per_beat": {', 1)
    body, rest = tail.split('"stills"', 1)
    return (head + '"per_beat": {' + re.sub(r'"([0-9]+)": \[', r'"string": "\1": [', body)
            + '"stills"' + rest)


def _reported(mode="shots", n=15):
    """The reported reply: an indented plan whose per_beat keys are all "string": "N":."""
    return _string_keyed(json.dumps(_picked_plan(mode, n), indent=2))


def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _run(ws, tmp_path, monkeypatch, plan, mode="chained", n=3, **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=_panel_script(mode, n),
                           critic=[seu.answer(seu.critic_json())])
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _rejected(problem, reply):
    return ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + problem
            + "\nPrevious reply:\n" + reply + "\n\nReply with the complete corrected JSON object "
            "only.")


# --- PJT1 (PJ1): the plan prompt names the per_beat key of beat 1 ------------------------------

def test_pjt1_the_lora_paragraph_names_the_per_beat_key(ws, tmp_path):
    old = ("per_beat maps a beat index, written as a string, to a list of motion or physics "
           "picks for that beat only;")
    assert se.LORA_PICK_PARAGRAPH == (
        "an object with the keys global, per_beat and stills. Each pick is an object with the "
        "keys id and strength, taken from the LoRA catalog below; strength must lie inside that "
        "entry's range. The catalog lists each LoRA under the places where it may go. global "
        "is a list of picks applied to every panel, taken only from the LoRAs that may be global "
        "picks: at most one style LoRA, plus at most one physics LoRA that suits the whole movie. "
        + CLAUSE + " a LoRA in global is never also in per_beat, and every beat may have at "
        "most one motion LoRA and at most one physics LoRA, counting global. stills is a list of "
        "at most one stills LoRA.")
    assert old not in se.LORA_PICK_PARAGRAPH
    assert "{" not in se.LORA_PICK_PARAGRAPH and "}" not in se.LORA_PICK_PARAGRAPH
    assert se.LORA_EMPTY_PARAGRAPH == (
        "an object with the keys global, per_beat and stills, each empty: global and stills are "
        "empty lists and per_beat is an empty object.")
    catalog = _catalog(tmp_path)
    for mode in ("chained", "no_stills", "shots"):
        for kw, picks in ((dict(catalog=catalog), True), (dict(), False),
                          (dict(catalog=catalog, auto_lora=False), False)):
            ctx = seu.make_ctx(se, ws, mode=mode, panels=4, **kw)
            prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), ctx.pinned)
            assert "written as a string" not in prompt, (mode, kw)
            assert (CLAUSE in prompt) == picks, (mode, kw)
            assert (se.LORA_EMPTY_PARAGRAPH in prompt) == (not picks), (mode, kw)


# --- PJT2 (PJ2): repair_string_keys rewrites only the malformed key ----------------------------

def test_pjt2_repair_string_keys():
    assert se.repair_string_keys('{"per_beat": {"string": "1": [], "string": 12: []}}') == (
        '{"per_beat": {"1": [], "12": []}}')
    assert se.repair_string_keys('{"string" :\n  "3"\t: [{"id": "a"}]}') == (
        '{"3": [{"id": "a"}]}')
    kept = ('{"title": "%s", "kind": {"string": "1"}, "string": 2, "per_beat": {"string": "4": '
            '[]}}' % QUOTED.replace('"', '\\"'))
    assert se.repair_string_keys(kept) == kept.replace('"string": "4":', '"4":')
    assert json.loads(se.repair_string_keys(kept)) == {
        "title": QUOTED, "kind": {"string": "1"}, "string": 2, "per_beat": {"4": []}}
    valid = json.dumps(_picked_plan("shots", 15, title=QUOTED), indent=2)
    assert se.repair_string_keys(valid) == valid
    for value in ({"string": "1", "lines": ["string", "2"]}, {"string": "12:30"},
                  {"string": "7", "a": 1}, {"string": 3}):
        assert se.repair_string_keys(json.dumps(value)) == json.dumps(value)
    assert se.repair_string_keys('{"string": "12:30", "per_beat": {"string": "1": []}}') == (
        '{"string": "12:30", "per_beat": {"1": []}}')


# --- PJT3 (PJ3, PJ6): extract_json repairs only a span that does not parse ---------------------

def test_pjt3_extract_json_repairs_only_a_reply_that_does_not_parse(monkeypatch):
    reported = _reported()
    assert reported.count('"string": "') == 15
    with pytest.raises(ValueError, match="Expecting ',' delimiter"):
        json.loads(reported)
    assert se.extract_json(reported) == _picked_plan("shots", 15)
    assert se.extract_json("```json\n" + reported + "\n```") == _picked_plan("shots", 15)
    quoted = _string_keyed(json.dumps(_picked_plan("shots", 15, title=QUOTED), indent=2))
    assert se.extract_json(quoted) == _picked_plan("shots", 15, title=QUOTED)
    assert se.extract_json('{"per_beat": {"string": "1": []} "stills": []}') is None
    assert se.extract_json('{"per_beat": {"string": "beat 1": []}}') is None

    def no_repair(span):
        raise AssertionError("repair_string_keys called for a reply that parses")

    monkeypatch.setattr(se, "repair_string_keys", no_repair)
    for value in (_picked_plan("shots", 15), _picked_plan("shots", 15, title=QUOTED),
                  {"string": "1"}, {"a": {"b": 2}}):
        text = json.dumps(value, indent=2)
        assert se.extract_json(text) == value == json.loads(text)
        assert se.extract_json("Sure!\n```json\n" + text + "\n```\nthanks") == value
    assert [se.extract_json(t) for t in ("[1, 2]", "{not json}", None, "no braces")] == [None] * 4
    assert se.extract_json("```{\"a\": 3}```") == {"a": 3}


# --- PJT4 (PJ1-PJ3, PJ6): the reported 15-beat reply is used by the first plan call ------------

def test_pjt4_the_reported_fifteen_beat_reply_is_used_on_the_first_call(ws, tmp_path,
                                                                       monkeypatch, capsys):
    reported = _reported()
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [{"answer": reported}], mode="shots", n=15,
                        catalog=_catalog(tmp_path))
    assert rc == 0
    assert [r["stage"] for r in log].count("plan") == 1
    assert CLAUSE in log[0]["argv"][-1]
    out = capsys.readouterr().out
    assert "plan: call 2 of 2" not in out and "was cut off" not in out
    with open(os.path.join(ctx.story_dir, "plan.json"), encoding="utf-8") as f:
        per_beat = json.load(f)["loras"]["per_beat"]
    assert sorted(per_beat, key=int) == [str(k) for k in range(1, 16)]
    assert all([p["id"] for p in picks] == ["fast-motion"] for picks in per_beat.values())
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_reply_1.txt"),
              encoding="utf-8") as f:
        assert f.read() == reported


# --- PJT5 (PJ4, PJ5): the retry prompt names where the JSON parser stopped ---------------------

def test_pjt5_the_retry_prompt_names_the_parse_error(ws, tmp_path, monkeypatch):
    broken = ('Here is the plan:\n```json\n{\n  "title": "The Sealed Letter"\n  "logline": "x"\n}'
              '\n```')
    assert se.json_error(broken) == (5, 3, "Expecting ',' delimiter")
    assert se.json_error("{not json}") == (1, 2, "Expecting property name enclosed in double "
                                                 "quotes")
    reported = _reported()
    line, column, message = se.json_error(reported)
    assert message == "Expecting ',' delimiter"
    assert reported.splitlines()[line - 1] == '      "string": "1": ['
    assert column == len('      "string": "1"') + 1
    for text in (None, "", "nope", "[1, 2]", '{"a": 1}', reported.replace('"string": ', ""),
                 '{"a": ' + "[" * 100000 + "}"):
        assert se.json_error(text) is None, text[:20] if text else text
    assert se.PLAN_JSON_ERROR % (4, 3, "Expecting ',' delimiter") == (
        " (the JSON parser stopped at line 4, column 3 of the previous reply: Expecting ',' "
        "delimiter)")
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": broken}, seu.answer(seu.plan_json("chained", 3))])
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + _rejected(
        "the reply is not one JSON object (the JSON parser stopped at line 5, column 3 of the "
        "previous reply: Expecting ',' delimiter)", broken)
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": "nope"}, seu.answer(seu.plan_json("chained", 3))],
                        story_id="s2")
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + _rejected(
        "the reply is not one JSON object", "nope")


# --- PJT6 (PJ5): a cut-off reply keeps the cut-off retry, with no parse error ------------------

def test_pjt6_a_cut_off_reply_keeps_the_cut_off_retry(ws, tmp_path, monkeypatch):
    cut = _reported("chained", 3)[:-200]
    assert '"string": "1": [' in cut
    assert se.cut_off_json(cut) and se.extract_json(cut) is None
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": cut}, seu.answer(seu.plan_json("chained", 3))])
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + se.PLAN_CUT_OFF_RETRY % (4096, 6144)
    assert "JSON parser" not in log[1]["argv"][-1]
