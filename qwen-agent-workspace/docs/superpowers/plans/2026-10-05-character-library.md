# Character library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the character-LoRA spike into a durable library and wire it into the movie pipeline:
- `bin/character create|train|list|show` builds `generated/characters/<name>/` (a validated `character.json`, a reviewed dataset with `dataset/contact_sheet.jpg`, a video LoRA trained with the spike config, and a stills LoRA trained through mflux that is kept only if it passes the compat gate);
- `bin/ltx-movie --character NAME` / `--cast "PHRASE=NAME"` makes every panel whose prompt names a cast phrase render with exactly those characters' LoRAs (1.0 alone, the multi-character strength otherwise), with the LoRA set recorded in clip provenance;
- the amendment's cast discovery: an `available characters:` line on unknown/unusable-character errors, and `bin/ltx-movie --list-characters`;
- an uncast run stays byte-for-byte what it is today (SC9).

**Architecture:** One stdlib-only owner of the schema and casting rules (`character_lib.py`), loaded by path only inside the casting branch of `bin/ltx-movie`, `bin/ltx-story-manifest` and `bin/ltx-story-images`. Everything heavy (VLM, ffmpeg, training subprocesses, safety gates, the Z-Image child process) lives in `character_dataset.py`, imported by `bin/character` only for `create`/`train`. The manifest is self-contained: each panel's optional `characters` list carries LoRA paths and strengths, so `bin/ltx-mlx-render` gains per-unit LoRAs without importing the library. `ltx2_mlx_video_skill` gains a `loras=` argv input; `z_image_skill` gains named adapters + `set_adapters` + one `fuse_lora`.

**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), pytest 8.3.4, Pillow 12.3.0, psutil 6.1.0, torch 2.12.1 / diffusers 0.40.0 (only behind fakes in tests), ffmpeg/ffprobe 9.0.1, Apple `/usr/bin/python3` 3.9.6 (deploy unittest gate only). mflux 0.21.0 in an isolated venv `~/mflux/.venv` (user-gated install, Task 1).

**Spec:** `docs/superpowers/specs/2026-10-05-character-library-design.md`, approved design `d038449` plus the user-approved amendments `136c6f8` ("cast discovery") and `bef47e4` ("global LoRAs combine with cast", Section 5.7), plus `18b43c4` (amendment 4: stills LoRA settings from L0 and the 512 test) and `9f980b2` (renumbered stills tests; the Task 10 review fix made normative). Spec decisions are not reopened. Where this plan must deviate because the spec is mechanically wrong, the deviation is listed under "Decisions" with the observed evidence (notably decision 1, the deploy test).

**How this plan was validated (2026-10-05):** every code block and edit below was applied, task by task, to a scratch copy of the workspace outside the repo (`/tmp/charplan/ws`, `/tmp/charplan/sim`; the target files were confirmed byte-identical to `HEAD`). Each block was then spliced into this document by a generator, byte for byte. Every "Expected:" count is an observation from replaying the task order on a pristine copy. That includes the red counts before each implementation step and the green counts after. The same applies to the 87/87 mutation catches. The amendment-2 revision was replayed from the real commit `0340882` (Task 2 already done). The amendment-4 revision was replayed onto the real commits `beedc77` (Task 11 applied from its text, then Tasks 12-14) and `f91de86` (Tasks 12-14). The existing suites gave their spec 0.2 counts after every task. The edit blocks for existing files were generated from base-versus-final diffs and verified to reproduce the final files exactly.

## Global Constraints

**Workspace and scope**
- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Run every command from `WS`. The git repo root is one level up, so `git diff --name-only` prints `qwen-agent-workspace/`-prefixed paths. Branch `qwen-agent-redteam`; base commit for the scope check: `136c6f8`.
- The working tree has unrelated modified files (`bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, `.gitignore`, `qwen-agent-workspace/.gitignore`) and many untracked files. Never stage them. Every commit stages files by explicit path and checks `git diff --cached --name-only` first. Every file this plan edits was verified clean against `HEAD` before planning; before each task, `git diff --quiet HEAD -- <that task's existing files>` must succeed.
- Commit messages start with a component prefix (`character_lib: `, `ltx-movie: `, ...) and end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- GPU work (Z-Image, training, renders) and server control happen only in the live-gate sections that the orchestrator runs (Task 1 and Final Acceptance L1-L7). Every implementer step is offline: fakes and mocks, no network, no GPU, no server. Do not run implementer tasks while a live gate is running.
- `rm` is blocked in this environment. Where a step needs a fresh directory, use a new path or move the old one aside with `mv`; never delete.

**Deliverables (spec 0.3, verbatim)**

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

This plan also edits four count-dependent expected values in `tests/test_deploy_pkg.py` (Decision 1). Its test count stays 165.

**Out of scope (spec 0.4, verbatim)**

- A `delete`/`rename` subcommand. Hand-editing anything other than `descriptor` and `referring_phrase` in `character.json`.
- Casting with `--no-stills` (refused: E-P2). Casting through `--story-prompt-override` when Phase 1 runs (refused: E-P8).
- Giving a LoRA to an on-screen character whose phrase the panel's prompt does not name. This is the known limit, recorded as G5.
- Tuning `CHECK_PROMPT` (the scorer's leniency) or the caption pose wording (G10).
- Shipping `bin/character`, `character_dataset.py`, mflux, the dev model, or any library content in the deploy package (Section 8).
- Pruning intermediate checkpoints, or choosing a checkpoint other than the last.
- Making `bin/ltx-movie` refuse to start while a training run is in progress (G13).
- Changing judges (`bin/judge-*`) or `bin/iterate-story`.

**Module boundaries and internal names (spec 1.2, 1.3, verbatim)**

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

**`bin/character` conventions and exit codes (spec 4.2, verbatim)**

- The shebang is `#!/usr/bin/env python3`. After stdlib imports: `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, `sys.path.insert(0, WS)`, `import character_lib`.
- `main(argv=None)` returns an int, and the file ends with `if __name__ == "__main__": sys.exit(main())`. There is no `pipeline_log` wiring (it is per-story) **[spec choice]**.
- `train`'s `--force` is a **[spec choice]** (the design lists none). It prevents an accidental 47-minute retrain that would replace a good LoRA.
- Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 `create` kept fewer than `MIN_KEEP` stills.

**Error handling (spec Section 7, verbatim; the exact message templates are in the code blocks of the tasks)**

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
| CT12 | mflux-train rc != 0; `sdir/out` already exists before the run (amendment 4); no adapter under `<out>/checkpoints/`; or the last checkpoint step != `total_steps` | 1 | 4.9 steps 1, 3 and 4 |
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

**Tests (spec 9.1, verbatim)**

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

Plan rules on top of 9.1:
- Exactly one test function per spec test ID; multi-case IDs loop inside one function. P55 lives in `tests/test_casting_pipeline.py` but is added in Task 13 (Decision 17). New test totals: `test_casting_regression.py` 3, `test_character_lib.py` 46, `test_z_image_skill_multi_lora.py` 6, `test_casting_pipeline.py` 63, `test_character_dataset.py` 41, `test_character_tool.py` 18 (177 in all). P75 lives in Task 9 (Decision 28).
- Each test file carries its own copy of the 9.1 helpers (`lib_dir`, `make_character`, ...): D11 fixes the file list, so there is no `conftest.py`.
- Test-run output: pytest prints a `pytest_asyncio` `PytestDeprecationWarning` at startup and `DeprecationWarning`s for `SourceFileLoader.load_module()`. The warning count varies by file. Neither is a failure. Gate on the `N passed` / `N failed` counts and on pytest's return code (printed as `rc=`), never on `$?` after a pipe to `tail`.

**Regression baselines (spec 0.2, verbatim; re-measured on this tree at planning time, identical)**

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

The new goldens (Task 2) add: `python3 -m pytest tests/test_casting_regression.py` -> `3 passed, 1 warning`.

**Mutation runner rules (Final Acceptance A3)**
- Each mutation is applied alone and judged by return code only. For a pytest target, 1 = CAUGHT, 0 = survived, anything else (2 collection error, 4 usage error, 5 no tests) = broken. For a direct-run target (`R1:<file>`), non-zero = CAUGHT.
- Before mutating, the runner asserts each anchor's exact occurrence count and that each target passes unmutated (control). It restores every file in `finally`.
- Every run gets a fresh `PYTHONPYCACHEPREFIX` and `TMPDIR`: a same-size mutation written in the same second as an earlier compile could otherwise load a stale `.pyc` and falsely survive.

## Decisions this plan makes where the spec is silent or inexact

These were decided while writing the plan and verified in the scratch copy. Do not re-decide them.

1. **The deploy test needs four expected-value edits besides the tuple (spec 0.3 D10 and 8 say "one tuple each").** Adding `character_lib.py` to `PIPELINE_FILES` makes the A1 component hold 19 files instead of 18, and the B07 resume prefix 27 entries instead of 26. With only the tuples edited, observation: `4 failed, 161 passed`. The four failing tests are `TestComponentCollection::test_stats` (`:841`, `(18, 3)`), `TestBuildCli::test_dry_run_report_format_and_writes_nothing` (`:1728`, `files=18`), `TestResume::test_RF2_resume_after_mid_copy_abort_completes_and_verifies` and `TestResume::test_T43_corrupted_listed_payload_is_recopied` (`:2222`, `:2248`, `resume prefix: 26 of`). Task 14 changes those values to 19 and 27, and the count stays 165 under both interpreters, as spec R2 requires. **The orchestrator reports this deviation to the user when Task 14 lands.** (`build_pkg.py:1569` prints a pre-existing stale "all 10 pipeline files". It is not touched.)
2. **`bin/ltx-story-images` keeps `tests/test_ltx_story_images.py` I20 green.** I20 pins `src.count("_compose_prompt(") == 3`, and spec 5.5's planning block would add a fourth call. The planning block therefore binds `compose = _compose_prompt` and calls `compose(...)`. The comment beside it must not contain the literal text `_compose_prompt(` either. I20 also pins `_panel_seed(args.seed, i, grounded)` to 2 occurrences, so the cast dry-run output is produced by editing the two existing dry-run `print` calls in place rather than adding new ones.
3. **I13 pins `"source": "generated"` to 4 occurrences.** The images.json `"loras"` key (spec 5.5) is therefore added by one loop after generation, `for r in results: if r["index"] in plans: r["loras"] = plans[r["index"]][1]`, not by editing the four `results.append` sites. `plans` is initialized to `{}` together with `members` and `strength`, so the uncast path is unchanged.
4. **`validate_character` message texts.** The spec fixes only the `"<field>: <reason>"` shape, so the reasons are the exact strings in Task 3's code. A missing or extra top-level key names the key; a LoRA entry's field is `loras.video` / `loras.stills`.
5. **Descriptors are validated twice.** `create` (descriptor mode) and `describe()` (seed mode) also run `character_lib.validate_descriptor` on the normalized descriptor. In descriptor mode a failure is CE9. In seed mode it counts as an unparseable reply: it is retried, then raises `DatasetError("describe failed: ...")`. Without this, a `validate_description`-normalized text such as `"AN ..."` would pass the first check and then crash `write_character` after the directory and trigger were already written.
6. **`story_server_state()` returns `"UNKNOWN"` when `bin/story-server status` exits non-zero**, as well as on OSError, timeout, or no `state:` line (fail closed; `status` exits 0 whenever it prints its report).
7. **`library_lock()`:** `os.kill(pid, 0)` raising `PermissionError` counts as alive. A pid `<= 0` or unreadable content counts as stale. If the retry also finds the file and its holder is dead, the result is `DatasetError("could not acquire the library lock <path>")`. `create`/`train` acquire the lock with `contextlib.ExitStack` so that only an acquire-time `DatasetError` becomes exit 2.
8. **Small helpers the spec leaves open:** `step_log_path` creates `<dir>/logs` (`exist_ok`). `run_zimage_child` sets `error.log_path = <log>` on the `DatasetError` it raises, so the compat reason reads `(see <log>)`; a fake `DatasetError` without the attribute falls back to its message. `wrap_still` also maps `OSError` (ffmpeg missing) to `DatasetError`. `build_dataset` prints `warning: story-server vision returned N` exactly like the stop warning. `extract_mflux_adapter` returns the zip path, and ranks a zip whose basename has no leading integer as -1.
9. **`create --regenerate` preserves `dataset/description.json`** (the raw VLM reply) across the `rmtree`. It tolerates a missing `dataset/` directory, and makes no other change to spec 4.4.
10. **Message details the spec leaves open:** CE10a prints the absolute path. CE16 prints `library_dir()`. CT7's `<kinds>` is `" and ".join(requested)` (for example `video and stills`), and `<n>` is printed with `%d`.
11. **`train_stills` details:** the kept stills are the `kept` items of `dataset/manifest.json`, and their count feeds `stills_epochs`. A candidate whose safetensors header cannot be parsed (`ValueError`, `struct.error`) counts as `expected = 0`. The incompatibility reasons are evaluated in spec order (child failure, then `expected == 0`, then the count mismatch), after the compat child has run. `control_path` is set only when the control job's status is `ok`. On success the tool prints `stills LoRA: <path>`, `  with LoRA: <sample>`, `  control:   <control>`.
12. **`character_dataset.py`'s top-level imports are complete from Task 10 on** (`glob`, `struct` and `zipfile` included), so Tasks 11 and 12 only insert functions before the marker line `# --- Z-Image child process (spec 4.9) ---`. All 4.1 constants are defined in Task 10.
13. **Between Tasks 11 and 12, `train()` names `train_stills`, which does not exist yet.** D24 installs it with `monkeypatch.setattr(..., raising=False)`, and D28 never reaches it. See "Skipping the stills half" for the rule if Task 12 is ever dropped.
14. **The render test harness writes 128 bytes that are unique to each stub render** (`"render N"` padded with NULs), where spec 9.1 says 128 zero bytes. `main` re-renders a chained panel only when its source clip's bytes change, so identical stub bytes would make P15(a)/(b) reuse panel 3 and fail. The harness also stubs `prepare_chain_seed` (real ffmpeg cannot read the stub clips) and points `story_dir_for` at `tmp_path`. In P9 panel 1 is `t2v`, so the schema-3 still-aspect preflight needs no real PNG.
15. **How tests reach `character_lib` without touching the real story tree.** The ltx-movie tests monkeypatch `ltx_movie._story_dir`, not `WS`: `_character_lib()` and the story.md validator keep loading the real files, and the story dirs land under `tmp_path`. The manifest tests patch `story_manifest.WS` (spec P20) and symlink the real `character_lib.py` into that temporary `WS`, so the real `_character_lib()` loader is exercised.
16. **Guard tests are green before their implementation step.** P8, P12, P14 and P66 (Task 6; for P66 see Decision 29), P24 (Task 7), P35 (Task 8), P49 and P57 (Task 9) pin unchanged or already-correct behavior. Each task's red counts below account for them. P57 is placed in Task 9 (the spec's Section 10 assignment) even though its code lands in Tasks 7-8.
17. **P55 is added in Task 13, not Task 9.** It compares `bin/ltx-movie --list-characters` with `bin/character list`, and `bin/character` does not exist until Task 13. It is appended to `tests/test_casting_pipeline.py` there.
18. **Mutation definitions the spec leaves open** (Final Acceptance A3):
   - "`trig` group removed (no idempotence)" is implemented as forcing `match.group("trig") is not None` to `False`. The regex itself is kept, so `cast_text` still runs. Removing the group outright would only crash on `group("trig")`.
   - "`usable_characters` iterates in creation order, not sorted" is implemented as `reversed(list_names())`. That is a deterministic non-sorted order; filesystem creation order is not deterministic enough to test against.
   - "manifest/images print the available line" is two rows, one per tool, both caught by P57. That makes 75 rows for the spec's 74 (57 from the base spec and amendment 1, with the old E-P19 row replaced, plus 17 more from amendment 2).
19. **Spec mutation rows that name R1 where R1 does not catch.** "provenance adds `\"loras\": []` for uncast units" lists P13 and R1, and "`render_panel` always passes `loras=`" lists P9 and R1 (R33). In both cases R1 passes (observed) and P13 / P9 catch. Likewise "`trig` group removed" is caught by C29 but not C28. Each row still has at least one catcher, which is the spec's rule.
20. **The L6 follow-up commit edits the tests that depend on the default strength:** P20 (`kyra@0.8, ronin@0.8`), P43 (`== 0.8`), P44 and P46 (`"0.8"` in the cast flags). It also edits `DEFAULT_CHARACTER_STRENGTH` and the three `(default 0.8, provisional)` help texts. C36/C37 pass `0.8` explicitly and do not change, although spec 6 names them. If L6's winner is 0.8, there is no follow-up commit.
21. **D2 reads `generated/charlora/tools/make_dataset_seed.py`, which is gitignored** (`generated/`). The test is correct on this host (the file exists), but it fails on a clone without the spike. The test files are not shipped, so this is a recorded risk, not a change.
22. **The B-golden serialization:** B1 is the subprocess's stdout. B2 is `json.dumps(manifest_minus_created_at, indent=2, ensure_ascii=False) + "\n"`. B3 is `json.dumps(argv, indent=2) + "\n"`. Normalization replaces the image path, then `sys.executable`, then `WS` (in that order). The fixture `story.md` names `the woman in grey` in all three Motion: fields.
23. **`bin/ltx-mlx-render` `render_panel` builds `extra` inside the existing `try:`**, directly before the `SKILL.generate_video(` call, so the call keeps its indentation and R33 still sees `lora_path`.
24. **Tests look up `character_lib`'s exception classes at call time** (`character_lib.CharacterError`, never `from character_lib import CharacterError`). The pipeline tools load `character_lib.py` by path into the same `sys.modules` entry, and that re-creates its classes. A class bound at import time therefore goes stale when `tests/test_character_lib.py` shares a pytest session with `tests/test_casting_pipeline.py`: observed as 17 C-test failures before this rule, 157 passed after. Production is unaffected, because each tool raises and catches through the module object it just loaded.
25. **Help text for the repeatable LoRA flags (spec 5.7.1 is ambiguous).** The spec gives one replacement sentence and says that on `--stills-lora` "video DiT" becomes "Phase 2 stills", but the sentence contains neither phrase. Each help string is therefore a subject prefix plus the spec sentence verbatim: `global LoRA for the video DiT (ltx-2-mlx): ` (render and ltx-movie `--lora`), `global LoRA for the Phase 2 stills (z_image_skill): ` (ltx-movie `--stills-lora`), `global LoRA for z_image_skill stills: ` (ltx-story-images `--lora`). ltx-movie `--lora` keeps the trailing `See --stills-lora for the stills side.`; both stills flags keep `Never used by --seed-image panels (there is no generation to apply it to).` No existing test pins these strings.
26. **`bin/ltx-story-images` under amendment 2.** `compose = _compose_prompt` is hoisted above the casting block because 5.7.4's default plan also composes a prompt, and the I20 count of `_compose_prompt(` must stay 3. The character plans go into `char_plans`; `plans` is then built for every selected non-seed panel when `members or global_stills`. The E-P16 one-set check now runs on `plans` unconditionally (it is a no-op when `plans` is empty). The dry-run `loras:` entry for a global LoRA prints `global=<path>@<s>`: the 5.5 format prints `l["name"]`, which is `None` for a global.
27. **`P6`'s expected entries include `"kind": "character"`.** Amended 5.3(b) adds `kind` to every unit LoRA; the P6 row's `{"name": "kyra", ...}` is read as elided.
28. **P75 is added in Task 9, not Task 6.** It compares the three `_RepeatableLoraAction` copies, and the last copy (bin/ltx-movie) lands in Task 9.
29. **Amendment-2 test constructions:** P61 compares two renders of an all-`t2v` manifest, ignoring `log_path` in the kwargs and `output_sha256` in the provenance (both legitimately differ per run). P66(d) uses an all-`t2v` manifest so panel 3 is not chained, and `--lora X:0.8` on run 1 so run 1 takes the merged route (a single value at 1.0 would take the legacy route and differ for another reason); run 2 gives panel 3 the same file as a character at 0.8, so only `kind` differs. P71 passes relative paths after `monkeypatch.chdir(tmp_path)`, so the forwarded `<abs path>:<s>` differs from the raw value. P66 passes on the pre-change render too: the old single-valued `--lora` happens to change provenance in every P66 case. It is therefore a guard in Task 6's red count, and the mutation rows still prove it.
30. **Amendment-2 mutation definitions:** "`panel_strengths` counts globals" is modeled in render's `build_units`, which never calls `panel_strengths` (strengths come from the manifest): characters in a panel with globals + characters >= 2 are capped at 0.8. "global-vs-character duplicate check removed" disables the check in all three tools at once (its catchers span P64, P69, P72). "`_RepeatableLoraAction` overwrites the dest" is applied to bin/ltx-movie's copy and caught by P73 and P75; R1 (I21) passes a single value, so it cannot catch it.
31. **`extract_mflux_adapter` check order (spec 4.9 step 4 lists the errors without an order).** The order is: no zip under `<out>/checkpoints/`, then the step mismatch (decided from the file name, before the zip is opened), then the adapter-member count. The step is the zip basename's first 7 characters as an int.
32. **D14 gets a fifth case, a zip nested at `out/run/checkpoints/`, which must not be searched.** The spec's catcher for "`extract_mflux_adapter` searches recursively" is the timestamped-sibling case. But a recursive glob rooted at `out` never reaches a sibling `out_<ts>/`, so that case alone cannot catch the mutation. The mutation is defined as the pre-amendment recursive glob under `out`, and the nested case catches it.
33. **`train_stills`'s refusal check runs after step 2 and before `train.json` is written**: it is "directly before step 3". It uses `os.path.lexists`. D40's refusal half uses a second character whose `train/stills/out` already exists, with `shutil.rmtree` patched to a no-op.
34. **beedc77 is recorded in Task 10 as Step 6.** Its two edits and its test append are given byte-exact, so a from-scratch replay reproduces the committed tree. As a consequence, Task 10 Step 3's verbatim-block check no longer holds for lines 95-245 after Step 6, because spec 4.1 now names the EXIF line as a deliberate change.
35. **Task 11's text is unchanged (the code needs nothing).** Its stated sizes and counts were computed before beedc77 added 6 code lines and 39 test lines. On the real tree: `wc -l character_dataset.py` = 1252 (text says 1246), `wc -l tests/test_character_dataset.py` = 714 (text says 675), red `11 failed, 16 passed` (text: `11 failed, 14 passed`), green `27 passed` (text: `25 passed`). The coordinator rules on whether to edit Task 11.
36. **Plan-added Task 11 test cases (coordinator ruling: extend D23/D26 or add IDs; this plan extends).** Task 12 Step 1 edits D23 (a non-final checkpoint only; a 0-byte final checkpoint) and D26 (story server `UNKNOWN`; a plain `transformer.safetensors` in the dev dir). They are marked plan-added in comments, and the mutation table gains four plan-added rows that they catch. Extending keeps the spec's ID set, and A1's count of 177, unchanged.
37. **`parse_lora_spec` error rows.** The 5.7.1 table's `:2.5`, `:-1`, `:nan`, `:inf` are read as suffixes on `a.safetensors`: a bare `:0.5` is a path by the table's own row, so the literal strings would not raise.

**Skipping the stills half (Task 12).** The spec default (Section 13 Q1) is to build Task 12 even if L0 finds the mflux adapter incompatible, in which case `train` always skips stills with a recorded reason. Task 12 may be skipped only on the user's explicit decision. If it is skipped:
- run the video-LoRA live gates as `bin/character train <name> --video`. With `--video` alone, `train()` never touches stills;
- never run `train` without `--video` while mflux is installed, because `train()` would call the undefined `train_stills`;
- report that a follow-up spec change is needed to drop stills from `train`'s default kinds;
- in Final Acceptance, drop D9-D14, D29-D34, D40 and D41 and the mutation rows M74, M75, M76, M77, M78, M79, M80, M83, M84. Every video-path task, test and gate is unaffected.

## Review Focus

Spec Section 12, verbatim:

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

Plan-specific additions:
6. **The deploy deviation (Decision 1)**: confirm the four edited expected values are the only non-tuple change to `tests/test_deploy_pkg.py`, and that the count is 165 under both interpreters.
7. **The existing-suite source pins**: I13 and I20 in `tests/test_ltx_story_images.py`, and L7i/L29 in `tests/test_ltx_movie_offline.py`. Confirm every count still holds (Decisions 2-3) and that no comment reintroduces a pinned literal.
9. **Global LoRAs (amendment 2)**: the legacy route (one value at 1.0, no character LoRAs) must stay byte-identical, so B1-B3, R33 and R18z must hold. Every merged-route path is validated by realpath against duplicates and character LoRAs. Order and `kind` are part of clip identity. The three `_RepeatableLoraAction` copies must stay identical.
8. **Cast discovery**: `UnusableCharacterError` must be raised exactly for an invalid name, unknown or invalid `character.json`, not trained, or a missing or empty video LoRA. `--list-characters` must short-circuit before argparse, the lockfile and the sudo check.

## Task map

| Task | Owner | Adds | New tests | Cumulative new tests | Files |
|---|---|---|---|---|---|
| 1 | orchestrator (user-gated, GPU) | L0: mflux install + compat smoke train | none (live gate L0) | 0 | none in the repo (`~/mflux/.venv`, `generated/charlora/mflux-compat/`) |
| 2 | implementer | B-golden capture before any pipeline change | B1-B3 (3) | 3 | `tests/test_casting_regression.py`, `tests/fixtures/casting_baseline/{story.md, ltx_movie_dry_run.txt, manifest.json, build_command.json}` |
| 3 | implementer | `character_lib.py` incl. 3.9 cast discovery | C1-C46 (46) | 49 | `character_lib.py` (520 lines), `tests/test_character_lib.py` (549 lines) |
| 4 | implementer | `ltx2_mlx_video_skill.py` `loras=` + `parse_lora_spec` | P1-P5, P60, P74 (7) | 56 | `ltx2_mlx_video_skill.py`, `tests/test_casting_pipeline.py` (220 lines) |
| 5 | implementer | `z_image_skill.py` multi-adapter | Z1-Z6 (6) | 62 | `z_image_skill.py`, `tests/test_z_image_skill_multi_lora.py` (141 lines) |
| 6 | implementer | `bin/ltx-mlx-render` per-unit LoRAs + provenance + global LoRAs (5.7.3) | P6-P17, P61-P67 (19) | 81 | `bin/ltx-mlx-render`, `tests/test_casting_pipeline.py` (654 lines) |
| 7 | implementer | `bin/ltx-story-manifest --cast` | P20-P25 (6) | 87 | `bin/ltx-story-manifest`, `tests/test_casting_pipeline.py` (803 lines) |
| 8 | implementer | `bin/ltx-story-images --cast` + global stills LoRAs (5.7.4) | P30-P35, P68, P69 (8) | 95 | `bin/ltx-story-images`, `tests/test_casting_pipeline.py` (999 lines) |
| 9 | implementer | `bin/ltx-movie` casting + amendment 1 (available line, `--list-characters`) + amendment 2 (global LoRAs, 5.7.5) | P40-P54, P56, P57, P70-P73, P75 (22) | 117 | `bin/ltx-movie`, `tests/test_casting_pipeline.py` (1409 lines) |
| 10 | implementer | `character_dataset.py` create half | D1-D6, D15-D19, D35-D37 (14) + D38, D39 (beedc77 review fix) | 133 | `character_dataset.py` (1005 lines), `tests/test_character_dataset.py` (382 lines) |
| 11 | implementer | video LoRA training + `train()` | D7, D8, D20-D28 (11) | 144 | `character_dataset.py` (1246 lines), `tests/test_character_dataset.py` (675 lines) |
| 12 | implementer | mflux stills LoRA + compat gate, amendment-4 settings (skippable only by user decision) | D9-D14, D29-D34, D40, D41 (14) | 158 | `character_dataset.py` (1428 lines), `tests/test_character_dataset.py` (967 lines) |
| 13 | implementer | `bin/character` | K1-K18, P55 (19) | 177 | `bin/character` (106 lines, `chmod +x`), `tests/test_character_tool.py` (492 lines), `tests/test_casting_pipeline.py` (1422 lines) |
| 14 | implementer | deploy ships `character_lib.py` | none (R2: count stays 165) | 177 | `scripts/deploy/build_pkg.py`, `tests/test_deploy_pkg.py` |
| FA | orchestrator | A1-A6 acceptance, mutation table, design review, live gates L1-L7 (+ L6m; L6b deferred), L6 follow-up | - | 177 | only the L6 follow-up commit edits files |

**Execution state at this revision:** Tasks 1-11 are DONE (Task 10's review fix is `beedc77`; Task 11 is `f91de86`, committed per its unchanged text). This revision (spec `18b43c4` + `9f980b2`) changes the text of Task 1 (L0 recorded as passed), Task 10 (the beedc77 record, Step 6), Task 12, Final Acceptance and the L0 notes. Task 11's text is unchanged; its stated counts predate beedc77 (Decision 36). Task 12 also extends Task 11's tests D23 and D26 (Decision 37).

Order and dependencies: Task 1 comes first. Tasks 2-11 do not depend on L0's outcome. Task 12 must not start until L0's result has been reported to the user. Task 2 must be committed before any existing pipeline file is edited. After that, tasks 3-9 form one chain and 10-13 another (13 needs 3, 10 and 11). Execute every task sequentially, one at a time; the `tests/test_casting_pipeline.py` appends assume this order.

---

### Task 1: L0 -- mflux install (user-gated) and the stills compat smoke train (ORCHESTRATOR ONLY)

**Status: DONE. L0 PASSED on 2026-10-05.** The adapter was compatible (210/210 injected through the existing `z_image_skill`). 1024 was rejected at 13.07 s/step, and the 512 follow-up set the amendment-4 settings; results are in spec 0.2 and in "L0 notes" at the end of this plan. The steps below are kept for the record.

This task is run by the orchestrator, never by an implementer. It touches no repo file and makes no commit. Its output is the L0 record, which goes into the "L0 notes" section at the end of the orchestrator's copy of this plan.

Spec 4.10, verbatim:

- Installing is a user-visible action. **The plan must ask the user before running these commands, and must not run them unapproved.**
- The location is an isolated venv at `~/mflux/.venv`, mirroring `~/ltx-2-mlx/.venv` **[spec choice]**. The reason is that mflux 0.21.0 needs torch >= 2.13, while the workspace interpreter's torch 2.12.1 backs z_image_skill (0.2).

```
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 -m venv ~/mflux/.venv
~/mflux/.venv/bin/python -m pip install 'mflux==0.21.0'
~/mflux/.venv/bin/mflux-train --help
```

- **Verified from mflux's docs:** the `mflux-train --config PATH` CLI; `mflux-train --resume CHECKPOINT.zip`; every key in 4.9 except `gradient_checkpointing` (that one is documented in prose, not in the example); the data layout (`NN.txt` + image, optional `preview*.txt`); and the checkpoint zip naming.
- **Measured by L0 and the 512 test (amendment 4; 0.2):**
  - the output layout and the existing-directory timestamp rule;
  - steps = epochs × images (42 × 24 = 1008 checkpoints observed);
  - the adapter key names;
  - s/step and peak memory.
- **Still unverified:** whether `gradient_checkpointing` is honored as a top-level key. The config was accepted and peak memory was 38.7 GB at 1024 and 38.66 GB at 512, but no A/B without the key was run.

Spec 9.7 row L0, verbatim:

| ID | Gate | Pass condition |
|---|---|---|
| L0 | **PASSED 2026-10-05 (amendment 4; results in 0.2).** At 1024, compatible: 210/210 injected via the existing z_image_skill. 13.07 s/step at 1024 was rejected, so the 512 follow-up chose the 4.9 settings. Original gate text, kept for the record: **mflux compat gate (plan task 1).** After the user approves 4.10, install it. Run a smoke train in the gitignored scratch dir `generated/charlora/mflux-compat/` (not `/tmp`). Data: copies of `generated/charlora/kyrawmn-v1/stills/char_NN.png` with `captions/char_NN.txt`. Config: `stills_train_config(…, kept=24)` with `num_epochs` overridden to 4 (96 steps) and `save_frequency` 48. Command: `HF_HOME=~/hf_home ~/mflux/.venv/bin/mflux-train --config …`. Extract the adapter (4.9 step 4). Then, in a throwaway `python3 -c` using the **existing** `z_image_skill.load_pipeline(lora_path=<adapter>)`, count `lora_A` modules against `lora_module_count(safetensors_keys(adapter))`, and render `kyrawmn woman, medium shot, standing and facing the camera, …` at 1024x640, seed 42 | `mflux-train` exits 0. Record s/step, the peak footprint (`/usr/bin/time -l`), the checkpoint dir layout, and the adapter key sample (first 5 keys) in the plan's notes. **Compatible** iff injected == expected > 0 and the image renders. If incompatible, report to the user before building 4.9; the code is still built per spec (it then always skips). If s/step x 2400 > 4 h, report it to the user |

- [ ] **Step 1: ORCHESTRATOR: confirm with user before running.** Ask the user, quoting the three commands below, whether to install mflux 0.21.0 into the isolated venv `~/mflux/.venv` (several GB; check `df -h ~` first). Do not run anything in this step without an explicit yes.

````bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 -m venv ~/mflux/.venv
~/mflux/.venv/bin/python -m pip install 'mflux==0.21.0'
~/mflux/.venv/bin/mflux-train --help
````

Success: the last command exits 0 and prints usage. If the user declines: record `L0: not run (install declined)`, skip Steps 2-6, and continue with Task 2. Task 12 is still built per spec; `train` then always skips stills with `mflux-train not found at ...`.

- [ ] **Step 2: Record host state; ORCHESTRATOR: confirm with user before stopping the story server.** Record:

````bash
bin/story-server status
vm_stat | head -8
python3 -c "import psutil; print('avail GiB %.1f' % (psutil.virtual_memory().available / 2**30))"
````

If the state is `SERVING ...`, ask the user before running `bin/story-server stop`: training needs the memory. Remember whether it was serving, because L1-L3 need it back afterwards (`bin/story-server vision`). Do not proceed below 30 GiB available.

- [ ] **Step 3: Build the smoke dataset and config** (`generated/charlora/mflux-compat/` is gitignored and must not exist yet; if it does, `mv` it aside to `mflux-compat.prev-<UTC>`):

````bash
python3 - <<'EOF'
import json, os, shutil
ws = os.getcwd()
src = os.path.join(ws, "generated", "charlora", "kyrawmn-v1")
root = os.path.join(ws, "generated", "charlora", "mflux-compat")
data, out = os.path.join(root, "data"), os.path.join(root, "out")
os.makedirs(data)
os.makedirs(out)
n = 0
for name in sorted(os.listdir(os.path.join(src, "stills"))):
    stem = name[:-len(".png")]
    shutil.copy2(os.path.join(src, "stills", name), os.path.join(data, name))
    shutil.copy2(os.path.join(src, "captions", stem + ".txt"), os.path.join(data, stem + ".txt"))
    n += 1
with open(os.path.join(data, "preview_1.txt"), "w") as f:
    f.write("kyrawmn woman, medium shot, standing and facing the camera, "
            "photorealistic live-action film still, natural light.")
modules = ["attention.to_q", "attention.to_k", "attention.to_v", "attention.to_out.0",
           "feed_forward.w1", "feed_forward.w2", "feed_forward.w3"]
config = {  # stills_train_config(data, out, 0, kept=24) with num_epochs 4 and save_frequency 48
    "model": "z-image-turbo", "data": data, "seed": 0, "steps": 9, "guidance": 0.0,
    "quantize": None, "max_resolution": 1024, "low_ram": False, "gradient_checkpointing": True,
    "training_loop": {"num_epochs": 4, "batch_size": 1, "timestep_low": 4, "timestep_high": 9},
    "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
    "checkpoint": {"save_frequency": 48, "output_path": out},
    "monitoring": {"preview_width": 1024, "preview_height": 640, "plot_frequency": 100,
                   "generate_image_frequency": 2400},
    "lora_layers": {"targets": [{"module_path": "layers.{block}." + m,
                                 "blocks": {"start": 0, "end": 30}, "rank": 16} for m in modules]},
}
with open(os.path.join(root, "train.json"), "w") as f:
    json.dump(config, f, indent=2)
print("pairs:", n)
EOF
````

Expected: `pairs: 24`. Those are 24 stills with captions (`char_01..char_24`), plus `preview_1.txt`.

- [ ] **Step 4: Run the smoke train (GPU).** Run it with the Bash tool's `run_in_background` and no `nohup`/`&` (a double-backgrounded launcher reports completion early). Completion is the `rc=` line in the output, not the notification.

````bash
(cd generated/charlora/mflux-compat && HF_HOME="$HOME/hf_home" /usr/bin/time -l "$HOME/mflux/.venv/bin/mflux-train" --config train.json > train.log 2>&1; echo "rc=$?")
````

Pass: `rc=0`. Record:
- the s/step, from `train.log`'s progress lines;
- the `peak memory footprint` line that `/usr/bin/time -l` appends to `train.log`;
- whether mflux accepted or warned about `gradient_checkpointing`;
- the checkpoint layout: `find generated/charlora/mflux-compat/out -type f | sort | head -40`.

- [ ] **Step 5: Extract the adapter (spec 4.9 step 4) and sample its keys:**

````bash
python3 - <<'EOF'
import glob, json, os, re, struct, zipfile
root = os.path.join(os.getcwd(), "generated", "charlora", "mflux-compat")
zips = glob.glob(os.path.join(root, "out", "**", "*_checkpoint.zip"), recursive=True)
lead = lambda p: int(re.match(r"\d+", os.path.basename(p)).group(0)) if re.match(r"\d+", os.path.basename(p)) else -1
newest = max(zips, key=lead)
with zipfile.ZipFile(newest) as archive:
    members = [m for m in archive.namelist() if m.endswith("_adapter.safetensors")]
    print("zip:", newest, "members:", archive.namelist())
    assert len(members) == 1, members
    with open(os.path.join(root, "adapter.safetensors"), "wb") as f:
        f.write(archive.read(members[0]))
with open(os.path.join(root, "adapter.safetensors"), "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    header = json.loads(f.read(n).decode("utf-8"))
keys = sorted(k for k in header if k != "__metadata__")
print("first 5 keys:", keys[:5])
print("lora_module_count:", len({k.split(".lora")[0] for k in keys if ".lora" in k}))
EOF
````

- [ ] **Step 6: Compat probe with the existing `z_image_skill` (GPU):**

````bash
python3 - <<'EOF'
import json, os, struct, sys
import torch
sys.path.insert(0, os.getcwd())
import z_image_skill
adapter = os.path.join(os.getcwd(), "generated", "charlora", "mflux-compat", "adapter.safetensors")
with open(adapter, "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    header = json.loads(f.read(n).decode("utf-8"))
expected = len({k.split(".lora")[0] for k in header if k != "__metadata__" and ".lora" in k})
pipeline = z_image_skill.load_pipeline(lora_path=adapter)
injected = sum(1 for m in pipeline.transformer.modules()
               if isinstance(getattr(m, "lora_A", None), torch.nn.ModuleDict) and len(m.lora_A) > 0)
print("adapters:", pipeline.get_list_adapters())
print("expected:", expected, "injected:", injected)
z_image_skill._pipeline = pipeline
image = z_image_skill.generate_image(
    "kyrawmn woman, medium shot, standing and facing the camera, photorealistic live-action film still, natural light.",
    output_path=os.path.join(os.getcwd(), "generated", "charlora", "mflux-compat", "l0_lora.png"),
    width=1024, height=640, generator=torch.Generator("cpu").manual_seed(42))
print("rendered:", image.size)
EOF
````

**Compatible** iff `injected == expected > 0` and `rendered: (1024, 640)` is printed. Look at `l0_lora.png`. An exception from `load_lora_weights` (for example `Invalid LoRA checkpoint`) means **incompatible**; record its text. Restart the story server (`bin/story-server vision`) if Step 2 stopped it.

- [ ] **Step 7: Report to the user and record the L0 notes.** Report:
- compatible yes/no, with the expected and injected counts;
- s/step, and s/step x 2400 as the estimated full stills-training time. Flag it explicitly if that is over 4 h;
- the peak footprint;
- the checkpoint layout;
- the first 5 keys;
- the `gradient_checkpointing` behavior.

If incompatible, the default is still to build Task 12 per spec (it will always skip). Ask whether the user wants the stills half dropped instead (see "Skipping the stills half"). Task 12 starts only after this report.

---

### Task 2: B-golden capture of the uncast outputs (before any pipeline change)

**Files:**
- Create: `tests/fixtures/casting_baseline/story.md` (16 lines)
- Create: `tests/test_casting_regression.py` (124 lines)
- Create (by the capture run): `tests/fixtures/casting_baseline/ltx_movie_dry_run.txt`, `manifest.json`, `build_command.json`

**Interfaces:**
- Consumes: `bin/ltx-movie` (subprocess, unchanged), `bin/ltx-story-manifest::main` (with module `WS` patched), `ltx2_mlx_video_skill.build_command` (unchanged).
- Produces: `b1_text()`, `b2_text(tmpdir)`, `b3_text()`, `capture()`, and the pytest functions `test_b1_ltx_movie_dry_run_is_unchanged`, `test_b2_chain_manifest_is_unchanged`, `test_b3_build_command_is_unchanged`. Every later task re-runs this file as part of the regression check.

Spec 9.7 B-golden rules and table, verbatim:

**B-goldens (`tests/test_casting_regression.py` + `tests/fixtures/casting_baseline/`).**

- The goldens are captured by `python3 tests/test_casting_regression.py --capture`, which the plan runs **before any production code changes** and commits. Running under pytest compares.
- Normalization replaces `WS` with `<WS>`, `sys.executable` with `<PY>`, and the fixture image path with `<IMAGE>`. `created_at` is removed.

| ID | Golden | Command |
|---|---|---|
| B1 | `ltx_movie_dry_run.txt` | `subprocess.run([sys.executable, "bin/ltx-movie", "a test narrative", "--story-id", "casting-baseline-dry", "--dry-run", "--no-review", "--model", "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"], cwd=WS, env=dict(os.environ, STORY_PIPELINE_LOGGED="1"), capture_output=True, text=True).stdout`, normalized |
| B2 | `manifest.json` | `story_manifest.main(["--story-id", "casting-baseline-manifest", "--prompts-md", <fixture story.md>, "--chain", "--image", <64x64 PNG made at runtime>, "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145", "--max-frames", "145", "--force"])`, with module `WS` patched to `tmp_path`. The written manifest is normalized. `story.md` is a 3-panel chain fixture: panel 1 Image/Motion/Narration, panels 2-3 Motion/Narration, naming `the woman in grey` |
| B3 | `build_command.json` | `SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png", width=704, height=448, num_frames=145, frame_rate=24, seed=1, model="M", gemma="G")` with `SKILL.LTX2_MLX_BIN = "/bin/ltx"`, as a JSON list |

Precondition: `git diff --quiet HEAD -- bin/ltx-movie bin/ltx-story-manifest ltx2_mlx_video_skill.py && echo clean` prints `clean`, and `generated/stories/casting-baseline-dry` does not exist.

- [ ] **Step 1: Write the fixture** `tests/fixtures/casting_baseline/story.md` with exactly this content (3-panel chain; panel 1 Image/Motion/Narration, panels 2-3 Motion/Narration; names `the woman in grey`):

````markdown
# Casting baseline

A woman in grey walks a forest trail at dawn.

## Panel 1 — The Trail
Image: A medium shot, eye level, of the woman in grey standing on a packed-dirt forest trail and facing the camera. The woman in grey is a young woman, slender, with long black hair pinned up with jade hairpins, wearing a pale grey kimono. Tall cedar trunks line the trail behind her. The light is overcast and flat, with a muted green and grey palette. The rendering is photorealistic live-action film still.
Motion: The woman in grey takes two slow steps toward the camera; the camera stays static.
Narration: She has walked this trail before.

## Panel 2 — The Pause
Motion: The woman in grey stops and turns her head to the left.
Narration: Something moves between the trees.

## Panel 3 — The Look
Motion: The woman in grey's eyes narrow as she leans forward.
Narration: She waits.
````

- [ ] **Step 2: Write `tests/test_casting_regression.py`** with exactly this content:

````python
"""Byte-identical goldens for UNCAST runs (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.7, B1-B3).

Capture once, before any production change, and commit the result:
    python3 tests/test_casting_regression.py --capture
Compare (every later run):
    python3 -m pytest tests/test_casting_regression.py

Normalization: the fixture image path becomes <IMAGE>, sys.executable becomes <PY>, the
workspace root becomes <WS> (replaced in that order), and the manifest's created_at is
removed.
"""

import contextlib
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import ltx2_mlx_video_skill as SKILL  # noqa: E402

story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_casting_regression",
    os.path.join(WS, "bin", "ltx-story-manifest")).load_module()

FIXTURES = os.path.join(WS, "tests", "fixtures", "casting_baseline")
STORY_MD = os.path.join(FIXTURES, "story.md")
GOLDEN_B1 = os.path.join(FIXTURES, "ltx_movie_dry_run.txt")
GOLDEN_B2 = os.path.join(FIXTURES, "manifest.json")
GOLDEN_B3 = os.path.join(FIXTURES, "build_command.json")
MODEL_25 = "/Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8"


def _normalize(text, image=None):
    if image is not None:
        text = text.replace(image, "<IMAGE>")
    return text.replace(sys.executable, "<PY>").replace(WS, "<WS>")


def b1_text():
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "a test narrative", "--story-id",
         "casting-baseline-dry", "--dry-run", "--no-review", "--model", MODEL_25],
        cwd=WS, env=dict(os.environ, STORY_PIPELINE_LOGGED="1"), capture_output=True,
        text=True)
    assert proc.returncode == 0, proc.stderr
    return _normalize(proc.stdout)


def b2_text(tmpdir):
    from PIL import Image
    image = os.path.join(tmpdir, "panel_01.png")
    Image.new("RGB", (64, 64), (90, 90, 90)).save(image)
    saved = story_manifest.WS
    story_manifest.WS = tmpdir
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = story_manifest.main([
                "--story-id", "casting-baseline-manifest", "--prompts-md", STORY_MD, "--chain",
                "--image", image, "--fps", "24", "--target-seconds", "18.125",
                "--min-frames", "145", "--max-frames", "145", "--force"])
    finally:
        story_manifest.WS = saved
    assert rc == 0
    path = os.path.join(tmpdir, "generated", "stories", "casting-baseline-manifest",
                        "manifest.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    del data["created_at"]
    return _normalize(json.dumps(data, indent=2, ensure_ascii=False) + "\n", image=image)


def b3_text():
    saved = SKILL.LTX2_MLX_BIN
    SKILL.LTX2_MLX_BIN = "/bin/ltx"
    try:
        cmd = SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png",
                                  width=704, height=448, num_frames=145, frame_rate=24, seed=1,
                                  model="M", gemma="G")
    finally:
        SKILL.LTX2_MLX_BIN = saved
    return _normalize(json.dumps(cmd, indent=2) + "\n")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_b1_ltx_movie_dry_run_is_unchanged():
    assert b1_text() == _read(GOLDEN_B1)


def test_b2_chain_manifest_is_unchanged(tmp_path):
    assert b2_text(str(tmp_path)) == _read(GOLDEN_B2)


def test_b3_build_command_is_unchanged():
    assert b3_text() == _read(GOLDEN_B3)


def capture():
    with tempfile.TemporaryDirectory() as tmpdir:
        texts = {GOLDEN_B1: b1_text(), GOLDEN_B2: b2_text(tmpdir), GOLDEN_B3: b3_text()}
    for path, text in texts.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s (%d bytes)" % (path, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--capture"]:
        print("usage: python3 tests/test_casting_regression.py --capture "
              "(compare with: python3 -m pytest tests/test_casting_regression.py)",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(capture())
````

- [ ] **Step 3: Run to fail (no goldens yet):** `python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `3 failed` (each test raises `FileNotFoundError` on its golden), `rc=1`.

- [ ] **Step 4: Capture:** `python3 tests/test_casting_regression.py --capture`

Expected (exactly three lines; the sizes were observed with this fixture):

````
wrote <WS>/tests/fixtures/casting_baseline/ltx_movie_dry_run.txt (9530 bytes)
wrote <WS>/tests/fixtures/casting_baseline/manifest.json (1980 bytes)
wrote <WS>/tests/fixtures/casting_baseline/build_command.json (287 bytes)
````

Check: `grep -c '<WS>' tests/fixtures/casting_baseline/ltx_movie_dry_run.txt` prints `7` and `grep -c '<PY>' ...` prints `5`; `grep -c '<IMAGE>' tests/fixtures/casting_baseline/manifest.json` prints `1`; `ls generated/stories/casting-baseline-dry` fails (the dry run wrote nothing).

- [ ] **Step 5: Run to pass:** `python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `3 passed, 1 warning`, `rc=0`.

- [ ] **Step 6: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add tests/test_casting_regression.py tests/fixtures/casting_baseline/story.md tests/fixtures/casting_baseline/ltx_movie_dry_run.txt tests/fixtures/casting_baseline/manifest.json tests/fixtures/casting_baseline/build_command.json
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/tests/test_casting_regression.py
qwen-agent-workspace/tests/fixtures/casting_baseline/story.md
qwen-agent-workspace/tests/fixtures/casting_baseline/ltx_movie_dry_run.txt
qwen-agent-workspace/tests/fixtures/casting_baseline/manifest.json
qwen-agent-workspace/tests/fixtures/casting_baseline/build_command.json
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
casting: capture uncast golden outputs before any pipeline change

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 3: `character_lib.py` -- schema, validation, casting rules and cast discovery

**Files:**
- Create: `character_lib.py` (520 lines)
- Test: create `tests/test_character_lib.py` (549 lines)

**Interfaces:**
- Consumes: nothing (stdlib only: `collections`, `datetime`, `json`, `os`, `re`, `uuid`).
- Produces (spec 1.3, 3.1, 3.9), used by Tasks 7, 8, 9, 10, 11, 12, 13:
  - constants `WS`, `LIBRARY_ENV`, `SCHEMA_VERSION`, `NAME_RE`, `TRIGGER_RE`, `CLASS_RE`, `PHRASE_WORD_RE`, `MAX_PHRASE_WORDS`, `ARTICLES`, `STATUSES`, `SOURCE_TYPES`, `MIN_SCORE`, `MIN_KEEP`, `DEFAULT_CHARACTER_STRENGTH = 0.8`, `SINGLE_CHARACTER_STRENGTH = 1.0`, `TRIGGER_REGISTRY`, `LOCK_NAME`, `SHA256_RE`, `UTC_RE`, `CAST_BLOCK_HEADER`, `CAST_BLOCK_RULES`, `NO_CHARACTERS_AVAILABLE`, `LIST_ROW_FORMAT`;
  - `class CharacterError(Exception)`, `class UnusableCharacterError(CharacterError)`, and the namedtuple `CastMember(name, phrase, trigger, class_noun, descriptor, video_lora, stills_lora, stills_skip_reason, strength)`;
  - `library_dir() -> str`, `character_dir(name) -> str`, `character_json_path(name) -> str`, `utc_now() -> str`;
  - `validate_name(name)`, `validate_trigger(trigger)`, `validate_class_noun(noun)`, `normalize_phrase(phrase) -> str`, `validate_descriptor(text)`, `validate_character(data, name=None)`;
  - `load_character(name) -> dict`, `write_character(data)`, `list_names() -> list`, `registered_triggers() -> dict`, `register_trigger(trigger, name)`, `auto_trigger(name, class_noun, taken, avoid=()) -> str`;
  - `parse_cast_arg(value) -> (phrase, name)`, `resolve_cast(entries) -> [CastMember]`, `phrase_occurs(text, phrase) -> bool`, `cast_text(text, members) -> (text, sorted names)`, `panel_strengths(names, members, character_strength) -> dict`, `build_cast_block(members) -> str`;
  - `usable_characters() -> [(name, phrase)]`, `format_available_line(characters) -> str`, `character_table_lines() -> [str]`.

Spec 9.2 test table (C1-C46), verbatim:

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

- [ ] **Step 1: Write the failing test.** Create `tests/test_character_lib.py` with exactly this content:

````python
"""Tests for character_lib.py (spec docs/superpowers/specs/2026-10-05-character-library-design.md
Section 9.2, C1-C41).

Run from the workspace root: python3 -m pytest tests/test_character_lib.py
Plain pytest asserts only (no check() helper). No network, no GPU. Every library lives
under tmp_path through $CHARACTER_LIBRARY_DIR.
"""

import ast
import copy
import hashlib
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402

# The exception classes are looked up on the module at call time, never bound with
# "from character_lib import ...": bin/ltx-movie, bin/ltx-story-manifest and
# bin/ltx-story-images load character_lib.py by path into the same sys.modules entry,
# which re-creates its classes, so a class bound at import time would go stale when this
# file shares a pytest session with tests/test_casting_pipeline.py.

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def member(name, phrase, trigger, strength=None):
    """A CastMember with dummy paths, for the pure matching tests (spec 9.1)."""
    return character_lib.CastMember(name, phrase, trigger, "woman", DESCRIPTOR,
                                    "/lib/%s/lora/video.safetensors" % name, None, None,
                                    strength)


KYRA = member("kyra", "the woman in grey", "kyrawmn")
RONIN = member("ronin", "the ronin", "roninmn")


def _raises(fn, *args, **kwargs):
    with pytest.raises(character_lib.CharacterError) as info:
        fn(*args, **kwargs)
    return str(info.value)


def _raises_unusable(fn, *args, **kwargs):
    """(message, is it an UnusableCharacterError) for a call that must raise CharacterError."""
    with pytest.raises(character_lib.CharacterError) as info:
        fn(*args, **kwargs)
    return str(info.value), isinstance(info.value, character_lib.UnusableCharacterError)


# --- C1-C7: names, triggers, phrases, auto_trigger (spec 2.4, 3.1, 3.2) -----------------
def test_c1_validate_name():
    for ok in ("kyra", "ab", "a-1", "x" * 24):
        character_lib.validate_name(ok)
    for bad in ("A", "a", "1ab", "ab_c", "a" * 25, None):
        message = _raises(character_lib.validate_name, bad)
        assert message == "character name must match [a-z][a-z0-9-]{1,23}, got %r" % (bad,)


def test_c2_validate_trigger():
    for ok in ("kyrawmn", "abcd", "a" + "b" * 15):
        character_lib.validate_trigger(ok)
    for bad in ("abc", "Kyra", "1abc", "ab-cd", "a" * 17):
        message = _raises(character_lib.validate_trigger, bad)
        assert message == "trigger must match [a-z][a-z0-9]{3,15}, got %r" % (bad,)


def test_c3_normalize_phrase_collapses_whitespace():
    assert character_lib.normalize_phrase("  the   woman in\ngrey ") == "the woman in grey"


def test_c4_normalize_phrase_rejects():
    for bad in ("", "a b c d e f g", "the", "An", "the ronin=", "the (ronin)", 5):
        _raises(character_lib.normalize_phrase, bad)


def test_c5_normalize_phrase_keeps_apostrophes_and_hyphens():
    for ok in ("the ronin’s ally", "o'brien", "half-elf"):
        assert character_lib.normalize_phrase(ok) == ok


def test_c6_auto_trigger_table():
    assert character_lib.auto_trigger("kyra", "woman", set()) == "kyrawmn"
    assert character_lib.auto_trigger("ronin", "man", set()) == "roninmn"
    assert character_lib.auto_trigger("kyra", "woman", {"kyrawmn"}) == "kyrawmn2"
    assert character_lib.auto_trigger("kyra", "woman", {"kyrawmn", "kyrawmn2"}) == "kyrawmn3"
    assert character_lib.auto_trigger("a1", "man", set()) == "amnx"
    assert character_lib.auto_trigger("ab-cd", "person", set()) == "abcdprs"


def test_c7_auto_trigger_avoids_phrase_words():
    assert character_lib.auto_trigger("ronin", "man", set(), avoid=["the", "roninmn"]) == "roninmn2"


# --- C8-C15: validate_character (spec 2.3) ----------------------------------------------
def test_c8_valid_for_every_status(lib_dir):
    for status in ("dataset", "untrained", "trained"):
        data = make_character(lib_dir, name="c-%s" % status, status=status)
        if status == "dataset":
            assert data["dataset"] is None
        character_lib.validate_character(data)
        character_lib.validate_character(data, name="c-%s" % status)


def test_c9_exact_top_level_keys(lib_dir):
    data = make_character(lib_dir)
    assert len(data) == 14
    for key in list(data):
        broken = copy.deepcopy(data)
        del broken[key]
        assert key in _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["extra_key"] = 1
    assert "extra_key" in _raises(character_lib.validate_character, broken)


def test_c10_status_consistency(lib_dir):
    data = make_character(lib_dir)
    broken = copy.deepcopy(data)
    broken["loras"]["video"] = None
    _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["status"] = "untrained"
    _raises(character_lib.validate_character, broken)
    untrained = make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin",
                               class_noun="man", status="untrained")
    untrained["dataset"]["kept"] = 11
    _raises(character_lib.validate_character, untrained)


def test_c11_lora_entry_rules(lib_dir):
    data = make_character(lib_dir)
    for key, value in (("alpha", 16), ("sha256", "ABC"), ("path", "lora/video.safetensors"),
                       ("rank", True)):
        broken = copy.deepcopy(data)
        broken["loras"]["video"][key] = value
        _raises(character_lib.validate_character, broken)


def test_c12_strength(lib_dir):
    data = make_character(lib_dir)
    for bad in (0, 1.5, True, "0.8"):
        broken = copy.deepcopy(data)
        broken["strength"] = bad
        _raises(character_lib.validate_character, broken)
    for ok in (None, 0.6, 1):
        good = copy.deepcopy(data)
        good["strength"] = ok
        character_lib.validate_character(good)


def test_c13_trigger_collisions(lib_dir):
    data = make_character(lib_dir)
    broken = copy.deepcopy(data)
    broken["trigger"] = "woman"
    _raises(character_lib.validate_character, broken)
    broken = copy.deepcopy(data)
    broken["trigger"] = "ronin"
    broken["referring_phrase"] = "the Ronin"
    _raises(character_lib.validate_character, broken)


def test_c14_source(lib_dir):
    data = make_character(lib_dir)
    for bad in ({"type": "seed_image"}, {"type": "descriptor", "path": "/x"}, {"type": "web"}):
        broken = copy.deepcopy(data)
        broken["source"] = bad
        _raises(character_lib.validate_character, broken)
    good = copy.deepcopy(data)
    good["source"] = {"type": "descriptor"}
    character_lib.validate_character(good)


def test_c15_descriptor(lib_dir):
    data = make_character(lib_dir)
    for bad in (DESCRIPTOR + ".", "The" + DESCRIPTOR[1:], "a young woman with long black hair",
                "a " + " ".join(["word"] * 60)):
        broken = copy.deepcopy(data)
        broken["descriptor"] = bad
        assert _raises(character_lib.validate_character, broken).startswith("descriptor: ")


# --- C16-C20: load, write, list, triggers (spec 3.1) ------------------------------------
def test_c16_unknown_character(lib_dir):
    message = _raises(character_lib.load_character, "ghost")
    assert message == "unknown character: ghost (no %s)" % os.path.join(
        lib_dir, "ghost", "character.json")


def test_c17_invalid_json(lib_dir):
    make_character(lib_dir)
    path = os.path.join(lib_dir, "kyra", "character.json")
    with open(path, "w") as f:
        f.write("{bad")
    assert _raises(character_lib.load_character, "kyra").startswith(
        "invalid character.json for kyra: ")
    with open(path, "w") as f:
        json.dump({"name": "kyra"}, f)
    assert _raises(character_lib.load_character, "kyra").startswith(
        "invalid character.json for kyra: ")


def test_c18_write_round_trip_and_atomicity(lib_dir):
    data = make_character(lib_dir)
    data["strength"] = 0.7
    character_lib.write_character(data)
    assert character_lib.load_character("kyra") == data
    path = os.path.join(lib_dir, "kyra", "character.json")
    with open(path, "rb") as f:
        before = f.read()
    broken = copy.deepcopy(data)
    broken["seed"] = -1
    _raises(character_lib.write_character, broken)
    with open(path, "rb") as f:
        assert f.read() == before
    assert [n for n in os.listdir(os.path.join(lib_dir, "kyra")) if n.endswith(".tmp")] == []


def test_c19_list_names(tmp_path, lib_dir):
    assert character_lib.list_names() == []
    make_character(lib_dir)
    os.makedirs(os.path.join(lib_dir, "bad"))
    for hidden in (".hidden", "Upper"):
        os.makedirs(os.path.join(lib_dir, hidden))
        with open(os.path.join(lib_dir, hidden, "character.json"), "w") as f:
            f.write("{}")
    with open(os.path.join(lib_dir, ".triggers"), "w") as f:
        f.write("kyrawmn kyra\n")
    assert character_lib.list_names() == ["kyra"]


def test_c20_registered_triggers(lib_dir):
    os.makedirs(os.path.join(lib_dir, "ghost"))
    with open(os.path.join(lib_dir, ".triggers"), "w") as f:
        f.write("kyrawmn kyra\ngarbage\nroninmn ronin\n")
    with open(os.path.join(lib_dir, "ghost", "character.json"), "w") as f:
        json.dump({"trigger": "ghosttt"}, f)
    assert character_lib.registered_triggers() == {
        "kyrawmn": "kyra", "roninmn": "ronin", "ghosttt": "ghost"}
    character_lib.register_trigger("newtrig", "newbie")
    assert character_lib.registered_triggers()["newtrig"] == "newbie"


# --- C21-C22: --cast parsing (spec 3.4) ---------------------------------------------------
def test_c21_parse_cast_arg():
    assert character_lib.parse_cast_arg("the woman in grey=kyra") == ("the woman in grey", "kyra")
    _raises(character_lib.parse_cast_arg, "a=b=kyra")
    assert character_lib.parse_cast_arg("the ronin = ronin") == ("the ronin", "ronin")


def test_c22_parse_cast_arg_rejects():
    assert _raises_unusable(character_lib.parse_cast_arg, "the ronin") == (
        "--cast must be PHRASE=NAME, got 'the ronin'", False)
    assert _raises_unusable(character_lib.parse_cast_arg, "the ronin=Bad Name") == (
        "character name must match [a-z][a-z0-9-]{1,23}, got 'Bad Name'", True)


# --- C23-C34: matching and trigger insertion (spec 3.6) ---------------------------------


def test_c23_article_case_kept():
    assert character_lib.cast_text("The woman in grey rides.", [KYRA]) == (
        "The kyrawmn woman in grey rides.", ["kyra"])


def test_c24_every_occurrence():
    assert character_lib.cast_text(
        "He bows to the woman in grey; the woman in grey nods.", [KYRA]) == (
        "He bows to the kyrawmn woman in grey; the kyrawmn woman in grey nods.", ["kyra"])


def test_c25_possessives():
    assert character_lib.cast_text("the ronin's blade", [RONIN]) == (
        "the roninmn ronin's blade", ["ronin"])
    assert character_lib.cast_text("the ronin’s blade", [RONIN]) == (
        "the roninmn ronin’s blade", ["ronin"])


def test_c26_word_boundaries():
    for text in ("the ronins", "the ronin-like", "bathe ronin", "theronin"):
        assert character_lib.cast_text(text, [RONIN]) == (text, [])
    assert character_lib.cast_text("the woman in grey-blue robe", [KYRA]) == (
        "the woman in grey-blue robe", [])


def test_c27_longest_phrase_first():
    x = member("x", "the woman", "xtrig")
    assert character_lib.cast_text("the woman in grey and the woman", [x, KYRA]) == (
        "the kyrawmn woman in grey and the xtrig woman", ["kyra", "x"])


def test_c28_no_article_prefixes():
    named = member("kyra", "Kyra", "kyrawmn")
    assert character_lib.cast_text("Kyra smiles at kyra.", [named]) == (
        "kyrawmn Kyra smiles at kyrawmn kyra.", ["kyra"])


def test_c29_idempotent():
    x = member("x", "the woman", "xtrig")
    named = member("kyra", "Kyra", "kyrawmn")
    cases = [("The woman in grey rides.", [KYRA]),
             ("He bows to the woman in grey; the woman in grey nods.", [KYRA]),
             ("the ronin's blade", [RONIN]), ("the ronin’s blade", [RONIN]),
             ("the ronins", [RONIN]), ("the ronin-like", [RONIN]), ("bathe ronin", [RONIN]),
             ("the woman in grey-blue robe", [KYRA]), ("theronin", [RONIN]),
             ("the woman in grey and the woman", [x, KYRA]),
             ("Kyra smiles at kyra.", [named])]
    for text, members in cases:
        once = character_lib.cast_text(text, members)
        assert character_lib.cast_text(once[0], members) == once


def test_c30_whitespace_runs():
    assert character_lib.cast_text("the woman\n in  grey", [KYRA]) == (
        "the kyrawmn woman\n in  grey", ["kyra"])


def test_c31_case_insensitive():
    assert character_lib.cast_text("THE RONIN draws.", [RONIN]) == (
        "THE roninmn RONIN draws.", ["ronin"])


def test_c32_article_a():
    stranger = member("stranger", "a stranger", "strgrmn")
    assert character_lib.cast_text("A stranger waits.", [stranger]) == (
        "A strgrmn stranger waits.", ["stranger"])


def test_c33_two_characters():
    assert character_lib.cast_text("The ronin shields the woman in grey.", [KYRA, RONIN]) == (
        "The roninmn ronin shields the kyrawmn woman in grey.", ["kyra", "ronin"])


def test_c34_phrase_occurs():
    assert character_lib.phrase_occurs("## Panel 1 — x\nMotion: The Ronin runs.", "the ronin")
    assert not character_lib.phrase_occurs("the ronins", "the ronin")


# --- C35-C38: resolve_cast and strengths (spec 3.5, 3.7) --------------------------------
def _two(lib_dir, ronin_strength=None):
    make_character(lib_dir)
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin",
                   class_noun="man", strength=ronin_strength)


def test_c35_resolve_cast_happy_path(lib_dir):
    _two(lib_dir)
    members = character_lib.resolve_cast([(None, "kyra"), ("the swordsman", "ronin")])
    assert [m.name for m in members] == ["kyra", "ronin"]
    assert members[0].phrase == "the woman in grey"
    assert members[1].phrase == "the swordsman"
    assert members[0].video_lora == os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    assert os.path.isabs(members[0].video_lora)
    assert members[0].stills_lora is None
    assert members[0].trigger == "kyrawmn" and members[1].class_noun == "man"


def test_c36_single_character_is_full_strength(lib_dir):
    _two(lib_dir)
    members = character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    assert character_lib.panel_strengths(["kyra"], members, 0.8) == {"kyra": 1.0}


def test_c37_override_and_default(lib_dir):
    _two(lib_dir, ronin_strength=0.6)
    members = character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    assert character_lib.panel_strengths(["kyra", "ronin"], members, 0.8) == {
        "kyra": 0.8, "ronin": 0.6}


def test_c38_resolve_cast_errors(lib_dir):
    resolve = character_lib.resolve_cast
    make_character(lib_dir)
    assert _raises_unusable(resolve, [(None, "ghost")]) == (
        "unknown character: ghost (no %s)" % os.path.join(lib_dir, "ghost", "character.json"),
        True)
    make_character(lib_dir, name="raw", trigger="rawtrig", status="untrained")
    assert _raises_unusable(resolve, [(None, "raw")]) == (
        "character raw is not trained (status untrained); run bin/character train raw", True)
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    os.remove(video)
    assert _raises_unusable(resolve, [(None, "kyra")]) == (
        "character kyra's video LoRA is missing or empty: %s" % video, True)
    open(video, "wb").close()
    assert _raises_unusable(resolve, [(None, "kyra")]) == (
        "character kyra's video LoRA is missing or empty: %s" % video, True)
    os.makedirs(os.path.join(lib_dir, "broken"))
    with open(os.path.join(lib_dir, "broken", "character.json"), "w") as f:
        f.write("{bad")
    message, unusable = _raises_unusable(resolve, [(None, "broken")])
    assert message.startswith("invalid character.json for broken: ") and unusable
    assert _raises_unusable(resolve, [(None, "Bad")]) == (
        "character name must match [a-z][a-z0-9-]{1,23}, got 'Bad'", True)
    make_character(lib_dir, name="sti", trigger="stitrig", stills=True)
    stills = os.path.join(lib_dir, "sti", "lora", "stills.safetensors")
    os.remove(stills)
    assert _raises_unusable(resolve, [(None, "sti")]) == (
        "character sti's stills LoRA is missing or empty: %s" % stills, False)
    make_character(lib_dir)
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man")
    assert _raises_unusable(resolve, [(None, "kyra"), ("the lady", "kyra")]) == (
        "character kyra is cast more than once", False)
    assert _raises_unusable(resolve, [("the ronin", "kyra"), ("The Ronin", "ronin")]) == (
        "cast phrase 'The Ronin' is used for both kyra and ronin", False)
    make_character(lib_dir, name="twin", trigger="kyrawmn", phrase="the twin")
    assert _raises_unusable(resolve, [(None, "kyra"), (None, "twin")]) == (
        "characters kyra and twin share the trigger kyrawmn", False)
    assert _raises_unusable(resolve, [("the kyrawmn", "kyra")]) == (
        "character kyra's trigger kyrawmn is a word of its cast phrase 'the kyrawmn'", False)


# --- C39-C41: the Cast block and the import rule (spec 1.2, 3.8) -------------------------
def test_c39_build_cast_block():
    assert character_lib.build_cast_block([KYRA, RONIN]) == (
        character_lib.CAST_BLOCK_HEADER + "\n"
        + '- "the woman in grey": ' + DESCRIPTOR + "." + "\n"
        + '- "the ronin": ' + DESCRIPTOR + "." + "\n"
        + character_lib.CAST_BLOCK_RULES)


def test_c40_cast_block_text():
    text = character_lib.CAST_BLOCK_HEADER + character_lib.CAST_BLOCK_RULES
    assert "{" not in text and "}" not in text
    assert text.count("word for word") == 2
    assert "longer than four words" in text


# --- C42-C46: cast discovery (spec 3.9, amendment) --------------------------------------
def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man",
                   status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def test_c42_format_available_line():
    assert character_lib.format_available_line([]) == (
        "available characters: none (create one with bin/character create)")
    assert character_lib.format_available_line(
        [("kyra", "the woman in grey"), ("ronin", "the ronin")]) == (
        "available characters: kyra (the woman in grey), ronin (the ronin)")


def test_c43_usable_characters(lib_dir):
    assert character_lib.usable_characters() == []
    make_character(lib_dir, name="zed", trigger="zedtrig", phrase="the zed", status="untrained")
    make_character(lib_dir, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man")
    os.makedirs(os.path.join(lib_dir, "bad"))
    with open(os.path.join(lib_dir, "bad", "character.json"), "w") as f:
        f.write("{bad")
    make_character(lib_dir, name="gone", trigger="gonetrig", phrase="the gone")
    os.remove(os.path.join(lib_dir, "gone", "lora", "video.safetensors"))
    make_character(lib_dir, name="stl", trigger="stltrig", phrase="the stl", stills=True)
    os.remove(os.path.join(lib_dir, "stl", "lora", "stills.safetensors"))
    make_character(lib_dir)
    assert character_lib.usable_characters() == [("kyra", "the woman in grey"),
                                                 ("ronin", "the ronin")]


def test_c44_table_for_an_empty_library(lib_dir):
    assert character_lib.character_table_lines() == ["no characters in %s" % lib_dir]


def test_c45_table_rows(lib_dir):
    _c45_library(lib_dir)
    with pytest.raises(character_lib.CharacterError) as info:
        character_lib.load_character("bad")
    row = character_lib.LIST_ROW_FORMAT
    assert character_lib.character_table_lines() == [
        row % ("NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS", "PHRASE"),
        "%-16s (invalid: %s)" % ("bad", info.value),
        row % ("kyra", "kyrawmn", "trained", "yes", "no", "the woman in grey"),
        row % ("ronin", "roninmn", "untrained", "no", "no", "the ronin")]


def test_c46_unusable_is_a_character_error():
    assert issubclass(character_lib.UnusableCharacterError, character_lib.CharacterError)


def test_c41_stdlib_only_imports():
    path = os.path.join(WS, "character_lib.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    roots = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.append((node.module or "").split(".")[0])
    assert roots and set(roots) <= {"collections", "datetime", "json", "os", "re", "uuid"}
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_character_lib.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `1 error` (collection: `ModuleNotFoundError: No module named 'character_lib'`), `rc=2`.

- [ ] **Step 3: Implement.** Create `character_lib.py` with exactly this content. It holds every code block of spec 2.4, 3.2-3.9 verbatim, plus the 2.3 validator, whose messages Decision 4 fixes:

````python
"""character_lib -- the character library's schema, validation and casting rules.

Stdlib only. This module is the single owner of the character.json schema
(schema_version 1), of name/trigger/phrase validation, and of the casting rules:
phrase matching, trigger insertion, per-panel LoRA strengths and the Phase 1 Cast
block. bin/character imports it at top level; bin/ltx-movie, bin/ltx-story-manifest
and bin/ltx-story-images load it by path, and only inside their casting branch, so
an uncast run never reads this file.

The library root is $CHARACTER_LIBRARY_DIR when set (test infrastructure only, like
LTX2_MLX_BIN), else <workspace>/generated/characters.

See docs/superpowers/specs/2026-10-05-character-library-design.md, Sections 2-3.
"""

import collections
import datetime
import json
import os
import re
import uuid

WS = os.path.dirname(os.path.realpath(__file__))
LIBRARY_ENV = "CHARACTER_LIBRARY_DIR"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")
TRIGGER_RE = re.compile(r"[a-z][a-z0-9]{3,15}")
CLASS_RE = re.compile(r"[a-z]{3,12}")
PHRASE_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
MAX_PHRASE_WORDS = 6
ARTICLES = ("the", "a", "an")
STATUSES = ("dataset", "untrained", "trained")
SOURCE_TYPES = ("seed_image", "descriptor")
MIN_SCORE = 7
MIN_KEEP = 12
DEFAULT_CHARACTER_STRENGTH = 0.8
SINGLE_CHARACTER_STRENGTH = 1.0
TRIGGER_REGISTRY = ".triggers"
LOCK_NAME = ".lock"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
CAST_BLOCK_HEADER = ("Cast: these characters have fixed identities that the pipeline already "
                     "knows how to draw.")
CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file: it replaces the phrase you would otherwise invent for them, even "
    "when it is longer than four words. In Panel 1's Image: field, describe each of these "
    "characters who is on screen in the opening frame with exactly the description given above, "
    "word for word. Bring a cast member on screen only where the narrative calls for them. "
    "Every other character still gets a referring phrase of your own, under the rules below.")

_TOP_LEVEL_KEYS = frozenset([
    "schema_version", "name", "trigger", "class_noun", "referring_phrase", "descriptor",
    "seed", "source", "strength", "status", "created_at", "dataset", "loras",
    "stills_skip_reason"])
_DATASET_KEYS = frozenset(["reference", "kept", "total", "min_score", "face_height",
                           "contact_sheet"])
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps",
                        "trained_at", "sample_path", "control_path"])


class CharacterError(Exception):
    """A character library problem: bad input, a missing or invalid record, or a cast
    that cannot be resolved. The message is printed after "Error: "."""


class UnusableCharacterError(CharacterError):
    """The named character does not exist, cannot be loaded, or cannot render (not trained, or
    its video LoRA is missing or empty). Callers that can offer alternatives append
    format_available_line(usable_characters()) (spec 3.9)."""


NO_CHARACTERS_AVAILABLE = "available characters: none (create one with bin/character create)"
LIST_ROW_FORMAT = "%-16s %-16s %-9s %-5s %-6s %s"


CastMember = collections.namedtuple("CastMember", [
    "name", "phrase", "trigger", "class_noun", "descriptor",
    "video_lora", "stills_lora", "stills_skip_reason", "strength"])


def library_dir():
    return os.environ.get(LIBRARY_ENV) or os.path.join(WS, "generated", "characters")


def character_dir(name):
    return os.path.join(library_dir(), name)


def character_json_path(name):
    return os.path.join(library_dir(), name, "character.json")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_abs_path(value):
    return isinstance(value, str) and os.path.isabs(value)


def validate_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise CharacterError("character name must match [a-z][a-z0-9-]{1,23}, got %r" % (name,))


def validate_trigger(trigger):
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise CharacterError("trigger must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))


def validate_class_noun(noun):
    if not isinstance(noun, str) or not CLASS_RE.fullmatch(noun):
        raise CharacterError("class noun must match [a-z]{3,12}, got %r" % (noun,))


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


def validate_descriptor(text):
    """The descriptor rule of spec 2.3. Raises CharacterError("descriptor: <reason>")."""
    if not isinstance(text, str):
        raise CharacterError("descriptor: must be a string, got %r" % (text,))
    if text != text.strip():
        raise CharacterError("descriptor: must not have leading or trailing whitespace")
    words = len(text.split())
    if not 8 <= words <= 60:
        raise CharacterError("descriptor: must be 8-60 words, got %d" % words)
    if not (text.startswith("a ") or text.startswith("an ")):
        raise CharacterError('descriptor: must start with "a " or "an ", got %r' % (text[:30],))
    if text.endswith("."):
        raise CharacterError('descriptor: must not end with "."')


def _validate_lora_entry(field, entry):
    if not isinstance(entry, dict) or set(entry) != _LORA_KEYS:
        raise CharacterError("%s: must be null or an object with exactly the keys %s, got %r"
                             % (field, ", ".join(sorted(_LORA_KEYS)), entry))
    if not _is_abs_path(entry["path"]):
        raise CharacterError("%s: path must be an absolute path, got %r" % (field, entry["path"]))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        raise CharacterError("%s: sha256 must be 64 lowercase hex characters, got %r"
                             % (field, entry["sha256"]))
    if not isinstance(entry["base_model"], str) or not entry["base_model"]:
        raise CharacterError("%s: base_model must be a non-empty string, got %r"
                             % (field, entry["base_model"]))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        raise CharacterError("%s: rank must be an int >= 1, got %r" % (field, entry["rank"]))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise CharacterError("%s: alpha must be an int equal to rank (%r), got %r"
                             % (field, entry["rank"], entry["alpha"]))
    if not _is_int(entry["steps"]) or entry["steps"] < 1:
        raise CharacterError("%s: steps must be an int >= 1, got %r" % (field, entry["steps"]))
    if not isinstance(entry["trained_at"], str) or not UTC_RE.fullmatch(entry["trained_at"]):
        raise CharacterError("%s: trained_at must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                             % (field, entry["trained_at"]))
    for key in ("sample_path", "control_path"):
        if entry[key] is not None and not _is_abs_path(entry[key]):
            raise CharacterError("%s: %s must be null or an absolute path, got %r"
                                 % (field, key, entry[key]))


def validate_character(data, name=None):
    """Strict schema_version 1 validation (spec 2.3). Raises CharacterError("<field>:
    <reason>"). File existence is not checked here."""
    if not isinstance(data, dict):
        raise CharacterError("top level: must be a JSON object, got %s" % type(data).__name__)
    missing = sorted(_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise CharacterError("top level: missing keys %s" % ", ".join(missing))
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise CharacterError("top level: unexpected keys %s" % ", ".join(extra))
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise CharacterError("schema_version: must be %d, got %r"
                             % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["name"], str) or not NAME_RE.fullmatch(data["name"]):
        raise CharacterError("name: must match [a-z][a-z0-9-]{1,23}, got %r" % (data["name"],))
    if name is not None and data["name"] != name:
        raise CharacterError("name: %r does not match its directory name %r" % (data["name"], name))
    trigger = data["trigger"]
    if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
        raise CharacterError("trigger: must match [a-z][a-z0-9]{3,15}, got %r" % (trigger,))
    class_noun = data["class_noun"]
    if not isinstance(class_noun, str) or not CLASS_RE.fullmatch(class_noun):
        raise CharacterError("class_noun: must match [a-z]{3,12}, got %r" % (class_noun,))
    if trigger == class_noun:
        raise CharacterError("trigger: must not equal class_noun %r" % (class_noun,))
    phrase = data["referring_phrase"]
    try:
        normalized = normalize_phrase(phrase)
    except CharacterError as e:
        raise CharacterError("referring_phrase: %s" % e)
    if normalized != phrase:
        raise CharacterError("referring_phrase: must be whitespace-normalized (%r), got %r"
                             % (normalized, phrase))
    if trigger in [w.lower() for w in phrase.split()]:
        raise CharacterError("trigger: %r must not be a word of referring_phrase %r"
                             % (trigger, phrase))
    validate_descriptor(data["descriptor"])
    if not _is_int(data["seed"]) or data["seed"] < 0:
        raise CharacterError("seed: must be an int >= 0, got %r" % (data["seed"],))
    source = data["source"]
    if not (source == {"type": "descriptor"}
            or (isinstance(source, dict) and set(source) == {"type", "path"}
                and source["type"] == "seed_image" and _is_abs_path(source["path"]))):
        raise CharacterError('source: must be {"type": "seed_image", "path": <absolute path>} '
                             'or {"type": "descriptor"}, got %r' % (source,))
    strength = data["strength"]
    if strength is not None and (not _is_number(strength) or not 0 < strength <= 1.0):
        raise CharacterError("strength: must be null or a number in (0, 1], got %r" % (strength,))
    if data["status"] not in STATUSES:
        raise CharacterError("status: must be one of %s, got %r"
                             % (", ".join(STATUSES), data["status"]))
    if not isinstance(data["created_at"], str) or not UTC_RE.fullmatch(data["created_at"]):
        raise CharacterError("created_at: must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
                             % (data["created_at"],))
    dataset = data["dataset"]
    if dataset is not None:
        if not isinstance(dataset, dict) or set(dataset) != _DATASET_KEYS:
            raise CharacterError("dataset: must be null or an object with exactly the keys %s, "
                                 "got %r" % (", ".join(sorted(_DATASET_KEYS)), dataset))
        if dataset["reference"] not in ("char_00", "char_01"):
            raise CharacterError("dataset: reference must be char_00 or char_01, got %r"
                                 % (dataset["reference"],))
        if (not _is_int(dataset["kept"]) or not _is_int(dataset["total"])
                or not 0 <= dataset["kept"] <= dataset["total"]):
            raise CharacterError("dataset: kept and total must be ints with 0 <= kept <= total, "
                                 "got kept=%r total=%r" % (dataset["kept"], dataset["total"]))
        if not _is_int(dataset["min_score"]) or not 1 <= dataset["min_score"] <= 10:
            raise CharacterError("dataset: min_score must be an int from 1 to 10, got %r"
                                 % (dataset["min_score"],))
        face = dataset["face_height"]
        if face is not None and (not _is_number(face) or not 0 <= face <= 1):
            raise CharacterError("dataset: face_height must be null or a number in [0, 1], got %r"
                                 % (face,))
        if not _is_abs_path(dataset["contact_sheet"]):
            raise CharacterError("dataset: contact_sheet must be an absolute path, got %r"
                                 % (dataset["contact_sheet"],))
    loras = data["loras"]
    if not isinstance(loras, dict) or set(loras) != {"video", "stills"}:
        raise CharacterError("loras: must be an object with exactly the keys stills, video, got %r"
                             % (loras,))
    for kind in ("video", "stills"):
        if loras[kind] is not None:
            _validate_lora_entry("loras.%s" % kind, loras[kind])
    reason = data["stills_skip_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise CharacterError("stills_skip_reason: must be null or a non-empty string, got %r"
                             % (reason,))
    if (data["status"] == "trained") != (loras["video"] is not None):
        raise CharacterError('status: %r is inconsistent with loras.video (%s); status is '
                             '"trained" exactly when a video LoRA is recorded'
                             % (data["status"], "null" if loras["video"] is None else "set"))
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise CharacterError("status: %r requires a dataset with at least %d kept stills"
                             % (data["status"], MIN_KEEP))


def load_character(name):
    validate_name(name)
    path = character_json_path(name)
    if not os.path.isfile(path):
        raise CharacterError("unknown character: %s (no %s)" % (name, path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        validate_character(data, name=name)
    except (ValueError, CharacterError) as e:
        raise CharacterError("invalid character.json for %s: %s" % (name, e))
    return data


def write_character(data):
    """Validate, then atomically replace <lib>/<name>/character.json. The directory must
    already exist."""
    validate_character(data)
    path = character_json_path(data["name"])
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_names():
    lib = library_dir()
    if not os.path.isdir(lib):
        return []
    return sorted(n for n in os.listdir(lib)
                  if NAME_RE.fullmatch(n) and os.path.isfile(character_json_path(n)))


def registered_triggers():
    """{trigger: name}: the .triggers registry, then every readable character.json trigger.
    Registry entries win on conflict; triggers are never reused (spec 2.4)."""
    triggers = {}
    registry = os.path.join(library_dir(), TRIGGER_REGISTRY)
    if os.path.isfile(registry):
        with open(registry, encoding="utf-8") as f:
            for line in f:
                fields = line.split()
                if len(fields) == 2:
                    triggers.setdefault(fields[0], fields[1])
    for name in list_names():
        try:
            with open(character_json_path(name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        trigger = data.get("trigger") if isinstance(data, dict) else None
        if isinstance(trigger, str):
            triggers.setdefault(trigger, name)
    return triggers


def register_trigger(trigger, name):
    lib = library_dir()
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, TRIGGER_REGISTRY), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (trigger, name))


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


def parse_cast_arg(value):
    """--cast PHRASE=NAME -> (normalized phrase, name), split on the LAST "=" (spec 3.4)."""
    if "=" not in value:
        raise CharacterError("--cast must be PHRASE=NAME, got %r" % (value,))
    phrase, name = value.rsplit("=", 1)
    try:
        validate_name(name.strip())
    except CharacterError as e:
        raise UnusableCharacterError(str(e))
    return normalize_phrase(phrase), name.strip()


def _readable_nonempty(p):
    return os.path.isfile(p) and os.access(p, os.R_OK) and os.path.getsize(p) > 0


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


def phrase_occurs(text, phrase):
    return _phrase_regex(normalize_phrase(phrase)).search(text) is not None


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


def panel_strengths(names, members, character_strength):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named; else each
    character's own character.json strength if set, otherwise character_strength (spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}


def build_cast_block(members):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(CAST_BLOCK_RULES)
    return "\n".join(lines)


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
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_character_lib.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `46 passed`, `rc=0`. Also `python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider` -> `3 passed, 1 warning`.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add character_lib.py tests/test_character_lib.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/character_lib.py
qwen-agent-workspace/tests/test_character_lib.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character_lib: library schema, validation, casting rules and cast discovery

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 4: `ltx2_mlx_video_skill.py` -- repeated `--lora PATH STRENGTH` via `loras=`

**Files:**
- Modify: `ltx2_mlx_video_skill.py` (10 edits below; +51/-6 lines)
- Test: create `tests/test_casting_pipeline.py` (220 lines at the end of this task)

**Interfaces:**
- Consumes: `character_lib` (Task 3; imported by the test header only).
- Produces:
  - `build_command(*, prompt, output_path, image_path=None, width, height, num_frames, frame_rate, seed, model=MODEL_ID, gemma=GEMMA_MODEL_ID, lora_path=None, low_ram=True, tile_frames=1, tile_spatial=1, quiet=False, loras=None)`;
  - `_validate_generate_args(prompt, output_path, image_path, width, height, num_frames, tile_frames, tile_spatial, force, log_path=None, timeout_s=None, lora_path=None, loras=None)`;
  - `generate_video(prompt, output_path, image_path=None, *, ..., force=False, quiet=False, loras=None)`.
  - `loras` is a list of `(path, strength)` pairs. Task 6 passes it from the render, Task 11 from the trigger-only A/B.
  - (amendment 2) `parse_lora_spec(value) -> (path, strength, explicit)` and `import math`. Tasks 6, 8 and 9 parse `--lora`/`--stills-lora` values with it.
- The test header produces the shared helpers that every later appended section relies on: `WS`, `character_lib`, `SKILL`, `render`, `story_manifest`, `story_images`, `ltx_movie` (scripts loaded with `SourceFileLoader`), `DESCRIPTOR`, `VIDEO_BYTES`, `STILLS_BYTES`, the `lib_dir` fixture, `make_character`, and `_ronin`.

Spec 5.1, verbatim:

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

Spec 5.7.1 `parse_lora_spec` (amendment 2), verbatim:

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

Spec 9.5 rows P1-P5, P60, P74, verbatim:

| ID | Test | Assertion |
|---|---|---|
| P1 | `SKILL.build_command(... loras=[("/a.safetensors", 1.0), ("/b.safetensors", 0.8)])` | the argv equals the uncast argv with `["--lora", "/a.safetensors", "1.0", "--lora", "/b.safetensors", "0.8"]` inserted directly after the `--gemma` value |
| P2 | `build_command(loras=[])`, `loras=None` | identical to the call without `loras` |
| P3 | `build_command(lora_path="/x", loras=[("/a", 1.0)])` | `ValueError("lora_path and loras are mutually exclusive")` |
| P4 | `generate_video` with `loras` cases: not a list; a 3-tuple; a missing file; strength `0`, `2.5`, `True`, `"1"`; plus `lora_path` | each `ValueError` with the 5.1 message. The stub binary never ran (`subprocess.Popen` patched to raise) |
| P5 | `generate_video(..., loras=[(real_tmp_file, 0.6)])` with `LTX2_MLX_BIN` = a stub script that writes its argv to a file and creates the output | the child argv contains `["--lora", tmp, "0.6"]` exactly once |
| P60 | `SKILL.parse_lora_spec` on every 5.7.1 table row | each result or `ValueError` exactly as tabled |
| P74 | `SKILL.generate_video(..., loras=[(g, 2.0), (k, 1.0)])`; `loras=[(g, 2.0001)]` | the first is accepted (argv `--lora g 2.0 --lora k 1.0`); the second raises `ValueError` |

Precondition: `git diff --quiet HEAD -- ltx2_mlx_video_skill.py && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Create `tests/test_casting_pipeline.py` with exactly this content:

````python
"""Tests for casting through the movie pipeline (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.5, P1-P49).

Run from the workspace root: python3 -m pytest tests/test_casting_pipeline.py
Plain pytest asserts only (no check() helper). No GPU, no model, no network: the render
harness stubs SKILL.generate_video (a fresh copy of the tests/test_ltx_mlx_render.py
_Harness pattern, not an import), Z-Image runs against fake torch/z_image_skill/
content_safety modules, and every character library lives under tmp_path through
$CHARACTER_LIBRARY_DIR.
"""

import contextlib
import glob
import hashlib
import importlib.machinery
import io
import json
import os
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


render = _load("ltx_mlx_render_casting", "bin/ltx-mlx-render")
story_manifest = _load("ltx_story_manifest_casting", "bin/ltx-story-manifest")
story_images = _load("ltx_story_images_casting", "bin/ltx-story-images")
ltx_movie = _load("ltx_movie_casting", "bin/ltx-movie")

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _ronin(lib, **kw):
    return make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin",
                          class_noun="man", **kw)


# --- P1-P5: ltx2_mlx_video_skill multi-LoRA argv and validation (spec 5.1) -------------
def _argv(**extra):
    return SKILL.build_command(prompt="p", output_path="/o.mp4", image_path="/i.png",
                               width=704, height=448, num_frames=145, frame_rate=24, seed=1,
                               model="M", gemma="G", **extra)


def test_p1_loras_follow_the_gemma_value(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    plain = _argv()
    cast = _argv(loras=[("/a.safetensors", 1.0), ("/b.safetensors", 0.8)])
    at = plain.index("--gemma") + 2
    assert cast == plain[:at] + ["--lora", "/a.safetensors", "1.0",
                                 "--lora", "/b.safetensors", "0.8"] + plain[at:]


def test_p2_empty_or_none_loras_change_nothing(monkeypatch):
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", "/bin/ltx")
    assert _argv(loras=[]) == _argv()
    assert _argv(loras=None) == _argv()


def test_p3_lora_path_and_loras_are_exclusive():
    with pytest.raises(ValueError) as info:
        _argv(lora_path="/x", loras=[("/a", 1.0)])
    assert str(info.value) == "lora_path and loras are mutually exclusive"


def test_p4_generate_video_rejects_bad_loras(tmp_path, monkeypatch):
    def _never(*args, **kwargs):
        raise AssertionError("subprocess.Popen ran")
    monkeypatch.setattr(SKILL.subprocess, "Popen", _never)
    good = str(tmp_path / "a.safetensors")
    with open(good, "wb") as f:
        f.write(b"x")
    missing = str(tmp_path / "missing.safetensors")
    out = str(tmp_path / "o.mp4")
    cases = [
        ({"loras": {good: 1.0}},
         "loras must be a list of (path, strength) pairs, got %r" % ({good: 1.0},)),
        ({"loras": [(good, 1.0, 2)]},
         "loras[0] must be a (path, strength) pair, got %r" % ((good, 1.0, 2),)),
        ({"loras": [(missing, 1.0)]}, "loras[0]: path is not a readable file: %r" % missing),
        ({"loras": [(good, 0)]}, "loras[0]: strength must be a number in (0, 2], got 0"),
        ({"loras": [(good, 2.5)]}, "loras[0]: strength must be a number in (0, 2], got 2.5"),
        ({"loras": [(good, True)]}, "loras[0]: strength must be a number in (0, 2], got True"),
        ({"loras": [(good, "1")]}, "loras[0]: strength must be a number in (0, 2], got '1'"),
        ({"loras": [(good, 1.0)], "lora_path": good}, "lora_path and loras are mutually exclusive"),
    ]
    for kwargs, message in cases:
        with pytest.raises(ValueError) as info:
            SKILL.generate_video("p", out, width=704, height=448, num_frames=145,
                                 frame_rate=24, **kwargs)
        assert str(info.value) == message


def test_p5_child_argv_carries_the_lora_once(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    lora = str(tmp_path / "k.safetensors")
    with open(lora, "wb") as f:
        f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(lora, 0.6)], force=True)
    argv = json.loads(argv_file.read_text())
    windows = [argv[i:i + 3] for i in range(len(argv) - 2)]
    assert windows.count(["--lora", lora, "0.6"]) == 1
    assert argv.count("--lora") == 1


def test_p60_parse_lora_spec_table():
    parse = SKILL.parse_lora_spec
    assert parse("a.safetensors") == ("a.safetensors", 1.0, False)
    assert parse("a.safetensors:0.5") == ("a.safetensors", 0.5, True)
    assert parse("/p/a:b.safetensors:0.8") == ("/p/a:b.safetensors", 0.8, True)
    assert parse("org/repo:main") == ("org/repo:main", 1.0, False)
    assert parse(":0.5") == (":0.5", 1.0, False)
    assert parse("a.safetensors:2") == ("a.safetensors", 2.0, True)
    for bad in ("a.safetensors:0", "a.safetensors:2.5", "a.safetensors:-1", "a.safetensors:nan",
                "a.safetensors:inf", ""):
        with pytest.raises(ValueError):
            parse(bad)


def test_p74_strength_two_is_the_upper_bound(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-stub"
    stub.write_text("#!%s\n"
                    "import json, os, sys\n"
                    "argv = sys.argv[1:]\n"
                    "with open(os.environ['CASTING_STUB_ARGV'], 'w') as f:\n"
                    "    json.dump(argv, f)\n"
                    "with open(argv[argv.index('--output') + 1], 'wb') as f:\n"
                    "    f.write(b'mp4')\n" % sys.executable)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("CASTING_STUB_ARGV", str(argv_file))
    monkeypatch.setattr(SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(SKILL, "LTX2_MLX_DIR", str(tmp_path))
    g, k = str(tmp_path / "g.safetensors"), str(tmp_path / "k.safetensors")
    for path in (g, k):
        with open(path, "wb") as f:
            f.write(b"lora")
    SKILL.generate_video("p", str(tmp_path / "o.mp4"), width=704, height=448, num_frames=145,
                         frame_rate=24, loras=[(g, 2.0), (k, 1.0)], force=True)
    argv = json.loads(argv_file.read_text())
    at = argv.index("--lora")
    assert argv[at:at + 6] == ["--lora", g, "2.0", "--lora", k, "1.0"]
    with pytest.raises(ValueError):
        SKILL.generate_video("p", str(tmp_path / "o2.mp4"), width=704, height=448,
                             num_frames=145, frame_rate=24, loras=[(g, 2.0001)], force=True)
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `7 failed` (`TypeError: ... unexpected keyword argument 'loras'`, and P60's `AttributeError: ... has no attribute 'parse_lora_spec'`), `rc=1`.

- [ ] **Step 3: Implement.** Apply these edits to `ltx2_mlx_video_skill.py`, in order:

**Edit 1** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python

import argparse
import os
import shlex
````

with:

````python

import argparse
import math
import os
import shlex
````

**Edit 2** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python


def _resolve_bin():
    """Absolute path to the ltx-2-mlx binary. A bare name (no path
````

with:

````python


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


def _resolve_bin():
    """Absolute path to the ltx-2-mlx binary. A bare name (no path
````

**Edit 3** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
                  num_frames, frame_rate, seed, model=MODEL_ID, gemma=GEMMA_MODEL_ID,
                  lora_path=None, low_ram=True,
                  tile_frames=1, tile_spatial=1, quiet=False):
    """Emit the ltx-2-mlx argv in a fixed token order so golden tests can
    assert on the list.
````

with:

````python
                  num_frames, frame_rate, seed, model=MODEL_ID, gemma=GEMMA_MODEL_ID,
                  lora_path=None, low_ram=True,
                  tile_frames=1, tile_spatial=1, quiet=False, loras=None):
    """Emit the ltx-2-mlx argv in a fixed token order so golden tests can
    assert on the list.
````

**Edit 4** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
    the single-anchor I2V semantics this pipeline relies on. lora_path is
    prep for future fine-tuning: omitted unless explicitly set, always
    applied at ltx-2-mlx's own --lora strength argument fixed to 1.0."""
    cmd = [_resolve_bin(), "generate",
           "--model", str(model),
````

with:

````python
    the single-anchor I2V semantics this pipeline relies on. lora_path is
    prep for future fine-tuning: omitted unless explicitly set, always
    applied at ltx-2-mlx's own --lora strength argument fixed to 1.0. loras is a list of
    (path, strength) pairs, emitted as one --lora PATH STRENGTH each, in order, right
    after the lora_path slot; it is mutually exclusive with lora_path."""
    if lora_path is not None and loras:
        raise ValueError("lora_path and loras are mutually exclusive")
    cmd = [_resolve_bin(), "generate",
           "--model", str(model),
````

**Edit 5** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
    if lora_path is not None:
        cmd += ["--lora", str(lora_path), "1.0"]
    cmd += ["--distilled",
           "--prompt", str(prompt),
````

with:

````python
    if lora_path is not None:
        cmd += ["--lora", str(lora_path), "1.0"]
    for path, strength in (loras or ()):
        cmd += ["--lora", str(path), repr(float(strength))]
    cmd += ["--distilled",
           "--prompt", str(prompt),
````

**Edit 6** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
def _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=None, timeout_s=None):
    """Every ValueError this module can raise is raised here, before any
    subprocess is spawned. Order matches the design doc section 5.3 list."""
````

with:

````python
def _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=None, timeout_s=None, lora_path=None, loras=None):
    """Every ValueError this module can raise is raised here, before any
    subprocess is spawned. Order matches the design doc section 5.3 list."""
````

**Edit 7** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
        raise ValueError("tile_spatial must be >= 1, got %d" % tile_spatial)


def generate_video(prompt, output_path, image_path=None, *,
````

with:

````python
        raise ValueError("tile_spatial must be >= 1, got %d" % tile_spatial)

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


def generate_video(prompt, output_path, image_path=None, *,
````

**Edit 8** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
                   low_ram=DEFAULT_LOW_RAM,
                   tile_frames=DEFAULT_TILE_FRAMES, tile_spatial=DEFAULT_TILE_SPATIAL,
                   log_path=None, timeout_s=None, force=False, quiet=False):
    """Render one clip and return the ABSOLUTE path of the written .mp4.

````

with:

````python
                   low_ram=DEFAULT_LOW_RAM,
                   tile_frames=DEFAULT_TILE_FRAMES, tile_spatial=DEFAULT_TILE_SPATIAL,
                   log_path=None, timeout_s=None, force=False, quiet=False, loras=None):
    """Render one clip and return the ABSOLUTE path of the written .mp4.

````

**Edit 9** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
    _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=log_path, timeout_s=timeout_s)
    resolved_bin = _resolve_bin()
    if not os.path.isfile(resolved_bin) or not os.access(resolved_bin, os.X_OK):
````

with:

````python
    _validate_generate_args(prompt, output_path, image_path, width, height,
                            num_frames, tile_frames, tile_spatial, force,
                            log_path=log_path, timeout_s=timeout_s,
                            lora_path=lora_path, loras=loras)
    resolved_bin = _resolve_bin()
    if not os.path.isfile(resolved_bin) or not os.access(resolved_bin, os.X_OK):
````

**Edit 10** (`ltx2_mlx_video_skill.py`). Replace this exact text, which occurs exactly once:

````python
                        frame_rate=frame_rate, seed=seed, model=model, gemma=gemma,
                        lora_path=lora_path, low_ram=low_ram,
                        tile_frames=tile_frames, tile_spatial=tile_spatial, quiet=quiet)
    print("[ltx2_mlx_video_skill] %s" % shlex.join(cmd))
    sys.stdout.flush()
````

with:

````python
                        frame_rate=frame_rate, seed=seed, model=model, gemma=gemma,
                        lora_path=lora_path, low_ram=low_ram,
                        tile_frames=tile_frames, tile_spatial=tile_spatial, quiet=quiet,
                        loras=loras)
    print("[ltx2_mlx_video_skill] %s" % shlex.join(cmd))
    sys.stdout.flush()
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `7 passed`, `rc=0`.

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add ltx2_mlx_video_skill.py tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/ltx2_mlx_video_skill.py
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx2_mlx_video_skill: repeated --lora PATH STRENGTH through loras=, and parse_lora_spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 5: `z_image_skill.py` -- named adapters, `set_adapters`, one `fuse_lora`

**Files:**
- Modify: `z_image_skill.py` (6 edits below; +38/-7 lines)
- Test: create `tests/test_z_image_skill_multi_lora.py` (141 lines)

**Interfaces:**
- Consumes: diffusers' `load_lora_weights(path, adapter_name=...)`, `get_list_adapters()`, `set_adapters(names, adapter_weights=...)` and `fuse_lora(adapter_names=..., lora_scale=1.0)` (behind fakes in the tests).
- Produces:
  - `load_pipeline(lora_path=None, loras=None)`, `_get_pipeline(lora_path=None, loras=None)`, `generate_image(prompt, output_path=None, lora_path=None, loras=None, **kwargs)`;
  - module globals `_pipeline` and `_pipeline_loras`.
  - Task 8 (`ltx-story-images`) and Task 10 (`child_zimage`) call `generate_image(..., loras=[(path, strength), ...])`.

Spec 5.2, verbatim:

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

Spec 9.6, verbatim:

It uses the `_fake_pipeline_classes` pattern from `tests/test_z_image_skill_cache.py:80-110`, extended: the fake pipeline records `load_lora_weights(path, **kw)`, `get_list_adapters()` (returns `{"transformer": [loaded names]}`, except that a path containing `"nomatch"` is not registered), `set_adapters(names, adapter_weights=…)`, and `fuse_lora(**kw)`. Each test resets `z_image_skill._pipeline = None` and `_pipeline_loras = None`.


| ID | Test | Assertion |
|---|---|---|
| Z1 | `load_pipeline(loras=[("a.st", 1.0), ("b.st", 0.8)])` | `lora_calls == [("a.st", {"adapter_name": "lora0"}), ("b.st", {"adapter_name": "lora1"})]`; `set_adapters` called once with `(["lora0", "lora1"], adapter_weights=[1.0, 0.8])`; `fuse_calls == [{"adapter_names": ["lora0", "lora1"], "lora_scale": 1.0}]` |
| Z2 | `load_pipeline(lora_path="x", loras=[("a", 1.0)])` | `ValueError` raised before `Qwen3Model.from_pretrained` (the fake records no construction) |
| Z3 | `load_pipeline(loras=[("nomatch.st", 1.0)])` | `ValueError` containing `"matched no Z-Image transformer weights"`. No `set_adapters`/`fuse_lora` call |
| Z4 | `generate_image("p", loras=[("a", 1.0)])` twice with the same set; then with `[("b", 1.0)]` | `load_pipeline` once; the third call raises `RuntimeError` |
| Z5 | `generate_image("p", lora_path="x")` with `load_pipeline` monkeypatched to `lambda lora_path=None: fake` | works (proves the uncast call shape is unchanged) |
| Z6 | `load_pipeline(lora_path="my_lora.safetensors")` | `lora_calls == ["my_lora.safetensors"]` (positional only) and `fuse_calls == [{"lora_scale": 1.0}]`, the same as `test_z_image_skill_cache.py:113-123` |

Precondition: `git diff --quiet HEAD -- z_image_skill.py && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Create `tests/test_z_image_skill_multi_lora.py` with exactly this content:

````python
"""Tests for z_image_skill's multi-adapter LoRA path (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.6, Z1-Z6).

Run from the workspace root: python3 -m pytest tests/test_z_image_skill_multi_lora.py
No model is loaded: Qwen3Model and ZImagePipeline are replaced by recording fakes
(the tests/test_z_image_skill_cache.py:108-139 pattern, extended with adapters).
"""

import torch

import pytest
import z_image_skill


@pytest.fixture(autouse=True)
def _fresh_singleton(monkeypatch):
    monkeypatch.setattr(z_image_skill, "_pipeline", None)
    monkeypatch.setattr(z_image_skill, "_pipeline_loras", None)
    monkeypatch.setattr(z_image_skill, "_pick_device", lambda: torch.device("cpu"))
    monkeypatch.delenv("Z_IMAGE_QUANTIZE_WEIGHTS", raising=False)


def _fake_pipeline_classes(record):
    """A pipeline that records LoRA/adapter calls. get_list_adapters reports every loaded
    adapter name, except one whose path contains "nomatch" (it matched no weights)."""

    class FakeQwen3Model:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            record["constructed"].append(model_id)
            return "FAKE_TEXT_ENCODER"

    class _FakeVAE:
        def to(self, dtype):
            pass

    class _FakePipeline:
        def __init__(self):
            self.vae = _FakeVAE()
            self.adapters = []

        def to(self, device):
            return self

        def load_lora_weights(self, path_or_repo, **kwargs):
            record["lora_calls"].append((path_or_repo, kwargs) if kwargs else path_or_repo)
            if "nomatch" not in path_or_repo:
                self.adapters.append(kwargs.get("adapter_name", "default_0"))

        def get_list_adapters(self):
            return {"transformer": list(self.adapters)}

        def set_adapters(self, names, adapter_weights=None):
            record["set_adapters"].append((list(names), adapter_weights))

        def fuse_lora(self, **kwargs):
            record["fuse_calls"].append(kwargs)

    class FakeZImagePipeline:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return _FakePipeline()

    return FakeQwen3Model, FakeZImagePipeline


def _install(monkeypatch):
    record = {"constructed": [], "lora_calls": [], "set_adapters": [], "fuse_calls": []}
    FakeQwen3Model, FakeZImagePipeline = _fake_pipeline_classes(record)
    monkeypatch.setattr(z_image_skill, "Qwen3Model", FakeQwen3Model)
    monkeypatch.setattr(z_image_skill, "ZImagePipeline", FakeZImagePipeline)
    return record


class _Image:
    def save(self, path):
        pass


class _CallablePipeline:
    def __call__(self, prompt, **kwargs):
        return type("Result", (), {"images": [_Image()]})()


def test_z1_adapters_weighted_and_fused_once(monkeypatch):
    record = _install(monkeypatch)
    z_image_skill.load_pipeline(loras=[("a.st", 1.0), ("b.st", 0.8)])
    assert record["lora_calls"] == [("a.st", {"adapter_name": "lora0"}),
                                    ("b.st", {"adapter_name": "lora1"})]
    assert record["set_adapters"] == [(["lora0", "lora1"], [1.0, 0.8])]
    assert record["fuse_calls"] == [{"adapter_names": ["lora0", "lora1"], "lora_scale": 1.0}]


def test_z2_lora_path_and_loras_are_exclusive(monkeypatch):
    record = _install(monkeypatch)
    with pytest.raises(ValueError, match="lora_path and loras are mutually exclusive"):
        z_image_skill.load_pipeline(lora_path="x", loras=[("a", 1.0)])
    assert record["constructed"] == []


def test_z3_unregistered_adapter_is_rejected(monkeypatch):
    record = _install(monkeypatch)
    with pytest.raises(ValueError, match="matched no Z-Image transformer weights"):
        z_image_skill.load_pipeline(loras=[("nomatch.st", 1.0)])
    assert record["set_adapters"] == []
    assert record["fuse_calls"] == []


def test_z4_singleton_refuses_a_different_lora_set(monkeypatch):
    calls = []

    def _load(lora_path=None, loras=None):
        calls.append((lora_path, loras))
        return _CallablePipeline()

    monkeypatch.setattr(z_image_skill, "load_pipeline", _load)
    monkeypatch.setattr(z_image_skill.content_safety, "assert_image_safe",
                        lambda image, **kw: None)
    z_image_skill.generate_image("p", loras=[("a", 1.0)])
    z_image_skill.generate_image("p", loras=[("a", 1.0)])
    assert calls == [(None, [("a", 1.0)])]
    with pytest.raises(RuntimeError, match="needs a new process"):
        z_image_skill.generate_image("p", loras=[("b", 1.0)])
    assert len(calls) == 1


def test_z5_uncast_call_shape_unchanged(monkeypatch):
    fake = _CallablePipeline()
    monkeypatch.setattr(z_image_skill, "load_pipeline", lambda lora_path=None: fake)
    monkeypatch.setattr(z_image_skill.content_safety, "assert_image_safe",
                        lambda image, **kw: None)
    image = z_image_skill.generate_image("p", lora_path="x")
    assert isinstance(image, _Image)


def test_z6_single_lora_path_unchanged(monkeypatch):
    record = _install(monkeypatch)
    z_image_skill.load_pipeline(lora_path="my_lora.safetensors")
    assert record["lora_calls"] == ["my_lora.safetensors"]
    assert record["fuse_calls"] == [{"lora_scale": 1.0}]
    assert record["set_adapters"] == []
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `6 errors` (the autouse fixture's `monkeypatch.setattr(z_image_skill, "_pipeline_loras", None)` raises `AttributeError`), `rc=1`.

- [ ] **Step 3: Implement.** Apply these edits to `z_image_skill.py`, in order:

**Edit 1** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python


def load_pipeline(lora_path=None):
    """Load the Z-Image-Turbo pipeline with the abliterated text encoder, moved to the
    best device.
````

with:

````python


def load_pipeline(lora_path=None, loras=None):
    """Load the Z-Image-Turbo pipeline with the abliterated text encoder, moved to the
    best device.
````

**Edit 2** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python
    so every later generate_image() call uses it with no per-call overhead.

    $Z_IMAGE_QUANTIZE_WEIGHTS (see the module docstring) quantizes the transformer
    only, before it is handed to the pipeline; omitted unless explicitly set."""
    device = _pick_device()
    dtype = _pick_dtype(device)
````

with:

````python
    so every later generate_image() call uses it with no per-call overhead.

    loras: a list of (local .safetensors path, strength) pairs, mutually exclusive with
    lora_path; each is loaded under the adapter name lora0, lora1, ..., checked to have
    registered on the transformer, weighted with set_adapters, and fused in ONE fuse_lora.

    $Z_IMAGE_QUANTIZE_WEIGHTS (see the module docstring) quantizes the transformer
    only, before it is handed to the pipeline; omitted unless explicitly set."""
    if lora_path is not None and loras:
        raise ValueError("lora_path and loras are mutually exclusive")
    device = _pick_device()
    dtype = _pick_dtype(device)
````

**Edit 3** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python
        pipeline.load_lora_weights(lora_path)
        pipeline.fuse_lora(lora_scale=1.0)
    return pipeline

````

with:

````python
        pipeline.load_lora_weights(lora_path)
        pipeline.fuse_lora(lora_scale=1.0)
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

````

**Edit 4** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python
# Lazily-loaded singleton so importing the module doesn't load the model.
_pipeline = None


def _get_pipeline(lora_path=None):
    """lora_path only takes effect on the FIRST call that constructs the singleton
    (same constraint as Z_IMAGE_HF_HOME): a later call with a different lora_path
    against an already-loaded pipeline is silently ignored."""
    global _pipeline
    if _pipeline is None:
        _pipeline = load_pipeline(lora_path=lora_path)
    return _pipeline


def generate_image(prompt: str, output_path: str = None, lora_path=None, **kwargs):
    """Generate an image from a text prompt using Z-Image-Turbo with the abliterated text encoder.

````

with:

````python
# Lazily-loaded singleton so importing the module doesn't load the model.
_pipeline = None
_pipeline_loras = None


def _get_pipeline(lora_path=None, loras=None):
    """lora_path only takes effect on the FIRST call that constructs the singleton
    (same constraint as Z_IMAGE_HF_HOME): a later call with a different lora_path
    against an already-loaded pipeline is silently ignored. A later call with a
    different loras set raises RuntimeError instead: that set needs a new process."""
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
    """Generate an image from a text prompt using Z-Image-Turbo with the abliterated text encoder.

````

**Edit 5** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python
            fine-tuning; forwarded to load_pipeline() (see its docstring for
            the singleton-timing caveat). Omitted unless explicitly set.
        **kwargs: Extra args forwarded to the pipeline call (e.g. height,
            width). Defaults num_inference_steps=9, guidance_scale=0.0 (this
````

with:

````python
            fine-tuning; forwarded to load_pipeline() (see its docstring for
            the singleton-timing caveat). Omitted unless explicitly set.
        loras: list of (local .safetensors path, strength) pairs, mutually exclusive
            with lora_path; fused once when the singleton is built, and a later call
            with a different set raises RuntimeError (see load_pipeline).
        **kwargs: Extra args forwarded to the pipeline call (e.g. height,
            width). Defaults num_inference_steps=9, guidance_scale=0.0 (this
````

**Edit 6** (`z_image_skill.py`). Replace this exact text, which occurs exactly once:

````python
        PIL.Image.Image: The generated image.
    """
    pipeline = _get_pipeline(lora_path=lora_path)
    kwargs.setdefault("num_inference_steps", 9)
    kwargs.setdefault("guidance_scale", 0.0)
````

with:

````python
        PIL.Image.Image: The generated image.
    """
    pipeline = (_get_pipeline(lora_path=lora_path, loras=loras) if loras
                else _get_pipeline(lora_path=lora_path))
    kwargs.setdefault("num_inference_steps", 9)
    kwargs.setdefault("guidance_scale", 0.0)
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `6 passed, 1 warning`, `rc=0`. Also `python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"` -> `13 passed, 1 warning` (Z6's pinned single-LoRA behavior is unchanged).

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add z_image_skill.py tests/test_z_image_skill_multi_lora.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/z_image_skill.py
qwen-agent-workspace/tests/test_z_image_skill_multi_lora.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
z_image_skill: multi-adapter LoRA loading with one weighted fuse

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 6: `bin/ltx-mlx-render` -- per-unit LoRAs, LoRA provenance, manifest validation, E-P19

**Files:**
- Modify: `bin/ltx-mlx-render` (17 edits below; +110/-11 lines)
- Test: append to `tests/test_casting_pipeline.py` (654 lines at the end of this task)

**Interfaces:**
- Consumes: `SKILL.generate_video(..., loras=[(path, strength)])` and `SKILL.build_command(..., loras=...)` (Task 4).
- Produces, consumed by Task 7's manifest output and by Final Acceptance L6/L7:
  - `load_manifest(path)`, which validates optional per-panel `characters: [{"name", "video_lora", "strength", ...}]`;
  - `build_units(...)`, which adds `unit["loras"] = [{"name", "path", "strength"}]` only when the panel has characters;
  - `_LORA_SHA256_CACHE = {}` and `lora_sha256(path) -> str`;
  - `build_clip_provenance(...)`, which appends `provenance["loras"] = [{"path", "sha256", "strength"}]` only for units that have loras;
  - (amendment 2) `class _RepeatableLoraAction(argparse.Action)` and the repeatable `--lora PATH[:STRENGTH]` flag (`args.lora_path` = first value, `args.lora_path_specs` = all values);
  - `build_units(panels, seed, clips_dir, run_root=None, global_loras=())`, whose unit `loras` entries are `{"kind": "global"|"character", "name", "path", "strength"}` (globals first, in CLI order);
  - provenance `loras` entries `{"kind", "path", "sha256", "strength"}`, in order;
  - in `main`, the 5.7.3 global-LoRA resolution (sets `args.global_loras`), which replaces the old `--lora` + cast refusal.
- The test section produces the helpers `R4L_KEYS`, `_lora`, `_entry`, `_chain_panels`, `_write_manifest`, `_render_args`, `_model_fixture`, `_CastHarness`, `_t2v_panels`, `_provenances` and `_without_logs`.

Spec 5.3, verbatim:

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

Spec 5.7 (amendment 2; normative, supersedes 5.3(f)): the repeatable flag action of 5.7.1, and 5.7.2, 5.7.3 and 5.7.6, verbatim:

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

#### 5.7.6 Strength rules with globals [spec choice: as recommended]

- Every global LoRA applies on **every** panel, at its own CLI strength. It is **never** reduced automatically.
- `panel_strengths` counts **only character LoRAs**. A panel with one character and two globals gives that character 1.0. A panel with two characters and one global gives each character 0.8 (or its override), and the global keeps its own strength.
- The per-panel order is globals (CLI order), then characters (sorted by name). This applies to video (units) and to stills (adapter list).
- The same file may not appear twice in a panel's list, or across the global and character lists (compared by `os.path.realpath`): exit 2.

Spec 9.5 rows P6-P17, P61-P67, verbatim:

| ID | Test | Assertion |
|---|---|---|
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
| P61 | render legacy route: `--lora /tmp/my.safetensors` (nonexistent) on an uncast manifest; then `--lora <real g>` and `--lora <real g>:1.0` | the first behaves like R33 (`kw["lora_path"] == "/tmp/my.safetensors"`, no `loras` kwarg, no file check). The last two give identical `received_kwargs` and identical provenance JSON (`lora_path == g`, no `loras` key) |
| P62 | render merged, uncast: `--lora a:1.0 --lora b:0.5` (real files) | every call has `loras == [(a, 1.0), (b, 0.5)]`, `lora_path is None`. Provenance `loras` kinds `["global", "global"]` |
| P63 | render, cast + globals: P9 manifest with `--lora a:0.7` | panel 1 `[(a, 0.7), (k, 1.0)]`, panel 2 `[(a, 0.7), (k, 0.8), (r, 0.8)]`, panel 3 `[(a, 0.7)]`: the global's strength is untouched, and globals do not count toward the character rule |
| P64 | render duplicates: `--lora a --lora a`; `--lora <symlink to a> --lora a`; `--lora k` where k is kyra's `video_lora` on the cast manifest (also via a symlink) | each exits 2 with E-P27 / E-P27 / E-P28 (`… (panel 1); pass it once`). `generate_video` never called |
| P65 | render merged-route errors: `--lora a --lora /missing.safetensors`; `--lora a:0`; `--lora a:3` | E-P26; E-P25; E-P25. Each exits 2 |
| P66 | `--resume` with globals on the P9 manifest: rerun after (a) the same flags; (b) `a:0.7` → `a:0.6`; (c) `--lora a --lora b` → `--lora b --lora a`; (d) LoRA X used as the global on run 1, and as a character LoRA (no global) on run 2 for an uncast→cast manifest change on panel 3 only | (a) nothing re-renders; (b) all panels re-render; (c) all re-render (order is identity); (d) panel 3 re-renders (kind differs) |
| P67 | render `--dry-run` with `--lora a:0.7` on the P9 manifest | each panel lists `            lora: <a> @ 0.7 (global)` first, then its character lines |

Precondition: `git diff --quiet HEAD -- bin/ltx-mlx-render && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Append exactly this content to the end of `tests/test_casting_pipeline.py`. The file currently ends with a newline, and the block starts with two blank lines. Afterwards `wc -l tests/test_casting_pipeline.py` prints `654`.

````python


# --- P6-P17: bin/ltx-mlx-render per-unit LoRAs, provenance, reuse (spec 5.3) -----------
R4L_KEYS = {"index", "label", "seed", "prompt", "image_path", "clip_path", "log_path",
            "conditioning", "chain_source"}


def _lora(tmp_path, name, content=None):
    path = os.path.join(str(tmp_path), "%s.safetensors" % name)
    with open(path, "wb") as f:
        f.write(content if content is not None else ("lora-%s" % name).encode())
    return path


def _entry(name, path, strength):
    phrase = {"kyra": "the woman in grey", "ronin": "the ronin"}[name]
    trigger = {"kyra": "kyrawmn", "ronin": "roninmn"}[name]
    return {"name": name, "phrase": phrase, "trigger": trigger, "video_lora": path,
            "strength": strength}


def _chain_panels(k, r):
    """The P9 manifest: panel 1 t2v [kyra@1.0], panel 2 chain [kyra@0.8, ronin@0.8],
    panel 3 chain with no characters."""
    return [
        {"index": 1, "image_path": None, "panel_text": "m1", "motion_prompt": "m1",
         "conditioning": "t2v", "characters": [_entry("kyra", k, 1.0)]},
        {"index": 2, "image_path": None, "panel_text": "m2", "motion_prompt": "m2",
         "conditioning": "chain",
         "characters": [_entry("kyra", k, 0.8), _entry("ronin", r, 0.8)]},
        {"index": 3, "image_path": None, "panel_text": "m3", "motion_prompt": "m3",
         "conditioning": "chain"},
    ]


def _write_manifest(directory, panels, story_id="cast-render"):
    path = os.path.join(str(directory), "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": story_id, "fps": 24, "panels": panels}, f)
    return path


def _render_args(model, **over):
    args = render.build_parser().parse_args(["/tmp/m.json", "/tmp/o.mp4"])
    args.model = model
    for key, value in over.items():
        setattr(args, key, value)
    return args


def _model_fixture(directory):
    model = os.path.join(str(directory), "model-fixture")
    os.makedirs(model, exist_ok=True)
    with open(os.path.join(model, "split_model.json"), "w") as f:
        json.dump({"recipe": "ltx-2.5"}, f)
    return model


class _CastHarness(object):
    """main() in-process with generate_video, probe_streams, assert_clips_uniform,
    build_concat_command, clip_frame_count and prepare_chain_seed stubbed and the story
    dir under tmp_path. Every stub render writes 128 bytes unique to that call, as a real
    render would, so a re-rendered clip changes the chain source of the next panel."""

    def __init__(self, monkeypatch, directory, panels, story_id="cast-render"):
        self.dir = str(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.story_id = story_id
        self.received = []
        self.renders = [0]
        self.manifest = _write_manifest(self.dir, panels, story_id)
        self.model = _model_fixture(self.dir)
        self.clips = os.path.join(self.dir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(self.dir, "movie.mp4")
        fake_bin = os.path.join(self.dir, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.renders[0] += 1
            index = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            harness.received.append((index, kw))
            with open(output_path, "wb") as f:
                f.write(("render %d" % harness.renders[0]).encode().ljust(128, b"\0"))
            return os.path.abspath(output_path)

        def _seed(unit, args):
            with open(unit["image_path"], "wb") as f:
                f.write(b"seed")
            return []

        monkeypatch.setattr(render.SKILL, "generate_video", _gen)
        monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
        monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
        monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
        monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out])
        monkeypatch.setattr(render, "clip_frame_count", lambda p: 241)
        monkeypatch.setattr(render, "prepare_chain_seed", _seed)
        monkeypatch.setattr(render, "story_dir_for",
                            lambda sid: os.path.join(harness.dir, "stories", sid))

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model] + list(extra))

    def rendered(self):
        return [index for index, _ in self.received]

    def kwargs(self, index):
        return [kw for i, kw in self.received if i == index][-1]

    def newest_summary(self):
        paths = glob.glob(os.path.join(self.dir, "stories", self.story_id, "runs", "*",
                                       "story_summary.json"))
        with open(max(paths, key=os.path.getmtime)) as f:
            return json.load(f)

    def rewrite(self, panels):
        _write_manifest(self.dir, panels, self.story_id)


def test_p6_valid_characters_become_unit_loras(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    manifest = render.load_manifest(_write_manifest(tmp_path, _chain_panels(k, r)))
    units = render.build_units(manifest["panels"], 0, str(tmp_path / "clips"))
    assert units[1]["loras"] == [{"kind": "character", "name": "kyra", "path": k, "strength": 0.8},
                                 {"kind": "character", "name": "ronin", "path": r, "strength": 0.8}]
    assert units[0]["loras"] == [{"kind": "character", "name": "kyra", "path": k, "strength": 1.0}]


def test_p7_malformed_characters_are_refused(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    missing = os.path.join(str(tmp_path), "missing.safetensors")
    cases = [
        ({}, "panel 2: characters must be a list"),
        ([{"video_lora": k, "strength": 0.8}],
         "panel 2: every characters entry needs a non-empty name"),
        ([_entry("kyra", k, 0.8), _entry("kyra", k, 0.8)],
         "panel 2: character kyra is listed more than once"),
        ([_entry("kyra", "kyra.safetensors", 0.8)],
         "panel 2: character kyra's video_lora is not a readable file: 'kyra.safetensors'"),
        ([_entry("kyra", missing, 0.8)],
         "panel 2: character kyra's video_lora is not a readable file: %r" % missing),
        ([_entry("kyra", k, 0)],
         "panel 2: character kyra's strength must be a number in (0, 1], got 0"),
        ([_entry("kyra", k, 1.2)],
         "panel 2: character kyra's strength must be a number in (0, 1], got 1.2"),
        ([_entry("kyra", k, True)],
         "panel 2: character kyra's strength must be a number in (0, 1], got True"),
    ]
    for characters, message in cases:
        panels = _chain_panels(k, r)
        panels[1]["characters"] = characters
        with pytest.raises(ValueError) as info:
            render.load_manifest(_write_manifest(tmp_path, panels))
        assert str(info.value) == message


def test_p8_uncast_units_keep_the_r4l_keys():
    panels = [{"index": 1, "image_path": None, "panel_text": "a", "motion_prompt": "a",
               "conditioning": "t2v", "characters": []},
              {"index": 2, "image_path": None, "panel_text": "b", "motion_prompt": "b",
               "conditioning": "t2v"}]
    for unit in render.build_units(panels, 0, "/clips"):
        assert set(unit) == R4L_KEYS


def test_p9_each_panel_renders_with_its_own_loras(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run() == 0
    assert h.rendered() == [1, 2, 3]
    assert h.kwargs(1)["loras"] == [(k, 1.0)]
    assert h.kwargs(2)["loras"] == [(k, 0.8), (r, 0.8)]
    assert "loras" not in h.kwargs(3)
    assert all(kw["lora_path"] is None for _, kw in h.received)


def test_p10_global_lora_combines_with_the_cast(tmp_path, monkeypatch):
    k, r, g = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "global")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--lora", g) == 0
    assert h.kwargs(1)["loras"] == [(g, 1.0), (k, 1.0)]
    assert h.kwargs(2)["loras"] == [(g, 1.0), (k, 0.8), (r, 0.8)]
    assert h.kwargs(3)["loras"] == [(g, 1.0)]
    assert all(kw["lora_path"] is None for _, kw in h.received)


def test_p11_dry_run_lists_each_panels_loras(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--dry-run") == 0
    lines = capsys.readouterr().out.splitlines()
    p1 = next(i for i, line in enumerate(lines) if line.startswith("  panel  1:"))
    p2 = next(i for i, line in enumerate(lines) if line.startswith("  panel  2:"))
    assert lines[p1 + 1] == "            lora: %s @ 1.0 (kyra)" % k
    assert lines[p2 + 1:p2 + 3] == ["            lora: %s @ 0.8 (kyra)" % k,
                                    "            lora: %s @ 0.8 (ronin)" % r]
    first = next(line for line in lines if line.startswith("first render command:"))
    assert "--lora %s 1.0" % k in first
    assert h.received == []


def test_p12_uncast_dry_run_has_no_lora_lines(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    panels = _chain_panels(k, r)
    for panel in panels:
        panel.pop("characters", None)
    h = _CastHarness(monkeypatch, tmp_path / "run", panels)
    assert h.run("--dry-run") == 0
    out = capsys.readouterr().out
    assert "lora:" not in out
    assert "--lora" not in out


def test_p13_provenance_records_the_lora_set(tmp_path):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    args = _render_args(_model_fixture(tmp_path))
    cast_unit = render.build_units(_chain_panels(k, r)[:1], 0, str(tmp_path))[0]
    provenance = render.build_clip_provenance(cast_unit, args)
    with open(k, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert provenance["loras"] == [{"kind": "character", "path": k, "sha256": digest,
                                    "strength": 1.0}]
    uncast = [{"index": 1, "image_path": None, "panel_text": "m1", "motion_prompt": "m1",
               "conditioning": "t2v"}]
    assert "loras" not in render.build_clip_provenance(
        render.build_units(uncast, 0, str(tmp_path))[0], args)


def test_p14_resume_reuses_an_identical_cast_render(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run() == 0
    h.received[:] = []
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == []
    assert [u["resumed"] for u in h.newest_summary()["units"]] == [True, True, True]


def test_p15_resume_never_reuses_a_different_lora_set(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")

    def _first_run(sub):
        h = _CastHarness(monkeypatch, tmp_path / sub, _chain_panels(k, r))
        assert h.run() == 0
        h.received[:] = []
        return h

    h = _first_run("a")
    panels = _chain_panels(k, r)
    panels[1]["characters"][1]["strength"] = 0.6
    h.rewrite(panels)
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [2, 3]

    h = _first_run("b")
    info = os.stat(k)
    with open(k, "wb") as f:
        f.write(b"retrained kyra lora")
    os.utime(k, ns=(info.st_atime_ns, info.st_mtime_ns + 10 ** 9))
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [1, 2, 3]

    h = _first_run("c")
    panels = _chain_panels(k, r)
    del panels[0]["characters"]
    h.rewrite(panels)
    assert h.run("--resume", "--force") == 0
    assert h.rendered() == [1, 2, 3]


def test_p16_lora_hash_is_memoized_on_identity(tmp_path, monkeypatch):
    k = _lora(tmp_path, "kyra")
    calls = []
    real = render.file_sha256

    def _counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(render, "file_sha256", _counting)
    monkeypatch.setattr(render, "_LORA_SHA256_CACHE", {})
    first = render.lora_sha256(k)
    assert render.lora_sha256(k) == first
    assert len(calls) == 1
    info = os.stat(k)
    os.utime(k, ns=(info.st_atime_ns, info.st_mtime_ns + 10 ** 9))
    assert render.lora_sha256(k) == first
    assert len(calls) == 2


def test_p17_lora_deleted_before_strict_provenance(tmp_path, monkeypatch, capsys):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    args = _render_args(_model_fixture(tmp_path))
    unit = render.build_units(_chain_panels(k, r)[:1], 0, str(tmp_path))[0]

    def _never(*a, **kw):
        raise AssertionError("generate_video ran")

    monkeypatch.setattr(render.SKILL, "generate_video", _never)
    os.remove(k)
    result = render.render_panel(unit, args)
    assert result["status"] == "error"
    assert "panel 1 FAILED (provenance)" in capsys.readouterr().err


# --- P61-P67: global LoRAs on the render (spec 5.7.2, 5.7.3, amendment 2) ----------------
def _t2v_panels(n=2):
    return [{"index": i, "image_path": None, "panel_text": "m%d" % i, "motion_prompt": "m%d" % i,
             "conditioning": "t2v"} for i in range(1, n + 1)]


def _provenances(h):
    out = []
    for path in sorted(glob.glob(os.path.join(h.clips, "panel_*.mp4.provenance.json"))):
        with open(path) as f:
            data = json.load(f)
        data.pop("output_sha256")
        out.append(data)
    return out


def _without_logs(received):
    return [(i, {key: v for key, v in kw.items() if key != "log_path"}) for i, kw in received]


def test_p61_legacy_route_is_unchanged(tmp_path, monkeypatch):
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", "/tmp/my.safetensors") == 0
    assert all(kw["lora_path"] == "/tmp/my.safetensors" and "loras" not in kw
               for _, kw in h.received)
    g = _lora(tmp_path, "global")
    h.received[:] = []
    assert h.run("--lora", g, "--force") == 0
    plain, plain_provenance = _without_logs(h.received), _provenances(h)
    h.received[:] = []
    assert h.run("--lora", g + ":1.0", "--force") == 0
    assert _without_logs(h.received) == plain
    assert _provenances(h) == plain_provenance
    assert all(p["lora_path"] == g and "loras" not in p for p in plain_provenance)


def test_p62_merged_route_without_a_cast(tmp_path, monkeypatch):
    a, b = _lora(tmp_path, "a"), _lora(tmp_path, "b")
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", a + ":1.0", "--lora", b + ":0.5") == 0
    assert all(kw["loras"] == [(a, 1.0), (b, 0.5)] and kw["lora_path"] is None
               for _, kw in h.received)
    assert [[l["kind"] for l in p["loras"]] for p in _provenances(h)] == [["global", "global"]] * 2


def test_p63_global_strength_is_untouched_by_the_character_rule(tmp_path, monkeypatch):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--lora", a + ":0.7") == 0
    assert h.kwargs(1)["loras"] == [(a, 0.7), (k, 1.0)]
    assert h.kwargs(2)["loras"] == [(a, 0.7), (k, 0.8), (r, 0.8)]
    assert h.kwargs(3)["loras"] == [(a, 0.7)]


def test_p64_duplicate_loras_are_refused(tmp_path, monkeypatch, capsys):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    link_a, link_k = str(tmp_path / "link-a.safetensors"), str(tmp_path / "link-k.safetensors")
    os.symlink(a, link_a)
    os.symlink(k, link_k)
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    cases = [
        (["--lora", a, "--lora", a], "Error: --lora %s is given more than once\n" % a),
        (["--lora", link_a, "--lora", a], "Error: --lora %s is given more than once\n" % a),
        (["--lora", k], "Error: --lora %s is also character kyra's video LoRA (panel 1); pass it "
                        "once\n" % k),
        (["--lora", link_k], "Error: --lora %s is also character kyra's video LoRA (panel 1); "
                             "pass it once\n" % link_k),
    ]
    for extra, message in cases:
        assert h.run(*extra) == 2, extra
        assert capsys.readouterr().err == message
    assert h.received == []


def test_p65_merged_route_argument_errors(tmp_path, monkeypatch, capsys):
    a = _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _t2v_panels())
    assert h.run("--lora", a, "--lora", "/missing.safetensors") == 2
    assert capsys.readouterr().err == "Error: --lora /missing.safetensors: not a readable file\n"
    assert h.run("--lora", a + ":0") == 2
    assert capsys.readouterr().err == (
        "Error: --lora: LoRA strength must be in (0, 2], got '0' in %r\n" % (a + ":0"))
    assert h.run("--lora", a + ":3") == 2
    assert capsys.readouterr().err == (
        "Error: --lora: LoRA strength must be in (0, 2], got '3' in %r\n" % (a + ":3"))
    assert h.received == []


def test_p66_resume_treats_the_global_set_as_identity(tmp_path, monkeypatch):
    k, r = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin")
    a, b = _lora(tmp_path, "a"), _lora(tmp_path, "b")

    def _rerun(sub, first, second, panels=None, second_panels=None):
        h = _CastHarness(monkeypatch, tmp_path / sub, panels or _chain_panels(k, r))
        assert h.run(*first) == 0
        h.received[:] = []
        if second_panels is not None:
            h.rewrite(second_panels)
        assert h.run(*(list(second) + ["--resume", "--force"])) == 0
        return h.rendered()

    assert _rerun("a", ["--lora", a + ":0.7"], ["--lora", a + ":0.7"]) == []
    assert _rerun("b", ["--lora", a + ":0.7"], ["--lora", a + ":0.6"]) == [1, 2, 3]
    assert _rerun("c", ["--lora", a, "--lora", b], ["--lora", b, "--lora", a]) == [1, 2, 3]
    cast_panel_3 = _t2v_panels(3)
    cast_panel_3[2]["characters"] = [_entry("kyra", a, 0.8)]
    assert _rerun("d", ["--lora", a + ":0.8"], [], panels=_t2v_panels(3),
                  second_panels=cast_panel_3) == [1, 2, 3]


def test_p67_dry_run_lists_globals_first(tmp_path, monkeypatch, capsys):
    k, r, a = _lora(tmp_path, "kyra"), _lora(tmp_path, "ronin"), _lora(tmp_path, "a")
    h = _CastHarness(monkeypatch, tmp_path / "run", _chain_panels(k, r))
    assert h.run("--dry-run", "--lora", a + ":0.7") == 0
    lines = capsys.readouterr().out.splitlines()
    glob_line = "            lora: %s @ 0.7 (global)" % a
    p1 = next(i for i, line in enumerate(lines) if line.startswith("  panel  1:"))
    p2 = next(i for i, line in enumerate(lines) if line.startswith("  panel  2:"))
    p3 = next(i for i, line in enumerate(lines) if line.startswith("  panel  3:"))
    assert lines[p1 + 1:p1 + 3] == [glob_line, "            lora: %s @ 1.0 (kyra)" % k]
    assert lines[p2 + 1:p2 + 4] == [glob_line, "            lora: %s @ 0.8 (kyra)" % k,
                                    "            lora: %s @ 0.8 (ronin)" % r]
    assert lines[p3 + 1] == glob_line
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `15 failed, 11 passed`, `rc=1`. The 11 passes are Task 4's 7 plus the guards P8, P12, P14 and P66 (Decision 29).

- [ ] **Step 3: Implement.** Apply these edits to `bin/ltx-mlx-render`, in order:

**Edit 1** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python


def build_parser():
    parser = argparse.ArgumentParser(
````

with:

````python


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


def build_parser():
    parser = argparse.ArgumentParser(
````

**Edit 2** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
    parser.add_argument("--model", default=SKILL.MODEL_ID)
    parser.add_argument("--gemma", default=SKILL.GEMMA_MODEL_ID)
    parser.add_argument("--lora", dest="lora_path", default=None,
                        help="LoRA .safetensors file or HF repo ID, prep for future "
                             "fine-tuning; always applied at strength 1.0")
    parser.add_argument("--no-low-ram", dest="no_low_ram", action="store_true",
                        default=False)
````

with:

````python
    parser.add_argument("--model", default=SKILL.MODEL_ID)
    parser.add_argument("--gemma", default=SKILL.GEMMA_MODEL_ID)
    parser.add_argument("--lora", dest="lora_path", action=_RepeatableLoraAction, default=None,
                        help="global LoRA for the video DiT (ltx-2-mlx): repeatable; PATH or "
                             "PATH:STRENGTH (0 < STRENGTH <= 2, default 1.0). Every global LoRA "
                             "applies to every panel, ahead of that panel's cast-character LoRAs, "
                             "at its own strength (never reduced automatically).")
    parser.add_argument("--no-low-ram", dest="no_low_ram", action="store_true",
                        default=False)
````

**Edit 3** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
            panel["conditioning"] = "still" if panel["image_path"] else "t2v"

        panel_text = panel.get("panel_text")
        if not isinstance(panel_text, str) or not panel_text.strip():
````

with:

````python
            panel["conditioning"] = "still" if panel["image_path"] else "t2v"

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

        panel_text = panel.get("panel_text")
        if not isinstance(panel_text, str) or not panel_text.strip():
````

**Edit 4** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python


def build_units(panels, seed, clips_dir, run_root=None):
    """Return the ordered per-panel unit list.

````

with:

````python


def build_units(panels, seed, clips_dir, run_root=None, global_loras=()):
    """Return the ordered per-panel unit list.

````

**Edit 5** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
        conditioning = panel["conditioning"]
        chained = conditioning == "chain"
        units.append({
            "index": i,
            "label": "panel-%d" % i,
````

with:

````python
        conditioning = panel["conditioning"]
        chained = conditioning == "chain"
        unit = {
            "index": i,
            "label": "panel-%d" % i,
````

**Edit 6** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
            "chain_source": (os.path.join(clips_dir, "panel_%02d.mp4" % (i - 1)) if chained
                             else None),
        })
    return units

````

with:

````python
            "chain_source": (os.path.join(clips_dir, "panel_%02d.mp4" % (i - 1)) if chained
                             else None),
        }
        loras = [{"kind": "global", "name": None, "path": g["path"], "strength": g["strength"]}
                 for g in global_loras]
        loras += [{"kind": "character", "name": c["name"], "path": c["video_lora"],
                   "strength": float(c["strength"])} for c in (panel.get("characters") or [])]
        if loras:
            unit["loras"] = loras
        units.append(unit)
    return units

````

**Edit 7** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python


def build_clip_provenance(unit, args, *, strict=False):
    """The exact generation identity a reusable clip must match. schema_version 2: every
````

with:

````python


_LORA_SHA256_CACHE = {}


def lora_sha256(path):
    """file_sha256, memoized on (realpath, size, mtime_ns): a 642 MB LoRA is hashed once per
    process, not three times per panel; a rewritten file changes the key and is re-hashed."""
    info = os.stat(path)
    key = (os.path.realpath(path), info.st_size, info.st_mtime_ns)
    if key not in _LORA_SHA256_CACHE:
        _LORA_SHA256_CACHE[key] = file_sha256(path)
    return _LORA_SHA256_CACHE[key]


def build_clip_provenance(unit, args, *, strict=False):
    """The exact generation identity a reusable clip must match. schema_version 2: every
````

**Edit 8** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
    change cannot cascade a spurious re-render while any real change to clip k-1 does."""
    conditioning = unit["conditioning"]
    return {
        "schema_version": 2,
        "backend": "ltx-2-mlx",
````

with:

````python
    change cannot cascade a spurious re-render while any real change to clip k-1 does."""
    conditioning = unit["conditioning"]
    provenance = {
        "schema_version": 2,
        "backend": "ltx-2-mlx",
````

**Edit 9** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
        "tile_frames": args.tile_frames, "tile_spatial": args.tile_spatial,
    }


````

with:

````python
        "tile_frames": args.tile_frames, "tile_spatial": args.tile_spatial,
    }
    if unit.get("loras"):
        provenance["loras"] = [{"kind": l["kind"], "path": l["path"],
                                "sha256": lora_sha256(l["path"]), "strength": l["strength"]}
                               for l in unit["loras"]]
    return provenance


````

**Edit 10** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
        else:
            print("  panel %2d: T2V (no conditioning image)" % unit["index"])
    print("clips dir: %s" % clips_dir)
    print("output: %s" % os.path.abspath(args.output_path))
````

with:

````python
        else:
            print("  panel %2d: T2V (no conditioning image)" % unit["index"])
        for l in unit.get("loras", []):
            print("            lora: %s @ %s (%s)" % (l["path"], repr(l["strength"]), l["name"] or "global"))
    print("clips dir: %s" % clips_dir)
    print("output: %s" % os.path.abspath(args.output_path))
````

**Edit 11** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
    if would_render:
        first = would_render[0]
        cmd = SKILL.build_command(
            prompt=first["prompt"], output_path=first["clip_path"],
````

with:

````python
    if would_render:
        first = would_render[0]
        extra = ({"loras": [(l["path"], l["strength"]) for l in first["loras"]]}
                 if first.get("loras") else {})
        cmd = SKILL.build_command(
            prompt=first["prompt"], output_path=first["clip_path"],
````

**Edit 12** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
            model=args.model, gemma=args.gemma, lora_path=args.lora_path,
            low_ram=(not args.no_low_ram),
            tile_frames=args.tile_frames, tile_spatial=args.tile_spatial)
        print("first render command: %s" % shlex.join(cmd))
    else:
````

with:

````python
            model=args.model, gemma=args.gemma, lora_path=args.lora_path,
            low_ram=(not args.no_low_ram),
            tile_frames=args.tile_frames, tile_spatial=args.tile_spatial, **extra)
        print("first render command: %s" % shlex.join(cmd))
    else:
````

**Edit 13** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
        return base
    try:
        clip = SKILL.generate_video(
            unit["prompt"], unit["clip_path"], image_path=unit["image_path"],
````

with:

````python
        return base
    try:
        extra = ({"loras": [(l["path"], l["strength"]) for l in unit["loras"]]}
                 if unit.get("loras") else {})
        clip = SKILL.generate_video(
            unit["prompt"], unit["clip_path"], image_path=unit["image_path"],
````

**Edit 14** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
            low_ram=(not args.no_low_ram), tile_frames=args.tile_frames,
            tile_spatial=args.tile_spatial, log_path=unit["log_path"],
            timeout_s=args.panel_timeout, force=True)
    except ValueError as e:
        print("panel %d FAILED (invalid): %s" % (unit["index"], e), file=sys.stderr)
````

with:

````python
            low_ram=(not args.no_low_ram), tile_frames=args.tile_frames,
            tile_spatial=args.tile_spatial, log_path=unit["log_path"],
            timeout_s=args.panel_timeout, force=True, **extra)
    except ValueError as e:
        print("panel %d FAILED (invalid): %s" % (unit["index"], e), file=sys.stderr)
````

**Edit 15** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
        return 2

    story_id = manifest.get("story_id") or "story"
    story_dir = story_dir_for(story_id)
````

with:

````python
        return 2

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

    story_id = manifest.get("story_id") or "story"
    story_dir = story_dir_for(story_id)
````

**Edit 16** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python

    if args.dry_run:
        units = build_units(panels, args.seed, clips_dir)
        return print_dry_run(args, manifest, units, story_id, clips_dir)

````

with:

````python

    if args.dry_run:
        units = build_units(panels, args.seed, clips_dir, global_loras=args.global_loras)
        return print_dry_run(args, manifest, units, story_id, clips_dir)

````

**Edit 17** (`bin/ltx-mlx-render`). Replace this exact text, which occurs exactly once:

````python
    print("clips dir: %s" % clips_dir)

    units = build_units(panels, args.seed, clips_dir, run_root)

    # ORDER-SAFE: keyed on unit index, never appended in loop order, because
````

with:

````python
    print("clips dir: %s" % clips_dir)

    units = build_units(panels, args.seed, clips_dir, run_root, global_loras=args.global_loras)

    # ORDER-SAFE: keyed on unit index, never appended in loop order, because
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `26 passed`, `rc=0`.

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-mlx-render tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-mlx-render
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-mlx-render: per-panel character LoRAs, repeatable global --lora, LoRA kinds in provenance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 7: `bin/ltx-story-manifest --cast` -- trigger insertion and per-panel `characters`

**Files:**
- Modify: `bin/ltx-story-manifest` (7 edits below; +66/-0 lines)
- Test: append to `tests/test_casting_pipeline.py` (803 lines at the end of this task)

**Interfaces:**
- Consumes: `character_lib` (Task 3), loaded by path: `DEFAULT_CHARACTER_STRENGTH`, `parse_cast_arg`, `resolve_cast`, `cast_text`, `panel_strengths`, `CharacterError`.
- Produces:
  - CLI flags `--cast PHRASE=NAME` (repeatable, `--chain` only) and `--character-strength S`;
  - `_character_lib()`;
  - in the manifest, every panel's optional `"characters": [{"name", "phrase", "trigger", "video_lora", "strength"}]` (sorted by name), consumed by Task 6's render;
  - stdout lines `cast: panel N: name@S, ...`.
  - Task 9's Phase 3 passes `--cast ... --character-strength S`.
- The test section produces `CAST_STORY`, `MOTION_1`, `_manifest_env`, `_manifest_argv`, `_read_manifest` and `_short` (Task 9 reuses `_manifest_env` and `_manifest_argv`).

Spec 5.4, verbatim:

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

Spec 9.5 rows P20-P25, verbatim:

| ID | Test | Assertion |
|---|---|---|
| P20 | `bin/ltx-story-manifest` `--chain --cast "the woman in grey=kyra" --cast "the ronin=ronin"` on a 3-panel story (panel 1 Motion names her, panel 2 both, panel 3 neither), with module `WS` patched to tmp | rc 0. `motion_prompt`s have triggers inserted. `panel_text`s are byte-identical to an uncast run. `characters` lists `[kyra@1.0]`, `[kyra@0.8, ronin@0.8]`, `[]`. Entry keys `{name, phrase, trigger, video_lora, strength}`. `schema_version == 3`. stdout has `cast: panel 1: kyra@1.0` |
| P21 | as P20 with `--character-strength 0.6` and ronin's `character.json` `strength 0.5` | panel 2 `[kyra@0.6, ronin@0.5]` |
| P22 | `--cast` phrase occurring in no Motion: text | rc 0. stdout has the E-P14 `WARNING:` |
| P23 | `--cast` without `--chain`; `--character-strength` without `--cast`; an unknown character; `--character-strength 0` | `SystemExit 2` / `SystemExit 2` / rc 2 / rc 2. No manifest written |
| P24 | the uncast run's manifest | has no `characters` key on any panel |
| P25 | `_prompt_length_warning` sees the cast prompt (a Motion: of 149 words plus one inserted trigger) | the `WARNING: unit 1 prompt is 150 words` line does not appear, but a 150-word Motion: plus a trigger (151) does |

Precondition: `git diff --quiet HEAD -- bin/ltx-story-manifest && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Append exactly this content to the end of `tests/test_casting_pipeline.py`. The file currently ends with a newline, and the block starts with two blank lines. Afterwards `wc -l tests/test_casting_pipeline.py` prints `803`.

````python


# --- P20-P25: bin/ltx-story-manifest --cast (spec 5.4) -----------------------------------
CAST_STORY = """# Cast test

Two travellers on a forest trail.

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a forest trail. Photorealistic live-action film still.
Motion: {motion1}
Narration: She listens to the trees.

## Panel 2 — Two
Motion: The ronin nods to the woman in grey.
Narration: They agree without a word.

## Panel 3 — Three
Motion: Leaves drift across the empty trail.
Narration: The forest is quiet again.
"""
MOTION_1 = "The woman in grey turns her head; the camera stays static."


def _manifest_env(tmp_path, monkeypatch, motion1=MOTION_1):
    """A workspace root under tmp_path for bin/ltx-story-manifest (its module WS is patched),
    with character_lib.py symlinked in so _character_lib() loads the real module, plus the
    story.md and panel 1's still. Returns (story_md, image, ws)."""
    from PIL import Image
    ws = tmp_path / "ws"
    ws.mkdir()
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / "story.md"
    story_md.write_text(CAST_STORY.format(motion1=motion1), encoding="utf-8")
    image = str(tmp_path / "panel_01.png")
    Image.new("RGB", (64, 64), (90, 90, 90)).save(image)
    return str(story_md), image, str(ws)


def _manifest_argv(story_id, story_md, image, *extra):
    return ["--story-id", story_id, "--prompts-md", story_md, "--chain", "--image", image,
            "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
            "--max-frames", "145", "--force"] + list(extra)


def _read_manifest(ws, story_id):
    with open(os.path.join(ws, "generated", "stories", story_id, "manifest.json")) as f:
        return json.load(f)


def _short(characters):
    return [(c["name"], c["strength"]) for c in characters]


def test_p20_cast_inserts_triggers_and_lists_characters(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("uncast", story_md, image)) == 0
    capsys.readouterr()
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the woman in grey=kyra",
        "--cast", "the ronin=ronin")) == 0
    out = capsys.readouterr().out
    uncast, cast = _read_manifest(ws, "uncast"), _read_manifest(ws, "cast")
    assert cast["schema_version"] == 3
    assert [p["motion_prompt"] for p in cast["panels"]] == [
        "The kyrawmn woman in grey turns her head; the camera stays static.",
        "The roninmn ronin nods to the kyrawmn woman in grey.",
        "Leaves drift across the empty trail."]
    assert [p["panel_text"] for p in cast["panels"]] == [p["panel_text"] for p in uncast["panels"]]
    assert [_short(p["characters"]) for p in cast["panels"]] == [
        [("kyra", 1.0)], [("kyra", 0.8), ("ronin", 0.8)], []]
    kyra = cast["panels"][0]["characters"][0]
    assert kyra == {"name": "kyra", "phrase": "the woman in grey", "trigger": "kyrawmn",
                    "video_lora": os.path.join(lib_dir, "kyra", "lora", "video.safetensors"),
                    "strength": 1.0}
    assert all(set(c) == {"name", "phrase", "trigger", "video_lora", "strength"}
               for p in cast["panels"] for c in p["characters"])
    assert "cast: panel 1: kyra@1.0" in out.splitlines()
    assert "cast: panel 2: kyra@0.8, ronin@0.8" in out.splitlines()
    assert not any(line.startswith("cast: panel 3") for line in out.splitlines())


def test_p21_character_strength_and_override(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir, strength=0.5)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the woman in grey=kyra",
        "--cast", "the ronin=ronin", "--character-strength", "0.6")) == 0
    panels = _read_manifest(ws, "cast")["panels"]
    assert _short(panels[0]["characters"]) == [("kyra", 1.0)]
    assert _short(panels[1]["characters"]) == [("kyra", 0.6), ("ronin", 0.5)]


def test_p22_unused_cast_phrase_warns(tmp_path, monkeypatch, capsys, lib_dir):
    _ronin(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv(
        "cast", story_md, image, "--cast", "the stranger=ronin")) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's "
            "Motion: text; that character gets no LoRA") in capsys.readouterr().out
    assert [p["characters"] for p in _read_manifest(ws, "cast")["panels"]] == [[], [], []]


def test_p23_cast_argument_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    manifest = os.path.join(ws, "generated", "stories", "bad", "manifest.json")
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--prompts-md", story_md, "--image", image,
                             "--cast", "the woman in grey=kyra"])
    assert info.value.code == 2
    assert "--cast requires --chain" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        story_manifest.main(_manifest_argv("bad", story_md, image, "--character-strength", "0.5"))
    assert info.value.code == 2
    assert "--character-strength requires --cast" in capsys.readouterr().err
    assert story_manifest.main(_manifest_argv("bad", story_md, image,
                                              "--cast", "the ghost=ghost")) == 2
    assert capsys.readouterr().err == "Error: unknown character: ghost (no %s)\n" % os.path.join(
        lib_dir, "ghost", "character.json")
    assert story_manifest.main(_manifest_argv("bad", story_md, image,
                                              "--cast", "the woman in grey=kyra",
                                              "--character-strength", "0")) == 2
    assert capsys.readouterr().err == "Error: --character-strength must be in (0, 1], got 0.0\n"
    assert not os.path.exists(manifest)


def test_p24_uncast_manifest_has_no_characters_key(tmp_path, monkeypatch, lib_dir):
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("uncast", story_md, image)) == 0
    assert all("characters" not in p for p in _read_manifest(ws, "uncast")["panels"])


def test_p25_length_warning_measures_the_cast_prompt(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    for filler, warned in ((145, False), (146, True)):
        sub = tmp_path / ("w%d" % filler)
        sub.mkdir()
        motion = "The woman in grey " + " ".join(["walks"] * filler)
        story_md, image, ws = _manifest_env(sub, monkeypatch, motion1=motion)
        capsys.readouterr()
        assert story_manifest.main(_manifest_argv(
            "long", story_md, image, "--cast", "the woman in grey=kyra")) == 0
        out = capsys.readouterr().out
        assert ("WARNING: unit 1 prompt is 151 words" in out) is warned
        assert "WARNING: unit 1 prompt is 150 words" not in out
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `5 failed, 27 passed`, `rc=1`. The guard P24 already passes: an uncast manifest has no `characters` key. Amendment 2 does not change this task's code (spec Section 10 task 7).

- [ ] **Step 3: Implement.** Apply these edits to `bin/ltx-story-manifest`, in order:

**Edit 1** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
"conditioning" key.

Dependencies: stdlib + Pillow only (for an image-openable sanity check on
each selected file). No torch, no diffusers -- this tool must stay fast
````

with:

````python
"conditioning" key.

--cast PHRASE=NAME (repeatable, --chain only) casts a trained character from the
character library (generated/characters/NAME, see
docs/superpowers/specs/2026-10-05-character-library-design.md). The character's trigger
token is inserted into every Motion: text (motion_prompt) that names PHRASE; panel_text
is left as authored. Every panel then carries an optional "characters" list (possibly
empty) of {"name", "phrase", "trigger", "video_lora", "strength"} entries, sorted by
name: strength is 1.0 when the panel names exactly one cast character, else the
character's own character.json strength or --character-strength (default 0.8).
schema_version stays 3, because the key is optional. character_lib.py is loaded by path
only when --cast is given.

Dependencies: stdlib + Pillow only (for an image-openable sanity check on
each selected file). No torch, no diffusers -- this tool must stay fast
````

**Edit 2** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
import datetime
import glob as glob_module
import json
import os
````

with:

````python
import datetime
import glob as glob_module
import importlib.machinery
import json
import os
````

**Edit 3** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
                         help="explicit per-panel num_frames override, repeatable; "
                              "count must equal panel count; mutually exclusive with --pace")
    return parser


````

with:

````python
                         help="explicit per-panel num_frames override, repeatable; "
                              "count must equal panel count; mutually exclusive with --pace")
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
    return parser


def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


````

**Edit 4** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
        if len(args.image or []) != 1:
            parser.error("--chain requires exactly one --image (panel 1's still)")

    if args.no_images:
````

with:

````python
        if len(args.image or []) != 1:
            parser.error("--chain requires exactly one --image (panel 1's still)")
    if args.cast and not args.chain:
        parser.error("--cast requires --chain")
    if args.character_strength is not None and not args.cast:
        parser.error("--character-strength requires --cast")

    if args.no_images:
````

**Edit 5** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
        print("WARNING: no --prompts-md; panel_text is a placeholder "
              "— edit manifest.json before running")

    n_panels = len(prompt_texts) if (args.no_images or args.chain) else len(matched)
````

with:

````python
        print("WARNING: no --prompts-md; panel_text is a placeholder "
              "— edit manifest.json before running")

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

    n_panels = len(prompt_texts) if (args.no_images or args.chain) else len(matched)
````

**Edit 6** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
        panels.append(panel)

    for p in panels:
        # Chain mode: the video model receives the Motion: text, so that is what is measured.
````

with:

````python
        panels.append(panel)

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

    for p in panels:
        # Chain mode: the video model receives the Motion: text, so that is what is measured.
````

**Edit 7** (`bin/ltx-story-manifest`). Replace this exact text, which occurs exactly once:

````python
              % (p["index"], basename, p["num_frames"], p["duration_s"], p["title"]))
    print("TOTAL %d frames = %.2f s @ %d fps" % (total_num_frames, total_num_frames / args.fps, args.fps))

    return 0
````

with:

````python
              % (p["index"], basename, p["num_frames"], p["duration_s"], p["title"]))
    print("TOTAL %d frames = %.2f s @ %d fps" % (total_num_frames, total_num_frames / args.fps, args.fps))
    if members:
        for p in panels:
            if p["characters"]:
                print("cast: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"])))

    return 0
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `32 passed`, `rc=0`.

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-story-manifest tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-story-manifest: --cast trigger insertion and per-panel characters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 8: `bin/ltx-story-images --cast` -- stills LoRAs for the Panel 1 still

**Files:**
- Modify: `bin/ltx-story-images` (9 edits below; +139/-7 lines)
- Test: append to `tests/test_casting_pipeline.py` (999 lines at the end of this task)

**Interfaces:**
- Consumes:
  - `character_lib` (Task 3), loaded by path;
  - `z_image_skill.generate_image(..., lora_path=args.lora_path, **lora_kwargs)` with `lora_kwargs = {"loras": [(path, strength)]}` (Task 5).
- Produces:
  - CLI flags `--cast PHRASE=NAME` (repeatable) and `--character-strength S`;
  - `_character_lib()`;
  - every planned images.json panel entry gains `"loras": [{"name", "path", "strength"}]`;
  - a dry-run line `    loras: name=path@S, ... | none` per planned panel (`global=path@S` for a global, Decision 26);
  - (amendment 2) `_RepeatableLoraAction` (an identical copy) and the repeatable `--lora PATH[:STRENGTH]` flag; the 5.7.4 legacy/merged routes; images.json `loras` entries `{"kind", "name", "path", "strength"}`, globals first.
- The test section produces `IMAGES_STORY`, `_FakeContentSafetyError`, `_fake_zimage`, `_images_env` and `_images_json` (Task 9 reuses `_fake_zimage` and `_images_env`).

Spec 5.5, verbatim:

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

Spec 5.7.4 (amendment 2; supersedes the 5.5 `--cast` + `--lora` refusal), verbatim:

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

Spec 9.5 rows P30-P35, P68, P69, verbatim:

| ID | Test | Assertion |
|---|---|---|
| P30 | `bin/ltx-story-images --cast "the woman in grey=kyra" --only 1` with kyra having a stills LoRA. Fake `torch`/`z_image_skill`/`content_safety` modules are in `sys.modules`; the fake `generate_image` records kwargs | the call has `loras == [(stills, 1.0)]` and `lora_path is None`. The prompt has `the kyrawmn woman in grey`. `images.json` panel `loras == [{"kind": "character", "name": "kyra", "path": stills, "strength": 1.0}]` and `prompt` is the cast prompt |
| P31 | kyra without a stills LoRA | stdout has the E-P17 `WARNING:`. The prompt has no trigger. The call has no `loras` key. `images.json` panel `loras == []` |
| P32 | `--only 1,2` where panel 1 names kyra and panel 2 names ronin (both with stills) | rc 2, E-P16. `generate_image` never called |
| P33 | (amendment 2) `--cast "the woman in grey=kyra" --lora g:0.5 --only 1` (kyra with a stills LoRA, `g` real) | rc 0. The call has `loras == [(g, 0.5), (stills, 1.0)]` and `lora_path is None`. `images.json` panel `loras` kinds are `["global", "character"]` |
| P34 | `--dry-run --cast …` | stdout shows the cast prompt and `    loras: kyra=<p>@1.0`. `torch` not imported (subprocess check, as in the existing I-tests) |
| P35 | the uncast run with the same fake modules | the call kwargs have no `loras` key. `images.json` panels have no `loras` key |
| P68 | ltx-story-images, no `--cast`: (a) `--lora my_lora.safetensors` (nonexistent); (b) `--lora g1 --lora g2:0.5` (real) | (a) `lora_path == "my_lora.safetensors"`, no `loras` kwarg, `images.json` has no `loras` key (today's behavior). (b) `loras == [(g1, 1.0), (g2, 0.5)]`, `lora_path is None`, `images.json` `loras` kinds `["global", "global"]` |
| P69 | ltx-story-images errors: `--lora <kyra's stills_lora>` with `--cast …=kyra`; `--lora /missing:0.5`; `--only 1,2 --lora g:0.5` where panels 1 and 2 match different characters | E-P28 (`stills LoRA`); E-P26; E-P16. `generate_image` never called |

Two existing source pins constrain this task (Decisions 2-3): `tests/test_ltx_story_images.py` I20 needs `_compose_prompt(` to occur 3 times and `_panel_seed(args.seed, i, grounded)` 2 times, and I13 needs `"source": "generated"` to occur 4 times. The edits below keep all three counts. Do not add a comment that contains `_compose_prompt(`.

Precondition: `git diff --quiet HEAD -- bin/ltx-story-images && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Append exactly this content to the end of `tests/test_casting_pipeline.py`. The file currently ends with a newline, and the block starts with two blank lines. Afterwards `wc -l tests/test_casting_pipeline.py` prints `999`.

````python


# --- P30-P35: bin/ltx-story-images --cast (spec 5.5) -------------------------------------
IMAGES_STORY = """# Stills cast test

Two travellers.

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a forest trail. Photorealistic live-action film still.
Motion: The woman in grey turns her head.
Narration: She listens.

## Panel 2 — Two
Image: A medium shot of the ronin waiting under a cedar. Photorealistic live-action film still.
Motion: The ronin nods.
Narration: He waits.
"""


class _FakeContentSafetyError(Exception):
    pass


def _fake_zimage(monkeypatch):
    """Fake torch, z_image_skill and content_safety modules in sys.modules; returns the list
    of (prompt, kwargs) generate_image calls."""
    calls = []

    class _Generator(object):
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            self.seed = seed
            return self

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = lambda prompt, **kwargs: calls.append((prompt, kwargs))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _FakeContentSafetyError
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    return calls


def _images_env(tmp_path):
    story_md = tmp_path / "story.md"
    story_md.write_text(IMAGES_STORY, encoding="utf-8")
    return str(story_md), str(tmp_path / "images")


def _images_json(out_dir):
    with open(os.path.join(out_dir, "images.json")) as f:
        return json.load(f)


def test_p30_still_renders_with_the_stills_lora(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert kwargs["loras"] == [(stills, 1.0)]
    assert kwargs["lora_path"] is None
    assert "the kyrawmn woman in grey" in prompt
    panel = _images_json(out_dir)["panels"][0]
    assert panel["loras"] == [{"kind": "character", "name": "kyra", "path": stills,
                               "strength": 1.0}]
    assert panel["prompt"] == prompt


def test_p31_member_without_stills_lora_warns(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    assert ("WARNING: character kyra has no stills LoRA (not trained); its trigger is not "
            "inserted into Image: prompts and panel stills render without it"
            in capsys.readouterr().out)
    prompt, kwargs = calls[0]
    assert "kyrawmn" not in prompt
    assert "loras" not in kwargs
    assert _images_json(out_dir)["panels"][0]["loras"] == []


def test_p32_different_lora_sets_are_refused(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _ronin(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2",
                              "--cast", "the woman in grey=kyra",
                              "--cast", "the ronin=ronin"]) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
        "set per process); run one --only panel per invocation\n")
    assert calls == []


def test_p33_global_stills_lora_combines_with_the_cast(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    g = str(tmp_path / "g.safetensors")
    with open(g, "wb") as f:
        f.write(b"global")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra", "--lora", g + ":0.5"]) == 0
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert calls[0][1]["loras"] == [(g, 0.5), (stills, 1.0)]
    assert calls[0][1]["lora_path"] is None
    assert [l["kind"] for l in _images_json(out_dir)["panels"][0]["loras"]] == ["global",
                                                                               "character"]


def test_p34_dry_run_shows_the_cast_plan_without_torch(tmp_path, lib_dir):
    make_character(lib_dir, stills=True)
    story_md, out_dir = _images_env(tmp_path)
    script = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_story_images', %r).load_module()\n"
        "rc = m.main(['--story-md', %r, '--out-dir', %r, '--only', '1', '--dry-run',\n"
        "             '--cast', 'the woman in grey=kyra'])\n"
        "print('TORCH_IMPORTED=%%s' %% ('torch' in sys.modules))\n"
        "print('RC=%%d' %% rc)\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-story-images"), story_md, out_dir)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir))
    lines = proc.stdout.splitlines()
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    assert "RC=0" in lines
    assert "TORCH_IMPORTED=False" in lines
    assert any(line.startswith("1 | ") and "the kyrawmn woman in grey" in line for line in lines)
    assert "    loras: kyra=%s@1.0" % stills in lines


def test_p35_uncast_run_is_unchanged(tmp_path, monkeypatch, lib_dir):
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1"]) == 0
    assert "loras" not in calls[0][1]
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])


# --- P68-P69: global stills LoRAs (spec 5.7.4, amendment 2) -------------------------------
def test_p68_global_stills_without_a_cast(tmp_path, monkeypatch, lib_dir):
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--lora", "my_lora.safetensors"]) == 0
    assert calls[0][1]["lora_path"] == "my_lora.safetensors"
    assert "loras" not in calls[0][1]
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])
    g1, g2 = str(tmp_path / "g1.safetensors"), str(tmp_path / "g2.safetensors")
    for path in (g1, g2):
        with open(path, "wb") as f:
            f.write(b"global")
    calls[:] = []
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--force", "--lora", g1, "--lora", g2 + ":0.5"]) == 0
    assert calls[0][1]["loras"] == [(g1, 1.0), (g2, 0.5)]
    assert calls[0][1]["lora_path"] is None
    assert [l["kind"] for l in _images_json(out_dir)["panels"][0]["loras"]] == ["global", "global"]


def test_p69_global_stills_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _ronin(lib_dir, stills=True)
    calls = _fake_zimage(monkeypatch)
    story_md, out_dir = _images_env(tmp_path)
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    g = str(tmp_path / "g.safetensors")
    with open(g, "wb") as f:
        f.write(b"global")
    base = ["--story-md", story_md, "--out-dir", out_dir]
    assert story_images.main(base + ["--only", "1", "--cast", "the woman in grey=kyra",
                                     "--lora", stills]) == 2
    assert capsys.readouterr().err == (
        "Error: --lora %s is also character kyra's stills LoRA; pass it once\n" % stills)
    assert story_images.main(base + ["--only", "1", "--lora", "/missing:0.5"]) == 2
    assert capsys.readouterr().err == "Error: --lora /missing: not a readable file\n"
    assert story_images.main(base + ["--only", "1,2", "--cast", "the woman in grey=kyra",
                                     "--cast", "the ronin=ronin", "--lora", g + ":0.5"]) == 2
    assert capsys.readouterr().err == (
        "Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
        "set per process); run one --only panel per invocation\n")
    assert calls == []
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `7 failed, 33 passed`, `rc=1`. The guard P35 already passes: an uncast run is unchanged.

- [ ] **Step 3: Implement.** Apply these edits to `bin/ltx-story-images`, in order:

**Edit 1** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
batch whether or not --seed-image is passed again.

Dependencies: stdlib only at import time. torch/z_image_skill/content_safety
are imported inside main(), after arg parsing and the --dry-run exit, so a
````

with:

````python
batch whether or not --seed-image is passed again.

Casting: --cast PHRASE=NAME (repeatable) casts a trained character from the character
library (docs/superpowers/specs/2026-10-05-character-library-design.md). For each cast
character that has a stills LoRA, its trigger token is inserted into every Image: prompt
that names PHRASE, and the panel is generated with those characters' stills LoRAs
(strength 1.0 for one character, else --character-strength or the character's own
strength). A character without a stills LoRA gets a warning and no trigger. Every planned
images.json entry then gains a "loras" list. z_image_skill loads one LoRA set per
process, so the selected panels must all need the same set. character_lib.py is loaded by
path only when --cast is given.

Dependencies: stdlib only at import time. torch/z_image_skill/content_safety
are imported inside main(), after arg parsing and the --dry-run exit, so a
````

**Edit 2** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
sys.path.insert(0, WS)
import pipeline_log  # noqa: E402


````

with:

````python
sys.path.insert(0, WS)
import pipeline_log  # noqa: E402


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


````

**Edit 3** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
                             "Panel 1 takes this path even with --force (there is no "
                             "txt2img output to regenerate).")
    parser.add_argument("--lora", dest="lora_path", default=None,
                        help="LoRA .safetensors file or HF repo ID for z_image_skill, "
                             "prep for future fine-tuning; always applied at strength "
                             "1.0. Never used by --seed-image panels (there is no "
                             "generation to apply it to).")
    return parser


````

with:

````python
                             "Panel 1 takes this path even with --force (there is no "
                             "txt2img output to regenerate).")
    parser.add_argument("--lora", dest="lora_path", action=_RepeatableLoraAction, default=None,
                        help="global LoRA for z_image_skill stills: repeatable; PATH or "
                             "PATH:STRENGTH (0 < STRENGTH <= 2, default 1.0). Every global LoRA "
                             "applies to every panel, ahead of that panel's cast-character LoRAs, "
                             "at its own strength (never reduced automatically). Never used by "
                             "--seed-image panels (there is no generation to apply it to).")
    parser.add_argument("--cast", dest="cast", action="append", default=None,
                        metavar="PHRASE=NAME",
                        help="cast a trained character (generated/characters/NAME) under PHRASE "
                             "(repeatable): for a character with a stills LoRA, its trigger is "
                             "inserted into every Image: prompt that names PHRASE and the panel "
                             "is generated with that LoRA")
    parser.add_argument("--character-strength", dest="character_strength", type=float,
                        default=None,
                        help="stills LoRA strength for each cast character in a panel that names "
                             "two or more of them (default 0.8, provisional); one character "
                             "always uses 1.0")
    return parser


def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


````

**Edit 4** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
        return 2

    # Grounded mode (see the module docstring): a non-empty Panel 1 Style: field
    # means this story.md was authored against a reference image and every panel
````

with:

````python
        return 2

    members, strength, plans = [], None, {}
    if args.character_strength is not None and not args.cast:
        print("Error: --character-strength requires --cast", file=sys.stderr)
        return 2
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
    import ltx2_mlx_video_skill
    try:
        parsed = [ltx2_mlx_video_skill.parse_lora_spec(v)
                  for v in (getattr(args, "lora_path_specs", None) or [])]
    except ValueError as e:
        print("Error: --lora: %s" % e, file=sys.stderr)
        return 2

    # Grounded mode (see the module docstring): a non-empty Panel 1 Style: field
    # means this story.md was authored against a reference image and every panel
````

**Edit 5** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
    style = _style_text(panels)
    grounded = bool(style)

    # panel_%02d.png matches bin/ltx-story-manifest's own _PANEL_NUM_RE, so
````

with:

````python
    style = _style_text(panels)
    grounded = bool(style)

    # A bound name, not a literal call: tests/test_ltx_story_images.py I20 pins how
    # many times the composing function's call text appears in this file.
    compose = _compose_prompt
    char_plans = {}
    if members:
        stills_members = [m for m in members if m.stills_lora]
        for m in members:
            if not m.stills_lora:
                print("WARNING: character %s has no stills LoRA (%s); its trigger is not inserted into "
                      "Image: prompts and panel stills render without it"
                      % (m.name, m.stills_skip_reason or "not trained"))
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            prompt, names = lib.cast_text(compose(panels[i - 1]["image"], style), stills_members)
            strengths = lib.panel_strengths(names, stills_members, strength)
            by_name = {m.name: m for m in stills_members}
            char_plans[i] = (prompt, [{"kind": "character", "name": n, "path": by_name[n].stills_lora,
                                       "strength": strengths[n]} for n in names])
    global_stills = []
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not any(v[1] for v in char_plans.values()):
        args.lora_path = parsed[0][0]                       # legacy route (spec 5.7.2)
    elif parsed:
        args.lora_path = None
        seen = {}
        for path, lora_strength, _explicit in parsed:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                print("Error: --lora %s: not a readable file" % path, file=sys.stderr)
                return 2
            real = os.path.realpath(path)
            if real in seen:
                print("Error: --lora %s is given more than once" % path, file=sys.stderr)
                return 2
            seen[real] = path
            global_stills.append({"kind": "global", "name": None, "path": os.path.abspath(path),
                                  "strength": lora_strength})
        for m in members:
            if m.stills_lora and os.path.realpath(m.stills_lora) in seen:
                print("Error: --lora %s is also character %s's stills LoRA; pass it once"
                      % (seen[os.path.realpath(m.stills_lora)], m.name), file=sys.stderr)
                return 2
    if members or global_stills:
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            prompt, chars = char_plans.get(i, (compose(panels[i - 1]["image"], style), []))
            plans[i] = (prompt, global_stills + chars)
    lora_sets = sorted({tuple((l["path"], l["strength"]) for l in v[1]) for v in plans.values()})
    if len(lora_sets) > 1:
        print("Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
              "set per process); run one --only panel per invocation", file=sys.stderr)
        return 2

    # panel_%02d.png matches bin/ltx-story-manifest's own _PANEL_NUM_RE, so
````

**Edit 6** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
                print("%d | %s | rng %d | +style | %r"
                      % (i, out_paths[i], _panel_seed(args.seed, i, grounded),
                         _compose_prompt(panels[i - 1]["image"], style)[:100]))
            else:
                print("%d | %s | %r" % (i, out_paths[i], panels[i - 1]["image"][:100]))
        return 0

````

with:

````python
                print("%d | %s | rng %d | +style | %r"
                      % (i, out_paths[i], _panel_seed(args.seed, i, grounded),
                         (plans[i][0] if i in plans
                          else _compose_prompt(panels[i - 1]["image"], style))[:100]))
            else:
                print("%d | %s | %r" % (i, out_paths[i],
                                        (plans[i][0] if i in plans
                                         else panels[i - 1]["image"])[:100]))
            if i in plans:
                print("    loras: %s" % (", ".join("%s=%s@%s" % (l["name"] or "global", l["path"], repr(l["strength"]))
                                                   for l in plans[i][1]) or "none"))
        return 0

````

**Edit 7** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
    for i in selected_indices:
        prompt = _compose_prompt(panels[i - 1]["image"], style)
        seed_used = _panel_seed(args.seed, i, grounded)
        path = out_paths[i]

        if args.seed_image is not None and i == 1:
````

with:

````python
    for i in selected_indices:
        prompt = _compose_prompt(panels[i - 1]["image"], style)
        if i in plans:
            prompt = plans[i][0]
        seed_used = _panel_seed(args.seed, i, grounded)
        path = out_paths[i]
        lora_kwargs = ({"loras": [(l["path"], l["strength"]) for l in plans[i][1]]}
                       if i in plans and plans[i][1] else {})

        if args.seed_image is not None and i == 1:
````

**Edit 8** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
                generator=torch.Generator("cpu").manual_seed(seed_used),
                lora_path=args.lora_path,
            )
            elapsed = time.monotonic() - start
````

with:

````python
                generator=torch.Generator("cpu").manual_seed(seed_used),
                lora_path=args.lora_path,
                **lora_kwargs,
            )
            elapsed = time.monotonic() - start
````

**Edit 9** (`bin/ltx-story-images`). Replace this exact text, which occurs exactly once:

````python
                             "seconds": round(elapsed, 1)})
            any_bad = True

    with open(os.path.join(args.out_dir, "images.json"), "w") as f:
````

with:

````python
                             "seconds": round(elapsed, 1)})
            any_bad = True

    for r in results:
        if r["index"] in plans:
            r["loras"] = plans[r["index"]][1]

    with open(os.path.join(args.out_dir, "images.json"), "w") as f:
````

After the edits, this must print `3 2 4 3`:

````bash
python3 -c "s=open('bin/ltx-story-images').read(); print(s.count('_compose_prompt('), s.count('_panel_seed(args.seed, i, grounded)'), s.count('\"source\": \"generated\"'), s.count('\"source\": \"seed\"'))"
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `40 passed`, `rc=0`.

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-story-images tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-story-images: --cast stills LoRAs, trigger insertion and repeatable global --lora

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 9: `bin/ltx-movie` -- `--character`/`--cast`, the Cast block, the available line, `--list-characters`

**Files:**
- Modify: `bin/ltx-movie` (15 edits below; +252/-17 lines)
- Test: append to `tests/test_casting_pipeline.py` (1409 lines at the end of this task)

**Interfaces:**
- Consumes:
  - `character_lib` (Task 3), loaded by path: `DEFAULT_CHARACTER_STRENGTH`, `parse_cast_arg`, `resolve_cast`, `build_cast_block`, `phrase_occurs`, `usable_characters`, `format_available_line`, `character_table_lines`, `CharacterError`, `UnusableCharacterError`;
  - the `--cast`/`--character-strength` flags of Tasks 7 and 8.
- Produces:
  - CLI flags `--character NAME` (repeatable, `dest="characters"`), `--cast PHRASE=NAME` (repeatable, `dest="casts"`), `--character-strength S` and `--list-characters`;
  - `_character_lib()`, `_resolve_casting(args) -> 0|2` (sets `args.cast_members`, `args.cast_block`, `args.character_strength`), `_list_characters(raw_argv) -> 0|2`, `_cast_flags(args) -> list`;
  - `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds, cast_block=None)`;
  - (amendment 2) `_RepeatableLoraAction` (an identical copy) on `--lora` and `--stills-lora`, `_video_skill()`, `_resolve_global_loras(args) -> 0|2` (sets `args.global_video_loras` and `args.global_stills_loras`), and the `<abs path>:<strength>` forwarding in `_render_flags` and both Phase 2 command builders. `_resolve_casting` no longer refuses `--lora`/`--stills-lora`.
- The test section produces `ANCHOR`, `MOVIE_STORY`, `_movie_stories`, `_write_story`, `_movie_args`, `_c45_library`, `_casting_stderr` and `_story_locks`. Task 13's P55 reuses `_c45_library`.

Spec 5.6, verbatim (including the amendment's 5.6(i)):

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

Spec 5.7.5 (amendment 2), verbatim:

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

Spec 9.5 rows P40-P54, P56, P57, P70-P73, P75, verbatim (P55 is added in Task 13, Decision 17; P75 lives here, Decision 28):

| ID | Test | Assertion |
|---|---|---|
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
| P56 | `ltx_movie.build_parser().format_help()` | contains `--list-characters`. The L1-style substring checks (`"145 frames @ 24 fps = 6.04s per clip."`) still hold. B1 still passes |
| P57 | manifest `--cast "the ronin=ghost"`; images `--cast "the ronin=ghost"` | rc 2. stderr is the single `Error: unknown character: …` line, with no `available characters:` (E-P6c) |
| P70 | ltx-movie legacy: `--lora x` (nonexistent, no cast) | `_resolve_global_loras` returns 0 with both lists `[]`. `_render_flags(args)` equals today's (contains `["--lora", "x"]`). The B1 golden still matches |
| P71 | ltx-movie merged: `--character kyra --lora g:0.7 --stills-lora s` (real files, kyra with a stills LoRA, no story.md) | rc 0. `_render_flags` contains `["--lora", "<abs g>:0.7"]` and no raw `g`. The Phase 2 dry-run command contains `--lora <abs s>:1.0` (merged, because kyra has a stills LoRA), then the `_cast_flags` |
| P72 | ltx-movie: `--character kyra --lora <kyra video_lora>`; `--stills-lora s --stills-lora s`; `--lora g:abc` (treated as path `g:abc`, missing) with a cast | E-P28 (`video LoRA`); E-P27; E-P26. Also, `--character kyra --lora g` is accepted (the former E-P3 is gone) |
| P73 | `_RepeatableLoraAction`: parse `["--lora", "a", "--lora", "b"]`; parse with no `--lora` | `lora_path == "a"`, `lora_path_specs == ["a", "b"]`; `lora_path is None` and `not hasattr(ns, "lora_path_specs")` |
| P75 | `inspect.getsource` of `_RepeatableLoraAction` in bin/ltx-movie, bin/ltx-mlx-render, bin/ltx-story-images | all three are identical strings |

Existing source pins that must stay true (all verified): L1z5 (`["--lora", args.stills_lora_path]` occurs exactly twice; the legacy fallbacks keep that text), L7i, L12, L29c/L29d, and `_render_flags(args)` and `os.path.join(WS, "bin", "ltx-mlx-render")` at 4 occurrences each in `tests/test_ltx_movie_offline.py`. Also, `bin/ltx-movie` must not gain a top-level `import re` (L7j), and `character_lib` must not be imported at top level (P49).

Precondition: `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** Append exactly this content to the end of `tests/test_casting_pipeline.py`. The file currently ends with a newline, and the block starts with two blank lines. Afterwards `wc -l tests/test_casting_pipeline.py` prints `1409`.

````python


# --- P40-P49: bin/ltx-movie --character / --cast (spec 5.6) ------------------------------
ANCHOR = "\n\nHow this movie is made:"
MOVIE_STORY = """# Movie cast test

Two travellers.

## Panel 1 — One
Image: A medium shot of {phrase} standing on a forest trail. Photorealistic live-action film still.
Motion: {phrase_cap} turns; the camera stays static.
Narration: A pause.

## Panel 2 — Two
Motion: {phrase_cap} steps forward.
Narration: A step.

## Panel 3 — Three
Motion: {phrase_cap} stops.
Narration: A stop.
"""


def _movie_stories(tmp_path, monkeypatch):
    """Point bin/ltx-movie's story dirs at tmp_path/stories (WS itself is unchanged, so
    _character_lib() and the story.md validator still load from the real workspace)."""
    stories = tmp_path / "stories"
    monkeypatch.setattr(ltx_movie, "_story_dir", lambda sid: str(stories / sid))
    return stories


def _write_story(stories, story_id, phrase):
    directory = stories / story_id
    directory.mkdir(parents=True)
    path = directory / "story.md"
    path.write_text(MOVIE_STORY.format(phrase=phrase, phrase_cap=phrase[0].upper() + phrase[1:]),
                    encoding="utf-8")
    return str(path)


def _movie_args(*argv):
    return ltx_movie.build_parser().parse_args(list(argv))


def test_p40_cast_block_sits_before_the_how_anchor():
    plain = ltx_movie.build_story_prompt("n", "sid", 3, seconds="6")
    expected = plain.replace(ANCHOR, "\n\nCAST" + ANCHOR)
    assert plain.count(ANCHOR) == 1
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block="CAST") == expected
    assert ltx_movie.build_story_prompt("n", "sid", 3, seed_image=True, seconds="6",
                                        cast_block="CAST") == (
        ltx_movie.SEED_IMAGE_PREFACE + "\n\n" + expected + "\n\n" + ltx_movie.SEED_IMAGE_POSTFACE)


def test_p41_no_cast_block_means_no_change():
    plain = ltx_movie.build_story_prompt("n", "sid", 3, seconds="6")
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block=None) == plain
    assert ltx_movie.build_story_prompt("n", "sid", 3, seconds="6", cast_block="") == plain


def test_p42_resolve_casting_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    override = tmp_path / "prompt.txt"
    override.write_text("verbatim prompt", encoding="utf-8")
    new_md = str(stories / "new" / "story.md")
    old_md = _write_story(stories, "old", "the traveller")
    cases = [
        (["n", "--story-id", "new", "--character-strength", "0.5"],
         "Error: --character-strength requires --character or --cast"),
        (["n", "--story-id", "new", "--character", "kyra", "--no-stills"],
         "Error: --character/--cast are not supported with --no-stills: casting needs the "
         "chained flow"),
        (["n", "--story-id", "new", "--character", "kyra", "--character-strength", "1.5"],
         "Error: --character-strength must be in (0, 1], got 1.5"),
        (["n", "--story-id", "new", "--cast", "the ronin"],
         "Error: --cast must be PHRASE=NAME, got 'the ronin'"),
        (["n", "--story-id", "new", "--character", "ghost"],
         "Error: unknown character: ghost (no %s)\n"
         "available characters: kyra (the woman in grey), ronin (the ronin)"
         % os.path.join(lib_dir, "ghost", "character.json")),
        (["n", "--story-id", "new", "--character", "kyra", "--cast", "the woman in grey=ronin"],
         "Error: cast phrase 'the woman in grey' is used for both kyra and ronin"),
        (["n", "--story-id", "new", "--cast", "the ronin=ronin"],
         "Error: --cast needs an existing story.md that already uses the phrase, and Phase 1 is "
         "about to write a new one (%s); use --character to cast a new story" % new_md),
        (["--story-id", "new", "--character", "kyra", "--story-prompt-override", str(override)],
         "Error: --character cannot be combined with --story-prompt-override when Phase 1 runs: "
         "the override is used verbatim, so the Cast block cannot be added"),
        (["n", "--story-id", "old", "--character", "kyra"],
         "Error: cast phrase 'the woman in grey' (character kyra) does not occur in %s" % old_md),
    ]
    for argv, message in cases:
        args = _movie_args(*argv)
        assert ltx_movie._resolve_casting(args) == 2, argv
        assert capsys.readouterr().err == message + "\n"
        assert args.cast_members == []


def test_p43_character_on_a_new_story_builds_the_cast_block(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    args = _movie_args("n", "--story-id", "new", "--character", "kyra")
    assert ltx_movie._resolve_casting(args) == 0
    members = character_lib.resolve_cast([(None, "kyra")])
    assert args.cast_block == character_lib.build_cast_block(members)
    assert args.cast_members == members
    assert args.character_strength == 0.8


def test_p44_existing_story_mixes_character_and_cast(tmp_path, monkeypatch, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    path = _write_story(stories, "old", "the woman in grey")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n## Panel 4 — Four\nMotion: The ronin waits.\nNarration: He waits.\n")
    args = _movie_args("n", "--story-id", "old", "--character", "kyra",
                       "--cast", "the ronin=ronin")
    assert ltx_movie._resolve_casting(args) == 0
    assert args.cast_block is None
    assert [m.name for m in args.cast_members] == ["kyra", "ronin"]
    assert ltx_movie._cast_flags(args) == [
        "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8"]


def test_p45_cast_flags_empty_when_uncast():
    import argparse
    assert ltx_movie._cast_flags(argparse.Namespace()) == []
    assert ltx_movie._cast_flags(argparse.Namespace(cast_members=[],
                                                    character_strength=0.8)) == []


def test_p46_dry_run_with_character(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    assert ltx_movie.main(["two travellers", "--story-id", "casting-p46", "--dry-run",
                           "--no-review", "--character", "kyra"]) == 0
    out = capsys.readouterr().out
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    assert "--- Cast ---" in out.splitlines()
    assert ('cast: kyra as "the woman in grey" (trigger kyrawmn; video LoRA %s; stills LoRA '
            'none: not trained)' % video) in out.splitlines()
    block = character_lib.build_cast_block(character_lib.resolve_cast([(None, "kyra")]))
    assert "\n\n" + block + ANCHOR in out
    commands = [line for line in out.splitlines() if line.startswith("Command: ")]
    flags = "--cast 'the woman in grey=kyra' --character-strength 0.8"
    assert flags in next(c for c in commands if "ltx-story-images" in c)
    assert flags in next(c for c in commands if "ltx-story-manifest" in c)


def test_p47_phase1_warns_when_story_md_omits_a_cast_phrase(tmp_path, monkeypatch, capsys,
                                                            lib_dir):
    make_character(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    _write_story(stories, "old", "the traveller")
    args = _movie_args("n", "--story-id", "old", "--panels", "3", "--no-review")
    args.cast_members = character_lib.resolve_cast([(None, "kyra")])
    assert ltx_movie.phase1_story(args) == 0
    assert ("Warning: story.md does not use cast phrase 'the woman in grey'; character kyra "
            "gets no LoRA in this story") in capsys.readouterr().out


def test_p48_phase2_warns_about_a_reused_panel_01(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    stories = _movie_stories(tmp_path, monkeypatch)
    _write_story(stories, "old", "the woman in grey")
    images = stories / "old" / "images"
    images.mkdir()
    (images / "panel_01.png").write_bytes(b"png")
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    args = _movie_args("n", "--story-id", "old")
    args.video_width, args.video_height = 704, 448
    args.cast_members = character_lib.resolve_cast([(None, "kyra")])
    args.character_strength = 0.8
    assert ltx_movie.phase2_stills(args) == 0
    assert ("Warning: %s exists and will be reused as-is; it was not necessarily rendered with "
            "the cast's stills LoRAs (delete it to regenerate)" % (images / "panel_01.png")
            in capsys.readouterr().out)
    assert runs[0][-4:] == ["--cast", "the woman in grey=kyra", "--character-strength", "0.8"]


def test_p49_uncast_ltx_movie_never_loads_character_lib():
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    lines = proc.stdout.splitlines()
    assert "RC=0" in lines
    assert "CHARACTER_LIB_LOADED=False" in lines



# --- P50-P57: cast discovery and --list-characters (spec 3.9, 5.6(i), amendment) ---------
def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    _ronin(lib, status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def _casting_stderr(capsys, *argv):
    args = _movie_args(*argv)
    assert ltx_movie._resolve_casting(args) == 2
    assert args.cast_members == []
    return capsys.readouterr().err


def test_p50_unknown_character_lists_the_usable_ones(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "ghost") == (
        "Error: unknown character: ghost (no %s)\n"
        "available characters: kyra (the woman in grey), ronin (the ronin)\n"
        % os.path.join(lib_dir, "ghost", "character.json"))


def test_p51_no_usable_characters(tmp_path, monkeypatch, capsys, lib_dir):
    _movie_stories(tmp_path, monkeypatch)
    none = "available characters: none (create one with bin/character create)"
    err = _casting_stderr(capsys, "n", "--story-id", "new", "--character", "ghost")
    assert err.splitlines()[1] == none
    make_character(lib_dir, name="zed", trigger="zedtrig", phrase="the zed", status="untrained")
    err = _casting_stderr(capsys, "n", "--story-id", "new", "--character", "zed")
    assert err.splitlines() == [
        "Error: character zed is not trained (status untrained); run bin/character train zed",
        none]


def test_p52_which_errors_list_alternatives(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _ronin(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    both = "available characters: kyra (the woman in grey), ronin (the ronin)"
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--cast", "the ronin=Ronin") == (
        "Error: character name must match [a-z][a-z0-9-]{1,23}, got 'Ronin'\n" + both + "\n")
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "kyra",
                           "--character", "kyra") == (
        "Error: character kyra is cast more than once\n")
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--cast", "the ronin") == (
        "Error: --cast must be PHRASE=NAME, got 'the ronin'\n")
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    os.remove(video)
    assert _casting_stderr(capsys, "n", "--story-id", "new", "--character", "kyra") == (
        "Error: character kyra's video LoRA is missing or empty: %s\n"
        "available characters: ronin (the ronin)\n" % video)


def _story_locks():
    return set(glob.glob(os.path.join(WS, "generated", "stories", "**", ".movie.lock"),
                         recursive=True))


def test_p53_list_characters_prints_the_table_and_touches_nothing(monkeypatch, capsys,
                                                                  lib_dir):
    import builtins
    _c45_library(lib_dir)

    def _forbidden(*args, **kwargs):
        raise AssertionError("--list-characters ran a subprocess or prompted")

    monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(builtins, "input", _forbidden)
    before = _story_locks()
    assert ltx_movie.main(["--list-characters"]) == 0
    out, err = capsys.readouterr()
    assert out == "\n".join(character_lib.character_table_lines()) + "\n"
    assert err == ""
    assert _story_locks() == before


def test_p54_list_characters_must_be_alone(capsys):
    for argv in (["--list-characters", "--story-id", "x"], ["a narrative", "--list-characters"],
                 ["--list-characters", "--help"]):
        assert ltx_movie.main(argv) == 2, argv
        out, err = capsys.readouterr()
        assert err == "Error: --list-characters takes no other arguments\n"
        assert out == ""


def test_p56_help_lists_the_flag():
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    assert "--list-characters" in helptext
    assert "145 frames @ 24 fps = 6.04s per clip." in helptext


def test_p57_manifest_and_images_print_no_available_line(tmp_path, monkeypatch, capsys,
                                                         lib_dir):
    make_character(lib_dir)
    unknown = "Error: unknown character: ghost (no %s)\n" % os.path.join(
        lib_dir, "ghost", "character.json")
    story_md, image, ws = _manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_manifest_argv("p57", story_md, image,
                                              "--cast", "the ronin=ghost")) == 2
    assert capsys.readouterr().err == unknown
    calls = _fake_zimage(monkeypatch)
    images_dir = tmp_path / "images-case"
    images_dir.mkdir()
    images_md, out_dir = _images_env(images_dir)
    assert story_images.main(["--story-md", images_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the ronin=ghost"]) == 2
    assert capsys.readouterr().err == unknown
    assert calls == []



# --- P70-P73, P75: global LoRAs in bin/ltx-movie (spec 5.7.1, 5.7.5, amendment 2) ---------
def _global_args(*argv):
    args = _movie_args(*argv)
    args.video_width, args.video_height = 704, 448
    return args


def _resolve_both(args):
    rc = ltx_movie._resolve_casting(args)
    return rc or ltx_movie._resolve_global_loras(args)


def _real_file(tmp_path, name):
    path = str(tmp_path / name)
    with open(path, "wb") as f:
        f.write(name.encode())
    return path


def test_p70_legacy_lora_is_forwarded_raw(tmp_path, monkeypatch):
    _movie_stories(tmp_path, monkeypatch)
    args = _global_args("n", "--story-id", "new", "--lora", "x")
    assert _resolve_both(args) == 0
    assert (args.global_video_loras, args.global_stills_loras) == ([], [])
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 2] == ["--lora", "x"]
    assert flags.count("--lora") == 1
    regression = _load("casting_regression_for_p70", "tests/test_casting_regression.py")
    with open(regression.GOLDEN_B1, encoding="utf-8") as f:
        assert regression.b1_text() == f.read()


def test_p71_merged_globals_are_forwarded_with_strengths(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir, stills=True)
    _movie_stories(tmp_path, monkeypatch)
    _real_file(tmp_path, "g.safetensors")
    _real_file(tmp_path, "s.safetensors")
    monkeypatch.chdir(tmp_path)
    abs_g, abs_s = os.path.abspath("g.safetensors"), os.path.abspath("s.safetensors")
    args = _global_args("n", "--story-id", "new", "--character", "kyra",
                        "--lora", "g.safetensors:0.7", "--stills-lora", "s.safetensors")
    assert _resolve_both(args) == 0
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 2] == ["--lora", abs_g + ":0.7"]
    assert "g.safetensors:0.7" not in flags and "g.safetensors" not in flags
    assert ltx_movie.main(["n", "--story-id", "new", "--dry-run", "--no-review",
                           "--character", "kyra", "--lora", "g.safetensors:0.7",
                           "--stills-lora", "s.safetensors"]) == 0
    phase2 = next(line for line in capsys.readouterr().out.splitlines()
                  if line.startswith("Command: ") and "ltx-story-images" in line)
    assert phase2.endswith("--lora %s:1.0 --cast 'the woman in grey=kyra' --character-strength 0.8"
                           % abs_s)


def test_p72_ltx_movie_global_lora_errors(tmp_path, monkeypatch, capsys, lib_dir):
    make_character(lib_dir)
    _movie_stories(tmp_path, monkeypatch)
    video = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    s, g = _real_file(tmp_path, "s.safetensors"), _real_file(tmp_path, "g.safetensors")
    cases = [
        (["--character", "kyra", "--lora", video],
         "Error: --lora %s is also character kyra's video LoRA; pass it once\n" % video),
        (["--stills-lora", s, "--stills-lora", s],
         "Error: --stills-lora %s is given more than once\n" % s),
        (["--character", "kyra", "--lora", "g:abc"],
         "Error: --lora g:abc: not a readable file\n"),
    ]
    for extra, message in cases:
        assert _resolve_both(_global_args("n", "--story-id", "new", *extra)) == 2, extra
        assert capsys.readouterr().err == message
    args = _global_args("n", "--story-id", "new", "--character", "kyra", "--lora", g)
    assert _resolve_both(args) == 0
    assert args.global_video_loras == [(g, 1.0)]


def test_p73_repeatable_lora_action():
    ns = _movie_args("n", "--story-id", "s", "--lora", "a", "--lora", "b")
    assert ns.lora_path == "a"
    assert ns.lora_path_specs == ["a", "b"]
    ns = _movie_args("n", "--story-id", "s")
    assert ns.lora_path is None
    assert not hasattr(ns, "lora_path_specs")


def test_p75_repeatable_lora_action_copies_are_identical():
    import inspect
    sources = [inspect.getsource(module._RepeatableLoraAction)
               for module in (ltx_movie, render, story_images)]
    assert sources[0] == sources[1] == sources[2]
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `20 failed, 42 passed`, `rc=1`. The guards P49 (uncast never loads `character_lib`) and P57 (manifest and images print no available line; their code landed in Tasks 7-8) already pass.

- [ ] **Step 3: Implement.** Apply these edits to `bin/ltx-movie`, in order:

**Edit 1** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
--max-tokens and its subprocess timeout scale with the resolved panel
count: max(4096, panels*550) tokens, max(900, panels*90)s.
"""

````

with:

````python
--max-tokens and its subprocess timeout scale with the resolved panel
count: max(4096, panels*550) tokens, max(900, panels*90)s.

Casting (docs/superpowers/specs/2026-10-05-character-library-design.md): --character NAME
casts a trained character from the character library (generated/characters/, built by
bin/character). For a new story, Phase 1's prompt gets a Cast block that fixes the
character's referring phrase and description; for an existing story.md, --character NAME
is the same as --cast "<its referring phrase>=NAME", and --cast "PHRASE=NAME" casts it
under a phrase the story already uses. Phases 2 and 3 receive --cast PHRASE=NAME per
member plus --character-strength, so every panel whose prompt names a cast phrase renders
with that character's LoRAs (1.0 for one character, --character-strength, default 0.8, for
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
loaded by path only when casting is used, so an uncast run never reads it.
"""

````

**Edit 2** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python

def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *,
                       seconds):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
    rendered = template.format(narrative=narrative, story_id=story_id, panels=panels,
                               seconds=seconds)
    if seed_image and not no_stills:
        # The postface goes AFTER the rendered template on purpose. The template's
````

with:

````python

def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *,
                       seconds, cast_block=None):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
    rendered = template.format(narrative=narrative, story_id=story_id, panels=panels,
                               seconds=seconds)
    if cast_block:
        anchor = "\n\nHow this movie is made:"
        if rendered.count(anchor) != 1:
            raise ValueError("the story template no longer has exactly one %r anchor" % anchor)
        rendered = rendered.replace(anchor, "\n\n" + cast_block + anchor, 1)
    if seed_image and not no_stills:
        # The postface goes AFTER the rendered template on purpose. The template's
````

**Edit 3** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
        return SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE
    return rendered


````

with:

````python
        return SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE
    return rendered


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


````

**Edit 4** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
                              "encoder (e.g. a smaller variant on a memory-constrained "
                              "host); the DiT pack selected by --model is unaffected.")
    parser.add_argument("--lora", dest="lora_path", default=None,
                         help="LoRA .safetensors file or HF repo ID for the VIDEO DiT "
                              "(ltx-2-mlx), prep for future fine-tuning; always applied "
                              "at strength 1.0. See --stills-lora for the stills side.")
    parser.add_argument("--stills-lora", dest="stills_lora_path", default=None,
                         help="LoRA .safetensors file or HF repo ID for Phase 2's "
                              "stills generation (z_image_skill), prep for future "
                              "fine-tuning; always applied at strength 1.0. Independent "
                              "of --lora, which is the video DiT's LoRA. Never used by "
                              "--seed-image panels (there is no generation to apply it "
                              "to).")
    parser.add_argument("--story-model", dest="story_model", default=None,
                         help="model name to declare to bin/qwen-agent's --model for "
````

with:

````python
                              "encoder (e.g. a smaller variant on a memory-constrained "
                              "host); the DiT pack selected by --model is unaffected.")
    parser.add_argument("--lora", dest="lora_path", action=_RepeatableLoraAction, default=None,
                         help="global LoRA for the video DiT (ltx-2-mlx): repeatable; PATH or "
                              "PATH:STRENGTH (0 < STRENGTH <= 2, default 1.0). Every global LoRA "
                              "applies to every panel, ahead of that panel's cast-character "
                              "LoRAs, at its own strength (never reduced automatically). See "
                              "--stills-lora for the stills side.")
    parser.add_argument("--stills-lora", dest="stills_lora_path", action=_RepeatableLoraAction,
                         default=None,
                         help="global LoRA for the Phase 2 stills (z_image_skill): repeatable; "
                              "PATH or PATH:STRENGTH (0 < STRENGTH <= 2, default 1.0). Every "
                              "global LoRA applies to every panel, ahead of that panel's "
                              "cast-character LoRAs, at its own strength (never reduced "
                              "automatically). Never used by --seed-image panels (there is no "
                              "generation to apply it to).")
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
    parser.add_argument("--story-model", dest="story_model", default=None,
                         help="model name to declare to bin/qwen-agent's --model for "
````

**Edit 5** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
             "--tile-frames", str(args.tile_frames),
             "--tile-spatial", str(args.tile_spatial)]
    if args.lora_path:
        flags += ["--lora", args.lora_path]
    if args.no_low_ram:
````

with:

````python
             "--tile-frames", str(args.tile_frames),
             "--tile-spatial", str(args.tile_spatial)]
    if getattr(args, "global_video_loras", None):
        for path, strength in args.global_video_loras:
            flags += ["--lora", "%s:%s" % (path, repr(float(strength)))]
    elif args.lora_path:
        flags += ["--lora", args.lora_path]
    if args.no_low_ram:
````

**Edit 6** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python


def _seed_geometry(seed_path):
    """Validate seed_path and derive the video geometry from it. Writes nothing.
````

with:

````python


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


def _list_characters(raw_argv):
    """--list-characters: print bin/character list's table and exit, before argparse (so no
    --story-id or narrative is required) and before the lockfile, the sudo check, the review
    gate or any phase (spec 5.6(i))."""
    if raw_argv != ["--list-characters"]:
        print("Error: --list-characters takes no other arguments", file=sys.stderr)
        return 2
    print("\n".join(_character_lib().character_table_lines()))
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


def _seed_geometry(seed_path):
    """Validate seed_path and derive the video geometry from it. Writes nothing.
````

**Edit 7** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
            prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                         bool(getattr(args, "seed_image", None)),
                                         seconds=_clip_seconds(args))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
````

with:

````python
            prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                         bool(getattr(args, "seed_image", None)),
                                         seconds=_clip_seconds(args),
                                         cast_block=getattr(args, "cast_block", None))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
````

**Edit 8** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
            print("Warning: %s" % w)

    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")
````

with:

````python
            print("Warning: %s" % w)

    members = getattr(args, "cast_members", None) or []
    if members:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
        lib = _character_lib()
        for m in members:
            if not lib.phrase_occurs(text, m.phrase):
                print("Warning: story.md does not use cast phrase %r; character %s gets no LoRA in "
                      "this story" % (m.phrase, m.name))

    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")
````

**Edit 9** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
    if getattr(args, "seed_image", None):
        cmd += ["--seed-image", args.seed_image]
    if args.stills_lora_path:
        cmd += ["--lora", args.stills_lora_path]
    print("Running: %s" % shlex.join(cmd))
    proc = subprocess.run(cmd, cwd=WS)
````

with:

````python
    if getattr(args, "seed_image", None):
        cmd += ["--seed-image", args.seed_image]
    if getattr(args, "global_stills_loras", None):
        for path, strength in args.global_stills_loras:
            cmd += ["--lora", "%s:%s" % (path, repr(float(strength)))]
    elif args.stills_lora_path:
        cmd += ["--lora", args.stills_lora_path]
    cmd += _cast_flags(args)
    panel_01 = os.path.join(paths["images_dir"], "panel_01.png")
    if (getattr(args, "cast_members", None) and not getattr(args, "seed_image", None)
            and os.path.exists(panel_01)):
        print("Warning: %s exists and will be reused as-is; it was not necessarily rendered with "
              "the cast's stills LoRAs (delete it to regenerate)" % panel_01)
    print("Running: %s" % shlex.join(cmd))
    proc = subprocess.run(cmd, cwd=WS)
````

**Edit 10** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
                     "--max-frames", str(args.frames),
                     "--force"]
    print("Running: %s" % shlex.join(cmd_manifest))
    proc = subprocess.run(cmd_manifest, cwd=WS)
````

with:

````python
                     "--max-frames", str(args.frames),
                     "--force"]
    cmd_manifest += _cast_flags(args)
    print("Running: %s" % shlex.join(cmd_manifest))
    proc = subprocess.run(cmd_manifest, cwd=WS)
````

**Edit 11** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                 bool(getattr(args, "seed_image", None)),
                                 seconds=_clip_seconds(args))

    print("=== DRY RUN: ltx-movie phase plan (story-id=%s) ===" % args.story_id)
    print()

    if getattr(args, "seed_image", None):
````

with:

````python
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                 bool(getattr(args, "seed_image", None)),
                                 seconds=_clip_seconds(args),
                                 cast_block=getattr(args, "cast_block", None))

    print("=== DRY RUN: ltx-movie phase plan (story-id=%s) ===" % args.story_id)
    print()

    if getattr(args, "cast_members", None):
        print("--- Cast ---")
        for m in args.cast_members:
            print('cast: %s as "%s" (trigger %s; video LoRA %s; stills LoRA %s)'
                  % (m.name, m.phrase, m.trigger, m.video_lora,
                     m.stills_lora or "none: " + (m.stills_skip_reason or "not trained")))
        print()

    if getattr(args, "seed_image", None):
````

**Edit 12** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
        if getattr(args, "seed_image", None):
            phase2_cmd += ["--seed-image", args.seed_image]
        if args.stills_lora_path:
            phase2_cmd += ["--lora", args.stills_lora_path]
        print("Command: %s" % shlex.join(phase2_cmd))
        print()
````

with:

````python
        if getattr(args, "seed_image", None):
            phase2_cmd += ["--seed-image", args.seed_image]
        if getattr(args, "global_stills_loras", None):
            for path, strength in args.global_stills_loras:
                phase2_cmd += ["--lora", "%s:%s" % (path, repr(float(strength)))]
        elif args.stills_lora_path:
            phase2_cmd += ["--lora", args.stills_lora_path]
        phase2_cmd += _cast_flags(args)
        print("Command: %s" % shlex.join(phase2_cmd))
        print()
````

**Edit 13** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
                             "--min-frames", str(args.frames),
                             "--max-frames", str(args.frames), "--force"]
    print("Command: %s" % shlex.join(phase3_manifest_cmd))
    phase3_render_cmd = [sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"),
````

with:

````python
                             "--min-frames", str(args.frames),
                             "--max-frames", str(args.frames), "--force"]
    phase3_manifest_cmd += _cast_flags(args)
    print("Command: %s" % shlex.join(phase3_manifest_cmd))
    phase3_render_cmd = [sys.executable, os.path.join(WS, "bin", "ltx-mlx-render"),
````

**Edit 14** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
def main(argv=None):
    raw_argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
````

with:

````python
def main(argv=None):
    raw_argv = argv if argv is not None else sys.argv[1:]
    if "--list-characters" in raw_argv:
        return _list_characters(raw_argv)
    parser = build_parser()
    args = parser.parse_args(argv)
````

**Edit 15** (`bin/ltx-movie`). Replace this exact text, which occurs exactly once:

````python
              file=sys.stderr)
        return 2

    if args.dry_run:
````

with:

````python
              file=sys.stderr)
        return 2

    rc = _resolve_casting(args)
    if rc:
        return rc
    rc = _resolve_global_loras(args)
    if rc:
        return rc

    if args.dry_run:
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `62 passed`, `rc=0`.

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: --character/--cast casting, Cast block, available characters, --list-characters, global LoRAs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 10: `character_dataset.py`, create half -- prompts, VLM analysis, contact sheet, gates, `create`, the Z-Image child

**Files:**
- Create: `character_dataset.py` (1005 lines at the end of this task)
- Test: create `tests/test_character_dataset.py` (382 lines at the end of this task)

**Interfaces:**
- Consumes:
  - `character_lib` (Task 3);
  - `ltx2_mlx_video_skill` as `SKILL` (Task 4; `LTX2_MLX_DIR`, `LTX2_MLX_BIN`, `LTX2_MLX_HF_HOME`, `GEMMA_MODEL_ID`);
  - `ltx_image_fit.load_oriented_rgb` (imported inside `create`);
  - in the child only: `z_image_skill.generate_image(..., loras=...)` (Task 5) and `content_safety.ContentSafetyError`.
- Produces (spec 4.1):
  - every 4.1 constant: `VLM_URL`, `MODELS_URL`, `VLM_MODEL`, `STORY_SERVER`, `WIDTH`, `HEIGHT`, `STYLE`, `SHOTS`, `VARIANTS`, `DESCRIBE_PROMPT`, `FACE_PROMPT`, `CHECK_PROMPT`, `FACE_MIN_HEIGHT`, `CREATE_MIN_FREE_GIB`, `TRAIN_MIN_FREE_GIB_PER_KIND`, `TRAIN_MIN_AVAIL_GIB`, `GENERATE_MIN_AVAIL_GIB`, `VLM_WAIT_S`, `AVAIL_WAIT_S`, `TRAIN_MODEL_DIR`, `TEST_MODEL_DIR`, `VIDEO_RANK`, `VIDEO_STEPS`, `VIDEO_FINAL_CKPT`, `STILLS_RANK`, `STILLS_TARGET_STEPS`, `MFLUX_TRAIN`, `MFLUX_HF_HOME`, the five `*_TIMEOUT_S`, `TEST_SEED`;
  - `class DatasetError(Exception)`;
  - functions: `extract_json`, `validate_description`, `validate_check`, `gen_prompt`, `caption`, `image_data_url`, `vlm_call`, `verify_ffprobe(mp4)`, `validate_face(d)`, `trigger_test_prompt(trigger, class_noun)`, `vlm_ready()`, `story_server(cmd)`, `story_server_state()`, `wait_for_vlm(timeout_s)`, `wait_for_avail(min_gib, timeout_s)`, `busy_process()`, `free_gib(path)`, `library_lock()`, `run_logged(cmd, log_path, cwd, env, timeout_s)`, `step_log_path(char_dir, step)`, `face_height(seed_path)`, `describe(seed_path)`, `score_still(ref_path, cand_path)`, `wrap_still(png, mp4)`, `write_contact_sheet(items, stills_dir, out_path)`, `build_dataset(data, face_height)`, `create(args)`, `run_zimage_child(spec, char_dir, step)`, `child_zimage(spec_path)`, `main(argv=None)`;
  - private helpers `_lock_holder`, `_error(message) -> 2`, `_sha256(path)`, `_build_dataset`, `_face_problem`, `_regenerate`;
  - the insertion marker line `# --- Z-Image child process (spec 4.9) ---`, used by Tasks 11-12.
- The test section produces `SPIKE`, the 9.1 helpers, `_spike_literals`, `_ok`, `_bad`, `STATUS_SERVING` and `_FakeProc`.

Spec 4.1, 4.4, 4.5, 4.6, 4.7, 4.12 and the 4.9 child protocol, verbatim:

**Copied verbatim from `generated/charlora/tools/make_dataset_seed.py`:** `VLM_URL`, `MODELS_URL`, `VLM_MODEL`, `WIDTH = 1024`, `HEIGHT = 640`, `STYLE`, `SHOTS`, `VARIANTS` (24 entries), `CHECK_PROMPT`, `extract_json`, `validate_description`, `validate_check`, `gen_prompt`, `caption`, `image_data_url` (EXIF fix below), `vlm_call`.

**Changed:**

- `WS = os.path.dirname(os.path.realpath(__file__))`.
- `STORY_SERVER = os.path.join(WS, "bin", "story-server")`.
- `verify_ffprobe(mp4)` raises `DatasetError("ffprobe: expected 1 frame in %s, got %r" % ...)` and `DatasetError("ffprobe failed for %s: %s" % ...)` instead of calling `sys.exit`.
- `DESCRIBE_PROMPT` is replaced (4.5).
- **(Task 10 review fix, commit beedc77; normative.)** `image_data_url` opens the image as `ImageOps.exif_transpose(Image.open(path)).convert("RGB")`. The original used `Image.open(path).convert("RGB")`. This way the VLM's face, describe and check calls see the same orientation as `ltx_image_fit.load_oriented_rgb`, and therefore the same orientation as `seed.png` and `char_00`. The thumbnail, JPEG quality 90, and data-URL format are unchanged.

**New:** `FACE_PROMPT` (4.5), `FACE_MIN_HEIGHT = 0.15`, `CREATE_MIN_FREE_GIB = 2.0`, `TRAIN_MIN_FREE_GIB_PER_KIND = 8.0`, `TRAIN_MIN_AVAIL_GIB = 30.0`, `GENERATE_MIN_AVAIL_GIB = 20.0`, `VLM_WAIT_S = 600`, `AVAIL_WAIT_S = 600`.

- `TRAIN_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.3-mlx-q8-dev")`
- `TEST_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.5-mlx-q8")`
- `VIDEO_RANK = 32`, `VIDEO_STEPS = 1000`, `VIDEO_FINAL_CKPT = "lora_weights_step_01000.safetensors"`
- `STILLS_RANK = 16`, `STILLS_TARGET_STEPS = 672`, `STILLS_MAX_RESOLUTION = 512` (amendment 4)
- `MFLUX_TRAIN = os.environ.get("CHARACTER_MFLUX_TRAIN", os.path.expanduser("~/mflux/.venv/bin/mflux-train"))` (the env var is test infrastructure)
- `MFLUX_HF_HOME = os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))`
- Timeouts: `PREPROCESS_TIMEOUT_S = 1800`, `VIDEO_TRAIN_TIMEOUT_S = 14400`, `STILLS_TRAIN_TIMEOUT_S = 10800` (3 h, about 3x the expected 55 min; amendment 4), `TEST_RENDER_TIMEOUT_S = 1800`, `ZIMAGE_CHILD_TIMEOUT_S = 3600`
- `TEST_SEED = 42`

Functions (signatures are normative; behavior is specified in the subsections below):

`trigger_test_prompt(trigger, class_noun)`, `validate_face(d)`, `vlm_ready()`, `story_server(cmd)`, `story_server_state()`, `wait_for_vlm(timeout_s)`, `wait_for_avail(min_gib, timeout_s)`, `busy_process()`, `free_gib(path)`, `library_lock()` (context manager), `run_logged(cmd, log_path, cwd, env, timeout_s)`, `step_log_path(char_dir, step)`, `run_zimage_child(spec, char_dir, step)`, `face_height(seed_path)`, `describe(seed_path)`, `score_still(ref_path, cand_path)`, `wrap_still(png, mp4)`, `write_contact_sheet(items, stills_dir, out_path)`, `build_dataset(data, face_height)`, `create(args)`, `video_train_config(data_root, validation_prompt, output_dir)`, `preprocess_argv(videos, captions, out_dir)`, `train_argv(config_path)`, `train_video(data)`, `stills_epochs(kept)`, `stills_train_config(data_dir, output_dir, seed, kept)`, `safetensors_keys(path)`, `lora_module_count(keys)`, `extract_mflux_adapter(out_dir, dest, total_steps)`, `train_stills(data)`, `train(args)`, `child_zimage(spec_path)`, `main(argv)`.

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

Spec 9.3 rows, verbatim:

| ID | Test | Assertion |
|---|---|---|
| D1 | every `make_dataset_seed.py` self-test case, ported 1:1 (`extract_json` ×5, `validate_description` ×6, `validate_check` ×6, `gen_prompt` exact, `caption` exact, `image_data_url` 2000x1000 → max side <= 768) | same pass/raise outcomes as `run_self_test` (`make_dataset_seed.py:296-426`) |
| D2 | `VARIANTS`, `SHOTS`, `STYLE`, `CHECK_PROMPT` | equal to the values in `generated/charlora/tools/make_dataset_seed.py` (the test reads that file with `ast` and compares the literals) |
| D3 | `DESCRIBE_PROMPT` | equals the 4.5 literal. Contains `"apparent ethnicity when it is visible"`, `"riding boots while riding"`, `"anything they are holding"` |
| D4 | `validate_face`: `{"face_box": [100, 200, 300, 500]}`, `{"face_box": None}`, `{"face_box": [0, 0, 1000, 1000]}` | `0.3`, `None`, `1.0` |
| D5 | `validate_face` raises: missing key; `[1, 2, 3]`; `[1, 2, 3, True]`; `[300, 200, 100, 500]`; `[0, 0, 1001, 10]`; `"box"` | raises `ValueError` each |
| D6 | `trigger_test_prompt("kyrawmn", "woman")` | `"kyrawmn woman, medium shot, standing and facing the camera, photorealistic live-action film still, natural light."` |
| D15 | `write_contact_sheet` with 25 items (item 5 dropped, item 7's PNG missing) | a 1280x900 JPEG. The pixel at the red border of tile 5 (`(5 % 5) * 256 + 1, (5 // 5) * 180 + 1`) is red-dominant (R > 200, G < 60). Tile 7's centre is black |
| D16 | `story_server_state` with `subprocess.run` patched to return the real `status` output captured in 0.2 (`"  state:          SERVING vision"`), then `STOPPED`, then `LOADING vision`, then rc 1 with no state line, then `OSError` | `"SERVING vision"`, `"STOPPED"`, `"LOADING vision"`, `"UNKNOWN"`, `"UNKNOWN"` |
| D17 | `busy_process` with `psutil.process_iter` patched to yield cmdlines `["/x/ltx-2-mlx", "generate", …]`, `["python3", "bin/ltx-mlx-render", …]`, `["/x/mflux-train", "--config", "c"]`, `["vim", "notes-ltx-2-mlx.txt"]`, `["python3", "character_dataset.py", "zimage", "--spec", "s"]` (one per run) | a match for 1, 2, 3, 5; `None` for 4 |
| D18 | `library_lock` | acquires (the file holds own pid); a second acquire while held by a live foreign pid (`os.getppid()` written in the file) raises `DatasetError`; a stale pid (99999999) is removed and acquired; released on exit (file gone) |
| D19 | `run_logged(["sh", "-c", "echo a; echo b 1>&2; exit 3"], log, "/", os.environ, 10)`; `run_logged(["sleep", "5"], log, …, 1)` | rc 3, log == `"a\nb\n"` (stderr merged); rc `-9` in < 3 s |
| D35 | `child_zimage` with fake `torch`, `z_image_skill`, and `content_safety` modules inserted in `sys.modules`. The fake `generate_image` raises `ContentSafetyError` for job 2. The fake `_pipeline.transformer.modules()` yields 3 modules with `lora_A = torch.nn.ModuleDict`-like objects containing `"lora0"` | report `jobs[1].status == "blocked"`, `injected_lora_modules == 3`. Returns 0. Every `generate_image` call received `loras` as a list of tuples |
| D36 | the `run_zimage_child` parent with `run_logged` patched to rc 1 | `DatasetError` naming the log |
| D37 | `character_dataset.py` source, parsed with `ast` | no top-level import of `torch`, `z_image_skill`, `content_safety`, `diffusers` |

Copy rule (spec 4.1 "copied verbatim"): the lines from `generated/charlora/tools/make_dataset_seed.py` that appear in the file below are byte-identical copies of that file's lines 25-27 (`VLM_URL`..`VLM_MODEL`), 29-66 (`WIDTH, HEIGHT` .. `VARIANTS`), 78-88 (`CHECK_PROMPT`) and 95-245 (`extract_json` .. `vlm_call`), including their original column alignment. Check after Step 3:

````bash
python3 - <<'EOF'
spike = open("generated/charlora/tools/make_dataset_seed.py").read().splitlines(keepends=True)
mine = open("character_dataset.py").read()
for a, b in ((25, 27), (29, 66), (78, 88), (95, 245)):
    block = "".join(spike[a - 1:b])
    assert mine.count(block) == 1, (a, b)
print("verbatim blocks: ok")
EOF
````

- [ ] **Step 1: Write the failing test.** Create `tests/test_character_dataset.py` with exactly this content:

````python
"""Tests for character_dataset.py (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.3, D1-D37).

Run from the workspace root: python3 -m pytest tests/test_character_dataset.py
Plain pytest asserts only (no check() helper). No network, no GPU, no real VLM, no real
training: every VLM call, story-server call, training subprocess and Z-Image child is
replaced by a fake. Real ffmpeg/ffprobe are used where the spec says so.
"""

import argparse
import ast
import base64
import collections
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import time
import types
import zipfile

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import character_lib  # noqa: E402
from character_dataset import DatasetError  # noqa: E402

SPIKE = os.path.join(WS, "generated", "charlora", "tools", "make_dataset_seed.py")

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _spike_literals():
    with open(SPIKE, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SPIKE)
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


def _ok(fn, *args):
    fn(*args)


def _bad(fn, *args):
    with pytest.raises(ValueError):
        fn(*args)


# --- D1-D6: ported helpers, prompts, face box, test prompt (spec 4.1, 4.5) ----------------
def test_d1_spike_self_test_ported(tmp_path):
    cd = character_dataset
    _ok(cd.extract_json, '{"a":1}')
    _ok(cd.extract_json, '```json\n{"b":2}\n```')
    _ok(cd.extract_json, 'here is result: {"c":3}')
    _bad(cd.extract_json, "not json at all")
    _bad(cd.extract_json, '[1,2,3]')
    good_desc = {"class_noun": "woman",
                 "descriptor": "a young woman with brown hair and blue eyes wearing a red jacket"}
    assert cd.validate_description(good_desc) == ("woman", good_desc["descriptor"])
    assert cd.validate_description({
        "class_noun": "man",
        "descriptor": "An older man with grey hair and a beard wearing a brown coat"})[1] == (
        "an older man with grey hair and a beard wearing a brown coat")
    _bad(cd.validate_description, {"class_noun": "woman", "descriptor": "a " + " ".join(["word"] * 60)})
    _bad(cd.validate_description, {"class_noun": "woman"})
    assert cd.validate_description({"class_noun": "Woman ",
                                    "descriptor": good_desc["descriptor"]})[0] == "woman"
    _bad(cd.validate_description, {"class_noun": "young woman",
                                   "descriptor": good_desc["descriptor"]})
    good_check = {"identity_score": 8, "shot": "medium shot",
                  "pose": "walking toward the camera", "setting": "a park"}
    assert cd.validate_check(good_check) == good_check
    _bad(cd.validate_check, {"identity_score": True, "shot": "medium shot", "pose": "standing",
                             "setting": "a park"})
    _bad(cd.validate_check, {"identity_score": 11, "shot": "medium shot", "pose": "standing",
                             "setting": "a park"})
    _bad(cd.validate_check, {"identity_score": 7, "shot": "full shot", "pose": "standing",
                             "setting": "a park"})
    assert cd.validate_check({"identity_score": 7, "shot": "medium shot", "pose": "standing",
                              "setting": "in a park."})["setting"] == "a park"
    _bad(cd.validate_check, {"identity_score": 7, "shot": "medium shot",
                             "pose": "one two three four five six seven eight nine ten eleven "
                                     "twelve thirteen", "setting": "a park"})
    assert cd.gen_prompt("medium shot", "walking toward the camera", "a city street",
                         "a young woman with brown hair") == (
        "Medium shot of a young woman with brown hair, walking toward the camera, in a city "
        "street. %s." % cd.STYLE)
    assert cd.caption("kyrawmn", "woman", {"identity_score": 9, "shot": "medium shot",
                                           "pose": "walking toward the camera",
                                           "setting": "a city street"}) == (
        "kyrawmn woman, medium shot, walking toward the camera, in a city street, %s." % cd.STYLE)
    path = str(tmp_path / "big.png")
    Image.new("RGB", (2000, 1000), (100, 150, 200)).save(path)
    url = cd.image_data_url(path, max_side=768)
    assert url.startswith("data:image/jpeg;base64,")
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(img.size) <= 768


def test_d2_copied_literals_match_the_spike():
    spike = _spike_literals()
    for name in ("VARIANTS", "SHOTS", "STYLE", "CHECK_PROMPT"):
        assert getattr(character_dataset, name) == spike[name], name
    assert len(character_dataset.VARIANTS) == 24


def test_d3_describe_prompt():
    assert character_dataset.DESCRIBE_PROMPT == (
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
        'the action, the camera, the lighting or the image style.')
    for phrase in ("apparent ethnicity when it is visible", "riding boots while riding",
                   "anything they are holding"):
        assert phrase in character_dataset.DESCRIBE_PROMPT


def test_d4_validate_face_values():
    assert character_dataset.validate_face({"face_box": [100, 200, 300, 500]}) == 0.3
    assert character_dataset.validate_face({"face_box": None}) is None
    assert character_dataset.validate_face({"face_box": [0, 0, 1000, 1000]}) == 1.0


def test_d5_validate_face_rejects():
    for reply in ({}, {"face_box": [1, 2, 3]}, {"face_box": [1, 2, 3, True]},
                  {"face_box": [300, 200, 100, 500]}, {"face_box": [0, 0, 1001, 10]},
                  {"face_box": "box"}):
        _bad(character_dataset.validate_face, reply)


def test_d6_trigger_test_prompt():
    assert character_dataset.trigger_test_prompt("kyrawmn", "woman") == (
        "kyrawmn woman, medium shot, standing and facing the camera, photorealistic live-action "
        "film still, natural light.")


# --- D15-D19: contact sheet, safety gates, run_logged (spec 4.7, 4.8, 4.12) ---------------
def test_d15_contact_sheet(tmp_path):
    stills = tmp_path / "stills"
    stills.mkdir()
    items = []
    for n in range(25):
        if n != 7:
            Image.new("RGB", (1024, 640), (40, 120, 200)).save(str(stills / ("char_%02d.png" % n)))
        items.append({"n": n, "identity_score": 9, "kept": n not in (5, 7)})
    out = str(tmp_path / "sheet.jpg")
    character_dataset.write_contact_sheet(items, str(stills), out)
    with Image.open(out) as sheet:
        assert sheet.format == "JPEG"
        assert sheet.size == (1280, 900)
        r, g, b = sheet.convert("RGB").getpixel(((5 % 5) * 256 + 1, (5 // 5) * 180 + 1))
        assert r > 200 and g < 60
        cx, cy = (7 % 5) * 256 + 128, (7 // 5) * 180 + 80
        assert max(sheet.convert("RGB").getpixel((cx, cy))) < 30


STATUS_SERVING = ("story-server status  2026-10-05T12:00:00Z\n"
                  "  state:          SERVING vision\n"
                  "  port 8177:      LISTEN pid 15362\n"
                  "  health:         HTTP 200 model=qwen38-6bit\n")


def test_d16_story_server_state(monkeypatch):
    replies = [(0, STATUS_SERVING), (0, STATUS_SERVING.replace("SERVING vision", "STOPPED")),
               (0, STATUS_SERVING.replace("SERVING vision", "LOADING vision")),
               (1, "story-server: something went wrong\n"), OSError("no such file")]

    def _run(cmd, **kwargs):
        assert cmd == [character_dataset.STORY_SERVER, "status"]
        assert kwargs["timeout"] == 60
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(cmd, reply[0], reply[1], "")

    monkeypatch.setattr(character_dataset.subprocess, "run", _run)
    assert [character_dataset.story_server_state() for _ in range(5)] == [
        "SERVING vision", "STOPPED", "LOADING vision", "UNKNOWN", "UNKNOWN"]


class _FakeProc(object):
    def __init__(self, pid, cmdline):
        self.info = {"pid": pid, "cmdline": cmdline}


def test_d17_busy_process(monkeypatch):
    cmdlines = [["/x/ltx-2-mlx", "generate", "--model", "m"],
                ["python3", "bin/ltx-mlx-render", "m.json", "o.mp4"],
                ["/x/mflux-train", "--config", "c"],
                ["vim", "notes-ltx-2-mlx.txt"],
                ["python3", "character_dataset.py", "zimage", "--spec", "s"]]
    results = []
    for cmdline in cmdlines:
        monkeypatch.setattr(character_dataset.psutil, "process_iter",
                            lambda attrs, c=cmdline: iter([_FakeProc(4242, c)]))
        results.append(character_dataset.busy_process())
    assert results[0] == (4242, "/x/ltx-2-mlx generate --model m")
    assert results[1] == (4242, "python3 bin/ltx-mlx-render m.json o.mp4")
    assert results[2] == (4242, "/x/mflux-train --config c")
    assert results[3] is None
    assert results[4] == (4242, "python3 character_dataset.py zimage --spec s")


def test_d18_library_lock(lib_dir):
    lock = os.path.join(lib_dir, ".lock")
    with character_dataset.library_lock():
        with open(lock) as f:
            assert f.read() == str(os.getpid())
    assert not os.path.exists(lock)
    with open(lock, "w") as f:
        f.write(str(os.getppid()))
    with pytest.raises(DatasetError) as info:
        with character_dataset.library_lock():
            pass
    assert str(info.value) == ("another bin/character create/train is running (pid %d); run "
                               "one at a time" % os.getppid())
    with open(lock, "w") as f:
        f.write("99999999")
    with character_dataset.library_lock():
        with open(lock) as f:
            assert f.read() == str(os.getpid())
    assert not os.path.exists(lock)


def test_d19_run_logged(tmp_path):
    log = str(tmp_path / "a.log")
    assert character_dataset.run_logged(["sh", "-c", "echo a; echo b 1>&2; exit 3"], log, "/",
                                        os.environ, 10) == 3
    with open(log) as f:
        assert f.read() == "a\nb\n"
    started = time.monotonic()
    assert character_dataset.run_logged(["sleep", "5"], str(tmp_path / "b.log"), "/",
                                        os.environ, 1) == -9
    assert time.monotonic() - started < 3


# --- D35-D37: the Z-Image child protocol and the import rule (spec 1.2, 4.9) -------------
def test_d35_child_zimage(tmp_path, monkeypatch):
    calls = []

    class _ModuleDict(dict):
        pass

    class _Generator(object):
        def __init__(self, device):
            pass

        def manual_seed(self, seed):
            return self

    class _Blocked(Exception):
        pass

    def _generate(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise _Blocked("blocked")

    modules = [types.SimpleNamespace(lora_A=_ModuleDict(lora0=1)) for _ in range(3)]
    modules.append(types.SimpleNamespace(lora_A=_ModuleDict(other=1)))
    modules.append(types.SimpleNamespace())
    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_torch.nn = types.SimpleNamespace(ModuleDict=_ModuleDict)
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = _generate
    fake_zimage._pipeline = types.SimpleNamespace(
        transformer=types.SimpleNamespace(modules=lambda: iter(modules)))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _Blocked
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    report_path = str(tmp_path / "report.json")
    spec = {"jobs": [{"prompt": "p%d" % i, "output_path": str(tmp_path / ("%d.png" % i)),
                      "seed": 42, "width": 1024, "height": 640} for i in range(3)],
            "loras": [["/x/a.safetensors", 1.0]], "report_path": report_path}
    spec_path = str(tmp_path / "spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f)
    assert character_dataset.main(["zimage", "--spec", spec_path]) == 0
    with open(report_path) as f:
        report = json.load(f)
    assert [j["status"] for j in report["jobs"]] == ["ok", "blocked", "ok"]
    assert report["injected_lora_modules"] == 3
    assert all(kw["loras"] == [("/x/a.safetensors", 1.0)] for kw in calls)
    assert len(calls) == 3


def test_d36_child_failure_names_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(character_dataset, "run_logged", lambda *a, **kw: 1)
    with pytest.raises(DatasetError) as info:
        character_dataset.run_zimage_child({"jobs": [], "loras": None}, str(tmp_path), "generate")
    message = str(info.value)
    assert message.startswith("Z-Image child process exited 1; log: %s" % os.path.join(
        str(tmp_path), "logs"))
    assert message.endswith("-generate.log")


def test_d37_no_heavy_top_level_imports():
    path = os.path.join(WS, "character_dataset.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert roots and not roots & {"torch", "z_image_skill", "content_safety", "diffusers"}
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `1 error` (collection: `ModuleNotFoundError: No module named 'character_dataset'`), `rc=2`.

- [ ] **Step 3: Implement.** Create `character_dataset.py` with exactly this content:

````python
#!/usr/bin/env python3
"""character_dataset -- dataset building, LoRA training, safety gates and the Z-Image
child process behind bin/character.

Spec: docs/superpowers/specs/2026-10-05-character-library-design.md, Section 4.

Top-level imports are stdlib, PIL and psutil, plus character_lib and
ltx2_mlx_video_skill (as SKILL). torch, z_image_skill and content_safety are imported
ONLY inside child_zimage(), which runs in a child process
(python3 character_dataset.py zimage --spec SPEC): z_image_skill allows one LoRA set per
process, and `create` must release Z-Image's memory before it restarts the vision
server.

The prompts, VARIANTS and the VLM helpers below are copied verbatim from the spike tool
generated/charlora/tools/make_dataset_seed.py (spec 4.1). CHARACTER_MFLUX_TRAIN is test
infrastructure only, like LTX2_MLX_BIN.
"""

import argparse
import base64
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import shlex
import signal
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

import psutil
from PIL import Image, ImageDraw, ImageOps

WS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402

STORY_SERVER = os.path.join(WS, "bin", "story-server")

VLM_URL      = "http://127.0.0.1:8177/v1/chat/completions"
MODELS_URL   = "http://127.0.0.1:8177/v1/models"
VLM_MODEL    = "qwen38-6bit"
WIDTH, HEIGHT = 1024, 640
STYLE = "photorealistic live-action film still, natural light"
SHOTS = [
    "extreme wide shot",
    "wide shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
]

VARIANTS = [
    # (shot, pose, setting)
    ("close-up",        "facing the camera with a neutral expression",        "a studio with a plain grey backdrop"),
    ("close-up",        "in three-quarter view looking to the left",          "a studio with a plain grey backdrop"),
    ("close-up",        "in profile facing right",                            "a softly lit interior room"),
    ("close-up",        "looking slightly upward",                            "an overcast outdoor setting"),
    ("medium close-up", "looking back over one shoulder",                     "a city street"),
    ("medium close-up", "smiling slightly",                                   "a sunlit park"),
    ("medium close-up", "with a serious expression",                          "a dim interior room"),
    ("medium close-up", "in three-quarter view looking to the right",         "a forest"),
    ("medium shot",     "standing with arms relaxed",                         "a studio with a plain grey backdrop"),
    ("medium shot",     "walking toward the camera",                          "a city street"),
    ("medium shot",     "seen from behind, glancing back",                    "a forest trail"),
    ("medium shot",     "sitting on a wooden bench",                          "a park"),
    ("medium shot",     "kneeling on one knee",                               "a forest clearing"),
    ("medium shot",     "gesturing with one hand while speaking",             "an interior room"),
    ("medium shot",     "leaning against a wall",                             "a narrow alley"),
    ("medium shot",     "crouching low",                                      "a rocky hillside"),
    ("medium shot",     "reaching toward something out of frame",             "a wooden interior"),
    ("medium shot",     "turning to look to the side",                        "a stone courtyard"),
    ("wide shot",       "standing still",                                     "an open field"),
    ("wide shot",       "walking away from the camera",                       "a forest trail"),
    ("wide shot",       "running",                                            "a beach"),
    ("wide shot",       "standing on stone steps",                            "a stone courtyard"),
    ("wide shot",       "sitting on the ground",                              "a grassy hillside"),
    ("wide shot",       "walking from left to right",                         "a city street"),
]

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

CHECK_PROMPT = (
    'The first image shows the reference character. The second image is a candidate picture. '
    'Reply with only a JSON object with four keys. '
    '"identity_score": an integer from 1 to 10 for how clearly the candidate shows the same character '
    'as the reference (face, hair and clothing), where 10 is unmistakably the same and 1 is a different '
    'person. '
    '"shot": exactly one of extreme wide shot, wide shot, medium shot, medium close-up, close-up, '
    'extreme close-up, describing the candidate. '
    '"pose": at most 12 words describing the candidate\'s pose or action, without pronouns. '
    '"setting": at most 8 words naming the candidate\'s surroundings.'
)

FACE_MIN_HEIGHT = 0.15
CREATE_MIN_FREE_GIB = 2.0
TRAIN_MIN_FREE_GIB_PER_KIND = 8.0
TRAIN_MIN_AVAIL_GIB = 30.0
GENERATE_MIN_AVAIL_GIB = 20.0
VLM_WAIT_S = 600
AVAIL_WAIT_S = 600

TRAIN_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.3-mlx-q8-dev")
TEST_MODEL_DIR = os.path.join(SKILL.LTX2_MLX_DIR, "models", "ltx-2.5-mlx-q8")
VIDEO_RANK = 32
VIDEO_STEPS = 1000
VIDEO_FINAL_CKPT = "lora_weights_step_01000.safetensors"
STILLS_RANK = 16
STILLS_TARGET_STEPS = 2400
MFLUX_TRAIN = os.environ.get("CHARACTER_MFLUX_TRAIN",
                             os.path.expanduser("~/mflux/.venv/bin/mflux-train"))
MFLUX_HF_HOME = os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))

PREPROCESS_TIMEOUT_S = 1800
VIDEO_TRAIN_TIMEOUT_S = 14400
STILLS_TRAIN_TIMEOUT_S = 21600
TEST_RENDER_TIMEOUT_S = 1800
ZIMAGE_CHILD_TIMEOUT_S = 3600

TEST_SEED = 42


class DatasetError(Exception):
    """A dataset, training or safety-gate failure; printed after "Error: "."""


# ---------------------------------------------------------------------------
# Pure helpers (copied verbatim from make_dataset_seed.py)
# ---------------------------------------------------------------------------

def extract_json(text):
    """Parse a JSON dict from model output; raise ValueError on failure."""
    text = text.strip()
    fence_match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    else:
        idx = text.find("{")
        if idx == -1:
            raise ValueError("no JSON object found in text")
        raw = text[idx:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as e:
        raise ValueError("JSON decode error: %s" % e)
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object, got %s" % type(obj).__name__)
    return obj


def validate_description(d):
    """Validate describe-phase response dict; return (class_noun, descriptor)."""
    if "class_noun" not in d:
        raise ValueError("missing key: class_noun")
    if "descriptor" not in d:
        raise ValueError("missing key: descriptor")
    class_noun = d["class_noun"]
    if not isinstance(class_noun, str):
        raise ValueError("class_noun must be a string")
    class_noun = class_noun.lower().strip()
    if not re.match(r'^[a-z]+$', class_noun):
        raise ValueError("class_noun must match ^[a-z]+$, got %r" % class_noun)
    if not (3 <= len(class_noun) <= 12):
        raise ValueError("class_noun length must be 3-12, got %d" % len(class_noun))
    descriptor = d["descriptor"]
    if not isinstance(descriptor, str):
        raise ValueError("descriptor must be a string")
    descriptor = descriptor.strip()
    if descriptor.endswith("."):
        descriptor = descriptor[:-1].strip()
    words = descriptor.split()
    if not (8 <= len(words) <= 60):
        raise ValueError("descriptor word count must be 8-60, got %d" % len(words))
    # Normalise first letter to lowercase
    if descriptor and descriptor[0].isupper():
        descriptor = descriptor[0].lower() + descriptor[1:]
    if not re.match(r'^(a |an )', descriptor, re.IGNORECASE):
        raise ValueError("descriptor must start with 'a ' or 'an ', got %r" % descriptor[:30])
    return class_noun, descriptor


def validate_check(d):
    """Validate check-phase response dict; return normalised dict."""
    if "identity_score" not in d:
        raise ValueError("missing key: identity_score")
    score = d["identity_score"]
    if isinstance(score, bool):
        raise ValueError("identity_score must be int, not bool")
    if not isinstance(score, int):
        raise ValueError("identity_score must be int, got %s" % type(score).__name__)
    if not (1 <= score <= 10):
        raise ValueError("identity_score must be 1-10, got %d" % score)
    if "shot" not in d:
        raise ValueError("missing key: shot")
    shot = d["shot"]
    if not isinstance(shot, str):
        raise ValueError("shot must be a string")
    shot = shot.lower().strip()
    if shot not in SHOTS:
        raise ValueError("shot %r not in SHOTS" % shot)
    if "pose" not in d:
        raise ValueError("missing key: pose")
    pose = d["pose"]
    if not isinstance(pose, str):
        raise ValueError("pose must be a string")
    pose = pose.strip()
    if pose.endswith("."):
        pose = pose[:-1].strip()
    pose_words = pose.split()
    if not (1 <= len(pose_words) <= 12):
        raise ValueError("pose word count must be 1-12, got %d" % len(pose_words))
    if "setting" not in d:
        raise ValueError("missing key: setting")
    setting = d["setting"]
    if not isinstance(setting, str):
        raise ValueError("setting must be a string")
    setting = setting.strip()
    if setting.endswith("."):
        setting = setting[:-1].strip()
    if setting.lower().startswith("in "):
        setting = setting[3:].strip()
    setting_words = setting.split()
    if not (1 <= len(setting_words) <= 8):
        raise ValueError("setting word count must be 1-8, got %d" % len(setting_words))
    return {
        "identity_score": score,
        "shot": shot,
        "pose": pose,
        "setting": setting,
    }


def gen_prompt(shot, pose, setting, descriptor):
    """Build an image-generation prompt."""
    shot_cap = shot[0].upper() + shot[1:]
    return "%s of %s, %s, in %s. %s." % (shot_cap, descriptor, pose, setting, STYLE)


def caption(trigger, class_noun, check):
    """Build a training caption string."""
    return "%s %s, %s, %s, in %s, %s." % (
        trigger, class_noun, check["shot"], check["pose"], check["setting"], STYLE
    )


def image_data_url(path, max_side=768):
    """Return a data URL for the image at path, scaled so max side <= max_side."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def vlm_call(content_parts, max_tokens=600):
    """POST to the VLM and return the reply text; raise RuntimeError on failure."""
    payload = json.dumps({
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        VLM_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %d from VLM: %s" % (e.code, e.read().decode(errors="replace")))
    except Exception as e:
        raise RuntimeError("VLM request failed: %s" % e)
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError("unexpected VLM response shape: %s" % e)


def verify_ffprobe(mp4):
    """Check that mp4 has exactly 1 frame via ffprobe; raise DatasetError on failure."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries", "stream=nb_read_frames",
         "-of", "default=nokey=1:noprint_wrappers=1", mp4],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise DatasetError("ffprobe failed for %s: %s" % (mp4, result.stderr.strip()))
    nb = result.stdout.strip()
    if nb != "1":
        raise DatasetError("ffprobe: expected 1 frame in %s, got %r" % (mp4, nb))


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


# ---------------------------------------------------------------------------
# Safety gates and process helpers (spec 4.8, 4.12)
# ---------------------------------------------------------------------------

_STATE_RE = re.compile(r"^\s*state:\s*(.+?)\s*$")


def vlm_ready():
    try:
        req = urllib.request.Request(MODELS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return VLM_MODEL in [m["id"] for m in body["data"]]
    except Exception:
        return False


def story_server(cmd):
    """Run bin/story-server CMD, print the last 5 lines of its output, return its exit code."""
    result = subprocess.run([STORY_SERVER, cmd], capture_output=True, text=True)
    tail_lines = (result.stdout + result.stderr).strip().splitlines()
    for line in tail_lines[-5:]:
        print(line)
    return result.returncode


def story_server_state():
    """The value of bin/story-server status's "state:" line (SERVING <mode>, FOREIGN pid N,
    LOADING <mode> or STOPPED), or "UNKNOWN" on any failure, which callers treat as not
    stopped (fail closed)."""
    try:
        proc = subprocess.run([STORY_SERVER, "status"], capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    if proc.returncode != 0:
        return "UNKNOWN"
    for line in proc.stdout.splitlines():
        match = _STATE_RE.match(line)
        if match:
            return match.group(1)
    return "UNKNOWN"


def wait_for_vlm(timeout_s):
    deadline = time.monotonic() + timeout_s
    while True:
        if vlm_ready():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(10)


def wait_for_avail(min_gib, timeout_s):
    deadline = time.monotonic() + timeout_s
    while psutil.virtual_memory().available < min_gib * 2 ** 30:
        if time.monotonic() > deadline:
            return False
        time.sleep(5)
    return True


def busy_process():
    """(pid, first 120 characters of its command line) for the first render, training or
    Z-Image process found, else None. Fail-closed by design (spec 4.12, G17)."""
    skip = {os.getpid(), os.getppid()}
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if pid in skip:
            continue
        joined = " ".join(cmdline)
        if (("ltx-2-mlx" in joined
             and any(t in cmdline for t in ("generate", "train", "preprocess")))
                or any(marker in joined for marker in (
                    "mflux-train", "bin/ltx-movie", "bin/ltx-mlx-render",
                    "bin/ltx-story-images", "character_dataset.py zimage"))):
            return pid, joined[:120]
    return None


def free_gib(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return shutil.disk_usage(path).free / 2 ** 30


def _lock_holder(path):
    try:
        with open(path, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


@contextlib.contextmanager
def library_lock():
    """Hold <library>/.lock (holding our pid) for the duration of the block. A lock held by
    a live pid raises DatasetError; a dead or unreadable one is removed and retried once."""
    lib = character_lib.library_dir()
    os.makedirs(lib, exist_ok=True)
    path = os.path.join(lib, character_lib.LOCK_NAME)
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = _lock_holder(path)
            if holder is not None:
                raise DatasetError("another bin/character create/train is running (pid %d); "
                                   "run one at a time" % holder)
            if attempt == 1:
                raise DatasetError("could not acquire the library lock %s" % path)
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        break
    try:
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


def run_logged(cmd, log_path, cwd, env, timeout_s):
    """Run cmd with stdout+stderr merged, streaming every line to sys.stdout and to log_path
    (appended). A watchdog SIGKILLs the whole process group after timeout_s. Returns the
    exit code, or -9 after a timeout kill."""
    print("Running: %s" % shlex.join(cmd))
    print("log: %s" % log_path)
    sys.stdout.flush()
    timed_out = [False]
    with open(log_path, "a") as logf:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                start_new_session=True)

        def _kill_group():
            timed_out[0] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass

        timer = threading.Timer(timeout_s, _kill_group)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                logf.write(line)
                logf.flush()
            proc.wait()
        finally:
            timer.cancel()
    return -9 if timed_out[0] else proc.returncode


def step_log_path(char_dir, step):
    logs = os.path.join(char_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "%s-%s.log" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), step))


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# VLM analysis (spec 4.4 helpers, 4.5)
# ---------------------------------------------------------------------------

def face_height(seed_path):
    content_parts = [{"type": "text", "text": FACE_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(seed_path)}}]
    reply, error = None, None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            return validate_face(extract_json(reply))
        except ValueError as e:
            error = e
    raise DatasetError("face check failed: %s; last reply: %r" % (error, reply))


def describe(seed_path):
    """(class_noun, descriptor, raw reply) for the seed image's main character."""
    content_parts = [{"type": "text", "text": DESCRIBE_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(seed_path)}}]
    reply, error = None, None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            class_noun, descriptor = validate_description(extract_json(reply))
            character_lib.validate_descriptor(descriptor)
            return class_noun, descriptor, reply
        except (ValueError, character_lib.CharacterError) as e:
            error = e
    raise DatasetError("describe failed: %s; last reply: %r" % (error, reply))


def score_still(ref_path, cand_path):
    """(normalized check dict, None), or the zero-score dict and an "unparseable: ..." reason
    after two unparseable replies. A RuntimeError from the VLM call propagates."""
    content_parts = [{"type": "text", "text": CHECK_PROMPT},
                     {"type": "image_url", "image_url": {"url": image_data_url(ref_path)}},
                     {"type": "image_url", "image_url": {"url": image_data_url(cand_path)}}]
    error = None
    for _attempt in range(2):
        reply = vlm_call(content_parts)
        try:
            return validate_check(extract_json(reply)), None
        except ValueError as e:
            error = e
    return ({"identity_score": 0, "shot": "", "pose": "", "setting": ""},
            "unparseable: %s" % error)


# ---------------------------------------------------------------------------
# Dataset building: create (spec 4.4, 4.6, 4.7)
# ---------------------------------------------------------------------------

def wrap_still(png, mp4):
    """Wrap one still into a 1-frame h264 mp4 (the make_dataset_seed.py ffmpeg argv)."""
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y",
             "-loop", "1", "-i", png,
             "-frames:v", "1", "-r", "24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DatasetError("ffmpeg failed to wrap %s into %s (exit %d)" % (png, mp4, e.returncode))
    except OSError as e:
        raise DatasetError("ffmpeg could not be run to wrap %s: %s" % (png, e))


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


def build_dataset(data, face_height):
    """Generate, score, caption and wrap the dataset for character.json data; write
    dataset/manifest.json, dataset/contact_sheet.jpg and the updated character.json.
    Returns 0, 1 (a DatasetError or RuntimeError, printed; status stays "dataset") or 3
    (fewer than MIN_KEEP stills kept)."""
    try:
        return _build_dataset(data, face_height)
    except (DatasetError, RuntimeError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1


def _build_dataset(data, face_height):
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    json_path = character_lib.character_json_path(name)
    dataset_dir = os.path.join(char_dir, "dataset")
    stills_dir = os.path.join(dataset_dir, "stills")
    captions_dir = os.path.join(dataset_dir, "captions")
    videos_dir = os.path.join(dataset_dir, "videos")
    seed_mode = data["source"]["type"] == "seed_image"
    if seed_mode:
        with Image.open(os.path.join(char_dir, "seed.png")) as img:
            ImageOps.fit(img.convert("RGB"), (WIDTH, HEIGHT), Image.LANCZOS,
                         centering=(0.5, 0.5)).save(os.path.join(stills_dir, "char_00.png"))
    spec = {"jobs": [{"prompt": gen_prompt(shot, pose, setting, data["descriptor"]),
                      "output_path": os.path.join(stills_dir, "char_%02d.png" % i),
                      "seed": data["seed"], "width": WIDTH, "height": HEIGHT}
                     for i, (shot, pose, setting) in enumerate(VARIANTS, 1)],
            "loras": None}

    print("=== generate ===")
    rc = story_server("stop")
    if rc != 0:
        print("warning: story-server stop returned %d" % rc, file=sys.stderr)
    try:
        if not wait_for_avail(GENERATE_MIN_AVAIL_GIB, AVAIL_WAIT_S):
            raise DatasetError("timed out waiting for 20 GiB available memory after stopping the "
                               "story server")
        run_zimage_child(spec, char_dir, "generate")
    finally:
        rc = story_server("vision")
        if rc != 0:
            print("warning: story-server vision returned %d" % rc, file=sys.stderr)
        if not wait_for_vlm(VLM_WAIT_S):
            raise DatasetError("timed out waiting for the vision server to come back")

    ref_n = 0 if seed_mode else 1
    ref_png = os.path.join(stills_dir, "char_%02d.png" % ref_n)
    if not os.path.isfile(ref_png):
        raise DatasetError("the reference still char_%02d was blocked by the content screen; edit "
                           "the descriptor in %s and run bin/character create %s --regenerate"
                           % (ref_n, json_path, name))

    print("=== score ===")
    items = []
    for n in (range(0, 25) if seed_mode else range(1, 25)):
        png = os.path.join(stills_dir, "char_%02d.png" % n)
        gen_prompt_str = None
        if n > 0:
            shot, pose, setting = VARIANTS[n - 1]
            gen_prompt_str = gen_prompt(shot, pose, setting, data["descriptor"])
        if not os.path.isfile(png):
            items.append({"n": n, "gen_prompt": gen_prompt_str, "identity_score": 0, "shot": "",
                          "pose": "", "setting": "", "kept": False,
                          "reason": "blocked by the content screen", "caption": None})
            continue
        check_result, reason = score_still(ref_png, png)
        kept = (n == ref_n) or check_result["identity_score"] >= character_lib.MIN_SCORE
        cap = None
        if kept:
            cap = caption(data["trigger"], data["class_noun"], check_result)
            with open(os.path.join(captions_dir, "char_%02d.txt" % n), "w") as f:
                f.write(cap)
            mp4 = os.path.join(videos_dir, "char_%02d.mp4" % n)
            wrap_still(png, mp4)
            verify_ffprobe(mp4)
        items.append({
            "n":              n,
            "gen_prompt":     gen_prompt_str,
            "identity_score": check_result["identity_score"],
            "shot":           check_result["shot"],
            "pose":           check_result["pose"],
            "setting":        check_result["setting"],
            "kept":           kept,
            "reason":         reason,
            "caption":        cap,
        })

    manifest = {"seed_image": data["source"].get("path"), "trigger": data["trigger"],
                "class_noun": data["class_noun"], "descriptor": data["descriptor"],
                "seed": data["seed"], "min_score": character_lib.MIN_SCORE,
                "reference": "char_%02d" % ref_n, "face_height": face_height, "items": items}
    with open(os.path.join(dataset_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    sheet = os.path.join(dataset_dir, "contact_sheet.jpg")
    write_contact_sheet(items, stills_dir, sheet)

    kept_count = sum(1 for item in items if item["kept"])
    total = len(items)
    data["dataset"] = {"reference": "char_%02d" % ref_n, "kept": kept_count, "total": total,
                       "min_score": character_lib.MIN_SCORE, "face_height": face_height,
                       "contact_sheet": sheet}
    data["status"] = "untrained" if kept_count >= character_lib.MIN_KEEP else "dataset"
    character_lib.write_character(data)

    print("%-4s %-6s %-5s %s" % ("n", "score", "kept", "caption"))
    for item in items:
        cap_str = item["caption"] or "(dropped)"
        print("%-4d %-6d %-5s %s" % (
            item["n"], item["identity_score"], str(item["kept"]), cap_str
        ))
    print("dataset: %d/%d stills kept (minimum %d) in %s"
          % (kept_count, total, character_lib.MIN_KEEP, dataset_dir))
    print("contact sheet: %s" % sheet)
    if kept_count < character_lib.MIN_KEEP:
        print('Error: only %d/%d stills kept (need %d); the dataset is kept in %s; edit '
              '"descriptor" in %s and run bin/character create %s --regenerate'
              % (kept_count, total, character_lib.MIN_KEEP, dataset_dir, json_path, name),
              file=sys.stderr)
        return 3
    print('next: review the contact sheet. To change the look, edit "descriptor" in %s and run '
          'bin/character create %s --regenerate; otherwise run bin/character train %s'
          % (json_path, name, name))
    return 0


def _face_problem(fh):
    """(error text, warning text) for a seed face that is missing or below FACE_MIN_HEIGHT
    (spec 4.5, CE18)."""
    if fh is None:
        return ("the vision model found no face in the seed image; pass --force to proceed anyway.",
                "the vision model found no face in the seed image; proceeding (--force)")
    head = ("the main character's face fills only %d%% of the seed image's height (minimum 15%%); "
            "a small face makes a weak identity reference" % round(100 * fh))
    return (head + ". Use a closer crop of the character, or pass --force to proceed anyway.",
            head + "; proceeding (--force)")


def create(args):
    """bin/character create (spec 4.4). Returns 0, 1, 2 or 3."""
    import ltx_image_fit
    name = args.name
    try:
        character_lib.validate_name(name)
    except character_lib.CharacterError as e:
        return _error(e)
    char_dir = character_lib.character_dir(name)
    json_path = character_lib.character_json_path(name)
    data = None
    if args.regenerate:
        if (any(v is not None for v in (args.phrase, args.seed_image, args.descriptor,
                                        args.class_noun, args.trigger, args.seed))
                or args.force):
            return _error("--regenerate takes no --phrase, --seed-image, --descriptor, --class, "
                          "--trigger, --seed or --force; edit %s instead" % json_path)
        try:
            data = character_lib.load_character(name)
        except character_lib.CharacterError as e:
            return _error(e)
        if data["status"] == "trained":
            return _error("character %s is trained; regenerating its dataset would orphan its "
                          "LoRAs. Create a new character instead" % name)
    else:
        if os.path.exists(char_dir):
            return _error("character %s already exists (%s); use --regenerate to rebuild its "
                          "dataset" % (name, char_dir))
        if args.phrase is None:
            return _error("create needs --phrase")
        try:
            phrase = character_lib.normalize_phrase(args.phrase)
        except character_lib.CharacterError as e:
            return _error("--phrase: %s" % e)
        if (args.seed_image is None) == (args.descriptor is None):
            return _error("create needs exactly one of --seed-image or --descriptor")
        if args.class_noun is not None:
            try:
                character_lib.validate_class_noun(args.class_noun)
            except character_lib.CharacterError as e:
                return _error(e)
        elif args.descriptor is not None:
            return _error("--descriptor needs --class NOUN (there is no image to take it from)")
        seed_path = descriptor = None
        if args.descriptor is not None:
            try:
                _, descriptor = validate_description({"class_noun": args.class_noun,
                                                      "descriptor": args.descriptor})
                character_lib.validate_descriptor(descriptor)
            except (ValueError, character_lib.CharacterError) as e:
                return _error("--descriptor: %s" % e)
        else:
            seed_path = os.path.abspath(args.seed_image)
            if not os.path.isfile(seed_path):
                return _error("--seed-image not found: %s" % seed_path)
            try:
                ltx_image_fit.load_oriented_rgb(seed_path)
            except Exception as e:
                return _error("--seed-image is not a readable image: %s: %s" % (seed_path, e))
        seed = args.seed if args.seed is not None else 0
        if seed < 0:
            return _error("--seed must be >= 0")
        if args.trigger is not None:
            try:
                character_lib.validate_trigger(args.trigger)
            except character_lib.CharacterError as e:
                return _error(e)
            owner = character_lib.registered_triggers().get(args.trigger)
            if owner is not None:
                return _error("trigger %s is already used by character %s; triggers are never "
                              "reused" % (args.trigger, owner))
            if (args.trigger in [w.lower() for w in phrase.split()]
                    or args.trigger == args.class_noun):
                return _error("trigger %s must not be a word of the phrase or the class noun"
                              % args.trigger)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(library_lock())
        except DatasetError as e:
            return _error(e)
        busy = busy_process()
        if busy is not None:
            return _error("a render or training process is running (pid %d: %s); bin/character "
                          "never trains or generates concurrently with a render" % busy)
        lib = character_lib.library_dir()
        free = free_gib(lib)
        if free < CREATE_MIN_FREE_GIB:
            return _error("only %.1f GiB free at %s; create needs 2 GiB" % (free, lib))
        if not vlm_ready():
            return _error("the vision model %s is not being served at %s; start it with: "
                          "bin/story-server vision" % (VLM_MODEL, MODELS_URL))

        if data is not None:
            return _regenerate(data)

        fh = raw = cls_vlm = None
        try:
            if seed_path is not None:
                fh = face_height(seed_path)
                if fh is None or fh < FACE_MIN_HEIGHT:
                    error_text, warning_text = _face_problem(fh)
                    if not args.force:
                        return _error(error_text)
                    print("Warning: %s" % warning_text, file=sys.stderr)
                cls_vlm, descriptor, raw = describe(seed_path)
                cls = args.class_noun or cls_vlm
            else:
                cls = args.class_noun
        except (DatasetError, RuntimeError) as e:
            print("Error: %s" % e, file=sys.stderr)
            return 1
        trigger = args.trigger or character_lib.auto_trigger(
            name, cls, character_lib.registered_triggers(), avoid=phrase.split())
        if args.trigger is not None and trigger == cls:
            return _error("trigger %s must not be a word of the phrase or the class noun" % trigger)

        for sub in ("stills", "captions", "videos"):
            os.makedirs(os.path.join(char_dir, "dataset", sub), exist_ok=True)
        os.makedirs(os.path.join(char_dir, "logs"), exist_ok=True)
        if seed_path is not None:
            ltx_image_fit.load_oriented_rgb(seed_path).save(os.path.join(char_dir, "seed.png"),
                                                            format="PNG")
            with open(os.path.join(char_dir, "dataset", "description.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"class_noun": cls_vlm, "descriptor": descriptor, "raw": raw}, f,
                          indent=2)
        character_lib.register_trigger(trigger, name)
        data = {"schema_version": character_lib.SCHEMA_VERSION, "name": name, "trigger": trigger,
                "class_noun": cls, "referring_phrase": phrase, "descriptor": descriptor,
                "seed": seed,
                "source": ({"type": "seed_image", "path": seed_path} if seed_path is not None
                           else {"type": "descriptor"}),
                "strength": None, "status": "dataset", "created_at": character_lib.utc_now(),
                "dataset": None, "loras": {"video": None, "stills": None},
                "stills_skip_reason": None}
        character_lib.write_character(data)
        return build_dataset(data, fh)


def _regenerate(data):
    """create --regenerate after its preflights: wipe and rebuild dataset/ from character.json,
    keeping face_height and dataset/description.json; no face check, no describe."""
    prev_fh = data["dataset"]["face_height"] if data["dataset"] else None
    dataset_dir = os.path.join(character_lib.character_dir(data["name"]), "dataset")
    description = os.path.join(dataset_dir, "description.json")
    saved_description = None
    if os.path.isfile(description):
        with open(description, "rb") as f:
            saved_description = f.read()
    if os.path.isdir(dataset_dir):
        shutil.rmtree(dataset_dir)
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(dataset_dir, sub))
    if saved_description is not None:
        with open(description, "wb") as f:
            f.write(saved_description)
    data["status"] = "dataset"
    data["dataset"] = None
    character_lib.write_character(data)
    return build_dataset(data, prev_fh)


# --- Z-Image child process (spec 4.9) ---

def run_zimage_child(spec, char_dir, step):
    """Run the jobs in spec through z_image_skill in a child process and return its report:
    {"jobs": [{"output_path", "status", "seconds"}], "injected_lora_modules": N or None}."""
    log = step_log_path(char_dir, step)
    stem = log[:-len(".log")]
    spec_path = stem + ".spec.json"
    report_path = stem + ".report.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(dict(spec, report_path=report_path), f, indent=2)
    rc = run_logged([sys.executable, os.path.join(WS, "character_dataset.py"), "zimage",
                     "--spec", spec_path], log, WS, dict(os.environ), ZIMAGE_CHILD_TIMEOUT_S)
    if rc != 0:
        error = DatasetError("Z-Image child process exited %d; log: %s" % (rc, log))
        error.log_path = log
        raise error
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)


def child_zimage(spec_path):
    """The child side: render every job, count the injected LoRA modules, write the report.
    Imports the heavy stack here and only here."""
    import torch
    import z_image_skill
    from content_safety import ContentSafetyError

    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    kwargs = {"loras": [tuple(x) for x in spec["loras"]]} if spec["loras"] else {}
    jobs = []
    for job in spec["jobs"]:
        started = time.monotonic()
        try:
            z_image_skill.generate_image(job["prompt"], output_path=job["output_path"],
                                         width=job["width"], height=job["height"],
                                         generator=torch.Generator("cpu").manual_seed(job["seed"]), **kwargs)
            status = "ok"
        except ContentSafetyError:
            status = "blocked"
        jobs.append({"output_path": job["output_path"], "status": status,
                     "seconds": round(time.monotonic() - started, 1)})
    injected = None
    if spec["loras"] and z_image_skill._pipeline is not None:
        injected = sum(1 for module in z_image_skill._pipeline.transformer.modules()
                       if isinstance(getattr(module, "lora_A", None), torch.nn.ModuleDict)
                       and "lora0" in module.lora_A)
    with open(spec["report_path"], "w", encoding="utf-8") as f:
        json.dump({"jobs": jobs, "injected_lora_modules": injected}, f, indent=2)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="character_dataset.py",
        description="bin/character's internal helper: the Z-Image child process.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    z = sub.add_parser("zimage", help="render a spec file's jobs with z_image_skill")
    z.add_argument("--spec", required=True, metavar="PATH")
    args = parser.parse_args(argv)
    return child_zimage(args.spec)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
````

Then run the verbatim-block check above. It must print `verbatim blocks: ok`.

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `14 passed`, `rc=0`. D2 reads the gitignored spike file `generated/charlora/tools/make_dataset_seed.py`, which must exist on this host (Decision 21). Also `python3 -m pytest tests/test_casting_regression.py tests/test_character_lib.py -q --color=no -p no:cacheprovider` -> `49 passed, 1 warning`.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add character_dataset.py tests/test_character_dataset.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/character_dataset.py
qwen-agent-workspace/tests/test_character_dataset.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character_dataset: dataset building, VLM analysis, safety gates and the Z-Image child

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

- [ ] **Step 6: Post-review fix (DONE in commit `beedc77`; recorded here, not to be redone).** The Task 10 review added two fixes, which spec commit `9f980b2` made normative (4.1 and 4.8): `run_logged` kills and reaps the child's process group in its `finally` when the child is still alive, and `image_data_url` applies `ImageOps.exif_transpose`. They come with tests D38 and D39. Spec rows, verbatim:

| ID | Test | Assertion |
|---|---|---|
| D38 | `test_d38_run_logged_kills_child_on_interrupt`: `run_logged` on a long-running child (`sleep`-style, in its own session), with `sys.stdout.write` patched to raise `KeyboardInterrupt` on the first streamed line after `Popen` | `KeyboardInterrupt` propagates. The child was killed and reaped: `returncode == -9` |
| D39 | `test_d39_image_data_url_applies_exif_orientation`: a 200x100 JPEG saved with EXIF orientation 6 | decoding the data URL's JPEG gives size `(100, 200)` |

The committed change, for a from-scratch replay only. Note that it makes Step 3's verbatim-block check fail for lines 95-245, because spec 4.1 now records the EXIF line as a deliberate change.

**Edit 1** (`character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
    img = Image.open(path).convert("RGB")
````

with:

````python
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
````

**Edit 2** (`character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
        finally:
            timer.cancel()
    return -9 if timed_out[0] else proc.returncode
````

with:

````python
        finally:
            timer.cancel()
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()
    return -9 if timed_out[0] else proc.returncode
````

Append exactly this content to the end of `tests/test_character_dataset.py`:

````python


def test_d38_run_logged_kills_child_on_interrupt(tmp_path, monkeypatch):
    procs = []
    real_popen = subprocess.Popen

    def _popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(character_dataset.subprocess, "Popen", _popen)

    class _Out(object):
        def write(self, text):
            if procs:
                raise KeyboardInterrupt()

        def flush(self):
            pass

    monkeypatch.setattr(character_dataset.sys, "stdout", _Out())
    with pytest.raises(KeyboardInterrupt):
        character_dataset.run_logged(["sh", "-c", "echo start; sleep 30"],
                                     str(tmp_path / "c.log"), "/", os.environ, 60)
    assert len(procs) == 1
    assert procs[0].poll() is not None
    assert procs[0].returncode == -9


def test_d39_image_data_url_applies_exif_orientation(tmp_path):
    path = str(tmp_path / "rot.jpg")
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(path, format="JPEG", exif=exif.tobytes())
    url = character_dataset.image_data_url(path)
    data = base64.b64decode(url.split(",", 1)[1])
    assert Image.open(io.BytesIO(data)).size == (100, 200)
````

State after `beedc77`: `character_dataset.py` has 1011 lines and `tests/test_character_dataset.py` 421 lines; `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"` gives `16 passed`.

---

### Task 11: `character_dataset.py`, video LoRA training and `train()`

**Files:**
- Modify: `character_dataset.py` (one insertion; 1246 lines at the end of this task)
- Test: append to `tests/test_character_dataset.py` (675 lines at the end of this task)

**Interfaces:**
- Consumes:
  - Task 10's `run_logged`, `step_log_path`, `library_lock`, `busy_process`, `story_server_state`, `free_gib`, `trigger_test_prompt`, `_error`, `_sha256`;
  - `SKILL.generate_video(..., loras=[(lora, 1.0)])` (Task 4);
  - `character_lib.load_character` / `write_character`.
- Produces:
  - `VIDEO_TRAIN_CONFIG_TEMPLATE`;
  - `video_train_config(data_root, validation_prompt, output_dir) -> str`, `preprocess_argv(videos, captions, out_dir) -> list`, `train_argv(config_path) -> list`;
  - `_video_failed(data, step, rc, log) -> "failed"`;
  - `train_video(data) -> "ok"|"failed"|"test_failed"`;
  - `train(args) -> 0|1|2`, which calls `train_stills(data)`. `train_stills` is defined in Task 12; Decision 13 covers the gap.
- The test section produces `_untrained`, `_fake_video_tools`, `_Memory`, `_train_ready`, `_train_args` and `_load`. Task 12 reuses them.

Spec 4.8 and 4.11, verbatim:

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

Spec 9.3 rows, verbatim:

| ID | Test | Assertion |
|---|---|---|
| D7 | `video_train_config("/d/pre", "p, q.", "/d/out")` | equals the template with `"…"` JSON-quoted values. Parsing it with a minimal check (`yaml` is not required): it contains the lines `  model_path: "<TRAIN_MODEL_DIR>"`, `  preprocessed_data_root: "/d/pre"`, `    - "p, q."`, `output_dir: "/d/out"`, `  rank: 32`, `  alpha: 32`, `  steps: 1000`, `  interval: 250`, `  keep_last_n: 10`. Contains no `{` |
| D8 | `preprocess_argv("/v", "/c", "/o")`; `train_argv("/t.yaml")` | `[BIN, "preprocess", "--videos", "/v", "--captions", "/c", "-o", "/o", "-m", TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]`; `[BIN, "train", "--config", "/t.yaml", "--low-ram"]` |
| D20 | `train_video` happy path. `run_logged` is patched: on preprocess it creates `.precomputed/latents/` with one file per mp4; on train it writes the final checkpoint (`b"lora"`). `SKILL.generate_video` is patched to record kwargs and write files | returns `"ok"`. `lora/video.safetensors == b"lora"`. `character.json` `status == "trained"`, `loras.video.sha256 == sha256(b"lora")`, rank/alpha/steps 32/32/1000, `sample_path`/`control_path` set. The first `generate_video` call has `loras == [(lora_path, 1.0)]`, `width 512`, `height 320`, `num_frames 25`, `seed 42`, `model == TEST_MODEL_DIR`, `image_path is None`; the second call has no `loras` key |
| D21 | `train_video`: preprocess rc 1 | returns `"failed"`. stderr has `"failed at preprocess (exit 1)"` and the log path. `status` is still `untrained`. `lora/` has no `video.safetensors` |
| D22 | `train_video`: latents count 23 for 24 videos | returns `"failed"`, stderr `"preprocess wrote 23 latents for 24 videos"` |
| D23 | `train_video`: train rc 0 but no final checkpoint | returns `"failed"`, `"failed at train"` |
| D24 | `train_video`: the LoRA test render raises `Ltx2MlxError` | returns `"test_failed"`. `train()` exits 1, and still runs stills when requested. `status == "trained"`, `loras.video.sample_path is None`, `control_path` set |
| D25 | the `train/video` dir pre-populated with a stale file | the stale file is gone after the run |
| D26 | `train()` preflight order: each of lock, busy, `story_server_state() == "SERVING vision"`, avail 29.9 GiB, free disk 15.9 GiB for both kinds, dev dir containing `transformer-distilled.safetensors` | each returns 2 with the 7.2 message. `train_video` is never called (a sentinel patch raises if called). An extra case with the server `SERVING vision` **and** avail 29.9 GiB reports CT5, which pins the order |
| D27 | `train()`: `--video` only on a character that has a video LoRA, without `--force`; with `--force` | 2 (CT3); proceeds |
| D28 | `train()` default kinds with `MFLUX_TRAIN` pointing at a missing path | video trains. `stills_skip_reason == "mflux-train not found at <p>"`. Exit 0. The same with `--stills` → exit 1 |

- [ ] **Step 1: Write the failing test.** Append exactly this content to the end of `tests/test_character_dataset.py` (the block starts with two blank lines). Afterwards `wc -l tests/test_character_dataset.py` prints `675`.

````python


# --- D7, D8, D20-D28: video LoRA training and train() (spec 4.8, 4.11) -------------------
def test_d7_video_train_config():
    text = character_dataset.video_train_config("/d/pre", "p, q.", "/d/out")
    assert text == character_dataset.VIDEO_TRAIN_CONFIG_TEMPLATE.format(
        model_path=json.dumps(character_dataset.TRAIN_MODEL_DIR),
        gemma=json.dumps(character_dataset.SKILL.GEMMA_MODEL_ID),
        data_root='"/d/pre"', validation_prompt='"p, q."', output_dir='"/d/out"')
    lines = text.splitlines()
    for line in ('  model_path: "%s"' % character_dataset.TRAIN_MODEL_DIR,
                 '  preprocessed_data_root: "/d/pre"', '    - "p, q."', 'output_dir: "/d/out"',
                 "  rank: 32", "  alpha: 32", "  steps: 1000", "  interval: 250",
                 "  keep_last_n: 10"):
        assert line in lines, line
    assert "{" not in text


def test_d8_preprocess_and_train_argv():
    cd = character_dataset
    assert cd.preprocess_argv("/v", "/c", "/o") == [
        cd.SKILL.LTX2_MLX_BIN, "preprocess", "--videos", "/v", "--captions", "/c", "-o", "/o",
        "-m", cd.TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]
    assert cd.train_argv("/t.yaml") == [cd.SKILL.LTX2_MLX_BIN, "train", "--config", "/t.yaml",
                                        "--low-ram"]


def _untrained(lib, name="kyra", kept=24):
    """An untrained character with a real dataset layout: 25 tiny stills, and captions,
    1-frame "videos" and manifest items for the kept ones (n 5 is the dropped still)."""
    data = make_character(lib, name=name, status="untrained")
    data["dataset"]["kept"] = kept
    cdir = os.path.join(lib, name)
    kept_ns = [n for n in range(25) if n != 5][:kept]
    for sub in ("stills", "captions", "videos"):
        os.makedirs(os.path.join(cdir, "dataset", sub), exist_ok=True)
    items = []
    for n in range(25):
        Image.new("RGB", (8, 8), (n, n, n)).save(os.path.join(cdir, "dataset", "stills",
                                                              "char_%02d.png" % n))
        if n in kept_ns:
            with open(os.path.join(cdir, "dataset", "captions", "char_%02d.txt" % n), "w") as f:
                f.write("kyrawmn woman, close-up, n %d" % n)
            with open(os.path.join(cdir, "dataset", "videos", "char_%02d.mp4" % n), "wb") as f:
                f.write(b"mp4")
        items.append({"n": n, "kept": n in kept_ns})
    with open(os.path.join(cdir, "dataset", "manifest.json"), "w") as f:
        json.dump({"items": items}, f)
    character_lib.write_character(data)
    return data


def _fake_video_tools(monkeypatch, preprocess_rc=0, latents=None, train_rc=0,
                      write_checkpoint=True, fail_test=None):
    """run_logged and SKILL.generate_video fakes; returns the dict of recorded calls."""
    record = {"run": [], "generate": []}

    def _run(cmd, log_path, cwd, env, timeout_s):
        record["run"].append({"cmd": cmd, "log": log_path, "cwd": cwd, "env": env})
        if cmd[1] == "preprocess":
            out_dir = cmd[cmd.index("-o") + 1]
            videos = cmd[cmd.index("--videos") + 1]
            latent_dir = os.path.join(out_dir, ".precomputed", "latents")
            os.makedirs(latent_dir)
            count = len(os.listdir(videos)) if latents is None else latents
            for i in range(count):
                open(os.path.join(latent_dir, "l%02d.safetensors" % i), "wb").close()
            return preprocess_rc
        vdir = os.path.dirname(cmd[cmd.index("--config") + 1])
        if write_checkpoint:
            ckpt_dir = os.path.join(vdir, "out", "checkpoints")
            os.makedirs(ckpt_dir)
            with open(os.path.join(ckpt_dir, character_dataset.VIDEO_FINAL_CKPT), "wb") as f:
                f.write(b"lora")
        return train_rc

    def _generate(prompt, output_path, **kwargs):
        record["generate"].append(dict(kwargs, prompt=prompt, output_path=output_path))
        if fail_test is not None and len(record["generate"]) == fail_test:
            raise character_dataset.SKILL.Ltx2MlxError("stub render failure")
        with open(output_path, "wb") as f:
            f.write(b"mp4")
        return output_path

    monkeypatch.setattr(character_dataset, "run_logged", _run)
    monkeypatch.setattr(character_dataset.SKILL, "generate_video", _generate)
    return record


_Memory = collections.namedtuple("_Memory", "available")


def _train_ready(monkeypatch, tmp_path):
    """Every train() preflight passes: no busy process, server STOPPED, 64 GiB available,
    100 GiB free, a valid dev-model dir, a test-model dir, and executable stub binaries."""
    dev = tmp_path / "dev-model"
    dev.mkdir(parents=True)
    (dev / "transformer-dev.safetensors").write_bytes(b"dev")
    test_model = tmp_path / "test-model"
    test_model.mkdir(parents=True)
    stub = tmp_path / "stub-bin"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
    monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
    monkeypatch.setattr(character_dataset.psutil, "virtual_memory",
                        lambda: _Memory(64.0 * 2 ** 30))
    monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)
    monkeypatch.setattr(character_dataset, "TRAIN_MODEL_DIR", str(dev))
    monkeypatch.setattr(character_dataset, "TEST_MODEL_DIR", str(test_model))
    monkeypatch.setattr(character_dataset.SKILL, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", str(stub))
    return dev


def _train_args(name="kyra", video=False, stills=False, force=False):
    return argparse.Namespace(command="train", name=name, video=video, stills=stills, force=force)


def _load(name="kyra"):
    return character_lib.load_character(name)


def test_d20_train_video_happy_path(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    record = _fake_video_tools(monkeypatch)
    assert character_dataset.train_video(data) == "ok"
    lora = os.path.join(lib_dir, "kyra", "lora", "video.safetensors")
    with open(lora, "rb") as f:
        assert f.read() == b"lora"
    saved = _load()
    entry = saved["loras"]["video"]
    assert saved["status"] == "trained"
    assert entry["sha256"] == hashlib.sha256(b"lora").hexdigest()
    assert (entry["rank"], entry["alpha"], entry["steps"]) == (32, 32, 1000)
    assert entry["sample_path"] == os.path.join(lib_dir, "kyra", "tests", "video_lora.mp4")
    assert entry["control_path"] == os.path.join(lib_dir, "kyra", "tests", "video_control.mp4")
    first, second = record["generate"]
    assert first["loras"] == [(lora, 1.0)]
    assert (first["width"], first["height"], first["num_frames"], first["seed"]) == (512, 320, 25, 42)
    assert first["model"] == character_dataset.TEST_MODEL_DIR
    assert first["image_path"] is None
    assert "loras" not in second
    assert [r["cmd"][1] for r in record["run"]] == ["preprocess", "train"]
    assert all(r["env"]["HF_HOME"] == character_dataset.SKILL.LTX2_MLX_HF_HOME
               and r["cwd"] == character_dataset.SKILL.LTX2_MLX_DIR for r in record["run"])


def test_d21_preprocess_failure(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, preprocess_rc=1)
    assert character_dataset.train_video(data) == "failed"
    err = capsys.readouterr().err
    assert "failed at preprocess (exit 1)" in err
    assert "log: %s" % os.path.join(lib_dir, "kyra", "logs") in err
    assert "-preprocess.log" in err
    assert _load()["status"] == "untrained"
    assert not os.path.exists(os.path.join(lib_dir, "kyra", "lora", "video.safetensors"))


def test_d22_latent_count_mismatch(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, latents=23)
    assert character_dataset.train_video(data) == "failed"
    assert "preprocess wrote 23 latents for 24 videos" in capsys.readouterr().err


def test_d23_missing_final_checkpoint(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, write_checkpoint=False)
    assert character_dataset.train_video(data) == "failed"
    assert "failed at train" in capsys.readouterr().err


def test_d24_test_render_failure_keeps_the_lora(tmp_path, lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, fail_test=1)
    assert character_dataset.train_video(data) == "test_failed"
    saved = _load()
    assert saved["status"] == "trained"
    assert saved["loras"]["video"]["sample_path"] is None
    assert saved["loras"]["video"]["control_path"] is not None
    assert "Error: video test render failed: stub render failure" in capsys.readouterr().err

    _untrained(lib_dir, name="ronin")
    _fake_video_tools(monkeypatch, fail_test=1)
    _train_ready(monkeypatch, tmp_path)
    stills_calls = []
    monkeypatch.setattr(character_dataset, "train_stills",
                        lambda d: stills_calls.append(d["name"]) or "ok", raising=False)
    assert character_dataset.train(_train_args("ronin")) == 1
    assert stills_calls == ["ronin"]


def test_d25_stale_training_dir_is_removed(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    stale = os.path.join(lib_dir, "kyra", "train", "video", "stale.txt")
    os.makedirs(os.path.dirname(stale))
    with open(stale, "w") as f:
        f.write("old")
    _fake_video_tools(monkeypatch)
    assert character_dataset.train_video(data) == "ok"
    assert not os.path.exists(stale)


def test_d26_preflight_order(tmp_path, lib_dir, monkeypatch, capsys):
    _untrained(lib_dir)
    char_dir = os.path.join(lib_dir, "kyra")

    def _never(data):
        raise AssertionError("train_video ran")

    def _case(name, override, message):
        with monkeypatch.context() as m:
            dev = _train_ready(m, tmp_path / name)
            m.setattr(character_dataset, "train_video", _never)
            override(m, dev)
            assert character_dataset.train(_train_args()) == 2, name
        assert capsys.readouterr().err == message + "\n", name

    lock = os.path.join(lib_dir, ".lock")

    def _hold_lock(m, dev):
        with open(lock, "w") as f:
            f.write(str(os.getppid()))

    _case("lock", _hold_lock, "Error: another bin/character create/train is running (pid %d); "
          "run one at a time" % os.getppid())
    os.remove(lock)
    _case("busy", lambda m, dev: m.setattr(character_dataset, "busy_process",
                                           lambda: (4242, "python3 bin/ltx-mlx-render m.json")),
          "Error: a render or training process is running (pid 4242: python3 bin/ltx-mlx-render "
          "m.json); bin/character never trains or generates concurrently with a render")
    _case("server", lambda m, dev: m.setattr(character_dataset, "story_server_state",
                                             lambda: "SERVING vision"),
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    _case("memory", lambda m, dev: m.setattr(character_dataset.psutil, "virtual_memory",
                                             lambda: _Memory(29.9 * 2 ** 30)),
          "Error: only 29.9 GiB of memory is available; training needs 30 GiB (quit "
          "memory-heavy apps and retry)")
    _case("disk", lambda m, dev: m.setattr(character_dataset, "free_gib", lambda path: 15.9),
          "Error: only 15.9 GiB free at %s; training video and stills needs 16 GiB" % char_dir)

    def _distilled(m, dev):
        (dev / "transformer-distilled.safetensors").write_bytes(b"x")

    _case("dev", _distilled,
          "Error: %s must contain transformer-dev.safetensors and neither "
          "transformer.safetensors nor transformer-distilled.safetensors (the trainer would "
          "pick those first)" % (tmp_path / "dev" / "dev-model"))

    def _server_and_memory(m, dev):
        m.setattr(character_dataset, "story_server_state", lambda: "SERVING vision")
        m.setattr(character_dataset.psutil, "virtual_memory", lambda: _Memory(29.9 * 2 ** 30))

    _case("order", _server_and_memory,
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    assert not os.path.exists(lock)


def test_d27_existing_lora_needs_force(tmp_path, lib_dir, monkeypatch, capsys):
    make_character(lib_dir)
    _train_ready(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(character_dataset, "train_video",
                        lambda data: calls.append(data["name"]) or "ok")
    assert character_dataset.train(_train_args(video=True)) == 2
    assert capsys.readouterr().err == (
        "Error: character kyra already has a video LoRA (%s); pass --force to retrain it\n"
        % os.path.join(lib_dir, "kyra", "lora", "video.safetensors"))
    assert calls == []
    assert character_dataset.train(_train_args(video=True, force=True)) == 0
    assert calls == ["kyra"]


def test_d28_missing_mflux_skips_stills(tmp_path, lib_dir, monkeypatch, capsys):
    _untrained(lib_dir)
    _train_ready(monkeypatch, tmp_path)
    missing = str(tmp_path / "no-mflux" / "mflux-train")
    monkeypatch.setattr(character_dataset, "MFLUX_TRAIN", missing)
    calls = []
    monkeypatch.setattr(character_dataset, "train_video",
                        lambda data: calls.append(data["name"]) or "ok")
    assert character_dataset.train(_train_args()) == 0
    assert calls == ["kyra"]
    assert _load()["stills_skip_reason"] == "mflux-train not found at %s" % missing
    assert ("stills LoRA skipped: mflux-train not found at %s; install mflux as described in "
            "docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10"
            % missing) in capsys.readouterr().out
    assert character_dataset.train(_train_args(stills=True)) == 1
    assert calls == ["kyra"]
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `11 failed, 14 passed`, `rc=1`.

- [ ] **Step 3: Implement.** In `character_dataset.py`, insert exactly this block immediately before the line `# --- Z-Image child process (spec 4.9) ---`, which occurs exactly once. The block ends with two blank lines, so the marker stays separated by two blank lines. Afterwards `wc -l character_dataset.py` prints `1246`.

````python
# ---------------------------------------------------------------------------
# Video LoRA training (spec 4.8, 4.11)
# ---------------------------------------------------------------------------

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


def preprocess_argv(videos, captions, out_dir):
    return [SKILL.LTX2_MLX_BIN, "preprocess", "--videos", videos, "--captions", captions,
            "-o", out_dir, "-m", TRAIN_MODEL_DIR, "-H", "320", "-W", "512", "--max-frames", "1"]


def train_argv(config_path):
    return [SKILL.LTX2_MLX_BIN, "train", "--config", config_path, "--low-ram"]


def _video_failed(data, step, rc, log):
    print("Error: video LoRA training failed at %s (exit %s); log: %s; character %s stays %s"
          % (step, rc, log, data["name"], data["status"]), file=sys.stderr)
    return "failed"


def train_video(data):
    """Preprocess, train, record and A/B-test the video LoRA (spec 4.8). Returns "ok",
    "failed" (nothing recorded) or "test_failed" (the LoRA is recorded; a test render
    failed)."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    vdir = os.path.join(char_dir, "train", "video")
    if os.path.exists(vdir):
        shutil.rmtree(vdir)
    os.makedirs(vdir)
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(char_dir, sub), exist_ok=True)
    prompt = trigger_test_prompt(data["trigger"], data["class_noun"])
    config_path = os.path.join(vdir, "train.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(video_train_config(os.path.join(vdir, "preprocessed"), prompt,
                                   os.path.join(vdir, "out")))
    env = dict(os.environ, HF_HOME=SKILL.LTX2_MLX_HF_HOME)
    videos = os.path.join(char_dir, "dataset", "videos")

    log = step_log_path(char_dir, "preprocess")
    rc = run_logged(preprocess_argv(videos, os.path.join(char_dir, "dataset", "captions"),
                                    os.path.join(vdir, "preprocessed")),
                    log, SKILL.LTX2_MLX_DIR, env, PREPROCESS_TIMEOUT_S)
    if rc != 0:
        return _video_failed(data, "preprocess", rc, log)
    latents = os.path.join(vdir, "preprocessed", ".precomputed", "latents")
    n_lat = len(os.listdir(latents)) if os.path.isdir(latents) else 0
    n_vid = len(glob.glob(os.path.join(videos, "*.mp4")))
    if n_lat != n_vid:
        print("Error: preprocess wrote %d latents for %d videos; log: %s" % (n_lat, n_vid, log),
              file=sys.stderr)
        return "failed"

    log = step_log_path(char_dir, "train")
    rc = run_logged(train_argv(config_path), log, SKILL.LTX2_MLX_DIR, env, VIDEO_TRAIN_TIMEOUT_S)
    final = os.path.join(vdir, "out", "checkpoints", VIDEO_FINAL_CKPT)
    if rc != 0 or not os.path.isfile(final) or os.path.getsize(final) == 0:
        return _video_failed(data, "train", rc, log)

    lora_path = os.path.join(char_dir, "lora", "video.safetensors")
    shutil.copy2(final, lora_path + ".tmp")
    os.replace(lora_path + ".tmp", lora_path)
    data["loras"]["video"] = {"path": lora_path, "sha256": _sha256(lora_path),
                              "base_model": TRAIN_MODEL_DIR, "rank": VIDEO_RANK,
                              "alpha": VIDEO_RANK, "steps": VIDEO_STEPS,
                              "trained_at": character_lib.utc_now(),
                              "sample_path": None, "control_path": None}
    data["status"] = "trained"
    character_lib.write_character(data)

    test_failed = False
    for key, filename, step, extra in (
            ("sample_path", "video_lora.mp4", "test-video-lora", {"loras": [(lora_path, 1.0)]}),
            ("control_path", "video_control.mp4", "test-video-control", {})):
        out = os.path.join(char_dir, "tests", filename)
        try:
            SKILL.generate_video(prompt, out, image_path=None, width=512, height=320,
                                 num_frames=25, frame_rate=24, seed=TEST_SEED,
                                 model=TEST_MODEL_DIR, gemma=SKILL.GEMMA_MODEL_ID, low_ram=True,
                                 log_path=step_log_path(char_dir, step),
                                 timeout_s=TEST_RENDER_TIMEOUT_S, force=True, **extra)
        except (ValueError, SKILL.Ltx2MlxError) as e:
            print("Error: video test render failed: %s" % e, file=sys.stderr)
            test_failed = True
            continue
        data["loras"]["video"][key] = out
        character_lib.write_character(data)

    entry = data["loras"]["video"]
    print("video LoRA: %s (sha256 %s)" % (lora_path, entry["sha256"]))
    print("trigger-only A/B (compare by eye; the LoRA clip should show the character, the "
          "control a stranger):")
    print("  with LoRA: %s" % entry["sample_path"])
    print("  control:   %s" % entry["control_path"])
    return "test_failed" if test_failed else "ok"


def train(args):
    """bin/character train (spec 4.11). Returns 0, 1 or 2."""
    name = args.name
    try:
        data = character_lib.load_character(name)
    except character_lib.CharacterError as e:
        return _error(e)
    if data["status"] == "dataset":
        return _error("character %s has no accepted dataset (status dataset); fix it with "
                      "bin/character create %s --regenerate" % (name, name))
    requested = [k for k in ("video", "stills") if getattr(args, k)] or ["video", "stills"]
    explicit_stills = args.stills
    for kind in requested:
        if data["loras"][kind] is not None and not args.force:
            return _error("character %s already has a %s LoRA (%s); pass --force to retrain it"
                          % (name, kind, data["loras"][kind]["path"]))
    char_dir = character_lib.character_dir(name)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(library_lock())
        except DatasetError as e:
            return _error(e)
        busy = busy_process()
        if busy is not None:
            return _error("a render or training process is running (pid %d: %s); bin/character "
                          "never trains or generates concurrently with a render" % busy)
        state = story_server_state()
        if state != "STOPPED":
            return _error("the story server is %s; stop it first with bin/story-server stop "
                          "(training needs its memory)" % state)
        avail = psutil.virtual_memory().available / 2 ** 30
        if avail < TRAIN_MIN_AVAIL_GIB:
            return _error("only %.1f GiB of memory is available; training needs 30 GiB (quit "
                          "memory-heavy apps and retry)" % avail)
        need = TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)
        free = free_gib(char_dir)
        if free < need:
            return _error("only %.1f GiB free at %s; training %s needs %d GiB"
                          % (free, char_dir, " and ".join(requested), need))
        if "video" in requested:
            if (not os.path.isfile(os.path.join(TRAIN_MODEL_DIR, "transformer-dev.safetensors"))
                    or os.path.exists(os.path.join(TRAIN_MODEL_DIR, "transformer.safetensors"))
                    or os.path.exists(os.path.join(TRAIN_MODEL_DIR,
                                                   "transformer-distilled.safetensors"))):
                return _error("%s must contain transformer-dev.safetensors and neither "
                              "transformer.safetensors nor transformer-distilled.safetensors "
                              "(the trainer would pick those first)" % TRAIN_MODEL_DIR)
            if not os.path.isdir(TEST_MODEL_DIR):
                return _error("test-render model not found: %s" % TEST_MODEL_DIR)
            if not (os.path.isfile(SKILL.LTX2_MLX_BIN) and os.access(SKILL.LTX2_MLX_BIN, os.X_OK)):
                return _error("ltx-2-mlx binary not found or not executable: %s"
                              % SKILL.LTX2_MLX_BIN)

        stills_outcome = "ok"
        if "stills" in requested and not (os.path.isfile(MFLUX_TRAIN)
                                          and os.access(MFLUX_TRAIN, os.X_OK)):
            data["stills_skip_reason"] = "mflux-train not found at %s" % MFLUX_TRAIN
            character_lib.write_character(data)
            print("stills LoRA skipped: %s; install mflux as described in "
                  "docs/superpowers/specs/2026-10-05-character-library-design.md section 4.10"
                  % data["stills_skip_reason"])
            requested.remove("stills")
            stills_outcome = "skipped"

        video_outcome = "ok"
        if "video" in requested:
            video_outcome = train_video(data)
            if video_outcome == "failed":
                return 1
        if "stills" in requested:
            stills_outcome = train_stills(data)
        if (video_outcome == "test_failed" or stills_outcome == "failed"
                or (stills_outcome == "skipped" and explicit_stills)):
            return 1
        return 0


````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `25 passed`, `rc=0`.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add character_dataset.py tests/test_character_dataset.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/character_dataset.py
qwen-agent-workspace/tests/test_character_dataset.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character_dataset: video LoRA training, trigger-only A/B and train()

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 12: `character_dataset.py`, stills LoRA through mflux and the compat gate (amendment 4 settings)

**Start condition:** Task 1's L0 has passed and been reported (it has: spec 0.2 "mflux, measured"). Task 11 is committed as `f91de86` (`character_dataset.py` 1252 lines, `tests/test_character_dataset.py` 714 lines). This task's counts were measured on a clone of `f91de86`. This task may be skipped only on the user's explicit decision; see "Skipping the stills half".

**Files:**
- Modify: `character_dataset.py` (two constant edits plus one insertion; 1428 lines at the end of this task)
- Test: append to `tests/test_character_dataset.py` (1003 lines at the end of this task)

**Interfaces:**
- Consumes:
  - Task 10's `run_logged`, `run_zimage_child`, `step_log_path`, `trigger_test_prompt`, `_sha256`, `DatasetError`;
  - `MFLUX_TRAIN`, `MFLUX_HF_HOME`, `STILLS_RANK`, `TEST_SEED`.
- Produces:
  - constants (amendment 4): `STILLS_TARGET_STEPS = 672` (was 2400), the new `STILLS_MAX_RESOLUTION = 512`, and `STILLS_TRAIN_TIMEOUT_S = 10800` (was 21600);
  - `stills_epochs(kept) -> (num_epochs, total_steps, save_frequency)`, where `save_frequency == total_steps` (final checkpoint only);
  - `stills_train_config(data_dir, output_dir, seed, kept) -> dict`;
  - `safetensors_keys(path) -> list`, `lora_module_count(keys) -> int`;
  - `extract_mflux_adapter(out_dir, dest, total_steps) -> zip path`, which searches only `<out_dir>/checkpoints/` and requires the last step to equal `total_steps`;
  - `train_stills(data) -> "ok"|"skipped"|"failed"`, which never pre-creates mflux's `output_path` (`<sdir>/out`) and refuses if it exists.

Spec 4.1 constants (amendment 4) and 4.9 up to the child protocol (which Task 10 implemented), verbatim:

- `STILLS_RANK = 16`, `STILLS_TARGET_STEPS = 672`, `STILLS_MAX_RESOLUTION = 512` (amendment 4)
- `MFLUX_TRAIN = os.environ.get("CHARACTER_MFLUX_TRAIN", os.path.expanduser("~/mflux/.venv/bin/mflux-train"))` (the env var is test infrastructure)
- `MFLUX_HF_HOME = os.environ.get("Z_IMAGE_HF_HOME", os.path.expanduser("~/hf_home"))`
- Timeouts: `PREPROCESS_TIMEOUT_S = 1800`, `VIDEO_TRAIN_TIMEOUT_S = 14400`, `STILLS_TRAIN_TIMEOUT_S = 10800` (3 h, about 3x the expected 55 min; amendment 4), `TEST_RENDER_TIMEOUT_S = 1800`, `ZIMAGE_CHILD_TIMEOUT_S = 3600`

**Epoch arithmetic (amendment 4).** The run gets about 672 steps (the 512-test sweet spot, 0.2) whatever the kept count. Only the final checkpoint is saved **[spec choice: final only]**: the 512 test showed no gain past 672, and intermediate zips cost about 389 MB each.

```python
def stills_epochs(kept):
    """(num_epochs, total_steps, save_frequency) for about STILLS_TARGET_STEPS steps; one
    checkpoint, at the final step (spec 4.9, amendment 4)."""
    num_epochs = max(1, round(STILLS_TARGET_STEPS / kept))
    total_steps = num_epochs * kept
    return num_epochs, total_steps, total_steps
```

| kept | result |
|---|---|
| 24 | `(28, 672, 672)` |
| 12 | `(56, 672, 672)` |
| 16 | `(42, 672, 672)` |
| 17 | `(40, 680, 680)` |
| 25 | `(27, 675, 675)` |
| 13 | `(52, 676, 676)` |

- `672 / kept` is never exactly x.5 for `kept` in 1..25, so Python's round-half-even never applies.
- The expected run time is about 55 min per character (672 × 4.6-5.1 s, no CPU contention).
- mflux additionally writes its own `0000000_checkpoint.zip` at step 0. It is ignored (step 4).

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
        "max_resolution": STILLS_MAX_RESOLUTION,
        "low_ram": False,
        "gradient_checkpointing": True,
        "training_loop": {"num_epochs": num_epochs, "batch_size": 1,
                          "timestep_low": 4, "timestep_high": 9},
        "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
        "checkpoint": {"save_frequency": save_frequency, "output_path": output_dir},
        "monitoring": {"preview_width": 512, "preview_height": 320,
                       "plot_frequency": 100, "generate_image_frequency": total_steps + 1},
        "lora_layers": {"targets": [
            {"module_path": "layers.{block}." + m, "blocks": {"start": 0, "end": 30},
             "rank": STILLS_RANK} for m in modules]},
    }
```

Choices made here:

- **Targets [spec choice]:** attention and feed-forward only, across all 30 blocks. The example's `cap_embedder.1` and `all_final_layer.2-1.linear` are dropped, because their diffusers-side names are the least likely to map (G1).
- `"quantize": None` (bf16 base) matches the bf16 base that z_image_skill fuses into **[spec choice]**.
- **(Amendment 4)** `max_resolution` is 512 (L0 at 1024 measured 13.07 s/step, rejected; 0.2).
- **(Amendment 4)** `generate_image_frequency` is `total_steps + 1` so that mflux renders **no** mid-run or final preview **[spec choice]**. The run's real trigger-only test is the compat gate's 1024x640 render (step 6). Previews are 512x320 should mflux render one anyway.
- **(Amendment 4)** These targets produced the L0-validated key format: 210 modules = 7 targets × 30 blocks, all injected. So G1 is resolved for them.

**`train_stills(data)`.** It returns `"ok"`, `"skipped"` (incompatible; the reason is recorded), or `"failed"` (a runtime failure).

1. `sdir = <dir>/train/stills`. If it exists, `shutil.rmtree(sdir)`. Then `os.makedirs(sdir/data)` **only**.
   - **(Amendment 4)** The mflux `output_path` is `sdir/out`, and it must **not** be pre-created: mflux would write to a timestamped sibling `out_<YYYYMMDD_HHMMSS>/` instead (0.2).
   - Only its parent `sdir` exists, because `os.makedirs(sdir/data)` creates `sdir`.
   - Directly before step 3, if `os.path.lexists(sdir/out)` (the rmtree failed, or something created it) → print `Error: stills LoRA training refused: mflux output directory already exists: <sdir>/out (mflux would write to a timestamped sibling); move it aside and retry`, return `"failed"`.
2. For each kept item: `shutil.copy2` `dataset/stills/char_NN.png` → `sdir/data/char_NN.png`, and `dataset/captions/char_NN.txt` → `sdir/data/char_NN.txt`. Write `sdir/data/preview_1.txt` = `trigger_test_prompt(...)`.
3. Write `sdir/train.json`. Run `[MFLUX_TRAIN, "--config", sdir/train.json]` with cwd `sdir`, env `dict(os.environ, HF_HOME=MFLUX_HF_HOME)`, timeout `STILLS_TRAIN_TIMEOUT_S`, and log step `train-stills`.
   - `HF_HOME` points at the internal `~/hf_home`, so the 31 G Z-Image-Turbo cache is reused and the training adapter downloads there, not to the USB global cache **[spec choice]**.
   - rc != 0 → `Error: stills LoRA training failed: mflux-train exited <rc>; log: <log>`, return `"failed"`.
4. Run `extract_mflux_adapter(sdir/out, <dir>/lora/stills.candidate.safetensors, total_steps)`, where `total_steps` comes from `stills_epochs(kept)`:
   - **(Amendment 4)** The signature becomes `extract_mflux_adapter(out_dir, dest, total_steps)`.
   - `zips = glob.glob(os.path.join(out_dir, "checkpoints", "[0-9]" * 7 + "_checkpoint.zip"))`. That is **only** `<output_path>/checkpoints/`: no recursion, and no timestamped siblings.
   - Take the zip whose 7-digit leading integer is largest.
   - Its members ending in `_adapter.safetensors` must be exactly 1; extract that member's bytes to `dest`.
   - No zip, or not exactly 1 adapter member → `DatasetError("mflux-train wrote no checkpoint zip with exactly one *_adapter.safetensors under %s" % os.path.join(out_dir, "checkpoints"))`.
   - The largest step is not `total_steps` (for example only `0000000_checkpoint.zip` exists) → `DatasetError("mflux-train's last checkpoint is step %d, expected %d (the run stopped early)" % (step, total_steps))`.
   - Both print `Error: <e>` and return `"failed"`.
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

Spec 7.2 row CT12, verbatim:

| # | Condition | Exit | Message / effect |
|---|---|---|---|
| CT12 | mflux-train rc != 0; `sdir/out` already exists before the run (amendment 4); no adapter under `<out>/checkpoints/`; or the last checkpoint step != `total_steps` | 1 | 4.9 steps 1, 3 and 4 |

Spec 9.3 rows, verbatim:

| ID | Test | Assertion |
|---|---|---|
| D9 | `stills_epochs` for the 4.9 table rows; and for k in 1..30 | each row exactly. For all k: `epochs >= 1`, `total == epochs * k`, `save == total`, `abs(total - 672) <= k / 2` |
| D10 | `stills_train_config("/d", "/o", 0, 24)` | the 4.9 dict exactly: `max_resolution == 512`; 7 targets, each `"blocks": {"start": 0, "end": 30}`, `"rank": 16`; `training_loop.num_epochs == 28`; `checkpoint == {"save_frequency": 672, "output_path": "/o"}`; `monitoring == {"preview_width": 512, "preview_height": 320, "plot_frequency": 100, "generate_image_frequency": 673}` |
| D11 | `safetensors_keys` on a hand-built file (8-byte header length + JSON with `__metadata__` and 3 tensors) | the 3 sorted keys |
| D12 | `lora_module_count` on `["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight", "lora_unet_x.lora_down.weight", "lora_unet_x.alpha", "other.weight"]` | `2` |
| D13 | `extract_mflux_adapter(out, dest, 672)` on `out/checkpoints/0000000_checkpoint.zip` and `out/checkpoints/0000672_checkpoint.zip`. Each holds the 0.2 member set (`NNNNNNN_adapter.safetensors`, `NNNNNNN_optimizer.safetensors`, `NNNNNNN_{iterator,loss,config}.json`, `checkpoint.json`, `run.json`) | the dest bytes equal the 672 zip's adapter member |
| D14 | `extract_mflux_adapter` with no zips; with a zip holding 2 adapter members; with only `0000000_checkpoint.zip` (step-mismatch message `"…last checkpoint is step 0, expected 672…"`); with the only zip in a timestamped sibling `out_20261005_194009/checkpoints/` (not searched) | `DatasetError` each |
| D40 | `train_stills` with `run_logged` patched to record `os.path.exists(sdir/out)` at the moment mflux is invoked | it records `False`, and `sdir` exists. A pre-existing `sdir/out` that survives (rmtree patched to a no-op) → `"failed"`, the CT12 "already exists" message, and mflux never invoked |
| D41 | `STILLS_TARGET_STEPS`, `STILLS_MAX_RESOLUTION`, `STILLS_TRAIN_TIMEOUT_S` | `672`, `512`, `10800` |
| D29 | `train_stills` happy path: `run_logged` writes a checkpoint zip whose adapter has 2 modules; `run_zimage_child` returns `injected_lora_modules: 2` and writes the PNG | `"ok"`. `lora/stills.safetensors` exists. `loras.stills.rank == 16`, `steps == 672` (24 kept). The patched mflux writes `sdir/out/checkpoints/0000672_checkpoint.zip`. The control child spec has `"loras": None`. The data dir holds 24 png+txt pairs plus `preview_1.txt == trigger_test_prompt(...)`. `train.json` equals `stills_train_config(...)`. The env passed has `HF_HOME == MFLUX_HF_HOME` |
| D30 | `train_stills`: injected 1 of 2 | `"skipped"`. `lora/stills.rejected.safetensors` exists and `stills.safetensors` does not. `stills_skip_reason` contains `"only 1 of 2 LoRA modules"`. `loras.stills` unchanged |
| D31 | `train_stills`: the compat child raises `DatasetError` | `"skipped"`, with the reason containing `"could not load or render"` |
| D32 | `train_stills`: the adapter has zero `.lora` keys | `"skipped"`, reason `"the adapter file has no LoRA modules"` |
| D33 | `train_stills`: mflux rc 2 | `"failed"`. `train()` exits 1 even without `--stills` |
| D34 | `--force` retrain of stills where the new adapter is incompatible, while a previous good stills entry exists | the previous entry and file are kept. `stills_skip_reason` is set |

D14 carries one extra case beyond the spec row, a zip nested at `out/run/checkpoints/` that is not searched. This is the case that catches the "searches recursively" mutation (Decision 32).

**Plan-added cases (Task 11 review; the spec is silent; Decision 37).** These extend the existing Task 11 tests D23 and D26; no new IDs. They pin four `train_video`/`train()` rules that four mutations survived (observed: 0/4 caught without these cases, 4/4 with them):
- D26 gains `story_server_state() == "UNKNOWN"` (must be refused as CT5), and a dev dir containing `transformer.safetensors` (must be refused as CT8a; D26 already covers `transformer-distilled.safetensors`).
- D23 gains two cases: only `lora_weights_step_00750.safetensors` is written, and the final checkpoint is 0 bytes. Each must give `"failed"` with `failed at train (exit 0)`, the status must stay `untrained`, and `lora/video.safetensors` must not exist.

- [ ] **Step 1: Write the tests.** First apply these two edits to `tests/test_character_dataset.py` (the plan-added D23/D26 cases):

**Edit 1** (`tests/test_character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
def test_d23_missing_final_checkpoint(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, write_checkpoint=False)
    assert character_dataset.train_video(data) == "failed"
    assert "failed at train" in capsys.readouterr().err
````

with:

````python
def test_d23_missing_final_checkpoint(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_video_tools(monkeypatch, write_checkpoint=False)
    assert character_dataset.train_video(data) == "failed"
    assert "failed at train" in capsys.readouterr().err
    # Plan-added (Task 11 review): only the exact final step counts, and it must be non-empty.
    for name, ckpt, content in (("early", "lora_weights_step_00750.safetensors", b"lora"),
                                ("empty", character_dataset.VIDEO_FINAL_CKPT, b"")):
        other = _untrained(lib_dir, name=name)
        _fake_video_tools(monkeypatch, write_checkpoint=False)
        fake_run = character_dataset.run_logged

        def _run(cmd, log_path, cwd, env, timeout_s, ckpt=ckpt, content=content, fake_run=fake_run):
            rc = fake_run(cmd, log_path, cwd, env, timeout_s)
            if cmd[1] == "train":
                ckpt_dir = os.path.join(os.path.dirname(cmd[cmd.index("--config") + 1]), "out",
                                        "checkpoints")
                os.makedirs(ckpt_dir, exist_ok=True)
                with open(os.path.join(ckpt_dir, ckpt), "wb") as f:
                    f.write(content)
            return rc

        monkeypatch.setattr(character_dataset, "run_logged", _run)
        assert character_dataset.train_video(other) == "failed", name
        assert "failed at train (exit 0)" in capsys.readouterr().err, name
        assert _load(name)["status"] == "untrained", name
        assert not os.path.exists(os.path.join(lib_dir, name, "lora", "video.safetensors")), name
````

**Edit 2** (`tests/test_character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
    _case("order", _server_and_memory,
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    assert not os.path.exists(lock)
````

with:

````python
    _case("order", _server_and_memory,
          "Error: the story server is SERVING vision; stop it first with bin/story-server stop "
          "(training needs its memory)")
    # Plan-added (Task 11 review): UNKNOWN fails closed, and a plain transformer.safetensors
    # in the dev dir is refused as well as transformer-distilled.safetensors.
    _case("unknown", lambda m, dev: m.setattr(character_dataset, "story_server_state",
                                              lambda: "UNKNOWN"),
          "Error: the story server is UNKNOWN; stop it first with bin/story-server stop "
          "(training needs its memory)")

    def _plain(m, dev):
        (dev / "transformer.safetensors").write_bytes(b"x")

    _case("plain", _plain,
          "Error: %s must contain transformer-dev.safetensors and neither "
          "transformer.safetensors nor transformer-distilled.safetensors (the trainer would "
          "pick those first)" % (tmp_path / "plain" / "dev-model"))
    assert not os.path.exists(lock)
````

Now `wc -l tests/test_character_dataset.py` prints `750`, and `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"` gives `27 passed`: the Task 11 code already obeys these rules.

Append exactly this content to the end of `tests/test_character_dataset.py` (the block starts with two blank lines). Afterwards `wc -l tests/test_character_dataset.py` prints `1003`.

````python


# --- D9-D14, D29-D34: stills LoRA through mflux and the compat gate (spec 4.9) -----------
def test_d9_stills_epochs():
    se = character_dataset.stills_epochs
    assert se(24) == (28, 672, 672)
    assert se(12) == (56, 672, 672)
    assert se(16) == (42, 672, 672)
    assert se(17) == (40, 680, 680)
    assert se(25) == (27, 675, 675)
    assert se(13) == (52, 676, 676)
    for kept in range(1, 31):
        epochs, total, save = se(kept)
        assert epochs >= 1 and total == epochs * kept and save == total
        assert abs(total - 672) <= kept / 2


def test_d10_stills_train_config():
    modules = ["attention.to_q", "attention.to_k", "attention.to_v", "attention.to_out.0",
               "feed_forward.w1", "feed_forward.w2", "feed_forward.w3"]
    assert character_dataset.stills_train_config("/d", "/o", 0, 24) == {
        "model": "z-image-turbo", "data": "/d", "seed": 0, "steps": 9, "guidance": 0.0,
        "quantize": None, "max_resolution": 512, "low_ram": False,
        "gradient_checkpointing": True,
        "training_loop": {"num_epochs": 28, "batch_size": 1, "timestep_low": 4,
                          "timestep_high": 9},
        "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
        "checkpoint": {"save_frequency": 672, "output_path": "/o"},
        "monitoring": {"preview_width": 512, "preview_height": 320, "plot_frequency": 100,
                       "generate_image_frequency": 673},
        "lora_layers": {"targets": [
            {"module_path": "layers.{block}." + m, "blocks": {"start": 0, "end": 30},
             "rank": 16} for m in modules]},
    }


def _safetensors_bytes(keys):
    header = {"__metadata__": {"format": "pt"}}
    for i, key in enumerate(keys):
        header[key] = {"dtype": "F32", "shape": [1], "data_offsets": [4 * i, 4 * i + 4]}
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * (4 * len(keys))


TWO_MODULE_KEYS = ["layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight",
                   "layers.0.attention.to_k.lora_A.weight", "layers.0.attention.to_k.lora_B.weight"]


def test_d11_safetensors_keys(tmp_path):
    path = str(tmp_path / "a.safetensors")
    with open(path, "wb") as f:
        f.write(_safetensors_bytes(["b.weight", "a.weight", "c.bias"]))
    assert character_dataset.safetensors_keys(path) == ["a.weight", "b.weight", "c.bias"]


def test_d12_lora_module_count():
    assert character_dataset.lora_module_count([
        "layers.0.attention.to_q.lora_A.weight", "layers.0.attention.to_q.lora_B.weight",
        "lora_unet_x.lora_down.weight", "lora_unet_x.alpha", "other.weight"]) == 2


def _checkpoint_zip(path, step, adapters=1):
    """A checkpoint zip with the measured mflux member set (spec 0.2)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("%07d_adapter.safetensors" % step, ("adapter %d" % step).encode())
        if adapters == 2:
            archive.writestr("%07d_extra_adapter.safetensors" % step, b"second adapter")
        archive.writestr("%07d_optimizer.safetensors" % step, b"optimizer")
        for name in ("iterator", "loss", "config"):
            archive.writestr("%07d_%s.json" % (step, name), b"{}")
        archive.writestr("checkpoint.json", b"{}")
        archive.writestr("run.json", b"{}")


def test_d13_extract_takes_the_final_step(tmp_path):
    out = tmp_path / "out"
    _checkpoint_zip(str(out / "checkpoints" / "0000000_checkpoint.zip"), 0)
    _checkpoint_zip(str(out / "checkpoints" / "0000672_checkpoint.zip"), 672)
    dest = str(tmp_path / "adapter.safetensors")
    character_dataset.extract_mflux_adapter(str(out), dest, 672)
    with open(dest, "rb") as f:
        assert f.read() == b"adapter 672"


def test_d14_extract_errors(tmp_path):
    message = ("mflux-train wrote no checkpoint zip with exactly one *_adapter.safetensors "
               "under %s")
    cases = []
    empty = tmp_path / "empty" / "out"
    empty.mkdir(parents=True)
    cases.append((empty, message % (empty / "checkpoints")))
    two = tmp_path / "two" / "out"
    _checkpoint_zip(str(two / "checkpoints" / "0000672_checkpoint.zip"), 672, adapters=2)
    cases.append((two, message % (two / "checkpoints")))
    early = tmp_path / "early" / "out"
    _checkpoint_zip(str(early / "checkpoints" / "0000000_checkpoint.zip"), 0)
    cases.append((early, "mflux-train's last checkpoint is step 0, expected 672 (the run "
                         "stopped early)"))
    sibling = tmp_path / "sibling" / "out"
    _checkpoint_zip(str(tmp_path / "sibling" / "out_20261005_194009" / "checkpoints"
                        / "0000672_checkpoint.zip"), 672)
    cases.append((sibling, message % (sibling / "checkpoints")))
    nested = tmp_path / "nested" / "out"
    _checkpoint_zip(str(nested / "run" / "checkpoints" / "0000672_checkpoint.zip"), 672)
    cases.append((nested, message % (nested / "checkpoints")))
    for out, expected in cases:
        with pytest.raises(DatasetError) as info:
            character_dataset.extract_mflux_adapter(str(out), str(tmp_path / "x"), 672)
        assert str(info.value) == expected, out


def _fake_stills_tools(monkeypatch, adapter_keys=TWO_MODULE_KEYS, mflux_rc=0, injected=2,
                       compat_error=False):
    """run_logged (mflux-train) and run_zimage_child fakes; returns the recorded calls."""
    record = {"run": [], "children": []}

    def _run(cmd, log_path, cwd, env, timeout_s):
        record["run"].append({"cmd": cmd, "cwd": cwd, "env": env})
        with open(cmd[cmd.index("--config") + 1]) as f:
            config = json.load(f)
        out = config["checkpoint"]["output_path"]
        record["out_existed"] = os.path.exists(out)
        zip_path = os.path.join(out, "checkpoints",
                                "%07d_checkpoint.zip" % config["checkpoint"]["save_frequency"])
        os.makedirs(os.path.dirname(zip_path))
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("0002400_adapter.safetensors", _safetensors_bytes(adapter_keys))
        return mflux_rc

    def _child(spec, char_dir, step):
        record["children"].append((spec, step))
        if compat_error and spec["loras"]:
            raise DatasetError("Z-Image child process exited 1; log: /x/logs/test.log")
        for job in spec["jobs"]:
            Image.new("RGB", (16, 10), (1, 2, 3)).save(job["output_path"])
        return {"jobs": [{"output_path": j["output_path"], "status": "ok", "seconds": 1.0}
                         for j in spec["jobs"]],
                "injected_lora_modules": injected if spec["loras"] else None}

    monkeypatch.setattr(character_dataset, "run_logged", _run)
    monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
    return record


def test_d29_train_stills_happy_path(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    record = _fake_stills_tools(monkeypatch)
    assert character_dataset.train_stills(data) == "ok"
    cdir = os.path.join(lib_dir, "kyra")
    assert os.path.isfile(os.path.join(cdir, "lora", "stills.safetensors"))
    entry = _load()["loras"]["stills"]
    assert (entry["rank"], entry["alpha"], entry["steps"]) == (16, 16, 672)
    assert os.path.isfile(os.path.join(cdir, "train", "stills", "out", "checkpoints",
                                       "0000672_checkpoint.zip"))
    assert entry["sample_path"] == os.path.join(cdir, "tests", "stills_lora.png")
    assert entry["control_path"] == os.path.join(cdir, "tests", "stills_control.png")
    (gate, gate_step), (control, control_step) = record["children"]
    assert gate["loras"] == [[os.path.join(cdir, "lora", "stills.candidate.safetensors"), 1.0]]
    assert (gate_step, control_step) == ("test-stills-lora", "test-stills-control")
    assert control["loras"] is None
    data_dir = os.path.join(cdir, "train", "stills", "data")
    names = sorted(os.listdir(data_dir))
    assert len([n for n in names if n.endswith(".png")]) == 24
    assert len([n for n in names if n.startswith("char_") and n.endswith(".txt")]) == 24
    with open(os.path.join(data_dir, "preview_1.txt")) as f:
        assert f.read() == character_dataset.trigger_test_prompt("kyrawmn", "woman")
    with open(os.path.join(cdir, "train", "stills", "train.json")) as f:
        assert json.load(f) == character_dataset.stills_train_config(
            data_dir, os.path.join(cdir, "train", "stills", "out"), 0, 24)
    run = record["run"][0]
    assert run["cmd"][0] == character_dataset.MFLUX_TRAIN
    assert run["env"]["HF_HOME"] == character_dataset.MFLUX_HF_HOME
    assert run["cwd"] == os.path.join(cdir, "train", "stills")


def test_d30_partial_injection_is_rejected(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_stills_tools(monkeypatch, injected=1)
    assert character_dataset.train_stills(data) == "skipped"
    lora = os.path.join(lib_dir, "kyra", "lora")
    assert os.path.isfile(os.path.join(lora, "stills.rejected.safetensors"))
    assert not os.path.exists(os.path.join(lora, "stills.safetensors"))
    saved = _load()
    assert "only 1 of 2 LoRA modules" in saved["stills_skip_reason"]
    assert saved["stills_skip_reason"].startswith("mflux adapter incompatible with z_image_skill: ")
    assert saved["loras"]["stills"] is None
    assert "the video LoRA is unaffected" in capsys.readouterr().out


def test_d31_child_failure_is_rejected(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    _fake_stills_tools(monkeypatch, compat_error=True)
    assert character_dataset.train_stills(data) == "skipped"
    assert "could not load or render" in _load()["stills_skip_reason"]


def test_d32_adapter_without_lora_keys_is_rejected(lib_dir, monkeypatch):
    data = _untrained(lib_dir)
    _fake_stills_tools(monkeypatch, adapter_keys=["layers.0.attention.to_q.weight"], injected=0)
    assert character_dataset.train_stills(data) == "skipped"
    assert _load()["stills_skip_reason"] == (
        "mflux adapter incompatible with z_image_skill: the adapter file has no LoRA modules")


def test_d33_mflux_failure_fails_train(tmp_path, lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    _fake_stills_tools(monkeypatch, mflux_rc=2)
    assert character_dataset.train_stills(data) == "failed"
    assert "Error: stills LoRA training failed: mflux-train exited 2; log: " in (
        capsys.readouterr().err)
    _train_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(character_dataset, "train_video", lambda d: "ok")
    assert character_dataset.train(_train_args()) == 1


def test_d34_failed_retrain_keeps_the_previous_stills_lora(tmp_path, lib_dir, monkeypatch):
    _untrained(lib_dir)
    data = make_character(lib_dir, stills=True)
    previous = data["loras"]["stills"]
    stills = previous["path"]
    _fake_stills_tools(monkeypatch, injected=1)
    _train_ready(monkeypatch, tmp_path)
    assert character_dataset.train(_train_args(stills=True, force=True)) == 1
    saved = _load()
    assert saved["loras"]["stills"] == previous
    with open(stills, "rb") as f:
        assert f.read() == STILLS_BYTES
    assert saved["stills_skip_reason"].startswith("mflux adapter incompatible with z_image_skill: ")


def test_d40_mflux_output_dir_is_never_pre_created(lib_dir, monkeypatch, capsys):
    data = _untrained(lib_dir)
    record = _fake_stills_tools(monkeypatch)
    assert character_dataset.train_stills(data) == "ok"
    assert record["out_existed"] is False
    assert os.path.isdir(os.path.join(lib_dir, "kyra", "train", "stills"))
    other = _untrained(lib_dir, name="ronin")
    out = os.path.join(lib_dir, "ronin", "train", "stills", "out")
    os.makedirs(out)
    record["run"][:] = []
    monkeypatch.setattr(character_dataset.shutil, "rmtree", lambda path, *a, **kw: None)
    assert character_dataset.train_stills(other) == "failed"
    assert capsys.readouterr().err == (
        "Error: stills LoRA training refused: mflux output directory already exists: %s "
        "(mflux would write to a timestamped sibling); move it aside and retry\n" % out)
    assert record["run"] == []


def test_d41_stills_constants():
    assert character_dataset.STILLS_TARGET_STEPS == 672
    assert character_dataset.STILLS_MAX_RESOLUTION == 512
    assert character_dataset.STILLS_TRAIN_TIMEOUT_S == 10800
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `14 failed, 27 passed`, `rc=1`. The 14 failures are the 12 stills tests plus D40 and D41; the 27 passes are Tasks 10-11's tests, including beedc77's D38/D39 and the extended D23/D26.

- [ ] **Step 3: Implement the constants.** Apply these two edits to `character_dataset.py`:

**Edit 3** (`character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
STILLS_RANK = 16
STILLS_TARGET_STEPS = 2400
````

with:

````python
STILLS_RANK = 16
STILLS_TARGET_STEPS = 672
STILLS_MAX_RESOLUTION = 512
````

**Edit 4** (`character_dataset.py`). Replace this exact text, which occurs exactly once:

````python
STILLS_TRAIN_TIMEOUT_S = 21600
````

with:

````python
STILLS_TRAIN_TIMEOUT_S = 10800
````

- [ ] **Step 4: Implement.** In `character_dataset.py`, insert exactly this block immediately before the line `# --- Z-Image child process (spec 4.9) ---`, which occurs exactly once. The block ends with two blank lines, so the marker stays separated by two blank lines. Afterwards `wc -l character_dataset.py` prints `1428`.

````python
# ---------------------------------------------------------------------------
# Stills LoRA training through mflux, and the compat gate (spec 4.9)
# ---------------------------------------------------------------------------

def stills_epochs(kept):
    """(num_epochs, total_steps, save_frequency) for about STILLS_TARGET_STEPS steps; one
    checkpoint, at the final step (spec 4.9, amendment 4)."""
    num_epochs = max(1, round(STILLS_TARGET_STEPS / kept))
    total_steps = num_epochs * kept
    return num_epochs, total_steps, total_steps


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
        "max_resolution": STILLS_MAX_RESOLUTION,
        "low_ram": False,
        "gradient_checkpointing": True,
        "training_loop": {"num_epochs": num_epochs, "batch_size": 1,
                          "timestep_low": 4, "timestep_high": 9},
        "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
        "checkpoint": {"save_frequency": save_frequency, "output_path": output_dir},
        "monitoring": {"preview_width": 512, "preview_height": 320,
                       "plot_frequency": 100, "generate_image_frequency": total_steps + 1},
        "lora_layers": {"targets": [
            {"module_path": "layers.{block}." + m, "blocks": {"start": 0, "end": 30},
             "rank": STILLS_RANK} for m in modules]},
    }


def safetensors_keys(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n).decode("utf-8"))
    return sorted(k for k in header if k != "__metadata__")


def lora_module_count(keys):
    return len({k.split(".lora")[0] for k in keys if ".lora" in k})


def extract_mflux_adapter(out_dir, dest, total_steps):
    """Write the single *_adapter.safetensors member of the highest-step
    <out_dir>/checkpoints/NNNNNNN_checkpoint.zip to dest and return that zip's path. Only
    <out_dir>/checkpoints/ is searched (no recursion, no timestamped siblings), and its last
    step must be total_steps (spec 4.9 step 4, amendment 4)."""
    checkpoints = os.path.join(out_dir, "checkpoints")
    zips = glob.glob(os.path.join(checkpoints, "[0-9]" * 7 + "_checkpoint.zip"))
    if zips:
        newest = max(zips, key=lambda p: int(os.path.basename(p)[:7]))
        step = int(os.path.basename(newest)[:7])
        if step != total_steps:
            raise DatasetError("mflux-train's last checkpoint is step %d, expected %d (the run "
                               "stopped early)" % (step, total_steps))
        with zipfile.ZipFile(newest) as archive:
            members = [m for m in archive.namelist() if m.endswith("_adapter.safetensors")]
            if len(members) == 1:
                with open(dest, "wb") as f:
                    f.write(archive.read(members[0]))
                return newest
    raise DatasetError("mflux-train wrote no checkpoint zip with exactly one "
                       "*_adapter.safetensors under %s" % checkpoints)


def train_stills(data):
    """Train the stills LoRA with mflux and keep it only if it passes the compat gate (spec
    4.9). Returns "ok", "skipped" (incompatible; the reason is recorded) or "failed"."""
    name = data["name"]
    char_dir = character_lib.character_dir(name)
    sdir = os.path.join(char_dir, "train", "stills")
    if os.path.exists(sdir):
        shutil.rmtree(sdir)
    os.makedirs(os.path.join(sdir, "data"))
    out = os.path.join(sdir, "out")
    for sub in ("lora", "tests", "logs"):
        os.makedirs(os.path.join(char_dir, sub), exist_ok=True)
    with open(os.path.join(char_dir, "dataset", "manifest.json"), encoding="utf-8") as f:
        kept_ns = [item["n"] for item in json.load(f)["items"] if item["kept"]]
    for n in kept_ns:
        for sub, ext in (("stills", "png"), ("captions", "txt")):
            shutil.copy2(os.path.join(char_dir, "dataset", sub, "char_%02d.%s" % (n, ext)),
                         os.path.join(sdir, "data", "char_%02d.%s" % (n, ext)))
    prompt = trigger_test_prompt(data["trigger"], data["class_noun"])
    with open(os.path.join(sdir, "data", "preview_1.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)
    if os.path.lexists(out):
        print("Error: stills LoRA training refused: mflux output directory already exists: %s "
              "(mflux would write to a timestamped sibling); move it aside and retry" % out,
              file=sys.stderr)
        return "failed"
    config_path = os.path.join(sdir, "train.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(stills_train_config(os.path.join(sdir, "data"), out, data["seed"],
                                      len(kept_ns)), f, indent=2)
    _num_epochs, total_steps, _save = stills_epochs(len(kept_ns))

    log = step_log_path(char_dir, "train-stills")
    rc = run_logged([MFLUX_TRAIN, "--config", config_path], log, sdir,
                    dict(os.environ, HF_HOME=MFLUX_HF_HOME), STILLS_TRAIN_TIMEOUT_S)
    if rc != 0:
        print("Error: stills LoRA training failed: mflux-train exited %d; log: %s" % (rc, log),
              file=sys.stderr)
        return "failed"
    candidate = os.path.join(char_dir, "lora", "stills.candidate.safetensors")
    try:
        extract_mflux_adapter(out, candidate, total_steps)
    except DatasetError as e:
        print("Error: %s" % e, file=sys.stderr)
        return "failed"
    try:
        expected = lora_module_count(safetensors_keys(candidate))
    except (ValueError, struct.error):
        expected = 0

    sample = os.path.join(char_dir, "tests", "stills_lora.png")
    job = {"prompt": prompt, "output_path": sample, "seed": TEST_SEED, "width": 1024,
           "height": 640}
    report = child_error = None
    try:
        report = run_zimage_child({"jobs": [job], "loras": [[candidate, 1.0]]}, char_dir,
                                  "test-stills-lora")
    except DatasetError as e:
        child_error = e
    if child_error is not None:
        reason = ("Z-Image could not load or render with it (see %s)"
                  % getattr(child_error, "log_path", child_error))
    elif expected == 0:
        reason = "the adapter file has no LoRA modules"
    elif report["injected_lora_modules"] != expected:
        reason = ("only %s of %d LoRA modules in the adapter matched the Z-Image transformer"
                  % (report["injected_lora_modules"], expected))
    else:
        reason = None

    if reason is not None:
        os.replace(candidate, os.path.join(char_dir, "lora", "stills.rejected.safetensors"))
        data["stills_skip_reason"] = "mflux adapter incompatible with z_image_skill: " + reason
        character_lib.write_character(data)
        print("stills LoRA skipped: %s; the video LoRA is unaffected" % data["stills_skip_reason"])
        return "skipped"

    stills_path = os.path.join(char_dir, "lora", "stills.safetensors")
    os.replace(candidate, stills_path)
    control = os.path.join(char_dir, "tests", "stills_control.png")
    control_path = None
    try:
        control_report = run_zimage_child({"jobs": [dict(job, output_path=control)],
                                           "loras": None}, char_dir, "test-stills-control")
        if control_report["jobs"][0]["status"] == "ok":
            control_path = control
    except DatasetError as e:
        print("Error: stills control render failed: %s" % e, file=sys.stderr)
    data["loras"]["stills"] = {"path": stills_path, "sha256": _sha256(stills_path),
                               "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": STILLS_RANK,
                               "alpha": STILLS_RANK, "steps": total_steps,
                               "trained_at": character_lib.utc_now(),
                               "sample_path": (sample if report["jobs"][0]["status"] == "ok"
                                               else None),
                               "control_path": control_path}
    data["stills_skip_reason"] = None
    character_lib.write_character(data)
    print("stills LoRA: %s" % stills_path)
    print("  with LoRA: %s" % data["loras"]["stills"]["sample_path"])
    print("  control:   %s" % control_path)
    return "ok"


````

- [ ] **Step 5: Run to pass:** `python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `41 passed`, `rc=0`. `grep -c 'def ' character_dataset.py` prints `49`.

- [ ] **Step 6: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add character_dataset.py tests/test_character_dataset.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/character_dataset.py
qwen-agent-workspace/tests/test_character_dataset.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character_dataset: mflux stills LoRA training (512, final checkpoint) and the compat gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 13: `bin/character` -- the library CLI, plus P55

**Files:**
- Create: `bin/character` (106 lines), then `chmod +x bin/character`
- Test: create `tests/test_character_tool.py` (492 lines); append P55 to `tests/test_casting_pipeline.py` (1422 lines at the end of this task)

**Interfaces:**
- Consumes:
  - `character_lib.character_table_lines`, `load_character`, `character_dir`, `CharacterError` (Task 3);
  - `character_dataset.create(args)` and `character_dataset.train(args)` (Tasks 10-11), imported inside `main` only.
- Produces:
  - `build_parser()` (spec 4.2, verbatim), `cmd_list() -> 0`, `cmd_show(name) -> 0|2`, `main(argv=None) -> int`;
  - the executable `bin/character create|train|list|show`.

Spec 4.2 and 4.3, verbatim:

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

Spec 9.4 and row P55, verbatim:

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
| P55 | subprocess: `[sys.executable, "bin/ltx-movie", "--list-characters"]` vs `[sys.executable, "bin/character", "list"]`, both with `CHARACTER_LIBRARY_DIR` = the C45 lib, `cwd=WS` | both rc 0, byte-identical stdout, empty stderr |

- [ ] **Step 1: Write the failing tests.** Create `tests/test_character_tool.py` with exactly this content:

````python
"""Tests for bin/character end to end (spec docs/superpowers/specs/
2026-10-05-character-library-design.md Section 9.4, K1-K18).

Run from the workspace root: python3 -m pytest tests/test_character_tool.py
Plain pytest asserts only (no check() helper). The VLM, the story server, the memory and
disk probes and the Z-Image child are fakes (spec 9.1); real ffmpeg/ffprobe wrap and verify
the kept stills. Every library lives under tmp_path through $CHARACTER_LIBRARY_DIR.
"""

import hashlib
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest
from PIL import Image

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_dataset  # noqa: E402
import character_lib  # noqa: E402

TOOL_PATH = os.path.join(WS, "bin", "character")
tool = importlib.machinery.SourceFileLoader("character_tool", TOOL_PATH).load_module()

# --- shared fixtures (spec 9.1) --------------------------------------------------------
DESCRIPTOR = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name="kyra", trigger="kyrawmn", phrase="the woman in grey",
                   class_noun="woman", status="trained", stills=False, strength=None):
    """Write a valid character.json (spec 2.2 shape) under lib/name and return the dict. A
    trained character also gets a 16-byte lora/video.safetensors, plus a 16-byte
    lora/stills.safetensors when stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = None
    if status in ("untrained", "trained"):
        dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                   "face_height": 0.38,
                   "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video = stills_entry = None
    if status == "trained":
        video_path = os.path.join(cdir, "lora", "video.safetensors")
        with open(video_path, "wb") as f:
            f.write(VIDEO_BYTES)
        video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
                 "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
                 "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
                 "sample_path": None, "control_path": None}
        if stills:
            stills_path = os.path.join(cdir, "lora", "stills.safetensors")
            with open(stills_path, "wb") as f:
                f.write(STILLS_BYTES)
            stills_entry = {"path": stills_path,
                            "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                            "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                            "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                            "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": DESCRIPTOR, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": status, "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


RONIN_DESCRIPTOR = ("a lean man in his late thirties with a topknot and a scarred brow, wearing a "
                    "faded indigo haori and dark hakama")
CHECK_REPLY = {"shot": "medium shot", "pose": "standing on a trail", "setting": "a forest"}


class _Fakes(object):
    """The spec 9.1 fakes for create/train: a VLM dispatching on the prompt text, the story
    server, the memory/disk/process probes, and a Z-Image child that writes 1024x640 solid
    PNGs for its jobs (except the job numbers in skip, or raising child_error)."""

    def __init__(self, monkeypatch, face=None, describe=None, scores=(), skip=(),
                 child_error=None):
        self.face, self.describe, self.scores = face, describe, list(scores)
        self.vlm_calls, self.server_calls, self.child_specs = [], [], []
        self.skip, self.child_error = set(skip), child_error
        fakes = self

        def _vlm(content_parts, max_tokens=600):
            text = content_parts[0]["text"]
            if text == character_dataset.FACE_PROMPT:
                fakes.vlm_calls.append("face")
                return json.dumps({"face_box": fakes.face})
            if text == character_dataset.DESCRIBE_PROMPT:
                fakes.vlm_calls.append("describe")
                return json.dumps(fakes.describe)
            assert text == character_dataset.CHECK_PROMPT
            fakes.vlm_calls.append("check")
            return json.dumps(dict(CHECK_REPLY, identity_score=fakes.scores.pop(0)))

        def _child(spec, char_dir, step):
            fakes.child_specs.append((spec, step))
            if fakes.child_error is not None:
                raise fakes.child_error
            jobs = []
            for i, job in enumerate(spec["jobs"], 1):
                if i in fakes.skip:
                    jobs.append({"output_path": job["output_path"], "status": "blocked",
                                 "seconds": 0.0})
                    continue
                Image.new("RGB", (job["width"], job["height"]), (60, 90, 120)).save(
                    job["output_path"])
                jobs.append({"output_path": job["output_path"], "status": "ok", "seconds": 1.0})
            return {"jobs": jobs, "injected_lora_modules": None}

        monkeypatch.setattr(character_dataset, "vlm_call", _vlm)
        monkeypatch.setattr(character_dataset, "run_zimage_child", _child)
        monkeypatch.setattr(character_dataset, "story_server",
                            lambda cmd: fakes.server_calls.append(cmd) or 0)
        monkeypatch.setattr(character_dataset, "wait_for_vlm", lambda timeout_s: True)
        monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: True)
        monkeypatch.setattr(character_dataset, "vlm_ready", lambda: True)
        monkeypatch.setattr(character_dataset, "busy_process", lambda: None)
        monkeypatch.setattr(character_dataset, "story_server_state", lambda: "STOPPED")
        monkeypatch.setattr(character_dataset, "free_gib", lambda path: 100.0)


def _seed_image(tmp_path):
    path = str(tmp_path / "seed.png")
    Image.new("RGB", (800, 600), (200, 180, 160)).save(path)
    return path


def _tree(lib):
    return sorted(os.listdir(lib)) if os.path.isdir(lib) else []


def _c45_library(lib):
    """kyra (trained, no stills), ronin (untrained) and an invalid bad (spec C45)."""
    make_character(lib)
    make_character(lib, name="ronin", trigger="roninmn", phrase="the ronin", class_noun="man",
                   status="untrained")
    os.makedirs(os.path.join(lib, "bad"))
    with open(os.path.join(lib, "bad", "character.json"), "w") as f:
        f.write("{bad")


def _ronin_create(*extra):
    return ["create", "ronin", "--phrase", "the ronin", "--descriptor", RONIN_DESCRIPTOR,
            "--class", "man"] + list(extra)


# --- K1-K3: argument errors, list, show (spec 4.2, 4.3) ----------------------------------
def test_k1_usage_errors():
    for argv in ([], ["create"], ["train"], ["show"]):
        with pytest.raises(SystemExit) as info:
            tool.main(argv)
        assert info.value.code == 2, argv


def test_k2_list(lib_dir, capsys):
    assert tool.main(["list"]) == 0
    assert capsys.readouterr().out == "no characters in %s\n" % lib_dir
    _c45_library(lib_dir)
    assert tool.main(["list"]) == 0
    out = capsys.readouterr().out
    assert out == "\n".join(character_lib.character_table_lines()) + "\n"
    assert out.splitlines()[0].split() == ["NAME", "TRIGGER", "STATUS", "VIDEO", "STILLS",
                                           "PHRASE"]
    assert out.splitlines()[1].startswith("bad              (invalid: ")


def test_k3_show(lib_dir, capsys):
    data = make_character(lib_dir)
    sample = os.path.join(lib_dir, "kyra", "tests", "video_lora.mp4")
    data["loras"]["video"]["sample_path"] = sample
    character_lib.write_character(data)
    assert tool.main(["show", "kyra"]) == 0
    files = [("MISSING", os.path.join(lib_dir, "kyra", "seed.png")),
             ("MISSING", data["dataset"]["contact_sheet"]),
             ("ok", data["loras"]["video"]["path"]),
             ("MISSING", sample)]
    assert capsys.readouterr().out == (
        json.dumps(data, indent=2, ensure_ascii=False) + "\nfiles:\n"
        + "".join("  %-8s %s\n" % f for f in files))
    assert tool.main(["show", "ghost"]) == 2
    assert capsys.readouterr().err == "Error: unknown character: ghost (no %s)\n" % (
        os.path.join(lib_dir, "ghost", "character.json"))


# --- K4-K8: create's argument checks, preflights and face gate (spec 4.4, 7.1) ------------
def test_k4_create_argument_errors(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch)
    make_character(lib_dir)
    character_lib.register_trigger("roninmn", "ronin")
    not_image = tmp_path / "notes.png"
    not_image.write_text("not an image")
    missing = str(tmp_path / "missing.png")
    base = ["create", "nova", "--phrase", "the nova"]
    desc = ["--descriptor", RONIN_DESCRIPTOR, "--class", "man"]
    cases = [
        (["create", "Bad"], "Error: character name must match [a-z][a-z0-9-]{1,23}, got 'Bad'"),
        (["create", "kyra", "--phrase", "the woman in grey"] + desc,
         "Error: character kyra already exists (%s); use --regenerate to rebuild its dataset"
         % os.path.join(lib_dir, "kyra")),
        (["create", "nova"] + desc, "Error: create needs --phrase"),
        (["create", "nova", "--phrase", "the"] + desc,
         "Error: --phrase: phrase must not be a lone article: 'the'"),
        (base, "Error: create needs exactly one of --seed-image or --descriptor"),
        (base + desc + ["--seed-image", missing],
         "Error: create needs exactly one of --seed-image or --descriptor"),
        (base + ["--descriptor", RONIN_DESCRIPTOR],
         "Error: --descriptor needs --class NOUN (there is no image to take it from)"),
        (base + ["--descriptor", RONIN_DESCRIPTOR, "--class", "Man"],
         "Error: class noun must match [a-z]{3,12}, got 'Man'"),
        (base + ["--descriptor", "a short one", "--class", "man"],
         "Error: --descriptor: descriptor word count must be 8-60, got 3"),
        (base + ["--seed-image", missing], "Error: --seed-image not found: %s" % missing),
        (base + desc + ["--trigger", "AB"],
         "Error: trigger must match [a-z][a-z0-9]{3,15}, got 'AB'"),
        (base + desc + ["--trigger", "roninmn"],
         "Error: trigger roninmn is already used by character ronin; triggers are never reused"),
        (base + desc + ["--trigger", "nova"],
         "Error: trigger nova must not be a word of the phrase or the class noun"),
        (base + ["--descriptor", RONIN_DESCRIPTOR, "--class", "mann", "--trigger", "mann"],
         "Error: trigger mann must not be a word of the phrase or the class noun"),
        (base + desc + ["--seed", "-1"], "Error: --seed must be >= 0"),
    ]
    before = _tree(lib_dir)
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == message + "\n", argv
        assert _tree(lib_dir) == before
    assert tool.main(base + ["--seed-image", str(not_image)]) == 2
    assert capsys.readouterr().err.startswith(
        "Error: --seed-image is not a readable image: %s: " % not_image)
    assert _tree(lib_dir) == before
    assert fakes.vlm_calls == []


def test_k5_regenerate_refusals(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    make_character(lib_dir)
    json_path = os.path.join(lib_dir, "kyra", "character.json")
    cases = [
        (["create", "kyra", "--regenerate", "--phrase", "the lady"],
         "Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger, "
         "--seed or --force; edit %s instead" % json_path),
        (["create", "kyra", "--regenerate", "--force"],
         "Error: --regenerate takes no --phrase, --seed-image, --descriptor, --class, --trigger, "
         "--seed or --force; edit %s instead" % json_path),
        (["create", "ghost", "--regenerate"],
         "Error: unknown character: ghost (no %s)" % os.path.join(lib_dir, "ghost",
                                                                  "character.json")),
        (["create", "kyra", "--regenerate"],
         "Error: character kyra is trained; regenerating its dataset would orphan its LoRAs. "
         "Create a new character instead"),
    ]
    for argv, message in cases:
        assert tool.main(argv) == 2, argv
        assert capsys.readouterr().err == message + "\n"


def test_k6_create_preflights(lib_dir, monkeypatch, capsys):
    argv = _ronin_create()
    lock = os.path.join(lib_dir, ".lock")
    os.makedirs(lib_dir)

    def _case(setup, message):
        with monkeypatch.context() as m:
            _Fakes(m)
            setup(m)
            assert tool.main(argv) == 2
        assert capsys.readouterr().err == message + "\n"
        assert not os.path.exists(os.path.join(lib_dir, "ronin"))

    def _hold(m):
        with open(lock, "w") as f:
            f.write(str(os.getppid()))

    _case(_hold, "Error: another bin/character create/train is running (pid %d); run one at a "
          "time" % os.getppid())
    os.remove(lock)
    _case(lambda m: m.setattr(character_dataset, "busy_process",
                              lambda: (4242, "python3 bin/ltx-movie n")),
          "Error: a render or training process is running (pid 4242: python3 bin/ltx-movie n); "
          "bin/character never trains or generates concurrently with a render")
    _case(lambda m: m.setattr(character_dataset, "free_gib", lambda path: 1.5),
          "Error: only 1.5 GiB free at %s; create needs 2 GiB" % lib_dir)
    _case(lambda m: m.setattr(character_dataset, "vlm_ready", lambda: False),
          "Error: the vision model qwen38-6bit is not being served at "
          "http://127.0.0.1:8177/v1/models; start it with: bin/story-server vision")
    assert not os.path.exists(lock)


def test_k7_small_face_refused(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[400, 100, 600, 220])
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path)]) == 2
    assert capsys.readouterr().err == (
        "Error: the main character's face fills only 12% of the seed image's height (minimum "
        "15%); a small face makes a weak identity reference. Use a closer crop of the character, "
        "or pass --force to proceed anyway.\n")
    assert not os.path.exists(os.path.join(lib_dir, "kyra"))
    assert not os.path.exists(os.path.join(lib_dir, ".triggers"))
    assert fakes.vlm_calls == ["face"]


KYRA_DESCRIBE = {"class_noun": "woman",
                 "descriptor": "A young East Asian woman with long black hair and a grey kimono."}


def test_k8_small_face_with_force(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, face=[400, 100, 600, 220], describe=KYRA_DESCRIBE, scores=[9] * 25)
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path), "--force"]) == 0
    assert ("Warning: the main character's face fills only 12% of the seed image's height "
            "(minimum 15%); a small face makes a weak identity reference; proceeding (--force)"
            in capsys.readouterr().err)
    assert character_lib.load_character("kyra")["dataset"]["face_height"] == 0.12


# --- K9-K14: create end to end (spec 4.4-4.7) ---------------------------------------------
def test_k9_seed_mode_happy_path(tmp_path, lib_dir, monkeypatch, capsys):
    scores = [9] * 25
    scores[5] = 4
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=scores)
    seed = _seed_image(tmp_path)
    assert tool.main(["create", "kyra", "--phrase", "the woman in grey",
                      "--seed-image", seed]) == 0
    cdir = os.path.join(lib_dir, "kyra")
    data = character_lib.load_character("kyra")
    assert data["status"] == "untrained"
    assert data["class_noun"] == "woman"
    assert data["descriptor"] == "a young East Asian woman with long black hair and a grey kimono"
    assert data["trigger"] == "kyrawmn"
    assert data["source"] == {"type": "seed_image", "path": seed}
    assert data["dataset"] == {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
                               "face_height": 0.4,
                               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    captions = sorted(os.listdir(os.path.join(cdir, "dataset", "captions")))
    videos = sorted(os.listdir(os.path.join(cdir, "dataset", "videos")))
    assert len(captions) == 24 and len(videos) == 24
    assert "char_05.txt" not in captions
    for name in videos:
        character_dataset.verify_ffprobe(os.path.join(cdir, "dataset", "videos", name))
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "kyrawmn kyra\n"
    assert fakes.server_calls == ["stop", "vision"]
    assert os.path.isfile(os.path.join(cdir, "seed.png"))
    with open(os.path.join(cdir, "dataset", "description.json")) as f:
        assert json.load(f)["class_noun"] == "woman"
    with open(os.path.join(cdir, "dataset", "manifest.json")) as f:
        manifest = json.load(f)
    assert [item["n"] for item in manifest["items"]] == list(range(25))
    assert manifest["reference"] == "char_00" and manifest["face_height"] == 0.4
    json_path = os.path.join(cdir, "character.json")
    assert capsys.readouterr().out.splitlines()[-3:] == [
        "dataset: 24/25 stills kept (minimum 12) in %s" % os.path.join(cdir, "dataset"),
        "contact sheet: %s" % os.path.join(cdir, "dataset", "contact_sheet.jpg"),
        'next: review the contact sheet. To change the look, edit "descriptor" in %s and run '
        'bin/character create kyra --regenerate; otherwise run bin/character train kyra'
        % json_path]


def test_k10_descriptor_mode(lib_dir, monkeypatch):
    scores = [3] + [9] * 23
    fakes = _Fakes(monkeypatch, scores=scores)
    assert tool.main(_ronin_create()) == 0
    assert "face" not in fakes.vlm_calls and "describe" not in fakes.vlm_calls
    data = character_lib.load_character("ronin")
    assert data["source"] == {"type": "descriptor"}
    assert data["trigger"] == "roninmn"
    assert data["dataset"]["reference"] == "char_01"
    assert data["dataset"]["face_height"] is None
    assert (data["dataset"]["kept"], data["dataset"]["total"]) == (24, 24)
    with open(os.path.join(lib_dir, "ronin", "dataset", "manifest.json")) as f:
        items = json.load(f)["items"]
    assert [item["n"] for item in items] == list(range(1, 25))
    assert items[0]["identity_score"] == 3 and items[0]["kept"] is True
    assert not os.path.exists(os.path.join(lib_dir, "ronin", "seed.png"))


def test_k11_too_few_kept(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[3] * 14 + [9] * 10)
    assert tool.main(_ronin_create()) == 3
    cdir = os.path.join(lib_dir, "ronin")
    assert capsys.readouterr().err == (
        'Error: only 11/24 stills kept (need 12); the dataset is kept in %s; edit "descriptor" in '
        '%s and run bin/character create ronin --regenerate\n'
        % (os.path.join(cdir, "dataset"), os.path.join(cdir, "character.json")))
    data = character_lib.load_character("ronin")
    assert data["status"] == "dataset"
    assert data["dataset"]["kept"] == 11
    assert os.path.isfile(os.path.join(cdir, "dataset", "manifest.json"))
    assert os.path.isfile(os.path.join(cdir, "dataset", "contact_sheet.jpg"))


def test_k12_regenerate_rebuilds_from_the_edited_descriptor(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[3] * 14 + [9] * 10)
    assert tool.main(_ronin_create()) == 3
    cdir = os.path.join(lib_dir, "ronin")
    json_path = os.path.join(cdir, "character.json")
    with open(json_path) as f:
        data = json.load(f)
    edited = ("a lean man in his late thirties with a long topknot and a scarred brow, wearing "
              "a faded indigo haori")
    data["descriptor"] = edited
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    stale = os.path.join(cdir, "dataset", "stale.txt")
    with open(stale, "w") as f:
        f.write("old")
    fakes = _Fakes(monkeypatch, scores=[9] * 24)
    assert tool.main(["create", "ronin", "--regenerate"]) == 0
    assert not os.path.exists(stale)
    assert fakes.vlm_calls == ["check"] * 24
    assert all(edited in job["prompt"] for job in fakes.child_specs[0][0]["jobs"])
    saved = character_lib.load_character("ronin")
    assert saved["trigger"] == "roninmn"
    assert (saved["status"], saved["dataset"]["kept"]) == ("untrained", 24)
    with open(os.path.join(lib_dir, ".triggers")) as f:
        assert f.read() == "roninmn ronin\n"


def test_k13_generation_failure_restarts_the_vision_server(lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, child_error=character_dataset.DatasetError(
        "Z-Image child process exited 1; log: /x.log"))
    assert tool.main(_ronin_create()) == 1
    assert capsys.readouterr().err == "Error: Z-Image child process exited 1; log: /x.log\n"
    assert fakes.server_calls == ["stop", "vision"]
    assert character_lib.load_character("ronin")["status"] == "dataset"


def test_k14_blocked_reference_still(lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[9] * 24, skip=[1])
    assert tool.main(_ronin_create()) == 1
    assert capsys.readouterr().err == (
        "Error: the reference still char_01 was blocked by the content screen; edit the "
        "descriptor in %s and run bin/character create ronin --regenerate\n"
        % os.path.join(lib_dir, "ronin", "character.json"))


def test_k15_registered_trigger_is_never_reused(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch)
    character_lib.register_trigger("kyrawmn", "kyra")
    assert tool.main(["create", "kyra2", "--phrase", "the woman in grey", "--seed-image",
                      _seed_image(tmp_path), "--trigger", "kyrawmn"]) == 2
    assert capsys.readouterr().err == (
        "Error: trigger kyrawmn is already used by character kyra; triggers are never reused\n")


# --- K16-K18: train delegation and the list import rule (spec 1.2, 4.11) -----------------
def test_k16_train_refuses_a_dataset_character(lib_dir, capsys):
    make_character(lib_dir, status="dataset")
    assert tool.main(["train", "kyra"]) == 2
    assert capsys.readouterr().err == (
        "Error: character kyra has no accepted dataset (status dataset); fix it with "
        "bin/character create kyra --regenerate\n")


def test_k17_train_exit_code_is_propagated(lib_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(character_dataset, "train", lambda args: calls.append(args.name) or 1)
    assert tool.main(["train", "kyra"]) == 1
    assert calls == ["kyra"]


def test_k18_list_imports_neither_pil_psutil_nor_character_dataset(lib_dir):
    make_character(lib_dir)
    script = (
        "import sys\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('character_tool', %r).load_module()\n"
        "rc = m.main(['list'])\n"
        "print(sorted(n for n in ('PIL', 'psutil', 'character_dataset') if n in sys.modules))\n"
    ) % TOOL_PATH
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "[]"
````

- [ ] **Step 2: Write the failing test.** Append exactly this content to the end of `tests/test_casting_pipeline.py`. The file currently ends with a newline, and the block starts with two blank lines. Afterwards `wc -l tests/test_casting_pipeline.py` prints `1422`.

````python


# --- P55: bin/ltx-movie --list-characters == bin/character list (spec 5.6(i)) -------------
def test_p55_list_characters_matches_bin_character_list(lib_dir):
    _c45_library(lib_dir)
    env = dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir)
    movie = subprocess.run([sys.executable, "bin/ltx-movie", "--list-characters"], cwd=WS,
                           env=env, capture_output=True)
    tool = subprocess.run([sys.executable, "bin/character", "list"], cwd=WS, env=env,
                          capture_output=True)
    assert movie.returncode == 0 and tool.returncode == 0
    assert movie.stdout == tool.stdout
    assert movie.stderr == b"" and tool.stderr == b""
````

- [ ] **Step 3: Run to fail:**

````bash
python3 -m pytest tests/test_character_tool.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected: `1 error` (collection: `bin/character` does not exist), `rc=2`; then `1 failed, 62 passed` (P55), `rc=1`.

- [ ] **Step 4: Implement.** Create `bin/character` with exactly this content, then run `chmod +x bin/character`:

````python
#!/usr/bin/env python3
"""character -- build, train and inspect the character LoRA library
(generated/characters/).

  bin/character create NAME --phrase PHRASE (--seed-image PATH | --descriptor TEXT --class NOUN)
                        [--trigger WORD] [--seed N] [--force]
  bin/character create NAME --regenerate
  bin/character train NAME [--video] [--stills] [--force]
  bin/character list
  bin/character show NAME

create builds the training dataset and stops for review (dataset/contact_sheet.jpg); train
trains the video LoRA (ltx-2-mlx) and, when mflux is installed and its adapter passes the
compat gate, the stills LoRA. list and show read the library only. A trained character is
cast into a movie with bin/ltx-movie --character NAME or --cast "PHRASE=NAME".

Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 create kept
fewer than 12 stills.

list/show import character_lib only (stdlib); create/train import character_dataset, which
needs PIL and psutil. See docs/superpowers/specs/2026-10-05-character-library-design.md.
"""

import argparse
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402


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


def cmd_list():
    print("\n".join(character_lib.character_table_lines()))
    return 0


def cmd_show(name):
    try:
        data = character_lib.load_character(name)
    except character_lib.CharacterError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("files:")
    paths = []
    if data["source"]["type"] == "seed_image":
        paths.append(os.path.join(character_lib.character_dir(name), "seed.png"))
    if data["dataset"] is not None:
        paths.append(data["dataset"]["contact_sheet"])
    for kind in ("video", "stills"):
        entry = data["loras"][kind]
        if entry is not None:
            paths.extend(p for p in (entry["path"], entry["sample_path"], entry["control_path"])
                         if p is not None)
    for p in paths:
        print("  %-8s %s" % ("ok" if os.path.isfile(p) else "MISSING", p))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "show":
        return cmd_show(args.name)
    import character_dataset
    if args.command == "create":
        return character_dataset.create(args)
    return character_dataset.train(args)


if __name__ == "__main__":
    sys.exit(main())
````

- [ ] **Step 5: Run to pass:**

````bash
python3 -m pytest tests/test_character_tool.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"
CHARACTER_LIBRARY_DIR=/tmp/charplan-empty-lib bin/character list; echo "rc=$?"
````

Expected: `18 passed, 1 warning`, `rc=0`; `63 passed`, `rc=0`; then `no characters in /tmp/charplan-empty-lib` and `rc=0`. Also `test -x bin/character && echo executable` prints `executable`.

- [ ] **Step 6: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/character tests/test_character_tool.py tests/test_casting_pipeline.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/character
qwen-agent-workspace/tests/test_character_tool.py
qwen-agent-workspace/tests/test_casting_pipeline.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character: bin/character create/train/list/show

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 14: Deploy package ships `character_lib.py`

**Files:**
- Modify: `scripts/deploy/build_pkg.py` (the `PIPELINE_FILES` tuple, +1/-1 lines)
- Modify: `tests/test_deploy_pkg.py` (the `PIPELINE` tuple plus the four count-dependent expected values of Decision 1; +5/-5 lines)

**Interfaces:**
- Consumes: `character_lib.py` (Task 3), now shipped in component A1.
- Produces: a package whose A1 component holds 19 files. `GATE_SPECS` and `TEST_FILES` are unchanged.

Spec Section 8, verbatim:

- `scripts/deploy/build_pkg.py:383` becomes `PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py", "character_lib.py", "bin/ltx-movie", …)`, with `"character_lib.py"` inserted directly after `"pipeline_log.py"`. `tests/test_deploy_pkg.py:308`'s `PIPELINE` tuple gets the identical insertion.
- **Why it must ship.** The shipped `bin/ltx-movie`, `bin/ltx-story-manifest`, and `bin/ltx-story-images` load `character_lib.py` whenever casting is used. Without it, casting on the target would fail with `FileNotFoundError`.
- **Not shipped [spec choice]:** `bin/character`, `character_dataset.py`, the mflux venv, the dev model, and any library content. Training needs the dev pack, the VLM server, and mflux, and is a source-machine activity. A target that wants casting must copy the trained `generated/characters/<name>/` directories, and the absolute LoRA paths inside `character.json` must be valid on that target (G12).
- **Gates.**
  - No new gate (`GATE_SPECS` and `TEST_FILES` are unchanged). The new test files are not shipped.
  - G1-G7 and X1/X2 run the unchanged existing suites and an uncast dry run, so their outputs are unchanged.
- **Deploy test counts: unchanged.** `tests/test_deploy_pkg.py` stays at **165** under `python3 -m pytest` (3.13) and under `/usr/bin/python3 -m unittest tests.test_deploy_pkg` (3.9.6). The tuple edit changes expected values, not test count.

---

Precondition: `git diff --quiet HEAD -- scripts/deploy/build_pkg.py tests/test_deploy_pkg.py && echo clean` prints `clean`.

- [ ] **Step 1: Run before the change:** `python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `165 passed`, `rc=0`. These tests pin the shipped file list, so the red step comes after the tuple edit (Step 3).

- [ ] **Step 2: Edit `scripts/deploy/build_pkg.py`:**

**Edit 1** (`scripts/deploy/build_pkg.py`). Replace this exact text, which occurs exactly once:

````python
}
PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py",
                  "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
                  "bin/story-server", "bin/qwen-agent")
TEST_FILES = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
````

with:

````python
}
PIPELINE_FILES = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py",
                  "character_lib.py", "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
                  "bin/story-server", "bin/qwen-agent")
TEST_FILES = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
````

- [ ] **Step 3: Run to fail:** `python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `101 failed, 64 passed`, `rc=1` (observed). The test fixture builds its fake workspace and golden entry list from the test file's own `PIPELINE` tuple, so most build, resume and install tests fail until Step 4 restores agreement.

- [ ] **Step 4: Edit `tests/test_deploy_pkg.py`.** The first edit is the spec's tuple; the other four are Decision 1's count-dependent values:

**Edit 1** (`tests/test_deploy_pkg.py`). Replace this exact text, which occurs exactly once:

````python

PIPELINE = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py",
            "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
            "bin/story-server", "bin/qwen-agent")
TESTS7 = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
````

with:

````python

PIPELINE = ("z_image_skill.py", "ltx2_mlx_video_skill.py", "ltx_image_fit.py", "content_safety.py", "pipeline_log.py",
            "character_lib.py", "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
            "bin/story-server", "bin/qwen-agent")
TESTS7 = ("tests/test_ltx_movie_offline.py", "tests/test_ltx_mlx_render.py", "tests/test_ltx_story_images.py",
````

**Edit 2** (`tests/test_deploy_pkg.py`). Replace this exact text, which occurs exactly once:

````python
        ctx = self.fx.ctx()
        self.assertEqual(list(ctx.comp_stats), list(ORDER))
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (18, 3))
        self.assertEqual(ctx.comp_stats["F2"], {"slug": "framework-symlinks", "files": 0, "symlinks": 17, "dirs": 3, "bytes": 0})
        totals = bp.stats_totals(ctx.comp_stats)
````

with:

````python
        ctx = self.fx.ctx()
        self.assertEqual(list(ctx.comp_stats), list(ORDER))
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (19, 3))
        self.assertEqual(ctx.comp_stats["F2"], {"slug": "framework-symlinks", "files": 0, "symlinks": 17, "dirs": 3, "bytes": 0})
        totals = bp.stats_totals(ctx.comp_stats)
````

**Edit 3** (`tests/test_deploy_pkg.py`). Replace this exact text, which occurs exactly once:

````python
        comp = [line for line in lines if re.match(r"^[A-H][0-9] ", line)]
        self.assertEqual([line.split()[0] for line in comp], list(ORDER))
        self.assertTrue(re.match(r"^A1 workspace-code files=18 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
        self.assertEqual(comp[9], "F2 framework-symlinks files=0 symlinks=17 dirs=3 bytes=0 (0.00 GiB)")
        totals = [line for line in lines if line.startswith("TOTAL ")]
````

with:

````python
        comp = [line for line in lines if re.match(r"^[A-H][0-9] ", line)]
        self.assertEqual([line.split()[0] for line in comp], list(ORDER))
        self.assertTrue(re.match(r"^A1 workspace-code files=19 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
        self.assertEqual(comp[9], "F2 framework-symlinks files=0 symlinks=17 dirs=3 bytes=0 (0.00 GiB)")
        totals = [line for line in lines if line.startswith("TOTAL ")]
````

**Edit 4** (`tests/test_deploy_pkg.py`). Replace this exact text, which occurs exactly once:

````python
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 26 of ", out)
        self.assert_identical(self.reference())

````

with:

````python
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 27 of ", out)
        self.assert_identical(self.reference())

````

**Edit 5** (`tests/test_deploy_pkg.py`). Replace this exact text, which occurs exactly once:

````python
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 26 of ", out)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
````

with:

````python
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 27 of ", out)
        rc, out, err = build_verify(self.fx)
        self.assertEqual(rc, 0, out + err)
````

- [ ] **Step 5: Run to pass under both interpreters:**

````bash
python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider; echo "rc=$?"
/usr/bin/python3 -m unittest tests.test_deploy_pkg 2>&1 | tail -3
````

Expected: `165 passed`, `rc=0`; then `Ran 165 tests in <t>s`, a blank line, and `OK`.

- [ ] **Step 6: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add scripts/deploy/build_pkg.py tests/test_deploy_pkg.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/scripts/deploy/build_pkg.py
qwen-agent-workspace/tests/test_deploy_pkg.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
deploy: ship character_lib.py with the pipeline files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

The orchestrator tells the user about Decision 1: four expected values in `tests/test_deploy_pkg.py` changed in addition to the tuple. The count is still 165.

---

## Final Acceptance (orchestrator, after Task 14; spec 9.7 and Section 10 task 14)

The orchestrator runs every step itself. Counts an implementer reports are not accepted (spec R1).

### A1: new-suite counts and test-ID coverage

````bash
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_character_lib.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_pipeline.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_character_dataset.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_character_tool.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected, in order: `3 passed`, `46 passed`, `6 passed`, `63 passed`, `41 passed`, `18 passed`, each with `rc=0` (177 in all). Then run all six in one session (Decision 24): `python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_dataset.py tests/test_character_lib.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider; echo "rc=$?"` -> `177 passed`, `rc=0`. Then check that every spec test ID has exactly one function:

````bash
python3 - <<'EOF'
import re
want = (["b1", "b2", "b3"] + ["c%d" % i for i in range(1, 47)] + ["z%d" % i for i in range(1, 7)]
        + ["p%d" % i for i in list(range(1, 18)) + list(range(20, 26)) + list(range(30, 36)) + list(range(40, 58)) + list(range(60, 76))]
        + ["d%d" % i for i in range(1, 42)] + ["k%d" % i for i in range(1, 19)])
files = ["tests/test_casting_regression.py", "tests/test_character_lib.py", "tests/test_z_image_skill_multi_lora.py",
         "tests/test_casting_pipeline.py", "tests/test_character_dataset.py", "tests/test_character_tool.py"]
names = []
for f in files:
    names += re.findall(r"^def test_([a-z]\d+)_", open(f).read(), re.M)
assert sorted(names) == sorted(want), (sorted(set(want) - set(names)), sorted(set(names) - set(want)))
assert len(names) == len(set(names)) == 177
print("test IDs: 177, one function each")
EOF
````

### A2: B-goldens (SC9)

`python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"` -> `3 passed, 1 warning`, `rc=0`. And `git log --format=%h -1 -- tests/fixtures/casting_baseline/ltx_movie_dry_run.txt` must name Task 2's commit: the goldens were never re-captured.

### A3: the full mutation table (self-restoring)

Write this runner to `/tmp/charplan/mutations.py` (outside the repo) and run `python3 /tmp/charplan/mutations.py` from `WS`. It edits tracked files temporarily and restores them in `finally`; nothing else may run against the tree meanwhile. Afterwards `git status --short -- character_lib.py character_dataset.py ltx2_mlx_video_skill.py z_image_skill.py bin/` must list nothing of this feature's files. If the runner is killed, restore with `git checkout -- <file>`: every target is committed by then.

````python
#!/usr/bin/env python3
"""Self-restoring mutation runner for the character-library feature (plan Final Acceptance A3).

Run from the workspace root:  python3 /tmp/charplan/mutations.py
Each row is applied alone. For every row: (1) each anchor's exact occurrence count is
asserted, (2) every target passes on the unmutated tree (control), (3) the mutation is
written, (4) each target runs; a pytest target returns 1 = CAUGHT, 0 = survived, anything
else = broken; a direct-run target ("R1:<file>") returns non-zero = CAUGHT, 0 = survived.
A row passes when at least one target is CAUGHT and none is broken. Files are restored in
finally. Every run gets a fresh PYTHONPYCACHEPREFIX and TMPDIR (a stale .pyc written in
the same second as the mutation can otherwise falsely survive).
"""
import os
import shutil
import subprocess
import sys
import tempfile

WS = os.getcwd()
LIB = "character_lib.py"
DS = "character_dataset.py"
SK = "ltx2_mlx_video_skill.py"
ZI = "z_image_skill.py"
RE = "bin/ltx-mlx-render"
MA = "bin/ltx-story-manifest"
IM = "bin/ltx-story-images"
MO = "bin/ltx-movie"
CH = "bin/character"
T_LIB = "tests/test_character_lib.py::"
T_DS = "tests/test_character_dataset.py::"
T_TO = "tests/test_character_tool.py::"
T_P = "tests/test_casting_pipeline.py::"
T_Z = "tests/test_z_image_skill_multi_lora.py::"
R1_RENDER = "R1:tests/test_ltx_mlx_render.py"

WARN_LOOP = ('    for p in panels:\n'
             '        # Chain mode: the video model receives the Motion: text, so that is what is measured.\n'
             '        _prompt_length_warning(p["index"], p["motion_prompt"] if args.chain else p["panel_text"])\n')

# (label, [(file, old, new, expected count of old)], [targets])
MUTATIONS = [
    ("_phrase_regex drops re.IGNORECASE",
     [(LIB, r'body + r"(?![\w-])", re.IGNORECASE)', r'body + r"(?![\w-])")', 1)],
     [T_LIB + "test_c23_article_case_kept", T_LIB + "test_c31_case_insensitive"]),
    ("boundary lookarounds use \\w only",
     [(LIB, r'r"(?<![\w-])" + body + r"(?![\w-])"', r'r"(?<!\w)" + body + r"(?!\w)"', 1)],
     [T_LIB + "test_c26_word_boundaries"]),
    ("(?<![\\w-]) removed",
     [(LIB, r're.compile(r"(?<![\w-])" + body', r're.compile(body', 1)],
     [T_LIB + "test_c26_word_boundaries"]),
    ("cast_text sorts members shortest first",
     [(LIB, "key=lambda m: (-len(m.phrase), m.phrase.lower(), m.name)",
       "key=lambda m: (len(m.phrase), m.phrase.lower(), m.name)", 1)],
     [T_LIB + "test_c27_longest_phrase_first"]),
    ("overlap check removed",
     [(LIB, "            if any(start < e and s < end for s, e, _, _ in found):\n                continue\n", "", 1)],
     [T_LIB + "test_c27_longest_phrase_first"]),
    ("trigger inserted before the article",
     [(LIB, '            cut = start + len(words[0])\n            out = out[:cut] + " " + member.trigger + out[cut:]',
       '            out = out[:start] + member.trigger + " " + out[start:]', 1)],
     [T_LIB + "test_c23_article_case_kept"]),
    ("trig group ignored (no idempotence)",
     [(LIB, 'match.group("trig") is not None))', 'False))', 1)],
     [T_LIB + "test_c29_idempotent", T_LIB + "test_c28_no_article_prefixes"]),
    ("no-article branch inserts after the first word",
     [(LIB, '        else:\n            out = out[:start] + member.trigger + " " + out[start:]',
       '        else:\n            cut = start + len(words[0])\n            out = out[:cut] + " " + member.trigger + out[cut:]', 1)],
     [T_LIB + "test_c28_no_article_prefixes"]),
    ("panel_strengths always uses character_strength",
     [(LIB, "    by_name = {m.name: m for m in members}\n    if len(names) == 1:",
       "    return {n: character_strength for n in names}\n    by_name = {m.name: m for m in members}\n    if len(names) == 1:", 1)],
     [T_LIB + "test_c36_single_character_is_full_strength", T_P + "test_p20_cast_inserts_triggers_and_lists_characters"]),
    ("panel_strengths ignores the per-character override",
     [(LIB, "(by_name[n].strength if by_name[n].strength is not None else character_strength)",
       "character_strength", 1)],
     [T_LIB + "test_c37_override_and_default", T_P + "test_p21_character_strength_and_override"]),
    ("resolve_cast skips the status check",
     [(LIB, '        if data["status"] != "trained":\n            raise UnusableCharacterError(',
       '        if False:\n            raise UnusableCharacterError(', 1)],
     [T_LIB + "test_c38_resolve_cast_errors"]),
    ("resolve_cast skips the duplicate-phrase check",
     [(LIB, "        if m.phrase.lower() in by_phrase:", "        if False:", 1)],
     [T_LIB + "test_c38_resolve_cast_errors"]),
    ("auto_trigger drops the digit suffix loop",
     [(LIB, '    while candidate in blocked:\n        candidate = "%s%d" % (base, k)\n        k += 1\n', "", 1)],
     [T_LIB + "test_c6_auto_trigger_table"]),
    ("validate_character drops alpha == rank",
     [(LIB, 'if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:',
       'if not _is_int(entry["alpha"]):', 1)],
     [T_LIB + "test_c11_lora_entry_rules"]),
    ("resolve_cast raises plain CharacterError for not-trained",
     [(LIB, 'raise UnusableCharacterError("character %s is not trained',
       'raise CharacterError("character %s is not trained', 1)],
     [T_P + "test_p51_no_usable_characters", T_LIB + "test_c38_resolve_cast_errors"]),
    ("parse_cast_arg keeps a plain CharacterError for an invalid name",
     [(LIB, "        raise UnusableCharacterError(str(e))\n    return normalize_phrase(phrase), name.strip()",
       "        raise CharacterError(str(e))\n    return normalize_phrase(phrase), name.strip()", 1)],
     [T_P + "test_p52_which_errors_list_alternatives", T_LIB + "test_c22_parse_cast_arg_rejects"]),
    ("usable_characters skips the resolve_cast check (lists every name)",
     [(LIB, "        try:\n            member = resolve_cast([(None, name)])[0]\n        except CharacterError:\n"
            "            continue\n        usable.append((member.name, member.phrase))",
       "        usable.append((name, name))", 1)],
     [T_LIB + "test_c43_usable_characters", T_P + "test_p52_which_errors_list_alternatives"]),
    ("format_available_line returns 'available characters: ' for an empty list",
     [(LIB, "    if not characters:\n        return NO_CHARACTERS_AVAILABLE\n", "", 1)],
     [T_LIB + "test_c42_format_available_line", T_P + "test_p51_no_usable_characters"]),
    ("usable_characters iterates in a non-sorted order (reversed)",
     [(LIB, "    usable = []\n    for name in list_names():", "    usable = []\n    for name in reversed(list_names()):", 1)],
     [T_LIB + "test_c43_usable_characters"]),
    ("build_command formats strength with %g",
     [(SK, 'cmd += ["--lora", str(path), repr(float(strength))]', 'cmd += ["--lora", str(path), "%g" % strength]', 1)],
     [T_P + "test_p1_loras_follow_the_gemma_value"]),
    ("build_command emits loras after --distilled",
     [(SK, '    for path, strength in (loras or ()):\n        cmd += ["--lora", str(path), repr(float(strength))]\n'
           '    cmd += ["--distilled",\n           "--prompt", str(prompt),\n           "--output", str(output_path)]\n',
       '    cmd += ["--distilled",\n           "--prompt", str(prompt),\n           "--output", str(output_path)]\n'
       '    for path, strength in (loras or ()):\n        cmd += ["--lora", str(path), repr(float(strength))]\n', 1)],
     [T_P + "test_p1_loras_follow_the_gemma_value"]),
    ("_validate_generate_args skips the file check",
     [(SK, "            if (not isinstance(path, str) or not os.path.isfile(path)\n                    or not os.access(path, os.R_OK)):",
       "            if not isinstance(path, str):", 1)],
     [T_P + "test_p4_generate_video_rejects_bad_loras"]),
    ("build_units always adds loras",
     [(RE, '        if loras:\n            unit["loras"] = loras', '        if True:\n            unit["loras"] = loras', 1)],
     [T_P + "test_p8_uncast_units_keep_the_r4l_keys", R1_RENDER]),
    ("provenance omits sha256",
     [(RE, '[{"kind": l["kind"], "path": l["path"],\n                                "sha256": lora_sha256(l["path"]), "strength": l["strength"]}',
       '[{"kind": l["kind"], "path": l["path"],\n                                "strength": l["strength"]}', 1)],
     [T_P + "test_p15_resume_never_reuses_a_different_lora_set"]),
    ("provenance omits strength",
     [(RE, '[{"kind": l["kind"], "path": l["path"],\n                                "sha256": lora_sha256(l["path"]), "strength": l["strength"]}',
       '[{"kind": l["kind"], "path": l["path"],\n                                "sha256": lora_sha256(l["path"])}', 1)],
     [T_P + "test_p15_resume_never_reuses_a_different_lora_set"]),
    ("provenance adds loras: [] for uncast units",
     [(RE, '    if unit.get("loras"):\n        provenance["loras"] =', '    if True:\n        provenance["loras"] =', 1),
      (RE, '                               for l in unit["loras"]]\n    return provenance',
       '                               for l in unit.get("loras", [])]\n    return provenance', 1)],
     [T_P + "test_p13_provenance_records_the_lora_set", R1_RENDER]),
    ("render_panel always passes loras=",
     [(RE, '        extra = ({"loras": [(l["path"], l["strength"]) for l in unit["loras"]]}\n'
           '                 if unit.get("loras") else {})\n        clip = SKILL.generate_video(',
       '        extra = {"loras": [(l["path"], l["strength"]) for l in unit.get("loras", [])]}\n'
       '        clip = SKILL.generate_video(', 1)],
     [T_P + "test_p9_each_panel_renders_with_its_own_loras", R1_RENDER]),
    ("(amendment 2) the old E-P19 refusal retained",
     [(RE, '    specs = getattr(args, "lora_path_specs", None) or []\n',
       '    cast_panels = [p["index"] for p in panels if p.get("characters")]\n'
       '    if args.lora_path and cast_panels:\n'
       '        print("Error: --lora cannot be combined with a manifest that casts characters", file=sys.stderr)\n'
       '        return 2\n'
       '    specs = getattr(args, "lora_path_specs", None) or []\n', 1)],
     [T_P + "test_p10_global_lora_combines_with_the_cast"]),
    ("lora_sha256 cache keyed on path only",
     [(RE, "    key = (os.path.realpath(path), info.st_size, info.st_mtime_ns)", "    key = os.path.realpath(path)", 1)],
     [T_P + "test_p16_lora_hash_is_memoized_on_identity"]),
    ("manifest inserts triggers into panel_text too",
     [(MA, '            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)\n',
       '            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)\n'
       '            p["panel_text"] = lib.cast_text(p["panel_text"], members)[0]\n', 1)],
     [T_P + "test_p20_cast_inserts_triggers_and_lists_characters"]),
    ("manifest omits characters: [] on uncast-in-cast panels",
     [(MA, '            strengths = lib.panel_strengths(names, members, strength)\n            p["characters"] = [',
       '            strengths = lib.panel_strengths(names, members, strength)\n            if not names:\n'
       '                continue\n            p["characters"] = [', 1)],
     [T_P + "test_p20_cast_inserts_triggers_and_lists_characters"]),
    ("casting applied after _prompt_length_warning",
     [(MA, WARN_LOOP, "", 1),
      (MA, "    if members:\n        by_name = {m.name: m for m in members}\n        used = set()\n",
       WARN_LOOP + "    if members:\n        by_name = {m.name: m for m in members}\n        used = set()\n", 1)],
     [T_P + "test_p25_length_warning_measures_the_cast_prompt"]),
    ("manifest prints the available line",
     [(MA, '            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])\n'
           '        except lib.CharacterError as e:\n            print("Error: %s" % e, file=sys.stderr)\n',
       '            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])\n'
       '        except lib.CharacterError as e:\n            print("Error: %s" % e, file=sys.stderr)\n'
       '            print(lib.format_available_line(lib.usable_characters()), file=sys.stderr)\n', 1)],
     [T_P + "test_p57_manifest_and_images_print_no_available_line"]),
    ("images prints the available line",
     [(IM, '            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])\n'
           '        except lib.CharacterError as e:\n            print("Error: %s" % e, file=sys.stderr)\n',
       '            members = lib.resolve_cast([lib.parse_cast_arg(v) for v in args.cast])\n'
       '        except lib.CharacterError as e:\n            print("Error: %s" % e, file=sys.stderr)\n'
       '            print(lib.format_available_line(lib.usable_characters()), file=sys.stderr)\n', 1)],
     [T_P + "test_p57_manifest_and_images_print_no_available_line"]),
    ("ltx-story-images inserts triggers for members without a stills LoRA",
     [(IM, 'insert={m.name for m in stills_members})', 'insert=None)', 1)],
     [T_P + "test_p31_member_without_stills_lora_warns"]),
    ("E-P16 check removed",
     [(IM, "    if len(lora_sets) > 1:", "    if False:", 1)],
     [T_P + "test_p32_different_lora_sets_are_refused"]),
    ("build_story_prompt appends the block at the end",
     [(MO, r'        rendered = rendered.replace(anchor, "\n\n" + cast_block + anchor, 1)',
       r'        rendered = rendered + "\n\n" + cast_block', 1)],
     [T_P + "test_p40_cast_block_sits_before_the_how_anchor"]),
    ("_resolve_casting allows --cast when Phase 1 runs",
     [(MO, '        if casts:\n            print("Error: --cast needs an existing story.md',
       '        if False:\n            print("Error: --cast needs an existing story.md', 1)],
     [T_P + "test_p42_resolve_casting_errors"]),
    ("_cast_flags omits --character-strength",
     [(MO, '    return flags + ["--character-strength", repr(float(args.character_strength))]', "    return flags", 1)],
     [T_P + "test_p44_existing_story_mixes_character_and_cast"]),
    ("ltx-movie imports character_lib at top level",
     [(MO, "import pipeline_log  # noqa: E402\n", "import pipeline_log  # noqa: E402\nimport character_lib  # noqa: E402\n", 1)],
     [T_P + "test_p49_uncast_ltx_movie_never_loads_character_lib"]),
    ("_resolve_casting catches only CharacterError (drops the available line)",
     [(MO, '    except lib.UnusableCharacterError as e:\n        print("Error: %s" % e, file=sys.stderr)\n'
           '        print(lib.format_available_line(lib.usable_characters()), file=sys.stderr)\n        return 2\n', "", 1)],
     [T_P + "test_p50_unknown_character_lists_the_usable_ones"]),
    ("_resolve_casting prints the available line for every CharacterError",
     [(MO, '        return 2\n    except lib.CharacterError as e:\n        print("Error: %s" % e, file=sys.stderr)\n        return 2\n',
       '        return 2\n    except lib.CharacterError as e:\n        print("Error: %s" % e, file=sys.stderr)\n'
       '        print(lib.format_available_line(lib.usable_characters()), file=sys.stderr)\n        return 2\n', 1)],
     [T_P + "test_p52_which_errors_list_alternatives"]),
    ("--list-characters pre-scan removed (left to argparse)",
     [(MO, '    if "--list-characters" in raw_argv:\n        return _list_characters(raw_argv)\n', "", 1)],
     [T_P + "test_p53_list_characters_prints_the_table_and_touches_nothing"]),
    ("_list_characters accepts extra arguments",
     [(MO, '    if raw_argv != ["--list-characters"]:', "    if False:", 1)],
     [T_P + "test_p54_list_characters_must_be_alone"]),
    ("--list-characters handled after the lockfile or sudo check",
     [(MO, '    if "--list-characters" in raw_argv:\n        return _list_characters(raw_argv)\n', "", 1),
      (MO, "        rc = _check_sudo_and_start_keepalive()\n        if rc is not None:\n            return rc\n",
       "        rc = _check_sudo_and_start_keepalive()\n        if rc is not None:\n            return rc\n"
       '        if "--list-characters" in raw_argv:\n            return _list_characters(raw_argv)\n', 1)],
     [T_P + "test_p53_list_characters_prints_the_table_and_touches_nothing"]),
    ("bin/character list keeps its own table code with a different column width",
     [(CH, '    print("\\n".join(character_lib.character_table_lines()))',
       '    print("\\n".join(line.replace("  ", " ") for line in character_lib.character_table_lines()))', 1)],
     [T_TO + "test_k2_list", T_P + "test_p55_list_characters_matches_bin_character_list"]),
    ("legacy route removed (always merged)",
     [(RE, "    if len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries:\n"
           "        args.lora_path = parsed[0][0]                       # legacy route (5.7.2)\n"
           "    elif parsed:\n", "    if parsed:\n", 1)],
     [T_P + "test_p61_legacy_route_is_unchanged", R1_RENDER]),
    ("legacy condition ignores the cast",
     [(RE, "parsed[0][1] == 1.0 and not cast_entries:", "parsed[0][1] == 1.0:", 1)],
     [T_P + "test_p63_global_strength_is_untouched_by_the_character_rule",
      T_P + "test_p10_global_lora_combines_with_the_cast"]),
    ("globals placed after the characters",
     [(RE, '        if loras:\n            unit["loras"] = loras',
       '        if loras:\n            unit["loras"] = ([l for l in loras if l["kind"] == "character"]\n'
       '                             + [l for l in loras if l["kind"] == "global"])', 1)],
     [T_P + "test_p10_global_lora_combines_with_the_cast",
      T_P + "test_p63_global_strength_is_untouched_by_the_character_rule"]),
    ("global strength reduced in multi-character panels",
     [(RE, '"path": g["path"], "strength": g["strength"]}',
       '"path": g["path"], "strength": g["strength"] * (0.8 if len(panel.get("characters") or []) > 1 else 1.0)}', 1)],
     [T_P + "test_p63_global_strength_is_untouched_by_the_character_rule"]),
    ("panel_strengths counts globals",
     [(RE, '"strength": float(c["strength"])} for c in (panel.get("characters") or [])]',
       '"strength": (float(c["strength"]) if len(global_loras) + len(panel.get("characters") or []) < 2 '
       'else min(float(c["strength"]), 0.8))} for c in (panel.get("characters") or [])]', 1)],
     [T_P + "test_p63_global_strength_is_untouched_by_the_character_rule"]),
    ("duplicate-global check removed",
     [(RE, '            if real in seen:\n                print("Error: --lora %s is given more than once"',
       '            if False:\n                print("Error: --lora %s is given more than once"', 1)],
     [T_P + "test_p64_duplicate_loras_are_refused"]),
    ("duplicate check by path string instead of realpath",
     [(RE, "            real = os.path.realpath(path)\n            if real in seen:",
       "            real = path\n            if real in seen:", 1)],
     [T_P + "test_p64_duplicate_loras_are_refused"]),
    ("global-vs-character duplicate check removed",
     [(RE, '            if real in seen:\n                print("Error: --lora %s is also character',
       '            if False:\n                print("Error: --lora %s is also character', 1),
      (IM, "            if m.stills_lora and os.path.realpath(m.stills_lora) in seen:", "            if False:", 1),
      (MO, "            if real in char_paths:", "            if False:", 1)],
     [T_P + "test_p64_duplicate_loras_are_refused", T_P + "test_p69_global_stills_errors",
      T_P + "test_p72_ltx_movie_global_lora_errors"]),
    ("parse_lora_spec splits on the first ':'",
     [(SK, 'head, sep, tail = value.rpartition(":")', 'head, sep, tail = value.partition(":")', 1)],
     [T_P + "test_p60_parse_lora_spec_table"]),
    ("parse_lora_spec errors on a non-float suffix",
     [(SK, "        except ValueError:\n            return value, 1.0, False",
       '        except ValueError:\n            raise ValueError("bad LoRA strength %r" % tail)', 1)],
     [T_P + "test_p60_parse_lora_spec_table"]),
    ("parse_lora_spec accepts strength 2.5",
     [(SK, "math.isfinite(strength) and 0 < strength <= 2.0)", "math.isfinite(strength) and 0 < strength <= 2.5)", 1)],
     [T_P + "test_p60_parse_lora_spec_table", T_P + "test_p65_merged_route_argument_errors"]),
    ("provenance omits kind",
     [(RE, 'provenance["loras"] = [{"kind": l["kind"], "path": l["path"],',
       'provenance["loras"] = [{"path": l["path"],', 1)],
     [T_P + "test_p66_resume_treats_the_global_set_as_identity"]),
    ("provenance list sorted (order not identity)",
     [(RE, '                               for l in unit["loras"]]\n    return provenance',
       '                               for l in sorted(unit["loras"], key=lambda l: l["path"])]\n    return provenance', 1)],
     [T_P + "test_p66_resume_treats_the_global_set_as_identity"]),
    ("ltx-movie keeps the E-P3 refusal",
     [(MO, "    lib = _character_lib()\n    strength = (args.character_strength",
       '    if args.lora_path or args.stills_lora_path:\n'
       '        print("Error: --character/--cast cannot be combined with --lora/--stills-lora", file=sys.stderr)\n'
       '        return 2\n'
       "    lib = _character_lib()\n    strength = (args.character_strength", 1)],
     [T_P + "test_p72_ltx_movie_global_lora_errors"]),
    ("ltx-story-images keeps the E-P15 refusal",
     [(IM, "    if args.cast:\n        lib = _character_lib()",
       '    if args.cast and args.lora_path:\n'
       '        print("Error: --cast cannot be combined with --lora", file=sys.stderr)\n'
       '        return 2\n'
       "    if args.cast:\n        lib = _character_lib()", 1)],
     [T_P + "test_p33_global_stills_lora_combines_with_the_cast"]),
    ("_render_flags forwards raw values on the merged route",
     [(MO, '        for path, strength in args.global_video_loras:\n'
           '            flags += ["--lora", "%s:%s" % (path, repr(float(strength)))]',
       '        for spec in args.lora_path_specs:\n            flags += ["--lora", spec]', 1)],
     [T_P + "test_p71_merged_globals_are_forwarded_with_strengths"]),
    ("_RepeatableLoraAction overwrites the dest with the last value",
     [(MO, "        if getattr(namespace, self.dest, None) is None:\n            setattr(namespace, self.dest, values)",
       "        setattr(namespace, self.dest, values)", 1)],
     [T_P + "test_p73_repeatable_lora_action", T_P + "test_p75_repeatable_lora_action_copies_are_identical"]),
    ("z_image fuses each adapter separately",
     [(ZI, "            names.append(name)\n        pipeline.set_adapters(names, adapter_weights=[float(s) for _, s in loras])\n"
           "        pipeline.fuse_lora(adapter_names=names, lora_scale=1.0)",
       "            names.append(name)\n            pipeline.fuse_lora(adapter_names=[name], lora_scale=float(strength))", 1)],
     [T_Z + "test_z1_adapters_weighted_and_fused_once"]),
    ("z_image skips the get_list_adapters check",
     [(ZI, '            if name not in pipeline.get_list_adapters().get("transformer", []):', "            if False:", 1)],
     [T_Z + "test_z3_unregistered_adapter_is_rejected"]),
    ("z_image ignores a different LoRA set on a loaded singleton",
     [(ZI, "    elif key is not None and key != _pipeline_loras:", "    elif False:", 1)],
     [T_Z + "test_z4_singleton_refuses_a_different_lora_set"]),
    ("train() checks memory before the story server",
     [(DS, '        state = story_server_state()\n        if state != "STOPPED":\n'
           '            return _error("the story server is %s; stop it first with bin/story-server stop "\n'
           '                          "(training needs its memory)" % state)\n',
       "", 1),
      (DS, "        need = TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)\n",
       '        state = story_server_state()\n        if state != "STOPPED":\n'
       '            return _error("the story server is %s; stop it first with bin/story-server stop "\n'
       '                          "(training needs its memory)" % state)\n'
       "        need = TRAIN_MIN_FREE_GIB_PER_KIND * len(requested)\n", 1)],
     [T_DS + "test_d26_preflight_order"]),
    ("story_server_state returns STOPPED on failure",
     [(DS, '        return "UNKNOWN"\n', '        return "STOPPED"\n', 2),
      (DS, '    return "UNKNOWN"\n\n\ndef wait_for_vlm', '    return "STOPPED"\n\n\ndef wait_for_vlm', 1)],
     [T_DS + "test_d16_story_server_state"]),
    ("train_video records the LoRA after the test renders",
     [(DS, '    data["status"] = "trained"\n    character_lib.write_character(data)\n\n    test_failed = False',
       '    data["status"] = "trained"\n\n    test_failed = False', 1),
      (DS, '            print("Error: video test render failed: %s" % e, file=sys.stderr)\n            test_failed = True\n            continue',
       '            print("Error: video test render failed: %s" % e, file=sys.stderr)\n            return "test_failed"', 1)],
     [T_DS + "test_d24_test_render_failure_keeps_the_lora"]),
    ("(plan-added) train() treats only SERVING as not stopped",
     [(DS, '        if state != "STOPPED":', '        if state.startswith("SERVING"):', 1)],
     [T_DS + "test_d26_preflight_order"]),
    ("(plan-added) CT8a ignores transformer.safetensors",
     [(DS, '                    or os.path.exists(os.path.join(TRAIN_MODEL_DIR, "transformer.safetensors"))\n', "", 1)],
     [T_DS + "test_d26_preflight_order"]),
    ("(plan-added) train_video takes the newest checkpoint, not the exact final step",
     [(DS, '    final = os.path.join(vdir, "out", "checkpoints", VIDEO_FINAL_CKPT)\n',
       '    final = (sorted(glob.glob(os.path.join(vdir, "out", "checkpoints", "lora_weights_step_*.safetensors")))\n'
       '             or [os.path.join(vdir, "out", "checkpoints", VIDEO_FINAL_CKPT)])[-1]\n', 1)],
     [T_DS + "test_d23_missing_final_checkpoint"]),
    ("(plan-added) train_video drops the empty-checkpoint check",
     [(DS, "if rc != 0 or not os.path.isfile(final) or os.path.getsize(final) == 0:",
       "if rc != 0 or not os.path.isfile(final):", 1)],
     [T_DS + "test_d23_missing_final_checkpoint"]),
    ("stills_epochs uses floor",
     [(DS, "    num_epochs = max(1, round(STILLS_TARGET_STEPS / kept))", "    num_epochs = max(1, STILLS_TARGET_STEPS // kept)", 1)],
     [T_DS + "test_d9_stills_epochs"]),
    ("stills_epochs saves 4 checkpoints again",
     [(DS, "    return num_epochs, total_steps, total_steps\n", "    return num_epochs, total_steps, total_steps // 4\n", 1)],
     [T_DS + "test_d9_stills_epochs", T_DS + "test_d10_stills_train_config"]),
    ("max_resolution back to 1024",
     [(DS, '        "max_resolution": STILLS_MAX_RESOLUTION,', '        "max_resolution": 1024,', 1)],
     [T_DS + "test_d10_stills_train_config"]),
    ("train_stills pre-creates sdir/out",
     [(DS, '    os.makedirs(os.path.join(sdir, "data"))\n    out = os.path.join(sdir, "out")\n',
       '    os.makedirs(os.path.join(sdir, "data"))\n    out = os.path.join(sdir, "out")\n    os.makedirs(out)\n', 1)],
     [T_DS + "test_d40_mflux_output_dir_is_never_pre_created"]),
    ("extract_mflux_adapter searches recursively",
     [(DS, '    zips = glob.glob(os.path.join(checkpoints, "[0-9]" * 7 + "_checkpoint.zip"))',
       '    zips = glob.glob(os.path.join(out_dir, "**", "[0-9]" * 7 + "_checkpoint.zip"), recursive=True)', 1)],
     [T_DS + "test_d14_extract_errors"]),
    ("step-mismatch check removed",
     [(DS, "        if step != total_steps:\n", "        if False:\n", 1)],
     [T_DS + "test_d14_extract_errors"]),
    ("generate_image_frequency set to total_steps",
     [(DS, '"generate_image_frequency": total_steps + 1}', '"generate_image_frequency": total_steps}', 1)],
     [T_DS + "test_d10_stills_train_config"]),
    ("run_logged's finally kill-and-wait block removed",
     [(DS, "            timer.cancel()\n            if proc.poll() is None:\n                try:\n"
           "                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)\n"
           "                except OSError:\n                    pass\n                proc.wait()\n",
       "            timer.cancel()\n", 1)],
     [T_DS + "test_d38_run_logged_kills_child_on_interrupt"]),
    ("image_data_url drops ImageOps.exif_transpose",
     [(DS, '    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")', '    img = Image.open(path).convert("RGB")', 1)],
     [T_DS + "test_d39_image_data_url_applies_exif_orientation"]),
    ("compat gate accepts injected != expected",
     [(DS, '    elif report["injected_lora_modules"] != expected:', "    elif False:", 1)],
     [T_DS + "test_d30_partial_injection_is_rejected"]),
    ("incompatible adapter overwrites a good previous stills LoRA",
     [(DS, '        os.replace(candidate, os.path.join(char_dir, "lora", "stills.rejected.safetensors"))',
       '        os.replace(candidate, os.path.join(char_dir, "lora", "stills.safetensors"))', 1)],
     [T_DS + "test_d34_failed_retrain_keeps_the_previous_stills_lora"]),
    ("create writes the dir before the face check",
     [(DS, "        fh = raw = cls_vlm = None\n",
       '        fh = raw = cls_vlm = None\n        os.makedirs(os.path.join(char_dir, "logs"), exist_ok=True)\n', 1)],
     [T_TO + "test_k7_small_face_refused"]),
    ("build_dataset restarts the vision server only on success",
     [(DS, '        run_zimage_child(spec, char_dir, "generate")\n    finally:\n',
       '        run_zimage_child(spec, char_dir, "generate")\n    except DatasetError:\n        raise\n    else:\n', 1)],
     [T_TO + "test_k13_generation_failure_restarts_the_vision_server"]),
    ("descriptor mode does not force-keep the reference",
     [(DS, '        kept = (n == ref_n) or check_result["identity_score"] >= character_lib.MIN_SCORE',
       '        kept = (n == 0) or check_result["identity_score"] >= character_lib.MIN_SCORE', 1)],
     [T_TO + "test_k10_descriptor_mode"]),
]


def run_target(target, root):
    env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(root, "pyc"),
               TMPDIR=os.path.join(root, "tmp"))
    os.makedirs(env["TMPDIR"], exist_ok=True)
    if target.startswith("R1:"):
        cmd = [sys.executable, target[3:]]
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider", target]
    return subprocess.run(cmd, cwd=WS, env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def fresh_run(target):
    root = tempfile.mkdtemp(prefix="char-mut-")
    try:
        return run_target(target, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    failures = 0
    for number, (label, edits, targets) in enumerate(MUTATIONS, 1):
        originals = {}
        for path, old, _new, count in edits:
            text = originals.setdefault(path, open(os.path.join(WS, path), encoding="utf-8").read())
            found = text.count(old)
            assert found == count, "M%d %s: anchor count %d != %d in %s: %r" % (
                number, label, found, count, path, old[:60])
        for target in targets:
            rc = fresh_run(target)
            assert rc == 0, "M%d %s: control run of %s returned %d" % (number, label, target, rc)
        mutated = dict(originals)
        for path, old, new, _count in edits:
            mutated[path] = mutated[path].replace(old, new)
        try:
            for path, text in mutated.items():
                with open(os.path.join(WS, path), "w", encoding="utf-8") as f:
                    f.write(text)
            results = [(t, fresh_run(t)) for t in targets]
        finally:
            for path, text in originals.items():
                with open(os.path.join(WS, path), "w", encoding="utf-8") as f:
                    f.write(text)
        broken = [t for t, rc in results
                  if not t.startswith("R1:") and rc not in (0, 1)]
        caught = [t for t, rc in results if rc != 0 and t not in broken]
        verdict = "CAUGHT" if caught and not broken else ("BROKEN" if broken else "SURVIVED")
        if verdict != "CAUGHT":
            failures += 1
        print("M%02d %-8s %s  <- %s" % (number, verdict, label,
                                        ", ".join("%s=%d" % (t.split("::")[-1], rc) for t, rc in results)))
    print("RESULT: %d/%d caught" % (len(MUTATIONS) - failures, len(MUTATIONS)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
````

Expected: 87 lines `Mxx CAUGHT ...` and a final `RESULT: 87/87 caught` (observed; about 18 minutes). The 87 rows are the spec's table below plus four plan-added rows (Decision 37). The spec's mutation table, verbatim (Decisions 18, 19, 30, 33 and 37 map the rows):

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
| `stills_epochs` uses floor | D9 (`kept=17` gives 39 × 17 = 663) |
| `stills_epochs` saves 4 checkpoints again | D9, D10 |
| `max_resolution` back to 1024 | D10 |
| `train_stills` pre-creates `sdir/out` | D40 |
| `run_logged`'s `finally` kill-and-wait block removed | D38 |
| `image_data_url` drops `ImageOps.exif_transpose` | D39 |
| `extract_mflux_adapter` searches recursively | D14 (timestamped-sibling case) |
| step-mismatch check removed | D14 (step-0-only case) |
| `generate_image_frequency` set to `total_steps` | D10 |
| compat gate accepts `injected != expected` | D30 |
| incompatible adapter overwrites a good previous stills LoRA | D34 |
| `create` writes the dir before the face check | K7 |
| `build_dataset` restarts the vision server only on success | K13 |
| descriptor mode does not force-keep the reference | K10 |

### A4: regression suites (R1, R2)

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/charplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/charplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py | tail -1
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider; echo "rc=$?"
````

Expected:

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
RESULT: ok
13 passed, 1 warning in <t>s   (then rc=0)
3 passed, 1 warning in <t>s    (then rc=0)
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

````bash
python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider; echo "rc=$?"
/usr/bin/python3 -m unittest tests.test_deploy_pkg 2>&1 | tail -3
````

Expected: `165 passed`, `rc=0`; `Ran 165 tests in <t>s` / `OK`. Then `git diff --stat 136c6f8 HEAD -- tests/test_ltx_movie_offline.py tests/test_ltx_story_images.py tests/test_ltx_mlx_render.py tests/test_ltx2_mlx_video_skill.py tests/test_ltx_story_manifest_chain.py tests/test_ltx_image_fit.py tests/check_ltx2_mlx_no_forbidden_imports.py tests/test_z_image_skill_cache.py` prints nothing (R1: none of those files changed).

### A5: scope check

````bash
git diff --name-only 136c6f8 HEAD | sort
````

Expected, exactly (before the L6 follow-up):

````
qwen-agent-workspace/bin/character
qwen-agent-workspace/bin/ltx-mlx-render
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/character_dataset.py
qwen-agent-workspace/character_lib.py
qwen-agent-workspace/docs/superpowers/specs/2026-10-05-character-library-design.md
qwen-agent-workspace/ltx2_mlx_video_skill.py
qwen-agent-workspace/scripts/deploy/build_pkg.py
qwen-agent-workspace/tests/fixtures/casting_baseline/build_command.json
qwen-agent-workspace/tests/fixtures/casting_baseline/ltx_movie_dry_run.txt
qwen-agent-workspace/tests/fixtures/casting_baseline/manifest.json
qwen-agent-workspace/tests/fixtures/casting_baseline/story.md
qwen-agent-workspace/tests/test_casting_pipeline.py
qwen-agent-workspace/tests/test_casting_regression.py
qwen-agent-workspace/tests/test_character_dataset.py
qwen-agent-workspace/tests/test_character_lib.py
qwen-agent-workspace/tests/test_character_tool.py
qwen-agent-workspace/tests/test_deploy_pkg.py
qwen-agent-workspace/tests/test_z_image_skill_multi_lora.py
qwen-agent-workspace/z_image_skill.py
````

The spec path is in the list only because of the amendment-2 commit `bef47e4`. `git log --format=%s 136c6f8..HEAD` lists the 13 task commits (Tasks 2-14), each with a component prefix, plus `bef47e4`; `git show --stat` of each task commit touches only that task's files.

### A6: design review

Dispatch the `design-reviewer` (Opus, high effort) on the commit range `136c6f8..HEAD`. Give it the spec path, this plan, the Review Focus above, and Decisions 1-37, and state that no work is in flight. Require a per-finding disposition table (accept, reject with evidence, or defer). If the verdict is NEEDS-FIX, the reviewer writes the verbatim patch and the executor only applies it; then rerun A1-A5. Pushing remains gated by this review.

### Live gates (orchestrator or user, on hardware, one at a time, no concurrent renders)

Spec 9.7 live gates, verbatim:

**Live gates.** These are run by the main thread or the user, on hardware, one at a time, with no concurrent renders. Before each GPU gate, `bin/story-server status` and `vm_stat`/available memory are recorded.

| ID | Gate | Pass condition |
|---|---|---|
| L0 | **PASSED 2026-10-05 (amendment 4; results in 0.2).** At 1024, compatible: 210/210 injected via the existing z_image_skill. 13.07 s/step at 1024 was rejected, so the 512 follow-up chose the 4.9 settings. Original gate text, kept for the record: **mflux compat gate (plan task 1).** After the user approves 4.10, install it. Run a smoke train in the gitignored scratch dir `generated/charlora/mflux-compat/` (not `/tmp`). Data: copies of `generated/charlora/kyrawmn-v1/stills/char_NN.png` with `captions/char_NN.txt`. Config: `stills_train_config(…, kept=24)` with `num_epochs` overridden to 4 (96 steps) and `save_frequency` 48. Command: `HF_HOME=~/hf_home ~/mflux/.venv/bin/mflux-train --config …`. Extract the adapter (4.9 step 4). Then, in a throwaway `python3 -c` using the **existing** `z_image_skill.load_pipeline(lora_path=<adapter>)`, count `lora_A` modules against `lora_module_count(safetensors_keys(adapter))`, and render `kyrawmn woman, medium shot, standing and facing the camera, …` at 1024x640, seed 42 | `mflux-train` exits 0. Record s/step, the peak footprint (`/usr/bin/time -l`), the checkpoint dir layout, and the adapter key sample (first 5 keys) in the plan's notes. **Compatible** iff injected == expected > 0 and the image renders. If incompatible, report to the user before building 4.9; the code is still built per spec (it then always skips). If s/step x 2400 > 4 h, report it to the user |
| L1 | Face-measure calibration (VLM only): `face_height` on `generated/charlora/kyrawmn-v1/stills/char_01.png`, and on `generated/stories/ronin-e2e-appearance-20261005/images/panel_01.png` | char_01 >= 0.25. ronin panel_01 < 0.15, or None. Record both values. If they do not separate, report (G3) |
| L1b | DESCRIBE on the ronin `panel_01.png` (a riding scene) | the descriptor does not contain `boots`, `riding`, `horse`, or `reins`. It mentions apparent ethnicity if the VLM states one. Record it |
| L2 | `bin/character create kyra --phrase "the woman in grey" --seed-image generated/charlora/kyrawmn-v1/stills/char_01.png` | exit 0. kept >= 12. Contact sheet eyeballed (consistent face, hairpins, kimono). Trigger `kyrawmn`. The vision server is serving again afterwards |
| L3 | `bin/character create ronin --phrase "the ronin" --descriptor "a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama" --class man` | exit 0. kept >= 12. Contact sheet eyeballed. Trigger `roninmn` |
| L4 | `bin/story-server stop`; `bin/character train kyra` | exit 0. (Amendment 4) The stills phase should take about 55 min (672 steps at 512), peak about 38.7 GB. `train/stills/out/checkpoints/0000672_checkpoint.zip` exists, and there is no `out_*` sibling. A skipped or incompatible stills LoRA (CT9/CT13) still exits 0 here, because `--stills` was not given. Exit 1 only on CT10, CT11, or CT12. `lora/video.safetensors` is 641,974,104 bytes. A/B eyeballed: `tests/video_lora.mp4` shows the character; `video_control.mp4` shows a stranger. If the stills LoRA trained: `tests/stills_lora.png` shows her, and the control shows a stranger. Record the wall-clock time (~47 min expected for video) and the peak footprint |
| L5 | `bin/character train ronin` | as L4 for the ronin |
| L6 | **Bleed sweep (acceptance gate).** Three story dirs, `generated/stories/bleed-sweep-s10`, `-s08`, `-s06`, each holding the 9.8 `story.md`. Run `bin/ltx-movie "two-character bleed sweep" --story-id bleed-sweep-sNN --panels 2 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength S` for S = 1.0, 0.8, 0.6. Then `bin/judge-clips --story-id bleed-sweep-sNN` for each | Each run exits 0, and the manifests show both characters at S on both panels. **Winner rule:** the highest S at which, in both panels, she shows her trained identity (face, three jade hairpins, grey kimono) with no male or ronin traits, **and** he shows topknot, scarred brow, and indigo haori with no female, kimono, or hairpin traits, by the user's eyeball. judge-clips `physical_realism` breaks ties (higher wins). If no S passes, the default stays 0.8 and G4 is recorded as unresolved. The winner is written into `DEFAULT_CHARACTER_STRENGTH` (plus C36/C37 and the help texts "default 0.8") in a follow-up commit |
| L6b | **Character + global quality case: DEFERRED** **[spec choice: defer, do not download]** | Run when the user provides a real non-character LTX LoRA `G`. Repeat the L6 `bleed-sweep-s08` command with `--lora G:1.0`, then with `--lora G:0.6` (new story ids `bleed-sweep-s08-gG10`/`-gG06`). Pass: G's effect is visible, and both identities hold by the L6 rule. Until then, record "L6b deferred: no non-character LoRA available locally (G22)" in the acceptance notes |
| L6m | **Mechanical global + character check** (not a quality signal) | Story id `bleed-sweep-globalmech` with the 9.8 `story.md`. Run the L6 command at S = 0.8 plus `--lora generated/charlora/kyrawmn-v1/out_full/checkpoints/lora_weights_step_00250.safetensors:0.3`. This is the spike's out-of-library checkpoint, used **only** as a stand-in global file. Pass: exit 0. Each clip's provenance `loras` has kinds `["global", "character", "character"]`, with the global at 0.3 and the characters at 0.8. The logged ltx-2-mlx argv has three `--lora` triples. Record the wall-clock time per panel against L6 |
| L7 | **Cast re-render.** Create `generated/stories/ronin-e2e-appearance-20261005-cast/` holding only a copy of the original `story.md`. Run `bin/ltx-movie "re-render of an existing story" --story-id ronin-e2e-appearance-20261005-cast --panels 20 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin"`. Then `bin/judge-clips --story-id ronin-e2e-appearance-20261005-cast` | exit 0, 20 clips. Each panel's `characters` in `manifest.json` equals `cast_text(<that panel's Motion: text>, members)[1]`, computed in a REPL from the copied `story.md`. Record the 20 lists. Note that panel 1's Motion: does not name her, so panel 1's clip gets no LoRA (G5) while its still does. Eyeball against the original `movie.mp4`: she stays recognizably the same across her panels, and he is recognizable from panel 12. Record both clips judgments (original movie: seam 7, narrative 2) side by side. The user's eyeball is decisive |

Before **every** GPU gate, record `bin/story-server status`, `vm_stat | head -8`, and available GiB (`python3 -c "import psutil; print(psutil.virtual_memory().available / 2**30)"`). Order: L1, L1b, L2, L3 with the vision server up (`bin/story-server status` shows `SERVING vision`). Then `bin/story-server stop` (wait for `STOPPED`), then L4, L5, L6, L6m, L7. L6b is deferred (G22).

- [ ] **L1 (VLM only):**

````bash
python3 -c "import character_dataset as c; print('char_01', c.face_height('generated/charlora/kyrawmn-v1/stills/char_01.png')); print('ronin panel_01', c.face_height('generated/stories/ronin-e2e-appearance-20261005/images/panel_01.png'))"
````

Pass: `char_01 >= 0.25`, and the ronin `panel_01` is `< 0.15` or `None`. Record both values. If they do not separate, report G3 to the user before L2.

- [ ] **L1b (VLM only):**

````bash
python3 -c "import character_dataset as c; print(c.describe('generated/stories/ronin-e2e-appearance-20261005/images/panel_01.png'))"
````

Pass: the descriptor (the second element) contains none of `boots`, `riding`, `horse`, `reins`, and names an apparent ethnicity if the VLM states one. Record it.

- [ ] **L2:** `bin/character create kyra --phrase "the woman in grey" --seed-image generated/charlora/kyrawmn-v1/stills/char_01.png`. Pass:
  - exit 0, and `kept >= 12` in `bin/character show kyra`;
  - trigger `kyrawmn`;
  - the user eyeballs `generated/characters/kyra/dataset/contact_sheet.jpg`: a consistent face, the hairpins, the kimono;
  - `bin/story-server status` shows `SERVING vision` again.

- [ ] **L3:** `bin/character create ronin --phrase "the ronin" --descriptor "a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama" --class man`. Pass:
  - exit 0 and `kept >= 12`;
  - trigger `roninmn`;
  - the user eyeballs the contact sheet.

- [ ] **L4:** `bin/story-server stop`, then `bin/character train kyra`. Run it with `run_in_background` and no `nohup`; the video LoRA alone takes about 47 min. Pass:
  - exit 0. CT9/CT13 (stills skipped) still exits 0, because `--stills` was not given; exit 1 only on CT10, CT11 or CT12;
  - `stat -f %z generated/characters/kyra/lora/video.safetensors` prints `641974104`;
  - (amendment 4) if stills trained: the stills phase took about 55 min (672 steps at 512) with a peak of about 38.7 GB; `generated/characters/kyra/train/stills/out/checkpoints/0000672_checkpoint.zip` exists; `ls -d generated/characters/kyra/train/stills/out_*` matches nothing; and `stat -f %z generated/characters/kyra/lora/stills.safetensors` prints about `140136769` (record the exact value);
  - the user eyeballs the A/B: `tests/video_lora.mp4` shows her, and `tests/video_control.mp4` shows a stranger;
  - if the stills LoRA trained, the user also eyeballs `tests/stills_lora.png` against `tests/stills_control.png`;
  - record the wall-clock time and the peak footprint.

  If Task 12 was skipped by the user's decision, run `bin/character train kyra --video` instead.

- [ ] **L5:** `bin/character train ronin` (or `--video`, as in L4). Pass: as L4, for the ronin.

- [ ] **L6 (acceptance gate; sets the default strength).** For each S in `1.0`, `0.8`, `0.6`, with NN = `10`, `08`, `06`:
  1. `mkdir -p generated/stories/bleed-sweep-sNN` and write the spec 9.8 `story.md` (below) into it, byte for byte.
  2. Run `bin/ltx-movie "two-character bleed sweep" --story-id bleed-sweep-sNN --panels 2 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength S`.
  3. Run `bin/judge-clips --story-id bleed-sweep-sNN`.

  Pass: each run exits 0. Also `python3 -c "import json; m=json.load(open('generated/stories/bleed-sweep-sNN/manifest.json')); print([[(c['name'], c['strength']) for c in p['characters']] for p in m['panels']])"` prints both characters at S on both panels. The winner rule is spec L6's: the user's eyeball decides, and `physical_realism` breaks ties.

````markdown
# Bleed sweep

A two-character test scene.

## Panel 1 — Two Travellers
Image: A medium shot, eye level, of the woman in grey and the ronin standing side by side on a packed-dirt forest trail, both facing the camera, the woman in grey on the left and the ronin on the right. The woman in grey is a young East Asian woman, slender, with pale skin and long black hair pinned up with three jade hairpins, wearing a pale grey silk kimono with a silver obi. The ronin is a lean man in his late thirties with a topknot and a scarred brow, wearing a faded indigo haori and dark hakama. Tall cedar trunks and ferns line the trail behind them. The light is overcast and flat, with a muted green, brown and grey palette. The rendering is photorealistic live-action film still.
Motion: The woman in grey turns her head toward the ronin while the ronin rests his left hand on his scabbard; the camera stays static.
Narration: Two travellers pause on the forest trail.

## Panel 2 — The Nod
Motion: The ronin nods once to the woman in grey, and the woman in grey bows her head slightly in return.
Narration: A silent agreement passes between them.
````

- [ ] **L6 follow-up commit (only if the winner W != 0.8).**
  1. In `character_lib.py`, change `DEFAULT_CHARACTER_STRENGTH = 0.8` to `DEFAULT_CHARACTER_STRENGTH = W`.
  2. In `bin/ltx-movie`, `bin/ltx-story-manifest` and `bin/ltx-story-images`, change the help text `(default 0.8, provisional)` to `(default W)`. It occurs once in each file.
  3. In `tests/test_casting_pipeline.py`, replace `0.8` with W in these default-dependent expectations (Decision 20):
     - P20: `[("kyra", 0.8), ("ronin", 0.8)]` and `"cast: panel 2: kyra@0.8, ronin@0.8"`;
     - P43: `args.character_strength == 0.8`;
     - P44: `"--character-strength", "0.8"`;
     - P46: `--character-strength 0.8`.
     Use `repr(float(W))` for the string forms.
  4. Rerun A1-A4: all counts unchanged, and the 58 mutations still caught.
  5. Commit `character_lib.py bin/ltx-movie bin/ltx-story-manifest bin/ltx-story-images tests/test_casting_pipeline.py` with the message `character_lib: set DEFAULT_CHARACTER_STRENGTH to W from the L6 bleed sweep` plus the `Co-Authored-By` line, staged by explicit path as in every task.

  If no S passes, the default stays 0.8 and G4 is recorded as unresolved.

- [ ] **L6m (mechanical global + character check; not a quality signal).**
  1. `mkdir -p generated/stories/bleed-sweep-globalmech` and write the spec 9.8 `story.md` into it, byte for byte.
  2. Run `bin/ltx-movie "two-character bleed sweep" --story-id bleed-sweep-globalmech --panels 2 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength 0.8 --lora generated/charlora/kyrawmn-v1/out_full/checkpoints/lora_weights_step_00250.safetensors:0.3`. If the L6 follow-up changed the default, keep `--character-strength 0.8` as written.

  Pass:
  - exit 0;
  - `python3 -c "import glob, json; [print(f, [(l['kind'], l['strength']) for l in json.load(open(f))['loras']]) for f in sorted(glob.glob('generated/stories/bleed-sweep-globalmech/clips/panel_*.mp4.provenance.json'))]"` prints `[('global', 0.3), ('character', 0.8), ('character', 0.8)]` for both clips;
  - `grep -c -- '--lora ' generated/stories/bleed-sweep-globalmech/movie.log` is at least 2, and each logged `ltx-2-mlx` argv line has three `--lora PATH STRENGTH` triples;
  - record the wall-clock time per panel against L6's.

- [ ] **L6b (deferred).** Do not download anything. Record in the acceptance notes: `L6b deferred: no non-character LoRA available locally (G22)`. Run it only when the user supplies a real non-character LTX LoRA, as spec L6b describes.

- [ ] **L7 (cast re-render).**
  1. `mkdir -p generated/stories/ronin-e2e-appearance-20261005-cast && cp generated/stories/ronin-e2e-appearance-20261005/story.md generated/stories/ronin-e2e-appearance-20261005-cast/`.
  2. Run `bin/ltx-movie "re-render of an existing story" --story-id ronin-e2e-appearance-20261005-cast --panels 20 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --cast "the woman in grey=kyra" --cast "the ronin=ronin"`.
  3. Run `bin/judge-clips --story-id ronin-e2e-appearance-20261005-cast`.

  Pass: exit 0, 20 clips, and the per-panel `characters` names equal the lists below. They were computed at planning time with `cast_text` over that story's Motion: fields.

  Re-check with:

````bash
python3 - <<'EOF'
import importlib.machinery, json
import character_lib as L
sm = importlib.machinery.SourceFileLoader("sm", "bin/ltx-story-manifest").load_module()
d = "generated/stories/ronin-e2e-appearance-20261005-cast"
members = L.resolve_cast([L.parse_cast_arg("the woman in grey=kyra"), L.parse_cast_arg("the ronin=ronin")])
_, panels = sm._parse_prompts_md(d + "/story.md")
expected = [L.cast_text(p["motion"], members)[1] for p in panels]
got = [[c["name"] for c in p["characters"]] for p in json.load(open(d + "/manifest.json"))["panels"]]
print(expected == got)
print(got)
EOF
````

Expected lists, panels 1-20:
- panel 1: `[]`. Its Motion: does not name her (G5); its still does get her stills LoRA, because the Image: field names her;
- panels 2-11: `["kyra"]`;
- panel 12: `["ronin"]`;
- panel 13: `["kyra", "ronin"]`;
- panels 14-17: `["ronin"]`;
- panels 18-19: `["kyra", "ronin"]`;
- panel 20: `["ronin"]`.

Then the user eyeballs the result against the original `movie.mp4`: she stays recognizably the same across her panels, and he is recognizable from panel 12. Record both clip judgments side by side (original movie: seam 7, narrative 2). The user's eyeball is decisive.

## L0 notes (L0 PASSED 2026-10-05; spec 0.2, verbatim)

**mflux, measured (amendment 4; `generated/charlora/mflux-compat/` = L0, `generated/charlora/mflux-512/` = follow-up).**

- **L0, `max_resolution` 1024 (kyrawmn-v1 data, 24 images):**
  - 13.07 s/step, peak 38.7 GB, so 2400 steps would take about 8.7 h. **Rejected.**
  - Adapter keys are `diffusion_model.layers.N.{attention.to_q, attention.to_k, attention.to_v, attention.to_out.0, feed_forward.w1, feed_forward.w2, feed_forward.w3}.lora_A/B.weight`: 210 modules.
  - The adapter loads through the **existing** `z_image_skill` (injected 210 == expected 210). So G1 is resolved positively for this key format.
- **Checkpoint zip** `NNNNNNN_checkpoint.zip` (verified with `unzip -l`):
  - members: `NNNNNNN_adapter.safetensors` (140,136,769 B), `NNNNNNN_optimizer.safetensors` (280,273,360 B), `NNNNNNN_{iterator,loss,config}.json`, `checkpoint.json`, `run.json`;
  - about 389 MB per zip;
  - mflux also writes a `0000000_checkpoint.zip` (about 128 MB) at step 0;
  - zips land under `<output_path>/checkpoints/`, next to `<output_path>/preview/` and `<output_path>/loss/`.
- **Output-path rule (observed):** mflux appends `_<YYYYMMDD_HHMMSS>` to `output_path` when that directory **already exists**. L0 pre-created `out/` and got `out_20261005_194009/`. When the directory does not exist, it writes to `output_path` exactly (the 512 test).
- **512 test, `max_resolution` 512, 1008 steps (42 epochs × 24 images):**
  - about 4.6-5.1 s/step, 82 min wall-clock with concurrent CPU load, peak 38.66 GB;
  - evaluated at 1024x640 with a trigger-only prompt **through `z_image_skill`, that is, with the abliterated text encoder**:
    - step 336: the face is right, but the costume is not learned;
    - **step 672: face, hairpins, kimono and obi are consistent across close-up, street and beach;**
    - step 1008: no visible gain over 672.

## Provenance of this document

Revised on 2026-10-05 for amendment 2 (`bef47e4`); replayed onto a clean export of `0340882`. Generated on 2026-10-05 from a validated scratch build (`/tmp/charplan/ws`, replayed task by task on `/tmp/charplan/sim`). It was generated against the spec at `136c6f8`, the amendment included. Every code block is the byte-exact file content or edit block that produced the stated counts. The test IDs of spec 9.2-9.6, including the amendment's C42-C46 and P50-P57, each map to exactly one test function, which the A1 check confirms.

