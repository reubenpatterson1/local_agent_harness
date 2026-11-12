# Shots Z-Image engine: one stills-engine picker in Compose, and Z-Image restored for seeded shots movies (panel 1 is the seed, every other panel a Z-Image still with its stills LoRAs)

Date: 2026-11-11

Status: design spec and implementation plan in one document. Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**The user's request:** "Let's restore Z-Image in the shots mode options in Compose." Clarified (binding): a per-run engine choice in Compose when the mode is shots and a seed is set: "Qwen edit of the seed" (today's behaviour, unchanged, the default) or "Z-Image". On the Z-Image path panel 1 is the seed (a letterboxed copy, as `bin/ltx-story-images --seed-image` writes it) and every other panel is a Z-Image still from its own `Image:` text, with the character, location and catalog stills LoRAs, exactly as shots mode without a seed.

**Scope change (binding, from the user):** the engine choice is not only shots+seed. (1) Text-to-video: offer a Z-Image still from the prompt as the first frame, then animate it. (2) With characters picked, offer Z-Image stills (with their stills LoRAs) as the panel engine in every mode. (3) ONE engine picker for every Compose mode, the shots+seed choice being one cell of it. Qwen stays the shots+seed default.

**The user's decisions on the scope (2026-11-11, binding; Section 9):** Q1: chained mode keeps its Z-Image panel-1 first frame exactly as today, no per-clip first-frame pipeline is built, and only shots mode gets the Qwen-or-Z-Image selection. Q2: Z-Image cannot edit, so every cell that edits a seed outside shots mode (chained with a seed, with or without characters) stays Qwen, and Z-Image is never offered there. **Deliverable 1 (Tasks 1-3) is therefore the whole job:** the one engine picker, which offers a choice only for shots with a seed (Qwen edit or Z-Image), shows the cells without a seed (shots, chained: Z-Image already) and text-to-video as read-only information **[spec choice]**, and never offers Z-Image where a seed is edited outside shots mode (SZ16); plus the shots+seed Z-Image engine with and without characters. F2 and F4 (Section 7) are optional follow-ups, not part of this work.

**Where.** Worktree `$S/sz-wt`, branch `shots-zimage`, off `e8d7f3a` (the merge of PR #20). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `$S/sz-wt/qwen-agent-workspace`. Every path is relative to `WS`; every line number cites `e8d7f3a`. At `e8d7f3a` the `test_mut26` BASELINE is `3d5e345f788b262cc51c6d961f0c1d9737e163fc` (`tests/test_movie_ui_builder.py:293`). Nobody but the user accesses macstudio.

**Builds on** **[SE]** `2026-11-05-compose-shots-seed-edit-design.md` (read in full; the binding earlier decision this spec amends), **[SI]** `2026-11-07-seeded-no-identity-sentence-design.md`, **[CR]** `2026-11-09-shots-multi-reference-stills-design.md`, **[CX]** `2026-11-10-seeded-shots-context-design.md`, **[QE]** `2026-11-03-qwen-edit-models-design.md`. Every requirement of those stays in force except where Section 8 names it as amended.

**IDs.** Requirements **ZE1-ZE14**, tests **SZ1-SZ16**, KPIs **SZK1-SZK6**, live checks **L1-L6** (live-check ids only). At `e8d7f3a`, `git grep -nE "\bZE[0-9]+\b|\bSZ[0-9]+\b|\bSZK[0-9]+\b"` finds nothing.

---

## 0. Scope

### 0.1 Every place that gates or branches on shots seed edit mode today (verified at `e8d7f3a`)

| # | Where | What it does |
|---|---|---|
| G1 | `bin/ltx-movie:89-102` (docstring "Shots mode" paragraph), `:113-116` ("Seed edit"), `:118-124` ("Seed context"), `:126-130` ("Cast references") | describe shots+seed as Qwen-only |
| G2 | `bin/ltx-movie:158-166` | `SHOTS_SEED_EDIT_SKILL`, `SHOTS_SEED_EDITS_SCHEMA`, `SHOTS_SEED_EDIT_PREFIX`, `SHOTS_SEED_LORA_NOTE` |
| G3 | `bin/ltx-movie:303-312, 314-333` | `SEED_IMAGE_PREFACE`/`POSTFACE`; `build_story_prompt` skips both for `shots` (`:325`, SE6), so every shots story keeps the shots template's `Image:` on every panel |
| G4 | `bin/ltx-movie:386-395, 396-403, 485-493` | help of `--seed-image`, `--seed-edit-model` ("With --shots it is required and as-is is refused"), `--shots` ("a Qwen edit of the seed (--seed-edit-model ID, required)") |
| G5 | `bin/ltx-movie:1101-1140` `_resolve_seed_edit` | as-is sets `args.seed_edit = None` (`:1116-1120`); `--seed-edit-lora` with as-is refused |
| G6 | `bin/ltx-movie:1186-1189` `_resolve_cast_refs` | `--cast-refs-model` refused with `--seed-image` |
| G7 | `bin/ltx-movie:1249-1261` `_resolve_seed_context` | needs `--seed-image` and a model (as-is refused) |
| G8 | `bin/ltx-movie:1490-1504` `_resolve_shots` | **the refusal:** no model or `as-is` → `Error: --shots with --seed-image needs --seed-edit-model ID: …`; `--stills-lora` refused; legacy engine refused |
| G9 | `bin/ltx-movie:1919-1949` `_story_context` | `seed_image=abspath` whenever seeded (`:1941`), so `story_engine.seed_omits_identities` (`story_engine.py:2436-2441`, SI1) drops every cast identity sentence from every shots `Image:` |
| G10 | `bin/ltx-movie:2339-2383` `phase2_stills` | `:2342-2345` sends every shots+seed run to `_phase2_seed_context` / `_phase2_shots_seed` (Qwen); `:2351-2354` adds `--seed-image`; `:2367-2370` shots → `_phase2_shots_cast_refs` / `_phase2_shots` |
| G11 | `bin/ltx-movie:2421-2427` `_shots_missing_stills`; `:2439-2476` `_phase2_shots` | existence-only reuse per stills-LoRA group |
| G12 | `bin/ltx-movie:2603-2815, 2817-3074` | the Qwen paths: `seed_edits.json`, `seed_context_edits.json` (entries `n`, `status`, `still_sha256`) |
| G13 | `bin/ltx-movie:3918-3926` (dry-run Phase 0 text, two-way on `shots`), `:3952` (Phase 1c block, not shots), `:3963-3969` (Qwen Phase 2 block for every shots+seed run), `:3970-4004` (stills branch) |
| G14 | `bin/ltx-movie:4051-4075` `_phase_sequence` | Phase 1c only when `seed_edit` and not shots (`:4068`); as-is never inserts it |
| G15 | `movie_ui_lib.py:1564-1574` V1 rule 8 | shots+seed: model `None`/`as-is` refused; stills LoRAs refused; legacy refused |
| G16 | `movie_ui_lib.py:1035-1039` `build_argv` | emits `--seed-edit-model <value>` (also `as-is`) when not `None`; `:2304-2305` `job_phases` 1c only when not shots |
| G17 | `movie_ui_server.py:849-854` `_h_job_create` | 409 probe skipped for `None`/`as-is` |
| G18 | `movie_ui_batch.py:38-46` | `seed_edit_model`/`seed_edit_loras` at level `stills` |
| G19 | `static/movie-ui/index.html:90-99` | the `c-sq` box, `c-sq-shots-note` ("… Z-Image is not used …"), `:101-105` the Mode select |
| G20 | `static/movie-ui/app.js:51` `COMPOSE_PICKER`; `:414-419` `composeSeedEditActive`; `:423-427` `composeSeedDefault`; `:429-463` `composeFields`; `:541-571` `updateComposeButtons` (SE31 block `:550-561`); `:844-845` `fillCompose`; `:886` panel-wide `change` → `updateComposeButtons(); preview();` |

### 0.2 Grounding: the pins (verified at `e8d7f3a`)

| Pin | File:line | Effect here |
|---|---|---|
| `test_mut26` BASELINE over `PIPELINE_FILES` | `tests/test_movie_ui_builder.py:223-228, 293` | `bin/ltx-movie` is the only pinned file that changes; Task 3 moves BASELINE |
| `NEW_PY` tail | `tests/test_qwen_edit.py:404-405` (QET11) | not extended ([CR] CR15 precedent); new files still avoid `load_module(` and `urllib` |
| L17b, RST50 `"no_stills" not in phase2_stills` | `tests/test_ltx_movie_offline.py:713-716`, `tests/test_story_engine.py:2423-2444` | the new code in `phase2_stills` has no `no_stills` |
| RST50 / L17d / L17f / L46e / L46f literal counts | `tests/test_story_engine.py:2427-2438`, `tests/test_ltx_movie_offline.py:721-729, 1588-1593, 1259-1260` | no new `cmd += ["--seed-image", args.seed_image]`, `phase2_cmd += ["--seed-image", …]`, `_render_flags(args)` or `ltx-mlx-render` path; none of `story-images` counts change (that file is untouched) |
| L7j (no top-level `import re`) | `tests/test_ltx_movie_offline.py` | no new import |
| plan prompt no-brace rule (RST8, RST47) | `tests/test_story_engine.py` | `story_engine.py` untouched |
| texts changed | S33 `tests/test_shots_mode.py:936-938`; SET1 `MODEL_RULE` + HELP `tests/test_ltx_movie_shots_seed.py:226-227, 240, 300-319`; CXT1 `tests/test_ltx_movie_seed_context.py:222-227`; MUT4 `tests/test_movie_ui_checks.py:76-78`; SDT17 `tests/test_movie_ui_seedfolder.py:560-561`; SET16/SET18 `NEEDS_MODEL` + SET20 `tests/test_movie_ui_shots_seed.py:33-34, 66, 227` | exact edits in E13-E16, U8-U10 |
| QET38/QET39 Compose pins | `tests/test_movie_ui_qwen_edit.py:436-439, 489-499` | kept verbatim: `qwenPicker("c-sq", true)`, the `seedEdit` and `seed_edit_model: seedEdit ? …` lines of `composeFields`, `COMPOSE_PICKER.select(f.seed_edit_model \|\| "as-is", …)` |
| deploy gate | `scripts/deploy/build_pkg.py:384`, `tests/test_deploy_pkg.py:1264` | records `bin/ltx-movie`'s own sha256; no change |

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `bin/ltx-movie` | **yes** | 1 | E1-E12 |
| D2 | `tests/test_ltx_movie_shots_zimage.py` | no | 1 | new, SZ1-SZ10 |
| D3 | `tests/test_shots_mode.py`, `tests/test_ltx_movie_shots_seed.py`, `tests/test_ltx_movie_seed_context.py` | no | 1 | E13-E16 |
| D4 | `movie_ui_lib.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js` | no | 2 | U1-U7 |
| D5 | `tests/test_movie_ui_shots_zimage.py` | no | 2 | new, SZ11-SZ16 |
| D6 | `tests/test_movie_ui_checks.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_shots_seed.py` | no | 2 | U8-U10 |
| D7 | `tests/test_movie_ui_builder.py` | no | 3 | BASELINE move |

Untouched: `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `qwen_edit.py`, `movie_ui_server.py`, `movie_ui_batch.py`, `scripts/deploy/*`.

### 0.4 Out of scope (deliverable 1)

F2 and F4 (Section 7, optional); a per-clip first-frame pipeline for text-to-video and any Z-Image option where a seed is edited outside shots mode (both closed by the user, Section 9); any change to the Qwen path's behaviour, records or texts other than the refusal texts of E3/U1; a new `FIELD_FLAGS` entry; cast refs on the Z-Image seed path; any model run, server or render in tests; any agent access to macstudio.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| SZK1 | The gate after Task 3: `lost 0 (listed 0, unexpected 0); new tests 16, not passing 0`, `GATE PASS`; `python3 tests/test_ltx_movie_offline.py` prints the same `OK n/n` as at `e8d7f3a` | V1 |
| SZK2 | `git diff --name-only e8d7f3a HEAD` is exactly D1-D7; among `PIPELINE_FILES` only `bin/ltx-movie` | V2 |
| SZK3 | L1: `images/panel_01.png` is the seed (letterboxed, no other change); no `seed_edits.json` is written and the log has no `seed edits:` line | L1 |
| SZK4 | L1: at least 6 of panels 2-8 show the seed's person recognisably (the user's judgement) and every `Image:` of story.md carries the cast description | L1 |
| SZK5 | L2: each Z-Image group log of a panel naming the library character loads that character's stills LoRA | L2 |
| SZK6 | L3: the default engine (Qwen) behaves exactly as before (`seed_edits.json`, `seed edits:` lines) | L3 |

Every ZE requirement and SZ test is a must-have. There are no nice-to-haves.

---

## 1. The Compose cells: which engine runs today and what each cell offers after deliverable 1

Facts (verified): `--no-stills` is text-to-video with no still at all (`bin/ltx-movie:560-565`), and refuses `--seed-image` (`:4121-4125`), `--character` (`:1004-1007`) and `--location` (`:1062-1065`). **Chained without a seed already makes a Z-Image still from panel 1's `Image:` and animates the chain from it** (`phase2_stills`, `--only 1`, `:2346-2383`), with the cast's stills LoRAs. **Shots without a seed already makes a Z-Image still per panel and animates each** (`_phase2_shots`).

| Cell | Mode | Seed | Characters | Image engine today | Engine picker after deliverable 1 (default first) | Changes |
|---|---|---|---|---|---|---|
| C1 | text-to-video | no | no | none | `none` only | picker shown, read-only **[spec choice]**; no Z-Image first frame (Q1, decided) |
| C2 | text-to-video | no | yes | refused (casting needs chained) | `none` only; the V1/CLI refusal unchanged | read-only; F2 optional |
| C3 | text-to-video | yes | any | refused (V1 rule 8) | `none` only; refusal unchanged | none |
| C4 | chained | no | no | Z-Image, panel 1 | `zimage` only | picker shown, read-only **[spec choice]** |
| C5 | chained | no | yes | Z-Image, panel 1, cast stills LoRAs | `zimage` only | read-only |
| C6 | chained | yes | no | panel 1 = seed as-is or a Qwen edit (the `c-sq` select) | `seed` only (never `zimage`); the `c-sq` select keeps as-is vs Qwen model | read-only **[spec choice]** (QET38 pins as-is inside `c-sq`); SZ16 |
| C7 | chained | yes | yes | as C6; stills LoRAs never apply to panel 1 | as C6 (no Z-Image: the seed is edited, Q2 decided) | read-only; SZ16 |
| C8 | shots | no | no | Z-Image, every panel | `zimage` only | read-only |
| C9 | shots | no | yes | Z-Image, every panel, cast stills LoRAs (`--cast-refs-model` is CLI-only) | `zimage` only | read-only |
| C10 | shots | yes | no | Qwen edit of the seed, every panel | `qwen` (default), `zimage` | **[spec choice]** ZE1-ZE14 |
| C11 | shots | yes | yes | as C10; stills LoRAs do not apply | `qwen` (default), `zimage` (character stills LoRAs apply to panels 2..N) | **[spec choice]** ZE1-ZE14 |

So the request's "Z-Image still as the first frame, then animate it" (1) is today's C4/C5 (kept exactly, Q1) and "Z-Image stills with the characters' stills LoRAs" (2) is today's C5/C8/C9. **Z-Image is offered as a choice only in C10 and C11.** It is shown, read-only, as the engine of C4, C5, C8 and C9 (no seed). It is never offered in C1-C3 (text-to-video) or C6-C7 (a seed edited outside shots mode, Q2).

---

## 2. Decisions

1. **CLI surface: no new option; `--seed-edit-model as-is` with `--shots --seed-image` selects the Z-Image engine [spec choice].** In chained mode as-is already means "panel 1 is the seed, no Qwen edit"; in shots mode the same value now means the same for panel 1 and the shots default (Z-Image) for the rest. Against a new `--shots-seed-engine {qwen,zimage}`: it would add a `FIELD_FLAGS` entry and V-rule gating (SET21 pins 31 entries), a field in `DEFAULT_FIELDS`, `FIELD_LEVELS` and the batch merge, and it would have to refuse `--shots-seed-engine zimage --seed-edit-model ID` anyway. With as-is, `build_argv`, `job_phases`, the 409 probe, the batch levels and the seed folder need no change (G16-G18), and an older workspace refuses the run in V6 with its own SE2 text, so nothing is queued there.
2. **A missing `--seed-edit-model` stays refused on the CLI, with a text naming both engines [spec choice]** (no silent default, as SE2). Compose always sends the choice.
3. **Composition with the other flags (ZE2):** `--seed-edit-lora` with as-is: refused by `_resolve_seed_edit` (unchanged text). `--seed-context` with as-is: refused by `_resolve_seed_context` (unchanged text). `--cast-refs-model` with a seed: refused (unchanged text; F4). `--stills-lora` with as-is: **allowed** (it applies to panels 2..N, as without a seed); with an ID still refused. `--story-legacy`/`--story-prompt-override`: refused for both engines (unchanged).
4. **Phase sequence (ZE5):** as-is sets `args.seed_edit = None`, so `_phase_sequence` inserts no Phase 1c (unchanged code). Tuple: `(phase0_seed, phase1_story, [phase_release_story_server,] [phase_redo_shots,] phase2_stills, phase3_manifest, phase4_render)`.
5. **Phase 2 (ZE4, ZE6):** the shots+seed dispatch to the Qwen paths gains `and not _shots_zimage_seed(args)`; the Z-Image run then takes the existing shots branch: one `bin/ltx-story-images` run per stills-LoRA group, each with `--seed-image <seed>`, so panel 1 is the letterboxed seed (`bin/ltx-story-images:471-491`, LoRA plans skip panel 1 at `:363-364, 393-394`) and every other panel is Z-Image with the global, catalog, cast and location stills LoRAs. Panel 1 always counts as missing on this path, so its group always runs and the copy always matches the current seed **[spec choice]** (cost: one `bin/ltx-story-images` start per Phase 2 run). Any still that `seed_edits.json` or `seed_context_edits.json` records as an `ok` Qwen edit with the same sha256 is moved aside into `<story>/redo/<stamp>-<pid>/images/` first (never deleted), because existence-only reuse would otherwise keep a Qwen still **[spec choice]**.
6. **Story prompt (ZE3):** the legacy preface/postface is already skipped for every shots story (SE6), so the shots template's `Image:` on every panel is kept. The robust engine still attaches the seed and `SEED_PARAGRAPH` (beat 1 starts from the seed's scene, cast described from the seed). **On the Z-Image path the cast identity sentences are restored in every `Image:` [spec choice]:** Z-Image never sees the seed, so without them a person the seed shows (no LoRA) would be invented anew on every panel. Mechanism, bin/ltx-movie only: `_story_context` passes `seed_image=None` on the Z-Image path, so `seed_omits_identities(ctx)` is false and the story is written exactly as an unseeded shots story; `seed_agent_image` is unchanged. plan.json's `seed_image` (no reader; grep of `*.py` and `bin/`) records `null` there.
7. **A story planned for the other engine (ZE7):** a rerun reuses story.md. On the Z-Image path Phase 2 prints one warning when plan.json records a non-null `seed_image` (planned for Qwen, identity sentences left out); nothing is refused **[spec choice]** (a batch "New stills" fork that flips the engine lands here too; Risk R3).
8. **What stays refused (ZE2, ZE11):** as Decision 3, plus V1: `None` refused with a new text naming both engines; stills LoRAs refused only with a Qwen model.
9. **UI (ZE12-ZE14):** one `Stills engine` select (`c-engine`) next to Mode, options per cell from `composeEngines(mode, seeded)` (Section 1). The choice of C10/C11 lives in `S.composeEngine` (`"qwen"` default, reset by every new seed, restored by `fillCompose` from a job's fields). With `zimage`: the `c-sq` box (Qwen model select, LoRA rows, the Qwen shots note and the probe reason) is hidden, `c-engine-note` explains the Z-Image path, and `composeFields` sends `seed_edit_model: "as-is"`, `seed_edit_loras: null`. With `qwen`: exactly today's page. The `c-sq` select's as-is option stays disabled in shots mode (SE31 verbatim). `composeEngines` never returns `zimage` for a seeded cell other than shots, and `composeFields`/`fillCompose` apply `S.composeEngine` only in shots mode, so a chained seed is always as-is or a Qwen edit (SZ16).

---

## 3. Requirements and edits

### Task 1: `bin/ltx-movie` (each Old occurs exactly once; stop if not)

- **E1 (ZE1)** after `SHOTS_SEED_LORA_NOTE`'s two lines (`:165-166`) add:
```python
# Shots Z-Image engine (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md, ZE1): with --shots, --seed-image
# and --seed-edit-model as-is, panel 1 is the seed and every other panel is a Z-Image still, as shots mode without a seed.
SHOTS_ZIMAGE_MOVE_WHY = "(a Qwen edit of the seed; the Z-Image engine renders this panel again)"
SHOTS_ZIMAGE_PLAN_WARNING = ("Warning: %s was planned for the Qwen engine (plan.json records the seed image), so its "
                             "Image: lines leave out the cast descriptions that Z-Image draws from; rerun with "
                             "--force-story to plan the story for Z-Image")
```
- **E2 (ZE1)** directly before `def _shots_missing_stills(args, panels):` (`:2421`) add:
```python
def _shots_zimage_seed(args):
    """True on the shots Z-Image seed path (shots Z-Image engine spec ZE1): --shots, --seed-image and --seed-edit-model
    as-is. Panel 1 is then the seed and every other panel a Z-Image still, as in shots mode without a seed."""
    return bool(getattr(args, "shots", False) and getattr(args, "seed_image", None)
                and getattr(args, "seed_edit_model", None) == "as-is")


def _shots_qwen_stills(args):
    """{n: path} of every images/panel_NN.png that seed_edits.json or seed_context_edits.json records as an ok Qwen
    edit with the same sha256 (shots Z-Image engine spec ZE6). Reads; never writes."""
    paths = _story_paths(args.story_id)
    found = {}
    for record, schema in ((_shots_seed_paths(paths["story_dir"])["record"], SHOTS_SEED_EDITS_SCHEMA),
                           (_seed_context_paths(paths["story_dir"])["record"], SEED_CONTEXT_SCHEMA)):
        for n, entry in _shots_seed_entries(record, schema).items():
            still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
            if (entry.get("status") == "ok" and os.path.isfile(still)
                    and entry.get("still_sha256") == _sha256_file(still)):
                found[n] = still
    return found


def _shots_zimage_prepare(args, dry_run=False):
    """Phase 2's first step on the shots Z-Image seed path (shots Z-Image engine spec ZE6, ZE7): the warning when
    plan.json was planned for the Qwen engine, then every recorded Qwen still moved aside into
    <story>/redo/<stamp>-<pid>/images/. With dry_run it prints the moves and moves nothing."""
    paths = _story_paths(args.story_id)
    try:
        with open(os.path.join(paths["story_dir"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        plan = None
    if (isinstance(plan, dict) and isinstance(plan.get("seed_image"), str) and plan["seed_image"]
            and not (dry_run and getattr(args, "force_story", False))):
        print(SHOTS_ZIMAGE_PLAN_WARNING % paths["story_md"])
    stale = _shots_qwen_stills(args)
    archive = os.path.join(paths["story_dir"], "redo", "<UTC stamp>-<pid>" if dry_run else "%s-%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()), "images")
    for n in sorted(stale):
        moved = os.path.join(archive, os.path.basename(stale[n]))
        if dry_run:
            print("Would move %s -> %s %s" % (stale[n], moved, SHOTS_ZIMAGE_MOVE_WHY))
            continue
        os.makedirs(archive, exist_ok=True)
        os.replace(stale[n], moved)
        print("stills: moved %s -> %s %s" % (stale[n], moved, SHOTS_ZIMAGE_MOVE_WHY))
```
- **E3 (ZE2)** in `_resolve_shots`: the comment `        # Shots seed edits SE2: every panel's still is a Qwen edit of the seed.` becomes the two lines `        # Shots seed edits SE2, amended by the shots Z-Image engine spec ZE2: an ID makes every panel's still a Qwen` / `        # edit of the seed; as-is keeps the seed as panel 1 and every other panel is a Z-Image still.`. The block `if args.seed_edit_model in (None, "as-is"):` and its three print lines become:
```python
        if args.seed_edit_model is None:
            print("Error: --shots with --seed-image needs --seed-edit-model: a Qwen model ID makes every panel's "
                  "still an edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still "
                  "with Z-Image", file=sys.stderr)
            return 2
```
  and the next line `        if getattr(args, "stills_lora_path_specs", None):` (`:1501`) becomes `        if args.seed_edit_model != "as-is" and getattr(args, "stills_lora_path_specs", None):` (its text unchanged).
- **E4 (ZE4)** `phase2_stills` `:2342`: `    if getattr(args, "shots", False) and getattr(args, "seed_image", None):` becomes `    if getattr(args, "shots", False) and getattr(args, "seed_image", None) and not _shots_zimage_seed(args):` with the line `    # Shots Z-Image engine ZE4: with --seed-edit-model as-is the shots branch below runs, panel 1 being the seed.` directly above. Nothing else in `phase2_stills` changes.
- **E5 (ZE6)** `_shots_missing_stills`: the body becomes
```python
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    zimage = _shots_zimage_seed(args)
    qwen = _shots_qwen_stills(args) if zimage else {}
    return [i for i in panels if i in redo or i in qwen or (zimage and i == 1)
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```
  and its docstring gains: ` On the shots Z-Image seed path (shots Z-Image engine spec ZE6) also panel 1, which bin/ltx-story-images writes again from the seed, and every panel whose still is a recorded Qwen edit.`
- **E6 (ZE6)** `_phase2_shots`: directly before `    groups = _exclude_groups(` (`:2447`) add `    if _shots_zimage_seed(args):` / `        _shots_zimage_prepare(args)        # shots Z-Image engine ZE6: the plan warning; Qwen stills moved aside`.
- **E7 (ZE3)** `_story_context` `:1941`: `        seed_image=os.path.abspath(args.seed_image) if seeded else None,` becomes `        seed_image=os.path.abspath(args.seed_image) if seeded and not _shots_zimage_seed(args) else None,` with `    # Shots Z-Image engine ZE3: Z-Image never sees the seed, so its Image: lines keep every cast description.` directly above `    return engine.StoryContext(`.
- **E8 (ZE9)** dry-run Phase 0 (`:3923-3925`): the conditional becomes
```python
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size and renders every other "
                 "panel's still with Z-Image; nothing is cropped." if _shots_zimage_seed(args) else
                 "Phase 2 edits the ORIGINAL into every panel's still with the Qwen edit model; nothing is cropped."
                 if getattr(args, "shots", False) else
                 "Phase 2 fits the ORIGINAL into panel_01.png at twice the video size; nothing is cropped."))
```
- **E9 (ZE9)** `:3963` gets E4's condition (`and not _shots_zimage_seed(args)`); `:3998-3999` `        elif getattr(args, "shots", False):` / `            _print_shots_stills_plan(args, phase2_cmd)` becomes that `elif` line, then `            if _shots_zimage_seed(args):` / `                _shots_zimage_prepare(args, dry_run=True)   # shots Z-Image engine ZE9`, then the unchanged call.
- **E10 (ZE10)** `--seed-edit-model` help becomes exactly: `with --seed-image: edit the seed into panel 1 with a Qwen registry edit model (qwen21-q4, qwen21-q8, qwen21-bf16, qwen2511-q4, qwen2511-bf16), prompted by panel 1's Image: text after Phase 1 and screened with content safety; as-is, like leaving the flag out, uses the seed unchanged. With --shots it is required and chooses the stills engine: an ID makes every panel's still an edit of the seed, each prompted by its own Image: text; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image and its stills LoRAs, as --shots does without a seed. See docs/superpowers/specs/2026-11-03-qwen-edit-models-design.md, 2026-11-05-compose-shots-seed-edit-design.md and 2026-11-11-shots-zimage-engine-design.md.`
- **E11 (ZE10)** in the `--shots` help, `With --seed-image, every panel's still is instead a Qwen edit of the seed (--seed-edit-model ID, required).` becomes `With --seed-image, --seed-edit-model (required) chooses the stills engine: an ID makes every panel's still a Qwen edit of the seed; as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image.` (literals split as the surrounding code does; `--seed-image`'s help is unchanged).
- **E12 (ZE10)** docstring `:116`, after `Absent, or as-is, the seed is used unchanged.`, add (wrapped to the paragraph's width): ` With --shots (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md) the flag is required: as-is keeps the seed as panel 1 and renders every other panel's still with Z-Image and its stills LoRAs, as --shots does without a seed.`
- **ZE5, ZE8 (no edit):** `_phase_sequence`, `build_story_prompt`, `phase3_manifest` (`--shots` manifest of every `images/panel_NN.png`), Phase 4 and `--redo` (`phase_redo_shots` moves the redo stills; the group rewrites them, panel 1 from the seed) are unchanged.
- **E13** `tests/test_shots_mode.py:937-938` and `tests/test_ltx_movie_shots_seed.py:226-227` (`MODEL_RULE`): the text becomes E3's (with `\n` in `MODEL_RULE`). In SET1 (`:240`) the case `(("--seed-edit-model", "as-is"), MODEL_RULE),` is removed and, after the existing `qwen21-q4` → 0 assert, `assert movie._resolve_shots(_parse(*(shots + ["--seed-edit-model", "as-is"]))) == 0` is added.
- **E14** `tests/test_ltx_movie_shots_seed.py` `HELP["--seed-edit-model"]` and `HELP["--shots"]` become E10's text and the E11-edited text.
- **E15** `tests/test_ltx_movie_seed_context.py` CXT1 `:222-227`: the no-model case expects E3's text + `\n`; the as-is case expects `Error: --seed-context needs --seed-edit-model ID, a Qwen registry edit model (as-is is refused): every shots still is a Qwen edit of the seed\n`.
- **E16** create `tests/test_ltx_movie_shots_zimage.py` (Section 4).

### Task 2: movie-ui

- **U1 (ZE11)** `movie_ui_lib.py:1565-1574`: the comment becomes `        # Shots seed edits SE23, amended by the shots Z-Image engine spec ZE11: as-is is the Z-Image engine.`; `if fields.get("seed_edit_model") in (None, "as-is"):` becomes `if fields.get("seed_edit_model") is None:` with the text `"a seed image in shots mode needs a stills engine: a Qwen edit model (every panel's still is an edit of the seed) or as-is (panel 1 is the seed and Z-Image renders every other panel)"`; the stills-LoRA condition becomes `if (fields.get("seed_edit_model") != "as-is" and isinstance(fields.get("stills_loras"), list) and fields["stills_loras"]):` (text unchanged). The legacy rule is unchanged.
- **U2 (ZE12)** `index.html`: between `:105` (`    </select></label>`, the Mode select's end) and `:106` insert `    <label>Stills engine <select id="c-engine"></select></label> <span id="c-engine-note" class="muted"></span>`.
- **U3 (ZE12)** `app.js:25`: `seedOrigin: null, ` becomes `seedOrigin: null, composeEngine: "qwen", `. In `composeSeedDefault` insert `    S.composeEngine = "qwen";` as its first body line. In `fillCompose`, directly after `    S.seedOrigin = "job";`, insert `    S.composeEngine = f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is" ? "zimage" : "qwen";`.
- **U4 (ZE12)** directly after `composeSeedDefault`'s closing `  }` add:
```js
  // Shots Z-Image engine spec ZE12: the stills engines of each Compose cell (mode x seed), the default first.
  const ZIMAGE_SEED_NOTE = "Panel 1 is the seed. Every other panel is a Z-Image still from its own Image: text, " +
    "with the stills LoRAs of the characters, the locations, the catalog pick and the stills LoRA rows.";
  function composeEngines(mode, seeded) {
    if (mode === "no_stills") { return [["none", "None: every clip is text-to-video"]]; }
    if (mode === "chained") {
      return [seeded ? ["seed", "The seed: panel 1 is the seed, as-is or a Qwen edit (below)"]
        : ["zimage", "Z-Image: panel 1's still from its Image: text"]];
    }
    return seeded ? [["qwen", "Qwen edit of the seed: every panel's still"],
      ["zimage", "Z-Image: panel 1 is the seed, every other panel from its Image: text"]]
      : [["zimage", "Z-Image: every panel's still from its Image: text"]];
  }

  function composeEngineUpdate(mode) {
    const seeded = ($("#c-res-seed").checked && Boolean(S.seedUpload)) || $("#c-res-folder").checked;
    const options = composeEngines(mode, seeded);
    const values = options.map(function (o) { return o[0]; });
    const select = $("#c-engine");
    if (Array.prototype.map.call(select.options, function (o) { return o.value; }).join(",") !== values.join(",")) {
      select.textContent = "";
      options.forEach(function (o) {
        const option = document.createElement("option");
        option.value = o[0];
        option.textContent = o[1];
        select.appendChild(option);
      });
    }
    const zimageSeed = mode === "shots" && seeded && S.composeEngine === "zimage";
    select.value = zimageSeed ? "zimage" : values[0];
    select.disabled = options.length === 1;
    $("#c-engine-note").textContent = zimageSeed ? ZIMAGE_SEED_NOTE : "";
    return select.value;
  }
```
- **U5 (ZE13)** `composeFields`: `    return {` (`:436`) becomes `    const out = {`; after its closing `    };` (`:463`) add:
```js
    // Shots Z-Image engine spec ZE13: a seeded shots movie's Z-Image engine is sent as the seed as-is.
    if (seedEdit && out.mode === "shots" && S.composeEngine === "zimage") {
      out.seed_edit_model = "as-is";
      out.seed_edit_loras = null;
    }
    return out;
```
- **U6 (ZE14)** `updateComposeButtons`: after `    show($("#c-check-seams-box"), mode === "chained");` insert `    const engine = composeEngineUpdate(mode);`; after `    show($("#c-sq-shots-note"), shotsSeed);` insert `    const zimageSeed = shotsSeed && engine === "zimage";`; `    show($("#c-sq-qwen-box"), seedEditOn);` becomes `    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);`; `    const seedEditReason = seedEditOn ? COMPOSE_PICKER.reason() : "";` becomes `    const seedEditReason = seedEditOn && !zimageSeed ? COMPOSE_PICKER.reason() : "";`.
- **U7 (ZE14)** `setupCompose`: after `:886` insert `    $("#c-engine").addEventListener("change", function () { S.composeEngine = $("#c-engine").value; });` (the target listener runs before the panel-wide one, which then runs `updateComposeButtons(); preview();`).
- **U8** `tests/test_movie_ui_checks.py:77-78` (MUT4) and `tests/test_movie_ui_seedfolder.py:560-561` (SDT17): U1's new text.
- **U9** `tests/test_movie_ui_shots_seed.py`: `NEEDS_MODEL` (`:33-34`) becomes U1's text; SET16 `for model in (None, "as-is"):` becomes `for model in (None,):` followed by `assert _errors(v1_env, seed_edit_model="as-is", **shots) == []`.
- **U10** `tests/test_movie_ui_shots_seed.py:227` (SET20): `SE31 + '    show($("#c-sq-qwen-box"), seedEditOn);\n'` becomes `SE31 + '    const zimageSeed = shotsSeed && engine === "zimage";\n    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);\n'`.
- **U11** create `tests/test_movie_ui_shots_zimage.py` (Section 4).
- Unchanged (ZE11): `build_argv`, `job_phases`, `FIELD_FLAGS`, `DEFAULT_FIELDS`, `movie_ui_server.py` (as-is skips the probe), `movie_ui_batch.py`, the `c-sq` markup and `qwenPicker`. All new page text goes in through markup or `textContent`.

---

## 4. Tests

**`tests/test_ltx_movie_shots_zimage.py`.** Docstring `"""Tests for the shots Z-Image engine (docs/superpowers/specs/2026-11-11-shots-zimage-engine-design.md, SZ1-SZ10): with --shots, --seed-image and --seed-edit-model as-is, panel 1 is the seed and every other panel a Z-Image still.` + blank + `Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py` + blank + `No test loads a model, renders or contacts a server. Stdlib, PIL and pytest."""`. Imports `argparse`, `glob`, `hashlib`, `json`, `os`, `pytest`, `from PIL import Image`, `import story_engine_testutil as seu`, `import test_dialogue as dlg`, `import test_ltx_movie_shots_seed as sse`, `from test_ltx_movie_shots_seed import clean_env  # noqa: F401`; `movie = sse.movie`. Helpers: `_z(tmp, **kw)` = `sse._phase_args(tmp, seed_edit=None, seed_edit_model="as-is", **kw)`; `_stills(tmp, n=3)` writes `<tmp>/stories/s1/images/panel_0k.png` (8x8 RGB, colour `(10*k, 0, 0)`) for k in 1..n and returns `{k: path}`; `_rec(tmp, name, schema, entries)` writes `<tmp>/stories/s1/<name>` as `{"schema": schema, "panels": entries}`; `_sha(path)`; `MOVE = "(a Qwen edit of the seed; the Z-Image engine renders this panel again)"`; `NO_MODEL` = E3's text + `"\n"`.

- **SZ1 `test_sz1_the_option_rules(clean_env, capsys)`:** with `shots = ["--shots", "--seed-image", sse._seed1920(tmp)]`: `_resolve_shots(sse._parse(*shots))` → 2, err `NO_MODEL`; `+ ["--seed-edit-model", "as-is"]` → 0; `+ as-is + ["--stills-lora", "/x.safetensors"]` → 0; `+ as-is + ["--story-legacy"]` → 2, err `sse.ENGINE_RULE % "--story-legacy"`; `+ qwen21-q4 + --stills-lora` → 2, err `sse.STILLS_RULE`. `movie.main(["n", "--story-id", "s1", "--dry-run", "--no-review", "--no-auto-lora"] + shots + ["--seed-edit-model", "as-is"] + extra)` == 2 with err exactly: extra `["--seed-edit-lora", "uncensored=1.0"]` → `Error: --seed-edit-lora cannot be combined with --seed-edit-model as-is\n`; `["--cast-refs-model", "qwen21-q4"]` → `Error: --cast-refs-model cannot be combined with --seed-image: with a seed image every shots still is already a Qwen edit of the seed\n`; `["--seed-context", "still"]` → E15's seed-context text.
- **SZ2 `test_sz2_the_path_predicate`:** `movie._shots_zimage_seed(argparse.Namespace(shots=s, seed_image=i, seed_edit_model=m))` is True only for `(True, "/s.png", "as-is")`; False for `(True, "/s.png", "qwen21-q4")`, `(True, "/s.png", None)`, `(True, None, "as-is")`, `(False, "/s.png", "as-is")`; False for `argparse.Namespace(shots=True, seed_image="/s.png")`.
- **SZ3 `test_sz3_the_phase_tuple(clean_env)`:** `args = sse._parse("--shots", "--seed-image", sse._seed1920(tmp), "--seed-edit-model", "as-is")`; `_resolve_shots(args) == 0`, `_resolve_seed_edit(args) == 0`, `args.seed_edit is None`; `args.seed_context = None`; `args.story_server_stop_after_story = True`; names of `_phase_sequence(args)` == `["phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest", "phase4_render"]`; with `args.story_only = True` → `["phase0_seed", "phase1_story"]`.
- **SZ4 `test_sz4_phase_2_runs_the_shots_branch(clean_env, monkeypatch, capsys)`:** patch `_phase2_shots_seed`, `_phase2_seed_context` (recorders returning 0) and `_phase2_shots` (records `list(cmd)`, returns 0). `args = _z(tmp, global_stills_loras=[("/x/still.safetensors", 0.8)])`; `phase2_stills(args) == 0`; no Qwen recorder call; one `_phase2_shots` cmd with `cmd[cmd.index("--seed-image") + 1] == args.seed_image`, `cmd[cmd.index("--lora") + 1] == "/x/still.safetensors:0.8"`, `cmd[cmd.index("--only") + 1] == "1"`, `cmd[cmd.index("--width") + 1] == "1408"`; stdout `"=== Phase 2: stills ===\n"`.
- **SZ5 `test_sz5_missing_stills(clean_env)`:** `sse._write_story(tmp)`; `p = _stills(tmp)`; `_rec(tmp, "seed_edits.json", "ltx-movie.seed-edits.v1", [{"n": 2, "status": "ok", "still_sha256": _sha(p[2])}, {"n": 3, "status": "ok", "still_sha256": "0" * 64}])`: `_shots_missing_stills(_z(tmp), [1, 2, 3]) == [1, 2]`; `_rec(tmp, "seed_context_edits.json", "ltx-movie.seed-context-edits.v1", [{"n": 3, "status": "ok", "still_sha256": _sha(p[3])}])` → `[1, 2, 3]`; `_phase_args(tmp)` (Qwen) → `[]`; `_phase_args(tmp, seed_image=None, seed_edit=None)` → `[]`.
- **SZ6 `test_sz6_qwen_stills_move_aside_and_the_group_runs(clean_env, monkeypatch, capsys)`:** state as SZ5's final state; patch `_stream_and_tee` to record `cmd` and return 0. `_phase2_shots(_z(tmp), ["py", "ltx-story-images", "--only", "1", "--seed-image", "/s.jpg"]) == 0`; one call with `--only` value `"1,2,3"` and last item `"--shots"`; `p[1]` exists; `p[2]`, `p[3]` do not; `glob` of `<story>/redo/*/images/panel_02.png` and `panel_03.png` each one file with the old sha; stdout lines `stills: moved <p[2]> -> <moved 2> ` + MOVE then the same for 3, in that order. Rewrite panels 2-3 with new bytes; a second call prints no `stills: moved` line and runs one group again (panel 1). `_phase2_shots(_phase_args(tmp, seed_image=None, seed_edit=None), same cmd)` runs no group (`every still exists; skipped`).
- **SZ7 `test_sz7_the_plan_warning(clean_env, capsys)`:** plan.json `{"seed_image": "/s/seed.png"}` → `_shots_zimage_prepare(_z(tmp))` stdout == `SHOTS_ZIMAGE_PLAN_WARNING % <story.md> + "\n"`; with `dry_run=True` and `force_story=True` → `""`; plan.json `{"seed_image": null}` → `""`; no plan.json → `""`.
- **SZ8 `test_sz8_the_story_keeps_the_identity_sentences(tmp_path, monkeypatch)`:** `seu.set_story_env(monkeypatch, tmp_path)`; `monkeypatch.setattr(dlg.ltx_movie, "WS", seu.make_ws(tmp_path))`; `args = dlg._movie_args("n", "--story-id", "x", "--shots", "--seed-image", "/s/seed.png", "--seed-edit-model", "as-is")`; `args.seed_downscaled_path = "/s/agent.png"`; `ctx = dlg.ltx_movie._story_context(args)`; `ctx.seed_image is None`, `ctx.seed_agent_image == "/s/agent.png"`, `not dlg.se.seed_omits_identities(ctx)`. The same with `qwen21-q4`: `ctx.seed_image == "/s/seed.png"` and `dlg.se.seed_omits_identities(ctx)`.
- **SZ9 `test_sz9_the_dry_run(clean_env, capsys)`:** `out = sse._dry(capsys, "--shots", "--seed-image", seed, "--seed-edit-model", "as-is")` (`seed = sse._seed1920(tmp)`): the one `Would validate ` line ends `(long edge 1024px) to <tmp>/stories/s1/seed_downscaled.png. Phase 2 fits the ORIGINAL into panel_01.png at twice the video size and renders every other panel's still with Z-Image; nothing is cropped.`; `--- Phase 1c: seed edit ---` not in lines; `Would edit the seed into every panel's still` not in out; the `Stills groups: computed from story.md after Phase 1 …` line (SET14's) is present and the next line contains `--seed-image ` + seed and ends `--shots`; `clean_env["fake"].calls` all empty. Then `sse._write_story(tmp)`, `_stills(tmp)`, SZ5's first record: lines contain `Would move <p2> -> <tmp>/stories/s1/redo/<UTC stamp>-<pid>/images/panel_02.png ` + MOVE and `stills group 1/1 (no character LoRAs; panels 1,2,3)` (no `would be skipped`); `p[2]` still exists; no `redo` directory.
- **SZ10 `test_sz10_help_and_docstring`:** the `--seed-edit-model` and `--shots` helps equal E10/E11 texts; `--seed-image` equals `sse.HELP["--seed-image"]`; `" ".join(movie.__doc__.split())` contains E12's sentence and `sse.DOC_SENTENCE`.

**`tests/test_movie_ui_shots_zimage.py`.** Docstring as above for SZ11-SZ16 (`movie-ui side`); imports `json`, `os`, `re`, `shutil`, `subprocess`, `pytest`, `movie_ui_testutil as mt`, `movie_ui_lib as lib`, `test_movie_ui_shots_seed as uss`, `from test_movie_ui_shots_seed import v1_env  # noqa: F401`, `from test_movie_ui_qwen_edit import _compose, _function, _job, _upload, env  # noqa: F401`; `NEEDS_CHOICE` = U1's text; `SHOTS = dict(seed_upload=uss.UP, mode="shots")`.

- **SZ11 `test_sz11_v1_rule_8(v1_env)`:** `uss._errors(v1_env, seed_edit_model="as-is", **SHOTS) == []`; with `stills_loras=[{"id": None, "path": "/a.safetensors", "strength": 1, "kind": None}]` → `[]`; `seed_edit_model=None` → `[NEEDS_CHOICE]`; as-is + `story_legacy=True` → `[uss.NEEDS_ENGINE]`; `qwen21-q4` + the stills row → `[uss.NO_STILLS_LORAS]`; as-is + `seed_edit_loras=uss.UNC` → `["seed edit LoRAs need a seed edit model other than as-is"]`.
- **SZ12 `test_sz12_argv_and_phases(v1_env)`:** `f = mt.fields(mt.WS, action="movie", seed_edit_model="as-is", **SHOTS)`; `argv = lib.build_argv(f, mt.WS, state)`; `i = argv.index("--seed-image")`; `argv[i:i + 4] == ["--seed-image", <state>/uploads/<UP>, "--seed-edit-model", "as-is"]`; `"--seed-edit-lora" not in argv`; `argv.count("--shots") == 1`; `lib.job_phases("movie", f) == ["0", "1", "1b", "2", "3", "4"]`.
- **SZ13 `test_sz13_jobs_and_seed_folders(env)`:** `up = _upload(s)`; POST `/api/jobs` `_compose(ws, up, story_id="shots-z", mode="shots", seed_edit_model="as-is")` → 201, its argv has `--seed-edit-model` then `as-is`, `env["probes"]["calls"] == []`. Seed folder as SET18's (`seed_edit_model="as-is"`) → 201, both rows `ok`, `queued == 2`; with `seed_edit_model=None` → 409, both rows `("refused", NEEDS_CHOICE)`.
- **SZ14 `test_sz14_the_page`:** `index.html` contains once `'      <option value="no_stills" data-field="no_stills">no stills</option>\n    </select></label>\n    <label>Stills engine <select id="c-engine"></select></label> <span id="c-engine-note" class="muted"></span>\n'`; `app.js` contains once each of `function composeEngines(mode, seeded) {`, `function composeEngineUpdate(mode) {`, `seedOrigin: null, composeEngine: "qwen", `; `updateComposeButtons` contains `'    show($("#c-check-seams-box"), mode === "chained");\n    const engine = composeEngineUpdate(mode);\n    COMPOSE_PICKER.update();\n'` and `'    const zimageSeed = shotsSeed && engine === "zimage";\n    show($("#c-sq-qwen-box"), seedEditOn && !zimageSeed);\n    const seedEditReason = seedEditOn && !zimageSeed ? COMPOSE_PICKER.reason() : "";\n'`; `composeFields` contains U5's five lines from `    if (seedEdit` through `    return out;`; `composeSeedDefault` contains `    S.composeEngine = "qwen";\n    S.seedOrigin = origin;\n`; `fillCompose` contains U3's line; `setupCompose` contains U7's line; SET20's page bans; `node --check app.js` when `node` exists.
- **SZ15 `test_sz15_the_engine_cells`:** skip unless `shutil.which("node")`; run `node -e` with `_function(js, "  function composeEngines(mode, seeded) {")` + `console.log(JSON.stringify([["no_stills",false],["chained",false],["chained",true],["shots",false],["shots",true]].map(function (c) { return composeEngines(c[0], c[1]).map(function (o) { return o[0]; }); })));` → stdout JSON `[["none"],["zimage"],["seed"],["zimage"],["qwen","zimage"]]` (Section 1's table).
- **SZ16 `test_sz16_no_zimage_where_a_seed_is_edited`:** (always runs) `body = _function(js, "  function composeEngines(mode, seeded) {")`; the chained branch text `'    if (mode === "chained") {\n      return [seeded ? ["seed", "The seed: panel 1 is the seed, as-is or a Qwen edit (below)"]\n'` is in `body`; `body.count('"zimage"') == 3` and `body.count('["zimage", "Z-Image: panel 1 is the seed') == 1`, the latter after `'return seeded ? [["qwen"'`; `composeFields` contains `out.mode === "shots" && S.composeEngine === "zimage"`; `fillCompose` contains `f.mode === "shots" && f.seed_upload && f.seed_edit_model === "as-is"`. When `node` exists, it also evaluates `composeEngines` for `["chained", true]`, `["no_stills", true]` and `["shots", true]`: the values are `["seed"]`, `["none"]` and `["qwen", "zimage"]`, and `"zimage"` is offered with more than one option only for `["shots", true]`.

---

## 5. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

Check out `shots-zimage` on macstudio first. Until a row is run it is recorded "not run (awaiting the user)".

| Row | Steps | Record | Pass |
|---|---|---|---|
| L1 | Compose: upload a medium-shot photo of one person, mode shots, Stills engine `Z-Image`, panels 8, a narrative through at least three places, Run all | the preview command (`--seed-edit-model as-is`, no `--seed-edit-lora`); `images/panel_01.png` beside the seed; story.md `Image:` lines; per panel 2-8: same person as the seed? (yes/no) | SZK3, SZK4 |
| L2 | L1 with a trained library character picked and a seed showing that character | each `images/stills-group-KK.log` | SZK5; at least 6 of panels 2-8 show the character |
| L3 | L1's seed and narrative with the default engine (`Qwen edit of the seed`), a new story id | `seed_edits.json`, the `seed edits:` lines | SZK6 |
| L4 | rerun L3's story id with `Z-Image` | the `stills: moved … (a Qwen edit …)` lines and the plan.json warning; `images/` | every Qwen still moved aside (none left in `images/` from `seed_edits.json`); the warning printed once |
| L5 | the page, each cell C1-C11 of Section 1 | the engine select's options and enabled state per cell; the `c-sq` box under `Z-Image` vs `Qwen`; a Stills LoRA row accepted under `Z-Image`, refused (preview error) under `Qwen` | every cell as the table; Z-Image is selectable only in shots with a seed (upload or folder); no console error |
| L6 | chained mode with an uploaded seed, with and then without a picked character: open the Stills engine select, then Run all with the default Qwen model | the select's options; the preview command; `seed_edit.json` and Phase 1c in the log | the select shows only `The seed: …` (disabled) and no Z-Image; the command has `--seed-edit-model qwen21-q4`; Phase 1c runs as before |

---

## 6. Risks (rulings)

- **R1 Look mismatch:** panel 1 is the photo, panels 2..N are Z-Image renders; the cut from photo to render is visible. Accepted; the user chose it.
- **R2 Identity:** a seed person without a LoRA is drawn from text alone on every panel; Z-Image never sees the seed. The restored identity sentences are the only anchor (L1 measures).
- **R3 Engine flips on an existing story** (Compose rerun, batch "New stills" fork): story.md is reused; a Qwen-planned story lacks the identity sentences; Phase 2 warns and continues. `--force-story` fixes it.
- **R4** Panel 1's group runs on every Phase 2 (one extra process start).
- **R5** `--cast-refs-model`'s refusal text ("already a Qwen edit of the seed") is inaccurate on the as-is path (F4).

## 7. Follow-up scopes (optional; not part of this work)

- **F1 (closed by the user, Q1):** no per-clip Z-Image first frame for text-to-video; chained mode's Z-Image panel 1 is the first-frame path, unchanged.
- **F2 characters in text-to-video (C2):** refused today ("casting needs the chained flow"). Optional. Since Q1 rules out a per-clip still pipeline, this would mean video-only cast LoRAs on text-to-video clips; not part of this work.
- **F3 (closed by the user, Q2):** no Z-Image in chained mode with a seed; Z-Image cannot edit a seed, so that cell stays as-is or Qwen.
- **F4 (optional)** `--cast-refs-model` on the Z-Image seed path (panels 2..N), with an accurate refusal text until then.

## 8. Amended requirements of earlier specs

[SE] SE2 (as-is refused in shots) → ZE2. SE4 helps → E10/E11. SE8 dispatch → E4. SE20 Phase 0 text → E8. SE23 → U1. SE31 → U6. [SE] §0.1 rule 6 still holds: Z-Image makes every image made from text. [SI] SI1's "set whenever --seed-image is given" → not on the Z-Image path (E7). [CX] CXT1's as-is case → E15. [QE] QE67 → U3 (the engine resets to Qwen with every new seed).

## 9. Open questions: decided by the user (2026-11-11)

- **Q1 (decided):** in text-to-video, a Z-Image still as the first frame meant either every clip's own first frame (a new pipeline) or panel 1 then a chain (today's Chained mode). **Decision:** keep chained mode's Z-Image panel-1 first frame exactly as it is today, build no per-clip first-frame pipeline, and give the Qwen-or-Z-Image selection to shots mode only. F1 is closed.
- **Q2 (decided):** in chained mode with a seed, should Z-Image replace the seed as panel 1? **Decision:** no. Z-Image has no edit capability, so every cell that edits a seed (chained with a seed, with or without characters) stays Qwen (or as-is), and the Z-Image engine is not offered there (SZ16, L6). F3 is closed.
- No open question remains for this work; F2 and F4 are optional follow-ups.

---

## Plan

### Before Task 1 (orchestrator)
1. Snapshot (house rule): `tar czf $S/snapshot-pre-sz-e8d7f3a.tgz -C $S/sz-wt --exclude generated .`; at least 20 GiB free on the disk holding `WS`.
2. Record the baseline at `e8d7f3a` with the usual gate (`zsh $S/<baseline dir>/gate-run.sh 0`) and `python3 tests/test_ltx_movie_offline.py`.

### Task 1: the Z-Image seed path in `bin/ltx-movie` (one commit)
- [ ] E1-E16 (Section 3, Task 1).
- [ ] `python3 -B -m pytest -q -p no:cacheprovider tests/test_ltx_movie_shots_zimage.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_ltx_movie_seed_context_frame.py tests/test_ltx_movie_cast_refs.py tests/test_shots_mode.py tests/test_seeded_no_identity.py tests/test_story_engine.py -k "sz or set or cxt or crt or s33 or sit or rst50" 2>&1 | tail -1`: 0 failed; `python3 tests/test_ltx_movie_offline.py`: same `OK n/n` as the baseline.
- [ ] `git add bin/ltx-movie tests/test_ltx_movie_shots_zimage.py tests/test_ltx_movie_shots_seed.py tests/test_ltx_movie_seed_context.py tests/test_shots_mode.py`; `git diff --cached --name-only` is exactly those five; `git commit -m "bin/ltx-movie: --shots --seed-image --seed-edit-model as-is keeps the seed as panel 1 and renders every other still with Z-Image (shots-zimage ZE1-ZE10)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`. The gate then loses only `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`.

### Task 2: the Compose engine picker and V1 (one commit)
- [ ] U1-U11 (Section 3, Task 2), with SZ16 in `tests/test_movie_ui_shots_zimage.py`.
- [ ] `python3 -B -m pytest -q -p no:cacheprovider tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seams.py tests/test_movie_ui_batch.py 2>&1 | tail -1`: 0 failed.
- [ ] `git add movie_ui_lib.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_shots_zimage.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_checks.py tests/test_movie_ui_seedfolder.py`; exactly those seven staged; `git commit -m "movie-ui: one Stills engine picker on every Compose cell; Z-Image for a seeded shots movie (shots-zimage ZE11-ZE14)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Task 3: the `test_mut26` re-baseline (a test-only commit; never amend)
- [ ] `SHA=$(git log -1 --format=%H -- bin/ltx-movie)` (Task 1's commit); `git diff --quiet $SHA HEAD -- bin/ltx-movie` exits 0; `git diff --name-only e8d7f3a $SHA -- <PIPELINE_FILES>` lists only `qwen-agent-workspace/bin/ltx-movie`.
- [ ] In `tests/test_movie_ui_builder.py`: the comment's end `then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted).` becomes `then to 3d5e345f788b262cc51c6d961f0c1d9737e163fc (audio-only-quoted), then to SHA (shots-zimage).` and `    BASELINE = "3d5e345f788b262cc51c6d961f0c1d9737e163fc"` becomes `    BASELINE = "SHA"` (the 40 characters of `$SHA`).
- [ ] `git diff --stat` is `1 file changed, 2 insertions(+), 2 deletions(-)`; `pytest -k mut26` passes; commit only that file: `git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the shots-zimage commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`. Merge with a merge commit (a squash would orphan BASELINE).

### Verification (orchestrator, not the executor)
- **V1:** the full gate after each task; after Task 3, SZK1.
- **V2:** SZK2; an Opus design review of the branch diff against this spec is clean.
- **V3:** L1-L6 (Section 5), run by the user on macstudio; push and merge only on the user's go.
