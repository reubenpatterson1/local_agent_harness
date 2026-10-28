# Pinned Cast Presence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every library character the user pins with `--character` (or picks in movie-ui) is in at least one beat's cast of the Phase 1 plan. A plan that leaves one out is rejected by a new hard plan check, P16 "cast presence". The existing plan call retries it once, and the run exits 1 when the retry also fails. The planner is told the rule, by library name. In chained movies a pinned co-star stays in frame, silent, in another character's speaking beat, and the writer is told who is silent. Shots and no_stills coercion, speech attribution, old stories and uncast runs stay exactly as they are.

**Architecture:** All production code is in `story_engine.py`, stdlib only. The plan prompt gets four new constants: `CAST_FIXED_INTRO` and `CAST_FIXED_LINE` (PC3), `SEED_CAST_SENTENCE` (PC4), `SPEAKER_RULE_KEEP_CAST` (PC5) and `LINES_PINNED_SENTENCE` (PC6). Each is used only when the movie has members, so uncast plan prompts stay byte-identical. `plan_checks` gains P16 (PC1), and `_Run.go` adds `"P16"` to its fatal ids (PC2), which reuses the existing `plan_round` retry feedback and the existing fatal-plan error. `speaking_coercion` keeps pinned co-stars in chained mode only (PC7). `build_panel_prompt` appends `SILENT_CAST_MOTION_SENTENCE` or uses `SPEAKING_IMAGE_SILENT_SENTENCE` on chained speaking panels that have co-stars, through the new helper `_and_list` (PC8). N17 stops counting chained library co-stars (PC9). `bin/ltx-movie`, `bin/ltx-story-manifest`, `character_lib.py` and movie-ui are not touched.

**Tech Stack:** Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only; `tests/story_engine_testutil.py` (`set_story_env`, `make_ws`, `make_ctx`, `plan_json`, `panel_json`, `answer`, `script_agent`, `agent_log`, `kyra`, `ronin`, `make_character`, `DESC_K`, `DESC_R`) and the fake `bin/qwen-agent` it installs.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md` (Section 8.3 "Open: None"). It is committed at `246896b` on branch `pc-impl` of the git worktree `pc-wt`. Its line numbers cite `0c0160d`, and `246896b`'s code tree is `0c0160d`'s: the only difference is the spec file. Every Edit below finds its text by content. The spec is binding; this plan changes no design decision. The user approved the spec, including its 8.2 confirmations, as written: **C1** P16 exhaustion is fatal (exit 1); **C2** chained coercion keeps only library characters; **C3** shots coercion is unchanged; **C4** old stories are not re-checked for presence. Where the plan had to read the spec, the reading is listed in "Plan decisions".

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions."
- [0.4 Not changed] "`character_lib.py` (`insert_speech`, `speech_text`, `phrase_occurs`, `member_referenced`, `shots_violations`)."
- [0.4 Not changed] "`bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/judge-story`, `bin/iterate-story`, `movie_ui_lib.py`, `static/*`."
- [0.4 Not changed] "`pasted_pieces`, `panel_fields`, `assemble`, `recheck`, `RECHECK_IDS`, `GENERATION_CHECKS`, `NON_BLOCKING_IDS`, `REPAIR_IDS`."
- [0.4 Not changed] "Every check except P16 (new) and N17 (PC9). The critic and `apply_patches`."
- [0.4 Not changed] "`SPEAKER_RULE`, `LINES_RULE`, `SEED_PARAGRAPH`, `SPEAKING_IMAGE_SENTENCE` and `SPEAKING_CHAINED_MOTION_SENTENCE` keep their exact text. New constants are added beside them."
- [0.4 Not changed] "`--story-legacy` and `build_cast_block`."
- [0.5] Out of scope: "**Requiring a pinned member in beat 1** of a chained movie (C4)."; "**A hard post-writer presence check**"; "**Re-checking old stories for presence**"; "**Keeping invented (non-library) co-stars** in chained speaking beats (D3)."; "A pre-flight feasibility error for shots runs that cannot fit every pinned member (R4)."; "Two-character LoRA blending (R3; [ENS])."; "Lip-sync attribution in render, beyond the recorded live observation."; "The pre-existing duplicate-identity case".
- [0.7] "PC1-PC9 and the tests (Section 4) are must-haves. Nothing else is built: no new CLI flag, no new check besides P16, no change to the manifest, ltx-movie or movie-ui, and no deterministic repair of the plan."
- [0.6 PK2] "`/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`." (checked here with `compile()`, see the house rules)
- [0.6 PK3] "`story_engine.py` gains no import (`git diff` shows no `import` line change)."
- [0.6 PK6] "Uncast plan prompts are byte-identical to `0c0160d`."
- [0.6 PK7] "`test_dlg11` and `test_nf16` pass unedited."
- [0.6 PK9] "Re-check of an existing story whose `plan.json` has a pinned member in no beat gives the same rc and `story_checks.json` messages as at `0c0160d`."
- [4.1] "No test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API."
- [4.2] The fixtures are generated "**at `0c0160d`, before any edit to `story_engine.py`**".
- [0.4 G5] "`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit**".
- [6] PR note: "Phase 1 now refuses a plan that leaves out a `--character` (P16; retried once, then exit 1). In chained movies a library character stays in frame, silent, in another character's speaking beats. Existing stories re-check exactly as before; a story generated before this change that dropped a character must be regenerated with `--force-story` (movie-ui: Regenerate)."

Repository rules (the controller's; every task's requirements include them):

- This Mac only. Never access the macstudio host or any remote host (no ssh, scp, rsync, curl or HTTP), use no network, and never contact a local server or port (`:8177`, `:8178`). Never render or load a model. Never read `~/.zshenv` or `fleet.env`. Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`: every command runs in the worktree `pc-wt`. Offline pytest in the worktree is allowed.
- Standard library only in every Python file this plan touches. Every new or changed file must run on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers.
- Tests never render, never contact a model server, a daemon or the Anthropic API, and never use the real `HOME`. `tests/test_pinned_cast.py` uses the autouse `story_env` fixture (`seu.set_story_env`: a temporary HOME, character library and LoRA catalog) and builds every ctx and workspace under `tmp_path`.
- Run tests as `cd $WS && python3 -m pytest -q -p no:cacheprovider tests/<file>`. Every pytest run prints a `pytest_asyncio` deprecation warning first, which is expected.
- Never stage `../.DS_Store`, `../.claude/`, `.claude/`, `../agent/__pycache__/`, the repo-root `../bin/` or `bin/action-from-dir`. Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Never use `git stash`, `git reset` or `git checkout` of a path.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The commit commands below pass it as a second `-m`.
- Known pre-existing failures at `0c0160d` are ignored when they fail exactly as at the baseline. The controller's baseline run in `pc-wt` at `0c0160d`'s code tree gave `2 failed, 1839 passed, 2 skipped`, and `tests/test_ltx_movie_offline.py` printed `OK 347/347`. The two failures are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`, and `tests/test_story_engine.py::test_rst62_import_sets`, which fails on `bin/ltx-mlx-render` before it reaches `story_engine.py`. `tests/test_story_engine.py::test_rst48_judge_story_patches` **passes** at the baseline, so it is not a known failure, whatever spec 0.3 says (Spec defect 1). The regression gate expects exactly those two failures and `1839 + 24` passed. No other test may fail.
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` diffs `PIPELINE_FILES`, which includes `story_engine.py` (`tests/test_movie_ui_builder.py:216-221`), in the working tree against a pinned commit (`cf0a0e6`). It therefore fails from Task 1's first `story_engine.py` edit until Task 5 re-baselines it, in its own test-only commit. No task before Task 5 runs or edits it. Each task's Step 4 run names its files and does not include `tests/test_movie_ui_builder.py`.
- The legacy `--story-legacy` outputs stay byte-identical: no task touches the legacy templates or path (`test_rst40`, `test_rst41` and `tests/test_casting_regression.py` pass unchanged after every task).

House rules:

- `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` = `$S/pc-wt/qwen-agent-workspace`. The git root is `$S/pc-wt`, one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS` (`cd $WS` first; every bash block below assumes it).
- Every code block is copied exactly, byte for byte. A **Create** writes a new file whose whole content is the block, followed by one newline. An **Append** adds two empty lines after the file's current last line (which ends with one newline), then the block, then one newline. An **Edit** replaces one block of old text with the new text. The old text must occur exactly once in the file at that moment; if it does not, stop and report, and do not adapt it. A **Run this command** step runs its `bash` block from `WS`.
- The compile check in each task is this command, with the task's files as `FILES`. It uses `compile()` on the source text, not `py_compile`, which errors on macOS when pointed at `/dev/null`. The expected output is two lines, `compiled N` for 3.9 and then for 3.13:

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs follow from the spec and are the ones most likely to reach a real run first. No PT test exercises them. Each is pinned by a test in its owning task.

1. **A plan reply that is both short and missing a pinned member** (a model that drops beats also tends to drop characters). Expected: after two such replies the run exits 1, and the fatal stderr lists the P1 beat-count message, then the P16 message, in `plan_checks` order, with no panel call and no `story.md` or `plan.json`. Test: `test_review_focus_1_an_exhausted_plan_lists_every_fatal_problem` (Task 2).
2. **A beat cast that names a pinned member by phrase instead of id** (`["c1", "the ronin"]`; models do this when the narrative uses names). Expected: `plan_checks` hard holds the existing `beat 2: P2 structure: cast id 'the ronin' is not defined` and also P16 for c2, as its last hard message. A phrase is not an id, so the retry feedback names the real fix. Test: `test_review_focus_2_a_beat_cast_that_names_a_member_by_phrase` (Task 2).
3. **A chained speaking beat whose speaker is given by phrase, in another case, and whose co-star is listed twice** (`speaker "The Woman in Grey"`, cast `["c2", "c2", "c1"]`). Expected: the speaker resolves to c1, the cast becomes `["c2", "c1"]` (beat order, no repeats), and the note is the silent-co-star note. `plan_checks` hard is empty: no P2 "listed twice" and no P16. Before PC7 the same plan loses the ronin and fails P16. Test: `test_review_focus_3_a_speaker_named_by_phrase_and_a_repeated_co_star` (Task 3).
4. **A writer re-ask on a chained speaking panel with a co-star** (the code-only round re-asks the writer with a fix block). Expected: the re-ask prompt's motion key line equals the first ask's, the filled `SILENT_CAST_MOTION_SENTENCE` appears exactly once in each prompt, the fix block lists the problem and the previous Motion, and no `@@` token is left. Test: `test_review_focus_4_a_writer_re_ask_keeps_one_silent_sentence` (Task 4).
5. **Three pinned members in one chained speaking beat, with the speaker not listed first** (`MAX_CAST` chained is 4). Expected: the beat cast stays `["c2", "c1", "c3"]`, P16 is silent, the motion key line ends with `Also in frame in this panel, and silent: "the ronin" and "the archer".`, and the on-screen line lists all three phrases in beat order. Test: `test_review_focus_5_three_library_characters_in_one_speaking_panel` (Task 4).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `story_engine.py` | Modify (Tasks 1-4) | Task 1: `SEED_CAST_SENTENCE` (PC4), `SPEAKER_RULE_KEEP_CAST` (PC5), `LINES_PINNED_SENTENCE` (PC6), `CAST_FIXED_INTRO` and `CAST_FIXED_LINE` (PC3), and their use in `build_plan_prompt`. Task 2: P16 in `plan_checks` and its docstring (PC1); `"P16"` in `_Run.go`'s fatal ids (PC2). Task 3: `speaking_coercion` (PC7). Task 4: `SILENT_CAST_MOTION_SENTENCE` and `SPEAKING_IMAGE_SILENT_SENTENCE`, `_and_list` and the `build_panel_prompt` edits (PC8); N17's library set (PC9). |
| `tests/fixtures/pinned_cast/` | Create (Task 1) | `uncast_chained_lines.txt`, `uncast_shots_lines.txt` and `uncast_chained_seed.txt`: byte-exact `build_plan_prompt` outputs of the unchanged code (spec 4.2). |
| `tests/test_pinned_cast.py` | Create (Task 1), Append (Tasks 2-4) | PT1-PT18 and Review Focus 1-5. |
| `tests/test_story_engine.py` | Modify (Task 1) | The spec 4.3 A edit of `test_rst8_plan_prompt_matrix`. |
| `tests/test_movie_ui_builder.py` | Modify (Task 5 only) | `test_mut26` `BASELINE` and its comment (spec 4.3 A, G5). |

Task 1 is the planner contract (everything the plan model reads). Task 2 is the presence rule and its retry and exit. Task 3 is the chained coercion. Task 4 is the writer contract and N17. Task 5 is the review, the test-only re-baseline and the final measurements. A reviewer can accept or reject each task on its own diff. The suite stays green after every task except `test_mut26`, as stated above.

---

## Before Task 1: baseline record and snapshot (controller; no code, no commit)

PK1 compares against the pass count recorded here. Nothing is written into the repository.

- [ ] **Step 1: Confirm the starting point.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
WS=$S/pc-wt/qwen-agent-workspace
cd $WS
git branch --show-current                        # expected: pc-impl
git log -1 --format=%s                           # expected: docs(plan): pinned cast presence implementation plan
git rev-parse HEAD~1                             # expected: 246896be99bbb0ae6f2f460df59c91f3d8b1fc78 (the spec commit)
git diff --stat 0c0160d HEAD -- . ':(exclude)docs' | tail -1   # expected: no output (HEAD's code tree is 0c0160d's)
git status --short                               # expected: only ?? ../agent/__pycache__/
ls tests/test_pinned_cast.py tests/fixtures/pinned_cast 2>&1 | grep -c "No such file"   # expected: 2
wc -l < story_engine.py                          # expected: 3705
grep -c "P16" story_engine.py                    # expected: 0
ls generated 2>&1 | grep -c "No such file"       # expected: 1 (the worktree has no generated/ tree)
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule; spec 6 step 1).**

```bash
tar czf $S/snapshot-pre-pinned-cast-0c0160d.tgz --exclude qwen-agent-workspace/generated -C $S/pc-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-pinned-cast-0c0160d.tgz | grep -c '^qwen-agent-workspace/story_engine.py$'   # expected: 1
```

- [ ] **Step 3: Record the pytest and script baselines (about 12 minutes).**

The controller recorded this baseline in `$S/pc-baseline/baseline-pytest.txt`: `2 failed, 1839 passed, 2 skipped`, with `OK 347/347` from the offline script. Reuse it, and do not overwrite it:

```bash
D=$S/pc-baseline
tail -1 $D/baseline-pytest.txt                   # expected: the summary line with 2 failed, 1839 passed, 2 skipped
git -C $S/pc-wt rev-parse HEAD > $D/base-commit.txt
```

If that file is missing or its last line is not that summary, record it now (the same command):

```bash
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
```

Then, in both cases:

```bash
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1 | tee $D/baseline-offline.txt
```

Expected: exactly two `FAILED` lines, `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`; the summary `2 failed, 1839 passed, 2 skipped`; and `OK 347/347` from the offline script. `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` is timing-sensitive and unrelated to this plan. If it fails here, rerun it alone (`python3 -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py -k trt41a`) and record both results. Write any other difference into `$D/baseline-notes.txt`; Task 5 compares against what is recorded here.

---

### Task 1: The planner contract: the fixtures, the fixed-cast block, the seed carve-out and the rule variants (PC3, PC4, PC5, PC6)

Implements G3 (spec 4.2: the three uncast fixtures, generated before any `story_engine.py` edit), PC3, PC4, PC5 and PC6, and the spec 4.3 A edit of `test_rst8_plan_prompt_matrix`. Tests: PT1 (the plan constants and the five unchanged literals, as `test_pt1_plan_constants`; Plan decision 2), PT2, PT3, PT4 and PT5. Creates `tests/test_pinned_cast.py`, which Tasks 2-4 append to. This is the first pipeline commit: `test_mut26` fails from here until Task 5.

**Files:**
- Create: `tests/fixtures/pinned_cast/uncast_chained_lines.txt`, `tests/fixtures/pinned_cast/uncast_shots_lines.txt`, `tests/fixtures/pinned_cast/uncast_chained_seed.txt`
- Create: `tests/test_pinned_cast.py`
- Modify: `story_engine.py` (after `SEED_PARAGRAPH` `:333-337`; after `SILENT_SPEAKER_RULE` `:355`; after `LINES_RULE` `:357-363`; before `def build_plan_prompt` `:734`; the fixed-cast block `:743-749`; the fragments `:761-773`)
- Modify: `tests/test_story_engine.py` (`test_rst8_plan_prompt_matrix` `:246-248`)

**Interfaces:**
- Consumes (existing): `story_engine.build_plan_prompt(ctx, compatible, pins) -> str`, `SEED_PARAGRAPH`, `SPEAKER_RULE`, `SILENT_SPEAKER_RULE`, `LINES_RULE`, `SPEAKING_IMAGE_SENTENCE`, `SPEAKING_CHAINED_MOTION_SENTENCE`, `engine_seconds(ctx)`, `StoryContext` (`members`, `mode`, `narration`, `seed_agent_image`); `character_lib.resolve_cast(entries) -> [CastMember]` (`CastMember.name`, `.phrase`, `.descriptor`), `dialogue_word_cap(seconds, fragments=1)`; `story_engine_testutil.set_story_env`, `make_ws`, `make_ctx(se, ws, **overrides)`, `plan_json(mode, n, cast=None, **overrides)`, `kyra(lib)`, `ronin(lib)`, `DESC_K`, `DESC_R`; `bin/ltx-movie` loaded by path.
- Produces: in `story_engine`, the strings `SEED_CAST_SENTENCE`, `SPEAKER_RULE_KEEP_CAST`, `LINES_PINNED_SENTENCE`, `CAST_FIXED_INTRO` and `CAST_FIXED_LINE` (a `%` format of `(int, str, str, str)`). `build_plan_prompt` uses them only when `ctx.members` is non-empty. In `tests/test_pinned_cast.py`: the module header (`WS`, `FIX`, `seu`, `lib`, `se`, `ltx_movie`, with `copy`, `json` and `re` imported), the fixtures `story_env` (autouse), `ws` and `movie`, the constants `KYRA`, `RONIN`, `CAST2`, `LINES_NARRATIVE` and `NARRATIVE`, and the helpers `_members(story_env) -> [CastMember]`, `_raw(mode, n, casts, speakers=None) -> dict`, `P16(cid, phrase, name, mode, narration) -> str` and `_prompt(ws, **kw) -> str`.

- [ ] **Step 1: Generate the fixtures, write the failing tests and the spec 4.3 A edit.**

New tests in this task: `test_pt1_plan_constants`, `test_pt2_fixed_cast_block_and_uncast_byte_identity`, `test_pt3_seed_carve_out`, `test_pt4_speaker_rule_variants`, `test_pt5_lines_sentence_variants`.

**1.1.** Run this command (from WS). It is the spec 4.2 script, run before any edit to `story_engine.py`, under a temporary HOME, character library and LoRA catalog (Plan decision 3):

```bash
T=$(mktemp -d $S/pc-fixture-env.XXXXXX)
mkdir -p $T/home $T/characters $T/loras
HOME=$T/home CHARACTER_LIBRARY_DIR=$T/characters LORA_CATALOG_DIR=$T/loras python3 - <<'EOF'
import importlib.machinery, os, sys, tempfile
WS = os.getcwd(); sys.path.insert(0, os.path.join(WS, "tests"))
import story_engine_testutil as seu
se = importlib.machinery.SourceFileLoader("se_fix", os.path.join(WS, "story_engine.py")).load_module()
ws = seu.make_ws(tempfile.mkdtemp())
LINES = ('At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks one step '
         'behind her. Near the top Kyra turns and says, "We reach the gate before dark." They pass '
         'under the gate together, and Kyra says, "Stay close to me."')
cases = {"uncast_chained_lines.txt": dict(mode="chained", narration="speech", narrative=LINES),
         "uncast_shots_lines.txt": dict(mode="shots", panels=4, narration="speech", narrative=LINES),
         "uncast_chained_seed.txt": dict(mode="chained", seed_agent_image="/s/seed.png")}
out = os.path.join(WS, "tests", "fixtures", "pinned_cast")
os.makedirs(out, exist_ok=True)
for name, kw in cases.items():
    ctx = seu.make_ctx(se, ws, **kw)
    with open(os.path.join(out, name), "w", encoding="utf-8") as f:
        f.write(se.build_plan_prompt(ctx, [], []))
EOF
git diff --quiet -- story_engine.py && echo "story_engine.py unedited"
(cd tests/fixtures/pinned_cast && shasum -a 256 uncast_chained_lines.txt uncast_shots_lines.txt uncast_chained_seed.txt)
```

Expected output, exactly (any other hash: stop and report):

```text
story_engine.py unedited
86f841d0e814170d85f115a50dce358b1f3227a4b641fb4f60b69139a93b20ad  uncast_chained_lines.txt
f212449440858e1111527e811e48fb9298f881c63d3f8432807c4d26e4f99fa3  uncast_shots_lines.txt
d5b4570f2ce345b0566adafc2549e146e0a82f0ff10a45d9a960e52a91ffbfd4  uncast_chained_seed.txt
```

**1.2.** Create `tests/test_pinned_cast.py`:

```python
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
```

**1.3.** Edit `tests/test_story_engine.py` (spec 4.3 A, `test_rst8`): replace this text, which occurs exactly once:

```python
                        assert ('\n- id c1, phrase "the woman in grey", descriptor "%s"'
                                % seu.DESC_K) in prompt
                        assert '\n- id c2, phrase "the ronin", descriptor "%s"' % seu.DESC_R in prompt
```

with:

```python
                        assert ('\n- id c1, name "kyra", phrase "the woman in grey", '
                                'descriptor "%s"' % seu.DESC_K) in prompt
                        assert ('\n- id c2, name "ronin", phrase "the ronin", descriptor "%s"'
                                % seu.DESC_R) in prompt
```

Nothing else in `test_rst8` changes.

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py::test_rst8_plan_prompt_matrix 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `6 failed`. PT1 and PT2 fail with `AttributeError: module 'story_engine_for_pinned' has no attribute 'CAST_FIXED_INTRO'` (PT2 after its three fixture comparisons pass), PT3 with `... has no attribute 'SEED_CAST_SENTENCE'`, PT4 with `... has no attribute 'SPEAKER_RULE_KEEP_CAST'`, PT5 with `... has no attribute 'LINES_PINNED_SENTENCE'`, and `test_rst8_plan_prompt_matrix` with an `AssertionError` on the new `name "kyra"` line.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (PC4, the constant): replace this text, which occurs exactly once:

```python
                  "scene it shows.\n\n")
MODE_RULES = {
```

with:

```python
                  "scene it shows.\n\n")
# Pinned cast presence spec PC4, D4: a declared character the seed image does not show is not
# an invention.
SEED_CAST_SENTENCE = (" The already-cast characters listed below are not invented: each of them "
                      "is in this movie even when the image does not show them.")
MODE_RULES = {
```

**3.2.** Edit `story_engine.py` (PC5, the constant): replace this text, which occurs exactly once:

```python
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
```

with:

```python
SILENT_SPEAKER_RULE = " speaker is always an empty string: nobody speaks in this movie."
# Pinned cast presence spec PC5, D3: in chained mode a declared character still in frame stays
# in a speaking beat, silent.
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, and the camera may stay static, push in, pull back or track them, "
    "as long as their face stays in frame and lit while they speak.")
```

**3.3.** Edit `story_engine.py` (PC6, the constant): replace this text, which occurs exactly once:

```python
              "least as many beats as lines.")
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

with:

```python
              "least as many beats as lines.")
# Pinned cast presence spec PC6, D3: where a speaking beat shows only the speaker, a declared
# character with no line needs a beat without a speaker.
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker, even when two consecutive lines must then share a beat.")
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
```

**3.4.** Edit `story_engine.py` (PC3, the constants): replace this text, which occurs exactly once:

```python
def build_plan_prompt(ctx, compatible, pins):
```

with:

```python
# Pinned cast presence spec PC3, D2: the declared characters, by library name, all on screen.
CAST_FIXED_INTRO = (" The following characters are already cast; list them first in cast with "
                    "exactly these ids, phrases and descriptors, and give your own characters "
                    "the next ids. Every one of them is in this movie: put each one's id in the "
                    "cast of at least one beat. When the narrative calls one of them by their "
                    "name, it means that character, whom the movie names only by their phrase:")
CAST_FIXED_LINE = '\n- id c%d, name "%s", phrase "%s", descriptor "%s"'


def build_plan_prompt(ctx, compatible, pins):
```

**3.5.** Edit `story_engine.py` (PC3, the fixed-cast block): replace this text, which occurs exactly once:

```python
    if ctx.members:
        cast_fixed += (" The following characters are already cast; list them first in cast with "
                      "exactly these ids, phrases and descriptors, and give your own characters "
                      "the next ids:")
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += '\n- id c%d, phrase "%s", descriptor "%s"' % (
                i, member.phrase, member.descriptor)
```

with:

```python
    if ctx.members:
        cast_fixed += CAST_FIXED_INTRO
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += CAST_FIXED_LINE % (i, member.name, member.phrase, member.descriptor)
```

**3.6.** Edit `story_engine.py` (PC4, the seed fragment): replace this text, which occurs exactly once:

```python
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@SEED_PARAGRAPH@@", SEED_PARAGRAPH if ctx.seed_agent_image else ""),
```

with:

```python
    seed = ""
    if ctx.seed_agent_image:
        seed = (SEED_PARAGRAPH[:-2] + SEED_CAST_SENTENCE + "\n\n" if ctx.members
                else SEED_PARAGRAPH)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@SEED_PARAGRAPH@@", seed),
```

**3.7.** Edit `story_engine.py` (PC5 and PC6, the rule fragments): replace this text, which occurs exactly once:

```python
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False else SPEAKER_RULE),
        ("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker"),
        ("@@LINES_RULE@@", LINES_RULE if lines else ""),
```

with:

```python
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False
         else SPEAKER_RULE_KEEP_CAST if ctx.mode == "chained" and ctx.members else SPEAKER_RULE),
        ("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker"),
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else ""))
         if lines else ""),
```

Nothing else in `build_plan_prompt` changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 454 passed, 1 skipped`. Spec 4.3 B passes unchanged in this run (`test_rst10`, `test_rst11`, `test_rst13`, `test_rst40`, `test_rst41`, `test_rst51`-`test_rst54`, `test_rst61`, DLG11, DLG13, NF13, NF16, NF17, every `test_writer_pacing.py` test). Then the compile check with `FILES` = `story_engine.py tests/test_pinned_cast.py tests/test_story_engine.py`; expected `compiled 3` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_pinned_cast.py tests/fixtures/pinned_cast tests/test_story_engine.py
git diff --cached --name-only    # expected: exactly these 6 paths, each with the qwen-agent-workspace/ prefix: story_engine.py, tests/fixtures/pinned_cast/uncast_chained_lines.txt, tests/fixtures/pinned_cast/uncast_chained_seed.txt, tests/fixtures/pinned_cast/uncast_shots_lines.txt, tests/test_pinned_cast.py, tests/test_story_engine.py
git commit -m "feat(story): tell the planner every --character is in the movie, by library name (PC3-PC6, PT1-PT5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: P16 cast presence, retried by the plan call and fatal when the retries run out (PC1, PC2)

Implements PC1 (the P16 block and the `plan_checks` docstring) and PC2 (`"P16"` in the fatal ids of `_Run.go`). Tests: PT6, PT7, PT14, PT15, PT18, Review Focus 1 and 2.

**Files:**
- Modify: `story_engine.py` (the `plan_checks` docstring `:1314-1317`; before `undeclared = undeclared_characters(ctx)` `:1451`; the fatal filter `:3407`)
- Modify: `tests/test_pinned_cast.py` (append)

**Interfaces:**
- Consumes: Task 1's test header, `_members`, `_raw`, `P16`, `KYRA`, `RONIN`, `NARRATIVE`, the `movie` fixture and `se.SEED_CAST_SENTENCE`; existing `story_engine.normalize_plan(ctx, raw) -> (plan, shape)`, `plan_checks(ctx, plan, shape=()) -> (hard, advisory)`, `parse_violation(text) -> dict`, `run(ctx, no_stills_rules="") -> (rc, advisories)`; `ltx_movie.main(argv) -> rc`; `seu.script_agent(monkeypatch, tmp_path, plan=(), panel=None, critic=()) -> log path`, `seu.agent_log(path)`, `seu.answer(obj)`, `seu.panel_json(mode, k, phrase)`.
- Produces: `plan_checks` hard gains one `plan: P16 cast presence: ...` message per pinned member in no beat's cast, in `plan["cast"]` order, after every existing hard message. `_Run.go` treats P16 as fatal (exit 1, the existing three-part stderr). In the test module: `_panel_script(n, phrase=KYRA) -> {"<k>": [reply]}` and `_read_json(story_dir, name)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_pt6_p16_matrix`, `test_pt7_p16_scope`, `test_pt14_e2e_retry`, `test_pt15_e2e_exhausted`, `test_pt18_seed_and_two_pinned_retried`, `test_review_focus_1_an_exhausted_plan_lists_every_fatal_problem`, `test_review_focus_2_a_beat_cast_that_names_a_member_by_phrase`.

**1.1.** Append to `tests/test_pinned_cast.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `7 failed, 5 passed`. PT6 and PT7 fail with an `AssertionError` (`[] == [...]`: no P16 message yet). PT14, PT15 and PT18 fail with an `AssertionError` on the stage list or the plan-call count: the first reply is accepted, so there is one plan call and the run goes on to the panels. Review Focus 1 fails on the stderr: the run already exits 1 on P1, but the P16 line is missing. Review Focus 2 with an `AssertionError` on `hard[-1]` (the P2 message is there, the P16 is not). Task 1's five tests pass.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (PC1, the docstring): replace this text, which occurs exactly once:

```python
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2 and P3's
    normalize and duplicate-phrase messages; every other P message is advisory (dialogue spec
    6.3)."""
```

with:

```python
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first. Hard: P1, P2, P3's normalize
    and duplicate-phrase messages, and P16 (a library character in no beat's cast; pinned cast
    presence spec PC1); every other P message is advisory (dialogue spec 6.3)."""
```

**3.2.** Edit `story_engine.py` (PC1, the check): replace this text, which occurs exactly once:

```python
                                    "their look is left to the video model" % (k, c))
    undeclared = undeclared_characters(ctx)
```

with:

```python
                                    "their look is left to the video model" % (k, c))
    # Pinned cast presence spec PC1, D1: every library character is in some beat's cast.
    on_screen = set(c for beat in beats for c in beat["cast"])
    for entry in plan["cast"]:
        if entry.get("cast_name") and entry["id"] not in on_screen:
            message = ("plan: P16 cast presence: %s %s (library character %s) is in no beat's "
                       "cast; every already-cast character must be on screen, so put %s in the "
                       "cast of at least one beat"
                       % (entry["id"], _q(entry["phrase"]), entry["cast_name"], entry["id"]))
            if ctx.mode != "chained" and ctx.narration is not False:
                message += ("; a beat with a speaker shows only the speaker, so that beat has no "
                            "speaker or %s is its speaker" % entry["id"])
            hard.append(message)
    undeclared = undeclared_characters(ctx)
```

**3.3.** Edit `story_engine.py` (PC2): replace this text, which occurs exactly once:

```python
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2")]
```

with:

```python
        # Pinned cast presence spec PC2: a plan that drops a library character is not usable.
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2", "P16")]
```

Nothing else in `plan_checks` or `go()` changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 461 passed, 1 skipped` (Task 1's count plus 7). `test_rst10` and `test_rst11` (the existing fatal-plan stderr), `test_rst13`, `test_rst53` (shots, two characters, both on screen) and `test_casting_pipeline.py` pass unchanged. Then the compile check with `FILES` = `story_engine.py tests/test_pinned_cast.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_pinned_cast.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_pinned_cast.py
git commit -m "feat(story): a plan that leaves out a --character is retried, then fatal (P16 cast presence; PC1, PC2, PT6, PT7, PT14, PT15, PT18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Chained speaking beats keep their library co-stars, silent (PC7)

Implements PC7 (`speaking_coercion` replaced). Tests: PT8, PT9, PT10 and Review Focus 3. `test_dlg11` and `test_nf16` pass unedited (PC7 equivalence: with no pinned member, or outside chained mode, every branch is byte-identical).

**Files:**
- Modify: `story_engine.py` (`speaking_coercion` `:1110-1133`)
- Modify: `tests/test_pinned_cast.py` (append)

**Interfaces:**
- Consumes: Task 1's header and helpers; Task 2's `P16` hard message; existing `normalize_plan` (which calls `coerce_speakers`, which calls `speaking_coercion` for each beat that keeps a speaker), `SPEAKING_SHOTS`, `SPEAKING_CAMERAS`, `_q`.
- Produces: `speaking_coercion(ctx, plan, k) -> [note]`, same signature. In chained mode a speaking beat's cast is the speaker plus every library character the beat lists (beat order, no repeats; the speaker first when it was not listed), with the new note `"beat %d: P14 speaking beat: cast [%s] changed to [%s]: the speaker, and the library character(s) %s, who stay in frame without speaking"`. A chained k=1 shot outside `SPEAKING_SHOTS` becomes `"medium shot"` when silent co-stars share the beat.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_pt8_chained_coercion_keeps_library_co_stars`, `test_pt9_shots_coercion_is_unchanged_with_members`, `test_pt10_chained_k1_shot_with_co_stars`, `test_review_focus_3_a_speaker_named_by_phrase_and_a_repeated_co_star`.

**1.1.** Append to `tests/test_pinned_cast.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `3 failed, 13 passed`. PT8 fails with an `AssertionError` on the first case's cast (`['c1'] == ['c1', 'c2']`), PT10 on the first shot (`'medium close-up' == 'medium shot'`), and Review Focus 3 on `(beat["speaker"], beat["cast"])` (`('c1', ['c1'])`). PT9 passes already: it pins the shots coercion this task must leave exactly as it is. Tasks 1 and 2's twelve tests pass.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (PC7): replace this text, which occurs exactly once:

```python
def speaking_coercion(ctx, plan, k):
    """The P14 notes of SP2 step 4 for beat k, whose speaker is already set (narrative dialogue
    fidelity spec QL7, SM2): the speaker is alone in the beat's cast, and when the beat frames
    its own shot (not a chained continuation, k >= 2) a shot wider than a medium shot becomes a
    medium close-up (an extreme close-up a close-up), and a camera that does not stay static,
    push in, pull back or track becomes static. Tracking is never coerced away."""
    notes = []
    beat = plan["beats"][k - 1]
    speaker = beat["speaker"]
    if beat["cast"] != [speaker]:
        notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker is "
                     "alone on screen" % (k, ", ".join(beat["cast"]), speaker))
        beat["cast"] = [speaker]
    if ctx.mode != "chained" or k == 1:
        if beat["shot"] not in SPEAKING_SHOTS:
            shot = "close-up" if beat["shot"] == "extreme close-up" else "medium close-up"
            notes.append("beat %d: P14 speaking beat: shot %s changed to %s so the speaker's "
                         "face stays readable" % (k, _q(beat["shot"]), _q(shot)))
            beat["shot"] = shot
```

with:

```python
def speaking_coercion(ctx, plan, k):
    """The P14 notes of SP2 step 4 for beat k, whose speaker is already set (narrative dialogue
    fidelity spec QL7, SM2; pinned cast presence spec PC7, D3): the beat's cast becomes the
    speaker plus, in chained mode only, every library character (cast_name set) the beat already
    lists, in the beat's order without repeats, who stays in frame silent; everyone else is
    removed. When the beat frames its own shot (not a chained continuation, k >= 2) a shot wider
    than a medium shot becomes a medium close-up (an extreme close-up a close-up), or a medium
    shot when silent library characters share the beat, and a camera that does not stay static,
    push in, pull back or track becomes static. Tracking is never coerced away."""
    notes = []
    beat = plan["beats"][k - 1]
    speaker = beat["speaker"]
    pinned = (set(c["id"] for c in plan["cast"] if c.get("cast_name"))
              if ctx.mode == "chained" else set())
    cast = []
    for cid in beat["cast"]:
        if (cid == speaker or cid in pinned) and cid not in cast:
            cast.append(cid)
    if speaker not in cast:
        cast.insert(0, speaker)
    silent = [cid for cid in cast if cid != speaker]
    if beat["cast"] != cast:
        if silent:
            notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s]: the speaker, "
                         "and the library character(s) %s, who stay in frame without speaking"
                         % (k, ", ".join(beat["cast"]), ", ".join(cast), ", ".join(silent)))
        else:
            notes.append("beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker "
                         "is alone on screen" % (k, ", ".join(beat["cast"]), speaker))
        beat["cast"] = cast
    if ctx.mode != "chained" or k == 1:
        if beat["shot"] not in SPEAKING_SHOTS:
            shot = ("medium shot" if silent else
                    "close-up" if beat["shot"] == "extreme close-up" else "medium close-up")
            notes.append("beat %d: P14 speaking beat: shot %s changed to %s so the speaker's "
                         "face stays readable" % (k, _q(beat["shot"]), _q(shot)))
            beat["shot"] = shot
```

The camera branch and `return notes` after this text are unchanged: they are already the spec's text.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 465 passed, 1 skipped` (Task 2's count plus 4). `test_dlg11_speaking_beat_coercion`, `test_nf13`, `test_nf16` and `test_nf17` pass unedited (PK7). Then the compile check with `FILES` = `story_engine.py tests/test_pinned_cast.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_pinned_cast.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_pinned_cast.py
git commit -m "feat(story): a chained speaking beat keeps its library co-stars in frame, silent (PC7, PT8-PT10)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The writer is told who is silent, and N17 does not count chained library co-stars (PC8, PC9)

Implements PC8 (`SILENT_CAST_MOTION_SENTENCE`, `SPEAKING_IMAGE_SILENT_SENTENCE`, `_and_list` and the three `build_panel_prompt` edits) and PC9 (N17's library set). Tests: PT1's writer half (`test_pt1_writer_constants_and_and_list`; Plan decision 2), PT11, PT12, PT13, PT16 (the reported case, end to end), PT17 (back-compat re-check), Review Focus 4 and 5.

**Files:**
- Modify: `story_engine.py` (after `SPEAKING_CHAINED_MOTION_SENTENCE` `:1769-1780`; before `def build_panel_prompt` `:2435`; `build_panel_prompt` `:2459`, `:2479-2481`, `:2484-2486`; N17 `:2264`)
- Modify: `tests/test_pinned_cast.py` (append)

**Interfaces:**
- Consumes: Tasks 1-3 (the header, `_members`, `_raw`, `_read_json`, `LINES_NARRATIVE`, P16 and PC7); existing `build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules="") -> str`, `empty_parts(mode, k, plan, ctx=None)`, `SPEECH_FRAMING_SENTENCE`, `SPEAKING_CHAINED_MOTION_SENTENCE`, `_field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared) -> (hard, advisory)`, `recheck(ctx, legacy_validate) -> (rc, advisories)`, `run(ctx)`; `character_lib.speech_text(phrase, line, delivery)`, `insert_speech(text, sentence, phrases=(), first_action=False)`, `make_character` (testutil).
- Produces: in `story_engine`, the strings `SILENT_CAST_MOTION_SENTENCE` and `SPEAKING_IMAGE_SILENT_SENTENCE` (tokens `@@SPEAKER@@`, `@@SILENT@@`) and `_and_list(items) -> str`. `build_panel_prompt` fills `@@SILENT@@` with the `_and_list` of a chained speaking beat's co-star phrases. N17's "a speaking shot shows only the speaker" advisory ignores library phrases in chained mode.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_pt1_writer_constants_and_and_list`, `test_pt11_writer_prompt`, `test_pt12_n17`, `test_pt13_speech_stays_with_the_speaker`, `test_pt16_two_pinned_chained_every_line_spoken_by_c1`, `test_pt17_back_compat_recheck`, `test_review_focus_4_a_writer_re_ask_keeps_one_silent_sentence`, `test_review_focus_5_three_library_characters_in_one_speaking_panel`.

**1.1.** Append to `tests/test_pinned_cast.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: `6 failed, 18 passed`. `test_pt1_writer_constants_and_and_list` and Review Focus 4 and 5 fail with `AttributeError: module 'story_engine_for_pinned' has no attribute 'SILENT_CAST_MOTION_SENTENCE'`, and PT11 with `... has no attribute 'SPEAKING_IMAGE_SILENT_SENTENCE'`; PT12 with an `AssertionError` (the chained N17 advisory "a speaking shot shows only the speaker" is still there); PT16 with an `AssertionError` on the advisory list (the same N17 message, on panels 2 and 3). PT13 and PT17 pass already: PT13 pins `character_lib`'s unchanged placement, and PT17 pins the unchanged `recheck`. Tasks 1-3's sixteen tests pass.

- [ ] **Step 3: Implement.**

**3.1.** Edit `story_engine.py` (PC8, the constants; the spec's comment line is wrapped at 100 columns, Plan decision 4): replace this text, which occurs exactly once:

```python
    "a speaking verb; the pipeline adds them.")
SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline "
```

with:

```python
    "a speaking verb; the pipeline adds them.")
# Pinned cast presence spec PC8, D3: a chained speaking panel's silent library co-stars
# (@@SILENT@@ is their quoted phrases).
SILENT_CAST_MOTION_SENTENCE = (" Also in frame in this panel, and silent: @@SILENT@@. Only "
                               "@@SPEAKER@@ speaks: mention each of the others by their referring "
                               "phrase, word for word, only inside the sentences that begin with "
                               "@@SPEAKER@@, and never give them a speaking verb.")
SPEAKING_IMAGE_SILENT_SENTENCE = (" @@SPEAKER@@ is in the foreground, facing the camera; also in "
                                  "frame, and silent: @@SILENT@@; any crowd stays in the "
                                  "background.")
SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline "
```

**3.2.** Edit `story_engine.py` (PC8, the helper): replace this text, which occurs exactly once:

```python
def build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules=""):
```

with:

```python
def _and_list(items):
    """'"a"', '"a" and "b"' or '"a", "b" and "c"' (pinned cast presence spec PC8); items is
    non-empty."""
    quoted = ['"%s"' % item for item in items]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


def build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules=""):
```

**3.3.** Edit `story_engine.py` (PC8, the co-star phrases): replace this text, which occurs exactly once:

```python
    phrase = speaker_phrase(plan, k) if speaks else None
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
```

with:

```python
    phrase = speaker_phrase(plan, k) if speaks else None
    silent = ([by_cast[c]["phrase"] for c in beat["cast"] if c != beat["speaker"] and c in by_cast]
              if speaks and ctx.mode == "chained" else [])
    words = str(_character_lib(ctx.ws).dialogue_word_cap(engine_seconds(ctx), 1)) if speaks else ""
```

**3.4.** Edit `story_engine.py` (PC8, the speaking sentences): replace this text, which occurs exactly once:

```python
        if speaks:
            line += (SPEAKING_CHAINED_MOTION_SENTENCE if ctx.mode == "chained" and key == "motion"
                     else SPEAKING_SENTENCES.get(key, ""))
```

with:

```python
        if speaks:
            if ctx.mode == "chained" and key == "motion":
                line += SPEAKING_CHAINED_MOTION_SENTENCE + (SILENT_CAST_MOTION_SENTENCE
                                                            if silent else "")
            elif ctx.mode == "chained" and key == "image" and silent:
                line += SPEAKING_IMAGE_SILENT_SENTENCE
            else:
                line += SPEAKING_SENTENCES.get(key, "")
```

**3.5.** Edit `story_engine.py` (PC8, the token replace): replace this text, which occurs exactly once:

```python
            line = (line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
                    .replace("@@LINE@@", '"%s"' % assigned))
```

with:

```python
            line = (line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
                    .replace("@@LINE@@", '"%s"' % assigned)
                    .replace("@@SILENT@@", _and_list(silent) if silent else ""))
```

**3.6.** Edit `story_engine.py` (PC9): replace this text, which occurs exactly once:

```python
            others = [p for p in on_screen if p.lower() != speaker.lower()]
```

with:

```python
            library = (set(c["phrase"].lower() for c in plan["cast"] if c.get("cast_name"))
                       if ctx.mode == "chained" else set())
            others = [p for p in on_screen if p.lower() != speaker.lower()
                      and p.lower() not in library]
```

Nothing else in `build_panel_prompt` or `_field_checks` changes.

- [ ] **Step 4: Run the tests and confirm they pass; compile on both interpreters.**

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_pinned_cast.py tests/test_story_engine.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_writer_pacing.py tests/test_shots_mode.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_iterate_story.py tests/test_ltx_story_manifest_chain.py tests/test_character_lib.py 2>&1 | grep -E '^FAILED|passed|failed'
```

Expected: one `FAILED` line, `tests/test_story_engine.py::test_rst62_import_sets` (the known failure), then `1 failed, 473 passed, 1 skipped` (Task 3's count plus 8). `test_dlg13_writer_keys_and_speaking_key_lines`, `test_n16_n17_n18_dialogue_messages`, DLG15-DLG24, NF28-NF35 and every `test_writer_pacing.py` test pass unedited (spec 4.3 B). Then the compile check with `FILES` = `story_engine.py tests/test_pinned_cast.py`; expected `compiled 2` twice.

- [ ] **Step 5: Commit.**

```bash
git add story_engine.py tests/test_pinned_cast.py
git diff --cached --name-only    # expected: qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_pinned_cast.py
git commit -m "feat(story): the chained writer is told which library co-stars stay silent, and N17 lets them share the shot (PC8, PC9, PT11-PT13, PT16, PT17)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Design review, the test_mut26 re-baseline (test-only commit), PK1-PK9 and the PK10 hand-off

Implements spec 6 steps 4-6 (G5) and measures PK1, PK2, PK3 and the unchanged files. It hands PK10 (the live runs, spec 5 and 6 step 7) and the PR note to the controller (see "Post-implementation: live checks"). No production code changes in this task.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26_pipeline_files_are_unchanged` `:283-285`: spec 4.3 A, "`BASELINE` becomes the feature commit's SHA. The comment's last item, `..., then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing).`, becomes `..., then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to <sha> (pinned cast presence).`")

**Interfaces:**
- Consumes: the commits of Tasks 1-4.
- Produces: the final pass counts in `$S/pc-baseline/final-pytest.txt`.

- [ ] **Step 1: Design review (controller; spec 6 step 5).** Ask an Opus `design-reviewer` to review `git diff 246896b..HEAD -- qwen-agent-workspace` against the spec and this plan. Fix every finding in a new commit on the owning task's files before Step 2, then re-run that task's Step 4.

- [ ] **Step 2: Re-baseline test_mut26 to the last pipeline commit.**

```bash
SHA=$(git log -1 --format=%H -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py)
echo "$SHA"
python3 - "$SHA" <<'EOF'
import sys
sha = sys.argv[1]
path = "tests/test_movie_ui_builder.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
old_comment = ("(writer pacing).\n"
               "    # This invariant holds from the new baseline.\n")
new_comment = ("(writer pacing), then to %s (pinned cast presence).\n"
               "    # This invariant holds from the new baseline.\n" % sha)
old_base = '    BASELINE = "cf0a0e684ea4f9ca09f7e7d45dc0e33544242971"\n'
assert text.count(old_comment) == 1 and text.count(old_base) == 1
text = text.replace(old_comment, new_comment).replace(old_base, '    BASELINE = "%s"\n' % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("re-based to", sha)
EOF
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected: the SHA is Task 4's commit, the last one that touched a `PIPELINE_FILES` entry (`story_engine.py`), or the Step 1 fix commit if that touched one; then `re-based to <that SHA>`; then `1 passed, 11 deselected`.

- [ ] **Step 3: Commit (test-only; spec 0.4 G5).**

```bash
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: only qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "test(movie-ui): re-baseline mut26 to the pinned cast presence pipeline commit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: PK1, the full suite against the baseline (about 12 minutes).**

```bash
D=$S/pc-baseline
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sed 's/ - .*//' | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sed 's/ - .*//' | sort) && echo "same failures"
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failure messages"
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1; cat $D/baseline-offline.txt
diff <(grep -E '^PASSED' $D/baseline-pytest.txt | sort) <(grep -E '^PASSED' $D/final-pytest.txt | sort) | grep '^<' || echo "no lost pass"
grep -c '^PASSED tests/test_pinned_cast.py::' $D/final-pytest.txt
```

Expected: the final summary is `2 failed, 1863 passed, 2 skipped` (the baseline's `2 failed, 1839 passed, 2 skipped` plus the 24 new tests). `same failures` and `same failure messages` print (exactly `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`, unchanged in number and message; PK1). The passed count is the baseline's plus 24, the functions of `tests/test_pinned_cast.py` (PT1 as two functions, PT2-PT18, Review Focus 1-5), plus 1 if `test_trt41a` failed in the baseline run only (if it fails here instead, rerun it alone). The skipped count is unchanged. The offline script prints `OK 347/347`, the same as `baseline-offline.txt`. The diff prints `no lost pass`, and the last command prints `24`. Any other difference: stop and report.

- [ ] **Step 5: PK2, PK3 and the unchanged files.**

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py tests/test_pinned_cast.py tests/test_story_engine.py tests/test_movie_ui_builder.py; done
git diff 0c0160d -- story_engine.py | grep -E '^[+-]\s*(import|from) ' || echo "no import change"
git diff --name-only 0c0160d -- character_lib.py bin/ltx-movie bin/ltx-story-manifest bin/judge-story bin/iterate-story movie_ui_lib.py static | wc -l
git diff --name-only 0c0160d -- . ':(exclude)docs' | sed 's#^qwen-agent-workspace/##' | grep -v -E '^(story_engine\.py|tests/test_pinned_cast\.py|tests/test_story_engine\.py|tests/test_movie_ui_builder\.py|tests/fixtures/pinned_cast/uncast_(chained_lines|shots_lines|chained_seed)\.txt)$' || echo "only the planned files"
git diff 0c0160d -- tests/test_story_engine.py | grep -c '^[+-] '
python3 -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_casting_regression.py tests/test_writer_pacing.py tests/test_dialogue.py tests/test_narrative_fidelity.py -k "rst40 or rst41 or rst61 or casting or wt8 or wt9 or dlg11 or nf16" 2>&1 | tail -1
```

Expected: `compiled 4` twice (PK2); `no import change` (PK3); `0` (spec 0.4 "Not changed"); `only the planned files`; `7` (the three removed and four added lines of the 4.3 A `test_rst8` edit, and nothing else in that file); then a `passed` line with no failure (PK7, PK9: `test_rst40`, `test_rst41`, `test_rst61`, `tests/test_casting_regression.py`, WT8, WT9, DLG11, NF16).

- [ ] **Step 6: Hand-off (controller; not an executor step).** Run the live checks of "Post-implementation: live checks" below after the merge, and put the spec 6 PR note in the PR description.

---

## Post-implementation: live checks (controller; spec 5, PK10; this Mac only, story-only; not a task and not a merge gate)

These runs are for the controller or the user after the merge, never for an executor. They run on this Mac only, never on macstudio (the user checks macstudio themselves), and they are story-only: nothing renders. Run them exactly as spec Section 5 writes them; the summary below is not a substitute for the spec text.

- **Setup.** `S` as above, `R=$S/pinned` (new, empty), and `W` = the merged workspace on this Mac (spec 5 names `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`; the controller decides when the merged code is there). The story model is the vllm-metal `qwen38-6bit` server on port 8177, started exactly as `start_llm` in `$S/hockey/rerun/run.sh`, and stopped with `bin/story-server stop` after the last run. The characters are this Mac's trained `kyra` ("the woman in grey") and `ronin` ("the ronin"). `N` is `LINES_NARRATIVE`.
- **Runs** (from `$W`, one after the other): `pin-ch3-a` and `pin-ch3-b` (`--panels 3`, chained), `pin-sh4-a` and `pin-sh4-b` (`--panels 4 --shots`), and `pin-sh2` (`--panels 2 --shots`). Each uses `--character kyra --character ronin --speech-only --story-only --no-review --force-story` and logs to `$R/run-<id>.log`. The exact command lines are in spec 5.
- **Measure.** Save spec 5's `measure.py` as `$R/measure.py`, and run `W=$W python3 -I $R/measure.py pin-ch3-a pin-ch3-b pin-sh4-a pin-sh4-b pin-sh2 > $R/measure.txt`.
- **Pass criteria (every run):** (a) exit 0, and Phase 1 completes with no `Error:` line; (b) both `kyra` and `ronin` have non-empty `beats` and `panels` lists in `measure.txt` (`panels` counts only Image, Motion or Prompt text inside `## Panel` sections); (c) every `speakers` entry is `the woman in grey`; (d) `hard` is `[]`; (e) chained runs: no advisory contains `"a speaking shot shows only the speaker"`; shots runs: the ronin's beats have no speaker in `plan.json`.
- **Recorded, not gating:** each run's plan-call count (2 means a retry; `plan_reply_1.txt` shows why), whether chained runs put the ronin in beat 1, and any N19 or P12 advisories. Optional and recorded: the pre-change control at `0c0160d` (`pin-ch3-base`, `pin-sh4-base`), the seed run `pin-seed3` (only if this Mac's story server has served `--seed-image` runs before), and the render of `pin-ch3-a` with contact sheets and whisper transcripts (R2, R3).
- Put the exit codes, `measure.txt`, and the plan reply and prompt of any retried run in the PR or report, with the spec 6 PR note.

---

## Coverage

### Spec section to task

| Spec | Task(s) |
|---|---|
| 0.4 G1 (`story_engine.py`) | 1 (PC3-PC6), 2 (PC1, PC2), 3 (PC7), 4 (PC8, PC9) |
| 0.4 G2 (`tests/test_pinned_cast.py`) | 1, 2, 3, 4 |
| 0.4 G3 (fixtures, 4.2) | 1 step 1.1 |
| 0.4 G4 (existing tests, 4.3 A) | 1 step 1.3 (`test_rst8`) |
| 0.4 G5 (`test_mut26`) | 5 steps 2, 3 |
| 0.4 Not changed | 5 step 5 (the `git diff` checks); PT1 (the five kept literals); every Edit touches only its listed text |
| 0.5 Out of scope | nothing is built for it; P12 and N19 stay advisory (no task edits them) |
| 0.6 PK1 | Before Task 1 (baseline), 5 step 4 |
| 0.6 PK2, PK3 | every task's compile check; `test_rst61` in each Step 4; 5 step 5 |
| 0.6 PK4 | 2 (PT6, PT7) |
| 0.6 PK5 | 2 (PT14, PT15; Review Focus 1) |
| 0.6 PK6 | 1 (PT2-PT5) |
| 0.6 PK7 | 3 (PT8-PT10; `test_dlg11`, `test_nf16` unedited in Step 4) |
| 0.6 PK8 | 4 (PT11-PT13, PT16) |
| 0.6 PK9 | 4 (PT17); 5 step 5 (WT8, WT9, `test_rst40`, `test_rst41`, `test_casting_regression.py`) |
| 0.6 PK10 | Post-implementation: live checks |
| D1 | 2 (PC1, PC2) |
| D2 | 1 (PC3) |
| D3 | 1 (PC5, PC6), 3 (PC7), 4 (PC8, PC9) |
| D4 | 1 (PC4); no post-writer check is built |
| D5 | 1-4 (the names); PT6 (`parse_violation` of P16) |
| D6 | nothing is built (P12 unchanged) |
| PC1 | 2 steps 3.1, 3.2 |
| PC2 | 2 step 3.3 |
| PC3 | 1 steps 3.4, 3.5 |
| PC4 | 1 steps 3.1, 3.6 |
| PC5 | 1 steps 3.2, 3.7 |
| PC6 | 1 steps 3.3, 3.7 |
| PC7 | 3 step 3.1 |
| PC8 | 4 steps 3.1-3.5 |
| PC9 | 4 step 3.6 |
| 3 interactions | plan retry and fatal exit: 2 (PT14, PT15, PT18, Review Focus 1); `assign_missing_lines` and `make_state`: 4 (PT16 runs both on an accepted plan); re-check: 4 (PT17); uncast runs: 1 (PT2), 3 (PC7 equivalence via DLG11, NF16), 4 (PT11's no-co-star case); `--no-narration`: 1 (PT4), 2 (PT6); critic, manifest, ltx-movie, movie-ui, iterate-story, `--story-legacy`: unchanged files (5 step 5) and the Step 4 suites |
| 4.1 | 1-4 (see the next table) |
| 4.2 | 1 step 1.1 |
| 4.3 A | 1 step 1.3; 5 step 2 |
| 4.3 B | every task's Step 4 run; 5 steps 4, 5 |
| 5 | Post-implementation: live checks |
| 6 rollout | Before Task 1 (snapshot, baseline); 1 step 1.1 (fixtures first); 1-4 (feature commits); 5 (review, test-only re-baseline, PK1, hand-off) |

### Test IDs and their owning task (each is owned by exactly one task)

| IDs | Task |
|---|---|
| PT1 (plan half: `test_pt1_plan_constants`), PT2, PT3, PT4, PT5; the 4.3 A edit of `test_rst8` | 1 |
| PT6, PT7, PT14, PT15, PT18, Review Focus 1, Review Focus 2 | 2 |
| PT8, PT9, PT10, Review Focus 3 | 3 |
| PT1 (writer half: `test_pt1_writer_constants_and_and_list`), PT11, PT12, PT13, PT16, PT17, Review Focus 4, Review Focus 5 | 4 |
| MUT26 re-baseline; PK1, PK2, PK3, PK9 measured; PK10 hand-off | 5 |

### Self-review

- **Spec coverage.** Every PC requirement (PC1-PC9) and every PT test (PT1-PT18) maps to exactly one task in the tables above. G1-G5, the 4.3 A edits and the PK criteria each have a step. The spec's live checks (Section 5) are the post-implementation section, not a task.
- **Placeholder scan.** No step says "TBD", "similar to Task N" or "add appropriate handling". Every test and implementation block is the full code. The only symbolic values are `$S`, `$WS`, `$D`, `$T` and `$SHA`, each defined in its block or in the house rules. Every expected count is a number measured on the replay (see "Execution handoff").
- **Type consistency.** `_raw(mode, n, casts, speakers=None)` builds a reply from `CAST2` in every task. `P16(cid, phrase, name, mode, narration)` matches PC1's format, including the `_q` quotes and the suffix rule. `_members(story_env)` returns `[CastMember]` in cast order (kyra c1, ronin c2). `_read_json(story_dir, name)` (Task 2) is used by Task 4. `se._and_list(items)` takes a non-empty list of phrase strings and is only called with `silent` non-empty. `speaking_coercion(ctx, plan, k)` keeps its signature and return type (a list of note strings).

## Plan decisions (where the spec is silent, conflicts with the task split, or needs a reading)

1. **Four feature commits instead of spec 6's single feature commit** (the task split: a reviewer can accept the planner text, the presence rule, the coercion and the writer text separately). `test_mut26` is re-based to the last commit that touches a `PIPELINE_FILES` entry (Task 4's, or the Step 1 review fix), in its own test-only commit, after the design review (Task 5). This follows how `0c0160d` re-based it to `cf0a0e6`.
2. **PT1 is two test functions.** `test_pt1_plan_constants` (Task 1) checks the five plan constants, the five kept literals and the "no `@@` token" rule. `test_pt1_writer_constants_and_and_list` (Task 4) checks the two writer constants, their token subset and `_and_list`. The writer constants exist only after Task 4, so a single PT1 in Task 1 could not pass. Every PT1 assertion is made once.
3. **The fixture script runs with `CHARACTER_LIBRARY_DIR` and `LORA_CATALOG_DIR` at empty temporary directories, as well as a temporary HOME** (spec 4.2 says "under a temporary HOME"). `build_plan_prompt` lists every undeclared library character, and `character_lib` falls back to `WS/generated/characters`. The worktree has no `generated/`, so the output is the same either way, but the empty library makes the fixtures equal to what PT2 rebuilds under `story_env`. The recorded hashes were produced this way on a scratch export of `246896b`.
4. **The PC8 comment is wrapped into two comment lines at 100 columns**, with the spec's words unchanged. The spec gives it as one line of 118 characters, and the file wraps every comment at 100 columns.
5. **PT2 compares the fixtures before it creates the library characters.** Once kyra and ronin are in the test library, an uncast prompt also carries the "Never use these names" sentence (`build_plan_prompt` `:740-742`), so the byte comparison must run first.
6. **Test readings.** The ctx of PT8, PT10, PT11, PT12, PT16 and Review Focus 3-5 uses `narration="speech"` (the reported `--speech-only` use; PT11 and PT16 name it, and the coercion does not depend on it). PT14's `NARRATIVE` is `test_story_engine.NARRATIVE`, copied, since `LINES_NARRATIVE` would add Q1 line problems to a reply that has no lines. The story ids the spec leaves open are `pc3` (PT18), `pc4` (Review Focus 1) and `pc5` (PT16, PT17). PT11's "contains no "silent"" is checked on the panel-2 motion key line. PT16 reads the `Image:` and `Dialogue:` lines straight from `story.md`. PT17 also asserts `story_checks.json` `source == "recheck"`, which proves the file was rewritten. PT13's second expected value is the spec's "SAY lands between the two speaker sentences", written out exactly as the unchanged `insert_speech` produces it: the facing sentence "The woman in grey faces the camera." moves to directly after the first action sentence, then SAY, then the second speaker sentence, then the camera sentence.
7. **Three tests pass before their own task's Step 3** and say so in Step 2: PT9 (Task 3), and PT13 and PT17 (Task 4). Each pins behaviour the new code must leave exactly as it is.
8. **`WS` is the worktree** (`$S/pc-wt/qwen-agent-workspace`), not the main checkout the spec names, per the controller's rule. Only the post-implementation live checks name the merged workspace, and the controller runs those.

## Questions for controller

None. The spec's four decisions to confirm (8.2: C1-C4) were approved by the user as written.

## Spec defects found (for the spec author; none blocks this plan)

1. **Spec 0.3's pre-existing failure list is wrong for the worktree.** It names `test_rst62_import_sets` and `test_rst48_judge_story_patches` with the judge run tests (the `anthropic` SDK error). The controller's baseline in `pc-wt` at `0c0160d`'s code tree failed only `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets` (`2 failed, 1839 passed, 2 skipped`), and `test_rst48` passed. This plan's gate expects exactly those two failures (Global Constraints).
2. **PC8's comment line is 118 characters** (Plan decision 4); cosmetic.
3. **Spec 4.2's fixture script does not isolate the character library** (Plan decision 3). It is harmless in the worktree, which has no `generated/`. In the main checkout it would write the real library's characters into the "uncast" fixtures, and PT2 would then fail.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-10-27-pinned-cast-presence.md`. Every Create, Append, Edit and Run block of Tasks 1-4 was replayed in order, by a script that reads this file, on two scratch `git archive` exports of `246896b` (one with a stub git history for the commit steps). Each old text occurred exactly once at its turn. The fixture hashes of Task 1 step 1.1 are the replay's. Each task's Step 2 run failed exactly as its Expected line states (`6 failed`; `7 failed, 5 passed`; `3 failed, 13 passed`; `6 failed, 18 passed`), and each Step 4 run gave `1 failed` (`test_rst62_import_sets`) with `454`, `461`, `465` and `473 passed, 1 skipped`. Every changed file compiled under Python 3.9.6 and 3.13, every spec Section 2 code block occurs verbatim in the replayed `story_engine.py`, and no added line is longer than 100 columns. The full suite on the replayed tree after Task 4 gave `2 failed, 1862 passed, 3 skipped`: the two baseline failures, the 24 new tests passing, and `test_mut26` skipped only because the stub history lacks `cf0a0e6` (in `pc-wt` it passes after Task 5's re-baseline, which gives `2 failed, 1863 passed, 2 skipped`). No other baseline pass was lost, and `tests/test_ltx_movie_offline.py` printed `OK 347/347`. Task 5's re-baseline script was dry-run on a copy with a dummy SHA, and its Step 5 `git diff` checks were dry-run against the stub base. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven**: a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end.
- **Native**: one session implements every task, then one fresh reviewer checks the whole branch.

For this plan I recommend **subagent-driven**. Its four feature tasks have separate review questions (planner text, the fatal-exit policy, the coercion, the writer text), and each one has its own failing-test cycle.
