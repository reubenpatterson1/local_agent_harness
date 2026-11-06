# Story no default crowd: a place gets a crowd only when the narrative has one

Date: 2026-11-06

Status: design spec and implementation plan in one document. Problem report (2026-11-06, user): every robust-engine story puts a crowd or an audience in the frame, including stories whose narrative has none. The fix: the plan prompt asks for a crowd in a setting sentence only when the narrative mentions one, and the speaking-panel Image: instructions stop naming a crowd. The user decided the intent; this spec settles the wording and the mechanism. Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/cr-wt`, branch `story-no-default-crowd`, off `origin/qwen-agent-redteam` at `b581e40`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `b581e40`.

Requirement IDs are **NC1-NC6**, tests **NCT1-NCT5**, KPIs **NCK1-NCK5**, live checks **L1-L2**. At `b581e40`, `git grep -nE "\bNC[0-9]+\b|\bNCT[0-9]+\b|\bNCK[0-9]+\b"` finds nothing.

---

## 1. Cause (verified at `b581e40`)

1. **The location rule asks for a crowd at every place.** `PLAN_PROMPT_TEMPLATE` (`story_engine.py:350-353`) says a setting is one sentence that "names the period, the place, the ground, the light and any crowd or other group of people in the background." A model that fills templates writes a crowd into every setting. `pasted_pieces` (`:2249-2270`) then pastes that setting sentence into every Image: (chained panel 1 and every shots panel) and every no_stills Prompt:.
2. **The speaking-panel Image: instructions name a crowd.** `SPEAKING_IMAGE_SENTENCE` (`:3029-3030`) and `SPEAKING_IMAGE_SILENT_SENTENCE` (`:3024-3026`) both end with "any crowd stays in the background", whether the movie has a crowd or not. `build_panel_prompt` adds them to the `image:` key line of a speaking chained panel 1 or shots panel (`:4104-4110`).
3. **The cast rule** (`:342-344`) says a group "is never a cast entry, and belongs in the setting sentence of its place." It only says where a group goes if one exists, so it does not cause the problem. It stays unchanged (NC3).

Introduced by the narrative dialogue fidelity spec (`docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md` 7.1(b), 7.2) for the hockey narrative, which has "cheering crowds in the stands". That case keeps working (NCT4, L2).

## 2. Requirements

**NC1 Location rule [spec choice: the wording].** In `PLAN_PROMPT_TEMPLATE`, the location rule ends:

> … and names the period, the place, the ground and the light, and a crowd or other group of people in the background only when the narrative mentions one.

The rule stays plain text for every narrative, with no code switch. The reasons:
- The user chose wording only.
- A switch keyed on `GROUP_NOUNS` would misfire both ways. It would fire on "two people" (`people` is in the list) and stay silent on "a packed arena".
- The model reads the narrative and judges "mentions one" better than a word list does.
- One template stays shared by all three modes.

`LOCATION_FIXED` (library places, `:1098-1127`) is unchanged, because those settings come from the library and the model does not write them.

**NC2 Speaking Image: sentences [spec choice: drop the clause outright].** The new texts:
- `SPEAKING_IMAGE_SENTENCE = " @@SPEAKER@@ is the only person in the foreground, facing the camera."`
- `SPEAKING_IMAGE_SILENT_SENTENCE` = `" @@SPEAKER@@ is in the foreground, facing the camera; also in frame, and silent: @@SILENT@@."`

The clause is dropped, not made conditional on the setting. Three reasons:
1. It is a constant-only change, so the chained, shots and no_stills code paths and `build_panel_prompt` keep their control flow.
2. When the narrative has a crowd, the pasted setting sentence already puts it "in the background" (NC1). "the only person in the foreground" still keeps the speaker alone up front.
3. A conditional would need a group detector on the setting text. That detector would have the same false positives as the switch rejected in NC1.

Legacy paths do not use these constants.

**NC3 Unchanged prompt texts.** The cast rule (`:342-344`) and every other prompt text in `story_engine.py`, `bin/ltx-movie`, `bin/ltx-story-images` and `bin/ltx-story-manifest` stay unchanged. The audit (Section 3) found no other text that adds people the narrative did not ask for.

**NC4 Guard.** After the change, the only module-level string in `story_engine.py` that contains "crowd" (case-insensitive) is `PLAN_PROMPT_TEMPLATE`, and it contains the word exactly twice: in the cast rule's "a crowd" and in NC1's "a crowd". NCT1 pins this, so a later text cannot bring back a default crowd without failing a test.

**NC5 Validators and critic are neutral (verified; no change).**
- `_setting_problems` (`:1810-1818`) checks only the "The setting is " start and that the setting is one sentence.
- `_setting_length` (`:1804-1807`) checks the 12-45 word count, as an advisory.
- Plan check P4 (`:2391-2396`) uses only those two.
- character_lib S12 checks that the setting sentence is present and long enough.
- `CRITIC_PROMPT_TEMPLATE` (`:4166-4208`) scores continuity, story and renderability, and says a patch never includes a setting sentence.
- `PLAN_REFERENCE_PLAN`, `FORMAT_REFERENCE` and `COPIED_EXAMPLES` show no crowd.
- The P15 notes (`:1477`, `:1774`, "describe it in the setting sentence instead") fire only after the model has itself cast a group. They are reports and change no setting.

None of these requires or rewards a crowd. NCT5 pins this.

**NC6 Scope.**
- `story_engine.py` is the only pinned file that changes. `bin/ltx-movie` and `character_lib.py` are untouched.
- No new behaviour, no new import, standard library only.
- Saved stories do not matter. `plan.json` stores the model's plan, not the prompt. `story_rounds/plan_prompt.txt` is written for the record and never read back. A reused story.md keeps its old settings, crowd included, until `--force-story` or a new story id. The hockey fixtures (`tests/fixtures/narrative_fidelity/hockey-*`, `tests/fixtures/writer_pacing/hockey-*`) are recorded model output for a narrative that has a crowd, and stay as they are.

## 3. Audit of prompt texts (NC3)

| Where | Text | Verdict |
|---|---|---|
| `story_engine.py:342-344` cast rule | "a group of people (a crowd, an audience, …) is never a cast entry, and belongs in the setting sentence of its place" | Applies only when a group exists. Kept. |
| `:350-353` location rule | "…and any crowd or other group of people in the background." | **Cause. Changed (NC1).** |
| `:3024-3030` speaking Image: sentences | "…; any crowd stays in the background." | **Cause. Changed (NC2).** |
| `:530-540` `GROUP_NOUNS`, `GROUP_DESCRIPTOR_RE`, `COLLECTIVE_NOUNS` | word lists, including "people extras" | Detectors only. Kept. |
| `:2924-2965` `KEY_LINE_TEMPLATES` `chained_image`/`shots_image` | "the background" | Scenery, not people. `shots_image` also says "Never name a person who is not in this shot". Kept. |
| `:2914` `SEED_PANEL`, `:384` `SEED_PARAGRAPH` | describe the attached image; "invent no person who is not visible" | Restrictive. Kept. |
| `:427` `END_FRAME_RULE` | "foreground or background" | Where cast members are placed. Kept. |
| `:2684`, `:2697`, `:2794-2876` references and examples | a lone fishmonger, a forest | No crowd. Kept. |
| `bin/ltx-movie:166`, `:194`, `:224` legacy Image:/Prompt: templates | "the setting and background", "the background" | Scenery. Kept. |
| `bin/ltx-movie:228` legacy shots setting rule | "names the period, the place, the ground and the light" | Already has no crowd. Kept. |
| `bin/ltx-movie:242` `SEED_IMAGE_PREFACE` | "do not add people … not visible" | Restrictive. Kept. |
| `bin/ltx-story-images`, `bin/ltx-story-manifest` | joins Image: with Style: (`:206-221`) and parses labels | No prompt wording. Kept. |
| `character_lib.py:112-115` S10, `:201-203` shots cast rule | "any other person may appear … only far in the background" | Limits extras and does not invite them. It is not a file in scope. Kept. |

No text in these files contains "bustling", "lively", "busy" or "background figures". "extras" appears only in `GROUP_NOUNS`.

## 4. Tests

**New file `tests/test_no_default_crowd.py`** (Plan Task 1, Step 1; the full text is in the Plan section):
- **NCT1:** the exact NC1 clause sits before `@@LOCATION_FIXED@@`. "any crowd" is absent from the template, which contains "crowd" exactly twice. The NC2 constants match exactly, and `SPEAKING_SENTENCES["image"]` matches too. NC4 holds: no other module-level string contains "crowd".
- **NCT2:** a narrative without a crowd gets plan prompts with the NC1 clause and no "any crowd", and "crowd" appears exactly twice. Cases: chained; shots; no_stills; seeded chained; shots with speech.
- **NCT3:** a movie without a crowd gets no "crowd" in any panel prompt or critic prompt. Cases: a speaking chained panel 1, a speaking shots panel, a speaking no_stills panel, and a chained panel 1 with a silent co-star. The `image:` key lines end with the NC2 texts, filled in.
- **NCT4:** a narrative with a crowd keeps it. The plan prompt holds the narrative and the NC1 clause. A setting that names a crowd survives `normalize_plan` unchanged, and it opens the Image: of every shots panel and of chained panel 1.
- **NCT5:** a setting with a crowd and one without both pass `_setting_problems` and `_setting_length`. A setting with a bad start still fails, as a control. `plan_checks` reports no P4 for either plan, and `PLAN_REFERENCE_PLAN` has no crowd. NCT5 pins behaviour that does not change, so it passes before the code change too.

**Edited pins (old text → new text, Task 1):** `tests/test_pinned_cast.py:163-164` and `:499-501`, `tests/test_narrative_fidelity.py:659-660` and `:720-721`, `tests/test_dialogue.py:774-775`, `tests/test_location_story.py:113`, `:122`, `:124` and `:130`.

**Golden fixtures (Task 1):** six plan-prompt fixtures each hold the old location clause exactly once:
- `tests/fixtures/location/plan_prompt_chained.txt`
- `tests/fixtures/location/plan_prompt_chained_cast.txt`
- `tests/fixtures/location/plan_prompt_shots.txt`
- `tests/fixtures/pinned_cast/uncast_chained_lines.txt`
- `tests/fixtures/pinned_cast/uncast_chained_seed.txt`
- `tests/fixtures/pinned_cast/uncast_shots_lines.txt`

There is no `uncast_shots_seed.txt`. They are edited with one mechanical `sed`, with counts checked before and after. LS1 (`tests/test_location_story.py:56-69`) and PT2 (`tests/test_pinned_cast.py:202-209`) then prove byte identity against `build_plan_prompt`. No panel-prompt fixture contains "crowd stays" (`grep -rn "crowd stays" tests/fixtures` prints nothing). Every other "crowd" in `tests/` is a narrative under test (speaker attribution, soft panel count, shot format) or a recorded hockey reply, and is unchanged.

## 5. Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| NCK1 | The full suite has no failure beyond the baseline recorded at `b581e40`. The final run is `2 failed, P0+5 passed, 2 skipped` (P0 = the baseline PASSED count, expected 2664) | gate, V1 |
| NCK2 | `grep -c "any crowd" story_engine.py` gives `0`. `grep -c crowd story_engine.py` goes from `8` to `6` | V1 |
| NCK3 | The only pinned file changed between `b581e40` and the final commit is `story_engine.py`, with numstat `4 6` | V1 |
| NCK4 | L1: a narrative with no crowd yields 0 group words in every plan.json setting and every story.md Image: line | L1 (user) |
| NCK5 | L2: a narrative with a crowd yields at least one setting that names it, and that setting is copied word for word into the Image: lines at that place | L2 (user) |

Every NC requirement and NCT test is a must-have. There are no nice-to-haves.

## 6. Live checks (the user runs these on the pipeline host; the agent never does)

Both use the robust engine through Compose in the movie UI, with a **new story id** for each run, or with `--force-story`, so that no old plan.json is reused. Use shots mode, 4 panels, and one quoted line so that a speaking panel occurs.

- **L1, no crowd.** Narrative: `A lighthouse keeper climbs the spiral stairs at dusk, lights the great lamp, and says "Home is wherever the light still turns." as the beam sweeps the sea.` Then, in `generated/stories/<id>/`:
  - `python3 -c 'import json; [print(l["setting"]) for l in json.load(open("plan.json"))["locations"]]'`
  - `grep -E '^Image:' story.md | grep -ciE '\b(crowd|crowds|audience|fans|spectators|onlookers|bystanders|passers-?by|pedestrians|people|extras|figures)\b'`

  Expected: the settings name no group, and the count is `0`. Also look at the panel stills: nobody stands behind the keeper.
- **L2, crowd.** Narrative: `A young skater lands the final jump at a packed rink while a crowd of fans cheers in the stands, then says "That one was for you." to the camera.` The same commands, with `grep -cF "<the crowd setting sentence>" story.md`. Expected: at least one setting names the crowd, and that sentence appears once in each Image: line at its place.

If L1 still shows a crowd, the plain-text rule is not enough for this model. The next step would be a code switch on the narrative, which needs its own spec. That is out of scope here.

## 7. Review focus

1. **No-crowd output.** NCT2 and NCT3 cover every path a no-crowd narrative can take: three modes, a seed, speech, speaking panels, a silent co-star and the critic.
2. **The narrative with a crowd still works** (NCT4). This is the case the old text was written for.
3. **Byte-exact fixture edits.** The fixtures have no trailing newline. macOS `sed -i ''` keeps that (verified in scratch), and LS1 and PT2 are the proof.
4. **NCT1's module scan** fails if a future constant mentions "crowd". This is on purpose. Detector word lists are frozensets, which the scan skips.

---

## Plan

**House rules** (every task):
- Work only in `$S/cr-wt`. Never touch `/Users/reubenpatterson/local_agent_harness`.
- Never stash, reset, amend, push or open a PR.
- Never contact a server, render, run a model, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. The one exception is Task 1 Step 4's `sed` on the six fixtures.
- An Edit's old text occurs exactly once in the file. If it does not, stop and report.
- Every changed `.py` file compiles on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

The whole plan was replayed in a scratch copy of `b581e40`: the new file failed `4 failed, 1 passed` before the code change. After the edits, the new file and every edited test file passed. Across 11 story test files the result was `1 failed, 443 passed, 2 skipped`, and the one failure is the baseline failure `test_rst62_import_sets`.

### Before Task 1: the baseline (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/cr-baseline; mkdir -p $D
cd $S/cr-wt/qwen-agent-workspace
git branch --show-current                                   # story-no-default-crowd
git diff --stat b581e40 HEAD -- . ':(exclude)docs' | tail -1 # no output (only this spec is committed)
git status --short                                          # no output
wc -l story_engine.py tests/test_pinned_cast.py tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_location_story.py tests/test_movie_ui_builder.py
# expected: 5483, 742, 1445, 2115, 330, 302
df -g . | tail -1                                           # at least 5 GiB free
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                   # record as P0
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
```

Expected:
- The summary is `2 failed, 2664 passed, 2 skipped`.
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`.
- There is no `ERROR` line.
- `test_mut26` passes.

If `test_tr27_fanout_two_rounds_and_missing_reasons` or `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` also fails, rerun the two alone. `2 passed` means the baseline stands. Any other difference: stop and report.

Then write the gate files, which are scratch files and never staged:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/cr-baseline
python3 - "$S/at-baseline/gate.py" "$D/gate.py" <<'EOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
for old, new in (("The task gate of the story agent tool restriction plan", "The task gate of the story no default crowd plan"),
                 ("tests/test_qwen_agent_tool_restriction.py", "tests/test_no_default_crowd.py")):
    assert s.count(old) == 2 if old.startswith("tests/") else s.count(old) == 1, old
    s = s.replace(old, new)
open(sys.argv[2], "w", encoding="utf-8").write(s)
EOF
sed -e 's#/at-baseline#/cr-baseline#' -e 's#/nt-wt/#/cr-wt/#' $S/at-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'EOF'
# story no default crowd plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged story_engine.py changes in Task 1; Task 2 moves BASELINE
1 2 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
EOF
grep -c cr-baseline $D/gate-run.sh; grep -c cr-wt $D/gate-run.sh; grep -c test_no_default_crowd $D/gate.py   # 1, 1, 2
```

**The gate** for task N is `zsh $S/cr-baseline/gate-run.sh N`, a full run of about 20 minutes. It prints:
- `disk ok`
- the pytest summary
- the gate line, then `GATE PASS`
- `2 passed` for the flake rerun
- `ATK2 OK lines unchanged`

On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the prompt texts, their tests and fixtures (one commit)

**Files:**
- `story_engine.py` (pinned)
- `tests/test_no_default_crowd.py` (new)
- `tests/test_pinned_cast.py`
- `tests/test_narrative_fidelity.py`
- `tests/test_dialogue.py`
- `tests/test_location_story.py`
- the six fixtures of Section 4

- [ ] **Step 1: Write `tests/test_no_default_crowd.py`** with the Write tool, exactly:

```python
"""Tests for the story-no-default-crowd change (docs/superpowers/specs/2026-11-06-story-no-
default-crowd-design.md: NCT1-NCT5): the robust story engine adds a crowd or other group of
people to a place only when the narrative mentions one.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_no_default_crowd.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a model server: every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog)
and builds prompts in memory.
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


se = _load("story_engine_for_no_default_crowd", "story_engine.py")

LOCATION_CLAUSE = ("names the period, the place, the ground and the light, and a crowd or other "
                   "group of people in the background only when the narrative mentions one.")
SPEAKING_IMAGE = " @@SPEAKER@@ is the only person in the foreground, facing the camera."
SPEAKING_IMAGE_SILENT = (" @@SPEAKER@@ is in the foreground, facing the camera; also in frame, "
                         "and silent: @@SILENT@@.")
CROWD_NARRATIVE = ("A young skater wins the final at a packed ice rink while a crowd of fans "
                   "cheers in the stands.")
CROWD_SETTING = ("The setting is an indoor ice rink in a modern city at night, smooth white ice "
                 "underfoot, a cheering crowd of fans in the stands in the background, under "
                 "bright floodlights.")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _strings(value):
    """Every str inside a str, dict, list or tuple value, in order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def _plan(ctx, mode, n, speaker_beat=None, locations=None):
    raw = seu.plan_json(mode, n)
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = "c1"
    if locations is not None:
        raw["locations"] = locations
    return se.normalize_plan(ctx, raw)[0]


def _parts(ctx, plan, n):
    return [se.empty_parts(ctx.mode, k, plan, ctx) for k in range(1, n + 1)]


def _key_line(prompt, key):
    return [line for line in prompt.split("\n") if line.startswith(key + ": ")][0]


# --- NCT1: the prompt texts (NC1, NC2, NC4) ----------------------------------------------------

def test_nct1_the_prompt_texts_name_no_default_crowd():
    assert LOCATION_CLAUSE + "@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE
    assert "any crowd" not in se.PLAN_PROMPT_TEMPLATE
    assert se.PLAN_PROMPT_TEMPLATE.lower().count("crowd") == 2
    assert se.SPEAKING_IMAGE_SENTENCE == SPEAKING_IMAGE
    assert se.SPEAKING_IMAGE_SILENT_SENTENCE == SPEAKING_IMAGE_SILENT
    assert se.SPEAKING_SENTENCES["image"] == SPEAKING_IMAGE
    for name, value in sorted(vars(se).items()):
        if name.startswith("__") or name == "PLAN_PROMPT_TEMPLATE":
            continue
        for text in _strings(value):
            assert "crowd" not in text.lower(), name


# --- NCT2: a plan prompt for a narrative without a crowd (NC1) -------------------------------

def test_nct2_plan_prompts_have_only_the_conditional_crowd_clause(ws):
    for kw in (dict(mode="chained"), dict(mode="shots", panels=4), dict(mode="no_stills"),
               dict(mode="chained", seed_agent_image="/s/seed.png"),
               dict(mode="shots", panels=4, narration="speech")):
        ctx = seu.make_ctx(se, ws, **kw)
        assert "crowd" not in ctx.narrative.lower()
        prompt = se.build_plan_prompt(ctx, [], [])
        assert LOCATION_CLAUSE + "\nprops: " in prompt, kw
        assert "any crowd" not in prompt, kw
        assert prompt.lower().count("crowd") == 2, kw


# --- NCT3: the panel and critic prompts of a movie without a crowd (NC2, NC3) -----------------

def test_nct3_panel_and_critic_prompts_name_no_crowd(ws):
    prompts = []
    for mode, n, k in (("chained", 3, 1), ("shots", 3, 2), ("no_stills", 3, 2)):
        ctx = seu.make_ctx(se, ws, mode=mode, panels=n)
        plan = _plan(ctx, mode, n, speaker_beat=k)
        parts = _parts(ctx, plan, n)
        panels = [se.build_panel_prompt(ctx, plan, parts, j) for j in range(1, n + 1)]
        if mode != "no_stills":
            assert _key_line(panels[k - 1], "image").endswith(
                ' "the courier" is the only person in the foreground, facing the camera.'), mode
        prompts += panels + [se.build_critic_prompt(plan, se.assemble(ctx, plan, parts), ([], []))]
    ctx = seu.make_ctx(se, ws)
    plan = _plan(ctx, "chained", 3, speaker_beat=1)
    plan["beats"][0]["cast"] = ["c1", "c2"]
    silent = se.build_panel_prompt(ctx, plan, _parts(ctx, plan, 3), 1)
    assert _key_line(silent, "image").endswith(
        ' "the courier" is in the foreground, facing the camera; also in frame, and silent: '
        '"the old monk".')
    for prompt in prompts + [silent]:
        assert "crowd" not in prompt.lower()


# --- NCT4: a narrative with a crowd keeps it (NC1, NC5) ----------------------------------------

def test_nct4_a_crowd_in_the_narrative_reaches_the_setting_and_every_image(ws):
    ctx = seu.make_ctx(se, ws, mode="shots", panels=3, narrative=CROWD_NARRATIVE)
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "\n" + CROWD_NARRATIVE + "\n" in prompt and LOCATION_CLAUSE in prompt
    plan = _plan(ctx, "shots", 3, locations=[{"id": "l1", "setting": CROWD_SETTING},
                                             {"id": "l2", "setting": seu.TEMPLE}])
    assert [l["setting"] for l in plan["locations"]] == [CROWD_SETTING, seu.TEMPLE]
    parts = _parts(ctx, plan, 3)
    for k in (1, 2, 3):
        assert dict(se.panel_fields(ctx, plan, parts, k))["Image"].startswith(CROWD_SETTING), k
    chained = seu.make_ctx(se, ws, narrative=CROWD_NARRATIVE)
    cplan = _plan(chained, "chained", 3, locations=[{"id": "l1", "setting": CROWD_SETTING},
                                                    {"id": "l2", "setting": seu.TEMPLE}])
    image = dict(se.panel_fields(chained, cplan, _parts(chained, cplan, 3), 1))["Image"]
    assert image.startswith(CROWD_SETTING)


# --- NCT5: the validators neither require nor reward a crowd (NC5) -----------------------------

def test_nct5_setting_checks_are_neutral_about_crowds(ws):
    for setting in (CROWD_SETTING, seu.HARBOUR, seu.TEMPLE):
        assert se._setting_problems(setting) == [], setting
        assert se._setting_length(setting) is None, setting
    assert se._setting_problems("A rink with fans.") == ['does not start with "The setting is"']
    for locations in (None, [{"id": "l1", "setting": CROWD_SETTING},
                             {"id": "l2", "setting": seu.TEMPLE}]):
        ctx = seu.make_ctx(se, ws)
        raw = seu.plan_json("chained", 3)
        if locations is not None:
            raw["locations"] = locations
        plan, shape = se.normalize_plan(ctx, raw)
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert [m for m in hard + advisory if " P4 " in m] == [], locations
    assert "crowd" not in json.dumps(se.PLAN_REFERENCE_PLAN).lower()
```

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_no_default_crowd.py | tail -1` should print `4 failed, 1 passed`. NCT5 pins behaviour that does not change, so it passes now.

- [ ] **Step 3: Edit `story_engine.py`, three Edits.**

E1 (`:352-353`). Old:
```python
    "the period, the place, the ground, the light and any crowd or other group of people in the "
    "background.@@LOCATION_FIXED@@\n"
```
New:
```python
    "the period, the place, the ground and the light, and a crowd or other group of people in the "
    "background only when the narrative mentions one.@@LOCATION_FIXED@@\n"
```
E2 (`:3024-3026`). Old:
```python
SPEAKING_IMAGE_SILENT_SENTENCE = (" @@SPEAKER@@ is in the foreground, facing the camera; also in "
                                  "frame, and silent: @@SILENT@@; any crowd stays in the "
                                  "background.")
```
New:
```python
SPEAKING_IMAGE_SILENT_SENTENCE = (" @@SPEAKER@@ is in the foreground, facing the camera; also in "
                                  "frame, and silent: @@SILENT@@.")
```
E3 (`:3029-3030`). Old:
```python
SPEAKING_IMAGE_SENTENCE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; "
                           "any crowd stays in the background.")
```
New:
```python
SPEAKING_IMAGE_SENTENCE = " @@SPEAKER@@ is the only person in the foreground, facing the camera."
```

- [ ] **Step 4: Edit the existing pins (Edit tool) and the fixtures (`sed`).**

T1 `tests/test_pinned_cast.py:163-164`. Old:
```python
    "SPEAKING_IMAGE_SENTENCE": (" @@SPEAKER@@ is the only person in the foreground, facing the "
                                "camera; any crowd stays in the background."),
```
New:
```python
    "SPEAKING_IMAGE_SENTENCE": (" @@SPEAKER@@ is the only person in the foreground, facing the "
                                "camera."),
```
T2 `tests/test_pinned_cast.py:499-501`: the same old and new text as E2.

T3 `tests/test_narrative_fidelity.py:659-660`. Old:
```python
SETTING_LINE = ("names the period, the place, the ground, the light and any crowd or other group "
                "of people in the background.\n")
```
New:
```python
SETTING_LINE = ("names the period, the place, the ground and the light, and a crowd or other group "
                "of people in the background only when the narrative mentions one.\n")
```
T4 `tests/test_narrative_fidelity.py:720-721`. Old:
```python
SPEAKING_IMAGE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; any crowd "
                  "stays in the background.")
```
New:
```python
SPEAKING_IMAGE = " @@SPEAKER@@ is the only person in the foreground, facing the camera."
```
T5 `tests/test_dialogue.py:775`. Old:
```python
            "foreground, facing the camera; any crowd stays in the background.\n") in prompt
```
New:
```python
            "foreground, facing the camera.\n") in prompt
```
T6 `tests/test_location_story.py`, four Edits:
- `:113`: replace `    assert "background.@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE` with `    assert "background only when the narrative mentions one.@@LOCATION_FIXED@@\n" in se.PLAN_PROMPT_TEMPLATE`.
- `:122`: replace `    assert ("any crowd or other group of people in the background." + fixed + "\nprops: ") in prompt` with these two lines:
```python
    assert ("a crowd or other group of people in the background only when the narrative mentions "
            "one." + fixed + "\nprops: ") in prompt
```
- `:124`: replace `    assert ('background.' + se.LOCATION_FIXED_INTRO` with `    assert ('mentions one.' + se.LOCATION_FIXED_INTRO`.
- `:130`: replace `    assert "in the background.\nprops: " in plain` with `    assert "only when the narrative mentions one.\nprops: " in plain`.

Fixtures, by mechanical substitution. macOS `sed -i ''` keeps a missing final newline; these files have none.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cr-wt/qwen-agent-workspace
O='the ground, the light and any crowd or other group of people in the background.'
N='the ground and the light, and a crowd or other group of people in the background only when the narrative mentions one.'
for f in tests/fixtures/location/plan_prompt_chained.txt tests/fixtures/location/plan_prompt_chained_cast.txt tests/fixtures/location/plan_prompt_shots.txt tests/fixtures/pinned_cast/uncast_chained_lines.txt tests/fixtures/pinned_cast/uncast_chained_seed.txt tests/fixtures/pinned_cast/uncast_shots_lines.txt; do
  before=$(grep -c -F "$O" $f); bytes=$(wc -c < $f)
  LC_ALL=C sed -i '' 's/the ground, the light and any crowd or other group of people in the background\./the ground and the light, and a crowd or other group of people in the background only when the narrative mentions one./' $f
  echo "$f before=$before old=$(grep -c -F "$O" $f) new=$(grep -c -F "$N" $f) grew=$(( $(wc -c < $f) - bytes )) last=$(tail -c1 $f)"
done
git diff --numstat -- tests/fixtures
```
Expected: six lines, each `before=1 old=0 new=1 grew=39 last=.`, then six numstat lines `1	1	…`.

- [ ] **Step 5: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cr-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_no_default_crowd.py tests/test_pinned_cast.py tests/test_narrative_fidelity.py tests/test_location_story.py tests/test_dialogue.py tests/test_writer_pacing.py 2>&1 | tail -1   # all passed
grep -c "any crowd" story_engine.py; grep -c crowd story_engine.py                # 0, 6
git diff --numstat -- story_engine.py tests/*.py                                   # 4 6 story_engine.py; 1 1 test_dialogue; 5 4 test_location_story; 3 4 test_narrative_fidelity; 2 3 test_pinned_cast
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py tests/test_no_default_crowd.py tests/test_pinned_cast.py tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_location_story.py; done   # compiled 6, twice
zsh $S/cr-baseline/gate-run.sh 1
```
Expected gate output:
- the summary `3 failed, P0+4 passed, 2 skipped`
- `lost 1 (listed 1, unexpected 0); new tests 5, not passing 0; baseline failures still failing 2 of 2`
- `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`

The single loss is `test_mut26`.

- [ ] **Step 6: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cr-wt/qwen-agent-workspace
git add story_engine.py tests/test_no_default_crowd.py tests/test_pinned_cast.py tests/test_narrative_fidelity.py tests/test_dialogue.py tests/test_location_story.py tests/fixtures/location/plan_prompt_chained.txt tests/fixtures/location/plan_prompt_chained_cast.txt tests/fixtures/location/plan_prompt_shots.txt tests/fixtures/pinned_cast/uncast_chained_lines.txt tests/fixtures/pinned_cast/uncast_chained_seed.txt tests/fixtures/pinned_cast/uncast_shots_lines.txt
git diff --cached --name-only | wc -l    # 12
git commit -m "story_engine: a place names a crowd only when the narrative mentions one; speaking Image: sentences name no crowd (story-no-default-crowd NC1, NC2, NCT1-NCT5)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: the `test_mut26` re-baseline (a test-only commit; never amend)

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cr-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/qwen-agent story_engine.py bin/ltx-movie); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only b581e40 $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected:
- a 40-hex `SHA`
- `SHA is HEAD`
- exactly one path, `qwen-agent-workspace/story_engine.py`

The 23 paths are written out because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Type the 40 characters of `SHA` where the word SHA appears.
  - Replace `960b2b151d2af137ef8819ffc42df24f118a964f (shots-seed-edit), then to b9e1e3b0f7dae16992b0ee67e9a5c59ea82aaab0 (agent-no-tools).` (it occurs once, at the end of the comment line `:291`) with `960b2b151d2af137ef8819ffc42df24f118a964f (shots-seed-edit), then to b9e1e3b0f7dae16992b0ee67e9a5c59ea82aaab0 (agent-no-tools), then to SHA (story-no-default-crowd).`
  - Replace `    BASELINE = "b9e1e3b0f7dae16992b0ee67e9a5c59ea82aaab0"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cr-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                    # 1
grep -c "(agent-no-tools), then to $SHA (story-no-default-crowd)\.$" tests/test_movie_ui_builder.py  # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/cr-baseline/gate-run.sh 2
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the story-no-default-crowd commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output:
- the summary `2 failed, P0+5 passed, 2 skipped`
- `lost 0 (listed 0, unexpected 0); new tests 5, not passing 0; baseline failures still failing 2 of 2`
- `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`
- `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/cr-baseline/task-2-pytest.txt` prints `1`

### Verification (controller)

- **V1:** confirm NCK1-NCK3 from Task 2's gate output and these commands:
  - `git diff --numstat b581e40 HEAD -- story_engine.py`: `4 6`
  - `git diff --name-only b581e40 HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `13`
  - `git diff b581e40 HEAD -- bin/ | wc -l`: `0`
- **V2:** an Opus design review (the `design-reviewer` agent) of the two commits against this spec, using Section 7 as the focus. A finding is fixed in a new commit. If that commit touches `story_engine.py`, another Task 2-style baseline commit follows, and V1 runs again.
- **V3:** live checks L1 and L2 (Section 6). The user runs them; the agent never does.

## Open questions

None. The one risk that only a live run can show is whether the plan model follows the conditional "only when the narrative mentions one". L1 measures it, and Section 6 names the follow-up if it fails.
