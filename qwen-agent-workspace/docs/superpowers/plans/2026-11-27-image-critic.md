# Image Critic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An opt-in image critic: after each Qwen seed-edit batch, the local 27B VLM scores every ok image for broken bodies; only the failures are re-edited with derived seeds (at most `--critic-rounds` more times); the best-scored attempt is kept at each output path and flagged when none passes. It covers the Seeds-tab generator (`bin/seed-edit --critic`) and the shots seed edit (`bin/ltx-movie --shots --seed-image ... --critic`), with a Critic checkbox in the movie UI's Seeds and Compose forms and a calibration CLI (`bin/image-critic score`). Flag off is byte-identical.

**Architecture:**
- One new stdlib-only module, `image_critic.py`: `critic_seed`, `parse_verdict`, `judge_image`, `VLMSession` (start the VLM around judging, stop it for each Qwen redo, return bin/story-server to the state it was found in) and `edit_with_critic(qe, ...)`, which wraps the caller's `qwen_edit.run_jobs`. It reaches `character_dataset` only through `image_critic._cd()`.
- `bin/seed-edit` imports `image_critic` inside `run_qwen`, only on the critic path. `bin/ltx-movie` loads `image_critic.py` by path (`_image_critic()`), only with `--critic`. `qwen_edit.py` and `character_dataset.py` are not changed.
- The movie UI only adds a field, a flag, argv, validation, a log regex and view keys. It runs `bin/*` as subprocesses and never imports or names `image_critic`.

**Tech Stack:**
- `python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (3.13.0, pytest 8.3.4, PIL 12.3.0), run as `python3 -m pytest -q -p no:cacheprovider <files>` from `WS`.
- `/usr/bin/python3` (3.9.6) for the 3.9 compile checks.
- `node` at `/opt/homebrew/bin/node` for `node --check` and the ICT23 composeFields run.
- Stdlib and PIL (through `character_dataset`, imported lazily). No new dependency.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-27-image-critic-design.md`, commit `9fd68c1` on branch `image-critic` (base `0074122`, Merge PR #32). The user approved it with the open-question defaults kept:
- Q1: reused shots panels are not judged.
- Q2: `JUDGE_WITH_SEED = False`.
- Q3: `VLM_MIN_AVAIL_GIB = 28.0`.
- Q4: no rounds input in the UI; the UI never sends `--critic-rounds`.
- Q5: attempt files are kept under `critic/`.
- Q6: `--redo` reproduces the same pictures; documented only.

Every Edit below is located by its old text, never by a line number. Line numbers in the Files lists are at `0074122`, for orientation only.

**Planning replay (done while writing this plan).** Every new file and Edit below was applied by script to scratch clones of `9fd68c1` outside the worktree (`$S/ic-replay`, `$S/ic-t`, `$S/ic-c3`) and run. Then this rendered plan itself was applied in document order (every Create, Edit, chmod, script and commit) to a fresh clone, `$S/ic-v`: all 70 Edits matched exactly once, the five commits held 5, 4, 1, 17 and 1 files, and the tree equalled `$S/ic-t` apart from the two shas.

| Stage | Result |
|---|---|
| Task 1 red | `1 error` (collection: `No module named 'image_critic'`) |
| Task 1 after `image_critic.py` | `2 failed, 18 passed` |
| Task 1 green | `20 passed`; the Task 1 verify set gives `45 passed` |
| Task 2 seed-edit red / green | `9 failed, 1 passed, 93 deselected` / `10 passed, 93 deselected` |
| Task 2 ltx-movie red / green | `5 failed, 20 deselected` / `25 passed` (the whole file) |
| Task 2 relevant set at C2 | `1 failed, 386 passed` (the failure is `test_mut26`, by design) |
| Task 3 | `test_mut26` `1 failed` before, `12 passed` (the whole builder file) after |
| Full suite at base / C3 / C4 / C5 | base `28 failed, 2943 passed, 2 skipped`; C3 `28 failed, 2978 passed, 2 skipped` (exactly the base list); C4 `29 failed, 2983 passed, 2 skipped` (the base list plus `test_cl_t34`, by design); C5 `29 failed, 2983 passed, 2 skipped` (`test_cl_t34` green; the extra failure was `tests/test_fleet_vision.py::test_vt20_harness_delegates_images_to_the_vision_peer`, a `qwen-agentd` startup race in a file no task touches, and the file gave `13 passed` on each of three reruns) |
| Task 4 red, after lib, after seedgen/server/batch, after the fixture, green | `5 failed, 1 passed`; `4 failed, 2 passed`; `2 failed, 4 passed`; `1 failed, 5 passed`; `6 passed` |
| Task 4 table pins before / after | `9 failed` / `9 passed`; the pin verify set `29 passed` |
| Task 4 movie-UI set at C4 | `27 failed, 587 passed`; the only failure outside the base list is `test_cl_t34`, by design |
| Task 5 | `test_cl_t34` `1 failed` before, `14 passed` (the whole file) after |

The base failures are all environmental and fail the same way at `0074122`: 25 `tests/test_movie_ui_http.py` batch-fork tests and `tests/test_vlm_lifecycle.py::test_bt30_fork_jobs_record_their_vlm_policy` (the 20 GiB batch-fork disk reserve; 14.7 GiB were free), `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. `/usr/bin/python3` and 3.13 both compile every changed Python file.

## Global Constraints

Exact values from the spec (section in brackets). Every task's requirements include this section.

**Constants** [2.1]
- `PASS_SCORE = 7` (a score `>= PASS_SCORE` passes), `DEFAULT_ROUNDS = 2`, `MAX_ROUNDS = 4`, `JUDGE_WITH_SEED = False`.
- `JUDGE_MAX_SIDE = 1024`, `JUDGE_ATTEMPTS = 2`, `JUDGE_MAX_TOKENS = 400`, `DEFECTS_MAX = 8`, `DEFECT_CHARS = 60`, `REASON_CHARS = 300`.
- `VLM_MIN_AVAIL_GIB = 28.0`: the critic waits (`character_dataset.wait_for_avail(28.0, AVAIL_WAIT_S = 600)`) for 28 GiB available before it starts the VLM.
- `SEED_MAX = 2147483647`, `CRITIC_DIR = "critic"`, `THINK_RE = re.compile(r"(?s)<think>.*?</think>")`, `LINE_STATES = {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}`.
- [2.2] `critic_seed(seed, round_n, n) = int(sha256("image-critic:%d:%d:%d" % (seed, round_n, n))[:8], 16) & SEED_MAX`, always from the job's requested seed.
- The prompts `JUDGE_PROMPT`, `SEED_PREFACE`, `JUDGE_SEED_PROMPT = SEED_PREFACE + JUDGE_PROMPT` and `JUDGE_RETRY` are the spec's exact text; ICT1 pins all four.

**Flags**
- `bin/seed-edit`: `--critic` (store_true), `--critic-rounds N` (a string `[0-9]+` with value `<= 4`). Qwen models only.
- `bin/ltx-movie`: `--critic` (dest `critic`), `--critic-rounds N` (dest `critic_rounds`, `type=int`, default None, 0 to 4). Only with `--shots`, `--seed-image` and a Qwen `--seed-edit-model` ID; never with `--seed-context`.
- `bin/image-critic score FILE [FILE ...] [--seed PATH] [--pass-score N] [--json]`, mode 100755. Exit 0 every file judged, 1 at least one not judged, 2 a usage error, a missing file or the VLM not serving.
- movie UI: the Compose field `critic` (bool, `DEFAULT_FIELDS` default `False`, right after `extra_refs`), `FIELD_FLAGS` entry `("critic", ("--critic",))` right before `extra_refs`; the Seeds request key `critic` (bool, qwen only). The UI never sends `--critic-rounds` (Q4).

**Log lines** [2.6] (`n/N` is the job number and `total`; `D` is `"; ".join(defects)` or `no defect named`; `A` is `round + 1`; `K` is the attempt count)
- `critic n/N: ok (score S, attempt A)` · `critic n/N: redo (score S: D)` · `critic n/N: flagged (best score B of K attempts: D(best))` · `critic n/N: unjudged (<reason>)`.
- Every other critic line starts `critic: ` (with a colon) and never matches `CRITIC_RE = re.compile(r"^critic (\d+)/(\d+): (ok|redo|flagged|unjudged)(?: \((.*)\))?$")`.

**Records** [2.4.4, 2.5]
- The block, keys in this order: `{"status": "passed"|"flagged"|"unjudged", "score", "defects", "reason", "seed_used", "pass_score": 7, "attempts": [{"round", "seed", "score", "defects", "note"}]}`.
- `bin/seed-edit` `run.json` (critic only): top-level `"critic": {"rounds": <rounds>, "pass_score": 7}`; each candidate gains `"critic": <block>`; candidate `seed` stays `seed + i`.
- `bin/ltx-movie` `seed_edits.json` (critic only): each judged panel's entry gains `"critic": <block>`; `seed` stays `args.image_seed`; `still_sha256` always describes the current `images/panel_NN.png`; the reuse key is unchanged.
- Attempt files: `<work_dir>/critic/<stem>.r<k>.png`, stages `<work_dir>/critic/<stem>.r<k>.pending.png`.

**Messages** [3] (byte-exact; the code blocks below carry them)
- `parse_verdict`: `the reply has no text` · `score must be an integer, got <repr>` · `score must be 1-10, got <n>` · `missing key: defects` · `defects must be a list of strings`.
- `judge_image`: `cannot read <path>: <Type>: <e>` · `VLM request failed: <Type>: <e>` · `unparseable: <error>`.
- `VLMSession`: `the story server is <state>; the image critic needs it stopped or serving mlx-vision` · `less than 28 GiB available for the VLM after waiting 600 s` · `bin/story-server-restore mlx-vision --wait exited <rc>` · `the VLM did not answer within 600 s` · `bin/story-server stop exited <rc>` · stdout `critic: starting the VLM (bin/story-server-restore mlx-vision --wait)` · `critic: stopping the VLM for the Qwen redo` · `critic: stopping the VLM (it was stopped before the critic started)` · `critic: restarting the VLM in the background (it was serving before the critic started)` · stderr `critic: interrupted; stopping the VLM in its own session` · `critic: warning: bin/story-server stop exited <rc>; the VLM may still hold its memory` · `critic: warning: restoring the VLM failed: <e>`.
- `edit_with_critic`: `critic: not run; the <noun> batch failed` · `critic: not run; no <noun> produced an image` · `critic: judging <k> <noun(s)> with the VLM (round <r>)` · `critic: redo round <r> of <R>: <noun(s)> <list> with new seeds` · `critic: redo round <r> of <R> not run: <reason>` · `critic: redo round <r> failed: <failure>; keeping the best attempts` · `critic: done: <p> passed, <f> flagged, <u> unjudged; <k> redo round(s) run` · notes `not judged: <reason>`, `blocked by the content screen`, `the edit failed`.
- `bin/image-critic`: `Error: --pass-score must be an integer from 1 to 10` · `Error: <p> is not a file` · `Error: the VLM is not serving at <url>; start it with bin/story-server mlx-vision`.
- `bin/seed-edit`: `--critic-rounds needs --critic` · `--critic is only for --model qwen` · `--critic-rounds must be an integer from 0 to 4` · `--probe takes no other options` (existing).
- `bin/ltx-movie`: `Error: --critic-rounds needs --critic` · `Error: --critic-rounds must be an integer from 0 to 4` · `Error: --critic cannot be combined with --seed-context: a redone still would change every later panel's context picture` · `Error: --critic needs --shots with --seed-image and a Qwen --seed-edit-model ID: the image critic judges the shots seed edits only` · `Error: --critic needs <path>, which this workspace does not have`.
- movie UI: `critic must be true or false` (V1 and Seeds) · `the image critic needs shots mode with a seed image and a Qwen seed edit model` · `critic is only for qwen`.

**Commit order** [Plan; binding]
- C1 (Task 1): `image_critic.py`, `bin/image-critic`, `tests/test_image_critic.py`, the `NEW_PY` and QET11 pins.
- C2 (Task 2): `bin/seed-edit`, `bin/ltx-movie` and their tests. At C2 `test_mut26` fails by design; every other test passes.
- C3 (Task 3): test-only; `tests/test_movie_ui_builder.py` `BASELINE` becomes the full sha of C2. Message: `tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the image-critic hooks commit`.
- C4 (Task 4): the movie UI and its table pins. It touches no `PIPELINE_FILES` member, so `test_mut26` needs no re-baseline. It does change `movie_ui_batch.py`, which `tests/test_movie_ui_seed_loras.py::test_cl_t34_batch_forks_are_unchanged` pins to commit `20cee82` with its own `git diff --quiet`, so at C4 `test_cl_t34` fails by design (R10).
- C5 (Task 5): test-only; `test_cl_t34`'s `FIELD_LEVELS` literal gains `critic` and its pin moves from `20cee82` to the full sha of C4. Message: `tests/test_movie_ui_seed_loras.py: test_cl_t34 batch pin moves to the image-critic movie UI commit`.
- **The BASELINE rule.** `bin/ltx-movie` is a `PIPELINE_FILES` member pinned by `test_mut26`. The BASELINE commit comes immediately after the commit that touches it (C3 right after C2). No later commit touches `bin/ltx-movie` without its own BASELINE commit right after it (message pattern `tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the image-critic <what> commit`), review fixes included. Never amend, rebase or squash C2 once C3 exists.
- **The batch-pin rule (R10).** The same holds for `movie_ui_batch.py` and `test_cl_t34`: C5 comes immediately after C4, and any later commit that changes `movie_ui_batch.py` is followed at once by its own `test_cl_t34` re-pin commit. Never amend, rebase or squash C4 once C5 exists.
- The PR merges with a merge commit (as PR #32 did), never squash or rebase, so the C2 and C4 shas survive.

**Safety and scope**
- `movie_ui_server.py`, `movie_ui_lib.py`, `movie_ui_seedgen.py` and `movie_ui_batch.py` never import or name `image_critic` (ICT24). `job_vlm`, `vlm_preflight`, `vlm_postflight` and `recovery_restore` are unchanged; `tests/test_vlm_lifecycle.py` passes unedited.
- `qwen_edit.py`, `character_dataset.py` and `location_dataset.py` are not changed.
- [F12] `image_critic.py`, `bin/image-critic`, `tests/test_image_critic.py` and `tests/test_movie_ui_critic.py` join `NEW_PY`, so `test_mut25` forbids `urllib`, `load_module(`, `shell=True`, `match` statements and `X | None` annotations in them, docstrings and stubs included. Tests use `OSError(...)` for transport failures.
- [2.11] `index.html` and `app.js` gain no `https?://`, `\son[a-z]+=`, `style=`, `\bconfirm\(`, `innerHTML`, `\balert\(`, `\bprompt\(`, `\beval\(`, `new Function`. All new text goes in through `el`'s `text` (textContent). `app.css` is unchanged.
- Python 3.9: every added line compiles on `/usr/bin/python3` 3.9.6 (`nonlocal` is fine; no `match`, no `X | Y`, `%` formatting).
- [Where] Nobody accesses macstudio. Live checks ICL1-ICL7 are the user's to run.

**House rules**
- **Checkout.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`, git root = `$S/ic-wt`, `WS` = `$S/ic-wt/qwen-agent-workspace`, branch `image-critic`. Shell variables do not persist between commands (and the shell is zsh, which does not word-split unquoted variables), so every command block below starts with its own `cd` and spells its file list out.
- **Git.** Never `git stash`, `reset`, `checkout`, `switch`, `amend`, `rebase` or `push`. Stage only the paths a task names, and check `git diff --cached --name-only` (paths carry the `qwen-agent-workspace/` prefix) before committing. Commits pass each paragraph as its own `-m`; the last `-m` is `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **Editing.** Change tracked files only with the Edit tool, or the Write tool for a new file. The two exceptions are Task 3 Step 3 and Task 5 Step 4, whose shas are only known at run time: they run the scripts given there. An Edit's old text is whole lines and occurs exactly once. If it does not match, stop and report. Code blocks are copied byte for byte (they use four-backtick fences because one test string contains three backticks).
- **Existing assertions.** No existing assertion is edited except in the pin steps of Tasks 1, 3, 4 and 5, which name every one. If any other existing test newly fails, stop and report.

## Plan rulings (where the spec was ambiguous or collided with a pin)

- **R1 (ICT8b).** The spec's ICT8(b) puts the `KeyboardInterrupt` in the redo `run_jobs` and expects a detached `Popen` stop. At that point `down()` has already stopped the VLM synchronously (K3) and cleared `maybe_up`, so nothing is left to stop. The plan splits ICT8(b): (b1) the interrupt in the redo `run_jobs` (pending files removed, `output_path` holds round 0, no `Popen`, the only stop is the pre-redo one); (b2) the interrupt in the round-1 `vlm_call`, after the VLM restarted (exactly one detached `Popen([STORY_SERVER, "stop"], ..., start_new_session=True)`, no synchronous stop after it).
- **R2 (`bin/image-critic`).** Every `Error:` line goes to stderr (the spec says so for `--pass-score` only). A `--json` row of an unjudged file has `"score": null, "defects": [], "reason": null`.
- **R3 (redo memory floor).** 2.4.2 step 2 computes `refs` from `redo_jobs`, which step 4 builds. The plan computes it from the caller's jobs of the active `n` (the same `sources`), before building `redo_jobs`.
- **R4 (Seeds checkbox).** `QWEN_BOX` (QET38 and SQT22) pins the whole `#se-qwen-box` block, so the Seeds label goes right after the box's closing `</div>`, with `hidden`, and `updateSeedButtons` shows it on the box's own condition (`model === "qwen"`). It is visible exactly when `#se-qwen-box` is.
- **R5 (Compose checkbox).** SET20 and SZ's `BUTTONS_BOX` pin the three lines from `const zimageSeed = ...` to `const seedEditReason = ...`, so the `show($("#c-critic-box"), ...)` line goes right after `$("#c-sq-reason").textContent = seedEditReason;`. SZ's `FIELDS_AS_IS` pins `}` followed by `return out;` in `composeFields`, so `out.critic = ...` goes right before the `// Shots Z-Image engine spec ZE13` comment, with the extra term `S.composeEngine !== "zimage"`: before that block the Z-Image engine has not yet turned `seed_edit_model` into `as-is`. The value sent is the spec's.
- **R6 (help fixture and extra count pins).** The stub workspace's `bin/ltx-movie --help` prints `tests/fixtures/movie_ui/ltx-movie-help-current.txt`, so V1 rule 18 and MU14's `all(supported.values())` need `--critic` there. The fixture gains `--critic` and `--critic-rounds` (as `0d36482` added `--extra-ref`), and these pins fail only because the tables gained the entry, so they are updated under 6.3's last Task-3 bullet: `tests/test_movie_ui_qwen_edit.py` `(28, 5, 33)` and `batch.GROUPS`; `tests/test_movie_ui_extra_refs.py` `batch.GROUPS[1]`; `tests/test_movie_ui_builder.py` MUT3's `current - old` set and `len(supported) == 32`; `tests/test_movie_ui_http.py` MU14's `len(...) == 32`.
- **R7 (comment chain).** `(extra-refs review fix).` becomes `(extra-refs review fix), then to <C2 sha> (image critic hooks).`
- **R8 (task numbers).** The spec's Task 2 (C2 and C3) is this plan's Task 2 (C2) and Task 3 (C3); the spec's Task 3 (C4) is Task 4.
- **R9 (seed-edit `run_qwen`).** The flag-off body is kept under `if not opts["critic"]:` with its continuation lines re-indented by four spaces; the call is otherwise unchanged.
- **R10 (a second git pin the spec missed).** `tests/test_movie_ui_seed_loras.py::test_cl_t34_batch_forks_are_unchanged` asserts both a `batch.FIELD_LEVELS` literal and `git diff --quiet 20cee82 -- movie_ui_batch.py`. Spec 2.10.4 must change `movie_ui_batch.py` (without it `test_bt1` fails, because `DEFAULT_FIELDS` gains `critic`). The plan therefore treats it like `test_mut26`: it fails by design at C4, and a test-only commit C5, right after C4, adds `"critic": "stills"` to its literal and moves its three `20cee82` references to C4's full sha. C1-C4 keep the spec's order; C5 is appended.

## Review Focus

The spec's Section 8 names the five edge cases most likely to bite. Each is pinned by a test in the task that owns its code; the three marked *new* are this plan's additions to the spec's ICT list.

1. **Zero failures.** One VLM start, one judge pass, one stop; no `wait_for_memory`, no redo, no `r0` copy. Test: `test_ict4_all_pass_one_start_one_stop` asserts the exact call log and an empty `critic/` (Task 1).
2. **Every image fails, or the rounds run out.** Each redo batch holds every active job, the strict `>` keeps the earliest best, `output_path` never holds a worse attempt, the run continues, and the final line is `flagged` even when the last attempt was blocked or unparseable. Tests: `test_ict6_flagged_on_exhaustion_keeps_the_best`, `test_ict9_blocked_outputs_are_skipped` and *new* `test_ic_review_focus_2_an_unparseable_last_attempt_still_flags` (Task 1).
3. **The VLM does not start, or dies mid-phase.** `maybe_up` is set before `restore_story_server(wait=True)`, so a half-started server is stopped at the end; after a transport error no further `vlm_call` happens and nothing is redone on a guess. Tests: `test_ict7a_the_vlm_does_not_start`, `test_ict7b_a_transport_error_ends_the_phase` (Task 1).
4. **An interrupt in the middle of a redo, and `ltx-movie`'s missing SIGTERM handler.** Pending stages removed, `output_path` the earlier best, the stop detached, the handlers restored; the shots record's interim `flagged` block is consistent with its `still_sha256`, so a rerun reuses the panel. Tests: `test_ict8b_an_interrupted_redo_and_its_judge_phase`, `test_ict8c_sigterm_during_judging` (Task 1) and *new* `test_ic_review_focus_4_an_interrupted_shots_redo_keeps_a_consistent_record` (Task 2).
5. **One-job batches, and blocked outputs.** `shots --redo 3` gives a one-job batch whose derived seed uses `n = 3` and whose stage basename (`panel_03.r1.pending.png`) differs from round 0's; reused panels are not judged (Q1); blocked round-0 outputs never reach the VLM. Tests: `test_ict9_blocked_outputs_are_skipped` (Task 1) and *new* `test_ic_review_focus_5_a_single_panel_redo_batch` (Task 2).

---

## Step 0: snapshot and baseline (controller; no code)

- [ ] **Step 0.1: Compressed snapshot (house rule) and disk.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad && tar -czf ic-snapshot-9fd68c1.tgz ic-wt && ls -l ic-snapshot-9fd68c1.tgz && git -C ic-wt log -1 --format=%h && git -C ic-wt status --short | wc -l && df -h /System/Volumes/Data | tail -1
```

Expected: the archive exists (a few MB); `9fd68c1` (or the plan commit on top of it); `0`; the free-space line (about 15 GiB were free during planning).

- [ ] **Step 0.2: Record the baseline failures of the full suite.** About 21 minutes. Let it finish before Task 1 Step 1 writes anything: several tests read other test files while they run.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && mkdir -p ../../ic-baseline && python3 -m pytest -q -p no:cacheprovider tests/ 2>&1 | tee ../../ic-baseline/full-base.log | grep -E '^(FAILED|ERROR) ' | sed 's/ - .*//' | sort > ../../ic-baseline/full-base-failures.txt; tail -1 ../../ic-baseline/full-base.log; wc -l < ../../ic-baseline/full-base-failures.txt
```

Expected at about 15 GiB free: `28 failed, 2943 passed, 2 skipped`, the 28 listed under the planning replay above. With 21 GiB or more free the 26 disk-reserve failures disappear. **This file is the allowed-failure list for every task.** A failure not in it is a stop-and-report.

---

### Task 1: `image_critic.py`, `bin/image-critic` and their unit tests (commit C1; spec 2.1-2.7, 6.1, 6.3; ICT1-ICT13; Review Focus 1-4)

**Files:**
- Create `qwen-agent-workspace/image_critic.py`.
- Create `qwen-agent-workspace/bin/image-critic` (mode 100755).
- Create `qwen-agent-workspace/tests/test_image_critic.py`.
- Modify `qwen-agent-workspace/tests/test_movie_ui_builder.py`: the `NEW_PY` tuple (:223-228).
- Modify `qwen-agent-workspace/tests/test_qwen_edit.py`: QET11's expected `NEW_PY` tail (:401-404).
- Pinned files touched: none.

**Interfaces:**
- Consumes (existing, through `image_critic._cd()` only): `character_dataset.extract_json(text)`, `image_data_url(path, max_side=768)`, `vlm_call(content_parts, max_tokens=600)`, `vlm_ready()`, `story_server(cmd) -> int`, `restore_story_server(wait=False) -> int`, `story_server_state() -> str`, `wait_for_vlm(timeout_s) -> bool`, `wait_for_avail(min_gib, timeout_s) -> bool`, and the constants `STORY_SERVER`, `VLM_SERVE_MODE`, `VLM_WAIT_S`, `AVAIL_WAIT_S`, `MODELS_URL`. From the caller's `qe` (`qwen_edit`): `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job") -> (results, failure)`, `wait_for_memory(floor, label, tag="seed-edit")`, `memory_floor(model_id, references=1) -> float`, `label(model_id) -> str`, `Unavailable`.
- Produces (Tasks 2 and 4 rely on these):
  - `image_critic.PASS_SCORE = 7`, `DEFAULT_ROUNDS = 2`, `MAX_ROUNDS = 4`, `CRITIC_DIR = "critic"`.
  - `critic_seed(seed, round_n, n) -> int`.
  - `parse_verdict(reply) -> {"score": int, "defects": [str], "reason": str}`, else `ValueError`.
  - `judge_image(path, seed_path=None) -> {"score", "defects", "reason"}`; raises `JudgeError`, or its subclass `VLMUnavailable`.
  - `vlm_ready() -> bool`, `vlm_models_url() -> str`.
  - `VLMSession(say)` with `up() -> None | str`, `down() -> None | str`, `restore(interrupted) -> None`.
  - `edit_with_critic(qe, model_id, loras, jobs, width, height, skill, work_dir, rounds=DEFAULT_ROUNDS, total=None, on_result=None, on_verdict=None, on_best=None, noun="job", tag="seed-edit", say=None) -> (results, failure)` of round 0; `on_verdict(n, block)`, `on_best(n, output_path)`.
  - `tests/test_image_critic.py` exports `FakeCD(log, state="STOPPED")` (its `replies` maps a judged path to its replies) and `verdict(score, defects=(), reason="r") -> str`, which Task 2's tests import.
  - `bin/image-critic`'s `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing test file.** Create `tests/test_image_critic.py` with exactly this content:

````python
"""Tests for image_critic.py and bin/image-critic (docs/superpowers/specs/2026-11-27-image-critic-design.md,
Section 6.1: ICT1-ICT13): the derived seeds, the verdict parser, judge_image, the VLM lifecycle around the judge
phases, edit_with_critic's redo loop, records and log lines, the interrupt cleanup, the calibration CLI and the
import hygiene.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py

Rules (spec 6.1): image_critic is a plain import. ic._cd is replaced by FakeCD, which records every call in order in
a shared log (FakeQE writes to the same log, so the order of Qwen and VLM work is visible); its extract_json is the
real character_dataset.extract_json and its image_data_url returns "data:" + path, so replies are scripted per file
and per call. ic.subprocess is replaced by a namespace whose Popen only records. No test contacts a server, starts a
process other than the importtime child of ICT13, or touches port 8177 or 8178. Stdlib and pytest.
"""

import glob
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import types

import pytest

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import character_dataset
import image_critic as ic

WS = mt.WS
MODELS_URL = "http://127.0.0.1:8177/v1/models"
JUDGE_PROMPT = (
    "The picture to check was made by an AI image editor. Check only the bodies of the people and animals in it for "
    "anatomy errors. Defects to look for: extra, missing or fused arms, legs, hands or fingers; melted, stretched, "
    "twisted or warped bodies or limbs; a distorted, doubled or smeared face; malformed hands; a body merging into "
    "the background, an object or another person. Ignore the art style, lighting, composition, framing, clothing, "
    "setting, image quality, and whether the picture matches any description; a dynamic or unusual pose is not a "
    "defect when the body is anatomically possible. Reply with only a JSON object with three keys. \"score\": an "
    "integer from 1 to 10 for how anatomically correct every body is, where 10 means every body is natural and "
    "complete, 7 means only small flaws a viewer would not notice at a glance, and 4 or less means an obvious "
    "defect; a picture with no people or animals scores 10. \"defects\": a list of at most 8 short phrases, one per "
    "defect you see, such as \"fused left hand\" (an empty list when there is none). \"reason\": one sentence.")
SEED_PREFACE = ("You get two images. The first is the photo the edit started from; the second is the picture to "
                "check. Use the first only to see what these people's bodies normally look like, and do not count "
                "differences in pose, setting, clothing or style. ")
START = "critic: starting the VLM (bin/story-server-restore mlx-vision --wait)"
STOP_END = "critic: stopping the VLM (it was stopped before the critic started)"
STOP_REDO = "critic: stopping the VLM for the Qwen redo"
HANDS_OFF = "the story server is SERVING text; the image critic needs it stopped or serving mlx-vision"


def verdict(score, defects=(), reason="r"):
    """A well-formed VLM reply."""
    return json.dumps({"score": score, "defects": list(defects), "reason": reason})


class FakeCD(object):
    """ic._cd's stand-in (spec 6.1). replies maps a judged file's path to its replies, one per vlm_call; a reply is a
    str, an exception (raised) or a callable (called, and its value used). The story server's state follows the
    calls: a successful stop makes vlm_ready False, a successful restore makes it True."""
    STORY_SERVER = "/fake-ws/bin/story-server"
    VLM_SERVE_MODE = "mlx-vision"
    VLM_WAIT_S = 600
    AVAIL_WAIT_S = 600
    MODELS_URL = MODELS_URL
    extract_json = staticmethod(character_dataset.extract_json)

    def __init__(self, log, state="STOPPED"):
        self.log = log
        self.state = state
        self.up = state.startswith("SERVING")
        self.replies, self.calls, self.parts, self.max_tokens = {}, {}, [], []
        self.avail, self.restore_rc, self.stop_rc, self.wait_ok = True, 0, 0, True
        self.unreadable = set()

    def story_server_state(self):
        self.log.append(("story_server_state",))
        return self.state

    def restore_story_server(self, wait=False):
        self.log.append(("restore_story_server", wait))
        if self.restore_rc == 0:
            self.up = True
        return self.restore_rc

    def story_server(self, cmd):
        self.log.append(("story_server", cmd))
        if cmd == "stop" and self.stop_rc == 0:
            self.up = False
        return self.stop_rc

    def wait_for_vlm(self, timeout_s):
        self.log.append(("wait_for_vlm", timeout_s))
        return self.wait_ok

    def wait_for_avail(self, min_gib, timeout_s):
        self.log.append(("wait_for_avail", min_gib, timeout_s))
        return self.avail

    def vlm_ready(self):
        self.log.append(("vlm_ready",))
        return self.up

    def image_data_url(self, path, max_side=768):
        self.log.append(("image_data_url", path, max_side))
        if path in self.unreadable:
            raise OSError("gone")
        return "data:" + path

    def vlm_call(self, parts, max_tokens=600):
        path = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"][-1][len("data:"):]
        self.log.append(("vlm_call", path))
        self.parts.append(parts)
        self.max_tokens.append(max_tokens)
        i = self.calls.get(path, 0)
        self.calls[path] = i + 1
        reply = self.replies[path][i]
        if callable(reply):
            reply = reply()
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeQE(object):
    """The qwen_edit stand-in (spec 6.1): run_jobs with the real signature handles the jobs in order by
    outcomes.get((n, seed), "ok"): "ok" writes b"img:<n>:<seed>" to output_path, "blocked" and "failed" write
    nothing, and an exception is raised after writing the job's stage file. failure maps a call index to the failure
    that call returns."""

    class Unavailable(Exception):
        pass

    def __init__(self, log):
        self.log = log
        self.outcomes, self.failure, self.calls, self.returns = {}, {}, [], []
        self.wait_error = None

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        index = len(self.calls)
        self.calls.append({"jobs": [dict(j) for j in jobs], "on_result": on_result is not None, "noun": noun,
                           "work_dir": work_dir})
        self.log.append(("run_jobs", [j["n"] for j in jobs]))
        results = []
        for job in jobs:
            outcome = self.outcomes.get((job["n"], job["seed"]), "ok")
            if isinstance(outcome, BaseException):
                with open(job["stage_path"], "wb") as f:
                    f.write(b"pending")
                raise outcome
            if outcome == "ok":
                with open(job["output_path"], "wb") as f:
                    f.write(b"img:%d:%d" % (job["n"], job["seed"]))
            result = {"n": job["n"], "output_path": job["output_path"], "status": outcome,
                      "seconds": None if outcome == "failed" else 1.0}
            if on_result is not None and outcome != "failed":
                on_result(dict(result))
            results.append(result)
        got = (results, self.failure.get(index))
        self.returns.append(got)
        return got

    def wait_for_memory(self, floor, label, tag="seed-edit"):
        self.log.append(("wait_for_memory", floor, label, tag))
        if self.wait_error is not None:
            raise self.wait_error

    def memory_floor(self, model_id, references=1):
        return 20.0

    def label(self, model_id):
        return "Fake"


class Env(object):
    """One test's fakes, its jobs and its recorders."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.log = []
        self.cd = FakeCD(self.log)
        self.qe = FakeQE(self.log)
        self.popens = []
        self.verdicts = []
        self.bests = []
        self.results = []

    def jobs(self, count, sub="run"):
        """count bin/seed-edit-shaped jobs under <tmp>/<sub>: seeds 11, 12, ...; work dir <tmp>/<sub>/work."""
        run_dir = os.path.join(self.tmp, sub)
        self.work = os.path.join(run_dir, "work")
        os.makedirs(self.work)
        return [{"n": n, "seed": 10 + n, "prompt": "make it night", "source": os.path.join(self.work, "source.png"),
                 "stage_path": os.path.join(self.work, "cand_%02d.pending.png" % n),
                 "output_path": os.path.join(run_dir, "cand_%02d.png" % n)} for n in range(1, count + 1)]

    def attempt(self, job, k):
        return os.path.join(os.path.dirname(job["stage_path"]), "critic", "cand_%02d.r%d.png" % (job["n"], k))

    def run(self, jobs, **kw):
        kw.setdefault("on_verdict", lambda n, block: self.verdicts.append((n, block)))
        kw.setdefault("on_best", lambda n, path: self.bests.append((n, path)))
        kw.setdefault("on_result", lambda r: self.results.append(r))
        return ic.edit_with_critic(self.qe, "qwen21-q4", [], jobs, 64, 64, "seed_edit", self.work, **kw)

    def block(self, n):
        """The newest block on_verdict got for job n."""
        return [b for m, b in self.verdicts if m == n][-1]

    def lifecycle(self):
        return [e for e in self.log if e[0] != "image_data_url"]


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = Env(os.path.realpath(str(tmp_path)))
    monkeypatch.setattr(ic, "_cd", lambda: e.cd)
    monkeypatch.setattr(ic, "subprocess", types.SimpleNamespace(
        Popen=lambda argv, **kw: e.popens.append((argv, kw)), DEVNULL=subprocess.DEVNULL))
    return e


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


def _att(round_n, seed, score, defects=(), note=None):
    return {"round": round_n, "seed": seed, "score": score, "defects": list(defects), "note": note}


# --- ICT1: constants, prompts and seeds ----------------------------------------------------------------------

def test_ict1_constants_prompts_and_seeds():
    assert (ic.PASS_SCORE, ic.DEFAULT_ROUNDS, ic.MAX_ROUNDS) == (7, 2, 4)
    assert ic.JUDGE_WITH_SEED is False
    assert (ic.JUDGE_MAX_SIDE, ic.JUDGE_ATTEMPTS, ic.JUDGE_MAX_TOKENS) == (1024, 2, 400)
    assert (ic.DEFECTS_MAX, ic.DEFECT_CHARS, ic.REASON_CHARS) == (8, 60, 300)
    assert (ic.VLM_MIN_AVAIL_GIB, ic.SEED_MAX, ic.CRITIC_DIR) == (28.0, 2147483647, "critic")
    assert ic.LINE_STATES == {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}
    assert ic.JUDGE_PROMPT == JUDGE_PROMPT
    assert ic.SEED_PREFACE == SEED_PREFACE and ic.JUDGE_SEED_PROMPT == SEED_PREFACE + JUDGE_PROMPT
    assert ic.JUDGE_RETRY == ('Your previous reply was rejected: %s. Previous reply: %s\n'
                              'Reply again with only the JSON object: "score" an integer from 1 to 10, "defects" a '
                              'list of short phrases (empty when there is none) and "reason" one sentence.')
    expected = int(hashlib.sha256(b"image-critic:7:1:2").hexdigest()[:8], 16) & 2147483647
    assert ic.critic_seed(7, 1, 2) == expected
    assert ic.critic_seed(7, 2, 2) != expected and ic.critic_seed(7, 1, 3) != expected
    rng = random.Random(27)
    for _ in range(100):
        seed = ic.critic_seed(rng.randrange(0, 2 ** 31), rng.randrange(1, 5), rng.randrange(1, 16))
        assert 0 <= seed <= ic.SEED_MAX


# --- ICT2: parse_verdict --------------------------------------------------------------------------------------

def test_ict2_parse_verdict(env):
    good = '{"score": 8, "defects": ["fused left hand"], "reason": "One hand is fused."}'
    want = {"score": 8, "defects": ["fused left hand"], "reason": "One hand is fused."}
    assert ic.parse_verdict(good) == want
    assert ic.parse_verdict("```json\n" + good + "\n```") == want
    assert ic.parse_verdict('<think>{"score": 1}</think>' + good) == want
    for score, message in ((True, "score must be an integer, got True"), (8.0, "score must be an integer, got 8.0"),
                           ("8", "score must be an integer, got '8'"), (None, "score must be an integer, got None"),
                           (0, "score must be 1-10, got 0"), (11, "score must be 1-10, got 11")):
        with pytest.raises(ValueError) as e:
            ic.parse_verdict(json.dumps({"score": score, "defects": [], "reason": "r"}))
        assert str(e.value) == message, score
    for reply, message in (('{"score": 8, "reason": "r"}', "missing key: defects"),
                           ('{"score": 8, "defects": "x"}', "defects must be a list of strings"),
                           ('{"score": 8, "defects": ["a", 2]}', "defects must be a list of strings"),
                           ("no json", "no JSON object found in text")):
        with pytest.raises(ValueError) as e:
            ic.parse_verdict(reply)
        assert str(e.value) == message, reply
    with pytest.raises(ValueError) as e:
        ic.parse_verdict(None)
    assert str(e.value) == "the reply has no text"
    messy = ["  fused \n left   hand ", "", "   ", "x" * 80] + ["d%d" % i for i in range(10)]
    got = ic.parse_verdict(json.dumps({"score": 5, "defects": messy}))
    assert got == {"score": 5, "defects": ["fused left hand", "x" * 60, "d0", "d1", "d2", "d3", "d4", "d5"],
                   "reason": ""}
    assert ic.parse_verdict('{"score": 5, "defects": [], "reason": 7}')["reason"] == ""
    assert ic.parse_verdict(json.dumps({"score": 5, "defects": [], "reason": " a \n b " + "c" * 400}))["reason"] == (
        "a b " + "c" * 296)


# --- ICT3: judge_image ----------------------------------------------------------------------------------------

def test_ict3_judge_image(env):
    cd = env.cd
    img, seed = os.path.join(env.tmp, "edit.png"), os.path.join(env.tmp, "seed.png")
    cd.replies[img] = ["no json here", verdict(8, ["fused hand"])]
    assert ic.judge_image(img) == {"score": 8, "defects": ["fused hand"], "reason": "r"}
    first, second = cd.parts
    assert first == [{"type": "text", "text": JUDGE_PROMPT}, {"type": "image_url", "image_url": {"url": "data:" + img}}]
    assert second[:-1] == first
    assert second[-1] == {"type": "text", "text": ic.JUDGE_RETRY % ("no JSON object found in text", "no json here")}
    assert cd.max_tokens == [400, 400]
    assert [e[2] for e in env.log if e[0] == "image_data_url"] == [1024]
    cd.replies[img] = ["a", "b", "c", "d"]
    cd.calls = {}
    with pytest.raises(ic.JudgeError) as e:
        ic.judge_image(img)
    assert type(e.value) is ic.JudgeError and str(e.value) == "unparseable: no JSON object found in text"
    for error, text in ((RuntimeError("HTTP 500"), "VLM request failed: RuntimeError: HTTP 500"),
                        (OSError("connection refused"), "VLM request failed: OSError: connection refused")):
        cd.replies[img], cd.calls = [error], {}
        with pytest.raises(ic.VLMUnavailable) as e:
            ic.judge_image(img)
        assert str(e.value) == text
    del cd.parts[:]
    cd.replies[img], cd.calls = [verdict(9)], {}
    assert ic.judge_image(img, seed)["score"] == 9
    assert cd.parts[-1] == [{"type": "text", "text": SEED_PREFACE + JUDGE_PROMPT},
                            {"type": "image_url", "image_url": {"url": "data:" + seed}},
                            {"type": "image_url", "image_url": {"url": "data:" + img}}]
    cd.unreadable.add(seed)
    with pytest.raises(ic.JudgeError) as e:
        ic.judge_image(img, seed)
    assert type(e.value) is ic.JudgeError and str(e.value) == "cannot read %s: OSError: gone" % seed


# --- ICT4 (K5): every image passes ----------------------------------------------------------------------------

def test_ict4_all_pass_one_start_one_stop(env, capsys):
    jobs = env.jobs(3)
    for job in jobs:
        env.cd.replies[job["output_path"]] = [verdict(8)]
    got = env.run(jobs)
    assert got[0] is env.qe.returns[0][0] and got[1] is None
    assert len(env.qe.calls) == 1 and env.qe.calls[0]["on_result"] is True
    assert env.lifecycle() == [("run_jobs", [1, 2, 3]), ("story_server_state",), ("wait_for_avail", 28.0, 600),
                               ("restore_story_server", True), ("wait_for_vlm", 600)] + [
        ("vlm_call", job["output_path"]) for job in jobs] + [("story_server", "stop")]
    for job in jobs:
        assert env.block(job["n"]) == {"status": "passed", "score": 8, "defects": [], "reason": "r",
                                       "seed_used": job["seed"], "pass_score": 7,
                                       "attempts": [_att(0, job["seed"], 8)]}
    assert [n for n, _b in env.verdicts] == [1, 2, 3, 1, 2, 3]
    assert glob.glob(os.path.join(env.work, "critic", "*.png")) == [] and env.bests == []
    assert [r["n"] for r in env.results] == [1, 2, 3]
    assert _lines(capsys) == ["critic: judging 3 jobs with the VLM (round 0)", START,
                              "critic 1/3: ok (score 8, attempt 1)", "critic 2/3: ok (score 8, attempt 1)",
                              "critic 3/3: ok (score 8, attempt 1)",
                              "critic: done: 3 passed, 0 flagged, 0 unjudged; 0 redo round(s) run", STOP_END]


# --- ICT5 (K2, K3): only the failed job is redone, and the VLM and Qwen take turns ----------------------------

def test_ict5_only_the_failed_job_is_redone_in_order(env, capsys):
    jobs = env.jobs(3)
    two = jobs[1]
    seed = ic.critic_seed(12, 1, 2)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3, ["fused left hand"])],
                           jobs[2]["output_path"]: [verdict(8)], env.attempt(two, 1): [verdict(8, [], "fixed")]})
    assert env.run(jobs, total=3)[1] is None
    (_first, redo) = env.qe.calls
    critic = os.path.join(env.work, "critic")
    assert redo["jobs"] == [dict(two, seed=seed, stage_path=os.path.join(critic, "cand_02.r1.pending.png"),
                                 output_path=os.path.join(critic, "cand_02.r1.png"))]
    assert redo["on_result"] is False and redo["noun"] == "job" and redo["work_dir"] == env.work
    assert env.lifecycle() == [
        ("run_jobs", [1, 2, 3]), ("story_server_state",), ("wait_for_avail", 28.0, 600),
        ("restore_story_server", True), ("wait_for_vlm", 600)] + [("vlm_call", j["output_path"]) for j in jobs] + [
        ("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"), ("run_jobs", [2]),
        ("wait_for_avail", 28.0, 600), ("restore_story_server", True), ("wait_for_vlm", 600),
        ("vlm_call", env.attempt(two, 1)), ("story_server", "stop")]
    assert _read(two["output_path"]) == b"img:2:%d" % seed
    assert _read(env.attempt(two, 0)) == b"img:2:12"
    assert sorted(os.listdir(critic)) == ["cand_02.r0.png", "cand_02.r1.png"]
    assert env.bests == [(2, two["output_path"])]
    assert env.block(2) == {"status": "passed", "score": 8, "defects": [], "reason": "fixed", "seed_used": seed,
                            "pass_score": 7, "attempts": [_att(0, 12, 3, ["fused left hand"]), _att(1, seed, 8)]}
    assert env.block(1)["attempts"] == [_att(0, 11, 8)]
    assert two["seed"] == 12 and "critic" not in two
    out = _lines(capsys)
    assert [line for line in out if line.startswith("critic 2/3")] == [
        "critic 2/3: redo (score 3: fused left hand)", "critic 2/3: ok (score 8, attempt 2)"]
    assert out[5:9] == [STOP_REDO, "critic: redo round 1 of 2: job 2 with new seeds",
                        "critic: judging 1 job with the VLM (round 1)", START]
    assert out[-2:] == ["critic: done: 3 passed, 0 flagged, 0 unjudged; 1 redo round(s) run", STOP_END]


# --- ICT6: flagged on exhaustion, the best attempt kept ---------------------------------------------------------

def test_ict6_flagged_on_exhaustion_keeps_the_best(env, capsys):
    (job,) = env.jobs(1, "a")
    env.cd.replies.update({job["output_path"]: [verdict(5, ["melted arm"])], env.attempt(job, 1): [verdict(3, ["x"])],
                           env.attempt(job, 2): [verdict(4, ["y"])]})
    assert env.run([job], rounds=2)[1] is None
    assert [len(c["jobs"]) for c in env.qe.calls] == [1, 1, 1]
    assert _read(job["output_path"]) == b"img:1:11" and env.bests == []
    block = env.block(1)
    assert (block["status"], block["score"], block["defects"], block["seed_used"]) == ("flagged", 5, ["melted arm"], 11)
    assert [a["score"] for a in block["attempts"]] == [5, 3, 4]
    assert [a["seed"] for a in block["attempts"]] == [11, ic.critic_seed(11, 1, 1), ic.critic_seed(11, 2, 1)]
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 5: melted arm)", "critic 1/1: redo (score 3: x)",
        "critic 1/1: flagged (best score 5 of 3 attempts: melted arm)"]
    (tie,) = env.jobs(1, "b")
    env.cd.replies.update({tie["output_path"]: [verdict(5, ["a"])], env.attempt(tie, 1): [verdict(5, ["b"])],
                           env.attempt(tie, 2): [verdict(2, ["c"])]})
    env.run([tie])
    assert _read(tie["output_path"]) == b"img:1:11"
    assert (env.block(1)["seed_used"], env.block(1)["defects"]) == (11, ["a"])
    capsys.readouterr()
    (once,) = env.jobs(1, "c")
    env.cd.replies[once["output_path"]] = [verdict(5, ["melted arm"])]
    calls = len(env.qe.calls)
    env.run([once], rounds=0)
    assert len(env.qe.calls) == calls + 1
    assert env.block(1)["status"] == "flagged" and len(env.block(1)["attempts"]) == 1
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: flagged (best score 5 of 1 attempts: melted arm)"]


# --- ICT7: unjudged when the VLM is down or the reply is unusable -----------------------------------------------

def test_ict7a_the_vlm_does_not_start(env, capsys):
    jobs = env.jobs(2)
    env.cd.restore_rc = 1
    env.run(jobs)
    reason = "bin/story-server-restore mlx-vision --wait exited 1"
    for job in jobs:
        assert env.block(job["n"]) == {"status": "unjudged", "score": None, "defects": [], "reason": reason,
                                       "seed_used": job["seed"], "pass_score": 7,
                                       "attempts": [_att(0, job["seed"], None, note="not judged: " + reason)]}
    assert len(env.qe.calls) == 1
    assert env.lifecycle()[-2:] == [("restore_story_server", True), ("story_server", "stop")]
    out = _lines(capsys)
    assert "critic 1/2: unjudged (%s)" % reason in out and "critic 2/2: unjudged (%s)" % reason in out
    assert "critic: done: 0 passed, 0 flagged, 2 unjudged; 0 redo round(s) run" in out


def test_ict7b_a_transport_error_ends_the_phase(env, capsys):
    jobs = env.jobs(3)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(3)],
                           jobs[1]["output_path"]: [OSError("connection refused")],
                           jobs[2]["output_path"]: [verdict(9)]})
    env.run(jobs)
    assert jobs[2]["output_path"] not in env.cd.calls
    assert len(env.qe.calls) == 1
    reason = "VLM request failed: OSError: connection refused"
    assert [env.block(n)["status"] for n in (1, 2, 3)] == ["flagged", "unjudged", "unjudged"]
    assert env.block(3)["reason"] == reason and env.block(3)["attempts"][0]["note"] == "not judged: " + reason
    assert [line for line in _lines(capsys) if line.startswith("critic ")] == [
        "critic 1/3: redo (score 3: no defect named)", "critic 2/3: unjudged (%s)" % reason,
        "critic 3/3: unjudged (%s)" % reason, "critic 1/3: flagged (best score 3 of 1 attempts: no defect named)"]


def test_ict7c_an_unparseable_image_is_never_redone(env):
    jobs = env.jobs(2)
    env.cd.replies.update({jobs[0]["output_path"]: ["nope", "still nope"], jobs[1]["output_path"]: [verdict(3)],
                           env.attempt(jobs[1], 1): [verdict(8)]})
    env.run(jobs)
    assert [[j["n"] for j in call["jobs"]] for call in env.qe.calls] == [[1, 2], [2]]
    assert env.block(1)["status"] == "unjudged"
    assert env.block(1)["reason"] == "unparseable: no JSON object found in text"
    assert env.block(2)["status"] == "passed"


def test_ict7d_a_foreign_story_server_is_left_alone(env, capsys):
    jobs = env.jobs(2)
    env.cd.state = "SERVING text"
    env.run(jobs)
    assert env.lifecycle() == [("run_jobs", [1, 2]), ("story_server_state",)]
    assert [env.block(n)["reason"] for n in (1, 2)] == [HANDS_OFF, HANDS_OFF]
    assert [env.block(n)["status"] for n in (1, 2)] == ["unjudged", "unjudged"]
    assert "critic 1/2: unjudged (%s)" % HANDS_OFF in _lines(capsys)


# --- ICT8 (K4): the VLM is restored on an exception and on a signal ---------------------------------------------

def test_ict8a_an_exception_restores_synchronously(env, capsys):
    jobs = env.jobs(1)
    env.cd.replies[jobs[0]["output_path"]] = [verdict(8)]

    def broken(n, block):
        raise RuntimeError("record write failed")

    with pytest.raises(RuntimeError, match="^record write failed$"):
        env.run(jobs, on_verdict=broken)
    assert env.lifecycle()[-1] == ("story_server", "stop") and env.popens == []
    assert _lines(capsys)[-1] == STOP_END


def test_ict8b_an_interrupted_redo_and_its_judge_phase(env, capsys):
    jobs = env.jobs(2, "a")
    two = jobs[1]
    seed = ic.critic_seed(12, 1, 2)
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)]})
    env.qe.outcomes[(2, seed)] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        env.run(jobs)
    assert glob.glob(os.path.join(env.work, "critic", "*.pending.png")) == []
    assert _read(two["output_path"]) == b"img:2:12"
    assert env.lifecycle()[-3:] == [("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
                                    ("run_jobs", [2])]
    assert env.popens == []
    capsys.readouterr()
    jobs = env.jobs(2, "b")
    two = jobs[1]
    del env.qe.outcomes[(2, seed)]
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)],
                           env.attempt(two, 1): [KeyboardInterrupt()]})
    del env.log[:]
    with pytest.raises(KeyboardInterrupt):
        env.run(jobs)
    assert env.popens == [([FakeCD.STORY_SERVER, "stop"], {
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        "start_new_session": True, "close_fds": True})]
    assert [e for e in env.log if e == ("story_server", "stop")] == [("story_server", "stop")]
    assert env.lifecycle()[-1] == ("vlm_call", env.attempt(two, 1))
    assert _read(two["output_path"]) == b"img:2:12"
    assert capsys.readouterr().err == "critic: interrupted; stopping the VLM in its own session\n"


def test_ict8c_sigterm_during_judging(env, monkeypatch):
    previous = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    hup = signal.getsignal(signal.SIGHUP)
    try:
        jobs = env.jobs(1)

        def terminate():
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL, "no SIGTERM handler: not sending it"
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(2)
            return verdict(8)

        env.cd.replies[jobs[0]["output_path"]] = [terminate]
        with pytest.raises(KeyboardInterrupt):
            env.run(jobs)
        assert [argv for argv, _kw in env.popens] == [[FakeCD.STORY_SERVER, "stop"]]
        assert ("story_server", "stop") not in env.log
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL and signal.getsignal(signal.SIGHUP) is hup
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_ict8d_a_serving_vlm_is_left_serving(env):
    env.cd.state, env.cd.up = "SERVING mlx-vision", True
    jobs = env.jobs(2, "a")
    two = jobs[1]
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)],
                           env.attempt(two, 1): [verdict(8)]})
    env.run(jobs)
    assert env.lifecycle() == [
        ("run_jobs", [1, 2]), ("story_server_state",), ("vlm_ready",), ("vlm_call", jobs[0]["output_path"]),
        ("vlm_call", two["output_path"]), ("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
        ("run_jobs", [2]), ("vlm_ready",), ("wait_for_avail", 28.0, 600), ("restore_story_server", True),
        ("wait_for_vlm", 600), ("vlm_call", env.attempt(two, 1))]
    env.cd.state, env.cd.up = "SERVING mlx-vision", True
    jobs = env.jobs(2, "b")
    two = jobs[1]
    env.qe.outcomes[(2, ic.critic_seed(12, 1, 2))] = "blocked"
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], two["output_path"]: [verdict(3)]})
    del env.log[:]
    env.run(jobs, rounds=1)
    assert env.lifecycle()[-4:] == [("story_server", "stop"), ("wait_for_memory", 20.0, "Fake", "seed-edit"),
                                    ("run_jobs", [2]), ("restore_story_server", False)]
    assert env.block(2)["status"] == "flagged"


# --- ICT9: blocked outputs are skipped, not judged ------------------------------------------------------------

def test_ict9_blocked_outputs_are_skipped(env, capsys):
    jobs = env.jobs(3, "a")
    env.qe.outcomes[(2, 12)] = "blocked"
    env.cd.replies.update({jobs[0]["output_path"]: [verdict(8)], jobs[2]["output_path"]: [verdict(9)]})
    env.run(jobs)
    assert ("vlm_call", jobs[1]["output_path"]) not in env.log
    assert sorted(set(n for n, _b in env.verdicts)) == [1, 3]
    assert not [line for line in _lines(capsys) if line.startswith("critic 2/3")]
    env.verdicts[:] = []
    (job,) = env.jobs(1, "b")
    seed = ic.critic_seed(11, 1, 1)
    env.qe.outcomes[(1, seed)] = "blocked"
    env.cd.replies[job["output_path"]] = [verdict(3, ["fused hand"])]
    env.run([job], rounds=1)
    block = env.block(1)
    assert (block["status"], block["score"], block["seed_used"]) == ("flagged", 3, 11)
    assert block["attempts"] == [_att(0, 11, 3, ["fused hand"]),
                                 _att(1, seed, None, note="blocked by the content screen")]
    assert [b["attempts"][-1]["note"] for _n, b in env.verdicts] == [None, "blocked by the content screen",
                                                                      "blocked by the content screen"]
    assert _read(job["output_path"]) == b"img:1:11"
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 3: fused hand)", "critic 1/1: flagged (best score 3 of 2 attempts: fused hand)"]


# --- Review Focus 2: an unparseable last attempt still ends flagged, with the earlier best kept ---------------------

def test_ic_review_focus_2_an_unparseable_last_attempt_still_flags(env, capsys):
    (job,) = env.jobs(1)
    env.cd.replies.update({job["output_path"]: [verdict(4, ["warped face"])], env.attempt(job, 1): ["nope", "nope"]})
    assert env.run([job], rounds=1)[1] is None
    block = env.block(1)
    assert (block["status"], block["score"], block["seed_used"]) == ("flagged", 4, 11)
    assert block["attempts"][1]["note"] == "not judged: unparseable: no JSON object found in text"
    assert _read(job["output_path"]) == b"img:1:11" and env.bests == []
    assert [line for line in _lines(capsys) if line.startswith("critic 1/1")] == [
        "critic 1/1: redo (score 4: warped face)", "critic 1/1: flagged (best score 4 of 2 attempts: warped face)"]


# --- ICT10: nothing to judge ----------------------------------------------------------------------------------

def test_ict10_nothing_to_judge(env, capsys):
    jobs = env.jobs(2, "a")
    env.qe.failure[0] = "Fake child exited 1: boom"
    assert env.run(jobs) == env.qe.returns[0]
    assert env.lifecycle() == [("run_jobs", [1, 2])] and env.verdicts == []
    assert _lines(capsys) == ["critic: not run; the job batch failed"]
    jobs = env.jobs(2, "b")
    env.qe.outcomes.update({(1, 11): "blocked", (2, 12): "blocked"})
    got = env.run(jobs)
    assert got == env.qe.returns[1] and got[1] is None
    assert env.lifecycle() == [("run_jobs", [1, 2]), ("run_jobs", [1, 2])] and env.verdicts == []
    assert _lines(capsys) == ["critic: not run; no job produced an image"]
    assert not os.path.exists(os.path.join(env.work, "critic"))


# --- ICT11: the redo is not run ---------------------------------------------------------------------------------

def test_ict11_the_redo_is_not_run(env, capsys):
    (job,) = env.jobs(1, "a")
    env.cd.replies[job["output_path"]] = [verdict(3)]
    env.qe.wait_error = FakeQE.Unavailable("x")
    env.run([job])
    assert len(env.qe.calls) == 1 and env.block(1)["status"] == "flagged"
    assert "critic: redo round 1 of 2 not run: x" in _lines(capsys)
    env.qe.wait_error = None
    (job,) = env.jobs(1, "b")
    env.cd.replies[job["output_path"]] = [verdict(3)]
    env.cd.stop_rc = 3
    env.run([job])
    assert len(env.qe.calls) == 2 and env.block(1)["status"] == "flagged"
    captured = capsys.readouterr()
    assert "critic: redo round 1 of 2 not run: bin/story-server stop exited 3" in captured.out.splitlines()
    assert captured.err == "critic: warning: bin/story-server stop exited 3; the VLM may still hold its memory\n"


# --- ICT12: bin/image-critic ----------------------------------------------------------------------------------

def _cli():
    loader = importlib.machinery.SourceFileLoader("image_critic_cli", os.path.join(WS, "bin", "image-critic"))
    spec = importlib.util.spec_from_loader("image_critic_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _files(env, *names):
    paths = []
    for name in names:
        path = os.path.join(env.tmp, name)
        with open(path, "wb") as f:
            f.write(b"png")
        paths.append(path)
    return paths


def test_ict12_the_calibration_cli(env, capsys):
    cli = _cli()
    assert cli.ic is ic
    a, b, c, seed = _files(env, "a.png", "b.png", "c.png", "seed.png")
    env.cd.up = True
    env.cd.replies.update({a: [verdict(8, ["small hand"], "fine")], b: [verdict(4, [], "")], c: ["x", "y"]})
    assert cli.main(["score", a, b]) == 0
    assert capsys.readouterr().out.splitlines() == ["%s: score 8 PASS: small hand -- fine" % a,
                                                    "%s: score 4 FAIL: no defect named -- -" % b,
                                                    "pass score 7: 1 pass, 1 fail, 0 unjudged"]
    env.cd.calls = {}
    assert cli.main(["score", a, b, "--pass-score", "9", "--json"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [{"path": a, "score": 8, "verdict": "fail", "defects": ["small hand"], "reason": "fine",
                     "error": None},
                    {"path": b, "score": 4, "verdict": "fail", "defects": [], "reason": "", "error": None}]
    env.cd.calls = {}
    del env.cd.parts[:]
    assert cli.main(["score", a, c, "--seed", seed]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "%s: score 8 PASS: small hand -- fine" % a, "%s: UNJUDGED: unparseable: no JSON object found in text" % c,
        "pass score 7: 1 pass, 0 fail, 1 unjudged"]
    assert env.cd.parts[0][1] == {"type": "image_url", "image_url": {"url": "data:" + seed}}
    env.cd.calls = {}
    env.cd.replies[b] = [OSError("refused")]
    assert cli.main(["score", b, a, "--json"]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["verdict"], r["score"], r["error"]) for r in rows] == [
        ("unjudged", None, "VLM request failed: OSError: refused")] * 2
    assert a not in env.cd.calls
    del env.log[:]
    missing = os.path.join(env.tmp, "missing.png")
    assert cli.main(["score", a, missing]) == 2
    assert capsys.readouterr().err == "Error: %s is not a file\n" % missing
    assert cli.main(["score", a, "--seed", missing]) == 2
    assert capsys.readouterr().err == "Error: %s is not a file\n" % missing
    assert ("vlm_ready",) not in env.log
    assert cli.main(["score", a, "--pass-score", "11"]) == 2
    assert capsys.readouterr().err == "Error: --pass-score must be an integer from 1 to 10\n"
    env.cd.up = False
    assert cli.main(["score", a]) == 2
    assert capsys.readouterr().err == (
        "Error: the VLM is not serving at %s; start it with bin/story-server mlx-vision\n" % MODELS_URL)
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


# --- ICT13: import hygiene ------------------------------------------------------------------------------------

def test_ict13_import_hygiene(tmp_path):
    with open(os.path.join(WS, "image_critic.py"), encoding="utf-8") as f:
        source = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M) == [
        "glob", "hashlib", "os", "re", "shutil", "signal", "subprocess", "sys", "threading"]
    proc = subprocess.run([sys.executable, "-B", "-X", "importtime", "-c", "import image_critic"], cwd=WS,
                          capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    imported = set(line.rsplit("|", 1)[1].strip().split(".")[0] for line in proc.stderr.splitlines()
                   if line.startswith("import time:") and line.count("|") == 2)
    assert "image_critic" in imported
    assert not imported & {"character_dataset", "PIL", "psutil"}, sorted(imported)
    with open(os.path.join(WS, "bin", "image-critic"), encoding="utf-8") as f:
        cli = f.read()
    assert re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", cli, re.M) == [
        "argparse", "json", "os", "sys", "image_critic"]
    assert os.stat(os.path.join(WS, "bin", "image-critic")).st_mode & 0o111 == 0o111
````

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py 2>&1 | tail -3`

Expected: `ERROR tests/test_image_critic.py`, `Interrupted: 1 error during collection`, `1 error in …` (`ModuleNotFoundError: No module named 'image_critic'`).

- [ ] **Step 3: Create `image_critic.py`** with exactly this content (spec 2.1-2.4; R3 is the `refs` line in `redo_phase`):

````python
"""image_critic -- the local VLM judges Qwen seed edits for broken bodies, and the failures are re-edited with new
seeds (docs/superpowers/specs/2026-11-27-image-critic-design.md).

judge_image scores one picture with the local 27B VLM (bin/story-server mlx-vision, 127.0.0.1:8177) and returns
{"score": 1-10, "defects": [...], "reason": "..."}. edit_with_critic wraps qwen_edit.run_jobs: after the Qwen batch
has returned it starts the VLM, judges every ok output, stops the VLM, re-edits only the jobs scored below
PASS_SCORE with derived seeds (at most `rounds` redo batches), keeps the best-scored attempt at each job's
output_path and flags the jobs whose best attempt never passed. Qwen and the VLM are never resident together, and
the story server is left in the state the critic found it in.

Python 3.9 and 3.13. The top level imports only the standard library; character_dataset (PIL, psutil) is imported
inside the functions that call the VLM or bin/story-server. movie_ui_server never imports this module.
"""

import glob
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading

PASS_SCORE = 7              # a score >= PASS_SCORE passes; calibrated live (spec ICL1)
DEFAULT_ROUNDS = 2          # redo rounds when --critic-rounds is not given
MAX_ROUNDS = 4
JUDGE_WITH_SEED = False     # edit_with_critic sends the edit alone (spec Q2); bin/image-critic --seed sends both
JUDGE_MAX_SIDE = 1024       # image_data_url's long side for a judged image
JUDGE_ATTEMPTS = 2          # one call, then one retry that quotes the rejected reply
JUDGE_MAX_TOKENS = 400
DEFECTS_MAX = 8
DEFECT_CHARS = 60
REASON_CHARS = 300
VLM_MIN_AVAIL_GIB = 28.0    # available memory awaited before the VLM starts
SEED_MAX = 2147483647
CRITIC_DIR = "critic"
THINK_RE = re.compile(r"(?s)<think>.*?</think>")          # bin/seam-report THINK_RE
LINE_STATES = {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}

JUDGE_PROMPT = (
    "The picture to check was made by an AI image editor. Check only the bodies of the people and animals in it for "
    "anatomy errors. Defects to look for: extra, missing or fused arms, legs, hands or fingers; melted, stretched, "
    "twisted or warped bodies or limbs; a distorted, doubled or smeared face; malformed hands; a body merging into "
    "the background, an object or another person. Ignore the art style, lighting, composition, framing, clothing, "
    "setting, image quality, and whether the picture matches any description; a dynamic or unusual pose is not a "
    "defect when the body is anatomically possible. Reply with only a JSON object with three keys. \"score\": an "
    "integer from 1 to 10 for how anatomically correct every body is, where 10 means every body is natural and "
    "complete, 7 means only small flaws a viewer would not notice at a glance, and 4 or less means an obvious "
    "defect; a picture with no people or animals scores 10. \"defects\": a list of at most 8 short phrases, one per "
    "defect you see, such as \"fused left hand\" (an empty list when there is none). \"reason\": one sentence.")
SEED_PREFACE = (
    "You get two images. The first is the photo the edit started from; the second is the picture to check. Use the "
    "first only to see what these people's bodies normally look like, and do not count differences in pose, setting, "
    "clothing or style. ")
JUDGE_SEED_PROMPT = SEED_PREFACE + JUDGE_PROMPT
JUDGE_RETRY = ("Your previous reply was rejected: %s. Previous reply: %s\n"
               "Reply again with only the JSON object: \"score\" an integer from 1 to 10, \"defects\" a list of short "
               "phrases (empty when there is none) and \"reason\" one sentence.")


class JudgeError(Exception):
    """This image could not be judged."""


class VLMUnavailable(JudgeError):
    """The VLM is not usable for any further image."""


def _cd():
    """character_dataset, imported here and only here (spec 2.1); the tests replace this function."""
    import character_dataset
    return character_dataset


def _say(text):
    print(text, flush=True)


# ---------------------------------------------------------------------------
# Seeds, verdicts and judge_image (spec 2.2)
# ---------------------------------------------------------------------------

def critic_seed(seed, round_n, n):
    """The seed of job n's redo in round round_n: derived from the job's requested seed (the
    location_dataset.topup_seed pattern), so a rerun derives the same seeds."""
    return int(hashlib.sha256(("image-critic:%d:%d:%d" % (seed, round_n, n)).encode("ascii")).hexdigest()[:8],
               16) & SEED_MAX


def parse_verdict(reply):
    """{"score", "defects", "reason"} of one VLM reply, else ValueError naming the first problem (spec 2.2)."""
    if not isinstance(reply, str):
        raise ValueError("the reply has no text")
    d = _cd().extract_json(THINK_RE.sub("", reply))
    score = d.get("score")
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValueError("score must be an integer, got %r" % (score,))
    if not 1 <= score <= 10:
        raise ValueError("score must be 1-10, got %d" % score)
    if "defects" not in d:
        raise ValueError("missing key: defects")
    defects = d["defects"]
    if not (isinstance(defects, list) and all(isinstance(x, str) for x in defects)):
        raise ValueError("defects must be a list of strings")
    cleaned = [x for x in (" ".join(x.split())[:DEFECT_CHARS] for x in defects) if x][:DEFECTS_MAX]
    r = d.get("reason")
    reason = " ".join(r.split())[:REASON_CHARS] if isinstance(r, str) else ""
    return {"score": score, "defects": cleaned, "reason": reason}


def judge_image(path, seed_path=None):
    """The verdict of the picture at path (with seed_path, the edit's source, sent first): one VLM call, then one
    retry that quotes the rejected reply. JudgeError when this image cannot be judged; VLMUnavailable (a
    JudgeError) when the VLM itself failed."""
    cd = _cd()
    parts = [{"type": "text", "text": JUDGE_SEED_PROMPT if seed_path else JUDGE_PROMPT}]
    for p in ([seed_path] if seed_path else []) + [path]:
        try:
            url = cd.image_data_url(p, JUDGE_MAX_SIDE)
        except Exception as e:
            raise JudgeError("cannot read %s: %s: %s" % (p, type(e).__name__, e))
        parts.append({"type": "image_url", "image_url": {"url": url}})
    reply, error = None, None
    for _attempt in range(JUDGE_ATTEMPTS):
        content = parts if error is None else parts + [{"type": "text", "text": JUDGE_RETRY % (error, reply)}]
        try:
            reply = cd.vlm_call(content, max_tokens=JUDGE_MAX_TOKENS)
        except Exception as e:
            raise VLMUnavailable("VLM request failed: %s: %s" % (type(e).__name__, e))
        try:
            return parse_verdict(reply)
        except ValueError as e:
            error = e
    raise JudgeError("unparseable: %s" % error)


def vlm_ready():
    return _cd().vlm_ready()


def vlm_models_url():
    return _cd().MODELS_URL


# ---------------------------------------------------------------------------
# The VLM lifecycle (spec 2.3)
# ---------------------------------------------------------------------------

class VLMSession(object):
    """Starts the VLM for the judge phases, stops it for each Qwen redo, and returns bin/story-server to the state
    it was in before the first judge phase. A story server in any other state (text mode, FOREIGN, UNKNOWN) is left
    alone: up() then returns the hands-off reason and nothing is started or stopped."""

    def __init__(self, say):
        self.original = None
        self.hands_off = None
        self.serving = False
        self.maybe_up = False
        self.say = say

    def up(self):
        """None when the VLM can judge, else the reason it cannot."""
        cd = _cd()
        mode = cd.VLM_SERVE_MODE
        if self.original is None:
            self.original = cd.story_server_state()
            if self.original not in ("STOPPED", "SERVING " + mode, "LOADING " + mode):
                self.hands_off = ("the story server is %s; the image critic needs it stopped or serving %s"
                                  % (self.original, mode))
        if self.hands_off:
            return self.hands_off
        if self.serving:
            return None
        if self.original != "STOPPED" and cd.vlm_ready():
            self.serving = self.maybe_up = True
            return None
        self.say("critic: starting the VLM (bin/story-server-restore %s --wait)" % mode)
        if not cd.wait_for_avail(VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S):
            return "less than %g GiB available for the VLM after waiting %d s" % (VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S)
        self.maybe_up = True
        rc = cd.restore_story_server(wait=True)
        if rc != 0:
            return "bin/story-server-restore %s --wait exited %d" % (mode, rc)
        if not cd.wait_for_vlm(cd.VLM_WAIT_S):
            return "the VLM did not answer within %d s" % cd.VLM_WAIT_S
        self.serving = True
        return None

    def down(self):
        """None when the VLM is down, else the reason it may not be."""
        if not self.maybe_up:
            return None
        self.say("critic: stopping the VLM for the Qwen redo")
        rc = _cd().story_server("stop")
        self.serving = False
        if rc != 0:
            return "bin/story-server stop exited %d" % rc
        self.maybe_up = False
        return None

    def restore(self, interrupted):
        """Back to the state before the first judge phase; never raises. After an interrupt the stop runs detached
        in its own session, so it outlives the movie-ui's cancel sweep."""
        try:
            cd = _cd()
            if self.original is None or self.hands_off:
                return
            if self.original == "STOPPED":
                if not self.maybe_up:
                    return
                if interrupted:
                    sys.stderr.write("critic: interrupted; stopping the VLM in its own session\n")
                    sys.stderr.flush()
                    subprocess.Popen([cd.STORY_SERVER, "stop"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
                    return
                self.say("critic: stopping the VLM (it was stopped before the critic started)")
                rc = cd.story_server("stop")
                if rc != 0:
                    sys.stderr.write("critic: warning: bin/story-server stop exited %d; the VLM may still hold its "
                                     "memory\n" % rc)
                    sys.stderr.flush()
                return
            if not self.serving:
                cd.restore_story_server()
                self.say("critic: restarting the VLM in the background (it was serving before the critic started)")
        except Exception as e:
            sys.stderr.write("critic: warning: restoring the VLM failed: %s\n" % e)
            sys.stderr.flush()


# ---------------------------------------------------------------------------
# edit_with_critic (spec 2.4)
# ---------------------------------------------------------------------------

def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def _install_interrupt_handlers():
    """Spec 2.4.6: on the main thread, SIGTERM and SIGHUP raise KeyboardInterrupt while the critic runs, when their
    handler is SIG_DFL (bin/ltx-movie installs none; bin/seed-edit's own handlers stay). Returns [(signal, the
    previous handler)] for _restore_handlers."""
    saved = []
    if threading.current_thread() is not threading.main_thread():
        return saved
    for sig in (signal.SIGTERM, signal.SIGHUP):
        if signal.getsignal(sig) is signal.SIG_DFL:
            saved.append((sig, signal.signal(sig, _raise_interrupt)))
    return saved


def _restore_handlers(saved):
    for sig, previous in saved:
        signal.signal(sig, previous)


def edit_with_critic(qe, model_id, loras, jobs, width, height, skill, work_dir, rounds=DEFAULT_ROUNDS, total=None,
                     on_result=None, on_verdict=None, on_best=None, noun="job", tag="seed-edit", say=None):
    """(results, failure) of round 0, exactly as qe.run_jobs returns them; between Qwen batches the VLM judges every
    ok output, the jobs scored below PASS_SCORE are re-edited with critic_seed seeds (at most rounds redo batches)
    and each job's output_path ends as its best-scored attempt (spec 2.4). on_result goes to the round-0 run_jobs
    only; on_verdict(n, block) is called whenever job n's critic block changes; on_best(n, output_path) after a
    better redo attempt replaced output_path. qe is the caller's qwen_edit module; jobs are not changed."""
    say = _say if say is None else say
    total = len(jobs) if total is None else total

    def plural(k):
        return noun if k == 1 else noun + "s"

    results, failure = qe.run_jobs(model_id, loras, jobs, width, height, skill, work_dir, on_result=on_result,
                                   noun=noun)
    if failure is not None:
        say("critic: not run; the %s batch failed" % noun)
        return results, failure
    ok = [r["n"] for r in results if r["status"] == "ok"]
    if not ok:
        say("critic: not run; no %s produced an image" % noun)
        return results, failure
    by_n = dict((job["n"], job) for job in jobs)
    critic_dir = os.path.join(work_dir, CRITIC_DIR)
    os.makedirs(critic_dir, exist_ok=True)

    def stem(n):
        return os.path.splitext(os.path.basename(by_n[n]["output_path"]))[0]

    def image(n, k):
        return os.path.join(critic_dir, "%s.r%d.png" % (stem(n), k))

    def stage(n, k):
        return os.path.join(critic_dir, "%s.r%d.pending.png" % (stem(n), k))

    for n in ok:
        for old in glob.glob(os.path.join(critic_dir, stem(n) + ".r*.png")):
            os.remove(old)
    state = {}
    for n in ok:
        state[n] = {"attempts": [{"round": 0, "seed": by_n[n]["seed"], "score": None, "defects": [], "note": None}],
                    "best": None, "reason": None, "seed_used": by_n[n]["seed"], "line": None}

    def best_of(n):
        s = state[n]
        return s["attempts"][s["best"]] if s["best"] is not None else None

    def status_of(n):
        best = best_of(n)
        if best is None:
            return "unjudged"
        return "passed" if best["score"] >= PASS_SCORE else "flagged"

    def block(n):
        s, best = state[n], best_of(n)
        return {"status": status_of(n), "score": best["score"] if best else None,
                "defects": list(best["defects"]) if best else [], "reason": s["reason"], "seed_used": s["seed_used"],
                "pass_score": PASS_SCORE,
                "attempts": [dict(a, defects=list(a["defects"])) for a in s["attempts"]]}

    def verdicts(ns):
        if on_verdict is not None:
            for n in ns:
                on_verdict(n, block(n))

    def d_text(att):
        return "; ".join(att["defects"]) or "no defect named"

    def emit(n, word, detail):
        state[n]["line"] = word
        say("critic %d/%d: %s (%s)" % (n, total, word, detail))

    def ok_line(n, att):
        emit(n, "ok", "score %d, attempt %d" % (att["score"], att["round"] + 1))

    def flagged_line(n):
        best = best_of(n)
        emit(n, "flagged", "best score %d of %d attempts: %s" % (best["score"], len(state[n]["attempts"]),
                                                                  d_text(best)))

    def not_judged(n, r, reason):
        s = state[n]
        s["attempts"][-1]["note"] = "not judged: " + reason
        if s["best"] is None:
            s["reason"] = reason
        if r == 0:
            emit(n, "unjudged", reason)

    def install(n, k):
        out = by_n[n]["output_path"]
        shutil.copyfile(image(n, k), out + ".critic-tmp")
        os.replace(out + ".critic-tmp", out)

    session = VLMSession(say)
    saved = _install_interrupt_handlers()
    redo_runs = 0

    def judge_phase(r, phase):
        """Judge the newest attempt of every job in phase; True when the loop must stop after this phase."""
        say("critic: judging %d %s with the VLM (round %d)" % (len(phase), plural(len(phase)), r))
        reason = session.up()
        if reason is not None:
            for n in phase:
                not_judged(n, r, reason)
            verdicts(phase)
            return True
        for i, n in enumerate(phase):
            s = state[n]
            att = s["attempts"][-1]
            path = by_n[n]["output_path"] if r == 0 else image(n, r)
            try:
                v = judge_image(path, by_n[n]["source"] if JUDGE_WITH_SEED else None)
            except VLMUnavailable as e:
                for m in phase[i:]:
                    not_judged(m, r, str(e))
                verdicts(phase)
                return True
            except JudgeError as e:
                not_judged(n, r, str(e))
                continue
            att["score"], att["defects"] = v["score"], v["defects"]
            best = best_of(n)
            if best is None or v["score"] > best["score"]:
                if r > 0:
                    install(n, r)
                    if on_best is not None:
                        on_best(n, by_n[n]["output_path"])
                s["best"] = len(s["attempts"]) - 1
                s["seed_used"] = att["seed"]
                s["reason"] = v["reason"]
            if v["score"] >= PASS_SCORE:
                ok_line(n, att)
            elif r < rounds:
                emit(n, "redo", "score %d: %s" % (v["score"], d_text(att)))
            else:
                flagged_line(n)
        verdicts(phase)
        return False

    def redo_phase(rr, active):
        """Re-edit the active jobs with new seeds; (the jobs whose redo output is ok, stop), or (None, True) when the
        redo did not run."""
        nonlocal redo_runs
        reason = session.down()
        if reason is not None:
            say("critic: redo round %d of %d not run: %s" % (rr, rounds, reason))
            return None, True
        refs = max(len(by_n[n].get("sources") or [by_n[n]["source"]]) for n in active)
        try:
            qe.wait_for_memory(qe.memory_floor(model_id, refs), qe.label(model_id), tag=tag)
        except qe.Unavailable as e:
            say("critic: redo round %d of %d not run: %s" % (rr, rounds, e))
            return None, True
        for n in active:
            if len(state[n]["attempts"]) == 1:
                shutil.copyfile(by_n[n]["output_path"], image(n, 0))
        redo_jobs = []
        for n in active:
            seed = critic_seed(by_n[n]["seed"], rr, n)
            redo_jobs.append(dict(by_n[n], seed=seed, stage_path=stage(n, rr), output_path=image(n, rr)))
            state[n]["attempts"].append({"round": rr, "seed": seed, "score": None, "defects": [], "note": None})
        say("critic: redo round %d of %d: %s %s with new seeds" % (rr, rounds, plural(len(active)),
                                                                    ", ".join(str(n) for n in active)))
        try:
            res, fail = qe.run_jobs(model_id, loras, redo_jobs, width, height, skill, work_dir, noun=noun)
        except qe.Unavailable as e:
            res, fail = [], str(e)
        redo_runs += 1
        status = dict((x["n"], x["status"]) for x in res)
        next_phase, noted = [], []
        for n in active:
            if status.get(n) == "ok":
                next_phase.append(n)
                continue
            state[n]["attempts"][-1]["note"] = ("blocked by the content screen" if status.get(n) == "blocked"
                                                else "the edit failed")
            noted.append(n)
        verdicts(noted)
        if fail is not None:
            say("critic: redo round %d failed: %s; keeping the best attempts" % (rr, fail))
            return next_phase, True
        return next_phase, False

    interrupted = False
    try:
        r, phase, stop = 0, sorted(ok), False
        while True:
            if phase:
                stop = judge_phase(r, phase) or stop
            active = sorted(n for n in state if best_of(n) is not None and best_of(n)["score"] < PASS_SCORE)
            if stop or r == rounds or not active:
                break
            phase, stop = redo_phase(r + 1, active)
            if phase is None:
                break
            r += 1
        for n in sorted(state):
            final = status_of(n)
            if state[n]["line"] == LINE_STATES[final]:
                continue
            if final == "passed":
                ok_line(n, best_of(n))
            elif final == "flagged":
                flagged_line(n)
            else:
                emit(n, "unjudged", state[n]["reason"])
        verdicts(sorted(state))
        counts = [status_of(n) for n in state]
        say("critic: done: %d passed, %d flagged, %d unjudged; %d redo round(s) run"
            % (counts.count("passed"), counts.count("flagged"), counts.count("unjudged"), redo_runs))
        return results, failure
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        for path in glob.glob(os.path.join(critic_dir, "*.pending.png")):
            try:
                os.remove(path)
            except OSError:
                pass
        for job in jobs:
            try:
                os.remove(job["output_path"] + ".critic-tmp")
            except OSError:
                pass
        session.restore(interrupted)
        _restore_handlers(saved)
````

- [ ] **Step 4: Run the tests.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py 2>&1 | tail -3`

Expected: `2 failed, 18 passed`. The two failures are `test_ict12_the_calibration_cli` and `test_ict13_import_hygiene`, both `FileNotFoundError` for `bin/image-critic`. Any other failure: stop.

- [ ] **Step 5: Create `bin/image-critic`** with exactly this content (spec 2.7; R2), then make it executable:

````python
#!/usr/bin/env python3
"""image-critic -- score images for broken bodies with the local VLM, to calibrate image_critic.PASS_SCORE
(docs/superpowers/specs/2026-11-27-image-critic-design.md, Section 2.7).

  bin/image-critic score FILE [FILE ...] [--seed PATH] [--pass-score N] [--json]

Needs the VLM serving (bin/story-server mlx-vision); it starts and stops nothing and writes nothing. --seed sends
that photo first, as the edit's source. Exit 0 every file judged; 1 at least one file not judged; 2 a usage error, a
missing file or the VLM not serving. Python 3.9 and 3.13.
"""

import argparse
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import image_critic as ic  # noqa: E402


def _defects_text(defects):
    return "; ".join(defects) or "no defect named"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="image-critic", description="Score images for broken bodies with the "
                                     "local VLM, to calibrate image_critic.PASS_SCORE.")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True
    score = sub.add_parser("score", help="judge each FILE and print its score, verdict and defects")
    score.add_argument("files", nargs="+", metavar="FILE")
    score.add_argument("--seed", default=None, metavar="PATH")
    score.add_argument("--pass-score", dest="pass_score", type=int, default=ic.PASS_SCORE, metavar="N")
    score.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.pass_score <= 10:
        print("Error: --pass-score must be an integer from 1 to 10", file=sys.stderr)
        return 2
    for path in ([args.seed] if args.seed is not None else []) + args.files:
        if not os.path.isfile(path):
            print("Error: %s is not a file" % path, file=sys.stderr)
            return 2
    if not ic.vlm_ready():
        print("Error: the VLM is not serving at %s; start it with bin/story-server mlx-vision" % ic.vlm_models_url(),
              file=sys.stderr)
        return 2
    rows, down = [], None
    for path in args.files:
        if down is not None:
            rows.append((path, None, down))
            continue
        try:
            rows.append((path, ic.judge_image(path, args.seed), None))
        except ic.VLMUnavailable as e:
            down = str(e)
            rows.append((path, None, down))
        except ic.JudgeError as e:
            rows.append((path, None, str(e)))
    counts = {"pass": 0, "fail": 0, "unjudged": 0}
    for path, v, error in rows:
        if v is None:
            word = "unjudged"
        else:
            word = "pass" if v["score"] >= args.pass_score else "fail"
        counts[word] += 1
        if args.json:
            print(json.dumps({"path": path, "score": v["score"] if v else None, "verdict": word,
                              "defects": v["defects"] if v else [], "reason": v["reason"] if v else None,
                              "error": error}, sort_keys=True))
        elif v is None:
            print("%s: UNJUDGED: %s" % (path, error))
        else:
            print("%s: score %d %s: %s -- %s" % (path, v["score"], word.upper(), _defects_text(v["defects"]),
                                                  v["reason"] or "-"))
    if not args.json:
        print("pass score %d: %d pass, %d fail, %d unjudged" % (args.pass_score, counts["pass"], counts["fail"],
                                                                 counts["unjudged"]))
    return 1 if counts["unjudged"] else 0


if __name__ == "__main__":
    sys.exit(main())
````

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && chmod 755 bin/image-critic && ls -l bin/image-critic
```

Expected: `-rwxr-xr-x`.

- [ ] **Step 6: Run the tests.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py 2>&1 | tail -1`

Expected: `20 passed`.

- [ ] **Step 7: QET11's expected `NEW_PY` tail (spec 6.3, Task 1).** First the pin, so it fails:

Edit `tests/test_qwen_edit.py`. Old:

````python
        "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
        "tests/test_movie_ui_shots_seed.py"]
````

New:

````python
        "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
        "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py"]
````

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files 2>&1 | tail -1`

Expected: `1 failed`.

- [ ] **Step 8: `NEW_PY` gains the three files (spec 6.3, Task 1).**

Edit `tests/test_movie_ui_builder.py`. Old:

````python
          "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
          "tests/test_movie_ui_shots_seed.py")
````

New:

````python
          "tests/test_movie_ui_qwen_edit.py", "tests/test_ltx_movie_shots_seed.py",
          "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py")
````

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py tests/test_movie_ui_seedgen.py::test_sgt34_the_new_python_files_and_the_tool_imports 2>&1 | tail -1`

Expected: `45 passed`. This runs `test_mut25` (which now compiles and scans the three new files on 3.9 and 3.13) and `test_mut26` (still green: no pinned file changed).

- [ ] **Step 9: Compile check and pinned-file check.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' image_critic.py bin/image-critic tests/test_image_critic.py; done
git diff --quiet a87e7992ff17c351aa75e47980977d81b1138e03 -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pinned files unchanged"
```

Expected: `compiled 3`, twice; `pinned files unchanged`.

- [ ] **Step 10: Commit C1.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git add image_critic.py bin/image-critic tests/test_image_critic.py tests/test_movie_ui_builder.py tests/test_qwen_edit.py && git diff --cached --name-only && git ls-files -s bin/image-critic && git commit -m "image critic: image_critic.py (judge_image, VLMSession, edit_with_critic) and the bin/image-critic calibration CLI" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: the five names, each prefixed `qwen-agent-workspace/`; `100755 … bin/image-critic`; one commit. If the mode is `100644`, run `git update-index --chmod=+x bin/image-critic` before committing.

---

### Task 2: the tool hooks, `bin/seed-edit` and `bin/ltx-movie` (commit C2; spec 2.8, 2.9, 6.2; ICT14-ICT19; Review Focus 4-5)

**Files:**
- Modify `qwen-agent-workspace/bin/seed-edit`: the docstring (:6-7, :21-22, :44-46), `parse` (:99-107), `check_args` (:110-168), `critic_verdict` after `finish` (:352-363), `run_qwen` (:423-434).
- Modify `qwen-agent-workspace/bin/ltx-movie` (a `PIPELINE_FILES` member): the docstring after the seed-edit paragraph (:113-120), the two flags after `--seed-edit-lora` (:447-450), `_image_critic` after `_qwen_edit` (:1000-1003), `_resolve_critic` after `_resolve_seed_context` (:1288-1322), `main` after the `_resolve_seed_context` block (:4485-4487), `_phase2_shots_seed`'s closures after `on_result` (:3057-3068) and its batch call (:3077-3078).
- Modify `qwen-agent-workspace/tests/test_seed_edit_tool.py` (ICT14-ICT16, appended).
- Modify `qwen-agent-workspace/tests/test_ltx_movie_shots_seed.py` (the docstring, two imports, ICT17-ICT19 and Review Focus 4-5, appended).
- `bin/seed-edit`'s top-level imports stay exactly SGT34's list (`image_critic` is imported inside `run_qwen`).

**Interfaces:**
- Consumes (Task 1): `image_critic.DEFAULT_ROUNDS`, `PASS_SCORE`, `critic_seed`, `edit_with_critic(...)` exactly as in Task 1's Interfaces; `tests/test_image_critic.py`'s `FakeCD` and `verdict`.
- Consumes (existing): `bin/seed-edit`'s `Refusal`, `say`, `write_run(ctx)`, `finish(ctx, n, status, seconds=None)`, `SAFETY_SKILL`; `bin/ltx-movie`'s `WS`, `_qwen_edit()`, `_image_fit()`, `_sha256_file(path)`, `_write_shots_seed_record(path, entries, total)`, `SHOTS_SEED_EDIT_SKILL`; the tests' `env`, `run_tool`, `record_of`, `statuses`, `cand`, `plain`, `png`, `mflux_venv`, `mflux_weights`, `stub_calls`, `BASE`, `QBASE`, `RUN`, `R1`, `PROMPT` (`test_seed_edit_tool.py`) and `clean_env`, `_phase_args`, `_FakeShotsQwenEdit`, `_write_story`, `_record`, `_sha`, `_jobs`, `_still`, `_parse`, `ENTRY_KEYS`, `movie` (`test_ltx_movie_shots_seed.py`).
- Produces:
  - `bin/seed-edit`: options `--critic`, `--critic-rounds N`; `check_args` returns two more keys, `"critic": bool` and `"critic_rounds": None | int`; `critic_verdict(ctx, n, block)`; with `--critic`, `run.json` gains `"critic": {"rounds", "pass_score"}` and each candidate's `"critic"` block. Task 4's `seed_edit_argv` emits `--critic`.
  - `bin/ltx-movie`: `args.critic: bool`, `args.critic_rounds: None | int`; `_image_critic()`; `_resolve_critic(args) -> 0 | 2`; `--critic` and `--critic-rounds` in `--help` (Task 4's V1 rule 18 and the help fixture rely on them).

- [ ] **Step 1: Write the failing `bin/seed-edit` tests (ICT14-ICT16).**

Edit `tests/test_seed_edit_tool.py`. Old:

````python
    mp.setattr(tool, "run", interrupted)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R1)
    assert (code, killed) == (130, [True])
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert capsys.readouterr().err == "seed-edit: interrupted\n"
````

New:

````python
    mp.setattr(tool, "run", interrupted)
    code, run_dir = run_tool(env, "--qwen-model", "qwen21-q4", model="qwen", run=R1)
    assert (code, killed) == (130, [True])
    record = record_of(run_dir)
    assert (record["state"], record["error"]) == ("cancelled", "interrupted")
    assert capsys.readouterr().err == "seed-edit: interrupted\n"


# --- ICT14-ICT16 (image critic spec 2.8, 6.2): --critic and --critic-rounds -----------------------------------------

CRITIC_RANGE = "--critic-rounds must be an integer from 0 to 4"
CRITIC_CASES = [
    (BASE + ["--critic"], "--critic is only for --model qwen"),
    (QBASE + ["--critic-rounds", "1"], "--critic-rounds needs --critic"),
    (QBASE + ["--critic", "--critic-rounds", "5"], CRITIC_RANGE),
    (QBASE + ["--critic", "--critic-rounds", "x"], CRITIC_RANGE),
    (QBASE + ["--critic", "--critic-rounds", "-1"], CRITIC_RANGE),
    (["--probe", "--critic"], "--probe takes no other options"),
    (["--probe", "--critic-rounds", "1"], "--probe takes no other options"),
]


@pytest.mark.parametrize("argv,message", CRITIC_CASES, ids=["case%d" % (i + 1) for i in range(len(CRITIC_CASES))])
def test_ict14_the_critic_option_rules(env, capsys, argv, message):
    source = png(os.path.join(env["tmp"], "src.png"), (128, 128))
    run_dir = os.path.join(env["tmp"], "runs", RUN)
    argv = [source if a == "SRC" else run_dir if a == "RUNDIR" else a for a in argv]
    assert env["tool"].main(argv) == 2
    assert capsys.readouterr() == ("", "Error: %s\n" % message)
    assert not os.path.exists(run_dir)


def test_ict14_the_cleaned_critic_options(env):
    tool = env["tool"]

    def opts(*extra):
        got = tool.check_args(tool.parse(["--source", "s", "--prompt", PROMPT, "--model", "qwen", "--run-dir", "r",
                                          "--seed", "1"] + list(extra)))
        return got["critic"], got["critic_rounds"]

    assert opts() == (False, None)
    assert opts("--critic") == (True, None)
    assert opts("--critic", "--critic-rounds", "0") == (True, 0)
    assert opts("--critic", "--critic-rounds", "4") == (True, 4)


def test_ict15_without_critic_the_run_is_unchanged(env, capsys):
    env["mp"].delitem(sys.modules, "image_critic", raising=False)
    mflux_venv(env)
    mflux_weights(env)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "2", "--seed", "100", model="qwen")
    assert code == 0
    record = record_of(run_dir)
    assert "critic" not in record
    assert [list(c) for c in record["candidates"]] == [["n", "seed", "status", "seconds"]] * 2
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("critic")]
    assert "image_critic" not in sys.modules
    assert not os.path.exists(os.path.join(run_dir, "work", "critic"))


def test_ict16_the_critic_wiring(env, capsys):
    py, _venv = mflux_venv(env)
    mflux_weights(env)
    seen = []
    fake = types.ModuleType("image_critic")
    fake.DEFAULT_ROUNDS, fake.PASS_SCORE = 2, 7

    def edit_with_critic(qe, model_id, loras, jobs, width, height, skill, work_dir, rounds=2, total=None,
                         on_result=None, on_verdict=None, on_best=None, noun="job", tag="seed-edit", say=None):
        seen.append({"qe": qe, "model_id": model_id, "loras": loras, "jobs": [dict(j) for j in jobs],
                     "size": (width, height), "skill": skill, "work_dir": work_dir, "rounds": rounds, "total": total,
                     "noun": noun, "tag": tag, "on_best": on_best, "say": say})
        for job in jobs:
            on_result({"n": job["n"], "output_path": job["output_path"], "status": "ok", "seconds": 1.0})
        on_verdict(1, {"status": "flagged"})
        return [], None

    fake.edit_with_critic = edit_with_critic
    env["mp"].setitem(sys.modules, "image_critic", fake)
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "3", "--seed", "100", "--critic",
                             model="qwen")
    assert code == 0
    work = os.path.join(run_dir, "work")
    (call,) = seen
    assert call["qe"] is env["qe"] and call["say"] is env["tool"].say
    assert (call["model_id"], call["loras"], call["size"], call["skill"], call["work_dir"]) == (
        "qwen2511-q4", [], (1024, 672), "seed_edit", work)
    assert call["jobs"] == [{"n": n, "seed": 100 + n, "prompt": PROMPT, "source": os.path.join(work, "source.png"),
                             "stage_path": os.path.join(work, "cand_%02d.pending.png" % n),
                             "output_path": cand(run_dir, n)} for n in (1, 2, 3)]
    assert (call["rounds"], call["total"], call["noun"], call["tag"], call["on_best"]) == (
        2, 3, "candidate", "seed-edit", None)
    record = record_of(run_dir)
    assert record["critic"] == {"rounds": 2, "pass_score": 7}
    assert record["candidates"][0]["critic"] == {"status": "flagged"}
    assert ["critic" in c for c in record["candidates"]] == [True, False, False]
    assert [c["seed"] for c in record["candidates"]] == [101, 102, 103]
    assert statuses(run_dir) == ["ok"] * 3 and stub_calls(py) == []
    assert plain([line for line in capsys.readouterr().out.splitlines() if line.startswith("candidate ")]) == [
        "candidate 1/3 ok Ss", "candidate 2/3 ok Ss", "candidate 3/3 ok Ss"]
    del seen[:]
    code, run_dir = run_tool(env, "--qwen-model", "qwen2511-q4", "--candidates", "1", "--seed", "100", "--critic",
                             "--critic-rounds", "0", model="qwen", run=R1)
    assert code == 0 and seen[0]["rounds"] == 0 and seen[0]["total"] == 1
    assert record_of(run_dir)["critic"] == {"rounds": 0, "pass_score": 7}
````

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py -k "ict14 or ict15 or ict16" 2>&1 | tail -1`

Expected: `9 failed, 1 passed, 93 deselected`. The failures are `SystemExit` from argparse (`unrecognized arguments: --critic`); `test_ict15_without_critic_the_run_is_unchanged` passes, because it pins today's behaviour.

- [ ] **Step 3: `bin/seed-edit`, the docstring (spec 2.8.1).** Three Edits.

(a) Edit `bin/seed-edit`. Old:

````python
                [--strength S] [--candidates N] [--seed N] --run-dir DIR
````

New:

````python
                [--strength S] [--candidates N] [--seed N] [--critic [--critic-rounds N]] --run-dir DIR
````

(b) Edit `bin/seed-edit`. Old:

````python
"reason"}} and loads nothing.
````

New:

````python
"reason"}} and loads nothing. --critic (Qwen models only) has the local VLM judge every ok
candidate for broken bodies between Qwen batches and re-edit the failures with new seeds, at most
--critic-rounds N (0 to 4, default 2) more times; the best attempt stays cand_NN.png and run.json
records each candidate's critic verdict (docs/superpowers/specs/2026-11-27-image-critic-design.md).
````

(c) Edit `bin/seed-edit`. Old:

````python
movie_ui_seedgen and qwen_edit; PIL, psutil, torch, z_image_skill, content_safety and
character_dataset are imported inside the functions that use them.
````

New:

````python
movie_ui_seedgen and qwen_edit; PIL, psutil, torch, z_image_skill, content_safety,
character_dataset and image_critic are imported inside the functions that use them.
````

- [ ] **Step 4: `bin/seed-edit`, `parse` and `check_args` (spec 2.8.2, 2.8.3).** Three Edits.

(a) Edit `bin/seed-edit`. Old:

````python
    parser.add_argument("--probe", action="store_true")
    return parser.parse_args(argv)
````

New:

````python
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--critic", action="store_true")
    parser.add_argument("--critic-rounds", type=str)
    return parser.parse_args(argv)
````

(b) Edit `bin/seed-edit`. Old:

````python
    given = (args.source, args.prompt, args.model, args.strength, args.candidates, args.seed, args.run_dir,
             args.qwen_model, args.lora)
````

New:

````python
    given = (args.source, args.prompt, args.model, args.strength, args.candidates, args.seed, args.run_dir,
             args.qwen_model, args.lora, args.critic_rounds, True if args.critic else None)
````

(c) Edit `bin/seed-edit`. Old:

````python
        raise Refusal("--seed must be an integer from 0 to 2147483647")
    return {"source": args.source, "prompt": args.prompt, "model": args.model, "strength": strength,
            "candidates": candidates, "seed": seed, "run_dir": os.path.abspath(args.run_dir),
            "qwen_model": qwen_model, "loras": loras}
````

New:

````python
        raise Refusal("--seed must be an integer from 0 to 2147483647")
    if args.critic_rounds is not None and not args.critic:
        raise Refusal("--critic-rounds needs --critic")
    if args.critic and args.model != "qwen":
        raise Refusal("--critic is only for --model qwen")
    if args.critic_rounds is not None and not (re.fullmatch(r"[0-9]+", args.critic_rounds)
                                               and int(args.critic_rounds) <= 4):
        raise Refusal("--critic-rounds must be an integer from 0 to 4")
    return {"source": args.source, "prompt": args.prompt, "model": args.model, "strength": strength,
            "candidates": candidates, "seed": seed, "run_dir": os.path.abspath(args.run_dir),
            "qwen_model": qwen_model, "loras": loras, "critic": bool(args.critic),
            "critic_rounds": None if args.critic_rounds is None else int(args.critic_rounds)}
````

- [ ] **Step 5: `bin/seed-edit`, `critic_verdict` and `run_qwen` (spec 2.8.4, 2.8.5; R9).** Two Edits.

(a) Edit `bin/seed-edit`. Old:

````python
        say("candidate %d/%d %s %.1fs" % (n, len(cands), status, cand["seconds"]))


def fail_rest(ctx):
````

New:

````python
        say("candidate %d/%d %s %.1fs" % (n, len(cands), status, cand["seconds"]))


def critic_verdict(ctx, n, block):
    """Image critic spec 2.8: candidate n's critic block, written to run.json whenever it changes."""
    ctx["record"]["candidates"][n - 1]["critic"] = block
    write_run(ctx)


def fail_rest(ctx):
````

(b) Edit `bin/seed-edit`. Old:

````python
    _results, failure = qe.run_jobs(entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL,
                                    ctx["work"], on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
                                    noun="candidate")
    return failure
````

New:

````python
    if not opts["critic"]:
        _results, failure = qe.run_jobs(entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL,
                                        ctx["work"], on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
                                        noun="candidate")
        return failure
    import image_critic
    rounds = image_critic.DEFAULT_ROUNDS if opts["critic_rounds"] is None else opts["critic_rounds"]
    rec["critic"] = {"rounds": rounds, "pass_score": image_critic.PASS_SCORE}
    write_run(ctx)
    _results, failure = image_critic.edit_with_critic(
        qe, entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL, ctx["work"],
        rounds=rounds, total=len(rec["candidates"]),
        on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
        on_verdict=lambda n, block: critic_verdict(ctx, n, block), noun="candidate", tag="seed-edit", say=say)
    return failure
````

- [ ] **Step 6: Run the `bin/seed-edit` tests.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_movie_ui_seedgen.py::test_sgt34_the_new_python_files_and_the_tool_imports 2>&1 | tail -1`

Expected: `104 passed` (the whole file, unedited tests included, plus SGT34).

- [ ] **Step 7: Write the failing `bin/ltx-movie` tests (ICT17-ICT19, Review Focus 4 and 5).** Three Edits to `tests/test_ltx_movie_shots_seed.py`.

(a) Edit `tests/test_ltx_movie_shots_seed.py`. Old:

````python
server or touches port 8177 or 8178. Stdlib, PIL and pytest.
"""
````

New:

````python
server or touches port 8177 or 8178. Stdlib, PIL and pytest.

ICT17-ICT19 (docs/superpowers/specs/2026-11-27-image-critic-design.md, 6.2) pin --critic: _resolve_critic's rules,
a shots seed run whose panel 2 the critic re-edits (the real image_critic with test_image_critic's FakeCD, so no
VLM is reached) and the unchanged run without the flag.
"""
````

(b) Edit `tests/test_ltx_movie_shots_seed.py`. Old:

````python
import movie_ui_testutil as mt
import qwen_edit
import test_seed_edit_tool as st
````

New:

````python
import movie_ui_testutil as mt
import image_critic
import qwen_edit
import test_image_critic as ict
import test_seed_edit_tool as st
````

(c) Edit `tests/test_ltx_movie_shots_seed.py`. Old:

````python
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]] and len(fake.calls["wait_for_memory"]) == 2
````

New:

````python
    fake.reset()
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2, 3]] and len(fake.calls["wait_for_memory"]) == 2


# --- ICT17-ICT19 (image critic spec 2.9, 6.2): --critic in shots mode with a seed image ------------------------

CRITIC_NEEDS = ("Error: --critic needs --shots with --seed-image and a Qwen --seed-edit-model ID: the image critic "
                "judges the shots seed edits only\n")


def test_ict17_resolve_critic(clean_env, capsys, monkeypatch):
    tmp = clean_env["tmp"]
    seed = st.png(os.path.join(tmp, "seed.png"), (64, 64))
    edit = {"qwen_model": "qwen21-q4", "loras": []}

    def args_of(*extra, shots=True, seed_image=True, seed_edit=edit, seed_context=None):
        argv = (["--shots"] if shots else []) + (["--seed-image", seed] if seed_image else []) + list(extra)
        args = _parse(*argv)
        args.seed_edit, args.seed_context = seed_edit, seed_context
        return args

    cases = [(args_of("--critic-rounds", "1"), "Error: --critic-rounds needs --critic\n"),
             (args_of("--critic", "--critic-rounds", "5"), "Error: --critic-rounds must be an integer from 0 to 4\n"),
             (args_of("--critic", "--critic-rounds", "-1"), "Error: --critic-rounds must be an integer from 0 to 4\n"),
             (args_of("--critic", seed_context={"mode": "still", "order": "seed-first"}),
              "Error: --critic cannot be combined with --seed-context: a redone still would change every later "
              "panel's context picture\n"),
             (args_of("--critic", shots=False), CRITIC_NEEDS),
             (args_of("--critic", seed_image=False), CRITIC_NEEDS),
             (args_of("--critic", seed_edit=None), CRITIC_NEEDS)]
    for args, text in cases:
        assert movie._resolve_critic(args) == 2, text
        assert capsys.readouterr().err == text
    assert movie._resolve_critic(args_of()) == 0
    args = args_of("--critic")
    assert movie._resolve_critic(args) == 0 and args.critic_rounds is None
    args = args_of("--critic", "--critic-rounds", "3")
    assert movie._resolve_critic(args) == 0 and args.critic_rounds == 3
    assert movie._resolve_critic(args_of("--critic", "--critic-rounds", "0")) == 0
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(movie, "WS", tmp)
    assert movie._resolve_critic(args_of("--critic")) == 2
    assert capsys.readouterr().err == (
        "Error: --critic needs %s, which this workspace does not have\n" % os.path.join(tmp, "image_critic.py"))
    text = movie.build_parser().format_help()
    assert "--critic" in text and "--critic-rounds" in text


class _ColourQwenEdit(_FakeShotsQwenEdit):
    """ICT18: run_jobs writes a 64x64 PNG of colour (seed % 256, 0, 40 * n) for every job, reports it ok and calls
    on_result only when it is given (the critic's redo batches pass none)."""

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        self.calls["run_jobs"].append({"model_id": model_id, "loras": loras, "jobs": [dict(j) for j in jobs],
                                       "size": (width, height), "skill": skill, "work_dir": work_dir, "noun": noun})
        results = []
        for job in jobs:
            Image.new("RGB", (64, 64), (job["seed"] % 256, 0, 40 * job["n"])).save(job["output_path"])
            result = {"n": job["n"], "output_path": job["output_path"], "status": "ok", "seconds": 12.5}
            if on_result is not None:
                on_result(dict(result))
            results.append(result)
        return results, None


def _critic_fakes(monkeypatch, fake):
    """movie._qwen_edit is fake and movie._image_critic the real image_critic, whose _cd is a fresh
    test_image_critic.FakeCD; returns (cd, the argv of every detached Popen)."""
    cd, popens = ict.FakeCD([]), []
    monkeypatch.setattr(movie, "_qwen_edit", lambda: fake)
    monkeypatch.setattr(image_critic, "_cd", lambda: cd)
    monkeypatch.setattr(image_critic, "subprocess", types.SimpleNamespace(
        Popen=lambda argv, **kw: popens.append(argv), DEVNULL=-3))
    monkeypatch.setattr(movie, "_image_critic", lambda: image_critic)
    return cd, popens


def test_ict18_shots_with_the_critic_end_to_end(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    fake = _ColourQwenEdit()
    cd, _popens = _critic_fakes(monkeypatch, fake)
    story_dir = _write_story(tmp)
    work = os.path.join(story_dir, "seed_edits")
    redo_seed = image_critic.critic_seed(3, 1, 2)
    cd.replies.update({os.path.join(work, "panel_01.png"): [ict.verdict(8)],
                       os.path.join(work, "panel_02.png"): [ict.verdict(3, ["fused left hand"])],
                       os.path.join(work, "panel_03.png"): [ict.verdict(8)],
                       os.path.join(work, "critic", "panel_02.r1.png"): [ict.verdict(9)]})
    assert movie._phase2_shots_seed(_phase_args(tmp, critic=True, critic_rounds=None)) == 0
    assert _jobs(fake) == [[1, 2, 3], [2]]
    assert fake.calls["run_jobs"][1]["jobs"][0]["seed"] == redo_seed
    assert [call[2] for call in fake.calls["wait_for_memory"]] == ["ltx-movie", "ltx-movie"]
    with Image.open(_still(story_dir, 2)) as img:
        assert img.size == (1408, 896) and img.getpixel((704, 448)) == (redo_seed % 256, 0, 80)
    with Image.open(_still(story_dir, 1)) as img:
        assert img.getpixel((704, 448)) == (3, 0, 40)
    entries = _record(story_dir)["panels"]
    two = entries[1]
    assert list(two) == ENTRY_KEYS + ["critic"]
    assert (two["seed"], two["critic"]["seed_used"], two["critic"]["status"]) == (3, redo_seed, "passed")
    assert two["still_sha256"] == _sha(_still(story_dir, 2))
    assert [e["critic"]["status"] for e in entries] == ["passed"] * 3
    assert [e["critic"]["seed_used"] for e in (entries[0], entries[2])] == [3, 3]
    out = capsys.readouterr().out.splitlines()
    assert "panel 2 -> %s (critic: a better attempt of the Qwen edit of the seed)" % _still(story_dir, 2) in out
    assert "critic 2/3: redo (score 3: fused left hand)" in out and "critic 2/3: ok (score 9, attempt 2)" in out
    assert out[-1] == "seed edits: 3 panel stills written"
    assert movie._phase2_shots_seed(_phase_args(tmp, critic=True, critic_rounds=None)) == 0
    assert len(fake.calls["run_jobs"]) == 2
    assert capsys.readouterr().out.splitlines() == [
        "seed edits: reusing the stills of panels 1,2,3 (recorded edits of the same seed image, prompt, seed and "
        "settings)",
        "seed edits: every panel's still is a recorded edit of the same seed image, prompt, seed and settings; "
        "nothing to edit"]


class _InterruptedRedoQwenEdit(_ColourQwenEdit):
    """Review Focus 4: the critic's redo batch (the call without on_result) writes its stage file, then raises
    KeyboardInterrupt, as a movie-ui Cancel during a redo does."""

    def run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None,
                 noun="job"):
        if on_result is None:
            with open(jobs[0]["stage_path"], "wb") as f:
                f.write(b"partial")
            raise KeyboardInterrupt()
        return _ColourQwenEdit.run_jobs(self, model_id, loras, jobs, width, height, skill, work_dir, log_path,
                                        on_result, noun)


def test_ic_review_focus_4_an_interrupted_shots_redo_keeps_a_consistent_record(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    cd, popens = _critic_fakes(monkeypatch, _InterruptedRedoQwenEdit())
    story_dir = _write_story(tmp)
    work = os.path.join(story_dir, "seed_edits")
    cd.replies.update({os.path.join(work, "panel_01.png"): [ict.verdict(8)],
                       os.path.join(work, "panel_02.png"): [ict.verdict(3, ["fused left hand"])],
                       os.path.join(work, "panel_03.png"): [ict.verdict(8)]})
    with pytest.raises(KeyboardInterrupt):
        movie._phase2_shots_seed(_phase_args(tmp, critic=True, critic_rounds=None))
    two = _record(story_dir)["panels"][1]
    assert (two["status"], two["critic"]["status"], two["critic"]["score"]) == ("ok", "flagged", 3)
    assert two["still_sha256"] == _sha(_still(story_dir, 2))
    with Image.open(_still(story_dir, 2)) as img:
        assert img.getpixel((704, 448)) == (3, 0, 80)
    assert glob.glob(os.path.join(work, "critic", "*.pending.png")) == []
    assert popens == []
    capsys.readouterr()
    monkeypatch.setattr(movie, "_qwen_edit", lambda: clean_env["fake"])
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert clean_env["fake"].calls["run_jobs"] == []


def test_ic_review_focus_5_a_single_panel_redo_batch(clean_env, monkeypatch, capsys):
    tmp = clean_env["tmp"]
    fake = _ColourQwenEdit()
    cd, _popens = _critic_fakes(monkeypatch, fake)
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    work = os.path.join(story_dir, "seed_edits")
    cd.replies.update({os.path.join(work, "panel_03.png"): [ict.verdict(2, ["extra arm"])],
                       os.path.join(work, "critic", "panel_03.r1.png"): [ict.verdict(9)]})
    capsys.readouterr()
    assert movie._phase2_shots_seed(_phase_args(tmp, redo_panels=[3], critic=True, critic_rounds=None)) == 0
    assert _jobs(fake) == [[1, 2, 3], [3], [3]]
    (first,), (redo,) = fake.calls["run_jobs"][1]["jobs"], fake.calls["run_jobs"][2]["jobs"]
    assert redo["seed"] == image_critic.critic_seed(3, 1, 3)
    assert (os.path.basename(first["stage_path"]), os.path.basename(redo["stage_path"])) == (
        "panel_03.pending.png", "panel_03.r1.pending.png")
    assert sorted(cd.calls) == [os.path.join(work, "critic", "panel_03.r1.png"), os.path.join(work, "panel_03.png")]
    entries = _record(story_dir)["panels"]
    assert ["critic" in entry for entry in entries] == [False, False, True]
    assert (entries[2]["critic"]["status"], entries[2]["critic"]["seed_used"]) == (
        "passed", image_critic.critic_seed(3, 1, 3))
    out = capsys.readouterr().out.splitlines()
    assert "critic 3/3: redo (score 2: extra arm)" in out and "critic 3/3: ok (score 9, attempt 2)" in out
    assert "critic: redo round 1 of 2: panel 3 with new seeds" in out


def test_ict19_without_critic_the_phase_is_unchanged(clean_env, monkeypatch, capsys):
    tmp, fake = clean_env["tmp"], clean_env["fake"]

    def refuse():
        raise AssertionError("_image_critic must not be called without --critic")

    monkeypatch.setattr(movie, "_image_critic", refuse)
    story_dir = _write_story(tmp)
    assert movie._phase2_shots_seed(_phase_args(tmp)) == 0
    assert len(fake.calls["run_jobs"]) == 1
    assert all("critic" not in entry for entry in _record(story_dir)["panels"])
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("critic")]
    assert not os.path.exists(os.path.join(story_dir, "seed_edits", "critic"))
    _write_story(tmp, "s2")
    assert movie._phase2_shots_seed(_phase_args(tmp, story_id="s2", critic=False, critic_rounds=None)) == 0
    assert len(fake.calls["run_jobs"]) == 2
````

- [ ] **Step 8: Run them to verify they fail.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py -k "ict17 or ict18 or ict19 or ic_review_focus" 2>&1 | tail -1`

Expected: `5 failed, 20 deselected` (`AttributeError` for `_resolve_critic` and `_image_critic`).

- [ ] **Step 9: `bin/ltx-movie`, the docstring, the flags and the loader (spec 2.9.1, 2.9.2, 2.9.5).** Three Edits.

(a) Edit `bin/ltx-movie`. Old:

````python
--shots does without a seed.

Extra references (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md): --extra-ref PATH[:CAPTION]
````

New:

````python
--shots does without a seed.

Image critic (docs/superpowers/specs/2026-11-27-image-critic-design.md): --critic with --shots, --seed-image and a
Qwen --seed-edit-model ID judges every panel's seed edit with the local VLM between Qwen batches and re-edits the
failures with new seeds (--critic-rounds, default 2); the best attempt is the still, and seed_edits.json records
each panel's verdict. It loads image_critic.py by path, only with --critic.

Extra references (docs/superpowers/specs/2026-11-13-extra-reference-images-design.md): --extra-ref PATH[:CAPTION]
````

(b) Edit `bin/ltx-movie`. Old:

````python
                         help="with --seed-edit-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
````

New:

````python
                         help="with --seed-edit-model ID: a registry LoRA of that model's family, 0 < SCALE <= 2 "
                              "(repeatable); none listed means no LoRA")
    parser.add_argument("--critic", dest="critic", action="store_true",
                         help="with --shots, --seed-image and a Qwen --seed-edit-model ID: the local VLM (bin/story-server "
                              "mlx-vision) judges every panel's seed edit for broken bodies between Qwen batches and "
                              "re-edits the failures with new seeds; the best attempt is kept and flagged when none "
                              "passes. See docs/superpowers/specs/2026-11-27-image-critic-design.md.")
    parser.add_argument("--critic-rounds", dest="critic_rounds", type=int, default=None, metavar="N",
                         help="with --critic: at most N redo rounds (0 to 4, default 2; 0 judges without redoing)")
````

(c) Edit `bin/ltx-movie`. Old:

````python
    return importlib.machinery.SourceFileLoader("qwen_edit", os.path.join(WS, "qwen_edit.py")).load_module()
````

New:

````python
    return importlib.machinery.SourceFileLoader("qwen_edit", os.path.join(WS, "qwen_edit.py")).load_module()


def _image_critic():
    """image_critic.py (image critic spec 2.9), loaded by path and only with --critic, so a run without it, a dry run
    and the deploy package never read it."""
    return importlib.machinery.SourceFileLoader("image_critic", os.path.join(WS, "image_critic.py")).load_module()
````

- [ ] **Step 10: `bin/ltx-movie`, `_resolve_critic` and `main` (spec 2.9.3).** Two Edits.

(a) Edit `bin/ltx-movie`. Old:

````python
    args.seed_context = {"mode": mode, "order": order or "seed-first"}
    return 0
````

New:

````python
    args.seed_context = {"mode": mode, "order": order or "seed-first"}
    return 0


def _resolve_critic(args):
    """--critic/--critic-rounds (image critic spec 2.9): returns 0, or 2 after one Error: line. args.critic_rounds
    stays None for the default (image_critic.DEFAULT_ROUNDS). Loads nothing: Phase 2 loads image_critic.py."""
    if args.critic_rounds is not None and not args.critic:
        print("Error: --critic-rounds needs --critic", file=sys.stderr)
        return 2
    if not args.critic:
        return 0
    if args.critic_rounds is not None and not 0 <= args.critic_rounds <= 4:
        print("Error: --critic-rounds must be an integer from 0 to 4", file=sys.stderr)
        return 2
    if getattr(args, "seed_context", None):
        print("Error: --critic cannot be combined with --seed-context: a redone still would change every later "
              "panel's context picture", file=sys.stderr)
        return 2
    if not (args.shots and getattr(args, "seed_image", None) and getattr(args, "seed_edit", None)):
        print("Error: --critic needs --shots with --seed-image and a Qwen --seed-edit-model ID: the image critic "
              "judges the shots seed edits only", file=sys.stderr)
        return 2
    path = os.path.join(WS, "image_critic.py")
    if not os.path.isfile(path):
        print("Error: --critic needs %s, which this workspace does not have" % path, file=sys.stderr)
        return 2
    return 0
````

(b) Edit `bin/ltx-movie`. Old:

````python
    rc = _resolve_seed_context(args)
    if rc:
        return rc
````

New:

````python
    rc = _resolve_seed_context(args)
    if rc:
        return rc
    rc = _resolve_critic(args)
    if rc:
        return rc
````

- [ ] **Step 11: `bin/ltx-movie`, `_phase2_shots_seed` (spec 2.9.4).** Two Edits.

(a) Edit `bin/ltx-movie`. Old:

````python
        entries[n] = record_entry(n, result["status"], result["seconds"], None)
        _write_shots_seed_record(files["record"], entries, total)

    _extra_refs_note(args)
````

New:

````python
        entries[n] = record_entry(n, result["status"], result["seconds"], None)
        _write_shots_seed_record(files["record"], entries, total)

    def on_verdict(n, block):
        entries[n]["critic"] = block
        _write_shots_seed_record(files["record"], entries, total)

    def on_best(n, output_path):
        still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
        fit.fit_letterbox(fit.load_oriented_rgb(output_path), still_w, still_h).save(still + ".tmp", format="PNG")
        os.replace(still + ".tmp", still)
        entries[n]["still_sha256"] = _sha256_file(still)
        _write_shots_seed_record(files["record"], entries, total)
        print("panel %d -> %s (critic: a better attempt of the Qwen edit of the seed)" % (n, still))

    _extra_refs_note(args)
````

(b) Edit `bin/ltx-movie`. Old:

````python
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references(jobs)), label, tag="ltx-movie")
        results, failure = qe.run_jobs(model_id, loras, jobs, width, height, SHOTS_SEED_EDIT_SKILL, files["work"],
                                       on_result=on_result, noun="panel")
````

New:

````python
        qe.wait_for_memory(qe.memory_floor(model_id, _edit_references(jobs)), label, tag="ltx-movie")
        if getattr(args, "critic", False):
            ic = _image_critic()
            rounds = ic.DEFAULT_ROUNDS if args.critic_rounds is None else args.critic_rounds
            results, failure = ic.edit_with_critic(qe, model_id, loras, jobs, width, height, SHOTS_SEED_EDIT_SKILL,
                                                   files["work"], rounds=rounds, total=total, on_result=on_result,
                                                   on_verdict=on_verdict, on_best=on_best, noun="panel",
                                                   tag="ltx-movie")
        else:
            results, failure = qe.run_jobs(model_id, loras, jobs, width, height, SHOTS_SEED_EDIT_SKILL, files["work"],
                                           on_result=on_result, noun="panel")
````

- [ ] **Step 12: Run the `bin/ltx-movie` tests.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_seed.py 2>&1 | tail -1`

Expected: `25 passed` (SET1-SET15 and Review Focus 1-4 pass unedited; ICT19).

- [ ] **Step 13: Run the relevant set, the compile check and the changed-file list.** About 40 seconds.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_seed_edit_tool.py tests/test_ltx_movie_cast_refs.py tests/test_ltx_movie_extra_refs.py tests/test_ltx_movie_iterate_flags.py tests/test_ltx_movie_offline.py tests/test_ltx_movie_seed_context_frame.py tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_edit.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_shots_zimage.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_builder.py tests/test_image_critic.py 2>&1 | grep -E '^(FAILED|ERROR) |passed|failed' | sed 's/ - .*//'
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' bin/seed-edit bin/ltx-movie tests/test_seed_edit_tool.py tests/test_ltx_movie_shots_seed.py; done
git diff --name-only HEAD
```

Expected:
1. Exactly one failure, `FAILED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`, and `1 failed, 386 passed`. `test_mut26` fails **by design** at C2 (`bin/ltx-movie` changed); Task 3 re-baselines it. Any other failure: stop.
2. `compiled 4`, twice.
3. Exactly `qwen-agent-workspace/bin/ltx-movie`, `qwen-agent-workspace/bin/seed-edit`, `qwen-agent-workspace/tests/test_ltx_movie_shots_seed.py`, `qwen-agent-workspace/tests/test_seed_edit_tool.py`.

- [ ] **Step 14: Commit C2.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git add bin/seed-edit bin/ltx-movie tests/test_seed_edit_tool.py tests/test_ltx_movie_shots_seed.py && git diff --cached --name-only && git commit -m "seed-edit, ltx-movie: --critic and --critic-rounds judge each Qwen seed edit with the local VLM and re-edit the failures (image critic hooks)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && git rev-parse HEAD
```

Expected: the four names, one commit, and its full 40-hex sha (Task 3 uses it). `bin/seed-edit` and `bin/ltx-movie` keep mode 100755; Edit does not change the mode.

---

### Task 3: re-baseline `test_mut26` to C2 (commit C3, test-only; spec 6.3 Task 2, Plan C3; R7)

**Files:**
- Modify `qwen-agent-workspace/tests/test_movie_ui_builder.py`: `test_mut26`'s comment chain (:288-297) and `BASELINE` (:298).
- Nothing else. C3 must come immediately after C2, with no commit between them.

**Interfaces:**
- Consumes (Task 2): the C2 commit, `HEAD` at the start of this task.
- Produces: `BASELINE = "<C2 sha>"`. From here on every commit keeps `test_mut26` green; a later commit that changes `bin/ltx-movie` (or any `PIPELINE_FILES` member) needs its own BASELINE commit right after it.

- [ ] **Step 1: Check that `HEAD` is C2.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git log -1 --format='%H %s' && git status --short | wc -l`

Expected: the C2 sha followed by `seed-edit, ltx-movie: --critic and --critic-rounds judge each Qwen seed edit with the local VLM and re-edit the failures (image critic hooks)`; `0`. Anything else: stop.

- [ ] **Step 2: Run `test_mut26` to see it fail.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1`

Expected: `1 failed, 11 deselected`.

- [ ] **Step 3: Write C2's sha into the pin.** The sha is known only now, so this one step runs a script instead of the Edit tool. It replaces exactly two texts, each of which must occur once: the line `    BASELINE = "a87e7992ff17c351aa75e47980977d81b1138e03"` becomes `    BASELINE = "<C2 sha>"`, and the chain's end `e6f773135b65f6c35065907534c28adca3456b40 (extra-refs review fix).` becomes `e6f773135b65f6c35065907534c28adca3456b40 (extra-refs review fix), then to <C2 sha> (image critic hooks).`

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 - "$(git rev-parse HEAD)" <<'EOF'
import sys
sha = sys.argv[1]
assert len(sha) == 40
path = "tests/test_movie_ui_builder.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
old_base = '    BASELINE = "a87e7992ff17c351aa75e47980977d81b1138e03"\n'
old_chain = "e6f773135b65f6c35065907534c28adca3456b40 (extra-refs review fix).\n"
assert text.count(old_base) == 1 and text.count(old_chain) == 1
text = text.replace(old_base, '    BASELINE = "%s"\n' % sha)
text = text.replace(old_chain, "e6f773135b65f6c35065907534c28adca3456b40 (extra-refs review fix), then to %s "
                               "(image critic hooks).\n" % sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("BASELINE ->", sha)
EOF
git diff --stat
```

Expected: `BASELINE -> <C2 sha>`; `1 file changed, 2 insertions(+), 2 deletions(-)`.

- [ ] **Step 4: Run the builder tests.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py 2>&1 | tail -1`

Expected: `12 passed`.

- [ ] **Step 5: Commit C3.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git add tests/test_movie_ui_builder.py && git diff --cached --name-only && git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the image-critic hooks commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: `qwen-agent-workspace/tests/test_movie_ui_builder.py` only, then one commit.

- [ ] **Step 6: Verify at C3: the full suite and the 3.9 compile.** About 21 minutes.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/ 2>&1 | tee ../../ic-baseline/full-c3.log | grep -E '^(FAILED|ERROR) ' | sed 's/ - .*//' | sort > ../../ic-baseline/full-c3-failures.txt; tail -1 ../../ic-baseline/full-c3.log; comm -13 ../../ic-baseline/full-base-failures.txt ../../ic-baseline/full-c3-failures.txt
/usr/bin/python3 -m py_compile bin/seed-edit bin/ltx-movie && echo "py39 ok"
```

Expected: the summary line (`28 failed, 2978 passed, 2 skipped` during planning), then **nothing** from `comm`; `py39 ok`. A `comm` line is a stop-and-report.

---

### Task 4: the movie UI (commit C4; spec 2.6, 2.10, 2.11, 5, 6.2, 6.3 Task 3; ICT20-ICT24; R4-R6)

**Files:**
- Modify `qwen-agent-workspace/movie_ui_lib.py`: `DEFAULT_FIELDS` (:947), `FIELD_FLAGS` (:974), `build_argv` (:1042-1043), `_rule_critic` after `_rule_seed_edit` (:1138-1152), the V1 list (:1642), `seed_edit_argv` (:1296-1301), `CRITIC_RE` after `SEED_CAND_RE` (:2356), `ProgressParser.__init__` (:2400), `_line` (:2427-2431), `critic_summary` before `snapshot` (:2477), `snapshot` (:2492-2496, :2510-2515).
- Modify `qwen-agent-workspace/movie_ui_seedgen.py`: `validate_run_request` (:228-240).
- Modify `qwen-agent-workspace/movie_ui_server.py`: `_cand_critic` after `_cand_file` (:1766-1769), `run_view` (:1826-1827), `_h_seed_run_create` (:1897-1901).
- Modify `qwen-agent-workspace/movie_ui_batch.py`: `GROUPS` (:34-35), `FIELD_LEVELS` (:43).
- Modify `qwen-agent-workspace/static/movie-ui/index.html` (:96, :200-201) and `qwen-agent-workspace/static/movie-ui/app.js` (`composeFields` :573, `updateComposeButtons` :681, `fillCompose` :967, `updateSeedButtons` :2299, `seedBody` :2341-2345, `seedRow` :2429-2450, `renderProgress` :3366, :3381-3382).
- Create `qwen-agent-workspace/tests/test_movie_ui_critic.py` (ICT20-ICT24).
- Modify `qwen-agent-workspace/tests/test_movie_ui_seedgen.py` (ICT22b, appended).
- Modify the help fixture `qwen-agent-workspace/tests/fixtures/movie_ui/ltx-movie-help-current.txt` (after `--extra-ref`, :58-60).
- Modify the table pins (spec 6.3 Task 3, R6): `tests/test_movie_ui_builder.py` (`NEW_PY`, MUT3), `tests/test_qwen_edit.py` (QET11), `tests/test_location_ui.py` (:267), `tests/test_movie_ui_extra_refs.py` (:60, :63, :132), `tests/test_movie_ui_qwen_edit.py` (:116, :352, :354-355), `tests/test_movie_ui_shots_seed.py` (:38-43, :157), `tests/test_movie_ui_batch.py` (:29-38, :79), `tests/test_movie_ui_http.py` (:225).
- Pinned files touched: none.

**Interfaces:**
- Consumes (Task 2): `bin/seed-edit --critic` and `bin/ltx-movie --critic` (the argv flags), `--critic` and `--critic-rounds` in `bin/ltx-movie --help`; the `run.json` candidate `"critic"` block of Task 1's shape; the Task 1 log lines.
- Consumes (existing): `lib._is_int`, `seedgen._absent`, `lib.compose_fields`, `lib.validate_fields(fields, ws_real, state)`, `lib.build_argv(fields, ws_real, state, py=sys.executable)`, `lib.seed_edit_argv(fields, ws_real, py=sys.executable)`, `lib.ProgressParser(kind, fields)` with `feed(data)` and `snapshot(job, status, state, now=None)`; the page helpers `$`, `el`, `show`; the tests' `mt.fields`, `mt.set_home`, `mt.make_stub_workspace`, `mt.PNG`, `mt.api`, `_clean_env` (`test_movie_ui_qwen_edit.py`), `_compose_page_code` and `_node` (`test_movie_ui_shots_zimage.py`), and `env`, `_upload`, `_body`, `_create`, `_record` (`test_movie_ui_seedgen.py`).
- Produces:
  - `lib.DEFAULT_FIELDS["critic"] = False`; `("critic", ("--critic",))` in `lib.FIELD_FLAGS`; `lib._rule_critic(fields) -> [str]` (V1 rule 12f); `lib.CRITIC_RE`; `ProgressParser.critic: {"<n>": state}` and `ProgressParser.critic_summary() -> {"ok", "redo", "flagged", "unjudged": [int]}`; the snapshots' `"critic"` key, only when the parser saw a critic line.
  - `seedgen.validate_run_request` puts `"critic": True` last in the clean dict only when the body's `critic` is `True`.
  - `srv._cand_critic(entry) -> None | {"status", "score", "defects", "reason", "attempts"}`; the run view's candidates carry `"critic"` only when it is not None; a seed job's `fields["critic"] = True` only when requested.
  - `batch.FIELD_LEVELS["critic"] = "stills"`; `"critic"` ends `batch.GROUPS[1]`.
  - Page ids `c-critic-box`, `c-critic`, `se-critic-box`, `se-critic`; JS `criticText(c)`, `criticProgressText(c)`; `composeFields(...).critic: bool`; a Seeds body's `critic: true` (qwen only).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_movie_ui_critic.py` with exactly this content:

````python
"""Tests for the image critic's movie-ui side (docs/superpowers/specs/2026-11-27-image-critic-design.md, Section 6.2:
ICT20-ICT24; ICT22b lives in tests/test_movie_ui_seedgen.py): the log regex and the progress summary, the Compose
field, flag, argv and V1 rule 12f, the batch level, the Seeds request, argv and candidate view, the static page,
and the rule that the server never imports image_critic.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_critic.py

Stdlib and pytest (node --check when node is on PATH). The V1 tests use a stub workspace whose bin/ltx-movie prints
tests/fixtures/movie_ui/ltx-movie-help-current.txt. No test starts a server, a job or a model.
"""

import os
import re
import shutil
import subprocess

import pytest

import movie_ui_testutil as mt
import movie_ui_batch as batch
import movie_ui_lib as lib
import movie_ui_seedgen as seedgen
import movie_ui_server as srv
from test_movie_ui_qwen_edit import _clean_env
from test_movie_ui_shots_zimage import _compose_page_code, _node

WS = mt.WS
UP = "a" * 64 + ".png"
UNC = [{"id": "uncensored", "scale": 1}]
RUN = "se-20261102-141500-a1b2"
RULE_12F = "the image critic needs shots mode with a seed image and a Qwen seed edit model"


@pytest.fixture
def v1_env(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    _clean_env(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    with open(os.path.join(state, "uploads", UP), "wb") as f:
        f.write(mt.PNG)
    return {"state": state, "ws": ws}


def _page():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    return static, html, js


# --- ICT20: the log regex and the progress summary ---------------------------------------------------------------

def test_ict20_the_log_regex_and_the_snapshot(tmp_path):
    for line, groups in (("critic 1/3: ok (score 8, attempt 1)", ("1", "3", "ok", "score 8, attempt 1")),
                         ("critic 2/3: redo (score 3: fused hand)", ("2", "3", "redo", "score 3: fused hand")),
                         ("critic 2/3: flagged (best score 5 of 3 attempts: no defect named)",
                          ("2", "3", "flagged", "best score 5 of 3 attempts: no defect named")),
                         ("critic 3/3: unjudged (VLM request failed: OSError: refused)",
                          ("3", "3", "unjudged", "VLM request failed: OSError: refused")),
                         ("critic 4/4: ok", ("4", "4", "ok", None))):
        match = lib.CRITIC_RE.match(line)
        assert match and match.groups() == groups, line
    for line in ("critic: done: 3 passed, 0 flagged, 0 unjudged; 0 redo round(s) run", "candidate 1/4 ok 2.0s",
                 "critic: judging 3 panels with the VLM (round 0)", "critic 1/3: skipped (x)"):
        assert not lib.CRITIC_RE.match(line), line
    state = str(tmp_path)
    job = {"id": "20261127-120000-a1b2", "workspace": state, "story_id": "s1"}
    lines = (b"candidate 1/3 ok 1.0s\ncandidate 2/3 ok 1.0s\ncandidate 3/3 ok 1.0s\n"
             b"critic 1/3: ok (score 8, attempt 1)\ncritic 2/3: redo (score 3: fused hand)\n"
             b"critic 3/3: unjudged (unparseable: x)\ncritic 2/3: flagged (best score 4 of 3 attempts: fused hand)\n")
    parser = lib.ProgressParser("seed-edit", {"candidates": 3})
    parser.feed(lines)
    snap = parser.snapshot(job, None, state)
    assert snap["critic"] == {"ok": [1], "redo": [], "flagged": [2], "unjudged": [3]}
    assert snap["candidates"]["ok"] == 3 and list(snap)[-1] == "critic"
    plain = lib.ProgressParser("seed-edit", {"candidates": 3})
    plain.feed(lines.split(b"critic")[0])
    assert "critic" not in plain.snapshot(job, None, state)
    movie = lib.ProgressParser("movie", {"mode": "shots"})
    movie.feed(b"panel 1 -> /x (Qwen edit of the seed, 12.5s)\ncritic 1/2: redo (score 3: x)\n"
               b"critic 2/2: ok (score 9, attempt 1)\ncritic 1/2: ok (score 8, attempt 2)\n")
    snap = movie.snapshot(job, None, state)
    assert snap["critic"] == {"ok": [1, 2], "redo": [], "flagged": [], "unjudged": []}
    assert snap["panels"] == {}
    bare = lib.ProgressParser("movie", {"mode": "shots"})
    bare.feed(b"seed edits: 3 panel stills written\n")
    assert "critic" not in bare.snapshot(job, None, state)


# --- ICT21: the Compose field, flag, argv, V1 rule 12f and the batch level ------------------------------------

def test_ict21_the_compose_field_flag_argv_and_v1(v1_env):
    state, ws = v1_env["state"], v1_env["ws"]
    keys = list(lib.DEFAULT_FIELDS)
    assert lib.DEFAULT_FIELDS["critic"] is False and keys[keys.index("extra_refs") + 1] == "critic"
    flags = [k for k, _f in lib.FIELD_FLAGS]
    assert dict(lib.FIELD_FLAGS)["critic"] == ("--critic",) and flags[flags.index("critic") + 1] == "extra_refs"
    f = mt.fields(WS, seed_upload=UP, action="movie", mode="shots", seed_edit_model="qwen21-q4",
                  seed_edit_loras=UNC, critic=True)
    argv = lib.build_argv(f, WS, state)
    i = argv.index("--seed-image")
    assert argv[i:i + 7] == ["--seed-image", os.path.join(state, "uploads", UP), "--seed-edit-model", "qwen21-q4",
                             "--seed-edit-lora", "uncensored=1.0", "--critic"]
    golden = [a for a in argv if a != "--critic"]
    assert lib.build_argv(dict(f, critic=False), WS, state) == golden
    old = dict((k, v) for k, v in f.items() if k != "critic")
    assert lib.build_argv(old, WS, state) == golden
    assert "--critic" not in lib.build_argv(dict(f, seed_upload=None, mode="chained"), WS, state)

    def errors(**overrides):
        return lib.validate_fields(mt.fields(ws, **overrides), ws, state)

    shots = dict(seed_upload=UP, mode="shots", seed_edit_model="qwen21-q4")
    assert errors(critic=True, **shots) == []
    assert errors(critic=False, **shots) == [] and errors(**shots) == []
    assert errors(critic="yes", **shots) == ["critic must be true or false"]
    assert errors(critic=1, **shots) == ["critic must be true or false"]
    assert errors(critic=True, seed_upload=UP, mode="chained", seed_edit_model="qwen21-q4") == [RULE_12F]
    assert errors(critic=True, mode="shots") == [RULE_12F]
    assert errors(critic=True, seed_upload=UP, mode="shots", seed_edit_model="as-is") == [RULE_12F]
    assert lib.validate_fields(dict((k, v) for k, v in mt.fields(ws, **shots).items() if k != "critic"),
                               ws, state) == []
    assert batch.FIELD_LEVELS["critic"] == "stills"
    assert "critic" in [group for group in batch.GROUPS if "seed_edit_model" in group][0]


# --- ICT22a: the Seeds request, argv and candidate view -------------------------------------------------------

def _req(**overrides):
    body = {"ws": "/abs/ws", "source": {"upload_id": UP}, "prompt": "make it night", "model": "qwen", "candidates": 2,
            "seed": 7}
    body.update(overrides)
    return body


def test_ict22a_seeds_request_argv_and_view():
    clean, error = seedgen.validate_run_request(_req(critic=True))
    assert error is None and clean["critic"] is True and list(clean)[-1] == "critic"
    assert seedgen.validate_run_request(_req(model="zimage", critic=True)) == (None, "critic is only for qwen")
    for bad in (1, "true", [True]):
        assert seedgen.validate_run_request(_req(critic=bad)) == (None, "critic must be true or false"), bad
    for body in (_req(), _req(critic=None), _req(critic=False), _req(model="zimage", critic=False)):
        clean, error = seedgen.validate_run_request(body)
        assert error is None and "critic" not in clean
    assert seedgen.validate_run_request(_req(prompt="", critic=1)) == (None, "prompt is required")
    fields = {"ws": "/ws", "run": RUN, "source_file": "source.png", "prompt": "make it night", "model": "qwen",
              "strength": None, "qwen_model": "qwen21-q4", "loras": [{"id": "uncensored", "scale": 1.0}],
              "candidates": 2, "seed": 7, "source": {"kind": "upload", "upload_id": UP}}
    plain = lib.seed_edit_argv(fields, "/ws", py="/py")
    argv = lib.seed_edit_argv(dict(fields, critic=True), "/ws", py="/py")
    i = argv.index("--candidates")
    assert argv[i - 3:i + 1] == ["--lora", "uncensored=1.0", "--critic", "--candidates"]
    assert [a for a in argv if a != "--critic"] == plain and "--critic" not in plain
    assert lib.seed_edit_argv(dict(fields, critic=False), "/ws", py="/py") == plain
    for entry in ({"n": 1}, {"n": 1, "critic": "flagged"}, {"n": 1, "critic": {"status": "redo"}},
                  {"n": 1, "critic": {"score": 5}}):
        assert srv._cand_critic(entry) is None, entry
    full = {"status": "flagged", "score": 5, "defects": ["fused hand", 3, "x"], "reason": "r" * 400,
            "seed_used": 9, "pass_score": 7, "attempts": [{}, {}, {}]}
    assert srv._cand_critic({"n": 1, "critic": full}) == {"status": "flagged", "score": 5,
                                                          "defects": ["fused hand", "x"], "reason": "r" * 300,
                                                          "attempts": 3}
    assert srv._cand_critic({"n": 1, "critic": {"status": "unjudged", "score": True, "defects": "x", "reason": 5,
                                                "attempts": None}}) == {
        "status": "unjudged", "score": None, "defects": [], "reason": None, "attempts": 0}


# --- ICT23: the static page -------------------------------------------------------------------------------------

def test_ict23_the_page():
    static, html, js = _page()
    for element in ("c-critic-box", "c-critic", "se-critic-box", "se-critic"):
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="c-sq-shots-note"') < html.index('id="c-critic-box"') < html.index('id="c-xr-box"')
    assert html.index('id="se-qwen-box"') < html.index('id="se-critic-box"') < html.index('id="se-strength-box"')
    assert '<label id="c-critic-box" hidden>' in html and '<label id="se-critic-box" hidden>' in html
    assert html.index('<p id="se-qwen-note" class="muted"></p>\n      </div>\n      <label id="se-critic-box"') > 0
    for text in ("function criticText(c) {", "function criticProgressText(c) {", '$("#c-critic").checked',
                 "body.critic = true;", "critic: flagged — best score ",
                 'show($("#c-critic-box"), shotsSeed && !zimageSeed',
                 '    show($("#se-qwen-box"), model === "qwen");\n    show($("#se-critic-box"), model === "qwen");\n',
                 'if (cand.critic) { row.parts.push(el("div", {cls: "muted", text: criticText(cand.critic)})); }',
                 "if (p.critic) { parts.push(criticProgressText(p.critic)); }",
                 '(p.critic ? " - " + criticProgressText(p.critic) : "")'):
        assert text in js, text
    assert js.count('$("#c-critic").checked') == 2
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\bconfirm\(", r"innerHTML"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    script = _compose_page_code() + (
        'function run(mode, engine, checked, editModel) {\n'
        '  $("#c-mode").value = mode;\n'
        '  $("#c-res-seed").checked = true;\n'
        '  S.seedUpload = "up1";\n'
        '  S.composeEngine = engine;\n'
        '  $("#c-critic").checked = checked;\n'
        '  PICKED.model = editModel;\n'
        '  return composeFields("movie").critic;\n'
        '}\n'
        'const out = [run("shots", "qwen", true, "qwen-edit-x"), run("shots", "zimage", true, "qwen-edit-x"),\n'
        '             run("chained", "qwen", true, "qwen-edit-x"), run("shots", "qwen", false, "qwen-edit-x"),\n'
        '             run("shots", "qwen", true, "as-is")];\n'
        'S.options = {supported: {critic: false}};\n'
        'out.push(run("shots", "qwen", true, "qwen-edit-x"));\n'
        'fillCompose({critic: true});\n'
        'const filled = $("#c-critic").checked;\n'
        'fillCompose({});\n'
        'console.log(JSON.stringify([out, filled, $("#c-critic").checked]));')
    assert _node(script) == [[True, False, False, False, False, False], True, False]


# --- ICT24: the server never imports the critic -----------------------------------------------------------------

def test_ict24_the_server_never_imports_the_critic():
    for rel in ("movie_ui_server.py", "movie_ui_lib.py", "movie_ui_seedgen.py", "movie_ui_batch.py"):
        with open(os.path.join(WS, rel), encoding="utf-8") as f:
            assert "image_critic" not in f.read(), rel
````

Then append ICT22b to `tests/test_movie_ui_seedgen.py`:

Edit `tests/test_movie_ui_seedgen.py`. Old:

````python
    peek = os.path.join(ws, "generated", "peek.png")
    os.symlink(os.path.join(work, "cand_02.pending.png"), peek)
    assert mt.api(s, "GET", "/files?ws=%s&path=%s" % (ws, peek))[0] == 403
````

New:

````python
    peek = os.path.join(ws, "generated", "peek.png")
    os.symlink(os.path.join(work, "cand_02.pending.png"), peek)
    assert mt.api(s, "GET", "/files?ws=%s&path=%s" % (ws, peek))[0] == 403


# --- ICT22b (image critic spec 2.10, 6.2): a critic run over HTTP, and its verdicts in the run view ------------------

def test_ict22b_a_critic_seed_run_over_http(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    up = _upload(s)
    body = _body(ws, {"upload_id": up}, model="qwen", strength=None, qwen_model="qwen21-q4",
                 loras=[{"id": "uncensored", "scale": 0.5}], critic=True)
    status, _h, data = _create(s, body)
    assert status == 201, data
    run, run_dir = data["run"]["run"], data["run"]["dir"]
    job = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))
    assert job["fields"]["critic"] is True and list(job["fields"])[-1] == "critic"
    assert job["argv"] == lib.seed_edit_argv(job["fields"], ws)
    assert job["argv"][job["argv"].index("--candidates") - 1] == "--critic"
    record = _record(run_dir)
    assert "critic" not in record and all("critic" not in c for c in record["candidates"])
    assert all("critic" not in c for c in data["run"]["candidates"])
    record["candidates"][0]["critic"] = {"status": "flagged", "score": 5, "defects": ["fused hand"], "reason": "r",
                                         "attempts": [{}, {}]}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)
    status, _h, view = mt.api(s, "GET", "/api/seeds/runs/%s?ws=%s" % (run, ws))
    assert status == 200, view
    first, second = view["candidates"]
    assert first["critic"] == {"status": "flagged", "score": 5, "defects": ["fused hand"], "reason": "r",
                               "attempts": 2}
    assert "critic" not in second
    assert _create(s, dict(body, model="zimage", strength=0.45, qwen_model=None, loras=None))[::2] == (
        400, {"error": "critic is only for qwen"})
    assert _create(s, dict(body, critic="yes"))[::2] == (400, {"error": "critic must be true or false"})
    status, _h, data = _create(s, dict(body, critic=False))
    assert status == 201, data
    job = lib.read_job(lib.job_dir(state, data["run"]["job"]["id"]))
    assert "critic" not in job["fields"] and "--critic" not in job["argv"]
````

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_critic.py tests/test_movie_ui_seedgen.py::test_ict22b_a_critic_seed_run_over_http 2>&1 | tail -1`

Expected: `5 failed, 1 passed`. `test_ict24_the_server_never_imports_the_critic` passes before and after.

- [ ] **Step 3: `movie_ui_lib.py`, the field, the flag, the argv and V1 rule 12f (spec 2.10.1).** Six Edits.

(a) Edit `movie_ui_lib.py`. Old:

````python
    "extra_refs": [],
    "mode": "chained",
````

New:

````python
    "extra_refs": [],
    "critic": False,
    "mode": "chained",
````

(b) Edit `movie_ui_lib.py`. Old:

````python
    ("no_review", ("--no-review",)), ("extra_refs", ("--extra-ref",)),
````

New:

````python
    ("no_review", ("--no-review",)), ("critic", ("--critic",)), ("extra_refs", ("--extra-ref",)),
````

(c) Edit `movie_ui_lib.py`. Old:

````python
        for item in fields.get("extra_refs") or []:        # extra references spec XR16
            argv += ["--extra-ref", extra_ref_arg(state, item)]
````

New:

````python
        for item in fields.get("extra_refs") or []:        # extra references spec XR16
            argv += ["--extra-ref", extra_ref_arg(state, item)]
        if fields.get("critic") is True:
            argv.append("--critic")   # image critic spec 2.10
````

(d) Edit `movie_ui_lib.py`. Old:

````python
    if loras is not None and model in (None, "as-is"):
        errors.append("seed edit LoRAs need a seed edit model other than as-is")
    return errors
````

New:

````python
    if loras is not None and model in (None, "as-is"):
        errors.append("seed edit LoRAs need a seed edit model other than as-is")
    return errors


def _rule_critic(fields):
    """V1 rule 12f (image critic spec 2.10): critic is a bool, and true only on a shots seed edit run."""
    critic = fields.get("critic", False)
    if not isinstance(critic, bool):
        return ["critic must be true or false"]
    if critic and not (fields.get("mode") == "shots" and fields.get("seed_upload") is not None
                       and fields.get("seed_edit_model") not in (None, "as-is")):
        return ["the image critic needs shots mode with a seed image and a Qwen seed edit model"]
    return []
````

(e) Edit `movie_ui_lib.py`. Old:

````python
    errors += _rule_extra_refs(fields, state)                                # 12e
````

New:

````python
    errors += _rule_extra_refs(fields, state)                                # 12e
    errors += _rule_critic(fields)                                           # 12f
````

(f) Edit `movie_ui_lib.py`. Old:

````python
    if fields["model"] == "zimage":
        argv += ["--strength", repr(float(fields["strength"]))]
    return argv + ["--candidates", str(fields["candidates"]), "--seed", str(fields["seed"]),
````

New:

````python
    if fields["model"] == "zimage":
        argv += ["--strength", repr(float(fields["strength"]))]
    if fields.get("critic") is True:
        argv.append("--critic")
    return argv + ["--candidates", str(fields["candidates"]), "--seed", str(fields["seed"]),
````

- [ ] **Step 4: `movie_ui_lib.py`, the log regex, the parser and the snapshot (spec 2.6).** Six Edits.

(a) Edit `movie_ui_lib.py`. Old:

````python
SEED_CAND_RE = re.compile(r"^candidate (\d+)/(\d+) (ok|blocked|failed)(?: [0-9]+\.[0-9]s)?$")   # seed generator SG31
````

New:

````python
SEED_CAND_RE = re.compile(r"^candidate (\d+)/(\d+) (ok|blocked|failed)(?: [0-9]+\.[0-9]s)?$")   # seed generator SG31
CRITIC_RE = re.compile(r"^critic (\d+)/(\d+): (ok|redo|flagged|unjudged)(?: \((.*)\))?$")   # image critic spec 2.6
````

(b) Edit `movie_ui_lib.py`. Old:

````python
        self.candidates_total = None
````

New:

````python
        self.candidates_total = None
        self.critic = {}            # image critic: {"<n>": "ok" | "redo" | "flagged" | "unjudged"}
````

(c) Edit `movie_ui_lib.py`. Old:

````python
        if line.strip():
            self.last_line = line[:LINE_CLIP]
        if self.kind == "seed-edit":
````

New:

````python
        if line.strip():
            self.last_line = line[:LINE_CLIP]
        match = CRITIC_RE.match(line)
        if match:
            self.critic[match.group(1)] = match.group(3)
            return
        if self.kind == "seed-edit":
````

(d) Edit `movie_ui_lib.py`. Old:

````python
    def snapshot(self, job, status, state, now=None):
````

New:

````python
    def critic_summary(self):
        """{"ok", "redo", "flagged", "unjudged"}: the sorted int n of each job in its newest critic state."""
        return dict((state, sorted(int(n) for n, s in self.critic.items() if s == state))
                    for state in ("ok", "redo", "flagged", "unjudged"))

    def snapshot(self, job, status, state, now=None):
````

(e) Edit `movie_ui_lib.py`. Old:

````python
            return {"kind": "seed-edit", "elapsed_s": elapsed, "last_line": self.current_last_line(),
                    "face_problem": False,
                    "candidates": {"total": total, "done": done, "ok": states.count("ok"),
                                   "blocked": states.count("blocked"), "failed": states.count("failed"),
                                   "current": done + 1 if total is not None and done < total else None}}
````

New:

````python
            out = {"kind": "seed-edit", "elapsed_s": elapsed, "last_line": self.current_last_line(),
                   "face_problem": False,
                   "candidates": {"total": total, "done": done, "ok": states.count("ok"),
                                  "blocked": states.count("blocked"), "failed": states.count("failed"),
                                  "current": done + 1 if total is not None and done < total else None}}
            if self.critic:
                out["critic"] = self.critic_summary()
            return out
````

(f) Edit `movie_ui_lib.py`. Old:

````python
        return {"phase": self.phase, "phase_title": self.phase_title, "rewrite": self.rewrite,
                "phases": job_phases(self.kind, self.fields), "redo": self.redo,
                "panels_total": self.panels_total,
                "panels": dict((k, dict(v)) for k, v in sorted(self.panels.items(), key=lambda kv: int(kv[0]))),
                "panels_done": sum(1 for v in self.panels.values() if v["state"] == "ok"),
                "wrap_up": self.wrap_up, "stills": stills, "last_line": self.current_last_line()}
````

New:

````python
        out = {"phase": self.phase, "phase_title": self.phase_title, "rewrite": self.rewrite,
               "phases": job_phases(self.kind, self.fields), "redo": self.redo,
               "panels_total": self.panels_total,
               "panels": dict((k, dict(v)) for k, v in sorted(self.panels.items(), key=lambda kv: int(kv[0]))),
               "panels_done": sum(1 for v in self.panels.values() if v["state"] == "ok"),
               "wrap_up": self.wrap_up, "stills": stills, "last_line": self.current_last_line()}
        if self.critic:
            out["critic"] = self.critic_summary()
        return out
````

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_critic.py tests/test_movie_ui_seedgen.py::test_ict22b_a_critic_seed_run_over_http 2>&1 | tail -1`

Expected: `4 failed, 2 passed` (ICT20 now passes).

- [ ] **Step 5: `movie_ui_seedgen.py`, `movie_ui_server.py`, `movie_ui_batch.py` (spec 2.10.2-2.10.4).** Seven Edits.

(a) Edit `movie_ui_seedgen.py`. Old:

````python
    qwen_model_id, loras, error = _qwen_fields(body, model)
    if error is not None:
        return None, error
    source, error = _source(body.get("source"))
````

New:

````python
    qwen_model_id, loras, error = _qwen_fields(body, model)
    if error is not None:
        return None, error
    critic = body.get("critic")
    if not _absent(body, "critic") and not isinstance(critic, bool):
        return None, "critic must be true or false"
    if critic is True and model != "qwen":
        return None, "critic is only for qwen"
    source, error = _source(body.get("source"))
````

(b) Edit `movie_ui_seedgen.py`. Old:

````python
    return {"prompt": prompt, "model": model, "strength": strength,
            "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
            "seed": seed, "qwen_model": qwen_model_id, "loras": loras, "source": source}, None
````

New:

````python
    clean = {"prompt": prompt, "model": model, "strength": strength,
             "candidates": CANDIDATES_DEFAULT if candidates is None else candidates,
             "seed": seed, "qwen_model": qwen_model_id, "loras": loras, "source": source}
    if critic is True:
        clean["critic"] = True
    return clean, None
````

(c) Edit `movie_ui_server.py`. Old:

````python
                  "seed": seed, "source": origin}
        lib.create_job(server.state, job_id, "seed-edit", real, None, None, lib.seed_edit_argv(fields, real), fields)
````

New:

````python
                  "seed": seed, "source": origin}
        if clean.get("critic") is True:
            fields["critic"] = True
        lib.create_job(server.state, job_id, "seed-edit", real, None, None, lib.seed_edit_argv(fields, real), fields)
````

(d) Edit `movie_ui_server.py`. Old:

````python
    path = os.path.join(run_dir, "cand_%02d.png" % entry["n"])
    return path if entry.get("status") == "ok" and _isfile_in(run_dir, path) else None
````

New:

````python
    path = os.path.join(run_dir, "cand_%02d.png" % entry["n"])
    return path if entry.get("status") == "ok" and _isfile_in(run_dir, path) else None


def _cand_critic(entry):
    """Image critic spec 2.10: the page's view of a candidate's critic block in run.json, else None."""
    block = entry.get("critic")
    if not (isinstance(block, dict) and block.get("status") in ("passed", "flagged", "unjudged")):
        return None
    defects, reason, attempts = block.get("defects"), block.get("reason"), block.get("attempts")
    return {"status": block["status"], "score": block.get("score") if lib._is_int(block.get("score")) else None,
            "defects": [d for d in defects if isinstance(d, str)] if isinstance(defects, list) else [],
            "reason": reason[:300] if isinstance(reason, str) else None,
            "attempts": len(attempts) if isinstance(attempts, list) else 0}
````

(e) Edit `movie_ui_server.py`. Old:

````python
    view["candidates"] = [{"n": c["n"], "seed": c.get("seed"), "status": c.get("status"),
                           "seconds": c.get("seconds"), "path": _cand_file(run_dir, c)} for c in _candidates(record)]
````

New:

````python
    view["candidates"] = []
    for c in _candidates(record):
        item = {"n": c["n"], "seed": c.get("seed"), "status": c.get("status"), "seconds": c.get("seconds"),
                "path": _cand_file(run_dir, c)}
        c2 = _cand_critic(c)
        if c2 is not None:
            item["critic"] = c2
        view["candidates"].append(item)
````

(f) Edit `movie_ui_batch.py`. Old:

````python
          ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs"))
````

New:

````python
          ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs", "critic"))
````

(g) Edit `movie_ui_batch.py`. Old:

````python
    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",
````

New:

````python
    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills", "critic": "stills",
````

Run: the Step 4 command. Expected: `2 failed, 4 passed` (`test_ict21_…` fails with `this workspace's bin/ltx-movie does not support --critic`, and `test_ict23_the_page`).

- [ ] **Step 6: The help fixture (R6).** The stub workspace's `bin/ltx-movie --help` prints this file, so V1 rule 18 sees `--critic` as the real tool's help does.

Edit `tests/fixtures/movie_ui/ltx-movie-help-current.txt`. Old:

````text
  --extra-ref PATH[:CAPTION]
                        an extra reference picture for every Qwen edit of the
                        run (repeatable)
````

New:

````text
  --extra-ref PATH[:CAPTION]
                        an extra reference picture for every Qwen edit of the
                        run (repeatable)
  --critic              with --shots, --seed-image and a Qwen --seed-edit-model
                        ID: the local VLM judges every panel's seed edit for
                        broken bodies and re-edits the failures
  --critic-rounds N     with --critic: at most N redo rounds (0 to 4, default 2)
````

Run: the Step 4 command. Expected: `1 failed, 5 passed` (only `test_ict23_the_page`).

- [ ] **Step 7: The page (spec 2.11; R4, R5).** Two Edits to `index.html`, then nine to `app.js`.

(a) Edit `static/movie-ui/index.html`. Old:

````html
          <p id="c-sq-shots-note" class="muted" hidden>Every panel's still is a Qwen edit of the seed, prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of characters and locations, do not apply (characters and locations still shape the story and the video).</p>
````

New:

````html
          <p id="c-sq-shots-note" class="muted" hidden>Every panel's still is a Qwen edit of the seed, prompted by that panel's own Image: text. Z-Image is not used: stills LoRAs, and the stills LoRAs of characters and locations, do not apply (characters and locations still shape the story and the video).</p>
          <label id="c-critic-box" hidden><input id="c-critic" type="checkbox"> Image critic: the local VLM checks every panel's still for broken bodies (extra, missing or fused limbs, warped faces or hands) and re-edits the failures with new seeds, up to 2 more times; the best attempt is kept, and flagged when none passes. Each round adds a VLM start.</label>
````

(b) Edit `static/movie-ui/index.html`. Old:

````html
        <p id="se-qwen-note" class="muted"></p>
      </div>
````

New:

````html
        <p id="se-qwen-note" class="muted"></p>
      </div>
      <label id="se-critic-box" hidden><input id="se-critic" type="checkbox"> Image critic: the local VLM checks each candidate for broken bodies and re-edits the failures with new seeds, up to 2 more times; the best attempt is kept, and flagged when none passes</label>
````

(c) Edit `static/movie-ui/app.js`. Old:

````js
    show($("#se-qwen-box"), model === "qwen");
````

New:

````js
    show($("#se-qwen-box"), model === "qwen");
    show($("#se-critic-box"), model === "qwen");
````

(d) Edit `static/movie-ui/app.js`. Old:

````js
    // Shots Z-Image engine spec ZE13: a seeded shots movie's Z-Image engine is sent as the seed as-is.
````

New:

````js
    out.critic = Boolean(seedEdit) && out.mode === "shots" && out.seed_edit_model !== "as-is" && S.composeEngine !== "zimage" && supported.critic !== false && $("#c-critic").checked;
    // Shots Z-Image engine spec ZE13: a seeded shots movie's Z-Image engine is sent as the seed as-is.
````

(e) Edit `static/movie-ui/app.js`. Old:

````js
    $("#c-sq-reason").textContent = seedEditReason;
````

New:

````js
    $("#c-sq-reason").textContent = seedEditReason;
    show($("#c-critic-box"), shotsSeed && !zimageSeed && !(S.options && S.options.supported && S.options.supported.critic === false));
````

(f) Edit `static/movie-ui/app.js`. Old:

````js
    $("#c-mode").value = f.mode || "chained";
````

New:

````js
    $("#c-mode").value = f.mode || "chained";
    $("#c-critic").checked = f.critic === true;
````

(g) Edit `static/movie-ui/app.js`. Old:

````js
    return {ws: S.ws, source: source, prompt: $("#se-prompt").value, model: model,
            strength: model === "zimage" ? Number($("#se-strength").value) : null,
            candidates: Number($("#se-candidates").value), seed: seedText === "" ? null : Number(seedText),
            qwen_model: model === "qwen" ? SEED_PICKER.selection().model : null, loras: model === "qwen" ? SEED_PICKER.selection().loras : null};
  }
````

New:

````js
    const body = {ws: S.ws, source: source, prompt: $("#se-prompt").value, model: model,
            strength: model === "zimage" ? Number($("#se-strength").value) : null,
            candidates: Number($("#se-candidates").value), seed: seedText === "" ? null : Number(seedText),
            qwen_model: model === "qwen" ? SEED_PICKER.selection().model : null, loras: model === "qwen" ? SEED_PICKER.selection().loras : null};
    if (model === "qwen" && $("#se-critic").checked) { body.critic = true; }
    return body;
  }
````

(h) Edit `static/movie-ui/app.js`. Old:

````js
  function seedRow(view, cand) {
    const progress = view.job && view.job.progress && view.job.progress.candidates;
    const current = progress ? progress.current : null;
    const key = cand.status + "|" + (cand.path || "") + "|" + (cand.status === "pending" && cand.n === current ? "now" : "");
````

New:

````js
  function criticText(c) {
    if (c.status === "passed") { return "critic: passed (score " + c.score + (c.attempts > 1 ? ", after " + c.attempts + " attempts" : "") + ")"; }
    if (c.status === "flagged") { return "critic: flagged — best score " + c.score + " of " + c.attempts + " attempts" + (c.defects.length ? ": " + c.defects.join("; ") : ""); }
    return "critic: not judged" + (c.reason ? " (" + c.reason + ")" : "");
  }

  function criticProgressText(c) {
    const parts = [c.ok.length + " ok"];
    if (c.redo.length) { parts.push(c.redo.length + " being redone"); }
    if (c.flagged.length) { parts.push("flagged " + c.flagged.join(", ")); }
    if (c.unjudged.length) { parts.push("not judged " + c.unjudged.join(", ")); }
    return "critic: " + parts.join(", ");
  }

  function seedRow(view, cand) {
    const progress = view.job && view.job.progress && view.job.progress.candidates;
    const current = progress ? progress.current : null;
    const key = cand.status + "|" + (cand.path || "") + "|" + (cand.status === "pending" && cand.n === current ? "now" : "") + "|" + (cand.critic ? cand.critic.status + ":" + cand.critic.score + ":" + cand.critic.attempts : "");
````

(i) Edit `static/movie-ui/app.js`. Old:

````js
    row.parts = [cell];
````

New:

````js
    row.parts = [cell];
    if (cand.critic) { row.parts.push(el("div", {cls: "muted", text: criticText(cand.critic)})); }
````

(j) Edit `static/movie-ui/app.js`. Old:

````js
      if (p.stills) { parts.push("stills " + p.stills.count + "/" + p.stills.expected); }
````

New:

````js
      if (p.stills) { parts.push("stills " + p.stills.count + "/" + p.stills.expected); }
      if (p.critic) { parts.push(criticProgressText(p.critic)); }
````

(k) Edit `static/movie-ui/app.js`. Old:

````js
        (p.face_problem ? " - the seed face was refused" : "") + counted}));
````

New:

````js
        (p.face_problem ? " - the seed face was refused" : "") + counted + (p.critic ? " - " + criticProgressText(p.critic) : "")}));
````

Run: the Step 4 command. Expected: `6 passed`.

- [ ] **Step 8: The table pins (spec 6.3 Task 3; R6).** First see them fail:

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_location_ui.py::test_lu10_compose_fields_flags_and_rule_12c tests/test_movie_ui_extra_refs.py::test_xrt19_fields_flags_and_argv tests/test_movie_ui_extra_refs.py::test_xrt22_batch_levels_groups_and_merge tests/test_movie_ui_qwen_edit.py::test_qet33_fields_flags_argv_rule_12d_and_phases tests/test_movie_ui_qwen_edit.py::test_qet37_the_batch_levels_groups_and_merge tests/test_movie_ui_shots_seed.py::test_set21_no_new_field_flag tests/test_movie_ui_batch.py::test_bt1_every_default_field_is_classified tests/test_movie_ui_builder.py::test_mut3_help_flags_fixtures_real_help_and_cache tests/test_movie_ui_http.py::test_mu14_ws_parameter_errors_and_options 2>&1 | tail -1`

Expected: `9 failed` (counts 32/33/28 and literal lists that lack `critic`).

Then fourteen Edits, each changing only the named literal:

(a) Edit `tests/test_location_ui.py`. Old:

````python
    assert len(lib.FIELD_FLAGS) == 32
````

New:

````python
    assert len(lib.FIELD_FLAGS) == 33
````

(b) Edit `tests/test_movie_ui_extra_refs.py`. Old:

````python
    assert len(lib.FIELD_FLAGS) == 32
````

New:

````python
    assert len(lib.FIELD_FLAGS) == 33
````

(c) Edit `tests/test_movie_ui_extra_refs.py`. Old:

````python
    assert len(lib.DEFAULT_FIELDS) == 33
````

New:

````python
    assert len(lib.DEFAULT_FIELDS) == 34
````

(d) Edit `tests/test_movie_ui_extra_refs.py`. Old:

````python
    assert batch.GROUPS[1] == ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs")
````

New:

````python
    assert batch.GROUPS[1] == ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs",
                               "critic")
````

(e) Edit `tests/test_movie_ui_qwen_edit.py`. Old:

````python
    assert len(lib.FIELD_FLAGS) == 32
````

New:

````python
    assert len(lib.FIELD_FLAGS) == 33
````

(f) Edit `tests/test_movie_ui_qwen_edit.py`. Old:

````python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (28, 5, 33)
````

New:

````python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (29, 5, 34)
````

(g) Edit `tests/test_movie_ui_qwen_edit.py`. Old:

````python
                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs"))
````

New:

````python
                            ("width", "height", "seed_upload", "seed_edit_model", "seed_edit_loras", "extra_refs",
                             "critic"))
````

(h) Edit `tests/test_movie_ui_shots_seed.py`. Old:

````python
    assert len(lib.FIELD_FLAGS) == 32
````

New:

````python
    assert len(lib.FIELD_FLAGS) == 33
````

(i) Edit `tests/test_movie_ui_shots_seed.py`. Old:

````python
         "--force", "--force-story", "--redo", "--story-only", "--no-review", "--seed-edit-model",
         "--seed-edit-lora", "--extra-ref"}
````

New:

````python
         "--force", "--force-story", "--redo", "--story-only", "--no-review", "--seed-edit-model",
         "--seed-edit-lora", "--extra-ref", "--critic"}
````

(j) Edit `tests/test_movie_ui_batch.py`. Old:

````python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (28, 5, 33)
````

New:

````python
    assert (len(batch.FIELD_LEVELS), len(batch.FIXED_KEYS), len(lib.DEFAULT_FIELDS)) == (29, 5, 34)
````

(k) Edit `tests/test_movie_ui_batch.py`. Old:

````python
    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",
````

New:

````python
    "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills", "critic": "stills",
````

(l) Edit `tests/test_movie_ui_builder.py`. Old:

````python
                             "--location-strength", "--seed-edit-model", "--seed-edit-lora", "--extra-ref"}
````

New:

````python
                             "--location-strength", "--seed-edit-model", "--seed-edit-lora", "--extra-ref",
                             "--critic", "--critic-rounds"}
````

(m) Edit `tests/test_movie_ui_builder.py`. Old:

````python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 32
````

New:

````python
    assert set(supported) == {k for k, _flags in lib.FIELD_FLAGS} and len(supported) == 33
````

(n) Edit `tests/test_movie_ui_http.py`. Old:

````python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 32
````

New:

````python
    assert all(payload["supported"].values()) and len(payload["supported"]) == 33
````

Run: the same command. Expected: `9 passed`.

- [ ] **Step 9: `NEW_PY` and QET11 gain the new test file (spec 6.3 Task 3).** First QET11's pin:

Edit `tests/test_qwen_edit.py`. Old:

````python
        "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py"]
````

New:

````python
        "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py",
        "tests/test_movie_ui_critic.py"]
````

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py::test_qet11_imports_and_the_new_files 2>&1 | tail -1`

Expected: `1 failed`. Then:

Edit `tests/test_movie_ui_builder.py`. Old:

````python
          "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py")
````

New:

````python
          "tests/test_movie_ui_shots_seed.py", "image_critic.py", "bin/image-critic", "tests/test_image_critic.py",
          "tests/test_movie_ui_critic.py")
````

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_qwen_edit.py tests/test_movie_ui_builder.py tests/test_movie_ui_critic.py 2>&1 | tail -1`

Expected: `29 passed`.

- [ ] **Step 10: Run the movie-UI set and compare with the baseline.** About 4 minutes.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_critic.py tests/test_vlm_lifecycle.py tests/test_clean_stop.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seed_loras.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py tests/test_lora_scope_ui.py tests/test_motion_beat_only_ui.py tests/test_movie_ui_extra_refs.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_builder.py tests/test_location_lib.py tests/test_movie_ui_seams.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_shots_zimage.py tests/test_soft_panel_count.py tests/test_lora_scope_fix.py tests/test_movie_ui_batch.py tests/test_movie_ui_jobs.py tests/test_movie_ui_progress.py tests/test_movie_ui_actions.py tests/test_qwen_edit.py 2>&1 | tee ../../ic-baseline/ui-c4.log | grep -E '^(FAILED|ERROR) ' | sed 's/ - .*//' | sort > ../../ic-baseline/ui-c4-failures.txt; tail -1 ../../ic-baseline/ui-c4.log; comm -13 ../../ic-baseline/full-base-failures.txt ../../ic-baseline/ui-c4-failures.txt
```

Expected: the summary line (`27 failed, 587 passed` at 14.7 GiB free during planning), then exactly one line from `comm`: `FAILED tests/test_movie_ui_seed_loras.py::test_cl_t34_batch_forks_are_unchanged`, which fails by design until Task 5 (R10). `tests/test_vlm_lifecycle.py` passes unedited except its base disk-reserve failure `test_bt30`. Any other `comm` line is a stop-and-report.

- [ ] **Step 11: Compile check, `node --check`, the changed-file list and the pinned-file check.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' movie_ui_lib.py movie_ui_seedgen.py movie_ui_server.py movie_ui_batch.py tests/test_movie_ui_critic.py tests/test_movie_ui_seedgen.py; done
node --check static/movie-ui/app.js && echo "app.js ok"
git diff --name-only HEAD; git status --short | grep '^??'
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected:
1. `compiled 6`, twice.
2. `app.js ok`.
3. Exactly these sixteen modified paths, each prefixed `qwen-agent-workspace/`: `movie_ui_batch.py`, `movie_ui_lib.py`, `movie_ui_seedgen.py`, `movie_ui_server.py`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `tests/fixtures/movie_ui/ltx-movie-help-current.txt`, `tests/test_location_ui.py`, `tests/test_movie_ui_batch.py`, `tests/test_movie_ui_builder.py`, `tests/test_movie_ui_extra_refs.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_qwen_edit.py`, `tests/test_movie_ui_seedgen.py`, `tests/test_movie_ui_shots_seed.py`, `tests/test_qwen_edit.py`; and one untracked `?? qwen-agent-workspace/tests/test_movie_ui_critic.py`.
4. `1 passed, 11 deselected`: no pinned file changed since C2, so no re-baseline.

- [ ] **Step 12: Commit C4.** The body names every pre-existing test file whose literal changed (spec 6.3).

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git add movie_ui_lib.py movie_ui_seedgen.py movie_ui_server.py movie_ui_batch.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_critic.py tests/test_movie_ui_seedgen.py tests/fixtures/movie_ui/ltx-movie-help-current.txt tests/test_movie_ui_builder.py tests/test_qwen_edit.py tests/test_location_ui.py tests/test_movie_ui_extra_refs.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_batch.py tests/test_movie_ui_http.py && git diff --cached --name-only | wc -l && git commit -m "movie UI: image critic checkbox in Compose and Seeds, V1 rule 12f, critic progress summary and candidate verdicts" -m "The critic compose field and --critic flag re-count the table pins in tests/test_location_ui.py, tests/test_movie_ui_extra_refs.py, tests/test_movie_ui_qwen_edit.py, tests/test_movie_ui_shots_seed.py, tests/test_movie_ui_batch.py, tests/test_movie_ui_builder.py and tests/test_movie_ui_http.py; tests/test_qwen_edit.py and tests/test_movie_ui_builder.py list the new test file; the ltx-movie help fixture gains --critic and --critic-rounds." -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: `17`, then one commit.

---

### Task 5: re-pin `test_cl_t34` to C4 (commit C5, test-only; R10)

**Files:**
- Modify `qwen-agent-workspace/tests/test_movie_ui_seed_loras.py`: `test_cl_t34_batch_forks_are_unchanged`'s `FIELD_LEVELS` literal (:413) and its three `20cee82` references (:421-423).
- Nothing else. C5 must come immediately after C4, with no commit between them.

**Interfaces:**
- Consumes (Task 4): the C4 commit, `HEAD` at the start of this task; `batch.FIELD_LEVELS["critic"] = "stills"`.
- Produces: `test_cl_t34` pinned to C4. From here on every commit keeps it green; a later commit that changes `movie_ui_batch.py` needs its own re-pin commit right after it.

- [ ] **Step 1: Check that `HEAD` is C4.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git log -1 --format='%H %s' && git status --short | wc -l`

Expected: the C4 sha followed by `movie UI: image critic checkbox in Compose and Seeds, V1 rule 12f, critic progress summary and candidate verdicts`; `0`. Anything else: stop.

- [ ] **Step 2: Run `test_cl_t34` to see it fail.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py::test_cl_t34_batch_forks_are_unchanged 2>&1 | tail -1`

Expected: `1 failed`.

- [ ] **Step 3: The `FIELD_LEVELS` literal.**

Edit `tests/test_movie_ui_seed_loras.py`. Old:

````python
        "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills",
````

New:

````python
        "seed_edit_model": "stills", "seed_edit_loras": "stills", "extra_refs": "stills", "critic": "stills",
````

- [ ] **Step 4: Write C4's sha into the pin.** Like Task 3 Step 3, the sha is known only now, so this step runs a script. It replaces every `20cee82` in the file (exactly three: the `cat-file` argument, the skip message and the `diff` argument) with C4's full sha.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 - "$(git rev-parse HEAD)" <<'EOF'
import sys
sha = sys.argv[1]
assert len(sha) == 40
path = "tests/test_movie_ui_seed_loras.py"
with open(path, encoding="utf-8") as f:
    text = f.read()
assert text.count("20cee82") == 3
text = text.replace("20cee82", sha)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("batch pin ->", sha)
EOF
git diff --stat
```

Expected: `batch pin -> <C4 sha>`; `1 file changed, 4 insertions(+), 4 deletions(-)`.

- [ ] **Step 5: Run the file.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seed_loras.py 2>&1 | tail -1`

Expected: `14 passed`.

- [ ] **Step 6: Commit C5.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ic-wt/qwen-agent-workspace && git add tests/test_movie_ui_seed_loras.py && git diff --cached --name-only && git commit -m "tests/test_movie_ui_seed_loras.py: test_cl_t34 batch pin moves to the image-critic movie UI commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: `qwen-agent-workspace/tests/test_movie_ui_seed_loras.py` only, then one commit.

- [ ] **Step 7 (controller): full suite, review, live checks.**
  1. Run `python3 -m pytest -q -p no:cacheprovider tests/` into `../../ic-baseline/full-c5-failures.txt` the same way as Task 3 Step 6. `comm -13 full-base-failures.txt full-c5-failures.txt` must be empty (`29 failed, 2983 passed, 2 skipped` during planning, the 29th being a one-off `tests/test_fleet_vision.py::test_vt20_…` daemon-startup race. If `comm` prints a test in a file no task touches, rerun that file three times: green each time means a flake, to be reported, not fixed; red is a stop-and-report during planning).
  2. The `design-reviewer` agent reviews C1, C2+C3 and C4+C5 before the feature is declared done. A review fix to `bin/ltx-movie` gets its own `test_mut26` BASELINE commit right after it, and one to `movie_ui_batch.py` its own `test_cl_t34` re-pin commit (Global Constraints).
  3. The PR merges with a merge commit. Hand live checks ICL1-ICL7 (spec Section 7) to the user. Nobody accesses macstudio.

---

## Self-review

**1. Spec coverage.**

| Spec | Where |
|---|---|
| 0.4.1, 2.1-2.4 `image_critic.py` | Task 1 Step 3; ICT1-ICT11, Review Focus 2 |
| 0.4.2, 2.7 `bin/image-critic` | Task 1 Step 5; ICT12, ICT13 (R2) |
| 0.4.3, 2.8 `bin/seed-edit` | Task 2 Steps 3-5; ICT14-ICT16 |
| 0.4.4, 2.9 `bin/ltx-movie` | Task 2 Steps 9-11; ICT17-ICT19, Review Focus 4-5 |
| 2.5 records | Task 1 (block), Task 2 (`run.json`, `seed_edits.json`); ICT4-ICT6, ICT16, ICT18 |
| 2.6 log lines, `CRITIC_RE`, parser, snapshot | Task 1 (lines), Task 4 Step 4; ICT4-ICT9, ICT20 |
| 0.4.5, 2.10.1 `movie_ui_lib.py` | Task 4 Steps 3-4; ICT20-ICT22a |
| 0.4.6, 2.10.2 `movie_ui_seedgen.py` | Task 4 Step 5; ICT22a, ICT22b |
| 0.4.7, 2.10.3 `movie_ui_server.py` | Task 4 Step 5; ICT22a, ICT22b |
| 0.4.8, 2.10.4 `movie_ui_batch.py` | Task 4 Step 5; ICT21 |
| 0.4.9, 2.11 the page | Task 4 Step 7 (R4, R5); ICT23 |
| 3 messages, 4 error handling | Task 1 (ICT2, ICT3, ICT7, ICT10-ICT12), Task 2 (ICT14, ICT17), Task 4 (ICT21, ICT22) |
| 5 VLM lifecycle rule, ICT24 | Global Constraints; ICT4, ICT5, ICT7d, ICT8; Task 4 Step 1 (ICT24), Step 10 (`test_vlm_lifecycle.py` unedited) |
| 6.3 pins | Task 1 Steps 7-8; Task 3; Task 4 Steps 6, 8, 9 (R6); Task 5 (R10) |
| K1 flag off unchanged | ICT15, ICT19, ICT21 golden argv, ICT22a/b, SET1-SET15 and the full suite |
| K2, K3 | ICT5, ICT6 |
| K4 | ICT8a-d |
| K5 | ICT4 |
| K6, IC-AC8, Section 7 | ICL1-ICL7: the user (Task 5 Step 7.3) |
| K7, IC-AC7 | Task 3 Step 6, Task 5 Step 7.1; the compile steps in every task |
| 8 Review Focus | the Review Focus section |
| Plan: commit order, BASELINE rule, merge commit | Global Constraints; Tasks 2-3 (and the same pattern for `test_cl_t34` in Tasks 4-5) |
| Q1-Q6 | Q1: Review Focus 5 test; Q2: `JUDGE_WITH_SEED` (ICT1); Q3: ICT4's `wait_for_avail` 28.0; Q4: no rounds input (Task 4 sends only `--critic`); Q5: ICT5's `cand_02.r0.png`/`r1.png`; Q6: no code |

Non-goals (0.5) stay untouched: no seed-context, cast-refs, Phase 1c, dataset or Z-Image change; reused panels are not judged; no deploy-package change.

**2. Step scan.** No step says TBD, TODO, "similar to", "handle errors" or "add tests". Every Edit carries its exact old and new text, every new file its full content, every run its command and expected summary. The plan is long by the house rule that a Sonnet executor makes no design decision, as `2026-11-23-bulk-action-clips.md` is; every code block was applied and run during the planning replay.

**3. Type and name consistency.**
- `edit_with_critic`'s parameters (`rounds`, `total`, `on_result`, `on_verdict`, `on_best`, `noun`, `tag`, `say`) are the same in Task 1's code, Task 2's two call sites and ICT16's fake.
- The block keys (`status`, `score`, `defects`, `reason`, `seed_used`, `pass_score`, `attempts`) match between `image_critic.block`, ICT4-ICT6, ICT18, `srv._cand_critic` and ICT22b; `attempts` is a list in the records and a count in the view (`criticText` uses the count).
- `critic_rounds` is None or an int in both tools; `opts["critic"]`/`args.critic` are bools; the UI field `critic` is a bool.
- The line words `ok`, `redo`, `flagged`, `unjudged` match `LINE_STATES`, `CRITIC_RE`, `critic_summary` and `criticProgressText`.
- `FakeCD` and `verdict` are defined in Task 1 and imported by Task 2's tests under those names.

**3b. Pins.** Every existing assertion the plan edits is named in a step: QET11 and `NEW_PY` (Tasks 1 and 4), `BASELINE` (Task 3), the fourteen Task 4 pins and the fixture, and `test_cl_t34` (Task 5). The replay ran the full suite at C3, C4 and C5 against the base list.

**4. Review Focus.** All five Section 8 cases are pinned (the Review Focus section); three new tests close the gaps the ICT list left.

**5. Proportion.** The spec is 1247 lines; the plan carries the code it decides, as the house rule requires.

## Risks and failure modes (not changed by this plan; for the reviewer)

- **Calibration is unknown.** `PASS_SCORE = 7` is a starting point; ICL1 may conclude the VLM is not reliable (K6). The feature is opt-in.
- **A movie-ui server restart mid-job** runs `recovery_restore`, which can start the VLM under any running forbidden job (spec 5.6). It predates this feature.
- **`--redo N` reproduces the same pictures** (Q6): the same requested seed gives the same round-0 image and the same derived seeds. A new `--image-seed` gives new pictures.
- **Disk reserve.** At about 15-22 GiB free, 26 batch-fork tests fail at base on the 20 GiB reserve; Step 0.2's list tells them apart from regressions.
