# Location Dataset Yield Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** More location stills survive the build, with no model change. Each photo-mode edit is scored against its own source photo. A text location whose description names an interior is drawn with indoor-aware variants. When fewer than 12 stills are kept, the dropped generated or edited stills are regenerated with new seeds for up to 2 bounded top-up rounds.

**Architecture:**
- All behaviour lives in `location_dataset.py`.
  - **Task 1** changes one argument of `_check_entry`'s edit check and the manifest's `"reference"` value.
  - **Task 2** adds the indoor rule (`INDOOR_WORDS`, `indoor_word`) and the indoor set (`INDOOR_VIEWS`, `INDOOR_LIGHTS`, `INDOOR_LIGHT_PHRASES`, `INDOOR_VARIANTS`, `INDOOR_PROMPT`, `indoor_prompt`). `_plan` chooses the set, `_build_dataset` prints the `variants:` line, and the manifest records `"variant_set"`.
  - **Task 3** adds round labels: `write_contact_sheet(..., rounds=1)`'s banner suffix, `cell_label`'s `rN` tag, and the movie-ui Locations card's `(round N)`. Nothing writes a `round` yet, so every output stays as it is today.
  - **Task 4** splits the round-1 build. `_plan` returns entries only (each with `seed` and `round`). `_child_spec` builds a child spec from any entries, `_render` runs one round's child, `_round_summary` records a round, and `_record` writes the manifest, contact sheet and `location.json`. The top-up loop uses `topup_seed`, and the `bin/location` and module docstrings gain one sentence each.
- No new module, no new dependency and no `location.json` schema change. `character_dataset.py` and every `PIPELINE_FILES` entry are untouched.

**Tech Stack:**
- Tests run on Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, with pytest 8.3.4, Pillow 12.3 and psutil 6.1). The compile check also uses Python 3.9.6 (`/usr/bin/python3`).
- The page is vanilla ES2017 in `static/movie-ui/app.js`. When `node` is installed (`/opt/homebrew/bin/node` on this Mac), `test_lu13` runs `node --check` on it.
- Real ffmpeg/ffprobe wrap kept stills in the tests, as today.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-02-location-yield-design.md`, committed at `b029c2b` on `location-yield`.
- It defines requirements LY1-LY16, tests LYD1-LYD13 and LYU1, and KPIs LYK1-LYK8.
- It amends Sections 2.5, 2.9, 2.10, 2.11 and 2.12 of `docs/superpowers/specs/2026-10-29-location-lora-design.md` ([LOC]). The implementer does not edit [LOC].
- The spec's line numbers cite `98e5f64`. `b029c2b` adds only the spec, so they still hold, and this plan cites them too. Each Edit below is located by its old text, never by a line number.
- The spec is binding. Where it leaves a detail open, this plan decides it in "Plan rulings" (R1-R12, all **[reading]**: none changes spec behaviour).

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.2] "The following files are not touched: `character_dataset.py`, `location_lib.py`, `movie_ui_server.py`, `movie_ui_lib.py`, `static/movie-ui/index.html`, and every `PIPELINE_FILES` entry. `location.json`'s schema is unchanged (LY13)."
- [0.3] Out of scope:
  - "People-removal edits on user photos"
  - "An edit-model selection from the Seeds registry"
  - "Any change to `MIN_KEEP` (12) or `MIN_SCORE` (7)"
  - "Any change to LoRA training"
  - "Indoor-aware photo-mode edits. `EDIT_PROMPT`, `EDIT_CONDITIONS` and `EDIT_VIEWS` are unchanged, and the indoor rule never applies in photo mode"
  - "A CLI flag or UI control to disable, extend or size the top-up"
  - "An explicit indoor/outdoor override field"
- [0.5] "Every LY requirement and every test in Section 7 is a must-have. Nothing else is built. None of the Section 0.3 items is built."
- [LYK2] "**Outdoor byte-identity.** For an outdoor description whose round 1 keeps at least 12, the round-1 child spec, stdout, stderr, `contact_sheet.jpg` and `location.json` are identical to `98e5f64`. The manifest differs only by the added keys of LY12."
- [LYK4] "At most 3 rounds and at most 3 story-server stop/restore cycles. Each top-up round renders exactly the regenerable stills, each with the LY7 seed. A user photo is never re-rendered. The rounds stop as soon as kept >= 12."
- [LYK6] "`/usr/bin/python3` (3.9) and `python3` both `py_compile` `location_dataset.py` and `bin/location`. No `match`, no PEP 604 unions, no walrus."
- [LYK7] "`character_dataset.py` and every `PIPELINE_FILES` entry are unchanged. `test_mut26` passes with no re-baseline."
- [LY6, LY7] `TOPUP_ROUNDS = 2`; `SEED_MAX = 2147483647 = 0x7FFFFFFF`. `location_lib` keeps `MIN_SCORE = 7`, `MIN_KEEP = 12` and `TOTAL_STILLS = 24`.
- [6] "The status rule (`untrained` when kept >= 12, else `dataset`) and the exit codes 0/1/2/3 are unchanged." The too-few message text is unchanged.
- [7.1] "pytest only; every library and `HOME` under `tmp_path`; never the real HOME; no real model, render or Z-Image/Qwen/VLM process, and no server contact; the children are stubbed at the process boundary (`character_dataset.run_zimage_child`/`run_edit_child`, `vlm_call`, `story_server`, `restore_story_server`, `wait_for_vlm`, `wait_for_avail`, `vlm_ready`, `busy_process`, `free_gib`, `edit_models_missing`) by `_Fakes`."
- [7.3] "LD1, LD2, LD5, LD11, LD14, LD16, LD17 and LD24, and every test in the other `tests/test_location_*.py` files, pass unedited." Only LD9, LD13, LD15 and `_Fakes` change.
- [8] The live check: "Agents never run this: it renders, and it needs the macstudio host, which agents must not touch."

Controller rules. One line each; every task's requirements include them.

- pytest runs from `qwen-agent-workspace/`.
  - Tests never use the real HOME, never load a real model, never render, and never contact a server. An in-test `127.0.0.1` server is OK.
  - Image children, the VLM and the story server are stubbed at the process boundary, as the existing `_Fakes` does.
- **Full-suite baseline:** exactly 2 known failures, and `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`. The failures are:
  - `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`
  - `tests/test_story_engine.py::test_rst62_import_sets`

  Every task leaves the suite otherwise green: no baseline pass is lost, and every new test passes.
- `character_dataset.py` is not modified (`test_mut26` pins it).
- The commit trailer is "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", passed as a second `-m`.
- Never stage `.DS_Store`, `.claude/`, `__pycache__/`, repo-root `bin/`, `qwen-agent-workspace/bin/action-from-dir`, `pin-sh2.json`, `story_bible_*.json` or `.superpowers/`. Stage only the paths a task names, and check `git diff --cached --name-only` before every commit.
- Never read, cat, grep or source `~/.zshenv` or any `fleet.env`, and never print tokens.
- Never ssh, scp, rsync or HTTP to macstudio. Never download model weights. Never push.
- **Python:** every changed file compiles on 3.9.6 and 3.13. So use none of: the `match` statement, `X | Y` type expressions, the walrus operator, `str.removeprefix`, `zip(strict=)` and parenthesised context managers. The code below uses none of them.
- **Editing:** executors change tracked files only with the Edit tool. Code blocks are copied byte for byte.
  - An Edit's old text must occur exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it.
  - Every old text below was checked against a replay of this plan (see "Execution handoff").
  - Never use `sed -i`, a redirect or a script to change a tracked file.
- **Paths:**
  - `S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
  - The worktree is `$S/locyield-wt`, on branch `location-yield`. `WS=$S/locyield-wt/qwen-agent-workspace`.
  - `D=$S/locyield-baseline` holds scratch files and is never staged.
  - Run every command from `WS`. Shell variables do not persist between commands, so every block defines the variables it uses.
  - Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`.

## Review Focus

The spec implies these five inputs and failure modes, but no LYD/LYU row exercises them. They are the ones most likely to reach the user first. Each is pinned by a `test_ly_review_focus_N_...` test in the task that owns its code.

1. **A photo location whose description names an interior.**
   - The user's subway location may be a photo location. The spec keeps photo mode outdoor-agnostic (0.3, LY5 "Photo mode never calls `indoor_word`"), but only text-mode tests use `SUBWAY_DESC`.
   - Expected, for a 2-photo create with `SUBWAY_DESC`:
     - `indoor_word` is never called (it is patched to raise);
     - no `variants:` line is printed and `variant_set` is `None`;
     - the 22 edit prompts are the unchanged `EDIT_PROMPT` ones;
     - each edit is checked against its own source photo.
   - Test: `test_ly_review_focus_1_a_photo_location_with_an_indoor_description` (Task 2).
2. **`--regenerate --description` that moves a text location between outdoor and indoor.**
   - LY5 says the rule "re-evaluates", but LYD3 only creates.
   - Expected:
     - outdoor to `SUBWAY_DESC`: the rebuild prints `variants: indoor (the description has the word "underground")`, its 24 prompts are `indoor_prompt`s, `variant_set` is `"indoor"` and the record holds the new description;
     - back to `HARBOUR_DESC`: no `variants:` line, `gen_prompt`s, and `"outdoor"`.
   - Test: `test_ly_review_focus_2_regenerate_with_a_new_description_switches_the_variants` (Task 2).
3. **The vision model fails while it scores a top-up round.**
   - Every round's restore reloads the VLM (LY11), and this host's vision server is known to die under load. LYD11 fails only the image child.
   - Expected, when round 2's first check raises `RuntimeError("VLM request failed: connection refused")`:
     - exit 1, and the last stderr line is `Error: VLM request failed: connection refused`;
     - the server calls are `["stop", "restore-wait"] * 2`;
     - the record is round 1's: status `dataset`, kept 11, one round, every item `round` 1;
     - `captions/` and `videos/` hold exactly n 1-11.
   - Test: `test_ly_review_focus_3_the_vision_model_fails_in_a_top_up_round` (Task 4).
4. **`--regenerate` after a failed top-up round.**
   - LY11 names `--regenerate` as the remedy, and LY9 step 6.6 has already deleted the dropped stills.
   - Expected:
     - after a round-2 child failure, `stills/` holds exactly n 1-11;
     - `create --regenerate` then exits 0 after one `generate` call of 24 jobs;
     - `rounds` is `[1]`, every item is `(round 1, seed 0, kept)`, status is `untrained` with 24 kept, and `stills/` holds n 1-24.
   - Test: `test_ly_review_focus_4_regenerate_after_a_failed_top_up_round` (Task 4).
5. **A still kept in a top-up round is trained.**
   - Training is the point of the dataset. LYD6 checks only `captions/`.
   - Expected, after the LYD6 build:
     - `videos/` holds exactly `loc_01.mp4`..`loc_12.mp4`;
     - `captions/loc_12.txt` equals item 12's `caption`;
     - the pairs `_train_stills` passes to `train_stills_lora` (stubbed) are exactly the still and caption paths of n 1-12.
   - Test: `test_ly_review_focus_5_a_still_kept_in_a_top_up_round_is_trained` (Task 4).

## Plan rulings

Each fills a detail the spec leaves open. None changes behaviour the spec states.

- **R1 [reading]** LY12's manifest keys land with the fix each one describes:
  - `"reference": "source photo"` in Task 1, with LY1, whose rule it names;
  - `"variant_set"` in Task 2, with LY5;
  - `"rounds"` and the per-item `"seed"`/`"round"` in Task 4.

  After Task 4 the manifest is exactly LY12's: key order `source, trigger, description, seed, min_score, reference, generator, variant_set, rounds, items`.
- **R2 [reading]** The LD13 re-baseline of spec 7.3 is split the same way: the photo `reference` in Task 1, the two `variant_set` lines in Task 2, and the `rounds`, `seed` and `round` lines in Task 4. Each task edits exactly the existing assertions its own code breaks, so the suite is green after every task.
- **R3 [reading]** The test file docstring's first sentence ends `character_dataset.py (LD18), and the yield spec LYD1-LYD13.` (spec 7.1: it "gains `, and the yield spec LYD1-LYD13`").
- **R4 [reading]** LYD1's compile step loops over `/usr/bin/python3` and `sys.executable`, and an interpreter that is absent is skipped (`continue`). The other one still runs, so `pytest.skip` is not used.
- **R5 [reading]** A `_Fakes` instance's `rounds` follows its own child-call count, and a name can be created only once. So these second creates each get a new `_Fakes` and, where needed, a new name (`dock-one`, `old-mill`): LYD8's `force=True` repeat, LYD11(b), and LYD12's `--new-seed` and same-seed runs.
- **R6 [reading]** The contact sheet is redrawn after every round, so LYD7 asserts the **last** banner drawn.
- **R7 [reading]** LYD6 checks the stdout order with a helper `_in_order` that finds each line after the end of the one before it (`=== check ===` occurs twice).
- **R8 [reading]** The spec names no place for the new functions:
  - `topup_seed`, `_child_spec` and `_render` sit between `_with_story_server_stopped` and `_check_entry` (`topup_seed` directly before `_plan`, the other two directly after it);
  - `_round_summary` and `_record` sit between `reason_counts` and `build_dataset`;
  - `TOPUP_ROUNDS` sits directly after `DESCRIBE_PHOTOS`;
  - the indoor block sits directly after `gen_prompt`, as LY2 says.
- **R9 [reading]** Only the round header (LY9 step 6.5) uses `flush=True`, as the spec writes it. The `variants:`, `top-up: not run` and `top-up round R of 3: kept` lines use plain `print`. The next flushed line, or process exit, writes them in order.
- **R10 [reading]** `cell_label` binds `item.get("round")` to a local `round_n` before applying LY14's test (an `int` that is not a `bool` and is `> 1`). The behaviour is identical. LYD13 also checks that `round: True` gives no tag.
- **R11 [reading]** Each task appends its new tests at the end of `tests/test_location_dataset.py`, under the one `# --- LY: ...` header, so the file order is LYD4; LYD1-LYD3, RF1, RF2; LYD13; LYD5-LYD12, RF3-RF5. `SUBWAY_DESC` sits directly under the header. LYU1 sits at the end of `tests/test_location_ui.py`, under its own header.
- **R12 [reading]** The module docstring's new sentence goes directly after `... and a 1-frame mp4.` (LY15), and the rest of that paragraph is rewrapped to 100 columns. The words are unchanged.

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `location_dataset.py` | Modify (Tasks 1-4) | T1: own-source edit check, `reference`. T2: indoor rule and indoor variants, `variants:` line, `variant_set`. T3: banner `rounds`, `cell_label` tag. T4: `TOPUP_ROUNDS`, `topup_seed`, `_plan` (entries only), `_child_spec`, `_render`, `_round_summary`, `_record`, the top-up loop in `_build_dataset`, per-item `seed`/`round`, module docstring. |
| `bin/location` | Modify (Task 4) | The docstring's exit-code paragraph (LY15). |
| `static/movie-ui/app.js` | Modify (Task 3) | The Locations card figcaption's first element (LY16). |
| `tests/test_location_dataset.py` | Modify (Tasks 1-4) | T1: docstring, LD9, LD13 `reference`, LY header, LYD4. T2: `import subprocess`, `SUBWAY_DESC`, LD13 `variant_set`, LYD1-LYD3, RF1, RF2. T3: LYD13. T4: `_Fakes` (spec 7.2), LD13 `rounds`/`seed`/`round`, LD15 `skip_n`, helpers, LYD5-LYD12, RF3-RF5. |
| `tests/test_location_ui.py` | Modify (Task 3) | LYU1. |

**Task split.** Each task carries its own test cycle and can be rejected on its own:

- Task 1 is fix 1: one argument, two re-baselined assertions and one new test.
- Task 2 is fix 2: pure literals and a rule, plus one branch in `_plan`.
- Task 3 is the display of rounds. It reads `round` with a presence check, so it ships before anything writes `round` and changes no output.
- Task 4 is fix 3, which restructures `_build_dataset`. It needs Task 3's `rounds=` parameter.

No task changes a file outside the table. The spec requires no README or [LOC] change.

---

## Before Task 1: the snapshot and the baseline (controller; no code)

- [ ] **Step 1: Confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/locyield-wt/qwen-agent-workspace
git branch --show-current                     # expected: location-yield
git log -3 --format='%h %s'                   # expected: <plan sha> docs: location dataset yield implementation plan; b029c2b docs: location dataset yield spec (...); 98e5f64 Merge pull request #6 ...
git diff --stat b029c2b HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                            # expected: no output
wc -l location_dataset.py bin/location static/movie-ui/app.js tests/test_location_dataset.py tests/test_location_ui.py | head -5
```

Expected `wc -l` counts: `location_dataset.py` 924, `bin/location` 161, `app.js` 3073, `tests/test_location_dataset.py` 1162, `tests/test_location_ui.py` 425. If any count differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Take the compressed snapshot (house rule).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-locyield-b029c2b.tgz --exclude qwen-agent-workspace/generated -C $S/locyield-wt qwen-agent-workspace
tar tzf $S/snapshot-pre-locyield-b029c2b.tgz | grep -c 'qwen-agent-workspace/location_dataset.py$'   # expected: 1
```

- [ ] **Step 3: Record the baseline and write the gate script.**

The full run takes about 18 minutes. It may run in the background.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/locyield-baseline
mkdir -p $D
cd $S/locyield-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 > $D/baseline-offline.txt; cat $D/baseline-offline.txt
```

Expected:
- exactly two `FAILED` lines, `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`;
- no `ERROR` line;
- `OK 347/347`.

Record the `PASSED` count as `P0`. If the failures differ, stop and report.

Then create `$D/gate.py` with the Write tool, exactly as below. It is outside the repository and never staged.

```python
"""The task gate of the location yield plan: a full pytest -rA run against the baseline. No
baseline pass may be lost, every new test (an ID the baseline does not have) must pass, their
count must be the expected one, and only the two known failures may fail."""
import re
import sys

base_file, run_file, want_new = sys.argv[1], sys.argv[2], int(sys.argv[3])
KNOWN = ["tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike",
         "tests/test_story_engine.py::test_rst62_import_sets"]


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            found = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if found:
                out[found.group(2)] = found.group(1)
    return out


base, now = status(base_file), status(run_file)
lost = sorted(t for t, s in base.items() if s == "PASSED" and now.get(t) != "PASSED")
new = sorted(t for t in now if t not in base)
broken = [t for t in new if now[t] != "PASSED"]
failing = sorted(t for t, s in now.items() if s in ("FAILED", "ERROR"))
print("lost %d; new tests %d (want %d), not passing %d; failing %d"
      % (len(lost), len(new), want_new, len(broken), len(failing)))
for t in lost:
    print("LOST", t)
for t in broken:
    print("NEW-TEST-FAIL", t, now[t])
for t in failing:
    if t not in KNOWN:
        print("FAILING", t)
ok = not lost and not broken and len(new) == want_new and failing == sorted(KNOWN)
print("GATE", "PASS" if ok else "STOP")
```

**The gate block.** This is the last step but one of every task. `N` is the task number, and `NEW` is the cumulative count of new test IDs: 1 after Task 1, 6 after Task 2, 8 after Task 3 and 19 after Task 4.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/locyield-baseline
N=1; NEW=1
cd $S/locyield-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $NEW
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
git -C .. diff --quiet b029c2b -- qwen-agent-workspace/character_dataset.py && echo "character_dataset unchanged"
```

Expected: `GATE PASS`, `offline unchanged` and `character_dataset unchanged`, with a `PASSED` count of `P0 + NEW`.

**On `GATE STOP`,** the executor stops and reports the `LOST`, `NEW-TEST-FAIL` and `FAILING` IDs, with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass is a defect in the task's code, and the controller writes the exact fix.

**Timing-sensitive tests unrelated to this plan:** `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` and `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules`. If the gate lists one of them as `LOST`, rerun it alone with `python3 -B -m pytest -q -p no:cacheprovider <node id>`. If it passes alone, the controller records it as flaky and the gate counts as passed.

**The compile check** (Step 4 of every task) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

---

### Task 1: Score each edit against its own source photo (LY1; LYD4)

This task implements:
- LY1: `_check_entry`'s edit branch checks `[still_path(loc_dir, entry["photo"]), png]`.
- LY12's `"reference"` value, `"source photo"` in photo mode (Plan ruling R1).

Re-baselines, in the same task (R2):
- LD9's expected checks (spec 7.3 row 1);
- LD13's photo `reference` (part of spec 7.3 row 2).

Also adds the test file docstring phrase (R3) and the LY test header. New test: LYD4.

**Files:**
- Modify: `location_dataset.py`: `_check_entry` `:404-405` and `_build_dataset`'s manifest literal `:487`.
- Modify: `tests/test_location_dataset.py`: docstring `:3-4`, LD9 `:546-551`, LD13 `:628-630`, and the end of the file after LD27 `:1162`.

**Interfaces:**
- Consumes:
  - `_check_entry(data, loc_dir, entry, force) -> item`;
  - `entry["photo"]`, the 1-based source photo of an edit, which `_plan` sets to `((j - 1) % P) + 1` (`:377`);
  - `still_path(loc_dir, n) -> str`.
- Produces:
  - the manifest's `"reference"`: `"source photo"` (photo mode) or `None` (text mode);
  - the line `# --- LY: dataset yield (docs/superpowers/specs/2026-11-02-location-yield-design.md) ---` at the end of `tests/test_location_dataset.py`. Tasks 2-4 add their tests below it;
  - `test_lyd4_each_edit_is_scored_against_its_own_source_photo`. Its last line, `    assert _manifest(env, "old-mill")["reference"] == "source photo"`, is Task 2's anchor.

- [ ] **Step 1: Write the failing tests.** Four Edits to `tests/test_location_dataset.py`, in this order.

**Edit `tests/test_location_dataset.py`:** the module docstring's first sentence (Plan ruling R3). Old text:

```python
the plan's Review Focus pins): location_dataset.py, and the qwenedit child extension in
character_dataset.py (LD18).
```

New text:

```python
the plan's Review Focus pins): location_dataset.py, and the qwenedit child extension in
character_dataset.py (LD18), and the yield spec LYD1-LYD13.
```

**Edit `tests/test_location_dataset.py`:** LD9's expected checks: each edit's reference is its own source photo (spec 7.3 row 1). Old text:

```python
    ref = "file:" + os.path.join(stills, "loc_01.png")
    assert fakes.checks() == (
        [(ld.TAG_PROMPT, ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
         for n in range(1, count + 1)]
        + [(ld.CHECK_PHOTO_PROMPT, [ref, "file:" + os.path.join(stills, "loc_%02d.png" % n)])
           for n in range(count + 1, 25)])
```

New text:

```python
    assert fakes.checks() == (
        [(ld.TAG_PROMPT, ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
         for n in range(1, count + 1)]
        + [(ld.CHECK_PHOTO_PROMPT,
            ["file:" + os.path.join(stills, "loc_%02d.png" % (((n - count - 1) % count) + 1)),
             "file:" + os.path.join(stills, "loc_%02d.png" % n)])
           for n in range(count + 1, 25)])
```

**Edit `tests/test_location_dataset.py`:** LD13's photo-mode `reference` (spec 7.3 row 2, part of R2). Old text:

```python
        "photos", "loc_01", "Qwen/Qwen-Image-Edit-2511 + "
```

New text:

```python
        "photos", "source photo", "Qwen/Qwen-Image-Edit-2511 + "
```

**Edit `tests/test_location_dataset.py`:** append the LY header and LYD4 after LD27, the file's last test. Old text:

```python
    assert "same camera position" not in prompt and "identical" not in prompt
```

New text:

```python
    assert "same camera position" not in prompt and "identical" not in prompt


# --- LY: dataset yield (docs/superpowers/specs/2026-11-02-location-yield-design.md) ---

def test_lyd4_each_edit_is_scored_against_its_own_source_photo(env, monkeypatch, tmp_path):
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 3),
                                  description=lt.MILL_DESC)) == 0
    stills = os.path.join(env["locations"], "old-mill", "stills")
    checks = fakes.checks()
    assert len(checks) == 24
    assert checks[3:] == [
        (ld.CHECK_PHOTO_PROMPT,
         ["file:" + os.path.join(stills, "loc_%02d.png" % (((n - 4) % 3) + 1)),
          "file:" + os.path.join(stills, "loc_%02d.png" % n)])
        for n in range(4, 25)]
    # edit 5 is checked against photo 2 and edit 6 against photo 3, not against photo 1
    assert checks[4][1][0] == "file:" + os.path.join(stills, "loc_02.png")
    assert checks[5][1][0] == "file:" + os.path.join(stills, "loc_03.png")
    assert _manifest(env, "old-mill")["reference"] == "source photo"
```

- [ ] **Step 2: Run the file to verify the new and edited tests fail.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py`

Expected: `4 failed, 27 passed`. The failures are:
- `test_ld9_the_round_robin_top_up[3]` and `[5]`: AssertionError, because edit 5 is checked against `loc_01`;
- `test_ld13_the_manifest`: AssertionError, `'loc_01'` vs `'source photo'`;
- `test_lyd4_each_edit_is_scored_against_its_own_source_photo`: AssertionError.

`test_ld9[1]` and `[24]` pass. With one photo, photo 1 is every edit's source; with 24, there are no edits.

- [ ] **Step 3: Implement.** Two Edits to `location_dataset.py`.

**Edit `location_dataset.py`:** `_check_entry`'s edit branch (LY1). Old text:

```python
    elif entry["source"] == "edit":
        check, unparseable = check_still(CHECK_PHOTO_PROMPT, [still_path(loc_dir, 1), png], True)
```

New text:

```python
    elif entry["source"] == "edit":
        check, unparseable = check_still(
            CHECK_PHOTO_PROMPT, [still_path(loc_dir, entry["photo"]), png], True)
```

**Edit `location_dataset.py`:** `_build_dataset`'s manifest `"reference"` (LY12, R1). Old text:

```python
                "min_score": location_lib.MIN_SCORE, "reference": "loc_01" if photo_mode else None,
```

New text:

```python
                "min_score": location_lib.MIN_SCORE,
                "reference": "source photo" if photo_mode else None,
```

- [ ] **Step 4: Run the two location files and the compile check.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_ui.py`

Expected: `48 passed`.

Then run the compile check with `FILES` = `location_dataset.py tests/test_location_dataset.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: Run the gate** with `N=1; NEW=1`. Expected: `GATE PASS`. The one new test is `test_lyd4_...`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/locyield-wt/qwen-agent-workspace
git add location_dataset.py tests/test_location_dataset.py
git diff --cached --name-only   # expected: exactly the two paths, with the qwen-agent-workspace/ prefix
git commit -m "fix(location): score each photo-mode edit against its own source photo (yield spec LY1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Indoor-aware text-mode variants (LY2-LY5; LYD1-LYD3, Review Focus 1-2)

This task implements:
- LY2 `INDOOR_WORDS`, verbatim.
- LY3 `indoor_word(description)`, verbatim.
- LY4: `INDOOR_VIEWS`, `INDOOR_LIGHTS`, `INDOOR_LIGHT_PHRASES`, `INDOOR_VARIANTS`, `INDOOR_PROMPT` and `indoor_prompt`, verbatim, directly after `gen_prompt`.
- LY5:
  - `_plan` draws a text location from `INDOOR_VARIANTS` with `indoor_prompt` when `indoor_word(description)` is not None, else from `VARIANTS` as today;
  - `_build_dataset` prints `variants: indoor (the description has the word "<word>")` before the first `=== generate:` line;
  - the manifest records `"variant_set"`: `"indoor"`, `"outdoor"` or `None` in photo mode (R1).
- Photo mode never calls `indoor_word`.

Re-baselines LD13's two `variant_set` lines (R2). New tests: LYD1, LYD2, LYD3, Review Focus 1 and 2.

**Files:**
- Modify: `location_dataset.py`:
  - after `gen_prompt` `:77-79`;
  - `_plan` `:364-370`;
  - `_build_dataset` `:469-473` and `:483-493`.
- Modify: `tests/test_location_dataset.py`:
  - imports `:17-23`;
  - LD13 `:610-612` and `:628-631`;
  - the LY section (Task 1's header and LYD4).

**Interfaces:**
- Consumes:
  - `location_lib.description_words(description) -> [str]` (`[a-z0-9]+` on the lower-cased text);
  - `STYLE`;
  - Task 1's LY header and LYD4's last line.
- Produces (Task 4 relies on these names):
  - `INDOOR_WORDS: frozenset` (36 words);
  - `indoor_word(description) -> str or None`;
  - `INDOOR_VIEWS: tuple`, `INDOOR_LIGHTS: tuple`, `INDOOR_LIGHT_PHRASES: dict`, `INDOOR_VARIANTS: list of (view, light)`, `INDOOR_PROMPT: str`;
  - `indoor_prompt(view, light, description) -> str`;
  - in `_build_dataset`, the locals `photo_mode` (now set before the render) and `word`.
  - `_plan` still returns `(plan, (child, spec))` in this task. Its text branch begins `word = indoor_word(data["description"])`.
  - `SUBWAY_DESC` (test module constant).
  - The last two lines of `test_ly_review_focus_2_...`, `        for view, time, weather in ld.VARIANTS]` and `    assert _manifest(env)["variant_set"] == "outdoor"`, are Task 3's anchor.

- [ ] **Step 1: Write the failing tests.** Five Edits to `tests/test_location_dataset.py`, in this order.

**Edit `tests/test_location_dataset.py`:** the imports gain `subprocess` (LYD1's compile step). Old text:

```python
import re
import sys
import types
```

New text:

```python
import re
import subprocess
import sys
import types
```

**Edit `tests/test_location_dataset.py`:** LD13's text-mode top-level keys gain `"variant_set": "outdoor"` (R2). Old text:

```python
        "min_score": 7, "reference": None, "generator": "Z-Image"}
```

New text:

```python
        "min_score": 7, "reference": None, "generator": "Z-Image", "variant_set": "outdoor"}
```

**Edit `tests/test_location_dataset.py`:** LD13's photo part asserts `variant_set` is None (R2). Old text:

```python
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    photo, edit = manifest["items"][1], manifest["items"][2]
```

New text:

```python
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    assert manifest["variant_set"] is None
    photo, edit = manifest["items"][1], manifest["items"][2]
```

**Edit `tests/test_location_dataset.py`:** `SUBWAY_DESC` directly under the LY header (spec 7.1, R11). Old text:

```python
# --- LY: dataset yield (docs/superpowers/specs/2026-11-02-location-yield-design.md) ---
```

New text:

```python
# --- LY: dataset yield (docs/superpowers/specs/2026-11-02-location-yield-design.md) ---

SUBWAY_DESC = ("a dimly lit underground new york subway platform with white tiled walls, green steel "
               "columns, mosaic station name signs, a yellow edge strip and dark track beds")
```

**Edit `tests/test_location_dataset.py`:** append LYD1, LYD2, LYD3, Review Focus 1 and 2 after LYD4. Old text:

```python
    assert _manifest(env, "old-mill")["reference"] == "source photo"
```

New text:

```python
    assert _manifest(env, "old-mill")["reference"] == "source photo"


def test_lyd1_the_indoor_rule(tmp_path):
    assert ld.INDOOR_WORDS == frozenset([
        "atrium", "attic", "auditorium", "basement", "bathroom", "bedroom", "carpet", "carpeted",
        "cellar", "ceiling", "ceilings", "chandelier", "chandeliers", "classroom", "concourse",
        "corridor", "corridors", "crypt", "escalator", "escalators", "foyer", "hallway",
        "hallways", "indoor", "indoors", "interior", "interiors", "lobby", "room", "rooms",
        "subway", "tunnel", "tunnels", "underground", "wallpaper", "wallpapered"])
    assert len(ld.INDOOR_WORDS) == 36
    assert ld.indoor_word(SUBWAY_DESC) == "underground"
    cafe = ("a small café terrace in Montréal with wrought iron chairs, striped awnings, cracked "
            "terracotta tiles and a faded blue sign above the door")    # test_location_tool.py:35
    ui = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
          "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
    for description in (lt.HARBOUR_DESC, lt.TEMPLE_DESC, lt.MILL_DESC, cafe, ui):
        assert ld.indoor_word(description) is None, description
    for word in sorted(ld.INDOOR_WORDS):
        assert ld.indoor_word("a quiet " + word + " with old fittings") == word
    for description in ("a grand ballroom with gilded mirrors", "a roomy yard with old sheds",
                        "an undergrounds market square"):
        assert ld.indoor_word(description) is None, description
    assert ld.indoor_word("a Subway entrance on a corner") == "subway"
    script = ("import py_compile, sys\n"
              "py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)\n")
    for python in ("/usr/bin/python3", sys.executable):
        if not os.path.isfile(python):
            continue                                     # an absent interpreter is skipped
        for k, rel in enumerate(("location_dataset.py", os.path.join("bin", "location"))):
            proc = subprocess.run([python, "-B", "-c", script, os.path.join(WS, rel),
                                   str(tmp_path / ("%d.pyc" % k))],
                                  capture_output=True, text=True, timeout=120)
            assert proc.returncode == 0, (python, rel, proc.stderr)


def test_lyd2_the_indoor_literals():
    views = ["Wide establishing shot from one end", "Wide shot from a high corner",
             "Eye-level view looking along the length", "Low-angle view from near the floor",
             "Medium shot of a single detail", "Close-up of a surface texture or sign"]
    assert ld.INDOOR_VIEWS == tuple(views)
    assert ld.INDOOR_LIGHTS == ("overhead", "dim", "bright", "warm", "cool", "shadow")
    assert ld.INDOOR_LIGHT_PHRASES == {
        "overhead": "under its own overhead lights", "dim": "in dim low light",
        "bright": "under bright even light", "warm": "in warm artificial light",
        "cool": "in cool white light", "shadow": "with deep shadows and pools of light"}
    assert ld.INDOOR_VARIANTS == [
        ("Wide establishing shot from one end", "overhead"),
        ("Wide establishing shot from one end", "dim"),
        ("Wide establishing shot from one end", "bright"),
        ("Wide establishing shot from one end", "warm"),
        ("Wide shot from a high corner", "dim"),
        ("Wide shot from a high corner", "bright"),
        ("Wide shot from a high corner", "warm"),
        ("Wide shot from a high corner", "cool"),
        ("Eye-level view looking along the length", "bright"),
        ("Eye-level view looking along the length", "warm"),
        ("Eye-level view looking along the length", "cool"),
        ("Eye-level view looking along the length", "shadow"),
        ("Low-angle view from near the floor", "warm"),
        ("Low-angle view from near the floor", "cool"),
        ("Low-angle view from near the floor", "shadow"),
        ("Low-angle view from near the floor", "overhead"),
        ("Medium shot of a single detail", "cool"),
        ("Medium shot of a single detail", "shadow"),
        ("Medium shot of a single detail", "overhead"),
        ("Medium shot of a single detail", "dim"),
        ("Close-up of a surface texture or sign", "shadow"),
        ("Close-up of a surface texture or sign", "overhead"),
        ("Close-up of a surface texture or sign", "dim"),
        ("Close-up of a surface texture or sign", "bright")]
    for view in views:
        lights = [light for v, light in ld.INDOOR_VARIANTS if v == view]
        assert len(lights) == 4 and len(set(lights)) == 4, view
    assert dict((light, sum(1 for _v, x in ld.INDOOR_VARIANTS if x == light))
                for light in ld.INDOOR_LIGHTS) == dict((light, 4) for light in ld.INDOOR_LIGHTS)
    assert ld.INDOOR_PROMPT == "%s of %s, %s, empty of people. %s."
    d = SUBWAY_DESC
    assert ld.indoor_prompt(*(ld.INDOOR_VARIANTS[0] + (d,))) == (
        "Wide establishing shot from one end of %s, under its own overhead lights, empty of "
        "people. photorealistic live-action film still, natural light." % d)
    assert ld.indoor_prompt(*(ld.INDOOR_VARIANTS[10] + (d,))) == (
        "Eye-level view looking along the length of %s, in cool white light, empty of people. "
        "photorealistic live-action film still, natural light." % d)
    assert ld.indoor_prompt(*(ld.INDOOR_VARIANTS[23] + (d,))) == (
        "Close-up of a surface texture or sign of %s, under bright even light, empty of people. "
        "photorealistic live-action film still, natural light." % d)


def test_lyd3_an_indoor_text_create(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="nyc-subway", description=SUBWAY_DESC, seed=7)) == 0
    stills = os.path.join(env["locations"], "nyc-subway", "stills")
    ((spec, step),) = fakes.child_specs
    assert step == "generate"
    assert spec["jobs"] == [{"prompt": ld.indoor_prompt(view, light, SUBWAY_DESC),
                             "output_path": os.path.join(stills, "loc_%02d.png" % n),
                             "seed": 7, "width": 1024, "height": 640}
                            for n, (view, light) in enumerate(ld.INDOOR_VARIANTS, start=1)]
    out = capsys.readouterr().out
    line = 'variants: indoor (the description has the word "underground")\n'
    assert line in out
    assert out.index(line) < out.index("=== generate: 24 stills ===")
    assert _manifest(env, "nyc-subway")["variant_set"] == "indoor"
    assert fakes.checks() == [(ld.CHECK_TEXT_PROMPT.replace("@@DESCRIPTION@@", SUBWAY_DESC),
                               ["file:" + os.path.join(stills, "loc_%02d.png" % n)])
                              for n in range(1, 25)]
    _Fakes(monkeypatch)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    assert _manifest(env)["variant_set"] == "outdoor"
    assert not [x for x in capsys.readouterr().out.splitlines() if x.startswith("variants:")]


def test_ly_review_focus_1_a_photo_location_with_an_indoor_description(env, monkeypatch,
                                                                         tmp_path, capsys):
    def _never(description):
        raise AssertionError("photo mode called indoor_word")

    monkeypatch.setattr(ld, "indoor_word", _never)
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="nyc-subway", photos=_photos(tmp_path, 2),
                                  description=SUBWAY_DESC)) == 0
    stills = os.path.join(env["locations"], "nyc-subway", "stills")
    ((spec, step),) = fakes.child_specs
    assert step == "edit"
    assert [job["prompt"] for job in spec["jobs"]] == [
        ld.EDIT_PROMPT % ((ld.EDIT_VIEWS[j - 1],) + ld.EDIT_CONDITIONS[j - 1]) for j in range(1, 23)]
    assert "variants:" not in capsys.readouterr().out
    assert _manifest(env, "nyc-subway")["variant_set"] is None
    assert [urls[0] for _prompt, urls in fakes.checks()[2:]] == [
        "file:" + os.path.join(stills, "loc_%02d.png" % (((n - 3) % 2) + 1)) for n in range(3, 25)]


def test_ly_review_focus_2_regenerate_with_a_new_description_switches_the_variants(
        env, monkeypatch, capsys):
    _Fakes(monkeypatch)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    capsys.readouterr()
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, description=SUBWAY_DESC)) == 0
    assert ('variants: indoor (the description has the word "underground")\n'
            in capsys.readouterr().out)
    assert [job["prompt"] for job in fakes.child_specs[0][0]["jobs"]] == [
        ld.indoor_prompt(view, light, SUBWAY_DESC) for view, light in ld.INDOOR_VARIANTS]
    assert _manifest(env)["variant_set"] == "indoor"
    assert _record(env)["description"] == SUBWAY_DESC
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True, description=lt.HARBOUR_DESC)) == 0
    assert "variants:" not in capsys.readouterr().out
    assert [job["prompt"] for job in fakes.child_specs[0][0]["jobs"]] == [
        ld.gen_prompt(view, time, weather, lt.HARBOUR_DESC)
        for view, time, weather in ld.VARIANTS]
    assert _manifest(env)["variant_set"] == "outdoor"
```

- [ ] **Step 2: Run the file to verify the new and edited tests fail.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py`

Expected: `6 failed, 30 passed`. The failures are:
- `test_ld13_the_manifest`: AssertionError, the manifest has no `variant_set`;
- `test_lyd1_the_indoor_rule`, `test_lyd2_the_indoor_literals`, `test_lyd3_an_indoor_text_create`, `test_ly_review_focus_1_a_photo_location_with_an_indoor_description` and `test_ly_review_focus_2_regenerate_with_a_new_description_switches_the_variants`: AttributeError, because `location_dataset` has no `INDOOR_WORDS`, `INDOOR_VIEWS`, `indoor_prompt` or `indoor_word`.

- [ ] **Step 3: Implement.** Five Edits to `location_dataset.py`, in this order.

**Edit `location_dataset.py`:** LY2, LY3 and LY4, directly after `gen_prompt`. Old text:

```python
def gen_prompt(view, time, weather, description):
    return "%s of %s, %s, %s, empty of people. %s." % (
        view, description, TIME_PHRASES[time], WEATHER_PHRASES[weather], STYLE)
```

New text:

```python
def gen_prompt(view, time, weather, description):
    return "%s of %s, %s, %s, empty of people. %s." % (
        view, description, TIME_PHRASES[time], WEATHER_PHRASES[weather], STYLE)


# Yield spec LY2: a text location is indoors when its description has one of these words.
INDOOR_WORDS = frozenset([
    "atrium", "attic", "auditorium", "basement", "bathroom", "bedroom", "carpet", "carpeted",
    "cellar", "ceiling", "ceilings", "chandelier", "chandeliers", "classroom", "concourse",
    "corridor", "corridors", "crypt", "escalator", "escalators", "foyer", "hallway", "hallways",
    "indoor", "indoors", "interior", "interiors", "lobby", "room", "rooms", "subway", "tunnel",
    "tunnels", "underground", "wallpaper", "wallpapered"])


def indoor_word(description):
    """The first word of description that is in INDOOR_WORDS (yield spec LY3), or None: a
    text location with one is drawn with INDOOR_VARIANTS."""
    for word in location_lib.description_words(description):
        if word in INDOOR_WORDS:
            return word
    return None


# Yield spec LY4: the 24 indoor text-mode stills.
INDOOR_VIEWS = ("Wide establishing shot from one end", "Wide shot from a high corner",
                "Eye-level view looking along the length", "Low-angle view from near the floor",
                "Medium shot of a single detail", "Close-up of a surface texture or sign")
INDOOR_LIGHTS = ("overhead", "dim", "bright", "warm", "cool", "shadow")
INDOOR_LIGHT_PHRASES = {"overhead": "under its own overhead lights", "dim": "in dim low light",
                        "bright": "under bright even light", "warm": "in warm artificial light",
                        "cool": "in cool white light",
                        "shadow": "with deep shadows and pools of light"}
INDOOR_VARIANTS = [
    # (view, light), still n = position; view k (0-based) takes INDOOR_LIGHTS[(k + j) % 6], j 0-3
    ("Wide establishing shot from one end", "overhead"),
    ("Wide establishing shot from one end", "dim"),
    ("Wide establishing shot from one end", "bright"),
    ("Wide establishing shot from one end", "warm"),
    ("Wide shot from a high corner", "dim"),
    ("Wide shot from a high corner", "bright"),
    ("Wide shot from a high corner", "warm"),
    ("Wide shot from a high corner", "cool"),
    ("Eye-level view looking along the length", "bright"),
    ("Eye-level view looking along the length", "warm"),
    ("Eye-level view looking along the length", "cool"),
    ("Eye-level view looking along the length", "shadow"),
    ("Low-angle view from near the floor", "warm"),
    ("Low-angle view from near the floor", "cool"),
    ("Low-angle view from near the floor", "shadow"),
    ("Low-angle view from near the floor", "overhead"),
    ("Medium shot of a single detail", "cool"),
    ("Medium shot of a single detail", "shadow"),
    ("Medium shot of a single detail", "overhead"),
    ("Medium shot of a single detail", "dim"),
    ("Close-up of a surface texture or sign", "shadow"),
    ("Close-up of a surface texture or sign", "overhead"),
    ("Close-up of a surface texture or sign", "dim"),
    ("Close-up of a surface texture or sign", "bright"),
]
INDOOR_PROMPT = "%s of %s, %s, empty of people. %s."


def indoor_prompt(view, light, description):
    return INDOOR_PROMPT % (view, description, INDOOR_LIGHT_PHRASES[light], STYLE)
```

**Edit `location_dataset.py`:** `_plan`'s text branch chooses the set (LY5); the rest of `_plan` is unchanged. Old text:

```python
def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt"}] for the 24 stills, and the image child to run:
    ("generate", spec), ("edit", spec) or (None, None)."""
    if data["source"] == "text":
        plan = [{"n": n, "source": "generated", "photo": None,
                 "prompt": gen_prompt(view, time, weather, data["description"])}
                for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
```

New text:

```python
def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt"}] for the 24 stills, and the image child to run:
    ("generate", spec), ("edit", spec) or (None, None). A text location whose description has
    an indoor word is drawn with INDOOR_VARIANTS (yield spec LY5)."""
    if data["source"] == "text":
        word = indoor_word(data["description"])
        if word is not None:
            plan = [{"n": n, "source": "generated", "photo": None,
                     "prompt": indoor_prompt(view, light, data["description"])}
                    for n, (view, light) in enumerate(INDOOR_VARIANTS, start=1)]
        else:
            plan = [{"n": n, "source": "generated", "photo": None,
                     "prompt": gen_prompt(view, time, weather, data["description"])}
                    for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
```

**Edit `location_dataset.py`:** `photo_mode` and `word` before the render, and the `variants:` line (LY5). Old text:

```python
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    if child == "generate":
```

New text:

```python
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    photo_mode = data["source"] == "photos"
    word = None if photo_mode else indoor_word(data["description"])
    if word is not None:
        print('variants: indoor (the description has the word "%s")' % word)
    if child == "generate":
```

**Edit `location_dataset.py`:** drop the later `photo_mode` line, now set before the render. Old text:

```python
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    photo_mode = data["source"] == "photos"
    manifest = {"source": data["source"], "trigger": data["trigger"],
```

New text:

```python
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    manifest = {"source": data["source"], "trigger": data["trigger"],
```

**Edit `location_dataset.py`:** the manifest gains `"variant_set"` after `"generator"` (LY12, R1). Old text:

```python
                              if child == "edit" else "photos only"),
                "items": items}
```

New text:

```python
                              if child == "edit" else "photos only"),
                "variant_set": None if photo_mode else ("indoor" if word else "outdoor"),
                "items": items}
```

- [ ] **Step 4: Run the location files and the compile check.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_ui.py`

Expected: `53 passed`.

Then run the compile check with `FILES` = `location_dataset.py tests/test_location_dataset.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: Run the gate** with `N=2; NEW=6`. Expected: `GATE PASS`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/locyield-wt/qwen-agent-workspace
git add location_dataset.py tests/test_location_dataset.py
git diff --cached --name-only   # expected: exactly the two paths
git commit -m "feat(location): indoor-aware text-mode variants (yield spec LY2-LY5)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Round labels on the contact sheet and the Locations tab (LY14, LY16; LYD13, LYU1)

This task implements:
- LY14:
  - `write_contact_sheet(items, stills_dir, out_path, rounds=1)` appends `" after %d rounds" % rounds` to the banner when `rounds > 1`;
  - `cell_label` adds ` rN` after the source letter when the item's `round` is an int, not a bool, and greater than 1 (R10).
- LY16: the Locations card figcaption's first element becomes the spec's expression, exactly.

Nothing writes `round` or passes `rounds` until Task 4, so LD14 and every other output is unchanged. New tests: LYD13 and LYU1.

**Files:**
- Modify: `location_dataset.py`: `write_contact_sheet` `:304-313` and `cell_label` `:326-329`.
- Modify: `static/movie-ui/app.js`: `openLocation`'s figcaption, `:2333-2334`.
- Modify: `tests/test_location_dataset.py`: the LY section.
- Modify: `tests/test_location_ui.py`: the end of the file, after `test_lu15` `:425`.

**Interfaces:**
- Consumes: manifest items `{"n", "source", "match_score", "kept", "reason"}`, optionally with `"round"`.
- Produces:
  - `write_contact_sheet(items, stills_dir, out_path, rounds=1)`, which Task 4's `_record` calls with `rounds=len(rounds)`;
  - `cell_label(item) -> str`;
  - LYD13's last two lines, `    assert [text for xy, text in texts if xy == (4, 6)] == [` and `        "kept 13 of 24 (need 12) after 3 rounds", "kept 13 of 24 (need 12)"]`, are Task 4's anchor.

- [ ] **Step 1: Write the failing tests.** Two Edits.

**Edit `tests/test_location_dataset.py`:** append LYD13 after Review Focus 2. Old text:

```python
        for view, time, weather in ld.VARIANTS]
    assert _manifest(env)["variant_set"] == "outdoor"
```

New text:

```python
        for view, time, weather in ld.VARIANTS]
    assert _manifest(env)["variant_set"] == "outdoor"


def test_lyd13_round_labels_and_the_banner(tmp_path, monkeypatch):
    item = {"n": 12, "source": "generated", "match_score": 8, "kept": True, "reason": None,
            "round": 2}
    assert ld.cell_label(item) == "12 G r2 s8 kept"
    for value in (1, None, True):
        assert ld.cell_label(dict(item, round=value)) == "12 G s8 kept", value
    assert ld.cell_label(dict((k, item[k]) for k in item if k != "round")) == "12 G s8 kept"
    stills = tmp_path / "stills"
    stills.mkdir()
    items = [{"n": n, "source": "generated", "match_score": 9 if n <= 13 else 3, "kept": n <= 13,
              "reason": None if n <= 13 else "score 3", "round": 1} for n in range(1, 25)]
    texts = []
    real_text = ld.ImageDraw.ImageDraw.text
    monkeypatch.setattr(ld.ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, **kw: texts.append((xy, text)) or real_text(
                            self, xy, text, **kw))
    ld.write_contact_sheet(items, str(stills), str(tmp_path / "three.jpg"), rounds=3)
    ld.write_contact_sheet(items, str(stills), str(tmp_path / "one.jpg"), rounds=1)
    assert [text for xy, text in texts if xy == (4, 6)] == [
        "kept 13 of 24 (need 12) after 3 rounds", "kept 13 of 24 (need 12)"]
```

**Edit `tests/test_location_ui.py`:** append LYU1 at the end of `tests/test_location_ui.py`. Old text:

```python
    assert lib._rule_locations(dict(base, story_legacy=False)) == []
```

New text:

```python
    assert lib._rule_locations(dict(base, story_legacy=False)) == []


# --- LYU1: a top-up still names its round (docs/superpowers/specs/2026-11-02-location-yield-design.md, LY16)

def test_lyu1_a_top_up_still_names_its_round():
    with open(os.path.join(WS, "static", "movie-ui", "app.js"), encoding="utf-8") as f:
        app = f.read()
    assert app.count('item.source + (typeof item.round === "number" && item.round > 1 ? " (round " '
                     '+ item.round + ")" : "")') == 1
    assert app.count('item.match_score === null ? "score -" : "score " + item.match_score') == 1
```

- [ ] **Step 2: Run the two files to verify the new tests fail.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_ui.py`

Expected: `2 failed, 53 passed`. The failures are:
- `test_lyd13_round_labels_and_the_banner`: AssertionError, `'12 G s8 kept'` vs `'12 G r2 s8 kept'`;
- `test_lyu1_a_top_up_still_names_its_round`: AssertionError, a count of 0.

- [ ] **Step 3: Implement.** Three Edits.

**Edit `location_dataset.py`:** `write_contact_sheet`'s `rounds` parameter and banner (LY14). Old text:

```python
def write_contact_sheet(items, stills_dir, out_path):
    """5 columns of 256x160 thumbnails, each with a 20-px label row, under a 24-px banner; a
    dropped cell is outlined in red, a missing still is a black cell."""
    cols, tw, th, lh, banner = 5, 256, 160, 20, 24
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, banner + rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    kept = sum(1 for item in items if item["kept"])
    draw.text((4, 6), "kept %d of %d (need %d)" % (kept, len(items), location_lib.MIN_KEEP),
              fill=(255, 255, 255))
```

New text:

```python
def write_contact_sheet(items, stills_dir, out_path, rounds=1):
    """5 columns of 256x160 thumbnails, each with a 20-px label row, under a 24-px banner; a
    dropped cell is outlined in red, a missing still is a black cell. After more than one round
    the banner names the round count (yield spec LY14)."""
    cols, tw, th, lh, banner = 5, 256, 160, 20, 24
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, banner + rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    kept = sum(1 for item in items if item["kept"])
    heading = "kept %d of %d (need %d)" % (kept, len(items), location_lib.MIN_KEEP)
    if rounds > 1:
        heading += " after %d rounds" % rounds
    draw.text((4, 6), heading, fill=(255, 255, 255))
```

**Edit `location_dataset.py`:** `cell_label`'s round tag (LY14, R10). Old text:

```python
def cell_label(item):
    score = "s%d" % item["match_score"] if item["match_score"] is not None else "s-"
    verdict = "kept" if item["kept"] else (item["reason"] or "")[:28]
    return "%02d %s %s %s" % (item["n"], item["source"][0].upper(), score, verdict)
```

New text:

```python
def cell_label(item):
    score = "s%d" % item["match_score"] if item["match_score"] is not None else "s-"
    verdict = "kept" if item["kept"] else (item["reason"] or "")[:28]
    round_n = item.get("round")         # absent in a manifest written before the yield spec
    round_text = (" r%d" % round_n if isinstance(round_n, int) and not isinstance(round_n, bool)
                  and round_n > 1 else "")
    return "%02d %s%s %s %s" % (item["n"], item["source"][0].upper(), round_text, score, verdict)
```

**Edit `static/movie-ui/app.js`:** the Locations card's figcaption: its first element becomes the LY16 expression. Old text:

```javascript
      parts.push(el("figcaption", {text: [item.source, item.match_score === null ? "score -" : "score " + item.match_score,
        people, item.caption || "", item.kept ? "kept" : "dropped: " + (item.reason || "")].join("; ")}));
```

New text:

```javascript
      parts.push(el("figcaption", {text: [
        item.source + (typeof item.round === "number" && item.round > 1 ? " (round " + item.round + ")" : ""),
        item.match_score === null ? "score -" : "score " + item.match_score,
        people, item.caption || "", item.kept ? "kept" : "dropped: " + (item.reason || "")].join("; ")}));
```

- [ ] **Step 4: Run the location files, node's syntax check and the compile check.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_ui.py`

Expected: `55 passed`. That includes `test_lu13_the_static_page`, which runs `node --check` when node is installed, and LD14, unedited.

Then run `node --check static/movie-ui/app.js && echo "app.js ok"`. Expected: `app.js ok`.

Then run the compile check with `FILES` = `location_dataset.py tests/test_location_dataset.py tests/test_location_ui.py`. Expected: `compiled 3` twice.

- [ ] **Step 5: Run the gate** with `N=3; NEW=8`. Expected: `GATE PASS`. It also confirms that the page tests in other files (`test_mut24_page_headers_and_asset_rules`, `test_bt13_the_static_page`, `test_ct27_the_static_page`, `test_sdt25_the_static_page`) still pass.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/locyield-wt/qwen-agent-workspace
git add location_dataset.py static/movie-ui/app.js tests/test_location_dataset.py tests/test_location_ui.py
git diff --cached --name-only   # expected: exactly the four paths
git commit -m "feat(location): round labels on the contact sheet and the Locations tab (yield spec LY14, LY16)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Bounded top-up rounds (LY6-LY13, LY15; LYD5-LYD12, Review Focus 3-5)

This task implements:
- LY6 `TOPUP_ROUNDS = 2` and LY7 `topup_seed`, verbatim.
- LY8:
  - `_plan(data, loc_dir)` returns only the plan list. Each entry has `{"n", "source", "photo", "prompt", "seed", "round"}`: `(data["seed"], 1)` for a generated or edit entry, `(None, None)` for a photo.
  - `_child_spec` and `_render`, verbatim apart from `_render`'s added docstring.
  - Round 1's step name is `child`; round r's is `"%s-round%d" % (child, r)`.
- LY9: the round loop, in the spec's order, with the spec's exact lines.
  - Every regenerable still is re-rendered.
  - A round that cannot reach 12 is not run.
  - Each dropped still's file is deleted before it is re-rendered.
- LY10 and LY11 follow from the loop and need no code of their own:
  - a failure keeps the record `_record` last wrote;
  - an interrupt restores detached through the unchanged `_with_story_server_stopped`.
- LY12:
  - `_record` writes the manifest (with `"rounds"`), the contact sheet (`rounds=len(rounds)`) and `location.json` after every round;
  - `_check_entry`'s item gains `"seed"` and `"round"` after `"caption"`.
- LY13: `location.json` is unchanged; old manifests stay readable.
- LY15: the `bin/location` docstring and the module docstring (R12).

Re-baselines:
- `_Fakes` gains `skip_n`, `rounds`, `child_error_at` and `existed` (spec 7.2). The defaults reproduce today's behaviour.
- LD13's `rounds`/`seed`/`round` lines (spec 7.3 row 2, R2).
- LD15's `skip=[21, 22]` becomes `skip_n=[21, 22]` (spec 7.3 row 3).

New tests: LYD5-LYD12 and Review Focus 3-5.

**Files:**
- Modify: `location_dataset.py`:
  - module docstring `:8-9`;
  - constants `:39`;
  - `_plan` (Task 2's version);
  - `_check_entry`'s item literal `:394-396`;
  - before `build_dataset` `:449`;
  - `_build_dataset` (Tasks 1-2's version, from `plan, (child, spec) = _plan(...)` through the first `location_lib.write_location(data)`).
- Modify: `bin/location`: docstring `:22-23`.
- Modify: `tests/test_location_dataset.py`:
  - `_Fakes` `:156-196`;
  - LD13;
  - LD15 `:675`;
  - the LY section after LYD13.

**Interfaces:**
- Consumes:
  - from Task 2: `indoor_word`, `indoor_prompt`, `INDOOR_VARIANTS`;
  - from Task 3: `write_contact_sheet(items, stills_dir, out_path, rounds=1)`;
  - existing: `_with_story_server_stopped(min_gib, work)`, `character_dataset.run_zimage_child(spec, loc_dir, step)` / `run_edit_child(spec, loc_dir, step)`, `GENERATE_MIN_AVAIL_GIB`, `EDIT_MIN_AVAIL_GIB`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`, `location_lib.write_location(data)`.
- Produces:
  - `TOPUP_ROUNDS: int`;
  - `topup_seed(seed, round_n, n) -> int`;
  - `_plan(data, loc_dir) -> [entry]`;
  - `_child_spec(data, loc_dir, entries) -> (child or None, spec or None)`;
  - `_render(child, spec, loc_dir, step) -> None`;
  - `_round_summary(round_n, items, entries) -> {"round", "made", "kept"}`;
  - `_record(data, loc_dir, items, rounds, child, variant_set) -> (kept, sheet)`;
  - the manifest of LY12; items with `"seed"` and `"round"`.
  - Test helpers: `_low(ns)`, `_made(n, seed, score)`, `_in_order(out, lines)`, `_loc(stills, n)`.
  - `_Fakes(..., skip_n=(), rounds=None, child_error_at=None)` with `.existed`.

- [ ] **Step 1: Write the failing tests.** Nine Edits to `tests/test_location_dataset.py`, in this order: the three `_Fakes` edits, the four LD13 edits, LD15, then the new tests.

**Edit `tests/test_location_dataset.py`:** `_Fakes`'s docstring and `__init__` (spec 7.2). Old text:

```python
    gate, and image children that write 1024x640 solid PNGs for their jobs (except the 1-based
    job numbers in skip, which are blocked) or raise child_error. image_data_url is replaced by
    "file:<path>", so a check call names its still."""

    def __init__(self, monkeypatch, replies=None, describe=(), skip=(), child_error=None,
                 missing=(), vlm_up=True):
        self.replies, self.describe = dict(replies or {}), list(describe)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error, self.missing = set(skip), child_error, list(missing)
        self.attempt = 0
```

New text:

```python
    gate, and image children that write 1024x640 solid PNGs for their jobs (except the 1-based
    job numbers in skip, which are blocked) or raise child_error. image_data_url is replaced by
    "file:<path>", so a check call names its still.

    Yield spec 7.2: skip_n blocks still numbers (from a job's output_path) in every child call;
    rounds, a list of replies dicts, answers a check from rounds[min(max(child calls so far, 1),
    len(rounds)) - 1], so the last dict repeats; child_error_at raises child_error only on that
    1-based child call; existed gets, per child call, whether each job's output existed before
    the call."""

    def __init__(self, monkeypatch, replies=None, describe=(), skip=(), child_error=None,
                 missing=(), vlm_up=True, skip_n=(), rounds=None, child_error_at=None):
        self.replies, self.describe = dict(replies or {}), list(describe)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error, self.missing = set(skip), child_error, list(missing)
        self.skip_n, self.rounds, self.child_error_at = set(skip_n), rounds, child_error_at
        self.existed = []
        self.attempt = 0
```

**Edit `tests/test_location_dataset.py`:** a check reply comes from `rounds` when given (spec 7.2). Old text:

```python
            reply = fakes.replies.get(int(re.search(r"loc_(\d+)\.png$", url).group(1)), PASS)
```

New text:

```python
            replies = fakes.replies if fakes.rounds is None else fakes.rounds[
                min(max(len(fakes.child_specs), 1), len(fakes.rounds)) - 1]
            reply = replies.get(int(re.search(r"loc_(\d+)\.png$", url).group(1)), PASS)
```

**Edit `tests/test_location_dataset.py`:** the child records `existed`, honours `child_error_at` and blocks `skip_n` (spec 7.2). Old text:

```python
            fakes.child_specs.append((json.loads(json.dumps(spec)), step))
            if fakes.child_error is not None:
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                if i in fakes.skip:
```

New text:

```python
            fakes.child_specs.append((json.loads(json.dumps(spec)), step))
            fakes.existed.append([os.path.exists(job["output_path"]) for job in spec["jobs"]])
            if fakes.child_error is not None and (
                    fakes.child_error_at is None or fakes.child_error_at == len(fakes.child_specs)):
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                n = int(re.search(r"loc_(\d+)\.png$", job["output_path"]).group(1))
                if i in fakes.skip or n in fakes.skip_n:
```

**Edit `tests/test_location_dataset.py`:** LD13's top-level comparison excludes `"rounds"`; one round, kept 23 (spec 7.3 row 2). Old text:

```python
    assert {k: manifest[k] for k in manifest if k != "items"} == {
        "source": "text", "trigger": "harboplc", "description": lt.HARBOUR_DESC, "seed": 4,
        "min_score": 7, "reference": None, "generator": "Z-Image", "variant_set": "outdoor"}
```

New text:

```python
    assert {k: manifest[k] for k in manifest if k not in ("items", "rounds")} == {
        "source": "text", "trigger": "harboplc", "description": lt.HARBOUR_DESC, "seed": 4,
        "min_score": 7, "reference": None, "generator": "Z-Image", "variant_set": "outdoor"}
    assert [r["round"] for r in manifest["rounds"]] == [1]
    assert manifest["rounds"][0]["kept"] == 23
```

**Edit `tests/test_location_dataset.py`:** LD13's `first` item gains `"seed": 4, "round": 1`. Old text:

```python
                     "caption": ld.caption("harboplc", PASS)}
```

New text:

```python
                     "caption": ld.caption("harboplc", PASS), "seed": 4, "round": 1}
```

**Edit `tests/test_location_dataset.py`:** LD13's `blocked` item gains `"seed": 4, "round": 1`. Old text:

```python
                       "weather": "", "kept": False, "reason": "blocked by the content screen",
                       "caption": None}
```

New text:

```python
                       "weather": "", "kept": False, "reason": "blocked by the content screen",
                       "caption": None, "seed": 4, "round": 1}
```

**Edit `tests/test_location_dataset.py`:** LD13's photo items: seed/round, and the item key order gains `"seed", "round"`. Old text:

```python
        "edit", 1, ld.EDIT_PROMPT % ((ld.EDIT_VIEWS[0],) + ld.EDIT_CONDITIONS[0]), 9)
    assert list(edit) == ["n", "source", "photo", "prompt", "match_score", "people_visible",
                          "shot", "time_of_day", "weather", "kept", "reason", "caption"]
```

New text:

```python
        "edit", 1, ld.EDIT_PROMPT % ((ld.EDIT_VIEWS[0],) + ld.EDIT_CONDITIONS[0]), 9)
    assert (photo["seed"], photo["round"]) == (None, None)
    assert (edit["seed"], edit["round"]) == (0, 1)
    assert list(edit) == ["n", "source", "photo", "prompt", "match_score", "people_visible",
                          "shot", "time_of_day", "weather", "kept", "reason", "caption", "seed",
                          "round"]
```

**Edit `tests/test_location_dataset.py`:** LD15 blocks stills 21 and 22 by still number in every round (spec 7.3 row 3). Old text:

```python
    _Fakes(monkeypatch, replies=replies, skip=[21, 22])
```

New text:

```python
    _Fakes(monkeypatch, replies=replies, skip_n=[21, 22])
```

**Edit `tests/test_location_dataset.py`:** append the helpers, LYD5-LYD12 and Review Focus 3-5 after LYD13. Old text:

```python
    assert [text for xy, text in texts if xy == (4, 6)] == [
        "kept 13 of 24 (need 12) after 3 rounds", "kept 13 of 24 (need 12)"]
```

New text:

```python
    assert [text for xy, text in texts if xy == (4, 6)] == [
        "kept 13 of 24 (need 12) after 3 rounds", "kept 13 of 24 (need 12)"]


def _low(ns):
    """Check replies that score every still n in ns 3, so each is dropped as "score 3"."""
    return dict((n, dict(PASS, match_score=3)) for n in ns)


def _made(n, seed, score):
    """One entry of a manifest round's "made" list, for a still the fakes scored score."""
    return {"n": n, "seed": seed, "match_score": score, "kept": score >= 7,
            "reason": None if score >= 7 else "score %d" % score}


def _in_order(out, lines):
    """True when every line occurs in out, each after the end of the one before it."""
    at = 0
    for line in lines:
        found = out.find(line, at)
        if found < 0:
            return False
        at = found + len(line)
    return True


def _loc(stills, n):
    return os.path.join(stills, "loc_%02d.png" % n)


def test_lyd5_the_top_up_seed():
    assert ld.TOPUP_ROUNDS == 2
    for args, value in (((0, 2, 12), 526042623), ((0, 3, 12), 543898680),
                        ((0, 2, 13), 972079275), ((1, 2, 12), 1141495259),
                        ((7, 2, 21), 1210575679), ((2147483647, 3, 24), 520239272)):
        assert ld.topup_seed(*args) == value, args
    values = [ld.topup_seed(0, r, n) for r in (2, 3) for n in range(1, 25)]
    assert len(set(values)) == 48
    assert all(0 <= v <= 2147483647 for v in values)


def test_lyd6_a_top_up_round_reaches_12(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25)), _low(range(13, 25))])
    inner, seen = character_dataset.run_zimage_child, []

    def _child(spec, loc_dir, step):
        if step == "generate-round2":
            seen.append((len(fakes.checks()), list(fakes.server_calls)))
        return inner(spec, loc_dir, step)

    monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=5)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    stills = os.path.join(ldir, "stills")
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("untrained", 12)
    assert [step for _spec, step in fakes.child_specs] == ["generate", "generate-round2"]
    prompts = [ld.gen_prompt(*(v + (lt.HARBOUR_DESC,))) for v in ld.VARIANTS]
    assert fakes.child_specs[1][0]["jobs"] == [
        {"prompt": prompts[n - 1], "output_path": _loc(stills, n),
         "seed": ld.topup_seed(5, 2, n), "width": 1024, "height": 640} for n in range(12, 25)]
    assert fakes.existed[1] == [False] * 13
    assert fakes.server_calls == ["stop", "restore-wait", "stop", "restore-wait"]
    assert seen == [(24, ["stop", "restore-wait", "stop"])]
    assert [urls for _prompt, urls in fakes.checks()] == (
        [["file:" + _loc(stills, n)] for n in range(1, 25)]
        + [["file:" + _loc(stills, n)] for n in range(12, 25)])
    assert _in_order(capsys.readouterr().out, [
        "=== top-up round 2 of 3: regenerating 13 dropped stills with new seeds (kept 11, need "
        "12) ===\n", "=== generate: 13 stills ===\n", "=== check ===\n",
        "top-up round 2 of 3: kept 12 of 24 (need 12)\n",
        "dataset: 12/24 stills kept (minimum 12) in %s\n" % ldir,
        "next: review the contact sheet, then run bin/location train harbour-street\n"])
    manifest = _manifest(env)
    assert manifest["rounds"] == [
        {"round": 1, "made": [_made(n, 5, 9 if n < 12 else 3) for n in range(1, 25)], "kept": 11},
        {"round": 2, "made": [_made(n, ld.topup_seed(5, 2, n), 9 if n == 12 else 3)
                              for n in range(12, 25)], "kept": 12}]
    items = manifest["items"]
    assert (items[11]["seed"], items[11]["round"], items[11]["kept"]) == (
        ld.topup_seed(5, 2, 12), 2, True)
    assert (items[12]["seed"], items[12]["round"], items[12]["kept"]) == (
        ld.topup_seed(5, 2, 13), 2, False)
    assert (items[0]["seed"], items[0]["round"]) == (5, 1)
    assert sorted(os.listdir(os.path.join(ldir, "captions"))) == [
        "loc_%02d.txt" % n for n in range(1, 13)]


def test_lyd7_the_top_up_is_exhausted(env, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))])
    texts = []
    real_text = ld.ImageDraw.ImageDraw.text
    monkeypatch.setattr(ld.ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, **kw: texts.append((xy, text)) or real_text(
                            self, xy, text, **kw))
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=5)) == 3
    ldir = os.path.join(env["locations"], "harbour-street")
    stills = os.path.join(ldir, "stills")
    assert [step for _spec, step in fakes.child_specs] == [
        "generate", "generate-round2", "generate-round3"]
    assert [(job["output_path"], job["seed"]) for job in fakes.child_specs[2][0]["jobs"]] == [
        (_loc(stills, n), ld.topup_seed(5, 3, n)) for n in range(12, 25)]
    assert fakes.server_calls == ["stop", "restore-wait"] * 3
    assert [r["kept"] for r in _manifest(env)["rounds"]] == [11, 11, 11]
    assert _err_line(capsys) == (
        "Error: only 11/24 stills kept (need 12): 13 score below 7; the dataset is kept in %s; "
        "run bin/location create harbour-street --regenerate --new-seed, or --regenerate "
        "--description TEXT with a clearer description" % ldir)
    assert [text for xy, text in texts if xy == (4, 6)][-1] == (
        "kept 11 of 24 (need 12) after 3 rounds")


def test_lyd8_a_photo_top_up_regenerates_edits_only(env, monkeypatch, tmp_path, capsys):
    paths = _photos(tmp_path, 3)
    people = dict(PASS, people_visible=True)
    first = dict((n, dict(PASS, match_score=5)) for n in range(4, 16))
    first[1] = people
    fakes = _Fakes(monkeypatch, rounds=[first, {1: people}])
    assert ld.create(_create_args(name="old-mill", photos=paths, description=lt.MILL_DESC,
                                  seed=2)) == 0
    stills = os.path.join(env["locations"], "old-mill", "stills")
    manifest = _manifest(env, "old-mill")
    assert [r["kept"] for r in manifest["rounds"]] == [11, 23]
    assert _record(env, "old-mill")["dataset"]["kept"] == 23
    assert len(fakes.child_specs) == 2
    spec, step = fakes.child_specs[1]
    assert (step, spec["skill"], spec["image"]) == ("edit-round2", "location_edit",
                                                    _loc(stills, 1))
    assert spec["jobs"] == [
        {"image": _loc(stills, ((n - 4) % 3) + 1),
         "prompt": ld.EDIT_PROMPT % ((ld.EDIT_VIEWS[n - 4],) + ld.EDIT_CONDITIONS[n - 4]),
         "output_path": _loc(stills, n), "seed": ld.topup_seed(2, 2, n), "width": 1024,
         "height": 640} for n in range(4, 16)]
    assert fakes.checks()[24:] == [
        (ld.CHECK_PHOTO_PROMPT, ["file:" + _loc(stills, ((n - 4) % 3) + 1),
                                 "file:" + _loc(stills, n)]) for n in range(4, 16)]
    photo = manifest["items"][0]
    assert (photo["kept"], photo["round"], photo["seed"]) == (False, None, None)
    capsys.readouterr()
    fakes = _Fakes(monkeypatch, rounds=[first, {1: people}])
    assert ld.create(_create_args(name="dock-one", photos=paths, description=lt.MILL_DESC,
                                  seed=2, force=True)) == 0
    assert len(fakes.child_specs) == 1
    assert "top-up" not in capsys.readouterr().out
    assert _record(env, "dock-one")["dataset"]["kept"] == 12


def test_lyd9_when_no_top_up_round_runs(env, monkeypatch, tmp_path, capsys):
    people = dict(PASS, people_visible=True)
    fakes = _Fakes(monkeypatch, replies=dict((n, people) for n in range(1, 14)))
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 24),
                                  description=lt.MILL_DESC)) == 3
    assert (fakes.child_specs, fakes.server_calls) == ([], [])
    assert _record(env, "old-mill")["dataset"]["kept"] == 11
    assert ("top-up: not run; no generated or edited stills were dropped\n"
            in capsys.readouterr().out)
    replies = dict((n, people) for n in range(1, 15))
    replies.update(_low([21, 22]))
    fakes = _Fakes(monkeypatch, replies=replies)
    assert ld.create(_create_args(name="dock-one", photos=_photos(tmp_path, 20, start=24),
                                  description=lt.MILL_DESC)) == 3
    assert len(fakes.child_specs) == 1
    assert _record(env, "dock-one")["dataset"]["kept"] == 8
    assert ("top-up: not run; 8 kept + 2 dropped generated or edited stills cannot reach 12\n"
            in capsys.readouterr().out)
    _Fakes(monkeypatch, replies=_low(range(21, 25)))
    assert ld.create(_create_args(description="The " + lt.HARBOUR_DESC[2:] + ".", seed=7)) == 0
    out = capsys.readouterr().out
    assert "top-up" not in out and "variants:" not in out
    assert len(_manifest(env)["rounds"]) == 1


def test_lyd10_a_still_blocked_again_in_a_top_up_round(env, monkeypatch):
    fakes = _Fakes(monkeypatch, skip_n=[12], rounds=[_low(range(13, 25)), {}])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    manifest = _manifest(env)
    assert [r["kept"] for r in manifest["rounds"]] == [11, 23]
    item = manifest["items"][11]
    assert (item["kept"], item["reason"], item["round"], item["seed"]) == (
        False, "blocked by the content screen", 2, ld.topup_seed(0, 2, 12))
    assert not os.path.exists(os.path.join(ldir, "stills", "loc_12.png"))
    assert fakes.existed[1] == [False] * 13


def test_lyd11_a_failure_or_interrupt_in_a_top_up_round(env, monkeypatch, capsys):
    error = character_dataset.DatasetError("Z-Image child process exited -9; log: /x/logs/g.log")
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))], child_error=error,
                   child_error_at=2)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore-wait", "stop", "restore-wait"]
    assert _err_line(capsys) == "Error: Z-Image child process exited -9; log: /x/logs/g.log"
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("dataset", 11)
    assert len(_manifest(env)["rounds"]) == 1
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))], child_error=KeyboardInterrupt(),
                   child_error_at=2)
    assert ld.create(_create_args(name="old-mill", description=lt.MILL_DESC)) == 1
    assert fakes.server_calls == ["stop", "restore-wait", "stop", "restore"]
    assert _err_line(capsys) == (
        "Error: aborted; the stills made so far are kept in %s; run bin/location create "
        "old-mill --regenerate to start again" % os.path.join(env["locations"], "old-mill"))


def test_lyd12_top_up_seeds_follow_the_location_seed(env, monkeypatch):
    def _seeds(fakes, k):
        return [job["seed"] for job in fakes.child_specs[k][0]["jobs"]]

    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=5)) == 3
    first = _seeds(fakes, 1)
    assert first == [ld.topup_seed(5, 2, n) for n in range(12, 25)]
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))])
    assert ld.create(_create_args(regenerate=True, new_seed=True)) == 3
    assert _record(env)["seed"] == 6
    assert _seeds(fakes, 0) == [6] * 24
    assert _seeds(fakes, 1) == [ld.topup_seed(6, 2, n) for n in range(12, 25)]
    assert _seeds(fakes, 2) == [ld.topup_seed(6, 3, n) for n in range(12, 25)]
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25))])
    assert ld.create(_create_args(name="dock-one", description=lt.HARBOUR_DESC, seed=5)) == 3
    assert _seeds(fakes, 1) == first


def test_ly_review_focus_3_the_vision_model_fails_in_a_top_up_round(env, monkeypatch, capsys):
    down = RuntimeError("VLM request failed: connection refused")
    fakes = _Fakes(monkeypatch, rounds=[_low(range(12, 25)), dict((n, down) for n in range(12, 25))])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    assert _err_line(capsys) == "Error: VLM request failed: connection refused"
    assert fakes.server_calls == ["stop", "restore-wait"] * 2
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("dataset", 11)
    manifest = _manifest(env)
    assert len(manifest["rounds"]) == 1
    assert [item["round"] for item in manifest["items"]] == [1] * 24
    ldir = os.path.join(env["locations"], "harbour-street")
    assert sorted(os.listdir(os.path.join(ldir, "captions"))) == [
        "loc_%02d.txt" % n for n in range(1, 12)]
    assert sorted(os.listdir(os.path.join(ldir, "videos"))) == [
        "loc_%02d.mp4" % n for n in range(1, 12)]


def test_ly_review_focus_4_regenerate_after_a_failed_top_up_round(env, monkeypatch):
    error = character_dataset.DatasetError("Z-Image child process exited -9; log: /x/logs/g.log")
    _Fakes(monkeypatch, rounds=[_low(range(12, 25))], child_error=error, child_error_at=2)
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 1
    stills = os.path.join(env["locations"], "harbour-street", "stills")
    assert sorted(os.listdir(stills)) == ["loc_%02d.png" % n for n in range(1, 12)]
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(regenerate=True)) == 0
    assert [step for _spec, step in fakes.child_specs] == ["generate"]
    assert len(fakes.child_specs[0][0]["jobs"]) == 24
    manifest = _manifest(env)
    assert [r["round"] for r in manifest["rounds"]] == [1]
    assert [(i["round"], i["seed"], i["kept"]) for i in manifest["items"]] == [(1, 0, True)] * 24
    data = _record(env)
    assert (data["status"], data["dataset"]["kept"]) == ("untrained", 24)
    assert sorted(os.listdir(stills)) == ["loc_%02d.png" % n for n in range(1, 25)]


def test_ly_review_focus_5_a_still_kept_in_a_top_up_round_is_trained(env, monkeypatch):
    _Fakes(monkeypatch, rounds=[_low(range(12, 25)), _low(range(13, 25))])
    assert ld.create(_create_args(description=lt.HARBOUR_DESC, seed=5)) == 0
    ldir = os.path.join(env["locations"], "harbour-street")
    assert sorted(os.listdir(os.path.join(ldir, "videos"))) == [
        "loc_%02d.mp4" % n for n in range(1, 13)]
    with open(os.path.join(ldir, "captions", "loc_12.txt"), encoding="utf-8") as f:
        assert f.read() == _manifest(env)["items"][11]["caption"]
    pairs = []
    monkeypatch.setattr(character_dataset, "train_stills_lora",
                        lambda loc_dir, p, prompt, seed, kept_ok, skipped: pairs.extend(p) or "ok")
    assert ld._train_stills(_record(env)) == "ok"
    assert pairs == [(os.path.join(ldir, "stills", "loc_%02d.png" % n),
                      os.path.join(ldir, "captions", "loc_%02d.txt" % n)) for n in range(1, 13)]
```

- [ ] **Step 2: Run the file to verify the new and edited tests fail.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py`

Expected: `12 failed, 36 passed`. The failures are:
- `test_ld13_the_manifest`: KeyError, `'rounds'`;
- `test_lyd5_the_top_up_seed`: AttributeError, no `TOPUP_ROUNDS`;
- `test_lyd6_...`, `test_lyd7_...`, `test_lyd8_...`, `test_lyd9_...`, `test_lyd10_...`, `test_lyd11_...` and `test_lyd12_...`: no top-up round runs, or the manifest has no `rounds`;
- `test_ly_review_focus_3_...`, `test_ly_review_focus_4_...` and `test_ly_review_focus_5_...`: the same.

LD15 passes, because `skip_n` blocks by still number and round 1's job index equals its still number. Every other existing test passes, because the `_Fakes` defaults reproduce today's behaviour.

- [ ] **Step 3: Implement.** Seven Edits, in this order: six to `location_dataset.py`, then `bin/location`.

**Edit `location_dataset.py`:** the module docstring (LY15, R12). Old text:

```python
The vision model checks every still; the kept ones get a trigger-led caption and a 1-frame mp4. Training reuses
character_dataset.train_video_lora and train_stills_lora.
```

New text:

```python
The vision model checks every still; the kept ones get a trigger-led caption and a 1-frame mp4.
When fewer than 12 are kept, the dropped generated or edited stills are regenerated with new seeds
for up to 2 more rounds (docs/superpowers/specs/2026-11-02-location-yield-design.md). Training
reuses character_dataset.train_video_lora and train_stills_lora.
```

**Edit `location_dataset.py`:** `TOPUP_ROUNDS` after `DESCRIBE_PHOTOS` (LY6). Old text:

```python
DESCRIBE_PHOTOS = 5
```

New text:

```python
DESCRIBE_PHOTOS = 5
TOPUP_ROUNDS = 2                        # yield spec LY6: rounds 2 and 3 regenerate dropped stills
```

**Edit `location_dataset.py`:** replace Task 2's `_plan` with `topup_seed`, the entries-only `_plan`, `_child_spec` and `_render` (LY7, LY8). Old text:

```python
def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt"}] for the 24 stills, and the image child to run:
    ("generate", spec), ("edit", spec) or (None, None). A text location whose description has
    an indoor word is drawn with INDOOR_VARIANTS (yield spec LY5)."""
    if data["source"] == "text":
        word = indoor_word(data["description"])
        if word is not None:
            plan = [{"n": n, "source": "generated", "photo": None,
                     "prompt": indoor_prompt(view, light, data["description"])}
                    for n, (view, light) in enumerate(INDOOR_VARIANTS, start=1)]
        else:
            plan = [{"n": n, "source": "generated", "photo": None,
                     "prompt": gen_prompt(view, time, weather, data["description"])}
                    for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
        jobs = [{"prompt": e["prompt"], "output_path": still_path(loc_dir, e["n"]),
                 "seed": data["seed"], "width": WIDTH, "height": HEIGHT} for e in plan]
        return plan, ("generate", {"jobs": jobs, "loras": None})
    p = len(data["photos"])
    plan = [{"n": k, "source": "photo", "photo": k, "prompt": None} for k in range(1, p + 1)]
    for j in range(1, location_lib.TOTAL_STILLS - p + 1):
        plan.append({"n": p + j, "source": "edit", "photo": ((j - 1) % p) + 1,
                     "prompt": EDIT_PROMPT % ((EDIT_VIEWS[j - 1],) + EDIT_CONDITIONS[j - 1])})
    edits = [e for e in plan if e["source"] == "edit"]
    if not edits:
        return plan, (None, None)
    jobs = [{"image": still_path(loc_dir, e["photo"]), "prompt": e["prompt"],
             "output_path": still_path(loc_dir, e["n"]), "seed": data["seed"], "width": WIDTH,
             "height": HEIGHT} for e in edits]
    spec = {"image": jobs[0]["image"], "skill": "location_edit",
            "model": character_dataset.EDIT_MODEL, "lora_repo": character_dataset.EDIT_LORA_REPO,
            "lora_file": character_dataset.EDIT_LORA_FILE, "steps": character_dataset.EDIT_STEPS,
            "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}
    return plan, ("edit", spec)
```

New text:

```python
def topup_seed(seed, round_n, n):
    """The seed of still n in top-up round round_n (yield spec LY7): deterministic from the
    location seed, the round and the still, in 0..SEED_MAX."""
    digest = hashlib.sha256(("location-topup:%d:%d:%d" % (seed, round_n, n)).encode("ascii"))
    return int(digest.hexdigest()[:8], 16) & SEED_MAX


def _plan(data, loc_dir):
    """[{"n", "source", "photo", "prompt", "seed", "round"}] for the 24 stills (yield spec LY8):
    a generated or edit entry starts at round 1 with the location seed, a photo entry has seed
    and round None. A text location whose description has an indoor word is drawn with
    INDOOR_VARIANTS (yield spec LY5)."""
    seed = data["seed"]
    if data["source"] == "text":
        word = indoor_word(data["description"])
        if word is not None:
            return [{"n": n, "source": "generated", "photo": None,
                     "prompt": indoor_prompt(view, light, data["description"]), "seed": seed,
                     "round": 1}
                    for n, (view, light) in enumerate(INDOOR_VARIANTS, start=1)]
        return [{"n": n, "source": "generated", "photo": None,
                 "prompt": gen_prompt(view, time, weather, data["description"]), "seed": seed,
                 "round": 1}
                for n, (view, time, weather) in enumerate(VARIANTS, start=1)]
    p = len(data["photos"])
    plan = [{"n": k, "source": "photo", "photo": k, "prompt": None, "seed": None, "round": None}
            for k in range(1, p + 1)]
    for j in range(1, location_lib.TOTAL_STILLS - p + 1):
        plan.append({"n": p + j, "source": "edit", "photo": ((j - 1) % p) + 1,
                     "prompt": EDIT_PROMPT % ((EDIT_VIEWS[j - 1],) + EDIT_CONDITIONS[j - 1]),
                     "seed": seed, "round": 1})
    return plan


def _child_spec(data, loc_dir, entries):
    """("generate", spec), ("edit", spec) or (None, None) for the image jobs of entries."""
    if not entries:
        return None, None
    if data["source"] == "text":
        jobs = [{"prompt": e["prompt"], "output_path": still_path(loc_dir, e["n"]),
                 "seed": e["seed"], "width": WIDTH, "height": HEIGHT} for e in entries]
        return "generate", {"jobs": jobs, "loras": None}
    jobs = [{"image": still_path(loc_dir, e["photo"]), "prompt": e["prompt"],
             "output_path": still_path(loc_dir, e["n"]), "seed": e["seed"], "width": WIDTH,
             "height": HEIGHT} for e in entries]
    return "edit", {"image": jobs[0]["image"], "skill": "location_edit",
                    "model": character_dataset.EDIT_MODEL,
                    "lora_repo": character_dataset.EDIT_LORA_REPO,
                    "lora_file": character_dataset.EDIT_LORA_FILE,
                    "steps": character_dataset.EDIT_STEPS,
                    "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}


def _render(child, spec, loc_dir, step):
    """Run one round's image child with the story server stopped (yield spec LY8, LY11)."""
    print("=== %s: %d stills ===" % (child, len(spec["jobs"])), flush=True)
    if child == "generate":
        _with_story_server_stopped(character_dataset.GENERATE_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_zimage_child(spec, loc_dir, step)))
    else:
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, step)))
```

**Edit `location_dataset.py`:** `_check_entry`'s item literal gains `"seed"` and `"round"` after `"caption"` (LY12). Old text:

```python
            "time_of_day": "", "weather": "", "kept": False, "reason": None, "caption": None}
```

New text:

```python
            "time_of_day": "", "weather": "", "kept": False, "reason": None, "caption": None,
            "seed": entry["seed"], "round": entry["round"]}
```

**Edit `location_dataset.py`:** `_round_summary` and `_record` before `build_dataset` (LY9, LY12). Old text:

```python
def build_dataset(data, force=False):
```

New text:

```python
def _round_summary(round_n, items, entries):
    """The manifest's record of one round (yield spec LY9): each still it made, with its seed,
    score and verdict, in n order, and the kept count over all 24 stills after it."""
    made = []
    for e in entries:
        item = items[e["n"] - 1]
        made.append({"n": item["n"], "seed": item["seed"], "match_score": item["match_score"],
                     "kept": item["kept"], "reason": item["reason"]})
    return {"round": round_n, "made": made, "kept": sum(1 for item in items if item["kept"])}


def _record(data, loc_dir, items, rounds, child, variant_set):
    """Write manifest.json, contact_sheet.jpg and location.json for items after a round
    (yield spec LY12); return (kept, contact sheet path)."""
    photo_mode = data["source"] == "photos"
    manifest = {"source": data["source"], "trigger": data["trigger"],
                "description": data["description"], "seed": data["seed"],
                "min_score": location_lib.MIN_SCORE,
                "reference": "source photo" if photo_mode else None,
                "generator": ("Z-Image" if not photo_mode
                              else "%s + %s, %d steps" % (character_dataset.EDIT_MODEL,
                                                          character_dataset.EDIT_LORA_FILE,
                                                          character_dataset.EDIT_STEPS)
                              if child == "edit" else "photos only"),
                "variant_set": variant_set, "rounds": rounds, "items": items}
    with open(os.path.join(loc_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(loc_dir, "contact_sheet.jpg")
    write_contact_sheet(items, os.path.join(loc_dir, "stills"), sheet, rounds=len(rounds))
    kept = sum(1 for item in items if item["kept"])
    data["dataset"] = {"kept": kept, "total": location_lib.TOTAL_STILLS,
                       "min_score": location_lib.MIN_SCORE, "contact_sheet": sheet}
    data["status"] = "untrained" if kept >= location_lib.MIN_KEEP else "dataset"
    location_lib.write_location(data)
    return kept, sheet


def build_dataset(data, force=False):
```

**Edit `location_dataset.py`:** `_build_dataset` from `plan = ...` through the round loop (LY9); its first three lines and its table/`next:` tail stay. Old text:

```python
    plan, (child, spec) = _plan(data, loc_dir)
    for k in range(1, len(data["photos"]) + 1):
        with Image.open(photo_copy_path(loc_dir, k)) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    photo_mode = data["source"] == "photos"
    word = None if photo_mode else indoor_word(data["description"])
    if word is not None:
        print('variants: indoor (the description has the word "%s")' % word)
    if child == "generate":
        print("=== generate: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.GENERATE_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_zimage_child(spec, loc_dir, "generate")))
    elif child == "edit":
        print("=== edit: %d stills ===" % len(spec["jobs"]), flush=True)
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, "edit")))

    print("=== check ===", flush=True)
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    manifest = {"source": data["source"], "trigger": data["trigger"],
                "description": data["description"], "seed": data["seed"],
                "min_score": location_lib.MIN_SCORE,
                "reference": "source photo" if photo_mode else None,
                "generator": ("Z-Image" if not photo_mode
                              else "%s + %s, %d steps" % (character_dataset.EDIT_MODEL,
                                                          character_dataset.EDIT_LORA_FILE,
                                                          character_dataset.EDIT_STEPS)
                              if child == "edit" else "photos only"),
                "variant_set": None if photo_mode else ("indoor" if word else "outdoor"),
                "items": items}
    with open(os.path.join(loc_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(loc_dir, "contact_sheet.jpg")
    write_contact_sheet(items, os.path.join(loc_dir, "stills"), sheet)

    kept = sum(1 for item in items if item["kept"])
    data["dataset"] = {"kept": kept, "total": location_lib.TOTAL_STILLS,
                       "min_score": location_lib.MIN_SCORE, "contact_sheet": sheet}
    data["status"] = "untrained" if kept >= location_lib.MIN_KEEP else "dataset"
    location_lib.write_location(data)
```

New text:

```python
    plan = _plan(data, loc_dir)
    for k in range(1, len(data["photos"]) + 1):
        with Image.open(photo_copy_path(loc_dir, k)) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(still_path(loc_dir, k))
    photo_mode = data["source"] == "photos"
    word = None if photo_mode else indoor_word(data["description"])
    variant_set = None if photo_mode else ("indoor" if word else "outdoor")
    if word is not None:
        print('variants: indoor (the description has the word "%s")' % word)
    # Round 1 (yield spec LY9 step 3): every generated or edit still, with the location seed.
    made = [e for e in plan if e["source"] != "photo"]
    child, spec = _child_spec(data, loc_dir, made)
    if child is not None:
        _render(child, spec, loc_dir, child)
    generator_child = child

    print("=== check ===", flush=True)
    items = [_check_entry(data, loc_dir, entry, force) for entry in plan]
    rounds = [_round_summary(1, items, made)]
    kept, sheet = _record(data, loc_dir, items, rounds, generator_child, variant_set)
    # Top-up rounds (yield spec LY9 step 6): regenerate every dropped generated or edit still.
    for r in range(2, 2 + TOPUP_ROUNDS):
        if kept >= location_lib.MIN_KEEP:
            break
        redo = [plan[k] for k, item in enumerate(items)
                if not item["kept"] and item["source"] != "photo"]
        if not redo:
            print("top-up: not run; no generated or edited stills were dropped")
            break
        if kept + len(redo) < location_lib.MIN_KEEP:
            print("top-up: not run; %d kept + %d dropped generated or edited stills cannot reach %d"
                  % (kept, len(redo), location_lib.MIN_KEEP))
            break
        print("=== top-up round %d of %d: regenerating %d dropped stills with new seeds (kept %d, "
              "need %d) ===" % (r, 1 + TOPUP_ROUNDS, len(redo), kept, location_lib.MIN_KEEP),
              flush=True)
        for e in redo:
            e["seed"] = topup_seed(data["seed"], r, e["n"])
            e["round"] = r
            # A blocked job writes no file, so the old dropped image must not be re-scored.
            with contextlib.suppress(FileNotFoundError):
                os.remove(still_path(loc_dir, e["n"]))
        child, spec = _child_spec(data, loc_dir, redo)
        _render(child, spec, loc_dir, "%s-round%d" % (child, r))
        print("=== check ===", flush=True)
        for e in redo:
            items[e["n"] - 1] = _check_entry(data, loc_dir, e, force)
        rounds.append(_round_summary(r, items, redo))
        kept, sheet = _record(data, loc_dir, items, rounds, generator_child, variant_set)
        print("top-up round %d of %d: kept %d of %d (need %d)"
              % (r, 1 + TOPUP_ROUNDS, kept, location_lib.TOTAL_STILLS, location_lib.MIN_KEEP))
```

**Edit `bin/location`:** `bin/location`'s exit-code paragraph (LY15). Old text:

```python
Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 create kept fewer
than 12 stills.
```

New text:

```python
Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 create kept fewer
than 12 stills. When fewer than 12 are kept, create regenerates the dropped generated or edited
stills (never your photos) with new seeds, for up to 2 more rounds.
```

After these Edits, `_build_dataset` reads, from `photo_mode = ...` to the end:
1. the `variants:` line;
2. round 1;
3. `=== check ===` and the round-1 checks;
4. `_record`;
5. the top-up loop;
6. the unchanged table, `dataset:`, `contact sheet:`, too-few/`next:` block, which uses `kept`, `sheet`, `items`, `photo_mode`, `name` and `loc_dir`.

`_plan`'s `loc_dir` parameter is unused now. It stays, because LY8 keeps the signature `_plan(data, loc_dir)`.

- [ ] **Step 4: Run the location files and the compile check.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_ui.py tests/test_location_tool.py tests/test_location_lib.py tests/test_location_story.py tests/test_location_golden.py tests/test_location_pipeline.py`

Expected: no failures. The first two files give `66 passed`. `test_location_tool.py` covers LT1 (`--help`, unchanged argparse text) and LT8 (SIGTERM, 130). `test_location_lib.py::test_ll1_every_new_and_changed_file_compiles` compiles `location_dataset.py` and `bin/location` on both Pythons.

Then run the compile check with `FILES` = `location_dataset.py bin/location tests/test_location_dataset.py`. Expected: `compiled 3` twice.

- [ ] **Step 5: Run the gate** with `N=4; NEW=19`. Expected: `GATE PASS`, including `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (LYK7).

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/locyield-wt/qwen-agent-workspace
git add location_dataset.py bin/location tests/test_location_dataset.py
git diff --cached --name-only   # expected: exactly the three paths
git commit -m "feat(location): bounded top-up rounds regenerate dropped stills (yield spec LY6-LY13, LY15)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification (controller; after Task 4)

- [ ] **V1. The pass bar (LYK1, LYK7).**
  - Task 4's gate output is the final one: `GATE PASS`, `P0 + 19` passes, the 2 known failures and `OK 347/347`.
  - `git -C .. diff --quiet b029c2b -- qwen-agent-workspace/character_dataset.py qwen-agent-workspace/location_lib.py qwen-agent-workspace/movie_ui_server.py qwen-agent-workspace/movie_ui_lib.py qwen-agent-workspace/static/movie-ui/index.html && echo untouched` prints `untouched`.
  - `git -C .. diff --name-only b029c2b HEAD` lists exactly the plan file, `qwen-agent-workspace/location_dataset.py`, `qwen-agent-workspace/bin/location`, `qwen-agent-workspace/static/movie-ui/app.js`, `qwen-agent-workspace/tests/test_location_dataset.py` and `qwen-agent-workspace/tests/test_location_ui.py`.
- [ ] **V2. An Opus design review** of `git diff b029c2b HEAD` against the spec, before the work is declared done (house rule).
- [ ] **V3. The live check (spec Section 8, LYK8)** is the user's. It runs on the macstudio host after the user pushes `location-yield`. No agent runs it, pushes, or touches macstudio. Until the user reports it, record it as not run.

## Self-review

**Spec coverage.**

| Spec item | Task | Pinned by |
|---|---|---|
| LY1 own-source scoring | 1 (round 1); 4 (top-up rounds reuse `_check_entry`) | LD9, LYD4, LYD8, RF1 |
| LY2, LY3 indoor rule | 2 | LYD1, RF1 |
| LY4 indoor variants | 2 | LYD2, LYD3 |
| LY5 set choice, `variants:` line | 2 (moved into the new `_build_dataset` in 4) | LYD3, LYD9(c), RF2 |
| LY6, LY7 constant and seed | 4 | LYD5, LYD6, LYD12 |
| LY8 `_plan`, `_child_spec`, `_render`, step names | 4 | LD5, LD9 (unchanged round-1 spec), LYD6-LYD8 |
| LY9 the loop, its lines, delete before render | 4 | LYD6-LYD10 |
| LY10 flag interactions | 4 | LYD8 (`--force`), LYD12 (`--new-seed`), RF4 (`--regenerate`), LD24 |
| LY11 VLM lifecycle, failure, interrupt | 4 | LYD6 (`server_calls`), LYD11, RF3 |
| LY12 `_record`, manifest keys, item keys | 1 (`reference`), 2 (`variant_set`), 4 (the rest) | LD13, LYD4, LYD6, LYD7 |
| LY13 compatibility | 3, 4 | LYD13 (no `round` key), RF5 (`_train_stills` reads only `n`/`kept`), LD19-LD23 unchanged |
| LY14 banner and cell tag | 3 (code), 4 (`rounds=` passed) | LYD13, LYD7, LD14 |
| LY15 docstrings | 4 | LT1 (help unchanged), LYD1/LL1 (compile) |
| LY16 app.js | 3 | LYU1, LU13 (node --check) |
| 7.2 `_Fakes` | 4 | every LYD6-LYD12 test |
| 7.3 LD9, LD13, LD15 | 1; 1, 2, 4; 4 | the edited tests themselves |
| LYK1 | every gate | `gate.py` |
| LYK2 outdoor byte-identity | 2, 3, 4 | LD1, LD5, LD14 (unedited), LYD9(c) |
| LYK3 | 2 | LYD1 |
| LYK4 | 4 | LYD6-LYD11 |
| LYK5 | 1, 4 | LD9, LYD4, LYD8 |
| LYK6 | 1-4 | LYD1, the compile check |
| LYK7 | every gate | `test_mut26`, the `git diff --quiet` line |
| LYK8 live | user | Verification V3 |

**Placeholder scan.** Every step has its literal Edit text or command. No step says "similar to", "TBD" or "add tests".

**Type consistency.** These names are spelled the same in every task:
- `indoor_word`, `indoor_prompt`, `INDOOR_VARIANTS`, `topup_seed`, `_child_spec`, `_render`, `_round_summary`, `_record`;
- `rounds=` in `write_contact_sheet`;
- `skip_n`, `rounds`, `child_error_at` and `existed` in `_Fakes`.

`_plan` returns `(plan, (child, spec))` in Tasks 1-3 and `plan` from Task 4 on. Task 4's `t4-build` Edit changes the one caller, `_build_dataset`, in the same Edit sequence. No other caller exists: at `b029c2b`, `location_dataset._plan` is called only by `_build_dataset` (`:468`), and no test calls it.

**Review Focus.** There are five lines, each with its test in the owning task: RF1 and RF2 in Task 2, RF3-RF5 in Task 4.

## Execution handoff

**Replay.** This plan was replayed on a scratch copy of `b029c2b`, the whole repository (`git archive b029c2b`). For each task, its test Edits and then its source Edits were applied in order, and every old text occurred exactly once at its turn. The two-file results (`tests/test_location_dataset.py` plus `tests/test_location_ui.py`) were:

| Task | After the test Edits | After the code Edits |
|---|---|---|
| 1 | 4 failed, 44 passed | 48 passed |
| 2 | 6 failed, 47 passed | 53 passed |
| 3 | 2 failed, 53 passed | 55 passed |
| 4 | 12 failed, 54 passed | 66 passed |

**Full suite in the replay.** `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider` was run on an unmodified `git archive b029c2b` copy and on the replayed final tree.
- Unmodified copy: `2 failed, 2449 passed, 8 skipped`.
- Final tree: `2 failed, 2468 passed, 8 skipped`.
- Both fail exactly `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`. No baseline pass was lost, and the 19 new test IDs all pass (2449 + 19 = 2468).
- `tests/test_ltx_movie_offline.py` printed `OK 347/347` on the final tree.
- Both Pythons compiled `location_dataset.py`, `bin/location` and the two test files, and `node --check static/movie-ui/app.js` passed.

The executor's own baseline (Before Task 1) is the authority for `P0`.

**Not run in the replay:** a real server, model, render or network, and the live check.

**Execution method.** Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-02-location-yield.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven:** a fresh Sonnet `code-executor` implements each task in `$S/locyield-wt` on branch `location-yield`, and a fresh Opus reviewer checks it before the next task starts. A whole-branch review follows at the end.
- **Native:** one session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend **subagent-driven**, for two reasons:
- The house rules require code to be typed by the Sonnet `code-executor` and reviewed by Opus before each unit is declared complete.
- Task 4's old texts are Tasks 1-3's exact output, so a drift in an earlier task is caught at its own gate, not as a stop in Task 4.

Does the plan capture what you want, and which approach should we use?
