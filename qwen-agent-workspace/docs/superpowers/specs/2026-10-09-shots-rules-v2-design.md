# Shots rules v2 -- Design Spec (contact, cast descriptions, extras, off-screen wording, setting sentences)

Date: 2026-10-09 (revised twice the same day after design review and a scoped re-review)
Status: The user approved the direction in the 2026-10-09 brief:
- three prompt changes (setting sentences, wind-up/reaction fights, no off-screen wording) plus a tightened cast-description rule;
- the restructuring rules become fatal validator rules enforced by the rewrite loop;
- an animal exemption for S7;
- one live gate on a new story.

**Revision 2 (design review rulings):**

- **F1:** two mitigations are in scope as code: an S9 auto-repair in Phase 1 and a second rewrite. Phase 1 trials (10.2a) and a hand-edited fallback render (L-R1b) are added to the gate.
- **F2:** an S8 spatial-word target filter.
- **F3:** S10 description blanking and an appositive-only class-noun skip.
- **F4:** the `--redo` consequence text in 4.1.
- **F5:** every new and changed test is a script-extractable code block, and the counts and mutation results below are measured with pytest.
- **F6:** a shorter L-R1 narrative, plus new handoff and take verbs.
- **M1-M5:** S12 minimum length, S11 synonyms, person-noun pruning, per-request timing in L-R1, and "test SX" wording.
- C1-C4 are accepted; C5 is superseded by the second rewrite.

**Revision 3 (scoped re-review rulings, all accepted):**

- **Important 1:** test S55 now pins the repair after a rewrite, and test S56 pins rewrite 2's timeout (mutation rows 67, 68).
- **Important 2:** a rewrite that fails after writing story.md (a timeout) moves that story.md aside too (5.3, E-S11), pinned by the new test S58 (row 69). 4.1 states the first-draft timeout case.
- **Important 3:** 10.3 records each repair and eyeballs repaired panels.
- **Minor 1:** the repair keeps a trailing carriage return (test S21, row 71).
- **Minor 2:** a story.md that Phase 1's call left unchanged is never repaired (5.3), pinned by the new test S59 (row 70).
- **Minors 3-6:** G-R18, G-R17, the 10.2a runbook and the audit-records note.

This document makes that direction implementable without reopening it. Every choice made while writing it is marked **[spec choice]**, and every reading of an ambiguous phrase is marked **[interpretation]**. Section 15 lists what remains for the user to confirm. None of it blocks implementation.

**How the numbers were produced.**

- Sections 3, 5 and 8 hold the complete reference code and tests. They were applied to a scratch copy of the workspace at HEAD `e85ed35`; the repository was not edited.
- Rebuilding the three files from this document's own blocks (by script) reproduces the 3.13, 5.5 and 8.5 sha256 values.
- With them, `python3 -m pytest tests/test_shots_mode.py --color=no` measured **81 passed**.
- Each of the 71 mutations in 8.6 was applied alone to that copy. Each was caught by the pytest file, and the failing tests are listed per row (71 of 71).
- Every count, message and projection in Sections 6-8 is that code's actual output.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Branch `qwen-agent-redteam`, HEAD `e85ed35`. This spec amends `docs/superpowers/specs/2026-10-06-shots-mode-design.md`, called **the shots spec** below, and uses its terms: **shots mode**, **cast**, **extra**, **roster** (the `## Characters` section), **rewrite**, and the rules **S1-S7** and **W1-W2**.

**ID convention (M5).** Rule IDs and test IDs share the "S" prefix, as in the shots spec. In this document a bare "S9" is always the **rule**, and "test S9" is always the **test**.

New terms:

- A **contact beat** is one shot in which one person acts physically on another: a blow, a grab, a push, a snatch, a hand-off, a taken hand, a helping hand.
- A **wind-up shot** shows only the person who acts. A **reaction shot** shows only the person acted on. The contact itself falls on the cut between them.
- A **setting sentence** is an `Image:` sentence of at least 12 words that starts with "The setting is". There is one per location, and it is copied word for word into every shot at that location.
- An **identity sentence** is `"<cast phrase, first letter capitalised> is <descriptor>."`, for example `The ronin is a lean man in his late thirties ... dark hakama.` (3.3).
- The **S9 repair** is the pipeline's insertion of a missing identity sentence into a story-model draft (3.11, 5.3).
- A **person reference** is one of the references defined in 4.5. A **distance cue** is a match of `_DISTANCE_CUE_RE` (3.2).

---

## 0. Purpose and scope

### 0.1 Purpose

Shots mode shipped with seven rules (S1-S7). The live runs since then show which story-model behaviours matter and which rules the model actually follows.

- **Contact beats render badly; split beats render well.** A beat shown as a wind-up shot, a hard cut and a reaction shot scores far higher than the same beat shown as two people in contact.
- **The model follows copy-this-sentence rules, but not restructuring rules.** It copies a sentence when told to. It ignores a rule that asks it to restructure the story (split a fight, repeat a description).

So v2:

- turns the restructuring rules into fatal validator rules (S8-S12);
- keeps the copyable rules in the prompt;
- takes the most mechanical rule, S9, off the model entirely with a deterministic repair;
- gives the model up to two rewrites, each with a grouped, copyable list of only the violations still present.

### 0.2 Grounding evidence

**Proven facts (from the brief and `.superpowers/sdd/2026-10-06-shots-mode/live/ls1-notes.md`; not re-litigated).**

- **Prompt length and the two-stage renderer are not levers.**
  - In the length A/Bs, Motion:-style prompts of 50-80 words (2 seeds x 2 judge passes) and 130-150 words (1 seed) raised motion fidelity by about +0.65 to +0.8. They cost realism (-0.6 to -0.9) and stability (-1.0 to -1.15).
  - The two-stage dev+CFG renderer took 2-3x the time and gave no win.
  - Motion: stays 10-25 words (S4 unchanged).
- **Wind-up/reaction works.** Story `ronin-shots-windup-20261008` split the full20 P7-10 contact beats into 6 one-person shots.
  - Judge means (2 passes each) for motion fidelity / physical realism / temporal stability went from 2.75 / 5.12 / 5.38 to 5.17 / 5.17 / 5.25.
  - Narrative clarity went from 3 to 4 in both passes.
  - Robber-only shots stayed in period.
- **Prose rules: copy-rules are followed, restructuring rules are not** (`ronin-shots-rules-20261009`, rules given as three prose paragraphs in `live/rules-prompt-20261009.txt`).
  - Followed: a setting sentence in 20/20 Image: fields, and "outside the frame"/"off-screen" in 0/20.
  - Ignored: the fight was split on 1 of about 4 contact beats, and the cast description was repeated word for word on 0 panels (22 W1 advisories plus 3 W2).
- **Rewrites regress.** Both earlier shots runs that needed a rewrite exited 2 (`ls1-notes.md` lines 2 and 18):
  - ls1 went from 7 violations to 2 after the rewrite;
  - full20 went from 2 to 1.
  - Each time, the rewrite fixed what was listed but introduced new violations, because the model rewrites the whole file.

  This is the basis for F1: repair S9 deterministically, and allow a second rewrite of only the remaining violations.
- **"just outside the frame" adds a foreground figure** (windup P2, P3 and P5).
- **Global LoRA fusion restyles human extras in cast shots.**
  - `ronin-shots-rules-20261009` P17/P18: the shogun rendered as the ronin's twin.
  - `ronin-rescue-shots-ls1` P9/P10: the woman and the robbers in a ronin shot.
- **S7 false positive on mounts.** S7 has flagged a rider together with her horse twice.
- **Baseline.** `ronin-shots-rules-20261009` judged over 2 passes: motion fidelity 5.05, physical realism 6.28, temporal stability 6.22, narrative clarity 4.

**Code facts (HEAD `e85ed35`).**

- **`character_lib.py`.**
  - 742 lines, sha256 `d952127b644600030e1398b76458bfe599aa53b8f11080b1388e7cda76e612d5`.
  - Imports `collections, datetime, json, os, re, uuid`; C41 and test S20 pin exactly this set.
  - Shots functions: `build_cast_block` (`:525-530`), `find_phrases` (`:533-550`), `parse_character_roster` (`:553-590`), `motion_problems` (`:593-614`), `shots_violations` (`:617-663`), `shots_advisories` (`:666-691`), `shots_rewrite_block` (`:694-701`).
  - `CastMember` carries `class_noun` ("woman" for kyra, "man" for ronin).
  - The brief's `parse_roster` is `parse_character_roster`.
- **`bin/ltx-movie`.**
  - 1826 lines, sha256 `b202a074dbb2752bfe7e811a1ec5c2fe3b92147c70920373adfff600c04d1429`.
  - `STORY_PROMPT_TEMPLATE_SHOTS` is at `:168-197` (642 words).
  - `_shots_check` (`:1107-1116`) and `_phase1_shots_finish` (`:1119-1185`):
    - validate;
    - on a draft written this run: move the draft aside, run **one** rewrite with `lib.shots_rewrite_block(violations, args.panels)` appended to the first prompt, and exit 2 if it still violates (E-S10).
  - The module imports `os`, `time`, `sys` and others, but **not `re`** (pin L7j), so every regex lives in `character_lib.py`.
- **`bin/ltx-story-manifest`.** `_PANEL_HEADER_RE = ^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$` and `_PANEL_LABEL_RE = ^(Image|Motion|Narration|Prompt|Style):\s*(.*)$` (`:100-101`).
  - A label line opens a field.
  - Every following non-blank unlabeled line is appended to the open field, space-joined (`:276-286`).
  - The S9 repair locates Image: fields in exactly this way (3.11).
- **`tests/test_shots_mode.py`.**
  - 1684 lines, **54 tests**; `54 passed`.
  - Free ID ranges: S21-S29, S54-S59, S67-S69, S73 and up.
  - `SHOTS_OK` has no setting sentence.
- **The windup story contains "outside the frame" three times** (P2, P3, P5): the wording blamed for the over-the-shoulder figure.
- **Stories as stored.**
  - `ronin-shots-full-20261007` and `ronin-rescue-shots-ls1` carry the documented hand-edits. ls1 also carries the L-S2 P2 edit.
  - `ronin-shots-rules-20261009` is the as-generated rules story plus 2 hand-edits (P2, P18 Motion).

**Baselines measured.**

| Suite | Result |
|---|---|
| `python3 -m pytest tests/test_shots_mode.py --color=no` | repo: `54 passed`; scratch with the v2 code and tests: **`81 passed`** |
| casting set (`test_casting_pipeline.py test_casting_regression.py test_character_lib.py test_character_dataset.py test_character_tool.py test_z_image_skill_multi_lora.py`) | repo: `178 passed`. Scratch with v2: `177 passed, 1 failed`. The failure is `test_d2_copied_literals_match_the_spike`, a scratch-copy artifact (the gitignored `generated/charlora/tools/make_dataset_seed.py` is absent); it fails identically without v2 |
| `python3 tests/test_ltx_movie_offline.py` (direct) | scratch with v2: `OK 344/344` |
| `python3 -m pytest tests/test_ltx_movie_iterate_flags.py` | scratch with v2: `13 passed` |
| `python3 -m pytest tests/test_deploy_pkg.py` / `/usr/bin/python3 -m unittest tests.test_deploy_pkg` | scratch with v2: `165 passed` / `Ran 165 tests … OK` |
| every other R1 suite | from the shots final acceptance (`progress.md` A4): `OK 101/101`, `OK 443/443`, `OK 146/146`, `OK 32/32`, `OK 77/77`, `RESULT: ok`, z_image cache `13`, pipeline_log `17`. Not re-measured here; Task 1 re-measures them |

### 0.3 Deliverables

| # | Item | File | Action |
|---|---|---|---|
| D1 | Rules S8-S12, the S7 animal exemption, W1 → S9, contact/person/animal helpers, the camera-sentence fold-in, identity sentences, the grouped rewrite block, `repair_cast_descriptions`, `SHOTS_MAX_REWRITES` | `character_lib.py` | edit (3.1-3.12) |
| D2 | The v2 shots story template; Phase 1 S9 repair and up to two rewrites | `bin/ltx-movie` | edit: `STORY_PROMPT_TEMPLATE_SHOTS` (5.1), the two-line `phase1_story` edit and the Phase 1 block (5.3) |
| D3 | Updated fixture, 8 updated tests, 27 new tests (S21, S54-S59, S80-S99) | `tests/test_shots_mode.py` | edit (Section 8) |
| D4 | The five corpus stories, byte copies | `tests/fixtures/shots_rules_v2/` (new dir, 5 files) | new (8.1) |
| D5 | A pointer paragraph in the shots spec's Status | `docs/superpowers/specs/2026-10-06-shots-mode-design.md` | edit (1.4) |

- **D4 [spec choice].** The corpus regression tests (S95, S96) must run on real model output, which lives under gitignored trees. `tests/fixtures/casting_baseline/` is the precedent.
- **D5 [spec choice].** It stops a reader of the shots spec from implementing W1 as an advisory, the old Cast rule Four, or the one-rewrite flow.
- **Unchanged:**
  - `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-mlx-render`;
  - `ltx2_mlx_video_skill.py`, `z_image_skill.py`, `bin/qwen-agent`;
  - the judges, `bin/iterate-story`;
  - the deploy tooling (not touched, so Apple-Python 3.9.6 compatibility is unaffected);
  - every other test file.

### 0.4 Out of scope (explicit)

- **`bin/judge-clips`' shots-mode prompt.** It still scores `seam_continuity` as "one continuous take" (shots spec G4). L-R1 records `seam_continuity` but does not compare it.
- **The two-stage renderer** (no win).
- **Prompt length.** Motion: stays 10-25 words, and the Image: 80-170-word budget is prompt-only.
- **Validating that one location reuses one setting sentence** (locations are not machine-identifiable; G-R8).
- **Verbatim descriptions for extras** (prompted, not validated or repaired).
- **Gender-aware possessive targets** (G-R1).
- **S7 for unlisted extras.**
- **`Narration:`.**
- **Grandfathering pre-v2 stories, a v1-rules escape flag, or `--redo`-scoped validation** (4.1).
- **An edit-mode rewrite that attaches the rejected draft.** The review measured about 6108 + 5000 + 1239 tokens against a 12552 budget.
- **A third rewrite.**
- **T2 minors 2, 3 and 4** (Section 14).
- **New CLI flags.** There are none.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC-R1 | `shots_violations` emits S8-S12 exactly as 4.3 defines, in the 4.3 order, alongside unchanged S1-S6 and the animal-exempt S7 | tests S14, S16, S85-S92 |
| SC-R2 | The detectors reproduce the corpus results of 7.1: windup 6, windup-v2 0, rules-as-generated 41, rules-edited 39, full20 52, ls1 25. After the S9 repair: 6, 0, 19, 17, 34, 23 | tests S95, S96 |
| SC-R3 | `repair_cast_descriptions` inserts identity sentences exactly as 3.11 defines. Phase 1 repairs only drafts written this run, keeps an untouched `story.pre-repair-*` copy, and validates and rewrites against the repaired text | tests S21, S54, S55, S59, S98 |
| SC-R4 | Phase 1 runs up to `SHOTS_MAX_REWRITES = 2` rewrites. Each lists only the current violations and reuses the same `cmd` and timeout. Drafts are moved aside without ever replacing one another. E-S10 means "still failing after 2 rewrites" | tests S36, S37, S39, S56, S57, S58 |
| SC-R5 | The shots Cast block carries identity sentences, and the template carries the setting / fights / screen-direction paragraphs, byte-exact | tests S3, S93, S97, S99 |
| SC-R6 | The rewrite block groups by rule and merges identical details; the cap stays at 40 listed lines | tests S94, S96, S98 |
| SC-R7 | W1 is no longer an advisory; W2 is unchanged and non-fatal | tests S18, S40, S86 |
| SC-R8 | The three edited files hash to 3.13 / 5.5 / 8.5. The shots suite measures `81 passed`, and every 0.2 suite holds its count | mechanical, R1, R2 |
| SC-R9 | Live gate L-R1 (10.2a trials, then L-R1 or L-R1b) runs, and every record item in 10.3 is filled in | L-R1 |

### 0.6 Must-have vs nice-to-have

Everything in Sections 1-11 is a must-have. There are no nice-to-haves.

---

## 1. Architecture

### 1.1 What changes in the flow

```
bin/ltx-movie --shots ...
  ├─ Phase 1: STORY_PROMPT_TEMPLATE_SHOTS v2 (+ shots Cast block v2 with identity sentences) → qwen-agent → story.md
  │     └─ _phase1_shots_finish:
  │          draft written this run → S9 repair in place (story.pre-repair-* kept) → shots_violations (S1-S12)
  │          → while violations and rewrites < 2: move draft aside, rewrite with a block of ONLY the current
  │            violations, repair, revalidate
  │          → still failing after 2 rewrites: exit 2 (E-S10)
  │          pre-existing story.md → no repair, no rewrite: violations exit 2 (E-S9)
  └─ Phases 1b, redo, 2, 3, 4: unchanged
```

### 1.2 Module boundaries [spec choice]

- **`character_lib.py` owns every rule, every regex and the repair transform** (`repair_cast_descriptions`: text in, text out, no I/O). Pin L7j forbids `import re` in bin/ltx-movie.
- **bin/ltx-movie owns the file side of the repair**: the pre-repair copy, the in-place write, and the log line. It also owns the rewrite loop. `_run_story_agent` and Phase 1's `cmd` construction are unchanged, so pins L19, L1z9, L1z14, L7i and `:531` hold (offline `OK 344/344` measured).
- **The new detectors take plain lists, not `CastMember` objects.** `find_contact` and `_person_refs` take phrase and description lists, so S8 works in an uncast run, using the roster alone.

### 1.3 New names [spec choice]

- **`character_lib.py`:**
  - public constants: `SHOTS_MAX_REWRITES`, `SHOTS_SETTING_MIN_WORDS`, `SHOTS_CONTACT_VERBS`, `SHOTS_HANDOFF_VERBS`, `SHOTS_TAKE_VERBS`, `SHOTS_PERSON_NOUNS`, `SHOTS_ANIMAL_NOUNS`, `SHOTS_RULE_GUIDANCE`, `SHOTS_IDENTITY_HEADER`;
  - private: `_CAMERA_SHORT_MAX_WORDS`, `_CAMERA_TERM_RE`, `_POSSESSIVE_DETERMINERS`, `_NOUN_MARKERS`, `_HER_OBJECT_FOLLOWERS`, `_WORD_RE`, `_POSSESSIVE_RE`, `_CLAUSE_BREAK_RE`, `_CAMERA_WORD_RE`, `_PRONOUN_KEYS`, `_EACH_OTHER_RE`, `_TO_RE`, `_FROM_RE`, `_SPATIAL_RE`, `_HAND_AFTER_RE`, `_OWN_HAND_RE`, `_OFFSCREEN_RE`, `_DISTANCE_CUE_RE`, `_SETTING_SENTENCE_RE`, `_VIOLATION_RE`, `_STORY_PANEL_RE`, `_STORY_FIELD_RE`, `_SENTENCE_END_RE`;
  - public functions: `identity_sentence`, `is_animal_phrase`, `find_contact`, `repair_cast_descriptions`;
  - private functions: `_phrase_spans`, `_is_camera_sentence`, `_blank`, `_passage_spans`, `_person_refs`, `_appositive_nouns`.
- **`bin/ltx-movie`:**
  - new functions: `_unused_path`, `_shots_repair_s9`;
  - changed: `phase1_story` (records `authored["before"]`), `_shots_check` (new `repair=False` keyword), `_phase1_shots_finish`.
- **Files written per story:**
  - `story.pre-repair-<UTC %Y%m%dT%H%M%SZ>-<pid>[-<k>].md`;
  - `story_prompt.rewrite-2.txt`;
  - `story.rejected-<stamp>-<pid>[-<k>].md`, where `-<k>` is added only when the plain name exists (`_unused_path`).
- **Violation rule names (4.2):** `S8 contact`, `S9 cast description`, `S10 extra in cast shot`, `S11 off-screen wording`, `S12 setting sentence`.
- **New test IDs:**
  - S21 (character_lib, continuing S1-S20);
  - S54-S59 (bin/ltx-movie Phase 1, continuing S30-S53);
  - S80-S99 (the v2 block).

### 1.4 Parts of the shots spec this spec supersedes

| Shots-spec section | What changes |
|---|---|
| 0.4, bullet "Validating semantic composition rules (... contact)" | Contact (S8) and background placement (S10) are now fatal. Framing (W2) stays advisory |
| 2.2 | The rows for rule Three, rule Four and W1 are replaced by Section 2 here |
| 3.3, 3.4, 3.6-3.9 | `SHOTS_CAST_BLOCK_RULES`, `build_cast_block`, `find_phrases` (now via `_phrase_spans`, same behaviour), `motion_problems`' camera test, `shots_violations`, `shots_advisories`, `SHOTS_REWRITE_TEMPLATE`, `shots_rewrite_block` |
| 4.2-4.4 | Rule names, rules and advisories. W1 is removed |
| 5.2 | `STORY_PROMPT_TEMPLATE_SHOTS` text |
| 5.4 (b) | `_shots_check` and `_phase1_shots_finish`: S9 repair, up to two rewrites, the new messages |
| 7.2 E-S10, E-S11 | New texts (5.4 here) |
| G2, G3 | Contact, placement and descriptor repetition are now validated |

**D5 (exact).** In the shots spec, insert this paragraph directly after the `Status:` paragraph (line 4), followed by one blank line:

```
Amended 2026-10-09 by docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md (shots rules v2): rules S8-S12 are added, W1 became the fatal S9 (repaired automatically in drafts the story model writes), S7 exempts animals, Phase 1 allows up to two rewrites, and the Cast block, rewrite block, story template and Phase 1 code in 3.3, 3.7-3.9, 5.2 and 5.4 are replaced. Where the two differ, the v2 spec wins.
```

---

## 2. Approved direction → enforcement map

| Approved direction | Prompt text | Enforced by |
|---|---|---|
| 1a. One setting sentence per location (period, place, ground, light), word for word | Section 5 "Setting sentences." + the Image: field spec | **S12** (fatal; presence and at least 12 words) |
| 1b. Fights are wind-up → cut → reaction; one person per shot; contact never on screen | "Fights and touch." + Cast rule Three | **S8** (fatal; Motion: and Image:) |
| 1c. No "outside the frame"/"off-screen"; fixed left/right screen direction | "Screen direction." | **S11** (fatal) |
| 1d. The cast description word for word in every Image: that shows them | Cast identity sentences and rules; the Image: field spec | **S9** (fatal; repaired automatically in drafts written this run) |
| 2c. No human extra in a cast shot unless far in the background | Cast rule Three | **S10** (fatal; roster extras and generic person nouns) |
| 2e. Animals are not people | Cast block sentence | `is_animal_phrase`: exempt from S7, S8 and S10 |
| Two cast characters touching | Cast rule Four "they never touch" **[interpretation, C2 accepted]** | **S8** |
| F1 rewrite regression | `SHOTS_REWRITE_TEMPLATE` | S9 repair + up to two rewrites (5.3) |

---

## 3. `character_lib.py` changes (normative)

**Byte-exactness.** These blocks contain non-ASCII characters:

- U+2019 `’` in `_WORD_RE`, `_POSSESSIVE_RE`, `_HAND_AFTER_RE`, `_SENTENCE_END_RE`, `_appositive_nouns` and `find_contact`;
- U+201C `“` / U+201D `”` in `_HAND_AFTER_RE`, `_SETTING_SENTENCE_RE`, `_SENTENCE_END_RE` and `_appositive_nouns`;
- U+2014 `—` / U+2013 `–` in `_STORY_PANEL_RE`.

Copy every block out of this file **by script**, never by retyping. Then check the whole file against 3.13.

Every block is a whole statement or a whole function, given in file order. Two blank lines separate top-level `def`s.

### 3.1 Constants

Insert directly after the line `SHOTS_CLOSE_SHOT_TYPES = ("medium shot", "medium close-up", "close-up", "extreme close-up")`, with no blank line between them.

```python
SHOTS_MAX_REWRITES = 2
SHOTS_SETTING_MIN_WORDS = 12
SHOTS_CONTACT_VERBS = frozenset("""
    strike strikes struck striking hit hits hitting slash slashes slashed slashing cut cuts
    cutting stab stabs stabbed stabbing thrust thrusts thrusting punch punches punched punching
    kick kicks kicked kicking slap slaps slapped slapping smash smashes smashed smashing slam
    slams slammed slamming knock knocks knocked knocking shove shoves shoved shoving push pushes
    pushed pushing pull pulls pulled pulling drag drags dragged dragging grab grabs grabbed
    grabbing seize seizes seized seizing catch catches caught catching tackle tackles tackled
    tackling trip trips tripped tripping choke chokes choked choking strangle strangles
    strangled strangling disarm disarms disarmed disarming block blocks blocked blocking parry
    parries parried parrying deflect deflects deflected deflecting wrestle wrestles wrestled
    wrestling grapple grapples grappled grappling fight fights fought fighting attack attacks
    attacked attacking drive drives drove driven driving swing swings swung swinging help helps
    helped helping touch touches touched touching hug hugs hugged hugging embrace embraces
    embraced embracing kiss kisses kissed kissing restrain restrains restrained restraining
    shoulder-charge shoulder-charges shoulder-charged shoulder-charging""".split())
SHOTS_HANDOFF_VERBS = frozenset("""
    hands handed handing give gives gave given giving return returns returned returning""".split())
SHOTS_TAKE_VERBS = frozenset("""
    take takes took taken taking accept accepts accepted accepting receive receives received
    receiving snatch snatches snatched snatching""".split())
SHOTS_PERSON_NOUNS = frozenset("""
    man men woman women boy boys girl girls child children person people figure figures someone
    somebody stranger strangers robber robbers bandit bandits thief thieves attacker attackers
    assailant assailants enemy enemies foe foes opponent opponents soldier soldiers warrior
    warriors samurai ronin ninja swordsman swordsmen spearman spearmen archer archers rider riders
    villager villagers elder elders monk monks priest priests merchant merchants servant servants
    maid lord lady master messenger messengers shogun daughter son father mother brother sister
    husband wife friend rival victim leader captain king queen prince princess emperor assassin
    killer""".split())
SHOTS_ANIMAL_NOUNS = frozenset("""
    horse horses mare mares stallion stallions pony ponies colt colts foal steed steeds mount
    mounts dog dogs hound hounds puppy wolf wolves fox foxes ox oxen bull bulls cow cows mule
    mules donkey donkeys goat goats sheep pig pigs boar boars deer stag doe bear bears tiger
    tigers monkey monkeys cat cats kitten rabbit rabbits hare rat rats mouse mice snake snakes
    serpent viper cobra hawk hawks falcon falcons eagle eagles crow crows raven ravens owl owls
    heron crane cranes bird birds sparrow dove doves pigeon rooster chicken chickens duck ducks
    fish koi carp frog toad turtle tortoise dragon dragons butterfly moth bee bees spider beetle
    firefly dragonfly camel elephant lion leopard panther""".split())
SHOTS_RULE_GUIDANCE = (
    ("S1 panel count", "S1 panel count -- write exactly the requested number of panel sections, "
                       "numbered from 1:"),
    ("S2 characters list", 'S2 characters list -- the "## Characters" section lists every '
                           'character as - "<referring phrase>": <full visual description>, '
                           "including every Cast phrase:"),
    ("S3 fields", "S3 fields -- every panel has an Image:, a Motion: and a Narration: field and "
                  "no Prompt: field:"),
    ("S4 motion length", "S4 motion length -- every Motion: is 10-25 words in total:"),
    ("S5 one action", "S5 one action -- every Motion: is one action sentence, optionally "
                      "followed by one camera sentence, with no chaining word, no semicolon and "
                      "no ', and':"),
    ("S6 cast count", "S6 cast count -- at most two Cast characters in any one shot:"),
    ("S7 cast and extra", "S7 cast and extra -- a Motion: never names a Cast character together "
                          "with another person; give the other person's action its own shot, then "
                          "cut to the Cast character's reaction:"),
    ("S8 contact", "S8 contact -- two people never touch on screen; replace each of these shots "
                   "with a wind-up shot that shows only the person acting and a reaction shot "
                   "that shows only the person acted on, each with a Motion: that names only "
                   "that person:"),
    ("S9 cast description", "S9 cast description -- every Image: that names a Cast character "
                            "contains that character's identity sentence, copied word for word; "
                            "an Image: that does not show them does not name them:"),
    ("S10 extra in cast shot", "S10 extra in cast shot -- in a shot that shows a Cast character, "
                               "leave every other person out of the Image:, or place them far in "
                               "the background, small in the frame, and write \"far in the "
                               "background\" in the sentence that mentions them:"),
    ("S11 off-screen wording", "S11 off-screen wording -- never mention anything outside the "
                               "frame; show who faces whom with left and right screen direction "
                               "instead:"),
    ("S12 setting sentence", "S12 setting sentence -- every Image: contains its location's setting "
                             "sentence, at least 12 words long and starting \"The setting is\", "
                             "copied word for word in every shot at that location:"),
)
```

The word lists are **[spec choice]**.

- **Sizes:** 158 contact verb forms, 12 handoff, 13 + 4 = 17 take, 88 person nouns, 113 animal nouns. The three verb sets are pairwise disjoint, and the person and animal sets are disjoint (test S80).
- **Contact verbs** are the brief's list plus slap, smash, slam, knock, pull, drag, catch, tackle, trip, choke, strangle, deflect, wrestle, grapple, fight, attack, drive, swing, help, touch, hug, embrace, kiss, restrain and shoulder-charge. Every form is spelled out. Deliberately excluded:
  - grip, grasp, clutch, hold: self-holding;
  - lift, raise: wind-ups;
  - throw: "throws a glance";
  - carry: descriptions;
  - wound, pierce: adjectives;
  - shoot/shot: "A medium shot";
  - pass: walking past;
  - offer, extend: an offer is not contact;
  - charge, lunge: approach.
- **Handoff verbs** are hand(s)/give/**return** forms (F6). They need "to <person>". The base form `hand` is excluded, because it is nearly always the noun.
- **Take verbs** are take/accept/receive/**snatch** forms (F6). They need "from <person>", "<person>'s hand" or "his/her/their hand". "snatches the letter from her sash" is not caught (possessive; G-R1).
- **Person nouns** are the people words seen in the corpus plus common role and kinship nouns. `guard`, `guards` and `general` are **removed (M3)**, because of "the guard of his katana", "standing guard" and "general direction".
- **Animal nouns** are the brief's list plus common animals, including "mount".

### 3.2 Private regexes and helpers' constants

Insert directly after the two-line `_SHOT_TYPE_RE = re.compile(...)` statement, with no blank line between them.

```python
_CAMERA_SHORT_MAX_WORDS = 4
_CAMERA_TERM_RE = re.compile(r"\b(?:camera|shot|push-in|pull-back|pans?|tilts?|zooms?|dolly|"
                             r"tracking|static|locked-off|handheld)\b", re.IGNORECASE)
_POSSESSIVE_DETERMINERS = frozenset(("his", "her", "their", "its"))
_NOUN_MARKERS = frozenset("""
    a an the his her their its my your our this that these those one each every no another both
    two""".split())
_HER_OBJECT_FOLLOWERS = frozenset("""
    away aside down up off forward forwards backward backwards over to toward towards into onto
    against from across out by with""".split())
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_POSSESSIVE_RE = re.compile(r"['’]s?$")
_CLAUSE_BREAK_RE = re.compile(r"[,;:]")
_CAMERA_WORD_RE = re.compile(r"\bcamera\b", re.IGNORECASE)
_PRONOUN_KEYS = frozenset(("him", "them", "her", "each other"))
_EACH_OTHER_RE = re.compile(r"\b(?:each\s+other|one\s+another)\b", re.IGNORECASE)
_TO_RE = re.compile(r"\bto\b", re.IGNORECASE)
_FROM_RE = re.compile(r"\bfrom\b", re.IGNORECASE)
_SPATIAL_RE = re.compile(r"\b(?:toward|towards|beside|behind|before|around|past|near|"
                         r"in\s+front\s+of|sight\s+of|up\s+with|back\s+from)\b", re.IGNORECASE)
_HAND_AFTER_RE = re.compile(r"""["”]?(?:['’]s)?\s+hands?\b""", re.IGNORECASE)
_OWN_HAND_RE = re.compile(r"\s+(?:his|her|their)\s+hands?\b", re.IGNORECASE)
_OFFSCREEN_RE = re.compile(r"\b(?:outside\s+(?:of\s+)?the\s+(?:frame|shot)|"
                           r"out\s+of\s+(?:the\s+)?(?:frame|shot)|out\s+of\s+(?:view|sight)|"
                           r"off(?:\s+|-)?screen|off(?:\s+|-)camera|"
                           r"beyond\s+the\s+(?:edge\s+of\s+the\s+)?frame|unseen)\b",
                           re.IGNORECASE)
_DISTANCE_CUE_RE = re.compile(r"\b(?:far\s+(?:in\s+the\s+)?(?:background|distance)|far\s+(?:behind|"
                              r"back|away|off)|far-off|in\s+the\s+(?:far\s+)?distance|in\s+the\s+"
                              r"far\s+background|distant|(?:small|tiny)\s+in\s+the\s+frame)\b",
                              re.IGNORECASE)
_SETTING_SENTENCE_RE = re.compile(r"""["“]?the\s+setting\s+is\b""", re.IGNORECASE)
_VIOLATION_RE = re.compile(r"(?:story|panel (\d+)): (S\d+ [^:]+): (.*)", re.DOTALL)
_STORY_PANEL_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$")
_STORY_FIELD_RE = re.compile(r"^(Image|Motion|Narration|Prompt|Style):\s*(.*)$")
_SENTENCE_END_RE = re.compile(r"""[.!?]["”’']?(?=\s|$)""")
```

- **`_SPATIAL_RE` (F2, the reviewer's exact regex).** A person reference preceded, after the verb, by toward, towards, beside, behind, before, around, past, near, in front of, sight of, up with, or back from is not a target. This removes measured false positives: "pulls her shawl tight around her", "drags his sword behind him", "catches sight of / up with", "pulls back from", "drives forward toward", "block the stone path in front of the woman in grey", "strikes a pose before", "hits the ground beside".
  - "pushes the gate open for the villagers" still fires. The reviewer listed it, but the reviewer's regex has no "for", and it is not among the seven sentences to add (G-R15).
- **`_OFFSCREEN_RE` (M2).** Adds out of view / out of sight / outside (of) the shot / beyond the edge of the frame / unseen. The accepted false positive "beyond the frame of the temple gate" is pinned in test S88.
- **`_DISTANCE_CUE_RE`.** Unchanged from revision 1. Bare "in the background" is not a cue.
- **`_POSSESSIVE_DETERMINERS` (M3).** A person noun directly after his/her/their/its is not a reference ("her figure", "his men").
- **`_STORY_PANEL_RE` / `_STORY_FIELD_RE`** are the manifest's `_PANEL_HEADER_RE` / `_PANEL_LABEL_RE` verbatim (0.2). `_SENTENCE_END_RE` finds a sentence end for the repair.

### 3.3 Cast block: rules, identity sentences, `build_cast_block`

**(a)** Replace the whole `SHOTS_CAST_BLOCK_RULES = (...)` statement (`:71-89`) with the block below, which also defines `SHOTS_IDENTITY_HEADER`.

```python
SHOTS_CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file, even when it is longer than four words, and list each of them in "
    "the Characters section with exactly the description given above. Every Image: field that "
    "shows one of these characters contains that character's identity sentence from the list "
    "above, copied word for word -- never shortened, reordered or paraphrased -- and an Image: "
    "field that does not show them never names them. Shots that show these characters follow "
    "four extra rules. One: at most two of these characters appear in any one shot. Two: a shot "
    "that shows one of them is composed around them -- a medium shot or closer, with them in the "
    "centre or the foreground of the frame. Three: any other "
    "person may appear in such a shot only far in the background, small in the frame, never "
    "touching them and never within arm's reach of them; the sentence that mentions that person "
    'says "far in the background", the Image: names no other person anywhere else -- not as '
    "someone a character looks at, and not even in a possessive -- and the shot's Motion: names "
    "none of the other characters; when one of these characters and another person act on each "
    "other at close range -- a grab, a blow, a shove -- show it by cutting: first a shot of the "
    "other person performing the action, then a separate shot of this character's reaction. "
    "Four: when two of these characters share a shot they never touch -- no taken hand, no "
    "hand-off, no grappling, embrace or overlap; show a hand-off or a taken hand as two shots, "
    "one of each character. A shot that shows none of these characters has none of these extra "
    "rules. An animal, such as a horse that a character rides, is not a person, so none of these "
    "rules limit it. Bring a cast member on screen only where the narrative calls for them. Every "
    "other character still gets a referring phrase of your own, under the rules below.")
SHOTS_IDENTITY_HEADER = ("Identity sentences -- copy the one for each of these characters, word "
                         "for word, into every Image: field that shows them:")
```

**(b)** Replace `build_cast_block` (`:525-530`) with the block below, which is `identity_sentence` followed by `build_cast_block`.

```python
def identity_sentence(member):
    """The sentence a shots-mode Image: copies for a cast member who is on screen (shots rules v2
    spec 3.3): the phrase with its first letter capitalised, " is ", the descriptor, "."."""
    return "%s%s is %s." % (member.phrase[:1].upper(), member.phrase[1:], member.descriptor)


def build_cast_block(members, shots=False):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    if shots:
        lines.append(SHOTS_IDENTITY_HEADER)
        lines += ["- " + identity_sentence(m) for m in members]
    lines.append(SHOTS_CAST_BLOCK_RULES if shots else CAST_BLOCK_RULES)
    return "\n".join(lines)
```

- `SHOTS_CAST_BLOCK_RULES` is 349 words, contains "word for word" exactly twice and no `{`, `}` or `%`.
- It keeps the fragments "at most two of these characters", "a medium shot or closer", "never within arm's reach", "show it by cutting" and "has none of these extra rules".
- **Identity sentences go before the rules [spec choice].** They are a list to copy, and the order keeps test S34's `endswith` true.
- Continuous mode is byte-identical.

### 3.4 `_phrase_spans` and `find_phrases`

Replace `find_phrases` (`:533-550`) with the block below. `find_phrases` behaves identically (test S4).

```python
def _phrase_spans(text, phrases):
    """[(start, end, phrase)] for every claimed occurrence of the given phrases in text, sorted:
    matched like cast_text, longest phrase first, a match overlapping an already-claimed span
    ignored (shots spec 3.4; shots rules v2 spec 3.4)."""
    claimed = []
    for phrase in sorted(set(phrases), key=lambda p: (-len(p), p.lower(), p)):
        for match in _phrase_regex(normalize_phrase(phrase)).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _ in claimed):
                continue
            claimed.append((start, end, phrase))
    return sorted(claimed)


def find_phrases(text, phrases):
    """The given phrases that occur in text, matched exactly like cast_text (case-insensitive,
    whitespace-tolerant, hyphen counts as a word character), longest phrase first, a match
    overlapping an already-claimed span ignored. Each phrase is returned once, as given, in the
    order of its first claimed occurrence (shots spec 3.4). Phrases must already be valid
    (normalize_phrase)."""
    ordered = []
    for _start, _end, phrase in _phrase_spans(text, phrases):
        if phrase not in ordered:
            ordered.append(phrase)
    return ordered
```

### 3.5 Helpers: `is_animal_phrase` (3.5), `_is_camera_sentence` (3.6), `_blank` / `_passage_spans` / `_person_refs` / `find_contact` (3.7), `_appositive_nouns` (3.8)

Insert this one contiguous block after `parse_character_roster` and before `motion_problems`, separated by two blank lines on each side. The semantics are defined in 4.5.

```python
def is_animal_phrase(phrase):
    """True when a word of phrase, lowercased and with a trailing 's or ' removed, is in
    SHOTS_ANIMAL_NOUNS: that roster character is an animal, exempt from S7, S8 and S10 (shots
    rules v2 spec 3.5)."""
    return any(_POSSESSIVE_RE.sub("", w.lower()) in SHOTS_ANIMAL_NOUNS for w in phrase.split())


def _is_camera_sentence(sentence):
    """A camera sentence (shots spec 4.3 S5; shots rules v2 spec 3.6): it starts with "camera"
    or "the camera", or it has at most _CAMERA_SHORT_MAX_WORDS words and contains a camera term
    ("Static camera.", "Slow push-in.")."""
    return bool(_CAMERA_SENTENCE_RE.match(sentence)
                or (len(sentence.split()) <= _CAMERA_SHORT_MAX_WORDS
                    and _CAMERA_TERM_RE.search(sentence)))


def _blank(text, spans):
    """text with every character inside the (start, end) spans replaced by a space."""
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _passage_spans(text, passages):
    """[(start, end)] of every case- and whitespace-insensitive occurrence in text of each
    passage, ignoring a trailing "." on the passage."""
    spans = []
    for passage in passages:
        words = passage.rstrip(".").split()
        if words:
            pattern = re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)
            spans += [m.span() for m in pattern.finditer(text)]
    return spans


def _person_refs(sentence, humans, animals, descriptions):
    """[(start, end, key)] of the people one sentence refers to, sorted by start (shots rules v2
    spec 3.7): each human roster or cast phrase (key: the phrase, lowercased); then, outside every
    roster phrase (human or animal) and every description, each SHOTS_PERSON_NOUNS word (key: the
    noun, lowercased, a trailing 's or ' removed), "him", "them", "each other", "one another"
    (key "each other"), and "her" used as an object: followed by no word, by punctuation, or by a
    _HER_OBJECT_FOLLOWERS word. A person noun right after his/her/their/its is skipped ("her
    figure")."""
    spans = _phrase_spans(sentence, list(humans) + list(animals))
    human_keys = {h.lower() for h in humans}
    refs = [(s, e, p.lower()) for s, e, p in spans if p.lower() in human_keys]
    blanked = _blank(sentence, [(s, e) for s, e, _ in spans]
                     + _passage_spans(sentence, descriptions))
    words = list(_WORD_RE.finditer(blanked))
    for j, word in enumerate(words):
        token = word.group(0).lower()
        noun = _POSSESSIVE_RE.sub("", token)
        if noun in SHOTS_PERSON_NOUNS:
            if j == 0 or words[j - 1].group(0).lower() not in _POSSESSIVE_DETERMINERS:
                refs.append((word.start(), word.end(), noun))
        elif token in ("him", "them"):
            refs.append((word.start(), word.end(), token))
        elif token == "her":
            nxt = words[j + 1] if j + 1 < len(words) else None
            if (nxt is None or any(c in ",;:.!?)" for c in blanked[word.end():nxt.start()])
                    or nxt.group(0).lower() in _HER_OBJECT_FOLLOWERS):
                refs.append((word.start(), word.end(), "her"))
    refs += [(m.start(), m.end(), "each other") for m in _EACH_OTHER_RE.finditer(blanked)]
    return sorted(refs)


def find_contact(sentence, humans, animals, descriptions):
    """(verb, target) for the first contact in one sentence, or None (shots rules v2 spec 3.7).
    A word in SHOTS_CONTACT_VERBS, SHOTS_HANDOFF_VERBS or SHOTS_TAKE_VERBS is a verb unless the
    word before it is in _NOUN_MARKERS or ends in 's. Its clause runs between the nearest , ; or
    : on either side; a clause containing "camera" is skipped. Its subject is the first person
    reference in the sentence before it; a target is a person reference after it, inside its
    clause, with a key other than the subject's and no _SPATIAL_RE word ("toward", "behind", "in
    front of", ...) between the verb and it. A contact verb needs any target; a handoff verb a
    target after "to"; a take verb either "his/her/their hand(s)" right after it, or a target
    after "from" or followed by 's hand(s)."""
    refs = _person_refs(sentence, humans, animals, descriptions)
    breaks = [m.start() for m in _CLAUSE_BREAK_RE.finditer(sentence)]
    words = list(_WORD_RE.finditer(sentence))
    for i, word in enumerate(words):
        form = word.group(0).lower()
        if (form not in SHOTS_CONTACT_VERBS and form not in SHOTS_HANDOFF_VERBS
                and form not in SHOTS_TAKE_VERBS):
            continue
        previous = words[i - 1].group(0).lower() if i else ""
        if previous in _NOUN_MARKERS or previous.endswith(("'s", "’s")):
            continue
        clause_start = max([b for b in breaks if b < word.start()], default=0)
        clause_end = min([b for b in breaks if b >= word.end()], default=len(sentence))
        if _CAMERA_WORD_RE.search(sentence[clause_start:clause_end]):
            continue
        before = [r for r in refs if r[1] <= word.start()]
        subject = before[0][2] if before else None
        targets = [r for r in refs
                   if r[0] >= word.end() and r[1] <= clause_end and r[2] != subject
                   and not _SPATIAL_RE.search(sentence, word.end(), r[0])]
        if form in SHOTS_HANDOFF_VERBS:
            targets = [r for r in targets if _TO_RE.search(sentence, word.end(), r[0])]
        elif form in SHOTS_TAKE_VERBS:
            own = _OWN_HAND_RE.match(sentence, word.end())
            if own:
                return form, own.group(0).strip()
            targets = [r for r in targets if _FROM_RE.search(sentence, word.end(), r[0])
                       or _HAND_AFTER_RE.match(sentence, r[1])]
        if targets:
            return form, sentence[targets[0][0]:targets[0][1]]
    return None


def _appositive_nouns(sentence, members):
    """{(start, end)} of each cast member's class noun standing in an appositive right after that
    member's phrase -- <phrase>, optional closing quote, "," or ":", "a" or "an", at most six
    words, <class noun> -- as in "the woman in grey, a young woman with ..." (shots rules v2 spec
    3.8 S10)."""
    spans = set()
    for m in members:
        tail = re.compile(r"""["”]?\s*[,:]\s*an?\s+(?:[\w'’-]+,?\s+){0,6}?(%s)\b"""
                          % re.escape(m.class_noun), re.IGNORECASE)
        for match in _phrase_regex(m.phrase).finditer(sentence):
            noun = tail.match(sentence, match.end())
            if noun:
                spans.add(noun.span(1))
    return spans
```

### 3.6 `motion_problems` (camera-sentence fold-in, T2-1)

Replace the whole function (`:593-614`) with the block below. Only the docstring and the `actions` line change. **[spec choice: T2-1 fold-in]**: "Static camera.", "Slow push-in." and "Handheld, slow pan left." are now camera sentences. 0 of the 128 shots Motion: fields on disk use these forms, so this is insurance.

```python
def motion_problems(motion):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S4, S5). A camera sentence
    (_is_camera_sentence) is not an action sentence."""
    problems = []
    words = len(motion.split())
    if not SHOTS_MOTION_MIN_WORDS <= words <= SHOTS_MOTION_MAX_WORDS:
        problems.append(("S4 motion length", "Motion: is %d words; it must be %d-%d"
                         % (words, SHOTS_MOTION_MIN_WORDS, SHOTS_MOTION_MAX_WORDS)))
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _is_camera_sentence(s)]
    if len(actions) != 1:
        problems.append(("S5 one action", "Motion: has %d action sentences; it must have exactly "
                         "one, optionally followed by a camera sentence" % len(actions)))
    if ";" in motion:
        problems.append(("S5 one action", "Motion: contains a semicolon"))
    chain = _CHAIN_WORD_RE.search(motion)
    if chain:
        problems.append(("S5 one action", "Motion: chains actions with %r"
                         % " ".join(chain.group(0).lower().split())))
    if _COMMA_AND_RE.search(motion):
        problems.append(("S5 one action", "Motion: chains actions with ', and'"))
    return problems
```

### 3.7 Person references and contact

These functions are in the 3.5 block, with semantics in 4.5. They are pinned by tests S82-S84.

### 3.8 `shots_violations`

Replace the whole function (`:617-663`) with:

```python
def shots_violations(text, panels, expected_panels, members):
    """Every shot-rule violation of a shots-mode story.md (shots spec 4.3; shots rules v2 spec 4),
    in this order: S1, S2, then per panel S3, S4, S5, S6, S7, S8 (Motion:, then Image:), S9, S10,
    S11 (Image:, then Motion:), S12. text is the whole file; panels are bin/ltx-story-manifest
    _parse_prompts_md dicts; members are CastMember (may be empty: then S2, S6, S7, S9 and S10
    are skipped). The roster is read even without members, so S8 knows an uncast story's
    extras and animals."""
    out = []
    if len(panels) != expected_panels:
        out.append("story: S1 panel count: expected exactly %d panels, found %d"
                   % (expected_panels, len(panels)))
    roster, problems = parse_character_roster(text)
    if members:
        out += ["story: S2 characters list: %s" % p for p in problems]
        listed = [p.lower() for p, _ in roster]
        for m in members:
            if m.phrase.lower() not in listed:
                out.append("story: S2 characters list: cast phrase %r (character %s) is not listed"
                           % (m.phrase, m.name))
    cast_phrases = {m.phrase.lower() for m in members}
    others = [p for p, _ in roster if p.lower() not in cast_phrases]
    animals = [p for p in others if is_animal_phrase(p)]
    extras = [p for p in others if not is_animal_phrase(p)]
    humans = [m.phrase for m in members] + extras
    descriptions = [d for _, d in roster] + [m.descriptor for m in members]
    for p in panels:
        num = p["number"]
        for label, key in (("Image", "image"), ("Motion", "motion"), ("Narration", "narration")):
            if not p[key].strip():
                out.append("panel %d: S3 fields: missing/empty %s: field" % (num, label))
        if p["prompt"].strip():
            out.append("panel %d: S3 fields: has a Prompt: field; shots mode expects Image:, "
                       "Motion: and Narration:" % num)
        if p["motion"].strip():
            out += ["panel %d: %s: %s" % (num, rule, detail)
                    for rule, detail in motion_problems(p["motion"])]
        names = []
        if members:
            names = sorted(set(cast_text(p["image"], members)[1])
                           | set(cast_text(p["motion"], members)[1]))
            if len(names) > SHOTS_MAX_CAST_PER_PANEL:
                out.append("panel %d: S6 cast count: the shot names %d cast characters (%s); "
                           "at most %d" % (num, len(names), ", ".join(names),
                                           SHOTS_MAX_CAST_PER_PANEL))
            found = find_phrases(p["motion"], [m.phrase for m in members] + others)
            cast_found = [f for f in found if f.lower() in cast_phrases]
            extra_found = [f for f in found if f in extras]
            if cast_found and extra_found:
                out.append("panel %d: S7 cast and extra: Motion: names %s together with %s; show "
                           "the other character's action in its own shot, then cut to the cast "
                           "character's reaction"
                           % (num, ", ".join(repr(f) for f in cast_found),
                              ", ".join(repr(f) for f in extra_found)))
        for label, key in (("Motion", "motion"), ("Image", "image")):
            sentences = [s for s in _SENTENCE_SPLIT_RE.split(p[key].strip()) if s.strip()]
            if key == "motion":
                sentences = [s for s in sentences if not _is_camera_sentence(s)]
            for sentence in sentences:
                contact = find_contact(sentence, humans, animals, descriptions)
                if contact:
                    out.append("panel %d: S8 contact: %s: %r acts on %r; two people touching on "
                               "screen" % (num, label, contact[0], contact[1]))
                    break
        image_norm = " ".join(p["image"].split()).lower()
        for m in members:
            if (phrase_occurs(p["image"], m.phrase)
                    and " ".join(m.descriptor.split()).lower() not in image_norm):
                out.append("panel %d: S9 cast description: Image: names %r without character %s's "
                           "description word for word; copy in this sentence: %s"
                           % (num, m.phrase, m.name, identity_sentence(m)))
        if names:
            flagged = {}
            for sentence in _SENTENCE_SPLIT_RE.split(p["image"].strip()):
                if _DISTANCE_CUE_RE.search(sentence):
                    continue
                own = _appositive_nouns(sentence, members)
                named = [d for phrase, d in roster if phrase_occurs(sentence, phrase)]
                for start, end, key in _person_refs(sentence, humans, animals,
                                                    [m.descriptor for m in members] + named):
                    if (key not in cast_phrases and key not in _PRONOUN_KEYS
                            and (start, end) not in own):
                        flagged.setdefault(key, sentence[start:end])
            out += ["panel %d: S10 extra in cast shot: Image: names %r in a shot that shows %s, "
                    "without \"far in the background\" or another distance cue in that sentence"
                    % (num, shown, ", ".join(names)) for shown in flagged.values()]
        for label, key in (("Image", "image"), ("Motion", "motion")):
            offscreen = _OFFSCREEN_RE.search(p[key])
            if offscreen:
                out.append("panel %d: S11 off-screen wording: %s: says %r; use left and right "
                           "screen direction instead"
                           % (num, label, " ".join(offscreen.group(0).lower().split())))
        if p["image"].strip() and not any(
                _SETTING_SENTENCE_RE.match(s) and len(s.split()) >= SHOTS_SETTING_MIN_WORDS
                for s in _SENTENCE_SPLIT_RE.split(p["image"].strip())):
            out.append('panel %d: S12 setting sentence: Image: has no setting sentence of at least '
                       '%d words starting "The setting is"' % (num, SHOTS_SETTING_MIN_WORDS))
    return out
```

### 3.9 `shots_advisories`

Replace the whole function (`:666-691`) with the block below, which is W2 only:

```python
def shots_advisories(panels, members):
    """Non-fatal shots-mode warnings (shots spec 4.4; its W1 is the fatal S9 since shots rules v2),
    per panel in order: W2 when the shot names a cast character but its Image: states no shot
    type, or a wide one. [] when members is empty."""
    out = []
    if not members:
        return out
    for p in panels:
        num = p["number"]
        names = sorted(set(cast_text(p["image"], members)[1])
                       | set(cast_text(p["motion"], members)[1]))
        if names:
            types = [t.lower() for t in _SHOT_TYPE_RE.findall(p["image"])]
            if not types or any(t not in SHOTS_CLOSE_SHOT_TYPES for t in types):
                out.append("panel %d: shows cast character(s) %s but its Image: shot type is %s; a "
                           "shot with a cast character should be a medium shot or closer"
                           % (num, ", ".join(names), ", ".join(types) or "not stated"))
    return out
```

### 3.10 Rewrite template and `shots_rewrite_block`

**(a)** Replace the whole `SHOTS_REWRITE_TEMPLATE = (...)` statement (`:90-97`) with:

```python
SHOTS_REWRITE_TEMPLATE = (
    "REWRITE REQUIRED. Your previous draft of this file was rejected because it broke these "
    "rules:\n"
    "%s\n"
    "Write the complete file again from the beginning, following every instruction above and "
    "fixing every listed problem. Keep EXACTLY %d panel sections. Where a Motion: held more than "
    "one action, keep only its single most important action and give the other beats their own "
    "panels instead. Where a shot showed two people touching, replace it with a wind-up shot of "
    "the one acting and a reaction shot of the one acted on. Merge or drop minor beats so that "
    "the panel count stays the same. Copy every identity sentence and every setting sentence "
    "exactly as written, without shortening or rewording it.")
```

**(b)** Replace `shots_rewrite_block` (`:694-701`) with:

```python
def shots_rewrite_block(violations, panels):
    """The text appended to the Phase 1 prompt for each rewrite (shots spec 5.4; shots rules v2
    spec 3.10, 6). Violations of a SHOTS_RULE_GUIDANCE rule are grouped by rule, in that order,
    under the rule's guidance line; within a rule, violations with the same detail merge into one
    "- panel N: <detail>" / "- panels N, M: <detail>" / "- story: <detail>" line. Any other
    violation follows as its own "- <violation>" line. At most SHOTS_REWRITE_MAX_LISTED "- "
    lines are listed, then "- ... and N more", N counting the violations not listed."""
    guidance = dict(SHOTS_RULE_GUIDANCE)
    merged, other = {}, []
    for v in violations:
        match = _VIOLATION_RE.fullmatch(v)
        if match and match.group(2) in guidance:
            merged.setdefault((match.group(2), match.group(3)), []).append(match.group(1))
        else:
            other.append(v)
    items = []
    for rule, _line in SHOTS_RULE_GUIDANCE:
        for (r, detail), numbers in merged.items():
            if r != rule:
                continue
            if numbers[0] is None:
                where = "story"
            elif len(numbers) == 1:
                where = "panel " + numbers[0]
            else:
                where = "panels " + ", ".join(numbers)
            items.append((rule, "- %s: %s" % (where, detail), len(numbers)))
    items += [(None, "- " + v, 1) for v in other]
    lines, current, shown = [], None, 0
    for rule, line, count in items[:SHOTS_REWRITE_MAX_LISTED]:
        if rule is not None and rule != current:
            lines.append(guidance[rule])
        current = rule
        lines.append(line)
        shown += count
    if shown < len(violations):
        lines.append("- ... and %d more" % (len(violations) - shown))
    return SHOTS_REWRITE_TEMPLATE % ("\n".join(lines), panels)
```

### 3.11 `repair_cast_descriptions` (ruling 1a)

Insert directly after `shots_rewrite_block` and before `usable_characters`, separated by two blank lines on each side.

```python
def repair_cast_descriptions(text, members):
    """(text, [(panel number, member name)]): S9 repaired in a shots story.md (shots rules v2 spec
    3.11). Panels and their Image: fields are found as bin/ltx-story-manifest parses them. For
    each panel in file order and each member in members order whose phrase occurs in the Image:
    field but whose descriptor (case- and whitespace-insensitive) does not, " " +
    identity_sentence(member) is inserted after the end of the sentence that holds the phrase's
    first match on one line of that field: the first ., ! or ?, optionally followed by a closing
    quote, that is followed by whitespace or the end of the line. When that line has no such end
    after the match, the sentence goes at the end of the line, after a "." if the line does not
    already end in ., ! or ? (a trailing carriage return stays last). A phrase that occurs only
    across a line break is not repaired (S9 still reports it). Every other byte of text is
    unchanged."""
    lines = text.split("\n")
    sections = []
    current, field = None, None
    for i, line in enumerate(lines):
        header = _STORY_PANEL_RE.match(line)
        if header:
            current, field = (int(header.group(1)), []), None
            sections.append(current)
            continue
        if line.startswith("##"):
            current, field = None, None
            continue
        if current is None:
            continue
        label = _STORY_FIELD_RE.match(line)
        if label:
            field = label.group(1)
            if field == "Image":
                current[1].append(i)
        elif field == "Image" and line.strip():
            current[1].append(i)
    repaired = []
    for number, indexes in sections:
        for m in members:
            values = []
            for i in indexes:
                label = _STORY_FIELD_RE.match(lines[i])
                value = (label.group(2) if label else lines[i]).strip()
                if value:
                    values.append(value)
            image = " ".join(values)
            if (not phrase_occurs(image, m.phrase)
                    or " ".join(m.descriptor.split()).lower() in " ".join(image.split()).lower()):
                continue
            for i in indexes:
                match = _phrase_regex(m.phrase).search(lines[i])
                if not match:
                    continue
                end = _SENTENCE_END_RE.search(lines[i], match.end())
                if end:
                    lines[i] = (lines[i][:end.end()] + " " + identity_sentence(m)
                                + lines[i][end.end():])
                else:
                    cr = "\r" if lines[i].endswith("\r") else ""
                    line = lines[i].rstrip()
                    lines[i] = (line + ("" if line.endswith((".", "!", "?")) else ".") + " "
                                + identity_sentence(m) + cr)
                repaired.append((number, m.name))
                break
    return "\n".join(lines), repaired
```

**Placement [spec choice].** The identity sentence is inserted **after the end of the sentence holding the first mention**, not as ": <descriptor>" directly after the mention.

- In the corpus the first mention is often mid-sentence ('A medium shot shows "the ronin" standing alone near a small stream') or possessive ('"the woman in grey"\'s hand'). An inline ": <descriptor>" there produces ungrammatical text, and that text goes straight to the image model.
- A whole identity sentence is always grammatical. It is the form the Cast block teaches, and it satisfies S9's check (descriptor substring) by construction.

Behaviour:

- **Order.** Members are processed in members order, and each is inserted directly after the sentence end. So when two members share a sentence, the later member's identity sentence comes first (test S21 pins this).
- **Measured effect.** All 22 S9 violations in the as-generated rules story, 18 in full20 and 2 in ls1 are repairable, and none remains after the repair (test S95).

### 3.12 Module docstring

Replace these two lines:

```
validation, advisories and the rewrite block;
docs/superpowers/specs/2026-10-06-shots-mode-design.md).
```

with these three lines:

```
validation, advisories and the rewrite block;
docs/superpowers/specs/2026-10-06-shots-mode-design.md and
docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md).
```

No import is added (test S20 / C41 unchanged).

### 3.13 Result check

After 3.1-3.12, `character_lib.py` is 1140 lines with sha256 `61539042fde24e5f126b1492e1d9d1394c64096d8c40a864e6990f8c98a21ce0`, from the base `d952127b…`. If the hash differs:

1. diff the file against the blocks by script;
2. fix only transcription differences;
3. never edit the spec's code to match.

---

## 4. Validation rules (normative index)

### 4.1 When validation and the S9 repair run

| Situation | What runs |
|---|---|
| `--shots`, Phase 1 wrote story.md in **this** run | **S9 repair** (in place, the unrepaired bytes kept as `story.pre-repair-*`), then S1-S12. On violations: move the draft aside, then rewrite. After each rewrite: repair, then S1-S12 again. Up to `SHOTS_MAX_REWRITES = 2` rewrites. Still failing after 2: exit 2 (E-S10) |
| `--shots`, story.md already existed (Phase 1 skipped, including every `--redo`) | S1-S12 with **no repair and no rewrite**. On violations: exit 2 (E-S9) |
| no `--shots` | today's `_validate_story_md` only |

- **The repair runs only on drafts the story model wrote in this run [spec choice].** A pre-existing story.md may hold the user's hand edits, and its stills already exist: repairing it would leave every reused still out of step with the new Image: text (see the consequence below). So for pre-existing stories S9 stays fatal, alongside the cases the repair cannot fix (a phrase split across a line break).
- **A story.md that Phase 1's call left unchanged is never repaired [spec choice, re-review Minor 2].** With `--force-story`, the old story.md exists while the story model runs. If the call ends without writing it (its `(st_ino, st_mtime_ns, st_size)` is the same as the `os.stat` taken before the call), Phase 1 exits 1 with the 5.4 message and touches nothing.
- **A first-draft timeout that left story.md: rerun with --force-story.** A first draft whose call times out after `write_file` exits 1 from `_run_story_agent` and leaves story.md in place. That story.md is then pre-existing, so a plain rerun gives E-S9 with no repair.
- **No grandfathering (C4, accepted).** v2 applies to every `--shots` run.

**Consequence: to redo a panel of a pre-v2 story, hand-edit every violation. Every panel whose Image: you changed must also be listed in `--redo`, or its reused still no longer matches story.md. A changed Motion: re-renders that clip on its existing still.**

The reasons:

- `--redo` validates in Phase 1, before `phase_redo_shots` moves anything. In this corpus that means 39 hand-edits for `ronin-shots-rules-20261009` and 52 for full20.
- Stills are reused because the file exists (`_shots_missing_stills`).
- Clip provenance keys on the Motion: text plus the still's bytes (`bin/ltx-mlx-render:416-444`).

### 4.2 Violation string format

The format is unchanged: `"story: <rule>: <detail>"` / `"panel <N>: <rule>: <detail>"`. `<rule>` is one of S1 panel count … S7 cast and extra (unchanged), `S8 contact`, `S9 cast description`, `S10 extra in cast shot`, `S11 off-screen wording`, `S12 setting sentence`.

Order: S1, S2, then per panel:

- S3, S4, S5, S6, S7;
- S8 (Motion:, then Image:);
- S9 (members order);
- S10 (sentence order, then position);
- S11 (Image:, then Motion:);
- S12.

Test S92 pins this order.

### 4.3 Rules (new and changed)

| Rule | Applies | Check (exact) | Message detail |
|---|---|---|---|
| S7 (changed) | cast only | An extra is a roster phrase that is not cast and not `is_animal_phrase`. Animal phrases still claim spans | unchanged |
| **S8** | always | For Motion: then Image:, sentences split by `_SENTENCE_SPLIT_RE` (Motion: drops camera sentences). The first sentence where `find_contact(sentence, humans, animals, descriptions)` is not `None` gives one violation per field. `humans` = cast phrases + human roster extras; `animals` = animal roster phrases; `descriptions` = every roster description + every cast descriptor | `<Field>: '<verb, lowercased>' acts on '<target as written>'; two people touching on screen` |
| **S9** | cast only | For each member, in members order: the member's phrase occurs in Image:, and its descriptor (whitespace-collapsed, lowercased) is not a substring of the whitespace-collapsed, lowercased Image: | `Image: names '<phrase>' without character <name>'s description word for word; copy in this sentence: <identity_sentence>` |
| **S10** | cast only, on panels whose cast set (Image: ∪ Motion:) is non-empty | For each Image: sentence with no distance cue: every person reference (4.5), with **only the cast descriptors and the descriptions of roster entries named in that sentence** blanked. Excluded keys: cast phrases, pronoun keys, and a cast member's class noun in the appositive position right after that member's phrase (`_appositive_nouns`). One violation per key per panel, in first-occurrence order | `Image: names '<reference as written>' in a shot that shows <sorted cast names, ", ">, without "far in the background" or another distance cue in that sentence` |
| **S11** | always | The first `_OFFSCREEN_RE` match in Image:, then in Motion: | `<Field>: says '<match, lowercased, whitespace-collapsed>'; use left and right screen direction instead` |
| **S12** | always, on a non-empty Image: | No `_SENTENCE_SPLIT_RE` sentence of Image: both matches `_SETTING_SENTENCE_RE` at its start **and** has at least `SHOTS_SETTING_MIN_WORDS = 12` words (M1) | `Image: has no setting sentence of at least 12 words starting "The setting is"` |

- **S10 blanking (F3) [spec choice beyond the reviewer's exact edit].**
  - The reviewer's edit blanked only the cast descriptors. Measured, that reports an extra twice when its roster description appears beside its phrase: once as the phrase, once as 'man' from its own description.
  - Blanking a roster description only when that entry's phrase is in the same sentence keeps the reviewer's goal: a description-only extra ("Beside her stands a stocky man with a black beard …") is flagged as 'man'. It also removes the duplicate.
  - Corpus counts are unchanged under both variants (measured). Mutations for both variants are in 8.6.
- **S10 class-noun skip narrowed to the appositive (F3).**
  - Measured: the six corpus counts and projections are identical under the broad skip ("any class noun of a member named in the sentence") and the appositive-only skip. So the appositive-only skip is used.
  - "The ronin faces a wiry young man" (or "… beside a wiry young man") is now flagged (test S87).
- **S12 minimum (M1).** "The setting is the same as before." fails. The 12-word boundary is pinned in test S89: 11 words fail, 12 pass. The corpus setting sentences are 22-29 words.

### 4.4 Advisories

| ID | Status |
|---|---|
| W1 | **Removed.** Its condition is the fatal S9, repaired automatically in drafts written this run |
| W2 | Unchanged |

### 4.5 Definitions used by S8 and S10 (`_person_refs`, `find_contact`)

1. **Person references in one sentence**, sorted by start:
   - each human roster or cast phrase match, longest first, with animal phrases also claiming their spans (key: the phrase, lowercased);
   - outside every claimed phrase span and every given description passage:
     - each `SHOTS_PERSON_NOUNS` word (key: the bare noun, with `'s`/`’s`/`'` stripped), unless the previous word is his/her/their/its;
     - `him`, `them`;
     - `each other` / `one another`;
     - `her` used as an object: followed by no further word, by punctuation from `,;:.!?)`, or by a `_HER_OBJECT_FOLLOWERS` word.
2. **A verb** is a word of the three verb sets, unless the previous word is in `_NOUN_MARKERS` or ends in `'s`/`’s`.
3. **Its clause** runs between the nearest `,`, `;` or `:` on either side. A clause containing "camera" is skipped.
4. **Its subject** is the first reference ending before the verb. **A target** is a reference that:
   - starts after the verb and ends inside the clause;
   - has a key different from the subject's;
   - has no `_SPATIAL_RE` match between the verb and it.
5. **The verb class decides the hit:**
   - contact verbs need any target;
   - handoff verbs need "to" between the verb and the target;
   - take verbs need "his/her/their hand(s)" directly after the verb, or "from" before the target, or the target followed by `"'s hand(s)`.

---

## 5. `bin/ltx-movie` (normative)

### 5.1 `STORY_PROMPT_TEMPLATE_SHOTS` v2 (unchanged from revision 1)

Replace the whole constant (`:168-197`) with the block below. The blank line before `SEED_IMAGE_PREFACE` stays.

```python
STORY_PROMPT_TEMPLATE_SHOTS = """You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

How this movie is made: it is a sequence of separate shots joined by cuts, {seconds} seconds each. Every panel is one shot. Its Image: field is rendered as a single still picture, that picture becomes the shot's first frame, and a {seconds}-second clip is animated from it. Nothing carries over from one shot to the next except what you write, so every Image: field must describe its whole shot. Cuts between panels are expected. Make the cuts read as one scene by stating the continuity in every Image: field: the same setting, the same time of day, lighting and colour palette, and consistent screen direction -- who is on the left and who is on the right, and which way each character faces or moves.

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file starts with a title line, a one-sentence summary and a Characters section, and then has EXACTLY {panels} panel sections, numbered 1 through {panels} in order:

# <title>

<one sentence summarising the story>

## Characters
- "<referring phrase>": <full visual description>

The Characters section has one line per character who appears anywhere in the file, in exactly that format, with the phrase in double quotes. A full visual description covers apparent age group, build, skin tone, hair colour, length and style, and clothing and accessories. Give each character a referring phrase of at most four words built only from details in their description or stated by the narrative, and use that exact phrase for them everywhere else in the file. Never add a colour, garment or trait just to make the phrase.

Every panel has exactly three fields, in this order:

## Panel N — <short title>
Image: <80-170 words describing this shot's first frame as one still picture: the setting sentence of this shot's location, copied word for word; for every character who is on screen, one sentence made of their referring phrase, the word "is" and their full description from the Characters section, copied word for word; where each one stands and which way they face; the background; the lighting and colour palette; the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up); the camera viewpoint; and the rendering style.>
Motion: <10-25 words: one sentence naming ONE character by their referring phrase and the ONE physical action they perform during these {seconds} seconds, then a separate short sentence about the camera, for example "The camera stays static.">
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

One action per shot. {seconds} seconds is enough for one gesture, a few steps, one swing or one turn of the head -- not for a sequence. The Motion: action sentence gives one character one action: never chain actions with "then", "while", "meanwhile", "simultaneously", "afterwards", "followed by" or ", and", never use a semicolon, and never write a second action sentence. When the story needs a sequence -- for example a charge, a draw and a strike -- give each beat its own panel, so a fight or a chase takes several panels. Do not describe appearance, clothing, setting or lighting in Motion: -- that belongs in Image:.

Setting sentences. For each location in the story, write one setting sentence that starts with "The setting is" and names the period, the place, the ground and the light, for example: "The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the ground covered in leaf litter, under flat overcast grey light." Copy that exact sentence, word for word, into the Image: field of every shot at that location.

Fights and touch. Two people never touch on screen. Split every strike, grab, push, thrust or block into two consecutive panels: first a wind-up shot that shows only the attacker (raising the blade, drawing back the arm, lunging forward), then a hard cut to a reaction shot that shows only the person who is hit (recoiling, staggering, clutching the wound, falling). The contact itself is never on screen; the cut implies it. Show a hand-off, a taken hand or a helping hand the same way: one shot of the person who gives or reaches, then one shot of the person who receives. Each of these shots shows one person, and its Motion: names no one else.

Screen direction. Never write "outside the frame", "off-screen", "out of frame" or anything like them, and never name a person who is not in the shot, not even as someone a character looks at. Show who faces whom with fixed screen direction instead: keep each attacker on the left of the frame facing right and each defender on the right facing left (or the reverse), the same way for each pair of characters for the whole fight.

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from shot to shot and by the narration. Each panel should move the action forward instead of repeating the previous panel's action.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls."""
```

- It is 922 words; the brace set is `{story_id, narrative, seconds, panels}`; `\n\nHow this movie is made:` occurs once.
- It contains every test S31 fragment and no "just outside the frame".
- The screen-direction paragraph quotes the banned words on purpose: S11 reads story.md, never the prompt.

### 5.2 Resulting Cast block for kyra + ronin (informative)

```
Cast: these characters have fixed identities that the pipeline already knows how to draw.
- "the woman in grey": a young East Asian woman with fair skin, long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi.
- "the ronin": a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama.
Identity sentences -- copy the one for each of these characters, word for word, into every Image: field that shows them:
- The woman in grey is a young East Asian woman with fair skin, long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi.
- The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama.
Use each quoted phrase above, word for word, as that character's referring phrase everywhere in the file, even when it is longer than four words, and list each of them in the Characters section with exactly the description given above. Every Image: field that shows one of these characters contains that character's identity sentence from the list above, copied word for word -- never shortened, reordered or paraphrased -- and an Image: field that does not show them never names them. Shots that show these characters follow four extra rules. One: at most two of these characters appear in any one shot. Two: a shot that shows one of them is composed around them -- a medium shot or closer, with them in the centre or the foreground of the frame. Three: any other person may appear in such a shot only far in the background, small in the frame, never touching them and never within arm's reach of them; the sentence that mentions that person says "far in the background", the Image: names no other person anywhere else -- not as someone a character looks at, and not even in a possessive -- and the shot's Motion: names none of the other characters; when one of these characters and another person act on each other at close range -- a grab, a blow, a shove -- show it by cutting: first a shot of the other person performing the action, then a separate shot of this character's reaction. Four: when two of these characters share a shot they never touch -- no taken hand, no hand-off, no grappling, embrace or overlap; show a hand-off or a taken hand as two shots, one of each character. A shot that shows none of these characters has none of these extra rules. An animal, such as a horse that a character rides, is not a person, so none of these rules limit it. Bring a cast member on screen only where the narrative calls for them. Every other character still gets a referring phrase of your own, under the rules below.
```

### 5.3 Phase 1: S9 repair and up to two rewrites (ruling 1a, 1b)

**(a) `phase1_story`.** Replace these four lines:

```python
        rc = _run_story_agent(cmd, timeout, story_md)
        if rc:
            return rc
        authored = {"cmd": cmd, "timeout": timeout, "prompt": prompt}
```

with these five:

```python
        before = os.stat(story_md) if os.path.exists(story_md) else None
        rc = _run_story_agent(cmd, timeout, story_md)
        if rc:
            return rc
        authored = {"cmd": cmd, "timeout": timeout, "prompt": prompt, "before": before}
```

The extra key is read only by `_phase1_shots_finish`, so continuous mode is unchanged (offline `OK 344/344`, iterate flags `13 passed`).

**(b) The Phase 1 block.** Replace the region from the line `def _shots_check(lib, story_md, expected_panels, members):` through the final `    return 0` of `_phase1_shots_finish` (`:1107-1185`, ending just before the two blank lines and the `# phase 2: stills` banner comment) with:

```python
def _unused_path(path):
    """path if nothing exists there, else path with -2, -3, ... inserted before its extension:
    the first that does not exist, so a moved-aside or copied draft never replaces an earlier one
    (shots rules v2 spec 5.3)."""
    root, ext = os.path.splitext(path)
    candidate, k = path, 2
    while os.path.lexists(candidate):
        candidate = "%s-%d%s" % (root, k, ext)
        k += 1
    return candidate


def _shots_repair_s9(lib, story_md, members):
    """Insert every missing cast identity sentence into story.md in place (shots rules v2 spec
    5.3; character_lib.repair_cast_descriptions). When anything changes, the unrepaired bytes
    are first copied to story.pre-repair-<UTC stamp>-<pid>.md and one "Repaired S9 on panels
    ..." line is printed. Returns the sorted repaired panel numbers, [] when nothing changed or
    story.md cannot be read or decoded (validation then reports it)."""
    if not members:
        return []
    try:
        with open(story_md, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    repaired_text, repaired = lib.repair_cast_descriptions(text, members)
    if not repaired:
        return []
    keep = _unused_path(os.path.join(
        os.path.dirname(story_md), "story.pre-repair-%s-%d.md"
        % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid())))
    with open(keep, "xb") as f:
        f.write(raw)
    temporary = story_md + ".repair.tmp"
    with open(temporary, "wb") as f:
        f.write(repaired_text.encode("utf-8"))
    os.replace(temporary, story_md)
    panels = sorted({number for number, _name in repaired})
    print("Repaired S9 on panels %s: inserted %d missing cast identity sentence(s); the "
          "unrepaired draft is kept at %s"
          % (",".join(str(n) for n in panels), len(repaired), keep))
    return panels


def _shots_check(lib, story_md, expected_panels, members, repair=False):
    """(violations, advisories) for a shots-mode story.md (shots spec 4). With repair, S9 is
    first repaired in place (shots rules v2 spec 5.3)."""
    if repair:
        _shots_repair_s9(lib, story_md, members)
    try:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return ["story: cannot read story.md: %s" % e], []
    panels = _load_story_panels(story_md)
    return (lib.shots_violations(text, panels, expected_panels, members),
            lib.shots_advisories(panels, members))


def _phase1_shots_finish(args, story_md, authored):
    """Shots-mode Phase 1 after story.md exists (shots spec 5.4; shots rules v2 spec 5.3):
    validate; a draft the story model wrote in this run first gets its missing cast identity
    sentences inserted (S9 repair) and then up to SHOTS_MAX_REWRITES rewrites, each listing only
    the violations still present; then the story dump, the advisories, the cast-phrase warnings
    and the review gate. authored is None when Phase 1 was skipped: no repair, no rewrite. A
    story.md that Phase 1's call left unchanged (authored["before"], an os.stat taken before the
    call) is never repaired or validated: exit 1."""
    lib = _character_lib()
    members = getattr(args, "cast_members", None) or []
    before = (authored or {}).get("before")
    if before is not None and os.path.isfile(story_md):
        now = os.stat(story_md)
        if ((now.st_ino, now.st_mtime_ns, now.st_size)
                == (before.st_ino, before.st_mtime_ns, before.st_size)):
            print("Error: qwen-agent did not write %s; the existing file is unchanged since before "
                  "Phase 1 and was neither validated nor repaired. Rerun the same command to try "
                  "again." % story_md, file=sys.stderr)
            return 1
    violations, advisories = _shots_check(lib, story_md, args.panels, members,
                                          repair=authored is not None)
    if violations and authored is None:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to have "
              "the story model write a new one." % story_md, file=sys.stderr)
        return 2
    if violations and not os.path.isfile(story_md):
        print("Error: qwen-agent exited 0 without writing %s; nothing to rewrite. Rerun the same "
              "command to try again." % story_md, file=sys.stderr)
        return 1
    story_dir = os.path.dirname(story_md)
    rejected = []
    attempt = 0
    while violations:
        if attempt == lib.SHOTS_MAX_REWRITES:
            print("Error: story.md still breaks the shot rules after %d rewrites:" % attempt,
                  file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("The rejected drafts are kept at %s. Hand-edit %s to fix the violations above "
                  "and rerun (Phase 1 is skipped while story.md exists), or rerun with "
                  "--force-story." % (", ".join(rejected), story_md), file=sys.stderr)
            return 2
        attempt += 1
        moved = _unused_path(os.path.join(story_dir, "story.rejected-%s-%d.md"
                                          % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                                             os.getpid())))
        if attempt == 1:
            print("Warning: the story model's draft broke the shot rules; moving it to %s and "
                  "asking for rewrite 1 of %d:" % (moved, lib.SHOTS_MAX_REWRITES))
        else:
            print("Warning: rewrite %d still breaks the shot rules; moving it to %s and asking for "
                  "rewrite %d of %d:" % (attempt - 1, moved, attempt, lib.SHOTS_MAX_REWRITES))
        for v in violations:
            print("  - %s" % v)
        os.replace(story_md, moved)
        rejected.append(moved)
        rewrite = authored["prompt"] + "\n\n" + lib.shots_rewrite_block(violations, args.panels)
        name = ("story_prompt.rewrite.txt" if attempt == 1
                else "story_prompt.rewrite-%d.txt" % attempt)
        with open(os.path.join(story_dir, name), "w", encoding="utf-8") as f:
            f.write(rewrite)
        cmd = list(authored["cmd"])
        cmd[-1] = rewrite
        print("=== Phase 1: story (rewrite %d of %d) ===" % (attempt, lib.SHOTS_MAX_REWRITES))
        rc = _run_story_agent(cmd, authored["timeout"], story_md)
        if not rc and not os.path.isfile(story_md):
            print("Error: qwen-agent exited 0 without writing %s" % story_md, file=sys.stderr)
            rc = 1
        if rc:
            if os.path.isfile(story_md):
                moved = _unused_path(os.path.join(story_dir, "story.rejected-%s-%d.md"
                                                  % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                                                     os.getpid())))
                os.replace(story_md, moved)
                rejected.append(moved)
            print("Error: shots rewrite %d of %d failed; the rejected draft(s) are kept at %s"
                  % (attempt, lib.SHOTS_MAX_REWRITES, ", ".join(rejected)), file=sys.stderr)
            return rc
        violations, advisories = _shots_check(lib, story_md, args.panels, members, repair=True)
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)
    for a in advisories:
        print("Warning: %s" % a)
    if members:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    for m in members:
        if not lib.phrase_occurs(text, m.phrase):
            print("Warning: story.md does not use cast phrase %r; character %s gets no LoRA in "
                  "this story" % (m.phrase, m.name))
    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")
    return 0
```

Decisions **[spec choice]**:

- **Both rewrites use the same `cmd` and timeout.** Rewrite k's prompt is `authored["prompt"] + "\n\n" + shots_rewrite_block(<violations of the latest draft>, panels)`, so the second rewrite lists only what is still wrong after rewrite 1, never a cumulative list. The prompt is the same size each time (Section 9).
- **Audit records.** `story_prompt.rewrite.txt` holds rewrite 1's prompt (unchanged name) and `story_prompt.rewrite-2.txt` holds rewrite 2's. A `story_prompt.rewrite-2.txt` left by an earlier run survives a later run that needed only one rewrite; check its mtime against `story_prompt.txt`.
- **Drafts are moved aside, never overwritten.** Every rejected draft gets `story.rejected-<stamp>-<pid>.md`, or `…-2.md`, `…-3.md` when that exists (`_unused_path`). Two moves within the same second (test runs) therefore keep both drafts. The first name is unchanged, so test S36's name regex holds.
- **A failed rewrite that left a story.md moves it aside (re-review Important 2).** On any rewrite failure (`rc` nonzero), an existing story.md is moved through `_unused_path` and appended to the rejected list before E-S11 is printed. The likely case is a timeout after `write_file`. A plain rerun therefore authors a fresh draft instead of hitting E-S9 on an unrepaired story.
- **An unchanged story.md is never repaired (re-review Minor 2).** See 4.1. `authored["before"]` is compared on `(st_ino, st_mtime_ns, st_size)`.
- **The repair's file handling.**
  - The unrepaired **bytes** are copied with `open(…, "xb")`, so the copy is byte-identical even with CRLF line endings.
  - story.md is replaced via `story.md.repair.tmp` + `os.replace`.
  - One stdout line is printed: `Repaired S9 on panels <N,M>: inserted <k> missing cast identity sentence(s); the unrepaired draft is kept at <path>`.
  - The repair runs before the first validation and again after each rewrite.

### 5.4 Error messages (replacing shots spec 7.2 E-S10, E-S11)

| # | Condition | Exit / effect |
|---|---|---|
| E-S9 | pre-existing story.md violates | unchanged (exit 2, no repair) |
| E-S10 | still violating after 2 rewrites | 2. stderr `Error: story.md still breaks the shot rules after 2 rewrites:`, then one `  - <violation>` line each, then `The rejected drafts are kept at <r1>, <r2>. Hand-edit <story.md> to fix the violations above and rerun (Phase 1 is skipped while story.md exists), or rerun with --force-story.` |
| E-S11 | qwen-agent fails during rewrite k (timeout, nonzero exit with no story.md, or exit 0 without writing) | 1. The existing qwen-agent error, then `Error: shots rewrite <k> of 2 failed; the rejected draft(s) are kept at <r1>[, <r2>]`. A story.md left by the failed rewrite is moved aside too, so a plain rerun authors a fresh draft |
| E-S19 | Phase 1's call (first draft) left an existing story.md unchanged (`--force-story`) | 1. `Error: qwen-agent did not write <story.md>; the existing file is unchanged since before Phase 1 and was neither validated nor repaired. Rerun the same command to try again.` Nothing is repaired, moved or validated |
| -- | rewrite 1 warning (stdout) | `Warning: the story model's draft broke the shot rules; moving it to <r1> and asking for rewrite 1 of 2:` plus the violation list |
| -- | rewrite 2 warning (stdout) | `Warning: rewrite 1 still breaks the shot rules; moving it to <r2> and asking for rewrite 2 of 2:` plus the violation list |
| -- | header | `=== Phase 1: story (rewrite <k> of 2) ===` (was `=== Phase 1: story (rewrite) ===`) |

### 5.5 Result check

After 5.1 and 5.3 (a)-(b), `bin/ltx-movie` is 1913 lines with sha256 `7c4315dbeb467a8fb09bbf99a783ce8da3aa1ac8af97e919a4c64eebe206bfc3` (base `b202a074…`).

There is no docstring or help-text change **[spec choice]**. The module docstring's shots paragraph ("asking the story model for one rewrite") is now imprecise. I leave it, because the user's rule is to change only what the task needs. It is noted in G-R20.

---

## 6. Rewrite pressure

### 6.1 Decisions

| Question | Decision |
|---|---|
| Group the block? | **Yes [spec choice].** Grouped by rule under one `SHOTS_RULE_GUIDANCE` line, in rule order. Identical details merge into `- panels 2, 3, 4: <detail>` |
| Cap? | **`SHOTS_REWRITE_MAX_LISTED = 40` merged lines; headers are not counted.** "and N more" counts violations (test S94). Test S19 is unchanged |
| Extra instruction? | **Yes.** `SHOTS_REWRITE_TEMPLATE` adds the split-contact and copy-exactly sentences. S9 details carry the identity sentence |
| S9 load on the model? | **Removed by the repair (ruling 1a).** The model never sees an S9 line for a repairable draft |
| How many rewrites? | **Up to 2 (ruling 1b),** each listing only the current violations. A third is out of scope |
| Include the rejected draft? | No: an edit-mode rewrite does not fit the budget (0.4) |

### 6.2 Measured block sizes (reference code, live descriptors)

| Story (first draft) | Violations raw → after S9 repair | Merged `- ` lines | Block chars | Est. tokens (`len(json.dumps(block)) // 3`) |
|---|---|---|---|---|
| rules-as-generated (20 panels) | 41 → **19** | 16 → 14 | 3682 → 2899 | 1239 → **977** |
| full20 (20 panels) | 52 → 34 | 13 → 11 | 3434 → 2666 | 1159 → 902 |

- The raw block is the 7.2 text. **The as-generated rules story's rewrite actually sees the 19-violation, 977-token block, also in 7.2.**
- Since revision 1, the S12 message is longer, which moves full20's raw block from 3378 to 3434 characters. No other number in 6.2 changed.

### 6.3 Why S12 is fatal [spec choice]

- **Cost.** Prose compliance was 20/20, and the fix is copying one sentence.
- **Benefit.** Without a setting line, extras-only shots lose their period (ls1).
- **The check is exact.** M1 adds the 12-word floor, so a stub ("The setting is the same as before.") cannot satisfy it.

---

## 7. False-positive / false-negative analysis

All numbers are from the reference code with the live descriptors.

### 7.1 Corpus results

| Story | Raw total | By rule | After S9 repair | Notes |
|---|---|---|---|---|
| `windup.md` (as stored) | 6 | S10 ×3 ('attacker', 'attacker', 'robber'), S11 ×3 | 6 | **[interpretation] (C1 accepted)** |
| `windup-v2` | **0** | -- | 0 | "must pass with zero" |
| `rules-as-generated.md` | 41 | S7 ×1, S8 ×7, S9 ×22, S10 ×11 | **19** (S7 ×1, S8 ×7, S10 ×11) | The brief's catches all hold (see below) |
| `rules-edited.md` | 39 | S8 ×6, S9 ×22, S10 ×11 | 17 | -- |
| `full20.md` | 52 | S9 ×18, S10 ×14, S12 ×20 | 34 | S8 ×0 (G-R1) |
| `ls1.md` | 25 | S8 ×3, S9 ×2, S10 ×6, S12 ×14 | 23 | P9 'woman'/'robbers' and P10 are the documented bleeds |

**Revision 2 changes nothing here.** F2, F3, M1, M2, M3 and the new verbs leave every raw count and projection exactly as in revision 1 (measured). Only the S12 message text changed.

The as-generated rules story is still caught where it was:

- P6 by S10 ('robber leader');
- P7 by S8 (Image: 'strikes' → 'robber leader') and by S10;
- P11 by S8 ×2 and by S10;
- the 22 S9 cases, now repaired;
- P17/P18 by S10 ('shogun'); P18 also by S7 and S8 ×2;
- P2 horse: exempt;
- P14: S8 ×2 (cast–cast hand, C2 accepted);
- P8, P9, P12, P16, P19, P20: S10.

### 7.2 The rules-as-generated rewrite blocks (reference output, exact)

Raw draft:

```
REWRITE REQUIRED. Your previous draft of this file was rejected because it broke these rules:
S7 cast and extra -- a Motion: never names a Cast character together with another person; give the other person's action its own shot, then cut to the Cast character's reaction:
- panel 18: Motion: names 'the ronin' together with 'shogun'; show the other character's action in its own shot, then cut to the cast character's reaction
S8 contact -- two people never touch on screen; replace each of these shots with a wind-up shot that shows only the person acting and a reaction shot that shows only the person acted on, each with a Motion: that names only that person:
- panel 7: Image: 'strikes' acts on 'robber leader'; two people touching on screen
- panel 11: Motion: 'disarming' acts on 'robber'; two people touching on screen
- panel 11: Image: 'disarms' acts on 'robber'; two people touching on screen
- panel 14: Motion: 'takes' acts on 'the ronin'; two people touching on screen
- panel 14: Image: 'taking' acts on 'the ronin'; two people touching on screen
- panel 18: Motion: 'hands' acts on 'the ronin'; two people touching on screen
- panel 18: Image: 'handing' acts on 'the ronin'; two people touching on screen
S9 cast description -- every Image: that names a Cast character contains that character's identity sentence, copied word for word; an Image: that does not show them does not name them:
- panels 1, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20: Image: names 'the ronin' without character ronin's description word for word; copy in this sentence: The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama.
- panels 2, 3, 4, 6, 7, 13, 14, 15, 16: Image: names 'the woman in grey' without character kyra's description word for word; copy in this sentence: The woman in grey is a young East Asian woman with fair skin, long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi.
S10 extra in cast shot -- in a shot that shows a Cast character, leave every other person out of the Image:, or place them far in the background, small in the frame, and write "far in the background" in the sentence that mentions them:
- panels 6, 7: Image: names 'robber leader' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence
- panel 8: Image: names 'robbers' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panel 9: Image: names 'robber leader' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panels 11, 12: Image: names 'robber' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panel 16: Image: names 'shogun' in a shot that shows kyra, ronin, without "far in the background" or another distance cue in that sentence
- panels 17, 18, 19, 20: Image: names 'shogun' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
Write the complete file again from the beginning, following every instruction above and fixing every listed problem. Keep EXACTLY 20 panel sections. Where a Motion: held more than one action, keep only its single most important action and give the other beats their own panels instead. Where a shot showed two people touching, replace it with a wind-up shot of the one acting and a reaction shot of the one acted on. Merge or drop minor beats so that the panel count stays the same. Copy every identity sentence and every setting sentence exactly as written, without shortening or rewording it.
```

After the S9 repair (what rewrite 1 actually sees):

```
REWRITE REQUIRED. Your previous draft of this file was rejected because it broke these rules:
S7 cast and extra -- a Motion: never names a Cast character together with another person; give the other person's action its own shot, then cut to the Cast character's reaction:
- panel 18: Motion: names 'the ronin' together with 'shogun'; show the other character's action in its own shot, then cut to the cast character's reaction
S8 contact -- two people never touch on screen; replace each of these shots with a wind-up shot that shows only the person acting and a reaction shot that shows only the person acted on, each with a Motion: that names only that person:
- panel 7: Image: 'strikes' acts on 'robber leader'; two people touching on screen
- panel 11: Motion: 'disarming' acts on 'robber'; two people touching on screen
- panel 11: Image: 'disarms' acts on 'robber'; two people touching on screen
- panel 14: Motion: 'takes' acts on 'the ronin'; two people touching on screen
- panel 14: Image: 'taking' acts on 'the ronin'; two people touching on screen
- panel 18: Motion: 'hands' acts on 'the ronin'; two people touching on screen
- panel 18: Image: 'handing' acts on 'the ronin'; two people touching on screen
S10 extra in cast shot -- in a shot that shows a Cast character, leave every other person out of the Image:, or place them far in the background, small in the frame, and write "far in the background" in the sentence that mentions them:
- panels 6, 7: Image: names 'robber leader' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence
- panel 8: Image: names 'robbers' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panel 9: Image: names 'robber leader' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panels 11, 12: Image: names 'robber' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
- panel 16: Image: names 'shogun' in a shot that shows kyra, ronin, without "far in the background" or another distance cue in that sentence
- panels 17, 18, 19, 20: Image: names 'shogun' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence
Write the complete file again from the beginning, following every instruction above and fixing every listed problem. Keep EXACTLY 20 panel sections. Where a Motion: held more than one action, keep only its single most important action and give the other beats their own panels instead. Where a shot showed two people touching, replace it with a wind-up shot of the one acting and a reaction shot of the one acted on. Merge or drop minor beats so that the panel count stays the same. Copy every identity sentence and every setting sentence exactly as written, without shortening or rewording it.
```

### 7.3 Known false-negative and false-positive classes (G-list)

- **G-R1. Possessive and weapon-only targets are not targets.** Each of these passes S8:
  - "swings his blade downward, aiming for her neck" (full20 P7; still caught by S10);
  - from the L-R1 narrative's own wording (F6): "snatches the letter from her sash", "knocks the short sword from his hand", "knocks the axe handle aside", "striking his wrist".

  Gender agreement is out of scope. These are pinned in test S84 where present.
- **G-R2. Handoff verb gaps.**
  - "gives the ronin a scroll" passes (no "to"; pinned).
  - "returns to the woman in grey" fires as a handoff, although it is walking back to her (measured; an accepted false positive).
  - "passes" is not a handoff verb.
- **G-R3. Contacts in a camera clause are skipped** ("the camera follows as he strikes the robber").
- **G-R4 (extended, F3). The class-noun skip.** A cast member's class noun is skipped only in the appositive right after that member's phrase. Any second person who shares a cast member's class noun is flagged elsewhere, but is missed inside that appositive window.
- **G-R5.** "the Shogun's daughter" in kyra's Image: is flagged as 'shogun'. The prompt forbids naming others, even in a possessive.
- **G-R6.** "He stays static." counts as a camera sentence (test S91).
- **G-R7.** The person-noun list is closed (no "farmer").
- **G-R8.** S12 checks presence and length, not that one location reuses one sentence.
- **G-R9.** A cue anywhere in a sentence exempts every person in it.
- **G-R10. Wide sweep (measured with the final code).**
  - Over all 59 `generated/stories/*/story.md` (527 unique Motion: action sentences, 646 unique Image: sentences), `find_contact` hits 37 + 6.
  - That is unchanged from revision 1: F2 and the new verbs changed no hit there.
  - Manual review of the revision-1 hits found all of them to be real contact beats. One is right for the wrong reason.
- **G-R11.** Two rewrites may still not converge. The trials in 10.2a measure that.
- **G-R12.** Gaze must be expressed as screen direction; eyeball in L-R1.
- **G-R13.** Cast–cast contact must be split; eyeball the split hand-off in L-R1 (C2).
- **G-R14.** Judges still assume continuous mode.
- **G-R15.** "pushes the gate open for the villagers" still fires (no "for" in `_SPATIAL_RE`, F2 as worded).
- **G-R16.** S11 false positive "beyond the frame of the temple gate" (accepted, pinned).
- **G-R17. The repair asserts presence.** Any cast character an Image: names gets their identity sentence, including one named only as an addressee ("speaks to "the ronin""). The pipeline already treats such a shot as showing them: `cast_text` loads their stills LoRA. One repair pass is not always a fixpoint: if member A's descriptor contains member B's phrase and B comes first in members order, a second pass repairs B. This is a known gap, measured only with a contrived descriptor; no code handles it.
- **G-R18. The repair's sentence-end search** stops at an abbreviation ("Mt. Fuji") and inserts there. It also stops at an ellipsis: "the ronin... kneeling." gets the sentence inserted before the lowercase fragment "kneeling.". And it stops at a trailing open quote: `kneeling "` becomes `kneeling ". The ronin is …`. Neither creates a violation, but the text sent to the image model is mangled.
- **G-R19. M3 leaves some person-noun false positives:** "samurai sword", "no other people are visible". The reviewer's measured list beyond `guard`/`general`/possessives was not part of the accepted edit.
- **G-R20.** `bin/ltx-movie`'s module docstring still says "one rewrite" (5.5).

---

## 8. Tests

### 8.1 Fixtures

**Corpus files** (D4) live in `tests/fixtures/shots_rules_v2/`. Copy each byte-for-byte with `cp`, then verify its sha256 (test S95 re-verifies).

| Fixture file | Source | sha256 |
|---|---|---|
| `windup.md` | `WS/generated/stories/ronin-shots-windup-20261008/story.md` | `b52b17348d7ff9add08a7202ff49632cbc6043ac994062cd69d33848cdacec85` |
| `rules-as-generated.md` | `/Users/reubenpatterson/local_model_harness/.superpowers/sdd/2026-10-06-shots-mode/live/rules-story.as-generated.md` | `b21ba27f8c0dfe31510a8dbe8024ea7047cfd8418cd283ef279fe815f1a33a63` |
| `rules-edited.md` | `WS/generated/stories/ronin-shots-rules-20261009/story.md` | `88dda540b2fb8da4800d35ce28264592ba27b4640b41aace3fc19912de455753` |
| `full20.md` | `WS/generated/stories/ronin-shots-full-20261007/story.md` | `f4ea6f71f7055f6b49c6bdd98636bc5676c118b1062f43eb1cda3a001027e7b6` |
| `ls1.md` | `WS/generated/stories/ronin-rescue-shots-ls1/story.md` | `b2c97fa050e87b2da8a483a1550ebc74c197f4777c2bc6b64440b97effd632d9` |

windup-v2 is built in the tests (`WINDUP_V2_EDITS`, sha256 `1a3d891d…` checked in `_corpus()`).

### 8.2 Changes to existing tests (exact; replace each whole item by script)

**(a)** Replace `SHOTS_OK` with:

```python
SHOTS_OK = """# Forest Rescue

A ronin saves a woman from a robber on a forest trail.

## Characters
- "the woman in grey": a young woman with long black hair pinned up with jade hairpins wearing a grey kimono
- "the ronin": a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori
- "the bearded robber": a stocky man with a black beard in a ragged brown jacket

## Panel 1 — The Trail
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium shot of the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing in the centre of a mossy cedar trail and facing right. Far behind her on the left, small in the frame, the bearded robber watches from the ferns. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The woman in grey turns her head slowly toward the ferns on her right. The camera stays static.
Narration: She senses she is not alone.

## Panel 2 — The Robber
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing left. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The bearded robber lunges forward out of the ferns with his short knife raised. The camera stays static.
Narration: A robber springs from cover.

## Panel 3 — The Ronin
Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft with moss, under soft overcast light. A medium shot of the ronin, a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori, and the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing an arm's length apart on the mossy cedar trail, the ronin on the left facing right. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The ronin offers his open hand to the woman in grey. The camera stays static.
Narration: Help arrives.
"""
```

and `PANEL_2_IMAGE` with:

```python
PANEL_2_IMAGE = ("Image: The setting is a mossy cedar trail in feudal Japan, ferns on both sides, "
                 "the ground soft with moss, under soft overcast light. A medium close-up of the bearded robber, a stocky man with a black beard in "
                 "a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing "
                 "left. Soft overcast light, muted green palette, eye-level camera, photorealistic "
                 "film still.\n")
```

**(b)** Replace test S3 with:

```python
def test_s3_shots_cast_block(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    m = _members("kyra", "ronin")
    lib = character_lib
    assert lib.build_cast_block(m, shots=True) == (
        lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
        + '- "the ronin": ' + DESC_R + "." + "\n" + lib.SHOTS_IDENTITY_HEADER + "\n"
        + "- The woman in grey is " + DESC_K + "." + "\n" + "- The ronin is " + DESC_R + "."
        + "\n" + lib.SHOTS_CAST_BLOCK_RULES)
    continuous = (lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
                  + '- "the ronin": ' + DESC_R + "." + "\n" + lib.CAST_BLOCK_RULES)
    assert lib.build_cast_block(m) == continuous
    assert lib.build_cast_block(m, shots=False) == continuous
    rules = lib.SHOTS_CAST_BLOCK_RULES
    assert "{" not in rules and "}" not in rules and "%" not in rules
    assert rules.count("word for word") == 2
    for fragment in ("at most two of these characters", "a medium shot or closer",
                     "never within arm's reach", "show it by cutting",
                     "identity sentence from the list above, copied word for word",
                     'says "far in the background"', "not even in a possessive",
                     "they never touch -- no taken hand, no hand-off",
                     "An animal, such as a horse that a character rides, is not a person",
                     "has none of these extra rules"):
        assert fragment in rules, fragment
```

**(c)** Replace test S14 with:

```python
def test_s14_violations_name_panel_and_rule(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_3_MOTION, "Motion: The ronin offers his hand then pulls the woman in "
                                    "grey to her feet on the trail.")
    assert _violations(tmp_path, text, members) == [
        "panel 3: S5 one action: Motion: chains actions with 'then'",
        "panel 3: S8 contact: Motion: 'pulls' acts on 'the woman in grey'; two people touching on "
        "screen"]
```

**(d)** Replace test S16 with:

```python
def test_s16_s7_cast_and_extra(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_1_MOTION, "Motion: The woman in grey pushes the bearded robber away from "
                                    "her with both hands.")
    assert _violations(tmp_path, text, members) == [
        "panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction",
        "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'; two people touching "
        "on screen"]
    assert _violations(tmp_path, SHOTS_OK, members) == []
```

**(e)** Replace test S18 with:

```python
def test_s18_shots_advisories(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)

    def advise(text, cast=members):
        return character_lib.shots_advisories(_panels(tmp_path, text), cast)

    assert advise(SHOTS_OK) == []
    assert advise(_variant("grey kimono, standing in the centre", "grey robe, standing in the centre")) == []
    assert advise(_variant("A medium shot of the woman in grey", "A wide shot of the woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is wide shot; a shot with "
        "a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium shot of the woman in grey", "The woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is not stated; a shot "
        "with a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium close-up of the bearded robber",
                           "A wide shot of the bearded robber")) == []
    assert advise(SHOTS_OK, cast=[]) == []
```

**(f)** Replace test S36. Only its warning line changes, to "rewrite 1 of 2".

```python
def test_s36_one_rewrite(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    first, second = agent.calls[0]["cmd"], agent.calls[1]["cmd"]
    assert agent.calls[1]["existed"] is False
    assert second[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3)
    assert second[:-1] == first[:-1]
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert re.fullmatch(r"story\.rejected-\d{8}T\d{6}Z-%d\.md" % os.getpid(),
                        os.path.basename(rejected[0]))
    with open(rejected[0], encoding="utf-8") as f:
        assert f.read() == BAD
    assert (directory / "story_prompt.rewrite.txt").read_text(encoding="utf-8") == second[-1]
    assert (directory / "story_prompt.txt").read_text(encoding="utf-8") == first[-1]
    lines = out.splitlines()
    runs = [line.split(":")[0] for line in lines if line.startswith("Running (timeout ")]
    assert len(runs) == 2 and runs[0] == runs[1]
    warning = next(i for i, line in enumerate(lines)
                   if line.startswith("Warning: the story model's draft broke the shot rules; "
                                      "moving it to %s and asking for rewrite 1 of 2:"
                                      % rejected[0]))
    assert lines[warning + 1:warning + 3] == ["  - " + v for v in BAD_VIOLATIONS]
```

**(g)** Replace test S37. It is renamed `test_s37_third_failure_exits_2`: three bad drafts, two rejected files, E-S10 "after 2 rewrites", and an order-independent path check.

```python
def test_s37_third_failure_exits_2(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD, BAD])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert len(agent.calls) == 3
    assert "Error: story.md still breaks the shot rules after 2 rewrites:" in err
    for v in BAD_VIOLATIONS:
        assert "  - " + v in err.splitlines()
    rejected = _rejected(directory)
    assert len(rejected) == 2
    kept = next(line for line in err.splitlines()
                if line.startswith("The rejected drafts are kept at "))
    assert sorted(kept[len("The rejected drafts are kept at "):].split(". Hand-edit ")[0]
                  .split(", ")) == rejected
    for path in rejected:
        with open(path, encoding="utf-8") as f:
            assert f.read() == BAD
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == BAD
```

**(h)** Replace test S39 (the new E-S11 text):

```python
def test_s39_rewrite_agent_failure(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, None], returncodes=[0, 1])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: qwen-agent exited 1 while authoring story.md" in err
    assert "Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept at " in err
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert os.path.isfile(rejected[0])
    agent = _FakeStoryAgent(monkeypatch, story_md, [None])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    assert "Error: qwen-agent exited 0 without writing %s" % story_md in capsys.readouterr().err
    assert _rejected(directory) == rejected
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, None])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: qwen-agent exited 0 without writing %s" % story_md in err
    assert "Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept at " in err
```

**(i)** Replace the line `PARAPHRASED = _variant(...)` with the block below (it adds `WIDE`, `WIDE_WARNING`; `PARAPHRASED` stays):

```python
PARAPHRASED = _variant("grey kimono, standing in the centre", "grey robe, standing in the centre")
WIDE = _variant("A medium shot of the woman in grey", "A wide shot of the woman in grey")
WIDE_WARNING = ("Warning: panel 1: shows cast character(s) kyra but its Image: shot type is wide "
                "shot; a shot with a cast character should be a medium shot or closer")
```

and replace test S40 with:

```python
def test_s40_advisories_are_not_fatal(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [WIDE])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert WIDE_WARNING in capsys.readouterr().out.splitlines()
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, WIDE])
    gate = []
    monkeypatch.setattr("builtins.input", lambda prompt="": gate.append(prompt) or "")
    argv = [a for a in SHOTS_ARGV if a != "--no-review"] + ["--force-story"]
    assert ltx_movie.phase1_story(_shots_args(*argv)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    assert gate == ["Review story.md above. Enter to continue, Ctrl-C to abort: "]
    dump = out.index("=== story.md ===\n" + WIDE)
    assert out.index(WIDE_WARNING) > dump
```

**(j)** Replace the module docstring's first two lines with:

```python
"""Tests for shots mode (spec docs/superpowers/specs/2026-10-06-shots-mode-design.md
Section 10, S1-S72) and shots rules v2 (docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md
Section 8: S21, S54-S59, S80-S99).
```

With (a)-(j) applied and none of 8.3 added, the existing 54 tests pass against the v2 code (measured: `54 passed`).

### 8.3 New tests (append this block at the end of `tests/test_shots_mode.py`)

```python
# --- shots rules v2 (docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md, Section 8) ----
FIXTURES_V2 = os.path.join(WS, "tests", "fixtures", "shots_rules_v2")
FIXTURE_SHA256 = {
    "windup.md": "b52b17348d7ff9add08a7202ff49632cbc6043ac994062cd69d33848cdacec85",
    "rules-as-generated.md": "b21ba27f8c0dfe31510a8dbe8024ea7047cfd8418cd283ef279fe815f1a33a63",
    "rules-edited.md": "88dda540b2fb8da4800d35ce28264592ba27b4640b41aace3fc19912de455753",
    "full20.md": "f4ea6f71f7055f6b49c6bdd98636bc5676c118b1062f43eb1cda3a001027e7b6",
    "ls1.md": "b2c97fa050e87b2da8a483a1550ebc74c197f4777c2bc6b64440b97effd632d9",
}
WINDUP_V2_SHA256 = "1a3d891d0442db0a9ddd1c6819cf3cf6506f1425dd98a815cb39ee6040dcd085"
WINDUP_V2_EDITS = (
    ("facing left toward an attacker just outside the frame, her eyes wide", "facing left, her eyes wide"),
    ("her eyes fixed on the attacker outside the frame.", "her eyes fixed on the left of the frame."),
    ("his eyes hard and fixed on the robber outside the frame.", "his eyes hard and fixed on the left of the frame."),
)
DESC_K_LIVE = ("a young East Asian woman with fair skin, long black hair pinned up with three jade "
               "hairpins, wearing a pale grey silk kimono with a silver obi")
DESC_R_LIVE = ("a lean man in his late thirties with a topknot and a scarred brow, wearing a faded "
               "indigo haori and dark hakama")
HUM = ["the woman in grey", "the ronin", "the bearded robber"]
ANI = ["the dark bay horse"]
DES = [DESC_K, DESC_R, "a stocky man with a black beard in a ragged brown jacket"]
P1_SENT = "Far behind her on the left, small in the frame, the bearded robber watches from the ferns."
P2_MOTION = ("Motion: The bearded robber lunges forward out of the ferns with his short knife raised. "
             "The camera stays static.")
M1_MOTION = "Motion: The woman in grey turns her head slowly toward the ferns on her right."
SET = ("The setting is a mossy cedar trail in feudal Japan, ferns on both sides, the ground soft "
       "with moss, under soft overcast light. ")
REST_2 = ("A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown "
          "jacket, crouching among ferns on a mossy cedar trail and facing left.")
IMG_2 = "crouching among ferns on a mossy cedar trail and facing left."
ROSTER_HORSE = _variant('- "the bearded robber":',
                        '- "the dark bay horse": a dark bay horse with a white blaze\n'
                        '- "the bearded robber":')
ROSTER_RIDER = _variant('- "the bearded robber":',
                        '- "the rider": a young man in a straw hat\n'
                        '- "the rider\'s horse": a grey mare with a rope bridle\n'
                        '- "the bearded robber":')
S7_LINE_1 = ("panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the "
             "bearded robber'; show the other character's action in its own shot, then cut to the "
             "cast character's reaction")
S8_TAIL = "; two people touching on screen"
S9_KYRA_1 = ("panel 1: S9 cast description: Image: names 'the woman in grey' without character "
             "kyra's description word for word; copy in this sentence: The woman in grey is "
             + DESC_K + ".")
S10_TAIL = ', without "far in the background" or another distance cue in that sentence'
S11_TAIL = "; use left and right screen direction instead"
S12_LINE = ('S12 setting sentence: Image: has no setting sentence of at least 12 words starting '
            '"The setting is"')
CORPUS_PROJ = {
    'windup.md': (6,
        '2:S10 2:S11 3:S10 3:S11 5:S10 5:S11'),
    'windup-v2': (0,
        ''),
    'rules-as-generated.md': (41,
        '1:S9 2:S9 3:S9 4:S9 6:S9 6:S10 7:S8 7:S9 7:S10 8:S9 8:S10 9:S9 9:S10 11:S8 11:S8 11:S9 11:S10 12:S9 12:S10 13:S9 13:S9 14:S8 14:S8 14:S9 14:S9 15:S9 15:S9 16:S9 16:S9 16:S10 17:S9 17:S10 18:S7 18:S8 18:S8 18:S9 18:S10 19:S9 19:S10 20:S9 20:S10'),
    'rules-edited.md': (39,
        '1:S9 2:S9 3:S9 4:S9 6:S9 6:S10 7:S8 7:S9 7:S10 8:S9 8:S10 9:S9 9:S10 11:S8 11:S8 11:S9 11:S10 12:S9 12:S10 13:S9 13:S9 14:S8 14:S8 14:S9 14:S9 15:S9 15:S9 16:S9 16:S9 16:S10 17:S9 17:S10 18:S8 18:S9 18:S10 19:S9 19:S10 20:S9 20:S10'),
    'full20.md': (52,
        '1:S9 1:S12 2:S9 2:S12 3:S12 4:S9 4:S12 5:S9 5:S12 6:S12 7:S9 7:S10 7:S10 7:S12 8:S9 8:S10 8:S10 8:S12 9:S9 9:S10 9:S10 9:S12 10:S9 10:S10 10:S12 11:S9 11:S9 11:S10 11:S10 11:S12 12:S9 12:S9 12:S12 13:S9 13:S9 13:S12 14:S12 15:S12 16:S9 16:S10 16:S12 17:S9 17:S10 17:S12 18:S12 19:S9 19:S10 19:S10 19:S12 20:S9 20:S10 20:S12'),
    'ls1.md': (25,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S8 11:S9 11:S10 11:S10 11:S12 12:S12 13:S8 13:S10 13:S12 14:S8 14:S9 14:S12'),
}
REPAIRED_PROJ = {
    'windup.md': (6, 0,
        '2:S10 2:S11 3:S10 3:S11 5:S10 5:S11'),
    'windup-v2': (0, 0,
        ''),
    'rules-as-generated.md': (19, 22,
        '6:S10 7:S8 7:S10 8:S10 9:S10 11:S8 11:S8 11:S10 12:S10 14:S8 14:S8 16:S10 17:S10 18:S7 18:S8 18:S8 18:S10 19:S10 20:S10'),
    'rules-edited.md': (17, 22,
        '6:S10 7:S8 7:S10 8:S10 9:S10 11:S8 11:S8 11:S10 12:S10 14:S8 14:S8 16:S10 17:S10 18:S8 18:S10 19:S10 20:S10'),
    'full20.md': (34, 18,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S10 7:S10 7:S12 8:S10 8:S10 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S10 11:S10 11:S12 12:S12 13:S12 14:S12 15:S12 16:S10 16:S12 17:S10 17:S12 18:S12 19:S10 19:S10 19:S12 20:S10 20:S12'),
    'ls1.md': (23, 2,
        '1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S10 9:S10 9:S12 10:S10 10:S12 11:S8 11:S10 11:S10 11:S12 12:S12 13:S8 13:S10 13:S12 14:S8 14:S12'),
}
S96_LINES = [
    ('rules-as-generated.md',
     "panel 7: S8 contact: Image: 'strikes' acts on 'robber leader'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 11: S8 contact: Motion: 'disarming' acts on 'robber'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 11: S8 contact: Image: 'disarms' acts on 'robber'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 14: S8 contact: Motion: 'takes' acts on 'the ronin'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 14: S8 contact: Image: 'taking' acts on 'the ronin'; two people touching on screen"),
    ('rules-as-generated.md',
     "panel 18: S7 cast and extra: Motion: names 'the ronin' together with 'shogun'; show the other character's action in its own shot, then cut to the cast character's reaction"),
    ('rules-as-generated.md',
     'panel 6: S10 extra in cast shot: Image: names \'robber leader\' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence'),
    ('rules-as-generated.md',
     'panel 17: S10 extra in cast shot: Image: names \'shogun\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('rules-as-generated.md',
     "panel 1: S9 cast description: Image: names 'the ronin' without character ronin's description word for word; copy in this sentence: The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama."),
    ('ls1.md',
     'panel 9: S10 extra in cast shot: Image: names \'woman\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 9: S10 extra in cast shot: Image: names \'robbers\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 10: S10 extra in cast shot: Image: names \'stocky bearded robber\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('ls1.md',
     'panel 13: S8 contact: Motion: \'cuts\' acts on "robber\'s"; two people touching on screen'),
    ('ls1.md',
     "panel 14: S8 contact: Motion: 'help' acts on 'her'; two people touching on screen"),
    ('windup.md',
     'panel 2: S10 extra in cast shot: Image: names \'attacker\' in a shot that shows kyra, without "far in the background" or another distance cue in that sentence'),
    ('windup.md',
     "panel 2: S11 off-screen wording: Image: says 'outside the frame'; use left and right screen direction instead"),
    ('full20.md',
     'panel 19: S10 extra in cast shot: Image: names \'shogun\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('full20.md',
     'panel 19: S10 extra in cast shot: Image: names \'woman\' in a shot that shows ronin, without "far in the background" or another distance cue in that sentence'),
    ('full20.md',
     'panel 1: S12 setting sentence: Image: has no setting sentence of at least 12 words starting "The setting is"'),
]


def _p1(new, text=None):
    return _variant(P1_SENT, new, text)


def _v(tmp_path, text, members):
    return character_lib.shots_violations(text, _panels(tmp_path, text), 3, members)


def _proj(violations):
    """'N:Sx' per panel violation, space-joined (shots rules v2 spec 8.4)."""
    assert all(v.startswith("panel ") for v in violations)
    return " ".join(re.match(r"panel (\d+): (S\d+) ", v).expand(r"\1:\2") for v in violations)


def _live_members(lib_dir):
    make_character(lib_dir, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K_LIVE)
    make_character(lib_dir, "ronin", "roninmn", "the ronin", "man", DESC_R_LIVE)
    return _members("kyra", "ronin")


def _corpus():
    """{name: text} for the five fixture stories and windup-v2 (spec 8.1)."""
    texts = {}
    for name, digest in FIXTURE_SHA256.items():
        with open(os.path.join(FIXTURES_V2, name), "rb") as f:
            raw = f.read()
        assert hashlib.sha256(raw).hexdigest() == digest, name
        texts[name] = raw.decode("utf-8")
    windup = texts["windup.md"]
    for old, new in WINDUP_V2_EDITS:
        assert windup.count(old) == 1, old
        windup = windup.replace(old, new)
    assert hashlib.sha256(windup.encode("utf-8")).hexdigest() == WINDUP_V2_SHA256
    texts["windup-v2"] = windup
    return texts


def _corpus_violations(tmp_path, text, members):
    panels = _panels(tmp_path, text)
    return character_lib.shots_violations(text, panels, len(panels), members)


def test_s21_repair_cast_descriptions(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    repair = character_lib.repair_cast_descriptions
    assert repair(SHOTS_OK, members) == (SHOTS_OK, [])
    fixed, repaired = repair(PARAPHRASED, members)
    assert repaired == [(1, "kyra")]
    assert fixed == _variant("facing right. Far behind her",
                             "facing right. The woman in grey is " + DESC_K + ". Far behind her",
                             PARAPHRASED)
    assert _v(tmp_path, fixed, members) == []
    assert repair(PARAPHRASED, []) == (PARAPHRASED, [])
    both = _variant("a lean man in his late thirties with a topknot and a scarred brow wearing an "
                    "indigo haori, and the woman in grey, a young woman with long black hair pinned "
                    "up with jade hairpins wearing a grey kimono, standing",
                    "a lean man, and the woman in grey standing")
    fixed, repaired = repair(both, members)
    assert repaired == [(3, "kyra"), (3, "ronin")]
    assert fixed == _variant("the ronin on the left facing right.",
                             "the ronin on the left facing right. The ronin is " + DESC_R
                             + ". The woman in grey is " + DESC_K + ".", both)
    no_end = _variant("A medium close-up of the bearded robber, a stocky man with a black beard in a "
                      "ragged brown jacket, crouching among ferns on a mossy cedar trail and facing "
                      "left. Soft overcast light, muted green palette, eye-level camera, "
                      "photorealistic film still.",
                      "A medium close-up of the bearded robber facing the ronin")
    fixed, repaired = repair(no_end, members)
    assert repaired == [(2, "ronin")]
    assert "facing the ronin. The ronin is " + DESC_R + ".\nMotion: The bearded robber" in fixed
    split = _variant("A medium shot of the woman in grey, a young woman with long black hair pinned "
                     "up with jade hairpins wearing a grey robe,",
                     "A medium shot of the woman\nin grey,", PARAPHRASED)
    assert repair(split, members) == (split, [])
    assert [v for v in _v(tmp_path, split, members) if " S9 " in v] == [
        "panel 1: S9 cast description: Image: names 'the woman in grey' without character kyra's "
        "description word for word; copy in this sentence: The woman in grey is " + DESC_K + "."]
    continued = _variant("under soft overcast light. A medium shot of the woman in grey",
                         "under soft overcast light.\nA medium shot of the woman in grey",
                         PARAPHRASED)
    fixed, repaired = repair(continued, members)
    assert repaired == [(1, "kyra")]
    assert fixed == _variant("facing right. Far behind her",
                             "facing right. The woman in grey is " + DESC_K + ". Far behind her",
                             continued)
    motion_only = _variant("Motion: The bearded robber lunges forward",
                           "Motion: The bearded robber lunges at the ronin")
    assert repair(motion_only, members) == (motion_only, [])
    crlf = PARAPHRASED.replace("\n", "\r\n")
    fixed, repaired = repair(crlf, members)
    assert repaired == [(1, "kyra")] and fixed.count("\r\n") == crlf.count("\r\n")
    crlf2 = no_end.replace("\n", "\r\n")
    fixed, repaired = repair(crlf2, members)
    assert repaired == [(2, "ronin")] and fixed.count("\r\n") == crlf2.count("\r\n")


def test_s54_phase1_repairs_s9_in_place(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 1
    kept = sorted(glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")))
    assert len(kept) == 1
    assert re.fullmatch(r"story\.pre-repair-\d{8}T\d{6}Z-%d\.md" % os.getpid(),
                        os.path.basename(kept[0]))
    with open(kept[0], "rb") as f:
        assert f.read() == PARAPHRASED.encode("utf-8")
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            PARAPHRASED, _members("kyra", "ronin"))[0]
    assert ("Repaired S9 on panels 1: inserted 1 missing cast identity sentence(s); the unrepaired "
            "draft is kept at %s" % kept[0]) in out.splitlines()
    assert _rejected(directory) == []
    assert not os.path.exists(story_md + ".repair.tmp")


def test_s55_repair_runs_before_the_rewrite_block(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    first = _variant("Motion: The bearded robber lunges forward out of the ferns with his short "
                     "knife raised. The camera stays static.",
                     "Motion: The bearded robber lunges then slashes.", PARAPHRASED)
    agent = _FakeStoryAgent(monkeypatch, story_md, [first, PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 2
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            PARAPHRASED, _members("kyra", "ronin"))[0]
    assert agent.calls[1]["cmd"][-1] == (agent.calls[0]["cmd"][-1] + "\n\n"
                                         + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3))
    rejected = _rejected(directory)
    assert len(rejected) == 1
    with open(rejected[0], encoding="utf-8") as f:
        assert f.read() == character_lib.repair_cast_descriptions(
            first, _members("kyra", "ronin"))[0]
    kept = glob.glob(os.path.join(str(directory), "story.pre-repair-*.md"))
    assert sorted(open(path, encoding="utf-8").read() for path in kept) == sorted([first,
                                                                                  PARAPHRASED])


def test_s56_second_rewrite_lists_only_the_remaining_violations(monkeypatch, movie_ws, lib_dir,
                                                                capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    bad2 = _variant(PANEL_3_MOTION, "Motion: The ronin offers his hand then pulls the woman in grey "
                                    "to her feet on the trail.")
    bad2_violations = ["panel 3: S5 one action: Motion: chains actions with 'then'",
                       "panel 3: S8 contact: Motion: 'pulls' acts on 'the woman in grey'" + S8_TAIL]
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, bad2, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 3
    first, second, third = (c["cmd"] for c in agent.calls)
    assert second[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3)
    assert third[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(bad2_violations, 3)
    assert first[:-1] == second[:-1] == third[:-1]
    assert agent.calls[2]["existed"] is False
    assert (directory / "story_prompt.rewrite.txt").read_text(encoding="utf-8") == second[-1]
    assert (directory / "story_prompt.rewrite-2.txt").read_text(encoding="utf-8") == third[-1]
    rejected = _rejected(directory)
    assert len(rejected) == 2
    contents = sorted(open(path, encoding="utf-8").read() for path in rejected)
    assert contents == sorted([BAD, bad2])
    lines = out.splitlines()
    second_warning = next(i for i, line in enumerate(lines)
                          if line.startswith("Warning: rewrite 1 still breaks the shot rules; "
                                             "moving it to "))
    assert lines[second_warning].endswith(" and asking for rewrite 2 of 2:")
    assert lines[second_warning + 1:second_warning + 3] == ["  - " + v for v in bad2_violations]
    assert "=== Phase 1: story (rewrite 1 of 2) ===" in lines
    assert "=== Phase 1: story (rewrite 2 of 2) ===" in lines
    runs = [line.split(":")[0] for line in lines if line.startswith("Running (timeout ")]
    assert len(runs) == 3 and len(set(runs)) == 1


def test_s57_second_rewrite_agent_failure(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD, None], returncodes=[0, 0, 1])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 3
    rejected = _rejected(directory)
    assert len(rejected) == 2
    line = next(l for l in err.splitlines()
                if l.startswith("Error: shots rewrite 2 of 2 failed; the rejected draft(s) are kept "
                                "at "))
    assert sorted(line.split(" are kept at ")[1].split(", ")) == rejected


def test_s58_failed_rewrite_moves_its_story_aside(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, PARAPHRASED])
    real = agent.__call__
    calls = {"n": 0}

    def call(cmd, **kwargs):
        proc = real(cmd, **kwargs)
        calls["n"] += 1
        if calls["n"] == 2:
            state = {"first": True}

            def communicate(timeout=None):
                if state["first"]:
                    state["first"] = False
                    raise subprocess.TimeoutExpired(cmd, timeout)
                return ("", None)
            proc.communicate = communicate
            proc.kill = lambda: None
        return proc
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", call)
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert calls["n"] == 2
    assert not os.path.exists(story_md)
    rejected = _rejected(directory)
    assert len(rejected) == 2
    assert sorted(open(path, encoding="utf-8").read() for path in rejected) == sorted([BAD,
                                                                                      PARAPHRASED])
    line = next(l for l in err.splitlines()
                if l.startswith("Error: shots rewrite 1 of 2 failed; the rejected draft(s) are kept "
                                "at "))
    assert sorted(line.split(" are kept at ")[1].split(", ")) == rejected
    assert "Error: qwen-agent timed out after " in err


def test_s59_force_story_without_a_write_never_repairs(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir, story=PARAPHRASED)
    agent = _FakeStoryAgent(monkeypatch, story_md, [None])
    assert ltx_movie.phase1_story(_shots_args(*(SHOTS_ARGV + ["--force-story"]))) == 1
    captured = capsys.readouterr()
    assert len(agent.calls) == 1
    assert ("Error: qwen-agent did not write %s; the existing file is unchanged since before "
            "Phase 1 and was neither validated nor repaired. Rerun the same command to try "
            "again." % story_md) in captured.err.splitlines()
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == PARAPHRASED
    assert glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")) == []
    assert _rejected(directory) == []
    assert "Repaired S9" not in captured.out


def test_s80_constants_and_word_lists():
    lib = character_lib
    assert lib.SHOTS_MAX_REWRITES == 2
    assert lib.SHOTS_SETTING_MIN_WORDS == 12
    assert lib.SHOTS_REWRITE_MAX_LISTED == 40
    assert lib._CAMERA_SHORT_MAX_WORDS == 4
    assert len(lib.SHOTS_CONTACT_VERBS) == 158
    assert len(lib.SHOTS_HANDOFF_VERBS) == 12
    assert len(lib.SHOTS_TAKE_VERBS) == 17
    assert len(lib.SHOTS_PERSON_NOUNS) == 88
    assert len(lib.SHOTS_ANIMAL_NOUNS) == 113
    verbs = (lib.SHOTS_CONTACT_VERBS, lib.SHOTS_HANDOFF_VERBS, lib.SHOTS_TAKE_VERBS)
    for a in range(3):
        for b in range(a + 1, 3):
            assert not verbs[a] & verbs[b]
    assert not lib.SHOTS_PERSON_NOUNS & lib.SHOTS_ANIMAL_NOUNS
    assert {"disarming", "shoulder-charges", "strikes", "help", "parries"} <= lib.SHOTS_CONTACT_VERBS
    assert {"hands", "gave", "returns", "returned"} <= lib.SHOTS_HANDOFF_VERBS
    assert {"snatches", "takes", "accepts"} <= lib.SHOTS_TAKE_VERBS
    for word in ("offer offers extend extends lift lifts grip grips clutch clutches hold holds "
                 "throw throws carry carrying pass passes hand wound pierce shoot shot charge "
                 "charges lunge lunges aim reach").split():
        assert all(word not in s for s in verbs), word
    assert {"robber", "attacker", "woman", "soldiers", "ronin"} <= lib.SHOTS_PERSON_NOUNS
    assert not {"guard", "guards", "general"} & lib.SHOTS_PERSON_NOUNS
    assert {"horse", "mare", "snake", "mount"} <= lib.SHOTS_ANIMAL_NOUNS
    assert tuple(r for r, _ in lib.SHOTS_RULE_GUIDANCE) == (
        "S1 panel count", "S2 characters list", "S3 fields", "S4 motion length", "S5 one action",
        "S6 cast count", "S7 cast and extra", "S8 contact", "S9 cast description",
        "S10 extra in cast shot", "S11 off-screen wording", "S12 setting sentence")
    for rule, line in lib.SHOTS_RULE_GUIDANCE:
        assert line.startswith(rule + " -- ") and line.endswith(":"), rule


def test_s81_is_animal_phrase():
    for phrase in ("horse", "the dark bay horse", "the grey mare", "snake", "the falcon's"):
        assert character_lib.is_animal_phrase(phrase) is True, phrase
    for phrase in ("the horseman", "robber leader", "the woman in grey", "the dog-faced bandit",
                   "shogun"):
        assert character_lib.is_animal_phrase(phrase) is False, phrase


def test_s82_person_refs():
    refs = character_lib._person_refs
    assert refs("The woman in grey watches the stocky man.", HUM, ANI, DES) == [
        (0, 17, "the woman in grey"), (37, 40, "man")]
    assert refs("A medium shot of the bearded robber, a stocky man with a black beard in a ragged "
                "brown jacket, facing left.", HUM, ANI, DES) == [(17, 35, "the bearded robber")]
    assert [r[2] for r in refs("The robbers' leader shoves him toward them, and her.",
                               HUM, ANI, DES)] == ["robbers", "leader", "him", "them", "her"]
    assert refs("She raises her blade toward the dark bay horse.", HUM, ANI, DES) == []
    assert [r[2] for r in refs("They face each other; one another.", HUM, ANI, DES)] == [
        "each other", "each other"]
    assert refs("Her figure is small against the trees, and his men wait.", HUM, ANI, DES) == []


S83_HITS = [
    ("The ronin strikes the bearded robber across the arm.", ("strikes", "the bearded robber")),
    ('"the ronin" swings his sword, disarming the robber.', ("disarming", "robber")),
    ("The bearded robber grabs her by the wrist.", ("grabs", "her")),
    ("The ronin pulls her to her feet.", ("pulls", "her")),
    ("The bearded robber shoves him.", ("shoves", "him")),
    ("Two robbers grapple with each other in the mud.", ("grapple", "each other")),
    ("The woman in grey strikes at the bearded robber's sword with a staff.",
     ("strikes", "the bearded robber")),
    ("The ronin slips the club's swing and cuts the robber's forearm.", ("cuts", "robber's")),
    ("The shogun hands the scroll to the ronin.", ("hands", "the ronin")),
    ("The woman in grey takes the ronin's hand.", ("takes", "the ronin")),
    ('"the woman in grey" takes "the ronin"\'s hand.', ("takes", "the ronin")),
    ("The woman in grey takes his hand.", ("takes", "his hand")),
    ("The ronin takes the scroll from the old man.", ("takes", "man")),
    ("The ronin extends his hand to help her up.", ("help", "her")),
    ("The ronin shoulder-charges the bearded robber off the trail.",
     ("shoulder-charges", "the bearded robber")),
    ("He is mid-swing, his katana cutting into the bearded robber's shoulder.",
     ("cutting", "the bearded robber")),
    ("The ronin swings his katana at the young bandit.", ("swings", "bandit")),
    ("The young bandit snatches the letter from the woman in grey.",
     ("snatches", "the woman in grey")),
    ("The ronin returns the letter to her.", ("returns", "her")),
]
S84_MISSES = [
    "The ronin offers his open hand to the woman in grey.",
    "The ronin extends his hand toward the woman in grey.",
    "The robber leader swings his blade downward, aiming for her neck.",
    "The woman in grey flinches backward, throwing her arm up to shield her face.",
    "The robber leader staggers backward, clutching his cut forearm against his chest.",
    "He deflects the bamboo spear with a swift, precise cut.",
    "The camera pushes in past him.",
    "The camera pushes in on him.",
    "The ronin kicks the dark bay horse forward.",
    "The ronin takes a step toward her.",
    "The woman in grey draws the dagger back to her hip, her eyes fixed on the attacker.",
    "The ronin strikes, his eyes on the bearded robber.",
    "The ronin's strike lands on the bearded robber.",
    "The woman in grey catches her breath.",
    "The ronin cuts the rope with his knife, freeing her.",
    "The ronin cuts through the air above the ronin's head.",
    "The ronin lifts the woman in grey's fallen hairpin from the moss.",
    "His strike lands hard on the bearded robber's shoulder.",
    "The shogun gives the ronin a scroll.",
    "The woman in grey pulls her shawl tight around her.",
    "The ronin drags his sword behind him.",
    "The ronin catches sight of the young bandit.",
    "The ronin catches up with the young bandit.",
    "The ronin pulls back from the scarred bandit.",
    "The ronin drives forward toward the scarred bandit.",
    "The scarred bandit steps out of the pines to block the stone path in front of the woman in "
    "grey.",
    "The ronin strikes a pose before the robbers.",
    "The ronin hits the ground beside the bandits.",
    "The ronin returns to the temple gate.",
    "The young bandit snatches the letter from her sash.",
]


def test_s83_find_contact_hits():
    for sentence, want in S83_HITS:
        assert character_lib.find_contact(sentence, HUM, ANI, DES) == want, sentence


def test_s84_find_contact_misses():
    for sentence in S84_MISSES:
        assert character_lib.find_contact(sentence, HUM, ANI, DES) is None, sentence


def test_s85_s8_in_shots_violations(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    a = _variant(P2_MOTION, "Motion: The bearded robber slashes at the woman in grey with his short "
                            "knife. The camera stays static.")
    motion_line = "panel 2: S8 contact: Motion: 'slashes' acts on 'the woman in grey'" + S8_TAIL
    image_line = "panel 2: S8 contact: Image: 'grabs' acts on 'the woman in grey'" + S8_TAIL
    assert _v(tmp_path, a, []) == [motion_line]
    assert _v(tmp_path, a, members) == [
        "panel 2: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction",
        motion_line,
        "panel 2: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "kyra" + S10_TAIL]
    grab = IMG_2 + " He grabs the woman in grey by the sleeve."
    assert _v(tmp_path, _variant(IMG_2, grab), []) == [image_line]
    assert _v(tmp_path, _variant(IMG_2, grab, a), []) == [motion_line, image_line]
    two = _variant(IMG_2, grab + " He shoves the ronin.")
    assert _v(tmp_path, two, []) == [image_line]
    assert _v(tmp_path, SHOTS_OK, []) == []
    assert _v(tmp_path, SHOTS_OK, members) == []


def test_s86_s9_cast_description(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _v(tmp_path, PARAPHRASED, members) == [S9_KYRA_1]
    assert _v(tmp_path, PARAPHRASED, []) == []
    assert _v(tmp_path, _variant("hairpins wearing a grey kimono, standing in the centre",
                                 "hairpins   WEARING a grey kimono, standing in the centre"),
              members) == []
    ident = _variant("the woman in grey, a young woman with long black hair pinned up with jade "
                     "hairpins wearing a grey kimono, standing in the centre",
                     "the woman in grey standing in the centre")
    ident = _variant("Far behind her on the left", "The woman in grey is " + DESC_K
                     + ". Far behind her on the left", ident)
    assert _v(tmp_path, ident, members) == []


def test_s87_s10_extra_in_cast_shot(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    robber = ("panel 1: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that "
              "shows kyra" + S10_TAIL)
    assert _v(tmp_path, _p1("On the left the bearded robber watches from the ferns."),
              members) == [robber]
    for cue in ("far in the background", "in the far background", "far behind", "far back",
                "far away", "far off", "far-off", "in the distance", "in the far distance",
                "far in the distance", "distant", "small in the frame", "tiny in the frame",
                "Far In The Background"):
        assert _v(tmp_path, _p1("On the left, %s, the bearded robber watches from the ferns."
                                % cue), members) == [], cue
    assert _v(tmp_path, _p1("In the background the bearded robber watches from the ferns."),
              members) == [robber]
    assert _v(tmp_path, _p1("On the left two robbers watch from the ferns."), members) == [
        "panel 1: S10 extra in cast shot: Image: names 'robbers' in a shot that shows kyra"
        + S10_TAIL]
    assert _v(tmp_path, _p1("She looks toward him and them."), members) == []
    assert _v(tmp_path, _p1("Far behind her is a ridge. The bearded robber watches from the ferns."),
              members) == [
        "panel 1: S10 extra in cast shot: Image: names 'The bearded robber' in a shot that shows "
        "kyra" + S10_TAIL]
    assert _v(tmp_path, _p1("On the left the bearded robber watches. The bearded robber grins."),
              members) == [robber]
    assert _v(tmp_path, _p1("On the left the dark bay horse grazes beside the ferns.",
                            ROSTER_HORSE), members) == []
    assert _v(tmp_path, S7_BAD, members) == [
        "panel 2: S7 cast and extra: Motion: names 'the ronin' together with 'the bearded robber'; "
        "show the other character's action in its own shot, then cut to the cast character's "
        "reaction",
        "panel 2: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "ronin" + S10_TAIL]
    assert _v(tmp_path, _p1("Beside her stands a stocky man with a black beard in a ragged brown "
                            "jacket."), members) == [
        "panel 1: S10 extra in cast shot: Image: names 'man' in a shot that shows kyra" + S10_TAIL]
    assert _v(tmp_path, _variant("standing an arm's length apart on the mossy cedar trail",
                                 "standing an arm's length apart on the mossy cedar trail beside "
                                 "a wiry young man"), members) == [
        "panel 3: S10 extra in cast shot: Image: names 'man' in a shot that shows kyra, ronin"
        + S10_TAIL]
    assert _v(tmp_path, _p1("Her figure is small against the ferns."), members) == []


def test_s88_s11_off_screen_wording(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    for phrase, shown in (("just outside the frame", "outside the frame"),
                          ("outside of the frame", "outside of the frame"),
                          ("outside the shot", "outside the shot"),
                          ("off-screen", "off-screen"), ("off  Screen", "off screen"),
                          ("offscreen", "offscreen"), ("out of frame", "out of frame"),
                          ("out of the frame", "out of the frame"), ("out of shot", "out of shot"),
                          ("out of view", "out of view"), ("out of sight", "out of sight"),
                          ("off camera", "off camera"), ("off-camera", "off-camera"),
                          ("beyond the frame", "beyond the frame"),
                          ("beyond the edge of the frame", "beyond the edge of the frame"),
                          ("unseen", "unseen"),
                          ("beyond the frame of the temple gate", "beyond the frame")):
        assert _v(tmp_path, _p1(P1_SENT + " Wind stirs the ferns %s." % phrase), members) == [
            "panel 1: S11 off-screen wording: Image: says '%s'" % shown + S11_TAIL], phrase
    assert _v(tmp_path, _variant(P2_MOTION, "Motion: The bearded robber lunges out of frame with his "
                                            "short knife raised. The camera stays static."),
              members) == ["panel 2: S11 off-screen wording: Motion: says 'out of frame'"
                           + S11_TAIL]
    both = _p1(P1_SENT + " Wind stirs the ferns off-screen.",
               _variant(M1_MOTION, "Motion: The woman in grey turns her head slowly toward the "
                                   "ferns off-screen."))
    assert _v(tmp_path, both, members) == [
        "panel 1: S11 off-screen wording: Image: says 'off-screen'" + S11_TAIL,
        "panel 1: S11 off-screen wording: Motion: says 'off-screen'" + S11_TAIL]
    for ok in ("on the left of the frame", "framed by tall ferns", "an offset stone lantern"):
        assert _v(tmp_path, _p1(P1_SENT + " Ferns stand %s." % ok), members) == [], ok


def test_s89_s12_setting_sentence(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    missing = ["panel 2: " + S12_LINE]
    assert _v(tmp_path, _variant(SET + REST_2, REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, REST_2 + " " + SET.strip()), members) == []
    assert _v(tmp_path, _variant(SET + REST_2, SET.replace("The setting", "the setting") + REST_2),
              members) == []
    assert _v(tmp_path, _variant(SET + REST_2, '"' + SET.strip() + '" ' + REST_2), members) == []
    assert _v(tmp_path, _variant(SET + REST_2, "Setting: a mossy cedar trail in feudal Japan. "
                                 + REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, "The setting is the same as before. " + REST_2),
              members) == missing
    eleven = "The setting is a mossy cedar trail in feudal Japan today. "
    twelve = "The setting is a mossy cedar trail in feudal Japan at dusk. "
    assert len(eleven.split()) == 11 and len(twelve.split()) == 12
    assert _v(tmp_path, _variant(SET + REST_2, eleven + REST_2), members) == missing
    assert _v(tmp_path, _variant(SET + REST_2, twelve + REST_2), members) == []
    assert _v(tmp_path, _variant(PANEL_2_IMAGE, ""), members) == [
        "panel 2: S3 fields: missing/empty Image: field"]


def test_s90_s7_animal_exemption(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey urges the dark bay horse "
                                            "forward along the mossy trail.", ROSTER_HORSE),
              members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey kicks the dark bay horse "
                                            "forward along the mossy trail.", ROSTER_HORSE),
              members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey pats the rider's horse gently "
                                            "on its neck.", ROSTER_RIDER), members) == []
    assert _v(tmp_path, _variant(M1_MOTION, "Motion: The woman in grey waves slowly to the rider "
                                            "across the mossy trail.", ROSTER_RIDER), members) == [
        "panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the rider'; "
        "show the other character's action in its own shot, then cut to the cast character's "
        "reaction"]


def test_s91_camera_sentence_fold_in():
    bow = "The ronin bows his head low before the small shrine. "
    for tail in ("Static camera.", "Slow push-in.", "Handheld, slow pan left.", "He stays static."):
        assert character_lib.motion_problems(bow + tail) == [], tail
    for tail in ("He kneels.", "The robber takes the shot."):
        assert character_lib.motion_problems(bow + tail) == [
            ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                              "followed by a camera sentence")], tail


def test_s92_rule_order_in_one_panel(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(SET + "A medium shot of the woman in grey", "A medium shot of the woman in grey",
                    PARAPHRASED)
    text = _variant(P1_SENT, "On the left the bearded robber stands just outside the frame.", text)
    text = _variant("Motion: The woman in grey turns her head slowly toward the ferns on her right. "
                    "The camera stays static.",
                    "Motion: The woman in grey pushes the bearded robber off-screen; then she runs.",
                    text)
    assert _v(tmp_path, text, members) == [
        "panel 1: S5 one action: Motion: contains a semicolon",
        "panel 1: S5 one action: Motion: chains actions with 'then'",
        S7_LINE_1,
        "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'" + S8_TAIL,
        S9_KYRA_1,
        "panel 1: S10 extra in cast shot: Image: names 'the bearded robber' in a shot that shows "
        "kyra" + S10_TAIL,
        "panel 1: S11 off-screen wording: Image: says 'outside the frame'" + S11_TAIL,
        "panel 1: S11 off-screen wording: Motion: says 'off-screen'" + S11_TAIL,
        "panel 1: " + S12_LINE]


def test_s93_identity_sentence_and_shots_cast_block(lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    lib = character_lib
    assert lib.identity_sentence(members[0]) == "The woman in grey is " + DESC_K + "."
    leader = lib.CastMember("x", "robber leader", "t", "man", "a man with a beard here ok", "/v",
                            None, None, None)
    assert lib.identity_sentence(leader) == "Robber leader is a man with a beard here ok."
    assert lib.SHOTS_IDENTITY_HEADER == ("Identity sentences -- copy the one for each of these "
                                         "characters, word for word, into every Image: field that "
                                         "shows them:")
    assert "Identity sentences" not in lib.build_cast_block(members)


S94_VV = [
    "story: S1 panel count: expected exactly 4 panels, found 3",
    "panel 2: S9 cast description: Image: names 'the ronin' without X",
    "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'; two people touching on "
    "screen",
    "panel 5: S9 cast description: Image: names 'the ronin' without X",
    'panel 3: S12 setting sentence: Image: has no sentence starting "The setting is"',
    'panel 4: S12 setting sentence: Image: has no sentence starting "The setting is"',
    "story: cannot read story.md: boom",
    "panel 2: S9 cast description: Image: names 'the woman in grey' without Y"]


def test_s94_rewrite_block_grouping_merging_cap(monkeypatch):
    lib = character_lib
    g = dict(lib.SHOTS_RULE_GUIDANCE)
    listing = "\n".join([
        g["S1 panel count"], "- story: expected exactly 4 panels, found 3",
        g["S8 contact"],
        "- panel 1: Motion: 'pushes' acts on 'the bearded robber'; two people touching on screen",
        g["S9 cast description"], "- panels 2, 5: Image: names 'the ronin' without X",
        "- panel 2: Image: names 'the woman in grey' without Y",
        g["S12 setting sentence"], '- panels 3, 4: Image: has no sentence starting "The setting is"',
        "- story: cannot read story.md: boom"])
    assert lib.shots_rewrite_block(S94_VV, 4) == lib.SHOTS_REWRITE_TEMPLATE % (listing, 4)
    monkeypatch.setattr(lib, "SHOTS_REWRITE_MAX_LISTED", 3)
    capped = "\n".join([
        g["S1 panel count"], "- story: expected exactly 4 panels, found 3",
        g["S8 contact"],
        "- panel 1: Motion: 'pushes' acts on 'the bearded robber'; two people touching on screen",
        g["S9 cast description"], "- panels 2, 5: Image: names 'the ronin' without X",
        "- ... and 4 more"])
    assert lib.shots_rewrite_block(S94_VV, 4) == lib.SHOTS_REWRITE_TEMPLATE % (capped, 4)


def test_s95_corpus_projections(tmp_path, lib_dir):
    members = _live_members(lib_dir)
    texts = _corpus()
    assert sorted(texts) == sorted(CORPUS_PROJ)
    for name, (count, proj) in CORPUS_PROJ.items():
        violations = _corpus_violations(tmp_path, texts[name], members)
        assert len(violations) == count, name
        assert _proj(violations) == proj, name
    for name, (count, repaired, proj) in REPAIRED_PROJ.items():
        fixed, done = character_lib.repair_cast_descriptions(texts[name], members)
        assert len(done) == repaired, name
        violations = _corpus_violations(tmp_path, fixed, members)
        assert len(violations) == count, name
        assert _proj(violations) == proj, name


def test_s96_corpus_exact_lines_uncast_and_block_shape(tmp_path, lib_dir):
    members = _live_members(lib_dir)
    texts = _corpus()
    found = {name: _corpus_violations(tmp_path, text, members) for name, text in texts.items()}
    for name, line in S96_LINES:
        assert line in found[name], (name, line)
    asgen = found["rules-as-generated.md"]
    assert _corpus_violations(tmp_path, texts["rules-as-generated.md"], []) == [
        v for v in asgen if " S8 contact: " in v]
    assert _corpus_violations(tmp_path, texts["windup-v2"], []) == []
    ls1 = _corpus_violations(tmp_path, texts["ls1.md"], [])
    assert _proj(ls1) == ("1:S12 2:S12 3:S12 4:S12 5:S12 6:S12 7:S12 8:S12 9:S12 10:S12 11:S8 "
                          "11:S12 12:S12 13:S8 13:S12 14:S8 14:S12")
    g = dict(character_lib.SHOTS_RULE_GUIDANCE)
    block = character_lib.shots_rewrite_block(asgen, 20)
    lines = block.splitlines()
    assert sum(1 for line in lines if line.startswith("- ")) == 16
    assert [line for line in lines if line in g.values()] == [
        g["S7 cast and extra"], g["S8 contact"], g["S9 cast description"],
        g["S10 extra in cast shot"]]
    assert ("- panels 1, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20: Image: names 'the ronin' "
            "without character ronin's description word for word; copy in this sentence: The "
            "ronin is " + DESC_R_LIVE + ".") in lines
    assert ("- panels 2, 3, 4, 6, 7, 13, 14, 15, 16: Image: names 'the woman in grey' without "
            "character kyra's description word for word; copy in this sentence: The woman in grey "
            "is " + DESC_K_LIVE + ".") in lines
    advisories = character_lib.shots_advisories(_panels(tmp_path, texts["rules-as-generated.md"]),
                                                members)
    assert [a.split(":")[0] for a in advisories] == ["panel 12", "panel 16", "panel 20"]
    assert all("Image: shot type is wide shot" in a for a in advisories)


def test_s97_template_v2():
    template = ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS
    assert {f for _, f, _, _ in string.Formatter().parse(template) if f} == {
        "story_id", "narrative", "seconds", "panels"}
    assert template.count("\n\nHow this movie is made:") == 1
    assert len(template.split()) == 922
    for fragment in ("sequence of separate shots joined by cuts", "## Characters", "10-25 words",
                     "ONE physical action", "never use a semicolon",
                     "EXACTLY {panels} panel sections",
                     "the setting sentence of this shot's location, copied word for word",
                     'one sentence made of their referring phrase, the word "is" and their full '
                     'description',
                     '"The setting is a dense cedar forest in feudal Japan, tall trunks and ferns '
                     'behind, the ground covered in leaf litter, under flat overcast grey light."',
                     "Fights and touch. Two people never touch on screen.",
                     "Show a hand-off, a taken hand or a helping hand the same way",
                     'Screen direction. Never write "outside the frame", "off-screen", "out of '
                     'frame"',
                     "never name a person who is not in the shot"):
        assert fragment in template, fragment
    assert "just outside the frame" not in template
    order = [template.index(s) for s in ("Setting sentences.", "Fights and touch.",
                                         "Screen direction.", "Give the story a narrative arc")]
    assert order == sorted(order)


def test_s98_phase1_with_v2_rules(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    first = _variant(PANEL_1_MOTION, "Motion: The woman in grey pushes the bearded robber away from "
                                     "her with both hands.")
    v2 = [S7_LINE_1, "panel 1: S8 contact: Motion: 'pushes' acts on 'the bearded robber'" + S8_TAIL]
    agent = _FakeStoryAgent(monkeypatch, story_md, [first, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    capsys.readouterr()
    block = character_lib.shots_rewrite_block(v2, 3)
    assert agent.calls[1]["cmd"][-1] == agent.calls[0]["cmd"][-1] + "\n\n" + block
    assert ("\n" + dict(character_lib.SHOTS_RULE_GUIDANCE)["S8 contact"] + "\n- panel 1: Motion: "
            "'pushes' acts on 'the bearded robber'; two people touching on screen\n") in block
    assert (character_lib.SHOTS_IDENTITY_HEADER + "\n- The woman in grey is " + DESC_K + "."
            in agent.calls[0]["cmd"][-1])
    (directory / "story.md").write_text(PARAPHRASED, encoding="utf-8")
    agent = _FakeStoryAgent(monkeypatch, story_md, [])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert agent.calls == []
    assert err.splitlines()[:2] == ["Error: story.md breaks the shot rules:", "  - " + S9_KYRA_1]
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == PARAPHRASED
    assert glob.glob(os.path.join(str(directory), "story.pre-repair-*.md")) == []


def test_s99_dry_run_shows_the_v2_prompt(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_id = "shots-s99-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
        cwd=WS, env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir, STORY_PIPELINE_LOGGED="1"),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert character_lib.SHOTS_IDENTITY_HEADER in out
    assert "\n- The woman in grey is " + DESC_K + ".\n- The ronin is " + DESC_R + ".\n" in out
    assert ('"The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the '
            'ground covered in leaf litter, under flat overcast grey light."') in out
    assert "Fights and touch. Two people never touch on screen." in out
    assert not os.path.exists(story_dir)
```

| Test | Covers |
|---|---|
| test S21 | `repair_cast_descriptions`: no-op on a valid story; the paraphrase case; two members in one sentence (order); a mention with no sentence end; a mention on a continuation line; a phrase split across lines (not repaired; S9 remains); Motion:-only mentions; empty members; CRLF preserved, with and without a sentence end |
| test S54 | Phase 1 repairs an authored draft in place: byte-identical pre-repair copy, exact log line, no rewrite |
| test S55 | The repair runs before the rewrite block, so the block lists only the non-S9 violations; it runs again on the rewrite draft (`PARAPHRASED`, repaired in place); both pre-repair copies are kept |
| test S56 | The second rewrite lists only rewrite 1's remaining violations; same `cmd[:-1]` and the same timeout; `story_prompt.rewrite-2.txt`; two rejected drafts; the warning and header lines |
| test S57 | Rewrite 2's agent failure: E-S11 "rewrite 2 of 2", listing both rejected drafts |
| test S58 | Rewrite 1 times out after writing story.md: rc 1, that story.md moved aside, both drafts listed in E-S11, no story.md left |
| test S59 | `--force-story` with a call that leaves the old story.md unchanged: rc 1, E-S19, no repair, no pre-repair copy, no rejected draft |
| test S80 | Constants, list sizes, disjointness, inclusions and exclusions (F6, M3), the guidance table |
| test S81 | `is_animal_phrase` |
| test S82 | `_person_refs`, including the possessive-determiner skip (M3) |
| test S83 | `find_contact` hits, including F2's "swings at the young bandit", F6's "snatches … from", "returns … to" |
| test S84 | `find_contact` misses, including the F2 sentences, the camera clause, G-R1 and G-R2 pins |
| test S85 | S8 in `shots_violations` (uncast, cast, Image:, both fields, first sentence only) |
| test S86 | S9 |
| test S87 | S10: cues; bare "in the background"; generic nouns; pronouns; dedup; animals; cast named in Motion: only; the description-only extra (F3); the appositive narrowing (F3); "her figure" (M3) |
| test S88 | S11, including M2's synonyms and the accepted false positive |
| test S89 | S12, including M1's 12-word floor (11 fail, 12 pass) |
| test S90 | S7 animal exemption |
| test S91 | Camera-sentence fold-in |
| test S92 | Rule order in one panel |
| test S93 | `identity_sentence`, `SHOTS_IDENTITY_HEADER` |
| test S94 | Rewrite block grouping, merging, cap |
| test S95 | Fixture hashes, corpus projections, raw and after repair |
| test S96 | Corpus exact lines, uncast results, the 16-line block shape, the 3 W2 advisories |
| test S97 | Template v2 |
| test S98 | Phase 1 rewrite with v2 rules; a pre-existing paraphrased story: E-S9, not repaired, no pre-repair file |
| test S99 | The dry run shows the v2 prompt and Cast block |

### 8.4 Counts (measured)

- `python3 -m pytest tests/test_shots_mode.py --color=no` → **`81 passed`**: 54 existing (8 changed, 46 byte-unchanged) + 27 new. With only 8.2 applied: `54 passed`.
- Checkpoints, measured with the repo's current test file: character_lib v2 alone → **15 failed, 39 passed**; character_lib + bin/ltx-movie v2 → **17 failed, 37 passed**. The extra two are S37 and S39.
- Casting set unchanged (178 in the repo). Offline `OK 344/344`, iterate flags `13 passed`, deploy `165` under both interpreters (scratch).

### 8.5 Result check

After 8.2 and 8.3, `tests/test_shots_mode.py` is 2534 lines with sha256 `2673052b0aaca13e701cd34c3626ec3c4a36bc3bc43cb5e35267461fb0856381` (base: the HEAD file, 1684 lines).

### 8.6 Mutation table (measured with pytest)

Each mutation was applied alone to the scratch copy, then `python3 -m pytest tests/test_shots_mode.py -q --color=no` was run. "Failing tests" lists every test that failed. **71 of 71 caught.** The main thread re-runs this table after implementation.

| # | File | Mutation | Failing tests |
|---|---|---|---|
| 1 | `character_lib.py` | find_contact: noun-marker check removed | test S84 |
| 2 | `character_lib.py` | find_contact: 's previous-word check removed | test S83, test S84, test S96 |
| 3 | `character_lib.py` | find_contact: clause end = sentence end | test S83, test S84, test S95, test S96 |
| 4 | `character_lib.py` | find_contact: camera-clause skip removed | test S84 |
| 5 | `character_lib.py` | find_contact: subject-key exclusion removed | test S84 |
| 6 | `character_lib.py` | find_contact: _SPATIAL_RE filter removed | test S84 |
| 7 | `character_lib.py` | find_contact: handoff 'to' requirement removed | test S84 |
| 8 | `character_lib.py` | find_contact: take 'from' alternative removed | test S83 |
| 9 | `character_lib.py` | find_contact: take 's-hand alternative removed | test S83, test S95, test S96 |
| 10 | `character_lib.py` | find_contact: take own-hand alternative removed | test S83 |
| 11 | `character_lib.py` | find_contact: take verbs treated as contact verbs | test S83 |
| 12 | `character_lib.py` | _person_refs: her never an object | test S82, test S83, test S95, test S96 |
| 13 | `character_lib.py` | _person_refs: her always an object | test S82, test S84, test S95, test S96 |
| 14 | `character_lib.py` | _HER_OBJECT_FOLLOWERS drops 'by' | test S83 |
| 15 | `character_lib.py` | _person_refs: description blanking removed | test S21, test S54, test S55, test S82, test S85, test S86, test S87, test S95 |
| 16 | `character_lib.py` | _person_refs: possessive-determiner skip removed | test S82, test S87 |
| 17 | `character_lib.py` | is_animal_phrase always False | test S81, test S87, test S90, test S95, test S96 |
| 18 | `character_lib.py` | S7: find_phrases without animal phrases | test S90 |
| 19 | `character_lib.py` | S7: animal phrases counted as extras | test S90, test S95, test S96 |
| 20 | `character_lib.py` | S8 skipped when members is empty | test S85, test S96 |
| 21 | `character_lib.py` | S8 checks Motion: only | test S85, test S95, test S96 |
| 22 | `character_lib.py` | S8 reports every contact sentence (no break) | test S85 |
| 23 | `character_lib.py` | S9 removed | test S21, test S86, test S92, test S95, test S96, test S98 |
| 24 | `character_lib.py` | S9 case-sensitive | test S86 |
| 25 | `character_lib.py` | S10 ignores distance cues | test S9, test S10, test S11, test S12, test S13, test S14, test S15, test S16, test S17, test S21, test S35, test S36, test S38, test S40, test S54, test S55, test S56, test S85, test S86, test S87, test S88, test S89, test S90, test S98 |
| 26 | `character_lib.py` | S10 flags pronoun keys | test S15, test S87, test S95, test S96 |
| 27 | `character_lib.py` | S10 appositive class-noun skip removed | test S21, test S54, test S55, test S86, test S92 |
| 28 | `character_lib.py` | S10 broad class-noun skip (any class noun of a member named in the sentence) | test S87 |
| 29 | `character_lib.py` | S10 blanks every roster description | test S87 |
| 30 | `character_lib.py` | S10 blanks cast descriptors only | test S85, test S87 |
| 31 | `character_lib.py` | S10 roster extras only | test S87, test S95, test S96 |
| 32 | `character_lib.py` | S10 no per-key de-duplication | test S87, test S95 |
| 33 | `character_lib.py` | S10 also on extras-only shots | test S9, test S10, test S11, test S12, test S13, test S14, test S15, test S16, test S17, test S21, test S35, test S36, test S40, test S54, test S55, test S56, test S85, test S86, test S87, test S88, test S89, test S90, test S92, test S95, test S96, test S98 |
| 34 | `character_lib.py` | _OFFSCREEN_RE: 'the' mandatory in out of (the) frame | test S88 |
| 35 | `character_lib.py` | _OFFSCREEN_RE: single-space off-screen | test S88 |
| 36 | `character_lib.py` | _OFFSCREEN_RE drops 'unseen' | test S88 |
| 37 | `character_lib.py` | S11 checks Image: only | test S88, test S92 |
| 38 | `character_lib.py` | S12 fires on an empty Image: | test S13, test S89 |
| 39 | `character_lib.py` | S12 minimum word count ignored | test S89 |
| 40 | `character_lib.py` | S12 only at the start of Image: | test S89, test S95, test S96 |
| 41 | `character_lib.py` | cue list drops 'distant' | test S87 |
| 42 | `character_lib.py` | SHOTS_PERSON_NOUNS drops 'robber' | test S80, test S83, test S95, test S96 |
| 43 | `character_lib.py` | SHOTS_CONTACT_VERBS drops 'disarming' | test S80, test S83, test S95, test S96 |
| 44 | `character_lib.py` | SHOTS_HANDOFF_VERBS drops 'returns' | test S80, test S83 |
| 45 | `character_lib.py` | SHOTS_TAKE_VERBS drops 'snatches' | test S80, test S83 |
| 46 | `character_lib.py` | camera fold-in reverted | test S91 |
| 47 | `character_lib.py` | _CAMERA_SHORT_MAX_WORDS = 6 | test S80, test S91 |
| 48 | `character_lib.py` | rewrite: merged line shows only the first panel | test S94, test S96 |
| 49 | `character_lib.py` | rewrite: no grouping | test S94, test S96, test S98 |
| 50 | `character_lib.py` | rewrite: no guidance headers | test S94, test S96, test S98 |
| 51 | `character_lib.py` | rewrite: 'and N more' counts lines | test S94, test S96 |
| 52 | `character_lib.py` | build_cast_block omits identity sentences | test S3, test S98, test S99 |
| 53 | `character_lib.py` | identity_sentence does not capitalise | test S3, test S21, test S86, test S92, test S93, test S96, test S98, test S99 |
| 54 | `character_lib.py` | repair: no-op | test S21, test S54, test S55, test S95 |
| 55 | `character_lib.py` | repair: always at the end of the line | test S21 |
| 56 | `character_lib.py` | repair: Image: label line only (continuations ignored) | test S21 |
| 57 | `character_lib.py` | repair: descriptor check skipped | test S21, test S36, test S37, test S40, test S54, test S56, test S58, test S95, test S98 |
| 58 | `bin/ltx-movie` | Phase 1: no repair on authored drafts | test S54, test S55 |
| 59 | `bin/ltx-movie` | Phase 1: repair on pre-existing story.md too | test S98 |
| 60 | `bin/ltx-movie` | repair: no pre-repair copy | test S54, test S55 |
| 61 | `bin/ltx-movie` | one rewrite only | test S37, test S56, test S57 |
| 62 | `bin/ltx-movie` | rewrite 2 lists the first draft's violations | test S56 |
| 63 | `bin/ltx-movie` | rejected drafts may overwrite (no _unused_path) | test S37, test S56, test S57 |
| 64 | `bin/ltx-movie` | rewrite 2 prompt overwrites story_prompt.rewrite.txt | test S56 |
| 65 | `bin/ltx-movie` | template: 'Fights and touch.' paragraph removed | test S97, test S99 |
| 66 | `bin/ltx-movie` | template: Image: field spec reverted | test S97 |
| 67 | `bin/ltx-movie` | no repair after a rewrite | test S55 |
| 68 | `bin/ltx-movie` | rewrite 2 timeout differs | test S56 |
| 69 | `bin/ltx-movie` | a failed rewrite leaves its story.md in place | test S58 |
| 70 | `bin/ltx-movie` | unchanged-story.md check removed | test S59 |
| 71 | `character_lib.py` | repair: CRLF fix reverted (no-end branch drops the carriage return) | test S21 |

**R1.** The main thread runs every 0.2 suite by its stated invocation. `git diff --stat` shows exactly `character_lib.py`, `bin/ltx-movie`, `tests/test_shots_mode.py`, the 5 fixture files and the shots spec (D5).

**R2.** `python3 -m pytest tests/test_deploy_pkg.py` → `165 passed`, and `/usr/bin/python3 -m unittest tests.test_deploy_pkg` → `Ran 165 tests … OK` (measured on the scratch copy). No deploy tuple changes.

---

## 9. Token budget and request time

Token counts use qwen-agent's estimator, `len(json.dumps(msg)) // 3 + 8`, against a 24576-token window.

| Prompt | Est. tokens |
|---|---|
| Shipped shots prompt, rescue narrative, 14 panels, kyra+ronin Cast block | 2274 |
| v2 shots prompt, same inputs | 3081 |
| v2 shots prompt, L-R1 narrative (10.2), 20 panels | **3041** |

- **At 20 panels:** `max_tokens = 11000`, so the budget is `24576 - 11000 - 1024 = 12552`.
  - First draft: 2937 fixed + 3041 = **5978**.
  - Each rewrite: + one block. Measured blocks are 977 (as-generated after repair) and 1239 (raw), giving 6955-7217.
  - Rewrite 2 is the same size as rewrite 1, because its block is not cumulative.
  - All of these fit.
- **Limits for this narrative.** The first draft fits up to 31 panels. A rewrite with the measured 1239-token block fits up to 29.
- **Round 2 (after `write_file`).** It overflows earlier than before, harmlessly (shots spec 9.1).
- **`max_tokens` is unchanged [spec choice].**
- **Request time (M4).**
  - qwen-agent is non-streaming, and each request has a 600 s `urlopen` timeout (`bin/qwen-agent:1798`).
  - Phase 1 now makes up to 3 story-model calls, each bounded by `_phase1_timeout(20) = 1800` s.
  - Per-request wall-clock is not measured here. L-R1 records it (10.3).

---

## 10. Live gate L-R1 (main thread or user, on hardware; no concurrent GPU work)

### 10.1 Preconditions

Record each of these before the run:

- `bin/story-server status` is `SERVING vision`, with no stand-down marker under `~/.qwen-serve-guard/`;
- `psutil.virtual_memory().available / 2**30`;
- `git -C WS log -1 --format=%h` (the commit carrying D1-D5);
- `python3 -m pytest tests/test_shots_mode.py --color=no` → `81 passed`.

None of the story-ids `kyra-ronin-pass-v2-t1`, `-t2`, `-t3` may exist. Use a `b` suffix on all three if any does.

**Timestamping (M4).** Pipe every L-R1 command's output through this, so each line carries a UTC time and the per-request wall-clock can be read off:

```
python3 -u -c 'import sys,time
for l in sys.stdin: sys.stdout.write(time.strftime("%H:%M:%S ", time.gmtime()) + l); sys.stdout.flush()'
```

Per-request wall-clock is the time from a `Running (timeout …)` line to the next line.

### 10.2 Narrative and command (no `--story-prompt-override`; no hand-edit except in L-R1b)

```
NARRATIVE="In feudal Japan, at dusk on a narrow mountain pass, the woman in grey is carrying a sealed letter to the temple at the summit. A scarred bandit with a long-handled axe steps out of the pines onto the stone path and swings at her. She knocks the axe handle aside with her folded iron fan, and the axe falls into the gorge. A wiry young bandit with a short sword snatches the letter from her sash and runs up the ridge. The ronin, resting at a roadside shrine, chases the young bandit through the pines and knocks the short sword from his hand with the flat of his katana; the bandit drops the letter and flees down the slope. At the temple gate, in the last light, the ronin returns the letter to her, and the two bow to each other before he walks away down the mountain. Relatively little dialogue; focus on realistic, physically grounded action."
bin/ltx-movie "$NARRATIVE" --story-id <ID> --shots --panels 20 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --character kyra --character ronin
```

**The narrative [spec choice, revised per F6].**

- It is a new story, as the user asked, cut to **5 contact beats**:
  1. the axe bandit swings at her;
  2. her fan knocks the axe handle aside;
  3. the young bandit snatches the letter;
  4. the ronin knocks the sword from his hand;
  5. the ronin returns the letter to her (a cast–cast hand-off, to eyeball per C2).
- It has two fights (hers and his), a chase and a bow.
- "from her father" was dropped, because it flagged 'father' under S10 in kyra shots.
- The narrative's own wording still meets three detector gaps (G-R1): "snatches the letter from her sash", "knocks the short sword from his hand", "knocks the axe handle aside". Judge those beats by eyeball.

### 10.2a Phase 1 trials

The reviewer's wording, adapted to two rewrites:

> **10.2a Phase 1 trials.** First run Phase 1 alone three times, with no render: `bin/ltx-movie "$NARRATIVE" --story-id kyra-ronin-pass-v2-t<k> --shots --panels 20 --story-only --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --character kyra --character ronin`, for k = 1, 2, 3. For each trial, record the first-draft violations per rule, each rewrite's remaining violations per rule, the rc and the Phase 1 wall-clock. **K-R1a** is the number of trials that end with rc 0.
>
> Run 10.2 with `--story-id` set to the first passing trial; Phase 1 is skipped because its story.md is valid.
>
> If no trial passes, K-R1 fails. Apply the E-S10 hand-edit runbook to trial 1, save the diff to `lr1-evidence/handedit.diff`, and render that story as **L-R1b**. Record K-R2/K-R3 marked "hand-edited".
>
> Pre-registered follow-up if K-R1a ≤ 1/3: a user decision between a third rewrite, a narrower S8/S10, or an edit-mode rewrite within a larger window (C5).

**Recording the trials.**

- Also record per trial: the number of S9 repairs (`Repaired S9 on panels …` lines), each request's wall-clock (10.1), and which rewrite (if any) passed.
- The per-rule counts come from the warning lists. Recompute them in a REPL:
  - for each `story.rejected-*.md`, `story.pre-repair-*.md` and the final story.md;
  - with `character_lib.shots_violations`, members `resolve_cast([(None, "kyra"), (None, "ronin")])`, 20 panels, and `_load_story_panels`.
- **The E-S10 hand-edit runbook (L-R1b only).**
  1. Copy the first trial whose story.md exists; if none has one, its newest story.rejected-*.md, copied to story.md. Keep a copy as `lr1-evidence/trial-final.md`.
  2. Edit story.md until `shots_violations` returns `[]`, changing only the lines named by violations.
  3. Save `diff -u` to `lr1-evidence/handedit.diff`.
  4. Render with the 10.2 command and that story-id.
  - Because trial 1 ran with `--story-only`, no stills or clips exist yet, so the F4 stale-still issue does not arise.

### 10.3 Record and pass conditions

Record:

1. **Phase 1 (from 10.2a).** For each trial:
   - first draft → after repair → after rewrite 1 → after rewrite 2, the violation counts per rule;
   - the rc, the S9 repairs, the per-request wall-clock (flag any request over 540 s, which is 90% of the 600 s request timeout);
   - the `story_prompt.rewrite*.txt` sizes;
   - for each repair: the panel, the member and the sentence holding the first mention (from the pre-repair copy), flagged when the mention is only a gaze, address or possessive target.
2. **Structure** (the rendered story):
   - fight beats, and how many are wind-up/reaction pairs;
   - beats dropped or merged;
   - distinct setting sentences and the panels that use each;
   - the hand-off (beat 5) shown as two shots or not.
3. **Render.** rc, clip count, retries, Phase 2 and Phase 4 wall-clock, stills groups.
4. **Judge (twice).**

   ```
   bin/judge-clips --story-id <ID> > <story>/judge-pass1.out 2>&1; cp <story>/clips_judgment.json <story>/judgment-pass1.json
   bin/judge-clips --story-id <ID> > <story>/judge-pass2.out 2>&1; cp <story>/clips_judgment.json <story>/judgment-pass2.json
   ```

   - Record per-clip and mean motion fidelity, physical realism and temporal stability, and narrative clarity, for each pass and the 2-pass mean.
   - `seam_continuity` is recorded but not compared.
   - Set side by side with `ronin-shots-rules-20261009` (5.05 / 6.28 / 6.22 / narrative 4).
   - **Comparison caveat (F6).** This is not a like-for-like comparison:
     - a different narrative and locations (mountain pass and temple gate, against a forest and a courtyard);
     - 5 contact beats against about 4;
     - a cast–cast hand-off;
     - v2's prompt.

     A difference in motion fidelity cannot be attributed to the v2 rules alone. Record it as directional.
5. **Eyeball (decisive).**
   - kyra's and the ronin's identity per cast shot, with costume drift against the rules story's recorded drift;
   - no human extra in a cast-LoRA shot rendered as a cast twin;
   - extras-only shots in period;
   - no over-the-shoulder foreground figure;
   - each wind-up and each reaction reads as one person;
   - **the split hand-off reads as a hand-off (C2);**
   - every repaired panel shows only the characters its Motion: and shot intent call for, at the shot scale its Image: states.

**Pass conditions:**

- **K-R1 (gating, mechanical).**
  - It holds when at least one 10.2a trial ends rc 0 with `shots_violations == []` (K-R1a ≥ 1), and 10.2 on that story exits 0 with 20 clips.
  - `manifest.json` must be schema 3, with every panel `still` and every character strength 0.8.
  - If K-R1a = 0, K-R1 fails, and **L-R1b** (10.2a) is rendered so that K-R2/K-R3 are still collected, marked "hand-edited". No other hand-edit or override is allowed.
- **K-R2 (non-gating KPIs)**, each recorded as met or not met:
  - mean motion fidelity ≥ 5.05;
  - narrative clarity ≥ 4 in both passes;
  - physical realism ≥ 5.78 and temporal stability ≥ 5.72;
  - at least 2 of the 2 fights shown as wind-up/reaction pairs;
  - the hand-off split into two shots.
- **K-R3 (eyeball, decisive for the user).** No extra-twin bleed in any cast shot, and no over-the-shoulder figure.

Snapshot `movie.log`, `images/stills-group-*.log`, `manifest.json`, `story.md`, `story.pre-repair-*.md`, `story.rejected-*.md`, `story_prompt*.txt`, both judgments and the three trial directories' Phase 1 files into `.superpowers/sdd/2026-10-06-shots-mode/live/lr1-evidence/` before any further run.

---

## 11. Task decomposition hint (for the planner)

1. **Baseline.** Rerun R1/R2 and record them. Copy and verify the 5 fixtures (8.1).
2. **`character_lib.py`.** Apply 3.1-3.12 by script and check the 3.13 hash. Then:
   - run the casting set (`178 passed`);
   - run the unedited shots suite and expect exactly **15 failed, 39 passed**: S3, S9-S18, S35, S36, S38, S40.
3. **`bin/ltx-movie`.** Apply 5.1, 5.3 (a) and 5.3 (b) and check the 5.5 hash. Then:
   - run the offline suite directly (`OK 344/344`) and iterate flags (`13 passed`);
   - run the unedited shots suite and expect **17 failed, 37 passed** (adds S37, S39).
4. **Tests.** Apply 8.2 (54 passed), then append 8.3 (81 passed), and check the 8.5 hash.
5. **R1, R2 and the full 8.6 mutation table,** run by the main thread. Then a design-reviewer code review, which diffs against this spec's blocks first.
6. **D5.**
7. **Live gate:** 10.2a trials, then L-R1 or L-R1b.

---

## 12. Known gaps beyond 7.3

G-R11 (convergence) is the main remaining risk. It is measured by 10.2a.

---

## 13. Review focus

1. **Byte identity of the transcribed code.** The curly quotes and dashes, and the 3.13 / 5.5 / 8.5 hashes.
2. **The repair's correctness on real stories.**
   - It inserts after a sentence end, never mid-word.
   - The pre-repair copy is byte-identical.
   - It never runs on a pre-existing story.md.
3. **The two-rewrite loop and its exit paths** (E-S10, E-S11 with the move-aside, E-S19).
   - The non-cumulative block.
   - `_unused_path` never loses a draft.
   - The `--danger-auto-approve` pass-through is unchanged (the same `cmd`).
   - A rewrite's `write_file` is to a NEW path (story.md was moved aside), so no approval prompt appears under `--no-review`.
4. **S10 strictness** on the 7.1 rows, read sentence by sentence.
5. **The no-grandfathering consequence (4.1).**

---

## 14. Shots Task 2 review minors

| Minor | Disposition |
|---|---|
| 1. Camera-sentence openers | **Folded in** (3.6, test S91) |
| 2. Camera-sentence loophole | Not folded (G-R3) |
| 3. Serial-comma list | Not folded (0 of 128 Motion: fields; the template forbids ", and") |
| 4. "Mr."/ellipsis | Not folded (phrases cannot contain "."; 0 occurrences) |

---

## 15. Dispositions and remaining confirmations

- **C1** (the windup story has 6 violations, windup-v2 has 0): **accepted.**
- **C2** (cast–cast contact banned): **accepted.** Eyeball the split hand-off in L-R1.
- **C3** (S10 counts generic person nouns): **accepted,** with M3 and F3.
- **C4** (no grandfathering): **accepted,** with the F4 consequence text (4.1).
- **C5:** **superseded** by the second rewrite (ruling 1b).

New [spec choice] items for the user to confirm:

- **C6.** The S9 repair runs only on drafts written this run, never on a pre-existing story.md, and never on a story.md that the run's call left unchanged (4.1).
- **C7.** The repair inserts the identity sentence after the sentence holding the first mention, not ": <descriptor>" inline (3.11).
- **C8.** The S10 blanking refinement: a roster description is blanked only when its phrase is in the same sentence, which removes the double report the reviewer's exact edit produced (4.3).
- **C9.** `_SPATIAL_RE` is kept exactly as the reviewer wrote it, without "for" (G-R15).
- **C10.** No change to `bin/ltx-movie`'s docstring or help (G-R20).
