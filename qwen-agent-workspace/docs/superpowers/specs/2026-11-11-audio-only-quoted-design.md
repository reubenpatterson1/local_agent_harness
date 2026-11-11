# Audio only quoted: the audio sentence of a chained or shots speech movie's video prompt says that only the quoted words are spoken, and a silent panel's says that nobody speaks

Date: 2026-11-11

Status: design spec and implementation plan in one document.

**The user's problem (confirmed):** LTX sometimes voices words of the video prompt that are not in double quotes (for example the catalog LoRA trigger words that `bin/ltx-story-manifest` prefixes to the prompt), and sometimes repeats a line. Nothing in the prompt tells the model that only the quoted words are speech.

**The user's decision ("option A"):** change the two fixed audio sentences so that the speaking one says only the quoted words are spoken, and the silent one says nobody speaks. No other prompt text changes.

Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Worktree `$S/as-wt`, branch `audio-only-quoted`, off `0338c92` (the lora-scope merge). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `$S/as-wt/qwen-agent-workspace`. Every path is relative to `WS`. Line numbers cite `0338c92`.
- Nothing outside the worktree is touched. Nobody but the user accesses macstudio.

**IDs.** Requirements **AQ1-AQ4**, tests **AOQ1-AOQ6**, KPIs **AQK1-AQK3**, live checks **L1-L2** (live-check ids only; not the lora_checks violations L1-L8). At `0338c92`, `git grep -nE "\bAQ[0-9]+\b|\bAOQ[0-9]+\b|\bAQK[0-9]+\b"` finds nothing.

---

## 0. Scope

### 0.1 What happens today (verified at `0338c92`)

- `character_lib.ACOUSTIC_SENTENCE` (`character_lib.py:792-793`) is `The audio is clear close-mic dialogue with a subtle natural room tone; the dialogue takes priority over the quiet ambience, and there is no music.` (146 characters).
- `character_lib.AMBIENCE_SENTENCE` (`character_lib.py:879`) is `The audio is the natural ambient sound of the place, with no music.` (67 characters).
- `panel_prompt` (`:906-918`) ends a chained or shots speech-movie panel with ACOUSTIC_SENTENCE when it speaks and AMBIENCE_SENTENCE when it is silent, under `beats` delivery only; `plain` and `beats-no-acoustic` add no audio sentence. `speech_text(..., "beats")` (`:874`) appends ACOUSTIC_SENTENCE.
- `bin/ltx-story-manifest:866-875`: every speaking panel outside chained/shots (the `--no-stills`/`--no-images` path and the stills path without `--chain`/`--shots`) appends `lib_.ACOUSTIC_SENTENCE` under `beats`; its silent panels get no audio sentence. Catalog triggers are prefixed afterwards (`:969-971`, `lora_catalog.prefix_triggers`), unquoted.
- `story_engine.FORMAT_REFERENCE` (`story_engine.py:2901-2944`) embeds ACOUSTIC_SENTENCE once (shot 2, `:2931-2933`) and AMBIENCE_SENTENCE twice (shot 1 `:2920`, shot 3 `:2942-2943`). It is shown only to the chained and shots writer (`build_panel_prompt`, `@@FORMAT_REFERENCE@@`, `:4352`); each "Shot N" text must equal `panel_prompt` of its parts byte for byte (CT14, SFT13).

### 0.2 Grounding: the pins (found with `grep -rIl "close-mic\|room tone\|quiet ambience\|ambient sound\|no music" . | grep -v /.git/` and `grep -rn "fec731a3\|3538" tests/`)

| File | Lines | What it pins | Change |
|---|---|---|---|
| `tests/test_chained_end_frames.py` | 1128-1130 | CT14: sha256 of FORMAT_REFERENCE and `(3538, 618)` | new sha and lengths (E6) |
| `tests/test_chained_end_frames.py` | 1131, 1150-1151 | quote list; counts via `lib.*_SENTENCE` | none: no new double quote; counts follow the constants |
| `tests/test_shot_format.py` | 488, 509, 641 | `FORMAT_REFERENCE_SHA256`, `(3538, 618)`, SFT21 `== 3538` | new sha and lengths (E7) |
| `tests/test_shot_format.py` | 642 | SFT21 `len(full) < 9000` | none: measured 7804 today, 7899 after (+95) |
| `tests/test_shot_format.py` | 1344-1346 | its own copies of both sentences | new literals (E8) |
| `tests/test_shot_format.py` | 1350-1353, 1387, 1448-1465 | use the module copies | none |
| `tests/test_dialogue.py` | 41-42 | `AC` literal | new literal (E9) |
| `tests/test_dialogue.py` | 109 and every `+ AC` | use `AC` | none |
| `tests/test_writer_pacing.py` | 364-379 | WT8 `COMPOSED` uses `dlg.AC` | none |
| `tests/fixtures/writer_pacing/hockey-*/manifest.json` | 22, 38 | recorded 2026-10-26 runs; they hold an older sentence without `and there is no music`, and no test reads their `motion_prompt` (WT8 reads only the panel count) | **none** [spec choice]: recorded history stays verbatim |
| `docs/superpowers/{specs,plans}/2026-10-2*`, `2026-10-30*` | - | historical specs and plans; no test reads them | none |
| `bin/ltx-story-manifest` | 875 | appends `lib_.ACOUSTIC_SENTENCE` | **none**: it follows the constant |
| `tests/test_movie_ui_builder.py` | 291-293 | test_mut26 BASELINE over `PIPELINE_FILES` (includes `character_lib.py`, `story_engine.py`) | Task 2 |

**Plan and critic prompts (RS7, RST8, RST47, deploy gate X2).** Neither sentence is in any plan or critic prompt: the plan prompt uses `PLAN_REFERENCE`, which has no audio sentence, and `FORMAT_REFERENCE` reaches only the writer prompt. `grep -rIl "ambient sound\|close-mic" tests/fixtures` finds only the two recorded manifests (the plan-prompt fixtures `tests/fixtures/location/plan_prompt_chained*.txt` and `tests/fixtures/pinned_cast/*` do not contain them). Both new sentences contain no `{`, `}` or `"`, so no brace or quote check can change. No edit.

### 0.3 Deliverables

| # | File | Pinned by mut26 | Task | Change |
|---|---|---|---|---|
| D1 | `character_lib.py` | yes | 1 | E1, E2 |
| D2 | `story_engine.py` | yes | 1 | E3-E5 (FORMAT_REFERENCE) |
| D3 | `tests/test_chained_end_frames.py` | no | 1 | E6 |
| D4 | `tests/test_shot_format.py` | no | 1 | E7, E8 |
| D5 | `tests/test_dialogue.py` | no | 1 | E9 |
| D6 | `tests/test_audio_only_quoted.py` | no | 1 | new, AOQ1-AOQ6 |
| D7 | `tests/test_movie_ui_builder.py` | no | 2 | BASELINE move |

### 0.4 Out of scope

- An audio sentence on a silent panel outside chained/shots (`--no-stills` and plain stills runs): they stay without one (AOQ6 pins this).
- Quoting, moving or removing trigger prefixes; the negative prompt; `plain` and `beats-no-acoustic` deliveries (unchanged, AOQ4).
- Re-recording the hockey fixtures; editing historical docs.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| AQK1 | The full gate has no failure beyond its baseline; after Task 2 the gate line is `lost 0 (listed 0, unexpected 0); new tests 6, not passing 0` and `GATE PASS` | gate (orchestrator) |
| AQK2 | `git diff --numstat 0338c92 HEAD` lists exactly D1-D7 with `3 1 character_lib.py`, `5 4 story_engine.py`, `2 2 tests/test_chained_end_frames.py`, `6 4 tests/test_shot_format.py`, `3 2 tests/test_dialogue.py`, `2 2 tests/test_movie_ui_builder.py` and the new file | Task 1 Step 3, Task 2 |
| AQK3 | On macstudio, the new sentences cut "repeated line" plus "voiced extra words" incidents by at least half against the old sentences, with no more missing lines | L2 (the user) |

All AQ requirements and AOQ tests are must-haves. There are no nice-to-haves.

---

## 1. Decisions and requirements

- **AQ1 (the speaking sentence) [spec choice].** `ACOUSTIC_SENTENCE` becomes exactly
  `The audio is clear close-mic dialogue with a subtle natural room tone; only the quoted words are spoken, and only once; the dialogue takes priority over the quiet ambience, and there is no music.` (195 characters, +49). `and only once` targets the repeated line; the rest of today's sentence is kept word for word.
- **AQ2 (the silent sentence) [spec choice].** `AMBIENCE_SENTENCE` becomes exactly
  `The audio is the natural ambient sound of the place; nobody speaks, and there is no music.` (90 characters, +23).
- Both are one sentence (no `.`, `!` or `?` before the end, so `_SENTENCE_SPLIT_RE` keeps each whole), with no brace and no double quote, and both keep `no music`.
- **AQ3 (FORMAT_REFERENCE).** Its three embedded copies change to the new text, so each "Shot N" still equals `panel_prompt` byte for byte. Its new values are sha256 `3ee8f85bbe4c129a22339ae746ada2775115793aa18041ce7c1361bbe21d568c`, `(3633, 635)` (computed by replacing the sentences in today's value; Task 1 Step 2 recomputes them from the edited file and must match).
- **AQ4 (the no-stills path).** `bin/ltx-story-manifest` is not edited: line 875 reads `lib_.ACOUSTIC_SENTENCE`, so its speaking panels get the new text; its silent panels still get no audio sentence.
- **One code commit, then one test-only commit [spec choice].** The pin updates ride with the code commit so every gate sees a green suite except test_mut26, which Task 2 re-baselines.

---

## 2. Tests: `tests/test_audio_only_quoted.py` (new)

Header and setup, exactly in this order: the module docstring `"""Tests for audio only quoted (docs/superpowers/specs/2026-11-11-audio-only-quoted-design.md, AQ1-AQ4: AOQ1-AOQ6): a chained or shots speech movie's audio sentence says only the quoted words are spoken, or that nobody speaks.` + blank line + `Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_audio_only_quoted.py` + blank line + `No test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API. Stdlib and pytest."""`; imports `importlib.machinery`, `os`, `re`, `sys`, `pytest`; `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`; `sys.path.insert(0, WS)`; `sys.path.insert(0, os.path.join(WS, "tests"))`; `import story_engine_testutil as seu  # noqa: E402`; `import test_dialogue as dlg  # noqa: E402`; `lib = importlib.machinery.SourceFileLoader("character_lib_for_aoq", os.path.join(WS, "character_lib.py")).load_module()`; the literals `ACOUSTIC` (AQ1 text) and `AMBIENCE` (AQ2 text), wrapped as in E1/E2; `SPEAK = "The courier lifts the letter. The camera pushes in."`; `WALK = "The courier walks down the road. The camera tracks alongside the movement."`; and the autouse fixture `story_env(monkeypatch, tmp_path)` returning `seu.set_story_env(monkeypatch, tmp_path)`.

- **AOQ1 `test_aoq1_the_sentences`:** `lib.ACOUSTIC_SENTENCE == ACOUSTIC`; `lib.AMBIENCE_SENTENCE == AMBIENCE`; `"only the quoted words are spoken, and only once" in ACOUSTIC`; `"the dialogue takes priority over the quiet ambience" in ACOUSTIC`; `"nobody speaks" in AMBIENCE`; for `s` in both: `"no music" in s`, `not set('{}"') & set(s)`, `lib._SENTENCE_SPLIT_RE.split(s) == [s]`, `s.endswith(".")`.
- **AOQ2 `test_aoq2_a_speaking_panel_ends_with_the_new_sentence`:** `p = lib.panel_prompt(SPEAK, "The shot is a close-up.", "the courier", "Go now.", "beats", ["the courier"])`; `p == 'The shot is a close-up. The courier lifts the letter. The courier says, "Go now." The camera pushes in. ' + ACOUSTIC`; `p.count("The audio is") == 1`; `re.findall(r'"[^"]*"', p) == ['"Go now."']`; and `lib.speech_text("the courier", "Go now.", "beats") == 'The courier says, "Go now." ' + ACOUSTIC`.
- **AOQ3 `test_aoq3_a_silent_panel_ends_with_nobody_speaks`:** `p = lib.panel_prompt(WALK, "The shot is a wide shot.", None, "", "beats", ["the courier"])`; `p == "The shot is a wide shot. " + WALK + " " + AMBIENCE`; `p.endswith("nobody speaks, and there is no music.")`; `'"' not in p`.
- **AOQ4 `test_aoq4_plain_and_no_acoustic_add_no_audio_sentence`:** `lib.panel_prompt(SPEAK, "", "the courier", "Go now.", "plain", ["the courier"]) == 'The courier lifts the letter. The courier says: "Go now." The camera pushes in.'`; the same with `"beats-no-acoustic"` `== 'The courier lifts the letter. The courier says, "Go now." The camera pushes in.'`; for `d` in `("plain", "beats-no-acoustic")`: `lib.panel_prompt(WALK, "", None, "", d, ["the courier"]) == WALK`; `lib.speech_text("the courier", "Go now.", "beats-no-acoustic") == 'The courier says, "Go now."'`.
- **AOQ5 `test_aoq5_the_shots_manifest_uses_both_sentences(tmp_path, monkeypatch)`:** `story_md, images, ws = dlg._manifest_ws(tmp_path, monkeypatch, "aoq5", dlg.SHOTS_DG9, images=3)`; `assert dlg.story_manifest.main(dlg._manifest_argv("aoq5", story_md, images, mode="shots", panels=3)) == 0`; `prompts = [p["motion_prompt"] for p in dlg._read_manifest(ws, "aoq5")["panels"]]`; `prompts[2].endswith(" " + ACOUSTIC)`; `prompts[0].endswith(" " + AMBIENCE)` and `prompts[1].endswith(" " + AMBIENCE)`.
- **AOQ6 `test_aoq6_the_no_stills_manifest_speaking_panel(tmp_path, monkeypatch)`:** `story_md, images, ws = dlg._manifest_ws(tmp_path, monkeypatch, "aoq6", dlg.NO_STILLS_DG9, plan=dlg.CAST_PLAN, images=0)`; `assert dlg.story_manifest.main(dlg._manifest_argv("aoq6", story_md, images, mode="no_images", panels=4)) == 0`; `prompts` as in AOQ5 with `"aoq6"`; `prompts[3].endswith(" " + ACOUSTIC)`; `prompts[3].count("The audio is") == 1`; for `k` in `(0, 1, 2)`: `"The audio is" not in prompts[k]` (no ambience on a no-stills silent panel).

---

## 3. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

`<cmd>` is the bin/ltx-movie command of a chained or shots speech story with `beats` delivery, at least 8 speaking and 4 silent panels in total (use two stories if one is short), and at least one catalog video LoRA with trigger words picked for its speaking panels. `<id>` is its `--story-id`; run `export D=generated/stories/<id>` first.

- **L1 (the prompts).** After the new arm's run: `python3 -c "import json,os; [print(p['index'], p['motion_prompt'][:60], '...', p['motion_prompt'][-95:]) for p in json.load(open(os.path.join(os.environ['D'], 'manifest.json')))['panels']]"`. Each speaking panel starts with its trigger words and ends with the AQ1 sentence; each silent panel ends with the AQ2 sentence.
- **L2 (the A/B; AQK3).**
  1. Arm A (old): on the workspace before pulling the merge (at `0338c92` or earlier), run `<cmd>`, then `mkdir -p ~/aoq-ab && cp -R $D ~/aoq-ab/A`.
  2. Arm B (new): pull the merge, run the same `<cmd>`, confirm L1, and check that every clip's mtime is newer than A's (a reused clip invalidates the arm: stop and report). Then `cp -R $D ~/aoq-ab/B`.
  3. Watch and listen to every clip of both arms. Per speaking panel count **R** (a quoted fragment voiced more than once), **V** (any voiced word not in the quotes, trigger words included) and **M** (the quoted line missing or cut off); per silent panel count **V** for any voice at all.
  4. **Success:** `R_B + V_B <= (R_A + V_A) / 2`, `R_B <= R_A`, `V_B <= V_A` and `M_B <= M_A`. If `R_A + V_A < 3`, the A/B is inconclusive: add a story and repeat. Report the table (panel, arm, R, V, M) and the two story ids.

---

## 4. Risks and open questions

- **R1.** The model may read `spoken` or `only once` literally and voice nothing; M in L2 catches it. Ruling: accepted, measured.
- **R2.** The unquoted tail grows by 49 characters on a speaking panel and 23 on a silent one; the writer prompt grows by 95 (SFT21 budget 9000 holds at 7899).
- **Q1.** `and only once` is this spec's addition for the repeated-line symptom; the user approved "only the quoted words are spoken". If the user wants the bare clause, AQ1 drops `, and only once` and every literal and sha in this spec changes accordingly.

---

## Plan

### Task 1: the two sentences and their pins (one code commit)

- [ ] **Step 1: Edits** (each Old occurs exactly once; stop if not).
  - **E1** `character_lib.py:792-793`. Old: the two lines `ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "` / `                     "the dialogue takes priority over the quiet ambience, and there is no music.")`. New: the same two lines with `                     "only the quoted words are spoken, and only once; "` inserted between them.
  - **E2** `character_lib.py:879`. Old: `AMBIENCE_SENTENCE = "The audio is the natural ambient sound of the place, with no music."`. New, two lines: `AMBIENCE_SENTENCE = ("The audio is the natural ambient sound of the place; "` / `                     "nobody speaks, and there is no music.")`.
  - **E3** `story_engine.py:2920`. Old: `    "feet. The audio is the natural ambient sound of the place, with no music.\n"`. New, two lines: `    "feet. The audio is the natural ambient sound of the place; nobody speaks, and there is no "` / `    "music.\n"`.
  - **E4** `story_engine.py:2932-2933`. Old: `    "close-mic dialogue with a subtle natural room tone; the dialogue takes priority over the "` / `    "quiet ambience, and there is no music.\n"`. New: `    "close-mic dialogue with a subtle natural room tone; only the quoted words are spoken, and "` / `    "only once; the dialogue takes priority over the quiet ambience, and there is no music.\n"`. Line 2931 is unchanged.
  - **E5** `story_engine.py:2943`. Old: `    "of the place, with no music.\n"`. New: `    "of the place; nobody speaks, and there is no music.\n"`. Line 2942 is unchanged.
  - **E6** `tests/test_chained_end_frames.py:1129-1130`: replace `fec731a3cedadf6578a511e10d93698039ad075729b208bed2903061faa8b12b` with the Step 2 sha and `(3538, 618)` with the Step 2 pair.
  - **E7** `tests/test_shot_format.py`: `:488` the same sha replacement; `:509` the same pair replacement; `:641` `== 3538` becomes `== <Step 2 length>`.
  - **E8** `tests/test_shot_format.py:1344-1346`: apply E1's insertion to the `ACOUSTIC_SENTENCE` literal (`:1344-1345`) and E2's replacement to the `AMBIENCE_SENTENCE` line (`:1346`), text identical to character_lib's.
  - **E9** `tests/test_dialogue.py:41-42`. New, three lines: `AC = ("The audio is clear close-mic dialogue with a subtle natural room tone; only the quoted "` / `      "words are spoken, and only once; the dialogue takes priority over the quiet ambience, and "` / `      "there is no music.")`.
  - **E10** create `tests/test_audio_only_quoted.py` exactly as Section 2.
- [ ] **Step 2: Compute the reference pins** (after E1-E5, before E6-E7):
```bash
cd $S/as-wt/qwen-agent-workspace
PYTHONDONTWRITEBYTECODE=1 python3 -c "import hashlib, importlib.machinery as m; r = m.SourceFileLoader('se_aoq', 'story_engine.py').load_module().FORMAT_REFERENCE; print(hashlib.sha256(r.encode('utf-8')).hexdigest(), len(r), len(r.split()))"
```
Expected: `3ee8f85bbe4c129a22339ae746ada2775115793aa18041ce7c1361bbe21d568c 3633 635`. Any other output: stop and report it (an edit is wrong). Use these three values in E6 and E7.
- [ ] **Step 3: Verify and commit.**
```bash
cd $S/as-wt/qwen-agent-workspace
git diff --numstat     # 3 1 character_lib.py; 5 4 story_engine.py; 2 2 tests/test_chained_end_frames.py; 3 2 tests/test_dialogue.py; 6 4 tests/test_shot_format.py
grep -rIn "with no music\|room tone; the dialogue" character_lib.py story_engine.py bin tests/*.py   # nothing
PYTHONDONTWRITEBYTECODE=1 python3 -c "import importlib.machinery as m; l = m.SourceFileLoader('cl_aoq', 'character_lib.py').load_module(); s = m.SourceFileLoader('se_aoq', 'story_engine.py').load_module(); t = l.ACOUSTIC_SENTENCE + l.AMBIENCE_SENTENCE + s.FORMAT_REFERENCE; print([o for o in ('room tone; the dialogue', 'place, with no music') if o in t], s.FORMAT_REFERENCE.count(l.ACOUSTIC_SENTENCE), s.FORMAT_REFERENCE.count(l.AMBIENCE_SENTENCE))"   # [] 1 2
python3 -B -m pytest -q -p no:cacheprovider tests/test_audio_only_quoted.py tests/test_chained_end_frames.py tests/test_shot_format.py tests/test_dialogue.py tests/test_writer_pacing.py 2>&1 | tail -1
git add character_lib.py story_engine.py tests/test_chained_end_frames.py tests/test_shot_format.py tests/test_dialogue.py tests/test_audio_only_quoted.py
git diff --cached --name-only    # exactly those six paths
git commit -m "character_lib, story_engine: the audio sentence says only the quoted words are spoken, and a silent panel's says nobody speaks (audio-only-quoted AQ1-AQ4)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected: the pytest line has `0 failed` apart from failures the orchestrator's baseline lists for these files; the 6 AOQ tests pass. Then the orchestrator runs the gate (Section "Verification"); expected gate line `lost 1 (listed 1, unexpected 0); new tests 6, not passing 0`, the lost test being `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`.

### Task 2: the `test_mut26` re-baseline (a test-only commit; never amend)

- [ ] **Step 1:**
```bash
cd $S/as-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- character_lib.py story_engine.py); echo $SHA; git log -1 --format=%s $SHA   # Task 1's subject
grep -c 'then to ba48a1a0c68f590a4f2eb8b40b498d38ad15cd50 (lora-scope)\.$' tests/test_movie_ui_builder.py   # 1
grep -c '    BASELINE = "ba48a1a0c68f590a4f2eb8b40b498d38ad15cd50"' tests/test_movie_ui_builder.py        # 1
```
- [ ] **Step 2: Two edits to `tests/test_movie_ui_builder.py`** (type the 40 characters of `SHA`): `then to ba48a1a0c68f590a4f2eb8b40b498d38ad15cd50 (lora-scope).` (end of the comment line `:291`) becomes `then to ba48a1a0c68f590a4f2eb8b40b498d38ad15cd50 (lora-scope), then to SHA (audio-only-quoted).`; `    BASELINE = "ba48a1a0c68f590a4f2eb8b40b498d38ad15cd50"` (`:293`) becomes `    BASELINE = "SHA"`.
- [ ] **Step 3:**
```bash
git diff --stat -- tests/test_movie_ui_builder.py | tail -1    # 1 file changed, 2 insertions(+), 2 deletions(-)
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1   # 1 passed
git add tests/test_movie_ui_builder.py && git diff --cached --name-only    # exactly tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the audio-only-quoted commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Verification (orchestrator, not the executor)

- **V1:** the full gate, the user's usual zsh run (`zsh $S/<baseline dir>/gate-run.sh N`, a full `pytest -rA` of about 20 minutes compared test by test with the baseline), after Task 1 (N=1) and after Task 2 (N=2). After Task 2: `lost 0 (listed 0, unexpected 0); new tests 6, not passing 0` and `GATE PASS` (AQK1).
- **V2:** `git diff --numstat 0338c92 HEAD` matches AQK2.
- **V3:** live checks L1-L2 (Section 3). The user runs them on macstudio; the assistant never does.
