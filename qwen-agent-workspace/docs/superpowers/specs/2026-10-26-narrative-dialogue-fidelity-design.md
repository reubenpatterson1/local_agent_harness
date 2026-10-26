# Narrative dialogue fidelity: quoted lines are required, speaking shots can move, crowds are setting

Date: 2026-10-26

Status: design spec for the three user-approved fixes F1-F3 (Section 0.1). Revision 2 applies every fix of the design review (approve-with-fixes) and the controller ruling on speech placement (SP-P, Section 4). This spec makes every design choice; each one the brief left open is marked **[spec choice]**, and Section 10 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `44f3c4d`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `44f3c4d`.

Specs this one builds on, cited by tag:
- **[DLG]** `docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md`. It covers the Dialogue field, SP2 coercion, the T/N18 rules, D6, the critic patches PG1-PG5 and casting.
- **[ROBUST]** `docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md`. It covers the plan, the critic and the round controller.

---

## 0. Purpose and scope

### 0.1 What happened, and the binding fixes

**Evidence: two real runs on 2026-10-26.** Both runs used the same narrative (`/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/hockey/narrative.txt`):

> A hockey player in a reddish-orange and white uniform with "FuboTV" in a big logo on the front stands in a hockey rink with "FuboTV" on the sides of the rink and on digital banners on the bleachers, with cheering crowds in the stands. He skates forward towards the camera and says "Getting the best deal on hockey isn't a hat trick..." then stops short, kicking up ice mist into the air, then says "It's just FuboTV." then skates away.

Both used `bin/ltx-movie ... --speech-only --judge --goal "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding" --no-review --model .../ltx-2.5-mlx-q8`.

- **`generated/stories/hockey-2x145`** (`--panels 2 --frames 145`):
  - The plan gave beat 1 the speaker `c1`.
  - Beat 2 got speaker `""` and cast `["c1", "c2"]`, where `c2` is "the cheering crowd" (`story_rounds/round_0/plan_reply_1.txt`). The SP rules allow only the speaker on screen, so beat 2 could not speak.
  - "It's just FuboTV." appears nowhere in `story.md`.
  - The critic saw only T2. The judge (story 5/10) did not name the missing line.
- **`generated/stories/hockey-1x241`** (`--panels 1 --frames 241`):
  - The plan had no speaker at all, so both lines were lost.
  - Round 0 had 0 hard violations, so the stop reason was `passed` and the critic never ran.
  - The judge scored story 4/10 but produced `patches: []`. It could not patch, because dialogue patches are offered only for T1/N18 panels.
- **Root cause 1.** No check compares the narrative's quoted speech with the Dialogue fields.
- **Root cause 2.** The speaking-shot rule (static or slow push-in, MCU/CU, speaker alone) contradicts a speaker who skates toward the camera and away. The rule lives in plan `SPEAKER_RULE` `:344-348`, SP2 `coerce_speakers` `:714-755`, `SPEAKING_ACTION_SENTENCE` `:1293-1296` and the N17 camera advisory `:1769-1776`. Faced with that conflict, the planner avoids speakers.
- **Root cause 3.** A crowd modelled as a cast member blocks the speaking beat.

**User-approved fixes (binding):**

- **F1. Quoted narrative lines are required content.** Every spoken line quoted in the narrative is extracted deterministically. The plan assigns each line to a beat. The pipeline gives any line the plan left out to an eligible beat, and code pastes every line verbatim. A new hard, blocking rule **Q1** fails when a required line is not in some panel's `Dialogue:`, word for word and in narrative order. When no beat is eligible, the critic can repair Q1 with a dialogue patch that also makes the panel's character the speaker. An infeasible line set is a hard error before any model call.
- **F2. Speaking shots may move.** A speaking beat may use a medium shot as well as MCU/CU. It may use camera tracking, push-in or pull-back as well as static. Coercion changes only framings and cameras that are not speaking-compatible, and it never coerces tracking away. Lip-readability guidance stays, as advisory and writer text.
- **SP-P (controller ruling). The spoken line is placed where the action allows it.** In a chained or shots Motion with two or more action sentences, the manifest inserts the speech after the first action sentence, not after the last. "stops, says X, skates away" then speaks before the skate-away.
- **F3. Crowds and background people are setting, not cast.** The plan prompt says so. Normalization removes a group cast entry and records an advisory note. A group never blocks a speaking beat.

### 0.2 Grounding (verified at 44f3c4d)

**`story_engine.py` (2997 lines, stdlib only)**
- Constants:
  - `SPEECH_SHOT_TYPES` `:33`; `SPEECH_SHOT_NOTE` `:34-35`; `SPEECH_FRAMING_SENTENCE` `:36-38`.
  - `CAMERA_SENTENCES` `:43-52`; `CAMERA_KEYS` `:53`.
- `StoryContext` `:81-85`. `narration` is `True`, `"speech"` (`--speech-only`) or `False` (`--no-narration`). `engine_seconds` is at `:93-95`.
- `parse_violation` `:258-265` gives a `story:` prefix the scope `"story"` and index `None`.
- Plan prompt:
  - `PLAN_PROMPT_TEMPLATE` `:277-314`, with the cast line `:289-295`, the setting line `:296-298` and the beat keys `:302-311`.
  - `SPEAKER_RULE` `:344-348`; `SILENT_SPEAKER_RULE` `:349`.
  - `_fill` `:362-370` replaces `@@NARRATIVE@@` last.
  - `build_plan_prompt` `:521-560`.
- Plan normalization and checks:
  - `normalize_plan` `:641-707`: beats `:677-692`; `speech_notes` `:706`.
  - `SPEAKING_SHOTS`/`SPEAKING_CAMERAS` `:710-711`; `coerce_speakers` `:714-755`.
  - `FACING_SENTENCE`/`SPEAKING_CAMERA` `:789-790`; `CAMERA_MOTION_RE` `:793-795`; `_facing` `:803-806`; `pasted_pieces` `:820-840`.
  - `plan_checks` `:870-1026`; `speech_notes` are appended at `:1025`.
- Writer:
  - `KEY_LINE_TEMPLATES` `:1224-1285`; `no_stills_prompt_speaking` `:1286-1290`.
  - `SPEAKING_ACTION_SENTENCE` `:1293-1296`; `SPEAKING_IMAGE_SENTENCE` `:1299`.
  - `writer_keys` `:1307`; `panel_speaks` `:1324`; `speaker_phrase` `:1329`; `panel_keys` `:1338`.
  - `empty_parts` `:1383`; `parse_panel_reply` `:1390-1412`; `_clean_dialogue` `:1415`.
- Assembly and panel checks:
  - `panel_fields` `:1424-1453`; `STILL_CAMERA_MOVES` `:1478-1479`.
  - `_field_checks` `:1540-1791`, with N16 at `:1719-1744` and N17 at `:1745-1776`.
  - `GENERATION_CHECKS` `:1831`; `panel_checks` `:1835-1862`; `_order_by_panel` `:1865` (panel-scope lines only); `build_panel_prompt` `:1882-1957`.
- Critic and patches:
  - `CRITIC_PROMPT_TEMPLATE` `:1969-2011`; `critic_field_lines` `:2031-2051`; `build_critic_prompt` `:2054-2077`.
  - `patch_ranges` `:2145`; `apply_patches` `:2187-2262`; `repairable_ids` `:2265-2272`.
  - `NON_BLOCKING_IDS` `:2281`; `REPAIR_IDS` `:2283`; `line_problem` `:2326`.
- Controller:
  - `_Run.plan_round` `:2485-2517`: a plan retry fires when `problems` is non-empty.
  - `make_state` `:2540-2558`; `critic_round` `:2562-2638`; `judge_gate` `:2642` (skipped when blocking); `go` `:2692-2770`.
- Re-check: `RECHECK_IDS` `:2811`; `PLAN_FREE_IDS` `:2813`; `load_plan` `:2817-2832`; `recheck` `:2910-2997`.

**`character_lib.py` (1409 lines)**
- `_SENTENCE_SPLIT_RE` `:126`.
- `_QUOTES` `:682`; `speaker_prefix` `:685`.
- `dialogue_word_cap` `:750`. At 145/24 fps (6.0417 s) it gives 14/13/12 for 1/2/3 fragments, and 14/14/14 at 241/24.
- `split_fragments` `:758`; `clean_line` `:763`; `parse_dialogue` `:783`.
- `insert_speech` `:718-733`: it inserts before the trailing camera-sentence run, so the line lands after every action sentence.
- `FACING_SENTENCE` `:1095`; `_drop_facing` `:1098-1103`; `shots_violations(..., ignore_facing)` `:1127`.

**`bin/ltx-story-manifest`:** the speech composition is at `:826-831` (`lib_.insert_speech(motion_prompt, lib_.speech_text(...), [speaker])`). `motion_prompt` is `pt["motion"]` under `--chain` (`:783`) and `--shots` (`:795`), and `pt["prompt"]` for a no_stills `Prompt:` panel (`:809`).

**Measured on the evidence (python, this checkout).**
- Line 1 is 10 words; line 2 is 3 words.
- Together they are 13 words in 2 fragments: `split_fragments` cuts after `trick...`.
- The cap is 13 at 6.0417 s (fits exactly) and 14 at 10.0417 s.
- `parse_dialogue("the FuboTV player: <both>", ["the FuboTV player"])` returns the line unchanged.

**Tests:**
- `tests/test_dialogue.py` (DLG tests; `_story` `:677`, `_run` `:1072`).
- `tests/story_engine_testutil.py`: `make_ws` `:241`, `script_agent` `:267`, `make_ctx` `:294` and `plan_json` `:363`. In `plan_json`, even beats are `wide shot`/`tracking` and odd beats `medium shot`/`static`.
- The fake agent `:185-238` picks its queue by the prompt's first line.
- `generated/` is gitignored (`.gitignore:2`), so recorded artifacts must be copied into `tests/fixtures/`.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | QL1-QL15 (F1), SM1-SM5 (F2), GC1-GC4 (F3), prompt text (Section 7) |
| G2 | `character_lib.py` | `is_facing_sentence`; `insert_speech(..., first_action=False)` (SP-P1) |
| G2b | `bin/ltx-story-manifest` | the one `insert_speech` call passes `first_action=bool(args.chain or args.shots)` (SP-P2) |
| G3 | `tests/test_narrative_fidelity.py` (new) | NF1-NF37, without NF18 (Section 8.1) |
| G4 | `tests/fixtures/narrative_fidelity/` (new) | verbatim copies of the recorded artifacts, plus 2 hand-written replies (8.2) |
| G5 | existing tests | only the edits of Section 8.3 |
| G6 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit** |

**Not changed:**
- `bin/ltx-movie`, `bin/judge-story` (`PATCH_FIELDS` already has `"dialogue"`), `bin/judge-clips`, `bin/judge-stills`.
- `bin/ltx-story-manifest`, apart from G2b.
- The `--story-legacy` templates and path.
- `movie_ui_lib.py` and `static/*`.
- `ltx2_mlx_video_skill.py`.

### 0.4 Out of scope

- **Pacing.** The slow-motion investigation (the panel-1 Motion "arms swinging gently", motion speed) is a separate investigation and spec.
- Branding legibility ("FuboTV" on the chest and boards), spray realism and stray props.
- Lip-sync quality measurement. The judges have no audio.
- **Who says a line.** Q1 checks that the words are spoken, not that the narrative's speaker says them.
- These quote forms are not extracted: screenplay form (`NAME: "line"` with no speech verb), single-quoted speech, `„…“` and `«…»` quotes, and nested quotes.
- Automatic splitting of an over-long quoted line. A line that no clip fits is a hard error (QL5).
- The legacy engine and the plan-free yardstick (`PLAN_FREE_IDS`): no Q1 there.
- Multi-speaker panels and off-screen speakers (unchanged from [DLG]).

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| NK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the pass count recorded just before implementation, plus every NF test, with no lost pass. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Both are measured after the G6 commit. | full run |
| NK2 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest`. | `test_rst61`, DK2 |
| NK3 | Import sets are unchanged: no new import in any changed file. | `test_rst62`, DK3 |
| NK4 | **Replay of the recorded plans through the new checks, without the QL8b assignment.** 2x145 flags exactly `[T2 panel 2, Q1 line 2]`, and 1x241 flags exactly `[Q1 line 1, Q1 line 2]`; both are blocking. With QL8b, `assign_missing_lines` gives 2x145 lines `[1]`/`[2]` and 1x241 lines `[1, 2]`, and Q1 does not fire. The fixture plans that assign both lines have 0 blocking violations and no Q1, with both lines verbatim in `Dialogue:` in order. | NF8, NF9, NF9b, NF10 |
| NK5 | **Engine runs with the fake agent.** In NF28 (2x145) and NF29 (1x241), the recorded plan replies (no `lines`) go through the plan retry and the QL8b assignment. Round 0 has no Q1, both lines are in `Dialogue:` in order, and the run exits 0. NF30: when no beat is eligible, Q1 blocks with exit 2 unless the critic's Q1 patch repairs it (NF24). NF31: an infeasible line set exits 2 with 0 agent calls. | NF28-NF31 |
| NK6 | **No regression for quote-free narratives.** Every test outside Section 8.3 A passes unedited. For a narrative with no quoted speech, the plan prompt changes only in the three sentences of 7.1 (a, b, d), with no `lines` key and no block. | Section 8.3, NF12 |
| NK7 | Legacy output stays byte-identical. | `test_rst40`, `test_rst41`, `test_s52`, `test_casting_regression.py` |
| NK8 | **Live, post-merge, not a merge gate.** Rerun both hockey commands of 0.1 with `--story-id hockey-2x145-f` and `--story-id hockey-1x241-f`. Phase 1 exits 0, and `story.md` holds both lines verbatim in `Dialogue:` fields in narrative order. Whisper on the clips hears both lines; in 2x145 panel 2 the line comes before the skate-away (SP-P). Record the results in the PR. | manual |

### 0.6 Must-have and nice-to-have

F1, F2 and F3 (Sections 3-5) and the tests (Section 8) are must-haves. Nothing else is built. In particular, there is no dry-run line, no movie-ui field and no new CLI flag.

---

## 1. Architecture

```
narrative ──spoken_lines()──► plan["spoken_lines"] = ["Getting ... trick...", "It's just FuboTV."]
   │                              │
   │ pre-flight (QL5): infeasible → exit 2, no model call
   ▼                              ▼
plan prompt: "Spoken lines" block + beat key "lines" (numbers) + LINES_RULE
normalize_plan: drop_groups (F3) → coerce_speakers: lines + speaker + SP2 (F2 table)
plan_round retry gate: an unassigned line → plan retry (plan-scope Q1 message)
go(): assign_missing_lines (QL8b) gives each still-unassigned line to the first eligible beat
panel writer: a beat with lines gets the dialogue_fixed key line; code pastes the verbatim lines
assembly: Dialogue: <phrase>: <assigned lines>   (a speaker with no lines: the writer's line, as today)
panel_checks: Q1 (story scope, hard, blocking) on the assembled Dialogue fields
critic: Q1 dialogue patch "<phrase>: <line(s)>" → sets the speaker, beat lines and the dialogue (no eligible beat)
manifest: composes the beats from Dialogue:; chained/shots speech goes after the first action sentence (SP-P)
```

Ownership:
- `story_engine.py` owns the extractor, Q1, coercion, prompts and patches.
- `character_lib.py` owns speech placement (`insert_speech`). The manifest is its only speech-composing caller: the engine never composes speech, because story.md keeps `Motion:` and `Dialogue:` separate. Engine assembly order is therefore unchanged (SP-P3).

---

## 2. Data shapes (normative)

### 2.1 plan.json

Two new top-level keys:
- `"spoken_lines"`: a list of display strings (QL3), `[]` when none or when `ctx.narration is False`.
- `"cast_notes"`: a list of P15 advisory strings, `[]` when none.

Key order after `"loras"`: `"spoken_lines"`, `"cast_notes"`, `"speech_notes"`. `speech_notes` stays last.

Each beat gains `"lines"`: a list of 1-based spoken-line numbers, after `"speaker"`. Beat key order: `index, arc, action, shot, camera, location, cast, speaker, lines`. The schema id is unchanged (`ltx-movie.plan.v1`).

`load_plan` adds:
- `beat.setdefault("lines", [])` next to the existing `speaker` default;
- `plan.setdefault("spoken_lines", [])`;
- `plan.setdefault("cast_notes", [])`.

Readers outside the engine (`bin/judge-story` loads plan.json raw) are covered: every new reader uses `.get(..., [])`.

### 2.2 Writer parts, story.md, story_checks.json, run.json

These are unchanged in shape. A beat with lines still has the `"dialogue"` writer key (`panel_keys` is unchanged). Its value is always the code-assembled line (QL9). Q1 violations are serialized by `parse_violation` as `{"id": "Q1", "name": "spoken line", "scope": "story", "index": null, ...}`.

---

## 3. F1: quoted lines are required (QL)

### QL1. Constants (`story_engine.py`, a new block after `_goal_paragraph` `:373-374`; the GC1 constants go in the same block, because step 5(b) of QL2 uses `GROUP_NOUNS`)

```python
QUOTE_RE = re.compile(r'"([^"]*)"')
_LINE_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
_CLAUSE_BREAK_RE = re.compile(r"[.!?;,]")
_QUOTE_EDGE_CHARS = " \t\n,:;—–-"
BEFORE_WINDOW_WORDS = 6
AFTER_WINDOW_WORDS = 4
SPEECH_VERBS = frozenset("""
    say says said saying ask asks asked asking reply replies replied replying
    answer answers answered answering shout shouts shouted shouting yell yells yelled yelling
    scream screams screamed screaming cry cries cried crying
    whisper whispers whispered whispering murmur murmurs murmured murmuring
    mutter mutters muttered muttering exclaim exclaims exclaimed exclaiming
    announce announces announced announcing declare declares declared declaring
    tell tells told telling speak speaks spoke speaking""".split())
CALL_VERBS = frozenset(("call", "calls", "called", "calling"))     # speech only before "out"
CLAUSE_STOP_WORDS = frozenset("and then as but while before after until so or when".split())
NOT_SPEAKER_WORDS = frozenset("""
    that which it sign signs banner banners logo logos screen screens scoreboard jumbotron
    board boards billboard poster posters label caption display shirt jersey note card""".split())
SPOKEN_LINES_HEADER = ("Spoken lines (the narrative quotes these words; the movie must speak "
                       "every one of them on camera, word for word, in this order):")
```

### QL2. `line_words(text)` and `classify_quotes(narrative)`

`line_words(text)` returns `_LINE_WORD_RE.findall(text.replace("’", "'").replace("‘", "'").lower())`. This is the normalization for every match. It removes case and all punctuation, including a trailing ellipsis. Apostrophes inside a word are kept (`isn't`, `it's`), and a hyphen splits words on both sides alike. Non-ASCII letters count as word characters (`café`, `s'il`).

`classify_quotes(narrative)` returns `[(inner, spoken)]` in narrative order:
1. Compute `text = narrative.replace("“", '"').replace("”", '"')`. Positions are unchanged, because every replacement is one character. Curly and straight double quotes therefore pair alike. An unmatched last quote is ignored.
2. `matches = list(QUOTE_RE.finditer(text))`. For match `i`:
   - `prev_end` is `matches[i-1].end()`, or `0`.
   - `next_start` is `matches[i+1].start()`, or `len(text)`.
   - `inner = " ".join(m.group(1).split())`.
3. **Before-window.** Let `before = text[prev_end:m.start()].rstrip(_QUOTE_EDGE_CHARS)` and `clause = _CLAUSE_BREAK_RE.split(before)[-1]`. Let `cw = line_words(clause)`. If `cw` contains a word in `CLAUSE_STOP_WORDS`, keep only the words after the **last** such word. The window is the indices `range(max(0, len(cw) - BEFORE_WINDOW_WORDS), len(cw))` of that cut `cw`.
4. **After-window.** Let `after = text[m.end():next_start].lstrip(_QUOTE_EDGE_CHARS)` and `clause = _CLAUSE_BREAK_RE.split(after)[0]`. Let `cw = line_words(clause)`. If `cw` contains a word in `CLAUSE_STOP_WORDS`, keep only the words before the **first** such word. The window is the indices `range(0, min(AFTER_WINDOW_WORDS, len(cw)))` of that cut `cw`.
5. **Speech-verb test.** In a window over `cw`, index `p` is a speech verb when both hold:
   - (a) `cw[p] in SPEECH_VERBS`, or `cw[p] in CALL_VERBS` with `p + 1 < len(cw)` and `cw[p + 1] == "out"`;
   - (b) `(cw[p - 1] if p > 0 else "") not in NOT_SPEAKER_WORDS | GROUP_NOUNS`. A group is never a speaker (F3), so "The crowd yells "Goal!"" is not required.
6. `spoken` is true when the before-window or the after-window contains a speech-verb index.

**Amendment (final review, 2026-10-26):** a speech verb is not a speaker's when the word before it is a group word (`GROUP_NOUNS`, "everyone", "everybody") or the two words before are "passers by", or when a group word follows within three words of the verb before any of to/at/toward/towards/over/across/into/with/for. A quote the crowd speaks is setting, not a required line. The rule leans to "not spoken": a missed line falls back to the pre-feature behaviour, while a wrongly required one puts the crowd's words in a character's mouth. Pinned by NF2b.

**[spec choice: the windows are clause-bounded (`.!?;,`) and cut at the nearest conjunction or temporal word (`CLAUSE_STOP_WORDS`); 6 words before and 4 after.]**
- They reach "says to the old monk, ..." and "the old monk says ...".
- They stop at the comma in "says nothing, pointing at the "EXIT" sign".
- They stop at "and" in "A sign says "OPEN" and he says "Come in."", "He looks at the "FuboTV" logo and says "Wow."", "He wears a "Fubo" cap and says nothing." and "He says nothing and points at the "EXIT" sign.". The neighbouring speech verb belongs to another clause, so the branding quote is not required.
- Excluding "that/which/it", text surfaces and group nouns rejects "a sign that says "OPEN"", "the scoreboard says "GOAL"" and "The crowd yells "Goal!"".
- The call verbs count only before "out", because "a shop called "Joe's"" and "He calls his dog "Rex"" are naming, not speech.
- Song, chant and "adds" verbs are excluded.

The reviewer's prototype (`/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/review/ql2.py`), extended with `CALL_VERBS` and the `GROUP_NOUNS` exclusion, reproduces every NF1 and NF2 expectation below: 25 of 25 cases, and the hockey result unchanged.

**The evidence narrative (normative, NF1):**

| # | inner | before-window words | after-window words | spoken |
|---|---|---|---|---|
| 1 | `FuboTV` | `white uniform with` (cut after `and`) | `in a big logo` | no: branding |
| 2 | `FuboTV` | `stands in a hockey rink with` | `on the sides of` (cut before `and`) | no: branding |
| 3 | `Getting the best deal on hockey isn't a hat trick...` | `says` (cut after `and`) | (empty: cut before `then`) | **yes** (`says`) |
| 4 | `It's just FuboTV.` | `says` (cut after `then`) | (empty: cut before `then`) | **yes** (`says`) |

### QL3. Display text and `spoken_lines(narrative)`

`spoken_display(inner)` works in four steps:
1. Inline the three operations of `character_lib.clean_line`; this function has no ctx and loads no module. Strip one surrounding `"…"` or `“…”` pair, replace every remaining `"`, `“` or `”` with `'`, and collapse whitespace.
2. `s = s.replace("…", "...")`.
3. `s = s.rstrip(" ,;:—–-")`.
4. If `s` does not end in `.`, `!` or `?`, append `.`.

The ellipsis is kept verbatim: `"trick..."` stays `"trick..."`. **[spec choice: it is the author's text; only matching ignores it.]**

`spoken_lines(narrative)` returns `[spoken_display(inner) for inner, spoken in classify_quotes(narrative) if spoken and line_words(inner)]`. A quote with no words (`""`, `"..."`) is skipped.

For the hockey narrative the result is `["Getting the best deal on hockey isn't a hat trick...", "It's just FuboTV."]`.

### QL4. `required_lines(ctx)`

`[] if ctx.narration is False else spoken_lines(ctx.narrative)`.

- Spoken lines are required for `True` and for `"speech"`.
- With `--no-narration` they are not required. Q1 never runs, and Q2 reports them (QL12). **[spec choice: the user asked for a silent movie.]**

### QL5. Pre-flight feasibility (hard error, no model call)

`panels_needed(lib, seconds, lines)` packs the lines greedily in order:

```
fits(group) := n = len(lib.split_fragments(" ".join(group))); w = len(" ".join(group).split());
               n <= lib.DIALOGUE_MAX_FRAGMENTS and w <= lib.dialogue_word_cap(seconds, n)
needed, i = 0, 0
while i < len(lines):
    j = i
    while j + 1 < len(lines) and fits(lines[i:j + 2]): j += 1
    needed += 1; i = j + 1
return needed
```

Greedy is optimal here because `fits` is monotone on contiguous runs.

`spoken_lines_problem(ctx)` returns a message, or `None`. Let `lines = required_lines(ctx)` and `secs = engine_seconds(ctx)`. It returns `None` when `lines` is empty. Otherwise it checks in this order:
1. For each line `i`, with `n` fragments and `w` words:
   - If `n > DIALOGUE_MAX_FRAGMENTS` or `w > DIALOGUE_MAX_WORDS`, return `"the narrative's spoken line %d (\"%s\") is %d words in %s; no clip fits it, because a spoken line has at most %d words in at most %d sentences; split it into shorter quoted lines in the narrative" % (i, line, w, _n_sentences(n), DIALOGUE_MAX_WORDS, DIALOGUE_MAX_FRAGMENTS)`.
   - Else, if `w > dialogue_word_cap(secs, n)`, return `"the narrative's spoken line %d (\"%s\") is %d words in %s; a %s-second clip fits at most %d words in %s; use longer clips (a larger --frames) or split it into shorter quoted lines in the narrative" % (i, line, w, _n_sentences(n), ctx.seconds, cap, _n_sentences(n))`.

   `_n_sentences(n)` returns `"1 sentence"` when `n == 1`, else `"%d sentences" % n`. It is used only by these new messages. The existing T1 and PG4 texts keep "1 sentences", because tests pin them; changing them is out of scope.
2. With `p = panels_needed(lib, secs, lines)`: if `p > ctx.panels`, return `"the narrative quotes %d spoken lines, which need at least %d panels of %s seconds (one panel speaks at most %d words), but this movie has %d; use --panels %d or more, or longer clips (a larger --frames)" % (len(lines), p, ctx.seconds, dialogue_word_cap(secs, 1), ctx.panels, p)`.

In `_Run.go()`, after `self.write_run()` and the catalog warnings (`:2699-2701`) and before `self.plan_round()`, add:
```python
problem = spoken_lines_problem(ctx)
if problem:
    print("Error: %s" % problem, file=sys.stderr)
    return self.finish(2)
```

Re-check does not run the pre-flight; Q1 reports instead. For the hockey lines: 1 panel at 6.04 s fits both lines (13 ≤ 13), and 1 panel at 10.04 s fits both (13 ≤ 14).

### QL6. Plan prompt

The exact text is in Section 7.1. `build_plan_prompt` computes `lines = required_lines(ctx)` and then:
- **Narrative.** `_fill(..., ctx.narrative + spoken_lines_block(lines))`. The block is appended to the narrative *value*, so user text is still inserted last and never scanned for tokens. `spoken_lines_block(lines)` is `""` when `lines` is empty, else `"\n\n" + SPOKEN_LINES_HEADER + "".join('\n%d. "%s"' % (i, l) for i, l in enumerate(lines, 1))`.
- **Fragments.** `("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker")` and `("@@LINES_RULE@@", LINES_RULE if lines else "")`.
- **Scalar.** `("@@LINE_WORDS@@", str(lib.dialogue_word_cap(engine_seconds(ctx), 2)))`, where `lib = _character_lib(ctx.ws)` (13 at 6.04 s, 14 at 10.04 s).

### QL7. Normalization and coercion of lines

**`normalize_plan` changes:**
- Each beat gets `"lines": _clean_lines(item.get("lines"))`, after `"speaker"`.
- `_clean_lines(v)`: when `v` is not a list, return `[]`. Otherwise keep, in order, each item that is an `int` and not a `bool`, and each `str` whose `.strip().isdigit()` (converted with `int`). Drop everything else.
- After the beats and loras are built:
  1. `plan["spoken_lines"] = required_lines(ctx)`;
  2. `plan["cast_notes"] = drop_groups(plan)` (GC3);
  3. `plan["speech_notes"] = coerce_speakers(ctx, plan)`.

**`speaking_coercion(ctx, plan, k)`** is new and returns notes. It is today's SP2 step 4 (`:741-754`), extracted unchanged except for the F2 table (SM2). It is applied to beat `k`, whose `speaker` is already set:
- the cast note and `beat["cast"] = [speaker]`;
- when `ctx.mode != "chained" or k == 1`, the shot and camera coercion of SM2.

**`coerce_speakers(ctx, plan)`, rewritten.** Notes are produced in this order, and the existing note strings are unchanged:

```
notes = []; cast_ids = [c["id"] for c in plan["cast"]]; spoken = plan["spoken_lines"]; last = 0
for k, beat in enumerate(plan["beats"], 1):
    raw, raw_lines = beat["speaker"], beat["lines"]
    beat["speaker"], beat["lines"] = "", []
    if ctx.narration is False:            # today's note for a non-empty raw; lines dropped silently
        ...; continue
    sid = <today's steps 2-3 and the phrase mapping of :730-739: a cast id, or "" with its note>
    lines = []
    if spoken:
        for n in sorted(set(raw_lines)):
            if not 1 <= n <= len(spoken):
                notes.append("beat %d: P14 speaking beat: line %d dropped: the narrative has no "
                             "spoken line %d" % (k, n, n))
            elif n <= last:
                notes.append("beat %d: P14 speaking beat: line %d dropped: an earlier beat already "
                             "speaks line %d or a later one" % (k, n, last))
            else:
                lines.append(n)
        if lines and not sid:
            if len(beat["cast"]) == 1 and beat["cast"][0] in cast_ids:
                sid = beat["cast"][0]
                notes.append("beat %d: P14 speaking beat: speaker set to %s, the only character in "
                             "the beat, to say line(s) %s" % (k, _q(sid), _nums(lines)))
            else:
                notes.append("beat %d: P14 speaking beat: line(s) %s dropped: the beat has no "
                             "speaker" % (k, _nums(lines)))
                lines = []
        while lines and line_problem(ctx, lib, " ".join(spoken[n - 1] for n in lines)):
            n = lines.pop()
            notes.append("beat %d: P14 speaking beat: line %d dropped: together with the beat's "
                         "other lines it does not fit a %s-second clip" % (k, n, ctx.seconds))
        beat["lines"] = lines
        if lines: last = lines[-1]
    if not sid: continue
    beat["speaker"] = sid
    notes += speaking_coercion(ctx, plan, k)
return notes
```

`_nums(ns)` is `", ".join(str(n) for n in ns)`. `lib` is `_character_lib(ctx.ws)`, loaded only when `spoken` is non-empty. When `spoken` is empty, any `lines` the reply gives are dropped silently, because the prompt never asked for them.

**[spec choice: a speaking beat without lines keeps its speaker, and the writer writes its line as today.]**
- With quoted lines, the plan prompt asks for speakers only on beats with lines.
- If the writer copies a required line anyway (2x145 panel 1 did), Q1 counts it.
- Nothing is dropped silently.

### QL8. Plan retry gate

`line_assignment_problems(plan)` returns, for each `n` from 1 to `len(plan["spoken_lines"])` that is in no beat's `lines`:

`"plan: Q1 spoken line: spoken line %d \"%s\" is in no beat's lines; put %d in the lines of the beat whose action surrounds it in the narrative, and give that beat a speaker" % (n, line, n)`.

In `plan_round` (`:2505-2509`), `problems = hard + line_assignment_problems(plan)`. `found` stays `(plan, shape, hard)`. These messages trigger the existing retry (at most `PLAN_MAX_CALLS = 2`) and never enter a state. **[spec choice: the planner has the narrative context, so it is the cheapest repair; the state-level Q1 still catches whatever survives.]**

### QL8b. Pipeline assignment of the lines the plan left out

In `_Run.go()`, right after the plan is accepted (`plan, self.shape, _hard = found`, `:2716`) and before the panel calls, add `plan["speech_notes"] += assign_missing_lines(ctx, plan)`.

`assign_missing_lines(ctx, plan) -> notes`:

```
spoken = plan["spoken_lines"]; beats = plan["beats"]; notes = []
if not spoken: return notes
lib = _character_lib(ctx.ws); cast_ids = [c["id"] for c in plan["cast"]]
holder = {n: k for k, b in enumerate(beats, 1) for n in b["lines"]}
for n in range(1, len(spoken) + 1):
    if n in holder: continue
    earlier = [holder[m] for m in range(1, n) if m in holder]
    prev_k = earlier[-1] if earlier else 0          # the beat holding the nearest earlier line
    later = [holder[m] for m in range(n + 1, len(spoken) + 1) if m in holder]
    next_k = later[0] if later else len(beats)      # no later than the beat of the next assigned line
    order = list(range(prev_k + 1, next_k + 1)) + ([prev_k] if prev_k else [])
    for k in order:
        b = beats[k - 1]
        if not (b["speaker"] or (len(b["cast"]) == 1 and b["cast"][0] in cast_ids)):
            continue
        lines = sorted(b["lines"] + [n])
        if line_problem(ctx, lib, " ".join(spoken[m - 1] for m in lines)):
            continue
        notes.append("beat %d: P14 speaking beat: line %d given to this beat by the pipeline, "
                     "because the plan gave it to no beat" % (k, n))
        if not b["speaker"]:
            b["speaker"] = b["cast"][0]
            notes += speaking_coercion(ctx, plan, k)
        b["lines"] = lines; holder[n] = k
        break
return notes
```

A beat is **eligible** for line `n` when all of these hold:
- it already has a speaker, or exactly one cast id;
- it is no later than the beat that holds the next assigned line;
- `line_problem` passes on its joined lines with `n` added.

The candidates are the first eligible beat after the beat holding the nearest earlier line, in beat order, and then that same beat. A line with no eligible beat stays unassigned: Q1 then fires, and the critic's Q1 patch (QL13) is the remaining repair.

**Amendment (implementation ruling, 2026-10-26):** a beat is eligible for line n only if its lines plus n form a consecutive run (spec 7.1 e); and the pass repeats until it places no line (at most one pass per spoken line), so the result does not depend on processing order and a second call is a no-op. Pinned by NF37b.

The notes reach `plan_checks` through `speech_notes` and are written to plan.json. The function runs only in `go()`; the replays NF8 and NF9 call `make_state` directly, so they still exercise Q1 itself.

Expected results on the recorded replies:
- **2x145.** Beat 1 is eligible (speaker `c1`), so it gets `[1]`. Beat 2 is eligible for line 2 (sole cast `c1` after P15), gets `[2]`, and its speaker is set to `c1`. Chained `k = 2`, so no coercion notes.
- **1x241.** Beat 1 gets `[1]` (speaker set to `c1`; `medium shot` and `tracking` are kept, with no notes). Line 2 has no later beat, so it falls back to beat 1: 13 words in 2 sentences, cap 14 at 10.04 s. Result `[1, 2]`.

**[spec choice: deterministic, and only in order. The pipeline never moves a line the plan placed; it only fills gaps.]**

### QL9. Writer: the assigned beat's dialogue is pasted

`assigned_dialogue(plan, k)` returns `" ".join(spoken[n - 1] for n in plan["beats"][k - 1].get("lines", []) if 1 <= n <= len(spoken))`, where `spoken = plan.get("spoken_lines", [])`.

- **`build_panel_prompt`.** For `key == "dialogue"`, use `KEY_LINE_TEMPLATES["dialogue_fixed"]` (7.2) when `assigned_dialogue(plan, k)` is non-empty, else `"dialogue"`. In step 5 (`:1929-1930`), also `.replace("@@LINE@@", '"%s"' % assigned)`.
- **`parse_panel_reply`.** For `key == "dialogue"` with a non-empty `assigned`, `value = assigned`. The reply's own `dialogue`, present or missing, is ignored.
- **`empty_parts`.** When `ctx` is given and `assigned` is non-empty, `parts["dialogue"] = assigned`.
- **`panel_fields`.** The `Dialogue` line text is `assigned_dialogue(plan, k) or clean_line(p.get("dialogue", ""))`, then `_sentence`. The plan is the single source for assigned lines.

### QL10. The Q1 check

```python
Q1_MISSING = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is in no panel's "
              "Dialogue:; give it word for word to the panel that shows it being said (Dialogue: "
              "<speaker's referring phrase>: <the line>)")
Q1_ORDER = ("story: Q1 spoken line: the narrative's spoken line %d \"%s\" is spoken out of the "
            "narrative's order; the Dialogue: fields must say the spoken lines in the order the "
            "narrative gives them")
```

`_find_run(words, run, start)` returns the first `j >= start` with `words[j:j + len(run)] == run`, else `None`.

`spoken_line_problems(ctx, lib, phrases, dialogues)` takes `dialogues`, one `Dialogue:` value (`""` if none) per panel in order:

```
required = required_lines(ctx); if not required: return []
D = []
for value in dialogues:
    phrase, line, _p = lib.parse_dialogue(value, phrases) if value.strip() else (None, "", None)
    D.append(line_words(line) if phrase else [])       # an N18-broken Dialogue counts as empty
kpos, jpos, out = 0, 0, []
for i, text in enumerate(required, 1):
    R = line_words(text); hit = None
    for p in range(kpos, len(D)):
        j = _find_run(D[p], R, jpos if p == kpos else 0)
        if j is not None: hit = (p, j); break
    if hit: kpos, jpos = hit[0], hit[1] + len(R); continue
    anywhere = any(_find_run(d, R, 0) is not None for d in D)
    out.append((Q1_ORDER if anywhere else Q1_MISSING) % (i, text))
return out
```

How a line is matched:
- A line must sit inside one panel's Dialogue.
- Extra words before or after it are allowed.
- Case and punctuation are ignored (QL2).
- A repeated line must occur again later.

**Wiring:**
- `"Q1"` is appended to `GENERATION_CHECKS` and `RECHECK_IDS`. `PLAN_FREE_IDS` is unchanged.
- In `panel_checks`, the per-panel loop collects `dict(fields).get("Dialogue", "")` for each panel. After the loop and before the shots block, it adds `if "Q1" in GENERATION_CHECKS: hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan), dialogues)`. The order is therefore the per-panel hard violations, then Q1 in line order, then S1/S3.
- In `recheck` with a plan, after the per-panel loop (`:2934`), add `hard += spoken_line_problems(ctx, lib, cast_phrases(ctx, plan), [p.get("dialogue", "") for p in parsed])`.

**Class.** Q1 is hard and **blocking**; it is not in `NON_BLOCKING_IDS`. It is not in `REPAIR_IDS`, because the code-only round cannot place a line. The judge gate skips a best round that has Q1, as today for blocking states.

### QL11. The critic prompt

`build_critic_prompt` replaces `@@NARRATIVE@@` with `plan["narrative"] + spoken_lines_block(plan.get("spoken_lines", []))`.

`critic_field_lines(mode, catalog_lines, narration=True, spoken=False)` appends `CRITIC_Q1_FIELD_LINE` (7.3) after the T1/N18 dialogue line when `spoken and narration is not False`. `build_critic_prompt` passes `spoken=bool(plan.get("spoken_lines"))`.

The template sentences pinned by DLG19 are unchanged. Without spoken lines the prompt is byte-identical, except that the plan JSON's beats now carry `"lines": []`.

### QL12. Q2 (lines dropped by `--no-narration`) and Q3 (odd quote count), both advisory

In `plan_checks`, after the P13 advisories:
1. `advisory += plan.get("cast_notes", [])`.
2. When `ctx.narration is False` and `spoken_lines(ctx.narrative)` is non-empty, append `"plan: Q2 spoken lines: the narrative quotes %d spoken line(s), but --no-narration makes this movie silent, so none of them is spoken" % n`.
3. **Q3, odd quote count (advisory, every narration mode).** Let `q` be the number of `"` characters in the narrative after the curly-to-straight replacement of QL2 step 1. When `q` is odd, append `"plan: Q3 quotes: the narrative has an odd number of double quotes (%d), so its last quote is unmatched and ignored; close every quoted line" % q`.
4. Then `advisory += plan["speech_notes"]` (existing; still last).

### QL13. Patches: the Q1 dialogue patch

- `repairable_ids(hard)` also collects story-scope ids under the key `"story"`: `out.setdefault("story", set()).add(id)` when `scope == "story"`. Integer panel keys are unchanged.
- In `apply_patches`, `q1 = bool(plan.get("spoken_lines")) and (repairable is None or "Q1" in repairable.get("story", set()))`.

`spoken_run(text, spoken)` matches a replacement against the spoken lines. Let `W = line_words(text)`; if `W` is empty, return `None`. For `i` from 1 to `m`, accumulate `line_words(spoken[i-1]) + ... + line_words(spoken[j-1])` for `j = i, i+1, …`. Return `(i, j)` at the first exact equality with `W`. Break the inner loop once the accumulated length is at least `len(W)`. Return `None` if nothing matches.

`contained_lines(text, spoken)` returns `[n for n, s in enumerate(spoken, 1) if _find_run(line_words(text), line_words(s), 0) is not None]`.

`q1_dialogue_patch(ctx, lib, plan, parts, k, replacement)` returns `(matched, problem)`. `matched` is False when the replacement is not a Q1 replacement. Otherwise `problem` is `None` (applied) or the rejection reason. It runs these steps in order:
1. `text = clean_writer(lib, replacement)`; `phrases` = the plan cast phrases.
2. **Find the spoken lines and the stated speaker.**
   - If `lib.parse_dialogue(text, phrases)` returns a phrase, take its line and look up the id `sid0` of the cast entry with that phrase (case-insensitive). `run = spoken_run(line, spoken)`.
   - Otherwise `sid0 = ""` and `run = spoken_run(lib.clean_line(text), spoken)`. If `run is None` and `lib.speaker_prefix(text)` finds `(prefix, rest)`, set `run = spoken_run(rest, spoken)`. If that run is not `None`, return `(True, "the replacement " + <parse_dialogue's problem string for text>)`.
   - If `run is None`, return `(False, None)`.
3. `(i, j) = run`; `beat = plan["beats"][k-1]`.
4. **Choose the speaker.** `sid` is the first non-empty of `sid0`, `beat["speaker"]`, and `beat["cast"][0]` when `len(beat["cast"]) == 1`. If none is found, return `(True, "name the speaker: start the replacement with their referring phrase and a colon")`.
5. If `beat["speaker"]` is set and `sid != beat["speaker"]`, return `(True, "panel %d's speaker is %s; a spoken-line patch never changes who speaks" % (k, _q(beat["speaker"])))`.
6. Let `current` be the panel's current Dialogue line: the line from `lib.parse_dialogue(dict(panel_fields(ctx, plan, parts, k)).get("Dialogue", ""), phrases)`, or `""`. Let `want = set(beat["lines"]) | set(contained_lines(current, spoken)) | set(range(i, j + 1))`. If `want` is not contiguous (`max(want) - min(want) + 1 != len(want)`), return `(True, "the replacement must keep panel %d's spoken lines and add only an adjacent line" % k)`. Otherwise set `i, j = min(want), max(want)`. A patch that names only the missing line therefore keeps the lines the panel already says, which avoids a deadlock in which neither line can be added. Then, if `line_words(current)` is non-empty and is not exactly the concatenated `line_words` of `spoken[a - 1:b]`, where `a`/`b` are the min and max of `contained_lines(current, spoken)`, return `(True, "panel %d's Dialogue: has words that are not the narrative's spoken lines, and existing Dialogue words are never rewritten" % k)`. This holds D6's "never rewritten" limit exactly: a canonical replacement only ever adds lines.
7. For every other beat `b`, if `set(b["lines"]) & set(range(i, j + 1))` is non-empty, return `(True, "spoken line %d is already given to beat %d" % (min of the overlap, that beat's number))`.
8. `canonical = " ".join(spoken[i - 1:j])`. If `line_problem(ctx, lib, canonical)` returns a problem, return `(True, problem)`.
9. **Apply.**
   - If `beat["speaker"] == ""`: set `beat["speaker"] = sid`, then `plan["speech_notes"] += speaking_coercion(ctx, plan, k)`.
   - Then `beat["lines"] = list(range(i, j + 1))` and `parts[k - 1]["dialogue"] = canonical`.
   - Return `(True, None)`.

**`apply_patches` panel loop (replaces `:2238-2261`).** Patches are taken in list order, so a later patch sees an earlier one's plan changes.

```
for patch in accepted (target "panel"):
    k, field = ...
    if field == "dialogue" and q1:
        matched, problem = q1_dialogue_patch(ctx, lib, plan, parts, k, patch["replacement"])
        if matched:
            (rejected.append({"patch": patch, "reason": problem}) if problem else applied.append(patch))
            continue
    need = {"T1", "N18"} if field == "dialogue" else {"T2", "T3"}
    if repairable is not None and not (repairable.get(k, set()) & need):
        reason = Q1_ONLY_REASON % k if (field == "dialogue" and q1) else <today's reason> % k
        rejected...; continue
    if field == "dialogue" and plan["beats"][k - 1].get("lines"):
        rejected.append({"patch": patch, "reason": "panel %d says the narrative's spoken line(s) %s, "
                         "which are never rewritten" % (k, _nums(plan["beats"][k - 1]["lines"]))})
        continue
    ... today's dialogue (PG4) / motion-prompt (PG3) branches, unchanged
```

`Q1_ONLY_REASON = ("panel %d has no hard timing problem, and under a Q1 problem a dialogue replacement must be the speaker's referring phrase, a colon and one or more consecutive spoken lines of the narrative, word for word")`.

**[spec choice: there is one patch field (`dialogue`) and no new `beat.speaker` field.]**
- The speaker comes from the replacement's phrase, then the beat's speaker, then the beat's sole cast member.
- The stored text is the extractor's canonical line, never the critic's spelling.
- Q1 is a user-approved exception to [DLG] D6 (2026-10-26). A missing narrative line blocks even though the pipeline could proceed. D6's other limits hold: at most 2 critic rounds, only hard problems are patched, and existing Dialogue words are never rewritten.
- `bin/judge-story`'s `PATCH_FIELDS` needs no change.

**Amendment (implementation ruling, 2026-10-26):** a Q1 dialogue patch is also rejected when, at the moment it is applied, an earlier beat holds a later line or a later beat an earlier one ("spoken line N is given to beat B, so panel K cannot say line I without breaking the narrative's order"); patches apply in sequence, so an accepted patch counts for the next. Pinned by NF21b.

**Amendment (final review, 2026-10-26):** step 6's `have` is the beat's `lines` when it has any (the plan is the single source of assigned lines, QL9), and `contained_lines` only otherwise, so a short line inside a longer one cannot reject a correct patch. Pinned by NF21c.

### QL14. Recheck

QL10 wiring. A hand-edited `story.md` that adds `Dialogue: the FuboTV player: It's just FuboTV.` to panel 2 passes Q1 on re-check.

### QL15. Interactions (normative)

| Setting | Lines required | Plan prompt block / `lines` key | Q1 | Notes |
|---|---|---|---|---|
| default (`narration True`) | yes | yes | yes | Narration stays voice-over; Q1 reads Dialogue only |
| `--speech-only` | yes | yes | yes | the evidence runs |
| `--no-narration` | no | no (SILENT rule) | no | Q2 advisory |
| `--story-legacy` | no | — | — | engine not used; unchanged |
| no quoted speech | — | no | no-op | prompts change only per 7.1 (a, b, d) |

---

## 4. F2: speaking shots may move (SM)

### SM1. Constants

```python
SPEAKING_SHOTS = ("medium shot", "medium close-up", "close-up")
SPEAKING_CAMERAS = ("static", "slow push-in", "slow pull-back", "tracking")
STILL_CAMERA_MOVES = ("static", "still", "hold", "holds", "locked-off", "push in", "pushes in",
                      "push-in", "pull back", "pulls back", "pull-back", "track", "tracks",
                      "tracking", "follow", "follows")
```

`speaking_camera(beat)` returns `beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "static"`.

### SM2. Coercion table (`speaking_coercion`, when `ctx.mode != "chained" or k == 1`)

| Planned | Result | Note |
|---|---|---|
| shot `medium shot`, `medium close-up`, `close-up` | kept | none |
| shot `extreme close-up` | `close-up` | existing shot note |
| shot `wide shot`, `extreme wide shot`, empty or unknown | `medium close-up` | existing shot note |
| camera `static`, `slow push-in`, `slow pull-back`, `tracking` | kept (**tracking is never coerced away**) | none |
| camera `slow pan left/right`, `slow tilt up/down`, empty or unknown | `static` | existing camera note `"... changed to 'static' so the speaker's face stays readable"` |

Chained `k >= 2` beats are still never coerced ([DLG] D8).

### SM3. Pasted pieces and the facing sentence

`pasted_pieces` (`:820-840`) keeps today's facing sentence: `facing = [FACING_SENTENCE % P]` on a speaking panel, else `[]`, where `P` is the capitalised speaker phrase. It is used in Image and in Motion/Prompt alike, with no second facing form.

| Mode / panel | Pieces |
|---|---|
| chained k=1, shots | unchanged: `image = [setting] + identities + facing + [shot]`; `motion = facing + [camera]` |
| chained k≥2 | `motion = facing + ([dict(CAMERA_SENTENCES)[speaking_camera(beat)]] if facing else [])` |
| no_stills | unchanged: `prompt = identities + [setting, shot] + facing + [camera]` |

The planned camera sentence of a chained `k >= 2` speaking panel now follows the beat (for example "The camera tracks alongside the movement."). It falls back to "The camera stays static." for a pan or tilt. `SPEAKING_CAMERA` stays as a constant, with the same text as `CAMERA_SENTENCES["static"]`.

The only assembly change F2 makes is the chained `k >= 2` camera sentence. Static and push-in output stays byte-identical.

### SM4. Writer and plan text

These are the exact strings in Sections 7.1 and 7.2:
- `SPEAKER_RULE`;
- `SPEAKING_ACTION_SENTENCE`;
- the `no_stills_prompt_speaking` replacement text;
- `SPEAKING_IMAGE_SENTENCE` (also F3);
- `SPEECH_FRAMING_SENTENCE`.

**[spec choice: the `--speech-only` framing sentence no longer forbids a character leaving or shrinking *after* their line.]** Its old text contradicted "then skates away".

### SM5. N17 (advisory)

- The camera-direction sub-rule (`:1769-1776`) uses the widened `STILL_CAMERA_MOVES`. Its message becomes: `"has the camera direction %s while %s speaks; while someone speaks the camera stays static, pushes in, pulls back or tracks them, so their face stays readable"`.
- The wide-shot, held-expression and other-people sub-rules are unchanged.
- **N16 is unchanged.** It is about who is in the shot, and F2 does not change that.

### SP-P. Speech placement (controller ruling)

**Problem.** Today `insert_speech` (`character_lib.py:718-733`) inserts the speech before the trailing run of camera sentences, which is after **every** action sentence. Take the hockey panel 2 Motion "... halts in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera. ...": its line is spoken after the skate-away, when the speaker is leaving the frame.

**SP-P1. `character_lib.py`.**

Add `is_facing_sentence(sentence, phrases)` after `FACING_SENTENCE` (`:1095`). It returns `sentence.strip().lower() in {(FACING_SENTENCE % (p[:1].upper() + p[1:])).lower() for p in phrases}`.

Change the signature to `insert_speech(text, sentence, phrases=(), first_action=False)`:

```
sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
trailing = <today's count of trailing _is_camera_sentence(..., phrases) sentences>
if first_action:
    body = sentences[:len(sentences) - trailing]
    actions = [i for i, s in enumerate(body)
               if not _is_camera_sentence(s, phrases) and not is_facing_sentence(s, phrases)]
    if len(actions) >= 2:
        facing = [s for s in body if is_facing_sentence(s, phrases)]
        rest = [s for s in body if not is_facing_sentence(s, phrases)]
        at = len([s for s in body[:actions[0] + 1] if not is_facing_sentence(s, phrases)])
        return " ".join(rest[:at] + facing + [sentence] + rest[at:]
                        + sentences[len(sentences) - trailing:])
<today's code, unchanged>
```

With two or more action sentences (the facing sentence does not count), the speech goes right after the first action sentence. Any pasted facing sentence moves to sit immediately before it, and the trailing camera run stays last. With one action sentence, or `first_action=False`, the output is byte-identical to today. `--speech-delivery plain` differs only in placement, because the `sentence` argument is the same string as today.

**SP-P2. `bin/ltx-story-manifest` (`:830-831`).** The call becomes `lib_.insert_speech(motion_prompt, lib_.speech_text(speaker, speech, args.speech_delivery), [speaker], first_action=bool(args.chain or args.shots))`. A no_stills `Prompt:` panel keeps today's placement. **[spec choice: a no_stills Prompt is one long chronological paragraph that includes pasted identity and setting sentences, so "after the first sentence" there would put the line before the scene is set.]**

**SP-P3. Engine.** The engine does not compose speech: story.md keeps `Motion:` and `Dialogue:` apart, and the manifest is the one composer. The engine's assembly order (writer text, then the facing sentence, then the camera sentence) is therefore unchanged. The manifest repositions the facing sentence itself, so every story.md, old or new, composes the same way. **[spec choice: this keeps PG3, `clean_writer`, T2 and every engine golden stable.]**

**Worked example (normative, NF35).** The 2x145 panel 2, after NF28, with Motion `The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera. The FuboTV player faces the camera. The camera stays static.` and Dialogue `the FuboTV player: It's just FuboTV.`, composes (beats) to:

```
The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice mist into the air. The FuboTV player faces the camera. The FuboTV player says, "It's just FuboTV." <AC> He skates away from the camera. The camera stays static.
```

With plain it is the same, with `The FuboTV player says: "It's just FuboTV."` in place of the beats sentence and with no `<AC>`. "He skates away from the camera." is an action sentence: `_is_camera_sentence` is False, because "He" is a pronoun. The facing sentence is not an action sentence.

Existing manifest goldens do not change. Every speaking `Motion:` in DLG7-DLG10, `test_review_focus_2` and `test_review_focus_3` has exactly one action sentence, so the output is byte-identical; Section 8.3 C pins them.

**Remaining risk R10.** A single writer sentence that chains actions with "then" ("skates forward, then stops, then skates away") cannot be split. Its line is still spoken after the whole sentence.

---

## 5. F3: crowds are setting, not cast (GC)

### GC1. Constants

```python
GROUP_NOUNS = frozenset("""
    crowd crowds audience audiences fans spectators onlookers bystanders passers-by passersby
    pedestrians commuters supporters cheerleaders throng throngs mob mobs masses public
    congregation team teams squad squads band bands people extras""".split())
GROUP_DESCRIPTOR_RE = re.compile(
    r"^an?\s+(?:[A-Za-z-]+\s+){0,2}(?:group|crowd|throng|mob|mass|sea|line|row|pack|band|team|"
    r"squad|horde|swarm|flock|herd)\s+of\b", re.IGNORECASE)
```

### GC2. `is_group_entry(entry)`

The entry is a group when `entry.get("cast_name") is None` and either of these holds:
- the head word is in `GROUP_NOUNS`. The head word is the last word of `entry["phrase"].split()`, lowercased, with a trailing `'s`, `’s`, `'` or `’` removed;
- `GROUP_DESCRIPTOR_RE.match(entry["descriptor"])`.

Library characters (`cast_name` set) are never groups.

**[spec choice: only the head noun is checked, so "the team captain" and "the crowd's leader" stay characters, while "the cheering crowd", "the fans'" and "the hockey team" are groups.]**

### GC3. `drop_groups(plan) -> notes`

1. Walk `plan["cast"]` in order and remove every group entry.
2. Let `gone` be the removed ids that no kept entry also uses. Remove every id in `gone` from every beat's `cast`, keeping order.
3. For each removed entry, in cast order, add one note: `"plan: P15 group cast: %s %s is a group of people, not a character, so it is removed from the cast%s; describe it in the setting sentence instead" % (id, _q(phrase), where)`.
   - `where` is `""` when no beat listed the id.
   - Otherwise it is `" and from beat %s"` for one beat or `" and from beats %s"` for several, with the beat numbers joined by `", "`.

It runs before `coerce_speakers`, so a group id given as a speaker is reported by the existing note "speaker %s is not a cast id, so nobody speaks in this beat". Ids are not renumbered: P2 checks the id format only.

For 2x145 the note is `plan: P15 group cast: c2 'the cheering crowd' is a group of people, not a character, so it is removed from the cast and from beat 2; describe it in the setting sentence instead`. P12 no longer fires for c2.

### GC4. Classification

P15 is **advisory**. It is never hard, never patched, and never makes the plan retry. **[spec choice: removal is deterministic and lossless for rendering. The crowd is still in the writer's Image text and should be in the setting.]**

---

## 6. Rule table (new and changed)

| ID | Class | Message / behaviour |
|---|---|---|
| Q1 (story) | hard, **blocking**; prevented by the plan retry and QL8b; repaired by the critic's Q1 dialogue patch | `Q1_MISSING`, `Q1_ORDER` (QL10) |
| Q1 (plan form) | plan-retry gate only; never in a state | QL8 |
| pre-flight | exit 2 before any model call; not a check id | QL5 (three messages) |
| Q2 | advisory | QL12 |
| Q3 | advisory | QL12 step 3 |
| P15 | advisory | GC3 |
| P14 | advisory | the existing notes, plus 5 line notes (QL7) and the QL8b "given to this beat by the pipeline" note; the SP2 camera note fires only for pans, tilts and unknown cameras |
| N17 | advisory | camera-direction message (SM5) |
| N16, T1-T3, N18, all others | unchanged | — |

Patch rejection reasons (exact):
- QL13 steps 2 and 4-8, including the step-6 contiguity and never-rewritten reasons;
- `Q1_ONLY_REASON`;
- "never rewritten".

---

## 7. Prompt text (exact)

### 7.1 Plan prompt (`PLAN_PROMPT_TEMPLATE`, `SPEAKER_RULE`, new `LINES_RULE`)

**(a) Cast line.** The template text `"cast: a list with one object per character who is ever on screen, with the keys id, phrase and descriptor. id is c1, ..."` becomes:

`"cast: a list with one object per individual character who acts or speaks on screen, with the keys id, phrase and descriptor; a group of people (a crowd, an audience, fans, spectators, a team) is never a cast entry, and belongs in the setting sentence of its place. id is c1, c2, c3 and so on, in order. ..."`

The rest of the line is unchanged.

**(b) Setting line.** `"names the period, the place, the ground and the light.\n"` becomes `"names the period, the place, the ground, the light and any crowd or other group of people in the background.\n"`.

**(c) Beat keys.** `"arc, action, shot, camera, location, cast and speaker. index runs from 1 to @@PANELS@@."` becomes `"arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to @@PANELS@@."`, and `"at most @@MAX_CAST@@.@@SPEAKER_RULE@@\n"` becomes `"at most @@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"`.

**(d) `SPEAKER_RULE`:**
```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, and the camera may stay static, "
                "push in, pull back or track them, as long as their face stays in frame and lit "
                "while they speak.")
```
`SILENT_SPEAKER_RULE` is unchanged.

**(e) `LINES_RULE`** (used only when there are spoken lines):
```python
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when together they "
              "are at most @@LINE_WORDS@@ words. Give each line its own beat whenever there are at "
              "least as many beats as lines.")
```

**(f) Spoken lines block.** This is appended to the narrative value (QL6). The hockey 2x145 prompt therefore reads:
```
Narrative to adapt:
A hockey player ... then skates away.

Spoken lines (the narrative quotes these words; the movie must speak every one of them on camera, word for word, in this order):
1. "Getting the best deal on hockey isn't a hat trick..."
2. "It's just FuboTV."

The target output goal is ...
```

The beats line ends `... cast is the list of ids of the characters on screen in the beat, at most 4.` + `SPEAKER_RULE` + `LINES_RULE` (with `13`).

### 7.2 Panel prompt

```python
KEY_LINE_TEMPLATES["dialogue_fixed"] = (
    "dialogue: exactly @@LINE@@ -- the narrative's own words, which @@SPEAKER@@ says aloud in "
    "this panel; copy them unchanged, because the pipeline uses the narrative's words whatever "
    "this field holds.")
SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: they may move as the "
                            "beat says, but write the motion so that their face is toward the "
                            "camera, in frame and lit while they speak -- a speaker who approaches "
                            "the camera speaks once close -- and do not write the spoken words or "
                            "a speaking verb here; the pipeline adds them.")
SPEAKING_IMAGE_SENTENCE = (" @@SPEAKER@@ is the only person in the foreground, facing the camera; "
                           "any crowd stays in the background.")
SPEECH_FRAMING_SENTENCE = (" Characters speak on screen in this movie: keep each character within "
                           "medium to close-up range of the camera while they speak, and never "
                           "have a character shrink into the distance or leave the frame before "
                           "their line ends.")
```

`no_stills_prompt_speaking` keeps its construction (`:1286-1290`). The replacement text becomes:

`"fills the full @@SECONDS@@ seconds with the one continuous movement of @@SPEAKER@@ that the beat describes, keeping their face toward the camera while they speak, "`

None of these strings contains "slowly", so `test_pacing_panel1_prompt_and_no_slowly` holds.

### 7.3 Critic prompt

The spoken lines block follows the narrative (QL11). The new field line:
```python
CRITIC_Q1_FIELD_LINE = (
    '- target "panel", field "dialogue", index = the number of the panel that shows the line '
    "being said, only when a [hard] Q1 problem names a spoken line: replacement is the "
    "speaker's referring phrase, a colon and then that spoken line, or several consecutive "
    "spoken lines, copied word for word from the Spoken lines list in their order; the pipeline "
    "makes that character the panel's speaker. This is the only patch that adds spoken words.")
```

---

## 8. Tests

### 8.1 New: `tests/test_narrative_fidelity.py`

The file follows the `tests/test_dialogue.py` conventions:
- stdlib plus pytest;
- modules loaded by path;
- the autouse `story_env` fixture (`seu.set_story_env`) and `ws = seu.make_ws(tmp_path)`;
- every `_Run` and `ctx` under `tmp_path`.

No test renders, contacts a server or reads the real HOME. Helpers:
- `_hockey(case)` loads `tests/fixtures/narrative_fidelity/<case>/case.json`.
- `_hockey_ctx(ws, case, **kw)` returns `seu.make_ctx(se, ws, story_id=..., mode="chained", panels=..., seconds=..., clip_seconds=frames / 24.0, narration="speech", narrative=<narrative.txt stripped>, goal=case["goal"])`.
- `_replay(ws, case, reply_file)`:
  1. `plan, shape = se.normalize_plan(ctx, se.extract_json(reply))`;
  2. `parts` = `parts.json` panels with `index` dropped;
  3. for each `k` with `plan["beats"][k-1]["lines"]`, `parts[k-1]["dialogue"] = se.assigned_dialogue(plan, k)`;
  4. `runner = se._Run(ctx, "")`, `runner.shape = shape`, and return `runner.make_state(0, plan, parts)` with `plan`.

`T2_2X145` is `"panel 2: T2 action amount: Motion: holds 3 actions; a 6-second clip fits at most 2, so cut the extra actions and keep every other sentence word for word"`.

| ID | Covers (exact assertions) |
|---|---|
| NF1 | `classify_quotes(hockey)` equals the QL2 table's 4 tuples; `spoken_lines(hockey)` equals the 2 display lines; `line_words(line 1)` equals `['getting','the','best','deal','on','hockey',"isn't",'a','hat','trick']` |
| NF2 | edge cases, `spoken_lines(...)` for each: `She whispers, “Keep moving.”` → `["Keep moving."]`; `"Run!" he shouts.` → `["Run!"]`; `"Wait," she says, "I'm coming."` → `["Wait.", "I'm coming."]`; `He says to the old monk, "Rest here."` → `["Rest here."]`; `"Hi," the old monk says.` → `["Hi."]`; `A sign that says "OPEN" hangs on the door.` → `[]`; `The scoreboard says "GOAL".` → `[]`; `The shop called "Joe's" is closed.` → `[]`; `He called out "Over here!"` → `["Over here!"]`; `The monk says nothing, pointing at the "EXIT" sign.` → `[]`; `He nods. "Go!" flashes on the screen.` → `[]`; `He says "Keep moving.` → `[]`; `He says "".` and `He says "...".` → `[]`; `He says "Wait…"` → `["Wait..."]`; `He says "Keep moving" and leaves.` → `["Keep moving."]`. Review cases, whose non-speech quotes are not required: `A sign says "OPEN" and he says "Come in."` → `["Come in."]`; `He looks at the "FuboTV" logo and says "Wow."` → `["Wow."]`; `He wears a "Fubo" cap and says nothing.` → `[]`; `He says nothing and points at the "EXIT" sign.` → `[]`; `He calls his dog "Rex"` → `[]`; `The crowd chants "Go Fubo!" as he says hello.` → `[]`; `The crowd yells "Goal!"` → `[]` (a group is never a speaker). Every case above was verified with the reviewer's prototype, extended per QL1/QL2 (25 of 25), and NF1 is unchanged |
| NF3 | `line_words` is insensitive to case, curly apostrophes and a trailing ellipsis or full stop; non-ASCII `"Café au lait, s’il vous plaît."` → `['café','au','lait',"s'il",'vous','plaît']` |
| NF4 | `required_lines` for narration True/"speech" (2 lines) and False (`[]`) |
| NF5 | `spoken_lines_problem`: the 15-word line (`OVER_CAP` of test_dialogue) gives exactly `"the narrative's spoken line 1 (\"I carry a sealed letter from the harbour master for the abbot of this temple.\") is 15 words in 1 sentence; no clip fits it, because a spoken line has at most 14 words in at most 3 sentences; split it into shorter quoted lines in the narrative"`; a 4-sentence line gives the same form with `in 4 sentences`; a 10-word line at `seconds="4"`, `clip_seconds=97/24` gives the exact "use longer clips" message with `fits at most 9 words in 1 sentence`; 3 six-word lines with `panels=1` give the exact panels message with "need at least 2 panels"; hockey with panels 2/145, 1/145 and 1/241 gives `None` |
| NF6 | `panels_needed`: hockey at 6.04 s gives 1; 3 six-word lines at 6.04 s give 2; 4 four-word lines give 2 |
| NF7 | `spoken_line_problems` on hand-built dialogues: both lines in panels 1/2 → `[]`; both in panel 1 → `[]`; line 2 missing → `[Q1_MISSING % (2, ...)]`; lines in panels 2/1 → `[Q1_ORDER % (2, ...)]`; line 1 split across panels 1-2 → MISSING 1; extra words around → `[]`; an N18 Dialogue (`"the stranger: ..."`) counts as empty; a duplicated required line needs two occurrences |
| NF8 | **replay 2x145 recorded** (`plan_reply_1.txt`, without QL8b): `state["hard"] == [T2_2X145, Q1_MISSING % (2, "It's just FuboTV.")]`; `se.blocking(state["hard"]) == [<the Q1>]`; the advisory holds the exact P15 note of GC3 and no P12; `plan["beats"][1]["cast"] == ["c1"]` |
| NF9 | **replay 1x241 recorded** (without QL8b): `state["hard"] == [Q1_MISSING % (1, line1), Q1_MISSING % (2, line2)]` |
| NF9b | **replay with QL8b.** `_replay` with `se.assign_missing_lines(ctx, plan)` called between steps 1 and 2. For 2x145: beats' lines `[[1], [2]]`; beat 2 speaker `c1`; the returned notes are exactly `["beat 1: P14 speaking beat: line 1 given to this beat by the pipeline, because the plan gave it to no beat", "beat 2: P14 speaking beat: line 2 given to this beat by the pipeline, because the plan gave it to no beat"]`; `state["hard"] == [T2_2X145]`. For 1x241: lines `[[1, 2]]`; speaker `c1`; shot and camera unchanged (`medium shot`, `tracking`); the notes are the two "given" notes for beat 1; `state["hard"] == []` |
| NF10 | **replay fixed fixtures.** 2x145 `plan_reply_fixed.json`: `hard == [T2_2X145]` and blocking `[]`; `"Dialogue: the FuboTV player: Getting the best deal on hockey isn't a hat trick...\n"` and `"Motion: The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice mist into the air. He holds the pose, then skates away from the camera. The FuboTV player faces the camera. The camera stays static.\nDialogue: the FuboTV player: It's just FuboTV.\n"` are in `state["text"]`, and the text ends with the latter. 1x241 `plan_reply_fixed.json`: `hard == []`; `speech_notes == []`; the beat stays (`"medium shot"`, `"tracking"`); the text holds `"Motion: The FuboTV player skates forward toward the camera, then stops abruptly in a hockey stop, spraying ice mist into the air. He then skates away from the camera. The FuboTV player faces the camera. The camera tracks alongside the movement.\nDialogue: the FuboTV player: Getting the best deal on hockey isn't a hat trick... It's just FuboTV.\n"`; the Image line ends `" The FuboTV player faces the camera. The shot is a medium shot."` |
| NF11 | re-check with a plan. Write NF10's 2x145 normalized plan to `<story_dir>/plan.json` and its `state["text"]` to `<story_dir>/story.md`; call `se.recheck(ctx, lambda path, panels, no_stills=False: [])`. With the file as written → rc 0. With the line `Dialogue: the FuboTV player: It's just FuboTV.` deleted → rc 2, and stderr has `"  - " + Q1_MISSING % (2, "It's just FuboTV.")`. With the same deleted file and `ctx._replace(narration=False)` → no Q1 in stderr |
| NF12 | plan prompt (hockey, 2 panels, 6 s): contains the 7.1 (f) block exactly, `"location, cast, speaker and lines. index runs"`, `"at most 4." + SPEAKER_RULE + LINES_RULE.replace("@@LINE_WORDS@@", "13") + "\n"`, the 7.1 (a) and (b) texts, no `@@`; 1 panel at 241/24 → `"at most 14 words."`; the seu narrative (no quotes) → no `"Spoken lines ("`, `"cast and speaker. index runs"`, no `"lines is the list"`; `narration=False` with the hockey narrative → no block, `SILENT_SPEAKER_RULE` |
| NF13 | `coerce_speakers` lines (a 3-line narrative `The courier says "Keep moving." Then he says "The gate is close." At the gate he whispers "We made it."`, chained 3): (a) `[[1],[2],[3]]` with speakers → kept, `speech_notes == []`; (b) `[2,1]` / `[2]` / `[4]` → beat 1 `[1,2]`, the exact "earlier beat" and "no spoken line 4" notes, `line_assignment_problems == ['plan: Q1 spoken line: spoken line 3 "We made it." is in no beat\'s lines; put 3 in the lines of the beat whose action surrounds it in the narrative, and give that beat a speaker']`; (c) speaker `""`, cast `["c1"]`, lines `[1]` → speaker `c1` and the exact "speaker set to 'c1'" note; (d) cast `["c1","c2"]` → the exact "line(s) 1 dropped: the beat has no speaker" note; (e) two 7-word lines at 6 s → the exact fit note, `[1]` kept; (f) a narrative without quotes, lines `[1]` → `[]`, no note; (g) `_clean_lines` with `"1"` → `[]` and `["2", True, 1.0, 3]` → `[2, 3]` |
| NF14 | `plan_round` with the fake agent, hockey ctx: replies [recorded, fixed] → 2 plan calls; the attempt-2 prompt contains `"- plan: Q1 spoken line: spoken line 1 "` and `"- plan: Q1 spoken line: spoken line 2 "`; the returned plan is the fixed one; replies [fixed] → 1 call |
| NF15 | writer, fixed 2x145 plan: the panel 2 prompt has `'\ndialogue: exactly "It\'s just FuboTV." -- the narrative\'s own words, which "the FuboTV player" says aloud in this panel; copy them unchanged, because the pipeline uses the narrative\'s words whatever this field holds.'` (with the trailing newline); `parse_panel_reply` with `dialogue` `"Something else."`, and with no dialogue key, gives `"It's just FuboTV."`; `empty_parts(..., ctx)["dialogue"] == "It's just FuboTV."` |
| NF16 | the SM2 table: shots mode, beat 2 speaking, for all 6 `SHOT_TYPES` × 8 `CAMERA_KEYS` (plus `""`), the coerced `(shot, camera)` and the presence of each note; chained beat 3 is never coerced |
| NF17 | `pasted_pieces`: chained k=2, tracking, speaking → motion `["The courier faces the camera.", "The camera tracks alongside the movement."]`; chained k=2, `slow pan left` → `["The courier faces the camera.", "The camera stays static."]`; shots k=2, `slow pull-back` → image facing `"The courier faces the camera."` and motion `["The courier faces the camera.", "The camera pulls back."]`; no_stills k=2, static → `[..., "The courier faces the camera.", "The camera stays static."]`; no constant `MOVING_FACING_SENTENCE` exists in either module |
| NF19 | N17 camera: `"The camera slowly pans left."` gives the exact SM5 message; `"The camera tracks the courier."`, `"The camera pulls back."`, `"The camera follows the courier."` give none |
| NF20 | the 7.2 constants are byte-exact; the `no_stills_prompt_speaking` text; `SPEECH_FRAMING_SENTENCE` |
| NF21 | `repairable_ids(["story: Q1 spoken line: x", T2_2X145]) == {2: {"T2"}, "story": {"Q1"}}` |
| NF22 | `is_group_entry`: phrases ending in each of `crowd`, `fans'`, `team`, `people`, `spectators` → True; `"the team captain"`, `"the crowd's leader"`, `"the FuboTV player"` → False; descriptor `"a dense group of spectators ..."` with phrase `"the onlookers"` → True; `"a man with a group of friends"` → False; any entry with `cast_name` set → False |
| NF23 | `normalize_plan` on the 2x145 recorded reply: cast ids `["c1"]`; `cast_notes` is the exact GC3 note; `plan_checks(...)[1]` has the P15 note after any P13 and before `speech_notes`; a group id given as a speaker gives the existing "not a cast id" note |
| NF24 | `apply_patches` Q1 path, unit cases, with `repairable={"story": {"Q1"}}` unless stated. "rec" is the `_replay` plan and parts of the recorded reply; "fix" is those of the fixed reply. "seu3" is a chained `seu.plan_json("chained", 3)` with the NF13 3-line narrative, beat 2 cast `["c1", "c2"]` and beat 3 speaker `c1`. Cases: (a) rec 2x145, panel 2 `"the FuboTV player: It's just FuboTV."` → applied; beat 2 speaker `c1`, lines `[2]`; `parts[1]["dialogue"] == "It's just FuboTV."`. (b) rec 1x241, panel 1 `"Getting the best deal on hockey isn't a hat trick... It's just FuboTV."` with no prefix → applied via the sole cast member; lines `[1, 2]`. (c) seu3, panel 2 `"Keep moving."` → `"name the speaker: start the replacement with their referring phrase and a colon"`. (d) rec 2x145, panel 2 `"It is just Fubo."` → `Q1_ONLY_REASON % 2`. (e) fix 2x145, panel 1 `"the FuboTV player: Getting the best deal on hockey isn't a hat trick... It's just FuboTV."` → `"spoken line 2 is already given to beat 2"`. (f) rec 2x145, panel 1 `"the FuboTV player: It's just FuboTV."`: panel 1 already says line 1, so `want` is `{1, 2}` → applied; beat 1 lines `[1, 2]`; `parts[0]["dialogue"] == "Getting the best deal on hockey isn't a hat trick... It's just FuboTV."`. (g) rec 1x241 with a ctx of `seconds="4"`, `clip_seconds=97/24`, panel 1 as in (b) → `"the new line is 13 words in 2 sentences; at most 8 words in 2 sentences fit this clip"`. (h) seu3, panel 3 `"the old monk: The gate is close."` → `"panel 3's speaker is 'c1'; a spoken-line patch never changes who speaks"`. (i) rec 2x145, panel 2 `"the hockey player: It's just FuboTV."` → `"the replacement names 'the hockey player', which is no character's referring phrase; use one of: 'the FuboTV player'"`. (j) rec 2x145, (a)'s patch with `repairable={2: {"T2"}}` → `"panel 2 has no hard timing or amount-of-action problem; advisory findings are never patched"`. (k) fix 2x145, panel 2 `"Short."` with `repairable={2: {"T1"}}` → `"panel 2 says the narrative's spoken line(s) 2, which are never rewritten"`. (l) seu3: an `apply_patches` call with panel 1 `"the courier: Keep moving."` → applied, lines `[1]`. A second `apply_patches` call, on that result, with panel 1 `"the courier: The gate is close."` (line 2 only) → applied, lines `[1, 2]`, dialogue `"Keep moving. The gate is close."`. (m) seu3 after (l)'s first call, panel 1 `"the courier: We made it."` → `"the replacement must keep panel 1's spoken lines and add only an adjacent line"`. (n) seu3 with beat 1 speaker `c1` and writer dialogue `"Hello there. Keep moving."`, panel 1 `"the courier: The gate is close."` → `"panel 1's Dialogue: has words that are not the narrative's spoken lines, and existing Dialogue words are never rewritten"` |
| NF25 | the critic prompt for the 2x145 recorded state contains the spoken lines block right after the narrative and `CRITIC_Q1_FIELD_LINE` right after the T1/N18 dialogue line; `critic_field_lines(mode, None)` is unchanged; `narration=False` → no Q1 line |
| NF26 | `load_plan` on a plan.json without `lines`, `spoken_lines` or `cast_notes` → defaults |
| NF27 | `plan_checks` with `narration=False` and the hockey narrative → the exact Q2 message |
| NF28 | **engine, the 2x145 failure** (`_run`-style, fake agent): plan `[recorded, recorded]`; panel `{1: [recorded p1], 2: [recorded p2]}`; critic `[seu.answer(seu.critic_json((7,6,6), "revise", [patch(panel 2, motion, "The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera.")]))]`. Asserts: 2 plan calls (the retry gate fires); the round_0 plan.json has beats' lines `[[1], [2]]`, beat 2 `speaker == "c1"` and `cast == ["c1"]`, and its `speech_notes` are the two NF9b 2x145 notes; round_0 `story_checks.json` hard ids `["T2"]` (**no Q1**); the panel 1 prompt has the `dialogue_fixed` key line with the line-1 text; round_1 `critic.json` applied the patch; rc 0; stop `passed`; 1 critic call; the final story.md has `"Dialogue: the FuboTV player: Getting the best deal on hockey isn't a hat trick...\n"` in panel 1 and ends with `"## Panel 2 — The FuboTV Hockey Stop\nMotion: The FuboTV player skates forward, then halts in a sharp hockey stop that sprays ice mist into the air. He skates away from the camera. The FuboTV player faces the camera. The camera stays static.\nDialogue: the FuboTV player: It's just FuboTV.\n"` |
| NF29 | **engine, the 1x241 failure**: plan `[recorded, recorded]`, panel `{1: [recorded]}`, critic `[]`. Asserts: 2 plan calls; round 0 hard `[]` (**no Q1**); stop `passed`; 0 critic calls; rc 0; the story.md Motion/Dialogue lines equal NF10's 1x241 lines; `speech_notes` are the two NF9b 1x241 notes |
| NF30 | **Q1 blocks when no beat is eligible.** Use `seu.plan_json("chained", 3)` with the NF13 3-line narrative, every beat's cast `["c1", "c2"]` and no speakers. Plan `[that, that]`, seu panel replies, critic `[{"answer": "x"}] * 4`. Asserts: `assign_missing_lines` gives no note (no eligible beat); rc 2; stderr has the three Q1_MISSING messages, each as `"  - " + msg`; final `story_checks.json` hard ids `["Q1", "Q1", "Q1"]`; 4 critic calls; the story.md has no Dialogue line. The critic's Q1 patch path for such a run is covered by NF24 |
| NF31 | **pre-flight**: the NF5 3-line narrative with panels 1 → rc 2; stderr is exactly `"Error: " + <panels message> + "\n"`; the agent log is empty; `run.json` exit 2 |
| NF32 | `--no-narration` with the hockey narrative (seu plan and panel replies, `narration=False`): rc 0; no Q1; the round-0 advisory holds the Q2 message; plan_prompt.txt has no `"Spoken lines ("` |
| NF33 | default narration (`True`) with the hockey narrative. Plan `[fixed 2x145]`, panel `{1: [recorded p1], 2: [recorded p2, recorded p2]}` (the code-only round re-asks panel 2), critic `[{"answer": "x"}] * 4`. Assert: 1 plan call (no retry); `assign_missing_lines` gives no note; round-0 hard ids `["T2"]` (no Q1, and no N11, because a speaking panel's empty Narration is allowed); rc 0 with `"Warning: unresolved after 2 critic round(s): " + T2_2X145`; story.md holds both Dialogue lines |
| NF34 | `character_lib.insert_speech(..., first_action=True)`, with phrases `["the FuboTV player"]` and `S` = any speech text. The 2x145 panel 2 Motion of SP-P → the worked-example order. `"The courier faces the camera. The courier runs. The courier waves. The camera stays static."` (phrases `["the courier"]`) → `"The courier runs. The courier faces the camera. S The courier waves. The camera stays static."`. `"The courier runs. The courier waves."` → `"The courier runs. S The courier waves."`. A one-action Motion → identical to `first_action=False`. `first_action=False` reproduces every DLG4 case. `is_facing_sentence` is case-insensitive |
| NF35 | the manifest (`_manifest_ws`/`_manifest_argv` of test_dialogue, chained, 2 panels, `frames=145`, plan with cast `the FuboTV player`). Panel 2 of the SP-P worked example → `motion_prompt` equals the worked example with `<AC>` = `ACOUSTIC_SENTENCE`; with `--speech-delivery plain` → the plain variant. The same panel under `--shots` gets the same placement. A no_stills `Prompt:` panel with two action sentences keeps today's placement (before the trailing camera run) |
| NF36 | Q3: the narrative `He says "Go.` → the advisory exactly `"plan: Q3 quotes: the narrative has an odd number of double quotes (1), so its last quote is unmatched and ignored; close every quoted line"`; hockey (8 quotes) → none; it fires for narration `True`, `"speech"` and `False` alike |
| NF37 | `assign_missing_lines` unit cases, chained 3 with the NF13 narrative, cast `c1`/`c2`, no `lines` given. (a) Every beat `["c1"]` and no speakers → lines `[[1], [2], [3]]`, three "given" notes, beat 1 shot and camera unchanged. (b) Beat 2 cast `["c1", "c2"]` → `[[1], [], [2, 3]]`. (c) Plan lines beat 1 `[1]` and beat 2 `[3]`, with speakers `c1` → line 2 goes to beat 2 (`[2, 3]`), never to beat 3. (d) A 1-beat plan at 6 s whose two lines are 7 words each → beat 1 `[1]` only; `line_assignment_problems` still lists line 2 |
| NF37b | `assign_missing_lines` keeps each beat's lines a consecutive run and repeats until nothing changes. (a) Beat 1 `[1]`, beats 2 and 3 two-cast without speakers, line 2 too long to fit, line 3 short → `[[1], [], []]`, no notes (line 3 never joins `[1]` as `[1, 3]`). (b) Five lines, beats 1 and 2 two-cast, beat 3 holds `[5]` → `[[], [], [3, 4, 5]]` with the notes for line 4 then line 3 (line 2 does not fit: 13 words in 4 sentences, 11 fit). (c) Beats 1 and 2 two-cast, beat 3 holds `[3]` → `[[], [], [1, 2, 3]]`, notes for line 2 then line 1. A second call returns `[]` and leaves the plan unchanged |

### 8.2 Fixtures: `tests/fixtures/narrative_fidelity/`

Verbatim copies, byte for byte, made at implementation time:
- `narrative.txt` ← `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/hockey/narrative.txt`.
- `hockey-2x145/{plan_reply_1.txt, panel_01_reply_1.txt, panel_02_reply_1.txt, parts.json}` ← `generated/stories/hockey-2x145/story_rounds/round_0/` (same names).
- `hockey-1x241/{plan_reply_1.txt, panel_01_reply_1.txt, parts.json}` ← `generated/stories/hockey-1x241/story_rounds/round_0/`.

Hand-written files:
- `hockey-2x145/case.json`: `{"story_id": "hockey-2x145", "panels": 2, "seconds": "6", "frames": 145, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}`.
- `hockey-1x241/case.json`: the same, with `"hockey-1x241"`, `1`, `"10"` and `241`.
- `hockey-2x145/plan_reply_fixed.json`: the JSON of `plan_reply_1.txt` with `beats[0]["lines"] = [1]`, `beats[1]["speaker"] = "c1"` and `beats[1]["lines"] = [2]`. Everything else is identical; the crowd `c2` is deliberately kept, so normalization removes it.
- `hockey-1x241/plan_reply_fixed.json`: the JSON of `plan_reply_1.txt` with `beats[0]["speaker"] = "c1"` and `beats[0]["lines"] = [1, 2]`.

### 8.3 Existing tests that change

**A. Must be updated, only for the stated reason:**

| Test | Reason |
|---|---|
| `test_dialogue.py::test_dlg11_speaking_beat_coercion` | SM2: beat 2 keeps `tracking` → `("medium close-up", "tracking")`; the camera note leaves `speech_notes` (3 notes); `[-4:]` → `[-3:]` |
| `::test_dlg12_plan_prompt_speaker_rule` | `spoken` = the new `SPEAKER_RULE` (7.1 d) |
| `::test_dlg13_writer_keys_and_speaking_key_lines` | the three asserted strings: `SPEAKING_ACTION_SENTENCE`, the no_stills speaking text, `SPEAKING_IMAGE_SENTENCE` (7.2) |
| `::test_dlg15_assembly_goldens_and_dedupe` | panel 2 is `wide shot`/`tracking`, and only the camera sentence changes. In `GOLDEN_SPEAKING`, each speaking panel's `"The camera stays static."` that follows `"The courier faces the camera."` in Motion (chained, shots) or Prompt (no_stills) becomes `"The camera tracks alongside the movement."`. The later shots speaking assertions: Motion `"The courier turns. The camera slowly pans left. The courier faces the camera. The camera tracks alongside the movement."`; `pasted_pieces` `["The courier faces the camera.", "The camera tracks alongside the movement."]` |
| `::test_shots_s5_ignores_the_pasted_facing_sentence` | the suffix becomes `" The courier faces the camera. The camera tracks alongside the movement."`; nothing else changes |
| `::test_n16_n17_n18_dialogue_messages` | the N17 camera message (SM5) |
| `::test_dlg22_the_critic_rewrites_one_sentence` | the suffix becomes `" The courier faces the camera. The camera tracks alongside the movement.\n"` |
| `test_story_engine.py::test_rst13_normalization` | `list(plan["beats"][0])[-1] == "lines"` |
| `::test_rst39_outputs_and_layout` | the plan key list gains `"spoken_lines", "cast_notes"` before `"speech_notes"` |
| `test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | G6, in a separate test-only follow-up commit: `BASELINE` = the feature commit's SHA, with `", then to <sha> (narrative dialogue fidelity)"` appended to the comment |

**B. Re-run; edit only for an A reason:**
- `test_dialogue.py`: `::test_dlg_h_offline_merge_gate`, `::test_dlg14`, `::test_dlg19`, `::test_dlg20`, `::test_dlg23`, `::test_dlg24`, `::test_ff3`, `::test_ff4`, `::test_ff5`, `::test_empty_parts_uses_panel_keys_with_ctx`, `::test_review_focus_1`.
- `test_story_engine.py`: `::test_rst8`, `::test_rst16`, `::test_rst22`, the `_speaker_plan`/`_over_cap` users, `::test_pacing_camera_sentences_classify_as_before`, `::test_pacing_panel1_prompt_and_no_slowly`.
- `test_judge_story.py` tests that call `build_critic_prompt`.

**C. Must pass unchanged:**
- `test_rst40`, `test_rst41`, `test_rst61`, `test_rst62`;
- `test_shots_mode.py::test_s52`, `::test_s20`;
- `test_casting_regression.py`;
- the manifest tests: DLG7-DLG10, `test_review_focus_2`, `test_review_focus_3` and `test_ltx_story_manifest_chain.py::test_v2_golden_byte_identical`. Every speaking Motion in them has one action sentence, so SP-P leaves them byte-identical;
- `test_dialogue.py::test_dlg4_insert_speech_placement` and `test_character_lib.py::test_spoken_narration_helpers` (`first_action` defaults to False);
- `test_ltx_movie_offline.py`.

---

## 9. Rollout

1. Copy the fixtures (8.2). Implement G1, G2, G2b, G3 and G5 in one feature commit.
2. Run NK2-NK7 and the full suite.
3. Opus design review of the diff against this spec.
4. Make the test-only follow-up commit G6 (`test_mut26`), then measure NK1.
5. Post-merge: the live NK8 reruns. Record exit codes, the Dialogue lines and the whisper transcripts in the PR.

**PR note (required text, in substance).** An existing story whose narrative quotes spoken lines, written before this change, now exits 2 on re-check (Q1) when a quoted line is missing from its `Dialogue:` fields. `bin/ltx-movie` re-checks an existing story.md unless `--force-story` is given. Either rerun with `--force-story` to regenerate it, or hand-add the `Dialogue:` lines the error names.

---

## 10. Values chosen by the spec

1. The quote grammar normalizes curly quotes to straight ones and pairs them left to right. An unmatched last quote is ignored, and Q3 reports an odd count.
2. A quote is speech when a speech verb lies in a clause-bounded window: 6 words before or 4 words after. The window is cut at `CLAUSE_STOP_WORDS` (and, then, as, ...).
3. The verb list is fixed. The call verbs count only before "out". A verb right after `that`, `which`, `it`, a text-surface noun or a group noun does not count.
4. Matching uses words only: case and punctuation, ellipsis included, are ignored. The display text keeps the author's punctuation, including "...".
5. Lines reach beats through a numeric `lines` key. Code pastes the verbatim words, so the writer can never paraphrase a required line.
6. A beat may hold consecutive lines within the fragment-aware cap. The plan prompt states the 2-fragment cap and asks for one line per beat when beats allow.
7. A speaking beat without lines keeps its speaker, and its writer writes the line. Q1 counts it if it matches.
8. Repair order:
   1. the plan-retry gate on unassigned lines;
   2. the deterministic QL8b assignment (first eligible beat, in order; it fills gaps only);
   3. the state-level Q1, which is hard and blocking;
   4. the critic's Q1 patch.
9. The critic's Q1 patch uses the `dialogue` field. It sets the speaker from the phrase, the existing speaker or the sole cast member. It keeps the panel's lines and extends them only contiguously. Its stored text is canonical. There is no new patch field.
10. Q1 is a user-approved exception to D6. D6's other limits hold.
11. An infeasible line set is exit 2 before any model call. It suggests more panels, longer clips or shorter quotes. New messages use correct sentence plurals; existing pinned texts are unchanged.
12. With `--no-narration`, lines are not required and Q2 is advisory.
13. F2: MCU is the coercion target for a wide shot. A medium shot is kept. Pans and tilts become static; tracking, push-in and pull-back are kept. Chained `k >= 2` speaking panels paste the beat's camera. There is one facing sentence.
14. `SPEECH_FRAMING_SENTENCE` is relaxed to "while they speak".
15. SP-P: in chained and shots Motion with two or more action sentences, speech goes after the first action sentence and the facing sentence moves to just before it. no_stills Prompts and one-action Motions are unchanged. Only the manifest composes; engine assembly is unchanged.
16. F3: groups are detected by head noun or by a "group of" descriptor. They are dropped from the cast with a P15 advisory. Library characters are exempt.
17. `SPEAKING_IMAGE_SENTENCE` says "in the foreground".

---

## 11. Open risks and questions

### 11.1 Risks

- **R1.** The speech-verb rule misreads some narratives.
  - Missed speech: "shouts at the top of his lungs, "..."" (the verb is 7 words back) and screenplay form.
  - False speech: "what he calls "freedom"". This is a branding-style quote next to a speech verb.
  - Mitigation: NF2 pins the behaviour, and the Q1 message quotes the line, so the user sees exactly what is required.
- **R2.** F2 trades lip-readability for fidelity. The 2x145 clip already showed a far, approaching speaker reading as voice-over, and a tracking or pull-back speaker may lip-sync worse. The guidance is writer text and the N17 advisory only. NK8's whisper and lip-sync review measures this.
- **R3.** The group list is closed. "the soldiers" stays cast. "the fans" as real protagonists (two fans who talk) would be removed; P15 says so, and `--character` exempts them.
- **R4.** A Q1 patch that makes a panel speak applies the SP2 cast coercion. Another character in that beat loses their identity sentence ([DLG] R11).
- **R6.** A spoken ellipsis ("trick...") is kept. LTX may trail off or pause there. The live A/B in NK8 shows whether it does.
- **R7.** Q1 ignores who speaks (0.4). A line given to the wrong character passes.
- **R8.** The plan-retry gate spends a second plan call (about 60 s here) whenever the planner skips `lines`.
- **R9.** With QL8b, the critic is needed only when no beat is eligible: every beat that could take the line has two or more cast members and no speaker, or the line does not fit. The local critic may still not propose the Q1 patch, and the run then exits 2 with a precise hand-edit instruction. Recorded evidence: the qwen critic never noticed the missing line before Q1 existed. Q1 now names it as `[hard]`, with an explicit patch form.
- **R10.** Speech placement (SP-P) splits only at sentence boundaries. A single writer sentence that chains actions ("skates forward, then stops, then skates away") still has its line spoken after the whole sentence. The "one or two plain sentences" writer guidance and T2 limit how often this happens. Nothing splits clauses.
- **R11.** QL8b puts a missing line on the first eligible beat in narrative order. That beat's action may not be the one that surrounds the line in the narrative, for example when the planner gave the speaker to a later beat with no lines. The P14 note names the choice, and NK8 shows whether it is a problem in practice.
- **R12.** Stories written before this change whose narrative quotes speech now exit 2 on re-check (see the rollout PR note).

R5 (the second facing form) was withdrawn in revision 2, together with that form.

### 11.2 Decisions to confirm (the spec resolves each; flagged because each goes slightly beyond the brief's wording)

- **C1.** `SPEECH_FRAMING_SENTENCE` is relaxed (SM4). Without this, `--speech-only` still tells every writer that nobody may leave the frame, which contradicts "then skates away".
- **C2.** `SPEAKING_IMAGE_SENTENCE` changes from "the only person in the frame" to "the only person in the foreground", to match F3.
- **C3.** A speaking beat with no assigned lines in a quoted narrative may still speak a writer-invented line (QL7). The alternative is to drop such speakers. That is stricter, but it discards a writer's correct copy of a line (the recorded 2x145 panel 1). With QL8b such a beat is also eligible to receive a missing line.

### 11.3 Open

None.
