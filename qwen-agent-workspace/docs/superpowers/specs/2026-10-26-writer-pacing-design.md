# Writer pacing: the speech point, fast concrete motion, named effects

Date: 2026-10-26

Status: design spec. Every design choice is made here; each one the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `88213da`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `88213da`.

Specs this one builds on, cited by tag:
- **[NF]** `docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`. It covers Q1, the assigned-lines paste, F2 (speaking shots may move) and SP-P (the spoken line goes after the first action sentence).
- **[DLG]** `docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md`. It covers the Dialogue field, T1-T3, N17 and the critic patches PG1-PG5.
- **[PACE1]** The panel-1 pacing fix, already shipped in commits `5cda31e` and `6a0b303`. Its spec is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/pacing-spec.md` and its report is `.../scratchpad/pacing-report.md`. It took "slowly" out of the camera sentences, set the chained panel-1 band to (15, 35) and added the panel-1 pacing sentence. This spec keeps all of that except the wording of the one panel-1 pacing sentence, which it replaces (WP1).

---

## 0. Purpose and scope

### 0.1 Evidence

**E1. The A/B pacing experiment (2026-10-25).** The files are in `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/hockey/ab/`. `run_ab.sh` and `run_f.sh` each render one panel-2 prompt with `ltx-2-mlx generate --distilled`, from the same chain seed, at seed 2.
- **LTX-2.x runs distilled.** It has no CFG and no negative prompt, so negative wording ("no slow motion") cannot suppress anything.
- **"Slow motion" is under-generated motion, not timing.** Fast, concrete verbs ("skates hard ... with quick, powerful strides", "snaps into", "pushes off ... at full speed") roughly doubled the optical flow against `B_base_97` ("skates forward, then halts ...").
- **Naming the physical effect makes it appear.** `F_spray_145` ("digs both skate edges into the ice in a hard hockey stop that throws a big, bright spray of ice shavings up into the air in front of him") shows a dense spray at t=3.29 s in `F_spray_145_sheet.jpg`.
- **Limiting the effect's duration removes it.** `C_fast_145` ("a short fan of ice shavings that falls back to the ice within half a second") shows no visible spray in `C_fast_145_sheet.jpg`.
- **Real-time wording helps.** Both fast prompts ended "Real-time speed, no slow motion."

**E2. The NK8 live rerun (2026-10-26, after [NF]).** The logs and checks are in `.../scratchpad/hockey/rerun/`: `run-hockey-2x145-f.log`, `run-hockey-1x241-f.log`, the whisper JSONs `2x145_p1.json`, `2x145_p2.json` and `1x241.json`, `sheet_2x145_p02.jpg` and `sheet_1x241.jpg`. The stories are `generated/stories/hockey-2x145-f/` and `generated/stories/hockey-1x241-f/`. Both runs exited 0, both lines were verbatim in `Dialogue:`, and whisper heard both lines.
- **2x145 panel 2, the order failure.**
  - Plan beat 2 is "He stops short, kicks up a spray of ice mist into the air, says the closing line, then skates away from the camera." The plan already states the speech point.
  - The writer replied with one action sentence and one camera sentence: "The FuboTV hockey player carves a sharp stop, spraying ice mist into the air, his face toward the lens, then pushes off and skates away from the camera. The camera holds on him as he recedes."
  - The body has one action sentence, so the SP-P branch never fires (`character_lib.py:735`, `len(actions) >= 2`). The line went after the whole sentence, before the trailing camera run (`manifest.json` `panels[1].motion_prompt`).
  - In the clip he stops and sprays at about 0.5 s and skates away at about 1.3-3.3 s. After a whip back to a close-up, he says "It's just FuboTV." at about 3.7-5.1 s. The narrative order (stop short with ice mist, then line 2, then skate away) was lost.
- **The writer prompt caused it.** In `story_rounds/round_0/panel_02_prompt_1.txt`, the motion key line says "one or two plain sentences ... Describe ONE continuous physical motion, not a sequence of separate steps", then "a speaker who approaches the camera speaks once close". Nothing told the writer where the line goes or how to split the sentences around it. N12 ("chains actions with 'then'") fired, but it is advisory.
- **The same Motion ends "The camera stays static."** That is the planned camera of beat 2, pasted per [NF] SM3. It comes after the writer's "The camera holds on him as he recedes."
- **1x241, a faint spray.** The Motion "skates toward the camera, stops short, and kicks up a spray of ice mist. He then skates away from the camera." has two action sentences. Both lines landed after the stop and before the skate-away; whisper heard them at 0.0-3.04 s and 6.16-7.36 s. The ice spray is barely visible (`sheet_1x241.jpg`, row 2, column 3).
- **Recorded checks.** 2x145-f advisory: `N7 'speaks'` (panel 1 copied "as he speaks" from the writer instruction), `N12 'then'` and `N1 46 words` (panel 2). 1x241-f advisory: `N12 'then'`. Neither run has a hard violation.

**E3. Final-review item M3 of [NF].** `SPEAKING_ACTION_SENTENCE` (`story_engine.py:1754-1758`) says "a speaker who approaches the camera speaks once close". Since SP-P, the manifest places the line after the **first** action sentence of a chained or shots Motion. The writer wording must state the placement that the code applies.

### 0.2 Grounding (verified at 88213da)

**`story_engine.py` (3669 lines, stdlib only)**
- `SPEECH_FRAMING_SENTENCE` `:36-39`; `CAMERA_SENTENCES` `:44-53`; `WORD_RANGES` `:56-58` (chained `motion1` and `motion` are both `(15, 35)`).
- `FACING_SENTENCE` `:1229`; `pasted_pieces` `:1260-1283`. A speaking chained panel's Motion pieces are `facing + [camera]`: `:1278` for k=1 and `:1279-1280` for k≥2.
- `KEY_LINE_TEMPLATES` `:1679-1740`:
  - `chained_motion1` `:1688-1695`, whose [PACE1] pacing sentence is at `:1693-1694`;
  - `chained_motion` `:1696-1703`;
  - `shots_motion` `:1724-1729`, which allows ONE sentence and never "then";
  - `no_stills_prompt` `:1704-1715`.
- `dialogue_fixed` `:1743-1746`; `no_stills_prompt_speaking` `:1747-1751`.
- Speaking sentences:
  - `SPEAKING_ACTION_SENTENCE` `:1752-1758`, the M3 text;
  - `SPEAKING_PROMPT_SENTENCE` `:1759-1760`; `SPEAKING_IMAGE_SENTENCE` `:1761-1762`;
  - `SPEAKING_SENTENCES` `:1763-1764`, keyed by writer key, so chained and shots Motion share `SPEAKING_ACTION_SENTENCE`.
- `panel_fields` `:1899-1929`. Motion is the writer text, then the pasted pieces. Engine assembly never composes speech ([NF] SP-P3).
- Checks:
  - `SEQUENCE_RE` `:1949`; `action_units` `:1969-1983`. Chained units are `1 + sequence markers + max(0, action sentences - 2)`.
  - `_field_checks` `:2018-2270`: N7 `:2100-2106`, T2/T3 `:2149-2170`, N12 `:2184-2192` (advisory), N17 `:2223-2255`.
  - `spoken_line_problems` (Q1) `:2328-2355`; `GENERATION_CHECKS` `:2358-2359`.
  - `NON_BLOCKING_IDS` `:2943`; `REPAIR_IDS` `:2945`; `RECHECK_IDS` `:3478-3479`; `recheck` `:3580`.
- `build_panel_prompt` `:2413-2490`. The key-line loop is `:2440-2463`, and the speaking sentence is appended at `:2457-2458` (`if speaks: line += SPEAKING_SENTENCES.get(key, "")`).
- Critic:
  - `CRITIC_PROMPT_TEMPLATE` `:2502-2544`; `CRITIC_Q1_FIELD_LINE` `:2555-2561`.
  - `critic_field_lines` `:2571-2594`, with the Motion/Prompt patch line at `:2582-2586`.
  - `build_critic_prompt` `:2597-2622`, with the field-lines call at `:2611-2612`. The engine's critic call is at `:3232-3234` (`narration=self.ctx.narration`).

**`character_lib.py`**
- `_SENTENCE_SPLIT_RE` `:126`; `_CHAIN_WORD_RE` `:128`.
- `insert_speech` `:718-745`, with the first-action branch at `:731-740`; `_is_camera_sentence` `:984`; `is_facing_sentence` `:1112`.

**`bin/ltx-story-manifest`** composes speech in exactly one place, `:826-832`: `insert_speech(motion_prompt, speech_text(...), [speaker], first_action=bool(args.chain or args.shots))`.

**`bin/ltx-movie`** composes no prompt text. `phase3_manifest` (`:2012`) only runs `bin/ltx-story-manifest` with `--chain` or `--shots` and `--speech-delivery`.

**`bin/judge-story`**: `main_patches` `:342` builds its user message with story_engine's `build_critic_prompt(..., for_judge=True)` (`:370-371`). Its `PATCH_FIELDS` is at `:147`.

**Measured with a scratch simulation of this spec's constants, run against the recorded 2x145-f plan and parts in the test environment:**
- The two-sentence Motion "The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of ice. The FuboTV hockey player skates away at real-time speed." composes with the line between the stop and the skate-away (WT5). It has 0 hard violations and no N12 or N1 on panel 2 (WT6).
- The same placement holds when the writer puts a camera sentence first or last.
- The recorded parts reassemble byte-identically to the recorded `story.md`, and `panel_checks` reproduces the recorded `story_checks.json` messages exactly.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | WP1-WP5 (Section 2) |
| G2 | `tests/test_writer_pacing.py` (new) | WT1-WT9 (Section 4.1) |
| G3 | `tests/fixtures/writer_pacing/` (new) | verbatim copies of the E2 artifacts plus two hand-written `case.json` (4.2) |
| G4 | existing tests | only the edits of Section 4.3 A |
| G5 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit** |

**Not changed:**
- `character_lib.py`: `insert_speech`, `is_facing_sentence`, `_is_camera_sentence`, `speech_text` and every regex. **The placement code stays as it is; the writer is told how it works.**
- `bin/ltx-story-manifest`, `bin/ltx-movie`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`. `bin/judge-story --patches` gets WP4 through `build_critic_prompt`, with no edit to its file.
- The plan prompt: `PLAN_PROMPT_TEMPLATE`, `SPEAKER_RULE`, `LINES_RULE`, `SILENT_SPEAKER_RULE`. The recorded plans already state the speech point in the beat action.
- `SPEAKING_ACTION_SENTENCE` keeps its exact text and is still used for shots Motion (D2). `SPEAKING_SENTENCES`, `SPEAKING_PROMPT_SENTENCE`, `SPEAKING_IMAGE_SENTENCE`, `SPEECH_FRAMING_SENTENCE`, `dialogue_fixed` and `no_stills_prompt_speaking` are also unchanged.
- `shots_motion`, `shots_image`, `chained_image`, `no_stills_prompt` and every other key line except the two chained Motion lines.
- `CAMERA_SENTENCES`, `SPEAKING_CAMERA`, `pasted_pieces`, `panel_fields`, `WORD_RANGES` and `MIN_WRITER_WORDS`.
- Every check: N1-N19, T1-T3, Q1, P*, S*. `GENERATION_CHECKS`, `RECHECK_IDS`, `NON_BLOCKING_IDS` and `REPAIR_IDS` are unchanged, and no check id is added.
- `apply_patches`, PG1-PG5, `repairable_ids` and `CRITIC_PROMPT_TEMPLATE`.
- The `--story-legacy` templates and path; `movie_ui_lib.py` and `static/*`; `ltx2_mlx_video_skill.py`.

### 0.4 Out of scope

- **`--auto-duration`** (E1's `E_fast_auto`). This is a separate follow-up.
- **The camera-sentence clash** ("The camera stays static." while the speaker recedes). D4 decides that it needs no change.
- **Clause splitting** of a writer sentence at ", then", and any new deterministic check of the speech point (D3).
- **Several insertion points for a multi-line beat.** The 1x241 narrative has the stop between line 1 and line 2. A beat whose `Dialogue:` holds both lines still speaks them at one point (R5).
- **Pacing text for shots and no_stills** (D5).
- Pasting a real-time sentence or phrase by code (D5).
- Changing the word bands of [PACE1].
- Measuring optical flow, lip-sync or audio quality as a gate.
- Branding legibility and stray props.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| WK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the pass count recorded just before implementation plus every WT test, with no lost pass. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Both are measured after the G5 commit. | full run |
| WK2 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`. | `test_rst61` |
| WK3 | Import sets are unchanged: `story_engine.py` gains no import. | `test_rst62` |
| WK4 | **The writer contract is in the prompt.** For chained speaking panels, the motion key line carries the speech-point sentence (WP2), and the old "speaks once close" text is absent. Both chained Motion key lines carry the pacing sentence (WP1). Shots and no_stills prompts are byte-identical to today. | WT1-WT4 |
| WK5 | **The contract matches the placement.** A Motion written to the contract composes, through the unchanged `insert_speech`, with the spoken line between the first sentence and the second. It has no T2, N12 or N1 on the evidence plan. | WT5, WT6 |
| WK6 | **Old stories are unchanged.** The recorded 2x145-f and 1x241-f stories compose to their recorded `manifest.json` `motion_prompt`s byte for byte. Their checks reproduce the recorded `story_checks.json` messages, and re-check exits 0. Legacy output stays byte-identical. | WT8, WT9, `test_rst40`, `test_rst41`, `test_s52`, `test_casting_regression.py` |
| WK7 | **Live, post-merge, not a merge gate.** Section 5: both hockey prompts with story ids `hockey-2x145-p` and `hockey-1x241-p`. Phase 1 exits 0, the lines are verbatim, whisper hears both, the 2x145 panel 2 line comes before the skate-away, and the ice spray is visible in both contact sheets. | Section 5 |

### 0.6 Must-have and nice-to-have

WP1-WP5 and the tests (Section 4) are must-haves. Nothing else is built: no new check, no new CLI flag, no paste, and no change to placement or to the plan prompt.

---

## 1. Design decisions

### D1. The speech point: a writer contract on the existing placement **[spec choice]**

**Chosen.** The writer of a chained speaking panel is told exactly what the code does: "the pipeline inserts the dialogue right after the first sentence about what the speaker does". The writer writes:
1. **First sentence:** everything the speaker does before the dialogue, ending near the camera and facing it.
2. **Second sentence:** only when the beat has the speaker act after the dialogue, what they do then.
3. **Never** an action from before the dialogue and one from after it in the same sentence.

This is "one sentence on each side of the speech point".

**Why this works with no code change:**
- `insert_speech(first_action=True)` places speech after the first action sentence when the body has two or more (`character_lib.py:731-740`). With one action sentence, it places speech after that sentence, before the trailing camera run (`:741-743`). Under the contract both branches give the same rule: speech follows sentence 1.
- Camera sentences are not action sentences, so a writer camera direction before, between or after the two sentences does not move the speech point (verified, WT5).
- The base template already says "in one or two plain sentences" (`:1689`, `:1697`), so the contract adds no sentence-count conflict.
- Two sentences with no "then" are 1 T2 unit in chained mode (`:1977`), within the 2 units a 6-second clip fits.

**Rejected: literally one action per sentence.**
- With first-action placement, two actions before the dialogue in two sentences put the line after the first of them.
- For beat 2 ("stops short, kicks up a spray ..., says the closing line, then skates away"), "He stops short. He throws a spray of ice. He skates away." speaks between the stop and the spray.
- The contract keeps every pre-dialogue action, effect included, in sentence 1.

**Rejected: the writer marks the speech point explicitly.** The options were a marker token in Motion or a second writer key such as `after_line`.
- Either changes the writer reply shape: `writer_keys`, `parse_panel_reply`, `empty_parts`, `clean_writer` and `panel_fields`.
- It changes how story.md carries the point. Either a marker appears in Motion, which every check, the critic, judge-story and the manifest parser then see, or the facing sentence must move mid-Motion and act as the marker.
- `recheck` and the critic's whole-Motion patches (PG3) would have to recover the split from story.md.
- It needs a new compatibility rule for old stories.
- All of that buys only what a stated contract already gives: the beat text already orders the speech, and the placement already honours sentence 1.

### D2. M3 wording **[spec choice]**

- The chained speaking sentence (WP2) replaces "a speaker who approaches the camera speaks once close" with the placement rule itself: "ending with them near the camera". An approaching speaker therefore speaks once close, because the approach is sentence 1.
- **Shots keeps `SPEAKING_ACTION_SENTENCE` unchanged.** `shots_motion` allows ONE sentence and never "then" (`:1725-1728`), so a shots Motion has one action sentence and the line always follows it, which is after the approach. In shots mode, "speaks once close" already states the placement. Giving shots the two-sentence contract would contradict its one-sentence rule.
- no_stills keeps `SPEAKING_PROMPT_SENTENCE`. Its placement is unchanged: before the trailing camera run ([NF] SP-P2).

### D3. No new deterministic check, no clause splitting **[spec choice]**

Three alternatives were considered and rejected:
- **(a) A lexical check** on a speaking Motion sentence that holds ", then" or "and then". It is brittle in both directions:
  - It fires on correct pre-dialogue chains. The [NF] fixture Motion "skates forward, then halts in a sharp hockey stop ... He skates away from the camera." already speaks after the halt, correctly.
  - Its repair (writer re-ask or critic patch) pushes a split that can land the line one action too early.
  - It cannot tell a pre-dialogue "then" from a bridging one without the narrative.
- **(b) A plan-text check.**
  - Find a speech verb (`DIALOGUE_RE`) in the beat action, then a later clause. Flag a writer Motion with one action sentence.
  - It is precise on E2: it fires on 2x145 beat 2, and is silent on 2x145 beat 1 and on 1x241, whose Motion has two sentences.
  - It depends on the planner's free wording. "Delivers the closing line" has no `DIALOGUE_RE` verb. "Says the line as he glides to a stop" is simultaneous, not before.
  - It needs a new id with hard, non-blocking, repairable wiring in five places.
  - It is **the designated follow-up if WK7 (c) fails**. It is not built now.
- **(c) Splitting by placement** at ", then".
  - It creates subjectless fragments ("Then pushes off and skates away.").
  - It splits the [NF] fixture Motion at the wrong point (between "skates forward" and "halts").
  - It changes the composition of every old story whose single sentence holds "then".

The existing N12 advisory still reports "then" chains. The critic gets the contract for its Motion patches (D6).

### D4. The camera-sentence clash is not changed **[spec choice]**

- Once the line comes before the skate-away, "The camera stays static." while he recedes is the intended sign-off: he speaks close, then skates away from a held camera.
- Static is the plan's own camera for beat 2. [NF] SM3 deliberately pastes the planned camera on chained k≥2 speaking panels, and `SPEECH_FRAMING_SENTENCE` only forbids leaving the frame *before the line ends*.
- The visible defect in E2 was the whip back to a close-up after the skate-away. That was LTX satisfying "faces the camera" and "says ..." placed after the departure, which is a placement symptom that D1 removes.
- The writer's own "The camera holds on him as he recedes." agrees with "stays static" (`holds` is in `STILL_CAMERA_MOVES`, so N17 is silent).
- WK7 (e) and (f) watch the result.

### D5. Pacing: one writer sentence for both chained Motion lines, not pasted, chained only **[spec choice]**

- **Writer text, not code paste.**
  - A pasted sentence (for example "The action happens at real-time speed.") counts as an action sentence.
  - It would add T2 units (`:1977`) and trip the SP-P branch on every one-sentence speaking Motion: the pacing sentence becomes action 2, so speech moves before it.
  - It would change every chained story.md and engine golden.
  - Writer wording puts "at real-time speed" inside an existing action sentence, so the sentence count does not change.
- **It replaces the [PACE1] sentence in `chained_motion1` and is added to `chained_motion`.**
  - [PACE1]'s "use plain action verbs with no adverbs of speed or manner" forbids the speed phrases ("at full speed", "at real-time speed") that E1 found helpful. The new sentence keeps its intent ("with no words that slow it down") and drops the ban on speed adverbs.
  - E1's panels and E2's slow panel 2 are chained k≥2, so `chained_motion` needs it as much as panel 1.
- **Chained only.** Every piece of evidence is chained.
  - `shots_motion` is one 10-25-word sentence under the S rules.
  - `no_stills_prompt` is a 150-220-word paragraph with its own connectors.
  - Neither has a measured pacing failure.
- **Effects.** The sentence names effects in the same sentence as their action, and as big, bright sprays, splashes or clouds (E1 F vs C, and the E2 1x241 faint spray). It never limits duration or size (E1 C).

### D6. The critic's Motion patch states the same contract **[spec choice]**

- In E2's predecessor run (NF28), the critic's T2 patch rewrote a speaking panel 2's Motion. A T2 cut that merges "stop" and "skate away" into one sentence reintroduces the E2 defect.
- When the plan has a speaking beat, the chained Motion patch line gets one clause stating the placement (WP4).
- Shots, no_stills and plans without a speaker keep byte-identical critic prompts.
- `bin/judge-story --patches` builds the same prompt, so it gets the clause with no edit.

---

## 2. Requirements (normative)

### WP1. `PACING_SENTENCE` and the two chained Motion key lines (`story_engine.py`)

Add this constant immediately before `KEY_LINE_TEMPLATES` (`:1679`), with the comment `# Writer pacing spec WP1, D5: fast, concrete motion at real-time speed, with named effects.`:

```python
PACING_SENTENCE = (" The motion plays at real-time speed: use fast, concrete action verbs, with no "
                   "words that slow it down, and end the main action with the words 'at real-time "
                   "speed'. When an action throws something up, such as ice, snow, water, dust or "
                   "sparks, name it in the same sentence as a big, bright spray, splash or cloud, "
                   "and never say how long it lasts, how small it is or when it settles.")
```

Replace the entries `chained_motion1` (`:1688-1695`) and `chained_motion` (`:1696-1703`) with:

```python
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps: @@SECONDS@@ seconds is enough for a single gesture, a few footsteps or the "
        "start of a movement." + PACING_SENTENCE + " You may add one camera direction; without "
        "one, the pipeline adds the planned camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement."
        + PACING_SENTENCE + " Do not describe appearance, clothing, setting, lighting, colour or "
        "style -- all of that is already on screen. You may add one camera direction."),
```

The [PACE1] sentence "The motion plays at natural, real-time speed: use plain action verbs with no adverbs of speed or manner." no longer appears anywhere in `story_engine.py`. Every other character of both entries is unchanged.

### WP2. `SPEAKING_CHAINED_MOTION_SENTENCE` (`story_engine.py`)

Add it immediately after `SPEAKING_ACTION_SENTENCE` (`:1758`). The comment line before it is `# Writer pacing spec WP2, D1, D2: a chained speaking panel's motion is one sentence before the dialogue (which character_lib.insert_speech places after it) and, when the beat goes on, one after it.`

```python
SPEAKING_CHAINED_MOTION_SENTENCE = (
    " In this panel @@SPEAKER@@ speaks the dialogue, and the pipeline inserts it right after the "
    "first sentence about what @@SPEAKER@@ does. Write that first sentence as everything "
    "@@SPEAKER@@ does before the dialogue, ending with them near the camera, face toward it (if "
    "the dialogue comes before they do anything, it is how they turn or step toward the camera; "
    "never write only that they face it); only when the beat has them act after the dialogue, "
    "write what they do then as a second "
    "sentence. Begin each of these sentences with @@SPEAKER@@, word for word, and write nothing "
    "about anyone else before the first one. The action before the dialogue and the action "
    "after it are the two parts of this one motion: never put an action from before the "
    "dialogue and one from after it in the same sentence, and do not write the spoken words or "
    "a speaking verb; the pipeline adds them.")
```

`SPEAKING_ACTION_SENTENCE` (`:1754-1758`) and `SPEAKING_SENTENCES` (`:1763-1764`) are unchanged. The comment above `SPEAKING_ACTION_SENTENCE` (`:1752-1753`) gains this sentence at its end: `Chained Motion uses SPEAKING_CHAINED_MOTION_SENTENCE instead (writer pacing spec WP2); shots Motion keeps this one (one action sentence, so the line follows it).`

**Amendment 2026-10-26 (Task 1 review).** `character_lib._is_camera_sentence` treats any sentence of four words or fewer that mentions the camera or shot ("He skates off camera.", "He faces the camera.") as a camera sentence, so a short second sentence could be skipped and the line placed after it; and "Describe ONE continuous physical motion" read as forbidding the two-sentence split. The sentence therefore also requires each of the two sentences to begin with the speaker's referring phrase word for word, with nothing about anyone else before the first, and names the two sentences as the two parts of one motion. WT1 pins the new text; WT5 pins "skates off camera" as placed after the line. Placement code is still unchanged. A later final-review amendment (M-1) changes the dialogue-first parenthetical to "turn or step toward the camera; never write only that they face it", because a first sentence that only says the speaker faces the camera is dropped from the action count as a facing sentence, which would place the line after the next action.

### WP3. `build_panel_prompt` uses WP2 for chained Motion (`story_engine.py:2457-2458`)

The two lines

```python
        if speaks:
            line += SPEAKING_SENTENCES.get(key, "")
```

become

```python
        if speaks:
            line += (SPEAKING_CHAINED_MOTION_SENTENCE if ctx.mode == "chained" and key == "motion"
                     else SPEAKING_SENTENCES.get(key, ""))
```

Nothing else in `build_panel_prompt` changes. The existing `.replace("@@SPEAKER@@", ...)` at `:2462` replaces both `@@SPEAKER@@` tokens of WP2, because `str.replace` with no count replaces every occurrence. Order in the motion key line: template (with W1/W2 and `@@SECONDS@@`), then `SPEECH_FRAMING_SENTENCE` under `--speech-only`, then WP2.

### WP4. The critic's chained Motion patch line (`story_engine.py`)

Add this constant immediately after `CRITIC_Q1_FIELD_LINE` (`:2555-2561`):

```python
# Writer pacing spec WP4, D6: a chained Motion patch on a speaking panel keeps the speech point.
CRITIC_SPEAKING_MOTION_CLAUSE = (
    " On a panel with a Dialogue: line, the pipeline inserts the spoken words right after the "
    "first sentence about what the speaker does, so keep everything the speaker does before "
    "the line in that first sentence and everything they do after it in a later sentence. Begin "
    "each of those sentences with the speaker's referring phrase.")
```

Change `critic_field_lines` (`:2571-2594`):
- Its signature becomes `critic_field_lines(mode, catalog_lines, narration=True, spoken=False, speaking=False)`.
- The Motion/Prompt line (`:2583-2586`) is built into a local `motion` string with today's exact text. Then `if speaking and mode == "chained" and narration is not False: motion += CRITIC_SPEAKING_MOTION_CLAUSE`, then `lines.append(motion)`.
- Append this sentence to the docstring: `With speaking (the plan has a speaking beat) in chained mode, the Motion line ends with CRITIC_SPEAKING_MOTION_CLAUSE (writer pacing spec WP4).`
- Nothing else changes. In particular the lora, dialogue and Q1 lines and their order are as today.

**Amendment 2026-10-26 (Task 1 review).** The clause ends with "Begin each of those sentences with the speaker's referring phrase.", matching the WP2 amendment, so a critic Motion patch cannot put a short camera-like sentence ("He skates off camera.") where the placement would skip it.

### WP5. `build_critic_prompt` passes `speaking` (`story_engine.py:2611-2612`)

The call becomes:

```python
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines, narration,
                                               spoken=bool(plan.get("spoken_lines")),
                                               speaking=any(b.get("speaker")
                                                            for b in plan["beats"]))),
```

- `plan["beats"]` always exists, because every caller passes a normalized plan or a plan.json that `bin/judge-story` validated by schema.
- `b.get` covers a hand-built plan whose beat has no `speaker`.
- With `--no-narration`, every speaker is `""` (`coerce_speakers`), so `speaking` is False, and `narration is not False` guards anyway.

---

## 3. Interactions (normative)

| Area | Behaviour after this change |
|---|---|
| Placement (`insert_speech`, manifest) | Unchanged code. A contract Motion gives speech after sentence 1. A one-sentence Motion gives speech after it, as today. |
| T2/T3 | Unchanged. A contract Motion is 1 unit, or 2 with a "then" inside a sentence; it fits 6 s (2 units) and 10 s (3). |
| N12 (advisory) | Unchanged. It still reports "then", ";" and ", and"; the contract discourages bridging "then". |
| N7 (advisory) | Unchanged. WP2 drops the old text's "while they speak", which panel 1 of E2 copied ("as he speaks"). |
| N1 (advisory) | Unchanged bands. WP1 adds effect words and "at real-time speed" (4 words), so N1 may fire more often (R3). |
| N3 (advisory) | Unchanged. `big`, `bright`, `spray`, `cloud`, `splash` and `speed` are not in `APPEARANCE_WORDS` (verified); WP1 names no colour. |
| N13 (advisory) | Unchanged. The shared words `real`, `time` and `speed` raise consecutive-panel Jaccard slightly (R4). |
| N17, N16, N18, T1, Q1, P*, S* | Unchanged. |
| Code-only round (`REPAIR_IDS`) | The re-asked writer gets the same key lines, so WP1 and WP2 apply to the re-ask. |
| Critic | WP4 clause on chained plans with a speaker. Prompts for shots, no_stills and speakerless plans are byte-identical. |
| `bin/judge-story --patches` | The same prompt through `build_critic_prompt(for_judge=True)`, so it gets the clause. No file edit. `PATCH_FIELDS` is unchanged. |
| `bin/judge-story` (story judgment, no `--patches`) | Unchanged. |
| Old stories (story.md, plan.json) | No check, assembly or composition changes. Re-check gives the same result, and a re-render composes byte-identically (WT8, WT9). Only a regenerated story (`--force-story` or a new story id) gets the new writer text. |
| `--story-legacy` | Unchanged. |
| Shots / no_stills | Writer prompts are byte-identical (WT2, WT4). |
| `--no-narration` | WP1 applies (chained). WP2 and WP4 never apply, because no panel speaks. |

---

## 4. Tests

### 4.1 New: `tests/test_writer_pacing.py`

The file follows the `tests/test_narrative_fidelity.py` conventions:
- stdlib plus pytest;
- `story_engine.py` and `character_lib.py` loaded by path with `importlib.machinery.SourceFileLoader`;
- the autouse `story_env` fixture (`seu.set_story_env`), and `ws = seu.make_ws(tmp_path)`;
- every ctx under `tmp_path`.

No test renders, reads the real HOME, or contacts a model server, daemon or the Anthropic API. The module docstring states this, as test_narrative_fidelity.py's does.

**Helpers:**
- `FIX = tests/fixtures/writer_pacing`.
- `_case(name)` loads `FIX/<name>/case.json`.
- `HOCKEY` is `tests/fixtures/narrative_fidelity/narrative.txt`, stripped.
- `_ctx(ws, name, **kw)` returns `seu.make_ctx(se, ws, story_id=c["story_id"], mode="chained", panels=c["panels"], seconds=c["seconds"], clip_seconds=c["frames"] / 24.0, narration="speech", narrative=HOCKEY, goal=c["goal"])`, updated with `kw`.
- `_recorded(name)` returns `(plan, parts)`:
  - `plan` is `json.load(FIX/<name>/plan.json)`;
  - `parts` is `[{k: v for k, v in p.items() if k != "index"} for p in json.load(FIX/<name>/parts.json)["panels"]]`.
- `PHRASE = "FuboTV hockey player"`, `LINE1 = "Getting the best deal on hockey isn't a hat trick..."` and `LINE2 = "It's just FuboTV."`.
- `GOOD2` is `"The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of ice. The FuboTV hockey player skates away at real-time speed."`
- `SAY2 = lib.speech_text(PHRASE, LINE2, "beats")`.
- `MOTION_LINE` and `DIALOGUE_FIELD_LINE` are imported from `test_dialogue` as `dlg`.

| ID | Covers (exact assertions) |
|---|---|
| WT1 | **Constants.** `se.PACING_SENTENCE`, `se.SPEAKING_CHAINED_MOTION_SENTENCE` and `se.CRITIC_SPEAKING_MOTION_CLAUSE` equal the WP1, WP2 and WP4 literals, copied into the test file. `se.KEY_LINE_TEMPLATES["chained_motion1"]` and `["chained_motion"]` equal the WP1 entries, written out in full in the test as single literals (not built from `se.PACING_SENTENCE`). `se.SPEAKING_ACTION_SENTENCE` equals its `88213da` literal (test_narrative_fidelity's `SPEAKING_ACTION`), and `se.SPEAKING_SENTENCES == {"image": se.SPEAKING_IMAGE_SENTENCE, "motion": se.SPEAKING_ACTION_SENTENCE, "prompt": se.SPEAKING_PROMPT_SENTENCE}`. None of the five new or changed strings contains `"slowly"` (case-insensitive) or `"no adverbs"`. `"speaks once close"` is not in `SPEAKING_CHAINED_MOTION_SENTENCE`. The only `@@` tokens in them are `@@SECONDS@@` and `@@SPEAKER@@` (`re.findall(r"@@[A-Z_]+@@", s)` is a subset of those two) |
| WT2 | **Pacing reaches chained prompts only.** `dlg._story(ws, "chained", 3)`: the prompts of panels 1, 2 and 3 each contain `se.PACING_SENTENCE` exactly once, and none contains `"use plain action verbs with no adverbs of speed or manner"`. `dlg._story(ws, "shots", 3)` panels 1-2 and `dlg._story(ws, "no_stills", 3)` panel 1 contain neither `se.PACING_SENTENCE` nor `"at real-time speed"` |
| WT3 | **The hockey speaking prompts.** With `ctx = _ctx(ws, "hockey-2x145-f")` and `_recorded("hockey-2x145-f")`, take the line of `se.build_panel_prompt(ctx, plan, parts, k)` that starts with `"motion: "`. For k=1 it equals `se.KEY_LINE_TEMPLATES["chained_motion1"].replace("W1", "5", 1).replace("W2", "23", 1).replace("@@SECONDS@@", "6") + se.SPEECH_FRAMING_SENTENCE + se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"FuboTV hockey player"')`. For k=2 it is the same with `"chained_motion"` and `"25"`. Both prompts contain `"before the dialogue"` and neither contains `"speaks once close"`. The prompt holds `dialogue: exactly "It's just FuboTV." -- ` for k=2 (unchanged QL9) |
| WT4 | **Shots and no_stills speaking prompts are unchanged.** `dlg._story(ws, "shots", 3, plan_mut=dlg._speaking(2), replies={2: {"dialogue": dlg.LINE}})`: the panel-2 prompt contains `'without one, the pipeline adds the planned camera sentence.' + se.SPEAKING_ACTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"') + "\n"` and does not contain `"before the dialogue"`. The no_stills equivalent contains `"here; the pipeline adds them.\n"` from `SPEAKING_PROMPT_SENTENCE` and does not contain `"before the dialogue"` |
| WT5 | **The contract matches placement.** With the 2x145-f ctx, plan and parts, and `parts[1]["motion"] = GOOD2`: `dict(se.panel_fields(ctx, plan, parts, 2))["Motion"] == GOOD2 + " FuboTV hockey player faces the camera. The camera stays static."`. `lib.insert_speech(that, SAY2, [PHRASE], first_action=True)` equals `"The FuboTV hockey player snaps into a hard stop, throwing a big, bright spray of ice. FuboTV hockey player faces the camera. " + SAY2 + " The FuboTV hockey player skates away at real-time speed. The camera stays static."`. Variants, each through `insert_speech(..., first_action=True)` on the writer text plus `" FuboTV hockey player faces the camera. The camera stays static."`: (a) writer `"The camera holds on him. The FuboTV hockey player snaps into a hard hockey stop. He skates away at real-time speed."` gives `"The camera holds on him. The FuboTV hockey player snaps into a hard hockey stop. FuboTV hockey player faces the camera. " + SAY2 + " He skates away at real-time speed. The camera stays static."`; (b) writer `"The FuboTV hockey player snaps into a hard hockey stop. He skates away at real-time speed. The camera holds on him as he recedes."` gives `"The FuboTV hockey player snaps into a hard hockey stop. FuboTV hockey player faces the camera. " + SAY2 + " He skates away at real-time speed. The camera holds on him as he recedes. The camera stays static."`; (c) the one-sentence writer `"The FuboTV hockey player skates toward the camera at real-time speed."` gives that sentence, the facing sentence, `SAY2`, then `"The camera stays static."`; (d) `plain` delivery (`lib.speech_text(PHRASE, LINE2, "plain")`) in the main case gives the same order. In every case, `out.index(SAY2_or_plain) < out.index("skates away")` where the writer text contains "skates away" |
| WT6 | **The contract Motion passes the checks.** With WT5's parts, `text = se.assemble(ctx, plan, parts)` written to `tmp_path/"story.md"`: `se.panel_checks(ctx, plan, parts, text, path) == ([], ["panel 1: N7 dialogue and text: Motion: says 'speaks'"])`. Panel 2 therefore has no T2, N12 or N1 |
| WT7 | **The critic clause.** `MOTION = dlg.MOTION_LINE % ("motion", "Motion")`. `se.critic_field_lines("chained", None, "speech", True, speaking=True).split("\n")[0] == MOTION + se.CRITIC_SPEAKING_MOTION_CLAUSE`. For `mode` in `("shots", "no_stills")`, `se.critic_field_lines(mode, None, "speech", True, speaking=True) == se.critic_field_lines(mode, None, "speech", True)`. `se.critic_field_lines("chained", None, False, False, speaking=True) == se.critic_field_lines("chained", None, False)`. For every mode, `se.critic_field_lines(mode, None) == se.critic_field_lines(mode, None, True, False, False)`. `se.build_critic_prompt(plan, text, ([], []), narration="speech")` with the 2x145-f recorded plan and story.md contains `"\n" + MOTION + se.CRITIC_SPEAKING_MOTION_CLAUSE + "\n"`, and so does the same call with `for_judge=True`. For `dlg._story(ws, "chained", 3)`, which has no speaker, the prompt does not contain `se.CRITIC_SPEAKING_MOTION_CLAUSE` |
| WT8 | **Old stories compose unchanged.** For `name` in `("hockey-2x145-f", "hockey-1x241-f")`, parse `FIX/<name>/story.md`: for each `## Panel` section, the text after `"Motion: "` and after `"Dialogue: "`. For each panel k, with `phrase, line, _ = lib.parse_dialogue(dialogue, [PHRASE])`: `lib.insert_speech(motion, lib.speech_text(phrase, line, "beats"), [phrase], first_action=True) == json.load(FIX/<name>/manifest.json)["panels"][k-1]["motion_prompt"]`. This pins E2's recorded composition, line after the whole bundled sentence included |
| WT9 | **Old stories check unchanged.** For both names, with `ctx = _ctx(ws, name)` and `_recorded(name)`: `se.assemble(ctx, plan, parts)` equals `FIX/<name>/story.md` byte for byte. `se.panel_checks(...)` equals `([m["message"] for m in rec["hard"]], [m["message"] for m in rec["advisory"]])`, where `rec = json.load(FIX/<name>/story_checks.json)`; that is `([], [N7, N12, N1])` for 2x145-f and `([], [N12])` for 1x241-f. Then copy `plan.json` and `story.md` into `ctx.story_dir`: `rc, _adv = se.recheck(ctx, lambda path, panels, no_stills=False: [])` gives `rc == 0` |

### 4.2 Fixtures: `tests/fixtures/writer_pacing/`

These are verbatim copies, byte for byte, made at implementation time. `generated/` is gitignored (`.gitignore:2`).
- `hockey-2x145-f/plan.json` ← `generated/stories/hockey-2x145-f/plan.json`
- `hockey-2x145-f/parts.json` ← `generated/stories/hockey-2x145-f/story_rounds/round_0/parts.json`
- `hockey-2x145-f/story.md` ← `generated/stories/hockey-2x145-f/story.md`
- `hockey-2x145-f/story_checks.json` ← `generated/stories/hockey-2x145-f/story_checks.json`
- `hockey-2x145-f/manifest.json` ← `generated/stories/hockey-2x145-f/manifest.json`
- `hockey-1x241-f/`: the same five files from `generated/stories/hockey-1x241-f/`.

Hand-written:
- `hockey-2x145-f/case.json`: `{"story_id": "hockey-2x145-f", "panels": 2, "seconds": "6", "frames": 145, "goal": "a polished, realistic FuboTV hockey promo: on-camera lines delivered by the player, a hockey stop with ice spray, legible FuboTV branding"}`
- `hockey-1x241-f/case.json`: the same, with `"hockey-1x241-f"`, `1`, `"10"` and `241`.

The narrative is reused from `tests/fixtures/narrative_fidelity/narrative.txt`, which is byte-identical to the run's `.../scratchpad/hockey/narrative.txt`. It is not copied again.

### 4.3 Existing tests that change

**A. Must be updated, only for the stated reason:**

| Test | Reason and exact edit |
|---|---|
| `tests/test_story_engine.py::test_pacing_panel1_prompt_and_no_slowly` (`:2920-2936`) | WP1. The assertion at `:2923-2924` becomes `assert "The motion plays at real-time speed: use fast, concrete action verbs, with no words that slow it down, and end the main action with the words 'at real-time speed'." in prompt`. Nothing else changes; the band and no-"slowly" assertions hold |
| `tests/test_dialogue.py::test_dlg13_writer_keys_and_speaking_key_lines` (`:711`; chained assertion `:741-745`) | WP2, WP3. The expected string becomes `'already on screen. You may add one camera direction.' + se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"the courier"') + "\n"`. The shots assertion at `:763-764` is unchanged and must pass |
| `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (`:285`) | G5, in a separate test-only follow-up commit. `BASELINE` becomes the feature commit's SHA, and the comment line ending `(narrative dialogue fidelity).` becomes `... (narrative dialogue fidelity), then to <sha> (writer pacing).` |

**B. Re-run; edit only for an A reason:**
- `test_story_engine.py`: `::test_rst16_panel_prompt` (its asserted prefixes end before the inserted sentence), `::test_rst22_critic_prompt`, `::test_rs4_constants` and `::test_pacing_camera_sentences_classify_as_before`.
- `test_dialogue.py`: `::test_dlg19_critic_prompt` (it calls `critic_field_lines(mode, None)`, so `speaking` is False, and its story has no speaker), `::test_dlg15_assembly_goldens_and_dedupe`, `::test_dlg20`, `::test_dlg22` and `::test_dlg24`.
- `test_narrative_fidelity.py`: `::test_nf15`, `::test_nf20` (WP2 adds a constant and leaves `SPEAKING_ACTION_SENTENCE` and `SPEAKING_SENTENCES` unchanged), `::test_nf25` (its plan has a speaker, so the chained Motion line now ends with the clause; its assertions name only the dialogue and Q1 lines), and NF28-NF33.

**C. Must pass unchanged:**
- `test_rst40`, `test_rst41`, `test_rst61`, `test_rst62`;
- `test_shots_mode.py` (all tests);
- `test_casting_regression.py`;
- every manifest and placement test: DLG4, DLG7-DLG10, NF34, NF35, `test_review_focus_2`, `test_review_focus_3` and `test_ltx_story_manifest_chain.py::test_v2_golden_byte_identical`;
- `test_character_lib.py`;
- `test_ltx_movie_offline.py`.

---

## 5. Live check (WK7; post-merge, not a merge gate)

**Setup.**
- Let `S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`, `R=$S/hockey/pacing` (new, empty) and `W=/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`.
- `N` is `$(cat $S/hockey/narrative.txt)` and `G` is the goal string of `case.json`.
- The story model is the vllm-metal `qwen38-6bit` server on port 8177, started exactly as `start_llm` in `$S/hockey/rerun/run.sh`.

**Runs.** From `$W`, one after the other, with `bin/story-server stop` after each (as in `run.sh`):

```
bin/ltx-movie "$N" --panels 2 --frames 145 --story-id hockey-2x145-p --model ~/ltx-2-mlx/models/ltx-2.5-mlx-q8 --speech-only --judge --goal "$G" --no-review > $R/run-hockey-2x145-p.log 2>&1; echo "2x145 exit $?"
bin/ltx-movie "$N" --panels 1 --frames 241 --story-id hockey-1x241-p --model ~/ltx-2-mlx/models/ltx-2.5-mlx-q8 --speech-only --judge --goal "$G" --no-review > $R/run-hockey-1x241-p.log 2>&1; echo "1x241 exit $?"
```

**Transcripts.** Run this for each clip `C` in `generated/stories/hockey-2x145-p/clips/panel_01.mp4`, `.../hockey-2x145-p/clips/panel_02.mp4` and `.../hockey-1x241-p/clips/panel_01.mp4`, with output names `2x145_p1`, `2x145_p2` and `1x241`:

`$S/hockey/whisper-venv/bin/mlx_whisper C --model mlx-community/whisper-small-mlx --language en --word-timestamps True -f json -o $R --output-name <name>`

**Contact sheets.**
- 145-frame clips: `ffmpeg -v error -y -i C -vf "fps=4,scale=320:-1,tile=6x4" -frames:v 1 $R/sheet_<name>.jpg`.
- The 241-frame clip: the same with `tile=8x5`.
- Tile `n` (0-based, row-major) is at about `t = n / 4` seconds.

**Normalization.** `norm(s)` is `s.lower()` with every character outside `[a-z0-9]` removed. So `norm(LINE1) = "gettingthebestdealonhockeyisntahattrick"` and `norm(LINE2) = "itsjustfubotv"`, which matches whisper's "Fubo TV".

**Pass criteria (all must hold):**

| # | Criterion |
|---|---|
| a | Both runs exit 0. Both logs show Phase 1 completing with no `Error:` line. |
| b | Each top-level `story_checks.json` `hard` list has no `Q1` id. In `story.md`: 2x145 panel 1 `Dialogue:` ends `: ` + LINE1, 2x145 panel 2 ends `: ` + LINE2, and 1x241 panel 1 ends `: ` + LINE1 + `" "` + LINE2. |
| c | **2x145 panel 2 speech point.** The writer Motion has two or more action sentences: the story.md Motion, without its last two sentences (the pasted facing and camera sentences), split by `character_lib._SENTENCE_SPLIT_RE`, keeping each sentence for which neither `_is_camera_sentence(s, [phrase])` nor `is_facing_sentence(s, [phrase])` is true. The skate-away is in an action sentence after the first. In `manifest.json` `panels[1].motion_prompt`, the index of `'says, "It\'s just FuboTV."'` is less than the index of the skate-away sentence. |
| d | **Whisper hears both lines.** `norm(2x145_p1 text)` contains `norm(LINE1)`; `norm(2x145_p2 text)` contains `norm(LINE2)`; `norm(1x241 text)` contains `norm(LINE1)`, followed later by `norm(LINE2)`. |
| e | **The 2x145 panel 2 line precedes the skate-away in the clip.** Let `t1` be the start of whisper's first word of line 2 and `t2` the end of its last word. No tile at `t < t1` shows the player turned away from the camera and receding. The tile nearest `(t1 + t2) / 2` shows him facing the camera at medium-shot size or closer. |
| f | **The ice spray is visible.** At least one tile of `sheet_2x145_p2.jpg` and at least one tile of `sheet_1x241.jpg` shows a spray of ice particles clearly visible at sheet size. The references are `$S/hockey/ab/F_spray_145_sheet.jpg` at t=3.29 s and `$S/hockey/rerun/sheet_2x145_p02.jpg` tile 2. A spray only as faint as `$S/hockey/rerun/sheet_1x241.jpg` row 2, column 3 fails. |

**Recorded, not gating:**
- whether each story.md Motion contains "at real-time speed" and names the spray in its stop sentence;
- the judge scores;
- any words whisper hears beyond the two lines (R2).

Put the exit codes, the Dialogue lines, the panel-2 Motion and `motion_prompt`, the whisper JSONs and the four sheets in the PR or report.

If (c) fails because the writer bundled the actions again, record it and open the D3 (b) follow-up. If (e) fails while (c) holds, the defect is LTX timing, not the writer, and gets a separate investigation.

---

## 6. Rollout

1. Take a compressed snapshot of the workspace before any edit (house rule): `tar czf $S/snapshot-pre-writer-pacing-88213da.tgz` of `WS`, excluding `generated/`.
2. Copy the fixtures (4.2). Implement G1, G2 and G4 in one feature commit.
3. Run WK1-WK6 and the full suite.
4. Opus design review of the diff against this spec.
5. Make the test-only follow-up commit G5 (`test_mut26`), then measure WK1.
6. Post-merge: the live WK7 runs (Section 5). Record the results.

PR note (required, in substance): "Writer prompts only. Existing stories re-check and re-render exactly as before; a story regenerated with `--force-story` gets the new chained Motion instructions."

---

## 7. Values chosen by the spec

1. **The speech point.** The writer contract is one sentence before the dialogue and, only when the beat continues, one after it. The existing first-action placement is unchanged; there is no marker and no new writer key (D1).
2. **M3.** Chained speaking Motion gets `SPEAKING_CHAINED_MOTION_SENTENCE`. Shots keeps `SPEAKING_ACTION_SENTENCE`, because it allows one sentence and the line follows it (D2).
3. **No deterministic check and no clause splitting.** The plan-text check (D3 b) is the designated follow-up if WK7 (c) fails.
4. **The camera clash is not changed** (D4).
5. **Pacing.** One writer sentence: fast, concrete verbs; "at real-time speed" in the main action; named, big and bright effects in the same sentence; never a duration or size limit. It replaces the [PACE1] panel-1 sentence and is added to `chained_motion`. It is chained only and never pasted (D5).
6. **The critic.** On chained plans with a speaking beat, the Motion patch line gains the placement clause. Other prompts are byte-identical. judge-story inherits it (D6).
7. **Word bands and the plan prompt are unchanged.**

---

## 8. Risks and questions

### 8.1 Risks

- **R1. The writer may bundle anyway.** The contract is prompt text, and the qwen writer may still write one "then" sentence that spans the dialogue. There is no deterministic net by design (D3). N12 still reports it as advisory. WK7 (c) measures it, and D3 (b) is the follow-up.
- **R2. "at real-time speed" in every chained Motion.** LTX might voice unquoted prompt words; this was seen with descriptive speech variants on fubo_quaterback_promo (`character_lib.speech_sentence` docstring). Whisper's extra words are recorded in WK7.
- **R3. Word budget.** Effect words plus the 4-word phrase push some Motions past the advisory N1 band, as with E2's 46 words. The bands are not changed: N1 is advisory, and the contract Motion of WT5 fits (25 writer words).
- **R4. Pacing on calm narratives.** "Fast, concrete action verbs" may hurry a deliberately calm scene, such as a monk sitting. This is accepted because the pipeline targets action, and E1 shows under-generated motion as the default failure. The shared phrase also nudges N13 similarity up slightly.
- **R5. A multi-line beat speaks at one point.** The 1x241 narrative puts the stop between its two lines, while one Dialogue field is inserted once. Under the contract, the 1x241 writer may now put both lines after the approach and before the stop, where E2 put them after the stop. Both orders keep the lines before the skate-away, and WK7 (d) and (f) cover the result.
- **R6. The beat text may not state the speech point.** The contract relies on the beat action ordering the dialogue. It did in both E2 plans ("..., says the closing line, then skates away"; "..., speaks the promo lines, stops short ..."). LINES_RULE does not require it.
- **R7. Effect wording may over-generate.** "Big, bright" sprays may become particle clouds that hide the subject, as in F_spray_145 at t=3.29 s. WK7 (f) checks only visibility, and the user judges the look.

### 8.2 Decisions to confirm (the spec resolves each; flagged because each narrows or departs from the brief's wording)

- **C1.** The brief suggested "one action per sentence". The spec uses "one sentence on each side of the speech point" (D1), because first-action placement would put the line after the first of two pre-dialogue actions.
- **C2.** The [PACE1] panel-1 sentence "use plain action verbs with no adverbs of speed or manner" is replaced. Its ban on speed adverbs contradicts E1's "at full speed" and "real-time speed" findings. Its intent ("no words that slow it down") is kept, and the word "slowly" still appears nowhere (D5).
- **C3.** Pacing text is chained only; shots and no_stills are left alone for lack of evidence (D5).

### 8.3 Open

None.
