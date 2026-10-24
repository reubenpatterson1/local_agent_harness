# On-camera dialogue: Dialogue: field, beat-mapped speech in the LTX motion prompt

Date: 2026-10-24 (rev 2, after design review: approve-with-fixes)

Status: design spec for user decisions D1-D6 (Section 0.1). This is revision 2. It applies every fix from the design review and records the answers to Q1-Q4 (Section 14.2). One item, Q5, is still open. Section 11 (casting attachment, chained) is a **PROPOSAL pending user approval**. It is not part of the merge gate and must not be built until the user approves it. Every value the decisions left open is marked **[spec choice]**; Section 13 collects them. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`. Line numbers cite HEAD `289254d`, and each citation was checked in that tree.

Specs this one builds on, cited by tag:
- **[ROBUST]** `docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md` (RS1-RS37, critic, patches, round controller, 7.1 premises).
- **[SHOTS]** `docs/superpowers/specs/2026-10-06-shots-mode-design.md`.
- **[RULES2]** `docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md`.
- **[CAST]** `docs/superpowers/specs/2026-10-05-character-library-design.md`.

---

## 0. Purpose and scope

### 0.1 Purpose and binding decisions

LTX-2.x generates audio and video jointly. Today a spoken line lives in `Narration:` with a speaker prefix (`Narration: the courier: Keep moving.`). `bin/ltx-story-manifest` then inserts a flat sentence, `The courier says: "Keep moving."` (`character_lib.speech_sentence`, `:665-672`, via `insert_speech`, `:675-682`), before the camera sentence of the motion prompt. Two problems follow:
- The speech comes out flat and detached, like voice-over, and lip-sync is weak.
- The critic and several hard checks treat camera directions, descriptive text and dialogue as faults. They patch them away, and the code-only rewrite rounds strip them from the final story.md.

Binding user decisions:

- **D1.** Add an optional per-panel field `Dialogue: <speaker phrase>: <verbatim line>`. The writer fills it, and the manifest composes the quoted, beat-mapped speech into the motion prompt. The writer's Motion text stays free of quotes. A prefixed `Narration:` line stays as a back-compat input alias that maps to Dialogue. `Narration:` becomes voice-over only and may be empty whenever `Dialogue:` is present. Voice-over stays text only and is not rendered.
- **D2.** Beat-mapped delivery plus a fixed acoustic sentence is the default. The old `X says: "..."` form stays behind a flag for A/B testing. The beat text must be designed so LTX-2.3 does not repeat lines or voice unquoted words (`character_lib.py:666-669`).
- **D3.** A spoken line is at most 14 words and at most 3 fragments per panel. Going over the cap is a hard error, with a repair instruction to split the line across alternating close-up panels.
- **D4.** Any panel in any mode may speak. A speaking panel has a static or near-static camera, a medium close-up or close-up framing, a frontal face, and exactly one on-screen character: the speaker, who must be a declared cast member.
- **D5.** Camera language in `Motion:` is allowed and is never a violation.
- **D6.** Only these are hard (they block or trigger a rewrite):
  - (a) **timing**: the spoken words do not fit the clip;
  - (b) **amount of action**: too many or too few actions for the clip.

  Everything else is advisory: reported to the user and the logs, never rewritten or removed automatically. A structural rule stays hard only when the pipeline literally cannot proceed. The critic preserves camera directions, descriptive text and Dialogue word for word. There are at most 2 critic rounds. If a story still fails after round 2, the run proceeds with a warning unless the timing is grossly impossible. KPI: a story passes within 2 critic rounds with no human edits.

### 0.2 Grounding (verified at 289254d)

**`story_engine.py` (2595 lines, stdlib)**
- Constants: `SHOT_TYPES` `:30`; `SPEECH_SHOT_TYPES`/`SPEECH_SHOT_NOTE`/`SPEECH_FRAMING_SENTENCE` `:33-38`; `CAMERA_SENTENCES` `:43-52`; `NARRATION_WORDS` `:58`; `CRITIC_MAX_ROUNDS = 3` `:66`; `MIN_OK_SCORE = 7` `:69`.
- `StoryContext` `:82-85`. Its `narration` field is one of `True`, `"speech"` (`--speech-only`), `False` (`--no-narration`).
- Plan: `PLAN_PROMPT_TEMPLATE` `:270-306` (the beat rule "with no dialogue and no on-screen text" is at `:300`); `normalize_plan` `:626`; `pasted_pieces` `:724`; `plan_checks` `:771`; `lora_checks` (`L5 strength` at `:969`).
- Panel checks: `APPEARANCE_WORDS` `:1043-1053` (contains `camera lens zoom zooms dolly framing close-up`); `_CAMERA_TARGET_RE` `:1058`; `DIALOGUE_RE` `:1064-1068`.
- Writer: `KEY_LINE_TEMPLATES` `:1118-1178` ("Do not mention the camera" at `:1131` and `:1163`; "camera or lens" at `:1138`); `writer_keys` `:1181`; `clean_writer` `:1213`; `parse_panel_reply` `:1240`; `panel_fields` `:1262`.
- `_field_checks` `:1316-1491`: N7 `:1397-1403`, N11 `:1420`, N16/N17 `:1436-1475`.
- `GENERATION_CHECKS` `:1530`; `panel_checks` `:1534`; `build_panel_prompt` `:1567`.
- Critic: `CRITIC_PROMPT_TEMPLATE` `:1641-1678`; `critic_field_lines` `:1698`; `patch_ranges` `:1817`; `_patch_problem` `:1832`; `apply_patches` `:1855`; `WRITER_CHECK_IDS` `:1967`.
- Ranking: `_key` `:1992-1996`; `better` `:1999`; `_new_rs37` `:2004`; `best_round` `:2012-2018`; `_checks_doc` `:2021`.
- Controller: `_Run.regenerate` `:2149`; `critic_round` `:2189`; `judge_gate` `:2270`; `go` `:2308`.
- Re-check: `RECHECK_IDS` `:2430`; `PLAN_FREE_IDS` `:2432`; `story_fields` `:2450`; `plan_free_report` `:2480-2501` (returns the hard list only); `_undeclared_gate` `:2504-2515` (exits 2 on N15); `recheck` `:2517`. The no-plan shots path of `recheck` is at `:2581-2595`.

**`character_lib.py` (1204 lines; import set pinned by `tests/test_character_lib.py:540-550` and `test_s20`)**
- `DEFAULT_CHARACTER_STRENGTH = 0.8` `:40`; `SINGLE_CHARACTER_STRENGTH = 1.0` `:41`; `SHOTS_RULE_GUIDANCE` `:93-125`; `_CAMERA_TERM_RE` `:134`; `_STORY_FIELD_RE` `:167`.
- `SHOTS_REWRITE_TEMPLATE` `:208-218` is used only by the `--story-legacy` loop (`bin/ltx-movie:1755`).
- `_phrase_regex`/`phrase_occurs`/`cast_text` `:592-632`. `cast_text` inserts a trigger at every phrase occurrence, inside quotes too.
- `speaker_prefix`/`split_speaker` `:642-662`; `speech_sentence` `:665`; `insert_speech` `:675`; `panel_strengths` `:684-693`; `_is_camera_sentence` `:786`; `motion_problems` `:905`; `shots_violations` `:926` (S3 at `:953-955`).

**`bin/ltx-story-manifest` (816 lines)**
- `_PANEL_LABEL_RE` `:110`; `_read_catalog_loras` `:217`, which refuses a strength outside (0, 2] at `:209-211`; `_parse_prompts_md` `:290-362`; `_known_phrases` `:365`; `_spoken_narration` `:385`.
- Proportional-pace error `:631-641`; speech insertion `:710-713`; cast pass `:735-747` (`cast_text` at `:736`).

**`bin/ltx-mlx-render`:** refuses a catalog strength outside (0, 2] at `:302-304`.

**`bin/ltx-movie`**
- Legacy templates `:119-218`; `--no-narration`/`--speech-only` `:455-462`; `_validate_story_md` `:629`; `_story_context` `:1407-1434`; `_phase1_robust` `:1589`; `_phase1_shots_finish` `:1696` (legacy only); `phase3_manifest` `:1998`.
- Phase 3 passes `--pace equal` **only** with `--no-narration`/`--speech-only` (`:2015`). The default is proportional pace, with min-frames = max-frames = `--frames` (`:2011-2014`).
- Dry-run lines `:2193`, `:2207`.

**Judges**
- `bin/judge-story`: `DEFAULT_GOAL` `:81`; `PATCH_FIELDS` `:146`.
- `bin/judge-clips`: `:149-151`; `format_panel_text` `:361-374`.
- `bin/judge-stills`: `PANEL_LABEL_RE` `:66` is a verbatim copy of the manifest regex.

**Renderer harness (`~/ltx-2-mlx`)**
- Always `--distilled` (`ltx2_mlx_video_skill.py:236,257`). Geometry is checked: width and height are multiples of 64 and frame counts are 8k+1 (`:181-192`). No CFG or modality knob is reachable.
- The Gemma text encoder tokenizes at `TOKENIZER_MAX_LENGTH = 1024` (`packages/ltx-core-mlx/src/ltx_core_mlx/text_encoders/gemma/encoders/gemma4_encoder.py:65`; `base_encoder.py:49`, default 1024). The pipeline calls `prompt_encoder.encode(prompt)` with that default (`ltx_pipelines_mlx/_base.py:579`).
- The longest composed prompt is about 280 words (no_stills: 220 words plus about 60 words of speech, acoustic and facing text). That is roughly 380 tokens, well under 1024. The manifest's "(>150 words); T5 may truncate at 256 tokens" warning (`:397-399`) is stale T5-era text. It is out of scope but listed as risk R9.

**Recorded data.** No `story_rounds/` directory exists in either harness tree. `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/` holds 62 legacy `story.md` files with no plans and no spoken lines. They are used only as calibration evidence (Section 10.4).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `character_lib.py` | dialogue constants and helpers (DG1-DG6); widened `_is_camera_sentence` (CM1); `insert_speech`/`motion_problems` take `phrases`; `cast_text` takes `skip_quoted`; S3 accepts Dialogue; `_STORY_FIELD_RE` gains `Dialogue` |
| G2 | `bin/ltx-story-manifest` | `Dialogue:` label and parsing, cap error, composition, `--speech-delivery`, pace weights, `speech_source` |
| G3 | `story_engine.py` | plan `speaker` and coercion (SP); dialogue writer key; assembly; camera changes (CM); T1/T2/T3/N18; the D6 reclassification, ranking, controller and patch whitelist (Section 6); prompt text (Section 8) |
| G4 | `bin/ltx-movie` | `--speech-delivery`; `_validate_story_md` accepts Dialogue; `clip_seconds`; dry-run, help and docstring text |
| G5 | `bin/judge-story` | `DEFAULT_GOAL`; `PATCH_FIELDS` gains `"dialogue"` |
| G6 | `bin/judge-clips` | Dialogue rule sentence; `format_panel_text` |
| G7 | `bin/judge-stills` | `PANEL_LABEL_RE` and field dict gain `Dialogue` (stays a verbatim copy) |
| G8 | `tests/test_dialogue.py` (new) | DLG1-DLG34, DLG-H, DLG-K1 (Section 9.1) |
| G9 | existing tests | the edits of Section 9.2 only |
| G10 | `tests/test_movie_ui_builder.py::test_mut26` | `BASELINE` re-baseline, in a **separate test-only follow-up commit** after G1-G9 land |

**Cut from this spec:** the movie-ui `speech_delivery` Compose field. A/B testing is done from the CLI only. No change is made to `movie_ui_lib.py`, `static/movie-ui/*`, the movie-ui help fixtures or `test_movie_ui_builder.py:118-131`.

**Not changed:** the legacy templates and the legacy Phase 1 path, including `_phase1_shots_finish` and `SHOTS_REWRITE_TEMPLATE` (Q2 resolution: the legacy shots loop **stays strict**); `ltx2_mlx_video_skill.py`; `bin/ltx-mlx-render`; `bin/ltx-story-images`; `lora_catalog.py`; `bin/qwen-agent`; `fleet_lib.py`; `movie_ui_lib.py`.

### 0.4 Out of scope

- CFG, modality or audio-guidance settings (not reachable: always `--distilled`; geometry already compliant).
- Voicing narration.
- Automatic panel restructuring.
- Writer-supplied beats, comma splitting, `/` or `|` separators.
- The legacy engine's checks and shots rewrite loop.
- Multi-speaker panels and off-screen speakers.
- The stale manifest T5 warning (R9).
- Section 11 until it is approved.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| DK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the pass count recorded just before implementation, plus every DLG test, plus the Section 9.2 edits, with no lost pass. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Measured **after** the G10 follow-up commit. | full run |
| DK2 | `/usr/bin/python3` (3.9) and `python3` both `py_compile` every changed file. | `test_rst61` |
| DK3 | Import sets are unchanged (`test_rst62`, `test_character_lib.py:540-550`, `test_s20`). | those tests |
| DK4 | **Merge gate (D6 invariants, offline).** DLG21-DLG24 and DLG-H pass. DLG-H runs 6 hand-written cases (3 modes × speaking/non-speaking) containing camera directions, descriptive sentences and, when speaking, Dialogue. Each case asserts 0 blocking violations at round 0, stop `passed`, no critic call, and every authored sentence and the Dialogue line byte-identical in the output story.md. | DLG21-DLG24, DLG-H |
| DK5 | Legacy outputs stay byte-identical: the `--story-legacy` Phase 1 prompt and argv (`test_rst40`); the `--story-legacy` dry run golden `tests/fixtures/casting_baseline/ltx_movie_dry_run.txt` (produced with `--story-legacy`, `tests/test_casting_regression.py:46-54`; `test_rst41`, `test_s52`); the v2 manifest golden (`test_ltx_story_manifest_chain.py::test_v2_golden_byte_identical`); plain delivery for an alias panel whose spoken words contain no cast phrase (DLG8). The **default (robust)** dry run is not golden-pinned; its changed lines are pinned by `test_rst47` (Section 9.2). | those tests |
| DK6 | **Post-merge calibration fixture (not a merge gate).** DLG-K1 replays the recorded 24-case corpus (Section 10.1) with a null critic. The target is at least 22 of 24 with 0 blocking violations. A miss is reported, not blocking; it feeds Section 10.2's rollback rule. | DLG-K1 |
| DK7 | **The real KPI (live, Section 10.2).** At least 14 of 16 runs exit 0 with no hand edit, within 2 critic rounds. **Rollback rule:** a miss reopens the T-rule constants (`ACTION_SECONDS`, `NO_STILLS_BEAT_SECONDS`, the cap formula, the T2/T3 thresholds) for a user decision, using DLG-K1 to calibrate. The feature does not ship as "done" until DK7 passes. | live protocol |

### 0.6 Must-have and nice-to-have

Sections 2-8 are must-haves. Section 11 is a proposal, built only on approval. Nothing else is built.

---

## 1. Architecture

### 1.1 A spoken line end to end

```
plan                      beat.speaker = "c2"  -> normalize_plan coerces cast/shot/camera (SP2)
panel writer              "dialogue": "You came far. Rest here."   (no quotes, no speaker)
assembly (story.md)       Motion: <writer>. The old monk faces the camera. The camera stays static.
                          Dialogue: the old monk: You came far. Rest here.
checks                    T1 hard+blocking; T2/T3 hard, repaired, never blocking; structural hard;
                          everything else advisory (Section 6)
critic (<= 2 rounds)      motion/prompt patches (PG3 guard) and dialogue patches only, on T panels
bin/ltx-story-manifest    parses Dialogue:, enforces the cap, composes beats + acoustic sentence,
                          inserts before the trailing camera run, then cast triggers (never in quotes)
LTX                       motion_prompt
```

### 1.2 Ownership

- `character_lib.py` owns the Dialogue grammar, fragments, cap, delivery templates and camera-sentence classifier. The engine and the manifest share them, so they cannot disagree.
- `story_engine.py` owns plan coercion, pasted sentences, writer prompts and every check classification.
- The manifest owns composition. story.md holds only the verbatim line. **[spec choice: delivery is a render-time A/B switch.]**

---

## 2. Data shapes (normative)

### 2.1 story.md panel fields, in file order

`Image:` (where the mode has it), `Motion:` or `Prompt:`, `Dialogue:` (optional), `Narration:` (optional per SP4). `Dialogue:` follows the same rules as the other labels: case-sensitive at the start of a line, and unlabeled continuation lines are joined with a space.

### 2.2 Plan

Each beat gains `"speaker"`: a cast id or `""`. The plan gains `"speech_notes"`: a list of advisory strings, `[]` when there are none. Both are written to plan.json. `_PLAN_KEYS` is unchanged. `load_plan` defaults a missing `speaker` to `""` and missing `speech_notes` to `[]`.

### 2.3 Writer parts

Gains `"dialogue"` when the beat speaks and `ctx.narration is not False`. parts.json keys come from `panel_keys` (SP5).

### 2.4 `StoryContext`

Gains a last field, `clip_seconds`; `defaults=(True, None)`. `engine_seconds(ctx)` returns `ctx.clip_seconds if ctx.clip_seconds is not None else float(ctx.seconds)`. `bin/ltx-movie._story_context` passes `clip_seconds=args.frames / float(args.fps)`.

### 2.5 Manifest panel keys

A panel with a spoken line has `"speaker"`, `"speech"` (as today) and the new `"speech_source"`: `"dialogue"` or `"narration"`. A panel without speech has none of the three, so the v2 golden and the C7 key sets are unchanged. For a Dialogue panel, `"narration"` is the Narration text and may be `""`. For an alias panel it is the raw prefixed narration, as today. `narration_words` is unchanged.

### 2.6 `story_checks.json`

The schema id stays `ltx-movie.story-checks.v1` and gains `"unresolved"`.
- Final file (from a run or a re-check): `"hard"` holds the **blocking** violations only; `"unresolved"` holds the remaining non-blocking hard violations (T2, T3).
- Per-round files: `"hard"` holds every hard violation; `"unresolved"` is `[]`.
- `_checks_doc` writes `"unresolved": []` by default.

---

## 3. Dialogue requirements (DG)

### DG1. Constants (`character_lib.py`, after `insert_speech`)

```python
DIALOGUE_MAX_WORDS = 14
DIALOGUE_MAX_FRAGMENTS = 3
DIALOGUE_WORDS_PER_SECOND = 2.4
DIALOGUE_BEAT_SECONDS = 0.4          # clip time each beat between fragments consumes
SPEECH_DELIVERIES = ("beats", "plain", "beats-no-acoustic")
DEFAULT_SPEECH_DELIVERY = "beats"
SPEECH_BEATS = ("After a breath", "After a short pause")   # before fragment 2, before fragment 3
ACOUSTIC_SENTENCE = ("The audio is clear close-mic dialogue with a subtle natural room tone; "
                     "the dialogue takes priority over the quiet ambience.")
```

### DG2. `dialogue_word_cap(seconds, fragments=1)`

Returns `min(DIALOGUE_MAX_WORDS, int(DIALOGUE_WORDS_PER_SECOND * (seconds - DIALOGUE_BEAT_SECONDS * (fragments - 1)) + 1e-9))`.

Values at 145/24 fps (6.04 s): 14, 13 and 12 for 1, 2 and 3 fragments. At 121/24: 12, 11, 10. At 97/24: 9, 8, 7. At 241/24: 14, 14, 14.

**[spec choice: 2.4 words per second is slightly under conversational pace and gives exactly D3's 14 at the default clip (2.4 × 6.04 = 14.5, which truncates to 14). Each beat between fragments uses about 0.4 s of the clip, so each extra fragment lowers the cap by about one word at the default length. The cap shrinks for shorter clips and never exceeds D3's 14.]** The `1e-9` only guards against a float product that lands just below an integer. It changes none of the values above.

### DG3. `parse_dialogue(value, phrases) -> (phrase, line, problem)`

1. Collapse whitespace in `value` and strip it. If the result is `""`, return `(None, "", None)`: the Dialogue is absent.
2. Sort the candidates with `sorted(phrases, key=lambda p: (-len(p.split()), -len(p), p.lower()))`. The first phrase whose regex matches the text case-insensitively wins: `^\s*` + the phrase's words (`re.escape`d, joined by `\s+`) + `\s*:\s*`. The returned `phrase` is the phrase exactly as given.
3. If no phrase matches:
   - When `speaker_prefix(text)` finds a prefix `p`, return `(None, "", "names %r, which is no character's referring phrase; use one of: %s" % (p, known))`. `known` is `", ".join(repr(x) for x in phrases)`, or `"none (no --cast, no ## Characters section and no plan.json cast)"` when there are no phrases.
   - Otherwise return `(None, "", "has no speaker; write it as <referring phrase>: <the spoken words>")`.
4. `line` is the text after the matched prefix and colon, stripped. Remove one surrounding pair of `"..."` or `“...”` and strip again. Replace every remaining `"`, `“` or `”` with `'`. Collapse whitespace.
5. If `line == ""`, return `(None, "", "has a speaker but no words")`.
6. If `line` does not end in `.`, `!` or `?`, append `.`. Return `(phrase, line, None)`.

**[spec choice: matching the known phrases accepts library phrases longer than `MAX_PHRASE_WORDS` and characters outside `_SPEAKER_PREFIX_RE`'s character class.]**

### DG4. `split_fragments(line)`

`[s.strip() for s in _SENTENCE_SPLIT_RE.split(line.strip()) if s.strip()]`. The word count is `len(line.split())`.

**[spec choice: the manifest splits at sentence ends and the writer marks nothing. Reasons: there is no new syntax for a 27B writer to get wrong, and a `/` could be voiced; old alias lines split the same way; a sentence end is a natural pause, so a beat placed there does not cut a phrase; one deterministic function serves both the check and the renderer. Comma splitting would cut clauses inside one breath.]**

**[spec choice: the beats are fixed text. A model-written beat is exactly the "descriptive variant" that macstudio saw LTX voice.]**

### DG5. Composition: `speech_text(phrase, line, delivery)`

```python
f = split_fragments(line)
if len(f) > DIALOGUE_MAX_FRAGMENTS:
    f = f[:DIALOGUE_MAX_FRAGMENTS - 1] + [" ".join(f[DIALOGUE_MAX_FRAGMENTS - 1:])]
if delivery == "plain":
    return speech_sentence(phrase, line)                 # unchanged: P says: "<line>"
P = phrase[:1].upper() + phrase[1:]
s = P + ' says, "' + f[0] + '"'
for i in range(1, len(f)):
    s += ' ' + SPEECH_BEATS[i - 1] + ', "' + f[i] + '"'
return s if delivery == "beats-no-acoustic" else s + ' ' + ACOUSTIC_SENTENCE
```

The fragment cap inside `speech_text` makes the function safe for any input. An over-cap alias line therefore never raises an `IndexError`.

Mitigations against repeated or voiced words (D2):
- (a) Each fragment appears exactly once, inside straight double quotes.
- (b) The only unquoted words between fragments are a 2-4 word stillness phrase ("After a breath", "After a short pause"). There is no "continues" (a speech verb that could invite LTX to keep talking), no second subject, and no speaking adverb or lip or mouth word, the vocabulary of the rejected `fubo_quaterback_promo` variants.
- (c) The speaker phrase occurs once, so `cast_text` inserts at most one trigger in the speech sentence.
- (d) The acoustic sentence describes the recording, comes after the last quote and never sits between fragments.
- (e) `plain` and `beats-no-acoustic` are one flag away for A/B (Section 10.3).

### DG6. Placement and triggers

- `insert_speech(text, sentence, phrases=())`. Let `r` be the number of trailing sentences `s` with `_is_camera_sentence(s, phrases)`. If `len(sentences) > 1` and `r >= 1`, insert at index `max(len(sentences) - r, 1)`. Otherwise append, as today.
- The manifest calls `insert_speech(motion_prompt, speech_text(speaker, speech, args.speech_delivery), [speaker])`. With the speaker's phrase supplied, the facing sentence is not mistaken for a camera sentence.
- `cast_text(text, members, insert=None, skip_quoted=False)`. With `skip_quoted`, a match whose span lies entirely inside a `"[^"]*"` span is ignored: it is neither triggered nor reported. The manifest's cast pass (`:736`) passes `skip_quoted=True`. **[spec choice: a trigger inside quotes would be voiced. This changes plain output only when the spoken words contain a cast phrase.]**

### DG7. Manifest (`bin/ltx-story-manifest`)

1. `_PANEL_LABEL_RE = r"^(Image|Motion|Narration|Prompt|Style|Dialogue):\s*(.*)$"`. `_parse_prompts_md` adds a `"Dialogue"` list and sets `p["dialogue"] = " ".join(fields["Dialogue"])`. Add one docstring sentence describing it.
2. Add `--speech-delivery {beats,plain,beats-no-acoustic}` with `default="beats"` and help: `"how a Dialogue: line (or a spoken Narration: line) is written into motion_prompt: beats (default) splits it at sentence ends with short fixed beats and adds a fixed close-mic audio sentence; beats-no-acoustic omits that sentence; plain is '<Speaker> says: \"<line>\"'"`.
3. `character_lib` is loaded when `--cast` is given, or any Narration contains a colon, or any `dialogue` is non-empty.
4. `_spoken_narration` is replaced by `_spoken(args, prompt_texts, members)`, which returns `(speaker, speech, source)` per panel:
   - A non-empty `pt["dialogue"]` is parsed with `parse_dialogue(pt["dialogue"], _known_phrases(args, members))`. A problem prints `Error: panel %d: Dialogue: %s` to stderr and returns 2. Otherwise the result is `(phrase, line, "dialogue")`, and that panel's Narration is voice-over: its prefix is not parsed.
   - Else, if `":"` is in the narration, use `split_speaker` as today: a speaker gives `(speaker, speech, "narration")`, otherwise `(None, narration, None)`.
   - Else `(None, narration, None)`.
5. Proportional pace (`:631-641`):
   - Fail only when the narration is empty **and** `source != "dialogue"`, with the message `"Error: --pace proportional requires every panel to have a non-empty Narration or Dialogue field; panel %d has neither"`.
   - The weight is `len(speech.split())` when there is a speaker, else `len(narration.split())`, minimum 1.
6. Cap check, after frame allocation, for each panel with a speaker. Let `n = len(split_fragments(speech))`, `cap = dialogue_word_cap(frame_counts[i-1] / float(args.fps), n)` and `words = len(speech.split())`. If `words > cap` or `n > DIALOGUE_MAX_FRAGMENTS`:
   - For source `"dialogue"`, print to stderr `Error: panel %d: Dialogue: is %d words in %d sentences; a %.2f-second clip fits at most %d words in %d sentences, and a line has at most 3 sentences; shorten the line, or split it across alternating close-up panels (the speaker, then the listener, then the speaker again)` and return 2.
   - For source `"narration"`, print the same text to stdout, with `WARNING: panel %d: the spoken Narration: is` in place of `Error: panel %d: Dialogue: is`, and continue (D1: old files render).
7. Composition (`:710-713`): `motion_prompt = lib.insert_speech(motion_prompt, lib.speech_text(speaker, speech, args.speech_delivery), [speaker])`. The panel gets `speaker`, `speech` and `speech_source`.

### DG8. `bin/ltx-movie`

- Add `--speech-delivery` (`dest="speech_delivery"`, choices as in DG1, `default="beats"`, help `"how spoken lines reach the video model (bin/ltx-story-manifest --speech-delivery): beats (default), beats-no-acoustic, or plain, the earlier '<Speaker> says: \"...\"' form, for A/B comparison"`), placed right after `--speech-only`.
- In `phase3_manifest` and in the dry-run manifest command, right after the `--pace equal` block: `if getattr(args, "speech_delivery", "beats") != "beats": cmd += ["--speech-delivery", args.speech_delivery]`.
- The flag is allowed with `--story-legacy`, because it affects Phase 3 only.

### DG9. Worked examples (normative goldens for DLG7)

Setup for all three examples:
- Cast: c1 "the courier" (a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers); c2 "the old monk" (an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals).
- Clips are 145 frames at 24 fps; no `--cast`.
- `<AC>` stands for `ACOUSTIC_SENTENCE`.

**Chained, panel 2 speaks.** Beat 2's speaker is `c2`, and the cast is coerced to `[c2]`. Narration is empty, so there is no Narration line. The line is 10 words in 2 fragments; the cap is 13.

```
## Panel 2 — At the Gate
Motion: The old monk lowers his broom and lifts his eyes. The old monk faces the camera. The camera stays static.
Dialogue: the old monk: You came far. Rest here before the abbot sees you.
```

beats:
```
The old monk lowers his broom and lifts his eyes. The old monk faces the camera. The old monk says, "You came far." After a breath, "Rest here before the abbot sees you." <AC> The camera stays static.
```

plain:
```
The old monk lowers his broom and lifts his eyes. The old monk faces the camera. The old monk says: "You came far. Rest here before the abbot sees you." The camera stays static.
```

**Shots, panel 3, one fragment.** The shot is coerced to medium close-up and the camera is static.

```
## Panel 3 — The Letter
Image: The setting is a hilltop temple gate in modern Japan, worn stone steps underfoot, cedar trees behind, under low golden evening light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier stands at the gate holding the sealed letter at chest height. The courier faces the camera. The shot is a medium close-up.
Motion: The courier raises the sealed letter toward the gate. The courier faces the camera. The camera stays static.
Dialogue: the courier: I carry a letter for the abbot.
Narration: The bell had not yet rung.
```

beats:
```
The courier raises the sealed letter toward the gate. The courier faces the camera. The courier says, "I carry a letter for the abbot." <AC> The camera stays static.
```

**No-stills, panel 4, three fragments.** The line is 10 words; the cap is 12. `<SETTING>` is l2's setting sentence.

```
## Panel 4 — Shelter
Prompt: The old monk sets down his broom as rain drips from the eaves. The old monk is an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals. <SETTING> The shot is a close-up. The old monk faces the camera. The camera stays static.
Dialogue: the old monk: Come in. Sit by the fire. He will see you.
Narration: Inside, the fire was already lit.
```

beats:
```
... The old monk faces the camera. The old monk says, "Come in." After a breath, "Sit by the fire." After a short pause, "He will see you." <AC> The camera stays static.
```

**Over the cap.** `Dialogue: the courier: I carry a sealed letter from the harbour master for the abbot of this temple.` is 16 words. The engine reports T1 (blocking); the manifest exits 2 with the message in DG7 step 6.

**Alias.** `Narration: the courier: Keep moving.` with no Dialogue gives `speech_source: "narration"`. With beats it produces `The courier says, "Keep moving." <AC>`. With plain it produces today's bytes.

---

## 4. Speaking panels (SP, D4)

### SP1. Plan prompt

Section 8.1.

### SP2. Coercion in `normalize_plan`

Coercion runs after the beats and the cast are built. It never causes a retry or a rewrite. **[spec choice: D4's hard framing rules are enforced deterministically.]**

Set `raw = _clean_str(item.get("speaker"))`. Every beat gets a `"speaker"` key. Let `cast_ids` be the ids in `plan["cast"]`, and `shot_applies(k) = ctx.mode != "chained" or k == 1`.

1. If `ctx.narration is False`, the speaker is `""`. If `raw` was non-empty, note `"beat %d: P14 speaking beat: speaker %s dropped: this movie has no spoken lines" % (k, _q(raw))`.
2. If `raw == ""`, the speaker is `""`.
3. If `raw` is not in `cast_ids`, the speaker is `""`. Note `"beat %d: P14 speaking beat: speaker %s is not a cast id, so nobody speaks in this beat"`.
4. Otherwise the speaker is `raw`, and:
   - If `beat["cast"] != [raw]`, note `"beat %d: P14 speaking beat: cast [%s] changed to [%s] so the speaker is alone on screen" % (k, ", ".join(cast), raw)` and set `cast = [raw]`.
   - If `shot_applies(k)` and the shot is not `"medium close-up"` or `"close-up"`, change it to `"close-up"` if it was `"extreme close-up"`, else to `"medium close-up"`. Note `"beat %d: P14 speaking beat: shot %s changed to %s so the speaker's face stays readable"`.
   - If `shot_applies(k)` and the camera is not `"static"` or `"slow push-in"`, change it to `"static"`. Note `"beat %d: P14 speaking beat: camera %s changed to 'static' so the speaker's face stays readable"`.
5. Chained mode only: if any beat `k >= 2` speaks, beat 1's shot and camera are coerced the same way. The note ends `"... because beat %d speaks later in this continuous take"` instead of `"... so the speaker's face stays readable"`, where `%d` is the first such beat. **(Q5 is open: whether to keep this.)**

The notes are stored, in order, in `plan["speech_notes"]`. `plan_checks` appends them to the advisory list after the P13 advisories.

**Side effects of the cast coercion in step 4, documented and accepted:**
- (i) The removed members' identity sentences are not pasted into that panel.
- (ii) With today's text-based attachment, a removed member's character LoRA is not attached to that panel unless the writer names them (Section 11 proposes plan-based attachment).
- (iii) If the writer names a removed member anyway, N4 stray cast is advisory.
- (iv) In chained mode a removed member is still physically present in the continued frame. The speaking shot depends on the camera framing, not on that member leaving.
- (v) plan.json stores the coerced values, so the critic, re-check and manifest see the coerced plan.

### SP3. "Declared cast member"

This means a plan cast id in the engine, or a phrase in `_known_phrases` in the manifest. An undeclared speaker phrase is N18 (structural).

### SP4. Pasted sentences and assembly

- `FACING_SENTENCE = "%s faces the camera."`, filled with the capitalised phrase.
- `SPEAKING_CAMERA = "The camera stays static."`
- A panel **speaks** when `beat["speaker"]` is non-empty and `ctx.narration is not False`.

`pasted_pieces` and `panel_fields` produce the fields below. `[x]` is present only when the panel speaks. `{cam}` is the beat's camera sentence; on a non-speaking panel it is dropped from the **assembled** field by CM4's dedupe.

| Mode / panel | Field and order |
|---|---|
| chained k=1, shots | `Image:` = setting, identities, writer image, [facing], shot. `Motion:` = writer motion, [facing], {cam} |
| chained k>=2 | `Motion:` = writer motion, [facing, SPEAKING_CAMERA] |
| no_stills | `Prompt:` = writer prompt, identities, setting, shot, [facing], {cam} |
| all | `Dialogue:` = `phrase + ": " + dialogue part` (DG3 steps 4 and 6 applied), present when the panel speaks |
| all | `Narration:` is present when `ctx.narration is True` and either the narration part is non-empty or the panel does not speak |

`pasted_pieces` **always** returns every planned pasted sentence: facing, SPEAKING_CAMERA, and the planned `{cam}` even when CM4 drops it from assembly. As a result, `clean_writer` still blanks a copied planned camera sentence, and `writer_targets`/P10 budgets count it.

`panel_fields` and `story_fields` emit `("Dialogue", text)`. `story_fields` (`:2450`) appends `("Dialogue", panel["dialogue"])` when it is non-empty, before Narration, in every mode and for every `narration` value.

### SP5. Writer keys

`writer_keys(mode, k, narration=True, speaks=False)` returns, in order:
- `title`;
- `image` (chained k=1 and shots);
- `motion` or `prompt`;
- `dialogue`, when `speaks` and `narration is not False`;
- `narration`, when `narration is True`.

**[spec choice: `--speech-only` no longer has a narration key.]**

`panel_keys(ctx, plan, k) = writer_keys(ctx.mode, k, ctx.narration, speaks=bool(plan["beats"][k-1]["speaker"]))` is used at every call site that has a plan: `parse_panel_reply`, `panel_checks`, `build_panel_prompt`, `make_state` (for parts.json) and `unparseable_panel_problem` (which gains `speaks=False`).

`parse_panel_reply`:
- Every non-title key must be non-empty, except `narration` on a speaking panel.
- `dialogue` is cleaned with `clean_writer`, then the DG3 step 4 quote replacement is applied, then a leading `<speaker phrase>:` is stripped (case-insensitive).

---

## 5. Camera language (CM, D5)

### CM1. `_is_camera_sentence(sentence, phrases=())`

The sentence is a camera sentence when any of these holds:
- (a) the existing start rule matches;
- (b) the existing short rule matches: at most 4 words and `_CAMERA_TERM_RE`, which still catches "Slow pan left." and "Zooms in.";
- (c) **new:** `_CAMERA_WIDE_TERM_RE` matches and the sentence refers to no person.

```python
_CAMERA_WIDE_TERM_RE = re.compile(r"\b(?:cameras?|lens|dolly|dollies|push-in|pull-back|"
                                  r"extreme close-up|medium close-up|close-up|wide shot|medium shot|"
                                  r"tracking shot|handheld|locked-off|framing)\b", re.IGNORECASE)
_PRONOUN_RE = re.compile(r"\b(?:he|she|they|him|her|them|his|hers|their|theirs|himself|herself|"
                         r"themselves)\b", re.IGNORECASE)
```

**[spec choice: no zoom, pan or tilt verb forms. "The waves pan out across the bay" and "the mast tilts" are action sentences.]**

A sentence refers to a person when any of these holds:
- `phrase_occurs(sentence, p)` for some `p` in `phrases` (a `CharacterError` is skipped);
- a `_WORD_RE` word, lowercased and with any possessive removed, is in `SHOTS_PERSON_NOUNS | SHOTS_ANIMAL_NOUNS`;
- `_PRONOUN_RE` matches.

`motion_problems(motion, phrases=())` passes `phrases` through. `shots_violations` passes `humans + animals` to `motion_problems` and to the S8 camera filter.

### CM2. N3

Remove `camera lens zoom zooms dolly framing close-up` from `APPEARANCE_WORDS`. Delete `_CAMERA_TARGET_RE` and its use, which are now unused. N3's message tail becomes `"...re-describe appearance, clothing, setting, lighting, colour or style"`. **[spec choice: N3 reads only chained k>=2 Motion, so removing the words is the same as exempting Motion.]**

### CM3. Writer instructions

Section 8.2. "Do not mention the camera" and "camera or lens" are deleted. The no_stills "do not name ... the camera motion" is softened.

### CM4. Dedupe

On a non-speaking panel, `{cam}` is left out of the **assembled** field when the writer text has a sentence `s` that satisfies both `_is_camera_sentence(s, plan cast phrases)` and `CAMERA_MOTION_RE.search(s)`:

```python
CAMERA_MOTION_RE = re.compile(r"\b(?:static|still|holds?|locked-off|push(?:es)?\s+in|push-in|"
                              r"pull(?:s)?\s+back|pull-back|pans?|tilts?|tracks?|tracking|dolly|"
                              r"dollies|zooms?|orbits?|cranes?|handheld|follows?)\b", re.IGNORECASE)
```

Speaking panels always keep their pasted camera sentence.

### CM5. Critic, plan and judges

- The plan beat rule and the critic renderability text drop "no dialogue" (Sections 8.1 and 8.3).
- `bin/judge-story`: `DEFAULT_GOAL = "the most realistic action scenes possible, with any spoken lines delivered on camera by the character who says them"`.
- `bin/judge-clips` `:149-151`: the sentence becomes `A Dialogue: text is a line the named character speaks on camera in that panel's clip; Narration: text is voice-over.`
- `format_panel_text`:
  - After `Motion:`, emit `"Dialogue: %s: %s" % (speaker, speech)` when both are non-empty.
  - Emit `Narration:` only when it is non-empty and `panel.get("speech_source", "narration" if panel.get("speaker") else None) != "narration"`.
- `bin/judge-stills` `PANEL_LABEL_RE` becomes the DG7 regex, and its field dict gains `"Dialogue": []`.

### CM6. Legacy

The `--story-legacy` templates, including "camera or lens" and "write no spoken dialogue", are unchanged. They are pinned by [ROBUST] RSK5, `test_rst40`, `test_rst41`, `test_s52`, L5 and L15.

The `--story-legacy` help gains this sentence: `"It does not ask for Dialogue: lines; a prefixed Narration: line still renders as dialogue."`

### CM7. Quote-free Motion

Once N7 is advisory (D6), nothing enforces a quote-free Motion: it rests on the writer instructions (Section 8.2: "do not write the spoken words or a speaking verb here"). This is accepted under D6. The consequence (quoted Motion words could be voiced, uncapped) is risk R10.

---

## 6. Less restrictive checks and repair (D6)

### 6.1 Classes

| Class | Effect |
|---|---|
| hard-timing (T1) | triggers repair; **blocking** after the rounds. It is the only "grossly impossible" class. |
| hard-action (T2, T3) | triggers repair; **never blocking**: an unresolved T2/T3 proceeds with a warning |
| hard-structural | blocking. Fixed only by plan retries (P1-P3, L1/L5-hard/L6/L7) or code-only rounds (N11). |
| advisory | `Warning:` lines and `story_checks.json` `advisory`; shown to the critic as `[advisory]`; never patched, rewritten or removed |

`NON_BLOCKING_IDS = ("T2", "T3")`. `n_blocking(state)` counts the hard messages whose `parse_violation(m)["id"]` is not in `NON_BLOCKING_IDS`.

### 6.2 Timing and action rules (new)

`secs = engine_seconds(ctx)`. `S` is `ctx.seconds` (for example `"6"`).

**T1 spoken timing (hard-timing, blocking).** Applies to a panel whose `Dialogue:` parses to `(phrase, line, None)`. Let `w = len(line.split())`, `n = len(split_fragments(line))` and `cap = dialogue_word_cap(secs, n)`. T1 fires when `w > cap` or `n > DIALOGUE_MAX_FRAGMENTS`, with the message `"panel %d: T1 spoken timing: Dialogue: is %d words in %d sentences; a %s-second clip fits at most %d words in %d sentences, and a line has at most 3 sentences; shorten the line, or split it across alternating close-up panels (the speaker, then the listener, then the speaker again)" % (k, w, n, S, cap, n)`.

For the alias (a prefixed Narration with no Dialogue) the same test is **advisory**. Its message starts `"panel %d: T1 spoken timing: Narration: speaks %d words in %d sentences; ..."` and is otherwise identical.

**T2 action amount / T3 action overload (hard-action, never blocking).**

`text` is the writer action text: the Motion writer text in chained and shots, the Prompt writer text in no_stills.

- `A` is the number of non-empty sentences `s` with `not _is_camera_sentence(s, plan cast phrases)`.
- `seq = len(SEQUENCE_RE.findall(text))`, where `SEQUENCE_RE = re.compile(r"\b(?:then|afterwards?|whereupon|followed\s+by|as\s+soon\s+as)\b", re.I)`.
- `conn = len(NO_STILLS_CONNECTOR_RE.findall(text))`, where `NO_STILLS_CONNECTOR_RE = re.compile(r"\b(?:initially|a\s+moment\s+later|moments\s+later|finally|after\s+that|soon\s+after)\b", re.I)`.

`units` by mode:
- chained: `1 + seq + max(0, A - 2)`;
- shots: `A + seq`;
- no_stills: `1 + seq + conn`.

`max_actions = max(1, int(secs / per + 1e-9))`, where `per` is `NO_STILLS_BEAT_SECONDS = 1.0` in no_stills and `ACTION_SECONDS = 3.0` otherwise. At the defaults that is 2, 2 and 6.

Messages (`L` is `Motion` or `Prompt`):
- `A == 0` → T2 `"panel %d: T2 action amount: %s: has no physical action; a %s-second clip needs one, so add one action sentence and keep every other sentence word for word"`.
- `max_actions < units <= 2*max_actions` → T2 `"panel %d: T2 action amount: %s: holds %d actions; a %s-second clip fits at most %d, so cut the extra actions and keep every other sentence word for word"`.
- `units > 2*max_actions` → T3 `"panel %d: T3 action overload: %s: holds %d actions; a %s-second clip fits at most %d and cannot render more than %d; give the extra actions their own panels"`.

**[spec choice: only sequence markers count as extra actions. `while`, `simultaneously` and `, and` describe concurrent action; counting them flagged 31 of 31 legacy chained stories (Section 10.4). Chained mode allows "one or two plain sentences". No_stills is deliberately multi-beat.]** T3 is not a separate blocking class. It exists so the message and the user's warning say "overload", and it is reported in `unresolved` like T2.

### 6.3 Audit of every current hard rule

"Renders" means the manifest and the renderer proceed with the violation present.

| Rule | Today | New class | Justification |
|---|---|---|---|
| V0 / `legacy_validate` (panel count, missing Image/Motion/Prompt, Prompt+Image) | hard | hard-structural | the manifest exits 2 on each |
| P1 beat count | hard | hard-structural | beats map 1:1 to panels |
| P2 structure | hard | hard-structural | assembly indexes undefined ids; already fatal at the plan stage |
| P3: phrase fails `normalize_phrase`, or a duplicate phrase | hard | hard-structural | phrase, speaker and trigger matching are undefined |
| P3: phrase longer than 4 words; descriptor invalid | hard | advisory | the identity sentence pastes either way |
| P4, P5, P7, P8, P9 | hard | advisory | renders (an unknown shot or camera only means no pasted sentence; speaking beats are coerced) |
| P13 undeclared library character | hard | advisory | renders without that LoRA (Q1 resolution) |
| N10 (plan scope) | hard | advisory | renders |
| L1 unknown id, wrong target or incompatible model | hard | hard-structural | the renderer cannot resolve the LoRA |
| L5 strength outside (0, 2] | hard | hard-structural | the manifest (`:209-211`) and the renderer (`:302-304`) refuse it |
| L5 strength inside (0, 2] but outside the entry's range | hard | advisory | renders; it is catalog policy |
| L6 duplicate on a panel | hard | hard-structural | the renderer's duplicate checks refuse it |
| L7 stills (more than 1; non-empty in no_stills; also passed as `--stills-lora`) | hard | hard-structural | Phase 2 consumes exactly one catalog stills LoRA (LC14) |
| L2 style, L3 motion, L4 count | hard | advisory | stacking policy; renders (Q4 resolution) |
| N2, N3, N4, N5, N6, N7, N8, N9, N10 | hard | advisory | renders |
| N11 narration empty | hard | hard-structural, narrowed to `ctx.narration is True` with Narration empty **and** no Dialogue | the manifest's proportional pace exits 2 (`:637`) |
| N15 undeclared library character | hard | advisory | renders (Q1) |
| N16 speaker not on screen; speech-only voice-over | hard | advisory | renders |
| N12 | advisory | advisory | T2/T3 now carry the binding part |
| S1 panel count | hard | hard-structural | the manifest exits 2 when the image count and the panel count differ |
| S3 fields (missing Image/Motion; Prompt present; Narration missing **and** no Dialogue) | hard | hard-structural | the `--shots` manifest exits 2; pace error |
| S2, S5, S6, S7, S8, S9, S10, S11, S12 | hard | advisory (robust engine) | renders; T2/T3 replace S5's binding part |
| new T1 | — | hard-timing, blocking | D3/D6 |
| new T2, T3 | — | hard-action, non-blocking | D6 |
| new N18 dialogue form | — | hard-structural | the manifest exits 2 (DG7 step 4) |
| new P14 speaking beat | — | advisory | coercion notes |

The S rules are reclassified **in the robust engine only**. `character_lib.shots_violations` still returns S1-S12 as one list, and the legacy path uses it unchanged. Every robust-engine caller splits the result: ids in `SHOTS_HARD_RULES = ("S1", "S3")` are hard, and the rest go to the advisory list after `_order_by_panel`, together with `shots_advisories`. This applies to `panel_checks`, `recheck` with a plan, the no-plan shots path of `recheck` (`:2581-2595`) and `plan_free_report`.

### 6.4 Where the classification lives (code changes)

- `_field_checks`:
  - N2-N10, N15 and N16 go to `advisory`.
  - N11 keeps the narrowed hard rule.
  - New hard rules: T1, T2, T3 and N18 (`"panel %d: N18 dialogue: Dialogue: %s"`; phrases are the plan cast phrases, or without a plan the member phrases).
  - The alias T1 is advisory. N17 is extended (Section 7).
  - The `Dialogue` label is excluded from N1-N10: N4 and N10 add `label != "Dialogue"`, while N1, N2, N3 and N5-N9 already never read it. N15 does read it.
- `GENERATION_CHECKS` and `RECHECK_IDS` gain `"N18", "T1", "T2", "T3"`. `PLAN_FREE_IDS` is unchanged.
- `plan_checks`:
  - P3's normalize and duplicate messages stay hard; P3's other messages go to advisory.
  - P4, P5, P7, P8, P9 and P13 go to advisory.
  - `speech_notes` are appended to advisory.
- `panel_checks`: `plan_copied_examples` goes to advisory.
- `lora_checks`:
  - L5 splits: when the strength is not within `0 < s <= 2`, the message is `"plan: L5 strength: %s strength %s is outside (0, 2], which the renderer refuses"` (hard).
  - Otherwise the existing range message is advisory.
  - L2, L3 and L4 (both branches) are advisory. L1, L6 and L7 stay hard.
- `REPAIR_IDS = ("N11", "T1", "T2", "T3")` replaces `WRITER_CHECK_IDS`, which is deleted.
- `_new_rs37` compares `hard + advisory` of state `i` against state 0.
- **Ranking (review fix 2):**
  - `_key(states, i)` returns `(n_blocking(states[i]), len(states[i]["hard"]), -low, -total)`.
  - `better` is unchanged in form.
  - `best_round` uses the key `(n_blocking(states[i]), len(states[i]["hard"]), _new_rs37(states, i)) + _key(states, i)[2:] + (-i,)`.
- `plan_free_report` returns `(hard, advisory)`:
  - hard = `legacy_validate` (non-shots), plus the hard part of `_field_checks`, plus S1/S3 (shots);
  - advisory = the advisory part of `_field_checks` (including N15), plus the other S rules.
- `_undeclared_gate` reads N15 from the advisory list, prints each one as `"Warning: %s"` to stdout, and returns `passed` (never `(2, [])`).

### 6.5 Round controller

`CRITIC_MAX_ROUNDS = 2`. Delete `MIN_OK_SCORE`. `critic_round(k, judged)` loses `passed_only` and its "passed" branch (Q3 resolution).

```
go(), after make_state(0, ...):
stop = "passed" if not states[0]["hard"] else None
for k in 1..CRITIC_MAX_ROUNDS while stop is None:
    if expired: stop = "time_cap"; break
    stop = critic_round(k, k - 1)
    if stop: break
    if not states[-1]["hard"]: stop = "passed"; break
    if time_up: stop = "time_cap"; break
    if k == CRITIC_MAX_ROUNDS: stop = "max_rounds"
judge = judge_gate() if ctx.judge else None
best, blocking, unresolved = final_outcome(states)
```

- A state with no hard violation stops immediately; the critic is **not called** and `scores` stay `None`.
- The valid-reply plateau check stays `judged >= 1 and not better(...)`. In the code-only branch, the count comparison becomes `(n_blocking(prev), len(prev["hard"])) >= (n_blocking(states[judged-1]), len(states[judged-1]["hard"]))`.
- `final_outcome(states)` is pure and module-level. It returns `(best_round(states), blocking, unresolved)`: blocking is the messages of the best state whose id is not in `NON_BLOCKING_IDS`, and unresolved is the rest of its hard list.

Outputs:
- `story_checks.json`: `"hard": blocking`, `"unresolved": unresolved`. story.md and plan.json are written as today.
- When nothing is blocking: print `"Warning: unresolved after %d critic round(s): %s"` per unresolved message (the round count is `len(states) - 1`), then `finish(0)`.
- When something is blocking: print the existing exit-2 block, listing and counting only the blocking messages. When unresolved is non-empty, print `"Also unresolved (not blocking):"` and `"  - %s"` lines before the hand-edit sentence. Then `finish(2)`.

**"Grossly impossible"** means T1: a spoken line over its fragment-aware cap. The manifest refuses it anyway, so proceeding would only move the failure to Phase 3. Structural violations block because the pipeline cannot continue, not because they are timing.

### 6.6 Patch whitelist (PG)

**PG1.** `patch_ranges`:
- `("panel","motion")`: `(1, n)` unless no_stills.
- `("panel","prompt")`: `(1, n)` in no_stills.
- `("panel","dialogue")`: `(1, n)` when `ctx.narration is not False`, else None.
- `("plan","lora")`: as today.
- `("plan","beat.action")`, `("plan","beat.shot")`, `("plan","beat.camera")`, `("plan","location.setting")`, `("panel","image")`, `("panel","narration")`: `NOT_REPAIRED = "advisory"`. `_patch_problem` returns `"not repaired automatically: only spoken timing and the amount of action are patched"` for them.

**PG2.** `apply_patches(ctx, state, patches, lora_allowed=None, repairable=None)` returns `(new, applied, rejected)`. The `regen` parameter, the `beat.action` branch, the regenerate list and `_Run.regenerate` are **deleted**: no caller is left once beat.action patches go and the judge gate stops applying patches.

`repairable` is `{panel: set(ids)}` built from the judged state's hard list; `None` means no restriction (unit tests).
- `motion`/`prompt` require `repairable is None` or the panel has `{"T2","T3"}` in its set.
- `dialogue` requires `"T1"` in the panel's set.
- When the requirement is not met, the reason is `"panel %d has no hard timing or amount-of-action problem; advisory findings are never patched"`.

**PG3. Sentence guard (motion/prompt).**

Let `old` be the sentence list of the current part, and `new` the sentence list of `clean_writer(...)` applied to the replacement (each list built with `_SENTENCE_SPLIT_RE`, stripped, non-empty). Let `p` be the length of the common prefix and `s` the common suffix, with `s <= min(len(old), len(new)) - p`.

The old span is `old[p:len(old)-s]` and the new span is `new[p:len(new)-s]`. `units0` and `max_actions` are computed by T2 on the old text, and `limit = max(1, units0 - max_actions)`.

Reject the patch when either holds:
- `len(old span) > limit`. Reason: `"the patch changes %d sentences; it may change at most %d contiguous sentence(s) and must keep every other sentence word for word"`.
- A camera sentence of the old span (`_is_camera_sentence(s, phrases)`) is absent from the new span. Reason: `"the patch drops the camera direction %s"`.

Sentences are compared with `==`.

**PG4. Dialogue patch.**
1. Apply `clean_writer`.
2. Strip a leading speaker phrase and colon.
3. Apply the DG3 step 4 quote replacement and add a terminal `.` if missing.
4. Reject with `"empty after cleanup"` when nothing is left.
5. Reject with `"the new line is %d words in %d sentences; at most %d words in %d sentences fit this clip"` when the line is over `dialogue_word_cap(secs, n)` or over 3 sentences.

**PG5. Code-only round** (no valid critic reply). For each panel with hard ids in `REPAIR_IDS` and panel budget left, call `panel_call(fix=<that panel's hard messages only>)`. Then merge into the previous parts:
- `motion`/`prompt` when the panel has T2/T3 and PG3 accepts;
- `dialogue` when it has T1 and the new line is within the cap;
- `narration` when it has N11.

Every other field keeps its previous text.

**PG6. LoRA patches.** `lora_allowed = lora_patches_allowed(ctx) and any(id in ("L1","L5","L6","L7") for the hard ids of prev)`. `catalog_lines` are passed to the prompt only when that holds.

### 6.7 Re-check

**With a plan:**
- hard = `legacy_validate` + the hard part of `_field_checks` + S1/S3 + the hard LoRA checks.
- Split it into blocking and unresolved as in `final_outcome`, and write `story_checks.json` with `hard` = blocking and `unresolved`.
- Exit 2 (existing messages) only when something is blocking. Otherwise print `"Warning: unresolved: %s"` per unresolved message and return `(0, advisory)`.

**Without a plan, shots** (`:2581-2595`): `violations` becomes the S1/S3 part only. The other S messages are appended to `advisories`, ahead of `shots_advisories`. The exit-2 block runs only for S1/S3, and the `_undeclared_gate` behaviour follows 6.4.

**Without a plan, non-shots:** `legacy_validate` as today, then `_undeclared_gate`, which now only warns.

### 6.8 Judge gate (`--judge`) is report-only (Q3 resolution)

- The gate is skipped when the best round's blocking list is non-empty.
- On success it records `{"status","detail","scores","min_score","applied": False}`.
- When `min_score < JUDGE_MIN_SCORE`, it writes `judgment.patches.json` into the best round's directory and prints `"Warning: judge-story minimum score %d is below %d; its patches are saved in %s and were not applied (only spoken timing and the amount of action are repaired automatically)"`. No state is added and no critic round follows.
- `--judge` help becomes `"after the local critic rounds, run bin/judge-story --patches (Claude; needs ANTHROPIC_API_KEY) as a final report: its scores go into story_checks.json and its patches are saved, never applied"`.
- The dry-run line at `:2207` becomes `"Judge gate: bin/judge-story --patches after the critic rounds (report only)."`.

### 6.9 `bin/ltx-movie` text

- Docstring `:100`: "up to three local critic rounds" becomes "up to two local critic rounds that repair only spoken timing and the amount of action", and "when hard violations remain" becomes "when blocking violations remain".
- Dry run `:2193`: `"Story engine: a JSON plan, one call per panel, deterministic checks and up to 2 critic rounds that repair only spoken timing and the amount of action (analyst via the local qwen-agentd, else a local one-shot); --story-legacy for the single-prompt path."`

---

## 7. Rule table (new and changed messages)

| ID | Class | Message |
|---|---|---|
| T1 | hard, blocking | 6.2 (the alias variant is advisory) |
| T2 | hard, non-blocking | 6.2 (two messages) |
| T3 | hard, non-blocking | 6.2 |
| N18 | hard-structural | `panel %d: N18 dialogue: Dialogue: <DG3 problem>` |
| P14 | advisory | SP2 notes |
| N11 | hard-structural | text unchanged; narrowed condition |
| L5 | hard (outside (0, 2]) / advisory (outside the entry's range) | 6.4 |
| N16 | advisory | Dialogue variant: `panel %d: N16 speaker: Dialogue: is spoken by %s, who is not in this shot; put %s in the shot or move the line to a panel that shows them`. The alias and speech-only texts are unchanged. |
| N17 | advisory | The existing wide-shot and held-expression texts use the label `Dialogue` (or `Narration` for the alias). New: `panel %d: N17 speaking shot: Dialogue: %s speaks in a shot that also shows %s; a speaking shot shows only the speaker`. New: `panel %d: N17 speaking shot: Motion: has the camera direction %s while %s speaks; a speaking shot keeps the camera static`, for the first writer camera sentence whose `CAMERA_MOTION_RE` match is **not** one of `static`, `still`, `hold`, `holds`, `locked-off`, `push in`, `pushes in`, `push-in` (the plan allows a slow push-in, so it is never flagged); the label is `Prompt` in no_stills. |
| N3 | advisory | the tail changes per CM2 |
| N2, N4-N10, N15; P3 (part), P4, P5, P7, P8, P9, P13; L2-L4; S2, S5-S12 | advisory | text unchanged |

---

## 8. Prompt text (exact)

### 8.1 Plan prompt

- `"with the keys index, arc, action, shot, camera, location and cast."` becomes `"with the keys index, arc, action, shot, camera, location, cast and speaker."`.
- `"not a sequence of steps, with no dialogue and no on-screen text."` becomes `"not a sequence of steps, with no on-screen text."`.
- `"at most @@MAX_CAST@@.\n"` becomes `"at most @@MAX_CAST@@.@@SPEAKER_RULE@@\n"`. `@@SPEAKER_RULE@@` is a fragment token:
  - When `ctx.narration is False`: `" speaker is always an empty string: nobody speaks in this movie."`
  - Otherwise: `" speaker is the id of the one character who says something aloud on screen during the beat, or an empty string when nobody speaks; give a speaker only where a spoken line moves the story. A beat with a speaker shows only that character (its cast is just their id), in a medium close-up or close-up, facing the camera, with the camera static or a slow push-in."`

### 8.2 Panel prompt

- `chained_motion1`: replace `" Do not mention the camera: the pipeline adds the camera sentence."` with `" You may add one camera direction; without one, the pipeline adds the planned camera sentence."`.
- `chained_motion`: replace `"Do not describe appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is already on screen."` with `"Do not describe appearance, clothing, setting, lighting, colour or style -- all of that is already on screen. You may add one camera direction."`.
- `shots_motion`: replace `" Do not mention the camera: the pipeline adds the camera sentence."` with `" You may follow it with one camera sentence; without one, the pipeline adds the planned camera sentence."`.
- `no_stills_prompt` becomes:

  `"prompt: W1 to W2 words in the present tense: one flowing paragraph in strict chronological order that opens with the main action, carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, then, while, a moment later), names the ambient and environmental sounds alongside the actions that make them, and states the camera viewpoint and the lighting and colour; you may also state a camera movement. Name each character only by their referring phrase. Do not describe any character's appearance or clothing, do not write a sentence about the place itself and do not name the shot type: the pipeline adds each character's description, the place's setting sentence, the shot type and, unless you state one, the camera movement itself. Describe only what is physically observable, with no mood words, no spoken words and no markdown."`

- New `no_stills_prompt_speaking`, used on a speaking no_stills panel. It resolves the conflict between "carry many beats" and "keep movement small". It is `no_stills_prompt` with `"carries enough separate beats to fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, then, while, a moment later), "` replaced by `"fills the full @@SECONDS@@ seconds with small, continuous movements of @@SPEAKER@@ -- a breath, a glance, a small hand gesture -- "`.
- `narration`: `"narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud. Never put a spoken line here."`
- New `narration_with_dialogue`: `"narration: one sentence of 3 to 30 words of voice-over that nobody on screen says aloud, or an empty string: this panel's spoken line goes in dialogue, never here."`
- New `dialogue`: `"dialogue: the exact words @@SPEAKER@@ says aloud in this panel: at most @@DWORDS@@ words as one sentence, about one word fewer for each further sentence, and at most three sentences; no quotation marks, no speaker name and no description of how the words are said -- the pipeline adds who says them and how."`
- Delete `narration_speech`.
- New constants:
  - `SPEAKING_ACTION_SENTENCE = (" In this panel @@SPEAKER@@ speaks the dialogue: keep their movement small -- a breath, a glance, a small hand gesture -- with the camera holding still, and do not write the spoken words or a speaking verb here; the pipeline adds them.")`
  - `SPEAKING_PROMPT_SENTENCE = (" Do not write the spoken words or a speaking verb here; the pipeline adds them.")`
  - `SPEAKING_IMAGE_SENTENCE = (" @@SPEAKER@@ is the only person in the frame, facing the camera.")`
- `build_panel_prompt` processes each key line in this order:
  1. Choose the template: `narration_with_dialogue` for `narration` on a speaking panel; `no_stills_prompt_speaking` for `prompt` on a speaking no_stills panel.
  2. Append `SPEECH_FRAMING_SENTENCE` as today.
  3. On a speaking panel, append `SPEAKING_IMAGE_SENTENCE` to `image`, `SPEAKING_ACTION_SENTENCE` to `motion`, and `SPEAKING_PROMPT_SENTENCE` to `prompt`.
  4. Replace W1/W2.
  5. Replace `@@SPEAKER@@` with `'"' + phrase + '"'` and `@@DWORDS@@` with `str(dialogue_word_cap(engine_seconds(ctx), 1))`.
- Fix block: insert `"\nFix only these problems. Keep every camera direction, every descriptive sentence and the dialogue word for word, and change only the sentence or sentences that cause them."` before `"\nPrevious version:\n"`.

### 8.3 Critic prompt

- `"Problems the pipeline's own checks found in this draft (fix the hard ones first):\n"` becomes `"Problems the pipeline's own checks found in this draft. Only the [hard] ones are fixed by patches; the [advisory] ones are reported to the user and must never be patched:\n"`.
- The renderability bullet becomes `"- renderability: every panel shows physical action that a video model can render in @@SECONDS@@ seconds -- neither more actions than fit nor none -- every spoken line fits its clip, and there is no on-screen text and nothing outside the frame. Camera directions and dialogue are part of a good panel, never a fault.\n"`.
- The text from `"Then propose at most 8 patches, most important first. Each patch ..."` through `"... because the pipeline adds those itself."` becomes:

  `"Then propose at most 8 patches, most important first, only for the [hard] problems: a spoken line that does not fit its clip, or a panel with more or fewer actions than its clip can hold. Each patch is an object with exactly the keys target, index, field, reason and replacement. The allowed patches are:\n@@FIELD_LINES@@\nPreserve every camera direction, every descriptive sentence and every dialogue line word for word: change only the sentence or sentences that cause the problem, and copy every other sentence of the field unchanged. A patch that changes anything else is rejected. A panel replacement holds only the text the writer writes: never include a character's description, a setting sentence or the shot type, because the pipeline adds those itself."`

  It is followed by the unchanged `" The number of panels, the characters' referring phrases and their descriptions never change.\n"`.
- `critic_field_lines(mode, catalog_lines, narration=True)` lists, in order:
  - the lora line, unchanged, when `catalog_lines` is set;
  - for chained and shots: `'- target "panel", field "motion", index = the panel number, only for a panel with a [hard] T2 or T3 problem: replacement is the panel\'s whole new Motion: writer text, identical to the current text except for the sentence or sentences that hold the extra or missing action.'`;
  - for no_stills: the same line with `"prompt"` and `Prompt:`;
  - when `narration is not False`: `'- target "panel", field "dialogue", index = the panel number, only for a panel with a [hard] T1 problem: replacement is the shortened spoken line, without the speaker\'s phrase and without quotation marks, within the limit the T1 problem states.'`.
- Delete `ONLY1` and `@@ONLY1@@`.
- `bin/judge-story` `PATCH_FIELDS` appends `"dialogue"`.

---

## 9. Tests

### 9.1 New: `tests/test_dialogue.py`

Stdlib plus pytest. Modules are loaded by path, as in `tests/test_story_engine.py`. It uses `tests/story_engine_testutil.py`. Every `_Run` gets `story_dir` under `tmp_path`.

| ID | Covers |
|---|---|
| DLG1 | `parse_dialogue`: phrase as given; the sort key (a 3-word phrase beats its 2-word prefix); quote stripping; inner quotes become `'`; terminal `.`; the three problem strings; a 7-word phrase; an empty value gives `(None, "", None)` |
| DLG2 | `split_fragments`; `dialogue_word_cap` values in DG2 (including 14/13/12 and the 241-frame row) |
| DLG3 | `speech_text` beats for 1/2/3 fragments (exact strings); `beats-no-acoustic`; plain equals `speech_sentence`; 5 fragments collapse into 3 without an exception; constants equal DG1 |
| DLG4 | `insert_speech` with `phrases`: the facing sentence is not a camera sentence; a 2-sentence trailing camera run; the existing `test_spoken_narration_helpers` cases unchanged |
| DLG5 | `_is_camera_sentence`: true for "Slowly the lens drifts across the empty quay." and "A close-up of the sealed letter."; false for "He turns toward the camera.", for "The courier faces the camera." when phrases are given, and for "The waves pan out across the bay."; true for every `CAMERA_SENTENCES` sentence; the `test_s91` tails unchanged |
| DLG6 | `cast_text(skip_quoted=True)` |
| DLG7 | manifest goldens: the DG9 examples (beats, chained plain, chained beats-no-acoustic), byte for byte; the `speaker`, `speech`, `speech_source` keys |
| DLG8 | the alias: `speech_source "narration"`; plain equals the pre-change string |
| DLG9 | manifest errors: unknown speaker; over the cap (exact message); alias over the cap gives a WARNING and rc 0; proportional pace with Dialogue and empty Narration passes; a panel with neither gives the new error |
| DLG10 | a panel with both Dialogue and a prefixed Narration: Dialogue wins and the Narration is voice-over |
| DLG11 | coercion: cast, shot and camera with exact P14 notes; invalid speaker; `narration=False`; chained beat 3 speaking coerces beat 1; plan.json carries the new keys |
| DLG12 | plan prompt `@@SPEAKER_RULE@@` text for True, `"speech"` and False; "no dialogue" is absent |
| DLG13 | `writer_keys(..., speaks)` for every mode and narration value; speaking key lines, including `no_stills_prompt_speaking` and the cap; no template contains "Do not mention the camera" or "camera or lens" |
| DLG14 | `parse_panel_reply` on a speaking panel |
| DLG15 | assembly goldens with Dialogue in all 3 modes; manifest round trip; CM4 dedupe drops `{cam}` from the assembly for "The camera slowly pans left." but `pasted_pieces` still lists it; "The camera viewpoint is front-facing." keeps `{cam}`; `story_fields` emits `("Dialogue", ...)` |
| DLG16 | T1 exact messages (16 words in 1 sentence; 13 words in 3 sentences gives T1 because the cap is 12; 4 sentences); alias T1 is advisory |
| DLG17 | T2/T3: chained "then" ×1 gives none, ×2 gives T2, ×4 gives T3; shots with 3 sentences gives T2; no_stills with 6 connectors gives T2; camera-only motion gives "no physical action"; every `seu.panel_json` fixture panel gives no T violation |
| DLG18 | reclassification: the rst20 N2-N10 mutations go to advisory; S2 and S5-S12 go to advisory and S1/S3 stay hard in `panel_checks`, `recheck` with a plan, the no-plan shots `recheck`, and `plan_free_report`; P4/P5/P7/P8/P9/P13 advisory; L2-L4 advisory; L5 strength 2.5 is hard and in-(0,2]-but-out-of-range is advisory; L1/L6/L7 hard |
| DLG19 | the critic prompt contains every 8.3 sentence; the field lines are exactly the allowed set; "(only 1:" and `field "beat.action"` are absent |
| DLG20 | `apply_patches`: the NOT_REPAIRED reason (including `beat.action`); the `repairable` block; dialogue only with T1; PG3 accepts a 1-sentence rewrite, rejects a 2-sentence change when the limit is 1, and rejects a dropped camera sentence; PG4 over-cap; the 3-tuple return |
| DLG21 | **D6 (a)**: an advisory-only round 0 (an N7 quote, N3 "camera", S8 contact in shots) stops `passed` with 0 critic and 0 extra panel calls; story.md equals `story_rounds/round_0/story.md` byte for byte; the advisories are printed |
| DLG22 | **D6 (b)**: panel 2's Motion is `"The courier stops at the crates, then turns, then pedals on. The courier glances up at the rain. The camera slowly pans left."` with a Dialogue (T2: 3 units). The critic rewrites only sentence 1 and the patch is applied; the other sentences, the camera sentence and the `Dialogue:` line stay byte-identical. A second patch that also rewords sentence 2 is rejected. |
| DLG23 | round cap 2: unresolved T2 → exit 0, `Warning: unresolved after 2 critic round(s): ...`, `hard == []`, one `unresolved`; unresolved **T3 → exit 0** with a warning; T1 → exit 2 with the split instruction; `run.json` critic_rounds is 2. **Ranking:** state A (1 hard, T1) and state B (3 hard, all T2); `best_round` picks B and `better(B, A)` is true. |
| DLG24 | code-only round merge (PG5): only a guarded motion is taken; image and narration are kept |
| DLG25 | re-check: T2/T3 only → rc 0 and `Warning: unresolved:`; T1 or N18 → rc 2; no-plan N15 → a Warning and rc 0; no-plan shots S8 → rc 0 with the advisory; S1 → rc 2 |
| DLG26 | the judge gate is report-only |
| DLG27 | `bin/ltx-movie --speech-delivery` default; `plain` and `beats-no-acoustic` reach the manifest command in Phase 3 and the dry run; the default robust dry run's manifest command has no `--speech-delivery` |
| DLG29 | judge-clips `format_panel_text` with a Dialogue panel, an alias panel and an old manifest without `speech_source`; the system prompt sentence |
| DLG30 | judge-story `DEFAULT_GOAL`; `"dialogue" in PATCH_FIELDS` |
| DLG31 | S3 and `_validate_story_md` accept Dialogue in place of Narration |
| DLG32 | `_PANEL_LABEL_RE`, `_STORY_FIELD_RE` and the judge-stills regex accept `Dialogue` and stay identical; a `Dialogue:` line never joins Image or Motion |
| DLG33 | an older plan.json without `speaker`/`speech_notes` loads |
| DLG34 | `motion_problems(..., phrases)`: "The courier faces the camera." counts as an action with the phrase and as a camera sentence without it |
| DLG-H | **Merge-gate offline set.** 6 cases built in code: mode ∈ {chained, shots, no_stills} × {non-speaking, speaking}. Plan: `seu.plan_json(mode, 3)`; the speaking variant sets `beats[1]["speaker"] = "c1"`. Parts: `seu.panel_json(mode, k)`, except panel 2. Panel 2's motion is, for chained, `"The courier leans into the bend while rain streams off the yellow hood. Water sprays from the front wheel across the cobblestones. The camera slowly pans left."`; for shots, `"The courier leans into the bend as rain streams off the yellow hood. The camera slowly pans left."`. In no_stills, panel 2's prompt is `seu.panel_json("no_stills", 2)["prompt"] + " The camera slowly pans left as the yellow hood flaps in the wind."`. In the speaking variants, panel 2's dialogue is `"Keep moving. The gate is close."` (6 words, 2 fragments, cap 13). Each case asserts: 0 blocking at round 0; stop `passed`; 0 critic calls; every sentence of panel 2's writer text appears verbatim in story.md; the speaking variants also have `Dialogue: the courier: Keep moving. The gate is close.` verbatim. |
| DLG-K1 | post-merge calibration replay (Section 10.1); `pytest.skip("dialogue KPI corpus not recorded")` when the corpus is absent; reports the pass count and asserts at least 22 only when the environment variable `DIALOGUE_KPI_ENFORCE=1` is set |

DLG28 (movie-ui) was cut with the Compose field.

### 9.2 Existing tests that change

**A. Must be updated**, limited to the stated reason:

| Test | Reason |
|---|---|
| `test_story_engine.py::test_rs4_constants` (`:81`) | `CRITIC_MAX_ROUNDS` becomes 2 |
| `::test_rst8_plan_prompt_matrix` | 8.1 |
| `::test_rst12_lexicons` (`:658`) | it asserts `{"grey","kimono","camera","close-up","palette"} <= APPEARANCE_WORDS`; the new assertion is `{"grey","kimono","palette"} <= APPEARANCE_WORDS` and `not ({"camera","close-up"} & APPEARANCE_WORDS)` |
| `::test_rst13_normalization` | `speaker`, `speech_notes` |
| `::test_rst14`, `::test_rst15`, `::test_rst55_p13_undeclared_character` | hard→advisory moves; the L5 split |
| `::test_rst16_panel_prompt` | fix-block text |
| `::test_rst20_panel_checks` (`:985-1012`) | the N3 "camera" case gives `[]`; N3 tail text |
| `::test_rst20b` | the 29-word alias adds an advisory T1 |
| `::test_rst20c` | speech-only has no narration key; `narration_speech` deleted; the voice-over N16 assertion moves to a re-check |
| `::test_rst20e` | `critic_field_lines` has no `beat.shot` line |
| `::test_rst22_critic_prompt` (`:1174`) | header text; no image line; ONLY1 count 0 |
| `::test_rst27`, `::test_rst28`, `::test_rst29`, `::test_rst30`, `::test_rst31`, `::test_rst32` | `apply_patches` returns a 3-tuple and has no `regen`; setting, shot, camera, image, narration and beat.action patches are rejected with the NOT_REPAIRED reason; `::test_rst29` becomes a beat.action rejection test |
| `::test_rst26b`, `::test_rst33`-`::test_rst39`, `::test_rst43`, `::test_rst51`-`::test_rst54`, `::test_rst58`, `::test_rst55b_p13_forces_plan_call_2` | `_shouting` (`:1476`; N7 strings at `:1571`, `:1651`, `:1776`) is replaced by a T2 helper (motion `"The courier stops at the crates, then turns, then pedals on toward the far end of the wet road."`). Exit-2 cases use a **T1 helper**: plan mutation `beats[1]["speaker"] = "c1"`, and panel 2's reply carries the 16-word over-cap dialogue in DG9. A clean round 0 makes no critic call; max rounds is 2; `story_checks` gains `unresolved`; P13 no longer forces plan call 2; `::test_rst38` is report-only |
| `::test_rst36`, `::test_rst36b` | the new ranking key; `_new_rs37` reads advisories |
| `::test_rst44`, `::test_rst44b`, `::test_rst44d`, `::test_rst44e`, `::test_rst45`, `::test_rst56`, `::test_rst56b` (both), `::test_rst56c` | N15/N7 are advisory; re-check exits 2 only when something is blocking; `plan_free_report` returns `(hard, advisory)` (`:2018-2026`) |
| `::test_rst47_robust_dry_run` (`:2529`, `:2534`) | 6.8 and 6.9 lines |
| `test_judge_story.py::test_goal_default_prompt_byte_identical` (`:494`) | new `DEFAULT_GOAL`; re-baseline the length (2223) and the SHA |
| `test_judge_clips.py::test_goal_default_prompt_byte_identical` (`:1202-1216`) | re-baseline the length and the SHA |
| `test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (`:258`) | **in a separate test-only follow-up commit** after the feature commit: set `BASELINE` to the feature commit's SHA and append ", then to <sha> (on-camera dialogue)" to the comment. DK1 is measured after this commit. |

**B. Re-run; edit only for an A reason:** `::test_rst10`, `::test_rst11`, `::test_rst21`, `::test_rst46`, `::test_rst50_source_literal_counts`, `::test_story_focus_1`-`3`, `::test_rst44c`, `::test_rst44f`, `::test_rst48`.

**C. Must pass unchanged:**
- `test_story_engine.py::test_rst17`, `::test_rst18`, `::test_rst19`, `::test_rst40`, `::test_rst41`, `::test_rst61`, `::test_rst62`;
- `test_character_lib.py::test_spoken_narration_helpers` (`:552`) and `:540-550`;
- `test_shots_mode.py::test_s6`, `::test_s7`, `::test_s91`, `::test_s97`, `::test_s52`, `::test_s20`;
- `test_ltx_movie_offline.py` L5 (`:300`), L15 (`:569-621`), L16;
- `test_ltx_story_manifest_chain.py` C7a-c and `::test_v2_golden_byte_identical` (`:335`);
- `test_movie_ui_builder.py:118-131` (no movie-ui change);
- `test_casting_regression.py`.

The legacy templates are unchanged and the new `phrases` parameters default to `()`. Each of those tests' inputs classifies the same under CM1: "He stays static." still matches rule (b), "The robber takes the shot." has a person noun, and no zoom, pan or tilt term was added to rule (c).

---

## 10. KPI measurement

### 10.1 Post-merge calibration corpus (DK6, DLG-K1)

`tests/fixtures/dialogue_kpi/<case>/` holds 24 cases: the 8 [ROBUST] 7.1 premises × {chained, shots, no_stills}.
- Every case uses `--panels 6` and no `--character`, `--seed-image` or `--model`.
- Premises 2, 6 and 8 get `" They exchange a few short spoken lines."` appended to the narrative.
- Each case holds `case.json` (`{"mode","panels","seconds":"6","clip_seconds":6.041666666666667,"narration":true}`) plus a verbatim copy of `story_rounds/round_0/plan.json` and `parts.json`.

The main thread or the user records the corpus on hardware, after the merge:

```
bin/ltx-movie "<premise>" --story-id kpi-<mode>-<n> --panels 6 [--shots|--no-stills] --story-only --no-review --force-story
```

Replay, per case:
1. Build `ctx` with `story_dir` under `tmp_path` and load the plan and the parts (parts.json `panels` with `index` dropped).
2. Call `runner.make_state(0, ...)`.
3. Monkeypatch `se.run_critic` to return the null critic `("ok", json.dumps(seu.critic_json(verdict="revise")), "local")`. `se.run_agent` must raise if it is called.
4. Run the 6.5 loop and `final_outcome`.

A case passes when blocking is `[]`. The calibration target is at least 22 of 24 (≥ 90%). That is the legacy chained no-T3 rate, 29 of 31, rounded down, with 2 misses allowed for model variance; the null critic makes it a no-repair lower bound.

DLG-K1 is a calibration fixture, not a merge gate (DK6).

### 10.2 Live: the real KPI (DK7)

Run [ROBUST] 7.1 premises 1-8 in chained and shots mode, with `--panels 6 --story-only --no-review --force-story` (16 runs), with the story server up and no other GPU work.
- Pass bar: at least 14 of 16 exit 0 with no hand edit. The 6 runs of premises 2, 6 and 8 each contain at least one speaking panel within its cap.
- Record per run: exit code, critic rounds used, and the blocking, unresolved and advisory counts.
- **Rollback rule:** a miss reopens the T-rule constants and thresholds for a user decision, calibrated with DLG-K1. It does not reopen the D6 classification.

### 10.3 Delivery A/B (informational)

Take 6 speaking panels from 10.2, with at least one panel each of 1, 2 and 3 fragments. Render each with `--speech-delivery beats` and with `plain`, using the same seed. For each clip, record:
- line repeated (y/n);
- unquoted prompt word voiced (y/n);
- **last words cut off (y/n)**;
- lip-sync (1-5);
- detached delivery (y/n).

If any beats clip repeats a line, render a third arm, `--speech-delivery beats-no-acoustic`, for the same 6 panels.

Log the results in the PR. Beats stays the default (D2); changing the default is a user decision.

### 10.4 Baseline evidence (a throwaway approximation run while writing this spec)

On the 62 legacy story.md files (counting sequence markers only; camera sentences by the start rule):

| Mode | Stories | Any panel over budget | Any panel over 2× budget | Panels over budget |
|---|---|---|---|---|
| chained | 31 | 7 | 2 | 9/273 |
| shots | 26 | 15 | 11 | 66/225 |
| no_stills | 5 | 0 | 0 | 0/30 |

Legacy shots Motions are often 6-7 sentences long, which the robust shots writer is never asked for. Counting `while` and `, and` would have flagged 31 of 31 chained stories. None of these stories has a spoken line.

---

## 11. Casting attachment (chained): PROPOSED, pending user approval

**Status:** proposal. Not part of DK1-DK7 or the merge gate. Build only after user approval, in its own commit, with its tests (CA-T1 to CA-T5) and an enumeration of the casting tests it re-baselines. That enumeration is done on approval.

**Problem.** In chained mode, a character LoRA and its trigger are attached only when `cast_text` finds the referring phrase in the panel's Motion text (`bin/ltx-story-manifest:736`, `character_lib.py:592-632`). A panel that refers to a cast member by pronoun ("she turns") or by name gets no LoRA, and its identity drifts at the seam. Strength also changes from panel to panel: 1.0 when exactly one cast character is named, otherwise the member's strength or 0.8 (`character_lib.py:40-41`, `:684-693`). Consecutive chained clips can therefore swing between 1.0 and 0.8 for the same character.

- **CA1. Plan-based attachment.** When `generated/stories/<id>/plan.json` loads (the manifest already reads it in `_known_phrases`), panel k's attached members are the members `m` with a plan cast entry in `beats[k-1].cast` whose `cast_name == m.name`, or whose phrase matches `m.phrase` case-insensitively, together with the members found by text (CA2). Without a valid plan, attachment stays text-only, as today.
- **CA2. Name and trigger matching.** `cast_text` also matches:
  - the member's **name** as a whole word that starts with an uppercase letter and is not preceded by `a`, `an` or `the` (so "the ronin" the phrase and "a ronin" the extra do not collide); the trigger is inserted before the name;
  - the bare **trigger**, which is counted with no insertion.

  The phrase stays the longest-first primary match. `skip_quoted` applies.
- **CA3. Pronoun-only reference.** An attached member with no phrase, name or trigger match in `motion_prompt` gets their trigger prefixed in LC18 format (`"t1, t2. " + prompt`, the `lora_catalog.prefix_triggers` semantics; the manifest loads `lora_catalog.py` by path only in this case). The story engine adds advisory **N19 cast reference**: `panel %d: N19 cast reference: Motion: refers to %s only by pronoun; the pipeline attaches their LoRA from the plan and prefixes their trigger` when `_PRONOUN_RE` matches the writer text, else `... Motion: never mentions %s; ...`. It runs in chained mode, for members with a `cast_name`.
- **CA4. Constant strength across panels (proposed rule).**
  - In chained mode, when the story declares exactly one cast member, that member's strength is `SINGLE_CHARACTER_STRENGTH` (1.0) in **every** panel, whether or not they are named.
  - With two or more cast members, each member's strength is constant across all panels: their `character.json` strength if set, else `--character-strength` (default `DEFAULT_CHARACTER_STRENGTH` 0.8).
  - Shots mode is unchanged (already constant).

  Rationale: a chained clip is conditioned on the previous clip's last frame, so a strength change at a seam is an identity change at the one point the take must hide.
- **CA tests (on approval):**
  - CA-T1: pronoun-only panel → LoRA attached and trigger prefixed.
  - CA-T2: name match → trigger inserted before the name; lowercase "a ronin" not matched.
  - CA-T3: no plan.json → behaviour unchanged.
  - CA-T4: strengths constant across panels for 1 and 2 cast members.
  - CA-T5: N19 messages.
- **Expected re-baselines:** the casting tests that pin the 1.0-when-named-alone rule, such as `tests/test_casting_pipeline.py` and `tests/test_ltx_story_manifest_chain.py` cast cases, to be enumerated on approval.

---

## 12. Rollout

1. Implement G1-G7 and the tests G8-G9 in one feature commit. Run the merge gate (DK2-DK5) and the full suite.
2. Opus design review of the diff against this spec.
3. Make the test-only follow-up commit G10 (the `test_mut26` re-baseline), then measure DK1.
4. Post-merge: record the corpus and run DLG-K1 with `DIALOGUE_KPI_ENFORCE=1` (DK6). Run the live KPI (DK7) and the A/B. A DK7 miss triggers the rollback rule.
5. Section 11 only after user approval.

---

## 13. Values chosen by the spec

1. The manifest splits fragments at sentence ends (DG4).
2. Beats are fixed: "After a breath", then "After a short pause", with no "continues" and no repeated subject (DG1, DG5).
3. The acoustic sentence is the brief's wording, verbatim.
4. A third delivery, `beats-no-acoustic`, exists for the A/B.
5. The cap is fragment-aware: `min(14, int(2.4 × (secs − 0.4 × (n − 1))))`, which gives 14/13/12 at the default clip (DG2).
6. One flag, `--speech-delivery`, on `bin/ltx-movie` and the manifest; it is CLI only.
7. Inner quotes become `'` (DG3).
8. An alias line over the cap only warns.
9. D4 is enforced by plan coercion (SP2); chained beat-1 coercion is Q5.
10. The facing sentence is pasted.
11. `--speech-only` has no narration key.
12. Composition happens at render time.
13. N3 camera words are removed.
14. Dedupe is movement-only, and `pasted_pieces` always keeps `{cam}`.
15. Legacy is unchanged, including the strict shots loop (Q2).
16. T2/T3 constants: sequence markers only, 3.0 s per action, 1.0 s per no_stills beat, T3 above 2× the budget.
17. Blocking = T1 + structural; T2/T3 never block.
18. Ranking puts the blocking count first.
19. A clean state skips the critic.
20. Critic patches: motion/prompt (guarded), dialogue, and lora (only with L1/L5-hard/L6/L7). beat.action and regeneration are removed.
21. Guard limit `max(1, units − max_actions)`.
22. `--judge` is report-only.
23. L2-L4 are advisory; L5 is split; L1/L6/L7 stay structural.
24. P13/N15 are advisory.
25. A no_stills speaking-panel prompt variant.
26. The merge gate is DLG21-DLG24 + DLG-H; the 24-case corpus is post-merge calibration; the live run is the KPI.

---

## 14. Open risks and questions

### 14.1 Risks

- **R1.** The acoustic sentence is the longest unquoted block, the pattern macstudio rejected. Mitigation: it comes last, has no speaker or lip words, and `beats-no-acoustic` and `plain` are flags. Only the A/B gives evidence.
- **R2.** "After a breath," followed by a quote may read to LTX as stage direction to voice. The A/B "unquoted word voiced" column measures this.
- **R3.** Chained stories with dialogue become one static close take (SP2 step 5; Q5).
- **R4.** The T-rule constants were calibrated on legacy outputs. DK7's rollback rule covers this.
- **R5.** Weaker enforcement means silent quality loss: S8 contact, N4, S9, P13/N15 and L2-L4 now render. Advisories are only as useful as the reader.
- **R6.** Naive sentence splitting ("Mr. Smith").
- **R7.** Engine and manifest seconds diverge only in manual manifest runs with other frame bounds.
- **R8.** Controller-test churn (Section 9.2 A). Do not weaken assertions beyond the stated reasons.
- **R9.** The manifest's 150-word "T5 may truncate at 256 tokens" warning is stale (Gemma tokenizes up to 1024 tokens) and will fire on long no_stills prompts. It is harmless but misleading; out of scope.
- **R10.** Quote-free Motion now rests only on writer instructions (CM7). Quoted words in Motion would be voiced, outside the T1 cap.
- **R11.** SP2's cast coercion drops other characters' identity sentences and, until Section 11, their LoRAs in speaking panels (SP2 side effects).

### 14.2 Resolutions recorded (design review)

- **Q1.** P13/N15 are advisory. Agreed, with fix 6: `plan_free_report` returns `(hard, advisory)` and `_undeclared_gate` warns only.
- **Q2.** The legacy `--story-legacy` shots rewrite loop (`_phase1_shots_finish`, `SHOTS_REWRITE_TEMPLATE`) **stays strict and unchanged**. D6 does not apply to `--story-legacy`.
- **Q3.** `--judge` is report-only, and `passed_only` is deleted.
- **Q4.** L2-L4 are advisory, and L5 is split: outside (0, 2] is hard-structural; outside the entry's range is advisory.

### 14.3 Open

- **Q5.** Chained beat-1 coercion (SP2 step 5). When any later beat speaks, the whole continuous take opens as a medium close-up or close-up with a static camera or a slow push-in. Assumed: keep it, so the speaking panel's inherited framing is close. Alternative: no beat-1 coercion, and only a P14 advisory (`"beat %d speaks, but the take opens as %s"`), which accepts that speaking panels in a wide take may not lip-sync.
