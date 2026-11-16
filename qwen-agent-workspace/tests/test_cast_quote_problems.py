"""Tests for the cast quote check (CQ-T1..CQ-T19): spoken words stay out of a cast entry's phrase
and descriptor. The planner prompt says so and P25 makes the plan call retry; P25 never enters a
state and never blocks a story.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_cast_quote_problems.py
Stdlib plus pytest. Every model call goes to the fake bin/qwen-agent of a temp workspace.
"""

import importlib.machinery
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_cast_quote", "story_engine.py")

QUOTED = 'a man who shouts "Stop. Not another step." and wears a grey coat and a flat cap'
CLEAN = "a stocky middle-aged man with short grey hair wearing a dark guard uniform and a flat cap"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _raw(mode, descriptor, phrase="the guard"):
    """seu.plan_json(mode, 2) whose c2 is an unnamed guard with the given descriptor."""
    cast = [{"id": "c1", "phrase": "the courier", "descriptor": seu.COURIER},
            {"id": "c2", "phrase": phrase, "descriptor": descriptor}]
    return seu.plan_json(mode, 2, cast=cast)


def _plan(ws, descriptor, phrase="the guard", mode="shots", **ctx_kw):
    ctx = seu.make_ctx(se, ws, mode=mode, panels=2, **ctx_kw)
    plan, shape = se.normalize_plan(ctx, _raw(mode, descriptor, phrase))
    return ctx, plan, shape


def _set(plan, index, **fields):
    plan["cast"][index].update(fields)
    return plan


def test_cq_t1_a_quoted_descriptor(ws):
    _ctx, plan, _shape = _plan(ws, QUOTED)
    assert se.cast_quote_problems(plan) == [se.P25_MESSAGE % "c2's descriptor"]


def test_cq_t2_curly_quotes(ws):
    _ctx, plan, _shape = _plan(ws, CLEAN)
    _set(plan, 1, descriptor="a man who shouts “Stop now” in a grey coat")
    assert se.cast_quote_problems(plan) == [se.P25_MESSAGE % "c2's descriptor"]
    _set(plan, 1, descriptor="a man who shouts “Stop now in a grey coat")
    assert se.cast_quote_problems(plan) == [se.P25_MESSAGE % "c2's descriptor"]


def test_cq_t3_a_quoted_phrase(ws):
    _ctx, plan, _shape = _plan(ws, CLEAN)
    _set(plan, 0, phrase='the "courier"')
    assert se.cast_quote_problems(plan) == [se.P25_MESSAGE % "c1's phrase"]
    _set(plan, 0, phrase="the courier")
    _set(plan, 1, phrase='the "guard"', descriptor=QUOTED)
    assert se.cast_quote_problems(plan) == [se.P25_MESSAGE % "c2's phrase",
                                            se.P25_MESSAGE % "c2's descriptor"]


def test_cq_t4_a_library_entry_is_ignored(ws):
    _ctx, plan, _shape = _plan(ws, CLEAN)
    _set(plan, 1, descriptor=QUOTED, cast_name="kyra")
    assert se.cast_quote_problems(plan) == []


def test_cq_t5_a_clean_plan(ws):
    _ctx, plan, _shape = _plan(ws, CLEAN)
    assert se.cast_quote_problems(plan) == []


def test_cq_t6_apostrophes_and_punctuation_are_not_quotes(ws):
    _ctx, plan, _shape = _plan(ws, CLEAN)
    _set(plan, 1, descriptor="a man in his father's coat, with a flat cap, grey hair, and "
                             "boots, worn.")
    assert se.cast_quote_problems(plan) == []
    _set(plan, 1, descriptor="a man in his father\u2019s coat, with a flat cap, grey hair, and "
                             "boots, worn.")
    assert se.cast_quote_problems(plan) == []


def test_cq_t7_the_plan_call_retries_and_never_blocks(ws, tmp_path, monkeypatch):
    quoted = seu.answer(_raw("shots", QUOTED))
    clean = seu.answer(_raw("shots", CLEAN))
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    log = seu.script_agent(monkeypatch, tmp_path, plan=[quoted, clean])
    found, why = se._Run(ctx, "").plan_round()
    calls = seu.agent_log(log)
    assert why is None and [c["stage"] for c in calls] == ["plan", "plan"]
    retry = calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1]
    assert "YOUR PREVIOUS REPLY WAS REJECTED" in retry
    assert "- plan: P25 cast quote: c2's descriptor holds a double quote" in retry
    assert found[0]["cast"][1]["descriptor"] == CLEAN
    assert se.cast_quote_problems(found[0]) == []
    log = seu.script_agent(monkeypatch, tmp_path, plan=[quoted, quoted])
    found, why = se._Run(ctx, "").plan_round()
    assert why is None and len(seu.agent_log(log)) == 2
    assert found[0]["cast"][1]["descriptor"] == QUOTED
    assert se._Run(ctx, "").plan_fatal(found) == []


def test_cq_t8_plan_checks_do_not_report_p25(ws):
    for mode in ("shots", "chained"):
        ctx, plan, shape = _plan(ws, QUOTED, mode=mode)
        assert se.cast_quote_problems(plan)
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert not any("P25" in m for m in hard + advisory)


def test_cq_t9_the_plan_prompt_wording(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = se._character_lib(WS).resolve_cast([(None, "kyra")])
    for mode in ("shots", "chained"):
        for cast in ([], members):
            ctx = seu.make_ctx(se, ws, mode=mode, members=cast)
            prompt = se.build_plan_prompt(ctx, [], [])
            assert ("the movie names them by this exact phrase everywhere. Each word of a "
                    "phrase uses only unaccented letters, digits, apostrophes and hyphens, and a "
                    "phrase never holds spoken words.") in prompt
            assert ('starts with "a " or "an ", does not end with a full stop and never holds '
                    "spoken words or double quotes.") in prompt
            assert ("when nothing you are given (the narrative or an attached image) says how "
                    "a character looks, make up a plausible look of your own:") in prompt
            assert "accessories." in prompt
            if cast:
                assert "accessories. Never use these names" in prompt
                assert "The following characters are already cast;" in prompt
            rest = prompt
            for lines in (True, False):
                rest = rest.replace(se.plan_reference(lines), "")
            assert "{" not in rest and "}" not in rest


def _undefined_cast(mode):
    raw = _raw(mode, CLEAN)
    raw["beats"][0]["cast"] = ["c9"]
    return raw


@pytest.mark.parametrize("mode", ["shots", "chained"])
def test_cq_t10_t11_a_fatal_retry_keeps_the_first_p25_plan(ws, tmp_path, monkeypatch, mode):
    first = seu.answer(_raw(mode, QUOTED))
    second = seu.answer(_undefined_cast(mode))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=2)
    expected, _shape = se.normalize_plan(ctx, _raw(mode, QUOTED))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[first, second])
    found, why = se._Run(ctx, "").plan_round()
    assert why is None and len(seu.agent_log(log)) == 2
    assert found[0] == expected
    assert se.cast_quote_problems(found[0])


def test_cq_t12_a_timeout_before_call_2_keeps_the_first_p25_plan(ws, tmp_path, monkeypatch):
    checks = []

    def expired(self):
        checks.append(1)
        return len(checks) == 2

    monkeypatch.setattr(se._Run, "expired", expired)
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2)
    expected, _shape = se.normalize_plan(ctx, _raw("shots", QUOTED))
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(_raw("shots", QUOTED)),
                                                        seu.answer(_raw("shots", CLEAN))])
    found, why = se._Run(ctx, "").plan_round()
    assert why is None and len(seu.agent_log(log)) == 1
    assert found[0] == expected


STOP = "Stop right there, you thief!"
STOP_NARRATIVE = 'A courier meets a guard. The guard shouts "%s" and the courier runs.' % STOP


def _copy_plan(ws, phrase="the guard", descriptor=CLEAN, line=STOP, narrative=STOP_NARRATIVE):
    _ctx, plan, _shape = _plan(ws, descriptor, phrase, narrative=narrative)
    plan["spoken_lines"] = [line]
    return plan


def test_cq_t13_a_phrase_copying_a_spoken_line(ws):
    plan = _copy_plan(ws, phrase="Stop right there")
    assert se.cast_quote_problems(plan, STOP_NARRATIVE) == [
        se.P25_COPY_MESSAGE % ("c2's phrase", 1, STOP)]


def test_cq_t14_a_two_word_phrase_is_not_flagged(ws):
    narrative = 'The courier yells "Stop the guard!" and runs.'
    plan = _copy_plan(ws, phrase="the guard", line="Stop the guard!", narrative=narrative)
    assert se.cast_quote_problems(plan, narrative) == []


def test_cq_t15_a_phrase_the_narrative_uses_outside_quotes(ws):
    line = "Ask the old fishmonger about it"
    said = 'The old fishmonger sells fish. The courier says "%s" and leaves.' % line
    silent = 'A fishmonger sells fish. The courier says "%s" and leaves.' % line
    plan = _copy_plan(ws, phrase="the old fishmonger", line=line, narrative=said)
    assert se.cast_quote_problems(plan, said) == []
    plan = _copy_plan(ws, phrase="the old fishmonger", line=line, narrative=silent)
    assert se.cast_quote_problems(plan, silent) == [
        se.P25_COPY_MESSAGE % ("c2's phrase", 1, line)]


def test_cq_t16_a_descriptor_copying_four_words(ws):
    plan = _copy_plan(ws, descriptor="a tall man who snarls stop right there you thief at the door")
    assert se.cast_quote_problems(plan, STOP_NARRATIVE) == [
        se.P25_COPY_MESSAGE % ("c2's descriptor", 1, STOP)]
    plan = _copy_plan(ws, descriptor="a tall man who snarls stop right there at the door")
    assert se.cast_quote_problems(plan, STOP_NARRATIVE) == []


def test_cq_t17_a_library_entry_copy_is_ignored(ws):
    plan = _copy_plan(ws, phrase="Stop right there")
    _set(plan, 1, cast_name="kyra")
    assert se.cast_quote_problems(plan, STOP_NARRATIVE) == []


def test_cq_t18_a_quote_and_a_copy_give_one_message(ws):
    plan = _copy_plan(ws, phrase='"Stop right there"')
    assert se.cast_quote_problems(plan, STOP_NARRATIVE) == [se.P25_MESSAGE % "c2's phrase"]


def test_cq_t19_the_plan_call_retries_on_a_copy_and_never_blocks(ws, tmp_path, monkeypatch):
    copied = seu.answer(_raw("shots", CLEAN, phrase="Stop right there"))
    clean = seu.answer(_raw("shots", CLEAN))
    ctx = seu.make_ctx(se, ws, mode="shots", panels=2, narrative=STOP_NARRATIVE)
    log = seu.script_agent(monkeypatch, tmp_path, plan=[copied, clean])
    found, why = se._Run(ctx, "").plan_round()
    calls = seu.agent_log(log)
    assert why is None and [c["stage"] for c in calls] == ["plan", "plan"]
    retry = calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1]
    assert "- plan: P25 cast quote: c2's phrase copies the words of spoken line 1" in retry
    assert found[0]["cast"][1]["phrase"] == "the guard"
    log = seu.script_agent(monkeypatch, tmp_path, plan=[copied, copied])
    found, why = se._Run(ctx, "").plan_round()
    assert why is None and len(seu.agent_log(log)) == 2
    assert found[0]["cast"][1]["phrase"] == "Stop right there"
    assert se._Run(ctx, "").plan_fatal(found) == []
