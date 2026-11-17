# Custom (user-added) Qwen edit LoRAs: register a public Hugging Face LoRA or a local .safetensors file once, then pick it in Seeds, Locations, Characters, Compose and `bin/ltx-movie --seed-edit-lora`, with its trigger prepended to every edit prompt

Date: 2026-11-17

Status: design spec and implementation plan in one document.

**The user's goal (verbatim):** "add custom loras to Seed creation and in the shots pipeline like https://huggingface.co/WarmBloodAban/Anything_to_Real_Characters_2511". That LoRA: base `Qwen/Qwen-Image-Edit-2511`, Apache-2.0, trigger prompt "transform the image to realistic photograph", the author recommends 30 steps and CFG 4 (not Lightning), it turns anime or stylised images into photoreal ones.

**The user's approved design (binding; Section 0.2 lists it in substance with what this spec adds).** Choices this spec makes beyond it are marked **[spec choice]**. The implementer makes no design decisions; every text in Section 3 is exact.

**Where.**
- Worktree `$S/cl-wt`, branch `custom-edit-loras`, at `20cee82` (Merge PR #26, shots-image-moment). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number is verified at `20cee82`.
- At `20cee82` every `PIPELINE_FILES` member is byte-identical to `ca958ca1c1320fdcb936c508f432eff83330d512`, the current `test_mut26` BASELINE (`tests/test_movie_ui_builder.py:293`; checked with `git diff --quiet ca958ca HEAD -- <PIPELINE_FILES>`).
- `/Users/reubenpatterson/local_agent_harness` is never touched. The user's other Mac (macstudio) is never accessed; the live checks (Section 6) are run by the user.

**Builds on** **[SQ]** `docs/superpowers/specs/2026-11-02-seed-models-design.md`, **[SG]** `2026-11-02-seed-generator-design.md`, **[QE]** `2026-11-03-qwen-edit-models-design.md`, **[SE]** `2026-11-05-compose-shots-seed-edit-design.md`, **[CR]** `2026-11-09-shots-multi-reference-stills-design.md`, **[XR]** `2026-11-13-extra-reference-images-design.md`, **[BF]** `2026-10-30-batch-forks-design.md` and **[LC]** `2026-10-17-robust-story-lora-catalog-design.md`. Every requirement of those specs stays in force except where Section 8 names it as amended.

**IDs.** Requirements **CL1-CL52** (plus CL22a and CL22b), tests **CL-T1-CL-T34**, KPIs **CLK1-CLK8**, live checks **CL-LV0-CL-LV9**, existing-test edits **E1-E9**. At `20cee82`, `git grep -nE "\bCL[0-9]+\b|CL-T[0-9]|CLK[0-9]|CL-LV[0-9]"` finds nothing.

**Terms.**
- The **registry** is the merged list of Qwen edit LoRAs: the **built-ins** (`uncensored`, `viggle-turbo`, both family `qwen21`) followed by the **custom LoRAs**.
- A **custom LoRA** (a **user entry**) is one entry of the **registry file** `generated/seed_loras/user_loras.json`. Its `source` is `"hf"` (a public Hugging Face repo pinned at a commit, downloaded by `bin/seed-edit-setup`) or `"local"` (a `.safetensors` file referenced in place, never copied).
- A LoRA's **trigger** is an optional text that `qwen_edit.run_jobs` prepends to every edit prompt of a selection that includes it.
- An **edit prompt** is the `"prompt"` of one `run_jobs` job.

---

## 0. Scope

### 0.1 Grounding (verified at `20cee82`)

**The registry today.** `movie_ui_seedgen.py` (341 lines, not pinned, in `NEW_PY`) holds `QWEN_MODELS` `:47-77`, `QWEN_LORAS` `:78-87`, `QWEN_MODEL_IDS` `:88`, `QWEN_LORA_IDS` `:89`. Family `qwen2511` has no LoRA; `qwen2511-q4` (`:66-71`, backend `mflux`) always loads `LIGHTNING` `:41-44` as its `builtin_lora`; `qwen2511-bf16` (`:72-76`) is backend `diffusers`. The module is standard library plus `movie_ui_lib` only; `tests/test_movie_ui_seedgen.py:205-209` (`test_sgt17_the_module_imports`) pins its sorted import list `["movie_ui_lib", "re", "secrets", "time"]`.

**`run_jobs` is the single edit choke point.** `qwen_edit.run_jobs` `:506-625` runs every Qwen edit: `bin/seed-edit` `run_qwen` `:421-432`; `bin/ltx-movie` Phase 1c `:2857`, seeded shots `:3075`, seed context `:3292`, cast refs `:3678`; `character_dataset._run_registry_edit` `:1881` (Characters and, through `character_dataset`, Locations). The mflux branch `:560-599` writes `mflux_spec.json` with each job's `"prompt"` `:567-569` and screens each output with `content_safety.assert_image_safe(rgb, skill=skill, prompt=job["prompt"])` `:593` (the prompt is logged in `content_safety.log`, `content_safety.py:84-92`). The diffusers branch `:531-559` passes only Lightning (`EDIT_LORA_REPO`/`EDIT_LORA_FILE`) to `character_dataset.py qwenedit` and silently ignores registry LoRAs.

**The mflux child** `seed_edit_mflux_child.py:83-89` passes `lora_paths` and `lora_scales` to mflux 0.24.0 with `bake_lora=False`; guidance is always `MFLUX_GUIDANCE = 1.0` (`qwen_edit.py:48`); qwen2511 jobs get `negative_prompt=" "` (`:102`). mflux 0.24.0 (`src/mflux/models/common/resolution/lora_resolution.py`, rule priority 0 `exists_locally`) uses an existing local path as is, and `src/mflux/models/qwen/weights/qwen_lora_mapping.py:13-24` accepts `X.lora_up.weight`/`X.lora_down.weight`, `X.lora_B.default.weight`/`X.lora_A.default.weight`, `diffusion_model.X.lora_A.weight` and `lora_unet_X.lora_down.weight` key forms; `lora_loader.py:131-176` raises when no layer applies.

**The target LoRA** (HF API `GET /api/models/WarmBloodAban/Anything_to_Real_Characters_2511?blobs=true`, read 2026-11-17): `sha` `e8f98cb5f976c9431f2bef47bd1a97caa1ee4ce7`; `gated: false`; `cardData.base_model` `"Qwen/Qwen-Image-Edit-2511"`, `cardData.license` `"apache-2.0"`, `cardData.instance_prompt` `"transform the image to realistic photograph"`; siblings `.gitattributes` (2307), `AnythingtoRealCharacters2511_20.safetensors` (354082336, the only root `.safetensors`), `README.md`, `images/2511动漫转写实真人.jpg`. Its safetensors header (1441 keys) uses `transformer_blocks.N.attn.add_k_proj.lora_A.default.weight` / `...lora_B.default.weight`. **`lora_catalog.has_lora_pairs` (`lora_catalog.py:326-329`) only matches `.lora_A.weight`, so it returns False for this file; this spec defines its own pair rule (CL19).**

**Consumers of the LoRA registry** (`git grep -nE 'QWEN_LORAS|QWEN_LORA_IDS|qwen_lora\(|lora\["repo"\]|\["revision"\]|\["file"\]|pinned_file|registry_order|default_loras|qwen_settings|record_settings|registry_view|lora_problem|check_lora_args|install_problem|generator_text|selection_of'`, plus `app.js`). "Change" names the requirement that edits it; "none" means it works unchanged through the accessors.

| # | File:line | Code | Reads | Change |
|---|---|---|---|---|
| C1 | `movie_ui_seedgen.py:124-153` | `qwen_selection` | `QWEN_LORA_IDS` `:142`, `qwen_lora` `:147`, `registry_order` `:153` | CL9, CL13 |
| C2 | `movie_ui_seedgen.py:234-239` | `qwen_lora` | `QWEN_LORAS` | CL7 |
| C3 | `movie_ui_seedgen.py:242-244` | `registry_order` | `QWEN_LORA_IDS.index` (raises on an unknown id) | CL8 |
| C4 | `movie_ui_seedgen.py:247-251` | `default_loras` | `QWEN_LORAS` | CL7 |
| C5 | `movie_ui_seedgen.py:254-269` | `qwen_settings` | `lora["repo"]`, `lora["file"]` `:263` | CL10 |
| C6 | `movie_ui_seedgen.py:272-281` | `record_settings` | the record only | none (CL45) |
| C7 | `movie_ui_seedgen.py:289-298` | `registry_view` | `QWEN_LORAS` | CL12 |
| C8 | `movie_ui_seedgen.py:311-329` | `availability_error` | `qwen_lora`, the probe's `loras[id]` | none (CL34 guarantees the key) |
| C9 | `qwen_edit.py:242-248` | `lora_problem` | `lora["repo"]`, `["revision"]`, `["file"]` | CL25 |
| C10 | `qwen_edit.py:371-395` | `check_lora_args` | `QWEN_LORA_IDS` `:380-381`, `qwen_lora` `:384` | CL13, CL26 |
| C11 | `qwen_edit.py:398-406` | `cli_selection` | `default_loras` | none |
| C12 | `qwen_edit.py:409-415` | `settings`, `selection_of` | `qwen_settings` | none |
| C13 | `qwen_edit.py:465-471` | `generator_text` | `qwen_settings` | none (CL10's `removed` item keeps it working) |
| C14 | `qwen_edit.py:474-489` | `install_problem` | `registry_order`, `qwen_lora`, `lora_problem` | CL27 |
| C15 | `qwen_edit.py:506-625` | `run_jobs` | `install_problem`, `qwen_settings` `:522`, `registry_order` `:564` | CL28 |
| C16 | `qwen_edit.py:181-189`, `:209-214` | `pinned_file`, `weights_problem` (Lightning only) | `builtin_lora` | none |
| C17 | `bin/seed-edit:156` | `check_args` | `check_lora_args` | none |
| C18 | `bin/seed-edit:259-261` | `probe` | `QWEN_LORAS`, `lora_problem` | CL30 |
| C19 | `bin/seed-edit:293`, `:300`, `:319` | `preflight`, `new_record` | `install_problem`, `qwen_settings` | CL31 |
| C20 | `bin/seed-edit-setup:124-132` | `pinned_file` (byte copy of C16, SQT18) | — | none |
| C21 | `bin/seed-edit-setup:261-279` | `selection` | `default_loras`, `QWEN_LORA_IDS` `:277-278` | CL32 |
| C22 | `bin/seed-edit-setup:282-299` | `items_of` | `qwen_lora`, `repo/revision/file/bytes/license` | CL32 |
| C23 | `bin/seed-edit-setup:302-308`, `:319-345` | `item_ok`, `report` | `pinned_file` | CL32, CL33 |
| C24 | `bin/ltx-movie:1184`, `:1258` (pinned) | `_resolve_seed_edit`, cast refs resolver | `cli_selection` | none |
| C25 | `bin/ltx-movie:2832`, `:2862`, `:2957`, `:3155`, `:3571` (pinned) | reuse keys and records | `qe.settings` | none (CL10 item shape) |
| C26 | `bin/ltx-movie:2850`, `:3037`, `:3343`, `:3411`, `:3631`, `:4073`, `:4104`, `:4149`, `:4280` (pinned) | header lines | `generator_text` | none |
| C27 | `bin/ltx-movie:2857`, `:3075`, `:3292`, `:3678` (pinned) | the four edit paths | `run_jobs` | none (CL28 applies the trigger inside) |
| C28 | `character_dataset.py:934`, `:1069`, `:1236`, `:1278`, `:1288`, `:1339`, `:1342`, `:1881` (pinned) | Characters edits | `selection_of`, `generator_text`, `cli_selection`, `settings`, `run_jobs` | none |
| C29 | `location_dataset.py:491`, `:591`, `:827`, `:881`, `:884`, `:905`, `:954`, `:960` | Locations edits | the same | none |
| C30 | `movie_ui_server.py:217` | initial `seed_edit` capability | `registry_view` | none |
| C31 | `movie_ui_server.py:229`, `:787`, `:1851` | `seed_edit_check(..., seedgen.QWEN_LORA_IDS)` | `QWEN_LORA_IDS` | CL36 |
| C32 | `movie_ui_server.py:765`, `:1514`, `:1548`, `:1622`, `:1669`, `:2107`, `:2174`, `:2222`, `:2230` | `qwen_selection` (Compose, Characters, Locations) | — | none |
| C33 | `movie_ui_server.py:1808`, `:1909` | `record_settings` (Seeds run views) | — | none |
| C34 | `movie_ui_server.py:1877-1879` | `_h_seed_run_create` initial `run.json` | `qwen_settings`, `clean["prompt"]` | CL37 |
| C35 | `movie_ui_lib.py:1761-1782` | `_probe_qwen` (exact LoRA id set) | `lora_ids` | CL34 |
| C36 | `movie_ui_lib.py:1135-1151` | `_rule_seed_edit` (`SEED_EDIT_ID_RE` `^[a-z0-9][a-z0-9-]{0,31}$`) | — | none (`user-` + 24 = 29 chars) |
| C37 | `movie_ui_lib.py:1018-1023` | `qwen_edit_flags` | — | none |
| C38 | `movie_ui_batch.py:38-56` | `FIELD_LEVELS`, `COPY_FILES` (`seed_edits.json` at level `render`) | — | none (CL47) |
| C39 | `static/movie-ui/app.js:1949-1959` | `seedRegistry`, `seedQwenEntry`, `seedLoraEntry` | capability registry | none |
| C40 | `static/movie-ui/app.js:1965-1978` | `seedModelText` | the record's ids | none |
| C41 | `static/movie-ui/app.js:1983-2151` | `qwenPicker` (`fresh` `:1992-2001`, rows `:2075-2096`, turbo `:2097-2102`) | `registry.loras` | CL40-CL43 |
| C42 | tests (Section 5.2) | `QWEN_LORAS`/`QWEN_LORA_IDS` pins | — | E3-E5 |

**The capability probe is cached per server run.** `MovieUIServer.__init__` `:213-217` seeds `capabilities["seed_edit"]` with `registry_view()`; `refresh_capabilities` `:224-235` runs `bin/seed-edit --probe` and stores `seedgen.capability(...)`, which embeds `registry_view()` (`movie_ui_seedgen.py:301-308`). It runs once at start (`_probe_once`, `start_threads` `:672-678`) and on `GET /api/host?refresh=1` (`:624-625`). The page reads only this cached copy (`app.js:229-232`, `:1949`). So a registry change is invisible to the page until the next refresh (CL38 fixes this for add/remove from the page). The per-request probes (`edit_availability` `:786-788`, `_h_seed_run_create` `:1851`) run `bin/seed-edit --probe` against the request's workspace each time.

**`_probe_qwen` requires the exact LoRA id set** (`movie_ui_lib.py:1774-1781`). The probe child reads its own workspace's registry; when that differs from the server's, `lib.seed_edit_check` returns "printed unparsable output" and the whole Seeds capability fails. CL34 and CL39 fix this.

**Test environment rules.**
- `tests/conftest.py` isolates `LORA_CATALOG_DIR` per test (`:8-12`); CL52 adds the same for the registry file.
- Nine helpers delete every `SEED_EDIT_*` variable: `tests/test_ltx_movie_extra_refs.py:115`, `test_ltx_movie_seed_edit.py:99`, `test_qwen_edit.py:45`, `test_ltx_movie_cast_refs.py:100`, `test_ltx_movie_shots_seed.py:148`, `test_movie_ui_seedgen.py:389`, `test_seed_edit_tool.py:120`, `test_movie_ui_qwen_edit.py:55`, `test_ltx_movie_seed_context.py:117`. Without E2 they would delete the isolation variable and read the developer's real registry file.
- `tests/test_movie_ui_builder.py:241-269` (`test_mut25`) scans `NEW_PY`, and `:259-269` pins the top-level imports of `movie_ui_lib.py` and `movie_ui_server.py`. `tests/test_qwen_edit.py:385-405` (QET11) pins `qwen_edit.py`'s top-level imports and the tail of `NEW_PY`. `tests/test_movie_ui_seedgen.py:1320-1331` (SGT34) pins `bin/seed-edit`'s top-level imports, and `:1346-1360` (SQT18) pins `bin/seed-edit-setup`'s top-level imports and byte-copies.
- `tests/test_movie_ui_qwen_edit.py:466-470` (QET38) forbids `https?://`, inline `on...=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(` and `new Function` in `index.html` and `app.js`, and pins the `se-qwen-box` markup (`QWEN_BOX` `:430-435`, also `tests/test_movie_ui_seedgen.py:1174-1179`). So the new form is built by JS (CL40) and uses `askConfirm` (`app.js:142-162`).
- `len(srv.ROUTES) == 64` is pinned in `tests/test_movie_ui_http.py:44`, `test_location_ui.py:66`, `test_movie_ui_seedfolder.py:923`, `:960`, `test_movie_ui_seedgen.py:627`; `test_sgt20` (`test_movie_ui_seedgen.py:622-627`) pins the six seed routes right after `POST /api/uploads`.

### 0.2 The user's approved design (binding), then what this spec adds

1. **Storage and model.** File `generated/seed_loras/user_loras.json` (override env `SEED_EDIT_USER_LORAS`), schema `seed-edit.user-loras.v1`, atomic write under a lock (the `lora_catalog.py` approach). Entry keys as the built-ins (id, label, family, revision, file, bytes, default_scale, license, steps, scheduler) plus `trigger` (optional, at most 200 characters), `user: true`, `source` `"hf"|"local"`; `default_on` always false. hf entries keep repo/revision/file; local entries have path (resolved absolute), sha256, bytes and no repo/revision. IDs `user-` + 1-24 of `[a-z0-9-]`, never colliding with a built-in. Order: built-ins first, then user entries in added order. Accessors `seedgen.qwen_loras()` and `qwen_lora_ids()` replace direct constant reads; the built-ins stay as `BUILTIN_QWEN_LORAS`; the merged list is re-read when the file's mtime changes. A missing or corrupt file gives built-ins only and one warning line, and never breaks a run. Old `run.json` and `seed_edits.json` records still read after a remove.
2. **Module and CLI.** New `seed_lora_registry.py` (shared by the CLI and the server) and `bin/seed-edit-lora` with `add --repo OWNER/NAME [--file F] | add --path P`, plus `[--family qwen21|qwen2511] [--id] [--label] [--trigger] [--scale] [--steps]`, `list`, `remove ID`; exactly one of `--repo`/`--path`. HF: one public unauthenticated call to the HF model API through one injectable function; pin the repo's current commit sha as revision; read the file list with sizes and the licence from the card; never download weights (`bin/seed-edit-setup --lora ID` stays the only downloader, with its disk check; it accepts user ids and only reports present/missing for local ones). File choice: exactly one root `.safetensors` is used; several need `--file`; anything not `.safetensors` is refused; above 8 GiB is refused. Family from the card's `base_model` (`Qwen/Qwen-Image-Edit-2511` → `qwen2511`, `Qwen/Qwen-Image-2.1` → `qwen21`), else `--family` is required; the inferred family is printed; a local path needs `--family`. Local files are referenced in place: exists, regular file, `.safetensors`, at most 8 GiB, `~` and relative paths expanded; the header must show LoRA A/B pairs; sha256 and size are stored; at run time the file must still exist with the recorded size (no re-hash), else a refusal naming the path and `re-run bin/seed-edit-lora add`; for hf entries `bin/seed-edit-setup` reads the header after download and an entry failing it is unusable. Defaults: id from a slug of the repo or file name cut to 24 with a numeric suffix on a clash; scale 1.0 (range above 0 to 2); label the repo or file name. `remove` deletes only the registry entry, never files, and prints the path. `list` shows id, family, source, repo@rev12 or path, scale, trigger, installed.
3. **Run path.** Nothing new for shots/Seeds beyond the registry. `run_jobs` prepends each selected LoRA's trigger (registry order, space-separated) to every job prompt; content safety screens the prompt with the trigger; the recorded prompt (`run.json`, `mflux_spec.json`) is the triggered text. Selection validation (`qwen_selection`, `check_lora_args`) refuses any LoRA on a diffusers-backend model. An entry may have steps (first-wins rule); `add --steps N` sets them; guidance stays 1.0; `qwen2511-q4` always loads Lightning, so the author's 30 steps / CFG 4 cannot be reproduced (a documented live-check risk). Memory floors unchanged.
4. **Server and UI.** `registry_view()` exposes user/source/trigger; `POST /api/seed-loras` (body exactly `{repo, file?}` or `{path}` plus `family?, id?, label?, trigger?, scale?, steps?`; unknown keys or bad values → 400 with CLI-identical wording) and `DELETE /api/seed-loras/<id>`, through the shared module; invalidate the cached probe on add/remove; routes in the `ROUTES` table pattern with sample paths and the route-table tests. UI: one shared "Add custom LoRA" form next to the LoRA picker on Seeds, Locations, Characters and Compose (source toggle, family, trigger, scale, steps), a custom tag and a remove button on custom entries, inside the existing `app.js` patterns. Batch forks and removed-LoRA behaviour are specified.
5. **Testing.** Numbered requirements with test ids; the full pytest run against the baseline (2 known baseline failures incl. `test_story_engine.py::test_rst62_import_sets`); the `test_mut26` BASELINE bump after any change to a pinned file; live checks on macstudio. Out of scope: dropping Lightning for a run, Z-Image stills LoRAs, diffusers-backend LoRAs, auto-updating pinned revisions.

**What this spec adds** (each justified in Section 1): the trigger character rule and the idempotent prefix (D1, D2); the prefix on an empty prompt (D3); the settings item shape of user entries, which carries `trigger` and the pin (D4); the `removed` item for an id no longer in the registry (D5); the pair rule that accepts `.lora_A.default.weight` (D6); keeping symlinks in a local path (D7); the registry file belongs to the UI's workspace and reaches every child through the environment (D8); the probe tolerance for `user-` ids (D9); refusal of duplicate content (D10); the HF URL form of `--repo` (D11); the instance_prompt hint instead of an automatic trigger (D12); a user entry's `steps` keeps the model's scheduler (D13); exit codes and HTTP statuses (D14); `.get()` access so the built-in dicts stay byte-identical (D15); lazy imports so no import pin moves except seedgen's (D16); the `SEED_EDIT_USER_LORAS` isolation and the nine helper edits (D17); no pinned file is touched (D18).

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D-1 | `movie_ui_seedgen.py` | no | 1 | the registry file reader, accessors, `trigger_prompt`, item shapes, `registry_view`, the diffusers rule (CL1-CL14) |
| D-2 | `seed_lora_registry.py` | new | 1 | add/remove/list core, HF fetch, header rules, file checks (CL15-CL22) |
| D-3 | `bin/seed-edit-lora` | new, mode 100755 | 1 | the CLI (CL23-CL24) |
| D-4 | `qwen_edit.py` | no | 1 | `lora_problem`, `check_lora_args`, `install_problem`, `run_jobs` (CL25-CL29) |
| D-5 | `bin/seed-edit`, `bin/seed-edit-setup` | no | 1 | probe, triggered `run.json` prompt, setup for user ids (CL30-CL33) |
| D-6 | `movie_ui_lib.py` | no | 1 | `USER_LORA_PREFIX`, `_probe_qwen` tolerance (CL34) |
| D-7 | `tests/conftest.py` and E2-E5 | — | 1 | isolation and registry pins |
| D-8 | `tests/test_seed_lora_registry.py` | new | 1 | CL-T1-CL-T24 |
| D-9 | `movie_ui_server.py` | no | 2 | routes, handlers, `refresh_seed_edit`, env propagation, accessors, triggered initial prompt (CL35-CL39) |
| D-10 | `static/movie-ui/app.js` | no | 2 | the form, the picker rows (CL40-CL44) |
| D-11 | `tests/test_movie_ui_seed_loras.py` | new | 2 | CL-T25-CL-T34 |
| D-12 | five route-count tests (E6), `tests/test_movie_ui_seedgen.py` registry-view and import pins (E4) | — | 2 / 1 | counts and literals |

Untouched (verified by CL50): every `PIPELINE_FILES` member (incl. `bin/ltx-movie`, `character_dataset.py`, `lora_catalog.py`, which is imported but not edited), `seed_edit_mflux_child.py`, `location_dataset.py`, `movie_ui_batch.py`, `movie_ui_seedfolder.py`, `content_safety.py`, `static/movie-ui/index.html`, `static/movie-ui/app.css`.

### 0.4 Out of scope

- Running a `qwen2511` edit without Lightning, or with guidance other than 1.0 (the author's 30 steps / CFG 4).
- Z-Image stills LoRAs (the LoRA catalog), video LoRAs.
- LoRAs on the diffusers backend (`qwen2511-bf16`): refused (CL13).
- Auto-updating a pinned revision; editing an entry in place (remove and add again).
- Downloading weights from the page (the page shows `bin/seed-edit-setup --lora ID`).
- LoKr/LoHa and other non A/B adapter formats (refused by CL19).
- Non-ASCII triggers (refused by CL3).
- A per-workspace registry for jobs in a workspace other than the UI's (D8).

### 0.5 Success criteria (KPIs)

- **CLK1.** With the HF call mocked by the recorded API answer of the target LoRA (Section 0.1), `bin/seed-edit-lora add --repo WarmBloodAban/Anything_to_Real_Characters_2511 --trigger "transform the image to realistic photograph"` writes exactly the entry of CL-T5 and prints the family line `family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)`.
- **CLK2.** For a selection with that LoRA, every `mflux_spec.json` job prompt, every `content_safety.log` prompt and the `run.json` `"prompt"` start with `transform the image to realistic photograph ` (CL-T15, CL-T16).
- **CLK3.** `git grep -nE "\bQWEN_LORAS\b|\bQWEN_LORA_IDS\b"` outside `docs/` finds nothing (every consumer reads the accessors or `BUILTIN_*`).
- **CLK4.** No test makes a network call: `HTTPSConnection` occurs exactly once in the workspace, inside `seed_lora_registry.fetch_model_info`, and every test that reaches `add --repo` patches `fetch_model_info` (CL-T6).
- **CLK5.** The full suite has no failure beyond the baseline list recorded before Task 1 (Plan, step 0).
- **CLK6.** Every new or changed Python file compiles with `/usr/bin/python3` (3.9) when present and with `sys.executable` (CL-T24).
- **CLK7.** `git diff --quiet ca958ca1c1320fdcb936c508f432eff83330d512 HEAD -- <PIPELINE_FILES>` exits 0 after both tasks (no BASELINE bump is needed).
- **CLK8 (live).** CL-LV3 and CL-LV5: the user judges the edited stills of an anime source more photoreal with the LoRA than without it at the same seed, and records the answer to the Lightning question (CL-LV4).

---

## 1. Decisions

- **D1. Trigger characters [spec choice].** A trigger is 1 to 200 characters matching `TRIGGER_RE = ^[A-Za-z0-9][A-Za-z0-9 ,.;:'!?()&/-]{0,199}$`, with no two consecutive spaces and no trailing space. It is prepended to prompts that reach JSON spec files, `content_safety.log`, `run.json`, the page (through `textContent`) and the mflux text encoder; it never reaches an argv (CL28 applies it after every argv is parsed). The rule excludes control characters, newlines, quotes `"`, backslashes, `<>{}[]$`, backticks and a leading `-`. Non-ASCII is refused (Section 7, Q6).
- **D2. Idempotent prefix [spec choice].** `trigger_prompt` skips a trigger that already occurs in the prompt (case-insensitive substring), like the catalog's LC18 `prefix_triggers`. Re-running a `run.json` prompt or a Characters regenerate therefore never doubles it.
- **D3. Empty prompt [spec choice].** The prefix is applied to an empty or whitespace-only prompt too; the result is the prefix alone (no trailing space). No current builder sends one (`bin/seed-edit` refuses an empty `--prompt` `:122-123`; `bin/ltx-movie` refuses a panel without `Image:` text), and a trigger alone is a valid instruction.
- **D4. Settings item of a user entry [spec choice].** `qwen_settings` records, for a built-in, `{id, repo, file, scale}` (unchanged); for an hf user entry `{id, repo, revision, file, scale, trigger}`; for a local user entry `{id, source: "local", file (basename), sha256, scale, trigger}`. Reason: `bin/ltx-movie`'s reuse keys (`:2832`, `:2957`, `:3155`, `:3571`) compare `qe.settings(...)` and the untriggered prompt; carrying `trigger` and the pin (revision or sha256) in the item makes a changed trigger or a re-pinned file re-edit the panels, with no change to the pinned `bin/ltx-movie`. A local item has no `repo` and no path, so a record never holds a user's absolute path.
- **D5. A removed id [spec choice].** `registry_order` sorts an id that is not in the registry after every known id; `qwen_settings` records it as `{"id", "scale", "removed": true}`; `trigger_prompt` skips it; `install_problem` refuses it (Section 3, M-REMOVED). So a recorded selection that names a removed LoRA never raises a `TypeError`: plan-time code (reuse keys, `generator_text`) works, and `run_jobs` refuses with `Unavailable`, which every caller already reports.
- **D6. Pair rule [spec choice].** `lora_catalog.has_lora_pairs` misses the target's `X.lora_A.default.weight` keys. `seed_lora_registry.lora_pair_count(header)` counts the keys K for which one of these substitutions on `K + "."` (first occurrence) gives a key present in the header (with the appended `.` removed): `".lora_A."` → `".lora_B."`, `".lora_down."` → `".lora_up."`, `".lora.down."` → `".lora.up."`. It covers every A/B form mflux 0.24.0's Qwen mapping lists. `lora_catalog.read_safetensors_header` and `lora_catalog.file_sha256` are reused unchanged.
- **D7. Local path keeps symlinks [spec choice].** `path` is `os.path.abspath` of the expanded input, not `os.path.realpath`. A Hugging Face snapshot file is a symlink to `blobs/<sha>` (no extension), and mlx picks the loader by extension; keeping the given name keeps `.safetensors`. The regular-file and size checks use the realpath.
- **D8. Whose registry [spec choice].** The registry file is `<the workspace of movie_ui_seedgen.py>/generated/seed_loras/user_loras.json` unless `SEED_EDIT_USER_LORAS` is set, like `lora_catalog.catalog_dir` (`lora_catalog.py:76-77`). The server's add/remove body has no `ws` (binding design), so the page edits the UI workspace's registry. `movie_ui_server.main` sets `SEED_EDIT_USER_LORAS` to that path before it starts any thread (CL39); every probe and job child inherits `os.environ` (`movie_ui_lib.py:212`, `:1306`), so a job or probe in another workspace reads the same file. `bin/seed-edit-lora` and `bin/ltx-movie` run by hand read their own workspace's file unless the variable is set.
- **D9. Probe tolerance [spec choice].** `_probe_qwen` keeps the exact rule for models and for every non-`user-` LoRA id; a `user-` id the probe did not report becomes `{"ok": false, "reason": M-NOT-REPORTED}`, and a `user-` key the server does not know is dropped. Reason: an older release's `bin/seed-edit` (or a race with a concurrent add) must not fail the whole Seeds capability. Existing SQT17 cases (a missing `loras`, an extra non-`user-` key) stay unparsable.
- **D10. Duplicates [spec choice].** `add` refuses an hf entry whose `(repo, file)` equals any registry entry's (built-in or user, any revision), and a local entry whose `path` or `sha256` equals a local user entry's (409, M-DUPLICATE). An A/B with other steps or scale is remove plus add (CL-LV4).
- **D11. `--repo` URL form [spec choice].** `https://huggingface.co/OWNER/NAME` with an optional trailing `/` is accepted and normalized to `OWNER/NAME`, because the user gave the LoRA as a URL. Nothing else (no `/tree/...`, no `hf.co`).
- **D12. No automatic trigger [spec choice].** The trigger is set only by `--trigger`/`trigger`. When the card has a string `instance_prompt` and no trigger was given, `add` emits note N-TRIGGER naming it. Binding design item 1 makes the trigger optional and user-given.
- **D13. Scheduler of a user entry [spec choice].** User entries always have `scheduler: null`. When the first LoRA with `steps` (registry order, SQ7's first-wins rule) has `scheduler: null`, `qwen_settings` keeps the model's own scheduler (`linear` for qwen21, `None` for qwen2511). `viggle-turbo` keeps `viggle_turbo`.
- **D14. Exit codes and statuses [spec choice].** `seed_lora_registry.RegistryError(status, message)`: 400 bad request value, 404 unknown custom id, 409 conflict or unreadable registry file, 502 Hugging Face API failure. `bin/seed-edit-lora` exits 2 for 400/404/409 and 1 for 502; argparse usage errors exit 2 as usual. The server answers the same status with `{"error": message}`.
- **D15. Built-in dicts unchanged [spec choice].** `BUILTIN_QWEN_LORAS` keeps exactly today's two dicts (SQT10's `LORA_REGISTRY` literal stays). Code reads `lora.get("user")`, `lora.get("source")`, `lora.get("trigger")` so built-ins need no new keys.
- **D16. Imports [spec choice].** `movie_ui_seedgen.py` gains `json`, `os`, `sys`, `threading` (E4 updates SGT17's list). `qwen_edit.py`, `bin/seed-edit`, `bin/seed-edit-setup`, `movie_ui_lib.py` and `movie_ui_server.py` keep their top-level imports; they import `seed_lora_registry` inside the functions that need it (QET11, SGT34, SQT18 and `test_mut25` stay as they are). `seed_lora_registry.py` imports `qwen_edit` only inside functions, so neither module imports the other at load time. `NEW_PY` is not extended ([CR] CR15, QET11 pins its tail); CL-T24 compiles and scans the new files instead.
- **D17. Isolation [spec choice].** The variable keeps its binding name `SEED_EDIT_USER_LORAS`. `tests/conftest.py` sets it to a missing per-test file (E1), and the nine helpers that delete `SEED_EDIT_*` skip it (E2). Without E2 those suites would read the developer's real registry file.
- **D18. Pinned files [spec choice].** No `PIPELINE_FILES` member changes: `bin/ltx-movie` and `character_dataset.py` already route through `qwen_edit`, and `lora_catalog.py` is imported only. So no `test_mut26` BASELINE bump is needed (CLK7). If an implementer finds a pinned file must change, they stop and report (Plan, step 0).

---

## 2. Requirements

### 2.1 The registry file and the accessors (`movie_ui_seedgen.py`)

- **CL1 (constants).** Rename `QWEN_LORAS` to `BUILTIN_QWEN_LORAS` (contents unchanged) and replace `QWEN_LORA_IDS` with `BUILTIN_QWEN_LORA_IDS = tuple(l["id"] for l in BUILTIN_QWEN_LORAS)`. Neither old name remains. Add, after `HF_TOKEN_VARS` `:94`:
  ```
  USER_LORAS_ENV = "SEED_EDIT_USER_LORAS"
  USER_LORAS_SCHEMA = "seed-edit.user-loras.v1"
  USER_ID_RE = re.compile(r"^user-[a-z0-9-]{1,24}$")
  USER_LORA_MAX_BYTES = 8 * 2 ** 30
  LABEL_MAX = 80
  LICENSE_MAX = 200
  STEPS_MAX = 100
  TRIGGER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.;:'!?()&/-]{0,199}$")
  HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
  HF_FILE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. +()-]{0,199}(/[A-Za-z0-9_][A-Za-z0-9_. +()-]{0,199})*$")
  HF_KEYS = ("id", "label", "family", "source", "repo", "revision", "file", "bytes", "default_on",
             "default_scale", "license", "steps", "scheduler", "trigger", "user")
  LOCAL_KEYS = ("id", "label", "family", "source", "path", "file", "sha256", "bytes", "default_on",
                "default_scale", "license", "steps", "scheduler", "trigger", "user")
  NO_LORAS_MSG = ("%s runs without LoRAs (its diffusers child loads only the built-in Lightning LoRA); "
                  "use qwen2511-q4")
  REMOVED_MSG = ("it is not in the Qwen edit LoRA registry (removed?); add it again with bin/seed-edit-lora "
                 "add, or choose other LoRAs")
  USER_LORAS_WARNING = "seed-edit: ignoring %s: %s; only the built-in Qwen edit LoRAs are available"
  ```
- **CL2 (path).** `user_loras_path()` returns `os.environ[USER_LORAS_ENV]` when it is set and non-empty, else `os.path.join(os.path.dirname(os.path.realpath(__file__)), "generated", "seed_loras", "user_loras.json")`.
- **CL3 (trigger rule).** `valid_trigger(text)` is True iff `text` is a `str`, `TRIGGER_RE.fullmatch(text)`, `"  " not in text` and `not text.endswith(" ")`.
- **CL4 (file validator).** `user_loras_problem(data)` returns `None` when `data` is a valid registry file, else one reason string, the first failing rule:
  1. `data` is a dict with exactly the keys `{"schema", "loras"}`, else `"top level must be {schema, loras}"`;
  2. `data["schema"] == USER_LORAS_SCHEMA`, else `"schema must be seed-edit.user-loras.v1"`;
  3. `data["loras"]` is a list, else `"loras must be a list"`;
  4. per entry `i` (1-based), in order, each failure `"entry %d: %s is invalid" % (i, key)`:
     - a dict whose `source` is `"hf"` with keys exactly `HF_KEYS`, or `"local"` with keys exactly `LOCAL_KEYS`; else the text `"entry %d: keys or source are invalid" % i`;
     - `id`: `USER_ID_RE.fullmatch`, not in `BUILTIN_QWEN_LORA_IDS`; a repeat gives `"entry %d: id %s is listed twice" % (i, id)`;
     - `label`: str, 1 to `LABEL_MAX` characters, no character below `\x20` and no `\x7f`;
     - `family` in `QWEN_FAMILIES`;
     - hf: `repo` matches `HF_REPO_RE`, contains neither `".."` nor `"--"`; `revision` matches `^[0-9a-f]{40}$`; `file` matches `HF_FILE_RE`, has no `".."` segment, ends with `".safetensors"`;
     - local: `path` is a str, `os.path.isabs`, no character below `\x20`, ends with `".safetensors"` (lower-case compare); `file == os.path.basename(path)`; `sha256` matches `^[0-9a-f]{64}$`;
     - `bytes`: int (not bool), 1 to `USER_LORA_MAX_BYTES`;
     - `default_on is False`; `default_scale`: number (not bool), `0 < x <= SCALE_MAX`;
     - `license`: str, 1 to `LICENSE_MAX` characters;
     - `steps`: `None` or int (not bool) 1 to `STEPS_MAX`; `scheduler is None`;
     - `trigger`: `None` or `valid_trigger`; `user is True`.
- **CL5 (reader).** `user_loras()` returns a tuple of entry dicts, never raises, and is thread-safe (a module `threading.Lock`):
  - `os.stat(path)` raising `FileNotFoundError` or `NotADirectoryError` → `()`, no warning, nothing cached;
  - another `OSError` → warning with reason `"cannot read: %s" % e`, `()`;
  - the cache key is `(path, st_mtime_ns, st_size, st_ino)`; an equal key returns the cached tuple without reading;
  - otherwise read the file as UTF-8 JSON; `OSError` → reason `"cannot read: %s"`; `ValueError`/`RecursionError` → reason `"not valid JSON"`; then `user_loras_problem`;
  - a reason prints `USER_LORAS_WARNING % (path, reason)` plus `"\n"` to `sys.stderr` once per cache key, and caches `()`; a valid file caches `tuple(data["loras"])`.
- **CL6 (merged list).** `qwen_loras()` returns `BUILTIN_QWEN_LORAS + user_loras()`; `qwen_lora_ids()` returns `tuple(l["id"] for l in qwen_loras())`. Built-ins come first, user entries in file order (append order, CL20).
- **CL7 (lookups).** `qwen_lora(lora_id)` and `default_loras(model_id)` iterate `qwen_loras()` instead of the constant. Behaviour is otherwise unchanged (user entries have `default_on: false`).
- **CL8 (order).** `registry_order(loras)`:
  ```
  ids = qwen_lora_ids()
  return sorted(loras, key=lambda item: ids.index(item["id"]) if item["id"] in ids else len(ids))
  ```
- **CL9 (selection ids).** `qwen_selection` checks `lora_id in qwen_lora_ids()` instead of `QWEN_LORA_IDS` (`:142`).
- **CL10 (settings).** `qwen_settings(model_id, loras)` builds each item with `settings_item(lora, scale)` (D4) and handles removed ids (D5) and the scheduler rule (D13):
  ```
  def settings_item(lora, scale):
      if not lora.get("user"):
          return {"id": lora["id"], "repo": lora["repo"], "file": lora["file"], "scale": scale}
      if lora["source"] == "local":
          return {"id": lora["id"], "source": "local", "file": lora["file"], "sha256": lora["sha256"],
                  "scale": scale, "trigger": lora["trigger"]}
      return {"id": lora["id"], "repo": lora["repo"], "revision": lora["revision"], "file": lora["file"],
              "scale": scale, "trigger": lora["trigger"]}
  ```
  In the loop, `lora = qwen_lora(item["id"])`; `None` appends `{"id": item["id"], "scale": float(item["scale"]), "removed": True}` and continues; otherwise it appends `settings_item(lora, float(item["scale"]))` and applies the first-wins steps rule. After the loop: `steps = turbo["steps"]`, `scheduler = turbo["scheduler"] if turbo["scheduler"] is not None else entry["scheduler"]`. Built-in results are byte-identical to today (SQT16 `_settings` unchanged).
- **CL11 (trigger prefix).** New pure function, D1-D3:
  ```
  def trigger_prompt(prompt, loras):
      """prompt with the triggers of the selected registry LoRAs in front (custom edit LoRAs spec CL11)."""
      missing = []
      for item in registry_order(loras):
          lora = qwen_lora(item["id"])
          trigger = lora.get("trigger") if lora is not None else None
          if (trigger and trigger.lower() not in prompt.lower()
                  and trigger.lower() not in [m.lower() for m in missing]):
              missing.append(trigger)
      if not missing:
          return prompt
      prefix = " ".join(missing)
      return prefix if not prompt.strip() else prefix + " " + prompt
  ```
  `loras` items need only `"id"` (a `{"id", "scale"}` selection or a settings item).
- **CL12 (view).** `registry_view()` iterates `qwen_loras()`; each LoRA item gains three keys after `"license"`: `"user": bool(lora.get("user"))`, `"source": lora.get("source", "builtin")`, `"trigger": lora.get("trigger")`; `"setup"` is `None` for `source == "local"`, else `"bin/seed-edit-setup --lora %s" % id` as today.
- **CL13 (diffusers refusal, server rule).** In `qwen_selection`, right after the family check (`:148-149`) and before the scale check: `if entry["backend"] == "diffusers": return None, None, "LoRA %s: " % lora_id + NO_LORAS_MSG % entry["id"]`. A `qwen21` LoRA on `qwen2511-bf16` still gets the family text first (unchanged tests).
- **CL14 (docstring).** The module docstring's second sentence names the registry file: the fixed models, the built-in LoRAs and the custom LoRAs read from `user_loras_path()` (docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md). "This module never writes and never starts a process" stays true.

### 2.2 `seed_lora_registry.py` (new)

- **CL15 (module).** Docstring names this spec and says: the only writer of the registry file; the only Hugging Face API caller (`fetch_model_info`); standard library plus `movie_ui_lib`, `movie_ui_seedgen` and `lora_catalog` at top level; `qwen_edit` imported inside functions only; Python 3.9 and 3.13. Top-level imports, in this order: `http.client`, `json`, `os`, `re`, `ssl`, then `import lora_catalog`, `import movie_ui_lib as lib`, `import movie_ui_seedgen as seedgen`. No `urllib`, no `load_module(`, no `match` statement, no `X | Y` annotations, `%` formatting only.
  Constants: `FIELDS = ("repo", "file", "path", "family", "id", "label", "trigger", "scale", "steps")`, `BASE_MODEL_FAMILIES = {"Qwen/Qwen-Image-Edit-2511": "qwen2511", "Qwen/Qwen-Image-2.1": "qwen21"}`, `HF_HOST = "huggingface.co"`, `HF_TIMEOUT_S = 30`, `HF_MAX_BYTES = 32 * 2 ** 20`, `USER_AGENT = "qwen-agent-seed-edit-lora/1"`, `HF_URL_RE = re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95})/?$")`, `PICKLE_EXTS = (".bin", ".pt", ".pth", ".ckpt", ".pkl")`, `LOCAL_LICENSE = "not stated (local file)"`, `NO_LICENSE = "not stated in the model card"`, and the message constants of Section 3.
- **CL16 (`RegistryError`).** `class RegistryError(Exception)` with `__init__(self, status, message)`: `Exception.__init__(self, message)`, `self.status = status`.
- **CL17 (`fetch_model_info(repo)`).** The only network code in the workspace:
  - `conn = http.client.HTTPSConnection(HF_HOST, timeout=HF_TIMEOUT_S, context=ssl.create_default_context())`;
  - `conn.request("GET", "/api/models/%s?blobs=true" % repo, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})` (`repo` is already `HF_REPO_RE`-valid, so no quoting); **no `Authorization` header, and no token variable is read**;
  - read at most `HF_MAX_BYTES + 1` bytes; status 200 with a longer body → 502 M-HF-BIG; status 200 → `json.loads(body.decode("utf-8"))` (decode or JSON error → 502 M-HF-JSON); status 301, 302, 307 or 308 → 400 M-HF-MOVED with the `Location` header (or `-`); 401 or 404 → 400 M-HF-NOTFOUND; any other status → 502 M-HF-STATUS;
  - `OSError`, `ssl.SSLError` and `http.client.HTTPException` → 502 M-HF-UNREACHABLE; `conn.close()` in `finally`.
- **CL18 (local file checks).** `check_local_file(path_text, base_dir)` returns `(path, real, size)` or raises `RegistryError(400, ...)`, first failure wins:
  1. `expanded = os.path.expanduser(path_text)`; not absolute and `base_dir is None` → M-PATH-ABS; not absolute → `expanded = os.path.join(base_dir, expanded)`; `path = os.path.abspath(expanded)` (D7);
  2. `path.lower().endswith(".safetensors")` else M-NOT-SAFETENSORS (`% path`);
  3. `os.path.exists(path)` else M-NOT-EXIST;
  4. `real = os.path.realpath(path)`; `os.path.isfile(real)` else M-NOT-REGULAR;
  5. `size = os.path.getsize(real)`; `size > USER_LORA_MAX_BYTES` → M-TOO-BIG;
  6. `lora_catalog.read_safetensors_header(real)`; `lora_catalog.CatalogError` → M-NOT-ST-HEADER;
  7. `lora_pair_count(header) == 0` → M-NO-PAIRS.
- **CL19 (pair rule).** `lora_pair_count(header)` (D6):
  ```
  PAIR_SUBSTITUTIONS = ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."), (".lora.down.", ".lora.up."))

  def lora_pair_count(header):
      count = 0
      for key in header:
          probe = key + "."
          for a, b in PAIR_SUBSTITUTIONS:
              if a in probe and probe.replace(a, b, 1)[:-1] in header:
                  count += 1
                  break
      return count
  ```
- **CL20 (strict load and save).** `load_entries()` returns the list of user entries of `seedgen.user_loras_path()`: a missing file → `[]`; unreadable, invalid JSON or `seedgen.user_loras_problem(data)` not None → `RegistryError(409, M-UNREADABLE % (path, reason))`. `save_entries(entries)` writes `{"schema": seedgen.USER_LORAS_SCHEMA, "loras": entries}` with `lib.write_json_atomic(path, ...)` (mode 0600, indent 2). Every read-modify-write runs inside `with lora_catalog.catalog_lock(path):` (the lock file `<dir>/.lock`, `lora_catalog.py:257-282`) after `os.makedirs(os.path.dirname(path), exist_ok=True)`. Entries are never sorted: order is append order.
- **CL21 (`add(request, base_dir)`).** Returns `(entry, notes)`; raises `RegistryError`. `request` is a dict of `FIELDS` (the server body or the CLI's parsed options); a value `None` counts as absent. Order:
  1. **Request rules R1-R12** (Section 3.2), pure, before any network or file access.
  2. **hf** (`repo` given): `info = fetch_model_info(repo)` (looked up as a module global so tests patch it), then rules H1-H9 (Section 3.3), which choose `file`, `bytes`, `family`, `license` and build the notes.
     **local** (`path` given): `path, real, size = check_local_file(path, base_dir)`, then `sha256 = lora_catalog.file_sha256(real)` (`OSError` → 400 `"cannot read %s: %s" % (path, e)`).
  3. **Under the lock:** `entries = load_entries()`; `ids = seedgen.BUILTIN_QWEN_LORA_IDS + tuple(e["id"] for e in entries)`; an explicit `id` in `ids` → 409 M-ID-TAKEN; duplicate content (D10) → 409 M-DUPLICATE; no explicit id → `default_id(slug source, ids)` (CL22); append the entry; `save_entries(entries)`.
  4. The entry, keys in `HF_KEYS`/`LOCAL_KEYS` order:
     - hf: `{"id", "label": label or repo[:80], "family", "source": "hf", "repo", "revision": info["sha"], "file", "bytes", "default_on": False, "default_scale": float(scale or 1.0), "license", "steps": steps, "scheduler": None, "trigger": trigger, "user": True}`;
     - local: `{"id", "label": label or os.path.basename(path)[:80], "family", "source": "local", "path", "file": os.path.basename(path), "sha256", "bytes": size, "default_on": False, "default_scale": float(scale or 1.0), "license": LOCAL_LICENSE, "steps", "scheduler": None, "trigger", "user": True}`.
     The built entry must pass `seedgen.user_loras_problem({"schema": ..., "loras": [entry]})` (an assertion; a failure is a bug).
  5. **Notes**, in this order (Section 3.4): N-FAMILY (hf only), N-FAMILY-CONFLICT (hf, when given and the card disagrees), N-TRIGGER (hf, no trigger, card `instance_prompt` is a str), N-STEPS (family qwen2511 and steps given), N-DOWNLOAD (hf), N-IN-PLACE (local).
- **CL22 (ids).** `slug(text)`: `re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].rstrip("-") or "lora"`. The slug source is the repo name after `/` (hf) or the file name without `.safetensors` (local, case-insensitive suffix). `default_id(base, ids)`: `"user-" + base` when free; else for `n = 2, 3, ...` the first free `"user-" + base[:24 - len("-%d" % n)].rstrip("-") + "-%d" % n`. Example: `Anything_to_Real_Characters_2511` → `user-anything-to-real-charact`, then `user-anything-to-real-chara-2`.
- **CL22a (`remove(lora_id)`).** Returns `(entry, kept)`. A built-in id → 400 M-BUILTIN; under the lock, an id not among the user entries → 404 M-UNKNOWN; otherwise drop it, save, and return `kept`: for local the entry's `path`; for hf `qwen_edit.pinned_file(repo, revision, file, qwen_edit.qwen_hubs())` (imported inside the function), which is `None` when it was never downloaded. No file is deleted.
- **CL22b (run-time checks shared with `qwen_edit` and setup).**
  - `local_problem(lora)`: `real = os.path.realpath(lora["path"])`; not `os.path.isfile(real)` → M-LOCAL-MISSING; `os.path.getsize(real) != lora["bytes"]` → M-LOCAL-CHANGED; else `None`. No hash, no header read (binding design).
  - `downloaded_problem(lora, path)` for a downloaded hf user file: size of its realpath `!= lora["bytes"]` → M-HF-SIZE; `read_safetensors_header` fails → M-HF-NOT-ST; `lora_pair_count == 0` → M-HF-NO-PAIRS; else `None`.

### 2.3 `bin/seed-edit-lora` (new)

- **CL23 (CLI).** `#!/usr/bin/env python3`, git mode `100755`; docstring with the three usages below and this spec's path; `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, `sys.path.insert(0, WS)`; top-level imports `argparse`, `os`, `sys`, then `movie_ui_seedgen as seedgen`, `seed_lora_registry as registry` (each `# noqa: E402`). `main(argv=None)` returns the exit code; `sys.exit(main())` under `__main__`.
  ```
  bin/seed-edit-lora add (--repo OWNER/NAME [--file F] | --path P) [--family qwen21|qwen2511] [--id ID]
                         [--label TEXT] [--trigger TEXT] [--scale S] [--steps N]
  bin/seed-edit-lora list
  bin/seed-edit-lora remove ID
  ```
  argparse subparsers `add`, `list`, `remove` (`dest="command"`, `required=True`); every `add` option is `type=str`, default `None` (no argparse mutual exclusion, so R3/R4 give the shared texts). `--scale` is converted with `float()` (a `ValueError` → print `Error: ` + M-SCALE, exit 2) and `--steps` with `re.fullmatch(r"[0-9]+", ...)` then `int` (else `Error: ` + M-STEPS, exit 2); the module validates the ranges.
- **CL24 (output).** Every stdout line starts `seed-edit-lora: ` except the `list` table. Errors are `Error: <message>` on stderr.
  - `add`: each note line, then `added <id>: <repo>@<revision[:12]> <file> (<bytes/2**30 %.2f> GiB, <license>)` (hf) or `added <id>: <path> (<%.2f> GiB, sha256 <sha256[:12]>)` (local); exit 0. `RegistryError` → exit 1 for status 502, else 2 (D14).
  - `list`: header `ID\tFAMILY\tSOURCE\tWHERE\tSCALE\tTRIGGER\tINSTALLED`, then one tab-separated line per `seedgen.qwen_loras()` entry: id; family; `builtin`/`hf`/`local`; `<repo>@<revision[:12]> <file>` or the path; `"%g" % default_scale`; the trigger or `-`; `yes` or `no: <problem>` from `qwen_edit.lora_problem(lora, qwen_edit.qwen_hubs())[0]` (imported inside the function). Then `seed-edit-lora: registry <path> (<n> custom)`. Exit 0.
  - `remove`: `removed <id> from <registry path>; ` + (`the file stays at <path>` | `its downloaded file stays at <path>` | `it was never downloaded`); exit 0.

### 2.4 `qwen_edit.py`

- **CL25 (`lora_problem`).** Built-ins keep today's code path and texts exactly. New branches:
  ```
  def lora_problem(lora, hubs):
      if lora.get("source") == "local":
          import seed_lora_registry
          problem = seed_lora_registry.local_problem(lora)
          return (problem, None) if problem is not None else (None, lora["path"])
      path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
      if path is None:
          return (<today's text>, None)
      if lora.get("user"):
          import seed_lora_registry
          problem = seed_lora_registry.downloaded_problem(lora, path)
          if problem is not None:
              return problem, None
      return None, path
  ```
- **CL26 (`check_lora_args`).** `seedgen.qwen_lora_ids()` replaces `seedgen.QWEN_LORA_IDS` at `:380-381` (the `known:` list then includes custom ids). After the family check `:385-387` and before the scale parse: `if entry["backend"] == "diffusers": raise SelectionError("%s %s: " % (flag, lora_id) + seedgen.NO_LORAS_MSG % entry["id"])`.
- **CL27 (`install_problem`).** After the model check `:479-481`: `if loras and entry["backend"] == "diffusers": return seedgen.NO_LORAS_MSG % entry["id"], {}`. In the LoRA loop, `lora is None` → `return "LoRA %s is unavailable: %s" % (item["id"], seedgen.REMOVED_MSG), {}`.
- **CL28 (`run_jobs` trigger).** Right after `entry = seedgen.qwen_model(model_id)` `:510`: `jobs = [dict(job, prompt=seedgen.trigger_prompt(job["prompt"], loras)) for job in jobs]`. Every later use (`mflux_spec.json` `:567-569`, `assert_image_safe(..., prompt=job["prompt"])` `:593`, the diffusers spec `:535`) then sees the triggered text. The callers' job dicts are not mutated. The docstring gains one sentence naming CL28.
- **CL29 (docstring).** The module docstring's registry sentence says LoRAs come from `movie_ui_seedgen.qwen_loras()` (built-ins plus custom) and that a local custom LoRA is used at its recorded path.

### 2.5 `bin/seed-edit` and `bin/seed-edit-setup`

- **CL30 (probe).** `bin/seed-edit` `probe` iterates `seedgen.qwen_loras()` (`:259`). The docstring's LoRA sentence (`:17-18`) reads: `Each --lora ID=SCALE (a registry LoRA: uncensored, viggle-turbo or a custom user-* LoRA of bin/seed-edit-lora; 0 < SCALE <= 2) must be of the model's family; viggle-turbo sets 6 steps and scheduler viggle_turbo; a custom LoRA's trigger is prepended to the prompt.` Top-level imports unchanged (SGT34).
- **CL31 (`run.json` prompt).** `new_record` `:317` writes `"prompt": seedgen.trigger_prompt(opts["prompt"], opts["loras"])`. `run_qwen` keeps passing `opts["prompt"]` (CL28 applies the same prefix). Z-Image runs have `loras == []`, so their prompt is unchanged.
- **CL32 (setup selection and items).** `selection` uses `seedgen.qwen_lora_ids()` at `:277-278`. `items_of` skips a LoRA whose `source == "local"` (no item: nothing to download), and gives a user hf LoRA the built-in item shape plus `"user": True`. The disk check, the licence lines and the download are unchanged, so a user hf file is downloaded into the Z-Image hub at its pinned revision like a built-in.
- **CL33 (setup report and header check).**
  - `report` prints, after the file-item lines and before the `free on` line, for each selected local LoRA: `LoRA <id> (local) <path>: <%.2f> GiB` when `seed_lora_registry.local_problem` is `None`, else `LoRA <id> (local): <problem>`.
  - New `unusable(items, hub)`: `[(item["name"], problem)]` for every item with `item.get("user")` whose `pinned_file(...)` is present and whose `seed_lora_registry.downloaded_problem(seedgen.qwen_lora(item["name"]), path)` is not `None`.
  - New `finish(items, hub)`: prints `LoRA <name> is unusable: <problem>` per pair, then returns `fail(1, M-UNUSABLE % n)` when any, else 0. `main` returns `finish(items, hub)` after `report` in both the "nothing to do" branch and the final branch (after the orphan refusal, which keeps precedence).
  - `seed_lora_registry` is imported inside these functions. Top-level imports and the byte-copied functions are unchanged (SQT18). The docstring's `--lora` sentence adds: custom `user-*` ids are accepted; a local one is only reported.

### 2.6 `movie_ui_lib.py`

- **CL34 (probe tolerance, D9).** Add `USER_LORA_PREFIX = "user-"` and `PROBE_NOT_REPORTED` (Section 3). `_probe_qwen` keeps the models rule; for `"loras"`: `found` must be a dict; every id in `lora_ids` not starting with `USER_LORA_PREFIX` must be present; a key of `found` that is not in `lora_ids` and does not start with `USER_LORA_PREFIX` → `None`; `parsed[i] = entry(found[i])` for each `i in lora_ids` present, `{"ok": False, "reason": PROBE_NOT_REPORTED}` for an absent `user-` id; `None` in `parsed` → `None`. Extra `user-` keys are dropped. The signature of `seed_edit_check` is unchanged.

### 2.7 `movie_ui_server.py`

- **CL35 (routes).** Insert right after `("GET", r"/api/seeds/folders", ...)` `:110`:
  ```
  ("POST", r"/api/seed-loras", "h_seed_lora_add", "/api/seed-loras"),
  ("DELETE", r"/api/seed-loras/(user-[a-z0-9-]{1,24})", "h_seed_lora_remove", "/api/seed-loras/user-anything-to-real"),
  ```
  `len(ROUTES)` becomes 66; `GET /api/seed-loras` answers 405 by the existing route rule.
- **CL36 (accessors).** `seedgen.QWEN_LORA_IDS` becomes `seedgen.qwen_lora_ids()` at `:229`, `:787` and `:1851`.
- **CL37 (initial `run.json` prompt).** `_h_seed_run_create` `:1877` writes `"prompt": seedgen.trigger_prompt(clean["prompt"], clean["loras"])`; `fields["prompt"]` `:1884` stays `clean["prompt"]` (the tool applies the prefix itself, CL28/CL31, and D2 keeps it single).
- **CL38 (handlers and probe refresh).** New method `MovieUIServer.refresh_seed_edit()`: `seed_models, seed_detail = lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.qwen_lora_ids())`; `checked = lib.utc_now()`; under `cap_lock` set `self.capabilities["seed_edit"] = seedgen.capability(seed_models, seed_detail, checked)`. `refresh_capabilities` is unchanged except CL36.
  Two handlers, placed after `_h_seed_folders` `:1994-2013`, with `MovieUIHandler.h_seed_lora_add = _h_seed_lora_add` and `MovieUIHandler.h_seed_lora_remove = _h_seed_lora_remove` after `:2021`:
  ```
  def _h_seed_lora_add(self, groups, query, body):
      """Custom edit LoRAs spec CL38: register a custom Qwen edit LoRA, then re-probe."""
      import seed_lora_registry as registry
      try:
          entry, notes = registry.add(body, None)
      except registry.RegistryError as e:
          raise ApiError(e.status, str(e))
      self.server.refresh_seed_edit()
      view = [l for l in seedgen.registry_view()["loras"] if l["id"] == entry["id"]][0]
      return 201, {"lora": view, "notes": notes, "seed_edit": self.server.capability_snapshot()["seed_edit"]}


  def _h_seed_lora_remove(self, groups, query, body):
      """Custom edit LoRAs spec CL38: drop a custom LoRA from the registry (never a file), then re-probe."""
      import seed_lora_registry as registry
      if body not in (None, {}):
          raise ApiError(400, M-DELETE-BODY)
      try:
          entry, kept = registry.remove(groups[0])
      except registry.RegistryError as e:
          raise ApiError(e.status, str(e))
      self.server.refresh_seed_edit()
      return 200, {"removed": entry["id"], "kept": kept, "seed_edit": self.server.capability_snapshot()["seed_edit"]}
  ```
  (M-DELETE-BODY is the Section 3 constant, defined in the server as `SEED_LORA_DELETE_BODY`.) The handler blocks for the HF call (at most 30 s), a local sha256 (minutes for 8 GiB on an HDD) and one probe (at most `LIGHT_TIMEOUT` 60 s); the threaded server keeps other requests flowing. A CLI add while the server runs is seen by every server-side check at once (CL5) and by the page after its Refresh button (`loadHost(true)`).
- **CL39 (environment).** In `main`, right before `stop = start_threads(server)` `:720`: `os.environ[seedgen.USER_LORAS_ENV] = seedgen.user_loras_path()` (D8).

### 2.8 The page (`static/movie-ui/app.js`; `index.html` and `app.css` unchanged)

- **CL40 (the form).** New `customLoraForm(prefix)` returns a `<details id="<prefix>-custom" class="se-custom">` built with `el()`; `qwenPicker`'s `p.render` appends it to `node("-qwen-box")` once (when `node("-custom")` is null) right after the registry check `:2029-2033`. Children, in order:
  1. `<summary>` text `Add custom LoRA`;
  2. `<label>Source <select id="<prefix>-custom-source">` with options `hf` (`Hugging Face repo`) and `local` (`Local file`);
  3. `<label>Repo <input id="<prefix>-custom-repo" type="text" size="40" placeholder="OWNER/NAME">` and `<label>File <input id="<prefix>-custom-file" type="text" size="40" placeholder="only when the repo has several .safetensors files">`, shown only for `hf`;
  4. `<label>Path <input id="<prefix>-custom-path" type="text" size="50" placeholder="/absolute/path/lora.safetensors">`, shown only for `local`;
  5. `<label>Family <select id="<prefix>-custom-family">` with options `""` (`from the model card`), `qwen2511` (`Qwen-Image-Edit-2511`), `qwen21` (`Qwen-Image-2.1`);
  6. `<label>Trigger <input id="<prefix>-custom-trigger" type="text" size="40" maxlength="200">`;
  7. `<label>Strength <input id="<prefix>-custom-scale" type="number" min="0" max="2" step="0.05" value="1">`;
  8. `<label>Steps <input id="<prefix>-custom-steps" type="number" min="1" max="100" step="1" placeholder="model default">`;
  9. `<button id="<prefix>-custom-add" type="button">` text `Add`, and `<span id="<prefix>-custom-status" class="muted">`.
  `input` and `change` listeners on the `<details>` call `event.stopPropagation()`, so typing never fires the picker's `p.listen` handler (which would re-run Compose's preview). No `https?://`, no inline handlers, no `style=` (QET38).
- **CL41 (the body).** New pure function `customLoraBody(v)` (`v` holds the eight form values as strings) returns the POST body: `hf` → `{repo: v.repo.trim()}` plus `file` when `v.file.trim()` is non-empty; `local` → `{path: v.path.trim()}`; then `family` when `v.family` is non-empty; `trigger` when `v.trigger.trim()` is non-empty (trimmed); `scale` when `v.scale.trim()` is non-empty, as `Number(v.scale)` when finite, else the raw string (so the server answers M-SCALE instead of reading `null`); `steps` the same way. The Add click: disable the button, status `adding…` (`adding… (hashing a large local file can take minutes)` for `local`), `api("POST", "/api/seed-loras", customLoraBody(...))`; on 201 set `S.host.capabilities.seed_edit = res.data.seed_edit` (when `S.host`), call `renderBadges()`, and set the status to `added <id>` followed by `; ` + each note; else the status is `res.data.error` (or `request failed (HTTP <status>)`); re-enable the button.
- **CL42 (rows).** In `p.render`:
  - the rows key `:2075` starts `entry.family + "|" + entry.backend + "|"` (switching `qwen2511-q4` ↔ `qwen2511-bf16` rebuilds the rows; `return [l.id, loraOk(l.id), loraNote(l)];` stays verbatim);
  - for `entry.family === "qwen2511"` the Lightning span `:2080` stays; then, when `entry.backend === "diffusers"` and `loras.length`, one `<span class="muted">` with M-UI-BF16 and no rows; else the rows below;
  - rows are built for every family-matching LoRA (no longer only for non-qwen2511); a LoRA with no state entry gets `state.loras[l.id] = {checked: false, scale: String(l.default_scale)}` before `const saved = state.loras[l.id];` `:2085`;
  - a row of a LoRA with `l.user` adds, after its label text, `" "` and `el("span", {cls: "chip", text: "custom"})`, and after the note a `<button type="button" class="se-lora-remove">` text `Remove`; its click runs `askConfirm("Remove custom LoRA " + l.label + " (" + l.id + ") from the registry? Its file is not deleted.")`, then `api("DELETE", "/api/seed-loras/" + enc(l.id))`; on 200 it updates the capability as in CL41 and sets `node("-custom-status")` to `removed <id>` plus `; the file stays at <kept>` when `kept`; else to the error.
- **CL43 (notes and steps).** `loraNote` `:2070-2074`, ok branch: `l.license + (l.steps ? "; " + l.steps + " steps" + (l.scheduler ? ", scheduler " + l.scheduler : "") : "") + (l.trigger ? "; trigger: " + l.trigger : "")`; the unavailable line stays verbatim. The steps line `:2101` becomes `turbo ? turbo.steps + (turbo.user ? " steps (set by " + turbo.label + ")" : " steps (turbo)")` (the literal `" steps (turbo)"` stays, QWEN_JS_TEXTS).
- **CL44 (scope).** No other page code changes. The six pickers (`se`, `lo-cq`, `lo-rq`, `ch-cq`, `ch-rq`, `c-sq`, `app.js:46-51`) each get the form; their `selection()` already sends whatever rows are checked.

### 2.9 Records, removal, forks

- **CL45 (old records).** `record_settings` returns a record's `qwen_model`, `loras`, `steps` and `scheduler` as recorded (no registry lookup), so `GET /api/seeds/runs` and `GET /api/seeds/runs/<run>` show a run whose LoRA was removed, with its recorded items (`seedModelText` shows `<id> <scale>`). `qwen_edit.selection_of` and `generator_text` work on such a record (D5).
- **CL46 (removed while queued or running).** A running child is unaffected (its `mflux_spec.json` holds the paths). A later `run_jobs` call in the same `bin/ltx-movie` run (seed context, frame mode) refuses with `LoRA <id> is unavailable: ` + `REMOVED_MSG`, which the phase reports as a failed edit. A queued Seeds job exits 2 with `Error: --lora: unknown LoRA <id>; known: ...` and `run.json` state `failed`. A queued `bin/ltx-movie` job exits 2 with `Error: --seed-edit-lora: unknown LoRA <id>; known: ...`. A Characters/Locations regenerate whose `character.json`/`location.json` `edit` names a removed id fails in `run_jobs` with `Unavailable` (reported through `DatasetError`, `character_dataset.py:1884-1885`). A local file moved or resized: M-LOCAL-MISSING / M-LOCAL-CHANGED from the probe and `install_problem`.
- **CL47 (batch forks).** `movie_ui_batch.py` is unchanged. A `render`-level fork copies `seed_edits.json` (`COPY_FILES` `:52-53`); its argv carries the same `--seed-edit-lora`, so its panels are reused exactly when the LoRA is still registered with the same pin and trigger (D4); a removed LoRA makes the fork exit 2 as in CL46. A changed `seed_edit_loras` is a `stills`-level fork, which copies no `seed_edits.json`.

### 2.10 Hygiene and gates

- **CL48 (py 3.9).** New and changed code runs on Python 3.9 and 3.13: no `match`, no `X | Y` types, no `zip(strict=)`, no parenthesized context managers, `%` formatting.
- **CL49 (public repo).** No token, no `Authorization` header and no user path (`/Users/...`) in code or tests; tests use `tmp_path`, synthetic safetensors files and the public metadata of Section 0.1.
- **CL50 (pinned files).** The implementation changes no `PIPELINE_FILES` member (CLK7). `test_mut26`'s BASELINE stays `ca958ca...`.
- **CL51 (one network function).** `HTTPSConnection` occurs once in the workspace (CL17).
- **CL52 (isolation).** E1 and E2.

---

## 3. Messages and text (exact)

### 3.1 Constants

| Name | Text |
|---|---|
| `NO_LORAS_MSG` (seedgen) | `%s runs without LoRAs (its diffusers child loads only the built-in Lightning LoRA); use qwen2511-q4` |
| `REMOVED_MSG` (seedgen) | `it is not in the Qwen edit LoRA registry (removed?); add it again with bin/seed-edit-lora add, or choose other LoRAs` |
| `USER_LORAS_WARNING` (seedgen) | `seed-edit: ignoring %s: %s; only the built-in Qwen edit LoRAs are available` |
| `PROBE_NOT_REPORTED` (lib) | `not reported by this workspace's bin/seed-edit --probe (it may predate custom LoRAs)` |
| M-UI-BF16 (app.js) | `qwen2511-bf16 runs without LoRAs; choose qwen2511-q4 to use a Qwen-Image-Edit-2511 LoRA` |
| M-DELETE-BODY (server `SEED_LORA_DELETE_BODY`) | `DELETE /api/seed-loras/<id> takes no body` |

### 3.2 Request rules (`seed_lora_registry.add`, first failure wins, all status 400)

| # | Rule | Message |
|---|---|---|
| R1 | `request` is a dict whose keys are all in `FIELDS` (the first unknown key in sorted order) | `unknown field %s; allowed: repo, file, path, family, id, label, trigger, scale, steps` |
| R2 | `repo, file, path, family, id, label, trigger` are `str` when present | `%s must be a string` |
| R3 | exactly one of `repo`, `path` | `give exactly one of repo and path` |
| R4 | `file` only with `repo` | `file is only for repo` |
| R5 | `repo` matches `HF_URL_RE` (normalized to group 1) or `HF_REPO_RE`, and has no `..` or `--` | `repo must be OWNER/NAME (letters, digits, '.', '_' or '-') or https://huggingface.co/OWNER/NAME (got %s)` |
| R6 | `file` (when given): lower-case ends with `.safetensors` (else M-NOT-SAFETENSORS `% file`), then `HF_FILE_RE` and no `..` segment | `file must be a relative path of letters, digits, spaces and . _ - + ( ), with no '..' (got %s)` |
| R7 | `family` in `QWEN_FAMILIES` when present; required for `path` | `family must be qwen21 or qwen2511 (got %s)`; `family is required for a local file (qwen21 or qwen2511)` |
| R8 | `id` matches `USER_ID_RE` | `id must be user- followed by 1 to 24 lowercase letters, digits or '-' (got %s)` |
| R9 | `label`: 1 to 80 characters, none below `\x20`, no `\x7f` | `label must be 1 to 80 characters with no control characters` |
| R10 | `valid_trigger(trigger)` | `trigger must be 1 to 200 characters: letters, digits, spaces and , . ; : ' ! ? ( ) & / -, starting with a letter or digit, with no double or trailing space` |
| R11 | `scale`: number, not bool, `0 < scale <= 2` | M-SCALE `scale must be a number above 0 and at most 2` |
| R12 | `steps`: int, not bool, 1 to 100 | M-STEPS `steps must be an integer from 1 to 100` |

### 3.3 Hugging Face and file messages

| Name | Status | Text |
|---|---|---|
| M-HF-UNREACHABLE | 502 | `cannot reach the Hugging Face API (huggingface.co): %s: %s` (type name, error); when the error is an `ssl.SSLCertVerificationError` append `; this Python has no CA certificates (run its Install Certificates.command)` |
| M-HF-NOTFOUND | 400 | `repo %s is not on the Hugging Face Hub, or it is private (only public repos can be added; no token is sent)` |
| M-HF-MOVED | 400 | `repo %s has moved (%s); add it by its new name` |
| M-HF-STATUS | 502 | `the Hugging Face API answered HTTP %d for %s` |
| M-HF-BIG | 502 | `the Hugging Face API answer for %s is larger than 32 MiB` |
| M-HF-JSON | 502 | `the Hugging Face API answered %s with invalid JSON` |
| H1 | 502 | info not a dict, `sha` not 40 hex, or `siblings` not a list: `the Hugging Face API returned no model, commit sha or file list for %s` |
| H2 | 400 | `info.get("disabled") is True`: `repo %s is disabled on the Hugging Face Hub` |
| H3 | 400 | `info.get("gated") not in (False, None)`: `repo %s is gated (%s); seed-edit downloads are unauthenticated, so it cannot be installed` |
| H4 | 400 | `file` given and not an `rfilename`: `file %s is not in %s@%s; its .safetensors files: %s` (all `.safetensors` rfilenames, at most 10 then `and N more`, or `none`) |
| H5 | 400 | no `file`, no root `.safetensors` (rfilename without `/`, lower-case suffix): `repo %s@%s has no .safetensors file at its top level` + (`; its .safetensors files in folders: %s; pass file` when any) + (`; it has %s, which are refused: pickle formats can run code when loaded` when an rfilename ends with a `PICKLE_EXTS` member) |
| H6 | 400 | several root `.safetensors`: `repo %s@%s has %d .safetensors files at its top level (%s); pass file to choose one` |
| H7 | 400 | the chosen rfilename fails R6: `the repo's file %s has characters this tool does not accept, so it cannot be added` |
| H8 | 502 / 400 | sibling `size` not an int >= 1: 502 `the Hugging Face API reported no size for %s`; above 8 GiB: M-TOO-BIG |
| H9 | 400 | family: `cardData.base_model` (a str, or a list of str) mapped by `BASE_MODEL_FAMILIES`; one family → inferred; none and no `family` → `the model card's base_model (%s) is not Qwen/Qwen-Image-Edit-2511 or Qwen/Qwen-Image-2.1; pass family (qwen21 or qwen2511)` (`%s` is the value or `none`); two families and no `family` → `the model card's base_model lists both families; pass family`. Licence: `cardData.license` str → it; a list of str → joined `, `; `"other"` with a str `license_name` → `other (<name>)`; else `NO_LICENSE`; cut to 200 |
| M-NOT-SAFETENSORS | 400 | `%s is not a .safetensors file; other formats are refused (the pickle formats .bin, .pt, .pth and .ckpt can run code when loaded)` |
| M-PATH-ABS | 400 | `path must be an absolute path or start with ~ (got %s)` |
| M-NOT-EXIST | 400 | `%s does not exist` |
| M-NOT-REGULAR | 400 | `%s is not a regular file` |
| M-TOO-BIG | 400 | `%s is %.1f GiB; custom LoRAs are limited to 8 GiB` |
| M-NOT-ST-HEADER | 400 | `%s is not a safetensors file (its header does not parse)` |
| M-NO-PAIRS | 400 | `%s has no LoRA weight pairs (lora_A/lora_B, lora_down/lora_up or lora.down/lora.up) in its safetensors header, so mflux would apply nothing` |
| M-ID-TAKEN | 409 | `LoRA id %s already exists; choose another id or remove it first` |
| M-DUPLICATE | 409 | `%s is already in the registry as %s` (`<repo>:<file>` or the path; the id) |
| M-UNREADABLE | 409 | `the custom LoRA registry %s is unreadable: %s; fix or delete it, then retry` |
| M-BUILTIN | 400 | `%s is a built-in LoRA and cannot be removed` |
| M-UNKNOWN | 404 | `unknown custom LoRA %s (custom LoRAs: %s)` (ids joined `, `, or `none`) |
| M-LOCAL-MISSING | — | `%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after bin/seed-edit-lora remove %s)` (path, id) |
| M-LOCAL-CHANGED | — | `%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run bin/seed-edit-lora add after bin/seed-edit-lora remove %s)` |
| M-HF-SIZE | — | `%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora %s again)` |
| M-HF-NOT-ST | — | `%s is not a safetensors file (bin/seed-edit-lora remove %s)` |
| M-HF-NO-PAIRS | — | `%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing (bin/seed-edit-lora remove %s)` |
| M-UNUSABLE (setup) | — | `%d custom LoRA file(s) failed the safetensors check (listed above); remove them with bin/seed-edit-lora remove ID` |

### 3.4 Notes (returned by `add`, printed by the CLI with the `seed-edit-lora: ` prefix)

| Name | Text |
|---|---|
| N-FAMILY | `family %s (the model card's base_model is %s)` when inferred; `family %s (given)` when `family` was given |
| N-FAMILY-CONFLICT | `warning: family %s was given, but the model card's base_model %s means %s` |
| N-TRIGGER | `the model card's instance_prompt is %r; pass trigger to prepend it to every edit prompt of this LoRA` |
| N-STEPS | `qwen2511-q4 always loads the Lightning 8-step LoRA; %d steps with Lightning are untested` |
| N-DOWNLOAD | `download it with: bin/seed-edit-setup --lora %s` |
| N-IN-PLACE | `the file is used in place: moving, replacing or resizing it makes this LoRA unavailable` |

---

## 4. What changes for existing runs and records

- Built-in selections: `qwen_settings`, `registry_order`, `generator_text`, every reuse key and every record are byte-identical (D15, CL10). A run with only built-ins has no trigger, so every prompt is unchanged.
- `registry_view()` gains `user`, `source`, `trigger` per LoRA (the page ignores unknown keys).
- A selection naming a custom LoRA records the D4 item; the untriggered builder prompt stays the reuse key in `seed_edit.json`, `seed_edits.json`, `seed_context_edits.json` and `cast_ref_edits.json`, while `run.json` and `mflux_spec.json` hold the triggered text.
- `qwen2511-bf16` with any LoRA is refused where it used to be impossible (no qwen2511 LoRA existed).
- A `qwen2511` LoRA cannot be used for cast refs: `qwen2511-q4` refuses several references (`MULTI_REFERENCE_REFUSED`, `qwen_edit.py:54-58`) and `qwen2511-bf16` refuses LoRAs.

---

## 5. Tests

### 5.1 New tests

`tests/test_seed_lora_registry.py` (Task 1) loads `bin/seed-edit-lora` and `bin/seed-edit-setup` with `importlib.machinery.SourceFileLoader` + `importlib.util.module_from_spec` + `exec_module` (never `load_module(`), sets `SEED_EDIT_USER_LORAS` to `tmp_path/"r"/"user_loras.json"`, and builds synthetic safetensors files as `struct.pack("<Q", len(h)) + h + b"\0" * 16` with `h = json.dumps(header).encode()`. `INFO` is the recorded API answer of Section 0.1 (sha, card, siblings with sizes) as a literal; `fetch_model_info` is always patched.

| Test | Covers | Asserts |
|---|---|---|
| CL-T1 | CL1, CL6 | no file: `qwen_lora_ids() == ("uncensored", "viggle-turbo") == BUILTIN_QWEN_LORA_IDS`; `[dict(l) for l in BUILTIN_QWEN_LORAS]` equals today's two dicts; `hasattr(seedgen, "QWEN_LORAS") is False` and the same for `QWEN_LORA_IDS` |
| CL-T2 | CL5, CL6 | a valid file with two entries (hf then local) → `qwen_lora_ids()` is built-ins then those two in file order; rewriting the file (atomic replace) with the order swapped is seen on the next call; a missing file again → built-ins only |
| CL-T3 | CL4, CL5 | each of: invalid JSON, wrong schema, an unknown key, a bad id, a built-in id, a repeated id, `default_on: true`, a bad trigger → built-ins only, exactly one stderr line starting `seed-edit: ignoring <path>: ` per file state (two calls, one line), and no exception from `qwen_selection`, `default_loras`, `registry_view` |
| CL-T4 | CL3, R10 | `valid_trigger`: accepts `transform the image to realistic photograph`, `a, b. c; d: 'e'! f? (g) & h/i-j`, 200 characters; refuses `""`, 201 characters, leading space, leading `-`, trailing space, double space, `"`, `\\`, `\n`, `é`, `<b>` |
| CL-T5 | CL21, H5, H9, CL22, N-* | `add({"repo": "WarmBloodAban/Anything_to_Real_Characters_2511", "trigger": "transform the image to realistic photograph"}, cwd)` with `INFO` writes exactly `{"id": "user-anything-to-real-charact", "label": "WarmBloodAban/Anything_to_Real_Characters_2511", "family": "qwen2511", "source": "hf", "repo": ..., "revision": "e8f98cb5f976c9431f2bef47bd1a97caa1ee4ce7", "file": "AnythingtoRealCharacters2511_20.safetensors", "bytes": 354082336, "default_on": false, "default_scale": 1.0, "license": "apache-2.0", "steps": null, "scheduler": null, "trigger": "transform the image to realistic photograph", "user": true}` and notes `[N-FAMILY, N-DOWNLOAD]`; the same add of the URL form with `--id user-to-real` (after a remove) works; a second add with another `id` → 409 M-DUPLICATE; without `trigger` the notes include N-TRIGGER with the instance prompt |
| CL-T6 | CL17, CL49, CL51 | `fetch_model_info` with a fake `http.client.HTTPSConnection` (patched on the module's `http.client`): request line `GET /api/models/o/n?blobs=true`, headers exactly `User-Agent` and `Accept` (no `Authorization` even with `HF_TOKEN` set); status mapping 200/301/302/307/308/401/404/500, oversize body, bad JSON, `OSError`, `ssl.SSLCertVerificationError` (the certificates sentence) → the Section 3.3 statuses and texts; source scan: `HTTPSConnection` occurs once in the workspace (`git grep -c`) |
| CL-T7 | R1-R12 | one case per row of Section 3.2, each the exact message and 400, and `fetch_model_info` not called |
| CL-T8 | H1-H9 | one case per row (gated, disabled, missing sha, file not in repo, no root file with folder files and a `.bin`, several roots, a bad rfilename, no size, 9 GiB, unknown base model, both families, family given that disagrees → N-FAMILY-CONFLICT, licence forms) |
| CL-T9 | CL22 | `slug` examples; `default_id` with `user-anything-to-real-charact` taken → `user-anything-to-real-chara-2`; ten taken → `-10` cut correctly; an empty slug → `user-lora` |
| CL-T10 | CL18, CL19, CL21 local | a synthetic file with `X.lora_A.default.weight`/`X.lora_B.default.weight` → added with the right sha256 (`hashlib`), bytes, `path == os.path.abspath(given)`, `file` basename, `license == "not stated (local file)"`; `~` expansion (HOME under tmp), a relative path with `base_dir`, a relative path with `base_dir=None` → M-PATH-ABS; a symlink `snap/x.safetensors` → `blobs/abc` keeps the link path (D7); missing, a directory, `.ckpt`, 0 bytes (header fails), invalid header, a header with only `.lora_A.weight` → each exact message; 9 GiB via a patched `os.path.getsize` → M-TOO-BIG; no `family` → R7 |
| CL-T11 | CL19 | `lora_pair_count` on the four forms (`.lora_A.weight`, `.lora_A.default.weight`, `.lora_down.weight`, `.lora.down.weight`) and on unpaired and LoKr-style keys (`lokr_w1`) → 0 |
| CL-T12 | CL22a, CL24 | `remove`: local prints the kept path; hf with a pinned file present in the Z-Image hub prints it; never downloaded → `it was never downloaded`; `uncensored` → exit 2 M-BUILTIN; unknown → exit 2 M-UNKNOWN; the files still exist after every remove |
| CL-T13 | CL24 | `main(["list"])` output: header, the two built-ins (`builtin`, `no: ... is not in ...`), an hf entry `hf  <repo>@e8f98cb5f976 <file>`, a local entry with `yes`; final registry line |
| CL-T14 | CL22b, CL25 | `qwen_edit.lora_problem`: local present → `(None, path)`; deleted → M-LOCAL-MISSING; truncated → M-LOCAL-CHANGED; hf user pinned file with wrong size → M-HF-SIZE; with no pairs → M-HF-NO-PAIRS; built-ins → today's texts (CL-T14 reuses `test_seed_edit_tool.py`'s `pinned_cache` shape, re-implemented locally) |
| CL-T15 | CL11, CL28 | `trigger_prompt` table (two triggers in registry order, skip when present in any case, duplicate triggers, empty prompt → prefix alone, unknown id skipped, built-in → unchanged); `run_jobs` with a fake mflux child (the `tests/test_qwen_edit.py` pattern) and a custom LoRA: `mflux_spec.json` job prompts are triggered, the patched `content_safety.assert_image_safe` receives the triggered prompt, the caller's job dicts are unchanged, `lora_paths` ends with the local path |
| CL-T16 | CL31, CL37 | `bin/seed-edit` run (the `test_seed_edit_tool.py` fake-child pattern) with `--lora user-x=1.0`: `run.json` `"prompt"` is the triggered text, the child spec's prompts are the same text once (not doubled) |
| CL-T17 | CL10, D4, D5, D13 | `qwen_settings` items for a built-in (unchanged), an hf user entry, a local user entry (no `repo`, no `path`), a removed id (`removed: true`); a user entry with `steps: 30` on `qwen21-q4` → steps 30, scheduler `linear`; on `qwen2511-q4` → steps 30, scheduler `None`; `viggle-turbo` unchanged; `generator_text` with a removed id lists `<id>@1` |
| CL-T18 | CL13, CL26, CL27 | a qwen2511 user LoRA on `qwen2511-bf16`: `qwen_selection` → `LoRA user-x: qwen2511-bf16 runs without LoRAs (...); use qwen2511-q4`; `check_lora_args(..., "--seed-edit-lora")` → `--seed-edit-lora user-x: qwen2511-bf16 runs without ...`; `install_problem("qwen2511-bf16", [...])` → `NO_LORAS_MSG % "qwen2511-bf16"`; the same LoRA on `qwen2511-q4` passes; a qwen21 LoRA on bf16 keeps the family text |
| CL-T19 | CL8, CL27, CL46 | after a remove: `registry_order` puts the removed id last; `install_problem` → `LoRA user-x is unavailable: it is not in the Qwen edit LoRA registry (removed?); ...`; `run_jobs` raises `Unavailable` with it; `check_lora_args` → `--lora: unknown LoRA user-x; known: uncensored, viggle-turbo` |
| CL-T20 | CL30, CL34 | `bin/seed-edit --probe` (in-process `probe()`) lists the custom ids with their verdicts; `lib._probe_qwen` (through `seed_edit_check` with a stub) fills a missing `user-` id with `PROBE_NOT_REPORTED`, drops an unknown `user-` key, still refuses a missing built-in id and an extra `extra` key |
| CL-T21 | CL32, CL33 | `bin/seed-edit-setup` with every process patched (the SQT11-SQT13 pattern): `--lora user-hf` downloads one file item at the pinned revision into the Z-Image hub and the disk check counts its bytes; `--lora user-local` makes no item and the report prints the local line; a downloaded user file with no pairs → `LoRA user-hf is unusable: ...` and exit 1 with M-UNUSABLE (also in the "nothing to do" branch); `unknown --lora` still lists the known ids |
| CL-T22 | CL20 | concurrency: two `add` calls from two threads with explicit ids → both entries present; a corrupt registry file → `add` and `remove` refuse with 409 M-UNREADABLE and leave the file byte-identical; the written file is mode 0600, indent 2, schema first |
| CL-T23 | CL5 | the reader's cache: `user_loras()` called twice with no file change reads the file once (patched `open` counter) |
| CL-T24 | CL48, D16 | `py_compile` of `seed_lora_registry.py`, `bin/seed-edit-lora`, `movie_ui_seedgen.py`, `qwen_edit.py`, `bin/seed-edit`, `bin/seed-edit-setup`, `movie_ui_lib.py`, `movie_ui_server.py`, both new test files and `tests/conftest.py` with `/usr/bin/python3` (skipped when absent) and `sys.executable` (`PYTHONPYCACHEPREFIX` under `tmp_path`); the `test_mut25` forbidden-pattern list applied to the two new source files and both new test files; `seed_lora_registry.py`'s top-level imports equal CL15's list; `bin/seed-edit-lora`'s equal CL23's; `git ls-files -s bin/seed-edit-lora` shows mode `100755` (skipped outside git) |

`tests/test_movie_ui_seed_loras.py` (Task 2) uses the `env` fixture pattern of `tests/test_movie_ui_seedgen.py:522-534` (its own copies of `stub_seed_edit` and `clean_env`, with E2's rule), and patches `seed_lora_registry.fetch_model_info`.

| Test | Covers | Asserts |
|---|---|---|
| CL-T25 | CL35 | both routes in `ROUTES` right after `/api/seeds/folders`, samples match their regexes, handlers bound, 401 without the token, `GET /api/seed-loras` 405, `DELETE /api/seed-loras/uncensored` 404 `not found`, `len(ROUTES) == 66` |
| CL-T26 | CL38, R1-R12 | POST bodies: an unknown key, `scale: "x"`, `scale: true`, `steps: 2.5`, both repo and path, a relative path → 400 with the exact Section 3 texts (the same strings CL-T7 asserts for the module) |
| CL-T27 | CL38 | POST hf (mocked) → 201 with `lora` (the registry_view item: `user: true`, `source: "hf"`, the trigger, `setup` text), `notes`, and `seed_edit.registry.loras` including it; the stub probe ran again (its call counter) and `seed_edit.models.qwen.loras["user-..."]` is `PROBE_NOT_REPORTED` when the stub omits it |
| CL-T28 | CL38 | POST local → 201; DELETE → 200 `{"removed", "kept": <path>, "seed_edit"}` and the registry no longer lists it; DELETE again → 404 M-UNKNOWN; DELETE with a body → 400 M-DELETE-BODY |
| CL-T29 | CL13, CL36 | `POST /api/seeds/runs` with `qwen_model: "qwen2511-bf16"` and a qwen2511 custom LoRA → 400 with the CL13 text; with `qwen2511-q4` → 201 and `run.json` `"prompt"` triggered (CL37), while the job argv's `--prompt` is the untriggered text |
| CL-T30 | CL45 | a run whose `run.json` records an hf and a local custom item, then both removed: `GET /api/seeds/runs` and `GET /api/seeds/runs/<run>` → 200 with the recorded `loras` unchanged |
| CL-T31 | CL39 | `main` sets `SEED_EDIT_USER_LORAS` before `start_threads` (patched `make_server`, `start_threads` and `serve_forever`; the env value seen inside the patched `start_threads` equals `seedgen.user_loras_path()`) |
| CL-T32 | CL40-CL43 | `app.js` text pins: `function customLoraForm(prefix) {`, `function customLoraBody(v) {`, `"/api/seed-loras"`, `"Add custom LoRA"`, M-UI-BF16, `" steps (set by "`, `el("span", {cls: "chip", text: "custom"})`, `askConfirm("Remove custom LoRA "`, `entry.family + "|" + entry.backend + "|"`, `event.stopPropagation()`; QET38's forbidden patterns still absent; `node --check` passes (skipped without node) |
| CL-T33 | CL41 | with node: `customLoraBody` extracted from `app.js` (the SQT22 extraction pattern) returns the exact bodies for hf with and without file, local, empty family/trigger/steps omitted, `scale: "abc"` kept as the string, `steps: "30"` → 30 |
| CL-T34 | CL47 | `movie_ui_batch.COPY_FILES` and `FIELD_LEVELS` are unchanged (literal) and `git diff --quiet 20cee82 HEAD -- movie_ui_batch.py` (skipped outside git) |

### 5.2 Existing tests and fixtures edited (all still pass; none is removed)

- **E1.** `tests/conftest.py`: a new autouse fixture after `lora_catalog_isolation`:
  ```
  @pytest.fixture(autouse=True)
  def seed_lora_isolation(monkeypatch, tmp_path):
      """Custom edit LoRAs spec CL52: every test sees no custom Qwen edit LoRA unless it writes one."""
      path = str(tmp_path / "seed_lora_isolation" / "user_loras.json")
      monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
      return path
  ```
- **E2.** The nine helpers of Section 0.1: `if key.startswith("SEED_EDIT_"):` becomes `if key.startswith("SEED_EDIT_") and key != "SEED_EDIT_USER_LORAS":`.
- **E3.** `tests/test_seed_edit_tool.py`: `:1142` `seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo")` and `seedgen.BUILTIN_QWEN_LORA_IDS == (...)`; `:1144` `BUILTIN_QWEN_LORAS`; `:1149`, `:1151`, `:1551` `BUILTIN_QWEN_LORAS`.
- **E4.** `tests/test_movie_ui_seedgen.py`: `:140` and `:370` `seedgen.BUILTIN_QWEN_LORA_IDS`; `:344-358` each LoRA dict of the `registry_view` literal gains `"user": False, "source": "builtin", "trigger": None`; `:208-209` the import list becomes `["json", "movie_ui_lib", "os", "re", "secrets", "sys", "threading", "time"]`.
- **E5.** `tests/test_movie_ui_qwen_edit.py:46` `seedgen.BUILTIN_QWEN_LORA_IDS`.
- **E6.** `len(srv.ROUTES) == 64` → `66` in `tests/test_movie_ui_http.py:44`, `tests/test_location_ui.py:66`, `tests/test_movie_ui_seedfolder.py:923`, `:960`, `tests/test_movie_ui_seedgen.py:627`.
- **E7.** No other existing assertion changes. If a further existing test fails, the implementer stops and reports it (it is a spec gap, not a test to adjust).

---

## 6. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

- **CL-LV0.** Pull the branch; `python3 -m pytest -q tests/test_seed_lora_registry.py tests/test_movie_ui_seed_loras.py` passes.
- **CL-LV1 (hf add).** `bin/seed-edit-lora add --repo https://huggingface.co/WarmBloodAban/Anything_to_Real_Characters_2511 --id user-to-real --trigger "transform the image to realistic photograph"` prints `family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)`, `download it with: bin/seed-edit-setup --lora user-to-real`, and `added user-to-real: WarmBloodAban/Anything_to_Real_Characters_2511@e8f98cb5f976 AnythingtoRealCharacters2511_20.safetensors (0.33 GiB, apache-2.0)` (the revision is whatever `main` is that day; record it). Then `bin/seed-edit-setup --lora user-to-real` downloads about 0.33 GiB, passes the header check and prints `probe: user-to-real ok`.
- **CL-LV2 (local add).** `bin/seed-edit-lora add --path ~/hf_home/hub/models--WarmBloodAban--Anything_to_Real_Characters_2511/snapshots/<rev>/AnythingtoRealCharacters2511_20.safetensors --family qwen2511 --id user-to-real-local --trigger "transform the image to realistic photograph"`; `bin/seed-edit-lora list` shows both with `yes`.
- **CL-LV3 (Seeds).** On the Seeds tab, an anime/stylised character source, model `qwen2511-q4`, check `user-to-real` at strength 1, prompt `keep the pose, clothing and background`, 4 candidates, fixed seed; repeat with the LoRA unchecked at the same seed. Judge realism (KPI CLK8). Check `run.json` `"prompt"` starts with the trigger and `content_safety.log` shows it.
- **CL-LV4 (the Lightning question).** Same source and seed at strengths 0.7, 1.0 and 1.5; then `bin/seed-edit-lora remove user-to-real`, re-add with `--steps 30` (N-STEPS is printed), run again. Record: does the LoRA work under Lightning at 8 steps, and does 30 steps with Lightning help or over-bake? The author's 30 steps / CFG 4 without Lightning cannot be run here (Section 0.4).
- **CL-LV5 (shots).** `bin/ltx-movie "<narrative>" --shots --seed-image <anime still> --seed-edit-model qwen2511-q4 --seed-edit-lora user-to-real=1.0 ...` (or Compose with the picker): every panel still is photoreal; `seed_edits.json` items carry `revision` and `trigger`; the `mflux_spec.json` prompts start with the trigger; a rerun reuses every panel.
- **CL-LV6 (bf16 refusal).** Choose `qwen2511-bf16` in Compose: the picker shows M-UI-BF16 and no rows; `bin/seed-edit --model qwen --qwen-model qwen2511-bf16 --lora user-to-real=1 ...` exits 2 with the CL26 text.
- **CL-LV7 (page add/remove).** Add the local file from the Characters create picker's "Add custom LoRA" form; it appears in all six pickers with the `custom` chip; remove it from the Compose picker after the confirm dialog; the file stays on disk; an old Seeds run with it still opens.
- **CL-LV8 (moved file).** Rename the local file: the picker shows `unavailable — <path> is missing or not a regular file (...)`; rename it back: available after Refresh.
- **CL-LV9 (memory and quantization).** Watch the `qwen2511-q4` run with the LoRA for an mflux `could not be applied` error (a LoRA on the q4-quantized transformer has never run in this repo) and for memory pressure; floors are unchanged.

---

## 7. Risks (rulings), follow-ups and open questions

**Risks.**
1. **Lightning is always on for `qwen2511-q4`.** Guidance is fixed at 1.0 and the 8-step Lightning LoRA is loaded with every qwen2511 mflux edit, so the author's recommended 30 steps / CFG 4 cannot be reproduced. Results may be weaker than the model card's examples. Ruling: documented, measured in CL-LV4; a "no Lightning" run mode is a follow-up spec.
2. **LoRA on a q4-quantized mflux transformer.** No qwen2511 LoRA has run here before. mflux applies unbaked LoRA layers; if it raises, the child exits non-zero and the run fails clearly (CL-LV9).
3. **TLS certificates.** A python.org framework Python without its certificates fails the HF call with `SSLCertVerificationError`; M-HF-UNREACHABLE names the fix.
4. **Per-workspace registry.** Like the LoRA catalog, the file lives in the workspace's `generated/`, so a new fleet release starts with an empty registry; jobs started by the movie-ui use the UI workspace's file (D8), while a hand-run tool in another workspace uses its own.
5. **Consumers that assumed `repo`/`revision`.** Every one is in the C-table; local items have no `repo` (D4). `bin/seed-edit-setup`'s `items_of`, `report` and `present_gib` only see hf items (CL32). The page reads no `repo`.
6. **Hashing large local files** in the request thread can take minutes on the HDD volume; the page says so (CL41).
7. **A changed trigger re-edits** recorded panels (by design, D4).

**Open questions (each has a default this spec implements; the user may overrule before Task 1).**
- **Q1.** Should `add` use the card's `instance_prompt` as the default trigger instead of only hinting (D12)? Default: hint only.
- **Q2.** Should hf entries also store the LFS sha256 the API returns with `blobs=true` (`a4be266a...` for the target) and should `bin/seed-edit-setup` verify it after download? Default: no (not in the approved design); it would be a cheap integrity gain.
- **Q3.** Is refusing duplicate content (D10) acceptable, given that an A/B of steps or scale then needs remove plus add? Default: refuse.
- **Q4.** The default id cut to 24 characters is ugly for long repo names (`user-anything-to-real-charact`); the live checks pass `--id`. Default: keep the agreed rule.
- **Q5.** Keeping the binding env name `SEED_EDIT_USER_LORAS` requires E2 in nine test helpers; a name outside the `SEED_EDIT_` prefix would avoid it. Default: keep the name, apply E2.
- **Q6.** Triggers are ASCII only (D1); some Qwen LoRA cards use Chinese trigger text. Default: refuse non-ASCII.
- **Q7.** The page's custom LoRAs are the UI workspace's even when the user selects another workspace (D8). Default: as specified.
- **Q8.** The baseline's second known failure is not named in the brief; the controller records the exact baseline list before Task 1 (Plan, step 0).

---

## 8. Amended requirements of earlier specs

- **[SQ] SQ5** (registry lookups): `qwen_lora`, `registry_order` read the merged registry (CL6-CL8); an unknown id sorts last.
- **[SQ] SQ6** (`default_loras`): over the merged registry; custom LoRAs are never default-on.
- **[SQ] SQ7** (`qwen_settings`): item shapes D4, removed ids D5, scheduler D13.
- **[SQ] SQ10** (`registry_view`): three new keys per LoRA (CL12).
- **[SQ] SQ12** rows 12-16 and **[QE] QE51** (selection rules): the diffusers refusal (CL13, CL26).
- **[SQ] SQ16** (`lora_problem`): local and user-hf branches (CL25).
- **[SQ] SQ18 / SQ35** (probe shape): custom ids included; `_probe_qwen`'s `user-` tolerance (CL34).
- **[SQ] SQ41-SQ47** (`bin/seed-edit-setup`): custom ids, local report lines, the header check and exit 1 (CL32, CL33).
- **[QE] QE13-QE16** (`run_jobs`): the trigger prefix (CL28).
- **[SG] SG11** (`run.json`): `"prompt"` is the triggered text for a selection with triggers (CL31, CL37).
- **[SG] SG38** (capability refresh): also after a page add/remove (CL38).

---

## Plan

Each task is one commit by the `code-executor`, implementing exactly the requirements named; Opus reviews each task (design-reviewer) before the next starts.

### Step 0 (controller, before Task 1)
1. In `$S/cl-wt`, run `python3 -m pytest -q -p no:cacheprovider` (with `PYTHONPYCACHEPREFIX` under `$S`) and record the failing test ids as the baseline (expected: two, including `tests/test_story_engine.py::test_rst62_import_sets`).
2. Confirm `git diff --quiet ca958ca1c1320fdcb936c508f432eff83330d512 HEAD -- <PIPELINE_FILES>` exits 0.

### Task 1: the registry, the module, the CLI and the run path (one commit)
- Files: `movie_ui_seedgen.py` (CL1-CL14), `seed_lora_registry.py` (CL15-CL22b), `bin/seed-edit-lora` (CL23-CL24, `git update-index --chmod=+x`), `qwen_edit.py` (CL25-CL29), `bin/seed-edit` (CL30-CL31), `bin/seed-edit-setup` (CL32-CL33), `movie_ui_lib.py` (CL34), `tests/conftest.py` (E1), the nine helpers (E2), E3, E4 (all three edits), E5, new `tests/test_seed_lora_registry.py` (CL-T1-CL-T24).
- Gate: the new file passes; `tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_qwen_edit.py tests/test_movie_ui_qwen_edit.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_shots_seed.py tests/test_movie_ui_builder.py` pass; CL-T24 on 3.9 and 3.13; CLK3 grep is empty except `movie_ui_server.py` (fixed in Task 2).

### Task 2: the server and the page (one commit)
- Files: `movie_ui_server.py` (CL35-CL39), `static/movie-ui/app.js` (CL40-CL44), E6, new `tests/test_movie_ui_seed_loras.py` (CL-T25-CL-T34).
- Gate: the new file passes; the five E6 files pass; `node --check static/movie-ui/app.js`.

### Verification (controller)
- The full suite: no failure beyond the Step 0 baseline (CLK5).
- CLK3, CLK4 and CLK7 greps and diff.
- Design review (Opus) of both commits against this spec before the branch is declared done; then the user runs Section 6.
- No `test_mut26` re-baseline commit (CL50). If any `PIPELINE_FILES` member shows a diff, stop: the plan is wrong, report before committing anything else.
