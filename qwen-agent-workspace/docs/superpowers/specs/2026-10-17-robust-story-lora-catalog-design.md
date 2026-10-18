# ltx-movie -- Design Spec (robust story generation and the LoRA catalog, piece E)

Date: 2026-10-17
Status: The user approved every design decision of piece E on 2026-10-17: Section 1 (the principle "the model writes small scoped pieces, code does structure"; the six stages PLAN, PANELS, CHECKS, CRITIC, GATE, REVIEW; `--story-legacy`), Section 2 (the check table, the critic JSON, the patch rules, the round controller and its budgets, and the hard-fail answer: stop for hand-editing, exit 2), Section 3 (the versioned LoRA catalog, `bin/lora-catalog`, per-panel selection), Section 4 (the test plan, the live protocol, the rollout), and the scheduling (piece D first, then E). This document writes those decisions down precisely enough to implement without reopening any. Every value they left open is marked **[spec choice]** with a one-line reason; Section 9 collects them. The user answered the three open questions of the first draft on 2026-10-17 (fallback sisters_sorrow premise, preference bar of at least 5 of 8, declared-only casting); Section 11 records the answers.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`; every relative path is relative to `WS`. Line numbers cite the tree at commit `1b651da`. `bin/qwen-agent` is being edited by piece D while this spec is written, so its citations name functions and give approximate lines (`~`).

Specs this one builds on (cited by tag):

- **[CHAIN]** `docs/superpowers/specs/2026-09-24-ltx-movie-narrative-chain-redesign-design.md` -- the chained flow.
- **[JUDGE]** `docs/superpowers/specs/2026-10-02-judge-story-design.md`.
- **[ITER]** `docs/superpowers/specs/2026-10-03-iterate-story-design.md`.
- **[CAST]** `docs/superpowers/specs/2026-10-05-character-library-design.md`.
- **[ANCHOR]** `docs/superpowers/specs/2026-10-05-prompt-anchoring-fixes.md`.
- **[SHOTS]** `docs/superpowers/specs/2026-10-06-shots-mode-design.md`.
- **[RULES2]** `docs/superpowers/specs/2026-10-09-shots-rules-v2-design.md` (S1-S12 as shipped).
- **[FLEET]** `docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md` (F59 `route_candidates`, F63 `daemon_url_from_env`, F64 `fetch_view`, F68 `delegate_once`).
- **[TRACE]** `docs/superpowers/specs/2026-10-17-fleet-tracing-design.md` (piece D; treated as implemented when E is implemented).

---

## 0. Purpose and scope

### 0.1 Purpose

Phase 1 of `bin/ltx-movie` today sends one large prompt per mode and asks a 27B model to write the whole `story.md` in one `write_file` call. Three failure classes survive every prompt-rule revision: continuity errors (a character re-described differently, a location that drifts), weak or off-goal stories, and unrenderable panels (sequences, dialogue, off-screen references). The shots-rules work established that the model copies sentences when told to but does not restructure a story on request, that examples in a prompt get copied, and that self-verification hangs ([RULES2] 0.2; `bin/ltx-movie:994-995`). This feature replaces the single prompt with a pipeline in which the model writes small, scoped pieces (a JSON story bible, then one panel at a time), code assembles `story.md` and pastes every fixed sentence verbatim, deterministic checks run on every round, and a local critic (the fleet `analyst` skill, no API cost) proposes per-panel patches that code applies to named fields only. A Claude gate (`bin/judge-story`) is optional. Second, a versioned LoRA catalog lets the planner pick style, motion and physics LoRAs per panel, which the manifest and renderer apply alongside the existing global and character LoRAs.

### 0.2 Grounding (shipped code)

**`bin/ltx-movie` (1913 lines).** Templates: `STORY_PROMPT_TEMPLATE` (chained, `:119-143`), `STORY_PROMPT_TEMPLATE_NO_STILLS` (`:145-166`; its `Rules:` block is `:147-151`), `STORY_PROMPT_TEMPLATE_SHOTS` (`:168-203`); `SEED_IMAGE_PREFACE`/`POSTFACE` (`:205-213`); `build_story_prompt` (`:216-234`). Parser `build_parser` (`:250-413`): `--lora` repeatable (`:294-299`, `_RepeatableLoraAction` `:237-247`), `--stills-lora` (`:300-307`), `--character` (`:308-315`), `--cast` (`:316-319`), `--shots` (`:330-337`), `--story-model` (`:343-351`), `--story-context-window` (`:352-364`), `--no-stills` (`:377-382`), `--no-review` (`:383`), `--force-story` (`:384`), `--story-prompt-override` (`:385-390`), `--story-only` (`:405-411`), `--dry-run` (`:412`). There is **no `--goal` flag** in `bin/ltx-movie` (only `bin/judge-story:429`, `bin/iterate-story:132`, `bin/judge-clips:429`). `_render_flags` (`:466-492`), `_phase1_max_tokens` (`:512-514`), `_phase1_timeout` (`:517-518`), `_story_paths` (`:525-536`), `_validate_story_md` (`:569-623`, structural only), `_load_story_panels` (`:626-643`), `_character_lib` (`:712-716`, loaded only when casting or `--shots`), `_resolve_casting` (`:719-775`), `_resolve_global_loras` (`:783-823`), `_cast_flags` (`:886-894`), `_run_story_agent` (`:977-1025`), `phase1_story` (`:1028-1111`; review `:1084-1109`), `_unused_path` (`:1114-1123`), `_phase1_shots_finish` (`:1174-1272`, up to `SHOTS_MAX_REWRITES` = 2 rewrites), `phase2_stills` (`:1288-1318`), `_phase2_shots` (`:1357-1392`), `phase3_manifest` (`:1471-1508`), `_print_dry_run_plan` (`:1648-1783`), `_phase_sequence` (`:1790-1808`), `main` (`:1811-1904`). Phase 1 runs `bin/qwen-agent` with `--max-rounds 4` and adds `--danger-auto-approve` only under `--force-story --no-review` (`:1052-1064`).

**`character_lib.py` (1140 lines, stdlib, import set pinned by `tests/test_shots_mode.py::test_s20`).** Constants `:43-49` (`SHOTS_MOTION_MIN_WORDS` 10, `SHOTS_MOTION_MAX_WORDS` 25, `SHOTS_MAX_CAST_PER_PANEL` 2, `SHOTS_MAX_REWRITES` 2, `SHOTS_SETTING_MIN_WORDS` 12); `SHOTS_RULE_GUIDANCE` S1-S12 (`:88-121`); `_SENTENCE_SPLIT_RE`, `_CHAIN_WORD_RE`, `_COMMA_AND_RE`, `_SHOT_TYPE_RE`, `_OFFSCREEN_RE`, `_SETTING_SENTENCE_RE`, `_WORD_RE` (`:123-167`); `TRIGGER_REGISTRY` (`:169`); `_TOP_LEVEL_KEYS`/`_LORA_KEYS` (`:219-226`; a character LoRA records `rank` and `alpha`, and `alpha == rank` is enforced at `:337-339`); `library_dir` (`:249`, `$CHARACTER_LIBRARY_DIR` override); `normalize_phrase` (`:292`); `validate_descriptor` (`:308`); `load_character` (`:449`); `list_names` (`:479`); `registered_triggers` (`:487`); `resolve_cast` (`:549`); `_phrase_regex`/`phrase_occurs`/`cast_text` (`:591-632`); `identity_sentence` (`:645`); `find_phrases` (`:676`); `is_animal_phrase` (`:729`); `_is_camera_sentence` (`:736`); `_passage_spans` (`:753`); `_person_refs` (`:765`); `motion_problems` (`:855`); `shots_violations` (`:879`); `shots_advisories` (`:978`); `shots_rewrite_block` (`:998`). E does not change this file.

**`bin/ltx-story-manifest` (686 lines; stdlib + Pillow).** `_parse_prompts_md` (`:219-290`) is the single story.md parser (`## Panel N — title`, labels `Image|Motion|Narration|Prompt|Style`). Per-panel `characters` from `--cast` (`:628-645`), trigger insertion into `motion_prompt` via `cast_text`.

**`bin/ltx-mlx-render` (1300 lines).** `_RepeatableLoraAction` (`:85-95`), `--lora` (`:118-121`), `load_manifest` (`:175-263`), `build_units` (`:271-313`; per-unit `loras`: global then character, `:306-311`), `lora_sha256` (`:406-413`), `build_clip_provenance` (`:416-444`; `loras` entries `{kind, path, sha256, strength}` at `:440-443`), `print_dry_run` (`:737-814`; command build `:789-797`), `render_panel` (`:850-920`; command build `:873-882`), `main` (`:1047-`; global/character duplicate checks `:1073-1102`). **Every panel is its own `ltx-2-mlx` process** (`render_panel` calls `SKILL.generate_video` once per unit), and each unit carries its own `loras` list.

**`ltx2_mlx_video_skill.py`.** `build_command(..., loras=None)` (`:142-189`) emits one `--lora PATH STRENGTH` per pair. `parse_lora_spec` (`:111`) caps strength at 2.

**`~/ltx-2-mlx/.../loader/fuse_loras.py:87-110`.** `_prepare_deltas`: `delta = sum(B_i @ A_i * strength_i)` over `*.lora_A.weight`/`*.lora_B.weight` pairs; no `alpha/rank` scaling, keys in any other format are ignored.

**`z_image_skill.py`.** `BASE_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"` (`:52`); one LoRA set per process (`_get_pipeline`, `:182-196`), so `bin/ltx-movie` runs one `bin/ltx-story-images` process per stills-LoRA group (`_phase2_shots`).

**`bin/ltx-story-images` (476 lines).** `plans` (`:253`), the per-panel prompt and LoRA plan (`:291-341`); source-count guards in `tests/test_ltx_story_images.py` (I13, `:585`, `:591`: `_compose_prompt(` appears exactly 3 times).

**`bin/judge-story` (368 lines; `anthropic`, `jsonschema`).** Scores four dimensions and writes `judgment.json` + `story_prompt.revised.txt`; report only.

**`bin/iterate-story` (354 lines).** Whole-prompt regeneration loop via `bin/ltx-movie --story-only --story-prompt-override` (`build_ltx_movie_cmd`, `:157-172`); measured stalls (5,5,5,4), panel drift, mode flags dropped.

**`bin/qwen-agent`.** One-shot mode (`oneshot`, ~`:4103`) prints one `qwen-agent.oneshot.v1` JSON envelope (`schema, status, answer, error, rounds, tool_calls`) as the last stdout line and exits 0 (`status == "ok"`) or 3. `--skill analyst` uses think off, temperature 0.2 (`SKILL_THINK_TEMP_DEFAULTS`). `QWEN_AGENT_PREFLIGHT_DONE=1` skips the tool-calling preflight probe (`setup`, ~`:3647`). `exec_delegate_to_skill` (~`:1372`) routes a skill through `FLEET.route_candidates`: `[LOCAL]` runs a local `--skill` subprocess; peers go through `_delegate_remote` -> `FLEET.delegate_once`.

**`fleet_lib.py` / `bin/qwen-agentd`.** `LOCAL = "@local"` (`fleet_lib.py:67`), `DEFAULT_DAEMON_URL = "http://127.0.0.1:8190"` (`:70`), `route_candidates` (`:865`), `daemon_url_from_env` (`:918`), `fetch_view` (`:934`), `delegate_once(daemon_url, skill, task, host_id, images=None, trace=None)` (`:982`). The daemon's loopback `POST /delegate` answers `not_live` when `host_id` is its own host (`bin/qwen-agentd` `handle_delegate`, `:1105-1111`): the local daemon cannot run a skill on its own host, so a "mac-local" analyst is always a local one-shot.

**Deploy package.** `scripts/deploy/build_pkg.py:383-385` `PIPELINE_FILES` lists the files shipped with `bin/ltx-movie`; gate X2 runs the default `bin/ltx-movie ... --dry-run` and fails when any output line contains `{` or `}` (`build_pkg.py:1117`, `install_pkg.py:854`).

**Tests that pin `bin/ltx-movie` source text** (Section 3.17 lists the literals): `tests/test_ltx_movie_offline.py` L1z9, L1z14, L12, L17b, L17d, L17f, L19a-c, L29c-g.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` (new) | the robust Phase 1 engine: prompts, agent calls, plan validation, assembly, checks, critic routing, patches, round controller, judge gate, re-check, outputs (Section 3) |
| G2 | `lora_catalog.py` (new) | catalog schema, load/save, safetensors header, verify, character folding, compatibility, `prefix_triggers` (Section 4) |
| G3 | `bin/lora-catalog` (new, executable) | `add`, `list`, `remove`, `verify` (Section 4.2) |
| G4 | `bin/ltx-movie` | flags `--story-legacy`, `--no-auto-lora`, `--judge`, `--goal`; `_resolve_story_engine`; `phase1_story` dispatch; `_phase1_robust`; robust dry-run block; catalog flags for Phases 2 and 3; docstring |
| G5 | `bin/ltx-story-manifest` | `--catalog-loras PATH`; per-panel `catalog_loras`; trigger prefix |
| G6 | `bin/ltx-story-images` | `--lora-trigger WORD` (repeatable) |
| G7 | `bin/ltx-mlx-render` | `catalog_loras` validation, kind `catalog` units, provenance, sha check, duplicate checks |
| G8 | `bin/judge-story` | `--patches` mode (per-panel patch output) |
| G9 | `bin/iterate-story` | deprecated wrapper |
| G10 | `scripts/deploy/build_pkg.py` | `PIPELINE_FILES` gains `story_engine.py`, `lora_catalog.py` |
| G11 | `tests/story_engine_testutil.py` (new) | fake agent / fake judge executables, temp workspace builder, fake fleet |
| G12 | `tests/test_story_engine.py` (new) | RST1-RST58, RST60-RST63 |
| G13 | `tests/test_lora_catalog.py` (new) | LCT1-LCT30 |
| G14 | existing tests | the edits of Section 5.5 only |

**Not changed:** `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agent`, every fleet test (piece D owns them), `character_lib.py`, `ltx2_mlx_video_skill.py`, `z_image_skill.py`, `bin/character`, every other file. E calls `bin/qwen-agent` only as a subprocess and loads `fleet_lib.py` read-only by path.

### 0.4 Out of scope

- Changing S1-S12, `character_lib.py`, the legacy templates, or the legacy Phase 1 code path (it stays byte-identical under `--story-legacy`).
- Calling a model server directly (every model call is a `bin/qwen-agent` subprocess).
- Auto-casting library characters: forbidden, not merely out of scope (RS37).
- Per-panel style LoRAs, per-panel stills LoRAs, more than one catalog stills LoRA.
- Training LoRAs; downloading LoRAs; editing the character `.triggers` registry from `bin/lora-catalog`.
- Images for the critic; tracing propagation from `bin/ltx-movie`.
- Any change to the render math, clip reuse rules for non-catalog clips, or Phase 4 policy.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| RSK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the baseline recorded immediately before implementation (after piece D is in) plus every RST/LCT test passing and the Section 5.5 edited tests passing, with **no lost pass**. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the same `n` as the baseline. | RST60 |
| RSK2 | `/usr/bin/python3 -m py_compile` (3.9.6) and `python3 -m py_compile` (3.13) succeed on every new or changed file (no `match`, no `X | Y` annotations, no parenthesised context managers, no `zip(strict=)`). | RST61 |
| RSK3 | Standard library only in `story_engine.py`, `lora_catalog.py`, `bin/lora-catalog`. Every touched file keeps its existing import constraints: `bin/ltx-movie` adds no top-level import; `bin/ltx-story-manifest` keeps stdlib + Pillow; `bin/ltx-mlx-render` adds no import; `bin/judge-story` adds no import; `bin/ltx-story-images` adds no top-level import. | RST62 |
| RSK4 | Tests never use the real `HOME`, never read or write the real `generated/loras/catalog.json` or `generated/characters/`, never render video, never contact a real model server, daemon or the Anthropic API. | review of RST/LCT; RST63 |
| RSK5 | `--story-legacy` reproduces today's Phase 1 prompt and `bin/qwen-agent` argv byte for byte, and today's default dry-run output byte for byte (the existing golden `tests/fixtures/casting_baseline/ltx_movie_dry_run.txt`). | RST40, RST41 |
| RSK6 | Live: the Section 7.3 pass bar on the eight premises (RSR1, RSR2, RSR4), and the Section 7.4 LoRA A/B (RSR3). | RSR1-RSR4 |

### 0.6 Must-have vs nice-to-have

Every requirement RS1-RS37 and LC1-LC20 is a must-have. Nothing else is built.

---

## 1. Architecture

### 1.1 Flow (robust engine, every mode)

```
bin/ltx-movie main -> _resolve_story_engine -> phase1_story -> _phase1_robust
  story.md exists and no --force-story?  -> story_engine.recheck  (RS28) -> review
  else story_engine.run:
    round 0:  PLAN    1-2 agent calls -> validate/normalize -> plan.json (P/L checks)
              PANELS  1 agent call per panel (+1 retry) -> code assembles story.md
              CHECKS  P*, L*, N*, (shots) S1-S12
    rounds 1..3: CRITIC judges state k-1 (fleet analyst or local one-shot --skill=analyst)
              -> stop? (passed / plateau) -> apply <= 8 patches to named fields -> CHECKS
    best round -> [GATE --judge: judge-story --patches; below 7 -> judge patches + 1 critic round]
    best has hard violations -> save, exit 2;  else write story.md, plan.json, story_checks.json
  -> REVIEW (human; skipped by --no-review)
Phase 2/3 add catalog LoRA flags from plan.json; the renderer applies them per panel.
```

### 1.2 Module boundaries [spec choice: the engine lives outside `bin/ltx-movie` so the existing source-count guards on that file (Section 3.17) keep passing unchanged, and so `bin/judge-story` can share its prompt builder]

- `story_engine.py` owns everything model-facing and every check. It is loaded by `bin/ltx-movie` by path (`importlib.machinery.SourceFileLoader("story_engine", os.path.join(WS, "story_engine.py")).load_module()`), only inside function bodies, through a new helper `_story_engine()` placed after `_character_lib()`.
- `story_engine.py` loads `character_lib.py`, `lora_catalog.py` and `fleet_lib.py` by path from `ctx.ws`, only inside function bodies (never at import). Dry runs load `story_engine.py` and `lora_catalog.py` only (no `character_lib.py` unless `_resolve_casting` already loaded it, no `fleet_lib.py`).
- `lora_catalog.py` owns the catalog file and the trigger prefix rule; it loads `character_lib.py` by path only inside `fold_characters` and `character_triggers`.
- `bin/ltx-story-manifest` and `bin/ltx-story-images` load `lora_catalog.py` by path only when `--catalog-loras` / `--lora-trigger` is given.

### 1.3 Engine selection

`args.story_engine` is set **only** by `_resolve_story_engine(args)` in `main()`; `phase1_story` and `_print_dry_run_plan` read `getattr(args, "story_engine", "legacy")`. **[spec choice: a namespace that did not pass through `main()` keeps today's behaviour, so the ~35 existing tests that call `phase1_story(args)` directly (`test_shots_mode.py`, `test_ltx_movie_iterate_flags.py`, `test_casting_pipeline.py::test_p47`) need no edit; `main()` is the only production entry.]**

### 1.4 Chained mode can switch LoRAs per panel (determination)

Pinned from the code: `bin/ltx-mlx-render` renders every panel, chained or not, as a separate `ltx-2-mlx` process with that unit's own `loras` list (`build_units:306-311`, `render_panel:873-882`); chained mode already switches character LoRAs per panel today (`bin/ltx-story-manifest:628-645` writes per-panel `characters` under `--chain`). A chain unit is conditioned only on the previous clip's last frame (`build_units:297-304`), which no LoRA affects. Therefore **chained mode gets per-panel motion/physics picks exactly like the other modes**. Style LoRAs are global-only in every mode (L2), which removes the main continuity risk of switching weights mid-take. Stills: z-image holds one LoRA set per process, so the catalog contributes at most one global stills LoRA (L7).

### 1.5 How the critic is reached

`story_engine.run_critic` (RS18) mirrors `exec_delegate_to_skill`: load `<ws>/fleet_lib.py` read-only; `daemon_url_from_env(os.environ)`; `fetch_view(url)`; `route_candidates("analyst", view)`. Peers (a non-empty list that is not `[LOCAL]`) are tried in order with `delegate_once(url, "analyst", task, host_id)` (four positional arguments; the `images`/`trace` defaults are never passed). `[LOCAL]`, no daemon, no view, no candidate, a load failure, or every peer failing all fall back to a local one-shot `bin/qwen-agent --skill=analyst`. On the Mac (which serves `analyst` verified) the route is therefore always the local one-shot.

---

## 2. Data shapes (normative)

All JSON files are written with `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing newline, to `<path>.<uuid4 hex>.tmp` then `os.replace` (the `character_lib.write_character` pattern).

### 2.1 `StoryContext`

`story_engine.StoryContext = collections.namedtuple("StoryContext", [...])` with exactly these fields, built by `bin/ltx-movie` (`_story_context(args)`):

| Field | Value |
|---|---|
| `ws` | `bin/ltx-movie` module `WS` |
| `story_id`, `story_dir` | `args.story_id`, `_story_dir(args.story_id)` |
| `mode` | `"no_stills"` if `args.no_stills`, `"shots"` if `args.shots`, else `"chained"` |
| `panels` | `args.panels` |
| `seconds` | `_clip_seconds(args)` (a string, `"6"` at the defaults) |
| `narrative` | `args.narrative` |
| `goal` | `args.goal` (None or the validated text) |
| `members` | `args.cast_members` (list of `character_lib.CastMember`, possibly empty) |
| `seed_image` | `os.path.abspath(args.seed_image)` or None |
| `seed_agent_image` | `args.seed_downscaled_path` (real run) / `_story_paths(...)["seed_downscaled"]` (dry run) when seeded, else None |
| `story_model`, `context_window` | `args.story_model`, `args.story_context_window` |
| `video_model` | `args.model` |
| `auto_lora` | `not args.no_auto_lora` |
| `catalog` | `args.story_catalog` (RS2 step 4): the loaded catalog dict (Section 2.7), or `{"schema_version": 1, "entries": []}` when the file is absent or `--no-auto-lora` |
| `pinned` | list of pin dicts (LC12) |
| `stills_pinned` | list of `os.path.realpath` of every resolved `--stills-lora` path |
| `judge` | `args.judge` |

### 2.2 Plan writer output and `plan.json`

The plan writer returns one JSON object with keys `title`, `logline`, `cast`, `locations`, `props`, `beats`, `loras` (RS7). Code validates and normalizes it (RS9) and writes `plan.json`:

```json
{
  "schema": "ltx-movie.plan.v1",
  "story_id": "ronin-rescue", "mode": "shots", "panels": 14, "seconds": "6",
  "narrative": "...", "goal": null, "seed_image": null,
  "video_model": "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "auto_lora": true,
  "title": "...", "logline": "...",
  "cast": [{"id": "c1", "phrase": "the woman in grey", "descriptor": "a young woman ...", "cast_name": "kyra"}],
  "locations": [{"id": "l1", "setting": "The setting is ... light."}],
  "props": [{"id": "p1", "name": "the branch"}],
  "beats": [{"index": 1, "arc": "introduction", "action": "...", "shot": "wide shot",
             "camera": "static", "location": "l1", "cast": ["c1"]}],
  "loras": {"global": [{"id": "film-grain", "strength": 0.8}],
            "per_beat": {"5": [{"id": "fast-motion", "strength": 0.7}]},
            "stills": [],
            "pinned": [{"path": "/abs/x.safetensors", "strength": 1.0, "catalog_id": null, "kind": null}]}
}
```

`cast_name` is the library character name for a `--character` member, else null. `pinned` is written by code (LC12), never by the model.

### 2.3 Panel writer I/O

Input: the panel prompt (RS12). Output: one JSON object whose keys depend on mode and panel:

| Mode | Panel | Keys |
|---|---|---|
| chained | 1 | `title`, `image`, `motion`, `narration` |
| chained | 2..N | `title`, `motion`, `narration` |
| no_stills | all | `title`, `prompt`, `narration` |
| shots | all | `title`, `image`, `motion`, `narration` |

These are the **writer parts** of a panel. `parts.json` in each round directory records them: `{"panels": [{"index": k, "title": ..., <mode keys>: ...}]}`.

### 2.4 Critic I/O

Input: the critic prompt (RS17). Output:

```json
{"scores": {"continuity": 7, "story": 6, "renderability": 8},
 "verdict": "revise",
 "patches": [{"target": "panel", "index": 3, "field": "motion",
              "reason": "one sentence", "replacement": "..."}]}
```

`scores` values are integers 1-10 (`bool` rejected); `verdict` is `"ok"` or `"revise"`; `patches` is a list (possibly empty). `field` is one of `beat.action`, `beat.camera`, `beat.shot`, `location.setting`, `lora`, `motion`, `image`, `prompt`, `narration`. `replacement` is a string for every field except `lora`, where it is a list of `{"id", "strength"}` objects. The judge's `submit_review` input (RS32) has the same shape.

`critic.json` (per critic round): `{"route": "local" | "fleet:<host_id>" | null, "calls": n, "reply": <parsed object or null>, "applied": [<patch> ...], "rejected": [{"patch": <patch>, "reason": "<text>"}]}`.

### 2.5 `story_checks.json`

```json
{
  "schema": "ltx-movie.story-checks.v1",
  "story_id": "...", "mode": "chained", "panels": 6,
  "checked_at": "2026-10-17T12:00:00Z",
  "source": "robust",
  "round": 2,
  "hard": [{"id": "N1", "name": "word count", "scope": "panel", "index": 3,
            "message": "panel 3: N1 word count: Motion: is 41 words; it must be 15-35"}],
  "advisory": [],
  "scores": {"continuity": 8, "story": 7, "renderability": 8},
  "verdict": "ok",
  "stop_reason": "passed",
  "rounds": [{"round": 0, "hard": 4, "advisory": 1, "scores": null, "verdict": null}],
  "best_round": 2,
  "judge": null
}
```

- `source`: `"robust"` (written by `run`) or `"recheck"` (written by `recheck`; then `round`, `scores`, `verdict`, `stop_reason`, `best_round`, `judge` are null and `rounds` is `[]`).
- Every violation is a string of the form `<scope>: <ID> <name>: <detail>` where `<scope>` is `story`, `plan`, `beat K` or `panel K`. `story_engine.parse_violation(text)` splits it with `^(?:(story|plan)|(beat|panel) (\d+)): ([A-Z]+\d+) ([^:]+): (.*)$` (DOTALL) into `id`, `name`, `scope` (`story|plan|beat|panel`), `index` (int or null), `message` (the whole string). A string that does not match (only `_validate_story_md` output during a re-check, RS28) is stored with `id` `"V0"`, `name` `"structure"`, `scope` `"story"`, `index` null.
- `judge`: null, or `{"status": "ok" | "error" | "skipped", "detail": "<text>", "scores": {...} | null, "min_score": n | null, "applied": true | false}`.

### 2.6 `story_rounds/` layout and `run.json`

```
<story_dir>/story_rounds/
  run.json
  round_0/  plan_prompt.txt  plan_reply_1.txt  [plan_reply_2.txt]
            panel_01_prompt_1.txt  panel_01_reply_1.txt  [..._2.txt] ...
            plan.json  parts.json  story.md  story_checks.json
  round_1/  critic_prompt_1.txt  critic_reply_1.txt  [critic_prompt_2.txt critic_reply_2.txt]
            critic.json  [panel_NN_prompt_2.txt panel_NN_reply_2.txt ...]
            plan.json  parts.json  story.md  story_checks.json
  ...
  round_<j>/ (judge round, when RS24 applies) judgment.patches.json critic.json plan.json parts.json story.md story_checks.json
```

- A reply file holds the envelope's `answer` text exactly, or `<no answer: STATUS>` when there is none (STATUS is `timeout`, `no_envelope`, `rc=N`, or the envelope `status`).
- The critic files of round k sit in `round_k/` (the round its patches produce); the critic judged round k-1.
- When `story_rounds/` already exists at the start of `run`, it is renamed to `_unused_path(<story_dir>/story_rounds-<UTC %Y%m%dT%H%M%SZ>-<pid>)` (directory variant of `_unused_path`: same rule on a directory path with no extension). Nothing is deleted.
- `run.json`: `{"schema": "ltx-movie.story-run.v1", "story_id", "mode", "panels", "started_at", "finished_at", "budgets": {"plan_calls": 2, "panel_calls": 2, "critic_rounds": 3, "critic_calls_per_round": 2, "max_patches": 8, "wall_clock_s": W}, "calls": [{"stage": "plan"|"panel"|"critic"|"judge", "panel": k|null, "round": r, "attempt": a, "route": "local"|"fleet:<id>"|null, "status": "<status>", "seconds": s}], "stop_reason": "...", "best_round": k, "exit": 0|1|2}`. Rewritten (atomically) after every call.

### 2.7 `catalog.json`

Path: `$LORA_CATALOG_DIR/catalog.json` when `LORA_CATALOG_DIR` is set (test infrastructure only, like `CHARACTER_LIBRARY_DIR`), else `<WS>/generated/loras/catalog.json` (gitignored: `qwen-agent-workspace/.gitignore` ignores `generated/`).

```json
{
  "schema_version": 1,
  "entries": [
    {"id": "film-grain", "kind": "style", "path": "/abs/film_grain.safetensors",
     "sha256": "<64 lowercase hex>", "bytes": 335544320,
     "base_models": ["MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8"], "target": "video",
     "triggers": ["grainfilm"], "rank": 32, "alpha": 32,
     "default_strength": 0.8, "strength_range": [0.5, 1.0],
     "description": "...", "use_when": "...", "avoid_when": "",
     "added_at": "2026-10-17T12:00:00Z"}
  ]
}
```

Validation rules: LC3. Entries are kept sorted by `id`.

### 2.8 `catalog_loras.json` and the manifest's `catalog_loras`

Written by `bin/ltx-movie` Phase 3 (LC13) to `<story_dir>/catalog_loras.json`:

```json
{"schema": "ltx-movie.catalog-loras.v1", "story_id": "...",
 "panels": [[{"id": "fast-motion", "kind": "motion", "path": "/abs/m.safetensors",
              "sha256": "...", "strength": 0.7, "triggers": ["fastmo"]},
             {"id": "film-grain", "kind": "style", "path": "/abs/s.safetensors",
              "sha256": "...", "strength": 0.8, "triggers": ["grainfilm"]}],
            []]}
```

`panels` has exactly N lists; each list holds at most one motion/physics entry first, then at most one style entry. `bin/ltx-story-manifest --catalog-loras` copies each list into that panel's `"catalog_loras"` key (same six keys per entry).

---

## 3. Story engine requirements (normative)

### RS1. `story_engine.py` module

- Top-level imports exactly: `collections`, `copy`, `datetime`, `hashlib`, `importlib.machinery`, `json`, `os`, `re`, `shlex`, `subprocess`, `sys`, `time`, `uuid`. Nothing else at top level.
- Module docstring: one paragraph naming this spec and stating "stdlib only; loaded by path by bin/ltx-movie and bin/judge-story; loads character_lib.py, lora_catalog.py and fleet_lib.py by path, only inside functions".
- Path loaders (each caches nothing; loads by path from `ws`): `_character_lib(ws)` -> `SourceFileLoader("character_lib", <ws>/character_lib.py)`; `_lora_catalog(ws)` -> `SourceFileLoader("lora_catalog", <ws>/lora_catalog.py)`; `_load_fleet(ws)` -> `SourceFileLoader("fleet_lib_for_story", <ws>/fleet_lib.py)` wrapped in `try/except Exception: return None`.
- Injectable seams used by tests: module attributes `_now = time.monotonic`, `_utc = lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`, and the functions `run_agent`, `run_critic`, `run_judge` (tests replace them via `monkeypatch.setattr`).

### RS2. Flags and engine resolution in `bin/ltx-movie`

Parser additions, appended after `--dry-run` (`:412`), in this order:

```python
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
```

`_parse_goal(text)` is a module-level function in `bin/ltx-movie` with exactly the body of `bin/judge-story`'s `parse_goal` (strip; drop one trailing `.`; reject empty, a line break, or more than 300 characters with `argparse.ArgumentTypeError` and the same three messages), defined above `build_parser`. **[spec choice: a copy, because importing `bin/judge-story` would import `anthropic`.]**

`_resolve_story_engine(args)` runs in `main()` immediately after `_resolve_global_loras` and before the `args.dry_run` branch. Returns 0 or 2 after one `Error:` line on stderr:

1. Let `legacy = args.story_legacy or args.story_prompt_override is not None`. Let `reason = "--story-legacy"` if `args.story_legacy` else `"--story-prompt-override"`.
2. If `legacy`: for each of `("--judge", args.judge)`, `("--no-auto-lora", args.no_auto_lora)`, `("--goal", args.goal is not None)` in that order, if set: `Error: %s needs the default story engine; it cannot be combined with %s` % (flag, reason) -> 2. Else `args.story_engine = "legacy"`, `args.story_catalog = None` -> 0.
3. Else: if `args.judge and not os.environ.get("ANTHROPIC_API_KEY")`: `Error: --judge needs ANTHROPIC_API_KEY for bin/judge-story; export it or drop --judge` -> 2. **[spec choice: fail before a long local run, not after it.]**
4. If `args.no_auto_lora`: `args.story_catalog = {"schema_version": 1, "entries": []}`. Else load the catalog with `lora_catalog.load_catalog(lora_catalog.catalog_path(WS))` (loaded by path); a `lora_catalog.CatalogError` -> `Error: invalid LoRA catalog %s: %s; run bin/lora-catalog verify` -> 2. A missing file yields the empty catalog.
5. `args.story_engine = "robust"` -> 0.

`phase1_story(args)`: its first statement becomes `if getattr(args, "story_engine", "legacy") == "robust": return _phase1_robust(args)`. The rest of `phase1_story` is unchanged except RS31.

### RS3. Modes and fields

`mode` per `StoryContext`. The **assembled fields** per mode: chained panel 1 `Image`, `Motion`, `Narration`; chained panels 2..N `Motion`, `Narration`; no_stills `Prompt`, `Narration`; shots `Image`, `Motion`, `Narration`. `--seed-image` is chained only (`bin/ltx-movie` already rejects it with `--no-stills` and `--shots`).

### RS4. Constants (in `story_engine.py`)

| Name | Value |
|---|---|
| `PLAN_SCHEMA`, `CHECKS_SCHEMA`, `RUN_SCHEMA`, `CATALOG_LORAS_SCHEMA` | `"ltx-movie.plan.v1"`, `"ltx-movie.story-checks.v1"`, `"ltx-movie.story-run.v1"`, `"ltx-movie.catalog-loras.v1"` |
| `SHOT_TYPES` | `("extreme wide shot", "wide shot", "medium shot", "medium close-up", "close-up", "extreme close-up")` (the six of every legacy template) |
| `CAMERA_SENTENCES` | ordered tuple of pairs: `("static", "The camera stays static.")`, `("slow push-in", "The camera slowly pushes in.")`, `("slow pull-back", "The camera slowly pulls back.")`, `("slow pan left", "The camera slowly pans left.")`, `("slow pan right", "The camera slowly pans right.")`, `("slow tilt up", "The camera slowly tilts up.")`, `("slow tilt down", "The camera slowly tilts down.")`, `("tracking", "The camera tracks alongside the movement.")` **[spec choice: the approved static/slow push/pull/pan/tilt/tracking list, each made one fixed sentence that `character_lib._is_camera_sentence` recognises, so S5 never counts it as an action]** |
| `ARC_ROLES` | `("introduction", "rising", "climax", "falling", "resolution")` |
| `WORD_RANGES` | `{"chained": {"image1": (120, 170), "motion1": (25, 50), "motion": (15, 35)}, "no_stills": {"prompt": (150, 220)}, "shots": {"image": (80, 170), "motion": (10, 25)}}` (from `:131-138`, `:159`, `:189-190`) |
| `NARRATION_WORDS` | `(3, 30)` **[spec choice: the templates say only "one sentence"]** |
| `MIN_WRITER_WORDS` | `{"image": 20, "prompt": 20, "motion": 5}` |
| `MAX_CAST` | `{"chained": 4, "no_stills": 4, "shots": 2}` **[spec choice: shots = `SHOTS_MAX_CAST_PER_PANEL`; 4 elsewhere keeps pasted descriptions inside the word ranges]** |
| `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `CRITIC_MAX_ROUNDS`, `CRITIC_CALLS_PER_ROUND`, `MAX_PATCHES` | `2`, `2`, `3`, `2`, `8` |
| `MIN_OK_SCORE`, `JUDGE_MIN_SCORE` | `7`, `7` |
| `LORA_PANEL_LIMIT` | `4` |
| `PANEL_MAX_TOKENS`, `CRITIC_MAX_TOKENS` | `1536`, `4096` |
| `PANEL_TIMEOUT`, `CRITIC_TIMEOUT`, `JUDGE_TIMEOUT` | `600`, `900`, `900` seconds |
| `REQUEST_TIMEOUT` | `600` (the `--request-timeout` of every agent call, as today) |
| `MAX_LISTED` | `40` (violation lines listed in any prompt, then `- ... and N more`) |
| `REPEAT_JACCARD` | `0.6` |

Functions: `plan_max_tokens(n) = max(4096, n * 250)`, `plan_timeout(n) = max(600, n * 40)`, `wall_clock_cap(n) = max(2400, n * 180)` seconds **[spec choice: covers N+2 writer calls, 3 critic rounds and regenerations at ~40 s per local call]**.

### RS5. Agent call contract

`agent_cmd(ctx, prompt, *, max_tokens, image=None, skill=None)` returns exactly:

```
[sys.executable, os.path.join(ctx.ws, "bin", "qwen-agent"),
 "--workspace", ctx.ws,
 "--max-tokens", str(max_tokens), "--max-rounds", "1",
 "--request-timeout", "600"]
+ (["--model", ctx.story_model] if ctx.story_model else [])
+ (["--context-window", str(ctx.context_window)] if ctx.context_window else [])
+ (["--image", image] if image else [])
+ (["--skill=analyst"] if skill == "analyst" else [])
+ ["--user-prompt", prompt]
```

`--danger-auto-approve` is never passed (no tool is ever needed). `run_agent(ctx, prompt, *, max_tokens, timeout, image=None, skill=None, preflight_done=False)`:

- `subprocess.Popen(cmd, cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", env=env)` where `env = dict(os.environ)` plus `QWEN_AGENT_PREFLIGHT_DONE="1"` when `preflight_done`. `communicate(timeout=timeout)`; on `TimeoutExpired`: `proc.kill()`, `communicate()`, return `("timeout", None)`.
- The envelope is `json.loads` of the last non-empty stdout line; it must be a dict with `schema == "qwen-agent.oneshot.v1"`, else return `("no_envelope", None)`.
- Return `(envelope["status"], answer)` where `answer` is the envelope's `answer` when it is a non-empty string after `strip()`, else None. A non-`ok` status with an answer (a forced summary) is still parsed by the caller.
- The first agent call of a `run` uses `preflight_done=False`; every later call in the same `run` uses `True` **[spec choice: one tool-calling preflight proves the server; repeating it costs up to 90 s per call]**. `recheck` makes no agent call.

### RS6. JSON extraction

`extract_json(text)`: if `text` is None return None. If it contains three backticks, take the substring after the first fence line (drop an optional `json` tag) up to the next fence. Then take from the first `{` to the last `}` inclusive; `json.loads`; return it only if it is a dict, else None. Any exception -> None.

### RS7. Plan prompt (exact)

`build_plan_prompt(ctx, compatible, pins)` returns `PLAN_PROMPT_TEMPLATE` with its tokens replaced by `str.replace`, in this order: first the fragment tokens `@@GOAL_PARAGRAPH@@`, `@@MODE_PARAGRAPH@@`, `@@SEED_PARAGRAPH@@`, `@@CAST_FIXED@@`, `@@ARC_RULE@@`, `@@SHOT_LIST@@`, `@@CAMERA_LIST@@`, `@@LORA_PARAGRAPH@@`, `@@MODE_RULES@@`; then the scalars `@@STORY_ID@@`, `@@PANELS@@`, `@@SECONDS@@`, `@@MAX_CAST@@`; last `@@NARRATIVE@@` (so user text is never scanned for tokens). The rendered plan prompt contains **no `{` or `}` character** for any input whose narrative and goal contain none **[spec choice: deploy gate X2 rejects brace lines in the default dry run, `build_pkg.py:1117`]**.

```
You are planning a short narrated movie (story-id "@@STORY_ID@@").

Narrative to adapt:
@@NARRATIVE@@

@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@

@@SEED_PARAGRAPH@@Write the story bible as one JSON object with exactly these seven keys:

title: the movie's title, at most 8 words.
logline: one sentence of 8 to 40 words that summarises the story.
cast: a list with one object per character who is ever on screen, with the keys id, phrase and descriptor. id is c1, c2, c3 and so on, in order. phrase is the character's referring phrase: at most four words, built only from details in their descriptor or stated by the narrative; the movie names them by this exact phrase everywhere. descriptor is their full visual description in 8 to 60 words that starts with "a " or "an " and does not end with a full stop: apparent age group, build, skin tone, hair colour, length and style, clothing and accessories.@@CAST_FIXED@@
locations: a list with one object per place, with the keys id and setting. id is l1, l2 and so on. setting is one sentence of 12 to 45 words that starts with "The setting is" and names the period, the place, the ground and the light.
props: a list with one object per object that matters to the story, with the keys id and name. id is p1, p2 and so on; name is a short noun phrase for the object. Use an empty list when no object matters.
beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, arc, action, shot, camera, location and cast. index runs from 1 to @@PANELS@@. arc is one of introduction, rising, climax, falling, resolution, in story order; @@ARC_RULE@@ action is one sentence of 6 to 40 words saying what the characters physically do during these @@SECONDS@@ seconds: one continuous physical action that a camera can film, not a sequence of steps, with no dialogue and no on-screen text. shot is exactly one of: @@SHOT_LIST@@. camera is exactly one of: @@CAMERA_LIST@@. location is the id of the place where the beat happens. cast is the list of ids of the characters on screen in the beat, at most @@MAX_CAST@@.
loras: @@LORA_PARAGRAPH@@

@@MODE_RULES@@Reply with the JSON object only, with no text before or after it. Do not call any tool: do NOT read any file, do NOT run run_python or any other tool to check it, and do NOT count or recount words.
```

Fragments:

- `@@GOAL_PARAGRAPH@@`: `""` when `ctx.goal` is None, else `"The target output goal is " + ctx.goal + ".\n\n"`.
- `@@MODE_PARAGRAPH@@` (`MODE_PARAGRAPHS[mode]`, also used by RS12 and RS17):
  - chained: `it is ONE continuous take, built @@SECONDS@@ seconds at a time. Panel 1 starts from a single still picture, and every later panel continues from the exact last frame of the panel before it. There are no cuts and no jumps in time or place: a new place, object or character must arrive through visible movement inside a beat.`
  - no_stills: `every panel is a separate @@SECONDS@@-second shot rendered from text alone, joined to the next panel by a hard cut. Nothing carries over between panels except what the text states.`
  - shots: `it is a sequence of separate shots joined by cuts, @@SECONDS@@ seconds each. Every panel is one shot that starts from its own still picture. One beat is one action: a fight or a chase takes several beats.`
- `@@SEED_PARAGRAPH@@`: `""` unless `ctx.seed_agent_image`; then `An image is attached to this message. It IS the first frame of this movie. Describe every person it shows faithfully in cast -- each one's apparent age group, build, skin tone, hair, clothing and accessories as actually visible -- invent no person who is not visible, and make beat 1 start from the exact scene it shows.` followed by `"\n\n"`.
- `@@CAST_FIXED@@`: the RS37 reserved sentence (possibly empty) followed by: `""` when `ctx.members` is empty; else ` The following characters are already cast; list them first in cast with exactly these ids, phrases and descriptors, and give your own characters the next ids:` followed, per member in `ctx.members` order (i from 1), by `\n- id c<i>, phrase "<phrase>", descriptor "<descriptor>"`.
- `@@ARC_RULE@@`: N >= 3: `the first beat is introduction, the last is resolution, and at least one beat is climax.`; N == 2: `the first beat is introduction and the last is resolution.`; N == 1: `use climax.`
- `@@SHOT_LIST@@`: `", ".join(SHOT_TYPES)`; `@@CAMERA_LIST@@`: `", ".join(key for key, _ in CAMERA_SENTENCES)`.
- `@@LORA_PARAGRAPH@@`: when `not ctx.auto_lora` or `compatible` is empty: `an object with the keys global, per_beat and stills, each empty: global and stills are empty lists and per_beat is an empty object.` Otherwise:
  `an object with the keys global, per_beat and stills. Each pick is an object with the keys id and strength, taken from the LoRA catalog below; strength must lie inside that entry's range. global is a list of picks applied to every panel: at most one style LoRA, plus motion or physics LoRAs that suit the whole movie. per_beat maps a beat index, written as a string, to a list of motion or physics picks for that beat only; every beat may have at most one motion or physics LoRA in total, counting global. stills is a list of at most one stills LoRA.` + (` This movie has no stills, so stills stays empty.` when mode is no_stills) + ` Pick a LoRA only when its use-when text fits and its avoid-when text does not; leave the lists empty when nothing fits.` + `"\n\nLoRA catalog (pick only from these):\n"` + `"\n".join(catalog_line(e) for e in compatible)` + the pins block.
  - `catalog_line(e)` = `"- %s: %s LoRA for %s, default strength %s, range %s to %s. %s Use when: %s Avoid when: %s" % (id, kind, target, repr(float(default_strength)), repr(float(lo)), repr(float(hi)), _sentence(description), _sentence(use_when), _sentence(avoid_when) if avoid_when else "nothing listed.")`, where `_sentence(t)` strips `t`, collapses whitespace and appends `.` unless it ends in `.`, `!` or `?`.
  - Pins block (when `pins` non-empty): `"\nAlready applied to every panel by the user, not to be picked again:"` then per pin `"\n- %s (%s) at strength %s" % (catalog_id, kind, repr(float(strength)))` for a catalog pin or `"\n- a LoRA outside the catalog at strength %s"` otherwise.
- `@@MODE_RULES@@`:
  - chained: `Rules for this movie: keep consecutive beats at the same location unless the action itself moves the characters there, and put every character who can be seen in the opening frame in beat 1's cast.` + `"\n\n"`.
  - shots: `Rules for this movie: two people never touch on screen. Split every strike, grab, push, block or hand-off into two consecutive beats -- first a beat whose cast is only the person who acts, then a beat whose cast is only the person acted on -- so the contact itself is never on screen.` + `"\n\n"` **[spec choice: the split rule moves into the plan, where the model creates beats; [RULES2] 0.2 measured that it ignores restructuring requests on a finished story]**.
  - no_stills: `""`.

The robust prompts contain no example content sentence **[spec choice: "examples get copied"]**.

### RS8. Plan calls

1. Call 1: `run_agent(ctx, prompt, max_tokens=plan_max_tokens(N), timeout=plan_timeout(N), image=ctx.seed_agent_image)`. Save `plan_prompt.txt`, `plan_reply_1.txt`.
2. Parse with `extract_json`; normalize and check (RS9-RS11). Call 2 is made when the reply is not a JSON object, or the checks report any hard P or L violation. Its prompt is the plan prompt + `"\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n"` + the violation lines (`"- " + message`, at most `MAX_LISTED`, then `"- ... and N more"`; for an unparseable reply the single line `- the reply is not one JSON object`) + `"\nPrevious reply:\n"` + the previous answer text truncated to its first 20000 characters (or `<no answer: STATUS>`) + `"\n\nReply with the complete corrected JSON object only."`. Saved as `plan_reply_2.txt` (the prompt is not saved a second time). Call 2's plan replaces call 1's only if it parses; otherwise call 1's parsed plan (if any) is kept.
3. **Fatal (exit 1, no story.md written)** after the last plan call: no parsed plan, or any P1 or P2 violation. Message (stderr): `Error: the story model did not return a usable plan after %d call(s)` + one `  - <message>` line per P1/P2 violation (or `  - the reply is not one JSON object`) + `Raw replies are kept in <round_0 dir>. Rerun the same command to try again.`
4. Every other P/L hard violation is carried into the rounds.

### RS9. Plan normalization and `plan.json`

On a parsed object `raw`, `normalize_plan(ctx, raw)` builds the plan dict of Section 2.2:

- Strings: `strip()` and collapse runs of whitespace to one space. `title`, `logline`, `phrase`, `descriptor`, `setting`, `name`, `action`, `arc`, `shot`, `camera`: as given (lowercased for `arc`, `shot`, `camera`). A descriptor ending in `.` loses that `.`; a setting not ending in `.`, `!` or `?` gains `.`.
- Fixed cast: for member i (1-based, `ctx.members` order) the entry with id `c<i>` is forced to `phrase = member.phrase`, `descriptor = member.descriptor`, `cast_name = member.name`; when the model omitted it, it is inserted at position i-1. Every other entry gets `cast_name: null`. **[spec choice: descriptors are immutable and code-owned; overwriting is silent because it can only improve conformance]**
- `loras`: absent or not an object -> `{"global": [], "per_beat": {}, "stills": []}`. Each pick lacking `strength` gets the entry's `default_strength` (when the id exists). `per_beat` keys are kept as given (L1 reports bad keys). When `not ctx.auto_lora`, the model's `loras` is discarded and replaced by the empty value **[spec choice: deterministic]**. `pinned` is set from `ctx.pinned` (LC12).
- Metadata keys `schema`, `story_id`, `mode`, `panels`, `seconds`, `narrative`, `goal`, `seed_image`, `video_model`, `auto_lora` come from `ctx`. Unknown model keys are dropped.
- Shape problems (missing keys, wrong types) are not raised: they become P2 violations and the offending value is replaced by an empty value of the right type so assembly can proceed.

### RS10. Plan checks

`plan_checks(ctx, plan)` returns `(hard, advisory)` lists of violation strings, in this order:

| ID | Name | Severity | Rule | Message |
|---|---|---|---|---|
| P1 | beat count | hard | `beats` has exactly N entries and `beats[i]["index"] == i + 1` | `plan: P1 beat count: expected exactly N beats, found M` / `plan: P1 beat count: beat K has index V; beats must be numbered 1 to N in order` |
| P2 | structure | hard | top level has `title`, `logline` (non-empty strings), `cast`, `locations`, `props`, `beats` (lists of objects); required sub-keys present with the right types; ids match `c[1-9][0-9]*`, `l[1-9][0-9]*`, `p[1-9][0-9]*` and are unique per kind; at least one location; every `beat.location` is a defined location id; every `beat.cast` entry is a defined cast id, no duplicates in a beat | `plan: P2 structure: <detail>` / `beat K: P2 structure: location 'l9' is not defined` / `beat K: P2 structure: cast id 'c9' is not defined` |
| P3 | cast entry | hard | `normalize_phrase` accepts the phrase; a phrase of a non-fixed entry has at most 4 words; phrases unique (case-insensitive); `validate_descriptor` accepts the descriptor | `plan: P3 cast entry: c2's phrase 'X' has 5 words; at most 4` / `plan: P3 cast entry: c2's phrase 'X' is also c1's` / `plan: P3 cast entry: c2's <CharacterError text>` |
| P4 | setting sentence | hard | starts with `The setting is `; 12-45 words; exactly one sentence (`character_lib._SENTENCE_SPLIT_RE` yields one non-empty piece) | `plan: P4 setting sentence: l2's setting <is W words; it must be 12-45 / does not start with "The setting is" / is more than one sentence>` |
| P5 | arc | hard | every `arc` in `ARC_ROLES`; required roles present: N==1 none, N==2 {introduction, resolution}, N>=3 {introduction, climax, resolution} | `beat K: P5 arc: 'X' is not one of introduction, rising, climax, falling, resolution` / `plan: P5 arc: no beat has arc 'climax'` |
| P6 | arc order | advisory | ranks of `ARC_ROLES` never decrease from beat to beat; for N>=2 the first arc is introduction and the last is resolution | `beat K: P6 arc order: 'rising' follows 'climax'` / `plan: P6 arc order: the first beat's arc is 'rising', not 'introduction'` / `plan: P6 arc order: the last beat's arc is 'climax', not 'resolution'` |
| P7 | shot type | hard | `shot` in `SHOT_TYPES` | `beat K: P7 shot type: 'X' is not one of: <SHOT_TYPES joined ", ">` |
| P8 | camera | hard | `camera` is a key of `CAMERA_SENTENCES` | `beat K: P8 camera: 'X' is not one of: <keys joined ", ">` |
| P9 | cast count | hard | `len(beat.cast) <= MAX_CAST[mode]` | `beat K: P9 cast count: C characters on screen; at most M in this mode` |
| P10 | word budget | hard | for every pasted field of the beat (RS14), `hi - pasted_words >= MIN_WRITER_WORDS[field kind]` | `beat K: P10 word budget: Image: the pasted sentences take W of its LO-HI words, leaving fewer than M for the writer` |
| P11 | location change | advisory, chained | beat K's location differs from beat K-1's | `beat K: P11 location change: moves from l1 to l2 with no cut; the action must carry the characters there` |
| P12 | new character | advisory, chained, K >= 2 | a cast id of beat K is not in beat 1's cast | `beat K: P12 new character: c3 is not in the opening frame; their look is left to the video model` |
| P13 | undeclared character | hard | RS37: no plan text references an undeclared library character | `plan: P13 undeclared character: <where> names library character <name> by its <kind> '<text>'; library characters appear only when declared with --character <name>` |

P3-P12 run only on entries that passed P2 for the fields they read.

### RS11. LoRA plan checks

`lora_checks(ctx, plan, compatible_by_id, catalog_by_id)` returns `(hard, advisory)`; the rules are LC12's numbers. Definitions: an **auto pick** is any pick in `global`, `per_beat` or `stills`; the **video LoRAs of panel K** are, in this order, every pin (catalog or not), every `global` pick, every `per_beat[str(K)]` pick, and one per beat-K cast entry with a non-null `cast_name`.

| ID | Name | Severity | Rule | Message |
|---|---|---|---|---|
| L1 | catalog id | hard | every pick is an object with a string `id` and a numeric (`bool` excluded) `strength`; `id` in the catalog; the entry is compatible (LC6) with `ctx.video_model` (video) or `lora_catalog.STILLS_BASE_MODEL` (stills); `global`/`per_beat` picks have target `video`, `stills` picks target `stills`; every `per_beat` key is `str(k)` for a k in 1..N | `plan: L1 catalog id: 'x' is not in the catalog` / `plan: L1 catalog id: 'x' does not support model M` / `plan: L1 catalog id: 'x' is a stills LoRA; global and per-beat picks must be video LoRAs` / `plan: L1 catalog id: 'x' is a video LoRA; a stills pick must be a stills LoRA` / `plan: L1 catalog id: per_beat key 'k' is not a beat number from 1 to N` / `plan: L1 catalog id: pick V is not an object with an id and a numeric strength` (scope `beat K` for picks under `per_beat`) |
| L2 | style | hard | at most one style LoRA among pins and `global`; no style pick in `per_beat` | `plan: L2 style: S style LoRAs for every panel (a, b); at most 1` / `beat K: L2 style: style LoRA 'x' can only be a global pick` |
| L3 | motion | hard | per panel at most one motion/physics LoRA among its video LoRAs | `beat K: L3 motion: C motion or physics LoRAs on this panel (a, b); at most 1` |
| L4 | LoRA count | hard if panel K has at least one auto pick, else advisory | panel K has at most `LORA_PANEL_LIMIT` video LoRAs | `beat K: L4 LoRA count: C LoRAs on this panel (labels); at most 4` (labels: catalog ids, `pinned LoRA`, `character NAME`) |
| L5 | strength | hard | an auto pick's strength lies in its entry's `strength_range` (inclusive); pins are not checked **[spec choice: the user chose the pin's strength]**; strengths are never changed by code | `plan: L5 strength: 'x' strength 1.4 is outside its range 0.5 to 1.0` |
| L6 | duplicate | hard | no id twice among a panel's video LoRAs; no auto pick whose path's realpath equals a pin's | `beat K: L6 duplicate: 'x' is applied twice on this panel` |
| L7 | stills | hard | `stills` has at most one pick; empty in no_stills mode; its path's realpath is not in `ctx.stills_pinned` | `plan: L7 stills: S stills LoRAs; at most 1` / `plan: L7 stills: this movie has no stills; stills must be empty` / `plan: L7 stills: 'x' is also passed with --stills-lora` |

When `not ctx.auto_lora`, L1-L7 are not run (picks are empty and pins are the user's).

### RS12. Panel prompt (exact)

`build_panel_prompt(ctx, plan, parts, k, fix=None)`; tokens replaced in the RS7 order (fragments, scalars, then `@@NARRATIVE@@`):

```
You are writing panel @@K@@ of @@PANELS@@ of a short narrated movie (story-id "@@STORY_ID@@").

Narrative to adapt:
@@NARRATIVE@@

@@GOAL_PARAGRAPH@@How this movie is made: @@MODE_PARAGRAPH@@

@@PANEL_RULES@@The beats of the whole movie, one per panel (this panel is marked >>):
@@BEAT_LINES@@

This panel's beat: @@ACTION@@
Characters on screen in this panel, named only by these exact referring phrases: @@CAST_PHRASES@@
@@PREVIOUS@@
@@SEED_PANEL@@Write this panel as one JSON object with exactly these keys:

@@KEY_LINES@@

@@FIX_BLOCK@@Reply with the JSON object only, with no text before or after it. Do not call any tool: do NOT read any file, do NOT run run_python or any other tool to check it, and do NOT count or recount words.
```

- `@@PANEL_RULES@@`: no_stills: `"Rules:\n"` + the lines of `STORY_PROMPT_TEMPLATE_NO_STILLS` between `"Rules:\n"` and `"\n\nNarrative to adapt:"`, each `strip()`ped, joined by `"\n"`, + `"\n\n"`; the template is read from `bin/ltx-movie`'s module by the caller and passed in as `ctx`-independent argument `no_stills_rules` (`build_panel_prompt(..., no_stills_rules="")`) **[spec choice: keeps the mode's existing content directives without duplicating their text]**. shots: `Rules for this shot: two people never touch on screen, nothing outside the frame is ever mentioned, and who faces whom is shown with fixed left and right screen direction.` + `"\n\n"`. chained: `""`.
- `@@BEAT_LINES@@`: one line per beat: `(">> " if index == k else "   ") + "%d. (%s) %s" % (index, arc, action)`, joined by `"\n"`.
- `@@ACTION@@`: beat k's action. `@@CAST_PHRASES@@`: `"; ".join('"%s"' % phrase for each beat-k cast id in order)` or `nobody`.
- `@@PREVIOUS@@`: chained and k >= 2: `"The previous panel's Motion: " + <assembled Motion of panel k-1 in the current state> + "\n"`; else `""`.
- `@@SEED_PANEL@@`: chained, k == 1, `ctx.seed_agent_image` set: `An image is attached to this message. It IS this movie's first frame: describe in image exactly what it shows -- each person's pose and place in the frame, the background, the lighting, the colour palette and the visual style -- and start motion from that exact pose.` + `"\n\n"`; else `""`.
- `@@KEY_LINES@@`: the key lines for the mode/panel (Section 2.3) joined by `"\n"`, with `W1`/`W2` from RS14's writer targets:
  - `title: a short title for the panel, 2 to 6 words.`
  - chained `image` (k == 1): `image: W1 to W2 words describing the opening frame as one still picture: where each character stands and which way they face, the background, the lighting and colour palette, the camera viewpoint and the rendering style. Do not describe any character's appearance or clothing, do not write a sentence about the place itself and do not name the shot type: the pipeline adds each character's description, the place's setting sentence and the shot type to this field itself.`
  - chained `motion` (k == 1): `motion: W1 to W2 words in one or two plain sentences: what the characters physically do during these S seconds. Name each character only by their referring phrase, word for word. Describe ONE continuous physical motion, not a sequence of separate steps. Do not mention the camera: the pipeline adds the camera sentence.`
  - chained `motion` (k >= 2): `motion: W1 to W2 words in one or two plain sentences: what the characters physically do during these S seconds, continuing from where the previous panel left them. Name each character only by their referring phrase, word for word. Describe ONE continuous physical motion, not a sequence of separate steps: S seconds is enough for a single gesture, a few footsteps or the start of a movement. Do not describe appearance, clothing, setting, lighting, colour, style, camera or lens -- all of that is already on screen.`
  - no_stills `prompt`: `prompt: W1 to W2 words in the present tense: one flowing paragraph in strict chronological order that opens with the main action, carries enough separate beats to fill the full S seconds, links them with temporal connectors (initially, as, then, while, a moment later), names the ambient and environmental sounds alongside the actions that make them, and states the camera viewpoint and the lighting and colour. Name each character only by their referring phrase. Do not describe any character's appearance or clothing, do not write a sentence about the place itself and do not name the shot type or the camera motion: the pipeline adds each character's description, the place's setting sentence, the shot type and the camera motion itself. Describe only what is physically observable, with no mood words, no spoken dialogue and no markdown.`
  - shots `image`: `image: W1 to W2 words describing this shot's first frame as one still picture: where each character stands and which way they face, using fixed left and right screen direction; the background; the lighting and colour palette; the camera viewpoint; and the rendering style. Do not describe any character's appearance or clothing, do not write a sentence about the place itself and do not name the shot type: the pipeline adds each character's description, the place's setting sentence and the shot type to this field itself. Never name a person who is not in this shot.`
  - shots `motion`: `motion: ONE sentence of W1 to W2 words naming ONE character by their referring phrase and the ONE physical action they perform during these S seconds. Never chain actions with then, while, meanwhile, simultaneously, afterwards, followed by or a comma before and, and never use a semicolon. Do not mention the camera: the pipeline adds the camera sentence.`
  - `narration: one sentence of voice-over narration, 3 to 30 words.`
  (`S` is `ctx.seconds`; written literally into the line before token replacement as `@@SECONDS@@`.)
- `@@FIX_BLOCK@@`: `""` when `fix` is None; else `"Your previous version of this panel was rejected. Problems:\n"` + the panel's violation lines (`"- " + message`, at most `MAX_LISTED`) + `"\nPrevious version:\n"` + one `"<key>: <value>"` line per current writer part of the panel (Section 2.3 key order; missing parts shown as empty) + `"\n\n"`. For an unparseable reply the problem line is `- the reply is not one JSON object with the keys <keys joined ", ">`.

### RS13. Panel calls and writer parts

- Each panel's first call happens in round 0 in panel order: `run_agent(ctx, prompt, max_tokens=PANEL_MAX_TOKENS, timeout=PANEL_TIMEOUT, image=(ctx.seed_agent_image if mode == "chained" and k == 1 else None))`. Files `panel_%02d_prompt_%d.txt` / `panel_%02d_reply_%d.txt` (call number within the whole run).
- A reply is **valid** when `extract_json` yields an object in which every non-title key of Section 2.3 holds a string that is non-empty after cleanup. Invalid -> one retry with `fix` = the unparseable-reply problem line, if the panel's budget allows (`PANEL_MAX_CALLS` calls per panel for the whole run, counting the first call, retries, `beat.action` regenerations and code-only regenerations). A panel still without a valid reply gets empty parts (assembly proceeds; N1/N11 then report it).
- Cleanup of every writer string, in order: `strip()`; remove one leading label matching `^(?:title|image|motion|prompt|narration)\s*:\s*` (case-insensitive); remove one pair of surrounding double quotes (`"`, `“`/`”`); collapse whitespace runs (including newlines) to one space; remove every case- and whitespace-insensitive occurrence of a pasted sentence of that field (RS14) using `character_lib._passage_spans` and `_blank`, then collapse whitespace again and `strip()`.
- `title`: if missing, empty or longer than 6 words -> the first five words of the beat action with every character other than letters, digits, spaces, `'` and `-` removed **[spec choice]**.

### RS14. Assembly

`assemble(ctx, plan, parts)` returns the `story.md` text. Definitions:

- `identity(c)` = `c["phrase"][:1].upper() + c["phrase"][1:] + " is " + c["descriptor"] + "."` (the `character_lib.identity_sentence` format, for every plan cast entry).
- `shot_sentence(beat)` = `"The shot is " + ("an " if shot starts with a vowel else "a ") + shot + "."`.
- `camera_sentence(beat)` = the `CAMERA_SENTENCES` value for `beat.camera`.
- `_sentence(t)` as RS7; `join(pieces)` = `" ".join(_sentence(p) for p in pieces if p.strip())`.

Assembled fields (the **pasted sentences** of each field are the non-writer pieces):

| Mode / panel | Field | Pieces, in order |
|---|---|---|
| chained 1 | Image | setting of beat 1's location; `identity(c)` per beat-1 cast id in beat order; writer `image`; `shot_sentence` |
| chained 1 | Motion | writer `motion`; `camera_sentence` |
| chained k>=2 | Motion | writer `motion` |
| no_stills | Prompt | writer `prompt`; `identity(c)` per beat cast id; setting; `shot_sentence`; `camera_sentence` |
| shots | Image | setting; `identity(c)` per beat cast id; writer `image`; `shot_sentence` |
| shots | Motion | writer `motion`; `camera_sentence` |
| all | Narration | writer `narration` (`_sentence` applied) |

Writer targets (used in RS12): for a field with range `(lo, hi)` (`image1`/`motion1`/`motion` for chained, `prompt`, `image`/`motion` for shots) and pasted word count `p` (`len(" ".join(pasted).split())`): `W1 = max(MIN_WRITER_WORDS[kind], lo - p)`, `W2 = max(W1, hi - p)`, where kind is `image`, `prompt` or `motion`.

File layout (each line ends with `"\n"`; no trailing blank line after the last panel's Narration line):

```
# <title>

<logline>

[shots only:]
## Characters
- "<phrase>": <descriptor>.        (one line per plan cast entry, plan order)

## Panel 1 — <panel title>
Image: <...>                        (chained panel 1, shots)
Prompt: <...>                       (no_stills)
Motion: <...>                       (chained, shots)
Narration: <...>

## Panel 2 — <panel title>
...
```

Sections are separated by one blank line. The dash is U+2014. A field whose assembled text is empty is still written as `Label: ` with nothing after the space (validators report it).

### RS15. Panel checks

`panel_checks(ctx, plan, parts, text)` returns `(hard, advisory)`, panel by panel, then (shots) `character_lib.shots_violations(text, panels, N, ctx.members)` appended to `hard` and `character_lib.shots_advisories(panels, ctx.members)` to `advisory` (S1-S12 and W2 unchanged). `panels` is `_parse_prompts_md` output, obtained through `bin/ltx-story-manifest` loaded by path exactly as `_load_story_panels` does, on a temporary copy written to `<round dir>/story.md`. **Writer text** below means the cleaned writer parts; **field text** means the assembled field.

| ID | Name | Severity | Scope | Rule | Message |
|---|---|---|---|---|---|
| N1 | word count | hard | every assembled field of RS14 except shots Motion (S4 covers it) and Narration | `lo <= len(field.split()) <= hi` | `panel K: N1 word count: Motion: is W words; it must be LO-HI` |
| N2 | referring phrase | hard | chained Motion, panels 2..N | no `character_lib._person_refs(sentence, humans, animals, [])` reference whose key is a `SHOTS_PERSON_NOUNS` noun (humans = plan phrases that are not `is_animal_phrase`, animals = those that are) | `panel K: N2 referring phrase: Motion: names 'woman' outside every referring phrase; name each character by their exact phrase` |
| N3 | appearance | hard | chained Motion, panels 2..N | after blanking every plan phrase and prop name (`_passage_spans` + `_blank`), no `APPEARANCE_WORDS` word (RS16) matches as a whole word (case-insensitive) | `panel K: N3 appearance: Motion: says 'grey'; panels after the first never re-describe appearance, clothing, setting, lighting, colour, style or camera` |
| N4 | stray cast | hard | writer text of every field except Narration | `character_lib.find_phrases(writer text, all plan phrases)` contains no phrase whose cast id is not in beat K's cast | `panel K: N4 stray cast: Motion: names 'the ronin', who is not in beat K's cast` |
| N5 | setting sentence | hard | chained panel 1 Image, shots Image, no_stills Prompt | the beat's setting appears (case-/whitespace-insensitive, trailing `.` ignored) and no other location's setting appears | `panel K: N5 setting sentence: Image: lacks l1's setting sentence word for word` / `panel K: N5 setting sentence: Image: contains l2's setting sentence; beat K is at l1` |
| N6 | description | hard | the same fields as N5 | every beat-K cast entry's descriptor appears (same matching); in shots mode entries with a non-null `cast_name` are skipped (S9 covers them) | `panel K: N6 description: Image: lacks c2's description word for word` |
| N7 | dialogue and text | hard | writer text of Image/Motion/Prompt | no `"`, `“` or `”`; no `DIALOGUE_RE` match; no `ONSCREEN_TEXT_RE` match | `panel K: N7 dialogue and text: Motion: <contains a double quote / says 'shouts' / says 'caption'>` |
| N8 | off-screen | hard | writer text of Image/Motion/Prompt, chained and no_stills (shots: S11) | no `character_lib._OFFSCREEN_RE` match | `panel K: N8 off-screen: Image: says 'off-screen'; describe only what is in the frame` |
| N9 | cut wording | hard | writer text of Image/Motion/Prompt, all modes | no `CUT_RE` match | `panel K: N9 cut wording: Motion: says 'cut to'; one panel is one continuous shot` |
| N10 | copied example | hard | writer text of every field, plus (scope `plan`) every descriptor, setting and action of the plan | no `PLACEHOLDER_RE` match; no `COPIED_EXAMPLES` phrase (lowercased, whitespace-collapsed, trailing `.` dropped) inside the equally normalized text | `panel K: N10 copied example: Motion: contains template text 'X'` / `plan: N10 copied example: l1's setting contains template text 'X'` |
| N11 | narration | hard | Narration | non-empty | `panel K: N11 narration: Narration: is empty` |
| N12 | one action | advisory | chained Motion writer text | no `_CHAIN_WORD_RE`, `;` or `_COMMA_AND_RE` match | `panel K: N12 one action: Motion: chains actions with 'then'` |
| N13 | repeat | advisory | consecutive panels' action writer text (chained/shots `motion`, no_stills `prompt`) | Jaccard similarity of their word sets (lowercased `_WORD_RE` words of length >= 3, minus every word of every plan phrase) is below `REPEAT_JACCARD` | `panel K: N13 repeat: Motion: repeats panel K-1's action (similarity 0.71)` (two decimals) |
| N14 | narration form | advisory | Narration | exactly one sentence (`_SENTENCE_SPLIT_RE`) and `NARRATION_WORDS` words | `panel K: N14 narration form: Narration: is 2 sentences / is W words; it should be one sentence of 3-30 words` |
| N15 | undeclared character | hard | panel title and every assembled field (Image/Motion/Prompt/Narration) | RS37: no reference to an undeclared library character | `panel K: N15 undeclared character: <Label>: names library character <name> by its <kind> '<text>'; library characters appear only when declared with --character <name>` (`<Label>` is `Title`, `Image`, `Motion`, `Prompt` or `Narration`) |

Each check reports at most one violation per panel per field (the first match).

### RS16. Lexicons (constants in `story_engine.py`)

- `APPEARANCE_WORDS` (frozenset; the categories the chained template forbids in later Motion, `bin/ltx-movie:138`) **[spec choice: a pinned word list; ambiguous words such as short, light, ring, cap, fair are excluded to avoid false positives]**:
  colours `red orange yellow green blue purple violet pink brown black white grey gray silver gold golden crimson scarlet navy beige auburn blonde blond brunette ginger`; hair and face `hair haired ponytail braid braided curls curly bald beard bearded moustache mustache stubble freckled wrinkled complexion`; clothing `wearing wears dressed dress shirt jacket coat cloak kimono robe hood hat helmet trousers pants jeans skirt boots shoes sandals gloves scarf belt armor armour uniform tunic vest apron glasses spectacles earrings necklace bracelet`; build `slender stocky muscular skinny plump pale tanned`; setting, lighting and style `lighting lit sunlight moonlight palette colour color cinematic photorealistic rendered style`; camera `camera lens zoom zooms dolly framing close-up`.
- `DIALOGUE_RE` = `re.compile(r"\b(?:say|says|said|saying|shout|shouts|shouted|shouting|whisper|whispers|whispered|whispering|yell|yells|yelled|yelling|ask|asks|asked|asking|reply|replies|replied|replying|tell|tells|told|telling|speak|speaks|spoke|speaking|exclaim|exclaims|exclaimed|mutter|mutters|muttered|murmur|murmurs|murmured|call(?:s|ed)?\s+out)\b", re.IGNORECASE)`.
- `ONSCREEN_TEXT_RE` = `re.compile(r"\b(?:captions?|subtitles?|title\s+cards?|on-screen\s+text|text\s+reading|that\s+reads|which\s+reads|lettering|inscription|written\s+words)\b", re.IGNORECASE)`.
- `CUT_RE` = `re.compile(r"\b(?:cuts?\s+to|smash\s+cut|jump\s+cut|fades?\s+(?:in|out|to)|dissolves?\s+to|flashback|hours\s+later|the\s+next\s+(?:day|morning))\b", re.IGNORECASE)`.
- `PLACEHOLDER_RE` = `re.compile(r"<[^<>]{1,80}>")` (an unreplaced template placeholder).
- `COPIED_EXAMPLES` (tuple; the example text of the legacy templates the model was observed to copy) **[spec choice: sourced from the templates in `bin/ltx-movie`; RST12 asserts each is a substring of a legacy template so drift is caught]**:
  1. `The setting is a dense cedar forest in feudal Japan, tall trunks and ferns behind, the ground covered in leaf litter, under flat overcast grey light` (`:195`)
  2. `walking to a door, opening it, stepping through, and closing it behind them` (`:138`)
  3. `raising the blade, drawing back the arm, lunging forward` (`:197`)
  4. `recoiling, staggering, clutching the wound, falling` (`:197`)
  5. `her eyebrows angle down and her lips press together` (`:164`)
  6. `a charge, a draw and a strike` (`:193`)

### RS17. Critic prompt (exact)

`build_critic_prompt(plan, story_md_text, violations, catalog_lines=None, for_judge=False)`; mode, panels, seconds, narrative, goal and story_id come from `plan`'s metadata. Tokens replaced in the RS7 order; `@@PLAN_JSON@@` and `@@STORY_MD@@` are replaced after the scalars and before `@@NARRATIVE@@`.

```
You are the critic for a short narrated movie (story-id "@@STORY_ID@@"). You will not see any other context: everything you need is below. Check the draft against its plan and propose small, exact fixes.

How this movie is made: @@MODE_PARAGRAPH@@

Narrative to adapt:
@@NARRATIVE@@

@@GOAL_PARAGRAPH@@The plan (JSON):
@@PLAN_JSON@@

The draft story.md:
@@STORY_MD@@

Problems the pipeline's own checks found in this draft (fix the hard ones first):
@@VIOLATIONS@@

Score the draft from 1 (worst) to 10 (best) on each of:
- continuity: characters, places, objects and positions stay consistent from panel to panel.
- story: the panels tell the narrative@@GOAL_CLAUSE@@, with a clear introduction, climax and resolution, and every panel moves the action forward.
- renderability: every panel shows one concrete physical action that a video model can render in @@SECONDS@@ seconds, with no dialogue, no on-screen text and nothing outside the frame.

Then propose at most 8 patches, most important first. Each patch is an object with exactly the keys target, index, field, reason and replacement. The allowed patches are:
@@FIELD_LINES@@
A panel replacement holds only the text the writer writes: never include a character's description, a setting sentence, the shot type or a camera sentence, because the pipeline adds those itself. The number of panels, the characters' referring phrases and their descriptions never change.

@@REPLY_PARAGRAPH@@
```

- `@@PLAN_JSON@@`: `json.dumps({k: plan[k] for k in ("title", "logline", "cast", "locations", "props", "beats", "loras")}, indent=1, ensure_ascii=False)`.
- `@@VIOLATIONS@@`: `"- [hard] " + m` for every hard, then `"- [advisory] " + m` for every advisory, at most `MAX_LISTED` lines then `- ... and N more`; `- none` when both are empty. The critic sees only the violations of the state it judges.
- `@@GOAL_CLAUSE@@`: `" and serve the target output goal"` when a goal is set, else `""`.
- `@@FIELD_LINES@@`: the allowed lines for the mode (RS20 whitelist), in this order, joined by `"\n"`:
  - `- target "plan", field "beat.action", index = the beat number: replacement is the beat's new action, one sentence of 6 to 40 words; the pipeline rewrites that panel from it.`
  - `- target "plan", field "beat.shot", index = the beat number@@ONLY1@@: replacement is exactly one of: <SHOT_TYPES joined ", ">.`
  - `- target "plan", field "beat.camera", index = the beat number@@ONLY1@@: replacement is exactly one of: <camera keys joined ", ">.`
  - `- target "plan", field "location.setting", index = the place's position in the plan's locations list (1 is the first): replacement is its new setting sentence, 12 to 45 words starting "The setting is"; it replaces that sentence in every panel at that place.`
  - (only when `catalog_lines` is non-empty) `- target "plan", field "lora", index 0 for the global picks or a beat number for that beat's own picks: replacement is the complete new list of picks, each an object with the keys id and strength, from this catalog:` followed by `"\n"` + `"\n".join(catalog_lines)`.
  - `- target "panel", field "image", index = the panel number@@ONLY1@@: replacement is the new writer text of that panel's Image: field.` (chained, shots)
  - `- target "panel", field "motion", index = the panel number: replacement is the new writer text of that panel's Motion: field.` (chained, shots)
  - `- target "panel", field "prompt", index = the panel number: replacement is the new writer text of that panel's Prompt: field.` (no_stills)
  - `- target "panel", field "narration", index = the panel number: replacement is the panel's new narration sentence.`
  `@@ONLY1@@` is ` (only 1: later panels continue the same picture)` in chained mode and `""` otherwise.
- `@@REPLY_PARAGRAPH@@`: when `for_judge` is False: `Reply with one JSON object with exactly the keys scores, verdict and patches: scores is an object with the integer keys continuity, story and renderability; verdict is "ok" when the draft needs no patch and "revise" otherwise; patches is the list of patches (empty when the verdict is "ok"). Reply with the JSON object only, with no text before or after it. Do not call any tool: do NOT read any file, and do NOT run any tool to check it.` When True: `Call submit_review with your scores, verdict and patches.`

Retry prompt (second call of a critic round) = the prompt + `"\n\nYour previous reply was not one JSON object with the keys scores, verdict and patches in the required form. Reply with that JSON object only."`.

### RS18. Critic routing

`run_critic(ctx, prompt)` returns `(status, answer, route)`:

1. `fleet = _load_fleet(ctx.ws)`. If not None: `url, _ = fleet.daemon_url_from_env(os.environ)`; `view, _ = fleet.fetch_view(url)` (url may be None: `fetch_view(None)` returns `(None, None)`). If `view` is not None: `candidates = fleet.route_candidates("analyst", view)`. If `candidates` is non-empty and `candidates != [fleet.LOCAL]`: for each `host_id` in order: `outcome, envelope, detail = fleet.delegate_once(url, "analyst", prompt, host_id)`; if `outcome == "ok"` and `envelope.get("status") == "ok"` and `envelope.get("answer")` is a non-empty string -> return `("ok", answer, "fleet:" + host_id)`; else print `Warning: critic on %s failed: %s %s` % (host_id, outcome, detail or "") and continue. Every call into `fleet` is wrapped in `try/except Exception` (treated as "no view").
2. Local: `status, answer = run_agent(ctx, prompt, max_tokens=CRITIC_MAX_TOKENS, timeout=CRITIC_TIMEOUT, skill="analyst", preflight_done=True)`; return `(status, answer, "local")`.

No image is ever sent to the critic. The wall-clock cap is checked before each attempt (RS23).

### RS19. Critic reply validation

`parse_critic(answer)` -> the reply dict or None. Valid when `extract_json` yields an object with `scores` holding exactly-typed integers 1..10 for `continuity`, `story`, `renderability` (extra score keys ignored), `verdict` in `{"ok", "revise"}`, and `patches` a list. Invalid individual patches do not invalidate the reply; they are rejected by RS20. Invalid reply -> the retry call (RS17) if the round has calls left; still invalid -> the round is a **code-only round** (RS21).

### RS20. Patch whitelist and application

Whitelist (target, field) per mode; a patch outside it is rejected with `field not allowed in this mode`:

| Field | chained | no_stills | shots |
|---|---|---|---|
| plan `beat.action` | 1..N | 1..N | 1..N |
| plan `beat.shot`, `beat.camera` | 1 only | 1..N | 1..N |
| plan `location.setting` | 1..L | 1..L | 1..L |
| plan `lora` | 0..N (only when auto LoRA is on and the catalog has compatible video entries) | same | same |
| panel `image` | 1 only | -- | 1..N |
| panel `motion` | 1..N | -- | 1..N |
| panel `prompt` | -- | 1..N | -- |
| panel `narration` | 1..N | 1..N | 1..N |

`apply_patches(ctx, state, patches)` works on a deep copy of `state` (plan + parts) and returns `(new_state, applied, rejected, regenerate)`:

1. Only the first `MAX_PATCHES` list items are considered; each further item is rejected with `over the 8-patch limit`.
2. A patch that is not an object with the five keys, whose `target`/`field` is unknown, whose `index` is not an `int` (bool excluded) in the allowed range, or whose `replacement` has the wrong type (string; list for `lora`) is rejected with a reason naming the problem.
3. A second patch to the same `(target, index, field)` is rejected with `duplicate patch target`.
4. Plan patches, in list order:
   - `beat.action`: replacement cleaned (RS13 cleanup without pasted-sentence removal); rejected if it has fewer than 6 or more than 40 words; else stored; panel `index` is added to `regenerate`.
   - `beat.shot` / `beat.camera`: lowercased; rejected unless in `SHOT_TYPES` / camera keys; else stored (reassembly only, no regeneration).
   - `location.setting`: normalized as RS9; rejected if P4 would report it; else stored; every panel at that location is reassembled with the new sentence (the old sentence is no longer pasted anywhere).
   - `lora`: the picks list replaces `global` (index 0) or `per_beat[str(index)]` (an empty list deletes the key); the resulting plan is run through RS11; if it adds any hard L violation not present before, the patch is rejected with `would break <first new violation>` and the plan is restored.
5. Panel regeneration: for each panel in `regenerate` (ascending), if its budget allows, one panel call with `fix` = the panel's current violations and the new beat action shown in `@@ACTION@@`; a valid reply replaces the panel's writer parts; a failed call keeps the old parts. Over budget: the `beat.action` patch stays applied, the regeneration is skipped and recorded in `rejected` as `panel K regeneration skipped: call budget exhausted`.
6. Panel patches, in list order: a panel in `regenerate` -> rejected with `panel regenerated from a beat.action patch this round`; otherwise the replacement is cleaned (RS13, including pasted-sentence removal) and replaces that writer part; an empty result is rejected with `empty after cleanup`.
7. Descriptors and phrases are never written by any patch (no field reaches them). The number of beats and panels never changes.

### RS21. Round controller

```
state[0] = round 0 (plan + panels + checks)
for k in 1..CRITIC_MAX_ROUNDS:
    if wall clock exceeded: stop "time_cap"
    reply = critic round k on state[k-1]  (<= CRITIC_CALLS_PER_ROUND calls)
    if reply valid:
        state[k-1].scores, state[k-1].verdict = reply.scores, reply.verdict
        if hard(state[k-1]) == 0 and verdict == "ok" and min(scores) >= MIN_OK_SCORE: stop "passed"
        if k >= 2 and not better(state[k-1], state[k-2]): stop "plateau"
        state[k] = apply_patches(state[k-1], reply.patches) ; checks
    else:  (code-only round)
        if k >= 2 and hard(state[k-1]) >= hard(state[k-2]): stop "plateau"
        state[k] = regenerate every panel with a hard writer-text violation (N1-N4, N7-N11,
                   S4, S5, S7, S8, S10, S11) that has budget left, ascending, fix = its violations;
                   checks
    if k == CRITIC_MAX_ROUNDS: stop "max_rounds"
```

- `better(a, b)` compares `(hard count, -min score, -total score)` tuples with `<` (strictly better). Unscored states use the inherited scores of RS22.
- Each state's checks (`plan_checks`, `lora_checks`, `panel_checks`) are all re-run on every state; nothing is carried over.
- A state with no change (no applied patch, no regenerated panel) is still recorded as a round.
- Progress lines (stdout), exact formats: `plan: call %d of %d`; `panel %d/%d: call %d`; `round %d: %d hard, %d advisory`; `critic round %d (%s): continuity=%d story=%d renderability=%d verdict=%s; %d patch(es): %d applied, %d rejected`; `critic round %d: no valid reply after %d call(s); code-only round`; `stop: %s; best round %d (%d hard)`.

### RS22. Ranking and best round

- Inherited scores: an unscored state takes the scores of its nearest scored ancestor (`state[k-1]`, then `state[k-2]` ...); with none, `min = total = 0`.
- `rank(s) = (hard count, new P13/N15, -min score, -total score, -round number)`, where `new P13/N15` is 1 when the state has a P13 or N15 hard violation (compared by message) that round 0 does not have, else 0, so on an equal hard count a state that introduced an undeclared library character loses; the best round is the state with the smallest `rank` **[spec choice: on a full tie the later round wins, because it carries the critic's fixes on the same judged baseline]**.

### RS23. Budgets and the wall clock

- Plan calls <= 2; panel calls <= 2 per panel; critic rounds <= 3 with <= 2 calls each; patches <= 8 per round; the judge gate adds exactly one `bin/judge-story` call and one more critic round (RS24).
- The wall clock starts when `run` starts (`_now()`); before every agent, critic or judge call, if `_now() - start >= wall_clock_cap(N)`: during round 0 -> exit 1 with `Error: story generation exceeded the wall-clock cap of %ds before every panel was written; partial work is kept in <round_0 dir>`; later -> stop with `time_cap` and select the best round.

### RS24. Judge gate (`--judge`)

Runs after RS21/RS22 only when `ctx.judge` and the best round has 0 hard violations; when it has hard violations, `judge = {"status": "skipped", "detail": "best round has hard violations", ...}`.

1. `run_judge(ctx, round_dir)`: `subprocess.run([sys.executable, os.path.join(ctx.ws, "bin", "judge-story"), "--story-md", os.path.join(round_dir, "story.md"), "--patches"] + (["--goal", ctx.goal] if ctx.goal else []), cwd=ctx.ws, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=JUDGE_TIMEOUT)`; then read `<round_dir>/judgment.patches.json`. A nonzero exit, a timeout, or an unreadable file -> `judge = {"status": "error", "detail": <one line: "exit N" / "timeout" / exception text>, "scores": null, "min_score": null, "applied": false}`, a `Warning: judge-story failed (%s); keeping the critic's best round` line, and the best round stands **[spec choice: an optional paid gate never discards a locally passing story]**.
2. Success: `min_score = min(scores)`. If `min_score >= JUDGE_MIN_SCORE` -> `judge.status = "ok"`, `applied = false`; done.
3. Else: a new round `j` (next round number) applies the judge's patches to the best state with RS20 (its `critic.json` has `route: null`, `reply` = the judgment's `{scores, verdict, patches}`); checks; then one more critic round `j+1` on state `j` exactly as one RS21 iteration (scores recorded on state `j`; its patches produce state `j+1`; a code-only round if the critic fails). The best round is re-selected over all states (RS22). `judge.applied = true`.

### RS25. Outputs

- On every exit after round 0 assembled: `<story_dir>/plan.json`, `<story_dir>/story_checks.json` (the best round's checks, `source: "robust"`), and `<story_dir>/story.md` = the best round's text, each written atomically. `story_rounds/` holds every round.
- `story_prompt.txt` is written by `bin/ltx-movie` before `run` is called, with the legacy prompt for the same arguments: `build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills, bool(seed), seconds=_clip_seconds(args), cast_block=args.cast_block, shots=args.shots)` **[spec choice: `bin/judge-story`'s default mode and the live A/B judge both engines against the identical stated format contract; the robust prompts are kept in `story_rounds/`]**.
- On exit 1 (RS8, RS23) nothing in `<story_dir>` except `story_rounds/` and `story_prompt.txt` is written; an existing `story.md` is left untouched.

### RS26. `story_checks.json`

Section 2.5. Written by `run` (best round) and by `recheck`. Also written per round as `<round dir>/story_checks.json` with `round` = that round and `stop_reason`/`best_round`/`judge` null.

### RS27. Exit codes and messages (Phase 1, robust engine)

| Code | When | stderr |
|---|---|---|
| 0 | the best round has 0 hard violations (and the review gate passed or was skipped) | -- |
| 1 | no usable plan (RS8), wall-clock cap in round 0 (RS23), or no panel produced any valid reply in round 0 | the RS8/RS23 message; for the last case `Error: the story model returned no valid panel in round 0; see <round_0 dir>` |
| 2 | the best round has hard violations; or a re-check fails (RS28) | see below |

Exit-2 message after `run`:

```
Error: story.md has %d hard violation(s) after the critic rounds (best round %d of %d):
  - <message>                                     (every hard violation)
story.md, plan.json and story_checks.json are saved in <story_dir>. Hand-edit story.md to fix the violations above and rerun: story.md already exists, so Phase 1 re-checks it instead of regenerating it (pass --force-story to regenerate).
```

`%d of %d` is the best round number and the highest round number.

When a `bin/qwen-agent` call gives no answer (timeout, no envelope, or an empty answer), `story_engine` prints on stdout `Warning: bin/qwen-agent gave no answer (<status>); the last lines of its stderr:` followed by up to 10 of its last non-empty stderr lines, each indented two spaces; nothing is printed when stderr is empty.

### RS28. Re-check of an existing `story.md`

When the robust engine is selected and `story.md` exists without `--force-story`, `_phase1_robust` prints `note: %s already exists; re-checking it instead of regenerating it (pass --force-story to regenerate)` and calls `story_engine.recheck(ctx)`:

- With `<story_dir>/plan.json` present and valid JSON with `schema == PLAN_SCHEMA`, `mode == ctx.mode` and `panels == N`: hard = `bin/ltx-movie`'s legacy structural violations for the mode (`_validate_story_md(story_md, N, no_stills)` for chained/no_stills; nothing extra for shots), plus N1, N2, N3 (whole field text), N4, N7, N8, N9, N10 (the writer text recovered by removing that panel's pasted plan sentences with the RS13 cleanup; `PLACEHOLDER_RE` and `COPIED_EXAMPLES` on it), N11, N15, plus (shots) S1-S12; plus L1-L7 when `ctx.auto_lora`; advisory = N12, N13 (recovered writer text), N14, (shots) W2, L4 advisory. P1-P12, N5 and N6 are not re-run **[spec choice: they validate generation; a hand-edited story.md is not re-derived from the plan, and requiring plan.json edits for a setting-sentence fix would be hostile]**. `_validate_story_md` is passed in by the caller as a function argument (`recheck(ctx, legacy_validate)`).
- With `plan.json` absent, unreadable, or for another mode/panel count: exactly today's validators -- chained/no_stills `_validate_story_md` (any violation -> the legacy message of `:1076-1082` and **exit 1**, as today), shots `character_lib.shots_violations`/`shots_advisories` (any -> the legacy message of `:1196-1201`, exit 2) **[spec choice: a story.md written before this feature must not start failing on new rules]**.
- `plan_free_report(story_md, mode, panels, members, legacy_validate)` (public; used by 7.2 and RST45) returns the hard list a re-check computes **without** a plan: `legacy_validate(story_md, panels, mode == "no_stills")` for chained/no_stills, N1 (field text), N7, N8 (not shots), N9, N10 (field text), N11, N15 (with `members`), and (shots) `character_lib.shots_violations`. It prints nothing and writes nothing. N2, N3 and N4 are left out because they need the plan's referring phrases (a phrase such as "the woman in grey" would otherwise trip N3).
- When plan.json exists but is malformed (the fallback below), the re-check first prints `note: <story_dir>/plan.json is malformed; re-checking story.md without it` on stdout.
- When a failing re-check with plan.json has an L violation, it ends with `The L violations come from plan.json's catalog LoRA picks, not from story.md: restore or re-add the LoRA files (bin/lora-catalog verify), rerun with --no-auto-lora, or pass --force-story to regenerate.` on stderr.
- With plan.json: any hard violation -> `Error: story.md fails the story checks:` + `  - <message>` lines + `Hand-edit <story.md> to fix the violations above and rerun, or pass --force-story to regenerate it.` -> exit 2. `story_checks.json` is written with `source: "recheck"` in both outcomes.

### RS29. Review gate

After `run` or `recheck` returns 0, `_phase1_robust` does exactly what `phase1_story` does after validation (`:1084-1109`): when not `--no-review`, print `=== story.md ===` and the file; print `Warning: <advisory>` for every advisory the engine returned (under `--no-review` too); print the cast-phrase warnings of `:1098-1106`; when not `--no-review`, `input("Review story.md above. Enter to continue, Ctrl-C to abort: ")`. `_chain_image_warnings` is not called (the engine never writes Image: on later panels).

### RS30. Dry run (robust engine)

`_print_dry_run_plan` keeps every line it prints today, except that when `getattr(args, "story_engine", "legacy") == "robust"` the Phase 1 block (`:1696-1714`) is replaced by:

```
--- Phase 1: story ---
Would skip if <story.md> already exists and re-check it instead (pass --force-story to regenerate).
Story engine: a JSON plan, one call per panel, deterministic checks and up to 3 critic rounds (analyst via the local qwen-agentd, else a local one-shot); --story-legacy for the single-prompt path.
Catalog LoRAs: <C> compatible entr<y|ies> in <catalog path>          | Catalog LoRAs: none compatible in <catalog path> | Catalog LoRAs: off (--no-auto-lora)
Judge gate: bin/judge-story --patches after the critic rounds.      (only with --judge)
Command (subprocess timeout <plan_timeout(N)>s): <shlex.join(plan call argv)>

Rendered plan prompt:
<plan prompt>

```

- The plan argv is `agent_cmd(ctx, prompt, max_tokens=plan_max_tokens(N), image=ctx.seed_agent_image)`; with `--seed-image` its `--image` is `_story_paths(...)["seed_downscaled"]`.
- The block contains none of the substrings `{`, `}`, `ltx-mlx-render`, `ltx-story-images`, `ltx-story-manifest`, `story-server`, `--resume`, `--chain`, `--shots`, `--no-images` (the existing dry-run tests count or forbid them in the whole output).
- The dry run writes nothing, loads no `character_lib.py` beyond what `_resolve_casting` loaded, and never loads `fleet_lib.py`.
- Phases 2 and 3 of the dry run add the catalog flags of LC13/LC14 only when `plan.json` exists for the story, `--force-story` is not given, and the plan has picks; the manifest command then shows `--catalog-loras <story_dir>/catalog_loras.json` (nothing is written).

### RS31. Legacy path

- `--story-legacy` (or `--story-prompt-override`): `phase1_story` runs today's code; the prompt (`build_story_prompt` / override), the `bin/qwen-agent` argv (`:1052-1064`), `story_prompt.txt`, the validators, the shots rewrite loop, the messages and the exit codes are unchanged byte for byte; `_print_dry_run_plan` prints today's Phase 1 block; Phases 2-3 add no catalog flag; no catalog is read.
- One added side effect, inside the `else:` branch where Phase 1 actually runs, before `story_prompt.txt` is written: if `<story_dir>/plan.json` exists, it is renamed to `_unused_path(<story_dir>/plan.stale-<UTC stamp>-<pid>.json)` and `note: moved the robust engine's plan.json aside to <path>; this story.md is written by --story-legacy` is printed **[spec choice: a later default run must not re-check or render with a plan that no longer matches story.md]**.

### RS32. `bin/judge-story --patches`

- New flag: `parser.add_argument("--patches", action="store_true", default=False, help="review a story written by bin/ltx-movie's default engine: read the sibling plan.json and story_checks.json and return per-panel patches (judgment.patches.json) instead of a revised prompt")`. `--patches` with `--target-panels` -> `parser.error("--patches cannot be combined with --target-panels")`.
- Without `--patches` every behaviour, output and file is unchanged.
- With `--patches`: `story_md` as today; `plan.json` must exist next to it (`Error: plan.json not found: %s. --patches needs a story written by bin/ltx-movie's default story engine.` -> 2); `story_prompt.txt` is not required. Violations come from the sibling `story_checks.json` (`hard` then `advisory` messages); absent or unreadable -> none. `story_engine.py` is loaded by path from `WS` inside `main`; the user message is `story_engine.build_critic_prompt(plan, story_md_text, (hard, advisory), catalog_lines=None, for_judge=True)` (no `lora` field for the judge **[spec choice: LoRA choice stays local, with the catalog]**).
- System prompt `PATCH_SYSTEM_PROMPT_TEMPLATE` with the same `@@GOAL@@` mechanism (`DEFAULT_GOAL` when `--goal` is omitted):
  `You are an expert story editor reviewing a story written for an AI image-and-video generation pipeline. The target output goal is @@GOAL@@.\n\nThe user message holds the movie's plan, its story.md and the problems the pipeline's own checks found. Score the story and propose at most 8 exact patches, following the instructions in the user message.\n\nYou must deliver your review by calling the submit_review tool exactly once. Do not put the review in a plain text reply; a response without a submit_review call is a failure.`
- Tool `submit_review`, description `Submit your review of the story: three 1-10 scores, a verdict, and at most 8 patches. You must call this exactly once.`, schema `SUBMIT_REVIEW_SCHEMA`: object with required `scores` (object, required integer 1-10 `continuity`, `story`, `renderability`), `verdict` (string enum `ok`, `revise`), `patches` (array, `maxItems` 8, items: object with required `target` (enum `plan`, `panel`), `index` (integer, minimum 0), `field` (enum of the nine fields), `reason` (string), `replacement` (no type constraint)).
- Same model, effort, `MAX_TOKENS`, `_create_message` parameters (tool name and schema substituted), one retry with `RETRY_REVIEW_MESSAGE` = `You did not call the submit_review tool. Call submit_review now with your scores, verdict and patches. Do not reply with plain text.`, the same raw-dump and error paths.
- Output `judgment.patches.json` next to story.md: keys in order `story_md_path`, `plan_path`, `model`, `effort`, `goal`, `timestamp`, `usage` (as today), `scores` (in the order continuity, story, renderability), `verdict`, `patches`. stdout: `Scores:` then `  %-14s  %d` per score, a blank line, `Verdict: %s`, `Patches: %d`. Exit codes as today.

### RS33. `bin/iterate-story` deprecated wrapper

- `DEPRECATION_NOTICE = "iterate-story is deprecated: bin/ltx-movie's default story engine now checks, critiques and patches the story itself (add --judge for the Claude gate)."`
- After argument validation (`main`, after `--max-rounds` is checked), if `<story_dir>/plan.json` exists and parses with `schema == "ltx-movie.plan.v1"`: print the notice to stderr; print `iterate-story: --threshold and --max-rounds are ignored on the default engine; its thresholds are fixed` to stderr; build `[sys.executable, os.path.join(WS, "bin", "ltx-movie"), plan["narrative"], "--story-id", story_id, "--panels", str(plan["panels"])] + (["--shots"] if mode == "shots" else ["--no-stills"] if mode == "no_stills" else []) + ["--character", c["cast_name"]] per cast entry with a non-null cast_name, in plan order + (["--seed-image", plan["seed_image"]] if set) + ["--lora", "%s:%s" % (p["path"], repr(float(p["strength"])))] per pin + (["--goal", args.goal or plan["goal"]] if either) + ["--force-story", "--no-review", "--story-only", "--judge"] + the existing `--story-model` / `--story-context-window` pass-through`; run it with `_run`; log it with `_log_run(story_dir, 1, "ltx-movie", cmd, result)`; write its captured output to stdout; return its exit code.
- Otherwise (no plan.json): today's loop unchanged, with the notice printed to stderr once, after the precondition checks pass (story.md, story_prompt.txt, panel count) and before round 1 **[spec choice: `tests/test_iterate_story.py` pins stdout exactly and `err.startswith("Error: ")` on precondition failures]**.

### RS34. Source-literal guards in `bin/ltx-movie`

New code in `bin/ltx-movie` adds **no** occurrence of: `["--model", args.story_model]`, `["--context-window", str(args.story_context_window)]`, `"--workspace", WS,`, `_render_flags(args)`, `os.path.join(WS, "bin", "ltx-mlx-render")`, `cmd += ["--image", args.seed_downscaled_path]`, `phase1_cmd += ["--image", paths["seed_downscaled"]]`, `\n        cmd += ["--seed-image", args.seed_image]` (newline plus eight spaces, as L29d anchors it), `phase2_cmd += ["--seed-image", args.seed_image]`, `"--glob"`, `"--engine"`, `sudo -S`; the body of `phase2_stills` gains no `no_stills` text. New code in `bin/ltx-story-images` adds no occurrence of `_compose_prompt(`, `"source": "generated"`, `"source": "seed"`, `_panel_seed(args.seed, i, grounded)`.

### RS35. `_phase1_robust(args)` in `bin/ltx-movie`

1. `paths = _story_paths(args.story_id)`; `engine = _story_engine()`; `ctx = _story_context(args)` (Section 2.1; `members = args.cast_members or []`).
2. If `story.md` exists and not `args.force_story`: `rc, advisories = engine.recheck(ctx, _validate_story_md)`.
3. Else: print `=== Phase 1: story ===`; write `story_prompt.txt` (RS25); `rc, advisories = engine.run(ctx, no_stills_rules=_no_stills_rules())` where `_no_stills_rules()` slices `STORY_PROMPT_TEMPLATE_NO_STILLS` as RS12 states.
4. `rc != 0` -> return `rc`. Else RS29, return 0.

`--character` with a robust new story keeps `_resolve_casting`'s checks (`--cast` needs an existing story; `--story-prompt-override` cannot combine), and `args.cast_block` is still computed (used only for `story_prompt.txt`).

### RS36. Docstrings

`bin/ltx-movie`'s module docstring gains one paragraph after the "Shots mode" paragraph: `Story engine (docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md): by default Phase 1 asks the story model for a JSON plan and then one panel at a time, assembles story.md itself, runs deterministic checks and up to three local critic rounds (the fleet analyst skill), and exits 2 with story.md, plan.json and story_checks.json saved when hard violations remain; a rerun re-checks the existing story.md. --judge adds bin/judge-story --patches as a final gate; --story-legacy restores the single-prompt path. The plan may pick catalog LoRAs (bin/lora-catalog), which Phases 2 and 3 apply per panel; --no-auto-lora turns that off.` The sentence "character_lib.py is loaded by path only when casting or --shots is used, so an uncast run without --shots never reads it" (`:83-84`) gains: `-- on the --story-legacy path and in every dry run; the default story engine loads it for its checks.`

### RS37. Library characters are declared only (never auto-cast)

- Using a library character is a declared action: a character from `character_lib.library_dir()` appears in a story only when the user passes `--character NAME` (or `--cast PHRASE=NAME` on an existing story). No stage -- planner, panel writer, critic, judge patch, LoRA selection -- may introduce one. The catalog never offers characters to the planner (LC5), no patch field can add one (RS20), and P13/N15 reject any that slips in.
- `library_identities(ws)` (in `story_engine.py`, stdlib, **without** loading `character_lib.py`, so dry runs stay character_lib-free): the library root is `$CHARACTER_LIBRARY_DIR` else `<ws>/generated/characters`; for every subdirectory whose `character.json` parses as an object with string `name`, `trigger` and `referring_phrase`, one `(name, trigger, referring_phrase)` tuple, sorted by name, regardless of status. Unreadable files are skipped silently. **Undeclared** = every tuple whose name is not the name of a member of `ctx.members`.
- Masks hide a reference only when it lies wholly inside an occurrence of a declared member's name, trigger, phrase or descriptor, or of an invented cast phrase that does not itself name an undeclared character.
- Reference kinds, tested in this order per character and per text, first hit reported: `referring phrase` (`character_lib.phrase_occurs(text, phrase)`, or exact case-insensitive equality for a cast entry's phrase), `trigger`, `name` (each `re.compile(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])", re.IGNORECASE)`). `<text>` is the matched substring as it appears.
- **P13** (plan) scans, in this order, with these `<where>` labels: each cast entry without `cast_name` -- `cN's phrase`, `cN's descriptor`; `the title`; `the logline`; each location -- `lN's setting`; each prop -- `pN's name`; each beat -- `beat K's action`. **N15** (panels) scans each panel's title and assembled fields; identity sentences of declared members are never flagged because declared members are excluded. Both are hard; P13 triggers the plan repair call (RS8) and both are listed to the critic like every other hard violation.
- Plan prompt fragment (prepended inside `@@CAST_FIXED@@`): when the undeclared list is non-empty, ` Never use these names or referring phrases, which belong to characters who are not in this movie: ` + `", ".join('%s ("%s")' % (name, phrase) for each undeclared tuple)` + `.`; else `""`. Panel prompts carry the same sentence on its own line after `@@CAST_PHRASES@@`'s line, prefixed `Characters who are not in this movie, never to be named: ` and listing the same items, when non-empty. The sentences contain no braces.

---

## 4. LoRA catalog requirements (normative)

### LC1. `lora_catalog.py`

Stdlib only; top-level imports exactly `datetime`, `fcntl`, `hashlib`, `importlib.machinery`, `json`, `os`, `re`, `struct`, `uuid`. Public names:

| Name | Contract |
|---|---|
| `SCHEMA_VERSION = 1`, `CATALOG_ENV = "LORA_CATALOG_DIR"`, `STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"`, `KINDS = ("style", "motion", "physics")`, `TARGETS = ("video", "stills")`, `ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")`, `TRIGGER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}")`, `MAX_TRIGGERS = 4`, `TEXT_MAX = 300`, `ENTRY_KEYS` (the 16 keys of Section 2.7) | constants |
| `class CatalogError(Exception)` | message printed after `Error: ` |
| `catalog_dir(ws)`, `catalog_path(ws)` | `$LORA_CATALOG_DIR` else `<ws>/generated/loras`; `+ "/catalog.json"` |
| `load_catalog(path)` | absent file -> `{"schema_version": 1, "entries": []}`; else parse and `validate_catalog`; raises `CatalogError("<path>: <reason>")` |
| `validate_catalog(data)`, `validate_entry(entry)` | LC3; raise `CatalogError` |
| `save_catalog(path, data)` | validate, sort entries by id, atomic write (Section 2) |
| `catalog_lock(path)` | context manager: `fcntl.flock(LOCK_EX)` on `<dir>/.lock` (created mode 0600) |
| `file_sha256(path)` | streaming, 1 MiB blocks |
| `read_safetensors_header(path)` | LC4 |
| `rank_alpha(header)` | LC4 -> `(rank or None, alpha or None)` |
| `has_lora_pairs(header)` | LC4 |
| `fold_characters(ws)` | LC5 |
| `character_triggers(ws)` | `{trigger.lower(): name}` from `character_lib.registered_triggers()` (loaded by path) |
| `compatible(entry, model)` | LC6 |
| `prefix_triggers(prompt, triggers)` | LC18 |
| `verify_entry(entry, all_entries, char_triggers)` | LC10 -> list of problem strings |

### LC2. Path

Section 2.7. `bin/lora-catalog` creates the directory (`os.makedirs(..., exist_ok=True)`) only on `add`.

### LC3. Schema and validation

- Top level: exactly `{"schema_version", "entries"}`; `schema_version == 1`; `entries` a list; ids unique; triggers unique across entries (case-insensitive).
- Entry: exactly `ENTRY_KEYS`; `id` matches `ID_RE` (no `:`, so folded `char:` ids never collide); `kind` in `KINDS`; `path` absolute string; `sha256` 64 lowercase hex; `bytes` int >= 1; `base_models` non-empty list of non-empty strings; `target` in `TARGETS`; `triggers` list of 0..4 strings each matching `TRIGGER_RE`; `rank` int >= 1; `alpha` int == `rank` (the message names the fuser: `alpha must equal rank (R); ltx-2-mlx fuses B@A*strength with no alpha/rank scaling (fuse_loras.py), so this LoRA would render at the wrong strength`); `default_strength` and both `strength_range` values are numbers (bool excluded), `0 < lo <= default_strength <= hi <= 2`; `description` and `use_when` strings of 1..300 characters; `avoid_when` string of 0..300; `added_at` matches `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z`. File existence is not checked here (LC10).

### LC4. Safetensors header

`read_safetensors_header(path)`: read 8 bytes, `struct.unpack("<Q")`; a length of 0 or above 100 MiB, a short read, or invalid JSON -> `CatalogError("<path>: not a safetensors file")`; return the parsed dict. `rank_alpha(header)`: rank = `shape[0]` of the tensor whose key is the lexicographically first key ending `.lora_A.weight`, else `int(header["__metadata__"]["ss_network_dim"])` when present; alpha = the first of `__metadata__["lora_alpha"]`, `["alpha"]`, `["ss_network_alpha"]` that parses as a number and equals an integer; else None. `has_lora_pairs(header)`: some key `X.lora_A.weight` has a matching `X.lora_B.weight`.

### LC5. Folded characters

`fold_characters(ws)` -> list of read-only pseudo-entries, one per `character_lib.list_names()` character whose `load_character` succeeds and whose `loras.video` is set: `{"id": "char:<name>", "kind": "character", "path": video.path, "sha256": video.sha256, "bytes": None, "base_models": [video.base_model], "target": "video", "triggers": [trigger], "rank": video.rank, "alpha": video.alpha, "default_strength": strength or 0.8, "strength_range": None, "description": descriptor, "use_when": "cast with bin/ltx-movie --character <name>", "avoid_when": ""}`. Never written to `catalog.json`. Never offered to the planner or the critic (RS7/RS17 show catalog entries only): characters are cast only with `--character` (RS37).

### LC6. Compatibility

`compatible(entry, model)` is True when `model` equals a `base_models` item exactly, or both are absolute paths with equal `os.path.realpath`. The planner's **compatible set** (`story_engine.compatible_entries(ctx)`): catalog entries with target `video` compatible with `ctx.video_model`, plus (modes chained and shots) entries with target `stills` compatible with `STILLS_BASE_MODEL`; minus entries whose `path` is not a readable file (one `Warning: catalog LoRA %s is skipped: %s is not a readable file` line each, printed by `run`, `recheck` and the dry run); minus entries with a trigger equal (case-insensitive) to a cast member's trigger (`Warning: catalog LoRA %s is skipped: its trigger %s is character %s's trigger`). Sorted by id.

### LC7. `bin/lora-catalog add`

```
bin/lora-catalog add PATH --id ID --kind {style,motion,physics} --target {video,stills}
                 --base-model M [--base-model M ...] [--trigger T ...]
                 --description TEXT --use-when TEXT [--avoid-when TEXT]
                 [--default-strength S] [--strength-range LO,HI] [--rank N] [--alpha N]
```

Defaults: `--default-strength 1.0`, `--strength-range 0.5,1.0` **[spec choice: a common style-LoRA operating range; the user overrides per entry]**, `--avoid-when ""`. Under `catalog_lock`: PATH must be a readable regular file; the header is read (LC4); for target `video`, `has_lora_pairs` must hold (`Error: %s has no lora_A/lora_B weight pairs; the ltx-2-mlx fuser would ignore it`); rank/alpha = the flags when given, else `rank_alpha`; a missing value -> `Error: cannot read the LoRA %s from the safetensors header; pass --%s` ; `id` not already present; `realpath(PATH)` not already cataloged under another id; not a character's video or stills LoRA path (realpath, via `fold_characters` and each character's `loras.stills.path`); every trigger unique against the catalog and `character_triggers`; then compute `sha256` and `bytes`, set `path = os.path.abspath(PATH)`, `added_at` = now (UTC), `validate_entry`, `save_catalog`. stdout on success: `added %s (%s, %s, rank %d, sha256 %s...) to %s` % (id, kind, target, rank, sha256[:12], catalog path). Every failure: one `Error: ...` line on stderr, exit 2, catalog unchanged.

### LC8. `bin/lora-catalog list [--model M] [--json]`

Rows: every catalog entry (sorted by id) then every folded character (sorted by id); `--model M` keeps only entries/characters compatible with M (for stills entries compatibility is against M as given). Table format `"%-24s %-9s %-7s %-14s %-24s %s"` with header `ID KIND TARGET STRENGTH TRIGGERS BASE_MODELS`; STRENGTH is `d (lo-hi)` with `repr(float())` values, or `d` for characters; TRIGGERS and BASE_MODELS joined by `,`. No rows: `no LoRAs in <catalog path>` (characters, if any, still listed below it). `--json`: `json.dumps({"catalog": <path>, "entries": [...], "characters": [...]}, indent=2, ensure_ascii=False)`. A `CatalogError` -> exit 2. Exit 0 otherwise.

### LC9. `bin/lora-catalog remove ID`

Under `catalog_lock`: remove the entry; `removed %s from %s`; the LoRA file is not touched. Unknown id or a `char:` id -> `Error: no catalog entry %s` (or `Error: %s is a library character; manage it with bin/character`), exit 2.

### LC10. `bin/lora-catalog verify [ID ...]`

For each selected entry (all when no ID; an unknown ID -> exit 2): problems from `verify_entry`, in order: path missing or unreadable; `bytes` differs from `os.path.getsize`; `sha256` differs from `file_sha256` (only computed when the size matched); header unreadable; `alpha != rank` in the record, or the header's readable rank/alpha differs from the record; video target without lora pairs; a trigger shared with another entry or a character (`trigger %s is also character %s's trigger`). Then, for every folded character, a trigger equal to a catalog trigger is reported as `FAIL char:<name>: trigger %s is also catalog entry %s's trigger`. stdout: `OK <id>` or `FAIL <id>: <problem>` (one line per problem); last line `verified N entr<y|ies>: K problem(s)`. Exit 0 with no problem, 1 with any **[spec choice: 1 = verification failure, 2 = usage error, matching the repo's 0/1/2 convention]**.

### LC11. Locking and atomicity

`add` and `remove` hold `catalog_lock` for their whole read-modify-write; `list` and `verify` read without the lock. `save_catalog` writes `<path>.<uuid4 hex>.tmp` (mode default) then `os.replace`.

### LC12. Planner inputs: pins and limits

- Pins (`_story_context`): from `args.global_video_loras` (merged route: `[(abs path, strength)]`) or, on the legacy route, `[(os.path.abspath(args.lora_path), 1.0)]` when `args.lora_path`; each becomes `{"path", "strength", "catalog_id", "kind"}` where `catalog_id`/`kind` come from the catalog entry with target `video` whose path has the same realpath (else null). Pins stay on the global `--lora` route to the renderer (`_render_flags` unchanged); they are recorded in `plan.json` and counted by L2-L6 **[spec choice: the render argv for a pinned LoRA is unchanged and no LoRA can be applied twice]**.
- Limits (Section RS11): at most one style LoRA for the whole movie; at most one motion/physics LoRA per panel; at most `LORA_PANEL_LIMIT` = 4 video LoRAs per panel including pins and characters; strengths inside the entry's range; never reduced automatically.

### LC13. Phase 3 resolution (`bin/ltx-movie`)

`_catalog_panel_loras(args)` returns None unless `args.story_engine == "robust"`, `not args.no_auto_lora`, and `<story_dir>/plan.json` is a valid plan for this mode and panel count with any `global` or `per_beat` pick. Otherwise it returns N lists: for panel K, `[motion/physics picks from global then per_beat[str(K)]] + [the style pick from global]`, each `{"id", "kind", "path", "sha256", "strength", "triggers"}` from the catalog entry and the pick's strength. A pick whose id is no longer in `args.story_catalog` -> `Error: plan.json picks catalog LoRA %s, which is no longer in the catalog; re-add it with bin/lora-catalog add, or rerun with --no-auto-lora` -> Phase 3 returns 2. A file whose size differs from `bytes` -> `Error: catalog LoRA %s changed since it was cataloged (%s); run bin/lora-catalog verify` -> 2. When the result is not None, `phase3_manifest` writes `<story_dir>/catalog_loras.json` (Section 2.8, atomic) and appends `["--catalog-loras", <that path>]` to `cmd_manifest` after `_cast_flags(args)`. The dry run prints the flag without writing (RS30).

### LC14. Phase 2 stills pick (`bin/ltx-movie`)

`_catalog_stills_flags(args)` (module level, not inside `phase2_stills`) returns `[]` unless the LC13 preconditions hold and the plan's `stills` has a pick; then `["--lora", "%s:%s" % (path, repr(float(strength)))] + ["--lora-trigger", t] per trigger`. `phase2_stills` and the dry run's Phase 2 command append it immediately before `_cast_flags(args)` (so it follows every user `--stills-lora`).

### LC15. `bin/ltx-story-manifest --catalog-loras PATH`

- Flag: `parser.add_argument("--catalog-loras", dest="catalog_loras", default=None, metavar="PATH", help="per-panel catalog LoRAs (bin/ltx-movie's catalog_loras.json): each panel gets a catalog_loras list and its triggers are prefixed to its motion_prompt")`. Without `--chain`, `--shots` or `--no-images` -> `parser.error("--catalog-loras requires --chain, --shots or --no-images")`.
- Validation (exit 2 with `Error: --catalog-loras %s: <reason>`): JSON object with `schema == "ltx-movie.catalog-loras.v1"`; `panels` a list of exactly n_panels lists; each entry has exactly the six keys; `id` matches `[a-z][a-z0-9-]{1,31}`; `kind` in `style`/`motion`/`physics`; `path` absolute and a readable file; `sha256` 64 lowercase hex; `strength` number (bool excluded) in `(0, 2]`; `triggers` list of strings; no id twice in a panel; at most one style and one motion/physics entry per panel.
- After the `--cast` block (`:628-645`): for each panel, `panel["catalog_loras"] = [dict(entry) for entry in lists[i]]` and, when the list has any trigger, `panel["motion_prompt"] = lora_catalog.prefix_triggers(panel["motion_prompt"], [t for e in list for t in e["triggers"]])` (`lora_catalog.py` loaded by path inside `main`). `panel_text` is left as authored. Panels with an empty list get `"catalog_loras": []`. `schema_version` is unchanged (the key is optional).
- After the `cast:` lines: one `catalog: panel %d: %s` line per panel with entries, listing `id@strength` with `repr(float())`.

### LC16. `bin/ltx-story-images --lora-trigger WORD`

Repeatable (`action="append"`, `dest="lora_trigger"`, default None). After the `lora_sets` check (`:336-341`), when given: for every selected panel that is not the seed panel, `prompt, loras = plans.get(i, (compose(panels[i - 1]["image"], style), []))`; `plans[i] = (lora_catalog.prefix_triggers(prompt, args.lora_trigger), loras)`. `lora_catalog.py` is loaded by path inside `main`. Each `images.json` entry for a generated panel gains `"lora_triggers": [...]` when the flag is given. RS34's literal guards apply.

### LC17. `bin/ltx-mlx-render`

- `load_manifest`: an optional per-panel `catalog_loras` (any schema version) must be a list of dicts with exactly the six keys and LC15's per-entry rules (`path` readable); violations raise `ValueError("panel %d: catalog_loras ...")` (exit 2 through `main`).
- `main`, after the existing global/character checks (`:1073-1102`): a catalog entry whose path's realpath equals a `--lora` global's -> `Error: catalog LoRA %s (panel %d) is also passed with --lora; pass it once` (2); equals one of that panel's character `video_lora` -> `Error: catalog LoRA %s (panel %d) is also character %s's video LoRA` (2); then for each distinct catalog path, `lora_sha256(path) != entry["sha256"]` -> `Error: panel %d: catalog LoRA %s does not match its cataloged sha256; the file changed since bin/lora-catalog add (run bin/lora-catalog verify)` (2). These run before the `--dry-run` short-circuit.
- `build_units`: `loras = catalog motion/physics entries (manifest order); then global entries; then catalog style entries; then character entries`. Catalog entries are stably partitioned by kind (motion/physics before style, original order within a kind), so a hand-edited style-first manifest still renders motion first. A catalog unit entry is `{"kind": "catalog", "name": id, "path": path, "strength": float(strength), "catalog_id": id}`. **[amended 2026-10-17 at implementation: the user's rule is that the motion/physics adapter is always listed first; runs without catalog entries are byte-identical to before; the sum in `fuse_loras` keeps pixels unchanged]**
- `build_clip_provenance`: a catalog entry is recorded as `{"kind": "catalog", "path", "sha256": lora_sha256(path), "strength", "catalog_id": id}`; global and character entries unchanged.
- `print_dry_run` needs no change (it prints `l["name"] or "global"`, which is the id).

### LC18. `prefix_triggers(prompt, triggers)`

`missing` = the triggers, in order, de-duplicated case-insensitively, that do not match `re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", re.IGNORECASE)` in `prompt`. Return `prompt` when `missing` is empty, else `", ".join(missing) + ". " + prompt` **[spec choice: catalog triggers have no anchor phrase, so they lead the prompt; already-present triggers are not repeated, like `cast_text`]**.

### LC19. Deploy package

`scripts/deploy/build_pkg.py` `PIPELINE_FILES` becomes `(..., "character_lib.py", "story_engine.py", "lora_catalog.py", "bin/ltx-movie", ...)` (the two names inserted right after `"character_lib.py"`). `bin/lora-catalog` is not shipped **[spec choice: the M1 host renders shipped stories; catalog management is a Mac task; a missing catalog is the empty catalog]**. `fleet_lib.py` is not shipped; the critic then always uses the local one-shot (RS18 load failure path).

### LC20. Exit codes summary

`bin/lora-catalog`: 0 success, 1 `verify` found problems, 2 usage or validation error. `bin/ltx-story-manifest`, `bin/ltx-mlx-render`: catalog problems exit 2. `bin/ltx-movie`: catalog problems exit 2 (RS2, LC13).

---

## 5. Tests

### 5.1 Rules

- New tests are pytest functions with plain `assert` (no `check()` helper). Every test that runs `bin/ltx-movie` code sets, via `monkeypatch.setenv` or the subprocess `env`: `HOME` = a temp dir, `CHARACTER_LIBRARY_DIR` = a temp dir, `LORA_CATALOG_DIR` = a temp dir, `QWEN_AGENT_DAEMON_URL` = `http://127.0.0.1:<closed port>` (from `fleet_testutil.free_port()`), `STORY_PIPELINE_LOGGED=1`. Tests needing `--judge` set `ANTHROPIC_API_KEY=test-not-a-key` and use the fake `bin/judge-story`.
- No test starts `ltx-2-mlx`, `z_image_skill`, a real model server, a real daemon, or the Anthropic API. Render tests use `--dry-run` or monkeypatched `SKILL.generate_video`, with LoRA files of a few bytes.
- The temp workspace (`story_engine_testutil.make_ws(tmp_path, fake_agent=True, fake_judge=False)`) creates `<tmp>/ws/` with symlinks to the real `character_lib.py`, `story_engine.py`, `lora_catalog.py`, `fleet_lib.py`, `pipeline_log.py`, `ltx_image_fit.py`, `ltx2_mlx_video_skill.py`, and a real `bin/` directory holding symlinks to every real `bin/*` file except `qwen-agent` (and `judge-story` when `fake_judge`), which are the fake executables; `generated/stories/` is created. In-process tests then `monkeypatch.setattr(ltx_movie, "WS", str(ws))`.

### 5.2 Helpers (`tests/story_engine_testutil.py`)

- **Fake agent** (`bin/qwen-agent` in the temp ws; Python, executable): reads `$FAKE_AGENT_SCRIPT` (JSON `{"plan": [...], "panel": {"<k>": [...], "*": [...]}, "critic": [...]}`), classifies the call by the prompt's first line (`You are planning` -> plan, `You are writing panel K of` -> panel K, `You are the critic` -> critic), pops the next reply for that stage (panel K: key `"<k>"` first, then `"*"`; an empty queue exits 9), appends `{"argv": sys.argv[1:], "stage", "panel", "env_preflight": os.environ.get("QWEN_AGENT_PREFLIGHT_DONE")}` to `$FAKE_AGENT_LOG` (JSON lines), and prints an envelope. A reply item is `{"answer": "<text>"}` (status ok, exit 0), `{"answer": "<text>", "status": "max_rounds"}` (exit 3), `{"status": "http_error"}` (answer null, exit 3), `{"no_envelope": true}` (prints `garbage`, exit 1) or `{"sleep": S}` (sleeps S seconds first).
- **Fake judge** (`bin/judge-story`): reads `$FAKE_JUDGE_REPLY` (JSON object or `{"exit": N}`), records argv to `$FAKE_JUDGE_LOG`, writes `judgment.patches.json` next to `--story-md` with the given `scores`/`verdict`/`patches`, exits 0 (or N).
- **Fake fleet**: `FakeFleet(view, outcomes)` with `LOCAL = "@local"`, `daemon_url_from_env`, `fetch_view`, `route_candidates` (the real algorithm over the given view), `delegate_once(url, skill, task, host_id)` returning the queued `(outcome, envelope, detail)` and recording calls; installed with `monkeypatch.setattr(story_engine, "_load_fleet", lambda ws: fake)`.
- Builders: `plan_json(mode, n, **overrides)` (a valid plan reply for n beats), `panel_json(mode, k, words=...)` (valid writer parts sized inside the targets), `critic_json(scores, verdict, patches)`, `make_catalog(dir, entries)`, `fake_safetensors(path, rank, alpha, pairs=True, metadata=None)` (a valid 8-byte-length header plus a few data bytes).

### 5.3 Story engine tests (`tests/test_story_engine.py`)

| ID | Covers | Pass condition |
|---|---|---|
| RST1 | RS1 | AST of `story_engine.py`: top-level imports equal the RS1 set; no top-level `SourceFileLoader` call; `py_compile` ok |
| RST2 | RS2 | parser: the four flags exist with their defaults; `_parse_goal` matches `bin/judge-story` `parse_goal` on 6 inputs (trailing dot, empty, newline, 301 chars, normal, spaces) |
| RST3 | RS2 | `_resolve_story_engine`: each of `--judge`/`--no-auto-lora`/`--goal` with `--story-legacy` and with `--story-prompt-override` -> 2 and the exact message; `--judge` without `ANTHROPIC_API_KEY` -> 2; an invalid catalog -> 2 with the message; default -> `story_engine == "robust"` |
| RST4 | 1.3, RS2 | `phase1_story(args)` on a namespace from `build_parser().parse_args` (no `main`) runs the legacy path (fake Popen records today's argv) |
| RST5 | RS5 | `agent_cmd` exact lists for: plain; `--story-model` + `--story-context-window`; image; `skill="analyst"`; never `--danger-auto-approve` |
| RST6 | RS5 | `run_agent` with the fake agent: ok envelope; `max_rounds` with answer -> answer returned; `http_error` -> None; garbage -> `no_envelope`; sleep beyond timeout -> `timeout`; stdin is DEVNULL; second call carries `QWEN_AGENT_PREFLIGHT_DONE=1`, first does not |
| RST7 | RS6 | `extract_json` on: bare object; fenced with `json` tag; prose around; array -> None; invalid -> None; None -> None |
| RST8 | RS7 | plan prompt for each mode x {uncast, cast kyra+ronin} x {catalog empty, catalog with one style + one motion + one stills, `--no-auto-lora`} x {seed, no seed (chained)}: contains no `{`/`}`; starts `You are planning a short narrated movie (story-id "`; ends with the no-tool sentence containing `do NOT run run_python or any other tool to check it`; the fixed cast lines list `c1`/`c2` with the library descriptors; stills note only in no_stills; seed paragraph starts `An image is attached to this message.`; token-free (`"@@" not in prompt`) |
| RST9 | RS7 | a narrative containing `@@PANELS@@` is inserted verbatim (not replaced) |
| RST10 | RS8 | plan call 1 invalid JSON, call 2 valid -> round 0 proceeds, `plan_reply_2.txt` exists, call 2's prompt has the `YOUR PREVIOUS REPLY WAS REJECTED` block; both invalid -> exit 1, exact message, no story.md, existing story.md untouched |
| RST11 | RS8, RS10 | call 2 still has 5 beats for `--panels 6` -> exit 1 listing the P1 message |
| RST12 | RS16 | every `COPIED_EXAMPLES` item is a substring of a legacy template constant (whitespace-normalized); `APPEARANCE_WORDS` contains none of short, light, ring, cap, fair |
| RST13 | RS9 | normalization: fixed cast forced and inserted when omitted; descriptor trailing dot dropped; setting dot added; `loras` absent -> empty; `--no-auto-lora` discards model picks; `pinned` from ctx; unknown keys dropped |
| RST14 | RS10 | one fixture per message variant of the RS10 table (P1-P12) producing exactly that message, and a valid plan producing none |
| RST15 | RS11 | one fixture per L-check message (L1 six variants, L2 two, L3, L4 hard and advisory, L5, L6, L7 three); a pinned style blocks a global style (L2); a pin outside range passes L5 |
| RST16 | RS12 | panel prompt per mode/panel: key lines and W1/W2 equal RS14's arithmetic for a fixture with a 20-word setting and two 30-word descriptors; chained k>=2 has `The previous panel's Motion:`; seed panel line only on chained panel 1; no_stills carries the four Rules lines sliced from `STORY_PROMPT_TEMPLATE_NO_STILLS`; fix block lists violations and the previous version |
| RST17 | RS13 | cleanup: leading label, quotes, newlines, pasted setting/identity/camera sentences removed from writer text; title fallback; invalid reply retried once; third call never made (budget) |
| RST18 | RS14 | assembled story.md for each mode is byte-equal to a golden string in the test; `_parse_prompts_md` reads back exactly N panels with the right fields; shots roster lines parse with `parse_character_roster` |
| RST19 | RS14 | the assembled shots story for a kyra+ronin fixture has zero S9 violations and zero S12 violations |
| RST20 | RS15 | one fixture per N-check producing exactly its message (N1-N14); N1 not reported on shots Motion; N8 not run in shots; N6 skips cast members in shots |
| RST21 | RS15 | shots S-rules appended unchanged: an S8 contact fixture yields the exact `character_lib` string |
| RST22 | RS17 | critic prompt: whitelist lines per mode (chained has `(only 1: ...)` on shot/camera/image); lora line present only with catalog lines; violations list with `[hard]`/`[advisory]`, cap of 40 with `... and N more`; `for_judge` swaps only the last paragraph |
| RST23 | RS18 | fake fleet: `[LOCAL]` -> local one-shot with `--skill=analyst`, no `delegate_once` call; peers `["a", "b"]` with a failing then ok -> route `fleet:b`; all peers fail -> local; `_load_fleet` returns None -> local; `fetch_view` raises -> local |
| RST24 | RS18 | the real `_load_fleet` on the temp ws with `QWEN_AGENT_DAEMON_URL` at a closed port returns a module whose `fetch_view` yields no view -> local route |
| RST25 | RS18, risk RSC6 | `inspect.signature(fleet_lib.delegate_once)` starts with `daemon_url, skill, task, host_id`; `fleet_lib` has `LOCAL`, `route_candidates`, `fetch_view`, `daemon_url_from_env` |
| RST26 | RS19 | invalid critic reply then valid -> 2 calls, round applied; both invalid -> code-only round regenerates only panels with hard writer-text violations and budget left |
| RST27 | RS20 | whitelist: each disallowed (mode, field, index) rejected with `field not allowed in this mode`/range reason; 9 patches -> 9th rejected `over the 8-patch limit`; duplicate target rejected |
| RST28 | RS20 | `location.setting` patch re-pastes the new sentence in every panel at that location and the old one appears nowhere; invalid setting rejected |
| RST29 | RS20 | `beat.action` regenerates exactly that panel (one panel call); a panel patch to the same panel in the same round is rejected; over budget -> recorded skip |
| RST30 | RS20 | `beat.shot`/`beat.camera` change the pasted sentences without any agent call |
| RST31 | RS20 | `lora` patch: valid replacement applied; one adding an L3 violation rejected with `would break ...` and plan restored |
| RST32 | RS20 | panel count and every descriptor/phrase identical before and after any sequence of patches (property over 20 random patch lists from a seeded `random.Random(7)`) |
| RST33 | RS21 | stop `passed`: round-0 state 0 hard, critic ok 7/7/8 -> 1 critic call, best round 0 |
| RST34 | RS21 | stop `plateau`: state 1 not better than state 0 when scored by round 2 -> no round-2 patches applied |
| RST35 | RS21 | stop `max_rounds`: three improving rounds -> states 0..3, best = round 3 when hard counts fall |
| RST36 | RS22 | ranking: fewer hard wins; tie on hard -> higher min; tie -> higher total; full tie -> later round; unscored inherits ancestor scores |
| RST37 | RS23 | budgets: plan <= 2, panel <= 2 per panel, critic <= 3 rounds x 2 calls, counted from `run.json`; `_now` advanced past the cap during round 0 -> exit 1 message; after round 1 -> `time_cap` stop with outputs written |
| RST38 | RS24 | `--judge`: judge min 8 -> no extra round, `judge.status == "ok"`; judge min 5 with patches -> judge round + one critic round, `applied: true`; fake judge exit 1 -> warning, best stands, `status: "error"`; best with hard -> judge not called, `skipped` |
| RST39 | RS25, RS26, 2.6 | after a run: `plan.json`, `story.md`, `story_checks.json` valid per Section 2; `story_rounds/round_k/` files as listed; an earlier `story_rounds/` renamed, not deleted; `story_prompt.txt` equals `build_story_prompt(...)` for the same args |
| RST40 | RSK5, RS31 | `--story-legacy` real Phase 1 with fake Popen: the recorded argv equals today's list literal for 4 cases (plain, `--force-story --no-review`, `--story-model`/`--story-context-window`, `--seed-image`); the prompt equals `build_story_prompt` output; no catalog read (`LORA_CATALOG_DIR` points at an invalid catalog and the run still succeeds) |
| RST41 | RSK5 | `tests/test_casting_regression.py::b1_text()` (now with `--story-legacy`) equals the unchanged golden byte for byte |
| RST42 | RS31 | legacy Phase 1 moves an existing `plan.json` aside with the note; a legacy dry run does not |
| RST43 | RS27 | exit-2 message exact for a run whose best round keeps 2 hard violations; story.md, plan.json, story_checks.json saved |
| RST44 | RS28 | re-check with plan.json: a hand-fixed story.md passes (exit 0, review runs); one with an N7 violation -> exit 2 exact message; `story_checks.json` `source: "recheck"`; no agent call made |
| RST45 | RS28 | re-check without plan.json: chained structural violation -> exit 1 with the legacy message; shots S-violation -> exit 2 with the legacy message; a story.md that passes today's validators but breaks N1 still passes |
| RST46 | RS29 | review: story dump, advisories as `Warning:`, cast-phrase warning, `input` called once without `--no-review`, never with it |
| RST47 | RS30 | robust dry run (subprocess, three modes, with and without `--seed-image`, `--judge`, catalog states): exact Phase 1 block lines; first `Command (subprocess timeout` line is the plan argv with `--max-rounds 1`; zero output lines containing `{` or `}`; none of the RS30 forbidden substrings in the Phase 1 block; nothing written under the story dir; `character_lib`/`fleet_lib_for_story` not in `sys.modules` for an uncast in-process dry run |
| RST48 | RS32 | `judge-story --patches` with a stub `anthropic` module (the `tests/test_judge_story.py` pattern): request uses `submit_review` and the patch system prompt; `judgment.patches.json` keys/order; stdout lines; missing plan.json -> 2; `--patches --target-panels` -> parser error; default mode output unchanged (one T7-equivalent run compared to the existing expectation) |
| RST49 | RS33 | iterate-story with plan.json: notice on stderr, ignored-flags note, ltx-movie argv exact for a shots cast plan with seed, pin and goal; returns ltx-movie's code; without plan.json: stdout unchanged, notice on stderr after preconditions only |
| RST50 | RS34 | source scan: each RS34 literal's count in `bin/ltx-movie` and `bin/ltx-story-images` equals its count at the baseline commit (counts hard-coded in the test: 2, 2, 2, 4, 4, 1, 1, 1, 1, 0, 0, 0; `_compose_prompt(` 3, `"source": "generated"` 4, `"source": "seed"` 3, `_panel_seed(args.seed, i, grounded)` 2) |
| RST51 | e2e chained | fake agent, `--panels 3`, uncast, `--story-only --no-review --force-story` via `ltx_movie.main`: exit 0; story.md passes `_validate_story_md`; plan.json and story_checks.json written; agent log shows 1 plan, 3 panel, 1 critic call with `--skill=analyst` |
| RST52 | e2e no_stills | same for `--no-stills --panels 2`: Prompt fields 150-220 words; the critic returns a `location.setting` patch that is applied |
| RST53 | e2e shots | `--shots --panels 4 --character kyra --character ronin`: S1-S12 clean; plan cast c1/c2 fixed; one malformed panel reply retried; critic first reply malformed then valid |
| RST55 | RS37 P13 | a temp library with trained `ronin` (phrase "the ronin", trigger `roninmn`) and an uncast run: a plan whose c2 phrase is "the ronin" -> the exact P13 message with `c2's phrase`/`referring phrase`; a beat action naming `roninmn` -> `beat 3's action`/`trigger`; a logline naming `Ronin` -> `the logline`/`name`; P13 forces plan call 2; with `--character ronin` none of these fire |
| RST56 | RS37 N15 | assembled panels referring to the undeclared `ronin` in Motion (phrase), Narration (name) and Title (trigger) give the three exact N15 messages; a declared member's identity sentence gives none; re-check with plan.json reports N15 and exits 2; `plan_free_report` reports it |
| RST57 | RS37 prompts | plan and panel prompts list the undeclared characters in the reserved sentence (brace-free) and omit declared ones; an uncast in-process dry run with a non-empty library still has no `character_lib` in `sys.modules`; `library_identities` skips an unreadable `character.json` |
| RST58 | RS37 patches | a critic `panel motion` patch whose replacement names the undeclared phrase is applied, then the next state's checks report N15 (hard), and the best-round selection prefers the state without it |
| RST54 | e2e hard fail + resume | a scripted run ending with one N7 violation -> exit 2; hand-edit story.md (test rewrites the line); rerun same argv without `--force-story` -> re-check passes, exit 0, no agent call |
| RST60 | RSK1 | baseline recorded before the change (`python3 -m pytest tests/ -q -rA`, `python3 tests/test_ltx_movie_offline.py`); after: no lost pass, new tests pass |
| RST61 | RSK2 | `/usr/bin/python3 -m py_compile` and `python3 -m py_compile` exit 0 on every G1-G13 file and every edited test |
| RST62 | RSK3 | AST checks: `story_engine.py`/`lora_catalog.py` import sets (RS1, LC1); `bin/lora-catalog` imports only stdlib + `lora_catalog`; `bin/ltx-movie`, `bin/ltx-story-images`, `bin/ltx-mlx-render`, `bin/judge-story`, `bin/ltx-story-manifest` top-level import sets equal the baseline |
| RST63 | RSK4 | every new test module's fixtures set the Section 5.1 environment; a sentinel test asserts the real `generated/loras/catalog.json` mtime (or absence) is unchanged across the session |

### 5.4 Catalog tests (`tests/test_lora_catalog.py`)

| ID | Covers | Pass condition |
|---|---|---|
| LCT1 | LC1 | AST import set; `STILLS_BASE_MODEL` equals the `BASE_MODEL_ID` literal read from `z_image_skill.py` source text (no import) |
| LCT2 | LC2 | `catalog_path` honours `LORA_CATALOG_DIR`; default is `<ws>/generated/loras/catalog.json`; absent file loads as empty |
| LCT3 | LC3 | one invalid fixture per rule (16 keys, id regex, kind, target, path relative, sha, bytes, base_models empty, triggers count/regex/dup, rank, alpha != rank with the fuser message, strengths order and bounds, text lengths, added_at) -> `CatalogError` naming the field |
| LCT4 | LC4 | header parsing: rank from lora_A shape, alpha from `lora_alpha`/`alpha`/`ss_network_alpha`, kohya-only keys -> no pairs; truncated file -> error |
| LCT5 | LC5 | folding: a trained library character appears as `char:<name>` with its trigger and base model; an untrained one does not; nothing written |
| LCT6 | LC6 | compatibility: exact string; realpath equality for paths; stills entries only against `STILLS_BASE_MODEL`; unreadable file and character-trigger clash skipped with the warnings |
| LCT7 | LC7 | `add` happy path: entry fields, sha, bytes, abspath, `added_at`, stdout line, catalog sorted |
| LCT8 | LC7 | `add` errors, each exit 2 and catalog unchanged: duplicate id, same file twice, character LoRA path, trigger vs catalog, trigger vs character registry, alpha != rank from header, no lora pairs (video), missing alpha without `--alpha`, strength out of range |
| LCT9 | LC8 | `list` table, `--model` filter, `--json` shape, empty-catalog line with characters listed |
| LCT10 | LC9 | `remove` ok; unknown id; `char:` id; file untouched |
| LCT11 | LC10 | `verify`: clean -> exit 0 and `OK` lines; changed size, changed bytes same size (sha), missing file, header rank mismatch, character trigger clash -> exit 1 with the exact `FAIL` lines and summary |
| LCT12 | LC11 | two concurrent `add` processes (different ids) both land (lock serialises); no `.tmp` left |
| LCT13 | LC12 | pins: merged route and legacy route both recorded; a catalog pin carries id/kind; render flags unchanged with a pin |
| LCT14 | LC13 | Phase 3 with plan picks writes `catalog_loras.json` exactly (order motion then style) and appends `--catalog-loras`; removed id -> exit 2 message; size change -> exit 2; `--no-auto-lora` -> no flag; legacy engine -> no flag |
| LCT15 | LC14 | Phase 2 command gains `--lora path:0.8 --lora-trigger t` before `--cast`; absent otherwise |
| LCT16 | LC15 | manifest `--catalog-loras`: per-panel `catalog_loras` copied; trigger prefixed to `motion_prompt` once (already-present trigger not repeated); `panel_text` unchanged; validation errors exit 2; requires chain/shots/no-images |
| LCT17 | LC15 | a manifest built without `--catalog-loras` is byte-identical to today's (the B2 golden still matches) |
| LCT18 | LC16 | `ltx-story-images --dry-run --lora-trigger t`: printed prompts start `t. `; without the flag unchanged |
| LCT19 | LC17 | render `load_manifest` accepts valid `catalog_loras` and rejects each invalid entry |
| LCT20 | LC17 | `build_units` order: catalog motion/physics, global, catalog style, character; catalog dict exact |
| LCT20b | LC17 | a style-first manifest still renders motion/physics first: units and dry-run argv are zz-motion, global, aa-style, character (no sort by id) |
| LCT21 | LC17 | provenance: catalog entry has `catalog_id` and the file's sha; a manifest without catalog entries yields provenance equal to today's for the same unit (dict equality with a golden built from the old function's output, captured as a literal in the test) |
| LCT22 | LC17 | sha mismatch -> exit 2 message (dry run and real); duplicates with `--lora` and with a character -> exit 2 |
| LCT23 | LC17 | `--dry-run` with catalog entries prints `lora: <path> @ 0.7 (<id>)` and the first render command contains one `--lora PATH 0.7` per entry in unit order |
| LCT24 | LC17 | real render path with monkeypatched `SKILL.generate_video` recording kwargs: `loras` list order per panel; per-panel switching in a chained manifest (panel 2 has a motion LoRA, panel 3 none) |
| LCT25 | LC17 | `--resume`: a clip rendered with catalog entries is reusable on an identical rerun and not reusable after the strength changes |
| LCT26 | LC18 | `prefix_triggers`: none missing; two missing in order; case-insensitive presence; duplicate triggers de-duplicated |
| LCT27 | LC19 | `build_pkg.PIPELINE_FILES` contains both names right after `character_lib.py` |
| LCT28 | RS11 + LC12 | end to end in-process: a plan with global style + per-beat motion + a cast character on that beat -> L-clean; adding a second motion LoRA via patch -> rejected |
| LCT29 | LC20 | exit codes of each CLI path in one table-driven test |
| LCT30 | 1.4 | a chained manifest with per-panel catalog LoRAs passes `load_manifest` and `--on-panel-failure stop` dry run; units 1..3 carry their own LoRA lists |

### 5.5 Existing tests that change

| File | Test | Edit | Why |
|---|---|---|---|
| `tests/test_ltx_movie_offline.py` | `test_default_dry_run_plan_unchanged` (L18i-L18p) | append `"--story-legacy"` to the argv list | L18l asserts the legacy chained template text, which the default dry run no longer prints; the robust default dry run is covered by RST47 |
| `tests/test_ltx_movie_offline.py` | `test_no_stills_dry_run_plan` (L18a-L18m) | append `"--story-legacy"` to the argv list | L18g asserts the legacy no-stills template text |
| `tests/test_casting_regression.py` | `b1_text` | add `"--story-legacy"` after `"--no-review"` in the argv | the golden captures the legacy dry run; unchanged golden proves RSK5 (also used by `test_shots_mode.py::test_s52`) |
| `tests/test_casting_pipeline.py` | `test_p46_dry_run_with_character` | add `"--story-legacy"` to the `main([...])` argv | asserts the legacy Cast block inside the rendered legacy prompt |
| `tests/test_shots_mode.py` | `test_s50_dry_run_new_shots_story`, `test_s99_dry_run_shows_the_v2_prompt` | add `"--story-legacy"` to the subprocess argv | both assert legacy shots template / Cast block text in the dry run |
| `tests/test_deploy_pkg.py` | module constant `PIPELINE` | insert `"story_engine.py", "lora_catalog.py"` after `"character_lib.py"` | LC19 |

Unchanged and still passing, checked against the code: every test that calls `phase1_story`, `_phase1_shots_finish`, `phase2_stills`, `phase3_manifest` or `_phase_sequence` directly (1.3: no `story_engine` attribute -> legacy, and Phases 2/3 add catalog flags only on the robust engine); L1z9-L1z18, L2, L12, L17, L19, L24, L27, L29, L43-L45 (RS30 keeps the header, the `Command (subprocess timeout` line, the no-verify sentence, the seed preface's first sentence and `--image ... seed_downscaled.png`; RS34 keeps the source counts); `test_p49` and `test_s53` (RS30: no `character_lib` in an uncast dry run); `test_judge_story.py` (default mode unchanged); `test_iterate_story.py` (no plan.json in any fixture; stdout unchanged; notice after preconditions); `test_ltx_mlx_render.py` (unit keys and provenance unchanged without catalog entries); `test_ltx_story_images.py` (RS34 guards); every fleet test (no fleet file touched).

### 5.6 Regression

RST60-RST63 above. Additionally `git diff --stat <base>` lists only G1-G14 (and this spec, committed separately).

---

## 6. Requirement-to-test table

| Req | Tests | Live-only / reason |
|---|---|---|
| RS1 | RST1, RST62 | |
| RS2 | RST2, RST3 | |
| RS3 | RST18, RST51-RST53 | |
| RS4 | RST14, RST16, RST20, RST37 | |
| RS5 | RST5, RST6 | |
| RS6 | RST7 | |
| RS7 | RST8, RST9 | |
| RS8 | RST10, RST11 | |
| RS9 | RST13 | |
| RS10 | RST14 | |
| RS11 | RST15, LCT28 | |
| RS12 | RST16 | |
| RS13 | RST17, RST53 | |
| RS14 | RST18, RST19 | |
| RS15 | RST20, RST21 | |
| RS16 | RST12, RST20 | |
| RS17 | RST22 | |
| RS18 | RST23, RST24, RST25 | real peer delegation: RSR1 step 4 (optional) |
| RS19 | RST26, RST53 | |
| RS20 | RST27-RST32 | |
| RS21 | RST33-RST35 | |
| RS22 | RST36 | |
| RS23 | RST37 | |
| RS24 | RST38 | real Claude scores: RSR1 (the `--judge` subset) |
| RS25 | RST39 | |
| RS26 | RST39, RST44 | |
| RS27 | RST10, RST43 | |
| RS28 | RST44, RST45, RST54 | |
| RS29 | RST46 | |
| RS30 | RST47 | |
| RS31 | RST40, RST41, RST42 | |
| RS32 | RST48 | real API: live only (RSR1 `--judge` subset) |
| RS33 | RST49 | |
| RS34 | RST50 | |
| RS35 | RST44, RST51-RST54 | |
| RS36 | review | docstring text, checked in code review |
| RS37 | RST55, RST56, RST57, RST58 | |
| LC1 | LCT1 | |
| LC2 | LCT2 | |
| LC3 | LCT3 | |
| LC4 | LCT4 | real LoRA headers: RSR3 (`lora-catalog add` on 1-2 real files) |
| LC5 | LCT5 | |
| LC6 | LCT6 | |
| LC7 | LCT7, LCT8 | |
| LC8 | LCT9 | |
| LC9 | LCT10 | |
| LC10 | LCT11 | |
| LC11 | LCT12 | |
| LC12 | LCT13, LCT28 | |
| LC13 | LCT14 | |
| LC14 | LCT15 | |
| LC15 | LCT16, LCT17 | |
| LC16 | LCT18 | |
| LC17 | LCT19-LCT25 (incl. LCT20b), LCT30 | pixels with a real LoRA: RSR3 |
| LC18 | LCT26 | |
| LC19 | LCT27 | |
| LC20 | LCT29 | |

**Coverage.** Every RS and LC requirement maps to at least one automated test except RS36 (docstring text). Model behaviour (plan and panel quality, critic usefulness, JSON reliability of the 27B and of `--skill=analyst`), Claude's patch quality, real LoRA headers and their visual effect are covered only by Section 7.

---

## 7. Live quality protocol (main thread or user, on hardware; story server up; no concurrent GPU work)

### 7.1 Premises

| # | Story id (legacy / new) | Flags | Narrative |
|---|---|---|---|
| 1 | `drift_red_test-L` / `-R` | `--seed-image ~/Downloads/red.jpg --panels 6` | `a short story about a red object crossing a city` (the [panel-drift-fix] A4 run) |
| 2 | `sisters_sorrow-L` / `-R` | `--panels 30` no original 2026-08-27 narrative exists (user, 2026-10-17), so the protocol uses this premise: `Two estranged sisters meet at their mother's empty seaside house after the funeral, sort through her belongings in silence, argue over a music box, find their childhood letters inside it, and walk together to scatter her ashes from the pier at dusk.` |
| 3 | `ronin-rescue-L` / `-R` | `--shots --panels 14 --character kyra --character ronin --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8` | the fight scene, verbatim from [SHOTS] `:1516` ("Deep in a cedar forest, three robbers corner the Shogun's daughter, ... focus on realistic, physically grounded action.") |
| 4 | `lighthouse-L` / `-R` | `--no-stills --panels 8` | `A lighthouse keeper climbs the spiral stairs during a storm, relights the dead lamp, and watches a fishing boat turn safely toward the harbour.` |
| 5 | `subway-dancer-L` / `-R` | `--panels 10` | `A street dancer practises alone in an empty subway station at dawn, slips on a puddle, gets up, and finishes the routine as the first train arrives.` |
| 6 | `night-market-L` / `-R` | `--shots --panels 12` | `Two rival chefs race to finish the same dish in a cramped night-market stall; one burns her sauce, the other quietly shares hers, and they plate the dish together.` |
| 7 | `lantern-market-L` / `-R` | `--panels 8 --character kyra` | `The woman in grey walks through a lantern-lit market at night, buys a paper fan, notices she is being followed, and slips away down a narrow alley.` |
| 8 | `courier-L` / `-R` | `--shots --panels 16` | `A courier on a bicycle carries a sealed letter from a rainy harbour to a hilltop temple, loses it to the wind on a bridge, chases it down, and delivers it at sunset.` |

### 7.2 Procedure

For each premise: `python3 bin/ltx-movie "<narrative>" --story-id <id>-L <flags> --story-legacy --story-only --no-review --force-story`, then the same with `--story-id <id>-R` and without `--story-legacy`, same `--story-model`. Record per run: exit code, wall time, panel count of story.md (`grep -c '^## Panel'`), hard violation count, and `bin/judge-story --story-id <id>` (default mode; both engines have `story_prompt.txt`, RS25) scores. Hard violations for **both** engines are measured with `story_engine.plan_free_report(story_md, mode, panels, members, ltx_movie._validate_story_md)` (RS28) **[spec choice: one yardstick that does not need a plan, so legacy outputs are measurable]**. For a new run that exits 2, the saved story.md is measured as is. The user reads both story.md files per premise and records a preference (L / R / same). Optionally (step 4) repeat premise 5 with a peer serving `analyst` and this host's daemon not serving it, to exercise the fleet route.

### 7.3 Pass bar (Section 4 of the design)

- **RSR1:** the new engine has 0 hard violations on at least 7 of 8 premises.
- **RSR2:** no panel drift: every new story.md has exactly the requested panel count (8 of 8), and judge-story's minimum score for the new story is >= the legacy minimum on at least 6 of 8 premises.
- **RSR4:** user preference favors the new engine on more than 50% of premises, i.e. at least 5 of 8 (a premise rated "same" does not count toward the 5).

### 7.4 LoRA A/B (RSR3)

1. `bin/lora-catalog add` one real motion or physics LoRA and optionally one style LoRA for the LTX pack in use (rank == alpha), with honest `--use-when` text; `bin/lora-catalog verify` exits 0.
2. Premise 5 at `--panels 4`: run A with `--no-auto-lora`, run B default, both with the same `--image-seed`/render seed, rendered for real.
3. Pass: B's `plan.json` picks at least one catalog LoRA; B's `manifest.json` has non-empty `catalog_loras` on those panels; every B clip's `.provenance.json` lists `{"kind": "catalog", "catalog_id": ..., "sha256": ...}` matching the catalog; B renders without failure; rerunning B with the same command reuses every clip (`--resume`); the user rates B's style/motion fit against A per panel and records it.

---

## 8. Rollout

1. Implement after piece D is merged (scheduling decision). Record the RST60 baseline first.
2. Merge: the robust engine is the default for chained, no-stills and shots. The critic reaches the Mac's own `analyst` through a local one-shot; peers are used only when this host does not serve `analyst`.
3. The catalog starts empty (`generated/loras/catalog.json` absent) until the user runs `bin/lora-catalog add`; until then the planner sees no catalog and plans pick nothing.
4. Run Section 7; if RSR1/RSR2 fail, the user may keep `--story-legacy` in their commands while the prompts are tuned (no code switch is added).

---

## 9. Values chosen by the spec

1. 1.2: the engine lives in `story_engine.py` (source guards; judge-story shares the prompt builder).
2. 1.3: `story_engine` is resolved only in `main()`; direct `phase1_story` calls stay legacy.
3. RS2: `_parse_goal` is a copy of judge-story's `parse_goal` (no `anthropic` import).
4. RS2: `--judge` without `ANTHROPIC_API_KEY` fails before Phase 1.
5. RS2: `--judge`/`--no-auto-lora`/`--goal` with `--story-legacy` or `--story-prompt-override` are errors.
6. RS4: the eight camera values and their fixed sentences.
7. RS4: narration 3-30 words, advisory only (beyond "non-empty").
8. RS4: `MAX_CAST` 2 in shots, 4 elsewhere.
9. RS4: budgets' timeouts and token caps (plan `max(4096, 250N)` tokens / `max(600, 40N)` s; panel 1536 / 600 s; critic 4096 / 900 s; judge 900 s; wall clock `max(2400, 180N)` s).
10. RS5: every agent call uses `--max-rounds 1`, stdin closed, no `--danger-auto-approve`; preflight only on the first call.
11. RS7: the plan prompt has no braces (deploy gate X2) and no example sentences.
12. RS7: the shots touch-split rule lives in the plan prompt.
13. RS9: fixed cast entries are overwritten silently; `--no-auto-lora` discards model picks.
14. RS12: the no-stills `Rules:` lines are sliced from the legacy template at runtime.
15. RS13: title fallback = first five words of the beat action.
16. RS16: the appearance lexicon, regexes and the six copied-example guards (all sourced from the legacy templates).
17. RS20: per-mode patch whitelist incl. chained shot/camera/image patches on panel 1 only; judge never patches `lora`.
18. RS22: full ties go to the later round; unscored states inherit ancestor scores.
19. RS24: a failing judge only warns.
20. RS25: `story_prompt.txt` holds the legacy prompt in robust mode.
21. RS28: re-check skips P*, N5, N6; stories without plan.json keep today's validators and exit codes.
22. RS31: legacy Phase 1 moves a stale `plan.json` aside.
23. RS33: iterate-story's notice placement; `--threshold`/`--max-rounds` ignored on the wrapper path.
24. (user decision, not a spec choice) RS37: library characters are declared only; P13/N15 enforce it.
25. LC7: `--default-strength 1.0`, `--strength-range 0.5,1.0`.
26. LC10: `verify` exits 1 on problems.
27. LC12: pins stay on the global `--lora` route; pins skip the range check.
28. LC17: render order catalog motion/physics, global, catalog style, character.
29. LC18: triggers lead the prompt as `t1, t2. <prompt>`.
30. LC19: `bin/lora-catalog` is not shipped in the deploy package.
31. 7.2: `plan_free_report` is the common hard-violation yardstick for the A/B.

---

## 10. Risks and contradictions

**Contradictions and readings**

- **RSC1. "Spec to pin: chained mode may only support global picks if the renderer can't switch per panel."** It can (1.4): each panel is its own `ltx-2-mlx` process with its own LoRA list, and chained character LoRAs already switch per panel. Chained mode therefore gets per-panel motion/physics picks; style is global-only in every mode (L2), which was the approved per-panel order's only continuity-sensitive kind. Residual risk: a motion LoRA that starts at panel K changes the weights between two continuous clips; the A/B (7.4) and the "use_when" text are the controls.
- **RSC2. "Replaces per-mode validators."** On the robust engine, the shared checks replace `_validate_story_md` and the shots rewrite loop. Stories without `plan.json` (written before this feature or by `--story-legacy`) keep today's validators and exit codes on re-check (RS28), so no existing story.md starts failing. The legacy chained validator exits 1 where the robust engine exits 2; both are kept as they are.
- **RSC3. "cast per shot limit (hard, <=2 shots)"** is read as "at most 2 characters per beat in shots mode"; chained/no-stills get 4 (a spec choice for word budgets).
- **RSC4. "Characters folded in automatically; planner/critic see the catalog and pick per panel."** Library characters are folded into `lora-catalog list`, `verify` and the per-panel limits, but the planner never picks them: casting a character LoRA forces an identity and stays explicit (`--character`). The planner chooses which beats a declared character appears in, which decides that character's LoRA per panel. User decision 2026-10-17: never auto-cast; enforced by RS37 (P13, N15).
- **RSC5. "Critic: delegate via local daemon, else local one-shot."** The daemon's `POST /delegate` refuses its own host (`handle_delegate:1105-1111`), so the Mac's analyst is always the local one-shot; the daemon is used only to discover and reach peers. This matches `bin/qwen-agent`'s own routing.
- **RSC6. Concurrent piece D (tracing).** E edits none of `fleet_lib.py`, `bin/qwen-agentd`, `bin/qwen-agent` or fleet tests. E depends read-only on `fleet_lib`'s F59/F63/F64/F68 functions and `LOCAL`; D already added `trace=None` as a trailing parameter of `delegate_once`, and E passes four positional arguments only. RST25 fails loudly if D changes those signatures. With D in place, each robust `bin/qwen-agent` call posts its own trace (a `oneshot` or `analyst` turn) to the local daemon; [TRACE] TRK6 bounds that at 2 s per call, so a slow daemon can add up to ~2 s x (N + 8) to Phase 1. `bin/qwen-agent` line numbers cited here will drift while D lands; this spec names functions.
- **RSC7. Deploy gate X2** counts brace lines in the default dry run; the robust dry run is brace-free by construction (RS7) and RST47 checks it.
- **RSC8. The design's "planner sees compatible entries (id, kind, description, use_when, avoid_when)"**: the catalog line also shows target and strength range, which the planner needs to pick a valid strength.

**Risks (accepted)**

- **RSX1. JSON reliability.** A 27B model or the `analyst` skill (whose system prompt is fact-check oriented) may wrap or truncate JSON. Mitigations: tolerant extraction (RS6), one retry per stage, code-only rounds, and exit 1 only when no plan exists.
- **RSX2. Wall time.** N + 2 to about 3N + 8 local calls; a 30-panel story may take an hour, bounded by the wall-clock cap (`5400 s` at N = 30).
- **RSX3. Check false positives.** `APPEARANCE_WORDS` and `DIALOGUE_RE` can flag innocent uses ("tells the time", "a black horse" in a later chained Motion). They are hard checks by design; the critic and the hand-edit path resolve them. The lists are pinned constants, easy to adjust in a follow-up.
- **RSX4. Remote analyst variance.** A peer's analyst runs a different model; its scores are not comparable with the local critic's. Ranking uses hard counts first.
- **RSX5. Catalog trigger collisions created later.** `bin/character create` does not know catalog triggers; `verify` reports collisions and the planner skips a clashing entry for a cast member (LC6).
- **RSX6. `story_prompt.txt` semantics.** In robust mode it holds the legacy prompt (the format contract), not a prompt that was sent; `story_rounds/` holds the prompts that were sent.
- **RSX7. Legacy-path invariant relaxed.** "An uncast run without --shots never reads character_lib.py" now holds only on `--story-legacy` and in dry runs (RS36).

---

## 11. Answered questions (user, 2026-10-17)

- **A1.** No original `sisters_sorrow` narrative exists; premise 2 uses the narrative in 7.1.
- **A2.** User preference must favor the new engine on at least 5 of 8 premises (RSR4).
- **A3.** The planner must never auto-cast library characters; casting is declared only with `--character` (RS37, P13, N15).

No open questions remain.
