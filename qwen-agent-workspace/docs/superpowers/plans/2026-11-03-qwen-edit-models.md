# Qwen Edit Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every image *edit* in the movie pipeline (Locations photo edits and their top-ups and Regenerate, Characters seed-image datasets and Regenerate, and Compose panel 1 when a seed image is used) runs a Qwen registry model and LoRAs the user picks (default `qwen21-q4` + `uncensored` @ 1.0, `qwen2511-bf16` kept for A/B), through one shared, screened edit runner, `qwen_edit.py`; Z-Image keeps every text-made image.

**Architecture:**
- **`qwen_edit.py` (Task 1)** is new and unpinned: the Qwen checks moved out of `bin/seed-edit` (installed, host memory, the mflux venv), the selection rules (`cli_selection`, `generator_text`, `child_timeout`, `memory_floor`) and `run_jobs`, which runs one child over a list of edit jobs and screens every output with `content_safety` in this process (mflux models) or in the unchanged `character_dataset.py qwenedit` child (`qwen2511-bf16`). `seed_edit_mflux_child.py` takes each job's own prompt and source and still reads the old spec shape.
- **Seeds (Task 2):** `bin/seed-edit` is refactored onto `qwen_edit.py` with its behaviour, texts and records unchanged; only the mflux spec shape changes.
- **Characters (Task 3, pinned files):** `character_lib.py` gains the optional `edit` key; `character_dataset.py` routes `run_edit_child` by the spec's `edit` (legacy model: the byte-identical qwenedit spec; any other model: `qwen_edit.run_jobs`), records the selection, uses the model's memory floor and sees the Qwen child in `busy_process`; `bin/character` gains `--qwen-model`/`--lora`.
- **Locations (Task 4):** `location_lib.py` gains the same `edit` key, `location_dataset.py` records and passes the selection to every edit round, `bin/location` gains the two options.
- **Compose (Task 5, pinned):** `bin/ltx-movie` gains `--seed-edit-model ID|as-is` and `--seed-edit-lora`, and a Phase 1c between Phase 1b and Phase 2 that edits the seed into panel 1 prompted by panel 1's `Image:` text, screens it, records `seed_edit.json`, and hands the edited image to the unchanged Phase 2 as its `--seed-image`.
- **movie-ui (Tasks 6, 7):** the request fields, V1 rule 12d, the 400/409 rules and argv forwarding for the three tabs, the batch levels, and one `qwenPicker` component mounted six times on four tabs (Seeds, Locations create and Regenerate, Characters create and Regenerate, Compose).
- **Task 8** moves `test_mut26`'s `BASELINE` in its own test-only commit.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest 8.3.4, Pillow, psutil); Python 3.9.6 (`/usr/bin/python3`) for the compile check only. The page is vanilla ES2017; `node` (`/opt/homebrew/bin/node`) runs `--check` in the page tests when present.
- mflux stays pinned `==0.24.0` in `~/mflux-edit/.venv` (never touched). No new dependency anywhere.
- Test helpers, unchanged: `tests/movie_ui_testutil.py`, `tests/location_testutil.py`, `tests/story_engine_testutil.py`; and, reused by import, the stubs and fakes of `tests/test_seed_edit_tool.py` (`MFLUX_STUB`, `QWENEDIT_STUB`, `make_fakes`, `install_model`, `install_lora`, `mflux_venv`, `qwenedit_stub`, `child_fakes`, `child_spec`), as `tests/test_clean_stop.py` already imports `tests/test_story_server.py`.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md`, committed at `c86808a` on `qwen-edit-models` (requirements QE1-QE70, tests QET1-QET39, KPIs QEK1-QEK9, live checks L1-L4, decisions in Section 15, conflicts with recommendations in Section 16).
- The dispatch adopts every Section 16 recommendation: build as approved (item 1), chained mode only (item 2), the page keeps the Seeds-Use origin (item 3), no mut25 allow-list change (item 4), keep the approved edit size (item 5), no `build_pkg.py` change (item 6).
- The spec's line citations are at `a62d477`; `c86808a` adds only the spec, so they hold. Every Edit below is located by its old text, never by a line number.
- The spec is binding. Where it cannot work as written against the existing suite, a numbered ruling in "Plan rulings" marked **[defect]** says what this plan does instead; rulings marked **[reading]** fill a detail the spec leaves open.

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions."
- [0.0 item 1] "Z-Image-Turbo stays for every image that is created from text. The Qwen registry applies only to edits and to Compose panel 1 when a seed image is used. No Qwen text-to-image anywhere."
- [0.0 item 5] "Default everywhere else: `qwen21-q4` + `uncensored` @ 1.0. `qwen2511-bf16` stays selectable for A/B."
- [0.0 item 6] "`content_safety.assert_image_safe` screens every output, always."
- [0.0 item 8] "Pinned files changed deliberately: `character_dataset.py`, `bin/character`, `character_lib.py`, `bin/ltx-movie`; `bin/ltx-story-images` stays untouched; `test_mut26`'s BASELINE moves in one separate test-only commit."
- [0.2] "Untouched: `bin/ltx-story-images`, `story_engine.py`, `bin/seed-edit-setup`, `content_safety.py`, `z_image_skill.py`, `mps_guard.py`, `movie_ui_seedfolder.py`, `scripts/deploy/build_pkg.py`, `static/movie-ui/app.css` (the picker reuses `.se-loras`/`.se-lora`), every other `PIPELINE_FILES` member."
- [QE1] "Its top-level imports are exactly `glob`, `importlib.util`, `json`, `os`, `re`, `signal`, `subprocess`, `sys`, `threading`, `time`, `movie_ui_lib`, `movie_ui_seedgen` (as `lib`, `seedgen`), in that order. It never imports `character_dataset`, PIL, psutil, torch, `content_safety` or mflux at top level ... Python 3.9 and 3.13."
- [QE2] "`movie_ui_lib.py` and `movie_ui_server.py` do **not** import `qwen_edit`."
- [QE10] "neither option → the registry default (`qwen21-q4` with `[{"id": "uncensored", "scale": 1.0}]`); `--qwen-model` given → exactly the listed LoRAs (none listed → none). ... `--lora` without `--qwen-model` is refused (`--lora needs --qwen-model`)."
- [QE11] "`child_timeout(n) = max(3600, 600 × n)`".
- [QE12] "Every edit waits for the selected entry's `memory_gib` available (`qwen21-q4` 20, `qwen21-q8` 32, `qwen21-bf16` 56, `qwen2511-q4` 32, `qwen2511-bf16` 64)".
- [QE15] "The mflux child's environment always comes from `seedgen.hf_child_env` (no `HF_TOKEN`, no `HUGGING_FACE_HUB_TOKEN`, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, `HF_HUB_OFFLINE=1`)."
- [QE16] "The legacy spec written by `run_jobs` for a run whose jobs share one source equals byte-for-byte what `bin/seed-edit`'s `run_bf16` writes today".
- [QE48 step 9] "There is no fallback to the unedited seed."
- [QE68] "Every node is built with `el()`/`clear()`, server text goes in through `textContent`; the page bans (`https?://`, `\son[a-z]+=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(`, `new Function`) still hold."
- [11.1] "No test loads a real model, uses the real HOME, runs `bin/seed-edit-setup`, renders, downloads, or contacts a server other than the in-test `127.0.0.1` one; none touches port 8177 or 8178. Every test sets `HOME`, `HF_HOME`, `Z_IMAGE_HF_HOME` under `tmp_path`, removes `HF_HUB_CACHE` and every `SEED_EDIT_*` variable".
- [11.1] "The new files `tests/test_qwen_edit.py`, `tests/test_ltx_movie_seed_edit.py`, `tests/test_movie_ui_qwen_edit.py` are added to `NEW_PY` and follow its scan: bin scripts are loaded with `SourceFileLoader` + `spec_from_loader` + `module_from_spec` + `exec_module` (never `load_module(`), no `urllib`."
- [11.1] "No check is added to `tests/test_ltx_movie_offline.py` (QEK2)".
- [QEK1] "`python3 -m pytest tests/ -q -rA` from `WS` has no failure beyond `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`"; [QEK2] "`python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`"; [QEK9] "At least 20 GiB free on the disk holding `WS` before the gate runs".
- [13.3] "Set `BASELINE = "<S>"` and extend the comment's last clause: `… then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames), then to <S> (qwen-edit-models).` ... Commit with only that file staged."
- [0.0 item 9, 12] "Live checks are run by the user on macstudio; the agent has no access to it."

Controller rules (every task's requirements include them):

- Never read, cat, grep or source `~/.zshenv` or any `fleet.env`, and never print tokens or secrets.
- Never ssh, scp, rsync or HTTP to macstudio or any other host, and never read or suggest copying its files. Never contact :8177 or :8178 or any server other than an in-test `127.0.0.1` one.
- Never download model weights; never run `bin/seed-edit-setup`, a real `bin/seed-edit`, `bin/location`, `bin/character` or `bin/ltx-movie` run (dry runs in tests excepted), a model, a render, a venv creation or a pip install. Never run tests against the real HOME.
- Never push. Push and the PR are a separate step that needs the user's go.

House rules (every task's requirements include them):

- **The checkout.** Never touch the main checkout `/Users/reubenpatterson/local_agent_harness`. Every command runs in the worktree `$S/qem-wt`, branch `qwen-edit-models`. Never git stash, reset, amend or check out other work.
- **Paths.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`; `WS` = `$S/qem-wt/qwen-agent-workspace`; `D` = `$S/qem-baseline` (scratch, never staged). The git root is `$S/qem-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Run every command from `WS`; shell variables do not persist between commands, so every block defines the variables it uses.
- **Python.** Every changed file must compile on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers. `test_mut25` also scans every `NEW_PY` file for `urllib`, `load_module(`, `shell=True` and `X | None` text, docstrings included. The code blocks below use none of them.
- **Editing.** Executors change tracked files only with the Edit tool, or the Write tool for a new file or a whole-file replacement after a Read (`bin/seed-edit` keeps mode `100755`). Never use `rm`, `sed -i`, a redirect or a script to change a tracked file.
- **Code blocks are copied byte for byte.** An Edit's old text is whole lines and occurs exactly once in the file at that moment, with or without its last newline. If it does not, stop and report; do not adapt it. Every Edit and Write below was replayed in order, in memory, against `c86808a`'s files (see "Execution handoff").
- **Git.** Stage only the paths a task names, and check `git diff --cached --name-only` before every commit. Every commit passes the trailer as a second `-m`: `-m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. Never stage `.DS_Store`, `.claude/`, `__pycache__/`, repo-root `bin/`, `qwen-agent-workspace/bin/action-from-dir`, `pin-sh2.json`, `story_bible_*.json` or `.superpowers/`.
- **The compile check** (in each task's verify step) is this command, with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

## Review Focus

These five inputs and failure modes are the ones most likely to reach a user first; the spec implies them and no QET row exercises them. Each is pinned by a test in the task that owns its code, named `test_qe_review_focus_N_...` (unique in the suite).

1. **A child that dies after writing an image but before reporting it** (a crash mid-run, or an mflux child that exits 0 one job short). QE13 promises "a `blocked` or `failed` job has no file at `output_path` or `stage_path` written by this call", but QE14's body only deletes blocked stage files; for Locations and Characters the stage file sits beside the stills (`loc_05.pending.png` in `stills/`), where nothing else cleans it. Expected: after `run_jobs` returns, no unfinished job's stage or output file exists, and the finished jobs' outputs do. Test: `test_qe_review_focus_1_an_unfinished_job_leaves_no_stage_file` (Task 1; plan ruling R4).
2. **The movie-ui Cancel during a Qwen Seeds run.** The refactor moves the child handle into `qwen_edit.CHILD`; `bin/seed-edit`'s interrupt branch must still kill it, or a cancelled run leaves the mflux child holding the GPU. SGT12 interrupts only a Z-Image run. Expected: `qe.kill_running_child()` SIGKILLs a real child's process group, and `bin/seed-edit`'s interrupt path calls it once and writes state `cancelled`, exit 130. Test: `test_qe_review_focus_2_an_interrupt_kills_the_qwen_child` (Task 2).
3. **A photo location built from 24 photos** (no edit runs). QE26 checks the editor only when there are fewer than 24 photos, but QE27 records `edit` on every photo location. Expected: with no Qwen model installed at all (the selection check would refuse), a 24-photo create still exits 0, prints no `edit model:` line, writes no manifest `edit` key (`generator` `photos only`), and records the default selection in `location.json` for a later Regenerate. Test: `test_qe_review_focus_3_a_24_photo_location_needs_no_editor` (Task 4).
4. **Regenerate of a photo location made before this feature, from the page.** The page preselects `qwen2511-bf16` for it (QE65) and sends `{"qwen_model": "qwen2511-bf16", "loras": []}`. Expected: the server probes that entry (409 `Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) is unavailable: ...` on a 48 GB host) and otherwise forwards `--qwen-model qwen2511-bf16` with no `--lora`; a 2.1 LoRA with it is a 400. Test: `test_qe_review_focus_4_a_legacy_photo_location_keeps_its_model` (Task 6).
5. **The selection survives the request → argv → tool round trip** for all three new argv builders. Any drift (LoRA order, scale formatting, the server's default LoRAs versus the tool's "none listed means none") would make the tool run a different selection than the page showed. Expected: for LoRAs given in reverse registry order, scales `2`, `1e-06` and `0.30000000000000004`, every model, and omitted LoRAs or model, the tool's `cli_selection` of the forwarded flags gives the same `qwen_edit.settings` as the server's cleaned selection, for `location_argv`, `character_argv` and `build_argv`. Test: `test_qe_review_focus_5_the_selection_round_trip` (Task 6).

## Plan rulings

1. **R1 [defect] `bin/ltx-movie` imports `hashlib` inside `phase_seed_edit`, not at the top (QE40).** `tests/test_dialogue.py::test_dk3_import_sets_are_unchanged` pins `bin/ltx-movie`'s top-level import set to `{argparse, glob, importlib.machinery, json, os, pipeline_log, shlex, subprocess, sys, threading, time}` and is a baseline pass the spec does not list in §11.3. A function-local `import hashlib` keeps that set and changes no behaviour (`hashlib` is only used to hash the seed in Phase 1c). `test_rst62_import_sets` is a baseline failure either way.
2. **R2 [defect] QE49 and QE50 keep the two `--seed-image` source lines textually unchanged.** `tests/test_ltx_movie_offline.py` L29d (part of `OK 347/347`, QEK2) counts the literals `\n        cmd += ["--seed-image", args.seed_image]` and `phase2_cmd += ["--seed-image", args.seed_image]` exactly once each. The plan keeps both lines and replaces the appended path afterwards (`cmd[-1] = args.seed_edited_path` when Phase 1c produced one; `phase2_cmd[-1] = <story>/seed-edited.png` in a dry run with `args.seed_edit`). The resulting argv is exactly QE49's and QE50's.
3. **R3 [defect] `test_k23_missing_editor_is_refused` and `test_ld10_the_edit_model_gate` pass `qwen2511-bf16` explicitly.** Both pin today's missing-editor refusal with no model option. Under QE10 the default becomes `qwen21-q4`, whose check is `edit_selection_problem` (faked to `None` by the §11.3 `_Fakes` edits), so both tests would silently stop testing the refusal. Their intent is the legacy editor check (QE26, QE36: "for `qwen_edit.LEGACY_EDIT_MODEL` unchanged"), so each gains `--qwen-model qwen2511-bf16` (`qwen_model="qwen2511-bf16"`); the asserted texts are unchanged. These are the only existing-test edits beyond spec §11.3.
4. **R4 [defect] `run_jobs` deletes the stage file of every job the child never reported, after the child exits.** QE13's contract says a `failed` job has no file at `stage_path` written by the call; QE14's body as typed leaves it. Four lines are added after the failure text is computed (Task 1 Step 3). Seeds already deleted these files in `cleanup`, so Seeds behaviour is unchanged (QEK3).
5. **R5 [reading] One commit per task, with that task's tests.** The dispatch shapes the work into right-sized tasks whose tests pass at their own end, so §13.2's "feature commit(s)" then "tests commit" become one commit per task; the `test_mut26` re-baseline is still its own final test-only commit (§13.2 item 3, §13.3), and `test_mut26` is an expected failure from Task 3 (the first pinned-file edit) through Task 7.
6. **R6 [reading] `NEW_PY` grows as each new file appears** (`test_mut25` compiles every listed file, so a name cannot precede its file): Task 1 adds `qwen_edit.py` and `tests/test_qwen_edit.py`, Task 5 `tests/test_ltx_movie_seed_edit.py`, Task 6 `tests/test_movie_ui_qwen_edit.py`. The final tuple is QE70's. QET11's `NEW_PY` assertion grows with it.
7. **R7 [reading] Characters before Locations.** Task 3 makes every `character_dataset.py` change (QE33-QE37), including the routing and `edit_selection_problem` that Locations call through, so one task carries all pinned-file review. QET18 tests that routing; it stays in `tests/test_location_dataset.py` (spec 11.2) and ships with Task 3. QET15's byte-identity check of `_edit_problem` needs both libraries, so it ships with Task 4.
8. **R8 [reading] §11.3's "SQT5, SGT9, review focus 1 and 3 spec dicts".** Only SQT5 and SGT9 compare whole mflux spec dicts; Seeds review focus 1 compares width and height and review focus 3 compares four keys, which do not change. Those two are not edited.
9. **R9 [reading] QE50's "`<W>x<H>` literally when Pillow is not importable"** is printed whenever `args.video_width` is not an `int` (the dry run's no-Pillow branch sets it to the string `"<W>"`).
10. **R10 [reading] `seed_edit.json`'s `status` is `failed` whenever `run_jobs` returns a failure text or raises `Unavailable`**, even if the job had reported `ok` before a non-zero exit; `output` is then `null`. `seconds` is the job's reported seconds when `run_jobs` returned a result row, else `null`.
11. **R11 [reading] `_h_location_regenerate` probes (409) when the record is unreadable** as well as when it is a dict with fewer than 24 photos (QE58 "409 when the record is a dict with fewer than 24 `photos` or unreadable").
12. **R12 [reading] Placement.** `qwen_selection` sits directly before `_qwen_fields`; `qwen_edit_flags` after `action_arg`; `SEED_EDIT_ID_RE` and `_rule_seed_edit` after `_rule_locations`; `_edit_given` and `edit_availability` after `_fields_body`; `edit_selection_problem` after `edit_models_missing`; `_run_registry_edit` after `run_edit_child`; `_edit_problem` and its constants before `validate_location`/`validate_character` and after `_PHOTO_KEYS`/`_LORA_KEYS`; `PHOTO_ONLY` after `BLOCKED`; `SEED_ONLY` after `character_dataset.SEED_MAX`; `SEED_EDIT_SKILL`/`SEED_EDIT_SCHEMA` after `SEED_MIN_EDGE`; `_qwen_edit` after `_location_lib`; `_resolve_seed_edit` after `_resolve_locations`; `_seed_edit_paths`, `_panel1_edit_prompt`, `_seed_edit_size`, `_write_seed_edit_record` and `phase_seed_edit` after `phase_release_story_server`; `qwenPicker` after `seedModelText`; `composeSeedEditActive` and `composeSeedDefault` before `composeFields`.
13. **R13 [reading] The new HTML blocks keep the surrounding indentation** (4 spaces inside the Locations and Characters `.grid` and detail sections, 6 inside the Compose fieldset); their elements and text are QE63's.
14. **R14 [reading] Docstrings.** The sentences QE18, QE23, QE24, QE30, QE31, QE32, QE35, QE37 and QE50 name are changed and the paragraph rewrapped to the file's width. Two unpinned docstrings whose import sentence this change makes false are corrected in the same edit: `bin/seed-edit` ("imports only the standard library, movie_ui_lib, movie_ui_seedgen and qwen_edit") and `location_dataset.py` ("character_dataset, location_lib and qwen_edit"). Pinned files get only the sentences the spec names.
15. **R15 [defect] The "current" `bin/ltx-movie --help` fixture gains the two new options, and the two tests that count against it follow.** `tests/test_movie_ui_http.py::test_mu14_ws_parameter_errors_and_options` asserts `all(payload["supported"].values()) and len(payload["supported"]) == 30` for the stub workspace, whose help is `tests/fixtures/movie_ui/ltx-movie-help-current.txt`; §11.3 misses it, and with `FIELD_FLAGS`' 31st entry it fails twice over. The location library set the precedent (commit `e4f1f30`): the fixture is re-captured with the new flags, `test_mut3_help_flags_fixtures_real_help_and_cache`'s `current - old` set gains them, and `test_mu14` counts 31. This plan does the same (Task 6). It also lets the Compose HTTP tests pass V1 rule 18 with the stub's default help.
16. **R16 [reading] Local names.** `location_dataset.create`/`_regenerate` and `character_dataset.create` call the cleaned selection `edit_model, edit_loras` (QE25's `model_id, loras` would shadow nothing but read as the record's `loras`); the server's "a selection was named" test is the helper `_edit_given(body)`.

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `qwen_edit.py` | Create (Task 1) | QE5-QE16: constants, the moved host and registry checks, `wait_for_memory`, `run_child`, `kill_running_child`, the pure selection helpers, `install_problem`, `selection_problem`, `run_jobs`. |
| `seed_edit_mflux_child.py` | Modify (Task 1) | QE17-QE18: per-job prompt and source, the old spec shape still read. |
| `bin/seed-edit` | Replace (Task 2) | QE19-QE23: the Seeds tool on top of `qwen_edit.py`, `run_qwen`. |
| `character_lib.py` (pinned) | Modify (Task 3) | QE38: `_OPTIONAL_KEYS`, `_edit_problem`, the `edit` rules in `validate_character`. |
| `character_dataset.py` (pinned) | Modify (Task 3) | QE33-QE37: `import qwen_edit`, `run_edit_child` routing, `_run_registry_edit`, `edit_selection_problem`, `busy_process`, `create`'s options, record and print, `_generate_edits`' spec, `_build_dataset`'s floor and manifest. |
| `bin/character` (pinned) | Modify (Task 3) | QE32: `--qwen-model`, `--lora`, docstring. |
| `location_lib.py` | Modify (Task 4) | QE31: the same `edit` rules for photo locations. |
| `location_dataset.py` | Modify (Task 4) | QE25-QE30: options, preflight, record, child spec, floor, manifest, docstring. |
| `bin/location` | Modify (Task 4) | QE24: `--qwen-model`, `--lora`, docstring. |
| `bin/ltx-movie` (pinned) | Modify (Task 5) | QE40-QE50: options, `_qwen_edit`, `_resolve_seed_edit`, Phase 1c, the Phase 2 seed, the dry run, docstring. |
| `movie_ui_seedgen.py` | Modify (Task 6) | QE51: `qwen_selection`. |
| `movie_ui_lib.py` | Modify (Task 6) | QE52-QE54, QE69: fields, flags, `qwen_edit_flags`, argv, V1 rule 12d, `PHASE_RE`, `job_phases`. |
| `movie_ui_server.py` | Modify (Task 6) | QE55-QE59: `edit_availability`, `_edit_given`, the Compose, Locations and Characters rules and forwarding. |
| `movie_ui_batch.py` | Modify (Task 6) | QE60: levels, groups, merge. |
| `static/movie-ui/index.html`, `static/movie-ui/app.js` | Modify (Task 7) | QE61-QE68: `qwenPicker` and its six mounts. |
| `tests/test_qwen_edit.py` | Create (Task 1) | QET1-QET11, Review Focus 1. |
| `tests/test_seed_edit_tool.py` | Modify (Tasks 1, 2) | `MFLUX_STUB`'s `silent` key (Task 1); §11.3's edits, QET12, Review Focus 2 (Task 2). |
| `tests/test_movie_ui_seedgen.py` | Modify (Tasks 2, 7) | SQT18 and SGT34 (Task 2); SGT33, SQT22 and the d/e/f page guards (Task 7). |
| `tests/test_location_dataset.py` | Modify (Tasks 3, 4) | QET18 (Task 3); `_Fakes`, LD13, LD10 (R3), QET13, QET14, QET16, QET17, Review Focus 3 (Task 4). |
| `tests/test_character_tool.py` | Modify (Task 3) | `_Fakes`, K19, K23 (R3), QET20-QET22. |
| `tests/test_character_lib.py`, `tests/test_character_dataset.py` | Modify (Task 3) | QET23; QET24, QET25. |
| `tests/test_location_lib.py`, `tests/test_location_tool.py` | Modify (Task 4) | QET15; the `_fakes` line and QET19. |
| `tests/test_ltx_movie_seed_edit.py` | Create (Task 5) | QET26-QET32. |
| `tests/test_movie_ui_qwen_edit.py` | Create (Task 6), Modify (Task 7) | QET33-QET37, Review Focus 4 and 5 (Task 6); QET38, QET39 (Task 7). |
| `tests/test_location_ui.py`, `tests/test_movie_ui_batch.py` | Modify (Task 6) | The `FIELD_FLAGS` count 31; `(27, 5, 32)` and `EXPECTED_LEVELS`. |
| `tests/test_movie_ui_http.py`, `tests/fixtures/movie_ui/ltx-movie-help-current.txt` | Modify (Task 6) | Ruling R15: `test_mu14`'s count 31; the "current" help fixture lists `--seed-edit-model` and `--seed-edit-lora`. |
| `tests/test_movie_ui_builder.py` | Modify (Tasks 1, 5, 6, 8) | `NEW_PY` (Tasks 1, 5, 6), `test_mut3`'s `current - old` set and the `FIELD_FLAGS` count 31 (Task 6, R15), `test_mut26` (Task 8 only). |

**Task split.** Each task is the smallest unit with its own test cycle and a reviewer gate, and each leaves the suite green except the expected `test_mut26` failure:
- Task 1 adds the runner beside the unchanged Seeds tool (whose copies of the moved functions still exist), so nothing consumes it yet; the child's new per-job reading is backward compatible, so Seeds keeps working.
- Task 2 switches Seeds onto it; a reviewer can reject the refactor without touching the runner.
- Task 3 is every pinned Characters change; Task 4 the unpinned Locations change that calls into it; Task 5 the pinned Compose orchestrator.
- Task 6 is the movie-ui server side (fields, rules, forwarding, batch), testable over HTTP without the page; Task 7 the page; Task 8 the baseline.

The browser check, the pass bar, the design review and the live checks need a browser, a person or the user's go, so they are the controller's "Verification" section. The spec requires no README change.

---

## Between tasks: the existing suite

**Expected lost passes**, written to `$D/expected-failures.txt` in "Before Task 1" Step 3. A line is `T<first task> <test id> <note>`; the list covers Tasks 3-7 and is empty from Task 8 on (Task 8 checks that `test_mut26` passes again):

```text
# qwen edit models plan: baseline passes expected to fail from the given task until Task 8
T3 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged pinned files change from Task 3 (character_dataset.py); Task 8 moves BASELINE
```

**The gate** is `$D/gate.py`, written in "Before Task 1" Step 3: the seed-models gate with `NEW_FILES` naming this plan's three new test files. Every task's verify step runs this block with its `N` (a full run of about 19 minutes; it may run in the background):

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/qem-baseline
N=1
cd $S/qem-wt/qwen-agent-workspace
df -g . | tail -1 | awk '{print ($4 >= 20) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
diff <(python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1) $D/baseline-offline.txt && echo "offline unchanged"
```

Expected: `disk ok` (QEK9: at least 20 GiB; on `DISK LOW` stop and report, never delete anything), `GATE PASS`, `not passing 0`, `baseline failures still failing 2 of 2`, `offline unchanged` (`OK 347/347`), and the `lost` line each task's verify step states.

**When the gate prints `GATE STOP`:** the executor stops and reports the UNEXPECTED or NEW-TEST-FAIL IDs with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass the list does not name is a defect in this task's code; the controller has an Opus reviewer rule on it and writes the exact fix. If an UNEXPECTED ID is `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` or `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules` (timing-sensitive, unrelated), rerun it alone; if it passes alone, the controller appends `T<N> <id> flaky` to the list and V1 rechecks it. A new test is never added to the list.

**Must stay green in every task** (none is in the list, so a failure stops the gate): `tests/test_dialogue.py::test_dk3_import_sets_are_unchanged` (R1), `tests/test_ltx_movie_offline.py`'s 347 checks (R2), `tests/test_character_dataset.py::test_d17_busy_process` and `test_d37_no_heavy_top_level_imports`, `tests/test_character_lib.py::test_c41_stdlib_only_imports`, `tests/test_location_golden.py` (`test_lg1`, `test_lg3`), `tests/test_location_tool.py::test_lt2_list_and_show_need_only_the_standard_library`, `tests/test_movie_ui_builder.py::test_mut25_*`, `tests/test_movie_ui_jobs.py::test_mut15_bin_movie_ui_lock_port_and_startup_lines`, `tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token` (63 routes: this plan adds none), every other test in the two Seeds files.

---

## Before Task 1: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 1: Confirm the plan commit and the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git branch --show-current                                      # expected: qwen-edit-models
git log -3 --format=%h' '%s                                    # expected: <plan sha> docs(plan): Qwen edit models implementation plan; c86808a docs(spec): ...; a62d477 Merge pull request #9 ...
git diff --stat a62d477 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
git status --short                                             # expected: no output
wc -l bin/seed-edit seed_edit_mflux_child.py movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py movie_ui_batch.py location_lib.py location_dataset.py bin/location character_lib.py character_dataset.py bin/character bin/ltx-movie static/movie-ui/index.html static/movie-ui/app.js | head -15
```

Expected `wc -l` counts (at `c86808a`): `bin/seed-edit` 893, `seed_edit_mflux_child.py` 105, `movie_ui_seedgen.py` 333, `movie_ui_lib.py` 2435, `movie_ui_server.py` 3418, `movie_ui_batch.py` 488, `location_lib.py` 533, `location_dataset.py` 1100, `bin/location` 162, `character_lib.py` 1482, `character_dataset.py` 1952, `bin/character` 152, `bin/ltx-movie` 2783, `index.html` 467, `app.js` 3236. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Confirm the compressed snapshot (house rule; spec 13.1 step 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
ls -l $S/qem-snapshot-a62d477.tar.gz
tar tzf $S/qem-snapshot-a62d477.tar.gz | grep -c 'qwen-agent-workspace/character_dataset.py$'   # expected: 1
tar tzf $S/qem-snapshot-a62d477.tar.gz | grep -c '/generated/'                                  # expected: 0
```

If the file is missing, take it now: `tar czf $S/qem-snapshot-a62d477.tar.gz --exclude qwen-agent-workspace/generated -C $S/qem-wt qwen-agent-workspace`.

- [ ] **Step 3: Record the baseline (spec 13.1 steps 2-3) and write the gate files.** The full run takes about 19 minutes and may run in the background.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/qem-baseline
mkdir -p $D
cd $S/qem-wt/qwen-agent-workspace
df -g . | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1 > $D/baseline-offline.txt; cat $D/baseline-offline.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt
```

Expected: at least 20 GiB available in the `df -g` line; a summary of the shape `2 failed, <P0> passed, 2 skipped, ...`; exactly the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...`; no `ERROR` line; `OK 347/347`; `1` (`test_mut26` passes at `c86808a`). Record the `PASSED` count as `P0`. If the failures differ, stop and report. These files **are** the baseline.

Then write two scratch files with the Write tool (outside the repository, never staged):

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate.py`, exactly:

```python
"""The task gate of the qwen edit models plan: a full pytest -rA run against the baseline. A new
test is one of the three new files or any test ID the baseline does not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_qwen_edit.py::", "tests/test_ltx_movie_seed_edit.py::", "tests/test_movie_ui_qwen_edit.py::")


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            found = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if found:
                out[found.group(2)] = found.group(1)
    return out


base, now = status(base_file), status(run_file)
expected = []
with open(expected_file, encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if parts and not line.startswith("#") and int(parts[0][1:]) <= task < 8:
            expected.append(parts[1])


def listed(test):
    return any(test == e or test.startswith(e + "[") for e in expected)


lost = sorted(t for t, s in base.items() if s == "PASSED" and now.get(t) != "PASSED")
unexpected = [t for t in lost if not listed(t)]
mine = sorted(t for t in now if t.startswith(NEW_FILES) or t not in base)
broken = [t for t in mine if now[t] != "PASSED"]
old_failures = sorted(t for t, s in base.items() if s in ("FAILED", "ERROR"))
still = [t for t in old_failures if now.get(t) in ("FAILED", "ERROR")]
print("lost %d (listed %d, unexpected %d); new tests %d, not passing %d; baseline "
      "failures still failing %d of %d" % (len(lost), len(lost) - len(unexpected),
                                          len(unexpected), len(mine), len(broken), len(still),
                                          len(old_failures)))
for t in lost:
    print("LOST", t, "listed" if listed(t) else "UNEXPECTED")
for t in broken:
    print("NEW-TEST-FAIL", t, now[t])
print("GATE", "PASS" if not unexpected and not broken else "STOP")
```

(The `task < 8` clause makes every listed loss unexpected from Task 8 on, which is how Task 8's gate proves `test_mut26` passes again.)

---

### Task 1: `qwen_edit.py`, the shared edit runner, and the mflux child's per-job prompt and source (QE1-QE18; QET1-QET11, Review Focus 1)

This task implements:
- `qwen_edit.py` (QE5-QE16): the constants and exceptions typed as QE5 gives them; the functions QE6 moves (here *copied*, byte for byte from `bin/seed-edit`; Task 2 deletes the originals); `wait_for_memory` (QE7), `run_child` (QE8), `kill_running_child` (QE9); the pure helpers of spec 2.3; `install_problem`, `selection_problem` (spec 2.4); `run_jobs` (QE13, QE14, plus ruling R4's four-line cleanup).
- `seed_edit_mflux_child.py` (QE17, QE18): per-job `prompt`/`source`, falling back to the spec-level values.
- Tests: the new `tests/test_qwen_edit.py` (QET1-QET11, Review Focus 1); `MFLUX_STUB`'s `silent` key in `tests/test_seed_edit_tool.py` (spec 11.1); `NEW_PY` gains `qwen_edit.py` and `tests/test_qwen_edit.py` (R6).

Nothing calls `qwen_edit.py` yet; `bin/seed-edit` keeps its own copies and still writes the old mflux spec shape, which the child still reads.

**Files:**
- Create: `qwen_edit.py`, `tests/test_qwen_edit.py`.
- Modify: `seed_edit_mflux_child.py` (docstring `:9-11`, job loop `:89-91`), `tests/test_seed_edit_tool.py` (`MFLUX_STUB` `:217-219`), `tests/test_movie_ui_builder.py` (`NEW_PY` `:213-218`).
- Read only: `bin/seed-edit` `:268-503`, `:506-520`, `:686-727`, `:749-813` (the source of the copied functions and of `run_jobs`' two branches); `movie_ui_seedgen.py` (`qwen_model`, `qwen_lora`, `registry_order`, `default_loras`, `qwen_settings`, `hf_child_env`, `QWEN_MODEL_IDS`, `QWEN_LORA_IDS`, `QWEN_FAMILIES`, `SCALE_MAX`, `DEFAULT_QWEN_MODEL`, `QWEN21_REQUIRED`).

**Interfaces:**
- Consumes (existing): `movie_ui_seedgen` as above; `movie_ui_lib.write_json_atomic(path, data)`, `lib.choose_snapshot`, `lib.repo_dir_name`, `lib.model_check`, `lib.intact_scan`, `lib.zimage_hub()`; `content_safety.assert_image_safe(image, *, skill, prompt)` and `content_safety.ContentSafetyError` (imported inside `run_jobs`).
- Produces, in `qwen_edit` (Tasks 2-6 use these names exactly):
  - constants `WS`, `EDIT_MODEL`, `EDIT_LORA_REPO`, `EDIT_LORA_FILE`, `EDIT_STEPS`, `EDIT_TRUE_CFG`, `LEGACY_EDIT_MODEL = "qwen2511-bf16"`, `MODEL_IDS`, `MFLUX_MIN_VERSION`, `MFLUX_GUIDANCE`, `DEFAULT_MFLUX_PYTHON`, `AVAIL_WAIT_S = 600`, `CHILD_TIMEOUT_S = 3600`, `JOB_TIMEOUT_S = 600`, `MFLUX_LINE_RE`, `QWENEDIT_LINE_RE`, the module global `CHILD`;
  - exceptions `SelectionError(Exception)`, `Unavailable(Exception)` (the message is the refusal text);
  - `avail_gib() -> float`, `total_gib() -> float or None`, `missing_modules(names) -> list`, `modules_problem(names)`, `default_hub()`, `mflux_python()`, `find_lightning(hubs)`, `bf16_problem()`, `mflux_version(venv)`, `pinned_snapshot(repo, revision, hubs)`, `pinned_file(repo, revision, name, hubs)`, `weights_problem(entry, hubs)`, `qwen_hubs()`, `mflux_env_problem(entry)`, `lora_problem(lora, hubs)`, `qwen_model_problem(entry)`, `memory_problem(entry)`, `_kill_group(pid)` (bodies as in `bin/seed-edit`);
  - `wait_for_memory(floor, label, tag="seed-edit") -> None` or raises `Unavailable`;
  - `run_child(argv, env, on_line, timeout_s, log_path=None) -> (exit code, timed_out bool)`; `kill_running_child() -> None`;
  - `check_lora_args(values, entry, flag="--lora") -> [{"id", "scale"}]` (registry order) or raises `SelectionError`;
  - `cli_selection(model_arg, lora_args, model_flag="--qwen-model", lora_flag="--lora") -> (model_id, [{"id", "scale"}])` or raises `SelectionError`;
  - `settings(model_id, loras) -> {"qwen_model": {"id", "repo"}, "loras": [{"id", "repo", "file", "scale"}], "steps", "scheduler"}`; `selection_of(edit) -> (model_id, [{"id", "scale"}])`; `label(model_id) -> str`; `multiple(model_id) -> int`; `memory_floor(model_id) -> float`; `child_timeout(n_jobs) -> int`; `generator_text(model_id, loras) -> str`;
  - `install_problem(model_id, loras) -> (None, {"model_path", "builtin_lora", "lora_paths"})` (for the diffusers model `{"lora_paths": []}`) or `(text, {})`; `selection_problem(model_id, loras) -> None or text`;
  - `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job") -> (results, failure)`: `jobs` is a non-empty list of `{"n", "seed", "prompt", "source", "stage_path", "output_path"}`; `results` one `{"n", "output_path", "status": "ok"|"blocked"|"failed", "seconds"}` per job in job order; `failure` `None` or QE13's text; raises `Unavailable` when `install_problem` fails.
- Produces, in the test helpers: `MFLUX_STUB` config key `"silent"` (job numbers whose done line is not printed; their image is still written).

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    color = (255, 0, 0) if job["n"] in config.get("red", []) else (0, 0, 200)
    Image.new("RGB", (spec["width"], spec["height"]), color).save(job["output_path"])
    print(config.get("prefix", "") + "seed-edit-child done %d 1.0" % job["n"], flush=True)
```

with:

```python
    color = (255, 0, 0) if job["n"] in config.get("red", []) else (0, 0, 200)
    Image.new("RGB", (spec["width"], spec["height"]), color).save(job["output_path"])
    if job["n"] not in config.get("silent", []):
        print(config.get("prefix", "") + "seed-edit-child done %d 1.0" % job["n"], flush=True)
```

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "seed_edit_mflux_child.py", "tests/test_seed_edit_tool.py", "tests/test_movie_ui_seedgen.py")
```

with:

```python
          "seed_edit_mflux_child.py", "tests/test_seed_edit_tool.py", "tests/test_movie_ui_seedgen.py",
          "qwen_edit.py", "tests/test_qwen_edit.py")
```

Write `tests/test_qwen_edit.py` with exactly this content (the Write tool):

```python
"""Tests for qwen_edit.py, the shared Qwen edit runner, and seed_edit_mflux_child.py's per-job prompt and
source (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, Section 11.2: QET1-QET11, with the
plan's Review Focus pin 1).

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py

Rules (spec 11.1): every test sets HOME, HF_HOME and Z_IMAGE_HF_HOME under tmp_path and removes
HF_HUB_CACHE and every SEED_EDIT_* variable (the env fixture). The mflux child is tests/test_seed_edit_tool.py's
MFLUX_STUB through SEED_EDIT_MFLUX_PYTHON, the qwenedit child its QWENEDIT_STUB through
SEED_EDIT_QWENEDIT_SCRIPT, and content_safety its sys.modules fake (make_fakes), whose assert_image_safe
blocks an image with a pure-red top-left pixel. qwen_edit.avail_gib, total_gib and missing_modules are
monkeypatched. No test uses the real HOME, loads a model, runs bin/seed-edit-setup, renders, downloads
or contacts a server; none touches port 8177 or 8178. Stdlib, PIL and pytest.
"""

import json
import os
import re
import subprocess
import sys
import time

import pytest

import movie_ui_testutil as mt
import movie_ui_seedgen as seedgen
import qwen_edit as qe
import test_seed_edit_tool as st

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
HEAVY = {"torch", "PIL", "psutil", "diffusers", "transformers", "content_safety", "character_dataset",
         "z_image_skill"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Spec 11.1's environment; qwen_edit's host probes faked (40 GiB available, 48 GiB total, every
    module importable) and the content_safety fake installed (test_seed_edit_tool.make_fakes)."""
    tmp = str(tmp_path)
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(tmp, "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(tmp, "zi"))
    monkeypatch.setattr(qe, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(qe, "total_gib", lambda: 48.0)
    monkeypatch.setattr(qe, "missing_modules", lambda names: [])
    return {"tmp": tmp, "qe": qe, "calls": st.make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}


def _sources(env):
    """Two distinct 1024x640 PNG sources under tmp."""
    return [st.png(os.path.join(env["tmp"], "src", "a.png"), (1024, 640), (0, 90, 0)),
            st.png(os.path.join(env["tmp"], "src", "b.png"), (1024, 640), (0, 0, 90))]


def _jobs(env, sources, stage="loc_%02d.pending.png", prompts=("north view", "south view", "east view")):
    """One job per prompt (n 1, 2, 3; seed 10 + n), the sources used in turn, staged and finished in
    <tmp>/out."""
    out = os.path.join(env["tmp"], "out")
    os.makedirs(out, exist_ok=True)
    return [{"n": n, "seed": 10 + n, "prompt": prompts[n - 1], "source": sources[(n - 1) % len(sources)],
             "stage_path": os.path.join(out, stage % n), "output_path": os.path.join(out, "loc_%02d.png" % n)}
            for n in range(1, len(prompts) + 1)]


def _mflux_ready(env, model_id="qwen21-q4"):
    """The mflux stub venv, model_id's pinned snapshot and the uncensored LoRA; returns (python, snapshot,
    LoRA path)."""
    py, _venv = st.mflux_venv(env)
    snapshot, _lightning = st.install_model(env, model_id)
    return py, snapshot, st.install_lora(env, "uncensored")


def _bf16_cache(env):
    """The diffusers model and the Lightning file in the default hub (as test_seed_edit_tool's bf16_cache)."""
    root = os.path.join(env["tmp"], "hf")
    mt.make_hf_cache(root, qe.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})


# --- QET1 (QE10): the CLI selection rule ----------------------------------------------------------------

def test_qet1_cli_selection():
    assert qe.cli_selection(None, None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert qe.cli_selection("qwen21-q8", None) == ("qwen21-q8", [])
    assert qe.cli_selection("qwen21-q4", ["viggle-turbo=0.5", "uncensored=1"]) == (
        "qwen21-q4", [{"id": "uncensored", "scale": 1.0}, {"id": "viggle-turbo", "scale": 0.5}])
    assert qe.cli_selection("qwen2511-bf16", []) == ("qwen2511-bf16", [])
    for model_flag, lora_flag in (("--qwen-model", "--lora"), ("--seed-edit-model", "--seed-edit-lora")):
        def refused(model, loras):
            with pytest.raises(qe.SelectionError) as info:
                qe.cli_selection(model, loras, model_flag, lora_flag)
            return str(info.value)

        scale = "%s uncensored scale must be a number above 0 and at most 2" % lora_flag
        assert refused(None, ["uncensored=1"]) == "%s needs %s" % (lora_flag, model_flag)
        assert refused("flux", None) == (
            "%s must be one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16" % model_flag)
        for loras, text in ((["uncensored"], "%s must be ID=SCALE (got uncensored)" % lora_flag),
                            (["Uncensored=1"], "%s must be ID=SCALE (got Uncensored=1)" % lora_flag),
                            (["nope=1"], "%s: unknown LoRA nope; known: uncensored, viggle-turbo" % lora_flag),
                            (["uncensored=1", "uncensored=0.5"], "%s uncensored is given twice" % lora_flag),
                            (["uncensored=0"], scale), (["uncensored=2.5"], scale), (["uncensored=x"], scale),
                            (["uncensored=nan"], scale), (["uncensored=inf"], scale)):
            assert refused("qwen21-q4", loras) == text, (model_flag, loras)
        assert refused("qwen2511-q4", ["uncensored=1"]) == (
            "%s uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)" % lora_flag)


# --- QET2 (QE9-QE12): texts, lookups and the selection checks --------------------------------------------

def test_qet2_texts_lookups_and_selection_checks(env):
    assert qe.generator_text("qwen21-q4", UNC) == (
        "Qwen-Image-2.1 q4 (mflux-community/qwen-image-2-1-mflux-q4) + LoRAs uncensored@1, 40 steps")
    assert qe.generator_text("qwen21-q8", [{"id": "uncensored", "scale": 0.5},
                                           {"id": "viggle-turbo", "scale": 1.0}]) == (
        "Qwen-Image-2.1 q8 (mflux-community/qwen-image-2-1-mflux-q8) + LoRAs uncensored@0.5, viggle-turbo@1, "
        "6 steps")
    assert qe.generator_text("qwen2511-q4", []) == (
        "Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-mflux-q4) + LoRAs none, "
        "8 steps")
    assert qe.generator_text("qwen2511-bf16", []) == (
        "Qwen/Qwen-Image-Edit-2511 + Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    want = {"qwen21-q4": ("Qwen-Image-2.1 q4", 32, 20.0), "qwen21-q8": ("Qwen-Image-2.1 q8", 32, 32.0),
            "qwen21-bf16": ("Qwen-Image-2.1 bf16", 32, 56.0),
            "qwen2511-q4": ("Qwen-Image-Edit-2511 q4 (Lightning)", 16, 32.0),
            "qwen2511-bf16": ("Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)", 16, 64.0)}
    for model_id, (label, multiple, floor) in want.items():
        assert (qe.label(model_id), qe.multiple(model_id), qe.memory_floor(model_id)) == (label, multiple, floor)
    assert qe.MODEL_IDS == seedgen.QWEN_MODEL_IDS and qe.LEGACY_EDIT_MODEL == "qwen2511-bf16"
    assert qe.settings("qwen21-q4", UNC) == seedgen.qwen_settings("qwen21-q4", UNC)
    assert qe.selection_of(qe.settings("qwen21-q8", [{"id": "uncensored", "scale": 0.5}])) == (
        "qwen21-q8", [{"id": "uncensored", "scale": 0.5}])
    where = "%s or %s" % (env["zhub"], env["hfhub"])
    st.mflux_venv(env)
    assert qe.install_problem("qwen21-q8", []) == (
        "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
        "(run bin/seed-edit-setup --model qwen21-q8)" % where, {})
    snapshot, _none = st.install_model(env, "qwen21-q4")
    assert qe.install_problem("qwen21-q4", UNC) == (
        "LoRA Uncensored (abenzerps) is unavailable: qwen-image-2.1-uncensored-lora.safetensors is not in %s "
        "(run bin/seed-edit-setup --lora uncensored)" % where, {})
    lora = st.install_lora(env, "uncensored")
    assert qe.install_problem("qwen21-q4", UNC) == (
        None, {"model_path": snapshot, "builtin_lora": None, "lora_paths": [lora]})
    env["mp"].setattr(qe, "total_gib", lambda: 16.0)
    assert qe.selection_problem("qwen21-q4", UNC) == (
        "Qwen-Image-2.1 q4 is unavailable: needs a host with at least 20 GiB of memory (this host has 16.0 GiB)")
    env["mp"].setattr(qe, "total_gib", lambda: 48.0)
    assert qe.selection_problem("qwen21-q4", UNC) is None
    assert qe.selection_problem("qwen21-q8", []).startswith(
        "Qwen-Image-2.1 q8 is unavailable: mflux-community/qwen-image-2-1-mflux-q8@")


# --- QET3 (QE11): the child timeout --------------------------------------------------------------------------

def test_qet3_the_child_timeout():
    assert (qe.CHILD_TIMEOUT_S, qe.JOB_TIMEOUT_S, qe.AVAIL_WAIT_S) == (3600, 600, 600)
    assert [qe.child_timeout(n) for n in (1, 4, 6, 7, 18, 23, 24)] == [
        3600, 3600, 3600, 4200, 10800, 13800, 14400]


# --- QET4 (QE13-QE15): the mflux spec, argv and environment ----------------------------------------------------

def test_qet4_the_mflux_spec_argv_and_env(env):
    mp = env["mp"]
    mp.setenv("HF_TOKEN", "dummy-not-a-token")
    mp.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    mp.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)
    py, snapshot, lora = _mflux_ready(env)
    jobs = _jobs(env, _sources(env))
    work = os.path.join(env["tmp"], "work")
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(dict(child_env))
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(qe, "run_child", spy)
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit", work)
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    (call,) = st.stub_calls(py)
    assert call["argv"] == [py, os.path.join(WS, "seed_edit_mflux_child.py"), "--spec",
                            os.path.join(work, "mflux_spec.json")]
    assert call["spec"] == {
        "family": "qwen21", "model_path": snapshot, "lora_paths": [lora], "lora_scales": [1.0], "width": 1024,
        "height": 640, "steps": 40, "guidance": 1.0, "scheduler": "linear",
        "jobs": [{"n": j["n"], "seed": j["seed"], "prompt": j["prompt"], "source": j["source"],
                  "output_path": j["stage_path"]} for j in jobs]}
    assert [j["source"] for j in call["spec"]["jobs"]] == [jobs[0]["source"], jobs[1]["source"], jobs[0]["source"]]
    assert len(seen) == 1
    child = seen[0]
    assert sorted(k for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN") if k in child) == []
    assert (child["HF_HUB_DISABLE_IMPLICIT_TOKEN"], child["HF_HUB_OFFLINE"], child["PYTHONUNBUFFERED"]) == (
        "1", "1", "1")
    assert os.environ["HF_TOKEN"] == "dummy-not-a-token"


# --- QET5 (QE13, QE14): every mflux output is screened in this process ------------------------------------------

def test_qet5_every_output_is_screened(env):
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"red": [2]})
    jobs = _jobs(env, _sources(env))
    seen = []

    def on_result(result):
        seen.append((result["n"], result["status"], os.path.isfile(result["output_path"])))

    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "work"), on_result=on_result)
    assert failure is None
    assert [(r["n"], r["status"], r["seconds"]) for r in results] == [
        (1, "ok", 1.0), (2, "blocked", 1.0), (3, "ok", 1.0)]
    assert env["calls"]["safety"] == [{"skill": "location_edit", "prompt": j["prompt"], "size": (1024, 640)}
                                      for j in jobs]
    assert seen == [(1, "ok", True), (2, "blocked", False), (3, "ok", True)]
    assert [os.path.exists(j["output_path"]) for j in jobs] == [True, False, True]
    assert [os.path.exists(j["stage_path"]) for j in jobs] == [False, False, False]


# --- QET6 (QE13): the three failure texts ------------------------------------------------------------------------

def test_qet6_child_failures(env):
    mp = env["mp"]
    py, _snapshot, _lora = _mflux_ready(env)
    work = os.path.join(env["tmp"], "work")
    st.stub_config(py, {"fail_after": 1})
    results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit", work)
    assert failure == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert [(r["status"], r["seconds"]) for r in results] == [("ok", 1.0), ("failed", None), ("failed", None)]
    mp.setattr(qe, "CHILD_TIMEOUT_S", 1)
    mp.setattr(qe, "JOB_TIMEOUT_S", 0)
    st.stub_config(py, {"sleep": 30})
    started = time.monotonic()
    results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit", work)
    assert failure == "Qwen-Image-2.1 q4 child timed out after 1 s" and time.monotonic() - started < 20
    assert [r["status"] for r in results] == ["failed"] * 3 and qe.CHILD is None
    mp.setattr(qe, "CHILD_TIMEOUT_S", 3600)
    st.stub_config(py, {"silent": [2]})
    for noun, text in (("job", "job 2"), ("candidate", "candidate 2")):
        results, failure = qe.run_jobs("qwen21-q4", UNC, _jobs(env, _sources(env)), 1024, 640, "location_edit",
                                       work, noun=noun)
        assert failure == "Qwen-Image-2.1 q4 child exited 0 without finishing %s" % text
        assert [r["status"] for r in results] == ["ok", "failed", "ok"]


# --- Review Focus 1 (plan ruling R4): an unfinished job leaves no stage file -------------------------------------

def test_qe_review_focus_1_an_unfinished_job_leaves_no_stage_file(env):
    """QE13: a failed job has no file at stage_path or output_path written by the call. The stub writes job
    2's image to its stage path but never reports it (exit 0), as a child killed between saving and
    printing would; then a child that exits 1 after job 1 leaves jobs 2 and 3 unwritten."""
    py, _snapshot, _lora = _mflux_ready(env)
    st.stub_config(py, {"silent": [2]})
    jobs = _jobs(env, _sources(env))
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "w1"))
    assert failure is not None and [r["status"] for r in results] == ["ok", "failed", "ok"]
    assert sorted(os.listdir(os.path.dirname(jobs[0]["output_path"]))) == ["loc_01.png", "loc_03.png"]
    st.stub_config(py, {"fail_after": 1})
    for job in jobs:
        if os.path.exists(job["output_path"]):
            os.remove(job["output_path"])
    results, failure = qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit",
                                   os.path.join(env["tmp"], "w2"))
    assert failure == "Qwen-Image-2.1 q4 child exited 1: boom"
    assert sorted(os.listdir(os.path.dirname(jobs[0]["output_path"]))) == ["loc_01.png"]


# --- QET7 (QE4, QE14, QE16): qwen2511-bf16 runs the unchanged qwenedit child ------------------------------------

def test_qet7_the_legacy_child(env):
    _bf16_cache(env)
    stub = st.qwenedit_stub(env, {"blocked": [2]})
    srcs = _sources(env)
    work = os.path.join(env["tmp"], "work")
    jobs = _jobs(env, srcs, stage="cand_%02d.part.png")
    results, failure = qe.run_jobs("qwen2511-bf16", [], jobs, 1024, 640, "location_edit", work)
    assert failure is None
    (call,) = st.stub_calls(stub)
    assert call["argv"] == [sys.executable, stub, "qwenedit", "--spec", os.path.join(work, "qwenedit_spec.json")]
    assert call["env"] == {"PYTHONUNBUFFERED": "1"}
    assert call["spec"] == {
        "image": srcs[0], "model": "Qwen/Qwen-Image-Edit-2511", "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
        "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
        "skill": "location_edit",
        "jobs": [{"prompt": "north view", "output_path": jobs[0]["stage_path"], "seed": 11, "width": 1024,
                  "height": 640},
                 {"prompt": "south view", "output_path": jobs[1]["stage_path"], "seed": 12, "width": 1024,
                  "height": 640, "image": srcs[1]},
                 {"prompt": "east view", "output_path": jobs[2]["stage_path"], "seed": 13, "width": 1024,
                  "height": 640}],
        "report_path": os.path.join(work, "qwenedit_report.json")}
    assert [(r["status"], r["seconds"]) for r in results] == [("ok", 1.0), ("blocked", 1.0), ("ok", 1.0)]
    assert [os.path.exists(j["output_path"]) for j in jobs] == [True, False, True]
    assert env["calls"]["safety"] == []


# --- QET8 (QE8, QE11): the timer gets child_timeout(jobs), and the log gets every child line ---------------------

def test_qet8_the_timeout_and_the_log(env):
    _mflux_ready(env)
    seen, real = [], qe.run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append((timeout_s, log_path))
        return real(argv, child_env, on_line, timeout_s, log_path)

    env["mp"].setattr(qe, "run_child", spy)
    log = os.path.join(env["tmp"], "edit.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("earlier line\n")
    jobs = _jobs(env, _sources(env))
    assert qe.run_jobs("qwen21-q4", UNC, jobs, 1024, 640, "location_edit", os.path.join(env["tmp"], "w"),
                       log_path=log)[1] is None
    assert qe.run_jobs("qwen21-q4", UNC, jobs[:1], 1024, 640, "location_edit", os.path.join(env["tmp"], "w2"))[1] is None
    assert seen == [(qe.child_timeout(3), log), (qe.child_timeout(1), None)]
    with open(log, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "earlier line"
    assert [line for line in lines if line.startswith("seed-edit-child done")] == [
        "seed-edit-child done %d 1.0" % n for n in (1, 2, 3)]


# --- QET9 (QE7): the memory wait --------------------------------------------------------------------------------

def test_qet9_wait_for_memory(env, capsys):
    env["mp"].setattr(qe, "avail_gib", lambda: 10.0)
    env["mp"].setattr(qe, "AVAIL_WAIT_S", 0)
    with pytest.raises(qe.Unavailable) as info:
        qe.wait_for_memory(20, "Qwen-Image-2.1 q4", tag="ltx-movie")
    assert str(info.value) == ("only 10.0 GiB available after waiting 0 s; Qwen-Image-2.1 q4 needs 20 GiB; free "
                               "memory and retry")
    assert capsys.readouterr().out == "ltx-movie: waiting up to 0 s for 20 GiB available (now 10.0 GiB)\n"
    env["mp"].setattr(qe, "avail_gib", lambda: 25.0)
    qe.wait_for_memory(20.0, "Qwen-Image-2.1 q4")
    assert capsys.readouterr().out == ""


# --- QET10 (QE17, QE18): the child reads each job's prompt and source, and the old spec shape --------------------

def test_qet10_the_child_takes_per_job_prompt_and_source(monkeypatch, tmp_path, capsys):
    import seed_edit_mflux_child as child
    monkeypatch.setattr(child, "exit_with_parent", lambda poll_s=2.0: None)
    monkeypatch.setattr(child.importlib.metadata, "version", lambda name: "0.24.0")
    record = st.child_fakes(monkeypatch)
    tmp = str(tmp_path)
    a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
    spec = {"family": "qwen21", "model_path": os.path.join(tmp, "model"), "lora_paths": [], "lora_scales": [],
            "width": 64, "height": 96, "steps": 40, "guidance": 1.0, "scheduler": "linear",
            "jobs": [{"n": 1, "seed": 11, "prompt": "north view", "source": a, "output_path": os.path.join(tmp, "1.png")},
                     {"n": 2, "seed": 12, "prompt": "south view", "source": b,
                      "output_path": os.path.join(tmp, "2.png")}]}
    path = os.path.join(tmp, "new-shape.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    assert child.main(["--spec", path]) == 0
    common = {"num_inference_steps": 40, "guidance": 1.0, "width": 64, "height": 96, "scheduler": "linear"}
    assert [kwargs for _name, kwargs in record["generate"]] == [
        dict(common, seed=11, prompt="north view", image_paths=[a]),
        dict(common, seed=12, prompt="south view", image_paths=[b])]
    record["init"], record["generate"] = [], []
    path, old = st.child_spec(tmp_path, "qwen21", [], [], "linear")
    assert "prompt" not in old["jobs"][0] and "source" not in old["jobs"][0]
    assert child.main(["--spec", path]) == 0
    assert [kwargs for _name, kwargs in record["generate"]] == [
        dict(common, seed=11, prompt=st.PROMPT, image_paths=[old["source"]])]
    with open(os.path.join(WS, "seed_edit_mflux_child.py"), encoding="utf-8") as f:
        source = f.read()
    assert 'prompt = job["prompt"] if "prompt" in job else spec["prompt"]' in source
    assert 'source = job["source"] if "source" in job else spec["source"]' in source
    capsys.readouterr()


# --- QET11 (QE1, QE70): the imports and the new files ---------------------------------------------------------

def test_qet11_imports_and_the_new_files(tmp_path):
    with open(os.path.join(WS, "qwen_edit.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "glob", "importlib.util", "json", "os", "re", "signal", "subprocess", "sys", "threading", "time",
        "movie_ui_lib", "movie_ui_seedgen"]
    proc = subprocess.run([sys.executable, "-B", "-X", "importtime", "-c", "import qwen_edit"], cwd=WS,
                          capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "movie_ui_seedgen" in imported
    assert not imported & HEAVY, sorted(imported & HEAVY)
    with open(os.path.join(WS, "tests", "test_movie_ui_builder.py"), encoding="utf-8") as f:
        builder = f.read()
    start = builder.index("NEW_PY = (")
    new_py = re.findall(r'"([^"]+)"', builder[start:builder.index(")", start)])
    assert new_py[new_py.index("tests/test_movie_ui_seedgen.py") + 1:] == ["qwen_edit.py", "tests/test_qwen_edit.py"]
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'qwen_edit'` (1 error). Also run `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_builder.py 2>&1 | tail -1`: exactly 3 failures, the two `test_mut25_every_new_and_changed_file_compiles` cases (`py_compile` cannot open `qwen_edit.py`) and `test_mut25_source_scan_of_new_python_files` (`FileNotFoundError` for `qwen_edit.py`); every Seeds test passes (the stub's new `silent` key is unused so far).

- [ ] **Step 3: Write the implementation.**

Write `qwen_edit.py` with exactly this content (the Write tool):

```python
"""qwen_edit -- the shared Qwen edit runner (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md,
Section 2): the selection checks (is a registry model and its LoRAs installed, does the host reach the
model's memory floor) and one child run over a list of edit jobs, every output screened with content
safety. bin/seed-edit, location_dataset.py and character_dataset.py import it; bin/ltx-movie loads it by
path, and only when --seed-edit-model names a registry model.

The mflux registry models run seed_edit_mflux_child.py under the mflux venv's Python, offline and with no
Hugging Face token in its environment, and this process screens every output before it gets its final
name; qwen2511-bf16 runs the unchanged character_dataset.py qwenedit child, which screens each output
itself. The child timeout is max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S x jobs) seconds.

Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python), SEED_EDIT_QWENEDIT_SCRIPT
(default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The mflux weights and LoRAs are looked up only at
their pinned revisions, in the Z-Image hub and then the default hub.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib and movie_ui_seedgen;
PIL, psutil and content_safety are imported inside the functions that use them.
"""

import glob
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

WS = os.path.dirname(os.path.realpath(__file__))
EDIT_MODEL = "Qwen/Qwen-Image-Edit-2511"                                  # character_dataset.EDIT_MODEL
EDIT_LORA_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"                # character_dataset.EDIT_LORA_REPO
EDIT_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
EDIT_STEPS = 8
EDIT_TRUE_CFG = 1.0
LEGACY_EDIT_MODEL = "qwen2511-bf16"
MODEL_IDS = seedgen.QWEN_MODEL_IDS
MFLUX_MIN_VERSION = (0, 24, 0)
MFLUX_GUIDANCE = 1.0
DEFAULT_MFLUX_PYTHON = "~/mflux-edit/.venv/bin/python"   # expanded at use
AVAIL_WAIT_S = 600               # character_dataset.AVAIL_WAIT_S
CHILD_TIMEOUT_S = 3600           # the timeout floor (bin/seed-edit's former fixed timeout)
JOB_TIMEOUT_S = 600              # the budget per job above the floor
MFLUX_LINE_RE = re.compile(r"^seed-edit-child done (\d+) ([0-9]+\.[0-9])$")
QWENEDIT_LINE_RE = re.compile(r"^(\S+) (ok|blocked) ([0-9]+\.[0-9])s$")
CHILD = None    # the running Qwen child's Popen, or None


class SelectionError(Exception):
    """A bad edit-model or LoRA option; the message is the refusal text."""


class Unavailable(Exception):
    """The selection cannot run here now; the message is the refusal text."""


# ---------------------------------------------------------------------------
# Host checks and the registry lookups (moved from bin/seed-edit; seed models SQ15-SQ18)
# ---------------------------------------------------------------------------

def avail_gib():
    import psutil
    return psutil.virtual_memory().available / 2 ** 30


def total_gib():
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except (ValueError, OSError):
        return None


def missing_modules(names):
    """The names importlib cannot find (find_spec None, ImportError or ValueError); imports nothing."""
    missing = []
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def modules_problem(names):
    missing = missing_modules(names)
    return "%s not importable by %s" % (", ".join(missing), sys.executable) if missing else None


def default_hub():
    """$HF_HUB_CACHE, else <$HF_HOME or ~/.cache/huggingface>/hub (huggingface_hub's own rule)."""
    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]
    return os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub")


def mflux_python():
    return os.environ.get("SEED_EDIT_MFLUX_PYTHON") or os.path.expanduser(DEFAULT_MFLUX_PYTHON)


def find_lightning(hubs):
    """The snapshot path of the Lightning LoRA file in the first hub holding it (a non-empty regular
    file through its realpath), or None."""
    for hub in hubs:
        snapshot = lib.choose_snapshot(os.path.join(hub, lib.repo_dir_name(EDIT_LORA_REPO)))[0]
        if snapshot is None:
            continue
        path = os.path.join(snapshot, EDIT_LORA_FILE)
        real = os.path.realpath(path)
        if os.path.isfile(real) and os.path.getsize(real) > 0:
            return path
    return None


def bf16_problem():
    """None when the diffusers bf16 child's weights and modules are present, else the first problem."""
    problem = modules_problem(["PIL", "psutil", "torch", "diffusers", "transformers", "huggingface_hub"])
    if problem:
        return problem
    hub = default_hub()
    ok, detail = lib.model_check(EDIT_MODEL, hub)
    if not ok:
        return detail
    if find_lightning([hub]) is None:
        return "Lightning LoRA %s is not in %s" % (EDIT_LORA_FILE, hub)
    return None


def mflux_version(venv):
    """(number of mflux-*.dist-info/METADATA files in venv, (parsed, text) of the highest version that
    parses or None). Reads the files only; nothing is imported."""
    paths = sorted(glob.glob(os.path.join(venv, "lib", "python*", "site-packages", "mflux-*.dist-info",
                                          "METADATA")))
    best = None
    for path in paths:
        text = None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Version: "):
                        text = line[len("Version: "):].strip()
                        break
        except OSError:
            continue
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
        if match:
            parsed = tuple(int(g) for g in match.groups())
            if best is None or parsed > best[0]:
                best = (parsed, text)
    return len(paths), best


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


def qwen_hubs():
    """Seed models SQ16: the hubs searched for the mflux weights and LoRAs, in order."""
    return [lib.zimage_hub(), default_hub()]


def mflux_env_problem(entry):
    """Seed models SQ16 (amended by §14a item H): None when the mflux venv holds mflux 0.24.0 or newer,
    else the first problem. The setup hint names entry's own --model, so one setup run installs the
    venv and that model."""
    setup = "(run bin/seed-edit-setup --model %s)" % entry["id"]
    py = mflux_python()
    if not os.access(py, os.X_OK):
        return "no mflux venv at %s %s" % (py, setup)
    venv = os.path.dirname(os.path.dirname(py))
    count, best = mflux_version(venv)
    if count == 0:
        return "mflux is not installed in %s %s" % (venv, setup)
    if best is None:
        return "cannot read the mflux version in %s" % venv
    if best[0] < MFLUX_MIN_VERSION:
        return "mflux %s in %s is older than 0.24.0 %s" % (best[1], venv, setup)
    return None


def lora_problem(lora, hubs):
    """Seed models SQ16: (None, snapshot path) of a registry LoRA's pinned file, else (problem, None)."""
    path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
    if path is None:
        return ("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]),
                None)
    return None, path


def qwen_model_problem(entry):
    """Seed models SQ16: (problem, paths) of a registry model; paths is {"model_path", "builtin_lora"}
    for a ready mflux entry, else {}."""
    if entry["backend"] == "diffusers":
        return bf16_problem(), {}
    problem = mflux_env_problem(entry)
    if problem is not None:
        return problem, {}
    problem, model_path, builtin_lora = weights_problem(entry, qwen_hubs())
    if problem is not None:
        return problem, {}
    problem = modules_problem(["PIL", "psutil", "torch", "transformers"])
    if problem is not None:
        return problem, {}
    return None, {"model_path": model_path, "builtin_lora": builtin_lora}


def memory_problem(entry):
    """Seed models SQ16: None when this host's total memory reaches the entry's floor, else why not."""
    t = total_gib()
    if t is None:
        return "cannot read this host's memory size"
    if t < entry["memory_gib"]:
        return "needs a host with at least %g GiB of memory (this host has %.1f GiB)" % (entry["memory_gib"], t)
    return None


def wait_for_memory(floor, label, tag="seed-edit"):
    """SG13 step 4, qwen edit models QE7: wait up to AVAIL_WAIT_S for floor GiB available, else
    Unavailable. tag starts the waiting line (seed-edit, ltx-movie)."""
    now = avail_gib()
    if now >= floor:
        return
    print("%s: waiting up to %d s for %g GiB available (now %.1f GiB)" % (tag, AVAIL_WAIT_S, floor, now), flush=True)
    deadline = time.monotonic() + AVAIL_WAIT_S
    while True:
        now = avail_gib()
        if now >= floor:
            return
        if time.monotonic() >= deadline:
            raise Unavailable("only %.1f GiB available after waiting %d s; %s needs %g GiB; free memory and retry"
                              % (now, AVAIL_WAIT_S, label, floor))
        time.sleep(5)


# ---------------------------------------------------------------------------
# The child (SG21, qwen edit models QE8, QE9)
# ---------------------------------------------------------------------------

def _kill_group(pid):
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def run_child(argv, env, on_line, timeout_s, log_path=None):
    """SG21, qwen edit models QE8: run a Qwen child in its own session with a timeout_s timer that
    SIGKILLs its process group; echo each line to stdout (and append it to log_path when given) and
    pass it to on_line without its newline. Text mode reads with universal newlines, so a progress
    bar's carriage return also ends a line and never hides a result line. Returns (exit code, True
    when the timer killed the child); any other SIGKILL (a memory-pressure kill) is an ordinary -9
    exit. The child is killed if this function exits early (an exception in on_line, or an
    interrupt)."""
    global CHILD
    proc = subprocess.Popen(argv, cwd=WS, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            bufsize=1, start_new_session=True)
    CHILD = proc
    timed_out = threading.Event()

    def on_timeout():
        if proc.poll() is None:
            timed_out.set()
            _kill_group(proc.pid)

    timer = threading.Timer(timeout_s, on_timeout)
    timer.daemon = True
    timer.start()
    log = None
    try:
        if log_path is not None:
            log = open(log_path, "a", encoding="utf-8")
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if log is not None:
                log.write(line)
                log.flush()
            on_line(line.rstrip("\n"))
        return proc.wait(), timed_out.is_set()
    finally:
        timer.cancel()
        if proc.poll() is None:
            _kill_group(proc.pid)
            proc.wait()
        proc.stdout.close()
        if log is not None:
            log.close()
        CHILD = None


def kill_running_child():
    """Qwen edit models QE9: SIGKILL the running Qwen child's process group, if there is one."""
    if CHILD is not None:
        _kill_group(CHILD.pid)


# ---------------------------------------------------------------------------
# The selection (qwen edit models Section 2.3, 2.4)
# ---------------------------------------------------------------------------

def check_lora_args(values, entry, flag="--lora"):
    """bin/seed-edit's check_loras (seed models SQ12 rows 12-16) with the flag name as a parameter:
    the cleaned [{"id", "scale"}] in registry order, or SelectionError."""
    loras = []
    for value in values:
        match = re.match(r"^([a-z0-9-]+)=(.*)$", value)
        if not match:
            raise SelectionError("%s must be ID=SCALE (got %s)" % (flag, value))
        lora_id, text = match.group(1), match.group(2)
        if lora_id not in seedgen.QWEN_LORA_IDS:
            raise SelectionError("%s: unknown LoRA %s; known: %s" % (flag, lora_id, ", ".join(seedgen.QWEN_LORA_IDS)))
        if any(item["id"] == lora_id for item in loras):
            raise SelectionError("%s %s is given twice" % (flag, lora_id))
        lora = seedgen.qwen_lora(lora_id)
        if lora["family"] != entry["family"]:
            raise SelectionError("%s %s is for %s, not %s" % (flag, lora_id, seedgen.QWEN_FAMILIES[lora["family"]],
                                                              entry["label"]))
        try:
            scale = float(text)
        except ValueError:
            scale = None
        if scale is None or not 0 < scale <= seedgen.SCALE_MAX:
            raise SelectionError("%s %s scale must be a number above 0 and at most 2" % (flag, lora_id))
        loras.append({"id": lora_id, "scale": scale})
    return seedgen.registry_order(loras)


def cli_selection(model_arg, lora_args, model_flag="--qwen-model", lora_flag="--lora"):
    """(model_id, loras) of a tool's edit-model options, or SelectionError (qwen edit models QE10)."""
    if model_arg is None:
        if lora_args is not None:
            raise SelectionError("%s needs %s" % (lora_flag, model_flag))
        return seedgen.DEFAULT_QWEN_MODEL, seedgen.default_loras(seedgen.DEFAULT_QWEN_MODEL)
    if model_arg not in MODEL_IDS:
        raise SelectionError("%s must be one of %s" % (model_flag, ", ".join(MODEL_IDS)))
    return model_arg, check_lora_args(lora_args or [], seedgen.qwen_model(model_arg), lora_flag)


def settings(model_id, loras):
    return seedgen.qwen_settings(model_id, loras)


def selection_of(edit):
    """(model_id, [{"id", "scale"}]) of a recorded settings block."""
    return edit["qwen_model"]["id"], [{"id": l["id"], "scale": l["scale"]} for l in edit["loras"]]


def label(model_id):
    return seedgen.qwen_model(model_id)["label"]


def multiple(model_id):
    return seedgen.qwen_model(model_id)["multiple"]


def memory_floor(model_id):
    return seedgen.qwen_model(model_id)["memory_gib"]


def child_timeout(n_jobs):
    return max(CHILD_TIMEOUT_S, JOB_TIMEOUT_S * n_jobs)


def generator_text(model_id, loras):
    """The manifest "generator" string of a selection; the legacy model keeps today's exact text."""
    if model_id == LEGACY_EDIT_MODEL:
        return "%s + %s, %d steps" % (EDIT_MODEL, EDIT_LORA_FILE, EDIT_STEPS)
    entry, chosen = seedgen.qwen_model(model_id), seedgen.qwen_settings(model_id, loras)
    listed = ", ".join("%s@%g" % (l["id"], l["scale"]) for l in chosen["loras"]) or "none"
    return "%s (%s) + LoRAs %s, %d steps" % (entry["label"], entry["repo"], listed, chosen["steps"])


def install_problem(model_id, loras):
    """(None, paths) when the selection is installed, else (refusal text, {}); paths is
    {"model_path", "builtin_lora", "lora_paths"} ({} entries for the diffusers model). The texts are
    bin/seed-edit's SQ21 steps 1-2."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = qwen_model_problem(entry)
    if problem is not None:
        return "%s is unavailable: %s" % (entry["label"], problem), {}
    lora_paths = []
    for item in seedgen.registry_order(loras):
        lora = seedgen.qwen_lora(item["id"])
        problem, path = lora_problem(lora, qwen_hubs())
        if problem is not None:
            return "LoRA %s is unavailable: %s" % (lora["label"], problem), {}
        lora_paths.append(path)
    return None, dict(paths, lora_paths=lora_paths)


def selection_problem(model_id, loras):
    """None when the selection can run on this host (its total memory reaches the entry's memory_gib
    and it is installed), else the refusal text. Memory first, as the probe (seed models SQ18)."""
    entry = seedgen.qwen_model(model_id)
    memory = memory_problem(entry)
    if memory is not None:
        return "%s is unavailable: %s" % (entry["label"], memory)
    return install_problem(model_id, loras)[0]


# ---------------------------------------------------------------------------
# run_jobs (qwen edit models QE13-QE16)
# ---------------------------------------------------------------------------

def run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job"):
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16)."""
    entry = seedgen.qwen_model(model_id)
    problem, paths = install_problem(model_id, loras)
    if problem is not None:
        raise Unavailable(problem)
    os.makedirs(work_dir, exist_ok=True)
    chosen = seedgen.qwen_settings(model_id, loras)
    by_n = dict((job["n"], job) for job in jobs)
    done = {}

    def finish(n, status, seconds):
        done[n] = (status, seconds)
        if on_result is not None:
            on_result({"n": n, "output_path": by_n[n]["output_path"], "status": status, "seconds": seconds})

    if entry["backend"] == "diffusers":
        first = jobs[0]["source"]
        spec_jobs = []
        for job in jobs:
            item = {"prompt": job["prompt"], "output_path": job["stage_path"], "seed": job["seed"],
                    "width": width, "height": height}
            if job["source"] != first:
                item["image"] = job["source"]
            spec_jobs.append(item)
        spec_path = os.path.join(work_dir, "qwenedit_spec.json")
        lib.write_json_atomic(spec_path, {
            "image": first, "model": EDIT_MODEL, "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE,
            "steps": EDIT_STEPS, "true_cfg": EDIT_TRUE_CFG, "skill": skill, "jobs": spec_jobs,
            "report_path": os.path.join(work_dir, "qwenedit_report.json")})
        by_stage = dict((os.path.basename(job["stage_path"]), job["n"]) for job in jobs)
        script = os.environ.get("SEED_EDIT_QWENEDIT_SCRIPT") or os.path.join(WS, "character_dataset.py")
        argv = [sys.executable, script, "qwenedit", "--spec", spec_path]
        env = dict(os.environ, PYTHONUNBUFFERED="1")

        def handle(line):
            match = QWENEDIT_LINE_RE.match(line)
            n = by_stage.get(match.group(1)) if match else None
            if n is None or n in done:
                return
            if match.group(2) == "ok":
                os.replace(by_n[n]["stage_path"], by_n[n]["output_path"])
            finish(n, match.group(2), float(match.group(3)))
    else:
        import content_safety
        from PIL import Image
        builtin = entry["builtin_lora"]
        ordered = seedgen.registry_order(loras)
        spec_path = os.path.join(work_dir, "mflux_spec.json")
        lib.write_json_atomic(spec_path, {
            "family": entry["family"], "model_path": paths["model_path"],
            "lora_paths": ([paths["builtin_lora"]] if builtin is not None else []) + paths["lora_paths"],
            "lora_scales": ([builtin["scale"]] if builtin is not None else []) + [item["scale"] for item in ordered],
            "width": width, "height": height, "steps": chosen["steps"], "guidance": MFLUX_GUIDANCE,
            "scheduler": chosen["scheduler"],
            "jobs": [{"n": job["n"], "seed": job["seed"], "prompt": job["prompt"], "source": job["source"],
                      "output_path": job["stage_path"]} for job in jobs]})
        argv = [mflux_python(), os.path.join(WS, "seed_edit_mflux_child.py"), "--spec", spec_path]
        env = seedgen.hf_child_env(os.environ, PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1")

        def handle(line):
            match = MFLUX_LINE_RE.match(line)
            n = int(match.group(1)) if match else None
            if n not in by_n or n in done:
                return
            job = by_n[n]
            with Image.open(job["stage_path"]) as img:
                rgb = img.convert("RGB")
            try:
                content_safety.assert_image_safe(rgb, skill=skill, prompt=job["prompt"])
            except content_safety.ContentSafetyError:
                os.remove(job["stage_path"])
                finish(n, "blocked", float(match.group(2)))
                return
            os.replace(job["stage_path"], job["output_path"])
            finish(n, "ok", float(match.group(2)))

    last = [""]

    def on_line(line):
        if line.strip():
            last[0] = line.strip()
        handle(line)

    timeout = child_timeout(len(jobs))
    code, timed_out = run_child(argv, env, on_line, timeout, log_path)
    failure = None
    if timed_out:
        failure = "%s child timed out after %d s" % (entry["label"], timeout)
    elif code != 0:
        failure = "%s child exited %d: %s" % (entry["label"], code, last[0] or "-")
    else:
        missing = [job["n"] for job in jobs if job["n"] not in done]
        if missing:
            failure = "%s child exited 0 without finishing %s %d" % (entry["label"], noun, missing[0])
    for job in jobs:
        if job["n"] not in done and os.path.exists(job["stage_path"]):
            os.remove(job["stage_path"])      # plan ruling R4: a failed job leaves no staged file (QE13)
    results = [{"n": job["n"], "output_path": job["output_path"],
                "status": done[job["n"]][0] if job["n"] in done else "failed",
                "seconds": done[job["n"]][1] if job["n"] in done else None} for job in jobs]
    return results, failure
```

Edit `seed_edit_mflux_child.py`: replace this text, which occurs exactly once:

```text
The spec carries family, model_path, lora_paths and lora_scales (equal-length lists, possibly
empty), prompt, source, width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and
jobs. Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
```

with:

```text
The spec carries family, model_path, lora_paths and lora_scales (equal-length lists, possibly
empty), width, height, steps, guidance (always 1.0), scheduler (qwen21 only) and jobs, each {n,
seed, prompt, source, output_path}; a spec-level prompt and source (the shape before
docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) are used for jobs that carry none.
Runs under the mflux venv's Python (mflux pinned to 0.24.0). It never screens: bin/seed-edit
```

Edit `seed_edit_mflux_child.py`: replace this text, which occurs exactly once:

```python
        kwargs = {"seed": job["seed"], "prompt": spec["prompt"], "image_paths": [spec["source"]],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
```

with:

```python
        prompt = job["prompt"] if "prompt" in job else spec["prompt"]
        source = job["source"] if "source" in job else spec["source"]
        kwargs = {"seed": job["seed"], "prompt": prompt, "image_paths": [source],
                  "num_inference_steps": spec["steps"], "guidance": spec["guidance"],
                  "width": spec["width"], "height": spec["height"]}
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_builder.py 2>&1 | tail -1`
Expected: `N passed` with no failure (Review Focus 1 and QET1-QET11: 12 new tests).

Run the compile check with `FILES` = `qwen_edit.py seed_edit_mflux_child.py tests/test_qwen_edit.py tests/test_seed_edit_tool.py tests/test_movie_ui_builder.py`. Expected: `compiled 5` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=1`. Expected: `GATE PASS`, `lost 0 (listed 0, unexpected 0); new tests 12, not passing 0; baseline failures still failing 2 of 2`, `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add qwen_edit.py seed_edit_mflux_child.py tests/test_qwen_edit.py tests/test_seed_edit_tool.py tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly those five paths, with the qwen-agent-workspace/ prefix
git commit -m "qwen_edit: the shared Qwen edit runner and the mflux child's per-job prompt and source (qwen edit models QE1-QE18, QET1-QET11)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `bin/seed-edit` on top of `qwen_edit.py`, behaviour unchanged (QE19-QE23, QEK3; QET12, Review Focus 2)

This task implements:
- QE19: `bin/seed-edit`'s top-level imports become exactly `argparse`, `glob`, `json`, `os`, `re`, `secrets`, `shutil`, `signal`, `sys`, `time`, `movie_ui_lib as lib`, `movie_ui_seedgen as seedgen`, `qwen_edit as qe`.
- QE20: the moved functions, `wait_for_memory`, `run_child`, `run_qwen_child`, `run_bf16`, `run_mflux`, `pending_candidate`, `check_loras` and the moved constants are removed.
- QE21: `check_args`, `zimage_problem`, `probe`, `preflight`, `run` and `main` call `qe.*` (texts unchanged); QE22 `run_qwen`; QE23 the docstring (plus R14's import sentence).
- The §11.3 edits of `tests/test_seed_edit_tool.py` (the `env` fixture's `qe`, every moved name, the SQT3 grep, the SQT5/SGT9 spec dicts, SGT10's `JOB_TIMEOUT_S`, the `test_sq_final_b` spy) and of `tests/test_movie_ui_seedgen.py` (SQT18 compares `bin/seed-edit-setup` with `qwen_edit.py`; SGT34's import list); new QET12 and Review Focus 2.

`bin/seed-edit` is replaced whole (Write after Read): the change is mostly the deletion of 330 lines, and the kept functions are byte for byte today's except the QE21 lines.

**Files:**
- Replace: `bin/seed-edit` (mode stays `100755`).
- Modify: `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_seedgen.py`.

**Interfaces:**
- Consumes (Task 1, `qwen_edit`): `SelectionError`, `Unavailable`, `check_lora_args`, `modules_problem`, `qwen_hubs`, `memory_problem`, `qwen_model_problem`, `lora_problem`, `install_problem`, `wait_for_memory`, `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job")`, `kill_running_child`, the moved constants (`CHILD`, `CHILD_TIMEOUT_S`, `JOB_TIMEOUT_S`, `AVAIL_WAIT_S`, `EDIT_*`, `MFLUX_MIN_VERSION`).
- Produces: `bin/seed-edit`'s module attribute `qe` (the `qwen_edit` module; tests reach the moved names as `tool.qe`), and `run_qwen(ctx) -> None or the SG17 failure text`. Every other name the tests use on `tool` (`main`, `parse`, `check_args`, `canvas`, `Refusal`, `probe`, `say`, `run`, `disk_free_gib`, `cpu_generator`, `ZIMAGE_MIN_AVAIL_GIB`, `MIN_FREE_GIB`) is unchanged.

- [ ] **Step 1: Write the failing tests and the §11.3 edits.**

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    tool = load_tool()
    gens = []
    monkeypatch.setattr(tool, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(tool, "total_gib", lambda: 48.0)
    monkeypatch.setattr(tool, "missing_modules", lambda names: [])
    monkeypatch.setattr(tool, "disk_free_gib", lambda path: 100.0)
    monkeypatch.setattr(tool, "cpu_generator", lambda seed: gens.append(seed) or seed)
    return {"tmp": tmp, "tool": tool, "gens": gens, "calls": make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}
```

with:

```python
    tool = load_tool()
    qe = tool.qe
    gens = []
    monkeypatch.setattr(qe, "avail_gib", lambda: 40.0)
    monkeypatch.setattr(qe, "total_gib", lambda: 48.0)
    monkeypatch.setattr(qe, "missing_modules", lambda names: [])
    monkeypatch.setattr(tool, "disk_free_gib", lambda path: 100.0)
    monkeypatch.setattr(tool, "cpu_generator", lambda seed: gens.append(seed) or seed)
    return {"tmp": tmp, "tool": tool, "qe": qe, "gens": gens, "calls": make_fakes(monkeypatch), "mp": monkeypatch,
            "zhub": os.path.join(tmp, "zi", "hub"), "hfhub": os.path.join(tmp, "hf", "hub")}
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    root, tool = os.path.join(env["tmp"], "hf"), env["tool"]
    mt.make_hf_cache(root, tool.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
```

with:

```python
    root, qe = os.path.join(env["tmp"], "hf"), env["qe"]
    mt.make_hf_cache(root, qe.EDIT_MODEL, {"transformer/x.safetensors": b"\x01" * 8})
    mt.make_hf_cache(root, qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    mp.setattr(tool, "missing_modules", lambda names: ["torch"])
    code, run_dir = run_tool(env, run=R3)
    assert code == 2
    _refused(run_dir, "Z-Image is unavailable: torch not importable by %s" % sys.executable, capsys.readouterr())
    mp.setattr(tool, "missing_modules", lambda names: [])
    mp.setattr(tool, "avail_gib", lambda: 10.0)
    mp.setattr(tool, "AVAIL_WAIT_S", 0)
```

with:

```python
    mp.setattr(env["qe"], "missing_modules", lambda names: ["torch"])
    code, run_dir = run_tool(env, run=R3)
    assert code == 2
    _refused(run_dir, "Z-Image is unavailable: torch not importable by %s" % sys.executable, capsys.readouterr())
    mp.setattr(env["qe"], "missing_modules", lambda names: [])
    mp.setattr(env["qe"], "avail_gib", lambda: 10.0)
    mp.setattr(env["qe"], "AVAIL_WAIT_S", 0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sqt3_the_pinned_lookups(env):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
    hubs, where = [zhub, hfhub], "%s or %s" % (zhub, hfhub)
    q8 = seedgen.qwen_model("qwen21-q8")
    absent = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
              "(run bin/seed-edit-setup --model qwen21-q8)" % where)
    assert tool.weights_problem(q8, hubs) == (absent, None, None)
    mt.make_hf_cache(os.path.join(env["tmp"], "hf"), q8["repo"], QWEN21_FILES)
    assert tool.weights_problem(q8, hubs) == (absent, None, None)
    q8_snapshot, _none = install_model(env, "qwen21-q8")
    assert tool.weights_problem(q8, hubs) == (None, q8_snapshot, None)
    q4 = seedgen.qwen_model("qwen21-q4")
    snapshot, _none = install_model(env, "qwen21-q4")
    with open(os.path.join(os.path.dirname(os.path.dirname(snapshot)), "blobs", "partial0.incomplete"), "wb") as f:
        f.write(b"x")
    assert tool.weights_problem(q4, hubs) == (
        "mflux-community/qwen-image-2-1-mflux-q4: download incomplete: 1 partial blob(s) "
        "(run bin/seed-edit-setup --model qwen21-q4)", None, None)
    bf16 = seedgen.qwen_model("qwen21-bf16")
    files = dict(QWEN21_FILES)
    del files["vae/config.json"], files["processor/tokenizer.json"]
    install_model(env, "qwen21-bf16", files=files)
    assert tool.weights_problem(bf16, hubs) == (
        "Qwen/Qwen-Image-2.1: missing vae/config.json; missing processor/ (run bin/seed-edit-setup --model qwen21-bf16)",
        None, None)
    e2511 = seedgen.qwen_model("qwen2511-q4")
    only = pinned_cache(os.path.join(env["tmp"], "hf"), e2511["repo"], e2511["revision"],
                        {"transformer/0.safetensors": b"\x01" * 8})
    mt.make_hf_cache(os.path.join(env["tmp"], "zi"), tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
    assert tool.weights_problem(e2511, hubs) == (
        "Lightning LoRA Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors is not in %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % where, None, None)
    lightning = os.path.join(pinned_cache(os.path.join(env["tmp"], "hf"), tool.EDIT_LORA_REPO,
                                          e2511["builtin_lora"]["revision"], {tool.EDIT_LORA_FILE: b"\x01" * 8}),
                             tool.EDIT_LORA_FILE)
    assert tool.weights_problem(e2511, hubs) == (None, only, lightning)
    unc = seedgen.qwen_lora("uncensored")
    missing = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
               % where)
    assert tool.lora_problem(unc, hubs) == (missing, None)
    pinned_cache(os.path.join(env["tmp"], "zi"), unc["repo"], unc["revision"], {unc["file"]: b""})
    assert tool.lora_problem(unc, hubs) == (missing, None)
    found = install_lora(env, "uncensored", root="hf")
    assert tool.lora_problem(unc, hubs) == (None, found)
    py = os.path.join(env["tmp"], "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    hint = "(run bin/seed-edit-setup --model qwen21-q8)"
    assert tool.mflux_env_problem(q8) == "no mflux venv at %s %s" % (py, hint)
    mflux_venv(env, version=None)
    assert tool.mflux_env_problem(q8) == "mflux is not installed in %s %s" % (venv, hint)
    set_mflux_version(venv, "banana")
    assert tool.mflux_env_problem(q8) == "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.23.9")
    assert tool.mflux_env_problem(q8) == "mflux 0.23.9 in %s is older than 0.24.0 %s" % (venv, hint)
    assert tool.mflux_env_problem(q4) == ("mflux 0.23.9 in %s is older than 0.24.0 "
                                          "(run bin/seed-edit-setup --model qwen21-q4)" % venv)
    for version in ("0.24.0", "0.25.1"):
        set_mflux_version(venv, version)
        assert tool.mflux_env_problem(q8) is None
    assert tool.qwen_model_problem(q8) == (None, {"model_path": q8_snapshot, "builtin_lora": None})
    mp.setattr(tool, "missing_modules", lambda names: ["torch"])
    assert tool.qwen_model_problem(q8) == ("torch not importable by %s" % sys.executable, {})
    assert tool.qwen_hubs() == [zhub, hfhub]
    assert tool.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("SEED_EDIT_QWEN_Q4_DIR", "SEED_EDIT_LIGHTNING_FILE", "def choose_qwen(", "def mflux_problem(",
                 "BF16_MIN_AVAIL_GIB", "MFLUX_MIN_AVAIL_GIB", "Q4_REPO", "Q4_NAME_PART"):
        assert gone not in source, gone
    assert set(re.findall(r"os\.environ(?:\.get\(|\[)\"([A-Z0-9_]+)\"", source)) == {
        "SEED_EDIT_MFLUX_PYTHON", "SEED_EDIT_QWENEDIT_SCRIPT", "HF_HUB_CACHE", "HF_HOME"}
```

with:

```python
def test_sqt3_the_pinned_lookups(env):
    qe, mp, zhub, hfhub = env["qe"], env["mp"], env["zhub"], env["hfhub"]
    hubs, where = [zhub, hfhub], "%s or %s" % (zhub, hfhub)
    q8 = seedgen.qwen_model("qwen21-q8")
    absent = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
              "(run bin/seed-edit-setup --model qwen21-q8)" % where)
    assert qe.weights_problem(q8, hubs) == (absent, None, None)
    mt.make_hf_cache(os.path.join(env["tmp"], "hf"), q8["repo"], QWEN21_FILES)
    assert qe.weights_problem(q8, hubs) == (absent, None, None)
    q8_snapshot, _none = install_model(env, "qwen21-q8")
    assert qe.weights_problem(q8, hubs) == (None, q8_snapshot, None)
    q4 = seedgen.qwen_model("qwen21-q4")
    snapshot, _none = install_model(env, "qwen21-q4")
    with open(os.path.join(os.path.dirname(os.path.dirname(snapshot)), "blobs", "partial0.incomplete"), "wb") as f:
        f.write(b"x")
    assert qe.weights_problem(q4, hubs) == (
        "mflux-community/qwen-image-2-1-mflux-q4: download incomplete: 1 partial blob(s) "
        "(run bin/seed-edit-setup --model qwen21-q4)", None, None)
    bf16 = seedgen.qwen_model("qwen21-bf16")
    files = dict(QWEN21_FILES)
    del files["vae/config.json"], files["processor/tokenizer.json"]
    install_model(env, "qwen21-bf16", files=files)
    assert qe.weights_problem(bf16, hubs) == (
        "Qwen/Qwen-Image-2.1: missing vae/config.json; missing processor/ (run bin/seed-edit-setup --model qwen21-bf16)",
        None, None)
    e2511 = seedgen.qwen_model("qwen2511-q4")
    only = pinned_cache(os.path.join(env["tmp"], "hf"), e2511["repo"], e2511["revision"],
                        {"transformer/0.safetensors": b"\x01" * 8})
    mt.make_hf_cache(os.path.join(env["tmp"], "zi"), qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})
    assert qe.weights_problem(e2511, hubs) == (
        "Lightning LoRA Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors is not in %s "
        "(run bin/seed-edit-setup --model qwen2511-q4)" % where, None, None)
    lightning = os.path.join(pinned_cache(os.path.join(env["tmp"], "hf"), qe.EDIT_LORA_REPO,
                                          e2511["builtin_lora"]["revision"], {qe.EDIT_LORA_FILE: b"\x01" * 8}),
                             qe.EDIT_LORA_FILE)
    assert qe.weights_problem(e2511, hubs) == (None, only, lightning)
    unc = seedgen.qwen_lora("uncensored")
    missing = ("qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)"
               % where)
    assert qe.lora_problem(unc, hubs) == (missing, None)
    pinned_cache(os.path.join(env["tmp"], "zi"), unc["repo"], unc["revision"], {unc["file"]: b""})
    assert qe.lora_problem(unc, hubs) == (missing, None)
    found = install_lora(env, "uncensored", root="hf")
    assert qe.lora_problem(unc, hubs) == (None, found)
    py = os.path.join(env["tmp"], "mflux-edit", ".venv", "bin", "python")
    venv = os.path.dirname(os.path.dirname(py))
    mp.setenv("SEED_EDIT_MFLUX_PYTHON", py)
    hint = "(run bin/seed-edit-setup --model qwen21-q8)"
    assert qe.mflux_env_problem(q8) == "no mflux venv at %s %s" % (py, hint)
    mflux_venv(env, version=None)
    assert qe.mflux_env_problem(q8) == "mflux is not installed in %s %s" % (venv, hint)
    set_mflux_version(venv, "banana")
    assert qe.mflux_env_problem(q8) == "cannot read the mflux version in %s" % venv
    set_mflux_version(venv, "0.23.9")
    assert qe.mflux_env_problem(q8) == "mflux 0.23.9 in %s is older than 0.24.0 %s" % (venv, hint)
    assert qe.mflux_env_problem(q4) == ("mflux 0.23.9 in %s is older than 0.24.0 "
                                        "(run bin/seed-edit-setup --model qwen21-q4)" % venv)
    for version in ("0.24.0", "0.25.1"):
        set_mflux_version(venv, version)
        assert qe.mflux_env_problem(q8) is None
    assert qe.qwen_model_problem(q8) == (None, {"model_path": q8_snapshot, "builtin_lora": None})
    mp.setattr(qe, "missing_modules", lambda names: ["torch"])
    assert qe.qwen_model_problem(q8) == ("torch not importable by %s" % sys.executable, {})
    assert qe.qwen_hubs() == [zhub, hfhub]
    assert qe.MFLUX_MIN_VERSION == (0, 24, 0)
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("SEED_EDIT_QWEN_Q4_DIR", "SEED_EDIT_LIGHTNING_FILE", "def choose_qwen(", "def mflux_problem(",
                 "BF16_MIN_AVAIL_GIB", "MFLUX_MIN_AVAIL_GIB", "Q4_REPO", "Q4_NAME_PART"):
        assert gone not in source, gone
    environ_re = r"os\.environ(?:\.get\(|\[)\"([A-Z0-9_]+)\""
    assert re.findall(environ_re, source) == []
    with open(os.path.join(WS, "qwen_edit.py"), encoding="utf-8") as f:
        assert set(re.findall(environ_re, f.read())) == {
            "SEED_EDIT_MFLUX_PYTHON", "SEED_EDIT_QWENEDIT_SCRIPT", "HF_HUB_CACHE", "HF_HOME"}
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    install_model(env, "qwen21-bf16")
    mp.setattr(tool, "total_gib", lambda: 128.0)
```

with:

```python
    install_model(env, "qwen21-bf16")
    mp.setattr(env["qe"], "total_gib", lambda: 128.0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    mp.setattr(tool, "total_gib", lambda: None)
```

with:

```python
    mp.setattr(env["qe"], "total_gib", lambda: None)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sqt5_the_mflux_selection(env, capsys, model_id, loras, paths, scales, steps, scheduler, why):
    tool = env["tool"]
    env["mp"].setattr(tool, "avail_gib", lambda: 128.0)
```

with:

```python
def test_sqt5_the_mflux_selection(env, capsys, model_id, loras, paths, scales, steps, scheduler, why):
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 128.0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    assert calls[0]["spec"] == {
        "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
        "lora_scales": scales, "prompt": PROMPT, "source": os.path.join(work, "source.png"), "width": 1024,
        "height": 672, "steps": steps, "guidance": 1.0, "scheduler": scheduler,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
                 for n in (1, 2)]}
```

with:

```python
    assert calls[0]["spec"] == {
        "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
        "lora_scales": scales, "width": 1024, "height": 672, "steps": steps, "guidance": 1.0,
        "scheduler": scheduler,
        "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                  "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2)]}
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    tool, calls = env["tool"], env["calls"]
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    py, _venv = mflux_venv(env)
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
```

with:

```python
    calls = env["calls"]
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 70.0)
    py, _venv = mflux_venv(env)
    for model_id in ("qwen21-q4", "qwen21-q8", "qwen21-bf16", "qwen2511-q4"):
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sqt7_run_time_refusals(env, capsys):
    tool, mp, zhub, hfhub = env["tool"], env["mp"], env["zhub"], env["hfhub"]
```

with:

```python
def test_sqt7_run_time_refusals(env, capsys):
    qe, mp, zhub, hfhub = env["qe"], env["mp"], env["zhub"], env["hfhub"]
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    mp.setattr(tool, "avail_gib", lambda: 10.0)
    mp.setattr(tool, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R3)
```

with:

```python
    mp.setattr(qe, "avail_gib", lambda: 10.0)
    mp.setattr(qe, "AVAIL_WAIT_S", 0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R3)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    mp.setattr(tool, "avail_gib", lambda: 40.0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", model="qwen", run=R4)
```

with:

```python
    mp.setattr(qe, "avail_gib", lambda: 40.0)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-bf16", model="qwen", run=R4)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    assert calls[0]["spec"] == {
        "family": "qwen2511", "model_path": q4, "lora_paths": [lora], "lora_scales": [1.0], "prompt": PROMPT,
        "source": os.path.join(work, "source.png"), "width": 1024, "height": 672, "steps": 8, "guidance": 1.0,
        "scheduler": None,
        "jobs": [{"n": n, "seed": 100 + n, "output_path": os.path.join(work, "cand_%02d.pending.png" % n)}
                 for n in (1, 2, 3)]}
```

with:

```python
    assert calls[0]["spec"] == {
        "family": "qwen2511", "model_path": q4, "lora_paths": [lora], "lora_scales": [1.0], "width": 1024,
        "height": 672, "steps": 8, "guidance": 1.0, "scheduler": None,
        "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                  "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2, 3)]}
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sgt10_the_mflux_child_fails_or_times_out(env, capsys):
    tool = env["tool"]
```

with:

```python
def test_sgt10_the_mflux_child_fails_or_times_out(env, capsys):
    qe = env["qe"]
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 1)
    stub_config(py, {"sleep": 30})
    started = time.monotonic()
    code, run_dir = run_tool(env, *q4, model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "Qwen-Image-Edit-2511 q4 (Lightning) child timed out after %d s" % tool.CHILD_TIMEOUT_S
    assert tool.CHILD is None
    env["mp"].setattr(tool, "CHILD_TIMEOUT_S", 3600)
```

with:

```python
    env["mp"].setattr(qe, "CHILD_TIMEOUT_S", 1)
    env["mp"].setattr(qe, "JOB_TIMEOUT_S", 0)
    stub_config(py, {"sleep": 30})
    started = time.monotonic()
    code, run_dir = run_tool(env, *q4, model="qwen", run=R2)
    assert code == 1 and time.monotonic() - started < 20
    record = record_of(run_dir)
    assert statuses(run_dir) == ["failed"] * 3
    assert record["error"] == "Qwen-Image-Edit-2511 q4 (Lightning) child timed out after %d s" % qe.CHILD_TIMEOUT_S
    assert qe.CHILD is None
    env["mp"].setattr(qe, "CHILD_TIMEOUT_S", 3600)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited -9: killed")
    assert tool.CHILD is None
```

with:

```python
    assert (record["state"], record["error"]) == ("failed", "Qwen-Image-Edit-2511 q4 (Lightning) child exited -9: killed")
    assert qe.CHILD is None
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sgt11_the_bf16_child(env, capsys):
    tool = env["tool"]
    bf16_cache(env)
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
```

with:

```python
def test_sgt11_the_bf16_child(env, capsys):
    bf16_cache(env)
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 70.0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    bf16_cache(env)
    mp.setattr(tool, "total_gib", lambda: 128.0)
```

with:

```python
    bf16_cache(env)
    mp.setattr(env["qe"], "total_gib", lambda: 128.0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    for name in ("EDIT_MODEL", "EDIT_LORA_REPO", "EDIT_LORA_FILE", "EDIT_STEPS", "EDIT_TRUE_CFG", "AVAIL_WAIT_S"):
        assert getattr(tool, name) == getattr(character_dataset, name), name
```

with:

```python
    for name in ("EDIT_MODEL", "EDIT_LORA_REPO", "EDIT_LORA_FILE", "EDIT_STEPS", "EDIT_TRUE_CFG", "AVAIL_WAIT_S"):
        assert getattr(tool.qe, name) == getattr(character_dataset, name), name
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
        assert entry["steps"] == tool.EDIT_STEPS
        assert (entry["builtin_lora"]["repo"], entry["builtin_lora"]["file"]) == (tool.EDIT_LORA_REPO, tool.EDIT_LORA_FILE)
    assert seedgen.qwen_model("qwen2511-bf16")["repo"] == tool.EDIT_MODEL
```

with:

```python
        assert entry["steps"] == tool.qe.EDIT_STEPS
        assert (entry["builtin_lora"]["repo"], entry["builtin_lora"]["file"]) == (tool.qe.EDIT_LORA_REPO,
                                                                                   tool.qe.EDIT_LORA_FILE)
    assert seedgen.qwen_model("qwen2511-bf16")["repo"] == tool.qe.EDIT_MODEL
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
def test_sg_review_focus_4_progress_bars_in_child_lines(env, capsys):
    tool = env["tool"]
```

with:

```python
def test_sg_review_focus_4_progress_bars_in_child_lines(env, capsys):
    qe = env["qe"]
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    env["mp"].setattr(tool, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
```

with:

```python
    env["mp"].setattr(qe, "avail_gib", lambda: 70.0)
    qwenedit_stub(env, {"prefix": "Loading pipeline components...: 100%|##########| 5/5\r"})
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    assert child.MIN_VERSION == tool.MFLUX_MIN_VERSION == (0, 24, 0)
```

with:

```python
    assert child.MIN_VERSION == tool.qe.MFLUX_MIN_VERSION == (0, 24, 0)
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    setup, rec, tool = e["setup"], e["rec"], e["tool"]
    entry = seedgen.qwen_model("qwen2511-q4")
    old = mt.make_hf_cache(os.path.join(e["tmp"], "zi"), entry["repo"], {"transformer/0.safetensors": b"\x01" * (4 * 2 ** 20)})
    mt.make_hf_cache(os.path.join(e["tmp"], "zi"), tool.EDIT_LORA_REPO, {tool.EDIT_LORA_FILE: b"\x01" * 8})
    assert tool.weights_problem(entry, tool.qwen_hubs())[0] == (
```

with:

```python
    setup, rec, qe = e["setup"], e["rec"], e["qe"]
    entry = seedgen.qwen_model("qwen2511-q4")
    old = mt.make_hf_cache(os.path.join(e["tmp"], "zi"), entry["repo"], {"transformer/0.safetensors": b"\x01" * (4 * 2 ** 20)})
    mt.make_hf_cache(os.path.join(e["tmp"], "zi"), qe.EDIT_LORA_REPO, {qe.EDIT_LORA_FILE: b"\x01" * 8})
    assert qe.weights_problem(entry, qe.qwen_hubs())[0] == (
```

Edit `tests/test_seed_edit_tool.py`: replace this text, which occurs exactly once:

```python
    seen, real = [], tool.run_child

    def spy(argv, child_env, on_line):
        seen.append(dict(child_env))
        return real(argv, child_env, on_line)

    mp.setattr(tool, "run_child", spy)
```

with:

```python
    seen, real = [], env["qe"].run_child

    def spy(argv, child_env, on_line, timeout_s, log_path=None):
        seen.append(dict(child_env))
        return real(argv, child_env, on_line, timeout_s, log_path)

    mp.setattr(env["qe"], "run_child", spy)
```

Edit `tests/test_seed_edit_tool.py` (append QET12 and Review Focus 2 at the end of the file): replace this text, which occurs exactly once:

```python
    assert (record["source"], record["source_size"], record["size"]) == (
        "source.jpg", {"width": 300, "height": 200}, {"width": 288, "height": 192})
    with open(mpo, "rb") as f, open(os.path.join(run_dir, "source.jpg"), "rb") as g:
        assert f.read() == g.read()
```

with:

```python
    assert (record["source"], record["source_size"], record["size"]) == (
        "source.jpg", {"width": 300, "height": 200}, {"width": 288, "height": 192})
    with open(mpo, "rb") as f, open(os.path.join(run_dir, "source.jpg"), "rb") as g:
        assert f.read() == g.read()


# --- QET12 (qwen edit models QE19-QE23, QEK3): the tool on top of qwen_edit.py behaves as before -------------

QET12_CASES = SQT5_CASES + [("qwen2511-bf16", [], [], [], 8, None,
                             "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers); LoRAs none; 8 steps; scheduler default")]


@pytest.mark.parametrize("model_id,loras,paths,scales,steps,scheduler,why", QET12_CASES,
                         ids=["case%d" % (i + 1) for i in range(len(QET12_CASES))])
def test_qet12_the_tool_on_qwen_edit_behaves_as_before(env, capsys, model_id, loras, paths, scales, steps,
                                                        scheduler, why):
    env["mp"].setattr(env["qe"], "avail_gib", lambda: 128.0)
    entry = seedgen.qwen_model(model_id)
    if entry["backend"] == "mflux":
        py, _venv = mflux_venv(env)
        snapshot, lightning = install_model(env, model_id)
        found = {"lightning": lightning}
        for lora_id in ("uncensored", "viggle-turbo"):
            found[lora_id] = install_lora(env, lora_id)
    else:
        bf16_cache(env)
        stub = qwenedit_stub(env, {})
    extra = ["--qwen-model", model_id, "--candidates", "2", "--seed", "100"]
    for value in loras:
        extra += ["--lora", value]
    code, run_dir = run_tool(env, *extra, model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    record = record_of(run_dir)
    chosen = [{"id": v.split("=")[0], "scale": float(v.split("=")[1])} for v in loras]
    expected = {"schema": "seed-edit.run.v1", "run": RUN, "created": None, "state": "done", "prompt": PROMPT,
                "model": "qwen", "backend": entry["backend"], "strength": None, "seed": 100,
                "size": {"width": 1024, "height": 672}, "source_size": {"width": 1536, "height": 1024},
                "source": "source.png", "source_origin": None, "job": None, "error": None,
                "candidates": [{"n": n, "seed": 100 + n, "status": "ok", "seconds": None} for n in (1, 2)]}
    expected.update(seedgen.qwen_settings(model_id, chosen))
    assert dict(record, created=None, candidates=[dict(c, seconds=None) for c in record["candidates"]]) == expected
    for n in (1, 2):
        with Image.open(cand(run_dir, n)) as img:
            assert img.size == (1024, 672)
    assert glob.glob(os.path.join(work, "*.part.png")) + glob.glob(os.path.join(work, "*.pending.png")) == []
    out = [line for line in capsys.readouterr().out.splitlines() if line.startswith(("seed-edit: ", "candidate "))]
    assert plain(out) == ["seed-edit: run %s" % run_dir, "seed-edit: source 1536x1024 -> 1024x672",
                          "seed-edit: backend %s (%s)" % (entry["backend"], why), "candidate 1/2 ok Ss",
                          "candidate 2/2 ok Ss", "seed-edit: done: 2 ok, 0 blocked, 0 failed"]
    if entry["backend"] == "mflux":
        (call,) = stub_calls(py)
        assert call["spec"] == {
            "family": entry["family"], "model_path": snapshot, "lora_paths": [found[p] for p in paths],
            "lora_scales": scales, "width": 1024, "height": 672, "steps": steps, "guidance": 1.0,
            "scheduler": scheduler,
            "jobs": [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                      "output_path": os.path.join(work, "cand_%02d.pending.png" % n)} for n in (1, 2)]}
    else:
        (call,) = stub_calls(stub)
        assert call["spec"] == {
            "image": os.path.join(work, "source.png"), "model": "Qwen/Qwen-Image-Edit-2511",
            "lora_repo": "lightx2v/Qwen-Image-Edit-2511-Lightning",
            "lora_file": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", "steps": 8, "true_cfg": 1.0,
            "skill": "seed_edit",
            "jobs": [{"prompt": PROMPT, "output_path": os.path.join(work, "cand_%02d.part.png" % n), "seed": 100 + n,
                      "width": 1024, "height": 672} for n in (1, 2)],
            "report_path": os.path.join(work, "qwenedit_report.json")}
    with open(TOOL_PATH, encoding="utf-8") as f:
        source = f.read()
    for gone in ("def run_child(", "def weights_problem(", "CHILD_TIMEOUT_S", "import subprocess", "import threading"):
        assert gone not in source, gone


# --- Review Focus 2: a Cancel during a Qwen run kills the Qwen child -----------------------------------------

def test_qe_review_focus_2_an_interrupt_kills_the_qwen_child(env, capsys):
    tool, qe, mp = env["tool"], env["qe"], env["mp"]
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        mp.setattr(qe, "CHILD", proc)
        qe.kill_running_child()
        assert proc.wait(timeout=10) == -9
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    killed = []
    mp.setattr(qe, "kill_running_child", lambda: killed.append(True))

    def interrupted(ctx):
        raise KeyboardInterrupt

    mp.setattr(tool, "run", interrupted)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R1)
    assert (code, killed) == (130, [True])
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert capsys.readouterr().err == "seed-edit: interrupted\n"
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    with open(os.path.join(WS, "bin", "seed-edit"), encoding="utf-8") as f:
        tool = f.read()
```

with:

```python
    with open(os.path.join(WS, "qwen_edit.py"), encoding="utf-8") as f:
        tool = f.read()
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "glob", "importlib.util", "json", "os", "re", "secrets", "shutil", "signal", "subprocess", "sys",
        "threading", "time", "movie_ui_lib", "movie_ui_seedgen"]
```

with:

```python
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "argparse", "glob", "json", "os", "re", "secrets", "shutil", "signal", "sys", "time", "movie_ui_lib",
        "movie_ui_seedgen", "qwen_edit"]
```

- [ ] **Step 2: Run the Seeds tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py 2>&1 | tail -1`
Expected: failures in every test that uses the `env` fixture (`AttributeError: module 'seed_edit_tool' has no attribute 'qe'`), including the QET12 cases and Review Focus 2, and in `test_sgt14_the_mirrored_constants`, `test_sqt10_the_registry_pins`, `test_sqt9_the_child_mirrors_the_registry` (`tool.qe`) and `test_sgt34_the_new_python_files_and_the_tool_imports` (the import list). `test_sqt18_the_setup_script_carries_the_tool_lookups` already passes (Task 1's copies in `qwen_edit.py` are byte-identical to `bin/seed-edit-setup`'s).

- [ ] **Step 3: Write the implementation.** Read `bin/seed-edit`, then Write `bin/seed-edit` with exactly this content (the Write tool; check `git ls-files -s bin/seed-edit | cut -c1-6` still prints `100755` afterwards):

```python
#!/usr/bin/env python3
"""seed-edit -- edit one source image into 1 to 4 seed candidates with Z-Image img2img or a Qwen
registry model (docs/superpowers/specs/2026-11-02-seed-generator-design.md, Section 2, amended by
docs/superpowers/specs/2026-11-02-seed-models-design.md, Section 3).

  bin/seed-edit --source PATH --prompt TEXT --model zimage|qwen [--qwen-model ID] [--lora ID=SCALE ...]
                [--strength S] [--candidates N] [--seed N] --run-dir DIR
  bin/seed-edit --probe

The movie-ui runs it as a queued GPU job of kind seed-edit; it also runs by hand. Candidate i
(1-based) uses seed + i and lands in <run dir>/cand_NN.png. --strength (0.10 to 0.90, default
0.45) is for zimage only; --candidates defaults to 4; a missing --seed is drawn at random.
--qwen-model is one of movie_ui_seedgen's registry IDs: qwen21-q4, qwen21-q8, qwen21-bf16
(Qwen-Image-2.1 through mflux), qwen2511-q4 (Qwen-Image-Edit-2511 q4 through mflux, Lightning
built in) or qwen2511-bf16 (the unchanged character_dataset.py qwenedit child); without it
--model qwen runs qwen2511-q4, as a job queued before the registry did. Each --lora ID=SCALE
(uncensored, viggle-turbo; 0 < SCALE <= 2) must be of the model's family; viggle-turbo sets 6
steps and scheduler viggle_turbo. Every candidate of every model is screened with content
safety before it gets its final name. --probe prints one JSON line {"qwen": {"ok", "reason",
"models": {ID: {"ok", "reason"}}, "loras": {ID: {"ok", "reason"}}}, "zimage": {"backend", "ok",
"reason"}} and loads nothing.

Exit codes: 0 every candidate ended ok or blocked; 1 the backend failed (finished candidates are
kept, the rest are failed); 2 refused before any model loaded; 130 interrupted (SIGINT, SIGTERM
or SIGHUP).

run.json (schema seed-edit.run.v1) write order: (1) the run directory and work/ are created;
(2) the source is read, copied and sized, and a refusal writes state failed with every candidate
failed; (3) state running, backend null, every candidate pending; (4) the preflight and the
backend choice, a refusal written as in (2); (5) the backend; (6) per candidate: the final
cand_NN.png (ok only), then run.json, then the candidate line; (7) state done or failed; (8) an
interrupt kills the child, marks the pending candidates failed and writes state cancelled.
created, source_origin and job are kept from an existing run.json; the tool owns every other key.

Environment (read by qwen_edit.py): SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python),
SEED_EDIT_QWENEDIT_SCRIPT (default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the
default hub), Z_IMAGE_HF_HOME (the Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The
mflux weights and LoRAs are looked up only at their pinned revisions, in the Z-Image hub and then
the default hub. The Qwen checks and the child run live in qwen_edit.py
(docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md); the child timeout is
max(3600, 600 x candidates) s.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib,
movie_ui_seedgen and qwen_edit; PIL, psutil, torch, z_image_skill, content_safety and
character_dataset are imported inside the functions that use them.
"""

import argparse
import glob
import json
import os
import re
import secrets
import shutil
import signal
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_lib as lib  # noqa: E402
import movie_ui_seedgen as seedgen  # noqa: E402
import qwen_edit as qe  # noqa: E402

LONG_EDGE = 1024
MULTIPLE = 16
MIN_SIDE = 64
PROMPT_MAX = 2000
SEED_MAX = 2147483647
STRENGTH_DEFAULT = 0.45
MIN_FREE_GIB = 2.0               # character_dataset.CREATE_MIN_FREE_GIB
ZIMAGE_MIN_AVAIL_GIB = 20.0      # character_dataset.GENERATE_MIN_AVAIL_GIB
SAFETY_SKILL = "seed_edit"
BACKEND_LABELS = {"zimage": "Z-Image", "mflux": "mflux", "diffusers": "diffusers"}

EXTS = {"PNG": "png", "JPEG": "jpg", "MPO": "jpg", "WEBP": "webp"}


class Refusal(Exception):
    """A refusal before any model loads (exit 2); the message is the error text."""


def say(text):
    """Every stdout line of the tool goes through here (SG7)."""
    print(text, flush=True)


def error(text):
    sys.stderr.write("Error: %s\n" % text)
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# The command line (SG4)
# ---------------------------------------------------------------------------

def parse(argv):
    parser = argparse.ArgumentParser(prog="seed-edit", description="Edit one source image into 1 to 4 "
                                     "seed candidates (Z-Image img2img or a Qwen registry model).")
    for name in ("--source", "--prompt", "--model", "--strength", "--candidates", "--seed", "--run-dir"):
        parser.add_argument(name, type=str)
    parser.add_argument("--qwen-model", type=str)
    parser.add_argument("--lora", type=str, action="append")
    parser.add_argument("--probe", action="store_true")
    return parser.parse_args(argv)


def check_args(args):
    """SG4 and seed models SQ12: the cleaned options (None for --probe), or Refusal with the first
    failing rule's text."""
    given = (args.source, args.prompt, args.model, args.strength, args.candidates, args.seed, args.run_dir,
             args.qwen_model, args.lora)
    if args.probe:
        if any(value is not None for value in given):
            raise Refusal("--probe takes no other options")
        return None
    if None in (args.source, args.prompt, args.model, args.run_dir):
        raise Refusal("--source, --prompt, --model and --run-dir are required")
    if args.model not in ("zimage", "qwen"):
        raise Refusal("--model must be zimage or qwen")
    if not args.prompt.strip():
        raise Refusal("--prompt must not be empty")
    if len(args.prompt) > PROMPT_MAX:
        raise Refusal("--prompt is longer than 2000 characters")
    if args.candidates is None:
        candidates = 4
    elif re.fullmatch(r"[0-9]+", args.candidates) and 1 <= int(args.candidates) <= 4:
        candidates = int(args.candidates)
    else:
        raise Refusal("--candidates must be an integer from 1 to 4")
    if args.model == "qwen":
        if args.strength is not None:
            raise Refusal("--strength is only for --model zimage")
        strength = None
    elif args.strength is None:
        strength = STRENGTH_DEFAULT
    else:
        try:
            strength = float(args.strength)
        except ValueError:
            strength = None
        if strength is None or not 0.10 <= strength <= 0.90:
            raise Refusal("--strength must be a number from 0.10 to 0.90")
    if args.model == "zimage":
        if args.qwen_model is not None:
            raise Refusal("--qwen-model is only for --model qwen")
        if args.lora is not None:
            raise Refusal("--lora is only for --model qwen")
        qwen_model, loras = None, []
    else:
        qwen_model = seedgen.LEGACY_QWEN_MODEL if args.qwen_model is None else args.qwen_model
        if qwen_model not in seedgen.QWEN_MODEL_IDS:
            raise Refusal("--qwen-model must be one of %s" % ", ".join(seedgen.QWEN_MODEL_IDS))
        try:
            loras = qe.check_lora_args(args.lora or [], seedgen.qwen_model(qwen_model))
        except qe.SelectionError as e:
            raise Refusal(str(e))
    if args.seed is None:
        seed = secrets.randbelow(SEED_MAX + 1)
    elif re.fullmatch(r"[0-9]+", args.seed) and int(args.seed) <= SEED_MAX:
        seed = int(args.seed)
    else:
        raise Refusal("--seed must be an integer from 0 to 2147483647")
    return {"source": args.source, "prompt": args.prompt, "model": args.model, "strength": strength,
            "candidates": candidates, "seed": seed, "run_dir": os.path.abspath(args.run_dir),
            "qwen_model": qwen_model, "loras": loras}


# ---------------------------------------------------------------------------
# The source and its size (SG8-SG10)
# ---------------------------------------------------------------------------

def canvas(w0, h0, multiple=MULTIPLE):
    """SG8, seed models SQ14: the (W, H) edit canvas of a w0 x h0 source, each side floored to a
    multiple of multiple, or Refusal when a side is under MIN_SIDE."""
    longest = max(w0, h0)
    if longest <= LONG_EDGE:
        w, h = w0, h0
    else:
        w, h = w0 * LONG_EDGE // longest, h0 * LONG_EDGE // longest
    width, height = w // multiple * multiple, h // multiple * multiple
    if width < MIN_SIDE or height < MIN_SIDE:
        raise Refusal("--source is too small: %dx%d gives a %dx%d canvas; each side must be at least 64 px"
                      % (w0, h0, width, height))
    return width, height


def read_source(path):
    """SG8, SG9: (PIL format, the EXIF-transposed RGB image) of path, or Refusal."""
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as img:
            fmt = img.format
            if fmt not in EXTS:
                raise Refusal("--source must be a PNG, JPEG or WebP image (got %s): %s" % (fmt, path))
            image = ImageOps.exif_transpose(img).convert("RGB")
    except Refusal:
        raise
    except Exception as e:
        raise Refusal("cannot read --source %s: %s: %s" % (path, type(e).__name__, e))
    return fmt, image


def prepare_source(ctx):
    """SG8-SG10: read the source, copy its bytes to <run>/source.<ext>, size it and save the
    transposed RGB image as work/source.png."""
    rec, path = ctx["record"], ctx["opts"]["source"]
    fmt, image = read_source(path)
    dest = os.path.join(ctx["dir"], "source." + EXTS[fmt])
    if not (os.path.exists(dest) and os.path.samefile(path, dest)):
        shutil.copyfile(path, dest)
    rec["source"] = os.path.basename(dest)
    w0, h0 = image.size
    width, height = canvas(w0, h0, seedgen.canvas_multiple(ctx["opts"]["model"], ctx["opts"]["qwen_model"]))
    rec["size"] = {"width": width, "height": height}
    rec["source_size"] = {"width": w0, "height": h0}
    image.save(os.path.join(ctx["work"], "source.png"))
    ctx["width"], ctx["height"] = width, height
    say("seed-edit: source %dx%d -> %dx%d" % (w0, h0, width, height))


# ---------------------------------------------------------------------------
# Host checks, the backend checks and the probe (SG13-SG15; the Qwen checks live in qwen_edit.py)
# ---------------------------------------------------------------------------

def disk_free_gib(path):
    return shutil.disk_usage(path).free / 2 ** 30


def cpu_generator(seed):
    import torch
    return torch.Generator("cpu").manual_seed(seed)


def zimage_problem():
    """None when Z-Image img2img can run in this python, else the first problem."""
    problem = qe.modules_problem(["PIL", "psutil", "torch", "diffusers", "transformers"])
    if problem:
        return problem
    for repo in (lib.STILLS_BASE_MODEL, lib.ZIMAGE_TEXT_ENCODER):
        ok, detail = lib.model_check(repo, lib.zimage_hub_for(repo))
        if not ok:
            return detail
    return None


def probe():
    """SG15, seed models SQ18: {"zimage": {"ok", "reason", "backend"}, "qwen": {"ok", "reason",
    "models", "loras"}}; each registry model is judged by the host's total memory first, then by
    what is installed. Loads no model and starts no process."""
    p = zimage_problem()
    hubs = qe.qwen_hubs()
    models = {}
    for entry in seedgen.QWEN_MODELS:
        reason = qe.memory_problem(entry) or qe.qwen_model_problem(entry)[0]
        models[entry["id"]] = {"ok": reason is None, "reason": reason}
    loras = {}
    for lora in seedgen.QWEN_LORAS:
        reason = qe.lora_problem(lora, hubs)[0]
        loras[lora["id"]] = {"ok": reason is None, "reason": reason}
    ok = any(m["ok"] for m in models.values())
    reason = None if ok else "; ".join("%s: %s" % (i, models[i]["reason"]) for i in seedgen.QWEN_MODEL_IDS)
    return {"zimage": {"ok": p is None, "reason": p, "backend": "zimage" if p is None else None},
            "qwen": {"ok": ok, "reason": reason, "models": models, "loras": loras}}


def preflight(ctx):
    """SG13, seed models SQ21 and qwen edit models QE21: disk, busy GPU, the selected model and LoRAs
    (qwen_edit.install_problem), the memory floor; (backend, why) or Refusal. Sets ctx["label"], and
    for qwen ctx["entry"]."""
    run_dir = ctx["dir"]
    free = disk_free_gib(run_dir)
    if free < MIN_FREE_GIB:
        raise Refusal("less than 2 GiB free on the disk holding %s (%.1f GiB free)" % (run_dir, free))
    import character_dataset
    busy = character_dataset.busy_process()
    if busy:
        raise Refusal("another GPU process is running (pid %s: %s); try again when it ends" % (busy[0], busy[1]))
    opts = ctx["opts"]
    if opts["model"] == "zimage":
        problem = zimage_problem()
        if problem is not None:
            raise Refusal("Z-Image is unavailable: %s" % problem)
        ctx["label"] = BACKEND_LABELS["zimage"]
        try:
            qe.wait_for_memory(ZIMAGE_MIN_AVAIL_GIB, ctx["label"])
        except qe.Unavailable as e:
            raise Refusal(str(e))
        return "zimage", "Z-Image img2img"
    entry = seedgen.qwen_model(opts["qwen_model"])
    ctx["entry"], ctx["label"] = entry, entry["label"]
    problem, _paths = qe.install_problem(entry["id"], opts["loras"])
    if problem is not None:
        raise Refusal(problem)
    try:
        qe.wait_for_memory(entry["memory_gib"], entry["label"])
    except qe.Unavailable as e:
        raise Refusal(str(e))
    settings = seedgen.qwen_settings(entry["id"], opts["loras"])
    listed = ", ".join("%s@%g" % (item["id"], item["scale"]) for item in settings["loras"]) or "none"
    return entry["backend"], "%s; LoRAs %s; %d steps; scheduler %s" % (
        entry["label"], listed, settings["steps"], settings["scheduler"] or "default")


# ---------------------------------------------------------------------------
# run.json and the candidates (SG11, SG12, SG16)
# ---------------------------------------------------------------------------

def new_record(run_dir, opts):
    old = lib.read_json(os.path.join(run_dir, "run.json"))
    if isinstance(old, dict):
        created, origin, job = old.get("created"), old.get("source_origin"), old.get("job")
    else:
        created, origin, job = lib.utc_now(), None, None
    return {"schema": "seed-edit.run.v1", "run": os.path.basename(run_dir), "created": created,
            "state": "running", "prompt": opts["prompt"], "model": opts["model"], "backend": None,
            "strength": opts["strength"], "seed": opts["seed"],
            **seedgen.qwen_settings(opts["qwen_model"], opts["loras"]), "size": None, "source_size": None,
            "source": None, "source_origin": origin, "job": job, "error": None,
            "candidates": [{"n": i, "seed": opts["seed"] + i, "status": "pending", "seconds": None}
                           for i in range(1, opts["candidates"] + 1)]}


def write_run(ctx):
    lib.write_json_atomic(os.path.join(ctx["dir"], "run.json"), ctx["record"])


def final_path(ctx, n):
    return os.path.join(ctx["dir"], "cand_%02d.png" % n)


def part_path(ctx, n):
    return os.path.join(ctx["work"], "cand_%02d.part.png" % n)


def pending_path(ctx, n):
    return os.path.join(ctx["work"], "cand_%02d.pending.png" % n)


def first_pending(ctx):
    """The first pending candidate's n, else the candidate count."""
    cands = ctx["record"]["candidates"]
    for cand in cands:
        if cand["status"] == "pending":
            return cand["n"]
    return len(cands)


def finish(ctx, n, status, seconds=None):
    """SG12 step 6, SG16: record candidate n's status in run.json, then print its line. An ok
    candidate's cand_NN.png is already in place."""
    cands = ctx["record"]["candidates"]
    cand = cands[n - 1]
    cand["status"] = status
    cand["seconds"] = None if seconds is None or status == "failed" else round(seconds, 1)
    write_run(ctx)
    if status == "failed":
        say("candidate %d/%d failed" % (n, len(cands)))
    else:
        say("candidate %d/%d %s %.1fs" % (n, len(cands), status, cand["seconds"]))


def fail_rest(ctx):
    """SG16: every candidate not yet finished gets its own failed line, in order."""
    for cand in ctx["record"]["candidates"]:
        if cand["status"] == "pending":
            finish(ctx, cand["n"], "failed")


def refuse(ctx, text):
    """SG12 steps 2 and 4: state failed, error, every candidate failed; exit 2."""
    rec = ctx["record"]
    for cand in rec["candidates"]:
        cand["status"], cand["seconds"] = "failed", None
    rec["state"], rec["error"] = "failed", text
    write_run(ctx)
    error(text)
    return 2


def cleanup(work):
    """SG12 step 7: delete leftover work/*.part.png and work/*.pending.png."""
    for pattern in ("*.part.png", "*.pending.png"):
        for path in glob.glob(os.path.join(work, pattern)):
            try:
                os.remove(path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The backends (SG17-SG22; the Qwen child run lives in qwen_edit.run_jobs)
# ---------------------------------------------------------------------------

def run_zimage(ctx):
    """SG18: Z-Image img2img in this process (the z_image_skill singleton loads once); returns None.
    A content-safety block is that candidate only; any other exception propagates to run()."""
    import z_image_skill
    import content_safety
    from PIL import Image
    opts = ctx["opts"]
    with Image.open(os.path.join(ctx["work"], "source.png")) as img:
        src = img.convert("RGB").resize((ctx["width"], ctx["height"]), Image.LANCZOS)
    for cand in ctx["record"]["candidates"]:
        n = cand["n"]
        started = time.monotonic()
        try:
            image = z_image_skill.generate_variation(src, opts["prompt"], output_path=None,
                                                     strength=opts["strength"], generator=cpu_generator(cand["seed"]))
        except content_safety.ContentSafetyError:
            finish(ctx, n, "blocked", time.monotonic() - started)
            continue
        seconds = time.monotonic() - started
        image.save(part_path(ctx, n))
        os.replace(part_path(ctx, n), final_path(ctx, n))
        finish(ctx, n, "ok", seconds)
    return None


def run_qwen(ctx):
    """SG19, SG20, seed models SQ23, qwen edit models QE22: every candidate through qwen_edit.run_jobs;
    returns None or the SG17 text. The bf16 child stages cand_NN.part.png, mflux cand_NN.pending.png."""
    opts, rec, entry = ctx["opts"], ctx["record"], ctx["entry"]
    stage = pending_path if entry["backend"] == "mflux" else part_path
    jobs = [{"n": c["n"], "seed": c["seed"], "prompt": opts["prompt"],
             "source": os.path.join(ctx["work"], "source.png"), "stage_path": stage(ctx, c["n"]),
             "output_path": final_path(ctx, c["n"])} for c in rec["candidates"]]
    _results, failure = qe.run_jobs(entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL,
                                    ctx["work"], on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
                                    noun="candidate")
    return failure


# ---------------------------------------------------------------------------
# main (SG5-SG7, SG12)
# ---------------------------------------------------------------------------

def run(ctx):
    """SG12 steps 2-7 for one run; returns the exit code."""
    rec = ctx["record"]
    try:
        prepare_source(ctx)
    except Refusal as e:
        return refuse(ctx, str(e))
    rec["state"] = "running"
    write_run(ctx)
    try:
        backend, why = preflight(ctx)
    except Refusal as e:
        return refuse(ctx, str(e))
    rec["backend"] = backend
    write_run(ctx)
    say("seed-edit: backend %s (%s)" % (backend, why))
    runner = {"zimage": run_zimage, "diffusers": run_qwen, "mflux": run_qwen}[backend]
    try:
        failure = runner(ctx)
    except Exception as e:
        failure = "%s failed on candidate %d: %s: %s" % (ctx["label"], first_pending(ctx), type(e).__name__, e)
    fail_rest(ctx)
    statuses = [cand["status"] for cand in rec["candidates"]]
    rec["state"] = "failed" if "failed" in statuses else "done"
    rec["error"] = failure
    write_run(ctx)
    say("seed-edit: done: %d ok, %d blocked, %d failed" % (statuses.count("ok"), statuses.count("blocked"),
                                                          statuses.count("failed")))
    return 0 if failure is None and "failed" not in statuses else 1


def main(argv=None):
    """bin/seed-edit (SG4-SG23). Returns the exit code; installs no signal handler."""
    args = parse(argv)
    try:
        opts = check_args(args)
    except Refusal as e:
        error(str(e))
        return 2
    if opts is None:
        say(json.dumps(probe(), sort_keys=True))
        return 0
    run_dir = opts["run_dir"]
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.join(run_dir, "work"), exist_ok=True)
    ctx = {"dir": run_dir, "work": os.path.join(run_dir, "work"), "opts": opts,
           "record": new_record(run_dir, opts)}
    say("seed-edit: run %s" % run_dir)
    try:
        return run(ctx)
    except KeyboardInterrupt:
        qe.kill_running_child()
        for cand in ctx["record"]["candidates"]:
            if cand["status"] == "pending":
                cand["status"] = "failed"
        ctx["record"]["state"], ctx["record"]["error"] = "cancelled", "interrupted"
        write_run(ctx)
        sys.stderr.write("seed-edit: interrupted\n")
        return 130
    finally:
        cleanup(ctx["work"])


def _interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    # A movie-ui Cancel (SIGTERM), a closed terminal (SIGHUP) and Ctrl-C take the same path (SG6).
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_qwen_edit.py 2>&1 | tail -1 && git ls-files -s bin/seed-edit | cut -c1-6`
Expected: `N passed` with no failure; `100755`.

Run the compile check with `FILES` = `bin/seed-edit tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py`. Expected: `compiled 3` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=2`. Expected: `GATE PASS`, `lost 0 (listed 0, unexpected 0); new tests 19, not passing 0; baseline failures still failing 2 of 2` (Task 1's 12 plus QET12's 6 cases and Review Focus 2), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add bin/seed-edit tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly those three paths
git commit -m "seed-edit: the Qwen checks and the child run move to qwen_edit.py, behaviour unchanged (qwen edit models QE19-QE23, QET12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Characters: the Qwen selection of seed-image datasets (pinned: `character_lib.py`, `character_dataset.py`, `bin/character`) (QE32-QE39; QET18, QET20-QET25)

This task implements:
- `character_lib.py` (QE38): `_OPTIONAL_KEYS`, `_EDIT_KEYS`, `_EDIT_MODEL_KEYS`, `_EDIT_LORA_KEYS`, `_edit_problem` (QE31's text, typed once here and byte-identically in `location_lib.py` in Task 4), and `validate_character`'s two `edit` rules.
- `character_dataset.py`: `import qwen_edit` (QE33); `run_edit_child`'s routing and `_run_registry_edit` (QE33); `edit_selection_problem` (QE34); `busy_process` (QE35); `create`'s options, refusals, editor check, regenerate persistence, new record and `edit model:` line (QE36); `_generate_edits`' spec `edit`, `_build_dataset`'s floor and manifest (QE37); the module and `busy_process` docstring sentences.
- `bin/character` (QE32): `--qwen-model`, `--lora`, the docstring.
- Tests: §11.3's `_Fakes` line and K19 in `tests/test_character_tool.py`, ruling R3's K23 edit, QET20-QET22 there; QET23 in `tests/test_character_lib.py`; QET24, QET25 in `tests/test_character_dataset.py`; QET18 in `tests/test_location_dataset.py` (R7).

From this task until Task 8, `test_mut26_pipeline_files_are_unchanged` fails (expected; it is the T3 line of `$D/expected-failures.txt`).

**Files:**
- Modify: `character_lib.py` (`_LORA_KEYS` `:236-237`, `validate_character` `:358-455`), `character_dataset.py` (docstring `:12-14`, imports `:49`, `busy_process` `:540-556`, `edit_models_missing` `:831-844`, `_generate_edits` `:919-944`, `_build_dataset` `:986`, `:1051-1057`, `create` `:1100-1300`, `run_edit_child` `:1806-1822`), `bin/character` (docstring `:5-19`, parser `:70-71`).
- Modify (tests): `tests/test_character_tool.py`, `tests/test_character_lib.py`, `tests/test_character_dataset.py`, `tests/test_location_dataset.py`.

**Interfaces:**
- Consumes (Task 1): `qwen_edit.LEGACY_EDIT_MODEL`, `SelectionError`, `Unavailable`, `cli_selection(model_arg, lora_args)`, `settings`, `selection_of`, `generator_text`, `memory_floor`, `label`, `selection_problem`, `run_jobs(...)`.
- Produces (Task 4 calls these through the `character_dataset` module):
  - `character_dataset.edit_selection_problem(model_id, loras) -> None or text`;
  - `character_dataset.run_edit_child(spec, char_dir, step) -> {"jobs": [{"output_path", "status", "seconds"}]}`, unchanged signature: a spec without `edit`, or whose `edit["qwen_model"]` is `qwen2511-bf16`, runs today's qwenedit child with today's spec file (the `edit` key removed); `{"edit": {"qwen_model": ID, "loras": [{"id", "scale"}]}}` with any other ID runs `qwen_edit.run_jobs` (jobs numbered from 1, source = `job["image"]` else `spec["image"]`, stage `<output stem>.pending.png`, size = the first job's, skill = `spec["skill"]` else `character_edit`, work dir = the log path without `.log`); a failure raises `DatasetError("<failure>; log: <log>")` with `.log_path`, `qwen_edit.Unavailable` raises `DatasetError(<text>)`;
  - `character_lib._edit_problem(edit) -> None or text` (Task 4's QET15 compares its code with `location_lib`'s);
  - `character.json`'s optional `edit` key = `qwen_edit.settings(model_id, loras)` (seed-image characters only).
- Produces (`bin/character create`): `--qwen-model ID` (dest `qwen_model`, default `None`), `--lora ID=SCALE` (dest `lora`, append, default `None`).

- [ ] **Step 1: Write the failing tests and the §11.3 / R3 edits.**

Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
import character_dataset  # noqa: E402
import character_lib  # noqa: E402
```

with:

```python
import character_dataset  # noqa: E402
import character_lib  # noqa: E402
import qwen_edit  # noqa: E402
```

Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
```

with:

```python
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
        monkeypatch.setattr(character_dataset, "edit_selection_problem", lambda model_id, loras: None)
```

Edit `tests/test_character_tool.py`: replace this text, which occurs exactly once:

```python
    assert manifest["generator"].startswith("Qwen/Qwen-Image-Edit-2511 + ")
```

with:

```python
    assert manifest["generator"] == qwen_edit.generator_text("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
```

Edit `tests/test_character_tool.py` (ruling R3): replace this text, which occurs exactly once:

```python
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review")) == 2
    assert capsys.readouterr().err == (
        "Error: the seed-image editor is not downloaded: Qwen/Qwen-Image-Edit-2511; download it "
```

with:

```python
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review", "--qwen-model", "qwen2511-bf16")) == 2
    assert capsys.readouterr().err == (
        "Error: the seed-image editor is not downloaded: Qwen/Qwen-Image-Edit-2511; download it "
```

Edit `tests/test_character_tool.py` (append QET20-QET22 at the end of the file): replace this text, which occurs exactly once:

```python
        "bin/character create kyra --regenerate --new-seed\n" % os.path.join(lib_dir, "kyra", "dataset"))
```

with:

```python
        "bin/character create kyra --regenerate --new-seed\n" % os.path.join(lib_dir, "kyra", "dataset"))


# --- QET20-QET22 (qwen edit models QE32, QE36, QE37, QE39): the Qwen selection of seed-image datasets -----

UNC = [{"id": "uncensored", "scale": 1.0}]


def _floors(monkeypatch):
    """Replace wait_for_avail with a recorder of the floors it is asked for; returns the list."""
    floors = []
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: floors.append(gib) or True)
    return floors


def test_qet20_a_seed_create_records_the_selection(tmp_path, lib_dir, monkeypatch, capsys):
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=[9] * 25)
    floors = _floors(monkeypatch)
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review")) == 0
    spec = fakes.child_specs[0][0]
    assert spec["edit"] == {"qwen_model": "qwen21-q4", "loras": UNC}
    data = character_lib.load_character("kyra")
    assert data["edit"] == qwen_edit.settings("qwen21-q4", UNC)
    with open(os.path.join(lib_dir, "kyra", "dataset", "manifest.json")) as f:
        manifest = json.load(f)
    text = qwen_edit.generator_text("qwen21-q4", UNC)
    assert manifest["generator"] == text and manifest["edit"] == data["edit"]
    keys = list(manifest)
    assert keys[keys.index("generator") + 1:] == ["edit", "items"]
    assert floors == [20.0]
    assert "edit model: %s" % text in capsys.readouterr().out.splitlines()
    fakes = _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=[9] * 25)
    floors = _floors(monkeypatch)
    legacy = []
    monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: legacy.append("checked") or [])
    monkeypatch.setattr(character_dataset, "edit_selection_problem",
                        lambda model_id, loras: pytest.fail("the registry check ran for qwen2511-bf16"))
    assert tool.main(["create", "kyra-two", "--phrase", "the woman in grey", "--seed-image", _seed_image(tmp_path),
                      "--no-review", "--qwen-model", "qwen2511-bf16"]) == 0
    spec = fakes.child_specs[0][0]
    assert spec["edit"] == {"qwen_model": "qwen2511-bf16", "loras": []}
    assert (spec["model"], spec["lora_file"], spec["steps"]) == (
        "Qwen/Qwen-Image-Edit-2511", "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", 8)
    with open(os.path.join(lib_dir, "kyra-two", "dataset", "manifest.json")) as f:
        assert json.load(f)["generator"] == (
            "Qwen/Qwen-Image-Edit-2511 + Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    assert (floors, legacy) == ([64.0], ["checked"])


def test_qet21_the_options_need_a_seed_image(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, scores=[9] * 24)
    seed_only = "Error: --qwen-model and --lora apply only to seed-image characters\n"
    for extra in (("--qwen-model", "qwen21-q4"), ("--lora", "uncensored=1")):
        assert tool.main(_ronin_create(*extra)) == 2, extra
        assert capsys.readouterr().err == seed_only
    assert not os.path.exists(os.path.join(lib_dir, "ronin"))
    path = _ronin_dataset(lib_dir, monkeypatch, seed=9)
    capsys.readouterr()
    before = open(path).read()
    _Fakes(monkeypatch)
    assert tool.main(["create", "ronin", "--regenerate", "--qwen-model", "qwen21-q4"]) == 2
    assert capsys.readouterr().err == seed_only and open(path).read() == before
    _Fakes(monkeypatch)
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review", "--lora", "uncensored=1")) == 2
    assert capsys.readouterr().err == "Error: --lora needs --qwen-model\n"
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review", "--qwen-model", "flux")) == 2
    assert capsys.readouterr().err == ("Error: --qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, "
                                       "qwen2511-q4, qwen2511-bf16\n")
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review", "--qwen-model", "qwen2511-q4",
                                       "--lora", "uncensored=1")) == 2
    assert capsys.readouterr().err == ("Error: --lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 "
                                       "q4 (Lightning)\n")
    assert not os.path.exists(os.path.join(lib_dir, "kyra"))


def test_qet22_regenerate_keeps_the_record_outside_the_dataset(tmp_path, lib_dir, monkeypatch, capsys):
    _Fakes(monkeypatch, face=[350, 100, 650, 500], describe=KYRA_DESCRIBE, scores=[9] * 25)
    assert tool.main(_kyra_seed_create(tmp_path, "--no-review", "--qwen-model", "qwen21-q4")) == 0
    cdir = os.path.join(lib_dir, "kyra")
    description = os.path.join(cdir, "dataset", "description.json")
    with open(description, "rb") as f:
        saved = f.read()
    capsys.readouterr()
    fakes = _Fakes(monkeypatch, scores=[9] * 25)
    assert tool.main(["create", "kyra", "--regenerate", "--new-seed", "--no-review", "--qwen-model", "qwen21-q8",
                      "--lora", "uncensored=0.5"]) == 0
    out = capsys.readouterr().out.splitlines()
    half = [{"id": "uncensored", "scale": 0.5}]
    assert "seed: 0 -> 1" in out and "edit model: %s" % qwen_edit.generator_text("qwen21-q8", half) in out
    assert fakes.child_specs[0][0]["edit"] == {"qwen_model": "qwen21-q8", "loras": half}
    assert character_lib.load_character("kyra")["edit"] == qwen_edit.settings("qwen21-q8", half)
    assert os.path.isfile(os.path.join(cdir, "character.json"))
    with open(description, "rb") as f:
        assert f.read() == saved
    assert len(os.listdir(os.path.join(cdir, "dataset", "stills"))) == 25
    _Fakes(monkeypatch, scores=[9] * 25)
    assert tool.main(["create", "kyra", "--regenerate", "--no-review"]) == 0
    assert "seed: 1 (unchanged)" in capsys.readouterr().out.splitlines()
    assert character_lib.load_character("kyra")["edit"] == qwen_edit.settings("qwen21-q4", UNC)
```

Edit `tests/test_character_lib.py` (append QET23 at the end of the file): replace this text, which occurs exactly once:

```python
    assert lib.insert_speech("He runs. He jumps.", said) == 'He runs. He jumps. He says: "Go."'
```

with:

```python
    assert lib.insert_speech("He runs. He jumps.", said) == 'He runs. He jumps. He says: "Go."'


# --- QET23 (qwen edit models QE38): the optional edit key of character.json ----------------------------------

EDIT = {"qwen_model": {"id": "qwen21-q4", "repo": "mflux-community/qwen-image-2-1-mflux-q4"},
        "loras": [{"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
                   "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 1.0}],
        "steps": 40, "scheduler": "linear"}


def _bad_edits():
    """(bad edit value, its _edit_problem text): one bad shape per QE31 rule."""
    no_steps = dict((k, v) for k, v in EDIT.items() if k != "steps")
    model = {"id": "qwen21-q4"}
    keys = "must be an object with exactly the keys loras, qwen_model, scheduler, steps, got %r"
    loras_text = ("loras must be a list of objects with exactly the keys file, id, repo (non-empty strings) and "
                  "scale (a number in (0, 2]), got %r")
    out = [("x", keys % ("x",)), (no_steps, keys % (no_steps,)),
           (dict(EDIT, qwen_model=model), "qwen_model must be an object with exactly the keys id and repo, both "
            "non-empty strings, got %r" % (model,))]
    for loras in ([{"id": "uncensored"}], [dict(EDIT["loras"][0], scale=0)], [dict(EDIT["loras"][0], scale=2.5)]):
        out.append((dict(EDIT, loras=loras), loras_text % (loras,)))
    out += [(dict(EDIT, steps=0), "steps must be an int >= 1, got 0"),
            (dict(EDIT, scheduler=""), "scheduler must be null or a non-empty string, got ''")]
    return out


def test_qet23_the_optional_edit_key(lib_dir):
    data = make_character(lib_dir, status="untrained")
    character_lib.validate_character(data, name="kyra")
    data["edit"] = copy.deepcopy(EDIT)
    character_lib.write_character(data)
    assert character_lib.load_character("kyra")["edit"] == EDIT
    character_lib.validate_character(dict(data, edit=dict(EDIT, scheduler=None, loras=[])), name="kyra")
    for bad, text in _bad_edits():
        assert _raises(character_lib.validate_character, dict(data, edit=bad)) == "edit: " + text, bad
    descriptor = dict(data, source={"type": "descriptor"})
    assert _raises(character_lib.validate_character, descriptor) == (
        "edit: only a seed-image character records an edit model")
    del descriptor["edit"]
    character_lib.validate_character(descriptor, name="kyra")
```

Edit `tests/test_character_dataset.py` (append QET24, QET25 at the end of the file): replace this text, which occurs exactly once:

```python
        "trg man, close-up, smiling, in a park, photorealistic live-action film still, natural "
        "light.")
```

with:

```python
        "trg man, close-up, smiling, in a park, photorealistic live-action film still, natural "
        "light.")


# --- QET24, QET25 (qwen edit models QE35, QE37) ------------------------------------------------------------------

def test_qet24_the_stills_test_renders_stay_on_z_image(lib_dir, monkeypatch):
    import qwen_edit
    data = _untrained(lib_dir)
    data["edit"] = qwen_edit.settings("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    character_lib.write_character(data)
    record = _fake_stills_tools(monkeypatch)
    monkeypatch.setattr(qwen_edit, "run_jobs", lambda *args, **kwargs: pytest.fail("qwen_edit.run_jobs was called"))
    assert character_dataset.train_stills(data) == "ok"
    assert [step for _spec, step in record["children"]] == ["test-stills-lora", "test-stills-control"]
    assert _load()["edit"] == data["edit"]


def test_qet25_busy_process_sees_the_qwen_child(monkeypatch):
    py = sys.executable
    cases = [([py, "/w/seed_edit_mflux_child.py", "--spec", "s"], True),
             ([py, "/w/bin/seed-edit", "--source", "/x/src.png", "--prompt", "p"], True),
             ([py, "bin/seed-edit", "--source", "/x/src.png"], True),
             ([py, "/w/bin/seed-edit", "--probe"], False),
             ([py, "/w/bin/seed-edit-setup"], False),
             ([py, "/w/bin/seed-edit-setup", "--model", "qwen21-q4"], False),
             (["/x/ltx-2-mlx", "generate", "--model", "m"], True),
             (["python3", "bin/ltx-mlx-render", "m.json", "o.mp4"], True),
             (["/x/mflux-train", "--config", "c"], True),
             (["python3", "/w/bin/ltx-movie", "n", "--story-id", "s"], True),
             (["python3", "/w/bin/ltx-story-images", "--story-md", "s"], True),
             (["python3", "character_dataset.py", "zimage", "--spec", "s"], True),
             (["python3", "/w/character_dataset.py", "qwenedit", "--spec", "s"], True),
             (["vim", "notes-ltx-2-mlx.txt"], False)]
    for cmdline, busy in cases:
        monkeypatch.setattr(character_dataset.psutil, "process_iter",
                            lambda attrs, c=cmdline: iter([_FakeProc(4242, c)]))
        found = character_dataset.busy_process()
        assert (found is not None) == busy, cmdline
        if busy:
            assert found == (4242, " ".join(cmdline)[:120]), cmdline
```

Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
```

with:

```python
import character_dataset  # noqa: E402
import location_testutil as lt  # noqa: E402
import qwen_edit  # noqa: E402
```

Edit `tests/test_location_dataset.py` (append QET18 at the end of the file): replace this text, which occurs exactly once:

```python
    assert ld.create(_create_args(name="dock-one", description=lt.TEMPLE_DESC)) == 0
    assert calls == [1]
    assert "top-up" not in capsys.readouterr().out
```

with:

```python
    assert ld.create(_create_args(name="dock-one", description=lt.TEMPLE_DESC)) == 0
    assert calls == [1]
    assert "top-up" not in capsys.readouterr().out


# --- QET18 (qwen edit models QE33): run_edit_child routes by the spec's edit key -----------------------------

def test_qet18_run_edit_child_routes_by_the_edit_key(tmp_path, monkeypatch):
    char_dir = str(tmp_path / "loc")
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    out = [str(tmp_path / ("loc_%02d.png" % n)) for n in (3, 4)]
    base = {"image": a, "skill": "location_edit", "model": character_dataset.EDIT_MODEL,
            "lora_repo": character_dataset.EDIT_LORA_REPO, "lora_file": character_dataset.EDIT_LORA_FILE,
            "steps": character_dataset.EDIT_STEPS, "true_cfg": character_dataset.EDIT_TRUE_CFG,
            "jobs": [{"image": a, "prompt": "north view", "output_path": out[0], "seed": 4, "width": 1024,
                      "height": 640},
                     {"image": b, "prompt": "south view", "output_path": out[1], "seed": 4, "width": 1024,
                      "height": 640}]}
    runs, calls = [], []

    def _run_logged(cmd, log_path, cwd, env, timeout_s):
        spec_path = cmd[cmd.index("--spec") + 1]
        with open(spec_path, encoding="utf-8") as f:
            text = f.read()
        runs.append({"cmd": cmd, "text": text, "log": log_path, "timeout": timeout_s, "spec_path": spec_path})
        with open(json.loads(text)["report_path"], "w", encoding="utf-8") as f:
            json.dump({"jobs": [{"output_path": p, "status": "ok", "seconds": 1.0} for p in out]}, f)
        return 0

    def _run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                  noun="job"):
        calls.append({"model_id": model_id, "loras": loras, "jobs": jobs, "size": (width, height), "skill": skill,
                      "work_dir": work_dir, "log_path": log_path})
        return [{"n": j["n"], "output_path": j["output_path"], "status": "ok", "seconds": 2.5} for j in jobs], None

    monkeypatch.setattr(character_dataset, "run_logged", _run_logged)
    monkeypatch.setattr(qwen_edit, "run_jobs", _run_jobs)
    for edit in (None, {"qwen_model": "qwen2511-bf16", "loras": []}):
        spec = dict(base) if edit is None else dict(base, edit=edit)
        report = character_dataset.run_edit_child(spec, char_dir, "edit")
        run = runs[-1]
        stem = run["log"][:-len(".log")]
        assert run["cmd"] == [sys.executable, os.path.join(WS, "character_dataset.py"), "qwenedit", "--spec",
                              stem + ".spec.json"]
        assert run["text"] == json.dumps(dict(base, report_path=stem + ".report.json"), indent=2)
        assert run["timeout"] == character_dataset.EDIT_CHILD_TIMEOUT_S
        assert report == {"jobs": [{"output_path": p, "status": "ok", "seconds": 1.0} for p in out]}
    assert calls == []
    unc = [{"id": "uncensored", "scale": 1.0}]
    report = character_dataset.run_edit_child(dict(base, edit={"qwen_model": "qwen21-q4", "loras": unc}), char_dir,
                                              "edit-round2")
    (call,) = calls
    log = call["log_path"]
    assert log.startswith(os.path.join(char_dir, "logs") + os.sep) and log.endswith("-edit-round2.log")
    assert (call["model_id"], call["loras"], call["size"], call["skill"], call["work_dir"]) == (
        "qwen21-q4", unc, (1024, 640), "location_edit", log[:-len(".log")])
    assert call["jobs"] == [
        {"n": 1, "seed": 4, "prompt": "north view", "source": a, "stage_path": str(tmp_path / "loc_03.pending.png"),
         "output_path": out[0]},
        {"n": 2, "seed": 4, "prompt": "south view", "source": b, "stage_path": str(tmp_path / "loc_04.pending.png"),
         "output_path": out[1]}]
    assert report == {"jobs": [{"output_path": p, "status": "ok", "seconds": 2.5} for p in out]}
    character = {"image": a, "model": character_dataset.EDIT_MODEL, "lora_repo": character_dataset.EDIT_LORA_REPO,
                 "lora_file": character_dataset.EDIT_LORA_FILE, "steps": 8, "true_cfg": 1.0,
                 "edit": {"qwen_model": "qwen21-q4", "loras": unc},
                 "jobs": [{"prompt": "a pose", "output_path": out[0], "seed": 0, "width": 1024, "height": 640}]}
    character_dataset.run_edit_child(character, char_dir, "edit")
    assert (calls[-1]["skill"], calls[-1]["jobs"][0]["source"]) == ("character_edit", a)

    def _failing(*args, **kwargs):
        return [], "Qwen-Image-2.1 q4 child exited 1: boom"

    monkeypatch.setattr(qwen_edit, "run_jobs", _failing)
    with pytest.raises(character_dataset.DatasetError) as info:
        character_dataset.run_edit_child(character, char_dir, "edit")
    assert str(info.value) == "Qwen-Image-2.1 q4 child exited 1: boom; log: %s" % info.value.log_path
    assert info.value.log_path.endswith("-edit.log")

    def _unavailable(*args, **kwargs):
        raise qwen_edit.Unavailable("LoRA Uncensored (abenzerps) is unavailable: gone")

    monkeypatch.setattr(qwen_edit, "run_jobs", _unavailable)
    with pytest.raises(character_dataset.DatasetError) as info:
        character_dataset.run_edit_child(character, char_dir, "edit")
    assert str(info.value) == "LoRA Uncensored (abenzerps) is unavailable: gone"
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_character_tool.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_location_dataset.py -k "qet or k19 or k23" 2>&1 | tail -3`
Expected: failures for every `qet18`/`qet20`-`qet25` test, K19 and K23 (no `edit` key, no `edit_selection_problem` attribute, `unrecognized arguments: --qwen-model` from `bin/character`'s parser, the `edit: ...` texts missing, `busy_process` not seeing `seed_edit_mflux_child.py`).

- [ ] **Step 3: Write the implementation.**

Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps",
                        "trained_at", "sample_path", "control_path"])
```

with:

```python
_LORA_KEYS = frozenset(["path", "sha256", "base_model", "rank", "alpha", "steps",
                        "trained_at", "sample_path", "control_path"])
_OPTIONAL_KEYS = frozenset(["edit"])
_EDIT_KEYS = frozenset(["qwen_model", "loras", "steps", "scheduler"])
_EDIT_MODEL_KEYS = frozenset(["id", "repo"])
_EDIT_LORA_KEYS = frozenset(["id", "repo", "file", "scale"])
```

Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
def validate_character(data, name=None):
```

with:

```python
def _edit_problem(edit):
    """The problem of a recorded Qwen edit settings block (qwen edit models spec QE31), or None. Shape
    only: the registry is not consulted."""
    if not isinstance(edit, dict) or set(edit) != _EDIT_KEYS:
        return "must be an object with exactly the keys loras, qwen_model, scheduler, steps, got %r" % (edit,)
    model = edit["qwen_model"]
    if not (isinstance(model, dict) and set(model) == _EDIT_MODEL_KEYS
            and all(isinstance(model[k], str) and model[k] for k in ("id", "repo"))):
        return "qwen_model must be an object with exactly the keys id and repo, both non-empty strings, got %r" % (model,)
    loras = edit["loras"]
    if not (isinstance(loras, list) and all(
            isinstance(l, dict) and set(l) == _EDIT_LORA_KEYS
            and all(isinstance(l[k], str) and l[k] for k in ("id", "repo", "file"))
            and _is_number(l["scale"]) and 0 < l["scale"] <= 2 for l in loras)):
        return ("loras must be a list of objects with exactly the keys file, id, repo (non-empty strings) and "
                "scale (a number in (0, 2]), got %r" % (loras,))
    if not _is_int(edit["steps"]) or edit["steps"] < 1:
        return "steps must be an int >= 1, got %r" % (edit["steps"],)
    if edit["scheduler"] is not None and not (isinstance(edit["scheduler"], str) and edit["scheduler"]):
        return "scheduler must be null or a non-empty string, got %r" % (edit["scheduler"],)
    return None


def validate_character(data, name=None):
```

Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
    if extra:
        raise CharacterError("top level: unexpected keys %s" % ", ".join(extra))
```

with:

```python
    extra = sorted(set(data) - _TOP_LEVEL_KEYS - _OPTIONAL_KEYS)
    if extra:
        raise CharacterError("top level: unexpected keys %s" % ", ".join(extra))
```

Edit `character_lib.py`: replace this text, which occurs exactly once:

```python
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise CharacterError("status: %r requires a dataset with at least %d kept stills"
                             % (data["status"], MIN_KEEP))
```

with:

```python
    if data["status"] in ("untrained", "trained") and (dataset is None
                                                        or dataset["kept"] < MIN_KEEP):
        raise CharacterError("status: %r requires a dataset with at least %d kept stills"
                             % (data["status"], MIN_KEEP))
    if "edit" in data:
        if data["source"].get("type") != "seed_image":
            raise CharacterError("edit: only a seed-image character records an edit model")
        problem = _edit_problem(data["edit"])
        if problem is not None:
            raise CharacterError("edit: " + problem)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```text
the vision server. Seed-image datasets are edits of the seed (qwenedit, spec
docs/superpowers/specs/2026-10-21-character-seed-edit-design.md); descriptor datasets are
Z-Image text2img (zimage).
```

with:

```text
the vision server. Seed-image datasets are edits of the seed with the Qwen registry model of
character.json's edit key (qwen_edit.run_jobs; the qwenedit child for qwen2511-bf16;
docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md); descriptor datasets are
Z-Image text2img (zimage).
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
import ltx2_mlx_video_skill as SKILL  # noqa: E402
```

with:

```python
import ltx2_mlx_video_skill as SKILL  # noqa: E402
import qwen_edit  # noqa: E402
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    """(pid, first 120 characters of its command line) for the first render, training,
    Z-Image or Qwen-Image-Edit process found, else None. Fail-closed by design (spec 4.12,
    G17)."""
```

with:

```python
    """(pid, first 120 characters of its command line) for the first render, training,
    Z-Image or Qwen-Image-Edit, Seeds or Qwen edit (seed_edit_mflux_child.py) process found, else
    None. Fail-closed by design (spec 4.12, G17)."""
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        joined = " ".join(cmdline)
        if (("ltx-2-mlx" in joined
             and any(t in cmdline for t in ("generate", "train", "preprocess")))
                or any(marker in joined for marker in (
                    "mflux-train", "bin/ltx-movie", "bin/ltx-mlx-render",
                    "bin/ltx-story-images", "character_dataset.py zimage",
                    "character_dataset.py qwenedit"))):
            return pid, joined[:120]
```

with:

```python
        joined = " ".join(cmdline)
        seed_tool = (any(a == "bin/seed-edit" or a.endswith("/bin/seed-edit") for a in cmdline)
                     and "--probe" not in cmdline)
        if (("ltx-2-mlx" in joined
             and any(t in cmdline for t in ("generate", "train", "preprocess")))
                or seed_tool
                or any(marker in joined for marker in (
                    "mflux-train", "bin/ltx-movie", "bin/ltx-mlx-render",
                    "bin/ltx-story-images", "character_dataset.py zimage",
                    "character_dataset.py qwenedit", "seed_edit_mflux_child.py"))):
            return pid, joined[:120]
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        missing.append("%s %s" % (EDIT_LORA_REPO, EDIT_LORA_FILE))
    return missing
```

with:

```python
        missing.append("%s %s" % (EDIT_LORA_REPO, EDIT_LORA_FILE))
    return missing


def edit_selection_problem(model_id, loras):
    """None when a registry edit selection other than qwen2511-bf16 is installed and fits this host's
    memory, else the reason (qwen edit models spec QE34). qwen2511-bf16 stays checked by
    edit_models_missing. Called through this module so a test fake applies to bin/location too."""
    return qwen_edit.selection_problem(model_id, loras)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    def spec_for(entries):
        return {"image": os.path.join(char_dir, "seed.png"), "model": EDIT_MODEL,
                "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE, "steps": EDIT_STEPS,
                "true_cfg": EDIT_TRUE_CFG,
```

with:

```python
    edit_model, edit_loras = qwen_edit.selection_of(data["edit"])

    def spec_for(entries):
        return {"image": os.path.join(char_dir, "seed.png"), "model": EDIT_MODEL,
                "lora_repo": EDIT_LORA_REPO, "lora_file": EDIT_LORA_FILE, "steps": EDIT_STEPS,
                "true_cfg": EDIT_TRUE_CFG, "edit": {"qwen_model": edit_model, "loras": edit_loras},
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        min_gib = EDIT_MIN_AVAIL_GIB if seed_mode else GENERATE_MIN_AVAIL_GIB
```

with:

```python
        min_gib = qwen_edit.memory_floor(data["edit"]["qwen_model"]["id"]) if seed_mode else GENERATE_MIN_AVAIL_GIB
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
                "reference": "char_%02d" % ref_n, "face_height": face_height,
                "generator": ("%s + %s, %d steps" % (EDIT_MODEL, EDIT_LORA_FILE, EDIT_STEPS)
                              if seed_mode else "Z-Image"),
                "items": items}
```

with:

```python
                "reference": "char_%02d" % ref_n, "face_height": face_height,
                "generator": (qwen_edit.generator_text(*qwen_edit.selection_of(data["edit"]))
                              if seed_mode else "Z-Image")}
    if seed_mode:
        manifest["edit"] = data["edit"]
    manifest["items"] = items
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
SEED_MAX = 2147483647


def create(args):
```

with:

```python
SEED_MAX = 2147483647
SEED_ONLY = "--qwen-model and --lora apply only to seed-image characters"


def create(args):
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    data = None
    if args.regenerate:
```

with:

```python
    data = None
    qwen_args = (getattr(args, "qwen_model", None), getattr(args, "lora", None))
    if args.regenerate:
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        seed_mode = data["source"]["type"] == "seed_image"
        old_seed = data["seed"]
```

with:

```python
        seed_mode = data["source"]["type"] == "seed_image"
        if not seed_mode and qwen_args != (None, None):
            return _error(SEED_ONLY)
        old_seed = data["seed"]
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        seed_mode = seed_path is not None

    review = seed_mode and not getattr(args, "no_review", False)
```

with:

```python
        seed_mode = seed_path is not None
        if not seed_mode and qwen_args != (None, None):
            return _error(SEED_ONLY)

    if seed_mode:
        try:
            edit_model, edit_loras = qwen_edit.cli_selection(*qwen_args)
        except qwen_edit.SelectionError as e:
            return _error(str(e))
    review = seed_mode and not getattr(args, "no_review", False)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
    if seed_mode:
        missing = edit_models_missing()
        if missing:
            return _error("the seed-image editor is not downloaded: %s; download it with: %s"
                          % (", ".join(missing),
                             "; ".join("hf download %s" % m for m in missing)))
```

with:

```python
    if seed_mode and edit_model == qwen_edit.LEGACY_EDIT_MODEL:
        missing = edit_models_missing()
        if missing:
            return _error("the seed-image editor is not downloaded: %s; download it with: %s"
                          % (", ".join(missing),
                             "; ".join("hf download %s" % m for m in missing)))
    elif seed_mode:
        problem = edit_selection_problem(edit_model, edit_loras)
        if problem:
            return _error(problem)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
            if new_seed != old_seed:
                data["seed"] = new_seed
                try:
                    character_lib.write_character(data)
                except character_lib.CharacterError as e:
                    return _error(e)
                print("seed: %d -> %d" % (old_seed, new_seed))
            else:
                print("seed: %d (unchanged)" % old_seed)
            return _regenerate(data, review)
```

with:

```python
            changed = new_seed != old_seed
            if seed_mode:
                new_edit = qwen_edit.settings(edit_model, edit_loras)
                changed = changed or data.get("edit") != new_edit
                data["edit"] = new_edit
            data["seed"] = new_seed
            if changed:
                try:
                    character_lib.write_character(data)
                except character_lib.CharacterError as e:
                    return _error(e)
            print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
                  else "seed: %d (unchanged)" % old_seed)
            if seed_mode:
                print("edit model: %s" % qwen_edit.generator_text(edit_model, edit_loras))
            return _regenerate(data, review)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
                "stills_skip_reason": None}
        character_lib.write_character(data)
        return build_dataset(data, fh, review)
```

with:

```python
                "stills_skip_reason": None}
        if seed_path is not None:
            data["edit"] = qwen_edit.settings(edit_model, edit_loras)
        character_lib.write_character(data)
        if seed_path is not None:
            print("edit model: %s" % qwen_edit.generator_text(edit_model, edit_loras))
        return build_dataset(data, fh, review)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
def run_edit_child(spec, char_dir, step):
    """Run the seed edits in spec through Qwen-Image-Edit in a child process and return its
    report: {"jobs": [{"output_path", "status", "seconds"}]}."""
    log = step_log_path(char_dir, step)
```

with:

```python
def run_edit_child(spec, char_dir, step):
    """Run the seed edits in spec through Qwen-Image-Edit in a child process and return its
    report: {"jobs": [{"output_path", "status", "seconds"}]}."""
    edit = spec.get("edit")
    if edit is not None and edit["qwen_model"] != qwen_edit.LEGACY_EDIT_MODEL:
        return _run_registry_edit(spec, edit, char_dir, step)
    spec = dict((k, v) for k, v in spec.items() if k != "edit")
    log = step_log_path(char_dir, step)
```

Edit `character_dataset.py`: replace this text, which occurs exactly once:

```python
        return json.load(f)


def exit_with_parent(poll_s=2.0):
```

with:

```python
        return json.load(f)


def _run_registry_edit(spec, edit, char_dir, step):
    """run_edit_child for a registry model other than qwen2511-bf16 (qwen edit models spec QE33): the jobs
    through qwen_edit.run_jobs, logged to logs/<stamp>-<step>.log, staged as <stem>.pending.png beside each
    output, screened with spec["skill"] (default character_edit). Returns run_edit_child's report shape."""
    log = step_log_path(char_dir, step)
    jobs = [{"n": i, "seed": job["seed"], "prompt": job["prompt"], "source": job.get("image", spec["image"]),
             "stage_path": os.path.splitext(job["output_path"])[0] + ".pending.png",
             "output_path": job["output_path"]} for i, job in enumerate(spec["jobs"], 1)]
    print("Running: %s edit of %d stills; log: %s" % (qwen_edit.label(edit["qwen_model"]), len(jobs), log))
    sys.stdout.flush()
    try:
        results, failure = qwen_edit.run_jobs(edit["qwen_model"], edit["loras"], jobs, spec["jobs"][0]["width"],
                                              spec["jobs"][0]["height"], spec.get("skill", "character_edit"),
                                              log[:-len(".log")], log_path=log)
    except qwen_edit.Unavailable as e:
        raise DatasetError(str(e))
    if failure is not None:
        error = DatasetError("%s; log: %s" % (failure, log))
        error.log_path = log
        raise error
    return {"jobs": [{"output_path": r["output_path"], "status": r["status"], "seconds": r["seconds"]}
                     for r in results]}


def exit_with_parent(poll_s=2.0):
```

Edit `bin/character`: replace this text, which occurs exactly once:

```text
  bin/character create NAME --phrase PHRASE --seed-image PATH [--descriptor TEXT --class NOUN]
                        [--trigger WORD] [--seed N] [--force] [--no-review]
  bin/character create NAME --phrase PHRASE --descriptor TEXT --class NOUN
                        [--trigger WORD] [--seed N]
  bin/character create NAME --regenerate [--seed N | --new-seed] [--no-review]
```

with:

```text
  bin/character create NAME --phrase PHRASE --seed-image PATH [--descriptor TEXT --class NOUN]
                        [--trigger WORD] [--seed N] [--force] [--no-review] [--qwen-model ID] [--lora ID=SCALE ...]
  bin/character create NAME --phrase PHRASE --descriptor TEXT --class NOUN
                        [--trigger WORD] [--seed N]
  bin/character create NAME --regenerate [--seed N | --new-seed] [--no-review] [--qwen-model ID] [--lora ID=SCALE ...]
```

Edit `bin/character`: replace this text, which occurs exactly once:

```text
create builds the training dataset and stops for review (dataset/contact_sheet.jpg). A
--seed-image create poses the seed itself with Qwen-Image-Edit-2511 (Lightning 8-step), editing 6
preview stills first and stopping at dataset/preview_sheet.jpg before the other 18; --no-review
```

with:

```text
create builds the training dataset and stops for review (dataset/contact_sheet.jpg). A
--seed-image create poses the seed itself with a Qwen edit model (--qwen-model; default
Qwen-Image-2.1 q4 with the uncensored LoRA; qwen2511-bf16 is the earlier Qwen-Image-Edit-2511
Lightning route), editing 6 preview stills first and stopping at dataset/preview_sheet.jpg
before the other 18; --no-review
```

Edit `bin/character`: replace this text, which occurs exactly once:

```python
    p.add_argument("--no-review", dest="no_review", action="store_true",
                   help="do not stop after the 6 preview stills of a seed-image dataset")
```

with:

```python
    p.add_argument("--no-review", dest="no_review", action="store_true",
                   help="do not stop after the 6 preview stills of a seed-image dataset")
    p.add_argument("--qwen-model", dest="qwen_model", default=None, metavar="ID",
                   help="seed-image characters: the Qwen edit model of the dataset edits (qwen21-q4, qwen21-q8, "
                        "qwen21-bf16, qwen2511-q4, qwen2511-bf16; default qwen21-q4 with its default LoRAs)")
    p.add_argument("--lora", dest="lora", action="append", default=None, metavar="ID=SCALE",
                   help="with --qwen-model: a registry LoRA of its family, 0 < SCALE <= 2 (repeatable); none listed "
                        "means no LoRA")
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_character_tool.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_location_dataset.py tests/test_location_golden.py 2>&1 | tail -3`
Expected: only `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` fails (baseline); every other test passes, `test_lg3_the_character_tests_pass_unedited` included.

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged 2>&1 | tail -1` — expected: `1 failed` (the expected failure; `character_dataset.py`, `character_lib.py` and `bin/character` changed).

Run the compile check with `FILES` = `character_lib.py character_dataset.py bin/character tests/test_character_tool.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_location_dataset.py`. Expected: `compiled 7` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=3`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 26, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`, from this task until Task 8; the 7 new tests are QET18, QET20-QET25), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add character_lib.py character_dataset.py bin/character tests/test_character_tool.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_location_dataset.py
git diff --cached --name-only    # expected: exactly those seven paths
git commit -m "character: the Qwen edit model of seed-image datasets; run_edit_child routes registry models to qwen_edit (qwen edit models QE32-QE39, QET18, QET20-QET25)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Locations: the Qwen selection of photo edits, their top-ups and Regenerate (QE24-QE31; QET13-QET17, QET19, Review Focus 3)

This task implements:
- `location_lib.py` (QE31): the same constants and byte-identical `_edit_problem` as Task 3's `character_lib.py`; `validate_location`'s two `edit` rules; the docstring sentence.
- `location_dataset.py` (QE25-QE30): `PHOTO_ONLY`, the option rules of `create` and `_regenerate`, `_edit_models_problem(model_id, loras)`, the record and the `edit model:` line, `_child_spec`'s `edit`, `_render`'s floor, `_record`'s generator and `edit`; the docstring sentences (QE30's, and R14's import sentence).
- `bin/location` (QE24): `--qwen-model`, `--lora`, the usage lines and the sentence.
- Tests: §11.3's `_Fakes` line, LD13's old-mill generator and R3's LD10 edit in `tests/test_location_dataset.py`, with QET13, QET14, QET16, QET17 and Review Focus 3; QET15 in `tests/test_location_lib.py` (with the byte-identity check, R7); §11.3's `_fakes` line and QET19 in `tests/test_location_tool.py`.

**Files:**
- Modify: `location_lib.py` (docstring `:3-5`, `_PHOTO_KEYS` `:59`, `validate_location` `:186-283`), `location_dataset.py` (docstring `:5-6`, `:12`, imports `:33`, `BLOCKED` `:247`, `_child_spec` `:477-493`, `_render` `:496-504`, `_record` `:577-600`, `_edit_models_problem` `:743-748`, `create` `:785-861`, `_regenerate` `:864-931`), `bin/location` (docstring `:4-17`, parser `:70-71`).
- Modify (tests): `tests/test_location_dataset.py`, `tests/test_location_lib.py`, `tests/test_location_tool.py`.

**Interfaces:**
- Consumes (Task 1): `qwen_edit.LEGACY_EDIT_MODEL`, `SelectionError`, `cli_selection`, `settings`, `selection_of`, `generator_text`, `memory_floor`. (Task 3): `character_dataset.edit_selection_problem(model_id, loras)`, `character_dataset.run_edit_child(spec, loc_dir, step)` routing by `spec["edit"]`; `character_lib._edit_problem` (QET15 compares the code).
- Produces: `location.json`'s optional `edit` key (photo locations only) = `qwen_edit.settings(...)`; the edit child spec's `edit` = `{"qwen_model": ID, "loras": [{"id", "scale"}]}` in every round; the manifest's `edit` key after `generator` when edits ran; `bin/location create --qwen-model ID --lora ID=SCALE` (dests `qwen_model`, `lora`, defaults `None`), which Task 6's `location_argv` emits.

- [ ] **Step 1: Write the failing tests and the §11.3 / R3 edits.**

Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: list(fakes.missing))
```

with:

```python
        monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: list(fakes.missing))
        monkeypatch.setattr(character_dataset, "edit_selection_problem", lambda model_id, loras: None)
```

Edit `tests/test_location_dataset.py` (ruling R3): replace this text, which occurs exactly once:

```python
    assert ld.create(_create_args(photos=_photos(tmp_path, 2), description=lt.HARBOUR_DESC)) == 2
```

with:

```python
    assert ld.create(_create_args(photos=_photos(tmp_path, 2), description=lt.HARBOUR_DESC,
                                  qwen_model="qwen2511-bf16")) == 2
```

Edit `tests/test_location_dataset.py`: replace this text, which occurs exactly once:

```python
    assert (manifest["source"], manifest["reference"], manifest["generator"]) == (
        "photos", "source photo", "Qwen/Qwen-Image-Edit-2511 + "
        "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
```

with:

```python
    assert (manifest["source"], manifest["reference"], manifest["generator"]) == (
        "photos", "source photo", qwen_edit.generator_text("qwen21-q4", [{"id": "uncensored", "scale": 1.0}]))
```

Edit `tests/test_location_dataset.py` (append at the end of the file, after Task 3's QET18): replace this text, which occurs exactly once:

```python
    monkeypatch.setattr(qwen_edit, "run_jobs", _unavailable)
    with pytest.raises(character_dataset.DatasetError) as info:
        character_dataset.run_edit_child(character, char_dir, "edit")
    assert str(info.value) == "LoRA Uncensored (abenzerps) is unavailable: gone"
```

with:

```python
    monkeypatch.setattr(qwen_edit, "run_jobs", _unavailable)
    with pytest.raises(character_dataset.DatasetError) as info:
        character_dataset.run_edit_child(character, char_dir, "edit")
    assert str(info.value) == "LoRA Uncensored (abenzerps) is unavailable: gone"


# --- QET13-QET17 (qwen edit models QE25-QE30): the Qwen selection of photo edits ---------------------------

UNC = [{"id": "uncensored", "scale": 1.0}]


def _floors(monkeypatch):
    """Replace wait_for_avail with a recorder of the floors it is asked for; returns the list."""
    floors = []
    monkeypatch.setattr(character_dataset, "wait_for_avail", lambda gib, timeout_s: floors.append(gib) or True)
    return floors


def test_qet13_a_photo_create_records_the_selection(env, monkeypatch, tmp_path, capsys):
    fakes = _Fakes(monkeypatch)
    floors = _floors(monkeypatch)
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 2), description=lt.MILL_DESC)) == 0
    ((spec, step),) = fakes.child_specs
    stills = os.path.join(env["locations"], "old-mill", "stills")
    assert (step, spec["skill"], spec["edit"]) == ("edit", "location_edit", {"qwen_model": "qwen21-q4", "loras": UNC})
    assert [job["image"] for job in spec["jobs"][:2]] == [_loc(stills, 1), _loc(stills, 2)]
    assert _record(env, "old-mill")["edit"] == qwen_edit.settings("qwen21-q4", UNC)
    manifest = _manifest(env, "old-mill")
    text = qwen_edit.generator_text("qwen21-q4", UNC)
    assert (manifest["generator"], manifest["edit"]) == (text, qwen_edit.settings("qwen21-q4", UNC))
    assert list(manifest) == ["source", "trigger", "description", "seed", "min_score", "reference", "generator",
                              "edit", "variant_set", "rounds", "items"]
    assert floors == [20.0]
    assert "edit model: %s" % text in capsys.readouterr().out.splitlines()
    fakes = _Fakes(monkeypatch)
    floors = _floors(monkeypatch)
    assert ld.create(_create_args(name="dock-one", photos=_photos(tmp_path, 2), description=lt.MILL_DESC,
                                  qwen_model="qwen2511-bf16")) == 0
    spec = fakes.child_specs[0][0]
    assert spec["edit"] == {"qwen_model": "qwen2511-bf16", "loras": []}
    assert (spec["model"], spec["lora_file"], spec["steps"]) == (
        character_dataset.EDIT_MODEL, character_dataset.EDIT_LORA_FILE, 8)
    assert _manifest(env, "dock-one")["generator"] == (
        "Qwen/Qwen-Image-Edit-2511 + Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors, 8 steps")
    assert floors == [64.0]


def test_qet14_the_options_need_a_photo_location(env, monkeypatch, tmp_path, capsys):
    fakes = _Fakes(monkeypatch)
    photo_only = "Error: --qwen-model and --lora apply only to photo locations"
    for extra in ({"qwen_model": "qwen21-q4"}, {"lora": ["uncensored=1"]}):
        assert ld.create(_create_args(description=lt.HARBOUR_DESC, **extra)) == 2, extra
        assert _err_line(capsys) == photo_only
    assert not os.path.exists(os.path.join(env["locations"], "harbour-street"))
    assert ld.create(_create_args(description=lt.HARBOUR_DESC)) == 0
    path = os.path.join(env["locations"], "harbour-street", "location.json")
    with open(path, encoding="utf-8") as f:
        before = f.read()
    assert "edit" not in json.loads(before)
    assert ld.create(_create_args(regenerate=True, qwen_model="qwen21-q4")) == 2
    assert _err_line(capsys) == photo_only
    with open(path, encoding="utf-8") as f:
        assert f.read() == before
    paths = _photos(tmp_path, 2)
    assert ld.create(_create_args(name="old-mill", photos=paths, description=lt.MILL_DESC,
                                  lora=["uncensored=1"])) == 2
    assert _err_line(capsys) == "Error: --lora needs --qwen-model"
    assert ld.create(_create_args(name="old-mill", photos=paths, description=lt.MILL_DESC, qwen_model="flux")) == 2
    assert _err_line(capsys) == ("Error: --qwen-model must be one of qwen21-q4, qwen21-q8, qwen21-bf16, "
                                 "qwen2511-q4, qwen2511-bf16")
    assert not os.path.exists(os.path.join(env["locations"], "old-mill"))
    assert len(fakes.child_specs) == 1


def test_qet16_regenerate_records_the_selection_under_the_lock(env, monkeypatch, tmp_path, capsys):
    _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 2), description=lt.MILL_DESC)) == 0
    path = os.path.join(env["locations"], "old-mill", "location.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    del data["edit"]                                    # a photo location made before this feature
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _Fakes(monkeypatch)
    writes = []
    real_write = ll.write_location
    monkeypatch.setattr(ll, "write_location", lambda d: writes.append((d["seed"], d.get("edit"))) or real_write(d))
    assert ld.create(_create_args(name="old-mill", regenerate=True, new_seed=True, qwen_model="qwen21-q8")) == 0
    assert writes[0] == (1, qwen_edit.settings("qwen21-q8", []))
    assert _record(env, "old-mill")["edit"] == qwen_edit.settings("qwen21-q8", [])
    assert "edit model: %s" % qwen_edit.generator_text("qwen21-q8", []) in capsys.readouterr().out.splitlines()
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", regenerate=True)) == 0
    assert _record(env, "old-mill")["edit"] == qwen_edit.settings("qwen21-q4", UNC)
    assert fakes.child_specs[0][0]["edit"] == {"qwen_model": "qwen21-q4", "loras": UNC}
    fakes = _Fakes(monkeypatch)
    assert ld.create(_create_args(name="old-mill", regenerate=True, qwen_model="qwen2511-bf16")) == 0
    spec = fakes.child_specs[0][0]
    assert spec["edit"] == {"qwen_model": "qwen2511-bf16", "loras": []}
    assert {k: spec[k] for k in ("skill", "model", "lora_repo", "lora_file", "steps", "true_cfg")} == {
        "skill": "location_edit", "model": character_dataset.EDIT_MODEL,
        "lora_repo": character_dataset.EDIT_LORA_REPO, "lora_file": character_dataset.EDIT_LORA_FILE,
        "steps": 8, "true_cfg": 1.0}


def test_qet17_top_up_rounds_reuse_the_selection(env, monkeypatch, tmp_path):
    first = dict((n, dict(PASS, match_score=5)) for n in range(4, 17))
    fakes = _Fakes(monkeypatch, rounds=[first, first, {}])
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 3), description=lt.MILL_DESC,
                                  qwen_model="qwen21-q8", lora=["uncensored=0.5"])) == 0
    assert [step for _spec, step in fakes.child_specs] == ["edit", "edit-round2", "edit-round3"]
    assert [spec["edit"] for spec, _step in fakes.child_specs] == [
        {"qwen_model": "qwen21-q8", "loras": [{"id": "uncensored", "scale": 0.5}]}] * 3
    assert [r["kept"] for r in _manifest(env, "old-mill")["rounds"]] == [11, 11, 24]


# --- Review Focus 3: a 24-photo location runs no edit and needs no editor -----------------------------------

def test_qe_review_focus_3_a_24_photo_location_needs_no_editor(env, monkeypatch, tmp_path, capsys):
    fakes = _Fakes(monkeypatch, missing=["Qwen/Qwen-Image-Edit-2511"])
    monkeypatch.setattr(character_dataset, "edit_selection_problem",
                        lambda model_id, loras: "Qwen-Image-2.1 q4 is unavailable: not installed here")
    assert ld.create(_create_args(name="old-mill", photos=_photos(tmp_path, 24, size=(768, 480)),
                                  description=lt.MILL_DESC)) == 0
    assert fakes.child_specs == []
    manifest = _manifest(env, "old-mill")
    assert manifest["generator"] == "photos only" and "edit" not in manifest
    assert _record(env, "old-mill")["edit"] == qwen_edit.settings("qwen21-q4", UNC)
    assert [line for line in capsys.readouterr().out.splitlines() if line.startswith("edit model:")] == []
```

Edit `tests/test_location_lib.py` (append QET15 at the end of the file): replace this text, which occurs exactly once:

```python
        assert "harbour-street" not in names
    finally:
        os.chmod(path, 0o644)
```

with:

```python
        assert "harbour-street" not in names
    finally:
        os.chmod(path, 0o644)


# --- QET15 (qwen edit models QE31, QE38): the optional edit key of location.json ----------------------------

EDIT = {"qwen_model": {"id": "qwen21-q4", "repo": "mflux-community/qwen-image-2-1-mflux-q4"},
        "loras": [{"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
                   "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 1.0}],
        "steps": 40, "scheduler": "linear"}


def _bad_edits():
    """(bad edit value, its _edit_problem text): one bad shape per QE31 rule."""
    no_steps = dict((k, v) for k, v in EDIT.items() if k != "steps")
    model = {"id": "qwen21-q4"}
    keys = "must be an object with exactly the keys loras, qwen_model, scheduler, steps, got %r"
    loras_text = ("loras must be a list of objects with exactly the keys file, id, repo (non-empty strings) and "
                  "scale (a number in (0, 2]), got %r")
    out = [("x", keys % ("x",)), (no_steps, keys % (no_steps,)),
           (dict(EDIT, qwen_model=model), "qwen_model must be an object with exactly the keys id and repo, both "
            "non-empty strings, got %r" % (model,))]
    for loras in ([{"id": "uncensored"}], [dict(EDIT["loras"][0], scale=0)], [dict(EDIT["loras"][0], scale=2.5)]):
        out.append((dict(EDIT, loras=loras), loras_text % (loras,)))
    out += [(dict(EDIT, steps=0), "steps must be an int >= 1, got 0"),
            (dict(EDIT, scheduler=""), "scheduler must be null or a non-empty string, got ''")]
    return out


def _code_of(source, name):
    """The text of function name in source, without its docstring (tests/test_movie_ui_seedgen.py's)."""
    start = source.index("\ndef %s(" % name)
    text = source[start:source.index("\n\n\n", start)]
    doc = text.index('"""')
    return text[:doc] + text[text.index('"""', doc + 3) + 3:]


def test_qet15_the_optional_edit_key(env):
    lib = env["locations"]
    data = lt.mill(lib, status="untrained", source="photos")
    ll.validate_location(data, name="old-mill")
    data["edit"] = json.loads(json.dumps(EDIT))
    ll.write_location(data)
    assert ll.load_location("old-mill")["edit"] == EDIT
    ll.validate_location(dict(data, edit=dict(EDIT, scheduler=None, loras=[])), name="old-mill")
    for bad, text in _bad_edits():
        assert _raises(ll.validate_location, dict(data, edit=bad)) == "edit: " + text, bad
    text_location = lt.harbour(lib)
    assert _raises(ll.validate_location, dict(text_location, edit=EDIT)) == (
        "edit: only a photo location records an edit model")
    ll.validate_location(text_location, name="harbour-street")
    sources = []
    for rel in ("location_lib.py", "character_lib.py"):
        with open(os.path.join(WS, rel), encoding="utf-8") as f:
            sources.append(f.read())
    assert _code_of(sources[0], "_edit_problem") == _code_of(sources[1], "_edit_problem")
    for name in ("_OPTIONAL_KEYS", "_EDIT_KEYS", "_EDIT_MODEL_KEYS", "_EDIT_LORA_KEYS"):
        assert getattr(ll, name) == getattr(cl, name), name
```

Edit `tests/test_location_tool.py`: replace this text, which occurs exactly once:

```python
    monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
```

with:

```python
    monkeypatch.setattr(character_dataset, "edit_models_missing", lambda: [])
    monkeypatch.setattr(character_dataset, "edit_selection_problem", lambda model_id, loras: None)
```

Edit `tests/test_location_tool.py` (append QET19 at the end of the file): replace this text, which occurs exactly once:

```python
    assert calls == ["video", "video", "stills"]
    assert ll.load_location("harbour-street")["status"] == "trained"
```

with:

```python
    assert calls == ["video", "video", "stills"]
    assert ll.load_location("harbour-street")["status"] == "trained"


# --- QET19 (qwen edit models QE24): bin/location create's two options -------------------------------------

def test_qet19_the_create_options(env):
    create = _subprocess(["create", "--help"])
    assert create.returncode == 0
    text = " ".join(create.stdout.split())
    for flag in ("[--qwen-model ID]", "[--lora ID=SCALE]"):
        assert flag in text, flag
    args = tool.build_parser().parse_args(["create", "old-mill", "--photo", "p.png", "--qwen-model", "qwen21-q4",
                                           "--lora", "uncensored=1", "--lora", "viggle-turbo=0.5"])
    assert (args.qwen_model, args.lora) == ("qwen21-q4", ["uncensored=1", "viggle-turbo=0.5"])
    args = tool.build_parser().parse_args(["create", "old-mill"])
    assert (args.qwen_model, args.lora) == (None, None)
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_lib.py tests/test_location_tool.py 2>&1 | tail -3`
Expected: failures for QET13-QET17, Review Focus 3, QET15, QET19 and LD13 (no `edit` key, generator text, no `--qwen-model`); LD10 still passes (today's photo create runs the legacy check, which the R3 edit pins explicitly).

- [ ] **Step 3: Write the implementation.**

Edit `location_lib.py`: replace this text, which occurs exactly once:

```text
Stdlib only. This module is the single owner of the location.json schema (schema_version 1), of
the location name, description and trigger rules, of resolving pinned locations (--location NAME)
into LocationPin records, and of reading a story's plan.json for the panels set at a pinned
```

with:

```text
Stdlib only. This module is the single owner of the location.json schema (schema_version 1, with
the optional edit key of docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md), of the
location name, description and trigger rules, of resolving pinned locations (--location NAME)
into LocationPin records, and of reading a story's plan.json for the panels set at a pinned
```

Edit `location_lib.py`: replace this text, which occurs exactly once:

```python
_PHOTO_KEYS = frozenset(["path", "sha256"])
```

with:

```python
_PHOTO_KEYS = frozenset(["path", "sha256"])
_OPTIONAL_KEYS = frozenset(["edit"])
_EDIT_KEYS = frozenset(["qwen_model", "loras", "steps", "scheduler"])
_EDIT_MODEL_KEYS = frozenset(["id", "repo"])
_EDIT_LORA_KEYS = frozenset(["id", "repo", "file", "scale"])
```

Edit `location_lib.py`: replace this text, which occurs exactly once:

```python
def validate_location(data, name=None):
```

with:

```python
def _edit_problem(edit):
    """The problem of a recorded Qwen edit settings block (qwen edit models spec QE31), or None. Shape
    only: the registry is not consulted."""
    if not isinstance(edit, dict) or set(edit) != _EDIT_KEYS:
        return "must be an object with exactly the keys loras, qwen_model, scheduler, steps, got %r" % (edit,)
    model = edit["qwen_model"]
    if not (isinstance(model, dict) and set(model) == _EDIT_MODEL_KEYS
            and all(isinstance(model[k], str) and model[k] for k in ("id", "repo"))):
        return "qwen_model must be an object with exactly the keys id and repo, both non-empty strings, got %r" % (model,)
    loras = edit["loras"]
    if not (isinstance(loras, list) and all(
            isinstance(l, dict) and set(l) == _EDIT_LORA_KEYS
            and all(isinstance(l[k], str) and l[k] for k in ("id", "repo", "file"))
            and _is_number(l["scale"]) and 0 < l["scale"] <= 2 for l in loras)):
        return ("loras must be a list of objects with exactly the keys file, id, repo (non-empty strings) and "
                "scale (a number in (0, 2]), got %r" % (loras,))
    if not _is_int(edit["steps"]) or edit["steps"] < 1:
        return "steps must be an int >= 1, got %r" % (edit["steps"],)
    if edit["scheduler"] is not None and not (isinstance(edit["scheduler"], str) and edit["scheduler"]):
        return "scheduler must be null or a non-empty string, got %r" % (edit["scheduler"],)
    return None


def validate_location(data, name=None):
```

Edit `location_lib.py`: replace this text, which occurs exactly once:

```python
    extra = sorted(set(data) - _TOP_LEVEL_KEYS)
```

with:

```python
    extra = sorted(set(data) - _TOP_LEVEL_KEYS - _OPTIONAL_KEYS)
```

Edit `location_lib.py`: replace this text, which occurs exactly once:

```python
        raise LocationError("status: %r requires a dataset with at least %d kept stills"
                            % (data["status"], MIN_KEEP))
```

with:

```python
        raise LocationError("status: %r requires a dataset with at least %d kept stills"
                            % (data["status"], MIN_KEEP))
    if "edit" in data:
        if data["source"] != "photos":
            raise LocationError("edit: only a photo location records an edit model")
        problem = _edit_problem(data["edit"])
        if problem is not None:
            raise LocationError("edit: " + problem)
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```text
description (text mode), or the user's photos plus Qwen-Image-Edit-2511 edits of them that
re-shoot the place from a new viewpoint at a new time of day, weather or season (photo mode).
```

with:

```text
description (text mode), or the user's photos plus Qwen edits (the registry model of
location.json's edit key; docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md) of them that
re-shoot the place from a new viewpoint at a new time of day, weather or season (photo mode).
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```text
Top-level imports are stdlib, PIL, psutil, character_dataset and location_lib. All
```

with:

```text
Top-level imports are stdlib, PIL, psutil, character_dataset, location_lib and qwen_edit. All
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
import location_lib  # noqa: E402
```

with:

```python
import location_lib  # noqa: E402
import qwen_edit  # noqa: E402
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
BLOCKED = "blocked by the content screen"
```

with:

```python
BLOCKED = "blocked by the content screen"
PHOTO_ONLY = "--qwen-model and --lora apply only to photo locations"
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
    return "edit", {"image": jobs[0]["image"], "skill": "location_edit",
                    "model": character_dataset.EDIT_MODEL,
                    "lora_repo": character_dataset.EDIT_LORA_REPO,
                    "lora_file": character_dataset.EDIT_LORA_FILE,
                    "steps": character_dataset.EDIT_STEPS,
                    "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}
```

with:

```python
    edit_model, edit_loras = qwen_edit.selection_of(data["edit"])
    return "edit", {"image": jobs[0]["image"], "skill": "location_edit",
                    "model": character_dataset.EDIT_MODEL,
                    "lora_repo": character_dataset.EDIT_LORA_REPO,
                    "lora_file": character_dataset.EDIT_LORA_FILE,
                    "steps": character_dataset.EDIT_STEPS,
                    "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs,
                    "edit": {"qwen_model": edit_model, "loras": edit_loras}}
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, step)))
```

with:

```python
        _with_story_server_stopped(qwen_edit.memory_floor(spec["edit"]["qwen_model"]), lambda: (
            character_dataset.run_edit_child(spec, loc_dir, step)))
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
                "generator": ("Z-Image" if not photo_mode
                              else "%s + %s, %d steps" % (character_dataset.EDIT_MODEL,
                                                          character_dataset.EDIT_LORA_FILE,
                                                          character_dataset.EDIT_STEPS)
                              if child == "edit" else "photos only"),
                "variant_set": variant_set, "rounds": rounds, "items": items}
```

with:

```python
                "generator": ("Z-Image" if not photo_mode
                              else qwen_edit.generator_text(*qwen_edit.selection_of(data["edit"]))
                              if child == "edit" else "photos only")}
    if child == "edit":
        manifest["edit"] = data["edit"]
    manifest["variant_set"] = variant_set
    manifest["rounds"] = rounds
    manifest["items"] = items
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
def _edit_models_problem():
    missing = character_dataset.edit_models_missing()
```

with:

```python
def _edit_models_problem(model_id, loras):
    """The photo editor preflight (qwen edit models QE26): qwen2511-bf16 keeps today's check of the
    diffusers weights; every other registry model is checked through character_dataset."""
    if model_id != qwen_edit.LEGACY_EDIT_MODEL:
        return character_dataset.edit_selection_problem(model_id, loras)
    missing = character_dataset.edit_models_missing()
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
        return _error("create needs --description or at least one --photo")
```

with:

```python
        return _error("create needs --description or at least one --photo")
    qwen_model, lora = getattr(args, "qwen_model", None), getattr(args, "lora", None)
    if not photos and (qwen_model is not None or lora is not None):
        return _error(PHOTO_ONLY)
    edit_model = edit_loras = None
    if photos:
        try:
            edit_model, edit_loras = qwen_edit.cli_selection(qwen_model, lora)
        except qwen_edit.SelectionError as e:
            return _error(str(e))
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
    if photos and len(photos) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
```

with:

```python
    if photos and len(photos) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem(edit_model, edit_loras)
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
                "stills_skip_reason": None, "strength": None}
        location_lib.write_location(data)
        return build_dataset(data, args.force)
```

with:

```python
                "stills_skip_reason": None, "strength": None}
        if photos:
            data["edit"] = qwen_edit.settings(edit_model, edit_loras)
        location_lib.write_location(data)
        if photos and len(photos) < location_lib.TOTAL_STILLS:
            print("edit model: %s" % qwen_edit.generator_text(edit_model, edit_loras))
        return build_dataset(data, args.force)
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
                      "the trigger it was created with")
```

with:

```python
                      "the trigger it was created with")
    qwen_model, lora = getattr(args, "qwen_model", None), getattr(args, "lora", None)
    if data["source"] != "photos" and (qwen_model is not None or lora is not None):
        return _error(PHOTO_ONLY)
    edit_model = edit_loras = None
    if data["source"] == "photos":
        try:
            edit_model, edit_loras = qwen_edit.cli_selection(qwen_model, lora)
        except qwen_edit.SelectionError as e:
            return _error(str(e))
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
    if data["source"] == "photos" and len(data["photos"]) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem()
```

with:

```python
    if data["source"] == "photos" and len(data["photos"]) < location_lib.TOTAL_STILLS:
        problem = _edit_models_problem(edit_model, edit_loras)
```

Edit `location_dataset.py`: replace this text, which occurs exactly once:

```python
        data["seed"], data["description"] = new_seed, description
        data["status"], data["dataset"] = "dataset", None
        location_lib.write_location(data)
        print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
              else "seed: %d (unchanged)" % old_seed)
```

with:

```python
        data["seed"], data["description"] = new_seed, description
        if data["source"] == "photos":
            data["edit"] = qwen_edit.settings(edit_model, edit_loras)
        data["status"], data["dataset"] = "dataset", None
        location_lib.write_location(data)
        print("seed: %d -> %d" % (old_seed, new_seed) if new_seed != old_seed
              else "seed: %d (unchanged)" % old_seed)
        if data["source"] == "photos" and len(data["photos"]) < location_lib.TOTAL_STILLS:
            print("edit model: %s" % qwen_edit.generator_text(edit_model, edit_loras))
```

Edit `bin/location`: replace this text, which occurs exactly once:

```text
  bin/location create NAME [--description TEXT] [--photo PATH ...] [--trigger WORD] [--seed N]
                           [--force]
  bin/location create NAME --regenerate [--seed N | --new-seed] [--description TEXT] [--force]
```

with:

```text
  bin/location create NAME [--description TEXT] [--photo PATH ...] [--trigger WORD] [--seed N]
                           [--force] [--qwen-model ID] [--lora ID=SCALE ...]
  bin/location create NAME --regenerate [--seed N | --new-seed] [--description TEXT] [--force]
                           [--qwen-model ID] [--lora ID=SCALE ...]
```

Edit `bin/location`: replace this text, which occurs exactly once:

```text
5 photos. train trains the video LoRA (ltx-2-mlx) and, when mflux is installed and its adapter
```

with:

```text
5 photos. Photo edits (and their top-up rounds) use the Qwen edit model of --qwen-model (default
qwen21-q4 with the uncensored LoRA); text stills stay Z-Image. train trains the video LoRA
(ltx-2-mlx) and, when mflux is installed and its adapter
```

Edit `bin/location`: replace this text, which occurs exactly once:

```python
    p.add_argument("--new-seed", dest="new_seed", action="store_true",
                   help="with --regenerate: use the stored seed + 1")
```

with:

```python
    p.add_argument("--new-seed", dest="new_seed", action="store_true",
                   help="with --regenerate: use the stored seed + 1")
    p.add_argument("--qwen-model", dest="qwen_model", default=None, metavar="ID",
                   help="photo locations: the Qwen edit model of the edits (qwen21-q4, qwen21-q8, qwen21-bf16, "
                        "qwen2511-q4, qwen2511-bf16; default qwen21-q4 with its default LoRAs)")
    p.add_argument("--lora", dest="lora", action="append", default=None, metavar="ID=SCALE",
                   help="with --qwen-model: a registry LoRA of its family, 0 < SCALE <= 2 (repeatable); none listed "
                        "means no LoRA")
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_location_dataset.py tests/test_location_lib.py tests/test_location_tool.py tests/test_location_ui.py tests/test_location_story.py tests/test_location_golden.py 2>&1 | tail -1`
Expected: `N passed` with no failure.

Run the compile check with `FILES` = `location_lib.py location_dataset.py bin/location tests/test_location_dataset.py tests/test_location_lib.py tests/test_location_tool.py`. Expected: `compiled 6` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=4`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 33, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`; the 7 new tests are QET13-QET17, QET19 and Review Focus 3), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add location_lib.py location_dataset.py bin/location tests/test_location_dataset.py tests/test_location_lib.py tests/test_location_tool.py
git diff --cached --name-only    # expected: exactly those six paths
git commit -m "location: the Qwen edit model of photo edits, their top-ups and Regenerate (qwen edit models QE24-QE31, QET13-QET17, QET19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Compose: `bin/ltx-movie --seed-edit-model` and Phase 1c (pinned) (QE40-QE50; QET26-QET32)

This task implements, in `bin/ltx-movie`:
- QE40: `--seed-edit-model ID|as-is` and repeatable `--seed-edit-lora ID=SCALE` after `--seed-image` (no top-level import change: ruling R1 imports `hashlib` inside `phase_seed_edit`).
- QE41 `_qwen_edit()`; QE42/QE43 `_resolve_seed_edit(args)` and its call after `_resolve_locations`.
- QE44 the Phase 1c insertion in `_phase_sequence`; QE45 `SEED_EDIT_SKILL`, `SEED_EDIT_SCHEMA`, `_seed_edit_paths`; QE46 `_panel1_edit_prompt`; QE47 `_seed_edit_size`; QE48 `phase_seed_edit` (with `_write_seed_edit_record`, R10).
- QE49 the Phase 2 seed and QE50 the dry run, both through ruling R2 (the pinned `--seed-image` literals stay); the docstring paragraph.
- Tests: the new `tests/test_ltx_movie_seed_edit.py` (QET26-QET32); `NEW_PY` gains it (R6) and QET11's assertion grows.

**Files:**
- Modify: `bin/ltx-movie` (docstring end `:106-108`, constants `:129`, parser `:306`, `_location_lib` `:808-815`, `_resolve_locations` end `:960-963`, `phase_release_story_server` end `:2158-2159`, `phase2_stills` `:2027-2028`, dry run `:2552-2558`, `:2570-2571`, `_phase_sequence` `:2648-2655`, `main` `:2728-2730`).
- Create: `tests/test_ltx_movie_seed_edit.py`.
- Modify: `tests/test_movie_ui_builder.py` (`NEW_PY`), `tests/test_qwen_edit.py` (QET11's tail list).

**Interfaces:**
- Consumes (Task 1, through `_qwen_edit()`): `MODEL_IDS`, `SelectionError`, `Unavailable`, `cli_selection(model_arg, lora_args, model_flag, lora_flag)`, `selection_problem(model_id, loras)`, `settings`, `label`, `multiple`, `memory_floor`, `generator_text`, `wait_for_memory(floor, label, tag=...)`, `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job")`. Existing: `_story_paths`, `_story_dir`, `_load_story_panels`, `_image_fit().load_oriented_rgb`, `bin/ltx-story-images`' `_compose_prompt(image_text, style_text)` and `_style_text(panels)`.
- Produces (Task 6's argv and the page rely on these): the flags `--seed-edit-model` (dest `seed_edit_model`) and `--seed-edit-lora` (dest `seed_edit_loras`, append); `args.seed_edit` (`None` or `{"qwen_model": ID, "loras": [{"id", "scale"}]}`); the progress line `=== Phase 1c: seed edit ===` (Task 6's `PHASE_RE`); the story files `seed-original.png`, `seed-edited.png`, `seed_edit.json` (schema `ltx-movie.seed-edit.v1`), `seed_edit_work/`.

- [ ] **Step 1: Write the failing tests.**

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "qwen_edit.py", "tests/test_qwen_edit.py")
```

with:

```python
          "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py")
```

Edit `tests/test_qwen_edit.py`: replace this text, which occurs exactly once:

```python
    assert new_py[new_py.index("tests/test_movie_ui_seedgen.py") + 1:] == ["qwen_edit.py", "tests/test_qwen_edit.py"]
```

with:

```python
    assert new_py[new_py.index("tests/test_movie_ui_seedgen.py") + 1:] == [
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py"]
```

Write `tests/test_ltx_movie_seed_edit.py` with exactly this content (the Write tool):

```python
"""Tests for bin/ltx-movie's seed edit (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md,
Section 7, test table 11.2: QET26-QET32): --seed-edit-model and --seed-edit-lora, their rules, Phase 1c,
seed_edit.json, the Phase 2 seed and the dry run.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_edit.py

Rules (spec 11.1): bin/ltx-movie is loaded with SourceFileLoader, spec_from_loader, module_from_spec and
exec_module as ltx_movie_qe. Every test patches _story_dir to <tmp>/stories/<id>, HOME to <tmp>/home and
_qwen_edit to a fake module (the qe_fake fixture): the real qwen_edit's MODEL_IDS, cli_selection,
SelectionError, Unavailable, settings, label, multiple, memory_floor and generator_text, and recorders for
selection_problem, wait_for_memory and run_jobs. Nothing loads a model, renders, contacts a server or
touches port 8177 or 8178; the only processes are none (Phase 2's subprocess.run is a recorder). Stdlib,
PIL and pytest.
"""

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import types

import pytest
from PIL import Image

import movie_ui_testutil as mt
import qwen_edit

WS = mt.WS
UNC = [{"id": "uncensored", "scale": 1.0}]
IMAGE = "A ronin in a grey kimono stands at a red temple gate at dusk, wide shot."
STYLE = "Muted film colour with soft grain."
PROMPT = IMAGE + " " + STYLE
STORY_MD = ("# The gate\n\nA ronin returns to his temple at dusk.\n\n"
            "## Panel 1 — The gate\nImage: %s\nStyle: %s\nMotion: The ronin bows. The camera stays static.\n"
            "Narration: He has come home.\n\n"
            "## Panel 2 — The road\nMotion: The ronin walks down the road. The camera follows him.\n"
            "Narration: The road behind him is long.\n" % (IMAGE, STYLE))


def _load_movie():
    path = os.path.join(WS, "bin", "ltx-movie")
    loader = importlib.machinery.SourceFileLoader("ltx_movie_qe", path)
    spec = importlib.util.spec_from_loader("ltx_movie_qe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


movie = _load_movie()


class _FakeQwenEdit(object):
    """QET26's fake qwen_edit: the real pure parts, and recorders for the three calls that would touch the
    host. result is "ok" (run_jobs writes the output and reports 12.5 s), "blocked", a failure text, or an
    exception to raise."""
    MODEL_IDS = qwen_edit.MODEL_IDS
    SelectionError = qwen_edit.SelectionError
    Unavailable = qwen_edit.Unavailable

    def __init__(self):
        self.calls = {"selection_problem": [], "wait_for_memory": [], "run_jobs": []}
        self.problem = None
        self.result = "ok"
        for name in ("cli_selection", "settings", "label", "multiple", "memory_floor", "generator_text"):
            setattr(self, name, getattr(qwen_edit, name))

    def selection_problem(self, model_id, loras):
        self.calls["selection_problem"].append((model_id, loras))
        return self.problem

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.calls["wait_for_memory"].append((floor, label, tag))

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.calls["run_jobs"].append({"model_id": model_id, "loras": loras, "jobs": jobs, "size": (width, height),
                                       "skill": skill, "work_dir": work_dir})
        job = jobs[0]
        if isinstance(self.result, Exception):
            raise self.result
        if self.result == "ok":
            Image.new("RGB", (width, height), (0, 0, 200)).save(job["output_path"])
            return [{"n": 1, "output_path": job["output_path"], "status": "ok", "seconds": 12.5}], None
        if self.result == "blocked":
            return [{"n": 1, "output_path": job["output_path"], "status": "blocked", "seconds": 12.5}], None
        return [{"n": 1, "output_path": job["output_path"], "status": "failed", "seconds": None}], self.result


@pytest.fixture
def qe_fake(monkeypatch, tmp_path):
    fake = _FakeQwenEdit()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(movie, "_story_dir", lambda story_id: os.path.join(str(tmp_path), "stories", story_id))
    monkeypatch.setenv("HOME", os.path.join(str(tmp_path), "home"))
    return fake


def _args(*extra):
    return movie.build_parser().parse_args(["a narrative", "--story-id", "s1"] + list(extra))


class _PhaseArgs(object):
    def __init__(self, no_stills=False, story_server_stop_after_story=False, seed_image=None, story_only=False,
                 seed_edit=None):
        self.no_stills, self.story_server_stop_after_story = no_stills, story_server_stop_after_story
        self.seed_image, self.story_only, self.seed_edit = seed_image, story_only, seed_edit
        self.min_avail_gib, self.avail_timeout = 25.0, 1800


def _names(args):
    return tuple(p.__name__ for p in movie._phase_sequence(args))


def _seed_jpeg(path, color=(0, 200, 0)):
    """A 200x100 JPEG whose EXIF orientation 6 makes it 100x200 when oriented."""
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (200, 100), color).save(path, "JPEG", exif=exif.tobytes())
    return path


def _edit_args(tmp_path, model="qwen21-q4", loras=None, width=704, height=448, image_seed=3, story_id="s1"):
    seed = os.path.join(str(tmp_path), "seed.jpg")
    if not os.path.isfile(seed):
        _seed_jpeg(seed)
    return argparse.Namespace(story_id=story_id, seed_image=seed, video_width=width, video_height=height,
                              image_seed=image_seed,
                              seed_edit={"qwen_model": model, "loras": UNC if loras is None else loras})


def _write_story(tmp_path, story_id="s1", text=STORY_MD):
    story_dir = os.path.join(str(tmp_path), "stories", story_id)
    os.makedirs(story_dir, exist_ok=True)
    with open(os.path.join(story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return story_dir


def _files(story_dir):
    return {"original": os.path.join(story_dir, "seed-original.png"),
            "edited": os.path.join(story_dir, "seed-edited.png"),
            "record": os.path.join(story_dir, "seed_edit.json"),
            "work": os.path.join(story_dir, "seed_edit_work"),
            "stage": os.path.join(story_dir, "seed_edit_work", "seed-edited.pending.png")}


L41 = [(dict(), ("phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(story_server_stop_after_story=True),
        ("phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True), ("phase1_story", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True, story_server_stop_after_story=True),
        ("phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render")),
       (dict(seed_image="x.png"), ("phase0_seed", "phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
       (dict(story_server_stop_after_story=True, seed_image="x.png"),
        ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
         "phase4_render")),
       (dict(no_stills=True, seed_image="x.png"), ("phase0_seed", "phase1_story", "phase3_manifest", "phase4_render")),
       (dict(no_stills=True, story_server_stop_after_story=True, seed_image="x.png"),
        ("phase0_seed", "phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render"))]


# --- QET26 (QE40-QE44, QEK4): the options, their rules and the unchanged phase tuples ----------------------

def test_qet26_the_options_and_their_rules(qe_fake, capsys):
    args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1",
                 "--seed-edit-lora", "viggle-turbo=0.5")
    assert (args.seed_edit_model, args.seed_edit_loras) == ("qwen21-q4", ["uncensored=1", "viggle-turbo=0.5"])
    assert (_args().seed_edit_model, _args().seed_edit_loras) == (None, None)
    rules = [(("--seed-edit-lora", "uncensored=1"), "--seed-edit-lora needs --seed-edit-model"),
             (("--seed-edit-model", "qwen21-q4"), "--seed-edit-model needs --seed-image"),
             (("--seed-image", "x.png", "--seed-edit-model", "as-is", "--seed-edit-lora", "uncensored=1"),
              "--seed-edit-lora cannot be combined with --seed-edit-model as-is"),
             (("--seed-image", "x.png", "--seed-edit-model", "flux"),
              "--seed-edit-model must be as-is or one of qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, "
              "qwen2511-bf16"),
             (("--seed-image", "x.png", "--seed-edit-model", "qwen2511-q4", "--seed-edit-lora", "uncensored=1"),
              "--seed-edit-lora uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
             (("--seed-image", "x.png", "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored"),
              "--seed-edit-lora must be ID=SCALE (got uncensored)")]
    for extra, text in rules:
        args = _args(*extra)
        assert movie._resolve_seed_edit(args) == 2, extra
        assert capsys.readouterr().err == "Error: %s\n" % text, extra
    for extra in ((), ("--seed-image", "x.png"), ("--seed-image", "x.png", "--seed-edit-model", "as-is")):
        args = _args(*extra)
        assert movie._resolve_seed_edit(args) == 0 and args.seed_edit is None, extra
    assert qe_fake.calls["selection_problem"] == []
    args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q8", "--seed-edit-lora", "uncensored=0.5")
    assert movie._resolve_seed_edit(args) == 0
    assert args.seed_edit == {"qwen_model": "qwen21-q8", "loras": [{"id": "uncensored", "scale": 0.5}]}
    assert qe_fake.calls["selection_problem"] == [("qwen21-q8", [{"id": "uncensored", "scale": 0.5}])]
    qe_fake.problem = "Qwen-Image-2.1 q8 is unavailable: not here (run bin/seed-edit-setup --model qwen21-q8)"
    assert movie._resolve_seed_edit(args) == 2 and args.seed_edit is None
    assert capsys.readouterr().err == ("Error: --seed-edit-model qwen21-q8: Qwen-Image-2.1 q8 is unavailable: not "
                                       "here (run bin/seed-edit-setup --model qwen21-q8)\n")
    for flag in ("--dry-run", "--story-only"):
        args = _args("--seed-image", "x.png", "--seed-edit-model", "qwen21-q8", flag)
        assert movie._resolve_seed_edit(args) == 0 and args.seed_edit["qwen_model"] == "qwen21-q8", flag
    assert len(qe_fake.calls["selection_problem"]) == 2
    for kwargs, names in L41:
        assert _names(_PhaseArgs(**kwargs)) == names, kwargs


# --- QET27 (QE44): Phase 1c sits after the story (and its release) and before the stills -------------------

def test_qet27_the_phase_sequence_with_a_seed_edit():
    edit = {"qwen_model": "qwen21-q4", "loras": UNC}
    assert _names(_PhaseArgs(seed_image="x.png", story_server_stop_after_story=True, seed_edit=edit)) == (
        "phase0_seed", "phase1_story", "phase_release_story_server", "phase_seed_edit", "phase2_stills",
        "phase3_manifest", "phase4_render")
    assert _names(_PhaseArgs(seed_image="x.png", seed_edit=edit)) == (
        "phase0_seed", "phase1_story", "phase_seed_edit", "phase2_stills", "phase3_manifest", "phase4_render")
    assert _names(_PhaseArgs(seed_image="x.png", story_only=True, seed_edit=edit)) == ("phase0_seed", "phase1_story")


# --- QET28 (QE45-QE49): Phase 1c edits the seed into panel 1, and Phase 2 takes the edited image ------------

def test_qet28_phase_1c_edits_the_seed_into_panel_1(qe_fake, tmp_path, monkeypatch, capsys):
    story_dir = _write_story(tmp_path)
    files = _files(story_dir)
    args = _edit_args(tmp_path)
    assert movie.phase_seed_edit(args) == 0
    (call,) = qe_fake.calls["run_jobs"]
    assert call == {"model_id": "qwen21-q4", "loras": UNC, "size": (704, 448), "skill": "ltx_movie_seed_edit",
                    "work_dir": files["work"],
                    "jobs": [{"n": 1, "seed": 3, "prompt": PROMPT, "source": files["original"],
                              "stage_path": files["stage"], "output_path": files["edited"]}]}
    assert qe_fake.calls["wait_for_memory"] == [(20.0, "Qwen-Image-2.1 q4", "ltx-movie")]
    with Image.open(files["original"]) as img:
        assert (img.format, img.size) == ("PNG", (100, 200))
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    with open(args.seed_image, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    settings = qwen_edit.settings("qwen21-q4", UNC)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["created"])
    assert list(record) == ["schema", "created", "status", "label", "source", "source_sha256", "original", "output",
                            "prompt", "seed", "width", "height", "qwen_model", "loras", "steps", "scheduler",
                            "seconds", "error"]
    assert dict(record, created=None) == {
        "schema": "ltx-movie.seed-edit.v1", "created": None, "status": "ok", "label": "Qwen-Image-2.1 q4",
        "source": os.path.abspath(args.seed_image), "source_sha256": sha, "original": "seed-original.png",
        "output": "seed-edited.png", "prompt": PROMPT, "seed": 3, "width": 704, "height": 448,
        "qwen_model": settings["qwen_model"], "loras": settings["loras"], "steps": 40, "scheduler": "linear",
        "seconds": 12.5, "error": None}
    assert args.seed_edited_path == files["edited"]
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "=== Phase 1c: seed edit ==="
    assert out[1] == "seed edit: %s; 704x448; seed 3; prompt: panel 1's Image: text (%d characters)" % (
        qwen_edit.generator_text("qwen21-q4", UNC), len(PROMPT))
    assert out[-1] == "seed edit: %s (12.5 s)" % files["edited"]
    runs = []
    monkeypatch.setattr(movie.subprocess, "run", lambda cmd, cwd=None: runs.append(cmd) or types.SimpleNamespace(
        returncode=0))
    monkeypatch.setattr(movie, "_catalog_stills_flags", lambda a, dry_run=False: (None, []))
    phase2 = argparse.Namespace(**vars(args))
    phase2.global_stills_loras = phase2.stills_lora_path = phase2.cast_members = phase2.location_pins = None
    phase2.shots = False
    assert movie.phase2_stills(phase2) == 0
    (cmd,) = runs
    assert cmd.count("--seed-image") == 1 and cmd[cmd.index("--seed-image") + 1] == files["edited"]
    for model, loras, size in (("qwen2511-q4", [], (720, 448)), ("qwen21-q4", UNC, (704, 448))):
        qe_fake.calls["run_jobs"] = []
        edit_args = _edit_args(tmp_path, model=model, loras=loras, width=720, height=448, story_id="s-" + model)
        _write_story(tmp_path, edit_args.story_id)
        assert movie.phase_seed_edit(edit_args) == 0
        assert qe_fake.calls["run_jobs"][0]["size"] == size, model


# --- QET29 (QE48 step 9): a blocked or failed edit stops the movie before Phase 2 ---------------------------

def test_qet29_a_blocked_or_failed_edit_stops_the_movie(qe_fake, tmp_path, monkeypatch, capsys):
    story_dir = _write_story(tmp_path)
    files = _files(story_dir)
    seed = _seed_jpeg(os.path.join(str(tmp_path), "seed.jpg"))
    ran = []

    def recorder(name, rc=0):
        def phase(args):
            ran.append(name)
            if name == "phase0_seed":
                args.video_width, args.video_height = 704, 448
            return rc
        return phase

    for name in ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
                 "phase4_render"):
        monkeypatch.setattr(movie, name, recorder(name))
    monkeypatch.setattr(movie, "_check_sudo_and_start_keepalive", lambda: None)
    qe_fake.result = "blocked"
    argv = ["a narrative", "--story-id", "s1", "--panels", "2", "--seed-image", seed, "--seed-edit-model",
            "qwen21-q4", "--no-review", "--story-legacy"]
    capsys.readouterr()
    assert movie.main(argv) == 1
    assert ran == ["phase0_seed", "phase1_story", "phase_release_story_server"]
    assert capsys.readouterr().err == (
        "Error: the content screen blocked the edited seed image (Qwen-Image-2.1 q4) for story s1; the movie stops "
        "here rather than use an unscreened or unedited panel 1. Change panel 1's Image: line in %s, or rerun with "
        "--seed-edit-model as-is to use the seed unchanged\n" % os.path.join(story_dir, "story.md"))
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    assert (record["status"], record["output"], record["error"], record["seconds"]) == ("blocked", None, None, 12.5)
    assert not os.path.exists(files["edited"]) and not os.path.exists(os.path.join(story_dir, ".movie.lock"))
    args = _edit_args(tmp_path)
    qe_fake.result = "Qwen-Image-2.1 q4 child exited 1: boom"
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == "Error: the seed edit failed: Qwen-Image-2.1 q4 child exited 1: boom\n"
    with open(files["record"], encoding="utf-8") as f:
        record = json.load(f)
    assert (record["status"], record["output"], record["error"], record["seconds"]) == (
        "failed", None, "Qwen-Image-2.1 q4 child exited 1: boom", None)
    qe_fake.result = qwen_edit.Unavailable("LoRA Uncensored (abenzerps) is unavailable: gone")
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == ("Error: the seed edit failed: LoRA Uncensored (abenzerps) is unavailable: "
                                       "gone\n")
    assert getattr(args, "seed_edited_path", None) is None
    _write_story(tmp_path, text=STORY_MD.replace("Image: %s\nStyle: %s\n" % (IMAGE, STYLE), ""))
    assert movie.phase_seed_edit(args) == 1
    assert capsys.readouterr().err == ("Error: panel 1 of %s has no Image: description to edit the seed with\n"
                                       % os.path.join(story_dir, "story.md"))


# --- QET30 (QE48 step 4): a rerun reuses an identical edit and redoes a changed one -------------------------

def test_qet30_a_rerun_reuses_an_identical_edit(qe_fake, tmp_path, capsys):
    story_dir = _write_story(tmp_path)
    edited = _files(story_dir)["edited"]
    assert movie.phase_seed_edit(_edit_args(tmp_path)) == 0
    capsys.readouterr()
    args = _edit_args(tmp_path)
    assert movie.phase_seed_edit(args) == 0
    assert len(qe_fake.calls["run_jobs"]) == 1 and args.seed_edited_path == edited
    assert capsys.readouterr().out.splitlines()[-1] == (
        "seed edit: reusing %s (same seed image, prompt, seed and settings)" % edited)

    def runs_after(edit_args):
        before = len(qe_fake.calls["run_jobs"])
        assert movie.phase_seed_edit(edit_args) == 0
        return len(qe_fake.calls["run_jobs"]) - before

    _seed_jpeg(os.path.join(str(tmp_path), "seed.jpg"), color=(200, 0, 0))
    assert runs_after(_edit_args(tmp_path)) == 1
    _write_story(tmp_path, text=STORY_MD.replace("at dusk, wide shot", "at dawn, wide shot"))
    assert runs_after(_edit_args(tmp_path)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8")) == 1
    half = [{"id": "uncensored", "scale": 0.5}]
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8", loras=half)) == 1
    assert runs_after(_edit_args(tmp_path, image_seed=4, model="qwen21-q8", loras=half)) == 0


# --- QET31 (QE50, QEK4): the dry run -----------------------------------------------------------------------------

def _dry(capsys, *extra):
    argv = ["a narrative", "--story-id", "s1", "--panels", "3", "--story-legacy", "--no-review", "--dry-run"]
    assert movie.main(argv + list(extra)) == 0
    return capsys.readouterr().out


def test_qet31_the_dry_run(qe_fake, tmp_path, capsys):
    seed = os.path.join(str(tmp_path), "seed1920.png")
    Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed)
    plain = _dry(capsys, "--seed-image", seed)
    assert _dry(capsys, "--seed-image", seed, "--seed-edit-model", "as-is") == plain
    edited = _dry(capsys, "--seed-image", seed, "--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1")
    files = _files(os.path.join(str(tmp_path), "stories", "s1"))
    lines, plain_lines = edited.splitlines(), plain.splitlines()
    i = lines.index("--- Phase 1c: seed edit ---")
    assert lines[:i] == plain_lines[:i] and plain_lines[i - 1] == "" and plain_lines[i] == "--- Phase 2: stills ---"
    assert lines[i:i + 3] == [
        "--- Phase 1c: seed edit ---",
        "Would edit the seed with %s at 576x320, seed 0, prompted by panel 1's Image: text (and its Style: text) "
        "from story.md; every output is screened with content safety (skill ltx_movie_seed_edit); writes %s, %s "
        "and %s. A blocked or failed edit stops the run." % (qwen_edit.generator_text("qwen21-q4", UNC),
                                                             files["original"], files["edited"], files["record"]),
        ""]
    assert lines[i - 4] == "--- Phase 1b: release the story server ---"
    assert lines[i + 3:] == [line.replace("--seed-image " + seed, "--seed-image " + files["edited"])
                             if "ltx-story-images" in line else line for line in plain_lines[i:]]
    assert [line for line in lines if "ltx-story-images" in line][0].count("--seed-image") == 1
    assert qe_fake.calls["selection_problem"] == [] and qe_fake.calls["run_jobs"] == []


# --- QET32 (QE43 row 6): a workspace without qwen_edit.py --------------------------------------------------------

def test_qet32_a_workspace_without_qwen_edit(qe_fake, tmp_path, monkeypatch, capsys):
    seed = os.path.join(str(tmp_path), "seed1920.png")
    Image.new("RGB", (1920, 1080), (40, 50, 60)).save(seed)
    path = os.path.join(movie.WS, "qwen_edit.py")
    real_isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == path else real_isfile(p))
    argv = ["a narrative", "--story-id", "s1", "--panels", "3", "--story-legacy", "--no-review", "--dry-run",
            "--seed-image", seed]
    assert movie.main(argv + ["--seed-edit-model", "qwen21-q4"]) == 2
    assert capsys.readouterr().err == "Error: --seed-edit-model needs %s, which this workspace does not have\n" % path
    assert movie.main(argv + ["--seed-edit-model", "as-is"]) == 0
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files 2>&1 | tail -3`
Expected: QET26-QET32 fail (`unrecognized arguments: --seed-edit-model`, `AttributeError: ... has no attribute '_qwen_edit'` from the fixture, `phase_seed_edit` missing); QET11 passes.

- [ ] **Step 3: Write the implementation.**

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```text
(bin/lora-catalog), which Phases 2 and 3 apply per panel; --no-auto-lora turns that off.
"""
```

with:

```text
(bin/lora-catalog), which Phases 2 and 3 apply per panel; --no-auto-lora turns that off.

Seed edit (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md): --seed-edit-model ID turns
the --seed-image into panel 1 with a Qwen registry edit model in Phase 1c (after the story, before
the stills), prompted by panel 1's Image: text; the edit is screened, recorded in seed_edit.json and
passed to Phase 2 as its --seed-image. Absent, or as-is, the seed is used unchanged.
"""
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
SEED_MIN_EDGE = 64
```

with:

```python
SEED_MIN_EDGE = 64
# Phase 1c, the seed edit (docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, QE45).
SEED_EDIT_SKILL = "ltx_movie_seed_edit"
SEED_EDIT_SCHEMA = "ltx-movie.seed-edit.v1"
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
                              "with --no-stills and with --video-width/--video-height.")
```

with:

```python
                              "with --no-stills and with --video-width/--video-height.")
    parser.add_argument("--seed-edit-model", dest="seed_edit_model", default=None, metavar="ID|as-is",
                         help="with --seed-image: edit the seed into panel 1 with a Qwen registry edit model "
                              "(qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's "
                              "Image: text after Phase 1 and screened with content safety; as-is, like leaving the "
                              "flag out, uses the seed unchanged. See docs/superpowers/specs/"
                              "2026-11-03-qwen-edit-models-design.md.")
    parser.add_argument("--seed-edit-lora", dest="seed_edit_loras", action="append", default=None,
                         metavar="ID=SCALE",
                         help="with --seed-edit-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _ltx2_skill():
```

with:

```python
def _qwen_edit():
    """qwen_edit.py (qwen edit models spec QE41), loaded by path and only when --seed-edit-model names a
    registry model, so a run without it, a dry run without it and the deploy package never read it."""
    return importlib.machinery.SourceFileLoader("qwen_edit", os.path.join(WS, "qwen_edit.py")).load_module()


def _ltx2_skill():
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    args.location_pins = pins
    args.location_strength = strength
    return 0


def _check_story_locations(args, names):
```

with:

```python
    args.location_pins = pins
    args.location_strength = strength
    return 0


def _resolve_seed_edit(args):
    """--seed-edit-model/--seed-edit-lora (qwen edit models spec QE43): sets args.seed_edit to None (the seed
    as-is) or {"qwen_model": ID, "loras": [{"id", "scale"}]}. Returns 0, or 2 after one Error: line. A dry
    run and --story-only read no weights; otherwise the selection must be installed and fit this host
    before the lockfile and any phase."""
    model, loras = args.seed_edit_model, args.seed_edit_loras
    args.seed_edit = None
    if model is None:
        if loras is not None:
            print("Error: --seed-edit-lora needs --seed-edit-model", file=sys.stderr)
            return 2
        return 0
    if not getattr(args, "seed_image", None):
        print("Error: --seed-edit-model needs --seed-image", file=sys.stderr)
        return 2
    if model == "as-is":
        if loras is not None:
            print("Error: --seed-edit-lora cannot be combined with --seed-edit-model as-is", file=sys.stderr)
            return 2
        return 0
    path = os.path.join(WS, "qwen_edit.py")
    if not os.path.isfile(path):
        print("Error: --seed-edit-model needs %s, which this workspace does not have" % path, file=sys.stderr)
        return 2
    qe = _qwen_edit()
    if model not in qe.MODEL_IDS:
        print("Error: --seed-edit-model must be as-is or one of %s" % ", ".join(qe.MODEL_IDS), file=sys.stderr)
        return 2
    try:
        model_id, clean = qe.cli_selection(model, loras, "--seed-edit-model", "--seed-edit-lora")
    except qe.SelectionError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    if not args.dry_run and not args.story_only:
        problem = qe.selection_problem(model_id, clean)
        if problem is not None:
            print("Error: --seed-edit-model %s: %s" % (model_id, problem), file=sys.stderr)
            return 2
    args.seed_edit = {"qwen_model": model_id, "loras": clean}
    return 0


def _check_story_locations(args, names):
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        return 1
    return 0


def _redo_moves(args, archive):
```

with:

```python
        return 1
    return 0


def _seed_edit_paths(story_dir):
    """Phase 1c's files in the story directory (qwen edit models spec QE45)."""
    return {"original": os.path.join(story_dir, "seed-original.png"),
            "edited": os.path.join(story_dir, "seed-edited.png"),
            "record": os.path.join(story_dir, "seed_edit.json"),
            "work": os.path.join(story_dir, "seed_edit_work"),
            "stage": os.path.join(story_dir, "seed_edit_work", "seed-edited.pending.png")}


def _panel1_edit_prompt(story_md):
    """Panel 1's Image: text plus the story's Style: text, joined as bin/ltx-story-images joins them, or ""."""
    panels = _load_story_panels(story_md)
    if not panels:
        return ""
    images = importlib.machinery.SourceFileLoader(
        "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
    return images._compose_prompt(panels[0]["image"], images._style_text(panels))


def _seed_edit_size(args, multiple):
    """Phase 1c's edit size (qwen edit models spec QE47): the video size floored to the model's multiple."""
    return (args.video_width // multiple * multiple, args.video_height // multiple * multiple)


def _write_seed_edit_record(path, record):
    """seed_edit.json, written atomically (<path>.tmp, then os.replace)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, path)


def phase_seed_edit(args):
    """Phase 1c (qwen edit models spec QE48): edit the --seed-image into panel 1 with the Qwen registry model
    of --seed-edit-model, prompted by panel 1's Image: (and Style:) text, screened with content safety, and
    recorded in seed_edit.json; on success Phase 2 gets the edited image as its --seed-image. A rerun with
    the same seed bytes, prompt, seed, size and settings reuses an ok edit. Returns 0 or 1; a blocked or
    failed edit stops the movie (no fallback to the unedited seed)."""
    import hashlib
    qe = _qwen_edit()
    paths = _story_paths(args.story_id)
    files = _seed_edit_paths(paths["story_dir"])
    model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
    label = qe.label(model_id)
    print("=== Phase 1c: seed edit ===")
    prompt = _panel1_edit_prompt(paths["story_md"])
    if not prompt:
        print("Error: panel 1 of %s has no Image: description to edit the seed with" % paths["story_md"],
              file=sys.stderr)
        return 1
    width, height = _seed_edit_size(args, qe.multiple(model_id))
    with open(args.seed_image, "rb") as f:
        source_sha256 = hashlib.sha256(f.read()).hexdigest()
    key = dict(qe.settings(model_id, loras), source_sha256=source_sha256, prompt=prompt,
               seed=args.image_seed, width=width, height=height)
    try:
        with open(files["record"], encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    if (isinstance(old, dict) and old.get("status") == "ok" and os.path.isfile(files["edited"])
            and all(k in old and old[k] == v for k, v in key.items())):
        print("seed edit: reusing %s (same seed image, prompt, seed and settings)" % files["edited"])
        args.seed_edited_path = files["edited"]
        return 0
    _image_fit().load_oriented_rgb(args.seed_image).save(files["original"], format="PNG")
    for path in (files["edited"], files["stage"]):
        if os.path.exists(path):
            os.remove(path)
    print("seed edit: %s; %dx%d; seed %d; prompt: panel 1's Image: text (%d characters)"
          % (qe.generator_text(model_id, loras), width, height, args.image_seed, len(prompt)))
    job = {"n": 1, "seed": args.image_seed, "prompt": prompt, "source": files["original"],
           "stage_path": files["stage"], "output_path": files["edited"]}
    try:
        qe.wait_for_memory(qe.memory_floor(model_id), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, [job], width, height, SEED_EDIT_SKILL, files["work"])
    except qe.Unavailable as e:
        results, failure = None, str(e)
    result = results[0] if results else None
    status = "failed" if failure is not None or result is None else result["status"]
    settings = qe.settings(model_id, loras)
    _write_seed_edit_record(files["record"], {
        "schema": SEED_EDIT_SCHEMA, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status, "label": label, "source": os.path.abspath(args.seed_image),
        "source_sha256": source_sha256, "original": os.path.basename(files["original"]),
        "output": os.path.basename(files["edited"]) if status == "ok" else None, "prompt": prompt,
        "seed": args.image_seed, "width": width, "height": height, "qwen_model": settings["qwen_model"],
        "loras": settings["loras"], "steps": settings["steps"], "scheduler": settings["scheduler"],
        "seconds": result["seconds"] if result is not None else None, "error": failure})
    if failure is not None:
        print("Error: the seed edit failed: %s" % failure, file=sys.stderr)
        return 1
    if status == "blocked":
        print("Error: the content screen blocked the edited seed image (%s) for story %s; the movie stops here "
              "rather than use an unscreened or unedited panel 1. Change panel 1's Image: line in %s, or rerun "
              "with --seed-edit-model as-is to use the seed unchanged" % (label, args.story_id, paths["story_md"]),
              file=sys.stderr)
        return 1
    args.seed_edited_path = files["edited"]
    print("seed edit: %s (%.1f s)" % (files["edited"], result["seconds"]))
    return 0


def _redo_moves(args, archive):
```

Edit `bin/ltx-movie` (ruling R2): replace this text, which occurs exactly once:

```python
    if getattr(args, "seed_image", None):
        cmd += ["--seed-image", args.seed_image]
```

with:

```python
    if getattr(args, "seed_image", None):
        cmd += ["--seed-image", args.seed_image]
        if getattr(args, "seed_edited_path", None):
            cmd[-1] = args.seed_edited_path            # QE49: Phase 1c's screened edit is panel 1's seed
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        print("Then only those panels' stills and clips re-render; every other panel is reused.")
        print()
```

with:

```python
        print("Then only those panels' stills and clips re-render; every other panel is reused.")
        print()

    if getattr(args, "seed_edit", None):
        qe = _qwen_edit()
        model_id, loras = args.seed_edit["qwen_model"], args.seed_edit["loras"]
        files = _seed_edit_paths(paths["story_dir"])
        size = ("%dx%d" % _seed_edit_size(args, qe.multiple(model_id)) if isinstance(args.video_width, int)
                else "<W>x<H>")
        print("--- Phase 1c: seed edit ---")
        print("Would edit the seed with %s at %s, seed %d, prompted by panel 1's Image: text (and its Style: "
              "text) from story.md; every output is screened with content safety (skill %s); writes %s, %s "
              "and %s. A blocked or failed edit stops the run."
              % (qe.generator_text(model_id, loras), size, args.image_seed, SEED_EDIT_SKILL,
                 files["original"], files["edited"], files["record"]))
        print()
```

Edit `bin/ltx-movie` (ruling R2): replace this text, which occurs exactly once:

```python
        if getattr(args, "seed_image", None):
            phase2_cmd += ["--seed-image", args.seed_image]
```

with:

```python
        if getattr(args, "seed_image", None):
            phase2_cmd += ["--seed-image", args.seed_image]
            if getattr(args, "seed_edit", None):
                phase2_cmd[-1] = _seed_edit_paths(paths["story_dir"])["edited"]
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]
```

with:

```python
        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]
    if getattr(args, "seed_edit", None) and phase2_stills in phases:
        cut = phases.index(phase2_stills)
        phases = phases[:cut] + (phase_seed_edit,) + phases[cut:]
```

Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    rc = _resolve_locations(args)
    if rc:
        return rc
```

with:

```python
    rc = _resolve_locations(args)
    if rc:
        return rc
    rc = _resolve_seed_edit(args)
    if rc:
        return rc
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py tests/test_dialogue.py::test_dk3_import_sets_are_unchanged tests/test_movie_ui_builder.py 2>&1 | tail -1 && python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1`
Expected: only `test_mut26_pipeline_files_are_unchanged` fails (expected), every other test passes; `OK 347/347`.

Run the compile check with `FILES` = `bin/ltx-movie tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py`. Expected: `compiled 4` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=5`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 40, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`; the 7 new tests are QET26-QET32), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add bin/ltx-movie tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly those four paths
git commit -m "ltx-movie: --seed-edit-model and Phase 1c, a screened Qwen edit of the seed into panel 1 (qwen edit models QE40-QE50, QET26-QET32)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: movie-ui: fields, V1 rule 12d, the 400/409 rules and argv forwarding for Compose, Locations and Characters, the batch levels (QE51-QE60, QE69; QET33-QET37, Review Focus 4 and 5)

This task implements:
- `movie_ui_seedgen.py` (QE51): `qwen_selection(model_id, loras, model_key="qwen_model", loras_key="loras")`; `_qwen_fields` calls it for qwen (same results and texts; SQT15 holds).
- `movie_ui_lib.py` (QE52-QE54, QE69): `DEFAULT_FIELDS`' two keys, `FIELD_FLAGS`' 31st entry, `qwen_edit_flags`, `build_argv`/`location_argv`/`character_argv` forwarding, `SEED_EDIT_ID_RE` and `_rule_seed_edit` (V1 rule 12d, after 12c), `PHASE_RE` `\d+[bc]?`, `job_phases`' `1c`.
- `movie_ui_server.py` (QE55-QE59): `_edit_given`, `edit_availability`; `_fields_body`'s 400; the Compose 409 in `_h_job_create` and `_h_seed_folder`; `location_create_errors`, `_h_location_create`, `_h_location_regenerate` (R11); `character_create_errors`, `_h_character_create`, `_h_character_seed_folder`, `_h_character_regenerate`.
- `movie_ui_batch.py` (QE60): `FIELD_LEVELS`, `GROUPS`, `merge`.
- Tests: the new `tests/test_movie_ui_qwen_edit.py` (QET33-QET37, Review Focus 4, 5); §11.3's count edits in `tests/test_location_ui.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_batch.py`; ruling R15's help fixture, `test_mut3` and `test_mu14` edits; `NEW_PY` gains the new file and QET11 grows (R6).

**Files:**
- Modify: `movie_ui_seedgen.py` (`_qwen_fields` `:124-157`), `movie_ui_lib.py` (`DEFAULT_FIELDS` `:942-955`, `FIELD_FLAGS` `:960-974`, `action_arg` `:1009-1013`, `build_argv` `:1027-1028`, `_rule_locations` end `:1116-1117`, `location_argv` `:1132-1147`, `character_argv` `:1172-1196`, `validate_fields` `:1534`, `PHASE_RE` `:2215`, `job_phases` `:2248-2256`), `movie_ui_server.py` (`_fields_body` `:759-762`, `_h_job_create` `:826-833`, `_h_seed_folder` `:926-954`, `character_create_errors` `:1419-1451`, `_h_character_create` `:1469-1481`, `_h_character_seed_folder` `:1537-1568`, `_h_character_regenerate` `:1571-1577`, `location_create_errors` `:1969-1998`, `_h_location_create` `:2053-2061`, `_h_location_regenerate` `:2082-2099`), `movie_ui_batch.py` (`GROUPS` `:34`, `FIELD_LEVELS` `:38-45`, `merge` `:194-212`).
- Create: `tests/test_movie_ui_qwen_edit.py`.
- Modify (tests): `tests/test_location_ui.py` (`:267`), `tests/test_movie_ui_builder.py` (`:128-130`, `:137`, `NEW_PY`), `tests/test_movie_ui_batch.py` (`EXPECTED_LEVELS`, `:78`), `tests/test_movie_ui_http.py` (`:225`), `tests/test_qwen_edit.py` (QET11), `tests/fixtures/movie_ui/ltx-movie-help-current.txt` (R15).

**Interfaces:**
- Consumes (Task 1-5): nothing at import time (QE2: no `qwen_edit` import); the argv targets `bin/ltx-movie --seed-edit-model/--seed-edit-lora`, `bin/location create --qwen-model/--lora`, `bin/character create --qwen-model/--lora`. Existing: `lib.seed_edit_check(ws_real, model_ids, lora_ids) -> (models, detail)`, `seedgen.availability_error(models, detail, clean)`, `seedgen.QWEN_MODEL_IDS`, `seedgen.QWEN_LORA_IDS`, `lib.read_json(path, default=None)`.
- Produces (Task 7's page sends these):
  - `seedgen.qwen_selection(model_id, loras, model_key="qwen_model", loras_key="loras") -> (model_id, loras, None)` or `(None, None, text)`;
  - `lib.DEFAULT_FIELDS["seed_edit_model"] = None`, `lib.DEFAULT_FIELDS["seed_edit_loras"] = None`; `lib.FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))`, so `/api/options`' `supported.seed_edit` gates the page's `[data-field="seed_edit"]`;
  - `lib.qwen_edit_flags(model_flag, lora_flag, model_id, loras) -> list`; `lib._rule_seed_edit(fields) -> [text]`; `lib.SEED_EDIT_ID_RE`;
  - request fields: Compose `seed_edit_model` (`null`, `"as-is"` or a registry ID) and `seed_edit_loras` (`null` or `[{"id", "scale"}]`); Locations and Characters `qwen_model` and `loras` (absent/`null`: no flag); job `fields` gain the cleaned values only when a selection was named (QE56);
  - `srv.edit_availability(real, model_id, loras) -> None or the 409 text`; `srv._edit_given(body) -> bool`.

- [ ] **Step 1: Write the failing tests and the §11.3 edits.**

Edit `tests/fixtures/movie_ui/ltx-movie-help-current.txt` (ruling R15): replace this text, which occurs exactly once:

```text
usage: ltx-movie [-h] --story-id STORY_ID [--seed-image SEED_IMAGE]
                 [--panels PANELS] [--length LENGTH] [--fps FPS]
```

with:

```text
usage: ltx-movie [-h] --story-id STORY_ID [--seed-image SEED_IMAGE]
                 [--seed-edit-model ID|as-is] [--seed-edit-lora ID=SCALE]
                 [--panels PANELS] [--length LENGTH] [--fps FPS]
```

Edit `tests/fixtures/movie_ui/ltx-movie-help-current.txt`: replace this text, which occurs exactly once:

```text
                        downscale keeps more real detail. Incompatible with
                        --no-stills and with --video-width/--video-height.
```

with:

```text
                        downscale keeps more real detail. Incompatible with
                        --no-stills and with --video-width/--video-height.
  --seed-edit-model ID|as-is
                        with --seed-image: edit the seed into panel 1 with a
                        Qwen registry edit model (qwen21-q4, qwen21-q8,
                        qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by
                        panel 1's Image: text after Phase 1 and screened with
                        content safety; as-is, like leaving the flag out, uses
                        the seed unchanged. See docs/superpowers/specs/2026-11-
                        03-qwen-edit-models-design.md.
  --seed-edit-lora ID=SCALE
                        with --seed-edit-model ID: a registry LoRA of that
                        model's family, 0 < SCALE <= 2 (repeatable); none
                        listed means no LoRA
```

Edit `tests/test_movie_ui_builder.py` (ruling R15): replace this text, which occurs exactly once:

```python
    assert current - old == {"--story-only", "--story-legacy", "--no-auto-lora", "--judge", "--goal", "--gemma",
                             "--no-narration", "--speech-only", "--action", "--location",
                             "--location-strength"}
```

with:

```python
    assert current - old == {"--story-only", "--story-legacy", "--no-auto-lora", "--judge", "--goal", "--gemma",
                             "--no-narration", "--speech-only", "--action", "--location",
                             "--location-strength", "--seed-edit-model", "--seed-edit-lora"}
```

Edit `tests/test_movie_ui_http.py` (ruling R15): replace this text, which occurs exactly once:

```python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 30
```

with:

```python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 31
```

Edit `tests/test_location_ui.py`: replace this text, which occurs exactly once:

```python
    assert len(lib.FIELD_FLAGS) == 30
```

with:

```python
    assert len(lib.FIELD_FLAGS) == 31
```

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 30
```

with:

```python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 31
```

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
          "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py")
```

with:

```python
          "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py",
          "tests/test_movie_ui_qwen_edit.py")
```

Edit `tests/test_qwen_edit.py`: replace this text, which occurs exactly once:

```python
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py"]
```

with:

```python
        "qwen_edit.py", "tests/test_qwen_edit.py", "tests/test_ltx_movie_seed_edit.py",
        "tests/test_movie_ui_qwen_edit.py"]
```

Edit `tests/test_movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
```

with:

```python
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "seed_edit_model": "stills", "seed_edit_loras": "stills",
```

Edit `tests/test_movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (25, 5, 30)
```

with:

```python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (27, 5, 32)
```

Write `tests/test_movie_ui_qwen_edit.py` with exactly this content (the Write tool):

```python
"""Tests for the movie-ui side of the Qwen edit models (docs/superpowers/specs/2026-11-03-qwen-edit-models-
design.md, Sections 8 and 9, test table 11.2: QET33-QET39, with the plan's Review Focus pins 4 and 5):
movie_ui_lib's fields, flags, argv, V1 rule 12d and phases; the server's 400/409 rules and forwarding for
Compose, Locations and Characters; the batch levels; and the static page.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py

Rules (spec 11.1): the HTTP tests use the in-test server and the stub workspace of tests/movie_ui_testutil.py
under a temporary HOME (the env fixture). lib.seed_edit_check is a recorder that answers in seed models SQ18's
shape (every model and LoRA ok unless a test says otherwise) and lib.shared_checks a pass stub (one V2
record); the stub bin/ltx-movie --help prints the current help fixture, which lists the two seed-edit flags
(V1 rule 18; plan ruling R15). No test uses the real HOME,
renders, dispatches a job or contacts a server other than the in-test 127.0.0.1 one; none touches port 8177
or 8178. Stdlib plus pytest.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import qwen_edit

WS = mt.WS
UP = "a" * 64 + ".png"
PASS_V2 = lib.check("V2", "render", "pass", "stub")
DESC = ("a narrow cobbled harbour street lined with weathered stone warehouses, green wooden "
        "shutters, rusted mooring rings and faded red fishmonger signs above granite quays")
SEL = {"qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 0.5}]}
PHOTO_ONLY = "qwen_model and loras apply only to photo locations"
SEED_ONLY = "qwen_model and loras apply only to seed-image characters"


def _probe(models=None, loras=None):
    """lib.seed_edit_check's models answer: every registry model and LoRA ok unless given."""
    found_models = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_MODEL_IDS)
    found_models.update(models or {})
    found_loras = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_LORA_IDS)
    found_loras.update(loras or {})
    return {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
            "qwen": {"ok": True, "reason": None, "models": found_models, "loras": found_loras}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.setenv("LOCATION_LIBRARY_DIR", str(tmp_path / "locations"))
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(tmp_path / "characters"))
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    monkeypatch.setattr(lib, "shared_checks", lambda fields, ws_real, py=None: [PASS_V2])
    probes = {"answer": (_probe(), None), "calls": []}

    def seed_edit_check(ws_real, model_ids, lora_ids):
        probes["calls"].append(ws_real)
        return probes["answer"]

    monkeypatch.setattr(lib, "seed_edit_check", seed_edit_check)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "probes": probes,
           "locations": str(tmp_path / "locations"), "characters": str(tmp_path / "characters")}
    running.close()
    mt.kill_everything(state)


def _upload(s, data=mt.PNG):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=data, headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _job(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))


def _compose(ws, up, **overrides):
    body = mt.fields(ws, seed_upload=up, action="movie")
    body.update(overrides)
    return body


def _record(root, name, file_name, record):
    os.makedirs(os.path.join(root, name), exist_ok=True)
    with open(os.path.join(root, name, file_name), "w", encoding="utf-8") as f:
        json.dump(record, f)


# --- QET33 (QE52-QE54, QE69): fields, flags, argv, V1 rule 12d and the phases --------------------------------

def test_qet33_fields_flags_argv_rule_12d_and_phases(tmp_path, monkeypatch):
    state = mt.set_home(monkeypatch, tmp_path)
    keys = list(lib.DEFAULT_FIELDS)
    assert keys[keys.index("seed_upload") + 1:keys.index("seed_upload") + 3] == ["seed_edit_model", "seed_edit_loras"]
    assert (lib.DEFAULT_FIELDS["seed_edit_model"], lib.DEFAULT_FIELDS["seed_edit_loras"]) == (None, None)
    assert lib.FIELD_FLAGS[-1] == ("seed_edit", ("--seed-edit-model", "--seed-edit-lora"))
    assert len(lib.FIELD_FLAGS) == 31
    seed_path = os.path.join(state, "uploads", UP)
    base = mt.fields(WS, seed_upload=UP, action="movie")
    argv = lib.build_argv(dict(base, seed_edit_model="qwen21-q4", seed_edit_loras=[{"id": "uncensored", "scale": 1}]),
                          WS, state)
    i = argv.index("--seed-image")
    assert argv[i - 4:i + 7] == ["--fps", "24", "--frames", "145", "--seed-image", seed_path, "--seed-edit-model",
                                 "qwen21-q4", "--seed-edit-lora", "uncensored=1.0", "--model"]
    argv = lib.build_argv(dict(base, seed_edit_model="as-is"), WS, state)
    i = argv.index("--seed-image")
    assert argv[i + 2:i + 5] == ["--seed-edit-model", "as-is", "--model"]
    assert "--seed-edit-model" not in lib.build_argv(base, WS, state)
    assert "--seed-edit-model" not in lib.build_argv(dict(base, seed_upload=None, width=704, height=448,
                                                          seed_edit_model="qwen21-q4"), WS, state)
    assert lib.qwen_edit_flags("--qwen-model", "--lora", "qwen21-q8", [{"id": "uncensored", "scale": 0.5},
                                                                     {"id": "viggle-turbo", "scale": 2}]) == [
        "--qwen-model", "qwen21-q8", "--lora", "uncensored=0.5", "--lora", "viggle-turbo=2.0"]
    py = sys.executable
    loc = {"name": "old-mill", "photo_uploads": [UP], "seed": 3, "force": True, "qwen_model": "qwen21-q4",
           "loras": [{"id": "uncensored", "scale": 0.5}]}
    assert lib.location_argv("location-create", loc, WS, state, py=py)[2:] == [
        "create", "old-mill", "--photo", seed_path, "--seed", "3", "--qwen-model", "qwen21-q4", "--lora",
        "uncensored=0.5", "--force"]
    old = dict((k, v) for k, v in loc.items() if k not in ("qwen_model", "loras"))
    assert lib.location_argv("location-create", old, WS, state, py=py)[2:] == [
        "create", "old-mill", "--photo", seed_path, "--seed", "3", "--force"]
    regen = {"name": "old-mill", "seed": None, "new_seed": True, "description": None, "force": True,
             "qwen_model": "qwen2511-bf16", "loras": []}
    assert lib.location_argv("location-regenerate", regen, WS, state, py=py)[2:] == [
        "create", "old-mill", "--regenerate", "--new-seed", "--qwen-model", "qwen2511-bf16", "--force"]
    char = {"name": "kyra", "phrase": "the woman", "seed_upload": UP, "class_noun": None, "trigger": None, "seed": 7,
            "force": False, "qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1.0}]}
    assert lib.character_argv("character-create", char, WS, state, py=py)[2:] == [
        "create", "kyra", "--phrase", "the woman", "--seed-image", seed_path, "--seed", "7", "--qwen-model",
        "qwen21-q4", "--lora", "uncensored=1.0", "--no-review"]
    assert lib.character_argv("character-regenerate", {"name": "kyra", "seed": 4, "qwen_model": "qwen21-q8",
                                                       "loras": []}, WS, state, py=py)[2:] == [
        "create", "kyra", "--regenerate", "--no-review", "--seed", "4", "--qwen-model", "qwen21-q8"]
    assert lib.character_argv("character-regenerate", {"name": "kyra", "seed": None}, WS, state, py=py)[2:] == [
        "create", "kyra", "--regenerate", "--no-review"]
    rule = lib._rule_seed_edit
    ok = {"seed_upload": UP, "seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1}]}
    assert rule(ok) == [] and rule({"seed_upload": None, "seed_edit_model": None, "seed_edit_loras": None}) == []
    assert rule(dict(ok, seed_edit_model="as-is", seed_edit_loras=None)) == []
    model_text = "seed edit model must be as-is or a Qwen model ID"
    loras_text = "seed edit LoRAs must be a list of at most 4 {id, scale} items"
    for model in ("Bad ID", 5, "-x", "a" * 33):
        assert rule(dict(ok, seed_edit_model=model)) == [model_text], model
    for loras in ("uncensored", [{"id": "uncensored"}], [{"id": "uncensored", "scale": "1"}],
                  [{"id": "Uncensored", "scale": 1}], [{"id": "uncensored", "scale": 1}] * 5):
        assert rule(dict(ok, seed_edit_loras=loras)) == [loras_text], loras
    assert rule(dict(ok, seed_upload=None, seed_edit_loras=None)) == ["a seed edit model needs a seed image"]
    assert rule(dict(ok, seed_edit_model="as-is", seed_edit_loras=[])) == [
        "seed edit LoRAs need a seed edit model other than as-is"]
    assert rule(dict(ok, seed_edit_model=None, seed_edit_loras=[])) == [
        "seed edit LoRAs need a seed edit model other than as-is"]
    movie = {"action": "movie", "mode": "chained", "seed_upload": UP}
    assert lib.job_phases("movie", dict(movie, seed_edit_model="qwen21-q4")) == ["0", "1", "1b", "1c", "2", "3", "4"]
    for model in (None, "as-is"):
        assert lib.job_phases("movie", dict(movie, seed_edit_model=model)) == ["0", "1", "1b", "2", "3", "4"]
    assert lib.job_phases("movie", dict(movie, seed_upload=None, seed_edit_model="qwen21-q4")) == [
        "1", "1b", "2", "3", "4"]
    assert lib.job_phases("story", dict(movie, seed_edit_model="qwen21-q4")) == ["0", "1"]
    found = lib.PHASE_RE.match("=== Phase 1c: seed edit ===")
    assert found and (found.group(1), found.group(2)) == ("1c", "seed edit")
    assert lib.PHASE_RE.match("=== Phase 1b: release the story server ===").group(1) == "1b"
    assert seedgen.qwen_selection(None, None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}], None)
    assert seedgen.qwen_selection("qwen21-q4", []) == ("qwen21-q4", [], None)
    assert seedgen.qwen_selection("flux", None, "seed_edit_model", "seed_edit_loras") == (
        None, None, "unknown seed_edit_model flux")
    assert seedgen.qwen_selection("qwen21-q4", "x", "seed_edit_model", "seed_edit_loras") == (
        None, None, "seed_edit_loras must be a list of {id, scale}")


# --- QET34 (QE56, QE57): Compose over HTTP ----------------------------------------------------------------------

def test_qet34_compose_rules_and_forwarding(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    up = _upload(s)
    q8 = ("mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in /z or /h "
          "(run bin/seed-edit-setup --model qwen21-q8)")
    cases = [({"seed_edit_model": "flux"}, "unknown seed_edit_model flux"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": "uncensored"},
              "seed_edit_loras must be a list of {id, scale}"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored"}]},
              "seed_edit_loras must be a list of {id, scale}"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "nope", "scale": 1}]}, "unknown LoRA nope"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1},
                                                                    {"id": "uncensored", "scale": 2}]},
              "LoRA uncensored is listed twice"),
             ({"seed_edit_model": "qwen2511-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1}]},
              "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 q4 (Lightning)"),
             ({"seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 0}]},
              "LoRA uncensored scale must be a number above 0 and at most 2")]
    for overrides, text in cases:
        for path in ("/api/preview", "/api/jobs"):
            status, _h, payload = mt.api(s, "POST", path, body=_compose(ws, up, **overrides))
            assert (status, payload) == (400, {"error": text}), (path, overrides)
    assert lib.list_job_ids(state) == [] and probes["calls"] == []
    status, _h, payload = mt.api(s, "POST", "/api/preview", body=_compose(ws, None, seed_edit_model="qwen21-q4"))
    assert status == 200 and "a seed edit model needs a seed image" in payload["errors"]
    for story_id, model in (("plain-seed", None), ("as-is-seed", "as-is")):
        status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id=story_id,
                                                                           seed_edit_model=model))
        assert status == 201, payload
        argv = _job(state, payload)["argv"]
        assert ("--seed-edit-model" in argv) == (model is not None)
        if model is not None:
            assert argv[argv.index("--seed-edit-model") + 1] == "as-is"
    assert probes["calls"] == []
    probes["answer"] = (_probe(models={"qwen21-q8": {"ok": False, "reason": q8}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id="q8-seed",
                                                                       seed_edit_model="qwen21-q8"))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8)
    assert len(lib.list_job_ids(state)) == 2 and probes["calls"] == [ws]
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(ws, up, story_id="story-seed", action="story",
                                                                       seed_edit_model="qwen21-q8"))
    assert status == 201 and len(probes["calls"]) == 1
    status, _h, payload = mt.api(s, "POST", "/api/jobs", body=_compose(
        ws, up, story_id="q4-seed", seed_edit_model="qwen21-q4", seed_edit_loras=[{"id": "uncensored", "scale": 1}]))
    assert status == 201 and len(probes["calls"]) == 2
    job = _job(state, payload)
    assert (job["fields"]["seed_edit_model"], job["fields"]["seed_edit_loras"]) == (
        "qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    i = job["argv"].index("--seed-edit-model")
    assert job["argv"][i:i + 4] == ["--seed-edit-model", "qwen21-q4", "--seed-edit-lora", "uncensored=1.0"]
    assert job["argv"][i - 2] == "--seed-image"
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = dict(mt.fields(ws, story_id="", action="movie", seed_edit_model="qwen21-q8"), seeds=seeds, preview=True)
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=folder)
    assert status == 200 and len(probes["calls"]) == 2, payload
    jobs = len(lib.list_job_ids(state))
    status, _h, payload = mt.api(s, "POST", "/api/jobs/seed-folder", body=dict(folder, preview=False))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q8 is unavailable: " + q8)
    assert len(probes["calls"]) == 3 and len(lib.list_job_ids(state)) == jobs


# --- QET35 (QE58): Locations over HTTP ---------------------------------------------------------------------------

def test_qet35_locations(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    one, two = _upload(s, mt.PNG + b"1"), _upload(s, mt.PNG + b"2")
    body = {"ws": ws, "name": "old-mill", "photo_uploads": [one, two]}
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=body)
    assert status == 201 and probes["calls"] == []
    job = _job(state, payload)
    assert job["argv"][2:] == ["create", "old-mill", "--photo", os.path.join(state, "uploads", one), "--photo",
                               os.path.join(state, "uploads", two)]
    assert "qwen_model" not in job["fields"] and "loras" not in job["fields"]
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="dock-one", **SEL))
    assert status == 201 and probes["calls"] == [ws]
    job = _job(state, payload)
    assert job["argv"][-4:] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=0.5"]
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 0.5}])
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict({"ws": ws, "name": "harbour-street",
                                                                         "description": DESC}, **SEL))
    assert (status, payload["errors"]) == (400, [PHOTO_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="bad-one", qwen_model="flux"))
    assert (status, payload["errors"]) == (400, ["unknown qwen_model flux"])
    probes["answer"] = (_probe(loras={"uncensored": {"ok": False, "reason": "gone"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations", body=dict(body, name="no-lora", **SEL))
    assert (status, payload["error"]) == (409, "LoRA Uncensored (abenzerps) is unavailable: gone")
    probes["answer"] = (_probe(), None)
    _record(env["locations"], "harbour-street", "location.json", {"source": "text", "photos": []})
    _record(env["locations"], "old-mill", "location.json",
            {"source": "photos", "photos": [{"path": None, "sha256": "0" * 64}] * 2})
    status, _h, payload = mt.api(s, "POST", "/api/locations/harbour-street/regenerate",
                                 body=dict({"ws": ws, "new_seed": True}, **SEL))
    assert (status, payload["errors"]) == (400, [PHOTO_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate",
                                 body=dict({"ws": ws, "new_seed": True}, **SEL))
    assert status == 201
    assert _job(state, payload)["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed", "--qwen-model",
                                                "qwen21-q4", "--lora", "uncensored=0.5"]
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body={"ws": ws, "new_seed": True})
    assert status == 201 and _job(state, payload)["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed"]
    probes["answer"] = (_probe(models={"qwen21-q4": {"ok": False, "reason": "not here"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=dict({"ws": ws}, **SEL))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q4 is unavailable: not here")


# --- QET36 (QE59): Characters over HTTP --------------------------------------------------------------------------

def test_qet36_characters(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    sel = {"qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1}]}
    base = {"ws": ws, "name": "kyra", "phrase": "the woman in grey", "seed_upload": _upload(s)}
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(base, **sel))
    assert status == 201 and probes["calls"] == [ws]
    job = _job(state, payload)
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}])
    assert job["argv"][-5:] == ["--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0", "--no-review"]
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(
        {"ws": ws, "name": "ronin", "phrase": "the ronin", "descriptor": "a lean man with a topknot",
         "class_noun": "man"}, **sel))
    assert (status, payload["errors"]) == (400, [SEED_ONLY])
    probes["answer"] = (_probe(models={"qwen21-q4": {"ok": False, "reason": "not here"}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/characters", body=dict(base, name="kyra-two", **sel))
    assert (status, payload["error"]) == (409, "Qwen-Image-2.1 q4 is unavailable: not here")
    probes["answer"] = (_probe(), None)
    seeds = [{"name": "alpha.png", "upload_id": _upload(s, mt.PNG + b"a")},
             {"name": "beta.png", "upload_id": _upload(s, mt.PNG + b"b")}]
    folder = {"ws": ws, "name": "", "phrase": "the stranger", "seed": 7, "seeds": seeds, "preview": False}
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, qwen_model="qwen21-q8",
                                                                                     loras=[]))
    assert status == 201 and payload["queued"] == 2, payload
    for row in payload["seeds"]:
        job = lib.read_job(lib.job_dir(state, row["job"]["id"]))
        assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen21-q8", [])
        assert job["argv"][-3:] == ["--qwen-model", "qwen21-q8", "--no-review"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, qwen_model="flux"))
    assert (status, payload) == (400, {"error": "unknown qwen_model flux"})
    status, _h, payload = mt.api(s, "POST", "/api/characters/seed-folder", body=dict(folder, phrase="the walker"))
    assert status == 201 and payload["queued"] == 2
    for row in payload["seeds"]:
        fields = lib.read_job(lib.job_dir(state, row["job"]["id"]))["fields"]
        assert set(fields) == {"name", "phrase", "class_noun", "descriptor", "trigger", "seed", "seed_upload",
                               "force", "ws", "seed_folder"}
    _record(env["characters"], "ronin", "character.json", {"name": "ronin", "source": {"type": "descriptor"}})
    _record(env["characters"], "kyra", "character.json",
            {"name": "kyra", "source": {"type": "seed_image", "path": "/x/seed.png"}})
    status, _h, payload = mt.api(s, "POST", "/api/characters/ronin/regenerate", body=dict({"ws": ws}, **sel))
    assert (status, payload["errors"]) == (400, [SEED_ONLY])
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body=dict({"ws": ws, "seed": 4}, **sel))
    assert status == 201
    assert _job(state, payload)["argv"][2:] == ["create", "kyra", "--regenerate", "--no-review", "--seed", "4",
                                                "--qwen-model", "qwen21-q4", "--lora", "uncensored=1.0"]
    status, _h, payload = mt.api(s, "POST", "/api/characters/kyra/regenerate", body={"ws": ws})
    assert status == 201 and _job(state, payload)["argv"][2:] == ["create", "kyra", "--regenerate", "--no-review"]


# --- QET37 (QE60): the batch levels, groups and merge ------------------------------------------------------------

def test_qet37_the_batch_levels_groups_and_merge():
    assert set(batch.FIELD_LEVELS) | set(batch.FIXED_KEYS) == set(lib.DEFAULT_FIELDS)
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (27, 5, 32)
    assert (batch.FIELD_LEVELS["seed_edit_model"], batch.FIELD_LEVELS["seed_edit_loras"]) == ("stills", "stills")
    assert batch.GROUPS == (("panels", "length"),
                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras"))
    seeded = lib.compose_fields({"ws": "/ws", "action": "movie", "story_id": "s1", "narrative": "N", "seed_upload": UP,
                                 "seed_edit_model": "qwen21-q4", "seed_edit_loras": [{"id": "uncensored", "scale": 1.0}]})

    def variant(settings):
        return {"label": "v1", "settings": settings, "prompt": {"append": "", "replace": [], "per_story": {}}}

    for settings in ({"width": 768, "height": 512}, {"height": 512}, {"seed_upload": None}):
        fork = batch.merge(seeded, variant(settings), "s1", None, "/ws")[1]
        assert (fork["seed_edit_model"], fork["seed_edit_loras"]) == (None, None), settings
    fork = batch.merge(seeded, variant({"panels": 12}), "s1", None, "/ws")[1]
    assert (fork["seed_edit_model"], fork["seed_upload"]) == ("qwen21-q4", UP)


# --- Review Focus 4: a photo location made before this feature regenerates on its old model ------------------

def test_qe_review_focus_4_a_legacy_photo_location_keeps_its_model(env):
    s, ws, state, probes = env["srv"], env["ws"], env["state"], env["probes"]
    _record(env["locations"], "old-mill", "location.json",
            {"source": "photos", "photos": [{"path": None, "sha256": "0" * 64}] * 2})
    legacy = {"ws": ws, "new_seed": True, "qwen_model": "qwen2511-bf16", "loras": []}
    bf16 = "needs a host with at least 64 GiB of memory (this host has 48.0 GiB)"
    probes["answer"] = (_probe(models={"qwen2511-bf16": {"ok": False, "reason": bf16}}), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=legacy)
    assert (status, payload["error"]) == (409, "Qwen-Image-Edit-2511 bf16 (Lightning, diffusers) is unavailable: " + bf16)
    probes["answer"] = (_probe(), None)
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate", body=legacy)
    assert status == 201
    job = _job(state, payload)
    assert job["argv"][2:] == ["create", "old-mill", "--regenerate", "--new-seed", "--qwen-model", "qwen2511-bf16"]
    assert (job["fields"]["qwen_model"], job["fields"]["loras"]) == ("qwen2511-bf16", [])
    status, _h, payload = mt.api(s, "POST", "/api/locations/old-mill/regenerate",
                                 body=dict(legacy, loras=[{"id": "uncensored", "scale": 1}]))
    assert (status, payload["errors"]) == (400, [
        "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)"])


# --- Review Focus 5: the selection survives the request -> argv -> tool round trip ------------------------------

ROUND_TRIPS = [("qwen21-q4", [{"id": "viggle-turbo", "scale": 2}, {"id": "uncensored", "scale": 1e-06}]),
               ("qwen21-q8", [{"id": "uncensored", "scale": 0.1 + 0.2}]), ("qwen21-bf16", []), ("qwen2511-q4", []),
               ("qwen2511-bf16", []), ("qwen21-q4", None), (None, None)]


def _flags(argv, model_flag, lora_flag):
    i = argv.index(model_flag)
    return argv[i + 1], [argv[k + 1] for k in range(i, len(argv) - 1) if argv[k] == lora_flag]


def test_qe_review_focus_5_the_selection_round_trip(tmp_path, monkeypatch):
    state = mt.set_home(monkeypatch, tmp_path)
    for model_id, loras in ROUND_TRIPS:
        clean_model, clean_loras, error = seedgen.qwen_selection(model_id, loras)
        assert error is None, (model_id, loras)
        want = qwen_edit.settings(clean_model, clean_loras)
        builders = [
            (lib.location_argv("location-create", {"name": "old-mill", "photo_uploads": [UP], "seed": None,
                                                   "qwen_model": clean_model, "loras": clean_loras}, WS, state),
             "--qwen-model", "--lora"),
            (lib.character_argv("character-create", {"name": "kyra", "phrase": "the woman", "seed_upload": UP,
                                                     "qwen_model": clean_model, "loras": clean_loras}, WS, state),
             "--qwen-model", "--lora"),
            (lib.build_argv(mt.fields(WS, seed_upload=UP, action="movie", seed_edit_model=clean_model,
                                      seed_edit_loras=clean_loras), WS, state), "--seed-edit-model", "--seed-edit-lora")]
        for argv, model_flag, lora_flag in builders:
            model_arg, lora_args = _flags(argv, model_flag, lora_flag)
            got = qwen_edit.cli_selection(model_arg, lora_args, model_flag, lora_flag)
            assert qwen_edit.settings(*got) == want, (model_id, loras, model_flag)
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_movie_ui_batch.py 2>&1 | tail -3`
Run also `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_http.py::test_mu14_ws_parameter_errors_and_options 2>&1 | tail -1`.
Expected: QET33-QET37 and both Review Focus tests fail (`KeyError: 'seed_edit_model'`, `AttributeError: ... 'qwen_selection'`, wrong counts), `test_lu10`, `test_mut3`, `test_mu14` and `test_bt1_every_default_field_is_classified` fail on the counts, `test_mut26` fails (expected); everything else passes.

- [ ] **Step 3: Write the implementation.**

Edit `movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
def _qwen_fields(body, model):
    """Seed models SQ30 rows 9a-9i: (qwen_model, loras, None) cleaned, or (None, None, error)."""
    model_id, loras = body.get("qwen_model"), body.get("loras")
    if model == "zimage":
        if model_id is not None:
            return None, None, "qwen_model is only for qwen"
        if loras is not None:
            return None, None, "loras is only for qwen"
        return None, [], None
    if model_id is not None and not (isinstance(model_id, str) and model_id in QWEN_MODEL_IDS):
        return None, None, "unknown qwen_model %s" % (model_id,)
    if model_id is None:
        model_id = DEFAULT_QWEN_MODEL
    if loras is None:
        return model_id, default_loras(model_id), None
    if not isinstance(loras, list):
        return None, None, LORAS_MSG
    entry, seen, clean = qwen_model(model_id), set(), []
    for item in loras:
        if not (isinstance(item, dict) and set(item) == {"id", "scale"}):
            return None, None, LORAS_MSG
```

with:

```python
def qwen_selection(model_id, loras, model_key="qwen_model", loras_key="loras"):
    """Seed models SQ30 rows 9b-9i as a shared rule (qwen edit models QE51): (model_id, loras, None)
    cleaned, or (None, None, error). A null model is DEFAULT_QWEN_MODEL, null loras that model's
    default_loras, [] no LoRA; model_key and loras_key name the request fields in the texts."""
    lists = "%s must be a list of {id, scale}" % loras_key
    if model_id is not None and not (isinstance(model_id, str) and model_id in QWEN_MODEL_IDS):
        return None, None, "unknown %s %s" % (model_key, model_id)
    if model_id is None:
        model_id = DEFAULT_QWEN_MODEL
    if loras is None:
        return model_id, default_loras(model_id), None
    if not isinstance(loras, list):
        return None, None, lists
    entry, seen, clean = qwen_model(model_id), set(), []
    for item in loras:
        if not (isinstance(item, dict) and set(item) == {"id", "scale"}):
            return None, None, lists
```

Edit `movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
        clean.append({"id": lora_id, "scale": float(scale)})
    return model_id, registry_order(clean), None
```

with:

```python
        clean.append({"id": lora_id, "scale": float(scale)})
    return model_id, registry_order(clean), None


def _qwen_fields(body, model):
    """Seed models SQ30 rows 9a-9i: (qwen_model, loras, None) cleaned, or (None, None, error)."""
    model_id, loras = body.get("qwen_model"), body.get("loras")
    if model == "zimage":
        if model_id is not None:
            return None, None, "qwen_model is only for qwen"
        if loras is not None:
            return None, None, "loras is only for qwen"
        return None, [], None
    return qwen_selection(model_id, loras)
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    "width": None, "height": None, "seed_upload": None,
```

with:

```python
    "width": None, "height": None, "seed_upload": None, "seed_edit_model": None, "seed_edit_loras": None,
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    ("no_review", ("--no-review",)),
)
```

with:

```python
    ("no_review", ("--no-review",)), ("seed_edit", ("--seed-edit-model", "--seed-edit-lora")),
)
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    return "%s:%s" % (item["name"], repr(float(item["strength"])))


def build_argv(fields, ws_real, state, py=sys.executable):
```

with:

```python
    return "%s:%s" % (item["name"], repr(float(item["strength"])))


def qwen_edit_flags(model_flag, lora_flag, model_id, loras):
    """[model_flag, model_id] then lora_flag ID=SCALE per LoRA, SCALE as repr(float) (qwen edit models QE52)."""
    argv = [model_flag, model_id]
    for lora in loras or []:
        argv += [lora_flag, "%s=%r" % (lora["id"], float(lora["scale"]))]
    return argv


def build_argv(fields, ws_real, state, py=sys.executable):
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        argv += ["--seed-image", os.path.join(state, "uploads", fields["seed_upload"])]
    elif fields["width"] is not None and fields["height"] is not None:
```

with:

```python
        argv += ["--seed-image", os.path.join(state, "uploads", fields["seed_upload"])]
        if fields.get("seed_edit_model") is not None:
            argv += qwen_edit_flags("--seed-edit-model", "--seed-edit-lora", fields["seed_edit_model"],
                                    fields.get("seed_edit_loras"))
    elif fields["width"] is not None and fields["height"] is not None:
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        errors.append("locations need the story engine; turn off story legacy")
    return errors
```

with:

```python
        errors.append("locations need the story engine; turn off story legacy")
    return errors


SEED_EDIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def _rule_seed_edit(fields):
    """V1 rule 12d (qwen edit models QE54): the shape of the Compose seed edit fields."""
    model, loras, seed = fields.get("seed_edit_model"), fields.get("seed_edit_loras"), fields.get("seed_upload")
    errors = []
    if not (model is None or (isinstance(model, str) and SEED_EDIT_ID_RE.fullmatch(model))):
        errors.append("seed edit model must be as-is or a Qwen model ID")
    if not (loras is None or (isinstance(loras, list) and len(loras) <= 4 and all(
            isinstance(i, dict) and set(i) == {"id", "scale"} and isinstance(i["id"], str)
            and SEED_EDIT_ID_RE.fullmatch(i["id"]) and _is_number(i["scale"]) for i in loras))):
        errors.append("seed edit LoRAs must be a list of at most 4 {id, scale} items")
    if model is not None and seed is None:
        errors.append("a seed edit model needs a seed image")
    if loras is not None and model in (None, "as-is"):
        errors.append("seed edit LoRAs need a seed edit model other than as-is")
    return errors
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        if fields.get("description"):
            argv += ["--description", fields["description"]]
        return argv + (["--force"] if fields.get("force") else [])
```

with:

```python
        if fields.get("description"):
            argv += ["--description", fields["description"]]
        if fields.get("qwen_model") is not None:
            argv += qwen_edit_flags("--qwen-model", "--lora", fields["qwen_model"], fields.get("loras"))
        return argv + (["--force"] if fields.get("force") else [])
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    return argv + (["--force"] if fields.get("force") else [])
```

with:

```python
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    if fields.get("qwen_model") is not None:
        argv += qwen_edit_flags("--qwen-model", "--lora", fields["qwen_model"], fields.get("loras"))
    return argv + (["--force"] if fields.get("force") else [])
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
        if fields.get("seed") is not None:
            argv += ["--seed", str(fields["seed"])]
        return argv
```

with:

```python
        if fields.get("seed") is not None:
            argv += ["--seed", str(fields["seed"])]
        if fields.get("qwen_model") is not None:
            argv += qwen_edit_flags("--qwen-model", "--lora", fields["qwen_model"], fields.get("loras"))
        return argv
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    if fields.get("force"):
        argv.append("--force")
    return argv + ["--no-review"]
```

with:

```python
    if fields.get("seed") is not None:
        argv += ["--seed", str(fields["seed"])]
    if fields.get("qwen_model") is not None:
        argv += qwen_edit_flags("--qwen-model", "--lora", fields["qwen_model"], fields.get("loras"))
    if fields.get("force"):
        argv.append("--force")
    return argv + ["--no-review"]
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    errors += _rule_locations(fields)                                        # 12c
```

with:

```python
    errors += _rule_locations(fields)                                        # 12c
    errors += _rule_seed_edit(fields)                                        # 12d
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
PHASE_RE = re.compile(r"^=== Phase (\d+b?): (.+?)(?: \(rewrite (\d+) of (\d+)\))? ===$")
```

with:

```python
PHASE_RE = re.compile(r"^=== Phase (\d+[bc]?): (.+?)(?: \(rewrite (\d+) of (\d+)\))? ===$")
```

Edit `movie_ui_lib.py`: replace this text, which occurs exactly once:

```python
    return (seed + ["1", "1b"] + (["redo"] if fields.get("action") == "redo" else [])
            + ([] if fields.get("mode") == "no_stills" else ["2"]) + ["3", "4"])
```

with:

```python
    edit = (["1c"] if kind == "movie" and fields.get("seed_upload")
            and fields.get("seed_edit_model") not in (None, "as-is") else [])
    return (seed + ["1", "1b"] + edit + (["redo"] if fields.get("action") == "redo" else [])
            + ([] if fields.get("mode") == "no_stills" else ["2"]) + ["3", "4"])
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
def _fields_body(body):
    fields = lib.compose_fields(body)
    fields["ws"] = resolve_ws(body.get("ws"))
    return fields
```

with:

```python
def _fields_body(body):
    fields = lib.compose_fields(body)
    fields["ws"] = resolve_ws(body.get("ws"))
    if fields["seed_edit_model"] not in (None, "as-is"):
        # Qwen edit models QE57: a named registry selection is checked and stored cleaned (400 otherwise).
        model_id, loras, error = seedgen.qwen_selection(fields["seed_edit_model"], fields["seed_edit_loras"],
                                                        "seed_edit_model", "seed_edit_loras")
        if error is not None:
            raise ApiError(400, error)
        fields["seed_edit_model"], fields["seed_edit_loras"] = model_id, loras
    return fields


def _edit_given(body):
    """Qwen edit models QE56: True when a Locations or Characters request names a Qwen edit selection."""
    return body.get("qwen_model") is not None or body.get("loras") is not None


def edit_availability(real, model_id, loras):
    """The 409 text of a Qwen edit selection (seed models SQ31 rules through bin/seed-edit --probe), or None."""
    models, detail = lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
    return seedgen.availability_error(models, detail, {"model": "qwen", "qwen_model": model_id, "loras": loras})
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if not lib.checks_pass(checks):
        raise ApiError(409, "validation failed", checks=checks)
    job_id = create_compose_job(self.server, fields,
```

with:

```python
    if not lib.checks_pass(checks):
        raise ApiError(409, "validation failed", checks=checks)
    if (fields["action"] == "movie" and fields["seed_upload"]
            and fields["seed_edit_model"] not in (None, "as-is")):
        text = edit_availability(fields["ws"], fields["seed_edit_model"], fields["seed_edit_loras"])
        if text is not None:
            raise ApiError(409, text)
    job_id = create_compose_job(self.server, fields,
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    clean, error = seedfolder.validate_request(body)
    if error is not None:
        raise ApiError(400, error)
    fields["seed_upload"] = fields["width"] = fields["height"] = None
```

with:

```python
    clean, error = seedfolder.validate_request(body)
    if error is not None:
        raise ApiError(400, error)
    if (not clean["preview"] and fields["action"] == "movie"
            and fields["seed_edit_model"] not in (None, "as-is")):
        text = edit_availability(fields["ws"], fields["seed_edit_model"], fields["seed_edit_loras"])
        if text is not None:
            raise ApiError(409, text)
    fields["seed_upload"] = fields["width"] = fields["height"] = None
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if not isinstance(force, bool):
        errors.append("force must be true or false")
    return errors
```

with:

```python
    if not isinstance(force, bool):
        errors.append("force must be true or false")
    if _edit_given(body):
        if seed is None:
            errors.append("qwen_model and loras apply only to seed-image characters")
        else:
            error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))[2]
            if error is not None:
                errors.append(error)
    return errors
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    fields["force"] = body.get("force", False)
    fields["ws"] = real
    return create_character_job(self.server, "character-create", real, fields)
```

with:

```python
    fields["force"] = body.get("force", False)
    fields["ws"] = real
    if _edit_given(body) and fields["seed_upload"]:
        model_id, loras, _error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))
        text = edit_availability(real, model_id, loras)
        if text is not None:
            raise ApiError(409, text)
        fields["qwen_model"], fields["loras"] = model_id, loras
    return create_character_job(self.server, "character-create", real, fields)
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    clean, error = seedfolder.validate_character_request(body)
    if error is not None:
        raise ApiError(400, error)
    rows = _character_rows(server, real, body, clean)
```

with:

```python
    clean, error = seedfolder.validate_character_request(body)
    if error is not None:
        raise ApiError(400, error)
    edit = None
    if _edit_given(body):
        model_id, loras, error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))
        if error is not None:
            raise ApiError(400, error)
        if not clean["preview"]:
            text = edit_availability(real, model_id, loras)
            if text is not None:
                raise ApiError(409, text)
        edit = (model_id, loras)
    rows = _character_rows(server, real, body, clean)
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
                      "force": False, "ws": real, "seed_folder": {"run": run, "name": rows[i]["name"]}}
```

with:

```python
                      "force": False, "ws": real, "seed_folder": {"run": run, "name": rows[i]["name"]}}
            if edit is not None:
                fields["qwen_model"], fields["loras"] = edit
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    seed = body.get("seed")
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed <= 2147483647):
        raise ApiError(400, "invalid fields", errors=["seed must be an integer from 0 to 2147483647"])
    return create_character_job(self.server, "character-regenerate", real,
                                {"ws": real, "name": groups[0], "seed": seed})
```

with:

```python
    seed = body.get("seed")
    errors = []
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed <= 2147483647):
        errors.append("seed must be an integer from 0 to 2147483647")
    given = _edit_given(body)
    if given:
        library = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(real, "generated", "characters")
        record = lib.read_json(os.path.join(library, groups[0], "character.json"))
        source = record.get("source") if isinstance(record, dict) else None
        if isinstance(source, dict) and source.get("type") == "descriptor":
            errors.append("qwen_model and loras apply only to seed-image characters")
        else:
            error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))[2]
            if error is not None:
                errors.append(error)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = {"ws": real, "name": groups[0], "seed": seed}
    if given:
        model_id, loras, _error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))
        text = edit_availability(real, model_id, loras)
        if text is not None:
            raise ApiError(409, text)
        fields["qwen_model"], fields["loras"] = model_id, loras
    return create_character_job(self.server, "character-regenerate", real, fields)
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    errors += _seed_errors(body.get("seed"))
    if not isinstance(body.get("force", False), bool):
        errors.append("force must be true or false")
    return errors
```

with:

```python
    errors += _seed_errors(body.get("seed"))
    if not isinstance(body.get("force", False), bool):
        errors.append("force must be true or false")
    if _edit_given(body):
        if not photos:
            errors.append("qwen_model and loras apply only to photo locations")
        else:
            error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))[2]
            if error is not None:
                errors.append(error)
    return errors
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
              "seed": body.get("seed"), "force": body.get("force", False)}
    return create_location_job(self.server, "location-create", real, fields)
```

with:

```python
              "seed": body.get("seed"), "force": body.get("force", False)}
    if _edit_given(body) and fields["photo_uploads"]:
        model_id, loras, _error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))
        if len(fields["photo_uploads"]) < LOCATION_MAX_PHOTOS:       # 24 photos: no edit runs
            text = edit_availability(real, model_id, loras)
            if text is not None:
                raise ApiError(409, text)
        fields["qwen_model"], fields["loras"] = model_id, loras
    return create_location_job(self.server, "location-create", real, fields)
```

Edit `movie_ui_server.py`: replace this text, which occurs exactly once:

```python
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    return create_location_job(self.server, "location-regenerate", real,
                               {"ws": real, "name": groups[0], "seed": seed, "new_seed": new_seed,
                                "description": description or None, "force": force})
```

with:

```python
    given = _edit_given(body)
    record = None
    if given:
        library = os.environ.get("LOCATION_LIBRARY_DIR") or os.path.join(real, "generated", "locations")
        record = lib.read_json(os.path.join(library, groups[0], "location.json"))
        if isinstance(record, dict) and record.get("source") == "text":
            errors.append("qwen_model and loras apply only to photo locations")
        else:
            error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))[2]
            if error is not None:
                errors.append(error)
    if errors:
        raise ApiError(400, "invalid fields", errors=errors)
    fields = {"ws": real, "name": groups[0], "seed": seed, "new_seed": new_seed,
              "description": description or None, "force": force}
    if given:
        model_id, loras, _error = seedgen.qwen_selection(body.get("qwen_model"), body.get("loras"))
        photos = record.get("photos") if isinstance(record, dict) else None
        if not (isinstance(photos, list) and len(photos) >= LOCATION_MAX_PHOTOS):   # plan ruling R11
            text = edit_availability(real, model_id, loras)
            if text is not None:
                raise ApiError(409, text)
        fields["qwen_model"], fields["loras"] = model_id, loras
    return create_location_job(self.server, "location-regenerate", real, fields)
```

Edit `movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
GROUPS = (("panels", "length"), ("width", "height", "seed_upload"))
```

with:

```python
GROUPS = (("panels", "length"), ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras"))
```

Edit `movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
```

with:

```python
    "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
    "seed_edit_model": "stills", "seed_edit_loras": "stills",
```

Edit `movie_ui_batch.py`: replace this text, which occurs exactly once:

```python
        elif key in ("width", "height"):
            fork["seed_upload"] = None
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
```

with:

```python
        elif key in ("width", "height"):
            fork["seed_upload"] = None
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None
        elif key == "seed_upload" and value is not None:
            fork["width"] = fork["height"] = None
        elif key == "seed_upload" and value is None:
            fork["seed_edit_model"] = fork["seed_edit_loras"] = None      # rule 12d: no edit without a seed
```

- [ ] **Step 4: Run the tests and the compile check; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_batch.py tests/test_movie_ui_http.py tests/test_movie_ui_checks.py tests/test_movie_ui_progress.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_qwen_edit.py 2>&1 | tail -1`
Expected: only `test_mut26_pipeline_files_are_unchanged` fails (expected); every other test passes.

Run the compile check with `FILES` = `movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_qwen_edit.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_movie_ui_batch.py tests/test_movie_ui_http.py tests/test_qwen_edit.py`. Expected: `compiled 10` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=6`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 47, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`; the 7 new tests are QET33-QET37 and Review Focus 4, 5), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add movie_ui_seedgen.py movie_ui_lib.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_qwen_edit.py tests/test_location_ui.py tests/test_movie_ui_builder.py tests/test_movie_ui_batch.py tests/test_movie_ui_http.py tests/test_qwen_edit.py tests/fixtures/movie_ui/ltx-movie-help-current.txt
git diff --cached --name-only    # expected: exactly those eleven paths
git commit -m "movie-ui: Qwen edit selections for Compose, Locations and Characters: fields, rule 12d, 400/409 and argv (qwen edit models QE51-QE60, QE69, QET33-QET37)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The page: one `qwenPicker` and its six mounts on four tabs (QE61-QE68; QET38, QET39)

This task implements, in `static/movie-ui/index.html` and `static/movie-ui/app.js`:
- QE63: the five new picker blocks (Locations form and detail, Characters form and detail, the Compose Resolution fieldset inside its `data-field="seed_edit"` wrapper); the Seeds `#se-qwen-box` is unchanged.
- QE61: `qwenPicker(prefix, asIs)`, typed as the spec gives it, after `seedModelText`; `readSeedQwen`, `renderSeedQwen` and `seedLoraBody` are removed; `seedMultiple` reads the Seeds picker.
- QE62: the six `const ..._PICKER = qwenPicker(...)` mounts after `S.seeds`, `S.seeds` without `qwen`/`qwenKey`, `S.seedOrigin`.
- QE64 (Seeds), QE65 (Locations), QE66 (Characters), QE67 (Compose: `composeSeedEditActive`, `composeSeedDefault`, the four callers, `updateComposeButtons`, `composeFields`, `setupCompose`).
- Tests: QET38, QET39 appended to `tests/test_movie_ui_qwen_edit.py`; §11.3's SGT33 `SEED_FUNCTIONS`, SQT22 `QWEN_JS_TEXTS` and `test_sq_final_d_e_f_page_guards` edits in `tests/test_movie_ui_seedgen.py`.

The picker's behaviour in a browser is the controller's V2 (spec 11.4), not a pytest DOM fake.

**Files:**
- Modify: `static/movie-ui/index.html` (`:89`, `:279`, `:300`, `:318`, `:335`), `static/movie-ui/app.js` (`S` `:22-26`, `S.seeds` `:43`, `seedMultiple`..`seedLoraBody` `:1785-1884`, `seedModelText` end `:1899`, `updateSeedButtons` `:1924-1987`, `seedBody` `:2024`, `composeFields` `:406-439`, `updateComposeButtons` `:516-538`, `onSeedFile` `:547-560`, `onFolderPick` `:576-600`, `fillCompose` `:776-`, `setupCompose` `:829-`, `useSeed` `:2162-2174`, `openCharacter`, `updateCharacterButtons`, `createCharacter`, `setupCharacters`, `openLocation`, `updateLocationButtons`, `createLocation`, `setupLocations`).
- Modify (tests): `tests/test_movie_ui_qwen_edit.py`, `tests/test_movie_ui_seedgen.py`.

**Interfaces:**
- Consumes (Task 6): `/api/options`' `supported.seed_edit`; the request fields Compose `seed_edit_model`/`seed_edit_loras`, Locations and Characters `qwen_model`/`loras`; `capability("seed_edit")`'s `registry` and `models` (unchanged since seed models); `location.json`'s and `character.json`'s `edit` key (Tasks 3, 4) through `/api/locations/<name>` and `/api/characters/<name>`.
- Produces: `qwenPicker(prefix, asIs)` returning `{state, key, wanted, select(model, loras), update(), read(), render(), selection() -> null or {model, loras}, reason() -> text, multiple() -> int, listen(onChange)}`; the six mounts `SEED_PICKER`, `LOCATION_PICKER`, `LOCATION_REGEN_PICKER`, `CHARACTER_PICKER`, `CHARACTER_REGEN_PICKER`, `COMPOSE_PICKER`; `composeSeedEditActive() -> bool`, `composeSeedDefault(origin)`; `S.seedOrigin` (`"seeds"`, `"upload"`, `"folder"`, `"job"` or `null`).

- [ ] **Step 1: Write the failing tests and the §11.3 edits.**

Edit `tests/test_movie_ui_qwen_edit.py` (append QET38, QET39 at the end of the file): replace this text, which occurs exactly once:

```python
        for argv, model_flag, lora_flag in builders:
            model_arg, lora_args = _flags(argv, model_flag, lora_flag)
            got = qwen_edit.cli_selection(model_arg, lora_args, model_flag, lora_flag)
            assert qwen_edit.settings(*got) == want, (model_id, loras, model_flag)
```

with:

```python
        for argv, model_flag, lora_flag in builders:
            model_arg, lora_args = _flags(argv, model_flag, lora_flag)
            got = qwen_edit.cli_selection(model_arg, lora_args, model_flag, lora_flag)
            assert qwen_edit.settings(*got) == want, (model_id, loras, model_flag)


# --- QET38, QET39 (QE61-QE63, QE67, QE68): the picker on the static page ------------------------------------

PREFIXES = ("lo-cq", "lo-rq", "ch-cq", "ch-rq", "c-sq")
SUFFIXES = ("qwen-box", "qwen-model", "steps", "loras", "qwen-note", "reason")
QWEN_BOX = ('      <div id="se-qwen-box" class="wide" hidden>\n'
            '        <label>Qwen model <select id="se-qwen-model"></select></label>\n'
            '        <span id="se-steps" class="muted"></span>\n'
            '        <div id="se-loras" class="se-loras"></div>\n'
            '        <p id="se-qwen-note" class="muted"></p>\n'
            '      </div>\n')   # SQT22's Seeds box, unchanged
MOUNTS = ('const SEED_PICKER = qwenPicker("se", false);', 'const LOCATION_PICKER = qwenPicker("lo-cq", false);',
          'const LOCATION_REGEN_PICKER = qwenPicker("lo-rq", false);',
          'const CHARACTER_PICKER = qwenPicker("ch-cq", false);',
          'const CHARACTER_REGEN_PICKER = qwenPicker("ch-rq", false);', 'const COMPOSE_PICKER = qwenPicker("c-sq", true);')


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


def _function(js, head):
    """The text of the app.js function starting with head, through its closing line."""
    start = js.index(head)
    return js[start:js.index("\n  }\n", start) + len("\n  }\n")]


def test_qet38_the_picker_on_the_page():
    static, html, js = _page()
    for prefix in PREFIXES:
        for suffix in SUFFIXES:
            assert html.count('id="%s-%s"' % (prefix, suffix)) == 1, (prefix, suffix)
    wrapper = html.index('<div data-field="seed_edit" class="wide">')
    assert html.index('id="c-folder-list"') < wrapper < html.index('id="c-sq-qwen-box"') < html.index(
        "</fieldset>", wrapper)
    assert '<span id="se-model-note" class="muted"></span>\n' + QWEN_BOX in html
    assert js.count("function qwenPicker(prefix, asIs) {") == 1 and '"Seed as-is (no edit)"' in js
    assert js.index("  function seedModelText(view) {") < js.index("  function qwenPicker(prefix, asIs) {")
    for line in MOUNTS:
        assert js.count(line) == 1, line
    assert js.index('S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};') < js.index(
        MOUNTS[0])
    for gone in ("function renderSeedQwen(", "function readSeedQwen(", "function seedLoraBody(", "S.seeds.qwen",
                 "qwenKey"):
        assert gone not in js, gone
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


def test_qet39_the_compose_defaults_and_fields():
    _static, _html, js = _page()
    assert 'composeSeedDefault("seeds");' in _function(js, "  async function useSeed(run, n, status) {")
    assert 'composeSeedDefault("upload");' in _function(js, "  async function onSeedFile() {")
    assert 'composeSeedDefault("folder")' in _function(js, "  function onFolderPick(box) {")
    assert ('COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);'
            in _function(js, "  function fillCompose(fields) {"))
    body = _function(js, "  function composeFields(action) {")
    assert "const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;" in body
    assert ('seed_edit_model: seedEdit ? seedEdit.model : null, seed_edit_loras: seedEdit && seedEdit.model !== '
            '"as-is" ? seedEdit.loras : null,') in body
    assert js.count("function composeSeedDefault(origin) {") == 1
    assert js.count("function composeSeedEditActive() {") == 1
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
                  "resetSeeds", "setupSeeds", "seedRegistry", "seedQwenEntry", "seedLoraEntry", "seedMultiple",
                  "renderSeedQwen", "readSeedQwen", "seedLoraBody", "seedModelText")
```

with:

```python
                  "resetSeeds", "setupSeeds", "seedRegistry", "seedQwenEntry", "seedLoraEntry", "seedMultiple",
                  "seedModelText")
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
                 '"se-lora-scale-"', '"se-lora-note-"', '" — unavailable"', '"checking models…"', '" (Lightning)"',
                 "qwen_model: model === \"qwen\" ? S.seeds.qwen.model : null",
                 "loras: model === \"qwen\" ? seedLoraBody() : null",
```

with:

```python
                 'prefix + "-lora-scale-"', 'prefix + "-lora-note-"', '" — unavailable"', '"checking models…"',
                 '" (Lightning)"',
                 "qwen_model: model === \"qwen\" ? SEED_PICKER.selection().model : null",
                 "loras: model === \"qwen\" ? SEED_PICKER.selection().loras : null",
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
                 'S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false, qwen: null, '
                 'qwenKey: ""};',
```

with:

```python
                 'S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};',
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
    for text in ('    if (model === "qwen" && models && !S.seeds.qwen) {\n'
                 '      qwenReason = "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui '
                 'server)";\n    }\n    else if (model === "qwen" && models && S.seeds.qwen) {\n',
                 '    const cap = capability("seed_edit");\n    const models = cap.models;\n    const state = S.seeds.qwen;\n',
```

with:

```python
    for text in ('      if (!p.state) {\n'
                 '        return models ? "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui '
                 'server)"\n',
                 'let qwenReason = ""; if (model === "qwen" && models) { qwenReason = SEED_PICKER.reason(); }',
                 '      const cap = capability("seed_edit");\n      const models = cap.models;\n      const state = p.state;\n',
```

Edit `tests/test_movie_ui_seedgen.py`: replace this text, which occurs exactly once:

```python
                 'const note = el("span", {cls: "muted", id: "se-lora-note-" + l.id, text: loraNote(l)});',
```

with:

```python
                 'const note = el("span", {cls: "muted", id: prefix + "-lora-note-" + l.id, text: loraNote(l)});',
```

- [ ] **Step 2: Run the page tests to verify they fail.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py -k "qet38 or qet39" tests/test_movie_ui_seedgen.py 2>&1 | tail -3`
Expected: QET38, QET39, `test_sgt33_the_static_page` (the removed functions are still defined, `"function renderSeedQwen("` count), `test_sqt22_the_qwen_box_on_the_page` and `test_sq_final_d_e_f_page_guards` (the new texts are missing) fail; every other Seeds test passes.

- [ ] **Step 3: Write the implementation.** Every Edit below, in order (index.html first, then app.js).

Edit `static/movie-ui/index.html` (QE63, the Locations form): replace this text, which occurs exactly once:

```html
    <label class="wide">Photos <input id="lo-photos" type="file" multiple accept="image/png,image/jpeg,image/webp"></label>
  </div>
```

with:

```html
    <label class="wide">Photos <input id="lo-photos" type="file" multiple accept="image/png,image/jpeg,image/webp"></label>
    <div id="lo-cq-qwen-box" class="wide" hidden>
      <label>Qwen edit model (photo edits) <select id="lo-cq-qwen-model"></select></label>
      <span id="lo-cq-steps" class="muted"></span>
      <div id="lo-cq-loras" class="se-loras"></div>
      <p id="lo-cq-qwen-note" class="muted"></p>
      <span id="lo-cq-reason" class="muted"></span>
    </div>
  </div>
```

Edit `static/movie-ui/index.html` (QE63, the Locations detail): replace this text, which occurs exactly once:

```html
      <span id="lo-status" class="muted"></span>
    </div>
```

with:

```html
      <span id="lo-status" class="muted"></span>
    </div>
    <div id="lo-rq-qwen-box" class="wide" hidden>
      <label>Qwen edit model for Regenerate <select id="lo-rq-qwen-model"></select></label>
      <span id="lo-rq-steps" class="muted"></span>
      <div id="lo-rq-loras" class="se-loras"></div>
      <p id="lo-rq-qwen-note" class="muted"></p>
      <span id="lo-rq-reason" class="muted"></span>
    </div>
```

Edit `static/movie-ui/index.html` (QE63, the Characters form): replace this text, which occurs exactly once:

```html
    <ul id="ch-folder-list" class="muted" hidden></ul>
  </div>
```

with:

```html
    <ul id="ch-folder-list" class="muted" hidden></ul>
    <div id="ch-cq-qwen-box" class="wide" hidden>
      <label>Qwen edit model (seed-image edits) <select id="ch-cq-qwen-model"></select></label>
      <span id="ch-cq-steps" class="muted"></span>
      <div id="ch-cq-loras" class="se-loras"></div>
      <p id="ch-cq-qwen-note" class="muted"></p>
      <span id="ch-cq-reason" class="muted"></span>
    </div>
  </div>
```

Edit `static/movie-ui/index.html` (QE63, the Characters detail): replace this text, which occurs exactly once:

```html
      <span id="ch-status" class="muted"></span>
    </div>
```

with:

```html
      <span id="ch-status" class="muted"></span>
    </div>
    <div id="ch-rq-qwen-box" class="wide" hidden>
      <label>Qwen edit model for Regenerate <select id="ch-rq-qwen-model"></select></label>
      <span id="ch-rq-steps" class="muted"></span>
      <div id="ch-rq-loras" class="se-loras"></div>
      <p id="ch-rq-qwen-note" class="muted"></p>
      <span id="ch-rq-reason" class="muted"></span>
    </div>
```

Edit `static/movie-ui/index.html` (QE63, the Compose Resolution fieldset): replace this text, which occurs exactly once:

```html
      <ul id="c-folder-list" class="muted" hidden></ul>
    </fieldset>
```

with:

```html
      <ul id="c-folder-list" class="muted" hidden></ul>
      <div data-field="seed_edit" class="wide">
        <div id="c-sq-qwen-box" hidden>
          <label>Panel 1 from the seed <select id="c-sq-qwen-model"></select></label>
          <span id="c-sq-steps" class="muted"></span>
          <div id="c-sq-loras" class="se-loras"></div>
          <p id="c-sq-qwen-note" class="muted"></p>
          <span id="c-sq-reason" class="muted"></span>
        </div>
      </div>
    </fieldset>
```

Edit `static/movie-ui/app.js` (QE62): replace this text, which occurs exactly once:

```js
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

with:

```js
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, seedOrigin: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
```

Edit `static/movie-ui/app.js` (QE62): replace this text, which occurs exactly once:

```js
  // Seed generator spec SG56: the Seeds tab's state.
  S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false, qwen: null, qwenKey: ""};
```

with:

```js
  // Seed generator spec SG56: the Seeds tab's state.
  S.seeds = {source: null, natural: null, run: null, view: null, rows: {}, busy: false};
  // Qwen edit models spec QE62: the picker's mounts.
  const SEED_PICKER = qwenPicker("se", false);
  const LOCATION_PICKER = qwenPicker("lo-cq", false);
  const LOCATION_REGEN_PICKER = qwenPicker("lo-rq", false);
  const CHARACTER_PICKER = qwenPicker("ch-cq", false);
  const CHARACTER_REGEN_PICKER = qwenPicker("ch-rq", false);
  const COMPOSE_PICKER = qwenPicker("c-sq", true);
```

Edit `static/movie-ui/app.js` (QE61, QE64: `readSeedQwen`, `renderSeedQwen` and `seedLoraBody` are absorbed by `qwenPicker`): replace this text, which occurs exactly once:

```js
  function seedMultiple() {
    const entry = seedQwenEntry(S.seeds.qwen ? S.seeds.qwen.model : null);
    return $("#se-model").value === "qwen" && entry ? entry.multiple : 16;
  }

  function readSeedQwen() {
    const state = S.seeds.qwen;
    if (!state) { return; }
    const select = $("#se-qwen-model");
    if (select.value) { state.model = select.value; }
    Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
      const id = row.dataset.lora;
      const box = $("#se-lora-" + id);
      if (!box.disabled) { state.loras[id].checked = box.checked; }
      state.loras[id].scale = $("#se-lora-scale-" + id).value;
    });
  }

  function renderSeedQwen() {
    const registry = seedRegistry();
    const select = $("#se-qwen-model");
    if (!registry) {
      clear(select);
      $("#se-steps").textContent = "checking models…";
      return;
    }
    const cap = capability("seed_edit");
    const models = cap.models;
    const state = S.seeds.qwen;
    function probe(id) { return models && models.qwen.models[id]; }
    function loraProbe(id) { return models && models.qwen.loras[id]; }
    function enabled(id) { return !(probe(id) && probe(id).ok === false); }
    if (select.options.length !== registry.models.length) {
      clear(select);
      registry.models.forEach(function (m) { select.appendChild(el("option", {value: m.id})); });
    }
    registry.models.forEach(function (m, i) {
      const option = select.options[i];
      option.textContent = m.label + (enabled(m.id) ? "" : " — unavailable");
      option.disabled = !enabled(m.id);
    });
    let chosen = state.model;
    if (!enabled(chosen)) {
      const first = registry.models.filter(function (m) { return enabled(m.id); })[0];
      if (enabled(registry.default_model)) { chosen = registry.default_model; }
      else if (first) { chosen = first.id; }
    }
    state.model = chosen;
    select.value = chosen;
    const entry = seedQwenEntry(chosen);
    const loras = registry.loras.filter(function (l) { return l.family === entry.family; });
    function loraOk(id) { return loraProbe(id) ? loraProbe(id).ok === true : false; }
    function loraNote(l) {
      if (loraOk(l.id)) { return l.license + (l.steps ? "; " + l.steps + " steps, scheduler " + l.scheduler : ""); }
      const found = loraProbe(l.id);
      return "unavailable — " + (found ? found.reason : ((cap.ok === false && cap.reason) || "probing"));
    }
    const key = entry.family + "|" + JSON.stringify(loras.map(function (l) { return [l.id, loraOk(l.id), loraNote(l)]; }));
    if (key !== S.seeds.qwenKey) {
      S.seeds.qwenKey = key;
      const box = clear($("#se-loras"));
      if (entry.family === "qwen2511") {
        box.appendChild(el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"}));
      }
      else {
        loras.forEach(function (l) {
          const ok = loraOk(l.id);
          const saved = state.loras[l.id];
          const checkbox = el("input", {type: "checkbox", id: "se-lora-" + l.id});
          checkbox.checked = saved.checked && ok;
          checkbox.disabled = !ok;
          const scale = el("input", {type: "number", id: "se-lora-scale-" + l.id, min: "0", max: "2", step: "0.05", value: saved.scale});
          scale.disabled = !ok;
          const note = el("span", {cls: "muted", id: "se-lora-note-" + l.id, text: loraNote(l)});
          box.appendChild(el("div", {cls: "se-lora", data: {lora: l.id}}, [el("label", {}, [checkbox, " " + l.label]),
            el("label", {}, ["strength ", scale]), note]));
        });
      }
    }
    const turbo = loras.filter(function (l) {
      const box = $("#se-lora-" + l.id);
      return l.steps && box && !box.disabled && box.checked;
    })[0];
    $("#se-steps").textContent = turbo ? turbo.steps + " steps (turbo)"
      : entry.steps + " steps" + (entry.family === "qwen2511" ? " (Lightning)" : "");
    const parts = registry.models.filter(function (m) { return !enabled(m.id); }).map(function (m) {
      return m.label + " — " + probe(m.id).reason;
    });
    $("#se-qwen-note").textContent = parts.length ? "Unavailable here: " + parts.join("; ") : "";
  }

  function seedLoraBody() {
    const out = [];
    Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
      const id = row.dataset.lora;
      const box = $("#se-lora-" + id);
      if (!box.disabled && box.checked) { out.push({id: id, scale: Number($("#se-lora-scale-" + id).value)}); }
    });
    return out;
  }

```

with:

```js
  function seedMultiple() {
    return $("#se-model").value === "qwen" ? SEED_PICKER.multiple() : 16;
  }

```

Edit `static/movie-ui/app.js` (QE61: `qwenPicker`, typed as the spec gives it, directly after `seedModelText`): replace this text, which occurs exactly once:

```js
    if (loras.length) { text += " + " + loras.map(function (l) { return l.id + " " + l.scale; }).join(", "); }
    return text;
  }

  function setSeedSource(source, statusText) {
```

with:

```js
    if (loras.length) { text += " + " + loras.map(function (l) { return l.id + " " + l.scale; }).join(", "); }
    return text;
  }

  // Qwen edit models spec QE61: one Qwen edit model + LoRA picker. prefix names its elements:
  // <prefix>-qwen-box, -qwen-model, -steps, -loras, -qwen-note, -lora-<id>, -lora-scale-<id>, -lora-note-<id>.
  // asIs puts "Seed as-is (no edit)" first (Compose). Nothing touches the DOM before update().
  function qwenPicker(prefix, asIs) {
    const p = {state: null, key: "", wanted: null};
    function node(suffix) { return $("#" + prefix + suffix); }
    function rows() { return document.querySelectorAll("#" + prefix + "-loras .se-lora"); }
    function probe(id) {
      const models = capability("seed_edit").models;
      return models && models.qwen.models[id];
    }
    function enabled(id) { return id === "as-is" || !(probe(id) && probe(id).ok === false); }
    function fresh(wanted) {
      const registry = seedRegistry();
      const loras = {};
      registry.loras.forEach(function (l) {
        const listed = wanted && wanted.loras ? wanted.loras.filter(function (w) { return w.id === l.id; })[0] : null;
        loras[l.id] = {checked: wanted && wanted.loras ? Boolean(listed) : l.default_on,
                       scale: String(listed ? listed.scale : l.default_scale)};
      });
      return {model: wanted && wanted.model ? wanted.model : registry.default_model, loras: loras};
    }
    p.select = function (model, loras) {
      p.wanted = {model: model, loras: loras};
      p.state = null;
      p.key = "";
    };
    p.update = function () {
      if (!p.state && seedRegistry()) {
        p.state = fresh(p.wanted);
        p.wanted = null;
      } else {
        p.read();
      }
      p.render();
    };
    p.read = function () {
      if (!p.state) { return; }
      const select = node("-qwen-model");
      if (select.value) { p.state.model = select.value; }
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        if (!box.disabled) { p.state.loras[id].checked = box.checked; }
        p.state.loras[id].scale = node("-lora-scale-" + id).value;
      });
    };
    p.render = function () {
      const registry = seedRegistry();
      const select = node("-qwen-model");
      if (!registry) {
        clear(select);
        node("-steps").textContent = "checking models…";
        return;
      }
      const cap = capability("seed_edit");
      const models = cap.models;
      const state = p.state;
      function loraProbe(id) { return models && models.qwen.loras[id]; }
      const ids = (asIs ? ["as-is"] : []).concat(registry.models.map(function (m) { return m.id; }));
      if (select.options.length !== ids.length) {
        clear(select);
        ids.forEach(function (id) { select.appendChild(el("option", {value: id})); });
      }
      ids.forEach(function (id, i) {
        const option = select.options[i];
        option.textContent = id === "as-is" ? "Seed as-is (no edit)"
          : seedQwenEntry(id).label + (enabled(id) ? "" : " — unavailable");
        option.disabled = !enabled(id);
      });
      let chosen = state.model;
      if (!enabled(chosen)) {
        const first = registry.models.filter(function (m) { return enabled(m.id); })[0];
        if (enabled(registry.default_model)) { chosen = registry.default_model; }
        else if (first) { chosen = first.id; }
      }
      state.model = chosen;
      select.value = chosen;
      const parts = registry.models.filter(function (m) { return !enabled(m.id); }).map(function (m) {
        return m.label + " — " + probe(m.id).reason;
      });
      node("-qwen-note").textContent = parts.length ? "Unavailable here: " + parts.join("; ") : "";
      if (chosen === "as-is") {
        if (p.key !== "as-is") { p.key = "as-is"; clear(node("-loras")); }
        node("-steps").textContent = "";
        return;
      }
      const entry = seedQwenEntry(chosen);
      const loras = registry.loras.filter(function (l) { return l.family === entry.family; });
      function loraOk(id) { return loraProbe(id) ? loraProbe(id).ok === true : false; }
      function loraNote(l) {
        if (loraOk(l.id)) { return l.license + (l.steps ? "; " + l.steps + " steps, scheduler " + l.scheduler : ""); }
        const found = loraProbe(l.id);
        return "unavailable — " + (found ? found.reason : ((cap.ok === false && cap.reason) || "probing"));
      }
      const key = entry.family + "|" + JSON.stringify(loras.map(function (l) { return [l.id, loraOk(l.id), loraNote(l)]; }));
      if (key !== p.key) {
        p.key = key;
        const box = clear(node("-loras"));
        if (entry.family === "qwen2511") {
          box.appendChild(el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"}));
        }
        else {
          loras.forEach(function (l) {
            const ok = loraOk(l.id);
            const saved = state.loras[l.id];
            const checkbox = el("input", {type: "checkbox", id: prefix + "-lora-" + l.id});
            checkbox.checked = saved.checked && ok;
            checkbox.disabled = !ok;
            const scale = el("input", {type: "number", id: prefix + "-lora-scale-" + l.id, min: "0", max: "2", step: "0.05", value: saved.scale});
            scale.disabled = !ok;
            const note = el("span", {cls: "muted", id: prefix + "-lora-note-" + l.id, text: loraNote(l)});
            box.appendChild(el("div", {cls: "se-lora", data: {lora: l.id}}, [el("label", {}, [checkbox, " " + l.label]),
              el("label", {}, ["strength ", scale]), note]));
          });
        }
      }
      const turbo = loras.filter(function (l) {
        const box = node("-lora-" + l.id);
        return l.steps && box && !box.disabled && box.checked;
      })[0];
      node("-steps").textContent = turbo ? turbo.steps + " steps (turbo)"
        : entry.steps + " steps" + (entry.family === "qwen2511" ? " (Lightning)" : "");
    };
    p.selection = function () {
      if (!p.state) { return null; }
      if (p.state.model === "as-is") { return {model: "as-is", loras: []}; }
      const out = [];
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        if (!box.disabled && box.checked) { out.push({id: id, scale: Number(node("-lora-scale-" + id).value)}); }
      });
      return {model: p.state.model, loras: out};
    };
    p.reason = function () {
      const cap = capability("seed_edit");
      const models = cap.models;
      if (!p.state) {
        return models ? "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui server)"
          : "checking models…";
      }
      if (p.state.model === "as-is") { return ""; }
      if (!models) { return cap.ok === false ? "cannot check the Qwen edit models: " + cap.reason : "checking models…"; }
      const chosen = seedQwenEntry(p.state.model);
      const found = models.qwen.models[p.state.model];
      if (!(found && found.ok === true)) {
        return (chosen ? chosen.label : p.state.model) + " unavailable: " + ((found && found.reason) || "probing");
      }
      let text = "";
      Array.prototype.forEach.call(rows(), function (row) {
        const id = row.dataset.lora;
        const box = node("-lora-" + id);
        const s = Number(node("-lora-scale-" + id).value);
        if (!text && !box.disabled && box.checked && !(Number.isFinite(s) && s > 0 && s <= 2)) {
          text = "LoRA " + seedLoraEntry(id).label + " strength must be above 0 and at most 2";
        }
      });
      return text;
    };
    p.multiple = function () {
      const entry = p.state ? seedQwenEntry(p.state.model) : null;
      return entry ? entry.multiple : 16;
    };
    p.listen = function (onChange) {
      ["input", "change"].forEach(function (type) { node("-qwen-box").addEventListener(type, onChange); });
    };
    return p;
  }

  function setSeedSource(source, statusText) {
```

Edit `static/movie-ui/app.js` (QE64): replace this text, which occurs exactly once:

```js
    const models = cap.models || null;
    const registry = seedRegistry();
    if (!S.seeds.qwen && registry) {
      const loras = {};
      registry.loras.forEach(function (l) { loras[l.id] = {checked: l.default_on, scale: String(l.default_scale)}; });
      S.seeds.qwen = {model: registry.default_model, loras: loras};
    }
    readSeedQwen();
    renderSeedQwen();
```

with:

```js
    const models = cap.models || null;
    SEED_PICKER.update();
```

Edit `static/movie-ui/app.js` (QE64): replace this text, which occurs exactly once:

```js
    let qwenReason = "";
    if (model === "qwen" && models && !S.seeds.qwen) {
      qwenReason = "Qwen-Image unavailable: the server sent no Qwen model list (restart the movie-ui server)";
    }
    else if (model === "qwen" && models && S.seeds.qwen) {
      const chosen = seedQwenEntry(S.seeds.qwen.model);
      const found = models.qwen.models[S.seeds.qwen.model];
      if (!(found && found.ok === true)) {
        qwenReason = (chosen ? chosen.label : S.seeds.qwen.model) + " unavailable: " + ((found && found.reason) || "probing");
      }
      else {
        Array.prototype.forEach.call(document.querySelectorAll("#se-loras .se-lora"), function (row) {
          const id = row.dataset.lora;
          const box = $("#se-lora-" + id);
          const s = Number($("#se-lora-scale-" + id).value);
          if (!qwenReason && !box.disabled && box.checked && !(Number.isFinite(s) && s > 0 && s <= 2)) {
            qwenReason = "LoRA " + seedLoraEntry(id).label + " strength must be above 0 and at most 2";
          }
        });
      }
    }
```

with:

```js
    let qwenReason = ""; if (model === "qwen" && models) { qwenReason = SEED_PICKER.reason(); }
```

Edit `static/movie-ui/app.js` (QE64): replace this text, which occurs exactly once:

```js
            qwen_model: model === "qwen" ? S.seeds.qwen.model : null, loras: model === "qwen" ? seedLoraBody() : null};
```

with:

```js
            qwen_model: model === "qwen" ? SEED_PICKER.selection().model : null, loras: model === "qwen" ? SEED_PICKER.selection().loras : null};
```

Edit `static/movie-ui/app.js` (QE67): replace this text, which occurs exactly once:

```js
  function composeFields(action) {
```

with:

```js
  function composeSeedEditActive() {
    const supported = (S.options && S.options.supported) || {};
    return supported.seed_edit !== false && $("#c-mode").value === "chained"
      && (($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked);
  }

  // Qwen edit models spec QE67: a Seeds-tab "Use" seed defaults to as-is, an upload or a seed folder to the
  // registry default (qwen21-q4 + its default LoRAs). The origin is kept in S.seedOrigin.
  function composeSeedDefault(origin) {
    S.seedOrigin = origin;
    if (origin === "seeds") { COMPOSE_PICKER.select("as-is", []); }
    else { COMPOSE_PICKER.select(null, null); }
  }

  function composeFields(action) {
```

Edit `static/movie-ui/app.js` (QE67): replace this text, which occurs exactly once:

```js
    const goal = textOrNull("#c-goal");
    return {
```

with:

```js
    const goal = textOrNull("#c-goal");
    const seedEdit = composeSeedEditActive() ? COMPOSE_PICKER.selection() : null;
    return {
```

Edit `static/movie-ui/app.js` (QE67): replace this text, which occurs exactly once:

```js
      seed_upload: bySeed ? S.seedUpload : null,
```

with:

```js
      seed_upload: bySeed ? S.seedUpload : null,
      seed_edit_model: seedEdit ? seedEdit.model : null, seed_edit_loras: seedEdit && seedEdit.model !== "as-is" ? seedEdit.loras : null,
```

Edit `static/movie-ui/app.js` (QE67): replace this text, which occurs exactly once:

```js
    show($("#c-check-seams-box"), mode === "chained");
```

with:

```js
    show($("#c-check-seams-box"), mode === "chained");
    COMPOSE_PICKER.update();
    const seedEditOn = composeSeedEditActive();
    show($("#c-sq-qwen-box"), seedEditOn);
    const seedEditReason = seedEditOn ? COMPOSE_PICKER.reason() : "";
    $("#c-sq-reason").textContent = seedEditReason;
    if (seedEditReason) {
      $("#c-run-all").disabled = true;
      const runReason = $("#c-run-all-reason");
      runReason.textContent = runReason.textContent ? runReason.textContent + "; " + seedEditReason : seedEditReason;
    }
```

Edit `static/movie-ui/app.js` (QE67, `onSeedFile`): replace this text, which occurs exactly once:

```js
      $("#c-seed-status").textContent = "uploaded " + S.seedUpload.slice(0, 12);
      $("#c-res-seed").checked = true;
```

with:

```js
      $("#c-seed-status").textContent = "uploaded " + S.seedUpload.slice(0, 12);
      $("#c-res-seed").checked = true;
      composeSeedDefault("upload");
```

Edit `static/movie-ui/app.js` (QE67, `onFolderPick`): replace this text, which occurs exactly once:

```js
      box.select();
```

with:

```js
      box.select();
      if (box === FOLDER_BOXES.compose) { composeSeedDefault("folder"); }
```

Edit `static/movie-ui/app.js` (QE67, `fillCompose`): replace this text, which occurs exactly once:

```js
    $("#c-res-size").checked = !S.seedUpload;
```

with:

```js
    $("#c-res-size").checked = !S.seedUpload;
    S.seedOrigin = "job";
    COMPOSE_PICKER.select(f.seed_edit_model || "as-is", f.seed_edit_loras || []);
```

Edit `static/movie-ui/app.js` (QE67, `setupCompose`): replace this text, which occurs exactly once:

```js
    $("#c-seed-file").addEventListener("change", onSeedFile);
```

with:

```js
    $("#c-seed-file").addEventListener("change", onSeedFile);
    COMPOSE_PICKER.listen(function () { updateComposeButtons(); preview(); });
```

Edit `static/movie-ui/app.js` (QE67, `useSeed`): replace this text, which occurs exactly once:

```js
    S.seedUpload = uploadId;
```

with:

```js
    S.seedUpload = uploadId;
    composeSeedDefault("seeds");
```

Edit `static/movie-ui/app.js` (QE66, `openCharacter`): replace this text, which occurs exactly once:

```js
    $("#ch-status").textContent = res.data.face_problem ? "the last create refused the seed face" : "";
    updateCharacterButtons();
```

with:

```js
    $("#ch-status").textContent = res.data.face_problem ? "the last create refused the seed face" : "";
    if (res.data.character.source.type === "seed_image") {
      const e = res.data.character.edit;
      CHARACTER_REGEN_PICKER.select(e ? e.qwen_model.id : "qwen2511-bf16", e ? e.loras.map(function (l) { return {id: l.id, scale: l.scale}; }) : []);
    }
    updateCharacterButtons();
```

Edit `static/movie-ui/app.js` (QE66, `updateCharacterButtons`): replace this text, which occurs exactly once:

```js
      $("#ch-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
```

with:

```js
      $("#ch-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
    const seedOn = FOLDER_BOXES.characters.mode() || $("#ch-seed-file").files.length > 0;
    CHARACTER_PICKER.update();
    show($("#ch-cq-qwen-box"), seedOn);
    const createReason = seedOn ? CHARACTER_PICKER.reason() : "";
    $("#ch-cq-reason").textContent = createReason;
    if (createReason) { $("#ch-create").disabled = true; }
    const seedCharacter = Boolean(S.character && S.character.character.source.type === "seed_image");
    CHARACTER_REGEN_PICKER.update();
    show($("#ch-rq-qwen-box"), seedCharacter);
    const regenReason = seedCharacter ? CHARACTER_REGEN_PICKER.reason() : "";
    $("#ch-rq-reason").textContent = regenReason;
    $("#ch-regenerate").disabled = Boolean(regenReason);
```

Edit `static/movie-ui/app.js` (QE66, `createCharacter`'s folder base): replace this text, which occurs exactly once:

```js
    if (!force && FOLDER_BOXES.characters.mode()) { openFolderConfirm(FOLDER_BOXES.characters, {ws: S.ws, name: $("#ch-name").value.trim(), phrase: $("#ch-phrase").value.trim(), seed: numberOrNull("#ch-seed")}); return; }
```

with:

```js
    if (!force && FOLDER_BOXES.characters.mode()) { openFolderConfirm(FOLDER_BOXES.characters, {ws: S.ws, name: $("#ch-name").value.trim(), phrase: $("#ch-phrase").value.trim(), seed: numberOrNull("#ch-seed"), qwen_model: CHARACTER_PICKER.selection().model, loras: CHARACTER_PICKER.selection().loras}); return; }
```

Edit `static/movie-ui/app.js` (QE66, `createCharacter`'s single-seed body): replace this text, which occurs exactly once:

```js
              trigger: textOrNull("#ch-trigger"), seed: numberOrNull("#ch-seed"), seed_upload: seed, force: false};
```

with:

```js
              trigger: textOrNull("#ch-trigger"), seed: numberOrNull("#ch-seed"), seed_upload: seed, force: false,
              qwen_model: file ? CHARACTER_PICKER.selection().model : null, loras: file ? CHARACTER_PICKER.selection().loras : null};
```

Edit `static/movie-ui/app.js` (QE66, `setupCharacters`): replace this text, which occurs exactly once:

```js
    $("#ch-folder-mode").addEventListener("change", updateCharacterButtons);
```

with:

```js
    $("#ch-folder-mode").addEventListener("change", updateCharacterButtons);
    CHARACTER_PICKER.listen(updateCharacterButtons);
    CHARACTER_REGEN_PICKER.listen(updateCharacterButtons);
    $("#ch-seed-file").addEventListener("change", updateCharacterButtons);
```

Edit `static/movie-ui/app.js` (QE66, `#ch-regenerate`): replace this text, which occurs exactly once:

```js
      const res = await api("POST", "/api/characters/" + enc(name) + "/regenerate",
                            withSeed ? {ws: S.ws, seed: seedValue} : {ws: S.ws});
```

with:

```js
      const body = withSeed ? {ws: S.ws, seed: seedValue} : {ws: S.ws};
      if (S.character.character.source.type === "seed_image") {
        const pick = CHARACTER_REGEN_PICKER.selection();
        body.qwen_model = pick.model;
        body.loras = pick.loras;
      }
      const res = await api("POST", "/api/characters/" + enc(name) + "/regenerate", body);
```

Edit `static/movie-ui/app.js` (QE65, `openLocation`): replace this text, which occurs exactly once:

```js
    $("#lo-status").textContent = "";
    updateLocationButtons();
  }
```

with:

```js
    $("#lo-status").textContent = "";
    if (loc.source === "photos") {
      const e = loc.edit;
      LOCATION_REGEN_PICKER.select(e ? e.qwen_model.id : "qwen2511-bf16", e ? e.loras.map(function (l) { return {id: l.id, scale: l.scale}; }) : []);
    }
    updateLocationButtons();
  }
```

Edit `static/movie-ui/app.js` (QE65, `updateLocationButtons`): replace this text, which occurs exactly once:

```js
      $("#lo-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
  }
```

with:

```js
      $("#lo-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
    const photosOn = photos > 0;
    LOCATION_PICKER.update();
    show($("#lo-cq-qwen-box"), photosOn);
    const createReason = photosOn ? LOCATION_PICKER.reason() : "";
    $("#lo-cq-reason").textContent = createReason;
    if (createReason) { $("#lo-create").disabled = true; }
    const photoLocation = Boolean(S.location && S.location.location.source === "photos");
    LOCATION_REGEN_PICKER.update();
    show($("#lo-rq-qwen-box"), photoLocation);
    const regenReason = photoLocation ? LOCATION_REGEN_PICKER.reason() : "";
    $("#lo-rq-reason").textContent = regenReason;
    $("#lo-regen").disabled = Boolean(regenReason);
  }
```

Edit `static/movie-ui/app.js` (QE65, `createLocation`): replace this text, which occurs exactly once:

```js
      seed: numberOrNull("#lo-seed"), force: false});
```

with:

```js
      seed: numberOrNull("#lo-seed"), force: false,
      qwen_model: uploads.length ? LOCATION_PICKER.selection().model : null, loras: uploads.length ? LOCATION_PICKER.selection().loras : null});
```

Edit `static/movie-ui/app.js` (QE65, `#lo-regen`): replace this text, which occurs exactly once:

```js
      const res = await api("POST", "/api/locations/" + enc(name) + "/regenerate",
                            {ws: S.ws, new_seed: true, force: $("#lo-force").checked});
```

with:

```js
      const body = {ws: S.ws, new_seed: true, force: $("#lo-force").checked};
      if (S.location.location.source === "photos") {
        const pick = LOCATION_REGEN_PICKER.selection();
        body.qwen_model = pick.model;
        body.loras = pick.loras;
      }
      const res = await api("POST", "/api/locations/" + enc(name) + "/regenerate", body);
```

Edit `static/movie-ui/app.js` (QE65, `setupLocations`): replace this text, which occurs exactly once:

```js
    $("#lo-photos").addEventListener("change", updateLocationButtons);
```

with:

```js
    $("#lo-photos").addEventListener("change", updateLocationButtons);
    LOCATION_PICKER.listen(updateLocationButtons);
    LOCATION_REGEN_PICKER.listen(updateLocationButtons);
```

- [ ] **Step 4: Run the tests; verify they pass.**

Run: `cd $S/qem-wt/qwen-agent-workspace && python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_batch.py tests/test_movie_ui_seams.py tests/test_movie_ui_http.py tests/test_vlm_lifecycle.py 2>&1 | tail -1 && node --check static/movie-ui/app.js && echo "node check ok"`
Expected: `N passed` with no failure; `node check ok`.

Run the compile check with `FILES` = `tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py`. Expected: `compiled 2` twice.

- [ ] **Step 5: The gate.** Run the gate block with `N=7`. Expected: `GATE PASS`, `lost 1 (listed 1, unexpected 0); new tests 49, not passing 0; baseline failures still failing 2 of 2` (the one listed loss is the expected failure `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`; the 2 new tests are QET38, QET39), `disk ok`, `offline unchanged`.

- [ ] **Step 6: Commit.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only    # expected: exactly those four paths
git commit -m "movie-ui page: one Qwen edit model picker on Seeds, Locations, Characters and Compose (qwen edit models QE61-QE68, QET38, QET39)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git rev-parse HEAD    # record this 40-character SHA for Task 8
```

---

### Task 8: The `test_mut26` re-baseline, a test-only commit (spec 13.3, D17)

This task moves `test_mut26_pipeline_files_are_unchanged`'s `BASELINE` to the last implementation commit (Task 7's, recorded at its Step 6; no pinned file changed after Task 5, so it is also a commit after every pinned-file change) and extends the comment's chain. Nothing else in the file changes, and the commit stages only that file (spec 13.3 items 2-3). If a later review fix touches a pinned file, add a new test-only baseline commit the same way; never amend.

**Files:**
- Modify: `tests/test_movie_ui_builder.py` (`test_mut26`'s comment line `:288` and `BASELINE` `:290`).

**Interfaces:** none (test-only).

- [ ] **Step 1: Take the SHA and check the pinned files (spec 13.3 item 1).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD); echo $SHA
git log -1 --format=%s                         # expected: movie-ui page: one Qwen edit model picker ... (Task 7)
P="bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py"
git diff --quiet $SHA -- $P && echo "pipeline files clean at SHA"
git diff --name-only a62d477 $SHA -- $P
```

Expected: a 40-hex `SHA`; `pipeline files clean at SHA`; exactly `qwen-agent-workspace/bin/character`, `qwen-agent-workspace/bin/ltx-movie`, `qwen-agent-workspace/character_dataset.py`, `qwen-agent-workspace/character_lib.py` (in that order). Anything else: stop and report.

- [ ] **Step 2: Edit the comment.** Type the 40 characters of `SHA` (Step 1) in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```text
    # 6a0b3035bdf3f6eb20833372436fd5e64af1f67b (panel-1 pacing instruction reworded), then to e25f58f5103ae1f703ab135a00a5d51b664b8124 (VLM lifecycle + panel-1 pacing), then to 75d914b9d128434b9fa0ac25cf0482e6f9b5ca7a (character_dataset.py: regenerate with a new seed), then to 5903089fe272c03933d31ca4af105c4aec42b823 (the seed is persisted under the library lock after the preflights), then to ac23105738adee0b26ea9d391681f3abbaa26ab0 (narrative dialogue fidelity), then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence), then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution), then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format), then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count), then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library), then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames).
```

with:

```text
    # 6a0b3035bdf3f6eb20833372436fd5e64af1f67b (panel-1 pacing instruction reworded), then to e25f58f5103ae1f703ab135a00a5d51b664b8124 (VLM lifecycle + panel-1 pacing), then to 75d914b9d128434b9fa0ac25cf0482e6f9b5ca7a (character_dataset.py: regenerate with a new seed), then to 5903089fe272c03933d31ca4af105c4aec42b823 (the seed is persisted under the library lock after the preflights), then to ac23105738adee0b26ea9d391681f3abbaa26ab0 (narrative dialogue fidelity), then to cf0a0e684ea4f9ca09f7e7d45dc0e33544242971 (writer pacing), then to 05ba1792b7e1620f96b1e50ba5a83f6349620529 (pinned cast presence), then to f7a38afc6d6ae9622b63dbf4ce939e362a05a7ad (speaker attribution), then to 42f33640cd008021a32dc0f8f948d0e8da04de2b (shot prompt format), then to ff757afbc0a801f2029628871c684ce4d98b4811 (soft panel count), then to 44beb3d67ad5af05093e29e1c6fc088330b41386 (location library), then to 38005c3bfee25daf73da231692609fc0b8d25892 (chained end frames), then to SHA (qwen-edit-models).
```

- [ ] **Step 3: Edit `BASELINE`.** Type `SHA` in place of the word `SHA`.

Edit `tests/test_movie_ui_builder.py`: replace this text, which occurs exactly once:

```python
    BASELINE = "38005c3bfee25daf73da231692609fc0b8d25892"
```

with:

```python
    BASELINE = "SHA"
```

- [ ] **Step 4: Verify.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                    # expected: 1
grep -c "(chained end frames), then to $SHA (qwen-edit-models)\.$" tests/test_movie_ui_builder.py   # expected: 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1                                         # expected: 1 file changed, 2 insertions(+), 2 deletions(-)
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py 2>&1 | tail -1            # expected: N passed, no failure
```

Then run the gate block with `N=8`. Expected: `GATE PASS`, `lost 0 (listed 0, unexpected 0); new tests 49, not passing 0; baseline failures still failing 2 of 2`, `disk ok`, `offline unchanged`; and `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/task-8-pytest.txt` prints `1`.

- [ ] **Step 5: Commit (test-only, one file).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/qem-wt/qwen-agent-workspace
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # expected: exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the last qwen-edit-models implementation commit (spec 13.3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Verification (controller only; not an implementer task)

The controller runs these after Task 8, in spec 13.1's order: the pass bar (V1), the browser check (V2), the Opus design review (V3); the live checks (V4) are the user's, on macstudio. Every rule of "Global Constraints" applies. A finding is fixed in a new commit on the owning task's files; if that commit touches a pinned file, a new Task 8-style test-only baseline commit follows; then V1 reruns.

- [ ] **V1: The pass bar, spec 13.1 items 2-4 (about 19 minutes).**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/qem-baseline
cd $S/qem-wt/qwen-agent-workspace
df -g . | tail -1
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt; tail -1 $D/final-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/final-pytest.txt $D/expected-failures.txt 8
diff <(grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt | sort) <(grep -E '^(FAILED|ERROR)' $D/final-pytest.txt | sort) && echo "same failures, same messages"
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1
git diff --stat a62d477..HEAD -- bin/ltx-story-images story_engine.py bin/seed-edit-setup content_safety.py z_image_skill.py mps_guard.py movie_ui_seedfolder.py scripts/deploy/build_pkg.py static/movie-ui/app.css tests/movie_ui_testutil.py | tail -1
git diff --name-only a62d477..HEAD | wc -l
git diff a62d477..HEAD -- movie_ui_lib.py movie_ui_server.py | grep -E '^\+(import|from) ' || echo "movie-ui imports unchanged (QE2)"
git diff a62d477..HEAD -- tests/ | grep -E '^\+' | grep -nE "expanduser\(|urlopen|import requests|zshenv|fleet\.env|macstudio|127\.0\.0\.1:81|HF_TOKEN\"\]" || echo "no real HOME, HTTP client, private host, model-server address or real token in the new tests"
git ls-files -s bin/seed-edit bin/location bin/character bin/ltx-movie | cut -c1-6 | sort -u
```

Expected, in order:
- at least 20 GiB available (QEK9);
- the final summary is the baseline's with the pass count higher by exactly 49 (`2 failed, <P0 + 49> passed, 2 skipped`);
- `lost 0 (listed 0, unexpected 0); new tests 49, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS`;
- `same failures, same messages` (QEK1); `OK 347/347` (QEK2);
- no output from the untouched-files `--stat` (spec 0.2);
- `34` (the spec, the plan, and the 32 files of the File Structure table, the help fixture included);
- `movie-ui imports unchanged (QE2)`; the "no real HOME ..." line; `100755` once.

- [ ] **V2: The browser check (spec 11.4), on a throwaway demo; never committed.**

Write `$S/qemdemo/demo.py` with the Write tool (a scratch file outside the repository), exactly:

```python
"""Throwaway demo server for the qwen edit models browser check (spec 11.4; never committed).

Run: python3 -B $S/qemdemo/demo.py (kill $(cat $S/qemdemo/pid) stops it). It never calls start_threads, so no
job ever runs. The page URL, with this run's throwaway token, goes to $S/qemdemo/url.txt (mode 0600) and is
never printed. The static files are copied fresh from the worktree on every start. The stub probe answers in
seed models SQ18's shape: qwen21-q4, qwen2511-q4 and uncensored ok; qwen21-q8 and viggle-turbo not installed;
qwen21-bf16 and qwen2511-bf16 below their memory floors. The stub bin/ltx-movie --help prints the current help
fixture (which lists --seed-edit-model). The real bin/location and bin/character list and show the demo
libraries: old-mill (photos, edit qwen21-q4 + uncensored 0.5), temple-gate (photos, made before this
feature), harbour-street (text); kyra (seed image, edit qwen21-q4 + uncensored 1), ronin (descriptor).
"""
import json
import os
import secrets
import shutil
import sys

S = "/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad"
WS = S + "/qem-wt/qwen-agent-workspace"
DEMO = S + "/qemdemo"
OLD_RUN = "se-20261102-120000-0001"
os.environ["HOME"] = DEMO + "/home"
os.environ["MOVIE_UI_VLM_LIFECYCLE"] = "0"
os.environ["MOVIE_UI_VLM_TOOLS"] = DEMO + "/no-tools"
os.environ["MOVIE_UI_VLM_PORT"] = "9"
os.environ["LOCATION_LIBRARY_DIR"] = DEMO + "/locations"
os.environ["CHARACTER_LIBRARY_DIR"] = DEMO + "/characters"
for key in list(os.environ):
    if key.startswith("SEED_EDIT_"):
        del os.environ[key]
os.makedirs(os.environ["HOME"], exist_ok=True)
sys.path.insert(0, WS + "/tests")
import movie_ui_testutil as mt  # noqa: E402  (puts WS on sys.path)
import location_testutil as lt  # noqa: E402
import movie_ui_lib as lib  # noqa: E402
import movie_ui_seedgen as seedgen  # noqa: E402
import movie_ui_server as srv  # noqa: E402
import qwen_edit  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def picture(path, size, back, front):
    """A real image: a background with a centred rectangle."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", size, back)
    w, h = size
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], fill=front)
    img.save(path)


def character(lib_dir, name, source, edit=None):
    """A valid untrained character.json under lib_dir/name (character library spec 2.2 shape)."""
    cdir = os.path.join(lib_dir, name)
    os.makedirs(os.path.join(cdir, "dataset"), exist_ok=True)
    data = {"schema_version": 1, "name": name, "trigger": name + "trg", "class_noun": "person",
            "referring_phrase": "the " + name, "seed": 0, "source": source, "strength": None,
            "descriptor": "an old man with a white beard wearing a saffron robe and beads", "status": "untrained",
            "created_at": "2026-11-03T10:00:00Z", "loras": {"video": None, "stills": None},
            "dataset": {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7, "face_height": 0.38,
                        "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")},
            "stills_skip_reason": None}
    if edit is not None:
        data["edit"] = edit
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


state = lib.state_dir()
lib.ensure_state(state)
ws = mt.make_stub_workspace(DEMO)
static = os.path.join(ws, "static", "movie-ui")
shutil.rmtree(static, ignore_errors=True)
shutil.copytree(os.path.join(WS, "static", "movie-ui"), static)
for rel in ("bin/location", "bin/character", "location_lib.py", "character_lib.py"):
    shutil.copy2(os.path.join(WS, rel), os.path.join(ws, rel))

hubs = "<zhub> or <dhub>"
models = {
    "qwen21-q4": {"ok": True, "reason": None},
    "qwen21-q8": {"ok": False, "reason": "mflux-community/qwen-image-2-1-mflux-q8@f5c8cc79a674 is not in %s "
                                         "(run bin/seed-edit-setup --model qwen21-q8)" % hubs},
    "qwen21-bf16": {"ok": False, "reason": "needs a host with at least 56 GiB of memory (this host has 48.0 GiB)"},
    "qwen2511-q4": {"ok": True, "reason": None},
    "qwen2511-bf16": {"ok": False, "reason": "needs a host with at least 64 GiB of memory (this host has 48.0 GiB)"}}
loras = {"uncensored": {"ok": True, "reason": None},
         "viggle-turbo": {"ok": False, "reason": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is "
                                                 "not in %s (run bin/seed-edit-setup --lora viggle-turbo)" % hubs}}
probe = {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
         "qwen": {"ok": True, "reason": None, "models": models, "loras": loras}}
models_path = os.path.join(DEMO, "models.json")
with open(models_path, "w", encoding="utf-8") as f:
    json.dump(probe, f)
stub = os.path.join(ws, "bin", "seed-edit")
with open(stub, "w", encoding="utf-8") as f:
    f.write("#!%s\nimport sys\nif sys.argv[1:] == ['--probe']:\n"
            "    sys.stdout.write(open(%r, encoding='utf-8').read().strip() + '\\n')\n" % (sys.executable, models_path))
os.chmod(stub, 0o755)

locations, characters = os.environ["LOCATION_LIBRARY_DIR"], os.environ["CHARACTER_LIBRARY_DIR"]
if not os.path.isdir(locations):
    mill = lt.mill(locations, status="untrained", source="photos")
    mill["edit"] = qwen_edit.settings("qwen21-q4", [{"id": "uncensored", "scale": 0.5}])
    with open(os.path.join(locations, "old-mill", "location.json"), "w", encoding="utf-8") as f:
        json.dump(mill, f, indent=2)
    lt.temple(locations, status="untrained", source="photos")
    lt.harbour(locations, status="untrained")
if not os.path.isdir(characters):
    character(characters, "kyra", {"type": "seed_image", "path": DEMO + "/seed-768x1024.png"},
              qwen_edit.settings("qwen21-q4", [{"id": "uncensored", "scale": 1.0}]))
    character(characters, "ronin", {"type": "descriptor"})

run_dir = os.path.join(ws, "generated", "seeds", "runs", OLD_RUN)
if not os.path.isdir(run_dir):
    picture(os.path.join(run_dir, "source.png"), (1024, 672), (30, 90, 160), (250, 250, 250))
    picture(os.path.join(run_dir, "cand_01.png"), (1024, 672), (20, 30, 60), (250, 160, 40))
    lib.write_json_atomic(os.path.join(run_dir, "run.json"), {
        "schema": "seed-edit.run.v1", "run": OLD_RUN, "created": "2026-11-02T12:00:00Z", "state": "done",
        "prompt": "the same street at night, wet cobblestones", "model": "qwen", "backend": "mflux-q4",
        "strength": None, "seed": 41, "size": {"width": 1024, "height": 672},
        "source_size": {"width": 1024, "height": 672}, "source": "source.png", "source_origin": None,
        "job": None, "error": None,
        "candidates": [{"n": 1, "seed": 42, "status": "ok", "seconds": 61.2},
                       {"n": 2, "seed": 43, "status": "blocked", "seconds": 9.8}]})
picture(os.path.join(DEMO, "upload-800x600.png"), (800, 600), (90, 140, 90), (250, 250, 120))
picture(os.path.join(DEMO, "photo-800x500.png"), (800, 500), (120, 100, 80), (200, 200, 220))
picture(os.path.join(DEMO, "seed-768x1024.png"), (768, 1024), (60, 60, 90), (230, 200, 170))

stills_ok = os.path.join(DEMO, "stills-ok")
with open(stills_ok, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nexit 0\n")
os.chmod(stills_ok, 0o755)
server = srv.make_server(0, state, ws, secrets.token_urlsafe(32))
assert server.port not in (8177, 8178, 8999), server.port
server.probe_ws = ws
server.stills_py = stills_ok
checked = lib.utc_now()
for key in ("render", "stills", "story_server"):
    server.capabilities[key] = {"ok": True, "reason": None, "checked": checked}
found, detail = lib.seed_edit_check(ws, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
assert found is not None, detail
server.capabilities["seed_edit"] = seedgen.capability(found, detail, checked)
url_path = os.path.join(DEMO, "url.txt")
fd = os.open(url_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("http://127.0.0.1:%d/?t=%s\n" % (server.port, server.token))
with open(os.path.join(DEMO, "pid"), "w", encoding="utf-8") as f:
    f.write("%d\n" % os.getpid())
print("demo serving on 127.0.0.1:%d; open the URL in %s" % (server.port, url_path))
sys.stdout.flush()
server.serve_forever()
```

Run it in the background: `python3 -B $S/qemdemo/demo.py`. It prints only the port and the path of `url.txt`; open the URL from that file in a browser (the token stays in the file, never in a terminal or a message). Pick `$S/qemdemo/ws` as the workspace (the typed path). A queued job's argv is read with `python3 -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["argv"])' $S/qemdemo/home/.local/share/qwen-agent/movie-ui/jobs/<job id>/job.json` (the demo never dispatches it). Check spec 11.4's items and record pass or the exact difference per item:

1. **Seeds:** the seed models plan's V2 items (spec [SQ] 9.5 cases 1-8) still pass: the Qwen box shows `Qwen-Image-2.1 q4` with Uncensored at 1 and `40 steps`; `Qwen-Image-2.1 q8 — unavailable` and the two memory-limited entries are disabled with the `Unavailable here: ...` list; Viggle's row is disabled with its setup reason; `upload-800x600.png` shows `800 × 600 → 800 × 576` on 2.1 and `→ 800 × 592` on 2511 q4; the old run `se-20261102-120000-0001` opens as `qwen2511-q4` with 8 steps.
2. **Locations:** choosing `photo-800x500.png` shows the create picker at `Qwen-Image-2.1 q4`, Uncensored at 1, `40 steps`; Create queues a job whose argv ends `--qwen-model qwen21-q4 --lora uncensored=1.0`. Opening `old-mill` shows the Regenerate picker at q4 with Uncensored at 0.5. Opening `temple-gate` preselects `qwen2511-bf16`, which this probe disables, so the picker shows the fallback `Qwen-Image-2.1 q4` with Uncensored unchecked and an empty reason line. `harbour-street` shows no Regenerate picker; the create picker hides again when the photos are cleared.
3. **Characters:** choosing a seed file (`seed-768x1024.png`) shows the create picker; ticking the seed-folder box shows it too; `kyra`'s detail preselects q4 with Uncensored at 1; `ronin` shows no Regenerate picker.
4. **Compose:** Seeds → a candidate of the old run → Use: the Compose picker shows `Seed as-is (no edit)` and the preview command has `--seed-edit-model as-is`; uploading `upload-800x600.png` as the seed switches it to `Qwen-Image-2.1 q4` + Uncensored and the command has `--seed-edit-model qwen21-q4 --seed-edit-lora uncensored=1.0`; `Qwen-Image-2.1 q8 — unavailable` cannot be chosen; Mode `shots` or the Size radio hides the picker (and the flags leave the command). Then make the stub help lack the flags and reload: `python3 -B -c 'import json,os,sys; json.dump({"ltx-movie --help": {"stdout": open(sys.argv[2]).read()}}, open(os.path.join(sys.argv[1], "stub_config.json"), "w")); os.utime(os.path.join(sys.argv[1], "bin", "ltx-movie"))' $S/qemdemo/ws $S/qem-wt/qwen-agent-workspace/tests/fixtures/movie_ui/ltx-movie-help-old.txt`: the picker's wrapper is hidden and the command has no seed-edit flag. Undo with `rm $S/qemdemo/ws/stub_config.json` (a scratch file outside the repository) and the same `os.utime`.
5. The browser console shows no error on any tab.

Stop the demo with `kill $(cat $S/qemdemo/pid)`.

- [ ] **V3: The design review.** An Opus `design-reviewer` reviews `git diff c86808a..HEAD` against the spec, the load-bearing properties first: content safety on every output of every path (QEK5; QET5, QET7, QET29), no token in the mflux child (QET4), Seeds unchanged (QET12), default `bin/ltx-movie` byte-identical (QET26, QET31, `OK 347/347`), the legacy routes byte-identical (QET7, QET18), and the plan rulings R1-R16. A finding is fixed as described above.

- [ ] **V4: The live checks (spec 12), run by the user on macstudio.** The agent never connects to macstudio. Record M0 and rows L1-L4 as "not run (awaiting the user)" until the user pastes the figures back; then record each row's figures and pass or fail per spec 12 (QEK6-QEK8). Open questions 1-4 of the spec are decided by the user from that record. Push and merge only on the user's go (spec 13.1 item 6).

---

## Coverage

### Spec requirements → task

| Requirement | Task | Where |
|---|---|---|
| QE1, QE5-QE16 | 1 | `qwen_edit.py` (QE14 plus R4's cleanup) |
| QE2 | 6 | `movie_ui_lib.py`, `movie_ui_server.py` gain no `qwen_edit` import (V1 checks) |
| QE3 | 2, 3, 4, 5 | the four callers' imports or loader |
| QE4 | 1, 3 | `run_jobs`' diffusers branch; `run_edit_child`'s unchanged legacy body |
| QE17, QE18 | 1 | `seed_edit_mflux_child.py` |
| QE19-QE23 | 2 | `bin/seed-edit` |
| QE24 | 4 | `bin/location` |
| QE25-QE30 | 4 | `location_dataset.py` |
| QE31 | 4 | `location_lib.py` |
| QE32 | 3 | `bin/character` |
| QE33-QE37 | 3 | `character_dataset.py` |
| QE38, QE39 | 3 | `character_lib.py`; `_regenerate` unchanged (the record lives outside `dataset/`) |
| QE40-QE50 | 5 | `bin/ltx-movie` (R1, R2) |
| QE51 | 6 | `movie_ui_seedgen.py` |
| QE52-QE54, QE69 | 6 | `movie_ui_lib.py` |
| QE55-QE59 | 6 | `movie_ui_server.py` (R11) |
| QE60 | 6 | `movie_ui_batch.py` |
| QE61-QE68 | 7 | `index.html`, `app.js` |
| QE70 | 1, 5, 6 | `NEW_PY` (R6) |
| §11.3 | 1 (stub `silent`), 2, 3, 4, 6, 7 | see the next table |
| §13.3, D17 | 8 | `test_mut26` |
| §11.4, §12, §13.1 | Verification | V1-V4 |

### Spec tests → test

| ID | Test (file) | Task |
|---|---|---|
| QET1-QET11 | `test_qet1_cli_selection` ... `test_qet11_imports_and_the_new_files` (`tests/test_qwen_edit.py`) | 1 |
| QET12 | `test_qet12_the_tool_on_qwen_edit_behaves_as_before[case1-6]` (`tests/test_seed_edit_tool.py`) | 2 |
| QET13, QET14, QET16, QET17 | `test_qet13_...`, `test_qet14_...`, `test_qet16_...`, `test_qet17_...` (`tests/test_location_dataset.py`) | 4 |
| QET15 | `test_qet15_the_optional_edit_key` (`tests/test_location_lib.py`) | 4 |
| QET18 | `test_qet18_run_edit_child_routes_by_the_edit_key` (`tests/test_location_dataset.py`) | 3 |
| QET19 | `test_qet19_the_create_options` (`tests/test_location_tool.py`) | 4 |
| QET20-QET22 | `test_qet20_...`, `test_qet21_...`, `test_qet22_...` (`tests/test_character_tool.py`) | 3 |
| QET23 | `test_qet23_the_optional_edit_key` (`tests/test_character_lib.py`) | 3 |
| QET24, QET25 | `test_qet24_...`, `test_qet25_...` (`tests/test_character_dataset.py`) | 3 |
| QET26-QET32 | `test_qet26_...` ... `test_qet32_...` (`tests/test_ltx_movie_seed_edit.py`) | 5 |
| QET33-QET37 | `test_qet33_...` ... `test_qet37_...` (`tests/test_movie_ui_qwen_edit.py`) | 6 |
| QET38, QET39 | `test_qet38_the_picker_on_the_page`, `test_qet39_the_compose_defaults_and_fields` (same file) | 7 |
| Review Focus 1-5 | `test_qe_review_focus_1_...` (Task 1), `_2_...` (Task 2), `_3_...` (Task 4), `_4_...`, `_5_...` (Task 6) | 1, 2, 4, 6 |

### Spec 11.3's edits of existing tests → task

| §11.3 row | Task |
|---|---|
| `tests/test_seed_edit_tool.py` `env` fixture, every moved name (`bf16_cache`, SGT7, SGT10, SGT11, SGT13, SGT14, SQT3-SQT7, SQT9, SQT10, Seeds review focus 4, `test_sq_final_b`), SQT3's grep, SQT5/SGT9 dicts (R8), SGT10's `JOB_TIMEOUT_S`, the `test_sq_final_b` spy | 2 |
| `MFLUX_STUB`'s `silent` key (spec 11.1) | 1 |
| `tests/test_movie_ui_seedgen.py` SQT18, SGT34 | 2 |
| SGT33 `SEED_FUNCTIONS`, SQT22 `QWEN_JS_TEXTS`, `test_sq_final_d_e_f_page_guards` | 7 |
| `tests/test_character_tool.py` `_Fakes`, K19 | 3 |
| `tests/test_location_dataset.py` `_Fakes`, the old-mill block; `tests/test_location_tool.py` fakes | 4 |
| `tests/test_location_ui.py:267`, `tests/test_movie_ui_builder.py:137`, `tests/test_movie_ui_batch.py:78` and `EXPECTED_LEVELS` | 6 |
| `NEW_PY` | 1, 5, 6 |
| Beyond §11.3 (rulings R3, R15): K23, LD10; the help fixture, `test_mut3`, `test_mu14` | 3, 4, 6 |

## Spec gaps found (for the spec author)

1. **[R1] `import hashlib` at the top of `bin/ltx-movie` breaks `test_dk3_import_sets_are_unchanged`** (a baseline pass §11.3 does not list). The plan imports it inside `phase_seed_edit`.
2. **[R2] QE49/QE50 as written break `tests/test_ltx_movie_offline.py` L29d** (QEK2's `OK 347/347`), which counts the two `--seed-image` literals. The plan keeps the literals and replaces the appended path.
3. **[R3] K23 and LD10 pin today's missing-editor refusal with no model option;** under the new default they would test nothing. The plan passes `qwen2511-bf16` explicitly.
4. **[R4] QE13's contract and QE14's typed body disagree** about a `failed` job's stage file. The plan follows the contract (four added lines), which matters for Locations and Characters, whose stage files sit in `stills/`.
5. **[R15] §11.3 misses `test_mu14_ws_parameter_errors_and_options`** (`all(supported)` and the count 30 against the "current" help fixture). The plan follows the location library's precedent: re-capture the fixture with the two flags and re-baseline `test_mut3` and `test_mu14`.
6. **QET15's byte-identity check of `_edit_problem` cannot pass until both libraries carry it;** with Characters first (R7), QET23 ships in Task 3 and the check ships with QET15 in Task 4.
7. **A Compose 409 from `_h_job_create` carries no `checks`** (`ApiError(409, text)`), and the page's `submit` shows only `res.data.checks` on a 409, so a seed-edit 409 shows no message on the Compose tab. The page's picker gate makes this rare (an unavailable model is not selectable), but a probe that changes between the gate and the submit would show nothing. Not changed (QE57 is explicit).
8. **`qwenPicker`'s `render` throws when the wanted model is not in the registry** (`enabled(id)` is true for an unknown ID, then `seedQwenEntry(chosen).family` is read from `null`). A `location.json`/`character.json` `edit` naming a model a later registry drops would break that tab's buttons. QE61 is "typed as written", so not changed.
9. **Phase 1c screens in the `bin/ltx-movie` process,** so `content_safety` imports torch and keeps its classifier resident through Phases 2-4 (QE14's mflux branch screens in the parent). The render's memory budget does not account for it; L3 will show whether it matters.
10. **`character_dataset.py`'s module docstring still says its top level imports "character_lib and ltx2_mlx_video_skill"** after QE33 adds `qwen_edit` (a pinned file, so the plan changes only the sentence QE37 names).
11. **`job_phases` puts `1c` before `redo`, while `_phase_sequence` puts Phase 1c after the redo phase;** the two never meet (redo needs shots mode, which refuses a seed), so the plan follows QE69 as written.

## Execution handoff

Plan complete and saved to `qwen-agent-workspace/docs/superpowers/plans/2026-11-03-qwen-edit-models.md`.

**How it was checked.**
- **Replay, in memory.** A read-only script parsed every Edit and Write block of this plan, in order, and applied it to an in-memory copy of `c86808a`'s files (no file on disk was changed), checking every old text occurs exactly once at its turn. The `SHA` placeholder of Task 8 was replayed as a 40-character stand-in.
- **Compile.** Every Python file the replay produced compiled under Python 3.9.6 and 3.13 (`compile()` on the in-memory text), and the replayed `app.js` passed `node --check` on its in-memory text.
- **Scans.** The replayed `NEW_PY` files passed `test_mut25`'s forbidden-pattern scan (in memory), and `bin/ltx-movie`'s replayed top-level import set equals `test_dk3`'s.
- **Executed in memory.** Against the replayed modules (loaded from their in-memory text, no bytecode written): QET1, QET3 and QET37 as written; QET23/QET15's `_bad_edits` texts against both `_edit_problem`s; Review Focus 5's round trip; V1 rule 12d's cases; `_phase_sequence` with and without `seed_edit`; `_resolve_seed_edit`'s rule texts with a fake `qwen_edit`; and the `--dry-run` of QET31 (with `_seed_geometry` faked, nothing written): byte-identical without the flag and with `as-is`, the Phase 1c block after Phase 1b, Phase 2's `--seed-image <story>/seed-edited.png`, no probe call.
- **Not run.** No pytest run (the planning session was read-only), so every gate count above is computed from the test lists, not observed; the executor's gate is the first run. No browser (V2), model, download, venv or network access; the live checks (V4) are the user's, on macstudio.

Please review the plan. Which execution approach would you prefer?
- **Subagent-driven.** A fresh Sonnet `code-executor` implements each task in `$S/qem-wt` on branch `qwen-edit-models`, and a fresh Opus reviewer checks it before the next one starts.
- **Native.** One session implements every task, then one fresh Opus reviewer checks the whole branch.

I recommend subagent-driven: Tasks 2-7 each consume the previous tasks' names (`qwen_edit`'s functions, `run_edit_child`'s routing, the request fields), three of them edit pinned pipeline files, and a shipped drift in content safety or the byte-identical legacy routes would be costly, so a reviewer gate after each task is worth its cost.
