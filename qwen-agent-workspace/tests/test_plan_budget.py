"""Tests for the plan token budget and cut-off replies (docs/superpowers/specs/2026-11-10-plan-
budget-truncation-design.md, PB1-PB8: PBT1-PBT9): a plan that picks catalog LoRAs gets a larger
first budget, a reply cut off inside its JSON object is named, recorded in run.json and retried
once with half as much budget again, and every complete reply takes today's path unchanged.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_plan_budget.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws); the dry-run test runs the real bin/ltx-movie --dry-run, which makes no model call. No
test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import importlib.machinery
import json
import os
import shlex
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_plan_budget", os.path.join(WS, "story_engine.py")).load_module()

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
HEADER = "Error: the story model did not return a usable plan after 2 call(s)\n"
FOOTER = "Raw replies are kept in %s. Rerun the same command to try again.\n"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _cut(mode, n, keep=300):
    """A plan reply cut off after keep characters (status ok, as bin/qwen-agent reports it)."""
    full = json.dumps(seu.plan_json(mode, n))
    assert len(full) > keep
    return {"answer": full[:keep]}


def _catalog(tmp_path):
    entry = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "fast"), "fast-motion")
    return {"schema_version": 1, "entries": [entry]}


def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _run(ws, tmp_path, monkeypatch, plan, mode="chained", n=3, panel=None, critic=(), **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=panel or {},
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _budgets(log):
    return [r["argv"][r["argv"].index("--max-tokens") + 1] for r in log if r["stage"] == "plan"]


def _rounds0(ctx):
    return os.path.join(ctx.story_dir, "story_rounds", "round_0")


def _plan_calls(ctx):
    with open(os.path.join(ctx.story_dir, "story_rounds", "run.json"), encoding="utf-8") as f:
        return [c for c in json.load(f)["calls"] if c["stage"] == "plan"]


def _plan_lines(out):
    return [line for line in out.splitlines() if line.startswith("plan: ")]


# --- PBT1 (PB1, PB5, PB6): the budget formulas and the exact messages -------------------------

def test_pbt1_the_budget_formulas_and_the_messages():
    assert (se.plan_max_tokens(14), se.plan_max_tokens(30)) == (4096, 7500)
    assert (se.plan_max_tokens(5), se.plan_max_tokens(17)) == (4096, 4250)
    assert (se.plan_max_tokens(6, catalog=True), se.plan_max_tokens(17, catalog=True),
            se.plan_max_tokens(45, catalog=True)) == (4096, 6800, 18000)
    assert (se.PLAN_CATALOG_TOKENS_PER_BEAT, se.PLAN_MAX_TOKENS_CAP) == (400, 16384)
    assert [se.escalated_plan_tokens(b) for b in (4096, 4250, 6800, 12000, 18000)] == [
        6144, 6375, 10200, 16384, 18000]
    assert se.PLAN_CUT_OFF_NOTE % (1, 6800) == (
        "plan: reply 1 was cut off at 6800 tokens before its JSON object closed")
    assert se.PLAN_CUT_OFF_NEXT % (2, 10200) == "; call 2 gets 10200 tokens"
    assert se.PLAN_CUT_OFF_PROBLEM % (10200, 2, " or --no-auto-lora") == (
        "the reply was cut off at 10200 tokens, the token budget of call 2, before its JSON "
        "object closed; fewer panels (--panels or --length) or --no-auto-lora make the plan "
        "shorter")
    assert se.PLAN_CUT_OFF_RETRY % (6800, 10200) == (
        "\n\nYOUR PREVIOUS REPLY WAS CUT OFF: it reached its limit of 6800 tokens before the JSON "
        "object closed, so it was discarded. This reply may use up to 10200 tokens. Write the "
        "complete JSON object compactly, with no indentation and no line breaks, so that it "
        "fits, and reply with the JSON object only.")


# --- PBT2 (PB1, PB2): the first budget follows the plan prompt's LoRA paragraph ---------------

def test_pbt2_plan_tokens_follows_the_lora_paragraph(ws, tmp_path):
    catalog = _catalog(tmp_path)
    cases = [(dict(catalog=catalog), 6800, True),
             (dict(catalog=catalog, auto_lora=False), 4250, False),
             (dict(), 4250, False)]
    for kw, budget, picks in cases:
        ctx = seu.make_ctx(se, ws, mode="shots", panels=15, **kw)
        compatible = se.compatible_entries(ctx)
        assert se.plan_tokens(ctx, compatible) == budget, kw
        prompt = se.build_plan_prompt(ctx, compatible, ctx.pinned)
        assert (se.LORA_PICK_PARAGRAPH in prompt) == picks, kw
    off = seu.make_ctx(se, ws, mode="shots", panels=15, catalog=catalog, auto_lora=False)
    assert se.plan_tokens(off, catalog["entries"]) == 4250
    assert se.LORA_PICK_PARAGRAPH not in se.build_plan_prompt(off, catalog["entries"], off.pinned)
    ctx = seu.make_ctx(se, ws, mode="shots", panels=4, catalog=catalog)
    assert se.plan_tokens(ctx, se.compatible_entries(ctx)) == 4096
    target = seu.make_ctx(se, ws, mode="shots", panels=17, panels_target=15, catalog=catalog)
    assert se.plan_tokens(target, se.compatible_entries(target)) == 6800


# --- PBT3 (PB3): cut_off_json -------------------------------------------------------------------

def test_pbt3_cut_off_json():
    full = json.dumps(seu.plan_json("shots", 15))
    assert se.cut_off_json(full[:-1]) is True
    assert se.cut_off_json(full) is False
    assert se.cut_off_json("```json\n" + full[:2000]) is True
    assert se.cut_off_json("```json\n" + full + "\n```") is False
    assert se.cut_off_json('Sure! {"a": [1, 2') is True
    assert se.cut_off_json('{"a": "}"') is True
    assert se.cut_off_json('{"a": "x\\"}"') is True
    assert se.cut_off_json('{"a": "x\\"y"}') is False
    assert se.cut_off_json('{"a": "\\\\"}') is False
    assert se.cut_off_json("{not json}") is False
    for text in (None, "", "   ", "no braces at all", "[1, 2", "I think the story is about rain."):
        assert se.cut_off_json(text) is False, text


# --- PBT4 (PB3-PB5, PB7): a cut-off reply is retried with more tokens, then the run goes on -----

def test_pbt4_a_cut_off_reply_is_retried_with_more_tokens(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("chained", 3),
                                                    seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert _budgets(log) == ["4096", "6144"]
    first, second = log[0]["argv"][-1], log[1]["argv"][-1]
    assert second == first + se.PLAN_CUT_OFF_RETRY % (4096, 6144)
    assert "Previous reply:" not in second
    assert _plan_lines(capsys.readouterr().out) == [
        "plan: call 1 of 2",
        "plan: reply 1 was cut off at 4096 tokens before its JSON object closed; call 2 gets "
        "6144 tokens",
        "plan: call 2 of 2"]
    calls = _plan_calls(ctx)
    assert calls[0]["cut_off_at_tokens"] == 4096 and calls[0]["status"] == "ok"
    assert "cut_off_at_tokens" not in calls[1]
    with open(os.path.join(_rounds0(ctx), "plan_reply_1.txt"), encoding="utf-8") as f:
        assert f.read() == _cut("chained", 3)["answer"]


# --- PBT5 (PB1-PB7): the 15-panel auto-lora run of the report, cut off twice ---------------------

def test_pbt5_fifteen_panel_auto_lora_cut_off_twice(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("shots", 15, 2000),
                                                    _cut("shots", 15, 3000)],
                        mode="shots", n=15, catalog=_catalog(tmp_path))
    assert rc == 1
    assert _budgets(log) == ["6800", "10200"]
    assert [r["stage"] for r in log] == ["plan", "plan"]
    captured = capsys.readouterr()
    assert captured.err == (
        HEADER + "  - the reply was cut off at 10200 tokens, the token budget of call 2, before "
        "its JSON object closed; fewer panels (--panels or --length) or --no-auto-lora make the "
        "plan shorter\n" + FOOTER % _rounds0(ctx))
    assert _plan_lines(captured.out) == [
        "plan: call 1 of 2",
        "plan: reply 1 was cut off at 6800 tokens before its JSON object closed; call 2 gets "
        "10200 tokens",
        "plan: call 2 of 2",
        "plan: reply 2 was cut off at 10200 tokens before its JSON object closed"]
    assert [c.get("cut_off_at_tokens") for c in _plan_calls(ctx)] == [6800, 10200]
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + se.PLAN_CUT_OFF_RETRY % (6800, 10200)


# --- PBT6 (PB1, PB8): without catalog picks the budget is today's ------------------------------

@pytest.mark.parametrize("auto_lora", [True, False])
def test_pbt6_without_catalog_picks_the_budget_is_unchanged(ws, tmp_path, monkeypatch, capsys,
                                                            auto_lora):
    catalog = _catalog(tmp_path) if not auto_lora else {"schema_version": 1, "entries": []}
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("shots", 15), _cut("shots", 15)],
                        mode="shots", n=15, catalog=catalog, auto_lora=auto_lora)
    assert rc == 1
    assert _budgets(log) == ["4250", "6375"]
    assert capsys.readouterr().err == (
        HEADER + "  - the reply was cut off at 6375 tokens, the token budget of call 2, before "
        "its JSON object closed; fewer panels (--panels or --length) make the plan shorter\n"
        + FOOTER % _rounds0(ctx))


# --- PBT7 (PB8): a closed reply, or an unclosed one whose status is not ok, keeps today's path ----

def test_pbt7_complete_and_non_ok_replies_keep_todays_path(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [{"answer": "{not json}"},
                                                    seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert _budgets(log) == ["4096", "4096"]
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object"
            " (the JSON parser stopped at line 1, column 2 of the previous reply: Expecting "
            "property name enclosed in double quotes)\nPrevious reply:\n{not json}\n\nReply "
            "with the complete corrected JSON object only.") in log[1]["argv"][-1]
    assert not [c for c in _plan_calls(ctx) if "cut_off_at_tokens" in c]
    assert "was cut off" not in capsys.readouterr().out
    cut = dict(_cut("chained", 3), status="max_rounds")
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [cut, dict(cut)], story_id="s2")
    assert rc == 1
    assert _budgets(log) == ["4096", "4096"]
    assert capsys.readouterr().err == (HEADER + "  - the reply is not one JSON object\n"
                                       + FOOTER % _rounds0(ctx))
    assert not [c for c in _plan_calls(ctx) if "cut_off_at_tokens" in c]


# --- PBT8 (PB4, PB6): only the last call's cut-off is named --------------------------------------

def test_pbt8_a_cut_off_then_garbage_reply_keeps_the_generic_message(ws, tmp_path, monkeypatch,
                                                                      capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("chained", 3), {"answer": "nope"}])
    assert rc == 1
    assert _budgets(log) == ["4096", "6144"]
    assert capsys.readouterr().err == (HEADER + "  - the reply is not one JSON object\n"
                                       + FOOTER % _rounds0(ctx))
    assert [c.get("cut_off_at_tokens") for c in _plan_calls(ctx)] == [4096, None]


# --- PBT9 (PB2): the dry run prints the first call's budget ------------------------------------

def test_pbt9_the_dry_run_prints_the_first_calls_budget(tmp_path, story_env):
    seu.make_catalog(story_env["catalog"], _catalog(tmp_path)["entries"])
    story_dir = os.path.join(WS, "generated", "stories", "pbt9-%d" % os.getpid())
    assert not os.path.exists(story_dir)

    def budget(*flags):
        proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                               "--story-id", os.path.basename(story_dir), "--dry-run",
                               "--no-review", "--shots", "--panels", "15"] + list(flags),
                              cwd=WS, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        argv = shlex.split(proc.stdout.split("Command (subprocess timeout 680s): ", 1)[1]
                           .split("\n\nRendered plan prompt:\n", 1)[0])
        return argv[argv.index("--max-tokens") + 1]

    assert budget() == "6800"
    assert budget("--no-auto-lora") == "4250"
    os.remove(os.path.join(story_env["catalog"], "catalog.json"))
    assert budget() == "4250"
    assert not os.path.exists(story_dir)
