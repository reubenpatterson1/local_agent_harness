# Custom Edit LoRAs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user register a public Hugging Face Qwen edit LoRA (pinned at its current commit) or a local `.safetensors` file once, with `bin/seed-edit-lora` or the page's "Add custom LoRA" form, and pick it in Seeds, Locations, Characters, Compose and `bin/ltx-movie --seed-edit-lora`, with its trigger prepended to every edit prompt.

**Architecture:** `movie_ui_seedgen.py` keeps the built-in LoRAs as `BUILTIN_QWEN_LORAS` and merges in the custom LoRAs of one JSON registry file (`generated/seed_loras/user_loras.json`, or `$SEED_EDIT_USER_LORAS`) through stat-cached accessors (`qwen_loras()`, `qwen_lora_ids()`); every consumer reads the accessors. `qwen_edit.run_jobs`, the single edit choke point, prepends each selected LoRA's trigger to every job prompt, so content safety, `mflux_spec.json` and `run.json` see the triggered text with no change to a pinned file. A new `seed_lora_registry.py` is the only writer of the registry file and the only Hugging Face API caller; `bin/seed-edit-lora` and the server's `POST`/`DELETE /api/seed-loras` share it, and the page builds its form in `app.js`.

**Tech Stack:**
- Python 3.13 (`python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`, pytest); Python 3.9.6 (`/usr/bin/python3`) for the compile checks. node v26 (`node` on PATH) for `node --check` and the node-evaluated test (they skip where node is missing).
- Standard library only (`http.client`, `ssl`, `json`, `threading`, `fcntl` through `lora_catalog`). No new dependency. Tests: stdlib, PIL, pytest, and these existing test modules reused by import, unchanged except E2-E6: `tests/test_seed_edit_tool.py` (`st`: the `env` and `setup_env` fixtures, `load_tool`, `make_fakes`, `mflux_venv`, `install_model`, `install_lora`, `pinned_cache`, `stub_calls`, `run_tool`, `record_of`, `read_json`, `downloads`, `mark_ready`, `LORA_REGISTRY`, `PROMPT`, `WS`), `tests/test_qwen_edit.py` (`_jobs`, `_sources`, `_mflux_ready`), `tests/movie_ui_testutil.py` (`mt`).

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md`, committed as `76742e8` on branch `custom-edit-loras` (requirements CL1-CL52 with CL22a/CL22b, tests CL-T1-CL-T34, KPIs CLK1-CLK8, live checks CL-LV0-CL-LV9, existing-test edits E1-E7). Its line citations are at `20cee82`; `76742e8` adds only the spec, so they hold. Every Edit below is located by its old text, never by a line number. Where the spec cannot work as written against the code, the host or its own tests, an entry of "Spec conflicts" says which way this plan rules; "Plan rulings" fill the details the spec leaves open.

## Spec conflicts

The spec is the authority. Each entry names the conflict, the ruling, and the cost if the ruling is wrong.

1. **SC1 [defect] CL36 cannot wait for the server task.** CL1 removes `seedgen.QWEN_LORA_IDS`, but `movie_ui_server.py:229`, `:787` and `:1851` read it; with CL36 in a later commit, every capability refresh, every `POST /api/seeds/runs` and every Characters/Locations edit request raises `AttributeError` (HTTP 500), and the spec's own Task 1 gate (`tests/test_movie_ui_seedgen.py`) fails. **Ruling:** CL36's three replacements move into Task 1 (the only `movie_ui_server.py` change there). **Cost if wrong:** none.
2. **SC2 [defect] CLK3's grep finds nothing even before the change.** On this host `git grep -nE '\bQWEN_LORAS\b|\bQWEN_LORA_IDS\b'` prints 0 lines at `76742e8`, where 25 uses exist (git's ERE here has no `\b`). **Ruling:** CLK3 is measured with `git grep -nwE 'QWEN_LORAS|QWEN_LORA_IDS' -- . ':(exclude)docs'` (word match; `BUILTIN_QWEN_LORAS` does not match because `_` is a word character). CL-T1's own `hasattr(seedgen, "QWEN_LORAS")` check would be such a match, so the test spells the two names `"QWEN_" + "LORAS"` and `"QWEN_" + "LORA_IDS"`. **Cost if wrong:** none.
3. **SC3 [defect] CL-T6/CLK4's `HTTPSConnection` count cannot be 1 as written.** The spec itself (and this plan) contain the word, `git grep` skips untracked files (Task 2's new module is untracked until its commit), and a test that patches the class must name it. **Ruling:** the count is `git grep --untracked -c HTTPSConnection -- . ':(exclude)docs'` run from `WS`, which must print exactly `seed_lora_registry.py:1`; the tests spell the name `"HTTPS" + "Connection"`. **Cost if wrong:** none.
4. **SC4 [defect] CL23 uses `re.fullmatch` but pins `bin/seed-edit-lora`'s top-level imports to `argparse, os, sys, movie_ui_seedgen, seed_lora_registry`.** **Ruling:** `import re` sits inside `add()` (indented, so CL-T24's top-level import regex does not see it). **Cost if wrong:** none.
5. **SC5 [defect] CL4's hf `file` rule is case-sensitive (`ends with ".safetensors"`) while R6 and H5 accept any case.** A repo whose only root file is `X.SafeTensors` passes R6/H5, then trips CL21's assertion (a crash). **Ruling:** CL4's hf `file` rule compares lower-case, like the local `path` rule. **Cost if wrong:** a file the spec meant to refuse is accepted; mflux loads by extension case-insensitively, so it still works.
6. **SC6 [defect] A local path with control characters passes CL18 but fails CL4** (`path` has no character below `\x20`), and a basename with `\x7f` makes the default label fail CL4's label rule: both crash CL21's assertion. **Ruling:** `check_local_file` refuses, right after it computes `path`, any character below `\x20` or `\x7f` in `path` with `RegistryError(400, "path must not contain control characters")` (`M_PATH_CONTROL`). **Cost if wrong:** one more refusal text than the spec lists.
7. **SC7 [split] The spec's two tasks become three** (Task 1 read side and run path, Task 2 writer and CLI, Task 3 server and page). A reviewer can reject the Hugging Face fetch and add/remove logic (network, file checks, locking) while approving the run path that changes every existing edit (the trigger prefix, the diffusers refusal), and the run path is fully testable with hand-written registry files. Consequences: `seed_lora_registry.py` is created in Task 1 with only the run-time checks CL19/CL22b and is rewritten whole in Task 2; CL-T1-CL-T24 are split between Task 1 and Task 2 in the same test file. **Cost if wrong:** one more review gate.
8. **SC8 [defect] CL-T24 compiles `tests/test_movie_ui_seed_loras.py`, which exists only after the server task.** **Ruling:** CL-T24 (Task 2) lists the files that exist then; Task 3 adds `tests/test_movie_ui_seed_loras.py` to its two tuples. **Cost if wrong:** none.
9. **SC9 [defect] CL-T24's `git ls-files -s bin/seed-edit-lora` prints nothing for an untracked file.** **Ruling:** Task 2 makes the file executable and stages it before the run that must pass. **Cost if wrong:** none.
10. **SC10 [defect] CL-T34's `git diff --quiet 20cee82 HEAD -- movie_ui_batch.py` cannot see uncommitted work.** **Ruling:** the test compares the working tree: `git diff --quiet 20cee82 -- movie_ui_batch.py` (skipped outside git or when `20cee82` is absent). **Cost if wrong:** none.
11. **SC11 [reading] The spec's ID line names E1-E9; Section 5.2 defines E1-E7.** **Ruling:** E1-E7 are the complete list; there is no E8 or E9. **Cost if wrong:** none.
12. **SC12 [Review Focus] An unwritable registry location crashes `add` and `remove`** (an `OSError` from `os.makedirs`, the lock or the atomic write: a CLI traceback, an HTTP 500). The spec is silent. **Ruling:** both wrap the locked section and answer `RegistryError(409, "cannot write the custom LoRA registry %s: %s" % (path, e))` (`M_UNWRITABLE`; 409 is D14's status for a registry-file problem; the CLI exits 2). Pinned by Review Focus 4. **Cost if wrong:** one more refusal text than the spec lists.

## Plan rulings

1. **R1 [reading] Message constant names.** The spec names messages `M-…`, `R1`-`R12`, `H1`-`H9`, `N-…`; their Python names are fixed in Task 2 Step 3 (`M_FIELD` … `N_IN_PLACE`) and `UNUSABLE_MSG` (bin/seed-edit-setup), `SEED_LORA_DELETE_BODY` (server, as the spec says), `USER_LORA_PREFIX`/`PROBE_NOT_REPORTED` (lib). Texts are the spec's, byte for byte.
2. **R2 [reading] H4-H6's `%s@%s`** is `<repo>@<sha[:12]>`, the short form CL24 and `weights_problem` use. A file list is at most 10 names joined `", "`, then `" and N more"`, or `none`, in the API's order.
3. **R3 [reading] R1 sees every key**, including one whose value is `None` (`{"ws": null}` is an unknown field); R2-R12 then treat a `None` value as absent.
4. **R4 [reading] H9's base-model text** is the str `base_model`, or the str items of a list joined `", "`, or `none`; N-FAMILY and N-FAMILY-CONFLICT print the same text. N-FAMILY-CONFLICT is emitted when `family` is given and the card names exactly one family that differs. The licence text is stripped before the 200-character cut; an empty result is `NO_LICENSE`.
5. **R5 [reading] H3 prints the `gated` value with `%s`** (`auto`, `manual`, `True`).
6. **R6 [reading] CL5's stat failure other than "missing"** is cached under the key `(path, "stat", str(error))`, so it also warns once.
7. **R7 [reading] CL33's local report line** prints `lora["bytes"] / 2 ** 30` (equal to the file size whenever `local_problem` is `None`).
8. **R8 [reading] Test harnesses the spec leaves open.** Task 1/2 tests reuse `tests/test_seed_edit_tool.py`'s `env` and `setup_env` fixtures by import (the precedent is `tests/test_ltx_movie_cast_refs.py:34`); CL-T27's probe call counter is a stub `bin/seed-edit` that appends a line to `<ws>/probe_calls.txt`; the server tests set `server.probe_ws` to the stub workspace (as `tests/test_movie_ui_seedgen.py:929` does) so `refresh_seed_edit` runs the stub; CL-T31 patches `make_server`, `start_threads`, `batch_recovery`, `lib.startup_recovery` and `signal.signal`, and deletes `SEED_EDIT_USER_LORAS` first so `main` must set it.
9. **R9 [reading] `INFO`**, the recorded API answer, is the 2026-11-18 read of `GET /api/models/WarmBloodAban/Anything_to_Real_Characters_2511?blobs=true` (the spec's sha, card and the four siblings; `README.md` is 3892 bytes and the image 1250845), trimmed to the keys the module reads plus `id`, `author`, `private`, `library_name`, `pipeline_tag`.
10. **R10 [reading] Test names** are `test_cl_t<N>_…` and `test_cl_review_focus_<N>_…`; `grep -rn "def test_cl_" tests/` prints nothing at `76742e8`.
11. **R11 [reading] The task gates are run by the controller**, never by an implementer (a full run takes about 20 minutes). Implementers run only the targeted commands their task names.
12. **R12 [reading] Planning replay.** During planning, every Edit of Tasks 1-3 was applied by script to a scratch copy of `76742e8` (outside the worktree): every old text matched exactly once; the three task stages gave the intermediate counts written below (`7`, `4`, `2`, `15`; Task 2 red `50 failed, 15 passed`, green `65 passed`; Task 3 red `10 failed`, green `76`); and `tests/test_seed_edit_tool.py`, `test_movie_ui_seedgen.py`, `test_qwen_edit.py`, `test_movie_ui_qwen_edit.py`, the five `test_ltx_movie_*` suites of E2, `test_movie_ui_http.py`, `test_location_ui.py`, `test_movie_ui_seedfolder.py`, `test_movie_ui_builder.py` and every other test file that reads `app.js` passed at the final state. The full suite was not run (Step 0.3 and the gates do that in the worktree).

## Global Constraints

From the spec, verbatim (section in brackets):

- [Status] "The implementer makes no design decisions; every text in Section 3 is exact."
- [Where] "`/Users/reubenpatterson/local_agent_harness` is never touched. The user's other Mac (macstudio) is never accessed; the live checks (Section 6) are run by the user."
- [D1] "`TRIGGER_RE = ^[A-Za-z0-9][A-Za-z0-9 ,.;:'!?()&/-]{0,199}$`, with no two consecutive spaces and no trailing space … it never reaches an argv (CL28 applies it after every argv is parsed)."
- [D15] "`BUILTIN_QWEN_LORAS` keeps exactly today's two dicts (SQT10's `LORA_REGISTRY` literal stays). Code reads `lora.get("user")`, `lora.get("source")`, `lora.get("trigger")` so built-ins need no new keys."
- [D16] "`movie_ui_seedgen.py` gains `json`, `os`, `sys`, `threading` (E4 updates SGT17's list). `qwen_edit.py`, `bin/seed-edit`, `bin/seed-edit-setup`, `movie_ui_lib.py` and `movie_ui_server.py` keep their top-level imports; they import `seed_lora_registry` inside the functions that need it … `seed_lora_registry.py` imports `qwen_edit` only inside functions … `NEW_PY` is not extended."
- [D18] "No `PIPELINE_FILES` member changes … So no `test_mut26` BASELINE bump is needed (CLK7). If an implementer finds a pinned file must change, they stop and report."
- [CL15] "No `urllib`, no `load_module(`, no `match` statement, no `X | Y` annotations, `%` formatting only."
- [CL17] "**no `Authorization` header, and no token variable is read**".
- [CL48] "New and changed code runs on Python 3.9 and 3.13: no `match`, no `X | Y` types, no `zip(strict=)`, no parenthesized context managers, `%` formatting."
- [CL49] "No token, no `Authorization` header and no user path (`/Users/...`) in code or tests; tests use `tmp_path`, synthetic safetensors files and the public metadata of Section 0.1."
- [CL50] "The implementation changes no `PIPELINE_FILES` member (CLK7). `test_mut26`'s BASELINE stays `ca958ca...`."
- [CL51] "`HTTPSConnection` occurs once in the workspace (CL17)." (measured as SC3 says)
- [0.3] "Untouched (verified by CL50): every `PIPELINE_FILES` member (incl. `bin/ltx-movie`, `character_dataset.py`, `lora_catalog.py`, which is imported but not edited), `seed_edit_mflux_child.py`, `location_dataset.py`, `movie_ui_batch.py`, `movie_ui_seedfolder.py`, `content_safety.py`, `static/movie-ui/index.html`, `static/movie-ui/app.css`."
- [0.4, out of scope] "Running a `qwen2511` edit without Lightning, or with guidance other than 1.0 … Z-Image stills LoRAs … LoRAs on the diffusers backend (`qwen2511-bf16`): refused (CL13) … Auto-updating a pinned revision; editing an entry in place … Downloading weights from the page … LoKr/LoHa … Non-ASCII triggers … A per-workspace registry for jobs in a workspace other than the UI's (D8)."
- [E7] "No other existing assertion changes. If a further existing test fails, the implementer stops and reports it (it is a spec gap, not a test to adjust)."
- [QET38, 0.1] the page: no `https?://`, inline `on...=`, `style=`, `alert(`, `confirm(`, `prompt(`, `eval(` or `new Function` in `index.html` or `app.js`; the new form is built by JS and uses `askConfirm`.

House rules (every task's requirements include them):

- **The checkout.** Every command runs in the worktree `$S/cl-wt`, branch `custom-edit-loras`, from `WS`. `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`; `WS` = `$S/cl-wt/qwen-agent-workspace`; `D` = `$S/cl-baseline` (scratch, never staged). The git root is `$S/cl-wt`, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Shell variables do not persist between commands, so every block defines what it uses. Never touch `/Users/reubenpatterson/local_agent_harness`; never ssh, scp, rsync or HTTP to macstudio or any other host; never contact a server other than an in-test `127.0.0.1` one (and never the Hugging Face API: every test patches it).
- **Git.** Never git stash, reset, checkout, switch, amend or rebase. Stage only the paths a task names and check `git diff --cached --name-only` before every commit. Implementer commits pass the trailer as a second `-m`: `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`. Never stage `.DS_Store`, `.claude/`, `__pycache__/`, `generated/`, `.superpowers/` or anything under `docs/` except this plan (Step 0). Never push.
- **Secrets.** The repository is public: no token, no `Authorization` header, no `/Users/...` path in code or tests. Tests that need a token variable set use the literal value `dummy-not-a-token`. Never read, print or source `~/.zshenv` or any `fleet.env`.
- **Python.** Every changed Python file compiles on Python 3.9.6 and 3.13: no `match` statement, no `X | Y` type expressions, no walrus operator, no `str.removeprefix`, no `zip(strict=)`, no parenthesised context managers. The code blocks below use none of them.
- **Source words.** The words `urllib` and `load_module(` and the text `->` appear nowhere in `seed_lora_registry.py`, `bin/seed-edit-lora`, `tests/test_seed_lora_registry.py` or `tests/test_movie_ui_seed_loras.py` (CL-T24 scans them, except its own `forbidden` list), and the word `HTTPSConnection` appears only once, in `seed_lora_registry.fetch_model_info` (SC3). No docstring line of a changed module starts at column 0 with `import ` or `from ` (the import-pin tests read column-0 lines).
- **Editing.** Executors change tracked files only with the Edit tool, or the Write tool for a new file or a whole-file replacement this plan names. Never use `sed -i`, a redirect or a script to change a tracked file. An Edit's old text is whole lines and occurs exactly once in the file at that moment, unless the step says `replace_all` and gives the count. If it does not match, stop and report; do not adapt it. The Edits of a step are applied in the order written.
- **Code blocks are copied byte for byte**, including comments, blank lines and the exact message texts.
- **The compile check** (in each task's verify step) is this command with the task's Python files as `FILES`. Expected: two lines, `compiled N` for 3.9 and then for 3.13.

```bash
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' FILES; done
```

- **The pinned-file check** (in each task's verify step; D18, CLK7). zsh does not word-split an unquoted variable, so the 23 paths are written out:

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git diff --quiet ca958ca1c1320fdcb936c508f432eff83330d512 -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pinned files unchanged"
python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py 2>&1 | tail -1
```

Expected: `pinned files unchanged`, then a summary with `passed` and no `failed`. **No `test_mut26` BASELINE bump is needed** (spec D18/CL50/CLK7: no pinned file changes); the second command is the proof the implementer must run, not assume. If `test_mut26_pipeline_files_are_unchanged` fails, stop and report: the plan is wrong.

## Review Focus

The five inputs and failure modes most likely to reach a person using this first. The spec implies each; no CL-T row exercises it. Each is pinned by a test named `test_cl_review_focus_N_…` in the task that owns its code.

1. **A queued Seeds run whose local custom LoRA file has gone** (the external drive holding it is unmounted, or the file was replaced by one of another size): `bin/seed-edit` must refuse before any child starts, exit 2, and write `run.json` state `failed` with the exact M-LOCAL-MISSING or M-LOCAL-CHANGED refusal. Test: `test_cl_review_focus_1_a_moved_local_lora_refuses_before_the_child` (Task 1).
2. **A relative or `~` `--path` typed in another directory** (`cd ~/Downloads; bin/seed-edit-lora add --path lora.safetensors …`): the CLI resolves it against the shell's current directory or HOME, stores the absolute path, and refuses `./lora.safetensors` as the same file. Test: `test_cl_review_focus_2_the_cli_resolves_relative_and_home_paths` (Task 2).
3. **A Hugging Face URL pasted the way browsers copy it** (a trailing `/`, `/tree/main`, `/blob/main/<file>`, `http://`, `hf.co/`, no scheme, a query string, a leading or trailing space or newline): only `https://huggingface.co/OWNER/NAME[/]` is accepted; every other form is refused with R5's text naming what was typed, and the Hugging Face API is never called for it. Test: `test_cl_review_focus_3_pasted_hugging_face_urls` (Task 2).
4. **An unwritable registry location** (`SEED_EDIT_USER_LORAS` under a regular file, a read-only `generated/`): `add` and `remove` refuse with 409 M_UNWRITABLE (SC12), the CLI exits 2 with one `Error:` line, and the readers still give the built-ins silently. Test: `test_cl_review_focus_4_an_unwritable_registry_is_a_clean_refusal` (Task 2).
5. **A Seeds run in a workspace whose `bin/seed-edit --probe` predates custom LoRAs** (D8/D9: the probe reports only the built-ins): the capability stays usable, and `POST /api/seeds/runs` with the custom LoRA answers 409 `LoRA <label> is unavailable: ` + PROBE_NOT_REPORTED and creates nothing. Test: `test_cl_review_focus_5_an_older_probe_gives_a_clear_409` (Task 3).

---

## File Structure

| File | Change | Task | Responsibility after this plan |
|---|---|---|---|
| `movie_ui_seedgen.py` | Modify | 1 | CL1-CL14: `BUILTIN_QWEN_LORAS`, the registry file reader `user_loras` and validator `user_loras_problem`, `qwen_loras`/`qwen_lora_ids`, `settings_item`, `trigger_prompt`, the diffusers rule, `registry_view`'s three keys. |
| `seed_lora_registry.py` | Create (Task 1), replace whole (Task 2) | 1, 2 | Task 1: CL19, CL22b (`lora_pair_count`, `local_problem`, `downloaded_problem`). Task 2: also CL15-CL22a (request rules, `fetch_model_info`, `check_local_file`, `load_entries`/`save_entries`, `add`, `remove`, `slug`, `default_id`). |
| `qwen_edit.py` | Modify | 1 | CL25-CL29: `lora_problem`, `check_lora_args`, `install_problem`, `run_jobs`'s trigger prefix, the docstring. |
| `bin/seed-edit` | Modify | 1 | CL30, CL31: the probe over `qwen_loras()`, the triggered `run.json` prompt, the docstring. |
| `bin/seed-edit-setup` | Modify | 1 | CL32, CL33: custom IDs, local report lines, `unusable`/`finish` and exit 1. |
| `movie_ui_lib.py` | Modify | 1 | CL34: `USER_LORA_PREFIX`, `PROBE_NOT_REPORTED`, `_probe_qwen`'s `user-` tolerance. |
| `movie_ui_server.py` | Modify | 1, 3 | Task 1: CL36 (SC1). Task 3: CL35, CL37-CL39 (routes, handlers, `refresh_seed_edit`, the triggered initial prompt, the environment). |
| `bin/seed-edit-lora` | Create (mode 100755) | 2 | CL23, CL24: the CLI. |
| `static/movie-ui/app.js` | Modify | 3 | CL40-CL43: `customLoraForm`, `customLoraBody`, the picker rows, notes and steps line. |
| `tests/conftest.py` | Modify | 1 | E1: `seed_lora_isolation`. |
| nine helpers (E2), `tests/test_seed_edit_tool.py` (E3), `tests/test_movie_ui_seedgen.py` (E4), `tests/test_movie_ui_qwen_edit.py` (E5) | Modify | 1 | Isolation and the registry pins. |
| `tests/test_movie_ui_http.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_seedgen.py` (E6) | Modify | 3 | `len(srv.ROUTES) == 66`. |
| `tests/test_seed_lora_registry.py` | Create (Task 1), extend (Task 2, Task 3 edits two tuples) | 1, 2 | CL-T1-CL-T4, CL-T11, CL-T14-CL-T21, CL-T23, Review Focus 1 (Task 1); CL-T5-CL-T10, CL-T12, CL-T13, CL-T22, CL-T24, Review Focus 2-4 (Task 2). |
| `tests/test_movie_ui_seed_loras.py` | Create | 3 | CL-T25-CL-T34, Review Focus 5. |

**Task split (SC7).** Task 1 is the read side and the run path: everything that consumes the registry, tested with hand-written registry files; after it, a hand-edited `user_loras.json` already works end to end. Task 2 is the writer: the Hugging Face call, the file checks, add/remove under the lock, and the CLI. Task 3 is the server and the page. Each ends with its own green test file and gate.

---

## Between tasks: the existing suite (controller)

**Allowed lost passes** (`$D/expected-failures.txt`, written in Step 0.3). No baseline pass may be lost by this plan (no pinned file changes), so the list holds only the three timing-sensitive tests that every gate reruns alone. A line is `<first task> <last task> <test id> <note>`:

```text
# custom-edit-loras plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 3 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 3 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
```

**The gate** is `zsh $D/gate-run.sh N` (written in Step 0.3; a full run of about 20 minutes; it may run in the background), run by the controller after task N's commit and before its review. It prints, in order: the `disk ok` line, the run's summary line, the gate's `lost … new tests … baseline failures still failing …` line with any `LOST`/`NEW-TEST-FAIL` lines and `GATE PASS` or `GATE STOP`, the flake rerun's summary (expected `3 passed`), and `ATK2 OK lines unchanged` (the five `OK n/n` lines of `test_ltx_movie_offline.py`, `test_qwen_agent_image_oneshot.py`, `test_qwen_agent_danger_auto_approve.py`, `test_qwen_agent_context_budget.py`, `test_qwen_agent_session_memory.py` equal the baseline's).

**When the gate prints `GATE STOP`:** report the UNEXPECTED or NEW-TEST-FAIL IDs with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`. A lost pass the list does not name is a defect in this task's code (or, under E7, a spec gap): an Opus reviewer rules on it and writes the exact fix as a new commit; nobody edits an existing assertion to make it pass. If an UNEXPECTED ID is `tests/test_fleet_tracing.py::test_trt41a_trace_cli_on_one_agent` or `tests/test_fleet_integration.py::test_t47_signatures_and_loopback_rules` (timing-sensitive, unrelated), rerun it alone; if it passes alone, append `<N> 3 <id> flaky` to the list and rerun the gate script's last three commands.

**Must stay green in every task** (none is in the list, so a failure stops the gate): `tests/test_movie_ui_builder.py` (`test_mut25_*`, `test_mut26_pipeline_files_are_unchanged`), `tests/test_qwen_edit.py` (QET11), `tests/test_seed_edit_tool.py` (SQT10, SQT4, SGT13), `tests/test_movie_ui_seedgen.py` (SGT17, SGT34, SQT17, SQT18, SQT22, SGT20), `tests/test_movie_ui_qwen_edit.py` (QET38, QET39), `tests/test_ltx_movie_seed_edit.py`, `tests/test_ltx_movie_shots_seed.py`, `tests/test_ltx_movie_cast_refs.py`, `tests/test_ltx_movie_extra_refs.py`, `tests/test_ltx_movie_seed_context.py`, `tests/test_ltx_movie_offline.py`.

---

## Step 0: the plan commit, the snapshot, the baseline (controller; no code)

- [ ] **Step 0.1: Commit this plan and confirm the tree.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/cl-wt/qwen-agent-workspace
git branch --show-current                                      # expected: custom-edit-loras
git status --short                                             # expected: ?? docs/superpowers/plans/2026-11-17-custom-edit-loras.md (only)
git add docs/superpowers/plans/2026-11-17-custom-edit-loras.md
git diff --cached --name-only                                  # expected: qwen-agent-workspace/docs/superpowers/plans/2026-11-17-custom-edit-loras.md
git commit -m "docs: custom edit LoRAs implementation plan" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git log -3 --format=%h' '%s                                    # expected: <plan sha> docs: custom edit LoRAs implementation plan; 76742e8 docs: custom edit LoRAs design spec; 20cee82 Merge pull request #26 ...
git diff --stat 20cee82 HEAD -- . ':(exclude)docs' | tail -1   # expected: no output
wc -l movie_ui_seedgen.py qwen_edit.py bin/seed-edit bin/seed-edit-setup movie_ui_lib.py movie_ui_server.py static/movie-ui/app.js tests/conftest.py | head -8
grep -rn "def test_cl_" tests/ | wc -l                         # expected: 0
```

Expected `wc -l` counts (at `76742e8`): `movie_ui_seedgen.py` 341, `qwen_edit.py` 625, `bin/seed-edit` 510, `bin/seed-edit-setup` 427, `movie_ui_lib.py` 2534, `movie_ui_server.py` 3556, `static/movie-ui/app.js` 3553, `tests/conftest.py` 31. If any value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 0.2: The compressed snapshot (house rule) and the disk.**

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
tar czf $S/snapshot-pre-cl-76742e8.tgz -C $S/cl-wt --exclude generated .
ls -l $S/snapshot-pre-cl-76742e8.tgz
tar tzf $S/snapshot-pre-cl-76742e8.tgz | grep -c 'qwen-agent-workspace/movie_ui_seedgen.py$'   # expected: 1
tar tzf $S/snapshot-pre-cl-76742e8.tgz | grep -c '/generated/'                                 # expected: 0
df -g $S/cl-wt | tail -1 | awk '{print ($4 >= 20) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
```

Expected: the archive exists, `1`, `0`, and `disk ok` (on `DISK LOW` stop and report; never delete anything).

- [ ] **Step 0.3: Write the gate files and record the baseline (spec Plan, step 0).** Create `$D` (`mkdir -p $S/cl-baseline`) and write three scratch files with the Write tool (outside the repository, never staged):

1. `$D/expected-failures.txt`: exactly the `text` block of "Between tasks" above.
2. `$D/gate-run.sh`, exactly:

```bash
#!/bin/zsh
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/cl-baseline
N=$1
cd $S/cl-wt/qwen-agent-workspace
df -g . | tail -1 | awk '{print ($4 >= 5) ? "disk ok: " $4 " GiB free" : "DISK LOW: " $4 " GiB free"}'
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/task-$N-pytest.txt 2>&1; tail -1 $D/task-$N-pytest.txt
python3 -B $D/gate.py $D/baseline-pytest.txt $D/task-$N-pytest.txt $D/expected-failures.txt $N
python3 -B -m pytest -q -p no:cacheprovider tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store 2>&1 | tail -1
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/task-$N-ok-lines.txt
diff $D/baseline-ok-lines.txt $D/task-$N-ok-lines.txt && echo "ATK2 OK lines unchanged"
```

3. `$D/gate.py`, exactly:

```python
"""The task gate of the custom-edit-loras plan: a full pytest -rA run against the baseline. A new test is any
test of tests/test_seed_lora_registry.py or tests/test_movie_ui_seed_loras.py, or any test ID the baseline does
not have."""
import re
import sys

base_file, run_file, expected_file, task = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
NEW_FILES = ("tests/test_seed_lora_registry.py::", "tests/test_movie_ui_seed_loras.py::")


def status(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            found = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED) (\S+)", line)
            if found:
                out[found.group(2)] = found.group(1)
    return out


base, now = status(base_file), status(run_file)
expected, flaky = [], []
with open(expected_file, encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if not parts or line.startswith("#"):
            continue
        if int(parts[0]) <= task <= int(parts[1]):
            expected.append(parts[2])
        if parts[3:4] == ["flaky"]:
            flaky.append(parts[2])


def listed(test):
    return any(test == e or test.startswith(e + "[") for e in expected)


lost = sorted(t for t, s in base.items() if s == "PASSED" and now.get(t) != "PASSED")
unexpected = [t for t in lost if not listed(t)]
mine = sorted(t for t in now if t.startswith(NEW_FILES) or t not in base)
broken = [t for t in mine if now[t] not in ("PASSED", "SKIPPED")]
old_failures = sorted(t for t, s in base.items() if s in ("FAILED", "ERROR") and t not in flaky)
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

(`SKIPPED` counts as passing for a new test: CL-T24's 3.9 compile and the node tests skip where the interpreter is missing.)

Then record the baseline (about 20 minutes; it may run in the background):

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/cl-baseline
cd $S/cl-wt/qwen-agent-workspace
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt; cat $D/baseline-ok-lines.txt
```

Expected: a summary line with `2 failed`; exactly the two `FAILED` lines `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets - AssertionError: b...` (both reproduced alone at `76742e8` during planning; this answers spec Q8); no `ERROR` line; `1` (`test_mut26` passes); five lines each ending `OK n/n`. If a flake of the three `test_fleet_tracing.py` tests is an extra `FAILED` line, rerun the three alone (the gate script's flake line); `3 passed` means the baseline stands (the gate ignores them). Any other difference: stop and report. These files **are** the baseline (CLK5).

- [ ] **Step 0.4: Confirm the pinned files.** Run the pinned-file check of "Global Constraints". Expected: `pinned files unchanged` and a `tests/test_movie_ui_builder.py` summary with no `failed`.

---
### Task 1: The registry read side and the run path (CL1-CL14, CL19, CL22b, CL25-CL34, CL36; E1-E5; CL-T1-CL-T4, CL-T11, CL-T14-CL-T21, CL-T23, Review Focus 1)

This task makes every consumer read the merged registry and makes a custom LoRA work end to end once its entry is in `user_loras.json` (written by hand in these tests): selection, the diffusers refusal, the settings items, the probe and its tolerance, `bin/seed-edit-setup`, and the trigger prefix in `run_jobs` and `run.json`. It adds no writer and no network code (Task 2).

**Files:**
- Modify: `movie_ui_seedgen.py` (docstring and imports `:1-17`, `QWEN_LORAS` `:78`, `QWEN_LORA_IDS` `:89`, after `HF_TOKEN_VARS` `:94`, `qwen_selection` `:142-151`, `qwen_lora` through `qwen_settings` `:234-269`, `registry_view` `:295-297`)
- Create: `seed_lora_registry.py` (the run-time checks only; Task 2 replaces it whole)
- Modify: `qwen_edit.py` (docstring `:16-22`, `lora_problem` `:242-248`, `check_lora_args` `:380-389`, `install_problem` `:479-485`, `run_jobs` `:507-510`)
- Modify: `bin/seed-edit` (docstring `:16-19`, `probe` `:259`, `new_record` `:316-318`)
- Modify: `bin/seed-edit-setup` (docstring `:9-13`, `:34-36`, after `HEADROOM_GIB` `:59`, `selection` `:276-278`, `items_of` `:295-298`, `report` `:336-338`, after `report`, `main` `:372-375`, `:419-423`)
- Modify: `movie_ui_lib.py` (before `_probe_model` `:1750`, `_probe_qwen` `:1761-1782`)
- Modify: `movie_ui_server.py` (`:229`, `:787`, `:1851`; SC1)
- Modify: `tests/conftest.py` (E1); `tests/test_ltx_movie_extra_refs.py:115`, `tests/test_ltx_movie_seed_edit.py:99`, `tests/test_qwen_edit.py:45`, `tests/test_ltx_movie_cast_refs.py:100`, `tests/test_ltx_movie_shots_seed.py:148`, `tests/test_movie_ui_seedgen.py:389`, `tests/test_seed_edit_tool.py:120`, `tests/test_movie_ui_qwen_edit.py:55`, `tests/test_ltx_movie_seed_context.py:117` (E2); `tests/test_seed_edit_tool.py:1142-1151`, `:1551` (E3); `tests/test_movie_ui_seedgen.py:140`, `:208-209`, `:352-357`, `:370` (E4); `tests/test_movie_ui_qwen_edit.py:46` (E5)
- Test: `tests/test_seed_lora_registry.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks. Existing: `lora_catalog.read_safetensors_header(path)` (raises `lora_catalog.CatalogError`), `movie_ui_lib.write_json_atomic(path, obj)`, `movie_ui_lib.write_bytes_atomic(path, data)`, `movie_ui_lib._is_int`, `movie_ui_lib._is_number`.
- Produces (Task 2 and Task 3 rely on these exact names):
  - `movie_ui_seedgen`: `BUILTIN_QWEN_LORAS` (tuple of the two built-in dicts), `BUILTIN_QWEN_LORA_IDS = ("uncensored", "viggle-turbo")`, `USER_LORAS_ENV = "SEED_EDIT_USER_LORAS"`, `USER_LORAS_SCHEMA = "seed-edit.user-loras.v1"`, `USER_ID_RE`, `USER_LORA_MAX_BYTES`, `LABEL_MAX`, `LICENSE_MAX`, `STEPS_MAX`, `TRIGGER_RE`, `HF_REPO_RE`, `HF_FILE_RE`, `HF_KEYS`, `LOCAL_KEYS`, `NO_LORAS_MSG`, `REMOVED_MSG`, `USER_LORAS_WARNING`; `user_loras_path() -> str`; `valid_trigger(text) -> bool`; `user_loras_problem(data) -> str or None`; `user_loras() -> tuple of dict`; `qwen_loras() -> tuple of dict`; `qwen_lora_ids() -> tuple of str`; `settings_item(lora, scale) -> dict`; `trigger_prompt(prompt, loras) -> str`; `registry_view()` LoRA items gain `"user"`, `"source"`, `"trigger"`.
  - `seed_lora_registry` (Task 1 part): `PAIR_SUBSTITUTIONS`, `lora_pair_count(header) -> int`, `local_problem(lora) -> str or None`, `downloaded_problem(lora, path) -> str or None`, `M_LOCAL_MISSING`, `M_LOCAL_CHANGED`, `M_HF_SIZE`, `M_HF_NOT_ST`, `M_HF_NO_PAIRS`.
  - `movie_ui_lib`: `USER_LORA_PREFIX = "user-"`, `PROBE_NOT_REPORTED`.
  - `tests/test_seed_lora_registry.py` helpers: `WS`, `REPO`, `FILE`, `SHA`, `TRIGGER`, `LOCAL_LICENSE`, `registry_path` (autouse fixture), `pairs(layer) -> dict`, `st_bytes(header) -> bytes`, `safetensors(path, header=None) -> path`, `hf_entry(lora_id="user-hf", family="qwen2511", trigger=TRIGGER, steps=None, size=354082336, repo=REPO, file=FILE) -> dict`, `local_entry(path, lora_id="user-local", family="qwen2511", trigger=TRIGGER, steps=None) -> dict`, `write_registry(path, entries)`, `probe_workspace(tmp_path, printed) -> str`.

- [ ] **Step 1: Write the failing test file.** Create `tests/test_seed_lora_registry.py` with exactly this content:

```python
"""Tests for the custom (user-added) Qwen edit LoRAs (docs/superpowers/specs/2026-11-17-custom-edit-loras-
design.md, Section 5.1: CL-T1-CL-T24, with the plan's Review Focus pins 1-4): the registry file and its
accessors in movie_ui_seedgen, seed_lora_registry, bin/seed-edit-lora, and the run path through qwen_edit,
bin/seed-edit and bin/seed-edit-setup.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py

Rules (spec 5.1):
- Every test's registry file is tmp_path/r/user_loras.json (SEED_EDIT_USER_LORAS, the autouse registry_path
  fixture). write_registry writes it as the registry module does (an atomic replace). Safetensors files are
  synthetic: the 8-byte little-endian header length, the JSON header and 16 zero bytes.
- No test calls the Hugging Face API: every test that reaches seed_lora_registry.add with a repo patches
  seed_lora_registry.fetch_model_info.
- bin/seed-edit, bin/seed-edit-setup and bin/seed-edit-lora run in-process, loaded with
  importlib.machinery.SourceFileLoader, importlib.util.module_from_spec and loader.exec_module. The tool tests
  use tests/test_seed_edit_tool.py's env and setup_env fixtures (HOME, HF_HOME and Z_IMAGE_HF_HOME under
  tmp_path, the host probes faked) and its stub mflux child; nothing loads a model, downloads, renders or
  contacts a server, and no test reads the real HOME.
Stdlib, PIL and pytest.
"""

import hashlib
import json
import os
import struct

import pytest

import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import qwen_edit as qe
import seed_lora_registry as registry
import test_seed_edit_tool as st
from test_qwen_edit import _jobs, _mflux_ready, _sources
from test_seed_edit_tool import env, setup_env  # noqa: F401

WS = st.WS
REPO = "WarmBloodAban/Anything_to_Real_Characters_2511"
FILE = "AnythingtoRealCharacters2511_20.safetensors"
SHA = "e8f98cb5f976c9431f2bef47bd1a97caa1ee4ce7"
TRIGGER = "transform the image to realistic photograph"
LOCAL_LICENSE = "not stated (local file)"


@pytest.fixture(autouse=True)
def registry_path(monkeypatch, tmp_path):
    """Spec 5.1: this file's registry file is tmp_path/r/user_loras.json."""
    path = str(tmp_path / "r" / "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
    return path


def pairs(layer):
    """A safetensors header with one lora_A.default/lora_B.default pair for layer (the target LoRA's key form)."""
    return {layer + ".lora_A.default.weight": {"dtype": "BF16", "shape": [16, 64], "data_offsets": [0, 8]},
            layer + ".lora_B.default.weight": {"dtype": "BF16", "shape": [64, 16], "data_offsets": [8, 16]}}


def st_bytes(header):
    """The bytes of a synthetic safetensors file with this header."""
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * 16


def safetensors(path, header=None):
    """Write a synthetic safetensors file (pairs("transformer_blocks.0.attn.add_k_proj") by default); returns path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(st_bytes(pairs("transformer_blocks.0.attn.add_k_proj") if header is None else header))
    return path


def hf_entry(lora_id="user-hf", family="qwen2511", trigger=TRIGGER, steps=None, size=354082336, repo=REPO, file=FILE):
    """A valid hf registry entry (spec CL4) pinned at SHA."""
    return {"id": lora_id, "label": repo, "family": family, "source": "hf", "repo": repo, "revision": SHA,
            "file": file, "bytes": size, "default_on": False, "default_scale": 1.0, "license": "apache-2.0",
            "steps": steps, "scheduler": None, "trigger": trigger, "user": True}


def local_entry(path, lora_id="user-local", family="qwen2511", trigger=TRIGGER, steps=None):
    """A valid local registry entry (spec CL4) for the file at path, with its sha256 and size."""
    with open(path, "rb") as f:
        data = f.read()
    return {"id": lora_id, "label": os.path.basename(path), "family": family, "source": "local", "path": path,
            "file": os.path.basename(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "default_on": False, "default_scale": 1.0, "license": LOCAL_LICENSE, "steps": steps,
            "scheduler": None, "trigger": trigger, "user": True}


def write_registry(path, entries):
    """The registry file at path holding entries (an atomic replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lib.write_json_atomic(path, {"schema": "seed-edit.user-loras.v1", "loras": entries})


def probe_workspace(tmp_path, printed):
    """A directory whose bin/seed-edit prints json.dumps(printed) (movie_ui_lib.seed_edit_check runs it with
    sys.executable); returns its path."""
    ws = os.path.join(str(tmp_path), "probe-ws")
    os.makedirs(os.path.join(ws, "bin"), exist_ok=True)
    with open(os.path.join(ws, "bin", "seed-edit"), "w", encoding="utf-8") as f:
        f.write("import sys\nsys.stdout.write(%r + '\\n')\n" % json.dumps(printed))
    return ws


# --- CL-T1, CL-T2 (CL1, CL2, CL5, CL6): the constants and the merged list --------------------------------------

def test_cl_t1_no_file_gives_the_built_ins(registry_path, monkeypatch):
    assert not os.path.exists(registry_path)
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo") == seedgen.BUILTIN_QWEN_LORA_IDS
    assert [dict(lora) for lora in seedgen.BUILTIN_QWEN_LORAS] == st.LORA_REGISTRY
    assert seedgen.qwen_loras() == seedgen.BUILTIN_QWEN_LORAS and seedgen.user_loras() == ()
    old_names = ("QWEN_" + "LORAS", "QWEN_" + "LORA_IDS")   # spelled in parts so the CLK3 grep stays empty
    assert [hasattr(seedgen, name) for name in old_names] == [False, False]
    assert (seedgen.USER_LORAS_ENV, seedgen.USER_LORAS_SCHEMA) == ("SEED_EDIT_USER_LORAS", "seed-edit.user-loras.v1")
    assert seedgen.user_loras_path() == registry_path
    default = os.path.join(WS, "generated", "seed_loras", "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", "")
    assert seedgen.user_loras_path() == default
    monkeypatch.delenv("SEED_EDIT_USER_LORAS")
    assert seedgen.user_loras_path() == default


def test_cl_t2_a_valid_file_appends_its_entries_in_file_order(registry_path, tmp_path):
    local = safetensors(str(tmp_path / "loras" / "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo", "user-hf", "user-local")
    assert seedgen.user_loras() == (hf_entry(), local_entry(local))
    assert seedgen.qwen_lora("user-local") == local_entry(local)
    assert seedgen.default_loras("qwen2511-q4") == [] and seedgen.default_loras("qwen21-q4") == [
        {"id": "uncensored", "scale": 1.0}]
    write_registry(registry_path, [local_entry(local), hf_entry()])
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo", "user-local", "user-hf")
    os.remove(registry_path)
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo")
    assert seedgen.qwen_lora("user-hf") is None


# --- CL-T3 (CL4, CL5): an unusable file gives the built-ins and one warning per file state ---------------------

def _data(entries):
    return {"schema": "seed-edit.user-loras.v1", "loras": entries}


BAD_FILE_CASES = [
    (b"{not json", "not valid JSON"),
    ({"schema": "seed-edit.user-loras.v2", "loras": []}, "schema must be seed-edit.user-loras.v1"),
    ({"schema": "seed-edit.user-loras.v1"}, "top level must be {schema, loras}"),
    ({"schema": "seed-edit.user-loras.v1", "loras": {}}, "loras must be a list"),
    (_data([dict(hf_entry(), extra=1)]), "entry 1: keys or source are invalid"),
    (_data([dict(hf_entry(), source="local")]), "entry 1: keys or source are invalid"),
    (_data([dict(hf_entry(), id="User-X")]), "entry 1: id is invalid"),
    (_data([dict(hf_entry(), id="uncensored")]), "entry 1: id is invalid"),
    (_data([hf_entry(), hf_entry()]), "entry 2: id user-hf is listed twice"),
    (_data([dict(hf_entry(), revision="main")]), "entry 1: revision is invalid"),
    (_data([dict(hf_entry(), file="x.bin")]), "entry 1: file is invalid"),
    (_data([dict(hf_entry(), bytes=0)]), "entry 1: bytes is invalid"),
    (_data([dict(hf_entry(), default_on=True)]), "entry 1: default_on is invalid"),
    (_data([dict(hf_entry(), trigger="x  y")]), "entry 1: trigger is invalid"),
]


def test_cl_t3_an_unusable_file_gives_the_built_ins_and_one_warning(registry_path, capsys):
    os.makedirs(os.path.dirname(registry_path))
    for data, reason in BAD_FILE_CASES:
        raw = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        lib.write_bytes_atomic(registry_path, raw)
        assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS, reason
        assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS, reason
        assert seedgen.qwen_selection("qwen21-q4", None) == ("qwen21-q4", [{"id": "uncensored", "scale": 1.0}], None)
        assert seedgen.default_loras("qwen21-q4") == [{"id": "uncensored", "scale": 1.0}]
        assert [lora["id"] for lora in seedgen.registry_view()["loras"]] == ["uncensored", "viggle-turbo"]
        assert capsys.readouterr().err == (
            "seed-edit: ignoring %s: %s; only the built-in Qwen edit LoRAs are available\n" % (registry_path, reason)), reason


# --- CL-T4 (CL3, R10): the trigger rule ----------------------------------------------------------------------

def test_cl_t4_the_trigger_rule():
    for text in (TRIGGER, "a, b. c; d: 'e'! f? (g) & h/i-j", "A" * 200, "9 lives", "x"):
        assert seedgen.valid_trigger(text) is True, text
    for text in ("", "a" * 201, " a", "-a", "a ", "a  b", 'say "x"', "a\\b", "a\nb", "caf\u00e9", "<b>", "{x}",
                 "a$b", "a`b", None, 5):
        assert seedgen.valid_trigger(text) is False, text


# --- CL-T11 (CL19): the LoRA pair rule ---------------------------------------------------------------------------

def test_cl_t11_the_pair_rule():
    t = {"dtype": "F16", "shape": [4, 4], "data_offsets": [0, 32]}
    assert registry.lora_pair_count({"a.lora_A.weight": t, "a.lora_B.weight": t}) == 1
    assert registry.lora_pair_count({"a.lora_A.default.weight": t, "a.lora_B.default.weight": t}) == 1
    assert registry.lora_pair_count({"lora_unet_a.lora_down.weight": t, "lora_unet_a.lora_up.weight": t,
                                     "lora_unet_a.alpha": t}) == 1
    assert registry.lora_pair_count({"a.lora.down.weight": t, "a.lora.up.weight": t}) == 1
    assert registry.lora_pair_count(dict(pairs("x.0"), **pairs("x.1"))) == 2
    assert registry.lora_pair_count({"a.lora_A.weight": t}) == 0
    assert registry.lora_pair_count({"a.lora_B.weight": t, "a.lora_up.weight": t}) == 0
    assert registry.lora_pair_count({"a.lokr_w1": t, "a.lokr_w2": t, "a.hada_w1_a": t}) == 0
    assert registry.lora_pair_count({"__metadata__": {"format": "pt"}}) == 0
    assert registry.PAIR_SUBSTITUTIONS == ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."),
                                           (".lora.down.", ".lora.up."))


# --- CL-T14 (CL22b, CL25): lora_problem for every source -------------------------------------------------------

def test_cl_t14_lora_problem_for_every_source(env, registry_path):
    hubs = qe.qwen_hubs()
    where = " or ".join(hubs)
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    entry = local_entry(local)
    assert qe.lora_problem(entry, hubs) == (None, local)
    os.truncate(local, entry["bytes"] - 1)
    assert qe.lora_problem(entry, hubs) == (
        "%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run bin/seed-edit-lora add "
        "after bin/seed-edit-lora remove user-local)" % (local, entry["bytes"] - 1, entry["bytes"]), None)
    os.remove(local)
    assert qe.lora_problem(entry, hubs) == (
        "%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after bin/seed-edit-lora "
        "remove user-local)" % local, None)
    data = st_bytes(pairs("transformer_blocks.0.attn.to_q"))
    pinned = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), REPO, SHA, {FILE: data}), FILE)
    assert qe.lora_problem(hf_entry(size=len(data)), hubs) == (None, pinned)
    assert qe.lora_problem(hf_entry(size=len(data) + 1), hubs) == (
        "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora user-hf again)"
        % (pinned, len(data), len(data) + 1), None)
    bad = st_bytes({"transformer_blocks.0.attn.to_q.weight": {"dtype": "BF16", "shape": [4, 4], "data_offsets": [0, 16]}})
    np_path = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), "o/no-pairs", SHA, {FILE: bad}), FILE)
    assert qe.lora_problem(hf_entry("user-np", size=len(bad), repo="o/no-pairs"), hubs) == (
        "%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing (bin/seed-edit-lora "
        "remove user-np)" % np_path, None)
    junk = b"not a safetensors file at all"
    ns_path = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), "o/not-st", SHA, {FILE: junk}), FILE)
    assert qe.lora_problem(hf_entry("user-ns", size=len(junk), repo="o/not-st"), hubs) == (
        "%s is not a safetensors file (bin/seed-edit-lora remove user-ns)" % ns_path, None)
    assert qe.lora_problem(hf_entry("user-never", repo="o/never"), hubs) == (
        "%s is not in %s (run bin/seed-edit-setup --lora user-never)" % (FILE, where), None)
    unc = seedgen.qwen_lora("uncensored")
    assert qe.lora_problem(unc, hubs) == (
        "qwen-image-2.1-uncensored-lora.safetensors is not in %s (run bin/seed-edit-setup --lora uncensored)" % where,
        None)
    unc_path = st.install_lora(env, "uncensored")
    assert qe.lora_problem(unc, hubs) == (None, unc_path)


# --- CL-T15 (CL11, CL28): the trigger prefix and run_jobs ------------------------------------------------------

def test_cl_t15_trigger_prompt_and_run_jobs(env, registry_path):
    write_registry(registry_path, [hf_entry("user-a"), hf_entry("user-b", trigger="Photo Style"),
                                   hf_entry("user-c", trigger=TRIGGER.upper()), hf_entry("user-d", trigger=None)])
    tp = seedgen.trigger_prompt
    a, b, c, d = ({"id": "user-%s" % k, "scale": 1.0} for k in "abcd")
    assert tp("make it night", [b, a]) == TRIGGER + " Photo Style make it night"
    assert tp("Photo style, TRANSFORM the image to realistic photograph: make it night", [a, b]) == (
        "Photo style, TRANSFORM the image to realistic photograph: make it night")
    assert tp("photo style at dusk", [a, b]) == TRIGGER + " photo style at dusk"
    assert tp("make it night", [a, c]) == TRIGGER + " make it night"
    assert tp("", [a]) == TRIGGER and tp("   ", [a]) == TRIGGER
    assert tp("make it night", [{"id": "user-gone", "scale": 1.0}]) == "make it night"
    assert tp("make it night", [{"id": "uncensored", "scale": 1.0}]) == "make it night"
    assert tp("make it night", [d]) == "make it night" and tp("make it night", []) == "make it night"
    items = seedgen.qwen_settings("qwen2511-q4", [a])["loras"]
    assert tp("x", items) == TRIGGER + " x"
    once = tp("make it night", [a, b])
    assert tp(once, [a, b]) == once
    py, _snapshot, unc = _mflux_ready(env)
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [local_entry(local, lora_id="user-real", family="qwen21", trigger="photo style")])
    jobs = _jobs(env, _sources(env))
    before = json.loads(json.dumps(jobs))
    loras = [{"id": "user-real", "scale": 0.5}, {"id": "uncensored", "scale": 1.0}]
    results, failure = qe.run_jobs("qwen21-q4", loras, jobs, 1024, 640, "location_edit", os.path.join(env["tmp"], "work"))
    assert failure is None and [r["status"] for r in results] == ["ok"] * 3
    assert jobs == before
    (call,) = st.stub_calls(py)
    want = ["photo style " + j["prompt"] for j in jobs]
    assert [j["prompt"] for j in call["spec"]["jobs"]] == want
    assert (call["spec"]["lora_paths"], call["spec"]["lora_scales"]) == ([unc, local], [1.0, 0.5])
    assert [c["prompt"] for c in env["calls"]["safety"]] == want


# --- CL-T16 (CL31): bin/seed-edit records the triggered prompt, once ---------------------------------------------

def test_cl_t16_seed_edit_records_the_triggered_prompt_once(env, registry_path):
    py, _venv = st.mflux_venv(env)
    st.install_model(env, "qwen21-q4")
    local = safetensors(os.path.join(env["tmp"], "loras", "x.safetensors"))
    entry = local_entry(local, lora_id="user-x", family="qwen21")
    write_registry(registry_path, [entry])
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen21-q4", "--lora", "user-x=1.0", "--candidates", "2",
                                "--seed", "100", model="qwen")
    assert code == 0
    want = TRIGGER + " " + st.PROMPT
    record = st.record_of(run_dir)
    assert record["prompt"] == want and record["state"] == "done"
    assert record["loras"] == [{"id": "user-x", "source": "local", "file": "x.safetensors", "sha256": entry["sha256"],
                                "scale": 1.0, "trigger": TRIGGER}]
    (call,) = st.stub_calls(py)
    assert [job["prompt"] for job in call["spec"]["jobs"]] == [want, want]
    assert all(job["prompt"].count(TRIGGER) == 1 for job in call["spec"]["jobs"])
    assert call["spec"]["lora_paths"] == [local]
    assert [c["prompt"] for c in env["calls"]["safety"]] == [want, want]


# --- CL-T17 (CL10, D4, D5, D13): the settings items --------------------------------------------------------------

def test_cl_t17_settings_items_removed_ids_and_steps(registry_path, tmp_path):
    local = safetensors(str(tmp_path / "loras" / "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local), hf_entry("user-q21", family="qwen21", steps=30),
                                   hf_entry("user-s30", steps=30)])
    s = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-local", "scale": 1}, {"id": "user-hf", "scale": 0.5}])
    assert s["loras"] == [
        {"id": "user-hf", "repo": REPO, "revision": SHA, "file": FILE, "scale": 0.5, "trigger": TRIGGER},
        {"id": "user-local", "source": "local", "file": "real.safetensors", "sha256": local_entry(local)["sha256"],
         "scale": 1.0, "trigger": TRIGGER}]
    assert (s["steps"], s["scheduler"]) == (8, None)
    assert "repo" not in s["loras"][1] and "path" not in s["loras"][1]
    assert seedgen.qwen_settings("qwen21-q4", [{"id": "uncensored", "scale": 1}])["loras"] == [
        {"id": "uncensored", "repo": "abenzerps/Qwen-Image-2.1-Uncensored-Quantized",
         "file": "qwen-image-2.1-uncensored-lora.safetensors", "scale": 1.0}]
    gone = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-gone", "scale": 1}])
    assert gone["loras"] == [{"id": "user-gone", "scale": 1.0, "removed": True}]
    q21 = seedgen.qwen_settings("qwen21-q4", [{"id": "user-q21", "scale": 1}])
    assert (q21["steps"], q21["scheduler"]) == (30, "linear")
    s30 = seedgen.qwen_settings("qwen2511-q4", [{"id": "user-s30", "scale": 1}])
    assert (s30["steps"], s30["scheduler"]) == (30, None)
    both = seedgen.qwen_settings("qwen21-q4", [{"id": "user-q21", "scale": 1}, {"id": "viggle-turbo", "scale": 1}])
    assert (both["steps"], both["scheduler"]) == (6, "viggle_turbo")
    assert qe.generator_text("qwen2511-q4", [{"id": "user-gone", "scale": 1}]) == (
        "Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-mflux-q4) + LoRAs user-gone@1, "
        "8 steps")
    assert qe.selection_of(gone) == ("qwen2511-q4", [{"id": "user-gone", "scale": 1.0}])
    assert seedgen.registry_order([{"id": "user-gone", "scale": 1}, {"id": "user-hf", "scale": 1},
                                   {"id": "uncensored", "scale": 1}]) == [
        {"id": "uncensored", "scale": 1}, {"id": "user-hf", "scale": 1}, {"id": "user-gone", "scale": 1}]
    view = [l for l in seedgen.registry_view()["loras"] if l["id"] in ("uncensored", "user-hf", "user-local")]
    assert [(l["user"], l["source"], l["trigger"], l["setup"]) for l in view] == [
        (False, "builtin", None, "bin/seed-edit-setup --lora uncensored"),
        (True, "hf", TRIGGER, "bin/seed-edit-setup --lora user-hf"), (True, "local", TRIGGER, None)]


# --- CL-T18 (CL13, CL26, CL27): no LoRA on the diffusers model ---------------------------------------------------

def test_cl_t18_no_lora_on_the_diffusers_model(registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry("user-x")])
    no_loras = ("qwen2511-bf16 runs without LoRAs (its diffusers child loads only the built-in Lightning LoRA); "
                "use qwen2511-q4")
    assert seedgen.NO_LORAS_MSG % "qwen2511-bf16" == no_loras
    assert seedgen.qwen_selection("qwen2511-bf16", [{"id": "user-x", "scale": 1}]) == (
        None, None, "LoRA user-x: " + no_loras)
    for flag in ("--lora", "--seed-edit-lora"):
        with pytest.raises(qe.SelectionError) as info:
            qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen2511-bf16"), flag)
        assert str(info.value) == "%s user-x: %s" % (flag, no_loras)
    monkeypatch.setattr(qe, "qwen_model_problem", lambda entry: (None, {}))
    assert qe.install_problem("qwen2511-bf16", [{"id": "user-x", "scale": 1.0}]) == (no_loras, {})
    assert qe.install_problem("qwen2511-bf16", []) == (None, {"lora_paths": []})
    assert seedgen.qwen_selection("qwen2511-q4", [{"id": "user-x", "scale": 1}]) == (
        "qwen2511-q4", [{"id": "user-x", "scale": 1.0}], None)
    assert qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen2511-q4")) == [{"id": "user-x", "scale": 1.0}]
    assert qe.cli_selection("qwen2511-q4", ["user-x=0.5"], "--seed-edit-model", "--seed-edit-lora") == (
        "qwen2511-q4", [{"id": "user-x", "scale": 0.5}])
    assert seedgen.qwen_selection("qwen2511-bf16", [{"id": "uncensored", "scale": 1}]) == (
        None, None, "LoRA uncensored is for Qwen-Image-2.1, not Qwen-Image-Edit-2511 bf16 (Lightning, diffusers)")


# --- CL-T19 (CL8, CL27, CL46): a removed LoRA --------------------------------------------------------------------

def test_cl_t19_a_removed_lora(env, registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry("user-x", family="qwen21")])
    selection = seedgen.qwen_selection("qwen21-q4", [{"id": "user-x", "scale": 1}, {"id": "uncensored", "scale": 1}])[1]
    assert selection == [{"id": "uncensored", "scale": 1.0}, {"id": "user-x", "scale": 1.0}]
    write_registry(registry_path, [])
    assert seedgen.registry_order(selection[::-1]) == selection
    monkeypatch.setattr(qe, "qwen_model_problem", lambda entry: (None, {"model_path": "/m", "builtin_lora": None}))
    text = ("LoRA user-x is unavailable: it is not in the Qwen edit LoRA registry (removed?); add it again with "
            "bin/seed-edit-lora add, or choose other LoRAs")
    assert qe.install_problem("qwen21-q4", [{"id": "user-x", "scale": 1.0}]) == (text, {})
    with pytest.raises(qe.Unavailable) as info:
        qe.run_jobs("qwen21-q4", [{"id": "user-x", "scale": 1.0}], _jobs(env, _sources(env)), 1024, 640,
                    "location_edit", os.path.join(env["tmp"], "work"))
    assert str(info.value) == text
    with pytest.raises(qe.SelectionError) as info:
        qe.check_lora_args(["user-x=1"], seedgen.qwen_model("qwen21-q4"))
    assert str(info.value) == "--lora: unknown LoRA user-x; known: uncensored, viggle-turbo"
    assert seedgen.qwen_selection("qwen21-q4", [{"id": "user-x", "scale": 1}]) == (None, None, "unknown LoRA user-x")


# --- CL-T20 (CL30, CL34): the probe lists custom IDs; the lib tolerates user- IDs --------------------------------

def test_cl_t20_the_probe_and_its_tolerance(env, registry_path, tmp_path):
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    loras = env["tool"].probe()["qwen"]["loras"]
    assert list(loras) == ["uncensored", "viggle-turbo", "user-hf", "user-local"]
    assert loras["user-local"] == {"ok": True, "reason": None}
    assert loras["user-hf"] == {"ok": False, "reason": "%s is not in %s or %s (run bin/seed-edit-setup --lora user-hf)"
                                % (FILE, env["zhub"], env["hfhub"])}
    ok = {"ok": True, "reason": None}
    models = dict((i, ok) for i in seedgen.QWEN_MODEL_IDS)
    builtins = dict((i, ok) for i in seedgen.BUILTIN_QWEN_LORA_IDS)

    def printed(found):
        return {"zimage": {"ok": True, "reason": None, "backend": "zimage"},
                "qwen": {"ok": True, "reason": None, "models": models, "loras": found}}

    ids = seedgen.BUILTIN_QWEN_LORA_IDS + ("user-a", "user-b")
    reported = dict(builtins, **{"user-b": {"ok": False, "reason": "gone"}, "user-zz": ok})
    found, detail = lib.seed_edit_check(probe_workspace(tmp_path, printed(reported)), seedgen.QWEN_MODEL_IDS, ids)
    assert detail is None
    assert found["qwen"]["loras"] == dict(builtins, **{
        "user-a": {"ok": False, "reason": lib.PROBE_NOT_REPORTED}, "user-b": {"ok": False, "reason": "gone"}})
    no_viggle = dict(builtins)
    del no_viggle["viggle-turbo"]
    for loras in (no_viggle, dict(builtins, extra=ok)):
        assert lib.seed_edit_check(probe_workspace(tmp_path, printed(loras)), seedgen.QWEN_MODEL_IDS, ids) == (
            None, "bin/seed-edit --probe printed unparsable output")
    assert lib.USER_LORA_PREFIX == "user-"
    assert lib.PROBE_NOT_REPORTED == (
        "not reported by this workspace's bin/seed-edit --probe (it may predate custom LoRAs)")


# --- CL-T21 (CL32, CL33): bin/seed-edit-setup for custom IDs -----------------------------------------------------

def test_cl_t21_setup_for_custom_ids(setup_env, registry_path, capsys):
    e = setup_env
    setup, rec = e["setup"], e["rec"]
    local = safetensors(os.path.join(e["tmp"], "loras", "local.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    rec["free"] = 1.0
    where = min(setup.existing_ancestor(e["hub"]), setup.existing_ancestor(os.path.dirname(e["venv"])))
    assert setup.main(["--lora", "user-hf"]) == 2
    assert capsys.readouterr().err == (
        "Error: only 1.0 GiB free on %s; seed-edit-setup needs at least 4.3 GiB more (4.3 GiB in all, 0.0 GiB "
        "already present; user-hf ~0.33 GiB, mflux venv ~3 GiB, 1 GiB headroom)\n" % where)
    rec["free"] = 100.0
    assert setup.main(["--lora", "user-hf"]) == 0
    assert st.downloads(rec) == [[{"kind": "file", "repo": REPO, "revision": SHA, "file": FILE}]]
    out = capsys.readouterr().out.splitlines()
    assert "seed-edit-setup: license: user-hf: apache-2.0" in out
    assert "seed-edit-setup: LoRA user-hf (%s) is not in %s" % (FILE, e["hub"]) in out
    st.mark_ready(e)
    rec["call"] = []
    assert setup.main(["--lora", "user-local"]) == 0
    out = capsys.readouterr().out.splitlines()
    line = "seed-edit-setup: LoRA user-local (local) %s: 0.00 GiB" % local
    assert rec["call"] == [] and "seed-edit-setup: nothing to do" in out and line in out
    assert out.index(line) < [i for i, text in enumerate(out) if text.startswith("seed-edit-setup: free on ")][0]
    os.remove(local)
    assert setup.main(["--lora", "user-local"]) == 0
    assert ("seed-edit-setup: LoRA user-local (local): %s is missing or not a regular file (restore it, or re-run "
            "bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)" % local) in (
        capsys.readouterr().out.splitlines())
    bad = st_bytes({"transformer_blocks.0.attn.to_q.weight": {"dtype": "BF16", "shape": [4, 4], "data_offsets": [0, 16]}})
    pinned = os.path.join(st.pinned_cache(os.path.join(e["tmp"], "zi"), REPO, SHA, {FILE: bad}), FILE)
    write_registry(registry_path, [hf_entry(size=len(bad))])
    unusable = ("seed-edit-setup: LoRA user-hf is unusable: %s has no LoRA weight pairs in its safetensors header, so "
                "mflux would apply nothing (bin/seed-edit-lora remove user-hf)" % pinned)
    error = ("Error: 1 custom LoRA file(s) failed the safetensors check (listed above); remove them with "
             "bin/seed-edit-lora remove ID\n")
    assert setup.main(["--lora", "user-hf"]) == 1
    captured = capsys.readouterr()
    assert "seed-edit-setup: nothing to do" in captured.out.splitlines() and unusable in captured.out.splitlines()
    assert captured.err == error
    rec["ready"] = False
    assert setup.main(["--lora", "user-hf"]) == 1
    captured = capsys.readouterr()
    assert "seed-edit-setup: nothing to do" not in captured.out.splitlines() and unusable in captured.out.splitlines()
    assert captured.err == error
    assert setup.main(["--lora", "user-nope"]) == 2
    assert capsys.readouterr().err == "Error: unknown --lora user-nope; known: uncensored, viggle-turbo, user-hf\n"


# --- CL-T23 (CL5): the reader caches by the file's stat ---------------------------------------------------------

def test_cl_t23_the_reader_caches_by_stat(registry_path, monkeypatch):
    write_registry(registry_path, [hf_entry()])
    opened = []
    real_open = open

    def counting_open(path, *args, **kwargs):
        opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(seedgen, "open", counting_open, raising=False)
    assert seedgen.qwen_lora_ids()[-1] == "user-hf"
    assert seedgen.qwen_lora_ids()[-1] == "user-hf"
    assert seedgen.user_loras() == (hf_entry(),)
    assert opened == [registry_path]
    write_registry(registry_path, [hf_entry("user-new")])
    assert seedgen.qwen_lora_ids()[-1] == "user-new"
    assert opened == [registry_path, registry_path]


# --- Review Focus 1: a moved local LoRA refuses before the child -------------------------------------------------

def test_cl_review_focus_1_a_moved_local_lora_refuses_before_the_child(env, registry_path):
    py, _venv = st.mflux_venv(env)
    st.install_model(env, "qwen2511-q4")
    local = safetensors(os.path.join(env["tmp"], "Volumes", "Drive", "real.safetensors"))
    entry = local_entry(local)
    write_registry(registry_path, [entry])
    os.remove(local)
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen2511-q4", "--lora", "user-local=1.0", "--candidates", "1",
                                model="qwen")
    assert code == 2
    record = st.record_of(run_dir)
    assert (record["state"], record["error"]) == (
        "failed", "LoRA real.safetensors is unavailable: %s is missing or not a regular file (restore it, or re-run "
                  "bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)" % local)
    assert [c["status"] for c in record["candidates"]] == ["failed"]
    safetensors(local, pairs("x"))
    size = os.path.getsize(local)
    assert size != entry["bytes"]
    code, run_dir = st.run_tool(env, "--qwen-model", "qwen2511-q4", "--lora", "user-local=1.0", "--candidates", "1",
                                model="qwen", run=st.R2)
    assert code == 2
    assert st.record_of(run_dir)["error"] == (
        "LoRA real.safetensors is unavailable: %s is %d bytes; the registry recorded %d (the file changed since it "
        "was added: re-run bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)"
        % (local, size, entry["bytes"]))
    assert st.stub_calls(py) == []
```

- [ ] **Step 2: Run the new file to verify it fails.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'seed_lora_registry'` (`1 error`).

- [ ] **Step 3: E1, `tests/conftest.py` (first: the new tests need the isolation variable to survive the helpers).** Edit; old:

```python
@pytest.fixture(autouse=True)
def lora_catalog_isolation(monkeypatch, tmp_path):
    path = str(tmp_path / "lora_catalog_isolation")
    monkeypatch.setenv("LORA_CATALOG_DIR", path)
    return path
```

new:

```python
@pytest.fixture(autouse=True)
def lora_catalog_isolation(monkeypatch, tmp_path):
    path = str(tmp_path / "lora_catalog_isolation")
    monkeypatch.setenv("LORA_CATALOG_DIR", path)
    return path


@pytest.fixture(autouse=True)
def seed_lora_isolation(monkeypatch, tmp_path):
    """Custom edit LoRAs spec CL52: every test sees no custom Qwen edit LoRA unless it writes one."""
    path = str(tmp_path / "seed_lora_isolation" / "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
    return path
```

- [ ] **Step 4: E2, the nine helpers.** In each of these nine files, one Edit (each file has exactly one occurrence); old:

```python
        if key.startswith("SEED_EDIT_"):
```

new:

```python
        if key.startswith("SEED_EDIT_") and key != "SEED_EDIT_USER_LORAS":
```

The nine files: `tests/test_ltx_movie_extra_refs.py`, `tests/test_ltx_movie_seed_edit.py`, `tests/test_qwen_edit.py`, `tests/test_ltx_movie_cast_refs.py`, `tests/test_ltx_movie_shots_seed.py`, `tests/test_movie_ui_seedgen.py`, `tests/test_seed_edit_tool.py`, `tests/test_movie_ui_qwen_edit.py`, `tests/test_ltx_movie_seed_context.py`. Then confirm:

Run: `grep -c 'if key.startswith("SEED_EDIT_") and key != "SEED_EDIT_USER_LORAS":' tests/test_ltx_movie_extra_refs.py tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_shots_seed.py tests/test_movie_ui_seedgen.py tests/test_seed_edit_tool.py tests/test_movie_ui_qwen_edit.py tests/test_ltx_movie_seed_context.py; grep -rn 'if key.startswith("SEED_EDIT_"):' tests/ | wc -l`
Expected: nine lines ending `:1`, then `0`.

- [ ] **Step 5: Create `seed_lora_registry.py` (the run-time checks; CL19, CL22b).** Write exactly this content (Task 2 replaces the file whole):

```python
"""seed_lora_registry -- the run-time checks of the custom (user-added) Qwen edit LoRAs
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md, Sections 2.2 and 3.3): the LoRA pair rule of
a safetensors header (CL19), a local LoRA's presence and size, and a downloaded Hugging Face LoRA's size and
header (CL22b). qwen_edit.lora_problem and bin/seed-edit-setup import it inside the functions that use it.

Standard library plus lora_catalog (its read_safetensors_header, reused unchanged). Valid on Python 3.9 and
3.13; %-formatting only.
"""

import os

import lora_catalog

PAIR_SUBSTITUTIONS = ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."), (".lora.down.", ".lora.up."))
M_LOCAL_MISSING = ("%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after "
                   "bin/seed-edit-lora remove %s)")
M_LOCAL_CHANGED = ("%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run "
                   "bin/seed-edit-lora add after bin/seed-edit-lora remove %s)")
M_HF_SIZE = "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora %s again)"
M_HF_NOT_ST = "%s is not a safetensors file (bin/seed-edit-lora remove %s)"
M_HF_NO_PAIRS = ("%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing "
                 "(bin/seed-edit-lora remove %s)")


def lora_pair_count(header):
    """Custom edit LoRAs spec CL19 (D6): the number of header keys K for which one PAIR_SUBSTITUTIONS swap on
    K + "." (first occurrence) names another key of the header."""
    count = 0
    for key in header:
        probe = key + "."
        for a, b in PAIR_SUBSTITUTIONS:
            if a in probe and probe.replace(a, b, 1)[:-1] in header:
                count += 1
                break
    return count


def local_problem(lora):
    """Custom edit LoRAs spec CL22b: None when a local custom LoRA's file is still a regular file of its recorded
    size (no hash, no header read), else the refusal text."""
    real = os.path.realpath(lora["path"])
    if not os.path.isfile(real):
        return M_LOCAL_MISSING % (lora["path"], lora["id"])
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_LOCAL_CHANGED % (lora["path"], size, lora["bytes"], lora["id"])
    return None


def downloaded_problem(lora, path):
    """Custom edit LoRAs spec CL22b: None when the downloaded file at path of a Hugging Face custom LoRA has its
    recorded size and a safetensors header with LoRA pairs, else the refusal text."""
    real = os.path.realpath(path)
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_HF_SIZE % (path, size, lora["bytes"], lora["id"])
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        return M_HF_NOT_ST % (path, lora["id"])
    if lora_pair_count(header) == 0:
        return M_HF_NO_PAIRS % (path, lora["id"])
    return None
```

- [ ] **Step 6: `movie_ui_seedgen.py`: the docstring and imports (CL14, D16).** Edit; old:

```python
"""movie_ui_seedgen -- the seed generator's pure core: the Seeds tab's request rules, the seed
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1), and the
fixed Qwen model and LoRA registry with its selection rules
(docs/superpowers/specs/2026-11-02-seed-models-design.md, Sections 2 and 5.1). bin/seed-edit and
bin/seed-edit-setup import the registry from here; the page gets it through the capability.

Standard library plus movie_ui_lib only (SG1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits.
"""

import re
import secrets
import time

import movie_ui_lib as lib
```

new:

```python
"""movie_ui_seedgen -- the seed generator's pure core: the Seeds tab's request rules, the seed
folder rule, the run ID, Keep's file names and the seed_edit capability shape
(docs/superpowers/specs/2026-11-02-seed-generator-design.md, deliverable G4, Section 5.1), and the
Qwen model and LoRA registry with its selection rules
(docs/superpowers/specs/2026-11-02-seed-models-design.md, Sections 2 and 5.1). The registry is the
fixed models, the built-in LoRAs and the custom LoRAs read from user_loras_path()
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md); bin/seed-edit and
bin/seed-edit-setup import it from here; the page gets it through the capability.

Standard library plus movie_ui_lib only (SG1). Valid on Python 3.9 and 3.13. This module never
writes and never starts a process. Every function is pure except new_run_id, which reads the
clock and draws random digits, and the registry lookups, which read the custom LoRA file through
user_loras (cached by its stat; an unusable file is warned about once on stderr).
"""

import json
import os
import re
import secrets
import sys
import threading
import time

import movie_ui_lib as lib
```

- [ ] **Step 7: `movie_ui_seedgen.py`: the built-in names (CL1).** Two Edits.

Old: `QWEN_LORAS = (` — new: `BUILTIN_QWEN_LORAS = (`

Old: `QWEN_LORA_IDS = tuple(l["id"] for l in QWEN_LORAS)` — new: `BUILTIN_QWEN_LORA_IDS = tuple(l["id"] for l in BUILTIN_QWEN_LORAS)`

- [ ] **Step 8: `movie_ui_seedgen.py`: the constants (CL1, CL5).** Edit; old:

```python
HF_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
```

new:

```python
HF_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
# Custom edit LoRAs spec CL1: the registry file of the custom (user-added) Qwen edit LoRAs.
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
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_USER_LOCK = threading.Lock()
_USER_CACHE = {"key": None, "loras": ()}     # CL5: the last file state read and its entries
```

- [ ] **Step 9: `movie_ui_seedgen.py`: `qwen_selection` (CL9, CL13).** Two Edits.

Old:

```python
        if not (isinstance(lora_id, str) and lora_id in QWEN_LORA_IDS):
```

new:

```python
        if not (isinstance(lora_id, str) and lora_id in qwen_lora_ids()):
```

Old:

```python
            return None, None, "LoRA %s is for %s, not %s" % (lora_id, QWEN_FAMILIES[lora["family"]], entry["label"])
        if not (lib._is_number(scale) and 0 < scale <= SCALE_MAX):
```

new:

```python
            return None, None, "LoRA %s is for %s, not %s" % (lora_id, QWEN_FAMILIES[lora["family"]], entry["label"])
        if entry["backend"] == "diffusers":
            return None, None, "LoRA %s: " % lora_id + NO_LORAS_MSG % entry["id"]
        if not (lib._is_number(scale) and 0 < scale <= SCALE_MAX):
```

- [ ] **Step 10: `movie_ui_seedgen.py`: the registry file, the accessors, the items and the trigger (CL2-CL8, CL10, CL11, SC5).** Edit; old (from `def qwen_lora` through the end of `qwen_settings`):

```python
def qwen_lora(lora_id):
    """Seed models SQ5: the QWEN_LORAS entry whose id is lora_id, else None."""
    for entry in QWEN_LORAS:
        if entry["id"] == lora_id:
            return entry
    return None


def registry_order(loras):
    """Seed models SQ5: a [{"id", "scale"}] list sorted by each id's place in QWEN_LORA_IDS."""
    return sorted(loras, key=lambda item: QWEN_LORA_IDS.index(item["id"]))


def default_loras(model_id):
    """Seed models SQ6: the default-on LoRAs of model_id's family, [{"id", "scale"}]."""
    family = qwen_model(model_id)["family"]
    return [{"id": lora["id"], "scale": lora["default_scale"]} for lora in QWEN_LORAS
            if lora["default_on"] and lora["family"] == family]


def qwen_settings(model_id, loras):
    """Seed models SQ7: {"qwen_model", "loras", "steps", "scheduler"} of a selection (model_id None
    for Z-Image). A LoRA with its own steps (the first in registry order) sets steps and scheduler."""
    if model_id is None:
        return {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    entry = qwen_model(model_id)
    steps, scheduler, turbo, out = entry["steps"], entry["scheduler"], None, []
    for item in registry_order(loras):
        lora = qwen_lora(item["id"])
        out.append({"id": lora["id"], "repo": lora["repo"], "file": lora["file"], "scale": float(item["scale"])})
        if turbo is None and lora["steps"] is not None:
            turbo = lora
    if turbo is not None:
        steps, scheduler = turbo["steps"], turbo["scheduler"]
    return {"qwen_model": {"id": entry["id"], "repo": entry["repo"]}, "loras": out, "steps": steps,
            "scheduler": scheduler}
```

new:

```python
def user_loras_path():
    """Custom edit LoRAs spec CL2 (D8): $SEED_EDIT_USER_LORAS when set and non-empty, else this workspace's
    generated/seed_loras/user_loras.json."""
    return os.environ.get(USER_LORAS_ENV) or os.path.join(os.path.dirname(os.path.realpath(__file__)), "generated",
                                                          "seed_loras", "user_loras.json")


def valid_trigger(text):
    """Custom edit LoRAs spec CL3 (D1): a str of TRIGGER_RE with no double and no trailing space."""
    return (isinstance(text, str) and TRIGGER_RE.fullmatch(text) is not None and "  " not in text
            and not text.endswith(" "))


def _plain_text(value, most):
    """A str of 1 to most characters with no character below a space and no DEL."""
    return (isinstance(value, str) and 1 <= len(value) <= most
            and not any(c < "\x20" or c == "\x7f" for c in value))


def _entry_problem(i, entry, seen):
    """Custom edit LoRAs spec CL4 rule 4: why entry i (1-based) of a registry file is invalid, or None. seen
    collects the ids of the entries before it."""
    source = entry.get("source") if isinstance(entry, dict) else None
    keys = {"hf": HF_KEYS, "local": LOCAL_KEYS}.get(source) if isinstance(source, str) else None
    if keys is None or set(entry) != set(keys):
        return "entry %d: keys or source are invalid" % i
    bad = "entry %d: %s is invalid"
    lora_id = entry["id"]
    if not (isinstance(lora_id, str) and USER_ID_RE.fullmatch(lora_id) and lora_id not in BUILTIN_QWEN_LORA_IDS):
        return bad % (i, "id")
    if lora_id in seen:
        return "entry %d: id %s is listed twice" % (i, lora_id)
    seen.add(lora_id)
    if not _plain_text(entry["label"], LABEL_MAX):
        return bad % (i, "label")
    if not (isinstance(entry["family"], str) and entry["family"] in QWEN_FAMILIES):
        return bad % (i, "family")
    if source == "hf":
        repo, revision, name = entry["repo"], entry["revision"], entry["file"]
        if not (isinstance(repo, str) and HF_REPO_RE.fullmatch(repo) and ".." not in repo and "--" not in repo):
            return bad % (i, "repo")
        if not (isinstance(revision, str) and _REVISION_RE.fullmatch(revision)):
            return bad % (i, "revision")
        if not (isinstance(name, str) and HF_FILE_RE.fullmatch(name) and ".." not in name.split("/")
                and name.lower().endswith(".safetensors")):
            return bad % (i, "file")
    else:
        path = entry["path"]
        if not (isinstance(path, str) and os.path.isabs(path) and not any(c < "\x20" for c in path)
                and path.lower().endswith(".safetensors")):
            return bad % (i, "path")
        if entry["file"] != os.path.basename(path):
            return bad % (i, "file")
        if not (isinstance(entry["sha256"], str) and _SHA256_RE.fullmatch(entry["sha256"])):
            return bad % (i, "sha256")
    if not (lib._is_int(entry["bytes"]) and 1 <= entry["bytes"] <= USER_LORA_MAX_BYTES):
        return bad % (i, "bytes")
    if entry["default_on"] is not False:
        return bad % (i, "default_on")
    if not (lib._is_number(entry["default_scale"]) and 0 < entry["default_scale"] <= SCALE_MAX):
        return bad % (i, "default_scale")
    if not (isinstance(entry["license"], str) and 1 <= len(entry["license"]) <= LICENSE_MAX):
        return bad % (i, "license")
    steps = entry["steps"]
    if not (steps is None or (lib._is_int(steps) and 1 <= steps <= STEPS_MAX)):
        return bad % (i, "steps")
    if entry["scheduler"] is not None:
        return bad % (i, "scheduler")
    if not (entry["trigger"] is None or valid_trigger(entry["trigger"])):
        return bad % (i, "trigger")
    if entry["user"] is not True:
        return bad % (i, "user")
    return None


def user_loras_problem(data):
    """Custom edit LoRAs spec CL4: None when data is a valid registry file, else the first failing rule's reason."""
    if not (isinstance(data, dict) and set(data) == {"schema", "loras"}):
        return "top level must be {schema, loras}"
    if data["schema"] != USER_LORAS_SCHEMA:
        return "schema must be seed-edit.user-loras.v1"
    if not isinstance(data["loras"], list):
        return "loras must be a list"
    seen = set()
    for i, entry in enumerate(data["loras"], 1):
        problem = _entry_problem(i, entry, seen)
        if problem is not None:
            return problem
    return None


def _ignored(key, path, reason):
    """Custom edit LoRAs spec CL5: warn once for this file state, remember it, and give no custom LoRA."""
    sys.stderr.write(USER_LORAS_WARNING % (path, reason) + "\n")
    sys.stderr.flush()
    _USER_CACHE["key"], _USER_CACHE["loras"] = key, ()
    return ()


def user_loras():
    """Custom edit LoRAs spec CL5: the entries of the registry file as a tuple; () when it is missing (no warning)
    or unusable (one warning per file state). Cached by (path, mtime_ns, size, inode); thread-safe; never raises."""
    path = user_loras_path()
    with _USER_LOCK:
        try:
            info = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return ()
        except OSError as e:
            key = (path, "stat", str(e))
            if _USER_CACHE["key"] == key:
                return ()
            return _ignored(key, path, "cannot read: %s" % e)
        key = (path, info.st_mtime_ns, info.st_size, info.st_ino)
        if _USER_CACHE["key"] == key:
            return _USER_CACHE["loras"]
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            return _ignored(key, path, "cannot read: %s" % e)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            return _ignored(key, path, "not valid JSON")
        reason = user_loras_problem(data)
        if reason is not None:
            return _ignored(key, path, reason)
        _USER_CACHE["key"], _USER_CACHE["loras"] = key, tuple(data["loras"])
        return _USER_CACHE["loras"]


def qwen_loras():
    """Custom edit LoRAs spec CL6: the registry's LoRAs: BUILTIN_QWEN_LORAS, then the custom LoRAs in file order."""
    return BUILTIN_QWEN_LORAS + user_loras()


def qwen_lora_ids():
    """Custom edit LoRAs spec CL6: the ids of qwen_loras(), in order."""
    return tuple(l["id"] for l in qwen_loras())


def qwen_lora(lora_id):
    """Seed models SQ5 (custom edit LoRAs spec CL7): the registry LoRA whose id is lora_id, else None."""
    for entry in qwen_loras():
        if entry["id"] == lora_id:
            return entry
    return None


def registry_order(loras):
    """Seed models SQ5 (custom edit LoRAs spec CL8): a list of {"id", ...} items sorted by each id's place in
    qwen_lora_ids(); an id that is no longer in the registry sorts after every known id."""
    ids = qwen_lora_ids()
    return sorted(loras, key=lambda item: ids.index(item["id"]) if item["id"] in ids else len(ids))


def default_loras(model_id):
    """Seed models SQ6: the default-on LoRAs of model_id's family, [{"id", "scale"}] (a custom LoRA is never
    default-on)."""
    family = qwen_model(model_id)["family"]
    return [{"id": lora["id"], "scale": lora["default_scale"]} for lora in qwen_loras()
            if lora["default_on"] and lora["family"] == family]


def settings_item(lora, scale):
    """Custom edit LoRAs spec CL10 (D4): the recorded item of one selected registry LoRA."""
    if not lora.get("user"):
        return {"id": lora["id"], "repo": lora["repo"], "file": lora["file"], "scale": scale}
    if lora["source"] == "local":
        return {"id": lora["id"], "source": "local", "file": lora["file"], "sha256": lora["sha256"],
                "scale": scale, "trigger": lora["trigger"]}
    return {"id": lora["id"], "repo": lora["repo"], "revision": lora["revision"], "file": lora["file"],
            "scale": scale, "trigger": lora["trigger"]}


def qwen_settings(model_id, loras):
    """Seed models SQ7 (custom edit LoRAs spec CL10): {"qwen_model", "loras", "steps", "scheduler"} of a
    selection (model_id None for Z-Image). Each item is settings_item's; an id no longer in the registry is
    {"id", "scale", "removed": True} (D5). The first LoRA in registry order with its own steps sets steps and
    its scheduler, or keeps the model's scheduler when its own is None (D13)."""
    if model_id is None:
        return {"qwen_model": None, "loras": [], "steps": None, "scheduler": None}
    entry = qwen_model(model_id)
    steps, scheduler, turbo, out = entry["steps"], entry["scheduler"], None, []
    for item in registry_order(loras):
        lora = qwen_lora(item["id"])
        if lora is None:
            out.append({"id": item["id"], "scale": float(item["scale"]), "removed": True})
            continue
        out.append(settings_item(lora, float(item["scale"])))
        if turbo is None and lora["steps"] is not None:
            turbo = lora
    if turbo is not None:
        steps = turbo["steps"]
        scheduler = turbo["scheduler"] if turbo["scheduler"] is not None else entry["scheduler"]
    return {"qwen_model": {"id": entry["id"], "repo": entry["repo"]}, "loras": out, "steps": steps,
            "scheduler": scheduler}


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

- [ ] **Step 11: `movie_ui_seedgen.py`: `registry_view` (CL12).** Edit; old:

```python
    loras = [{"id": lora["id"], "label": lora["label"], "family": lora["family"], "default_on": lora["default_on"],
              "default_scale": lora["default_scale"], "steps": lora["steps"], "scheduler": lora["scheduler"],
              "license": lora["license"], "setup": "bin/seed-edit-setup --lora %s" % lora["id"]} for lora in QWEN_LORAS]
```

new:

```python
    loras = [{"id": lora["id"], "label": lora["label"], "family": lora["family"], "default_on": lora["default_on"],
              "default_scale": lora["default_scale"], "steps": lora["steps"], "scheduler": lora["scheduler"],
              "license": lora["license"], "user": bool(lora.get("user")), "source": lora.get("source", "builtin"),
              "trigger": lora.get("trigger"),
              "setup": None if lora.get("source") == "local" else "bin/seed-edit-setup --lora %s" % lora["id"]}
             for lora in qwen_loras()]
```

- [ ] **Step 12: Run the pure-module tests.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py -k "cl_t1_ or cl_t2_ or cl_t3_ or cl_t4_ or cl_t11_ or cl_t17_ or cl_t23_" 2>&1 | tail -3`
Expected: `7 passed` (the other tests are deselected).

- [ ] **Step 13: `qwen_edit.py`: the docstring (CL29).** Edit; old:

```python
Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python), SEED_EDIT_QWENEDIT_SCRIPT
(default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The mflux weights and LoRAs are looked up only at
their pinned revisions, in the Z-Image hub and then the default hub.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib and movie_ui_seedgen;
PIL, psutil and content_safety are imported inside the functions that use them.
```

new:

```python
Environment: SEED_EDIT_MFLUX_PYTHON (default ~/mflux-edit/.venv/bin/python), SEED_EDIT_QWENEDIT_SCRIPT
(default <ws>/character_dataset.py), HF_HUB_CACHE and HF_HOME (the default hub), Z_IMAGE_HF_HOME (the
Z-Image hub, through movie_ui_lib.zimage_hub) and HOME. The LoRAs come from movie_ui_seedgen.qwen_loras():
the built-ins plus the custom LoRAs of bin/seed-edit-lora
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md). The mflux weights, the built-in LoRAs and
the Hugging Face custom LoRAs are looked up only at their pinned revisions, in the Z-Image hub and then the
default hub; a local custom LoRA is used at its recorded path.

Python 3.9 and 3.13. The top level imports only the standard library, movie_ui_lib and movie_ui_seedgen;
PIL, psutil, content_safety and seed_lora_registry are imported inside the functions that use them.
```

- [ ] **Step 14: `qwen_edit.py`: `lora_problem` (CL25).** Edit; old:

```python
def lora_problem(lora, hubs):
    """Seed models SQ16: (None, snapshot path) of a registry LoRA's pinned file, else (problem, None)."""
    path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
    if path is None:
        return ("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]),
                None)
    return None, path
```

new:

```python
def lora_problem(lora, hubs):
    """Seed models SQ16 (custom edit LoRAs spec CL25): (None, path) of a registry LoRA's file, else (problem,
    None). A local custom LoRA is its recorded path once seed_lora_registry.local_problem passes; any other LoRA
    is its pinned snapshot file, which for a custom one must also pass seed_lora_registry.downloaded_problem."""
    if lora.get("source") == "local":
        import seed_lora_registry
        problem = seed_lora_registry.local_problem(lora)
        return (problem, None) if problem is not None else (None, lora["path"])
    path = pinned_file(lora["repo"], lora["revision"], lora["file"], hubs)
    if path is None:
        return ("%s is not in %s (run bin/seed-edit-setup --lora %s)" % (lora["file"], " or ".join(hubs), lora["id"]),
                None)
    if lora.get("user"):
        import seed_lora_registry
        problem = seed_lora_registry.downloaded_problem(lora, path)
        if problem is not None:
            return problem, None
    return None, path
```

- [ ] **Step 15: `qwen_edit.py`: `check_lora_args` (CL26).** Two Edits.

Old:

```python
        if lora_id not in seedgen.QWEN_LORA_IDS:
            raise SelectionError("%s: unknown LoRA %s; known: %s" % (flag, lora_id, ", ".join(seedgen.QWEN_LORA_IDS)))
```

new:

```python
        known = seedgen.qwen_lora_ids()
        if lora_id not in known:
            raise SelectionError("%s: unknown LoRA %s; known: %s" % (flag, lora_id, ", ".join(known)))
```

Old:

```python
            raise SelectionError("%s %s is for %s, not %s" % (flag, lora_id, seedgen.QWEN_FAMILIES[lora["family"]],
                                                              entry["label"]))
```

new:

```python
            raise SelectionError("%s %s is for %s, not %s" % (flag, lora_id, seedgen.QWEN_FAMILIES[lora["family"]],
                                                              entry["label"]))
        if entry["backend"] == "diffusers":
            raise SelectionError("%s %s: " % (flag, lora_id) + seedgen.NO_LORAS_MSG % entry["id"])
```

- [ ] **Step 16: `qwen_edit.py`: `install_problem` (CL27).** Edit; old:

```python
    if problem is not None:
        return "%s is unavailable: %s" % (entry["label"], problem), {}
    lora_paths = []
    for item in seedgen.registry_order(loras):
        lora = seedgen.qwen_lora(item["id"])
        problem, path = lora_problem(lora, qwen_hubs())
```

new:

```python
    if problem is not None:
        return "%s is unavailable: %s" % (entry["label"], problem), {}
    if loras and entry["backend"] == "diffusers":
        return seedgen.NO_LORAS_MSG % entry["id"], {}          # custom edit LoRAs spec CL27
    lora_paths = []
    for item in seedgen.registry_order(loras):
        lora = seedgen.qwen_lora(item["id"])
        if lora is None:
            return "LoRA %s is unavailable: %s" % (item["id"], seedgen.REMOVED_MSG), {}
        problem, path = lora_problem(lora, qwen_hubs())
```

- [ ] **Step 17: `qwen_edit.py`: the trigger prefix in `run_jobs` (CL28).** Edit; old:

```python
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16). A job may also
    carry "sources", the list of its reference images in order, whose first item is its "source" (cast refs spec
    CR3); the child then edits with every listed image."""
    entry = seedgen.qwen_model(model_id)
```

new:

```python
    """Run one Qwen edit child over jobs and screen every output (qwen edit models spec QE13-QE16). A job may also
    carry "sources", the list of its reference images in order, whose first item is its "source" (cast refs spec
    CR3); the child then edits with every listed image. Every job's prompt first gets the triggers of the
    selected LoRAs in front (movie_ui_seedgen.trigger_prompt, custom edit LoRAs spec CL28), so the child, content
    safety and mflux_spec.json see the triggered text; the callers' job dicts are not changed."""
    entry = seedgen.qwen_model(model_id)
    jobs = [dict(job, prompt=seedgen.trigger_prompt(job["prompt"], loras)) for job in jobs]
```

- [ ] **Step 18: Run the qwen_edit tests of the new file.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py -k "cl_t14_ or cl_t15_ or cl_t18_ or cl_t19_" 2>&1 | tail -3`
Expected: `4 passed`.

- [ ] **Step 19: `bin/seed-edit`: the docstring, the probe and `run.json` (CL30, CL31).** Three Edits.

Old:

```python
--model qwen runs qwen2511-q4, as a job queued before the registry did. Each --lora ID=SCALE
(uncensored, viggle-turbo; 0 < SCALE <= 2) must be of the model's family; viggle-turbo sets 6
steps and scheduler viggle_turbo. Every candidate of every model is screened with content
safety before it gets its final name. --probe prints one JSON line {"qwen": {"ok", "reason",
```

new:

```python
--model qwen runs qwen2511-q4, as a job queued before the registry did. Each --lora ID=SCALE (a
registry LoRA: uncensored, viggle-turbo or a custom user-* LoRA of bin/seed-edit-lora; 0 < SCALE
<= 2) must be of the model's family; viggle-turbo sets 6 steps and scheduler viggle_turbo; a
custom LoRA's trigger is prepended to the prompt. Every candidate of every model is screened with
content safety before it gets its final name. --probe prints one JSON line {"qwen": {"ok", "reason",
```

Old:

```python
    for lora in seedgen.QWEN_LORAS:
```

new:

```python
    for lora in seedgen.qwen_loras():
```

Old:

```python
            "state": "running", "prompt": opts["prompt"], "model": opts["model"], "backend": None,
```

new:

```python
            "state": "running", "prompt": seedgen.trigger_prompt(opts["prompt"], opts["loras"]),
            "model": opts["model"], "backend": None,
```

- [ ] **Step 20: Run the bin/seed-edit tests of the new file.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py -k "cl_t16_ or review_focus_1_" 2>&1 | tail -3`
Expected: `2 passed`.

- [ ] **Step 21: `bin/seed-edit-setup`: the docstring (CL33).** Two Edits.

Old:

```python
venv and those LoRAs only). --model takes qwen21-q4, qwen21-q8, qwen21-bf16 or qwen2511-q4;
qwen2511-bf16 is refused (it runs the diffusers weights of the default Hugging Face cache).
```

new:

```python
venv and those LoRAs only). --model takes qwen21-q4, qwen21-q8, qwen21-bf16 or qwen2511-q4;
qwen2511-bf16 is refused (it runs the diffusers weights of the default Hugging Face cache). --lora
also accepts the custom user-* IDs of bin/seed-edit-lora
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md): a Hugging Face one is downloaded
like a built-in and its safetensors header is checked after the download; a local one is only
reported.
```

Old:

```python
Exit codes: 0 done or nothing to do; 1 a step failed, or an orphan partial blob still blocks a
pinned snapshot; 2 a precondition failed.
Standard library plus movie_ui_lib and movie_ui_seedgen. Python 3.9 and 3.13.
```

new:

```python
Exit codes: 0 done or nothing to do; 1 a step failed, an orphan partial blob still blocks a pinned
snapshot, or a downloaded custom LoRA file failed the safetensors check; 2 a precondition failed.
Standard library plus movie_ui_lib and movie_ui_seedgen (seed_lora_registry inside the functions
that use it). Python 3.9 and 3.13.
```

- [ ] **Step 22: `bin/seed-edit-setup`: the constant, `selection` and `items_of` (CL32).** Three Edits.

Old: `HEADROOM_GIB = 1.0` — new (two lines):

```python
HEADROOM_GIB = 1.0
UNUSABLE_MSG = ("%d custom LoRA file(s) failed the safetensors check (listed above); remove them with "
                "bin/seed-edit-lora remove ID")
```

Old:

```python
    for lora_id in loras:
        if lora_id not in seedgen.QWEN_LORA_IDS:
            return None, "unknown --lora %s; known: %s" % (lora_id, ", ".join(seedgen.QWEN_LORA_IDS))
```

new:

```python
    known = seedgen.qwen_lora_ids()
    for lora_id in loras:
        if lora_id not in known:
            return None, "unknown --lora %s; known: %s" % (lora_id, ", ".join(known))
```

Old:

```python
    for lora_id in loras:
        lora = seedgen.qwen_lora(lora_id)
        items.append({"kind": "file", "name": lora_id, "repo": lora["repo"], "revision": lora["revision"],
                      "file": lora["file"], "bytes": lora["bytes"], "license": lora["license"]})
    return items
```

new:

```python
    for lora_id in loras:
        lora = seedgen.qwen_lora(lora_id)
        if lora.get("source") == "local":
            continue                      # custom edit LoRAs spec CL32: a local LoRA has nothing to download
        item = {"kind": "file", "name": lora_id, "repo": lora["repo"], "revision": lora["revision"],
                "file": lora["file"], "bytes": lora["bytes"], "license": lora["license"]}
        if lora.get("user"):
            item["user"] = True
        items.append(item)
    return items
```

- [ ] **Step 23: `bin/seed-edit-setup`: `report`, `unusable`, `finish` and `main` (CL33).** Three Edits.

Old:

```python
        else:
            say("LoRA %s (%s) is not in %s" % (item["name"], item["file"], hub))
    ancestor = existing_ancestor(hub)
```

new:

```python
        else:
            say("LoRA %s (%s) is not in %s" % (item["name"], item["file"], hub))
    import seed_lora_registry
    for lora_id in loras:
        lora = seedgen.qwen_lora(lora_id)
        if lora.get("source") != "local":
            continue
        problem = seed_lora_registry.local_problem(lora)
        if problem is None:
            say("LoRA %s (local) %s: %.2f GiB" % (lora_id, lora["path"], lora["bytes"] / 2 ** 30))
        else:
            say("LoRA %s (local): %s" % (lora_id, problem))
    ancestor = existing_ancestor(hub)
```

Old:

```python
    for line in lines:
        say(line)


def main(argv=None):
```

new:

```python
    for line in lines:
        say(line)


def unusable(items, hub):
    """Custom edit LoRAs spec CL33: [(name, problem)] of the downloaded custom Hugging Face LoRA files that fail
    seed_lora_registry.downloaded_problem."""
    import seed_lora_registry
    out = []
    for item in items:
        if not item.get("user"):
            continue
        path = pinned_file(item["repo"], item["revision"], item["file"], [hub])
        if path is None:
            continue
        problem = seed_lora_registry.downloaded_problem(seedgen.qwen_lora(item["name"]), path)
        if problem is not None:
            out.append((item["name"], problem))
    return out


def finish(items, hub):
    """Custom edit LoRAs spec CL33: name every unusable custom LoRA file; 1 (UNUSABLE_MSG) when there is one,
    else 0."""
    bad = unusable(items, hub)
    for name, problem in bad:
        say("LoRA %s is unusable: %s" % (name, problem))
    if bad:
        return fail(1, UNUSABLE_MSG % len(bad))
    return 0


def main(argv=None):
```

Old:

```python
    if venv_ok and not needed:
        say("nothing to do")
        report(venv, hub, models, loras, items)
        return 0
```

new:

```python
    if venv_ok and not needed:
        say("nothing to do")
        report(venv, hub, models, loras, items)
        return finish(items, hub)
```

Old:

```python
    if orphans:
        return fail(1, "%d orphan partial blob(s) left by an earlier download block the pinned snapshot; delete the "
                       "file(s) listed above, then re-run bin/seed-edit-setup" % len(orphans))
    return 0
```

new:

```python
    if orphans:
        return fail(1, "%d orphan partial blob(s) left by an earlier download block the pinned snapshot; delete the "
                       "file(s) listed above, then re-run bin/seed-edit-setup" % len(orphans))
    return finish(items, hub)
```

- [ ] **Step 24: `movie_ui_lib.py`: the probe tolerance (CL34, D9).** Two Edits.

Old:

```python
def _probe_model(value):
```

new:

```python
USER_LORA_PREFIX = "user-"          # custom edit LoRAs spec CL34: the id prefix of a custom Qwen edit LoRA
PROBE_NOT_REPORTED = "not reported by this workspace's bin/seed-edit --probe (it may predate custom LoRAs)"


def _probe_model(value):
```

Old (the whole `_probe_qwen`):

```python
def _probe_qwen(value, model_ids, lora_ids):
    """The qwen entry of bin/seed-edit --probe's output (seed models SQ35): {"ok", "reason", "models",
    "loras"} with exactly those keys, models and loras keyed by exactly model_ids and lora_ids and each
    entry {"ok", "reason"}; extra keys are dropped. None when the shape is wrong."""
    def entry(item):
        if not (isinstance(item, dict) and isinstance(item.get("ok"), bool) and "reason" in item
                and (item["reason"] is None or isinstance(item["reason"], str))):
            return None
        return {"ok": item["ok"], "reason": item["reason"]}

    top = entry(value)
    if top is None:
        return None
    for key, ids in (("models", model_ids), ("loras", lora_ids)):
        found = value.get(key)
        if not (isinstance(found, dict) and set(found) == set(ids)):
            return None
        parsed = dict((i, entry(found[i])) for i in ids)
        if None in parsed.values():
            return None
        top[key] = parsed
    return top
```

new:

```python
def _probe_qwen(value, model_ids, lora_ids):
    """The qwen entry of bin/seed-edit --probe's output (seed models SQ35): {"ok", "reason", "models",
    "loras"} with exactly those keys, models keyed by exactly model_ids, loras by lora_ids, and each entry
    {"ok", "reason"}; extra keys are dropped. None when the shape is wrong. Custom edit LoRAs spec CL34 (D9): a
    user- LoRA id the probe did not report reads {"ok": False, "reason": PROBE_NOT_REPORTED}, and a user- key
    the caller does not know is dropped; every other LoRA id must be reported and no other key may appear."""
    def entry(item):
        if not (isinstance(item, dict) and isinstance(item.get("ok"), bool) and "reason" in item
                and (item["reason"] is None or isinstance(item["reason"], str))):
            return None
        return {"ok": item["ok"], "reason": item["reason"]}

    top = entry(value)
    if top is None:
        return None
    found = value.get("models")
    if not (isinstance(found, dict) and set(found) == set(model_ids)):
        return None
    parsed = dict((i, entry(found[i])) for i in model_ids)
    if None in parsed.values():
        return None
    top["models"] = parsed
    found = value.get("loras")
    if not isinstance(found, dict):
        return None
    if any(i not in found for i in lora_ids if not i.startswith(USER_LORA_PREFIX)):
        return None
    if any(k not in lora_ids and not k.startswith(USER_LORA_PREFIX) for k in found):
        return None
    parsed = dict((i, entry(found[i]) if i in found else {"ok": False, "reason": PROBE_NOT_REPORTED})
                  for i in lora_ids)
    if None in parsed.values():
        return None
    top["loras"] = parsed
    return top
```

- [ ] **Step 25: `movie_ui_server.py`: the accessors (CL36; SC1).** Two Edits.

Old:

```python
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
```

new:

```python
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.qwen_lora_ids())
```

Old (with `replace_all: true`; it occurs exactly twice, in `edit_availability` and `_h_seed_run_create`):

```python
    models, detail = lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS)
```

new:

```python
    models, detail = lib.seed_edit_check(real, seedgen.QWEN_MODEL_IDS, seedgen.qwen_lora_ids())
```

- [ ] **Step 26: E3, `tests/test_seed_edit_tool.py`.** Four Edits.

Old:

```python
    assert seedgen.QWEN_LORA_IDS == ("uncensored", "viggle-turbo")
```

new:

```python
    assert seedgen.qwen_lora_ids() == ("uncensored", "viggle-turbo")
    assert seedgen.BUILTIN_QWEN_LORA_IDS == ("uncensored", "viggle-turbo")
```

Old:

```python
    assert [dict(lora) for lora in seedgen.QWEN_LORAS] == LORA_REGISTRY
```

new:

```python
    assert [dict(lora) for lora in seedgen.BUILTIN_QWEN_LORAS] == LORA_REGISTRY
```

Old:

```python
    for entry in seedgen.QWEN_MODELS + seedgen.QWEN_LORAS:
        assert entry["revision"] is None or re.fullmatch(r"[0-9a-f]{40}", entry["revision"]), entry["id"]
    assert all("allow_patterns" not in lora for lora in seedgen.QWEN_LORAS)
```

new:

```python
    for entry in seedgen.QWEN_MODELS + seedgen.BUILTIN_QWEN_LORAS:
        assert entry["revision"] is None or re.fullmatch(r"[0-9a-f]{40}", entry["revision"]), entry["id"]
    assert all("allow_patterns" not in lora for lora in seedgen.BUILTIN_QWEN_LORAS)
```

Old:

```python
    lora_repos = set(lora["repo"] for lora in seedgen.QWEN_LORAS) | {"lightx2v/Qwen-Image-Edit-2511-Lightning"}
```

new:

```python
    lora_repos = set(lora["repo"] for lora in seedgen.BUILTIN_QWEN_LORAS) | {"lightx2v/Qwen-Image-Edit-2511-Lightning"}
```

- [ ] **Step 27: E4, `tests/test_movie_ui_seedgen.py`.** Four Edits.

Old:

```python
    per_lora = dict((i, {"ok": i not in loras, "reason": loras.get(i)}) for i in seedgen.QWEN_LORA_IDS)
```

new:

```python
    per_lora = dict((i, {"ok": i not in loras, "reason": loras.get(i)}) for i in seedgen.BUILTIN_QWEN_LORA_IDS)
```

Old:

```python
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "movie_ui_lib", "re", "secrets", "time"]
```

new:

```python
    assert sorted(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)) == [
        "json", "movie_ui_lib", "os", "re", "secrets", "sys", "threading", "time"]
```

Old:

```python
        "loras": [{"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21", "default_on": True,
                   "default_scale": 1.0, "steps": None, "scheduler": None, "license": research,
                   "setup": "bin/seed-edit-setup --lora uncensored"},
                  {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21", "default_on": False,
                   "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": research,
                   "setup": "bin/seed-edit-setup --lora viggle-turbo"}]}
```

new:

```python
        "loras": [{"id": "uncensored", "label": "Uncensored (abenzerps)", "family": "qwen21", "default_on": True,
                   "default_scale": 1.0, "steps": None, "scheduler": None, "license": research,
                   "user": False, "source": "builtin", "trigger": None,
                   "setup": "bin/seed-edit-setup --lora uncensored"},
                  {"id": "viggle-turbo", "label": "Viggle turbo 6-step", "family": "qwen21", "default_on": False,
                   "default_scale": 1.0, "steps": 6, "scheduler": "viggle_turbo", "license": research,
                   "user": False, "source": "builtin", "trigger": None,
                   "setup": "bin/seed-edit-setup --lora viggle-turbo"}]}
```

Old: `IDS, LIDS = seedgen.QWEN_MODEL_IDS, seedgen.QWEN_LORA_IDS` — new: `IDS, LIDS = seedgen.QWEN_MODEL_IDS, seedgen.BUILTIN_QWEN_LORA_IDS`

- [ ] **Step 28: E5, `tests/test_movie_ui_qwen_edit.py`.** Edit; old:

```python
    found_loras = dict((i, {"ok": True, "reason": None}) for i in seedgen.QWEN_LORA_IDS)
```

new:

```python
    found_loras = dict((i, {"ok": True, "reason": None}) for i in seedgen.BUILTIN_QWEN_LORA_IDS)
```

- [ ] **Step 29: Run the new file and the spec's Task 1 suites.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py 2>&1 | tail -3`
Expected: `15 passed` (CL-T1, T2, T3, T4, T11, T14, T15, T16, T17, T18, T19, T20, T21, T23, Review Focus 1).

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_qwen_edit.py tests/test_movie_ui_qwen_edit.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_extra_refs.py tests/test_ltx_movie_seed_context.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py 2>&1 | tail -3`
Expected: a summary with `passed` and no `failed` or `error` (some node-dependent tests may be `skipped`). Any failure: stop and report it with `--tb=short` output (E7: a further failing existing test is a spec gap, never a test to adjust).

- [ ] **Step 30: Verify: the greps, the compile check and the pinned files.**

Run: `git grep -nwE 'QWEN_LORAS|QWEN_LORA_IDS' -- . ':(exclude)docs' | wc -l` — Expected: `0` (CLK3, SC2).

Run the compile check with `FILES` = `movie_ui_seedgen.py seed_lora_registry.py qwen_edit.py bin/seed-edit bin/seed-edit-setup movie_ui_lib.py movie_ui_server.py tests/conftest.py tests/test_seed_lora_registry.py tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_qwen_edit.py tests/test_movie_ui_qwen_edit.py tests/test_ltx_movie_extra_refs.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py` — Expected: `compiled 18` twice.

Run the pinned-file check of "Global Constraints" — Expected: `pinned files unchanged` and `tests/test_movie_ui_builder.py` with no `failed` (no `test_mut26` bump is needed; this run proves it).

Run: `git diff --stat -- static/ movie_ui_batch.py location_dataset.py seed_edit_mflux_child.py content_safety.py movie_ui_seedfolder.py | tail -1` — Expected: no output.

- [ ] **Step 31: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git add movie_ui_seedgen.py seed_lora_registry.py qwen_edit.py bin/seed-edit bin/seed-edit-setup movie_ui_lib.py movie_ui_server.py tests/conftest.py tests/test_seed_lora_registry.py tests/test_ltx_movie_extra_refs.py tests/test_ltx_movie_seed_edit.py tests/test_qwen_edit.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_shots_seed.py tests/test_movie_ui_seedgen.py tests/test_seed_edit_tool.py tests/test_movie_ui_qwen_edit.py tests/test_ltx_movie_seed_context.py
git diff --cached --name-only | wc -l          # expected: 18
git commit -m "custom edit LoRAs: the registry file, its accessors and the triggered run path (Task 1)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 32: The gate (controller).** Run `zsh $D/gate-run.sh 1`. Expected: `lost 0 (listed 0, unexpected 0); new tests 15, not passing 0; baseline failures still failing 2 of 2`, `GATE PASS`, `3 passed`, `ATK2 OK lines unchanged`. Then an Opus design review of the Task 1 commit against CL1-CL14, CL19, CL22b, CL25-CL34, CL36 and E1-E5 before Task 2 starts.

---
### Task 2: Registering custom LoRAs: `seed_lora_registry` and `bin/seed-edit-lora` (CL15-CL24, SC3-SC6, SC9, SC12; CL-T5-CL-T10, CL-T12, CL-T13, CL-T22, CL-T24, Review Focus 2-4)

This task adds the only writer of the registry file and the only Hugging Face API call: the request rules, the HF model API answer rules, the local file checks, add and remove under the lock, and the CLI. The run path of Task 1 is unchanged.

**Files:**
- Replace whole: `seed_lora_registry.py` (keeps Task 1's `PAIR_SUBSTITUTIONS`, `M_LOCAL_MISSING` … `M_HF_NO_PAIRS`, `lora_pair_count`, `local_problem`, `downloaded_problem` byte for byte)
- Create: `bin/seed-edit-lora` (git mode 100755)
- Modify: `tests/test_seed_lora_registry.py` (the import block; append the Task 2 helpers and tests)

**Interfaces:**
- Consumes (Task 1): `seedgen.user_loras_path()`, `seedgen.user_loras_problem(data)`, `seedgen.valid_trigger(text)`, `seedgen._plain_text(value, most)`, `seedgen.qwen_loras()`, `seedgen.BUILTIN_QWEN_LORAS`, `seedgen.BUILTIN_QWEN_LORA_IDS`, `seedgen.USER_LORAS_SCHEMA`, `seedgen.USER_ID_RE`, `seedgen.HF_REPO_RE`, `seedgen.HF_FILE_RE`, `seedgen.QWEN_FAMILIES`, `seedgen.SCALE_MAX`, `seedgen.STEPS_MAX`, `seedgen.LABEL_MAX`, `seedgen.LICENSE_MAX`, `seedgen.USER_LORA_MAX_BYTES`; `qwen_edit.lora_problem(lora, hubs)`, `qwen_edit.pinned_file(repo, revision, name, hubs)`, `qwen_edit.qwen_hubs()`; the Task 1 test helpers (`REPO`, `FILE`, `SHA`, `TRIGGER`, `LOCAL_LICENSE`, `pairs`, `st_bytes`, `safetensors`, `hf_entry`, `local_entry`, `write_registry`). Existing: `lora_catalog.catalog_lock(path)`, `lora_catalog.file_sha256(path)`, `lora_catalog.read_safetensors_header(path)`, `lora_catalog.CatalogError`, `movie_ui_lib.write_json_atomic`, `movie_ui_lib._is_int`, `movie_ui_lib._is_number`.
- Produces (Task 3 relies on these):
  - `seed_lora_registry`: `class RegistryError(Exception)` with `.status`; `FIELDS`; `fetch_model_info(repo) -> dict` (patched in every test); `add(request, base_dir) -> (entry, notes)`; `remove(lora_id) -> (entry, kept)`; `check_request(request) -> dict`; `check_local_file(path_text, base_dir) -> (path, real, size)`; `load_entries() -> list`; `save_entries(entries)`; `slug(text) -> str`; `default_id(base, ids) -> str`; `M_SCALE`, `M_STEPS` (the CLI's texts) and every message constant of Step 3.
  - `bin/seed-edit-lora`: `main(argv=None) -> int`.
  - `tests/test_seed_lora_registry.py` helpers: `INFO`, `fake_fetch(monkeypatch, info=None) -> list`, `load_cli()`.

- [ ] **Step 1: Write the failing tests.** Two Edits to `tests/test_seed_lora_registry.py`.

Edit 1, the import block; old:

```python
import hashlib
import json
import os
import struct

import pytest
```

new:

```python
import hashlib
import http.client
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import ssl
import stat
import struct
import subprocess
import sys
import threading

import pytest
```

Edit 2, append after the last line of the file (the last line is `    assert st.stub_calls(py) == []`); old:

```python
                                model="qwen", run=st.R2)
    assert code == 2
    assert st.record_of(run_dir)["error"] == (
        "LoRA real.safetensors is unavailable: %s is %d bytes; the registry recorded %d (the file changed since it "
        "was added: re-run bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)"
        % (local, size, entry["bytes"]))
    assert st.stub_calls(py) == []
```

new (the old text, then two blank lines, then the Task 2 block):

```python
                                model="qwen", run=st.R2)
    assert code == 2
    assert st.record_of(run_dir)["error"] == (
        "LoRA real.safetensors is unavailable: %s is %d bytes; the registry recorded %d (the file changed since it "
        "was added: re-run bin/seed-edit-lora add after bin/seed-edit-lora remove user-local)"
        % (local, size, entry["bytes"]))
    assert st.stub_calls(py) == []


# --- Task 2: the writer, the Hugging Face answer and the CLI ------------------------------------------------------

INFO = {"id": REPO, "modelId": REPO, "author": "WarmBloodAban", "sha": SHA, "private": False, "disabled": False,
        "gated": False, "library_name": "diffusers", "pipeline_tag": "image-to-image",
        "cardData": {"base_model": "Qwen/Qwen-Image-Edit-2511", "instance_prompt": TRIGGER, "license": "apache-2.0",
                     "library_name": "diffusers", "pipeline_tag": "image-to-image",
                     "new_version": "Qwen/Qwen-Image-Edit-2511",
                     "tags": ["text-to-image", "lora", "diffusers", "template:diffusion-lora", "toReal",
                              "Qwen-image-Edit-2511"]},
        "siblings": [{"rfilename": ".gitattributes", "size": 2307}, {"rfilename": FILE, "size": 354082336},
                     {"rfilename": "README.md", "size": 3892},
                     {"rfilename": "images/2511动漫转写实真人.jpg", "size": 1250845}]}
ENTRY = {"id": "user-anything-to-real-charact", "label": REPO, "family": "qwen2511", "source": "hf", "repo": REPO,
         "revision": SHA, "file": FILE, "bytes": 354082336, "default_on": False, "default_scale": 1.0,
         "license": "apache-2.0", "steps": None, "scheduler": None, "trigger": TRIGGER, "user": True}
N_FAMILY = "family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)"
N_IN_PLACE = "the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"
R5 = "repo must be OWNER/NAME (letters, digits, '.', '_' or '-') or https://huggingface.co/OWNER/NAME (got %s)"
CONN = "HTTPS" + "Connection"   # spelled in two parts: the workspace has one use of the name (CL51, SC3)


def fake_fetch(monkeypatch, info=None):
    """Patch seed_lora_registry.fetch_model_info to answer a copy of info (INFO by default); returns the list of
    the repos it was asked for."""
    asked = []
    answer = INFO if info is None else info

    def fetch(repo):
        asked.append(repo)
        return json.loads(json.dumps(answer))

    monkeypatch.setattr(registry, "fetch_model_info", fetch)
    return asked


def load_cli():
    path = os.path.join(WS, "bin", "seed-edit-lora")
    loader = importlib.machinery.SourceFileLoader("seed_edit_lora_cli", path)
    spec = importlib.util.spec_from_loader("seed_edit_lora_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def refused(call):
    """(status, text) of the RegistryError that call() raises."""
    with pytest.raises(registry.RegistryError) as info:
        call()
    return info.value.status, str(info.value)


# --- CL-T5 (CL21, CL22, CL24, H5, H9, N-*; CLK1): add the target LoRA ---------------------------------------------

def test_cl_t5_add_the_target_lora(env, registry_path, monkeypatch, capsys):
    asked = fake_fetch(monkeypatch)
    cli = load_cli()
    assert cli.main(["add", "--repo", REPO, "--trigger", TRIGGER]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "seed-edit-lora: " + N_FAMILY,
        "seed-edit-lora: download it with: bin/seed-edit-setup --lora user-anything-to-real-charact",
        "seed-edit-lora: added user-anything-to-real-charact: %s@e8f98cb5f976 %s (0.33 GiB, apache-2.0)" % (REPO, FILE)]
    assert asked == [REPO]
    assert st.read_json(registry_path) == {"schema": "seed-edit.user-loras.v1", "loras": [ENTRY]}
    assert seedgen.qwen_lora_ids()[-1] == ENTRY["id"]
    assert refused(lambda: registry.add({"repo": REPO, "id": ENTRY["id"]}, None)) == (
        409, "LoRA id user-anything-to-real-charact already exists; choose another id or remove it first")
    registry.remove(ENTRY["id"])
    entry, notes = registry.add({"repo": "https://huggingface.co/" + REPO, "id": "user-to-real", "trigger": TRIGGER},
                                os.getcwd())
    assert entry == dict(ENTRY, id="user-to-real") and asked[-1] == REPO
    assert notes == [N_FAMILY, "download it with: bin/seed-edit-setup --lora user-to-real"]
    assert refused(lambda: registry.add({"repo": REPO, "id": "user-other"}, None)) == (
        409, "%s:%s is already in the registry as user-to-real" % (REPO, FILE))
    registry.remove("user-to-real")
    entry, notes = registry.add({"repo": REPO}, None)
    assert entry == dict(ENTRY, trigger=None)
    assert notes == [N_FAMILY, "the model card's instance_prompt is 'transform the image to realistic photograph'; "
                               "pass trigger to prepend it to every edit prompt of this LoRA",
                     "download it with: bin/seed-edit-setup --lora user-anything-to-real-charact"]


# --- CL-T6 (CL17, CL49, CL51; CLK4): the one network function -------------------------------------------------------

class FakeResponse(object):
    def __init__(self, status, body, headers):
        self.status, self.body, self.headers = status, body, headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


def fake_connection(monkeypatch, status=200, body=b"{}", headers=None, error=None):
    """Patch http.client's HTTPS connection class, as seed_lora_registry sees it, with a fake answering status,
    body and headers, or raising error from request(); returns the list of its recorded calls."""
    calls = []

    class Fake(object):
        def __init__(self, host, timeout=None, context=None):
            calls.append(("init", host, timeout, context is not None))

        def request(self, method, url, headers=None):
            calls.append(("request", method, url, dict(headers or {})))
            if error is not None:
                raise error

        def getresponse(self):
            return FakeResponse(status, body, headers or {})

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(registry.http.client, CONN, Fake)
    return calls


def test_cl_t6_fetch_model_info(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "dummy-not-a-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "dummy-not-a-token")
    calls = fake_connection(monkeypatch, body=json.dumps(INFO).encode("utf-8"))
    assert registry.fetch_model_info("o/n") == INFO
    assert calls == [("init", "huggingface.co", 30, True),
                     ("request", "GET", "/api/models/o/n?blobs=true",
                      {"User-Agent": "qwen-agent-seed-edit-lora/1", "Accept": "application/json"}),
                     ("close",)]
    moved = "repo o/n has moved (%s); add it by its new name"
    gone = ("repo o/n is not on the Hugging Face Hub, or it is private (only public repos can be added; no token is "
            "sent)")
    cases = [(301, b"", {"Location": "/api/models/o/m"}, 400, moved % "/api/models/o/m"), (302, b"", {}, 400, moved % "-"),
             (307, b"", {}, 400, moved % "-"), (308, b"", {"Location": "/x"}, 400, moved % "/x"),
             (401, b"", {}, 400, gone), (404, b"", {}, 400, gone),
             (500, b"", {}, 502, "the Hugging Face API answered HTTP 500 for o/n"),
             (200, b"{bad", {}, 502, "the Hugging Face API answered o/n with invalid JSON"),
             (200, b"\xff\xfe", {}, 502, "the Hugging Face API answered o/n with invalid JSON")]
    for status, body, headers, code, text in cases:
        calls = fake_connection(monkeypatch, status=status, body=body, headers=headers)
        assert refused(lambda: registry.fetch_model_info("o/n")) == (code, text), status
        assert calls[-1] == ("close",)
    monkeypatch.setattr(registry, "HF_MAX_BYTES", 10)
    fake_connection(monkeypatch, body=b"{" + b" " * 9 + b"}")
    assert refused(lambda: registry.fetch_model_info("o/n")) == (
        502, "the Hugging Face API answer for o/n is larger than 32 MiB")
    monkeypatch.setattr(registry, "HF_MAX_BYTES", 32 * 2 ** 20)
    unreachable = "cannot reach the Hugging Face API (huggingface.co): %s"
    for error, text in ((OSError("boom"), "OSError: boom"),
                        (http.client.RemoteDisconnected("closed"), "RemoteDisconnected: closed"),
                        (ssl.SSLCertVerificationError(1, "certificate verify failed"),
                         "SSLCertVerificationError: certificate verify failed; this Python has no CA certificates "
                         "(run its Install Certificates.command)")):
        calls = fake_connection(monkeypatch, error=error)
        assert refused(lambda: registry.fetch_model_info("o/n")) == (502, unreachable % text)
        assert calls[-1] == ("close",)


def test_cl_t6_one_network_function_in_the_workspace():
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    proc = subprocess.run(["git", "-C", WS, "grep", "--untracked", "-c", CONN, "--", ".", ":(exclude)docs"],
                          capture_output=True, text=True)
    assert proc.stdout.splitlines() == ["seed_lora_registry.py:1"]
    with open(os.path.join(WS, "seed_lora_registry.py"), encoding="utf-8") as f:
        source = f.read()
    for gone in ("Authorization", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "os.environ"):
        assert gone not in source, gone


# --- CL-T7 (R1-R12): the request rules, before any network or file access ------------------------------------------

BASE = {"repo": REPO}
LOCAL = {"path": "/abs/x.safetensors", "family": "qwen2511"}
FIELDS_TEXT = "unknown field %s; allowed: repo, file, path, family, id, label, trigger, scale, steps"
ONE_SOURCE = "give exactly one of repo and path"
R6 = "file must be a relative path of letters, digits, spaces and . _ - + ( ), with no '..' (got %s)"
NOT_ST = ("%s is not a .safetensors file; other formats are refused (the pickle formats .bin, .pt, .pth and .ckpt "
          "can run code when loaded)")
R8 = "id must be user- followed by 1 to 24 lowercase letters, digits or '-' (got %s)"
LABEL_TEXT = "label must be 1 to 80 characters with no control characters"
TRIGGER_TEXT = ("trigger must be 1 to 200 characters: letters, digits, spaces and , . ; : ' ! ? ( ) & / -, starting "
                "with a letter or digit, with no double or trailing space")
SCALE_TEXT = "scale must be a number above 0 and at most 2"
STEPS_TEXT = "steps must be an integer from 1 to 100"
REQUEST_CASES = [
    (dict(BASE, ws="/abs/ws"), FIELDS_TEXT % "ws"),
    (dict(BASE, zz=1, aa=None), FIELDS_TEXT % "aa"),
    ({"repo": 5}, "repo must be a string"),
    (dict(BASE, label=["x"]), "label must be a string"),
    (dict(LOCAL, family=21), "family must be a string"),
    ({}, ONE_SOURCE),
    ({"repo": None, "path": None}, ONE_SOURCE),
    (dict(BASE, path="/abs/x.safetensors"), ONE_SOURCE),
    (dict(LOCAL, file="a.safetensors"), "file is only for repo"),
    ({"repo": "no-slash"}, R5 % "no-slash"),
    ({"repo": "a/b..c"}, R5 % "a/b..c"),
    ({"repo": "a--b/c"}, R5 % "a--b/c"),
    (dict(BASE, file="x.bin"), NOT_ST % "x.bin"),
    (dict(BASE, file="../x.safetensors"), R6 % "../x.safetensors"),
    (dict(BASE, file="a/../b.safetensors"), R6 % "a/../b.safetensors"),
    (dict(BASE, family="flux"), "family must be qwen21 or qwen2511 (got flux)"),
    ({"path": "/abs/x.safetensors"}, "family is required for a local file (qwen21 or qwen2511)"),
    (dict(BASE, id="to-real"), R8 % "to-real"),
    (dict(BASE, id="user-" + "a" * 25), R8 % ("user-" + "a" * 25)),
    (dict(BASE, id="user-A"), R8 % "user-A"),
    (dict(BASE, label=""), LABEL_TEXT),
    (dict(BASE, label="a" * 81), LABEL_TEXT),
    (dict(BASE, label="a\tb"), LABEL_TEXT),
    (dict(BASE, label="a\x7fb"), LABEL_TEXT),
    (dict(BASE, trigger="a  b"), TRIGGER_TEXT),
    (dict(BASE, trigger="-x"), TRIGGER_TEXT),
    (dict(BASE, scale=0), SCALE_TEXT),
    (dict(BASE, scale=2.5), SCALE_TEXT),
    (dict(BASE, scale=True), SCALE_TEXT),
    (dict(BASE, scale="1"), SCALE_TEXT),
    (dict(BASE, steps=0), STEPS_TEXT),
    (dict(BASE, steps=101), STEPS_TEXT),
    (dict(BASE, steps=2.5), STEPS_TEXT),
    (dict(BASE, steps=True), STEPS_TEXT),
]


@pytest.mark.parametrize("body,message", REQUEST_CASES, ids=["case%d" % (i + 1) for i in range(len(REQUEST_CASES))])
def test_cl_t7_the_request_rules(body, message, registry_path, monkeypatch):
    asked = fake_fetch(monkeypatch)
    assert refused(lambda: registry.add(body, None)) == (400, message)
    assert asked == [] and not os.path.exists(os.path.dirname(registry_path))


def test_cl_t7_the_cli_conversions(registry_path, monkeypatch, capsys):
    asked = fake_fetch(monkeypatch)
    cli = load_cli()
    for argv, text in ((["add", "--repo", REPO, "--scale", "x"], SCALE_TEXT),
                       (["add", "--repo", REPO, "--scale", "nan"], SCALE_TEXT),
                       (["add", "--repo", REPO, "--steps", "2.5"], STEPS_TEXT),
                       (["add", "--repo", REPO, "--steps", "0"], STEPS_TEXT),
                       (["add", "--repo", REPO, "--path", "/abs/x.safetensors"], ONE_SOURCE),
                       (["add"], ONE_SOURCE)):
        assert cli.main(argv) == 2, argv
        assert capsys.readouterr().err == "Error: %s\n" % text, argv
    with pytest.raises(SystemExit) as info:
        cli.main(["frob"])
    assert info.value.code == 2
    assert asked == [] and not os.path.exists(registry_path)
    assert (registry.M_SCALE, registry.M_STEPS) == (SCALE_TEXT, STEPS_TEXT)


# --- CL-T8 (H1-H9): the Hugging Face answer rules -------------------------------------------------------------------

def info_with(card=None, **changes):
    """A copy of INFO with changes, and with cardData updated by card (a key set to None is removed)."""
    info = json.loads(json.dumps(INFO))
    info.update(changes)
    for key, value in (card or {}).items():
        if value is None:
            info["cardData"].pop(key, None)
        else:
            info["cardData"][key] = value
    return info


def test_cl_t8_the_hugging_face_answer_rules(env, registry_path, monkeypatch):
    def no(info, body=None):
        fake_fetch(monkeypatch, info)
        return refused(lambda: registry.add(body or {"repo": REPO, "trigger": TRIGGER}, None))

    def yes(info, body=None):
        fake_fetch(monkeypatch, info)
        entry, notes = registry.add(body or {"repo": REPO, "trigger": TRIGGER}, None)
        registry.remove(entry["id"])
        return entry, notes

    where = REPO + "@e8f98cb5f976"
    no_model = (502, "the Hugging Face API returned no model, commit sha or file list for " + REPO)
    assert no("x") == no_model
    assert no(info_with(sha=None)) == no_model and no(info_with(sha=SHA.upper())) == no_model
    assert no(info_with(siblings={"x": 1})) == no_model
    assert no(info_with(disabled=True)) == (400, "repo %s is disabled on the Hugging Face Hub" % REPO)
    assert no(info_with(gated="auto")) == (
        400, "repo %s is gated (auto); seed-edit downloads are unauthenticated, so it cannot be installed" % REPO)
    assert yes(info_with(gated=None))[0]["file"] == FILE
    assert no(INFO, {"repo": REPO, "file": "other.safetensors"}) == (
        400, "file other.safetensors is not in %s; its .safetensors files: %s" % (where, FILE))
    many = [{"rfilename": "l%02d.safetensors" % i, "size": 10} for i in range(12)]
    assert no(info_with(siblings=many), {"repo": REPO, "file": "other.safetensors"}) == (
        400, "file other.safetensors is not in %s; its .safetensors files: %s and 2 more"
        % (where, ", ".join("l%02d.safetensors" % i for i in range(10))))
    folders = [{"rfilename": "README.md", "size": 1}, {"rfilename": "loras/a.safetensors", "size": 10},
               {"rfilename": "model.bin", "size": 10}, {"rfilename": "weights.PT", "size": 10}]
    assert no(info_with(siblings=folders)) == (
        400, "repo %s has no .safetensors file at its top level; its .safetensors files in folders: "
             "loras/a.safetensors; pass file; it has model.bin, weights.PT, which are refused: pickle formats can run "
             "code when loaded" % where)
    assert no(info_with(siblings=[{"rfilename": "README.md", "size": 1}])) == (
        400, "repo %s has no .safetensors file at its top level" % where)
    two = [{"rfilename": "a.safetensors", "size": 10}, {"rfilename": "b.safetensors", "size": 10}]
    assert no(info_with(siblings=two)) == (
        400, "repo %s has 2 .safetensors files at its top level (a.safetensors, b.safetensors); pass file to choose "
             "one" % where)
    entry, _notes = yes(info_with(siblings=two), {"repo": REPO, "file": "b.safetensors", "trigger": TRIGGER})
    assert (entry["file"], entry["bytes"]) == ("b.safetensors", 10)
    assert no(info_with(siblings=[{"rfilename": "bad name!.safetensors", "size": 10}])) == (
        400, "the repo's file bad name!.safetensors has characters this tool does not accept, so it cannot be added")
    assert yes(info_with(siblings=[{"rfilename": "Lora.SafeTensors", "size": 10}]))[0]["file"] == "Lora.SafeTensors"
    no_size = (502, "the Hugging Face API reported no size for " + FILE)
    assert no(info_with(siblings=[{"rfilename": FILE}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": True}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": 0}])) == no_size
    assert no(info_with(siblings=[{"rfilename": FILE, "size": 9 * 2 ** 30}])) == (
        400, "%s is 9.0 GiB; custom LoRAs are limited to 8 GiB" % FILE)
    unknown = ("the model card's base_model (%s) is not Qwen/Qwen-Image-Edit-2511 or Qwen/Qwen-Image-2.1; pass family "
               "(qwen21 or qwen2511)")
    assert no(info_with(card={"base_model": "black-forest-labs/FLUX.1-dev"})) == (
        400, unknown % "black-forest-labs/FLUX.1-dev")
    assert no(info_with(card={"base_model": None})) == (400, unknown % "none")
    assert no(info_with(cardData=None)) == (400, unknown % "none")
    both = ["Qwen/Qwen-Image-Edit-2511", "Qwen/Qwen-Image-2.1"]
    assert no(info_with(card={"base_model": both})) == (400, "the model card's base_model lists both families; pass family")
    download = "download it with: bin/seed-edit-setup --lora user-anything-to-real-charact"
    entry, notes = yes(INFO, {"repo": REPO, "family": "qwen21", "trigger": TRIGGER})
    assert entry["family"] == "qwen21" and notes == [
        "family qwen21 (given)",
        "warning: family qwen21 was given, but the model card's base_model Qwen/Qwen-Image-Edit-2511 means qwen2511",
        download]
    entry, notes = yes(info_with(card={"base_model": both}), {"repo": REPO, "family": "qwen2511", "trigger": TRIGGER})
    assert notes == ["family qwen2511 (given)", download]
    entry, notes = yes(info_with(card={"base_model": ["Qwen/Qwen-Image-Edit-2511", "x/y"]}))
    assert notes == ["family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511, x/y)", download]
    entry, notes = yes(INFO, {"repo": REPO, "trigger": TRIGGER, "steps": 30, "scale": 0.7, "label": "To real"})
    assert (entry["steps"], entry["default_scale"], entry["label"]) == (30, 0.7, "To real")
    assert notes == [N_FAMILY, "qwen2511-q4 always loads the Lightning 8-step LoRA; 30 steps with Lightning are "
                               "untested", download]
    for card, licence in (({"license": ["mit", "apache-2.0"]}, "mit, apache-2.0"),
                          ({"license": "other", "license_name": "flux-1-dev-non-commercial-license"},
                           "other (flux-1-dev-non-commercial-license)"),
                          ({"license": None}, "not stated in the model card"),
                          ({"license": 5}, "not stated in the model card"),
                          ({"license": "x" * 300}, "x" * 200)):
        assert yes(info_with(card=card))[0]["license"] == licence, card
    assert st.read_json(registry_path)["loras"] == []


# --- CL-T9 (CL22): the default ids ---------------------------------------------------------------------------------

def test_cl_t9_ids():
    assert registry.slug("Anything_to_Real_Characters_2511") == "anything-to-real-charact"
    assert registry.slug("My LoRA v2.1") == "my-lora-v2-1"
    assert registry.slug("--x--") == "x"
    assert registry.slug("动漫") == "lora" and registry.slug("___") == "lora" and registry.slug("") == "lora"
    assert registry.slug("a" * 23 + "-b") == "a" * 23
    base = "anything-to-real-charact"
    assert registry.default_id(base, ()) == "user-anything-to-real-charact"
    taken = ("user-anything-to-real-charact",)
    assert registry.default_id(base, taken) == "user-anything-to-real-chara-2"
    taken += tuple("user-anything-to-real-chara-%d" % n for n in range(2, 10))
    assert registry.default_id(base, taken) == "user-anything-to-real-char-10"
    assert seedgen.USER_ID_RE.fullmatch("user-anything-to-real-char-10")
    assert registry.default_id("lora", ("user-lora",)) == "user-lora-2"


# --- CL-T10 (CL18, CL19, CL21 local; D7, D10, SC6): local files ------------------------------------------------------

def test_cl_t10_local_files(env, registry_path, monkeypatch):
    tmp = env["tmp"]
    given = safetensors(os.path.join(tmp, "loras", "Real Skin.safetensors"), pairs("block0"))
    entry, notes = registry.add({"path": given, "family": "qwen2511", "trigger": TRIGGER}, None)
    with open(given, "rb") as f:
        data = f.read()
    assert entry == {"id": "user-real-skin", "label": "Real Skin.safetensors", "family": "qwen2511", "source": "local",
                     "path": given, "file": "Real Skin.safetensors", "sha256": hashlib.sha256(data).hexdigest(),
                     "bytes": len(data), "default_on": False, "default_scale": 1.0, "license": LOCAL_LICENSE,
                     "steps": None, "scheduler": None, "trigger": TRIGGER, "user": True}
    assert notes == [N_IN_PLACE]
    copy = os.path.join(tmp, "loras", "copy.safetensors")
    shutil.copyfile(given, copy)
    assert refused(lambda: registry.add({"path": copy, "family": "qwen2511", "id": "user-copy"}, None)) == (
        409, "%s is already in the registry as user-real-skin" % copy)
    home_file = safetensors(os.path.join(tmp, "home", "loras", "h.safetensors"), pairs("block1"))
    entry, notes = registry.add({"path": "~/loras/h.safetensors", "family": "qwen21", "steps": 30}, None)
    assert (entry["path"], entry["id"], notes) == (home_file, "user-h", [N_IN_PLACE])
    rel = safetensors(os.path.join(tmp, "work", "rel", "y.safetensors"), pairs("block2"))
    entry, _notes = registry.add({"path": os.path.join("rel", "y.safetensors"), "family": "qwen21"},
                                 os.path.join(tmp, "work"))
    assert entry["path"] == rel
    assert refused(lambda: registry.add({"path": os.path.join("rel", "y.safetensors"), "family": "qwen21"}, None)) == (
        400, "path must be an absolute path or start with ~ (got %s)" % os.path.join("rel", "y.safetensors"))
    blob = os.path.join(tmp, "hub", "blobs", "abc")
    os.makedirs(os.path.dirname(blob))
    with open(blob, "wb") as f:
        f.write(st_bytes(pairs("block3")))
    link = os.path.join(tmp, "hub", "snapshots", "rev", "x.safetensors")
    os.makedirs(os.path.dirname(link))
    os.symlink(blob, link)
    entry, notes = registry.add({"path": link, "family": "qwen2511", "steps": 30}, None)
    assert (entry["path"], entry["file"], entry["bytes"]) == (link, "x.safetensors", os.path.getsize(blob))
    assert notes == ["qwen2511-q4 always loads the Lightning 8-step LoRA; 30 steps with Lightning are untested",
                     N_IN_PLACE]
    with open(registry_path, "rb") as f:
        before = f.read()
    os.makedirs(os.path.join(tmp, "dir.safetensors"))
    ckpt = os.path.join(tmp, "x.ckpt")
    with open(ckpt, "wb") as f:
        f.write(b"x")
    empty = os.path.join(tmp, "empty.safetensors")
    open(empty, "wb").close()
    garbage = os.path.join(tmp, "garbage.safetensors")
    with open(garbage, "wb") as f:
        f.write(b"not a safetensors file at all")
    unpaired = safetensors(os.path.join(tmp, "unpaired.safetensors"), {"a.lora_A.weight": {"dtype": "F16"}})
    control = os.path.join(tmp, "bad\nname.safetensors")
    for path, text in ((os.path.join(tmp, "nope.safetensors"), "%s does not exist"),
                       (os.path.join(tmp, "dir.safetensors"), "%s is not a regular file"),
                       (ckpt, NOT_ST),
                       (empty, "%s is not a safetensors file (its header does not parse)"),
                       (garbage, "%s is not a safetensors file (its header does not parse)"),
                       (unpaired, "%s has no LoRA weight pairs (lora_A/lora_B, lora_down/lora_up or lora.down/lora.up) "
                                  "in its safetensors header, so mflux would apply nothing")):
        assert refused(lambda: registry.add({"path": path, "family": "qwen21"}, None)) == (400, text % path), path
    assert refused(lambda: registry.add({"path": control, "family": "qwen21"}, None)) == (
        400, "path must not contain control characters")
    with monkeypatch.context() as m:
        m.setattr(os.path, "getsize", lambda p: 9 * 2 ** 30)
        assert refused(lambda: registry.add({"path": unpaired, "family": "qwen21"}, None)) == (
            400, "%s is 9.0 GiB; custom LoRAs are limited to 8 GiB" % unpaired)
    assert refused(lambda: registry.add({"path": unpaired}, None)) == (
        400, "family is required for a local file (qwen21 or qwen2511)")
    with open(registry_path, "rb") as f:
        assert f.read() == before
    assert [e["id"] for e in st.read_json(registry_path)["loras"]] == ["user-real-skin", "user-h", "user-y", "user-x"]


# --- CL-T12 (CL22a, CL24): remove keeps every file --------------------------------------------------------------------

def test_cl_t12_remove_keeps_every_file(env, registry_path, capsys):
    cli = load_cli()
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    data = st_bytes(pairs("block0"))
    pinned = os.path.join(st.pinned_cache(os.path.join(env["tmp"], "zi"), REPO, SHA, {FILE: data}), FILE)
    write_registry(registry_path, [local_entry(local), hf_entry(size=len(data)),
                                   hf_entry("user-never", repo="o/never", file="never.safetensors")])
    assert cli.main(["remove", "user-nope"]) == 2
    assert capsys.readouterr().err == (
        "Error: unknown custom LoRA user-nope (custom LoRAs: user-local, user-hf, user-never)\n")
    head = "seed-edit-lora: removed %s from " + registry_path + "; "
    assert cli.main(["remove", "user-local"]) == 0
    assert capsys.readouterr().out == head % "user-local" + "the file stays at %s\n" % local
    assert cli.main(["remove", "user-hf"]) == 0
    assert capsys.readouterr().out == head % "user-hf" + "its downloaded file stays at %s\n" % pinned
    assert cli.main(["remove", "user-never"]) == 0
    assert capsys.readouterr().out == head % "user-never" + "it was never downloaded\n"
    assert cli.main(["remove", "uncensored"]) == 2
    assert capsys.readouterr().err == "Error: uncensored is a built-in LoRA and cannot be removed\n"
    assert cli.main(["remove", "user-nope"]) == 2
    assert capsys.readouterr().err == "Error: unknown custom LoRA user-nope (custom LoRAs: none)\n"
    assert os.path.isfile(local) and os.path.isfile(pinned)
    assert st.read_json(registry_path) == {"schema": "seed-edit.user-loras.v1", "loras": []}


# --- CL-T13 (CL24): the list ------------------------------------------------------------------------------------------

def test_cl_t13_the_list(env, registry_path, capsys):
    local = safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    write_registry(registry_path, [hf_entry(), local_entry(local)])
    assert load_cli().main(["list"]) == 0
    where = "%s or %s" % (env["zhub"], env["hfhub"])
    assert capsys.readouterr().out.splitlines() == [
        "ID\tFAMILY\tSOURCE\tWHERE\tSCALE\tTRIGGER\tINSTALLED",
        "uncensored\tqwen21\tbuiltin\tabenzerps/Qwen-Image-2.1-Uncensored-Quantized@7959e658915f "
        "qwen-image-2.1-uncensored-lora.safetensors\t1\t-\tno: qwen-image-2.1-uncensored-lora.safetensors is not in "
        "%s (run bin/seed-edit-setup --lora uncensored)" % where,
        "viggle-turbo\tqwen21\tbuiltin\tViggle/Qwen-Image-2.1-viggle-turbo@009a44a895ef "
        "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors\t1\t-\tno: "
        "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors is not in %s (run bin/seed-edit-setup --lora "
        "viggle-turbo)" % where,
        "user-hf\tqwen2511\thf\t%s@e8f98cb5f976 %s\t1\t%s\tno: %s is not in %s (run bin/seed-edit-setup --lora "
        "user-hf)" % (REPO, FILE, TRIGGER, FILE, where),
        "user-local\tqwen2511\tlocal\t%s\t1\t%s\tyes" % (local, TRIGGER),
        "seed-edit-lora: registry %s (2 custom)" % registry_path]


# --- CL-T22 (CL20): the lock, the file and an unreadable registry ------------------------------------------------------

def test_cl_t22_the_lock_and_the_file(env, registry_path):
    tmp = env["tmp"]
    a = safetensors(os.path.join(tmp, "loras", "a.safetensors"), pairs("block0"))
    b = safetensors(os.path.join(tmp, "loras", "b.safetensors"), pairs("block1"))
    barrier = threading.Barrier(2)
    errors = []

    def run(path, lora_id):
        barrier.wait()
        try:
            registry.add({"path": path, "family": "qwen21", "id": lora_id}, None)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run, args=(a, "user-a")), threading.Thread(target=run, args=(b, "user-b"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == []
    data = st.read_json(registry_path)
    assert sorted(e["id"] for e in data["loras"]) == ["user-a", "user-b"]
    with open(registry_path, encoding="utf-8") as f:
        raw = f.read()
    assert raw == json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert raw.startswith('{\n  "schema": "seed-edit.user-loras.v1",\n  "loras": [\n')
    assert stat.S_IMODE(os.stat(registry_path).st_mode) == 0o600
    assert os.path.isfile(os.path.join(os.path.dirname(registry_path), ".lock"))
    with open(registry_path, "wb") as f:
        f.write(b"{broken")
    text = "the custom LoRA registry %s is unreadable: not valid JSON; fix or delete it, then retry" % registry_path
    assert refused(lambda: registry.add({"path": a, "family": "qwen21", "id": "user-c"}, None)) == (409, text)
    assert refused(lambda: registry.remove("user-a")) == (409, text)
    assert refused(registry.load_entries) == (409, text)
    with open(registry_path, "rb") as f:
        assert f.read() == b"{broken"


# --- CL-T24 (CL48, D16, SC8, SC9): 3.9 and 3.13, the source scan, the imports and the mode ---------------------------

COMPILED = ("seed_lora_registry.py", "bin/seed-edit-lora", "movie_ui_seedgen.py", "qwen_edit.py", "bin/seed-edit",
            "bin/seed-edit-setup", "movie_ui_lib.py", "movie_ui_server.py", "tests/test_seed_lora_registry.py",
            "tests/conftest.py")
SCANNED = ("seed_lora_registry.py", "bin/seed-edit-lora", "tests/test_seed_lora_registry.py")


@pytest.mark.parametrize("python", ["/usr/bin/python3", sys.executable])
def test_cl_t24_every_new_and_changed_file_compiles(python, tmp_path):
    if not os.path.isfile(python):
        pytest.skip("%s is not installed" % python)
    proc = subprocess.run([python, "-m", "py_compile"] + [os.path.join(WS, rel) for rel in COMPILED],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr


def test_cl_t24_the_source_scan_the_imports_and_the_mode():
    forbidden = [(re.compile(r"^\s*(import|from)\s+cgi\b", re.M), "cgi"),
                 (re.compile(r"\burllib\b"), "urllib"),
                 (re.compile(r"shell\s*=\s*True"), "shell=True"),
                 (re.compile(r"^\s*match\s+\S.*:\s*$", re.M), "match statement"),
                 (re.compile(r"->[^:\n]*\|"), "X | Y return annotation"),
                 (re.compile(r":\s*[A-Za-z_][\w.\[\], ]*\|\s*None"), "X | None annotation"),
                 (re.compile(r"strict\s*=\s*True\s*\)"), "zip(strict=)"),
                 (re.compile(r"load_module\("), "load_module")]
    for rel in SCANNED:
        with open(os.path.join(WS, rel), encoding="utf-8") as f:
            source = f.read()
        if rel == "tests/test_seed_lora_registry.py":
            start = source.index("    forbidden = [")
            end = source.index("    for rel in SCANNED:", start)
            source = source[:start] + source[end:]
        for regex, what in forbidden:
            assert not regex.search(source), (rel, what)
    imports = r"^(?:import|from)\s+([A-Za-z_][\w.]*)"
    with open(os.path.join(WS, "seed_lora_registry.py"), encoding="utf-8") as f:
        assert re.findall(imports, f.read(), re.M) == ["http.client", "json", "os", "re", "ssl", "lora_catalog",
                                                      "movie_ui_lib", "movie_ui_seedgen"]
    cli = os.path.join(WS, "bin", "seed-edit-lora")
    with open(cli, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("#!/usr/bin/env python3\n")
    assert re.findall(imports, text, re.M) == ["argparse", "os", "sys", "movie_ui_seedgen", "seed_lora_registry"]
    assert os.access(cli, os.X_OK)
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    proc = subprocess.run(["git", "-C", WS, "ls-files", "-s", "bin/seed-edit-lora"], capture_output=True, text=True)
    assert proc.stdout.split()[:1] == ["100755"], "bin/seed-edit-lora must be staged with git mode 100755"


# --- Review Focus 2: the CLI resolves relative and ~ paths -------------------------------------------------------------

def test_cl_review_focus_2_the_cli_resolves_relative_and_home_paths(env, registry_path, monkeypatch, capsys):
    tmp = env["tmp"]
    downloads = os.path.join(tmp, "Downloads")
    safetensors(os.path.join(downloads, "lora.safetensors"), pairs("block0"))
    home_file = safetensors(os.path.join(tmp, "home", "loras", "skin.safetensors"), pairs("block1"))
    monkeypatch.chdir(downloads)
    here = os.path.join(os.getcwd(), "lora.safetensors")
    cli = load_cli()
    assert cli.main(["add", "--path", "lora.safetensors", "--family", "qwen2511"]) == 0
    with open(here, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    assert capsys.readouterr().out.splitlines() == [
        "seed-edit-lora: " + N_IN_PLACE, "seed-edit-lora: added user-lora: %s (0.00 GiB, sha256 %s)" % (here, sha[:12])]
    assert cli.main(["add", "--path", "./lora.safetensors", "--family", "qwen2511", "--id", "user-again"]) == 2
    assert capsys.readouterr().err == "Error: %s is already in the registry as user-lora\n" % here
    assert cli.main(["add", "--path", "~/loras/skin.safetensors", "--family", "qwen21"]) == 0
    capsys.readouterr()
    assert [(e["id"], e["path"]) for e in st.read_json(registry_path)["loras"]] == [
        ("user-lora", here), ("user-skin", home_file)]


# --- Review Focus 3: Hugging Face URLs pasted the way browsers copy them -----------------------------------------------

def test_cl_review_focus_3_pasted_hugging_face_urls(env, registry_path, monkeypatch):
    asked = fake_fetch(monkeypatch)
    entry, _notes = registry.add({"repo": "https://huggingface.co/%s/" % REPO, "trigger": TRIGGER}, None)
    assert entry["repo"] == REPO and asked == [REPO]
    registry.remove(entry["id"])
    for text in (" https://huggingface.co/" + REPO, "https://huggingface.co/%s/tree/main" % REPO,
                 "https://huggingface.co/%s/blob/main/%s" % (REPO, FILE), "http://huggingface.co/" + REPO,
                 "hf.co/" + REPO, "huggingface.co/" + REPO, "https://huggingface.co/%s?library=diffusers" % REPO,
                 "https://huggingface.co/" + REPO + "\n", REPO + " ", "https://www.huggingface.co/" + REPO):
        assert refused(lambda: registry.add({"repo": text}, None)) == (400, R5 % text), text
    assert asked == [REPO]


# --- Review Focus 4: an unwritable registry is a clean refusal ---------------------------------------------------------

def test_cl_review_focus_4_an_unwritable_registry_is_a_clean_refusal(env, monkeypatch, capsys):
    tmp = env["tmp"]
    blocker = os.path.join(tmp, "blocker")
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("a file, not a directory")
    path = os.path.join(blocker, "user_loras.json")
    monkeypatch.setenv("SEED_EDIT_USER_LORAS", path)
    lora = safetensors(os.path.join(tmp, "loras", "a.safetensors"))
    prefix = "cannot write the custom LoRA registry %s: " % path
    status, text = refused(lambda: registry.add({"path": lora, "family": "qwen21"}, None))
    assert status == 409 and text.startswith(prefix)
    status, text = refused(lambda: registry.remove("user-a"))
    assert status == 409 and text.startswith(prefix)
    assert load_cli().main(["add", "--path", lora, "--family", "qwen21"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: " + prefix) and err.count("\n") == 1
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS
    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py 2>&1 | tail -3`
Expected: `50 failed, 15 passed`: the 15 Task 1 tests pass and every Task 2 test fails (for example `AttributeError: module 'seed_lora_registry' has no attribute 'add'`, `FileNotFoundError` for `bin/seed-edit-lora`, and `test_cl_t6_one_network_function_in_the_workspace` because `git grep` finds no `HTTPSConnection` yet).

- [ ] **Step 3: Replace `seed_lora_registry.py` whole.** Write exactly this content (it keeps Task 1's constants and three functions byte for byte):

```python
"""seed_lora_registry -- the custom (user-added) Qwen edit LoRAs of the registry file
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md, Sections 2.2 and 3): the request rules, the
Hugging Face model API call and its answer rules, the local file checks, the strict load and the locked,
atomic save, add and remove, and the run-time checks that qwen_edit.lora_problem and bin/seed-edit-setup use.

This module is the only writer of the registry file (movie_ui_seedgen only reads it) and the only Hugging
Face API caller in the workspace: fetch_model_info makes one unauthenticated GET and no token is read or
sent. Weights are never downloaded here; bin/seed-edit-setup --lora ID stays the only downloader.
bin/seed-edit-lora and the movie-ui server's POST and DELETE /api/seed-loras share it.

Standard library plus lora_catalog, movie_ui_lib and movie_ui_seedgen at the top level; qwen_edit is
imported inside remove only, so neither module imports the other at load time. Valid on Python 3.9 and
3.13; %-formatting only.
"""

import http.client
import json
import os
import re
import ssl

import lora_catalog
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen

FIELDS = ("repo", "file", "path", "family", "id", "label", "trigger", "scale", "steps")
BASE_MODEL_FAMILIES = {"Qwen/Qwen-Image-Edit-2511": "qwen2511", "Qwen/Qwen-Image-2.1": "qwen21"}
HF_HOST = "huggingface.co"
HF_TIMEOUT_S = 30
HF_MAX_BYTES = 32 * 2 ** 20
USER_AGENT = "qwen-agent-seed-edit-lora/1"
HF_URL_RE = re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95})/?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PICKLE_EXTS = (".bin", ".pt", ".pth", ".ckpt", ".pkl")
LOCAL_LICENSE = "not stated (local file)"
NO_LICENSE = "not stated in the model card"
LIST_MAX = 10
PAIR_SUBSTITUTIONS = ((".lora_A.", ".lora_B."), (".lora_down.", ".lora_up."), (".lora.down.", ".lora.up."))
# Section 3.2: the request rules R1-R12 (status 400).
M_FIELD = "unknown field %s; allowed: repo, file, path, family, id, label, trigger, scale, steps"
M_STRING = "%s must be a string"
M_ONE_SOURCE = "give exactly one of repo and path"
M_FILE_ONLY_REPO = "file is only for repo"
M_REPO = ("repo must be OWNER/NAME (letters, digits, '.', '_' or '-') or https://huggingface.co/OWNER/NAME "
          "(got %s)")
M_FILE = "file must be a relative path of letters, digits, spaces and . _ - + ( ), with no '..' (got %s)"
M_FAMILY = "family must be qwen21 or qwen2511 (got %s)"
M_FAMILY_LOCAL = "family is required for a local file (qwen21 or qwen2511)"
M_ID = "id must be user- followed by 1 to 24 lowercase letters, digits or '-' (got %s)"
M_LABEL = "label must be 1 to 80 characters with no control characters"
M_TRIGGER = ("trigger must be 1 to 200 characters: letters, digits, spaces and , . ; : ' ! ? ( ) & / -, starting "
             "with a letter or digit, with no double or trailing space")
M_SCALE = "scale must be a number above 0 and at most 2"
M_STEPS = "steps must be an integer from 1 to 100"
# Section 3.3: the Hugging Face API, its answer (H1-H9) and the files.
M_HF_UNREACHABLE = "cannot reach the Hugging Face API (huggingface.co): %s: %s"
M_HF_NO_CERTS = "; this Python has no CA certificates (run its Install Certificates.command)"
M_HF_NOTFOUND = ("repo %s is not on the Hugging Face Hub, or it is private (only public repos can be added; no "
                 "token is sent)")
M_HF_MOVED = "repo %s has moved (%s); add it by its new name"
M_HF_STATUS = "the Hugging Face API answered HTTP %d for %s"
M_HF_BIG = "the Hugging Face API answer for %s is larger than 32 MiB"
M_HF_JSON = "the Hugging Face API answered %s with invalid JSON"
M_HF_NO_MODEL = "the Hugging Face API returned no model, commit sha or file list for %s"
M_HF_DISABLED = "repo %s is disabled on the Hugging Face Hub"
M_HF_GATED = "repo %s is gated (%s); seed-edit downloads are unauthenticated, so it cannot be installed"
M_HF_FILE_MISSING = "file %s is not in %s@%s; its .safetensors files: %s"
M_HF_NO_ROOT = "repo %s@%s has no .safetensors file at its top level"
M_HF_NO_ROOT_FOLDERS = "; its .safetensors files in folders: %s; pass file"
M_HF_NO_ROOT_PICKLE = "; it has %s, which are refused: pickle formats can run code when loaded"
M_HF_SEVERAL = "repo %s@%s has %d .safetensors files at its top level (%s); pass file to choose one"
M_HF_BAD_NAME = "the repo's file %s has characters this tool does not accept, so it cannot be added"
M_HF_NO_SIZE = "the Hugging Face API reported no size for %s"
M_HF_BASE_UNKNOWN = ("the model card's base_model (%s) is not Qwen/Qwen-Image-Edit-2511 or Qwen/Qwen-Image-2.1; "
                     "pass family (qwen21 or qwen2511)")
M_HF_BASE_BOTH = "the model card's base_model lists both families; pass family"
M_NOT_SAFETENSORS = ("%s is not a .safetensors file; other formats are refused (the pickle formats .bin, .pt, .pth "
                     "and .ckpt can run code when loaded)")
M_PATH_ABS = "path must be an absolute path or start with ~ (got %s)"
M_PATH_CONTROL = "path must not contain control characters"                  # plan SC6
M_NOT_EXIST = "%s does not exist"
M_NOT_REGULAR = "%s is not a regular file"
M_TOO_BIG = "%s is %.1f GiB; custom LoRAs are limited to 8 GiB"
M_NOT_ST_HEADER = "%s is not a safetensors file (its header does not parse)"
M_NO_PAIRS = ("%s has no LoRA weight pairs (lora_A/lora_B, lora_down/lora_up or lora.down/lora.up) in its "
              "safetensors header, so mflux would apply nothing")
M_READ = "cannot read %s: %s"
M_ID_TAKEN = "LoRA id %s already exists; choose another id or remove it first"
M_DUPLICATE = "%s is already in the registry as %s"
M_UNREADABLE = "the custom LoRA registry %s is unreadable: %s; fix or delete it, then retry"
M_UNWRITABLE = "cannot write the custom LoRA registry %s: %s"                # plan SC12
M_BUILTIN = "%s is a built-in LoRA and cannot be removed"
M_UNKNOWN = "unknown custom LoRA %s (custom LoRAs: %s)"
M_LOCAL_MISSING = ("%s is missing or not a regular file (restore it, or re-run bin/seed-edit-lora add after "
                   "bin/seed-edit-lora remove %s)")
M_LOCAL_CHANGED = ("%s is %d bytes; the registry recorded %d (the file changed since it was added: re-run "
                   "bin/seed-edit-lora add after bin/seed-edit-lora remove %s)")
M_HF_SIZE = "%s is %d bytes; the registry recorded %d (delete it and run bin/seed-edit-setup --lora %s again)"
M_HF_NOT_ST = "%s is not a safetensors file (bin/seed-edit-lora remove %s)"
M_HF_NO_PAIRS = ("%s has no LoRA weight pairs in its safetensors header, so mflux would apply nothing "
                 "(bin/seed-edit-lora remove %s)")
# Section 3.4: the notes add returns.
N_FAMILY_INFERRED = "family %s (the model card's base_model is %s)"
N_FAMILY_GIVEN = "family %s (given)"
N_FAMILY_CONFLICT = "warning: family %s was given, but the model card's base_model %s means %s"
N_TRIGGER = "the model card's instance_prompt is %r; pass trigger to prepend it to every edit prompt of this LoRA"
N_STEPS = "qwen2511-q4 always loads the Lightning 8-step LoRA; %d steps with Lightning are untested"
N_DOWNLOAD = "download it with: bin/seed-edit-setup --lora %s"
N_IN_PLACE = "the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"


class RegistryError(Exception):
    """A refused request (custom edit LoRAs spec CL16, D14): status is 400, 404, 409 or 502; the message is the
    text the CLI prints and the server answers."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


# ---------------------------------------------------------------------------
# The Hugging Face model API (CL17)
# ---------------------------------------------------------------------------

def fetch_model_info(repo):
    """Custom edit LoRAs spec CL17: the parsed GET /api/models/<repo>?blobs=true answer of huggingface.co, sent
    with only the User-Agent and Accept headers and no token read; RegistryError (400 or 502) for anything else.
    repo is already HF_REPO_RE-valid."""
    conn = http.client.HTTPSConnection(HF_HOST, timeout=HF_TIMEOUT_S, context=ssl.create_default_context())
    try:
        conn.request("GET", "/api/models/%s?blobs=true" % repo,
                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location")
        body = resp.read(HF_MAX_BYTES + 1)
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        text = M_HF_UNREACHABLE % (type(e).__name__, e)
        if isinstance(e, ssl.SSLCertVerificationError):
            text += M_HF_NO_CERTS
        raise RegistryError(502, text)
    finally:
        conn.close()
    if status == 200:
        if len(body) > HF_MAX_BYTES:
            raise RegistryError(502, M_HF_BIG % repo)
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, RecursionError):
            raise RegistryError(502, M_HF_JSON % repo)
    if status in (301, 302, 307, 308):
        raise RegistryError(400, M_HF_MOVED % (repo, location or "-"))
    if status in (401, 404):
        raise RegistryError(400, M_HF_NOTFOUND % repo)
    raise RegistryError(502, M_HF_STATUS % (status, repo))


# ---------------------------------------------------------------------------
# The request rules (Section 3.2) and the answer rules (Section 3.3)
# ---------------------------------------------------------------------------

def _names(names):
    """Section 3.3's file list (plan R2): at most LIST_MAX names joined ', ', then ' and N more'; 'none'."""
    if not names:
        return "none"
    text = ", ".join(names[:LIST_MAX])
    if len(names) > LIST_MAX:
        text += " and %d more" % (len(names) - LIST_MAX)
    return text


def _file_problem(name):
    """R6, and H7's check of a chosen repo file: the refusal text of a repo file name, or None."""
    if not name.lower().endswith(".safetensors"):
        return M_NOT_SAFETENSORS % name
    if not seedgen.HF_FILE_RE.fullmatch(name) or ".." in name.split("/"):
        return M_FILE % name
    return None


def check_request(request):
    """Custom edit LoRAs spec Section 3.2, R1-R12 in order (pure): the given values (a None value counts as
    absent; repo normalized to OWNER/NAME), or RegistryError(400)."""
    unknown = sorted(key for key in request if key not in FIELDS)
    if unknown:
        raise RegistryError(400, M_FIELD % unknown[0])
    given = dict((key, value) for key, value in request.items() if value is not None)
    for key in ("repo", "file", "path", "family", "id", "label", "trigger"):
        if key in given and not isinstance(given[key], str):
            raise RegistryError(400, M_STRING % key)
    if ("repo" in given) == ("path" in given):
        raise RegistryError(400, M_ONE_SOURCE)
    if "file" in given and "repo" not in given:
        raise RegistryError(400, M_FILE_ONLY_REPO)
    if "repo" in given:
        text = given["repo"]
        found = HF_URL_RE.fullmatch(text)
        repo = found.group(1) if found else text
        if not (seedgen.HF_REPO_RE.fullmatch(repo) and ".." not in repo and "--" not in repo):
            raise RegistryError(400, M_REPO % text)
        given["repo"] = repo
    if "file" in given:
        problem = _file_problem(given["file"])
        if problem is not None:
            raise RegistryError(400, problem)
    if "family" in given and given["family"] not in seedgen.QWEN_FAMILIES:
        raise RegistryError(400, M_FAMILY % given["family"])
    if "path" in given and "family" not in given:
        raise RegistryError(400, M_FAMILY_LOCAL)
    if "id" in given and not seedgen.USER_ID_RE.fullmatch(given["id"]):
        raise RegistryError(400, M_ID % given["id"])
    if "label" in given and not seedgen._plain_text(given["label"], seedgen.LABEL_MAX):
        raise RegistryError(400, M_LABEL)
    if "trigger" in given and not seedgen.valid_trigger(given["trigger"]):
        raise RegistryError(400, M_TRIGGER)
    if "scale" in given and not (lib._is_number(given["scale"]) and 0 < given["scale"] <= seedgen.SCALE_MAX):
        raise RegistryError(400, M_SCALE)
    if "steps" in given and not (lib._is_int(given["steps"]) and 1 <= given["steps"] <= seedgen.STEPS_MAX):
        raise RegistryError(400, M_STEPS)
    return given


def _card(info):
    """The cardData dict of an API answer, else {}."""
    card = info.get("cardData") if isinstance(info, dict) else None
    return card if isinstance(card, dict) else {}


def _hf_family(given, card):
    """H9's family: (family, the N-FAMILY notes), or RegistryError(400) (plan R4)."""
    base = card.get("base_model")
    if isinstance(base, str):
        bases = [base]
    elif isinstance(base, list):
        bases = [b for b in base if isinstance(b, str)]
    else:
        bases = []
    base_text = ", ".join(bases) or "none"
    families = sorted(set(BASE_MODEL_FAMILIES[b] for b in bases if b in BASE_MODEL_FAMILIES))
    if "family" in given:
        family = given["family"]
        notes = [N_FAMILY_GIVEN % family]
        if len(families) == 1 and families[0] != family:
            notes.append(N_FAMILY_CONFLICT % (family, base_text, families[0]))
        return family, notes
    if not families:
        raise RegistryError(400, M_HF_BASE_UNKNOWN % base_text)
    if len(families) > 1:
        raise RegistryError(400, M_HF_BASE_BOTH)
    return families[0], [N_FAMILY_INFERRED % (families[0], base_text)]


def _licence(card):
    """H9's licence: the card's license text, a list joined ', ', 'other (<license_name>)', else NO_LICENSE; cut to
    LICENSE_MAX characters (plan R4)."""
    value, name = card.get("license"), card.get("license_name")
    if value == "other" and isinstance(name, str) and name.strip():
        text = "other (%s)" % name.strip()
    elif isinstance(value, str):
        text = value
    elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        text = ", ".join(value)
    else:
        text = ""
    return text.strip()[:seedgen.LICENSE_MAX] or NO_LICENSE


def _hf_fields(repo, given, info):
    """Custom edit LoRAs spec Section 3.3, H1-H9 on repo's API answer: (revision, file, bytes, family, licence,
    the family notes), or RegistryError."""
    sha = info.get("sha") if isinstance(info, dict) else None
    siblings = info.get("siblings") if isinstance(info, dict) else None
    if not (isinstance(sha, str) and SHA_RE.fullmatch(sha) and isinstance(siblings, list)):
        raise RegistryError(502, M_HF_NO_MODEL % repo)
    if info.get("disabled") is True:
        raise RegistryError(400, M_HF_DISABLED % repo)
    if info.get("gated") not in (False, None):
        raise RegistryError(400, M_HF_GATED % (repo, info.get("gated")))
    sizes = {}
    for item in siblings:
        if isinstance(item, dict) and isinstance(item.get("rfilename"), str):
            sizes[item["rfilename"]] = item.get("size")
    names = list(sizes)
    tensors = [n for n in names if n.lower().endswith(".safetensors")]
    if "file" in given:
        name = given["file"]
        if name not in sizes:
            raise RegistryError(400, M_HF_FILE_MISSING % (name, repo, sha[:12], _names(tensors)))
    else:
        roots = [n for n in tensors if "/" not in n]
        if not roots:
            text = M_HF_NO_ROOT % (repo, sha[:12])
            folders = [n for n in tensors if "/" in n]
            if folders:
                text += M_HF_NO_ROOT_FOLDERS % _names(folders)
            pickles = [n for n in names if n.lower().endswith(PICKLE_EXTS)]
            if pickles:
                text += M_HF_NO_ROOT_PICKLE % _names(pickles)
            raise RegistryError(400, text)
        if len(roots) > 1:
            raise RegistryError(400, M_HF_SEVERAL % (repo, sha[:12], len(roots), _names(roots)))
        name = roots[0]
    if _file_problem(name) is not None:
        raise RegistryError(400, M_HF_BAD_NAME % name)
    size = sizes[name]
    if not (lib._is_int(size) and size >= 1):
        raise RegistryError(502, M_HF_NO_SIZE % name)
    if size > seedgen.USER_LORA_MAX_BYTES:
        raise RegistryError(400, M_TOO_BIG % (name, size / 2 ** 30))
    card = _card(info)
    family, notes = _hf_family(given, card)
    return sha, name, size, family, _licence(card), notes


# ---------------------------------------------------------------------------
# The files (CL18, CL19, CL22b)
# ---------------------------------------------------------------------------

def check_local_file(path_text, base_dir):
    """Custom edit LoRAs spec CL18 (D7, SC6): (path, real, size) of a local LoRA file, first failure wins, else
    RegistryError(400). path keeps symlinks (os.path.abspath); the regular-file and size checks use real."""
    expanded = os.path.expanduser(path_text)
    if not os.path.isabs(expanded):
        if base_dir is None:
            raise RegistryError(400, M_PATH_ABS % path_text)
        expanded = os.path.join(base_dir, expanded)
    path = os.path.abspath(expanded)
    if any(c < "\x20" or c == "\x7f" for c in path):
        raise RegistryError(400, M_PATH_CONTROL)
    if not path.lower().endswith(".safetensors"):
        raise RegistryError(400, M_NOT_SAFETENSORS % path)
    if not os.path.exists(path):
        raise RegistryError(400, M_NOT_EXIST % path)
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise RegistryError(400, M_NOT_REGULAR % path)
    size = os.path.getsize(real)
    if size > seedgen.USER_LORA_MAX_BYTES:
        raise RegistryError(400, M_TOO_BIG % (path, size / 2 ** 30))
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        raise RegistryError(400, M_NOT_ST_HEADER % path)
    if lora_pair_count(header) == 0:
        raise RegistryError(400, M_NO_PAIRS % path)
    return path, real, size


def lora_pair_count(header):
    """Custom edit LoRAs spec CL19 (D6): the number of header keys K for which one PAIR_SUBSTITUTIONS swap on
    K + "." (first occurrence) names another key of the header."""
    count = 0
    for key in header:
        probe = key + "."
        for a, b in PAIR_SUBSTITUTIONS:
            if a in probe and probe.replace(a, b, 1)[:-1] in header:
                count += 1
                break
    return count


def local_problem(lora):
    """Custom edit LoRAs spec CL22b: None when a local custom LoRA's file is still a regular file of its recorded
    size (no hash, no header read), else the refusal text."""
    real = os.path.realpath(lora["path"])
    if not os.path.isfile(real):
        return M_LOCAL_MISSING % (lora["path"], lora["id"])
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_LOCAL_CHANGED % (lora["path"], size, lora["bytes"], lora["id"])
    return None


def downloaded_problem(lora, path):
    """Custom edit LoRAs spec CL22b: None when the downloaded file at path of a Hugging Face custom LoRA has its
    recorded size and a safetensors header with LoRA pairs, else the refusal text."""
    real = os.path.realpath(path)
    size = os.path.getsize(real)
    if size != lora["bytes"]:
        return M_HF_SIZE % (path, size, lora["bytes"], lora["id"])
    try:
        header = lora_catalog.read_safetensors_header(real)
    except lora_catalog.CatalogError:
        return M_HF_NOT_ST % (path, lora["id"])
    if lora_pair_count(header) == 0:
        return M_HF_NO_PAIRS % (path, lora["id"])
    return None


# ---------------------------------------------------------------------------
# The registry file (CL20) and the ids (CL22)
# ---------------------------------------------------------------------------

def load_entries():
    """Custom edit LoRAs spec CL20: the user entries of the registry file (a list, file order); [] when it is
    missing; RegistryError(409, M_UNREADABLE) when it cannot be read, is not JSON or fails
    movie_ui_seedgen.user_loras_problem."""
    path = seedgen.user_loras_path()
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RegistryError(409, M_UNREADABLE % (path, "cannot read: %s" % e))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise RegistryError(409, M_UNREADABLE % (path, "not valid JSON"))
    problem = seedgen.user_loras_problem(data)
    if problem is not None:
        raise RegistryError(409, M_UNREADABLE % (path, problem))
    return list(data["loras"])


def save_entries(entries):
    """Custom edit LoRAs spec CL20: write {schema, loras: entries} to the registry file with
    movie_ui_lib.write_json_atomic (an atomic replace, mode 0600, indent 2). The caller holds the lock."""
    lib.write_json_atomic(seedgen.user_loras_path(), {"schema": seedgen.USER_LORAS_SCHEMA, "loras": entries})


def slug(text):
    """Custom edit LoRAs spec CL22: lower-case, runs of other characters as '-', cut to 24; 'lora' when empty."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].rstrip("-") or "lora"


def default_id(base, ids):
    """Custom edit LoRAs spec CL22: "user-" + base when free, else the first free "user-<base cut>-<n>", n >= 2."""
    if "user-" + base not in ids:
        return "user-" + base
    n = 2
    while True:
        suffix = "-%d" % n
        candidate = "user-" + base[:24 - len(suffix)].rstrip("-") + suffix
        if candidate not in ids:
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# add and remove (CL21, CL22a)
# ---------------------------------------------------------------------------

def add(request, base_dir):
    """Custom edit LoRAs spec CL21: register one custom LoRA. request holds FIELDS values (a None value counts as
    absent); base_dir resolves a relative path (None refuses one). Returns (entry, notes); raises RegistryError."""
    given = check_request(request)
    if "repo" in given:
        repo = given["repo"]
        info = fetch_model_info(repo)
        revision, name, size, family, licence, notes = _hf_fields(repo, given, info)
        instance = _card(info).get("instance_prompt")
        if "trigger" not in given and isinstance(instance, str):
            notes.append(N_TRIGGER % instance)
        source_name = repo.split("/", 1)[1]
    else:
        local, real, size = check_local_file(given["path"], base_dir)
        try:
            sha256 = lora_catalog.file_sha256(real)
        except OSError as e:
            raise RegistryError(400, M_READ % (local, e))
        family, notes = given["family"], []
        name = os.path.basename(local)
        source_name = name[:-len(".safetensors")]
    if "steps" in given and family == "qwen2511":
        notes.append(N_STEPS % given["steps"])
    path = seedgen.user_loras_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with lora_catalog.catalog_lock(path):
            entries = load_entries()
            ids = seedgen.BUILTIN_QWEN_LORA_IDS + tuple(e["id"] for e in entries)
            if "id" in given and given["id"] in ids:
                raise RegistryError(409, M_ID_TAKEN % given["id"])
            if "repo" in given:
                same = [l for l in seedgen.BUILTIN_QWEN_LORAS + tuple(entries)
                        if l.get("repo") == repo and l.get("file") == name]
                what = "%s:%s" % (repo, name)
            else:
                same = [e for e in entries if e["source"] == "local" and (e["path"] == local or e["sha256"] == sha256)]
                what = local
            if same:
                raise RegistryError(409, M_DUPLICATE % (what, same[0]["id"]))
            lora_id = given["id"] if "id" in given else default_id(slug(source_name), ids)
            scale = float(given.get("scale") or 1.0)
            if "repo" in given:
                entry = {"id": lora_id, "label": given.get("label") or repo[:seedgen.LABEL_MAX], "family": family,
                         "source": "hf", "repo": repo, "revision": revision, "file": name, "bytes": size,
                         "default_on": False, "default_scale": scale, "license": licence, "steps": given.get("steps"),
                         "scheduler": None, "trigger": given.get("trigger"), "user": True}
            else:
                entry = {"id": lora_id, "label": given.get("label") or name[:seedgen.LABEL_MAX], "family": family,
                         "source": "local", "path": local, "file": name, "sha256": sha256, "bytes": size,
                         "default_on": False, "default_scale": scale, "license": LOCAL_LICENSE,
                         "steps": given.get("steps"), "scheduler": None, "trigger": given.get("trigger"), "user": True}
            problem = seedgen.user_loras_problem({"schema": seedgen.USER_LORAS_SCHEMA, "loras": [entry]})
            if problem is not None:
                raise AssertionError("seed_lora_registry.add built an invalid entry: %s" % problem)
            save_entries(entries + [entry])
    except OSError as e:
        raise RegistryError(409, M_UNWRITABLE % (path, e))
    notes.append(N_DOWNLOAD % lora_id if "repo" in given else N_IN_PLACE)
    return entry, notes


def remove(lora_id):
    """Custom edit LoRAs spec CL22a: drop custom LoRA lora_id from the registry file; no file is deleted. Returns
    (entry, kept): a local entry's path, else the downloaded snapshot file (None when it was never downloaded)."""
    if lora_id in seedgen.BUILTIN_QWEN_LORA_IDS:
        raise RegistryError(400, M_BUILTIN % lora_id)
    path = seedgen.user_loras_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with lora_catalog.catalog_lock(path):
            entries = load_entries()
            found = [e for e in entries if e["id"] == lora_id]
            if not found:
                raise RegistryError(404, M_UNKNOWN % (lora_id, ", ".join(e["id"] for e in entries) or "none"))
            save_entries([e for e in entries if e["id"] != lora_id])
    except OSError as e:
        raise RegistryError(409, M_UNWRITABLE % (path, e))
    entry = found[0]
    if entry["source"] == "local":
        return entry, entry["path"]
    import qwen_edit
    return entry, qwen_edit.pinned_file(entry["repo"], entry["revision"], entry["file"], qwen_edit.qwen_hubs())
```

- [ ] **Step 4: Create `bin/seed-edit-lora` (CL23, CL24, SC4) and stage it executable (SC9).** Write exactly this content:

```python
#!/usr/bin/env python3
"""seed-edit-lora -- register a custom Qwen edit LoRA (a public Hugging Face repo pinned at its current
commit, or a local .safetensors file used in place), list the registry, or remove a custom LoRA
(docs/superpowers/specs/2026-11-17-custom-edit-loras-design.md, Section 2.3).

  bin/seed-edit-lora add (--repo OWNER/NAME [--file F] | --path P) [--family qwen21|qwen2511] [--id ID]
                         [--label TEXT] [--trigger TEXT] [--scale S] [--steps N]
  bin/seed-edit-lora list
  bin/seed-edit-lora remove ID

add makes one unauthenticated call to the Hugging Face model API for --repo and never downloads weights
(bin/seed-edit-setup --lora ID does); for --path it reads the file's header and sha256, and a relative
path or one starting with ~ is resolved against the current directory or HOME. remove deletes the registry
entry only, never a file. The registry is $SEED_EDIT_USER_LORAS, else <ws>/generated/seed_loras/user_loras.json.
Every stdout line starts "seed-edit-lora: " except the list table; errors go to stderr as "Error: <message>".

Exit codes: 0 done; 1 the Hugging Face API failed; 2 a refused request (a bad option or value, an unknown or
built-in ID, a duplicate, an unreadable or unwritable registry) or an argparse usage error.
Standard library plus movie_ui_seedgen and seed_lora_registry (qwen_edit inside list). Python 3.9 and 3.13.
"""

import argparse
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import movie_ui_seedgen as seedgen  # noqa: E402
import seed_lora_registry as registry  # noqa: E402


def say(text):
    print("seed-edit-lora: " + text, flush=True)


def error(text, code):
    sys.stderr.write("Error: %s\n" % text)
    sys.stderr.flush()
    return code


def add(args):
    """CL23, CL24: convert --scale and --steps, add the LoRA, then print the notes and the added line."""
    import re
    request = dict((name, getattr(args, name)) for name in registry.FIELDS)
    if request["scale"] is not None:
        try:
            request["scale"] = float(request["scale"])
        except ValueError:
            return error(registry.M_SCALE, 2)
    if request["steps"] is not None:
        if not re.fullmatch(r"[0-9]+", request["steps"]):
            return error(registry.M_STEPS, 2)
        request["steps"] = int(request["steps"])
    entry, notes = registry.add(request, os.getcwd())
    for note in notes:
        say(note)
    gib = entry["bytes"] / 2 ** 30
    if entry["source"] == "hf":
        say("added %s: %s@%s %s (%.2f GiB, %s)" % (entry["id"], entry["repo"], entry["revision"][:12], entry["file"],
                                                   gib, entry["license"]))
    else:
        say("added %s: %s (%.2f GiB, sha256 %s)" % (entry["id"], entry["path"], gib, entry["sha256"][:12]))
    return 0


def show_list():
    """CL24: every registry LoRA as one tab-separated line, then the registry line."""
    import qwen_edit
    hubs = qwen_edit.qwen_hubs()
    print("ID\tFAMILY\tSOURCE\tWHERE\tSCALE\tTRIGGER\tINSTALLED", flush=True)
    custom = 0
    for lora in seedgen.qwen_loras():
        source = lora.get("source", "builtin")
        if source == "local":
            where = lora["path"]
        else:
            where = "%s@%s %s" % (lora["repo"], lora["revision"][:12], lora["file"])
        problem = qwen_edit.lora_problem(lora, hubs)[0]
        print("\t".join([lora["id"], lora["family"], source, where, "%g" % lora["default_scale"],
                         lora.get("trigger") or "-", "yes" if problem is None else "no: " + problem]), flush=True)
        if lora.get("user"):
            custom += 1
    say("registry %s (%d custom)" % (seedgen.user_loras_path(), custom))
    return 0


def remove(lora_id):
    """CL24: remove the entry, then say where its file stays."""
    entry, kept = registry.remove(lora_id)
    if entry["source"] == "local":
        tail = "the file stays at %s" % kept
    elif kept is not None:
        tail = "its downloaded file stays at %s" % kept
    else:
        tail = "it was never downloaded"
    say("removed %s from %s; %s" % (entry["id"], seedgen.user_loras_path(), tail))
    return 0


def main(argv=None):
    """bin/seed-edit-lora (custom edit LoRAs spec CL23, CL24). Returns the exit code."""
    parser = argparse.ArgumentParser(prog="seed-edit-lora", description="Register, list or remove the custom Qwen "
                                     "edit LoRAs of Seeds, Locations, Characters, Compose and --seed-edit-lora.")
    commands = parser.add_subparsers(dest="command", required=True)
    add_parser = commands.add_parser("add", help="register a public Hugging Face LoRA or a local .safetensors file")
    for name in ("--repo", "--file", "--path", "--family", "--id", "--label", "--trigger", "--scale", "--steps"):
        add_parser.add_argument(name, type=str, default=None)
    commands.add_parser("list", help="show every registry LoRA and whether it is installed")
    remove_parser = commands.add_parser("remove", help="drop a custom LoRA from the registry (never a file)")
    remove_parser.add_argument("id", type=str)
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            return add(args)
        if args.command == "list":
            return show_list()
        return remove(args.id)
    except registry.RegistryError as e:
        return error(str(e), 1 if e.status == 502 else 2)


if __name__ == "__main__":
    sys.exit(main())
```

Then make it executable and stage it (CL-T24 reads its git mode):

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
chmod 755 bin/seed-edit-lora
git add bin/seed-edit-lora
git update-index --chmod=+x bin/seed-edit-lora
git ls-files -s bin/seed-edit-lora | cut -c1-6        # expected: 100755
```

- [ ] **Step 5: Run the new file to verify it passes.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_lora_registry.py 2>&1 | tail -3`
Expected: `65 passed` (15 Task 1 tests, then CL-T5, CL-T6 x2, CL-T7 34 cases + the CLI test, CL-T8, CL-T9, CL-T10, CL-T12, CL-T13, CL-T22, CL-T24 x2 + the scan test, Review Focus 2-4), or `64 passed, 1 skipped` where `/usr/bin/python3` is absent.

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py tests/test_qwen_edit.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_builder.py 2>&1 | tail -1`
Expected: no `failed`.

- [ ] **Step 6: Verify: CLK4, the compile check and the pinned files.**

Run: `git grep --untracked -c HTTPSConnection -- . ':(exclude)docs'` — Expected: exactly `seed_lora_registry.py:1` (CLK4, SC3).

Run the compile check with `FILES` = `seed_lora_registry.py bin/seed-edit-lora tests/test_seed_lora_registry.py` — Expected: `compiled 3` twice.

Run the pinned-file check of "Global Constraints" — Expected: `pinned files unchanged` and `tests/test_movie_ui_builder.py` with no `failed`.

- [ ] **Step 7: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git add seed_lora_registry.py bin/seed-edit-lora tests/test_seed_lora_registry.py
git diff --cached --name-only                 # expected: exactly these three paths, with the qwen-agent-workspace/ prefix
git commit -m "custom edit LoRAs: seed_lora_registry add/remove/list, the Hugging Face answer rules and bin/seed-edit-lora (Task 2)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git ls-tree HEAD bin/seed-edit-lora | cut -c1-6  # expected: 100755
```

- [ ] **Step 8: The gate (controller).** Run `zsh $D/gate-run.sh 2`. Expected: `lost 0 (listed 0, unexpected 0); new tests 65, not passing 0; baseline failures still failing 2 of 2` (`not passing` counts a `SKIPPED` 3.9 compile as passing), `GATE PASS`, `3 passed`, `ATK2 OK lines unchanged`. Then an Opus design review of the Task 2 commit against CL15-CL24, SC3-SC6, SC9 and SC12 before Task 3 starts.

---
### Task 3: The server routes and the page (CL35, CL37-CL44, SC8, SC10; E6; CL-T25-CL-T34, Review Focus 5)

This task exposes Task 2's add and remove over HTTP, refreshes the cached `seed_edit` capability after each, exports the registry path to every child, writes the triggered initial `run.json` prompt, and adds the "Add custom LoRA" form, the custom rows and the bf16 note to the six Qwen pickers.

**Files:**
- Modify: `movie_ui_server.py` (ROUTES after `:110`; `refresh_seed_edit` before `capability_snapshot` `:237`; `_h_seed_run_create` `:1877`; the handlers after `_h_seed_folders` `:2013` and their bindings after `:2021`; `main` `:720`)
- Modify: `static/movie-ui/app.js` (before the `qwenPicker` comment `:1980`; inside `qwenPicker`: after `enabled` `:1991`, after the registry check `:2033`, `loraNote` `:2070-2074`, the rows `:2075-2096`, the steps line `:2101`)
- Modify: `tests/test_movie_ui_http.py:44`, `tests/test_location_ui.py:66`, `tests/test_movie_ui_seedfolder.py:923`, `:960`, `tests/test_movie_ui_seedgen.py:627` (E6)
- Modify: `tests/test_seed_lora_registry.py` (CL-T24's `COMPILED` and `SCANNED`; SC8)
- Test: `tests/test_movie_ui_seed_loras.py` (create)

**Interfaces:**
- Consumes (Task 1): `seedgen.qwen_lora_ids()`, `seedgen.registry_view()`, `seedgen.capability(models, detail, checked)`, `seedgen.trigger_prompt(prompt, loras)`, `seedgen.user_loras_path()`, `seedgen.USER_LORAS_ENV`, `seedgen.BUILTIN_QWEN_LORA_IDS`, `seedgen.QWEN_MODEL_IDS`, `lib.PROBE_NOT_REPORTED`; (Task 2) `seed_lora_registry.add(request, base_dir)`, `seed_lora_registry.remove(lora_id)`, `seed_lora_registry.RegistryError` (`.status`); test helpers of `tests/test_seed_lora_registry.py` (`slr`): `REPO`, `FILE`, `SHA`, `TRIGGER`, `INFO`, `pairs`, `safetensors`, `hf_entry`, `local_entry`, `write_registry`, `fake_fetch`. Existing server names: `ApiError(status, message)`, `MovieUIServer.cap_lock`, `.capabilities`, `.probe_ws`, `.capability_snapshot()`, `lib.seed_edit_check`, `lib.utc_now`; page names: `el`, `node`, `api`, `askConfirm`, `enc`, `show`, `renderBadges`, `S.host`.
- Produces: routes `POST /api/seed-loras` (`h_seed_lora_add`) and `DELETE /api/seed-loras/(user-[a-z0-9-]{1,24})` (`h_seed_lora_remove`); `movie_ui_server.SEED_LORA_DELETE_BODY`; `MovieUIServer.refresh_seed_edit()`; `len(ROUTES) == 66`; page functions `customLoraForm(prefix)` and `customLoraBody(v)`.

- [ ] **Step 1: Write the failing test file.** Create `tests/test_movie_ui_seed_loras.py` with exactly this content:

```python
"""Tests for the custom edit LoRAs' server routes and page (docs/superpowers/specs/2026-11-17-custom-edit-loras-
design.md, Section 5.1: CL-T25-CL-T34, with the plan's Review Focus pin 5): POST and DELETE /api/seed-loras, the
seed_edit capability refresh, the triggered initial run.json prompt, old records after a remove, main's
environment, the "Add custom LoRA" form and the picker rows in app.js, and the unchanged batch forks.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py

Rules (spec 5.1): the HTTP tests use the env fixture (tests/test_movie_ui_seedgen.py's pattern): mt.set_home,
mt.make_stub_workspace and the in-test mt.Running server on 127.0.0.1, whose probe_ws is the stub workspace. The
workspace's bin/seed-edit is stub_seed_edit's (it counts its --probe runs in <ws>/probe_calls.txt). The registry
file is conftest's per-test isolation file. seed_lora_registry.fetch_model_info is patched (slr.fake_fetch), so
nothing contacts the Hugging Face API; node runs only where it is installed. No test loads a model, dispatches a
job or uses the real HOME.
Stdlib and pytest.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv
import qwen_edit as qe
import test_seed_lora_registry as slr

WS = mt.WS
OK = {"ok": True, "reason": None}
OK_Z = {"ok": True, "reason": None, "backend": "zimage"}
LORA_ID = "user-anything-to-real-charact"
NO_LORAS = ("LoRA user-local: qwen2511-bf16 runs without LoRAs (its diffusers child loads only the built-in "
            "Lightning LoRA); use qwen2511-q4")
STUB = '''#!{python}
import sys
if sys.argv[1:] == ["--probe"]:
    with open({calls!r}, "a", encoding="utf-8") as f:
        f.write("probe\\n")
    sys.stdout.write({out!r} + "\\n")
'''


def qwen_probe(lora_ids):
    """A probe qwen entry: every registry model ok, and one ok entry per id of lora_ids."""
    return {"ok": True, "reason": None, "models": dict((i, OK) for i in seedgen.QWEN_MODEL_IDS),
            "loras": dict((i, OK) for i in lora_ids)}


OK_MODELS = {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS)}


def stub_seed_edit(ws, models):
    """<ws>/bin/seed-edit as a stub: for --probe it appends one line to <ws>/probe_calls.txt and prints
    json.dumps(models). Returns its path."""
    path = os.path.join(ws, "bin", "seed-edit")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STUB.format(python=sys.executable, calls=os.path.join(ws, "probe_calls.txt"), out=json.dumps(models)))
    os.chmod(path, 0o755)
    return path


def probe_count(ws):
    try:
        with open(os.path.join(ws, "probe_calls.txt"), encoding="utf-8") as f:
            return len(f.read().splitlines())
    except OSError:
        return 0


def clean_env(monkeypatch, tmp_path):
    """No HF_HUB_CACHE and no SEED_EDIT_* variable but SEED_EDIT_USER_LORAS (spec E2); HF_HOME and
    Z_IMAGE_HF_HOME under tmp_path."""
    for key in list(os.environ):
        if key.startswith("SEED_EDIT_") and key != "SEED_EDIT_USER_LORAS":
            monkeypatch.delenv(key)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", os.path.join(str(tmp_path), "hf"))
    monkeypatch.setenv("Z_IMAGE_HF_HOME", os.path.join(str(tmp_path), "zi"))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_UI_VLM_LIFECYCLE", "0")
    monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)
    state = mt.set_home(monkeypatch, tmp_path)
    clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    stub_seed_edit(ws, OK_MODELS)
    monkeypatch.setattr(srv, "seed_free_gib", lambda path: 100.0)
    asked = slr.fake_fetch(monkeypatch)
    running = mt.Running(state)
    running.server.probe_ws = ws
    yield {"state": state, "ws": ws, "tmp": str(tmp_path), "srv": running, "mp": monkeypatch, "asked": asked,
           "registry": seedgen.user_loras_path()}
    running.close()
    mt.kill_everything(state)


def _upload(s):
    status, _h, payload = mt.api(s, "POST", "/api/uploads", raw=mt.PNG + b"src", headers={"Content-Type": "image/png"})
    assert status == 201, payload
    return payload["upload_id"]


def _run_body(ws, up, model_id, lora_ids):
    return {"ws": ws, "source": {"upload_id": up}, "prompt": "make it night", "model": "qwen", "qwen_model": model_id,
            "loras": [{"id": i, "scale": 1.0} for i in lora_ids], "candidates": 1, "seed": 7}


# --- CL-T25 (CL35): the routes ---------------------------------------------------------------------------------------

NEW_ROUTES = [("POST", r"/api/seed-loras", "h_seed_lora_add", "/api/seed-loras"),
              ("DELETE", r"/api/seed-loras/(user-[a-z0-9-]{1,24})", "h_seed_lora_remove",
               "/api/seed-loras/user-anything-to-real")]


def test_cl_t25_the_routes(env):
    s = env["srv"]
    routes = list(srv.ROUTES)
    i = routes.index(("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"))
    assert routes[i + 1:i + 3] == NEW_ROUTES
    assert len(srv.ROUTES) == 66
    for method, regex, name, sample in NEW_ROUTES:
        assert re.fullmatch(regex, sample), sample
        assert getattr(srv.MovieUIHandler, name) is getattr(srv, "_" + name), name
        for token in (None, "wrong-token"):
            assert mt.api(s, method, sample, body={} if method == "POST" else None, token=token)[::2] == (
                401, {"error": "missing or invalid token"}), (sample, token)
    assert mt.api(s, "GET", "/api/seed-loras")[::2] == (405, {"error": "method not allowed"})
    assert mt.api(s, "DELETE", "/api/seed-loras/uncensored")[::2] == (404, {"error": "not found"})
    assert srv.SEED_LORA_DELETE_BODY == "DELETE /api/seed-loras/<id> takes no body"
    assert probe_count(env["ws"]) == 0


# --- CL-T26 (CL38, R1-R12): bad bodies get the CLI's texts ----------------------------------------------------------

BAD_BODIES = [({"repo": slr.REPO, "ws": "/abs/ws"}, slr.FIELDS_TEXT % "ws"),
              ({"repo": slr.REPO, "scale": "x"}, slr.SCALE_TEXT),
              ({"repo": slr.REPO, "scale": True}, slr.SCALE_TEXT),
              ({"repo": slr.REPO, "steps": 2.5}, slr.STEPS_TEXT),
              ({"repo": slr.REPO, "path": "/abs/x.safetensors"}, slr.ONE_SOURCE),
              ({"path": "rel/x.safetensors", "family": "qwen2511"},
               "path must be an absolute path or start with ~ (got rel/x.safetensors)")]


def test_cl_t26_bad_bodies_get_the_cli_texts(env):
    for body, message in BAD_BODIES:
        assert mt.api(env["srv"], "POST", "/api/seed-loras", body=body)[::2] == (400, {"error": message}), body
    assert env["asked"] == [] and not os.path.exists(env["registry"]) and probe_count(env["ws"]) == 0


# --- CL-T27 (CL38): POST a Hugging Face LoRA ------------------------------------------------------------------------

def test_cl_t27_post_a_hugging_face_lora(env):
    s, ws = env["srv"], env["ws"]
    status, _h, data = mt.api(s, "POST", "/api/seed-loras", body={"repo": slr.REPO, "trigger": slr.TRIGGER})
    assert status == 201, data
    assert data["lora"] == {"id": LORA_ID, "label": slr.REPO, "family": "qwen2511", "default_on": False,
                            "default_scale": 1.0, "steps": None, "scheduler": None, "license": "apache-2.0",
                            "user": True, "source": "hf", "trigger": slr.TRIGGER,
                            "setup": "bin/seed-edit-setup --lora " + LORA_ID}
    assert data["notes"] == ["family qwen2511 (the model card's base_model is Qwen/Qwen-Image-Edit-2511)",
                             "download it with: bin/seed-edit-setup --lora " + LORA_ID]
    cap = data["seed_edit"]
    assert cap["registry"] == seedgen.registry_view() and data["lora"] in cap["registry"]["loras"]
    assert probe_count(ws) == 1 and env["asked"] == [slr.REPO]
    assert cap["ok"] is True and cap["models"]["qwen"]["loras"][LORA_ID] == {
        "ok": False, "reason": lib.PROBE_NOT_REPORTED}
    assert mt.api(s, "GET", "/api/host")[2]["capabilities"]["seed_edit"] == cap


# --- CL-T28 (CL38): POST a local LoRA, then DELETE it ----------------------------------------------------------------

def test_cl_t28_post_local_and_delete(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    status, _h, data = mt.api(s, "POST", "/api/seed-loras", body={"path": path, "family": "qwen2511", "id": "user-real"})
    assert status == 201, data
    assert (data["lora"]["id"], data["lora"]["source"], data["lora"]["setup"]) == ("user-real", "local", None)
    assert data["notes"] == ["the file is used in place: moving, replacing or resizing it makes this LoRA unavailable"]
    status, _h, data = mt.api(s, "DELETE", "/api/seed-loras/user-real")
    assert status == 200, data
    assert set(data) == {"removed", "kept", "seed_edit"} and (data["removed"], data["kept"]) == ("user-real", path)
    assert "user-real" not in [l["id"] for l in data["seed_edit"]["registry"]["loras"]]
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS and os.path.isfile(path)
    assert probe_count(ws) == 2
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real")[::2] == (
        404, {"error": "unknown custom LoRA user-real (custom LoRAs: none)"})
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real", body={"x": 1})[::2] == (
        400, {"error": "DELETE /api/seed-loras/<id> takes no body"})
    assert mt.api(s, "DELETE", "/api/seed-loras/user-real", body={})[0] == 404
    assert probe_count(ws) == 2


# --- CL-T29 (CL13, CL36, CL37): a Seeds run with a custom LoRA -------------------------------------------------------

def test_cl_t29_a_seeds_run_with_a_custom_lora(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    entry = slr.local_entry(path)
    slr.write_registry(env["registry"], [entry])
    stub_seed_edit(ws, {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS + ("user-local",))})
    up = _upload(s)
    assert mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, up, "qwen2511-bf16", ["user-local"]))[::2] == (
        400, {"error": NO_LORAS})
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, up, "qwen2511-q4", ["user-local"]))
    assert status == 201, data
    with open(os.path.join(data["run"]["dir"], "run.json"), encoding="utf-8") as f:
        record = json.load(f)
    assert record["prompt"] == slr.TRIGGER + " make it night" == data["run"]["prompt"]
    assert record["loras"] == [{"id": "user-local", "source": "local", "file": "real.safetensors",
                                "sha256": entry["sha256"], "scale": 1.0, "trigger": slr.TRIGGER}]
    job = lib.read_job(lib.job_dir(state, record["job"]))
    argv = job["argv"]
    assert argv[argv.index("--prompt") + 1] == "make it night" and job["fields"]["prompt"] == "make it night"
    assert argv[argv.index("--lora") + 1] == "user-local=1.0"


# --- CL-T30 (CL45): old records after a remove -------------------------------------------------------------------------

def test_cl_t30_old_records_after_a_remove(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    slr.write_registry(env["registry"], [slr.hf_entry(), slr.local_entry(path)])
    stub_seed_edit(ws, {"zimage": OK_Z, "qwen": qwen_probe(seedgen.BUILTIN_QWEN_LORA_IDS + ("user-hf", "user-local"))})
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs",
                              body=_run_body(ws, _upload(s), "qwen2511-q4", ["user-local", "user-hf"]))
    assert status == 201, data
    run = data["run"]["run"]
    with open(os.path.join(data["run"]["dir"], "run.json"), encoding="utf-8") as f:
        recorded = json.load(f)["loras"]
    assert [l["id"] for l in recorded] == ["user-hf", "user-local"]
    for lora_id in ("user-hf", "user-local"):
        assert mt.api(s, "DELETE", "/api/seed-loras/" + lora_id)[0] == 200, lora_id
    assert seedgen.qwen_lora_ids() == seedgen.BUILTIN_QWEN_LORA_IDS
    status, _h, data = mt.api(s, "GET", "/api/seeds/runs?ws=" + ws)
    assert status == 200 and [(r["run"], r["loras"]) for r in data["runs"]] == [(run, recorded)]
    status, _h, view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (run, ws))
    assert status == 200 and view["loras"] == recorded and view["qwen_model"]["id"] == "qwen2511-q4"
    chosen = qe.selection_of(view)
    assert chosen == ("qwen2511-q4", [{"id": "user-hf", "scale": 1.0}, {"id": "user-local", "scale": 1.0}])
    assert qe.generator_text(*chosen) == ("Qwen-Image-Edit-2511 q4 (Lightning) (mflux-community/qwen-image-edit-2511-"
                                          "mflux-q4) + LoRAs user-hf@1, user-local@1, 8 steps")


# --- CL-T31 (CL39): main exports the registry path before the threads start -------------------------------------------

def test_cl_t31_main_exports_the_registry_path_before_the_threads(monkeypatch, tmp_path, capsys):
    mt.set_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SEED_EDIT_USER_LORAS")
    seen = []

    class FakeServer(object):
        port = 8999

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    def start(server):
        seen.append(os.environ.get("SEED_EDIT_USER_LORAS"))
        return threading.Event()

    monkeypatch.setattr(srv, "make_server", lambda port, state, ui_ws, token: FakeServer())
    monkeypatch.setattr(srv, "start_threads", start)
    monkeypatch.setattr(srv, "batch_recovery", lambda state: None)
    monkeypatch.setattr(srv.lib, "startup_recovery", lambda state: None)
    monkeypatch.setattr(srv.signal, "signal", lambda signum, handler: None)
    try:
        assert srv.main(["--port", "8999"]) == 0
    finally:
        while srv._LOCK_FD:
            os.close(srv._LOCK_FD.pop())
    assert seen == [os.path.join(WS, "generated", "seed_loras", "user_loras.json")] == [seedgen.user_loras_path()]
    assert capsys.readouterr().out.endswith("movie-ui: stopped\n")


# --- CL-T32, CL-T33 (CL40-CL43): the page ------------------------------------------------------------------------------

APP_JS_PINS = ("  function customLoraForm(prefix) {", "  function customLoraBody(v) {", '"/api/seed-loras"',
               '"Add custom LoRA"', '"qwen2511-bf16 runs without LoRAs; choose qwen2511-q4 to use a Qwen-Image-Edit-2511 LoRA"',
               '" steps (set by "', 'el("span", {cls: "chip", text: "custom"})', 'askConfirm("Remove custom LoRA "',
               'entry.family + "|" + entry.backend + "|"', "event.stopPropagation()",
               "return [l.id, loraOk(l.id), loraNote(l)];", '" steps (turbo)"',
               'if (!node("-custom")) { node("-qwen-box").appendChild(customLoraForm(prefix)); }',
               '"adding… (hashing a large local file can take minutes)"', '"; the file stays at "',
               'cls: "se-lora-remove", text: "Remove"', '"; trigger: "')


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


def test_cl_t32_the_page_texts():
    static, html, js = _page()
    for text in APP_JS_PINS:
        assert text in js, text
    assert js.count("function customLoraForm(prefix) {") == 1 and js.count("function customLoraBody(v) {") == 1
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\balert\(", r"\bconfirm\(", r"\bprompt\(",
                        r"\beval\(", r"new Function"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


BODY_CASES = [
    ({"source": "hf", "repo": " " + slr.REPO + " ", "file": " ", "path": "/left/over.safetensors", "family": "",
      "trigger": "  ", "scale": "", "steps": ""}, {"repo": slr.REPO}),
    ({"source": "hf", "repo": slr.REPO, "file": " a.safetensors ", "path": "", "family": "qwen2511",
      "trigger": " " + slr.TRIGGER + " ", "scale": "0.7", "steps": "30"},
     {"repo": slr.REPO, "file": "a.safetensors", "family": "qwen2511", "trigger": slr.TRIGGER, "scale": 0.7,
      "steps": 30}),
    ({"source": "local", "repo": "left/over", "file": "x.safetensors", "path": " /a/b.safetensors ", "family": "qwen21",
      "trigger": "", "scale": "1", "steps": ""}, {"path": "/a/b.safetensors", "family": "qwen21", "scale": 1}),
    ({"source": "hf", "repo": "o/n", "file": "", "path": "", "family": "", "trigger": "", "scale": "abc", "steps": "x"},
     {"repo": "o/n", "scale": "abc", "steps": "x"}),
]


def test_cl_t33_the_post_body(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    _static, _html, js = _page()
    start = js.index("  function customLoraBody(v) {")
    body = js[start:js.index("\n  }\n", start) + len("\n  }\n")]
    script = body + "process.stdout.write(JSON.stringify(%s.map(customLoraBody)));\n" % json.dumps(
        [v for v, _want in BODY_CASES])
    path = os.path.join(str(tmp_path), "body.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [want for _v, want in BODY_CASES]


# --- CL-T34 (CL47, SC10): batch forks are unchanged ------------------------------------------------------------------

def test_cl_t34_batch_forks_are_unchanged():
    assert batch.COPY_FILES == {
        "render": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt", "catalog_loras.json",
                   "manifest.json", "seed_edits.json"),
        "stills": ("story.md", "plan.json", "story_checks.json", "story_prompt.txt"),
        "replan": ()}
    assert batch.FIELD_LEVELS == {
        "model": "render", "gemma": "render", "video_loras": "render", "action_loras": "render",
        "frames": "render", "fps": "render", "no_low_ram": "render", "panel_timeout": "render",
        "width": "stills", "height": "stills", "stills_loras": "stills", "location_strength": "stills",
        "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",
        "narrative": "replan", "goal": "replan", "panels": "replan", "length": "replan",
        "seed_upload": "replan", "mode": "replan", "characters": "replan", "locations": "replan",
        "narration": "replan", "story_model": "replan", "story_legacy": "replan", "judge": "replan",
        "auto_lora": "replan"}
    root = subprocess.run(["git", "-C", WS, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if root.returncode != 0:
        pytest.skip("not a git checkout")
    if subprocess.run(["git", "-C", WS, "cat-file", "-e", "20cee82^{commit}"], capture_output=True).returncode:
        pytest.skip("20cee82 is not in this checkout")
    proc = subprocess.run(["git", "-C", WS, "diff", "--quiet", "20cee82", "--", "movie_ui_batch.py"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- Review Focus 5: an older probe gives a clear 409 --------------------------------------------------------------------

def test_cl_review_focus_5_an_older_probe_gives_a_clear_409(env):
    s, ws = env["srv"], env["ws"]
    path = slr.safetensors(os.path.join(env["tmp"], "loras", "real.safetensors"))
    slr.write_registry(env["registry"], [slr.local_entry(path)])
    status, _h, data = mt.api(s, "POST", "/api/seeds/runs", body=_run_body(ws, _upload(s), "qwen2511-q4", ["user-local"]))
    assert (status, data) == (409, {"error": "LoRA real.safetensors is unavailable: not reported by this workspace's "
                                             "bin/seed-edit --probe (it may predate custom LoRAs)"})
    assert not os.path.exists(os.path.join(ws, "generated", "seeds"))
    s.server.refresh_seed_edit()
    cap = s.server.capability_snapshot()["seed_edit"]
    assert cap["ok"] is True and cap["models"]["qwen"]["loras"] == dict(
        [(i, OK) for i in seedgen.BUILTIN_QWEN_LORA_IDS] + [("user-local", {"ok": False, "reason": lib.PROBE_NOT_REPORTED})])
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py 2>&1 | tail -3`
Expected: `10 failed, 1 passed` (`9 failed, 1 passed, 1 skipped` without node): CL-T25 (`assert routes[i + 1:i + 3] == NEW_ROUTES`), CL-T26-CL-T28 and CL-T30 (`404` for `/api/seed-loras`), CL-T29 (the `run.json` prompt is not triggered yet), CL-T31 (`[None]`), CL-T32 (`AssertionError:   function customLoraForm(prefix) {`), CL-T33 (`ValueError: substring not found`) and Review Focus 5 (`AttributeError: ... 'refresh_seed_edit'`) fail; CL-T34 passes (it pins unchanged code).

- [ ] **Step 3: `movie_ui_server.py`: the routes (CL35).** Edit; old:

```python
    ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
```

new:

```python
    ("GET", r"/api/seeds/folders", "h_seed_folders", "/api/seeds/folders"),
    ("POST", r"/api/seed-loras", "h_seed_lora_add", "/api/seed-loras"),
    ("DELETE", r"/api/seed-loras/(user-[a-z0-9-]{1,24})", "h_seed_lora_remove", "/api/seed-loras/user-anything-to-real"),
```

- [ ] **Step 4: `movie_ui_server.py`: `refresh_seed_edit` (CL38).** Edit; old:

```python
    def capability_snapshot(self):
```

new:

```python
    def refresh_seed_edit(self):
        """Custom edit LoRAs spec CL38: re-run only the seed_edit probe against probe_ws (after a custom LoRA add or
        remove) and store it."""
        seed_models, seed_detail = lib.seed_edit_check(self.probe_ws, seedgen.QWEN_MODEL_IDS, seedgen.qwen_lora_ids())
        checked = lib.utc_now()
        with self.cap_lock:
            self.capabilities["seed_edit"] = seedgen.capability(seed_models, seed_detail, checked)

    def capability_snapshot(self):
```

- [ ] **Step 5: `movie_ui_server.py`: the triggered initial `run.json` prompt (CL37).** Edit; old:

```python
                  "prompt": clean["prompt"], "model": clean["model"], "backend": None,
```

new:

```python
                  "prompt": seedgen.trigger_prompt(clean["prompt"], clean["loras"]), "model": clean["model"],
                  "backend": None,
```

(`fields["prompt"]` a few lines below stays `clean["prompt"]`: the tool applies the prefix itself, CL28/CL31, and D2 keeps it single.)

- [ ] **Step 6: `movie_ui_server.py`: the handlers (CL38).** Two Edits.

Old:

```python
        folders.append({"folder": name, "count": count, "path": path})
    return 200, {"root": root, "folders": folders}
```

new:

```python
        folders.append({"folder": name, "count": count, "path": path})
    return 200, {"root": root, "folders": folders}


SEED_LORA_DELETE_BODY = "DELETE /api/seed-loras/<id> takes no body"    # custom edit LoRAs spec Section 3.1


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
        raise ApiError(400, SEED_LORA_DELETE_BODY)
    try:
        entry, kept = registry.remove(groups[0])
    except registry.RegistryError as e:
        raise ApiError(e.status, str(e))
    self.server.refresh_seed_edit()
    return 200, {"removed": entry["id"], "kept": kept, "seed_edit": self.server.capability_snapshot()["seed_edit"]}
```

Old: `MovieUIHandler.h_seed_folders = _h_seed_folders` — new (three lines):

```python
MovieUIHandler.h_seed_folders = _h_seed_folders
MovieUIHandler.h_seed_lora_add = _h_seed_lora_add
MovieUIHandler.h_seed_lora_remove = _h_seed_lora_remove
```

- [ ] **Step 7: `movie_ui_server.py`: the environment (CL39, D8).** Edit; old:

```python
    stop = start_threads(server)
```

new:

```python
    os.environ[seedgen.USER_LORAS_ENV] = seedgen.user_loras_path()   # custom edit LoRAs spec CL39 (D8): every child
    stop = start_threads(server)
```

- [ ] **Step 8: Run the server tests of the new file.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py -k "cl_t25_ or cl_t26_ or cl_t27_ or cl_t28_ or cl_t29_ or cl_t30_ or cl_t31_ or cl_t34_ or review_focus_5_" 2>&1 | tail -3`
Expected: `9 passed`.

- [ ] **Step 9: `static/movie-ui/app.js`: `customLoraBody` and `customLoraForm` (CL40, CL41).** Edit; old:

```javascript
  // Qwen edit models spec QE61: one Qwen edit model + LoRA picker. prefix names its elements:
```

new:

```javascript
  // Custom edit LoRAs spec CL41: the POST /api/seed-loras body of the form's eight values (all strings).
  function customLoraBody(v) {
    const body = v.source === "local" ? {path: v.path.trim()} : {repo: v.repo.trim()};
    if (v.source !== "local" && v.file.trim()) { body.file = v.file.trim(); }
    if (v.family) { body.family = v.family; }
    if (v.trigger.trim()) { body.trigger = v.trigger.trim(); }
    ["scale", "steps"].forEach(function (key) {
      if (v[key].trim()) { body[key] = Number.isFinite(Number(v[key])) ? Number(v[key]) : v[key]; }
    });
    return body;
  }

  // Custom edit LoRAs spec CL40, CL41: the "Add custom LoRA" form of one Qwen picker, <prefix>-custom and its
  // -custom-source, -repo, -file, -path, -family, -trigger, -scale, -steps, -add and -status elements.
  function customLoraForm(prefix) {
    function id(suffix) { return prefix + "-custom-" + suffix; }
    function field(label, input) { return el("label", {}, [label + " ", input]); }
    const source = el("select", {id: id("source")}, [el("option", {value: "hf", text: "Hugging Face repo"}),
      el("option", {value: "local", text: "Local file"})]);
    const repo = el("input", {id: id("repo"), type: "text", size: "40", placeholder: "OWNER/NAME"});
    const file = el("input", {id: id("file"), type: "text", size: "40",
                              placeholder: "only when the repo has several .safetensors files"});
    const path = el("input", {id: id("path"), type: "text", size: "50", placeholder: "/absolute/path/lora.safetensors"});
    const family = el("select", {id: id("family")}, [el("option", {value: "", text: "from the model card"}),
      el("option", {value: "qwen2511", text: "Qwen-Image-Edit-2511"}), el("option", {value: "qwen21", text: "Qwen-Image-2.1"})]);
    const trigger = el("input", {id: id("trigger"), type: "text", size: "40", maxlength: "200"});
    const scale = el("input", {id: id("scale"), type: "number", min: "0", max: "2", step: "0.05", value: "1"});
    const steps = el("input", {id: id("steps"), type: "number", min: "1", max: "100", step: "1", placeholder: "model default"});
    const add = el("button", {id: id("add"), type: "button", text: "Add"});
    const status = el("span", {id: id("status"), cls: "muted"});
    const repoLabel = field("Repo", repo);
    const fileLabel = field("File", file);
    const pathLabel = field("Path", path);
    const form = el("details", {id: prefix + "-custom", cls: "se-custom"}, [el("summary", {text: "Add custom LoRA"}),
      field("Source", source), repoLabel, fileLabel, pathLabel, field("Family", family), field("Trigger", trigger),
      field("Strength", scale), field("Steps", steps), add, status]);
    function sourceShown() {
      const local = source.value === "local";
      show(repoLabel, !local);
      show(fileLabel, !local);
      show(pathLabel, local);
    }
    ["input", "change"].forEach(function (type) {
      form.addEventListener(type, function (event) { event.stopPropagation(); });
    });
    source.addEventListener("change", sourceShown);
    add.addEventListener("click", async function () {
      const v = {source: source.value, repo: repo.value, file: file.value, path: path.value, family: family.value,
                 trigger: trigger.value, scale: scale.value, steps: steps.value};
      add.disabled = true;
      status.textContent = v.source === "local" ? "adding… (hashing a large local file can take minutes)" : "adding…";
      try {
        const res = await api("POST", "/api/seed-loras", customLoraBody(v));
        if (res.status === 201) {
          if (S.host) { S.host.capabilities.seed_edit = res.data.seed_edit; }
          renderBadges();
          status.textContent = ["added " + res.data.lora.id].concat(res.data.notes).join("; ");
        } else {
          status.textContent = (res.data && res.data.error) || "request failed (HTTP " + res.status + ")";
        }
      } finally {
        add.disabled = false;
      }
    });
    sourceShown();
    return form;
  }

  // Qwen edit models spec QE61: one Qwen edit model + LoRA picker. prefix names its elements:
```

- [ ] **Step 10: `static/movie-ui/app.js`: the remove button and the form's mount (CL40, CL42).** Two Edits.

Old:

```javascript
    function enabled(id) { return id === "as-is" || (Boolean(seedQwenEntry(id)) && !(probe(id) && probe(id).ok === false)); }
```

new:

```javascript
    function enabled(id) { return id === "as-is" || (Boolean(seedQwenEntry(id)) && !(probe(id) && probe(id).ok === false)); }
    // Custom edit LoRAs spec CL42: the Remove button of a custom LoRA's row.
    function removeButton(l) {
      const button = el("button", {type: "button", cls: "se-lora-remove", text: "Remove"});
      button.addEventListener("click", async function () {
        if (!(await askConfirm("Remove custom LoRA " + l.label + " (" + l.id + ") from the registry? Its file is not deleted."))) { return; }
        const res = await api("DELETE", "/api/seed-loras/" + enc(l.id));
        const status = node("-custom-status");
        if (res.status === 200) {
          if (S.host) { S.host.capabilities.seed_edit = res.data.seed_edit; }
          renderBadges();
          status.textContent = "removed " + res.data.removed + (res.data.kept ? "; the file stays at " + res.data.kept : "");
        } else {
          status.textContent = (res.data && res.data.error) || "request failed (HTTP " + res.status + ")";
        }
      });
      return button;
    }
```

Old:

```javascript
        node("-steps").textContent = "checking models…";
        return;
      }
```

new:

```javascript
        node("-steps").textContent = "checking models…";
        return;
      }
      if (!node("-custom")) { node("-qwen-box").appendChild(customLoraForm(prefix)); }
```

- [ ] **Step 11: `static/movie-ui/app.js`: the notes, the rows and the steps line (CL42, CL43).** Edit; old (from `function loraNote(l) {` through the steps line):

```javascript
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
```

new:

```javascript
      function loraNote(l) {
        if (loraOk(l.id)) {
          return l.license + (l.steps ? "; " + l.steps + " steps" + (l.scheduler ? ", scheduler " + l.scheduler : "") : "")
            + (l.trigger ? "; trigger: " + l.trigger : "");
        }
        const found = loraProbe(l.id);
        return "unavailable — " + (found ? found.reason : ((cap.ok === false && cap.reason) || "probing"));
      }
      const key = entry.family + "|" + entry.backend + "|" + JSON.stringify(loras.map(function (l) { return [l.id, loraOk(l.id), loraNote(l)]; }));
      if (key !== p.key) {
        p.key = key;
        const box = clear(node("-loras"));
        if (entry.family === "qwen2511") {
          box.appendChild(el("span", {cls: "muted", text: "Lightning 8-step LoRA built in (not selectable)"}));
        }
        if (entry.backend === "diffusers" && loras.length) {
          box.appendChild(el("span", {cls: "muted", text: "qwen2511-bf16 runs without LoRAs; choose qwen2511-q4 to use a Qwen-Image-Edit-2511 LoRA"}));
        }
        else {
          loras.forEach(function (l) {
            const ok = loraOk(l.id);
            if (!state.loras[l.id]) { state.loras[l.id] = {checked: false, scale: String(l.default_scale)}; }
            const saved = state.loras[l.id];
            const checkbox = el("input", {type: "checkbox", id: prefix + "-lora-" + l.id});
            checkbox.checked = saved.checked && ok;
            checkbox.disabled = !ok;
            const scale = el("input", {type: "number", id: prefix + "-lora-scale-" + l.id, min: "0", max: "2", step: "0.05", value: saved.scale});
            scale.disabled = !ok;
            const note = el("span", {cls: "muted", id: prefix + "-lora-note-" + l.id, text: loraNote(l)});
            const row = el("div", {cls: "se-lora", data: {lora: l.id}}, [
              el("label", {}, [checkbox, " " + l.label].concat(l.user ? [" ", el("span", {cls: "chip", text: "custom"})] : [])),
              el("label", {}, ["strength ", scale]), note]);
            if (l.user) { row.appendChild(removeButton(l)); }
            box.appendChild(row);
          });
        }
      }
      const turbo = loras.filter(function (l) {
        const box = node("-lora-" + l.id);
        return l.steps && box && !box.disabled && box.checked;
      })[0];
      node("-steps").textContent = turbo ? turbo.steps + (turbo.user ? " steps (set by " + turbo.label + ")" : " steps (turbo)")
        : entry.steps + " steps" + (entry.family === "qwen2511" ? " (Lightning)" : "");
```

- [ ] **Step 12: E6, the route counts.** Edits; old:

```python
    assert len(srv.ROUTES) == 64
```

new:

```python
    assert len(srv.ROUTES) == 66
```

in `tests/test_movie_ui_http.py` (once), `tests/test_location_ui.py` (once), `tests/test_movie_ui_seedgen.py` (once) and `tests/test_movie_ui_seedfolder.py` (`replace_all: true`; exactly two occurrences). Then:

Run: `grep -rn "len(srv.ROUTES) == 6" tests/ | sort`
Expected: exactly five lines, each ending `== 66`: `tests/test_location_ui.py:66`, `tests/test_movie_ui_http.py:44`, `tests/test_movie_ui_seedfolder.py:923`, `tests/test_movie_ui_seedfolder.py:960`, `tests/test_movie_ui_seedgen.py:627`.

- [ ] **Step 13: CL-T24 covers the new test file (SC8).** Two Edits to `tests/test_seed_lora_registry.py`.

Old:

```python
            "bin/seed-edit-setup", "movie_ui_lib.py", "movie_ui_server.py", "tests/test_seed_lora_registry.py",
            "tests/conftest.py")
SCANNED = ("seed_lora_registry.py", "bin/seed-edit-lora", "tests/test_seed_lora_registry.py")
```

new:

```python
            "bin/seed-edit-setup", "movie_ui_lib.py", "movie_ui_server.py", "tests/test_seed_lora_registry.py",
            "tests/conftest.py", "tests/test_movie_ui_seed_loras.py")
SCANNED = ("seed_lora_registry.py", "bin/seed-edit-lora", "tests/test_seed_lora_registry.py",
           "tests/test_movie_ui_seed_loras.py")
```

(That is one Edit; the old text spans the three lines.)

- [ ] **Step 14: Run the new tests and the suites they touch.**

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py tests/test_seed_lora_registry.py 2>&1 | tail -3`
Expected: `76 passed` (11 here, 65 in the registry file), or fewer passed with `skipped` only for the node tests and the 3.9 compile where those interpreters are absent.

Run: `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_builder.py 2>&1 | tail -1`
Expected: no `failed`.

Run: `node --check static/movie-ui/app.js && echo "app.js ok"` — Expected: `app.js ok`.

- [ ] **Step 15: Verify: the compile check, the pinned files and the untouched page files.**

Run the compile check with `FILES` = `movie_ui_server.py tests/test_movie_ui_seed_loras.py tests/test_seed_lora_registry.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py` — Expected: `compiled 7` twice.

Run the pinned-file check of "Global Constraints" — Expected: `pinned files unchanged` and no `failed`.

Run: `git diff --stat 20cee82 -- static/movie-ui/index.html static/movie-ui/app.css movie_ui_batch.py | tail -1` — Expected: no output.

- [ ] **Step 16: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git add movie_ui_server.py static/movie-ui/app.js tests/test_movie_ui_seed_loras.py tests/test_seed_lora_registry.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py
git diff --cached --name-only | wc -l          # expected: 8
git commit -m "custom edit LoRAs: POST/DELETE /api/seed-loras, the capability refresh and the Add custom LoRA form (Task 3)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 17: The gate (controller).** Run `zsh $D/gate-run.sh 3`. Expected: `lost 0 (listed 0, unexpected 0); new tests 76, not passing 0; baseline failures still failing 2 of 2`, `GATE PASS`, `3 passed`, `ATK2 OK lines unchanged`. Then an Opus design review of the Task 3 commit against CL35, CL37-CL44 and E6.

---
## Verification (controller, after Task 3's gate)

- [ ] **V1: The full gate against the baseline (CLK5).** Task 3's gate (Step 17) is the final full run: `lost 0 (listed 0, unexpected 0)`, `not passing 0`, `baseline failures still failing 2 of 2`, `GATE PASS`, the flake rerun `3 passed`, and `ATK2 OK lines unchanged`. If a review-fix commit lands after that gate, rerun `zsh $D/gate-run.sh 3` and require the same result.

- [ ] **V2: The KPI greps and the pinned files (CLK3, CLK4, CLK6, CLK7).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git grep -nwE 'QWEN_LORAS|QWEN_LORA_IDS' -- . ':(exclude)docs' | wc -l          # expected: 0 (CLK3, SC2)
git grep --untracked -c HTTPSConnection -- . ':(exclude)docs'                     # expected: seed_lora_registry.py:1 (CLK4, SC3)
git ls-tree HEAD bin/seed-edit-lora | cut -c1-6                                   # expected: 100755
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' movie_ui_seedgen.py seed_lora_registry.py qwen_edit.py bin/seed-edit bin/seed-edit-setup bin/seed-edit-lora movie_ui_lib.py movie_ui_server.py tests/conftest.py tests/test_seed_lora_registry.py tests/test_movie_ui_seed_loras.py; done   # expected: compiled 11, twice (CLK6)
```

Then the pinned-file check of "Global Constraints" (CLK7, CL50): `pinned files unchanged`, and `tests/test_movie_ui_builder.py` with no `failed` (`test_mut26` still passes at BASELINE `ca958ca…`; no re-baseline commit exists or is needed).

- [ ] **V3: The changed files are exactly the deliverables (0.3) and the E1-E7 edits.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git diff --name-only 76742e8 HEAD -- . ':(exclude)docs' ':(exclude)tests'
git diff --name-only 76742e8 HEAD -- tests/
git diff --name-only 76742e8 HEAD -- docs/
git diff --stat 20cee82 HEAD -- seed_edit_mflux_child.py location_dataset.py movie_ui_batch.py movie_ui_seedfolder.py content_safety.py static/movie-ui/index.html static/movie-ui/app.css | tail -1
```

Expected, in order (paths carry the `qwen-agent-workspace/` prefix): exactly the nine code paths `bin/seed-edit`, `bin/seed-edit-lora`, `bin/seed-edit-setup`, `movie_ui_lib.py`, `movie_ui_seedgen.py`, `movie_ui_server.py`, `qwen_edit.py`, `seed_lora_registry.py`, `static/movie-ui/app.js`; exactly the fifteen test paths `tests/conftest.py`, `tests/test_location_ui.py`, `tests/test_ltx_movie_cast_refs.py`, `tests/test_ltx_movie_extra_refs.py`, `tests/test_ltx_movie_seed_context.py`, `tests/test_ltx_movie_seed_edit.py`, `tests/test_ltx_movie_shots_seed.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_qwen_edit.py`, `tests/test_movie_ui_seed_loras.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_seedgen.py`, `tests/test_qwen_edit.py`, `tests/test_seed_edit_tool.py`, `tests/test_seed_lora_registry.py`; exactly `docs/superpowers/plans/2026-11-17-custom-edit-loras.md`; no output for the untouched files. Then read `git diff 76742e8 HEAD -- tests/ ':(exclude)tests/test_seed_lora_registry.py' ':(exclude)tests/test_movie_ui_seed_loras.py'` and confirm every hunk is one of E1 (the `seed_lora_isolation` fixture), E2 (nine `startswith` lines), E3 (five `seedgen` names), E4 (four edits), E5 (one line) or E6 (five `== 66` lines): E7 allows nothing else.

- [ ] **V4: The secret scan of the code diff (public repository).**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/cl-wt/qwen-agent-workspace
git diff 76742e8 HEAD -- . ':(exclude)docs' | grep -nE '^\+.*(hf_[A-Za-z0-9]{20,}|Authorization|/Users/|BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key *=)' | head
```

Expected: no output (CL49). A hit stops everything until it is fixed.

- [ ] **V5: The whole-branch review and the hand-off.** An Opus design review of `76742e8..HEAD` against this spec and plan (every CL requirement, the five Review Focus lines, the SC rulings). Then the user runs the live checks CL-LV0-CL-LV9 on macstudio (the assistant never accesses macstudio) and decides push and merge; nothing is pushed before the user's go.

---

## Self-review

**1. Spec coverage.** Every requirement has a task step:

| Requirement | Where |
|---|---|
| CL1, CL2-CL8, CL10, CL11 | Task 1 Steps 7, 8, 10 (`movie_ui_seedgen.py`) |
| CL9, CL13 | Task 1 Step 9 |
| CL12 | Task 1 Step 11 |
| CL14 | Task 1 Step 6 |
| CL15-CL18, CL20-CL22a | Task 2 Step 3 |
| CL19, CL22b | Task 1 Step 5 (kept by Task 2 Step 3) |
| CL23, CL24 | Task 2 Step 4 |
| CL25, CL26, CL27, CL28, CL29 | Task 1 Steps 14, 15, 16, 17, 13 |
| CL30, CL31 | Task 1 Step 19 |
| CL32, CL33 | Task 1 Steps 21-23 |
| CL34 | Task 1 Step 24 |
| CL35, CL37, CL38, CL39 | Task 3 Steps 3, 5, 4 and 6, 7 |
| CL36 | Task 1 Step 25 (SC1) |
| CL40-CL43 | Task 3 Steps 9-11 |
| CL44 | Task 3 touches only `customLoraBody`, `customLoraForm`, `removeButton`, the mount line, `loraNote`, the rows and the steps line (Steps 9-11); V3 and the review check nothing else changed |
| CL45, CL46 | No code (record_settings and the CL46 refusals come from CL5-CL10, CL26, CL27); pinned by CL-T19, CL-T30, Review Focus 1 |
| CL47 | No code; CL-T34 |
| CL48, CL49, CL51 | Global Constraints and house rules; CL-T24, CL-T6, V2, V4 |
| CL50 | The pinned-file check in every task and V2 |
| CL52 | Task 1 Steps 3-4 (E1, E2) |
| E1-E5, E6, E7 | Task 1 Steps 3, 4, 26-28; Task 3 Step 12; V3 |

Tests: CL-T1-CL-T4, CL-T11, CL-T14-CL-T21, CL-T23 (Task 1 Step 1); CL-T5-CL-T10, CL-T12, CL-T13, CL-T22, CL-T24 (Task 2 Step 1, CL-T24's tuples extended in Task 3 Step 13); CL-T25-CL-T34 (Task 3 Step 1). KPIs: CLK1 (CL-T5's CLI run), CLK2 (CL-T15, CL-T16: the content safety prompt is asserted on the fake that `content_safety.log` is written from), CLK3, CLK4, CLK6, CLK7 (V2), CLK5 (the gates), CLK8 (the user's live checks). Plan step 0 is Step 0.3/0.4.

**2. Placeholder scan.** No "TBD", "TODO", "similar to", or step without its code: every Edit has its old and new text, every new file its full content, every run its command and expected output.

**3. Type and name consistency.** Checked across tasks: `seedgen._plain_text` (Task 1 Step 10) is what Task 2's `check_request` calls; `seedgen.user_loras_problem`, `user_loras_path`, `valid_trigger`, `BUILTIN_QWEN_LORAS`/`_IDS`, `USER_LORAS_SCHEMA`, `USER_LORAS_ENV` are spelled the same in Tasks 1-3; `seed_lora_registry.local_problem`/`downloaded_problem`/`lora_pair_count` keep their Task 1 signatures in Task 2's rewrite; `registry.FIELDS`, `M_SCALE`, `M_STEPS` (Task 2) are what `bin/seed-edit-lora` reads; `registry.add(body, None)`, `registry.remove(groups[0])`, `RegistryError.status` (Task 2) are what the Task 3 handlers call; `lib.PROBE_NOT_REPORTED` (Task 1) is what Task 3's tests assert; the test helpers `REPO`, `FILE`, `SHA`, `TRIGGER`, `pairs`, `st_bytes`, `safetensors`, `hf_entry`, `local_entry`, `write_registry` (Task 1) and `INFO`, `fake_fetch`, `load_cli`, `FIELDS_TEXT`, `SCALE_TEXT`, `STEPS_TEXT`, `ONE_SOURCE` (Task 2) are the names Task 3's `slr.` uses.

**4. Review Focus.** Five lines, each pinned in its owning task: 1 in Task 1, 2-4 in Task 2, 5 in Task 3. Inputs considered and found covered by CL-T rows instead: an invalid or hand-edited registry file (CL-T3), a trigger already in the prompt in another case (CL-T15), duplicate content (CL-T5, CL-T10), concurrent adds (CL-T22), HF outages and TLS (CL-T6), non-ASCII triggers (CL-T4), a removed LoRA in an old record (CL-T19, CL-T30), the bf16 model (CL-T18, CL-T29).

---

## Execution handoff

Recommended: **subagent-driven** (superpowers:subagent-driven-development): three tasks whose later tasks consume the earlier ones' exact names, a public repository, and a change to the run path of every existing Qwen edit, so a fresh Sonnet `code-executor` per task with an Opus `design-reviewer` gate after each (and the controller's full-suite gate) is worth its cost.
