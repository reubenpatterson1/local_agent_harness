# Shots mode -- Design Spec (independent single-action shots for cast stories)

Date: 2026-10-06
Status: The user approved the design in three sections (story structure and prompt rules; pipeline; errors and tests) and pre-authorized implementation ("write the spec and implement"). This document transcribes those decisions without reopening them. Every choice made while writing it to remove ambiguity is marked **[spec choice]**, and every reading of an ambiguous approved phrase is marked **[interpretation]**. The facts checked against real files this session are in 0.2. Anything that could not be verified offline is in Section 12 (Known gaps). There are no open questions (Section 14).

Amended 2026-10-09 by docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md (shots rules v2): rules S8-S12 are added, W1 became the fatal S9 (repaired automatically in drafts the story model writes), S7 exempts animals, Phase 1 allows up to two rewrites, and the Cast block, rewrite block, story template and Phase 1 code in 3.3, 3.7-3.9, 5.2 and 5.4 are replaced. Where the two differ, the v2 spec wins.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Branch `qwen-agent-redteam`, HEAD `1567e35`. This feature builds on `docs/superpowers/specs/2026-10-05-character-library-design.md` (called "the casting spec" below) and uses its terms: **character**, **cast**, **casting**, **uncast**, **trigger**, **referring phrase**, **global LoRA**.

Two new terms:

- **Shots mode** is a `bin/ltx-movie --shots` run. Every panel is an independent shot with its own `Image:` field and its own still, and every clip renders from its own still. There is no chaining.
- **Continuous mode** is today's chained flow: one still for panel 1, and every later clip continues from the previous clip's last frame. **Without `--shots`, every existing output is byte-identical to today** (SC9).

An **extra** is a character listed in a shots story's `## Characters` section who is not cast.

---

## 0. Purpose and scope

### 0.1 Purpose

Character LoRAs fuse globally. They restyle everything in the frame, not only the character they were trained on. Clips also rarely perform multi-beat Motion text. Today's chained flow combines both problems: a cast character shares long, crowded, multi-action shots with uncast people, and each clip inherits the previous clip's drift. Shots mode makes three changes:

1. Every shot is short and single-action.
2. A cast character is composed alone or with one other cast character, never at close range with an extra.
3. Every shot starts from its own freshly rendered, LoRA-anchored still, so drift does not accumulate.

### 0.2 Grounding evidence (checked 2026-10-06)

**Bleed and strength evidence (from the brief, re-inspected on disk).**

- `generated/stories/ronin-rescue-cast-20261006/` was rendered by `bin/ltx-movie … --panels 8 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --character kyra --character ronin` (`iterate-story.log:28`).
  - The manifest's `characters`: panels 1-2 `[kyra@1.0]`, panels 3-5 `[ronin@1.0]`, panels 6-8 `[kyra@0.8, ronin@0.8]`. Panel 1 is `still`; panels 2-8 are `chain`.
  - `clips_judgment.json` (claude-opus-5-5, high): movie `{"seam_continuity": 6, "narrative_clarity": 3}`.
    - motion_fidelity: 5, 3, 4, 2, 4, 5, 7, 4 (mean 4.25).
    - physical_realism: 5, 3, 4, 3, 5, 5, 6, 6 (mean 4.625).
    - temporal_stability: 4, 2, 3, 2, 4, 3, 6, 4 (mean 3.5).
  - Critique, verbatim fragments:
    - panel 2: "a second woman in grey appears holding the stick";
    - panel 4: "the bald robber grows hair and a topknot, becomes a samurai";
    - panel 5: "the 'robbers' are now samurai in matching robes";
    - panel 6: "her grey silk kimono is now blue".
  - A lone cast LoRA at 1.0 restyled uncast people. In panels 6-8, both characters at 0.8 in close physical contact blended (the brief; the critique says panel 8's "ronin's face also gradually takes on feminine features").
- `generated/stories/ronin-rescue-cast-20261006-solo07/` is the same story with lone panels at 0.7. Its manifest has panels 1-5 at 0.7 and 6-8 at 0.8; the 0.7 was a hand-edited manifest, since `panel_strengths` can only produce 1.0 for a lone panel.
  - motion_fidelity 5, 4, 2, 2, 4, 4, 6, 6 (mean 4.125); physical_realism mean 5.125; temporal_stability mean 3.875; movie `{"seam_continuity": 7, "narrative_clarity": 3}`.
  - Critique, panel 3: "No new character sprints in. Instead the woman seems to turn into a grey-robed swordsman". That is the brief's "lone at 0.7 made the ronin vanish".
- `generated/stories/bleed-sweep-s08/` is two quiet two-person panels at 0.8/0.8. The brief records that both identities held (user eyeball). The judge's critique is less positive: "Identity drift is severe" in panel 2, and panel 1 "has one visible hairpin instead of three". Scores: motion_fidelity 5, 5; movie seam 8, narrative 6. **Both readings are recorded. Live gate L-S1 is the arbiter for 0.8.**
- **Compound panels.** Every rescue `Motion:` is a 45-71-word multi-sentence sequence (for example panel 3: sprint + shoulder-charge + draw + swing), although the chained template asks for "15-35 words … ONLY ONE continuous physical motion". The motion_fidelity scores above (mostly 2-5) are the brief's "clips rarely perform multi-beat Motion text".
- **The story model paraphrases "word for word" descriptions.** Rescue panel 1's Image: says "her long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi". The CAST block asked for the full descriptor verbatim ("a young East Asian woman with fair skin, long black hair …"). It **did** use both cast phrases verbatim everywhere.
- **The heuristics in 4.3, run this session over real Motion: text:**
  - all 8 rescue panels are flagged by S4 and S5;
  - of 378 Motion: fields across `generated/stories/*/story.md` (all written under continuous-mode rules), 359 are flagged. The 19 that pass include compounds joined by a bare " and " or a participle ("tucks the sword back at his hip and walks off"). That is the known false-negative class G1.

**Library state.** `generated/characters/kyra` (trigger `kyrawmn`, phrase `the woman in grey`, 27-word descriptor) and `generated/characters/ronin` (trigger `roninmn`, phrase `the ronin`, 22-word descriptor) are both `trained`, with both a video and a stills LoRA. `strength` is null for both.

**Code facts (read in full before specifying edits).**

- `character_lib.py` (523 lines, stdlib: `collections, datetime, json, os, re, uuid`):
  - `panel_strengths(names, members, character_strength)` returns 1.0 for one name; otherwise each name gets its `character.json` strength, or `character_strength`.
  - `cast_text(text, members, insert=None)`. `_phrase_regex(phrase, trigger=None)`: `cast_text` calls `match.group("trig")`, so it needs members that carry triggers.
  - `build_cast_block(members)`, `CAST_BLOCK_RULES`, `DEFAULT_CHARACTER_STRENGTH = 0.8`, `SINGLE_CHARACTER_STRENGTH = 1.0`.
- `bin/ltx-movie` (1447 lines):
  - `STORY_PROMPT_TEMPLATE` (`:107-131`) contains `\n\nHow this movie is made:` exactly once. `build_story_prompt` (`:167-184`).
  - `_resolve_casting` (`:654-709`). `_validate_story_md` (`:504-558`) is the chained/no-stills validator.
  - `phase1_story` (`:862-978`):
    - it builds `cmd` once, with the prompt as its last element;
    - on validation failure it **exits 1 with a hand-edit hint. There is no rewrite path today**;
    - the review gate is `input(...)`.
  - `phase2_stills` (`:994-1022`) runs `bin/ltx-story-images --only 1` once.
  - `phase3_manifest` (`:1050-1085`). `_phase4_flags` (`:431-444`): stills mode uses `stop`, `--no-stills` uses `skip`.
  - `_stream_and_tee(cmd, log_path)` (`:1132-1141`). `_phase_sequence` (`:1330-1345`) is pure. `_phase1_max_tokens(panels) = max(4096, panels * 550)` (`:447-449`).
  - Imports: `argparse, glob, importlib.machinery, json, os, shlex, subprocess, sys, threading, time` plus `pipeline_log`. **No `re`, `datetime` or `uuid`.**
- `bin/ltx-story-images` (464 lines):
  - an existing `panel_NN.png` is reused unless `--force` (`:397-401`);
  - `grounded = bool(style)` (`:274`); `_panel_seed` gives `--seed` when grounded, else `--seed + i` (`:188-196`);
  - the E-P16 one-LoRA-set-per-process refusal is at `:324-328`;
  - every invocation **overwrites** `images.json` with only its own selected panels (`:441-449`).
- `bin/ltx-story-manifest` (640 lines):
  - `--cast requires --chain` (`:358-359`);
  - the non-chain `--image` path writes schema 2 with no `conditioning` key (`:532-558`);
  - casting applies `cast_text` to `motion_prompt` only (`:576-589`);
  - `_parse_prompts_md` (`:203-275`) ignores every line after a `##` header that is not a panel header, so a `## Characters` section is invisible to it.
- `bin/ltx-mlx-render` (1300 lines):
  - `load_manifest` accepts schema 3 with `conditioning: "still"` on any panel (`:219-231`);
  - `build_clip_provenance` keys reuse on `prompt_sha256`, `image_sha256` (still units), `seed` and the LoRA set (`:416-444`);
  - `clip_is_reusable` returns False for a missing clip (`:462-478`);
  - the end-of-run retry pass skips only chained manifests (`:949-952`).
- `bin/qwen-agent`: a `write_file` to a **new** path auto-approves; an overwrite asks a human unless `--danger-auto-approve` is given (`:850-881`). `context_budget = CONTEXT_WINDOW - max_tokens - 1024` (`:2574-2576`), estimated at 3 characters per token.
- `bin/story-server`: `VISION_MAX_MODEL_LEN` defaults to 24576 (`:57`). `stop` with nothing running prints `nothing to stop` and exits 0.
- `bin/judge-clips` / `bin/judge-stills` scan only `clips/` and `images/` top-level `panel_NN.*` names (`judge-stills:183-193`, `judge-clips:245-252`). `seam_continuity` is scored as "one continuous take" (`judge-clips:163-165`).
- `scripts/deploy/build_pkg.py:383-388`: `PIPELINE_FILES` already ships `character_lib.py`, `bin/ltx-movie`, `bin/ltx-story-images`, `bin/ltx-story-manifest` and `bin/ltx-mlx-render`. `TEST_FILES` and `GATE_SPECS` (G1-G7, X1, X2) list only existing suites and an uncast dry run.

**Source-text pins the implementation must keep green. None of these test files is edited.**

| Pin | File:line | Constraint on the edit |
|---|---|---|
| L1z5 | `test_ltx_movie_offline.py:124-128` | `'["--lora", args.stills_lora_path]'` occurs exactly **2** times in bin/ltx-movie, so shots Phase 2 must reuse the already-built Phase 2 `cmd` |
| L1z9, L1z14 | `:150-186` | `'["--model", args.story_model]'` and `'["--context-window", str(args.story_context_window)]'` each occur exactly 2 times, so the rewrite reuses Phase 1's `cmd` |
| L7i | `:426-428` | the 3-line `    if not args.no_stills:\n        for w in _chain_image_warnings(…` block occurs exactly once, unchanged, so the shots path branches off **before** it |
| L7j | `:432-434` | `"\nimport re\n"` must not appear in bin/ltx-movie, so **all shot-rule regexes live in `character_lib.py`** |
| L17b | `:713-715` | `phase2_stills`'s body never mentions `no_stills` |
| L17c | `:716-719` | `'"--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")'` stays, and `'"--glob"'` never appears |
| L19a-c | `:800-811` | `'"--workspace", WS,'` occurs exactly 2 times, with both literal `cmd = [...]` / `phase1_cmd = [...]` openings unchanged |
| L24, L51, L41 | `:873`, `:1354-1368`, `:1414-1442` | an uncast dry run prints `ltx-mlx-render` twice; `_phase4_flags` keeps stop/skip for stills/no-stills; `_phase_sequence` on an object without `redo_panels` is unchanged |
| L1, P56 | `:50-63` | existing help substrings stay |
| `_render_flags(args)` ×4, `os.path.join(WS, "bin", "ltx-mlx-render")` ×4, `os.path.join(WS, "bin", "story-server")` ×2 | `:722-729`, `:1567-1574` | new code never writes these literals |
| I20, I21 | `test_ltx_story_images.py:581-592` | `_panel_seed(args.seed, i, grounded)` ×2, `_compose_prompt(` ×3, the substring `grounded = bool(style)`, and `lora_path=args.lora_path` all stay |
| P22, P23 | `test_casting_pipeline.py:756`, `:769` | the chained E-P14 warning text is byte-identical; `"--cast requires --chain"` stays a **substring** of the manifest's error |
| `:531` | `test_ltx_movie_offline.py` | the substring `qwen-agent exited %d but story.md exists` stays in bin/ltx-movie |

**Baseline test counts (run this session, before any change).**

| Suite | Invocation | Result |
|---|---|---|
| `tests/test_ltx_movie_offline.py` | `python3 tests/test_ltx_movie_offline.py` (direct; **never pytest**, which false-greens it) | `OK 344/344` |
| `tests/test_ltx_story_images.py` | direct | `OK 101/101` |
| `tests/test_ltx_mlx_render.py` | direct | `OK 443/443` |
| `tests/test_ltx2_mlx_video_skill.py` | direct | `OK 146/146` |
| `tests/test_ltx_story_manifest_chain.py` | direct | `OK 32/32` |
| `tests/test_ltx_image_fit.py` | direct | `OK 77/77` |
| `tests/check_ltx2_mlx_no_forbidden_imports.py` | direct | `RESULT: ok` |
| `tests/test_casting_pipeline.py`, `test_casting_regression.py`, `test_character_lib.py`, `test_character_dataset.py`, `test_character_tool.py`, `test_z_image_skill_multi_lora.py` | `python3 -m pytest` (together) | `178 passed` (63 + 3 + 46 + 41 + 18 + 7) |
| `tests/test_z_image_skill_cache.py` | `python3 -m pytest` | `13 passed` |
| `tests/test_ltx_movie_iterate_flags.py` | `python3 -m pytest` | `13 passed` (it drives `phase1_story` through a fake Popen) |
| `tests/test_pipeline_log.py` | `python3 -m pytest` | `17 passed` |
| `tests/test_deploy_pkg.py` | `python3 -m pytest` (3.13) | `165 passed` |
| `tests/test_deploy_pkg.py` | `/usr/bin/python3 -m unittest tests.test_deploy_pkg` (3.9.6) | `Ran 165 tests … OK` |

**Token measurements** (qwen-agent's own estimator, `len(json.dumps(msg)) // 3 + 8`, loaded from `bin/qwen-agent` this session):

- system message: 782;
- tool schema: 2155;
- the 5.2 shots prompt for the rescue narrative with the two-member shots Cast block: 6702 characters, 2273 tokens;
- a 40-line rewrite block: about 1303 tokens.

These are used in 9.1.

**Stills timing** (`images.json` / `iterate-story.log` on disk):

- the first still of a process at 1408x896 with one stills LoRA, which includes the Z-Image load, the fuse and the content-screen load: 113.2, 113.8, 115.4, 120.0, 120.3 and 121.8 s (six runs, 2026-10-05/06);
- later stills of the same process at 1280x704 (`mystorytest2`, 2026-09-17): 44.3, 47.8, 50.7 and 53.4 s.

### 0.3 Deliverables

| # | Item | File | Action |
|---|---|---|---|
| D1 | Shots strength, shots Cast block, phrase finder, roster parser, shot-rule validator, advisories, rewrite block | `character_lib.py` | edit (additions only, plus a `shots=` keyword on two functions) |
| D2 | `--shots`, `--redo`, shots template, validation and rewrite, stills groups, redo phase, shots manifest flags, skip policy, dry run | `bin/ltx-movie` | edit |
| D3 | `--shots` manifest mode (schema 3, every panel `still`, cast from Image: ∪ Motion:) | `bin/ltx-story-manifest` | edit |
| D4 | `--shots` strength rule and pinned seed | `bin/ltx-story-images` | edit |
| D5 | Tests | `tests/test_shots_mode.py` | new |

`bin/ltx-mlx-render`, `ltx2_mlx_video_skill.py`, `z_image_skill.py`, `bin/qwen-agent`, the judges, `bin/iterate-story`, the deploy tooling and **every existing test file** are unchanged.

### 0.4 Out of scope

- `--shots` with `--seed-image` (refused, E-S2) or with `--no-stills` (refused, E-S1).
- Changing judges. `seam_continuity` still assumes one continuous take (G4).
- Merging `images/images.json` across stills groups (G5).
- A seed-varying "new take" for `--redo` (G6).
- Validating semantic composition rules (framing, background placement, contact). They are prompt rules with non-fatal advisories (4.4, G2).
- A panel-count cap (9.1).
- Changing continuous mode in any observable way.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `--shots` builds its Phase 1 prompt from `STORY_PROMPT_TEMPLATE_SHOTS` (5.2), and a cast run uses the shots Cast block (3.3), both byte-exact | S3, S30-S32, S34 |
| SC2 | Each shot rule S1-S7 (4.3) has a passing case and a failing case with the exact message. Advisories W1-W2 never fail a run | S5-S19, S40 |
| SC3 | A draft that Phase 1 wrote this run and that breaks the rules is moved aside and rewritten exactly once, with the violations listed. A second failure exits 2, naming each panel and rule. A pre-existing story.md that breaks the rules exits 2 without a rewrite | S35-S39 |
| SC4 | Phase 2 renders a still for every panel. Panels are grouped by stills-LoRA set; each group is one `bin/ltx-story-images --only <group> --shots` process, whose `--only` list is exactly that group; a group whose stills all exist is skipped. E-P16 never fires | S42-S45 |
| SC5 | The shots manifest is schema 3. Every panel is `conditioning: "still"` with its own `image_path`; there is no `chain` | S46, S60, S66 |
| SC6 | In shots mode every character LoRA (video and stills, lone or paired) is 0.8 by default; `character.json` strength and then `--character-strength` override it. Continuous mode keeps 1.0 for a lone character | S2, S61, S62, S70, C36 (existing) |
| SC7 | `--shots --redo N[,M]` moves, and never deletes, only those panels' still, clip and clip provenance plus `movie.mp4`. Only those panels re-render; every other still and clip is byte-unchanged | S48, S49, S51, L-S2 |
| SC8 | Every 7.1 argument error exits 2 before any phase, lockfile or GPU work | S33 |
| SC9 | Without `--shots`, every existing argv, prompt, manifest, still prompt, provenance and dry-run is byte-identical. Every 0.2 suite passes at its 0.2 count, and B1-B3 pass | R1, S52 |
| SC10 | The deploy package file set is unchanged. `tests/test_deploy_pkg.py` stays at 165 under both interpreters | R2 |
| SC11 | Live gates L-S1 and L-S2 pass (10.8) | L-S1, L-S2 |

### 0.6 Must-have vs nice-to-have

Everything in Sections 1-11 is a must-have. There are no nice-to-haves.

---

## 1. Architecture

### 1.1 Data flow

```
bin/ltx-movie --shots [--character NAME ...] [--redo N[,M]]
  ├─ _resolve_shots (7.1 argument errors, exit 2) → _resolve_casting (shots Cast block, default 0.8)
  ├─ Phase 1: STORY_PROMPT_TEMPLATE_SHOTS (+ shots Cast block) → qwen-agent → story.md
  │     └─ _phase1_shots_finish: character_lib.shots_violations → (once) move draft aside + rewrite
  ├─ Phase 1b: story-server stop (unchanged)
  ├─ Redo (only with --redo): move panel_NN.png / panel_NN.mp4(+provenance) / movie.mp4 → redo/<stamp>-<pid>/
  ├─ Phase 2: _shots_stills_groups → for each group: bin/ltx-story-images --only <group> --shots …
  │                                  (teed to images/stills-group-KK.log; skipped when all stills exist)
  ├─ Phase 3: bin/ltx-story-manifest --shots --image panel_01.png … --image panel_NN.png [--cast …]
  │                                  → schema 3, every panel conditioning "still"
  └─ Phase 4: bin/ltx-mlx-render (unchanged tool) --resume --on-panel-failure skip
```

### 1.2 Module boundaries [spec choice]

- **`character_lib.py` owns every shot rule** (the roster parser, the Motion: heuristics, the validator, the advisories and the rewrite block). There are three reasons:
  - it is the existing stdlib-only owner of phrase matching;
  - bin/ltx-movie may not `import re` (pin L7j);
  - `character_lib.py` already ships in the deploy package.
- bin/ltx-movie loads it with the existing `_character_lib()` helper, only on the `--shots` path or the casting path. P49 still holds: an uncast run without `--shots` never loads it.
- bin/ltx-movie gets the stills-prompt composition from bin/ltx-story-images itself. It loads that file with `importlib.machinery.SourceFileLoader("ltx_story_images_for_movie", …)` and calls `_style_text` and `_compose_prompt`. The group computation therefore matches what bin/ltx-story-images will do. That file imports only stdlib at import time.
- Panels are still parsed only by `bin/ltx-story-manifest::_parse_prompts_md`, through the existing `_load_story_panels`. The `## Characters` roster is a separate section that this parser ignores by construction (0.2). `character_lib.parse_character_roster` reads only that section, so the "one story.md parser" rule (`bin/ltx-story-images:203-207`) is kept for panels.
- `bin/ltx-mlx-render` needs no change. A shots manifest is a schema-3 manifest whose panels are all `still`, which it already renders, verifies and resumes.

### 1.3 New names [spec choice]

- **`character_lib.py`:**
  - constants: `SHOTS_CHARACTER_STRENGTH`, `SHOTS_MOTION_MIN_WORDS`, `SHOTS_MOTION_MAX_WORDS`, `SHOTS_MAX_CAST_PER_PANEL`, `SHOTS_REWRITE_MAX_LISTED`, `SHOTS_CLOSE_SHOT_TYPES`, `SHOTS_CAST_BLOCK_RULES`, `SHOTS_REWRITE_TEMPLATE`;
  - private regexes: `_ROSTER_HEADER_RE`, `_ROSTER_ENTRY_RE`, `_SENTENCE_SPLIT_RE`, `_CAMERA_SENTENCE_RE`, `_CHAIN_WORD_RE`, `_COMMA_AND_RE`, `_SHOT_TYPE_RE`;
  - functions: `find_phrases`, `parse_character_roster`, `motion_problems`, `shots_violations`, `shots_advisories`, `shots_rewrite_block`.
- **`bin/ltx-movie`:**
  - constant: `STORY_PROMPT_TEMPLATE_SHOTS`;
  - functions: `_resolve_shots`, `_run_story_agent`, `_shots_check`, `_phase1_shots_finish`, `_panel_list`, `_shots_stills_groups`, `_shots_missing_stills`, `_phase2_shots`, `_print_shots_stills_plan`, `_shots_image_flags`, `_redo_moves`, `phase_redo_shots`.
- **Files written per story:**
  - `story.rejected-<UTC %Y%m%dT%H%M%SZ>-<pid>.md`;
  - `story_prompt.rewrite.txt`;
  - `images/stills-group-<KK>.log`;
  - `redo/<UTC %Y%m%dT%H%M%SZ>-<pid>/{images,clips}/…` and `redo/<…>/movie.mp4`.

---

## 2. The shots story.md contract

### 2.1 Shape

```
# <title>

<one sentence summarising the story>

## Characters
- "<referring phrase>": <full visual description>
- "<referring phrase>": <full visual description>

## Panel 1 — <short title>
Image: <80-170 words>
Motion: <10-25 words: one action sentence, optionally one camera sentence>
Narration: <one sentence>

## Panel 2 — <short title>
Image: …
Motion: …
Narration: …
```

- Every panel has `Image:`, `Motion:` and `Narration:`. There is no `Prompt:`.
- `_parse_prompts_md` parses the panels exactly as today. The title line, the summary and the `## Characters` section are invisible to it (0.2), so the manifest's `narrative` field stays the summary line, as today.
- The `## Characters` section is **the roster** **[spec choice]**. It is the only deterministic way to know an extra's referring phrase, and rule S7 ("no extra named in a cast character's Motion:") needs that. It is requested in every shots story, and enforced (S2) only when the run has cast members.

### 2.2 Approved rules → enforcement map

| Approved rule (Section 1 of the design) | Prompt text | Enforced by |
|---|---|---|
| Every panel is an independent shot with its own Image: | 5.2 | S3 (fatal) |
| Motion: is one physical action by one subject, 10-25 words, no compound chains | 5.2 | S4, S5 (fatal heuristics; G1) |
| At most 2 named characters in any shot | 3.3 rule One | S6 (fatal). **[interpretation]** "named character" means a **cast** character, one with a name in the library. The approved validation list says "<=2 cast characters per panel", and the approved design says extras-only shots "have no restrictions", so a shot of three robbers is legal |
| Shots with a cast character are medium shot or closer, cast centre/foreground | 3.3 rule Two | W2 (advisory only; G2) |
| Extras only far in the background of a cast shot, never touching or within arm's reach; close-range cast↔extra action is shown by cutting | 3.3 rule Three | S7 (fatal, on Motion:); background placement is prompt-only (G2) |
| Two cast in one shot: separated or light contact only | 3.3 rule Four | prompt-only (G2) |
| Extras-only shots: no LoRA, no restrictions | 3.3 last sentence; 5.5 grouping | S6/S7 cannot fire without a cast phrase |
| Cast phrase + full descriptor in every Image: where on screen; continuity cues | 3.3 and 5.2 | W1 (advisory only) **[spec choice]**. Rescue panel 1 shows the model paraphrases the descriptor despite "word for word" (0.2), so a fatal rule would push most runs to exit 2. Continuity cues are prompt-only (G2) |
| All character LoRAs at 0.8 in shots mode | -- | Section 6 |

---

## 3. `character_lib.py` additions (normative)

`panel_strengths` and `build_cast_block` are replaced in place by the 3.2 and 3.3 versions. `SHOTS_CAST_BLOCK_RULES` goes directly after `CAST_BLOCK_RULES`, and `SHOTS_REWRITE_TEMPLATE` directly after it. The other 3.1 constants go after `SINGLE_CHARACTER_STRENGTH`. The new functions go after `build_cast_block` and before `usable_characters`, in the order 3.4-3.9. The module docstring's first paragraph gains this sentence at its end: `It also owns the shots-mode story rules (shot-rule validation, advisories and the rewrite block; docs/superpowers/specs/2026-10-06-shots-mode-design.md).` No import is added (C41 still passes).

### 3.1 Constants

```python
SHOTS_CHARACTER_STRENGTH = 0.8
SHOTS_MOTION_MIN_WORDS = 10
SHOTS_MOTION_MAX_WORDS = 25
SHOTS_MAX_CAST_PER_PANEL = 2
SHOTS_REWRITE_MAX_LISTED = 40
SHOTS_CLOSE_SHOT_TYPES = ("medium shot", "medium close-up", "close-up", "extreme close-up")

_ROSTER_HEADER_RE = re.compile(r"##\s*Characters", re.IGNORECASE)
_ROSTER_ENTRY_RE = re.compile(r'[-*]\s*["“]([^"“”]+)["”]\s*:\s*(\S.*)')
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CAMERA_SENTENCE_RE = re.compile(r"(?:the\s+)?camera\b", re.IGNORECASE)
_CHAIN_WORD_RE = re.compile(r"\b(?:then|while|meanwhile|simultaneously|afterwards?|whereupon|"
                            r"followed\s+by|as\s+soon\s+as)\b", re.IGNORECASE)
_COMMA_AND_RE = re.compile(r",\s+and\b", re.IGNORECASE)
_SHOT_TYPE_RE = re.compile(r"(?<![\w-])(extreme wide shot|extreme close-up|medium close-up|"
                           r"medium shot|wide shot|close-up)(?![\w-])", re.IGNORECASE)
```

The thresholds come from the approved design: the 10-25 word band, at most 2 cast, and 0.8. The chain-word list is a **[spec choice]**:

- It is the approved "then"/"while" plus four unambiguous sequencing words and two sequencing phrases.
- `before`, `after` and `as` are deliberately excluded, because they are common non-sequencing words ("kneels before her", "runs after him", "as high as").

### 3.2 Strengths

```python
def panel_strengths(names, members, character_strength, shots=False):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named (continuous
    mode only); else -- and always in shots mode -- each character's own character.json strength
    if set, otherwise character_strength (casting spec 6; shots spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1 and not shots:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}
```

### 3.3 Shots Cast block (exact text)

```python
SHOTS_CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file, even when it is longer than four words, and list each of them in "
    "the Characters section with exactly the description given above. In every panel's Image: "
    "field where one of these characters is on screen, name them by that phrase and then give "
    "exactly the description given above, word for word. Shots that show these characters "
    "follow four extra rules. One: at most two of these characters appear in any one shot. "
    "Two: a shot that shows one of them is composed around them -- a medium shot or closer, "
    "with them in the centre or the foreground of the frame. Three: any other character may "
    "appear in such a shot only far in the background, small in the frame, never touching them "
    "and never within arm's reach of them, and that shot's Motion: names none of the other "
    "characters; when one of these characters and another character act on each other at close "
    "range -- a grab, a blow, a shove -- show it by cutting: first a shot of the other character "
    "performing the action, then a separate shot of this character's reaction. Four: when two "
    "of these characters share a shot they stay apart or touch only lightly, such as an offered "
    "hand or a hand on an arm; they never grapple, embrace or overlap. A shot that shows none of "
    "these characters has none of these extra rules. Bring a cast member on screen only where "
    "the narrative calls for them. Every other character still gets a referring phrase of your "
    "own, under the rules below.")


def build_cast_block(members, shots=False):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(SHOTS_CAST_BLOCK_RULES if shots else CAST_BLOCK_RULES)
    return "\n".join(lines)
```

`SHOTS_CAST_BLOCK_RULES` contains no `{`, `}` or `%`. It contains "word for word" exactly twice. It is 278 words, measured.

### 3.4 `find_phrases`

```python
def find_phrases(text, phrases):
    """The given phrases that occur in text, matched exactly like cast_text (case-insensitive,
    whitespace-tolerant, hyphen counts as a word character), longest phrase first, a match
    overlapping an already-claimed span ignored. Each phrase is returned once, as given, in the
    order of its first claimed occurrence (shots spec 3.4). Phrases must already be valid
    (normalize_phrase)."""
    claimed = []
    for phrase in sorted(set(phrases), key=lambda p: (-len(p), p.lower(), p)):
        for match in _phrase_regex(normalize_phrase(phrase)).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _ in claimed):
                continue
            claimed.append((start, end, phrase))
    ordered = []
    for _start, _end, phrase in sorted(claimed):
        if phrase not in ordered:
            ordered.append(phrase)
    return ordered
```

### 3.5 `parse_character_roster`

```python
def parse_character_roster(text):
    """([(phrase, description)], [problem]) from a shots story's "## Characters" section: the
    lines after the first line that is exactly "## Characters" (case-insensitive, any spacing
    after the hashes), up to the next line starting with "#". Blank lines are skipped; every
    other line must be - "<phrase>": <description> (straight or curly double quotes, "-" or
    "*" bullet). Phrases are normalized; a duplicate (case-insensitive) is a problem (spec 3.5)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _ROSTER_HEADER_RE.fullmatch(line.strip()):
            start = i + 1
            break
    if start is None:
        return [], ['no "## Characters" section']
    entries, problems = [], []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped:
            continue
        match = _ROSTER_ENTRY_RE.fullmatch(stripped)
        if not match:
            problems.append('line %r is not - "<referring phrase>": <description>'
                            % stripped[:80])
            continue
        try:
            phrase = normalize_phrase(match.group(1))
        except CharacterError as e:
            problems.append(str(e))
            continue
        if phrase.lower() in [p.lower() for p, _ in entries]:
            problems.append("phrase %r is listed more than once" % phrase)
            continue
        entries.append((phrase, match.group(2).strip()))
    if not entries:
        problems.append('the "## Characters" section lists no characters')
    return entries, problems
```

### 3.6 `motion_problems`

```python
def motion_problems(motion):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S4, S5). A sentence that starts
    with "camera" or "the camera" is a camera sentence and is not an action sentence."""
    problems = []
    words = len(motion.split())
    if not SHOTS_MOTION_MIN_WORDS <= words <= SHOTS_MOTION_MAX_WORDS:
        problems.append(("S4 motion length", "Motion: is %d words; it must be %d-%d"
                         % (words, SHOTS_MOTION_MIN_WORDS, SHOTS_MOTION_MAX_WORDS)))
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _CAMERA_SENTENCE_RE.match(s)]
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

### 3.7 `shots_violations`

```python
def shots_violations(text, panels, expected_panels, members):
    """Every shot-rule violation of a shots-mode story.md (spec 4.3), in this order: S1, S2, then
    per panel S3, S4, S5, S6, S7. text is the whole file; panels are bin/ltx-story-manifest
    _parse_prompts_md dicts; members are CastMember (may be empty: then S2, S6, S7 are skipped)."""
    out = []
    if len(panels) != expected_panels:
        out.append("story: S1 panel count: expected exactly %d panels, found %d"
                   % (expected_panels, len(panels)))
    roster = []
    if members:
        roster, problems = parse_character_roster(text)
        out += ["story: S2 characters list: %s" % p for p in problems]
        listed = [p.lower() for p, _ in roster]
        for m in members:
            if m.phrase.lower() not in listed:
                out.append("story: S2 characters list: cast phrase %r (character %s) is not listed"
                           % (m.phrase, m.name))
    cast_phrases = {m.phrase.lower() for m in members}
    extras = [p for p, _ in roster if p.lower() not in cast_phrases]
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
        if not members:
            continue
        names = sorted(set(cast_text(p["image"], members)[1])
                       | set(cast_text(p["motion"], members)[1]))
        if len(names) > SHOTS_MAX_CAST_PER_PANEL:
            out.append("panel %d: S6 cast count: the shot names %d cast characters (%s); at most %d"
                       % (num, len(names), ", ".join(names), SHOTS_MAX_CAST_PER_PANEL))
        found = find_phrases(p["motion"], [m.phrase for m in members] + extras)
        cast_found = [f for f in found if f.lower() in cast_phrases]
        extra_found = [f for f in found if f.lower() not in cast_phrases]
        if cast_found and extra_found:
            out.append("panel %d: S7 cast and extra: Motion: names %s together with %s; show the "
                       "other character's action in its own shot, then cut to the cast "
                       "character's reaction"
                       % (num, ", ".join(repr(f) for f in cast_found),
                          ", ".join(repr(f) for f in extra_found)))
    return out
```

### 3.8 `shots_advisories`

```python
def shots_advisories(panels, members):
    """Non-fatal shots-mode warnings (spec 4.4), per panel in order: W1 for each cast member
    named in Image: whose descriptor is not repeated there (whitespace- and case-insensitive),
    then W2 when the shot names a cast character but its Image: states no shot type, or a wide
    one. [] when members is empty."""
    out = []
    if not members:
        return out
    for p in panels:
        num = p["number"]
        image_norm = " ".join(p["image"].split()).lower()
        for m in members:
            if (phrase_occurs(p["image"], m.phrase)
                    and " ".join(m.descriptor.split()).lower() not in image_norm):
                out.append("panel %d: Image: names %r but does not repeat character %s's Cast "
                           "description word for word; that still relies on the phrase and the "
                           "stills LoRA alone" % (num, m.phrase, m.name))
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

### 3.9 Rewrite block (exact text)

```python
SHOTS_REWRITE_TEMPLATE = (
    "REWRITE REQUIRED. Your previous draft of this file was rejected because it broke these "
    "rules:\n"
    "%s\n"
    "Write the complete file again from the beginning, following every instruction above and "
    "fixing every listed problem. Keep EXACTLY %d panel sections. Where a Motion: held more than "
    "one action, keep only its single most important action and give the other beats their own "
    "panels instead, merging or dropping minor beats so that the panel count stays the same.")


def shots_rewrite_block(violations, panels):
    """The text appended to the Phase 1 prompt for the one rewrite (spec 5.4): at most
    SHOTS_REWRITE_MAX_LISTED violations as "- <violation>" lines, then "- ... and N more"."""
    listed = violations[:SHOTS_REWRITE_MAX_LISTED]
    lines = ["- " + v for v in listed]
    if len(violations) > len(listed):
        lines.append("- ... and %d more" % (len(violations) - len(listed)))
    return SHOTS_REWRITE_TEMPLATE % ("\n".join(lines), panels)
```

The rewrite prompt does **not** include the rejected draft **[spec choice]**. It costs about 440-460 estimated tokens per panel (9.1), and the violation list already names every panel and rule.

---

## 4. Validation rules (normative index)

### 4.1 When validation runs

| Situation | Rules | On violations |
|---|---|---|
| `--shots`, Phase 1 wrote story.md in **this** run | S1-S7 (S2, S6, S7 only with cast) | first time: warning (stdout), move the draft aside, one rewrite (5.4). Second time: exit 2 (E-S10) |
| `--shots`, story.md already existed (Phase 1 skipped, including every `--redo` run) | S1-S7 | exit 2, no rewrite (E-S9) **[spec choice]**: the file may hold hand edits, and the story model must never overwrite user data |
| no `--shots` | today's `_validate_story_md` only | unchanged |

### 4.2 Violation string format

`"story: <rule>: <detail>"` or `"panel <N>: <rule>: <detail>"`. `<N>` is the number in the `## Panel N` header. `<rule>` is one of `S1 panel count`, `S2 characters list`, `S3 fields`, `S4 motion length`, `S5 one action`, `S6 cast count`, `S7 cast and extra`. Each printed line therefore names the panel and the rule (the approved error behavior).

### 4.3 Rules

| Rule | Check (exact) | Message detail(s) |
|---|---|---|
| S1 | `len(panels) == --panels` | `expected exactly <n> panels, found <m>` |
| S2 (cast only) | `parse_character_roster` (3.5) problems, then each cast phrase is listed (case-insensitive) | `no "## Characters" section` / `line '<…>' is not - "<referring phrase>": <description>` / `<normalize_phrase message>` / `phrase '<p>' is listed more than once` / `the "## Characters" section lists no characters` / `cast phrase '<p>' (character <name>) is not listed` |
| S3 | `Image:`, `Motion:`, `Narration:` non-empty; no `Prompt:` | `missing/empty <Label>: field` / `has a Prompt: field; shots mode expects Image:, Motion: and Narration:` |
| S4 | `10 <= len(motion.split()) <= 25` (the whole field, camera sentence included) | `Motion: is <w> words; it must be 10-25` |
| S5 | (a) exactly 1 non-camera sentence after splitting on `(?<=[.!?])\s+`; (b) no `;`; (c) no `_CHAIN_WORD_RE` match; (d) no `,\s+and\b` | (a) `Motion: has <k> action sentences; it must have exactly one, optionally followed by a camera sentence`; (b) `Motion: contains a semicolon`; (c) `Motion: chains actions with '<word>'` (lowercased, whitespace-collapsed); (d) `Motion: chains actions with ', and'` |
| S6 (cast only) | the cast names found by `cast_text` in `Image:` ∪ `Motion:` number at most 2 | `the shot names <k> cast characters (<names sorted>); at most 2` |
| S7 (cast only) | `find_phrases(Motion:, cast phrases + extra phrases)` must not contain a cast phrase together with an extra phrase | `Motion: names '<cast>'[, …] together with '<extra>'[, …]; show the other character's action in its own shot, then cut to the cast character's reaction` |

### 4.4 Advisories (never fatal; printed as `Warning: <text>` to stdout)

| ID | Condition | Text |
|---|---|---|
| W1 | a cast phrase occurs in a panel's Image:, and that member's descriptor (whitespace-collapsed, lowercased) is not a substring of the whitespace-collapsed, lowercased Image: | `panel <N>: Image: names '<phrase>' but does not repeat character <name>'s Cast description word for word; that still relies on the phrase and the stills LoRA alone` |
| W2 | the shot names a cast character (Image: ∪ Motion:), and its Image: has no `_SHOT_TYPE_RE` match, or any match is not in `SHOTS_CLOSE_SHOT_TYPES` | `panel <N>: shows cast character(s) <names> but its Image: shot type is <types or "not stated">; a shot with a cast character should be a medium shot or closer` |

---

## 5. Pipeline integration (normative)

### 5.1 `bin/ltx-movie` arguments and `_resolve_shots`

**Arguments.** Add these two directly after `--list-characters` in `build_parser`. No existing help string changes.

```python
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                         help="shots mode: every panel is its own shot with its own Image: still "
                              "and is rendered from that still (no chaining; cuts between "
                              "panels). Phase 1 uses the shots story template and enforces the "
                              "shot rules (one action per Motion:, at most two cast characters "
                              "per shot), Phase 2 renders a still for every panel, and every "
                              "cast character LoRA defaults to 0.8. See docs/superpowers/specs/"
                              "2026-10-06-shots-mode-design.md.")
    parser.add_argument("--redo", dest="redo", default=None, metavar="N[,M...]",
                         help="with --shots and an existing story.md: move panels N,M...'s "
                              "stills and clips (and movie.mp4) aside into "
                              "<story>/redo/<stamp>/ and re-render only those panels; every "
                              "other panel is reused")
```

**`_resolve_shots(args)`.** Add it after `_resolve_global_loras`. `main` calls it directly after the `--story-prompt-override` file-existence check and **before** `rc = _resolve_casting(args)`, using the same `rc = …; if rc: return rc` pattern.

```python
def _resolve_shots(args):
    """Validate --shots/--redo (shots spec 5.1). Sets args.redo_panels to the sorted, de-duplicated
    panel numbers ([] without --redo). Returns 0, or 2 after one Error: line. Touches nothing."""
    args.redo_panels = []
    if not args.shots:
        if args.redo is not None:
            print("Error: --redo requires --shots", file=sys.stderr)
            return 2
        return 0
    if args.no_stills:
        print("Error: --shots needs Phase 2's per-panel stills; it cannot be combined with "
              "--no-stills", file=sys.stderr)
        return 2
    if getattr(args, "seed_image", None):
        print("Error: --shots is not supported with --seed-image: the seed image can be only "
              "panel 1's still, and the seed-image story preface describes the chained flow",
              file=sys.stderr)
        return 2
    if args.redo is None:
        return 0
    if args.force_story:
        print("Error: --redo cannot be combined with --force-story: --force-story writes a new "
              "story.md, so every panel changes", file=sys.stderr)
        return 2
    if args.story_only:
        print("Error: --redo cannot be combined with --story-only: --story-only stops before the "
              "stills and clips that --redo re-renders", file=sys.stderr)
        return 2
    try:
        panels = sorted({int(x) for x in args.redo.split(",") if x.strip()})
    except ValueError:
        panels = []
    if not panels:
        print("Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; "
              "got %r" % args.redo, file=sys.stderr)
        return 2
    for n in panels:
        if not 1 <= n <= args.panels:
            print("Error: --redo panel %d is out of range (1..%d)" % (n, args.panels),
                  file=sys.stderr)
            return 2
    story_md = _story_paths(args.story_id)["story_md"]
    if not os.path.isfile(story_md):
        print("Error: --redo needs an existing story.md: %s" % story_md, file=sys.stderr)
        return 2
    args.redo_panels = panels
    return 0
```

- The range is checked against `--panels` **[spec choice]**. That is the count the validator enforces (S1), so `--redo` needs the same `--panels` as the original run.
- Duplicates are de-duplicated silently.
- `--shots` with `--story-prompt-override` is allowed **[spec choice]**. The override is used verbatim, as today, and the shot rules and the one rewrite still apply.
- `--shots` without any cast is allowed **[spec choice]**. Only S1 and S3-S5 apply, and there is one stills group.

**`_resolve_casting` (two edits).**

1. The default-strength expression becomes:

```python
    strength = (args.character_strength if args.character_strength is not None
                else (lib.SHOTS_CHARACTER_STRENGTH if getattr(args, "shots", False)
                      else lib.DEFAULT_CHARACTER_STRENGTH))
```

2. `args.cast_block = lib.build_cast_block(members)` becomes `args.cast_block = lib.build_cast_block(members, shots=getattr(args, "shots", False))`.

**Module docstring.** Append this paragraph after the casting paragraph:

> Shots mode (docs/superpowers/specs/2026-10-06-shots-mode-design.md): --shots makes every panel its own shot. Phase 1 uses STORY_PROMPT_TEMPLATE_SHOTS (a Characters list, an Image: field on every panel, one action per Motion:) and enforces the shot rules in character_lib.shots_violations, asking the story model for one rewrite of a draft it wrote in this run; Phase 2 renders a still for every panel, one bin/ltx-story-images run per stills-LoRA group (z_image_skill holds one LoRA set per process); Phase 3 builds a --shots manifest in which every panel is conditioned on its own still; Phase 4 renders independent clips (--on-panel-failure skip). Every cast character LoRA defaults to 0.8, alone or paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into <story>/redo/<stamp>-<pid>/ so that only they re-render.

### 5.2 `STORY_PROMPT_TEMPLATE_SHOTS` (exact text) and `build_story_prompt`

Place this constant directly after `STORY_PROMPT_TEMPLATE_NO_STILLS`:

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
Image: <80-170 words describing this shot's first frame as one still picture: every character who is on screen, each named by their referring phrase and then given their full description from the Characters section, word for word; where each one stands and which way they face; the setting and background; the lighting and colour palette; the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up); the camera viewpoint; and the rendering style.>
Motion: <10-25 words: one sentence naming ONE character by their referring phrase and the ONE physical action they perform during these {seconds} seconds, then a separate short sentence about the camera, for example "The camera stays static.">
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

One action per shot. {seconds} seconds is enough for one gesture, a few steps, one swing or one turn of the head -- not for a sequence. The Motion: action sentence gives one character one action: never chain actions with "then", "while", "meanwhile", "simultaneously", "afterwards", "followed by" or ", and", never use a semicolon, and never write a second action sentence. When the story needs a sequence -- for example a charge, a draw and a strike -- give each beat its own panel, so a fight or a chase takes several panels. Do not describe appearance, clothing, setting or lighting in Motion: -- that belongs in Image:.

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from shot to shot and by the narration. Each panel should move the action forward instead of repeating the previous panel's action.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls."""
```

Its only braces are `{story_id}`, `{narrative}`, `{seconds}` and `{panels}` (verified). The anchor `\n\nHow this movie is made:` occurs exactly once, so the existing Cast-block insertion in `build_story_prompt` works unchanged. The template is 642 words.

**`build_story_prompt`.**

- The signature becomes `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds, cast_block=None, shots=False)`.
- The template line becomes:

```python
    template = (STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills
                else STORY_PROMPT_TEMPLATE_SHOTS if shots else STORY_PROMPT_TEMPLATE)
```

- Both call sites (`phase1_story`, `_print_dry_run_plan`) add `shots=getattr(args, "shots", False)` after `cast_block=…`.
- With `shots=False`, every call is byte-identical to today (S32, B1).

### 5.3 Strengths downstream

`_cast_flags(args)` is unchanged. It always forwards `--character-strength <resolved>`, which is `0.8` by default in shots mode. The sub-tools receive `--shots` (5.5, 5.7), which switches the lone-character rule (Section 6).

### 5.4 Phase 1: extraction, shots finish, the one rewrite

**(a) Extract `_run_story_agent`** (a refactor, behavior-preserving). Add a module-level function directly above `phase1_story`. Its body is the block of `phase1_story` that runs from the line `print("Running (timeout %ds): %s" % (` through the end of the `if proc.returncode != 0:` block. Move it verbatim, dedented by 4 spaces, with exactly two changes:

1. `len(prompt)` becomes `len(cmd[-1])`. The last element of `cmd` is the prompt, so the output is byte-identical.
2. `return 0` is appended at the end.

```python
def _run_story_agent(cmd, timeout, story_md):
    """Run one bin/qwen-agent story-authoring call: print the command, wait up to timeout
    seconds, and apply Phase 1's exit-code rules. Returns 0 when story.md may be validated
    (including qwen-agent exiting nonzero after writing it), else 1. Moved verbatim out of
    phase1_story so the shots rewrite reuses it (shots spec 5.4)."""
    print("Running (timeout %ds): %s" % (
        timeout, shlex.join(cmd[:-1] + ["--user-prompt", "<%d chars>" % len(cmd[-1])])
    ))
    ... (the moved lines, unchanged, through the final "return 1") ...
    return 0
```

In `phase1_story`:

- add `authored = None` directly after `story_md = paths["story_md"]`;
- replace the moved block with:

```python
        rc = _run_story_agent(cmd, timeout, story_md)
        if rc:
            return rc
        authored = {"cmd": cmd, "timeout": timeout, "prompt": prompt}
```

- directly before `    violations = _validate_story_md(story_md, args.panels, args.no_stills)`, insert:

```python
    if getattr(args, "shots", False):
        return _phase1_shots_finish(args, story_md, authored)
```

The chained path after that line is untouched, so pins L7i, L19 and `:531` hold.

**(b) `_shots_check` and `_phase1_shots_finish`.**

```python
def _shots_check(lib, story_md, expected_panels, members):
    """(violations, advisories) for a shots-mode story.md (shots spec 4)."""
    try:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return ["story: cannot read story.md: %s" % e], []
    panels = _load_story_panels(story_md)
    return (lib.shots_violations(text, panels, expected_panels, members),
            lib.shots_advisories(panels, members))


def _phase1_shots_finish(args, story_md, authored):
    """Shots-mode Phase 1 after story.md exists (shots spec 5.4): validate; a draft the story
    model wrote in this run gets exactly one rewrite; then the story dump, the advisories, the
    cast-phrase warnings and the review gate. authored is None when Phase 1 was skipped."""
    lib = _character_lib()
    members = getattr(args, "cast_members", None) or []
    violations, advisories = _shots_check(lib, story_md, args.panels, members)
    if violations and authored is None:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to have "
              "the story model write a new one." % story_md, file=sys.stderr)
        return 2
    if violations:
        story_dir = os.path.dirname(story_md)
        rejected = os.path.join(story_dir, "story.rejected-%s-%d.md"
                                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
        print("Warning: the story model's draft broke the shot rules; moving it to %s and asking "
              "for one rewrite:" % rejected)
        for v in violations:
            print("  - %s" % v)
        os.replace(story_md, rejected)
        rewrite = authored["prompt"] + "\n\n" + lib.shots_rewrite_block(violations, args.panels)
        with open(os.path.join(story_dir, "story_prompt.rewrite.txt"), "w", encoding="utf-8") as f:
            f.write(rewrite)
        cmd = list(authored["cmd"])
        cmd[-1] = rewrite
        print("=== Phase 1: story (rewrite) ===")
        rc = _run_story_agent(cmd, authored["timeout"], story_md)
        if rc:
            print("Error: the shots rewrite failed; the rejected first draft is kept at %s"
                  % rejected, file=sys.stderr)
            return rc
        violations, advisories = _shots_check(lib, story_md, args.panels, members)
        if violations:
            print("Error: story.md still breaks the shot rules after one rewrite:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("The rejected first draft is kept at %s. Hand-edit %s to fix the violations "
                  "above and rerun (Phase 1 is skipped while story.md exists), or rerun with "
                  "--force-story." % (rejected, story_md), file=sys.stderr)
            return 2
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

Why it works this way:

- **The draft is moved aside, never overwritten or deleted [spec choice].** Two reasons:
  1. It keeps the rejected draft for diagnosis.
  2. It makes the rewrite's `write_file` a **new** file, which qwen-agent auto-approves (0.2), so an unattended `--no-review` run never hangs on an overwrite prompt.
- The name carries a UTC stamp and the pid, so no earlier rejected draft is ever replaced.
- The rewrite reuses Phase 1's `cmd` object, with only the prompt replaced. `--max-tokens` and the timeout are the same, and the source-count pins hold.
- `story_prompt.rewrite.txt` is the audit record of the second prompt. `story_prompt.txt` keeps the first prompt, unchanged.

### 5.5 Phase 2: stills groups

**Grouping.**

```python
def _panel_list(panels):
    return ",".join(str(i) for i in panels)


def _shots_stills_groups(story_md_path, members):
    """[(names, [panel numbers])]: shots-mode panels grouped by the cast characters whose stills
    LoRAs bin/ltx-story-images will load for them -- the same _compose_prompt(Image:, Style:) +
    cast_text(insert=members with a stills LoRA) match it performs, so every group is one LoRA
    set (shots spec 5.5). Sorted by (len(names), names); panels ascending, 1-based by position.
    Uncast: one group of every panel."""
    panels = _load_story_panels(story_md_path)
    by_panel = {i: () for i in range(1, len(panels) + 1)}
    if members:
        lib = _character_lib()
        images = importlib.machinery.SourceFileLoader(
            "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
        style = images._style_text(panels)
        insert = {m.name for m in members if m.stills_lora}
        for i, p in enumerate(panels, start=1):
            by_panel[i] = tuple(lib.cast_text(images._compose_prompt(p["image"], style), members,
                                              insert=insert)[1])
    groups = {}
    for i, names in sorted(by_panel.items()):
        groups.setdefault(names, []).append(i)
    return sorted(groups.items(), key=lambda g: (len(g[0]), g[0]))


def _shots_missing_stills(args, panels):
    """The panels of one group whose still must be generated: those being redone, and those
    with no images/panel_NN.png."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```

Two facts make "one group = one LoRA set" hold, so E-P16 can never fire on a group:

- the global stills LoRAs are identical for every panel;
- the shots strength rule (Section 6) depends only on the character, not on how many are present.

**`phase2_stills` edit.** Directly after `    cmd += _cast_flags(args)`, insert:

```python
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

So the existing command construction, which carries the `["--lora", args.stills_lora_path]` literal (pin L1z5), is reused. The E-P11 panel-1 warning is not printed in shots mode, because stills are reused by existence and `--redo` is the regeneration mechanism.

```python
def _phase2_shots(args, cmd):
    """Phase 2 in shots mode (shots spec 5.5): one bin/ltx-story-images run per stills-LoRA group,
    each the Phase 2 cmd with --only <the group's panels> and --shots appended, teed to
    images/stills-group-KK.log. A group with no missing still is skipped. A failing group does
    not stop the rest: every group runs, then one error lists each failed group and Phase 2
    returns 1. Stills already written are kept."""
    paths = _story_paths(args.story_id)
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [])
    os.makedirs(paths["images_dir"], exist_ok=True)
    failed = []
    for k, (names, panels) in enumerate(groups, start=1):
        label = "%s; panels %s" % (", ".join(names) or "no character LoRAs", _panel_list(panels))
        if not _shots_missing_stills(args, panels):
            print("stills group %d/%d (%s): every still exists; skipped" % (k, len(groups), label))
            continue
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        log_path = os.path.join(paths["images_dir"], "stills-group-%02d.log" % k)
        print("stills group %d/%d (%s); log: %s" % (k, len(groups), label, log_path))
        print("Running: %s" % shlex.join(group_cmd))
        rc = _stream_and_tee(group_cmd, log_path)
        if rc != 0:
            failed.append("  - stills group %d/%d (%s) exited %d -- see %s"
                          % (k, len(groups), label, rc, log_path))
    if failed:
        print("Error: ltx-story-images exited nonzero for %d of %d stills groups:"
              % (len(failed), len(groups)), file=sys.stderr)
        for line in failed:
            print(line, file=sys.stderr)
        print("Stills already written are kept. If a log shows \"panel N BLOCKED\", edit that "
              "panel's Image: line in story.md first -- the stills seed is pinned, so a rerun alone "
              "reproduces the block. Then rerun the same command to continue -- groups whose stills "
              "all exist are skipped.", file=sys.stderr)
        return 1
    return 0
```

- `--only` lists the whole group, not only its missing panels **[spec choice]**. bin/ltx-story-images skips existing stills itself, and the log shows the full group.
- **Skipping a fully rendered group [spec choice]** avoids a process start plus the torch import, and leaves `images.json` as it was.
- **Every group runs; Phase 2 fails at the end [user decision, 2026-10-07].** The stills seed is pinned (S71), so a content-safety BLOCK on one panel recurs on every rerun. Stopping at the first failing group would keep every later, independent group (often the cast characters) from ever rendering. So Phase 2 runs every group with a missing still, then prints one E-S12 error that lists each failed group and returns 1, never a group's rc. Phase 4's `skip` policy (5.7) follows the same reasoning.
- Seeds come from bin/ltx-story-images `--shots` (5.7): every still uses `--image-seed` exactly.
- Group order is by size, then by names: `()`, then single characters alphabetically, then pairs. For the rescue cast that is at most 4 groups: `()`, `(kyra,)`, `(ronin,)`, `(kyra, ronin)`.

### 5.6 `--redo`: moving panels aside

**Choice and justification [spec choice].** `--redo` invalidates by **moving** files into a per-run archive, and never deletes. Moving is chosen for three reasons:

1. **Missing file is the one invalidation signal both tools already honor.** bin/ltx-story-images regenerates a missing `panel_NN.png`. bin/ltx-mlx-render's `clip_is_reusable` returns False for a missing clip. No tool gains a per-panel force flag.
2. **Nothing the user made is lost.** The previous take stays next to the new one for an A/B. bin/ltx-story-images `--force` would overwrite the old still in place, and there is no per-panel clip force at all.
3. **No cascade.** Shots panels are independent (`still` conditioning), so the other panels' provenance (image bytes, prompt, seed, LoRAs) is unchanged and `--resume` reuses them.

`movie.mp4` is moved too. That keeps the previous cut for comparison, and lets Phase 4's existing "already exists; pass --force" guard pass without `--force`.

```python
def _redo_moves(args, archive):
    """[(src, dst)] for every existing file --redo moves aside (shots spec 5.6), in order: per redo
    panel its still, clip and clip provenance; then movie.mp4. Reads only os.path state."""
    paths = _story_paths(args.story_id)
    clips_dir = os.path.join(paths["story_dir"], "clips")
    moves = []
    for n in args.redo_panels:
        for src, sub in ((os.path.join(paths["images_dir"], "panel_%02d.png" % n), "images"),
                         (os.path.join(clips_dir, "panel_%02d.mp4" % n), "clips"),
                         (os.path.join(clips_dir, "panel_%02d.mp4.provenance.json" % n), "clips")):
            if os.path.lexists(src):
                moves.append((src, os.path.join(archive, sub, os.path.basename(src))))
    if os.path.lexists(paths["movie_path"]):
        moves.append((paths["movie_path"], os.path.join(archive, "movie.mp4")))
    return moves


def phase_redo_shots(args):
    """--redo (shots spec 5.6): move the named panels' still, clip and clip provenance, and
    movie.mp4, into <story>/redo/<UTC stamp>-<pid>/, so Phase 2 regenerates only those stills
    and Phase 4 (--resume) re-renders only those clips. Never deletes anything."""
    paths = _story_paths(args.story_id)
    panels = _panel_list(args.redo_panels)
    print("=== Redo: panels %s ===" % panels)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d"
                           % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
    moves = _redo_moves(args, archive)
    for src, dst in moves:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
        except OSError as e:
            print("Error: --redo could not move %s to %s: %s" % (src, dst, e), file=sys.stderr)
            return 1
        print("redo: moved %s -> %s" % (src, dst))
    if not moves:
        print("redo: nothing to move (no still, clip or movie exists yet for panels %s)" % panels)
    print("redo: panels %s re-render; every other panel's still and clip is reused (stills by "
          "existence, clips by --resume provenance)" % panels)
    return 0
```

**`_phase_sequence`.** After the `--story-server-stop-after-story` insertion and before the `--seed-image` prefix:

```python
    if getattr(args, "redo_panels", None):
        cut = phases.index(phase2_stills)
        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]
```

- The redo phase runs after Phase 1's validation (an invalid story exits 2 before anything moves), and before Phase 2.
- `--redo` requires `--shots`, which excludes `--no-stills`, so `phase2_stills` is always present.
- Objects without `redo_panels` (test L41) get today's sequences.

**Seeds.** `--redo` re-renders with the same seeds: the stills use the pinned `--image-seed`, and the render uses `--seed + i`. So `--redo` is meant to follow an edit of that panel's `Image:` and/or `Motion:` in story.md. An unedited redo reproduces the same take (G6).

### 5.7 Phase 3 and Phase 4

```python
def _shots_image_flags(args):
    """--image <images>/panel_NN.png for every panel 1..--panels, in order (shots spec 5.7)."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    flags = []
    for i in range(1, args.panels + 1):
        flags += ["--image", os.path.join(images_dir, "panel_%02d.png" % i)]
    return flags
```

- **`phase3_manifest`.** Between `if args.no_stills: cmd_manifest += ["--no-images"]` and its `else:`, insert `elif getattr(args, "shots", False): cmd_manifest += ["--shots"] + _shots_image_flags(args)`.
- **`_print_dry_run_plan`.** Insert the identical `elif` into its `phase3_manifest_cmd` block. The rest of each command (`--fps … --force`, then `_cast_flags(args)`) is unchanged.
- **`_phase4_flags`.** The failure-policy line becomes `"--on-panel-failure", "skip" if (args.no_stills or getattr(args, "shots", False)) else "stop",` **[spec choice]**. Shots clips are independent, like `--no-stills` clips, so one failed panel must not stop the rest. bin/ltx-mlx-render's end-of-run retry pass (one retry after 120 s) applies, because the manifest has no chain units. The docstring gains: `--shots renders independent clips too and passes skip.`
- **Phase 4** is otherwise unchanged. The render tool is unchanged.

### 5.8 Dry run

In `_print_dry_run_plan` (every addition is conditional, so an uncast dry run without `--shots` is byte-identical, B1):

1. The rendered prompt uses `shots=` (5.2).
2. After the Phase 1b block and before the `if args.no_stills:` Phase 2 block, insert:

```python
    if getattr(args, "redo_panels", None):
        print("--- Redo: panels %s ---" % _panel_list(args.redo_panels))
        for src, dst in _redo_moves(args, os.path.join(paths["story_dir"], "redo",
                                                       "<UTC stamp>-<pid>")):
            print("Would move %s -> %s" % (src, dst))
        print("Then only those panels' stills and clips re-render; every other panel is reused.")
        print()
```

3. In the Phase 2 block, replace `        print("Command: %s" % shlex.join(phase2_cmd))` with:

```python
        if getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
        else:
            print("Command: %s" % shlex.join(phase2_cmd))
```

```python
def _print_shots_stills_plan(args, cmd):
    """Phase 2's dry-run lines in shots mode (shots spec 5.8). Touches nothing."""
    story_md = _story_paths(args.story_id)["story_md"]
    if args.force_story or not os.path.exists(story_md):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = "<PANELS>"
        group_cmd.append("--shots")
        print("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of "
              "cast stills LoRAs, each with --only <PANELS> (that group's panels):")
        print("Command: %s" % shlex.join(group_cmd))
        return
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        skip = "" if _shots_missing_stills(args, panels) else " -- would be skipped: every still exists"
        print("stills group %d/%d (%s; panels %s)%s"
              % (k, len(groups), ", ".join(names) or "no character LoRAs", _panel_list(panels), skip))
        print("Command: %s" % shlex.join(group_cmd))
```

4. The Phase 3 manifest command uses the 5.7 `elif`. The Phase 4 command shows `--on-panel-failure skip`.

### 5.9 `bin/ltx-story-manifest --shots`

1. **Argument**, directly after `--chain`:

```python
    parser.add_argument("--shots", action="store_true", default=False,
                         help="shots flow (bin/ltx-movie --shots): every panel is its own shot "
                              "conditioned on its own still; give one --image per panel, in "
                              "panel order. Requires --prompts-md; mutually exclusive with "
                              "--chain, --glob and --no-images. With --cast, a panel's "
                              "characters are those its Image: or Motion: names, each at its "
                              "character.json strength or --character-strength (default 0.8), "
                              "alone or not.")
```

2. **Validation.** Directly **before** the first `    if args.chain:` in `main` (the argument-validation block at `:351`), insert the block below. Then replace `    if args.cast and not args.chain:\n        parser.error("--cast requires --chain")` with `    if args.cast and not (args.chain or args.shots):\n        parser.error("--cast requires --chain or --shots")`. P23's substring holds.

```python
    if args.shots:
        if args.chain or args.no_images or args.glob:
            parser.error("--shots is mutually exclusive with --chain, --glob and --no-images")
        if not args.prompts_md:
            parser.error("--shots requires --prompts-md")
```

3. **Field checks.** Directly after the `if args.chain: … elif not args.no_images and len(parsed_panels) != len(matched): …` block (`:404-426`, before the "both a Prompt: field and an Image:/Motion:" loop), insert the block below. The count check (`Error: prompts.md has %d panels but %d images were selected`) already applies to `--shots`, because it is not `--chain`.

```python
        if args.shots:
            for i, pt in enumerate(parsed_panels, start=1):
                if not pt["image"].strip():
                    print("Error: --shots requires every panel to have a non-empty Image: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if not pt["motion"].strip():
                    print("Error: --shots requires every panel to have a non-empty Motion: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if pt["prompt"].strip():
                    print("Error: --shots does not accept Prompt: fields; panel %d has one" % i,
                          file=sys.stderr)
                    return 2
```

4. **Default strength:** `strength = (args.character_strength if args.character_strength is not None else (lib.SHOTS_CHARACTER_STRENGTH if args.shots else lib.DEFAULT_CHARACTER_STRENGTH))`.
5. **Panel loop** (`:517-574`). Insert an `elif args.shots:` branch between that loop's `if args.chain:` branch and its `else:`:

```python
        elif args.shots:
            title = pt["title"]
            narration = pt["narration"]
            motion_prompt = pt["motion"]
            image_path = matched[i - 1]
            conditioning = "still"
            panel_text = pt["image"]
```

6. **Cast application.** Inside `if members:`, after `p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)`, add:

```python
            if args.shots:
                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))
```

   - `panel_strengths(...)` gets `shots=args.shots`.
   - The E-P14 warning becomes `"WARNING: cast phrase %r (character %s) occurs in no panel's %s text; that character gets no LoRA" % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:")`. The chained output is byte-identical (P22).
   - **The video character set is Image: ∪ Motion: [spec choice].** In shots mode the Image: is the panel's own conditioning frame, so it is the authoritative list of who is on screen, and a pronoun-only Motion: ("She bows") no longer drops the LoRA (casting gap G5).
   - Triggers are still inserted only into `motion_prompt`, where the phrase occurs. `panel_text` is left as authored.
7. `_prompt_length_warning(p["index"], p["motion_prompt"] if (args.chain or args.shots) else p["panel_text"])`.
8. `"schema_version": 3 if (args.chain or args.shots) else 2`.
9. **Docstring.** Append: `--shots (bin/ltx-movie --shots) writes schema_version 3 with every panel conditioning "still": one --image per panel, in order; panel_text is the Image: text and motion_prompt the Motion: text. With --cast, a panel's characters are the cast phrases its Image: or Motion: names, each at its character.json strength or --character-strength (default 0.8), alone or not.`

### 5.10 `bin/ltx-story-images --shots`

1. **Argument**, directly after `--character-strength`:

```python
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                        help="shots mode (bin/ltx-movie --shots): every generated panel uses --seed "
                             "exactly (pinned, as in grounded mode), and every cast character's "
                             "stills LoRA, alone or with another, uses its character.json strength "
                             "or --character-strength (default 0.8)")
```

2. **Default strength:** `(args.character_strength if args.character_strength is not None else (lib.SHOTS_CHARACTER_STRENGTH if args.shots else lib.DEFAULT_CHARACTER_STRENGTH))`.
3. `strengths = lib.panel_strengths(names, stills_members, strength, shots=args.shots)`.
4. `grounded = bool(style)` becomes `grounded = bool(style) or args.shots`.
   - **[interpretation]** The approved "pinned seed grounded mode as today" means every shots still uses the grounded-mode seed rule: `--seed` exactly for every panel, not `--seed + i`. That favours the matching setting and palette that the cuts rely on.
   - Style text is still appended only when Panel 1 has a `Style:` field.
   - The comment above that line gains: `--shots pins the seed the same way (shots spec 5.10).`
   - Pin I20 holds, because it checks the substring `grounded = bool(style)`.
5. **Docstring.** Append: `--shots (bin/ltx-movie --shots) pins every generated panel's seed to --seed and gives every cast character's stills LoRA, alone or paired, its character.json strength or --character-strength (default 0.8).`
6. `--shots` without `--cast` is accepted. It only pins the seed.

---

## 6. Strengths

| Mode | Panel names | Strength per character |
|---|---|---|
| continuous (today, unchanged) | exactly one cast character | `SINGLE_CHARACTER_STRENGTH` = 1.0 |
| continuous | two or more | `character.json` strength, else `--character-strength`, else `DEFAULT_CHARACTER_STRENGTH` (0.8) |
| shots | one **or** two | `character.json` strength, else `--character-strength`, else `SHOTS_CHARACTER_STRENGTH` (0.8) |

- The same rule applies to video LoRAs (manifest) and stills LoRAs (bin/ltx-story-images). Global LoRAs are never counted and never changed (casting spec 5.7.6).
- **Precedence [spec choice]:** the `character.json` strength beats `--character-strength`, the same as today's multi-character rule.
- `SHOTS_CHARACTER_STRENGTH` is a separate constant from `DEFAULT_CHARACTER_STRENGTH`, so a future retune of the continuous pair default cannot move shots mode.
- **Evidence and risk:** a lone LoRA at 1.0 restyled uncast people; a lone 0.7 lost the ronin; two characters at 0.8 in quiet shots held (user eyeball) but drifted (judge) (0.2). L-S1 is the gate for 0.8 (G8).

---

## 7. Error handling

`Error:` lines go to stderr. `Warning:` lines and `WARNING:` lines go to stdout.

### 7.1 `bin/ltx-movie` argument errors (exit 2, before any phase, lockfile or GPU work)

| # | Condition | Message |
|---|---|---|
| E-S1 | `--shots` + `--no-stills` | `Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills` |
| E-S2 | `--shots` + `--seed-image` | `Error: --shots is not supported with --seed-image: the seed image can be only panel 1's still, and the seed-image story preface describes the chained flow` |
| E-S3 | `--redo` without `--shots` | `Error: --redo requires --shots` |
| E-S4 | `--redo` value with no int, a non-int, or empty | `Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; got '<v>'` |
| E-S5 | `--redo` panel < 1 or > `--panels` | `Error: --redo panel <n> is out of range (1..<panels>)` |
| E-S6 | `--redo` + `--force-story` | `Error: --redo cannot be combined with --force-story: --force-story writes a new story.md, so every panel changes` |
| E-S7 | `--redo` + `--story-only` | `Error: --redo cannot be combined with --story-only: --story-only stops before the stills and clips that --redo re-renders` |
| E-S8 | `--redo` with no story.md | `Error: --redo needs an existing story.md: <path>` |

Checks run in the order of the 5.1 `_resolve_shots` code: E-S3, E-S1, E-S2, E-S6, E-S7, E-S4, E-S5, E-S8. `_resolve_shots` runs after the existing `main` checks, so the existing `--seed-image` + `--no-stills` error still wins when all three flags are given.

### 7.2 Runtime

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-S9 | ltx-movie | `--shots`, story.md pre-existed, S-violations | 2. `Error: story.md breaks the shot rules:` plus one `  - <violation>` line each, plus the hand-edit hint (5.4). No file changes |
| E-S10 | ltx-movie | first draft (this run) violates | `Warning:` plus the list (stdout); the draft moves to `story.rejected-<stamp>-<pid>.md`; one rewrite. If the rewrite also violates: 2, with `Error: story.md still breaks the shot rules after one rewrite:`, the list, and the kept-draft hint |
| E-S11 | ltx-movie | qwen-agent fails during the rewrite (rc 1 path: timeout, or nonzero with no story.md) | 1. The existing qwen-agent error, then `Error: the shots rewrite failed; the rejected first draft is kept at <path>` |
| E-S12 | ltx-movie | one or more stills groups exit nonzero | 1, after every group has run (whatever the groups' rc values). `Error: ltx-story-images exited nonzero for <f> of <n> stills groups:`, then one line per failed group, in group order: `  - stills group <k>/<n> (<names or "no character LoRAs">; panels <list>) exited <rc> -- see <story>/images/stills-group-<KK>.log`, then `Stills already written are kept. If a log shows "panel N BLOCKED", edit that panel's Image: line in story.md first -- the stills seed is pinned, so a rerun alone reproduces the block. Then rerun the same command to continue -- groups whose stills all exist are skipped.` |
| E-S13 | ltx-movie | `--redo` move fails (OSError) | 1. `Error: --redo could not move <src> to <dst>: <e>`. Earlier moves stay in the archive (printed) |
| E-S14 | ltx-movie | W1/W2 advisories | `Warning: <text>` (stdout), continues |
| E-S15 | ltx-story-manifest | `--shots` with `--chain`/`--glob`/`--no-images`; or without `--prompts-md` | 2 (`parser.error`, 5.9 messages) |
| E-S16 | ltx-story-manifest | `--shots`: count mismatch; a panel without Image: or Motion:; a `Prompt:` field | 2, the 5.9 / existing messages. No manifest written |
| E-S17 | ltx-story-manifest | `--cast` without `--chain` or `--shots` | 2, `--cast requires --chain or --shots` |
| E-S18 | ltx-mlx-render | a shots panel fails to render | today's skip policy: the other panels render; one retry pass; exit 1 if incomplete, so ltx-movie returns 1. A rerun resumes |

---

## 8. Deploy package

- **No file is added to or removed from the package.** `PIPELINE_FILES` already ships `character_lib.py` and the four edited tools. `TEST_FILES`, `GATE_SPECS` and `EXTRA_SPECS` are unchanged. The new `tests/test_shots_mode.py` is not shipped **[spec choice]**, matching the casting tests.
- The shipped `bin/ltx-movie --shots` loads `character_lib.py` even when uncast. It is already shipped, so a target can run shots mode wherever it can run casting.
- Gates G1-G7 run unedited suites, so their counts are those of 0.2. X2 (an uncast `--dry-run`) is byte-identical (SC9).
- **Deploy test count: unchanged at 165** under `python3 -m pytest tests/test_deploy_pkg.py` and under `/usr/bin/python3 -m unittest tests.test_deploy_pkg`. No expected value changes, because no tuple changes.

---

## 9. Token budget, story-model reliability, cost

### 9.1 Token budget against the served Qwen3-VL (max_model_len 24576)

These figures use qwen-agent's own estimator (0.2):

- **Window and budget.** qwen-agent discovers the window from `/v1/models` (24576, `bin/story-server:57`). Its per-request budget is `24576 - max_tokens - 1024`.
- **`max_tokens`.** `--max-tokens` stays `_phase1_max_tokens(panels) = max(4096, 550 x panels)` **[spec choice: unchanged]**. A shots panel is about 1280-1320 characters of story text (Image: ≤170 words, Motion: ≤25, Narration: ~15, header and labels). That is about 300-350 real tokens per panel, inside the 550 per-panel allowance. The roster adds about 300.
- **Round 1 (the request that writes the file).**
  - The fixed overhead is 2937 (system 782 + tools 2155). The shots prompt for the rescue narrative with the two-member shots Cast block is 2273, for a total of 5210. A rewrite adds at most about 1423 (a 40-line block plus template), for 6633.
  - Budget at 16 panels: 24576 - 8800 - 1024 = 14752. That fits.
  - The first draft fits up to 33 panels, and the rewrite up to 30 panels (24576 - 16500 - 1024 = 7052 ≥ 6633). The rewrite fails at 31 (6502 < 6633).
  - There is no panel cap **[spec choice]**. A run above that gets qwen-agent's own `context_budget` status: story.md is never written, and Phase 1 exits 1 (G10).
- **Round 2 (after `write_file`).** The transcript then also carries the story, at about 440-460 estimated tokens per panel. That exceeds the budget from about 18 panels. qwen-agent then ends with a nonzero status **after** the file is written. bin/ltx-movie's existing path ("qwen-agent exited %d but story.md exists -- validating the file instead of failing", observed 2026-08-27) validates the file. No change is needed.
- **The real server limit** (prompt plus `max_tokens` ≤ 24576 real tokens) is looser than the estimate at 3 characters per token, so the estimate is the binding check.

### 9.2 Does the story model follow the rules?

**Not reliably, by the evidence.** That is why validation plus one rewrite is the guard, and a second failure exits 2. In the rescue run (0.2):

- it kept both cast phrases verbatim;
- it paraphrased the descriptor;
- it wrote 45-71-word, multi-sentence Motion: in every panel against a 15-35-word, one-motion rule.

The rewrite prompt lists every broken rule with its panel. Whether one rewrite brings Qwen3-VL-32B inside the 10-25-word band is unverified until L-S1, which records the first-draft violation count, whether the rewrite passed, and the rewrite's violation count (G9). On a second failure the user hand-edits story.md. Phase 1 is then skipped on rerun, and validation runs again with no rewrite.

### 9.3 Cost

- **Phase 2 adds `N - 1` stills and up to `G - 1` extra Z-Image loads.** G is the number of groups: at most 4 for two cast characters with stills LoRAs.
- **Per still (measured, 0.2).** The first still of a process takes 113-122 s at 1408x896 (load + fuse + screen). Later stills take 44-53 s at 1280x704. 1408x896 has 1.40x the pixels, so an estimated 60-75 s (unmeasured, G11).
- **Total for 20 panels and 4 groups:** 19 × 60-75 s + 3 × ~60 s load ≈ **22-27 min extra**.
  - The brief's ~12-15 min assumed 30-40 s per still. The measured per-still times on this host are about 1.5-2x that.
- **Render time per panel is unchanged.** A still-conditioned clip and a chained clip cost the same. Chain-frame extraction is skipped.
- The rewrite, when it happens, adds one more Phase 1 call. The rescue's Phase 1 (8 panels) took one qwen-agent call; a call is bounded by `_phase1_timeout(panels) = max(900, 90 x panels)` s.

---

## 10. Testing

### 10.1 Framework and fixtures

- **One new file, `tests/test_shots_mode.py`.**
  - It uses pytest with plain `assert` and **no `check()` helper**. Run it as `python3 -m pytest tests/test_shots_mode.py` from `WS`.
  - It loads scripts with `importlib.machinery.SourceFileLoader`: `bin/ltx-movie` as `ltx_movie_shots`, `bin/ltx-story-manifest` as `ltx_story_manifest_shots`, `bin/ltx-story-images` as `ltx_story_images_shots`, `bin/ltx-mlx-render` as `ltx_mlx_render_shots`.
  - No network, GPU, VLM, Z-Image or LTX.
- **`lib_dir` fixture** sets `CHARACTER_LIBRARY_DIR` to `tmp_path / "lib"`. It is a fresh copy of `tests/test_casting_pipeline.py:47-51`.
- **`make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True, strength=None)`** is a fresh copy of `test_casting_pipeline.py:54-92`, with a `descriptor` parameter added. The fixtures are:
  - kyra: `("kyra", "kyrawmn", "the woman in grey", "woman", DESC_K)`;
  - ronin: `("ronin", "roninmn", "the ronin", "man", DESC_R)`;
  - monk (S15 only): `("monk", "monkmn", "the monk", "man", DESC_M)`.
- **Descriptors:**
  - `DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"`;
  - `DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"`;
  - `DESC_M = "an old bald man with a white beard wearing a saffron robe and wooden prayer beads"`.
- **Members** are always obtained with `character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])`.
- **Fake qwen-agent:** `monkeypatch.setattr(ltx_movie.subprocess, "Popen", fake)`.
  - `fake(cmd, **kw)` records `list(cmd)`, plus `os.path.exists(story_md)` at call time.
  - It writes the next queued story text to `story_md` (an empty queue entry `None` writes nothing).
  - It returns an object with `returncode` (queued, default 0) and `communicate(timeout=None) -> ("", None)`.
  - `ltx_movie.WS` is monkeypatched to `tmp_path`, as in `tests/test_ltx_movie_iterate_flags.py:44-57`.
- **Fake stills runner:** `monkeypatch.setattr(ltx_movie, "_stream_and_tee", fake)`. It records `(list(cmd), log_path)`, creates a 1x1 PNG for each `--only` panel when the queued rc is 0, and returns the queued rc.
- **Fake Z-Image modules** for bin/ltx-story-images are a fresh copy of the P30 harness (`test_casting_pipeline.py`): fake `torch`, `z_image_skill` and `content_safety` in `sys.modules`; the fake `generate_image` records its kwargs, and `torch.Generator("cpu").manual_seed(n)` records `n`.

### 10.2 Fixture story `SHOTS_OK` (exact; valid under every rule; members kyra + ronin)

```
# Forest Rescue

A ronin saves a woman from a robber on a forest trail.

## Characters
- "the woman in grey": a young woman with long black hair pinned up with jade hairpins wearing a grey kimono
- "the ronin": a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori
- "the bearded robber": a stocky man with a black beard in a ragged brown jacket

## Panel 1 — The Trail
Image: A medium shot of the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing in the centre of a mossy cedar trail and facing right. Far behind her on the left, small in the frame, the bearded robber watches from the ferns. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The woman in grey turns her head slowly toward the ferns on her right. The camera stays static.
Narration: She senses she is not alone.

## Panel 2 — The Robber
Image: A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing left. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The bearded robber lunges forward out of the ferns with his short knife raised. The camera stays static.
Narration: A robber springs from cover.

## Panel 3 — The Ronin
Image: A medium shot of the ronin, a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori, and the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing an arm's length apart on the mossy cedar trail, the ronin on the left facing right. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The ronin offers his open hand to the woman in grey. The camera stays static.
Narration: Help arrives.
```

The Motion: word counts are 18, 18 and 15. `shots_violations(SHOTS_OK, panels, 3, [kyra, ronin]) == []` and `shots_advisories(panels, [kyra, ronin]) == []`. Variants are built from it by exact string replacement (named in each test).

### 10.3 `character_lib` (S1-S20)

| ID | Test | Assertion |
|---|---|---|
| S1 | constants | `SHOTS_CHARACTER_STRENGTH == 0.8`, `SHOTS_MOTION_MIN_WORDS == 10`, `SHOTS_MOTION_MAX_WORDS == 25`, `SHOTS_MAX_CAST_PER_PANEL == 2`, `SHOTS_REWRITE_MAX_LISTED == 40`, `SHOTS_CLOSE_SHOT_TYPES == ("medium shot", "medium close-up", "close-up", "extreme close-up")` |
| S2 | `panel_strengths` with members kyra (strength None) and ronin (strength 0.6) | `(["kyra"], m, 0.8, shots=True) == {"kyra": 0.8}`; `(["kyra"], m, 0.7, shots=True) == {"kyra": 0.7}`; `(["ronin"], m, 0.8, shots=True) == {"ronin": 0.6}`; `(["kyra", "ronin"], m, 0.8, shots=True) == {"kyra": 0.8, "ronin": 0.6}`; `(["kyra"], m, 0.8) == {"kyra": 1.0}` (continuous unchanged); `([], m, 0.8, shots=True) == {}` |
| S3 | `build_cast_block([kyra, ronin], shots=True)` | `== CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n" + '- "the ronin": ' + DESC_R + "." + "\n" + SHOTS_CAST_BLOCK_RULES`. `build_cast_block(m)` and `build_cast_block(m, shots=False)` both equal the C39 form (`CAST_BLOCK_RULES`). `SHOTS_CAST_BLOCK_RULES` has no `{`, `}` or `%`, `.count("word for word") == 2`, and contains `"at most two of these characters"`, `"a medium shot or closer"`, `"never within arm's reach"`, `"show it by cutting"`, `"an offered hand or a hand on an arm"`, `"has none of these extra rules"` |
| S4 | `find_phrases` | `("The woman in grey nods to the woman.", ["the woman", "the woman in grey"]) == ["the woman in grey", "the woman"]`; `("THE RONIN bows.", ["the ronin"]) == ["the ronin"]`; `("the ronin's blade", ["the ronin"]) == ["the ronin"]`; `("the ronin-like man", ["the ronin"]) == []`; `("the bearded robber grabs the ronin; the ronin", ["the ronin", "the bearded robber"]) == ["the bearded robber", "the ronin"]` (first-occurrence order, once each); `("", ["the ronin"]) == []` |
| S5 | `parse_character_roster` | on `SHOTS_OK`: three entries in order, with problems `[]`. Curly quotes `- “the ronin”: a man` and a `* "the ronin": a man` bullet each parse. No header gives `([], ['no "## Characters" section'])`. A line `- the ronin: a man` gives problem `'line \'- the ronin: a man\' is not - "<referring phrase>": <description>'`. A 7-word phrase gives the `normalize_phrase` message. `"The Ronin"` after `"the ronin"` gives `"phrase 'The Ronin' is listed more than once"`. Blank lines inside the section are skipped. The section ends at `## Panel 1` (a later `- "x y": z` line after the panels is not read). A header with no entries gives `['the "## Characters" section lists no characters']`. A header placed after the panels is found |
| S6 | `motion_problems` pass cases | `[]` for: each `SHOTS_OK` Motion:; `"The ronin draws his katana from its scabbard in one smooth motion. The camera stays static."`; `"The woman in grey swings the cedar branch at the robber's knife hand."` (no camera sentence); a text of exactly 10 words; a text of exactly 25 words; `"Camera holds. The ronin kneels beside the fallen branch on the trail."` (camera sentence first) |
| S7 | `motion_problems` fail cases (one each, exact list; every case text is otherwise clean: one sentence, no chain word, unless the case is about that) | 9 words → `[("S4 motion length", "Motion: is 9 words; it must be 10-25")]`. 26 words → the same with 26. `"The ronin draws his sword. The ronin strikes the bearded robber hard."` → `[("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally followed by a camera sentence")]`. `"The ronin draws his sword; he strikes the bearded robber across the arm."` → `[("S5 one action", "Motion: contains a semicolon")]`. Each of `then`, `While`, `meanwhile`, `simultaneously`, `afterwards`, `followed  by` (two spaces), `as soon as`, placed in an otherwise valid 15-word sentence → `[("S5 one action", "Motion: chains actions with '<word lowercased, single-spaced>'")]`. `"The ronin sprints in, and he draws his katana toward the robber."` → `[("S5 one action", "Motion: chains actions with ', and'")]`. `"The camera pans slowly across the empty clearing toward the cedar trees."` → `[("S5 one action", "Motion: has 0 action sentences; …")]` |
| S8 | negative controls | `[]` for: `"The ronin crosses the strengthened rope bridge above the river gorge slowly."` (`then` inside a word); `"The woman in grey kneels before the shrine and lowers her head."` (bare `and`, `before`: the known G1 false negative, pinned so that a future tightening is a deliberate change) |
| S9 | `shots_violations(SHOTS_OK, panels, 3, [kyra, ronin])` | `[]`. `shots_violations(SHOTS_OK, panels, 3, [])` is also `[]` |
| S10 | S1 | `expected_panels=4` → first item `"story: S1 panel count: expected exactly 4 panels, found 3"` |
| S11 | S2 roster presence | `SHOTS_OK` with the `## Characters` section removed: with members → contains `'story: S2 characters list: no "## Characters" section'` and two `cast phrase … is not listed` items; with `[]` members → `[]` |
| S12 | S2 cast phrase missing | roster without the `"the ronin"` line → exactly `["story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]` |
| S13 | S3 | panel 2's `Image: …` line removed → `["panel 2: S3 fields: missing/empty Image: field"]`. Panel 3 gains `Prompt: x` → `"panel 3: S3 fields: has a Prompt: field; shots mode expects Image:, Motion: and Narration:"` |
| S14 | S4/S5 numbering | panel 3's Motion: replaced with `"The ronin offers his hand then pulls the woman in grey to her feet on the trail."` → `["panel 3: S5 one action: Motion: chains actions with 'then'"]` |
| S15 | S6 | members kyra, ronin, monk; the roster gains `- "the monk": ` + `DESC_M` (directly before the bearded-robber line, so S2 stays silent); panel 3's Image: gains `" The monk, an old bald man with a white beard wearing a saffron robe and wooden prayer beads, stands behind them."` → `["panel 3: S6 cast count: the shot names 3 cast characters (kyra, monk, ronin); at most 2"]`. The same with the monk named only in Motion: (Motion: `"The monk raises his hand toward the ronin and the woman in grey."`) also gives S6, which proves the Image: ∪ Motion: union. `SHOTS_OK` (2 cast) gives no S6 |
| S16 | S7 | panel 1's Motion: replaced with `"The woman in grey pushes the bearded robber away from her with both hands."` → `["panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded robber'; show the other character's action in its own shot, then cut to the cast character's reaction"]`. Panel 1 as in `SHOTS_OK` (robber in Image: only) gives no S7. Panel 2 (extra only) gives no S7. Panel 3 (two cast) gives no S7 |
| S17 | S7 overlap | the roster gains `- "the woman": an old woman in a straw hat`, and panel 1's Motion: is `"The woman in grey bows her head to the trail shrine slowly. The camera stays static."` → no S7 (the longest phrase claims the span) |
| S18 | `shots_advisories` | on `SHOTS_OK` → `[]`. Panel 1's descriptor paraphrased by replacing the unique string `"grey kimono, standing in the centre"` with `"grey robe, standing in the centre"` (verified unique; a first-occurrence replace of the descriptor itself would hit the roster line instead) → exactly `["panel 1: Image: names 'the woman in grey' but does not repeat character kyra's Cast description word for word; that still relies on the phrase and the stills LoRA alone"]`. Panel 1's `"hairpins wearing a grey kimono, standing in the centre"` → `"hairpins   WEARING a grey kimono, standing in the centre"` (whitespace and case) → no W1. Panel 1's `"A medium shot"` → `"A wide shot"` → `["panel 1: shows cast character(s) kyra but its Image: shot type is wide shot; a shot with a cast character should be a medium shot or closer"]`. Shot type removed → `"… shot type is not stated; …"`. Panel 2 (no cast) with `"wide shot"` → no W2. Empty members → `[]` |
| S19 | `shots_rewrite_block` | `(["a", "b", "c"], 14) == SHOTS_REWRITE_TEMPLATE % ("- a\n- b\n- c", 14)`, contains `"Keep EXACTLY 14 panel sections."`. 45 violations → 40 `"- v<i>"` lines then `"- ... and 5 more"`. `SHOTS_REWRITE_TEMPLATE.count("%") == 2` |
| S20 | `character_lib.py` ast | top-level imports still exactly `{collections, datetime, json, os, re, uuid}` (C41 unchanged) |

### 10.4 `bin/ltx-movie` (S30-S53)

| ID | Test | Assertion |
|---|---|---|
| S30 | parser | `parse_args(["n", "--story-id", "x"])`: `shots is False`, `redo is None`. `--shots --redo 3,1` → `shots is True`, `redo == "3,1"`. `format_help()` contains `--shots` and `--redo`. The L1 help substrings still hold |
| S31 | `build_story_prompt("N", "sid", 14, seconds="6", shots=True)` | `== STORY_PROMPT_TEMPLATE_SHOTS.format(narrative="N", story_id="sid", panels=14, seconds="6")`. With `cast_block="CAST"`, `"\n\nCAST"` sits immediately before `"\n\nHow this movie is made:"`. The template's brace set is exactly `{story_id, narrative, seconds, panels}`, it has 1 anchor, and it contains `"sequence of separate shots joined by cuts"`, `"## Characters"`, `"10-25 words"`, `"ONE physical action"`, `"never use a semicolon"`, `"EXACTLY {panels} panel sections"` |
| S32 | non-shots identity | `build_story_prompt(…, shots=False)` equals the call without `shots`, for `no_stills` False/True and `seed_image` False/True |
| S33 | `_resolve_shots` | rc 2 with exactly the one 7.1 stderr line, and `redo_panels == []`, for: E-S3; E-S1; E-S2 (seed file exists); E-S4 for `"x"`, `"3.0"`, `""`, `","`; E-S5 for `"0"`, `"15"` with `--panels 14`, `"-1"`; E-S6; E-S7; E-S8 (no story.md). OK: `--shots --redo "3, 1,3"` with story.md present → rc 0, `redo_panels == [1, 3]`. `--shots` alone → rc 0, `[]`. No file is created under `tmp_path` by any case |
| S34 | `_resolve_casting` with `--shots --character kyra`, no story.md | rc 0, `character_strength == 0.8`, `cast_block == build_cast_block(members, shots=True)`. Without `--shots`, `cast_block` is the continuous block (P43 unchanged) |
| S35 | Phase 1, valid first draft | fake qwen-agent queue `[SHOTS_OK]`, `--shots --character kyra --character ronin --panels 3 --no-review` → rc 0. Popen called once. No `story.rejected-*` file. stdout has no `"has an Image: field, which is ignored"` |
| S36 | Phase 1, one rewrite | queue `[BAD, SHOTS_OK]`, where `BAD` = `SHOTS_OK` with panel 2's Motion: replaced by `"The bearded robber lunges then slashes."` → rc 0. Popen called twice. At the 2nd call story.md did not exist. The 2nd `cmd[-1] == first_cmd[-1] + "\n\n" + character_lib.shots_rewrite_block(viol, 3)`, where `viol == ["panel 2: S4 motion length: Motion: is 6 words; it must be 10-25", "panel 2: S5 one action: Motion: chains actions with 'then'"]`. Exactly one `story.rejected-*.md`, byte-identical to `BAD`. `story_prompt.rewrite.txt == second cmd[-1]`. `story_prompt.txt` holds the first prompt. stdout lists both violations under the `Warning:` line. All `cmd` elements except the last are equal between the two calls |
| S37 | Phase 1, second failure | queue `[BAD, BAD]` → rc 2. Popen exactly twice. stderr has `"Error: story.md still breaks the shot rules after one rewrite:"`, both `  - panel 2: …` lines, and the rejected path. story.md (the second `BAD`) is still in place |
| S38 | Phase 1 skipped, story.md pre-exists as `BAD` | rc 2. Popen never called. story.md byte-unchanged. No rejected file. stderr starts `"Error: story.md breaks the shot rules:"` and contains `"pass --force-story"` |
| S39 | rewrite agent failure | queue `[BAD, None]`, with the 2nd returncode 1 → rc 1. stderr has the existing `"Error: qwen-agent exited 1 while authoring story.md"` and `"Error: the shots rewrite failed; the rejected first draft is kept at "`. The rejected file exists |
| S40 | advisories are not fatal | queue `[SHOTS_OK with the S18 paraphrase]` → rc 0. stdout contains `"Warning: panel 1: Image: names 'the woman in grey' but does not repeat"` |
| S41 | continuous mode unaffected | no `--shots`, story.md = a 2-panel chained story (panel 1 with Image:/Motion:/Narration:, panel 2 with Motion:/Narration:) whose panel 2 Motion: is `"She draws then strikes; then he falls."` → `phase1_story` rc 0 (only `_validate_story_md` applies) |
| S42 | `_shots_stills_groups` | a 5-panel story whose Image: fields name {kyra}, {ronin}, {kyra, ronin}, {}, {kyra}, with both members having stills → `[((), [4]), (("kyra",), [1, 5]), (("ronin",), [2]), (("kyra", "ronin"), [3])]`. Uncast → `[((), [1, 2, 3, 4, 5])]`. Ronin without a stills LoRA → ronin names drop: `[((), [2, 4]), (("kyra",), [1, 3, 5])]`. A nested phrase (cast `"the woman"` without stills, and kyra `"the woman in grey"` with stills, Image: `"the woman in grey"`) → `(("kyra",), …)` (the I3 rule). Motion:-only mentions do not affect groups |
| S43 | `phase2_stills` shots | the S42 story (all stills absent), fake stills runner (rc 0 each) → rc 0. Exactly 4 runs, in S42 group order. Each `cmd` equals the non-shots Phase 2 `cmd` (built by the same args) with the `--only` value replaced by `"4"`, `"1,5"`, `"2"`, `"3"` (the S42 group lists, in that order) and `"--shots"` as the last element, after the `--cast …` and `--character-strength 0.8` flags. `log_path`s are `images/stills-group-01.log` … `-04.log`. Rerun with every still present → 0 runs, and 4 `"every still exists; skipped"` lines. With only panel 2's still absent → exactly 1 run (group `ronin`) |
| S44 | stills group failure | runner rc queue `[0, 1, 0, 2]` → rc 1. Exactly 4 runs, `--only` `"4"`, `"1,5"`, `"2"`, `"3"` (a failing group does not stop the rest). stderr equals the E-S12 text exactly: 2 of 4 groups, group 2/4 exited 1 (`stills-group-02.log`), group 4/4 exited 2 (`stills-group-04.log`). Exactly `panel_02.png` and `panel_04.png` exist. Rerun with queue `[2]` → rc 1 (not 2). 2 runs (`"1,5"`, `"3"`), 2 `"every still exists; skipped"` lines, and stderr lists only group 2/4, exited 2. A third run (rc 0) → rc 0, 1 run (`"1,5"`), empty stderr |
| S45 | one LoRA set per process, end to end | for each S43-recorded group `cmd` (S42 story; members with stills), call `story_images.main(cmd[2:])` under the fake Z-Image modules → each rc 0 (E-P16 never fires). Every `generate_image` call in a group has `loras == [(stills_path(n), 0.8) for n in group names]` (sorted by name), or no `loras` key for the `()` group |
| S46 | `phase3_manifest` shots | `subprocess.run` patched to record → the manifest `cmd` has `"--shots"` directly followed by `--image <images>/panel_01.png … --image <images>/panel_14.png` (`--panels 14`) and no `"--chain"`. The `_print_dry_run_plan` Phase 3 line is the same command |
| S47 | `_phase4_flags` | `--shots` → `--on-panel-failure skip`. Default → `stop`. `--no-stills` → `skip` (L51 unchanged) |
| S48 | `_phase_sequence` | an object with `no_stills=False`, `story_server_stop_after_story=True`, `redo_panels=[3]` → `("phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills", "phase3_manifest", "phase4_render")`. `redo_panels=[]` → no redo phase. Every L41 case is unchanged |
| S49 | `phase_redo_shots` | story dir with `images/panel_0{1,2,3}.png`, `clips/panel_0{1,2,3}.mp4` (+ `.provenance.json`) and `movie.mp4`, each with distinct bytes; `redo_panels=[2]` → rc 0. `redo/<stamp>-<pid>/images/panel_02.png`, `…/clips/panel_02.mp4`, `…/clips/panel_02.mp4.provenance.json` and `…/movie.mp4` hold the original bytes. Those source paths are gone. Panels 1 and 3 are byte- and mtime-unchanged. The total file count under the story dir is unchanged (nothing deleted). `redo_panels=[3]` with no clip for 3 moves only what exists, and prints one line per move |
| S50 | dry run, shots, new story | subprocess `bin/ltx-movie "n" --story-id <fresh> --shots --panels 4 --dry-run --no-review --character kyra --character ronin` (`CHARACTER_LIBRARY_DIR` set) → rc 0. stdout contains the shots template text (`"sequence of separate shots joined by cuts"`) and the shots Cast rules (`"at most two of these characters"`), `"Stills groups: computed from story.md after Phase 1"`, a Phase 2 `Command:` with `--only '<PANELS>'` and ending in `--shots`, the Phase 3 manifest command with `--shots` and 4 `--image`s, and `--on-panel-failure skip`. `generated/stories/<fresh>` is not created |
| S51 | dry run, existing story, `--redo 2` | `WS` patched to `tmp_path`, with the S49 tree and `SHOTS_OK` as story.md (3 panels) → `main([... "--dry-run" ...])` rc 0. stdout has `"--- Redo: panels 2 ---"`, one `"Would move …"` line per existing file, and per-group `Command:` lines. Panel 2's group is not marked skipped, and other fully-present groups are marked `"would be skipped"`. Every file is byte- and mtime-unchanged, and no `redo/` dir exists |
| S52 | non-shots byte identity | B1 (its golden holds the full rendered prompt and the Phase 2, 3 and 4 commands of an uncast dry run), B2, B3, P46 (cast dry run) and L51 pass unchanged. Additionally, for a default `parse_args(["n", "--story-id", "x"])` namespace: no `"--shots"` token in `_phase4_flags(args)`, `_render_flags(args)` or the dry-run output; `--on-panel-failure stop`; and `"--chain"` present in the Phase 3 manifest command |
| S53 | uncast non-shots run never loads `character_lib` | P49 unchanged. Additionally `main(["n", "--story-id", "x", "--dry-run", "--no-review", "--shots"])` with no cast does not load `character_lib`: the dry run needs no validation, and the grouping is uncast |

### 10.5 `bin/ltx-story-manifest` and the render (S60-S66)

All use `WS` patched to `tmp_path` and 64x64 PNGs made at runtime.

| ID | Test | Assertion |
|---|---|---|
| S60 | `--shots`, uncast, `SHOTS_OK` + 3 images | rc 0. `schema_version == 3`. Each panel has `conditioning == "still"`, `image_path ==` the abspath of its own image, `panel_text ==` its Image:, `motion_prompt ==` its Motion:. No `characters` key. No `"(chained)"` in stdout |
| S61 | `--shots --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength 0.8` on a 4-panel story: P1 Image+Motion kyra; P2 Image kyra+ronin, Motion ronin only; P3 Image kyra, Motion `"She bows her head low to the shrine on the trail."`; P4 nobody | characters `[kyra@0.8]`, `[kyra@0.8, ronin@0.8]`, `[kyra@0.8]`, `[]`. `motion_prompt`s: P1 has `the kyrawmn woman in grey`; P2 has `the roninmn ronin` and no `kyrawmn`; P3 is unchanged (no trigger). Every `panel_text` is byte-identical to S60's. stdout has `cast: panel 1: kyra@0.8` |
| S62 | strength overrides | `--character-strength 0.6` → P1 `[kyra@0.6]`. Ronin `character.json` `strength 0.5` → P2 `[kyra@0.6, ronin@0.5]`. No `--character-strength` → 0.8 (the `SHOTS_CHARACTER_STRENGTH` default). The same story with `--chain` (and one image) still gives a lone 1.0 (continuous unchanged) |
| S63 | errors | each exits 2 and writes no manifest: `--shots --chain`; `--shots --no-images`; `--shots --glob 'panel_*.png'` (`SystemExit` 2, the E-S15 message); `--shots` without `--prompts-md`; 2 images for 3 panels (`"Error: prompts.md has 3 panels but 2 images were selected"`); panel 2 without Image: (`"Error: --shots requires every panel to have a non-empty Image: field; panel 2 has none"`); panel 3 without Motion:; panel 1 with `Prompt:` (`"Error: --shots does not accept Prompt: fields; panel 1 has one"`) |
| S64 | `--cast` without `--chain`/`--shots` | `SystemExit` 2, stderr contains `"--cast requires --chain or --shots"` (and therefore P23's substring) |
| S65 | E-P14, shots | cast phrase in no Image: or Motion: → stdout `"WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Image: or Motion: text; that character gets no LoRA"`. The `--chain` wording is unchanged (P22) |
| S66 | render accepts the shots manifest | the S61 manifest through `render.load_manifest` → ok. `build_units` → every unit `conditioning == "still"`, `chain_source is None`, `image_path ==` that panel's image. The render harness (fresh copy of the P9 `_Harness`) with panel 2's `generate_video` raising `Ltx2MlxError` and `--on-panel-failure skip --retry-failed 0` → panels 1, 3 and 4 render, and the summary has panel 2 `error` (no `chain_broken` stop) |

### 10.6 `bin/ltx-story-images` (S70-S72)

| ID | Test | Assertion |
|---|---|---|
| S70 | `--cast "the woman in grey=kyra" --only 1 --shots` (kyra has stills) | the `generate_image` call has `loras == [(stills, 0.8)]`, and `images.json` panel `loras[0]["strength"] == 0.8`. The same without `--shots` → 1.0 (P30 unchanged) |
| S71 | pinned seed | ungrounded story (no Style:), `--only 2,3 --seed 0 --shots` → `manual_seed` called with `0`, `0`. Without `--shots` → `2`, `3` |
| S72 | `--shots` without `--cast` | rc 0. No `loras` kwarg. `images.json` has no `loras` key. Pinned seeds |

### 10.7 Regression, mutation

**R1 (SC9).**

- The main thread runs every 0.2 suite by the stated invocation. Counts the implementer reports are not accepted.
- Results must equal 0.2 exactly: `OK 344/344`, `OK 101/101`, `OK 443/443`, `OK 146/146`, `OK 32/32`, `OK 77/77`, `RESULT: ok`, `178 passed`, `13 passed` (z_image cache), `13 passed` (iterate flags), `17 passed` (pipeline_log).
- None of those files appears in `git diff --stat`.
- `tests/test_shots_mode.py` passes in full.
- **R2 (SC10):** `165 passed` and `Ran 165 tests … OK`.

**Mutation checks.** Apply each mutation alone, run the named file, confirm at least one named test fails, revert. "R1:x" names an existing-suite pin.

| Mutation | Must fail |
|---|---|
| `panel_strengths` ignores `shots` (lone → 1.0) | S2, S61, S70 |
| shots strength ignores the `character.json` override | S2, S62 |
| `SHOTS_CHARACTER_STRENGTH = 1.0` | S1, S34, S62 |
| `build_cast_block` ignores `shots` | S3, S34 |
| `find_phrases` sorts shortest first | S4, S17 |
| `find_phrases` overlap check removed | S4, S17 |
| `find_phrases` returns sorted phrases, not first-occurrence order | S4 |
| roster entry regex accepts unquoted phrases | S5 |
| roster duplicate check removed | S5 |
| roster section ends at a blank line instead of the next `#` line | S5 |
| roster parse starts at the first line containing "Characters" anywhere | S5 (header-after-panels case reads a panel line) |
| S4 bounds `<` instead of `<=` (either end) | S6 (10- and 25-word cases) |
| S4 bounds widened to 9-26 | S7 |
| camera sentence counted as an action sentence | S6, S43's fixture via S9 |
| sentence count check `>= 1` | S7 |
| semicolon check removed | S7 |
| `_CHAIN_WORD_RE` without `\b` | S8 (`strengthened`) |
| `, and` check removed | S7 |
| chain-word list drops `while` | S7 |
| S2 enforced without members | S11, S9 |
| S2 skipped with members | S11, S12 |
| S6 counts Motion: only | S15 (Image: case) |
| S6 limit 3 | S15 |
| S7 checks Image: instead of Motion: | S16 (`SHOTS_OK` panel 1 would fail) |
| S7 ignores extras (cast-only matching) | S16 |
| advisories appended to violations | S40, S9 |
| W1 compares case/whitespace-sensitively | S18 |
| W2 accepts `wide shot` | S18 |
| rewrite also runs for a pre-existing story.md | S38 |
| a second rewrite is allowed | S37 |
| rejected draft overwritten or deleted instead of moved | S36 |
| rewrite prompt omits the violations | S36 |
| rewrite rebuilds `cmd` instead of reusing it (a different flag set) | S36, R1:L19a |
| `_run_story_agent` drops the `--danger-auto-approve` print | R1 (iterate-flags C1 tests) |
| `len(cmd[-1])` left as `len(prompt)` | S36 (NameError) |
| shots branch placed after `_validate_story_md` | S35 (chain-image warning text), S36 |
| groups computed from Motion: instead of Image: | S42 |
| groups insert triggers for members without stills | S42, S45 |
| groups not sorted | S43 |
| `--only` not replaced | S43 |
| `--shots` not appended to group commands | S43, S45 (strength 1.0) |
| a fully rendered group is still run | S43 |
| a failing group stops Phase 2 (`return 1` inside the loop) | S44 |
| Phase 3 shots passes `--chain` | S46 |
| manifest shots panels 2+ `chain` | S60, S66 |
| manifest shots names from Motion: only | S61 (panel 3) |
| manifest inserts triggers into `panel_text` | S61 |
| manifest shots writes schema 2 | S60, S66 |
| `_phase4_flags` keeps `stop` for shots | S47 |
| redo deletes instead of moving | S49 |
| redo moves other panels' files | S49 |
| redo phase placed after `phase2_stills` | S48 |
| redo phase inserted when `redo_panels == []` | S48, R1:L41 |
| `--redo` accepted without `--shots` | S33 |
| `--redo 0` accepted | S33 |
| dry-run `--redo` moves files | S51 |
| bin/ltx-story-images `--shots` does not pin the seed | S71 |
| seed pinned always (`grounded = True`) | S71 (no-`--shots` case), R1:I-suite |
| `build_story_prompt` ignores `shots` | S31 |
| shots template used without `--shots` | S32, B1 |
| ltx-movie gains `import re` | R1:L7j |
| shots Phase 2 builds its own `--lora` line | R1:L1z5 |

### 10.8 Live gates (main thread or user, on hardware, one at a time, no concurrent renders)

Before each gate, record `bin/story-server status` and `psutil.virtual_memory().available / 2**30`. Phase 1 needs the story server `SERVING vision` (qwen38-6bit). Phase 1b stops it.

**L-S1. The rescue as a shots story.**

```
bin/ltx-movie "Deep in a cedar forest, three robbers corner the Shogun's daughter, the woman in grey: a stocky bearded robber in a ragged brown jacket with a short knife, a tall gaunt shaved-head robber in a patched blue tunic with a wooden club, and a young wiry spear robber bare-chested under a straw cape with a bamboo spear. They grab at her jade hairpins and kimono; she fights back with a fallen cedar branch, striking the club robber's forearm, until the spear robber drives the butt of his spear into her ribs and she drops to her knees. The ronin sprints in along the trail, shoulder-charges the bearded robber off her, draws his katana and knocks the spear aside, drives the pommel into the spear robber's jaw, and slips the club robber's swing with a cut across his forearm. The three robbers scramble up and flee into the ferns. The ronin sheathes his sword and helps her to her feet. Relatively little dialogue; focus on realistic, physically grounded action." --story-id ronin-rescue-shots-ls1 --shots --panels 14 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --character kyra --character ronin
bin/judge-clips --story-id ronin-rescue-shots-ls1
```

The narrative is the rescue's verbatim (`ronin-rescue-cast-20261006/iterate-story.log:28`). `ronin-rescue-shots-ls1` must not exist beforehand; if it does, use `-ls1b`. Pass conditions, all required:

1. Exit 0. 14 clips. `story.md` passes `shots_violations`. Record whether a `story.rejected-*.md` exists, its violation count, and the rewrite's count (9.2).
2. `manifest.json`:
   - `schema_version 3`;
   - every panel `conditioning "still"` with its own `images/panel_NN.png`;
   - every `characters` strength 0.8;
   - at most 2 characters per panel;
   - for every panel, the `characters` names equal `sorted(set(cast_text(Image:)) | set(cast_text(Motion:)))`, computed in a REPL from story.md.
3. Every `clips/panel_NN.mp4.provenance.json` has `conditioning "still"` and LoRA strengths 0.8. The `images/stills-group-KK.log` files number at most 4, and each shows `fused <n> LoRA adapter(s)` equal to its group size (or no fuse line for the `()` group).
4. **Eyeball (decisive):**
   - in every shot whose `characters` include kyra, her still and her clip's first, middle and last frames show her trained identity (face, three jade hairpins, pale grey kimono with silver obi), with no male or ronin traits;
   - in every ronin shot, topknot, scarred brow and indigo haori, with no female, kimono or hairpin traits;
   - **in every extras-only shot, the robbers stay robbers**: no kimono, no topknot or samurai restyle, no second woman in grey. These are the specific `ronin-rescue-cast-20261006` failures;
   - no cast character vanishes from a shot whose Image: places them (the solo07 0.7 failure).
5. Record, side by side with `ronin-rescue-cast-20261006` (means: motion_fidelity 4.25, physical_realism 4.625, temporal_stability 3.5, narrative_clarity 3) and `-solo07` (4.125 / 5.125 / 3.875 / 3):
   - this run's per-clip and mean motion_fidelity, physical_realism and temporal_stability, and narrative_clarity;
   - `seam_continuity` is recorded but not compared (cuts by design, G4).
   - **KPI K1:** mean motion_fidelity > 4.25. K1 does not gate. If it fails, record "single-action hypothesis not confirmed" for the user.
6. Record the Phase 2 wall-clock (from `stills-group-*.log` timings) against the 9.3 estimate.

**L-S2. `--redo` one panel.** Run after L-S1, on the same story.

1. Record sha256 of every `images/panel_NN.png` and `clips/panel_NN.mp4`.
2. Choose `K` = the lowest panel whose `characters` has exactly one entry. In story.md, change that panel's shot-type words in `Image:` (`medium shot` ↔ `medium close-up`) so that its still must change. Leave everything else as it is. Record the edit.
3. Run the L-S1 `bin/ltx-movie` command with `--redo K` appended.

Pass conditions:

- exit 0;
- `redo/<stamp>-<pid>/` holds the old `images/panel_KK.png`, `clips/panel_KK.mp4`, its provenance and `movie.mp4`, all byte-identical to the step-1 hashes;
- the new `panel_KK.png` and `panel_KK.mp4` hashes differ from the old ones;
- **every other `panel_NN.png` and `panel_NN.mp4` sha256 is unchanged**;
- `movie.log` shows `reusing` for every other panel;
- exactly one stills group ran: the others print `every still exists; skipped`.

---

## 11. Task decomposition hint (for the planner)

1. **Baseline.** Rerun R1 (and record it), with no code changes.
2. `character_lib.py` additions (Section 3) + S1-S20. Run `tests/test_character_lib.py` (46) and the casting pytest set (178).
3. `bin/ltx-story-manifest --shots` (5.9) + S60-S65. Run the manifest chain suite (`OK 32/32`) and B2.
4. `bin/ltx-story-images --shots` (5.10) + S70-S72. Run the direct `OK 101/101`.
5. Render: no code. Test S66.
6. `bin/ltx-movie`: arguments, `_resolve_shots`, the template, `build_story_prompt`, and the `_resolve_casting` edits (5.1-5.3) + S30-S34.
7. `bin/ltx-movie`: the `_run_story_agent` extraction **alone first**. Run the offline suite direct (`OK 344/344`) and the iterate flags (13) as a refactor checkpoint. Then `_phase1_shots_finish` + S35-S41.
8. `bin/ltx-movie`: Phase 2 groups, the redo phase, Phase 3/4, the dry run (5.5-5.8) + S42-S53.
9. R1, R2, B, and the full 10.7 mutation table, run by the main thread. Then a design-reviewer (Opus high) code review.
10. Live gates L-S1, then L-S2.

Tasks 2-5 can run in any order after 1. Tasks 6-8 depend on 2 and run in order.

---

## 12. Known gaps

- **G1. Motion: heuristics are lexical.**
  - False negatives: compounds joined by a bare " and " ("kneels before the shrine and lowers her head"), participles ("drawing his sword, he lunges"), and "that"-clauses ("draws his katana in one rising stroke that knocks aside the spear"). S8 pins one of them.
  - False positives: "then"/"while" in non-sequencing senses ("for a while").
  - The second line of defense is the prompt and the rewrite list.
- **G2. Semantic rules are unvalidated** (framing, extras small in the background, cast-cast light contact, continuity cues). W2 covers only the stated shot type. L-S1's eyeball is the check.
- **G3. Descriptor repetition is advisory (W1)**, by evidence (0.2).
- **G4. Judges assume continuous mode.** `seam_continuity` scores "one continuous take", which penalizes cuts that are correct here. Judges are out of scope.
- **G5. `images/images.json` reflects only the last stills group that ran.** Each `bin/ltx-story-images` run overwrites it. The stills themselves, the group logs and the manifest are complete. No current tool reads `images.json` except as a pointer in an error message.
- **G6. `--redo` is deterministic.** It uses the pinned stills seed and the fixed render seed `--seed + i`. An unedited redo reproduces the same take; a different take needs a text edit of that panel.
- **G7. Bleed onto background extras in cast shots at 0.8 is unmeasured.** The mitigation is composition (small, far back). L-S1 checks it by eye.
- **G8. Lone 0.8 is untested.** 1.0 bled and 0.7 lost the ronin (0.2). L-S1 is the first lone-0.8 evidence.
- **G9. Story-model compliance with the 10-25-word band and the roster is unverified.** If Qwen3-VL-32B fails twice routinely, shots runs will need hand edits. L-S1 records the rates.
- **G10. Token budget.** About 31+ panels exceeds the rewrite's round-1 budget, and about 34+ the first draft's. There is no cap; qwen-agent's `context_budget` status surfaces it as a Phase 1 exit 1. Rounds after `write_file` overflow from about 18 panels, harmlessly (9.1).
- **G11. 1408x896 per-still time is extrapolated** from 1280x704 measurements (9.3).
- **G12. `--seed-image` is not supported in shots mode** (E-S2).
- **G13. Pre-existing display quirk, not fixed.** Phase 1's `Running (timeout …)` line prints `--user-prompt --user-prompt '<N chars>'`, because `cmd[:-1]` already ends with `--user-prompt` (visible in `ronin-rescue-cast-20261006/iterate-story.log:33`). `_run_story_agent` moves this line verbatim. Mentioned here per the "don't fix unrelated code" rule.
- **G14. bin/ltx-story-images `--shots --dry-run` reuses the grounded-mode labels.** It prints `style: ` (empty), the `seed: pinned …` line, and `| +style |` on each panel line, because `grounded` also carries the pinned seed. This is cosmetic, and bin/ltx-movie never calls that dry run.
- **G15. The "≤2 named characters" reading is "≤2 cast characters"** (2.2). A crowded extras-only shot is legal.
- **G16. An Image:-only cast character's video LoRA loads without a trigger token** in the render prompt, because the trigger is inserted only where the phrase occurs in Motion:. The conditioning still carries the identity.
- **G17. S7 depends on the roster.** An extra the model named in Motion: but left out of `## Characters` escapes S7.

---

## 13. Review Focus

These are the five failure modes most likely to matter that the offline tests cannot fully cover:

1. **Rewrite flow on the real host.**
   - Confirm that the moved-aside draft makes the rewrite's `write_file` a NEW file (no approval prompt under `--no-review`).
   - Confirm that the reused `cmd` carries `--danger-auto-approve` only when it did before.
   - Confirm that a qwen-agent nonzero exit after writing still validates the file.
   - A wrong call here hangs an unattended run or loses the first draft.
2. **Group equality with bin/ltx-story-images' own plan.** `_shots_stills_groups` must compute exactly the names that bin/ltx-story-images' `cast_text(_compose_prompt(Image:, Style:), members, insert=stills members)` computes, including nested phrases and members without stills. Otherwise E-P16 fires mid-Phase 2, after paid stills. S45 runs them together, but only on fixtures.
3. **`--redo` and provenance.**
   - Moving, not deleting.
   - Only the named panels.
   - `movie.mp4` moved, so Phase 4 needs no `--force`.
   - Every other clip reused, because its provenance (image bytes, prompt, seed, LoRAs) is unchanged.
   - Confirm nothing else in Phase 3 changes the other panels' render prompts. For example, a trigger inserted differently would change `prompt_sha256` and cascade re-renders.
4. **Byte identity without `--shots`.** Every edit is guarded by `shots` or `redo_panels`. Review each changed line of the four files against the pins in 0.2 and against B1-B3, especially the `_run_story_agent` move (`len(cmd[-1])`) and the manifest's E-P14 wording.
5. **Heuristic strictness against the story model.** The 10-25-word band is far below what the model wrote in the rescue (45-71). Review whether the rewrite text (3.9) gives the model enough guidance to comply in one pass. If L-S1 shows routine double failures, the follow-up is a prompt change, not a looser validator. That is a user decision.

---

## 14. Open questions

None. Every decision is made above. The [spec choice] and [interpretation] markers show where this spec chose; L-S1 and L-S2 are the evidence that confirms or overturns them.
