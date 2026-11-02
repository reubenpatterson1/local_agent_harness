# Seed models: a fixed Qwen model registry (Qwen-Image-2.1 q4/q8/bf16, 2511 q4/bf16) with model and LoRA selection on the Seeds tab

Date: 2026-11-02

Status: design spec. The user approved the design (scratchpad `seedmodels-design-notes.md`, Sections 1-3, "proceed") on 2026-11-02. This document carries that design without reopening it. Each detail the notes leave open is decided here and marked **[spec choice]**; Section 13 lists them all. Section 14 lists the points the code or the upstream sources make impossible or risky, with their resolution. Section 14a records the amendments from the final whole-branch review; where it and an earlier section differ, Section 14a wins. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/seedmodels-wt`, branch `seed-models`, stacked on `seed-generator` at `aee9461`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`; every line number cites `aee9461`.

This spec **amends** [SG] `docs/superpowers/specs/2026-11-02-seed-generator-design.md` (including §14a). Every SG requirement stays in force except where Section 12 names it as superseded or amended. Requirement IDs here are **SQ1-SQ56**, tests are **SQT1-SQT22**. No spec, test or source file uses `SQ<n>` or `SQT<n>` (checked with grep at `aee9461`; `SM<n>` is taken by a narrative-dialogue plan, so it is not used).

Terms: a **registry model** is one entry of `QWEN_MODELS` (§2); a **registry LoRA** is one entry of `QWEN_LORAS`; a **family** is `qwen21` (Qwen-Image-2.1) or `qwen2511` (Qwen-Image-Edit-2511); a **selection** is one registry model plus 0-2 registry LoRAs with a scale each. Other terms are [SG]'s.

---

## 0. Scope

### 0.0 The approved design (binding summary)

1. Default Qwen model: Qwen-Image-2.1 mflux q4 (`mflux-community/qwen-image-2-1-mflux-q4`) plus the abenzerps uncensored LoRA (`qwen-image-2.1-uncensored-lora.safetensors` from `abenzerps/Qwen-Image-2.1-Uncensored-Quantized`) at strength 1.0. The user accepted the Qwen Research License (non-commercial) by choosing it.
2. Fixed registry, no free-form repo IDs or paths: `qwen21-q4` (default), `qwen21-q8`, `qwen21-bf16` (official `Qwen/Qwen-Image-2.1`), `qwen2511-q4` (the current q4 with its Lightning 8-step LoRA built in), `qwen2511-bf16` (the current diffusers route). 2.1 without the uncensored LoRA is selectable.
3. LoRA registry, family-filtered: `uncensored` (2.1, default on at 1.0) and `viggle-turbo` (2.1, default off, forces 6 steps and scheduler `viggle_turbo`). Each checked LoRA has a strength in (0, 2].
4. Explicit selection replaces the auto-by-memory 2511 backend choice.
5. `bin/seed-edit-setup --model ID [--lora ID ...]`, default `qwen21-q4` + `uncensored`. The model is the only repo snapshot; every LoRA is a single-file download. Per-selection free-disk floor; interrupted downloads resume.
6. Child dispatch by family; mflux stays pinned `==0.24.0`. Probe per model and per LoRA `{ok, reason}`. `run.json` records the selection; old runs still open.
7. `content_safety.assert_image_safe` runs on every candidate of every model, with or without a LoRA.
8. 400 for unknown IDs, wrong-family LoRA, strength out of range; 409 for not installed or memory below the floor, the reason naming the setup command.
9. Live A/B checks run by the user on the macstudio host (the agent has no access to it).

### 0.1 Verification of the two open items (evidence; nothing downloaded beyond metadata and safetensors headers)

**(a) mflux 0.24.0 loads the official `Qwen/Qwen-Image-2.1` repo unquantized: yes.** `qwen21-bf16` is therefore an **mflux** entry; diffusers `QwenImage21Pipeline` is not used anywhere (SQ12).
- HF API `GET /api/models/Qwen/Qwen-Image-2.1?blobs=true`: sha `d26bb61231c349cf6b7896fa83353113880e1ba3`, `gated: false`, license `other` / `qwen-research`. Files include `model_index.json`, `processor/{added_tokens.json, chat_template.jinja, merges.txt, preprocessor_config.json, special_tokens_map.json, tokenizer.json, tokenizer_config.json, video_preprocessor_config.json, vocab.json}`, `scheduler/scheduler_config.json`, `text_encoder/config.json` + 4 shards + index, `transformer/config.json` + 2 shards + index, `vae/config.json` + `vae/diffusion_pytorch_model.safetensors`. Every component config and `processor/` that `QwenImage21Initializer` requires is present.
- mflux tag `v.0.24.0` (read with `gh api repos/filipstrand/mflux/contents/...?ref=v.0.24.0`):
  - `src/mflux/models/qwen21/qwen_image21_initializer.py:50-66`: `root = PathResolution.resolve(model_path or model_config.model_name, download_patterns or definition.get_download_patterns())`; then it requires `vae/`, `transformer/`, `text_encoder/` `config.json` and its error text says "Use the original Qwen-Image-2.1 checkpoint or an export from QwenImage21Edit.save_model".
  - `src/mflux/models/common/config/model_config.py:187-188, 1055-1069`: `ModelConfig.qwen_image_21()` has `model_name="Qwen/Qwen-Image-2.1"`, so the official repo is mflux's own default for `QwenImage21Edit` (`qwen_image_21_edit.py:47-69`, `model_config or ModelConfig.qwen_image_21()`).
  - `src/mflux/models/common/resolution/model_revisions.py:55`: mflux pins `"Qwen/Qwen-Image-2.1": "d26bb61231c349cf6b7896fa83353113880e1ba3"`, the same commit as the HF API's current sha.
  - `src/mflux/models/common/resolution/path_resolution.py:20, 108`: a local path that exists is used as is (rule `local`); a repo ID is fetched with `snapshot_download(repo_id, allow_patterns=…, revision=ModelRevisions.get(path))`.
  - `src/mflux/models/qwen21/weights/qwen_image21_weight_definition.py:31-42`: the download patterns are `model_index.json`, `scheduler/*.json`, `processor/**`, `vae/*.json`, `vae/*.safetensors`, `transformer/*.json`, `transformer/*.safetensors`, `text_encoder/*.json`, `text_encoder/*.safetensors`; `:45-54` the tokenizer is read from `processor/`.
  - `src/mflux/models/qwen21/README.md:28-33, 50-56`: "On Apple Silicon the bf16 default is both the fastest and the most accurate path … Peak memory is ~46 GB … a 64 GB machine is the comfortable default"; the Python API example uses `quantize=None`.
  - The facts file's "a base-2.1 bf16 mflux-community repo was NOT found" is out of date: `mflux-community/qwen-image-2-1-mflux-bf16` exists (sha `cf34f2422e8fa33c2841239dfe3c34f5f319a122`, 33,127,131,833 B). The binding design names the official repo, and the official repo loads natively, so the registry uses the official repo; the community bf16 repo is the fallback named in Open question 1.
- Not proven by running: no model was loaded. Live row A5 (§10) is the proof.

**(b) The Viggle turbo LoRA.** Repo `Viggle/Qwen-Image-2.1-viggle-turbo` (the official Viggle org repo; HF search `viggle` lists it first and the rest are re-uploads or GGUF packs), sha `009a44a895ef85f7e643c80fdca9543795248867`, `gated: false`, `private: false`, license `other` / `qwen-research` (`LICENSE` in the repo), base model `Qwen/Qwen-Image-2.1`, repo total 104,875,454,260 B (97.67 GiB). File **`Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors`**, 679,604,800 B, LFS sha256 `0c98591700346f9777051d4e6fa29aa94519abec0d85b1f1f672a2a3db8c94b3`. Its safetensors header (bytes 0-62015 read with HTTP range requests) holds 454 tensors, bf16, rank 128, `lora_alpha` 128: `transformer.transformer_blocks.{0..31}.{attn.to_q, attn.to_k, attn.to_v, attn.to_out.0, img_mlp.proj, img_mlp.gate_layer, img_mlp.out}.lora_{A,B}.weight`, `transformer.modulation.1.lora_{A,B}.weight`, `transformer.time_text_embed.timestep_embedder.linear_{1,2}.lora_{A,B}.weight`. Every key matches a pattern of mflux's `Qwen21LoRAMapping` (`src/mflux/models/qwen21/weights/qwen21_lora_mapping.py:9-66`, the `transformer.…` prefix forms). The v0.2.1 r128 file (679,604,800 B, sha256 `bafb91d0…345b`) has the identical key set and shapes; v0.3 is the newest and the model card (`README.md:26-61`) calls it current. Card usage (`README.md:158-164`): 6 steps on the raw sigma nodes, no CFG, no negative prompt, "keep the LoRA unmerged and at scale 1.0" — mflux's `ViggleTurboScheduler` implements exactly these nodes and refuses any step count but 6 (`qwen21_scheduler.py:28-41`).

Also pinned from the HF API for the record (Section 2 uses these exact values):

| Repo | sha | bytes (files setup fetches) | license |
|---|---|---|---|
| `mflux-community/qwen-image-2-1-mflux-q4` | `b6c0fc76350650482d13aea89b316c28cd487f7f` | 10,638,928,735 (whole repo, 21 files; "Converted with MFlux 0.24.0") | qwen-research |
| `mflux-community/qwen-image-2-1-mflux-q8` | `f5c8cc79a6741026a6057546012fba3b0a4b5b25` | 18,460,986,297 (whole repo, 25 files) | qwen-research |
| `Qwen/Qwen-Image-2.1` | `d26bb61231c349cf6b7896fa83353113880e1ba3` | 33,131,601,593 (24 files matching the 9 mflux patterns; skips `.gitattributes`, `LICENSE`, `README.md`, `assets/qr.png`) | qwen-research |
| `mflux-community/qwen-image-edit-2511-mflux-q4` | `3c74aab7dd79e6a8148c329cbca78c00c049ec3b` | 28,958,989,673 (whole repo) | Apache-2.0 |
| `lightx2v/Qwen-Image-Edit-2511-Lightning` | `107d238d68b8387e32843d0b4a2e24ceb0d3ad86` | 849,608,296 (one file; sha256 `a9e81a58…1ba8`) | Apache-2.0 |
| `abenzerps/Qwen-Image-2.1-Uncensored-Quantized` | `7959e658915f52274897fb573ffeda49de8dc16b` | 33,586,704 (one file; sha256 `00ee2cb7f00a37b097640c1880ed0d17e368e30599f34bb348fee0e8c2cc4ca1`; repo total 97.96 GiB) | qwen-research |
| `Viggle/Qwen-Image-2.1-viggle-turbo` | `009a44a895ef85f7e643c80fdca9543795248867` | 679,604,800 (one file) | qwen-research |
| `Qwen/Qwen-Image-Edit-2511` | (current `6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9`; not pinned, §2) | not fetched by setup | Apache-2.0 |

All are public and ungated; no token is used anywhere. The abenzerps LoRA header (32,264 B) holds 256 bf16 tensors `transformer_blocks.{0..31}.attn.{to_q,to_k,to_v,to_out.0}.lora_{A,B}.default.weight`, rank 16, no metadata: mflux mapping pattern 1.

### 0.2 Grounding (verified at `aee9461`)

- **Tool.** `bin/seed-edit`: constants `:60-83` (`BF16_MIN_AVAIL_GIB` `:68`, `MFLUX_MIN_AVAIL_GIB` `:69`, `Q4_REPO` `:77`, `Q4_NAME_PART` `:78`, `MFLUX_MIN_VERSION = (0, 22, 0)` `:79`, `BACKEND_LABELS` `:83`); `parse` `:109-115`; `check_args` `:118-159`; `canvas` (multiple 16) `:166-177`; `prepare_source` `:196-211`; `find_lightning` `:280-291`; `bf16_problem` `:294-305`; `mflux_problem` with the `SEED_EDIT_QWEN_Q4_DIR`/`SEED_EDIT_LIGHTNING_FILE` overrides and `refs/main` lookup `:332-382`; `choose_qwen` (auto by memory) `:385-399`; `probe` (`qwen.backend`) `:402-418`; `preflight` `:438-460`; `new_record` `:467-478`; `run_bf16` `:648-671`; `run_mflux` (spec keys `model_path, lora_path, …`, parent screening `:688-702`) `:674-706`; `run` (runner map `:729`, failure text `:733`) `:713-742`.
- **Child.** `seed_edit_mflux_child.py`: `MIN_VERSION = (0, 22, 0)` `:27`; version gate `:52-60`; one fixed class/config `QwenImageEdit` + `ModelConfig.qwen_image_edit_2511()` `:63-70`; one LoRA `lora_paths=[spec["lora_path"]], lora_scales=[1.0]` `:69-70`; generate with `negative_prompt=" "` and no scheduler `:74-77`; `result.image.save` `:78`.
- **Setup.** `bin/seed-edit-setup`: no options `:177-179`; constants `SETUP_MIN_FREE_GIB = 31.0`, `Q4_REPO`, `EDIT_LORA_*` `:37-49`; `find_lightning` copy `:86-96`; `present_gib(hub, venv)` `:134-142`; `report` `:150-172`; fixed free-space formula `:192-199`; `DOWNLOAD` (one snapshot, one file, no revision) `:45-49`, run `:217-222`.
- **Pure module.** `movie_ui_seedgen.py`: `MODELS` `:23`; `validate_run_request` `:61-97`; `capability` `:116-122`; `availability_error(models, detail, model)` `:125-131`.
- **Library.** `movie_ui_lib.py`: `seed_edit_argv` `:1199-1208`; `_probe_model` (three keys) `:1648-1655`; `seed_edit_check(ws_real)` `:1658-1677`; `intact_scan` `:1779-1839`; `repo_dir_name` `:1743`; `choose_snapshot` (refs/main, else the only snapshot) `:1753-1771`.
- **Server.** `movie_ui_server.py`: initial `seed_edit` capability `:215`; `refresh_capabilities` `:222-233`; `run_view` `:1692-1706`; `_h_seed_run_create` `:1733-1778` (record `:1765-1771`, fields `:1772-1774`); `_h_seed_runs` `:1781-1802`.
- **Page.** `index.html` Seeds panel `:160-193` (`se-model` `:173-176`, `se-model-note` `:177`). `app.js`: constants `:15-21`; `S.seeds` `:43`; `seedCanvas(w, h)` `:1761-1770`; `updateSeedButtons` `:1795-1849` (option disabling `:1799-1806`, backend note `:1808-1820`); `seedBody` `:1851-1862`; run title `:1923-1924`; `editSeedAgain` `:2014-2017`; `loadSeedRuns` model cell `:2038`; `resetSeeds` `:2084-2103`; `setupSeeds` load handler `:2108-2115`. `el(tag, attrs, children)` sets any other attribute with `setAttribute` (`:49-60`). `.grid .wide { grid-column: 1 / -1; }` `app.css:30`.
- **Tests.** `tests/test_seed_edit_tool.py` (SGT1-SGT16 and the review/final pins), `tests/test_movie_ui_seedgen.py` (SGT17-SGT34). `mt.make_hf_cache` always names the snapshot `0123456789abcdef0123456789abcdef01234567` and writes `refs/main` unless `refs=False` (`tests/movie_ui_testutil.py:298-323`). `NEW_PY` (`tests/test_movie_ui_builder.py:213-217`) already lists the six seed-generator files, so the edited ones keep being compiled on `/usr/bin/python3` (3.9) and scanned; this feature adds no file.
- **mflux 0.24.0 2.1 edit API** (`qwen_image_21_edit.py`): `EDIT_SCHEDULERS = ("linear", "viggle_turbo")` `:36`; `__init__(quantize, model_path, model_config, lora_paths, lora_scales, bake_lora, compute_precision, small_text_encoder)` `:47-69`; `generate_image(seed, prompt, num_inference_steps, height, width, guidance=1.0, negative_prompt=None, image_paths, …, scheduler="linear")` `:71-92`; references are opened as RGBA `:110`; **`QwenImage21LatentCreator.validate` refuses a width or height that is not a multiple of 32** (`qwen_image21_latent_creator.py:24-26`, called at `:118`); a negative prompt is only needed when guidance > 1 (`:121`). Turbo detection is by `model_config.model_name` only (`qwen21_scheduler.py:109-116`), and `check_generate` returns at once for the non-Turbo config (`:119-122`). The 2.1 default step count is 40 (`src/mflux/cli/defaults/defaults.py:66`). LoRAs apply at run time on pre-quantized weights (`qwen21_initializer.py:104-116`).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| Q1 | `movie_ui_seedgen.py` | the registry, selection rules, settings, legacy derivation, registry view, capability and 409 rules (§2, §5) |
| Q2 | `bin/seed-edit` | `--qwen-model`/`--lora`, per-family canvas, registry lookups, probe shape, preflight, child spec (§3) |
| Q3 | `seed_edit_mflux_child.py` | family dispatch, LoRA lists, scheduler, 0.24.0 gate, RGB save (§4) |
| Q4 | `bin/seed-edit-setup` | `--model`/`--lora`, per-selection floor, pinned downloads (§6) |
| Q5 | `movie_ui_lib.py` | `seed_edit_argv` selection args, `seed_edit_check` new shape (§5.3) |
| Q6 | `movie_ui_server.py` | capability registry, create fields/record, view and list keys (§5.4) |
| Q7 | `static/movie-ui/index.html`, `app.js`, `app.css` | Qwen model select, LoRA rows, steps text, gating, titles, Runs column (§7) |
| Q8 | `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_seedgen.py` | SQT1-SQT22 and the §9.2 edits |

No new file. Untouched: `character_dataset.py` and every other `PIPELINE_FILES` member (`test_mut26` passes unedited), `content_safety.py`, `mps_guard.py`, `z_image_skill.py`, `movie_ui_seedfolder.py`, `movie_ui_batch.py`, `tests/movie_ui_testutil.py`, `tests/test_movie_ui_builder.py`.

### 0.4 Out of scope

- Free-form repo IDs, local model directories or LoRA files chosen by the user (the `SEED_EDIT_QWEN_Q4_DIR` and `SEED_EDIT_LIGHTNING_FILE` overrides are removed, SQ19).
- diffusers `QwenImage21Pipeline`; the Qwen-Image-2.1-Turbo checkpoint; the lightx2v 2.1 Lightning LoRA (`lora.down`/`lora.up` keys mflux does not map); Viggle's 9-step mode; any q3/q5/q6 repo.
- User-editable steps, guidance or scheduler (steps are derived and shown read-only); negative prompts; multi-reference edits; LoRAs on the 2511 family.
- `bin/seed-edit-setup` installing `qwen2511-bf16` (SQ43).
- Running setup, a real model or a real server in tests; any agent access to the macstudio host.

### 0.5 Must-haves and nice-to-haves

Every SQ requirement and SQT test is a must-have. There are no nice-to-haves.

---

## 1. Architecture (changes to [SG] §1)

```
Seeds tab: source + prompt + Model (Z-Image | Qwen-Image) + [Qwen model select + LoRA rows + steps text]
  Generate -> POST /api/seeds/runs {…, qwen_model, loras}: validate against the registry (400)
           -> bin/seed-edit --probe in ws: per-model / per-LoRA {ok, reason} (409) -> disk (409)
           -> run.json gains qwen_model, loras, steps, scheduler -> job argv gains --qwen-model, --lora ID=S
<py> bin/seed-edit --model qwen --qwen-model qwen21-q4 --lora uncensored=1.0 …:
   canvas (multiple 32 for qwen21) -> preflight: disk, busy, the selected model and LoRAs installed, memory floor
   -> backend mflux: child `<mflux venv python> seed_edit_mflux_child.py --spec` with {"family", lora_paths, lora_scales,
      steps, scheduler}; the parent screens every pending image with content_safety (unchanged SG20 rule)
   -> backend diffusers (qwen2511-bf16 only): unchanged character_dataset.py qwenedit child (screens itself)
```

- **SQ1.** The registry lives in `movie_ui_seedgen.py` (data plus pure functions). `bin/seed-edit` and `bin/seed-edit-setup` import it at module top as `import movie_ui_seedgen as seedgen` (directly after `import movie_ui_lib as lib`). `movie_ui_seedgen.py`'s own imports stay exactly `re`, `secrets`, `time`, `movie_ui_lib` (SG1 unchanged). The registry dicts are never mutated at run time. **[spec choice]** One source for the tool, setup, server and (through the capability, SQ33) the page; no new file, so `NEW_PY` and the import allow-list need no edit.
- **SQ2.** `seed_edit_mflux_child.py` does not import the registry (it runs under the venv's python, outside the workspace's imports); it carries its own `FAMILIES` table, which SQT9 pins equal to the registry's `mflux_class`/`mflux_config` per family.

---

## 2. The registry (`movie_ui_seedgen.py`) (SQ3-SQ11)

- **SQ3.** These constants are added after `SOURCE_MSG` (`:31`), typed exactly (values from §0.1):

```python
MODELS = {"zimage": "Z-Image", "qwen": "Qwen-Image"}          # replaces :23 ("Qwen-Image-Edit" -> "Qwen-Image")
QWEN_FAMILIES = {"qwen21": "Qwen-Image-2.1", "qwen2511": "Qwen-Image-Edit-2511"}
QWEN21_PATTERNS = ["model_index.json", "scheduler/*.json", "processor/**", "vae/*.json", "vae/*.safetensors",
                   "transformer/*.json", "transformer/*.safetensors", "text_encoder/*.json",
                   "text_encoder/*.safetensors"]          # mflux 0.24.0 QwenImage21WeightDefinition patterns
QWEN21_REQUIRED = ("vae/config.json", "transformer/config.json", "text_encoder/config.json")
QWEN_RESEARCH = "Qwen Research License (non-commercial)"
LIGHTNING = {"repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
             "revision": "107d238d68b8387e32843d0b4a2e24ceb0d3ad86",
             "file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
             "bytes": 849608296, "scale": 1.0}
QWEN21_CLASS = "mflux.models.qwen21.variants.edit.qwen_image_21_edit.QwenImage21Edit"
QWEN2511_CLASS = "mflux.models.qwen.variants.edit.qwen_image_edit.QwenImageEdit"
QWEN_MODELS = (
    {"id": "qwen21-q4", "label": "Qwen-Image-2.1 q4", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0fc76350650482d13aea89b316c28cd487f7f",
     "allow_patterns": None, "bytes": 10638928735, "quant": "q4",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 20.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-q8", "label": "Qwen-Image-2.1 q8", "family": "qwen21", "backend": "mflux",
     "repo": "mflux-community/qwen-image-2-1-mflux-q8", "revision": "f5c8cc79a6741026a6057546012fba3b0a4b5b25",
     "allow_patterns": None, "bytes": 18460986297, "quant": "q8",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 32.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen21-bf16", "label": "Qwen-Image-2.1 bf16", "family": "qwen21", "backend": "mflux",
     "repo": "Qwen/Qwen-Image-2.1", "revision": "d26bb61231c349cf6b7896fa83353113880e1ba3",
     "allow_patterns": QWEN21_PATTERNS, "bytes": 33131601593, "quant": "bf16",
     "mflux_class": QWEN21_CLASS, "mflux_config": "qwen_image_21",
     "steps": 40, "guidance": 1.0, "scheduler": "linear", "multiple": 32, "builtin_lora": None,
     "memory_gib": 56.0, "license": QWEN_RESEARCH, "setup": True},
    {"id": "qwen2511-q4", "label": "Qwen-Image-Edit-2511 q4 (Lightning)", "family": "qwen2511", "backend": "mflux",
     "repo": "mflux-community/qwen-image-edit-2511-mflux-q4", "revision": "3c74aab7dd79e6a8148c329cbca78c00c049ec3b",
     "allow_patterns": None, "bytes": 28958989673, "quant": "q4",
     "mflux_class": QWEN2511_CLASS, "mflux_config": "qwen_image_edit_2511",
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": LIGHTNING,
     "memory_gib": 32.0, "license": "Apache-2.0", "setup": True},
    {"id": "qwen2511-bf16", "label": "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", "family": "qwen2511",
     "backend": "diffusers", "repo": "Qwen/Qwen-Image-Edit-2511", "revision": None,
     "allow_patterns": None, "bytes": None, "quant": "bf16", "mflux_class": None, "mflux_config": None,
     "steps": 8, "guidance": 1.0, "scheduler": None, "multiple": 16, "builtin_lora": dict(LIGHTNING, revision=None),
     "memory_gib": 64.0, "license": "Apache-2.0", "setup": False},
)
QWEN_LORAS = (
    {"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21",
     "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized", "revision": "7959e658915f52274897fb573ffeda49de8dc16b",
     "file": "qwen-image-2.1-uncensored-lora.safetensors", "bytes": 33586704,
     "default_on": True, "default_scale": 1.0, "steps": None, "scheduler": None, "license": QWEN_RESEARCH},
    {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21",
     "repo": "Viggle/Qwen-Image-2.1-viggle-turbo", "revision": "009a44a895ef85f7e643c80fdca9543795248867",
     "file": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors", "bytes": 679604800,
     "default_on": False, "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": QWEN_RESEARCH},
)
QWEN_MODEL_IDS = tuple(m["id"] for m in QWEN_MODELS)
QWEN_LORA_IDS = tuple(l["id"] for l in QWEN_LORAS)
DEFAULT_QWEN_MODEL = "qwen21-q4"
LEGACY_QWEN_MODEL = "qwen2511-q4"
SCALE_MAX = 2.0
LORAS_MSG = "loras must be a list of {id, scale}"
```

- **SQ4. Field meanings.** `backend`: `mflux` runs `seed_edit_mflux_child.py`; `diffusers` runs the unchanged `character_dataset.py qwenedit` child. `revision`: the HF commit setup downloads and the tool looks up (`<hub>/<repo dir>/snapshots/<revision>`); `None` only for `qwen2511-bf16`, whose pinned child loads by `refs/main` (Section 14 item 4). `allow_patterns`: `None` = the whole repo. `bytes`: what setup fetches (§0.1), used by the disk floor. `multiple`: the canvas multiple (SQ14). `memory_gib`: the available-memory floor at run time and the total-memory floor in the probe (SQ17, SQ21). `builtin_lora`: a fixed LoRA the entry always loads at `scale` (not selectable, not listed in `loras`). `setup`: whether `bin/seed-edit-setup` can install it. `guidance` and `quant` are **informational** (amended by §14a): no code path reads them; the tool always sends `MFLUX_GUIDANCE` (1.0, SQ23) and the quantisation is a property of the repo, so editing either value changes nothing at run time.
- **SQ5. Lookups.** `qwen_model(model_id)` → the `QWEN_MODELS` dict whose `id` equals it, else `None`; `qwen_lora(lora_id)` likewise over `QWEN_LORAS`. `registry_order(loras)` returns the given `[{"id", "scale"}]` list sorted by the index of each `id` in `QWEN_LORA_IDS` (a stable order for argv, run.json and the child, whatever order the request used; LoRA deltas are additive, so order never changes the result).
- **SQ6.** `default_loras(model_id)` → `[{"id": l["id"], "scale": l["default_scale"]} for l in QWEN_LORAS if l["default_on"] and l["family"] == qwen_model(model_id)["family"]]` → `[{"id": "uncensored", "scale": 1.0}]` for the `qwen21` models and `[]` for the `qwen2511` ones.
- **SQ7.** `qwen_settings(model_id, loras)` (pure) → exactly `{"qwen_model", "loras", "steps", "scheduler"}`:
  - `model_id is None` (Z-Image) → `{"qwen_model": None, "loras": [], "steps": None, "scheduler": None}`.
  - else, with `m = qwen_model(model_id)` and `ls = registry_order(loras)`: `qwen_model = {"id": m["id"], "repo": m["repo"]}`; `loras = [{"id", "repo", "file", "scale": float(scale)}]` from each `qwen_lora`; `steps, scheduler` = the `steps`/`scheduler` of the first LoRA in `ls` whose `steps` is not `None`, else `m["steps"]`, `m["scheduler"]`. So `qwen21-*` + `viggle-turbo` → `6`, `"viggle_turbo"`; `qwen21-*` otherwise → `40`, `"linear"`; `qwen2511-*` → `8`, `None`.
- **SQ8. Legacy runs.** `record_settings(record)` (pure) → the same four keys for a `run.json` dict: when `record.get("qwen_model")` is a dict, the record's own values (`loras` replaced by `[]` when it is not a list; `steps`/`scheduler` as stored, missing → `None`); else when `record.get("model") == "qwen"` (a run made before this feature) → `qwen_settings("qwen2511-bf16" if record.get("backend") == "diffusers-bf16" else LEGACY_QWEN_MODEL, [])`; else the Z-Image value of SQ7. **[spec choice]** The notes say old runs show as 2511 q4; an old run that actually ran diffusers bf16 shows as `qwen2511-bf16`, because its `backend` says so.
- **SQ9.** `canvas_multiple(model, model_id)` → `qwen_model(model_id)["multiple"]` when `model == "qwen"`, else `16`.
- **SQ10.** `registry_view()` (pure) → the page's copy of the registry:
  `{"default_model": DEFAULT_QWEN_MODEL, "families": QWEN_FAMILIES, "models": [{"id", "label", "family", "backend", "steps", "scheduler", "multiple", "memory_gib", "license", "setup"}], "loras": [{"id", "label", "family", "default_on", "default_scale", "steps", "scheduler", "license", "setup"}]}`, both lists in registry order, every value copied from the entry except `setup`, which is the text `"bin/seed-edit-setup --model <id>"` / `"bin/seed-edit-setup --lora <id>"` (or `None` for a model with `setup: False`).
- **SQ11. Licences.** The Qwen Research License entries are non-commercial; the user accepted them (design notes). The registry `license` text is shown next to each LoRA (SQ51) and printed by setup before a download (SQ45). No code path checks a licence.

---

## 3. `bin/seed-edit` (SQ12-SQ27)

### 3.1 Command line (amends SG4)

```
bin/seed-edit --source PATH --prompt TEXT --model zimage|qwen [--qwen-model ID] [--lora ID=SCALE ...]
              [--strength S] [--candidates N] [--seed N] --run-dir DIR
bin/seed-edit --probe
```

- **SQ12.** `parse` adds `--qwen-model` (`type=str`) and `--lora` (`type=str`, `action="append"`). `check_args` rules, in this order (each failure exit 2, `Error: <text>`, nothing created), with the new rows marked:
  | # | Rule | Text |
  |---|---|---|
  | 1 | `--probe` with any other option (including `--qwen-model`, `--lora`) | `--probe takes no other options` |
  | 2-8 | SG4 rows 2-8 unchanged (required options, model, prompt empty/long, candidates, strength with qwen, zimage strength) | SG4 texts |
  | 9 new | `--qwen-model` given with `zimage` | `--qwen-model is only for --model qwen` |
  | 10 new | `--lora` given with `zimage` | `--lora is only for --model qwen` |
  | 11 new | `--qwen-model` not in `seedgen.QWEN_MODEL_IDS` | `--qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16` |
  | 12 new | a `--lora` value not matching `^([a-z0-9-]+)=(.*)$` | `--lora must be ID=SCALE (got <value>)` |
  | 13 new | its ID not in `QWEN_LORA_IDS` | `--lora: unknown LoRA <id>; known: uncensored, viggle-turbo` |
  | 14 new | its ID given twice | `--lora <id> is given twice` |
  | 15 new | its family differs from the model's | `--lora <id> is for <QWEN_FAMILIES[lora family]>, not <model label>` |
  | 16 new | `float(scale)` raises `ValueError`, or not `0 < s <= 2.0` | `--lora <id> scale must be a number above 0 and at most 2` |
  | 17 | SG4's seed row | SG4 text |
  Rows 12-16 run for each `--lora` value in the order given (`args.lora` is `None` when absent; row 1 counts it as given when it is not `None`). `--model qwen` without `--qwen-model` uses `LEGACY_QWEN_MODEL` (`qwen2511-q4`) with no LoRA. **[spec choice]** A job queued before this feature has no `--qwen-model` in its argv and then runs the q4 path it would have run on this host; the server always passes `--qwen-model` (SQ30). The cleaned options gain `"qwen_model"` (ID or `None` for zimage) and `"loras"` (`[{"id", "scale": float}]` in registry order through `seedgen.registry_order`, SQ5; `[]` for zimage). With `--model qwen`, the LoRA set is exactly the `--lora` options; the tool applies no default LoRA.
- **SQ13. Labels.** `ctx["label"]` is `"Z-Image"` for zimage, else the registry `label` of the selected model. It replaces `BACKEND_LABELS[backend]` in `run`'s exception text (`:733`), and `run_bf16`/`run_mflux` pass `ctx["label"]` to `run_qwen_child` instead of the literals `"diffusers bf16"` (`:670`) and `"mflux q4"` (`:705`), so every SG17 text carries it: for example `Qwen-Image-2.1 q4 child exited 1: boom`, `Qwen-Image-Edit-2511 q4 (Lightning) child timed out after 3600 s`, `Qwen-Image-2.1 q8 failed on candidate 2: RuntimeError: x`.

### 3.2 Canvas (amends SG8)

- **SQ14.** `canvas(w0, h0, multiple=MULTIPLE)`: SG8's integers with `multiple` in place of 16: `W, H = w // multiple * multiple, h // multiple * multiple`; the 64 px minimum and its refusal text are unchanged. `prepare_source` calls it with `seedgen.canvas_multiple(opts["model"], opts["qwen_model"])`. Examples with 32 (SQT1): 1536×1024 → 1024×672; 1024×1024 → 1024×1024; 800×600 → 800×576; 4000×3000 → 1024×768; 3000×4000 → 768×1024; 720×1280 → 576×1024; 1023×1023 → 992×992; 100×70 → 96×64; 90×90 → 64×64; 100×60 → refused (`--source is too small: 100x60 gives a 96x32 canvas; each side must be at least 64 px`). With 16 every SG8 example is unchanged. **[spec choice]** mflux 2.1 refuses any side that is not a multiple of 32 (§0.2); flooring keeps the "never upscale" rule.

### 3.3 Registry lookups (replace SG14's mflux checks)

- **SQ15.** New module functions, typed exactly (each is copied byte-for-byte into `bin/seed-edit-setup`, SQ42):

```python
def pinned_snapshot(repo, revision, hubs):
    """(snapshot, repo_dir) of the first hub holding <repo dir>/snapshots/<revision> as a directory,
    else (None, None)."""
    for hub in hubs:
        repo_dir = os.path.join(hub, lib.repo_dir_name(repo))
        snapshot = os.path.join(repo_dir, "snapshots", revision)
        if os.path.isdir(snapshot):
            return snapshot, repo_dir
    return None, None


def pinned_file(repo, revision, name, hubs):
    """<hub>/<repo dir>/snapshots/<revision>/<name> in the first hub where its realpath is a non-empty
    regular file (the snapshot path is returned, not the realpath), else None."""
    for hub in hubs:
        path = os.path.join(hub, lib.repo_dir_name(repo), "snapshots", revision, name)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def weights_problem(entry, hubs):
    """(problem, model dir, built-in LoRA path) of an mflux registry model in hubs. problem is None
    when the pinned snapshot is intact (for qwen21 also with its component configs and processor/)
    and the built-in LoRA, if any, is present."""
    where = " or ".join(hubs)
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    snapshot, repo_dir = pinned_snapshot(entry["repo"], entry["revision"], hubs)
    if snapshot is None:
        return "%s@%s is not in %s %s" % (entry["repo"], entry["revision"][:12], where, setup), None, None
    problems = list(lib.intact_scan(snapshot, repo_dir)[0])
    if entry["family"] == "qwen21":
        problems += ["missing %s" % rel for rel in seedgen.QWEN21_REQUIRED
                     if not os.path.isfile(os.path.join(snapshot, rel))]
        if not os.path.isdir(os.path.join(snapshot, "processor")):
            problems.append("missing processor/")
    if problems:
        return "%s: %s %s" % (entry["repo"], "; ".join(problems), setup), None, None
    lora = entry["builtin_lora"]
    lora_path = None
    if lora is not None:
        lora_path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
        if lora_path is None:
            return "Lightning LoRA %s is not in %s %s" % (lora["file"], where, setup), None, None
    return None, snapshot, lora_path
```

- **SQ16.** Further module functions:
  - `qwen_hubs()` → `[lib.zimage_hub(), default_hub()]` (SG14's hub order, unchanged).
  - `mflux_env_problem()` → SG14 `mflux_problem` steps 1-2 unchanged except the gate: below `MFLUX_MIN_VERSION = (0, 24, 0)` → `mflux <version text> in <venv> is older than 0.24.0 (run bin/seed-edit-setup)`; else `None`.
  - `lora_problem(lora, hubs)` → `(None, path)` when `pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)` finds it, else `("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]), None)`.
  - `qwen_model_problem(entry)` → `(problem, paths)`: backend `diffusers` → `(bf16_problem(), {})` (SG14's function, unchanged, default hub and `refs/main`); backend `mflux` → the first non-`None` of `mflux_env_problem()`, `weights_problem(entry, qwen_hubs())[0]`, `modules_problem(["PIL", "psutil", "torch", "transformers"])` (the parent's screening deps), with `paths = {"model_path": <snapshot>, "builtin_lora": <path or None>}` when all pass, else `{}`.
  - `memory_problem(entry)` → `None`, or `"cannot read this host's memory size"` when `total_gib()` is `None`, or `"needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (entry["memory_gib"], t)` when `t < entry["memory_gib"]`.
- **SQ17.** Removed from `bin/seed-edit`: `choose_qwen`, `mflux_problem`, the `SEED_EDIT_QWEN_Q4_DIR` and `SEED_EDIT_LIGHTNING_FILE` handling, and the constants `BF16_MIN_AVAIL_GIB`, `MFLUX_MIN_AVAIL_GIB`, `Q4_REPO`, `Q4_NAME_PART`. `find_lightning` and `bf16_problem` stay (used only by `qwen2511-bf16`). `BACKEND_LABELS` becomes `{"zimage": "Z-Image", "mflux": "mflux", "diffusers": "diffusers"}`. `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG` stay (SG19's spec and SGT14's mirror).

### 3.4 Probe (replaces SG15's shape)

- **SQ18.** `--probe` prints one line, `json.dumps(probe(), sort_keys=True)`, exits 0 whatever it finds, imports nothing beyond SQ1/SG2's top-level modules, loads no model, starts no process. Example on a 48 GiB host (paths and two reasons abbreviated; `<zhub>`/`<dhub>` are the two hub paths):

```json
{"zimage": {"ok": true, "reason": null, "backend": "zimage"},
 "qwen": {"ok": true, "reason": null,
          "models": {"qwen21-q4": {"ok": true, "reason": null},
                     "qwen21-q8": {"ok": false, "reason": "mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in <zhub> or <dhub> (run bin/seed-edit-setup --model qwen21-q8)"},
                     "qwen21-bf16": {"ok": false, "reason": "needs a host with at least 56 GiB of memory (this host has 48.0 GiB)"},
                     "qwen2511-q4": {"ok": false, "reason": "…"}, "qwen2511-bf16": {"ok": false, "reason": "…"}},
          "loras": {"uncensored": {"ok": true, "reason": null},
                    "viggle-turbo": {"ok": false, "reason": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in <zhub> or <dhub> (run bin/seed-edit-setup --lora viggle-turbo)"}}}}
```
  `zimage` is SG15's unchanged. Each model: `reason = memory_problem(entry) or qwen_model_problem(entry)[0]` (memory first: there is no point installing what cannot run here), `ok = reason is None`. Each LoRA: `reason = lora_problem(lora, qwen_hubs())[0]`. `qwen.ok = any(model ok)`; `qwen.reason = None` when ok, else `"; ".join("%s: %s" % (id, reason))` over the models in registry order. The `qwen` value has no `backend` key. **[spec choice]** As in SG15, the probe judges memory by the host's total memory (the VLM is up while it runs); the job judges by available memory (SQ21).

### 3.5 run.json (amends SG11, SG12)

- **SQ19.** `new_record` adds four keys after `"seed"`: `**seedgen.qwen_settings(opts["qwen_model"], opts["loras"])` (SQ7). `backend` becomes `"zimage"`, `"mflux"` or `"diffusers"` (the registry `backend`) once chosen; it is still `null` until SG12 step 5. The schema name stays `seed-edit.run.v1` (the change only adds keys). Example of a finished run:
  ```json
  {"schema": "seed-edit.run.v1", "run": "se-20261102-141500-a1b2", "created": "…", "state": "done",
   "prompt": "…", "model": "qwen", "backend": "mflux", "strength": null, "seed": 7,
   "qwen_model": {"id": "qwen21-q4", "repo": "mflux-community/qwen-image-2-1-mflux-q4"},
   "loras": [{"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
              "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 1.0}],
   "steps": 40, "scheduler": "linear", "size": {"width": 1024, "height": 672}, …}
  ```
  For zimage: `qwen_model: null, loras: [], steps: null, scheduler: null`.
- **SQ20.** SG7's backend line becomes `seed-edit: backend <backend> (<why>)` with `why` = `Z-Image img2img` for zimage, else `"<label>; LoRAs <list>; <steps> steps; scheduler <scheduler or default>"`, where `<list>` is `", ".join("%s@%g" % (id, scale))` or `none`. Example: `seed-edit: backend mflux (Qwen-Image-2.1 q4; LoRAs uncensored@1; 40 steps; scheduler linear)`.

### 3.6 Preflight (replaces SG13 steps 3-4 for qwen)

- **SQ21.** For `--model qwen`, after SG13's disk and busy steps, in order (each failure an exit-2 refusal written per SG12 step 4):
  1. `entry = seedgen.qwen_model(opts["qwen_model"])`; `problem, paths = qwen_model_problem(entry)`; problem → `<label> is unavailable: <problem>`.
  2. For each selected LoRA in registry order: `problem, path = lora_problem(lora, qwen_hubs())`; problem → `LoRA <lora label> is unavailable: <problem>`.
  3. `wait_for_memory(entry["memory_gib"], entry["label"])` (SG13 step 4's loop and text, now for every Qwen model including `qwen2511-bf16`): e.g. `only 40.0 GiB available after waiting 600 s; Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) needs 64 GiB; free memory and retry`.
  `preflight` returns `(entry["backend"], why)` and stores `ctx["paths"] = paths`, `ctx["lora_paths"]` (the paths of step 2, registry order), `ctx["label"]`, `ctx["entry"]`. Z-Image's branch is unchanged. **[spec choice]** The 2511 bf16 entry is no longer chosen "at ≥ 64 GiB available" but waits like the others, because it is now an explicit choice.

### 3.7 Backends (amend SG19, SG20)

- **SQ22.** `run` dispatches on `backend`: `{"zimage": run_zimage, "diffusers": run_bf16, "mflux": run_mflux}`. `run_zimage` and `run_bf16` are unchanged (the bf16 spec is SG19's dict, byte-identical; its child screens every image with skill `seed_edit` and never saves a blocked one).
- **SQ23.** `run_mflux` writes `<run>/work/mflux_spec.json`:
  ```json
  {"family": "qwen21", "model_path": "<pinned snapshot>",
   "lora_paths": ["<LoRA snapshot path>", …], "lora_scales": [1.0, …],
   "prompt": "<prompt>", "source": "<run>/work/source.png", "width": W, "height": H,
   "steps": 40, "guidance": 1.0, "scheduler": "linear",
   "jobs": [{"n": 1, "seed": <base+1>, "output_path": "<run>/work/cand_01.pending.png"}, …]}
  ```
  `family`, `steps`, `scheduler` from SQ7/registry; `guidance` is `MFLUX_GUIDANCE` (1.0) for every entry. `lora_paths`/`lora_scales`: for `qwen2511-q4`, `[<Lightning snapshot path>]`/`[1.0]`; for `qwen21-*`, the selected LoRAs' snapshot paths and their scales in registry order (`[]`/`[]` when none). Argv, env (`HF_HUB_OFFLINE="1"`, `PYTHONUNBUFFERED="1"`), the done-line regex and the per-candidate handling are SG20's, unchanged: the parent opens each pending file and calls `content_safety.assert_image_safe(img.convert("RGB"), skill="seed_edit", prompt=prompt)` before `os.replace` to `cand_NN.png`; `ContentSafetyError` deletes the pending file and marks `blocked`.
- **SQ24. Content safety on every candidate.** For every registry model, with or without LoRAs, every candidate passes `content_safety.assert_image_safe` before it gets its final name: in the parent for every `mflux` entry (SQ23), in the unchanged child with skill `seed_edit` for `qwen2511-bf16` (SG19), inside `z_image_skill.generate_variation` for Z-Image (SG18). No registry field, request field, environment variable or LoRA turns it off. `/files` keeps refusing `work/` (SG §14a item 5). SQT6 pins it per entry.
- **SQ25.** SG26 holds per LoRA: every `lora_paths` element is a local file path inside a pinned snapshot, never a repo ID; `model_path` is a local directory; `bake_lora` is always False; `HF_HUB_OFFLINE=1` stays.

### 3.8 Environment and docstring (amends SG23)

- **SQ26.** The only environment variables `bin/seed-edit` reads: `SEED_EDIT_MFLUX_PYTHON`, `SEED_EDIT_QWENEDIT_SCRIPT`, `HF_HUB_CACHE`, `HF_HOME`, `Z_IMAGE_HF_HOME`, `HOME`. The module docstring is rewritten to name the new options, the registry IDs, the probe shape (SQ18), the exit codes (unchanged) and the run.json write order (unchanged), and drops the auto-by-memory text (`:12-16`).
- **SQ27.** Top-level imports of `bin/seed-edit` become the SGT34 list plus `movie_ui_seedgen` directly after `movie_ui_lib`.

---

## 4. `seed_edit_mflux_child.py` (replaces SG25's body; SQ28-SQ29)

- **SQ28.** Top-level imports stay exactly SG24's list. `MIN_VERSION = (0, 24, 0)`. The body (load-bearing; typed as written; `parse_version` and `exit_with_parent` unchanged):

```python
MIN_VERSION = (0, 24, 0)
FAMILIES = {
    "qwen21": ("mflux.models.qwen21.variants.edit.qwen_image_21_edit", "QwenImage21Edit", "qwen_image_21"),
    "qwen2511": ("mflux.models.qwen.variants.edit.qwen_image_edit", "QwenImageEdit", "qwen_image_edit_2511"),
}


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
        print("seed-edit-child: mflux %s is missing or older than 0.24.0; refusing (run bin/seed-edit-setup)"
              % version, flush=True)
        return 2
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    family = spec.get("family")
    if family not in FAMILIES:
        print("seed-edit-child: unknown model family %r; refusing" % (family,), flush=True)
        return 2
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    module_name, class_name, config_name = FAMILIES[family]
    model_class = getattr(importlib.import_module(module_name), class_name)
    config = getattr(ModelConfig, config_name)()
    loras = [[os.path.basename(p), s] for p, s in zip(spec["lora_paths"], spec["lora_scales"])]
    print("seed-edit-child: mflux %s, family %s, model %s, transformer overrides %s, scheduler %s, LoRAs %s"
          % (version, family, config.model_name, getattr(config, "transformer_overrides", None),
             spec["scheduler"], json.dumps(loras)), flush=True)
    model = model_class(model_path=spec["model_path"], quantize=None, model_config=config,
                        lora_paths=spec["lora_paths"] or None, lora_scales=spec["lora_scales"] or None,
                        bake_lora=False)
    peak = getattr(mx, "get_peak_memory", None) or mx.metal.get_peak_memory
    for job in spec["jobs"]:
        started = time.monotonic()
        kwargs = {"seed": job["seed"], "prompt": spec["prompt"], "image_paths": [spec["source"]],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
        if family == "qwen21":
            kwargs["scheduler"] = spec["scheduler"]
        else:
            kwargs["negative_prompt"] = " "
        result = model.generate_image(**kwargs)
        result.image.convert("RGB").save(job["output_path"])
        seconds = time.monotonic() - started
        print("seed-edit-child: mlx peak memory %.2f GiB" % (peak() / 2 ** 30), flush=True)
        print("seed-edit-child done %d %.1f" % (job["n"], seconds), flush=True)
    return 0
```
  `importlib.import_module` is reachable because `import importlib.metadata` binds `importlib`. The 2511 call keeps today's arguments (`negative_prompt=" "`, no `scheduler`), so `qwen2511-q4` behaves as the SG q4 backend did. The 2.1 call passes no negative prompt (guidance 1.0 runs no negative pass; the Viggle card says no negative prompt). `.convert("RGB")` turns mflux 2.1's RGBA output into the RGB PNG every other path saves.
- **SQ29.** Exit codes: 0 all jobs saved; 2 the version refusal (before the spec is read) or an unknown family (before mlx or mflux is imported); 3 the parent died; anything else a crash. The docstring is rewritten to match (two families, LoRA lists, 0.24.0).

---

## 5. Library and server (SQ30-SQ40)

### 5.1 Request rules (`movie_ui_seedgen.validate_run_request`, amends SG33)

- **SQ30.** New rows between SG33 rows 9 and 10 (first failure only; values inserted with `%s` as sent):
  | # | Rule | `error` |
  |---|---|---|
  | 9a | model `zimage` and `qwen_model` present and not null | `qwen_model is only for qwen` |
  | 9b | model `zimage` and `loras` present and not null | `loras is only for qwen` |
  | 9c | model `qwen`, `qwen_model` not null and not a str in `QWEN_MODEL_IDS` | `unknown qwen_model <value>` |
  | 9d | model `qwen`, `loras` not null and not a list | `loras must be a list of {id, scale}` |
  | 9e | an item that is not a dict whose key set is exactly `{"id", "scale"}` | `loras must be a list of {id, scale}` |
  | 9f | its `id` not a str in `QWEN_LORA_IDS` | `unknown LoRA <id>` |
  | 9g | its `id` already seen in this list | `LoRA <id> is listed twice` |
  | 9h | its family differs from the model's | `LoRA <id> is for <QWEN_FAMILIES[lora family]>, not <model label>` |
  | 9i | its `scale` not `lib._is_number` or not `0 < scale <= 2.0` | `LoRA <id> scale must be a number above 0 and at most 2` |
  Rows 9e-9i run item by item in list order. For 9h the model is the cleaned one (`qwen_model` null/absent → `DEFAULT_QWEN_MODEL`). `clean` gains `"qwen_model"` (`None` for zimage; null/absent → `"qwen21-q4"`) and `"loras"` (`[]` for zimage; null/absent → `default_loras(qwen_model)`; else the items as `{"id", "scale": float}` in registry order). An explicit `[]` stays `[]` (no LoRA).
- **SQ31.** `availability_error(models, detail, clean)` (signature change; the server passes `clean`): models `None` → `cannot check the seed models: <detail>`; zimage not ok → `Z-Image is unavailable: <reason>` (SG37); qwen: the selected model's `models["qwen"]["models"][id]` not ok → `<model label> is unavailable: <reason>`; then each selected LoRA (registry order) whose entry is not ok → `LoRA <lora label> is unavailable: <reason>`; else `None`. The aggregate `qwen.ok` is not consulted for qwen (the selected model's own entry is more precise).
- **SQ32.** `capability(models, detail, checked)` adds `"registry": registry_view()` to both branches; `reason` keeps SG36's formula with the new `MODELS` labels (`Z-Image: …; Qwen-Image: …`).

### 5.2 Capability (amends SG38)

- **SQ33.** The server's initial `seed_edit` capability is `{"ok": None, "reason": "probing", "checked": None, "models": None, "registry": seedgen.registry_view()}`. `refresh_capabilities` calls `lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)`.

### 5.3 `movie_ui_lib.py` (amends SG29, SG30)

- **SQ34.** `seed_edit_argv`: for `fields["model"] == "qwen"`, directly after `"--model", "qwen"`: `"--qwen-model", fields["qwen_model"]`, then for each `l` in `fields["loras"]` (already in registry order): `"--lora", "%s=%r" % (l["id"], float(l["scale"]))`. Example: `[…, "--model", "qwen", "--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0", "--lora", "viggle-turbo=0.5", "--candidates", "4", …]`. Zimage argv unchanged. Fields without `qwen_model` (a job made before this feature) produce SG29's argv unchanged.
- **SQ35.** `seed_edit_check(ws_real, model_ids, lora_ids)`: SG30's process, timeout and exit-code handling unchanged. Parsing: `zimage` through `_probe_model` (unchanged, three keys); `qwen` through new `_probe_qwen(value, model_ids, lora_ids)`, which requires a dict with a bool `ok`, a str-or-None `reason`, and `models`/`loras` dicts whose key sets equal `set(model_ids)`/`set(lora_ids)`, each value a dict with a bool `ok` and a str-or-None `reason`; it returns `{"ok", "reason", "models": {id: {"ok", "reason"}}, "loras": {id: {"ok", "reason"}}}` holding exactly those keys (extra keys dropped). Any failure → `(None, "bin/seed-edit --probe printed unparsable output")`.

### 5.4 Server (amends SG43, SG44, SG47)

- **SQ36.** `_h_seed_run_create`: step 3 calls `lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)` and `seedgen.availability_error(models, detail, clean)`. Step 7's record gains, after `"seed"`, the four `seedgen.qwen_settings(clean["qwen_model"], clean["loras"])` keys; `fields` gains `"qwen_model": clean["qwen_model"]` and `"loras": clean["loras"]` (after `"strength"`).
- **SQ37.** `run_view` adds `qwen_model`, `loras`, `steps`, `scheduler` from `seedgen.record_settings(record)` (after `backend`). The view's key set becomes SG43's plus these four.
- **SQ38.** `_h_seed_runs` items add `"qwen_model"` and `"loras"` from `seedgen.record_settings(record)` (item keys: `run, created, state, prompt, model, backend, qwen_model, loras, count, ok, thumbs`).
- **SQ39.** 400 and 409 leave no run directory and no job (SG45 unchanged). The 400 table is SG45's plus SQ30's rows; the 409 table is SG45's with SG37's Qwen text replaced by SQ31's two texts.
- **SQ40.** `job_summary`, `ProgressParser`, the routes (63) and `/files` are unchanged.

---

## 6. `bin/seed-edit-setup` (replaces SG66-SG69; SQ41-SQ47)

- **SQ41. Command line.** `bin/seed-edit-setup [--model ID ...] [--lora ID ...]` (argparse, both `action="append"`, `type=str`). No option at all → models `["qwen21-q4"]`, LoRAs `["uncensored"]`. Otherwise the selection is exactly the options given (duplicates dropped, first order kept; `--lora` alone installs only the venv and those LoRAs). Refusals, exit 2, `Error: …` on stderr, checked in this order before anything else:
  | Rule | Text |
  |---|---|
  | `--model` value not in `QWEN_MODEL_IDS` | `unknown --model <id>; known: qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16` |
  | `--model qwen2511-bf16` | `qwen2511-bf16 is not installed by seed-edit-setup: it runs the diffusers weights of Qwen/Qwen-Image-Edit-2511 and lightx2v/Qwen-Image-Edit-2511-Lightning from the default Hugging Face cache (<default hub>)` |
  | `--lora` value not in `QWEN_LORA_IDS` | `unknown --lora <id>; known: uncensored, viggle-turbo` |
  | `SEED_EDIT_MFLUX_PYTHON` set | SG67 step 1's text (unchanged) |
- **SQ42. Copied functions.** The script carries byte-identical copies of `bin/seed-edit`'s `mflux_version`, `default_hub`, `pinned_snapshot`, `pinned_file` and `weights_problem` (SQT18 compares their code). It drops `find_lightning`, `Q4_REPO`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE` and `SETUP_MIN_FREE_GIB`. Constants: `VENV`, `MFLUX_SPEC = "mflux==0.24.0"`, `MFLUX_VERSION`, `DEFAULT_BASE_PYTHON` unchanged; `VENV_GIB = 3.0`; `HEADROOM_GIB = 1.0`.
- **SQ43. Items.** `hub = lib.zimage_hub()` (the download target, as SG66). The items of a selection, in order: for each model a **snapshot** item `{"kind": "snapshot", "name": <model id>, "repo", "revision", "allow_patterns", "bytes"}`; for `qwen2511-q4` also a **file** item for its built-in Lightning LoRA (`"name": "lightning"`, `"repo", "revision", "file", "bytes"` from `LIGHTNING`); for each LoRA a **file** item (`"name": <lora id>`). A snapshot item is **ok** when `weights_problem(dict(entry, builtin_lora=None), [hub])[0] is None` (the pinned snapshot is intact; for `qwen21` also with its component configs and `processor/`); a file item is **ok** when `pinned_file(repo, revision, file, [hub])` is not `None`. A LoRA repo is never a snapshot item; `snapshot_download` is never called with a LoRA repo (abenzerps 97.96 GiB, Viggle 97.67 GiB).
- **SQ44. Steps** (each failure `Error: …` on stderr):
  1. SQ41.
  2. `venv_ok` (SG67's rule: venv python executable and dist-info version exactly `0.24.0`); `needed` = the items that are not ok.
  3. `venv_ok` and no `needed` → print `seed-edit-setup: nothing to do`, then step 9, exit 0.
  4. **Disk floor.** `total = Σ item["bytes"] / 2**30 over needed + (VENV_GIB if not venv_ok else 0) + HEADROOM_GIB`; `present = Σ tree_gib(<hub>/<repo dir>)` over the distinct repo dirs of `needed` that exist `+ (tree_gib(venv) if not venv_ok and isdir(venv) else 0)`; `need = max(total - present, 0.0)`; `free, where` = the smaller of `free_gib` on `existing_ancestor(hub)` and `existing_ancestor(dirname(venv))` (unchanged). `free < need` → exit 2 `only <free:.1f> GiB free on <where>; seed-edit-setup needs at least <need:.1f> GiB more (<total:.1f> GiB in all, <present:.1f> GiB already present; <parts>)` with `<parts>` = `", ".join("%s ~%.2f GiB" % (name, bytes / 2**30))` over `needed`, plus `", mflux venv ~3 GiB"` when the venv is not ok, plus `", 1 GiB headroom"`. Example, the default selection on an empty host: total 9.91 + 0.03 + 3 + 1 = 13.94 GiB. The full macstudio set (§10 M0): 9.91 + 17.19 + 30.86 + 26.97 + 0.79 + 0.03 + 0.63 + 3 + 1 = 90.38 GiB. Re-running after a partial download subtracts what is present, so it resumes (SG68 kept).
  5. Base python checks (SG67 step 5, unchanged).
  6. Venv creation (SG67 step 6, unchanged); 7. pip install `mflux==0.24.0` when the version is not `0.24.0` (SG67 step 7, unchanged).
  8. `needed` non-empty → print, for each needed item, `seed-edit-setup: license: <name>: <license>` (model or LoRA registry `license`; `Apache-2.0` for `lightning`), then run `[<venv python>, "-c", DOWNLOAD, hub, json.dumps(items)]` where `items` is `[{"kind", "repo", "revision", "allow_patterns"}]` for snapshot items and `[{"kind", "repo", "revision", "file"}]` for file items (needed only, item order), with SG67/§14a's env unchanged (`HF_HOME=dirname(hub)`, `HF_HUB_OFFLINE="0"`, `HF_XET_CHUNK_CACHE_SIZE_BYTES="0"`, `HF_HUB_ENABLE_HF_TRANSFER="0"`); non-zero → exit 1 `the download exited <rc>`. `DOWNLOAD` is exactly:
     ```python
     import json
     import sys
     from huggingface_hub import hf_hub_download, snapshot_download
     hub, items = sys.argv[1], json.loads(sys.argv[2])
     for item in items:
         if item["kind"] == "snapshot":
             print(snapshot_download(repo_id=item["repo"], revision=item["revision"],
                                     allow_patterns=item["allow_patterns"], cache_dir=hub), flush=True)
         else:
             print(hf_hub_download(repo_id=item["repo"], filename=item["file"], revision=item["revision"],
                                   cache_dir=hub), flush=True)
     ```
     A commit-hash `revision` makes huggingface_hub write `snapshots/<revision>/`, which is where SQ15 looks.
  9. Report: `seed-edit-setup: venv <path>: <x.xx> GiB`; per selected model `seed-edit-setup: model <id> <snapshot>: <x.xx> GiB` (SG67's realpath-once sum) or `seed-edit-setup: model <id>: <weights_problem text>`; per file item `seed-edit-setup: LoRA <name> <path>: <x.xx> GiB` or `seed-edit-setup: LoRA <name> (<file>) is not in <hub>`; `seed-edit-setup: free on <ancestor>: <x.x> GiB`; then `[sys.executable, <WS>/bin/seed-edit, "--probe"]` and, per selected model and LoRA, `seed-edit-setup: probe: <id> ok` or `seed-edit-setup: probe: <id> unavailable: <reason>` (from `qwen.models[id]` / `qwen.loras[id]`; an unparsable answer prints `seed-edit-setup: probe: unavailable: bin/seed-edit --probe printed unparsable output` once). Informational; exit 0.
- **SQ45.** Exit codes unchanged (0 / 1 / 2; §14a item C adds a case of 1). Idempotent: a second run after success prints `nothing to do` and the report. No token is read or sent (amended by §14a item B): the download child's environment is `seedgen.hf_child_env(os.environ, HF_HOME=…, HF_HUB_OFFLINE="0", HF_XET_CHUNK_CACHE_SIZE_BYTES="0", HF_HUB_ENABLE_HF_TRANSFER="0")`, which has no `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` key and sets `HF_HUB_DISABLE_IMPLICIT_TOKEN="1"`, so huggingface_hub sends neither an environment token nor a stored one. The rule is pinned on the environment the `subprocess.call` recorder receives, with dummy token values set in `os.environ` (`test_sq_final_b_no_token_reaches_the_download`); the earlier source-grep form ("`HF_TOKEN` appears nowhere in the file") is withdrawn.
- **SQ46.** The docstring is rewritten: options, default selection, items, the floor formula, resume, licences, "never snapshots a LoRA repo", exit codes.
- **SQ47.** Existing installs: a 2511 q4 snapshot downloaded by the old setup sits under whatever `main` was then. If that commit is not `3c74aab7…`, the probe says `…@3c74aab7dd79 is not in …` and `bin/seed-edit-setup --model qwen2511-q4` re-links it at the pinned commit (huggingface_hub reuses identical blobs). This Mac has no `~/mflux-edit` (facts file); macstudio's state is unknown to the agent, so this is a note for the user, not a migration.

---

## 7. The page (amends SG55-SG63; SQ48-SQ56)

- **SQ48. HTML.** In `#se-model`, the second option's text becomes `Qwen-Image (edit)` (value `qwen` unchanged). Directly after `<span id="se-model-note" class="muted"></span>` insert exactly:
  ```html
      <div id="se-qwen-box" class="wide" hidden>
        <label>Qwen model <select id="se-qwen-model"></select></label>
        <span id="se-steps" class="muted"></span>
        <div id="se-loras" class="se-loras"></div>
        <p id="se-qwen-note" class="muted"></p>
      </div>
  ```
  `app.css` appends `.se-loras { display: flex; flex-direction: column; gap: 4px; }` and `.se-lora { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }`.
- **SQ49. Constants and state.** `SEED_MODEL_LABELS = {zimage: "Z-Image", qwen: "Qwen-Image"};` `SEED_BACKEND_LABELS = {"zimage": "Z-Image img2img", "mflux": "mflux", "diffusers": "diffusers", "mflux-q4": "mflux q4", "diffusers-bf16": "diffusers bf16"};` (the last two label old runs). `S.seeds` gains `qwen: null` and `qwenKey: ""`. `S.seeds.qwen` is `{model: <id>, loras: {<id>: {checked: bool, scale: <string>}}}`, created once, the first time `updateSeedButtons` sees `cap.registry`: `model = registry.default_model`, each LoRA `{checked: default_on, scale: String(default_scale)}`. `resetSeeds` and `editSeedAgain` never touch `S.seeds.qwen`, `#se-model` or `#se-qwen-model` (Edit again keeps the selection; a workspace switch keeps it too).
- **SQ50. New functions** (each defined exactly once, added to SG57's list): `seedRegistry()` → `capability("seed_edit").registry || null`; `seedQwenEntry(id)` → the registry model with that id or `null`; `seedLoraEntry(id)` likewise; `seedMultiple()` → with `entry = seedQwenEntry(S.seeds.qwen ? S.seeds.qwen.model : null)`: `entry.multiple` when `$("#se-model").value === "qwen"` and `entry` is not null, else `16`; `renderSeedQwen()`; `readSeedQwen()`; `seedLoraBody()`; `seedModelText(view)`. `seedCanvas(w, h)` becomes `seedCanvas(w, h, multiple)` (`Math.floor(a / multiple) * multiple`, same for b).
- **SQ51. `renderSeedQwen()`.** `updateSeedButtons` runs, before its gating: the SQ49 initialisation (when `S.seeds.qwen` is null and a registry exists), then `readSeedQwen()`, then `renderSeedQwen()`, which does:
  - With no registry: `#se-qwen-model` empty, `#se-steps` `checking models…`, nothing else.
  - `models = capability("seed_edit").models`; `probe(id)` = `models && models.qwen.models[id]` (may be `undefined` while probing); same for LoRAs.
  - Options: one `<option value="<id>">` per registry model in order, text `label` plus ` — unavailable` when `probe(id) && probe(id).ok === false`, `disabled` in that case. Selection: `S.seeds.qwen.model` when it is not disabled; else the default model when it is not disabled; else the first enabled option in order; else `S.seeds.qwen.model` unchanged. The chosen ID is written back to `S.seeds.qwen.model` and set as the select's value.
  - LoRA rows. `key = family + "|" + JSON.stringify(<for each LoRA of this family: [id, ok]>)`; only when `key !== S.seeds.qwenKey` is `#se-loras` rebuilt (so typing a strength is never interrupted) and `S.seeds.qwenKey = key`. Family `qwen2511`: one `el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"})`. Family `qwen21`: per LoRA of that family in registry order, `el("div", {cls: "se-lora", data: {lora: id}}, [el("label", {}, [checkbox, " " + label]), el("label", {}, ["strength ", scale]), note])` with `checkbox = el("input", {type: "checkbox", id: "se-lora-" + id})`, `checked = state.checked && ok`, `disabled = !ok`; `scale = el("input", {type: "number", id: "se-lora-scale-" + id, min: "0", max: "2", step: "0.05", value: state.scale})`, `disabled = !ok`; `note = el("span", {cls: "muted", id: "se-lora-note-" + id})` with text `"unavailable — " + reason` when not ok, else `license` plus (`steps` set) `"; " + steps + " steps, scheduler " + scheduler`. `ok` here is `probe(id) ? probe(id).ok === true : false`.
  - `#se-steps` (recomputed every call): with `m` the selected entry and `turbo` the first checked-and-enabled LoRA of the family with a `steps` value: `turbo ? turbo.steps + " steps (turbo)" : m.steps + " steps" + (m.family === "qwen2511" ? " (Lightning)" : "")`. So `40 steps`, `6 steps (turbo)`, `8 steps (Lightning)`.
  - `#se-qwen-note`: `"Unavailable here: " + parts.join("; ")` with one part `label + " — " + reason` per registry model whose probe entry is not ok; empty when none.
- **SQ52. `readSeedQwen()`** copies the DOM into state before rendering: `S.seeds.qwen.model = $("#se-qwen-model").value` when it is non-empty; for each `.se-lora` row its checkbox's `checked` (only when the checkbox is enabled; a disabled checkbox keeps the stored value) and its scale input's `value` into `S.seeds.qwen.loras[id]`.
- **SQ53. Gating** (`updateSeedButtons`, amends SG59):
  - `#se-qwen-box` is shown only when `#se-model` is `qwen`. The SG59 option disabling for `#se-model` stays (`qwen` is disabled when `models.qwen.ok === false`).
  - `#se-model-note`: `checking models…` / `cannot check the seed models: …` unchanged; else the parts joined by `"; "`: `Z-Image: unavailable — <reason>` when zimage is not ok, `Qwen-Image: unavailable — <reason>` when qwen is not ok. The `Qwen-Image-Edit backend: …` part is removed.
  - `#se-source-size` text is set here (no longer only in the load handler) whenever `natural` is set: `"<W0> × <H0> → <W> × <H>"` from `seedCanvas(w0, h0, seedMultiple())`; the too-small rule uses the same canvas. The load handler (`:2108-2115`) sets `natural` and calls `updateSeedButtons()`.
  - After SG59's `<model> unavailable` reason and before the strength reason, for `qwen`: `<label> unavailable: <reason or "probing">` when the selected model's probe entry is not `ok === true`; then, per checked-and-enabled LoRA in registry order, `LoRA <label> strength must be above 0 and at most 2` when `Number(scale)` is not finite or not `0 < s <= 2`.
- **SQ54. Body** (amends SG60): `seedBody()` adds `qwen_model: model === "qwen" ? S.seeds.qwen.model : null` and `loras: model === "qwen" ? seedLoraBody() : null`, where `seedLoraBody()` → `[{id, scale: Number(scale)}]` for each checked-and-enabled LoRA row in registry order (`[]` when none, so the server applies no default).
- **SQ55. Run title and Runs list** (amend SG61, SG63). `seedModelText(view)`: `zimage` → `Z-Image`; `qwen` → the registry label of `view.qwen_model.id` (the id itself when unknown; `Qwen-Image` when `qwen_model` is null) plus, when `view.loras` is non-empty, `" + " + view.loras.map(function (l) { return l.id + " " + l.scale; }).join(", ")`. `#se-run-title` = `view.run + " · " + seedModelText(view) + (view.steps ? " · " + view.steps + " steps" : "") + (view.backend ? " (" + (SEED_BACKEND_LABELS[view.backend] || view.backend) + ")" : "")`, e.g. `se-… · Qwen-Image-2.1 q4 + uncensored 1 · 40 steps (mflux)`. The Runs table's Model cell is `seedModelText(r)` (the list items carry `model`, `qwen_model`, `loras`, SQ38). An old run reads `se-… · Qwen-Image-Edit-2511 q4 (Lightning) · 8 steps (mflux q4)`.
- **SQ56.** Every node is built with `el()`/`button()`, server text goes in through `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `\bprompt\(`, …) and the pinned lines of SGT33 still hold.

---

## 8. Errors (additions to [SG] §8)

| Condition | Where | Text | Effect |
|---|---|---|---|
| unknown model / LoRA, wrong family, bad scale, Qwen fields with Z-Image | `POST /api/seeds/runs` | SQ30 rows 9a-9i | 400, nothing created |
| selected model not installed / below the memory floor | same | `<model label> is unavailable: <reason>` (reason names `bin/seed-edit-setup --model <id>`, or the memory figure) | 409, nothing created |
| selected LoRA not installed | same | `LoRA <label> is unavailable: <… (run bin/seed-edit-setup --lora <id>)>` | 409, nothing created |
| bad `--qwen-model` / `--lora` | `bin/seed-edit` | SQ12 rows 9-16 | exit 2, nothing written |
| model / LoRA missing at run time | `bin/seed-edit` | SQ21 texts | exit 2, run.json `failed` |
| low available memory | `bin/seed-edit` | `only <x.x> GiB available after waiting 600 s; <label> needs <floor> GiB; free memory and retry` | exit 2 |
| mflux below 0.24.0 | tool and child | `mflux <v> in <venv> is older than 0.24.0 (run bin/seed-edit-setup)` / SQ28's child text | refused before loading |
| unknown family in the child spec | child | `seed-edit-child: unknown model family '<x>'; refusing` | child exit 2 → SG17 `<label> child exited 2: …` |
| setup argv / qwen2511-bf16 / disk | `bin/seed-edit-setup` | SQ41, SQ44 step 4 | exit 2 |

---

## 9. Tests

### 9.1 Rules

[SG] §9's rules hold, with these changes:
- `bin/seed-edit-setup` is loaded in-process with `SourceFileLoader("seed_edit_setup", path)` (as `test_sg_final_setup_resume_counts_what_is_present` already does) and its `main` **is** called, but only with `setup.subprocess.call` (a recorder returning 0), `setup.subprocess.run` (a recorder returning `types.SimpleNamespace(returncode=0, stdout="3.13\n", stderr="")` for the base-python version check and `types.SimpleNamespace(returncode=0, stdout="", stderr="")` for the report's probe), `setup.free_gib` and `setup.venv_ready` replaced, `SEED_EDIT_SETUP_PYTHON` pointing at an executable stub file under `tmp_path`, and the hub under `tmp_path` through `Z_IMAGE_HF_HOME`: no test starts a process from it, downloads anything or touches a real venv. `DOWNLOAD` is executed with `exec(compile(setup.DOWNLOAD, "DOWNLOAD", "exec"), {})` under `monkeypatch.setattr(sys, "argv", …)` and a fake `huggingface_hub` module in `sys.modules` whose two functions record their keyword arguments.
- Pinned caches are built by a new helper in `tests/test_seed_edit_tool.py`: `pinned_cache(root, repo, revision, files)` = `mt.make_hf_cache(root, repo, files, refs=False)` followed by `os.rename(<repo dir>/snapshots/0123…4567, <repo dir>/snapshots/<revision>)` (the blob symlinks are relative and keep working); returns the snapshot path. A `qwen21` fixture always holds `vae/config.json`, `transformer/config.json`, `text_encoder/config.json`, `processor/tokenizer.json` and one `transformer/0.safetensors`.
- The child's behaviour is tested in-process with fake `mlx`, `mlx.core` and `mflux…` modules in `sys.modules` (SQT8); no test imports the real mflux or mlx.
- Every test sets `HOME` under `tmp_path`, removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable, sets `HF_HOME` and `Z_IMAGE_HF_HOME` under `tmp_path`; no test loads a real model, uses the real HOME, or contacts a server other than the in-test `127.0.0.1` one; none touches port 8177 or 8178; no test dispatches a job.

### 9.2 New tests

`tests/test_seed_edit_tool.py`:

| ID | Covers | Test |
|---|---|---|
| SQT1 | SQ14 | `tool.canvas(w, h, 32)` on SQ14's ten examples exactly (100×60 raises the exact refusal); SGT1's nine examples still hold with the default 16 |
| SQT2 | SQ12 | every new row's exact `Error:` text with `--run-dir` not created: `--qwen-model qwen21-q4` and `--lora uncensored=1` with zimage; `--qwen-model flux`; `--lora uncensored`, `--lora =1`; `--lora nope=1`; `--lora uncensored=1 --lora uncensored=0.5`; `--qwen-model qwen2511-q4 --lora uncensored=1` (family text with `Qwen-Image-Edit-2511 q4 (Lightning)`); scales `0`, `-1`, `2.5`, `x`, `nan`; `--probe --lora uncensored=1`. `check_args` of `--model qwen` alone → `qwen_model == "qwen2511-q4"`, `loras == []`; of `--qwen-model qwen21-q4 --lora viggle-turbo=0.5 --lora uncensored=1` → loras `[{"id": "uncensored", "scale": 1.0}, {"id": "viggle-turbo", "scale": 0.5}]` |
| SQT3 | SQ15, SQ16 | `weights_problem`: absent → exact `…@<rev12> is not in <a> or <b> (run bin/seed-edit-setup --model qwen21-q8)`; a snapshot under a different revision only → the same text; one `.incomplete` blob → `<repo>: download incomplete: 1 partial blob(s) (run …)`; a qwen21 snapshot without `processor/` and `vae/config.json` → `missing vae/config.json; missing processor/`; qwen2511-q4 without Lightning → the Lightning text; complete → `(None, <snapshot>, <lightning path or None>)`; found in the default hub when absent from the Z-Image hub. `lora_problem` absent/present texts. `mflux_env_problem` with 0.23.9 → `older than 0.24.0` |
| SQT4 | SQ18 | `probe()` exact dict on fixtures (`total_gib` 48): q4 + uncensored installed → those ok; `qwen21-bf16` and `qwen2511-bf16` carry the memory texts; `qwen.ok` true; with no model installed `qwen.ok` false and `qwen.reason` = the `"; "`-joined per-ID texts in registry order; `total_gib` 128 and the bf16 2.1 snapshot present → `qwen21-bf16` ok; `qwen` has no `backend` key. SGT13's importtime subprocess check still passes (no heavy import) |
| SQT5 | SQ7, SQ19-SQ23 | parametrized over: (`qwen21-q4`, `uncensored=1.0`) → steps 40, scheduler linear; (`qwen21-q4`, `viggle-turbo=1.0 uncensored=0.5` given in that order) → steps 6, scheduler `viggle_turbo`, lora order uncensored then viggle; (`qwen21-q8`, none) → `lora_paths == []`; (`qwen21-bf16`, `uncensored=1.0`) with `total_gib`/`avail_gib` 128; (`qwen2511-q4`, none) → `lora_paths == [<Lightning snapshot path>]`, `lora_scales == [1.0]`, steps 8, scheduler null, family `qwen2511`. Each: the mflux stub started once with SG20's argv and `HF_HUB_OFFLINE == "1"`; its spec equals the expected SQ23 dict exactly (pinned snapshot paths, never realpaths); `run.json` has `backend "mflux"` and the SQ7 keys; the backend line equals SQ20's text |
| SQT6 | SQ24 | content safety on every candidate of every registry model: for each of the four mflux entries (with and without each family-legal LoRA), 3 candidates with candidate 2 drawn red → `env["calls"]["safety"]` has exactly 3 entries, all skill `seed_edit` and the run's prompt; statuses ok/blocked/ok; `cand_02.png` and its pending file absent. For `qwen2511-bf16` (avail 70): the qwenedit stub's spec has `"skill": "seed_edit"` and SG19's dict byte-equal; a `blocked` line leaves no file. For each case, no `cand_NN.png` exists for a candidate whose status is not `ok` |
| SQT7 | SQ21, SQ13 | run-time refusals, each exit 2, run.json `failed`, every candidate failed, no child started: model not installed → `Qwen-Image-2.1 q8 is unavailable: …(run bin/seed-edit-setup --model qwen21-q8)`; LoRA missing → `LoRA Viggle turbo 6-step is unavailable: …(run bin/seed-edit-setup --lora viggle-turbo)`; `avail_gib` 10 with `AVAIL_WAIT_S = 0` → `only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free memory and retry`; `qwen2511-bf16` at avail 40 → the 64 GiB text. A child exiting 1 → error `Qwen-Image-2.1 q4 child exited 1: boom` |
| SQT8 | SQ28, SQ29 | the child in-process with fakes: `importlib.metadata.version` → `0.24.0`; fake `mlx.core` (`get_peak_memory`), fake `ModelConfig` with `qwen_image_21()`/`qwen_image_edit_2511()` returning objects with `model_name`; fake classes at both `FAMILIES` module paths recording `__init__` kwargs and `generate_image` kwargs and returning an object whose `.image` is an RGBA PIL image. qwen21 spec with 1 LoRA → init kwargs `{model_path, quantize: None, model_config: <21 config>, lora_paths: [p], lora_scales: [1.0], bake_lora: False}`; generate kwargs include `scheduler` and not `negative_prompt`; the saved file is mode `RGB`; stdout ends with `seed-edit-child done 1 <s>`. qwen21 with no LoRA → `lora_paths is None`, `lora_scales is None`. qwen2511 spec → `negative_prompt == " "` and no `scheduler`. Family `x` → returns 2 with the exact text and neither fake class is constructed. Version `0.23.0` → returns 2 with SQ28's text before the spec is opened |
| SQT9 | SQ2, SQ28 | `child.FAMILIES[family] == (cls.rsplit(".", 1)[0], cls.rsplit(".", 1)[1], cfg)` for each registry family's `mflux_class`/`mflux_config`; `child.MIN_VERSION == tool.MFLUX_MIN_VERSION == (0, 24, 0)`; the child's top-level imports are exactly SG24's list; its source contains `bake_lora=False`, `quantize=None`, `.convert("RGB").save(` |
| SQT10 | SQ3, SQ4, SQ6 | registry pins: IDs and order; every field of every entry equals SQ3's literal values; every non-None revision matches `^[0-9a-f]{40}$`; no LoRA has `allow_patterns`; `qwen2511-*` entries mirror `tool.EDIT_STEPS`, `tool.EDIT_LORA_REPO`, `tool.EDIT_LORA_FILE`; `qwen2511-bf16.memory_gib == character_dataset.EDIT_MIN_AVAIL_GIB`; `default_loras` for each model; `QWEN21_PATTERNS` equals §0.1's mflux list |
| SQT11 | SQ41-SQ44 | setup `main` with recorders: `[]` on an empty hub with `venv_ready` False → venv and pip calls as SG67, then one download call `[py, "-c", setup.DOWNLOAD, hub, J]` with `json.loads(J) == [{"kind": "snapshot", "repo": "mflux-community/qwen-image-2-1-mflux-q4", "revision": "b6c0…7f7f", "allow_patterns": None}, {"kind": "file", "repo": "abenzerps/…", "revision": "7959…c16b", "file": "qwen-image-2.1-uncensored-lora.safetensors"}]`, the env of SQ44 step 8, and license lines for both; `--model qwen21-bf16 --lora viggle-turbo --lora uncensored` → snapshot with `QWEN21_PATTERNS` and the two file items in that order; `--model qwen2511-q4` → snapshot + Lightning file item; `--lora viggle-turbo` alone → only that file item. For every combination of one model and any subset of LoRAs, no snapshot item names a LoRA repo or `lightx2v/…` |
| SQT12 | SQ44 step 4 | `free_gib` 5.0 for the default selection, venv not ready → exit 2 with the exact text (`need 13.9`, `total 13.9`, `present 0.0`, parts `qwen21-q4 ~9.91 GiB, uncensored ~0.03 GiB, mflux venv ~3 GiB, 1 GiB headroom`); a 3 MiB partial blob in the q4 repo dir reduces `present` accordingly; venv ready → no venv part; all present → `nothing to do`, no download call, exit 0 |
| SQT13 | SQ41 | exact exit-2 texts for `--model flux`, `--model qwen2511-bf16` (with the default hub path), `--lora nope`; none of them calls a recorder |
| SQT14 | SQ44 step 8 | `exec` of `DOWNLOAD` with a fake `huggingface_hub` and argv `["-c", hub, json.dumps(items)]` → `snapshot_download(repo_id, revision, allow_patterns, cache_dir=hub)` and `hf_hub_download(repo_id, filename, revision, cache_dir=hub)` called once each with exactly those keywords |

`tests/test_movie_ui_seedgen.py`:

| ID | Covers | Test |
|---|---|---|
| SQT15 | SQ30 | `validate_run_request`: every 9a-9i text exactly (including `loras: "x"`, `[{}]`, `[{"id": "uncensored"}]`, `[{"id": 5, "scale": 1}]`, a duplicate, `qwen_model: "qwen2511-q4"` + uncensored, scales `0`, `2.01`, `True`, `"1"`); defaults: qwen with neither field → `qwen_model "qwen21-q4"`, `loras [{"id": "uncensored", "scale": 1.0}]`; `qwen2511-q4` with loras absent → `[]`; explicit `[]` stays `[]`; request order viggle-then-uncensored comes back in registry order; zimage clean has `qwen_model None`, `loras []`; SG33's rows and order are unchanged |
| SQT16 | SQ7-SQ10, SQ31, SQ32 | `qwen_settings` for every model with and without each LoRA (exact dicts); `record_settings` on a new record, on a legacy qwen record with `backend` `mflux-q4`, `null`, `diffusers-bf16`, and on a zimage record; `registry_view()` exact; `capability` includes `registry` in both branches and the `Qwen-Image:` reason; `availability_error` texts for model unavailable, LoRA unavailable, zimage, `None` |
| SQT17 | SQ34, SQ35 | `seed_edit_argv` exact list for qwen with two LoRAs and for a legacy fields dict without `qwen_model`; `seed_edit_check` with the stub: the new shape parses; a missing model ID, an extra LoRA ID, `ok: "yes"` in a model entry, and a qwen value without `loras` → unparsable; extra keys are dropped |
| SQT18 | SQ42 | the five copied functions' code (SGT16's `_code_of`) is identical in `bin/seed-edit` and `bin/seed-edit-setup`; setup source contains `"mflux==0.24.0"`, `VENV_GIB = 3.0`, `HEADROOM_GIB = 1.0`, `cache_dir=hub`, `revision=item["revision"]`, and not `SETUP_MIN_FREE_GIB` (amended by §14a item B: the token rule of SQ45 is pinned by an env-recorder test, `test_sq_final_b_no_token_reaches_the_download`, not by a source grep, so the setup source may name the token variables) |
| SQT19 | SQ36, SQ39 | over HTTP: a qwen run `{qwen_model: "qwen21-q4", loras: [{id: "uncensored", scale: 0.5}]}` → 201; run.json has the four SQ7 keys; job fields gain `qwen_model`, `loras`; argv == `lib.seed_edit_argv(fields, ws)` and contains `--qwen-model qwen21-q4 --lora uncensored=0.5`. Each SQ30 row → 400 with nothing created. Probe says `qwen21-q8` unavailable → 409 `Qwen-Image-2.1 q8 is unavailable: <reason>`; `viggle-turbo` unavailable → 409 `LoRA Viggle turbo 6-step is unavailable: <reason>`; nothing created |
| SQT20 | SQ37, SQ38 | the run view's key set is SG43's plus the four; a hand-made legacy run (no `qwen_model`, backend `mflux-q4`) opens with `qwen_model {"id": "qwen2511-q4", …}`, `steps 8`; the runs list items have `qwen_model` and `loras` |
| SQT21 | SQ33 | a fresh server's `seed_edit` capability equals `{"ok": None, "reason": "probing", "checked": None, "models": None, "registry": seedgen.registry_view()}`; after `GET /api/host?refresh=1` `models` is the stub's parsed shape and `registry` is still present |
| SQT22 | SQ48-SQ56 | static page: the five new IDs appear once each; `Qwen-Image (edit)`; the two CSS rules; `app.js` contains `"Lightning 8-step LoRA built in (not selectable)"`, `" steps (turbo)"`, `"Unavailable here: "`, `"se-lora-scale-"`, `qwen_model:`, `loras:`, the new `SEED_MODEL_LABELS` and `SEED_BACKEND_LABELS` lines; each SQ50 function is defined exactly once; `function seedCanvas(w, h, multiple) {`; the page bans hold; `node --check app.js` passes when node exists; Review Focus 5's node comparison runs `seedCanvas(w, h, m)` against `tool.canvas(w, h, m)` for `m` in 16 and 32 over its cases |

### 9.3 Existing tests to change (in the same test commit)

| Test | Exact edit |
|---|---|
| SGT5 (`ARG_CASES`) | unchanged rows stay; the `qwen` rows add `--qwen-model qwen2511-q4` where they need to reach a later rule |
| SGT7 | the mflux memory case uses `--qwen-model qwen2511-q4` and expects `… Qwen-Image-Edit-2511 q4 (Lightning) needs 32 GiB …` |
| SGT8 (`choose_qwen`) | deleted; SQT3, SQT7 replace it |
| SGT9, SGT10, review focus 4 | use `pinned_cache` for the 2511 q4 repo and Lightning, pass `--qwen-model qwen2511-q4`; SGT9's expected spec is SQT5's qwen2511 dict; SGT10's texts become `Qwen-Image-Edit-2511 q4 (Lightning) child exited 1: boom`, `… child timed out after 1 s`, `… child exited -9: killed`; the backend line expectation becomes SQ20's |
| SGT11 | `--qwen-model qwen2511-bf16`; `record["backend"] == "diffusers"`; the backend line `seed-edit: backend diffusers (Qwen-Image-Edit-2511 bf16 (Lightning, diffusers); LoRAs none; 8 steps; scheduler default)` |
| SGT13 | the probe dicts take SQ18's shape (`qwen` without `backend`) |
| SGT14 | drop `BF16_MIN_AVAIL_GIB`; add `seedgen.qwen_model("qwen2511-bf16")["memory_gib"] == character_dataset.EDIT_MIN_AVAIL_GIB` |
| SGT15 | the import list is unchanged; the source pins become SQT9's; the refusal text becomes SQ28's 0.24.0 text with `0.23.0` |
| SGT16 | replaced by SQT18 |
| `test_sg_final_setup_resume_counts_what_is_present` | rewritten against SQ44 step 4's `present` (the same 3 MiB partial blob + 1 MiB venv case through `main` with `free_gib` patched) and the `already present` text |
| SGT17 | `MODELS` label `Qwen-Image`; the capability cases include `registry`; `availability_error` takes `clean` |
| SGT19, SGT22, SGT23, SGT26, SGT27, SGT31, SGT32 | `OK_MODELS` becomes SQ18's shape with every model and LoRA ok; texts `Qwen-Image-Edit is unavailable: …` become SQ31's; SGT23's record and `fields` gain the SQ36 keys (zimage: `qwen_model None`, `loras []`, `steps None`, `scheduler None`); SGT26/27's key sets gain SQ37/SQ38's keys; SGT31's initial capability gains `registry` |
| SGT33 | `PAGE_IDS` gains the five new IDs; `JS_TEXTS`' `SEED_MODEL_LABELS`-dependent strings follow SQ49; `SEED_FUNCTIONS` gains SQ50's names |
| SGT34 | the `bin/seed-edit` import list gains `"movie_ui_seedgen"` after `"movie_ui_lib"` |
| Review focus 5 | `js.index("  function seedCanvas(w, h, multiple) {")`; the script calls it with the case's multiple (SQT22) |

### 9.4 Load-bearing properties

Content safety on every candidate of every registry model (SQT6), "a LoRA repo is never snapshotted" (SQT11), exact child class/config/kwargs per family (SQT5, SQT8, SQT9), the 32-multiple canvas for 2.1 (SQT1, SQT22), and "nothing created on 400/409" (SQT19) are load-bearing; a change that weakens one of them fails review.

### 9.5 Browser check (before the merge; not pytest)

[SG] §9.3's throwaway demo under `$S/sgdemo/`, with the stub probe in SQ18's shape: `qwen21-q4`, `qwen2511-q4` and `uncensored` ok; `qwen21-q8` not installed; `qwen21-bf16` and `qwen2511-bf16` with memory texts; `viggle-turbo` not installed. Pass when:
1. Choosing Qwen-Image shows the Qwen box: `Qwen-Image-2.1 q4` selected, `40 steps`, the Uncensored row checked at strength 1, the Viggle row disabled with `unavailable — …(run bin/seed-edit-setup --lora viggle-turbo)`, and `Unavailable here: …` naming q8, 2.1 bf16 and 2511 bf16 with their reasons; those three options read `… — unavailable` and cannot be chosen.
2. A 800×600 upload reads `800 × 600 → 800 × 576` with 2.1 selected and `800 × 600 → 800 × 592` after switching to 2511 q4 (whose box reads `8 steps (Lightning)` and `Lightning 8-step LoRA built in (not selectable)`).
3. Strength 3 on the Uncensored row disables Generate with `LoRA Uncensored (abenzerps) strength must be above 0 and at most 2`.
4. Generate (2.1 q4, Uncensored 0.5) queues a run whose title reads `se-… · Qwen-Image-2.1 q4 + uncensored 0.5 · 40 steps` and whose job command carries `--qwen-model qwen21-q4 --lora uncensored=0.5`.
5. Edit again on a demo candidate keeps Qwen-Image-2.1 q4 and the LoRA state; a workspace switch keeps them too.
6. The demo's pre-made old run (no `qwen_model`, backend `mflux-q4`) lists as `Qwen-Image-Edit-2511 q4 (Lightning)` and opens with `(mflux q4)` in its title.
7. **A failed probe** (added by §14a, items E and F): restart the demo with the `seed_edit` capability set to `seedgen.capability(None, <detail>, <checked>)` (`ok: false`, `models: null`, the registry present), as a probe that printed unparsable output gives. Choosing Qwen-Image shows the box; the Uncensored and Viggle rows read `unavailable — <detail>` (never `unavailable — probing`), their checkbox and strength are disabled; with a source and a prompt set, Generate is disabled with `Qwen-Image unavailable: <detail>`; the browser console shows no error.
8. **A junk run record** (added by §14a, item D): a second pre-made run whose `run.json` has `qwen_model: {"id": "qwen21-q4", "repo": "mflux-community/qwen-image-2-1-mflux-q4"}`, `loras: [null]`, `steps: 40`, `scheduler: "linear"` and `backend: "mflux"` lists in the Runs table as `Qwen-Image-2.1 q4`, every other row of the table still renders, and it opens with the title `se-… · Qwen-Image-2.1 q4 · 40 steps (mflux)` and its candidates; the browser console shows no error.
Run this check after the §14a fix wave (it is the only behavioural test of the page; §11 item 4).

---

## 10. Live checks on the macstudio host (run by the user; the agent has no access)

The agent never connects to macstudio. The user checks out branch `seed-models` there, runs the steps and pastes the recorded figures back. Until then each row is recorded as "not run (awaiting the user)".

- **M0 setup.** `bin/seed-edit-setup --model qwen21-q4 --model qwen21-q8 --model qwen21-bf16 --model qwen2511-q4 --lora uncensored --lora viggle-turbo` (needs about 90.4 GiB free, SQ44). Record every size line, the licence lines and every `probe:` line. Pass: exit 0; every listed ID `ok`.
- **Fixed inputs for every row:** one source image the user picks (a typical seed photo, at least 1024 px on its long edge, the same file for every row), one edit prompt the user picks (the same text for every row), seed 1000, 4 candidates, nothing else running on the GPU, the movie-ui on macstudio. Note `psutil` available memory right before each Generate.
- **A/B matrix** (one Seeds-tab run per row):
  | Row | Qwen model | LoRAs | Expected steps / scheduler |
  |---|---|---|---|
  | A1 | qwen21-q4 | uncensored 1.0 | 40 / linear |
  | A2 | qwen21-q4 | none | 40 / linear |
  | A3 | qwen21-q4 | uncensored 0.5 | 40 / linear |
  | A4 | qwen21-q8 | uncensored 1.0 | 40 / linear |
  | A5 | qwen21-q8 | none | 40 / linear |
  | A6 | qwen21-bf16 | uncensored 1.0 | 40 / linear |
  | A7 | qwen21-bf16 | none | 40 / linear |
  | A8 | qwen2511-q4 | (Lightning built in) | 8 / default |
  | A9 | qwen21-q4 | uncensored 1.0 + viggle-turbo 1.0 | 6 / viggle_turbo |
- **Record per row:** the job's end state; the child config line (`model Qwen/Qwen-Image-2.1`, scheduler and LoRA list for A1-A7 and A9; `model Qwen/Qwen-Image-Edit-2511` with `zero_cond_t` true in the overrides for A8); the highest `mlx peak memory` line; seconds per candidate from `run.json` (candidate 1 includes the load); the blocked count out of 4 (the blocked rate); a one-line visual note per row (edit fidelity to the prompt, identity kept, artefacts); for A1 vs A3, which uncensored strength (0.5 or 1.0) follows the prompt better with fewer artefacts.
- **Pass:** every row ends `done` (a `blocked` candidate is recorded, not a failure); every row's config line matches its expected model, steps and scheduler; every blocked candidate has no `cand_NN.png`. A6/A7 prove Section 0.1(a) by running; if either fails to load, record the traceback's last line and see Open question 1.
- [SG] §9.4 L1-L3 are superseded by M0 and the matrix (A8 is the old L3).

---

## 11. Pass bar and rollout

1. SQT1-SQT22 and every edited existing test pass.
2. `python3 -m pytest tests/ -q -rA` from `WS` has no failures beyond the 2 known ones ([SG] §10 item 2).
3. `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`.
4. The browser check (§9.5) passes; an Opus design review of the diff against this spec is clean.
5. The live checks (§10) pass once the user runs them; before that they are recorded as not run.

Rollout: (1) snapshot `WS` (house rule) `tar czf $S/snapshot-pre-seedmodels-aee9461.tgz` excluding `generated/`; (2) record the full-suite counts at `aee9461`; (3) feature commit Q1-Q7; (4) test commit Q8 (§9.2, §9.3); (5) items 1-4; (6) push and the PR only on the user's go; the PR opens after PR #6 merges.

---

## 12. [SG] requirements superseded or amended

| [SG] item | Status |
|---|---|
| §0.0 item 3 (Qwen backend chosen by memory) | superseded by explicit selection (SQ12, SQ21, SQ30) |
| §0.0 item 6 (setup downloads the q4 repo and one Lightning file) | superseded by §6 |
| §0.3 "LoRAs on the edit models", "mflux q8" | superseded (registry LoRAs on 2.1; `qwen21-q8`); "steps/guidance controls", negative prompts, multi-image edits stay out of scope |
| §1.1 constants | amended by SQ3, SQ17, SQ49 |
| SG4 | amended by SQ12 |
| SG7 (backend line), SG17 (labels) | amended by SQ20, SQ13 |
| SG8 | amended by SQ14 (multiple per family) |
| SG11, SG12 | amended by SQ19 (four keys; backend values `mflux`/`diffusers`) |
| SG13 steps 3-4 | amended by SQ21 |
| SG14 (`mflux_problem`, `choose_qwen`, the override variables, `refs/main` lookup for q4) | superseded by SQ15-SQ17 |
| SG15 | superseded by SQ18 |
| SG19 | unchanged (now only `qwen2511-bf16`) |
| SG20 | amended by SQ23 (spec shape); parent screening unchanged |
| SG23 | amended by SQ26 |
| SG25, SG27 | superseded by SQ28, SQ29 |
| SG26 ("the LoRA is a local file path, never a repo ID") | kept, applied per LoRA (SQ25) |
| SG29, SG30 | amended by SQ34, SQ35 |
| SG33, SG36, SG37 | amended by SQ30-SQ32 |
| SG38 | amended by SQ33 |
| SG43, SG47 | amended by SQ37, SQ38 |
| SG55, SG57, SG59, SG60, SG61, SG63 | amended by SQ48-SQ55 |
| SG66-SG69 | superseded by SQ41-SQ47 (SG69's env rationale kept) |
| SGT8, SGT16 and the §9.3 list | replaced or edited per §9.3 |
| §9.4 L1-L3 | superseded by §10 |
| §12 R1, R6; §13 decisions 4, 6, 8, 10, 40 | superseded by the floors in SQ3, the probe rule in SQ18 and §6 |

---

## 13. Decisions made in the spec

1. **Registry location:** data and pure helpers in `movie_ui_seedgen.py`, imported by the tool and setup; the page gets it through the capability (SQ1, SQ10, SQ33).
2. **qwen21-bf16 backend:** mflux with `quantize=None` on the official repo, from the mflux source evidence (§0.1 a).
3. **Viggle file:** v0.3 6-step r128, the newest file whose keys match mflux's mapping (§0.1 b).
4. **Pinned revisions** for every setup-installed repo, looked up as `snapshots/<revision>`; `qwen2511-bf16` stays on `refs/main` (SQ4, SQ15).
5. **Memory floors:** q4 20, q8 32, 2.1 bf16 56 (the notes' "~56 GiB"; mflux's ~46 GB peak plus margin), 2511 q4 32, 2511 bf16 64; the probe judges total memory, the job waits up to 600 s for available memory, for every model (SQ3, SQ18, SQ21).
6. **Canvas multiple 32 for 2.1** (SQ14).
7. **Steps/scheduler rule:** a LoRA with `steps` overrides the model's (SQ7).
8. **LoRA order:** registry order everywhere (SQ5).
9. **Request defaults:** absent `qwen_model` → `qwen21-q4`; absent `loras` → the family defaults; explicit `[]` = none (SQ30).
10. **CLI default:** absent `--qwen-model` → `qwen2511-q4` with no LoRA, for jobs queued before this feature (SQ12).
11. **Legacy run display:** `qwen2511-bf16` when the old backend was `diffusers-bf16`, else `qwen2511-q4` (SQ8).
12. **Backend values** `mflux`/`diffusers` in new runs; old values keep their labels (SQ19, SQ49).
13. **Probe shape:** `qwen` gains `models`/`loras`, loses `backend`; memory checked before installation (SQ18).
14. **409 for qwen** checks the selected model's own entry, then each LoRA (SQ31).
15. **Label rename:** `Qwen-Image-Edit` → `Qwen-Image` (SQ3, SQ48).
16. **Overrides removed:** `SEED_EDIT_QWEN_Q4_DIR`, `SEED_EDIT_LIGHTNING_FILE` (SQ17).
17. **mflux gate 0.24.0** in the tool and the child (SQ16, SQ28).
18. **Child:** own `FAMILIES` table, family-specific kwargs, RGB save, unknown family refused (SQ28).
19. **Setup argv:** both options repeatable; no options = default; `--lora` alone = LoRAs only; `qwen2511-bf16` refused (SQ41).
20. **Setup floor:** item bytes + 3 GiB venv + 1 GiB headroom − what is present (SQ44).
21. **Setup download target:** the Z-Image hub only, as before; licence lines before downloading (SQ43, SQ44).
22. **UI:** Qwen box with select, LoRA rows rebuilt only on family/availability change, steps text, unavailable list; selection survives Edit again and workspace switches (SQ48-SQ55).
23. **Viggle default strength 1.0** (the card's value) inside the approved (0, 2] range (SQ3).

## 14. Points the code or the sources make impossible or risky

1. **2.1 needs multiples of 32** (`qwen_image21_latent_creator.py:24-26`); the notes did not mention it. Resolution: per-family canvas (SQ14), mirrored in the page.
2. **Facts file vs HF:** `mflux-community/qwen-image-2-1-mflux-bf16` does exist. Resolution: the binding choice (official repo) stands because mflux loads it natively; the community repo is the fallback (Open question 1).
3. **mflux 2.1 output is RGBA-capable.** Resolution: the child saves `convert("RGB")` (SQ28); the parent screens the RGB image as before.
4. **`qwen2511-bf16` cannot be revision-pinned:** its loader is the pinned `character_dataset.py`, which resolves `refs/main` with `local_files_only=True`. Resolution: `revision: None` for that entry only, keeping SG14's `bf16_problem` (SQ4, SQ16).
5. **The Viggle repo is 97.67 GiB and the abenzerps repo 97.96 GiB.** Resolution: LoRAs are only ever file items (SQ43, SQT11).
6. **Turbo detection is by `model_config.model_name`.** Resolution: the child always passes the explicit registry config; no Turbo checkpoint is in the registry, and the Viggle schedule is passed by name (SQ28).
7. **A 2511 q4 snapshot downloaded at an older `main`** is not found under the pinned commit. Resolution: re-run setup for that model (SQ47).
8. **Strength above 1.0** for Viggle contradicts its card ("keep at scale 1.0"). Resolution: allowed by the approved range, default 1.0, the card's advice is not enforced.

## 14a. Amendments from the final review

The final whole-branch review of `b068542..08d1840` found no Critical issue and judged the branch ready "with fixes". The controller's ruling (one final fix wave, items A-I plus one spec-only note) is binding and amends this spec as below; where this section and an earlier one differ, this section wins. The exact edits and tests are in `.superpowers/sdd/2026-11-02-seed-models/final-fix-brief.md` (outside git). In this spec "§14a" means this section; "[SG] §14a" and SQ44 step 8's "SG67/§14a" mean the seed generator spec's.

| Item | Amends | Change | Why |
|---|---|---|---|
| A | SQ44 step 4 (`present`), Review Focus 4 | `present` = over the distinct pinned snapshots `<hub>/<repo dir>/snapshots/<revision>/` of the needed items that exist, `snapshot_gib` (realpath sizes, each realpath once) **+** over the distinct repo directories of the needed items, the lstat sizes of `partial_blobs(repo_dir)` (the `blobs/*.incomplete` files whose finished blob `<sha256>` is absent, `lib.intact_scan`'s rule) **+** `tree_gib(venv)` when the venv is not ok and exists (unchanged). New setup functions `partial_blobs(repo_dir)` and `present_gib(hub, needed)`. The refusal text and `total`/`need` are unchanged. | The whole-repo-directory sum counted another revision's snapshot and blobs (a 2511 q4 snapshot at an older `main`, SQ47), which the pinned download may not reuse, so such a host could pass the floor with about 2 GiB free and fill the disk; the floor exists to prevent that. A stale `.incomplete` beside a finished blob is never resumed, so it is not counted. Cost: a host whose old blobs the pinned commit does reuse is asked for more space than it will use (conservative). Review Focus 4 now expects a refusal 2 MiB under the full size (`0.0 GiB already present`) and a pass at the full size. |
| B | SQ23 (env), SQ44 step 8 (env), SQ45, SQT18 | `movie_ui_seedgen` gains `HF_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")` and the pure `hf_child_env(environ, **extra)`: a copy of `environ` with `extra` set, every `HF_TOKEN_VARS` key removed and `HF_HUB_DISABLE_IMPLICIT_TOKEN="1"`. The setup download child gets `hf_child_env(os.environ, <SQ44 step 8's four values>)`; `bin/seed-edit`'s mflux child gets `hf_child_env(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")`. SQ45 and SQT18 are amended in place. SQ1 (seedgen imports) and SQ26 (variables the tool reads) still hold: the tool removes keys from the child's copy and reads none. The diffusers bf16 child's environment (`run_bf16`) is unchanged. | House rule: no token in a child environment. Every setup download is public and the mflux child is offline (`HF_HUB_OFFLINE=1`), so neither needs one; `HF_HUB_DISABLE_IMPLICIT_TOKEN` also stops huggingface_hub from sending a token stored under `HF_HOME`. The old SQT18 source grep would have failed on any such fix, and the behaviour is now asserted on the env dict each recorder receives, with dummy token values (no assert prints a whole env dict). |
| C | SQ44 step 8 (after the download), SQ45 exit codes | After the download exits 0, for each needed snapshot item whose `weights_problem(dict(entry, builtin_lora=None), [hub])[0]` still contains `download incomplete`, setup prints, per path of `partial_blobs(<its repo dir>)`, `seed-edit-setup: orphan partial blob <path> blocks <id> (it is not part of <repo>@<revision[:12]>); delete it`; then the step 9 report; then exit 1 with `Error: <k> orphan partial blob(s) left by an earlier download block the pinned snapshot; delete the file(s) listed above, then re-run bin/seed-edit-setup`. New setup function `orphans_of(hub, needed)`. Setup never deletes a file. **[spec choice]** exit 1, not 0: the selected model is still unusable, so §10 M0's "exit 0" check fails visibly. | An `.incomplete` left by an old-`main` download whose sha is not in the pinned revision makes `intact_scan` report the pinned snapshot incomplete forever, and the `(run bin/seed-edit-setup --model <id>)` hint loops, because the pinned `snapshot_download` never touches it. |
| D | SQ55 (`seedModelText`) | `qwen_model` is used only when it is an object with a string `id` (else the text is `Qwen-Image`); `loras` only when it is an array, and then only its items that are objects with a string `id`. Both call sites (the run title and the Runs Model cell) use `seedModelText`, so both are covered. | `record_settings` passes a list's items through unchanged, so a hand-edited `run.json` with `loras: [null]` threw: the Runs table stopped at that row, `loadSeeds` rejected and `openSeedRun` never polled. |
| E | SQ53 (gating) | For `qwen`, when the capability has models but the page has no registry (`S.seeds.qwen` is null), Generate is disabled with `Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui server)`. | A movie-ui server started before this branch serves the new page with an old capability (no `registry`); Generate was enabled and `seedBody` threw on `S.seeds.qwen.model`, so the click did nothing. |
| F | SQ51 (LoRA rows), plan PR11 | A not-ok LoRA row's note is `"unavailable — " +` (the probe entry's `reason`; else the capability's `reason` when `cap.ok === false`; else `probing`). The rows' key becomes `family + "|" + JSON.stringify(<for each LoRA of the family: [id, ok, note]>)`. | After a failed probe (`models: null`) the rows read `unavailable — probing` forever; because `ok` stayed false the old key never changed, so the rows were never rebuilt. |
| G | SQ44 step 9 (test only) | New test of the per-ID probe lines in selection order and of the unparsable line (missing ID, empty, bad JSON, wrong shape); the setup fixture's `subprocess.run` recorder returns `rec["probe"]` as the probe's stdout. No behaviour change. | SQ44 step 9's probe lines had no test. |
| H | SQ16 (`mflux_env_problem`), §8 "mflux below 0.24.0" | `mflux_env_problem(entry)`; its three setup hints read `(run bin/seed-edit-setup --model <entry id>)`: `no mflux venv at <py> (run bin/seed-edit-setup --model <id>)`, `mflux is not installed in <venv> (run …)`, `mflux <v> in <venv> is older than 0.24.0 (run …)`. `cannot read the mflux version in <venv>` has no hint (unchanged). The LoRA hint already names `--lora <id>` (`lora_problem`) and is unchanged; the child's own SQ28 text is unchanged (the child has no model ID). | A bare `bin/seed-edit-setup` installs the default q4 selection, so a user of q8, 2.1 bf16 or 2511 q4 on a fresh host needed two setup runs. |
| I | SQ41 (default selection) | No option at all → models `[seedgen.DEFAULT_QWEN_MODEL]`, LoRAs `[l["id"] for l in seedgen.default_loras(seedgen.DEFAULT_QWEN_MODEL)]` (today `["qwen21-q4"]`, `["uncensored"]`, as before). | One source with SQ6 and SQ30's request default instead of a literal. |
| SQ4 note | SQ4 | `guidance` and `quant` are marked informational in place. | Nothing reads them (the tool sends `MFLUX_GUIDANCE`), so an edit to either would silently do nothing. |

New tests (all in the two seed test files; 184 tests there after the wave): `test_sq_final_a_the_floor_counts_only_the_pinned_revision`, `test_sq_final_b_no_token_reaches_the_mflux_child`, `test_sq_final_b_no_token_reaches_the_download`, `test_sq_final_c_an_orphan_partial_blob_is_named`, `test_sq_final_g_the_setup_probe_lines`, `test_sq_final_i_the_default_selection_follows_the_registry` (`tests/test_seed_edit_tool.py`) and `test_sq_final_d_e_f_page_guards` (`tests/test_movie_ui_seedgen.py`; text pins for E and F, a node run of `seedModelText` on junk views for D). Edited: SQT3, SQT7, SGT13 (item H texts), Review Focus 4 (item A), SQT18 (item B), the `setup_env` fixture (item G). No test is renamed or removed. §9.5 gains cases 7 (a failed probe, `models: null`) and 8 (a `run.json` with `loras: [null]`); the browser check runs after this wave.

**For the PR body (SQ47 upgrade action).** A host whose older `bin/seed-edit-setup` fetched Qwen-Image-Edit-2511 q4 or the Lightning LoRA at a `main` other than the pinned commits (`3c74aab7…`, `107d238d…`) loses the 2511 q4 path after this branch, and any queued pre-registry Qwen job (which runs `qwen2511-q4`) fails, until the user runs `bin/seed-edit-setup --model qwen2511-q4` on that host. The refusal text names that command. With item A, that run asks for the full size free (about 28.8 GiB with a ready venv; the old snapshot is not counted); if it then reports an orphan partial blob (item C), delete the listed file. macstudio may be such a host; put the same step in §10 M0's instructions to the user.

## 15. Open questions

1. **Live proof of (a).** The official-repo load is verified from mflux's source and its revision pin, not by running. If live rows A6/A7 fail to load, the fix is to change `qwen21-bf16`'s `repo`/`revision`/`allow_patterns`/`bytes` to `mflux-community/qwen-image-2-1-mflux-bf16` @ `cf34f2422e8fa33c2841239dfe3c34f5f319a122` / `None` / 33,127,131,833 (a registry data change only); this needs the user's decision then.
2. **Uncensored LoRA behaviour:** its live load and best strength (0.5 vs 1.0) are unknown until rows A1/A3; the default stays 1.0 (binding) until the user decides from the record.
3. **Memory floors for q8 (32) and 2.1 bf16 (56)** are estimates from mflux's published peaks; the matrix's peak-memory figures may justify tuning them (a registry data change).
