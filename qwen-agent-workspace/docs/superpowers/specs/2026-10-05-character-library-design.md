# Character library -- Design Spec (n-character LoRA pipeline)

Date: 2026-10-05
Status: The user approved the design in a sectioned dialogue (Sections 1-4 of the brief: components; dataset and training; strengths, bleed and errors; testing). This document transcribes those decisions without reopening them. Every choice made while writing this document to remove ambiguity is marked **[spec choice]**. Facts that were checked against the real files, CLIs, and docs this session are in Section 0.2. Anything that could not be verified is listed in Section 11 (Known gaps), and the questions that remain for the user are in Section 13.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Branch `qwen-agent-redteam`.

**Amendment 2026-10-05 (user-approved): cast discovery.** This amendment adds two things:

- `bin/ltx-movie` appends an `available characters: …` line to every unknown/unusable-character error.
- `bin/ltx-movie --list-characters` prints the `bin/character list` table.

Both helpers live in `character_lib.py`: see Sections 3.9 and 5.6(i), the rows E-P6a, E-P23 and E-P24, the tests C42-C46, K2 and P50-P57, the new mutation rows, and Section 10 tasks 3, 9 and 12.

**Amendment 2, 2026-10-05 (user-approved): global LoRAs combine with the cast.**

- `--lora`/`--stills-lora` become repeatable `PATH[:STRENGTH]` flags.
- Global (non-character) LoRAs are applied on every panel, alongside the character LoRAs. They are no longer mutually exclusive with them.
- **Section 5.7 is normative and supersedes** every earlier passage that refuses `--lora` with a cast: the former E-P3, E-P15 and E-P19, and the `--cast` + `--lora` bullet in 5.5.

See also the rows E-P25 to E-P29, the tests P60-P75, the gaps G19-G23, and the gates L6b and L6m.

Two terms are used throughout:

- A **character** is one entry in the library: a name, a trigger token, a referring phrase, a descriptor, a dataset, and up to two LoRAs (one video, one stills).
- **Casting** means binding characters to a story, either through `--character NAME` (for a new story) or through `--cast "PHRASE=NAME"` (for an existing `story.md`). A run that uses neither is "uncast". **An uncast run must behave byte-for-byte as it does today** (SC9).

---

## 0. Purpose and scope

### 0.1 Purpose

Today, a character's identity is carried only by the Panel 1 still and by the chained last-frame conditioning. It drifts across a long chained movie, and a second character has no anchor at all. The spike (`generated/charlora/`) proved three things:

1. An LTX video LoRA trained on 24 one-frame stills of a character makes LTX-2.5 distilled draw that character from a trigger-only prompt.
2. `ltx-2-mlx generate --lora` is repeatable.
3. The dataset can be built automatically from either a seed image or a text descriptor.

This feature turns the spike into a durable library (`bin/character`) and wires the library into the movie pipeline. It supports n characters per story. Each panel renders with the LoRAs of exactly the characters its prompt names.

### 0.2 Grounding evidence (checked 2026-10-05)

**Spike facts (from the brief; artifacts re-inspected on disk).**

- `generated/charlora/kyrawmn-v1/train_full.yaml` is the working video config: `model_path` is `~/ltx-2-mlx/models/ltx-2.3-mlx-q8-dev`, rank 32, alpha 32, lr 2e-4, 1000 steps, checkpoint interval 250, keep_last_n 10, validation `video_dims: [512, 320, 25]`, validation interval 1000. The output is `out_full/checkpoints/lora_weights_step_00250 … _01000.safetensors`, each **641,974,104 bytes**.
- Measured `du` sizes: `out_full` is 2.4 G (4 checkpoints plus a 194 KB sample), `preprocessed` is 578 M, `stills` is 16 M, and `videos` is 484 K.
- `train_full.log` reports a peak memory footprint of 40,243,060,904 bytes. `preprocess.log` reports 18,600,111,864 bytes.
- `~/ltx-2-mlx/models/ltx-2.3-mlx-q8-dev/` holds `transformer-dev.safetensors` and **no** `transformer.safetensors` or `transformer-distilled.safetensors`. That is deliberate (the brief): the trainer would pick those first.
- The A/B pair is `kyrawmn-v1/ab/v25_lora.mp4` and `v25_nolora.mp4`. ffprobe gives 512x320, 25 frames, 24 fps. The log shows `Mode: Distilled Two-Stage`, model `~/ltx-2-mlx/models/ltx-2.5-mlx-q8`, and 41.4 s per clip.
- `generated/charlora/kyraseed-v1/` is the `make_dataset_seed.py` live run: 24/25 kept. The VLM descriptor was `"a young woman with fair skin, …, wearing a traditional gray kimono with a dark obi, and black riding boots"`. That shows the situational-item leak, and that the descriptor omits apparent ethnicity. The captions also leak clothing through the pose field (`"holding black boots"`, `"wearing boots"`). Scores are 8-10 except one 5.
- `make_dataset_seed.py` (776 lines, read in full) writes **no contact sheet**. It runs Z-Image **in its own process** while it stops and restarts the vision server.

**`ltx-2-mlx` CLI (`~/ltx-2-mlx/.venv/bin/ltx-2-mlx … --help`, run this session).**

- `generate`: `--lora PATH STRENGTH  LoRA weights and strength (repeatable)`. `--frame-rate` is mandatory. `--distilled` is one of the pipeline-mode flags.
- `--low-ram` help: "Compatible with generate's --lora flag via per-block BlockLoraSource bind-time fusion … custom strengths trigger bind-time LoRA fusion (slower but supports any strength)."
- `preprocess`: `--videos --output [--model] [--gemma] [--height] [--width] [--max-frames (frames % 8 == 1)] [--captions] [--caption-ext] [--with-audio] [--frame-rate]`.
- `train`: `--config CONFIG [--low-ram]`.
- `packages/ltx-core-mlx/src/ltx_core_mlx/loader/fuse_loras.py:93`: `delta = sum(B_i @ A_i * strength_i)`. No alpha appears in the delta, so **alpha must equal rank** for the trained scale to be what is applied.

**Workspace code (read before specifying edits).**

- `ltx2_mlx_video_skill.py:122-162` `build_command` emits `--lora PATH 1.0` once, right after `--gemma`, when `lora_path` is set. `generate_video` (`:211`) has no multi-LoRA input. `tests/check_ltx2_mlx_no_forbidden_imports.py` keeps the module stdlib-only.
- `z_image_skill.py:113-164`: one pipeline singleton per process. `lora_path` is honored only on the first `_get_pipeline` call, and is applied with `load_lora_weights` plus `fuse_lora(lora_scale=1.0)`. `tests/test_z_image_skill_cache.py:113-135` pins `lora_calls == ["my_lora.safetensors"]` and `fuse_calls == [{"lora_scale": 1.0}]`.
- `bin/ltx-mlx-render`:
  - `build_units` (`:233-268`) produces units with exactly 9 keys, pinned by test R4l.
  - `build_clip_provenance` (`:358-381`, schema_version 2) already records `model_identity` and `lora_path` (path only, not bytes).
  - `clip_is_reusable` (`:399-415`) compares the full canonical JSON.
  - `render_panel` calls `SKILL.generate_video` at `:806`.
  - `print_dry_run` builds the first command at `:724`.
  - `load_manifest` (`:160-225`) validates schema 3.
- `bin/ltx-movie`:
  - `STORY_PROMPT_TEMPLATE` (`:96-120`) carries the referring-phrase rule at `:108` ("at most four words … use that exact phrase for them everywhere else"). The anchor text `\n\nHow this movie is made:` occurs exactly once in it.
  - The existing `--lora` / `--stills-lora` flags are at `:215-225`.
  - Phase 2 is at `:792-811` (`bin/ltx-story-images --only 1`), Phase 3 at `:839-873`, and Phase 4 at `:961-983`.
  - `main` requires a narrative positional or `--story-prompt-override` (`:1126`).
- `bin/ltx-story-manifest:470-528`:
  - In schema 3, `motion_prompt` is the Motion: text for every panel, and the render prompt is `resolve_prompt` = `motion_prompt or panel_text`.
  - `story_dir` is read from the module global `WS` at call time.
  - The tool imports stdlib plus PIL only.
- `bin/ltx-story-images`:
  - Stills are rendered from `_compose_prompt(Image:, Style:)`.
  - An existing `panel_NN.png` is reused unless `--force` (`:269-273`).
  - Test I21 checks the source text `lora_path=args.lora_path`.
- Live-gate story `generated/stories/ronin-e2e-appearance-20261005/`:
  - 20 panels, schema 3.
  - Its phrases are `the woman in grey`, `the bearded robber`, `the club robber`, `the spear robber`, and `the ronin`. Several Motion: fields embed `Appearance: The woman in grey is …` text.
  - Original command (from `iterate-story.log`): `bin/ltx-movie --story-id ronin-e2e-appearance-20261005 --panels 20 --no-review --story-prompt-override …/story_prompt.txt --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8`.
  - `clips_judgment.json`: movie `{"seam_continuity": 7, "narrative_clarity": 2}`.
- `generated/charlora/kyrawmn-v1/stills/char_01.png` was viewed this session: a frontal close-up (1024x640) of a young East Asian woman with jade hairpins and a pale grey kimono. Her face is roughly 35-40% of the image height. It is the seed image for live-gate character A (Section 9.7).
- `bin/story-server status` prints a `  state:` line whose value is one of `SERVING <mode>`, `FOREIGN pid N`, `LOADING <mode>`, or `STOPPED` (`bin/story-server:497-506`). At the time of writing it reported `SERVING vision`, model `qwen38-6bit`.

**Libraries (python3 = 3.13.0).**

- diffusers 0.40.0, transformers 5.15.1, torch 2.12.1, and peft 0.20.0.
- `ZImageLoraLoaderMixin.load_lora_weights(path, adapter_name=None, hotswap=False)`.
- `fuse_lora(components=['transformer'], lora_scale=1.0, safe_fusing=False, adapter_names=None)`.
- `set_adapters(adapter_names, adapter_weights=None)` and `get_list_adapters()` exist.
- `lora_state_dict` converts `lora_unet_` / `diffusion_model.` / `.alpha` / `default.` key formats.
- `load_lora_weights` raises `ValueError("Invalid LoRA checkpoint …")` when a key lacks `lora`.
- `PeftAdapterMixin.load_lora_adapter` injects only `if len(state_dict) > 0`. Otherwise it only logs `No LoRA keys associated to …`. **A fully mismatched LoRA therefore registers no adapter, and a partially mismatched one loads silently.** Section 4.9 gates on both cases.

**mflux (not installed; `import mflux` fails; `mflux-train` is not on PATH).**

- PyPI latest is **0.21.0** (published 2026-10-03), `requires_python >=3.10`.
- Its requirements include `torch<3.0,>=2.13.0`, `transformers<6.0,>=5.5.0`, and `mlx<0.33.0,>=0.32.0`. The workspace python has torch 2.12.1, so **installing mflux into it would upgrade torch under z_image_skill**. That is the reason for the isolated venv in Section 4.10.
- `src/mflux/models/z_image/README.md` § Training: "Use `mflux-train` with a training config that targets `z-image` or `z-image-turbo`. We automatically load the Z-Image Turbo training adapter (ostris/zimage_turbo_training_adapter) only when training the turbo model". The command is `mflux-train --config /path/to/train_z_image.json`.
- `src/mflux/models/common/training/_example/train.json` and `src/mflux/models/common/README.md` § Training (LoRA) document:
  - the data folder of `NN.txt` + `NN.png` pairs, with optional `preview*.txt`;
  - the `model_path` key and the `"gradient_checkpointing": true` option;
  - outputs `checkpoints/0000030_checkpoint.zip`, `loss/`, and `preview/`.
- `src/mflux/models/common/training/state/training_state.py:28,50,70`: each checkpoint zip contains `{iterations:07d}_adapter.safetensors`.
- **Unverified:** the adapter's key naming and its loadability into diffusers' `ZImageTransformer2DModel` (Section 11, G1).

**Baseline test counts (run this session, before any change).**

| Suite | Invocation | Result |
|---|---|---|
| `tests/test_ltx_movie_offline.py` | `python3 tests/test_ltx_movie_offline.py` | `OK 344/344` |
| `tests/test_ltx_story_images.py` | direct | `OK 101/101` |
| `tests/test_ltx_mlx_render.py` | direct | `OK 443/443` |
| `tests/test_ltx2_mlx_video_skill.py` | direct | `OK 146/146` |
| `tests/test_ltx_story_manifest_chain.py` | direct | `OK 32/32` |
| `tests/test_ltx_image_fit.py` | direct | `OK 77/77` |
| `tests/check_ltx2_mlx_no_forbidden_imports.py` | direct | `RESULT: ok` |
| `tests/test_z_image_skill_cache.py` | `python3 -m pytest` | `13 passed` |
| `tests/test_deploy_pkg.py` | `python3 -m pytest` (3.13) | `165 passed` |
| `tests/test_deploy_pkg.py` | `/usr/bin/python3 -m unittest tests.test_deploy_pkg` (3.9.6) | `Ran 165 tests … OK` |

**Disk.** `df -h ~`: 66 GiB free of 926 GiB. `~/hf_home/hub/models--Tongyi-MAI--Z-Image-Turbo` is 31 G.

### 0.3 Deliverables

| # | Item | File | Action |
|---|---|---|---|
| D1 | Library schema + casting rules (stdlib only) | `character_lib.py` | new |
| D2 | Dataset building, training, safety gates, Z-Image child process | `character_dataset.py` | new |
| D3 | Library CLI | `bin/character` | new, `chmod +x` |
| D4 | Multi-LoRA argv | `ltx2_mlx_video_skill.py` | edit |
| D5 | Multi-adapter stills | `z_image_skill.py` | edit |
| D6 | Per-unit LoRAs, provenance, manifest validation | `bin/ltx-mlx-render` | edit |
| D7 | `--cast`, trigger insertion, per-panel `characters` | `bin/ltx-story-manifest` | edit |
| D8 | `--cast` for the Panel 1 still | `bin/ltx-story-images` | edit |
| D9 | `--character`, `--cast`, `--character-strength`, CAST block | `bin/ltx-movie` | edit |
| D10 | Deploy ships `character_lib.py` | `scripts/deploy/build_pkg.py`, `tests/test_deploy_pkg.py` | edit (one tuple each) |
| D11 | Tests | `tests/test_character_lib.py`, `tests/test_character_dataset.py`, `tests/test_character_tool.py`, `tests/test_casting_pipeline.py`, `tests/test_z_image_skill_multi_lora.py`, `tests/test_casting_regression.py`, `tests/fixtures/casting_baseline/*` | new |

No other tracked file changes. In particular, none of the existing test files listed in 0.2 is edited, except the single tuple in `tests/test_deploy_pkg.py` (D10). Their counts must be identical after the change (SC9).

### 0.4 Out of scope

- A `delete`/`rename` subcommand. Hand-editing anything other than `descriptor` and `referring_phrase` in `character.json`.
- Casting with `--no-stills` (refused: E-P2). Casting through `--story-prompt-override` when Phase 1 runs (refused: E-P8).
- Giving a LoRA to an on-screen character whose phrase the panel's prompt does not name. This is the known limit, recorded as G5.
- Tuning `CHECK_PROMPT` (the scorer's leniency) or the caption pose wording (G10).
- Shipping `bin/character`, `character_dataset.py`, mflux, the dev model, or any library content in the deploy package (Section 8).
- Pruning intermediate checkpoints, or choosing a checkpoint other than the last.
- Making `bin/ltx-movie` refuse to start while a training run is in progress (G13).
- Changing judges (`bin/judge-*`) or `bin/iterate-story`.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `bin/character create` builds `generated/characters/<name>/` with a valid `character.json`, a dataset of at least 12 kept stills, and `dataset/contact_sheet.jpg`, from either a seed image or a descriptor | D-tests, K-tests, L2, L3 |
| SC2 | `bin/character train` produces `lora/video.safetensors` with the spike config, and records it with its sha256 and a trigger-only A/B pair | D20-D27, L4, L5 |
| SC3 | The stills LoRA trains through mflux and is used **only** if it passes the compat gate (adapter registered, every adapter module injected, one test image rendered). Otherwise it is skipped with a message and the video LoRA is untouched | D28-D34, L0, L4 |
| SC4 | Trigger insertion follows Section 3.6 exactly: after the leading article, prefix when there is none, case-insensitive, word-boundary, longest phrase first, possessives, idempotent | C20-C34 |
| SC5 | Each panel renders with exactly the LoRAs of the cast characters named in its render prompt, at 1.0 alone or at the multi-character strength, as repeated `--lora PATH STRENGTH` | P1-P12, P20-P28 |
| SC6 | The LoRA set (path, sha256, strength) is in clip provenance. `--resume` never reuses a clip rendered with a different LoRA set | P13-P17 |
| SC7 | The Panel 1 still is rendered with the stills LoRAs of the characters its Image: text names, through diffusers adapter names, `set_adapters`, and one `fuse_lora` | Z1-Z6, P30-P35 |
| SC8 | Every row of Section 7's error tables gives the stated exit code or warning, before any GPU work where the table says so | C, K, P tests |
| SC9 | With no `--character`/`--cast`, every existing render argv, manifest, still prompt, and provenance is byte-identical. The existing suites pass with their 0.2 counts unchanged, and the B-golden tests pass | R1, B1-B3 |
| SC10 | The deploy package ships `character_lib.py`. `tests/test_deploy_pkg.py` stays at 165 under both interpreters | R2 |
| SC11 | Live gates L0-L7 pass (Section 9.7). L6 sets the multi-character default strength | L0-L7 |
| SC13 | Global LoRAs (`--lora`/`--stills-lora`, repeatable, `PATH[:STRENGTH]`) apply on every panel ahead of that panel's character LoRAs. Only character LoRAs are counted for the multi-character strength rule, and a global LoRA's strength is never reduced automatically. A path given twice, or also used as a character LoRA, exits 2. The full ordered set, each entry with `kind`, is in provenance. A single `--lora PATH` with no cast stays byte-identical to today | P60-P75, B1-B3, R1 |
| SC12 | An unknown or unusable `--character`/`--cast` name in `bin/ltx-movie` exits 2 with the error plus an `available characters:` line. `bin/ltx-movie --list-characters` prints exactly the `bin/character list` table and exits 0, with no `--story-id`, no narrative, and no server, GPU or lockfile activity | C42-C46, K2, P50-P57 |

### 0.6 Must-have vs nice-to-have

Every requirement in Sections 1-10 is a must-have. There are no nice-to-haves.

---

## 1. Architecture

### 1.1 Data flow

```
bin/character create NAME ...  ──>  generated/characters/NAME/{character.json, seed.png, dataset/}
bin/character train NAME       ──>  .../lora/video.safetensors (+ lora/stills.safetensors), tests/

bin/ltx-movie --character NAME / --cast "PHRASE=NAME"
  ├─ resolve cast via character_lib (exit 2 on any library problem, before any phase)
  ├─ Phase 1: STORY_PROMPT_TEMPLATE + CAST block (only for --character on a new story)
  ├─ Phase 2: bin/ltx-story-images ... [--lora PATH:S ...] --cast PHRASE=NAME ... --character-strength S
  │            -> trigger inserted into panel 1's Image: prompt; z_image_skill loads stills LoRAs
  ├─ Phase 3: bin/ltx-story-manifest ... --cast PHRASE=NAME ... --character-strength S
  │            -> trigger inserted into each motion_prompt; per-panel "characters" list
  └─ Phase 4: bin/ltx-mlx-render [--lora PATH:S ...] reads panel["characters"]
               -> per panel: global LoRAs (CLI order) + that panel's character LoRAs (amendment 2, 5.7)
               -> ltx2_mlx_video_skill: --lora PATH STRENGTH per character; LoRA set in provenance
```

### 1.2 Module boundaries and import rules [spec choice]

- `character_lib.py` (WS root) is **stdlib only**. It is the one owner of the `character.json` schema, of name/trigger/phrase validation, and of the casting rules (matching, insertion, strengths, CAST block).
  - `bin/ltx-movie`, `bin/ltx-story-manifest`, and `bin/ltx-story-images` load it **only inside the casting branch**, through `importlib.machinery.SourceFileLoader("character_lib", os.path.join(WS, "character_lib.py")).load_module()`. This is the same pattern as `bin/ltx-movie::_image_fit` (`:583-588`).
  - An uncast run therefore never reads the file. That keeps import cost and behavior identical, and keeps X2 (`ltx-movie --dry-run`) independent of it.
- `bin/ltx-mlx-render` does **not** import `character_lib`. The manifest is self-contained: each `characters` entry carries its LoRA path and strength. This preserves the script's "carries its own validator" rule (`:16-21`).
- `ltx2_mlx_video_skill.py` stays stdlib only (the forbidden-imports check must still print `RESULT: ok`). It only gains an argv list input.
- `character_dataset.py` (WS root) holds everything heavy:
  - top-level imports are stdlib, `PIL`, and `psutil`;
  - `torch`, `z_image_skill`, and `content_safety` are imported **only** inside `child_zimage()`, which runs in a child process;
  - it also imports `character_lib` and `ltx2_mlx_video_skill` (as `SKILL`) at top level.
- `bin/character` imports `character_lib` at top level (with `WS` on `sys.path`), and imports `character_dataset` only inside `create`/`train`. So `list`/`show` need neither PIL nor psutil.
- Z-Image generation always runs in a **child process** (`python3 character_dataset.py zimage --spec SPEC`) **[spec choice]**. Two reasons:
  1. z_image_skill allows one LoRA set per process (5.2).
  2. `create` must release Z-Image's ~20 GB before it restarts the 22 GB vision server. `make_dataset_seed.py` kept the pipeline resident during scoring.

### 1.3 Internal names [spec choice]

`character_lib.py` constants: `WS`, `LIBRARY_ENV = "CHARACTER_LIBRARY_DIR"`, `SCHEMA_VERSION = 1`, `NAME_RE`, `TRIGGER_RE`, `CLASS_RE`, `PHRASE_WORD_RE`, `MAX_PHRASE_WORDS = 6`, `ARTICLES = ("the", "a", "an")`, `STATUSES = ("dataset", "untrained", "trained")`, `SOURCE_TYPES = ("seed_image", "descriptor")`, `MIN_SCORE = 7`, `MIN_KEEP = 12`, `DEFAULT_CHARACTER_STRENGTH = 0.8`, `SINGLE_CHARACTER_STRENGTH = 1.0`, `TRIGGER_REGISTRY = ".triggers"`, `LOCK_NAME = ".lock"`, `SHA256_RE`, `UTC_RE`, `CAST_BLOCK_HEADER`, `CAST_BLOCK_RULES`, `LIST_ROW_FORMAT`, `NO_CHARACTERS_AVAILABLE`.

`character_lib.py` names: `CharacterError(Exception)`, `UnusableCharacterError(CharacterError)` (3.9), and `CastMember` (namedtuple). Its functions are listed in 3.1.

`character_dataset.py` names: `DatasetError(Exception)`. Its constants and functions are listed in 4.1.

---

## 2. The library on disk

### 2.1 Layout

The root is `character_lib.library_dir()`, which is `$CHARACTER_LIBRARY_DIR` if set, else `WS/generated/characters`. The env var is test infrastructure only, the same kind of override as `LTX2_MLX_BIN` **[spec choice]**. The root is gitignored through `WS/.gitignore:2` (`generated/`) and is durable.

```
generated/characters/
  .triggers                         # append-only registry: "<trigger> <name>\n" per line
  .lock                             # pid of the running create/train (absent when idle)
  <name>/
    character.json
    seed.png                        # seed-image mode only: EXIF-oriented RGB copy of the input
    dataset/
      stills/char_NN.png            # char_00 = seed fitted to 1024x640 (seed mode); char_01..24 generated
      captions/char_NN.txt          # kept stills only
      videos/char_NN.mp4            # kept stills only; 1-frame h264 wrap
      description.json              # seed mode only: {"class_noun", "descriptor", "raw"}
      manifest.json                 # Section 4.6
      contact_sheet.jpg             # Section 4.7
    train/
      video/train.yaml, video/preprocessed/.precomputed/{latents,conditions}/, video/out/checkpoints/
      stills/data/char_NN.{png,txt} + preview_1.txt, stills/train.json, stills/out/...
    lora/video.safetensors          # copy of the final video checkpoint
    lora/stills.safetensors         # extracted mflux adapter, present only if it passed the compat gate
    lora/stills.rejected.safetensors  # an adapter that failed the compat gate (kept for diagnosis)
    tests/video_lora.mp4, tests/video_control.mp4, tests/stills_lora.png, tests/stills_control.png
    logs/<UTC %Y%m%dT%H%M%SZ>-<step>.log  (+ .spec.json / .report.json for Z-Image children)
```

### 2.2 `character.json` (schema_version 1)

Example (a trained seed-image character whose stills LoRA was skipped):

```json
{
  "schema_version": 1,
  "name": "kyra",
  "trigger": "kyrawmn",
  "class_noun": "woman",
  "referring_phrase": "the woman in grey",
  "descriptor": "a young East Asian woman, slender, with pale skin and long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi",
  "seed": 0,
  "source": {"type": "seed_image", "path": "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/charlora/kyrawmn-v1/stills/char_01.png"},
  "strength": null,
  "status": "trained",
  "created_at": "2026-10-06T01:02:03Z",
  "dataset": {"reference": "char_00", "kept": 23, "total": 25, "min_score": 7,
              "face_height": 0.38,
              "contact_sheet": "/Users/.../generated/characters/kyra/dataset/contact_sheet.jpg"},
  "loras": {
    "video": {"path": "/Users/.../generated/characters/kyra/lora/video.safetensors",
              "sha256": "<64 lowercase hex>",
              "base_model": "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.3-mlx-q8-dev",
              "rank": 32, "alpha": 32, "steps": 1000,
              "trained_at": "2026-10-06T02:00:00Z",
              "sample_path": "/Users/.../generated/characters/kyra/tests/video_lora.mp4",
              "control_path": "/Users/.../generated/characters/kyra/tests/video_control.mp4"},
    "stills": null
  },
  "stills_skip_reason": "mflux-train not found at /Users/reubenpatterson/mflux/.venv/bin/mflux-train"
}
```

The design's fields (`name`, `trigger`, `class_noun`, `referring_phrase`, `descriptor`, `seed`, `source`, `strength`, `status`, `loras.video` / `loras.stills` with `path, base_model, rank, alpha, steps, trained_at, sample_path`) are kept. **[spec choice]** additions:

- `schema_version`;
- `created_at`;
- `dataset` (null until scoring completes);
- `sha256` and `control_path` in each LoRA entry;
- `stills_skip_reason`.

`source` is the object `{"type": "seed_image", "path": <absolute original path>}` or `{"type": "descriptor"}`.

### 2.3 Validation (`validate_character(data, name=None)`) [spec choice: strict]

Every rule raises `CharacterError("<field>: <reason>")`. The message for a failed `load_character` is `invalid character.json for <name>: <field>: <reason>`.

| Field | Rule |
|---|---|
| top level | a dict whose key set is exactly `{schema_version, name, trigger, class_noun, referring_phrase, descriptor, seed, source, strength, status, created_at, dataset, loras, stills_skip_reason}` |
| `schema_version` | `== 1` (int, not bool) |
| `name` | `NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")` fullmatch. Equals `name` when one is given (the directory name) |
| `trigger` | `TRIGGER_RE = re.compile(r"[a-z][a-z0-9]{3,15}")` fullmatch. Not equal to `class_noun`. Not equal (case-insensitive) to any word of `referring_phrase` |
| `class_noun` | `CLASS_RE = re.compile(r"[a-z]{3,12}")` fullmatch |
| `referring_phrase` | `normalize_phrase(v) == v` (3.2) |
| `descriptor` | a str. `8 <= len(v.split()) <= 60`. Starts with `"a "` or `"an "` (lowercase). Does not end with `"."`. `v == v.strip()` |
| `seed` | int, not bool, `>= 0` |
| `source` | the dict `{"type": "seed_image", "path": <absolute str>}` or exactly `{"type": "descriptor"}` |
| `strength` | `None`, or an int/float (not bool) with `0 < v <= 1.0` |
| `status` | in `STATUSES` |
| `created_at` | `UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")` fullmatch |
| `dataset` | `None`, or a dict with exactly the keys `reference` (`"char_00"` or `"char_01"`), `kept` (int), `total` (int, `0 <= kept <= total`), `min_score` (int 1-10), `face_height` (`None`, or a number in `[0, 1]`), `contact_sheet` (absolute str) |
| `loras` | a dict with exactly the keys `video`, `stills`. Each is `None` or a LoRA entry |
| LoRA entry | a dict with exactly the keys `path` (absolute str), `sha256` (`SHA256_RE = re.compile(r"[0-9a-f]{64}")` fullmatch), `base_model` (non-empty str), `rank` (int >= 1), `alpha` (int, `== rank`), `steps` (int >= 1), `trained_at` (UTC_RE), `sample_path` and `control_path` (each `None` or an absolute str) |
| `stills_skip_reason` | `None` or a non-empty str |
| consistency | `status == "trained"` exactly when `loras.video is not None`. `status in ("untrained", "trained")` requires `dataset is not None and dataset.kept >= MIN_KEEP` |

File existence is **not** checked by `validate_character`. `resolve_cast` checks it (3.5), and so does `bin/character show` (4.4).

### 2.4 Names and triggers

- **Name:** `NAME_RE`. It is the directory name and the CLI handle.
- **Trigger:** `TRIGGER_RE`. It is unique across the library **forever**. `registered_triggers()` is the union of the `.triggers` registry and every `character.json` `trigger` readable in the library. A trigger is registered when a character directory is first created, so a create that fails afterwards still reserves its trigger **[spec choice]**. Triggers are never reused.
- **Auto-generation** (rare-token style; reproduces the spike's `kyrawmn`) **[spec choice]**:

```python
def auto_trigger(name, class_noun, taken, avoid=()):
    """Rare-token trigger: up to 5 letters of the name + up to 3 consonants of the class noun,
    padded with 'x' to 4 characters, then suffixed 2, 3, ... until unused (spec 2.4)."""
    stem = re.sub(r"[^a-z]", "", name)[:5]
    suffix = "".join(c for c in class_noun if c not in "aeiou")[:3] or class_noun[:3]
    base = stem + suffix
    if len(base) < 4:
        base = (base + "xxxx")[:4]
    blocked = set(taken) | {w.lower() for w in avoid} | {class_noun}
    candidate, k = base, 2
    while candidate in blocked:
        candidate = "%s%d" % (base, k)
        k += 1
    return candidate
```

| Call | Result |
|---|---|
| `auto_trigger("kyra", "woman", set())` | `"kyrawmn"` |
| `auto_trigger("ronin", "man", set())` | `"roninmn"` |
| `auto_trigger("kyra", "woman", {"kyrawmn"})` | `"kyrawmn2"` |
| `auto_trigger("kyra", "woman", {"kyrawmn", "kyrawmn2"})` | `"kyrawmn3"` |
| `auto_trigger("a1", "man", set())` | `"amnx"` |
| `auto_trigger("ab-cd", "person", set())` | `"abcdprs"` |

`avoid` is the phrase's words. The result always matches `TRIGGER_RE`, because the name starts with a letter and the result is at most 8 + digits characters long.

---

## 3. `character_lib.py` (normative)

### 3.1 Public functions

| Function | Behavior |
|---|---|
| `library_dir()` | `os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "characters")`, read at call time |
| `character_dir(name)` / `character_json_path(name)` | `<lib>/<name>`, `<lib>/<name>/character.json` |
| `utc_now()` | `datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` |
| `validate_name(name)` | `CharacterError("character name must match [a-z][a-z0-9-]{1,23}, got %r" % (name,))` |
| `validate_trigger(trigger)` | `CharacterError("trigger must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))` |
| `validate_class_noun(noun)` | `CharacterError("class noun must match [a-z]{3,12}, got %r" % (noun,))` |
| `normalize_phrase(phrase)` | 3.2 |
| `validate_descriptor(text)` | the `descriptor` rule of 2.3. `CharacterError("descriptor: <reason>")` |
| `validate_character(data, name=None)` | 2.3 |
| `load_character(name)` | `validate_name`. A missing file gives `CharacterError("unknown character: %s (no %s)" % (name, path))`. `ValueError` from the JSON parse, or a `CharacterError` from validation, gives `CharacterError("invalid character.json for %s: %s" % (name, e))`. Returns the dict |
| `write_character(data)` | `validate_character(data)`, then an atomic write to `character_json_path(data["name"])`: `json.dump(data, f, indent=2, ensure_ascii=False)` + `"\n"` into `<path>.<uuid4 hex>.tmp`, then `os.replace`. The directory must already exist |
| `list_names()` | `[]` if the library dir is missing. Otherwise `sorted(n for n in os.listdir(lib) if NAME_RE.fullmatch(n) and os.path.isfile(character_json_path(n)))` |
| `registered_triggers()` | `{trigger: name}`. First read `.triggers` (lines split on whitespace into exactly 2 fields; other lines are ignored). Then, for each name in `list_names()`, read the raw JSON, and if `data.get("trigger")` is a str, add it (registry entries win on conflict). Unreadable JSON is skipped |
| `register_trigger(trigger, name)` | `os.makedirs(lib, exist_ok=True)`, then append `"%s %s\n" % (trigger, name)` to `.triggers` |
| `auto_trigger(name, class_noun, taken, avoid=())` | 2.4 |
| `parse_cast_arg(value)` | 3.4 |
| `resolve_cast(entries)` | 3.5 |
| `phrase_occurs(text, phrase)` | `_phrase_regex(normalize_phrase(phrase)).search(text) is not None` |
| `cast_text(text, members)` | 3.6 |
| `panel_strengths(names, members, character_strength)` | 3.7 |
| `build_cast_block(members)` | 3.8 |
| `usable_characters()` | 3.9 |
| `format_available_line(characters)` | 3.9 |
| `character_table_lines()` | 3.9 |

### 3.2 Phrases

```python
PHRASE_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def normalize_phrase(phrase):
    """Whitespace-collapsed phrase, case preserved. Raises CharacterError (spec 3.2)."""
    if not isinstance(phrase, str):
        raise CharacterError("phrase must be a string, got %r" % (phrase,))
    words = phrase.split()
    if not 1 <= len(words) <= MAX_PHRASE_WORDS:
        raise CharacterError("phrase must be 1-%d words, got %r" % (MAX_PHRASE_WORDS, phrase))
    for word in words:
        if not PHRASE_WORD_RE.fullmatch(word):
            raise CharacterError("phrase word %r may contain only letters, digits, apostrophes "
                                 "and hyphens (phrase %r)" % (word, phrase))
    if len(words) == 1 and words[0].lower() in ARTICLES:
        raise CharacterError("phrase must not be a lone article: %r" % (phrase,))
    return " ".join(words)
```

The six-word cap is a **[spec choice]**. The story template's own phrases are capped at four words (`bin/ltx-movie:108`), and the CAST block (3.8) explicitly allows a longer cast phrase.

### 3.3 `CastMember`

```python
CastMember = collections.namedtuple("CastMember", [
    "name", "phrase", "trigger", "class_noun", "descriptor",
    "video_lora", "stills_lora", "stills_skip_reason", "strength"])
```

`video_lora` is the absolute path. `stills_lora` is the absolute path or `None`. `strength` is the `character.json` override or `None`.

### 3.4 `parse_cast_arg(value)`

- It splits on the **last** `=`: `phrase, name = value.rsplit("=", 1)`.
- If there is no `=`: `CharacterError("--cast must be PHRASE=NAME, got %r" % (value,))`.
- It returns `(normalize_phrase(phrase), name.strip())`, after `validate_name(name.strip())`.
- **(Amendment)** A `validate_name` failure here is re-raised as `UnusableCharacterError` with the same message: `raise UnusableCharacterError(str(e))`. A missing `=` and an invalid phrase stay plain `CharacterError`.

### 3.5 `resolve_cast(entries)`

`entries` is a list of `(phrase_or_None, name)`. A `None` phrase means "use the character's `referring_phrase`" (that is `--character NAME`).

```python
def resolve_cast(entries):
    members = []
    for phrase, name in entries:
        try:
            data = load_character(name)
        except UnusableCharacterError:
            raise
        except CharacterError as e:
            raise UnusableCharacterError(str(e))
        if data["status"] != "trained":
            raise UnusableCharacterError("character %s is not trained (status %s); run "
                                         "bin/character train %s" % (name, data["status"], name))
        video = data["loras"]["video"]["path"]
        if not _readable_nonempty(video):
            raise UnusableCharacterError("character %s's video LoRA is missing or empty: %s"
                                         % (name, video))
        stills = data["loras"]["stills"]["path"] if data["loras"]["stills"] else None
        if stills is not None and not _readable_nonempty(stills):
            raise CharacterError("character %s's stills LoRA is missing or empty: %s" % (name, stills))
        phrase = normalize_phrase(phrase) if phrase is not None else data["referring_phrase"]
        if data["trigger"] in [w.lower() for w in phrase.split()]:
            raise CharacterError("character %s's trigger %s is a word of its cast phrase %r"
                                 % (name, data["trigger"], phrase))
        members.append(CastMember(name, phrase, data["trigger"], data["class_noun"],
                                  data["descriptor"], video, stills,
                                  data["stills_skip_reason"], data["strength"]))
    by_name, by_phrase, by_trigger = {}, {}, {}
    for m in members:
        if m.name in by_name:
            raise CharacterError("character %s is cast more than once" % m.name)
        if m.phrase.lower() in by_phrase:
            raise CharacterError("cast phrase %r is used for both %s and %s"
                                 % (m.phrase, by_phrase[m.phrase.lower()], m.name))
        if m.trigger in by_trigger:
            raise CharacterError("characters %s and %s share the trigger %s"
                                 % (by_trigger[m.trigger], m.name, m.trigger))
        by_name[m.name] = m
        by_phrase[m.phrase.lower()] = m.name
        by_trigger[m.trigger] = m.name
    return members
```

`_readable_nonempty(p)` is `os.path.isfile(p) and os.access(p, os.R_OK) and os.path.getsize(p) > 0`. Members keep entry order.

**(Amendment)** Message texts are unchanged; only the exception class changes. `UnusableCharacterError` is raised for:

- an invalid name, an unknown character, or an invalid `character.json` (anything `load_character` raises);
- status other than `trained`;
- a video LoRA that is missing or empty.

Every other `resolve_cast` failure stays a plain `CharacterError`: a missing or empty stills LoRA, the trigger being a phrase word, an invalid phrase, a duplicate name, phrase or trigger. Those are errors in the request, not in the choice of character, so no alternatives are listed **[spec choice]**. LoRA bytes are **not** hashed here **[spec choice]**: the cost would be about 0.5 s per 642 MB file per tool invocation. The render hashes them for provenance (5.3).

### 3.6 Matching and trigger insertion

```python
def _phrase_regex(phrase, trigger=None):
    words = phrase.split()
    esc = [re.escape(w) for w in words]
    trig = re.escape(trigger) if trigger else None
    if len(words) > 1 and words[0].lower() in ARTICLES:
        body = (esc[0] + (r"(?P<trig>\s+" + trig + r")?" if trig else "")
                + r"\s+" + r"\s+".join(esc[1:]))
    else:
        body = (r"(?P<trig>" + trig + r"\s+)?" if trig else "") + r"\s+".join(esc)
    return re.compile(r"(?<![\w-])" + body + r"(?![\w-])", re.IGNORECASE)


def cast_text(text, members):
    """(text with each cast phrase's trigger inserted, sorted names of the members found).
    Longest phrase first; a match overlapping an already-claimed span is ignored; an
    occurrence that already carries the trigger is counted but not re-inserted (spec 3.6)."""
    found = []
    for member in sorted(members, key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)):
        for match in _phrase_regex(member.phrase, member.trigger).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _, _ in found):
                continue
            found.append((start, end, member, match.group("trig") is not None))
    out = text
    for start, _end, member, already in sorted(found, key=lambda f: f[0], reverse=True):
        if already:
            continue
        words = member.phrase.split()
        if len(words) > 1 and words[0].lower() in ARTICLES:
            cut = start + len(words[0])
            out = out[:cut] + " " + member.trigger + out[cut:]
        else:
            out = out[:start] + member.trigger + " " + out[start:]
    return out, sorted({member.name for _, _, member, _ in found})
```

Rules this code encodes:

- **Case-insensitive.** The article keeps its written case (`"The woman in grey"` becomes `"The kyrawmn woman in grey"`). The trigger is always inserted in lowercase.
- **Word boundary.** Neither a word character nor a hyphen may touch either end of the match **[spec choice: hyphen counts as a word character]**:
  - `"the ronins"` does not match, and `"the ronin-like"` does not match;
  - `"the woman in grey-blue robe"` does not match `the woman in grey`;
  - `"bathe ronin"` does not match `the ronin`.
- **Possessive.** `"the ronin's"` and `"the ronin’s"` (U+2019) both match `the ronin`, because `'` and `’` are not word characters. The insertion gives `"the roninmn ronin's"`.
- **Whitespace.** Words may be separated by any run of whitespace, including newlines.
- **Longest phrase first.** Ties are broken by lowercase phrase, then by name. When `the woman` and `the woman in grey` are both cast, `"the woman in grey"` is claimed by the longer phrase.
- **No article** (or a single-word phrase): the trigger is prefixed (`"Kyra smiles"` becomes `"kyrawmn Kyra smiles"`).
- **Idempotent.** `cast_text(cast_text(t, m)[0], m) == cast_text(t, m)`, because the optional `trig` group recognizes an already-inserted trigger.

### 3.7 Strengths

```python
def panel_strengths(names, members, character_strength):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named; else each
    character's own character.json strength if set, otherwise character_strength (spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}
```

### 3.8 CAST block

```python
CAST_BLOCK_HEADER = ("Cast: these characters have fixed identities that the pipeline already "
                     "knows how to draw.")
CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file: it replaces the phrase you would otherwise invent for them, even "
    "when it is longer than four words. In Panel 1's Image: field, describe each of these "
    "characters who is on screen in the opening frame with exactly the description given above, "
    "word for word. Bring a cast member on screen only where the narrative calls for them. "
    "Every other character still gets a referring phrase of your own, under the rules below.")


def build_cast_block(members):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(CAST_BLOCK_RULES)
    return "\n".join(lines)
```

The block contains no `{` or `}` (C40), so it can never disturb `str.format` or the deploy X2 brace check.

### 3.9 Cast discovery (amendment)

```python
class UnusableCharacterError(CharacterError):
    """The named character does not exist, cannot be loaded, or cannot render (not trained, or
    its video LoRA is missing or empty). Callers that can offer alternatives append
    format_available_line(usable_characters()) (spec 3.9)."""


NO_CHARACTERS_AVAILABLE = "available characters: none (create one with bin/character create)"
LIST_ROW_FORMAT = "%-16s %-16s %-9s %-5s %-6s %s"


def usable_characters():
    """[(name, referring_phrase)] sorted by name, for every library character that
    resolve_cast would accept on its own (loadable, trained, video LoRA readable and non-empty,
    stills LoRA readable and non-empty when recorded)."""
    usable = []
    for name in list_names():
        try:
            member = resolve_cast([(None, name)])[0]
        except CharacterError:
            continue
        usable.append((member.name, member.phrase))
    return usable


def format_available_line(characters):
    """One line naming the usable characters; characters is usable_characters()'s list."""
    if not characters:
        return NO_CHARACTERS_AVAILABLE
    return "available characters: " + ", ".join("%s (%s)" % (n, p) for n, p in characters)


def character_table_lines():
    """The library table printed by bin/character list and bin/ltx-movie --list-characters."""
    names = list_names()
    if not names:
        return ["no characters in %s" % library_dir()]
    lines = [LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS", "PHRASE")]
    for name in names:
        try:
            data = load_character(name)
        except CharacterError as e:
            lines.append("%-16s (invalid: %s)" % (name, e))
            continue
        lines.append(LIST_ROW_FORMAT % (
            name, data["trigger"], data["status"],
            "yes" if data["loras"]["video"] else "no",
            "yes" if data["loras"]["stills"] else "no",
            data["referring_phrase"]))
    return lines
```

- `usable_characters()` is ordered by `list_names()`, which is already sorted. Each phrase listed is the character's `referring_phrase`, not a `--cast` override.
- The table's `VIDEO`/`STILLS` columns report what `character.json` records. They do not check files: a character can show `yes` and still be absent from `available characters:`, because its file is missing.
- Only `bin/ltx-movie` appends the `available characters:` line **[spec choice]**. `bin/ltx-story-manifest` and `bin/ltx-story-images` run only after `bin/ltx-movie` has resolved the cast, or by hand, so their error messages are unchanged.
- `bin/character`'s own errors (CT1, CS1) are also unchanged. It reuses `character_table_lines()` for `list`, and `format_available_line` remains available to it.

---

## 4. `bin/character` and `character_dataset.py`

### 4.1 `character_dataset.py` names

**Copied verbatim from `generated/charlora/tools/make_dataset_seed.py`:** `VLM_URL`, `MODELS_URL`, `VLM_MODEL`, `WIDTH = 1024`, `HEIGHT = 640`, `STYLE`, `SHOTS`, `VARIANTS` (24 entries), `CHECK_PROMPT`, `extract_json`, `validate_description`, `validate_check`, `gen_prompt`, `caption`, `image_data_url`, `vlm_call`.

**Changed:**

- `WS = os.path.dirname(os.path.realpath(__file__))`.
- `STORY_SERVER = os.path.join(WS, "bin", "story-server")`.
- `verify_ffprobe(mp4)` raises `DatasetError("ffprobe: expected 1 frame in %s, got %r" % ...)` and `DatasetError("ffprobe failed for %s: %s" % ...)` instead of calling `sys.exit`.
- `DESCRIBE_PROMPT` is replaced (4.5).

**New:** `FACE_PROMPT` (4.5), `FACE_MIN_HEIGHT = 0.15`, `CREATE_MIN_FREE_GIB = 2.0`, `TRAIN_MIN_FREE_GIB_PER_KIND = 8.0`, `TRAIN_MIN_AVAIL_GIB = 30.0`, `GENERATE_MIN_AVAIL_GIB = 20.0`, `VLM_WAIT_S = 600`, `AVAIL_WAIT_S = 600`.

- `TRAIN_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.3-mlx-q8-dev")`
- `TEST_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.5-mlx-q8")`
- `VIDEO_RANK = 32`, `VIDEO_STEPS = 1000`, `VIDEO_FINAL_CKPT = "lora_weights_step_01000.safetensors"`
- `STILLS_RANK = 16`, `STILLS_TARGET_STEPS = 2400`
- `MFLUX_TRAIN = os.environ.get("CHARACTER_MFLUX_TRAIN", os.path.expanduser("~/mflux/.venv/bin/mflux-train"))` (the env var is test infrastructure)
- `MFLUX_HF_HOME = os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))`
- Timeouts: `PREPROCESS_TIMEOUT_S = 1800`, `VIDEO_TRAIN_TIMEOUT_S = 14400`, `STILLS_TRAIN_TIMEOUT_S = 21600`, `TEST_RENDER_TIMEOUT_S = 1800`, `ZIMAGE_CHILD_TIMEOUT_S = 3600`
- `TEST_SEED = 42`

Functions (signatures are normative; behavior is specified in the subsections below):

`trigger_test_prompt(trigger, class_noun)`, `validate_face(d)`, `vlm_ready()`, `story_server(cmd)`, `story_server_state()`, `wait_for_vlm(timeout_s)`, `wait_for_avail(min_gib, timeout_s)`, `busy_process()`, `free_gib(path)`, `library_lock()` (context manager), `run_logged(cmd, log_path, cwd, env, timeout_s)`, `step_log_path(char_dir, step)`, `run_zimage_child(spec, char_dir, step)`, `face_height(seed_path)`, `describe(seed_path)`, `score_still(ref_path, cand_path)`, `wrap_still(png, mp4)`, `write_contact_sheet(items, stills_dir, out_path)`, `build_dataset(data, face_height)`, `create(args)`, `video_train_config(data_root, validation_prompt, output_dir)`, `preprocess_argv(videos, captions, out_dir)`, `train_argv(config_path)`, `train_video(data)`, `stills_epochs(kept)`, `stills_train_config(data_dir, output_dir, seed, kept)`, `safetensors_keys(path)`, `lora_module_count(keys)`, `extract_mflux_adapter(out_dir, dest)`, `train_stills(data)`, `train(args)`, `child_zimage(spec_path)`, `main(argv)`.

### 4.2 `bin/character` CLI

```python
def build_parser():
    parser = argparse.ArgumentParser(
        prog="character",
        description="Build, train and inspect the character LoRA library (generated/characters/).")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    p = sub.add_parser("create", help="build a character's training dataset and stop for review")
    p.add_argument("name", metavar="NAME")
    p.add_argument("--phrase", default=None, metavar="PHRASE",
                   help='fixed referring phrase used in stories, e.g. "the ronin"')
    p.add_argument("--seed-image", dest="seed_image", default=None, metavar="PATH")
    p.add_argument("--descriptor", default=None, metavar="TEXT")
    p.add_argument("--class", dest="class_noun", default=None, metavar="NOUN")
    p.add_argument("--trigger", default=None, metavar="WORD")
    p.add_argument("--seed", type=int, default=None, metavar="N")
    p.add_argument("--force", action="store_true",
                   help="proceed although the seed image's face is small or not found")
    p.add_argument("--regenerate", action="store_true",
                   help="rebuild an existing, untrained character's dataset from its character.json")
    t = sub.add_parser("train", help="train the video LoRA and/or the stills LoRA")
    t.add_argument("name", metavar="NAME")
    t.add_argument("--video", action="store_true")
    t.add_argument("--stills", action="store_true")
    t.add_argument("--force", action="store_true", help="retrain a LoRA that already exists")
    sub.add_parser("list", help="list every character")
    s = sub.add_parser("show", help="print one character's record and file status")
    s.add_argument("name", metavar="NAME")
    return parser
```

- The shebang is `#!/usr/bin/env python3`. After stdlib imports: `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, `sys.path.insert(0, WS)`, `import character_lib`.
- `main(argv=None)` returns an int, and the file ends with `if __name__ == "__main__": sys.exit(main())`. There is no `pipeline_log` wiring (it is per-story) **[spec choice]**.
- `train`'s `--force` is a **[spec choice]** (the design lists none). It prevents an accidental 47-minute retrain that would replace a good LoRA.
- Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 `create` kept fewer than `MIN_KEEP` stills.

### 4.3 `list` and `show`

- **`list`.** It runs `print("\n".join(character_lib.character_table_lines()))` and exits 0 (3.9).
  - An empty library gives the single line `no characters in <library_dir()>`.
  - Otherwise the output is a `NAME TRIGGER STATUS VIDEO STILLS PHRASE` header and one row per name, both in `LIST_ROW_FORMAT`. `VIDEO`/`STILLS` are `yes`/`no`.
  - A character whose `load_character` fails gets the row `"%-16s (invalid: %s)" % (name, e)`, and the exit code is still 0.
- **`show NAME`.**
  - It runs `load_character` (on `CharacterError`: `Error: <e>`, exit 2).
  - It prints `json.dumps(data, indent=2, ensure_ascii=False)`, then `files:`.
  - Then, for each of `seed.png` (seed mode), `dataset.contact_sheet`, each non-null LoRA `path`, `sample_path`, and `control_path`, it prints a line `"  %-8s %s" % ("ok" if os.path.isfile(p) else "MISSING", p)`.
  - Exit 0.

### 4.4 `create`

**Argument validation.** These run in this order, and every failure exits 2 with `Error: …` (Section 7.1). Nothing is written before step 15.

1. `validate_name(name)`.
2. **`--regenerate` given:**
   - Any of `--phrase`, `--seed-image`, `--descriptor`, `--class`, `--trigger`, `--seed`, `--force` → CE13a.
   - Then `load_character(name)` (CE13b).
   - `status == "trained"` → CE13c.
   - Then go to step 9.
3. Otherwise, `character_dir(name)` exists → CE3.
4. `--phrase` is missing → CE4. Otherwise `phrase = normalize_phrase(args.phrase)` (CE5).
5. The count of `--seed-image` / `--descriptor` given is not exactly 1 → CE6.
6. `--class` given → `validate_class_noun` (CE8). In descriptor mode without `--class` → CE7.
7. **Descriptor mode:** `_, descriptor = validate_description({"class_noun": cls, "descriptor": args.descriptor})`, which normalizes a leading capital and a trailing `.`. A `ValueError` → CE9.
   **Seed mode:** `seed_path = os.path.abspath(args.seed_image)`. Not a file → CE10a. `ltx_image_fit.load_oriented_rgb(seed_path)` raises → CE10b.
8. Seed: `args.seed if args.seed is not None else 0`. A value below 0 → CE12. `--trigger` given → `validate_trigger` (CE11a). Already in `registered_triggers()` → CE11b. A word of the phrase, or equal to `--class` → CE11c.

**Preflights.** Both modes.

9. Enter `library_lock()` (CE14). Then `busy_process()` (CE15). Then `free_gib(<library_dir or its nearest existing parent>) < CREATE_MIN_FREE_GIB` (CE16). Then `vlm_ready()` (CE17).

**New-character analysis** (skipped by `--regenerate`).

10. **Seed mode:** `fh = face_height(seed_path)` (CE19 on failure). If `fh is None` or `fh < FACE_MIN_HEIGHT`:
    - without `--force` → CE18 (exit 2, nothing written);
    - with `--force`, print the CE18 text with `Warning: ` in place of `Error: ` and `; proceeding (--force)` in place of the trailing advice.
11. **Seed mode:** `cls_vlm, descriptor, raw = describe(seed_path)` (CE19). `cls = args.class_noun or cls_vlm`.
12. **Descriptor mode:** `fh = None`, `raw = None`.
13. `trigger = args.trigger or auto_trigger(name, cls, registered_triggers(), avoid=phrase.split())`. If `--trigger` was given and `trigger == cls` → CE11c (only possible once the VLM has chosen `cls`).

**Writing.**

14. `os.makedirs` for `<dir>/dataset/{stills,captions,videos}`, `<dir>/logs`, and the parents.
    - Seed mode: save `load_oriented_rgb(seed_path)` as `<dir>/seed.png` (PNG), and write `dataset/description.json` (`{"class_noun", "descriptor", "raw"}`, indent 2).
    - Call `register_trigger(trigger, name)`.
15. `write_character({...})` with `status: "dataset"`, `dataset: null`, `loras: {"video": null, "stills": null}`, `stills_skip_reason: null`, `strength: null`, and `created_at: utc_now()`.
16. `return build_dataset(data, fh)`.

**`--regenerate`** after its preflights:

- `prev_fh = data["dataset"]["face_height"] if data["dataset"] else None`.
- `shutil.rmtree(<dir>/dataset)`, then recreate `dataset/{stills,captions,videos}`.
- Set `status = "dataset"` and `dataset = None`, then `write_character`.
- `return build_dataset(data, prev_fh)`. The face check and describe are not rerun, and the seed is `data["seed"]`.

**`build_dataset(data, face_height)`** catches `(DatasetError, RuntimeError)` and prints `Error: <e>`. On those it returns 1 and leaves `status` at `"dataset"`, which is the recovery path for `--regenerate`.

1. **Seed mode only:** write `stills/char_00.png` as `ImageOps.fit(Image.open(seed.png).convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS, centering=(0.5, 0.5))`.
2. Build the Z-Image child spec:
   - jobs: one per `VARIANTS[i-1]`, `i = 1..24`, as `{"prompt": gen_prompt(shot, pose, setting, descriptor), "output_path": stills/char_%02d.png % i, "seed": data["seed"], "width": WIDTH, "height": HEIGHT}`;
   - `"loras": null`.
3. Print `=== generate ===`.
   - `story_server("stop")`. A non-zero rc prints `warning: story-server stop returned N`.
   - Inside `try`:
     - `wait_for_avail(GENERATE_MIN_AVAIL_GIB, AVAIL_WAIT_S)`. False → `DatasetError("timed out waiting for 20 GiB available memory after stopping the story server")`;
     - `report = run_zimage_child(spec, char_dir, "generate")`.
   - `finally`: `story_server("vision")`; then `wait_for_vlm(VLM_WAIT_S)`. False → `DatasetError("timed out waiting for the vision server to come back")`.
4. `ref_n = 0 if seed mode else 1`. If `stills/char_%02d.png % ref_n` is missing (blocked by the content screen) → `DatasetError("the reference still char_%02d was blocked by the content screen; edit the descriptor in <json> and run bin/character create NAME --regenerate")`.
5. Print `=== score ===`. For `n` in `range(0, 25)` (seed) or `range(1, 25)` (descriptor):
   - If `char_NN.png` is missing → item `identity_score 0`, `shot/pose/setting ""`, `kept False`, `reason "blocked by the content screen"`, `caption null`.
   - Else `check, reason = score_still(ref_png, png)`, and `kept = (n == ref_n) or check["identity_score"] >= MIN_SCORE`.
   - For kept items: write `captions/char_NN.txt = caption(trigger, class_noun, check)` (no trailing newline, as before). Then `wrap_still(png, videos/char_NN.mp4)`, then `verify_ffprobe`.
   - Each item is `{"n", "gen_prompt" (null for n == 0), "identity_score", "shot", "pose", "setting", "kept", "reason", "caption"}`, exactly as `make_dataset_seed.py:728-738`.
6. Write `dataset/manifest.json` (4.6) and `dataset/contact_sheet.jpg` (4.7).
7. `kept = count`, `total = len(items)`.
   - Set `data["dataset"] = {"reference": "char_%02d" % ref_n, "kept": kept, "total": total, "min_score": MIN_SCORE, "face_height": fh, "contact_sheet": <abs path>}`.
   - Set `status = "untrained" if kept >= MIN_KEEP else "dataset"`, then `write_character`.
   - `fh` is the `face_height` argument of `build_dataset(data, face_height)`:
     - for a new character, step 10's value (`None` in descriptor mode);
     - for `--regenerate`, the previous `dataset.face_height`, read before the reset (`None` if `dataset` was null). So it is preserved across `--regenerate` **[spec choice]**.
8. Print the table (`make_dataset_seed.py:756-761` format), then:

```
dataset: <kept>/<total> stills kept (minimum 12) in <dir>/dataset
contact sheet: <dir>/dataset/contact_sheet.jpg
next: review the contact sheet. To change the look, edit "descriptor" in <dir>/character.json and run bin/character create <name> --regenerate; otherwise run bin/character train <name>
```

   Return 0. If `kept < MIN_KEEP`, print CE22 to stderr instead of the `next:` line, and return 3.

**Helpers.**

- **`score_still`:** two attempts, each `vlm_call([CHECK_PROMPT text, ref image_url, candidate image_url])` → `extract_json` → `validate_check`. A `ValueError` twice → `({"identity_score": 0, "shot": "", "pose": "", "setting": ""}, "unparseable: %s" % e)`. A `RuntimeError` propagates.
- **`face_height` / `describe`:** two attempts each. A `ValueError` twice → `DatasetError("face check failed: %s; last reply: %r" % ...)` / `DatasetError("describe failed: %s; last reply: %r" % ...)`.
- **`wrap_still`:** the exact ffmpeg argv at `make_dataset_seed.py:719-725`. `check=True` becomes `DatasetError` on `CalledProcessError`.

### 4.5 Prompts (exact text)

```python
DESCRIBE_PROMPT = (
    'Describe the main character in this image for an image generator that must redraw the same '
    'person in many different poses and places. Reply with only a JSON object with two keys. '
    '"class_noun": one lowercase word for what they are (for example woman, man, girl, boy, person). '
    '"descriptor": one noun phrase of at most 45 words that starts with "a" or "an" and covers only '
    'what is visible about the character themselves: apparent age group, apparent ethnicity when it '
    'is visible, build, skin tone, hair colour, length and style, notable facial features, and the '
    'clothing and accessories they would wear anywhere. Leave out anything that belongs to this one '
    'situation rather than to the person: footwear, gear or props that are visible only because of '
    'what they are doing here (for example riding boots while riding, or a tool they are using), '
    'anything they are holding, and any animal or vehicle. Do not mention the background, the pose, '
    'the action, the camera, the lighting or the image style.'
)

FACE_PROMPT = (
    'Reply with only a JSON object with one key. "face_box": the bounding box of the main '
    "character's face, from the top of the forehead to the chin and from ear to ear, as "
    '[x1, y1, x2, y2] in coordinates from 0 to 1000, where 0,0 is the top-left corner of the image '
    'and 1000,1000 is the bottom-right corner; or null if no face is visible.'
)


def validate_face(d):
    """Face height as a fraction of the image height, or None when no face is visible.
    Raises ValueError on any malformed reply (spec 4.5)."""
    if "face_box" not in d:
        raise ValueError("missing key: face_box")
    box = d["face_box"]
    if box is None:
        return None
    if (not isinstance(box, list) or len(box) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box)):
        raise ValueError("face_box must be null or a list of 4 numbers, got %r" % (box,))
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError("face_box must satisfy 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000, "
                         "got %r" % (box,))
    return (y2 - y1) / 1000.0


def trigger_test_prompt(trigger, class_noun):
    return "%s %s, medium shot, standing and facing the camera, %s." % (trigger, class_noun, STYLE)
```

**Face-size measure [spec choice: a VLM bounding box, normalized 0-1000; height fraction against `FACE_MIN_HEIGHT = 0.15`].**

- Justification: the served model is Qwen3-VL, whose grounding output uses relative 0-1000 boxes. A box gives a number that can be tested against a threshold. A size category would be a second subjective judgment from the same lenient model.
- The image is sent through `image_data_url(seed_path)` (768 px max side). The coordinates are relative, so the downscale does not matter.
- It is a separate call from DESCRIBE, so a malformed box never invalidates a good descriptor.
- The 0-1000 convention on this server is unverified (G3). Live gate L1 calibrates it.

**Face messages (CE18).**

- Small face: `Error: the main character's face fills only <round(100*fh)>% of the seed image's height (minimum 15%); a small face makes a weak identity reference. Use a closer crop of the character, or pass --force to proceed anyway.`
- No face: `Error: the vision model found no face in the seed image; pass --force to proceed anyway.`

**VLM call shapes** are those of `make_dataset_seed.py`: a text part, then `image_url` parts, `temperature 0`, `max_tokens 600`, and `enable_thinking False`.

### 4.6 `dataset/manifest.json`

```json
{"seed_image": "<abs original path or null>", "trigger": "...", "class_noun": "...",
 "descriptor": "...", "seed": 0, "min_score": 7, "reference": "char_00",
 "face_height": 0.38, "items": [ ...4.4 step 5 items, in n order... ]}
```

It is written with `json.dump(..., indent=2)`.

### 4.7 Contact sheet [spec choice]

```python
def write_contact_sheet(items, stills_dir, out_path):
    cols, tw, th, lh = 5, 256, 160, 20
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + lh)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for k, item in enumerate(items):
        x, y = (k % cols) * tw, (k // cols) * (th + lh)
        path = os.path.join(stills_dir, "char_%02d.png" % item["n"])
        if os.path.isfile(path):
            with Image.open(path) as img:
                sheet.paste(img.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        if not item["kept"]:
            draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=(255, 0, 0), width=4)
        draw.text((x + 4, y + th + 3), "%02d  score %d  %s"
                  % (item["n"], item["identity_score"], "kept" if item["kept"] else "DROPPED"),
                  fill=(255, 255, 255))
    sheet.save(out_path, format="JPEG", quality=90)
```

Twenty-five items give a 1280x900 sheet.

### 4.8 Video LoRA training

**Config text** (`video_train_config`) is the spike config with the comments removed. Placeholders are filled with `json.dumps(value)`, and a JSON string is a valid YAML double-quoted scalar **[spec choice]**. `str.format` is used, and the template contains no literal braces:

```python
VIDEO_TRAIN_CONFIG_TEMPLATE = """model:
  model_path: {model_path}
  text_encoder_path: {gemma}
  training_mode: lora

lora:
  rank: 32
  alpha: 32
  dropout: 0.0
  target_modules:
    - to_k
    - to_q
    - to_v
    - to_out.0

optimization:
  learning_rate: 2.0e-4
  steps: 1000
  batch_size: 1
  gradient_accumulation_steps: 1
  max_grad_norm: 1.0
  weight_decay: 0.0
  scheduler_type: linear
  scheduler_params:
    start_factor: 1.0
    end_factor: 0.1

data:
  preprocessed_data_root: {data_root}

training_strategy:
  name: text_to_video
  generate_audio: false

flow_matching:
  timestep_sampling_mode: shifted_logit_normal

validation:
  prompts:
    - {validation_prompt}
  video_dims: [512, 320, 25]
  frame_rate: 24.0
  inference_steps: 8
  interval: 1000
  guidance_scale: 4.0
  stg_scale: 0.0
  seed: 42
  generate_audio: false
  skip_initial_validation: true

checkpoints:
  interval: 250
  keep_last_n: 10

seed: 42
output_dir: {output_dir}
"""


def video_train_config(data_root, validation_prompt, output_dir):
    return VIDEO_TRAIN_CONFIG_TEMPLATE.format(
        model_path=json.dumps(TRAIN_MODEL_DIR), gemma=json.dumps(SKILL.GEMMA_MODEL_ID),
        data_root=json.dumps(data_root), validation_prompt=json.dumps(validation_prompt),
        output_dir=json.dumps(output_dir))
```

**Argv.** The env is `dict(os.environ, HF_HOME=SKILL.LTX2_MLX_HF_HOME)` and the cwd is `SKILL.LTX2_MLX_DIR`.

```python
def preprocess_argv(videos, captions, out_dir):
    return [SKILL.LTX2_MLX_BIN, "preprocess", "--videos", videos, "--captions", captions,
            "-o", out_dir, "-m", TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]


def train_argv(config_path):
    return [SKILL.LTX2_MLX_BIN, "train", "--config", config_path, "--low-ram"]
```

**`run_logged(cmd, log_path, cwd, env, timeout_s)`.**

- It runs `subprocess.Popen(cmd, cwd=cwd, env=env, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, start_new_session=True)`.
- It streams each line to `sys.stdout` and to `log_path` (opened `"a"`).
- A `threading.Timer(timeout_s)` calls `os.killpg(os.getpgid(pid), SIGKILL)`, the same as `ltx2_mlx_video_skill._run_subprocess`.
- It returns the returncode, or `-9` after a timeout kill. It first prints `Running: <shlex.join(cmd)>` and `log: <log_path>`.
- `step_log_path(char_dir, step)` = `<char_dir>/logs/<UTC %Y%m%dT%H%M%SZ>-<step>.log`. Every "log step `<s>`" in this section means `step_log_path(<dir>, "<s>")`.

**`train_video(data)`.** It returns `"ok"`, `"failed"` (CT10: nothing recorded, after printing an `Error:` line), or `"test_failed"` (CT11: the LoRA is recorded, but a test render failed).

1. `vdir = <dir>/train/video`. If it exists, `shutil.rmtree(vdir)`. Then `os.makedirs(vdir)` and `os.makedirs` of `<dir>/lora`, `<dir>/tests`, `<dir>/logs`.
2. Write `vdir/train.yaml` = `video_train_config(vdir + "/preprocessed", trigger_test_prompt(trigger, class_noun), vdir + "/out")`.
3. Run preprocess: `preprocess_argv(<dir>/dataset/videos, <dir>/dataset/captions, vdir + "/preprocessed")`, with timeout `PREPROCESS_TIMEOUT_S`.
   - rc != 0 → CT10 with step `preprocess`.
   - `n_lat = len(os.listdir(vdir/preprocessed/.precomputed/latents))` (a missing dir counts as 0) must equal the number of `*.mp4` files in `dataset/videos`. Otherwise → `Error: preprocess wrote <n_lat> latents for <n_vid> videos; log: <log>` (exit 1).
4. Run train: `train_argv(vdir/train.yaml)`, with timeout `VIDEO_TRAIN_TIMEOUT_S`.
   - rc != 0, or `vdir/out/checkpoints/lora_weights_step_01000.safetensors` missing or empty → CT10 with step `train`.
5. `shutil.copy2(final, <dir>/lora/video.safetensors.tmp)`, then `os.replace` to `<dir>/lora/video.safetensors`. Compute sha256 in 1 MiB blocks.
6. Set `data["loras"]["video"] = {path, sha256, "base_model": TRAIN_MODEL_DIR, "rank": 32, "alpha": 32, "steps": 1000, "trained_at": utc_now(), "sample_path": None, "control_path": None}` and `data["status"] = "trained"`, then `write_character(data)`. The LoRA is recorded **before** the test renders, so a test-render failure never loses a trained LoRA **[spec choice]**.
7. Run two test renders: first with the LoRA, then the control. Each is `SKILL.generate_video(trigger_test_prompt(...), <dir>/tests/video_lora.mp4 | video_control.mp4, image_path=None, width=512, height=320, num_frames=25, frame_rate=24, seed=TEST_SEED, model=TEST_MODEL_DIR, gemma=SKILL.GEMMA_MODEL_ID, low_ram=True, log_path=step_log_path(dir, "test-video-lora" | "test-video-control"), timeout_s=TEST_RENDER_TIMEOUT_S, force=True)`, with `loras=[(lora_path, 1.0)]` on the first call only. These parameters match the spike A/B (512x320, 25 frames, 24 fps, distilled, the 2.5 q8 pack).
   - A `ValueError` or `SKILL.Ltx2MlxError` → print `Error: video test render failed: <e>`, and remember the failure.
   - Record each successful path in `sample_path`/`control_path`, then `write_character`.
8. Print:

```
video LoRA: <dir>/lora/video.safetensors (sha256 <hex>)
trigger-only A/B (compare by eye; the LoRA clip should show the character, the control a stranger):
  with LoRA: <sample_path>
  control:   <control_path>
```

   Return `"test_failed"` if a test render failed, else `"ok"`. Every CT10 path in steps 3-4 returns `"failed"`.

### 4.9 Stills LoRA training (mflux) and the compat gate

**Epoch arithmetic [spec choice].** The run gets about 2400 steps whatever the kept count, and exactly 4 checkpoints, the last one at the final step:

```python
def stills_epochs(kept):
    """(num_epochs, total_steps, save_frequency): num_epochs is a multiple of 4 and
    save_frequency divides total_steps exactly (spec 4.9)."""
    quarter = -(-STILLS_TARGET_STEPS // (4 * kept))     # ceil
    num_epochs = 4 * quarter
    return num_epochs, num_epochs * kept, quarter * kept
```

`stills_epochs(24) == (100, 2400, 600)`, `stills_epochs(12) == (200, 2400, 600)`, and `stills_epochs(17) == (144, 2448, 612)`. The 2400 figure follows the published Z-Image Turbo practice for 10-30 images (lr 1e-4, rank 16, 2500-3000 steps). It is provisional: L0 measures s/step (G14).

**Config (`stills_train_config`).** `json.dump(..., indent=2)` writes it to `<dir>/train/stills/train.json`. The keys come from mflux's `_example/train.json`, plus `gradient_checkpointing` from mflux's common README:

```python
def stills_train_config(data_dir, output_dir, seed, kept):
    num_epochs, total_steps, save_frequency = stills_epochs(kept)
    modules = ["attention.to_q", "attention.to_k", "attention.to_v", "attention.to_out.0",
               "feed_forward.w1", "feed_forward.w2", "feed_forward.w3"]
    return {
        "model": "z-image-turbo",
        "data": data_dir,
        "seed": seed,
        "steps": 9,
        "guidance": 0.0,
        "quantize": None,
        "max_resolution": 1024,
        "low_ram": False,
        "gradient_checkpointing": True,
        "training_loop": {"num_epochs": num_epochs, "batch_size": 1,
                          "timestep_low": 4, "timestep_high": 9},
        "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
        "checkpoint": {"save_frequency": save_frequency, "output_path": output_dir},
        "monitoring": {"preview_width": 1024, "preview_height": 640,
                       "plot_frequency": 100, "generate_image_frequency": total_steps},
        "lora_layers": {"targets": [
            {"module_path": "layers.{block}." + m, "blocks": {"start": 0, "end": 30},
             "rank": STILLS_RANK} for m in modules]},
    }
```

Choices made here:

- **Targets [spec choice]:** attention and feed-forward only, across all 30 blocks. The example's `cap_embedder.1` and `all_final_layer.2-1.linear` are dropped, because their diffusers-side names are the least likely to map (G1).
- `"quantize": None` (bf16 base) matches the bf16 base that z_image_skill fuses into **[spec choice]**.

**`train_stills(data)`.** It returns `"ok"`, `"skipped"` (incompatible; the reason is recorded), or `"failed"` (a runtime failure).

1. `sdir = <dir>/train/stills`. If it exists, `shutil.rmtree(sdir)`. Then `os.makedirs(sdir/data)` and `os.makedirs(sdir/out)`.
2. For each kept item: `shutil.copy2` `dataset/stills/char_NN.png` → `sdir/data/char_NN.png`, and `dataset/captions/char_NN.txt` → `sdir/data/char_NN.txt`. Write `sdir/data/preview_1.txt` = `trigger_test_prompt(...)`.
3. Write `sdir/train.json`. Run `[MFLUX_TRAIN, "--config", sdir/train.json]` with cwd `sdir`, env `dict(os.environ, HF_HOME=MFLUX_HF_HOME)`, timeout `STILLS_TRAIN_TIMEOUT_S`, and log step `train-stills`.
   - `HF_HOME` points at the internal `~/hf_home`, so the 31 G Z-Image-Turbo cache is reused and the training adapter downloads there, not to the USB global cache **[spec choice]**.
   - rc != 0 → `Error: stills LoRA training failed: mflux-train exited <rc>; log: <log>`, return `"failed"`.
4. Run `extract_mflux_adapter(sdir/out, <dir>/lora/stills.candidate.safetensors)`:
   - `zips = glob.glob(os.path.join(out_dir, "**", "*_checkpoint.zip"), recursive=True)`. A recursive glob is used because the exact subfolder layout is unverified (G14).
   - Take the zip whose basename's leading integer is largest.
   - Its members ending in `_adapter.safetensors` must be exactly 1; extract that member's bytes to `dest`.
   - No zip, or not exactly 1 adapter member → `DatasetError("mflux-train wrote no checkpoint zip with exactly one *_adapter.safetensors under %s" % out_dir)` → print `Error: <e>`, return `"failed"`.
5. `expected = lora_module_count(safetensors_keys(candidate))`. The stdlib parsers are:

```python
def safetensors_keys(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n).decode("utf-8"))
    return sorted(k for k in header if k != "__metadata__")


def lora_module_count(keys):
    return len({k.split(".lora")[0] for k in keys if ".lora" in k})
```

6. **Compat gate.** Run `report = run_zimage_child({"jobs": [{"prompt": trigger_test_prompt(...), "output_path": <dir>/tests/stills_lora.png, "seed": TEST_SEED, "width": 1024, "height": 640}], "loras": [[candidate, 1.0]]}, dir, "test-stills-lora")`. The result is **incompatible** when:
   - the child failed (`DatasetError`): reason `"Z-Image could not load or render with it (see <log>)"`;
   - `expected == 0`: reason `"the adapter file has no LoRA modules"`;
   - `report["injected_lora_modules"] != expected`: reason `"only <injected> of <expected> LoRA modules in the adapter matched the Z-Image transformer"`.
7. **Incompatible:**
   - `os.replace(candidate, <dir>/lora/stills.rejected.safetensors)`;
   - `data["stills_skip_reason"] = "mflux adapter incompatible with z_image_skill: " + reason`;
   - leave `loras.stills` unchanged (a previous good stills LoRA survives a failed `--force` retrain) **[spec choice]**;
   - `write_character`;
   - print `stills LoRA skipped: <stills_skip_reason>; the video LoRA is unaffected`;
   - return `"skipped"`.
8. **Compatible:**
   - `os.replace(candidate, <dir>/lora/stills.safetensors)`;
   - run the control child (same job with `output_path` `tests/stills_control.png`, and `"loras": null`, step `test-stills-control`). A control failure leaves `control_path` null and prints `Error: stills control render failed: <e>`, but does not fail the stills LoRA;
   - set `loras.stills = {path, sha256, "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16, "steps": total_steps, "trained_at", "sample_path": tests/stills_lora.png if the job status was "ok" else None, "control_path"}`;
   - set `stills_skip_reason = None`, then `write_character`;
   - print `stills LoRA: <path>` and the two image paths;
   - return `"ok"`.

**Z-Image child protocol (`run_zimage_child` / `child_zimage`).**

- **Parent.**
  - It writes `spec` plus `"report_path"` to `<log stem>.spec.json`.
  - It runs `[sys.executable, os.path.join(WS, "character_dataset.py"), "zimage", "--spec", spec_path]` through `run_logged` (cwd `WS`, env `os.environ`, timeout `ZIMAGE_CHILD_TIMEOUT_S`).
  - rc != 0 → `DatasetError("Z-Image child process exited %d; log: %s" % (rc, log))`. Otherwise it returns the parsed report.
- **Child** (`main(["zimage", "--spec", P])` → `child_zimage(P)`). It imports `torch`, `z_image_skill`, and `from content_safety import ContentSafetyError`. For each job:

```python
kwargs = {"loras": [tuple(x) for x in spec["loras"]]} if spec["loras"] else {}
try:
    z_image_skill.generate_image(job["prompt"], output_path=job["output_path"],
                                 width=job["width"], height=job["height"],
                                 generator=torch.Generator("cpu").manual_seed(job["seed"]), **kwargs)
    status = "ok"
except ContentSafetyError:
    status = "blocked"
```

  After all jobs it computes:

```python
injected = None
if spec["loras"] and z_image_skill._pipeline is not None:
    injected = sum(1 for module in z_image_skill._pipeline.transformer.modules()
                   if isinstance(getattr(module, "lora_A", None), torch.nn.ModuleDict)
                   and "lora0" in module.lora_A)
```

  Then it writes `{"jobs": [{"output_path", "status", "seconds"}], "injected_lora_modules": injected}` to `report_path` and returns 0. Any other exception propagates (traceback in the log, exit 1).

### 4.10 mflux installation (user-gated)

- Installing is a user-visible action. **The plan must ask the user before running these commands, and must not run them unapproved.**
- The location is an isolated venv at `~/mflux/.venv`, mirroring `~/ltx-2-mlx/.venv` **[spec choice]**. The reason is that mflux 0.21.0 needs torch >= 2.13, while the workspace interpreter's torch 2.12.1 backs z_image_skill (0.2).

```
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 -m venv ~/mflux/.venv
~/mflux/.venv/bin/python -m pip install 'mflux==0.21.0'
~/mflux/.venv/bin/mflux-train --help
```

- **Verified from mflux's docs:** the `mflux-train --config PATH` CLI; `mflux-train --resume CHECKPOINT.zip`; every key in 4.9 except `gradient_checkpointing` (that one is documented in prose, not in the example); the data layout (`NN.txt` + image, optional `preview*.txt`); and the checkpoint zip naming.
- **Unverified:** whether `gradient_checkpointing` is a top-level key; the output subfolder layout; whether "steps" = epochs x images; the adapter's tensor key names; and the s/step and peak memory on this host. L0 measures these.

### 4.11 `train(args)` (normative order)

1. `data = load_character(name)` (CT1). `status == "dataset"` → CT2.
2. `requested = [k for k in ("video", "stills") if getattr(args, k)] or ["video", "stills"]`, and `explicit_stills = args.stills`.
3. For each k in `requested`: if `data["loras"][k] is not None and not args.force` → CT3.
4. Preflights, in this order, each exiting 2:
   - `library_lock()` (CT4a) and `busy_process()` (CT4b);
   - `story_server_state() != "STOPPED"` (CT5);
   - `psutil.virtual_memory().available / 2**30 < TRAIN_MIN_AVAIL_GIB` (CT6). The 30 GB of the design is read as 30 GiB **[spec choice]**;
   - `free_gib(<dir>) < TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)` (CT7);
   - if `"video"` is requested: `TRAIN_MODEL_DIR/transformer-dev.safetensors` is not a file, or `transformer.safetensors` or `transformer-distilled.safetensors` exists there → CT8a; `TEST_MODEL_DIR` is not a dir → CT8b; `SKILL.LTX2_MLX_BIN` is not executable → CT8c.
5. If `"stills"` is requested and `MFLUX_TRAIN` is not an executable file:
   - set `data["stills_skip_reason"] = "mflux-train not found at %s" % MFLUX_TRAIN` and `write_character`;
   - print `stills LoRA skipped: <reason>; install mflux as described in docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10`;
   - remove `"stills"` from `requested`, and set `stills_outcome = "skipped"`.
6. If `"video"` is requested: `video_outcome = train_video(data)`.
   - `"failed"` (CT10): `train` returns 1 at once, before stills are attempted.
   - `"test_failed"` (CT11): stills still run.
   - If video is not requested, `video_outcome = "ok"`.
7. If `"stills"` is requested: `stills_outcome = train_stills(data)` (otherwise it keeps its step-5 value, or `"ok"`).
8. The exit code is 1 if `video_outcome == "test_failed"`, if `stills_outcome == "failed"`, or if `stills_outcome == "skipped" and explicit_stills`. Otherwise it is 0.

Everything after the preflights runs inside `library_lock()`.

### 4.12 Safety gates (shared by `create` and `train`)

**`library_lock()`.**

- It acquires `<lib>/.lock` with `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` and writes `str(os.getpid())`. `os.makedirs(lib, exist_ok=True)` runs first.
- On `FileExistsError` it reads the pid:
  - alive (`os.kill(pid, 0)` succeeds) → `DatasetError("another bin/character create/train is running (pid %d); run one at a time" % pid)`;
  - dead or unreadable → remove the file and retry once.
- It releases the lock in `finally` by removing the file.
- `create` and `train` catch that acquire-time `DatasetError`, print `Error: <e>`, and return 2 (CE14/CT4a). A `DatasetError` raised later, inside the locked body, keeps its own exit code (1).

**`busy_process()`.**

- It iterates `psutil.process_iter(["pid", "cmdline"])`, skipping `os.getpid()` and its parent, and ignoring `NoSuchProcess`/`AccessDenied`.
- With `joined = " ".join(cmdline or [])`, it returns `(pid, joined[:120])` for the first process where:
  - `"ltx-2-mlx" in joined and any(t in (cmdline or []) for t in ("generate", "train", "preprocess"))`, or
  - any of `"mflux-train"`, `"bin/ltx-movie"`, `"bin/ltx-mlx-render"`, `"bin/ltx-story-images"`, `"character_dataset.py zimage"` is in `joined`.
- Otherwise it returns `None`.
- It is fail-closed **[spec choice]**. CT4b/CE15 message: `Error: a render or training process is running (pid <pid>: <cmd>); bin/character never trains or generates concurrently with a render`.

**`story_server_state()`.**

- It runs `[STORY_SERVER, "status"]`, captured with a 60 s timeout.
- It parses the first line matching `^\s*state:\s*(.+?)\s*$` and returns the group.
- On any failure (OSError, timeout, or no such line) it returns `"UNKNOWN"`, which fails closed.

**`vlm_ready()`.** It sends GET `MODELS_URL` (10 s timeout) and checks `VLM_MODEL in [m["id"] for m in body["data"]]`. Any exception → False.

**`story_server(cmd)`** and **`wait_for_vlm`** are `make_dataset_seed.py:600-668`, factored out: the last 5 output lines are printed, and the vision wait polls every 10 s up to `timeout_s`.

**`wait_for_avail(min_gib, timeout_s)`** polls `psutil.virtual_memory().available` every 5 s and returns a bool.

**`free_gib(path)`** = `shutil.disk_usage(<path, or its nearest existing ancestor>).free / 2**30`.

### 4.13 Disk budget per character (measured from the spike, plus estimates)

| Item | Size | Basis |
|---|---|---|
| `dataset/` (25 PNG stills, 24 mp4s, captions, contact sheet) | ~18 MB | spike: stills 16 M, videos 0.5 M |
| `train/video/preprocessed` | ~0.6 GB | spike: 578 M |
| `train/video/out` (4 checkpoints + sample) | ~2.6 GB | spike: 4 x 641,974,104 B |
| `lora/video.safetensors` | 0.64 GB | copy of the final checkpoint |
| `train/stills/out` (4 zips with adapter + optimizer state) | ~1.5-2 GB | **estimate**: rank-16 adapter on 210 modules ~70-140 MB; AdamW state ~2x |
| `lora/stills.safetensors` | ~70-140 MB | estimate |
| `tests/` | <1 MB | spike A/B: 104 KB + 132 KB |
| **Total** | **~4 GB video-only; ~6 GB with stills** | |

The one-time mflux training adapter download goes into `~/hf_home` and is shared.

**Preflights:** `create` needs 2 GiB free; `train` needs 8 GiB per requested kind (CT7). With 66 GiB free today, that is about ten fully trained characters before pruning `train/*/out` is needed (G18).

---

## 5. Pipeline integration

### 5.1 `ltx2_mlx_video_skill.py`

- **`build_command`.** It gains a keyword `loras=None` (last in the signature). If `lora_path is not None and loras`, it raises `ValueError("lora_path and loras are mutually exclusive")`. Directly after the existing `if lora_path is not None:` block, it adds:

```python
    for path, strength in (loras or ()):
        cmd += ["--lora", str(path), repr(float(strength))]
```

  The strength token is `repr(float(s))`, so `1.0 → "1.0"`, `0.8 → "0.8"`, and `0.6 → "0.6"` **[spec choice]**.
- **(Amendment 2)** The module gains `parse_lora_spec` (5.7.1).
  - The `lora_path`/`loras` mutual-exclusion `ValueError`s here and in z_image_skill (5.2) are **kept, as internal API invariants** **[spec choice]**. Every caller merges global and character LoRAs into the single ordered `loras` list, or uses `lora_path` alone on the legacy route (5.7.2), so the combination the user wants never needs both.
  - Keeping one list means the argv, the adapter order and the provenance list are all the same object. Allowing both would leave two orderings to reconcile.
- **`generate_video`.** It gains a keyword `loras=None` (last), and passes `loras=loras` to `build_command`. It also passes `lora_path=lora_path, loras=loras` as **keywords** to `_validate_generate_args`, which gains `lora_path=None, loras=None` at the end of its signature. These checks are added **after** the tile checks:

```python
    if loras is not None:
        if lora_path is not None and loras:
            raise ValueError("lora_path and loras are mutually exclusive")
        if not isinstance(loras, (list, tuple)):
            raise ValueError("loras must be a list of (path, strength) pairs, got %r" % (loras,))
        for i, item in enumerate(loras):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("loras[%d] must be a (path, strength) pair, got %r" % (i, item))
            path, strength = item
            if (not isinstance(path, str) or not os.path.isfile(path)
                    or not os.access(path, os.R_OK)):
                raise ValueError("loras[%d]: path is not a readable file: %r" % (i, path))
            if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                    or not 0 < strength <= 2.0):
                raise ValueError("loras[%d]: strength must be a number in (0, 2], got %r"
                                 % (i, strength))
```

- `loras=[]` emits no `--lora` token.
- `loras` accepts local files only, never HF repo IDs **[spec choice]**.
- The CLI (`build_cli_parser`) is unchanged.
- The docstring of `build_command` gains one sentence on `loras`.

### 5.2 `z_image_skill.py` (multi-adapter) [spec choice: diffusers adapter names + `set_adapters` + one `fuse_lora`]

**Justification.**

- `set_adapters(names, adapter_weights=[…])` followed by `fuse_lora(adapter_names=names, lora_scale=1.0)` merges the weighted sum of the deltas in **one** fuse. That is the same summed-delta semantics as `ltx-2-mlx --lora`.
- It keeps the existing "no per-call overhead after load" property.
- Adapter names are required, because loading a second LoRA needs a distinct name. They also let the compat gate check registration through `get_list_adapters()`.
- Sequential `load → fuse → unload` per LoRA was rejected. It fuses N times, and an unfused-then-unloaded adapter cannot be inspected by the gate.

**Code.**

```python
def load_pipeline(lora_path=None, loras=None):
    if lora_path is not None and loras:
        raise ValueError("lora_path and loras are mutually exclusive")
    ... (unchanged through pipeline.vae.to(torch.float32)) ...
    if lora_path is not None:
        ... (unchanged three lines) ...
    elif loras:
        names = []
        for i, (path, strength) in enumerate(loras):
            name = "lora%d" % i
            print(f"[z_image_skill] loading LoRA {path} as adapter {name} (strength {strength})")
            pipeline.load_lora_weights(path, adapter_name=name)
            if name not in pipeline.get_list_adapters().get("transformer", []):
                raise ValueError(f"LoRA {path} matched no Z-Image transformer weights; it is not "
                                 f"a compatible Z-Image LoRA")
            names.append(name)
        pipeline.set_adapters(names, adapter_weights=[float(s) for _, s in loras])
        pipeline.fuse_lora(adapter_names=names, lora_scale=1.0)
        print(f"[z_image_skill] fused {len(names)} LoRA adapter(s)")
    return pipeline


_pipeline = None
_pipeline_loras = None


def _get_pipeline(lora_path=None, loras=None):
    global _pipeline, _pipeline_loras
    key = tuple((str(p), float(s)) for p, s in loras) if loras else None
    if _pipeline is None:
        _pipeline = (load_pipeline(lora_path=lora_path, loras=loras) if loras
                     else load_pipeline(lora_path=lora_path))
        _pipeline_loras = key
    elif key is not None and key != _pipeline_loras:
        raise RuntimeError("z_image_skill's pipeline is already loaded with LoRA set %r; LoRA set "
                           "%r needs a new process" % (_pipeline_loras, key))
    return _pipeline


def generate_image(prompt: str, output_path: str = None, lora_path=None, loras=None, **kwargs):
    pipeline = (_get_pipeline(lora_path=lora_path, loras=loras) if loras
                else _get_pipeline(lora_path=lora_path))
    ... (unchanged) ...
```

- When `loras` is falsy, every call is made exactly as before (`load_pipeline(lora_path=…)` and `_get_pipeline(lora_path=…)`). The pinned `test_z_image_skill_cache.py` cases and any monkeypatched fakes keep working.
- The existing silent-ignore behavior for a later `lora_path` is unchanged. The new `RuntimeError` covers `loras` only.
- The docstrings of `load_pipeline` and `generate_image` gain one sentence each on `loras`.

### 5.3 `bin/ltx-mlx-render`

**(a) `load_manifest`.** Inside the per-panel loop, after the schema-3 conditioning checks and before the `panel_text` check:

```python
        if "characters" in panel:
            characters = panel["characters"]
            if not isinstance(characters, list):
                raise ValueError("panel %d: characters must be a list" % index)
            seen = set()
            for entry in characters:
                name = entry.get("name") if isinstance(entry, dict) else None
                if not isinstance(name, str) or not name:
                    raise ValueError("panel %d: every characters entry needs a non-empty name" % index)
                if name in seen:
                    raise ValueError("panel %d: character %s is listed more than once" % (index, name))
                seen.add(name)
                lora = entry.get("video_lora")
                if (not isinstance(lora, str) or not os.path.isabs(lora) or not os.path.isfile(lora)
                        or not os.access(lora, os.R_OK)):
                    raise ValueError("panel %d: character %s's video_lora is not a readable file: %r"
                                     % (index, name, lora))
                strength = entry.get("strength")
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: character %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, name, strength))
```

**(b) `build_units`.** It is superseded by amendment 2. The signature becomes `build_units(panels, seed, clips_dir, run_root=None, global_loras=())`. The unit dict is built exactly as today. Then:

```python
        loras = [{"kind": "global", "name": None, "path": g["path"], "strength": g["strength"]}
                 for g in global_loras]
        loras += [{"kind": "character", "name": c["name"], "path": c["video_lora"],
                   "strength": float(c["strength"])} for c in (panel.get("characters") or [])]
        if loras:
            unit["loras"] = loras
```

- The `"loras"` key exists **only** when the list is non-empty, so test R4l's 9-key set holds for every uncast unit. The legacy route (5.7.2) has `global_loras == []`.
- Both `main` call sites (dry run and real run) pass `global_loras=args.global_loras`.

**(c) Provenance.** A module cache, plus the addition at the end of `build_clip_provenance` (the dict literal is unchanged):

```python
_LORA_SHA256_CACHE = {}


def lora_sha256(path):
    """file_sha256, memoized on (realpath, size, mtime_ns): a 642 MB LoRA is hashed once per
    process, not three times per panel; a rewritten file changes the key and is re-hashed."""
    info = os.stat(path)
    key = (os.path.realpath(path), info.st_size, info.st_mtime_ns)
    if key not in _LORA_SHA256_CACHE:
        _LORA_SHA256_CACHE[key] = file_sha256(path)
    return _LORA_SHA256_CACHE[key]
```

```python
    provenance = { ...unchanged literal... }
    if unit.get("loras"):
        provenance["loras"] = [{"kind": l["kind"], "path": l["path"],
                                "sha256": lora_sha256(l["path"]), "strength": l["strength"]}
                               for l in unit["loras"]]
    return provenance
```

- The character name is not part of provenance **[spec choice]**: identity is the bytes plus the strength.
- **(Amendment 2)** Each entry records `kind` (`global` or `character`), and the list is **ordered**: globals in CLI order, then characters by name. Order and kind are part of the reuse decision **[spec choice]**.
  - The deltas sum, so order does not change the math. Recording it exactly is the conservative choice: a reordered `--lora` list re-renders rather than risk a wrong reuse.
  - On the legacy route, `lora_path` carries the single global LoRA exactly as today, and there is no `loras` key.
- `clip_is_reusable` is unchanged. It compares the full canonical JSON, so:
  - a different LoRA set is not reused;
  - different bytes are not reused;
  - a different strength is not reused;
  - an uncast clip versus a cast clip of the same panel is not reused;
  - a cast panel whose match list is empty produces the same provenance as uncast, and that is correct, because the argv is the same.
- `render_panel`'s pre-render and post-render provenance comparison detects a LoRA rewritten mid-render: the mtime changes, the cache misses, and the new hash differs.

**(d) `render_panel`.** Directly before the `SKILL.generate_video(` call:

```python
        extra = ({"loras": [(l["path"], l["strength"]) for l in unit["loras"]]}
                 if unit.get("loras") else {})
```

`**extra` is appended to the call's keyword arguments. The keyword set seen by an uncast call is unchanged (R33 still sees `lora_path`).

**(e) `print_dry_run`.**

- The same `extra` is built for `first`, and `**extra` is passed into `SKILL.build_command`.
- In the per-panel listing, after each panel's existing line, for each `l in unit.get("loras", [])` it prints `"            lora: %s @ %s (%s)" % (l["path"], repr(l["strength"]), l["name"] or "global")`.

**(f) `main`.** It is superseded by amendment 2: the `--lora` + cast refusal is **removed**. Directly after the chained `--on-panel-failure skip` check, and before the `--dry-run` short-circuit, `main` runs the 5.7.3 global-LoRA resolution. The `--lora` flag becomes repeatable `PATH[:STRENGTH]` (5.7.1). There are no other CLI changes.

### 5.4 `bin/ltx-story-manifest`

**Arguments** (after `--frames`):

```python
    parser.add_argument("--cast", dest="cast", action="append", default=None,
                         metavar="PHRASE=NAME",
                         help="cast a trained character (generated/characters/NAME) under PHRASE "
                              "(repeatable; --chain only): its trigger is inserted into every "
                              "Motion: text that names PHRASE, and the panel's 'characters' list "
                              "carries its video LoRA and strength")
    parser.add_argument("--character-strength", dest="character_strength", type=float,
                         default=None,
                         help="LoRA strength for each cast character in a panel that names two "
                              "or more of them (default 0.8, provisional); one character always "
                              "uses 1.0")
```

`import importlib.machinery` is added to the stdlib imports, along with the helper:

```python
def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()
```

**Validation** (in `main`, right after the existing `--chain` checks):

```python
    if args.cast and not args.chain:
        parser.error("--cast requires --chain")
    if args.character_strength is not None and not args.cast:
        parser.error("--character-strength requires --cast")
```

**Resolution** (right after the `--prompts-md` parse block, before frame allocation):

```python
    members, strength = [], None
    if args.cast:
        lib = _character_lib()
        strength = (args.character_strength if args.character_strength is not None
                    else lib.DEFAULT_CHARACTER_STRENGTH)
        if not 0 < strength <= 1.0:
            print("Error: --character-strength must be in (0, 1], got %r" % strength, file=sys.stderr)
            return 2
        try:
            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])
        except lib.CharacterError as e:
            print("Error: %s" % e, file=sys.stderr)
            return 2
```

**Application.** After the `panels` list is built and **before** the `_prompt_length_warning` loop:

```python
    if members:
        by_name = {m.name: m for m in members}
        used = set()
        for p in panels:
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)
            strengths = lib.panel_strengths(names, members, strength)
            p["characters"] = [{"name": n, "phrase": by_name[n].phrase, "trigger": by_name[n].trigger,
                                "video_lora": by_name[n].video_lora, "strength": strengths[n]}
                               for n in names]
            used.update(names)
        for m in members:
            if m.name not in used:
                print("WARNING: cast phrase %r (character %s) occurs in no panel's Motion: text; "
                      "that character gets no LoRA" % (m.phrase, m.name))
```

What this does:

- Only `motion_prompt` (the render prompt) gets triggers. `panel_text` is left as authored for every panel **[spec choice]**, so the opening-still description and the chain panels' `panel_text` keep their authored wording.
- Every panel carries `characters` (possibly `[]`) exactly when `--cast` was given. Entries are sorted by name, because `cast_text` returns sorted names.
- `schema_version` stays 3, since the key is optional **[spec choice]**.

**Output.** After the `TOTAL …` line, only when `members` is non-empty, one line per panel with characters: `"cast: panel %d: %s" % (index, ", ".join("%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"]))`.

The docstring gains a paragraph describing `--cast` and the `characters` key.

### 5.5 `bin/ltx-story-images`

**Arguments.** These go after `--lora`, with the same `--cast` and `--character-strength` definitions as 5.4. The help says the trigger is inserted into Image: prompts for characters that have a stills LoRA. `_character_lib()` is the same helper; `importlib.machinery` is already imported.

**Validation** (after the `--seed-image` existence check, before the dry-run). `strength` and `members` are resolved exactly as in 5.4's resolution block. Each failure exits 2:

- `--character-strength` without `--cast` → `Error: --character-strength requires --cast`.
- ~~`--cast` with `--lora`~~: **removed by amendment 2.** Global stills LoRAs combine with the cast (5.7.4).
- `--character-strength` outside (0, 1] → the same message as in 5.4.
- `resolve_cast` raises `CharacterError` → `Error: <e>`.

**Planning** (only when `members`; amendment 2 then prepends the global stills LoRAs, 5.7.4):

```python
    stills_members = [m for m in members if m.stills_lora]
    for m in members:
        if not m.stills_lora:
            print("WARNING: character %s has no stills LoRA (%s); its trigger is not inserted into "
                  "Image: prompts and panel stills render without it"
                  % (m.name, m.stills_skip_reason or "not trained"))
    plans = {}
    for i in selected_indices:
        if args.seed_image is not None and i == 1:
            continue
        prompt, names = lib.cast_text(_compose_prompt(panels[i - 1]["image"], style), stills_members)
        strengths = lib.panel_strengths(names, stills_members, strength)
        by_name = {m.name: m for m in stills_members}
        plans[i] = (prompt, [{"kind": "character", "name": n, "path": by_name[n].stills_lora,
                              "strength": strengths[n]} for n in names])
    lora_sets = sorted({tuple((l["path"], l["strength"]) for l in v[1]) for v in plans.values()})
    if len(lora_sets) > 1:
        print("Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
              "set per process); run one --only panel per invocation", file=sys.stderr)
        return 2
```

**Dry run.**

- For a planned panel, it prints the existing line format with the **cast** prompt in place of the plain one, then `"    loras: %s" % (", ".join("%s=%s@%s" % (l["name"], l["path"], repr(l["strength"])) for l in loras) or "none")`.
- Uncast dry-run output is unchanged.

**Generation.**

- For a planned panel, `prompt` is `plans[i][0]`. `lora_kwargs = {"loras": [(l["path"], l["strength"]) for l in plans[i][1]]} if plans[i][1] else {}`.
- The call stays textually `lora_path=args.lora_path,` (test I21), with `**lora_kwargs,` appended as its last argument.
- Each `results` entry for a planned panel gains `"loras": plans[i][1]` (the key appears only under `--cast`) **[spec choice]**. Its `prompt` is the cast prompt.
- The `--seed-image` panel 1 and the uncast paths are unchanged.

### 5.6 `bin/ltx-movie`

**(a) Arguments** (directly after `--stills-lora`):

```python
    parser.add_argument("--character", dest="characters", action="append", default=None,
                         metavar="NAME",
                         help="cast a trained character from generated/characters/ (repeatable). "
                              "For a new story, Phase 1's prompt gets a Cast block with the "
                              "character's fixed referring phrase and description; every panel "
                              "whose prompt names that phrase renders with the character's "
                              "LoRAs. See docs/superpowers/specs/"
                              "2026-10-05-character-library-design.md.")
    parser.add_argument("--cast", dest="casts", action="append", default=None,
                         metavar="PHRASE=NAME",
                         help="cast a trained character under PHRASE in an EXISTING story.md "
                              "(repeatable); PHRASE must occur in story.md")
    parser.add_argument("--character-strength", dest="character_strength", type=float,
                         default=None,
                         help="LoRA strength for each cast character in a panel that names two "
                              "or more of them (default 0.8, provisional); a panel that names "
                              "one cast character always uses 1.0")
    parser.add_argument("--list-characters", dest="list_characters", action="store_true",
                         default=False,
                         help="print the character library table (the same as bin/character "
                              "list) and exit; must be the only argument")
```

`--list-characters` is registered so that it appears in `--help`. `main` handles it before argparse runs (5.6(i)), so argparse never acts on it. This adds one `--help` entry and changes no existing help substring, so test L1 still passes.

**(b) Helpers.**

```python
def _character_lib():
    """character_lib.py, loaded by path and only when casting is used, so an uncast run never
    reads it (spec 1.2)."""
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


def _resolve_casting(args):
    """Validate and resolve --character/--cast into args.cast_members (and args.cast_block when
    Phase 1 will run). Returns 0, or 2 after printing an Error: line. Touches nothing."""
    characters = args.characters or []
    casts = args.casts or []
    args.cast_members = []
    args.cast_block = None
    if not characters and not casts:
        if args.character_strength is not None:
            print("Error: --character-strength requires --character or --cast", file=sys.stderr)
            return 2
        return 0
    if args.no_stills:
        print("Error: --character/--cast are not supported with --no-stills: casting needs the "
              "chained flow", file=sys.stderr)
        return 2
    lib = _character_lib()
    strength = (args.character_strength if args.character_strength is not None
                else lib.DEFAULT_CHARACTER_STRENGTH)
    if not 0 < strength <= 1.0:
        print("Error: --character-strength must be in (0, 1], got %r" % strength, file=sys.stderr)
        return 2
    try:
        entries = [(None, name) for name in characters] + [lib.parse_cast_arg(v) for v in casts]
        members = lib.resolve_cast(entries)
    except lib.UnusableCharacterError as e:
        print("Error: %s" % e, file=sys.stderr)
        print(lib.format_available_line(lib.usable_characters()), file=sys.stderr)
        return 2
    except lib.CharacterError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    story_md = _story_paths(args.story_id)["story_md"]
    if args.force_story or not os.path.exists(story_md):
        if casts:
            print("Error: --cast needs an existing story.md that already uses the phrase, and Phase "
                  "1 is about to write a new one (%s); use --character to cast a new story"
                  % story_md, file=sys.stderr)
            return 2
        if args.story_prompt_override is not None:
            print("Error: --character cannot be combined with --story-prompt-override when Phase 1 "
                  "runs: the override is used verbatim, so the Cast block cannot be added",
                  file=sys.stderr)
            return 2
        args.cast_block = lib.build_cast_block(members)
    else:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
        for m in members:
            if not lib.phrase_occurs(text, m.phrase):
                print("Error: cast phrase %r (character %s) does not occur in %s"
                      % (m.phrase, m.name, story_md), file=sys.stderr)
                return 2
    args.character_strength = strength
    args.cast_members = members
    return 0


def _cast_flags(args):
    """--cast PHRASE=NAME per member, then --character-strength; [] when uncast."""
    members = getattr(args, "cast_members", None)
    if not members:
        return []
    flags = []
    for m in members:
        flags += ["--cast", "%s=%s" % (m.phrase, m.name)]
    return flags + ["--character-strength", repr(float(args.character_strength))]
```

These rules are **[spec choice]**, for a consistent single mechanism downstream:

- When Phase 1 is skipped, `--character NAME` is exactly `--cast "<referring_phrase>=NAME"`.
- `--cast` is refused whenever Phase 1 will write `story.md`.
- Members are ordered `--character` entries first, then `--cast` entries, each in command-line order.

**(c) `main`.** Directly after the `--story-prompt-override` existence check, and before `if args.dry_run:`:

```python
    rc = _resolve_casting(args)
    if rc:
        return rc
```

`main` also gains the 5.6(i) pre-scan as its first statement after `raw_argv` is computed.

**(d) `build_story_prompt`.** It gains a keyword `cast_block=None` (after `seconds`). Right after `rendered = template.format(...)`:

```python
    if cast_block:
        anchor = "\n\nHow this movie is made:"
        if rendered.count(anchor) != 1:
            raise ValueError("the story template no longer has exactly one %r anchor" % anchor)
        rendered = rendered.replace(anchor, "\n\n" + cast_block + anchor, 1)
```

The block therefore sits between `Narrative to adapt:\n<narrative>` and `How this movie is made:`, and inside the seed-image preface/postface wrapper when one applies. Both call sites (`phase1_story`, `_print_dry_run_plan`) pass `cast_block=getattr(args, "cast_block", None)`.

**(e) `phase1_story`.** After the `_chain_image_warnings` loop and before the final review `input`:

```python
    members = getattr(args, "cast_members", None) or []
    if members:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
        lib = _character_lib()
        for m in members:
            if not lib.phrase_occurs(text, m.phrase):
                print("Warning: story.md does not use cast phrase %r; character %s gets no LoRA in "
                      "this story" % (m.phrase, m.name))
```

**(f) `phase2_stills`.**

- Before `Running:`: if `cast_members` is set, `--seed-image` is not given, and `images/panel_01.png` exists, it prints `Warning: <path> exists and will be reused as-is; it was not necessarily rendered with the cast's stills LoRAs (delete it to regenerate)`.
- `cmd += _cast_flags(args)` is appended after the `--lora` line. The dry-run mirror does the same.
- **(Amendment 2)** The `--lora` line itself becomes the 5.7.5 stills form.

**(g) `phase3_manifest`.** `cmd_manifest += _cast_flags(args)` is appended after `"--force"`. The dry-run mirror does the same. Phase 4 is unchanged: the manifest carries the LoRAs.

**(h) `_print_dry_run_plan`.** After the header line and the blank line, only when `cast_members` is set:

- print `--- Cast ---`;
- then one line per member: `'cast: %s as "%s" (trigger %s; video LoRA %s; stills LoRA %s)' % (m.name, m.phrase, m.trigger, m.video_lora, m.stills_lora or "none: " + (m.stills_skip_reason or "not trained"))`;
- then a blank line.

The module docstring gains a paragraph on casting that cites this spec.

**(i) `--list-characters` (amendment).** `main` begins:

```python
def main(argv=None):
    raw_argv = argv if argv is not None else sys.argv[1:]
    if "--list-characters" in raw_argv:
        return _list_characters(raw_argv)
    parser = build_parser()
    ... (unchanged) ...
```

```python
def _list_characters(raw_argv):
    """--list-characters: print bin/character list's table and exit, before argparse (so no
    --story-id or narrative is required) and before the lockfile, the sudo check, the review
    gate or any phase (spec 5.6(i))."""
    if raw_argv != ["--list-characters"]:
        print("Error: --list-characters takes no other arguments", file=sys.stderr)
        return 2
    print("\n".join(_character_lib().character_table_lines()))
    return 0
```

- **Bypassing argparse's required arguments.** The pre-scan matches the exact token `--list-characters` anywhere in `raw_argv`, the same pattern as `make_dataset_seed.py`'s `--self-test` pre-scan. That runs before `build_parser().parse_args`, so `--story-id` and the narrative are never required.
- **Combined with anything else [spec choice: refuse].** If the token appears together with any other argument (including `--help`, `--dry-run`, or a narrative), the result is exit 2, `Error: --list-characters takes no other arguments` on stderr, and nothing on stdout.
  - `--list-characters=x` does not match the token. argparse then rejects it with its usual usage error (exit 2).
- **No side effects.** It writes nothing, takes no lockfile, runs no `sudo -n true`, spawns no subprocess, and touches no server, story directory or GPU.
  - `__main__`'s `pipeline_log.run_logged` gets `story_dir None`, because there is no `--story-id`. It therefore calls `main` directly and writes no log (`pipeline_log.py:88`).
- **The uncast path is untouched.** Without the token, `main` proceeds exactly as before. The B1 golden (an uncast `--dry-run`) and every existing ltx-movie argv and output stay byte-identical. P49 still holds: `character_lib` is loaded only by `_list_characters` or by casting.

### 5.7 Global LoRAs combine with the cast (amendment 2; normative)

A **global LoRA** is a non-character LoRA, such as an action-sequence or style LoRA, given by `--lora` (video) or `--stills-lora` (bin/ltx-movie; on bin/ltx-story-images it is that tool's `--lora`). It applies to every panel.

#### 5.7.1 Flag syntax and parsing

`ltx2_mlx_video_skill.py` (stdlib only) gains:

```python
def parse_lora_spec(value):
    """(path, strength, explicit) from PATH or PATH:STRENGTH. The value is split on its LAST ':'
    only when the text after it parses as a float; otherwise the whole value is the path
    (so 'org/repo:main' and ':0.5' are paths). STRENGTH must be finite and in (0, 2]. Default
    strength 1.0 (spec 5.7.1)."""
    if not isinstance(value, str) or not value:
        raise ValueError("LoRA value must be a non-empty PATH or PATH:STRENGTH, got %r" % (value,))
    head, sep, tail = value.rpartition(":")
    if sep and head:
        try:
            strength = float(tail)
        except ValueError:
            return value, 1.0, False
        if not (math.isfinite(strength) and 0 < strength <= 2.0):
            raise ValueError("LoRA strength must be in (0, 2], got %r in %r" % (tail, value))
        return head, strength, True
    return value, 1.0, False
```

`import math` is added to the stdlib imports. The forbidden-imports check still passes.

| Value | Result |
|---|---|
| `a.safetensors` | `("a.safetensors", 1.0, False)` |
| `a.safetensors:0.5` | `("a.safetensors", 0.5, True)` |
| `/p/a:b.safetensors:0.8` | `("/p/a:b.safetensors", 0.8, True)` |
| `org/repo:main` | `("org/repo:main", 1.0, False)` |
| `:0.5` | `(":0.5", 1.0, False)` |
| `a.safetensors:2` | `("a.safetensors", 2.0, True)` |
| `a.safetensors:0`, `:2.5`, `:-1`, `:nan`, `:inf`; `""` | `ValueError` |

A path whose own name ends in `:<number>` must be given as `PATH:1.0` (G20).

**Repeatable flag action.** bin/ltx-movie (`--lora`, `--stills-lora`), bin/ltx-mlx-render (`--lora`) and bin/ltx-story-images (`--lora`) each define this identical class, and use `action=_RepeatableLoraAction, default=None` on their existing `dest`. It is copied, not imported, because each parser is built before any lazy import **[spec choice]**. P75 pins that the copies are identical.

```python
class _RepeatableLoraAction(argparse.Action):
    """Repeatable --lora: the dest (lora_path / stills_lora_path) keeps the FIRST value as a
    string, exactly like the old single-valued flag; <dest>_specs collects every value in
    command-line order (spec 5.7.1)."""

    def __call__(self, parser, namespace, values, option_string=None):
        specs = list(getattr(namespace, self.dest + "_specs", None) or [])
        specs.append(values)
        setattr(namespace, self.dest + "_specs", specs)
        if getattr(namespace, self.dest, None) is None:
            setattr(namespace, self.dest, values)
```

The existing pins `lora_path is None` by default, `--lora x` giving `lora_path == "x"`, and the source text `lora_path=args.lora_path` (I21) all keep holding.

**Help text (exact additions).** The existing `--lora` help sentence is replaced. On `--stills-lora`, "video DiT" becomes "Phase 2 stills":

> `repeatable; PATH or PATH:STRENGTH (0 < STRENGTH <= 2, default 1.0). Every global LoRA applies to every panel, ahead of that panel's cast-character LoRAs, at its own strength (never reduced automatically).`

#### 5.7.2 The legacy route (byte-identity)

The **legacy route** is taken when a tool receives **exactly one** global LoRA value, its parsed strength is `1.0`, **and** the run has no character LoRAs. In that case:

- the flag behaves exactly as today: the single value goes through `lora_path`;
- there is no file-existence check, so HF repo IDs still work;
- there is no `loras` key in units or provenance.

"No character LoRAs" means, for each tool:

- **bin/ltx-mlx-render:** no manifest panel has a non-empty `characters`.
- **bin/ltx-story-images:** no planned panel matched a cast member that has a stills LoRA.
- **bin/ltx-movie:** for video, no cast members; for stills, no cast member has a stills LoRA.

On the legacy route, bin/ltx-movie forwards the **raw** value unchanged. bin/ltx-mlx-render and bin/ltx-story-images set `args.lora_path` to the parsed path, so `x:1.0` and `x` are the same render with the same provenance (P61).

Every other case takes the **merged route** (5.7.3-5.7.5). Therefore `--lora PATH` with no cast produces today's argv, manifest, still prompt and provenance (B1-B3 and R1 unchanged).

#### 5.7.3 bin/ltx-mlx-render (merged route)

This replaces the former 5.3(f) refusal, in the same position:

```python
    specs = getattr(args, "lora_path_specs", None) or []
    try:
        parsed = [SKILL.parse_lora_spec(v) for v in specs]
    except ValueError as e:
        print("Error: --lora: %s" % e, file=sys.stderr)
        return 2
    cast_entries = [(p["index"], c) for p in panels for c in (p.get("characters") or [])]
    args.global_loras = []
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries:
        args.lora_path = parsed[0][0]                       # legacy route (5.7.2)
    elif parsed:
        args.lora_path = None
        seen = {}
        for path, strength, _explicit in parsed:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                print("Error: --lora %s: not a readable file" % path, file=sys.stderr)
                return 2
            real = os.path.realpath(path)
            if real in seen:
                print("Error: --lora %s is given more than once" % path, file=sys.stderr)
                return 2
            seen[real] = path
            args.global_loras.append({"path": os.path.abspath(path), "strength": strength})
        for index, c in cast_entries:
            real = os.path.realpath(c["video_lora"])
            if real in seen:
                print("Error: --lora %s is also character %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], c["name"], index), file=sys.stderr)
                return 2
```

- Units carry `global loras + panel character loras` (5.3(b)), and render with `lora_path=None`. `render_panel` and `print_dry_run` already pass `unit["loras"]` as `loras` (5.3(d)/(e)), with globals listed as `(global)`.
- The `--lora` value now means "global LoRA(s)". It is not tied to the manifest.

#### 5.7.4 bin/ltx-story-images (merged route) and z_image_skill

- After `--cast` is resolved, it parses `getattr(args, "lora_path_specs", None) or []` with `ltx2_mlx_video_skill.parse_lora_spec`, using `import ltx2_mlx_video_skill` inside `main` (stdlib only; WS is on `sys.path`). A `ValueError` → `Error: --lora: <e>`, exit 2.
- The character plans are computed as in 5.5 into `char_plans`. They are empty without `--cast`.
- **Legacy check:** `len(parsed) == 1 and parsed[0][1] == 1.0 and not any(v[1] for v in char_plans.values())` → `args.lora_path = parsed[0][0]`, `global_stills = []`.
- **Otherwise (merged):** `args.lora_path = None`. Each path is validated with the same three checks and messages as 5.7.3, with these differences:
  - the character comparison uses every resolved member's `stills_lora` (`Error: --lora %s is also character %s's stills LoRA; pass it once`);
  - `global_stills = [{"kind": "global", "name": None, "path": abspath, "strength": s} …]`.
- **Plans.** When `members or global_stills`, every selected non-seed panel `i` gets `plans[i] = (prompt, global_stills + chars)`. `(prompt, chars) = char_plans.get(i, (_compose_prompt(panels[i - 1]["image"], style), []))`.
- The E-P16 one-set-per-process check, the `lora_kwargs`, the dry-run `loras:` line, and the `images.json` `"loras"` entries all use this combined list.
  - The `"loras"` key is present when `--cast` is given **or** the merged route is used. Its entries are `{"kind", "name", "path", "strength"}`.
  - The legacy single LoRA is not listed, the same as today.
- The `--seed-image` panel 1 is still never generated, so no LoRA applies to it.
- **z_image_skill needs no code change.** `loras` is already an ordered list. Adapter names `lora0…` follow it, so globals come first, and `set_adapters` weights are each entry's own strength.

#### 5.7.5 bin/ltx-movie

`_resolve_casting` loses its `--lora`/`--stills-lora` refusal. `main` calls `_resolve_global_loras(args)` right after `_resolve_casting`, with the same `if rc: return rc` pattern:

```python
def _video_skill():
    return importlib.machinery.SourceFileLoader(
        "ltx2_mlx_video_skill", os.path.join(WS, "ltx2_mlx_video_skill.py")).load_module()


def _resolve_global_loras(args):
    """Validate --lora/--stills-lora (spec 5.7). Sets args.global_video_loras and
    args.global_stills_loras to [(abs path, strength)] on the merged route; both stay [] on the
    legacy route, where the single raw value is forwarded exactly as before. Returns 0 or 2."""
    args.global_video_loras, args.global_stills_loras = [], []
    members = getattr(args, "cast_members", None) or []
    checks = (
        ("--lora", "lora_path_specs", "global_video_loras", "video",
         {os.path.realpath(m.video_lora): m.name for m in members}),
        ("--stills-lora", "stills_lora_path_specs", "global_stills_loras", "stills",
         {os.path.realpath(m.stills_lora): m.name for m in members if m.stills_lora}),
    )
    for flag, specs_attr, out_attr, kind, char_paths in checks:
        specs = getattr(args, specs_attr, None) or []
        if not specs:
            continue
        skill = _video_skill()
        try:
            parsed = [skill.parse_lora_spec(v) for v in specs]
        except ValueError as e:
            print("Error: %s: %s" % (flag, e), file=sys.stderr)
            return 2
        if len(parsed) == 1 and parsed[0][1] == 1.0 and not char_paths:
            continue                                        # legacy route (5.7.2)
        seen, resolved = {}, []
        for path, strength, _explicit in parsed:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                print("Error: %s %s: not a readable file" % (flag, path), file=sys.stderr)
                return 2
            real = os.path.realpath(path)
            if real in seen:
                print("Error: %s %s is given more than once" % (flag, path), file=sys.stderr)
                return 2
            if real in char_paths:
                print("Error: %s %s is also character %s's %s LoRA; pass it once"
                      % (flag, path, char_paths[real], kind), file=sys.stderr)
                return 2
            seen[real] = path
            resolved.append((os.path.abspath(path), strength))
        setattr(args, out_attr, resolved)
    return 0
```

**Forwarding.** `_render_flags` (shared by the Phase 3 dry run and Phase 4) replaces its `if args.lora_path:` line with:

```python
    if getattr(args, "global_video_loras", None):
        for path, strength in args.global_video_loras:
            flags += ["--lora", "%s:%s" % (path, repr(float(strength)))]
    elif args.lora_path:
        flags += ["--lora", args.lora_path]
```

Phase 2 and its dry-run mirror replace `if args.stills_lora_path: cmd += ["--lora", args.stills_lora_path]` with the same shape:

- `global_stills_loras` gives `["--lora", "<path>:<repr(strength)>"]` per entry;
- otherwise it falls back to the legacy raw `args.stills_lora_path`.

`"%s:%s"` always re-parses to the same path, because the split is on the last `:` and the suffix is always a float.

#### 5.7.6 Strength rules with globals [spec choice: as recommended]

- Every global LoRA applies on **every** panel, at its own CLI strength. It is **never** reduced automatically.
- `panel_strengths` counts **only character LoRAs**. A panel with one character and two globals gives that character 1.0. A panel with two characters and one global gives each character 0.8 (or its override), and the global keeps its own strength.
- The per-panel order is globals (CLI order), then characters (sorted by name). This applies to video (units) and to stills (adapter list).
- The same file may not appear twice in a panel's list, or across the global and character lists (compared by `os.path.realpath`): exit 2.

---

## 6. Strengths and bleed

- A panel that names exactly one cast character uses 1.0.
- A panel that names two or more uses, for each character, its `character.json` `strength` if set, else `--character-strength`. That default is `DEFAULT_CHARACTER_STRENGTH = 0.8`.
- This rule applies identically to the video LoRAs (5.4) and to the stills LoRAs (5.5). For stills, only members **with** a stills LoRA count toward "two or more".
- **(Amendment 2)** Global LoRAs never count toward "two or more", and their strength is never changed (5.7.6).
- **The 0.8 default is provisional.** Acceptance gate L6 (Section 9.7) renders a two-character panel at 1.0/1.0, 0.8/0.8, and 0.6/0.6. The winner becomes `DEFAULT_CHARACTER_STRENGTH` in a follow-up one-line commit, which also updates tests C36 and C37. That commit is part of this feature's acceptance.
- **Known limit (G5):** an on-screen character whose phrase is not in that panel's prompt gets no LoRA.

---

## 7. Error handling

Every `Error:` and `Warning:` line goes to stderr except where marked (stdout). `<…>` marks substituted values. The exact message templates are in Sections 3-5 next to the code that emits them; these tables index them.

### 7.1 `bin/character create`

| # | Condition | Exit | Message / effect |
|---|---|---|---|
| CE1 | argparse error | 2 | usage |
| CE2 | invalid NAME | 2 | `Error: character name must match [a-z][a-z0-9-]{1,23}, got '<v>'` |
| CE3 | NAME exists (no `--regenerate`) | 2 | `Error: character <name> already exists (<dir>); use --regenerate to rebuild its dataset` |
| CE4 | no `--phrase` | 2 | `Error: create needs --phrase` |
| CE5 | invalid phrase | 2 | `Error: --phrase: <normalize_phrase message>` |
| CE6 | not exactly one of `--seed-image`/`--descriptor` | 2 | `Error: create needs exactly one of --seed-image or --descriptor` |
| CE7 | descriptor mode without `--class` | 2 | `Error: --descriptor needs --class NOUN (there is no image to take it from)` |
| CE8 | invalid `--class` | 2 | `Error: class noun must match [a-z]{3,12}, got '<v>'` |
| CE9 | invalid descriptor | 2 | `Error: --descriptor: <validate_description message>` |
| CE10a/b | seed image missing / unreadable | 2 | `Error: --seed-image not found: <p>` / `Error: --seed-image is not a readable image: <p>: <e>` |
| CE11a/b/c | trigger invalid / already registered / a word of the phrase or equal to the class noun | 2 | `Error: trigger must match …` / `Error: trigger <t> is already used by character <n>; triggers are never reused` / `Error: trigger <t> must not be a word of the phrase or the class noun` |
| CE12 | `--seed` < 0 | 2 | `Error: --seed must be >= 0` |
| CE13a/b/c | `--regenerate` with a forbidden flag / unknown or invalid character / trained character | 2 | `Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger, --seed or --force; edit <json> instead` / `Error: <CharacterError>` / `Error: character <n> is trained; regenerating its dataset would orphan its LoRAs. Create a new character instead` |
| CE14 | library lock held by a live pid | 2 | `Error: another bin/character create/train is running (pid <p>); run one at a time` |
| CE15 | `busy_process()` | 2 | 4.12 |
| CE16 | free disk < 2 GiB | 2 | `Error: only <x.x> GiB free at <path>; create needs 2 GiB` |
| CE17 | VLM not served | 2 | `Error: the vision model qwen38-6bit is not being served at http://127.0.0.1:8177/v1/models; start it with: bin/story-server vision` |
| CE18 | face < 15% or none, without `--force` | 2 | 4.5. Nothing is written. With `--force` it is a warning and create proceeds |
| CE19 | face/describe unparseable twice, or a VLM HTTP failure | 1 | `Error: <DatasetError / RuntimeError>`. Nothing is written if this happens before step 14 |
| CE20 | avail-memory wait timeout, Z-Image child failure, vision restart timeout, ffmpeg/ffprobe failure, or a VLM HTTP failure while scoring | 1 | `Error: <e>`. `status` stays `"dataset"`. The vision server is always restarted |
| CE21 | reference still blocked by the content screen | 1 | 4.4 build_dataset step 4 |
| CE22 | kept < 12 | 3 | `Error: only <k>/<t> stills kept (need 12); the dataset is kept in <dir>/dataset; edit "descriptor" in <json> and run bin/character create <name> --regenerate`. `status` = `"dataset"` |

### 7.2 `bin/character train` / `list` / `show`

| # | Condition | Exit | Message / effect |
|---|---|---|---|
| CT1 | unknown or invalid character | 2 | `Error: <CharacterError>` |
| CT2 | status `dataset` | 2 | `Error: character <n> has no accepted dataset (status dataset); fix it with bin/character create <n> --regenerate` |
| CT3 | requested LoRA exists, no `--force` | 2 | `Error: character <n> already has a <kind> LoRA (<path>); pass --force to retrain it` |
| CT4a/b | lock held / busy process | 2 | as CE14 / CE15 |
| CT5 | story server not `STOPPED` (including `UNKNOWN`) | 2 | `Error: the story server is <state>; stop it first with bin/story-server stop (training needs its memory)` |
| CT6 | available memory < 30 GiB | 2 | `Error: only <x.x> GiB of memory is available; training needs 30 GiB (quit memory-heavy apps and retry)` |
| CT7 | free disk < 8 GiB x kinds | 2 | `Error: only <x.x> GiB free at <dir>; training <kinds> needs <n> GiB` |
| CT8a/b/c | dev model dir layout wrong / test model missing / ltx-2-mlx binary missing | 2 | `Error: <TRAIN_MODEL_DIR> must contain transformer-dev.safetensors and neither transformer.safetensors nor transformer-distilled.safetensors (the trainer would pick those first)` / `Error: test-render model not found: <TEST_MODEL_DIR>` / `Error: ltx-2-mlx binary not found or not executable: <bin>` |
| CT9 | mflux-train missing | 1 iff `--stills` given, else 0 | 4.11 step 5. The video LoRA proceeds or is kept |
| CT10 | preprocess or train rc != 0, wrong latent count, or missing final checkpoint | 1 | `Error: video LoRA training failed at <step> (exit <rc>); log: <log>; character <n> stays <status>`. `status` unchanged. Stills not attempted |
| CT11 | video test render failed | 1 | `Error: video test render failed: <e>`. The LoRA stays recorded, `status` = `trained` |
| CT12 | mflux-train rc != 0, or no adapter in its output | 1 | 4.9 steps 3-4 |
| CT13 | adapter incompatible | 1 iff `--stills` given, else 0 | 4.9 step 7. `lora/stills.rejected.safetensors` is kept |
| CS1 | `show` unknown/invalid | 2 | `Error: <CharacterError>` |
| CS2 | `list` with an invalid entry | 0 | a row `(invalid: <e>)` |

### 7.3 Pipeline

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-P1 | ltx-movie | `--character-strength` without casting | 2 (5.6b) |
| E-P2 | ltx-movie | casting with `--no-stills` | 2 |
| E-P3 | ltx-movie | ~~casting with `--lora`/`--stills-lora`~~ | **removed by amendment 2.** They combine (5.7) |
| E-P4 | ltx-movie, manifest, images | `--character-strength` outside (0, 1] | 2 |
| E-P5 | ltx-movie, manifest, images | malformed `--cast` | 2, `Error: --cast must be PHRASE=NAME, got '<v>'` |
| E-P6a | ltx-movie | `UnusableCharacterError` (3.5): invalid or unknown name, invalid `character.json`, not trained, video LoRA missing or empty | 2. Two stderr lines: `Error: <message>`, then `format_available_line(usable_characters())`, e.g. `available characters: kyra (the woman in grey), ronin (the ronin)`, or `available characters: none (create one with bin/character create)`. Before any phase and any GPU work |
| E-P6b | ltx-movie | other `CharacterError` from `resolve_cast`/`parse_cast_arg`: stills LoRA missing or empty, duplicate name, phrase or trigger, trigger is a phrase word, malformed `--cast` | 2, `Error: <message>` only |
| E-P6c | manifest, images | any `CharacterError`, including `UnusableCharacterError` | 2, `Error: <message>` only (3.9: no available line) |
| E-P7 | ltx-movie | `--cast` while Phase 1 will run | 2 |
| E-P8 | ltx-movie | `--character` + `--story-prompt-override` while Phase 1 will run | 2 |
| E-P9 | ltx-movie | cast phrase not in the existing story.md | 2 |
| E-P10 | ltx-movie | phrase unused in a newly written story.md | warning (stdout), continues |
| E-P11 | ltx-movie | casting while `images/panel_01.png` already exists | warning (stdout), continues |
| E-P12 | ltx-story-manifest | `--cast` without `--chain` | 2 (`parser.error`) |
| E-P13 | ltx-story-manifest, images | `--character-strength` without `--cast` | 2 |
| E-P14 | ltx-story-manifest | cast phrase in no panel's Motion: text | `WARNING:` (stdout), continues |
| E-P15 | ltx-story-images | ~~`--cast` + `--lora`~~ | **removed by amendment 2** (5.7.4) |
| E-P16 | ltx-story-images | selected panels need different stills LoRA sets | 2 |
| E-P17 | ltx-story-images | a cast member has no stills LoRA | `WARNING:` (stdout), its trigger is not inserted, continues |
| E-P18 | ltx-mlx-render | malformed `characters` entry (not a list, nameless, duplicate, unreadable or relative `video_lora`, bad strength) | 2, `Error: panel <n>: …` (5.3a) |
| E-P19 | ltx-mlx-render | ~~`--lora` + a cast manifest~~ | **removed by amendment 2.** They combine (5.7.3) |
| E-P20 | ltx-mlx-render | LoRA unreadable when provenance is built | the existing `panel N FAILED (provenance)` path |
| E-P21 | ltx2_mlx_video_skill | `loras` invalid, or combined with `lora_path` | `ValueError` before any subprocess (5.1). The CLI maps it to exit 2 |
| E-P23 | ltx-movie | `--list-characters` alone | 0. stdout = `"\n".join(character_table_lines()) + "\n"`. No other effect (5.6(i)) |
| E-P24 | ltx-movie | `--list-characters` with any other argument | 2, `Error: --list-characters takes no other arguments`, stdout empty |
| E-P25 | ltx-movie, render, images | a `--lora`/`--stills-lora` value fails `parse_lora_spec` | 2, `Error: <flag>: <ValueError>` |
| E-P26 | ltx-movie, render, images | merged route: a global LoRA path is not a readable file | 2, `Error: <flag> <path>: not a readable file` |
| E-P27 | ltx-movie, render, images | the same file given twice as a global LoRA (realpath) | 2, `Error: <flag> <path> is given more than once` |
| E-P28 | ltx-movie, render, images | a global LoRA is also a cast character's LoRA (realpath) | 2. ltx-movie: `Error: <flag> <path> is also character <n>'s <video|stills> LoRA; pass it once`. render adds ` (panel <i>)` before `; pass it once`. images says `stills LoRA` |
| E-P29 | ltx-movie, render, images | legacy route (one value at 1.0, no character LoRAs) | not validated, exactly as today (HF repo IDs allowed; G19) |
| E-P22 | z_image_skill | `lora_path` + `loras` / adapter not registered / a different LoRA set on a loaded singleton | `ValueError` / `ValueError` / `RuntimeError` (5.2) |

---

## 8. Deploy package

- `scripts/deploy/build_pkg.py:383` becomes `PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py", "character_lib.py", "bin/ltx-movie", …)`, with `"character_lib.py"` inserted directly after `"pipeline_log.py"`. `tests/test_deploy_pkg.py:308`'s `PIPELINE` tuple gets the identical insertion.
- **Why it must ship.** The shipped `bin/ltx-movie`, `bin/ltx-story-manifest`, and `bin/ltx-story-images` load `character_lib.py` whenever casting is used. Without it, casting on the target would fail with `FileNotFoundError`.
- **Not shipped [spec choice]:** `bin/character`, `character_dataset.py`, the mflux venv, the dev model, and any library content. Training needs the dev pack, the VLM server, and mflux, and is a source-machine activity. A target that wants casting must copy the trained `generated/characters/<name>/` directories, and the absolute LoRA paths inside `character.json` must be valid on that target (G12).
- **Gates.**
  - No new gate (`GATE_SPECS` and `TEST_FILES` are unchanged). The new test files are not shipped.
  - G1-G7 and X1/X2 run the unchanged existing suites and an uncast dry run, so their outputs are unchanged.
- **Deploy test counts: unchanged.** `tests/test_deploy_pkg.py` stays at **165** under `python3 -m pytest` (3.13) and under `/usr/bin/python3 -m unittest tests.test_deploy_pkg` (3.9.6). The tuple edit changes expected values, not test count.

---

## 9. Testing

### 9.1 Framework and fixtures

- Every new test file uses pytest with plain `assert` and **no `check()` helper**, and runs under `python3 -m pytest <file>` from `WS`. Scripts are loaded with `importlib.machinery.SourceFileLoader(...)` (the pattern at `tests/test_ltx_mlx_render.py:24`). There are no network calls, no GPU work, and no real VLM.
- **`lib_dir` fixture.** `monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(tmp_path / "lib"))`.
- **`make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey", class_noun="woman", status="trained", stills=False, strength=None)` helper.**
  - It writes a valid `character.json` (2.2 shape; descriptor `"a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"`).
  - For `trained`, it creates `lora/video.safetensors` as 16 bytes `b"fake-video-lora!"`, and `lora/stills.safetensors` when `stills`.
  - It sets `sha256` to the real hash, and returns the dict.
- **`member(name, phrase, trigger, strength=None)`.** It builds a `CastMember` with dummy paths, for the pure tests.
- **Render harness.** It is modeled on `tests/test_ltx_mlx_render.py:1736-1800` `_Harness`: it stubs `SKILL.generate_video` (recording kwargs and writing 128 zero bytes), `probe_streams`, `assert_clips_uniform`, `build_concat_command`, and `clip_frame_count`, and sets `SKILL.LTX2_MLX_BIN` to a `#!/bin/sh\nexit 0` file. It is a fresh copy in `tests/test_casting_pipeline.py`, not an import of the other test file.
- **Fake VLM.** `monkeypatch.setattr(character_dataset, "vlm_call", fake)`, where `fake` returns queued strings per prompt kind: it dispatches on `content_parts[0]["text"]` being `FACE_PROMPT`, `DESCRIBE_PROMPT`, or `CHECK_PROMPT`. Also patched: `story_server`, `wait_for_vlm`, `wait_for_avail`, `vlm_ready`, `busy_process`, `story_server_state`, `free_gib`, and `run_zimage_child`. The last one writes 1024x640 solid PNGs for the spec's jobs and returns a report.
- Real `ffmpeg`/`ffprobe` are used for `wrap_still`/`verify_ffprobe` (installed: 9.0.1).

### 9.2 `tests/test_character_lib.py`

| ID | Test | Assertion |
|---|---|---|
| C1 | `validate_name` on `"kyra"`, `"ab"`, `"a-1"`, `"x" * 24` / `"A"`, `"a"`, `"1ab"`, `"ab_c"`, `"a" * 25`, `None` | first group ok; second raises `CharacterError` |
| C2 | `validate_trigger` on `"kyrawmn"`, `"abcd"`, `"a"+"b"*15` / `"abc"`, `"Kyra"`, `"1abc"`, `"ab-cd"`, `"a"*17` | ok / raises |
| C3 | `normalize_phrase("  the   woman in\ngrey ")` | `== "the woman in grey"` |
| C4 | `normalize_phrase` raises on `""`, `"a b c d e f g"` (7 words), `"the"`, `"An"`, `"the ronin="`, `"the (ronin)"`, `5` | raises each |
| C5 | `normalize_phrase("the ronin’s ally")`, `"o'brien"`, `"half-elf"` | returned unchanged |
| C6 | `auto_trigger` table (2.4) | each row equal |
| C7 | `auto_trigger("ronin", "man", set(), avoid=["the", "roninmn"])` | `"roninmn2"` |
| C8 | `validate_character(make_character dict)` for each status (`dataset` with `dataset=None`, `untrained`, `trained`) | no raise |
| C9 | each of the 14 top-level keys removed; one extra key added | raises, with the field name in the message |
| C10 | `status="trained"` with `loras.video=None`; `status="untrained"` with a video entry; `untrained` with `dataset.kept=11` | raises each |
| C11 | LoRA entry `alpha=16, rank=32`; `sha256="ABC"`; relative `path`; `rank=True` | raises each |
| C12 | `strength` in `0`, `1.5`, `True`, `"0.8"` / `None`, `0.6`, `1` | raises / ok |
| C13 | `trigger == class_noun`; trigger equal to a phrase word (`"ronin"`, phrase `"the Ronin"`) | raises |
| C14 | `source` `{"type": "seed_image"}` (no path); `{"type": "descriptor", "path": "/x"}`; `{"type": "web"}` | raises |
| C15 | `descriptor` ending with `"."`; starting `"The"`; 7 words; 61 words | raises |
| C16 | `load_character("ghost")` in an empty lib | `CharacterError` with `str == "unknown character: ghost (no <lib>/ghost/character.json)"` |
| C17 | `load_character` on a file holding `"{bad"` / a valid JSON failing C9 | message starts `"invalid character.json for kyra: "` |
| C18 | `write_character` then `load_character` round trip; `write_character` of an invalid dict | equal dict; raises, and the file is unchanged (byte compare) and no `*.tmp` remains |
| C19 | `list_names` with dirs `kyra` (valid), `bad` (no json), `.hidden`, `Upper` (json present), and the file `.triggers` | `["kyra"]`; a missing lib dir gives `[]` |
| C20 | `registered_triggers` with `.triggers` = `"kyrawmn kyra\ngarbage\nroninmn ronin\n"` and a dir `ghost` whose JSON is invalid but has `"trigger": "ghosttt"` | `{"kyrawmn": "kyra", "roninmn": "ronin", "ghosttt": "ghost"}` |
| C21 | `parse_cast_arg("the woman in grey=kyra")`, `"a=b=kyra"`, `"the ronin = ronin"` | `("the woman in grey", "kyra")`; `CharacterError` (the phrase `"a=b"` fails `PHRASE_WORD_RE`); `("the ronin", "ronin")` |
| C22 | `parse_cast_arg("the ronin")`, `"the ronin=Bad Name"` | the first raises `CharacterError` and is **not** an `UnusableCharacterError`. The second raises `UnusableCharacterError` |
| C23 | `cast_text("The woman in grey rides.", [kyra])` | `("The kyrawmn woman in grey rides.", ["kyra"])` |
| C24 | mid-sentence and multiple occurrences: `"He bows to the woman in grey; the woman in grey nods."` | both inserted, names `["kyra"]` |
| C25 | possessives: `"the ronin's blade"`, `"the ronin’s blade"` (phrase `the ronin`, trigger `roninmn`) | `"the roninmn ronin's blade"`, `"the roninmn ronin’s blade"` |
| C26 | boundaries: `"the ronins"`, `"the ronin-like"`, `"bathe ronin"`, `"the woman in grey-blue robe"`, `"theronin"` | unchanged, names `[]` |
| C27 | longest first: members `x` (`"the woman"`, `xtrig`) and kyra; `"the woman in grey and the woman"` | `("the kyrawmn woman in grey and the xtrig woman", ["kyra", "x"])` |
| C28 | no article: phrase `"Kyra"`, trigger `kyrawmn`: `"Kyra smiles at kyra."` | `"kyrawmn Kyra smiles at kyrawmn kyra."` |
| C29 | idempotence: apply C23-C28 outputs again | identical text and names |
| C30 | whitespace: `"the woman\n in  grey"` | `"the kyrawmn woman\n in  grey"` |
| C31 | case: `"THE RONIN draws."` | `"THE roninmn RONIN draws."` |
| C32 | article `a`: phrase `"a stranger"`, trigger `strgrmn`: `"A stranger waits."` | `"A strgrmn stranger waits."` |
| C33 | two characters in one text: kyra + ronin in `"The ronin shields the woman in grey."` | both inserted, names `["kyra", "ronin"]` |
| C34 | `phrase_occurs("## Panel 1 — x\nMotion: The Ronin runs.", "the ronin")`; `phrase_occurs("the ronins", "the ronin")` | True; False |
| C35 | `resolve_cast` happy path: kyra via `(None, "kyra")`, ronin via `("the swordsman", "ronin")` | members in entry order; kyra's phrase is her `referring_phrase`; ronin's is `"the swordsman"`; `video_lora` absolute; `stills_lora is None` |
| C36 | `panel_strengths(["kyra"], members, 0.8)` | `{"kyra": 1.0}` |
| C37 | `panel_strengths(["kyra", "ronin"], members, 0.8)` with ronin `strength=0.6` | `{"kyra": 0.8, "ronin": 0.6}` |
| C38 | `resolve_cast` errors: unknown; `status untrained`; video file deleted; video file emptied; stills entry set but file missing; duplicate name; duplicate phrase differing only in case; two characters with the same trigger (hand-written JSON); trigger is a phrase word | each raises `CharacterError` with the 3.5 message. The exception is an `UnusableCharacterError` exactly for: unknown, untrained, video deleted, video emptied (plus an invalid `character.json` and the name `"Bad"`, both added to this case list). For the rest it is not |
| C39 | `build_cast_block([kyra, ronin])` | `== CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": <descriptor>.' + "\n" + '- "the ronin": <descriptor>.' + "\n" + CAST_BLOCK_RULES` |
| C40 | `CAST_BLOCK_HEADER + CAST_BLOCK_RULES` | contains no `{` or `}`. Contains `"word for word"` twice and `"longer than four words"` |
| C42 | `format_available_line([])`; `format_available_line([("kyra", "the woman in grey"), ("ronin", "the ronin")])` | `"available characters: none (create one with bin/character create)"`; `"available characters: kyra (the woman in grey), ronin (the ronin)"` |
| C43 | `usable_characters()` in a lib created in this order: `zed` (untrained), `ronin` (trained), `bad` (invalid JSON), `gone` (trained, video file deleted), `stl` (trained, stills entry whose file is missing), `kyra` (trained) | `[("kyra", "the woman in grey"), ("ronin", "the ronin")]`. An empty or missing lib gives `[]` |
| C44 | `character_table_lines()` on an empty lib | `["no characters in <lib>"]` |
| C45 | `character_table_lines()` on kyra (trained, no stills), ronin (untrained), and `bad` (invalid) | exactly `[LIST_ROW_FORMAT % ("NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS", "PHRASE"), "%-16s (invalid: %s)" % ("bad", <load_character message>), LIST_ROW_FORMAT % ("kyra", "kyrawmn", "trained", "yes", "no", "the woman in grey"), LIST_ROW_FORMAT % ("ronin", "roninmn", "untrained", "no", "no", "the ronin")]` |
| C46 | `UnusableCharacterError` | is a subclass of `CharacterError` (an existing `except CharacterError` in manifest and images still catches it) |
| C41 | `character_lib.py` source, parsed with `ast` | every top-level `Import`/`ImportFrom` is a stdlib module from the set `{collections, datetime, json, os, re, uuid}` |

### 9.3 `tests/test_character_dataset.py`

| ID | Test | Assertion |
|---|---|---|
| D1 | every `make_dataset_seed.py` self-test case, ported 1:1 (`extract_json` ×5, `validate_description` ×6, `validate_check` ×6, `gen_prompt` exact, `caption` exact, `image_data_url` 2000x1000 → max side <= 768) | same pass/raise outcomes as `run_self_test` (`make_dataset_seed.py:296-426`) |
| D2 | `VARIANTS`, `SHOTS`, `STYLE`, `CHECK_PROMPT` | equal to the values in `generated/charlora/tools/make_dataset_seed.py` (the test reads that file with `ast` and compares the literals) |
| D3 | `DESCRIBE_PROMPT` | equals the 4.5 literal. Contains `"apparent ethnicity when it is visible"`, `"riding boots while riding"`, `"anything they are holding"` |
| D4 | `validate_face`: `{"face_box": [100, 200, 300, 500]}`, `{"face_box": None}`, `{"face_box": [0, 0, 1000, 1000]}` | `0.3`, `None`, `1.0` |
| D5 | `validate_face` raises: missing key; `[1, 2, 3]`; `[1, 2, 3, True]`; `[300, 200, 100, 500]`; `[0, 0, 1001, 10]`; `"box"` | raises `ValueError` each |
| D6 | `trigger_test_prompt("kyrawmn", "woman")` | `"kyrawmn woman, medium shot, standing and facing the camera, photorealistic live-action film still, natural light."` |
| D7 | `video_train_config("/d/pre", "p, q.", "/d/out")` | equals the template with `"…"` JSON-quoted values. Parsing it with a minimal check (`yaml` is not required): it contains the lines `  model_path: "<TRAIN_MODEL_DIR>"`, `  preprocessed_data_root: "/d/pre"`, `    - "p, q."`, `output_dir: "/d/out"`, `  rank: 32`, `  alpha: 32`, `  steps: 1000`, `  interval: 250`, `  keep_last_n: 10`. Contains no `{` |
| D8 | `preprocess_argv("/v", "/c", "/o")`; `train_argv("/t.yaml")` | `[BIN, "preprocess", "--videos", "/v", "--captions", "/c", "-o", "/o", "-m", TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]`; `[BIN, "train", "--config", "/t.yaml", "--low-ram"]` |
| D9 | `stills_epochs(24)`, `(12)`, `(17)`, `(25)`; and for k in 1..30 | `(100, 2400, 600)`, `(200, 2400, 600)`, `(144, 2448, 612)`, `(96, 2400, 600)`. For all k: `epochs % 4 == 0`, `total % save == 0`, `total // save == 4`, `total >= 2400` |
| D10 | `stills_train_config("/d", "/o", 0, 24)` | the 4.9 dict exactly: 7 targets, each `"blocks": {"start": 0, "end": 30}`, `"rank": 16`; `checkpoint == {"save_frequency": 600, "output_path": "/o"}`; `monitoring.generate_image_frequency == 2400` |
| D11 | `safetensors_keys` on a hand-built file (8-byte header length + JSON with `__metadata__` and 3 tensors) | the 3 sorted keys |
| D12 | `lora_module_count` on `["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight", "lora_unet_x.lora_down.weight", "lora_unet_x.alpha", "other.weight"]` | `2` |
| D13 | `extract_mflux_adapter` on a tmp tree `out/run/checkpoints/0000600_checkpoint.zip` and `0002400_checkpoint.zip`, each holding `NNNNNNN_adapter.safetensors` + `NNNNNNN_optimizer.safetensors` | the dest bytes equal the 2400 zip's adapter member |
| D14 | `extract_mflux_adapter` with no zips; with a zip holding 2 adapter members | `DatasetError` each |
| D15 | `write_contact_sheet` with 25 items (item 5 dropped, item 7's PNG missing) | a 1280x900 JPEG. The pixel at the red border of tile 5 (`(5 % 5) * 256 + 1, (5 // 5) * 180 + 1`) is red-dominant (R > 200, G < 60). Tile 7's centre is black |
| D16 | `story_server_state` with `subprocess.run` patched to return the real `status` output captured in 0.2 (`"  state:          SERVING vision"`), then `STOPPED`, then `LOADING vision`, then rc 1 with no state line, then `OSError` | `"SERVING vision"`, `"STOPPED"`, `"LOADING vision"`, `"UNKNOWN"`, `"UNKNOWN"` |
| D17 | `busy_process` with `psutil.process_iter` patched to yield cmdlines `["/x/ltx-2-mlx", "generate", …]`, `["python3", "bin/ltx-mlx-render", …]`, `["/x/mflux-train", "--config", "c"]`, `["vim", "notes-ltx-2-mlx.txt"]`, `["python3", "character_dataset.py", "zimage", "--spec", "s"]` (one per run) | a match for 1, 2, 3, 5; `None` for 4 |
| D18 | `library_lock` | acquires (the file holds own pid); a second acquire while held by a live foreign pid (`os.getppid()` written in the file) raises `DatasetError`; a stale pid (99999999) is removed and acquired; released on exit (file gone) |
| D19 | `run_logged(["sh", "-c", "echo a; echo b 1>&2; exit 3"], log, "/", os.environ, 10)`; `run_logged(["sleep", "5"], log, …, 1)` | rc 3, log == `"a\nb\n"` (stderr merged); rc `-9` in < 3 s |
| D20 | `train_video` happy path. `run_logged` is patched: on preprocess it creates `.precomputed/latents/` with one file per mp4; on train it writes the final checkpoint (`b"lora"`). `SKILL.generate_video` is patched to record kwargs and write files | returns `"ok"`. `lora/video.safetensors == b"lora"`. `character.json` `status == "trained"`, `loras.video.sha256 == sha256(b"lora")`, rank/alpha/steps 32/32/1000, `sample_path`/`control_path` set. The first `generate_video` call has `loras == [(lora_path, 1.0)]`, `width 512`, `height 320`, `num_frames 25`, `seed 42`, `model == TEST_MODEL_DIR`, `image_path is None`; the second call has no `loras` key |
| D21 | `train_video`: preprocess rc 1 | returns `"failed"`. stderr has `"failed at preprocess (exit 1)"` and the log path. `status` is still `untrained`. `lora/` has no `video.safetensors` |
| D22 | `train_video`: latents count 23 for 24 videos | returns `"failed"`, stderr `"preprocess wrote 23 latents for 24 videos"` |
| D23 | `train_video`: train rc 0 but no final checkpoint | returns `"failed"`, `"failed at train"` |
| D24 | `train_video`: the LoRA test render raises `Ltx2MlxError` | returns `"test_failed"`. `train()` exits 1, and still runs stills when requested. `status == "trained"`, `loras.video.sample_path is None`, `control_path` set |
| D25 | the `train/video` dir pre-populated with a stale file | the stale file is gone after the run |
| D26 | `train()` preflight order: each of lock, busy, `story_server_state() == "SERVING vision"`, avail 29.9 GiB, free disk 15.9 GiB for both kinds, dev dir containing `transformer-distilled.safetensors` | each returns 2 with the 7.2 message. `train_video` is never called (a sentinel patch raises if called). An extra case with the server `SERVING vision` **and** avail 29.9 GiB reports CT5, which pins the order |
| D27 | `train()`: `--video` only on a character that has a video LoRA, without `--force`; with `--force` | 2 (CT3); proceeds |
| D28 | `train()` default kinds with `MFLUX_TRAIN` pointing at a missing path | video trains. `stills_skip_reason == "mflux-train not found at <p>"`. Exit 0. The same with `--stills` → exit 1 |
| D29 | `train_stills` happy path: `run_logged` writes a checkpoint zip whose adapter has 2 modules; `run_zimage_child` returns `injected_lora_modules: 2` and writes the PNG | `"ok"`. `lora/stills.safetensors` exists. `loras.stills.rank == 16`, `steps == 2400` (24 kept). The control child spec has `"loras": None`. The data dir holds 24 png+txt pairs plus `preview_1.txt == trigger_test_prompt(...)`. `train.json` equals `stills_train_config(...)`. The env passed has `HF_HOME == MFLUX_HF_HOME` |
| D30 | `train_stills`: injected 1 of 2 | `"skipped"`. `lora/stills.rejected.safetensors` exists and `stills.safetensors` does not. `stills_skip_reason` contains `"only 1 of 2 LoRA modules"`. `loras.stills` unchanged |
| D31 | `train_stills`: the compat child raises `DatasetError` | `"skipped"`, with the reason containing `"could not load or render"` |
| D32 | `train_stills`: the adapter has zero `.lora` keys | `"skipped"`, reason `"the adapter file has no LoRA modules"` |
| D33 | `train_stills`: mflux rc 2 | `"failed"`. `train()` exits 1 even without `--stills` |
| D34 | `--force` retrain of stills where the new adapter is incompatible, while a previous good stills entry exists | the previous entry and file are kept. `stills_skip_reason` is set |
| D35 | `child_zimage` with fake `torch`, `z_image_skill`, and `content_safety` modules inserted in `sys.modules`. The fake `generate_image` raises `ContentSafetyError` for job 2. The fake `_pipeline.transformer.modules()` yields 3 modules with `lora_A = torch.nn.ModuleDict`-like objects containing `"lora0"` | report `jobs[1].status == "blocked"`, `injected_lora_modules == 3`. Returns 0. Every `generate_image` call received `loras` as a list of tuples |
| D36 | the `run_zimage_child` parent with `run_logged` patched to rc 1 | `DatasetError` naming the log |
| D37 | `character_dataset.py` source, parsed with `ast` | no top-level import of `torch`, `z_image_skill`, `content_safety`, `diffusers` |

### 9.4 `tests/test_character_tool.py` (`bin/character` end to end, with 9.1 fakes)

| ID | Test | Assertion |
|---|---|---|
| K1 | `main([])`, `main(["create"])`, `main(["train"])`, `main(["show"])` | `SystemExit` code 2 |
| K2 | `list` on an empty lib; on a lib with kyra (trained, no stills) and ronin (untrained) plus an invalid `bad` | stdout `== "\n".join(character_lib.character_table_lines()) + "\n"` in both cases (the C44/C45 lines), exit 0 |
| K3 | `show kyra`; `show ghost` | the JSON dump + `files:` lines (`ok` for an existing LoRA, `MISSING` for a deleted sample); `show ghost` exits 2 |
| K4 | `create` CE2-CE12 cases, one run each | the exact exit 2 and message. `<lib>` gains no directory. The fake VLM was never called (its call list is empty) |
| K5 | `create` CE13a-c | 2 each |
| K6 | `create` CE14-CE17 | 2 each. No dir created |
| K7 | seed mode, face reply `{"face_box": [400, 100, 600, 220]}` (12%) without `--force` | exit 2, the CE18 message with `12%`, no dir, `.triggers` absent |
| K8 | as K7 with `--force` | proceeds. stderr has `Warning: the main character's face fills only 12%` |
| K9 | seed-mode happy path: face `[350, 100, 650, 500]`, describe reply `{"class_noun": "woman", "descriptor": "A young East Asian woman with long black hair and a grey kimono."}`, every check reply score 9 except n=5 score 4 | exit 0. `character.json` `status "untrained"`, `class_noun "woman"`, descriptor normalized (`"a young …kimono"`, no period), trigger `kyrawmn`, `dataset == {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7, "face_height": 0.4, "contact_sheet": …}`. 24 captions and 24 mp4s (each verified as 1 frame). `char_05` has no caption. `.triggers == "kyrawmn kyra\n"`. Story-server calls were `["stop", "vision"]` in that order. stdout ends with the 3 summary lines (4.4 step 8) |
| K10 | descriptor mode (`--descriptor "a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama" --class man`) | no FACE/DESCRIBE call. 24 items (n 1..24), reference `char_01`, kept forced for n=1 even when its score reply is 3. `face_height None`. `source == {"type": "descriptor"}` |
| K11 | kept 11 (scores 3 for 14 items) | exit 3. CE22 on stderr. `status "dataset"`. Dataset files present |
| K12 | `--regenerate` after K11 with the descriptor edited by hand | wipes and rebuilds `dataset/`. No FACE/DESCRIBE calls. The trigger is unchanged. `.triggers` is not appended to again |
| K13 | the generation child raises `DatasetError` | exit 1. `story_server` calls `["stop", "vision"]` (restart in `finally`). `status "dataset"` |
| K14 | the reference still is missing after generation (descriptor mode, the fake child skips job 1) | exit 1 with the CE21 text |
| K15 | `--trigger kyrawmn` when `.triggers` already lists it | exit 2, CE11b |
| K16 | `train kyra` on `status dataset` | exit 2, CT2 |
| K17 | `train` delegates to `character_dataset.train` (patched to return 1) | the exit code is propagated |
| K18 | importing `bin/character` and running `list` | `sys.modules` has no `PIL`, `psutil`, or `character_dataset` afterwards (checked in a subprocess: `python3 -c "…main(['list'])…; print(sorted(m for m in ('PIL','psutil','character_dataset') if m in sys.modules))"` prints `[]`) |

### 9.5 `tests/test_casting_pipeline.py`

| ID | Test | Assertion |
|---|---|---|
| P1 | `SKILL.build_command(... loras=[("/a.safetensors", 1.0), ("/b.safetensors", 0.8)])` | the argv equals the uncast argv with `["--lora", "/a.safetensors", "1.0", "--lora", "/b.safetensors", "0.8"]` inserted directly after the `--gemma` value |
| P2 | `build_command(loras=[])`, `loras=None` | identical to the call without `loras` |
| P3 | `build_command(lora_path="/x", loras=[("/a", 1.0)])` | `ValueError("lora_path and loras are mutually exclusive")` |
| P4 | `generate_video` with `loras` cases: not a list; a 3-tuple; a missing file; strength `0`, `2.5`, `True`, `"1"`; plus `lora_path` | each `ValueError` with the 5.1 message. The stub binary never ran (`subprocess.Popen` patched to raise) |
| P5 | `generate_video(..., loras=[(real_tmp_file, 0.6)])` with `LTX2_MLX_BIN` = a stub script that writes its argv to a file and creates the output | the child argv contains `["--lora", tmp, "0.6"]` exactly once |
| P6 | `render.load_manifest` with `characters` valid (2 entries) | loads. Units have `loras == [{"name": "kyra", "path": …, "strength": 0.8}, {"name": "ronin", …}]` |
| P7 | `load_manifest` invalid `characters` cases: a dict; an entry without a name; a duplicate name; a relative `video_lora`; a missing file; strength `0`, `1.2`, `True` | `ValueError` each, message `panel 2: …` |
| P8 | `build_units` on panels with `characters: []` and with no key | the unit key set is exactly R4l's 9 keys |
| P9 | harness run, 3-panel chain manifest, panel 1 `characters` [kyra@1.0], panel 2 [kyra@0.8, ronin@0.8], panel 3 none | `received_kwargs[0]["loras"] == [(k, 1.0)]`; `[1]["loras"] == [(k, 0.8), (r, 0.8)]`; `"loras" not in received_kwargs[2]`; `lora_path is None` in all |
| P10 | (amendment 2) `main(["m.json", "o.mp4", "--lora", g])` on the P9 cast manifest, `g` a real tmp file | exit 0. `received_kwargs[0]["loras"] == [(g, 1.0), (k, 1.0)]`, `[1]["loras"] == [(g, 1.0), (k, 0.8), (r, 0.8)]`, `[2]["loras"] == [(g, 1.0)]`. `lora_path is None` in all |
| P11 | `--dry-run` on the P9 manifest | stdout has `"            lora: <k> @ 1.0 (kyra)"` under panel 1 and two lora lines under panel 2. The `first render command:` line contains `--lora <k> 1.0` |
| P12 | `--dry-run` on an uncast manifest | contains no `"lora:"` line and no `--lora` |
| P13 | `build_clip_provenance` for a cast unit | it has a `loras` key `== [{"kind": "character", "path": k, "sha256": sha256(k bytes), "strength": 1.0}]`. An uncast unit has no `loras` key |
| P14 | reuse: render the P9 manifest, then rerun with `--resume` and the same manifest | the second run renders nothing (all `resumed: True`) |
| P15 | rerun with `--resume` after (a) panel 2's ronin strength changes to 0.6; (b) kyra's LoRA file bytes change (rewrite with new content and a new mtime); (c) panel 1's characters removed | (a) panels 2 and 3 re-render (3 is chained to 2); (b) all panels re-render; (c) panels 1-3 re-render |
| P16 | `lora_sha256` is called twice on the same file | `file_sha256` runs once (patched counter). After `os.utime` changes the mtime_ns, it runs again |
| P17 | `render_panel` where the LoRA file is deleted between the reuse check and `build_clip_provenance(strict=True)` | status `"error"`, `panel 1 FAILED (provenance)` on stderr |
| P20 | `bin/ltx-story-manifest` `--chain --cast "the woman in grey=kyra" --cast "the ronin=ronin"` on a 3-panel story (panel 1 Motion names her, panel 2 both, panel 3 neither), with module `WS` patched to tmp | rc 0. `motion_prompt`s have triggers inserted. `panel_text`s are byte-identical to an uncast run. `characters` lists `[kyra@1.0]`, `[kyra@0.8, ronin@0.8]`, `[]`. Entry keys `{name, phrase, trigger, video_lora, strength}`. `schema_version == 3`. stdout has `cast: panel 1: kyra@1.0` |
| P21 | as P20 with `--character-strength 0.6` and ronin's `character.json` `strength 0.5` | panel 2 `[kyra@0.6, ronin@0.5]` |
| P22 | `--cast` phrase occurring in no Motion: text | rc 0. stdout has the E-P14 `WARNING:` |
| P23 | `--cast` without `--chain`; `--character-strength` without `--cast`; an unknown character; `--character-strength 0` | `SystemExit 2` / `SystemExit 2` / rc 2 / rc 2. No manifest written |
| P24 | the uncast run's manifest | has no `characters` key on any panel |
| P25 | `_prompt_length_warning` sees the cast prompt (a Motion: of 149 words plus one inserted trigger) | the `WARNING: unit 1 prompt is 150 words` line does not appear, but a 150-word Motion: plus a trigger (151) does |
| P30 | `bin/ltx-story-images --cast "the woman in grey=kyra" --only 1` with kyra having a stills LoRA. Fake `torch`/`z_image_skill`/`content_safety` modules are in `sys.modules`; the fake `generate_image` records kwargs | the call has `loras == [(stills, 1.0)]` and `lora_path is None`. The prompt has `the kyrawmn woman in grey`. `images.json` panel `loras == [{"kind": "character", "name": "kyra", "path": stills, "strength": 1.0}]` and `prompt` is the cast prompt |
| P31 | kyra without a stills LoRA | stdout has the E-P17 `WARNING:`. The prompt has no trigger. The call has no `loras` key. `images.json` panel `loras == []` |
| P32 | `--only 1,2` where panel 1 names kyra and panel 2 names ronin (both with stills) | rc 2, E-P16. `generate_image` never called |
| P33 | (amendment 2) `--cast "the woman in grey=kyra" --lora g:0.5 --only 1` (kyra with a stills LoRA, `g` real) | rc 0. The call has `loras == [(g, 0.5), (stills, 1.0)]` and `lora_path is None`. `images.json` panel `loras` kinds are `["global", "character"]` |
| P34 | `--dry-run --cast …` | stdout shows the cast prompt and `    loras: kyra=<p>@1.0`. `torch` not imported (subprocess check, as in the existing I-tests) |
| P35 | the uncast run with the same fake modules | the call kwargs have no `loras` key. `images.json` panels have no `loras` key |
| P40 | `ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block="CAST")` | equals the uncast prompt with `"\n\nCAST"` inserted immediately before `"\n\nHow this movie is made:"`. With `seed_image=True`, the preface and postface are unchanged and the block is inside |
| P41 | `build_story_prompt(..., cast_block=None)` and `cast_block=""` | identical to the call without the keyword |
| P42 | `_resolve_casting` E-P1, E-P2, E-P4, E-P5, E-P6a (unknown), E-P6b (duplicate phrase), E-P7, E-P8, E-P9 | each returns 2 with the exact message: E-P6a is two lines (P50), every other case is exactly one line. `args.cast_members == []` |
| P43 | `_resolve_casting` with `--character kyra` and no story.md | 0. `cast_block == build_cast_block([kyra])`. `character_strength == 0.8` |
| P44 | `_resolve_casting` with story.md present containing `the woman in grey`, `--character kyra --cast "the ronin=ronin"` | 0. `cast_block is None`. Members `[kyra, ronin]`. `_cast_flags(args) == ["--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin", "--character-strength", "0.8"]` |
| P45 | `_cast_flags` on a `Namespace` without `cast_members`, and with `[]` | `[]` |
| P46 | `ltx-movie --dry-run --character kyra` (no story.md) | exit 0. stdout has `--- Cast ---`, the `cast: kyra as "the woman in grey" (…)` line, the CAST block inside the rendered prompt, and `--cast 'the woman in grey=kyra' --character-strength 0.8` on both the Phase 2 and Phase 3 manifest command lines |
| P47 | `phase1_story` with Phase 1 skipped (story.md exists without the phrase, forced through by setting `args.cast_members` directly) | the E-P10 warning is printed. rc 0 |
| P48 | `phase2_stills` with casting and an existing `images/panel_01.png` (`subprocess.run` patched) | the E-P11 warning. The cmd ends with the `_cast_flags` |
| P49 | `ltx-movie` uncast: `sys.modules` after `main(["n", "--story-id", "x", "--dry-run", "--no-review"])` | no module named `character_lib` was loaded |
| P50 | `_resolve_casting` with `--character ghost`, lib = kyra + ronin (trained) | rc 2. stderr `== "Error: unknown character: ghost (no <lib>/ghost/character.json)\navailable characters: kyra (the woman in grey), ronin (the ronin)\n"` |
| P51 | as P50 with an empty lib; and with a lib holding only `zed` (untrained) via `--character zed` | stderr second line `== "available characters: none (create one with bin/character create)"` in both. In the second case the first line is the 3.5 not-trained message |
| P52 | `--cast "the ronin=Ronin"` (invalid name); `--character kyra` where kyra's video file is deleted; `--character kyra --character kyra`; `--cast "the ronin"` (no `=`) | the first two: error line plus the available line (in the second, kyra is absent from it). The last two: exactly one stderr line, with no `available characters:` |
| P53 | `main(["--list-characters"])` with the C45 lib. `subprocess.run`, `subprocess.Popen` and `builtins.input` are patched to raise; `_story_dir` is unchanged | rc 0. stdout `== "\n".join(lib.character_table_lines()) + "\n"`. stderr empty. No `.movie.lock` created anywhere under `WS/generated/stories`. Nothing patched was called |
| P54 | `main(["--list-characters", "--story-id", "x"])`, `main(["a narrative", "--list-characters"])`, `main(["--list-characters", "--help"])` | each rc 2. stderr `== "Error: --list-characters takes no other arguments\n"`. stdout `""` (no `SystemExit` from argparse) |
| P55 | subprocess: `[sys.executable, "bin/ltx-movie", "--list-characters"]` vs `[sys.executable, "bin/character", "list"]`, both with `CHARACTER_LIBRARY_DIR` = the C45 lib, `cwd=WS` | both rc 0, byte-identical stdout, empty stderr |
| P56 | `ltx_movie.build_parser().format_help()` | contains `--list-characters`. The L1-style substring checks (`"145 frames @ 24 fps = 6.04s per clip."`) still hold. B1 still passes |
| P57 | manifest `--cast "the ronin=ghost"`; images `--cast "the ronin=ghost"` | rc 2. stderr is the single `Error: unknown character: …` line, with no `available characters:` (E-P6c) |
| P60 | `SKILL.parse_lora_spec` on every 5.7.1 table row | each result or `ValueError` exactly as tabled |
| P61 | render legacy route: `--lora /tmp/my.safetensors` (nonexistent) on an uncast manifest; then `--lora <real g>` and `--lora <real g>:1.0` | the first behaves like R33 (`kw["lora_path"] == "/tmp/my.safetensors"`, no `loras` kwarg, no file check). The last two give identical `received_kwargs` and identical provenance JSON (`lora_path == g`, no `loras` key) |
| P62 | render merged, uncast: `--lora a:1.0 --lora b:0.5` (real files) | every call has `loras == [(a, 1.0), (b, 0.5)]`, `lora_path is None`. Provenance `loras` kinds `["global", "global"]` |
| P63 | render, cast + globals: P9 manifest with `--lora a:0.7` | panel 1 `[(a, 0.7), (k, 1.0)]`, panel 2 `[(a, 0.7), (k, 0.8), (r, 0.8)]`, panel 3 `[(a, 0.7)]`: the global's strength is untouched, and globals do not count toward the character rule |
| P64 | render duplicates: `--lora a --lora a`; `--lora <symlink to a> --lora a`; `--lora k` where k is kyra's `video_lora` on the cast manifest (also via a symlink) | each exits 2 with E-P27 / E-P27 / E-P28 (`… (panel 1); pass it once`). `generate_video` never called |
| P65 | render merged-route errors: `--lora a --lora /missing.safetensors`; `--lora a:0`; `--lora a:3` | E-P26; E-P25; E-P25. Each exits 2 |
| P66 | `--resume` with globals on the P9 manifest: rerun after (a) the same flags; (b) `a:0.7` → `a:0.6`; (c) `--lora a --lora b` → `--lora b --lora a`; (d) LoRA X used as the global on run 1, and as a character LoRA (no global) on run 2 for an uncast→cast manifest change on panel 3 only | (a) nothing re-renders; (b) all panels re-render; (c) all re-render (order is identity); (d) panel 3 re-renders (kind differs) |
| P67 | render `--dry-run` with `--lora a:0.7` on the P9 manifest | each panel lists `            lora: <a> @ 0.7 (global)` first, then its character lines |
| P68 | ltx-story-images, no `--cast`: (a) `--lora my_lora.safetensors` (nonexistent); (b) `--lora g1 --lora g2:0.5` (real) | (a) `lora_path == "my_lora.safetensors"`, no `loras` kwarg, `images.json` has no `loras` key (today's behavior). (b) `loras == [(g1, 1.0), (g2, 0.5)]`, `lora_path is None`, `images.json` `loras` kinds `["global", "global"]` |
| P69 | ltx-story-images errors: `--lora <kyra's stills_lora>` with `--cast …=kyra`; `--lora /missing:0.5`; `--only 1,2 --lora g:0.5` where panels 1 and 2 match different characters | E-P28 (`stills LoRA`); E-P26; E-P16. `generate_image` never called |
| P70 | ltx-movie legacy: `--lora x` (nonexistent, no cast) | `_resolve_global_loras` returns 0 with both lists `[]`. `_render_flags(args)` equals today's (contains `["--lora", "x"]`). The B1 golden still matches |
| P71 | ltx-movie merged: `--character kyra --lora g:0.7 --stills-lora s` (real files, kyra with a stills LoRA, no story.md) | rc 0. `_render_flags` contains `["--lora", "<abs g>:0.7"]` and no raw `g`. The Phase 2 dry-run command contains `--lora <abs s>:1.0` (merged, because kyra has a stills LoRA), then the `_cast_flags` |
| P72 | ltx-movie: `--character kyra --lora <kyra video_lora>`; `--stills-lora s --stills-lora s`; `--lora g:abc` (treated as path `g:abc`, missing) with a cast | E-P28 (`video LoRA`); E-P27; E-P26. Also, `--character kyra --lora g` is accepted (the former E-P3 is gone) |
| P73 | `_RepeatableLoraAction`: parse `["--lora", "a", "--lora", "b"]`; parse with no `--lora` | `lora_path == "a"`, `lora_path_specs == ["a", "b"]`; `lora_path is None` and `not hasattr(ns, "lora_path_specs")` |
| P74 | `SKILL.generate_video(..., loras=[(g, 2.0), (k, 1.0)])`; `loras=[(g, 2.0001)]` | the first is accepted (argv `--lora g 2.0 --lora k 1.0`); the second raises `ValueError` |
| P75 | `inspect.getsource` of `_RepeatableLoraAction` in bin/ltx-movie, bin/ltx-mlx-render, bin/ltx-story-images | all three are identical strings |

### 9.6 `tests/test_z_image_skill_multi_lora.py`

It uses the `_fake_pipeline_classes` pattern from `tests/test_z_image_skill_cache.py:80-110`, extended: the fake pipeline records `load_lora_weights(path, **kw)`, `get_list_adapters()` (returns `{"transformer": [loaded names]}`, except that a path containing `"nomatch"` is not registered), `set_adapters(names, adapter_weights=…)`, and `fuse_lora(**kw)`. Each test resets `z_image_skill._pipeline = None` and `_pipeline_loras = None`.

| ID | Test | Assertion |
|---|---|---|
| Z1 | `load_pipeline(loras=[("a.st", 1.0), ("b.st", 0.8)])` | `lora_calls == [("a.st", {"adapter_name": "lora0"}), ("b.st", {"adapter_name": "lora1"})]`; `set_adapters` called once with `(["lora0", "lora1"], adapter_weights=[1.0, 0.8])`; `fuse_calls == [{"adapter_names": ["lora0", "lora1"], "lora_scale": 1.0}]` |
| Z2 | `load_pipeline(lora_path="x", loras=[("a", 1.0)])` | `ValueError` raised before `Qwen3Model.from_pretrained` (the fake records no construction) |
| Z3 | `load_pipeline(loras=[("nomatch.st", 1.0)])` | `ValueError` containing `"matched no Z-Image transformer weights"`. No `set_adapters`/`fuse_lora` call |
| Z4 | `generate_image("p", loras=[("a", 1.0)])` twice with the same set; then with `[("b", 1.0)]` | `load_pipeline` once; the third call raises `RuntimeError` |
| Z5 | `generate_image("p", lora_path="x")` with `load_pipeline` monkeypatched to `lambda lora_path=None: fake` | works (proves the uncast call shape is unchanged) |
| Z6 | `load_pipeline(lora_path="my_lora.safetensors")` | `lora_calls == ["my_lora.safetensors"]` (positional only) and `fuse_calls == [{"lora_scale": 1.0}]`, the same as `test_z_image_skill_cache.py:113-123` |

### 9.7 Regression, mutation, acceptance, live gates

**R1 (SC9).**

- Run each suite directly by the main thread; counts reported by the implementer are not accepted. They must give exactly the 0.2 results: `OK 344/344`, `OK 101/101`, `OK 443/443`, `OK 146/146`, `OK 32/32`, `OK 77/77`, `RESULT: ok`, `13 passed`.
- None of those files may appear in `git diff --stat`.

**R2 (SC10).** `python3 -m pytest tests/test_deploy_pkg.py` → `165 passed`, and `/usr/bin/python3 -m unittest tests.test_deploy_pkg` → `Ran 165 tests … OK`.

**B-goldens (`tests/test_casting_regression.py` + `tests/fixtures/casting_baseline/`).**

- The goldens are captured by `python3 tests/test_casting_regression.py --capture`, which the plan runs **before any production code changes** and commits. Running under pytest compares.
- Normalization replaces `WS` with `<WS>`, `sys.executable` with `<PY>`, and the fixture image path with `<IMAGE>`. `created_at` is removed.

| ID | Golden | Command |
|---|---|---|
| B1 | `ltx_movie_dry_run.txt` | `subprocess.run([sys.executable, "bin/ltx-movie", "a test narrative", "--story-id", "casting-baseline-dry", "--dry-run", "--no-review", "--model", "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"], cwd=WS, env=dict(os.environ, STORY_PIPELINE_LOGGED="1"), capture_output=True, text=True).stdout`, normalized |
| B2 | `manifest.json` | `story_manifest.main(["--story-id", "casting-baseline-manifest", "--prompts-md", <fixture story.md>, "--chain", "--image", <64x64 PNG made at runtime>, "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145", "--max-frames", "145", "--force"])`, with module `WS` patched to `tmp_path`. The written manifest is normalized. `story.md` is a 3-panel chain fixture: panel 1 Image/Motion/Narration, panels 2-3 Motion/Narration, naming `the woman in grey` |
| B3 | `build_command.json` | `SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png", width=704, height=448, num_frames=145, frame_rate=24, seed=1, model="M", gemma="G")` with `SKILL.LTX2_MLX_BIN = "/bin/ltx"`, as a JSON list |

**Mutation checks.** Before declaring the implementation complete, apply each mutation alone, run the named file, confirm that at least one named test fails, and revert.

| Mutation | Must fail |
|---|---|
| `_phrase_regex` drops `re.IGNORECASE` | C23, C31 |
| boundary lookarounds use `\w` only (hyphen not excluded) | C26 |
| `(?<![\w-])` removed | C26 (`bathe ronin`) |
| `cast_text` sorts members shortest first | C27 |
| overlap check removed | C27 |
| trigger inserted before the article | C23 |
| `trig` group removed (no idempotence) | C29, C28 |
| no-article branch inserts after the first word | C28 |
| `panel_strengths` always uses `character_strength` | C36, P20 |
| `panel_strengths` ignores the per-character override | C37, P21 |
| `resolve_cast` skips the status check | C38 |
| `resolve_cast` skips the duplicate-phrase check | C38 |
| `auto_trigger` drops the digit suffix loop | C6 (`kyrawmn2`) |
| `validate_character` drops `alpha == rank` | C11 |
| `build_command` formats strength with `"%g" % strength` (`"1"` for 1.0) | P1 |
| `build_command` emits `loras` after `--distilled` | P1 |
| `_validate_generate_args` skips the file check | P4 |
| `build_units` always adds `"loras"` | P8, R1 (R4l) |
| provenance omits `sha256` | P15(b) |
| provenance omits `strength` | P15(a) |
| provenance adds `"loras": []` for uncast units | P13, R1 |
| `render_panel` always passes `loras=` | P9 (panel 3), R1 (R33) |
| (amendment 2) the old E-P19 refusal retained (`--lora` + cast exits 2) | P10 |
| legacy route removed (always merged) | P61, R1 (R33, R18z) |
| legacy condition ignores the cast | P63, P10 |
| globals placed after the characters | P10, P63 |
| global strength reduced in multi-character panels | P63 |
| `panel_strengths` counts globals | P63 (panel 1 kyra would drop to 0.8) |
| duplicate-global check removed | P64 |
| duplicate check by path string instead of realpath | P64 (symlink cases) |
| global-vs-character duplicate check removed | P64, P69, P72 |
| `parse_lora_spec` splits on the first `:` | P60 (`/p/a:b.safetensors:0.8`) |
| `parse_lora_spec` errors on a non-float suffix | P60 (`org/repo:main`) |
| `parse_lora_spec` accepts strength 2.5 | P60, P65 |
| provenance omits `kind` | P66(d) |
| provenance list sorted (order not identity) | P66(c) |
| ltx-movie keeps the E-P3 refusal | P72 |
| ltx-story-images keeps the E-P15 refusal | P33 |
| `_render_flags` forwards raw values on the merged route | P71 |
| `_RepeatableLoraAction` overwrites the dest with the last value | P73, R1 (I21) |
| `lora_sha256` cache keyed on path only | P16 |
| manifest inserts triggers into `panel_text` too | P20 |
| manifest omits `characters: []` on uncast-in-cast panels | P20 |
| casting applied after `_prompt_length_warning` | P25 |
| z_image fuses each adapter separately | Z1 |
| z_image skips the `get_list_adapters` check | Z3 |
| z_image ignores a different LoRA set on a loaded singleton | Z4 |
| ltx-story-images inserts triggers for members without a stills LoRA | P31 |
| E-P16 check removed | P32 |
| `build_story_prompt` appends the block at the end | P40 |
| `_resolve_casting` allows `--cast` when Phase 1 runs | P42 |
| `_cast_flags` omits `--character-strength` | P44 |
| ltx-movie imports `character_lib` at top level | P49 |
| `resolve_cast` raises plain `CharacterError` for not-trained | P51, C38 |
| `parse_cast_arg` keeps a plain `CharacterError` for an invalid name | P52, C22 |
| `_resolve_casting` catches only `CharacterError` (drops the available line) | P50 |
| `_resolve_casting` prints the available line for every `CharacterError` | P52 |
| `usable_characters` skips the `resolve_cast` check (lists every name) | C43, P52 |
| `format_available_line` returns `"available characters: "` for an empty list | C42, P51 |
| `usable_characters` iterates in creation order, not sorted | C43 |
| `bin/character list` keeps its own table code with a different column width | K2, P55 |
| `--list-characters` pre-scan removed (left to argparse) | P53 (argparse `SystemExit` for the missing `--story-id`) |
| `_list_characters` accepts extra arguments | P54 |
| `--list-characters` handled after the lockfile or sudo check | P53 |
| manifest/images print the available line | P57 |
| `train()` checks memory before the story server | D26 (order) |
| `story_server_state` returns `"STOPPED"` on failure | D16 |
| `train_video` records the LoRA after the test renders | D24 |
| `stills_epochs` uses floor | D9 |
| compat gate accepts `injected != expected` | D30 |
| incompatible adapter overwrites a good previous stills LoRA | D34 |
| `create` writes the dir before the face check | K7 |
| `build_dataset` restarts the vision server only on success | K13 |
| descriptor mode does not force-keep the reference | K10 |

**Live gates.** These are run by the main thread or the user, on hardware, one at a time, with no concurrent renders. Before each GPU gate, `bin/story-server status` and `vm_stat`/available memory are recorded.

| ID | Gate | Pass condition |
|---|---|---|
| L0 | **mflux compat gate (plan task 1).** After the user approves 4.10, install it. Run a smoke train in the gitignored scratch dir `generated/charlora/mflux-compat/` (not `/tmp`). Data: copies of `generated/charlora/kyrawmn-v1/stills/char_NN.png` with `captions/char_NN.txt`. Config: `stills_train_config(…, kept=24)` with `num_epochs` overridden to 4 (96 steps) and `save_frequency` 48. Command: `HF_HOME=~/hf_home ~/mflux/.venv/bin/mflux-train --config …`. Extract the adapter (4.9 step 4). Then, in a throwaway `python3 -c` using the **existing** `z_image_skill.load_pipeline(lora_path=<adapter>)`, count `lora_A` modules against `lora_module_count(safetensors_keys(adapter))`, and render `kyrawmn woman, medium shot, standing and facing the camera, …` at 1024x640, seed 42 | `mflux-train` exits 0. Record s/step, the peak footprint (`/usr/bin/time -l`), the checkpoint dir layout, and the adapter key sample (first 5 keys) in the plan's notes. **Compatible** iff injected == expected > 0 and the image renders. If incompatible, report to the user before building 4.9; the code is still built per spec (it then always skips). If s/step x 2400 > 4 h, report it to the user |
| L1 | Face-measure calibration (VLM only): `face_height` on `generated/charlora/kyrawmn-v1/stills/char_01.png`, and on `generated/stories/ronin-e2e-appearance-20261005/images/panel_01.png` | char_01 >= 0.25. ronin panel_01 < 0.15, or None. Record both values. If they do not separate, report (G3) |
| L1b | DESCRIBE on the ronin `panel_01.png` (a riding scene) | the descriptor does not contain `boots`, `riding`, `horse`, or `reins`. It mentions apparent ethnicity if the VLM states one. Record it |
| L2 | `bin/character create kyra --phrase "the woman in grey" --seed-image generated/charlora/kyrawmn-v1/stills/char_01.png` | exit 0. kept >= 12. Contact sheet eyeballed (consistent face, hairpins, kimono). Trigger `kyrawmn`. The vision server is serving again afterwards |
| L3 | `bin/character create ronin --phrase "the ronin" --descriptor "a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama" --class man` | exit 0. kept >= 12. Contact sheet eyeballed. Trigger `roninmn` |
| L4 | `bin/story-server stop`; `bin/character train kyra` | exit 0. A skipped or incompatible stills LoRA (CT9/CT13) still exits 0 here, because `--stills` was not given. Exit 1 only on CT10, CT11, or CT12. `lora/video.safetensors` is 641,974,104 bytes. A/B eyeballed: `tests/video_lora.mp4` shows the character; `video_control.mp4` shows a stranger. If the stills LoRA trained: `tests/stills_lora.png` shows her, and the control shows a stranger. Record the wall-clock time (~47 min expected for video) and the peak footprint |
| L5 | `bin/character train ronin` | as L4 for the ronin |
| L6 | **Bleed sweep (acceptance gate).** Three story dirs, `generated/stories/bleed-sweep-s10`, `-s08`, `-s06`, each holding the 9.8 `story.md`. Run `bin/ltx-movie "two-character bleed sweep" --story-id bleed-sweep-sNN --panels 2 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength S` for S = 1.0, 0.8, 0.6. Then `bin/judge-clips --story-id bleed-sweep-sNN` for each | Each run exits 0, and the manifests show both characters at S on both panels. **Winner rule:** the highest S at which, in both panels, she shows her trained identity (face, three jade hairpins, grey kimono) with no male or ronin traits, **and** he shows topknot, scarred brow, and indigo haori with no female, kimono, or hairpin traits, by the user's eyeball. judge-clips `physical_realism` breaks ties (higher wins). If no S passes, the default stays 0.8 and G4 is recorded as unresolved. The winner is written into `DEFAULT_CHARACTER_STRENGTH` (plus C36/C37 and the help texts "default 0.8") in a follow-up commit |
| L6b | **Character + global quality case: DEFERRED** **[spec choice: defer, do not download]** | Run when the user provides a real non-character LTX LoRA `G`. Repeat the L6 `bleed-sweep-s08` command with `--lora G:1.0`, then with `--lora G:0.6` (new story ids `bleed-sweep-s08-gG10`/`-gG06`). Pass: G's effect is visible, and both identities hold by the L6 rule. Until then, record "L6b deferred: no non-character LoRA available locally (G22)" in the acceptance notes |
| L6m | **Mechanical global + character check** (not a quality signal) | Story id `bleed-sweep-globalmech` with the 9.8 `story.md`. Run the L6 command at S = 0.8 plus `--lora generated/charlora/kyrawmn-v1/out_full/checkpoints/lora_weights_step_00250.safetensors:0.3`. This is the spike's out-of-library checkpoint, used **only** as a stand-in global file. Pass: exit 0. Each clip's provenance `loras` has kinds `["global", "character", "character"]`, with the global at 0.3 and the characters at 0.8. The logged ltx-2-mlx argv has three `--lora` triples. Record the wall-clock time per panel against L6 |
| L7 | **Cast re-render.** Create `generated/stories/ronin-e2e-appearance-20261005-cast/` holding only a copy of the original `story.md`. Run `bin/ltx-movie "re-render of an existing story" --story-id ronin-e2e-appearance-20261005-cast --panels 20 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin"`. Then `bin/judge-clips --story-id ronin-e2e-appearance-20261005-cast` | exit 0, 20 clips. Each panel's `characters` in `manifest.json` equals `cast_text(<that panel's Motion: text>, members)[1]`, computed in a REPL from the copied `story.md`. Record the 20 lists. Note that panel 1's Motion: does not name her, so panel 1's clip gets no LoRA (G5) while its still does. Eyeball against the original `movie.mp4`: she stays recognizably the same across her panels, and he is recognizable from panel 12. Record both clips judgments (original movie: seam 7, narrative 2) side by side. The user's eyeball is decisive |

**Ordering note.** L2/L3 need the vision server up; L4-L7 need it down. The plan sequences them as L1, L1b, L2, L3 (server up), then `bin/story-server stop`, then L4, L5, L6, L6m, L7. L6b is deferred (G22).

### 9.8 Bleed-sweep `story.md` (exact)

```
# Bleed sweep

A two-character test scene.

## Panel 1 — Two Travellers
Image: A medium shot, eye level, of the woman in grey and the ronin standing side by side on a packed-dirt forest trail, both facing the camera, the woman in grey on the left and the ronin on the right. The woman in grey is a young East Asian woman, slender, with pale skin and long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi. The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama. Tall cedar trunks and ferns line the trail behind them. The light is overcast and flat, with a muted green, brown and grey palette. The rendering is photorealistic live-action film still.
Motion: The woman in grey turns her head toward the ronin while the ronin rests his left hand on his scabbard; the camera stays static.
Narration: Two travellers pause on the forest trail.

## Panel 2 — The Nod
Motion: The ronin nods once to the woman in grey, and the woman in grey bows her head slightly in return.
Narration: A silent agreement passes between them.
```

---

## 10. Task decomposition hint (for the planner)

1. **L0: mflux install (user-gated) + compat gate.** This is a throwaway check that touches no repo code. Report the result before building 4.9.
2. **B-golden capture** (`tests/test_casting_regression.py --capture`, plus the fixtures), committed before any production edit.
3. `character_lib.py` + `tests/test_character_lib.py`, including the 3.9 cast-discovery helpers and C42-C46.
4. `ltx2_mlx_video_skill.py` `loras` + P1-P5, plus amendment 2's `parse_lora_spec` (P60, P74).
5. `z_image_skill.py` multi-adapter + Z1-Z6. Amendment 2 needs no code change: the order is globals then characters, which callers build.
6. `bin/ltx-mlx-render` + P6-P17, plus amendment 2: `_RepeatableLoraAction`, 5.7.3, `kind` in units and provenance, and the E-P19 removal (P10, P13, P61-P67, P75).
7. `bin/ltx-story-manifest --cast` + P20-P25. Amendment 2 does not change the manifest: globals are render and stills flags, not manifest content.
8. `bin/ltx-story-images --cast` + P30-P35, plus amendment 2: 5.7.4 and the E-P15 removal (P33, P68, P69).
9. `bin/ltx-movie` casting + P40-P49, plus amendment 2: `_RepeatableLoraAction`, `_resolve_global_loras`, the forwarding, and the E-P3 removal (P70-P73). Then amendment 1: the E-P6a available line (P50-P52), `--list-characters` (P53-P56), and P57 (manifest/images unchanged).
10. `character_dataset.py`: create half (prompts, face, describe, score, contact sheet, child protocol, gates) + D1-D19, D35-D37.
11. `character_dataset.py`: train half (4.8, 4.9, 4.11) + D20-D34.
12. `bin/character` + K1-K18. `list` reuses `character_table_lines()` (K2, P55).
13. Deploy tuple (Section 8) + R2.
14. R1 + B + the full mutation table, run by the main thread. Then the design-reviewer (Opus high) code review.
15. Live gates L1 → L7 in the 9.7 order. L6 is the **acceptance gate** that sets `DEFAULT_CHARACTER_STRENGTH`, followed by the one-line follow-up commit.

Tasks 3-9 and 10-12 are independent chains. Within each chain the order matters.

---

## 11. Known gaps

- **G1. mflux → diffusers key compatibility is unverified.**
  - mflux saves `{n:07d}_adapter.safetensors` inside a zip, with key names not seen. diffusers converts only `lora_unet_` / `diffusion_model.` / `.alpha` / `default.` formats, and silently ignores unmatched keys.
  - The compat gate (4.9) and L0 are the only proof. The stills half may ship permanently skipped.
- **G2. Text-encoder mismatch.** mflux trains with stock Z-Image-Turbo (Qwen3-4B text encoder), but `z_image_skill` renders with the abliterated `BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1`. A LoRA learned against one encoder's embeddings is applied under the other's. L4's stills A/B is the only check.
- **G3. Face-box convention.** That `qwen38-6bit` (Qwen3-VL-32B, 6-bit) returns 0-1000 relative boxes is assumed from the model family, and L1 calibrates it. If it returns pixel coordinates of its resized input, the threshold is meaningless until it is re-derived.
- **G4.** The multi-character default strength of 0.8 is provisional until L6.
- **G5.** An on-screen character whose phrase is absent from a panel's prompt gets no LoRA (approved limit). Pronoun-only panels (`"she turns"`) are the common case.
- **G6. Multi-LoRA at strength ≠ 1.0 on the distilled two-stage `--low-ram` path is unverified on hardware.** The `--low-ram` help says custom strengths take a slower bind-time fusion path. L6 measures the speed and quality.
- **G7. Cross-version LoRAs.** The LoRA is trained on LTX-2.3 dev and applied to LTX-2.5 distilled. The spike proved one character at 1.0 only. Two summed LoRAs are covered only by L6.
- **G8. Judges see trigger tokens.** `motion_prompt` carries trigger tokens (`the kyrawmn woman in grey`), and judge-clips sends `motion_prompt` as the panel's Motion: text. The judge sees a rare word. Judges are out of scope.
- **G9. Stale panel 1 still.** `bin/ltx-story-images` reuses an existing `panel_01.png` by existence only. A cast run on a story with an uncast still keeps the uncast still (warning E-P11 only). Render provenance still re-renders correctly, because the image hash is unchanged and the LoRA set differs.
- **G10. Scorer and captions.** The scorer stays lenient (CHECK_PROMPT unchanged), and the caption `pose` field can leak clothing (`holding black boots`). Both were observed in the spike and not addressed by the approved design.
- **G11. Seed-image and CAST block conflict.** `--seed-image` + `--character` gives the story model two instructions that can conflict: describe the image literally, and use the cast description word for word. Not refused.
- **G12. Deploy targets.** They get `character_lib.py` but no tooling. Copied library dirs carry absolute LoRA paths that must match the target's layout.
- **G13. Concurrency is enforced only by `bin/character`.** `bin/ltx-movie` does not refuse to start during a training run. Its avail-memory gate (25 GiB) normally blocks it, because training holds about 40 GB.
- **G14. Unverified mflux details.** The placement of `gradient_checkpointing`, the checkpoint subfolder layout (handled by the recursive glob), steps-per-epoch semantics (hence the "highest step" rule), and runtime and memory. L0 records them.
- **G15. Trigger tokenization.** Whether Gemma-3 (the LTX encoder) and Qwen3-4B tokenize a trigger like `kyrawmn` into stable sub-tokens is unverified beyond the spike's success with exactly `kyrawmn`.
- **G16. Hashing cost.** Provenance hashes each LoRA once per render process: about 0.5-1 s per 642 MB file. The dry run hashes too, when `--resume` predicts.
- **G17. Process scan false positives.** `busy_process` matches on command-line substrings, so an unrelated process whose argv contains `bin/ltx-movie` (for example an editor) blocks create and train (fail-closed by design).
- **G18. No pruning.** About 2.6 GB of intermediate video checkpoints are kept per character. Pruning is out of scope.
- **G19. The legacy route keeps today's lax validation.** A single `--lora` at 1.0 with no cast is not checked for existence (HF repo IDs still work), but the same file with a cast, or with a second LoRA, is validated. A typo is therefore caught only on the merged route.
- **G20. Colon ambiguity.** A local LoRA whose filename itself ends in `:<number>` is read as `PATH:STRENGTH`. The workaround is to append `:1.0`. HF repo IDs containing `:` followed by a number are not supported on the merged route.
- **G21. Order is part of identity.** Reordering `--lora` flags re-renders every clip, although the summed deltas are the same.
- **G22. No quality check for globals.** No non-character LTX LoRA exists on this machine. The only other LoRA file is the pack's own `ltx-2.5-22b-distilled-lora-450-bf16.safetensors`, which the distilled pipeline already applies internally, so it is not usable as a global. The quality of a global combined with the cast (L6b) is unverified until the user supplies one. L6m checks only the mechanics.
- **G23. Global plus character overload.** A global LoRA trained on a different base, or at a high strength, may overpower the character LoRAs. Globals are never auto-reduced (5.7.6), so the user tunes `PATH:STRENGTH` by hand.

---

## 12. Review Focus

These are the five failure modes most likely to matter that the offline tests cannot fully cover:

1. **Phrase matching on real story text.**
   - The ronin story embeds `Appearance: The woman in grey is …` inside Motion: fields, uses possessives (`the spear robber's`), and has phrases nested in longer ones (`the robber` is not cast, but `the bearded robber` might be).
   - The review should run `cast_text` mentally (or in a REPL) over `generated/stories/ronin-e2e-appearance-20261005/story.md`, and confirm the per-panel character lists L7 expects.
2. **Provenance and `--resume` with LoRA identity.**
   - Confirm that the chained cascade re-renders everything after the first changed panel, that the sha cache cannot serve a stale hash (key = realpath, size, mtime_ns), and that an uncast unit's provenance is byte-identical to today's (no `loras` key).
   - A wrong call here silently reuses a clip rendered with a different identity.
3. **The z_image multi-adapter fuse.**
   - `set_adapters` + `fuse_lora(adapter_names=…)` on diffusers 0.40 / peft 0.20 with `Z_IMAGE_QUANTIZE_WEIGHTS=int8` (quanto layers) is untested. The existing single-LoRA path has the same exposure.
   - The registration check proves the adapter registered, not that the fused weights are numerically right. L4's A/B is the real proof.
4. **The mflux compat gate's definition of "compatible".**
   - `injected == expected` counts modules by key-prefix grouping. A converter that renames keys while keeping one module per prefix passes. A file whose keys use no `.lora` substring yields `expected == 0`, which is rejected.
   - Confirm this cannot accept a LoRA whose deltas land on the wrong modules (it can, if the names map wrongly but plausibly; L4's eyeball covers that).
5. **Safety gates under real host states.**
   - `story_server_state` must return `STOPPED` only when truly stopped (`LOADING` is the dangerous window, per `bin/story-server:16-20`).
   - The 30 GiB check runs once, with no wait loop.
   - `create` always restarts the vision server, even when generation fails.
   - The lock is released on every exit path.
   - Confirm the order: lock, then process scan, then server, then memory, then disk.

---

## 13. Open questions (non-blocking; defaults are specified above)

1. If L0 shows the mflux adapter is incompatible, should the stills half (4.9, D28-D34) still be built as specified (always skipping), or removed from scope? This spec builds it.
2. Should `bin/ltx-movie` also refuse to start while a `bin/character train` holds the library lock (G13)? This spec does not add that.
3. After L6, should the winning strength also become the per-panel stills strength? This spec uses one rule for both (Section 6).
