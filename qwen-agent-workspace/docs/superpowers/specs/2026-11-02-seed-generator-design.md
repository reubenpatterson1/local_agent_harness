# Seed generator: a Seeds tab that edits one source image into a few seed candidates

Date: 2026-11-02

Status: design spec. The user approved the design (scratchpad `seedgen-design-notes.md`, Sections 1-4) on 2026-11-02. This document carries that design without reopening it. Each detail the notes leave open is decided here and marked **[spec choice]**; Section 13 lists them all. Section 14 lists the points of the approved design that the code makes impossible or risky, with their resolution. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/seedgen-wt`, branch `seed-generator`, HEAD `9eb363c` (the seed-folder merge). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `9eb363c`.

Builds on **[MUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md` (routes, jobs, capabilities), **[VL]** `docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md` (job `vlm` policy), **[CE]** `docs/superpowers/specs/2026-10-21-character-seed-edit-design.md` (the Qwen-Image-Edit child) and **[SF]** `docs/superpowers/specs/2026-11-01-seed-folder-compose-design.md` (module style, Compose seed image).

Terms: the **source** is the image being edited. A **run** is one Generate: one `seed-edit` job and its directory `generated/seeds/runs/<run>/`. A **candidate** is one edited image of a run (1-4 per run). A **seed folder** is `generated/seeds/<folder>/`. A **backend** is `zimage`, `diffusers-bf16` or `mflux-q4`. Requirement IDs are SG1-SG69 and tests are SGT1-SGT34. No existing spec, test or source file uses `SG<n>` or `SGT<n>` IDs (checked with grep at `9eb363c`).

---

## 0. Scope

### 0.0 The approved design (binding summary)

1. A new movie-ui **Seeds** tab: one source + a prompt + a model → 1-4 candidates (default 4). The user picks; per candidate: **Keep** into a named seed folder, **Use in Compose**, **Edit again**. A before/after grid. A runs list. The Characters tab gets **New seed from this** on each still.
2. Storage: `generated/seeds/runs/<run>/` keeps every candidate of every run; `generated/seeds/<folder>/` holds kept seeds.
3. Models: **Z-Image (img2img)** (strength 0.10-0.90, default 0.45) and **Qwen-Image-Edit-2511**. Qwen's backend is chosen by memory at run time: diffusers bf16 when at least 64 GiB is available and the bf16 weights are cached (the `character_dataset.py` Qwen child), else mflux q4 from a separate venv `~/mflux-edit` (mflux pinned 0.24.0) with the pre-quantized q4 repo and the Lightning 8-step LoRA, else refused before loading with the reason.
4. One tool, `bin/seed-edit`, run as a normal queued GPU job of kind `seed-edit` (VLM lifecycle like other GPU kinds). Model loaded once per job. Content safety on every candidate. Progress lines `candidate 2/4 ok 41.3s`.
5. Six token-gated routes under `/api/seeds/`. Images through the existing `/files`.
6. `bin/seed-edit-setup` creates the venv and downloads the q4 repo and one Lightning file; it and every live check run only on the user's go.

### 0.1 Grounding (verified at `9eb363c`)

- **Routes.** `ROUTES` `movie_ui_server.py:69-131` (57 entries; `POST /api/uploads` at `:98`, `GET /files` last at `:130`). Handlers attached as `MovieUIHandler.h_* = _h_*` (`:1087-1097`, `:1573-1585`, `:2178-2182`). `ApiError(status, message)` → `{"error": message}` (`:134-139`). `resolve_ws` `:169-183`. `STORE_LOCK` (non-reentrant) `:36`. Route matching tries every regex in order and keeps looking after a method mismatch (`:393-399`).
- **Capabilities.** `MovieUIServer.__init__` creates `render`, `stills`, `story_server` as `{"ok": None, "reason": "probing", "checked": None}` (`:202-203`). `refresh_capabilities` runs the three probes on `probe_ws` (`:210-218`); it runs at startup in the probe thread (`start_threads` `:652-658`) and on `GET /api/host?refresh=1` (`:606-608`). `capability_snapshot` `:220-222`.
- **Jobs.** `job_summary` returns 15 keys, the last `seed_folder` (`:726-739`); `test_mut2_preview_argv_is_the_job_argv` pins the key set (`tests/test_movie_ui_http.py:342-344`). `server.progress` feeds `lib.ProgressParser(kind, fields)` (`:233-245`). `create_character_job`/`_character_job_locked` show the create-under-`STORE_LOCK` pattern (`:1431-1443`).
- **Uploads.** `_h_upload` stores `<STATE>/uploads/<sha256 hex>.<ext>` via `lib.write_bytes_atomic` and answers 201 `{"upload_id", "path", "bytes"}` (`:1118-1128`); `UPLOAD_TYPES` `:54-55`; `lib.UPLOAD_ID_RE` `movie_ui_lib.py:36`.
- **Files.** `_h_files` serves only realpaths under `<ws>/generated` or `<STATE>/uploads` (`:2105-2175`, roots `:2116-2117`). `_inside(path, base)` `:1922-1927`, `_json_in` `:1938-1946`, `_isfile_in` `:1949-1950`.
- **Characters.** `STILL_FILE_RE = ^char_[0-9]{2}\.png$` `:1302`. `_h_character` lists `<dirname(contact_sheet)>/stills/char_NN.png` (`:1350-1358`). The library is `$CHARACTER_LIBRARY_DIR` or `<ws>/generated/characters` (`:1467`, `character_lib.py:258-263`); a dataset lives in `<library>/<name>/dataset/` with stills in `dataset/stills/` (`character_dataset.py:952`, `:1060`). `lib.CHARACTER_NAME_RE` `movie_ui_lib.py:38`.
- **Library.** `utc_now` (`%Y-%m-%dT%H:%M:%SZ`) `movie_ui_lib.py:49-51`. `write_bytes_atomic`/`write_json_atomic` (0600, `os.replace`) `:88-104`. `read_json` `:107-113`. `new_job_id` `:165-171`. `create_job` (caller holds `STORE_LOCK`) `:174-190`. `job_vlm` `:421-436`, forbidden kinds `:434`. `job_state` `:855-860`. `run_light` `:1199-1226`, `tool_argv` `:1229-1231`, `last_line` `:1234-1237`, `LIGHT_TIMEOUT = 60` `:957`. `_is_int`, `_is_number`, `_argv_safe` `:1307-1381`. `STILLS_BASE_MODEL`, `ZIMAGE_TEXT_ENCODER` `:935-936`. `zimage_hub` `:1689-1691`, `hf_hub` `:1694-1696`, `repo_dir_name` `:1699-1700`, `zimage_hub_for` `:1703-1706`, `choose_snapshot` `:1709-1724`, `intact_scan`/`model_check` `:1735-1812`. `ProgressParser` `:2182-2296` (`_line` `:2221-2263`, generic non-story snapshot `:2274-2276`). `bin/model-download` already imports `movie_ui_lib` for hub paths (`bin/model-download:18-23`).
- **VLM lifecycle.** A `forbidden` job makes the runner run `bin/story-server stop` before the child, and the postflight restores the VLM when the queue is empty or the next job needs it (`movie_ui_lib.py:627-711`). It never stops the 8178 embed server ([VL] VR1/R4; `run_job` comment `:336-342`).
- **Qwen child (pinned).** `character_dataset.py` is in `PIPELINE_FILES` (`tests/test_movie_ui_builder.py:219-224`) and `test_mut26` fails on any diff from baseline `38005c3` (`:268-298`). Its child: `python character_dataset.py qwenedit --spec SPEC` (`main` `:1934-1948`), spec keys `image, model, lora_repo, lora_file, steps, true_cfg, skill, jobs[{prompt, output_path, seed, width, height, image?}], report_path`; it loads with `local_files_only=True` from the default HF cache, screens each image with `content_safety` under `spec["skill"]`, saves only safe images, prints `<basename(output_path)> <ok|blocked> <s.s>s` per job and writes the report at the end (`child_qwenedit` `:1839-1883`). Constants `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS = 8`, `EDIT_TRUE_CFG = 1.0`, `EDIT_MIN_AVAIL_GIB = 64.0` `:164-181`; `CREATE_MIN_FREE_GIB = 2.0` `:194`; `GENERATE_MIN_AVAIL_GIB = 20.0` `:197`; `AVAIL_WAIT_S = 600` `:199`. `busy_process` `:535-556`. `run_logged` (group kill on timeout) `:616-654`. `exit_with_parent` `:1825-1836`. Importing `character_dataset` costs only stdlib, PIL, psutil, `character_lib`, `ltx2_mlx_video_skill` (all stdlib-only) (`:20-49`).
- **Z-Image (pinned).** `z_image_skill.generate_variation(seed_image, prompt, output_path=None, strength=0.45, generator=None, ...)` builds the img2img pipeline once (singleton) and calls `content_safety.assert_image_safe` before saving, raising `ContentSafetyError` (`z_image_skill.py:251-272`). Scoped cache `$Z_IMAGE_HF_HOME` or `~/hf_home` (`:56-69`). It imports torch, diffusers, transformers and `content_safety` at top (`:43-49`).
- **Content safety.** `assert_image_safe(image, *, skill, prompt)` raises `ContentSafetyError`; imports numpy, torch, PIL, transformers (`content_safety.py:10-16`, `:84-100`).
- **mps_guard.** `preflight()` refuses while 8177 **or 8178** listens and without the qwen-serve-guard stand-down file, and imports torch in its census (`mps_guard.py:490-540`, `:245-270`); no image tool uses it.
- **mflux 0.24.0** (read from tag `v.0.24.0` with `gh api`). `from mflux.models.qwen.variants.edit.qwen_image_edit import QwenImageEdit`; `from mflux.models.common.config.model_config import ModelConfig`; `ModelConfig.qwen_image_edit_2511()` (`model_name="Qwen/Qwen-Image-Edit-2511"`). `QwenImageEdit(quantize, model_path, lora_paths, lora_scales, bake_lora, model_config)`; `QwenImageInitializer.init_edit` takes the transformer overrides (`zero_cond_t`) from `model_config`, not from the path. `generate_image(seed, prompt, image_paths, num_inference_steps, height, width, guidance, image_path, scheduler, negative_prompt)` → `GeneratedImage` with `.image` (PIL). A local `model_path` that exists is used as is (`PathResolution` rule `local`). `requires-python >= 3.11`; dependencies include `torch>=2.13`, `transformers>=5.5`, `huggingface-hub>=1.1.6`, `mlx>=0.32`.
- **This Mac (read-only checks).** `~/mflux/.venv` (mflux 0.21.0, from `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13`) exists; `~/mflux-edit` does not. `~/hf_home/hub` holds the Z-Image repos and `Falconsai/nsfw_image_detection`.
- **UI.** `index.html`: nav `:32-42`, `panel-compose` `:45-157` (seed image radio `c-res-seed` `:81-83`), `panel-characters` `:222-266` (`ch-gallery` `:251`). `app.js`: `S` `:13-17`, `FOLDER_BOXES`/`part` `:20-33`, `el` `:39-51`, `fileUrl` `:75-77`, `stopPolling` `:86-92`, `api` `:94-121`, `capability` `:210-213`, `renderBadges` `:215-235`, `selectWorkspace` `:281-288`, `TABS`/`showTab` `:307-322`, `updateComposeButtons` `:500-522`, `uploadFile` `:524-529`, `onSeedFile` `:531-544`, `openCharacter` `:1768-1784` (stills line `:1778`), `jobLabel` `:2232-2234`, `renderProgress` `:2249-2278`, `button` `:2296-2300`, `start` `:2654-2681`.
- **Static-page rules.** `test_mut24` and `test_ct27` forbid `https?://`, `\son[a-z]+=`, `style=`, `\balert\(`, `\bconfirm\(`, `\bprompt\(`, `\beval\(`, `new Function` in `index.html`, `app.js`, `app.css` (`tests/test_movie_ui_http.py:1037-1039`, `tests/test_movie_ui_seams.py:371-374`). `test_movie_ui_batch.py:500` pins the substring `["jobs", "log", "host", "batch"]`. Three tests pin the `const TABS = [...]` line (`tests/test_location_ui.py:389`, `tests/test_movie_ui_batch.py:495`, `tests/test_movie_ui_seams.py:351`).
- **Tests.** `tests/movie_ui_testutil.py`: `set_home`, `make_stub_workspace`, `stub_config`, `make_hf_cache(root, repo, files)` (`<root>/hub/models--…` with `refs/main`) `:298-327`, `Running`, `api`, `make_job`, `copy_ui` (fixed list `:463-465`), `PNG` (magic bytes only). `conftest.py` turns the VLM lifecycle off. Character tests stub external executables through env vars (`CHARACTER_MFLUX_TRAIN`, `character_dataset.py:209-210`). `NEW_PY` (`tests/test_movie_ui_builder.py:213-217`) files are compiled with `/usr/bin/python3` (3.9) and scanned (no `urllib`, no `match` statements, no `X | None`, no `load_module(`); the import allow-list covers `NEW_PY[:2]` only (`:255-266`).

### 0.2 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `bin/seed-edit` (new, Python) | the tool: argv, run.json, preflight, backend choice, three backends, probe (§2) |
| G2 | `seed_edit_mflux_child.py` (new) | the mflux q4 child (§3) |
| G3 | `bin/seed-edit-setup` (new, Python) | venv + downloads (§7) |
| G4 | `movie_ui_seedgen.py` (new) | pure request rules, folder rule, run ID, capability shape (§5.1) |
| G5 | `movie_ui_lib.py` | `job_vlm` kind, `seed_edit_argv`, `seed_edit_check`, progress hook (§4) |
| G6 | `movie_ui_server.py` | capability, 6 routes, `store_upload`, `job_summary` key `seed_run` (§5) |
| G7 | `static/movie-ui/index.html`, `app.js`, `app.css` | Seeds tab, Characters button, Jobs label (§6) |
| G8 | tests | `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_seedgen.py` (new); §9.2 edits |

Untouched: every file in `PIPELINE_FILES` (including `character_dataset.py`, `z_image_skill.py`, `bin/character`), `content_safety.py`, `mps_guard.py`, `movie_ui_seedfolder.py`, `movie_ui_batch.py`, the existing `~/mflux` venv. `test_mut26` passes unedited.

### 0.3 Out of scope

- Deleting or renaming runs or seed folders; batch-editing a whole folder (notes).
- Multi-image Qwen edits, negative prompts, steps/guidance controls, LoRAs on the edit models.
- mflux q8, or any download outside `bin/seed-edit-setup`.
- Stopping the 8178 embed server or any server other than the story server the VLM lifecycle already stops.
- A seed-edit entry on the Batches page; a CLI flag on `bin/ltx-movie`.
- Running `bin/seed-edit-setup`, a real model or a real server in tests.

### 0.4 Must-haves and nice-to-haves

Every SG requirement and SGT test is a must-have. There are no nice-to-haves.

---

## 1. Architecture

```
Seeds tab: source (upload | Edit again {run,n} | Characters {character,still}) + prompt + model
  Generate -> POST /api/seeds/runs: validate (400) -> bin/seed-edit --probe in ws (409) -> disk (409)
           -> mkdir runs/<run>, copy source.<ext> -> STORE_LOCK { job id, run.json, create_job }
dispatcher -> runner: VLM preflight (story-server stop; job vlm=forbidden)
           -> <py> bin/seed-edit --source … --run-dir …:
              args -> source + size -> run.json(running) -> preflight (disk, busy, backend, memory)
              -> zimage: in-process z_image_skill.generate_variation x N
              -> diffusers-bf16: child `character_dataset.py qwenedit --spec` (unchanged, screens itself)
              -> mflux-q4: child `~/mflux-edit/.venv/bin/python seed_edit_mflux_child.py --spec`,
                 parent screens each pending image with content_safety
              per candidate: final PNG -> run.json -> "candidate i/N <status> …"
           -> VLM postflight
page polls GET /api/seeds/runs/<run>; Keep / Use / Edit again; /files serves every image
```

- **SG1.** `movie_ui_seedgen.py` imports only `re`, `secrets`, `time` and `movie_ui_lib as lib`. It is Python 3.9-compatible, never writes, never starts a process; every function is pure except `new_run_id` (clock and random). The server imports it as `import movie_ui_seedgen as seedgen`. **[spec choice]** Same module pattern as `movie_ui_seedfolder.py`.
- **SG2.** `bin/seed-edit`, `bin/seed-edit-setup` and `seed_edit_mflux_child.py` are Python 3.9-compatible source (they compile under `/usr/bin/python3`; the child runs under the venv's 3.13). `bin/seed-edit` puts its workspace (`WS = dirname(dirname(realpath(__file__)))`) first on `sys.path` and imports at module top only the standard library and `movie_ui_lib as lib`. PIL, psutil, torch, `z_image_skill`, `content_safety` and `character_dataset` are imported only inside the run functions named in §2.
- **SG3.** Besides the ordinary job record, nothing is added under STATE except uploads written by the Use route (SG52). The run directory and its `run.json` are the only record of a run.

### 1.1 Constants

`movie_ui_seedgen.py`:
```python
PROMPT_MAX = 2000
CANDIDATES_MAX = 4
CANDIDATES_DEFAULT = 4
STRENGTH_MIN, STRENGTH_MAX, STRENGTH_DEFAULT = 0.10, 0.90, 0.45
SEED_MAX = 2147483647
MIN_FREE_GIB = 2.0
RUNS_MAX = 200
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image-Edit"}
RUN_ID_RE = re.compile(r"^se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STILL_RE = re.compile(r"^char_[0-9]{2}\.png$")          # movie_ui_server.STILL_FILE_RE
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
SOURCE_NAMES = ("source.png", "source.jpg", "source.webp")
```
`bin/seed-edit`:
```python
LONG_EDGE = 1024
MULTIPLE = 16
MIN_SIDE = 64
PROMPT_MAX = 2000
SEED_MAX = 2147483647
STRENGTH_DEFAULT = 0.45
MIN_FREE_GIB = 2.0               # character_dataset.CREATE_MIN_FREE_GIB
ZIMAGE_MIN_AVAIL_GIB = 20.0      # character_dataset.GENERATE_MIN_AVAIL_GIB
BF16_MIN_AVAIL_GIB = 64.0        # character_dataset.EDIT_MIN_AVAIL_GIB
MFLUX_MIN_AVAIL_GIB = 32.0
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
CHILD_TIMEOUT_S = 3600
EDIT_MODEL = "Qwen/Qwen-Image-Edit-2511"                                  # character_dataset.EDIT_MODEL
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"                # character_dataset.EDIT_LORA_REPO
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
EDIT_STEPS = 8
EDIT_TRUE_CFG = 1.0
Q4_REPO = "mflux-community/qwen-image-edit-2511-mflux-q4"
Q4_NAME_PART = "qwen-image-edit-2511"
MFLUX_MIN_VERSION = (0, 22, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
SAFETY_SKILL = "seed_edit"
BACKEND_LABELS = {"zimage": "Z-Image", "diffusers-bf16": "diffusers bf16", "mflux-q4": "mflux q4"}
```
`app.js`: `const SEED_LONG_EDGE = 1024;`, `const SEED_MIN_SIDE = 64;`, `const SEED_PROMPT_MAX = 2000;`, `const SEED_POLL_MS = 2000;`, `const SEED_ACTIVE = ["queued", "starting", "running"];`, `const SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image-Edit"};`, `const SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};`.

---

## 2. `bin/seed-edit`

### 2.1 Command line (SG4-SG7)

```
bin/seed-edit --source PATH --prompt TEXT --model zimage|qwen [--strength S] [--candidates N]
              [--seed N] --run-dir DIR
bin/seed-edit --probe
```
- **SG4.** argparse with every option `type=str` (`--probe` is `store_true`), so the tool writes its own messages. Validation runs in this order, each failure printing `Error: <text>` on stderr and exiting 2 **before anything is created or written**:
  | Rule | Text |
  |---|---|
  | `--probe` with any other option | `--probe takes no other options` |
  | any of `--source`, `--prompt`, `--model`, `--run-dir` missing | `--source, --prompt, --model and --run-dir are required` |
  | model not `zimage`/`qwen` | `--model must be zimage or qwen` |
  | prompt empty after `strip()` | `--prompt must not be empty` |
  | `len(prompt) > 2000` | `--prompt is longer than 2000 characters` |
  | candidates not `^[0-9]+$` or outside 1-4 (absent → 4) | `--candidates must be an integer from 1 to 4` |
  | strength given with `qwen` | `--strength is only for --model zimage` |
  | zimage strength not a float in 0.10-0.90 (absent → 0.45) | `--strength must be a number from 0.10 to 0.90` |
  | seed not `^[0-9]+$` or above 2147483647 (absent → `secrets.randbelow(2147483648)`) | `--seed must be an integer from 0 to 2147483647` |
- **SG5.** Exit codes: **0** every candidate ended `ok` or `blocked`; **1** the backend failed (a crash, a child exiting non-zero or timing out) — finished candidates are kept, the rest are `failed`; **2** refused before any model loaded (SG4, SG9, SG13); **130** interrupted (SIGINT, SIGTERM or SIGHUP). The movie-ui runner maps 0 to `done` and anything else to `failed` (or `cancelled` when its cancel marker exists).
- **SG6.** `__main__` installs a handler that raises `KeyboardInterrupt` for SIGINT, SIGTERM and SIGHUP (as `bin/character` does), then `sys.exit(main())`. `main(argv=None)` returns the exit code and never installs handlers (tests call it in-process).
- **SG7.** Output: every stdout line goes through the module function `say(text)` (`print(text, flush=True)`); `Error: …` lines go to stderr. Fixed lines, in order of appearance: `seed-edit: run <run dir>`; `seed-edit: source <W0>x<H0> -> <W>x<H>`; `seed-edit: backend <backend> (<why>)`; optionally the SG13 waiting line; the candidate lines (SG16); `seed-edit: done: <a> ok, <b> blocked, <c> failed`.

### 2.2 Size math and the source (SG8-SG10)

- **SG8.** The source opens with PIL; `ImageOps.exif_transpose` is applied; the result is converted to RGB. `(W0, H0)` is that image's size. With `L = max(W0, H0)`: if `L <= 1024`, `w, h = W0, H0`; else `w, h = W0 * 1024 // L, H0 * 1024 // L` (integer floor). Then `W, H = w // 16 * 16, h // 16 * 16`. Never upscales. Examples (SGT1): 1536×1024 → 1024×672; 1024×1024 → 1024×1024; 800×600 → 800×592; 4000×3000 → 1024×768; 3000×4000 → 768×1024; 720×1280 → 576×1024; 1023×1023 → 1008×1008; 100×70 → 96×64; 100×60 → refused (96×48).
- **SG9.** Refusals (exit 2; written to `run.json` as SG12 says): unreadable source → `cannot read --source <path>: <ExcType>: <message>`; PIL format not PNG, JPEG or WEBP → `--source must be a PNG, JPEG or WebP image (got <format>): <path>`; `W < 64` or `H < 64` → `--source is too small: <W0>x<H0> gives a <W>x<H> canvas; each side must be at least 64 px`.
- **SG10.** `<run>/source.<ext>` is an exact byte copy of `--source` (`ext` = `png`, `jpg`, `webp` from the PIL format); when that file exists and `os.path.samefile(--source, it)` is true, nothing is copied. `<run>/work/source.png` is the transposed RGB image, saved once; every backend reads it (Z-Image resizes it in memory to `W×H` with `Image.LANCZOS`; the Qwen children get its path and `width=W, height=H`). **[spec choice]** The browser shows EXIF-rotated images, so the tool edits what the user saw while `source.<ext>` stays an exact copy (notes).

### 2.3 The run directory and `run.json` (SG11-SG12)

- **SG11.** `run.json` (schema `seed-edit.run.v1`), written only with `lib.write_json_atomic`:
  ```json
  {"schema": "seed-edit.run.v1", "run": "se-20261102-141500-a1b2", "created": "2026-11-02T14:15:00Z",
   "state": "queued|running|done|failed|cancelled", "prompt": "…", "model": "zimage|qwen",
   "backend": null, "strength": 0.45, "seed": 7,
   "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
   "source": "source.png",
   "source_origin": {"kind": "upload", "upload_id": "<id>"} | {"kind": "run", "run": "<run>", "n": 2}
                    | {"kind": "character", "character": "kyra", "still": "char_05.png"} | null,
   "job": "<job id>" | null, "error": null,
   "candidates": [{"n": 1, "seed": 8, "status": "pending|ok|blocked|failed", "seconds": null}]}
  ```
  `run` is the run directory's basename. `strength` is null for `qwen`. `backend` is null until chosen, then `zimage`, `diffusers-bf16` or `mflux-q4`. Candidate `i` (1-based) has `seed = base + i`. `seconds` is the generation time rounded to 0.1 for `ok`/`blocked`, else null. `size`/`source_size` are null until SG8 succeeds. `error` holds the SG9/SG13/SG17 text without `Error: `.
- **SG12.** Write order. The tool keeps `created`, `source_origin` and `job` from an existing readable `run.json` object in `--run-dir` (else `created = lib.utc_now()`, `source_origin = null`, `job = null`) and owns every other key:
  1. After SG4 passes: `os.makedirs(run_dir, exist_ok=True)`, `os.makedirs(<run>/work, exist_ok=True)`, print `seed-edit: run <dir>`.
  2. SG8-SG10. On a refusal: write `run.json` with `state: failed`, `error`, every candidate `failed`; exit 2.
  3. Write `run.json` with `state: running`, `backend: null`, every candidate `pending`.
  4. Preflight and backend choice (§2.4). On a refusal: write `state: failed`, `error`, every candidate `failed`; exit 2.
  5. Write `run.json` with `backend`; print `seed-edit: backend …`.
  6. Per candidate, in this order: the final file `<run>/cand_NN.png` (two digits) appears by `os.replace` from a part file in `work/` (ok only); `run.json` is written with that candidate's status; the candidate line is printed. The page therefore never sees a status ahead of its file.
  7. End: `state: done` (no `failed` candidate) or `failed` (with `error`), then `seed-edit: done: …`. Leftover `work/*.part.png` and `work/*.pending.png` are deleted in a `finally`.
  8. On `KeyboardInterrupt` anywhere after step 1: kill the child's process group with SIGKILL if a child runs, mark every `pending` candidate `failed`, write `state: cancelled`, `error: "interrupted"`, print `seed-edit: interrupted` on stderr, return 130.

### 2.4 Preflight and backend choice (SG13-SG15)

- **SG13.** Before any model loads, in this order (each failure is an exit-2 refusal, SG12 step 4):
  1. **Disk:** `disk_free_gib(run_dir) < 2.0` → `less than 2 GiB free on the disk holding <run dir> (<x.x> GiB free)`, where the module function `disk_free_gib(path)` is `shutil.disk_usage(path).free / 2**30`.
  2. **Busy:** `character_dataset.busy_process()` (imported here) returns `(pid, cmd)` → `another GPU process is running (pid <pid>: <cmd>); try again when it ends`.
  3. **Backend:** SG14.
  4. **Memory floor** for `zimage` (20 GiB) and `mflux-q4` (32 GiB): if `avail_gib() < floor`, print `seed-edit: waiting up to <AVAIL_WAIT_S> s for <floor:g> GiB available (now <x.x> GiB)`; then `deadline = time.monotonic() + AVAIL_WAIT_S`; `while avail_gib() < floor:` refuse when `time.monotonic() >= deadline`, else `time.sleep(5)`. The refusal is `only <x.x> GiB available after waiting <AVAIL_WAIT_S> s; <Z-Image|mflux q4> needs <floor:g> GiB; free memory and retry` (`%d` of the module constant, so 600 in use). `diffusers-bf16` was chosen at ≥ 64 GiB and is not re-gated.
  `avail_gib()` is `psutil.virtual_memory().available / 2**30`; `total_gib()` is `os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30`, or `None` when that raises `ValueError`/`OSError`. Both are module functions so tests replace them. **[spec choice]** No `mps_guard.preflight`: it refuses whenever 8178 listens and needs the guard stand-down file, and no image tool uses it; the psutil floors follow `character_dataset`'s convention.
- **SG14.** Checks (module functions, each returning `None` or the first problem text):
  - `missing_modules(names)`: the names whose `importlib.util.find_spec(name)` is `None` or raises `ImportError`/`ValueError`; never imports them. Problem text `<names joined ", "> not importable by <sys.executable>`.
  - `default_hub()`: `$HF_HUB_CACHE`, else `<$HF_HOME or ~/.cache/huggingface>/hub` (huggingface_hub's own resolution, which the unchanged Qwen child uses). `zimage_hub()` is `lib.zimage_hub()`.
  - **Z-Image** `zimage_problem()`: `missing_modules(["PIL", "psutil", "torch", "diffusers", "transformers"])`; then `lib.model_check(lib.STILLS_BASE_MODEL, lib.zimage_hub_for(lib.STILLS_BASE_MODEL))` and the same for `lib.ZIMAGE_TEXT_ENCODER` — a failing check's detail is the problem.
  - **bf16 weights** `bf16_problem()`: `missing_modules(["PIL", "psutil", "torch", "diffusers", "transformers", "huggingface_hub"])`; `lib.model_check(EDIT_MODEL, default_hub())` detail; the Lightning file in `default_hub()` (below) else `Lightning LoRA <EDIT_LORA_FILE> is not in <default hub>`.
  - **Lightning lookup** `find_lightning(hubs)`: for each hub in order, `repo = <hub>/models--lightx2v--Qwen-Image-Edit-2511-Lightning`; `snapshot = lib.choose_snapshot(repo)[0]`; the file `<snapshot>/<EDIT_LORA_FILE>` counts when its realpath is a regular file larger than 0 bytes. Returns the snapshot path of the file (not its realpath) or `None`.
  - **mflux** `mflux_problem()` → the tuple `(problem, q4_dir, lora_file)` (`problem` is `None` when ready; the paths are `None` when not):
    1. `py = $SEED_EDIT_MFLUX_PYTHON or expanduser(DEFAULT_MFLUX_PYTHON)`; not `os.access(py, X_OK)` → `no mflux venv at <py> (run bin/seed-edit-setup)`.
    2. `venv = dirname(dirname(py))` (no realpath: a venv python is a symlink). `glob <venv>/lib/python*/site-packages/mflux-*.dist-info/METADATA`; none → `mflux is not installed in <venv> (run bin/seed-edit-setup)`. From each, the first line starting `Version: `; parse `^(\d+)\.(\d+)\.(\d+)` into an int tuple; take the highest; none parse → `cannot read the mflux version in <venv>`. Below `(0, 22, 0)` → `mflux <version text> in <venv> is older than 0.22.0 (run bin/seed-edit-setup)`. Torch is never imported for this.
    3. q4: with `$SEED_EDIT_QWEN_Q4_DIR` set: it must be absolute, its basename must contain `qwen-image-edit-2511` case-insensitively (else `SEED_EDIT_QWEN_Q4_DIR <path>: the directory name must contain qwen-image-edit-2511`), and `lib.model_check(path, None)` must pass (else `SEED_EDIT_QWEN_Q4_DIR <path>: <detail>`); `q4_dir = path`. Unset: the first of `zimage_hub()`, `default_hub()` holding `<hub>/models--mflux-community--qwen-image-edit-2511-mflux-q4`; none → `mflux-community/qwen-image-edit-2511-mflux-q4 is not in <zimage hub> or <default hub> (run bin/seed-edit-setup)`; `lib.model_check(Q4_REPO, hub)` failing → `mflux-community/qwen-image-edit-2511-mflux-q4: <detail>`; `q4_dir = lib.choose_snapshot(<repo dir>)[0]`.
    4. Lightning: with `$SEED_EDIT_LIGHTNING_FILE` set it must be an absolute path whose realpath is a non-empty regular file (else `SEED_EDIT_LIGHTNING_FILE <path> is not a non-empty file`); unset, `find_lightning([zimage_hub(), default_hub()])`, none → `Lightning LoRA <EDIT_LORA_FILE> is not in <zimage hub> or <default hub> (run bin/seed-edit-setup)`.
    5. Screening deps in this (parent) python: `missing_modules(["PIL", "psutil", "torch", "transformers"])`.
  - **Run-time Qwen choice** `choose_qwen()` → `(backend, why)` or a refusal:
    1. `b = bf16_problem()`; if `b is None`: `a = avail_gib()`; `a >= 64.0` → `("diffusers-bf16", "<a:.1f> GiB available")`; else `b = "only <a:.1f> GiB available (needs 64)"`.
    2. `m = mflux_problem()[0]`; `m is None` → `("mflux-q4", "diffusers bf16: <b>")`.
    3. Else refuse: `Qwen-Image-Edit is unavailable: diffusers bf16: <b>; mflux q4: <m>`.
  - **Run-time Z-Image:** `zimage_problem()` not `None` → refuse `Z-Image is unavailable: <problem>`; `why` is `Z-Image img2img`.
- **SG15.** `--probe` prints one line, `json.dumps({"zimage": {...}, "qwen": {...}}, sort_keys=True)`, and exits 0 whatever it finds. Each value is `{"ok": bool, "reason": str|None, "backend": str|None}`.
  - `zimage`: `p = zimage_problem()` → `{"ok": p is None, "reason": p, "backend": "zimage" if p is None else None}`.
  - `qwen`: bf16 eligibility at probe time uses **total** memory: `t = total_gib()`; `b = "cannot read this host's memory size"` when `t is None`, else `"needs a host with at least 64 GiB of memory (this host has <t:.1f> GiB)"` when `t < 64.0`, else `bf16_problem()`. `m = mflux_problem()[0]`. `ok = b is None or m is None`; `backend = "diffusers-bf16"` when `b is None`, else `"mflux-q4"` when `m is None`, else `None`; `reason = None` when ok, else `diffusers bf16: <b>; mflux q4: <m>`.
  The probe imports nothing beyond SG2's top-level modules, loads no model, starts no process, and typically finishes in well under a second. **[spec choice]** At probe time the story server is usually up, so available memory says nothing about the job (which runs after the VLM stop); total memory is the honest eligibility test, and the run-time rule (SG14) stays exactly the notes' rule.

### 2.5 Candidate lines and backends (SG16-SG22)

- **SG16.** One line per finished candidate, exactly `candidate <i>/<N> ok <s.s>s`, `candidate <i>/<N> blocked <s.s>s` or `candidate <i>/<N> failed`. After a backend failure, every candidate not yet finished gets its own `failed` line (in order). A refusal before loading prints no candidate line.
- **SG17.** Backend failure texts (`error`, exit 1): Z-Image → `Z-Image failed on candidate <i>: <ExcType>: <message>`; a child exiting non-zero → `<diffusers bf16|mflux q4> child exited <rc>: <last non-empty line the child printed, or ->`; a child timeout → `<diffusers bf16|mflux q4> child timed out after <CHILD_TIMEOUT_S> s` (`%d` of the module constant, so 3600 in use); a child exiting 0 with a candidate unfinished → `<diffusers bf16|mflux q4> child exited 0 without finishing candidate <i>` (the first such i).
- **SG18. Z-Image** (`run_zimage`): `import z_image_skill, content_safety`; `src = Image.open(<run>/work/source.png).convert("RGB").resize((W, H), Image.LANCZOS)`; for `i` in 1..N: `seed = base + i`; time it; `image = z_image_skill.generate_variation(src, prompt, output_path=None, strength=strength, generator=cpu_generator(seed))`; save to `<run>/work/cand_NN.part.png`, `os.replace` to `<run>/cand_NN.png` → `ok`; `content_safety.ContentSafetyError` → `blocked` (nothing saved); any other `Exception` → this and every later candidate `failed`, SG17 text, stop. `cpu_generator(seed)` is a module function `import torch; return torch.Generator("cpu").manual_seed(seed)`. The pipeline singleton loads on the first call, so candidate 1's `seconds` includes the model load (recorded in the live check).
- **SG19. diffusers bf16** (`run_bf16`): writes `<run>/work/qwenedit_spec.json`:
  ```json
  {"image": "<run>/work/source.png", "model": "Qwen/Qwen-Image-Edit-2511",
   "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning", "lora_file": "<EDIT_LORA_FILE>",
   "steps": 8, "true_cfg": 1.0, "skill": "seed_edit",
   "jobs": [{"prompt": "<prompt>", "output_path": "<run>/work/cand_01.part.png", "seed": <base+1>,
             "width": W, "height": H}, …],
   "report_path": "<run>/work/qwenedit_report.json"}
  ```
  and runs `[sys.executable, $SEED_EDIT_QWENEDIT_SCRIPT or <WS>/character_dataset.py, "qwenedit", "--spec", <spec>]` through `run_child` (SG21) with `env = dict(os.environ, PYTHONUNBUFFERED="1")`. A child line matching `^cand_(\d{2})\.part\.png (ok|blocked) ([0-9]+\.[0-9])s$` finishes candidate NN: `ok` → `os.replace` the part file to `cand_NN.png`; `blocked` → nothing saved (the child screens with skill `seed_edit` and never saves a blocked image). After the child ends, unfinished candidates are `failed`; a non-zero exit gives SG17's text. `character_dataset.py` is not modified (**[spec choice]**, Section 14 item 1).
- **SG20. mflux q4** (`run_mflux`): imports `content_safety` first (a missing dependency is caught earlier by SG14 step 5), writes `<run>/work/mflux_spec.json`:
  ```json
  {"model_path": "<q4_dir>", "lora_path": "<lora_file>", "prompt": "<prompt>",
   "source": "<run>/work/source.png", "width": W, "height": H, "steps": 8, "guidance": 1.0,
   "jobs": [{"n": 1, "seed": <base+1>, "output_path": "<run>/work/cand_01.pending.png"}, …]}
  ```
  and runs `[<mflux python>, <WS>/seed_edit_mflux_child.py, "--spec", <spec>]` through `run_child` with `env = dict(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")`. A child line matching `^seed-edit-child done (\d+) ([0-9]+\.[0-9])$` finishes candidate n: the parent opens the pending file, `content_safety.assert_image_safe(img.convert("RGB"), skill="seed_edit", prompt=prompt)`; safe → `os.replace` to `cand_NN.png`, `ok`; `ContentSafetyError` → delete the pending file, `blocked`. `seconds` is the child's figure. After the child ends, unfinished candidates are `failed`; non-zero exit → SG17. **[spec choice]** The parent screens: the child stays mflux/mlx/PIL/stdlib, screening uses the workspace's tested torch/transformers, and no candidate reaches its final name unscreened.
- **SG21.** `run_child(argv, env, on_line)`: `subprocess.Popen(argv, cwd=WS, env=env, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, start_new_session=True)`, stored in module global `CHILD`; a daemon `threading.Timer(CHILD_TIMEOUT_S)` SIGKILLs the process group (`os.killpg(os.getpgid(pid), SIGKILL)`, ignoring `OSError`) and the timer is cancelled after `wait()`; each line is written to stdout as is, then `on_line(line.rstrip("\n"))`; returns the exit code, or `-9` after a timeout (SG17's timeout text). `CHILD` is reset to `None` after `wait()`.
- **SG22.** Each backend loads its model once per job: Z-Image through the `z_image_skill` singleton, each child once per run (SGT9, SGT11 count child starts).

### 2.6 Environment overrides (SG23)

- **SG23.** The only environment variables `bin/seed-edit` reads: `SEED_EDIT_MFLUX_PYTHON`, `SEED_EDIT_QWEN_Q4_DIR`, `SEED_EDIT_LIGHTNING_FILE`, `SEED_EDIT_QWENEDIT_SCRIPT` (all §2.4-2.5), plus `HF_HUB_CACHE`, `HF_HOME` (default hub), `Z_IMAGE_HF_HOME` (via `lib.zimage_hub`), `HOME` (expansion). The tool's docstring lists them, the usage, the exit codes and the run.json write order.

---

## 3. `seed_edit_mflux_child.py` (SG24-SG27)

- **SG24.** Runs under the venv python; top-level imports only `argparse`, `importlib.metadata`, `json`, `os`, `re`, `sys`, `threading`, `time`. `mlx.core` and mflux are imported inside `main` after the version gate; PIL is used only through `GeneratedImage.image`. It never imports `content_safety` and never screens.
- **SG25.** Body (the API calls are load-bearing; the implementer types them as written):
  ```python
  MIN_VERSION = (0, 22, 0)


  def parse_version(text):
      m = re.match(r"(\d+)\.(\d+)\.(\d+)", text or "")
      return tuple(int(g) for g in m.groups()) if m else None


  def exit_with_parent(poll_s=2.0):
      parent = os.getppid()

      def _watch():
          while True:
              time.sleep(poll_s)
              if os.getppid() != parent:
                  os._exit(3)

      threading.Thread(target=_watch, daemon=True).start()


  def main(argv=None):
      parser = argparse.ArgumentParser(prog="seed_edit_mflux_child.py")
      parser.add_argument("--spec", required=True)
      args = parser.parse_args(argv)
      exit_with_parent()
      try:
          version = importlib.metadata.version("mflux")
      except importlib.metadata.PackageNotFoundError:
          version = None
      parsed = parse_version(version)
      if parsed is None or parsed < MIN_VERSION:
          print("seed-edit-child: mflux %s is missing or older than 0.22.0; refusing (it would run "
                "Qwen-Image-Edit-2509)" % version, flush=True)
          return 2
      with open(args.spec, encoding="utf-8") as f:
          spec = json.load(f)
      import mlx.core as mx
      from mflux.models.common.config.model_config import ModelConfig
      from mflux.models.qwen.variants.edit.qwen_image_edit import QwenImageEdit
      config = ModelConfig.qwen_image_edit_2511()
      print("seed-edit-child: mflux %s, model %s, transformer overrides %s"
            % (version, config.model_name, config.transformer_overrides), flush=True)
      model = QwenImageEdit(model_path=spec["model_path"], quantize=None, model_config=config,
                            lora_paths=[spec["lora_path"]], lora_scales=[1.0], bake_lora=False)
      peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
      for job in spec["jobs"]:
          started = time.monotonic()
          result = model.generate_image(seed=job["seed"], prompt=spec["prompt"],
                                        image_paths=[spec["source"]],
                                        num_inference_steps=spec["steps"], guidance=spec["guidance"],
                                        negative_prompt=" ", width=spec["width"], height=spec["height"])
          result.image.save(job["output_path"])
          seconds = time.monotonic() - started
          print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
          print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```
- **SG26.** `guidance` is always 1.0 and `bake_lora` always False (notes: the CLI default 2.5 and baking into quantized weights are both wrong). The LoRA is a local file path, never a repo ID. `model_path` is a local directory, so mflux never resolves or downloads (`HF_HUB_OFFLINE=1` from SG20 is a second guard).
- **SG27.** Exit codes: 0 all jobs saved; 2 version refusal (before the spec is read); 3 the parent died; anything else is a crash (the traceback goes to the job log through SG21).

---

## 4. movie-ui library (`movie_ui_lib.py`) (SG28-SG32)

- **SG28.** `job_vlm`: the forbidden tuple at `:434` becomes `("smoke", "character-train", "action-train", "location-train", "seed-edit")`. The runner therefore stops the story server before the tool starts and the postflight restores it as for every other forbidden kind ([VL]).
- **SG29.** New, directly below `character_argv`:
  ```python
  def seed_edit_argv(fields, ws_real, py=sys.executable):
      """The bin/seed-edit argv of a seed-edit job (seed generator spec SG29)."""
      run_dir = os.path.join(ws_real, "generated", "seeds", "runs", fields["run"])
      argv = [py, os.path.join(ws_real, "bin", "seed-edit"),
              "--source", os.path.join(run_dir, fields["source_file"]),
              "--prompt", fields["prompt"], "--model", fields["model"]]
      if fields["model"] == "zimage":
          argv += ["--strength", repr(float(fields["strength"]))]
      return argv + ["--candidates", str(fields["candidates"]), "--seed", str(fields["seed"]),
                     "--run-dir", run_dir]
  ```
- **SG30.** New, directly below `story_server_record`:
  ```python
  def seed_edit_check(ws_real):
      """(models, None) from <ws>/bin/seed-edit --probe, or (None, detail) (seed generator SG30)."""
  ```
  It runs `run_light(tool_argv(ws_real, "seed-edit", "--probe"), ws_real)`. Timeout → `(None, "bin/seed-edit --probe timed out after %d s" % LIGHT_TIMEOUT)`; exit code not 0 → `(None, "bin/seed-edit --probe exited %s: %s" % (code or "none", last_line(stderr) or "-"))` (`code` is the int, or the text `none` when it is `None`); `json.loads(last_line(stdout))` failing, or the result not a dict whose `zimage` and `qwen` values are each a dict with a bool `ok`, a `str`-or-`None` `reason` and a `str`-or-`None` `backend` → `(None, "bin/seed-edit --probe printed unparsable output")`; else `({"zimage": …, "qwen": …}, None)` holding exactly those three keys per model.
- **SG31.** Progress hook. `SEED_CAND_RE = re.compile(r"^candidate (\d+)/(\d+) (ok|blocked|failed)(?: [0-9]+\.[0-9]s)?$")` next to the other patterns. `ProgressParser.__init__` adds `self.candidates = {}` and `self.candidates_total = None`. In `_line`, directly after the `last_line` update: `if self.kind == "seed-edit":` match `SEED_CAND_RE`; on a match set `candidates_total = int(group 2)` and `candidates[group 1] = group 3`; then `return` (no other pattern applies to this kind). Other kinds are unchanged.
- **SG32.** `snapshot`, before the generic branch: for kind `seed-edit` return
  `{"kind": "seed-edit", "elapsed_s": elapsed, "last_line": self.current_last_line(), "face_problem": False, "candidates": {"total": T, "done": D, "ok": …, "blocked": …, "failed": …, "current": D + 1 if T is not None and D < T else None}}`, where `T = self.candidates_total` or, when that is `None`, `self.fields.get("candidates")` if it is an int, else `None`; `D = len(self.candidates)`.

---

## 5. Server

### 5.1 `movie_ui_seedgen.py` (SG33-SG37)

- **SG33.** `validate_run_request(body)` → `(clean, None)` or `(None, error)`; first failure only, in this order:
  | # | Rule | `error` |
  |---|---|---|
  | 1 | `prompt` not a str, or empty after `strip()` | `prompt is required` |
  | 2 | `len(prompt) > 2000` | `prompt is longer than 2000 characters` |
  | 3 | `not lib._argv_safe(prompt)` | `prompt contains invalid characters` |
  | 4 | `prompt.strip().startswith("-")` | `prompt must not start with '-'` |
  | 5 | `model` not `"zimage"`/`"qwen"` | `model must be zimage or qwen` |
  | 6 | model `qwen` and `strength` present and not null | `strength is only for zimage` |
  | 7 | model `zimage`, `strength` not null/absent and not (`lib._is_number` and 0.10 ≤ s ≤ 0.90) | `strength must be a number from 0.10 to 0.90` |
  | 8 | `candidates` not null/absent and not (`lib._is_int` and 1 ≤ n ≤ 4) | `candidates must be an integer from 1 to 4` |
  | 9 | `seed` not null/absent and not (`lib._is_int` and 0 ≤ n ≤ 2147483647) | `seed must be an integer from 0 to 2147483647` |
  | 10 | `source` not a dict whose key set is exactly `{"upload_id"}` (str), `{"run", "n"}` (str, `lib._is_int`) or `{"character", "still"}` (str, str) | `source must be {upload_id}, {run, n} or {character, still}` |
  | 11 | upload: `not lib.UPLOAD_ID_RE.fullmatch(id)` | `source upload <id> not found` |
  | 12 | run: `not RUN_ID_RE.fullmatch(run)` | `unknown source run <run>` |
  | 13 | run: `not 1 <= n <= 4` | `source run <run> has no ok candidate <n>` |
  | 14 | character: not `lib.CHARACTER_NAME_RE.fullmatch(c)` or not `STILL_RE.fullmatch(s)` | `unknown character still <c>/<s>` |

  `clean` = `{"prompt": prompt (as sent), "model", "strength": float or None (zimage null/absent → 0.45; qwen → None), "candidates": int (null/absent → 4), "seed": int or None, "source": {"kind": "upload", "upload_id"} | {"kind": "run", "run", "n"} | {"kind": "character", "character", "still"}}`. Text inserted into a message is the value as sent (`%s`). Extra body keys are ignored.
- **SG34.** `valid_folder(name)`: a str, `FOLDER_RE.fullmatch`, no `..`, and `name.lower() != "runs"`. Message `FOLDER_MSG = "folder must be 1 to 64 letters, digits, '.', '_' or '-', start with a letter or digit, contain no '..' and not be 'runs'"`. **[spec choice]** The story-ID charset at 64 characters (notes); `runs` is refused case-insensitively because macOS volumes are case-insensitive.
- **SG35.** `new_run_id()` = `"se-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)`. `keep_name(run, n, k)` = `"%s-%02d.png" % (run, n)` for `k == 1`, else `"%s-%02d-%d.png" % (run, n, k)`.
- **SG36.** `capability(models, detail, checked)` → the `seed_edit` capability: models `None` → `{"ok": False, "reason": detail, "checked": checked, "models": None}`; else `ok = any(m["ok"] for m in models.values())`, `reason = None` if ok else `"; ".join("%s: %s" % (MODELS[k], models[k]["reason"]) for k in ("zimage", "qwen"))`, `models` as given.
- **SG37.** `availability_error(models, detail, model)`: models `None` → `"cannot check the seed models: %s" % detail`; `models[model]["ok"]` false → `"%s is unavailable: %s" % (MODELS[model], models[model]["reason"])`; else `None`.

### 5.2 Capability `seed_edit` (SG38-SG39)

- **SG38.** `MovieUIServer.__init__` adds `self.capabilities["seed_edit"] = {"ok": None, "reason": "probing", "checked": None, "models": None}` after the existing three. `refresh_capabilities` calls `models, detail = lib.seed_edit_check(self.probe_ws)` after the existing three probes and, inside the same `cap_lock` block, sets `self.capabilities["seed_edit"] = seedgen.capability(models, detail, checked)`. `capability_snapshot` is unchanged (it copies every key).
- **SG39.** Cost and cadence: one light subprocess with no model load, at startup (probe thread) and on every `GET /api/host?refresh=1` (the page's Re-check button), like the other probes; plus one synchronous probe in the request's workspace on every `POST /api/seeds/runs` (SG44 step 3). There is no periodic re-probe.

### 5.3 Routes (SG40-SG42)

- **SG40.** Directly after `("POST", r"/api/uploads", …)` in `ROUTES`, in this order, with `_RUN = r"(se-[0-9]{8}-[0-9]{6}-[0-9a-f]{4})"` and `_SAMPLE_RUN = "se-20261102-141500-a1b2"` next to `_ID`:
  ```python
  ("POST", r"/api/seeds/runs", "h_seed_run_create", "/api/seeds/runs"),
  ("GET", r"/api/seeds/runs", "h_seed_runs", "/api/seeds/runs"),
  ("GET", r"/api/seeds/runs/" + _RUN, "h_seed_run", "/api/seeds/runs/" + _SAMPLE_RUN),
  ("POST", r"/api/seeds/runs/" + _RUN + r"/keep", "h_seed_keep", "/api/seeds/runs/" + _SAMPLE_RUN + "/keep"),
  ("POST", r"/api/seeds/runs/" + _RUN + r"/use", "h_seed_use", "/api/seeds/runs/" + _SAMPLE_RUN + "/use"),
  ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
  ```
  `len(ROUTES)` becomes 63. All six are token-gated by the existing check order. The handlers are attached in a new block `MovieUIHandler.h_seed_* = _h_seed_*` after the uploads/characters block.
- **SG41.** New server names: `SEEDS_LOCK = threading.Lock()` next to `BATCH_LOCK` (guards Keep's name choice and write; never held together with `STORE_LOCK`); `seeds_root(ws_real)` = `<ws>/generated/seeds`; `runs_root(ws_real)` = `<seeds_root>/runs`; `seed_free_gib(path)` = `shutil.disk_usage(path).free / 2**30` (module function, tests replace it).
- **SG42.** Run lookup `_seed_run(ws_real, run)` → `(run_dir, record)`: `run_dir = <runs_root>/<run>`; it must satisfy `_inside(run_dir, runs_root)` and `os.path.isdir`, and `record = _json_in(run_dir, <run_dir>/run.json)` must be a dict, else `ApiError(404, "unknown seed run %s" % run)`. `_candidates(record)` = the entries of `record["candidates"]` (when a list) that are dicts with `lib._is_int(n)` and 1 ≤ n ≤ 4, in order. `_cand_file(run_dir, entry)` = `<run_dir>/cand_%02d.png` when `entry["status"] == "ok"` and `_isfile_in(run_dir, path)`, else `None`.

### 5.4 The run view, the runs list and the folders list (SG43, SG47-SG49)

- **SG43.** `run_state(server, record, queue)`: `record["state"]` when it is `done`, `failed` or `cancelled`; else, when `record["job"]` is a str matching `lib.JOB_ID_RE` and its job directory exists, `lib.job_state(server.state, job, queue)`; else `"unknown"`. **[spec choice]** A job cancelled while queued never runs the tool, so its run.json says `queued`; the job's state is the truth then.
  `run_view(server, ws_real, run, run_dir, record, queue)` returns exactly these keys: `run`, `dir` (the run dir), `created`, `state` (`run_state`), `prompt`, `model`, `backend`, `strength`, `seed`, `size`, `source_size`, `source_origin`, `error` (each copied from the record, missing → `None`), `source` (`<run_dir>/<record["source"]>` when that name is in `SOURCE_NAMES` and `_isfile_in`, else `None`), `candidates` (`[{"n", "seed", "status", "seconds", "path": _cand_file(…)}]` from `_candidates`) and `job` (`job_summary(server, job, queue)` when the job exists, else `None`).
- **SG47. `GET /api/seeds/runs?ws=`** → 200 `{"runs": [...]}`: names in `runs_root` matching `RUN_ID_RE`, sorted descending, at most `RUNS_MAX` (200) of those whose `_seed_run` lookup succeeds (others skipped silently; `queue.json` read once). Item keys: `run`, `created`, `state`, `prompt`, `model`, `backend`, `count` (number of candidates), `ok` (number `ok`), `thumbs` (the non-null candidate paths, in order). No `runs_root` → `{"runs": []}`.
- **SG48. `GET /api/seeds/runs/<run>?ws=`** → 200 `run_view(…)`; 404 per SG42.
- **SG49. `GET /api/seeds/folders?ws=`** → 200 `{"root": <seeds_root>, "folders": [...]}`. Each entry of `os.listdir(seeds_root)` that passes `valid_folder`, is a directory, and satisfies `_inside(path, seeds_root)`, sorted by `name.lower()`: `{"folder": name, "count": number of regular files directly inside whose lower-cased extension is in IMAGE_EXTS, "path": <seeds_root>/<name>}`. No `seeds_root` → `"folders": []`.

### 5.5 `POST /api/seeds/runs` (SG44-SG46)

- **SG44.** Steps:
  1. `real = self.ws(body.get("ws"))`; `clean, error = seedgen.validate_run_request(body)`; error → 400.
  2. Source existence (400, nothing created): upload → `<STATE>/uploads/<id>` is a regular file, else `source upload <id> not found`; run → `_seed_run(real, run)` succeeds (its 404 is caught and replaced by 400 `unknown source run <run>`) and `_cand_file` of entry n is not `None` (else `source run <run> has no ok candidate <n>`); character → `library = $CHARACTER_LIBRARY_DIR or <ws>/generated/characters`, `path = <library>/<c>/dataset/stills/<s>`, `_isfile_in(library, path)`, else `unknown character still <c>/<s>`. The source file, its extension (`upload_id`'s extension, else `png`) and `origin` (= `clean["source"]` without changes) are kept.
  3. `models, detail = lib.seed_edit_check(real)`; `seedgen.availability_error(models, detail, clean["model"])` not `None` → 409 with that `error`.
  4. `free = seed_free_gib(<ws>/generated if it is a directory else <ws>)`; `free < 2.0` → 409 `less than 2 GiB free on the disk holding <path> (<free:.1f> GiB free)`.
  5. `seed = clean["seed"]` or `secrets.randbelow(2147483648)`.
  6. `os.makedirs(runs_root, exist_ok=True)`; loop: `run = seedgen.new_run_id()`; `os.mkdir(<runs_root>/<run>)`; on `FileExistsError` draw again. `shutil.copyfile(source, <run_dir>/source.<ext>)`.
  7. Under `STORE_LOCK`: `job_id = lib.new_job_id(state)`; write `run.json` (SG11 shape: `state: queued`, `backend/size/source_size/error: null`, `source: "source.<ext>"`, `source_origin: origin`, `job: job_id`, candidates `pending` with `seed + i`); `fields = {"ws": real, "run": run, "source_file": "source.<ext>", "prompt", "model", "strength", "candidates", "seed": seed, "source": origin}`; `lib.create_job(state, job_id, "seed-edit", real, None, None, lib.seed_edit_argv(fields, real), fields)`.
  8. 201 `{"run": run_view(…)}` (queue read after the lock is released).
- **SG45.** The 400 table is SG33's rows plus `resolve_ws`'s messages and step 2's three messages; the 409 table is SG37's two messages and step 4's message. Every 400 and 409 leaves no run directory and no job.
- **SG46.** `job_summary` gains a 16th key, `"seed_run": (job.get("fields") or {}).get("run") if job["kind"] == "seed-edit" else None`.

### 5.6 Keep and Use (SG50-SG53)

- **SG50. `POST /api/seeds/runs/<run>/keep` `{ws, n, folder}`**: `real = self.ws(...)`; `_seed_run` (404); `entries = _candidates(record)`; `n` must be `lib._is_int` and 1 ≤ n ≤ `len(entries)`, else 400 `n must be a candidate number from 1 to <len>`; `folder` must pass `valid_folder`, else 400 `FOLDER_MSG`; the entry with that n (absent → status `missing`) must have status `ok`, else 409 `candidate <n> of <run> is <status>; only an ok candidate can be kept`; `_cand_file` `None` → 409 `candidate <n> of <run> has no image file`. Then under `SEEDS_LOCK`: `os.makedirs(<seeds_root>/<folder>, exist_ok=True)`; when `_inside(<folder dir>, seeds_root)` is false (a symlink pointing elsewhere) → 409 `folder <folder> resolves outside <seeds_root>`; for `k = 1, 2, …`: `dest = <folder dir>/keep_name(run, n, k)`; `fd = os.open(dest, O_WRONLY | O_CREAT | O_EXCL, 0o666)` (on `FileExistsError` try the next k); write the candidate's bytes; close (unlink `dest` if writing raises). 201 `{"folder": folder, "file": basename(dest), "path": dest}`.
- **SG51.** Keep never overwrites: the first free of `<run>-<nn>.png`, `<run>-<nn>-2.png`, `<run>-<nn>-3.png`, … (notes: "-2 suffix").
- **SG52. `POST /api/seeds/runs/<run>/use` `{ws, n}`**: same lookup, `n` and status rules as SG50 (409 text ends `only an ok candidate can be used`); then `store_upload(server.state, data, "png")`, 201 with its result.
- **SG53.** `store_upload(state, data, ext)` is extracted from `_h_upload`: `upload_id = "%s.%s" % (hashlib.sha256(data).hexdigest(), ext)`; `path = <state>/uploads/<upload_id>`; `lib.write_bytes_atomic(path, data)` unless `os.path.isfile(path)`; returns `{"upload_id", "path", "bytes": len(data)}`. `_h_upload` keeps its type/magic checks and returns `201, store_upload(self.server.state, body, ext)`; its behaviour is unchanged. The Use upload ID therefore equals the ID `POST /api/uploads` gives the same bytes.

---

## 6. The page (SG54-SG65)

- **SG54. Tab.** `index.html` nav: `<button id="tab-seeds" type="button" class="tab">Seeds</button>` directly after `tab-compose`. `app.js`: `const TABS = ["compose", "seeds", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"];`. `showTab` adds `if (name !== "seeds") { stopSeedPoll(); }` after its `stopBatchPoll` line and `if (name === "seeds") { loadSeeds(); }`.
- **SG55. Panel** (directly after `panel-compose`'s `</section>`), exactly these IDs, each once:
  ```html
  <section id="panel-seeds" class="panel" hidden>
    <h3>Source</h3>
    <div class="row">
      <label>Upload <input id="se-file" type="file" accept="image/png,image/jpeg,image/webp"></label>
      <span id="se-source-status" class="muted"></span>
    </div>
    <div class="row">
      <img id="se-source-img" class="se-thumb" alt="source image" hidden>
      <span id="se-source-size" class="muted"></span>
    </div>
    <div class="grid">
      <label class="wide">Prompt <textarea id="se-prompt" rows="3" maxlength="2000"></textarea></label>
      <span id="se-prompt-count" class="muted">0 / 2000 characters</span>
      <label>Model <select id="se-model">
          <option value="zimage">Z-Image (img2img)</option>
          <option value="qwen">Qwen-Image-Edit</option>
        </select></label>
      <span id="se-model-note" class="muted"></span>
      <label id="se-strength-box">Strength <input id="se-strength" type="number" min="0.10" max="0.90" step="0.05" value="0.45">
        <span class="muted">lower keeps more of the source</span></label>
      <label>Candidates <select id="se-candidates"><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4" selected>4</option></select></label>
      <label>Seed <input id="se-seed" type="number" min="0" max="2147483647" step="1" placeholder="blank = random"></label>
    </div>
    <div class="row"><button id="se-generate" type="button">Generate</button> <span id="se-generate-reason" class="muted"></span></div>
    <h3 id="se-run-title"></h3>
    <p id="se-run-status" class="muted"></p>
    <datalist id="se-folder-options"></datalist>
    <div id="se-grid" class="se-grid"></div>
    <h3>Runs</h3>
    <table id="se-runs" class="list"><thead><tr><th>Run</th><th>Prompt</th><th>Model</th><th>State</th><th>Candidates</th></tr></thead><tbody></tbody></table>
    <h3>Seed folders</h3>
    <p class="muted">Kept seeds land in these folders; pick one in Compose → Seed folder.</p>
    <table id="se-folders" class="list"><thead><tr><th>Folder</th><th>Images</th><th>Path</th><th></th></tr></thead><tbody></tbody></table>
  </section>
  ```
- **SG56. State.** Directly after `part`: `S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};`. `source` is `{kind: "upload", upload_id, path}`, `{kind: "run", run, n, path}` or `{kind: "character", character, still, path}`. `natural` is `{width, height}` of the loaded thumbnail or `null`. Every DOM node is built with `el()`/`button()`; server text goes in through `textContent`/`text`; events use `addEventListener` only. No identifier or call spelled `prompt(` and no `on<x>=` assignment (the page bans `\bprompt\(` and `\son[a-z]+=`).
- **SG57. Functions** (each defined exactly once): `seedCanvas(w, h)` → `{width, height}` by SG8's integers (`L = Math.max(w, h)`; `L > SEED_LONG_EDGE` → `Math.floor(w * SEED_LONG_EDGE / L)`, likewise h; then `Math.floor(x / 16) * 16`); `setSeedSource(source, statusText)`; `onSeedSourceFile()`; `updateSeedButtons()`; `seedBody()`; `generateSeeds()`; `openSeedRun(run)`; `pollSeedRun()`; `renderSeedRun(view)`; `seedRow(view, cand)`; `keepSeed(run, n, input, status)`; `useSeed(run, n, status)`; `editSeedAgain(cand)`; `loadSeeds()`; `loadSeedRuns()`; `loadSeedFolders()`; `copySeedPath(input, status)`; `seedFromStill(name, path)`; `stopSeedPoll()`; `resetSeeds()`; `setupSeeds()`.
- **SG58. Source.**
  - `onSeedSourceFile`: status `uploading…`; `id = await uploadFile(file)`; `setSeedSource({kind: "upload", upload_id: id, path: S.host.state_dir + "/uploads/" + id}, "uploaded " + id.slice(0, 12))`; an error sets the status to `err.message`.
  - `setSeedSource` stores the source, sets `natural = null`, sets `#se-source-status`, sets `#se-source-img`'s `src` to `fileUrl(path)` and shows it; on the image's `load` event it sets `natural` from `naturalWidth`/`naturalHeight` and `#se-source-size` to `"<W0> × <H0> → <W> × <H>"` (from `seedCanvas`); `updateSeedButtons()` runs after both.
  - Status texts: run source `candidate <n> of <run>`; character source `still <still> of <character>`.
- **SG59. Model and Generate gating** (`updateSeedButtons`, also called from `renderBadges` after `updateLocationButtons()` and on every `input`/`change` in `#panel-seeds`):
  - `cap = capability("seed_edit")`; `models = cap.models`. Each `#se-model` option is disabled when `models && models[value].ok === false`; when the selected option becomes disabled and the other is not, select the other.
  - `#se-model-note`: `checking models…` while `cap.ok === null`; `cannot check the seed models: <cap.reason>` when `models` is null and `cap.ok === false`; else the parts joined by `"; "`: `Z-Image: unavailable — <reason>` when zimage is not ok; then `Qwen-Image-Edit backend: <SEED_BACKEND_LABELS[backend]>` when qwen is ok, else `Qwen-Image-Edit: unavailable — <reason>`.
  - `#se-strength-box` shown only for `zimage`. `#se-prompt-count` = `<length> / 2000 characters`.
  - Generate is disabled with the first reason that applies, in `#se-generate-reason` (empty when enabled): `queueing…` (`S.seeds.busy`); `choose a source image`; `loading the source image…` (`natural` null); `the source is too small: each side must be at least 64 px after scaling`; `enter a prompt` (trimmed empty); `<SEED_MODEL_LABELS[model]> unavailable: <(models && models[model] && models[model].reason) or cap.reason or "probing">` when `!(models && models[model] && models[model].ok === true)`; `strength must be from 0.10 to 0.90` (zimage, `Number(value)` outside or not finite); `seed must be an integer from 0 to 2147483647` (non-blank and not an integer in range).
- **SG60. Generate.** `seedBody()` = `{ws: S.ws, source: <{upload_id} | {run, n} | {character, still}>, prompt: <textarea value>, model, strength: zimage ? Number(strength) : null, candidates: Number(select), seed: blank ? null : Number(seed)}`. `generateSeeds()`: `busy = true`, update buttons; POST `/api/seeds/runs`; 201 → `openSeedRun(data.run.run)` and `pollJobs()`; otherwise `#se-generate-reason` = `data.error` or `http <status>`; `busy = false` in a `finally`.
- **SG61. Run grid.** `openSeedRun(run)` sets `S.seeds.run`, clears `#se-grid` and `rows`, GETs the view, renders it, and starts `S.timers.seeds = setInterval(pollSeedRun, SEED_POLL_MS)` while `SEED_ACTIVE` contains the state. `pollSeedRun` GETs and renders; when the state leaves `SEED_ACTIVE` it calls `stopSeedPoll()` and `loadSeedRuns()`. `renderSeedRun` stores the view in `S.seeds.view`; a response whose `run` differs from `S.seeds.run` is ignored.
  - `#se-run-title` = `<run> · <model label>` plus ` (<backend label>)` when `backend` is set. `#se-run-status`: `queued (position <job.queue_position>)`; `starting…`; `candidate <current> of <total>…` from `job.progress.candidates` while running (`running…` when that is absent); `done: <a> ok, <b> blocked, <c> failed`; `failed: <error or job.error or "see the job log">`; `cancelled`; `lost: the job's runner disappeared`; `unknown: the job record is gone`.
  - `seedRow(view, cand)` keeps one `div.se-row` per n in `S.seeds.rows[n] = {status, node}` and replaces only its candidate cell and actions when the status (or path) changed, so a folder name being typed survives polling. Row content: `div.se-label` text `Candidate <n> · seed <seed>`; `img.se-img` of `view.source`; the candidate cell: `img.se-img` of `cand.path` (ok), or `span.muted` with `generating…` (pending and `n === current`), `waiting…` (other pending), `blocked by content safety`, `failed`; for ok only, `div.se-actions` with `input.se-keep-folder` (`type="text"`, `list="se-folder-options"`, `placeholder="folder name"`, `size="20"`), buttons `Keep`, `Use in Compose`, `Edit again`, and `span.se-cand-status.muted`. Source and candidate images get the same CSS width (before/after at the same size).
- **SG62. Actions.**
  - `keepSeed`: POST `/api/seeds/runs/<run>/keep` `{ws, n, folder: input.value.trim()}`; 201 → status `kept as <path>` and `loadSeedFolders()`; else status `data.error`.
  - `useSeed`: POST `/use` `{ws, n}`; 201 → `S.seedUpload = upload_id; $("#c-res-seed").checked = true; $("#c-seed-status").textContent = "seed from " + run + " candidate " + n + " (" + upload_id.slice(0, 12) + ")";` then `showTab("compose"); updateComposeButtons(); preview();`; else status `data.error`.
  - `editSeedAgain(cand)`: with `run = S.seeds.view.run`, `setSeedSource({kind: "run", run: run, n: cand.n, path: cand.path}, "candidate " + cand.n + " of " + run)`; prompt, model, strength, candidates and seed stay as they are; scrolls nothing; does not generate.
- **SG63. Lists.** `loadSeedRuns`: one row per run (`tr.clickable`, click → `openSeedRun(run)`): run ID, the prompt cut to 80 characters plus `…` when longer, model label, state, and one `img.se-mini` per thumb. `loadSeedFolders`: rebuilds `#se-folder-options` (`<option value="<folder>">`) and one row per folder: name, count, `input.se-path` (`type="text"`, `readonly`, `size="60"`, value = path), `button("Copy path")` and a status span. `copySeedPath`: `navigator.clipboard && navigator.clipboard.writeText(path)` resolving → status `copied`; missing API or rejection → `input.focus(); input.select();` and status `selected — press Cmd+C`. `loadSeeds()` = both, then `updateSeedButtons()`, then `openSeedRun(S.seeds.run)` when a run is open.
- **SG64. Characters, Jobs, polling, workspace.**
  - `openCharacter`: the line at `:1778` becomes `res.data.dataset.stills.forEach(function (p) { gallery.appendChild(el("figure", {cls: "se-still"}, [el("img", {src: fileUrl(p), alt: p}), button("New seed from this", function () { seedFromStill(name, p); })])); });`. `seedFromStill(name, p)`: `const still = p.split("/").pop();` then `setSeedSource({kind: "character", character: name, still: still, path: p}, "still " + still + " of " + name)` and `showTab("seeds")`.
  - `jobLabel` becomes `return job.story_id || job.character || (job.seed_run ? "seed run " + job.seed_run : "") || (job.kind === "smoke" ? "smoke render" : "-");`.
  - `renderProgress`'s generic branch appends `" - candidate " + current + " of " + total` when `p.candidates && p.candidates.current`, and `" - " + done + " of " + total + " candidates"` when `p.candidates` and `current` is null.
  - `stopPolling` gets one added line after its forEach: `if (S.timers.seeds) { clearInterval(S.timers.seeds); S.timers.seeds = null; }` (the pinned `["jobs", "log", "host", "batch"]` array is unchanged).
  - `selectWorkspace` gets `resetSeeds();` directly before `await loadOptions();` (clears source, run, grid, both lists, stops the poll); the pinned `Promise.all` line is unchanged.
  - `start` calls `setupSeeds();` after `setupCompose();`. `setupSeeds` wires `#se-file` change, `#se-generate` click, and `input`/`change` on `#panel-seeds` → `updateSeedButtons`.
- **SG65. CSS** (`app.css`, appended): `.se-grid { display: flex; flex-direction: column; gap: 12px; }`, `.se-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; }`, `.se-img, .se-thumb { width: 320px; height: auto; border: 1px solid var(--line); }`, `.se-actions { display: flex; flex-direction: column; gap: 4px; }`, `.se-mini { width: 64px; height: auto; margin-right: 4px; }`, `.gallery figure { margin: 0; display: flex; flex-direction: column; gap: 4px; }`.

---

## 7. `bin/seed-edit-setup` (SG66-SG69)

- **SG66.** Python, shebang `#!/usr/bin/env python3`, stdlib plus `movie_ui_lib` (for `zimage_hub`, `model_check`, `choose_snapshot`). No options besides `-h`. Run only by the controller on the user's go; never by a test. Constants: `VENV = "~/mflux-edit/.venv"`, `MFLUX_SPEC = "mflux==0.24.0"`, `SETUP_MIN_FREE_GIB = 31.0`, `DEFAULT_BASE_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"` (the interpreter `~/mflux/.venv` was built from), and the repo/file constants of §1.1. The download target is `lib.zimage_hub()` (`$Z_IMAGE_HF_HOME/hub` or `~/hf_home/hub`, the internal-SSD cache Z-Image already uses), never `$HF_HOME`.
- **SG67.** Steps, in order (each failure prints `Error: …` on stderr):
  1. `$SEED_EDIT_MFLUX_PYTHON` set → exit 2 `SEED_EDIT_MFLUX_PYTHON is set; unset it to set up the default venv at ~/mflux-edit/.venv`.
  2. State: `venv_ok` = the venv python is executable and its dist-info version is exactly `0.24.0`; `q4_ok` = `lib.model_check(Q4_REPO, hub)` passes; `lora_ok` = the Lightning file is found in `hub`. The script carries its own copies of SG14's `mflux_version(venv)` (dist-info `METADATA` parse) and `find_lightning(hubs)` rules, with identical behaviour (a file without `.py` cannot be imported cleanly).
  3. All three ok → print `seed-edit-setup: nothing to do`, then step 9, exit 0.
  4. Free space: for the nearest existing ancestor of `hub` and of `~/mflux-edit`, `shutil.disk_usage(...).free / 2**30`; the smaller below 31.0 → exit 2 `only <x.x> GiB free on <path>; seed-edit-setup needs at least 31 GiB (q4 weights ~29 GB, Lightning LoRA ~0.85 GB, mflux venv)`.
  5. Base python = `$SEED_EDIT_SETUP_PYTHON` or `DEFAULT_BASE_PYTHON`; not executable → exit 2 `base python <path> is not executable (set SEED_EDIT_SETUP_PYTHON)`; `[py, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]` below 3.11 → exit 2 `base python <path> is Python <v>; mflux 0.24.0 needs 3.11 or newer`.
  6. Venv python missing → `[py, "-m", "venv", <VENV>]`; non-zero → exit 1 `python -m venv exited <rc>`.
  7. Version not `0.24.0` → `[<venv python>, "-m", "pip", "install", "mflux==0.24.0"]`; non-zero → exit 1 `pip install mflux==0.24.0 exited <rc>`.
  8. Not `q4_ok` or not `lora_ok` → `[<venv python>, "-c", DOWNLOAD, hub, Q4_REPO, EDIT_LORA_REPO, EDIT_LORA_FILE]` with `env = dict(os.environ, HF_HOME=dirname(hub), HF_HUB_OFFLINE="0", HF_XET_CHUNK_CACHE_SIZE_BYTES="0")`; non-zero → exit 1 `the download exited <rc>`. `DOWNLOAD` is:
     ```python
     import sys
     from huggingface_hub import hf_hub_download, snapshot_download
     hub, repo, lora_repo, lora_file = sys.argv[1:5]
     print(snapshot_download(repo_id=repo, cache_dir=hub), flush=True)
     print(hf_hub_download(repo_id=lora_repo, filename=lora_file, cache_dir=hub), flush=True)
     ```
     Only the q4 repo snapshot and the single Lightning file are fetched; both repos are public, so no token is used.
  9. Sizes: `seed-edit-setup: venv <path>: <x.xx> GiB` (sum of `lstat` sizes, symlinks not followed), `seed-edit-setup: q4 <snapshot>: <x.xx> GiB` (sum of the realpath sizes of the snapshot's files, each realpath once), `seed-edit-setup: Lightning <file>: <x.xx> GiB`, `seed-edit-setup: free on <hub ancestor>: <x.x> GiB`. Then `[sys.executable, <WS>/bin/seed-edit, "--probe"]` and print `seed-edit-setup: probe: Qwen-Image-Edit ok (<backend>)` or `seed-edit-setup: probe: Qwen-Image-Edit unavailable: <reason>` (informational).
- **SG68.** Exit codes: 0 done or nothing to do; 1 a step failed; 2 a precondition failed. Re-running after success does nothing but print (idempotent); re-running after a partial download resumes it.
- **SG69.** `HF_XET_CHUNK_CACHE_SIZE_BYTES=0` keeps hf-xet's chunk cache (default 10 GB) off the 31 GiB budget, and `HF_HOME=dirname(hub)` keeps token and xet state off a possibly unmounted global `HF_HOME`.

---

## 8. Errors

| Condition | Where | Text | Effect |
|---|---|---|---|
| no or bad token | any new route | `missing or invalid token` | 401 |
| bad `ws` | any new route | `resolve_ws`'s messages | 400 |
| bad run request field | `POST /api/seeds/runs` | SG33 rows 1-14 | 400, nothing created |
| upload missing | same | `source upload <id> not found` | 400 |
| run or candidate unknown / not ok | same | `unknown source run <run>` / `source run <run> has no ok candidate <n>` | 400 |
| character still missing or outside the library | same | `unknown character still <c>/<s>` | 400 |
| model unavailable | same | `<Z-Image\|Qwen-Image-Edit> is unavailable: <reason>` | 409, nothing created |
| probe failed | same | `cannot check the seed models: <detail>` (SG30 details) | 409 |
| low disk | same | `less than 2 GiB free on the disk holding <path> (<x.x> GiB free)` | 409 |
| unknown run in a URL | GET run, keep, use | `unknown seed run <run>` | 404 |
| bad `n` | keep, use | `n must be a candidate number from 1 to <count>` | 400 |
| bad folder | keep | `FOLDER_MSG` (SG34) | 400 |
| candidate not ok | keep / use | `candidate <n> of <run> is <status>; only an ok candidate can be kept` / `… used` | 409 |
| ok but file missing | keep, use | `candidate <n> of <run> has no image file` | 409 |
| folder is a symlink to elsewhere | keep | `folder <folder> resolves outside <seeds_root>` | 409, nothing written |
| Keep onto an existing name | keep | — | `-2`, `-3`, … (SG51) |
| bad tool arguments | `bin/seed-edit` | SG4 table | exit 2, nothing written |
| bad source | `bin/seed-edit` | SG9 texts | exit 2, run.json `failed` |
| low disk / busy GPU / model unavailable / low memory | `bin/seed-edit` | SG13-SG14 texts | exit 2, run.json `failed`, all candidates `failed` |
| mflux older than 0.22 | `bin/seed-edit` (and the child) | `mflux <v> in <venv> is older than 0.22.0 (run bin/seed-edit-setup)` | refused before loading; never runs 2509 |
| content-safety block | any backend | `candidate i/N blocked …` | that candidate only; no file |
| backend crash / child non-zero / child timeout | `bin/seed-edit` | SG17 texts (`… child timed out after 3600 s`) | exit 1, finished candidates kept, rest `failed`, job `failed` |
| cancel | `bin/seed-edit` | `interrupted` | exit 130, run.json `cancelled`, job `cancelled` |
| setup preconditions / step failures | `bin/seed-edit-setup` | SG67 texts | exit 2 / 1 |
| page gating | Seeds tab | SG59 reasons | Generate disabled |

---

## 9. Tests

Rules:
- Two new files. `tests/test_seed_edit_tool.py` (SGT1-SGT16) loads `bin/seed-edit` with `importlib.machinery.SourceFileLoader("seed_edit_tool", path)`, `importlib.util.spec_from_loader`, `module_from_spec` and `loader.exec_module` (never `load_module(`), and `seed_edit_mflux_child.py` by plain import. `tests/test_movie_ui_seedgen.py` (SGT17-SGT34) uses an `env` fixture like `tests/test_movie_ui_seedfolder.py:350-360` (`mt.set_home`, `mt.make_stub_workspace`, `mt.Running`, `CHARACTER_LIBRARY_DIR` removed unless a test sets it). Both docstrings state these rules and the run command `python3 -m pytest -q -p no:cacheprovider tests/<file>`.
- Every test sets `HOME` to `tmp_path/home` (via `mt.set_home` or `monkeypatch.setenv`), removes `HF_HUB_CACHE`, `SEED_EDIT_*`, and sets `HF_HOME` and `Z_IMAGE_HF_HOME` under `tmp_path`. HF caches are built with `mt.make_hf_cache` (one non-empty `x.safetensors` per repo, plus the Lightning file where needed).
- Process boundaries are stubbed, never crossed for real: the bf16 child via `SEED_EDIT_QWENEDIT_SCRIPT` (a Python stub run by `sys.executable`), the mflux child via `SEED_EDIT_MFLUX_PYTHON` (an executable stub with shebang `sys.executable`, beside a fake `lib/python3.13/site-packages/mflux-<v>.dist-info/METADATA`), and the in-process imports via `monkeypatch.setitem(sys.modules, …)` fakes of `z_image_skill`, `content_safety` and `character_dataset` (fake `busy_process`). Each stub records its argv, env subset and spec to a JSON file and behaves per a config file its test writes. The fake `content_safety.assert_image_safe` raises `ContentSafetyError` when the image's top-left pixel is pure red; stubs draw red for the candidates a test wants blocked. `tool.avail_gib`, `tool.total_gib`, `tool.missing_modules`, `tool.cpu_generator`, `tool.disk_free_gib` (SG13 step 1 calls this module function) and `srv.seed_free_gib` are monkeypatched. Real PNG/JPEG sources are drawn with PIL in `tmp_path`.
- No test uses the real HOME, loads a real model, runs `bin/seed-edit-setup`, or contacts a server other than the in-test `127.0.0.1` one. None touches port 8177 or 8178. No test dispatches a job (HTTP tests only queue).
- HTTP tests put an executable stub at `<ws>/bin/seed-edit` (written by a helper `stub_seed_edit(ws, models, exit=0, stderr="")`) that prints `json.dumps(models)` for `--probe`.

| ID | Covers | Test |
|---|---|---|
| SGT1 | SG8 | `canvas(W0, H0)` on §2.2's nine examples, exact; the refused case raises the SG9 too-small text |
| SGT2 | SG11, SG12, SG16, SG18 | Z-Image fake, `--candidates 3 --seed 100 --strength 0.3`: `cpu_generator` saw 101, 102, 103; `generate_variation` got a `W×H` image and strength 0.3; `cand_01..03.png` exist; final `run.json` == the expected dict (`state done`, `backend zimage`, sizes, statuses, float seconds); stdout lines match SG16; a monkeypatched `tool.say` snapshots `run.json` at each candidate line and finds that candidate already final; exit 0 |
| SGT3 | SG18 | seed 102 blocked → `cand_02.png` absent, status `blocked`, others ok, line `candidate 2/3 blocked …`, exit 0, `state done` |
| SGT4 | SG17, SG18 | `RuntimeError("boom")` on seed 102 → exit 1; `cand_01.png` kept; 2, 3 `failed` with two `failed` lines; `error == "Z-Image failed on candidate 2: RuntimeError: boom"`; no `work/*.part.png` left |
| SGT5 | SG4 | each SG4 row (candidates 0, 5, `x`; strength 0.05, 0.95, `x`; strength with qwen; seed -1, 2147483648; prompt `"  "`, 2001 chars; missing `--run-dir`; `--probe --model qwen`) → exit 2 with the exact `Error:` text and `--run-dir` not created |
| SGT6 | SG9, SG10, SG12 | GIF source → exit 2, exact text, `run.json` `failed` with every candidate `failed`; a 100×60 PNG → too-small text; an outside PNG is copied byte-exact to `source.png`; a JPEG with EXIF orientation 6 stored 200×100 gives `source_size` 100×200 and `work/source.png` 100×200 |
| SGT7 | SG13 | `disk_free_gib` 1.5 → exact disk text; fake `busy_process` → exact busy text; `avail_gib` 10 with `AVAIL_WAIT_S = 0` → exact memory text for Z-Image and for mflux q4; in each, no backend ran and `run.json` is `failed` |
| SGT8 | SG14 | `choose_qwen` matrix: bf16 cached + avail 70 → `diffusers-bf16`; bf16 cached + avail 40 + mflux ready → `mflux-q4` with why `diffusers bf16: only 40.0 GiB available (needs 64)`; bf16 absent + mflux ready → `mflux-q4`; mflux 0.21.0 → refusal containing `is older than 0.22.0`; no venv python → `no mflux venv at`; q4 missing; Lightning missing; `SEED_EDIT_QWEN_Q4_DIR=…/qwen-edit-q4` → basename text; `…/QWEN-IMAGE-EDIT-2511-q4` accepted; all texts exact |
| SGT9 | SG20, SG21, SG22 | mflux stub, 3 candidates, candidate 2 drawn red: stub started once with argv `[stub, <WS>/seed_edit_mflux_child.py, "--spec", <run>/work/mflux_spec.json]`, env `HF_HUB_OFFLINE == "1"`; spec == the SG20 dict (q4 snapshot path, Lightning snapshot path, steps 8, guidance 1.0, seeds base+i, pending paths); `cand_01`, `cand_03` exist, `cand_02` absent and its pending file deleted; statuses ok/blocked/ok; exit 0 |
| SGT10 | SG17, SG20 | mflux stub exits 1 after candidate 1 printing `boom` last → exit 1; `cand_01` ok; 2, 3 failed; `error == "mflux q4 child exited 1: boom"`; with the stub sleeping and `CHILD_TIMEOUT_S = 1` → `mflux q4 child timed out after 1 s` (the test reads the constant into the expected text) |
| SGT11 | SG19, SG22 | bf16 path (avail 70, bf16 cache present), qwenedit stub printing `cand_01.part.png ok 1.0s`, `cand_02.part.png blocked 1.0s`: started once with argv `[sys.executable, stub, "qwenedit", "--spec", <run>/work/qwenedit_spec.json]`; spec == the SG19 dict (skill `seed_edit`, true_cfg 1.0, report path); statuses ok/blocked; `cand_01.png` exists |
| SGT12 | SG6, SG12 | Z-Image fake raises `KeyboardInterrupt` on candidate 2 → `main` returns 130; `state cancelled`, `error interrupted`, 1 ok, 2..N failed |
| SGT13 | SG15 | in-process `probe()` on fixtures: both ok (`backend` `zimage`, `mflux-q4`); `total_gib` 128 + bf16 cache → qwen backend `diffusers-bf16`; total 48 + no mflux → qwen not ok with reason `diffusers bf16: needs a host with at least 64 GiB of memory (this host has 48.0 GiB); mflux q4: no mflux venv at …`. Subprocess `[sys.executable, "-X", "importtime", <WS>/bin/seed-edit, "--probe"]` with the fixture env: exit 0, stdout one JSON line with both keys, and the importtime stderr names none of `torch`, `PIL`, `psutil`, `diffusers`, `transformers`, `z_image_skill`, `content_safety`, `character_dataset` |
| SGT14 | §1.1 | `bin/seed-edit`'s mirrored constants equal `character_dataset`'s (`EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`, `EDIT_MIN_AVAIL_GIB`, `GENERATE_MIN_AVAIL_GIB`, `AVAIL_WAIT_S`, `CREATE_MIN_FREE_GIB`) |
| SGT15 | SG24, SG25, SG27 | the child's top-level import lines name exactly SG24's modules; `parse_version` on `0.24.0`, `0.22.0`, `0.21.9`, `x`, `None`; `main(["--spec", <missing path>])` with `importlib.metadata.version` patched to return `0.21.0` returns 2 and prints the refusal (the spec is never opened); the source contains `guidance=spec["guidance"]`, `bake_lora=False`, `negative_prompt=" "`, `ModelConfig.qwen_image_edit_2511()` |
| SGT16 | SG66-SG69 | `bin/seed-edit-setup` is never executed: its source contains `"mflux==0.24.0"`, `SETUP_MIN_FREE_GIB = 31.0`, `Q4_REPO`'s and the Lightning repo/file strings, `HF_XET_CHUNK_CACHE_SIZE_BYTES`, `cache_dir=hub`, and no `HF_TOKEN` |
| SGT17 | SG33-SG37 | `validate_run_request`: every row's exact message; first-failure order (bad prompt + bad model → the prompt message); defaults (zimage strength null/absent → 0.45, candidates absent → 4, seed absent → None); `valid_folder` on `heroes`, `a.b-c_d`, 64 chars yes; `""`, `runs`, `Runs`, `a..b`, `-x`, `.x`, 65 chars, `a/b`, `5` no; `new_run_id` matches `RUN_ID_RE`; `keep_name("se-…", 2, 1)`/`(…, 2, 3)`; `capability` and `availability_error` on ok, partial and `None` inputs; the module's imports are exactly `re`, `secrets`, `time`, `movie_ui_lib` |
| SGT18 | SG28, SG29, SG31, SG32 | `lib.job_vlm("seed-edit", {}, ws, None) == "forbidden"`; `seed_edit_argv` for zimage (`--strength 0.3`) and qwen (no `--strength`), exact lists; a `seed-edit` parser fed `candidate 1/4 ok 1.0s\ncandidate 2/4 blocked 2.0s\n` → `candidates == {"total": 4, "done": 2, "ok": 1, "blocked": 1, "failed": 0, "current": 3}`; before any line `total` comes from fields; a `character-create` parser fed the same lines has an unchanged snapshot key set |
| SGT19 | SG30 | `seed_edit_check` with the stub: valid JSON → models; exit 3 with stderr `nope` → `bin/seed-edit --probe exited 3: nope`; `not json` → unparsable; `{"zimage": {"ok": "yes", …}}` → unparsable; stub sleeping 2 s with `lib.LIGHT_TIMEOUT` patched to 1 → `timed out after 1 s` |
| SGT20 | SG40 | the six routes follow `POST /api/uploads` in SG40 order; `len(srv.ROUTES) == 63`; each sample matches its regex; 401 without and with a wrong token on each; `DELETE /api/seeds/runs` → 405; handlers are the `_h_seed_*` functions |
| SGT21 | SG33, SG44, SG45 | over HTTP, each 400 (bad ws; SG33 rows 1-14; the three existence messages) with its exact `error`; afterwards `generated/seeds` has no run and `queue.json` is unchanged |
| SGT22 | SG37, SG44, SG45 | probe says qwen unavailable → 409 `Qwen-Image-Edit is unavailable: <reason>`; stub exits 1 → 409 `cannot check the seed models: bin/seed-edit --probe exited 1: …`; `seed_free_gib` 1.0 → 409 exact; nothing created in each |
| SGT23 | SG44, SG46, SG53 | upload source (uploaded through `POST /api/uploads`), zimage, seed 7, 2 candidates → 201: `source.png` bytes == the upload; `run.json` == the SG44 step-7 record (`created` matched by format); the job's `kind`, `story_id` null, `character` null, `vlm` `forbidden`, `fields` keys exactly SG44's, argv == `lib.seed_edit_argv(fields, ws)`; the response `run` view has the SG43 keys and `job.seed_run == run`; seed null → `0 <= seed <= 2147483647` and candidate seeds `seed+1`, `seed+2` |
| SGT24 | SG44 | `{run, n}` source from a hand-made finished run (`run.json` + `cand_02.png`) → `source.png` == `cand_02.png`, origin `{"kind": "run", …}`; n pointing at a blocked candidate and at a missing file → 400 `source run <run> has no ok candidate 2`; unknown run → 400 |
| SGT25 | SG44 | `CHARACTER_LIBRARY_DIR=tmp/lib` with `kyra/dataset/stills/char_05.png` → copied, origin character; missing still, `char_5.png`, and a `char_06.png` symlink pointing outside the library → 400 `unknown character still …`; with the variable unset, `<ws>/generated/characters` is used |
| SGT26 | SG43, SG47 | three runs (one queued with a queued job, one `done`, one whose job dir is gone) plus `junk`, a run dir without `run.json` and a run-named symlink to outside: list newest first with only the three, exact item keys, states `queued`/`done`/`unknown`, `thumbs` only for ok files; 201 valid runs → 200 listed |
| SGT27 | SG42, SG43, SG48 | the detail view: exact keys, `path` only for ok candidates whose file exists, `source` path, `job` summary; a run cancelled while queued shows `cancelled`; 404 for an unknown run and for a run-named symlink to outside |
| SGT28 | SG50, SG51 | Keep `n=1` into `heroes` → 201 and `generated/seeds/heroes/<run>-01.png` equals the candidate; twice more → `-2`, `-3`; blocked → 409 exact; every bad folder of SGT17 → 400 `FOLDER_MSG`; `generated/seeds/out` a symlink to a directory outside → 409 `folder out resolves outside …` and nothing written there; `n` 0, 3 (of 2), `"1"` → 400 exact; unknown run → 404 |
| SGT29 | SG52, SG53 | Use → 201 `{upload_id, path, bytes}`; `upload_id` equals what `POST /api/uploads` returns for the same bytes, and the file exists under `<STATE>/uploads`; blocked → 409 `… only an ok candidate can be used`; `_h_upload`'s existing answers are unchanged |
| SGT30 | SG49 | folders: `heroes` (2 PNG, 1 JPG, 1 TXT, 1 subdir) → count 3; `runs`, `Runs`, `a..b`, a file `loose.png` and a symlinked dir to outside are not listed; sorted case-insensitively; absolute paths; no seeds dir → `{"root": …, "folders": []}` |
| SGT31 | SG36, SG38 | a fresh server's `seed_edit` capability is `{"ok": None, "reason": "probing", "checked": None, "models": None}`; with `probe_ws` = the stub ws, `GET /api/host?refresh=1` gives `ok True`, `reason None`, `models` from the stub; a failing stub gives `ok False`, the SG30 detail, `models None`; the other three capabilities are unchanged |
| SGT32 | SG46 | `job_summary` of a seed-edit job has `seed_run` == its run; a compose job (`mt.make_job`) has `seed_run: None` |
| SGT33 | SG54-SG65 | static page: every SG55 ID appears once in `index.html`; `tab-seeds` sits between `tab-compose` and `tab-stories`; the SG54 `TABS` line; these strings are in `app.js`: `"/api/seeds/runs"`, `"/api/seeds/folders"`, `"/keep"`, `"/use"`, `"New seed from this"`, `"Use in Compose"`, `"Edit again"`, `"Copy path"`, `"blocked by content safety"`, `"unavailable — "`, `"selected — press Cmd+C"`, `"seed run "`, `navigator.clipboard`, `S.timers.seeds`; each SG57 function is defined exactly once as `function <name>(`; the `test_mut24` patterns are absent; the `["jobs", "log", "host", "batch"]` substring and the pinned `Promise.all` line are still present; `node --check app.js` passes when `node` exists |
| SGT34 | SG2, SG24 | the new Python files are in `NEW_PY` (so `test_mut25` compiles them on 3.9 and scans them); `bin/seed-edit`'s top-level imports are stdlib plus `movie_ui_lib` only (regex on lines that start at column 0) |

### 9.1 Must-pass properties restated

SG12's write order (SGT2), the parent-side screening (SGT9), "never silently 2509" (SGT8, SGT15), the content-hash identity of Use (SGT29) and "nothing created on 400/409" (SGT21, SGT22) are the load-bearing tests; a change that weakens one of them fails review.

### 9.2 Existing tests to change (one test-only commit, after the feature commit)

| Test | Exact edit |
|---|---|
| `tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token` (`:44`) | `== 57` → `== 63` |
| `tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token` (`:66`) | `== 57` → `== 63` |
| `tests/test_movie_ui_seedfolder.py` (`:921`, `:958`) | both `== 57` → `== 63` |
| `tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv` (`:342-344`) | the key set gains `"seed_run"` |
| `tests/test_location_ui.py` (`:389-390`), `tests/test_movie_ui_batch.py` (`:495-496`), `tests/test_movie_ui_seams.py` (`:351-352`) | the pinned `TABS` text gains `"seeds", ` after `"compose", ` |
| `tests/test_movie_ui_builder.py` `NEW_PY` (`:213-217`) | append `"movie_ui_seedgen.py"`, `"bin/seed-edit"`, `"bin/seed-edit-setup"`, `"seed_edit_mflux_child.py"`, `"tests/test_seed_edit_tool.py"`, `"tests/test_movie_ui_seedgen.py"` |
| `tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files` (`:259-262`) | `allowed` gains `"movie_ui_seedgen"` |
| `tests/movie_ui_testutil.py::copy_ui` (`:463-465`) | the copied list gains `"movie_ui_seedgen.py"` |

No other existing test pins the Characters gallery line, `jobLabel`, `stopPolling`'s body or `_h_upload`'s body (checked with grep at `9eb363c`). Because of `NEW_PY`, no new file may contain `urllib`, `load_module(`, a `match` statement, `X | None` text or `zip(strict=`, docstrings included.

### 9.3 Browser check (before the merge; not pytest)

A throwaway demo under `$S/sgdemo/`, never committed. `demo.py` sets `HOME=$S/sgdemo/home`, `MOVIE_UI_VLM_LIFECYCLE=0`, `MOVIE_UI_VLM_TOOLS=$S/sgdemo/no-tools`, `MOVIE_UI_VLM_PORT=9`, `CHARACTER_LIBRARY_DIR=<ws>/generated/characters`; builds `ws = mt.make_stub_workspace("$S/sgdemo")`; writes the stub `<ws>/bin/seed-edit` (both models ok, qwen backend `mflux-q4`); writes `stub_config` so `character list` prints one trained row for `kyra` and `character show kyra` prints a record whose `dataset.contact_sheet` is `<ws>/generated/characters/kyra/dataset/contact_sheet.jpg`, with two real PNG stills beside it in `dataset/stills/`; pre-creates one finished run `se-20261102-120000-0001` (3 candidates: ok, blocked, ok; real PNGs); calls `srv.make_server(0, …)` on an OS-chosen port (never 8177, 8178, 8999), sets `server.probe_ws = ws` (so Re-check probes only the stub workspace), sets the four capabilities (`seed_edit` from `seedgen.capability`), prints the URL and serves without `start_threads` (no job ever runs). Pass when:
1. The Seeds tab sits right after Compose; the note reads `Qwen-Image-Edit backend: mflux q4`.
2. Uploading a 1536×1024 PNG shows the thumbnail and `1536 × 1024 → 1024 × 672`; Generate stays disabled with `enter a prompt` until a prompt is typed; Strength (0.45) shows for Z-Image and hides for Qwen.
3. Generate (Z-Image, 2 candidates, seed 7) opens the run: title `se-… · Z-Image`, status `queued (position 1)`, two rows of source + `waiting…`; Jobs shows a queued `seed-edit` job labelled `seed run se-…`.
4. The runs list shows the new run first, then the demo run with two thumbnails.
5. Opening the demo run shows three rows, source and candidate at the same width; row 2 reads `blocked by content safety` with no buttons.
6. Keep row 1 into `heroes` → `kept as …/generated/seeds/heroes/se-20261102-120000-0001-01.png`; again → `…-01-2.png`; the folders table lists `heroes  2  <absolute path>`; Copy path either says `copied` (paste matches) or selects the path text.
7. Use in Compose on row 3 → Compose tab, Seed image radio checked, status `seed from se-20261102-120000-0001 candidate 3 (…)`, and the command preview carries `--seed-image <STATE>/uploads/<sha256>.png`.
8. Edit again on row 1 → Seeds source becomes that candidate (`candidate 1 of se-20261102-120000-0001`), the prompt text is unchanged.
9. Characters → `kyra` shows `New seed from this` under each still; clicking one opens Seeds with `still char_01.png of kyra` and its thumbnail.
10. After the stub's qwen entry is changed to unavailable and Re-check is pressed, the Qwen option is disabled and the note reads `Qwen-Image-Edit: unavailable — <reason>`.

### 9.4 Live checks (each only on the user's go; never on macstudio)

- **L1 setup.** `bin/seed-edit-setup` on this Mac. Record its four size lines and probe line. Pass: exit 0 and `Qwen-Image-Edit ok (mflux-q4)`. If it refuses for free space (SG67 step 4), report the figure and stop.
- **L2 Z-Image.** From this Mac's movie-ui, one real seed image, a short edit prompt, Z-Image, 2 candidates. Pass: the job ends `done` with 2 candidates `ok` (a `blocked` is recorded, not a failure); its log shows `vlm: stopped for this job` before the tool and the postflight line after; record each candidate's seconds (candidate 1 includes the load, SG18).
- **L3 Qwen mflux q4** (after L1). Same with Qwen. Pass: the job ends `done`; the log shows `backend mflux-q4` and the child line naming `Qwen/Qwen-Image-Edit-2511` with `zero_cond_t` true in its overrides. Record: the highest `mlx peak memory` line, `psutil` available memory right before Generate, seconds per candidate, and candidate variety (mean absolute per-pixel difference of `cand_01` vs `cand_02` via `PIL.ImageChops.difference`, plus a one-line visual note).
Without the go, each is recorded as "not run (awaiting the user's go)".

---

## 10. Pass bar

1. Every new test (SGT1-SGT34) passes.
2. `python3 -m pytest tests/ -q -rA` from `WS` has no failures beyond the 2 known ones: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`.
3. `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`.
4. The browser check (§9.3) passes.
5. The live checks (§9.4) pass once the user gives the go; before that they are recorded as not run.

## 11. Rollout

1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-seedgen-9eb363c.tgz` excluding `generated/`.
2. At `9eb363c`, record the full-suite counts, the failure list and the offline line.
3. Feature commit: G1-G7 plus the two new test files.
4. Test-only commit: §9.2.
5. §10 items 1-3, the browser check, an Opus design review of the diff against this spec.
6. On the user's go: L1, then L2, then L3.

## 12. Risks

- **R1 Memory on 48 GiB.** The VLM lifecycle stops only the story server; the 8178 embed server keeps its memory (by design, VL R4). q4 needs ~27 GiB of weights plus 2-5 GB of activations. The 32 GiB floor with a 600 s wait refuses rather than swaps; L3 records the real peak so the floor can be tuned later.
- **R2 Setup disk.** The internal SSD has about 30 GiB free; the binding 31 GiB gate makes setup refuse until about 1 GiB more is freed. The refusal names the figure.
- **R3 Look-alike candidates.** Qwen seeds vary little; L3 records it. No mitigation in v1.
- **R4 Speed.** mflux runs a negative pass even at guidance 1.0: about 1.5-3 min per candidate plus the load, so 4 candidates take 6-12 minutes.
- **R5 mflux drift.** Pinned 0.24.0; the gate refuses below 0.22.0 in the parent (dist-info) and in the child (installed metadata); the child prints the config so L3 proves `zero_cond_t`.
- **R6 Probe vs run.** The probe judges bf16 by total memory and the job by available memory (SG15), so on a ≥ 64 GiB host the probe can say `diffusers-bf16` while the job runs mflux q4 (or refuses when mflux is absent). `run.json` records what ran.
- **R7 The job python.** Z-Image, the bf16 child and the parent's screening need torch, diffusers and transformers in movie-ui's interpreter; the probe reports a missing one and the page disables the model.
- **R8 `HF_HOME` on this host** may point at the unmounted USB volume; the q4 weights and setup therefore use the Z-Image hub, and bf16 lookup simply finds nothing there.

## 13. Decisions made in the spec

1. **Module:** `movie_ui_seedgen.py`, pure like `movie_ui_seedfolder.py`, holds request rules, folder rule, run ID and capability shape (SG1).
2. **Qwen bf16 reuse:** subprocess `character_dataset.py qwenedit --spec` with skill `seed_edit`, parsing its per-job line for progress — the file is pinned by `test_mut26` (SG19).
3. **Probe location:** `bin/seed-edit --probe`, run by the server as a light subprocess, so backend rules live in one place and the server stays stdlib-only (SG15, SG30).
4. **Probe bf16 eligibility:** total memory ≥ 64 GiB at probe time; available ≥ 64 GiB stays the run-time rule — the VLM is up when the probe runs (SG15).
5. **Weights present:** `lib.model_check` (intact snapshot, no partial blobs) for every repo; Lightning = non-empty file in the chosen snapshot — the same rule V3 uses (SG14).
6. **Hub order:** q4 and Lightning are looked up in the Z-Image hub, then the default hub; bf16 only in the default hub, where the unchanged child loads from (SG14).
7. **mflux version gate:** parse `METADATA` from the venv's dist-info; no subprocess, no torch (SG14).
8. **q4 path:** the local snapshot directory with an explicit `ModelConfig.qwen_image_edit_2511()`; override dirs must contain `qwen-image-edit-2511` in the basename (SG14, SG25).
9. **Screening for mflux:** in the parent, before the final rename (SG20).
10. **Memory floors:** Z-Image 20 GiB and mflux 32 GiB with a 600 s wait, psutil available, like `character_dataset`; no `mps_guard` (SG13).
11. **Busy check:** reuse `character_dataset.busy_process` (SG13).
12. **Disk floor:** 2 GiB in the tool and in the route (notes' 409) (SG13, SG44).
13. **Exit codes:** 0 / 1 / 2 / 130 as SG5, matching the house tools.
14. **Random seed:** drawn by the server (and by the tool when run by hand) with `secrets.randbelow(2^31)`; candidate seeds are `base + i` without wrap (SG4, SG44).
15. **Size math:** integer floor to 1024 on the long edge, then floor to 16; no upscaling; minimum side 64 (SG8).
16. **EXIF:** transposed working copy `work/source.png` for every backend; `source.<ext>` stays exact (SG10).
17. **run.json:** one schema with `pending` before a candidate ends; the server writes it once before queueing, the tool owns it after (SG11, SG12, SG44).
18. **Write order:** file, then run.json, then the progress line (SG12).
19. **Progress lines:** `candidate i/N ok|blocked s.ss` / `failed`; a dedicated parser branch for kind `seed-edit` (SG16, SG31).
20. **Job kind policy:** `seed-edit` is VLM-`forbidden` (SG28).
21. **Child timeout:** 3600 s per run, group kill (SG21).
22. **Overrides:** four `SEED_EDIT_*` variables, like `CHARACTER_MFLUX_TRAIN` (SG23).
23. **Run ID:** `se-` + UTC time + 4 hex, redrawn while the directory exists (SG35, SG44).
24. **Folder rule:** story-ID charset, 1-64 characters, `runs` refused case-insensitively (SG34).
25. **Keep:** `O_EXCL` claim under `SEEDS_LOCK`, `-2`, `-3`… (SG50, SG51).
26. **Use:** `store_upload` extracted from `_h_upload`, so the ID is identical by construction (SG53).
27. **Request shape:** single `error` per 400, first failure only, like the other movie-ui routes (SG33).
28. **`ws` in every body/query:** the notes' Keep/Use bodies gain `ws`, needed to find the run (SG50, SG52).
29. **URL run unknown:** 404 `unknown seed run <run>` (body-field unknowns stay 400, notes) (SG42).
30. **Responses wrapped:** `{"runs": […]}`, `{"root", "folders": […]}`, `{"run": view}` (SG44, SG47, SG49).
31. **Run state:** final tool state, else the job's state, else `unknown` (SG43).
32. **Runs cap:** 200 newest (SG47).
33. **Character still path:** `<library>/<name>/dataset/stills/char_NN.png` with the realpath inside the library; no `bin/character` subprocess (SG44).
34. **Jobs label:** `job_summary.seed_run` → `seed run <run>` (SG46, SG64).
35. **Capability shape:** a fourth entry `seed_edit` with `models`; no header badge (SG36, SG38).
36. **Tab position:** right after Compose (SG54).
37. **Incremental grid:** rows keyed by n, so polling never wipes a typed folder name (SG61).
38. **Thumbnail size:** computed in the browser from the loaded image with the tool's formula; the server never decodes images (SG58).
39. **Copy path:** `navigator.clipboard.writeText`, else select the read-only input (SG63).
40. **Setup location and python:** `~/mflux-edit/.venv` from the 3.13 framework python (`SEED_EDIT_SETUP_PYTHON` overrides), downloads into the Z-Image hub with the xet chunk cache off; exit 0 when its three items are present (SG66-SG69).
41. **Tests in `NEW_PY`:** all new Python files, for the 3.9 compile and the pattern scan (SGT34).

## 14. Design points the code makes impossible or risky

1. **"Reuse character_dataset.py's Qwen child"** — the file is a pinned pipeline file (`test_mut26`, `PIPELINE_FILES`), so it cannot be edited for incremental reporting or a `seed_edit` mode. Resolution: run it unchanged as a subprocess; its existing per-job stdout line and `spec["skill"]` give progress and the right safety label (SG19).
2. **"Same stop/restart of the model servers (VLM lifecycle)"** with **"fits 48 GB with the vllm servers stopped"** — the lifecycle stops only the story server and deliberately never the 8178 embed server, so "servers stopped" is not guaranteed. Resolution: no new server control; a 32 GiB available-memory floor with a 600 s wait refuses with a clear reason instead of swapping (SG13, R1).
3. **"≥ 64 GiB available"** — at probe time the VLM is up, so available memory would misjudge large hosts. Resolution: total memory for the probe's eligibility, the notes' available-memory rule at run time (SG14, SG15, R6).
4. **"Refuses under 31 GiB free"** vs **"~30 GiB free"** on this Mac — setup will refuse until about 1 GiB is freed. Resolution: kept as approved; the refusal names the figure (R2).
5. **"Thumbnail + size shown"** — the server is stdlib-only and cannot decode images. Resolution: the browser computes the size from the loaded image with the same formula; the tool enforces it (SG58, SG8).
6. **mflux model-dir basename inference** — verified in the 0.24.0 source that an explicit `model_config` sets the 2511 overrides regardless of the path; override dirs are still basename-checked (SG14, SG25).
7. **"Download into the default HF cache"** — `HF_HOME` on this host may name the unmounted USB volume, and hf-xet's chunk cache could add up to 10 GB. Resolution: download into the Z-Image hub on the internal SSD, `HF_HOME` pointed beside it, chunk cache off (SG66-SG69).
8. **Content safety in `~/mflux-edit`** — mflux 0.24.0 declares torch and transformers, so `content_safety` would import there, but the parent screens anyway (decision 9).
9. **Page bans** — `\bprompt\(` and the pinned `["jobs", "log", "host", "batch"]` and `Promise.all` lines constrain naming and placement (SG56, SG64).

## 14a. Amendments during implementation

Made by the controller from the task and final reviews; each is pinned by a test.

1. **§9.2 (PR2).** The test-only commit also changes `test_sdt19_the_seed_folder_tag` (`tests/test_movie_ui_seedfolder.py:612`): `len(j) == 15` becomes `== 16`, because SG46 adds the 16th summary key.
2. **SG21.** `run_child` returns the exit code and whether the `CHILD_TIMEOUT_S` timer killed the child. Only a timer kill gives the SG17 timeout text; any other SIGKILL (for example a macOS memory-pressure kill) is an ordinary `<label> child exited -9: <last line>`.
3. **SG60/SG62/SG63 (page guards).** Only one seed poll runs at a time and never on a hidden tab; a Runs or Seed folders answer for a workspace that is no longer selected is ignored; a workspace switch while the Seeds tab is open reloads both lists; Keep and Use in Compose are disabled while their request runs; Generate's unknown outcome (status 0, 5xx, or a 201 without a run) shows `the request may have been queued — check Runs and Jobs before retrying` and refreshes Runs and Jobs; a source image that fails to load is dropped with `the source image could not be loaded — pick it again`; a 201 also calls `loadSeedRuns()` so the new run is listed at once.
4. **SG9.** A Pillow format of `MPO` (a JPEG with an MPF secondary image, as iOS and Android HDR photos are) counts as JPEG: `source.jpg`, frame 0.
5. **SG20 / `/files`.** The guarantee is that no unscreened candidate is reachable: `/files` answers 403 `path not allowed` for any path inside `generated/seeds/runs/<run>/work/` (compared by inode, so case and symlinks do not get round it).
6. **SG67 step 4 / SG68.** The free-space check needs `31 GiB − what an earlier run left` (the lstat sizes of the q4 and Lightning repo directories in the hub and of the venv), so re-running after a partial download resumes it as SG68 says. The download also sets `HF_HUB_ENABLE_HF_TRANSFER="0"`.

## 15. Open questions

None. Every point the notes left open is decided in Section 13.
