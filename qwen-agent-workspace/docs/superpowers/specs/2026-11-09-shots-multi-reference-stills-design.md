# Shots multi-reference stills: two-character panels as one Qwen edit with both characters' reference stills (a test option)

Date: 2026-11-09

Status: design spec and implementation plan in one document. Problem report (user): in shots mode, a still that shows two library characters is rendered by Z-Image with BOTH characters' stills LoRAs loaded at once, and the two people blend. Recorded on macstudio and copied to this Mac at `~/test_runs/stories/the_fight4`: panels 7-9 (the haori changes colour; the ogre wears the ronin's clothes). `~/test_runs/stories/the_fight7` was clean only because the troll has no stills LoRA, so only one LoRA loaded. **The user's request:** add the Qwen-edit multi-reference option, with each character's reference still as an input image, "for testing if the newer image model can stack references". It is a TEST OPTION: opt-in, and the default behaviour stays byte-identical. Choices this spec makes beyond the controller's decisions are marked **[spec choice]**. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/mr-wt`, branch `shots-multiref`, off `f1a0737` (the merge of PR #14, seeded-no-identity). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `f1a0737`. At `f1a0737` every `PIPELINE_FILES` member is byte-identical to `c33919221ea8ae8fd7811c74e587c2cbccafc4be`, the current `test_mut26` BASELINE (checked with `git diff --quiet`).

Builds on **[QE]** `docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md`, **[SE]** `2026-11-05-compose-shots-seed-edit-design.md`, **[SI]** `2026-11-07-seeded-no-identity-sentence-design.md`, **[SHOTS]** `2026-10-06-shots-mode-design.md` and **[CL]** `2026-10-05-character-library-design.md`. Every requirement of those specs stays in force except where Section 11 names it as amended.

Requirement IDs are **CR1-CR16**, tests **CRT1-CRT18**, KPIs **CRK1-CRK9**, live checks **L1, L1b, L2-L5**. At `f1a0737`, `git grep -nE "\bCR[0-9]+\b|\bCRT[0-9]+\b|\bCRK[0-9]+\b"` finds nothing.

Terms (as [QE]): a **registry model** is one `movie_ui_seedgen.QWEN_MODELS` entry. A **selection** is a registry model ID plus `[{"id", "scale"}]`. A **cast-reference panel** is a shots panel whose `Image:` text, joined with the story's `Style:` text, names exactly two cast library characters (`--character`/`--cast`) by `character_lib.cast_text`. A **reference picture** is the dataset still of a cast member that this spec feeds to the edit model (CR6). A **two-shot** is a panel that shows two cast characters.

---

## 0. Scope

### 0.1 What happens today (verified)

- `phase2_stills` (`bin/ltx-movie:2118-2158`) builds one `bin/ltx-story-images` command and, in shots mode, calls `_phase2_shots` (`:2144-2145`, `:2205-2241`). That function groups the panels by the set of cast stills LoRAs that `_shots_stills_groups` (`:2165-2193`) finds in each `Image:` text, and runs `bin/ltx-story-images` once per group (z_image_skill holds one LoRA set per process).
- **the_fight4** (`~/test_runs/stories/the_fight4/iterate-story.log`, flags at line 111: `--shots --character ogre --character ronin --location cyberpunk-city --video-width 1024 --video-height 576 --panels 9 --speech-only --no-auto-lora`): `stills group 3/3 (ogre, ronin, location cyberpunk-city; panels 7,8,9)`, and `images/stills-group-03.log` loads three LoRAs into one Z-Image process: `cyberpunk-city` stills (0.8), `ogre` stills (0.8) and `ronin` stills (0.8). Those are the blended panels.
- **the_fight7** (flags: `--character ronin --character troll`, otherwise the same): the troll has no stills LoRA (`WARNING: character troll has no stills LoRA (not trained)`), so its two-shots (panels 2, 8, 9) loaded only the ronin's LoRA.
- `character_lib.cast_text` over the recorded `story.md` files (run on this Mac with stand-in CastMembers): the_fight4 panels 7, 8 and 9 name `ogre` and `ronin`, and the_fight7 panels 2, 8 and 9 name `ronin` and `troll`. Every other panel names exactly one. Panel 7 of the_fight4 names both even though its plan beat cast is `["c2"]`, because its `Image:` says the green ogre is "partially visible on the right edge of the frame".

### 0.2 The controller's decisions (binding; verbatim, then what this spec adds)

1. **v1 scope:** shots mode WITHOUT `--seed-image` only. A panel is a 'multi-reference panel' when its `Image:` text references 2 library (pinned, with a reference still on disk) cast characters. Those panels render as a Qwen edit job with `sources=[ref still of cast member A, ref still of cast member B]` in a fixed order (order of the beat cast / plan cast ids), output at the stills size, prompt = a fixed prefix that names Picture 1 and Picture 2 by their referring phrases, says each person keeps their own face, hair, skin tone, build and clothing from their picture, then the panel's `Image:` text with the pasted identity sentences and per-character LoRA trigger words handled by a clear ruling. All other panels (0 or 1 library character) keep the existing Z-Image path with its stills LoRAs unchanged. Seeded shots (seed edit) unchanged and out of scope (follow-up: seed + both refs).
2. **Opt-in flag** on `bin/ltx-movie`: `--cast-refs-model ID` (a Qwen edit registry id, same registry/validation/LoRA selection machinery as `--seed-edit-model`; reuse its selection checks; refuse `as-is`, refuse `qwen2511-q4`, refuse without `--shots`, refuse with `--seed-image`, refuse with `--no-stills`; with fewer than 2 pinned library characters it is a no-op note). Absent means byte-identical behaviour. Expose it in movie-ui Compose only if that is small and in the existing style; otherwise CLI-only for v1, with the UI listed as a follow-up.
3. **Record** per panel in a new JSON record like `seed_edits.json` (`cast_ref_edits.json`) with source sha256s, order, prompt, seed, model and LoRAs, so reruns reuse unchanged panels and `--redo` works; mirror SE12.
4. **Z-Image character stills LoRAs are NOT applied to multi-reference panels** (Qwen edit cannot take them); print a note once, like `SHOTS_SEED_LORA_NOTE`. Video LoRAs unchanged.
5. **Failure:** a blocked or failed multi-reference panel fails the phase after the batch, with no fallback to Z-Image (as seeded shots), so the test is clean.
6. **Qwen edit job schema:** add `sources` (list, 1..N) beside `source`; single-image callers byte-identical. The mflux child and the diffusers child read the list.
7. **Memory and timeouts:** state the expected cost, raise the per-job timeout for multi-image jobs by a stated factor, no change for single-image jobs.
8. **qwen2511-q4 is refused in v1** with an `Error:` line naming why: a silent single-image fallback would invalidate the test. The tokenizer patch is a follow-up.

**What this spec adds** (each justified in Section 1): the reference picture rule (CR6: the kept medium-shot dataset still `char_09`, else the dataset reference), the left/right position sentence (CR8), `--cast-refs-lora` (CR7), the rulings on identity sentences and trigger words (CR8), the timeout factor 6 (CR2), CLI-only (Section 1 item 9), the order rule "cast order = plan cast ids" (CR9), the errors for 3+ characters in one panel and for identical reference bytes (CR4, CR9), Z-Image first then the Qwen batch (CR10), the `NEW_PY` ruling (CR15), and the live-check casts (Section 8).

### 0.3 Feasibility (from the investigator; marked verified or inferred)

| Model | Multi-image | Evidence | Status |
|---|---|---|---|
| `qwen21-q4`/`q8`/`bf16` (Qwen-Image-2.1, mflux `QwenImage21Edit.generate_image(image_paths: list)`) | yes, `MAX_REFERENCES = 10` | upstream mflux 0.24.0 source; the prompt is auto-prefixed with `<image1>`..`<imageN>` tags; each reference is resized to about 1024² area, so about +4096 image tokens per reference whatever the output size | verified (source read); behaviour on our prompts inferred |
| `qwen2511-bf16` (diffusers `QwenImageEditPlusPipeline`, `image=[...]`) | yes | diffusers source prefixes `Picture {i}:` per image; our child already passes a one-item list (`character_dataset.py:1936`) | verified (source read); diffusers is NOT installed on this Mac, so no local run |
| `qwen2511-q4` (mflux `QwenImageEdit`) | **no (silently uses image 1 only)** | image side takes a list (one latent per image, `qwen_edit_util.py:25-56`) but the edit tokenizer is built with `use_picture_prefix=False` (`qwen_initializer.py:63`), so only image 1's tokens are inserted (`qwen_encoder.py:71-80`, `qwen_vision_language_processor.py:56-67`) | verified (source read); the patch (`use_picture_prefix=True` when more than one image) is inferred and untested, so refused (decision 8) |
| Model cards | 2509: "trained via image concatenation", best with 1-3 input images; 2511: fusion of two separate person images; both place subjects by position ("the magician bear is on the left, the alchemist bear on the right"), not by index | | verified (cards read); that naming "Picture 1/Picture 2" works follows the diffusers template (inferred) |

### 0.4 Grounding (verified at `f1a0737`)

**`bin/ltx-movie` (pinned).**
- Top-level imports: `argparse`, `glob`, `importlib.machinery`, `json`, `os`, `shlex`, `subprocess`, `sys`, `threading`, `time`, plus `pipeline_log` (`:119-132`). **No top-level `import re` is allowed:** `tests/test_ltx_movie_offline.py:432-434` (check L7j) asserts `"\nimport re\n" not in text`. CR8 imports `re` inside the one function that uses it, as `_sha256_file` imports `hashlib` (`:2377`).
- Module docstring ends with the Seed edit paragraph (`:113-116`). `SHOTS_SEED_LORA_NOTE` `:151-152`. Parser: `--seed-edit-model` `:333-340`, `--seed-edit-lora` `:341-344`, `--shots` `:422-431`, `--redo` `:432-436`.
- `_character_lib` `:841-845`; `_qwen_edit` `:857-860`; `_resolve_casting` `:903-959` (sets `args.cast_members` in `--character` then `--cast` order); `_resolve_seed_edit` `:1012-1051`; `_resolve_shots` `:1260-1316` (`--shots --no-stills` refused at `:1269-1272`).
- `_still_size` (2W × 2H) `:2109-2115`; `phase2_stills` `:2118-2158` (shots dispatch `:2144-2145`); `_panel_list` `:2161-2162`; `_shots_stills_groups` `:2165-2193`; `_shots_missing_stills` `:2196-2202`; `_phase2_shots` `:2205-2241`.
- Shots seed edits: `_write_seed_edit_record` `:2289-2294`; `_sha256_file` `:2375-2382`; `_shots_seed_entries` `:2399-2411`; `_write_shots_seed_record` `:2414-2418`; `_shots_seed_plan` `:2421-2454`; `_shots_seed_lora_note` `:2457-2465`; `_phase2_shots_seed` `:2468-2578`; `_redo_moves` `:2581`; `phase_redo_shots` `:2598-2620`.
- `_stream_and_tee` `:2733`; dry run: `_print_shots_stills_plan` `:2874-2894`, `_print_shots_seed_plan` `:2897-2921`, `_print_dry_run_plan` `:2924-3097` (shots stills dispatch `:3051-3052`); `_phase_sequence` `:3104-3125`; `main` `:3128-3247` (`_resolve_seed_edit` call `:3201-3203`).
- The render review gate is `input("Review the plan and the estimated render time above. Enter to render, ...")` in `phase3_manifest` (`:2683`), after Phase 2 and before Phase 4.

**`qwen_edit.py` (unpinned).** `MODEL_IDS` `:42`; `CHILD_TIMEOUT_S = 3600`, `JOB_TIMEOUT_S = 600` `:47-48`; `child_timeout` `:411-412`; `run_jobs` `:456-557`. The diffusers branch builds one item per job and adds `"image"` only when the job's source differs from job 1's (`:472-485`). The mflux branch writes `jobs: [{n, seed, prompt, source, output_path}]` (`:504-512`). The timeout is `child_timeout(len(jobs))` (`:540`). Callers of `run_jobs`: `bin/ltx-movie:2340` (Phase 1c), `:2552` (shots seed), `bin/seed-edit:429`, `character_dataset.py:1881` (`_run_registry_edit`). None sets `"sources"`.

**`seed_edit_mflux_child.py` (unpinned).** `image_paths: [source]` at `:92-93`; the peak-memory line `seed-edit-child: mlx peak memory %.2f GiB` at `:103`, printed once per job.

**`character_dataset.py` (pinned).**
- `WIDTH, HEIGHT = 1024, 640` `:65`.
- `VARIANTS` `:76-101`. Still n is `VARIANTS[n-1]`, and **n = 9 is `("medium shot", "standing with arms relaxed", "a studio with a plain grey backdrop")` at `:86`**. Both build modes number their stills from `VARIANTS`: `edit_plan` for seed-image characters (`:825-833`) and `_dataset_plan` for descriptor characters (`:884-909`; the opt-in two-source mode numbers differently, and its "medium shot, standing with arms relaxed" anchor is n = 17, `:873`).
- `EDIT_PROMPT` `:171-176` names the shot, the pose and the setting.
- `seed_still` `:702-718`: char_00 is the seed cropped to 1024×640 around the face box, with the face centre 40 % down. It is **not a face-only crop**, but for a portrait seed it keeps only a head-and-upper-body band.
- `_build_dataset` `:961-`: char_00 written `:977`; `ref_n = 0 if seed_mode else 1` `:1024`; `dataset.reference` recorded `:1081`; `dataset/manifest.json` items carry `n`, `gen_prompt`, `kept` (`:1034-1075`).
- `child_qwenedit` `:1908-1952` caches sources by path and calls `pipe(image=[source], ...)` (`:1927-1936`).

**`character_lib.py` (pinned, untouched).**
- `CastMember` `:257-259` has no image path. `character_dir(name)` `:266-267` is `library_dir()/name`, honouring `CHARACTER_LIBRARY_DIR`. `dataset.reference` must be `char_00` or `char_01` (`:446-449`).
- Absolute paths inside character.json can name another user's home: macstudio records `/Users/ailab1/...` (the_fight4 logs) and this Mac `/Users/reubenpatterson/...`. So CR6 derives paths from the character directory.
- `resolve_cast` `:591-630` refuses a character cast twice.
- `_phrase_regex` `:633-642`. `cast_text` `:649-702` returns `(text, sorted names found)`.

**`story_engine.py` (pinned, untouched).** `MAX_CAST = {"shots": 2}` (`:83`) is a per-beat plan rule. Plan cast ids `c1..cN` are assigned in `ctx.members` order (`--character` order, `:1309-1311`), so "plan cast id order" equals `args.cast_members` order. The `shots_image` key line (`:2968-2974`) asks the writer for "where each character stands and which way they face, using fixed left and right screen direction".

**Reference stills seen on this Mac** (the dev-Mac library copy `generated/characters/ronin`, descriptor-built, read-only): char_01 (the reference) is a head-and-shoulders close-up, with the haori collar visible and no hakama. char_09 is the medium shot, standing, with the indigo haori and dark hakama visible. Its manifest item 9 is `kept: true` with `gen_prompt` "Medium shot of a lean man ... standing with arms relaxed, in a studio with a plain grey backdrop. ...".

**Tests.**
- `tests/test_movie_ui_builder.py`: `NEW_PY` `:213-221`; `PIPELINE_FILES` `:223-228` (23 paths, including `bin/ltx-movie` and `character_dataset.py`); `test_mut26` `:272-302`, with its comment chain ending at `:291` and `BASELINE = "c33919221ea8ae8fd7811c74e587c2cbccafc4be"` at `:293`.
- `tests/test_qwen_edit.py` QET3 (`:164-167`) pins `child_timeout` and the constants (unchanged here). QET4 (`:172-205`) pins the exact mflux spec of single-image jobs (unchanged here).
- `tests/test_seed_edit_tool.py` SQT8 (`:1375-1423`) pins `image_paths: [spec["source"]]` (unchanged).
- `tests/test_location_dataset.py` LD18 (`:108-148`) pins `child_qwenedit`'s per-job image and the open-once cache (unchanged).
- `tests/test_qwen_edit.py` QET11 (`:385-405`) pins `qwen_edit.py`'s import list (unchanged here) and the exact tail of `NEW_PY` (`:402-405`), which is why CR15 leaves `NEW_PY` alone.

### 0.5 Deliverables

| # | File | Pinned | Change |
|---|---|---|---|
| D1 | `qwen_edit.py` | no | refusal table, `jobs_timeout`, `sources` in both spec shapes, the guard (CR1-CR3; edits Q1-Q8) |
| D2 | `seed_edit_mflux_child.py` | no | `image_paths` from `sources` (CR3; C1-C2) |
| D3 | `character_dataset.py` | **yes** | `child_qwenedit` reads a job's `images` list (CR3; D1-D2) |
| D4 | `bin/ltx-movie` | **yes** | flags, resolver, reference picture, prompt, plan, Phase 2 split, record, dry run, help (CR4-CR13; M1-M15) |
| D5 | `tests/test_qwen_edit_cast_refs.py` | — | new, CRT1-CRT6 |
| D6 | `tests/test_ltx_movie_cast_refs.py` | — | new, CRT7-CRT18 |
| D7 | `tests/test_movie_ui_builder.py` | — | only `test_mut26`'s BASELINE, in its own test-only commit (CR16); `NEW_PY` is NOT extended (CR15) |

Untouched: `character_lib.py`, `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/qwen-agent`, `content_safety.py`, `movie_ui_*.py`, `static/movie-ui/*`, `ltx_image_fit.py`, `movie_ui_seedgen.py` (the registry), every other test.

### 0.6 Out of scope

- Seeded shots (`--seed-image`), chained mode, `--no-stills` (refused, CR4).
- Patching mflux for `qwen2511-q4` multi-image (follow-up F1).
- A movie-ui control (follow-up F3; Section 1 item 9).
- Panels that name three or more cast characters (an error, CR9), and group shots.
- A Qwen edit for single-character panels.
- Changing the Z-Image path, its existence-only reuse, or any stills LoRA rule for non-cast-reference panels.
- Running a real model, server, render or download in tests; any agent access to macstudio.

### 0.7 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| CRK1 | The full suite has no failure beyond the baseline recorded at `f1a0737`. The final run is `2 failed, P0+18 passed, 2 skipped` (P0 = the baseline PASSED count, expected 2680) | gate (Plan), V1 |
| CRK2 | Between `f1a0737` and the final commit the only pinned files changed are `bin/ltx-movie` (numstat `423 15`) and `character_dataset.py` (`9 9`); `qwen_edit.py` `41 6`; `seed_edit_mflux_child.py` `5 2`; the only other non-docs files are the two new test files and `test_mut26`'s two BASELINE lines | V1 |
| CRK3 | Without `--cast-refs-model` nothing changes: Phase 2 calls `_phase2_shots(args, cmd)` exactly as before, no record or work directory is written, the mflux and diffusers spec files of single-image jobs and their timeouts are byte-identical, and no existing test is edited except `test_mut26`'s BASELINE | CRT2, CRT15, the unchanged suites, L3 |
| CRK4 | One Qwen child per Phase 2 run: `run_jobs` is called once with exactly the cast-reference panels to edit, never for a one-character panel; zero times when every cast-reference still is reused | CRT11, CRT12, CRT14 |
| CRK5 | Every cast-reference output is screened (skill `ltx_movie_cast_ref_edit`, the job's own prompt). A blocked or failed panel makes Phase 2 exit 1 with no still for that panel and no Z-Image fallback; the Z-Image panels still run | CRT13, CRT18 |
| CRK6 | L1 (`qwen21-q4`, the_fight4 story, ogre + ronin): the user judges at least 2 of the 3 two-shots (panels 7-9) **clean**, against the recorded the_fight4 Z-Image stills | L1 |
| CRK7 | L2 (`qwen2511-bf16`, same story): at least 2 of 3 two-shots clean, or the row says "not run: <reason>" when the model is not installed | L2 |
| CRK8 | L4: no child timeout in L1, L1b or L2; seconds per panel and peak memory recorded for each | L4 |
| CRK9 | L1b (`qwen21-q4`, the_fight7 story, ronin + troll): at least 2 of the 3 two-shots (panels 2, 8, 9) clean, so cast references do not regress a cast whose Z-Image two-shots were already clean | L1b |

A two-shot is **clean** when all four hold: both characters are present; each is recognisable as its library character (face, hair, build); each wears its own clothing (the ronin's haori stays indigo, with dark hakama; neither creature wears the ronin's clothes); and no feature is swapped between them.

Every CR requirement and CRT test is a must-have. Every live check row is a must-have for the user's decision, with L2 allowed to be "not run" when its model is missing. There are no nice-to-haves.

---

## 1. Decisions

1. **Where:** Phase 2 inside `bin/ltx-movie`, as a shots branch of `phase2_stills` taken only when `args.cast_refs` is set (CR10). This matches [SE] Decision 1: `bin/ltx-story-images` is pinned, stdlib-only at import time, and runs once per stills-LoRA group. The cast-reference panels are taken out of the Z-Image groups (`_exclude_groups`, CR11) and edited in ONE `qwen_edit.run_jobs` batch, so the model loads once.
2. **Order of the two pictures = cast order** (`args.cast_members`, which is `--character` order, then `--cast` order). The robust engine numbers plan cast ids `c1..cN` in the same order (`story_engine.py:1309-1311`), so this is "the plan cast ids' order" from decision 1. The beat cast is not used, because a panel can name a character who is not in its beat cast (the_fight4 panel 7). **[spec choice]**
3. **The reference picture: the kept medium-shot dataset still, else the dataset reference (CR6).** **[spec choice]**
   - The decision's "reference still" (`<dataset.reference>.png`) is char_00 for seed-built characters and char_01 for descriptor-built ones. char_00 is a face-centred 16:10 crop of the seed; char_01 is a close-up (Section 0.4). Neither reliably shows the clothing, and clothing is exactly what blended in the_fight4.
   - Still 9 of both build modes is "medium shot, standing with arms relaxed, plain grey backdrop" (`character_dataset.py:86`), which shows the full outfit on a neutral background. It is used when `dataset/manifest.json` lists item 9 as kept and its `gen_prompt` names both "medium shot" and "standing with arms relaxed". That check protects against the two-source numbering, in which n = 9 is a profile close-up.
   - Otherwise the dataset reference is used, after a note that says the clothing then rests on the `Image:` text.
   - No character.json path is read: paths come from `character_lib.character_dir(name)`.
4. **Prompt (CR8).**
   - The prompt is `CAST_REFS_EDIT_PREFIX` (naming "Picture 1, the first input image" and "Picture 2, the second input image" by their referring phrases), then an optional position sentence, then the panel's `Image:` text joined with the `Style:` text exactly as `bin/ltx-story-images` joins them. "The first input image" is included because qwen21 tags pictures `<image1>`, `<image2>` while diffusers writes `Picture 1:`, `Picture 2:`.
   - **Identity sentences are kept** (ruling): they are the library descriptors from which the reference stills were generated, they bind each description to its phrase, and the Z-Image baseline had the same text, so the A/B varies only the image model and its conditioning. No code removes them.
   - **No LoRA trigger word is inserted** (ruling): triggers are Z-Image LoRA tokens and no character LoRA runs in a Qwen edit (as [SE] SE11).
5. **Position sentence (CR8).** The model cards place subjects by position, so when the `Image:` text puts the two phrases on different sides (left/right patterns, CR8), the prompt adds "In the new shot A is on the S1 of the frame and B is on the S2." Otherwise nothing is added: no guessing. This mitigates Picture 1/2 confusion; L1 measures swaps. **[spec choice]**
6. **Size.** Edit at the still size (2W × 2H) floored to the model's multiple, which is a no-op because 2W and 2H are multiples of 128. That is decision 1's "output at the stills size", the same pixel size as the Z-Image stills. `fit_letterbox` into `images/panel_NN.png` is kept as a guard and adds no bars. Risk R2 and Open question 2 cover the resolution.
7. **Timeout factor 6 (CR2).** **[spec choice]**
   - Image tokens at 16 px per token (inferred from the Qwen-Image VAE ×8 and 2×2 patches): a 2048×1152 output is 9216 tokens, and each reference is about 4096 (about 1024² area). A two-reference job at the still size is about 9216 + 8192 + about 400 text tokens, roughly 17.8k tokens. A one-reference job at a 1024×576 video size is about 6.7k.
   - That is about 2.7× the tokens. Attention cost grows roughly with the square (about 7×) and the MLP linearly (about 2.7×).
   - The timeout only bounds a hang, so it is set generously: a job with two or more sources counts as 6 jobs, 3600 s each. That gives max(3600, 600 × 6 × n) for n two-reference jobs: 3600 s for one panel, 10800 s for three.
   - Single-image jobs are unchanged (`jobs_timeout` equals `child_timeout(len(jobs))`).
8. **Memory.** The registry floors are total-RAM gates and stay unchanged (`qwen21-q4` 20 GiB, `qwen2511-bf16` 64 GiB). A second reference and the 4× larger canvas raise peak memory (inferred: a few GiB on q4). The mflux child already prints `mlx peak memory` per job; this spec logs the child to `<story>/cast_ref_edits/child.log` so L4 can read it.
9. **CLI-only for v1.** **[spec choice]** A Compose control would touch:
   - `movie_ui_lib.py`: a new `FIELD_FLAGS` entry (31 entries pinned by SET21), `DEFAULT_FIELDS`, `build_argv`, V1 rules.
   - `movie_ui_server.py`: field cleaning and the 409 availability probe for a second selection.
   - `movie_ui_batch.py`: `FIELD_LEVELS`.
   - `index.html` and `app.js`: a second `qwenPicker`, `composeFields`, `fillCompose`, `updateComposeButtons`.
   - their tests.

   That is at least six files and several pins, for a test option. It is follow-up F3.
10. **Z-Image first, then the Qwen batch (CR10).** Both always run. The existing groups' output appears first and unchanged. A failed Qwen batch never stops the Z-Image panels, and a failed Z-Image group never stops the Qwen batch. Phase 2 returns 1 if either failed, so a rerun reuses everything finished (Z-Image by existence, Qwen by record). **[spec choice]**
11. **Errors, not fallbacks.** These are errors:
    - a cast member with no reference still (exit 2 before any phase);
    - two cast members with byte-identical reference stills (exit 2);
    - a panel naming three or more cast characters (Phase 2 exit 1, nothing run);
    - a blocked or failed edit (Phase 2 exit 1 after the batch).

    A silent Z-Image fallback for any of them would mix the two pipelines in a test that compares them.

---

## 2. Architecture

```
bin/ltx-movie --shots --character A --character B --cast-refs-model ID [--cast-refs-lora ID=S ...]
  main: ... _resolve_seed_edit -> _resolve_cast_refs (CR4; sets args.cast_refs or None)
  Phase 1 (unchanged) -> Phase 1b -> [Redo] -> Phase 2: phase2_stills
      shots and args.cast_refs -> _phase2_shots_cast_refs (CR10)
          _cast_refs_plan (CR9, read-only): pairs {n: [A, B]}, prompts (CR8), keys, reuse / todo
          no pair -> note, _phase2_shots(args, cmd)            (byte-identical groups)
          note (CR5) -> _phase2_shots(args, cmd, exclude=pairs) (Z-Image, other panels)
                     -> _phase2_cast_refs_batch: move stale stills aside, clear todo entries,
                        qwen_edit.wait_for_memory -> qwen_edit.run_jobs(jobs with sources=[A, B])
                        on_result: fit into images/panel_NN.png, record entry in cast_ref_edits.json
  -> Phase 3 manifest (unchanged; every panel still is images/panel_NN.png; video LoRAs by --cast)
  -> Phase 4 render (unchanged; --resume re-renders clips whose still bytes changed)
qwen_edit.run_jobs: job "sources" -> mflux spec job "sources" -> image_paths
                                  -> diffusers spec job "images" -> pipe(image=[...])
```

---

## 3. `qwen_edit.py` and the two children (CR1-CR3)

- **CR1. The refusal table.** `MULTI_REFERENCE_REFUSED = {"qwen2511-q4": <text>}`, `MULTI_REFERENCE_MODEL_IDS` (the registry ids minus the refused ones: `qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-bf16`), and `multi_reference_problem(model_id)` returning the text or `None`. Exact text in edit Q2.
- **CR2. The timeout.** `MULTI_REFERENCE_TIMEOUT_FACTOR = 6`. `jobs_timeout(jobs)` = `max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S × Σ weight)`, where the weight is 6 for a job whose `sources` lists two or more images and 1 otherwise. `run_jobs` uses it instead of `child_timeout(len(jobs))`. `child_timeout` is unchanged, and `jobs_timeout` of single-image jobs equals it.
- **CR3. The job schema.**
  - A `run_jobs` job may carry `"sources"`: its reference images in order, whose first item is its `"source"`.
  - **mflux:** the spec job gets `"sources"` after its usual five keys, only when the job has it. `seed_edit_mflux_child.py` passes `job["sources"]` as `image_paths`, else `[source]`.
  - **diffusers:** the spec item gets `"images"` only when the job has `"sources"`. `child_qwenedit` uses `job["images"]` when present, else `[job.get("image", spec["image"])]`, opens each path once, and passes the list to `pipe(image=...)`.
  - **The guard:** `run_jobs` raises `Unavailable("<label> cannot edit with several reference images: <CR1 text>")` before any check or child when the model is refused and any job lists two or more sources.
  - Single-image jobs produce byte-identical spec files (QET4, SQT8 and LD18 stay unedited and pass).

## 4. `bin/ltx-movie` (CR4-CR13)

- **CR4. `_resolve_cast_refs(args)`** (edit M4), called from `main` directly after `_resolve_seed_edit` (M15). Sets `args.cast_refs` to `None` or `{"qwen_model", "loras", "stills": {name: path}}`. The rules apply in this order; each refusal prints one `Error:` line and returns 2:
  1. no `--cast-refs-model`: with `--cast-refs-lora` refuse, else `None`;
  2. without `--shots` refuse. This also covers `--no-stills`: `--shots --no-stills` is already refused earlier by `_resolve_shots`, and `--no-stills` without `--shots` is refused here;
  3. with `--seed-image` refuse;
  4. no `qwen_edit.py` in the workspace: refuse;
  5. not a registry id (`as-is` included): refuse, listing `MULTI_REFERENCE_MODEL_IDS`;
  6. a refused id (`qwen2511-q4`): refuse with the CR1 text;
  7. `qe.cli_selection(model, loras, "--cast-refs-model", "--cast-refs-lora")`; a `SelectionError` refuses;
  8. fewer than two cast members: print `CAST_REFS_NOOP_NOTE`, keep `None`, return 0;
  9. per cast member, `_cast_ref_still` (CR6); a missing still refuses; two members with the same sha256 refuse;
  10. unless `--dry-run` or `--story-only`, `qe.selection_problem(model_id, loras)`; a problem refuses.
- **CR5. Constants** (M2): `CAST_REFS_SKILL = "ltx_movie_cast_ref_edit"`, `CAST_REFS_SCHEMA = "ltx-movie.cast-ref-edits.v1"`, the prefix, the position sentence, the two regex patterns, `CAST_REFS_FULL_STILL = "char_09.png"`, `CAST_REFS_FULL_WORDS`, and four notes. `CAST_REFS_LORA_NOTE` is printed once per Phase 2, before the Z-Image groups, when any Z-Image stills LoRA would have applied: a cast or location stills LoRA or the catalog stills pick (`_shots_seed_lora_note`), or `--stills-lora`.
- **CR6. `_cast_ref_still(member)`** returns `(path, error)` as Section 1 item 3 describes. The fallback prints `CAST_REFS_FALLBACK_NOTE`.
- **CR7. Flags** (M3): `--cast-refs-model ID` and the repeatable `--cast-refs-lora ID=SCALE` (none listed means no LoRA, as `--seed-edit-lora`). The exact help texts are in M3 and pinned by CRT17.
- **CR8. Prompt and position.**
  - `_cast_refs_side(lib, text, phrase, other)` scans each occurrence of `phrase`. Its segment runs to the next mention of either phrase or the next `.`, `!`, `?` or `;`. Inside the segment it collects matches of `CAST_REFS_SIDE_PATTERN` (`on/at/in the left|right`, `left|right of/side/edge/half`, `center-left` / `centre right`).
  - It returns the side when exactly one side is named, else tries the next occurrence; with none it returns `None`.
  - `_cast_refs_prompt(lib, pair, text)` adds `CAST_REFS_POSITION` only when both sides are found and differ.
  - Verified on the recorded stories: the_fight4 panel 7 gives green ogre `right` and ronin `left`. Panels 8 and 9 ("stand center-frame, facing each other") and the_fight7 2, 8 and 9 give no sentence.
- **CR9. Plan, key, record, reuse.** `_cast_refs_plan(args, qe)` is read-only.
  - Each panel's names come from `lib.cast_text(_compose_prompt(Image:, Style:), args.cast_members)[1]`. More than two is an error; exactly two makes a pair in cast order.
  - Edit size = still size floored to the multiple.
  - The key is the settings block plus `sources` (`[{"name", "still" (the file name), "sha256"}]` in picture order), `prompt`, `seed` (`--image-seed`), `width`, `height`, `still_width` and `still_height`.
  - Reuse follows SE13 exactly: not a `--redo` panel, entry `ok`, every key item equal, and the still exists with the recorded sha256.
  - The record is `<story>/cast_ref_edits.json`, `{"schema": "ltx-movie.cast-ref-edits.v1", "updated", "panels": [entry...]}`. Each entry has exactly these keys in this order: `n`, `status`, `created`, `label`, `sources`, `source_paths` (absolute, for inspection; not keyed, because hosts differ), `prompt`, `seed`, `width`, `height`, `still_width`, `still_height`, `qwen_model`, `loras`, `steps`, `scheduler`, `output`, `still`, `still_sha256`, `seconds`, `error`.
  - It is written through the existing `_write_shots_seed_record(..., schema)` and read through `_shots_seed_entries(..., schema)`; both gain a defaulted `schema` parameter (M8, M9), and every existing call is unchanged.
- **CR10. Phase 2.**
  - `_phase2_shots_cast_refs(args, cmd)`: plan error → exit 1. No pair → `CAST_REFS_NONE_NOTE`, then exactly `_phase2_shots(args, cmd)`. Otherwise: the LoRA note, `_phase2_shots(args, cmd, exclude=pairs)`, then `_phase2_cast_refs_batch`. Exit 1 if either failed.
  - `_phase2_cast_refs_batch` mirrors SE15 line for line: reuse lines; todo stills moved to `<story>/redo/<stamp>-<pid>/images/`; work files and entries cleared before the child; one `run_jobs` call with `log_path=<story>/cast_ref_edits/child.log` and `noun="panel"`; `on_result` fits and records; failed entries after the batch; failure and block texts (Section 5); no fallback.
  - Jobs are `{"n", "seed", "prompt", "source": A's still, "sources": [A's still, B's still], "stage_path", "output_path"}`, with stage and output files under `<story>/cast_ref_edits/`.
- **CR11.** `_exclude_groups(groups, exclude)` (M6) returns `groups` itself when `exclude` is empty, else the groups without those panels, dropping any group left empty. `_phase2_shots` (M7) and `_print_shots_stills_plan` (M11, M12) gain `exclude=()`.
- **CR12. Dry run** (M13, M14): `_print_cast_refs_plan` prints one sentence (model, size, seed, both pictures in cast order, skill, record path). Then, before Phase 1 has written story.md, it prints `Cast-reference panels: decided at Phase 2, from story.md after Phase 1` and the usual groups lines. Otherwise it prints `Cast-reference panels: <n (A, B); ...>; to edit: <list>; reused: <list>` and the groups without those panels. It reads no weights and writes nothing.
- **CR13. Docstring** (M1) and help (M3), pinned by CRT17.
- **CR14. Byte-identical default.** Every new path is gated by `args.cast_refs` (set only by CR4) or by the `exclude` and `schema` defaults. Without the flag, `phase2_stills` executes the same calls with the same arguments and prints the same lines; `run_jobs` writes the same spec and uses the same timeout for every existing caller.
- **CR15. `NEW_PY` is not extended** **[spec choice]**. `tests/test_qwen_edit.py` QET11 (`:402-405`) pins the exact tail of `NEW_PY`, so adding the two new files there would also mean editing QET11. The full-suite replay caught exactly that. The seeded-no-identity precedent is followed instead: its new test file is not in `NEW_PY`. Both new files still meet the `NEW_PY` rules by construction (no `load_module(`, no `urllib`; `SourceFileLoader` + `exec_module`), and each task compiles them on Python 3.9 and 3.13.
- **CR16. `test_mut26`** moves its BASELINE once, after both pinned files have changed (Task 3).

---

## 5. Errors and messages

| Condition | Where | Text | Effect |
|---|---|---|---|
| `--cast-refs-lora` without model | `_resolve_cast_refs` | `Error: --cast-refs-lora needs --cast-refs-model` | exit 2 |
| no `--shots` (also with `--no-stills`) | same | `Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters` | exit 2 |
| `--shots --no-stills` | `_resolve_shots` (existing) | `Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills` | exit 2 |
| with `--seed-image` | `_resolve_cast_refs` | `Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is already a Qwen edit of the seed` | exit 2 |
| no `qwen_edit.py` | same | `Error: --cast-refs-model needs <WS>/qwen_edit.py, which this workspace does not have` | exit 2 |
| not a registry id / `as-is` | same | `Error: --cast-refs-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-bf16` | exit 2 |
| `qwen2511-q4` | same | `Error: --cast-refs-model qwen2511-q4 is refused: mflux's Qwen-Image-Edit-2511 pipeline reads only the first input image (its edit tokenizer is built without picture prefixes), so the second character's reference would be silently ignored; use qwen2511-bf16 or a qwen21 model` | exit 2 |
| bad LoRA | same (`cli_selection`) | the `SelectionError` text with flag `--cast-refs-lora`, e.g. `Error: --cast-refs-lora: unknown LoRA x; known: uncensored, viggle-turbo` | exit 2 |
| fewer than 2 cast members | same | `note: --cast-refs-model has no effect: it needs at least two cast characters (--character or --cast), and this run casts <k>; every still is a Z-Image still` | stdout; flag off |
| a member without the medium-shot still | `_cast_ref_still` | `note: --cast-refs-model: character <name> has no kept medium-shot dataset still (char_09.png); its reference still <path> is used, which may show only the head and shoulders, so its clothing rests on the Image: text` | stdout |
| no reference still | `_resolve_cast_refs` | `Error: --cast-refs-model: character <name> has no reference still (looked for <path>); rebuild its dataset with bin/character create <name> --regenerate` | exit 2 |
| identical reference bytes | same | `Error: --cast-refs-model: characters <a> and <b> have the same reference still bytes (<path>); each picture must show a different person` | exit 2 |
| host check | same | `Error: --cast-refs-model <id>: <selection_problem text>` | exit 2 |
| story.md without panels | Phase 2 | `Error: <story.md> has no panels` | exit 1, nothing run |
| a panel names 3+ cast characters | Phase 2 | `Error: panel <n> of <story.md> names <k> cast characters (<names>); --cast-refs-model takes exactly two per panel` | exit 1, nothing run |
| no cast-reference panel | Phase 2 | `note: cast refs: no panel's Image: names two cast characters; every still is a Z-Image still` | then the unchanged Z-Image Phase 2 |
| LoRA note | Phase 2 | `note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to the cast-reference panels <list>: they are Qwen edits of the two characters' reference stills; every other panel keeps its Z-Image stills LoRAs` | stdout, once |
| child failure, timeout, missing result, memory wait, install check | Phase 2 | `Error: the cast-reference edits failed: <failure> (kept: <panels or none>; edited on the next run: <panels>)` | exit 1; failed entries recorded |
| blocked panel | Phase 2 | `Error: the content screen blocked the cast-reference Qwen edit (<label>) of panels <list> of story <id>; the movie stops here rather than use an unscreened or Z-Image still. Change those panels' Image: lines in <story.md>, then rerun: every other panel's still is reused` | exit 1; blocked entries recorded |
| info | Phase 2 | `cast refs: reusing the stills of panels <list> (...)`; `cast refs: every cast-reference panel's still is a recorded edit ...; nothing to edit`; `cast refs: moved <src> -> <dst> (...)`; `cast refs: <generator_text>; <W>x<H>, fitted into <SW>x<SH> stills; seed <s>; panels <list>, each with its two characters' reference stills as Picture 1 and Picture 2`; `cast refs: panel <n>: Picture 1 <A> (<path>), Picture 2 <B> (<path>)`; `panel <n> -> <still> (cast-reference Qwen edit, <s>s)`; `panel <n> BLOCKED: the content screen blocked the cast-reference Qwen edit`; `cast refs: <k> panel stills written` | stdout |
| refused model reaching `run_jobs` | `qwen_edit.run_jobs` | `Qwen-Image-Edit-2511 q4 (Lightning) cannot edit with several reference images: <CR1 text>` | `Unavailable` |

None of the new stdout lines matches the movie-ui render progress patterns (`^panel (\d+) ok: `, `^panel (\d+): reusing `, `^panel (\d+) FAILED \(`, `^=== panel (\d+)/(\d+) \(`), and `panel_NN.png.tmp` does not match `STILL_NAME_RE` (as [SE] SE15).

## 6. Audit: everything the change touches or could touch

| Reader / writer | Where | Verdict |
|---|---|---|
| `run_jobs` callers without `sources` | `bin/ltx-movie:2340`, `:2552`; `bin/seed-edit:429`; `character_dataset.py:1881` | Unchanged: spec files byte-identical (CR3), timeout identical (CR2). Pinned by QET3, QET4, SET5, SET15 and the seed-edit tests, all unedited. |
| `child_qwenedit` | character builds (`run_edit_child`), location builds (per-job `image`), `run_jobs` diffusers branch | Jobs without `images` take the old path: same open-once cache, `pipe(image=[one image])` (LD18, D44 unedited). |
| mflux child | every mflux registry run | Jobs without `sources` get `image_paths = [source]` (SQT8 unedited). |
| `_shots_stills_groups` | `_phase2_shots`, `_print_shots_stills_plan` | Called unchanged; filtering happens after it in `_exclude_groups`, which returns the same list object when nothing is excluded (CRT15). |
| `_shots_seed_entries`, `_write_shots_seed_record` | `_shots_seed_plan`, `_phase2_shots_seed` | Default `schema` keeps every existing call identical (SET5-SET15 unedited). |
| `images/panel_NN.png` | Phase 3 `--shots` manifest, Phase 4 `--resume` (`image_sha256`) | Same file names and size; a re-edited still re-renders its clip. |
| `--redo` | `phase_redo_shots` moves stills before Phase 2 | Redo panels are todo in CR9 (SE13 rule); the Z-Image path regenerates missing non-cast-reference stills as today. |
| Z-Image existence-only reuse | `_shots_missing_stills` | Unchanged for non-cast-reference panels. A panel that stops naming two characters, or a run without the flag, keeps an existing Qwen still: Review Focus 9. |
| Video LoRAs | Phase 3 `--cast` (`_cast_flags`) | Unchanged: each cast character's video LoRA still applies per panel. |
| movie-ui | stills counter (`images/panel_NN.png`), `FIELD_FLAGS` | Never passes the flag (CLI-only); `help_flags` sees two new flags, which no field maps. |
| deploy package | `scripts/deploy/build_pkg.py` ships `bin/ltx-movie`, not `qwen_edit.py` | There, `--cast-refs-model` gets the "needs qwen_edit.py" error (CR4 row 4). |

---

## 7. Tests

Two new files. Their full text is in the Plan (Task 1 Step 1, Task 2 Step 1). They follow [QE] §11.1: no real model, HOME, server, render or download. The children are the stubs of `tests/test_seed_edit_tool.py` or in-process `sys.modules` fakes.

`tests/test_qwen_edit_cast_refs.py` (Task 1):

| ID | Covers | Asserts |
|---|---|---|
| CRT1 | CR1, CR2 | the refusal table and allowed ids exactly; `multi_reference_problem` per registry id; factor 6; `jobs_timeout` equals `child_timeout(n)` for single jobs (n = 1, 6, 7, 24) and for one-item `sources`; `[3600, 7200, 10800, 21600]` for 1, 2, 3, 6 two-reference jobs; 6000 for one two-reference job plus four single jobs |
| CRT2 | CR2, CR3 | real `run_jobs` (mflux stub): the spec jobs carry `"sources"` only for the two-reference jobs, after the five usual keys; the single job's key list is exactly `n, seed, prompt, source, output_path`; the child timeout is 7800 s; a batch of single jobs has no `sources` key and the timeout `child_timeout(3)` |
| CRT3 | CR1, CR3 | `qwen2511-q4` with a two-reference job raises `Unavailable` with the exact text before any child runs; single jobs on `qwen2511-q4` still run |
| CRT4 | CR3 | real `run_jobs` (qwenedit stub): spec item `images: [a, b]` for two-reference jobs, `image: c` for the differing single job, skill passed |
| CRT5 | CR3 | the mflux child in-process: `image_paths` is `[a, b]` for a `sources` job and `[b]` for a plain one; the child's import list unchanged |
| CRT6 | CR3 | `child_qwenedit` in-process: the pipe gets `[a, b]`, `[c]`, `[b, a]`, `[a]` (sizes), each file opened once in first-use order, skill passed |

`tests/test_ltx_movie_cast_refs.py` (Task 2):

| ID | Covers | Asserts |
|---|---|---|
| CRT7 | CR4 | every refusal text exactly (rows of Section 5), the `--shots --no-stills` path through `main`, the no-op note, the resolved `args.cast_refs` in a dry run (no host check) and with a host problem (one `selection_problem` call), the missing-still and identical-bytes errors, the missing `qwen_edit.py` error |
| CRT8 | CR6 | char_09 chosen for a kept item 9 whose `gen_prompt` names both words (descriptor and edit prompt forms); the reference with the note for item 9 not kept, a close-up prompt, item n = 17, a non-dict item, a missing char_09 file and an unreadable manifest; the error when the reference file is missing |
| CRT9 | CR8 | the side reading on the the_fight4 panel 7 sentence (`right`, `left`), on the two-sentence case, `None` for four ambiguous or position-free texts, `center-left`/`centre right`; the exact prompt with and without the position sentence; the reversed cast order names the ronin as Picture 1 |
| CRT10 | CR9 | pairs `{2: [kyra, ronin], 4: [kyra, ronin]}`, the prompts, sizes 1408×896, todo `[2, 4]`, the exact key; reversed cast order; a three-character panel error; a story with no panels |
| CRT11 | CR10, CR11 | `phase2_stills` end to end: the LoRA note, Z-Image groups for panels 1 and 3 only, one `run_jobs` call with the exact jobs (source and sources), size, skill, work dir, noun and child log; the memory wait; stills at 1408×896 (Z-Image red for 1 and 3, Qwen colour for 2 and 4); the record's schema, key order and entries; the last stdout lines |
| CRT12 | CR9 | an identical rerun runs nothing; a changed `Image:` re-edits only panel 4 (old still moved to `redo/`); `--redo 2` only 2; new reference bytes both; another model both; an overwritten still only that panel; the Z-Image groups never rerun |
| CRT13 | CR10 | a blocked panel: exact error, no still, record entry `blocked`, Z-Image panels still made; a failed batch: exact text and `failed` entry; a memory-wait failure; a failing Z-Image group returns 1 but the Qwen batch still runs |
| CRT14 | CR10 | no two-character panel: the note, the plain groups, no `run_jobs`, no record |
| CRT15 | CR11, CR14 | without the flag: `_phase2_shots` called with `(args, cmd)` and no keyword, the plain groups, no fake call, no work dir; `_exclude_groups` identity and filtering; the schema defaults of the shared record helpers |
| CRT16 | CR12 | the dry run through `main`: the CR12 sentence and the "decided at Phase 2" line, followed by the unchanged groups lines; with a story and a record, `Cast-reference panels: 2 (kyra, ronin); 4 (kyra, ronin); to edit: 4; reused: 2` and groups without 2 and 4; no host check |
| CRT17 | CR7, CR13 | both help texts and the docstring paragraph exactly; still no top-level `import re` |
| CRT18 | CR3, CR10 | the real runner, mflux stub: one child, jobs with both sources, every output screened with skill `ltx_movie_cast_ref_edit` at 1408×896, panel 4 blocked, `child.log` written; the real runner with the diffusers stub: spec jobs carry `images` |

Before any code change: Task 1's file gives `6 failed`, and Task 2's gives `12 failed` (with Task 1's code in place). After the change, 18 passed. Mutation check in the scratch replay: reverting each edit made at least one new test fail. The dispatch (M5) failed 4, the exclusion (M7) 3, the record schema (M9) 4, the position sentence 4, the host check 1, `jobs_timeout` 1, mflux `sources` 2, diffusers `images` 2, the guard 1, the mflux child 1 and the qwenedit child 1.

No existing test is edited except `test_mut26`'s BASELINE (Task 3). No fixture is regenerated.

---

## 8. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

**Preparation.**
- In `~/local_agent_harness`: `git fetch && git checkout shots-multiref`.
- `bin/seed-edit-setup --model qwen21-q4 --lora uncensored`, if not installed.
- For L2: `Qwen/Qwen-Image-Edit-2511` and its Lightning LoRA must be in the default hub, and diffusers must be importable. If `bin/ltx-movie ... --cast-refs-model qwen2511-bf16` refuses with `... is unavailable: <reason>`, record L2 "not run: <reason>".
- Every run uses a NEW story id and a COPY of a recorded story, so the prompts equal the Z-Image baseline's. Unrecorded rows read "not run (awaiting the user)".

```bash
cd ~/local_agent_harness/qwen-agent-workspace
FLAGS="--panels 9 --fps 24 --frames 145 --video-width 1024 --video-height 576 --model dgrauet/ltx-2.5-mlx --gemma mlx-community/gemma-3-12b-it-qat-abliterated-lm-4bit --story-model DreamFast/Qwen3-VL-4b-Heretic --shots --location cyberpunk-city --no-auto-lora --speech-only"
copy() { mkdir -p generated/stories/$2 && cp generated/stories/$1/story.md generated/stories/$1/plan.json generated/stories/$2/; }
narr() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["narrative"])' generated/stories/$1/plan.json; }
```

The commands are zsh, macOS's default shell: `${=FLAGS}` splits the string into words (in bash, write `$FLAGS`). Each run has no `--no-review`. At the story review, press Enter. At the render gate ("Review the plan and the estimated render time above. Enter to render, ..."), the stills are done; press Ctrl-C there unless the row says to render.

| Row | Steps | Record | Pass |
|---|---|---|---|
| L1 | `copy the_fight4 mr_q21_ogre; /usr/bin/time -l bin/ltx-movie "$(narr the_fight4)" --story-id mr_q21_ogre ${=FLAGS} --character ogre --character ronin --cast-refs-model qwen21-q4 --cast-refs-lora uncensored=1.0` | the Phase 2 log (expect `stills group` lines for panels 1-6 only, and `cast refs:` lines for 7,8,9 with Picture 1 ogre, Picture 2 ronin); the report script below; for panels 7, 8 and 9, the four "clean" judgements (both present / each recognisable / own clothing / nothing swapped) beside the_fight4's `images/panel_07..09.png` (the Z-Image baseline: record how many of those 3 were clean) | CRK6: at least 2 of 3 clean |
| L1b | `copy the_fight7 mr_q21_troll; /usr/bin/time -l bin/ltx-movie "$(narr the_fight7)" --story-id mr_q21_troll ${=FLAGS} --character ronin --character troll --cast-refs-model qwen21-q4 --cast-refs-lora uncensored=1.0` | the same, for panels 2, 8 and 9 against the_fight7's stills; note any `panel N BLOCKED` (the troll is described "wearing no clothing") | CRK9: at least 2 of 3 clean |
| L2 | L1 with story id `mr_bf16_ogre` and `--cast-refs-model qwen2511-bf16` (no `--cast-refs-lora`) | the same records | CRK7: at least 2 of 3 clean, or "not run: <reason>" |
| L3 | default unchanged: `copy the_fight4 mr_default; bin/ltx-movie "$(narr the_fight4)" --story-id mr_default ${=FLAGS} --character ogre --character ronin --dry-run` | the Phase 2 block | it shows `stills group 1/3 (ogre, location cyberpunk-city; panels 2,4,6)`, `stills group 2/3 (ronin, location cyberpunk-city; panels 1,3,5)`, `stills group 3/3 (ogre, ronin, location cyberpunk-city; panels 7,8,9)`, and no `Cast-reference` and no `cast refs` text; `generated/stories/mr_default/cast_ref_edits.json` does not exist |
| L4 | from L1, L1b and L2 | per run: the report's seconds per panel and `mlx peak GiB` (mflux runs), `/usr/bin/time -l`'s "maximum resident set size" (an upper bound over every child of the run), and whether any `child timed out` line appeared | CRK8: no timeout; numbers recorded |
| L5 | rerun the exact L1 command, then rerun it with `--redo 8` | the first rerun's `cast refs: reusing the stills of panels 7,8,9 ...` and no child; the second's `cast refs:` plan line listing only panel 8, and `redo/<stamp>-<pid>/images/panel_08.png` holding the old still | reuse and `--redo` behave as described |

**Report script.** Run it inside each run's `generated/stories/<id>/`:

```bash
python3 - <<'EOF'
import glob, json, os, re
record = json.load(open("cast_ref_edits.json"))
for e in record["panels"]:
    print("panel", e["n"], e["status"], "%ss" % e["seconds"], e["qwen_model"]["id"],
          "%dx%d" % (e["width"], e["height"]),
          "pictures", [s["name"] + ":" + s["still"] for s in e["sources"]],
          "position" if "In the new shot " in e["prompt"] else "no position",
          len(e["prompt"].split()), "words", e["error"] or "")
log = "cast_ref_edits/child.log"
peaks = ([float(m) for m in re.findall(r"mlx peak memory ([0-9.]+) GiB", open(log).read())]
         if os.path.exists(log) else [])
print("mlx peak GiB per panel", peaks, "max", max(peaks) if peaks else None)
print("timed out" if os.path.exists(log) and "timed out" in open(log).read() else "no timeout line in child.log")
print("stills", sorted(os.path.basename(p) for p in glob.glob("images/panel_*.png")))
EOF
```

**If L1 fails**, the report shows where the problem is:
- `pictures ...:char_00.png` or `char_01.png` means a face crop was the reference (Risk R3).
- `no position` on a swapped panel means the `Image:` text gave no sides (Review Focus 2).
- Duplicated or extra people at 2048×1152 point to the resolution (Risk R2, Open question 2).

---

## 9. Review focus

1. **Face-crop reference adequacy (CR6).** char_00 is a 16:10 face-centred crop of the seed, and char_01 is a close-up (verified in code and on the dev-Mac ronin). Neither carries the full outfit, so CR6 prefers the kept still 9, a medium shot standing on grey. Check that the manifest guard (n = 9, kept, both words) cannot pick a two-source still, and that the fallback note fires. The live report names the still used per character.
2. **Swapping / ordering.** Pictures follow cast order, which is plan cast id order. The prefix names each picture by its phrase in both template styles. The position sentence is added only when the `Image:` text gives distinct sides (CR8). the_fight4 panel 7 gets one; panels 8 and 9 ("center-frame, facing each other") do not. L1's "nothing swapped" judgement measures the result.
3. **Output aspect vs resized references.** The output is the still size (2W×2H, already a multiple of 32 and 16), so `fit_letterbox` adds no bars. The references are 1024×640 dataset stills that the pipelines resize to about 1024² area (qwen21) or 384² for the VL tower and 1024² for the VAE (diffusers). Both are inferred from source and condition the edit; they are not the canvas.
4. **Character with no reference still.** This is exit 2 before any phase, naming the path and `bin/character create <name> --regenerate` (CRT7).
5. **Same person twice.** `cast_text` reports each member once, so one character cannot fill both pictures. `resolve_cast` refuses a character cast twice. Two members with byte-identical stills are refused (CRT7).
6. **Cast of 2 where only one is a library character.** `cast_text` searches only `args.cast_members`, so such a panel names one member and stays on the Z-Image path with that member's stills LoRA, exactly as today.
7. **Content safety on outputs.**
   - Every output is screened with skill `ltx_movie_cast_ref_edit`: mflux in this process, diffusers inside the child (CRT18).
   - Inputs are not re-screened. Dataset stills were screened when they were generated; char_00 is a crop of the user's own seed.
   - A false-positive block stops Phase 2 (decision 5). The troll's descriptor says "wearing no clothing".
8. **qwen21 vs qwen2511-bf16.**
   - Picture tags: `<imageN>` vs `Picture N:`. The prefix names both.
   - Steps: 40 (`linear` scheduler) vs 8 (Lightning).
   - Memory floor: 20 vs 64 GiB. Multiple: 32 vs 16.
   - The `uncensored` LoRA exists for qwen21 only.
   - mflux screens in the parent; diffusers screens in the child.
   - Both get the same prompt and the same pictures.
9. **Existence-only reuse on the Z-Image side.** A panel whose `Image:` no longer names two characters, or a later run without the flag, keeps its existing Qwen still, because the Z-Image path reuses by existence (unchanged). Use `--redo N` or a new story id. `cast_ref_edits.json` keeps the stale entry, which is harmless because only cast-reference panels are ever reused from it.
10. **Identity sentences and triggers (CR8).** Identity sentences are kept for A/B fairness, and no triggers are added. Check that the prompt is `PREFIX [+ POSITION] + "The new shot: " + _compose_prompt(Image, Style)` and nothing else.
11. **Resolution.** Decision 1 sets the still size. For a 1024×576 video that is 2048×1152 (2.36 MP), above Qwen's usual 1-1.8 MP: Risk R2.
12. **The timeout factor and `jobs_timeout`** must keep every existing caller's timeout identical (CRT1, CRT2; QET3 unedited).

## 10. Risks the user should know (rulings)

- **R1 Style mismatch between panels.** The cast-reference panels are Qwen edits with no Z-Image character, location or catalog stills LoRA. The other panels are Z-Image with them. Expect a visibly different look (texture, colour response, the location LoRA's style), and a different look from the clips' neighbours. Not fixed here. A `Style:` line (or the rendering-style sentence the shots writer already puts in `Image:`) is the only shared lever. Judge style separately from identity in L1.
- **R2 Resolution.** At 2048×1152 a Qwen model can duplicate subjects or soften detail; it also costs about 2.7× the tokens of a video-size edit (Section 1 item 7). If L1 shows extra people or the run is too slow, Open question 2.
- **R3 Face-only fallback.** A character without a kept still 9 is conditioned on a face crop, so its clothing comes from the identity sentence only. The note and the report say when this happened.
- **R4 Picture swap.** Index naming may not bind; the position sentence exists only when the `Image:` text gives sides.
- **R5 Content screen.** A blocked panel stops the run by design, and with the pinned `--image-seed` an unchanged rerun reproduces the block.
- **R6 Run time** is unmeasured. The cap is 3600 s per two-reference panel; a timeout keeps the finished panels.
- **R7 Memory.** The floors are total-RAM gates, and peak use rises with the second reference and the larger canvas (L4 measures it).
- **R8 Prompt length.** The prefix (about 85 words), optionally the position sentence, then `Image:` with two identity sentences (often 150-250 words): the text-encoder limit is unverified ([SE] risk 5).
- **R9 The identity sentences stay** and can disagree with a reference picture that drifted from the descriptor.
- **R10 qwen2511-q4 is unavailable** for this option until follow-up F1.

## 11. Amended requirements of earlier specs

| Item | Status |
|---|---|
| [QE] `qwen_edit.py` docstring "qwen2511-bf16 runs the unchanged character_dataset.py qwenedit child" | amended by CR3 (the child also reads a job's `images` list) |
| [QE] QE11 (child timeout `child_timeout(len(jobs))` in `run_jobs`) | amended by CR2 (`jobs_timeout`, identical for single-image jobs) |
| [QE] QE13-QE15 (spec shapes) | extended by CR3 (`sources` / `images` only for multi-reference jobs) |
| [SHOTS] 5.5 (one `bin/ltx-story-images` run per stills-LoRA group, every panel) | with `--cast-refs-model`, the cast-reference panels are excluded (CR10, CR11) |
| [SE] SE12 helpers `_shots_seed_entries`, `_write_shots_seed_record` | gain a defaulted `schema` parameter (CR9); behaviour unchanged |
| [SE] Section 0.5 "Shots panels conditioned on another panel's still (multi-reference edits)" out of scope | still out of scope for seeded shots; this spec adds multi-reference for unseeded shots only |

## 12. Follow-ups (not in this spec)

- F1 `qwen2511-q4` multi-image: replace `model.tokenizers["qwen_vl"]` with a `QwenVisionLanguageTokenizer(..., use_picture_prefix=True)` in the child when a job has more than one image (inferred fix; needs its own spike).
- F2 Seeded shots + both references (the seed plus each character's picture).
- F3 A movie-ui Compose control (Section 1 item 9).
- F4 Three or more references (group shots), and a single-reference Qwen edit for one-character panels.
- F5 A user-chosen reference still per character.

## 13. Open questions (for after the live checks)

1. **The live-check cast.** The controller named "ronin + troll". A Z-Image baseline with BOTH stills LoRAs exists only for ronin + ogre (the troll has no stills LoRA), so L1 uses the_fight4 (ogre + ronin) and L1b the_fight7 (ronin + troll). Confirm both runs are wanted.
2. **Edit size.** Keep the still size (decision 1), or edit at the video size and fit, as seeded shots do, if L1 shows duplicated people or long runs?
3. **Identity sentences.** Keep them in the Qwen prompt (this spec), or drop them for cast-reference panels in a follow-up A/B?
4. If L1 passes, should cast references become the default for two-shots, and should one-character panels get a one-reference Qwen edit for a consistent look (R1)?
5. Is factor 6 (3600 s per two-reference panel) right once L4 has numbers?

---

## Plan

**House rules** (every task):
- Work only in `$S/mr-wt`. Never touch `/Users/reubenpatterson/local_agent_harness`.
- Never stash, reset, amend, push or open a PR. Never access macstudio.
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's old text occurs exactly once in the file. If it does not, stop and report.
- Every changed `.py` file and both new test files compile on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

**Replay.**
- Tasks 1 and 2 were replayed in a scratch copy of `f1a0737` (`$S/mr-replay`, from `git archive`).
- Task 1's file gave `6 failed` before its edits and `6 passed` after. Task 2's gave `12 failed` before its edits (with Task 1's code in place) and `12 passed` after.
- Every Old/New block below was applied by script to a second fresh archive copy (`$S/mr-check`), and the result was byte-identical to the replay files.
- `git diff --no-index --numstat` gave: `bin/ltx-movie` `423 15`, `qwen_edit.py` `41 6`, `seed_edit_mflux_child.py` `5 2`, `character_dataset.py` `9 9`.
- Both Pythons compiled all six files.
- The full-suite replay is in "Replay result" at the end.

### Before Task 1: the snapshot, the baseline and the gate files (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/mr-baseline; mkdir -p $D
cd $S/mr-wt/qwen-agent-workspace
git branch --show-current                                     # shots-multiref
git diff --stat f1a0737 HEAD -- . ':(exclude)docs' | tail -1  # no output (only this spec is committed)
git status --short                                            # no output
wc -l bin/ltx-movie qwen_edit.py seed_edit_mflux_child.py character_dataset.py tests/test_movie_ui_builder.py
                                                              # 3256, 557, 109, 2021, 302
tar czf $S/snapshot-pre-mr-f1a0737.tgz --exclude generated -C $S/mr-wt qwen-agent-workspace; ls -l $S/snapshot-pre-mr-f1a0737.tgz
df -g . | tail -1                                             # at least 5 GiB free
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                     # record as P0
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
```

Expected:
- The summary is `2 failed, 2680 passed, 2 skipped`. That is the seeded-no-identity Task 2 result (`$S/si-baseline/task-2-pytest.txt`), on a tree identical to `f1a0737` (`dc8507a` and `f1a0737` have no diff).
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. There is no `ERROR` line, and `test_mut26` passes.
- `baseline-ok-lines.txt` holds `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68`, `OK 205/205`.

If `test_tr27_fanout_two_rounds_and_missing_reasons` or `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` also fails, rerun the two alone; `2 passed` means the baseline stands. Any other difference: stop and report.

Then write the gate files (scratch, never staged) from the seeded-no-identity plan's:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/mr-baseline
python3 - "$S/si-baseline/gate.py" "$D/gate.py" <<'EOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
for old, new in (("The task gate of the seeded no identity plan", "The task gate of the shots multi-reference plan"),
                 ("test is any test of tests/test_seeded_no_identity.py or any test ID",
                  "test is any test of the plan's two new test files or any test ID"),
                 ('NEW_FILES = ("tests/test_seeded_no_identity.py::",)',
                  'NEW_FILES = ("tests/test_qwen_edit_cast_refs.py::", "tests/test_ltx_movie_cast_refs.py::")')):
    assert s.count(old) == 1, old
    s = s.replace(old, new)
open(sys.argv[2], "w", encoding="utf-8").write(s)
EOF
sed -e 's#/si-baseline#/mr-baseline#' -e 's#/si-wt/#/mr-wt/#' $S/si-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'EOF'
# shots multi-reference plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 2 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged character_dataset.py changes in Task 1 and bin/ltx-movie in Task 2; Task 3 moves BASELINE
1 3 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
EOF
grep -c mr-baseline $D/gate-run.sh; grep -c /mr-wt/ $D/gate-run.sh; grep -c "_cast_refs.py::" $D/gate.py   # 1, 1, 1
```

**The gate** for task N is `zsh $S/mr-baseline/gate-run.sh N`. It is a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints `disk ok`, the pytest summary, the gate line and `GATE PASS`, `2 passed` for the flake rerun, and `ATK2 OK lines unchanged`. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the multi-reference job in `qwen_edit.py` and both children (one commit)

**Files:** `qwen_edit.py`, `seed_edit_mflux_child.py`, `character_dataset.py` (pinned), `tests/test_qwen_edit_cast_refs.py` (new).

- [ ] **Step 1: Write `tests/test_qwen_edit_cast_refs.py`** with the Write tool, exactly (the file ends with a single newline after the last line):

```python
"""Tests for the multi-reference Qwen edit job (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-
design.md, CR1-CR3: CRT1-CRT6): a qwen_edit.run_jobs job may carry "sources", every reference image in order;
the mflux child passes them as image_paths, the diffusers qwenedit child as its image list; qwen2511-q4 is
refused; a multi-reference job counts MULTI_REFERENCE_TIMEOUT_FACTOR jobs in the child timeout. Single-image jobs
are unchanged.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit_cast_refs.py

The children are tests/test_seed_edit_tool.py's stubs (through test_qwen_edit's env fixture) or run in-process
with sys.modules fakes (test_seed_edit_tool.child_fakes, test_location_dataset._fake_edit_stack). No test loads a
model, renders, downloads or contacts a server. Stdlib, PIL and pytest.
"""

import json
import os
import re

import pytest
from PIL import Image

import movie_ui_testutil as mt  # first: it puts the workspace on sys.path
import character_dataset  # noqa: E402
import qwen_edit as qe  # noqa: E402
import test_seed_edit_tool as st
from test_location_dataset import _fake_edit_stack
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

UNC = [{"id": "uncensored", "scale": 1.0}]
REFUSED = ("mflux's Qwen-Image-Edit-2511 pipeline reads only the first input image (its edit tokenizer is built "
           "without picture prefixes), so the second character's reference would be silently ignored; use "
           "qwen2511-bf16 or a qwen21 model")


def _refs(env):
    """Two distinct 1024x640 reference PNGs and one 640x1024 source under tmp."""
    return [st.png(os.path.join(env["tmp"], "refs", "a.png"), (1024, 640), (0, 90, 0)),
            st.png(os.path.join(env["tmp"], "refs", "b.png"), (1024, 640), (0, 0, 90)),
            st.png(os.path.join(env["tmp"], "refs", "c.png"), (640, 1024), (90, 0, 0))]


def _jobs(env, refs, multi=(1, 3)):
    """Jobs 1-3 (stage cand_NN.pending.png): the numbers in multi carry sources [a, b], the rest only source c."""
    out = os.path.join(env["tmp"], "out")
    os.makedirs(out, exist_ok=True)
    jobs = []
    for n in (1, 2, 3):
        job = {"n": n, "seed": 7, "prompt": "two people %d" % n, "source": refs[0] if n in multi else refs[2],
               "stage_path": os.path.join(out, "cand_%02d.pending.png" % n),
               "output_path": os.path.join(out, "cand_%02d.png" % n)}
        if n in multi:
            job["sources"] = [refs[0], refs[1]]
        jobs.append(job)
    return jobs


# --- CRT1 (CR1, CR2): the refusal table and the timeout ------------------------------------------------------

def test_crt1_the_refusal_table_and_the_timeout():
    assert qe.MULTI_REFERENCE_REFUSED == {"qwen2511-q4": REFUSED}
    assert qe.MULTI_REFERENCE_MODEL_IDS == ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-bf16")
    assert [qe.multi_reference_problem(m) for m in qe.MODEL_IDS] == [None, None, None, REFUSED, None]
    assert qe.MULTI_REFERENCE_TIMEOUT_FACTOR == 6
    single, multi = {"n": 1}, {"n": 1, "sources": ["a", "b"]}
    for n in (1, 6, 7, 24):
        assert qe.jobs_timeout([single] * n) == qe.child_timeout(n), n
    assert qe.jobs_timeout([{"n": 1, "sources": ["a"]}] * 7) == qe.child_timeout(7)
    assert [qe.jobs_timeout([multi] * n) for n in (1, 2, 3, 6)] == [3600, 7200, 10800, 21600]
    assert qe.jobs_timeout([multi, single, single, single, single]) == 6000


# --- CRT2 (CR3): the mflux spec carries sources only for multi-reference jobs; the timeout follows ---------

def test_crt2_the_mflux_spec_and_timeout(env):
    mp = env["mp"]
    py, _snapshot, _lora = _mflux_ready(env)
    refs = _refs(env)
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(timeout_s)
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qe, "run_child", spy)
    jobs = _jobs(env, refs)
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 576, "ltx_movie_cast_ref_edit",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(py)
    assert call["spec"]["jobs"] == [
        {"n": 1, "seed": 7, "prompt": "two people 1", "source": refs[0], "output_path": jobs[0]["stage_path"],
         "sources": [refs[0], refs[1]]},
        {"n": 2, "seed": 7, "prompt": "two people 2", "source": refs[2], "output_path": jobs[1]["stage_path"]},
        {"n": 3, "seed": 7, "prompt": "two people 3", "source": refs[0], "output_path": jobs[2]["stage_path"],
         "sources": [refs[0], refs[1]]}]
    assert seen == [max(3600, 600 * (6 + 1 + 6))]
    with open(os.path.join(env["tmp"], "work", "mflux_spec.json"), encoding="utf-8") as f:
        assert list(json.load(f)["jobs"][1]) == ["n", "seed", "prompt", "source", "output_path"]
    single = _jobs(env, refs, multi=())
    qe.run_jobs("qwen21-q4", UNC, single, 1024, 576, "x", os.path.join(env["tmp"], "work2"))
    assert all("sources" not in j for j in st.stub_calls(py)[1]["spec"]["jobs"])
    assert seen[1] == qe.child_timeout(3)


# --- CRT3 (CR1, CR3): qwen2511-q4 refuses a multi-reference job before any child; single jobs still run ----

def test_crt3_qwen2511_q4_refuses_several_references(env):
    py, _snapshot, _lora = _mflux_ready(env, "qwen2511-q4")
    refs = _refs(env)
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen2511-q4", [], _jobs(env, refs), 1024, 576, "x", os.path.join(env["tmp"], "work"))
    assert str(info.value) == ("Qwen-Image-Edit-2511 q4 (Lightning) cannot edit with several reference images: "
                               + REFUSED)
    assert st.stub_calls(py) == []
    results, failure = qe.run_jobs("qwen2511-q4", [], _jobs(env, refs, multi=()), 1024, 576, "x",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3


# --- CRT4 (CR3): the diffusers spec gives a multi-reference job its "images" list -------------------------

def test_crt4_the_diffusers_spec_lists_every_reference(env):
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {})
    refs = _refs(env)
    jobs = _jobs(env, refs)
    results, failure = qe.run_jobs("qwen2511-bf16", [], jobs, 1024, 576, "ltx_movie_cast_ref_edit",
                                   os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(stub)
    spec = call["spec"]
    assert (spec["image"], spec["skill"]) == (refs[0], "ltx_movie_cast_ref_edit")
    assert spec["jobs"] == [
        {"prompt": "two people 1", "output_path": jobs[0]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "images": [refs[0], refs[1]]},
        {"prompt": "two people 2", "output_path": jobs[1]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "image": refs[2]},
        {"prompt": "two people 3", "output_path": jobs[2]["stage_path"], "seed": 7, "width": 1024, "height": 576,
         "images": [refs[0], refs[1]]}]


# --- CRT5 (CR3): the mflux child edits with every listed source -------------------------------------------

def test_crt5_the_mflux_child_passes_every_source(monkeypatch, tmp_path):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = st.child_fakes(monkeypatch)
    tmp = str(tmp_path)
    a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
    spec = {"family": "qwen21", "model_path": os.path.join(tmp, "model"), "lora_paths": [], "lora_scales": [],
            "width": 64, "height": 96, "steps": 40, "guidance": 1.0, "scheduler": "linear",
            "jobs": [{"n": 1, "seed": 3, "prompt": "p1", "source": a, "sources": [a, b],
                      "output_path": os.path.join(tmp, "o1.png")},
                     {"n": 2, "seed": 3, "prompt": "p2", "source": b, "output_path": os.path.join(tmp, "o2.png")}]}
    path = os.path.join(tmp, "spec.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    assert child.main(["--spec", path]) == 0
    assert [kwargs["image_paths"] for _name, kwargs in record["generate"]] == [[a, b], [b]]
    with open(os.path.join(mt.WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "importlib.metadata", "json", "os", "re", "sys", "threading", "time"]


# --- CRT6 (CR3): the qwenedit child gives the pipeline every image of a job, each file opened once --------

def test_crt6_the_qwenedit_child_takes_a_per_job_image_list(tmp_path, monkeypatch):
    a, b, c = str(tmp_path / "a.png"), str(tmp_path / "b.png"), str(tmp_path / "c.png")
    Image.new("RGB", (300, 200), (10, 20, 30)).save(a)
    Image.new("RGB", (200, 300), (40, 50, 60)).save(b)
    Image.new("RGB", (100, 100), (70, 80, 90)).save(c)
    calls = {"pipe": [], "skills": [], "opened": [], "lora": None}
    _fake_edit_stack(monkeypatch, calls)
    jobs = [{"prompt": "two", "output_path": str(tmp_path / "o1.png"), "seed": 5, "width": 64, "height": 40,
             "images": [a, b]},
            {"prompt": "one", "output_path": str(tmp_path / "o2.png"), "seed": 5, "width": 64, "height": 40,
             "image": c},
            {"prompt": "two again", "output_path": str(tmp_path / "o3.png"), "seed": 5, "width": 64, "height": 40,
             "images": [b, a]},
            {"prompt": "spec image", "output_path": str(tmp_path / "o4.png"), "seed": 5, "width": 64, "height": 40}]
    spec = {"image": a, "model": "M", "lora_repo": "R", "lora_file": "F.safetensors", "steps": 8, "true_cfg": 1.0,
            "skill": "ltx_movie_cast_ref_edit", "report_path": str(tmp_path / "report.json"), "jobs": jobs}
    path = str(tmp_path / "spec.json")
    with open(path, "w") as f:
        json.dump(spec, f)
    assert character_dataset.main(["qwenedit", "--spec", path]) == 0
    assert calls["opened"] == [a, b, c]
    assert [[img.size for img in call["image"]] for call in calls["pipe"]] == [
        [(300, 200), (200, 300)], [(100, 100)], [(200, 300), (300, 200)], [(300, 200)]]
    assert calls["skills"] == ["ltx_movie_cast_ref_edit"] * 4
    with open(str(tmp_path / "report.json")) as f:
        assert [j["status"] for j in json.load(f)["jobs"]] == ["ok"] * 4
```

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit_cast_refs.py 2>&1 | tail -1` prints `6 failed, ...`. CRT1 fails with `AttributeError: module 'qwen_edit' has no attribute 'MULTI_REFERENCE_REFUSED'`, and the others fail on assertions or `DID NOT RAISE`, not on import errors.

- [ ] **Step 3: Twelve Edits** (Q1-Q8, C1-C2, D1-D2). Each Old text occurs exactly once.

**Q1** (`qwen_edit.py`). Old:
```python
name; qwen2511-bf16 runs the unchanged character_dataset.py qwenedit child, which screens each output
itself. The child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds.
```
New:
```python
name; qwen2511-bf16 runs the character_dataset.py qwenedit child, which screens each output itself. The
child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds, where a job with several reference images
(its "sources" list, docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md) counts
MULTI_REFERENCE_TIMEOUT_FACTOR jobs.
```

**Q2** (`qwen_edit.py`). Old:
```python
JOB_TIMEOUT_S = 600              # the budget per job above the floor
```
New:
```python
JOB_TIMEOUT_S = 600              # the budget per job above the floor
MULTI_REFERENCE_TIMEOUT_FACTOR = 6   # a job with several reference images counts as this many jobs (cast refs CR2)
MULTI_REFERENCE_REFUSED = {          # registry models that cannot edit with several reference images (cast refs CR1)
    "qwen2511-q4": ("mflux's Qwen-Image-Edit-2511 pipeline reads only the first input image (its edit tokenizer is "
                    "built without picture prefixes), so the second character's reference would be silently "
                    "ignored; use qwen2511-bf16 or a qwen21 model"),
}
MULTI_REFERENCE_MODEL_IDS = tuple(m for m in MODEL_IDS if m not in MULTI_REFERENCE_REFUSED)
```

**Q3** (`qwen_edit.py`). Old:
```python
def child_timeout(n_jobs):
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * n_jobs)
```
New:
```python
def child_timeout(n_jobs):
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * n_jobs)


def multi_reference_problem(model_id):
    """Why model_id cannot edit with several reference images in one job, or None (cast refs spec CR1)."""
    return MULTI_REFERENCE_REFUSED.get(model_id)


def jobs_timeout(jobs):
    """The child timeout for jobs (cast refs spec CR2): child_timeout(len(jobs)) when no job lists more than one
    source; a job whose "sources" lists two or more images counts MULTI_REFERENCE_TIMEOUT_FACTOR jobs."""
    weight = sum(MULTI_REFERENCE_TIMEOUT_FACTOR if len(job.get("sources") or ()) > 1 else 1 for job in jobs)
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * weight)
```

**Q4** (`qwen_edit.py`). Old:
```python
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16)."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = install_problem(model_id, loras)
```
New:
```python
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16). A job may also
    carry "sources", the list of its reference images in order, whose first item is its "source" (cast refs spec
    CR3); the child then edits with every listed image."""
    entry = seedgen.qwen_model(model_id)
    refused = multi_reference_problem(model_id)
    if refused is not None and any(len(job.get("sources") or ()) > 1 for job in jobs):
        raise Unavailable("%s cannot edit with several reference images: %s" % (entry["label"], refused))
    problem, paths = install_problem(model_id, loras)
```

**Q5** (`qwen_edit.py`). Old:
```python
            if job["source"] != first:
                item["image"] = job["source"]
            spec_jobs.append(item)
```
New:
```python
            if job["source"] != first:
                item["image"] = job["source"]
            if "sources" in job:
                item["images"] = list(job["sources"])     # cast refs CR3
            spec_jobs.append(item)
```

**Q6** (`qwen_edit.py`). Old:
```python
        ordered = seedgen.registry_order(loras)
        spec_path = os.path.join(work_dir, "mflux_spec.json")
        lib.write_json_atomic(spec_path, {
            "family": entry["family"], "model_path": paths["model_path"],
```
New:
```python
        ordered = seedgen.registry_order(loras)
        spec_path = os.path.join(work_dir, "mflux_spec.json")

        def spec_job(job):
            item = {"n": job["n"], "seed": job["seed"], "prompt": job["prompt"], "source": job["source"],
                    "output_path": job["stage_path"]}
            if "sources" in job:
                item["sources"] = list(job["sources"])    # cast refs CR3
            return item

        lib.write_json_atomic(spec_path, {
            "family": entry["family"], "model_path": paths["model_path"],
```

**Q7** (`qwen_edit.py`). Old:
```python
            "jobs": [{"n": job["n"], "seed": job["seed"], "prompt": job["prompt"], "source": job["source"],
                      "output_path": job["stage_path"]} for job in jobs]})
```
New:
```python
            "jobs": [spec_job(job) for job in jobs]})
```

**Q8** (`qwen_edit.py`). Old:
```python
    timeout = child_timeout(len(jobs))
```
New:
```python
    timeout = jobs_timeout(jobs)
```

**C1** (`seed_edit_mflux_child.py`). Old:
```python
empty), width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and jobs, each {n,
seed, prompt, source, output_path}; a spec-level prompt and source (the shape before
docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) are used for jobs that carry none.
```
New:
```python
empty), width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and jobs, each {n,
seed, prompt, source, output_path}; a spec-level prompt and source (the shape before
docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) are used for jobs that carry none. A job
with "sources" edits with every listed image, in order (its first item is its source;
docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md).
```

**C2** (`seed_edit_mflux_child.py`). Old:
```python
        source = job["source"] if "source" in job else spec["source"]
        kwargs = {"seed": job["seed"], "prompt": prompt, "image_paths": [source],
```
New:
```python
        source = job["source"] if "source" in job else spec["source"]
        images = job["sources"] if "sources" in job else [source]
        kwargs = {"seed": job["seed"], "prompt": prompt, "image_paths": images,
```

**D1** (`character_dataset.py`). Old:
```python
    """The child side of run_edit_child: load the editor and its Lightning LoRA from the local
    cache, edit each job's image (job["image"], else spec["image"]; location library spec L1.8)
    into every job, screen each result with spec["skill"] (default "character_edit"), write the
    report."""
```
New:
```python
    """The child side of run_edit_child: load the editor and its Lightning LoRA from the local
    cache, edit each job's images (job["images"], the cast refs spec's reference list, else
    job["image"], else spec["image"]; location library spec L1.8) into every job, screen each
    result with spec["skill"] (default "character_edit"), write the report."""
```

**D2** (`character_dataset.py`). Old:
```python
    for job in spec["jobs"]:
        path = job.get("image", spec["image"])
        if path not in sources:
            with Image.open(path) as img:
                sources[path] = img.convert("RGB")
        source = sources[path]
        started = time.monotonic()
        image = pipe(image=[source], prompt=job["prompt"], negative_prompt=" ",
```
New:
```python
    for job in spec["jobs"]:
        paths = job.get("images") or [job.get("image", spec["image"])]
        for path in paths:
            if path not in sources:
                with Image.open(path) as img:
                    sources[path] = img.convert("RGB")
        started = time.monotonic()
        image = pipe(image=[sources[path] for path in paths], prompt=job["prompt"], negative_prompt=" ",
```

No other line of these files changes.

- [ ] **Step 4: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit_cast_refs.py 2>&1 | tail -1     # 6 passed
python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py tests/test_seed_edit_tool.py tests/test_character_dataset.py tests/test_location_dataset.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_edit.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_builder.py 2>&1 | grep -E '^FAILED|passed|failed'
    # only test_d2_copied_literals_match_the_spike (baseline) and test_mut26_pipeline_files_are_unchanged (expected) fail
git diff --numstat                                             # 9 9 character_dataset.py; 41 6 qwen_edit.py; 5 2 seed_edit_mflux_child.py
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' qwen_edit.py seed_edit_mflux_child.py character_dataset.py tests/test_qwen_edit_cast_refs.py; done   # compiled 4, twice
zsh $S/mr-baseline/gate-run.sh 1
```
Expected gate output: the summary `3 failed, P0+5 passed, 2 skipped`; `lost 1 (listed 1, unexpected 0); new tests 6, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`. The single loss is `test_mut26` (`character_dataset.py` differs from BASELINE).

- [ ] **Step 5: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
git add qwen_edit.py seed_edit_mflux_child.py character_dataset.py tests/test_qwen_edit_cast_refs.py
git diff --cached --name-only | wc -l    # 4
git commit -m "qwen_edit: a job may carry several reference images (sources); the mflux and qwenedit children edit with all of them; qwen2511-q4 refuses them; multi-reference jobs get 6x the per-job timeout (shots-multiref CR1-CR3, CRT1-CRT6)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: `--cast-refs-model` in `bin/ltx-movie` (one commit)

**Files:** `bin/ltx-movie` (pinned), `tests/test_ltx_movie_cast_refs.py` (new).

- [ ] **Step 1: Write `tests/test_ltx_movie_cast_refs.py`** with the Write tool, exactly (the file ends with a single newline after the last line):

```python
"""Tests for bin/ltx-movie's --cast-refs-model (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-
design.md, CR4-CR13: CRT7-CRT18): in shots mode without a seed image, every panel whose Image: names two cast
characters is one Qwen edit with both characters' reference stills as its sources, in one batch, screened,
fitted, recorded in cast_ref_edits.json and reused on a rerun; every other panel keeps the Z-Image stills groups.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_cast_refs.py

bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and exec_module as
ltx_movie_crf. The cast_env fixture is story_engine_testutil.set_story_env (a temporary HOME and character
library) plus HF_HOME and Z_IMAGE_HF_HOME under tmp_path, no HF_HUB_CACHE and no SEED_EDIT_* variable; it patches
_story_dir to <tmp>/stories/<id>, _qwen_edit to a recording fake, and _stream_and_tee (the Z-Image stills group
runs) to a recorder that writes a still for every --only panel. CRT18 uses the real qwen_edit with the stub
children of tests/test_seed_edit_tool.py. No test loads a model, renders, contacts a server or touches port 8177
or 8178. Stdlib, PIL and pytest.
"""

import argparse
import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit
import story_engine_testutil as seu
import test_seed_edit_tool as st
from test_ltx_movie_shots_seed import PANEL_QWENEDIT_STUB, _FakeShotsQwenEdit
from test_qwen_edit import _bf16_cache, _mflux_ready, env  # noqa: F401

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
KYRA, RONIN = "the woman in grey", "the ronin"
STYLE = "Muted teal colour."
IMAGES = ["The woman in grey stands at the temple gate in the rain.",
          "The woman in grey stands on the left of the frame facing right toward the ronin. The ronin stands on the "
          "right of the frame and faces left.",
          "The ronin kneels by the stone well.",
          "The ronin and the woman in grey stand center-frame facing each other."]
PREFIX = ("Make one new film still that shows two different people together. Picture 1, the first input image, "
          "shows the woman in grey, and Picture 2, the second input image, shows the ronin. The woman in grey keeps "
          "exactly the face, hair, skin tone, build and clothing from Picture 1, and the ronin keeps exactly the "
          "face, hair, skin tone, build and clothing from Picture 2; never swap or mix their faces, colours or "
          "clothing. Take only these two people from the pictures, not their pose, background, lighting or "
          "framing. ")
POSITION = "In the new shot the woman in grey is on the left of the frame and the ronin is on the right. "
ENTRY_KEYS = ["n", "status", "created", "label", "sources", "source_paths", "prompt", "seed", "width", "height",
              "still_width", "still_height", "qwen_model", "loras", "steps", "scheduler", "output", "still",
              "still_sha256", "seconds", "error"]
LORA_NOTE = ("note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to the "
             "cast-reference panels %s: they are Qwen edits of the two characters' reference stills; every other "
             "panel keeps its Z-Image stills LoRAs")


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_crf", path)
    spec = importlib.util.spec_from_loader("ltx_movie_crf", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


def _prompt(n, images=IMAGES):
    return PREFIX + ("The new shot: " if n != 2 else POSITION + "The new shot: ") + images[n - 1] + " " + STYLE


class _FakeCastRefsQwenEdit(_FakeShotsQwenEdit):
    """test_ltx_movie_shots_seed's multi-job fake, plus the multi-reference table of the real qwen_edit; run_jobs
    also records log_path."""
    MULTI_REFERENCE_MODEL_IDS = qwen_edit.MULTI_REFERENCE_MODEL_IDS

    def __init__(self):
        _FakeShotsQwenEdit.__init__(self)
        self.multi_reference_problem = qwen_edit.multi_reference_problem
        self.logs = []

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.logs.append(log_path)
        return _FakeShotsQwenEdit.run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir,
                                           on_result=on_result, noun=noun)


@pytest.fixture
def cast_env(monkeypatch, tmp_path):
    """The module docstring's environment. Returns {"tmp", "lib", "fake", "groups"}; groups records every Z-Image
    group command and returns groups_rc (a list holding one int)."""
    tmp = str(tmp_path)
    story_env = seu.set_story_env(monkeypatch, tmp_path)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    fake = _FakeCastRefsQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    groups, groups_rc = [], [0]

    def stream(cmd, log_path):
        groups.append(list(cmd))
        out = cmd[cmd.index("--out-dir") + 1]
        size = (int(cmd[cmd.index("--width") + 1]), int(cmd[cmd.index("--height") + 1]))
        os.makedirs(out, exist_ok=True)
        for n in cmd[cmd.index("--only") + 1].split(","):
            Image.new("RGB", size, (200, 0, 0)).save(os.path.join(out, "panel_%02d.png" % int(n)))
        return groups_rc[0]

    monkeypatch.setattr(movie, "_stream_and_tee", stream)
    return {"tmp": tmp, "lib": story_env["lib"], "fake": fake, "groups": groups, "groups_rc": groups_rc}


def _character_still(lib, name, filename, color, size=(1024, 640)):
    path = os.path.join(lib, name, "dataset", "stills", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _manifest(lib, name, item9):
    path = os.path.join(lib, name, "dataset", "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"reference": "char_00", "items": [{"n": 1, "kept": True, "gen_prompt": "Close-up of x"}, item9]},
                  f)


def _cast(lib, names=("kyra", "ronin"), stills=True):
    """Trained kyra and ronin (and a third, monk, when named) with a char_00 reference still each (distinct colours)
    unless stills is False; returns the resolved CastMember list in names order."""
    makers = {"kyra": seu.kyra, "ronin": seu.ronin,
              "monk": lambda d: seu.make_character(d, "monk", "monkmn", "the old monk", "man", seu.MONK)}
    for i, name in enumerate(names):
        makers[name](lib)
        if stills:
            _character_still(lib, name, "char_00.png", (10 + 40 * i, 20, 30))
    return movie._character_lib().resolve_cast([(None, name) for name in names])


def _story(tmp, images=IMAGES, story_id="s1", style=STYLE):
    story_dir = os.path.join(tmp, "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    lines = ["# The gate", "", "Two strangers meet at a temple gate.", "", "## Characters",
             '- "the woman in grey": %s.' % seu.DESC_K, '- "the ronin": %s.' % seu.DESC_R, ""]
    for n, image in enumerate(images, start=1):
        lines += ["## Panel %d — Shot %d" % (n, n), "Image: %s" % image]
        if n == 1 and style:
            lines.append("Style: %s" % style)
        lines += ["Motion: The ronin turns his head. The camera stays static.", "Narration: Rain falls.", ""]
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return story_dir


def _args(tmp, members, stills=None, **overrides):
    """Phase args of a shots run of story s1 at 704x448 (stills 1408x896), image seed 3, qwen21-q4 + uncensored."""
    lib = movie._character_lib()
    stills = stills or dict((m.name, os.path.join(lib.character_dir(m.name), "dataset", "stills", "char_00.png"))
                            for m in members)
    values = dict(story_id="s1", seed_image=None, video_width=704, video_height=448, image_seed=3, shots=True,
                  redo_panels=[], cast_members=members, character_strength=0.8, location_pins=[],
                  story_engine="robust", no_auto_lora=True, panels=4, force_story=False, global_stills_loras=[],
                  stills_lora_path=None, cast_refs={"qwen_model": "qwen21-q4", "loras": UNC, "stills": stills})
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(story_dir):
    with open(os.path.join(story_dir, "cast_ref_edits.json"), encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _still(story_dir, n):
    return os.path.join(story_dir, "images", "panel_%02d.png" % n)


def _only(groups):
    return [cmd[cmd.index("--only") + 1] for cmd in groups]


# --- CRT7 (CR4): the option rules --------------------------------------------------------------------------------

def _parse(*extra):
    args = movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))
    args.cast_members = []
    return args


def test_crt7_the_option_rules(cast_env, capsys, monkeypatch):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    args = _parse()
    assert (args.cast_refs_model, args.cast_refs_loras) == (None, None)
    assert movie._resolve_cast_refs(args) == 0 and args.cast_refs is None
    assert capsys.readouterr() == ("", "")
    cases = [(("--cast-refs-lora", "uncensored=1"),
              "Error: --cast-refs-lora needs --cast-refs-model\n"),
             (("--cast-refs-model", "qwen21-q4"),
              "Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters\n"),
             (("--cast-refs-model", "qwen21-q4", "--no-stills"),
              "Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters\n"),
             (("--shots", "--seed-image", seed, "--cast-refs-model", "qwen21-q4"),
              "Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is "
              "already a Qwen edit of the seed\n"),
             (("--shots", "--cast-refs-model", "as-is"),
              "Error: --cast-refs-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-bf16\n"),
             (("--shots", "--cast-refs-model", "qwen2511-q4"),
              "Error: --cast-refs-model qwen2511-q4 is refused: " + qwen_edit.MULTI_REFERENCE_REFUSED["qwen2511-q4"]
              + "\n"),
             (("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "x=1"),
              "Error: --cast-refs-lora: unknown LoRA x; known: uncensored, viggle-turbo\n")]
    for extra, text in cases:
        args = _parse(*extra)
        assert movie._resolve_cast_refs(args) == 2, extra
        assert capsys.readouterr() == ("", text), extra
        assert args.cast_refs is None
    assert movie.main(["n", "--story-id", "s1", "--shots", "--no-stills", "--cast-refs-model", "qwen21-q4",
                       "--dry-run"]) == 2
    assert capsys.readouterr().err == ("Error: --shots needs Phase 2's per-panel stills; it cannot be combined with "
                                       "--no-stills\n")
    members = _cast(lib)
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4")
    args.cast_members = members[:1]
    assert movie._resolve_cast_refs(args) == 0 and args.cast_refs is None
    assert capsys.readouterr() == (
        "note: --cast-refs-model has no effect: it needs at least two cast characters (--character or --cast), and "
        "this run casts 1; every still is a Z-Image still\n", "")
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "uncensored=1", "--dry-run")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 0
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert args.cast_refs == {"qwen_model": "qwen21-q4", "loras": UNC, "stills": {"kyra": k00, "ronin": r00}}
    out = capsys.readouterr().out.splitlines()
    assert out == ["note: --cast-refs-model: character %s has no kept medium-shot dataset still (char_09.png); its "
                   "reference still %s is used, which may show only the head and shoulders, so its clothing rests "
                   "on the Image: text" % (name, path) for name, path in (("kyra", k00), ("ronin", r00))]
    assert fake.calls["selection_problem"] == []
    monkeypatch.setattr(fake, "selection_problem", lambda model_id, loras: fake.calls["selection_problem"].append(
        (model_id, loras)) or "Qwen-Image-2.1 q4 is unavailable: no mflux venv")
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--cast-refs-lora", "uncensored=1")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 2 and args.cast_refs is None
    assert capsys.readouterr().err == ("Error: --cast-refs-model qwen21-q4: Qwen-Image-2.1 q4 is unavailable: no "
                                       "mflux venv\n")
    assert fake.calls["selection_problem"] == [("qwen21-q4", UNC)]
    os.remove(r00)
    args = _parse("--shots", "--cast-refs-model", "qwen21-q4", "--dry-run")
    args.cast_members = members
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == (
        "Error: --cast-refs-model: character ronin has no reference still (looked for %s); rebuild its dataset with "
        "bin/character create ronin --regenerate\n" % r00)
    shutil.copyfile(k00, r00)
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == (
        "Error: --cast-refs-model: characters kyra and ronin have the same reference still bytes (%s); each picture "
        "must show a different person\n" % r00)
    monkeypatch.setattr(movie, "WS", tmp)
    assert movie._resolve_cast_refs(args) == 2
    assert capsys.readouterr().err == ("Error: --cast-refs-model needs %s, which this workspace does not have\n"
                                       % os.path.join(tmp, "qwen_edit.py"))


# --- CRT8 (CR6): the reference picture: the kept medium-shot still, else the dataset reference ---------------

def test_crt8_the_reference_picture(cast_env, capsys):
    lib = cast_env["lib"]
    kyra = _cast(lib, names=("kyra",))[0]
    k00 = os.path.join(lib, "kyra", "dataset", "stills", "char_00.png")
    k09 = _character_still(lib, "kyra", "char_09.png", (0, 0, 250))
    standing = {"n": 9, "kept": True, "gen_prompt": "Medium shot of a woman, standing with arms relaxed, in a studio"}
    edit = {"n": 9, "kept": True, "gen_prompt": "Show this exact same person ... Re-shoot them as a medium shot, "
                                                "standing with arms relaxed, in a studio with a plain grey backdrop."}
    for item9 in (standing, edit):
        _manifest(lib, "kyra", item9)
        assert movie._cast_ref_still(kyra) == (k09, None)
        assert capsys.readouterr() == ("", "")
    for item9 in (dict(standing, kept=False), dict(standing, gen_prompt="Close-up of a woman, in profile facing right"),
                  dict(standing, n=17), "not an item"):
        _manifest(lib, "kyra", item9)
        assert movie._cast_ref_still(kyra) == (k00, None), item9
        assert "has no kept medium-shot dataset still (char_09.png)" in capsys.readouterr().out
    _manifest(lib, "kyra", standing)
    os.remove(k09)
    assert movie._cast_ref_still(kyra) == (k00, None)
    with open(os.path.join(lib, "kyra", "dataset", "manifest.json"), "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    assert movie._cast_ref_still(kyra) == (k00, None)
    os.remove(k00)
    assert movie._cast_ref_still(kyra) == (None, "character kyra has no reference still (looked for %s); rebuild its "
                                                 "dataset with bin/character create kyra --regenerate" % k00)


# --- CRT9 (CR8): the left/right reading and the prompt -----------------------------------------------------

FIGHT7 = ("The setting is a neon street. The ronin is a lean man wearing a faded indigo haori. The ronin stands left "
          "of center, sword raised, facing right toward the green ogre who is partially visible on the right edge of "
          "the frame, blocking with a fist. The shot is a medium close-up.")


def test_crt9_the_left_right_reading_and_the_prompt(cast_env):
    lib = movie._character_lib()
    side = movie._cast_refs_side
    assert (side(lib, FIGHT7, "the green ogre", "the ronin"), side(lib, FIGHT7, "the ronin", "the green ogre")) == (
        "right", "left")
    assert (side(lib, IMAGES[1], KYRA, RONIN), side(lib, IMAGES[1], RONIN, KYRA)) == ("left", "right")
    for text in (IMAGES[3], "The ronin walks left to right past the woman in grey.",
                 "The ronin stands on the left and turns to the right edge of the road; the woman in grey waits.",
                 "The ronin faces left. The woman in grey faces right."):
        assert side(lib, text, RONIN, KYRA) is None, text
    assert side(lib, "The ronin stands center-left. The woman in grey stands centre right.", RONIN, KYRA) == "left"
    assert side(lib, "The ronin stands center-left. The woman in grey stands centre right.", KYRA, RONIN) == "right"
    members = _cast(cast_env["lib"])
    assert movie._cast_refs_prompt(lib, members, IMAGES[1]) == PREFIX + POSITION + "The new shot: " + IMAGES[1]
    assert movie._cast_refs_prompt(lib, members, IMAGES[3]) == PREFIX + "The new shot: " + IMAGES[3]
    assert movie._cast_refs_prompt(lib, members[::-1], IMAGES[1]).startswith(
        "Make one new film still that shows two different people together. Picture 1, the first input image, shows "
        "the ronin, and Picture 2, the second input image, shows the woman in grey. The ronin keeps exactly")
    assert ("In the new shot the ronin is on the right of the frame and the woman in grey is on the left. The new "
            "shot: ") in movie._cast_refs_prompt(lib, members[::-1], IMAGES[1])


# --- CRT10 (CR9): the plan: which panels, in what order, with what key --------------------------------------

def test_crt10_the_plan(cast_env, capsys):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    members = _cast(lib)
    story_dir = _story(tmp)
    error, plan = movie._cast_refs_plan(_args(tmp, members), fake)
    assert error is None
    assert dict((n, [m.name for m in pair]) for n, pair in plan["pairs"].items()) == {2: ["kyra", "ronin"],
                                                                                      4: ["kyra", "ronin"]}
    assert plan["prompts"] == {2: _prompt(2), 4: _prompt(4)}
    assert (plan["size"], plan["still"], plan["todo"], plan["reuse"], plan["total"]) == (
        (1408, 896), (1408, 896), [2, 4], [], 4)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert plan["keys"][2] == dict(qwen_edit.settings("qwen21-q4", UNC),
                                   sources=[{"name": "kyra", "still": "char_00.png", "sha256": _sha(k00)},
                                            {"name": "ronin", "still": "char_00.png", "sha256": _sha(r00)}],
                                   prompt=_prompt(2), seed=3, width=1408, height=896, still_width=1408,
                                   still_height=896)
    reversed_cast = movie._character_lib().resolve_cast([(None, "ronin"), (None, "kyra")])
    _error, plan = movie._cast_refs_plan(_args(tmp, reversed_cast), fake)
    assert [m.name for m in plan["pairs"][2]] == ["ronin", "kyra"]
    three = _cast(lib, names=("kyra", "ronin", "monk"))
    _story(tmp, images=IMAGES[:3] + ["The ronin, the woman in grey and the old monk share tea."])
    error, plan = movie._cast_refs_plan(_args(tmp, three), fake)
    assert (error, plan) == ("panel 4 of %s names 3 cast characters (kyra, monk, ronin); --cast-refs-model takes "
                             "exactly two per panel" % os.path.join(story_dir, "story.md"), None)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write("# Empty\n")
    assert movie._cast_refs_plan(_args(tmp, members), fake) == ("%s has no panels" % os.path.join(story_dir,
                                                                                                    "story.md"), None)


# --- CRT11 (CR10, CR11): Phase 2: Z-Image groups without the cast-reference panels, then one Qwen batch ------

def test_crt11_phase_2_splits_the_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["=== Phase 2: stills ===", LORA_NOTE % "2,4"]
    assert sorted(_only(groups)) == ["1", "3"] and all("--shots" in cmd for cmd in groups)
    (call,) = fake.calls["run_jobs"]
    work = os.path.join(story_dir, "cast_ref_edits")
    assert (call["model_id"], call["loras"], call["size"], call["skill"], call["work_dir"], call["noun"]) == (
        "qwen21-q4", UNC, (1408, 896), "ltx_movie_cast_ref_edit", work, "panel")
    assert fake.logs == [os.path.join(work, "child.log")]
    assert call["jobs"] == [{"n": n, "seed": 3, "prompt": _prompt(n), "source": k00, "sources": [k00, r00],
                             "stage_path": os.path.join(work, "panel_%02d.pending.png" % n),
                             "output_path": os.path.join(work, "panel_%02d.png" % n)} for n in (2, 4)]
    assert fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    for n in (1, 2, 3, 4):
        with Image.open(_still(story_dir, n)) as img:
            assert img.size == (1408, 896)
            assert img.getpixel((5, 5)) == ((200, 0, 0) if n in (1, 3) else (0, 0, 40 * n))
    record = _record(story_dir)
    assert record["schema"] == "ltx-movie.cast-ref-edits.v1"
    assert [list(e) for e in record["panels"]] == [ENTRY_KEYS, ENTRY_KEYS]
    for entry, n in zip(record["panels"], (2, 4)):
        assert (entry["n"], entry["status"], entry["label"], entry["prompt"], entry["seed"], entry["output"],
                entry["still"], entry["still_sha256"], entry["seconds"], entry["error"]) == (
            n, "ok", "Qwen-Image-2.1 q4", _prompt(n), 3, "cast_ref_edits/panel_%02d.png" % n,
            "images/panel_%02d.png" % n, _sha(_still(story_dir, n)), 12.5, None)
        assert entry["sources"] == [{"name": "kyra", "still": "char_00.png", "sha256": _sha(k00)},
                                    {"name": "ronin", "still": "char_00.png", "sha256": _sha(r00)}]
        assert entry["source_paths"] == [k00, r00]
    assert "cast refs: panel 2: Picture 1 kyra (%s), Picture 2 ronin (%s)" % (k00, r00) in out
    assert out[-3:] == ["panel 2 -> %s (cast-reference Qwen edit, 12.5s)" % _still(story_dir, 2),
                        "panel 4 -> %s (cast-reference Qwen edit, 12.5s)" % _still(story_dir, 4),
                        "cast refs: 2 panel stills written"]


# --- CRT12 (CR9): a rerun edits exactly the changed panels --------------------------------------------------

def test_crt12_a_rerun_edits_exactly_the_changed_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    assert movie.phase2_stills(_args(tmp, members)) == 0
    capsys.readouterr()
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out
    assert len(fake.calls["run_jobs"]) == 1 and len(fake.calls["wait_for_memory"]) == 1 and len(groups) == 2
    assert ("cast refs: reusing the stills of panels 2,4 (recorded edits of the same pictures, prompt, seed and "
            "settings)\ncast refs: every cast-reference panel's still is a recorded edit of the same pictures, "
            "prompt, seed and settings; nothing to edit\n") in out
    _story(tmp, images=IMAGES[:3] + [IMAGES[3] + " Lanterns glow."])
    assert movie.phase2_stills(_args(tmp, members)) == 0
    assert [[j["n"] for j in c["jobs"]] for c in fake.calls["run_jobs"]] == [[2, 4], [4]]
    (moved,) = glob.glob(os.path.join(story_dir, "redo", "*", "images", "panel_04.png"))
    assert "cast refs: moved %s -> %s (not a recorded cast-reference edit" % (_still(story_dir, 4), moved) in (
        capsys.readouterr().out)
    assert movie.phase2_stills(_args(tmp, members, redo_panels=[2])) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2]
    _character_still(lib, "ronin", "char_00.png", (99, 99, 99))
    assert movie.phase2_stills(_args(tmp, members)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2, 4]
    q8 = dict(_args(tmp, members).cast_refs, qwen_model="qwen21-q8", loras=[])
    assert movie.phase2_stills(_args(tmp, members, cast_refs=q8)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2, 4]
    Image.new("RGB", (1408, 896), (1, 2, 3)).save(_still(story_dir, 2))
    assert movie.phase2_stills(_args(tmp, members, cast_refs=q8)) == 0
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [2]
    assert len(groups) == 2


# --- CRT13 (CR10): a blocked or failed panel fails the phase after the batch; no Z-Image fallback ---------------

def test_crt13_blocked_and_failed_panels(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    fake.outcomes = {4: "blocked"}
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert capsys.readouterr().err == (
        "Error: the content screen blocked the cast-reference Qwen edit (Qwen-Image-2.1 q4) of panels 4 of story s1; "
        "the movie stops here rather than use an unscreened or Z-Image still. Change those panels' Image: lines in "
        "%s, then rerun: every other panel's still is reused\n" % os.path.join(story_dir, "story.md"))
    assert [os.path.isfile(_still(story_dir, n)) for n in (1, 2, 3, 4)] == [True, True, True, False]
    assert sorted(_only(groups)) == ["1", "3"]
    assert [(e["n"], e["status"], e["still"]) for e in _record(story_dir)["panels"]] == [
        (2, "ok", "images/panel_02.png"), (4, "blocked", None)]
    fake.reset()
    fake.outcomes, fake.failure = {4: "stop"}, "Qwen-Image-2.1 q4 child timed out after 7200 s"
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert capsys.readouterr().err == ("Error: the cast-reference edits failed: Qwen-Image-2.1 q4 child timed out "
                                       "after 7200 s (kept: 2; edited on the next run: 4)\n")
    assert [(e["n"], e["status"], e["error"]) for e in _record(story_dir)["panels"]] == [
        (2, "ok", None), (4, "failed", "Qwen-Image-2.1 q4 child timed out after 7200 s")]
    assert not os.path.exists(_still(story_dir, 4))
    fake.reset()
    fake.wait_error = qwen_edit.Unavailable("only 3.0 GiB available after waiting 600 s; Qwen-Image-2.1 q4 needs 20 "
                                            "GiB; free memory and retry")
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert "Error: the cast-reference edits failed: only 3.0 GiB" in capsys.readouterr().err
    fake.reset()
    os.remove(_still(story_dir, 1))
    cast_env["groups_rc"][0] = 1
    assert movie.phase2_stills(_args(tmp, members)) == 1
    assert "Error: ltx-story-images exited nonzero for 1 of 2 stills groups:" in capsys.readouterr().err
    assert [j["n"] for j in fake.calls["run_jobs"][-1]["jobs"]] == [4]
    assert os.path.isfile(_still(story_dir, 4))


# --- CRT14 (CR10): no two-character panel means the plain Z-Image Phase 2 ------------------------------------

def test_crt14_no_cast_reference_panel(cast_env, capsys):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp, images=[IMAGES[0], IMAGES[2], IMAGES[0], IMAGES[2]])
    assert movie.phase2_stills(_args(tmp, members)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["=== Phase 2: stills ===", "note: cast refs: no panel's Image: names two cast characters; "
                                                  "every still is a Z-Image still"]
    assert sorted(_only(groups)) == ["1,3", "2,4"]
    assert fake.calls["run_jobs"] == [] and not os.path.exists(os.path.join(story_dir, "cast_ref_edits.json"))


# --- CRT15 (CR14): without the flag, Phase 2 and the record helpers are unchanged ------------------------------

def test_crt15_without_the_flag_nothing_changes(cast_env, capsys, monkeypatch):
    tmp, lib, fake, groups = cast_env["tmp"], cast_env["lib"], cast_env["fake"], cast_env["groups"]
    members = _cast(lib)
    story_dir = _story(tmp)
    seen = []
    real = movie._phase2_shots
    monkeypatch.setattr(movie, "_phase2_shots", lambda *a, **k: seen.append((len(a), k)) or real(*a, **k))
    assert movie.phase2_stills(_args(tmp, members, cast_refs=None)) == 0
    assert seen == [(2, {})]
    assert sorted(_only(groups)) == ["1", "2,4", "3"]
    assert fake.calls == {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
    assert not os.path.exists(os.path.join(story_dir, "cast_ref_edits"))
    built = [(("kyra",), [1]), (("kyra", "ronin"), [2, 4])]
    assert movie._exclude_groups(built, ()) is built
    assert movie._exclude_groups(built, [2]) == [(("kyra",), [1]), (("kyra", "ronin"), [4])]
    assert movie._exclude_groups(built, [2, 4]) == [(("kyra",), [1])]
    path = os.path.join(tmp, "r.json")
    movie._write_shots_seed_record(path, {1: {"n": 1}}, 3)
    assert movie._shots_seed_entries(path) == {1: {"n": 1}} and movie._shots_seed_entries(
        path, movie.CAST_REFS_SCHEMA) == {}
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["schema"] == "ltx-movie.seed-edits.v1"


# --- CRT16 (CR12): the dry run ----------------------------------------------------------------------------------

def _dry(capsys, *extra):
    rc = movie.main(["a narrative", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora", "--shots",
                     "--panels", "4", "--character", "kyra", "--character", "ronin"] + list(extra))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    return captured.out.splitlines()


def test_crt16_the_dry_run(cast_env, capsys):
    tmp, lib, fake = cast_env["tmp"], cast_env["lib"], cast_env["fake"]
    _cast(lib)
    story_dir = os.path.join(tmp, "stories", "s1")
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    plain = _dry(capsys)
    lines = _dry(capsys, "--cast-refs-model", "qwen21-q4")
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 1] == (
        "Would edit every panel whose Image: names two cast characters with %s at 1408x896, seed 0, in one Qwen "
        "child: Picture 1 and Picture 2 are the two characters' reference stills in cast order (kyra %s; ronin %s); "
        "each panel is prompted by the cast-reference instruction and its own Image: text (and the Style: text), "
        "screened with content safety (skill ltx_movie_cast_ref_edit) and recorded in %s. No Z-Image stills LoRA "
        "applies to those panels; a blocked or failed one stops the run after the batch. Every other panel is a "
        "Z-Image still:" % (qwen_edit.generator_text("qwen21-q4", []), k00, r00,
                            os.path.join(story_dir, "cast_ref_edits.json")))
    assert lines[i + 2] == "Cast-reference panels: decided at Phase 2, from story.md after Phase 1"
    j = plain.index("--- Phase 2: stills ---")
    assert lines[i + 3:i + 5] == plain[j + 1:j + 3]
    assert [line for line in lines if line not in plain and not line.startswith("note: --cast-refs-model")] == \
        lines[i + 1:i + 3]
    _story(tmp)
    members = movie._character_lib().resolve_cast([(None, "kyra"), (None, "ronin")])
    args = _args(tmp, members, image_seed=0, cast_refs={"qwen_model": "qwen21-q4", "loras": [],
                                                        "stills": {"kyra": k00, "ronin": r00}})
    _error, plan = movie._cast_refs_plan(args, fake)
    assert movie._phase2_cast_refs_batch(args, fake, plan) == 0
    _story(tmp, images=IMAGES[:3] + [IMAGES[3] + " Lanterns glow."])
    capsys.readouterr()
    lines = _dry(capsys, "--cast-refs-model", "qwen21-q4")
    i = lines.index("--- Phase 2: stills ---")
    assert lines[i + 2] == "Cast-reference panels: 2 (kyra, ronin); 4 (kyra, ronin); to edit: 4; reused: 2"
    groups = lines[i + 3:lines.index("", i)]
    assert [line for line in groups if line.startswith("stills group ")] == [
        "stills group 1/2 (kyra; panels 1)", "stills group 2/2 (ronin; panels 3)"]
    assert len(fake.calls["run_jobs"]) == 1 and fake.calls["selection_problem"] == []


# --- CRT17 (CR13): the help texts and the docstring paragraph ------------------------------------------------

HELP = {
    "--cast-refs-model": (
        "a test option for --shots without --seed-image: every panel whose Image: names two cast characters "
        "(--character/--cast) is rendered by this Qwen registry edit model (qwen21-q4, qwen21-q8, qwen21-bf16, "
        "qwen2511-bf16; qwen2511-q4 is refused) with the two characters' reference stills as Picture 1 and Picture "
        "2, instead of Z-Image with both stills LoRAs; screened with content safety and recorded in "
        "cast_ref_edits.json. Every other panel is unchanged. See docs/superpowers/specs/"
        "2026-11-09-shots-multi-reference-stills-design.md."),
    "--cast-refs-lora": ("with --cast-refs-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                         "(repeatable); none listed means no LoRA")}
DOC = ("Cast references (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md), a test option: "
       "in shots mode without --seed-image, --cast-refs-model ID renders every panel whose Image: names two cast "
       "characters as one Qwen edit with both characters' reference stills as Picture 1 and Picture 2, instead of "
       "Z-Image with both stills LoRAs (which blends the two people); one child for all of them, screened, recorded "
       "in cast_ref_edits.json and reused on a rerun when nothing changed. Every other panel is unchanged. Absent, "
       "Phase 2 is unchanged.")


def test_crt17_the_help_texts_and_the_docstring():
    actions = dict((a.option_strings[0], a) for a in movie.build_parser()._actions if a.option_strings)
    for flag, text in HELP.items():
        assert actions[flag].help == text, flag
    assert " ".join(movie.__doc__.split()).endswith(DOC)
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        assert "\nimport re\n" not in f.read()


# --- CRT18 (CR3, CR10): the real runner: one child, both sources, every output screened ---------------------

def test_crt18_the_real_runner(env, monkeypatch):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [4]})
    tmp, mp = env["tmp"], env["mp"]
    lib = os.path.join(tmp, "characters")
    os.makedirs(lib)
    mp.setenv("CHARACTER_LIBRARY_DIR", lib)
    mp.setattr(movie, "_qwen_edit", lambda: qwen_edit)
    mp.setattr(movie, "_story_dir", lambda story_id: os.path.join(tmp, "stories", story_id))
    members = _cast(lib)
    story_dir = _story(tmp)
    k00, r00 = (os.path.join(lib, name, "dataset", "stills", "char_00.png") for name in ("kyra", "ronin"))
    args = _args(tmp, members)
    _error, plan = movie._cast_refs_plan(args, qwen_edit)
    assert movie._phase2_cast_refs_batch(args, qwen_edit, plan) == 1
    (call,) = st.stub_calls(py)
    assert [(j["n"], j["prompt"], j["source"], j["sources"]) for j in call["spec"]["jobs"]] == [
        (n, _prompt(n), k00, [k00, r00]) for n in (2, 4)]
    assert (call["spec"]["width"], call["spec"]["height"]) == (1408, 896)
    assert env["calls"]["safety"] == [{"skill": "ltx_movie_cast_ref_edit", "prompt": _prompt(n), "size": (1408, 896)}
                                      for n in (2, 4)]
    assert [e["status"] for e in _record(story_dir)["panels"]] == ["ok", "blocked"]
    assert os.path.isfile(os.path.join(story_dir, "cast_ref_edits", "child.log"))
    stub = st.qwenedit_stub(env, {"blocked": []})
    with open(stub, "w", encoding="utf-8") as f:
        f.write(PANEL_QWENEDIT_STUB)
    _bf16_cache(env)
    mp.setattr(qwen_edit, "avail_gib", lambda: 80.0)
    args = _args(tmp, members, cast_refs={"qwen_model": "qwen2511-bf16", "loras": [],
                                          "stills": {"kyra": k00, "ronin": r00}})
    _error, plan = movie._cast_refs_plan(args, qwen_edit)
    assert plan["todo"] == [2, 4]
    assert movie._phase2_cast_refs_batch(args, qwen_edit, plan) == 0
    (call,) = st.stub_calls(stub)
    assert [j["images"] for j in call["spec"]["jobs"]] == [[k00, r00], [k00, r00]]
    assert call["spec"]["skill"] == "ltx_movie_cast_ref_edit"
```

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_cast_refs.py 2>&1 | tail -1` prints `12 failed, ...` (AttributeError on the new functions or flags, and `SystemExit: 2` for CRT16's unknown flag).

- [ ] **Step 3: Fifteen Edits** (M1-M15 to `bin/ltx-movie`). Apply them in order: M11 and M12 both edit `_print_shots_stills_plan`, and M10's Old text (`def _redo_moves(args, archive):`) and M13's (`def _print_dry_run_plan(args):`) are single anchor lines. Each Old text occurs exactly once at the time it is applied.

**M1** (`bin/ltx-movie`). Old:
```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.
"""
```
New:
```python
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.

Cast references (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md), a test option: in
shots mode without --seed-image, --cast-refs-model ID renders every panel whose Image: names two cast characters
as one Qwen edit with both characters' reference stills as Picture 1 and Picture 2, instead of Z-Image with both
stills LoRAs (which blends the two people); one child for all of them, screened, recorded in cast_ref_edits.json
and reused on a rerun when nothing changed. Every other panel is unchanged. Absent, Phase 2 is unchanged.
"""
```

**M2** (`bin/ltx-movie`). Old:
```python
SHOTS_SEED_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply "
                        "to Qwen edits; every panel's still is edited without them")
```
New:
```python
SHOTS_SEED_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location and catalog stills LoRAs) do not apply "
                        "to Qwen edits; every panel's still is edited without them")
# Cast references (docs/superpowers/specs/2026-11-09-shots-multi-reference-stills-design.md, CR5), a test option: in
# shots mode without a seed image, a panel whose Image: names two cast characters is one Qwen edit with both
# characters' reference stills as Picture 1 and Picture 2.
CAST_REFS_SKILL = "ltx_movie_cast_ref_edit"
CAST_REFS_SCHEMA = "ltx-movie.cast-ref-edits.v1"
CAST_REFS_EDIT_PREFIX = (
    "Make one new film still that shows two different people together. Picture 1, the first input image, shows "
    "%(a)s, and Picture 2, the second input image, shows %(b)s. %(A)s keeps exactly the face, hair, skin tone, "
    "build and clothing from Picture 1, and %(b)s keeps exactly the face, hair, skin tone, build and clothing "
    "from Picture 2; never swap or mix their faces, colours or clothing. Take only these two people from the "
    "pictures, not their pose, background, lighting or framing. %(position)sThe new shot: ")
CAST_REFS_POSITION = "In the new shot %s is on the %s of the frame and %s is on the %s. "
CAST_REFS_SIDE_PATTERN = (r"\b(?:on|at|in) the (left|right)\b|\b(left|right) (?:of|side|edge|half)\b"
                          r"|\bcent(?:er|re)[- ](left|right)\b")
CAST_REFS_STOP_PATTERN = r"[.!?;]"
CAST_REFS_FULL_STILL = "char_09.png"
CAST_REFS_FULL_WORDS = ("medium shot", "standing with arms relaxed")
CAST_REFS_NOOP_NOTE = ("note: --cast-refs-model has no effect: it needs at least two cast characters (--character or "
                       "--cast), and this run casts %d; every still is a Z-Image still")
CAST_REFS_FALLBACK_NOTE = ("note: --cast-refs-model: character %s has no kept medium-shot dataset still (%s); its "
                           "reference still %s is used, which may show only the head and shoulders, so its clothing "
                           "rests on the Image: text")
CAST_REFS_NONE_NOTE = ("note: cast refs: no panel's Image: names two cast characters; every still is a Z-Image "
                       "still")
CAST_REFS_LORA_NOTE = ("note: Z-Image stills LoRAs (character, location, catalog and --stills-lora) do not apply to "
                       "the cast-reference panels %s: they are Qwen edits of the two characters' reference stills; "
                       "every other panel keeps its Z-Image stills LoRAs")
```

**M3** (`bin/ltx-movie`). Old:
```python
                              "<story>/redo/<stamp>-<pid>/ and re-render only those panels; "
                              "every other panel is reused")
```
New:
```python
                              "<story>/redo/<stamp>-<pid>/ and re-render only those panels; "
                              "every other panel is reused")
    parser.add_argument("--cast-refs-model", dest="cast_refs_model", default=None, metavar="ID",
                         help="a test option for --shots without --seed-image: every panel whose Image: names two "
                              "cast characters (--character/--cast) is rendered by this Qwen registry edit model "
                              "(qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-bf16; qwen2511-q4 is refused) with the "
                              "two characters' reference stills as Picture 1 and Picture 2, instead of Z-Image with "
                              "both stills LoRAs; screened with content safety and recorded in cast_ref_edits.json. "
                              "Every other panel is unchanged. See docs/superpowers/specs/"
                              "2026-11-09-shots-multi-reference-stills-design.md.")
    parser.add_argument("--cast-refs-lora", dest="cast_refs_loras", action="append", default=None,
                         metavar="ID=SCALE",
                         help="with --cast-refs-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
```

**M4** (`bin/ltx-movie`). Old:
```python
    args.seed_edit = {"qwen_model": model_id, "loras": clean}
    return 0
```
New:
```python
    args.seed_edit = {"qwen_model": model_id, "loras": clean}
    return 0


def _cast_ref_still(member):
    """(path, error) of a cast member's reference picture for --cast-refs-model (cast refs spec CR6), derived from
    its character directory, never from the absolute paths inside character.json: dataset/stills/char_09.png (the
    medium shot standing with arms relaxed, which shows the clothing) when dataset/manifest.json lists still 9 as
    kept with a generation prompt naming both CAST_REFS_FULL_WORDS; else the dataset reference still
    dataset/stills/<dataset.reference>.png (char_00, the seed cropped around the face, or char_01, a close-up), after
    CAST_REFS_FALLBACK_NOTE. error is the text of an Error: line when neither file exists, else None."""
    lib = _character_lib()
    stills_dir = os.path.join(lib.character_dir(member.name), "dataset", "stills")
    full = os.path.join(stills_dir, CAST_REFS_FULL_STILL)
    try:
        with open(os.path.join(os.path.dirname(stills_dir), "manifest.json"), encoding="utf-8") as f:
            items = json.load(f).get("items")
    except (OSError, ValueError, AttributeError):
        items = None
    for item in items if isinstance(items, list) else []:
        if (isinstance(item, dict) and item.get("n") == 9 and item.get("kept") is True
                and all(w in str(item.get("gen_prompt") or "").lower() for w in CAST_REFS_FULL_WORDS)
                and os.path.isfile(full)):
            return full, None
    path = os.path.join(stills_dir, "%s.png" % lib.load_character(member.name)["dataset"]["reference"])
    if not os.path.isfile(path):
        return None, ("character %s has no reference still (looked for %s); rebuild its dataset with bin/character "
                      "create %s --regenerate" % (member.name, path, member.name))
    print(CAST_REFS_FALLBACK_NOTE % (member.name, CAST_REFS_FULL_STILL, path))
    return path, None


def _resolve_cast_refs(args):
    """--cast-refs-model/--cast-refs-lora (cast refs spec CR4): sets args.cast_refs to None (off, or a no-op with fewer
    than two cast characters) or {"qwen_model": ID, "loras": [{"id", "scale"}], "stills": {name: path}}. Returns 0,
    or 2 after one Error: line. A dry run and --story-only read no weights."""
    model, loras = args.cast_refs_model, args.cast_refs_loras
    args.cast_refs = None
    if model is None:
        if loras is not None:
            print("Error: --cast-refs-lora needs --cast-refs-model", file=sys.stderr)
            return 2
        return 0
    if not args.shots:
        print("Error: --cast-refs-model needs --shots: it renders the shots stills that show two cast characters",
              file=sys.stderr)
        return 2
    if getattr(args, "seed_image", None):
        print("Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still "
              "is already a Qwen edit of the seed", file=sys.stderr)
        return 2
    path = os.path.join(WS, "qwen_edit.py")
    if not os.path.isfile(path):
        print("Error: --cast-refs-model needs %s, which this workspace does not have" % path, file=sys.stderr)
        return 2
    qe = _qwen_edit()
    if model not in qe.MODEL_IDS:
        print("Error: --cast-refs-model must be one of %s" % ", ".join(qe.MULTI_REFERENCE_MODEL_IDS),
              file=sys.stderr)
        return 2
    if qe.multi_reference_problem(model) is not None:
        print("Error: --cast-refs-model %s is refused: %s" % (model, qe.multi_reference_problem(model)),
              file=sys.stderr)
        return 2
    try:
        model_id, clean = qe.cli_selection(model, loras, "--cast-refs-model", "--cast-refs-lora")
    except qe.SelectionError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    members = getattr(args, "cast_members", None) or []
    if len(members) < 2:
        print(CAST_REFS_NOOP_NOTE % len(members))
        return 0
    stills, seen = {}, {}
    for m in members:
        still, error = _cast_ref_still(m)
        if error is not None:
            print("Error: --cast-refs-model: %s" % error, file=sys.stderr)
            return 2
        digest = _sha256_file(still)
        if digest in seen:
            print("Error: --cast-refs-model: characters %s and %s have the same reference still bytes (%s); each "
                  "picture must show a different person" % (seen[digest], m.name, still), file=sys.stderr)
            return 2
        seen[digest] = m.name
        stills[m.name] = still
    if not args.dry_run and not args.story_only:
        problem = qe.selection_problem(model_id, clean)
        if problem is not None:
            print("Error: --cast-refs-model %s: %s" % (model_id, problem), file=sys.stderr)
            return 2
    args.cast_refs = {"qwen_model": model_id, "loras": clean, "stills": stills}
    return 0
```

**M5** (`bin/ltx-movie`). Old:
```python
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```
New:
```python
    if getattr(args, "shots", False):
        if getattr(args, "cast_refs", None):
            return _phase2_shots_cast_refs(args, cmd)   # cast refs CR10: two-character panels are Qwen edits
        return _phase2_shots(args, cmd)
```

**M6** (`bin/ltx-movie`). Old:
```python
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```
New:
```python
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]


def _exclude_groups(groups, exclude):
    """groups without the panels in exclude, leaving out a group that has none left (cast refs spec CR11); groups
    itself when exclude is empty."""
    if not exclude:
        return groups
    kept = [(names, [i for i in panels if i not in exclude]) for names, panels in groups]
    return [(names, panels) for names, panels in kept if panels]
```

**M7** (`bin/ltx-movie`). Old:
```python
def _phase2_shots(args, cmd):
    """Phase 2 in shots mode (shots spec 5.5): one bin/ltx-story-images run per stills-LoRA group,
    each the Phase 2 cmd with --only <the group's panels> and --shots appended, teed to
    images/stills-group-KK.log. A group with no missing still is skipped. A failing group does
    not stop the rest: every group runs, then one error lists each failed group and Phase 2
    returns 1. Stills already written are kept."""
    paths = _story_paths(args.story_id)
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [],
                                  getattr(args, "location_pins", None) or [])
```
New:
```python
def _phase2_shots(args, cmd, exclude=()):
    """Phase 2 in shots mode (shots spec 5.5): one bin/ltx-story-images run per stills-LoRA group,
    each the Phase 2 cmd with --only <the group's panels> and --shots appended, teed to
    images/stills-group-KK.log. A group with no missing still is skipped. A failing group does
    not stop the rest: every group runs, then one error lists each failed group and Phase 2
    returns 1. Stills already written are kept. The panels in exclude (the cast-reference
    panels, cast refs spec CR11) are left out of every group."""
    paths = _story_paths(args.story_id)
    groups = _exclude_groups(_shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [],
                                                  getattr(args, "location_pins", None) or []), exclude)
```

**M8** (`bin/ltx-movie`). Old:
```python
def _shots_seed_entries(record_path):
    """{n: entry} of seed_edits.json (shots seed edits spec SE12), or {} when it is missing, unreadable or not
    this schema."""
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return {}
    if not (isinstance(record, dict) and record.get("schema") == SHOTS_SEED_EDITS_SCHEMA
```
New:
```python
def _shots_seed_entries(record_path, schema=SHOTS_SEED_EDITS_SCHEMA):
    """{n: entry} of seed_edits.json (shots seed edits spec SE12), or {} when it is missing, unreadable or not
    this schema (cast_ref_edits.json with CAST_REFS_SCHEMA, cast refs spec CR9)."""
    try:
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return {}
    if not (isinstance(record, dict) and record.get("schema") == schema
```

**M9** (`bin/ltx-movie`). Old:
```python
def _write_shots_seed_record(path, entries, total):
    """seed_edits.json with the entries of panels 1..total in panel order, written atomically (SE12)."""
    _write_seed_edit_record(path, {"schema": SHOTS_SEED_EDITS_SCHEMA,
```
New:
```python
def _write_shots_seed_record(path, entries, total, schema=SHOTS_SEED_EDITS_SCHEMA):
    """seed_edits.json (or, with CAST_REFS_SCHEMA, cast_ref_edits.json) with the entries of panels 1..total in panel
    order, written atomically (SE12; cast refs spec CR9)."""
    _write_seed_edit_record(path, {"schema": schema,
```

**M10** (`bin/ltx-movie`). Old:
```python
def _redo_moves(args, archive):
```
New:
```python
def _cast_refs_paths(story_dir):
    """The cast-reference edits' files in the story directory (cast refs spec CR9)."""
    return {"record": os.path.join(story_dir, "cast_ref_edits.json"),
            "work": os.path.join(story_dir, "cast_ref_edits")}


def _cast_refs_side(lib, text, phrase, other):
    """"left" or "right" when text puts phrase on one side of the frame, else None (cast refs spec CR8): the first
    occurrence of phrase whose words, up to the next mention of either phrase or the next . ! ? or ;, name screen
    positions (CAST_REFS_SIDE_PATTERN) of exactly one side."""
    import re
    mine, theirs, stop = lib._phrase_regex(phrase), lib._phrase_regex(other), re.compile(CAST_REFS_STOP_PATTERN)
    for match in mine.finditer(text):
        ends = [m.start() for m in (mine.search(text, match.end()), theirs.search(text, match.end()),
                                     stop.search(text, match.end())) if m]
        segment = text[match.end():min(ends) if ends else len(text)]
        sides = set(next(g for g in m.groups() if g).lower()
                    for m in re.finditer(CAST_REFS_SIDE_PATTERN, segment, re.IGNORECASE))
        if len(sides) == 1:
            return sides.pop()
    return None


def _cast_refs_prompt(lib, pair, text):
    """A cast-reference panel's edit prompt (cast refs spec CR8): CAST_REFS_EDIT_PREFIX with pair[0] as Picture 1 and
    pair[1] as Picture 2, plus CAST_REFS_POSITION when text puts them on different sides, then text (the panel's
    Image: text joined with the Style: text). No LoRA trigger word is inserted."""
    a, b = pair[0].phrase, pair[1].phrase
    sides = (_cast_refs_side(lib, text, a, b), _cast_refs_side(lib, text, b, a))
    position = CAST_REFS_POSITION % (a, sides[0], b, sides[1]) if None not in sides and sides[0] != sides[1] else ""
    return CAST_REFS_EDIT_PREFIX % {"a": a, "b": b, "A": a[:1].upper() + a[1:], "position": position} + text


def _cast_refs_plan(args, qe):
    """Phase 2's cast-reference plan, read-only (cast refs spec CR9): (error, plan). error is the text of an Error:
    line or None. A cast-reference panel is one whose Image: text, joined with the Style: text, names exactly two
    cast characters (character_lib.cast_text); its pair lists them in cast order. A panel naming three or more is an
    error. plan is {"pairs": {n: [member, member]}, "prompts": {n: prompt}, "size": (W, H), "still": (SW, SH),
    "keys": {n: key}, "entries": {n: entry}, "reuse": [n], "todo": [n], "total": the panel count}. A panel is reused
    iff it is not a --redo panel, its entry is ok with every key item equal, and images/panel_NN.png exists with the
    entry's still_sha256."""
    paths = _story_paths(args.story_id)
    model_id, loras = args.cast_refs["qwen_model"], args.cast_refs["loras"]
    panels = _load_story_panels(paths["story_md"])
    if not panels:
        return "%s has no panels" % paths["story_md"], None
    lib = _character_lib()
    images = importlib.machinery.SourceFileLoader(
        "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
    style = images._style_text(panels)
    members = args.cast_members
    pairs, prompts = {}, {}
    for n, p in enumerate(panels, start=1):
        text = images._compose_prompt(p["image"], style)
        names = lib.cast_text(text, members)[1]
        if len(names) > 2:
            return ("panel %d of %s names %d cast characters (%s); --cast-refs-model takes exactly two per panel"
                    % (n, paths["story_md"], len(names), ", ".join(names))), None
        if len(names) == 2:
            pairs[n] = [m for m in members if m.name in names]
            prompts[n] = _cast_refs_prompt(lib, pairs[n], text)
    still = _still_size(args)
    multiple = qe.multiple(model_id)
    size = (still[0] // multiple * multiple, still[1] // multiple * multiple)
    stills = args.cast_refs["stills"]
    digests = dict((name, _sha256_file(path)) for name, path in stills.items())
    settings = qe.settings(model_id, loras)
    entries = _shots_seed_entries(_cast_refs_paths(paths["story_dir"])["record"], CAST_REFS_SCHEMA)
    redo = set(getattr(args, "redo_panels", None) or [])
    keys, reuse, todo = {}, [], []
    for n in sorted(pairs):
        sources = [{"name": m.name, "still": os.path.basename(stills[m.name]), "sha256": digests[m.name]}
                   for m in pairs[n]]
        keys[n] = dict(settings, sources=sources, prompt=prompts[n], seed=args.image_seed, width=size[0],
                       height=size[1], still_width=still[0], still_height=still[1])
        entry = entries.get(n)
        path = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if (n not in redo and isinstance(entry, dict) and entry.get("status") == "ok"
                and all(k in entry and entry[k] == v for k, v in keys[n].items())
                and os.path.isfile(path) and entry.get("still_sha256") == _sha256_file(path)):
            reuse.append(n)
        else:
            todo.append(n)
    return None, {"pairs": pairs, "prompts": prompts, "size": size, "still": still, "keys": keys,
                  "entries": entries, "reuse": reuse, "todo": todo, "total": len(panels)}


def _phase2_cast_refs_batch(args, qe, plan):
    """The cast-reference edits of plan["todo"] in one qwen_edit.run_jobs batch (cast refs spec CR10): each job's
    sources are its pair's reference stills in cast order; every output is screened with content safety, fitted into
    images/panel_NN.png at the still size and recorded in cast_ref_edits.json. A todo panel's existing still is moved
    aside first. Returns 0 or 1; a blocked or failed panel returns 1 after the batch, with no fallback to Z-Image."""
    paths = _story_paths(args.story_id)
    files = _cast_refs_paths(paths["story_dir"])
    model_id, loras = args.cast_refs["qwen_model"], args.cast_refs["loras"]
    label = qe.label(model_id)
    stills = args.cast_refs["stills"]
    entries, todo, total = plan["entries"], plan["todo"], plan["total"]
    if plan["reuse"]:
        print("cast refs: reusing the stills of panels %s (recorded edits of the same pictures, prompt, seed and "
              "settings)" % _panel_list(plan["reuse"]))
    if not todo:
        print("cast refs: every cast-reference panel's still is a recorded edit of the same pictures, prompt, seed "
              "and settings; nothing to edit")
        return 0
    os.makedirs(paths["images_dir"], exist_ok=True)
    os.makedirs(files["work"], exist_ok=True)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    for n in todo:
        still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        if os.path.lexists(still):
            os.makedirs(archive, exist_ok=True)
            moved = os.path.join(archive, os.path.basename(still))
            os.replace(still, moved)
            print("cast refs: moved %s -> %s (not a recorded cast-reference edit of these pictures, prompt, seed "
                  "and settings)" % (still, moved))
        for name in ("panel_%02d.png" % n, "panel_%02d.pending.png" % n):
            if os.path.lexists(os.path.join(files["work"], name)):
                os.remove(os.path.join(files["work"], name))
        entries.pop(n, None)
    _write_shots_seed_record(files["record"], entries, total, CAST_REFS_SCHEMA)
    fit = _image_fit()
    (width, height), (still_w, still_h) = plan["size"], plan["still"]
    print("cast refs: %s; %dx%d, fitted into %dx%d stills; seed %d; panels %s, each with its two characters' "
          "reference stills as Picture 1 and Picture 2" % (qe.generator_text(model_id, loras), width, height,
                                                           still_w, still_h, args.image_seed, _panel_list(todo)))
    for n in todo:
        print("cast refs: panel %d: Picture 1 %s (%s), Picture 2 %s (%s)"
              % (n, plan["pairs"][n][0].name, stills[plan["pairs"][n][0].name], plan["pairs"][n][1].name,
                 stills[plan["pairs"][n][1].name]))

    def record_entry(n, status, seconds, error_text):
        key = plan["keys"][n]
        ok = status == "ok"
        return {"n": n, "status": status, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "label": label, "sources": key["sources"],
                "source_paths": [os.path.abspath(stills[m.name]) for m in plan["pairs"][n]],
                "prompt": key["prompt"], "seed": key["seed"], "width": key["width"], "height": key["height"],
                "still_width": key["still_width"], "still_height": key["still_height"],
                "qwen_model": key["qwen_model"], "loras": key["loras"], "steps": key["steps"],
                "scheduler": key["scheduler"],
                "output": "cast_ref_edits/panel_%02d.png" % n if ok else None,
                "still": "images/panel_%02d.png" % n if ok else None,
                "still_sha256": (_sha256_file(os.path.join(paths["images_dir"], "panel_%02d.png" % n))
                                 if ok else None),
                "seconds": seconds, "error": error_text}

    def on_result(result):
        n = result["n"]
        if result["status"] == "ok":
            still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
            fit.fit_letterbox(fit.load_oriented_rgb(result["output_path"]), still_w, still_h).save(
                still + ".tmp", format="PNG")
            os.replace(still + ".tmp", still)
            print("panel %d -> %s (cast-reference Qwen edit, %.1fs)" % (n, still, result["seconds"]))
        else:
            print("panel %d BLOCKED: the content screen blocked the cast-reference Qwen edit" % n)
        entries[n] = record_entry(n, result["status"], result["seconds"], None)
        _write_shots_seed_record(files["record"], entries, total, CAST_REFS_SCHEMA)

    jobs = []
    for n in todo:
        sources = [stills[m.name] for m in plan["pairs"][n]]
        jobs.append({"n": n, "seed": args.image_seed, "prompt": plan["prompts"][n], "source": sources[0],
                     "sources": sources, "stage_path": os.path.join(files["work"], "panel_%02d.pending.png" % n),
                     "output_path": os.path.join(files["work"], "panel_%02d.png" % n)})
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, jobs, width, height, CAST_REFS_SKILL, files["work"],
                                       log_path=os.path.join(files["work"], "child.log"), on_result=on_result,
                                       noun="panel")
    except qe.Unavailable as e:
        results, failure = None, str(e)
    status = dict((r["n"], r["status"]) for r in results or [])
    ok = [n for n in todo if status.get(n) == "ok"]
    blocked = [n for n in todo if status.get(n) == "blocked"]
    failed = [n for n in todo if n not in ok and n not in blocked]
    if failed and failure is None:
        failure = "%s reported no result for panels %s" % (label, _panel_list(failed))
    if failed:
        for n in failed:
            entries[n] = record_entry(n, "failed", None, failure)
        _write_shots_seed_record(files["record"], entries, total, CAST_REFS_SCHEMA)
    if failure is not None:
        print("Error: the cast-reference edits failed: %s (kept: %s; edited on the next run: %s)"
              % (failure, _panel_list(sorted(plan["reuse"] + ok)) or "none", _panel_list(sorted(failed + blocked))),
              file=sys.stderr)
    if blocked:
        print("Error: the content screen blocked the cast-reference Qwen edit (%s) of panels %s of story %s; the "
              "movie stops here rather than use an unscreened or Z-Image still. Change those panels' Image: lines in "
              "%s, then rerun: every other panel's still is reused"
              % (label, _panel_list(blocked), args.story_id, paths["story_md"]), file=sys.stderr)
    if failure is not None or blocked:
        return 1
    print("cast refs: %d panel stills written" % len(ok))
    return 0


def _phase2_shots_cast_refs(args, cmd):
    """Phase 2 in shots mode with --cast-refs-model (cast refs spec CR10): the cast-reference panels are Qwen edits
    of their two characters' reference stills (_phase2_cast_refs_batch); every other panel runs the unchanged
    Z-Image stills groups (_phase2_shots without those panels). Both run, the Z-Image groups first; returns 1 when
    either failed. With no cast-reference panel, Phase 2 is exactly _phase2_shots after one note."""
    qe = _qwen_edit()
    error, plan = _cast_refs_plan(args, qe)
    if error is not None:
        print("Error: %s" % error, file=sys.stderr)
        return 1
    if not plan["pairs"]:
        print(CAST_REFS_NONE_NOTE)
        return _phase2_shots(args, cmd)
    multi = sorted(plan["pairs"])
    if (_shots_seed_lora_note(args) or getattr(args, "global_stills_loras", None)
            or getattr(args, "stills_lora_path", None)):
        print(CAST_REFS_LORA_NOTE % _panel_list(multi))
    rc = _phase2_shots(args, cmd, exclude=multi)
    if _phase2_cast_refs_batch(args, qe, plan) != 0 or rc != 0:
        return 1
    return 0


def _redo_moves(args, archive):
```

**M11** (`bin/ltx-movie`). Old:
```python
def _print_shots_stills_plan(args, cmd):
    """Phase 2's dry-run lines in shots mode (shots spec 5.8). Touches nothing."""
```
New:
```python
def _print_shots_stills_plan(args, cmd, exclude=()):
    """Phase 2's dry-run lines in shots mode (shots spec 5.8). Touches nothing. The panels in exclude (the
    cast-reference panels, cast refs spec CR12) are left out of every group."""
```

**M12** (`bin/ltx-movie`). Old:
```python
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [],
                                  getattr(args, "location_pins", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        skip = 
```
New:
```python
    groups = _exclude_groups(_shots_stills_groups(story_md, getattr(args, "cast_members", None) or [],
                                                  getattr(args, "location_pins", None) or []), exclude)
    for k, (names, panels) in enumerate(groups, start=1):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        skip = 
```

**M13** (`bin/ltx-movie`). Old:
```python
def _print_dry_run_plan(args):
```
New:
```python
def _print_cast_refs_plan(args, cmd):
    """Phase 2's dry-run lines in shots mode with --cast-refs-model (cast refs spec CR12). Reads; never writes."""
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    model_id, loras = args.cast_refs["qwen_model"], args.cast_refs["loras"]
    still = _still_size(args)
    multiple = qe.multiple(model_id)
    print("Would edit every panel whose Image: names two cast characters with %s at %dx%d, seed %d, in one Qwen "
          "child: Picture 1 and Picture 2 are the two characters' reference stills in cast order (%s); each panel is "
          "prompted by the cast-reference instruction and its own Image: text (and the Style: text), screened with "
          "content safety (skill %s) and recorded in %s. No Z-Image stills LoRA applies to those panels; a blocked "
          "or failed one stops the run after the batch. Every other panel is a Z-Image still:"
          % (qe.generator_text(model_id, loras), still[0] // multiple * multiple, still[1] // multiple * multiple,
             args.image_seed, "; ".join("%s %s" % (m.name, args.cast_refs["stills"][m.name])
                                        for m in args.cast_members),
             CAST_REFS_SKILL, _cast_refs_paths(paths["story_dir"])["record"]))
    if args.force_story or not os.path.exists(paths["story_md"]):
        print("Cast-reference panels: decided at Phase 2, from story.md after Phase 1")
        _print_shots_stills_plan(args, cmd)
        return
    error, plan = _cast_refs_plan(args, qe)
    if error is not None:
        print("Cast-reference panels: Phase 2 would stop: %s" % error)
        return
    multi = sorted(plan["pairs"])
    print("Cast-reference panels: %s; to edit: %s; reused: %s"
          % ("; ".join("%d (%s)" % (n, ", ".join(m.name for m in plan["pairs"][n])) for n in multi) or "none",
             _panel_list(plan["todo"]) or "none", _panel_list(plan["reuse"]) or "none"))
    _print_shots_stills_plan(args, cmd, exclude=multi)


def _print_dry_run_plan(args):
```

**M14** (`bin/ltx-movie`). Old:
```python
        if getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
```
New:
```python
        if getattr(args, "shots", False) and getattr(args, "cast_refs", None):
            _print_cast_refs_plan(args, phase2_cmd)
        elif getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
```

**M15** (`bin/ltx-movie`). Old:
```python
    rc = _resolve_seed_edit(args)
    if rc:
        return rc
```
New:
```python
    rc = _resolve_seed_edit(args)
    if rc:
        return rc
    rc = _resolve_cast_refs(args)
    if rc:
        return rc
```

No other line of `bin/ltx-movie` changes.

- [ ] **Step 4: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_cast_refs.py tests/test_qwen_edit_cast_refs.py 2>&1 | tail -1   # 18 passed
python3 -B -m pytest -q -p no:cacheprovider tests/test_shots_mode.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_edit.py tests/test_dialogue.py tests/test_casting_pipeline.py tests/test_location_pipeline.py tests/test_movie_ui_builder.py 2>&1 | grep -E '^FAILED|passed|failed'
    # only test_mut26_pipeline_files_are_unchanged fails (expected)
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1      # OK 347/347
git diff --numstat                                             # 423 15 bin/ltx-movie
grep -c "cast_refs" bin/ltx-movie                              # 34
grep -c "^import re$" bin/ltx-movie                            # 0
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' bin/ltx-movie tests/test_ltx_movie_cast_refs.py; done   # compiled 2, twice
zsh $S/mr-baseline/gate-run.sh 2
```
Expected gate output: the summary `3 failed, P0+17 passed, 2 skipped`; `lost 1 (listed 1, unexpected 0); new tests 18, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`.

- [ ] **Step 5: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_cast_refs.py
git diff --cached --name-only | wc -l    # 2
git commit -m "ltx-movie: --cast-refs-model, a test option: in shots mode a panel naming two cast characters is one Qwen edit with both characters' reference stills, recorded in cast_ref_edits.json; every other panel keeps Z-Image (shots-multiref CR4-CR14, CRT7-CRT18)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 3: the `test_mut26` re-baseline (a test-only commit; never amend)

The baseline chain moves from `c339192` (seeded-no-identity) to the Task 2 commit.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/ltx-movie character_dataset.py); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only c33919221ea8ae8fd7811c74e587c2cbccafc4be $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected: a 40-hex `SHA`; `SHA is HEAD`; exactly two paths, `qwen-agent-workspace/bin/ltx-movie` and `qwen-agent-workspace/character_dataset.py`. The 23 paths are written out because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Type the 40 characters of `SHA` where the word SHA appears.
  - Replace `then to c33919221ea8ae8fd7811c74e587c2cbccafc4be (seeded-no-identity).` with `then to c33919221ea8ae8fd7811c74e587c2cbccafc4be (seeded-no-identity), then to SHA (shots-multiref).` (once, at the end of the long comment line `:291`).
  - Replace `    BASELINE = "c33919221ea8ae8fd7811c74e587c2cbccafc4be"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/mr-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                         # 1
grep -c "(seeded-no-identity), then to $SHA (shots-multiref)\.$" tests/test_movie_ui_builder.py         # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/mr-baseline/gate-run.sh 3
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the shots-multiref commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output: the summary `2 failed, P0+18 passed, 2 skipped`; `lost 0 (listed 0, unexpected 0); new tests 18, not passing 0; baseline failures still failing 2 of 2`; `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`; `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/mr-baseline/task-3-pytest.txt` prints `1`.

### Verification (controller)

- **V1:** confirm CRK1 and CRK2 from Task 3's gate output and:
  - `git diff --numstat f1a0737 HEAD -- bin/ltx-movie character_dataset.py qwen_edit.py seed_edit_mflux_child.py`: `423 15`, `9 9`, `41 6`, `5 2`
  - `git diff --name-only f1a0737 HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `7` (four code files, two new test files, `tests/test_movie_ui_builder.py`)
  - `git diff f1a0737 HEAD -- story_engine.py character_lib.py bin/ltx-story-images bin/ltx-story-manifest movie_ui_lib.py static | wc -l`: `0`
- **V2:** an Opus design review (the `design-reviewer` agent) of the three commits against this spec, with Section 9 as the focus. A finding is fixed in a new commit. If that commit touches a pinned file, another Task 3-style baseline commit follows, and V1 runs again.
- **V3:** live checks L1, L1b and L2-L5 (Section 8). The user runs them on macstudio; the assistant never does.

### Replay result

The full suite was run twice on archive copies of `f1a0737` with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors`: once untouched (`$S/mr-base`), and once after Tasks 1 and 2 (`$S/mr-replay`).

| Copy | Result |
|---|---|
| `$S/mr-base` (untouched) | `3 failed, 2666 passed, 8 skipped, 1 error` |
| `$S/mr-replay` (Tasks 1-2) | `3 failed, 2684 passed, 8 skipped, 1 error` |

Test by test, the replay lost no baseline pass, and all 18 new tests passed (2666 + 18 = 2684). The failures, the error and the extra skips are the same in both copies and come from the copies not being git worktrees, as in the seeded-no-identity replay:
- the 2 known failures, `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`
- `tests/test_qwen_agent_fleet.py::test_t30_researcher_constants_and_prompt` and the collection error of `tests/test_researcher_think_off.py`, which open `$S/agent/qwen-agent-unsafe` outside the workspace
- the 8 skip lines: `not a git checkout` (`test_mut26` and the `d210c26` tests) and 2 host-only skips

**The first replay found a defect in an earlier draft of this plan, now fixed.** That draft added both new files to `NEW_PY`, and `tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files` failed because it pins the exact tail of `NEW_PY`. CR15 now leaves `NEW_PY` alone, and the second replay above is of the plan as written. `python3 -B tests/test_ltx_movie_offline.py` printed `OK 347/347` in the replay. The real gate runs in `$S/mr-wt`, a git worktree, where the copy effects do not apply.
