# Pinned cast presence: every `--character` is on screen

Date: 2026-10-27

Status: design spec. Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `0c0160d`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `0c0160d`.

Specs this one builds on, cited by tag:
- **[DLG]** `docs/superpowers/specs/2026-10-24-on-camera-dialogue-design.md`. It covers SP2 (the speaking-beat coercion, including its accepted side effects (i)-(v)), SP4 (pasted facing sentence) and the N16/N17 checks.
- **[NF]** `docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`. It covers QL7/QL8 (lines, `LINES_RULE`, the Q1 plan retry), SM1-SM3 (speaking shots and cameras) and GC1-GC3 (group cast).
- **[WP]** `docs/superpowers/specs/2026-10-26-writer-pacing-design.md`. It covers `SPEAKING_CHAINED_MOTION_SENTENCE` (WP2) and the speech-point contract (one sentence on each side of the line).
- **[CL]** `docs/superpowers/specs/2026-10-05-character-library-design.md`. It covers `--character`, `CastMember` and plan-based casting attachment.
- **[ENS]** `docs/superpowers/specs/2026-10-20-character-ensemble-design.md`. It records the two-LoRA identity blend (R3 below).

"Pinned member" means a plan cast entry whose `cast_name` is not `None`: a library character the user declared with `--character` (or picked in movie-ui). These are exactly `ctx.members`, normalised to ids `c1..cN` by `normalize_plan` (`story_engine.py:900-907`).

---

## 0. Purpose and scope

### 0.1 Problem

**User report (macstudio, no artifacts).** The user pins two library characters, either with `--character A --character B` or by picking two in movie-ui. Phase 1 then drops one of them: `story.md` and its panels feature only one.

**E1. Offline probe at `0c0160d` (this Mac).** The probe script was `.../scratchpad/probe/probe_p16.py`, run against the real `WS` with a temporary HOME and character library. Setup: members `kyra` (c1, "the woman in grey") and `ronin` (c2, "the ronin"), and a plan reply whose beats all have cast `["c1"]`.

| Mode | Beats' cast after `normalize_plan` | `plan_checks(...)[0]` (hard) |
|---|---|---|
| chained | `[['c1'], ['c1'], ['c1']]` | `[]` |
| chained, beat 2 `cast=["c1","c2"]`, `speaker="c1"` | `[['c1'], ['c1'], ['c1']]`. Note: `beat 2: P14 speaking beat: cast [c1, c2] changed to [c1] so the speaker is alone on screen` | `[]` |
| shots | `[['c1'], ['c1'], ['c1']]` | `[]` |
| shots, same speaking beat | the same, plus the shot note | `[]` |

`plan["cast"]` still lists c2, because `normalize_plan` re-inserts every pinned member (`:900-907`). So `plan.json` looks complete even though no beat shows c2. The writer only ever sees each beat's cast (`build_panel_prompt`, `:2449`).

### 0.2 Causes (each verified at `0c0160d`)

- **C1. Speaker coercion removes the other character.**
  - The planner is told a speaking beat "shows only that character (its cast is just their id)". This is `SPEAKER_RULE`, `:348-354`.
  - It is also told "Give each line its own beat whenever there are at least as many beats as lines". This is `LINES_RULE`, `:357-363`.
  - `speaking_coercion` (`:1110-1133`; cast at `:1119-1122`) then forces `cast = [speaker]` in every mode. That includes chained `k >= 2`, where the other character is physically still in the continued frame ([DLG] SP2 (iv)).
  - If A has every line, B is removed from every speaking beat. Only the advisory P14 note records it.
- **C2. The fixed-cast block does not require presence and omits the library name.**
  - `@@CAST_FIXED@@` (`:743-749`) gives id, phrase and descriptor only. A narrative that names "Kyra" leaves the model to guess which entry she is, so it may invent c3 or leave c2 unused.
  - Nothing says every listed character must appear.
- **C3. The seed paragraph pushes omission.** `SEED_PARAGRAPH` (`:333-337`) says "invent no person who is not visible". With a one-person seed image, a pinned character who is not in the image reads as an invention.
- **C4. The chained panel-1 Image is built from beat 1's cast only.** See `pasted_pieces`, `:1271-1277`. A late entrance is only the advisory P12 (`:1445-1450`).

**Guards that do not catch it:**
- `plan_checks` (`:1313-1480`) has no presence rule.
- `bin/ltx-movie:1636-1645` "story.md does not use cast phrase" is advisory, and it searches the whole file:
  - the logline can hide the omission;
  - in shots mode the `## Characters` roster (`story_engine.assemble`, `:1957-1959`) lists every plan cast entry, so the warning never fires.
- `bin/ltx-story-manifest:875-879` "occurs in no panel's ... text" is a WARNING only, and the manifest never runs under `--story-only`. movie-ui's story and regenerate actions pass `--story-only` (`movie_ui_lib.py:1012`).
- The casting exit-2 path `bin/ltx-movie:881-887` only applies to an existing story.md, and it searches the whole file.

**Ruled out:**
- The crowd classifier: `is_group_entry` returns False whenever `cast_name` is set (`:1143`).
- The critic: it cannot edit `beat.cast`, because its patch targets are `beat.action/shot/camera`, `location.setting` and panel fields (`:2731-2740`).
- Overlapping phrases, the manifest LoRA path, and movie-ui argv.

### 0.3 Grounding (verified at 0c0160d)

**`story_engine.py` (3705 lines, stdlib only)**
- `PLAN_MAX_CALLS = 2` `:65`; `MAX_CAST` `:64` (chained 4, no_stills 4, shots 2).
- `PLAN_PROMPT_TEMPLATE` `:276-317`; `SEED_PARAGRAPH` `:333-337`; `MODE_RULES` `:338-347`; `SPEAKER_RULE` `:348-354`; `SILENT_SPEAKER_RULE` `:355`; `LINES_RULE` `:357-363`.
- `build_plan_prompt` `:734-776`. The fixed-cast block is `:743-749`, and the fragments are `:761-775`, among them `@@SEED_PARAGRAPH@@` `:763`, `@@SPEAKER_RULE@@` `:771` and `@@LINES_RULE@@` `:773`.
- Plan normalisation:
  - `normalize_plan` `:882-957`, with its pinned re-insert at `:900-907`;
  - `coerce_speakers` `:966-1050`; `assign_missing_lines` `:1063-1107`, which only uses beats with a speaker or exactly one cast member, so it never changes a beat's cast membership;
  - `speaking_coercion` `:1110-1133`; `is_group_entry` `:1136-1160`.
- `pasted_pieces` `:1260-1283`; `plan_checks` `:1313-1480`, with P12 at `:1445-1450` and the line `undeclared = undeclared_characters(ctx)` at `:1451`.
- Writer prompt pieces:
  - `SPEAKING_ACTION_SENTENCE` `:1761-1765` and `SPEAKING_CHAINED_MOTION_SENTENCE` `:1769-1780`;
  - `SPEAKING_IMAGE_SENTENCE` `:1783-1784`; `SPEAKING_SENTENCES` `:1785-1786`.
- `_field_checks` `:2040-2296`:
  - N4 stray cast;
  - N17 starts at `:2245`, and its "also shows" list is at `:2264-2268`;
  - N19 cast reference is advisory and chained-only.
- `build_panel_prompt` `:2435-2512`. It contains the cast phrases `:2449`, `speaks`/`phrase` `:2458-2459`, the speaking-sentence append `:2479-2481` and the token replace `:2484-2486`.
- The run:
  - `_Run.plan_round` `:3183-3214`. It retries while `plan_checks` hard, `lora_checks` hard or `line_assignment_problems` is non-empty, appending "YOUR PREVIOUS REPLY WAS REJECTED. Problems: ...";
  - `_Run.go`, whose fatal filter `("P1", "P2")` is at `:3407-3417` (exit 1);
  - `assign_missing_lines` is called at `:3419`;
  - `recheck` `:3616-3705` never calls `plan_checks`.

**`bin/ltx-movie`**
- `_resolve_casting` `:834`, which rejects `--character` with `--no-stills` (`:847`);
- the existing-story phrase check `:881-887`;
- `--shots` + `--seed-image` is rejected at `:1086-1090`;
- the Phase 1 dispatch and the advisory cast-phrase warning are at `:1610-1645`.

**`bin/ltx-story-manifest`**
- `_plan_cast_names` `:445`.
- Chained panels attach every plan-cast member's LoRA and prefix the trigger when Motion does not name them (`:862-872`).
- Shots panels attach from Motion plus Image text (`:858-860`).
- The WARNING is at `:875-879`.

**`bin/iterate-story`** `:270-272` regenerates with `--character` from `plan.json` cast entries.

**Tests at 0c0160d:**
- `test_story_engine.py::test_rst53` `:2419` (shots, two characters; happy path only);
- `test_dialogue.py::test_dlg11` `:580` (shots coercion with *invented* characters);
- `test_narrative_fidelity.py::test_nf16` `:338` (coercion table; its chained part is uncast);
- `test_story_engine.py::test_rst8` `:216` (plan prompt matrix; it pins the fixed-cast line format at `:246-248`).

**Measured with a scratch copy of `WS` at `.../scratchpad/pcp/`**, running `test_story_engine`, `test_dialogue`, `test_narrative_fidelity`, `test_writer_pacing`, `test_shots_mode`, `test_casting_regression`, `test_casting_pipeline` and `test_iterate_story`:
- A probe adding a P16-style hard check plus the fatal-id change broke no existing test.
- A scratch implementation of PC1-PC9 exactly as Section 2 writes them (`.../scratchpad/probe/apply_spec.py`) compiled under 3.9 and 3.13. Those suites, plus `test_ltx_story_manifest_chain` and `test_character_lib`, gave 447 passed and 3 failed: `test_rst8` (the line format, 4.3 A) and the two pre-existing failures below. `test_dlg11` and `test_nf16` stayed green.
- On that scratch implementation, the PT16 scenario gave rc 0, stages `plan, panel, panel, panel`, zero hard and zero advisory messages, and plan beats `[['c1', 'c2']] * 3`. The PT6, PT8, PT10, PT11 and PT13 expected values in Section 4.1 were read off that run.

**Pre-existing failures on this Mac at `0c0160d`** (real `WS`, not caused by this work):
- `test_story_engine.py::test_rst62_import_sets` fails on `bin/ltx-mlx-render`.
- `test_rst48_judge_story_patches` fails, as do the judge-story, judge-clips and judge-stills run tests. The installed `anthropic` SDK raises `'Usage' object has no attribute 'output_tokens_details'`.

They must fail identically after the change and must not grow.

### 0.4 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | PC1-PC9 (Section 2) |
| G2 | `tests/test_pinned_cast.py` (new) | PT1-PT18 (Section 4.1) |
| G3 | `tests/fixtures/pinned_cast/` (new) | three byte-exact uncast plan prompts generated at `0c0160d` before any edit (4.2) |
| G4 | existing tests | only the edits of Section 4.3 A |
| G5 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit** |

**Not changed:**
- `character_lib.py` (`insert_speech`, `speech_text`, `phrase_occurs`, `member_referenced`, `shots_violations`).
- `bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/judge-story`, `bin/iterate-story`, `movie_ui_lib.py`, `static/*`.
- `pasted_pieces`, `panel_fields`, `assemble`, `recheck`, `RECHECK_IDS`, `GENERATION_CHECKS`, `NON_BLOCKING_IDS`, `REPAIR_IDS`.
- Every check except P16 (new) and N17 (PC9). The critic and `apply_patches`.
- `SPEAKER_RULE`, `LINES_RULE`, `SEED_PARAGRAPH`, `SPEAKING_IMAGE_SENTENCE` and `SPEAKING_CHAINED_MOTION_SENTENCE` keep their exact text. New constants are added beside them.
- `--story-legacy` and `build_cast_block`.

### 0.5 Out of scope

- **Requiring a pinned member in beat 1** of a chained movie (C4). Late entrance stays the advisory P12 (D6).
- **A hard post-writer presence check**: a story.md text check, or promoting N19, `bin/ltx-movie:1636-1645` or the manifest WARNING (D4).
- **Re-checking old stories for presence** (Section 3, back-compat).
- **Keeping invented (non-library) co-stars** in chained speaking beats (D3).
- A pre-flight feasibility error for shots runs that cannot fit every pinned member (R4).
- Two-character LoRA blending (R3; [ENS]).
- Lip-sync attribution in render, beyond the recorded live observation.
- The pre-existing duplicate-identity case, where a seed image shows a pinned character and the planner also invents an entry for them.

### 0.6 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| PK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the pass count recorded just before implementation plus every PT test, with no lost pass. The 0.3 pre-existing failures are unchanged in number and message. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Both are measured after the G5 commit. | full run |
| PK2 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`. | `test_rst61` |
| PK3 | `story_engine.py` gains no import (`git diff` shows no `import` line change). | review, `test_rst62` (fails before and after on `bin/ltx-mlx-render` only) |
| PK4 | **Hard presence, 100% offline.** For every mode (chained, shots, no_stills) × narration (`True`, `"speech"`, `False`) × missing set (`{c1}`, `{c2}`, `{c1, c2}`), a normalised plan in which those pinned members are in no beat's cast gives exactly one P16 hard message per missing member, in cast order. A plan with every pinned member in some beat, and an uncast plan, give zero P16. | PT6, PT7 |
| PK5 | **Retry, then fatal.** A first plan reply missing a pinned member, followed by a corrected reply, ends with rc 0 after exactly 2 plan calls. The second call's prompt lists the P16 message. Two missing replies end with rc 1 and the exact existing fatal-plan stderr, with no panel call and no story.md. | PT14, PT15 |
| PK6 | **Planner contract.** With members, the plan prompt carries `CAST_FIXED_INTRO` and the name-bearing lines. In chained mode with members it carries `SPEAKER_RULE_KEEP_CAST` instead of `SPEAKER_RULE`. In shots and no_stills with members and lines, it carries `LINES_PINNED_SENTENCE`. With a seed image and members, it carries `SEED_CAST_SENTENCE`. Uncast plan prompts are byte-identical to `0c0160d`. | PT2-PT5 |
| PK7 | **Chained keeps pinned silent co-stars; shots coercion is unchanged.** `test_dlg11` and `test_nf16` pass unedited. | PT8-PT10 |
| PK8 | **Speech stays with the speaker only.** The writer is told who is silent. The composed motion prompt names only the speaker as saying the line. N17 does not flag a chained pinned co-star. | PT11-PT13, PT16 |
| PK9 | **Old stories are unchanged.** Re-check of an existing story whose `plan.json` has a pinned member in no beat gives the same rc and `story_checks.json` messages as at `0c0160d`. Writer-pacing WT8/WT9, `test_rst40`, `test_rst41`, `test_casting_regression.py` pass. | PT17, existing |
| PK10 | **Live, this Mac, post-merge, not a merge gate (Section 5).** Every gating story-only run exits 0. In each, both `kyra` and `ronin` are in at least one beat's cast in `plan.json`, and each pinned phrase occurs in at least one `## Panel` section's Image, Motion or Prompt text, which excludes the logline and the `## Characters` roster. Every `Dialogue:` is spoken by the woman in grey. | Section 5 |

### 0.7 Must-have and nice-to-have

PC1-PC9 and the tests (Section 4) are must-haves. Nothing else is built: no new CLI flag, no new check besides P16, no change to the manifest, ltx-movie or movie-ui, and no deterministic repair of the plan.

---

## 1. Design decisions

### D1. P16 "cast presence" is a hard plan check, retried by the plan call and fatal when retries run out **[spec choice]**

**Rule.** After normalisation and speaker coercion (that is, on the plan `plan_checks` already receives), every pinned member's id appears in the `cast` of at least one beat. If one does not, a hard `plan: P16 cast presence: ...` message is reported for each missing member.

**Where it lives: `plan_checks`, hard.**
- `plan_round` (`:3203-3207`) already retries any `plan_checks` hard message with the existing "YOUR PREVIOUS REPLY WAS REJECTED" feedback. So adding P16 to the hard list reuses the planner repair mechanism with no new code, and `PLAN_MAX_CALLS` stays 2.
- It is checked after `coerce_speakers`, because `normalize_plan` runs coercion (`:951`) before `plan_checks` sees the plan. A member the coercion removed is therefore correctly reported as absent.
- `assign_missing_lines` (`:3419`, after the plan round) never changes cast membership (0.3), so a plan that passes P16 keeps passing.
- The critic cannot edit `beat.cast` (0.2). So in `make_state`, which runs `plan_checks` every round, P16 never fires on an accepted plan.

**Exhaustion: fatal, exit 1, the existing message.** `"P16"` joins the fatal ids in `_Run.go` (`:3407`), next to P1 and P2. Two missing replies therefore print exactly the existing three-part fatal error:
```
Error: the story model did not return a usable plan after 2 call(s)
  - plan: P16 cast presence: c2 'the ronin' (library character ronin) is in no beat's cast; ...
Raw replies are kept in <story_dir>/story_rounds/round_0. Rerun the same command to try again.
```
The run exits 1, as P1/P2 do (`test_rst10`, `test_rst11`).

**Rejected: let a P16 plan through and block at the end (exit 2).** Non-fatal plan hard messages (P3, L*) continue into the panels. P16 would then survive every critic round unchanged, because the critic cannot fix cast, and that would waste the whole panel and critic budget. The exit-2 text then says "Hand-edit story.md ... rerun", but the defect is in `plan.json` beats, which a story.md edit cannot fix.

**Rejected: deterministic repair** (insert the missing member into some beat). Which beat a character belongs in is a narrative decision, and the planner owns it. The user approved hard plus retry.

**Rejected: a plan-only problem list like `line_assignment_problems`** (retries, never in a state). When retries run out it would let the defect through, which is the reported bug.

### D2. The fixed-cast block names each character and requires presence **[spec choice]**

- Each fixed line carries the library name: `- id c1, name "kyra", phrase "...", descriptor "..."`. The intro then states two things: every listed character is in the movie with its id in at least one beat's cast, and a narrative name means that character, whom the movie names by phrase only (PC3).
- Library names are `NAME_RE` slugs (`character_lib.py:30`, for example `kyra`). The narrative's "Kyra" maps to it case-insensitively, which the model handles.
- Phrases stay the only names used on screen. `PLAN_PROMPT_TEMPLATE` already says "the movie names them by this exact phrase everywhere".
- Undeclared library characters keep their "Never use these names" sentence, which comes before the block (`:740-742`).

### D3. Speaker coercion: chained keeps pinned co-stars silent; shots and no_stills are unchanged **[spec choice]**

**Chained (all k, including k=1).** A speaking beat's cast becomes:
- the speaker;
- every pinned member the beat already listed, in the beat's order with duplicates removed. If the speaker was not listed, it goes first.

Invented (non-library) characters are still removed, as today.
- **Why pinned members stay.** Chained mode is one continuous take, so a character in the previous frame is physically still there ([DLG] SP2 (iv)). Removing them only removes their identity sentence (k=1) and their LoRA attachment ([DLG] SP2 (ii)), so their look drifts while they stay in frame.
- **Why only pinned members.** The user's instruction is about the declared characters. Widening the rule to invented characters would change every chained speaking plan and the `test_dlg11`-style expectations, which is beyond the approved scope.
- **What the planner is told.** In chained mode with members, `SPEAKER_RULE_KEEP_CAST` replaces `SPEAKER_RULE` (PC5): a speaking beat's cast is the speaker plus every already-cast character still in frame, who stays silent, and no character of the planner's own.
- **What the writer is told** (PC8):
  - On a chained speaking panel with silent co-stars, the Motion key line ends with `SILENT_CAST_MOTION_SENTENCE`. It names them as silent, says only the speaker speaks, and puts their mentions only inside the sentences that begin with the speaker's phrase.
  - That keeps [WP]'s speech point intact. `insert_speech(first_action=True)` places the line after the first action sentence (`character_lib.py:731-740`). Under [WP] WP2 that sentence begins with the speaker, and nothing about anyone else comes before it.
  - On chained panel 1, the Image key line uses `SPEAKING_IMAGE_SILENT_SENTENCE` instead of "the only person in the foreground".
- **Speech attribution.** It is unchanged and stays single-speaker:
  - `Dialogue:` is `"<speaker phrase>: <line>"` (`panel_fields`).
  - The manifest composes `speech_text(speaker, ...)` with `[speaker]` only (`bin/ltx-story-manifest:828-832`).
  - The P14 note names the silent members.
- **Shot coercion (chained k=1 only, where shots are coerced).** With silent co-stars, a shot wider than the speaking set becomes `"medium shot"` rather than `"medium close-up"`, so both fit in panel 1's still. An extreme close-up also becomes a medium shot when co-stars share the beat. Shots already inside `SPEAKING_SHOTS` are kept.
- **N17.** Its "a speaking shot shows only the speaker" advisory no longer counts chained pinned co-stars (PC9). Otherwise it would fire on every such panel by design.

**Shots and no_stills: coercion stays as it is.**
- Every shot follows a cut and starts from its own still. A single-person speaking close-up followed by a separate shot of the other character is normal shot/reverse-shot grammar, which the T1 split instruction already recommends ("the speaker, then the listener, then the speaker again").
- Two library LoRAs in one medium close-up raise the identity-blend risk ([ENS] 0.1) and compete for the lip-sync. The SM1 shot coercion forces that tight framing.
- D1 then forces a non-speaking beat for the other member. The P16 message in these modes says so (PC1 suffix), because the planner cannot see the coercion's P14 notes in the retry feedback; the feedback lists hard problems only.

**LINES_RULE interaction.**
- *Chained:* no change. A pinned non-speaker can share the speaker's beats, so "each line its own beat" never leaves them out.
- *Shots and no_stills* with members and spoken lines: `LINES_PINNED_SENTENCE` follows `LINES_RULE` (PC6). An already-cast character who says none of the lines needs a beat with no speaker, even when two consecutive lines must then share a beat. The existing word cap on shared lines still applies.
- If the lines cannot share a beat and every beat must speak, the plan is infeasible. That is R4, which fails at P16 with exit 1.
- no_stills cannot take `--character` through `bin/ltx-movie` (`:847`). The rule is still mode-generic in the engine.

### D4. No hard post-writer check; the seed paragraph gets a one-sentence carve-out **[spec choice]**

**Post-writer presence stays advisory.** Once D1 holds, the writer-side text already carries each pinned member, deterministically, except in one case:
- *shots:* every beat's Image pastes each cast member's identity sentence (`pasted_pieces`, `:1270-1283`), which contains their phrase. The manifest attaches LoRAs from Image text (`bin/ltx-story-manifest:858-860`).
- *chained k=1:* the Image pastes the identity sentence of every beat-1 cast member. D3 keeps pinned co-stars there.
- *chained k >= 2:* the manifest attaches every plan-cast member's LoRA and prefixes the trigger even when Motion does not name them (`:862-872`). N19 (advisory) already reports a pinned beat member whom the writer never names. **This is the only writer-dependent case.**

A hard story-text check would add a new blocking id with `REPAIR_IDS` and critic wiring. It would also fire on pronoun references, which N19 deliberately keeps advisory, for a residual case the plan attachment already covers. It is rejected. The `bin/ltx-movie:1636-1645` and manifest warnings stay as they are (0.5).

**The seed paragraph gets `SEED_CAST_SENTENCE` when the movie has members** (PC4). "Invent no person who is not visible" directly contradicts a pinned character who is not in the seed image, and D1 would otherwise turn that contradiction into retries. The fix is one sentence, conditional on members, and it leaves uncast seed prompts byte-identical. The chained `MODE_PARAGRAPHS` text already tells the planner how such a character arrives: "through visible movement inside a beat".

### D5. Message ids and names **[spec choice]**

- The new check is `P16`, named `cast presence`. P1-P15 are taken in `story_engine.py`. `_VIOLATION_RE` (`:102`) parses `plan: P16 cast presence: ...` with scope `plan`.
- New constants are named `CAST_FIXED_INTRO`, `CAST_FIXED_LINE`, `SEED_CAST_SENTENCE`, `SPEAKER_RULE_KEEP_CAST`, `LINES_PINNED_SENTENCE`, `SPEAKING_IMAGE_SILENT_SENTENCE` and `SILENT_CAST_MOTION_SENTENCE`. The new helper is `_and_list`.

### D6. Late entrance (C4) is left alone **[spec choice]**

- A chained narrative may legitimately bring a character in later "through visible movement". Forcing every pinned member into beat 1 would rewrite such stories.
- After D1 and D3, a late-entering pinned member is still in a beat's cast. Their LoRA and trigger attach from the plan (`:862-872`). P12 stays advisory.

---

## 2. Requirements (normative)

### PC1. P16 in `plan_checks` (`story_engine.py`)

Insert this block immediately before `undeclared = undeclared_characters(ctx)` (`:1451`):

```python
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
```

- The block reads `beats = plan["beats"]` (already bound at `:1320`). Messages follow `plan["cast"]` order.
- The `plan_checks` docstring sentence "Hard: P1, P2 and P3's normalize and duplicate-phrase messages; every other P message is advisory (dialogue spec 6.3)." becomes "Hard: P1, P2, P3's normalize and duplicate-phrase messages, and P16 (a library character in no beat's cast; pinned cast presence spec PC1); every other P message is advisory (dialogue spec 6.3)."
- Nothing else in `plan_checks` changes.

### PC2. P16 is fatal after the plan retries (`story_engine.py:3407`)

`("P1", "P2")` becomes `("P1", "P2", "P16")`, with the comment `# Pinned cast presence spec PC2: a plan that drops a library character is not usable.` on the line above `fatal = (...)`. Nothing else in `go()` changes. The error lines, `finish(1)` and the kept `story_rounds/round_0` are the existing ones.

### PC3. The fixed-cast block (`story_engine.py`)

Add these two constants immediately before `def build_plan_prompt` (`:734`), with the comment `# Pinned cast presence spec PC3, D2: the declared characters, by library name, all on screen.`:

```python
CAST_FIXED_INTRO = (" The following characters are already cast; list them first in cast with "
                    "exactly these ids, phrases and descriptors, and give your own characters "
                    "the next ids. Every one of them is in this movie: put each one's id in the "
                    "cast of at least one beat. When the narrative calls one of them by their "
                    "name, it means that character, whom the movie names only by their phrase:")
CAST_FIXED_LINE = '\n- id c%d, name "%s", phrase "%s", descriptor "%s"'
```

Lines `:743-749` become:

```python
    if ctx.members:
        cast_fixed += CAST_FIXED_INTRO
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += CAST_FIXED_LINE % (i, member.name, member.phrase, member.descriptor)
```

### PC4. The seed carve-out (`story_engine.py`)

Add this immediately after `SEED_PARAGRAPH` (`:337`):

```python
# Pinned cast presence spec PC4, D4: a declared character the seed image does not show is not
# an invention.
SEED_CAST_SENTENCE = (" The already-cast characters listed below are not invented: each of them "
                      "is in this movie even when the image does not show them.")
```

In `build_plan_prompt`, immediately before `fragments = [` (`:761`), add:

```python
    seed = ""
    if ctx.seed_agent_image:
        seed = (SEED_PARAGRAPH[:-2] + SEED_CAST_SENTENCE + "\n\n" if ctx.members
                else SEED_PARAGRAPH)
```

The fragment `("@@SEED_PARAGRAPH@@", SEED_PARAGRAPH if ctx.seed_agent_image else "")` becomes `("@@SEED_PARAGRAPH@@", seed)`. `SEED_PARAGRAPH[:-2]` drops its trailing `"\n\n"`, so the sentence follows "...the exact scene it shows." on the same line.

### PC5. The chained speaker rule with members (`story_engine.py`)

Add this immediately after `SILENT_SPEAKER_RULE` (`:355`):

```python
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

The `@@SPEAKER_RULE@@` fragment (`:771`) becomes:

```python
        ("@@SPEAKER_RULE@@", SILENT_SPEAKER_RULE if ctx.narration is False
         else SPEAKER_RULE_KEEP_CAST if ctx.mode == "chained" and ctx.members else SPEAKER_RULE),
```

### PC6. The lines rule with members in shots and no_stills (`story_engine.py`)

Add this immediately after `LINES_RULE` (`:363`):

```python
# Pinned cast presence spec PC6, D3: where a speaking beat shows only the speaker, a declared
# character with no line needs a beat without a speaker.
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker, even when two consecutive lines must then share a beat.")
```

The `@@LINES_RULE@@` fragment (`:773`) becomes:

```python
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else ""))
         if lines else ""),
```

### PC7. `speaking_coercion` (`story_engine.py:1110-1133`)

Replace the function with:

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
        if beat["camera"] not in SPEAKING_CAMERAS:
            notes.append("beat %d: P14 speaking beat: camera %s changed to 'static' so the "
                         "speaker's face stays readable" % (k, _q(beat["camera"])))
            beat["camera"] = "static"
    return notes
```

**Equivalence.** When `ctx.mode != "chained"` or the plan has no pinned member, `pinned` is empty. Then `cast == [speaker]` and `silent == []`, so every branch, note and value is byte-identical to `0c0160d`. That covers `test_dlg11`, `test_nf16`, NF13 and every shots and uncast plan.

### PC8. Writer prompt for a chained speaking panel with silent co-stars (`story_engine.py`)

Add these constants immediately after `SPEAKING_CHAINED_MOTION_SENTENCE` (`:1780`). The comment line before them is `# Pinned cast presence spec PC8, D3: a chained speaking panel's silent library co-stars (@@SILENT@@ is their quoted phrases).`

```python
SILENT_CAST_MOTION_SENTENCE = (" Also in frame in this panel, and silent: @@SILENT@@. Only "
                               "@@SPEAKER@@ speaks: mention each of the others by their referring "
                               "phrase, word for word, only inside the sentences that begin with "
                               "@@SPEAKER@@, and never give them a speaking verb.")
SPEAKING_IMAGE_SILENT_SENTENCE = (" @@SPEAKER@@ is in the foreground, facing the camera; also in "
                                  "frame, and silent: @@SILENT@@; any crowd stays in the "
                                  "background.")
```

Add this helper immediately before `def build_panel_prompt` (`:2435`):

```python
def _and_list(items):
    """'"a"', '"a" and "b"' or '"a", "b" and "c"' (pinned cast presence spec PC8); items is
    non-empty."""
    quoted = ['"%s"' % item for item in items]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]
```

In `build_panel_prompt`:
- Immediately after `phrase = speaker_phrase(plan, k) if speaks else None` (`:2459`), add:
  ```python
      silent = ([by_cast[c]["phrase"] for c in beat["cast"] if c != beat["speaker"] and c in by_cast]
                if speaks and ctx.mode == "chained" else [])
  ```
- `:2479-2481` become:
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
- `:2484-2486` become:
  ```python
          if speaks:
              line = (line.replace("@@SPEAKER@@", '"%s"' % phrase).replace("@@DWORDS@@", words)
                      .replace("@@LINE@@", '"%s"' % assigned)
                      .replace("@@SILENT@@", _and_list(silent) if silent else ""))
  ```

Nothing else in `build_panel_prompt` changes. With `silent == []`, every key line is byte-identical to `0c0160d`, because the `@@SILENT@@` replace is a no-op on lines without the token. The "Characters on screen in this panel" line (`:2449`) already lists every beat cast phrase, co-stars included.

### PC9. N17 does not count chained library co-stars (`story_engine.py:2264`)

```python
            others = [p for p in on_screen if p.lower() != speaker.lower()]
```

becomes

```python
            library = (set(c["phrase"].lower() for c in plan["cast"] if c.get("cast_name"))
                       if ctx.mode == "chained" else set())
            others = [p for p in on_screen if p.lower() != speaker.lower()
                      and p.lower() not in library]
```

The N17 branch is only reached with `beat is not None`, which implies `plan` is not None. The message text is unchanged. In shots and no_stills, and for invented co-stars, N17 behaves exactly as today.

---

## 3. Interactions (normative)

| Area | Behaviour after this change |
|---|---|
| Plan retry (`plan_round`) | P16 is one more hard problem in the existing feedback list. `PLAN_MAX_CALLS` is 2, unchanged. |
| Fatal plan exit | P16, P1 or P2 after the last call: exit 1, the existing three-part stderr, no panel call, and no `story.md` or `plan.json` written. A previous `story.md` is untouched (as in `test_rst10`). |
| `assign_missing_lines` | Unchanged. It never changes cast membership, so P16 stays satisfied. A beat it gives a speaker has exactly one cast member, so the coercion keeps that cast. |
| Critic, `apply_patches`, judge-story `--patches` | Unchanged. They cannot edit `beat.cast`. `CRITIC_SPEAKING_MOTION_CLAUSE` already asks for speaker-first sentences, so it agrees with PC8. |
| `make_state` (every round) | It runs `plan_checks`. P16 never fires on an accepted plan. |
| Re-check of an existing story.md (`recheck`) | **Unchanged.** It never calls `plan_checks`, so an old story whose `plan.json` has a pinned member in no beat re-checks and renders as before. Fixing such a story takes `--force-story`, or movie-ui "regenerate", which passes `--force-story` (`movie_ui_lib.py:1009`). |
| `bin/ltx-movie` existing-story casting check (`:881-887`) | Unchanged (whole-file phrase search). |
| Manifest (`bin/ltx-story-manifest`) | Unchanged code. A chained speaking panel with a kept co-star attaches the co-star's LoRA from the plan cast, which is the intended reversal of [DLG] SP2 side effect (ii). Speech is composed for the speaker only. |
| `plan.json` schema | Unchanged (`PLAN_SCHEMA`). Chained speaking beats may now list pinned co-stars after the speaker. |
| `bin/iterate-story` | Unchanged. Its `--character` regeneration now gets P16 enforcement. |
| movie-ui | Unchanged. Its story and regenerate jobs run Phase 1 with the same argv, so a P16 exhaustion is a failed job with the stderr above. |
| Uncast runs (all modes) | Plan prompts, coercion, writer prompts and checks are byte-identical (PT2 fixtures; PC7 and PC8 equivalence). |
| Shots with members | Plan prompt: `CAST_FIXED_INTRO` lines, plus `LINES_PINNED_SENTENCE` when the narrative quotes lines. Coercion and writer prompts are unchanged. |
| Chained with members | Plan prompt: `CAST_FIXED_INTRO` lines plus `SPEAKER_RULE_KEEP_CAST`. Coercion keeps pinned co-stars. Writer prompts gain the silent sentences only on panels that have co-stars. |
| `--no-narration` | `SILENT_SPEAKER_RULE` as today. There are no speakers, so there is no coercion and no silent sentences. P16 applies, without the speaker suffix. |
| `--story-legacy` | Unchanged; P16 is not applied. |
| P9, P10, P12, N4, N6, N19 | Unchanged rules. A chained speaking panel 1 with co-stars pastes more identity sentences, so P10 may fire more often (advisory). N19 reports a co-star the writer never names (advisory). |

---

## 4. Tests

### 4.1 New: `tests/test_pinned_cast.py`

The file follows the `tests/test_writer_pacing.py` conventions:
- stdlib plus pytest;
- `story_engine.py` and `character_lib.py` loaded by path with `importlib.machinery.SourceFileLoader`, under the names `story_engine_for_pinned` and `character_lib_for_pinned`;
- `bin/ltx-movie` loaded the way `test_story_engine.py` loads it (`ltx_movie`);
- the autouse `story_env` fixture (`seu.set_story_env`), the `ws` fixture (`seu.make_ws(tmp_path)`) and the `movie` fixture copied from `test_story_engine.py:2177-2183`.

No test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API. The module docstring states this, as test_writer_pacing.py's does.

**Helpers:**
- `KYRA = "the woman in grey"`, `RONIN = "the ronin"`.
- `_members(story_env)`: `seu.kyra(story_env["lib"]); seu.ronin(story_env["lib"])`, then `return lib.resolve_cast([(None, "kyra"), (None, "ronin")])`.
- `CAST2 = [{"id": "c1", "phrase": "x", "descriptor": "a woman"}, {"id": "c2", "phrase": "y", "descriptor": "a man"}]`. Normalisation replaces both with the members.
- `_raw(mode, n, casts, speakers=None)`: `seu.plan_json(mode, n, cast=copy.deepcopy(CAST2))`. Each beat `k` gets `cast = casts[k-1]`, and when `speakers` is given, `speaker = speakers[k-1]`.
- `LINES_NARRATIVE = 'At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks one step behind her. Near the top Kyra turns and says, "We reach the gate before dark." They pass under the gate together, and Kyra says, "Stay close to me."'`
- `P16(cid, phrase, name, mode, narration)` builds the PC1 message, with the suffix exactly when `mode != "chained" and narration is not False`.

| ID | Covers (exact assertions) |
|---|---|
| PT1 | **Constants.** `se.CAST_FIXED_INTRO`, `se.CAST_FIXED_LINE`, `se.SEED_CAST_SENTENCE`, `se.SPEAKER_RULE_KEEP_CAST`, `se.LINES_PINNED_SENTENCE`, `se.SILENT_CAST_MOTION_SENTENCE` and `se.SPEAKING_IMAGE_SILENT_SENTENCE` equal the Section 2 literals, written out in the test. `se.SPEAKER_RULE`, `se.LINES_RULE`, `se.SEED_PARAGRAPH`, `se.SPEAKING_IMAGE_SENTENCE` and `se.SPEAKING_CHAINED_MOTION_SENTENCE` equal their `0c0160d` literals, written out in the test. `re.findall(r"@@[A-Z_]+@@", s)` is a subset of `{"@@SPEAKER@@", "@@SILENT@@"}` for the two writer constants and is empty for the five plan constants. `se._and_list(["a"]) == '"a"'`, `se._and_list(["a", "b"]) == '"a" and "b"'` and `se._and_list(["a", "b", "c"]) == '"a", "b" and "c"'` |
| PT2 | **Plan prompt: fixed cast, and uncast byte-identity.** For `mode` in chained and shots, with `members=_members(story_env)`: the prompt contains `se.CAST_FIXED_INTRO + '\n- id c1, name "kyra", phrase "the woman in grey", descriptor "%s"' % seu.DESC_K + '\n- id c2, name "ronin", phrase "the ronin", descriptor "%s"' % seu.DESC_R`, and does not contain `'\n- id c1, phrase "'`. For each fixture in 4.2, rebuilding its ctx and calling `se.build_plan_prompt(ctx, [], [])` gives the fixture text byte for byte |
| PT3 | **Seed carve-out.** In chained mode with `seed_agent_image="/s/seed.png"`, members → the prompt contains `se.SEED_PARAGRAPH[:-2] + se.SEED_CAST_SENTENCE + "\n\n"`. Uncast → it contains `se.SEED_PARAGRAPH` and not `se.SEED_CAST_SENTENCE`. With members and no seed, `se.SEED_CAST_SENTENCE` is absent |
| PT4 | **Speaker rule variants.** Chained + members → the prompt contains `se.SPEAKER_RULE_KEEP_CAST` and not `se.SPEAKER_RULE`. Shots + members, and chained uncast → `se.SPEAKER_RULE` and not `se.SPEAKER_RULE_KEEP_CAST`. Chained + members + `narration=False` → `se.SILENT_SPEAKER_RULE` and neither of the others |
| PT5 | **Lines sentence variants**, with `narrative=LINES_NARRATIVE`. Shots + members → the prompt contains `se.LINES_RULE.replace("@@LINE_WORDS@@", cap) + se.LINES_PINNED_SENTENCE`, where `cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))`. The same holds for `mode="no_stills"` + members, built directly with `make_ctx`. Chained + members, and shots uncast → `se.LINES_PINNED_SENTENCE` is absent and the filled `LINES_RULE` is present. The default narrative (no quotes) gives neither |
| PT6 | **P16 matrix, the 100% KPI (PK4).** For `mode` in chained, shots and no_stills; `narration` in `True`, `"speech"` and `False`; and `missing` in `{"c1"}`, `{"c2"}` and `{"c1", "c2"}`: build `_raw(mode, 3, casts)` where each beat's cast is `[c for c in ("c1", "c2") if c not in missing]`, or `[]` when both are missing. Then `plan, shape = se.normalize_plan(ctx, raw)` and `hard = se.plan_checks(ctx, plan, shape)[0]`. `[m for m in hard if " P16 " in m]` equals `[P16(c, phrase, name, mode, narration) for each missing member in cast order]`, and `se.parse_violation(m)` gives `id == "P16"`, `name == "cast presence"`, `scope == "plan"`. The complementary plan (every beat `["c1", "c2"]` for chained, `["c1"], ["c2"], ["c1", "c2"]` for shots and no_stills) gives no P16 |
| PT7 | **P16 scope.** An uncast `seu.plan_json(mode, 3)` (c2 "the old monk" invented and in no beat) gives no P16 in any mode. With members, an invented c3 in no beat gives no P16. A single member (`--character kyra` only, `resolve_cast([(None, "kyra")])`) missing from every beat gives exactly one P16 |
| PT8 | **Chained coercion keeps library co-stars.** Chained ctx with members, 3 beats, speaker `c1` in beat 2, and beat 2 cast as listed: `["c1", "c2", "c3"]` (c3 invented, added to the raw cast as `{"id": "c3", "phrase": "the porter", "descriptor": "a man"}`) → `["c1", "c2"]`, with the note `"beat 2: P14 speaking beat: cast [c1, c2, c3] changed to [c1, c2]: the speaker, and the library character(s) c2, who stay in frame without speaking"`; `["c2", "c1"]` → unchanged, no cast note; `["c2"]` → `["c1", "c2"]` with the matching note; `["c1", "c1"]` → `["c1"]` with the existing "alone on screen" note; speaker `c3` with `["c1", "c2", "c3"]` → unchanged. In all five cases, `plan_checks` hard has no P16 and no P2 |
| PT9 | **Shots coercion is unchanged with members.** Shots ctx with members, beat 2 `cast=["c1", "c2"]`, `speaker="c1"`, the other beats `["c1"]`: beat 2 cast `["c1"]`, and the first speech note is `"beat 2: P14 speaking beat: cast [c1, c2] changed to [c1] so the speaker is alone on screen"`. The hard list holds `P16("c2", RONIN, "ronin", "shots", True)` with the suffix. With beat 3 `["c2"]` added, there is no P16. `test_dlg11` passes unedited (re-run in PK1) |
| PT10 | **Chained k=1 shot with co-stars.** Chained + members, beat 1 `speaker="c1"`, `cast=["c1", "c2"]`. For each `shot` in `("wide shot", "extreme wide shot", "extreme close-up")`, the coerced shot is `"medium shot"`. For `"medium close-up"`, `"close-up"` and `"medium shot"`, it is unchanged. With `cast=["c1"]` (no co-star), `"wide shot"` → `"medium close-up"` and `"extreme close-up"` → `"close-up"` (today). Beat 2 (k ≥ 2), `speaker="c1"`, `"wide shot"` → unchanged |
| PT11 | **Writer prompt.** Chained + members + `narration="speech"`. Plan: beat 1 `speaker="c1"`, `cast=["c1", "c2"]`; beat 2 `speaker="c1"`, `cast=["c1", "c2"]`; beat 3 `speaker=""`, `cast=["c1", "c2"]`. Use `parts = [se.empty_parts("chained", k, plan, ctx) for k in 1..3]`. The panel-1 line starting `"image: "` ends with `se.SPEECH_FRAMING_SENTENCE + se.SPEAKING_IMAGE_SILENT_SENTENCE.replace("@@SPEAKER@@", '"the woman in grey"').replace("@@SILENT@@", '"the ronin"')`. The panel-2 `"motion: "` line ends with `(se.SPEAKING_CHAINED_MOTION_SENTENCE + se.SILENT_CAST_MOTION_SENTENCE).replace("@@SPEAKER@@", '"the woman in grey"').replace("@@SILENT@@", '"the ronin"')`. Both prompts contain `'Characters on screen in this panel, named only by these exact referring phrases: "the woman in grey"; "the ronin"\n'`. Panel 3 contains neither silent constant. With beat 2 `cast=["c1"]`, the panel-2 motion line ends with `se.SPEAKING_CHAINED_MOTION_SENTENCE.replace("@@SPEAKER@@", '"the woman in grey"')` and contains no `"silent"`. No prompt contains `"@@"` |
| PT12 | **N17.** With PT11's plan, `se._field_checks(ctx, lib, plan, 2, "T", [("Motion", "The woman in grey steps toward the camera. The woman in grey faces the camera. The camera stays static."), ("Dialogue", "the woman in grey: Stay close to me.")], {"Motion": "The woman in grey steps toward the camera."}, ("N17",), [])` gives no message containing `"a speaking shot shows only the speaker"`. A shots ctx with members and a hand-set beat 2 cast `["c1", "c2"]` (coercion bypassed by editing the normalised plan) gives `["panel 2: N17 speaking shot: Dialogue: 'the woman in grey' speaks in a shot that also shows 'the ronin'; a speaking shot shows only the speaker"]`. `test_dialogue.py::test_n16_n17_n18_dialogue_messages` passes unedited |
| PT13 | **Speech stays with the speaker.** With `SAY = lib.speech_text(KYRA, "Stay close to me.", "beats")`: `lib.insert_speech("The woman in grey steps toward the camera as the ronin waits beside her. The woman in grey faces the camera. The camera stays static.", SAY, [KYRA], first_action=True)` equals `"The woman in grey steps toward the camera as the ronin waits beside her. The woman in grey faces the camera. " + SAY + " The camera stays static."`. With a second speaker sentence `"The woman in grey walks under the gate, the ronin a pace behind her."` after the first, `SAY` lands between the two speaker sentences. `"the ronin says"` occurs in neither output |
| PT14 | **E2E retry (PK5).** `movie` fixture; `seu.kyra`/`seu.ronin` in `story_env["lib"]`. Run `ltx_movie.main([NARRATIVE, "--story-id", "pc1", "--panels", "3", "--character", "kyra", "--character", "ronin", "--story-only", "--no-review"])` through `seu.script_agent` (as `test_story_engine._main_run`). Plan replies: `[answer(_raw("chained", 3, [["c1"]] * 3)), answer(_raw("chained", 3, [["c1"], ["c1", "c2"], ["c1", "c2"]]))]`; panel replies are `_panel_script`-style `seu.panel_json("chained", k, phrase=KYRA)`. Assertions: rc 0; the log stages start `["plan", "plan", "panel"]`; `log[1]["argv"][-1]` contains `"YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P16("c2", RONIN, "ronin", "chained", True) + "\n"`; `plan.json` beats 2 and 3 list c2; `story_checks.json` `hard == []` |
| PT15 | **E2E exhausted.** Engine level, as `test_story_engine.py::test_rst10` (`se.run(ctx)` with `seu.script_agent`, `capsys`). Ctx: chained, 3 panels, members, story id `pc2`. Both plan replies are `_raw("chained", 3, [["c1"]] * 3)`. Assertions: rc 1; the log stages are `["plan", "plan"]`; stderr equals `"Error: the story model did not return a usable plan after 2 call(s)\n  - " + P16("c2", RONIN, "ronin", "chained", True) + "\nRaw replies are kept in %s. Rerun the same command to try again.\n" % <story_dir>/story_rounds/round_0`; `story.md` and `plan.json` do not exist in the story dir |
| PT16 | **E2E two pinned, chained, every line spoken by c1 (the reported case).** Engine level, through `se.run(ctx)` with `seu.script_agent` as `test_narrative_fidelity._engine`. Ctx: chained, 3 panels, members, `narration="speech"`, `narrative=LINES_NARRATIVE`. The plan reply is `_raw("chained", 3, [["c1", "c2"]] * 3)` with beat 2 `speaker="c1"`, `lines=[1]`, and beat 3 `speaker="c1"`, `lines=[2]`. There is one panel reply per panel, with these exact values. Panel 1: `{"title": "The Temple Steps", "image": seu.panel_json("chained", 1, KYRA)["image"], "motion": "The woman in grey climbs the stone steps as the ronin follows one step behind her."}`. Panel 2: `{"title": "Near The Top", "motion": "The woman in grey turns and steps toward the camera, the ronin a pace behind her.", "dialogue": "We reach the gate before dark."}`. Panel 3: `{"title": "Through The Gate", "motion": "The woman in grey walks under the gate toward the camera, the ronin beside her.", "dialogue": "Stay close to me."}`. Assertions: rc 0; the log stages are `["plan", "panel", "panel", "panel"]` (a clean round 0 makes no critic call); `plan.json` beats 2 and 3 cast `["c1", "c2"]`; story.md panel 1 `Image:` contains `"The woman in grey is " + seu.DESC_K + "."` and `"The ronin is " + seu.DESC_R + "."`; the `Dialogue:` lines are `"the woman in grey: We reach the gate before dark."` and `"the woman in grey: Stay close to me."`; `story_checks.json` `hard == []` and no advisory contains `"a speaking shot shows only the speaker"`. If round 0 is not clean with these replies, the implementer stops and reports the message: it is a spec error, not a choice to make |
| PT17 | **Back-compat re-check (PK9).** After PT16's run, rewrite `plan.json` with every beat's cast set to `["c1"]`, so the ronin is in no beat, and monkeypatch `se.plan_checks` to raise `AssertionError("recheck must not call plan_checks")`. Then `rc, _adv = se.recheck(ctx, lambda path, panels, no_stills=False: [])` gives `rc == 0`, and no message in the rewritten `story_checks.json` contains `" P16 "` |
| PT18 | **Seed + two pinned, retried.** Engine level. Chained, members, `seed_agent_image="/s/seed.png"`; plan replies `[answer(_raw("chained", 3, [["c1"]] * 3)), answer(_raw("chained", 3, [["c1"], ["c1", "c2"], ["c1", "c2"]]))]`. Assertions: rc 0; `story_rounds/round_0/plan_prompt.txt` contains `se.SEED_CAST_SENTENCE`; both plan calls carry `--image /s/seed.png` in argv; the second carries the P16 message |

### 4.2 Fixtures: `tests/fixtures/pinned_cast/`

Generate these **at `0c0160d`, before any edit to `story_engine.py`**, with this script run from `WS` under a temporary HOME. They are byte-exact outputs of the unchanged `build_plan_prompt`.

```python
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
```

PT2 rebuilds each ctx with the same keyword arguments (the `LINES` text equals `LINES_NARRATIVE`) and compares the result byte for byte. `StoryContext` has the `narration` field at `0c0160d` (`:82-86`).

### 4.3 Existing tests that change

**A. Must be updated, only for the stated reason:**

| Test | Reason and exact edit |
|---|---|
| `tests/test_story_engine.py::test_rst8_plan_prompt_matrix` (`:246-248`) | PC3 line format. The two assertions become `('\n- id c1, name "kyra", phrase "the woman in grey", descriptor "%s"' % seu.DESC_K) in prompt` and `'\n- id c2, name "ronin", phrase "the ronin", descriptor "%s"' % seu.DESC_R in prompt`. Nothing else changes |
| `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (`:285`) | G5, in a separate test-only follow-up commit. `BASELINE` becomes the feature commit's SHA. The comment's last item, `..., then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing).`, becomes `..., then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to <sha> (pinned cast presence).` |

**B. Must pass unchanged** (the brief's question about `test_dlg11`: no change is needed, because it is shots mode with invented characters, and PC7 is byte-identical there):
- `test_dialogue.py`: `test_dlg11_speaking_beat_coercion`, `test_dlg13_writer_keys_and_speaking_key_lines`, `test_n16_n17_n18_dialogue_messages`, DLG15-DLG24.
- `test_narrative_fidelity.py`: `test_nf13`, `test_nf16`, `test_nf17` and NF28-NF35.
- `test_story_engine.py`: `test_rst10`, `test_rst11`, `test_rst13`, `test_rst40`, `test_rst41`, `test_rst51`-`test_rst54`, `test_rst61`.
- `test_writer_pacing.py` (all; WT8 and WT9 pin old-story composition and checks).
- `test_shots_mode.py`, `test_casting_regression.py`, `test_casting_pipeline.py`, `test_iterate_story.py`, `test_ltx_story_manifest_chain.py`, `test_character_lib.py`, `test_ltx_movie_offline.py`.

---

## 5. Live checks (PK10; this Mac only, post-merge, not a merge gate)

These are run by the user or the implementer on this Mac, never on macstudio, which the user checks themselves. They are story-only: no render is gating.

**Setup.**
- `S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`, `R=$S/pinned` (new, empty), `W=/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`.
- The story model is the vllm-metal `qwen38-6bit` server on port 8177, started exactly as `start_llm` in `$S/hockey/rerun/run.sh`. Stop it with `bin/story-server stop` after the last run.
- The characters are this Mac's trained `kyra` ("the woman in grey") and `ronin` ("the ronin") in `generated/characters/`.
- `N` is `LINES_NARRATIVE` (4.1): two quoted lines, both Kyra's, and the ronin never speaks. This is the reported failure shape.

**Runs.** From `$W`, one after the other:

```
for id in pin-ch3-a pin-ch3-b; do bin/ltx-movie "$N" --panels 3 --story-id $id --character kyra --character ronin --speech-only --story-only --no-review --force-story > $R/run-$id.log 2>&1; echo "$id exit $?"; done
for id in pin-sh4-a pin-sh4-b; do bin/ltx-movie "$N" --panels 4 --shots --story-id $id --character kyra --character ronin --speech-only --story-only --no-review --force-story > $R/run-$id.log 2>&1; echo "$id exit $?"; done
bin/ltx-movie "$N" --panels 2 --shots --story-id pin-sh2 --character kyra --character ronin --speech-only --story-only --no-review --force-story > $R/run-pin-sh2.log 2>&1; echo "pin-sh2 exit $?"
```

**Measure.** Save this as `$R/measure.py` and run `W=$W python3 -I $R/measure.py pin-ch3-a pin-ch3-b pin-sh4-a pin-sh4-b pin-sh2 > $R/measure.txt`:

```python
import importlib.machinery, json, os, sys
W = os.environ["W"]
lib = importlib.machinery.SourceFileLoader("cl", os.path.join(W, "character_lib.py")).load_module()
man = importlib.machinery.SourceFileLoader("man", os.path.join(W, "bin", "ltx-story-manifest")).load_module()
for sid in sys.argv[1:]:
    d = os.path.join(W, "generated", "stories", sid)
    plan = json.load(open(os.path.join(d, "plan.json")))
    panels = man._parse_prompts_md(os.path.join(d, "story.md"))[1]
    for c in [c for c in plan["cast"] if c.get("cast_name")]:
        beats = [b["index"] for b in plan["beats"] if c["id"] in b["cast"]]
        shown = [k for k, p in enumerate(panels, 1)
                 if any(lib.phrase_occurs(p.get(f, ""), c["phrase"]) for f in ("image", "motion", "prompt"))]
        print(sid, c["id"], c["cast_name"], "beats", beats, "panels", shown)
    print(sid, "speakers", [p["dialogue"].split(":", 1)[0] for p in panels if p.get("dialogue", "").strip()])
    checks = json.load(open(os.path.join(d, "story_checks.json")))
    calls = json.load(open(os.path.join(d, "story_rounds", "run.json")))["calls"]
    print(sid, "hard", [h["id"] for h in checks["hard"]], "plan calls", len([c for c in calls if c["stage"] == "plan"]))
```

**Pass criteria (all must hold, for every run):**

| # | Criterion |
|---|---|
| a | The run exits 0, and its log shows Phase 1 completing with no `Error:` line. |
| b | In `measure.txt`, both `kyra` and `ronin` have a non-empty `beats` list and a non-empty `panels` list. `panels` counts only Image, Motion or Prompt text inside `## Panel` sections, never the logline or `## Characters`. |
| c | Every `speakers` entry is `the woman in grey`. |
| d | `hard` is `[]`. |
| e | Chained runs: no `story_checks.json` advisory contains `"a speaking shot shows only the speaker"`. Shots runs: the ronin's beats have no speaker in `plan.json`. |

**Recorded, not gating:**
- the plan-call count of each run, where 2 means P16 or another hard problem triggered a retry, and `plan_reply_1.txt` shows which;
- whether chained runs put the ronin in beat 1;
- any N19 or P12 advisories.

**Optional, recorded, not gating:**
- **Pre-change control.** Before the feature commit, run the `pin-ch3-a` and `pin-sh4-a` commands once at `0c0160d`, with ids `pin-ch3-base` and `pin-sh4-base`. Record `measure.txt`, which shows whether the defect reproduces locally.
- **Seed.** Only if this Mac's story server has served `--seed-image` runs before: `bin/ltx-movie "$N" --panels 3 --story-id pin-seed3 --seed-image generated/characters/kyra/seed.png --character kyra --character ronin --speech-only --story-only --no-review --force-story`. The same criteria a-e apply.
- **Render of `pin-ch3-a`.** Run `bin/ltx-movie "$N" --panels 3 --story-id pin-ch3-a --character kyra --character ronin --speech-only --model ~/ltx-2-mlx/models/ltx-2.3-mlx-q8-dev --no-review`. The story exists, so Phase 1 re-checks it. Make contact sheets and whisper transcripts as in [WP] Section 5. Record whether both people are visible in the speaking panels, whether whisper hears both lines, and whose mouth moves (R2), plus any identity blend (R3).

Put the exit codes, `measure.txt`, and the plan reply and prompt of any retried run in the PR or report.

---

## 6. Rollout

1. Take a compressed snapshot of the workspace before any edit (house rule): `tar czf $S/snapshot-pre-pinned-cast-0c0160d.tgz` of `WS`, excluding `generated/`.
2. Generate the 4.2 fixtures at `0c0160d`, and record the full-suite pass count and the 0.3 failure list.
3. Implement G1, G2, G3 and G4 in one feature commit.
4. Run PK1-PK9 and the full suite.
5. Opus design review of the diff against this spec.
6. Make the test-only follow-up commit G5 (`test_mut26`), then measure PK1.
7. Post-merge: the live PK10 runs (Section 5). Record the results.

PR note (required, in substance): "Phase 1 now refuses a plan that leaves out a `--character` (P16; retried once, then exit 1). In chained movies a library character stays in frame, silent, in another character's speaking beats. Existing stories re-check exactly as before; a story generated before this change that dropped a character must be regenerated with `--force-story` (movie-ui: Regenerate)."

---

## 7. Values chosen by the spec

1. **Presence.** P16 `cast presence` is a hard plan check after normalisation and coercion, retried by the existing plan feedback, and fatal (exit 1, the existing message) after `PLAN_MAX_CALLS` = 2. There is no deterministic repair (D1).
2. **Planner text.** Each fixed-cast line carries the library name, and the intro requires every listed id in at least one beat and maps narrative names to phrases (D2).
3. **Coercion.** Chained keeps pinned co-stars silent in speaking beats (all k). Invented co-stars are still removed. Shots and no_stills coercion is unchanged (D3).
4. **Chained k=1 framing.** With co-stars, a coerced shot becomes `medium shot` (D3).
5. **Planner rule variants.** `SPEAKER_RULE_KEEP_CAST` for chained with members. `LINES_PINNED_SENTENCE` for shots and no_stills with members and lines (D3).
6. **Writer text.** `SILENT_CAST_MOTION_SENTENCE` (chained Motion) and `SPEAKING_IMAGE_SILENT_SENTENCE` (chained panel-1 Image), only on panels that have co-stars. Speech attribution is unchanged (D3).
7. **N17** ignores chained pinned co-stars (D3).
8. **No hard post-writer check.** N19, P12 and the ltx-movie and manifest warnings stay advisory (D4, D6).
9. **The seed paragraph** gains one conditional sentence (D4).
10. **Old stories** are not re-checked for P16 (Section 3).

---

## 8. Risks and questions

### 8.1 Risks

- **R1. More plan retries and exit-1 runs.** A model that ignores the new block fails after two calls where it used to "succeed" with a character missing. That is intended, since the run used to produce the wrong movie, but it shows up as a failed job. PK10 records the retry count.
- **R2. A silent co-star's lips may move.** LTX sees two faces and one quoted line. The prompt attributes the line to the speaker only, and the co-star has no speaking verb. That is all this spec controls (0.5). The optional render records it.
- **R3. Two LoRAs in chained speaking panels.** Keeping the co-star attaches both character LoRAs where only one was attached before. [ENS] 0.1 records identity blending for fused pairs, which already affected chained non-speaking two-character panels. The optional render records it. An ensemble LoRA is the existing remedy, outside this spec.
- **R4. Infeasible shots plans.** Shots with spoken lines and fewer free beats than silent pinned members fails at P16 (exit 1). The worst case is 1 panel with a line and 2 members, or lines that cannot share a beat. The remedy is more `--panels`, or chained mode. A pre-flight error is out of scope.
- **R5. Prompt length.** The fixed-cast block grows by about 50 words, plus a name per member. The chained speaking Motion key line grows by about 35 words on co-star panels. Both are well inside the plan and panel budgets.
- **R6. The writer may still omit a co-star in a chained k ≥ 2 Motion.** The plan casting attaches their LoRA and trigger anyway, and N19 reports it. This is the accepted residual case of D4.

### 8.2 Decisions to confirm (the spec resolves each; flagged because each narrows or departs from the brief's wording)

- **C1.** P16 exhaustion is **fatal (exit 1)**, like P1 and P2, not a story-end hard failure (exit 2). The exit-2 path tells the user to hand-edit story.md, which cannot fix a plan's beat casts (D1).
- **C2.** Chained coercion keeps **only library characters**. Invented co-stars are still removed, so `test_dlg11`-style behaviour and every uncast plan are unchanged (D3).
- **C3.** Shots coercion is **unchanged**. The other character gets their own non-speaking beat, enforced by P16 and told by `LINES_PINNED_SENTENCE` (D3).
- **C4.** **Old stories are not re-checked** for presence. A previously generated story that dropped a character needs `--force-story` (Section 3).

### 8.3 Open

None.


## Amendment 2026-10-27 (final whole-branch review)

- **A1 (fixed).** `coerce_speakers` also resolves a speaker written as a pinned member's library name (`cast_name`, case-insensitive, surrounding space ignored) to that member's id, as it already did for the phrase. Reason: PC3 prints the library name beside each id and PC5 keeps co-stars in chained speaking beats, so the sole-member fallback that used to rescue a speaker such as "kyra" no longer fires and every line would be dropped. Beat-cast entries written as names stay a P2 error, unchanged. Test: `test_final_i1_speaker_given_by_library_name`.
- **A2 (known limit, not changed).** When both plan calls leave a quoted line unassigned, `assign_missing_lines` can give it to a one-member beat of a pinned character who has no line in the narrative (shots mode, where LINES_PINNED_SENTENCE asks for such beats). Pre-existing behaviour. PK10's shots runs record any `speech_notes` entry saying a line was given to a beat by the pipeline.
- **A3 (correction to Section 3).** "The critic cannot edit `beat.cast`" is inexact: a Q1 dialogue patch on a shots beat with no speaker sets the speaker from the patch's phrase, and speaker coercion then narrows that beat's cast, which can leave a pinned member in no beat (P16 then appears in that round's checks). This path dropped the member silently before this change; it is not changed here.
- **A4 (known limit).** Under `--speech-only` the chained beat-1 widening to "medium shot" applies only to shots wider than the ones offered, so a chained beat-1 close-up with a silent co-star stays a close-up (PT10 pins this). PK10 records the beat-1 shot of the chained runs.
- **A5 (2026-10-28, speaker attribution spec SA4).** A2 closed by speaker attribution spec SA4 for lines the narrative attributes; unattributed lines unchanged.
