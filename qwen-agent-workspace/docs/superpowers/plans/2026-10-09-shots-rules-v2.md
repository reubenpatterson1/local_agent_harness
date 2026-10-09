# Shots Rules v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement shots rules v2: S8-S12, the animal exemption, the S9 auto-repair and up to two rewrites. Then run live gate L-R1, a new story written from scratch.

**Architecture:** The spec holds every changed byte as code blocks, and their result hashes were verified by an independent rebuild. This plan applies those blocks with one script and gates each task on the hash plus the spec's measured test checkpoints.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md` (commit 49f7a59). Every exact value lives in the spec; this plan only orders and gates.

## Global Constraints

- WS = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. Branch `qwen-agent-redteam`. Base `49f7a59`, which is the spec commit; code is unchanged since e85ed35.
- **Code is applied ONLY by** `python3 /Users/reubenpatterson/local_model_harness/.superpowers/sdd/2026-10-09-shots-rules-v2/apply_v2.py <lib|movie|tests>`, run from WS.
  - The script rebuilds the file from the repo copy plus the spec's blocks.
  - It writes the file only if the spec's sha256 matches, and prints `HASH MISMATCH; nothing written` otherwise.
  - Never retype code from the spec. It contains U+2019/201C/201D.
- `tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` run with plain `python3`, never pytest. pytest always runs with `--color=no -p no:cacheprovider`, and results are judged by return code.
- Stage files by explicit path only. The tree has unrelated dirty files (`bin/ltx-story-video`, `bin/qwen-agent`, `ltx_ceiling.json`, `ltx_video_skill.py`, `.gitignore`s); never stage those.
- No GPU work, no servers and no subagents in Tasks 1-4.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Expected hashes (spec 3.13, 5.5, 8.5)

| File | sha256 |
|---|---|
| `character_lib.py` | `61539042fde24e5f126b1492e1d9d1394c64096d8c40a864e6990f8c98a21ce0` |
| `bin/ltx-movie` | `7c4315dbeb467a8fb09bbf99a783ce8da3aa1ac8af97e919a4c64eebe206bfc3` |
| `tests/test_shots_mode.py` | `2673052b0aaca13e701cd34c3626ec3c4a36bc3bc43cb5e35267461fb0856381` |

## Review Focus (spec 13)

These are the inputs most likely to go wrong:
- false positives in S8 contact and S10 extras on ordinary prose;
- a repair that corrupts a story or changes who is on screen;
- the two-rewrite exit paths;
- continuous mode must stay unchanged.

---

### Task 1: Baseline (orchestrator; no commit)

- [ ] **Step 1: Run R1 and R2 from WS.** Run the 11 suites, then deploy under both interpreters. Expected results:
  - offline 344/344, story-images 101/101, mlx-render 443/443, video-skill 146/146, manifest-chain 32/32, image-fit 77/77;
  - forbidden-imports ok;
  - casting 178, z_image_skill_cache 13, iterate flags 13, pipeline_log 17, shots 54;
  - deploy 165 under pytest and 165 under unittest with `/usr/bin/python3`.

---

### Task 2: `character_lib.py` plus fixtures (spec 3, 8.1)

**Files:**
- Modify: `character_lib.py`
- Create: `tests/fixtures/shots_rules_v2/{windup,rules-as-generated,rules-edited,full20,ls1}.md`

- [ ] **Step 1: Copy the five fixtures byte for byte.** Use the source paths in the spec 8.1 table. One source is outside WS: `.superpowers/sdd/2026-10-06-shots-mode/live/rules-story.as-generated.md`. Then run `shasum -a 256 tests/fixtures/shots_rules_v2/*.md`. Each must equal its 8.1 hash. If any differs, STOP and report.
- [ ] **Step 2: Apply the library change.** Run `python3 …/apply_v2.py lib`. Expected output: `character_lib MATCH 6153…` then `wrote /character_lib.py`.
- [ ] **Step 3: Run the checkpoints.**
  - The casting set (the 6 files of R1's casting line) must give `178 passed`.
  - The unedited shots suite must give **exactly 15 failed, 39 passed**, and the failures must be exactly S3, S9-S18, S35, S36, S38 and S40 (spec 11 item 2).
- [ ] **Step 4: Run** `python3 tests/test_ltx_movie_offline.py`, expecting `OK 344/344`.
- [ ] **Step 5: Commit.**
  - Run `git add character_lib.py tests/fixtures/shots_rules_v2/`.
  - Message: `character_lib: shots rules v2 — S8-S12, animal exemption, identity sentences, grouped rewrite block, S9 repair`.

---

### Task 3: `bin/ltx-movie` (spec 5.1, 5.3)

**Files:** Modify: `bin/ltx-movie`

- [ ] **Step 1: Apply the change.** Run `python3 …/apply_v2.py movie`. Expected output: `ltx-movie MATCH 7c43…` then `wrote /bin/ltx-movie`. Confirm the file is still executable (`test -x bin/ltx-movie`).
- [ ] **Step 2: Run the checkpoints.**
  - `python3 tests/test_ltx_movie_offline.py` must print `OK 344/344`.
  - Iterate flags must give `13 passed`.
  - The unedited shots suite must give **exactly 17 failed, 37 passed**: Task 2's 15 failures plus S37 and S39.
- [ ] **Step 3: Commit.**
  - Run `git add bin/ltx-movie`.
  - Message: `ltx-movie: shots rules v2 story template, S9 repair before validation, up to two rewrites`.

---

### Task 4: `tests/test_shots_mode.py` (spec 8.2, 8.3)

**Files:** Modify: `tests/test_shots_mode.py`

- [ ] **Step 1: Apply the change.** Run `python3 …/apply_v2.py tests`. Expected output: `tests MATCH 2673…` then `wrote /tests/test_shots_mode.py`.
- [ ] **Step 2: Run the shots suite.** It must give **81 passed**, with rc 0.
- [ ] **Step 3: Run the one-session check.** Run the shots suite together with the 6 casting files and expect `259 passed` (81 + 178).
- [ ] **Step 4: Commit.**
  - Run `git add tests/test_shots_mode.py`.
  - Message: `tests: shots rules v2 — 8 updated tests, 27 new (S21, S54-S59, S80-S99)`.

---

### Task 5: D5 pointer (spec 0.3 D5, 1.4)

**Files:** Modify: `docs/superpowers/specs/2026-10-06-shots-mode-design.md`

- [ ] **Step 1: Add the pointer paragraph.** Add the Status pointer exactly as spec 1.4 gives it, stating that the v2 spec amends this spec.
- [ ] **Step 2: Commit** that file only.

---

## Final Acceptance (orchestrator)

- **A1.** Shots 81 and one-session 259, both from the main thread.
- **A2.** Full R1/R2: every Task 1 line, with shots now at 81. `git diff --stat 49f7a59 HEAD` lists only the five files above plus the fixtures directory.
- **A3.** The full spec 8.6 mutation table (71 rows), run against the real WS. Expect 71/71 caught, and the tree restored afterwards.
- **A4.** A design-reviewer code review of `49f7a59..HEAD`. Its first step is verdict 1: rebuild from the spec and diff. If the verdict is NEEDS-FIX, the reviewer writes a verbatim patch and the executor applies it.
- **A5.** Push to both remotes, after the user-approved push pattern.

## Live gate (spec 10)

- **10.1 preconditions:** story-server SERVING vision, no concurrent GPU work.
- **10.2a trials:** three Phase 1-only trials. Record the violations per rule for the first draft, rewrite 1 and rewrite 2; the rc; the wall-clock; and the repairs.
- **L-R1:** if a trial passed, render it, then judge it twice and record against spec 10.3.
- **L-R1b:** if no trial passed, use the hand-edit runbook and label the run as hand-edited.
