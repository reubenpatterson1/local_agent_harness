# Shot prompt format: one planned camera move, a fixed speaking order, and a format reference

Date: 2026-10-28

Status: design spec. The user approved the design brief (Section 0.0). Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `3970e96`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `3970e96`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.

Inputs:
- External research: `$S/writer-research-external.md` (LTX prompting guide, camera-movement guide, directing-dialogue guide, LTX-2 README).
- Internal audit: `$S/writer-research-internal.md` (scripts `$S/audit/m.py`, `$S/audit/sim.py`).

Specs this one builds on, cited by tag:
- **[DLG]** `docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md`: SP2 (speaking coercion), SP4 (pasted facing sentence), CM1-CM4 (camera sentences), DG5-DG7 (speech text and manifest placement), N16/N17.
- **[NF]** `docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`: SM1-SM3 (speaking shots and cameras), SP-P1 (line after the first action), QL7-QL13.
- **[WP]** `docs/superpowers/specs/2026-10-26-writer-pacing-design.md`: WP1 (`PACING_SENTENCE`, no "slowly"), WP2 (`SPEAKING_CHAINED_MOTION_SENTENCE`), WP4 (critic clause), WK7.
- **[PCP]** `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md`: P16, `SPEAKER_RULE_KEEP_CAST` (PC5).
- **[SA]** `docs/superpowers/specs/2026-10-28-speaker-attribution-design.md`: `line_speakers`, `_mentions`, `_mentions_at`, P17, D6 (old stories re-check as before).

---

## 0. Purpose and scope

### 0.0 The approved design (binding summary)

1. **Camera.** Moves first and static last in the planner's camera list. Every beat gets one move; static only for a deliberate hold, at most `ceil(panels/3)`. Speaking beats prefer push-in, pull-back, tracking or handheld and avoid pans. The writer is told the planned move and writes the one camera sentence itself, with end framing ("as the move completes, ..."). The pipeline appends the planned camera sentence only when the writer wrote none, speaking panels included. A new hard check catches more than one camera sentence, or static mixed with a move, in one panel. A static-ratio check runs over the plan.
2. **Dialogue.** A speaking panel follows a fixed order: framing, action, `Name says, "…"`, one reaction by the speaker, camera sentence, and the acoustic sentence last. Nobody exits and nobody else acts after the quote. N7 (a speaking verb without a quote) becomes hard and is repaired automatically.
3. **Format reference.** A three-panel reference (an old woman closing a fish market at dawn) goes into the writer prompt, labelled "FORMAT REFERENCE ONLY — never reuse its people, places, objects or words". A hard check catches copying from it.
4. **Out of scope:** voice descriptors, phrase/cue/phrase line splitting, the prompt enhancer, and narration-mode voice-over.
5. **Tests and live acceptance:** Sections 4 and 5.

### 0.1 Problem (each item verified at `3970e96` unless marked audit)

- **E1. Most panels are static.**
  - Audit: 17 `story.md`, 43 panels, 25 static (58%). Speaking beats were static 20/27 times, and the planner never picked a pan or tilt for one.
  - Recount of the 12 story directories now under `generated/stories/` (`plan.json` beats): 27 panels, 14 static (52%); speaking beats 12/17 static (71%).
- **E2. A panel can carry two contradictory camera directions.** `generated/stories/hockey-2x145-f/story.md:11` reads: `... then pushes off and skates away from the camera. The camera holds on him as he recedes. FuboTV hockey player faces the camera. The camera stays static.` The writer's "holds on him as he recedes" and the pasted "stays static" both reach the final prompt (`manifest.json` panel 2).
- **E3. The writer writes a speaking verb without a quote.** `generated/stories/pin-sh2-b/story.md:11` has `The woman in grey turns her head toward the camera and speaks.` The planner's beat action is the source: `pin-sh4-a/story_rounds/round_0/panel_02_prompt_1.txt` shows the beat `... turns to face the camera and speaks the words ...`.
- **E4. Action and exits come after the quote.** `generated/stories/hockey-2x145-p/manifest.json` panel 2 composes `... says, "It's just FuboTV." The audio is clear close-mic dialogue ... FuboTV hockey player pushes off and skates away at real-time speed. The camera stays static.` The audit found post-quote exits or third-party action in 5 of 27 speaking panels.
- **E5. The acoustic sentence is not last.** Every composed speaking prompt is `action, facing, quote, acoustic, [after-action], camera`.
- **E6. The writer never sees the planned camera or a finished example.** No key line names the planned move (`story_engine.py:1944-1984`). `COPIED_EXAMPLES` (`:1885-1892`) is used only for copy detection.
- **E7. The shots writer is asked for 5-14 words** (`panel_02_prompt_1.txt`: `motion: ONE sentence of 5 to 14 words`). The LTX guidance is one paragraph of about 90-150 words per clip.

### 0.2 Causes (verified at `3970e96`)

- **C1. The planner list and rules favour static.**
  - `CAMERA_SENTENCES` lists `static` first (`story_engine.py:44-53`), and `@@CAMERA_LIST@@` (`:961`) copies that order.
  - `SPEAKER_RULE` (`:352-358`) and `SPEAKER_RULE_KEEP_CAST` (`:362-369`) say "the camera may stay static, push in, pull back or track them".
- **C2. Pans and tilts on a speaking beat become static.**
  - `speaking_coercion` (`:1350-1353`) rewrites a framed speaking beat's pan or tilt to `static`.
  - `speaking_camera` (`:1158-1160`) does the same for chained k >= 2 at paste time (`:1500`).
- **C3. A speaking panel always gets the planned camera.** The CM4 guard in `panel_fields` (`:2201`, `if not facing and ...`) keeps the pasted camera on every speaking panel, even after the writer moved the camera (E2).
- **C4. A chained silent continuation never gets the planned camera.** `pasted_pieces` (`:1499-1501`) pastes a camera on chained k >= 2 only when the panel speaks.
- **C5. The manifest orders the sentences.**
  - `bin/ltx-story-manifest:827-832` calls `insert_speech(..., speech_text(speaker, speech, delivery), [speaker], first_action=...)`.
  - `speech_text` (`character_lib.py:825-841`) appends `ACOUSTIC_SENTENCE` (`:759-760`) right after the quote.
  - `insert_speech` (`:718-749`) puts that bundle before the trailing camera run, so whatever follows the first action sentence also follows the quote.
- **C6. N7 is advisory.** `_field_checks` (`story_engine.py:2381-2387`) only advises on `DIALOGUE_RE` (`:1874-1878`). Nothing checks for an exit or another character's action after the line.

### 0.3 Grounding (verified at `3970e96`)

**`story_engine.py` (4058 lines, stdlib only).** `re` and `copy` are imported (`:11-23`).
- **Camera.**
  - `CAMERA_SENTENCES` `:44-53`, `CAMERA_KEYS` `:54`, `WORD_RANGES` `:56-58`.
  - `SPEAKING_SHOTS`/`SPEAKING_CAMERAS` `:1153-1155`, `speaking_camera` `:1158-1160`.
  - `SPEAKING_CAMERA` `:1451` is unused dead code; this spec leaves it.
  - `CAMERA_MOTION_RE` `:1454-1456`, `_sentences` `:1459-1461`, `_facing` `:1464-1467`, `_moves_camera` `:1470-1478`.
  - `pasted_pieces` `:1481-1506`, P8 `:1644-1646`, `panel_fields` `:2180-2215`.
  - `STILL_CAMERA_MOVES` `:2236-2238`, N17 camera branch `:2531-2538`.
- **Plan prompt.**
  - `PLAN_PROMPT_TEMPLATE` `:278-321`; its camera clause is at `:313`.
  - `SPEAKER_RULE` `:352-358`, `SILENT_SPEAKER_RULE` `:359`, `SPEAKER_RULE_KEEP_CAST` `:362-369`, `LINES_RULE` `:371-377`.
  - `build_plan_prompt` `:917-979`: fragments `:955-971`, scalars `:976-978`.
- **Coercion and lines.** `speaking_coercion` `:1313-1354`, `assign_missing_lines` `:1261`.
- **Shared helpers.**
  - `line_words` `:447`, `CLAUSE_STOP_WORDS` `:432`, `GROUP_NOUNS` `:436-440`, `_CLAUSE_BREAK_RE` `:415`.
  - `_mentions` `:573`, `_mentions_at` `:584`, `line_speakers` (SA1).
  - `_q` `:1414`, `speaker_phrase_of` `:1423`, `_sentence` `:146`.
- **Writer prompt.**
  - `DIALOGUE_RE` `:1874-1878`, `PLACEHOLDER_RE` `:1884`, `COPIED_EXAMPLES` `:1885-1892`, `PANEL_PROMPT_TEMPLATE` `:1901-1921`.
  - `KEY_LINE_TEMPLATES`: `chained_motion1` `:1944-1950`, `chained_motion` `:1951-1958`, `no_stills_prompt` `:1959-1970`, `shots_motion` `:1979-1984`.
  - `SPEAKING_ACTION_SENTENCE` `:2011-2016`, `SPEAKING_CHAINED_MOTION_SENTENCE` `:2019-2031`, `SPEAKING_SENTENCES` `:2044-2045`, `FIX_INSTRUCTION` `:2046-2048`.
  - `build_panel_prompt` `:2766-2852`: key-line loop `:2796-2826`, fragments `:2837-2849`.
- **Parsing, checks and repair.**
  - `parse_panel_reply` `:2145-2167`.
  - `_field_checks` `:2299-2554`: N7 `:2380-2387`; `known` `:2413`; `action_label` `:2430`.
  - `ACTION_SECONDS` `:2228`, `GENERATION_CHECKS` `:2698-2699`, `panel_checks` `:2702-2739`.
  - `CRITIC_SPEAKING_MOTION_CLAUSE` `:2925-2929`, `critic_field_lines` `:2939-2967`.
  - `apply_patches` `:3213-3306`, with the `need` set at `:3280`.
  - `REPAIR_IDS` `:3331`, `guard_problem` `:3348`, `merge_repair` `:3385-3400`.
- **Run and recheck.**
  - `_Run.go` round 0 `:3772-3790`, with `assign_missing_lines` called at `:3772`.
  - `RECHECK_IDS` `:3867-3868`, `PLAN_FREE_IDS` `:3869`.
  - `recheck` `:3969` uses `RECHECK_IDS` and never runs `plan_checks`.

**`character_lib.py` (1430 lines).**
- **Shots constants.** `SHOTS_MOTION_MIN_WORDS`/`MAX` `:43-44`, `SHOTS_MOTION_WORD_TOLERANCE` `:45`.
- **Camera detection.**
  - `_SENTENCE_SPLIT_RE` `:126`, `_CAMERA_SENTENCE_RE` `:127`, `_CHAIN_WORD_RE` `:128`, `_COMMA_AND_RE` `:130`.
  - `_CAMERA_TERM_RE` `:134`, `_CAMERA_WIDE_TERM_RE` `:138`, `_is_camera_sentence` `:984-995`.
- **Speech.**
  - `speech_sentence` `:708-715`. Its docstring records that voice descriptors made LTX-2.3 repeat lines.
  - `insert_speech` `:718-749`, `ACOUSTIC_SENTENCE` `:759-760`, `speech_text` `:825-841`.
- **Shots checks.** `FACING_SENTENCE` `:1110`, `is_facing_sentence` `:1112`, `motion_problems` `:1127-1145`, `shots_violations` `:1148`, `motion_length_advisory` `:1252-1260`, `shots_advisories` `:1263`.

**`bin/ltx-story-manifest` (947 lines).**
- `--speech-delivery` `:181-187`, `_known_phrases` `:381-398`, `_spoken` `:460-484`, `spoken = _spoken(...)` `:696`.
- The speech insertion `:827-832`; `pt` is the panel's parsed story fields (keys `image`, `motion`, `prompt`, ...).

**Callers.**
- `speech_text` and `insert_speech` are called only by `bin/ltx-story-manifest:830-831`.
- `CAMERA_SENTENCES`, `CAMERA_KEYS`, `SPEAKING_CAMERAS` and `STILL_CAMERA_MOVES` are referenced only inside `story_engine.py` and by tests.

**Tests and fixtures.**
- `tests/story_engine_testutil.py`: `plan_json` `:363-385` gives odd beats `static` and even beats `tracking`. `MOTION_SENTENCES` `:400-409`, `SHOTS_MOTION` `:432-435`, `panel_json` `:454-476`.
- `tests/test_story_engine.py::test_pacing_panel1_prompt_and_no_slowly` (`:2920-2936`) forbids "slowly" in every key line and camera sentence. That is [WP] WP1, and this spec keeps it.

### 0.4 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | SF1-SF14 (Section 2) |
| G2 | `character_lib.py` | SF15 |
| G3 | `bin/ltx-story-manifest` | SF16 |
| G4 | `tests/test_shot_format.py` (new) | SFT1-SFT25 (Section 4.1; SFT23-SFT25 from Amendment SF-A1) |
| G5 | Existing tests and fixtures | The re-baselines of Section 4.2, in a **separate test-only commit** whose body explains every changed file (Section 4.2 rule) |
| G6 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in its own follow-up commit, as in [SA] G4. The comment gains `, then to <sha> (shot prompt format).` |

**Not changed:**
- `movie_ui_lib.py`, `static/*`, `bin/ltx-movie` (including its legacy prompt at `:202`), `bin/judge-story` and `bin/ltx-mlx-render`.
- `LINES_RULE`, `LINES_PINNED_SENTENCE`, `LINE_SPEAKERS_SENTENCE`, P16 and P17. The approved item "do not drop or merge narrative lines" is already `LINES_RULE` plus P17 and Q1. **Nothing changes there.**
- `speech_text`, `insert_speech`, `speech_sentence`, `SPEECH_BEATS`, `_is_camera_sentence`, `CAMERA_MOTION_RE`, `COPIED_EXAMPLES`, `RECHECK_IDS`, `PLAN_FREE_IDS`, `NON_BLOCKING_IDS`, `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `PANEL_MAX_TOKENS`, the `plan.json` schema and the `story_checks.json` shape.

### 0.5 Out of scope and known limits

- **Voice descriptors** ("speaks in a low, tired voice") are a future A/B. `character_lib.py:708-713` records that descriptive speech wording made LTX-2.3 repeat lines. That finding conflicts with the official LTX guidance, so it needs its own render A/B.
- **Phrase/cue/phrase splitting** of one line around an acting cue is a future A/B. The fixed `SPEECH_BEATS` form ("After a breath") stays as it is.
- **The prompt enhancer** and **narration-mode voice-over** stay as they are.
- **`no_stills` ordering.** In `no_stills` only the camera rules (SF6, SF7, SF9) and the N7/N21-exit/N22 checks apply. Its Prompt keeps its pasted order (writer, identities, setting, shot, facing, camera). Its speech keeps `insert_speech`'s placement, with the acoustic sentence moved last (SF16). It gets no format reference (D9).
- **Old stories** are not repaired. The manifest composes them in the new order (SF16), but any old contradictory camera sentences stay in the prompt; regenerate with `--force-story`. Re-checking them gives the same hard list and exit code as at `3970e96` (D12).
- **Negative audio wording.** LTX-2.x runs distilled with no CFG ([WP] Section 1), so "no music" may not suppress music. LTX's own examples use the phrase. Its effect is judged in the Section 5.3 render A/B.
- **The hockey skate-away.** The hockey narrative has the speaker skate away after line 2. A speaking beat can no longer contain an exit (SF3, SF10), so in the 2-panel and 1-panel hockey configs the skate-away is left out of the movie, and the user is told with a P19 advisory that names the panel count that would keep it (Amendment SF-A1). This supersedes [WP] WK7's "the 2x145 panel 2 line comes before the skate-away" (Section 8.2, C4).
- **Future work: a soft panel count.** A separate follow-on spec will make `--panels` a target: the planner may add up to 2 panels, never fewer. That removes this limit. It is not part of this spec.
- **The `bin/ltx-story-manifest` 150-word warning** (`MAX_PROMPT_WORDS`, `:113`) can now print for speaking panels near the top of the range. It is a warning only and is left as it is.

### 0.6 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SK1 | From `WS`, `python3 -m pytest tests/ -q -rA` passes after G4-G6, apart from the pre-existing failures recorded before implementation (same tests, same messages). `python3 tests/test_ltx_movie_offline.py` prints `OK n/n`. | full run |
| SK2 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest`. | `test_rst61`, SFT1 |
| SK3 | None of the three files gains an import. | `git diff` |
| SK4 | **Planner camera contract.** The camera list puts moves first, static last and includes `handheld`. The plan prompt carries `CAMERA_RULE` with `MAX_STATIC = ceil(panels/3)`, plus `CAMERA_SPEAKING_SENTENCE` unless `--no-narration`. A framed speaking beat's pan or tilt becomes `slow push-in`, never static. After the plan, no movie has more than `ceil(panels/3)` static beats (P18 cap). | SFT2-SFT4 |
| SK5 | **One camera direction per panel.** For every mode, a panel's assembled Motion or Prompt holds exactly one camera direction, and it names the panel's camera. That holds when the writer wrote none, one valid one, a wrong one, two, or one inside an action sentence. Speaking panels drop the planned sentence when the writer's is valid. | SFT6-SFT8 |
| SK6 | **Speaking order.** In a speech movie in chained or shots mode, every composed speaking prompt has this order: the framing sentence (shots, chained panel 1), the first action, the facing sentence, the quote, the other actions, the camera sentences, then `ACOUSTIC_SENTENCE` last. Silent panels in such movies end with `AMBIENCE_SENTENCE`. Movies with no spoken panel compose byte-identically to `3970e96`. | SFT13, SFT14 |
| SK7 | **After the line.** A speaking panel whose writer text has an exit, or has another character act after the line, is re-asked once in round 0 and then trimmed. It ends with no hard N21, unless trimming would leave no action. | SFT10, SFT11 |
| SK8 | **N7 is hard while generating.** A speaking verb in a Motion or Prompt is cut or dropped at parse time. It cannot be removed only when it is the panel's sole action sentence, and then it is a hard N7. Recheck still reports N7 as advisory, exactly as at `3970e96`. | SFT9, SFT17 |
| SK9 | **Format reference.** Chained and shots writer prompts (narration not False) contain `FORMAT_REFERENCE` exactly once, before "Write this panel". Copying a reference term, or 6 consecutive reference words, gives a hard N22 that is re-asked and then trimmed. Text the narrative or plan already has is exempt. | SFT5, SFT12 |
| SK10 | **Old stories.** `recheck` of a `3970e96`-era story gives the same rc and hard list. It runs none of N20-N22, and N7 stays advisory. | SFT17 |
| SK11 | **Live, this Mac, post-merge, not a merge gate.** Section 5 KPIs K1-K7. | Section 5 |

### 0.7 Must-haves and nice-to-haves

SF1-SF16 and SFT1-SFT22 are must-haves. Nothing else is built: no CLI flag, no voice descriptors, no line splitting, no `no_stills` reordering.

---

## 1. Design decisions

### D1. The plan asks for moves; static is a capped, deliberate hold

`CAMERA_KEYS` is reordered so moves come first. The speaking-friendly moves (push-in, pull-back, tracking, handheld) lead, and static comes last.
- **`handheld` is added [spec choice].** The approved design lists it as a preferred speaking move, and LTX documents "handheld movement".
- **The pasted sentences keep their `3970e96` text [spec choice].** Writers now usually write the camera sentence themselves, so the pasted sentence is only a fallback. Keeping its text limits re-baselining, and keeps the [WP] WP1 rule that no camera sentence says "slowly". The handheld sentence is new.

`CAMERA_RULE` tells the planner: one move per beat, static only for a deliberate hold, and at most `ceil(panels/3)` static beats. `CAMERA_SPEAKING_SENTENCE` adds that a speaking beat prefers push-in, pull-back, tracking or handheld and never pans or tilts. The LTX dialogue guide recommends a slow push-in on the emotional turn and no wide pans while someone speaks (`$S/writer-research-external.md`).

### D2. A speaking pan or tilt becomes a slow push-in, not static **[spec choice]**

- `SPEAKING_CAMERAS` becomes `("slow push-in", "slow pull-back", "tracking", "handheld", "static")`.
- `speaking_coercion` and `speaking_camera` map any other camera to `slow push-in`, which is the dialogue guide's move.
- Static stays allowed for a speaking beat, because a deliberate hold is a valid choice and the cap governs it.
- Coercing to static would re-create E1.

### D3. The static ratio is a deterministic cap with an advisory note, never retried and never fatal **[spec choice]**

P18 "static camera" runs once, right after the plan is accepted (after `assign_missing_lines`). If more than `ceil(panels/3)` beats are `static`, the earliest excess static beats become `slow push-in`, and each change writes a P14-style note into `plan["speech_notes"]`. That note is advisory in every state. The **latest** static beats keep static as the deliberate holds, because a closing hold is the usual one (the reference's shot 3).

**Rejected: hard with a retry, then exit 1 (like P16/P17).**
- A retry costs a full plan call (minutes on the local Qwen) for a choice the pipeline can fix without loss.
- A retried plan can regress the things that matter: lines, speakers and cast.
- Exit 1 for a camera choice is disproportionate.

**Rejected: advisory only.** That is the status quo, and it gave 52-58% static (E1).

### D4. The writer writes the camera sentence; the pipeline's sentence is only a fallback

- **Every action key line ends with `CAMERA_WRITER_SENTENCE`.** It names the panel's camera (`panel_camera`: the planned camera, or `speaking_camera` on a chained k >= 2 speaking panel). It gives a documented wording with an end frame ("The camera pushes in — as the move completes, <what then fills the frame>.").
- **The em dash is a [spec choice].** It keeps the end frame in the same sentence without the semicolon and ", and" that the shots S5 and chained N12 checks flag.
- **The pipeline appends the planned sentence only when the writer's text has no camera direction** (CM4 without the `not facing` guard; this fixes C3).
- **Chained k >= 2 silent panels now also get the planned fallback (fixes C4) [spec choice].** Every panel then carries exactly one move, and the static cap means what it says.

### D5. N20 "camera direction" is a hard check with a deterministic repair at parse time **[spec choice]**

Detection runs on the assembled action field, so it sees the writer's text plus any pasted fallback.

**A camera direction is either:**
- a camera sentence (`_is_camera_sentence` with the cast phrases) that has a `CAMERA_MOTION_RE` word; or
- any other sentence with a `CAMERA_CLAUSE_RE` match, such as "camera holds" or "camera pushes".

**The check fails when the field has:**
- more than one direction;
- one direction that sits inside an action sentence;
- one camera sentence that has a static word (static, still, locked-off) together with a move word; or
- one camera sentence that does not name the panel's camera (`CAMERA_MOVE_WORDS`).

**The repair runs on the writer's text as soon as the reply is parsed:**
- keep the first valid camera sentence;
- drop the other camera sentences;
- cut a camera clause out of an action sentence at the nearest preceding clause boundary.

So N20 can remain only when a camera clause cannot be cut. That panel gets the round-0 re-ask (D8).

**Why deterministic.** The planned camera sentence is always a correct fallback, so a wrong or extra writer camera can be removed without any model call. The cost is losing the writer's end framing in that one panel.

### D6. Fixed speaking order, composed by the manifest **[spec choice]**

The final prompt is composed in `bin/ltx-story-manifest` by a new `character_lib.panel_prompt`. `story.md` keeps its fields.

**Order:**
1. Framing: the `The shot is ...` sentence taken from the panel's `Image:` (shots, chained panel 1).
2. The first action sentence.
3. The pasted facing sentence.
4. The quote (`speech_text` with no acoustic sentence).
5. The other action sentences: the one reaction.
6. The camera sentences.
7. `ACOUSTIC_SENTENCE`, last.

**Why the manifest.** Taking framing from `Image:` keeps `story.md`, `writer_targets` and every `story.md` golden unaffected by the framing addition.

**Scope.**
- The new composition applies only to **speech movies**: at least one panel has a speaker, from `Dialogue:` or a spoken `Narration:`.
- It applies only in `--chain` and `--shots`, where `insert_speech` already used the first-action placement.
- In a speech movie, each silent panel ends with `AMBIENCE_SENTENCE`.
- Movies with no spoken panel compose byte-identically (`test_v2_golden_byte_identical` holds).
- `insert_speech` and `speech_text` keep their contracts. The manifest calls `speech_text` with `beats-no-acoustic` and appends the audio sentence itself.

**Audio wording.**
- `ACOUSTIC_SENTENCE` gains ", and there is no music" **[spec choice]**, so that the reference's speaking shot (approved: "audio last with 'no music'") is exactly what the pipeline produces.
- `AMBIENCE_SENTENCE` is new: "The audio is the natural ambient sound of the place, with no music."

### D7. N21 "after the line": exits and other actors are hard, more than one reaction is advisory **[spec choice]**

The check runs on a speaking panel's writer action text. `compose_motion` places the quote right after the first action sentence, so "after the line" means action sentences 2..n. Camera sentences and the facing sentence are not action sentences.

**Hard, exit.** Any writer sentence of a speaking panel (before or after the line, camera sentences included) matches `EXIT_RE`.
- Before the line counts too, because a speaker who leaves before speaking breaks the speech-only framing rule (`SPEECH_FRAMING_SENTENCE`).
- Camera sentences count because E2's "holds on him as he recedes" is an exit written as a camera sentence.
- `no_stills` gets this branch only.

**Hard, other actor.** Some post-line sentence has another character as a clause subject (chained and shots).
- That character is another cast entry's mention, using [SA]'s `_mentions` (phrase, plus the library name for pinned members), or a `GROUP_NOUNS` word with at most one article.
- A subject is a mention that starts a clause piece (`_CLAUSE_BREAK_RE` split) or follows a `CLAUSE_STOP_WORDS` word.
- A mention as an object ("glances back at the ronin") is allowed. This keeps [PCP] PC8's silent co-star wording valid.

**Advisory.** More than one post-line sentence. The scripted 3-sentence chained replies of the existing tests would otherwise trigger re-asks everywhere. The KPIs bind exits and other actors, not the count.

**Repair:** the round-0 re-ask, then the deterministic trim (D8).

### D8. Repair path for the writer-format checks **[spec choice]**

Steps:
1. **Parse time (deterministic, always):** the N7 cut (D10) and the N20 repair (D5) on the action field.
2. **Round 0:** if the parsed panel still has a hard N7, N20, N21 or N22, and the panel has a writer call left (`PANEL_MAX_CALLS` is 2), the writer is re-asked once. The problems go in the existing fix block. The re-ask's reply is kept if it has no more format problems than the first.
3. **Round 0, after that:** the deterministic trim.
   - N21: cut an exit clause, or drop the sentence; drop a post-line sentence that has another actor.
   - N22: drop the sentences that copy the reference.
   - Each drop happens only if at least one action sentence remains. Camera sentences may always be dropped, because the planned fallback replaces them.
4. **Critic rounds:** the critic may patch the action field of a panel with a hard N7/N20/N21/N22, and its dialogue for N22. A code-only round may re-ask for those ids (`REPAIR_IDS`).

Every deterministic removal is recorded as an advisory: `panel K: <id> <name>: <Label>: the pipeline removed '<text>'`.

**Why this order.** The re-ask lets the writer rewrite the reaction properly. The trim is a floor, so a run never exits 2 because the writer added an exit or a stray actor. Re-asks use the existing per-panel budget, so the worst case adds one call per panel.

### D9. The format reference is a constant in `story_engine.py`, inserted only into chained and shots writer prompts of movies that can speak **[spec choice]**

- `FORMAT_REFERENCE` is one string constant: a label paragraph plus three `Shot N (...)` lines. Each line is exactly the final prompt `panel_prompt` composes from its parts (SFT13 enforces this).
- **Why a constant, not a file:** stdlib-only and byte-deterministic, with no I/O and no path resolution in tests.
- **Where it goes:** the panel prompt, between the reserved/previous lines and `@@SEED_PANEL@@`.
- **When it is left out:**
  - `no_stills`, whose Prompt has a different shape (Section 0.5);
  - `--no-narration`, where a speaking example would invite speech into a silent movie.
- **It contains no "slowly"** ([WP] WP1). Its speaker's reaction sentence begins with the speaker's phrase ([WP] WP2).

### D10. N7 is hard while generating, with a deterministic cut **[spec choice]**

- A `DIALOGUE_RE` word in the writer's Motion or Prompt is cut at the clause boundary before it ("... toward the camera and speaks." becomes "... toward the camera."). If there is no boundary, the sentence is dropped, provided another action sentence remains.
- **Hard N7** remains only when the verb sits in the panel's only action sentence and no boundary precedes it. That panel gets the round-0 re-ask.
- `generating=True` (used only by `panel_checks` and `format_problems`) makes N7's speech-verb branch on the action field hard.
- `recheck` and the plan-free report keep the `3970e96` advisory logic exactly, so old stories re-check as before ([SA] D6).
- The Image field keeps the advisory, because it feeds the still, not the video.

### D11. N22 "reference copy" is hard, with a re-ask and then a trim **[spec choice]**

**The checked fields:** the writer's Image, Motion, Prompt, Dialogue and Narration.

**A field fails when it contains either:**
- a `REFERENCE_TERMS` term, as a whole `line_words` sequence; or
- six consecutive words of any `REFERENCE_COPY_SEGMENTS` segment, with the n-grams taken within a segment.

**What is exempt:** a term or 6-gram that also appears in the narrative, the goal, or the plan's cast phrases, descriptors, settings, prop names or beat actions. A user's own fish-market story is never flagged.

**What the segments leave out:**
- the prescribed camera wording ("The camera tracks ... — as the move completes,");
- "at real-time speed", which [WP] requires;
- the pipeline's sentences.

**Verification:** none of the 129 source 6-grams and none of the terms occurs in any of the 289 existing `generated/stories` and `tests` text files (computed on `3970e96`).

`COPIED_EXAMPLES` and N10 are unchanged. N10 stays the advisory for the planner template texts, and N22 is a separate hard check for the writer reference.

### D12. New checks run only while generating

- N20, N21 and N22 go into `GENERATION_CHECKS`, placed before `Q1` so the existing slice assertions hold. They are **not** added to `RECHECK_IDS` or `PLAN_FREE_IDS`.
- The S5 speaking allowance and the S4 range (SF14) are passed only by `panel_checks`.
- `recheck` keeps the `3970e96` defaults.

### D13. Word ranges grow so the writer can follow the reference **[spec choice]**

- `WORD_RANGES` for chained `motion1`/`motion` and shots `motion` become `(55, 105)`, for the assembled `story.md` field (writer text plus pasted facing and fallback camera). `no_stills` `prompt` stays `(150, 220)`.
- **What the final prompt then holds:**
  - speaking: framing (5) + field (55-105) + quote (about 12) + `ACOUSTIC_SENTENCE` (26), which is about 98-148 words;
  - silent: about 73-123 words.
  - This matches the LTX guidance of about 90-150 words and stays under the README's 200.
- The reference's fields are 71-76 words.
- At `3970e96` the shots writer was asked for 5-14 words, which cannot hold an action, a reaction and an end-framed camera sentence.

---

## 2. Requirements (normative)

### SF1. Camera keys and sentences (`story_engine.py:44-54`)

Replace `CAMERA_SENTENCES` with:

```python
# Shot prompt format spec SF1, D1: moves first, static last; the pasted sentence is the fallback
# when the writer writes no camera sentence (SF6).
CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("static", "The camera stays static."),
)
```

`CAMERA_KEYS` (`:54`) keeps its definition. P8's message (`:1645-1646`) lists the keys in the new order, with no code change.

Immediately after `CAMERA_KEYS`, add:

```python
def max_static(panels):
    """The most beats a movie of `panels` beats may give the static camera: one in three, rounded
    up (shot prompt format spec SF2, D3)."""
    return (panels + 2) // 3
```

### SF2. The plan prompt camera rule (`story_engine.py`)

**Template (`:313`).** The template line `"camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat "` becomes `"camera is exactly one of: @@CAMERA_LIST@@.@@CAMERA_RULE@@ location is the id of the place where the beat "`.

**Constants.** Add them immediately after `SILENT_SPEAKER_RULE` (`:359`):

```python
# Shot prompt format spec SF2, D1: one move per beat, static only as a capped deliberate hold.
CAMERA_RULE = (" Give every beat one camera move from this list, and use static only for a "
               "deliberate hold: at most one beat in three may be static, so at most "
               "@@MAX_STATIC@@ in this movie.")
CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                            "tracking or handheld, and never use a pan or a tilt, which sweeps "
                            "the speaker's face out of the frame.")
```

**`build_plan_prompt`.**
- Insert this fragment immediately after the `@@CAMERA_LIST@@` fragment (`:961`):
  ```python
  ("@@CAMERA_RULE@@", CAMERA_RULE + ("" if ctx.narration is False else CAMERA_SPEAKING_SENTENCE)),
  ```
- Append this scalar to the scalars list (`:976-978`): `("@@MAX_STATIC@@", str(max_static(ctx.panels)))`.

### SF3. Speaker rules (`story_engine.py:352-369`)

Add immediately before `SPEAKER_RULE`:

```python
# Shot prompt format spec SF3, D7: a speaking beat's action is physical, and it ends with the
# speaker in frame and nobody else acting.
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, or leave it out when no later beat is left.")
```

`SPEAKER_RULE` becomes (exact):

```python
SPEAKER_RULE = (" speaker is the id of the one character who says something aloud on screen "
                "during the beat, or an empty string when nobody speaks; give a speaker only where "
                "a spoken line moves the story. A beat with a speaker shows only that character "
                "(its cast is just their id), facing the camera, in a medium shot, medium close-up "
                "or close-up; the speaker may move during the beat, as long as their face stays in "
                "frame and lit while they speak." + SPEAKING_BEAT_SENTENCE)
```

`SPEAKER_RULE_KEEP_CAST` becomes (exact; the comment above it is kept):

```python
SPEAKER_RULE_KEEP_CAST = (
    " speaker is the id of the one character who says something aloud on screen during the "
    "beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves "
    "the story. A beat with a speaker shows that character facing the camera, in a medium shot, "
    "medium close-up or close-up; its cast is the speaker's id plus the id of every already-cast "
    "character who is still in frame and stays silent, and no character of your own. The speaker "
    "may move during the beat, as long as their face stays in frame and lit while they speak."
    + SPEAKING_BEAT_SENTENCE)
```

`SILENT_SPEAKER_RULE` is unchanged.

### SF4. Speaking cameras and the P14 coercion (`story_engine.py`)

- **`:1153-1155`.** The comment becomes `# Narrative dialogue fidelity spec SM1; shot prompt format spec SF4, D2: a speaking beat may be a medium shot, and its camera pushes in, pulls back, tracks, is handheld or stays static.` and `SPEAKING_CAMERAS = ("slow push-in", "slow pull-back", "tracking", "handheld", "static")`.
- **`speaking_camera` (`:1158-1160`).** It returns `beat["camera"] if beat["camera"] in SPEAKING_CAMERAS else "slow push-in"`. Its docstring becomes `"""The beat's camera when a speaking shot may keep it, else "slow push-in" (SM1; shot prompt format spec SF4)."""`.
- **`speaking_coercion` (`:1350-1353`).**
  - The note becomes `"beat %d: P14 speaking beat: camera %s changed to 'slow push-in' so the speaker's face stays readable"`, and the assignment becomes `beat["camera"] = "slow push-in"`.
  - In its docstring, "a camera that does not stay static, push in, pull back or track becomes static. Tracking is never coerced away." becomes "a camera that does not push in, pull back, track, move handheld or stay static becomes a slow push-in (shot prompt format spec SF4). Tracking is never coerced away."
- **`STILL_CAMERA_MOVES` (`:2236-2238`)** gains `"handheld"` as its last item. The N17 message text is unchanged.

### SF5. P18: the static cap (`story_engine.py`)

Add immediately after `speaking_coercion` (before `def is_group_entry`):

```python
# Shot prompt format spec SF5, D3: at most max_static(panels) static beats; the earliest excess
# ones become a slow push-in, and the latest static beats stay as the deliberate holds.
P18_NOTE = ("beat %d: P18 static camera: camera 'static' changed to 'slow push-in': at most %d "
            "of the %d beats may be static, and the latest static beats are kept as the "
            "deliberate holds")


def cap_static_cameras(ctx, plan):
    """The P18 notes of the static cap (shot prompt format spec SF5), in beat order; changes
    plan["beats"] in place."""
    cap = max_static(ctx.panels)
    static = [k for k, beat in enumerate(plan["beats"], start=1) if beat["camera"] == "static"]
    notes = []
    for k in static[:max(0, len(static) - cap)]:
        plan["beats"][k - 1]["camera"] = "slow push-in"
        notes.append(P18_NOTE % (k, cap, ctx.panels))
    return notes
```

In `_Run.go`, immediately after `plan["speech_notes"] += assign_missing_lines(ctx, plan)` (`:3772`), add `plan["speech_notes"] += cap_static_cameras(ctx, plan)` at the same indent.

`plan_checks` and `plan_round` are unchanged: P18 never retries and never appears as hard. Its notes reach every state's advisory list through `plan["speech_notes"]` (`:1730`).

### SF6. The pasted camera and the CM4 fix (`story_engine.py`)

Add immediately before `pasted_pieces` (`:1481`):

```python
def panel_camera(ctx, plan, k):
    """The camera key panel k uses (shot prompt format spec SF6): speaking_camera(beat) on a
    chained k >= 2 speaking panel, else the beat's planned camera."""
    beat = plan["beats"][k - 1]
    if ctx.mode == "chained" and k >= 2 and panel_speaks(ctx, plan, k):
        return speaking_camera(beat)
    return beat["camera"]
```

In `pasted_pieces`:
- `camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")` (`:1494`) becomes `camera = dict(CAMERA_SENTENCES).get(panel_camera(ctx, plan, k), "")`.
- The chained k >= 2 return (`:1500-1501`) becomes `return {"motion": facing + [camera], "narration": []}`.
- In the docstring, "(and, chained k >= 2, the camera sentence of speaking_camera: the planned camera, or "The camera stays static." for a pan or tilt; narrative dialogue fidelity spec SM3)" becomes "; every panel, chained k >= 2 included, lists its panel_camera sentence (shot prompt format spec SF6)".

In `panel_fields` (`:2201`):
- `if not facing and pieces and _moves_camera(ctx, plan, p.get(key, "")):` becomes `if pieces and _moves_camera(ctx, plan, p.get(key, "")):`.
- In its docstring, "on a non-speaking panel the planned camera sentence is left out when the writer text moves the camera, CM4" becomes "the planned camera sentence is left out when the writer text moves the camera, CM4; shot prompt format spec SF6".

### SF7. Writer key lines and word ranges (`story_engine.py`)

**`WORD_RANGES` (`:56-58`)** becomes:

```python
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (55, 105), "motion": (55, 105)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (55, 105)}}
```

**Key lines.** Replace these four `KEY_LINE_TEMPLATES` entries (exact):

```python
    "chained_motion1": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, then the camera sentence. Name each character only by "
        "their referring phrase, word for word. Describe ONE continuous physical motion, not a "
        "sequence of separate steps: @@SECONDS@@ seconds is enough for a single gesture, a few "
        "footsteps or the start of a movement." + PACING_SENTENCE),
    "chained_motion": (
        "motion: W1 to W2 words: one or two plain sentences of what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them, "
        "then the camera sentence. Name each character only by their referring phrase, word for "
        "word. Describe ONE continuous physical motion, not a sequence of separate steps: "
        "@@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the start of a "
        "movement." + PACING_SENTENCE + " Do not describe appearance, clothing, setting, "
        "lighting, colour or style -- all of that is already on screen."),
    "shots_motion": (
        "motion: W1 to W2 words: ONE sentence naming ONE character by their referring phrase and "
        "the ONE physical action they perform during these @@SECONDS@@ seconds, told in concrete "
        "detail (where in the frame they start, how they move and where they end), then the "
        "camera sentence. Never chain actions with then, while, meanwhile, simultaneously, "
        "afterwards, followed by or a comma before and, and never use a semicolon."),
```

In `"no_stills_prompt"` (`:1964-1965`), replace the substring `"and states the camera viewpoint and the lighting and colour; you may also state a camera movement. Name"` with `"and states the camera viewpoint and the lighting and colour. Name"`. Keep the source line breaks as they are. `no_stills_prompt_speaking` (`:2002-2006`) keeps its `.replace` call, and its target substring is unaffected.

**New constants.** Add them immediately after `SPEAKING_SENTENCES` (`:2044-2045`):

```python
# Shot prompt format spec SF7, D4: the writer writes the panel's one camera sentence, with the
# end frame; CAMERA_WRITER_FORMS maps a camera key to (the move, as said of the camera; the form).
CAMERA_WRITER_SENTENCE = (" End this field with exactly one camera sentence, for this panel's "
                          "planned camera, in which the camera @@CAMERA_MOVE@@: begin it with "
                          "'The camera' and write it like @@CAMERA_FORM@@, with your own words in "
                          "place of the part in angle brackets. Write no other camera direction "
                          "anywhere in this field.")
CAMERA_WRITER_FORMS = {
    "slow push-in": ("pushes in", "'The camera pushes in — as the move completes, <what then "
                                  "fills the frame>.'"),
    "slow pull-back": ("pulls back", "'The camera pulls back — as the move completes, <what the "
                                     "wider frame then shows>.'"),
    "tracking": ("tracks the movement", "'The camera tracks <whom it follows> — as the move "
                                        "completes, <where the frame ends>.'"),
    "handheld": ("moves handheld", "'The camera follows with handheld movement — as the move "
                                   "completes, <where the frame ends>.'"),
    "slow pan left": ("pans left", "'The camera pans left — as the move completes, <what the "
                                   "frame ends on>.'"),
    "slow pan right": ("pans right", "'The camera pans right — as the move completes, <what the "
                                     "frame ends on>.'"),
    "slow tilt up": ("tilts up", "'The camera tilts up — as the move completes, <what the frame "
                                 "ends on>.'"),
    "slow tilt down": ("tilts down", "'The camera tilts down — as the move completes, <what the "
                                     "frame ends on>.'"),
    "static": ("stays static", "'The camera stays static, holding <what stays in the frame>.'"),
}
# Shot prompt format spec SF7, D7: a shots speaking panel's reaction after the line, and the
# speaker staying in frame (every mode).
SPEAKING_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                              "sentence. Between that sentence and the camera sentence you may "
                              "write one short sentence, beginning with @@SPEAKER@@, of how they "
                              "react once the line is said, such as a nod, a breath or a glance "
                              "down; nobody else acts in it.")
SPEAKING_NO_REACTION_SENTENCE = (" The pipeline puts the spoken line right after your first "
                                 "sentence, so write no other action sentence.")
SPEAKING_STAY_SENTENCE = (" In this whole panel @@SPEAKER@@ never leaves, turns away or moves "
                          "out of the frame, even when the beat says so.")
```

**`SPEAKING_CHAINED_MOTION_SENTENCE` (`:2019-2031`)** becomes (exact; the comment above it gains `; shot prompt format spec SF7`):

```python
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); after it you may write one short second sentence of "
    "how @@SPEAKER@@ reacts once the line is said, such as a nod, a breath or a glance down, in "
    "which nobody else acts. Begin each of these sentences with @@SPEAKER@@, word for word, and "
    "write nothing about anyone else before the first one. Never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or a "
    "speaking verb; the pipeline adds them.")
```

`SPEAKING_ACTION_SENTENCE`, `SPEAKING_PROMPT_SENTENCE`, `SILENT_CAST_MOTION_SENTENCE` and `SPEAKING_IMAGE_*` are unchanged.

**`build_panel_prompt` (`:2766-2852`).**
- Before the key-line loop, after `assigned = assigned_dialogue(plan, k)` (`:2794`), add:
  ```python
  camera_key = panel_camera(ctx, plan, k)
  fits_two = max(1, int(engine_seconds(ctx) / ACTION_SECONDS + 1e-9)) >= 2
  ```
- Inside the loop, immediately after the `if speaks:` block that appends the speaking sentences (`:2812-2819`) and before `if key in targets:`, add:
  ```python
  if speaks and key in ("motion", "prompt"):
      if ctx.mode == "shots":
          line += SPEAKING_REACTION_SENTENCE if fits_two else SPEAKING_NO_REACTION_SENTENCE
      line += SPEAKING_STAY_SENTENCE
  if key in ("motion", "prompt") and camera_key in CAMERA_WRITER_FORMS:
      line += CAMERA_WRITER_SENTENCE
  ```
- After the existing `if speaks:` token replacement (`:2822-2825`), add (same indent):
  ```python
  if camera_key in CAMERA_WRITER_FORMS:
      move, form = CAMERA_WRITER_FORMS[camera_key]
      line = line.replace("@@CAMERA_MOVE@@", move).replace("@@CAMERA_FORM@@", form)
  ```

### SF8. The format reference (`story_engine.py`)

Add immediately after `COPIED_EXAMPLES` (`:1885-1892`). The literal characters `—` (U+2014) are written as such; the file is UTF-8.

```python
# Shot prompt format spec SF8, D9: three finished shots of an unrelated movie, shown to the
# chained and shots writer for their order only. Each "Shot N" text is exactly
# character_lib.panel_prompt of its parts (SFT13).
FORMAT_REFERENCE = (
    "FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. These are the "
    "finished video prompts of three shots from a different movie. They show the order of every "
    "finished shot: the shot type; the action; when someone speaks, the spoken line and then one "
    "short reaction by the speaker; the one camera sentence, which says where the move ends; and "
    "the audio last. The pipeline wrote the sentences that start \"The shot is\", the sentence "
    "\"The old fishmonger faces the camera.\", the spoken line and the audio sentence; the "
    "writer wrote every other sentence.\n"
    "Shot 1 (silent; the camera tracks): The shot is a wide shot. The old fishmonger drags a "
    "tall stack of empty herring crates across the wet concrete of the market hall toward the "
    "half-open shutter at real-time speed, her heavy steps splashing through shallow puddles "
    "that hold the first glow from the harbour doors. The camera tracks alongside her from the "
    "left — as the move completes, she reaches the shutter at frame centre, the long rows of "
    "bare zinc counters stretching away behind her. The audio is the natural ambient sound of "
    "the place, with no music.\n"
    "Shot 2 (speaking; the camera pushes in): The shot is a medium shot. The old fishmonger "
    "looks up from the empty ice trays to the camera, drying her knuckles on a folded cloth at "
    "the zinc counter at real-time speed. The old fishmonger faces the camera. The old "
    "fishmonger says, \"Forty years of mornings.\" After a breath, \"Not one more.\" The old "
    "fishmonger lets the folded cloth drop onto the counter, her shoulders sinking. The camera "
    "pushes in — as the move completes, her face fills the frame from chin to brow, the bare "
    "counters soft behind her. The audio is clear close-mic dialogue with a subtle natural room "
    "tone; the dialogue takes priority over the quiet ambience, and there is no music.\n"
    "Shot 3 (silent; the movie's one deliberate static hold): The shot is a close-up. The old "
    "fishmonger presses her forehead against the cold ribs of the half-closed steel shutter at "
    "real-time speed, both palms flat on the metal, her breath fogging the ribbed steel as a "
    "thin trickle of meltwater runs past her knuckles and drips onto the wet concrete at her "
    "feet. The camera stays static, holding her face, her knuckles and the ribbed steel tight in "
    "the frame as her eyelids drop shut and the shutter stops trembling. The audio is the "
    "natural ambient sound of the place, with no music.\n\n")
```

The value is 421 words and 2406 characters, with sha256 `d2fe46c687bdaf8ebc75235bdf530d5d751aa1fa62f9bf393bf9855bef7681dd`. SFT1 asserts the hash, so a transcription slip fails loudly.

**Insertion.**
- `PANEL_PROMPT_TEMPLATE` line `:1917` `"@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"` becomes `"@@FORMAT_REFERENCE@@@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"`.
- In `build_panel_prompt`'s fragments, insert immediately before `("@@SEED_PANEL@@", seed)`:
  ```python
  ("@@FORMAT_REFERENCE@@", FORMAT_REFERENCE
   if ctx.mode in ("chained", "shots") and ctx.narration is not False else ""),
  ```
- `FORMAT_REFERENCE` contains no `@@` token.

**What the writer sees.** The writer sees the constant verbatim. Each `Shot N:` text is also what `bin/ltx-story-manifest` would write as that panel's `motion_prompt`. Shot 1 is a wide panel with the Image ending `The shot is a wide shot.` and the Motion field below. Shot 2 is speaking, with `Dialogue: the old fishmonger: Forty years of mornings. Not one more.` and `beats` delivery. The `story.md` Motion fields behind them are:
- Shot 1: `The old fishmonger drags ... harbour doors. The camera tracks ... behind her.`
- Shot 2: `The old fishmonger looks up ... real-time speed. The old fishmonger lets ... sinking. The camera pushes in — ... behind her. The old fishmonger faces the camera.`
- Shot 3: `The old fishmonger presses ... at her feet. The camera stays static, ... stops trembling.`

**Token budget.**
- **The reference costs about 560-600 prompt tokens per writer call.** It is 2406 characters; Qwen3's tokenizer averages about 4.1 characters, or 1.35 tokens per English word. The new key-line sentences add about 100-150 tokens.
- **Prompt size.** Writer prompts at `3970e96` are 4033-4959 characters (`pin-sh4-a` panel 2, `pin-ch3-b` panel 2, `hockey-1x241-p` panel 1), about 1000-1250 tokens. They become about 1700-2000 tokens. The server runs with `--max-model-len 16384` (`$S/attrib/run.sh`), so prompts stay under 13% of the context.
- **Output.** `PANEL_MAX_TOKENS` (1536) is unchanged. The reply grows by at most about 90 Motion words, about 120 tokens.
- **Latency** grows by the prefill of about 700 tokens per writer call. Section 5 records each panel call's seconds before and after; that measurement is not gating.

### SF9. N20 "camera direction" (`story_engine.py`)

Add immediately after `_moves_camera` (`:1470-1478`):

```python
# Shot prompt format spec SF9, D5: a panel has exactly one camera direction, a camera sentence
# that names its camera.
STATIC_CAMERA_WORDS = ("static", "still", "locked-off")
CAMERA_MOVE_WORDS = {
    "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
    "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                       "zooms"),
    "tracking": ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies"),
    "handheld": ("handheld",),
    "slow pan left": ("pan", "pans"),
    "slow pan right": ("pan", "pans"),
    "slow tilt up": ("tilt", "tilts"),
    "slow tilt down": ("tilt", "tilts"),
    "static": ("static", "still", "hold", "holds", "locked-off"),
}
CAMERA_CLAUSE_RE = re.compile(
    r"\bcamera\s+(?:[a-z]+ly\s+)?(?:stays|remains|is|holds?|moves?|push(?:es)?|pulls?|pans?|"
    r"tilts?|tracks?|follows?|zooms?|dollies|orbits?|cranes?|circles?|swings?|glides?|drifts?|"
    r"sweeps?|rises?|lowers?)\b", re.IGNORECASE)
_CUT_RE = re.compile(r"\s*[,;:—–]\s*(?:(?:and|then|while|as|before|after|until|so)\s+)?|\s+-\s+"
                     r"|\s+(?:and|then|while|as|before|after|until|so)\s+", re.IGNORECASE)
REPAIR_NOTE = "panel %d: %s %s: %s: the pipeline removed %s"


def _camera_words(sentence):
    """The CAMERA_MOTION_RE words of a sentence, lower case, whitespace collapsed, in order."""
    return [" ".join(m.group(0).lower().split()) for m in CAMERA_MOTION_RE.finditer(sentence)]


def camera_directions(lib, text, phrases):
    """[(index, kind)] of the camera directions among _sentences(text) (SF9): "sentence" for a
    camera sentence (lib._is_camera_sentence with phrases) that has a CAMERA_MOTION_RE word,
    "clause" for any other sentence with a CAMERA_CLAUSE_RE match."""
    out = []
    for i, sentence in enumerate(_sentences(text)):
        if lib._is_camera_sentence(sentence, phrases):
            if _camera_words(sentence):
                out.append((i, "sentence"))
        elif CAMERA_CLAUSE_RE.search(sentence):
            out.append((i, "clause"))
    return out


def _mixed_camera(sentence):
    """True when a camera sentence both keeps the camera still and moves it."""
    words = _camera_words(sentence)
    return (any(w in STATIC_CAMERA_WORDS for w in words)
            and any(w not in CAMERA_MOVE_WORDS["static"] for w in words))


def _names_camera(sentence, key):
    return any(w in CAMERA_MOVE_WORDS[key] for w in _camera_words(sentence))


def camera_problem(lib, text, phrases, key):
    """The N20 detail of an assembled action field, or None (SF9). key is the panel's camera
    (panel_camera); a key not in CAMERA_MOVE_WORDS (None, "") skips the planned-move test."""
    sentences = _sentences(text)
    found = camera_directions(lib, text, phrases)
    hint = ("; write one camera sentence in which the camera %s" % CAMERA_WRITER_FORMS[key][0]
            if key in CAMERA_WRITER_FORMS else "")
    if len(found) > 1:
        return ("has %d camera directions (%s); a panel has exactly one camera sentence%s"
                % (len(found), "; ".join(_q(sentences[i]) for i, _kind in found), hint))
    if not found:
        return None
    i, kind = found[0]
    if kind == "clause":
        return ("puts the camera direction inside the action sentence %s; write it as its own "
                "sentence that begins with 'The camera'%s" % (_q(sentences[i]), hint))
    if _mixed_camera(sentences[i]):
        return "the camera sentence %s has the camera both stay still and move%s" % (
            _q(sentences[i]), hint)
    if key in CAMERA_MOVE_WORDS and not _names_camera(sentences[i], key):
        return "the camera sentence %s does not move the camera the planned way%s" % (
            _q(sentences[i]), hint)
    return None


def _cut_clause(sentence, at):
    """(head, tail) of a sentence cut at the last clause boundary (_CUT_RE) that ends at or
    before index at: head is the text before the boundary with a full stop, tail the text from
    the boundary on without its leading punctuation; None when no boundary ends at or before at,
    or when head would have fewer than 3 words."""
    start = None
    for match in _CUT_RE.finditer(sentence, 0, at + 1):
        if match.end() <= at:
            start = match.start()
    if start is None:
        return None
    head = sentence[:start].rstrip(" ,;:—–-")
    if len(head.split()) < 3:
        return None
    return head + ".", sentence[start:].strip(" ,;:—–-")
```

`CAMERA_WRITER_FORMS` is defined later in the module. `camera_problem` reads it only at call time, so that order is valid.

**The check.** In `_field_checks`, add this block immediately before the final `return hard, advisory` (`:2554`), at function-body indent:

```python
    # Shot prompt format spec SF9-SF12: the writer-format checks (generation only, D12).
    if plan and beat is not None and action_label in dict(fields):
        if "N20" in ids:
            detail = camera_problem(lib, dict(fields)[action_label], known,
                                    panel_camera(ctx, plan, k))
            if detail:
                hard.append("%s N20 camera direction: %s: %s" % (prefix, action_label, detail))
```

(SF10 and SF12 extend this block.)

### SF10. N21 "after the line" (`story_engine.py`)

Add immediately after `_cut_clause`:

```python
# Shot prompt format spec SF10, D7: a speaker never leaves, and nobody else acts after the line.
EXIT_RE = re.compile(
    r"\b(?:(?:walk|walks|walking|skate|skates|skating|run|runs|running|ride|rides|riding|drive|"
    r"drives|driving|glide|glides|gliding|stride|strides|striding|head|heads|heading|hurry|"
    r"hurries|hurrying|wander|wanders|wandering|march|marches|marching|drift|drifts|drifting|"
    r"fly|flies|flying|swim|swims|swimming|limp|limps|limping|move|moves|moving|step|steps|"
    r"stepping|back|backs|backing)\s+(?:away|off)|(?:turn|turns|turning|pull|pulls|pulling)\s+"
    r"away|leav(?:e|es|ing)\s+(?:the\s+)?(?:frame|shot|scene|room|rink|ice)|exit(?:s|ing)|"
    r"depart(?:s|ing)|disappear(?:s|ing)?\s+(?:from|into|behind|through)|retreat(?:s|ing)|"
    r"reced(?:es|ing)|out\s+of\s+(?:the\s+)?(?:frame|shot|view|sight)|into\s+the\s+distance|"
    r"turn(?:s|ing)?\s+(?:her|his|their)\s+back)\b", re.IGNORECASE)


def post_line_sentences(lib, text, phrases):
    """The action sentences of a speaking panel's writer action text that compose_motion puts
    after the spoken line (SF10): every action sentence (not a camera sentence, not a pasted
    facing sentence) after the first."""
    return [s for s in _sentences(text) if not lib._is_camera_sentence(s, phrases)
            and not lib.is_facing_sentence(s, phrases)][1:]


def _other_actor(sentence, others, own):
    """The words of the first other-character clause subject of a sentence, or None (SF10): a
    mention in others ([(cast id, words)], as _mentions), or a GROUP_NOUNS word with at most one
    article, that starts a _CLAUSE_BREAK_RE piece or follows a CLAUSE_STOP_WORDS word, and is
    not where a mention in own (the speaker's) starts."""
    for piece in _CLAUSE_BREAK_RE.split(sentence):
        words = line_words(piece)
        for p in range(len(words)):
            if (p and words[p - 1] not in CLAUSE_STOP_WORDS) or _mentions_at(words, own, start=p):
                continue
            hits = _mentions_at(words, others, start=p)
            if hits:
                return " ".join(words[p:p + max(hits.values())])
            q = p + 1 if words[p] in ("the", "a", "an") else p
            if q < len(words) and words[q] in GROUP_NOUNS:
                return " ".join(words[p:q + 1])
    return None
```

**Extend the SF9 block in `_field_checks`** (same indent as the `if "N20" in ids:` line):

```python
        if "N21" in ids and panel_speaks(ctx, plan, k):
            writer = writers.get(action_label, "")
            speaker = speaker_phrase(plan, k)
            for sentence in _sentences(writer):
                found = EXIT_RE.search(sentence)
                if found:
                    hard.append("%s N21 after the line: %s: %s has a character leave the frame or "
                                "turn away (%s); %s speaks in this panel, so end it with %s still "
                                "in frame, face toward the camera"
                                % (prefix, action_label, _q(sentence),
                                   _q(" ".join(found.group(0).lower().split())), _q(speaker),
                                   _q(speaker)))
                    break
            if ctx.mode != "no_stills":
                post = post_line_sentences(lib, writer, known)
                mentions = _mentions(plan["cast"])
                others = [m for m in mentions if m[0] != beat["speaker"]]
                own = [m for m in mentions if m[0] == beat["speaker"]]
                for sentence in post:
                    actor = _other_actor(sentence, others, own)
                    if actor:
                        hard.append("%s N21 after the line: %s: %s has %s act after the spoken "
                                    "line; after the line only %s reacts, and nobody else acts"
                                    % (prefix, action_label, _q(sentence), _q(actor),
                                       _q(speaker)))
                        break
                if len(post) > 1:
                    advisory.append("%s N21 after the line: %s: has %d sentences after the first "
                                    "one, which the spoken line follows; after the line write at "
                                    "most one short sentence of how %s reacts"
                                    % (prefix, action_label, len(post), _q(speaker)))
```

### SF11. N7 hard while generating (`story_engine.py`)

- `_field_checks`' signature becomes `def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared, generating=False):`.
- Its docstring's "Hard: N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3; every other N rule is advisory" becomes "Hard: N11 (Narration: empty with no Dialogue:), N18, T1, T2, T3, and with generating (shot prompt format spec SF11-SF12) N7 on the Motion or Prompt, N20, N21 (exits and other actors) and N22; every other N rule is advisory".
- `panel_checks` (`:2719-2720`) passes `generating=True`. The calls at `:3947` and `:3990` are unchanged.

The N7 block (`:2381-2387`) becomes:

```python
            if "N7" in ids:
                speech = _first(DIALOGUE_RE, writer)
                if (generating and speech
                        and label == ("Prompt" if ctx.mode == "no_stills" else "Motion")):
                    add(hard, "N7", "dialogue and text", label,
                        "says %s; the pipeline adds the spoken line itself, so write only what "
                        "the speaker physically does, with no speaking verb" % _q(speech))
                elif any(q in writer for q in ('"', "“", "”")):
                    add(advisory, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = speech or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(advisory, "N7", "dialogue and text", label, "says %s" % _q(word))
```

With `generating=False`, the output equals `3970e96` for every input. `speech or ...` is exactly `_first(DIALOGUE_RE, writer) or ...`.

**The deterministic repair** (D10). Add immediately after `REPAIR_NOTE`'s block (after `_other_actor`):

```python
def _apply_drops(lib, sentences, drop, phrases):
    """(kept sentences, dropped sentences): the indices in drop are removed when at least one
    action sentence (not a camera sentence, not a facing sentence) remains; otherwise only the
    camera sentences among them are removed (SF11)."""
    def action(s):
        return not lib._is_camera_sentence(s, phrases) and not lib.is_facing_sentence(s, phrases)
    drop = set(drop)
    if not any(action(s) for i, s in enumerate(sentences) if i not in drop):
        drop = set(i for i in drop if not action(sentences[i]))
    return ([s for i, s in enumerate(sentences) if i not in drop],
            [s for i, s in enumerate(sentences) if i in drop])


def repair_action_text(ctx, plan, k, text):
    """(text, notes): panel k's writer Motion or Prompt after the SF11 speaking-verb cut and the
    SF9 camera repair, with one REPAIR_NOTE advisory per removed piece. When the result would be
    empty the text is returned unchanged with no notes."""
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    sentences, notes, drop = [], [], []
    for sentence in _sentences(text):
        found = DIALOGUE_RE.search(sentence)
        cut = _cut_clause(sentence, found.start()) if found else None
        if cut:
            sentences.append(cut[0])
            notes.append(REPAIR_NOTE % (k, "N7", "dialogue and text", label, _q(cut[1])))
        else:
            if found:
                drop.append(len(sentences))
            sentences.append(sentence)
    sentences, dropped = _apply_drops(lib, sentences, drop, phrases)
    notes += [REPAIR_NOTE % (k, "N7", "dialogue and text", label, _q(s)) for s in dropped]
    key = panel_camera(ctx, plan, k)
    found = camera_directions(lib, " ".join(sentences), phrases)
    valid = [i for i, kind in found if kind == "sentence" and not _mixed_camera(sentences[i])
             and (key not in CAMERA_MOVE_WORDS or _names_camera(sentences[i], key))]
    if found and not (len(found) == 1 and valid):
        keep, kinds, out = (valid[0] if valid else None), dict(found), []
        for i, sentence in enumerate(sentences):
            kind = kinds.get(i)
            if kind is None or i == keep:
                out.append(sentence)
            elif kind == "sentence":
                notes.append(REPAIR_NOTE % (k, "N20", "camera direction", label, _q(sentence)))
            else:
                start = CAMERA_CLAUSE_RE.search(sentence).start()
                if sentence[:start].lower().endswith("the "):
                    start -= 4
                cut = _cut_clause(sentence, start)
                out.append(cut[0] if cut else sentence)
                if cut:
                    notes.append(REPAIR_NOTE % (k, "N20", "camera direction", label, _q(cut[1])))
        sentences = out
    repaired = " ".join(sentences)
    return (repaired, notes) if repaired else (text, [])
```

### SF12. N22 "reference copy" (`story_engine.py`)

Add immediately after `FORMAT_REFERENCE` (SF8):

```python
# Shot prompt format spec SF12, D11: the reference's own names, props and wording.
REFERENCE_TERMS = ("fishmonger", "fishmongers", "herring", "herrings", "zinc", "ice trays",
                   "market hall", "fish market", "harbour doors", "meltwater",
                   "forty years of mornings")
REFERENCE_COPY_SEGMENTS = (
    "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
    "the market hall toward the half-open shutter",
    "her heavy steps splashing through shallow puddles that hold the first glow from the "
    "harbour doors",
    "she reaches the shutter at frame centre, the long rows of bare zinc counters stretching "
    "away behind her",
    "The old fishmonger looks up from the empty ice trays to the camera, drying her knuckles on "
    "a folded cloth at the zinc counter",
    "The old fishmonger lets the folded cloth drop onto the counter, her shoulders sinking",
    "her face fills the frame from chin to brow, the bare counters soft behind her",
    "The old fishmonger presses her forehead against the cold ribs of the half-closed steel "
    "shutter",
    "both palms flat on the metal, her breath fogging the ribbed steel as a thin trickle of "
    "meltwater runs past her knuckles and drips onto the wet concrete at her feet",
    "holding her face, her knuckles and the ribbed steel tight in the frame as her eyelids drop "
    "shut and the shutter stops trembling",
    "Forty years of mornings. Not one more.",
)


def _six_grams(words):
    return set(tuple(words[i:i + 6]) for i in range(len(words) - 5))


REFERENCE_SIX_GRAMS = frozenset(g for s in REFERENCE_COPY_SEGMENTS for g in _six_grams(line_words(s)))


def reference_copies(narrative, plan, text, goal=None):
    """The REFERENCE_TERMS terms and the six-word REFERENCE_COPY_SEGMENTS runs that text copies
    from FORMAT_REFERENCE, in that order (SF12), leaving out any that the narrative, the goal or
    the plan (cast phrases and descriptors, settings, prop names, beat actions) already has."""
    own = [narrative or "", goal or ""]
    if plan:
        own += ([c.get("phrase") or "" for c in plan["cast"]]
                + [c.get("descriptor") or "" for c in plan["cast"]]
                + [l.get("setting") or "" for l in plan["locations"]]
                + [p.get("name") or "" for p in plan["props"]]
                + [b.get("action") or "" for b in plan["beats"]])
    own_words = [line_words(t) for t in own]
    own_line = " " + " | ".join(" ".join(w) for w in own_words) + " "
    own_grams = set(g for w in own_words for g in _six_grams(w))
    words = line_words(text or "")
    line = " " + " ".join(words) + " "
    hits = [t for t in REFERENCE_TERMS
            if (" %s " % " ".join(line_words(t))) in line
            and (" %s " % " ".join(line_words(t))) not in own_line]
    return hits + [" ".join(g) for g in sorted((_six_grams(words) & REFERENCE_SIX_GRAMS)
                                               - own_grams)]
```

`line_words` (`:447`) is defined before this point, so `REFERENCE_SIX_GRAMS` is computed at import (129 6-grams).

**Extend the SF9 block in `_field_checks`** (same indent as `if "N20" in ids:`):

```python
        if "N22" in ids:
            for label, text in writers.items():
                hits = reference_copies(ctx.narrative, plan, text, ctx.goal)
                if hits:
                    hard.append("%s N22 reference copy: %s: copies the format reference (%s); "
                                "describe only this movie's own people, places, objects and "
                                "words" % (prefix, label, ", ".join(_q(h) for h in hits[:3])))
```

### SF13. Repair plumbing (`story_engine.py`)

**(a) Parse time.** In `parse_panel_reply` (`:2145-2167`), replace the final `return dict({"title": title}, **parts)` with:

```python
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    parts[action], repairs = repair_action_text(ctx, plan, k, parts[action])
    out = dict({"title": title}, **parts)
    if repairs:
        out["repairs"] = repairs
    return out
```

The `"repairs"` key is present only when non-empty. `parts.json` writes only `panel_keys` (`:3601-3603`), so the key is never written there.

**(b) Format problems.** Add immediately before `def panel_checks` (`:2702`):

```python
# Shot prompt format spec SF13, D8: the writer-format ids.
FORMAT_IDS = ("N7", "N20", "N21", "N22")


def format_problems(ctx, plan, part, k):
    """The hard N7, N20, N21 and N22 messages of panel k with writer parts part (SF13)."""
    parts = [{}] * (k - 1) + [part]
    writers = {LABELS[key]: part.get(key, "") for key in panel_keys(ctx, plan, k)
               if key != "title"}
    return _field_checks(ctx, _character_lib(ctx.ws), plan, k, part.get("title", ""),
                         panel_fields(ctx, plan, parts, k), writers, FORMAT_IDS, (),
                         generating=True)[0]


def trim_format(ctx, plan, k, part):
    """part after the SF13 trim, which runs only for an N21 or N22 that format_problems still
    finds: on the action field an exit is cut at the clause boundary before it (a camera
    sentence with an exit is dropped), a post-line sentence with another actor is dropped, and a
    sentence that copies the reference is dropped (_apply_drops keeps one action sentence); on
    the image and narration fields a copying sentence is dropped while one sentence remains.
    Each removal adds a REPAIR_NOTE to part["repairs"]."""
    ids = set(parse_violation(m)["id"] for m in format_problems(ctx, plan, part, k))
    if not ids & {"N21", "N22"}:
        return part
    lib = _character_lib(ctx.ws)
    phrases = cast_phrases(ctx, plan)
    new = dict(part)
    notes = list(part.get("repairs", []))
    action = "prompt" if ctx.mode == "no_stills" else "motion"
    label = LABELS[action]
    sentences = _sentences(new.get(action, ""))
    why = {}
    if "N21" in ids:
        beat = plan["beats"][k - 1]
        mentions = _mentions(plan["cast"])
        others = [m for m in mentions if m[0] != beat["speaker"]]
        own = [m for m in mentions if m[0] == beat["speaker"]]
        for i, sentence in enumerate(sentences):
            found = EXIT_RE.search(sentence)
            if not found:
                continue
            cut = (None if lib._is_camera_sentence(sentence, phrases)
                   else _cut_clause(sentence, found.start()))
            if cut:
                sentences[i] = cut[0]
                notes.append(REPAIR_NOTE % (k, "N21", "after the line", label, _q(cut[1])))
            else:
                why[i] = "N21"
        if ctx.mode != "no_stills":
            actions = [i for i, s in enumerate(sentences) if not lib._is_camera_sentence(s, phrases)
                       and not lib.is_facing_sentence(s, phrases)]
            for i in actions[1:]:
                if _other_actor(sentences[i], others, own):
                    why.setdefault(i, "N21")
    if "N22" in ids:
        for i, sentence in enumerate(sentences):
            if reference_copies(ctx.narrative, plan, sentence, ctx.goal):
                why.setdefault(i, "N22")
    kept, dropped = _apply_drops(lib, sentences, sorted(why), phrases)
    for i, sentence in enumerate(sentences):
        if sentence in dropped and i in why:
            name = "after the line" if why[i] == "N21" else "reference copy"
            notes.append(REPAIR_NOTE % (k, why[i], name, label, _q(sentence)))
    if kept:
        new[action] = " ".join(kept)
    if "N22" in ids:
        for key in ("image", "narration"):
            if new.get(key):
                field = _sentences(new[key])
                bad = [s for s in field if reference_copies(ctx.narrative, plan, s, ctx.goal)]
                if bad and len(bad) < len(field):
                    new[key] = " ".join(s for s in field if s not in bad)
                    notes += [REPAIR_NOTE % (k, "N22", "reference copy", LABELS[key], _q(s))
                              for s in bad]
    if notes:
        new["repairs"] = notes
    return new
```

**(c) Advisory.** In `panel_checks`, immediately after the `h, a = _field_checks(...)` call (`:2719-2720`), add `a = a + parts[k - 1].get("repairs", [])`.

**(d) Round 0.** In `_Run.go`, the `if new is not None:` block (`:3784-3786`) becomes:

```python
            if new is not None:
                parts[k - 1] = new
                # Shot prompt format spec SF13, D8: one re-ask for a writer-format problem while
                # the panel has a call left, then the deterministic trim.
                problems = format_problems(ctx, plan, new, k)
                if (problems and self.panel_calls[k] < PANEL_MAX_CALLS
                        and not self.expired()):
                    again = self.panel_call(plan, parts, k, 0, problems)
                    if (again is not None
                            and len(format_problems(ctx, plan, again, k)) <= len(problems)):
                        parts[k - 1] = again
                parts[k - 1] = trim_format(ctx, plan, k, parts[k - 1])
                valid += 1
```

The re-ask prompt is the normal fix-block prompt: `build_panel_prompt(..., fix=problems)`, with the "Previous version" taken from `parts[k - 1]`. It is saved as `panel_KK_prompt_2.txt` and recorded in `run.json` like every panel call.

**(e) Repair ids.** `REPAIR_IDS` (`:3331`) becomes `("N7", "N11", "N18", "N20", "N21", "N22", "T1", "T2", "T3")`, and its comment gains `; shot prompt format spec SF13 adds N7, N20, N21 and N22`.

**(f) `merge_repair` (`:3385-3400`).** Add immediately before `if "N11" in ids and "narration" in new:`:

```python
    if (ids & set(FORMAT_IDS) and new.get(action)
            and len(format_problems(ctx, plan, new, k))
            < len(format_problems(ctx, plan, old, k))):
        merged[action] = new[action]
        merged.pop("repairs", None)
        if new.get("repairs"):
            merged["repairs"] = new["repairs"]
    if "N22" in ids:
        for key in ("image", "narration"):
            if (new.get(key) and old.get(key)
                    and reference_copies(ctx.narrative, plan, old[key], ctx.goal)
                    and not reference_copies(ctx.narrative, plan, new[key], ctx.goal)):
                merged[key] = new[key]
```

In the same function, `if (ids & {"T1", "N18"} and new.get("dialogue")` becomes `if (ids & {"T1", "N18", "N22"} and new.get("dialogue")`.

The docstring gains: "With N7, N20, N21 or N22 (shot prompt format spec SF13) it takes new's action text when that has fewer writer-format problems, and for N22 new's image or narration when only old's copies the reference."

**(g) `apply_patches`.**
- `need` (`:3280`) becomes `{"T1", "N18", "N22"} if field == "dialogue" else {"T2", "T3", "N7", "N20", "N21", "N22"}`.
- The non-dialogue branch (`:3292-3296`) becomes:

```python
        else:
            text = clean_writer(lib, patch["replacement"],
                                pasted_pieces(ctx, plan, k).get(field, ()))
            notes = []
            if text and field in ("motion", "prompt"):
                text, notes = repair_action_text(ctx, plan, k, text)
            if not text:
                problem = "empty after cleanup"
            elif repairable is not None and repairable.get(k, set()) & set(FORMAT_IDS):
                problem = (None if len(format_problems(ctx, plan, dict(parts[k - 1], **{field: text}),
                                                       k))
                           < len(format_problems(ctx, plan, parts[k - 1], k))
                           else "the patch does not fix the panel's N7, N20, N21 or N22 problem")
            else:
                problem = guard_problem(ctx, plan, parts[k - 1].get(field, ""), text)
```

  On success, immediately after `parts[k - 1][field] = text`, add:

  ```python
  if field in ("motion", "prompt"):
      parts[k - 1].pop("repairs", None)
      if notes:
          parts[k - 1]["repairs"] = notes
  ```

  For a dialogue patch, `notes` is not defined and not used. The two added lines sit inside `if field in ("motion", "prompt"):`, which only the non-dialogue branch reaches.

**(h) Critic text.**
- **`critic_field_lines`, motion line (`:2953-2956`).**
  - `"only for a panel with a "` + `"[hard] T2 or T3 problem: replacement ..."` becomes `"[hard] T2, T3, N7, N20, N21 or N22 problem: replacement ..."`.
  - `"the sentence or sentences that hold the extra or missing action."` becomes `"the sentence or sentences that cause the problem."`.
- **Dialogue line (`:2961-2964`).** `"panel with a [hard] T1 or N18 problem: replacement is the shortened spoken line, "` becomes `"panel with a [hard] T1, N18 or N22 problem: replacement is the new spoken line, "`, and `"within the limit the T1 problem states."` becomes `"within the limit a T1 problem states."`.
- **`CRITIC_SPEAKING_MOTION_CLAUSE` (`:2925-2929`)** becomes (exact; still chained-only, `:2957` unchanged):

```python
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and at most one short sentence of the speaker's reaction "
    "after it, in which nobody else acts and the speaker never leaves the frame. Begin each of "
    "those sentences with the speaker's referring phrase.")
```

### SF14. Generation ids and the shots S4/S5 parameters (`story_engine.py`)

- `GENERATION_CHECKS` (`:2698-2699`) becomes `("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N20", "N21", "N22", "Q1", "N19")`. The slices `[16:20]`, `[-2:]` and `[-1]` are unchanged.
- In `panel_checks` (`:2735-2738`):
  - `lib.shots_violations(text, panels, ctx.panels, ctx.members, ctx.narration is True, ignore_facing=True)` gains `, speaking_actions=2`;
  - `lib.shots_advisories(panels, ctx.members)` becomes `lib.shots_advisories(panels, ctx.members, motion_words=WORD_RANGES["shots"]["motion"])`.
- The recheck and plan-free calls (`:3952`, `:3998-4002`, `:4045-4048`) are unchanged (D12).

### SF15. `character_lib.py`

**(a)** `ACOUSTIC_SENTENCE` (`:759-760`) becomes:

```python
ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience, and there is no music.")
```

**(b)** Add immediately after `speech_text` (`:825-841`):

```python
# Shot prompt format spec SF15, D6: a speech movie's chained or shots video prompt, in the fixed
# order framing, first action, facing, line, other actions, camera, audio.
AMBIENCE_SENTENCE = "The audio is the natural ambient sound of the place, with no music."
SHOT_SENTENCE_RE = re.compile(r"The shot is an? (?:extreme wide shot|wide shot|medium shot|"
                              r"medium close-up|close-up|extreme close-up)\.")


def framing_sentence(image):
    """The last robust-engine shot sentence ("The shot is a medium shot.") in an Image: text, or
    "" (SF15)."""
    found = SHOT_SENTENCE_RE.findall(image or "")
    return found[-1] if found else ""


def compose_motion(text, speech="", phrases=(), audio="", framing=""):
    """text's sentences in the SF15 order: framing (unless text already has that shot
    sentence), text's shot sentences, its first action sentence, its pasted facing sentences
    (is_facing_sentence with phrases), speech, its other action sentences, its camera sentences
    (_is_camera_sentence with phrases), audio. Empty pieces are left out."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]
    shot = [s for s in sentences if SHOT_SENTENCE_RE.fullmatch(s)]
    facing = [s for s in sentences if s not in shot and is_facing_sentence(s, phrases)]
    camera = [s for s in sentences if s not in shot and s not in facing
              and _is_camera_sentence(s, phrases)]
    actions = [s for s in sentences if s not in shot and s not in facing and s not in camera]
    lead = [framing] if framing and framing not in shot else []
    return " ".join(lead + shot + actions[:1] + facing + ([speech] if speech else [])
                    + actions[1:] + camera + ([audio] if audio else []))


def panel_prompt(motion, framing="", speaker=None, line="", delivery=DEFAULT_SPEECH_DELIVERY,
                 phrases=()):
    """The final video prompt of one chained or shots panel of a speech movie (SF15): on a
    speaking panel (speaker set) compose_motion with speech_text's words (no acoustic sentence)
    and [speaker] as the phrases; with beats delivery the last sentence is ACOUSTIC_SENTENCE on
    a speaking panel and AMBIENCE_SENTENCE on a silent one; plain and beats-no-acoustic add no
    audio sentence."""
    speaks = speaker is not None
    said = (speech_text(speaker, line, "beats-no-acoustic" if delivery == "beats" else delivery)
            if speaks else "")
    audio = "" if delivery != "beats" else ACOUSTIC_SENTENCE if speaks else AMBIENCE_SENTENCE
    return compose_motion(motion, said, [speaker] if speaks else phrases, audio, framing)
```

`is_facing_sentence` (`:1112`) and `_is_camera_sentence` (`:984`) are module functions, read at call time.

**(c)** S5 and S4 parameters (legacy defaults unchanged):
- **`motion_problems(motion, phrases=())` (`:1127`)** becomes `motion_problems(motion, phrases=(), max_actions=1)`. The action test `if len(actions) != 1:` becomes `if not 1 <= len(actions) <= max_actions:`.
  - With `max_actions == 1` the message is unchanged.
  - Otherwise it is `"Motion: has %d action sentences; a speaking shot has one, or one and the speaker's reaction, optionally followed by a camera sentence" % len(actions)`.
- **`shots_violations(...)` (`:1148`)** gains `speaking_actions=1` as its last keyword. Its `motion_problems(...)` call (`:1186-1188`) passes `max_actions=speaking_actions if p.get("dialogue", "").strip() else 1`.
- **`motion_length_advisory(motion)` (`:1252`)** becomes `motion_length_advisory(motion, lo=SHOTS_MOTION_MIN_WORDS, hi=SHOTS_MOTION_MAX_WORDS)`. It uses those `lo`/`hi` in place of the two constants on `:1256`.
- **`shots_advisories(panels, members)` (`:1263`)** becomes `shots_advisories(panels, members, motion_words=None)`, and its call becomes `motion_length_advisory(p["motion"], *motion_words) if motion_words else motion_length_advisory(p["motion"])`.

### SF16. `bin/ltx-story-manifest` composition

**(a)** Immediately after `spoken = _spoken(...)` and its `None` check (`:696-698`), add:

```python
    # Shot prompt format spec SF16, D6: a speech movie's chained or shots prompts use the fixed
    # order; a movie with no spoken panel composes exactly as before.
    speech_movie = any(s[0] is not None for s in spoken)
    order_phrases = (_known_phrases(args, members)
                     if speech_movie and (args.chain or args.shots) else [])
```

**(b)** The speech insertion (`:828-832`) becomes:

```python
        if motion_prompt is not None and speech_movie and (args.chain or args.shots):
            lib_ = _character_lib()
            framing = lib_.framing_sentence(pt["image"]) if (args.shots or i == 1) else ""
            motion_prompt = lib_.panel_prompt(motion_prompt, framing, speaker, speech,
                                              args.speech_delivery, order_phrases)
        elif speaker is not None and motion_prompt is not None:
            lib_ = _character_lib()
            beats = args.speech_delivery == "beats"
            motion_prompt = lib_.insert_speech(
                motion_prompt, lib_.speech_text(speaker, speech, "beats-no-acoustic" if beats
                                                else args.speech_delivery), [speaker],
                first_action=bool(args.chain or args.shots))
            if beats:
                motion_prompt += " " + lib_.ACOUSTIC_SENTENCE
```

**(c)** The `--speech-delivery` help (`:184-187`) becomes: `"how a Dialogue: line (or a spoken Narration: line) is written into motion_prompt: beats (default) splits it at sentence ends with short fixed beats and ends the prompt with a fixed audio sentence; beats-no-acoustic omits that sentence; plain is '<Speaker> says: \"<line>\"'"`.

No other line of the manifest changes. `cast_text` and the trigger prefix run after composition, as before.

---

## 3. Interactions (normative)

| Area | Behaviour after this change |
|---|---|
| Plan retry (`plan_round`) | Unchanged. P18 is never a retry reason, and P17/P16 behave as in [SA]. |
| After the plan | `assign_missing_lines`, then `cap_static_cameras`. P18 notes are advisories in every state. |
| Round 0 | Each panel: one call. Then the unparseable retry, or the SF13 format re-ask (never both; the budget is 2 calls). Then the trim. |
| Critic and code-only rounds | Unchanged flow. N7/N20/N21/N22 panels become patchable and re-askable (SF13 e-h). |
| Blocking | N7 (generation), N20, N21 (exits and others) and N22 are hard and blocking. N21's sentence count is advisory. |
| `recheck` | Unchanged: `RECHECK_IDS`, legacy S4/S5, advisory N7, no repairs (D12). |
| Manifest, speech movie, chain/shots | Framing from Image, the fixed order, and the audio sentence last (D6). |
| Manifest, no spoken panel | Byte-identical to `3970e96`. |
| Manifest, `no_stills` speaking | `insert_speech` placement as before, then `ACOUSTIC_SENTENCE` last (beats delivery). |
| `--no-narration` | No `CAMERA_SPEAKING_SENTENCE`, no `FORMAT_REFERENCE`; camera rules apply. |
| movie-ui, `bin/judge-story`, `iterate-story` | No code change. Their critic and judge prompts get the SF13(h) field-line text. |

---

## 4. Tests

### 4.1 New: `tests/test_shot_format.py`

**Conventions** (as `tests/test_speaker_attribution.py`):
- stdlib plus pytest;
- `story_engine.py`, `character_lib.py` and `bin/ltx-story-manifest` loaded by path with `importlib.machinery.SourceFileLoader`, under `story_engine_for_shot_format`, `character_lib_for_shot_format` and `ltx_story_manifest_for_shot_format`;
- the autouse `story_env` and the `ws` fixtures from `tests/story_engine_testutil.py`;
- the module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API.

Manifest tests run `bin/ltx-story-manifest` as `tests/test_dialogue.py::test_dlg7_manifest_goldens` does: a temporary story directory and the existing fake-image helper.

**Helpers:**
- `REF_PHRASE = "the old fishmonger"`.
- `REF_PARTS` is a tuple of three dicts, each with:
  - `shot` (the Image's shot sentence);
  - `motion` (the `story.md` Motion fields of SF8);
  - `speaker` (`None`, `"the old fishmonger"`, `None`);
  - `line` (`""`, `"Forty years of mornings. Not one more."`, `""`).
- `ref_shots()` returns the three `Shot N:` texts split out of `se.FORMAT_REFERENCE`: the text after each `"): "` up to the line end.

| ID | Covers (exact assertions) |
|---|---|
| SFT1 | **Constants.** These equal the SF literals, written out in the test: `se.CAMERA_SENTENCES`, `se.CAMERA_KEYS`, `se.SPEAKING_CAMERAS`, `se.STILL_CAMERA_MOVES[-1] == "handheld"`, `se.CAMERA_RULE`, `se.CAMERA_SPEAKING_SENTENCE`, `se.SPEAKING_BEAT_SENTENCE`, `se.SPEAKER_RULE`, `se.SPEAKER_RULE_KEEP_CAST`, `se.CAMERA_WRITER_SENTENCE`, `se.CAMERA_WRITER_FORMS`, `se.SPEAKING_REACTION_SENTENCE`, `se.SPEAKING_NO_REACTION_SENTENCE`, `se.SPEAKING_STAY_SENTENCE`, `se.SPEAKING_CHAINED_MOTION_SENTENCE`, `se.CRITIC_SPEAKING_MOTION_CLAUSE`, the three replaced `KEY_LINE_TEMPLATES` entries, `se.WORD_RANGES`, `se.REFERENCE_TERMS`, `se.REFERENCE_COPY_SEGMENTS`, `se.P18_NOTE`, `se.REPAIR_NOTE`, `se.FORMAT_IDS`, `se.REPAIR_IDS`, `se.GENERATION_CHECKS`, `lib.ACOUSTIC_SENTENCE` and `lib.AMBIENCE_SENTENCE`. `hashlib.sha256(se.FORMAT_REFERENCE.encode()).hexdigest()` equals the SF8 hash. `len(se.FORMAT_REFERENCE.split()) == 421`. `"slowly"` (case-insensitive) is in none of the new or changed strings, in no `CAMERA_SENTENCES` value and not in `FORMAT_REFERENCE`. `"@@"` is not in `FORMAT_REFERENCE`. `set(se.CAMERA_WRITER_FORMS) == set(se.CAMERA_KEYS) == set(se.CAMERA_MOVE_WORDS)`. For every key, `se._names_camera(sentence, key)` holds both for its `CAMERA_SENTENCES` sentence and for its writer form with `<...>` replaced by `"x"`, and neither is `_mixed_camera`. `se.RECHECK_IDS` and `se.PLAN_FREE_IDS` equal their `3970e96` literals. `len(se.REFERENCE_SIX_GRAMS) == 129`. `/usr/bin/python3 -m py_compile` passes for the three files when that interpreter exists (else skip) |
| SFT2 | **Plan prompt.** For `panels` in 1..7, shots, `"speech"`: the prompt contains `"camera is exactly one of: slow push-in, slow pull-back, tracking, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, static." + se.CAMERA_RULE.replace("@@MAX_STATIC@@", str(m)) + se.CAMERA_SPEAKING_SENTENCE + " location is"`, with `m` from `(1, 1, 1, 2, 2, 2, 3)`. `narration=False` leaves out `CAMERA_SPEAKING_SENTENCE`. `"the camera may stay static"` is in no plan prompt of any mode or narration. Chained with members contains `se.SPEAKER_RULE_KEEP_CAST`; shots contains `se.SPEAKER_RULE` |
| SFT3 | **Coercion.** Shots, members, a speaking beat with `camera` in `("slow pan left", "slow pan right", "slow tilt up", "slow tilt down", "")`: the camera becomes `slow push-in`, with the note `"beat 1: P14 speaking beat: camera %s changed to 'slow push-in' so the speaker's face stays readable" % _q(old)`. With `handheld`, `static`, `tracking`, `slow pull-back` or `slow push-in` it is unchanged, with no camera note. Chained beat 2 speaking with `slow pan right`: `se.panel_camera(...) == "slow push-in"` and `pasted_pieces(...)["motion"][-1] == "The camera pushes in."` |
| SFT4 | **P18.** `cap_static_cameras` on 3/4/6/7-beat plans with cameras `[s,s,s]`, `[s,t,s,s]`, `[s,s,s,s,s,s]`, `[s,s,t,s,s,s,s]` (`s` static, `t` tracking). Expected cameras `[p,p,s]`, `[p,t,s,s]`, `[p,p,p,p,s,s]`, `[p,p,t,p,s,s,s]` (`p` slow push-in). The notes equal `P18_NOTE % (k, cap, n)` for each changed `k`, in order. E2E: a 3-panel shots `se.run` with `plan_json` (beats 1 and 3 static) gives exactly 1 plan call; `plan.json` beat 1 has camera `slow push-in`; `story_checks.json` advisory has the P18 message; panel 1's Motion ends `The camera pushes in.` |
| SFT5 | **Writer prompt.** Shots 3 panels, `"speech"`, beat 2 speaking, cameras `["tracking", "slow push-in", "static"]`. Panel 1's motion line ends with `CAMERA_WRITER_SENTENCE`, filled with `"tracks the movement"` and its form. Panel 2's motion line contains `SPEAKING_ACTION_SENTENCE + SPEAKING_REACTION_SENTENCE + SPEAKING_STAY_SENTENCE + CAMERA_WRITER_SENTENCE`, filled with `'"<speaker phrase>"'`, `"pushes in"` and its form. With `clip_seconds=5.04`, panel 2 has `SPEAKING_NO_REACTION_SENTENCE` instead. `prompt.count(se.FORMAT_REFERENCE) == 1`, and it is immediately followed by `"Write this panel as one JSON object"` (no seed). Chained: also once. `no_stills`, and any mode with `narration=False`: `"FORMAT REFERENCE ONLY"` is absent. No prompt contains `"@@"`. Chained k=2 silent with beat camera `static`: the motion line has `"in which the camera stays static"`. A beat camera `""` gives no `CAMERA_WRITER_SENTENCE` |
| SFT6 | **Pasted camera and CM4.** For each mode and for speaking/silent: writer motion `X` with no camera sentence → the assembled field ends with the `panel_camera` sentence. Writer `X + " The camera pushes in — as the move completes, her face fills the frame."` with planned `slow push-in` → the field has that sentence and no `"The camera pushes in."` fallback. Chained k=2 silent → the planned sentence is present (C4 fixed) |
| SFT7 | **N20 detection** (`camera_problem`, phrases `["the courier"]`). Rows (text, key → `None` or the detail's first clause): `"The courier runs. The camera pushes in."`, `slow push-in` → None; `"The courier runs. The camera holds on him as he recedes. The camera stays static."`, `static` → `"has 2 camera directions"`; `"The courier runs while the camera tracks him. The camera pushes in."` → `"has 2 camera directions"`; `"The courier runs while the camera tracks him."`, `""` → `"puts the camera direction inside the action sentence"`; `"The camera pushes in and stays static."`, `slow push-in` → `"has the camera both stay still and move"`; `"The camera pans left."`, `slow push-in` → `"does not move the camera the planned way"`; `"The camera follows with handheld movement."`, `handheld` → None; `"The camera follows her."`, `tracking` → None; `"The camera holds steady on her."`, `static` → None; `"The courier faces the camera."`, `static` → None; `"The shot is a medium shot. The courier runs. The camera tracks alongside the movement."`, `tracking` → None. Full message format via `panel_checks` on a story with E2's panel-2 text: `"panel 2: N20 camera direction: Motion: has 2 camera directions ('The camera holds on him as he recedes.'; 'The camera stays static.'); a panel has exactly one camera sentence; write one camera sentence in which the camera stays static"` |
| SFT8 | **N20 and N7 repair** (`repair_action_text`, shots, planned `slow push-in`, phrase `"the courier"`). Inputs → (text, notes): `"The courier runs. The camera pans left."` → `("The courier runs.", [REPAIR_NOTE % (1, "N20", "camera direction", "Motion", "'The camera pans left.'")])`; `"The courier runs while the camera tracks him."` → `("The courier runs.", [... "'while the camera tracks him.'"])`; `"The courier runs. The camera pushes in. The camera holds."` → `("The courier runs. The camera pushes in.", [... "'The camera holds.'"])`; `"The courier turns toward the camera and speaks."` → `("The courier turns toward the camera.", [REPAIR_NOTE % (1, "N7", "dialogue and text", "Motion", "'and speaks.'")])`; `"The courier speaks softly. The courier waves."` → `("The courier waves.", [... "'The courier speaks softly.'"])`; `"The courier speaks."` → unchanged, `[]`; `"The camera pans left."` alone → unchanged, `[]`. After `parse_panel_reply` of a reply with `"The courier runs. The camera pans left."`, the part has `"repairs"`, and `panel_checks` advisory contains that note while hard has no N20 |
| SFT9 | **N7 severity.** `_field_checks` with `GENERATION_CHECKS`: Motion `"The courier speaks."` gives hard `"panel 1: N7 dialogue and text: Motion: says 'speaks'; the pipeline adds the spoken line itself, so write only what the speaker physically does, with no speaking verb"`, and generating False gives the `3970e96` advisory `"panel 1: N7 dialogue and text: Motion: says 'speaks'"`. Image `"The courier speaks."` with generating True gives the advisory form. A Motion with a double quote and no speech verb gives the advisory `"contains a double quote"` both ways |
| SFT10 | **N21 detection.** Shots and chained, members kyra and ronin, beat speaker `c1`. Writer motion rows → hard N21 messages (exact strings built from SF10): `"The woman in grey turns to the camera. The woman in grey skates away."` → exit `'skates away'`; `"The woman in grey turns to the camera, then walks off."` → exit `'walks off'`; `"The woman in grey turns. The camera holds on her as she recedes."` → exit `'recedes'`; `"The woman in grey turns. The ronin bows."` → other actor `'the ronin'`; `"The woman in grey turns. The woman in grey nods as the ronin bows."` → `'the ronin'`; `"The woman in grey turns. The crowd cheers."` → `'the crowd'`. No hard: `"The woman in grey turns. The woman in grey glances back at the ronin."`; `"The woman in grey turns. Her shoulders drop."`; any silent panel. Advisory N21 for `"A. B. C."` (three action sentences by the speaker). no_stills speaking: exit rows flagged, other-actor rows not. Uncast: `"the courier"` speaking with `"The old monk bows."` after → other actor `'the old monk'` |
| SFT11 | **Round-0 re-ask and trim (E2E, shots, 2 panels, `"speech"`).** (a) Panel 1 replies `[R_exit, R_clean]`, where `R_exit` motion is `"The woman in grey turns to the camera. The woman in grey walks away."` → rc 0; the stages are `["plan", "panel", "panel", "panel"]`; `panel_01_prompt_2.txt` contains `"Your previous version of this panel was rejected. Problems:\n- panel 1: N21 after the line: Motion: "`; `story.md` panel 1 Motion starts with `R_clean`'s motion; no `"the pipeline removed"` advisory. (b) Replies `[R_exit, R_exit]` → rc 0, panel 1 Motion has no `walks away`, and the advisory has `REPAIR_NOTE % (1, "N21", "after the line", "Motion", "'The woman in grey walks away.'")`. (c) Reply `["The woman in grey skates away."]` twice (no other action) → rc 2, with the hard N21 in `story_checks.json` after the critic rounds (scripted critic with no valid reply) |
| SFT12 | **N22.** `reference_copies(narrative, plan_json, text)`: `"The courier walks past the zinc counter."` → `["zinc"]`; `"The courier looks up from the empty ice trays to the camera"` → `["ice trays", "the courier looks up from the"...]`, asserted as `hits[0] == "ice trays"` and a 6-gram present; `"at real-time speed"` text → `[]`; narrative containing `"a fish market"` → `"fish market"` exempt. `panel_checks` on a Motion copying segment 5 → hard `"panel 1: N22 reference copy: Motion: copies the format reference ('fishmonger', ...); describe only this movie's own people, places, objects and words"`. **Corpus guard:** no `REFERENCE_SIX_GRAMS` member and no `REFERENCE_TERMS` term occurs in any file under `tests/fixtures/` (line_words). Every segment is a substring of `FORMAT_REFERENCE` |
| SFT13 | **Composition and reference self-consistency.** For each `REF_PARTS` entry, `lib.panel_prompt(motion, shot, speaker, line, "beats", [REF_PHRASE]) == ref_shots()[i]`. Each reference shot passes `camera_problem(..., key)` with keys `tracking`, `slow push-in`, `static` → None. `post_line_sentences` of shot 2's motion is exactly the reaction sentence, and `_other_actor` of it is None. `compose_motion` table: (a) a camera sentence first and an action after → camera moves to the end; (b) `"A. X faces the camera. B. The camera tracks alongside the movement."` + speech `S` → `"A. X faces the camera. S B. The camera tracks alongside the movement."`; (c) no action → framing + facing + speech + camera + audio; (d) framing equal to a shot sentence already in text → not duplicated. `panel_prompt` deliveries: `plain` → `speech_sentence` form, no audio; `beats-no-acoustic` → no audio; silent + `beats` → ends with `AMBIENCE_SENTENCE` |
| SFT14 | **Manifest E2E.** (a) `--shots`, 2 panels, panel 1 `Dialogue: the courier: Go now.`, panel 2 silent: `motion_prompt[0] == "The shot is a medium shot. <action>. The courier faces the camera. The courier says, \"Go now.\" <camera>. " + ACOUSTIC_SENTENCE`; `motion_prompt[1]` ends `" " + AMBIENCE_SENTENCE` and starts `"The shot is "`. (b) `--chain`, 2 panels, speech on panel 2: panel 1 starts with its Image shot sentence; panel 2 has no shot sentence. (c) The same 2-panel shots story with no Dialogue and no spoken Narration: `motion_prompt`s equal the raw Motion fields (byte-identical to `3970e96`). (d) Non-chain `--image` (v2) story with a Dialogue: `insert_speech` placement, then `" " + ACOUSTIC_SENTENCE` last. (e) `--speech-delivery plain`: no audio sentence |
| SFT15 | **S4/S5 parameters.** `motion_problems(m, phrases, max_actions=2)` with 2 action sentences → `[]`; 3 → the speaking-shot S5 message. `motion_problems(m)` defaults unchanged. A shots `story.md` speaking panel with action + reaction + camera: `panel_checks` advisory has no `S5 one action`, while `shots_violations(...)` with default arguments still reports it. `shots_advisories(panels, [], motion_words=(55, 105))` on a 20-word Motion → `"panel 1: S4 motion length: Motion: is 20 words; aim for 55-105"` |
| SFT16 | **Critic and patches.** `critic_field_lines(mode, None)` equals the SF13(h) lines for every mode. `apply_patches` with `repairable={1: {"N21"}}`: a motion patch removing the exit is applied; a patch that keeps the exit is rejected with `"the patch does not fix the panel's N7, N20, N21 or N22 problem"`. `repairable={1: {"T2"}}` keeps the PG3 guard path (an existing guard rejection reproduces). `merge_repair` with ids `{"N22"}` takes a new image that stops copying |
| SFT17 | **Old stories (SK10).** Save a story whose Motion is E2's panel-2 text and E3's `"... and speaks."`. Monkeypatch `se.repair_action_text`, `se.reference_copies` and `se.cap_static_cameras` to raise `AssertionError`. Then `se.recheck(ctx, ltx_movie._validate_story_md)` returns rc 0. Its advisories contain `"panel 1: N7 dialogue and text: Motion: says 'speaks'"` and no `" N20 "`, `" N21 "` or `" N22 "` |
| SFT18 | **Exit verbs.** `EXIT_RE` matches: `skates away`, `walks off`, `turns away`, `steps off`, `pulls away`, `leaves the frame`, `exits`, `disappears into`, `out of frame`, `out of the shot`, `into the distance`, `recedes`, `turns her back`. It does not match: `pushes off from the kerb`, `turns off the light`, `the leaves fall`, `the exit sign`, `steps back`, `turns toward the camera`, `runs down the steel` |
| SFT19 | **Trim keeps an action.** `trim_format` when the only action sentence has an uncuttable exit → the part is unchanged and the hard N21 remains (`format_problems` non-empty) |
| SFT20 | **Chained hockey shape.** With `tests/fixtures/writer_pacing/hockey-2x145-f/plan.json` and its parts, `format_problems` of panel 2 has the N21 exit for `'skates away'`. `trim_format` cuts at `", then"`, leaving `"The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, his face toward the lens."`. `repair_action_text` removes `'The camera holds on him as he recedes.'` (N20) |
| SFT21 | **Prompt budget.** For the 3-panel shots story of SFT5, `len(prompt)` for panel 2 minus the same prompt built with `FORMAT_REFERENCE` monkeypatched to `""` equals `len(se.FORMAT_REFERENCE)` (2406). The panel prompt is under 9000 characters |
| SFT22 | **No server, no HOME.** `seu.script_agent` is used for every E2E; `os.path.expanduser("~")` is never the real HOME during the module (asserted via the `story_env` fixture) |
| SFT23 | **Narrative exit detection (SF-A1).** `se.narrative_exit_after_last_line(text)` rows (text → result): the hockey narrative `$S/hockey/narrative.txt`, written out in the test → `"skates away"`; `LINES_NARRATIVE` → `None`; `'Kyra says, "Go." She walks off.'` → `"walks off"`; `'Kyra walks off. Kyra says, "Go."'` → `None` (the exit is before the last line); `'Kyra says, "Go," and the ronin leaves the frame.'` → `"leaves the frame"`; `'Kyra says, "Go." Later the crowd says, "Yes." Kyra turns away.'` → `"turns away"`; `'A sign reads "Closed". Kyra walks away.'` → `None` (no spoken line); `'Kyra says, "Go." She pushes off from the kerb.'` → `None`; curly quotes `'Kyra says, “Go.” She skates away.'` → `"skates away"` |
| SFT24 | **When P19 fires (SF-A1).** `se.exit_left_out_notes(ctx, plan)` on normalised plans, hockey narrative, 2 spoken lines. Chained 2 beats with lines `[1]`, `[2]` → `[P19_NOTE % ("'skates away'", 3)]`. Chained 1 beat with lines `[1, 2]` → `[P19_NOTE % ("'skates away'", 2)]`. Shots 3 beats with lines `[1]`, `[2]`, `[]` → `[]` (a later beat exists). Shots 3 beats with lines `[1]`, `[]`, `[2]` → `[P19_NOTE % ("'skates away'", 4)]`. The 2-beat plan with `narration=False` → `[]`. The 2-beat plan with line 2 in no beat → `[]`. `LINES_NARRATIVE` with any plan → `[]`. `parse_violation(P19_NOTE % ("'x'", 3))` is `("P19", "exit left out", "plan", None)` |
| SFT25 | **P19 end to end (SF-A1).** `se.run` on the hockey narrative, chained, 2 panels, `"speech"`, with a scripted plan reply whose beats hold lines `[1]` and `[2]` and scripted panel replies → rc 0. `story_checks.json` advisory and the advisories returned by `se.run` each contain exactly one P19 message, ending `"rerun with --force-story --panels 3 to keep it"`. `plan.json` `speech_notes` holds it. The same run on `LINES_NARRATIVE` has no P19. `se.recheck` of the saved hockey story prints and returns no P19 (recheck runs no plan step) |

### 4.2 Existing tests and fixtures to re-baseline

**Rule (mandatory).**
- Run the full suite before G1 and after G1-G3 + G4.
- Every existing test that changes outcome must be explained by one or more of the codes below.
- Its assertions are updated to the new behaviour in the G5 commit.
- The G5 commit body has one paragraph per changed file. Each paragraph names the tests, the codes, and in one sentence per golden what changed (for example "panel 2 Motion: 'The camera stays static.' fallback dropped because the writer's 'The camera tracks him.' is valid (R6)").
- A failure that no code explains is an implementation defect: fix the code, not the test.
- No test is deleted. No assertion is weakened beyond the new behaviour.

| Code | Cause |
|---|---|
| R1 | Camera key order and `handheld` (SF1): `CAMERA_SENTENCES` order, the P8 message, `@@CAMERA_LIST@@` bytes, `len(CAMERA_SENTENCES) == 9` |
| R2 | `CAMERA_RULE`/`CAMERA_SPEAKING_SENTENCE` in plan prompts (SF2): byte fixtures and containment |
| R3 | `SPEAKER_RULE`/`SPEAKER_RULE_KEEP_CAST` text (SF3) |
| R4 | Speaking pan/tilt to slow push-in (SF4): P14 note text and pasted sentence |
| R5 | P18 cap (SF5): `plan_json` with 3 or 6 beats has 2 or 3 static beats, so beat 1 becomes `slow push-in` in `se.run` E2Es (plan.json, story.md, advisories) |
| R6 | CM4 fix (SF6): a speaking panel with a valid writer camera loses the pasted camera |
| R7 | Chained k >= 2 silent planned camera (SF6): those Motion fields gain the planned sentence, and their writer W1/W2 shrink |
| R8 | `WORD_RANGES` (SF7): writer targets `W1 to W2`, N1 advisories, robust-engine S4 range |
| R9 | Key-line texts (SF7): camera clauses removed, `CAMERA_WRITER_SENTENCE`, reaction/stay sentences, `SPEAKING_CHAINED_MOTION_SENTENCE` |
| R10 | `FORMAT_REFERENCE` in chained/shots writer prompts (SF8) |
| R11 | `REPAIR_IDS` (SF13e) |
| R12 | N7 hard in generation and the parse-time cut/repairs (SF11, SF13a) |
| R13 | Manifest composition (SF15, SF16): framing, order, audio last, `ACOUSTIC_SENTENCE` text, `AMBIENCE_SENTENCE` |
| R14 | Critic field lines and `CRITIC_SPEAKING_MOTION_CLAUSE` (SF13h) |
| R15 | S5 speaking allowance in generation (SF14) |
| R16 | N20/N21/N22 or the round-0 re-ask acting on a scripted reply (SF9-SF13) |
| R17 | The P19 note (Amendment SF-A1): `se.run` E2Es on the hockey narrative, or another narrative with an exit after its last line whose last line is in the last beat, gain one advisory and one `speech_notes` entry |

**Expected to change.** Found by grepping the pinned wording at `3970e96`; the implementer confirms each by running the suite.
- **`tests/test_story_engine.py`:**
  - `test_rs4_constants` (R1, R8);
  - `test_rst8_plan_prompt_matrix`, `test_rst9_narrative_is_inserted_verbatim`, `test_rst57_reserved_sentence_in_the_plan_prompt`, `test_rst20e_speech_only_framing` (R2, R3);
  - `test_rst14_plan_checks` P8 row `:401-403` (R1);
  - `test_rst16_panel_prompt`, `test_rst20c_narration_modes` (R8, R9, R10);
  - `GOLDEN_CHAINED`/`GOLDEN_NO_STILLS`/`GOLDEN_SHOTS` and their tests (R5, R7);
  - `test_rst17_cleanup_and_title_fallback`, `test_rst20_panel_checks`, `test_rst39_outputs_and_layout`, `test_rst48_judge_story_patches` (R5, R7, R8, R12);
  - `test_pacing_camera_sentences_classify_as_before` (R1: 9 sentences; `handheld` gets an "old" entry equal to its new sentence);
  - `test_pacing_panel1_prompt_and_no_slowly`. R8: the band assertion becomes `(55, 105)`, and `"motion: 11 to 31 words"` becomes `"motion: 51 to 101 words"` (the band less the 4 words of panel 1's pasted "The camera stays static."; the `_story` helper does not run P18). The no-"slowly" assertions stay and also cover the new constants.
- **`tests/test_dialogue.py`:**
  - `AC`/`test_dlg3_speech_text` (R13 text);
  - `test_dlg7_manifest_goldens`, `test_dlg8_narration_alias`, `test_dlg10_dialogue_wins_over_a_prefixed_narration`, `test_review_focus_2_*`, `test_review_focus_3_*`, `test_dlg29_judge_clips_panel_text` (R13);
  - `test_dlg5_camera_sentence_classifier` (R1);
  - `test_dlg12_plan_prompt_speaker_rule` (R2, R3);
  - `test_dlg13_writer_keys_and_speaking_key_lines` (R9);
  - `test_dlg21_an_advisory_only_round_0_passes_untouched` (R12);
  - the critic field-line test at `:1500-1548` (R14);
  - `test_n16_n17_n18_dialogue_messages`, `CAST_PLAN`/`IDENTITY` goldens (R5-R7).
  - `test_dlg4_insert_speech_placement` must **not** change (`insert_speech` is unchanged).
- **`tests/test_narrative_fidelity.py`:**
  - `test_nf16_the_speaking_coercion_table` (R4);
  - `test_nf17_pasted_pieces_of_a_speaking_panel` (R4, R6);
  - `test_nf19_n17_accepts_a_moving_speaking_camera` (R6);
  - `SPEAKER_RULE`/`test_nf12_the_plan_prompt` (R2, R3);
  - `test_nf20_the_panel_prompt_constants` (R9);
  - `test_nf35_manifest_places_the_line_after_the_first_action` (R13);
  - `test_nf28_engine_the_2x145_failure` (R6, R7, R16).
  - `test_nf34_insert_speech_after_the_first_action` must **not** change, and `SPEAKING_CAMERA` (`:378`) is unchanged.
- **`tests/test_writer_pacing.py`:**
  - `test_wt1_the_constants` (`SPEAKING_CHAINED`, `CHAINED_MOTION*`, `CRITIC_CLAUSE`: R9, R14);
  - `_expected_line` and WT3 (R8, R9);
  - `test_wt4_shots_and_no_stills_speaking_prompts_are_unchanged` (R9: renamed assertions keep the test name);
  - `test_wt5_the_contract_matches_the_placement`, `test_wt8_old_stories_compose_unchanged` (R13: composes with `panel_prompt` and new expected strings);
  - `test_review_focus_1_a_writer_re_ask_keeps_one_contract` (R9);
  - `test_wt6`/`RECORDED_ADVISORY` (R12, R16).
- **`tests/test_pinned_cast.py`:**
  - `SPEAKER_RULE_KEEP_CAST`, `UNCHANGED`, `test_pt1_plan_constants`, `test_pt4_speaker_rule_variants` (R3);
  - `FIXTURE_CASES` with `tests/fixtures/pinned_cast/uncast_shots_lines.txt`, `uncast_chained_seed.txt`, `uncast_chained_lines.txt` and the other `uncast_*.txt` plan-prompt fixtures (R1, R2, R3: regenerate each fixture from the new `build_plan_prompt` and diff it; the diff must be exactly the camera list order, the `CAMERA_RULE`/`CAMERA_SPEAKING_SENTENCE` insertion and the speaker-rule text);
  - `test_pt5_lines_sentence_variants`, `test_pt18_seed_and_two_pinned_retried` (R2);
  - `test_pt11_writer_prompt` (R8-R10);
  - `test_pt13_speech_stays_with_the_speaker` (R13).
- **`tests/test_speaker_attribution.py`:**
  - `test_q1_a2_constants` (R11);
  - `_plan_prompt`/`test_sat9_plan_prompt`/`test_sat6_e2e_retry`/`test_review_focus_3_*`/`test_review_focus_4_*`: only if they compare whole prompt bytes (R2, R3); containment assertions hold.
- **`tests/test_shots_mode.py`:**
  - `test_s1_constants` (unchanged: the `SHOTS_MOTION_*` constants keep 10/25);
  - shots `story.md` goldens built through the robust engine (`SHOTS_OK`, `BAD`, `DES`, `test_s55_*`, `test_s92_*`: R5-R8, R15);
  - `test_s60_shots_manifest_uncast`, `test_s61_*` (R13 only if their story has a spoken panel).
  - `tests/fixtures/shots_rules_v2/*.md` change only if a test regenerates them through the robust engine. As inputs to `shots_violations` with default arguments they are unchanged.
- **`tests/test_casting_pipeline.py`:** `test_p20_cast_inserts_triggers_and_lists_characters` and `CAST_STORY`/`MOVIE_STORY` (R13 if spoken; R6, R7). `tests/fixtures/casting_baseline/manifest.json` and `story.md` are re-baselined only through R13 or R7.
- **`tests/fixtures/writer_pacing/hockey-2x145-f/*`:** the fixture files are **not** edited (they are recorded artifacts). The tests that compare against them change their expected values (R13).
- **`tests/test_movie_ui_builder.py::test_mut26`:** G6.

### 4.3 Must pass unchanged

- `tests/test_ltx_story_manifest_chain.py::test_v2_golden_byte_identical` and its other tests with no spoken panel.
- `tests/test_ltx_mlx_render.py`, `tests/test_ltx_story_video.py`, `tests/test_judge_clips.py` (unless a fixture composes a spoken panel: R13), `tests/test_lora_catalog.py`, `tests/test_character_lib.py` (`speech_text` and `insert_speech` are unchanged), `tests/test_iterate_story.py`, `tests/test_judge_story.py` (unless it pins critic field-line text: R14), `tests/test_casting_regression.py` and `tests/test_ltx_movie_offline.py`.
- `test_dlg4_insert_speech_placement` and `test_nf34_insert_speech_after_the_first_action`.

---

## 5. Live acceptance (SK11; this Mac only, story-only, post-merge, not a merge gate)

These run on this Mac only, never on macstudio or another host. The runner is whoever is authorized to start the local story server; the spec author ran nothing.

**Preconditions.** No render is running on this Mac: the running accent render has finished, `$S/accent2/.render.lock` does not exist, and `pgrep -f ltx-mlx-render` prints nothing.

### 5.1 Setup and runs

- `R=$S/shotfmt-live` (new, empty), `W=$WS`.
- Archive first: `mkdir -p $R/pre && cp -Rp $W/generated/stories/pin-* $W/generated/stories/hockey-* $R/pre/`.
- Start the story server exactly as the `vllm serve` line of `$S/attrib/run.sh` (vllm-metal `qwen38-6bit`, port 8177), and wait for it as that script does. Stop it with `bin/story-server stop` after the last run.
- `NP` is `LINES_NARRATIVE` (`tests/test_pinned_cast.py:66-69`). `NH="$(cat $S/hockey/narrative.txt)"`. `G` is the `goal` of `tests/fixtures/writer_pacing/hockey-2x145-f/case.json`.
- `X` is the id prefix: `sf0` for the **before** runs (WS at `3970e96`, before the G1-G6 commits land in WS) and `sf1` for the **after** runs (WS at the merged HEAD).

**The nine configurations** (each from `$W`, log to `$R/run-$X-<name>.log`, then `echo "<name> exit $?"`). The six `pin-*` configurations are the `$S/attrib/run.sh` commands with only the story id changed. **The third hockey configuration, shots with 3 panels, is new [spec choice]:** it adds the hockey narrative in shots mode, since only two distinct hockey configurations existed.

| name | command |
|---|---|
| ch3-a | `bin/ltx-movie "$NP" --panels 3 --story-id $X-ch3-a --character kyra --character ronin --speech-only --story-only --no-review --force-story` |
| ch3-b | as ch3-a with `--story-id $X-ch3-b` |
| sh4-a | `bin/ltx-movie "$NP" --panels 4 --shots --story-id $X-sh4-a --character kyra --character ronin --speech-only --story-only --no-review --force-story` |
| sh4-b | as sh4-a with `--story-id $X-sh4-b` |
| sh2 | `bin/ltx-movie "$NP" --panels 2 --shots --story-id $X-sh2 --character kyra --character ronin --speech-only --story-only --no-review --force-story` |
| sh2-b | as sh2 with `--story-id $X-sh2-b` |
| hk2 | `bin/ltx-movie "$NH" --panels 2 --frames 145 --story-id $X-hk2 --model ~/ltx-2-mlx/models/ltx-2.5-mlx-q8 --speech-only --goal "$G" --story-only --no-review --force-story` |
| hk1 | as hk2 with `--panels 1 --frames 241 --story-id $X-hk1` |
| hk3s | as hk2 with `--panels 3 --shots --story-id $X-hk3s` |

### 5.2 Measure

After the merge, save this as `$R/measure_sf.py`. Run `W=$W python3 -I $R/measure_sf.py sf0-ch3-a sf0-ch3-b sf0-sh4-a sf0-sh4-b sf0-sh2 sf0-sh2-b sf0-hk2 sf0-hk1 sf0-hk3s > $R/measure_before.txt`, and the same with `sf1-` into `$R/measure_after.txt`. Both use the post-change detectors on the recorded files.

```python
import importlib.machinery, json, os, sys
W = os.environ["W"]
def load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(W, rel)).load_module()
se, lib = load("se_sf", "story_engine.py"), load("cl_sf", "character_lib.py")
man = load("man_sf", os.path.join("bin", "ltx-story-manifest"))
STILL = set(se.CAMERA_MOVE_WORDS["static"])
total = {"panels": 0, "static": 0}
for sid in sys.argv[1:]:
    d = os.path.join(W, "generated", "stories", sid)
    run = json.load(open(os.path.join(d, "story_rounds", "run.json")))
    def calls(stage):
        return len([c for c in run["calls"] if c["stage"] == stage])
    secs = sorted(c["seconds"] for c in run["calls"] if c["stage"] == "panel")
    if run.get("exit") != 0:
        print(sid, "exit", run.get("exit"), "plan", calls("plan"), "panel", calls("panel"))
        continue
    plan = json.load(open(os.path.join(d, "plan.json")))
    panels = man._parse_prompts_md(os.path.join(d, "story.md"))[1]
    phrases = [c["phrase"] for c in plan["cast"] if c.get("phrase")]
    mentions = se._mentions(plan["cast"])
    n = dict(static=0, contra=0, speaks=0, after=0, copies=0)
    for k, p in enumerate(panels, start=1):
        text = p["prompt"] if plan["mode"] == "no_stills" else p["motion"]
        sents = se._sentences(text)
        words = [w for i, _k in se.camera_directions(lib, text, phrases)
                 for w in se._camera_words(sents[i])]
        n["static"] += (not words) or all(w in STILL for w in words)
        n["contra"] += se.camera_problem(lib, text, phrases, None) is not None
        n["speaks"] += se.DIALOGUE_RE.search(text) is not None
        beat = plan["beats"][k - 1]
        if p.get("dialogue", "").strip() and beat.get("speaker"):
            others = [m for m in mentions if m[0] != beat["speaker"]]
            own = [m for m in mentions if m[0] == beat["speaker"]]
            post = se.post_line_sentences(lib, text, phrases)
            n["after"] += bool(se.EXIT_RE.search(text)
                               or any(se._other_actor(s, others, own) for s in post))
        n["copies"] += any(se.reference_copies(plan["narrative"], plan, p.get(f, ""),
                                               plan.get("goal"))
                           for f in ("image", "motion", "prompt", "dialogue", "narration"))
    seq = []
    for p in panels:
        if p.get("dialogue", "").strip():
            phrase, line, _problem = lib.parse_dialogue(p["dialogue"], phrases)
            seq.append(((phrase or "").lower(), se.line_words(line)))
    want = se.line_speakers(plan["narrative"], plan["cast"])
    ok, pos = True, 0
    for i, spoken in enumerate(se.spoken_lines(plan["narrative"])):
        target = se.line_words(spoken)
        who = se.speaker_phrase_of(plan, want[i]).lower() if want[i] else None
        while pos < len(seq) and not ((who is None or seq[pos][0] == who) and any(
                seq[pos][1][j:j + len(target)] == target
                for j in range(len(seq[pos][1]) - len(target) + 1))):
            pos += 1
        ok = ok and pos < len(seq)
    checks = json.load(open(os.path.join(d, "story_checks.json")))
    repairs = sorted(a["id"] for a in checks["advisory"] if "the pipeline removed" in a["message"])
    p18 = len([a for a in checks["advisory"] if a["id"] == "P18"])
    p19 = [a["message"] for a in checks["advisory"] if a["id"] == "P19"]
    total["panels"] += len(panels)
    total["static"] += n["static"]
    print(sid, "exit 0", "panels", len(panels), "static", n["static"], "contradictions",
          n["contra"], "speaks", n["speaks"], "after-line", n["after"], "copies", n["copies"],
          "lines ok", ok, "plan", calls("plan"), "panel", calls("panel"), "critic",
          calls("critic"), "repairs", repairs, "P18", p18, "P19", p19,
          "median panel s", secs[len(secs) // 2] if secs else None)
print("TOTAL panels", total["panels"], "static", total["static"],
      "ratio %.2f" % (total["static"] / float(total["panels"] or 1)))
```

### 5.3 KPIs (gating for the live report; measured on `measure_after.txt`)

| # | KPI | Target |
|---|---|---|
| K1 | Static panels, pooled over the 9 runs that exit 0 | ratio <= 0.35, and every run <= `ceil(panels/3)` |
| K2 | Camera contradictions (more than one direction, or still plus move) | 0 panels |
| K3 | A speaking verb in a Motion or Prompt | 0 panels |
| K4 | An exit, or another actor after the line, in a speaking panel | 0 panels |
| K5 | Reference copies | 0 panels |
| K6 | Every narrative line present, in order, spoken by its attributed character (`lines ok`) | True for every run |
| K7 | Exit code | 0 for all 9. Any other exit is reported with its stderr, plan/panel/critic call counts and `repairs`; that is a KPI miss, not a contract failure |
| K8 | The P19 note (Amendment SF-A1) | `sf1-hk2` shows exactly one P19 ending `rerun with --force-story --panels 3 to keep it`, and `sf1-hk1` one ending `rerun with --force-story --panels 2 to keep it`, in `measure_after.txt` and as a `Warning: plan: P19 ...` line in `$R/run-sf1-hk2.log` and `$R/run-sf1-hk1.log`. `sf1-hk3s` shows P19 (`--panels 4`) exactly when its plan puts line 2 in beat 3. No `sf1` pin run shows P19 |

**Recorded, not gating:**
- the same rows for the before runs;
- the `repairs` ids and P18 counts;
- each run's plan and panel call counts;
- the median panel-call seconds before and after (the SF8 latency budget);
- `panel_01_prompt_1.txt` character counts;
- for `sf1-hk2` and `sf1-hk1`, whether the skate-away appears anywhere (expected: no, per Section 0.5; K8 checks that the user is told).

### 5.4 Render A/B (4 pairs, for the user's eyes and ears)

The pairs are `sh2`, `ch3-a`, `hk2` and `hk1` **[spec choice]**. They cover shots and chained, 1-3 panels, a silent pinned co-star, a 10-second clip with two lines, and the E2/E4 hockey shapes. That is 8 clips per side, 16 clips in all.

- **Before renders:** WS at `3970e96`, before the merge, one at a time. Rerun each `sf0-<name>` command **without** `--story-only` and **without** `--force-story`: Phase 1 re-checks the existing `story.md` and the movie renders with the `3970e96` manifest.
- **After renders:** the same with `sf1-<name>` after the merge.
- Never run two renders at once, and never run the story server during a render.
- Write `$R/ab.html`: one row per pair. Each row has two `<video controls src="...">` elements (the before and after `movie.mp4`, by absolute `file://` path) and, under each, every panel's `motion_prompt` from that story's `manifest.json`.
- The user watches and listens. The outcome is recorded in the report and does not gate this spec. It decides the future A/Bs of Section 0.5.

---

## 6. Rollout

1. Snapshot (house rule): `tar czf $S/snapshot-pre-shot-format-3970e96.tgz -C /Users/reubenpatterson/local_agent_harness --exclude 'qwen-agent-workspace/generated' qwen-agent-workspace`. Record the full-suite pass count and the pre-existing failure list at `3970e96`.
2. Implement in a git worktree of `qwen-agent-redteam` at `3970e96` (for example `$S/sf-wt`), so that WS stays at `3970e96` for the before runs.
   - Commit 1 (feature): G1-G4.
   - Commit 2 (tests only): G5, with the per-file explanations of Section 4.2.
   - Commit 3 (tests only): G6.
   - Run SK1-SK3 in the worktree.
3. Opus design review of the diff against this spec. Fix, then re-run SK1.
4. Once the accent render has finished: the Section 5.1 before runs (`sf0-*`) and the Section 5.4 before renders, all in WS at `3970e96`.
5. Fast-forward WS to the reviewed commits.
6. The after runs (`sf1-*`), both measures, the after renders and `$R/ab.html`.
7. Report: K1-K7 with both measure files, the recorded rows, the exit codes and the A/B page path.

PR note (required, in substance): "Phase 1 now plans one camera move per panel (static at most one panel in three) and tells the writer that move; the writer writes the one camera sentence with its end frame, and the pipeline's sentence is only a fallback. A speaking panel's final prompt is shot type, action, the line, one reaction, camera, then the audio sentence last; nobody leaves or acts after the line, speaking verbs are cut, and writers see a format-only reference that a hard check keeps them from copying. Old stories re-check exactly as before; regenerate one with `--force-story` (movie-ui: Regenerate)."

---

## 7. Values chosen by the spec

1. **Camera list.** Moves first and static last; `handheld` added; existing fallback sentence texts kept (D1, SF1).
2. **Speaking coercion target** is `slow push-in`, for P14 and for chained k >= 2 paste-time cameras. Static stays a valid speaking camera (D2, SF4).
3. **Static ratio.** P18 is a deterministic cap with an advisory note: not retried, not fatal, latest statics kept (D3, SF5).
4. **Writer camera sentence.** An em-dash form with the end frame, built from `CAMERA_WRITER_FORMS`; no "slowly" (D4, SF7).
5. **Chained k >= 2 silent panels** get the planned camera fallback (D4, SF6).
6. **N20** runs on the assembled field, with the deterministic parse-time repair; the round-0 re-ask is used only when a clause cannot be cut (D5, SF9, SF11).
7. **Composition in the manifest.** Framing comes from `Image:`, and the new order applies only to speech movies in chain/shots. Voice-over-only movies are byte-identical (D6, SF15, SF16).
8. **Audio.** `ACOUSTIC_SENTENCE` gains "and there is no music"; `AMBIENCE_SENTENCE` closes silent panels of speech movies (D6).
9. **N21.** Exits (anywhere in a speaking panel) and other actors (after the line) are hard; more than one reaction is advisory; `EXIT_RE` is the exact list in SF10 (D7).
10. **Repair path.** Parse-time deterministic fixes, one round-0 re-ask on the existing budget, then a trim that keeps one action sentence; the critic and code-only rounds accept the new ids (D8, SF13).
11. **N7** is hard only while generating, and only on the Motion or Prompt, with a clause cut. Recheck stays advisory (D10, SF11).
12. **N22 terms and segments** are as listed; the narrative and plan are exempt; it is separate from `COPIED_EXAMPLES`/N10 (D11, SF12).
13. **Reference placement.** A constant, inserted before `@@SEED_PANEL@@` in chained and shots prompts when narration is not False (D9, SF8).
14. **Shots reaction.** It is offered only when the clip fits two actions (`engine_seconds >= 6`). Shots S5 allows 2 action sentences on a speaking panel in generation only (SF7, SF14).
15. **Word ranges.** `(55, 105)` for chained and shots Motion (D13).
16. **Planner speaking-beat sentence.** It also bans a speaking verb in the beat action (`SPEAKING_BEAT_SENTENCE`, "never as speaking"), the upstream cause of E3 (SF3).
17. **Generation-only checks.** New ids are placed before `Q1` in `GENERATION_CHECKS`; nothing is added to `RECHECK_IDS` (D12).
18. **Live configurations.** The third hockey configuration is shots with 3 panels (`hk3s`). The A/B pairs are `sh2`, `ch3-a`, `hk2` and `hk1` (Section 5).
19. **The critic speaking clause** stays chained-only (text updated) (SF13h).
20. **P19 "exit left out"** is a plan-level advisory note: deterministic (narrative exit after the last spoken line, and that line in the last beat), never hard, and suggesting `--panels` + 1 (Amendment SF-A1).

---

## 8. Risks and questions

### 8.1 Risks

- **R1. Longer Motion fields mean more action.** Raising the range to 55-105 words gives the writer room for extra action sentences, so T2 or T3 can fire more often in shots. Those are repaired by the existing critic path, and they are non-blocking. Section 5 records the critic call counts.
- **R2. False positives in `EXIT_RE` and `_other_actor`.** For example "the tide recedes" in a speaking panel, or a group noun used as a subject. Each costs one re-ask, then a trim of that sentence. SFT18 pins the conservative list.
- **R3. Deterministic repairs lose writer content.** A wrong-move camera sentence, together with its end framing, is replaced by the fallback; a cut clause may drop detail. Every removal is visible as a `the pipeline removed` advisory.
- **R4. Prompt size and latency.** Each writer call gets about 700 more prompt tokens (SF8). On the local 27B 6-bit model this lengthens prefill. Section 5 records the median call time.
- **R5. "no music" in a distilled model** may not suppress music (Section 0.5). Judged in the A/B.
- **R6. Re-baselining volume.** Section 4.2 is large. The per-file explanation rule makes every golden change auditable.

### 8.2 Decisions confirmed (user-approved 2026-10-28)

All six were reviewed and approved by the user on 2026-10-28. C4 was approved as option A, with the note defined in Amendment SF-A1.

- **C1 (approved).** `WORD_RANGES` for chained and shots Motion grow from (15, 35)/(10, 25) to (55, 105) (D13). Without this, the writer is asked for 5-14 words while being shown a reference of about 70-word fields.
- **C2 (approved).** `ACOUSTIC_SENTENCE` changes text (", and there is no music"), and silent panels of speech movies gain `AMBIENCE_SENTENCE` (D6). The brief bound "no music" only for the reference.
- **C3 (approved).** Framing is added by the manifest from `Image:` rather than written into `story.md` (D6).
- **C4 (approved as option A).** In a movie with too few panels, an exit after the last line is left out, and the user is told with a hint naming the panel count that would keep it (Amendment SF-A1). This supersedes [WP] WK7's "line before the skate-away". A follow-on soft-panel-count spec will remove the limit (Section 0.5).
- **C5 (approved).** Chained k >= 2 silent panels now carry the planned camera sentence (D4).
- **C6 (approved).** The format reference is left out of `no_stills` and `--no-narration` movies (D9).

### 8.3 Open

None.


## Amendment 2026-10-28 (user review)

### SF-A1. P19 "exit left out": tell the user when an exit after the last line is not filmed

**Rule.** A movie leaves out the narrative's exit after its last spoken line when that line is in the movie's last beat: a speaking beat never shows its speaker leave (SF3, SF10), and no later beat exists. When that happens, the pipeline adds one advisory note that names the panel count that would keep the exit.

**Where it is detected: the plan level only [spec choice].** The condition is a pure function of the narrative and the accepted plan, so it is deterministic and testable without any writer reply.
- **Rejected: the N21 trim path.** It depends on whether the writer happened to write the exit. The planner usually leaves the exit out of the beat action (SF3), so the trim would not fire in most runs where the exit is lost, and it would fire for exits the narrative never had.
- **Rejected: detecting that no beat action contains the exit.** Matching the narrative's exit wording against free-form beat actions is not deterministic (paraphrases, pronouns). The note instead fires on the one case where the exit cannot be placed at all: no beat follows the last line.

**Code (`story_engine.py`).** Add immediately after `EXIT_RE` (SF10):

```python
# Shot prompt format spec amendment SF-A1: the narrative's exit after its last spoken line is
# left out when that line is in the last beat.
P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; rerun with --force-story --panels %d to keep it")


def narrative_exit_after_last_line(narrative):
    """The EXIT_RE words (lower case, whitespace collapsed) of the first exit in the narrative
    text after the closing quote of its last spoken line, or None (SF-A1). The quotes are paired
    as in line_speakers: curly quotes count as straight ones, and classify_quotes decides which
    quote is spoken."""
    text = narrative.replace("“", '"').replace("”", '"')
    spoken = [match for match, (inner, said) in zip(QUOTE_RE.finditer(text),
                                                    classify_quotes(narrative))
              if said and line_words(inner)]
    if not spoken:
        return None
    found = EXIT_RE.search(text[spoken[-1].end():])
    return " ".join(found.group(0).lower().split()) if found else None


def exit_left_out_notes(ctx, plan):
    """[P19_NOTE] when the narrative has an exit after its last spoken line and the beat that
    says that line is the last beat, else [] (SF-A1)."""
    lines = plan.get("spoken_lines") or []
    if ctx.narration is False or not lines:
        return []
    found = narrative_exit_after_last_line(ctx.narrative)
    last = plan["beats"][-1] if plan["beats"] else None
    if found is None or last is None or len(lines) not in last.get("lines", []):
        return []
    return [P19_NOTE % (_q(found), ctx.panels + 1)]
```

**Call site.** In `_Run.go`, immediately after `plan["speech_notes"] += cap_static_cameras(ctx, plan)` (SF5), add `plan["speech_notes"] += exit_left_out_notes(ctx, plan)`. It runs after `assign_missing_lines`, so a line the pipeline placed counts.

**Where it is recorded and printed.** The note goes into `plan["speech_notes"]`, so it is:
- in `plan.json`;
- in every state's advisory list (`plan_checks` adds `speech_notes`, `:1730`), and so in `story_checks.json` `advisory`;
- in the advisories `se.run` returns, which `bin/ltx-movie:1634-1635` prints as `Warning: plan: P19 exit left out: ...`, like every other advisory.

It is advisory: never hard, never retried, never blocking.

**Example.** For the hockey narrative with `--panels 2`: `plan: P19 exit left out: the narrative's exit after its last spoken line ('skates away') was left out, because that line is in the last beat and a speaking beat never shows its speaker leave; rerun with --force-story --panels 3 to keep it`. With `--panels 1` it ends `rerun with --force-story --panels 2 to keep it`.

**When it does not fire.**
- `--no-narration` (`ctx.narration is False`), or the narrative has no spoken line.
- No `EXIT_RE` match after the closing quote of the last spoken line. An exit before the last line, or between two lines, is not covered.
- The last spoken line is in a beat before the last beat (a later beat can hold the exit; whether the planner used it is not checked).
- The last spoken line is in no beat (story Q1 handles that).
- `recheck`, which runs no plan step, so old stories and re-checked stories never show it.

**Tests:** SFT23-SFT25 (Section 4.1). **Re-baseline code:** R17 (Section 4.2). **Live check:** K8 (Section 5.3).

**SF-A1 erratum (coordinator, 2026-10-29).** The P19 hint reads "rerun with --force-story --panels %d to keep it". Without `--force-story`, a rerun with a different `--panels` re-checks the saved story and exits 1 ("expected exactly n panels"), so the hint must name both flags. Found by the soft-panel-count design review.
