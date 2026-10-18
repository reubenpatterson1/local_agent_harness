# Robust Story Generation and the LoRA Catalog (piece E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `bin/ltx-movie`'s single-prompt Phase 1 with a robust engine in which the story model writes a JSON plan and then one panel at a time, code assembles `story.md` and pastes every fixed sentence verbatim, deterministic checks run on every round, a local critic proposes per-panel patches that code applies to named fields only, and `bin/judge-story --patches` is an optional gate; and add a versioned LoRA catalog (`bin/lora-catalog`) whose style, motion and physics LoRAs the plan picks per panel and Phases 2-4 apply, with library characters used only when declared with `--character`.

**Architecture:** Everything model-facing and every check lives in a new stdlib-only `story_engine.py`, loaded by path (never at import) by `bin/ltx-movie` and `bin/judge-story`; it calls `bin/qwen-agent` only as a one-shot subprocess and loads `character_lib.py`, `lora_catalog.py` and `fleet_lib.py` by path inside functions. The catalog file, its validation, the safetensors header reader, the character folding and the trigger prefix rule live in a new stdlib-only `lora_catalog.py` with a small CLI, `bin/lora-catalog`. `bin/ltx-movie` resolves the engine in `main()` (`--story-legacy` keeps today's path byte for byte), runs `story_engine.run` or `story_engine.recheck` from `_phase1_robust`, and turns the plan's picks into `--lora`/`--lora-trigger` flags for Phase 2 and a per-panel `catalog_loras.json` for Phase 3, which `bin/ltx-story-manifest` copies into the manifest and `bin/ltx-mlx-render` applies, checks and records per clip.

**Tech Stack:** Python 3.13 (`python3`, pytest 8.3.4) and Python 3.9.6 (`/usr/bin/python3`, compile check only); standard library only in every new module; Pillow only where it already is (`bin/ltx-story-manifest`); the existing `anthropic`/`jsonschema` of `bin/judge-story`; a fake `bin/qwen-agent`, a fake `bin/judge-story` and a fake fleet from the new `tests/story_engine_testutil.py`.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md` as amended at `7a3e1f0` (the user's three answers: the fallback `sisters_sorrow` premise, a preference bar of at least 5 of 8 (RSR4), and declared-only casting enforced by RS37, P13 and N15). Every Edit below is written against `qwen-agent-redteam` at `7a3e1f0`, whose code tree is the code tree of `5eed461` (piece D merged; `92124d6` and `7a3e1f0` change only the spec). The spec cites line numbers at `1b651da`; `bin/ltx-movie` and the other touched files are unchanged since, and every Edit locates its old text itself. The spec is final; this plan changes no design decision. Where the plan had to read the spec, or the spec was silent, the reading is listed as a proposed ruling in "Plan decisions" at the end.

## Global Constraints

From the spec, verbatim (requirement IDs in brackets):

- [0.3] "**Not changed:** `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agent`, every fleet test (piece D owns them), `character_lib.py`, `ltx2_mlx_video_skill.py`, `z_image_skill.py`, `bin/character`, every other file. E calls `bin/qwen-agent` only as a subprocess and loads `fleet_lib.py` read-only by path."
- [0.4] Out of scope: "Changing S1-S12, `character_lib.py`, the legacy templates, or the legacy Phase 1 code path (it stays byte-identical under `--story-legacy`)."; "Calling a model server directly (every model call is a `bin/qwen-agent` subprocess)."; "Auto-casting library characters: forbidden, not merely out of scope (RS37)."; "Per-panel style LoRAs, per-panel stills LoRAs, more than one catalog stills LoRA."; "Training LoRAs; downloading LoRAs; editing the character `.triggers` registry from `bin/lora-catalog`."; "Images for the critic; tracing propagation from `bin/ltx-movie`."; "Any change to the render math, clip reuse rules for non-catalog clips, or Phase 4 policy."
- [RSK1] "`python3 -m pytest tests/ -q -rA` from `WS` gives the baseline recorded immediately before implementation (after piece D is in) plus every RST/LCT test passing and the Section 5.5 edited tests passing, with **no lost pass**. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the same `n` as the baseline."
- [RSK2] "`/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on every new or changed file (no `match`, no `X | Y` annotations, no parenthesised context managers, no `zip(strict=)`)."
- [RSK3] "Standard library only in `story_engine.py`, `lora_catalog.py`, `bin/lora-catalog`. Every touched file keeps its existing import constraints: `bin/ltx-movie` adds no top-level import; `bin/ltx-story-manifest` keeps stdlib + Pillow; `bin/ltx-mlx-render` adds no import; `bin/judge-story` adds no import; `bin/ltx-story-images` adds no top-level import."
- [RSK4] "Tests never use the real `HOME`, never read or write the real `generated/loras/catalog.json` or `generated/characters/`, never render video, never contact a real model server, daemon or the Anthropic API."
- [RSK5] "`--story-legacy` reproduces today's Phase 1 prompt and `bin/qwen-agent` argv byte for byte, and today's default dry-run output byte for byte (the existing golden `tests/fixtures/casting_baseline/ltx_movie_dry_run.txt`)."
- [RS34] "New code in `bin/ltx-movie` adds **no** occurrence of: `["--model", args.story_model]`, `["--context-window", str(args.story_context_window)]`, `"--workspace", WS,`, `_render_flags(args)`, `os.path.join(WS, "bin", "ltx-mlx-render")`, `cmd += ["--image", args.seed_downscaled_path]`, `phase1_cmd += ["--image", paths["seed_downscaled"]]`, `\n        cmd += ["--seed-image", args.seed_image]` (newline plus eight spaces, as L29d anchors it), `phase2_cmd += ["--seed-image", args.seed_image]`, `"--glob"`, `"--engine"`, `sudo -S`; the body of `phase2_stills` gains no `no_stills` text. New code in `bin/ltx-story-images` adds no occurrence of `_compose_prompt(`, `"source": "generated"`, `"source": "seed"`, `_panel_seed(args.seed, i, grounded)`."
- [5.1] "New tests are pytest functions with plain `assert` (no `check()` helper). Every test that runs `bin/ltx-movie` code sets, via `monkeypatch.setenv` or the subprocess `env`: `HOME` = a temp dir, `CHARACTER_LIBRARY_DIR` = a temp dir, `LORA_CATALOG_DIR` = a temp dir, `QWEN_AGENT_DAEMON_URL` = `http://127.0.0.1:<closed port>` (from `fleet_testutil.free_port()`), `STORY_PIPELINE_LOGGED=1`. Tests needing `--judge` set `ANTHROPIC_API_KEY=test-not-a-key` and use the fake `bin/judge-story`."; "No test starts `ltx-2-mlx`, `z_image_skill`, a real model server, a real daemon, or the Anthropic API. Render tests use `--dry-run` or monkeypatched `SKILL.generate_video`, with LoRA files of a few bytes."
- [RS37] "Using a library character is a declared action: a character from `character_lib.library_dir()` appears in a story only when the user passes `--character NAME` (or `--cast PHRASE=NAME` on an existing story). No stage -- planner, panel writer, critic, judge patch, LoRA selection -- may introduce one."
- [0.6] "Every requirement RS1-RS37 and LC1-LC20 is a must-have. Nothing else is built."

House rules for this plan:

- `WS` = `/Users/reubenpatterson/local_agent_harness/qwen-agent-workspace`. The git root is one level up, so `git diff --name-only` paths carry the `qwen-agent-workspace/` prefix. Branch `qwen-agent-redteam`. Run every command from `WS` unless a step says otherwise.
- Files this plan creates: `story_engine.py`, `lora_catalog.py`, `bin/lora-catalog`, `tests/story_engine_testutil.py`, `tests/test_story_engine.py`, `tests/test_lora_catalog.py`. Files it modifies, and no others: `bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-mlx-render`, `bin/judge-story`, `bin/iterate-story`, `scripts/deploy/build_pkg.py` (the `PIPELINE_FILES` tuple only), `tests/test_deploy_pkg.py`, `tests/test_ltx_movie_offline.py`, `tests/test_casting_regression.py`, `tests/test_casting_pipeline.py`, `tests/test_shots_mode.py`. `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agent`, `character_lib.py`, every fleet test, `docs/` and every other file stay byte-identical.
- Every code block in this plan is copied exactly, byte for byte. An "Edit" replaces one block of old text, which occurs exactly once in the file at that moment, with the new text; if the old text does not occur exactly once, stop and report: do not adapt it. An "Append" adds two empty lines after the file's current last line, then the block. A "Create" writes a new file whose whole content is the block. Never retype a block from the spec when this plan shows it. Blocks that contain three backticks are fenced with four.
- Tests and commands never touch the real `HOME`, never write `generated/loras/` or `generated/characters/`, never render video, never contact 192.168.1.x or any real model server, daemon or the Anthropic API; the new tests enforce this themselves (Task 17's RST63). The live protocol at the end is human-run, not an executor task.
- Every pytest run first prints a `pytest_asyncio` `PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope`, and `load_module()` `DeprecationWarning`s; both are expected. Durations and warning counts vary; only the pass/fail counts matter. macOS has no `timeout` command; do not use it.
- Commit hygiene: the working tree has unrelated untracked paths (`../.DS_Store`, `../.claude/`, `../agent/__pycache__/`, `../bin/`); never stage them. Stage only the paths each task names, check `git diff --cached --name-only` before each commit, put `(story RS<n>)` and/or `(catalog LC<n>)` in every commit subject, and end every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the Step 6 commands pass it as a second `-m`).
- Pre-tested: every task was implemented from this plan's blocks in a scratch copy of `7a3e1f0`'s tree (`git archive HEAD`, outside the repository, under a temporary `HOME`); each RED and GREEN line below is the one observed there, on this Mac, and every changed file compiled under both interpreters. Replaying this plan's Creates, Appends and Edits in order on that tree reproduces the tested final tree byte for byte (checked by parsing this file back into edits and diffing the result).

## Review Focus

These five inputs are implied by the spec, are the ones most likely to hit a real user first, and no RST/LCT test exercises them. Each is pinned by a test in its owning task.

1. **A model-written referring phrase with a non-ASCII letter** (`"the café owner"`; `character_lib.normalize_phrase` accepts only ASCII letters). Expected: P3 names the exact word, the plan repair call (RS8) carries the message and a corrected second reply proceeds; an uncorrected one ends in exit 2 listing the P3 message (patches cannot change phrases), never exit 1 or a traceback. Test: `test_story_focus_1_a_non_ascii_phrase_is_repaired_or_reported` (Task 9).
2. **A one-panel story** (`--panels 1`). Expected: the plan prompt asks for `use climax.`, P5/P6 accept a single `climax` beat, and the run assembles and passes a one-panel story.md. Test: `test_story_focus_2_a_one_panel_story` (Task 9).
3. **Ctrl-C during a long run** (a 30-panel run takes up to an hour, RSX2). Expected: the interrupt propagates, an existing story.md is untouched, `story_rounds/` keeps the partial prompts and replies with `run.json` `exit` still null, and the next run renames that directory aside and starts fresh. Test: `test_story_focus_3_ctrl_c_during_a_run_keeps_story_md` (Task 9).
4. **A cataloged LoRA file deleted after Phase 1 picked it** (the user tidies a downloads folder between Phase 1 and the render). Expected: Phase 3 and Phase 2 exit 2 with LC13's `changed since it was cataloged` line naming the file, write no `catalog_loras.json`, and never crash on the missing file. Test: `test_story_focus_4_a_cataloged_lora_deleted_after_phase_1` (Task 13).
5. **A narrative and model text outside ASCII** (CJK, an em dash, an accented word). Expected: the prompts carry the narrative unchanged, and `plan.json` and `story.md` are written as UTF-8 text (no `\u` escapes) and read back unchanged. Test: `test_story_focus_5_non_ascii_text_round_trips` (Task 11).

---

## File Structure

| File | Change | Responsibility after this plan |
|---|---|---|
| `lora_catalog.py` | Create (Task 2) | The catalog file: schema validation, atomic save under `fcntl` lock, safetensors header (rank, alpha, lora pairs), folded library characters, character LoRA paths and triggers, base-model compatibility, `prefix_triggers`, `verify_entry`. Stdlib only. |
| `bin/lora-catalog` | Create (Task 3) | `add`, `list`, `remove`, `verify` (exit 0/1/2). |
| `story_engine.py` | Create (Task 4), append (Tasks 5-10) | In file order: constants and `StoryContext`, loaders, the agent call, JSON extraction (Task 4); the plan prompt, compatible set, normalization, P/L checks, RS37 identities and P13 (Task 5); lexicons, panel prompt, cleanup, assembly, N checks, N15 (Task 6); the critic (Task 7); patches (Task 8); the run, ranking, judge gate, outputs (Task 9); re-check and `plan_free_report` (Task 10). Stdlib only; loads `character_lib.py`, `lora_catalog.py`, `fleet_lib.py`, `bin/ltx-story-manifest` by path inside functions. |
| `bin/ltx-movie` | Modify (Tasks 11-13) | Flags, `_resolve_story_engine`, `_story_context`, `_phase1_robust` and the review gate, the stale-plan move on the legacy path, the robust dry-run block, catalog flags for Phases 2-3; docstring paragraph. No new import. |
| `bin/ltx-story-manifest` | Modify (Task 14) | `--catalog-loras`: per-panel `catalog_loras`, triggers prefixed to `motion_prompt`. |
| `bin/ltx-story-images` | Modify (Task 14) | `--lora-trigger`: triggers prefixed to generated panels' prompts. |
| `bin/ltx-mlx-render` | Modify (Task 15) | `catalog_loras` validation, kind `catalog` units between global and character LoRAs, provenance `catalog_id`, duplicate and sha checks before `--dry-run`. No new import. |
| `bin/judge-story` | Modify (Task 16) | `--patches`: `submit_review`, `judgment.patches.json`. No new import. |
| `bin/iterate-story` | Modify (Task 16) | Deprecation notice; a plan.json story is regenerated by `bin/ltx-movie --judge`. |
| `scripts/deploy/build_pkg.py` | Modify (Task 4) | `PIPELINE_FILES` ships `story_engine.py` and `lora_catalog.py`. |
| `tests/story_engine_testutil.py` | Create (Task 2), append (Tasks 4-7) | Section 5.1 environment, LoRA/catalog/character builders, the temp workspace with fake `bin/qwen-agent` and `bin/judge-story`, plan/panel/critic builders, `FakeFleet`, the real-catalog sentinel. |
| `tests/test_lora_catalog.py` | Create (Task 2), append (Tasks 3, 4, 11, 13-15) | LCT1-LCT30 and Review Focus 4. |
| `tests/test_story_engine.py` | Create (Task 4), append (Tasks 5-12, 16, 17) | RST1-RST58, RST61-RST63 and Review Focus 1-3 and 5. |
| `tests/test_deploy_pkg.py` | Modify (Task 4) | Section 5.5's `PIPELINE` edit and the four counts it implies. |
| `tests/test_shots_mode.py` | Modify (Tasks 11, 12) | `movie_ws` links the two new modules; `test_s50`, `test_s99` pin `--story-legacy`. |
| `tests/test_ltx_movie_offline.py`, `tests/test_casting_regression.py`, `tests/test_casting_pipeline.py` | Modify (Task 12) | Section 5.5's `--story-legacy` edits (plus L11). |

The suite stays green after every task. One ordering is deliberate: Task 11 makes `main()` select the robust engine while the dry run still prints today's Phase 1 block (so every dry-run golden still matches), and Task 12 switches the dry run and migrates the dry-run tests in the same commit.

---

### Task 1: Baseline record (orchestrator; no code, no commit)

Implements RST60's "before the change" half and the import baseline of RST62. Nothing is written into the repository.

**Files:**
- Create (outside git, never staged): `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story/` with `base-commit.txt`, `baseline-pytest.txt`, `baseline-scripts.txt`, and `baseline-notes.txt` only if something differs.

**Interfaces:** Consumes nothing. Produces the files Task 18 compares against.

- [ ] **Step 1: Confirm the starting point (piece D in, the amended spec in, nothing of this plan yet).**

```bash
cd /Users/reubenpatterson/local_agent_harness/qwen-agent-workspace
git status --short            # expected: only ?? ../.DS_Store, ?? ../.claude/, ?? ../agent/__pycache__/, ?? ../bin/
git log --oneline -1 -- docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md   # expected: 7a3e1f0 docs: E spec — declared-only casting (RS37, P13, N15), ...
grep -c "^### RS37" docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md        # expected: 1
ls story_engine.py lora_catalog.py bin/lora-catalog tests/test_story_engine.py 2>&1 | grep -c "No such file"   # expected: 4
wc -l < bin/ltx-movie         # expected: 1913
grep -c "def delegate_once(daemon_url, skill, task, host_id, images=None, trace=None)" fleet_lib.py   # expected: 1 (piece D is in)
```

If any expected value differs, stop and report: every Edit below was written against this tree.

- [ ] **Step 2: Record the base commit and the pytest baseline (about 10 min).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story
mkdir -p $D
git rev-parse HEAD > $D/base-commit.txt
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' $D/baseline-pytest.txt
```

Expected (observed on the scratch copy): last line `1 failed, 1261 passed, 1 skipped, 274 warnings in ...`; the only `FAILED` line is `FAILED tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and the only `SKIPPED` line is `SKIPPED [1] tests/test_fleet_lib.py:272: no fleet.env on this host`. If your counts differ (another environment can pass or skip a different number of host-dependent tests), write the actual line into `$D/baseline-notes.txt`; Task 18 compares against what is recorded here, not against these literals.

- [ ] **Step 3: Record the plain-python scripts.**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story
for f in test_ltx_movie_offline test_ltx_mlx_render test_ltx_story_images test_ltx2_mlx_video_skill test_ltx_image_fit test_ltx_story_manifest_chain test_ltx_chain test_ltx_multiframe test_ltx_t2v_offline test_ltx_story_video test_mps_guard_metric test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory test_qwen_agent_danger_auto_approve; do
  printf '%s: ' "$f"; python3 tests/$f.py 2>&1 | tail -1
done | tee $D/baseline-scripts.txt
```

Expected (observed):

```text
test_ltx_movie_offline: OK 344/344
test_ltx_mlx_render: OK 440/443
test_ltx_story_images: OK 101/101
test_ltx2_mlx_video_skill: OK 146/146
test_ltx_image_fit: OK 77/77
test_ltx_story_manifest_chain: OK 32/32
test_ltx_chain: OK 51/51
test_ltx_multiframe: ModuleNotFoundError: No module named 'ltx_video_skill'
test_ltx_t2v_offline: ModuleNotFoundError: No module named 'ltx_video_skill'
test_ltx_story_video: OK 216/216
test_mps_guard_metric: ModuleNotFoundError: No module named 'mps_guard'
test_qwen_agent_context_budget: OK 68/68
test_qwen_agent_image_oneshot: OK 25/25
test_qwen_agent_session_memory: OK 205/205
test_qwen_agent_danger_auto_approve: OK 37/37
```

The three `ModuleNotFoundError` lines are pre-existing and unrelated; they must read the same at Task 18.

---

### Task 2: lora_catalog.py: the catalog schema, header reader, folding, compatibility and prefix rule

Implements LC1-LC6 and LC18 (the whole of `lora_catalog.py`), plus the shared test helpers of spec 5.1/5.2 that the catalog tests need. Tests LCT1-LCT5, LCT6a (the `compatible` half of LCT6; LCT6b, the planner's compatible set, is in Task 5), LCT26, and `test_lct3b_save_sorts_and_is_atomic`.

**Files:**
- Create: `tests/story_engine_testutil.py`
- Create: `tests/test_lora_catalog.py`
- Create: `lora_catalog.py`

**Interfaces:**
- Consumes: `character_lib.list_names`, `load_character`, `registered_triggers`, `CharacterError` (existing; loaded by path).
- Produces: In `lora_catalog`: `SCHEMA_VERSION`, `CATALOG_ENV`, `STILLS_BASE_MODEL`, `KINDS`, `TARGETS`, `ID_RE`, `TRIGGER_RE`, `MAX_TRIGGERS`, `TEXT_MAX`, `ENTRY_KEYS`; `CatalogError`; `utc_now() -> str`; `catalog_dir(ws) -> str`; `catalog_path(ws) -> str`; `empty_catalog() -> dict`; `validate_entry(entry)`; `validate_catalog(data)`; `load_catalog(path) -> dict`; `save_catalog(path, data)`; `catalog_lock(path)` (a `with` object); `file_sha256(path) -> str`; `read_safetensors_header(path) -> dict`; `rank_alpha(header) -> (int|None, int|None)`; `has_lora_pairs(header) -> bool`; `fold_characters(ws) -> [dict]`; `character_paths(ws) -> {realpath: (name, "video"|"stills")}`; `character_triggers(ws) -> {trigger_lower: name}`; `compatible(entry, model) -> bool`; `prefix_triggers(prompt, triggers) -> str`; `verify_entry(entry, all_entries, char_triggers) -> [str]`. In `tests/story_engine_testutil.py` (imported as `seu`): `REAL_CATALOG`, `REAL_CATALOG_STAT`, `_stat_or_none(path)`, `DESC_K`, `DESC_R`, `CHARACTER_BASE_MODEL`, `VIDEO_MODEL`, `STILLS_MODEL`, `set_story_env(monkeypatch, tmp_path) -> {"home", "lib", "catalog"}`, `fake_safetensors(path, rank, alpha, pairs=True, metadata=None, data=...)`, `sha256_file(path)`, `catalog_entry(path, entry_id, kind="motion", target="video", triggers=(), rank=16, base_models=(VIDEO_MODEL,), default_strength=0.8, strength_range=(0.5, 1.0), description=..., use_when=..., avoid_when="")`, `make_catalog(directory, entries) -> path`, `lora_file(directory, name, rank=16, alpha=None, pairs=True) -> path`, `make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True, strength=None, base_model=CHARACTER_BASE_MODEL)`, `kyra(lib, **kw)`, `ronin(lib, **kw)`, `make_untrained(lib, name)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_lct1_import_set_and_stills_base_model`, `test_lct2_catalog_path`, `test_lct3_entry_validation`, `test_lct3b_save_sorts_and_is_atomic`, `test_lct4_safetensors_header`, `test_lct5_character_folding`, `test_lct6a_compatibility`, `test_lct26_prefix_triggers`.

**1.1.** Create `tests/story_engine_testutil.py` with exactly this content:

```python
"""Shared helpers for tests/test_story_engine.py and tests/test_lora_catalog.py (robust story
engine and LoRA catalog spec, docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md
Section 5.2).

Not a test module (pytest does not collect it). Every helper writes under a tmp_path the caller
passes in; nothing here reads or writes the real HOME, generated/loras/ or generated/characters/.
REAL_CATALOG_STAT is captured when this module is first imported, so RST63 can prove the real
catalog file was never touched during the session.
"""

import hashlib
import json
import os
import struct
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TESTS = os.path.join(WS, "tests")
sys.path.insert(0, WS)
sys.path.insert(0, TESTS)

import fleet_testutil  # noqa: E402

REAL_CATALOG = os.path.join(WS, "generated", "loras", "catalog.json")


def _stat_or_none(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


REAL_CATALOG_STAT = _stat_or_none(REAL_CATALOG)

DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"
CHARACTER_BASE_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
VIDEO_MODEL = "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"
STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo"


def set_story_env(monkeypatch, tmp_path):
    """Section 5.1's environment for one test: HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR
    under tmp_path, QWEN_AGENT_DAEMON_URL at a closed loopback port, STORY_PIPELINE_LOGGED=1,
    and no ANTHROPIC_API_KEY. Returns {"home", "lib", "catalog"} (paths as str)."""
    home = os.path.join(str(tmp_path), "home")
    lib = os.path.join(str(tmp_path), "characters")
    catalog = os.path.join(str(tmp_path), "loras")
    for path in (home, lib, catalog):
        os.makedirs(path, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", lib)
    monkeypatch.setenv("LORA_CATALOG_DIR", catalog)
    monkeypatch.setenv("QWEN_AGENT_DAEMON_URL", "http://127.0.0.1:%d" % fleet_testutil.free_port())
    monkeypatch.setenv("STORY_PIPELINE_LOGGED", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_AGENT_PREFLIGHT_DONE", raising=False)
    return {"home": home, "lib": lib, "catalog": catalog}


def fake_safetensors(path, rank, alpha, pairs=True, metadata=None, data=b"\x00" * 16):
    """Write a minimal safetensors file: an 8-byte little-endian header length, the JSON
    header (one lora_A tensor of shape [rank, 8], plus its lora_B pair when pairs, plus
    __metadata__ with lora_alpha when alpha is not None, merged with metadata), then data.
    Returns path."""
    header = {"blocks.0.attn.to_q.lora_A.weight":
              {"dtype": "F16", "shape": [rank, 8], "data_offsets": [0, 8]}}
    if pairs:
        header["blocks.0.attn.to_q.lora_B.weight"] = {"dtype": "F16", "shape": [8, rank],
                                                     "data_offsets": [8, 16]}
    meta = {}
    if alpha is not None:
        meta["lora_alpha"] = str(alpha)
    meta.update(metadata or {})
    if meta:
        header["__metadata__"] = meta
    raw = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(raw)) + raw + data)
    return path


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def catalog_entry(path, entry_id, kind="motion", target="video", triggers=(), rank=16,
                  base_models=(VIDEO_MODEL,), default_strength=0.8, strength_range=(0.5, 1.0),
                  description="a test LoRA", use_when="a test fits", avoid_when=""):
    """A valid catalog entry for the existing file at path (sha256 and bytes from the file)."""
    return {"id": entry_id, "kind": kind, "path": os.path.abspath(path),
            "sha256": sha256_file(path), "bytes": os.path.getsize(path),
            "base_models": list(base_models), "target": target, "triggers": list(triggers),
            "rank": rank, "alpha": rank, "default_strength": default_strength,
            "strength_range": list(strength_range), "description": description,
            "use_when": use_when, "avoid_when": avoid_when, "added_at": "2026-10-17T12:00:00Z"}


def make_catalog(directory, entries):
    """Write <directory>/catalog.json with the given entries (sorted by id) and return its
    path. The directory is created."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "catalog.json")
    data = {"schema_version": 1, "entries": sorted(entries, key=lambda e: e["id"])}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def lora_file(directory, name, rank=16, alpha=None, pairs=True):
    """A fake safetensors LoRA <directory>/<name>.safetensors (alpha defaults to rank)."""
    os.makedirs(directory, exist_ok=True)
    return fake_safetensors(os.path.join(directory, name + ".safetensors"), rank,
                            rank if alpha is None else alpha, pairs=pairs)


def make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True,
                   strength=None, base_model=CHARACTER_BASE_MODEL):
    """Write a valid trained character.json under lib/name (character library spec 2.2 shape):
    a 16-byte lora/video.safetensors, plus a 16-byte lora/stills.safetensors when stills, each
    entry with its real sha256. Returns the dict."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
               "face_height": 0.38,
               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video_path = os.path.join(cdir, "lora", "video.safetensors")
    with open(video_path, "wb") as f:
        f.write(VIDEO_BYTES)
    video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
             "base_model": base_model, "rank": 32, "alpha": 32, "steps": 1000,
             "trained_at": "2026-10-06T02:00:00Z", "sample_path": None, "control_path": None}
    stills_entry = None
    if stills:
        stills_path = os.path.join(cdir, "lora", "stills.safetensors")
        with open(stills_path, "wb") as f:
            f.write(STILLS_BYTES)
        stills_entry = {"path": stills_path, "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                        "base_model": STILLS_MODEL, "rank": 16, "alpha": 16, "steps": 2400,
                        "trained_at": "2026-10-06T03:00:00Z", "sample_path": None,
                        "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": descriptor, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": "trained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def kyra(lib, **kw):
    return make_character(lib, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K, **kw)


def ronin(lib, **kw):
    return make_character(lib, "ronin", "roninmn", "the ronin", "man", DESC_R, **kw)


def make_untrained(lib, name):
    """A valid untrained character (no LoRAs) under lib/name."""
    data = make_character(lib, name, name + "trg", "the " + name, "person",
                          "an old man with a white beard wearing a saffron robe and beads")
    data["status"] = "untrained"
    data["loras"] = {"video": None, "stills": None}
    with open(os.path.join(lib, name, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data
```

**1.2.** Create `tests/test_lora_catalog.py` with exactly this content:

```python
"""Tests for the LoRA catalog (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md
Section 5.4, LCT1-LCT30): lora_catalog.py, bin/lora-catalog, and the catalog's path through
bin/ltx-movie, bin/ltx-story-manifest, bin/ltx-story-images and bin/ltx-mlx-render.

Run from the workspace root: python3 -m pytest tests/test_lora_catalog.py
Plain pytest asserts only. Every test runs under Section 5.1's environment (the autouse
story_env fixture): HOME, CHARACTER_LIBRARY_DIR and LORA_CATALOG_DIR under tmp_path, the daemon
URL at a closed port. LoRA files are a few bytes; nothing renders.
"""

import ast
import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

LORA_CATALOG_CLI = os.path.join(WS, "bin", "lora-catalog")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _top_level_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


# --- LCT1-LCT6, LCT26: lora_catalog.py (LC1-LC6, LC18) ------------------------------------

def test_lct1_import_set_and_stills_base_model():
    assert _top_level_imports(os.path.join(WS, "lora_catalog.py")) == {
        "datetime", "fcntl", "hashlib", "importlib.machinery", "json", "os", "re", "struct",
        "uuid"}
    with open(os.path.join(WS, "z_image_skill.py"), encoding="utf-8") as f:
        literal = re.search(r'^BASE_MODEL_ID = "([^"]+)"', f.read(), re.MULTILINE).group(1)
    assert lora_catalog.STILLS_BASE_MODEL == literal == "Tongyi-MAI/Z-Image-Turbo"
    assert lora_catalog.KINDS == ("style", "motion", "physics")
    assert lora_catalog.TARGETS == ("video", "stills")
    assert lora_catalog.MAX_TRIGGERS == 4 and lora_catalog.TEXT_MAX == 300
    assert len(lora_catalog.ENTRY_KEYS) == 16
    assert lora_catalog.CATALOG_ENV == "LORA_CATALOG_DIR" and lora_catalog.SCHEMA_VERSION == 1


def test_lct2_catalog_path(monkeypatch, tmp_path, story_env):
    assert lora_catalog.catalog_path("/ws") == os.path.join(story_env["catalog"], "catalog.json")
    monkeypatch.delenv("LORA_CATALOG_DIR")
    assert lora_catalog.catalog_path("/ws") == "/ws/generated/loras/catalog.json"
    assert lora_catalog.catalog_dir("/ws") == "/ws/generated/loras"
    absent = str(tmp_path / "nowhere" / "catalog.json")
    assert lora_catalog.load_catalog(absent) == {"schema_version": 1, "entries": []}


def _valid_entry(tmp_path):
    path = seu.lora_file(str(tmp_path / "files"), "m", rank=16)
    return seu.catalog_entry(path, "fast-motion", triggers=["fastmo"])


def test_lct3_entry_validation(tmp_path):
    base = _valid_entry(tmp_path)
    lora_catalog.validate_entry(base)
    cases = [
        (lambda e: e.pop("use_when"), "missing keys use_when"),
        (lambda e: e.update(extra=1), "unexpected keys extra"),
        (lambda e: e.update(id="Bad_id"), "id must match"),
        (lambda e: e.update(id="char:kyra"), "id must match"),
        (lambda e: e.update(kind="character"), "kind must be one of"),
        (lambda e: e.update(target="audio"), "target must be one of"),
        (lambda e: e.update(path="relative/x.safetensors"), "path must be an absolute path"),
        (lambda e: e.update(sha256="ABC"), "sha256 must be 64 lowercase hex"),
        (lambda e: e.update(bytes=0), "bytes must be an int >= 1"),
        (lambda e: e.update(bytes=True), "bytes must be an int >= 1"),
        (lambda e: e.update(base_models=[]), "base_models must be a non-empty list"),
        (lambda e: e.update(base_models=[""]), "base_models must be a non-empty list"),
        (lambda e: e.update(triggers=["a", "b", "c", "d", "e"]), "triggers must be a list of at most 4"),
        (lambda e: e.update(triggers=["-bad"]), "triggers item must match"),
        (lambda e: e.update(triggers=["Same", "same"]), "triggers must not repeat"),
        (lambda e: e.update(rank=0), "rank must be an int >= 1"),
        (lambda e: e.update(alpha=8), "alpha must equal rank (16); ltx-2-mlx fuses B@A*strength "
                                     "with no alpha/rank scaling (fuse_loras.py), so this LoRA "
                                     "would render at the wrong strength"),
        (lambda e: e.update(default_strength=True), "default_strength must be a number"),
        (lambda e: e.update(strength_range=[0.5]), "strength_range must be a list of two numbers"),
        (lambda e: e.update(default_strength=1.2), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(strength_range=[0, 1.0]), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(strength_range=[0.5, 2.5]), "strength_range and default_strength must satisfy"),
        (lambda e: e.update(description=""), "description must be a string of 1 to 300"),
        (lambda e: e.update(use_when="x" * 301), "use_when must be a string of 1 to 300"),
        (lambda e: e.update(avoid_when=None), "avoid_when must be a string of 0 to 300"),
        (lambda e: e.update(added_at="2026-10-17 12:00:00"), "added_at must be a UTC timestamp"),
    ]
    for mutate, needle in cases:
        entry = json.loads(json.dumps(base))
        mutate(entry)
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(entry)
        assert needle in str(exc.value), (needle, str(exc.value))
    other = dict(base, id="other", path=base["path"], triggers=["FASTMO"])
    for data, needle in (({"schema_version": 1}, "top level"),
                         ({"schema_version": 2, "entries": []}, "schema_version: must be 1"),
                         ({"schema_version": 1, "entries": {}}, "entries: must be a list"),
                         ({"schema_version": 1, "entries": [base, dict(base)]},
                          "id fast-motion is listed more than once"),
                         ({"schema_version": 1, "entries": [base, other]},
                          "trigger FASTMO is used by both fast-motion and other")):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_catalog(data)
        assert needle in str(exc.value), (needle, str(exc.value))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.load_catalog(str(bad))
    assert str(exc.value).startswith(str(bad) + ": not valid JSON")


def test_lct3b_save_sorts_and_is_atomic(tmp_path):
    base = _valid_entry(tmp_path)
    path = str(tmp_path / "cat" / "catalog.json")
    os.makedirs(os.path.dirname(path))
    second = dict(base, id="alpha-grain", kind="style", triggers=[])
    lora_catalog.save_catalog(path, {"schema_version": 1, "entries": [base, second]})
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.endswith("}\n")
    assert [e["id"] for e in json.loads(text)["entries"]] == ["alpha-grain", "fast-motion"]
    assert os.listdir(os.path.dirname(path)) == ["catalog.json"]
    assert lora_catalog.load_catalog(path)["entries"][1] == base


def test_lct4_safetensors_header(tmp_path):
    path = seu.fake_safetensors(str(tmp_path / "a.safetensors"), 32, 32)
    header = lora_catalog.read_safetensors_header(path)
    assert lora_catalog.rank_alpha(header) == (32, 32)
    assert lora_catalog.has_lora_pairs(header) is True
    for key in ("lora_alpha", "alpha", "ss_network_alpha"):
        path = seu.fake_safetensors(str(tmp_path / ("%s.safetensors" % key)), 8, None,
                                    metadata={key: "8.0"})
        assert lora_catalog.rank_alpha(lora_catalog.read_safetensors_header(path)) == (8, 8)
    path = seu.fake_safetensors(str(tmp_path / "frac.safetensors"), 8, None,
                                metadata={"lora_alpha": "4.5"})
    assert lora_catalog.rank_alpha(lora_catalog.read_safetensors_header(path)) == (8, None)
    kohya = {"lora_unet_blocks_0.lora_down.weight": {"dtype": "F16", "shape": [4, 8],
                                                     "data_offsets": [0, 8]},
             "__metadata__": {"ss_network_dim": "4", "ss_network_alpha": "4"}}
    raw = json.dumps(kohya).encode("utf-8")
    path = str(tmp_path / "kohya.safetensors")
    with open(path, "wb") as f:
        f.write(len(raw).to_bytes(8, "little") + raw)
    header = lora_catalog.read_safetensors_header(path)
    assert lora_catalog.has_lora_pairs(header) is False
    assert lora_catalog.rank_alpha(header) == (4, 4)
    unpaired = lora_catalog.read_safetensors_header(
        seu.fake_safetensors(str(tmp_path / "u.safetensors"), 8, 8, pairs=False))
    assert lora_catalog.has_lora_pairs(unpaired) is False
    for name, content in (("short.safetensors", b"\x01\x02"),
                          ("zero.safetensors", (0).to_bytes(8, "little")),
                          ("huge.safetensors", (200 * 1024 * 1024).to_bytes(8, "little")),
                          ("trunc.safetensors", (50).to_bytes(8, "little") + b"{}"),
                          ("notjson.safetensors", (4).to_bytes(8, "little") + b"nope")):
        path = str(tmp_path / name)
        with open(path, "wb") as f:
            f.write(content)
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.read_safetensors_header(path)
        assert str(exc.value) == "%s: not a safetensors file" % path


def test_lct5_character_folding(story_env):
    lib = story_env["lib"]
    seu.kyra(lib, strength=0.6)
    seu.make_untrained(lib, "monk")
    before = sorted(os.listdir(story_env["catalog"]))
    folded = lora_catalog.fold_characters(WS)
    assert [e["id"] for e in folded] == ["char:kyra"]
    entry = folded[0]
    assert entry["kind"] == "character" and entry["target"] == "video"
    assert entry["triggers"] == ["kyrawmn"]
    assert entry["base_models"] == [seu.CHARACTER_BASE_MODEL]
    assert entry["default_strength"] == 0.6 and entry["strength_range"] is None
    assert entry["bytes"] is None and entry["rank"] == entry["alpha"] == 32
    assert entry["description"] == seu.DESC_K
    assert entry["use_when"] == "cast with bin/ltx-movie --character kyra"
    assert entry["path"] == os.path.join(lib, "kyra", "lora", "video.safetensors")
    assert lora_catalog.character_triggers(WS) == {"kyrawmn": "kyra", "monktrg": "monk"}
    assert sorted(os.listdir(story_env["catalog"])) == before


def test_lct6a_compatibility(tmp_path):
    entry = {"base_models": ["MLXBits/pack", str(tmp_path / "models" / "pack")]}
    assert lora_catalog.compatible(entry, "MLXBits/pack") is True
    assert lora_catalog.compatible(entry, "MLXBits/other") is False
    os.makedirs(str(tmp_path / "models" / "pack"))
    os.symlink(str(tmp_path / "models" / "pack"), str(tmp_path / "link"))
    assert lora_catalog.compatible(entry, str(tmp_path / "link")) is True
    assert lora_catalog.compatible({"base_models": [lora_catalog.STILLS_BASE_MODEL]},
                                   "Tongyi-MAI/Z-Image-Turbo") is True


def test_lct26_prefix_triggers():
    p = "The courier pedals hard."
    assert lora_catalog.prefix_triggers(p, []) == p
    assert lora_catalog.prefix_triggers(p, ["fastmo", "grainfilm"]) == "fastmo, grainfilm. " + p
    assert lora_catalog.prefix_triggers("FASTMO courier", ["fastmo"]) == "FASTMO courier"
    assert lora_catalog.prefix_triggers(p, ["fastmo", "FastMo", "x"]) == "fastmo, x. " + p
    assert lora_catalog.prefix_triggers("the fastmo-like blur", ["fastmo"]) == (
        "fastmo. the fastmo-like blur")
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
1 error
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
ERROR tests/test_lora_catalog.py
```

The error is the collection error `E   ModuleNotFoundError: No module named 'lora_catalog'`.

- [ ] **Step 3: Implement.**

**3.1.** Create `lora_catalog.py` with exactly this content:

```python
"""lora_catalog -- the versioned LoRA catalog (generated/loras/catalog.json).

Stdlib only. This module owns the catalog file: its schema_version 1 shape and validation,
atomic saves under an exclusive lock, the safetensors header reader (rank, alpha, lora_A /
lora_B pairs), the read-only folding of trained library characters, base-model compatibility
and the catalog trigger prefix rule. bin/lora-catalog imports it at top level; bin/ltx-movie,
story_engine.py, bin/ltx-story-manifest and bin/ltx-story-images load it by path, only inside
functions. It loads character_lib.py by path, only inside fold_characters and
character_triggers.

The catalog root is $LORA_CATALOG_DIR when set (test infrastructure only, like
CHARACTER_LIBRARY_DIR), else <workspace>/generated/loras.

See docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md, Section 4.
"""

import datetime
import fcntl
import hashlib
import importlib.machinery
import json
import os
import re
import struct
import uuid

SCHEMA_VERSION = 1
CATALOG_ENV = "LORA_CATALOG_DIR"
STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
KINDS = ("style", "motion", "physics")
TARGETS = ("video", "stills")
ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
TRIGGER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}")
MAX_TRIGGERS = 4
TEXT_MAX = 300
ENTRY_KEYS = ("id", "kind", "path", "sha256", "bytes", "base_models", "target", "triggers",
              "rank", "alpha", "default_strength", "strength_range", "description", "use_when",
              "avoid_when", "added_at")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HEADER_MAX_BYTES = 100 * 1024 * 1024
LORA_A_SUFFIX = ".lora_A.weight"
LORA_B_SUFFIX = ".lora_B.weight"
ALPHA_RANK_MESSAGE = ("alpha must equal rank (%d); ltx-2-mlx fuses B@A*strength with no "
                      "alpha/rank scaling (fuse_loras.py), so this LoRA would render at the "
                      "wrong strength")


class CatalogError(Exception):
    """A catalog problem: an invalid catalog file or entry, or an unreadable LoRA header. The
    message is printed after "Error: "."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog_dir(ws):
    return os.environ.get(CATALOG_ENV) or os.path.join(ws, "generated", "loras")


def catalog_path(ws):
    return os.path.join(catalog_dir(ws), "catalog.json")


def empty_catalog():
    return {"schema_version": SCHEMA_VERSION, "entries": []}


def validate_entry(entry):
    """LC3 entry rules. Raises CatalogError("entry <id>: <field> <reason>"). File existence is
    not checked here (verify_entry does that)."""
    if not isinstance(entry, dict):
        raise CatalogError("entry: must be an object, got %s" % type(entry).__name__)
    label = entry.get("id") if isinstance(entry.get("id"), str) else "?"

    def fail(field, reason):
        raise CatalogError("entry %s: %s %s" % (label, field, reason))

    missing = [key for key in ENTRY_KEYS if key not in entry]
    if missing:
        raise CatalogError("entry %s: missing keys %s" % (label, ", ".join(missing)))
    extra = sorted(set(entry) - set(ENTRY_KEYS))
    if extra:
        raise CatalogError("entry %s: unexpected keys %s" % (label, ", ".join(extra)))
    if not isinstance(entry["id"], str) or not ID_RE.fullmatch(entry["id"]):
        fail("id", "must match [a-z][a-z0-9-]{1,31}, got %r" % (entry["id"],))
    if entry["kind"] not in KINDS:
        fail("kind", "must be one of %s, got %r" % (", ".join(KINDS), entry["kind"]))
    if not isinstance(entry["path"], str) or not os.path.isabs(entry["path"]):
        fail("path", "must be an absolute path, got %r" % (entry["path"],))
    if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
        fail("sha256", "must be 64 lowercase hex characters, got %r" % (entry["sha256"],))
    if not _is_int(entry["bytes"]) or entry["bytes"] < 1:
        fail("bytes", "must be an int >= 1, got %r" % (entry["bytes"],))
    models = entry["base_models"]
    if (not isinstance(models, list) or not models
            or not all(isinstance(m, str) and m for m in models)):
        fail("base_models", "must be a non-empty list of non-empty strings, got %r" % (models,))
    if entry["target"] not in TARGETS:
        fail("target", "must be one of %s, got %r" % (", ".join(TARGETS), entry["target"]))
    triggers = entry["triggers"]
    if not isinstance(triggers, list) or len(triggers) > MAX_TRIGGERS:
        fail("triggers", "must be a list of at most %d strings, got %r" % (MAX_TRIGGERS, triggers))
    for trigger in triggers:
        if not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger):
            fail("triggers", "item must match [A-Za-z0-9][A-Za-z0-9 _'-]{0,39}, got %r"
                 % (trigger,))
    if len({t.lower() for t in triggers}) != len(triggers):
        fail("triggers", "must not repeat a trigger, got %r" % (triggers,))
    if not _is_int(entry["rank"]) or entry["rank"] < 1:
        fail("rank", "must be an int >= 1, got %r" % (entry["rank"],))
    if not _is_int(entry["alpha"]) or entry["alpha"] != entry["rank"]:
        raise CatalogError("entry %s: %s" % (label, ALPHA_RANK_MESSAGE % entry["rank"]))
    default = entry["default_strength"]
    span = entry["strength_range"]
    if not _is_number(default):
        fail("default_strength", "must be a number, got %r" % (default,))
    if (not isinstance(span, list) or len(span) != 2
            or not all(_is_number(v) for v in span)):
        fail("strength_range", "must be a list of two numbers, got %r" % (span,))
    if not 0 < span[0] <= default <= span[1] <= 2:
        fail("strength_range", "and default_strength must satisfy 0 < lo <= default <= hi <= 2, "
             "got range %r and default %r" % (span, default))
    for key, low in (("description", 1), ("use_when", 1), ("avoid_when", 0)):
        text = entry[key]
        if not isinstance(text, str) or not low <= len(text) <= TEXT_MAX:
            fail(key, "must be a string of %d to %d characters, got %r" % (low, TEXT_MAX, text))
    if not isinstance(entry["added_at"], str) or not UTC_RE.fullmatch(entry["added_at"]):
        fail("added_at", "must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got %r"
             % (entry["added_at"],))


def validate_catalog(data):
    """LC3 top-level rules plus every entry. Raises CatalogError."""
    if not isinstance(data, dict) or set(data) != {"schema_version", "entries"}:
        raise CatalogError("top level: must be an object with exactly the keys entries, "
                           "schema_version")
    if not _is_int(data["schema_version"]) or data["schema_version"] != SCHEMA_VERSION:
        raise CatalogError("schema_version: must be %d, got %r"
                           % (SCHEMA_VERSION, data["schema_version"]))
    if not isinstance(data["entries"], list):
        raise CatalogError("entries: must be a list")
    ids, triggers = set(), {}
    for entry in data["entries"]:
        validate_entry(entry)
        if entry["id"] in ids:
            raise CatalogError("entries: id %s is listed more than once" % entry["id"])
        ids.add(entry["id"])
        for trigger in entry["triggers"]:
            owner = triggers.get(trigger.lower())
            if owner is not None:
                raise CatalogError("entries: trigger %s is used by both %s and %s"
                                   % (trigger, owner, entry["id"]))
            triggers[trigger.lower()] = entry["id"]


def load_catalog(path):
    """The catalog at path, validated; the empty catalog when the file does not exist. Raises
    CatalogError("<path>: <reason>")."""
    if not os.path.exists(path):
        return empty_catalog()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise CatalogError("%s: cannot read: %s" % (path, e))
    except ValueError as e:
        raise CatalogError("%s: not valid JSON: %s" % (path, e))
    try:
        validate_catalog(data)
    except CatalogError as e:
        raise CatalogError("%s: %s" % (path, e))
    return data


def save_catalog(path, data):
    """Validate, sort the entries by id, and atomically replace path (written to
    <path>.<uuid4 hex>.tmp, then os.replace)."""
    validate_catalog(data)
    data = {"schema_version": SCHEMA_VERSION,
            "entries": sorted(data["entries"], key=lambda e: e["id"])}
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _CatalogLock(object):
    """fcntl.flock(LOCK_EX) on <catalog dir>/.lock (created mode 0600) for a with block."""

    def __init__(self, path):
        self.lock_path = os.path.join(os.path.dirname(path), ".lock")
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
        return False


def catalog_lock(path):
    return _CatalogLock(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_safetensors_header(path):
    """The parsed JSON header of a safetensors file (LC4). Raises CatalogError("<path>: not a
    safetensors file") on a short read, a length of 0 or above 100 MiB, or invalid JSON."""
    bad = CatalogError("%s: not a safetensors file" % path)
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) != 8:
                raise bad
            (length,) = struct.unpack("<Q", head)
            if length == 0 or length > HEADER_MAX_BYTES:
                raise bad
            raw = f.read(length)
        if len(raw) != length:
            raise bad
        header = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, struct.error):
        raise bad
    if not isinstance(header, dict):
        raise bad
    return header


def _whole_number(value):
    try:
        number = float(value)
        whole = int(number)
    except (TypeError, ValueError, OverflowError):
        return None
    return whole if number == whole else None


def rank_alpha(header):
    """(rank or None, alpha or None) from a safetensors header (LC4)."""
    meta = header.get("__metadata__")
    meta = meta if isinstance(meta, dict) else {}
    rank = None
    keys = sorted(k for k in header if k.endswith(LORA_A_SUFFIX))
    if keys:
        tensor = header[keys[0]]
        shape = tensor.get("shape") if isinstance(tensor, dict) else None
        if isinstance(shape, list) and shape and _is_int(shape[0]) and shape[0] >= 1:
            rank = shape[0]
    if rank is None and "ss_network_dim" in meta:
        rank = _whole_number(meta["ss_network_dim"])
    alpha = None
    for key in ("lora_alpha", "alpha", "ss_network_alpha"):
        if key in meta:
            alpha = _whole_number(meta[key])
            if alpha is not None:
                break
    return rank, alpha


def has_lora_pairs(header):
    """True when some key X.lora_A.weight has a matching X.lora_B.weight (LC4)."""
    return any(k.endswith(LORA_A_SUFFIX)
               and k[:-len(LORA_A_SUFFIX)] + LORA_B_SUFFIX in header for k in header)


def _character_lib(ws):
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(ws, "character_lib.py")).load_module()


def fold_characters(ws):
    """Read-only pseudo-entries for every library character with a video LoRA (LC5), sorted by
    id. Never written to catalog.json and never offered to the story planner."""
    lib = _character_lib(ws)
    folded = []
    for name in lib.list_names():
        try:
            data = lib.load_character(name)
        except lib.CharacterError:
            continue
        video = data["loras"]["video"]
        if not video:
            continue
        folded.append({
            "id": "char:%s" % name, "kind": "character", "path": video["path"],
            "sha256": video["sha256"], "bytes": None, "base_models": [video["base_model"]],
            "target": "video", "triggers": [data["trigger"]], "rank": video["rank"],
            "alpha": video["alpha"],
            "default_strength": data["strength"] if data["strength"] is not None else 0.8,
            "strength_range": None, "description": data["descriptor"],
            "use_when": "cast with bin/ltx-movie --character %s" % name, "avoid_when": ""})
    return sorted(folded, key=lambda e: e["id"])


def character_paths(ws):
    """{realpath: (name, "video" | "stills")} for every library character LoRA file."""
    lib = _character_lib(ws)
    paths = {}
    for name in lib.list_names():
        try:
            data = lib.load_character(name)
        except lib.CharacterError:
            continue
        for kind in ("video", "stills"):
            if data["loras"][kind]:
                paths[os.path.realpath(data["loras"][kind]["path"])] = (name, kind)
    return paths


def character_triggers(ws):
    """{trigger.lower(): name} from character_lib.registered_triggers()."""
    return {t.lower(): name for t, name in _character_lib(ws).registered_triggers().items()}


def compatible(entry, model):
    """True when model equals a base_models item exactly, or both are absolute paths with the
    same os.path.realpath (LC6)."""
    for base in entry["base_models"]:
        if base == model:
            return True
        if (os.path.isabs(base) and os.path.isabs(model)
                and os.path.realpath(base) == os.path.realpath(model)):
            return True
    return False


def prefix_triggers(prompt, triggers):
    """prompt with the missing triggers in front as "t1, t2. " (LC18): the triggers, in order,
    de-duplicated case-insensitively, that do not already occur as whole words."""
    missing, seen = [], set()
    for trigger in triggers:
        if trigger.lower() in seen:
            continue
        seen.add(trigger.lower())
        pattern = r"(?<![\w-])" + re.escape(trigger) + r"(?![\w-])"
        if not re.search(pattern, prompt, re.IGNORECASE):
            missing.append(trigger)
    if not missing:
        return prompt
    return ", ".join(missing) + ". " + prompt


def verify_entry(entry, all_entries, char_triggers):
    """Problem strings for one catalog entry (LC10), in order: the file, its size, its sha256
    (only when the size matched), its header, rank/alpha, lora pairs, shared triggers."""
    problems = []
    path = entry["path"]
    readable = os.path.isfile(path) and os.access(path, os.R_OK)
    header = None
    if not readable:
        problems.append("%s is missing or unreadable" % path)
    else:
        size = os.path.getsize(path)
        if size != entry["bytes"]:
            problems.append("size is %d bytes; the catalog records %d" % (size, entry["bytes"]))
        elif file_sha256(path) != entry["sha256"]:
            problems.append("sha256 differs from the catalog; the file changed since it was added")
        try:
            header = read_safetensors_header(path)
        except CatalogError:
            problems.append("not a safetensors file")
    if entry["alpha"] != entry["rank"]:
        problems.append("alpha %r does not equal rank %r" % (entry["alpha"], entry["rank"]))
    if header is not None:
        rank, alpha = rank_alpha(header)
        if rank is not None and rank != entry["rank"]:
            problems.append("the header's rank %d differs from the recorded rank %d"
                            % (rank, entry["rank"]))
        if alpha is not None and alpha != entry["alpha"]:
            problems.append("the header's alpha %d differs from the recorded alpha %d"
                            % (alpha, entry["alpha"]))
        if entry["target"] == "video" and not has_lora_pairs(header):
            problems.append("has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would "
                            "ignore it")
    for trigger in entry["triggers"]:
        for other in all_entries:
            if other["id"] != entry["id"] and trigger.lower() in [t.lower() for t in other["triggers"]]:
                problems.append("trigger %s is also catalog entry %s's trigger"
                                % (trigger, other["id"]))
        if trigger.lower() in char_triggers:
            problems.append("trigger %s is also character %s's trigger"
                            % (trigger, char_triggers[trigger.lower()]))
    return problems
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
8 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/story_engine_testutil.py tests/test_lora_catalog.py lora_catalog.py && echo py39-ok
python3 -m py_compile tests/story_engine_testutil.py tests/test_lora_catalog.py lora_catalog.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/story_engine_testutil.py tests/test_lora_catalog.py lora_catalog.py
git diff --cached --name-only
git commit -m "lora_catalog: catalog schema, safetensors header, folding, prefix rule (catalog LC1-LC6, LC18)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/lora_catalog.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_lora_catalog.py
```


---

### Task 3: bin/lora-catalog: add, list, remove, verify

Implements LC7-LC11 and the `bin/lora-catalog` half of LC20. Tests LCT7-LCT12 and LCT29.

**Files:**
- Create: `bin/lora-catalog`
- Modify: `tests/test_lora_catalog.py`

**Interfaces:**
- Consumes: Everything `lora_catalog` produces in Task 2; `seu.lora_file`, `seu.catalog_entry`, `seu.make_catalog`, `seu.kyra`, `seu.fake_safetensors`, `seu.sha256_file` (Task 2).
- Produces: The executable `bin/lora-catalog` (`build_parser()`, `cmd_add`, `cmd_list`, `cmd_remove`, `cmd_verify`, `main(argv=None) -> int`). In `tests/test_lora_catalog.py`: `_cli(*argv)`, `_add_argv(path, entry_id, *extra, **kw)`, `_catalog_bytes(story_env)`, `lora_catalog_row(*cells)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_lct7_add_happy_path`, `test_lct8_add_errors_leave_the_catalog_unchanged`, `test_lct9_list`, `test_lct10_remove`, `test_lct11_verify`, `test_lct12_concurrent_adds_both_land`, `test_lct29_lora_catalog_exit_codes`.

**1.1.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- LCT7-LCT12, LCT29: bin/lora-catalog (LC7-LC11, LC20) ---------------------------------

def _cli(*argv):
    return subprocess.run([sys.executable, LORA_CATALOG_CLI] + list(argv), cwd=WS,
                          capture_output=True, text=True)


def _add_argv(path, entry_id, *extra, **kw):
    argv = ["add", path, "--id", entry_id, "--kind", kw.get("kind", "motion"),
            "--target", kw.get("target", "video"), "--base-model", seu.VIDEO_MODEL,
            "--description", "fast motion blur", "--use-when", "a chase or a sprint"]
    return argv + list(extra)


def _catalog_bytes(story_env):
    path = os.path.join(story_env["catalog"], "catalog.json")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def test_lct7_add_happy_path(tmp_path, story_env):
    files = str(tmp_path / "files")
    zeta = seu.lora_file(files, "zeta", rank=16)
    alpha = seu.lora_file(files, "alpha", rank=8)
    result = _cli(*_add_argv(zeta, "zeta-motion", "--trigger", "zetamo",
                             "--default-strength", "0.7", "--strength-range", "0.4,0.9",
                             "--avoid-when", "a still scene"))
    assert result.returncode == 0, result.stderr
    path = os.path.join(story_env["catalog"], "catalog.json")
    sha = seu.sha256_file(zeta)
    assert result.stdout == "added zeta-motion (motion, video, rank 16, sha256 %s...) to %s\n" % (
        sha[:12], path)
    assert result.stderr == ""
    entry = lora_catalog.load_catalog(path)["entries"][0]
    assert entry == {
        "id": "zeta-motion", "kind": "motion", "path": os.path.abspath(zeta), "sha256": sha,
        "bytes": os.path.getsize(zeta), "base_models": [seu.VIDEO_MODEL], "target": "video",
        "triggers": ["zetamo"], "rank": 16, "alpha": 16, "default_strength": 0.7,
        "strength_range": [0.4, 0.9], "description": "fast motion blur",
        "use_when": "a chase or a sprint", "avoid_when": "a still scene",
        "added_at": entry["added_at"]}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["added_at"])
    result = _cli(*_add_argv(alpha, "alpha-grain", kind="style"))
    assert result.returncode == 0, result.stderr
    data = lora_catalog.load_catalog(path)
    assert [e["id"] for e in data["entries"]] == ["alpha-grain", "zeta-motion"]
    assert data["entries"][0]["default_strength"] == 1.0
    assert data["entries"][0]["strength_range"] == [0.5, 1.0]
    assert data["entries"][0]["avoid_when"] == ""
    assert sorted(os.listdir(story_env["catalog"])) == [".lock", "catalog.json"]
    assert oct(os.stat(os.path.join(story_env["catalog"], ".lock")).st_mode & 0o777) == "0o600"


def test_lct8_add_errors_leave_the_catalog_unchanged(tmp_path, story_env):
    files = str(tmp_path / "files")
    first = seu.lora_file(files, "first", rank=16)
    assert _cli(*_add_argv(first, "first-motion", "--trigger", "firstmo")).returncode == 0
    seu.kyra(story_env["lib"])
    kyra_video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    seu.fake_safetensors(kyra_video, 32, 32)
    cases = [
        (_add_argv(seu.lora_file(files, "a", rank=16), "first-motion"),
         "Error: catalog entry first-motion already exists\n"),
        (_add_argv(first, "second-motion"),
         "Error: %s is already cataloged as first-motion\n" % first),
        (_add_argv(kyra_video, "kyra-copy"),
         "Error: %s is character kyra's video LoRA; cast it with bin/ltx-movie --character\n"
         % kyra_video),
        (_add_argv(seu.lora_file(files, "b", rank=16), "b-motion", "--trigger", "FIRSTMO"),
         "Error: trigger FIRSTMO is already catalog entry first-motion's trigger\n"),
        (_add_argv(seu.lora_file(files, "c", rank=16), "c-motion", "--trigger", "kyrawmn"),
         "Error: trigger kyrawmn is character kyra's trigger\n"),
        (_add_argv(seu.lora_file(files, "d", rank=16, alpha=8), "d-motion"),
         "Error: entry d-motion: alpha must equal rank (16); ltx-2-mlx fuses B@A*strength with "
         "no alpha/rank scaling (fuse_loras.py), so this LoRA would render at the wrong "
         "strength\n"),
        (_add_argv(seu.lora_file(files, "e", rank=16, pairs=False), "e-motion"),
         "Error: %s has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would ignore it\n"
         % os.path.join(files, "e.safetensors")),
        (_add_argv(seu.fake_safetensors(os.path.join(files, "f.safetensors"), 16, None),
                   "f-motion"),
         "Error: cannot read the LoRA alpha from the safetensors header; pass --alpha\n"),
        (_add_argv(seu.lora_file(files, "g", rank=16), "g-motion", "--default-strength", "1.5"),
         "Error: entry g-motion: strength_range and default_strength must satisfy 0 < lo <= "
         "default <= hi <= 2, got range [0.5, 1.0] and default 1.5\n"),
        (_add_argv(os.path.join(files, "missing.safetensors"), "h-motion"),
         "Error: %s is not a readable file\n" % os.path.join(files, "missing.safetensors")),
        (_add_argv(seu.lora_file(files, "i", rank=16), "i-motion", "--strength-range", "0.5"),
         "Error: --strength-range must be LO,HI, got '0.5'\n"),
    ]
    before = _catalog_bytes(story_env)
    for argv, stderr in cases:
        result = _cli(*argv)
        assert (result.returncode, result.stdout, result.stderr) == (2, "", stderr), argv
        assert _catalog_bytes(story_env) == before
    ok = _cli(*_add_argv(seu.fake_safetensors(os.path.join(files, "j.safetensors"), 16, None),
                         "j-motion", "--alpha", "16"))
    assert ok.returncode == 0, ok.stderr


def test_lct9_list(tmp_path, story_env):
    path = os.path.join(story_env["catalog"], "catalog.json")
    empty = _cli("list")
    assert (empty.returncode, empty.stdout) == (0, "no LoRAs in %s\n" % path)
    seu.kyra(story_env["lib"])
    header = lora_catalog_row("ID", "KIND", "TARGET", "STRENGTH", "TRIGGERS", "BASE_MODELS")
    kyra_row = lora_catalog_row("char:kyra", "character", "video", "0.8", "kyrawmn",
                                seu.CHARACTER_BASE_MODEL)
    only_chars = _cli("list")
    assert only_chars.stdout == "no LoRAs in %s\n%s\n%s\n" % (path, header, kyra_row)
    files = str(tmp_path / "files")
    motion = seu.catalog_entry(seu.lora_file(files, "m"), "fast-motion", triggers=["fastmo"])
    stills = seu.catalog_entry(seu.lora_file(files, "s"), "ink-stills", kind="style",
                               target="stills", base_models=[seu.STILLS_MODEL],
                               default_strength=0.9, strength_range=[0.6, 1.2])
    seu.make_catalog(story_env["catalog"], [motion, stills])
    table = _cli("list")
    assert table.returncode == 0
    assert table.stdout.splitlines() == [
        header,
        lora_catalog_row("fast-motion", "motion", "video", "0.8 (0.5-1.0)", "fastmo",
                         seu.VIDEO_MODEL),
        lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                         seu.STILLS_MODEL),
        kyra_row]
    filtered = _cli("list", "--model", seu.STILLS_MODEL)
    assert filtered.stdout.splitlines() == [
        header, lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                                 seu.STILLS_MODEL)]
    as_json = json.loads(_cli("list", "--json").stdout)
    assert list(as_json) == ["catalog", "entries", "characters"]
    assert as_json["catalog"] == path
    assert [e["id"] for e in as_json["entries"]] == ["fast-motion", "ink-stills"]
    assert [c["id"] for c in as_json["characters"]] == ["char:kyra"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]")
    broken = _cli("list")
    assert broken.returncode == 2 and broken.stderr.startswith("Error: %s: top level" % path)


def lora_catalog_row(*cells):
    return "%-24s %-9s %-7s %-14s %-24s %s" % cells


def test_lct10_remove(tmp_path, story_env):
    files = str(tmp_path / "files")
    lora = seu.lora_file(files, "m")
    with open(lora, "rb") as f:
        lora_bytes = f.read()
    seu.make_catalog(story_env["catalog"], [seu.catalog_entry(lora, "fast-motion")])
    path = os.path.join(story_env["catalog"], "catalog.json")
    unknown = _cli("remove", "nope")
    assert (unknown.returncode, unknown.stderr) == (2, "Error: no catalog entry nope\n")
    char = _cli("remove", "char:kyra")
    assert (char.returncode, char.stderr) == (
        2, "Error: char:kyra is a library character; manage it with bin/character\n")
    ok = _cli("remove", "fast-motion")
    assert (ok.returncode, ok.stdout) == (0, "removed fast-motion from %s\n" % path)
    assert lora_catalog.load_catalog(path)["entries"] == []
    with open(lora, "rb") as f:
        assert f.read() == lora_bytes


def test_lct11_verify(tmp_path, story_env):
    files = str(tmp_path / "files")
    good = seu.catalog_entry(seu.lora_file(files, "good"), "good-motion", triggers=["goodmo"])
    seu.make_catalog(story_env["catalog"], [good])
    clean = _cli("verify")
    assert (clean.returncode, clean.stdout) == (0, "OK good-motion\nverified 1 entry: 0 problem(s)\n")
    grown = seu.catalog_entry(seu.lora_file(files, "grown"), "grown-motion")
    with open(grown["path"], "ab") as f:
        f.write(b"extra")
    same = seu.catalog_entry(seu.lora_file(files, "same"), "same-size")
    with open(same["path"], "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x01")
    gone = seu.catalog_entry(seu.lora_file(files, "gone"), "gone-motion")
    os.remove(gone["path"])
    ranked = seu.catalog_entry(seu.lora_file(files, "ranked", rank=16), "ranked-motion", rank=8)
    clash = seu.catalog_entry(seu.lora_file(files, "clash"), "clash-motion", triggers=["kyrawmn"])
    seu.kyra(story_env["lib"])
    seu.make_catalog(story_env["catalog"], [good, grown, same, gone, ranked, clash])
    result = _cli("verify")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL clash-motion: trigger kyrawmn is also character kyra's trigger",
        "FAIL gone-motion: %s is missing or unreadable" % gone["path"],
        "OK good-motion",
        "FAIL grown-motion: size is %d bytes; the catalog records %d"
        % (grown["bytes"] + 5, grown["bytes"]),
        "FAIL ranked-motion: the header's rank 16 differs from the recorded rank 8",
        "FAIL ranked-motion: the header's alpha 16 differs from the recorded alpha 8",
        "FAIL same-size: sha256 differs from the catalog; the file changed since it was added",
        "FAIL char:kyra: trigger kyrawmn is also catalog entry clash-motion's trigger",
        "verified 6 entries: 7 problem(s)"]
    one = _cli("verify", "good-motion")
    assert (one.returncode, one.stdout) == (0, "OK good-motion\nverified 1 entry: 0 problem(s)\n")
    missing = _cli("verify", "nope")
    assert (missing.returncode, missing.stderr) == (2, "Error: no catalog entry nope\n")


def test_lct12_concurrent_adds_both_land(tmp_path, story_env):
    files = str(tmp_path / "files")
    procs = [subprocess.Popen([sys.executable, LORA_CATALOG_CLI]
                              + _add_argv(seu.lora_file(files, name), name + "-motion"),
                              cwd=WS, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for name in ("one", "two")]
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
    path = os.path.join(story_env["catalog"], "catalog.json")
    assert [e["id"] for e in lora_catalog.load_catalog(path)["entries"]] == [
        "one-motion", "two-motion"]
    assert not [n for n in os.listdir(story_env["catalog"]) if n.endswith(".tmp")]


def test_lct29_lora_catalog_exit_codes(tmp_path, story_env):
    files = str(tmp_path / "files")
    lora = seu.lora_file(files, "m")
    table = [
        (["list"], 0),
        (_add_argv(lora, "fast-motion"), 0),
        (_add_argv(lora, "fast-motion"), 2),
        (["verify"], 0),
        (["verify", "nope"], 2),
        (["remove", "nope"], 2),
        (["remove", "fast-motion"], 0),
        (["bogus"], 2),
        (["add", lora], 2),
    ]
    for argv, rc in table:
        assert _cli(*argv).returncode == rc, argv
    assert _cli(*_add_argv(lora, "fast-motion")).returncode == 0
    os.remove(lora)
    assert _cli("verify").returncode == 1
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
7 failed, 8 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_lora_catalog.py::test_lct7_add_happy_path
FAILED tests/test_lora_catalog.py::test_lct8_add_errors_leave_the_catalog_unchanged
FAILED tests/test_lora_catalog.py::test_lct9_list
FAILED tests/test_lora_catalog.py::test_lct10_remove
FAILED tests/test_lora_catalog.py::test_lct11_verify
FAILED tests/test_lora_catalog.py::test_lct12_concurrent_adds_both_land
FAILED tests/test_lora_catalog.py::test_lct29_lora_catalog_exit_codes
```

- [ ] **Step 3: Implement.**

**3.1.** Create `bin/lora-catalog` with exactly this content:

```python
#!/usr/bin/env python3
"""lora-catalog -- manage the versioned LoRA catalog (generated/loras/catalog.json).

  bin/lora-catalog add PATH --id ID --kind {style,motion,physics} --target {video,stills}
                   --base-model M [--base-model M ...] [--trigger T ...]
                   --description TEXT --use-when TEXT [--avoid-when TEXT]
                   [--default-strength S] [--strength-range LO,HI] [--rank N] [--alpha N]
  bin/lora-catalog list [--model M] [--json]
  bin/lora-catalog remove ID
  bin/lora-catalog verify [ID ...]

bin/ltx-movie's story planner may pick catalog entries per panel (style LoRAs only for the
whole movie); trained library characters are listed and verified here but are cast only with
bin/ltx-movie --character. The catalog lives in $LORA_CATALOG_DIR when set (tests only), else
generated/loras/. add and remove hold the catalog lock for their whole read-modify-write.
Exit codes: 0 success, 1 verify found problems, 2 usage or validation error. See
docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md, Section 4.
"""

import argparse
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
import lora_catalog  # noqa: E402

ROW_FORMAT = "%-24s %-9s %-7s %-14s %-24s %s"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="lora-catalog",
        description="Manage the LoRA catalog that bin/ltx-movie's story planner picks from.")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="catalog a LoRA file")
    add.add_argument("path", metavar="PATH")
    add.add_argument("--id", dest="entry_id", required=True)
    add.add_argument("--kind", choices=lora_catalog.KINDS, required=True)
    add.add_argument("--target", choices=lora_catalog.TARGETS, required=True)
    add.add_argument("--base-model", dest="base_models", action="append", required=True,
                     metavar="M")
    add.add_argument("--trigger", dest="triggers", action="append", default=None, metavar="T")
    add.add_argument("--description", required=True)
    add.add_argument("--use-when", dest="use_when", required=True)
    add.add_argument("--avoid-when", dest="avoid_when", default="")
    add.add_argument("--default-strength", dest="default_strength", type=float, default=1.0)
    add.add_argument("--strength-range", dest="strength_range", default="0.5,1.0",
                     metavar="LO,HI")
    add.add_argument("--rank", type=int, default=None)
    add.add_argument("--alpha", type=int, default=None)
    lst = sub.add_parser("list", help="list catalog entries and library characters")
    lst.add_argument("--model", default=None, metavar="M")
    lst.add_argument("--json", dest="as_json", action="store_true", default=False)
    rm = sub.add_parser("remove", help="remove a catalog entry (the file is not touched)")
    rm.add_argument("entry_id", metavar="ID")
    ver = sub.add_parser("verify", help="check catalog entries against their files")
    ver.add_argument("entry_ids", metavar="ID", nargs="*")
    return parser


def _error(message):
    print("Error: %s" % message, file=sys.stderr)
    return 2


def _parse_range(text):
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError(text)
    return [float(parts[0]), float(parts[1])]


def cmd_add(args):
    path = lora_catalog.catalog_path(WS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        span = _parse_range(args.strength_range)
    except ValueError:
        return _error("--strength-range must be LO,HI, got %r" % args.strength_range)
    with lora_catalog.catalog_lock(path):
        if not os.path.isfile(args.path) or not os.access(args.path, os.R_OK):
            return _error("%s is not a readable file" % args.path)
        try:
            header = lora_catalog.read_safetensors_header(args.path)
        except lora_catalog.CatalogError as e:
            return _error(str(e))
        if args.target == "video" and not lora_catalog.has_lora_pairs(header):
            return _error("%s has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would "
                          "ignore it" % args.path)
        header_rank, header_alpha = lora_catalog.rank_alpha(header)
        rank = args.rank if args.rank is not None else header_rank
        alpha = args.alpha if args.alpha is not None else header_alpha
        for name, value in (("rank", rank), ("alpha", alpha)):
            if value is None:
                return _error("cannot read the LoRA %s from the safetensors header; pass --%s"
                              % (name, name))
        try:
            catalog = lora_catalog.load_catalog(path)
        except lora_catalog.CatalogError as e:
            return _error(str(e))
        entries = catalog["entries"]
        if any(e["id"] == args.entry_id for e in entries):
            return _error("catalog entry %s already exists" % args.entry_id)
        real = os.path.realpath(args.path)
        for e in entries:
            if os.path.realpath(e["path"]) == real:
                return _error("%s is already cataloged as %s" % (args.path, e["id"]))
        owner = lora_catalog.character_paths(WS).get(real)
        if owner is not None:
            return _error("%s is character %s's %s LoRA; cast it with bin/ltx-movie --character"
                          % (args.path, owner[0], owner[1]))
        char_triggers = lora_catalog.character_triggers(WS)
        for trigger in args.triggers or []:
            for e in entries:
                if trigger.lower() in [t.lower() for t in e["triggers"]]:
                    return _error("trigger %s is already catalog entry %s's trigger"
                                  % (trigger, e["id"]))
            if trigger.lower() in char_triggers:
                return _error("trigger %s is character %s's trigger"
                              % (trigger, char_triggers[trigger.lower()]))
        entry = {"id": args.entry_id, "kind": args.kind, "path": os.path.abspath(args.path),
                 "sha256": lora_catalog.file_sha256(args.path),
                 "bytes": os.path.getsize(args.path), "base_models": list(args.base_models),
                 "target": args.target, "triggers": list(args.triggers or []), "rank": rank,
                 "alpha": alpha, "default_strength": args.default_strength,
                 "strength_range": span, "description": args.description,
                 "use_when": args.use_when, "avoid_when": args.avoid_when,
                 "added_at": lora_catalog.utc_now()}
        try:
            lora_catalog.validate_entry(entry)
            lora_catalog.save_catalog(path, {"schema_version": lora_catalog.SCHEMA_VERSION,
                                             "entries": entries + [entry]})
        except lora_catalog.CatalogError as e:
            return _error(str(e))
    print("added %s (%s, %s, rank %d, sha256 %s...) to %s"
          % (entry["id"], entry["kind"], entry["target"], rank, entry["sha256"][:12], path))
    return 0


def _strength_text(entry):
    default = repr(float(entry["default_strength"]))
    if entry["strength_range"] is None:
        return default
    return "%s (%s-%s)" % (default, repr(float(entry["strength_range"][0])),
                           repr(float(entry["strength_range"][1])))


def _row(entry):
    return ROW_FORMAT % (entry["id"], entry["kind"], entry["target"], _strength_text(entry),
                         ",".join(entry["triggers"]), ",".join(entry["base_models"]))


def cmd_list(args):
    path = lora_catalog.catalog_path(WS)
    try:
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    characters = lora_catalog.fold_characters(WS)
    if args.model is not None:
        entries = [e for e in entries if lora_catalog.compatible(e, args.model)]
        characters = [c for c in characters if lora_catalog.compatible(c, args.model)]
    if args.as_json:
        print(json.dumps({"catalog": path, "entries": entries, "characters": characters},
                         indent=2, ensure_ascii=False))
        return 0
    header = ROW_FORMAT % ("ID", "KIND", "TARGET", "STRENGTH", "TRIGGERS", "BASE_MODELS")
    if not entries:
        print("no LoRAs in %s" % path)
        if characters:
            print(header)
    else:
        print(header)
        for entry in entries:
            print(_row(entry))
    for entry in characters:
        print(_row(entry))
    return 0


def cmd_remove(args):
    path = lora_catalog.catalog_path(WS)
    if args.entry_id.startswith("char:"):
        return _error("%s is a library character; manage it with bin/character" % args.entry_id)
    if not os.path.isdir(os.path.dirname(path)):
        return _error("no catalog entry %s" % args.entry_id)
    with lora_catalog.catalog_lock(path):
        try:
            catalog = lora_catalog.load_catalog(path)
        except lora_catalog.CatalogError as e:
            return _error(str(e))
        kept = [e for e in catalog["entries"] if e["id"] != args.entry_id]
        if len(kept) == len(catalog["entries"]):
            return _error("no catalog entry %s" % args.entry_id)
        try:
            lora_catalog.save_catalog(path, {"schema_version": lora_catalog.SCHEMA_VERSION,
                                             "entries": kept})
        except lora_catalog.CatalogError as e:
            return _error(str(e))
    print("removed %s from %s" % (args.entry_id, path))
    return 0


def cmd_verify(args):
    path = lora_catalog.catalog_path(WS)
    try:
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    by_id = {e["id"]: e for e in entries}
    for entry_id in args.entry_ids:
        if entry_id not in by_id:
            return _error("no catalog entry %s" % entry_id)
    selected = [by_id[i] for i in args.entry_ids] if args.entry_ids else entries
    char_triggers = lora_catalog.character_triggers(WS)
    problems = 0
    for entry in selected:
        found = lora_catalog.verify_entry(entry, entries, char_triggers)
        if not found:
            print("OK %s" % entry["id"])
        for problem in found:
            print("FAIL %s: %s" % (entry["id"], problem))
        problems += len(found)
    owners = {}
    for entry in selected:
        for trigger in entry["triggers"]:
            owners[trigger.lower()] = entry["id"]
    for character in lora_catalog.fold_characters(WS):
        for trigger in character["triggers"]:
            if trigger.lower() in owners:
                print("FAIL %s: trigger %s is also catalog entry %s's trigger"
                      % (character["id"], trigger, owners[trigger.lower()]))
                problems += 1
    print("verified %d entr%s: %d problem(s)"
          % (len(selected), "y" if len(selected) == 1 else "ies", problems))
    return 1 if problems else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {"add": cmd_add, "list": cmd_list, "remove": cmd_remove,
            "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
```

**3.2.** Make it executable:

```bash
chmod 755 bin/lora-catalog
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
15 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile bin/lora-catalog tests/test_lora_catalog.py && echo py39-ok
python3 -m py_compile bin/lora-catalog tests/test_lora_catalog.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add bin/lora-catalog tests/test_lora_catalog.py
git diff --cached --name-only
git commit -m "bin/lora-catalog: add, list, remove, verify under the catalog lock (catalog LC7-LC11, LC20)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/lora-catalog
qwen-agent-workspace/tests/test_lora_catalog.py
```


---

### Task 4: story_engine.py foundation: constants, StoryContext, loaders, the agent call, JSON extraction; the fake agent; the deploy list

Implements RS1, RS4 (constants and budget functions), RS5, RS6, the `parse_violation` rule of Section 2.5, the fake agent / fake judge / temp workspace of spec 5.2, and LC19 (`PIPELINE_FILES`, with the Section 5.5 `PIPELINE` edit of `tests/test_deploy_pkg.py`). Tests RST1, RST5, RST6, RST7, RST25, LCT27, `test_rs4_constants`, `test_parse_violation_shapes`.

**Files:**
- Create: `tests/test_story_engine.py`
- Create: `story_engine.py`
- Modify: `tests/story_engine_testutil.py`
- Modify: `tests/test_deploy_pkg.py`
- Modify: `tests/test_lora_catalog.py`
- Modify: `scripts/deploy/build_pkg.py`

**Interfaces:**
- Consumes: `fleet_lib.LOCAL`, `delegate_once`, `route_candidates`, `fetch_view`, `daemon_url_from_env` (read-only, by path); `fleet_testutil.free_port` (Task 2's `set_story_env`).
- Produces: In `story_engine` (loaded by path as `se`): `PLAN_SCHEMA`, `CHECKS_SCHEMA`, `RUN_SCHEMA`, `CATALOG_LORAS_SCHEMA`, `ONESHOT_SCHEMA`, `SHOT_TYPES`, `CAMERA_SENTENCES`, `CAMERA_KEYS`, `ARC_ROLES`, `WORD_RANGES`, `NARRATION_WORDS`, `MIN_WRITER_WORDS`, `MAX_CAST`, `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `CRITIC_MAX_ROUNDS`, `CRITIC_CALLS_PER_ROUND`, `MAX_PATCHES`, `MIN_OK_SCORE`, `JUDGE_MIN_SCORE`, `LORA_PANEL_LIMIT`, `PANEL_MAX_TOKENS`, `CRITIC_MAX_TOKENS`, `PANEL_TIMEOUT`, `CRITIC_TIMEOUT`, `JUDGE_TIMEOUT`, `REQUEST_TIMEOUT`, `MAX_LISTED`, `REPEAT_JACCARD`, `SCORE_KEYS`; `StoryContext` (19 fields, spec 2.1 order); seams `_now`, `_utc`; `_character_lib(ws)`, `_lora_catalog(ws)`, `_load_fleet(ws) -> module|None`, `_story_manifest(ws)`; `plan_max_tokens(n)`, `plan_timeout(n)`, `wall_clock_cap(n)`; `_collapse(text)`, `_sentence(text)`, `_words(text)`, `_write_text(path, text)`, `_write_json(path, obj)` (atomic); `agent_cmd(ctx, prompt, *, max_tokens, image=None, skill=None) -> [str]`; `run_agent(ctx, prompt, *, max_tokens, timeout, image=None, skill=None, preflight_done=False) -> (status, answer|None)`; `extract_json(text) -> dict|None`; `parse_violation(text) -> dict`. In `seu`: `LINKED_FILES`, `FAKE_AGENT_SOURCE`, `FAKE_JUDGE_SOURCE`, `make_ws(tmp_path, fake_agent=True, fake_judge=False) -> ws`, `script_agent(monkeypatch, tmp_path, plan=(), panel=None, critic=()) -> log path`, `agent_log(path) -> [dict]`, `answer(obj) -> dict`, `make_ctx(se, ws, **overrides) -> StoryContext`. In `tests/test_story_engine.py`: the module header, `story_env` and `ws` fixtures, `_top_level_imports(path)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst1_module_imports_and_no_top_level_loader`, `test_rs4_constants`, `test_rst5_agent_cmd`, `test_rst6_run_agent`, `test_rst7_extract_json`, `test_parse_violation_shapes`, `test_rst25_fleet_lib_contract`, `test_lct27_deploy_pipeline_files`.

**1.1.** Append to `tests/story_engine_testutil.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- the temp workspace and the fake bin/qwen-agent (spec 5.1, 5.2) ------------------------

LINKED_FILES = ("character_lib.py", "story_engine.py", "lora_catalog.py", "fleet_lib.py",
                "pipeline_log.py", "ltx_image_fit.py", "ltx2_mlx_video_skill.py")

FAKE_AGENT_SOURCE = r'''#!/usr/bin/env python3
"""Fake bin/qwen-agent for the story engine tests (spec 5.2). Pops the next scripted reply for
the stage named by the --user-prompt's first line, logs the call, prints one envelope."""
import json
import os
import re
import sys
import time

argv = sys.argv[1:]
prompt = argv[argv.index("--user-prompt") + 1] if "--user-prompt" in argv else ""
first = prompt.split("\n", 1)[0]
panel = None
if first.startswith("You are planning"):
    stage = "plan"
elif first.startswith("You are writing panel "):
    stage = "panel"
    panel = int(re.match(r"You are writing panel (\d+) of", first).group(1))
elif first.startswith("You are the critic"):
    stage = "critic"
else:
    stage = "unknown"
script_path = os.environ["FAKE_AGENT_SCRIPT"]
with open(script_path, encoding="utf-8") as f:
    script = json.load(f)
queue = None
if stage == "panel":
    panels = script.setdefault("panel", {})
    for key in (str(panel), "*"):
        if panels.get(key):
            queue = panels[key]
            break
elif script.get(stage):
    queue = script[stage]
with open(os.environ["FAKE_AGENT_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "stage": stage, "panel": panel,
                        "env_preflight": os.environ.get("QWEN_AGENT_PREFLIGHT_DONE")}) + "\n")
if not queue:
    sys.exit(9)
item = queue.pop(0)
with open(script_path, "w", encoding="utf-8") as f:
    json.dump(script, f)
if item.get("sleep"):
    time.sleep(item["sleep"])
if item.get("no_envelope"):
    print("garbage")
    sys.exit(1)
status = item.get("status", "ok")
answer = item.get("answer")
print("some log line")
print(json.dumps({"schema": "qwen-agent.oneshot.v1", "status": status, "answer": answer,
                  "error": None, "rounds": 1, "tool_calls": 0}))
sys.exit(0 if status == "ok" else 3)
'''


def make_ws(tmp_path, fake_agent=True, fake_judge=False):
    """<tmp>/ws: symlinks to the real LINKED_FILES, a real bin/ holding symlinks to every real
    bin/* file except qwen-agent (the fake agent when fake_agent) and judge-story (the fake
    judge when fake_judge), and generated/stories/. Returns the ws path (str)."""
    ws = os.path.join(str(tmp_path), "ws")
    os.makedirs(os.path.join(ws, "bin"))
    os.makedirs(os.path.join(ws, "generated", "stories"))
    for name in LINKED_FILES:
        os.symlink(os.path.join(WS, name), os.path.join(ws, name))
    for name in sorted(os.listdir(os.path.join(WS, "bin"))):
        if (name == "qwen-agent" and fake_agent) or (name == "judge-story" and fake_judge):
            continue
        os.symlink(os.path.join(WS, "bin", name), os.path.join(ws, "bin", name))
    if fake_agent:
        _write_executable(os.path.join(ws, "bin", "qwen-agent"), FAKE_AGENT_SOURCE)
    if fake_judge:
        _write_executable(os.path.join(ws, "bin", "judge-story"), FAKE_JUDGE_SOURCE)
    return ws


def _write_executable(path, source):
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    os.chmod(path, 0o755)


def script_agent(monkeypatch, tmp_path, plan=(), panel=None, critic=()):
    """Write the fake agent's script ({"plan": [...], "panel": {"<k>"|"*": [...]}, "critic":
    [...]}) and point FAKE_AGENT_SCRIPT / FAKE_AGENT_LOG at it. Returns the log path."""
    script = os.path.join(str(tmp_path), "agent_script.json")
    log = os.path.join(str(tmp_path), "agent_log.jsonl")
    with open(script, "w", encoding="utf-8") as f:
        json.dump({"plan": list(plan), "panel": dict(panel or {}), "critic": list(critic)}, f)
    if os.path.exists(log):
        os.remove(log)
    monkeypatch.setenv("FAKE_AGENT_SCRIPT", script)
    monkeypatch.setenv("FAKE_AGENT_LOG", log)
    return log


def agent_log(path):
    """The fake agent's call records, in call order ([] when it was never called)."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def answer(obj):
    """A fake-agent reply item whose answer is obj (a dict is JSON-encoded)."""
    return {"answer": obj if isinstance(obj, str) else json.dumps(obj)}


def make_ctx(se, ws, **overrides):
    """A story_engine.StoryContext for ws with test defaults (chained, 3 panels, uncast, empty
    catalog, auto LoRA on); keyword arguments replace fields."""
    story_id = overrides.pop("story_id", "s1")
    fields = dict(ws=ws, story_id=story_id,
                  story_dir=os.path.join(ws, "generated", "stories", story_id), mode="chained",
                  panels=3, seconds="6",
                  narrative="A courier carries a sealed letter across a rainy harbour town.",
                  goal=None, members=[], seed_image=None, seed_agent_image=None,
                  story_model=None, context_window=None, video_model=VIDEO_MODEL,
                  auto_lora=True, catalog={"schema_version": 1, "entries": []}, pinned=[],
                  stills_pinned=[], judge=False)
    fields.update(overrides)
    os.makedirs(fields["story_dir"], exist_ok=True)
    return se.StoryContext(**fields)
```

**1.2.** Append to `tests/story_engine_testutil.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
FAKE_JUDGE_SOURCE = r'''#!/usr/bin/env python3
"""Fake bin/judge-story --patches for the story engine tests (spec 5.2)."""
import json
import os
import sys

argv = sys.argv[1:]
with open(os.environ["FAKE_JUDGE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv}) + "\n")
reply = json.loads(os.environ["FAKE_JUDGE_REPLY"])
if "exit" in reply:
    print("judge-story failed")
    sys.exit(reply["exit"])
story_md = argv[argv.index("--story-md") + 1]
with open(os.path.join(os.path.dirname(story_md), "judgment.patches.json"), "w",
          encoding="utf-8") as f:
    json.dump({"scores": reply["scores"], "verdict": reply["verdict"],
               "patches": reply["patches"]}, f)
print("Scores: ...")
sys.exit(0)
'''
```

**1.3.** Create `tests/test_story_engine.py` with exactly this content:

````python
"""Tests for the robust story engine (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-
design.md Section 5.3, RST1-RST54 and RST60-RST63): story_engine.py and its integration into
bin/ltx-movie, bin/judge-story and bin/iterate-story.

Run from the workspace root: python3 -m pytest tests/test_story_engine.py
Plain pytest asserts only. Every model call goes to the fake bin/qwen-agent of a temp
workspace (story_engine_testutil.make_ws) or to a monkeypatched seam; no test reaches a model
server, a daemon or the Anthropic API, and every test runs under Section 5.1's environment
(the autouse story_env fixture).
"""

import ast
import contextlib
import importlib.machinery
import inspect
import io
import json
import os
import py_compile
import random
import re
import shlex
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

story_engine = importlib.machinery.SourceFileLoader(
    "story_engine", os.path.join(WS, "story_engine.py")).load_module()
se = story_engine


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _top_level_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


# --- RST1, RST5-RST7, RST25: the module, the agent call, JSON extraction (RS1, RS4-RS6) -----

def test_rst1_module_imports_and_no_top_level_loader():
    path = os.path.join(WS, "story_engine.py")
    assert _top_level_imports(path) == {
        "collections", "copy", "datetime", "hashlib", "importlib.machinery", "json", "os", "re",
        "shlex", "subprocess", "sys", "time", "uuid"}
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            assert not (isinstance(sub, ast.Attribute) and sub.attr == "SourceFileLoader")
    py_compile.compile(path, doraise=True)
    assert "stdlib only; loaded by path by bin/ltx-movie and\nbin/judge-story" in se.__doc__
    assert se._now is se.time.monotonic
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", se._utc())


def test_rs4_constants():
    assert se.SHOT_TYPES == ("extreme wide shot", "wide shot", "medium shot", "medium close-up",
                             "close-up", "extreme close-up")
    assert [k for k, _ in se.CAMERA_SENTENCES] == [
        "static", "slow push-in", "slow pull-back", "slow pan left", "slow pan right",
        "slow tilt up", "slow tilt down", "tracking"]
    assert se.ARC_ROLES == ("introduction", "rising", "climax", "falling", "resolution")
    assert se.WORD_RANGES["chained"] == {"image1": (120, 170), "motion1": (25, 50),
                                         "motion": (15, 35)}
    assert se.MAX_CAST == {"chained": 4, "no_stills": 4, "shots": 2}
    assert (se.PLAN_MAX_CALLS, se.PANEL_MAX_CALLS, se.CRITIC_MAX_ROUNDS,
            se.CRITIC_CALLS_PER_ROUND, se.MAX_PATCHES) == (2, 2, 3, 2, 8)
    assert (se.PANEL_MAX_TOKENS, se.CRITIC_MAX_TOKENS, se.PANEL_TIMEOUT, se.CRITIC_TIMEOUT,
            se.JUDGE_TIMEOUT, se.REQUEST_TIMEOUT, se.MAX_LISTED) == (1536, 4096, 600, 900, 900,
                                                                      600, 40)
    assert (se.plan_max_tokens(14), se.plan_max_tokens(30)) == (4096, 7500)
    assert (se.plan_timeout(6), se.plan_timeout(30)) == (600, 1200)
    assert (se.wall_clock_cap(6), se.wall_clock_cap(30)) == (2400, 5400)
    character_lib = se._character_lib(WS)
    for _key, sentence in se.CAMERA_SENTENCES:
        assert character_lib._is_camera_sentence(sentence), sentence


def test_rst5_agent_cmd(ws):
    ctx = seu.make_ctx(se, ws)
    head = [sys.executable, os.path.join(ws, "bin", "qwen-agent"), "--workspace", ws,
            "--max-tokens", "4096", "--max-rounds", "1", "--request-timeout", "600"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096) == head + ["--user-prompt", "P"]
    tuned = ctx._replace(story_model="andrevp/Qwen", context_window=262144)
    assert se.agent_cmd(tuned, "P", max_tokens=4096) == head + [
        "--model", "andrevp/Qwen", "--context-window", "262144", "--user-prompt", "P"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096, image="/s/seed.png") == head + [
        "--image", "/s/seed.png", "--user-prompt", "P"]
    assert se.agent_cmd(ctx, "P", max_tokens=4096, skill="analyst") == head + [
        "--skill=analyst", "--user-prompt", "P"]
    for cmd in (se.agent_cmd(tuned, "P", max_tokens=1, image="/i", skill="analyst"),):
        assert "--danger-auto-approve" not in cmd


def test_rst6_run_agent(ws, tmp_path, monkeypatch):
    ctx = seu.make_ctx(se, ws)
    log = seu.script_agent(monkeypatch, tmp_path, plan=[
        {"answer": "first"}, {"answer": "forced summary", "status": "max_rounds"},
        {"status": "http_error"}, {"no_envelope": True}, {"sleep": 5, "answer": "late"},
        {"answer": "   "}])
    seen = []
    real_popen = se.subprocess.Popen

    def recording_popen(cmd, **kwargs):
        seen.append(kwargs)
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(se.subprocess, "Popen", recording_popen)
    prompt = "You are planning a test"
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("ok", "first")
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30, preflight_done=True) == (
        "max_rounds", "forced summary")
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("http_error", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("no_envelope", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=1) == ("timeout", None)
    assert se.run_agent(ctx, prompt, max_tokens=10, timeout=30) == ("ok", None)
    assert all(kw["stdin"] is subprocess.DEVNULL and kw["cwd"] == ws for kw in seen)
    records = seu.agent_log(log)
    assert [r["env_preflight"] for r in records[:2]] == [None, "1"]
    assert records[0]["argv"][-2:] == ["--user-prompt", prompt]


def test_rst7_extract_json():
    assert se.extract_json('{"a": 1}') == {"a": 1}
    assert se.extract_json('Here:\n```json\n{"a": {"b": 2}}\n```\nthanks') == {"a": {"b": 2}}
    assert se.extract_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    assert se.extract_json("```{\"a\": 3}```") == {"a": 3}
    assert se.extract_json("[1, 2]") is None
    assert se.extract_json("{not json}") is None
    assert se.extract_json(None) is None
    assert se.extract_json("no braces at all") is None


def test_parse_violation_shapes():
    assert se.parse_violation("panel 3: N1 word count: Motion: is 41 words; it must be 15-35") == {
        "id": "N1", "name": "word count", "scope": "panel", "index": 3,
        "message": "panel 3: N1 word count: Motion: is 41 words; it must be 15-35"}
    assert se.parse_violation("plan: P5 arc: no beat has arc 'climax'")["scope"] == "plan"
    assert se.parse_violation("story: S1 panel count: expected exactly 4 panels, found 3")[
        "index"] is None
    assert se.parse_violation("panel 2: missing/empty Motion: field") == {
        "id": "V0", "name": "structure", "scope": "story", "index": None,
        "message": "panel 2: missing/empty Motion: field"}


def test_rst25_fleet_lib_contract():
    fleet = se._load_fleet(WS)
    params = list(inspect.signature(fleet.delegate_once).parameters)
    assert params[:4] == ["daemon_url", "skill", "task", "host_id"]
    assert fleet.LOCAL == "@local"
    for name in ("route_candidates", "fetch_view", "daemon_url_from_env"):
        assert callable(getattr(fleet, name))
    assert se._load_fleet(str(os.path.join(WS, "no-such-dir"))) is None
````

**1.4.** Edit `tests/test_deploy_pkg.py`: replace this text, which occurs exactly once:

```python
            "character_lib.py", "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
```

with:

```python
            "character_lib.py", "story_engine.py", "lora_catalog.py", "bin/ltx-movie", "bin/ltx-story-images",
            "bin/ltx-story-manifest", "bin/ltx-mlx-render",
```

**1.5.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
def test_lct27_deploy_pipeline_files():
    build_pkg = importlib.machinery.SourceFileLoader(
        "build_pkg_for_lct27", os.path.join(WS, "scripts", "deploy", "build_pkg.py")).load_module()
    files = list(build_pkg.PIPELINE_FILES)
    at = files.index("character_lib.py")
    assert files[at + 1:at + 3] == ["story_engine.py", "lora_catalog.py"]
    assert "bin/lora-catalog" not in files and "fleet_lib.py" not in files
```

**1.6.** Edit `tests/test_deploy_pkg.py`: replace this text, which occurs exactly once:

```python
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (19, 3))
```

with:

```python
        self.assertEqual((ctx.comp_stats["A1"]["files"], ctx.comp_stats["A1"]["dirs"]), (21, 3))
```

**1.7.** Edit `tests/test_deploy_pkg.py`: replace this text, which occurs exactly once:

```python
        self.assertTrue(re.match(r"^A1 workspace-code files=19 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
```

with:

```python
        self.assertTrue(re.match(r"^A1 workspace-code files=21 symlinks=0 dirs=3 bytes=\d+ \(\d+\.\d\d GiB\)$", comp[0]), comp[0])
```

**1.8.** Edit `tests/test_deploy_pkg.py`: replace this text, which occurs exactly once:

```python
            fh.write(b"L")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 27 of ", out)
```

with:

```python
            fh.write(b"L")
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 29 of ", out)
```

**1.9.** Edit `tests/test_deploy_pkg.py`: replace this text, which occurs exactly once:

```python
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 27 of ", out)
```

with:

```python
        bp.HOOKS["after_chunk"] = lambda src, nbytes: None
        rc, out, err = build_apply(self.fx, "--resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PASS B07 resume prefix: 29 of ", out)
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_deploy_pkg.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
1 error
1 failed, 15 passed
8 failed, 157 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
ERROR tests/test_story_engine.py
FAILED tests/test_lora_catalog.py::test_lct27_deploy_pipeline_files
FAILED tests/test_deploy_pkg.py::TestComponentCollection::test_T01_golden_entry_list
FAILED tests/test_deploy_pkg.py::TestComponentCollection::test_T02_exclusions
FAILED tests/test_deploy_pkg.py::TestComponentCollection::test_T02b_constants_verbatim
FAILED tests/test_deploy_pkg.py::TestComponentCollection::test_stats
FAILED tests/test_deploy_pkg.py::TestBuildChecks::test_clean_fixture_passes_every_check_in_table_order
FAILED tests/test_deploy_pkg.py::TestBuildCli::test_dry_run_report_format_and_writes_nothing
FAILED tests/test_deploy_pkg.py::TestResume::test_RF2_resume_after_mid_copy_abort_completes_and_verifies
FAILED tests/test_deploy_pkg.py::TestResume::test_T43_corrupted_listed_payload_is_recopied
```

The `tests/test_story_engine.py` error is the collection error `E   FileNotFoundError: [Errno 2] No such file or directory: '.../qwen-agent-workspace/story_engine.py'`; the deploy failures come from Step 1's `PIPELINE` and count edits, which expect the two new files in `PIPELINE_FILES`.

- [ ] **Step 3: Implement.**

**3.1.** Create `story_engine.py` with exactly this content:

````python
"""story_engine -- bin/ltx-movie's robust Phase 1 (docs/superpowers/specs/2026-10-17-robust-story-
lora-catalog-design.md): the model writes small scoped pieces (a JSON story bible, then one panel
at a time) through bin/qwen-agent one-shot subprocesses, code assembles story.md and pastes every
fixed sentence verbatim, deterministic checks run on every round, and a local critic (the fleet
analyst skill) proposes per-panel patches that code applies to named fields only; bin/judge-story
--patches is an optional final gate. stdlib only; loaded by path by bin/ltx-movie and
bin/judge-story; loads character_lib.py, lora_catalog.py and fleet_lib.py by path, only inside
functions.
"""

import collections
import copy
import datetime
import hashlib
import importlib.machinery
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

PLAN_SCHEMA = "ltx-movie.plan.v1"
CHECKS_SCHEMA = "ltx-movie.story-checks.v1"
RUN_SCHEMA = "ltx-movie.story-run.v1"
CATALOG_LORAS_SCHEMA = "ltx-movie.catalog-loras.v1"
ONESHOT_SCHEMA = "qwen-agent.oneshot.v1"
SHOT_TYPES = ("extreme wide shot", "wide shot", "medium shot", "medium close-up", "close-up",
              "extreme close-up")
CAMERA_SENTENCES = (
    ("static", "The camera stays static."),
    ("slow push-in", "The camera slowly pushes in."),
    ("slow pull-back", "The camera slowly pulls back."),
    ("slow pan left", "The camera slowly pans left."),
    ("slow pan right", "The camera slowly pans right."),
    ("slow tilt up", "The camera slowly tilts up."),
    ("slow tilt down", "The camera slowly tilts down."),
    ("tracking", "The camera tracks alongside the movement."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
ARC_ROLES = ("introduction", "rising", "climax", "falling", "resolution")
WORD_RANGES = {"chained": {"image1": (120, 170), "motion1": (25, 50), "motion": (15, 35)},
               "no_stills": {"prompt": (150, 220)},
               "shots": {"image": (80, 170), "motion": (10, 25)}}
NARRATION_WORDS = (3, 30)
MIN_WRITER_WORDS = {"image": 20, "prompt": 20, "motion": 5}
MAX_CAST = {"chained": 4, "no_stills": 4, "shots": 2}
PLAN_MAX_CALLS = 2
PANEL_MAX_CALLS = 2
CRITIC_MAX_ROUNDS = 3
CRITIC_CALLS_PER_ROUND = 2
MAX_PATCHES = 8
MIN_OK_SCORE = 7
JUDGE_MIN_SCORE = 7
LORA_PANEL_LIMIT = 4
PANEL_MAX_TOKENS = 1536
CRITIC_MAX_TOKENS = 4096
PANEL_TIMEOUT = 600
CRITIC_TIMEOUT = 900
JUDGE_TIMEOUT = 900
REQUEST_TIMEOUT = 600
MAX_LISTED = 40
REPEAT_JACCARD = 0.6
SCORE_KEYS = ("continuity", "story", "renderability")

StoryContext = collections.namedtuple("StoryContext", [
    "ws", "story_id", "story_dir", "mode", "panels", "seconds", "narrative", "goal", "members",
    "seed_image", "seed_agent_image", "story_model", "context_window", "video_model",
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge"])

# Injectable seams (tests replace them with monkeypatch.setattr).
_now = time.monotonic
_utc = lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

_VIOLATION_RE = re.compile(r"^(?:(story|plan)|(beat|panel) (\d+)): ([A-Z]+\d+) ([^:]+): (.*)$",
                           re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _character_lib(ws):
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(ws, "character_lib.py")).load_module()


def _lora_catalog(ws):
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(ws, "lora_catalog.py")).load_module()


def _load_fleet(ws):
    try:
        return importlib.machinery.SourceFileLoader(
            "fleet_lib_for_story", os.path.join(ws, "fleet_lib.py")).load_module()
    except Exception:
        return None


def _story_manifest(ws):
    return importlib.machinery.SourceFileLoader(
        "ltx_story_manifest_for_movie", os.path.join(ws, "bin", "ltx-story-manifest")).load_module()


def plan_max_tokens(n):
    return max(4096, n * 250)


def plan_timeout(n):
    return max(600, n * 40)


def wall_clock_cap(n):
    return max(2400, n * 180)


def _collapse(text):
    return _WS_RE.sub(" ", text).strip()


def _sentence(text):
    """text stripped, whitespace collapsed, with "." appended unless it ends in . ! or ?"""
    text = _collapse(text)
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text


def _words(text):
    return len(text.split())


def _write_text(path, text):
    """Atomic write: <path>.<uuid4 hex>.tmp, then os.replace."""
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path, obj):
    _write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def agent_cmd(ctx, prompt, *, max_tokens, image=None, skill=None):
    """The bin/qwen-agent one-shot argv of every robust-engine model call (RS5)."""
    cmd = [sys.executable, os.path.join(ctx.ws, "bin", "qwen-agent"),
           "--workspace", ctx.ws,
           "--max-tokens", str(max_tokens), "--max-rounds", "1",
           "--request-timeout", str(REQUEST_TIMEOUT)]
    if ctx.story_model:
        cmd += ["--model", ctx.story_model]
    if ctx.context_window:
        cmd += ["--context-window", str(ctx.context_window)]
    if image:
        cmd += ["--image", image]
    if skill == "analyst":
        cmd += ["--skill=analyst"]
    return cmd + ["--user-prompt", prompt]


def run_agent(ctx, prompt, *, max_tokens, timeout, image=None, skill=None, preflight_done=False):
    """(status, answer) of one bin/qwen-agent one-shot call (RS5). status is the envelope's
    status, "timeout" or "no_envelope"; answer is the envelope's non-empty answer or None."""
    cmd = agent_cmd(ctx, prompt, max_tokens=max_tokens, image=image, skill=skill)
    env = dict(os.environ)
    if preflight_done:
        env["QWEN_AGENT_PREFLIGHT_DONE"] = "1"
    proc = subprocess.Popen(cmd, cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors="replace", env=env)
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return "timeout", None
    lines = [line for line in (out or "").splitlines() if line.strip()]
    try:
        envelope = json.loads(lines[-1])
    except (IndexError, ValueError):
        return "no_envelope", None
    if not isinstance(envelope, dict) or envelope.get("schema") != ONESHOT_SCHEMA:
        return "no_envelope", None
    answer = envelope.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = None
    return str(envelope.get("status")), answer


def extract_json(text):
    """The JSON object in a model reply, or None (RS6): the body of the first ``` fence when
    there is one, then the span from the first { to the last }."""
    if text is None:
        return None
    try:
        if "```" in text:
            start = text.index("```") + 3
            newline = text.find("\n", start)
            if newline == -1:
                body = text[start:]
                if body.startswith("json"):
                    body = body[4:]
            else:
                body = text[newline + 1:]
            end = body.find("```")
            text = body if end == -1 else body[:end]
        first, last = text.find("{"), text.rfind("}")
        if first == -1 or last < first:
            return None
        value = json.loads(text[first:last + 1])
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def parse_violation(text):
    """A violation string as the story_checks.json object of Section 2.5."""
    match = _VIOLATION_RE.match(text)
    if match is None:
        return {"id": "V0", "name": "structure", "scope": "story", "index": None, "message": text}
    return {"id": match.group(4), "name": match.group(5),
            "scope": match.group(1) or match.group(2),
            "index": int(match.group(3)) if match.group(3) else None, "message": text}
````

**3.2.** Edit `scripts/deploy/build_pkg.py`: replace this text, which occurs exactly once:

```python
                  "character_lib.py", "bin/ltx-movie", "bin/ltx-story-images", "bin/ltx-story-manifest", "bin/ltx-mlx-render",
```

with:

```python
                  "character_lib.py", "story_engine.py", "lora_catalog.py", "bin/ltx-movie", "bin/ltx-story-images",
                  "bin/ltx-story-manifest", "bin/ltx-mlx-render",
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_deploy_pkg.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
7 passed
16 passed
165 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py story_engine.py tests/story_engine_testutil.py tests/test_deploy_pkg.py tests/test_lora_catalog.py scripts/deploy/build_pkg.py && echo py39-ok
python3 -m py_compile tests/test_story_engine.py story_engine.py tests/story_engine_testutil.py tests/test_deploy_pkg.py tests/test_lora_catalog.py scripts/deploy/build_pkg.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py story_engine.py tests/story_engine_testutil.py tests/test_deploy_pkg.py tests/test_lora_catalog.py scripts/deploy/build_pkg.py
git diff --cached --name-only
git commit -m "story_engine: module, constants, agent call, JSON extraction; deploy ships it (story RS1, RS4-RS6; catalog LC19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/scripts/deploy/build_pkg.py
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_deploy_pkg.py
qwen-agent-workspace/tests/test_lora_catalog.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 5: The plan: prompt, compatible catalog set, normalization, plan checks, LoRA checks, undeclared characters (P13)

Implements RS7, RS9, RS10 (P1-P12), RS11 (L1-L7), LC6's compatible set and warnings, and the plan half of RS37 (`library_identities`, the reserved sentence in `@@CAST_FIXED@@`, P13). Tests RST8, RST9, RST13, RST14, RST15, RST55 (the checks; the forced plan call 2 is RST55b in Task 9), RST57 (the plan prompt and `library_identities`), LCT6b.

**Files:**
- Modify: `tests/story_engine_testutil.py`
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Task 4's constants, `_character_lib`, `_lora_catalog`, `_collapse`, `_sentence`, `_words`; `character_lib.normalize_phrase`, `validate_descriptor`, `_phrase_regex`, `CharacterError`; `lora_catalog.compatible`, `STILLS_BASE_MODEL`.
- Produces: In `se`: `NO_TOOL_SENTENCE`, `PLAN_PROMPT_TEMPLATE`, `MODE_PARAGRAPHS`, `SEED_PARAGRAPH`, `MODE_RULES`, `LORA_EMPTY_PARAGRAPH`, `LORA_PICK_PARAGRAPH`; `_fill(template, fragments, scalars, narrative)`; `_goal_paragraph(goal)`; `catalog_line(entry) -> str`; `_arc_rule(n)`; `library_identities(ws) -> [(name, trigger, phrase)]`; `undeclared_characters(ctx)`; `reserved_items(undeclared) -> str`; `undeclared_references(lib, text, undeclared, exact_phrase=False) -> [(name, kind, matched)]`; `undeclared_message(prefix, where, hit) -> str`; `build_plan_prompt(ctx, compatible, pins) -> str`; `compatible_entries(ctx) -> [entry]`; `catalog_warnings(ctx) -> [str]`; `normalize_plan(ctx, raw) -> (plan, shape)`; `_SENTENCE_SPLIT_RE`; `_q(text)`; `_setting_problems(setting) -> [str]`; `pasted_pieces(ctx, plan, k) -> {field: [str]}`; `identity(cast_entry)`; `shot_sentence(beat)`; `field_range(ctx, k, field) -> (kind, (lo, hi))|None`; `plan_checks(ctx, plan, shape=()) -> (hard, advisory)`; `lora_checks(ctx, plan, compatible_by_id, catalog_by_id) -> (hard, advisory)`. In `seu`: `COURIER`, `MONK`, `HARBOUR`, `TEMPLE`, `ACTIONS`, `arcs(n)`, `plan_json(mode, n, cast=None, **overrides)`. In the test module: `_cast_members(story_env, *names)`, `_three_entry_catalog(tmp_path)`, `_checks(ctx, raw)`, `_lora_ctx`, `_lora_violations`, `_pins`, `_p13`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst8_plan_prompt_matrix`, `test_rst9_narrative_is_inserted_verbatim`, `test_rst13_normalization`, `test_rst14_plan_checks`, `test_rst15_lora_checks`, `test_lct6b_compatible_set_and_warnings`, `test_rst55_p13_undeclared_character`, `test_rst57_reserved_sentence_in_the_plan_prompt`.

**1.1.** Append to `tests/story_engine_testutil.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- plan builders (spec 5.2) ---------------------------------------------------------------

COURIER = "a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers"
MONK = "an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals"
HARBOUR = ("The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, "
           "fishing boats behind, under grey afternoon light.")
TEMPLE = ("The setting is a hilltop temple gate in modern Japan, worn stone steps underfoot, "
          "pine trees behind, under warm sunset light.")
ACTIONS = (
    "pedals a bicycle along the wet harbour road past the moored fishing boats",
    "swerves around a stack of fishing crates on the slippery quay",
    "rides hard up the narrow lane between the shuttered shops",
    "brakes at the foot of the temple steps and climbs off the bicycle",
    "climbs the worn stone steps two at a time toward the gate",
    "holds out the sealed letter at the temple gate with both hands",
    "turns back toward the harbour as the rain finally stops",
    "leans the bicycle against a lamp post beside the gate",
)


def arcs(n):
    """A valid arc sequence for n beats (RS10 P5/P6)."""
    if n == 1:
        return ["climax"]
    if n == 2:
        return ["introduction", "resolution"]
    return ["introduction"] + ["rising"] * (n - 3) + ["climax", "resolution"]


def plan_json(mode, n, cast=None, **overrides):
    """A valid plan-writer reply (Section 2.2 keys) for n beats: cast c1 "the courier" (and c2
    "the old monk", never on screen), locations l1 (harbour) and l2 (temple), every beat at l1
    with cast ["c1"]. cast replaces the cast list (e.g. fixed library characters); every
    keyword replaces a top-level key."""
    phrase = (cast[0]["phrase"] if cast else "the courier")
    plan = {
        "title": "The Sealed Letter",
        "logline": "A courier carries a sealed letter through a rainy harbour town and "
                   "delivers it at the temple gate.",
        "cast": cast if cast is not None else [
            {"id": "c1", "phrase": "the courier", "descriptor": COURIER},
            {"id": "c2", "phrase": "the old monk", "descriptor": MONK}],
        "locations": [{"id": "l1", "setting": HARBOUR}, {"id": "l2", "setting": TEMPLE}],
        "props": [{"id": "p1", "name": "the sealed letter"}],
        "beats": [{"index": k, "arc": arc, "action": phrase + " " + ACTIONS[(k - 1) % len(ACTIONS)],
                   "shot": "medium shot" if k % 2 else "wide shot",
                   "camera": "static" if k % 2 else "tracking", "location": "l1", "cast": ["c1"]}
                  for k, arc in enumerate(arcs(n), start=1)],
        "loras": {"global": [], "per_beat": {}, "stills": []},
    }
    plan.update(overrides)
    return plan
```

**1.2.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST8, RST9, RST13-RST15, LCT6b: the plan (RS7, RS9-RS11, LC6) ------------------------

def _cast_members(story_env, *names):
    lib = story_env["lib"]
    if "kyra" in names:
        seu.kyra(lib)
    if "ronin" in names:
        seu.ronin(lib)
    return se._character_lib(WS).resolve_cast([(None, n) for n in names])


def _three_entry_catalog(tmp_path):
    files = str(tmp_path / "files")
    return {"schema_version": 1, "entries": [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                          triggers=["grainfilm"]),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", triggers=["fastmo"],
                          use_when="a chase", avoid_when="a still scene"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]}


def test_rst8_plan_prompt_matrix(ws, tmp_path, story_env):
    members = _cast_members(story_env, "kyra", "ronin")
    catalog = _three_entry_catalog(tmp_path)
    for mode in ("chained", "no_stills", "shots"):
        for cast in ([], members):
            for state in ("empty", "catalog", "off"):
                for seed in ((None, "/s/seed_downscaled.png") if mode == "chained" else (None,)):
                    ctx = seu.make_ctx(se, ws, mode=mode, members=cast, seed_agent_image=seed,
                                       catalog=catalog if state == "catalog" else
                                       {"schema_version": 1, "entries": []},
                                       auto_lora=state != "off")
                    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
                    where = (mode, len(cast), state, seed)
                    assert "{" not in prompt and "}" not in prompt, where
                    assert "@@" not in prompt, where
                    assert prompt.startswith(
                        'You are planning a short narrated movie (story-id "s1").\n'), where
                    assert prompt.endswith(se.NO_TOOL_SENTENCE), where
                    assert "do NOT run run_python or any other tool to check it" in prompt
                    assert ("This movie has no stills, so stills stays empty." in prompt) == (
                        mode == "no_stills" and state == "catalog"), where
                    assert ("An image is attached to this message." in prompt) == bool(seed)
                    assert ("LoRA catalog (pick only from these):" in prompt) == (state == "catalog")
                    if cast:
                        assert ('\n- id c1, phrase "the woman in grey", descriptor "%s"'
                                % seu.DESC_K) in prompt
                        assert '\n- id c2, phrase "the ronin", descriptor "%s"' % seu.DESC_R in prompt
                    else:
                        assert "already cast" not in prompt
                    if state == "catalog":
                        assert ("- ink-stills: style LoRA for stills" in prompt) == (
                            mode != "no_stills")
                        assert ("- fast-motion: motion LoRA for video, default strength 0.8, "
                                "range 0.5 to 1.0. a test LoRA. Use when: a chase. Avoid when: "
                                "a still scene.") in prompt
    ctx = seu.make_ctx(se, ws, mode="shots", panels=14, goal="the most realistic action")
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "\n\nThe target output goal is the most realistic action.\n\nHow this movie is made: it " \
           "is a sequence of separate shots joined by cuts, 6 seconds each." in prompt
    assert "beats: a list of EXACTLY 14 objects" in prompt and "at most 2.\n" in prompt
    assert "Rules for this movie: two people never touch on screen." in prompt
    assert "loras: " + se.LORA_EMPTY_PARAGRAPH + "\n" in prompt
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None},
            {"path": "/p/b.safetensors", "strength": 0.6, "catalog_id": "film-grain",
             "kind": "style"}]
    ctx = seu.make_ctx(se, ws, catalog=catalog, panels=2)
    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), pins)
    assert prompt.count("\n- ") >= 4
    assert ("\nAlready applied to every panel by the user, not to be picked again:\n- a LoRA "
            "outside the catalog at strength 1.0\n- film-grain (style) at strength 0.6\n\n") in prompt
    assert "the first beat is introduction and the last is resolution." in prompt
    assert "arc is one of introduction, rising, climax, falling, resolution, in story order; " \
           "use climax." in se.build_plan_prompt(seu.make_ctx(se, ws, panels=1), [], [])


def test_rst9_narrative_is_inserted_verbatim(ws):
    ctx = seu.make_ctx(se, ws, narrative="Count @@PANELS@@ and @@STORY_ID@@ {x}.")
    prompt = se.build_plan_prompt(ctx, [], [])
    assert "Narrative to adapt:\nCount @@PANELS@@ and @@STORY_ID@@ {x}.\n" in prompt
    assert "EXACTLY 3 objects" in prompt


def test_rst13_normalization(ws, story_env, tmp_path):
    members = _cast_members(story_env, "kyra", "ronin")
    catalog = _three_entry_catalog(tmp_path)
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None}]
    ctx = seu.make_ctx(se, ws, mode="shots", members=members, catalog=catalog, pinned=pins)
    raw = seu.plan_json("shots", 3, cast=[
        {"id": "c2", "phrase": "the swordsman", "descriptor": "a man"},
        {"id": "c3", "phrase": "  the   bandit ", "descriptor": seu.MONK + "."}],
        surprise="dropped", locations=[{"id": "l1", "setting": "The setting is a forest " * 3}])
    raw["loras"] = {"global": [{"id": "film-grain"}], "per_beat": {"2": [{"id": "fast-motion",
                                                                          "strength": 0.7}]}}
    plan, shape = se.normalize_plan(ctx, raw)
    assert shape == []
    assert [c["id"] for c in plan["cast"]] == ["c1", "c2", "c3"]
    assert plan["cast"][0] == {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K,
                               "cast_name": "kyra"}
    assert plan["cast"][1] == {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R,
                               "cast_name": "ronin"}
    assert plan["cast"][2] == {"id": "c3", "phrase": "the bandit", "descriptor": seu.MONK,
                               "cast_name": None}
    assert plan["locations"][0]["setting"] == ("The setting is a forest The setting is a forest "
                                               "The setting is a forest.")
    assert "surprise" not in plan
    assert list(plan)[:10] == ["schema", "story_id", "mode", "panels", "seconds", "narrative",
                               "goal", "seed_image", "video_model", "auto_lora"]
    assert plan["loras"] == {"global": [{"id": "film-grain", "strength": 0.8}],
                             "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
                             "stills": [], "pinned": pins}
    off, _ = se.normalize_plan(ctx._replace(auto_lora=False), raw)
    assert off["loras"] == {"global": [], "per_beat": {}, "stills": [], "pinned": pins}
    raw.pop("loras")
    assert se.normalize_plan(ctx, raw)[0]["loras"]["global"] == []
    broken, shape = se.normalize_plan(seu.make_ctx(se, ws), {"title": 5, "cast": "nobody",
                                                             "beats": [3, {"cast": "c1"}]})
    assert shape == ["plan: P2 structure: 'cast' is not a list",
                     "plan: P2 structure: the reply is missing the key 'locations'",
                     "plan: P2 structure: the reply is missing the key 'props'",
                     "plan: P2 structure: beats item 1 is not an object",
                     "beat 1: P2 structure: cast is not a list"]
    assert broken["title"] == "" and broken["cast"] == [] and broken["beats"][0]["index"] == 0


def _checks(ctx, raw):
    plan, shape = se.normalize_plan(ctx, raw)
    hard, advisory = se.plan_checks(ctx, plan, shape)
    return hard + advisory


def test_rst14_plan_checks(ws):
    chained = seu.make_ctx(se, ws, panels=6)
    assert _checks(chained, seu.plan_json("chained", 6)) == []
    for mode in ("no_stills", "shots"):
        assert _checks(seu.make_ctx(se, ws, mode=mode, panels=6), seu.plan_json(mode, 6)) == []

    def variant(mutate, mode="chained", n=6):
        raw = seu.plan_json(mode, n)
        mutate(raw)
        return _checks(seu.make_ctx(se, ws, mode=mode, panels=n), raw)

    def beat(k, **changes):
        return lambda raw: raw["beats"][k - 1].update(changes)

    def cast2(**changes):
        return lambda raw: raw["cast"][1].update(changes)

    def setting(text):
        return lambda raw: raw["locations"][0].update(setting=text)

    long_desc = "a tall woman " + "with a long " * 15 + "coat"
    cases = [
        (lambda raw: (raw["beats"].pop(2), [b.update(index=i) for i, b in
                                             enumerate(raw["beats"], start=1)]),
         ["plan: P1 beat count: expected exactly 6 beats, found 5"]),
        (beat(3, index=7), ["plan: P1 beat count: beat 3 has index 7; beats must be numbered 1 "
                            "to 6 in order"]),
        (lambda raw: raw.update(title=""), ["plan: P2 structure: title must be a non-empty string"]),
        (beat(2, location="l9"), ["beat 2: P2 structure: location 'l9' is not defined"]),
        (beat(2, cast=["c9"]), ["beat 2: P2 structure: cast id 'c9' is not defined"]),
        (lambda raw: raw.pop("props"), ["plan: P2 structure: the reply is missing the key 'props'"]),
        (lambda raw: raw["cast"][1].update(id="x2"),
         ["plan: P2 structure: cast entry 2 has id 'x2'; ids are c1, c2 and so on"]),
        (beat(4, action=""), ["beat 4: P2 structure: action is missing or empty"]),
        (lambda raw: raw.update(locations=[]),
         ["plan: P2 structure: there must be at least one location"]
         + ["beat %d: P2 structure: location 'l1' is not defined" % k for k in range(1, 7)]),
        (cast2(phrase="the very old bald monk"),
         ["plan: P3 cast entry: c2's phrase 'the very old bald monk' has 5 words; at most 4"]),
        (cast2(phrase="The Courier"), ["plan: P3 cast entry: c2's phrase 'The Courier' is also c1's"]),
        (cast2(descriptor="an old man"),
         ["plan: P3 cast entry: c2's descriptor: must be 8-60 words, got 3"]),
        (cast2(phrase="the monk!"),
         ["plan: P3 cast entry: c2's phrase word 'monk!' may contain only letters, digits, "
          "apostrophes and hyphens (phrase 'the monk!')"]),
        (setting("A rainy harbour town in modern Japan, wet cobblestones underfoot, boats behind, "
                 "under grey light."),
         ['plan: P4 setting sentence: l1\'s setting does not start with "The setting is"']),
        (setting("The setting is a harbour."),
         ["plan: P4 setting sentence: l1's setting is 5 words; it must be 12-45"]),
        (setting("The setting is a rainy harbour town in Japan. Boats rock behind under grey "
                 "light all afternoon."),
         ["plan: P4 setting sentence: l1's setting is more than one sentence"]),
        (beat(2, arc="middle"), ["beat 2: P5 arc: 'middle' is not one of introduction, rising, "
                                 "climax, falling, resolution"]),
        (beat(5, arc="rising"), ["plan: P5 arc: no beat has arc 'climax'"]),
        (lambda raw: (raw["beats"][3].update(arc="climax"), raw["beats"][4].update(arc="rising")),
         ["beat 5: P6 arc order: 'rising' follows 'climax'"]),
        (beat(1, arc="rising"), ["plan: P5 arc: no beat has arc 'introduction'",
                                 "plan: P6 arc order: the first beat's arc is 'rising', not "
                                 "'introduction'"]),
        (beat(6, arc="falling"), ["plan: P5 arc: no beat has arc 'resolution'",
                                  "plan: P6 arc order: the last beat's arc is 'falling', not "
                                  "'resolution'"]),
        (beat(3, shot="aerial shot"), ["beat 3: P7 shot type: 'aerial shot' is not one of: extreme "
                                       "wide shot, wide shot, medium shot, medium close-up, "
                                       "close-up, extreme close-up"]),
        (beat(3, camera="zoom"), ["beat 3: P8 camera: 'zoom' is not one of: static, slow push-in, "
                                  "slow pull-back, slow pan left, slow pan right, slow tilt up, "
                                  "slow tilt down, tracking"]),
        (lambda raw: (raw["cast"].append({"id": "c3", "phrase": "the guard",
                                          "descriptor": seu.MONK}),
                      raw["beats"][1].update(cast=["c1", "c2", "c3"])),
         ("shots", ["beat 2: P9 cast count: 3 characters on screen; at most 2 in this mode"])),
        (lambda raw: (raw["cast"][1].update(descriptor=long_desc),
                      raw["cast"].append({"id": "c3", "phrase": "the guard",
                                          "descriptor": long_desc}),
                      raw["beats"][0].update(cast=["c1", "c2", "c3"]),
                      [b.update(cast=["c1", "c2", "c3"]) for b in raw["beats"]]),
         ["beat 1: P10 word budget: Image: the pasted sentences take 153 of its 120-170 words, "
          "leaving fewer than 20 for the writer"]),
        (lambda raw: [b.update(location="l2") for b in raw["beats"][3:]],
         ["beat 4: P11 location change: moves from l1 to l2 with no cut; the action must carry "
          "the characters there"]),
        (beat(3, cast=["c1", "c2"]), ["beat 3: P12 new character: c2 is not in the opening frame; "
                                      "their look is left to the video model"]),
    ]
    for mutate, expected in cases:
        mode = "chained"
        if isinstance(expected, tuple):
            mode, expected = expected
        assert variant(mutate, mode=mode) == expected, expected


def _lora_ctx(ws, tmp_path, **overrides):
    files = str(tmp_path / "files")
    entries = [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL]),
        seu.catalog_entry(seu.lora_file(files, "other"), "other-model",
                          base_models=["Other/pack"])]
    overrides.setdefault("catalog", {"schema_version": 1, "entries": entries})
    return seu.make_ctx(se, ws, **overrides)


def _lora_violations(ctx, loras, cast=None, beat_cast=None):
    raw = seu.plan_json(ctx.mode, ctx.panels, cast=cast)
    if beat_cast is not None:
        raw["beats"][0]["cast"] = beat_cast
    raw["loras"] = loras
    plan, _ = se.normalize_plan(ctx, raw)
    compatible = {e["id"]: e for e in se.compatible_entries(ctx)}
    catalog = {e["id"]: e for e in ctx.catalog["entries"]}
    hard, advisory = se.lora_checks(ctx, plan, compatible, catalog)
    return hard, advisory


def _pins(*specs):
    return [{"path": path, "strength": strength, "catalog_id": cid, "kind": kind}
            for path, strength, cid, kind in specs]


def test_rst15_lora_checks(ws, tmp_path, story_env):
    ctx = _lora_ctx(ws, tmp_path)
    paths = {e["id"]: e["path"] for e in ctx.catalog["entries"]}
    model = seu.VIDEO_MODEL

    def pick(entry_id, strength=0.8):
        return {"id": entry_id, "strength": strength}

    def lv(loras, **kw):
        return _lora_violations(kw.pop("ctx", ctx), loras, **kw)

    assert lv({"global": [pick("film-grain"), pick("fast-motion")],
               "per_beat": {"2": [pick("rain-physics")]}, "stills": [pick("ink-stills")]}) == (
        ["beat 2: L3 motion: 2 motion or physics LoRAs on this panel (fast-motion, "
         "rain-physics); at most 1"], [])
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("rain-physics")]},
               "stills": [pick("ink-stills")]}) == ([], [])
    cases = [
        ({"global": [pick("nope")]}, ["plan: L1 catalog id: 'nope' is not in the catalog"]),
        ({"global": [pick("other-model")]},
         ["plan: L1 catalog id: 'other-model' does not support model %s" % model]),
        ({"global": [pick("ink-stills")]},
         ["plan: L1 catalog id: 'ink-stills' is a stills LoRA; global and per-beat picks must "
          "be video LoRAs"]),
        ({"stills": [pick("fast-motion")]},
         ["plan: L1 catalog id: 'fast-motion' is a video LoRA; a stills pick must be a stills "
          "LoRA"]),
        ({"per_beat": {"9": [pick("fast-motion")]}},
         ["plan: L1 catalog id: per_beat key '9' is not a beat number from 1 to 3"]),
        ({"per_beat": {"2": [{"id": "fast-motion", "strength": "high"}]}},
         ['beat 2: L1 catalog id: pick {"id": "fast-motion", "strength": "high"} is not an '
          'object with an id and a numeric strength']),
        ({"global": [pick("film-grain"), pick("big-style")]},
         ["plan: L2 style: 2 style LoRAs for every panel (film-grain, big-style); at most 1"]),
        ({"per_beat": {"2": [pick("film-grain")]}},
         ["beat 2: L2 style: style LoRA 'film-grain' can only be a global pick"]),
        ({"global": [pick("fast-motion", 1.4)]},
         ["plan: L5 strength: 'fast-motion' strength 1.4 is outside its range 0.5 to 1.0"]),
        ({"stills": [pick("ink-stills"), pick("ink-stills")]},
         ["plan: L7 stills: 2 stills LoRAs; at most 1"]),
    ]
    for loras, expected in cases:
        full = {"global": [], "per_beat": {}, "stills": []}
        full.update(loras)
        assert lv(full) == (expected, []), expected
    pins3 = _pins(("/p/1.safetensors", 1.0, None, None), ("/p/2.safetensors", 1.0, None, None),
                  ("/p/3.safetensors", 1.0, None, None))
    assert lv({"global": [pick("film-grain")], "per_beat": {"2": [pick("fast-motion")]}},
              ctx=ctx._replace(pinned=pins3)) == (
        ["beat 2: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned LoRA, "
         "film-grain, fast-motion); at most 4"], [])
    members = _cast_members(story_env, "kyra", "ronin")
    cast_ctx = ctx._replace(pinned=pins3, members=members, mode="shots")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    assert lv({}, ctx=cast_ctx, cast=fixed, beat_cast=["c1", "c2"]) == (
        [], ["beat 1: L4 LoRA count: 5 LoRAs on this panel (pinned LoRA, pinned LoRA, pinned "
             "LoRA, character kyra, character ronin); at most 4"])
    dup_pin = _pins((paths["rain-physics"], 1.0, "rain-physics", "physics"))
    hard, _ = lv({"global": [pick("rain-physics")]}, ctx=ctx._replace(pinned=dup_pin))
    assert "beat 1: L6 duplicate: 'rain-physics' is applied twice on this panel" in hard
    assert sum("L6" in h for h in hard) == 1
    hard, _ = lv({"stills": [pick("ink-stills")]}, ctx=ctx._replace(mode="no_stills"))
    assert hard == ["plan: L1 catalog id: 'ink-stills' is not in the catalog",
                    "plan: L7 stills: this movie has no stills; stills must be empty"]
    assert lv({"stills": [pick("ink-stills")]},
              ctx=ctx._replace(stills_pinned=[os.path.realpath(paths["ink-stills"])])) == (
        ["plan: L7 stills: 'ink-stills' is also passed with --stills-lora"], [])
    style_pin = _pins((paths["big-style"], 1.9, "big-style", "style"))
    assert lv({"global": [pick("film-grain")]}, ctx=ctx._replace(pinned=style_pin)) == (
        ["plan: L2 style: 2 style LoRAs for every panel (big-style, film-grain); at most 1"], [])
    assert lv({}, ctx=ctx._replace(pinned=style_pin)) == ([], [])
    off = ctx._replace(auto_lora=False)
    assert lv({"global": [pick("nope")]}, ctx=off) == ([], [])


def test_lct6b_compatible_set_and_warnings(ws, tmp_path, story_env):
    members = _cast_members(story_env, "kyra")
    files = str(tmp_path / "files")
    gone = seu.catalog_entry(seu.lora_file(files, "gone"), "gone-motion")
    os.remove(gone["path"])
    clash = seu.catalog_entry(seu.lora_file(files, "clash"), "clash-motion", triggers=["KyraWmn"])
    ok = seu.catalog_entry(seu.lora_file(files, "ok"), "ok-motion")
    ink = seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                            target="stills", base_models=[seu.STILLS_MODEL])
    wrong_stills = seu.catalog_entry(seu.lora_file(files, "ws"), "video-model-stills",
                                     kind="style", target="stills", base_models=[seu.VIDEO_MODEL])
    catalog = {"schema_version": 1, "entries": [gone, clash, ok, ink, wrong_stills]}
    ctx = seu.make_ctx(se, ws, mode="shots", members=members, catalog=catalog)
    assert [e["id"] for e in se.compatible_entries(ctx)] == ["ink-stills", "ok-motion"]
    assert se.catalog_warnings(ctx) == [
        "Warning: catalog LoRA clash-motion is skipped: its trigger KyraWmn is character kyra's "
        "trigger",
        "Warning: catalog LoRA gone-motion is skipped: %s is not a readable file" % gone["path"]]
    no_stills = ctx._replace(mode="no_stills", members=[])
    assert [e["id"] for e in se.compatible_entries(no_stills)] == ["clash-motion", "ok-motion"]
    assert se.compatible_entries(ctx._replace(auto_lora=False)) == []


def _p13(ronin_name="ronin"):
    return ("library characters appear only when declared with --character %s" % ronin_name)


def test_rst55_p13_undeclared_character(ws, story_env):
    seu.ronin(story_env["lib"])
    uncast = seu.make_ctx(se, ws, panels=4)
    raw = seu.plan_json("chained", 4)
    raw["cast"][1]["phrase"] = "the ronin"
    raw["beats"][2]["action"] = "the courier hands the sealed letter to roninmn on the quay"
    raw["logline"] = "A courier crosses a rainy harbour town to meet Ronin at the temple gate."
    expected = [
        "plan: P13 undeclared character: c2's phrase names library character ronin by its "
        "referring phrase 'the ronin'; " + _p13(),
        "plan: P13 undeclared character: the logline names library character ronin by its name "
        "'Ronin'; " + _p13(),
        "plan: P13 undeclared character: beat 3's action names library character ronin by its "
        "trigger 'roninmn'; " + _p13()]
    assert _checks(uncast, raw) == expected
    clean = seu.plan_json("chained", 4)
    clean["beats"][1]["action"] = "the courier waves at the ronin across the wet quay"
    assert _checks(uncast, clean) == [
        "plan: P13 undeclared character: beat 2's action names library character ronin by its "
        "referring phrase 'the ronin'; " + _p13()]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    declared = seu.make_ctx(se, ws, panels=4, members=members)
    raw["cast"][1]["phrase"] = "the old monk"
    assert [m for m in _checks(declared, raw) if "P13" in m] == []


def test_rst57_reserved_sentence_in_the_plan_prompt(ws, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    os.makedirs(os.path.join(story_env["lib"], "broken"))
    with open(os.path.join(story_env["lib"], "broken", "character.json"), "w") as f:
        f.write("{not json")
    os.makedirs(os.path.join(story_env["lib"], "partial"))
    with open(os.path.join(story_env["lib"], "partial", "character.json"), "w") as f:
        json.dump({"name": "partial", "trigger": 5}, f)
    assert se.library_identities(ws) == [("kyra", "kyrawmn", "the woman in grey"),
                                         ("ronin", "roninmn", "the ronin")]
    uncast = seu.make_ctx(se, ws)
    prompt = se.build_plan_prompt(uncast, [], [])
    sentence = (" Never use these names or referring phrases, which belong to characters who are "
                'not in this movie: kyra ("the woman in grey"), ronin ("the ronin").\n')
    assert "accessories." + sentence in prompt
    assert "{" not in prompt and "}" not in prompt
    members = se._character_lib(WS).resolve_cast([(None, "kyra")])
    cast = seu.make_ctx(se, ws, mode="shots", members=members)
    prompt = se.build_plan_prompt(cast, [], [])
    assert ('accessories. Never use these names or referring phrases, which belong to characters '
            'who are not in this movie: ronin ("the ronin"). The following characters are already '
            'cast;') in prompt
    assert 'kyra ("the woman in grey")' not in prompt
    both = se._character_lib(WS).resolve_cast([(None, "kyra"), (None, "ronin")])
    assert "Never use these names" not in se.build_plan_prompt(
        seu.make_ctx(se, ws, mode="shots", members=both), [], [])
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
8 failed, 7 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst8_plan_prompt_matrix
FAILED tests/test_story_engine.py::test_rst9_narrative_is_inserted_verbatim
FAILED tests/test_story_engine.py::test_rst13_normalization
FAILED tests/test_story_engine.py::test_rst14_plan_checks
FAILED tests/test_story_engine.py::test_rst15_lora_checks
FAILED tests/test_story_engine.py::test_lct6b_compatible_set_and_warnings
FAILED tests/test_story_engine.py::test_rst55_p13_undeclared_character
FAILED tests/test_story_engine.py::test_rst57_reserved_sentence_in_the_plan_prompt
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# The plan: prompt (RS7), the compatible catalog set (LC6), normalization (RS9), checks
# (RS10, RS11)
# ---------------------------------------------------------------------------

NO_TOOL_SENTENCE = ("Reply with the JSON object only, with no text before or after it. Do not "
                    "call any tool: do NOT read any file, do NOT run run_python or any other "
                    "tool to check it, and do NOT count or recount words.")

PLAN_PROMPT_TEMPLATE = (
    'You are planning a short narrated movie (story-id "@@STORY_ID@@").\n'
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "@@SEED_PARAGRAPH@@Write the story bible as one JSON object with exactly these seven keys:\n"
    "\n"
    "title: the movie's title, at most 8 words.\n"
    "logline: one sentence of 8 to 40 words that summarises the story.\n"
    "cast: a list with one object per character who is ever on screen, with the keys id, phrase "
    "and descriptor. id is c1, c2, c3 and so on, in order. phrase is the character's referring "
    "phrase: at most four words, built only from details in their descriptor or stated by the "
    "narrative; the movie names them by this exact phrase everywhere. descriptor is their full "
    'visual description in 8 to 60 words that starts with "a " or "an " and does not end with a '
    "full stop: apparent age group, build, skin tone, hair colour, length and style, clothing and "
    "accessories.@@CAST_FIXED@@\n"
    "locations: a list with one object per place, with the keys id and setting. id is l1, l2 and "
    'so on. setting is one sentence of 12 to 45 words that starts with "The setting is" and names '
    "the period, the place, the ground and the light.\n"
    "props: a list with one object per object that matters to the story, with the keys id and "
    "name. id is p1, p2 and so on; name is a short noun phrase for the object. Use an empty list "
    "when no object matters.\n"
    "beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location and cast. index runs from 1 to @@PANELS@@. arc is one of "
    "introduction, rising, climax, falling, resolution, in story order; @@ARC_RULE@@ action is "
    "one sentence of 6 to 40 words saying what the characters physically do during these "
    "@@SECONDS@@ seconds: one continuous physical action that a camera can film, not a sequence "
    "of steps, with no dialogue and no on-screen text. shot is exactly one of: @@SHOT_LIST@@. "
    "camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat "
    "happens. cast is the list of ids of the characters on screen in the beat, at most "
    "@@MAX_CAST@@.\n"
    "loras: @@LORA_PARAGRAPH@@\n"
    "\n"
    "@@MODE_RULES@@" + NO_TOOL_SENTENCE)

MODE_PARAGRAPHS = {
    "chained": ("it is ONE continuous take, built @@SECONDS@@ seconds at a time. Panel 1 starts "
                "from a single still picture, and every later panel continues from the exact "
                "last frame of the panel before it. There are no cuts and no jumps in time or "
                "place: a new place, object or character must arrive through visible movement "
                "inside a beat."),
    "no_stills": ("every panel is a separate @@SECONDS@@-second shot rendered from text alone, "
                  "joined to the next panel by a hard cut. Nothing carries over between panels "
                  "except what the text states."),
    "shots": ("it is a sequence of separate shots joined by cuts, @@SECONDS@@ seconds each. "
              "Every panel is one shot that starts from its own still picture. One beat is one "
              "action: a fight or a chase takes several beats."),
}
SEED_PARAGRAPH = ("An image is attached to this message. It IS the first frame of this movie. "
                  "Describe every person it shows faithfully in cast -- each one's apparent age "
                  "group, build, skin tone, hair, clothing and accessories as actually visible "
                  "-- invent no person who is not visible, and make beat 1 start from the exact "
                  "scene it shows.\n\n")
MODE_RULES = {
    "chained": ("Rules for this movie: keep consecutive beats at the same location unless the "
                "action itself moves the characters there, and put every character who can be "
                "seen in the opening frame in beat 1's cast.\n\n"),
    "shots": ("Rules for this movie: two people never touch on screen. Split every strike, grab, "
              "push, block or hand-off into two consecutive beats -- first a beat whose cast is "
              "only the person who acts, then a beat whose cast is only the person acted on -- so "
              "the contact itself is never on screen.\n\n"),
    "no_stills": "",
}
LORA_EMPTY_PARAGRAPH = ("an object with the keys global, per_beat and stills, each empty: global "
                        "and stills are empty lists and per_beat is an empty object.")
LORA_PICK_PARAGRAPH = (
    "an object with the keys global, per_beat and stills. Each pick is an object with the keys "
    "id and strength, taken from the LoRA catalog below; strength must lie inside that entry's "
    "range. global is a list of picks applied to every panel: at most one style LoRA, plus "
    "motion or physics LoRAs that suit the whole movie. per_beat maps a beat index, written as a "
    "string, to a list of motion or physics picks for that beat only; every beat may have at "
    "most one motion or physics LoRA in total, counting global. stills is a list of at most one "
    "stills LoRA.")


def _fill(template, fragments, scalars, narrative):
    """str.replace in the RS7 order: fragment tokens, then scalar tokens, then @@NARRATIVE@@
    last, so user text is never scanned for tokens."""
    text = template
    for token, value in fragments:
        text = text.replace(token, value)
    for token, value in scalars:
        text = text.replace(token, value)
    return text.replace("@@NARRATIVE@@", narrative)


def _goal_paragraph(goal):
    return "" if goal is None else "The target output goal is " + goal + ".\n\n"


def catalog_line(entry):
    """One catalog entry as the planner and the critic see it (RS7)."""
    lo, hi = entry["strength_range"]
    return "- %s: %s LoRA for %s, default strength %s, range %s to %s. %s Use when: %s Avoid when: %s" % (
        entry["id"], entry["kind"], entry["target"], repr(float(entry["default_strength"])),
        repr(float(lo)), repr(float(hi)), _sentence(entry["description"]),
        _sentence(entry["use_when"]),
        _sentence(entry["avoid_when"]) if entry["avoid_when"] else "nothing listed.")


def _pins_block(pins):
    if not pins:
        return ""
    lines = ["\nAlready applied to every panel by the user, not to be picked again:"]
    for pin in pins:
        if pin.get("catalog_id"):
            lines.append("\n- %s (%s) at strength %s"
                         % (pin["catalog_id"], pin["kind"], repr(float(pin["strength"]))))
        else:
            lines.append("\n- a LoRA outside the catalog at strength %s"
                         % repr(float(pin["strength"])))
    return "".join(lines)


def _arc_rule(n):
    if n >= 3:
        return ("the first beat is introduction, the last is resolution, and at least one beat "
                "is climax.")
    if n == 2:
        return "the first beat is introduction and the last is resolution."
    return "use climax."


def library_identities(ws):
    """[(name, trigger, referring_phrase)] for every character.json in the character library
    ($CHARACTER_LIBRARY_DIR, else <ws>/generated/characters) that parses as an object with
    string name, trigger and referring_phrase, sorted by name, whatever its status (RS37).
    Unreadable files are skipped. character_lib.py is not loaded."""
    root = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(ws, "generated", "characters")
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in names:
        try:
            with open(os.path.join(root, entry, "character.json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if (isinstance(data, dict) and all(isinstance(data.get(k), str)
                                           for k in ("name", "trigger", "referring_phrase"))):
            found.append((data["name"], data["trigger"], data["referring_phrase"]))
    return sorted(found)


def undeclared_characters(ctx):
    """The library identities of characters that are not members of ctx (RS37)."""
    declared = {m.name for m in ctx.members}
    return [t for t in library_identities(ctx.ws) if t[0] not in declared]


def reserved_items(undeclared):
    return ", ".join('%s ("%s")' % (name, phrase) for name, _trigger, phrase in undeclared)


def _word_match(word, text):
    return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", text, re.IGNORECASE)


def undeclared_references(lib, text, undeclared, exact_phrase=False):
    """[(name, kind, matched text)] for each undeclared character text refers to, first kind
    per character in the RS37 order: referring phrase, trigger, name. exact_phrase compares a
    cast entry's phrase by case-insensitive equality instead of occurrence."""
    hits = []
    for name, trigger, phrase in undeclared:
        hit = None
        if exact_phrase:
            if text.strip().lower() == phrase.strip().lower():
                hit = "referring phrase", text
        else:
            try:
                match = lib._phrase_regex(lib.normalize_phrase(phrase)).search(text)
            except lib.CharacterError:
                match = None
            if match:
                hit = "referring phrase", match.group(0)
        for kind, word in (("trigger", trigger), ("name", name)):
            if hit is None:
                match = _word_match(word, text)
                if match:
                    hit = kind, match.group(0)
        if hit:
            hits.append((name, hit[0], hit[1]))
    return hits


def undeclared_message(prefix, where, hit):
    name, kind, matched = hit
    return ("%s %s names library character %s by its %s '%s'; library characters appear only "
            "when declared with --character %s" % (prefix, where, name, kind, matched, name))


def build_plan_prompt(ctx, compatible, pins):
    """The exact plan prompt of RS7."""
    undeclared = undeclared_characters(ctx)
    cast_fixed = ""
    if undeclared:
        cast_fixed = (" Never use these names or referring phrases, which belong to characters "
                      "who are not in this movie: " + reserved_items(undeclared) + ".")
    if ctx.members:
        cast_fixed += (" The following characters are already cast; list them first in cast with "
                      "exactly these ids, phrases and descriptors, and give your own characters "
                      "the next ids:")
        for i, member in enumerate(ctx.members, start=1):
            cast_fixed += '\n- id c%d, phrase "%s", descriptor "%s"' % (
                i, member.phrase, member.descriptor)
    if not ctx.auto_lora or not compatible:
        lora = LORA_EMPTY_PARAGRAPH
    else:
        lora = LORA_PICK_PARAGRAPH
        if ctx.mode == "no_stills":
            lora += " This movie has no stills, so stills stays empty."
        lora += (" Pick a LoRA only when its use-when text fits and its avoid-when text does "
                 "not; leave the lists empty when nothing fits.")
        lora += "\n\nLoRA catalog (pick only from these):\n"
        lora += "\n".join(catalog_line(e) for e in compatible) + _pins_block(pins)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@SEED_PARAGRAPH@@", SEED_PARAGRAPH if ctx.seed_agent_image else ""),
        ("@@CAST_FIXED@@", cast_fixed),
        ("@@ARC_RULE@@", _arc_rule(ctx.panels)),
        ("@@SHOT_LIST@@", ", ".join(SHOT_TYPES)),
        ("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS)),
        ("@@LORA_PARAGRAPH@@", lora),
        ("@@MODE_RULES@@", MODE_RULES[ctx.mode]),
    ]
    scalars = [("@@STORY_ID@@", ctx.story_id), ("@@PANELS@@", str(ctx.panels)),
               ("@@SECONDS@@", ctx.seconds), ("@@MAX_CAST@@", str(MAX_CAST[ctx.mode]))]
    return _fill(PLAN_PROMPT_TEMPLATE, fragments, scalars, ctx.narrative)


def _readable(path):
    return isinstance(path, str) and os.path.isfile(path) and os.access(path, os.R_OK)


def _catalog_filter(ctx):
    """(compatible entries sorted by id, warning lines) for LC6's planner set."""
    if not ctx.auto_lora:
        return [], []
    lora_catalog = _lora_catalog(ctx.ws)
    member_triggers = {m.trigger.lower(): m.name for m in ctx.members}
    kept, warnings = [], []
    for entry in sorted(ctx.catalog.get("entries", []), key=lambda e: e["id"]):
        if entry["target"] == "video":
            ok = lora_catalog.compatible(entry, ctx.video_model)
        else:
            ok = (ctx.mode != "no_stills"
                  and lora_catalog.compatible(entry, lora_catalog.STILLS_BASE_MODEL))
        if not ok:
            continue
        if not _readable(entry["path"]):
            warnings.append("Warning: catalog LoRA %s is skipped: %s is not a readable file"
                            % (entry["id"], entry["path"]))
            continue
        clash = [t for t in entry["triggers"] if t.lower() in member_triggers]
        if clash:
            warnings.append("Warning: catalog LoRA %s is skipped: its trigger %s is character "
                            "%s's trigger" % (entry["id"], clash[0],
                                              member_triggers[clash[0].lower()]))
            continue
        kept.append(entry)
    return kept, warnings


def compatible_entries(ctx):
    """The planner's compatible catalog set (LC6), sorted by id. Prints nothing."""
    return _catalog_filter(ctx)[0]


def catalog_warnings(ctx):
    """The LC6 skip warnings for ctx's catalog (printed by run, recheck and the dry run)."""
    return _catalog_filter(ctx)[1]


def _clean_str(value):
    return _collapse(value) if isinstance(value, str) else ""


def _empty_loras():
    return {"global": [], "per_beat": {}, "stills": []}


def _list_of_objects(raw, key, shape, scope="plan"):
    value = raw.get(key)
    if key not in raw:
        shape.append("%s: P2 structure: the reply is missing the key '%s'" % (scope, key))
        return []
    if not isinstance(value, list):
        shape.append("%s: P2 structure: '%s' is not a list" % (scope, key))
        return []
    items = []
    for i, item in enumerate(value, start=1):
        if isinstance(item, dict):
            items.append(item)
        else:
            shape.append("%s: P2 structure: %s item %d is not an object" % (scope, key, i))
    return items


def _normalize_picks(picks, by_id):
    out = []
    for pick in picks if isinstance(picks, list) else []:
        if (isinstance(pick, dict) and "strength" not in pick and isinstance(pick.get("id"), str)
                and pick["id"] in by_id):
            pick = dict(pick, strength=by_id[pick["id"]]["default_strength"])
        out.append(pick)
    return out


def normalize_plan(ctx, raw):
    """(plan, shape): the Section 2.2 plan built from a parsed plan-writer reply (RS9), and the
    P2 violations for container shapes that normalization had to repair (a missing or non-list
    cast, locations, props or beats; an item that is not an object; a beat cast that is not a
    list). Wrong-typed string fields become "" and are reported by plan_checks."""
    shape = []
    plan = {"schema": PLAN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "seconds": ctx.seconds, "narrative": ctx.narrative,
            "goal": ctx.goal, "seed_image": ctx.seed_image, "video_model": ctx.video_model,
            "auto_lora": ctx.auto_lora,
            "title": _clean_str(raw.get("title")), "logline": _clean_str(raw.get("logline"))}
    cast = []
    for item in _list_of_objects(raw, "cast", shape):
        descriptor = _clean_str(item.get("descriptor"))
        if descriptor.endswith("."):
            descriptor = descriptor[:-1].rstrip()
        cast.append({"id": _clean_str(item.get("id")), "phrase": _clean_str(item.get("phrase")),
                     "descriptor": descriptor, "cast_name": None})
    for i, member in enumerate(ctx.members, start=1):
        fixed = {"id": "c%d" % i, "phrase": member.phrase, "descriptor": member.descriptor,
                 "cast_name": member.name}
        at = [j for j, c in enumerate(cast) if c["id"] == fixed["id"]]
        if at:
            cast[at[0]] = fixed
        else:
            cast.insert(i - 1, fixed)
    plan["cast"] = cast
    locations = []
    for item in _list_of_objects(raw, "locations", shape):
        setting = _clean_str(item.get("setting"))
        if setting and not setting.endswith((".", "!", "?")):
            setting += "."
        locations.append({"id": _clean_str(item.get("id")), "setting": setting})
    plan["locations"] = locations
    plan["props"] = [{"id": _clean_str(item.get("id")), "name": _clean_str(item.get("name"))}
                     for item in _list_of_objects(raw, "props", shape)]
    beats = []
    for k, item in enumerate(_list_of_objects(raw, "beats", shape), start=1):
        index = item.get("index")
        beat_cast = item.get("cast")
        if not isinstance(beat_cast, list):
            shape.append("beat %d: P2 structure: cast is not a list" % k)
            beat_cast = []
        beats.append({
            "index": index if isinstance(index, int) and not isinstance(index, bool) else 0,
            "arc": _clean_str(item.get("arc")).lower(), "action": _clean_str(item.get("action")),
            "shot": _clean_str(item.get("shot")).lower(),
            "camera": _clean_str(item.get("camera")).lower(),
            "location": _clean_str(item.get("location")),
            "cast": [_clean_str(c) if isinstance(c, str) else json.dumps(c) for c in beat_cast]})
    plan["beats"] = beats
    loras = raw.get("loras")
    if not ctx.auto_lora or not isinstance(loras, dict):
        picks = _empty_loras()
    else:
        by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
        per_beat = loras.get("per_beat")
        picks = {"global": _normalize_picks(loras.get("global"), by_id),
                 "per_beat": {str(key): _normalize_picks(value, by_id)
                              for key, value in (per_beat.items()
                                                 if isinstance(per_beat, dict) else [])},
                 "stills": _normalize_picks(loras.get("stills"), by_id)}
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
    return plan, shape


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")   # character_lib._SENTENCE_SPLIT_RE
_ID_RES = {"cast": re.compile(r"c[1-9][0-9]*"), "locations": re.compile(r"l[1-9][0-9]*"),
           "props": re.compile(r"p[1-9][0-9]*")}


def _q(text):
    return "'%s'" % text


def _setting_problems(setting):
    """The P4 details for one setting sentence (start, word count, one sentence)."""
    problems = []
    if not setting.startswith("The setting is "):
        problems.append('does not start with "The setting is"')
    words = _words(setting)
    if not 12 <= words <= 45:
        problems.append("is %d words; it must be 12-45" % words)
    if len([s for s in _SENTENCE_SPLIT_RE.split(setting.strip()) if s.strip()]) != 1:
        problems.append("is more than one sentence")
    return problems


def pasted_pieces(ctx, plan, k):
    """{field: [pasted sentences in assembly order]} for panel k (RS14): the pieces of each
    assembled field that the writer does not write."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    by_location = {l["id"]: l for l in plan["locations"]}
    setting = by_location[beat["location"]]["setting"] if beat["location"] in by_location else ""
    identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]
    shot = shot_sentence(beat) if beat["shot"] in SHOT_TYPES else ""
    camera = dict(CAMERA_SENTENCES).get(beat["camera"], "")
    pieces = [setting] + identities + [shot]
    if ctx.mode == "chained":
        if k == 1:
            return {"image": pieces, "motion": [camera], "narration": []}
        return {"motion": [], "narration": []}
    if ctx.mode == "no_stills":
        return {"prompt": identities + [setting, shot, camera], "narration": []}
    return {"image": pieces, "motion": [camera], "narration": []}


def identity(cast_entry):
    """The identity sentence of a plan cast entry (character_lib.identity_sentence format)."""
    phrase = cast_entry["phrase"]
    return phrase[:1].upper() + phrase[1:] + " is " + cast_entry["descriptor"] + "."


def shot_sentence(beat):
    shot = beat["shot"]
    return "The shot is " + ("an " if shot[:1] in "aeiou" else "a ") + shot + "."


def field_range(ctx, k, field):
    """(kind, (lo, hi)) of an assembled field with a word range, or None (Narration, and
    nothing else, has none)."""
    ranges = WORD_RANGES[ctx.mode]
    if ctx.mode == "chained":
        if field == "image" and k == 1:
            return "image", ranges["image1"]
        if field == "motion":
            return "motion", ranges["motion1"] if k == 1 else ranges["motion"]
    elif ctx.mode == "no_stills" and field == "prompt":
        return "prompt", ranges["prompt"]
    elif ctx.mode == "shots" and field in ("image", "motion"):
        return field, ranges[field]
    return None


def plan_checks(ctx, plan, shape=()):
    """(hard, advisory) violation strings for a normalized plan (RS10). shape holds
    normalize_plan's container-shape P2 violations, reported first."""
    hard, advisory = list(shape), []
    n = ctx.panels
    beats = plan["beats"]
    if len(beats) != n:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (n, len(beats)))
    for i, beat in enumerate(beats):
        if beat["index"] != i + 1:
            hard.append("plan: P1 beat count: beat %d has index %r; beats must be numbered 1 to %d "
                        "in order" % (i + 1, beat["index"], n))
    for key in ("title", "logline"):
        if not plan[key]:
            hard.append("plan: P2 structure: %s must be a non-empty string" % key)
    valid = {}
    for kind, fields in (("cast", ("phrase", "descriptor")), ("locations", ("setting",)),
                         ("props", ("name",))):
        seen = set()
        valid[kind] = {}
        for pos, entry in enumerate(plan[kind], start=1):
            label = entry["id"] if _ID_RES[kind].fullmatch(entry["id"]) else None
            if label is None:
                hard.append("plan: P2 structure: %s entry %d has id %s; ids are %s1, %s2 and so on"
                            % (kind, pos, _q(entry["id"]), kind[0], kind[0]))
            elif label in seen:
                hard.append("plan: P2 structure: %s id %s is used twice" % (kind, _q(label)))
                label = None
            missing = [f for f in fields if not entry[f]]
            for field in missing:
                hard.append("plan: P2 structure: %s entry %d has no %s" % (kind, pos, field))
            if label is not None:
                seen.add(label)
                if not missing:
                    valid[kind][label] = entry
    if not plan["locations"]:
        hard.append("plan: P2 structure: there must be at least one location")
    for k, beat in enumerate(beats, start=1):
        for field in ("arc", "action", "shot", "camera", "location"):
            if not beat[field]:
                hard.append("beat %d: P2 structure: %s is missing or empty" % (k, field))
        if beat["location"] and beat["location"] not in valid["locations"]:
            hard.append("beat %d: P2 structure: location %s is not defined"
                        % (k, _q(beat["location"])))
        for c in beat["cast"]:
            if c not in valid["cast"]:
                hard.append("beat %d: P2 structure: cast id %s is not defined" % (k, _q(c)))
        for c in sorted(set(c for c in beat["cast"] if beat["cast"].count(c) > 1)):
            hard.append("beat %d: P2 structure: cast id %s is listed twice" % (k, _q(c)))
    lib = _character_lib(ctx.ws)
    phrases = {}
    for cid, entry in valid["cast"].items():
        try:
            lib.normalize_phrase(entry["phrase"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
            continue
        words = _words(entry["phrase"])
        if entry["cast_name"] is None and words > 4:
            hard.append("plan: P3 cast entry: %s's phrase %s has %d words; at most 4"
                        % (cid, _q(entry["phrase"]), words))
        other = phrases.get(entry["phrase"].lower())
        if other is not None:
            hard.append("plan: P3 cast entry: %s's phrase %s is also %s's"
                        % (cid, _q(entry["phrase"]), other))
        else:
            phrases[entry["phrase"].lower()] = cid
        try:
            lib.validate_descriptor(entry["descriptor"])
        except lib.CharacterError as e:
            hard.append("plan: P3 cast entry: %s's %s" % (cid, e))
    for lid, entry in valid["locations"].items():
        for problem in _setting_problems(entry["setting"]):
            hard.append("plan: P4 setting sentence: %s's setting %s" % (lid, problem))
    arcs = [beat["arc"] if beat["arc"] in ARC_ROLES else None for beat in beats]
    for k, beat in enumerate(beats, start=1):
        if beat["arc"] and beat["arc"] not in ARC_ROLES:
            hard.append("beat %d: P5 arc: %s is not one of %s"
                        % (k, _q(beat["arc"]), ", ".join(ARC_ROLES)))
    required = (() if n == 1 else ("introduction", "resolution") if n == 2
                else ("introduction", "climax", "resolution"))
    for role in required:
        if role not in arcs:
            hard.append("plan: P5 arc: no beat has arc %s" % _q(role))
    for k in range(2, len(arcs) + 1):
        a, b = arcs[k - 2], arcs[k - 1]
        if a and b and ARC_ROLES.index(b) < ARC_ROLES.index(a):
            advisory.append("beat %d: P6 arc order: %s follows %s" % (k, _q(b), _q(a)))
    if n >= 2 and arcs:
        if arcs[0] and arcs[0] != "introduction":
            advisory.append("plan: P6 arc order: the first beat's arc is %s, not 'introduction'"
                            % _q(arcs[0]))
        if arcs[-1] and arcs[-1] != "resolution":
            advisory.append("plan: P6 arc order: the last beat's arc is %s, not 'resolution'"
                            % _q(arcs[-1]))
    for k, beat in enumerate(beats, start=1):
        if beat["shot"] and beat["shot"] not in SHOT_TYPES:
            hard.append("beat %d: P7 shot type: %s is not one of: %s"
                        % (k, _q(beat["shot"]), ", ".join(SHOT_TYPES)))
        if beat["camera"] and beat["camera"] not in CAMERA_KEYS:
            hard.append("beat %d: P8 camera: %s is not one of: %s"
                        % (k, _q(beat["camera"]), ", ".join(CAMERA_KEYS)))
        if len(beat["cast"]) > MAX_CAST[ctx.mode]:
            hard.append("beat %d: P9 cast count: %d characters on screen; at most %d in this mode"
                        % (k, len(beat["cast"]), MAX_CAST[ctx.mode]))
        if k <= n:
            for field, pasted in pasted_pieces(ctx, plan, k).items():
                spec = field_range(ctx, k, field)
                pasted = [p for p in pasted if p]
                if spec is None or not pasted:
                    continue
                kind, (lo, hi) = spec
                used = _words(" ".join(pasted))
                if hi - used < MIN_WRITER_WORDS[kind]:
                    hard.append("beat %d: P10 word budget: %s: the pasted sentences take %d of its "
                                "%d-%d words, leaving fewer than %d for the writer"
                                % (k, field.capitalize(), used, lo, hi, MIN_WRITER_WORDS[kind]))
    if ctx.mode == "chained":
        for k in range(2, len(beats) + 1):
            prev, cur = beats[k - 2]["location"], beats[k - 1]["location"]
            if (prev in valid["locations"] and cur in valid["locations"] and prev != cur):
                advisory.append("beat %d: P11 location change: moves from %s to %s with no cut; "
                                "the action must carry the characters there" % (k, prev, cur))
        opening = set(beats[0]["cast"]) if beats else set()
        for k in range(2, len(beats) + 1):
            for c in beats[k - 1]["cast"]:
                if c in valid["cast"] and c not in opening:
                    advisory.append("beat %d: P12 new character: %s is not in the opening frame; "
                                    "their look is left to the video model" % (k, c))
    undeclared = undeclared_characters(ctx)
    if undeclared:
        texts = []
        for entry in plan["cast"]:
            if entry["cast_name"] is None:
                texts.append(("%s's phrase" % entry["id"], entry["phrase"], True))
                texts.append(("%s's descriptor" % entry["id"], entry["descriptor"], False))
        texts += [("the title", plan["title"], False), ("the logline", plan["logline"], False)]
        texts += [("%s's setting" % l["id"], l["setting"], False) for l in plan["locations"]]
        texts += [("%s's name" % p["id"], p["name"], False) for p in plan["props"]]
        texts += [("beat %d's action" % k, b["action"], False)
                  for k, b in enumerate(beats, start=1)]
        for where, text, exact in texts:
            for hit in undeclared_references(lib, text, undeclared, exact_phrase=exact):
                hard.append(undeclared_message("plan: P13 undeclared character:", where, hit))
    return hard, advisory


def _is_pick(pick):
    return (isinstance(pick, dict) and isinstance(pick.get("id"), str)
            and isinstance(pick.get("strength"), (int, float))
            and not isinstance(pick.get("strength"), bool))


def lora_checks(ctx, plan, compatible_by_id, catalog_by_id):
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA."""
    hard, advisory = [], []
    if not ctx.auto_lora:
        return hard, advisory
    n = ctx.panels
    loras = plan["loras"]
    lora_catalog = _lora_catalog(ctx.ws)

    def check_pick(pick, scope, target):
        if not _is_pick(pick):
            hard.append("%s: L1 catalog id: pick %s is not an object with an id and a numeric "
                        "strength" % (scope, json.dumps(pick, ensure_ascii=False)))
            return None
        entry = catalog_by_id.get(pick["id"])
        if entry is None:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        if target == "video" and entry["target"] != "video":
            hard.append("%s: L1 catalog id: %s is a stills LoRA; global and per-beat picks must "
                        "be video LoRAs" % (scope, _q(pick["id"])))
            return None
        if target == "stills" and entry["target"] != "stills":
            hard.append("%s: L1 catalog id: %s is a video LoRA; a stills pick must be a stills "
                        "LoRA" % (scope, _q(pick["id"])))
            return None
        model = ctx.video_model if target == "video" else lora_catalog.STILLS_BASE_MODEL
        if not lora_catalog.compatible(entry, model):
            hard.append("%s: L1 catalog id: %s does not support model %s"
                        % (scope, _q(pick["id"]), model))
            return None
        if pick["id"] not in compatible_by_id:
            hard.append("%s: L1 catalog id: %s is not in the catalog" % (scope, _q(pick["id"])))
            return None
        lo, hi = entry["strength_range"]
        if not lo <= pick["strength"] <= hi:
            hard.append("plan: L5 strength: %s strength %s is outside its range %s to %s"
                        % (_q(pick["id"]), repr(float(pick["strength"])), repr(float(lo)),
                           repr(float(hi))))
        return dict(entry, strength=pick["strength"])

    global_picks = [e for e in (check_pick(p, "plan", "video") for p in loras["global"]) if e]
    per_beat = {}
    for key, picks in loras["per_beat"].items():
        if key not in [str(k) for k in range(1, n + 1)]:
            hard.append("plan: L1 catalog id: per_beat key %s is not a beat number from 1 to %d"
                        % (_q(key), n))
            continue
        per_beat[int(key)] = [e for e in (check_pick(p, "beat %s" % key, "video")
                                          for p in picks) if e]
    stills = [e for e in (check_pick(p, "plan", "stills") for p in loras["stills"]) if e]
    pins = loras.get("pinned", [])

    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"

    styles = ([pin_label(p) for p in pins if p.get("kind") == "style"]
              + [e["id"] for e in global_picks if e["kind"] == "style"])
    if len(styles) > 1:
        hard.append("plan: L2 style: %d style LoRAs for every panel (%s); at most 1"
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                hard.append("beat %d: L2 style: style LoRA %s can only be a global pick"
                            % (k, _q(e["id"])))
    by_cast = {c["id"]: c for c in plan["cast"]}
    reported_dupes = set()
    pin_paths = {os.path.realpath(p["path"]) for p in pins}
    for k in range(1, n + 1):
        beat = plan["beats"][k - 1] if k <= len(plan["beats"]) else {"cast": []}
        loras_k = ([(pin_label(p), p.get("kind"), p.get("catalog_id"), None) for p in pins]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in global_picks]
                   + [(e["id"], e["kind"], e["id"], e["path"]) for e in per_beat.get(k, [])]
                   + [("character " + by_cast[c]["cast_name"], "character", None, None)
                      for c in beat["cast"] if c in by_cast and by_cast[c]["cast_name"]])
        motion = [label for label, kind, _i, _p in loras_k if kind in ("motion", "physics")]
        if len(motion) > 1:
            hard.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
        if len(loras_k) > LORA_PANEL_LIMIT:
            message = ("beat %d: L4 LoRA count: %d LoRAs on this panel (%s); at most %d"
                       % (k, len(loras_k), ", ".join(l[0] for l in loras_k), LORA_PANEL_LIMIT))
            (hard if (global_picks or per_beat.get(k)) else advisory).append(message)
        ids = [i for _l, _k, i, _p in loras_k if i]
        for dup in sorted(set(i for i in ids if ids.count(i) > 1)):
            if dup not in reported_dupes:
                reported_dupes.add(dup)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(dup)))
        for label, _kind, catalog_id, path in loras_k:
            if (path and os.path.realpath(path) in pin_paths and catalog_id not in reported_dupes):
                reported_dupes.add(catalog_id)
                hard.append("beat %d: L6 duplicate: %s is applied twice on this panel"
                            % (k, _q(catalog_id)))
    if len(loras["stills"]) > 1:
        hard.append("plan: L7 stills: %d stills LoRAs; at most 1" % len(loras["stills"]))
    if ctx.mode == "no_stills" and loras["stills"]:
        hard.append("plan: L7 stills: this movie has no stills; stills must be empty")
    for e in stills:
        if os.path.realpath(e["path"]) in set(ctx.stills_pinned):
            hard.append("plan: L7 stills: %s is also passed with --stills-lora" % _q(e["id"]))
    return hard, advisory
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
15 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: plan prompt, normalization, plan and LoRA checks, P13 (story RS7, RS9-RS11, RS37; catalog LC6)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 6: Panels: lexicons, panel prompt, writer cleanup, assembly, panel checks, N15

Implements RS3, RS12, RS13 (cleanup, title fallback, reply validity; the retry and budget are Task 9), RS14, RS15 (N1-N14 and the appended S1-S12/W2), RS16, and the panel half of RS37 (the reserved line, N15). Tests RST12, RST16, RST17 (cleanup and title), RST18, RST19, RST20, RST21, RST56 (panels; re-check and `plan_free_report` are RST56b in Task 10), RST57 (the panel prompt).

**Files:**
- Modify: `tests/story_engine_testutil.py`
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Task 5's `pasted_pieces`, `field_range`, `identity`, `shot_sentence`, `undeclared_characters`, `undeclared_references`, `undeclared_message`, `reserved_items`, `_fill`, `_goal_paragraph`, `MODE_PARAGRAPHS`, `NO_TOOL_SENTENCE`, `_q`; `character_lib._passage_spans`, `_blank`, `_person_refs`, `find_phrases`, `is_animal_phrase`, `SHOTS_PERSON_NOUNS`, `_OFFSCREEN_RE`, `_CHAIN_WORD_RE`, `_COMMA_AND_RE`, `_WORD_RE`, `_SENTENCE_SPLIT_RE`, `shots_violations`, `shots_advisories`; `bin/ltx-story-manifest._parse_prompts_md`.
- Produces: In `se`: `APPEARANCE_WORDS`, `DIALOGUE_RE`, `ONSCREEN_TEXT_RE`, `CUT_RE`, `PLACEHOLDER_RE`, `COPIED_EXAMPLES`, `LABELS`, `PANEL_PROMPT_TEMPLATE`, `SHOTS_PANEL_RULES`, `SEED_PANEL`, `KEY_LINE_TEMPLATES`; `writer_keys(mode, k) -> tuple`; `writer_targets(ctx, plan, k) -> {field: (W1, W2)}`; `title_fallback(action)`; `clean_writer(lib, text, pasted=()) -> str`; `empty_parts(mode, k, plan) -> dict`; `parse_panel_reply(ctx, plan, k, answer) -> dict|None`; `panel_fields(ctx, plan, parts, k) -> [(Label, text)]`; `assemble(ctx, plan, parts) -> str`; `_norm_text`, `_first`, `_valid_phrases`; `_field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared) -> (hard, advisory)`; `repeat_advisories(ctx, lib, plan, writers_by_panel) -> [str]`; `plan_copied_examples(plan) -> [str]`; `GENERATION_CHECKS`; `panel_checks(ctx, plan, parts, text, story_md_path) -> (hard, advisory)`; `_order_by_panel(lines)`; `build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules="") -> str`; `unparseable_panel_problem(mode, k) -> str`. In `seu`: `IMAGE_SENTENCES`, `MOTION_SENTENCES`, `PROMPT_SENTENCES`, `SHOTS_MOTION`, `NARRATIONS`, `_words_from(sentences, phrase, start, count)`, `panel_json(mode, k, phrase="the courier", words=None)`, `critic_json(scores=(8, 8, 8), verdict="ok", patches=())`. In the test module: `ltx_movie` (bin/ltx-movie loaded as `ltx_movie_for_story_engine`), `DESC30`, `MONK30`, `_norm`, `_story(ws, mode, n, plan_mut=None, part_mut=None, ctx_kw=None) -> (ctx, plan, parts, text, path)`, `_story_checks(ws, mode, n=3, **kw)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst12_lexicons`, `test_rst16_panel_prompt`, `test_rst17_cleanup_and_title_fallback`, `test_rst18_assembly_goldens`, `test_rst19_cast_shots_story_has_no_s9_or_s12`, `test_rst20_panel_checks`, `test_rst21_shots_rules_are_appended_unchanged`, `test_rst56_n15_undeclared_character_in_panels`, `test_rst57_reserved_line_in_the_panel_prompt`.

**1.1.** Append to `tests/story_engine_testutil.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- panel and critic builders (spec 5.2) ------------------------------------------------------

IMAGE_SENTENCES = (
    "{P} stands on the left of the frame and faces right toward the water.",
    "Rain streaks across the scene in thin silver lines.",
    "Puddles reflect the glow of shop signs along the quay.",
    "Fishing boats rock gently at their moorings in the background.",
    "The palette is cool blue and slate with warm amber accents.",
    "The viewpoint is at eye level from across the road.",
    "The image is a photorealistic film still with soft contrast.",
    "Gulls circle low over the harbour wall.",
)
MOTION_SENTENCES = (
    "{P} pedals steadily along the wet road toward the far end of the quay.",
    "{P} leans into the bend and the wheels splash through a shallow puddle.",
    "{P} glances over one shoulder at the boats rocking behind.",
    "{P} grips the handlebars more tightly against a gust of wind.",
    "{P} rises from the saddle to climb the gentle slope ahead.",
    "{P} slows down beside a stack of wooden crates near the water.",
    "{P} pushes off from the kerb with one foot to gather speed.",
    "{P} ducks under a dripping awning at the corner of the street.",
)
PROMPT_SENTENCES = (
    "{P} pedals a bicycle along the wet harbour road as rain drums on the cobblestones.",
    "Initially the tyres hiss through shallow puddles beside the moored boats.",
    "As the road bends a gust rattles the shutters of the closed shops.",
    "A moment later gulls cry overhead and a halyard clinks against a mast.",
    "Then {P} rises from the saddle to climb the gentle slope.",
    "The viewpoint follows from the side at eye level.",
    "Cool blue light falls across the wet stones and the amber shop signs.",
    "Water splashes up from the front wheel with a soft slap.",
    "Behind the bicycle the harbour water ripples under the falling rain.",
    "The chain clicks steadily as the pedals turn.",
    "{P} swings around a parked handcart loaded with nets.",
    "A dog barks once from a doorway as the bicycle passes.",
    "Steam drifts from a noodle stall where a radio hums softly.",
    "The front brake squeals briefly at the bottom of the hill.",
    "Initially the lane narrows between tall timber houses.",
    "{P} stands on the pedals and the frame creaks under the effort.",
    "Rainwater gurgles down a gutter beside the stone steps.",
    "A moment later a shutter bangs open above the street.",
    "The viewpoint drops low as the wheel rolls past a lantern.",
    "Thunder rumbles far away over the grey hills.",
)
SHOTS_MOTION = ("{P} turns slowly toward the harbour wall on the right.",
                "{P} lifts the sealed letter close to the chest.",
                "{P} steps forward onto the wet stones.",
                "{P} raises one hand against the falling rain.")
NARRATIONS = ("The rain had not stopped since dawn.", "Every street led down to the water.",
              "He knew the letter could not wait.", "The temple bell was still silent.",
              "Nobody else was out in the storm.", "The gate stood open at the top.",
              "His legs burned on the last climb.", "Someone was waiting for this letter.")


def _words_from(sentences, phrase, start, count):
    """Whole sentences (cycled from start) until there are at least count words, {P} -> phrase;
    the first letter of each sentence is capitalised."""
    words = []
    i = start
    while len(words) < count:
        sentence = sentences[i % len(sentences)].replace("{P}", phrase)
        words += (sentence[:1].upper() + sentence[1:]).split()
        i += 1
    return " ".join(words)


def panel_json(mode, k, phrase="the courier", words=None):
    """A valid panel-writer reply for panel k (Section 2.3 keys) whose writer texts land inside
    the RS14 writer targets of plan_json's plan. words maps a key to a minimum word count."""
    words = dict(words or {})
    reply = {"title": "Harbour Road Part %d" % k}
    if mode == "chained":
        if k == 1:
            reply["image"] = _words_from(IMAGE_SENTENCES, phrase, 0, words.get("image", 90))
            reply["motion"] = _words_from(MOTION_SENTENCES, phrase, 0, words.get("motion", 25))
        else:
            reply["motion"] = _words_from(MOTION_SENTENCES, phrase, 2 * k - 1,
                                          words.get("motion", 20))
    elif mode == "no_stills":
        reply["prompt"] = _words_from(PROMPT_SENTENCES, phrase, 5 * (k - 1),
                                     words.get("prompt", 110))
    else:
        reply["image"] = _words_from(IMAGE_SENTENCES, phrase, k - 1, words.get("image", 50))
        motion = SHOTS_MOTION[(k - 1) % len(SHOTS_MOTION)].replace("{P}", phrase)
        reply["motion"] = motion[:1].upper() + motion[1:]
    reply["narration"] = NARRATIONS[(k - 1) % len(NARRATIONS)]
    return reply


def critic_json(scores=(8, 8, 8), verdict="ok", patches=()):
    """A critic reply (Section 2.4)."""
    return {"scores": dict(zip(("continuity", "story", "renderability"), scores)),
            "verdict": verdict, "patches": list(patches)}
```

**1.2.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST12, RST16-RST21, RST56, RST57: panels (RS12-RS16, RS37) -----------------------------

ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_story_engine", os.path.join(WS, "bin", "ltx-movie")).load_module()
DESC30 = ("a young man with short brown hair and a lean build wearing a yellow rain jacket with "
          "a hood over grey trousers and black boots and a canvas satchel strapped")
MONK30 = ("an old man with a shaved head and a calm lined face wearing a saffron robe and wooden "
          "sandals with a string of prayer beads looped twice around his wrist")


def _norm(text):
    return " ".join(text.split())


def test_rst12_lexicons():
    templates = _norm(ltx_movie.STORY_PROMPT_TEMPLATE + " " + ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS
                      + " " + ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS)
    for example in se.COPIED_EXAMPLES:
        assert _norm(example) in templates, example
    for word in ("short", "light", "ring", "cap", "fair"):
        assert word not in se.APPEARANCE_WORDS
    assert {"grey", "kimono", "camera", "close-up", "palette"} <= se.APPEARANCE_WORDS


def _story(ws, mode, n, plan_mut=None, part_mut=None, ctx_kw=None):
    """(ctx, plan, parts, text, path) for plan_json/panel_json with the mutations applied."""
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **(ctx_kw or {}))
    raw = seu.plan_json(mode, n)
    if plan_mut:
        plan_mut(raw)
    plan, _ = se.normalize_plan(ctx, raw)
    phrase = plan["cast"][0]["phrase"]
    parts = [se.parse_panel_reply(ctx, plan, k, json.dumps(seu.panel_json(mode, k, phrase)))
             for k in range(1, n + 1)]
    if part_mut:
        part_mut(parts)
    text = se.assemble(ctx, plan, parts)
    path = os.path.join(ctx.story_dir, "check.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return ctx, plan, parts, text, path


def _story_checks(ws, mode, n=3, **kw):
    ctx, plan, parts, text, path = _story(ws, mode, n, **kw)
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    return hard + advisory


def test_rst16_panel_prompt(ws):
    def fixture(raw):
        raw["cast"][0]["descriptor"] = DESC30
        raw["cast"][1]["descriptor"] = MONK30
        raw["beats"][0]["cast"] = ["c1", "c2"]

    rules = ltx_movie.STORY_PROMPT_TEMPLATE_NO_STILLS
    rules = rules[rules.index("Rules:\n") + len("Rules:\n"):rules.index("\n\nNarrative to adapt:")]
    rules = "\n".join(line.strip() for line in rules.split("\n"))
    expected = {
        ("chained", 1): ["image: 27 to 77 words describing the opening frame",
                         "motion: 21 to 46 words in one or two plain sentences: what the characters "
                         "physically do during these 6 seconds. Name"],
        ("chained", 2): ["motion: 15 to 35 words in one or two plain sentences: what the characters "
                         "physically do during these 6 seconds, continuing"],
        ("no_stills", 1): ["prompt: 53 to 123 words in the present tense"],
        ("shots", 1): ["image: 20 to 77 words describing this shot's first frame",
                       "motion: ONE sentence of 6 to 21 words naming ONE character"],
        ("shots", 2): ["motion: ONE sentence of 5 to 19 words naming ONE character"],
    }
    for (mode, k), lines in expected.items():
        ctx, plan, parts, _text, _path = _story(ws, mode, 3, plan_mut=fixture,
                                                ctx_kw={"seed_agent_image": "/s/seed.png"}
                                                if mode == "chained" else None)
        prompt = se.build_panel_prompt(ctx, plan, parts, k, no_stills_rules=rules)
        assert prompt.startswith('You are writing panel %d of 3 of a short narrated movie '
                                 '(story-id "s1").\n' % k)
        assert prompt.endswith(se.NO_TOOL_SENTENCE)
        assert "{" not in prompt and "}" not in prompt and "@@" not in prompt
        for line in lines:
            assert "\n" + line in prompt, (mode, k, line)
        assert "\ntitle: a short title for the panel, 2 to 6 words.\n" in prompt
        assert prompt.count("\nnarration: one sentence of voice-over narration, 3 to 30 words.\n") == 1
        assert ("The previous panel's Motion: " in prompt) == (mode == "chained" and k >= 2)
        assert ("It IS this movie's first frame" in prompt) == (mode == "chained" and k == 1)
        assert ("\nRules:\n" + rules + "\n\n" in prompt) == (mode == "no_stills")
        assert ("Rules for this shot: two people never touch" in prompt) == (mode == "shots")
        assert (">> %d. (%s) " % (k, plan["beats"][k - 1]["arc"])) in prompt
        if k == 1:
            assert 'referring phrases: "the courier"; "the old monk"\n' in prompt
    assert len(rules.split("\n")) == 4
    ctx, plan, parts, _text, _path = _story(ws, "chained", 3)
    prompt = se.build_panel_prompt(ctx, plan, parts, 2)
    previous = dict(se.panel_fields(ctx, plan, parts, 1))["Motion"]
    assert ('referring phrases: "the courier"\nThe previous panel\'s Motion: ' + previous
            + "\n\nWrite this panel as one JSON object") in prompt
    fixed = se.build_panel_prompt(ctx, plan, parts, 2, fix=["panel 2: N3 appearance: x",
                                                            "panel 2: N12 one action: y"])
    assert ("\n\nYour previous version of this panel was rejected. Problems:\n- panel 2: N3 "
            "appearance: x\n- panel 2: N12 one action: y\nPrevious version:\ntitle: "
            + parts[1]["title"] + "\nmotion: " + parts[1]["motion"] + "\nnarration: "
            + parts[1]["narration"] + "\n\nReply with the JSON object only") in fixed
    assert se.unparseable_panel_problem("chained", 2) == (
        "the reply is not one JSON object with the keys title, motion, narration")


def test_rst17_cleanup_and_title_fallback(ws):
    ctx, plan, parts, _t, _p = _story(ws, "shots", 3)
    lib = se._character_lib(WS)
    pasted = se.pasted_pieces(ctx, plan, 1)["image"]
    raw = ('Image:  "The courier stands left.\nThe setting is a RAINY harbour town in modern '
           'Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. '
           'Gulls circle.  The shot is a medium shot."')
    assert se.clean_writer(lib, raw, pasted) == "The courier stands left. Gulls circle."
    assert se.clean_writer(lib, "“motion: x y”") == "motion: x y"
    assert se.clean_writer(lib, "MOTION : The courier turns. The camera stays static.",
                           se.pasted_pieces(ctx, plan, 1)["motion"]) == "The courier turns."
    assert se.clean_writer(lib, None) == ""
    reply = dict(seu.panel_json("shots", 1), title="one two three four five six seven")
    assert se.parse_panel_reply(ctx, plan, 1, json.dumps(reply))["title"] == "the courier pedals a bicycle"
    plan["beats"][0]["action"] = "the courier's (wet) bike: rolls, slowly away"
    assert se.title_fallback(plan["beats"][0]["action"]) == "the courier's wet bike rolls"
    for bad in ("not json", json.dumps(dict(seu.panel_json("shots", 1), motion="  ")),
                json.dumps({"title": "x", "image": "a b"})):
        assert se.parse_panel_reply(ctx, plan, 1, bad) is None


GOLDEN_CHAINED = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Panel 1 — Wet Road
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier waits on the left. The shot is a medium shot.
Motion: The courier pushes off. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Motion: The courier leans into the bend.
Narration: Every street led down to the water.
"""
GOLDEN_NO_STILLS = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Panel 1 — Wet Road
Prompt: The courier pedals through the rain. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The shot is a medium shot. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Prompt: The courier leans into the bend. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The shot is a wide shot. The camera tracks alongside the movement.
Narration: Every street led down to the water.
"""
GOLDEN_SHOTS = """# The Sealed Letter

A courier carries a sealed letter through a rainy harbour town and delivers it at the temple gate.

## Characters
- "the courier": a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers.
- "the old monk": an old man with a shaved head and a calm face wearing a saffron robe and wooden sandals.

## Panel 1 — Wet Road
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier waits on the left. The shot is a medium shot.
Motion: The courier pushes off. The camera stays static.
Narration: The rain had not stopped.

## Panel 2 — The Bend
Image: The setting is a rainy harbour town in modern Japan, wet cobblestones underfoot, fishing boats behind, under grey afternoon light. The courier is a young man with short brown hair and a lean build wearing a yellow rain jacket and grey trousers. The courier leans right. The shot is a wide shot.
Motion: The courier leans into the bend. The camera tracks alongside the movement.
Narration: Every street led down to the water.
"""


def test_rst18_assembly_goldens(ws):
    writer = {
        "chained": [{"title": "Wet Road", "image": "The courier waits on the left",
                     "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                    {"title": "The Bend", "motion": "The courier leans into the bend.",
                     "narration": "Every street led down to the water."}],
        "no_stills": [{"title": "Wet Road", "prompt": "The courier pedals through the rain",
                       "narration": "The rain had not stopped"},
                      {"title": "The Bend", "prompt": "The courier leans into the bend.",
                       "narration": "Every street led down to the water."}],
        "shots": [{"title": "Wet Road", "image": "The courier waits on the left",
                   "motion": "The courier pushes off", "narration": "The rain had not stopped"},
                  {"title": "The Bend", "image": "The courier leans right.",
                   "motion": "The courier leans into the bend.",
                   "narration": "Every street led down to the water."}],
    }
    goldens = {"chained": GOLDEN_CHAINED, "no_stills": GOLDEN_NO_STILLS, "shots": GOLDEN_SHOTS}
    manifest = se._story_manifest(WS)
    lib = se._character_lib(WS)
    for mode, golden in goldens.items():
        ctx = seu.make_ctx(se, ws, mode=mode, panels=2)
        plan, _ = se.normalize_plan(ctx, seu.plan_json(mode, 2))
        text = se.assemble(ctx, plan, writer[mode])
        assert text == golden, mode
        path = os.path.join(ctx.story_dir, "golden.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        panels = manifest._parse_prompts_md(path)[1]
        assert [p["number"] for p in panels] == [1, 2]
        assert [p["title"] for p in panels] == ["Wet Road", "The Bend"]
        assert [bool(p["image"]) for p in panels] == {"chained": [True, False],
                                                      "no_stills": [False, False],
                                                      "shots": [True, True]}[mode]
        assert all(bool(p["prompt"]) == (mode == "no_stills") for p in panels)
        assert all(bool(p["motion"]) == (mode != "no_stills") for p in panels)
        if mode == "shots":
            assert lib.parse_character_roster(text) == ([("the courier", seu.COURIER + "."),
                                                         ("the old monk", seu.MONK + ".")], [])


def test_rst19_cast_shots_story_has_no_s9_or_s12(ws, story_env):
    members = _cast_members(story_env, "kyra", "ronin")
    fixed = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
             {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]

    def cast(raw):
        raw["cast"] = fixed
        raw["beats"][2]["cast"] = ["c2"]

    ctx, plan, parts, text, path = _story(ws, "shots", 4, plan_mut=cast,
                                          ctx_kw={"members": members})
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert not [h for h in hard if " S9 " in h or " S12 " in h]
    assert "The woman in grey is %s." % seu.DESC_K in text


def test_rst20_panel_checks(ws):
    for mode in ("chained", "no_stills", "shots"):
        assert _story_checks(ws, mode) == [], mode

    def part(k, **changes):
        return lambda parts: parts[k - 1].update(changes)

    forty = " ".join(["The courier pedals onward"] * 10)
    cases = [
        ("chained", {"part_mut": part(2, motion=forty)},
         ["panel 2: N1 word count: Motion: is 40 words; it must be 15-35"]),
        ("chained", {"part_mut": part(2, motion="The courier waves at the woman beside the crates "
                                                "and keeps pedalling forward in the rain.")},
         ["panel 2: N2 referring phrase: Motion: names 'woman' outside every referring phrase; "
          "name each character by their exact phrase"]),
        ("chained", {"part_mut": part(2, motion="The courier pulls the grey hood tighter and "
                                                "pedals forward along the road past the boats.")},
         ["panel 2: N3 appearance: Motion: says 'grey'; panels after the first never re-describe "
          "appearance, clothing, setting, lighting, colour, style or camera"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals past the old monk beside the "
                                                "crates and on toward the end of the quay.")},
         ["panel 2: N4 stray cast: Motion: names 'the old monk', who is not in beat 2's cast"]),
        ("chained", {"part_mut": lambda parts: parts[0].update(
            image=parts[0]["image"][:300] + " " + seu.TEMPLE)},
         ["panel 1: N5 setting sentence: Image: contains l2's setting sentence; beat 1 is at l1"]),
        ("no_stills", {"part_mut": part(2, prompt=seu.panel_json("no_stills", 2)["prompt"]
                                        + " A fisherman shouts across the water.")},
         ["panel 2: N7 dialogue and text: Prompt: says 'shouts'"]),
        ("chained", {"part_mut": part(3, motion='The courier reads the "urgent" note and pedals on '
                                                "toward the end of the quay.")},
         ["panel 3: N7 dialogue and text: Motion: contains a double quote"]),
        ("shots", {"part_mut": part(2, image=seu.panel_json("shots", 2)["image"]
                                    + " A caption fills the lower edge.")},
         ["panel 2: N7 dialogue and text: Image: says 'caption'"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals toward a noise off-screen at "
                                                "the far end of the long quay.")},
         ["panel 2: N8 off-screen: Motion: says 'off-screen'; describe only what is in the frame"]),
        ("chained", {"part_mut": part(2, motion="The courier pedals hard and we cut to the far end "
                                                "of the quay at once.")},
         ["panel 2: N9 cut wording: Motion: says 'cut to'; one panel is one continuous shot"]),
        ("chained", {"part_mut": part(1, narration="<one sentence of voice-over narration>")},
         ["panel 1: N10 copied example: Narration: contains template text '<one sentence of "
          "voice-over narration>'"]),
        ("chained", {"plan_mut": lambda raw: raw["locations"][1].update(
            setting=se.COPIED_EXAMPLES[0] + ".")},
         ["plan: N10 copied example: l2's setting contains template text '%s'"
          % se.COPIED_EXAMPLES[0]]),
        ("chained", {"part_mut": part(2, narration="")},
         ["panel 2: N11 narration: Narration: is empty"]),
        ("chained", {"part_mut": part(2, motion="The courier stops at the crates then pedals "
                                                "forward along the wet road past the boats.")},
         ["panel 2: N12 one action: Motion: chains actions with 'then'"]),
        ("chained", {"part_mut": lambda parts: parts[2].update(motion=parts[1]["motion"])},
         ["panel 3: N13 repeat: Motion: repeats panel 2's action (similarity 1.00)"]),
        ("chained", {"part_mut": part(2, narration="It rained. It poured.")},
         ["panel 2: N14 narration form: Narration: is 2 sentences; it should be one sentence of "
          "3-30 words"]),
        ("chained", {"part_mut": part(2, narration="Rain")},
         ["panel 2: N14 narration form: Narration: is 1 words; it should be one sentence of 3-30 "
          "words"]),
    ]
    for mode, kw, expected in cases:
        assert _story_checks(ws, mode, **kw) == expected, expected
    shots_long = _story_checks(ws, "shots", part_mut=part(2, motion=forty))
    assert not [v for v in shots_long if " N1 " in v]
    assert [v for v in shots_long if " S4 " in v] == [
        "panel 2: S4 motion length: Motion: is 46 words; it must be 10-25"]
    offscreen = _story_checks(ws, "shots", part_mut=part(2, motion="The courier turns toward "
                                                                   "a noise off-screen."))
    assert offscreen == ["panel 2: S11 off-screen wording: Motion: says 'off-screen'; use left "
                         "and right screen direction instead"]
    ctx, plan, parts, _text, _path = _story(ws, "chained", 3)
    lib = se._character_lib(WS)
    fields = [("Image", "The courier stands."), ("Motion", "x"), ("Narration", "y")]
    assert se._field_checks(ctx, lib, plan, 1, "T", fields, {}, ("N5", "N6"), []) == (
        ["panel 1: N5 setting sentence: Image: lacks l1's setting sentence word for word",
         "panel 1: N6 description: Image: lacks c1's description word for word"], [])
    shots_ctx = ctx._replace(mode="shots")
    plan["cast"][0]["cast_name"] = "kyra"
    assert se._field_checks(shots_ctx, lib, plan, 1, "T", fields, {}, ("N6",), []) == ([], [])


def test_rst21_shots_rules_are_appended_unchanged(ws):
    def contact(raw):
        raw["beats"][1]["cast"] = ["c1", "c2"]

    checks = _story_checks(ws, "shots", plan_mut=contact, part_mut=lambda parts: parts[1].update(
        motion="The courier strikes the old monk with a heavy staff."))
    assert checks == ["panel 2: S8 contact: Motion: 'strikes' acts on 'the old monk'; two people "
                      "touching on screen"]


def test_rst56_n15_undeclared_character_in_panels(ws, story_env):
    seu.ronin(story_env["lib"])

    def refer(parts):
        parts[0]["title"] = "roninmn Arrives"
        parts[1]["motion"] = "The ronin raises one hand against the falling rain."
        parts[2]["narration"] = "Ronin had waited all day."

    checks = _story_checks(ws, "shots", part_mut=refer)
    tail = "; library characters appear only when declared with --character ronin"
    assert checks == [
        "panel 1: N15 undeclared character: Title: names library character ronin by its trigger "
        "'roninmn'" + tail,
        "panel 2: N15 undeclared character: Motion: names library character ronin by its "
        "referring phrase 'The ronin'" + tail,
        "panel 3: N15 undeclared character: Narration: names library character ronin by its name "
        "'Ronin'" + tail]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    fixed = [{"id": "c1", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    declared = _story_checks(ws, "shots", plan_mut=lambda raw: raw.update(cast=fixed),
                             ctx_kw={"members": members})
    assert not [v for v in declared if " N15 " in v]


def test_rst57_reserved_line_in_the_panel_prompt(ws, story_env):
    seu.ronin(story_env["lib"])
    ctx, plan, parts, _t, _p = _story(ws, "chained", 3)
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert ('referring phrases: "the courier"\nCharacters who are not in this movie, never to be '
            'named: ronin ("the ronin").\n\nAn image') not in prompt
    assert ('referring phrases: "the courier"\nCharacters who are not in this movie, never to be '
            'named: ronin ("the ronin").\n\nWrite this panel') in prompt
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    declared = ctx._replace(members=members)
    assert "never to be named" not in se.build_panel_prompt(declared, plan, parts, 1)
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
9 failed, 15 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst12_lexicons
FAILED tests/test_story_engine.py::test_rst16_panel_prompt
FAILED tests/test_story_engine.py::test_rst17_cleanup_and_title_fallback
FAILED tests/test_story_engine.py::test_rst18_assembly_goldens
FAILED tests/test_story_engine.py::test_rst19_cast_shots_story_has_no_s9_or_s12
FAILED tests/test_story_engine.py::test_rst20_panel_checks
FAILED tests/test_story_engine.py::test_rst21_shots_rules_are_appended_unchanged
FAILED tests/test_story_engine.py::test_rst56_n15_undeclared_character_in_panels
FAILED tests/test_story_engine.py::test_rst57_reserved_line_in_the_panel_prompt
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# Panels: lexicons (RS16), the panel prompt (RS12), writer parts and cleanup (RS13),
# assembly (RS14), panel checks (RS15) and the undeclared-character check N15 (RS37)
# ---------------------------------------------------------------------------

APPEARANCE_WORDS = frozenset("""
    red orange yellow green blue purple violet pink brown black white grey gray silver gold golden
    crimson scarlet navy beige auburn blonde blond brunette ginger
    hair haired ponytail braid braided curls curly bald beard bearded moustache mustache stubble
    freckled wrinkled complexion
    wearing wears dressed dress shirt jacket coat cloak kimono robe hood hat helmet trousers pants
    jeans skirt boots shoes sandals gloves scarf belt armor armour uniform tunic vest apron glasses
    spectacles earrings necklace bracelet
    slender stocky muscular skinny plump pale tanned
    lighting lit sunlight moonlight palette colour color cinematic photorealistic rendered style
    camera lens zoom zooms dolly framing close-up""".split())
_APPEARANCE_RE = re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % "|".join(
    re.escape(w) for w in sorted(APPEARANCE_WORDS, key=lambda w: (-len(w), w))), re.IGNORECASE)
DIALOGUE_RE = re.compile(
    r"\b(?:say|says|said|saying|shout|shouts|shouted|shouting|whisper|whispers|whispered|"
    r"whispering|yell|yells|yelled|yelling|ask|asks|asked|asking|reply|replies|replied|replying|"
    r"tell|tells|told|telling|speak|speaks|spoke|speaking|exclaim|exclaims|exclaimed|mutter|"
    r"mutters|muttered|murmur|murmurs|murmured|call(?:s|ed)?\s+out)\b", re.IGNORECASE)
ONSCREEN_TEXT_RE = re.compile(
    r"\b(?:captions?|subtitles?|title\s+cards?|on-screen\s+text|text\s+reading|that\s+reads|"
    r"which\s+reads|lettering|inscription|written\s+words)\b", re.IGNORECASE)
CUT_RE = re.compile(
    r"\b(?:cuts?\s+to|smash\s+cut|jump\s+cut|fades?\s+(?:in|out|to)|dissolves?\s+to|flashback|"
    r"hours\s+later|the\s+next\s+(?:day|morning))\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"<[^<>]{1,80}>")
COPIED_EXAMPLES = (
    "The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the "
    "ground covered in leaf litter, under flat overcast grey light",
    "walking to a door, opening it, stepping through, and closing it behind them",
    "raising the blade, drawing back the arm, lunging forward",
    "recoiling, staggering, clutching the wound, falling",
    "her eyebrows angle down and her lips press together",
    "a charge, a draw and a strike",
)
_LABEL_RE = re.compile(r"^(?:title|image|motion|prompt|narration)\s*:\s*", re.IGNORECASE)
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))
_TITLE_CHARS_RE = re.compile(r"[^A-Za-z0-9 '-]")
LABELS = {"image": "Image", "motion": "Motion", "prompt": "Prompt", "narration": "Narration"}

PANEL_PROMPT_TEMPLATE = (
    'You are writing panel @@K@@ of @@PANELS@@ of a short narrated movie (story-id '
    '"@@STORY_ID@@").\n'
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "@@PANEL_RULES@@The beats of the whole movie, one per panel (this panel is marked >>):\n"
    "@@BEAT_LINES@@\n"
    "\n"
    "This panel's beat: @@ACTION@@\n"
    "Characters on screen in this panel, named only by these exact referring phrases: "
    "@@CAST_PHRASES@@\n"
    "@@RESERVED@@@@PREVIOUS@@\n"
    "@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:\n"
    "\n"
    "@@KEY_LINES@@\n"
    "\n"
    "@@FIX_BLOCK@@" + NO_TOOL_SENTENCE)
SHOTS_PANEL_RULES = ("Rules for this shot: two people never touch on screen, nothing outside the "
                     "frame is ever mentioned, and who faces whom is shown with fixed left and "
                     "right screen direction.\n\n")
SEED_PANEL = ("An image is attached to this message. It IS this movie's first frame: describe in "
              "image exactly what it shows -- each person's pose and place in the frame, the "
              "background, the lighting, the colour palette and the visual style -- and start "
              "motion from that exact pose.\n\n")
KEY_LINE_TEMPLATES = {
    "title": "title: a short title for the panel, 2 to 6 words.",
    "chained_image": (
        "image: W1 to W2 words describing the opening frame as one still picture: where each "
        "character stands and which way they face, the background, the lighting and colour "
        "palette, the camera viewpoint and the rendering style. Do not describe any character's "
        "appearance or clothing, do not write a sentence about the place itself and do not name "
        "the shot type: the pipeline adds each character's description, the place's setting "
        "sentence and the shot type to this field itself."),
    "chained_motion1": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds. Name each character only by their referring phrase, "
        "word for word. Describe ONE continuous physical motion, not a sequence of separate "
        "steps. Do not mention the camera: the pipeline adds the camera sentence."),
    "chained_motion": (
        "motion: W1 to W2 words in one or two plain sentences: what the characters physically do "
        "during these @@SECONDS@@ seconds, continuing from where the previous panel left them. "
        "Name each character only by their referring phrase, word for word. Describe ONE "
        "continuous physical motion, not a sequence of separate steps: @@SECONDS@@ seconds is "
        "enough for a single gesture, a few footsteps or the start of a movement. Do not describe "
        "appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is "
        "already on screen."),
    "no_stills_prompt": (
        "prompt: W1 to W2 words in the present tense: one flowing paragraph in strict "
        "chronological order that opens with the main action, carries enough separate beats to "
        "fill the full @@SECONDS@@ seconds, links them with temporal connectors (initially, as, "
        "then, while, a moment later), names the ambient and environmental sounds alongside the "
        "actions that make them, and states the camera viewpoint and the lighting and colour. "
        "Name each character only by their referring phrase. Do not describe any character's "
        "appearance or clothing, do not write a sentence about the place itself and do not name "
        "the shot type or the camera motion: the pipeline adds each character's description, the "
        "place's setting sentence, the shot type and the camera motion itself. Describe only what "
        "is physically observable, with no mood words, no spoken dialogue and no markdown."),
    "shots_image": (
        "image: W1 to W2 words describing this shot's first frame as one still picture: where "
        "each character stands and which way they face, using fixed left and right screen "
        "direction; the background; the lighting and colour palette; the camera viewpoint; and "
        "the rendering style. Do not describe any character's appearance or clothing, do not "
        "write a sentence about the place itself and do not name the shot type: the pipeline "
        "adds each character's description, the place's setting sentence and the shot type to "
        "this field itself. Never name a person who is not in this shot."),
    "shots_motion": (
        "motion: ONE sentence of W1 to W2 words naming ONE character by their referring phrase "
        "and the ONE physical action they perform during these @@SECONDS@@ seconds. Never chain "
        "actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma "
        "before and, and never use a semicolon. Do not mention the camera: the pipeline adds the "
        "camera sentence."),
    "narration": "narration: one sentence of voice-over narration, 3 to 30 words.",
}


def writer_keys(mode, k):
    """The writer parts of panel k (Section 2.3), in order."""
    if mode == "chained":
        return ("title", "image", "motion", "narration") if k == 1 else (
            "title", "motion", "narration")
    if mode == "no_stills":
        return ("title", "prompt", "narration")
    return ("title", "image", "motion", "narration")


def writer_targets(ctx, plan, k):
    """{field: (W1, W2)} for every writer field with a word range (RS14)."""
    targets = {}
    for field, pasted in pasted_pieces(ctx, plan, k).items():
        spec = field_range(ctx, k, field)
        if spec is None:
            continue
        kind, (lo, hi) = spec
        used = _words(" ".join(p for p in pasted if p))
        w1 = max(MIN_WRITER_WORDS[kind], lo - used)
        targets[field] = (w1, max(w1, hi - used))
    return targets


def title_fallback(action):
    """The first five words of the beat action, letters, digits, spaces, ' and - only."""
    return _collapse(_TITLE_CHARS_RE.sub("", " ".join(action.split()[:5])))


def clean_writer(lib, text, pasted=()):
    """RS13 cleanup of one writer string: strip; drop one leading field label and one pair of
    surrounding double quotes; collapse whitespace; blank every case- and whitespace-
    insensitive occurrence of a pasted sentence (character_lib._passage_spans and _blank, each
    span widened over the sentence's own full stop); collapse again."""
    if not isinstance(text, str):
        return ""
    text = _LABEL_RE.sub("", text.strip(), count=1).strip()
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1]
            break
    text = _collapse(text)
    pasted = [p for p in pasted if p]
    if pasted:
        spans = [(s, e + 1 if text[e:e + 1] == "." else e)
                 for s, e in lib._passage_spans(text, pasted)]
        text = _collapse(lib._blank(text, spans))
    return text


def empty_parts(mode, k, plan):
    parts = {key: "" for key in writer_keys(mode, k)}
    parts["title"] = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return parts


def parse_panel_reply(ctx, plan, k, answer):
    """The cleaned writer parts of panel k from a reply, or None when the reply is not valid
    (RS13): every non-title key must hold a string that is non-empty after cleanup."""
    obj = extract_json(answer)
    if obj is None:
        return None
    lib = _character_lib(ctx.ws)
    pasted = pasted_pieces(ctx, plan, k)
    parts = {}
    for key in writer_keys(ctx.mode, k):
        if key == "title":
            continue
        value = clean_writer(lib, obj.get(key), pasted.get(key, ()))
        if not value:
            return None
        parts[key] = value
    title = clean_writer(lib, obj.get("title"))
    if not title or _words(title) > 6:
        title = title_fallback(plan["beats"][k - 1]["action"]) or "Panel %d" % k
    return dict({"title": title}, **parts)


def panel_fields(ctx, plan, parts, k):
    """[(Label, assembled text)] of panel k in file order (RS14)."""
    p = parts[k - 1]
    pasted = pasted_pieces(ctx, plan, k)

    def join(pieces):
        return " ".join(_sentence(piece) for piece in pieces if piece and piece.strip())

    fields = []
    if (ctx.mode == "chained" and k == 1) or ctx.mode == "shots":
        image = pasted["image"]
        fields.append(("Image", join(image[:-1] + [p.get("image", "")] + image[-1:])))
    if ctx.mode == "no_stills":
        fields.append(("Prompt", join([p.get("prompt", "")] + pasted["prompt"])))
    else:
        fields.append(("Motion", join([p.get("motion", "")] + pasted["motion"])))
    fields.append(("Narration", _sentence(p.get("narration", ""))))
    return fields


def assemble(ctx, plan, parts):
    """The story.md text of a plan and its writer parts (RS14)."""
    lines = ["# " + plan["title"], "", plan["logline"], ""]
    if ctx.mode == "shots":
        lines.append("## Characters")
        lines += ['- "%s": %s.' % (c["phrase"], c["descriptor"]) for c in plan["cast"]]
        lines.append("")
    for k in range(1, len(parts) + 1):
        lines.append("## Panel %d — %s" % (k, parts[k - 1]["title"]))
        lines += ["%s: %s" % (label, text) for label, text in panel_fields(ctx, plan, parts, k)]
        lines.append("")
    return "\n".join(lines[:-1]) + "\n"


def _norm_text(text):
    return " ".join(text.lower().split()).rstrip(".")


def _first(regex, text):
    match = regex.search(text)
    return " ".join(match.group(0).lower().split()) if match else None


def _valid_phrases(lib, plan):
    phrases = {}
    for c in plan["cast"]:
        try:
            phrases[lib.normalize_phrase(c["phrase"])] = c["id"]
        except lib.CharacterError:
            continue
    return phrases


def _field_checks(ctx, lib, plan, k, title, fields, writers, ids, undeclared):
    """(hard, advisory) of one panel: the RS15 checks named in ids, plus N15 when in ids.
    fields: [(Label, assembled text)]; writers: {Label: writer text}; plan may be None (then
    every check that needs the plan is skipped)."""
    hard, advisory = [], []
    beat = plan["beats"][k - 1] if plan and k <= len(plan["beats"]) else None
    phrases = _valid_phrases(lib, plan) if plan else {}
    by_cast = {c["id"]: c for c in plan["cast"]} if plan else {}
    by_location = {l["id"]: l for l in plan["locations"]} if plan else {}
    prefix = "panel %d:" % k

    def add(target, check, name, label, detail):
        target.append("%s %s %s: %s: %s" % (prefix, check, name, label, detail))

    action_fields = ("Image", "Motion", "Prompt")
    for label, text in fields:
        writer = writers.get(label, "")
        key = label.lower()
        if "N1" in ids and label != "Narration" and not (ctx.mode == "shots" and label == "Motion"):
            spec = field_range(ctx, k, key)
            if spec:
                lo, hi = spec[1]
                if not lo <= _words(text) <= hi:
                    add(hard, "N1", "word count", label,
                        "is %d words; it must be %d-%d" % (_words(text), lo, hi))
        if ctx.mode == "chained" and k >= 2 and label == "Motion" and plan:
            humans = [p for p in phrases if not lib.is_animal_phrase(p)]
            animals = [p for p in phrases if lib.is_animal_phrase(p)]
            if "N2" in ids:
                for sentence in lib._SENTENCE_SPLIT_RE.split(text.strip()):
                    refs = [r for r in lib._person_refs(sentence, humans, animals, [])
                            if r[2] in lib.SHOTS_PERSON_NOUNS]
                    if refs:
                        add(hard, "N2", "referring phrase", label,
                            "names %s outside every referring phrase; name each character by "
                            "their exact phrase" % _q(refs[0][2]))
                        break
            if "N3" in ids:
                blanked = lib._blank(text, lib._passage_spans(
                    text, list(phrases) + [p["name"] for p in plan["props"] if p["name"]]))
                word = _first(_APPEARANCE_RE, blanked)
                if word:
                    add(hard, "N3", "appearance", label,
                        "says %s; panels after the first never re-describe appearance, clothing, "
                        "setting, lighting, colour, style or camera" % _q(word))
        if "N4" in ids and label != "Narration" and beat is not None:
            for phrase in lib.find_phrases(writer, list(phrases)):
                if phrases[phrase] not in beat["cast"]:
                    add(hard, "N4", "stray cast", label,
                        "names %s, who is not in beat %d's cast" % (_q(phrase), k))
                    break
        pasted_field = ((ctx.mode == "chained" and k == 1 and label == "Image")
                        or (ctx.mode == "shots" and label == "Image")
                        or (ctx.mode == "no_stills" and label == "Prompt"))
        if pasted_field and beat is not None:
            norm = _norm_text(text)
            if "N5" in ids and beat["location"] in by_location:
                own = by_location[beat["location"]]
                if _norm_text(own["setting"]) not in norm:
                    add(hard, "N5", "setting sentence", label,
                        "lacks %s's setting sentence word for word" % own["id"])
                else:
                    for other in plan["locations"]:
                        if (other["id"] != own["id"] and other["setting"]
                                and _norm_text(other["setting"]) != _norm_text(own["setting"])
                                and _norm_text(other["setting"]) in norm):
                            add(hard, "N5", "setting sentence", label,
                                "contains %s's setting sentence; beat %d is at %s"
                                % (other["id"], k, own["id"]))
                            break
            if "N6" in ids:
                for cid in beat["cast"]:
                    entry = by_cast.get(cid)
                    if entry is None or (ctx.mode == "shots" and entry["cast_name"]):
                        continue
                    if _norm_text(entry["descriptor"]) not in norm:
                        add(hard, "N6", "description", label,
                            "lacks %s's description word for word" % cid)
                        break
        if label in action_fields:
            if "N7" in ids:
                if any(q in writer for q in ('"', "“", "”")):
                    add(hard, "N7", "dialogue and text", label, "contains a double quote")
                else:
                    word = _first(DIALOGUE_RE, writer) or _first(ONSCREEN_TEXT_RE, writer)
                    if word:
                        add(hard, "N7", "dialogue and text", label, "says %s" % _q(word))
            if "N8" in ids and ctx.mode != "shots":
                word = _first(lib._OFFSCREEN_RE, writer)
                if word:
                    add(hard, "N8", "off-screen", label,
                        "says %s; describe only what is in the frame" % _q(word))
            if "N9" in ids:
                word = _first(CUT_RE, writer)
                if word:
                    add(hard, "N9", "cut wording", label,
                        "says %s; one panel is one continuous shot" % _q(word))
        if "N10" in ids:
            found = PLACEHOLDER_RE.search(writer)
            copied = found.group(0) if found else next(
                (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(writer)), None)
            if copied:
                add(hard, "N10", "copied example", label, "contains template text %s" % _q(copied))
        if "N11" in ids and label == "Narration" and not text.strip():
            hard.append("%s N11 narration: Narration: is empty" % prefix)
    if "N15" in ids and undeclared:
        for label, text in [("Title", title)] + list(fields):
            for hit in undeclared_references(lib, text, undeclared):
                hard.append(undeclared_message("%s N15 undeclared character:" % prefix,
                                               label + ":", hit))
    if "N12" in ids and ctx.mode == "chained":
        writer = writers.get("Motion", "")
        chain = _first(lib._CHAIN_WORD_RE, writer)
        if chain is None and ";" in writer:
            chain = ";"
        if chain is None and lib._COMMA_AND_RE.search(writer):
            chain = ", and"
        if chain:
            add(advisory, "N12", "one action", "Motion", "chains actions with %s" % _q(chain))
    if "N14" in ids:
        narration = dict(fields).get("Narration", "")
        if narration.strip():
            sentences = [s for s in lib._SENTENCE_SPLIT_RE.split(narration.strip()) if s.strip()]
            lo, hi = NARRATION_WORDS
            if len(sentences) != 1:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d sentences; it should be one sentence of %d-%d words"
                    % (len(sentences), lo, hi))
            elif not lo <= _words(narration) <= hi:
                add(advisory, "N14", "narration form", "Narration",
                    "is %d words; it should be one sentence of %d-%d words"
                    % (_words(narration), lo, hi))
    return hard, advisory


def _repeat_words(lib, text, phrase_words):
    return {w.lower() for w in lib._WORD_RE.findall(text) if len(w) >= 3} - phrase_words


def repeat_advisories(ctx, lib, plan, writers_by_panel):
    """N13 for consecutive panels' action writer text (Motion, or Prompt in no_stills)."""
    label = "Prompt" if ctx.mode == "no_stills" else "Motion"
    phrase_words = set()
    for c in plan["cast"] if plan else []:
        phrase_words.update(w.lower() for w in c["phrase"].split())
    out = []
    for k in range(2, len(writers_by_panel) + 1):
        a = _repeat_words(lib, writers_by_panel[k - 2].get(label, ""), phrase_words)
        b = _repeat_words(lib, writers_by_panel[k - 1].get(label, ""), phrase_words)
        if a or b:
            similarity = len(a & b) / float(len(a | b))
            if similarity >= REPEAT_JACCARD:
                out.append("panel %d: N13 repeat: %s: repeats panel %d's action (similarity %.2f)"
                           % (k, label, k - 1, similarity))
    return out


def plan_copied_examples(plan):
    """N10 at plan scope: every descriptor, setting and action of the plan."""
    out = []
    texts = ([("%s's descriptor" % c["id"], c["descriptor"]) for c in plan["cast"]]
             + [("%s's setting" % l["id"], l["setting"]) for l in plan["locations"]]
             + [("beat %d's action" % k, b["action"]) for k, b in enumerate(plan["beats"], 1)])
    for where, text in texts:
        found = PLACEHOLDER_RE.search(text)
        copied = found.group(0) if found else next(
            (ex for ex in COPIED_EXAMPLES if _norm_text(ex) in _norm_text(text)), None)
        if copied:
            out.append("plan: N10 copied example: %s contains template text %s" % (where, _q(copied)))
    return out


GENERATION_CHECKS = ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12",
                     "N14", "N15")


def panel_checks(ctx, plan, parts, text, story_md_path):
    """(hard, advisory) of an assembled story (RS15): plan-scope N10, then per panel N1-N11 and
    N15 (hard) and N12-N14 (advisory), then (shots) character_lib.shots_violations and
    shots_advisories. story_md_path holds text (written by the caller) and is parsed with
    bin/ltx-story-manifest's _parse_prompts_md."""
    lib = _character_lib(ctx.ws)
    undeclared = undeclared_characters(ctx)
    hard, advisory = plan_copied_examples(plan), []
    writers_by_panel = []
    for k in range(1, len(parts) + 1):
        fields = panel_fields(ctx, plan, parts, k)
        writers = {LABELS[key]: parts[k - 1].get(key, "") for key in writer_keys(ctx.mode, k)
                   if key != "title"}
        writers_by_panel.append(writers)
        h, a = _field_checks(ctx, lib, plan, k, parts[k - 1]["title"], fields, writers,
                             GENERATION_CHECKS, undeclared)
        hard += h
        advisory += a
    advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
        panels = _story_manifest(ctx.ws)._parse_prompts_md(story_md_path)[1]
        hard += lib.shots_violations(text, panels, ctx.panels, ctx.members)
        advisory += lib.shots_advisories(panels, ctx.members)
    return hard, advisory


def _order_by_panel(lines):
    """Panel advisories sorted by panel, then N12, N13, N14 (stable)."""
    order = {"N12": 0, "N13": 1, "N14": 2}
    return sorted(lines, key=lambda l: (int(l.split(":", 1)[0].split()[1]),
                                        order.get(l.split()[2], 3)))


def build_panel_prompt(ctx, plan, parts, k, fix=None, no_stills_rules=""):
    """The exact panel prompt of RS12 (plus the RS37 reserved line)."""
    beat = plan["beats"][k - 1]
    by_cast = {c["id"]: c for c in plan["cast"]}
    targets = writer_targets(ctx, plan, k)
    if ctx.mode == "no_stills":
        rules = "Rules:\n" + no_stills_rules + "\n\n" if no_stills_rules else ""
    elif ctx.mode == "shots":
        rules = SHOTS_PANEL_RULES
    else:
        rules = ""
    beat_lines = "\n".join((">> " if b["index"] == k else "   ")
                           + "%d. (%s) %s" % (b["index"], b["arc"], b["action"])
                           for b in plan["beats"])
    phrases = "; ".join('"%s"' % by_cast[c]["phrase"] for c in beat["cast"] if c in by_cast)
    undeclared = undeclared_characters(ctx)
    reserved = ("Characters who are not in this movie, never to be named: "
                + reserved_items(undeclared) + ".\n") if undeclared else ""
    previous = ""
    if ctx.mode == "chained" and k >= 2:
        previous = ("The previous panel's Motion: "
                    + dict(panel_fields(ctx, plan, parts, k - 1))["Motion"] + "\n")
    seed = SEED_PANEL if ctx.mode == "chained" and k == 1 and ctx.seed_agent_image else ""
    key_lines = []
    for key in writer_keys(ctx.mode, k):
        if key == "title" or key == "narration":
            line = KEY_LINE_TEMPLATES[key]
        elif ctx.mode == "chained":
            line = KEY_LINE_TEMPLATES["chained_image" if key == "image" else
                                      "chained_motion1" if k == 1 else "chained_motion"]
        else:
            line = KEY_LINE_TEMPLATES["%s_%s" % (ctx.mode, key)]
        if key in targets:
            line = line.replace("W1", str(targets[key][0]), 1).replace("W2", str(targets[key][1]), 1)
        key_lines.append(line)
    fix_block = ""
    if fix is not None:
        keys = writer_keys(ctx.mode, k)
        current = parts[k - 1] if k <= len(parts) and parts[k - 1] else {}
        fix_block = ("Your previous version of this panel was rejected. Problems:\n"
                     + "\n".join("- " + m for m in fix[:MAX_LISTED])
                     + "\nPrevious version:\n"
                     + "\n".join("%s: %s" % (key, current.get(key, "")) for key in keys)
                     + "\n\n")
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(ctx.goal)),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[ctx.mode]),
        ("@@PANEL_RULES@@", rules),
        ("@@BEAT_LINES@@", beat_lines),
        ("@@ACTION@@", beat["action"]),
        ("@@CAST_PHRASES@@", phrases or "nobody"),
        ("@@RESERVED@@", reserved),
        ("@@PREVIOUS@@", previous),
        ("@@SEED_PANEL@@", seed),
        ("@@KEY_LINES@@", "\n".join(key_lines)),
        ("@@FIX_BLOCK@@", fix_block),
    ]
    scalars = [("@@K@@", str(k)), ("@@PANELS@@", str(ctx.panels)),
               ("@@STORY_ID@@", ctx.story_id), ("@@SECONDS@@", ctx.seconds)]
    return _fill(PANEL_PROMPT_TEMPLATE, fragments, scalars, ctx.narrative)


def unparseable_panel_problem(mode, k):
    return ("the reply is not one JSON object with the keys %s"
            % ", ".join(writer_keys(mode, k)))
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
24 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: panel prompt, cleanup, assembly, panel checks, N15 (story RS3, RS12-RS16, RS37)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 7: The critic: prompt, routing through the fleet or a local one-shot, reply validation

Implements RS17, RS18, RS19 (validation; the retry and code-only round are in Task 9). Tests RST22, RST23, RST24, RST26a.

**Files:**
- Modify: `tests/story_engine_testutil.py`
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Task 4's `run_agent`, `_load_fleet`, `extract_json`; Task 5's `MODE_PARAGRAPHS`, `_goal_paragraph`, `CAMERA_KEYS`; `SHOT_TYPES`, `SCORE_KEYS`.
- Produces: In `se`: `CRITIC_PROMPT_TEMPLATE`, `CRITIC_REPLY_PARAGRAPH`, `JUDGE_REPLY_PARAGRAPH`, `CRITIC_RETRY_SUFFIX`, `ONLY1`; `listed(lines) -> [str]`; `critic_field_lines(mode, catalog_lines) -> str`; `build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False) -> str`; `run_critic(ctx, prompt) -> (status, answer, route)`; `_score(value) -> bool`; `parse_critic(answer) -> dict|None`. In `seu`: `FakeFleet(view, outcomes=(), raise_on_fetch=False)`, `fleet_view(self_serves, peers)`, `ok_envelope(text)`. In the test module: `_critic_ws(tmp_path, monkeypatch, critic=())`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst22_critic_prompt`, `test_rst23_critic_routing`, `test_rst24_real_fleet_lib_with_no_daemon`, `test_rst26a_parse_critic`.

**1.1.** Append to `tests/story_engine_testutil.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- the fake fleet (spec 5.2) ------------------------------------------------------------------

class FakeFleet(object):
    """Stands in for fleet_lib in story_engine.run_critic. view is a fleet view (or None);
    outcomes are the queued (outcome, envelope, detail) results of delegate_once; calls records
    every delegate_once call as (url, skill, task, host_id)."""

    LOCAL = "@local"

    def __init__(self, view, outcomes=(), raise_on_fetch=False):
        self.view = view
        self.outcomes = list(outcomes)
        self.raise_on_fetch = raise_on_fetch
        self.calls = []

    def daemon_url_from_env(self, environ):
        return "http://127.0.0.1:8190", None

    def fetch_view(self, url):
        if self.raise_on_fetch:
            raise OSError("boom")
        return self.view, None

    def route_candidates(self, skill, view):
        def serves(skills):
            return any(s.get("skill") == skill and s.get("verified") is True for s in skills)
        if serves(view["self"]["skills"]):
            return [self.LOCAL]
        return [p["host_id"] for p in view["peers"]
                if p.get("compatible") is True and serves(p["skills"])]

    def delegate_once(self, url, skill, task, host_id):
        self.calls.append((url, skill, task, host_id))
        return self.outcomes.pop(0)


def fleet_view(self_serves, peers):
    """A fleet view: self serves analyst when self_serves; peers are host ids serving it."""
    analyst = [{"skill": "analyst", "verified": True}]
    return {"schema": "qwen-agentd.peers.v1",
            "self": {"host_id": "mac-local", "skills": analyst if self_serves else []},
            "peers": [{"host_id": h, "compatible": True, "skills": analyst} for h in peers]}


def ok_envelope(text):
    return {"schema": "qwen-agent.oneshot.v1", "status": "ok", "answer": text, "error": None,
            "rounds": 1, "tool_calls": 0}
```

**1.2.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

````python
# --- RST22-RST24, RST26 (validation): the critic (RS17-RS19) ---------------------------------

def test_rst22_critic_prompt(ws, tmp_path):
    texts = {}
    for mode in ("chained", "no_stills", "shots"):
        ctx, plan, parts, text, _p = _story(ws, mode, 3)
        prompt = se.build_critic_prompt(plan, text, ([], []))
        texts[mode] = prompt
        assert prompt.startswith('You are the critic for a short narrated movie (story-id "s1").')
        assert "\nThe draft story.md:\n" + text + "\n\nProblems" in prompt
        assert "\nProblems the pipeline's own checks found in this draft (fix the hard ones first):"\
               "\n- none\n" in prompt
        assert '"title": "The Sealed Letter"' in prompt and '"schema"' not in prompt
        assert prompt.endswith(se.CRITIC_REPLY_PARAGRAPH)
        assert "{" in prompt
        assert 'field "lora"' not in prompt
        has = {f: ('field "%s"' % f) in prompt for f in ("image", "motion", "prompt")}
        assert has == {"image": mode != "no_stills", "motion": mode != "no_stills",
                       "prompt": mode == "no_stills"}, mode
        assert prompt.count("(only 1: later panels continue the same picture)") == (
            3 if mode == "chained" else 0)
        assert "render in 6 seconds" in prompt and "@@" not in prompt
    ctx, plan, parts, text, _p = _story(ws, "shots", 3)
    lines = ["- fast-motion: motion LoRA for video, default strength 0.8, range 0.5 to 1.0."]
    with_lora = se.build_critic_prompt(plan, text, ([], []), catalog_lines=lines)
    assert ('field "lora", index 0 for the global picks or a beat number for that beat\'s own '
            "picks: replacement is the complete new list of picks, each an object with the keys "
            "id and strength, from this catalog:\n" + lines[0] + "\n") in with_lora
    many = (["panel %d: N1 word count: x" % i for i in range(1, 39)],
            ["panel 1: N13 repeat: y", "panel 2: N13 repeat: y", "panel 3: N13 repeat: y"])
    capped = se.build_critic_prompt(plan, text, many)
    block = capped.split("fix the hard ones first):\n", 1)[1].split("\n\nScore the draft", 1)[0]
    assert block.split("\n") == (["- [hard] panel %d: N1 word count: x" % i for i in range(1, 39)]
                                 + ["- [advisory] panel 1: N13 repeat: y",
                                    "- [advisory] panel 2: N13 repeat: y", "- ... and 1 more"])
    judge = se.build_critic_prompt(plan, text, many, for_judge=True)
    assert judge.endswith("\n\nCall submit_review with your scores, verdict and patches.")
    assert judge[:-len(se.JUDGE_REPLY_PARAGRAPH)] == capped[:-len(se.CRITIC_REPLY_PARAGRAPH)]
    goal_plan = dict(plan, goal="quiet suspense", narrative="N @@SECONDS@@")
    goal = se.build_critic_prompt(goal_plan, text, ([], []))
    assert "\n\nThe target output goal is quiet suspense.\n\nThe plan (JSON):\n" in goal
    assert "the panels tell the narrative and serve the target output goal, with" in goal
    assert "Narrative to adapt:\nN @@SECONDS@@\n" in goal


def _critic_ws(tmp_path, monkeypatch, critic=()):
    ws = seu.make_ws(tmp_path)
    log = seu.script_agent(monkeypatch, tmp_path, critic=list(critic))
    return seu.make_ctx(se, ws), log


def test_rst23_critic_routing(tmp_path, monkeypatch, capsys):
    prompt = "You are the critic for a test"
    ctx, log = _critic_ws(tmp_path, monkeypatch, critic=[{"answer": "L1"}, {"answer": "L2"},
                                                         {"answer": "L3"}, {"answer": "L4"}])
    local = seu.FakeFleet(seu.fleet_view(True, ["a"]))
    monkeypatch.setattr(se, "_load_fleet", lambda ws: local)
    assert se.run_critic(ctx, prompt) == ("ok", "L1", "local")
    assert local.calls == []
    records = seu.agent_log(log)
    assert "--skill=analyst" in records[0]["argv"] and records[0]["env_preflight"] == "1"
    peers = seu.FakeFleet(seu.fleet_view(False, ["a", "b"]),
                          [("busy", None, "no capacity"), ("ok", seu.ok_envelope("FLEET"), "")])
    monkeypatch.setattr(se, "_load_fleet", lambda ws: peers)
    assert se.run_critic(ctx, prompt) == ("ok", "FLEET", "fleet:b")
    assert [c[3] for c in peers.calls] == ["a", "b"]
    assert peers.calls[0][:3] == ("http://127.0.0.1:8190", "analyst", prompt)
    assert capsys.readouterr().out == "Warning: critic on a failed: busy no capacity\n"
    failing = seu.FakeFleet(seu.fleet_view(False, ["a"]), [("ok", seu.ok_envelope("  "), "")])
    monkeypatch.setattr(se, "_load_fleet", lambda ws: failing)
    assert se.run_critic(ctx, prompt) == ("ok", "L2", "local")
    monkeypatch.setattr(se, "_load_fleet", lambda ws: None)
    assert se.run_critic(ctx, prompt) == ("ok", "L3", "local")
    broken = seu.FakeFleet(seu.fleet_view(False, ["a"]), raise_on_fetch=True)
    monkeypatch.setattr(se, "_load_fleet", lambda ws: broken)
    assert se.run_critic(ctx, prompt) == ("ok", "L4", "local")
    assert broken.calls == []
    assert len(seu.agent_log(log)) == 4


def test_rst24_real_fleet_lib_with_no_daemon(tmp_path, monkeypatch):
    ctx, log = _critic_ws(tmp_path, monkeypatch, critic=[{"answer": "LOCAL"}])
    assert se._load_fleet(ctx.ws) is not None
    assert se.run_critic(ctx, "You are the critic for a test") == ("ok", "LOCAL", "local")
    assert len(seu.agent_log(log)) == 1


def test_rst26a_parse_critic():
    good = seu.critic_json((7, 6, 8), "revise", [{"target": "panel"}])
    assert se.parse_critic(json.dumps(good)) == good
    assert se.parse_critic("```json\n" + json.dumps(dict(good, extra=1)) + "\n```") == good
    for bad in (dict(good, scores={"continuity": 7, "story": 6}),
                dict(good, scores={"continuity": True, "story": 6, "renderability": 8}),
                dict(good, scores={"continuity": 11, "story": 6, "renderability": 8}),
                dict(good, scores={"continuity": 7.0, "story": 6, "renderability": 8}),
                dict(good, verdict="maybe"), dict(good, patches={})):
        assert se.parse_critic(json.dumps(bad)) is None, bad
    assert se.parse_critic(None) is None
````

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
4 failed, 24 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst22_critic_prompt
FAILED tests/test_story_engine.py::test_rst23_critic_routing
FAILED tests/test_story_engine.py::test_rst24_real_fleet_lib_with_no_daemon
FAILED tests/test_story_engine.py::test_rst26a_parse_critic
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# The critic: prompt (RS17), routing (RS18) and reply validation (RS19)
# ---------------------------------------------------------------------------

CRITIC_PROMPT_TEMPLATE = (
    'You are the critic for a short narrated movie (story-id "@@STORY_ID@@"). You will not see '
    "any other context: everything you need is below. Check the draft against its plan and "
    "propose small, exact fixes.\n"
    "\n"
    "How this movie is made: @@MODE_PARAGRAPH@@\n"
    "\n"
    "Narrative to adapt:\n"
    "@@NARRATIVE@@\n"
    "\n"
    "@@GOAL_PARAGRAPH@@The plan (JSON):\n"
    "@@PLAN_JSON@@\n"
    "\n"
    "The draft story.md:\n"
    "@@STORY_MD@@\n"
    "\n"
    "Problems the pipeline's own checks found in this draft (fix the hard ones first):\n"
    "@@VIOLATIONS@@\n"
    "\n"
    "Score the draft from 1 (worst) to 10 (best) on each of:\n"
    "- continuity: characters, places, objects and positions stay consistent from panel to "
    "panel.\n"
    "- story: the panels tell the narrative@@GOAL_CLAUSE@@, with a clear introduction, climax "
    "and resolution, and every panel moves the action forward.\n"
    "- renderability: every panel shows one concrete physical action that a video model can "
    "render in @@SECONDS@@ seconds, with no dialogue, no on-screen text and nothing outside the "
    "frame.\n"
    "\n"
    "Then propose at most 8 patches, most important first. Each patch is an object with exactly "
    "the keys target, index, field, reason and replacement. The allowed patches are:\n"
    "@@FIELD_LINES@@\n"
    "A panel replacement holds only the text the writer writes: never include a character's "
    "description, a setting sentence, the shot type or a camera sentence, because the pipeline "
    "adds those itself. The number of panels, the characters' referring phrases and their "
    "descriptions never change.\n"
    "\n"
    "@@REPLY_PARAGRAPH@@")
CRITIC_REPLY_PARAGRAPH = (
    "Reply with one JSON object with exactly the keys scores, verdict and patches: scores is an "
    "object with the integer keys continuity, story and renderability; verdict is \"ok\" when "
    "the draft needs no patch and \"revise\" otherwise; patches is the list of patches (empty "
    "when the verdict is \"ok\"). Reply with the JSON object only, with no text before or after "
    "it. Do not call any tool: do NOT read any file, and do NOT run any tool to check it.")
JUDGE_REPLY_PARAGRAPH = "Call submit_review with your scores, verdict and patches."
CRITIC_RETRY_SUFFIX = ("\n\nYour previous reply was not one JSON object with the keys scores, "
                       "verdict and patches in the required form. Reply with that JSON object "
                       "only.")
ONLY1 = " (only 1: later panels continue the same picture)"


def listed(lines):
    """At most MAX_LISTED lines, then "- ... and N more"."""
    if len(lines) <= MAX_LISTED:
        return list(lines)
    return list(lines[:MAX_LISTED]) + ["- ... and %d more" % (len(lines) - MAX_LISTED)]


def critic_field_lines(mode, catalog_lines):
    lines = [
        '- target "plan", field "beat.action", index = the beat number: replacement is the beat\'s '
        "new action, one sentence of 6 to 40 words; the pipeline rewrites that panel from it.",
        '- target "plan", field "beat.shot", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(SHOT_TYPES) + ".",
        '- target "plan", field "beat.camera", index = the beat number@@ONLY1@@: replacement is '
        "exactly one of: " + ", ".join(CAMERA_KEYS) + ".",
        '- target "plan", field "location.setting", index = the place\'s position in the plan\'s '
        "locations list (1 is the first): replacement is its new setting sentence, 12 to 45 "
        'words starting "The setting is"; it replaces that sentence in every panel at that '
        "place."]
    if catalog_lines:
        lines.append('- target "plan", field "lora", index 0 for the global picks or a beat '
                     "number for that beat's own picks: replacement is the complete new list of "
                     "picks, each an object with the keys id and strength, from this catalog:"
                     + "\n" + "\n".join(catalog_lines))
    if mode in ("chained", "shots"):
        lines.append('- target "panel", field "image", index = the panel number@@ONLY1@@: '
                     "replacement is the new writer text of that panel's Image: field.")
        lines.append('- target "panel", field "motion", index = the panel number: replacement is '
                     "the new writer text of that panel's Motion: field.")
    else:
        lines.append('- target "panel", field "prompt", index = the panel number: replacement is '
                     "the new writer text of that panel's Prompt: field.")
    lines.append('- target "panel", field "narration", index = the panel number: replacement is '
                 "the panel's new narration sentence.")
    return "\n".join(lines)


def build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False):
    """The exact critic prompt of RS17. violations is (hard, advisory) of the judged state;
    mode, panels, seconds, narrative, goal and story_id come from the plan."""
    hard, advisory = violations
    lines = listed(["- [hard] " + m for m in hard] + ["- [advisory] " + m for m in advisory])
    plan_json = json.dumps({k: plan[k] for k in ("title", "logline", "cast", "locations", "props",
                                                 "beats", "loras")}, indent=1, ensure_ascii=False)
    fragments = [
        ("@@GOAL_PARAGRAPH@@", _goal_paragraph(plan["goal"])),
        ("@@MODE_PARAGRAPH@@", MODE_PARAGRAPHS[plan["mode"]]),
        ("@@VIOLATIONS@@", "\n".join(lines) if lines else "- none"),
        ("@@GOAL_CLAUSE@@", " and serve the target output goal" if plan["goal"] else ""),
        ("@@FIELD_LINES@@", critic_field_lines(plan["mode"], catalog_lines)),
        ("@@ONLY1@@", ONLY1 if plan["mode"] == "chained" else ""),
        ("@@REPLY_PARAGRAPH@@", JUDGE_REPLY_PARAGRAPH if for_judge else CRITIC_REPLY_PARAGRAPH),
    ]
    text = CRITIC_PROMPT_TEMPLATE
    for token, value in fragments:
        text = text.replace(token, value)
    for token, value in (("@@STORY_ID@@", plan["story_id"]), ("@@SECONDS@@", plan["seconds"])):
        text = text.replace(token, value)
    text = text.replace("@@PLAN_JSON@@", plan_json).replace("@@STORY_MD@@", story_md_text)
    return text.replace("@@NARRATIVE@@", plan["narrative"])


def run_critic(ctx, prompt):
    """(status, answer, route) of one critic call (RS18): the fleet's analyst peers in order
    when this host does not serve analyst, else (and on every failure) a local one-shot
    bin/qwen-agent --skill=analyst."""
    fleet = _load_fleet(ctx.ws)
    if fleet is not None:
        try:
            url, _warning = fleet.daemon_url_from_env(os.environ)
            view, _warning = fleet.fetch_view(url)
            candidates = fleet.route_candidates("analyst", view) if view is not None else []
        except Exception:
            url, candidates = None, []
        if candidates and candidates != [fleet.LOCAL]:
            for host_id in candidates:
                try:
                    outcome, envelope, detail = fleet.delegate_once(url, "analyst", prompt, host_id)
                except Exception as e:
                    outcome, envelope, detail = "error", None, type(e).__name__
                answer = envelope.get("answer") if isinstance(envelope, dict) else None
                if (outcome == "ok" and isinstance(envelope, dict)
                        and envelope.get("status") == "ok"
                        and isinstance(answer, str) and answer.strip()):
                    return "ok", answer, "fleet:" + host_id
                print("Warning: critic on %s failed: %s %s" % (host_id, outcome, detail or ""))
    status, answer = run_agent(ctx, prompt, max_tokens=CRITIC_MAX_TOKENS, timeout=CRITIC_TIMEOUT,
                               skill="analyst", preflight_done=True)
    return status, answer, "local"


def _score(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10


def parse_critic(answer):
    """The critic reply dict, or None unless it has integer scores 1-10 for continuity, story
    and renderability, a verdict of "ok" or "revise", and a patches list (RS19)."""
    obj = extract_json(answer)
    if obj is None:
        return None
    scores = obj.get("scores")
    if not isinstance(scores, dict) or not all(_score(scores.get(k)) for k in SCORE_KEYS):
        return None
    if obj.get("verdict") not in ("ok", "revise") or not isinstance(obj.get("patches"), list):
        return None
    return {"scores": {k: scores[k] for k in SCORE_KEYS}, "verdict": obj["verdict"],
            "patches": obj["patches"]}
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
28 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/story_engine_testutil.py tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: critic prompt, fleet or local routing, reply validation (story RS17-RS19)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 8: Patches: the per-mode whitelist and application

Implements RS20. Tests RST27-RST32 and LCT28.

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Task 5's `lora_checks`, `compatible_entries`, `_setting_problems`, `pasted_pieces`, `_q`; Task 6's `clean_writer`; `SHOT_TYPES`, `CAMERA_KEYS`, `MAX_PATCHES`.
- Produces: In `se`: `PATCH_KEYS`; `lora_patches_allowed(ctx) -> bool`; `patch_ranges(ctx, plan, lora_allowed) -> {(target, field): (lo, hi)|None}`; `_patch_problem(ranges, patch) -> str|None`; `apply_patches(ctx, state, patches, regen=None, lora_allowed=None) -> (new_state, applied, rejected, regenerate)` where `state` is `{"plan", "parts"}`, `rejected` items are `{"patch", "reason"}`, and `regen(k, plan, parts)` returns `("ok", parts_k)`, `("failed", None)`, `("budget", None)` or `("time", None)`. In the test module: `_patch(target, index, field, replacement, reason="because")`, `_state(ws, mode, n=3, **kw)`, `_reasons(rejected)`, `_lora_state(ws, tmp_path, story_env, cast_kyra=False)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst27_whitelist_limit_and_duplicates`, `test_rst28_location_setting_patch`, `test_rst29_beat_action_regenerates_that_panel`, `test_rst30_shot_and_camera_reassemble_without_agent_calls`, `test_rst31_lora_patch`, `test_rst32_patches_never_change_counts_phrases_or_descriptors`, `test_lct28_lora_limits_with_a_cast_character`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST27-RST32, LCT28: patches (RS20) ----------------------------------------------------

def _patch(target, index, field, replacement, reason="because"):
    return {"target": target, "index": index, "field": field, "reason": reason,
            "replacement": replacement}


def _state(ws, mode, n=3, **kw):
    ctx, plan, parts, _text, _path = _story(ws, mode, n, **kw)
    return ctx, {"plan": plan, "parts": parts}


def _reasons(rejected):
    return [r["reason"] for r in rejected]


def test_rst27_whitelist_limit_and_duplicates(ws):
    ctx, state = _state(ws, "chained")
    good_action = "the courier coasts slowly down the empty harbour road"
    patches = [
        _patch("plan", 2, "beat.shot", "close-up"),
        _patch("plan", 2, "beat.camera", "static"),
        _patch("panel", 2, "image", "x"),
        _patch("panel", 1, "prompt", "x"),
        _patch("plan", 1, "lora", []),
        _patch("plan", 4, "beat.action", good_action),
        _patch("plan", True, "beat.action", good_action),
        _patch("panel", 0, "narration", "x"),
        _patch("story", 1, "narration", "x"),
        {"target": "panel", "index": 1, "field": "narration"},
        _patch("panel", 1, "narration", ["x"]),
        _patch("plan", 1, "lora", "x"),
    ]
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, patches[:8])
    assert applied == [] and regenerate == []
    assert _reasons(rejected) == [
        "index 2 is out of range for beat.shot (allowed: 1 only)",
        "index 2 is out of range for beat.camera (allowed: 1 only)",
        "index 2 is out of range for image (allowed: 1 only)",
        "field not allowed in this mode",
        "field not allowed in this mode",
        "index 4 is out of range for beat.action (allowed: 1 to 3)",
        "index is not an integer",
        "index 0 is out of range for narration (allowed: 1 to 3)"]
    _new, _a, rejected, _r = se.apply_patches(ctx, state, patches[8:])
    assert _reasons(rejected) == [
        "unknown target or field",
        "not an object with the keys target, index, field, reason and replacement",
        "replacement must be a string", "field not allowed in this mode"]
    nine = [_patch("panel", (i % 3) + 1, "narration", "Line %d of the rain." % i) for i in range(9)]
    _new, applied, rejected, _r = se.apply_patches(ctx, state, nine)
    assert [p["index"] for p in applied] == [1, 2, 3]
    assert _reasons(rejected) == ["duplicate patch target"] * 5 + ["over the 8-patch limit"]
    assert rejected[-1]["patch"] is nine[8]
    shots_ctx, shots_state = _state(ws, "shots")
    _new, applied, rejected, _r = se.apply_patches(shots_ctx, shots_state, [
        _patch("plan", 3, "beat.shot", "close-up"), _patch("panel", 3, "image", "The courier "
                                                                                "waits."),
        _patch("panel", 2, "prompt", "x")])
    assert len(applied) == 2 and _reasons(rejected) == ["field not allowed in this mode"]
    no_stills_ctx, ns_state = _state(ws, "no_stills")
    _new, applied, rejected, _r = se.apply_patches(no_stills_ctx, ns_state, [
        _patch("panel", 2, "motion", "x"), _patch("panel", 2, "prompt", "The courier pedals.")])
    assert len(applied) == 1 and _reasons(rejected) == ["field not allowed in this mode"]
    assert state["parts"][0]["narration"] == "The rain had not stopped since dawn."


def test_rst28_location_setting_patch(ws):
    ctx, state = _state(ws, "shots")
    new_setting = ("The setting is a stormy fishing harbour in modern Japan, slick black "
                   "cobblestones underfoot, cranes behind, under blue evening light.")
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 1, "location.setting", new_setting[:-1]),
        _patch("plan", 2, "location.setting", "The setting is short")])
    assert len(applied) == 1
    assert _reasons(rejected) == ["the new setting is 4 words; it must be 12-45"]
    text = se.assemble(ctx, new["plan"], new["parts"])
    assert text.count(new_setting) == 3
    assert seu.HARBOUR not in text
    assert state["plan"]["locations"][0]["setting"] == seu.HARBOUR


def test_rst29_beat_action_regenerates_that_panel(ws):
    ctx, state = _state(ws, "shots")
    calls = []

    def regen(k, plan, parts):
        calls.append((k, plan["beats"][k - 1]["action"]))
        return "ok", dict(parts[k - 1], motion="The courier rests one hand on the railing.")

    action = "the courier stops beside the railing to catch his breath"
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.action", action),
        _patch("panel", 2, "motion", "The courier waves."),
        _patch("plan", 3, "beat.action", "too short")], regen=regen)
    assert calls == [(2, action)] and regenerate == [2]
    assert new["parts"][1]["motion"] == "The courier rests one hand on the railing."
    assert _reasons(rejected) == ["the new action is 2 words; it must be 6 to 40",
                                  "panel regenerated from a beat.action patch this round"]
    new, applied, rejected, regenerate = se.apply_patches(
        ctx, state, [_patch("plan", 2, "beat.action", action)],
        regen=lambda k, plan, parts: ("budget", None))
    assert new["plan"]["beats"][1]["action"] == action
    assert new["parts"][1] == state["parts"][1]
    assert _reasons(rejected) == ["panel 2 regeneration skipped: call budget exhausted"]


def test_rst30_shot_and_camera_reassemble_without_agent_calls(ws, monkeypatch):
    ctx, state = _state(ws, "shots")
    monkeypatch.setattr(se, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    new, applied, rejected, regenerate = se.apply_patches(ctx, state, [
        _patch("plan", 2, "beat.shot", "Close-Up"), _patch("plan", 2, "beat.camera", "slow pan left"),
        _patch("plan", 3, "beat.shot", "aerial")])
    assert regenerate == [] and len(applied) == 2
    assert _reasons(rejected) == ["'aerial' is not one of: extreme wide shot, wide shot, medium "
                                  "shot, medium close-up, close-up, extreme close-up"]
    fields = dict(se.panel_fields(ctx, new["plan"], new["parts"], 2))
    assert fields["Image"].endswith(" The shot is a close-up.")
    assert fields["Motion"].endswith(" The camera slowly pans left.")


def _lora_state(ws, tmp_path, story_env, cast_kyra=False):
    files = str(tmp_path / "files")
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    kw = {"catalog": {"schema_version": 1, "entries": entries}}
    plan_mut = None
    if cast_kyra:
        kw["members"] = _cast_members(story_env, "kyra")

        def plan_mut(raw):
            raw["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
                           {"id": "c2", "phrase": "the old monk", "descriptor": seu.MONK}]
            raw["loras"] = {"global": [{"id": "film-grain", "strength": 0.8}],
                            "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
                            "stills": []}
    return _state(ws, "shots", plan_mut=plan_mut, ctx_kw=kw)


def test_rst31_lora_patch(ws, tmp_path, story_env):
    ctx, state = _lora_state(ws, tmp_path, story_env)
    new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 0, "lora", [{"id": "fast-motion", "strength": 0.7}]),
        _patch("plan", 2, "lora", [{"id": "rain-physics", "strength": 0.9}])])
    assert len(applied) == 1
    assert new["plan"]["loras"]["global"] == [{"id": "fast-motion", "strength": 0.7}]
    assert new["plan"]["loras"]["per_beat"] == {}
    assert _reasons(rejected) == ["would break beat 2: L3 motion: 2 motion or physics LoRAs on "
                                  "this panel (fast-motion, rain-physics); at most 1"]
    cleared, applied, _rj, _r = se.apply_patches(ctx, new, [_patch("plan", 0, "lora", [])])
    assert cleared["plan"]["loras"]["global"] == [] and len(applied) == 1


def test_rst32_patches_never_change_counts_phrases_or_descriptors(ws):
    ctx, state = _state(ws, "shots", n=4)
    rng = random.Random(7)
    fields = ["beat.action", "beat.shot", "beat.camera", "location.setting", "lora", "motion",
              "image", "prompt", "narration", "cast.phrase", "descriptor"]
    values = ["the courier runs along the quay past the moored boats", "close-up", "static",
              seu.TEMPLE, "x", "", "The courier jumps.", [], [{"id": "x", "strength": 1}], 3,
              "the stranger"]
    before = (len(state["parts"]), len(state["plan"]["beats"]),
              [(c["phrase"], c["descriptor"]) for c in state["plan"]["cast"]])
    for _ in range(20):
        patches = [_patch(rng.choice(["plan", "panel", "cast"]), rng.randint(-1, 5),
                          rng.choice(fields), rng.choice(values)) for _ in range(rng.randint(0, 10))]
        new, _a, _rj, _r = se.apply_patches(ctx, state, patches)
        after = (len(new["parts"]), len(new["plan"]["beats"]),
                 [(c["phrase"], c["descriptor"]) for c in new["plan"]["cast"]])
        assert after == before
        state = new


def test_lct28_lora_limits_with_a_cast_character(ws, tmp_path, story_env):
    ctx, state = _lora_state(ws, tmp_path, story_env, cast_kyra=True)
    plan = state["plan"]
    assert plan["beats"][1]["cast"] == ["c1"] and plan["cast"][0]["cast_name"] == "kyra"
    compatible = {e["id"]: e for e in se.compatible_entries(ctx)}
    catalog = {e["id"]: e for e in ctx.catalog["entries"]}
    assert se.lora_checks(ctx, plan, compatible, catalog) == ([], [])
    _new, applied, rejected, _r = se.apply_patches(ctx, state, [
        _patch("plan", 2, "lora", [{"id": "fast-motion", "strength": 0.7},
                                   {"id": "rain-physics", "strength": 0.6}])])
    assert applied == []
    assert _reasons(rejected) == ["would break beat 2: L3 motion: 2 motion or physics LoRAs on "
                                  "this panel (fast-motion, rain-physics); at most 1"]
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
7 failed, 28 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst27_whitelist_limit_and_duplicates
FAILED tests/test_story_engine.py::test_rst28_location_setting_patch
FAILED tests/test_story_engine.py::test_rst29_beat_action_regenerates_that_panel
FAILED tests/test_story_engine.py::test_rst30_shot_and_camera_reassemble_without_agent_calls
FAILED tests/test_story_engine.py::test_rst31_lora_patch
FAILED tests/test_story_engine.py::test_rst32_patches_never_change_counts_phrases_or_descriptors
FAILED tests/test_story_engine.py::test_lct28_lora_limits_with_a_cast_character
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# Patches: the per-mode whitelist and application (RS20)
# ---------------------------------------------------------------------------

PATCH_KEYS = ("target", "index", "field", "reason", "replacement")


def lora_patches_allowed(ctx):
    """lora patches need auto LoRA and at least one compatible video catalog entry."""
    return ctx.auto_lora and any(e["target"] == "video" for e in compatible_entries(ctx))


def patch_ranges(ctx, plan, lora_allowed):
    """{(target, field): (lo, hi) | None} -- None means "field not allowed in this mode"."""
    n, mode = ctx.panels, ctx.mode
    first_only = (1, 1) if mode == "chained" else (1, n)
    return {("plan", "beat.action"): (1, n),
            ("plan", "beat.shot"): first_only,
            ("plan", "beat.camera"): first_only,
            ("plan", "location.setting"): (1, len(plan["locations"])),
            ("plan", "lora"): (0, n) if lora_allowed else None,
            ("panel", "image"): first_only if mode != "no_stills" else None,
            ("panel", "motion"): (1, n) if mode != "no_stills" else None,
            ("panel", "prompt"): (1, n) if mode == "no_stills" else None,
            ("panel", "narration"): (1, n)}


def _patch_problem(ranges, patch):
    if not isinstance(patch, dict) or not all(k in patch for k in PATCH_KEYS):
        return "not an object with the keys target, index, field, reason and replacement"
    key = (patch["target"], patch["field"])
    if not all(isinstance(v, str) for v in key) or key not in ranges:
        return "unknown target or field"
    span = ranges[key]
    if span is None:
        return "field not allowed in this mode"
    index = patch["index"]
    if not isinstance(index, int) or isinstance(index, bool):
        return "index is not an integer"
    if not span[0] <= index <= span[1]:
        allowed = "%d only" % span[0] if span[0] == span[1] else "%d to %d" % span
        return "index %d is out of range for %s (allowed: %s)" % (index, patch["field"], allowed)
    if patch["field"] == "lora":
        if not isinstance(patch["replacement"], list):
            return "replacement must be a list of picks"
    elif not isinstance(patch["replacement"], str):
        return "replacement must be a string"
    return None


def apply_patches(ctx, state, patches, regen=None, lora_allowed=None):
    """(new_state, applied, rejected, regenerate) for a state {"plan", "parts"} and a patch
    list (RS20). Works on a deep copy. regen(k, plan, parts) -> ("ok", parts_k) | ("failed",
    None) | ("budget", None) | ("time", None) regenerates panel k after a beat.action patch;
    without regen the panel keeps its parts. rejected items are {"patch", "reason"}."""
    new = copy.deepcopy(state)
    plan, parts = new["plan"], new["parts"]
    lib = _character_lib(ctx.ws)
    if lora_allowed is None:
        lora_allowed = lora_patches_allowed(ctx)
    ranges = patch_ranges(ctx, plan, lora_allowed)
    applied, rejected, regenerate = [], [], []
    accepted, seen = [], set()
    patches = patches if isinstance(patches, list) else []
    for i, patch in enumerate(patches):
        if i >= MAX_PATCHES:
            rejected.append({"patch": patch, "reason": "over the 8-patch limit"})
            continue
        problem = _patch_problem(ranges, patch)
        if problem is None:
            key = (patch["target"], patch["index"], patch["field"])
            if key in seen:
                problem = "duplicate patch target"
            seen.add(key)
        if problem:
            rejected.append({"patch": patch, "reason": problem})
        else:
            accepted.append(patch)
    compatible_by_id = {e["id"]: e for e in compatible_entries(ctx)}
    catalog_by_id = {e["id"]: e for e in ctx.catalog.get("entries", [])}
    for patch in accepted:
        if patch["target"] != "plan":
            continue
        field, index = patch["field"], patch["index"]
        if field == "beat.action":
            action = clean_writer(lib, patch["replacement"])
            words = _words(action)
            if not 6 <= words <= 40:
                rejected.append({"patch": patch, "reason": "the new action is %d words; it must "
                                                           "be 6 to 40" % words})
                continue
            plan["beats"][index - 1]["action"] = action
            regenerate.append(index)
        elif field in ("beat.shot", "beat.camera"):
            value = _collapse(patch["replacement"]).lower()
            allowed = SHOT_TYPES if field == "beat.shot" else CAMERA_KEYS
            if value not in allowed:
                rejected.append({"patch": patch, "reason": "%s is not one of: %s"
                                 % (_q(value), ", ".join(allowed))})
                continue
            plan["beats"][index - 1][field.split(".")[1]] = value
        elif field == "location.setting":
            setting = _collapse(patch["replacement"])
            if setting and not setting.endswith((".", "!", "?")):
                setting += "."
            problems = _setting_problems(setting)
            if problems:
                rejected.append({"patch": patch, "reason": "the new setting " + problems[0]})
                continue
            plan["locations"][index - 1]["setting"] = setting
        else:
            before = lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
            saved = copy.deepcopy(plan["loras"])
            if index == 0:
                plan["loras"]["global"] = patch["replacement"]
            elif patch["replacement"]:
                plan["loras"]["per_beat"][str(index)] = patch["replacement"]
            else:
                plan["loras"]["per_beat"].pop(str(index), None)
            broken = [h for h in lora_checks(ctx, plan, compatible_by_id, catalog_by_id)[0]
                      if h not in before]
            if broken:
                plan["loras"] = saved
                rejected.append({"patch": patch, "reason": "would break " + broken[0]})
                continue
        applied.append(patch)
    regenerate = sorted(set(regenerate))
    for k in regenerate:
        if regen is None:
            continue
        outcome, new_parts = regen(k, plan, parts)
        if outcome == "ok":
            parts[k - 1] = new_parts
        elif outcome in ("budget", "time"):
            action_patch = [p for p in accepted if p["field"] == "beat.action"
                            and p["index"] == k][0]
            rejected.append({"patch": action_patch, "reason": "panel %d regeneration skipped: %s"
                             % (k, "call budget exhausted" if outcome == "budget"
                                else "wall-clock cap reached")})
    for patch in accepted:
        if patch["target"] != "panel":
            continue
        k, field = patch["index"], patch["field"]
        if k in regenerate:
            rejected.append({"patch": patch,
                             "reason": "panel regenerated from a beat.action patch this round"})
            continue
        text = clean_writer(lib, patch["replacement"],
                            pasted_pieces(ctx, plan, k).get(field, ()))
        if not text:
            rejected.append({"patch": patch, "reason": "empty after cleanup"})
            continue
        parts[k - 1][field] = text
        applied.append(patch)
    return new, applied, rejected, regenerate
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
35 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: patch whitelist and application (story RS20; catalog LC12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 9: The run: plan and panel calls, the round controller, ranking, budgets, the judge gate, outputs

Implements RS8, RS13 (retry and budget), RS21, RS22, RS23, RS24, RS25 (the engine's files), RS26 (per round and best round), RS27. Tests RST10, RST11, RST17b, RST26b, RST33-RST39, RST43, RST55b, RST58, and Review Focus 1-3.

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Everything Tasks 4-8 produce; the fake judge of Task 4.
- Produces: In `se`: `WRITER_CHECK_IDS`; `_unused_dir(path)`; `_reply_text(status, answer)`; `_scores_of(states, i)`; `_key(states, i)`; `better(states, a, b) -> bool`; `best_round(states) -> int`; `_checks_doc(ctx, state, source="robust") -> dict`; class `_Run`; `run(ctx, no_stills_rules="") -> (exit code, advisories)`; `run_judge(ctx, round_dir) -> ("ok", "", reply) | ("error", detail, None)`. In the test module: `SHOUT1`, `SHOUT2`, `_panel_script(mode, n, phrase="the courier", **overrides)`, `_shouting(mode, k, text)`, `_run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(), **ctx_kw) -> (rc, advisories, ctx, agent log)`, `_rounds(ctx, r=None)`, `_read_json(path)`, `_narration_patch(k, text)`, `_motion_patch(k, text)`, `_judge_env(monkeypatch, tmp_path, reply)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst10_plan_retry_and_fatal_plan`, `test_rst11_short_plan_is_fatal`, `test_rst17b_invalid_panel_retried_once_never_three_times`, `test_rst26b_critic_retry_and_code_only_round`, `test_rst33_stop_passed`, `test_rst34_stop_plateau`, `test_rst35_stop_max_rounds`, `test_rst36_ranking`, `test_rst37_budgets_and_the_wall_clock`, `test_rst39_outputs_and_layout`, `test_rst43_exit_2_message`, `test_rst55b_p13_forces_plan_call_2`, `test_rst58_a_patch_that_names_an_undeclared_character_loses`, `test_rst38_judge_gate`, `test_story_focus_1_a_non_ascii_phrase_is_repaired_or_reported`, `test_story_focus_2_a_one_panel_story`, `test_story_focus_3_ctrl_c_during_a_run_keeps_story_md`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST10, RST11, RST17b, RST26b, RST33-RST39, RST43, RST55b, RST58: the run (RS8, RS13,
# RS21-RS27) -----------------------------------------------------------------------------------

SHOUT2 = "The courier shouts across the quay and pedals on toward the far end of the wet road."
SHOUT1 = SHOUT2[:-1] + " past the moored boats."


def _panel_script(mode, n, phrase="the courier", **overrides):
    """{"<k>": [one valid reply]} for every panel; overrides p<k>=[items] replace panel k's."""
    script = dict((str(k), [seu.answer(seu.panel_json(mode, k, phrase))]) for k in range(1, n + 1))
    for key, items in overrides.items():
        script[key[1:]] = items
    return script


def _shouting(mode, k, text):
    return seu.answer(dict(seu.panel_json(mode, k), motion=text))


def _run(ws, tmp_path, monkeypatch, mode="chained", n=3, plan=None, panel=None, critic=(),
         **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path,
                           plan=plan if plan is not None else [seu.answer(seu.plan_json(mode, n))],
                           panel=panel if panel is not None else _panel_script(mode, n),
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, advisories = se.run(ctx)
    return rc, advisories, ctx, seu.agent_log(log)


def _rounds(ctx, r=None):
    base = os.path.join(ctx.story_dir, "story_rounds")
    return base if r is None else os.path.join(base, "round_%d" % r)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_rst10_plan_retry_and_fatal_plan(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "I think the story is about rain."}, seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert os.path.exists(os.path.join(_rounds(ctx, 0), "plan_reply_2.txt"))
    second = log[1]["argv"][-1]
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object\n"
            "Previous reply:\nI think the story is about rain.\n\nReply with the complete "
            "corrected JSON object only.") in second
    assert second.startswith('You are planning a short narrated movie (story-id "s1").')
    capsys.readouterr()
    os.makedirs(os.path.join(ws, "generated", "stories", "s2"))
    with open(os.path.join(ws, "generated", "stories", "s2", "story.md"), "w") as f:
        f.write("OLD")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2",
                            plan=[{"answer": "nope"}, {"status": "http_error"}])
    assert rc == 1
    err = capsys.readouterr().err
    assert err == ("Error: the story model did not return a usable plan after 2 call(s)\n"
                   "  - the reply is not one JSON object\n"
                   "Raw replies are kept in %s. Rerun the same command to try again.\n"
                   % _rounds(ctx, 0))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert f.read() == "OLD"
    assert not os.path.exists(os.path.join(ctx.story_dir, "plan.json"))
    with open(os.path.join(_rounds(ctx, 0), "plan_reply_2.txt")) as f:
        assert f.read() == "<no answer: http_error>"
    assert [r["stage"] for r in log] == ["plan", "plan"]


def test_rst11_short_plan_is_fatal(ws, tmp_path, monkeypatch, capsys):
    short = seu.plan_json("chained", 5)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, n=6,
                            plan=[seu.answer(short), seu.answer(short)])
    assert rc == 1 and len(log) == 2
    assert capsys.readouterr().err.splitlines()[:2] == [
        "Error: the story model did not return a usable plan after 2 call(s)",
        "  - plan: P1 beat count: expected exactly 6 beats, found 5"]
    assert "plan: P1 beat count: expected exactly 6 beats, found 5" in log[1]["argv"][-1]


def test_rst17b_invalid_panel_retried_once_never_three_times(ws, tmp_path, monkeypatch):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[{"answer": "not json"}, {"answer": "still not json"}]))
    assert rc == 2
    panel2 = [r for r in log if r["stage"] == "panel" and r["panel"] == 2]
    assert len(panel2) == 2
    assert ("Your previous version of this panel was rejected. Problems:\n- the reply is not one "
            "JSON object with the keys title, motion, narration\nPrevious version:\ntitle: "
            "the courier swerves around a\nmotion: \nnarration: \n\n") in panel2[1]["argv"][-1]
    parts = _read_json(os.path.join(_rounds(ctx, 0), "parts.json"))["panels"]
    assert parts[1] == {"index": 2, "title": "the courier swerves around a", "motion": "",
                        "narration": ""}


def test_rst26b_critic_retry_and_code_only_round(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))]),
        critic=[{"answer": "garbage"}, {"answer": "{}"}, {"answer": "still garbage"},
                seu.answer(seu.critic_json())])
    assert rc == 0
    out = capsys.readouterr().out
    assert "critic round 1: no valid reply after 2 call(s); code-only round\n" in out
    assert "critic round 2 (local): continuity=8 story=8 renderability=8 verdict=ok; 0 patch(es): " \
           "0 applied, 0 rejected\nstop: passed; best round 1 (0 hard)\n" in out
    assert [(r["stage"], r["panel"]) for r in log] == [
        ("plan", None), ("panel", 1), ("panel", 2), ("panel", 3), ("critic", None),
        ("critic", None), ("panel", 2), ("critic", None), ("critic", None)]
    assert log[5]["argv"][-1].endswith(se.CRITIC_RETRY_SUFFIX)
    assert "panel 2: N7 dialogue and text: Motion: says 'shouts'" in log[6]["argv"][-1]
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1 == {"route": "local", "calls": 2, "reply": None, "applied": [], "rejected": []}


def test_rst33_stop_passed(ws, tmp_path, monkeypatch, capsys):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch,
                                    critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert (rc, advisories) == (0, [])
    assert capsys.readouterr().out == (
        "plan: call 1 of 2\npanel 1/3: call 1\npanel 2/3: call 1\npanel 3/3: call 1\n"
        "round 0: 0 hard, 0 advisory\n"
        "critic round 1 (local): continuity=7 story=7 renderability=8 verdict=ok; 0 patch(es): "
        "0 applied, 0 rejected\nstop: passed; best round 0 (0 hard)\n")
    assert [r["stage"] for r in log].count("critic") == 1
    assert [r["env_preflight"] for r in log] == [None, "1", "1", "1", "1"]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["stop_reason"], checks["best_round"], checks["round"]) == ("passed", 0, 0)
    assert checks["scores"] == {"continuity": 7, "story": 7, "renderability": 8}


def _narration_patch(k, text):
    return {"target": "panel", "index": k, "field": "narration", "reason": "r",
            "replacement": text}


def test_rst34_stop_plateau(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "The streets ran with water.")])),
        seu.answer(seu.critic_json((5, 5, 5), "revise", [_narration_patch(3, "Never applied.")]))])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.endswith("critic round 2 (local): continuity=5 story=5 renderability=5 "
                        "verdict=revise; 1 patch(es): 0 applied, 0 rejected\n"
                        "stop: plateau; best round 0 (0 hard)\n")
    assert _read_json(os.path.join(_rounds(ctx, 2), "critic.json"))["applied"] == []
    assert not os.path.exists(os.path.join(_rounds(ctx, 2), "plan.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        story = f.read()
    with open(os.path.join(_rounds(ctx, 0), "story.md")) as f:
        assert f.read() == story


def _motion_patch(k, text):
    return {"target": "panel", "index": k, "field": "motion", "reason": "r", "replacement": text}


def test_rst35_stop_max_rounds(ws, tmp_path, monkeypatch, capsys):
    clean = dict((k, seu.panel_json("chained", k)["motion"]) for k in (1, 2, 3))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p1=[_shouting("chained", 1, SHOUT1)], p2=[_shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, SHOUT2.replace("quay", "lane"))]),
        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(2, clean[2])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(3, clean[3])])),
                seu.answer(seu.critic_json((6, 6, 6), "revise", [_motion_patch(1, clean[1])]))])
    assert rc == 0
    out = capsys.readouterr().out
    hard_counts = [int(line.split()[2]) for line in out.splitlines() if line.startswith("round ")]
    assert hard_counts == [3, 2, 1, 0]
    assert out.endswith("stop: max_rounds; best round 3 (0 hard)\n")
    assert sorted(os.listdir(_rounds(ctx))) == ["round_0", "round_1", "round_2", "round_3",
                                                "run.json"]


def test_rst36_ranking():
    def state(hard, scores=None):
        return {"hard": ["x"] * hard,
                "scores": dict(zip(se.SCORE_KEYS, scores)) if scores else None}

    assert se.best_round([state(2, (9, 9, 9)), state(1, (3, 3, 3))]) == 1
    assert se.best_round([state(1, (6, 9, 9)), state(1, (7, 7, 7))]) == 1
    assert se.best_round([state(1, (7, 7, 9)), state(1, (7, 7, 8))]) == 0
    assert se.best_round([state(1, (7, 7, 8)), state(1, (7, 7, 8))]) == 1
    states = [state(1, (6, 6, 6)), state(1)]
    assert se.best_round(states) == 1 and not se.better(states, 1, 0)
    assert se.better([state(2), state(1)], 1, 0)
    assert se.best_round([state(0), state(0)]) == 1


def test_rst37_budgets_and_the_wall_clock(ws, tmp_path, monkeypatch, capsys):
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        {"answer": "no"}, seu.answer(seu.plan_json("chained", 3))], panel=_panel_script(
        "chained", 3, p1=[{"answer": "no"}, seu.answer(seu.panel_json("chained", 1))],
        p2=[_shouting("chained", 2, SHOUT2), seu.answer(seu.panel_json("chained", 2))],
        p3=[_shouting("chained", 3, SHOUT2), _shouting("chained", 3, SHOUT2)]),
        critic=[{"answer": "x"}] * 6)
    assert rc == 2
    calls = _read_json(os.path.join(_rounds(ctx), "run.json"))["calls"]
    stages = [(c["stage"], c["panel"]) for c in calls]
    assert stages.count(("plan", None)) == 2
    assert all(stages.count(("panel", k)) <= 2 for k in (1, 2, 3))
    assert [c["round"] for c in calls if c["stage"] == "critic"] == [1, 1, 2, 2, 3, 3]
    assert "stop: plateau; best round 2 (1 hard)" in capsys.readouterr().out
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert run_doc["budgets"] == {"plan_calls": 2, "panel_calls": 2, "critic_rounds": 3,
                                  "critic_calls_per_round": 2, "max_patches": 8,
                                  "wall_clock_s": 2400}
    assert (run_doc["exit"], run_doc["stop_reason"], run_doc["best_round"]) == (2, "plateau", 2)

    clock = [0.0]
    monkeypatch.setattr(se, "_now", lambda: clock[0])
    real_agent = se.run_agent

    def slow_agent(*args, **kwargs):
        result = real_agent(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_agent", slow_agent)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2")
    assert rc == 1 and [r["stage"] for r in log] == ["plan"]
    assert capsys.readouterr().err == (
        "Error: story generation exceeded the wall-clock cap of 2400s before every panel was "
        "written; partial work is kept in %s\n" % _rounds(ctx, 0))
    assert not os.path.exists(os.path.join(ctx.story_dir, "story.md"))

    clock[0] = 0.0
    monkeypatch.setattr(se, "run_agent", real_agent)
    real_critic = se.run_critic

    def slow_critic(*args, **kwargs):
        result = real_critic(*args, **kwargs)
        clock[0] = 10.0 ** 6
        return result

    monkeypatch.setattr(se, "run_critic", slow_critic)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s3", critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")]))])
    assert rc == 0
    assert capsys.readouterr().out.endswith("stop: time_cap; best round 1 (0 hard)\n")
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))


def test_rst39_outputs_and_layout(ws, tmp_path, monkeypatch):
    os.makedirs(os.path.join(ws, "generated", "stories", "s1", "story_rounds"))
    with open(os.path.join(ws, "generated", "stories", "s1", "story_rounds", "old.txt"), "w") as f:
        f.write("kept")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((6, 6, 6), "revise", [_narration_patch(2, "It rained on.")])),
        seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    moved = [n for n in os.listdir(ctx.story_dir) if n.startswith("story_rounds-")]
    assert len(moved) == 1 and re.fullmatch(r"story_rounds-\d{8}T\d{6}Z-\d+", moved[0])
    with open(os.path.join(ctx.story_dir, moved[0], "old.txt")) as f:
        assert f.read() == "kept"
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert list(plan) == ["schema", "story_id", "mode", "panels", "seconds", "narrative", "goal",
                          "seed_image", "video_model", "auto_lora", "title", "logline", "cast",
                          "locations", "props", "beats", "loras"]
    assert plan["schema"] == "ltx-movie.plan.v1" and plan["panels"] == 3
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert list(checks) == ["schema", "story_id", "mode", "panels", "checked_at", "source",
                            "round", "hard", "advisory", "scores", "verdict", "stop_reason",
                            "rounds", "best_round", "judge"]
    assert checks["source"] == "robust" and checks["best_round"] == 1 and checks["judge"] is None
    assert checks["rounds"] == [
        {"round": 0, "hard": 0, "advisory": 0, "scores": {"continuity": 6, "story": 6,
                                                          "renderability": 6},
         "verdict": "revise"},
        {"round": 1, "hard": 0, "advisory": 0, "scores": {"continuity": 8, "story": 8,
                                                          "renderability": 8},
         "verdict": "ok"}]
    assert sorted(os.listdir(_rounds(ctx, 0))) == [
        "panel_01_prompt_1.txt", "panel_01_reply_1.txt", "panel_02_prompt_1.txt",
        "panel_02_reply_1.txt", "panel_03_prompt_1.txt", "panel_03_reply_1.txt", "parts.json",
        "plan.json", "plan_prompt.txt", "plan_reply_1.txt", "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == [
        "critic.json", "critic_prompt_1.txt", "critic_reply_1.txt", "parts.json", "plan.json",
        "story.md", "story_checks.json"]
    assert sorted(os.listdir(_rounds(ctx, 2))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert (round1["round"], round1["stop_reason"], round1["best_round"], round1["rounds"]) == (
        1, None, None, [])
    run_doc = _read_json(os.path.join(_rounds(ctx), "run.json"))
    assert [c["stage"] for c in run_doc["calls"]] == ["plan", "panel", "panel", "panel",
                                                      "critic", "critic"]
    assert run_doc["calls"][4]["route"] == "local" and run_doc["exit"] == 0
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: It rained on.\n" in f.read()


def test_rst43_exit_2_message(ws, tmp_path, monkeypatch, capsys):
    shout3 = SHOUT2.replace("quay", "lane")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)],
        p3=[_shouting("chained", 3, shout3), _shouting("chained", 3, shout3)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert capsys.readouterr().err == (
        "Error: story.md has 2 hard violation(s) after the critic rounds (best round 1 of 1):\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n"
        "  - panel 3: N7 dialogue and text: Motion: says 'shouts'\n"
        "story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to fix "
        "the violations above and rerun: story.md already exists, so Phase 1 re-checks it "
        "instead of regenerating it (pass --force-story to regenerate).\n" % ctx.story_dir)
    for name in ("plan.json", "story.md", "story_checks.json"):
        assert os.path.exists(os.path.join(ctx.story_dir, name))
    assert [h["id"] for h in _read_json(os.path.join(ctx.story_dir,
                                                     "story_checks.json"))["hard"]] == ["N7", "N7"]


def test_rst55b_p13_forces_plan_call_2(ws, tmp_path, monkeypatch, story_env):
    seu.ronin(story_env["lib"])
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the ronin"
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        seu.answer(bad), seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0 and [r["stage"] for r in log][:2] == ["plan", "plan"]
    assert ("- plan: P13 undeclared character: c2's phrase names library character ronin by its "
            "referring phrase 'the ronin'") in log[1]["argv"][-1]


def test_rst58_a_patch_that_names_an_undeclared_character_loses(ws, tmp_path, monkeypatch,
                                                                 story_env):
    seu.ronin(story_env["lib"])
    patch = _motion_patch(2, "The courier waves to the ronin by the crates and pedals on along "
                             "the quay.")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[
        seu.answer(seu.critic_json((8, 8, 8), "revise", [patch])),
        seu.answer(seu.critic_json((9, 9, 9)))])
    assert rc == 0
    assert _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))["applied"] == [patch]
    round1 = _read_json(os.path.join(_rounds(ctx, 1), "story_checks.json"))
    assert "N15" in [h["id"] for h in round1["hard"]]
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["best_round"], checks["stop_reason"]) == (0, "plateau")


def _judge_env(monkeypatch, tmp_path, reply):
    log = os.path.join(str(tmp_path), "judge_log.jsonl")
    monkeypatch.setenv("FAKE_JUDGE_REPLY", json.dumps(reply))
    monkeypatch.setenv("FAKE_JUDGE_LOG", log)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    return log


def test_rst38_judge_gate(tmp_path, monkeypatch, capsys):
    ws = seu.make_ws(tmp_path, fake_judge=True)
    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json((8, 9, 8)))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, goal="quiet suspense",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "ok", "detail": "min score 8",
                     "scores": {"continuity": 8, "story": 9, "renderability": 8},
                     "min_score": 8, "applied": False}
    argv = seu.agent_log(judge_log)[0]["argv"]
    assert argv == ["--story-md", os.path.join(_rounds(ctx, 0), "story.md"), "--patches",
                    "--goal", "quiet suspense"]
    assert sorted(os.listdir(_rounds(ctx, 1))) == ["critic.json", "critic_prompt_1.txt",
                                                   "critic_reply_1.txt"]

    _judge_env(monkeypatch, tmp_path, seu.critic_json((5, 7, 7), "revise",
                                                      [_narration_patch(2, "The judge's line.")]))
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s2", critic=[
        seu.answer(seu.critic_json((7, 7, 8))), seu.answer(seu.critic_json((8, 8, 8)))])
    assert rc == 0
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["judge"]["applied"] is True and checks["judge"]["min_score"] == 5
    assert checks["best_round"] == 1
    critic1 = _read_json(os.path.join(_rounds(ctx, 1), "critic.json"))
    assert critic1["route"] is None and critic1["reply"]["scores"]["continuity"] == 5
    assert os.path.exists(os.path.join(_rounds(ctx, 1), "judgment.patches.json"))
    assert os.path.exists(os.path.join(_rounds(ctx, 2), "critic.json"))
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert "Narration: The judge's line.\n" in f.read()

    _judge_env(monkeypatch, tmp_path, {"exit": 1})
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s3",
                            critic=[seu.answer(seu.critic_json((7, 7, 8)))])
    assert rc == 0
    assert "Warning: judge-story failed (exit 1); keeping the critic's best round\n" in (
        capsys.readouterr().out)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert (judge["status"], judge["detail"], judge["applied"]) == ("error", "exit 1", False)

    judge_log = _judge_env(monkeypatch, tmp_path, seu.critic_json())
    os.remove(judge_log) if os.path.exists(judge_log) else None
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, judge=True, story_id="s4", panel=_panel_script(
        "chained", 3, p2=[_shouting("chained", 2, SHOUT2), _shouting("chained", 2, SHOUT2)]),
        critic=[{"answer": "x"}] * 4)
    assert rc == 2 and not os.path.exists(judge_log)
    judge = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["judge"]
    assert judge == {"status": "skipped", "detail": "best round has hard violations",
                     "scores": None, "min_score": None, "applied": False}


def test_story_focus_1_a_non_ascii_phrase_is_repaired_or_reported(ws, tmp_path, monkeypatch,
                                                                    capsys):
    bad = seu.plan_json("chained", 3)
    bad["cast"][1]["phrase"] = "the café owner"
    p3 = ("plan: P3 cast entry: c2's phrase word 'café' may contain only letters, digits, "
          "apostrophes and hyphens (phrase 'the café owner')")
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, plan=[
        seu.answer(bad), seu.answer(seu.plan_json("chained", 3))],
        critic=[seu.answer(seu.critic_json())])
    assert rc == 0 and ("- " + p3) in log[1]["argv"][-1]
    capsys.readouterr()
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, story_id="s2",
                            plan=[seu.answer(bad), seu.answer(bad)], critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - %s\n" % p3 in capsys.readouterr().err


def test_story_focus_2_a_one_panel_story(ws, tmp_path, monkeypatch):
    rc, advisories, ctx, log = _run(ws, tmp_path, monkeypatch, n=1,
                                    critic=[seu.answer(seu.critic_json())])
    assert (rc, advisories) == (0, [])
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert [b["arc"] for b in plan["beats"]] == ["climax"]
    with open(os.path.join(ctx.story_dir, "story.md")) as f:
        assert f.read().count("## Panel ") == 1
    assert "use climax." in log[0]["argv"][-1]


def test_story_focus_3_ctrl_c_during_a_run_keeps_story_md(ws, tmp_path, monkeypatch):
    story_dir = os.path.join(ws, "generated", "stories", "s1")
    os.makedirs(story_dir)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("OLD")
    real = se.run_agent

    def interrupted(ctx, prompt, **kwargs):
        if prompt.startswith("You are writing panel 2 "):
            raise KeyboardInterrupt
        return real(ctx, prompt, **kwargs)

    monkeypatch.setattr(se, "run_agent", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _run(ws, tmp_path, monkeypatch)
    with open(os.path.join(story_dir, "story.md")) as f:
        assert f.read() == "OLD"
    rounds = os.path.join(story_dir, "story_rounds")
    assert os.path.exists(os.path.join(rounds, "round_0", "panel_01_reply_1.txt"))
    assert _read_json(os.path.join(rounds, "run.json"))["exit"] is None
    monkeypatch.setattr(se, "run_agent", real)
    rc, _a, ctx, log = _run(ws, tmp_path, monkeypatch, critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert len([n for n in os.listdir(story_dir) if n.startswith("story_rounds-")]) == 1
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
17 failed, 35 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst10_plan_retry_and_fatal_plan
FAILED tests/test_story_engine.py::test_rst11_short_plan_is_fatal
FAILED tests/test_story_engine.py::test_rst17b_invalid_panel_retried_once_never_three_times
FAILED tests/test_story_engine.py::test_rst26b_critic_retry_and_code_only_round
FAILED tests/test_story_engine.py::test_rst33_stop_passed
FAILED tests/test_story_engine.py::test_rst34_stop_plateau
FAILED tests/test_story_engine.py::test_rst35_stop_max_rounds
FAILED tests/test_story_engine.py::test_rst36_ranking
FAILED tests/test_story_engine.py::test_rst37_budgets_and_the_wall_clock
FAILED tests/test_story_engine.py::test_rst39_outputs_and_layout
FAILED tests/test_story_engine.py::test_rst43_exit_2_message
FAILED tests/test_story_engine.py::test_rst55b_p13_forces_plan_call_2
FAILED tests/test_story_engine.py::test_rst58_a_patch_that_names_an_undeclared_character_loses
FAILED tests/test_story_engine.py::test_rst38_judge_gate
FAILED tests/test_story_engine.py::test_story_focus_1_a_non_ascii_phrase_is_repaired_or_reported
FAILED tests/test_story_engine.py::test_story_focus_2_a_one_panel_story
FAILED tests/test_story_engine.py::test_story_focus_3_ctrl_c_during_a_run_keeps_story_md
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# The run: plan calls (RS8), panel calls (RS13), the round controller (RS21), ranking (RS22),
# budgets and the wall clock (RS23), outputs (RS25-RS27)
# ---------------------------------------------------------------------------

WRITER_CHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "S4", "S5", "S7",
                    "S8", "S10", "S11")


def _unused_dir(path):
    """bin/ltx-movie's _unused_path for a directory path (no extension)."""
    candidate, k = path, 2
    while os.path.lexists(candidate):
        candidate = "%s-%d" % (path, k)
        k += 1
    return candidate


def _reply_text(status, answer):
    return answer if answer is not None else "<no answer: %s>" % status


def _scores_of(states, i):
    """The scores of states[i], else of its nearest scored ancestor, else None (RS22)."""
    for j in range(i, -1, -1):
        if states[j]["scores"]:
            return states[j]["scores"]
    return None


def _key(states, i):
    scores = _scores_of(states, i)
    low = min(scores.values()) if scores else 0
    total = sum(scores.values()) if scores else 0
    return (len(states[i]["hard"]), -low, -total)


def better(states, a, b):
    """True when states[a] is strictly better than states[b] (RS21)."""
    return _key(states, a) < _key(states, b)


def best_round(states):
    """The index of the state with the smallest (hard, -min, -total, -round) (RS22)."""
    return min(range(len(states)), key=lambda i: _key(states, i) + (-i,))


def _checks_doc(ctx, state, source="robust"):
    return {"schema": CHECKS_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
            "panels": ctx.panels, "checked_at": _utc(), "source": source,
            "round": state["round"] if source == "robust" else None,
            "hard": [parse_violation(m) for m in state["hard"]],
            "advisory": [parse_violation(m) for m in state["advisory"]],
            "scores": state.get("scores"), "verdict": state.get("verdict"), "stop_reason": None,
            "rounds": [], "best_round": None, "judge": None}


class _Run(object):
    """One robust Phase 1 run: budgets, files, run.json and the states of every round."""

    def __init__(self, ctx, no_stills_rules):
        self.ctx = ctx
        self.rules = no_stills_rules
        self.start = _now()
        self.cap = wall_clock_cap(ctx.panels)
        self.rounds_dir = os.path.join(ctx.story_dir, "story_rounds")
        self.agent_calls = 0
        self.panel_calls = dict((k, 0) for k in range(1, ctx.panels + 1))
        self.time_up = False
        self.shape = []
        self.states = []
        self.doc = {"schema": RUN_SCHEMA, "story_id": ctx.story_id, "mode": ctx.mode,
                    "panels": ctx.panels, "started_at": _utc(), "finished_at": None,
                    "budgets": {"plan_calls": PLAN_MAX_CALLS, "panel_calls": PANEL_MAX_CALLS,
                                "critic_rounds": CRITIC_MAX_ROUNDS,
                                "critic_calls_per_round": CRITIC_CALLS_PER_ROUND,
                                "max_patches": MAX_PATCHES, "wall_clock_s": self.cap},
                    "calls": [], "stop_reason": None, "best_round": None, "exit": None}
        compatible = compatible_entries(ctx)
        self.compatible_by_id = dict((e["id"], e) for e in compatible)
        self.catalog_by_id = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
        self.catalog_lines = ([catalog_line(e) for e in compatible if e["target"] == "video"]
                              if lora_patches_allowed(ctx) else None)
        self.compatible = compatible

    def expired(self):
        return _now() - self.start >= self.cap

    def round_dir(self, r):
        path = os.path.join(self.rounds_dir, "round_%d" % r)
        os.makedirs(path, exist_ok=True)
        return path

    def write_run(self):
        _write_json(os.path.join(self.rounds_dir, "run.json"), self.doc)

    def record(self, stage, panel, rnd, attempt, route, status, started):
        self.doc["calls"].append({"stage": stage, "panel": panel, "round": rnd,
                                  "attempt": attempt, "route": route, "status": status,
                                  "seconds": round(_now() - started, 1)})
        self.write_run()

    def agent(self, prompt, max_tokens, timeout, image=None):
        preflight = self.agent_calls > 0
        self.agent_calls += 1
        return run_agent(self.ctx, prompt, max_tokens=max_tokens, timeout=timeout, image=image,
                         preflight_done=preflight)

    def round0_timeout(self):
        print("Error: story generation exceeded the wall-clock cap of %ds before every panel was "
              "written; partial work is kept in %s" % (self.cap, self.round_dir(0)),
              file=sys.stderr)
        return self.finish(1)

    def finish(self, code):
        self.doc["finished_at"] = _utc()
        self.doc["exit"] = code
        self.write_run()
        return code

    # -- plan ------------------------------------------------------------------------------

    def plan_round(self):
        ctx = self.ctx
        rdir = self.round_dir(0)
        prompt = build_plan_prompt(ctx, self.compatible, ctx.pinned)
        _write_text(os.path.join(rdir, "plan_prompt.txt"), prompt)
        text, found, problems = prompt, None, []
        for attempt in range(1, PLAN_MAX_CALLS + 1):
            if self.expired():
                return None, "timeout"
            print("plan: call %d of %d" % (attempt, PLAN_MAX_CALLS))
            started = _now()
            status, answer = self.agent(text, plan_max_tokens(ctx.panels),
                                        plan_timeout(ctx.panels), image=ctx.seed_agent_image)
            self.record("plan", None, 0, attempt, None, status, started)
            _write_text(os.path.join(rdir, "plan_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            raw = extract_json(answer)
            if raw is None:
                problems = ["the reply is not one JSON object"]
            else:
                plan, shape = normalize_plan(ctx, raw)
                hard = (plan_checks(ctx, plan, shape)[0]
                        + lora_checks(ctx, plan, self.compatible_by_id, self.catalog_by_id)[0])
                found = (plan, shape, hard)
                problems = hard
            if not problems:
                break
            text = (prompt + "\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n"
                    + "\n".join(listed(["- " + m for m in problems]))
                    + "\nPrevious reply:\n"
                    + (answer[:20000] if answer is not None else "<no answer: %s>" % status)
                    + "\n\nReply with the complete corrected JSON object only.")
        return found, None

    # -- panels ----------------------------------------------------------------------------

    def panel_call(self, plan, parts, k, rnd, fix):
        """(valid parts or None) after one panel call; the caller checks the budget."""
        ctx = self.ctx
        self.panel_calls[k] += 1
        n = self.panel_calls[k]
        print("panel %d/%d: call %d" % (k, ctx.panels, n))
        rdir = self.round_dir(rnd)
        prompt = build_panel_prompt(ctx, plan, parts, k, fix=fix, no_stills_rules=self.rules)
        _write_text(os.path.join(rdir, "panel_%02d_prompt_%d.txt" % (k, n)), prompt)
        started = _now()
        image = ctx.seed_agent_image if ctx.mode == "chained" and k == 1 else None
        status, answer = self.agent(prompt, PANEL_MAX_TOKENS, PANEL_TIMEOUT, image=image)
        self.record("panel", k, rnd, n, None, status, started)
        _write_text(os.path.join(rdir, "panel_%02d_reply_%d.txt" % (k, n)),
                    _reply_text(status, answer))
        return parse_panel_reply(ctx, plan, k, answer)

    def regenerate(self, state, k, plan, parts, rnd):
        """("ok", parts_k) | ("failed", None) | ("budget", None) | ("time", None)."""
        if self.panel_calls[k] >= PANEL_MAX_CALLS:
            return "budget", None
        if self.expired():
            self.time_up = True
            return "time", None
        fix = [m for m in state["hard"] + state["advisory"]
               if parse_violation(m)["index"] == k
               and parse_violation(m)["scope"] in ("panel", "beat")]
        if not fix:
            fix = ["this panel's beat was revised; rewrite the panel for the new beat"]
        new = self.panel_call(plan, parts, k, rnd, fix)
        return ("ok", new) if new is not None else ("failed", None)

    # -- states ----------------------------------------------------------------------------

    def make_state(self, rnd, plan, parts):
        ctx = self.ctx
        rdir = self.round_dir(rnd)
        text = assemble(ctx, plan, parts)
        story_md = os.path.join(rdir, "story.md")
        _write_text(story_md, text)
        ph, pa = plan_checks(ctx, plan, self.shape)
        lh, la = lora_checks(ctx, plan, self.compatible_by_id, self.catalog_by_id)
        nh, na = panel_checks(ctx, plan, parts, text, story_md)
        state = {"round": rnd, "plan": plan, "parts": parts, "text": text, "hard": ph + lh + nh,
                 "advisory": pa + la + na, "scores": None, "verdict": None, "dir": rdir}
        _write_json(os.path.join(rdir, "plan.json"), plan)
        _write_json(os.path.join(rdir, "parts.json"), {"panels": [
            dict([("index", k)] + [(key, p.get(key, "")) for key in writer_keys(ctx.mode, k)])
            for k, p in enumerate(parts, start=1)]})
        _write_json(os.path.join(rdir, "story_checks.json"), _checks_doc(ctx, state))
        print("round %d: %d hard, %d advisory" % (rnd, len(state["hard"]), len(state["advisory"])))
        self.states.append(state)
        return state

    # -- critic rounds ---------------------------------------------------------------------

    def critic_round(self, k, judged, passed_only=False):
        """One RS21 iteration on states[judged]. Returns a stop reason or None (a new state was
        appended)."""
        ctx = self.ctx
        prev = self.states[judged]
        rdir = os.path.join(self.rounds_dir, "round_%d" % k)
        base = build_critic_prompt(prev["plan"], prev["text"], (prev["hard"], prev["advisory"]),
                                   self.catalog_lines)
        prompt, reply, route, calls = base, None, None, 0
        for attempt in range(1, CRITIC_CALLS_PER_ROUND + 1):
            if self.expired():
                if calls == 0:
                    return "time_cap"
                break
            calls += 1
            self.round_dir(k)
            _write_text(os.path.join(rdir, "critic_prompt_%d.txt" % attempt), prompt)
            started = _now()
            self.agent_calls += 1
            status, answer, route = run_critic(ctx, prompt)
            self.record("critic", None, k, attempt, route, status, started)
            _write_text(os.path.join(rdir, "critic_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            reply = parse_critic(answer)
            if reply is not None:
                break
            prompt = base + CRITIC_RETRY_SUFFIX
        critic = {"route": route, "calls": calls, "reply": reply, "applied": [], "rejected": []}
        critic_path = os.path.join(rdir, "critic.json")
        if reply is not None:
            prev["scores"], prev["verdict"] = reply["scores"], reply["verdict"]
            scores = reply["scores"]

            def line(applied, rejected):
                print("critic round %d (%s): continuity=%d story=%d renderability=%d verdict=%s; "
                      "%d patch(es): %d applied, %d rejected"
                      % (k, route, scores["continuity"], scores["story"],
                         scores["renderability"], reply["verdict"], len(reply["patches"]),
                         applied, rejected))

            if (not prev["hard"] and reply["verdict"] == "ok"
                    and min(scores.values()) >= MIN_OK_SCORE):
                _write_json(critic_path, critic)
                line(0, 0)
                return "passed"
            if not passed_only and judged >= 1 and not better(self.states, judged, judged - 1):
                _write_json(critic_path, critic)
                line(0, 0)
                return "plateau"
            new, applied, rejected, _regen = apply_patches(
                ctx, {"plan": prev["plan"], "parts": prev["parts"]}, reply["patches"],
                regen=lambda kk, plan, parts: self.regenerate(prev, kk, plan, parts, k))
            critic["applied"], critic["rejected"] = applied, rejected
            _write_json(critic_path, critic)
            line(len(applied), len(rejected))
            self.make_state(k, new["plan"], new["parts"])
            return None
        print("critic round %d: no valid reply after %d call(s); code-only round" % (k, calls))
        _write_json(critic_path, critic)
        if (not passed_only and judged >= 1
                and len(prev["hard"]) >= len(self.states[judged - 1]["hard"])):
            return "plateau"
        parts = copy.deepcopy(prev["parts"])
        plan = copy.deepcopy(prev["plan"])
        for kk in range(1, ctx.panels + 1):
            mine = [m for m in prev["hard"] if parse_violation(m)["scope"] == "panel"
                    and parse_violation(m)["index"] == kk
                    and parse_violation(m)["id"] in WRITER_CHECK_IDS]
            if not mine or self.panel_calls[kk] >= PANEL_MAX_CALLS:
                continue
            if self.expired():
                self.time_up = True
                break
            new = self.panel_call(plan, parts, kk, k, mine)
            if new is not None:
                parts[kk - 1] = new
        self.make_state(k, plan, parts)
        return None

    # -- judge -----------------------------------------------------------------------------

    def judge_gate(self):
        ctx = self.ctx
        best = self.states[best_round(self.states)]
        if best["hard"]:
            return {"status": "skipped", "detail": "best round has hard violations",
                    "scores": None, "min_score": None, "applied": False}
        if self.expired():
            return {"status": "skipped", "detail": "wall-clock cap reached", "scores": None,
                    "min_score": None, "applied": False}
        started = _now()
        status, detail, reply = run_judge(ctx, best["dir"])
        self.record("judge", None, best["round"], 1, None, status, started)
        if status != "ok":
            print("Warning: judge-story failed (%s); keeping the critic's best round" % detail)
            return {"status": "error", "detail": detail, "scores": None, "min_score": None,
                    "applied": False}
        low = min(reply["scores"].values())
        judge = {"status": "ok", "detail": "min score %d" % low, "scores": reply["scores"],
                 "min_score": low, "applied": False}
        if low >= JUDGE_MIN_SCORE:
            return judge
        j = len(self.states)
        rdir = self.round_dir(j)
        new, applied, rejected, _regen = apply_patches(
            ctx, {"plan": best["plan"], "parts": best["parts"]}, reply["patches"],
            regen=lambda kk, plan, parts: self.regenerate(best, kk, plan, parts, j),
            lora_allowed=False)
        _write_json(os.path.join(rdir, "judgment.patches.json"), reply)
        _write_json(os.path.join(rdir, "critic.json"), {
            "route": None, "calls": 0, "reply": reply, "applied": applied, "rejected": rejected})
        self.make_state(j, new["plan"], new["parts"])
        if not self.expired():
            self.critic_round(j + 1, j, passed_only=True)
        judge["applied"] = True
        return judge

    # -- the whole run ---------------------------------------------------------------------

    def go(self):
        ctx = self.ctx
        if os.path.lexists(self.rounds_dir):
            os.replace(self.rounds_dir, _unused_dir(os.path.join(
                ctx.story_dir, "story_rounds-%s-%d"
                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))))
        self.round_dir(0)
        self.write_run()
        for warning in catalog_warnings(ctx):
            print(warning)
        found, why = self.plan_round()
        if why == "timeout":
            return self.round0_timeout()
        fatal = ([h for h in found[2] if parse_violation(h)["id"] in ("P1", "P2")]
                 if found else ["the reply is not one JSON object"])
        if fatal:
            calls = len([c for c in self.doc["calls"] if c["stage"] == "plan"])
            print("Error: the story model did not return a usable plan after %d call(s)" % calls,
                  file=sys.stderr)
            for message in fatal:
                print("  - %s" % message, file=sys.stderr)
            print("Raw replies are kept in %s. Rerun the same command to try again."
                  % self.round_dir(0), file=sys.stderr)
            return self.finish(1)
        plan, self.shape, _hard = found
        parts = [empty_parts(ctx.mode, k, plan) for k in range(1, ctx.panels + 1)]
        valid = 0
        for k in range(1, ctx.panels + 1):
            if self.expired():
                return self.round0_timeout()
            new = self.panel_call(plan, parts, k, 0, None)
            if new is None and self.panel_calls[k] < PANEL_MAX_CALLS:
                if self.expired():
                    return self.round0_timeout()
                new = self.panel_call(plan, parts, k, 0,
                                      [unparseable_panel_problem(ctx.mode, k)])
            if new is not None:
                parts[k - 1] = new
                valid += 1
        if not valid:
            print("Error: the story model returned no valid panel in round 0; see %s"
                  % self.round_dir(0), file=sys.stderr)
            return self.finish(1)
        self.make_state(0, plan, parts)
        stop = None
        for k in range(1, CRITIC_MAX_ROUNDS + 1):
            if self.expired():
                stop = "time_cap"
                break
            stop = self.critic_round(k, k - 1)
            if stop:
                break
            if self.time_up:
                stop = "time_cap"
                break
            if k == CRITIC_MAX_ROUNDS:
                stop = "max_rounds"
        judge = self.judge_gate() if ctx.judge else None
        best = best_round(self.states)
        state = self.states[best]
        print("stop: %s; best round %d (%d hard)" % (stop, best, len(state["hard"])))
        doc = _checks_doc(ctx, state)
        doc.update({"stop_reason": stop, "best_round": best, "judge": judge,
                    "rounds": [{"round": s["round"], "hard": len(s["hard"]),
                                "advisory": len(s["advisory"]), "scores": s["scores"],
                                "verdict": s["verdict"]} for s in self.states]})
        _write_json(os.path.join(ctx.story_dir, "plan.json"), state["plan"])
        _write_json(os.path.join(ctx.story_dir, "story_checks.json"), doc)
        _write_text(os.path.join(ctx.story_dir, "story.md"), state["text"])
        self.doc["stop_reason"], self.doc["best_round"] = stop, best
        self.advisories = state["advisory"]
        if not state["hard"]:
            return self.finish(0)
        print("Error: story.md has %d hard violation(s) after the critic rounds (best round %d of "
              "%d):" % (len(state["hard"]), best, len(self.states) - 1), file=sys.stderr)
        for message in state["hard"]:
            print("  - %s" % message, file=sys.stderr)
        print("story.md, plan.json and story_checks.json are saved in %s. Hand-edit story.md to "
              "fix the violations above and rerun: story.md already exists, so Phase 1 re-checks "
              "it instead of regenerating it (pass --force-story to regenerate)." % ctx.story_dir,
              file=sys.stderr)
        return self.finish(2)


def run(ctx, no_stills_rules=""):
    """Generate story.md with the robust engine. Returns (exit code, advisories)."""
    runner = _Run(ctx, no_stills_rules)
    runner.advisories = []
    code = runner.go()
    return code, runner.advisories


def run_judge(ctx, round_dir):
    """("ok", "", reply) or ("error", detail, None) for bin/judge-story --patches on
    <round_dir>/story.md (RS24); reply is {"scores", "verdict", "patches"}."""
    cmd = ([sys.executable, os.path.join(ctx.ws, "bin", "judge-story"),
            "--story-md", os.path.join(round_dir, "story.md"), "--patches"]
           + (["--goal", ctx.goal] if ctx.goal else []))
    try:
        proc = subprocess.run(cmd, cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=JUDGE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "error", "timeout", None
    if proc.returncode != 0:
        return "error", "exit %d" % proc.returncode, None
    try:
        with open(os.path.join(round_dir, "judgment.patches.json"), encoding="utf-8") as f:
            data = json.load(f)
        reply = {"scores": {k: data["scores"][k] for k in SCORE_KEYS},
                 "verdict": data["verdict"], "patches": data["patches"]}
        if not all(_score(v) for v in reply["scores"].values()) or not isinstance(
                reply["patches"], list):
            raise ValueError("invalid judgment.patches.json")
    except Exception as e:
        return "error", " ".join(str(e).split()) or type(e).__name__, None
    return "ok", "", reply
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
52 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: run, round controller, ranking, budgets, judge gate (story RS8, RS13, RS21-RS27)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 10: Re-check of an existing story.md and the plan-free yardstick

Implements RS28 (with N15, RS37). Tests RST44 (the engine half; the bin/ltx-movie path is RST54 in Task 11), RST45, RST56b.

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `story_engine.py`

**Interfaces:**
- Consumes: Task 6's `_field_checks`, `repeat_advisories`, `_order_by_panel`, `undeclared_characters`; Task 5's `lora_checks`, `compatible_entries`, `catalog_warnings`; Task 9's `_checks_doc`; `bin/ltx-movie._validate_story_md` (passed in).
- Produces: In `se`: `RECHECK_IDS`, `PLAN_FREE_IDS`; `load_plan(ctx) -> dict|None`; `story_fields(mode, k, panel) -> [(Label, text)]`; `_read_story(ctx, story_md) -> (text, panels)`; `plan_free_report(story_md, mode, panels, members, legacy_validate, ws=None) -> [str]`; `recheck(ctx, legacy_validate) -> (exit code, advisories)`. In the test module: `_saved_story(ws, monkeypatch, mode="chained", n=3, **kw) -> (ctx, text)`, `_edit_story(ctx, old, new)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst44_recheck_with_plan`, `test_rst45_recheck_without_plan`, `test_rst56b_n15_in_recheck_and_plan_free_report`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST44 (engine), RST45, RST56b: re-check (RS28) -----------------------------------------

def _saved_story(ws, monkeypatch, mode="chained", n=3, **kw):
    """A story.md and plan.json saved in <story_dir> as a run would leave them."""
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, parts, text, _path = _story(ws, mode, n, **kw)
    with open(os.path.join(ctx.story_dir, "story.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return ctx, text


def _edit_story(ctx, old, new):
    path = os.path.join(ctx.story_dir, "story.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert text.count(old) == 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def test_rst44_recheck_with_plan(ws, monkeypatch, tmp_path, capsys):
    log = seu.script_agent(monkeypatch, tmp_path)
    ctx, text = _saved_story(ws, monkeypatch)
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (0, [])
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert (checks["source"], checks["round"], checks["stop_reason"], checks["rounds"],
            checks["hard"]) == ("recheck", None, None, [], [])
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(ctx, "Motion: " + motion, "Motion: The courier yells " + motion[12:])
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (2, [])
    assert capsys.readouterr().err == (
        "Error: story.md fails the story checks:\n"
        "  - panel 2: N7 dialogue and text: Motion: says 'yells'\n"
        "Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
        "regenerate it.\n" % story_md)
    checks = _read_json(os.path.join(ctx.story_dir, "story_checks.json"))
    assert checks["source"] == "recheck" and [h["id"] for h in checks["hard"]] == ["N7"]
    assert seu.agent_log(log) == []
    _edit_story(ctx, "Narration: Every street led down to the water.\n", "Narration:\n")
    se.recheck(ctx, ltx_movie._validate_story_md)
    hard = [h["message"] for h in _read_json(os.path.join(ctx.story_dir, "story_checks.json"))["hard"]]
    assert hard == ["panel 2: missing/empty Narration: field",
                    "panel 2: N7 dialogue and text: Motion: says 'yells'",
                    "panel 2: N11 narration: Narration: is empty"]


def test_rst45_recheck_without_plan(ws, monkeypatch, capsys, story_env):
    ctx, text = _saved_story(ws, monkeypatch)
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    story_md = os.path.join(ctx.story_dir, "story.md")
    _edit_story(ctx, "Narration: The rain had not stopped since dawn.\n", "")
    assert se.recheck(ctx, ltx_movie._validate_story_md) == (1, [])
    assert capsys.readouterr().err == (
        "Error: story.md failed validation:\n  - panel 1: missing/empty Narration: field\n"
        "Hand-edit %s to fix the violations above and rerun; story.md already exists so Phase 1 "
        "will be skipped next time (pass --force-story to regenerate it instead).\n" % story_md)
    assert not os.path.exists(os.path.join(ctx.story_dir, "story_checks.json"))
    short, _t = _saved_story(ws, monkeypatch, n=3, ctx_kw={"story_id": "s9"})
    os.remove(os.path.join(short.story_dir, "plan.json"))
    motion = seu.panel_json("chained", 2)["motion"]
    _edit_story(short, "Motion: " + motion, "Motion: The courier pedals on.")
    assert se.recheck(short, ltx_movie._validate_story_md) == (0, [])
    shots, _t = _saved_story(ws, monkeypatch, mode="shots", ctx_kw={"story_id": "s8"})
    os.remove(os.path.join(shots.story_dir, "plan.json"))
    _edit_story(shots, "Motion: The courier steps forward onto the wet stones.",
                "Motion: The courier steps forward then turns.")
    assert se.recheck(shots, ltx_movie._validate_story_md) == (2, [])
    err = capsys.readouterr().err
    assert err.startswith("Error: story.md breaks the shot rules:\n")
    assert "  - panel 3: S5 one action: Motion: chains actions with 'then'\n" in err
    assert err.endswith("Hand-edit %s to fix the violations above and rerun, or pass "
                        "--force-story to have the story model write a new one.\n"
                        % os.path.join(shots.story_dir, "story.md"))


def test_rst56b_n15_in_recheck_and_plan_free_report(ws, monkeypatch, capsys, story_env):
    seu.ronin(story_env["lib"])
    ctx, text = _saved_story(ws, monkeypatch, mode="shots")
    _edit_story(ctx, "Narration: He knew the letter could not wait.",
                "Narration: Ronin knew the letter could not wait.")
    assert se.recheck(ctx, ltx_movie._validate_story_md)[0] == 2
    message = ("panel 3: N15 undeclared character: Narration: names library character ronin by "
               "its name 'Ronin'; library characters appear only when declared with --character "
               "ronin")
    assert "  - %s\n" % message in capsys.readouterr().err
    story_md = os.path.join(ctx.story_dir, "story.md")
    assert se.plan_free_report(story_md, "shots", 3, [], ltx_movie._validate_story_md,
                               ws=ws) == [message]
    members = se._character_lib(WS).resolve_cast([(None, "ronin")])
    report = se.plan_free_report(story_md, "shots", 3, members, ltx_movie._validate_story_md, ws=ws)
    assert message not in report
    chained, _t = _saved_story(ws, monkeypatch, ctx_kw={"story_id": "s7"})
    path = os.path.join(chained.story_dir, "story.md")
    assert se.plan_free_report(path, "chained", 3, [], ltx_movie._validate_story_md, ws=ws) == []
    assert se.plan_free_report(path, "chained", 4, [], ltx_movie._validate_story_md, ws=ws) == [
        "expected exactly 4 panels, found 3"]
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
3 failed, 52 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst44_recheck_with_plan
FAILED tests/test_story_engine.py::test_rst45_recheck_without_plan
FAILED tests/test_story_engine.py::test_rst56b_n15_in_recheck_and_plan_free_report
```

- [ ] **Step 3: Implement.**

**3.1.** Append to `story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# ---------------------------------------------------------------------------
# Re-check of an existing story.md (RS28) and the plan-free yardstick (RS28, 7.2)
# ---------------------------------------------------------------------------

RECHECK_IDS = ("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15")
PLAN_FREE_IDS = ("N1", "N7", "N8", "N9", "N10", "N11", "N15")
_PLAN_KEYS = ("title", "logline", "cast", "locations", "props", "beats", "loras")


def load_plan(ctx):
    """<story_dir>/plan.json when it is a valid plan for ctx's mode and panel count, else None."""
    try:
        with open(os.path.join(ctx.story_dir, "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    if (not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA
            or plan.get("mode") != ctx.mode or plan.get("panels") != ctx.panels
            or not all(k in plan for k in _PLAN_KEYS)):
        return None
    return plan


def story_fields(mode, k, panel):
    """[(Label, text)] of a parsed story.md panel, the fields RS3 assembles for mode/panel k."""
    if mode == "no_stills":
        labels = ("Prompt", "Narration")
    elif mode == "chained" and k >= 2:
        labels = ("Motion", "Narration")
    else:
        labels = ("Image", "Motion", "Narration")
    return [(label, panel[label.lower()]) for label in labels]


def _read_story(ctx, story_md):
    with open(story_md, encoding="utf-8") as f:
        text = f.read()
    return text, _story_manifest(ctx.ws)._parse_prompts_md(story_md)[1]


def plan_free_report(story_md, mode, panels, members, legacy_validate, ws=None):
    """The hard violations a re-check computes without a plan (RS28; the 7.2 yardstick for both
    engines). ws (default: this file's directory) locates the character library and the
    manifest parser. Prints nothing, writes nothing."""
    ws = ws or os.path.dirname(os.path.realpath(__file__))
    ctx = StoryContext(ws=ws, story_id="", story_dir=os.path.dirname(story_md), mode=mode,
                       panels=panels, seconds="6", narrative="", goal=None, members=members,
                       seed_image=None, seed_agent_image=None, story_model=None,
                       context_window=None, video_model="", auto_lora=False,
                       catalog={"schema_version": 1, "entries": []}, pinned=[], stills_pinned=[],
                       judge=False)
    lib = _character_lib(ws)
    hard = [] if mode == "shots" else list(legacy_validate(story_md, panels, mode == "no_stills"))
    text, parsed = _read_story(ctx, story_md)
    undeclared = undeclared_characters(ctx)
    for k, panel in enumerate(parsed, start=1):
        fields = story_fields(mode, k, panel)
        hard += _field_checks(ctx, lib, None, k, panel["title"], fields, dict(fields),
                              PLAN_FREE_IDS, undeclared)[0]
    if mode == "shots":
        hard += lib.shots_violations(text, parsed, panels, members)
    return hard


def recheck(ctx, legacy_validate):
    """Re-check an existing story.md instead of regenerating it (RS28). Returns (exit code,
    advisories). legacy_validate is bin/ltx-movie's _validate_story_md."""
    story_md = os.path.join(ctx.story_dir, "story.md")
    for warning in catalog_warnings(ctx):
        print(warning)
    lib = _character_lib(ctx.ws)
    plan = load_plan(ctx)
    if plan is None:
        if ctx.mode != "shots":
            violations = legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")
            if violations:
                print("Error: story.md failed validation:", file=sys.stderr)
                for v in violations:
                    print("  - %s" % v, file=sys.stderr)
                print("Hand-edit %s to fix the violations above and rerun; story.md already exists "
                      "so Phase 1 will be skipped next time (pass --force-story to regenerate it "
                      "instead)." % story_md, file=sys.stderr)
                return 1, []
            return 0, []
        try:
            text, parsed = _read_story(ctx, story_md)
            violations = lib.shots_violations(text, parsed, ctx.panels, ctx.members)
            advisories = lib.shots_advisories(parsed, ctx.members)
        except OSError as e:
            violations, advisories = ["story: cannot read story.md: %s" % e], []
        if violations:
            print("Error: story.md breaks the shot rules:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
                  "have the story model write a new one." % story_md, file=sys.stderr)
            return 2, []
        return 0, advisories
    hard = ([] if ctx.mode == "shots"
            else list(legacy_validate(story_md, ctx.panels, ctx.mode == "no_stills")))
    advisory = []
    text, parsed = _read_story(ctx, story_md)
    undeclared = undeclared_characters(ctx)
    writers_by_panel = []
    for k, panel in enumerate(parsed, start=1):
        fields = story_fields(ctx.mode, k, panel)
        writers_by_panel.append(dict(fields))
        h, a = _field_checks(ctx, lib, plan, k, panel["title"], fields, dict(fields),
                             RECHECK_IDS, undeclared)
        hard += h
        advisory += a
    advisory = _order_by_panel(advisory + repeat_advisories(ctx, lib, plan, writers_by_panel))
    if ctx.mode == "shots":
        hard += lib.shots_violations(text, parsed, ctx.panels, ctx.members)
        advisory += lib.shots_advisories(parsed, ctx.members)
    if ctx.auto_lora:
        compatible = dict((e["id"], e) for e in compatible_entries(ctx))
        catalog = dict((e["id"], e) for e in ctx.catalog.get("entries", []))
        lh, la = lora_checks(ctx, plan, compatible, catalog)
        hard += lh
        advisory += la
    _write_json(os.path.join(ctx.story_dir, "story_checks.json"),
                _checks_doc(ctx, {"hard": hard, "advisory": advisory}, source="recheck"))
    if hard:
        print("Error: story.md fails the story checks:", file=sys.stderr)
        for message in hard:
            print("  - %s" % message, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to "
              "regenerate it." % story_md, file=sys.stderr)
        return 2, advisory
    return 0, advisory
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
55 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py39-ok
python3 -m py_compile tests/test_story_engine.py story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py story_engine.py
git diff --cached --name-only
git commit -m "story_engine: re-check and the plan-free report (story RS28, RS37)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 11: bin/ltx-movie: the four flags, engine resolution, the robust Phase 1, review, the stale-plan move

Implements RS2, RS25 (`story_prompt.txt`), RS29, RS31 (the stale `plan.json` move), RS34 (guarded), RS35, RS36, LC12 (pins). Also the `movie_ws` fixture migration of `tests/test_shots_mode.py` (Plan decision 18). Tests RST2, RST3, RST4, RST40, RST42, RST46, RST50, RST51, RST52, RST53, RST54, LCT13, Review Focus 5.

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `tests/test_lora_catalog.py`
- Modify: `tests/test_shots_mode.py`
- Modify: `bin/ltx-movie`

**Interfaces:**
- Consumes: `story_engine.StoryContext`, `run`, `recheck` (Tasks 4, 9, 10); `lora_catalog.catalog_path`, `load_catalog`, `CatalogError` (Task 2).
- Produces: In `bin/ltx-movie`: `GOAL_MAX_CHARS`, `_parse_goal(text)`, the parser flags `--story-legacy`, `--no-auto-lora`, `--judge`, `--goal`; `_story_engine()`, `_lora_catalog()`; `_resolve_story_engine(args) -> 0|2` (sets `args.story_engine`, `args.story_catalog`); `_story_mode(args)`; `_story_pins(args, catalog) -> [pin]`; `_story_context(args, dry_run=False) -> StoryContext`; `_no_stills_rules() -> str`; `_phase1_robust(args) -> int`. In `tests/test_story_engine.py`: `LEGACY_STORY`, `NARRATIVE`, the `movie` fixture, `_LegacyPopen`, `_engine_args(*argv)`, `_main_run(tmp_path, monkeypatch, argv, plan=None, panel=None, critic=())`. In `tests/test_lora_catalog.py`: `ltx_movie` (loaded as `ltx_movie_for_lora_catalog`), `_movie_args(*argv)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst2_flags_and_parse_goal`, `test_rst3_resolve_story_engine`, `test_rst4_direct_phase1_story_call_stays_legacy`, `test_rst40_legacy_phase1_is_byte_identical`, `test_rst42_legacy_moves_a_stale_plan_aside`, `test_rst46_review_gate`, `test_rst50_source_literal_counts`, `test_rst51_e2e_chained`, `test_rst52_e2e_no_stills_with_a_setting_patch`, `test_rst53_e2e_shots_with_two_characters`, `test_rst54_e2e_hard_fail_then_hand_edit_and_recheck`, `test_story_focus_5_non_ascii_text_round_trips`, `test_lct13_pins`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST2-RST4, RST39b, RST40, RST42, RST46, RST50-RST54: bin/ltx-movie (RS2, RS25, RS29,
# RS31, RS34, RS35) -------------------------------------------------------------------------

LEGACY_STORY = """# Legacy

## Panel 1 — One
Image: A courier stands on a wet quay.
Motion: The courier pushes off.
Narration: It rained.

## Panel 2 — Two
Motion: The courier pedals on.
Narration: It rained more.

## Panel 3 — Three
Motion: The courier arrives.
Narration: It stopped.
"""
NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."


@pytest.fixture
def movie(tmp_path, monkeypatch):
    """A temp workspace with the fake agent; ltx_movie.WS points at it; no sudo check."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie, "_check_sudo_and_start_keepalive", lambda: None)
    return ws


class _LegacyPopen(object):
    """Records each Popen argv; communicate() writes LEGACY_STORY to the story.md named by the
    story id in the prompt and exits 0."""
    calls = []

    def __init__(self, cmd, **kwargs):
        _LegacyPopen.calls.append(list(cmd))
        self.cmd = cmd
        self.returncode = 0

    def communicate(self, timeout=None):
        story_id = re.search(r'\(story-id "([^"]+)"\)', self.cmd[-1]).group(1)
        with open(os.path.join(ltx_movie.WS, "generated", "stories", story_id, "story.md"),
                  "w", encoding="utf-8") as f:
            f.write(LEGACY_STORY)
        return "", None


def test_rst2_flags_and_parse_goal():
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"])
    assert (args.story_legacy, args.no_auto_lora, args.judge, args.goal) == (False, False, False,
                                                                             None)
    judge_story = importlib.machinery.SourceFileLoader(
        "judge_story_for_rst2", os.path.join(WS, "bin", "judge-story")).load_module()
    for text in ("a quiet drama.", "", "two\nlines", "x" * 301, "realistic action", "   "):
        outcomes = []
        for parse in (ltx_movie._parse_goal, judge_story.parse_goal):
            try:
                outcomes.append(("ok", parse(text)))
            except Exception as e:
                outcomes.append((type(e).__name__, str(e)))
        assert outcomes[0] == outcomes[1], text
    assert ltx_movie._parse_goal(" a quiet drama. ") == "a quiet drama"
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x", "--story-legacy",
                                                "--no-auto-lora", "--judge", "--goal", "g."])
    assert (args.story_legacy, args.no_auto_lora, args.judge, args.goal) == (True, True, True, "g")


def _engine_args(*argv):
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"] + list(argv))
    return args, ltx_movie._resolve_story_engine(args)


def test_rst3_resolve_story_engine(tmp_path, capsys, monkeypatch, story_env):
    override = str(tmp_path / "override.txt")
    with open(override, "w") as f:
        f.write("P")
    for extra, reason in ((["--story-legacy"], "--story-legacy"),
                          (["--story-prompt-override", override], "--story-prompt-override")):
        for flag in (["--judge"], ["--no-auto-lora"], ["--goal", "g"]):
            _args, rc = _engine_args(*(extra + flag))
            assert rc == 2
            assert capsys.readouterr().err == (
                "Error: %s needs the default story engine; it cannot be combined with %s\n"
                % (flag[0], reason))
        args, rc = _engine_args(*extra)
        assert (rc, args.story_engine, args.story_catalog) == (0, "legacy", None)
    _args, rc = _engine_args("--judge")
    assert rc == 2 and capsys.readouterr().err == (
        "Error: --judge needs ANTHROPIC_API_KEY for bin/judge-story; export it or drop --judge\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    args, rc = _engine_args("--judge")
    assert (rc, args.story_engine) == (0, "robust")
    args, rc = _engine_args()
    assert (rc, args.story_engine, args.story_catalog) == (0, "robust", {"schema_version": 1,
                                                                         "entries": []})
    path = os.path.join(story_env["catalog"], "catalog.json")
    with open(path, "w") as f:
        f.write("[]")
    _args, rc = _engine_args()
    assert rc == 2 and capsys.readouterr().err == (
        "Error: invalid LoRA catalog %s: top level: must be an object with exactly the keys "
        "entries, schema_version; run bin/lora-catalog verify\n" % path)
    args, rc = _engine_args("--no-auto-lora")
    assert (rc, args.story_catalog) == (0, {"schema_version": 1, "entries": []})


def test_rst4_direct_phase1_story_call_stays_legacy(movie, monkeypatch):
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    os.makedirs(os.path.join(movie, "generated", "stories", "d1"))
    args = ltx_movie.build_parser().parse_args([NARRATIVE, "--story-id", "d1", "--panels", "3",
                                                "--no-review"])
    assert not hasattr(args, "story_engine")
    assert ltx_movie.phase1_story(args) == 0
    assert _LegacyPopen.calls[0][4:8] == ["--max-tokens", "4096", "--max-rounds", "4"]


def test_rst40_legacy_phase1_is_byte_identical(movie, monkeypatch, tmp_path, story_env, capsys):
    from PIL import Image
    with open(os.path.join(story_env["catalog"], "catalog.json"), "w") as f:
        f.write("[]")
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (704, 448), (10, 20, 30)).save(seed)
    head = [sys.executable, os.path.join(movie, "bin", "qwen-agent"), "--workspace", movie,
            "--max-tokens", "4096", "--max-rounds", "4", "--request-timeout", "600"]
    cases = [
        ("l1", [], [], False),
        ("l2", ["--force-story"], ["--danger-auto-approve"], False),
        ("l3", ["--story-model", "andrevp/Qwen", "--story-context-window", "262144"],
         ["--model", "andrevp/Qwen", "--context-window", "262144"], False),
        ("l4", ["--seed-image", seed],
         ["--image", os.path.join(movie, "generated", "stories", "l4", "seed_downscaled.png")],
         True),
    ]
    for story_id, flags, middle, seeded in cases:
        argv = [NARRATIVE, "--story-id", story_id, "--panels", "3", "--story-legacy",
                "--story-only", "--no-review"] + flags
        assert ltx_movie.main(argv) == 0, capsys.readouterr().err
        prompt = ltx_movie.build_story_prompt(NARRATIVE, story_id, 3, False, seeded, seconds="6")
        assert _LegacyPopen.calls[-1] == head + middle + ["--user-prompt", prompt]
        with open(os.path.join(movie, "generated", "stories", story_id, "story_prompt.txt")) as f:
            assert f.read() == prompt
    assert len(_LegacyPopen.calls) == 4


def test_rst42_legacy_moves_a_stale_plan_aside(movie, monkeypatch, capsys):
    _LegacyPopen.calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _LegacyPopen)
    story_dir = os.path.join(movie, "generated", "stories", "m1")
    os.makedirs(story_dir)
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        f.write("{}")
    assert ltx_movie.main([NARRATIVE, "--story-id", "m1", "--panels", "3", "--story-legacy",
                           "--dry-run", "--no-review"]) == 0
    assert os.path.exists(os.path.join(story_dir, "plan.json"))
    capsys.readouterr()
    assert ltx_movie.main([NARRATIVE, "--story-id", "m1", "--panels", "3", "--story-legacy",
                           "--story-only", "--no-review"]) == 0
    moved = [n for n in os.listdir(story_dir) if n.startswith("plan.stale-")]
    assert len(moved) == 1 and re.fullmatch(r"plan\.stale-\d{8}T\d{6}Z-\d+\.json", moved[0])
    assert not os.path.exists(os.path.join(story_dir, "plan.json"))
    assert ("note: moved the robust engine's plan.json aside to %s; this story.md is written by "
            "--story-legacy\n" % os.path.join(story_dir, moved[0])) in capsys.readouterr().out


def test_rst46_review_gate(ws, monkeypatch, capsys, story_env):
    ctx, text = _saved_story(ws, monkeypatch, part_mut=lambda parts: parts[1].update(
        narration="It rained. It poured."))
    members = _cast_members(story_env, "kyra")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))
    for no_review in (False, True):
        args = ltx_movie.build_parser().parse_args(
            [NARRATIVE, "--story-id", "s1", "--panels", "3"] + (["--no-review"] if no_review else []))
        assert ltx_movie._resolve_story_engine(args) == 0
        args.cast_members = members
        assert ltx_movie._phase1_robust(args) == 0
        out = capsys.readouterr().out
        warnings = ("Warning: panel 2: N14 narration form: Narration: is 2 sentences; it should be "
                    "one sentence of 3-30 words\nWarning: story.md does not use cast phrase 'the "
                    "woman in grey'; character kyra gets no LoRA in this story\n")
        note = ("note: %s already exists; re-checking it instead of regenerating it (pass "
                "--force-story to regenerate)\n" % os.path.join(ctx.story_dir, "story.md"))
        if no_review:
            assert out == note + warnings
        else:
            assert out == note + "=== story.md ===\n" + text + "\n" + warnings
    assert prompts == ["Review story.md above. Enter to continue, Ctrl-C to abort: "]


def test_rst50_source_literal_counts():
    with open(os.path.join(WS, "bin", "ltx-movie"), encoding="utf-8") as f:
        movie = f.read()
    with open(os.path.join(WS, "bin", "ltx-story-images"), encoding="utf-8") as f:
        images = f.read()
    counts = [('["--model", args.story_model]', 2),
              ('["--context-window", str(args.story_context_window)]', 2),
              ('"--workspace", WS,', 2), ("_render_flags(args)", 4),
              ('os.path.join(WS, "bin", "ltx-mlx-render")', 4),
              ('cmd += ["--image", args.seed_downscaled_path]', 1),
              ('phase1_cmd += ["--image", paths["seed_downscaled"]]', 1),
              ('\n        cmd += ["--seed-image", args.seed_image]', 1),
              ('phase2_cmd += ["--seed-image", args.seed_image]', 1),
              ('"--glob"', 0), ('"--engine"', 0), ("sudo -S", 0)]
    for literal, count in counts:
        assert movie.count(literal) == count, literal
    for literal, count in (("_compose_prompt(", 3), ('"source": "generated"', 4),
                           ('"source": "seed"', 3), ("_panel_seed(args.seed, i, grounded)", 2)):
        assert images.count(literal) == count, literal
    body = inspect.getsource(ltx_movie.phase2_stills)
    assert "no_stills" not in body


def _main_run(tmp_path, monkeypatch, argv, plan=None, panel=None, critic=()):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan or [], panel=panel or {},
                           critic=list(critic))
    rc = ltx_movie.main(argv)
    return rc, seu.agent_log(log)


def test_rst51_e2e_chained(movie, tmp_path, monkeypatch):
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e1", "--panels", "3", "--story-only",
                         "--no-review", "--force-story"],
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3), critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e1")
    assert ltx_movie._validate_story_md(os.path.join(story_dir, "story.md"), 3) == []
    for name in ("plan.json", "story_checks.json"):
        assert os.path.exists(os.path.join(story_dir, name))
    with open(os.path.join(story_dir, "story_prompt.txt")) as f:
        assert f.read() == ltx_movie.build_story_prompt(NARRATIVE, "e1", 3, False, False,
                                                        seconds="6")
    assert [r["stage"] for r in log] == ["plan", "panel", "panel", "panel", "critic"]
    assert "--skill=analyst" in log[-1]["argv"]
    assert all("--max-rounds" in r["argv"] and r["argv"][r["argv"].index("--max-rounds") + 1] == "1"
               for r in log)


def test_rst52_e2e_no_stills_with_a_setting_patch(movie, tmp_path, monkeypatch):
    setting = ("The setting is a stormy fishing harbour in modern Japan, slick black cobblestones "
               "underfoot, cranes behind, under blue evening light.")
    patch = {"target": "plan", "index": 1, "field": "location.setting", "reason": "r",
             "replacement": setting}
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e2", "--panels", "2", "--no-stills",
                         "--story-only", "--no-review"],
                        plan=[seu.answer(seu.plan_json("no_stills", 2))],
                        panel=_panel_script("no_stills", 2),
                        critic=[seu.answer(seu.critic_json((6, 6, 6), "revise", [patch])),
                                seu.answer(seu.critic_json())])
    assert rc == 0
    story_md = os.path.join(movie, "generated", "stories", "e2", "story.md")
    panels = se._story_manifest(WS)._parse_prompts_md(story_md)[1]
    assert [150 <= len(p["prompt"].split()) <= 220 for p in panels] == [True, True]
    assert all(setting in p["prompt"] for p in panels)
    critic = _read_json(os.path.join(movie, "generated", "stories", "e2", "story_rounds",
                                     "round_1", "critic.json"))
    assert critic["applied"] == [patch]


def test_rst53_e2e_shots_with_two_characters(movie, tmp_path, monkeypatch, story_env):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    cast = [{"id": "c1", "phrase": "the woman in grey", "descriptor": "a woman"},
            {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    raw = seu.plan_json("shots", 4, cast=cast)
    raw["beats"][2]["cast"] = ["c2"]
    raw["beats"][2]["action"] = "the ronin steps out from behind a cedar trunk onto the trail"
    panels = _panel_script("shots", 4, phrase="the woman in grey")
    panels["2"] = [{"answer": "I would rather not"}] + panels["2"]
    panels["3"] = [seu.answer(seu.panel_json("shots", 3, phrase="the ronin"))]
    rc, log = _main_run(tmp_path, monkeypatch,
                        [NARRATIVE, "--story-id", "e3", "--panels", "4", "--shots", "--character",
                         "kyra", "--character", "ronin", "--story-only", "--no-review"],
                        plan=[seu.answer(raw)], panel=panels,
                        critic=[{"answer": "garbage"}, seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "e3")
    plan = _read_json(os.path.join(story_dir, "plan.json"))
    assert plan["cast"][:2] == [
        {"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K, "cast_name": "kyra"},
        {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R, "cast_name": "ronin"}]
    checks = _read_json(os.path.join(story_dir, "story_checks.json"))
    assert checks["hard"] == []
    assert [(r["stage"], r["panel"]) for r in log].count(("panel", 2)) == 2
    assert [r["stage"] for r in log].count("critic") == 2
    with open(os.path.join(story_dir, "story.md")) as f:
        text = f.read()
    lib = se._character_lib(WS)
    members = lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    parsed = se._story_manifest(WS)._parse_prompts_md(os.path.join(story_dir, "story.md"))[1]
    assert lib.shots_violations(text, parsed, 4, members) == []


def test_rst54_e2e_hard_fail_then_hand_edit_and_recheck(movie, tmp_path, monkeypatch, capsys):
    argv = [NARRATIVE, "--story-id", "e4", "--panels", "3", "--story-only", "--no-review"]
    rc, log = _main_run(tmp_path, monkeypatch, argv,
                        plan=[seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3, p2=[_shouting("chained", 2, SHOUT2),
                                                              _shouting("chained", 2, SHOUT2)]),
                        critic=[{"answer": "x"}] * 4)
    assert rc == 2
    assert "  - panel 2: N7 dialogue and text: Motion: says 'shouts'\n" in capsys.readouterr().err
    story_md = os.path.join(movie, "generated", "stories", "e4", "story.md")
    with open(story_md) as f:
        text = f.read()
    with open(story_md, "w") as f:
        f.write(text.replace("Motion: " + SHOUT2,
                             "Motion: " + seu.panel_json("chained", 2)["motion"] + "."))
    rc, again = _main_run(tmp_path, monkeypatch, argv)
    assert rc == 0 and again == []
    assert "re-checking it instead of regenerating it" in capsys.readouterr().out
    assert _read_json(os.path.join(movie, "generated", "stories", "e4",
                                   "story_checks.json"))["source"] == "recheck"


def test_story_focus_5_non_ascii_text_round_trips(movie, tmp_path, monkeypatch):
    narrative = "東京の雨 — a courier's café run through Shinjuku."
    raw = seu.plan_json("chained", 2)
    raw["title"] = "Café 東京"
    rc, log = _main_run(tmp_path, monkeypatch,
                        [narrative, "--story-id", "u1", "--panels", "2", "--story-only",
                         "--no-review"],
                        plan=[seu.answer(raw)], panel=_panel_script("chained", 2),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    story_dir = os.path.join(movie, "generated", "stories", "u1")
    with open(os.path.join(story_dir, "plan.json"), encoding="utf-8") as f:
        text = f.read()
    assert narrative in text and "\\u" not in text
    with open(os.path.join(story_dir, "story.md"), encoding="utf-8") as f:
        assert f.read().startswith("# Café 東京\n")
    assert ("Narrative to adapt:\n" + narrative + "\n") in log[0]["argv"][-1]
```

**1.2.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- LCT13: pins in bin/ltx-movie's story context (LC12) ------------------------------------

ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_lora_catalog", os.path.join(WS, "bin", "ltx-movie")).load_module()


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def test_lct13_pins(tmp_path, story_env):
    files = str(tmp_path / "files")
    fast = seu.lora_file(files, "fast")
    other = seu.lora_file(files, "other")
    seu.make_catalog(story_env["catalog"], [seu.catalog_entry(fast, "fast-motion")])
    args = _movie_args("n", "--story-id", "p1", "--lora", fast + ":0.7", "--lora", other)
    assert ltx_movie._story_context(args).pinned == [
        {"path": fast, "strength": 0.7, "catalog_id": "fast-motion", "kind": "motion"},
        {"path": other, "strength": 1.0, "catalog_id": None, "kind": None}]
    flags = ltx_movie._render_flags(args)
    assert flags[flags.index("--lora"):flags.index("--lora") + 4] == [
        "--lora", fast + ":0.7", "--lora", other + ":1.0"]
    legacy = _movie_args("n", "--story-id", "p1", "--lora", other)
    assert ltx_movie._story_context(legacy).pinned == [
        {"path": other, "strength": 1.0, "catalog_id": None, "kind": None}]
    assert ltx_movie._render_flags(legacy)[16:18] == ["--lora", other]
    assert "--lora" not in ltx_movie._render_flags(_movie_args("n", "--story-id", "p1"))
```

**1.3.** Edit `tests/test_shots_mode.py`: replace this text, which occurs exactly once:

```python
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(ltx_movie, "WS", str(ws))
    return ws
```

with:

```python
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    os.symlink(os.path.join(WS, "story_engine.py"), str(ws / "story_engine.py"))
    os.symlink(os.path.join(WS, "lora_catalog.py"), str(ws / "lora_catalog.py"))
    monkeypatch.setattr(ltx_movie, "WS", str(ws))
    return ws
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_shots_mode.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
10 failed, 57 passed
1 failed, 16 passed
81 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst2_flags_and_parse_goal
FAILED tests/test_story_engine.py::test_rst3_resolve_story_engine
FAILED tests/test_story_engine.py::test_rst40_legacy_phase1_is_byte_identical
FAILED tests/test_story_engine.py::test_rst42_legacy_moves_a_stale_plan_aside
FAILED tests/test_story_engine.py::test_rst46_review_gate
FAILED tests/test_story_engine.py::test_rst51_e2e_chained
FAILED tests/test_story_engine.py::test_rst52_e2e_no_stills_with_a_setting_patch
FAILED tests/test_story_engine.py::test_rst53_e2e_shots_with_two_characters
FAILED tests/test_story_engine.py::test_rst54_e2e_hard_fail_then_hand_edit_and_recheck
FAILED tests/test_story_engine.py::test_story_focus_5_non_ascii_text_round_trips
FAILED tests/test_lora_catalog.py::test_lct13_pins
```

`test_rst4_direct_phase1_story_call_stays_legacy` and `test_rst50_source_literal_counts` pass already: they pin today's behaviour (a direct `phase1_story` call is legacy; the RS34 literal counts), which Step 3 must keep. `tests/test_shots_mode.py` passes before and after: Step 1's fixture edit only adds two symlinks that Step 3 needs.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
loaded by path only when casting or --shots is used, so an uncast run without --shots
never reads it.
```

with:

```python
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
loaded by path only when casting or --shots is used, so an uncast run without --shots
never reads it -- on the --story-legacy path and in every dry run; the default story engine
loads it for its checks.
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into
<story>/redo/<stamp>-<pid>/ so that only they re-render.
"""
```

with:

```python
paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into
<story>/redo/<stamp>-<pid>/ so that only they re-render.

Story engine (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md): by default
Phase 1 asks the story model for a JSON plan and then one panel at a time, assembles story.md
itself, runs deterministic checks and up to three local critic rounds (the fleet analyst skill),
and exits 2 with story.md, plan.json and story_checks.json saved when hard violations remain; a
rerun re-checks the existing story.md. --judge adds bin/judge-story --patches as a final gate;
--story-legacy restores the single-prompt path. The plan may pick catalog LoRAs
(bin/lora-catalog), which Phases 2 and 3 apply per panel; --no-auto-lora turns that off.
"""
```

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def build_parser():
```

with:

```python
GOAL_MAX_CHARS = 300


def _parse_goal(text):
    """argparse type= for --goal: a copy of bin/judge-story's parse_goal (importing bin/judge-story
    would import anthropic). Strips surrounding whitespace and then one trailing "." (the prompt
    supplies its own), and rejects an empty result, a line break, or more than GOAL_MAX_CHARS
    characters."""
    goal = text.strip()
    if goal.endswith("."):
        goal = goal[:-1].rstrip()
    if not goal:
        raise argparse.ArgumentTypeError("must not be empty")
    if "\n" in goal or "\r" in goal:
        raise argparse.ArgumentTypeError("must be a single line")
    if len(goal) > GOAL_MAX_CHARS:
        raise argparse.ArgumentTypeError("must be at most %d characters (got %d)"
                                         % (GOAL_MAX_CHARS, len(goal)))
    return goal


def build_parser():
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    return parser
```

with:

```python
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    parser.add_argument("--story-legacy", dest="story_legacy", action="store_true", default=False,
                         help="Phase 1 uses the single-prompt story path (one bin/qwen-agent call that "
                              "writes story.md), exactly as before the robust story engine. See "
                              "docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md.")
    parser.add_argument("--no-auto-lora", dest="no_auto_lora", action="store_true", default=False,
                         help="the story plan picks no catalog LoRAs (generated/loras/catalog.json); "
                              "--lora/--stills-lora still apply")
    parser.add_argument("--judge", dest="judge", action="store_true", default=False,
                         help="after the local critic rounds, run bin/judge-story --patches (Claude; "
                              "needs ANTHROPIC_API_KEY) as a final gate; a minimum score below 7 "
                              "applies its patches and runs one more critic round")
    parser.add_argument("--goal", dest="goal", type=_parse_goal, default=None, metavar="TEXT",
                         help="the target output goal given to the story planner, the critic and the "
                              "judge, worded to complete 'The target output goal is TEXT.'")
    return parser
```

**3.5.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()
```

with:

```python
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


def _story_engine():
    """story_engine.py, the robust Phase 1 engine, loaded by path and only inside function bodies
    (robust story spec 1.2), so importing this file stays stdlib-only."""
    return importlib.machinery.SourceFileLoader(
        "story_engine", os.path.join(WS, "story_engine.py")).load_module()


def _lora_catalog():
    """lora_catalog.py, loaded by path and only inside function bodies (robust story spec 1.2)."""
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(WS, "lora_catalog.py")).load_module()
```

**3.6.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _resolve_shots(args):
```

with:

```python
def _resolve_story_engine(args):
    """Select Phase 1's story engine (robust story spec RS2): sets args.story_engine to "robust" or
    "legacy" and args.story_catalog to the loaded LoRA catalog (the empty catalog with
    --no-auto-lora, None on the legacy engine). Returns 0, or 2 after one Error: line."""
    legacy = args.story_legacy or args.story_prompt_override is not None
    reason = "--story-legacy" if args.story_legacy else "--story-prompt-override"
    if legacy:
        for flag, given in (("--judge", args.judge), ("--no-auto-lora", args.no_auto_lora),
                            ("--goal", args.goal is not None)):
            if given:
                print("Error: %s needs the default story engine; it cannot be combined with %s"
                      % (flag, reason), file=sys.stderr)
                return 2
        args.story_engine, args.story_catalog = "legacy", None
        return 0
    if args.judge and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: --judge needs ANTHROPIC_API_KEY for bin/judge-story; export it or drop "
              "--judge", file=sys.stderr)
        return 2
    if args.no_auto_lora:
        args.story_catalog = {"schema_version": 1, "entries": []}
    else:
        catalog = _lora_catalog()
        path = catalog.catalog_path(WS)
        try:
            args.story_catalog = catalog.load_catalog(path)
        except catalog.CatalogError as e:
            reason = str(e)
            if reason.startswith(path + ": "):
                reason = reason[len(path) + 2:]
            print("Error: invalid LoRA catalog %s: %s; run bin/lora-catalog verify" % (path, reason),
                  file=sys.stderr)
            return 2
    args.story_engine = "robust"
    return 0


def _resolve_shots(args):
```

**3.7.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def phase1_story(args):
    paths = _story_paths(args.story_id)
```

with:

```python
def phase1_story(args):
    if getattr(args, "story_engine", "legacy") == "robust":
        return _phase1_robust(args)
    paths = _story_paths(args.story_id)
```

**3.8.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        print("=== Phase 1: story ===")
        if args.story_prompt_override is not None:
```

with:

```python
        print("=== Phase 1: story ===")
        stale_plan = os.path.join(_story_dir(args.story_id), "plan.json")
        if os.path.exists(stale_plan):
            moved = _unused_path(os.path.join(_story_dir(args.story_id), "plan.stale-%s-%d.json"
                                              % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                                                 os.getpid())))
            os.replace(stale_plan, moved)
            print("note: moved the robust engine's plan.json aside to %s; this story.md is written "
                  "by --story-legacy" % moved)
        if args.story_prompt_override is not None:
```

**3.9.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _unused_path(path):
```

with:

```python
def _story_mode(args):
    return ("no_stills" if args.no_stills
            else "shots" if getattr(args, "shots", False) else "chained")


def _story_pins(args, catalog):
    """Every global video --lora as a pin {"path", "strength", "catalog_id", "kind"} (LC12); the
    catalog fields come from a video catalog entry with the same realpath, else null."""
    if getattr(args, "global_video_loras", None):
        loras = list(args.global_video_loras)
    elif args.lora_path:
        loras = [(os.path.abspath(args.lora_path), 1.0)]
    else:
        loras = []
    by_real = dict((os.path.realpath(e["path"]), e) for e in catalog["entries"]
                   if e["target"] == "video")
    pins = []
    for path, strength in loras:
        entry = by_real.get(os.path.realpath(path))
        pins.append({"path": path, "strength": strength,
                     "catalog_id": entry["id"] if entry else None,
                     "kind": entry["kind"] if entry else None})
    return pins


def _story_context(args, dry_run=False):
    """The story_engine.StoryContext of this run (robust story spec 2.1)."""
    engine = _story_engine()
    paths = _story_paths(args.story_id)
    seeded = bool(getattr(args, "seed_image", None))
    catalog = getattr(args, "story_catalog", None) or {"schema_version": 1, "entries": []}
    if getattr(args, "global_stills_loras", None):
        stills = [os.path.realpath(path) for path, _strength in args.global_stills_loras]
    elif args.stills_lora_path:
        stills = [os.path.realpath(args.stills_lora_path)]
    else:
        stills = []
    if not seeded:
        agent_image = None
    elif dry_run:
        agent_image = paths["seed_downscaled"]
    else:
        agent_image = getattr(args, "seed_downscaled_path", None)
    return engine.StoryContext(
        ws=WS, story_id=args.story_id, story_dir=paths["story_dir"], mode=_story_mode(args),
        panels=args.panels, seconds=_clip_seconds(args), narrative=args.narrative,
        goal=args.goal, members=list(getattr(args, "cast_members", None) or []),
        seed_image=os.path.abspath(args.seed_image) if seeded else None,
        seed_agent_image=agent_image, story_model=args.story_model,
        context_window=args.story_context_window, video_model=args.model,
        auto_lora=not args.no_auto_lora, catalog=catalog, pinned=_story_pins(args, catalog),
        stills_pinned=stills, judge=args.judge)


def _no_stills_rules():
    """The Rules: lines of STORY_PROMPT_TEMPLATE_NO_STILLS, each stripped (robust story spec RS12)."""
    template = STORY_PROMPT_TEMPLATE_NO_STILLS
    block = template[template.index("Rules:\n") + len("Rules:\n"):
                     template.index("\n\nNarrative to adapt:")]
    return "\n".join(line.strip() for line in block.split("\n"))


def _phase1_robust(args):
    """Phase 1 on the robust story engine (robust story spec RS35): re-check an existing story.md
    (no --force-story), else write story_prompt.txt and run the engine; then the review gate."""
    paths = _story_paths(args.story_id)
    story_md = paths["story_md"]
    engine = _story_engine()
    ctx = _story_context(args)
    if os.path.exists(story_md) and not args.force_story:
        print("note: %s already exists; re-checking it instead of regenerating it (pass "
              "--force-story to regenerate)" % story_md)
        rc, advisories = engine.recheck(ctx, _validate_story_md)
    else:
        print("=== Phase 1: story ===")
        prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                     bool(getattr(args, "seed_image", None)),
                                     seconds=_clip_seconds(args),
                                     cast_block=getattr(args, "cast_block", None),
                                     shots=getattr(args, "shots", False))
        with open(os.path.join(paths["story_dir"], "story_prompt.txt"), "w",
                  encoding="utf-8") as f:
            f.write(prompt)
        rc, advisories = engine.run(ctx, no_stills_rules=_no_stills_rules())
    if rc != 0:
        return rc
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)
    for advisory in advisories:
        print("Warning: %s" % advisory)
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
    return 0


def _unused_path(path):
```

**3.10.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    rc = _resolve_global_loras(args)
    if rc:
        return rc

    if args.dry_run:
```

with:

```python
    rc = _resolve_global_loras(args)
    if rc:
        return rc
    rc = _resolve_story_engine(args)
    if rc:
        return rc

    if args.dry_run:
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_shots_mode.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
67 passed
17 passed
81 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py tests/test_lora_catalog.py tests/test_shots_mode.py bin/ltx-movie && echo py39-ok
python3 -m py_compile tests/test_story_engine.py tests/test_lora_catalog.py tests/test_shots_mode.py bin/ltx-movie && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py tests/test_lora_catalog.py tests/test_shots_mode.py bin/ltx-movie
git diff --cached --name-only
git commit -m "ltx-movie: --story-legacy, --no-auto-lora, --judge, --goal and the robust Phase 1 (story RS2, RS25, RS29, RS31, RS34-RS36; catalog LC12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_lora_catalog.py
qwen-agent-workspace/tests/test_shots_mode.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 12: The robust dry run and the Section 5.5 dry-run test migrations

Implements RS30 (the Phase 1 block) and RSK5's golden. Section 5.5's `--story-legacy` edits of `tests/test_ltx_movie_offline.py` (L18 twice), `tests/test_casting_regression.py` (`b1_text`), `tests/test_casting_pipeline.py` (`test_p46`), `tests/test_shots_mode.py` (`test_s50`, `test_s99`), plus L11 (Plan decision 18). Tests RST41, RST47, RST57 (the dry run).

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `tests/test_ltx_movie_offline.py`
- Modify: `tests/test_casting_regression.py`
- Modify: `tests/test_casting_pipeline.py`
- Modify: `tests/test_shots_mode.py`
- Modify: `bin/ltx-movie`

**Interfaces:**
- Consumes: Task 11's `_story_engine`, `_lora_catalog`, `_story_context(args, dry_run=True)`; `story_engine.compatible_entries`, `catalog_warnings`, `build_plan_prompt`, `agent_cmd`, `plan_max_tokens`, `plan_timeout`.
- Produces: In `bin/ltx-movie`: `_print_legacy_phase1(args, paths, prompt, max_tokens, timeout)` (today's Phase 1 dry-run block, moved verbatim) and `_print_robust_phase1(args, paths)`. In the test module: `FORBIDDEN_IN_PHASE1`, `_dry_run(story_id, *flags, env=None)`, `_phase1_block(out)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst41_legacy_dry_run_matches_the_golden`, `test_rst47_robust_dry_run`, `test_rst57c_dry_run_lists_the_undeclared_characters`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST41, RST47, RST57 (dry run): the robust dry run (RS30, RSK5) ---------------------------

FORBIDDEN_IN_PHASE1 = ("{", "}", "ltx-mlx-render", "ltx-story-images", "ltx-story-manifest",
                       "story-server", "--resume", "--chain", "--shots", "--no-images")


def test_rst41_legacy_dry_run_matches_the_golden():
    regression = importlib.machinery.SourceFileLoader(
        "casting_regression_for_rst41", os.path.join(WS, "tests", "test_casting_regression.py")
    ).load_module()
    with open(regression.GOLDEN_B1, encoding="utf-8") as f:
        assert regression.b1_text() == f.read()


def _dry_run(story_id, *flags, env=None):
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                           "--story-id", story_id, "--dry-run", "--no-review"] + list(flags),
                          cwd=WS, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))
    return proc


def _phase1_block(out):
    lines = out.splitlines()
    start = lines.index("--- Phase 1: story ---")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("--- Phase "))
    return lines[start:end]


def test_rst47_robust_dry_run(tmp_path, story_env, monkeypatch):
    from PIL import Image
    seed = str(tmp_path / "seed.png")
    Image.new("RGB", (704, 448), (10, 20, 30)).save(seed)
    files = str(tmp_path / "files")
    seu.make_catalog(story_env["catalog"], [
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
        seu.catalog_entry(seu.lora_file(files, "other"), "other-model", base_models=["X/y"])])
    catalog_path = os.path.join(story_env["catalog"], "catalog.json")
    story_dir = os.path.join(WS, "generated", "stories", "rst47-%d" % os.getpid())
    assert not os.path.exists(story_dir)
    cases = [
        ([], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--no-stills"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--shots"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, False),
        (["--seed-image", seed], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, True,
         False),
        (["--no-auto-lora"], "Catalog LoRAs: off (--no-auto-lora)", False, False),
        (["--judge"], "Catalog LoRAs: 1 compatible entry in %s" % catalog_path, False, True),
    ]
    for flags, catalog_line, seeded, judge in cases:
        proc = _dry_run(os.path.basename(story_dir), "--panels", "4", *flags,
                        env={"ANTHROPIC_API_KEY": "test-not-a-key"} if judge else None)
        assert proc.returncode == 0, proc.stderr
        block = _phase1_block(proc.stdout)
        assert block[:4] == [
            "--- Phase 1: story ---",
            "Would skip if %s already exists and re-check it instead (pass --force-story to "
            "regenerate)." % os.path.join(story_dir, "story.md"),
            "Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 "
            "critic rounds (analyst via the local qwen-agentd, else a local one-shot); "
            "--story-legacy for the single-prompt path.",
            catalog_line]
        command = block[5 if judge else 4]
        if judge:
            assert block[4] == "Judge gate: bin/judge-story --patches after the critic rounds."
        assert command.startswith("Command (subprocess timeout 600s): ")
        argv = shlex.split(proc.stdout.split("Command (subprocess timeout 600s): ", 1)[1]
                           .split("\n\nRendered plan prompt:\n", 1)[0])
        assert argv[argv.index("--max-rounds") + 1] == "1"
        assert argv[argv.index("--max-tokens") + 1] == "4096"
        assert ("--image" in argv) == seeded
        if seeded:
            assert argv[argv.index("--image") + 1] == os.path.join(story_dir, "seed_downscaled.png")
        assert argv[-1].startswith('You are planning a short narrated movie (story-id "rst47-')
        assert block[block.index("Rendered plan prompt:") + 1].startswith("You are planning")
        assert not [line for line in proc.stdout.splitlines() if "{" in line or "}" in line]
        phase1 = "\n".join(block)
        assert not [s for s in FORBIDDEN_IN_PHASE1 if s in phase1], flags
    assert not os.path.exists(story_dir)
    os.remove(catalog_path)
    proc = _dry_run("rst47b-%d" % os.getpid())
    assert ("Catalog LoRAs: none compatible in %s" % catalog_path) in proc.stdout.splitlines()
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
        "print('FLEET_LOADED=%%s' %% ('fleet_lib_for_story' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    seu.kyra(story_env["lib"])
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.stdout.splitlines() == ["RC=0", "CHARACTER_LIB_LOADED=False", "FLEET_LOADED=False"], (
        proc.stderr)


def test_rst57c_dry_run_lists_the_undeclared_characters(story_env):
    seu.ronin(story_env["lib"])
    proc = _dry_run("rst57-%d" % os.getpid(), "--panels", "3")
    assert proc.returncode == 0, proc.stderr
    assert (' Never use these names or referring phrases, which belong to characters who are not '
            'in this movie: ronin ("the ronin").') in proc.stdout
```

**1.2.** Edit `tests/test_ltx_movie_offline.py`: replace this text, which occurs exactly once:

```python
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-nostills",
         "--no-stills", "--panels", "6", "--dry-run"],
```

with:

```python
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-nostills",
         "--no-stills", "--panels", "6", "--dry-run", "--story-legacy"],
```

**1.3.** Edit `tests/test_ltx_movie_offline.py`: replace this text, which occurs exactly once:

```python
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-default",
         "--panels", "6", "--dry-run"],
```

with:

```python
        [sys.executable, _SCRIPT_PATH, "a narrative", "--story-id", "unittest-default",
         "--panels", "6", "--dry-run", "--story-legacy"],
```

**1.4.** Edit `tests/test_casting_regression.py`: replace this text, which occurs exactly once:

```python
         "casting-baseline-dry", "--dry-run", "--no-review", "--model", MODEL_25],
```

with:

```python
         "casting-baseline-dry", "--dry-run", "--no-review", "--story-legacy", "--model",
         MODEL_25],
```

**1.5.** Edit `tests/test_casting_pipeline.py`: replace this text, which occurs exactly once:

```python
    assert ltx_movie.main(["two travellers", "--story-id", "casting-p46", "--dry-run",
                           "--no-review", "--character", "kyra"]) == 0
```

with:

```python
    assert ltx_movie.main(["two travellers", "--story-id", "casting-p46", "--dry-run",
                           "--no-review", "--character", "kyra", "--story-legacy"]) == 0
```

**1.6.** Edit `tests/test_shots_mode.py`: replace this text, which occurs exactly once:

```python
    story_id = "shots-s50-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
```

with:

```python
    story_id = "shots-s50-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin",
         "--story-legacy"],
```

**1.7.** Edit `tests/test_shots_mode.py`: replace this text, which occurs exactly once:

```python
    story_id = "shots-s99-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
```

with:

```python
    story_id = "shots-s99-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin",
         "--story-legacy"],
```

**1.8.** Edit `tests/test_ltx_movie_offline.py`: replace this text, which occurs exactly once:

```python
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "100", "--dry-run"],
```

with:

```python
        [sys.executable, _SCRIPT_PATH, "narrative", "--story-id", "x",
         "--length", "100", "--dry-run", "--story-legacy"],
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_shots_mode.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_casting_pipeline.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_casting_regression.py -q -p no:cacheprovider 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
2 failed, 68 passed
81 passed
63 passed
3 passed
OK 344/344
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst47_robust_dry_run
FAILED tests/test_story_engine.py::test_rst57c_dry_run_lists_the_undeclared_characters
```

`test_rst41_legacy_dry_run_matches_the_golden` passes already: since Task 11 `--story-legacy` exists and the dry run still prints today's block; Step 3 must keep it passing. The migrated suites pass before and after Step 3.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    print("--- Phase 1: story ---")
    print("Would skip if %s already exists (pass --force-story to regenerate)."
          % paths["story_md"])
    phase1_cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),
                  "--workspace", WS,
                  "--max-tokens", str(max_tokens), "--max-rounds", "4",
                  "--request-timeout", "600"]
    if args.story_model:
        phase1_cmd += ["--model", args.story_model]
    if args.story_context_window:
        phase1_cmd += ["--context-window", str(args.story_context_window)]
    if getattr(args, "seed_image", None):
        phase1_cmd += ["--image", paths["seed_downscaled"]]
    phase1_cmd += ["--user-prompt", prompt]
    print("Command (subprocess timeout %ds): %s" % (timeout, shlex.join(phase1_cmd)))
    print()
    print("Rendered story prompt:")
    print(prompt)
    print()

```

with:

```python
    print("--- Phase 1: story ---")
    if getattr(args, "story_engine", "legacy") == "robust":
        _print_robust_phase1(args, paths)
    else:
        _print_legacy_phase1(args, paths, prompt, max_tokens, timeout)

```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _print_shots_stills_plan(args, cmd):
```

with:

```python
def _print_legacy_phase1(args, paths, prompt, max_tokens, timeout):
    """The --story-legacy Phase 1 block of the dry run, exactly as before the robust engine."""
    print("Would skip if %s already exists (pass --force-story to regenerate)."
          % paths["story_md"])
    phase1_cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),
                  "--workspace", WS,
                  "--max-tokens", str(max_tokens), "--max-rounds", "4",
                  "--request-timeout", "600"]
    if args.story_model:
        phase1_cmd += ["--model", args.story_model]
    if args.story_context_window:
        phase1_cmd += ["--context-window", str(args.story_context_window)]
    if getattr(args, "seed_image", None):
        phase1_cmd += ["--image", paths["seed_downscaled"]]
    phase1_cmd += ["--user-prompt", prompt]
    print("Command (subprocess timeout %ds): %s" % (timeout, shlex.join(phase1_cmd)))
    print()
    print("Rendered story prompt:")
    print(prompt)
    print()


def _print_robust_phase1(args, paths):
    """The robust engine's Phase 1 block of the dry run (robust story spec RS30). Writes nothing;
    loads story_engine.py and lora_catalog.py only."""
    engine = _story_engine()
    ctx = _story_context(args, dry_run=True)
    compatible = engine.compatible_entries(ctx)
    print("Would skip if %s already exists and re-check it instead (pass --force-story to "
          "regenerate)." % paths["story_md"])
    print("Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 critic "
          "rounds (analyst via the local qwen-agentd, else a local one-shot); --story-legacy for "
          "the single-prompt path.")
    for warning in engine.catalog_warnings(ctx):
        print(warning)
    catalog_path = _lora_catalog().catalog_path(WS)
    if args.no_auto_lora:
        print("Catalog LoRAs: off (--no-auto-lora)")
    elif compatible:
        print("Catalog LoRAs: %d compatible entr%s in %s"
              % (len(compatible), "y" if len(compatible) == 1 else "ies", catalog_path))
    else:
        print("Catalog LoRAs: none compatible in %s" % catalog_path)
    if args.judge:
        print("Judge gate: bin/judge-story --patches after the critic rounds.")
    prompt = engine.build_plan_prompt(ctx, compatible, ctx.pinned)
    argv = engine.agent_cmd(ctx, prompt, max_tokens=engine.plan_max_tokens(args.panels),
                            image=ctx.seed_agent_image)
    print("Command (subprocess timeout %ds): %s"
          % (engine.plan_timeout(args.panels), shlex.join(argv)))
    print()
    print("Rendered plan prompt:")
    print(prompt)
    print()


def _print_shots_stills_plan(args, cmd):
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_shots_mode.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_casting_pipeline.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_casting_regression.py -q -p no:cacheprovider 2>&1 | tail -1
python3 tests/test_ltx_movie_offline.py 2>&1 | tail -1
```

Expected:

```
70 passed
81 passed
63 passed
3 passed
OK 344/344
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py tests/test_ltx_movie_offline.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_shots_mode.py bin/ltx-movie && echo py39-ok
python3 -m py_compile tests/test_story_engine.py tests/test_ltx_movie_offline.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_shots_mode.py bin/ltx-movie && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py tests/test_ltx_movie_offline.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_shots_mode.py bin/ltx-movie
git diff --cached --name-only
git commit -m "ltx-movie: robust dry-run Phase 1 block; dry-run tests pin --story-legacy (story RS30, RS31)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_casting_pipeline.py
qwen-agent-workspace/tests/test_casting_regression.py
qwen-agent-workspace/tests/test_ltx_movie_offline.py
qwen-agent-workspace/tests/test_shots_mode.py
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 13: bin/ltx-movie: catalog LoRAs for Phases 2 and 3 (and their dry run)

Implements LC13, LC14, and RS30's last bullet (the dry run shows the flags). Tests LCT14, LCT15, Review Focus 4.

**Files:**
- Modify: `tests/test_lora_catalog.py`
- Modify: `bin/ltx-movie`

**Interfaces:**
- Consumes: Task 11's `_story_mode`, `args.story_engine`, `args.story_catalog`, `args.no_auto_lora`.
- Produces: In `bin/ltx-movie`: `_catalog_plan(args, dry_run=False) -> dict|None`; `_catalog_pick(args, pick) -> (item, None) | (None, error line)`; `_catalog_panel_loras(args, dry_run=False) -> (error|None, lists|None)`; `_catalog_stills_flags(args, dry_run=False) -> (error|None, flags)`; `_write_catalog_loras(args, path, panels)`. In `tests/test_lora_catalog.py`: `_Done`, `_catalog_story(tmp_path, monkeypatch, story_env, stills=False, extra=())`, `_recorded(monkeypatch)`, `_item(entry, strength)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_lct14_phase3_catalog_loras`, `test_lct15_phase2_stills_pick`, `test_story_focus_4_a_cataloged_lora_deleted_after_phase_1`.

**1.1.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- LCT14, LCT15: the catalog flags of Phases 2 and 3 in bin/ltx-movie (LC13, LC14) ---------

class _Done(object):
    returncode = 0


def _catalog_story(tmp_path, monkeypatch, story_env, stills=False, extra=()):
    """A temp workspace (ltx_movie.WS) with a 3-panel chained story whose plan.json picks
    film-grain (global style) and fast-motion (beat 2); returns (ws, story_dir, entries)."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    files = str(tmp_path / "files")
    grain = seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                              triggers=["grainfilm"])
    fast = seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", triggers=["fastmo"])
    ink = seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                            target="stills", base_models=[seu.STILLS_MODEL], triggers=["inkstyle"])
    seu.make_catalog(story_env["catalog"], [grain, fast, ink] + list(extra))
    story_dir = os.path.join(ws, "generated", "stories", "c1")
    os.makedirs(story_dir)
    loras = {"global": [{"id": "film-grain", "strength": 0.8}],
             "per_beat": {"2": [{"id": "fast-motion", "strength": 0.7}]},
             "stills": [{"id": "ink-stills", "strength": 0.8}] if stills else []}
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump({"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 3,
                   "loras": loras}, f)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("# T\n\n## Panel 1 — A\nImage: The woman in grey waits.\nMotion: x\n"
                "Narration: y\n")
    return ws, story_dir, {"film-grain": grain, "fast-motion": fast, "ink-stills": ink}


def _recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or _Done())
    return calls


def _item(entry, strength):
    return {"id": entry["id"], "kind": entry["kind"], "path": entry["path"],
            "sha256": entry["sha256"], "strength": strength, "triggers": entry["triggers"]}


def test_lct14_phase3_catalog_loras(tmp_path, monkeypatch, story_env, capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env)
    calls = _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    assert ltx_movie.phase3_manifest(args) == 0
    path = os.path.join(story_dir, "catalog_loras.json")
    grain, fast = _item(entries["film-grain"], 0.8), _item(entries["fast-motion"], 0.7)
    with open(path) as f:
        assert json.load(f) == {"schema": "ltx-movie.catalog-loras.v1", "story_id": "c1",
                                "panels": [[grain], [fast, grain], [grain]]}
    assert calls[0][-2:] == ["--catalog-loras", path]
    os.remove(path)
    for flags in (["--no-auto-lora"], ["--story-legacy"]):
        calls[:] = []
        assert ltx_movie.phase3_manifest(_movie_args("n", "--story-id", "c1", "--panels", "3",
                                                     "--no-review", *flags)) == 0
        assert "--catalog-loras" not in calls[0] and not os.path.exists(path)
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run",
                           "--no-review"]) == 0
    manifest_line = [l for l in capsys.readouterr().out.splitlines()
                     if "ltx-story-manifest" in l][0]
    assert manifest_line.endswith(" --catalog-loras " + path)
    assert not os.path.exists(path)
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run", "--no-review",
                           "--force-story"]) == 0
    assert "--catalog-loras" not in capsys.readouterr().out
    with open(entries["fast-motion"]["path"], "ab") as f:
        f.write(b"x")
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["fast-motion"]["path"])
    seu.make_catalog(story_env["catalog"], [entries["film-grain"]])
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: plan.json picks catalog LoRA fast-motion, which is no longer in the catalog; "
        "re-add it with bin/lora-catalog add, or rerun with --no-auto-lora\n")


def test_lct15_phase2_stills_pick(tmp_path, monkeypatch, story_env, capsys):
    seu.kyra(story_env["lib"])
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env, stills=True)
    calls = _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review", "--character",
                       "kyra")
    assert ltx_movie.phase2_stills(args) == 0
    ink = entries["ink-stills"]["path"]
    cmd = calls[0]
    at = cmd.index("--cast")
    assert cmd[at - 4:at + 2] == ["--lora", ink + ":0.8", "--lora-trigger", "inkstyle", "--cast",
                                  "the woman in grey=kyra"]
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "c1", "--panels", "3", "--dry-run", "--no-review",
                           "--character", "kyra"]) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if "ltx-story-images" in l][0]
    assert ("--lora %s:0.8 --lora-trigger inkstyle --cast" % ink) in line
    calls[:] = []
    assert ltx_movie.phase2_stills(_movie_args("n", "--story-id", "c1", "--panels", "3",
                                               "--no-review", "--no-auto-lora")) == 0
    assert "--lora-trigger" not in calls[0] and "--lora" not in calls[0]


def test_story_focus_4_a_cataloged_lora_deleted_after_phase_1(tmp_path, monkeypatch, story_env,
                                                               capsys):
    ws, story_dir, entries = _catalog_story(tmp_path, monkeypatch, story_env, stills=True)
    _recorded(monkeypatch)
    args = _movie_args("n", "--story-id", "c1", "--panels", "3", "--no-review")
    os.remove(entries["fast-motion"]["path"])
    os.remove(entries["ink-stills"]["path"])
    assert ltx_movie.phase3_manifest(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["fast-motion"]["path"])
    assert ltx_movie.phase2_stills(args) == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA ink-stills changed since it was cataloged (%s); run "
        "bin/lora-catalog verify\n" % entries["ink-stills"]["path"])
    assert not os.path.exists(os.path.join(story_dir, "catalog_loras.json"))
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
3 failed, 17 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_lora_catalog.py::test_lct14_phase3_catalog_loras
FAILED tests/test_lora_catalog.py::test_lct15_phase2_stills_pick
FAILED tests/test_lora_catalog.py::test_story_focus_4_a_cataloged_lora_deleted_after_phase_1
```

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
def _phase1_robust(args):
```

with:

```python
def _catalog_plan(args, dry_run=False):
    """This story's plan.json when catalog LoRAs apply (LC13): the robust engine, auto LoRA on,
    and a valid plan for this mode and panel count (and, in a dry run, no --force-story). Else
    None."""
    if (getattr(args, "story_engine", "legacy") != "robust" or getattr(args, "no_auto_lora", False)
            or (dry_run and args.force_story)):
        return None
    try:
        with open(os.path.join(_story_dir(args.story_id), "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    if (not isinstance(plan, dict) or plan.get("schema") != "ltx-movie.plan.v1"
            or plan.get("mode") != _story_mode(args) or plan.get("panels") != args.panels
            or not isinstance(plan.get("loras"), dict)):
        return None
    return plan


def _catalog_pick(args, pick):
    """(the catalog-loras entry of one plan pick, None) or (None, the LC13 Error line)."""
    entries = dict((e["id"], e) for e in (getattr(args, "story_catalog", None) or {}).get(
        "entries", []))
    entry = entries.get(pick.get("id"))
    if entry is None:
        return None, ("Error: plan.json picks catalog LoRA %s, which is no longer in the catalog; "
                      "re-add it with bin/lora-catalog add, or rerun with --no-auto-lora"
                      % pick.get("id"))
    try:
        size = os.path.getsize(entry["path"])
    except OSError:
        size = None
    if size != entry["bytes"]:
        return None, ("Error: catalog LoRA %s changed since it was cataloged (%s); run "
                      "bin/lora-catalog verify" % (entry["id"], entry["path"]))
    return {"id": entry["id"], "kind": entry["kind"], "path": entry["path"],
            "sha256": entry["sha256"], "strength": pick["strength"],
            "triggers": list(entry["triggers"])}, None


def _catalog_panel_loras(args, dry_run=False):
    """(None, None) when the plan picks no video catalog LoRA; else (None, one list per panel:
    its motion/physics picks, global then per-beat, then the global style pick) or (the LC13
    Error line, None)."""
    plan = _catalog_plan(args, dry_run)
    if plan is None:
        return None, None
    global_picks = plan["loras"].get("global") or []
    per_beat = plan["loras"].get("per_beat") or {}
    if not global_picks and not any(per_beat.values()):
        return None, None
    resolved = {}
    for pick in global_picks + [p for picks in per_beat.values() for p in picks]:
        item, error = _catalog_pick(args, pick)
        if error:
            return error, None
        resolved[id(pick)] = item
    panels = []
    for k in range(1, args.panels + 1):
        picks = [resolved[id(p)] for p in global_picks + (per_beat.get(str(k)) or [])]
        panels.append([p for p in picks if p["kind"] in ("motion", "physics")]
                      + [resolved[id(p)] for p in global_picks
                         if resolved[id(p)]["kind"] == "style"])
    return None, panels


def _catalog_stills_flags(args, dry_run=False):
    """(None, ["--lora", PATH:STRENGTH, "--lora-trigger", T, ...]) for the plan's stills pick,
    (None, []) without one, or (the LC13 Error line, []) (LC14)."""
    plan = _catalog_plan(args, dry_run)
    picks = (plan["loras"].get("stills") or []) if plan else []
    if not picks:
        return None, []
    item, error = _catalog_pick(args, picks[0])
    if error:
        return error, []
    flags = ["--lora", "%s:%s" % (item["path"], repr(float(item["strength"])))]
    for trigger in item["triggers"]:
        flags += ["--lora-trigger", trigger]
    return None, flags


def _write_catalog_loras(args, path, panels):
    """<story_dir>/catalog_loras.json (robust story spec 2.8), written atomically."""
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": args.story_id,
                   "panels": panels}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(temporary, path)


def _phase1_robust(args):
```

**3.2.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    cmd += _cast_flags(args)
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

with:

```python
    error, catalog_flags = _catalog_stills_flags(args)
    if error:
        print(error, file=sys.stderr)
        return 2
    cmd += catalog_flags
    cmd += _cast_flags(args)
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

**3.3.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    cmd_manifest += _cast_flags(args)
    print("Running: %s" % shlex.join(cmd_manifest))
```

with:

```python
    cmd_manifest += _cast_flags(args)
    error, catalog_lists = _catalog_panel_loras(args)
    if error:
        print(error, file=sys.stderr)
        return 2
    if catalog_lists is not None:
        catalog_path = os.path.join(paths["story_dir"], "catalog_loras.json")
        _write_catalog_loras(args, catalog_path, catalog_lists)
        cmd_manifest += ["--catalog-loras", catalog_path]
    print("Running: %s" % shlex.join(cmd_manifest))
```

**3.4.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
        phase2_cmd += _cast_flags(args)
```

with:

```python
        error, catalog_flags = _catalog_stills_flags(args, dry_run=True)
        if error:
            print(error, file=sys.stderr)
            return 2
        phase2_cmd += catalog_flags
        phase2_cmd += _cast_flags(args)
```

**3.5.** Edit `bin/ltx-movie`: replace this text, which occurs exactly once:

```python
    phase3_manifest_cmd += _cast_flags(args)
```

with:

```python
    phase3_manifest_cmd += _cast_flags(args)
    error, catalog_lists = _catalog_panel_loras(args, dry_run=True)
    if error:
        print(error, file=sys.stderr)
        return 2
    if catalog_lists is not None:
        phase3_manifest_cmd += ["--catalog-loras",
                                os.path.join(paths["story_dir"], "catalog_loras.json")]
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
20 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_lora_catalog.py bin/ltx-movie && echo py39-ok
python3 -m py_compile tests/test_lora_catalog.py bin/ltx-movie && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_lora_catalog.py bin/ltx-movie
git diff --cached --name-only
git commit -m "ltx-movie: catalog LoRA flags for Phases 2 and 3 (catalog LC13, LC14)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_lora_catalog.py
```


---

### Task 14: bin/ltx-story-manifest --catalog-loras and bin/ltx-story-images --lora-trigger

Implements LC15, LC16. Tests LCT16, LCT17, LCT18.

**Files:**
- Modify: `tests/test_lora_catalog.py`
- Modify: `bin/ltx-story-manifest`
- Modify: `bin/ltx-story-images`

**Interfaces:**
- Consumes: `lora_catalog.prefix_triggers` (Task 2).
- Produces: In `bin/ltx-story-manifest`: the `--catalog-loras` flag, `_lora_catalog()`, `_catalog_entry_problem(entry)`, `_read_catalog_loras(path, n_panels) -> (lists, None) | (None, reason)`; each panel's optional `catalog_loras`. In `bin/ltx-story-images`: the `--lora-trigger` flag and `lora_triggers` in `images.json`. In `tests/test_lora_catalog.py`: `story_manifest`, `story_images`, `CHAIN_STORY`, `_manifest_inputs`, `_entry(tmp_path, entry_id, kind, strength, triggers)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_lct16_manifest_catalog_loras`, `test_lct17_manifest_without_catalog_is_unchanged`, `test_lct18_story_images_lora_trigger`.

**1.1.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- LCT16-LCT18: bin/ltx-story-manifest --catalog-loras, bin/ltx-story-images --lora-trigger ---

story_manifest = importlib.machinery.SourceFileLoader(
    "ltx_story_manifest_for_lora_catalog", os.path.join(WS, "bin", "ltx-story-manifest")).load_module()
story_images = importlib.machinery.SourceFileLoader(
    "ltx_story_images_for_lora_catalog", os.path.join(WS, "bin", "ltx-story-images")).load_module()
CHAIN_STORY = """# Test

## Panel 1 — One
Image: A courier stands on a wet quay beside the boats.
Motion: The courier pushes off.
Narration: It rained.

## Panel 2 — Two
Motion: The courier pedals hard.
Narration: It rained more.

## Panel 3 — Three
Motion: FASTMO blur as the courier arrives.
Narration: It stopped.
"""


def _manifest_inputs(tmp_path, monkeypatch, lists):
    from PIL import Image
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(story_manifest, "WS", ws)
    story_md = str(tmp_path / "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(CHAIN_STORY)
    image = str(tmp_path / "panel_01.png")
    Image.new("RGB", (64, 64), (9, 9, 9)).save(image)
    catalog_path = str(tmp_path / "catalog_loras.json")
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "m1", "panels": lists}, f)
    argv = ["--story-id", "m1", "--prompts-md", story_md, "--chain", "--image", image,
            "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
            "--max-frames", "145", "--force", "--catalog-loras", catalog_path]
    return ws, argv, catalog_path


def _entry(tmp_path, entry_id, kind, strength, triggers):
    path = seu.lora_file(str(tmp_path / "files"), entry_id)
    return {"id": entry_id, "kind": kind, "path": path, "sha256": seu.sha256_file(path),
            "strength": strength, "triggers": triggers}


def test_lct16_manifest_catalog_loras(tmp_path, monkeypatch, capsys):
    fast = _entry(tmp_path, "fast-motion", "motion", 0.7, ["fastmo"])
    grain = _entry(tmp_path, "film-grain", "style", 0.8, ["grainfilm"])
    ws, argv, catalog_path = _manifest_inputs(tmp_path, monkeypatch, [[grain], [fast, grain], [fast]])
    assert story_manifest.main(argv) == 0
    out = capsys.readouterr().out
    assert out.endswith("catalog: panel 1: film-grain@0.8\ncatalog: panel 2: fast-motion@0.7, "
                        "film-grain@0.8\ncatalog: panel 3: fast-motion@0.7\n")
    with open(os.path.join(ws, "generated", "stories", "m1", "manifest.json")) as f:
        manifest = json.load(f)
    panels = manifest["panels"]
    assert [p["catalog_loras"] for p in panels] == [[grain], [fast, grain], [fast]]
    assert [p["motion_prompt"] for p in panels] == [
        "grainfilm. The courier pushes off.", "fastmo, grainfilm. The courier pedals hard.",
        "FASTMO blur as the courier arrives."]
    assert panels[0]["panel_text"] == "A courier stands on a wet quay beside the boats."
    assert manifest["schema_version"] == 3
    bad_cases = [
        ([[grain], [fast]], "panels must be a list of exactly 3 lists"),
        ([[dict(grain, path="rel.safetensors")], [], []],
         "panel 1 entry 1: path must be an absolute path to a readable file, got 'rel.safetensors'"),
        ([[grain, dict(grain, id="other-grain")], [], []],
         "panel 1 has more than one style or motion/physics LoRA"),
        ([[grain, grain], [], []], "panel 1 lists a LoRA twice"),
        ([[dict(grain, strength=True)], [], []],
         "panel 1 entry 1: strength must be a number in (0, 2], got True"),
        ([[dict(grain, extra=1)], [], []],
         "panel 1 entry 1: must be an object with exactly the keys id, kind, path, sha256, "
         "strength, triggers"),
    ]
    for lists, reason in bad_cases:
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump({"schema": "ltx-movie.catalog-loras.v1", "story_id": "m1", "panels": lists}, f)
        assert story_manifest.main(argv) == 2
        assert capsys.readouterr().err == "Error: --catalog-loras %s: %s\n" % (catalog_path, reason)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump({"schema": "other"}, f)
    assert story_manifest.main(argv) == 2
    glob_argv = ["--story-id", "m1", "--glob", "panel_*.png", "--catalog-loras", catalog_path]
    with pytest.raises(SystemExit) as exc:
        story_manifest.main(glob_argv)
    assert exc.value.code == 2
    assert "--catalog-loras requires --chain, --shots or --no-images" in capsys.readouterr().err


def test_lct17_manifest_without_catalog_is_unchanged(tmp_path):
    regression = importlib.machinery.SourceFileLoader(
        "casting_regression_for_lct17", os.path.join(WS, "tests", "test_casting_regression.py")
    ).load_module()
    text = regression.b2_text(str(tmp_path))
    with open(regression.GOLDEN_B2, encoding="utf-8") as f:
        assert text == f.read()
    assert "catalog_loras" not in text


def test_lct18_story_images_lora_trigger(tmp_path, capsys):
    story_md = str(tmp_path / "story.md")
    with open(story_md, "w", encoding="utf-8") as f:
        f.write(CHAIN_STORY.replace("Motion: The courier pedals hard.",
                                    "Image: Inkstyle courier on the quay.\nMotion: The courier "
                                    "pedals hard."))
    out_dir = str(tmp_path / "images")
    base = ["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2", "--dry-run"]
    assert story_images.main(base) == 0
    plain = capsys.readouterr().out.splitlines()
    assert plain[0].endswith(" | 'A courier stands on a wet quay beside the boats.'")
    assert story_images.main(base + ["--lora-trigger", "inkstyle", "--lora-trigger", "ink2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith(" | 'inkstyle, ink2. A courier stands on a wet quay beside the boats.'")
    assert lines[2].endswith(" | 'ink2. Inkstyle courier on the quay.'")
    assert lines[1] == lines[3] == "    loras: none"
    assert not os.path.exists(out_dir)
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
2 failed, 21 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_lora_catalog.py::test_lct16_manifest_catalog_loras
FAILED tests/test_lora_catalog.py::test_lct18_story_images_lora_trigger
```

`test_lct17_manifest_without_catalog_is_unchanged` passes already: it pins today's manifest bytes, which Step 3 must keep.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                              "1.0, except with --shots, where every cast character uses this "
                              "strength")
    return parser


def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()
```

with:

```python
                              "1.0, except with --shots, where every cast character uses this "
                              "strength")
    parser.add_argument("--catalog-loras", dest="catalog_loras", default=None, metavar="PATH",
                         help="per-panel catalog LoRAs (bin/ltx-movie's catalog_loras.json): each "
                              "panel gets a catalog_loras list and its triggers are prefixed to its "
                              "motion_prompt")
    return parser


def _character_lib():
    return importlib.machinery.SourceFileLoader(
        "character_lib", os.path.join(WS, "character_lib.py")).load_module()


def _lora_catalog():
    return importlib.machinery.SourceFileLoader(
        "lora_catalog", os.path.join(WS, "lora_catalog.py")).load_module()


_CATALOG_ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
_CATALOG_SHA_RE = re.compile(r"[0-9a-f]{64}")
_CATALOG_ENTRY_KEYS = {"id", "kind", "path", "sha256", "strength", "triggers"}


def _catalog_entry_problem(entry):
    if not isinstance(entry, dict) or set(entry) != _CATALOG_ENTRY_KEYS:
        return "must be an object with exactly the keys id, kind, path, sha256, strength, triggers"
    if not isinstance(entry["id"], str) or not _CATALOG_ID_RE.fullmatch(entry["id"]):
        return "id must match [a-z][a-z0-9-]{1,31}, got %r" % (entry["id"],)
    if entry["kind"] not in ("style", "motion", "physics"):
        return "kind must be style, motion or physics, got %r" % (entry["kind"],)
    path = entry["path"]
    if (not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path)
            or not os.access(path, os.R_OK)):
        return "path must be an absolute path to a readable file, got %r" % (path,)
    if not isinstance(entry["sha256"], str) or not _CATALOG_SHA_RE.fullmatch(entry["sha256"]):
        return "sha256 must be 64 lowercase hex characters"
    strength = entry["strength"]
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 < strength <= 2:
        return "strength must be a number in (0, 2], got %r" % (strength,)
    if not isinstance(entry["triggers"], list) or not all(isinstance(t, str) for t in entry["triggers"]):
        return "triggers must be a list of strings"
    return None


def _read_catalog_loras(path, n_panels):
    """(per-panel lists, None) from bin/ltx-movie's catalog_loras.json, or (None, reason)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, "cannot read it: %s" % e
    if not isinstance(data, dict) or data.get("schema") != "ltx-movie.catalog-loras.v1":
        return None, "not a JSON object with schema ltx-movie.catalog-loras.v1"
    lists = data.get("panels")
    if (not isinstance(lists, list) or len(lists) != n_panels
            or not all(isinstance(entries, list) for entries in lists)):
        return None, "panels must be a list of exactly %d lists" % n_panels
    for i, entries in enumerate(lists, start=1):
        for j, entry in enumerate(entries, start=1):
            problem = _catalog_entry_problem(entry)
            if problem:
                return None, "panel %d entry %d: %s" % (i, j, problem)
        ids = [e["id"] for e in entries]
        if len(set(ids)) != len(ids):
            return None, "panel %d lists a LoRA twice" % i
        if (sum(1 for e in entries if e["kind"] == "style") > 1
                or sum(1 for e in entries if e["kind"] != "style") > 1):
            return None, "panel %d has more than one style or motion/physics LoRA" % i
    return lists, None
```

**3.2.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
    if args.cast and not (args.chain or args.shots):
        parser.error("--cast requires --chain or --shots")
```

with:

```python
    if args.cast and not (args.chain or args.shots):
        parser.error("--cast requires --chain or --shots")
    if args.catalog_loras and not (args.chain or args.shots or args.no_images):
        parser.error("--catalog-loras requires --chain, --shots or --no-images")
```

**3.3.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                print("WARNING: cast phrase %r (character %s) occurs in no panel's %s text; "
                      "that character gets no LoRA"
                      % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:"))
```

with:

```python
                print("WARNING: cast phrase %r (character %s) occurs in no panel's %s text; "
                      "that character gets no LoRA"
                      % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:"))

    if args.catalog_loras:
        lists, error = _read_catalog_loras(args.catalog_loras, n_panels)
        if error:
            print("Error: --catalog-loras %s: %s" % (args.catalog_loras, error), file=sys.stderr)
            return 2
        lora_catalog = _lora_catalog()
        for p, entries in zip(panels, lists):
            p["catalog_loras"] = [dict(entry) for entry in entries]
            triggers = [t for entry in entries for t in entry["triggers"]]
            if triggers:
                p["motion_prompt"] = lora_catalog.prefix_triggers(p["motion_prompt"], triggers)
```

**3.4.** Edit `bin/ltx-story-manifest`: replace this text, which occurs exactly once:

```python
                print("cast: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"])))
```

with:

```python
                print("cast: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (c["name"], repr(c["strength"])) for c in p["characters"])))
    if args.catalog_loras:
        for p in panels:
            if p["catalog_loras"]:
                print("catalog: panel %d: %s" % (p["index"], ", ".join(
                    "%s@%s" % (e["id"], repr(float(e["strength"]))) for e in p["catalog_loras"])))
```

**3.5.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
                             "or --character-strength (default 0.8)")
    return parser
```

with:

```python
                             "or --character-strength (default 0.8)")
    parser.add_argument("--lora-trigger", dest="lora_trigger", action="append", default=None,
                        metavar="WORD",
                        help="a catalog stills LoRA's trigger (repeatable, from bin/ltx-movie): "
                             "prefixed to every generated panel's prompt that lacks it")
    return parser
```

**3.6.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
        print("Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
              "set per process); run one --only panel per invocation", file=sys.stderr)
        return 2
```

with:

```python
        print("Error: the selected panels need different stills LoRA sets (z_image_skill loads one "
              "set per process); run one --only panel per invocation", file=sys.stderr)
        return 2
    if args.lora_trigger:
        lora_catalog = importlib.machinery.SourceFileLoader(
            "lora_catalog", os.path.join(WS, "lora_catalog.py")).load_module()
        for i in selected_indices:
            if args.seed_image is not None and i == 1:
                continue
            prompt, loras = plans.get(i, (compose(panels[i - 1]["image"], style), []))
            plans[i] = (lora_catalog.prefix_triggers(prompt, args.lora_trigger), loras)
```

**3.7.** Edit `bin/ltx-story-images`: replace this text, which occurs exactly once:

```python
    for r in results:
        if r["index"] in plans:
            r["loras"] = plans[r["index"]][1]
```

with:

```python
    for r in results:
        if r["index"] in plans:
            r["loras"] = plans[r["index"]][1]
        if args.lora_trigger and r["source"] == "generated":
            r["lora_triggers"] = list(args.lora_trigger)
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
23 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_lora_catalog.py bin/ltx-story-manifest bin/ltx-story-images && echo py39-ok
python3 -m py_compile tests/test_lora_catalog.py bin/ltx-story-manifest bin/ltx-story-images && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_lora_catalog.py bin/ltx-story-manifest bin/ltx-story-images
git diff --cached --name-only
git commit -m "story-manifest, story-images: per-panel catalog LoRAs and triggers (catalog LC15, LC16)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/tests/test_lora_catalog.py
```


---

### Task 15: bin/ltx-mlx-render: catalog_loras validation, units, provenance and checks

Implements LC17 and spec 1.4 (chained per-panel switching). Tests LCT19-LCT25, LCT30.

**Files:**
- Modify: `tests/test_lora_catalog.py`
- Modify: `bin/ltx-mlx-render`

**Interfaces:**
- Consumes: Manifest `catalog_loras` entries (Task 14's shape).
- Produces: In `bin/ltx-mlx-render`: `_catalog_lora_problem(entry)`; `load_manifest` validates `catalog_loras`; `build_units` adds `{"kind": "catalog", "name", "path", "strength", "catalog_id"}` between global and character entries; `build_clip_provenance` records `catalog_id`; `main` refuses duplicates and sha mismatches before `--dry-run`. In `tests/test_lora_catalog.py`: `render`, `_still`, `_chain_panels`, `_write_render_manifest`, `_RenderHarness`, `_render_entries`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_lct19_load_manifest_validates_catalog_loras`, `test_lct20_unit_lora_order`, `test_lct21_provenance`, `test_lct22_sha_and_duplicate_checks`, `test_lct23_dry_run_lists_catalog_loras`, `test_lct24_per_panel_loras_reach_generate_video`, `test_lct25_resume_with_catalog_loras`, `test_lct30_chained_manifest_per_panel_units`.

**1.1.** Append to `tests/test_lora_catalog.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- LCT19-LCT25, LCT30: bin/ltx-mlx-render catalog_loras (LC17, 1.4) ------------------------

render = importlib.machinery.SourceFileLoader(
    "ltx_mlx_render_for_lora_catalog", os.path.join(WS, "bin", "ltx-mlx-render")).load_module()


def _still(directory):
    from PIL import Image
    path = os.path.join(str(directory), "panel_01.png")
    Image.new("RGB", (64, 64), (40, 40, 40)).save(path)
    return path


def _chain_panels(directory, catalog_by_panel, characters=None):
    image = _still(directory)
    panels = []
    for i, entries in enumerate(catalog_by_panel, start=1):
        panel = {"index": i, "image_path": image if i == 1 else None,
                 "conditioning": "still" if i == 1 else "chain",
                 "panel_text": "panel %d text" % i, "motion_prompt": "panel %d motion" % i,
                 "catalog_loras": entries}
        if characters and i in characters:
            panel["characters"] = characters[i]
        panels.append(panel)
    return panels


def _write_render_manifest(directory, panels, story_id="cat-render"):
    path = os.path.join(str(directory), "manifest.json")
    with open(path, "w") as f:
        json.dump({"schema_version": 3, "story_id": story_id, "fps": 24, "panels": panels}, f)
    return path


class _RenderHarness(object):
    """bin/ltx-mlx-render's main() in-process with generate_video, probe_streams,
    assert_clips_uniform, build_concat_command, clip_frame_count and prepare_chain_seed stubbed
    (as tests/test_casting_pipeline.py's _CastHarness); every stub render writes 128 bytes
    unique to that call."""

    def __init__(self, monkeypatch, directory, panels):
        self.dir = str(directory)
        self.received = []
        self.renders = [0]
        self.manifest = _write_render_manifest(self.dir, panels)
        self.model = os.path.join(self.dir, "model-fixture")
        os.makedirs(self.model, exist_ok=True)
        with open(os.path.join(self.model, "split_model.json"), "w") as f:
            json.dump({"recipe": "ltx-2.5"}, f)
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
                            "--skip-input-screen", "--model", self.model, "--width", "64",
                            "--height", "64"] + list(extra))

    def loras(self, index):
        return [kw.get("loras") for i, kw in self.received if i == index][-1]


def _render_entries(tmp_path):
    fast = _entry(tmp_path, "fast-motion", "motion", 0.7, ["fastmo"])
    grain = _entry(tmp_path, "film-grain", "style", 0.8, ["grainfilm"])
    return fast, grain


def test_lct19_load_manifest_validates_catalog_loras(tmp_path):
    fast, grain = _render_entries(tmp_path)
    good = _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[fast, grain], [], [fast]]))
    assert render.load_manifest(good)["panels"][0]["catalog_loras"] == [fast, grain]
    cases = [
        ({"x": 1}, "panel 1: catalog_loras must be a list"),
        ([dict(fast, extra=1)], "panel 1: catalog_loras entry must have exactly the keys id, "
                                "kind, path, sha256, strength, triggers"),
        ([dict(fast, kind="character")], "panel 1: catalog_loras fast-motion: kind must be "
                                         "style, motion or physics, got 'character'"),
        ([dict(fast, path="/no/such.safetensors")], "panel 1: catalog_loras fast-motion: path is "
                                                    "not a readable file: '/no/such.safetensors'"),
        ([dict(fast, strength=3)], "panel 1: catalog_loras fast-motion: strength must be a number "
                                   "in (0, 2], got 3"),
        ([fast, fast], "panel 1: catalog_loras lists a LoRA twice"),
        ([grain, dict(grain, id="big-style")], "panel 1: catalog_loras has more than one style or "
                                               "motion/physics LoRA"),
    ]
    for entries, message in cases:
        path = _write_render_manifest(tmp_path, _chain_panels(tmp_path, [entries, [], []]))
        with pytest.raises(ValueError) as exc:
            render.load_manifest(path)
        assert str(exc.value) == message


def test_lct20_unit_lora_order(tmp_path, story_env):
    fast, grain = _render_entries(tmp_path)
    seu.kyra(story_env["lib"])
    video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    character = {"name": "kyra", "phrase": "the woman in grey", "trigger": "kyrawmn",
                 "video_lora": video, "strength": 1.0}
    panels = _chain_panels(tmp_path, [[fast, grain], [], []], characters={1: [character]})
    data = render.load_manifest(_write_render_manifest(tmp_path, panels))
    units = render.build_units(data["panels"], 0, str(tmp_path / "clips"),
                               global_loras=[{"path": "/g.safetensors", "strength": 0.5}])
    assert units[0]["loras"] == [
        {"kind": "global", "name": None, "path": "/g.safetensors", "strength": 0.5},
        {"kind": "catalog", "name": "fast-motion", "path": fast["path"], "strength": 0.7,
         "catalog_id": "fast-motion"},
        {"kind": "catalog", "name": "film-grain", "path": grain["path"], "strength": 0.8,
         "catalog_id": "film-grain"},
        {"kind": "character", "name": "kyra", "path": video, "strength": 1.0}]
    assert units[1]["loras"] == [{"kind": "global", "name": None, "path": "/g.safetensors",
                                  "strength": 0.5}]


def test_lct21_provenance(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(render, "model_identity", lambda model, strict=False: None)
    fast, _grain = _render_entries(tmp_path)
    global_lora = seu.lora_file(str(tmp_path / "files"), "global")
    args = render.build_parser().parse_args(["/m.json", "/o.mp4", "--model", "M"])
    unit = {"index": 1, "label": "panel-1", "seed": 1, "prompt": "p", "image_path": None,
            "clip_path": "/c/panel_01.mp4", "log_path": None, "conditioning": "t2v",
            "chain_source": None,
            "loras": [{"kind": "global", "name": None, "path": global_lora, "strength": 1.0}]}
    assert render.build_clip_provenance(unit, args) == {
        "schema_version": 2, "backend": "ltx-2-mlx", "model": "M", "model_identity": None,
        "gemma": args.gemma, "lora_path": None,
        "prompt_sha256": hashlib.sha256(b"p").hexdigest(), "conditioning": "t2v",
        "image_sha256": None, "chain_source_sha256": None, "chain_frame_index": None, "seed": 1,
        "width": args.width, "height": args.height, "frames": args.frames,
        "fps": args.frame_rate, "low_ram": True, "tile_frames": 1, "tile_spatial": 1,
        "loras": [{"kind": "global", "path": global_lora, "sha256": seu.sha256_file(global_lora),
                   "strength": 1.0}]}
    unit["loras"].append({"kind": "catalog", "name": "fast-motion", "path": fast["path"],
                          "strength": 0.7, "catalog_id": "fast-motion"})
    assert render.build_clip_provenance(unit, args)["loras"][1] == {
        "kind": "catalog", "path": fast["path"], "sha256": fast["sha256"], "strength": 0.7,
        "catalog_id": "fast-motion"}


def test_lct22_sha_and_duplicate_checks(tmp_path, monkeypatch, capsys, story_env):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    with open(fast["path"], "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x07")
    for extra in (["--dry-run"], []):
        assert harness.run(*extra) == 2
        assert capsys.readouterr().err == (
            "Error: panel 2: catalog LoRA fast-motion does not match its cataloged sha256; the "
            "file changed since bin/lora-catalog add (run bin/lora-catalog verify)\n")
    assert harness.received == []
    fast, grain = _render_entries(tmp_path / "again")
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    assert harness.run("--dry-run", "--lora", fast["path"] + ":0.5") == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion (panel 2) is also passed with --lora; pass it once\n")
    seu.kyra(story_env["lib"])
    video = os.path.join(story_env["lib"], "kyra", "lora", "video.safetensors")
    clash = dict(fast, path=video, sha256=seu.sha256_file(video))
    character = {"name": "kyra", "phrase": "p", "trigger": "kyrawmn", "video_lora": video,
                 "strength": 1.0}
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [clash], []],
                                                   characters={2: [character]}))
    assert harness.run("--dry-run") == 2
    assert capsys.readouterr().err == (
        "Error: catalog LoRA fast-motion (panel 2) is also character kyra's video LoRA\n")


def test_lct23_dry_run_lists_catalog_loras(tmp_path, monkeypatch, capsys):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path,
                             _chain_panels(tmp_path, [[fast, grain], [fast], []]))
    assert harness.run("--dry-run") == 0
    out = capsys.readouterr().out
    assert ("            lora: %s @ 0.7 (fast-motion)\n            lora: %s @ 0.8 (film-grain)\n"
            % (fast["path"], grain["path"])) in out
    command = [l for l in out.splitlines() if l.startswith("first render command: ")][0]
    assert (" --lora %s 0.7 --lora %s 0.8 --distilled " % (fast["path"], grain["path"])) in command


def test_lct24_per_panel_loras_reach_generate_video(tmp_path, monkeypatch):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[grain], [fast, grain],
                                                                             []]))
    assert harness.run() == 0
    assert harness.loras(1) == [(grain["path"], 0.8)]
    assert harness.loras(2) == [(fast["path"], 0.7), (grain["path"], 0.8)]
    assert harness.loras(3) is None


def test_lct25_resume_with_catalog_loras(tmp_path, monkeypatch):
    fast, grain = _render_entries(tmp_path)
    harness = _RenderHarness(monkeypatch, tmp_path, _chain_panels(tmp_path, [[], [fast], []]))
    assert harness.run() == 0
    assert [i for i, _kw in harness.received] == [1, 2, 3]
    harness.received[:] = []
    assert harness.run("--resume", "--force") == 0
    assert harness.received == []
    _write_render_manifest(tmp_path, _chain_panels(tmp_path, [[], [dict(fast, strength=0.8)], []]))
    assert harness.run("--resume", "--force") == 0
    assert [i for i, _kw in harness.received] == [2, 3]


def test_lct30_chained_manifest_per_panel_units(tmp_path, monkeypatch, capsys):
    fast, grain = _render_entries(tmp_path)
    panels = _chain_panels(tmp_path, [[grain], [fast, grain], [grain]])
    data = render.load_manifest(_write_render_manifest(tmp_path, panels))
    units = render.build_units(data["panels"], 0, str(tmp_path / "clips"))
    assert [[l["name"] for l in u["loras"]] for u in units] == [
        ["film-grain"], ["fast-motion", "film-grain"], ["film-grain"]]
    harness = _RenderHarness(monkeypatch, tmp_path, panels)
    assert harness.run("--dry-run", "--on-panel-failure", "stop") == 0
    assert "panel  2: I2V chained" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
8 failed, 23 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_lora_catalog.py::test_lct19_load_manifest_validates_catalog_loras
FAILED tests/test_lora_catalog.py::test_lct20_unit_lora_order
FAILED tests/test_lora_catalog.py::test_lct21_provenance
FAILED tests/test_lora_catalog.py::test_lct22_sha_and_duplicate_checks
FAILED tests/test_lora_catalog.py::test_lct23_dry_run_lists_catalog_loras
FAILED tests/test_lora_catalog.py::test_lct24_per_panel_loras_reach_generate_video
FAILED tests/test_lora_catalog.py::test_lct25_resume_with_catalog_loras
FAILED tests/test_lora_catalog.py::test_lct30_chained_manifest_per_panel_units
```

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: character %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, name, strength))
```

with:

```python
                if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                        or not 0 < strength <= 1.0):
                    raise ValueError("panel %d: character %s's strength must be a number in (0, 1], "
                                     "got %r" % (index, name, strength))

        if "catalog_loras" in panel:
            entries = panel["catalog_loras"]
            if not isinstance(entries, list):
                raise ValueError("panel %d: catalog_loras must be a list" % index)
            for entry in entries:
                problem = _catalog_lora_problem(entry)
                if problem:
                    raise ValueError("panel %d: catalog_loras %s" % (index, problem))
            ids = [entry["id"] for entry in entries]
            if len(set(ids)) != len(ids):
                raise ValueError("panel %d: catalog_loras lists a LoRA twice" % index)
            if (sum(1 for e in entries if e["kind"] == "style") > 1
                    or sum(1 for e in entries if e["kind"] != "style") > 1):
                raise ValueError("panel %d: catalog_loras has more than one style or "
                                 "motion/physics LoRA" % index)
```

**3.2.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
def resolve_prompt(panel):
```

with:

```python
_CATALOG_ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
_CATALOG_SHA_RE = re.compile(r"[0-9a-f]{64}")
_CATALOG_ENTRY_KEYS = {"id", "kind", "path", "sha256", "strength", "triggers"}


def _catalog_lora_problem(entry):
    """None, or what is wrong with one manifest catalog_loras entry (robust story spec LC15)."""
    if not isinstance(entry, dict) or set(entry) != _CATALOG_ENTRY_KEYS:
        return "entry must have exactly the keys id, kind, path, sha256, strength, triggers"
    if not isinstance(entry["id"], str) or not _CATALOG_ID_RE.fullmatch(entry["id"]):
        return "id must match [a-z][a-z0-9-]{1,31}, got %r" % (entry["id"],)
    if entry["kind"] not in ("style", "motion", "physics"):
        return "%s: kind must be style, motion or physics, got %r" % (entry["id"], entry["kind"])
    path = entry["path"]
    if (not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path)
            or not os.access(path, os.R_OK)):
        return "%s: path is not a readable file: %r" % (entry["id"], path)
    if not isinstance(entry["sha256"], str) or not _CATALOG_SHA_RE.fullmatch(entry["sha256"]):
        return "%s: sha256 must be 64 lowercase hex characters" % entry["id"]
    strength = entry["strength"]
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 < strength <= 2:
        return "%s: strength must be a number in (0, 2], got %r" % (entry["id"], strength)
    if not isinstance(entry["triggers"], list) or not all(isinstance(t, str) for t in entry["triggers"]):
        return "%s: triggers must be a list of strings" % entry["id"]
    return None


def resolve_prompt(panel):
```

**3.3.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
        loras = [{"kind": "global", "name": None, "path": g["path"], "strength": g["strength"]}
                 for g in global_loras]
```

with:

```python
        loras = [{"kind": "global", "name": None, "path": g["path"], "strength": g["strength"]}
                 for g in global_loras]
        loras += [{"kind": "catalog", "name": e["id"], "path": e["path"],
                   "strength": float(e["strength"]), "catalog_id": e["id"]}
                  for e in (panel.get("catalog_loras") or [])]
```

**3.4.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
    if unit.get("loras"):
        provenance["loras"] = [{"kind": l["kind"], "path": l["path"],
                                "sha256": lora_sha256(l["path"]), "strength": l["strength"]}
                               for l in unit["loras"]]
    return provenance
```

with:

```python
    if unit.get("loras"):
        provenance["loras"] = []
        for l in unit["loras"]:
            entry = {"kind": l["kind"], "path": l["path"], "sha256": lora_sha256(l["path"]),
                     "strength": l["strength"]}
            if l["kind"] == "catalog":
                entry["catalog_id"] = l["catalog_id"]
            provenance["loras"].append(entry)
    return provenance
```

**3.5.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
    cast_entries = [(p["index"], c) for p in panels for c in (p.get("characters") or [])]
    args.global_loras = []
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries:
```

with:

```python
    cast_entries = [(p["index"], c) for p in panels for c in (p.get("characters") or [])]
    catalog_entries = [(p["index"], e) for p in panels for e in (p.get("catalog_loras") or [])]
    args.global_loras = []
    if len(parsed) == 1 and parsed[0][1] == 1.0 and not cast_entries and not catalog_entries:
```

**3.6.** Edit `bin/ltx-mlx-render`: replace this text, which occurs exactly once:

```python
            if real in seen:
                print("Error: --lora %s is also character %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], c["name"], index), file=sys.stderr)
                return 2
```

with:

```python
            if real in seen:
                print("Error: --lora %s is also character %s's video LoRA (panel %d); pass it "
                      "once" % (seen[real], c["name"], index), file=sys.stderr)
                return 2
    if catalog_entries:
        global_reals = set(os.path.realpath(g["path"]) for g in args.global_loras)
        by_index = dict((p["index"], p) for p in panels)
        for index, entry in catalog_entries:
            real = os.path.realpath(entry["path"])
            if real in global_reals:
                print("Error: catalog LoRA %s (panel %d) is also passed with --lora; pass it once"
                      % (entry["id"], index), file=sys.stderr)
                return 2
            for c in by_index[index].get("characters") or []:
                if os.path.realpath(c["video_lora"]) == real:
                    print("Error: catalog LoRA %s (panel %d) is also character %s's video LoRA"
                          % (entry["id"], index, c["name"]), file=sys.stderr)
                    return 2
        checked = set()
        for index, entry in catalog_entries:
            real = os.path.realpath(entry["path"])
            if real in checked:
                continue
            checked.add(real)
            if lora_sha256(entry["path"]) != entry["sha256"]:
                print("Error: panel %d: catalog LoRA %s does not match its cataloged sha256; the "
                      "file changed since bin/lora-catalog add (run bin/lora-catalog verify)"
                      % (index, entry["id"]), file=sys.stderr)
                return 2
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_lora_catalog.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
31 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_lora_catalog.py bin/ltx-mlx-render && echo py39-ok
python3 -m py_compile tests/test_lora_catalog.py bin/ltx-mlx-render && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_lora_catalog.py bin/ltx-mlx-render
git diff --cached --name-only
git commit -m "ltx-mlx-render: per-panel catalog LoRAs, provenance and checks (catalog LC17)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/ltx-mlx-render
qwen-agent-workspace/tests/test_lora_catalog.py
```


---

### Task 16: bin/judge-story --patches and the bin/iterate-story deprecation wrapper

Implements RS32, RS33. Tests RST48, RST49.

**Files:**
- Modify: `tests/test_story_engine.py`
- Modify: `bin/judge-story`
- Modify: `bin/iterate-story`

**Interfaces:**
- Consumes: `story_engine.build_critic_prompt` (Task 7, loaded by path into a namespace).
- Produces: In `bin/judge-story`: `REVIEW_TOOL_NAME`, `REVIEW_TOOL_DESCRIPTION`, `REVIEW_SCORE_KEYS`, `PATCH_FIELDS`, `SUBMIT_REVIEW_SCHEMA`, `PATCH_SYSTEM_PROMPT_TEMPLATE`, `RETRY_REVIEW_MESSAGE`, `find_tool_use(response, name=TOOL_NAME)`, `_create_message(client, system_prompt, messages, tool=None)`, `_story_engine() -> dict`, `_story_checks_messages(story_dir)`, `main_patches(args, story_dir, story_md_path)`, the `--patches` flag. In `bin/iterate-story`: `DEPRECATION_NOTICE`, `_robust_plan(story_dir)`, `build_engine_cmd(story_id, plan, goal=None, story_model=None, story_context_window=None)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst48_judge_story_patches`, `test_rst49_iterate_story_wrapper`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST48, RST49: bin/judge-story --patches, bin/iterate-story (RS32, RS33) --------------------

judge_story = importlib.machinery.SourceFileLoader(
    "judge_story_for_story_engine", os.path.join(WS, "bin", "judge-story")).load_module()
iterate_story = importlib.machinery.SourceFileLoader(
    "iterate_story_for_story_engine", os.path.join(WS, "bin", "iterate-story")).load_module()


class _FakeAnthropic(object):
    """Stands in for anthropic.Anthropic (the tests/test_judge_story.py pattern)."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.messages = type("M", (), {})()
        self.messages.create = self._create

    def __call__(self, *args, **kwargs):
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.scripted.pop(0)


def _anthropic_message(name, tool_input):
    import anthropic
    return anthropic.types.Message.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": "tool_use", "stop_sequence": None,
        "content": [{"type": "tool_use", "id": "toolu_test", "name": name, "input": tool_input}],
        "usage": {"input_tokens": 100, "output_tokens": 50}})


def test_rst48_judge_story_patches(ws, monkeypatch, capsys, tmp_path):
    ctx, text = _saved_story(ws, monkeypatch)
    story_md = os.path.join(ctx.story_dir, "story.md")
    checks = {"hard": [{"message": "panel 2: N7 dialogue and text: Motion: says 'yells'"}],
              "advisory": [{"message": "panel 3: N13 repeat: Motion: repeats panel 2's action "
                                       "(similarity 0.71)"}]}
    with open(os.path.join(ctx.story_dir, "story_checks.json"), "w") as f:
        json.dump(checks, f)
    review = {"scores": {"renderability": 6, "continuity": 8, "story": 7}, "verdict": "revise",
              "patches": [{"target": "panel", "index": 2, "field": "motion", "reason": "dialogue",
                           "replacement": "The courier pedals on."}]}
    fake = _FakeAnthropic([_anthropic_message("submit_review", review)])
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    monkeypatch.setattr(judge_story, "WS", WS)
    assert judge_story.main(["--story-md", story_md, "--patches"]) == 0
    kwargs = fake.calls[0]
    assert kwargs["system"] == judge_story.PATCH_SYSTEM_PROMPT_TEMPLATE.replace(
        "@@GOAL@@", judge_story.DEFAULT_GOAL)
    assert kwargs["tools"] == [{"name": "submit_review", "description": (
        "Submit your review of the story: three 1-10 scores, a verdict, and at most 8 patches. "
        "You must call this exactly once."), "input_schema": judge_story.SUBMIT_REVIEW_SCHEMA}]
    plan = _read_json(os.path.join(ctx.story_dir, "plan.json"))
    assert kwargs["messages"] == [{"role": "user", "content": se.build_critic_prompt(
        plan, text, ([checks["hard"][0]["message"]], [checks["advisory"][0]["message"]]),
        for_judge=True)}]
    judgment = _read_json(os.path.join(ctx.story_dir, "judgment.patches.json"))
    assert list(judgment) == ["story_md_path", "plan_path", "model", "effort", "goal", "timestamp",
                              "usage", "scores", "verdict", "patches"]
    assert list(judgment["scores"]) == ["continuity", "story", "renderability"]
    assert judgment["patches"] == review["patches"]
    assert capsys.readouterr().out == ("Scores:\n  continuity      8\n  story           7\n"
                                       "  renderability   6\n\nVerdict: revise\nPatches: 1\n")
    os.remove(os.path.join(ctx.story_dir, "plan.json"))
    assert judge_story.main(["--story-md", story_md, "--patches"]) == 2
    assert capsys.readouterr().err == (
        "Error: plan.json not found: %s. --patches needs a story written by bin/ltx-movie's "
        "default story engine.\n" % os.path.join(ctx.story_dir, "plan.json"))
    with pytest.raises(SystemExit) as exc:
        judge_story.main(["--story-md", story_md, "--patches", "--target-panels", "3"])
    assert exc.value.code == 2
    assert "--patches cannot be combined with --target-panels" in capsys.readouterr().err
    with open(os.path.join(ctx.story_dir, "story_prompt.txt"), "w") as f:
        f.write("PROMPT")
    judgment_input = {"scores": dict((k, 7) for k in judge_story.SCORE_KEYS), "critique": "c",
                      "revised_prompt": "r"}
    fake = _FakeAnthropic([_anthropic_message("submit_judgment", judgment_input)])
    monkeypatch.setattr(judge_story.anthropic, "Anthropic", fake)
    assert judge_story.main(["--story-md", story_md]) == 0
    assert fake.calls[0]["system"] == judge_story.SYSTEM_PROMPT
    assert fake.calls[0]["tools"][0]["name"] == "submit_judgment"
    assert list(_read_json(os.path.join(ctx.story_dir, "judgment.json"))) == [
        "story_md_path", "story_prompt_path", "model", "effort", "goal", "timestamp", "usage",
        "scores", "critique", "revised_prompt"]


class _Completed(object):
    def __init__(self, returncode, stdout):
        self.returncode, self.stdout = returncode, stdout


def test_rst49_iterate_story_wrapper(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    story_dir = tmp_path / "generated" / "stories" / "it1"
    story_dir.mkdir(parents=True)
    plan = {"schema": "ltx-movie.plan.v1", "mode": "shots", "panels": 4,
            "narrative": "A ronin at dusk.", "seed_image": "/s/seed.png", "goal": "plan goal",
            "cast": [{"id": "c1", "cast_name": "kyra"}, {"id": "c2", "cast_name": None},
                     {"id": "c3", "cast_name": "ronin"}],
            "loras": {"pinned": [{"path": "/p/a.safetensors", "strength": 1.0},
                                 {"path": "/p/b.safetensors", "strength": 0.5}]}}
    (story_dir / "plan.json").write_text(json.dumps(plan))
    calls = []
    monkeypatch.setattr(iterate_story, "_run",
                        lambda cmd: calls.append(cmd) or _Completed(3, "engine output\n"))
    rc = iterate_story.main(["--story-id", "it1", "--threshold", "8", "--goal", "cli goal",
                             "--story-model", "M", "--story-context-window", "9000"])
    assert rc == 3
    assert calls == [[sys.executable, os.path.join(str(tmp_path), "bin", "ltx-movie"),
                      "A ronin at dusk.", "--story-id", "it1", "--panels", "4", "--shots",
                      "--character", "kyra", "--character", "ronin", "--seed-image",
                      "/s/seed.png", "--lora", "/p/a.safetensors:1.0", "--lora",
                      "/p/b.safetensors:0.5", "--goal", "cli goal", "--force-story",
                      "--no-review", "--story-only", "--judge", "--story-model", "M",
                      "--story-context-window", "9000"]]
    out, err = capsys.readouterr()
    assert out == "engine output\n"
    assert err == (iterate_story.DEPRECATION_NOTICE + "\niterate-story: --threshold and "
                   "--max-rounds are ignored on the default engine; its thresholds are fixed\n")
    assert "=== round 1: ltx-movie ===" in (story_dir / "iterate-story.log").read_text()
    plan.update(mode="no_stills", goal=None, seed_image=None)
    (story_dir / "plan.json").write_text(json.dumps(plan))
    iterate_story.main(["--story-id", "it1", "--threshold", "8"])
    assert calls[-1][7] == "--no-stills" and "--goal" not in calls[-1]
    capsys.readouterr()
    (story_dir / "plan.json").unlink()
    assert iterate_story.main(["--story-id", "it1", "--threshold", "8"]) == 2
    out, err = capsys.readouterr()
    assert err.startswith("Error: story.md not found") and iterate_story.DEPRECATION_NOTICE not in err
    (story_dir / "story.md").write_text("## Panel 1 — A\nMotion: x\n")
    (story_dir / "story_prompt.txt").write_text("P")
    monkeypatch.setattr(iterate_story, "_run", lambda cmd: _Completed(1, "judge failed"))
    assert iterate_story.main(["--story-id", "it1", "--threshold", "8"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(iterate_story.DEPRECATION_NOTICE + "\nError: round 1: judge-story "
                          "exited 1")
```

- [ ] **Step 2: Run the tests and confirm they fail as shown.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_judge_story.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_iterate_story.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected last lines, one per command, in order (the warning count and the duration are left out; they vary):

```
2 failed, 70 passed
22 passed
18 passed
```

The failing tests are exactly these (any other failure is a stop-and-report):

```
FAILED tests/test_story_engine.py::test_rst48_judge_story_patches
FAILED tests/test_story_engine.py::test_rst49_iterate_story_wrapper
```

`tests/test_judge_story.py` and `tests/test_iterate_story.py` pass before and after Step 3: the default modes are unchanged.

- [ ] **Step 3: Implement.**

**3.1.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores, critique, and revised_prompt. Do not reply with "
                      "plain text.")
```

with:

```python
RETRY_USER_MESSAGE = ("You did not call the submit_judgment tool. Call submit_judgment now "
                      "with your scores, critique, and revised_prompt. Do not reply with "
                      "plain text.")

# --patches (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md RS32): review a
# story written by bin/ltx-movie's default engine and return per-panel patches.
REVIEW_TOOL_NAME = "submit_review"
REVIEW_TOOL_DESCRIPTION = ("Submit your review of the story: three 1-10 scores, a verdict, and at "
                           "most 8 patches. You must call this exactly once.")
REVIEW_SCORE_KEYS = ("continuity", "story", "renderability")
PATCH_FIELDS = ("beat.action", "beat.shot", "beat.camera", "location.setting", "lora", "motion",
                "image", "prompt", "narration")
SUBMIT_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {key: {"type": "integer", "minimum": 1, "maximum": 10}
                           for key in REVIEW_SCORE_KEYS},
            "required": list(REVIEW_SCORE_KEYS),
        },
        "verdict": {"type": "string", "enum": ["ok", "revise"]},
        "patches": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["plan", "panel"]},
                    "index": {"type": "integer", "minimum": 0},
                    "field": {"type": "string", "enum": list(PATCH_FIELDS)},
                    "reason": {"type": "string"},
                    "replacement": {},
                },
                "required": ["target", "index", "field", "reason", "replacement"],
            },
        },
    },
    "required": ["scores", "verdict", "patches"],
}
PATCH_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert story editor reviewing a story written for an AI image-and-video "
    "generation pipeline. The target output goal is @@GOAL@@.\n"
    "\n"
    "The user message holds the movie's plan, its story.md and the problems the pipeline's own "
    "checks found. Score the story and propose at most 8 exact patches, following the "
    "instructions in the user message.\n"
    "\n"
    "You must deliver your review by calling the submit_review tool exactly once. Do not put the "
    "review in a plain text reply; a response without a submit_review call is a failure.")
RETRY_REVIEW_MESSAGE = ("You did not call the submit_review tool. Call submit_review now with "
                        "your scores, verdict and patches. Do not reply with plain text.")
```

**3.2.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
def find_tool_use(response):
    """First content block that is a submit_judgment tool call, else None."""
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None
```

with:

```python
def find_tool_use(response, name=TOOL_NAME):
    """First content block that is a call of the named tool (submit_judgment), else None."""
    for block in response.content:
        if block.type == "tool_use" and block.name == name:
            return block
    return None
```

**3.3.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
                       help="instruct the judge that revised_prompt must target exactly N "
                            "panels (used by bin/iterate-story to keep the panel count "
                            "stable across rounds)")
```

with:

```python
                       help="instruct the judge that revised_prompt must target exactly N "
                            "panels (used by bin/iterate-story to keep the panel count "
                            "stable across rounds)")
    parser.add_argument("--patches", action="store_true", default=False,
                        help="review a story written by bin/ltx-movie's default engine: read the "
                             "sibling plan.json and story_checks.json and return per-panel "
                             "patches (judgment.patches.json) instead of a revised prompt")
```

**3.4.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
def _create_message(client, system_prompt, messages):
    """One non-streaming judging call with the fixed spec 4.1 parameters and the given
    system prompt. No temperature, top_k, or top_p: extended thinking rejects non-default
    values."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=system_prompt,
        tools=[{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": SUBMIT_JUDGMENT_SCHEMA,
        }],
```

with:

```python
def _create_message(client, system_prompt, messages, tool=None):
    """One non-streaming judging call with the fixed spec 4.1 parameters and the given
    system prompt. No temperature, top_k, or top_p: extended thinking rejects non-default
    values. tool replaces the submit_judgment tool definition (--patches)."""
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        system=system_prompt,
        tools=[tool or {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": SUBMIT_JUDGMENT_SCHEMA,
        }],
```

**3.5.** Edit `bin/judge-story`: replace this text, which occurs exactly once:

```python
def main(argv=None):
    args = build_parser().parse_args(argv)
    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id, args.story_md)

    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
```

with:

```python
def _story_engine():
    """story_engine.py's namespace, loaded by path from WS (robust story spec RS32). The file is
    executed into a fresh dict rather than imported, so this script gains no import statement
    (spec RSK3)."""
    path = os.path.join(WS, "story_engine.py")
    namespace = {"__name__": "story_engine_for_judge", "__file__": path}
    with open(path, encoding="utf-8") as f:
        exec(compile(f.read(), path, "exec"), namespace)
    return namespace


def _story_checks_messages(story_dir):
    """(hard, advisory) messages from the sibling story_checks.json; ([], []) when it is absent
    or unreadable."""
    try:
        with open(os.path.join(story_dir, "story_checks.json"), encoding="utf-8") as f:
            checks = json.load(f)
        return ([v["message"] for v in checks["hard"]],
                [v["message"] for v in checks["advisory"]])
    except Exception:
        return [], []


def main_patches(args, story_dir, story_md_path):
    """--patches: per-panel patches for a robust-engine story (robust story spec RS32)."""
    plan_path = os.path.join(story_dir, "plan.json")
    if not os.path.isfile(plan_path):
        print("Error: plan.json not found: %s. --patches needs a story written by bin/ltx-movie's "
              "default story engine." % plan_path, file=sys.stderr)
        return 2
    with open(story_md_path, encoding="utf-8") as f:
        story_md_text = f.read()
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except ValueError as e:
        print("Error: plan.json is not valid JSON: %s: %s" % (plan_path, e), file=sys.stderr)
        return 2
    violations = _story_checks_messages(story_dir)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set; export it in your environment to run "
              "judge-story.", file=sys.stderr)
        return 1
    client = anthropic.Anthropic()
    user_message = _story_engine()["build_critic_prompt"](plan, story_md_text, violations,
                                                          catalog_lines=None, for_judge=True)
    goal = DEFAULT_GOAL if args.goal is None else args.goal
    system_prompt = PATCH_SYSTEM_PROMPT_TEMPLATE.replace(GOAL_TOKEN, goal)
    tool = {"name": REVIEW_TOOL_NAME, "description": REVIEW_TOOL_DESCRIPTION,
            "input_schema": SUBMIT_REVIEW_SCHEMA}
    responses = []
    try:
        responses.append(_create_message(client, system_prompt,
                                         [{"role": "user", "content": user_message}], tool))
        block = find_tool_use(responses[0], REVIEW_TOOL_NAME)
        if block is None:
            responses.append(_create_message(client, system_prompt, [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": responses[0].content},
                {"role": "user", "content": RETRY_REVIEW_MESSAGE},
            ], tool))
            block = find_tool_use(responses[1], REVIEW_TOOL_NAME)
    except anthropic.APIError as e:
        print("Error: Anthropic API call failed: %s: %s" % (type(e).__name__, e),
              file=sys.stderr)
        return 1
    if block is None:
        raw_path = _write_raw(story_dir, responses)
        print("Error: Claude did not call submit_review after one retry; raw responses "
              "written to %s" % raw_path, file=sys.stderr)
        return 1
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        jsonschema.validate(instance=block.input, schema=SUBMIT_REVIEW_SCHEMA)
    except jsonschema.ValidationError as e:
        _write_raw(story_dir, responses)
        print("Error: submit_review input failed schema validation: %s" % e.message,
              file=sys.stderr)
        return 1
    review = block.input
    thinking_counts = [r.usage.output_tokens_details.thinking_tokens for r in responses
                       if r.usage.output_tokens_details is not None
                       and r.usage.output_tokens_details.thinking_tokens is not None]
    judgment = {
        "story_md_path": story_md_path,
        "plan_path": plan_path,
        "model": MODEL,
        "effort": EFFORT,
        "goal": goal,
        "timestamp": timestamp,
        "usage": {
            "input_tokens": sum(r.usage.input_tokens for r in responses),
            "output_tokens": sum(r.usage.output_tokens for r in responses),
            "thinking_tokens": sum(thinking_counts) if thinking_counts else None,
        },
        "scores": {name: review["scores"][name] for name in REVIEW_SCORE_KEYS},
        "verdict": review["verdict"],
        "patches": review["patches"],
    }
    with open(os.path.join(story_dir, "judgment.patches.json"), "w", encoding="utf-8") as f:
        json.dump(judgment, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("Scores:")
    for name in REVIEW_SCORE_KEYS:
        print("  %-14s  %d" % (name, judgment["scores"][name]))
    print()
    print("Verdict: %s" % judgment["verdict"])
    print("Patches: %d" % len(judgment["patches"]))
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.patches and args.target_panels is not None:
        parser.error("--patches cannot be combined with --target-panels")
    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id, args.story_md)

    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
    if args.patches:
        return main_patches(args, story_dir, story_md_path)
```

**3.6.** Edit `bin/iterate-story`: replace this text, which occurs exactly once:

```python
# The one panel-count sentence removed from the judge's revised_prompt (spec 3.2, G19).
```

with:

```python
DEPRECATION_NOTICE = ("iterate-story is deprecated: bin/ltx-movie's default story engine now "
                      "checks, critiques and patches the story itself (add --judge for the "
                      "Claude gate).")
# The one panel-count sentence removed from the judge's revised_prompt (spec 3.2, G19).
```

**3.7.** Edit `bin/iterate-story`: replace this text, which occurs exactly once:

```python
def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.threshold <= 10:
        parser.error("--threshold must be an integer from 1 to 10")
    if args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1")

    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id)
```

with:

```python
def _robust_plan(story_dir):
    """<story_dir>/plan.json when bin/ltx-movie's default engine wrote it, else None."""
    try:
        with open(os.path.join(story_dir, "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    return plan if isinstance(plan, dict) and plan.get("schema") == "ltx-movie.plan.v1" else None


def build_engine_cmd(story_id, plan, goal=None, story_model=None, story_context_window=None):
    """The bin/ltx-movie argv that regenerates a default-engine story with the --judge gate
    (robust story spec RS33)."""
    cmd = [sys.executable, os.path.join(WS, "bin", "ltx-movie"), plan["narrative"],
           "--story-id", story_id, "--panels", str(plan["panels"])]
    if plan["mode"] == "shots":
        cmd.append("--shots")
    elif plan["mode"] == "no_stills":
        cmd.append("--no-stills")
    for entry in plan["cast"]:
        if entry.get("cast_name"):
            cmd += ["--character", entry["cast_name"]]
    if plan.get("seed_image"):
        cmd += ["--seed-image", plan["seed_image"]]
    for pin in plan["loras"].get("pinned", []):
        cmd += ["--lora", "%s:%s" % (pin["path"], repr(float(pin["strength"])))]
    if goal or plan.get("goal"):
        cmd += ["--goal", goal or plan["goal"]]
    cmd += ["--force-story", "--no-review", "--story-only", "--judge"]
    if story_model is not None:
        cmd += ["--story-model", story_model]
    if story_context_window is not None:
        cmd += ["--story-context-window", str(story_context_window)]
    return cmd


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.threshold <= 10:
        parser.error("--threshold must be an integer from 1 to 10")
    if args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1")

    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id)
    plan = _robust_plan(story_dir)
    if plan is not None:
        print(DEPRECATION_NOTICE, file=sys.stderr)
        print("iterate-story: --threshold and --max-rounds are ignored on the default engine; its "
              "thresholds are fixed", file=sys.stderr)
        cmd = build_engine_cmd(args.story_id, plan, args.goal, args.story_model,
                               args.story_context_window)
        result = _run(cmd)
        _log_run(story_dir, 1, "ltx-movie", cmd, result)
        sys.stdout.write(result.stdout or "")
        return result.returncode
```

**3.8.** Edit `bin/iterate-story`: replace this text, which occurs exactly once:

```python
        print('Error: no "## Panel" headers found in story.md: %s; cannot pin the panel '
              'count.' % story_md_path, file=sys.stderr)
        return 2
```

with:

```python
        print('Error: no "## Panel" headers found in story.md: %s; cannot pin the panel '
              'count.' % story_md_path, file=sys.stderr)
        return 2
    print(DEPRECATION_NOTICE, file=sys.stderr)
```

- [ ] **Step 4: Run the tests and confirm they pass.**

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_judge_story.py -q -p no:cacheprovider 2>&1 | tail -1
python3 -m pytest tests/test_iterate_story.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected:

```
72 passed
22 passed
18 passed
```

- [ ] **Step 5: Compile every changed file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py bin/judge-story bin/iterate-story && echo py39-ok
python3 -m py_compile tests/test_story_engine.py bin/judge-story bin/iterate-story && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_story_engine.py bin/judge-story bin/iterate-story
git diff --cached --name-only
git commit -m "judge-story --patches; iterate-story wraps the default engine (story RS32, RS33)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/bin/iterate-story
qwen-agent-workspace/bin/judge-story
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 17: Regression guards: both interpreters, import sets, test isolation

Implements RST61, RST62, RST63 as tests (RSK2-RSK4).

**Files:**
- Modify: `tests/test_story_engine.py`

**Interfaces:**
- Consumes: Every file of Tasks 2-16.
- Produces: In the test module: `CHANGED_FILES`, `COMPILE_ONLY`, `_all_imports(path)`.

- [ ] **Step 1: Write the failing tests.**

New tests in this task: `test_rst61_both_interpreters_compile_every_changed_file`, `test_rst62_import_sets`, `test_rst63_isolation`.

**1.1.** Append to `tests/test_story_engine.py` (two empty lines after its current last line, then this block, which ends with a newline):

```python
# --- RST61-RST63: interpreters, imports, isolation (RSK2-RSK4) --------------------------------

CHANGED_FILES = ("story_engine.py", "lora_catalog.py", "bin/lora-catalog", "bin/ltx-movie",
                 "bin/ltx-story-manifest", "bin/ltx-story-images", "bin/ltx-mlx-render",
                 "bin/judge-story", "bin/iterate-story", "scripts/deploy/build_pkg.py",
                 "tests/story_engine_testutil.py", "tests/test_story_engine.py",
                 "tests/test_lora_catalog.py", "tests/test_ltx_movie_offline.py",
                 "tests/test_casting_regression.py", "tests/test_casting_pipeline.py",
                 "tests/test_shots_mode.py", "tests/test_deploy_pkg.py")
COMPILE_ONLY = ("import sys\n"
                "for path in sys.argv[1:]:\n"
                "    with open(path, encoding='utf-8') as f:\n"
                "        compile(f.read(), path, 'exec')\n"
                "print('compiled %d' % (len(sys.argv) - 1))\n")


def test_rst61_both_interpreters_compile_every_changed_file():
    paths = [os.path.join(WS, rel) for rel in CHANGED_FILES]
    for interpreter in ("/usr/bin/python3", sys.executable):
        proc = subprocess.run([interpreter, "-c", COMPILE_ONLY] + paths, capture_output=True,
                              text=True)
        assert (proc.returncode, proc.stdout) == (0, "compiled %d\n" % len(paths)), (
            interpreter, proc.stderr)


def _all_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    return names


def test_rst62_import_sets():
    assert _top_level_imports(os.path.join(WS, "bin", "lora-catalog")) == {
        "argparse", "json", "os", "sys", "lora_catalog"}
    baseline = {
        "bin/ltx-movie": {"argparse", "glob", "importlib.machinery", "json", "os", "pipeline_log",
                          "shlex", "subprocess", "sys", "threading", "time"},
        "bin/ltx-story-images": {"argparse", "importlib.machinery", "json", "os", "pipeline_log",
                                 "sys", "time"},
        "bin/ltx-mlx-render": {"argparse", "datetime", "glob", "hashlib", "json",
                               "ltx2_mlx_video_skill", "os", "re", "shlex", "shutil", "stat",
                               "subprocess", "sys", "time", "uuid"},
        "bin/judge-story": {"anthropic", "argparse", "datetime", "json", "jsonschema", "os", "sys"},
        "bin/ltx-story-manifest": {"PIL", "argparse", "datetime", "glob", "importlib.machinery",
                                   "json", "os", "re", "sys"},
    }
    for rel, names in baseline.items():
        assert _top_level_imports(os.path.join(WS, rel)) == names, rel
    for rel in ("bin/ltx-mlx-render", "bin/judge-story"):
        assert _all_imports(os.path.join(WS, rel)) == baseline[rel], rel
    assert _all_imports(os.path.join(WS, "story_engine.py")) == _top_level_imports(
        os.path.join(WS, "story_engine.py"))


def test_rst63_isolation(story_env):
    assert os.environ["HOME"] == story_env["home"]
    assert os.environ["CHARACTER_LIBRARY_DIR"] == story_env["lib"]
    assert os.environ["LORA_CATALOG_DIR"] == story_env["catalog"]
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", os.environ["QWEN_AGENT_DAEMON_URL"])
    assert os.environ["STORY_PIPELINE_LOGGED"] == "1"
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert seu._stat_or_none(seu.REAL_CATALOG) == seu.REAL_CATALOG_STAT
    for module in ("tests/test_story_engine.py", "tests/test_lora_catalog.py"):
        with open(os.path.join(WS, module), encoding="utf-8") as f:
            source = f.read()
        assert "@pytest.fixture(autouse=True)\ndef story_env(monkeypatch, tmp_path):\n    return " \
               "seu.set_story_env(monkeypatch, tmp_path)\n" in source
```

- [ ] **Step 2: Run the guards; they pass at once.**

These tests add no behaviour: they pin what Tasks 2-16 built (both interpreters, the import sets, the test isolation), so there is no RED step and no Step 3.

```bash
python3 -m pytest tests/test_story_engine.py -q -p no:cacheprovider 2>&1 | tail -1
```

Expected (the warning count and the duration are left out):

```
75 passed
```

- [ ] **Step 3: Compile the changed test file under both interpreters.**

```bash
/usr/bin/python3 -m py_compile tests/test_story_engine.py && echo py39-ok
python3 -m py_compile tests/test_story_engine.py && echo py313-ok
```

Expected: `py39-ok` then `py313-ok`.

- [ ] **Step 4: Commit.**

```bash
git add tests/test_story_engine.py
git diff --cached --name-only
git commit -m "tests: dual-interpreter compile, import sets, isolation sentinel (story RS1; catalog LC1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected `git diff --cached --name-only` output, exactly:

```
qwen-agent-workspace/tests/test_story_engine.py
```


---

### Task 18: Regression, dual-interpreter compile, imports, untouched files, legacy byte-identity, design review (no code)

Implements RST60-RST63 against the whole tree and the deliverable check of spec 0.3/5.6. No file is changed; nothing is committed unless a defect is found (then fix it in the task that owns it, with that task's commit prefix, and re-run this task).

**Files:** none modified. Reads Task 1's records.

**Interfaces:** Consumes every earlier task. Produces `/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story/final-pytest.txt`.

- [ ] **Step 1: RST60, the full suite (about 10 min).**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story
python3 -m pytest tests/ -q -rA -p no:cacheprovider > $D/final-pytest.txt 2>&1
tail -1 $D/final-pytest.txt
grep -E '^(FAILED|ERROR|SKIPPED)' $D/final-pytest.txt
comm -23 <(grep '^PASSED' $D/baseline-pytest.txt | sort) <(grep '^PASSED' $D/final-pytest.txt | sort)
comm -13 <(grep '^PASSED' $D/baseline-pytest.txt | sort) <(grep '^PASSED' $D/final-pytest.txt | sort) | wc -l
```

Expected (observed): `1 failed, 1367 passed, 1 skipped, ... warnings in ...` (the baseline's passes plus 106); the only `FAILED` line is `FAILED tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and the only `SKIPPED` line is `SKIPPED [1] tests/test_fleet_lib.py:272: no fleet.env on this host`; the first `comm` prints nothing (every baseline pass still passes, including every Section 5.5 migrated test); the second prints `106` (75 in `tests/test_story_engine.py`, 31 in `tests/test_lora_catalog.py`). With a different baseline (Task 1's notes), the rule is the same: no lost pass, and exactly 106 new passes.

- [ ] **Step 2: RSK1's plain scripts.**

```bash
D=/Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story
for f in test_ltx_movie_offline test_ltx_mlx_render test_ltx_story_images test_ltx2_mlx_video_skill test_ltx_image_fit test_ltx_story_manifest_chain test_ltx_chain test_ltx_multiframe test_ltx_t2v_offline test_ltx_story_video test_mps_guard_metric test_qwen_agent_context_budget test_qwen_agent_image_oneshot test_qwen_agent_session_memory test_qwen_agent_danger_auto_approve; do
  printf '%s: ' "$f"; python3 tests/$f.py 2>&1 | tail -1
done | diff $D/baseline-scripts.txt - && echo scripts-same
```

Expected: `scripts-same` (`test_ltx_movie_offline: OK 344/344` and every other line as in Task 1).

- [ ] **Step 3: RST61, both interpreters on every new or changed file.**

```bash
/usr/bin/python3 -m py_compile story_engine.py lora_catalog.py bin/lora-catalog bin/ltx-movie bin/ltx-story-manifest bin/ltx-story-images bin/ltx-mlx-render bin/judge-story bin/iterate-story scripts/deploy/build_pkg.py tests/story_engine_testutil.py tests/test_story_engine.py tests/test_lora_catalog.py tests/test_ltx_movie_offline.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_shots_mode.py tests/test_deploy_pkg.py && echo py39-ok
python3 -m py_compile story_engine.py lora_catalog.py bin/lora-catalog bin/ltx-movie bin/ltx-story-manifest bin/ltx-story-images bin/ltx-mlx-render bin/judge-story bin/iterate-story scripts/deploy/build_pkg.py tests/story_engine_testutil.py tests/test_story_engine.py tests/test_lora_catalog.py tests/test_ltx_movie_offline.py tests/test_casting_regression.py tests/test_casting_pipeline.py tests/test_shots_mode.py tests/test_deploy_pkg.py && echo py313-ok
```

Expected: `py39-ok`, `py313-ok`.

- [ ] **Step 4: RST62 and RSK5 by hand: imports and the legacy golden.**

```bash
BASE=$(cat /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story/base-commit.txt)
for f in bin/ltx-movie bin/ltx-story-images bin/ltx-mlx-render bin/judge-story bin/ltx-story-manifest bin/iterate-story; do
  printf '%s: ' "$f"; git diff $BASE -- $f | grep -cE '^[-+](import |from [a-zA-Z_.]+ import )'
done
python3 -m pytest tests/test_casting_regression.py::test_b1_ltx_movie_dry_run_is_unchanged tests/test_story_engine.py::test_rst40_legacy_phase1_is_byte_identical tests/test_story_engine.py::test_rst41_legacy_dry_run_matches_the_golden -q -p no:cacheprovider 2>&1 | tail -1
```

Expected: every file prints `0` (no import line added or removed anywhere in those files, top level or inside a function); then `3 passed, ...` (the unchanged legacy dry-run golden, the legacy Phase 1 argv and prompt, and RST41).

- [ ] **Step 5: RST63 and spec 5.6, untouched files and the exact change set (run from the repo root).**

```bash
cd /Users/reubenpatterson/local_agent_harness
BASE=$(cat .superpowers/sdd/2026-10-17-story/base-commit.txt)
git diff --quiet $BASE -- qwen-agent-workspace/fleet_lib.py qwen-agent-workspace/bin/qwen-agentd qwen-agent-workspace/bin/qwen-agent qwen-agent-workspace/character_lib.py qwen-agent-workspace/ltx2_mlx_video_skill.py qwen-agent-workspace/z_image_skill.py qwen-agent-workspace/bin/character qwen-agent-workspace/docs && echo untouched-ok
git diff --name-only $BASE..HEAD
git log --format=%s $BASE..HEAD | grep -cE "\((story RS|catalog LC)"
ls qwen-agent-workspace/generated/loras 2>&1 | head -1
cd qwen-agent-workspace
test -x bin/lora-catalog && echo mode-ok
```

Expected: `untouched-ok`; the name list is exactly these 18 paths (plus this plan file, `qwen-agent-workspace/docs/superpowers/plans/2026-10-17-robust-story-lora-catalog.md`, only if it was committed after `BASE`):

```text
qwen-agent-workspace/bin/iterate-story
qwen-agent-workspace/bin/judge-story
qwen-agent-workspace/bin/lora-catalog
qwen-agent-workspace/bin/ltx-mlx-render
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/lora_catalog.py
qwen-agent-workspace/scripts/deploy/build_pkg.py
qwen-agent-workspace/story_engine.py
qwen-agent-workspace/tests/story_engine_testutil.py
qwen-agent-workspace/tests/test_casting_pipeline.py
qwen-agent-workspace/tests/test_casting_regression.py
qwen-agent-workspace/tests/test_deploy_pkg.py
qwen-agent-workspace/tests/test_lora_catalog.py
qwen-agent-workspace/tests/test_ltx_movie_offline.py
qwen-agent-workspace/tests/test_shots_mode.py
qwen-agent-workspace/tests/test_story_engine.py
```

then `16` (one commit per Task 2-17), then the real catalog directory's state as before the run (`ls: ... No such file or directory` on a host that never ran `bin/lora-catalog add`), then `mode-ok`.

- [ ] **Step 6: Design review.** Dispatch a `design-reviewer` (Opus, high effort) over `git diff $(cat /Users/reubenpatterson/local_agent_harness/.superpowers/sdd/2026-10-17-story/base-commit.txt)..HEAD` with this plan and the spec. It must check at minimum: the five Review Focus items; RS31/RSK5 (the `--story-legacy` path, its argv, prompt, messages and dry-run block are byte-identical; `_print_legacy_phase1` is the old block moved verbatim); RS34 (RST50's counts); RS37 (no stage can introduce an undeclared library character: the catalog never lists characters to the planner or critic, no patch field reaches phrases or descriptors, P13/N15 report any that slips in, declared members are excluded); RS5/RS18 (every model call is a `bin/qwen-agent --max-rounds 1` subprocess with stdin closed and no `--danger-auto-approve`; the critic falls back to the local one-shot on every fleet failure); RS20 (patches touch only named fields; at most 8; budgets honoured); RS23 (the wall clock is checked before every call); RS27 (exit codes and messages); LC13-LC17 (catalog picks reach Phase 2 flags, `catalog_loras.json`, the manifest, the render units in the order global, catalog, character, and the provenance; sha and duplicate checks run before `--dry-run`); RSK3 (no new import in `bin/ltx-mlx-render` or `bin/judge-story`; stdlib only in the three new files); and every proposed ruling in "Plan decisions". A NEEDS-FIX verdict comes with an exact patch; apply it in the owning task's files, re-run Steps 1-5, and commit with that task's message prefix.

---

## Coverage

### Requirements to tasks

| Req | Task(s) | Req | Task(s) |
|---|---|---|---|
| RS1, RS4, RS5, RS6 | 4 | RS24 | 9 |
| RS2 | 11 | RS25 | 9 (engine files), 11 (`story_prompt.txt`) |
| RS3 | 6, 11 | RS26 | 9, 10 |
| RS7, RS9, RS10, RS11 | 5 | RS27 | 9 |
| RS8 | 9 | RS28 | 10, 11 (`_phase1_robust`) |
| RS12, RS14, RS15, RS16 | 6 | RS29, RS35, RS36 | 11 |
| RS13 | 6 (cleanup), 9 (retry, budget) | RS30 | 12, 13 (catalog flags) |
| RS17, RS18, RS19 | 7 (RS19 retry in 9) | RS31 | 11 (move), 12 (dry run) |
| RS20 | 8 | RS32, RS33 | 16 |
| RS21, RS22, RS23 | 9 | RS34 | 11 (RST50), every later `bin/ltx-movie` task keeps it |
| RS37 | 5 (P13, plan prompt), 6 (N15, panel prompt), 9 (plan call 2, ranking), 10 (re-check), 12 (dry run) | | |
| LC1-LC6, LC18 | 2 (LC6's compatible set: 5) | LC14 | 13 |
| LC7-LC11 | 3 | LC15, LC16 | 14 |
| LC12 | 5 (L-checks), 8 (patches), 11 (pins) | LC17 | 15 |
| LC13 | 13 | LC19 | 4 |
| LC20 | 3 (lora-catalog), 13 (ltx-movie), 14 (manifest), 15 (render) | | |

### Tests to tasks

| Tests | Task | Tests | Task |
|---|---|---|---|
| LCT1-LCT5, LCT6a, LCT26, `test_lct3b_*` | 2 | RST10, RST11, RST17b, RST26b, RST33-RST39, RST43, RST55b, RST58, Review Focus 1-3 | 9 |
| LCT7-LCT12, LCT29 | 3 | RST44, RST45, RST56b | 10 |
| RST1, RST5-RST7, RST25, LCT27, `test_rs4_constants`, `test_parse_violation_shapes` | 4 | RST2-RST4, RST40, RST42, RST46, RST50-RST54, LCT13, Review Focus 5 | 11 |
| RST8, RST9, RST13-RST15, RST55, RST57 (plan), LCT6b | 5 | RST41, RST47, RST57c | 12 |
| RST12, RST16-RST21, RST56, RST57 (panel) | 6 | LCT14, LCT15, Review Focus 4 | 13 |
| RST22-RST24, RST26a | 7 | LCT16-LCT18 | 14 |
| RST27-RST32, LCT28 | 8 | LCT19-LCT25, LCT30 | 15 |
| RST48, RST49 | 16 | RST61-RST63 | 17 |
| RST60 | 1 (baseline), 18 | | |

### Success criteria

| KPI | Automated (task) | Live |
|---|---|---|
| RSK1 | RST60 (Task 18 Steps 1-2) | none |
| RSK2 | RST61 (Task 17, Task 18 Step 3, every task's Step 5) | none |
| RSK3 | RST1 (4), LCT1 (2), RST62 (17), Task 18 Step 4 | none |
| RSK4 | every new test via `story_env`; RST63 (17); Task 18 Step 5 | none |
| RSK5 | RST40 (11), RST41 (12), Task 18 Step 4 | none |
| RSK6 | none | RSR1-RSR4 (below) |

---

## Plan decisions (where the spec is silent, split across tasks, or needed a reading)

The spec's design is unchanged. Each item is pinned by code shown in its task; each is a **proposed ruling** for the user.

**Readings of the spec:**

1. **RS9/RS10, P2's detection point.** Normalization replaces bad values with empty ones, so the checks cannot see a missing key afterwards. `normalize_plan` returns `(plan, shape)`: `shape` holds the container problems it repaired (`the reply is missing the key 'props'`, `'cast' is not a list`, `beats item 1 is not an object`, `beat K: P2 structure: cast is not a list`), and `plan_checks(ctx, plan, shape=())` reports them first; empty strings, bad ids, duplicates and undefined references are P2 messages computed from the normalized plan (`title must be a non-empty string`, `cast entry 2 has id 'x2'; ids are c1, c2 and so on`, `beat 4: P2 structure: action is missing or empty`, `there must be at least one location`, ...). `shape` is carried unchanged into every round.
2. **P4** reports every failing condition of a setting (start, word count, one sentence) rather than the first; **P12** reports each new cast id once per beat; **L6** is reported once per id, at the first panel it occurs on; a pick of a catalog entry dropped from the compatible set (unreadable file, character-trigger clash) is reported as **L1** `'x' is not in the catalog`.
3. **RS13 cleanup** widens each pasted-sentence span over the sentence's own full stop (spec: "remove every ... occurrence of a pasted sentence"); `character_lib._passage_spans` ignores the trailing `.`, which would otherwise leave a stray `.` in the writer text. The title fallback of an empty beat action is `Panel K`.
4. **RS12** with `no_stills_rules=""` omits the Rules block; the panel fix block lists at most 40 problems with no `- ... and N more` line (the spec states the limit only).
5. **RS37's reserved line** sits on its own line between the cast-phrases line and `@@PREVIOUS@@` (template token `@@RESERVED@@`), as the amended spec states.
6. **RS15 ordering:** plan-scope N10 comes first in the hard list; within a panel the hard checks run N1-N11 then N15; advisories are ordered per panel N12, N13, N14. N13 fires when the similarity is `>= 0.6` (the rule states the passing side, `below REPEAT_JACCARD`). `panel_checks` takes a fifth argument, `story_md_path`, the round's `story.md` the caller has just written (the spec parses "a temporary copy written to `<round dir>/story.md`").
7. **RS20 signature:** `apply_patches(ctx, state, patches, regen=None, lora_allowed=None)`; the round controller passes a `regen` callback that makes the panel call (so the patch logic stays testable without agents); `regen=None` skips regeneration silently. A regeneration skipped for budget is recorded as the spec says; one skipped because the wall clock ran out is recorded as `panel K regeneration skipped: wall-clock cap reached`. A `beat.action` regeneration's fix lines are the panel's current violations (scope `panel K` or `beat K`), or, when there are none, `this panel's beat was revised; rewrite the panel for the new beat`.
8. **RS21 files:** a critic round that stops (`passed`, `plateau`) keeps its prompt, reply and `critic.json` in `round_k/` with no state files; a round directory is created only when a critic call is made.
9. **RS24:** the judge is skipped with `detail: "wall-clock cap reached"` when the cap is exhausted before it; its follow-up critic round applies the `passed` stop only (a plateau test there would compare the judge's state with an unrelated earlier round); `judge.detail` is `min score N`; `run_judge` also rejects a `judgment.patches.json` whose shape is wrong.
10. **RS28:** a re-check without `plan.json` writes no `story_checks.json` (that path is "exactly today's validators"). `plan_free_report` gains a keyword `ws` (default: `story_engine.py`'s directory) to find the character library for N15.
11. **RS2's invalid-catalog message** prints the reason without repeating the path that `CatalogError` already prefixes.
12. **RS32 / RSK3:** `bin/judge-story` "adds no import" (RSK3 says so for it and `bin/ltx-mlx-render`, and "no top-level import" for the others), so `story_engine.py` is executed into a fresh namespace dict (`_story_engine()`), not imported. RST62 checks every import statement in both files, not only top-level ones.
13. **LC17:** a manifest with `catalog_loras` forces the render's merged `--lora` route, because `build_command` forbids `lora_path` together with `loras`; without catalog entries nothing changes.
14. **LC14's precondition** is read as the engine/auto-LoRA/valid-plan part of LC13 (a plan whose only pick is a stills LoRA still gets its stills flag). `_catalog_panel_loras` and `_catalog_stills_flags` return `(error line or None, value)`; the dry run prints a catalog error and exits 2, like the real phase.
15. **LC16:** `images.json` entries of generated panels gain `lora_triggers` when `--lora-trigger` is given; such panels also carry `"loras": []`, because the trigger plan adds them to `plans`.
16. **LC7/LC10 texts** the spec leaves open: `catalog entry X already exists`, `PATH is already cataloged as X`, `PATH is character NAME's video LoRA; cast it with bin/ltx-movie --character`, `trigger T is already catalog entry X's trigger`, `trigger T is character NAME's trigger`, `--strength-range must be LO,HI, got '...'`; `verify` problems as in `verify_entry`. `list` with only characters prints the header after the `no LoRAs in ...` line.
17. **RS5:** `run_agent` never returns `rc=N` (a missing envelope is `no_envelope`, as RS5 states); RS18's warning and LC6's skip warnings go to stdout, like the other `Warning:` lines of `bin/ltx-movie`. RS30's catalog warnings are printed just before the `Catalog LoRAs:` line.
18. **Section 5.5 is incomplete; three more existing-test edits are forced** and kept minimal: `tests/test_shots_mode.py`'s `movie_ws` fixture links `story_engine.py` and `lora_catalog.py` (its `main()` calls in s34, s46, s51 and s52 now resolve the engine and load the catalog module from the temp `WS`); `tests/test_ltx_movie_offline.py` L11 (`test_length_100_panels_and_tokens`) gets `--story-legacy` (it asserts the legacy 9350-token Phase 1 budget); and `tests/test_deploy_pkg.py` updates four counts that follow from LC19's two extra files (A1 `19` -> `21` twice, resume prefix `27 of` -> `29 of` twice).
19. **RSK4 and unchanged old tests:** tests the spec keeps unchanged (L1z, L2, L24, L27 ...) run the default dry run, which now stats the real `generated/loras/catalog.json` path (absent on this host) without reading or writing it; every new test points `LORA_CATALOG_DIR` at a temp directory, and RST63 asserts the real file's state is unchanged.
20. **Test splits and extras:** LCT6 is split (6a in Task 2, 6b in Task 5), RST17/RST26/RST44/RST55/RST56/RST57 are split by owning code (suffixes `b`, `a`/`b`, `c`), LCT13 lives in Task 11 with the pins; extra tests: `test_rs4_constants`, `test_parse_violation_shapes`, `test_lct3b_save_sorts_and_is_atomic`, and the five `test_story_focus_<n>_*`. Test-only helpers: `panel_json` builds whole sentences (cutting mid-sentence can split a referring phrase), the fake agent prints one log line before its envelope (as the real one-shot does), and `make_untrained` writes a valid untrained character.
21. **Task size:** 18 tasks (above the suggested 12-16): the critic (Task 7) and the patches (Task 8) are separate reviewer gates, and so are the robust dry run (Task 12) and the catalog flags (Task 13), because each can be rejected while its neighbour is approved.

**Known residual risks (no automated test):** model behaviour (plan and panel quality, critic usefulness, JSON reliability of the 27B model and of `--skill=analyst`), Claude's patch quality, real LoRA headers and their visual effect, and real peer delegation of the critic -- all covered only by the live protocol below; RSX1-RSX7 of spec Section 10, accepted by the user.

---

## Live quality protocol and LoRA A/B (human-run, after Task 18; not an executor task)

Spec Section 7, run on the Mac by the user or the main thread with the story server up and no concurrent GPU work; it calls the real story model, the Anthropic API (`bin/judge-story`) and, for 7.4, renders video, so no executor runs it.

1. **Premises (7.1).** Eight premises, each run twice: `drift_red_test` (`--seed-image ~/Downloads/red.jpg --panels 6`), `sisters_sorrow` (`--panels 30`, the 7.1 premise "Two estranged sisters meet at their mother's empty seaside house ..."; no original narrative exists, A1), `ronin-rescue` (`--shots --panels 14 --character kyra --character ronin --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8`), `lighthouse` (`--no-stills --panels 8`), `subway-dancer` (`--panels 10`), `night-market` (`--shots --panels 12`), `lantern-market` (`--panels 8 --character kyra`), `courier` (`--shots --panels 16`), with the narratives of the 7.1 table verbatim.
2. **Procedure (7.2).** Per premise: `python3 bin/ltx-movie "<narrative>" --story-id <id>-L <flags> --story-legacy --story-only --no-review --force-story`, then the same with `--story-id <id>-R` and without `--story-legacy`, same `--story-model`. Record exit code, wall time, `grep -c '^## Panel' story.md`, the hard-violation count from `story_engine.plan_free_report(story_md, mode, panels, members, ltx_movie._validate_story_md)` for both engines (a `-R` run that exited 2 is measured as saved), and `bin/judge-story --story-id <id>` scores (default mode). The user reads both story.md files and records L / R / same. Optional step 4: premise 5 again with a peer serving `analyst` and this host's daemon not serving it (exercises RS18's fleet route).
3. **Pass bar (7.3).** RSR1: the new engine has 0 hard violations on at least 7 of 8 premises. RSR2: every new story.md has exactly the requested panel count (8 of 8), and judge-story's minimum score for the new story is >= the legacy minimum on at least 6 of 8. RSR4: user preference favours the new engine on at least 5 of 8 premises (a "same" does not count toward the 5).
4. **LoRA A/B (7.4, RSR3).** `bin/lora-catalog add` one real motion or physics LoRA (rank == alpha) and optionally one style LoRA for the LTX pack in use, with honest `--use-when` text; `bin/lora-catalog verify` exits 0. Premise 5 at `--panels 4`: run A with `--no-auto-lora`, run B default, same `--image-seed`/render seed, rendered for real. Pass: B's `plan.json` picks at least one catalog LoRA; B's `manifest.json` has non-empty `catalog_loras` on those panels; every B clip's `.provenance.json` lists `{"kind": "catalog", "catalog_id": ..., "sha256": ...}` matching the catalog; B renders without failure; rerunning B with the same command reuses every clip (`--resume`); the user rates B's style/motion fit against A per panel.
5. **Rollout (spec 8).** If RSR1/RSR2 fail, keep `--story-legacy` in commands while the prompts are tuned; no code switch is added. The catalog starts empty until the first `bin/lora-catalog add`.
