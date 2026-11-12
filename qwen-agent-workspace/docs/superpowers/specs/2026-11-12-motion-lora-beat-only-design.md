# Motion LoRA is beat-only: a catalog motion video LoRA is only ever a per-beat pick, as a style video LoRA is only ever a global pick; a saved global or either scope on a motion entry loads as beat with a warning, a new write of one is refused, and a global physics LoRA may share a panel with a per-beat motion LoRA

Date: 2026-11-12

Status: design spec and implementation plan in one document.

**The user's problem (confirmed):** a motion video LoRA (for example the fight LoRA) changes the movement of every panel it is applied to, so it belongs on the beats that need it, never on the whole movie. Since lora-scope (`docs/superpowers/specs/2026-11-10-lora-scope-design.md`, LS1-LS9 and fix round A1-A4) a motion entry may still be scoped `global` or `either`. And two related things confuse the user today:
- A scope value that the catalog rules forbid makes **the whole catalog file** fail to load (every auto-LoRA run stops with `Error: invalid LoRA catalog ...`).
- The advisory L3 counts motion and physics together, so a global physics LoRA (rain) plus a per-beat motion LoRA (fight) is flagged.

**The user's decisions (binding):**
- A motion video LoRA is always a per-beat pick, as a style video LoRA is always a global pick (A1). Global picks may only be style or physics LoRAs.
- Physics keeps the scopes `global`, `beat` and `either`; its default stays `beat`. Style does not change: it is always global. A stills entry's scope is still accepted and ignored.
- Rule L3 counts only kind `motion`, so a global physics LoRA plus a per-beat motion LoRA is not flagged. The planner paragraph is made to match.
- On load, a motion video entry saved with the scope `global` or `either` does not make the catalog fail. Its effective scope is `beat`, and a one-line warning is printed. A new write of such a scope (`bin/lora-catalog add` and `scope`, `POST /api/loras`, `POST /api/loras/scope`) is refused, with a message like the style one.
- The movie UI's LoRAs tab shows no Scope select for a motion row, as for a style row. The add form's Scope select is disabled for kind motion, as for kind style.
- `entry_scope()` returns `beat` for every motion video entry.
- L8 does not change. A motion entry picked globally now becomes an L8 violation; its message already reads `may only be a per-beat pick`.

**This spec:**
- makes `entry_scope` return `beat` for every motion video entry, gives `validate_entry` a `for_write` flag that refuses a non-beat motion scope, and adds `MOTION_SCOPE_WARNING` and `scope_warnings` (MB1-MB4);
- prints the warning in bin/ltx-movie, `bin/lora-catalog list` and `verify`, and the movie UI's LoRAs tab (MB4);
- splits L3 into a motion count and a physics count, and rewrites the paragraph and the re-check hint to match (MB5, MB6);
- **relaxes the per-panel limit of bin/ltx-story-manifest and bin/ltx-mlx-render** from "one style and one motion-or-physics" to "one of each kind". Without this, the combination the user asked for would still fail in Phase 3 (MB7, and finding F-1 below);
- changes the movie UI's add route, form and catalog table (MB8);
- re-baselines `test_mut26` (MB9).

Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Worktree `$S/mb-wt`, branch `motion-beat-only`, at `4dacff2` (Merge PR #21, shots-zimage). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number is verified at `4dacff2`.
- `/Users/reubenpatterson/local_agent_harness` is never touched, except through the worktree.

**IDs.** Requirements **MB1-MB9**, tests **MB-T1-MB-T9**, KPIs **MBK1-MBK6**, live checks **MB-LV1-MB-LV6**, behaviour changes **C1-C12**, edits **E1-E52**. At `4dacff2`, `git grep -nE "\bMB[0-9]+\b|MB-T[0-9]|MBK[0-9]|MB-LV[0-9]"` finds nothing in code or tests.

**Terms.** A **video entry** has `target` `video`. The **effective scope** of an entry is `lora_catalog.entry_scope(entry)`. A **legacy motion scope** is a `scope` key of `global` or `either` on a motion video entry. Before this change it was valid and could be written by `bin/lora-catalog add --scope`, `bin/lora-catalog scope` or the movie UI.

---

## 0. Scope

### 0.1 What happens today (verified at `4dacff2`)

- **The catalog rules.** `lora_catalog.validate_entry` (`lora_catalog.py:86-155`) first checks that `scope` is in `SCOPES` (`:118-119`). Then, for a style video entry, it requires `global` (`:120-124`), with the message `entry <id>: scope must be global for a style LoRA, which applies to every panel, got <repr>; edit catalog.json by hand: remove the scope key or set it to global` (lora-scope review S1, `ba48a1a`). A motion entry may hold any of the three scopes.
- **One function for every check.** The same `validate_entry` is called by:
  - `validate_catalog` (`:169-190`), which runs from `load_catalog` (`:193-209`) and from `save_catalog` (`:212-215`);
  - `bin/lora-catalog` `cmd_add` (`bin/lora-catalog:222`).
  
  So any rule added unconditionally to `validate_entry` is also a load rule, and one bad entry fails the whole file.
- **`entry_scope`** (`lora_catalog.py:157-166`) returns `global` for every style video entry, else `entry.get("scope") or DEFAULT_SCOPES[kind]`. A motion entry scoped `global` or `either` is therefore listed under `May be global picks` (`catalog_groups`, `story_engine.py:1079-1093`). It passes L8 as a global pick (`story_engine.py:2789-2796`), and `drop_duplicate_picks` (`story_engine.py:1437-1467`) keeps its global copy.
- **Its callers** (`git grep -n entry_scope`):
  - `story_engine.py:1084` (`catalog_groups`), `:1442` (`drop_duplicate_picks`), `:2791` and `:2795` (L8);
  - `bin/lora-catalog:244` (the SCOPE cell of `list`) and `:336` (`scope ID default` output).
- **The scope constants.**
  - `DEFAULT_SCOPES` (`lora_catalog.py:46`) is read only by `entry_scope` and LST1 (`tests/test_lora_scope_catalog.py:69`).
  - `OPTIONAL_ENTRY_KEYS` (`:44`) is read by `validate_entry:99` and LST1 `:70`.
  - `SCOPES` (`:45`) is read by `validate_entry:118`, `bin/lora-catalog:103` and `:119` (argparse choices), LST1 and LST10 (`tests/test_lora_scope_ui.py:41`).
  - `movie_ui_server.LORA_SCOPES` (`movie_ui_server.py:1288`) is used by `_h_lora_add:1247` and `_h_lora_scope:1296`.
  - `LORA_SCOPE_DEFAULTS` (`static/movie-ui/app.js:9`) is used by `scopeCell` (`app.js:2942`), and LST11 compares it with `DEFAULT_SCOPES`.
  - `LORA_SCOPE_GLOBAL` and `LORA_SCOPE_BEAT` (`story_engine.py:603-608`) are the L8 messages. None of these constants changes.
- **The writers.**
  - `bin/lora-catalog add` refuses a scope on a stills entry (`:147-149`) and `beat` or `either` on a style entry (`:150-152`) before it reads anything. It validates the new entry at `:222`.
  - `cmd_scope` refuses a stills entry (`:318-319`) and `beat` or `either` on a style entry (`:320-322`), then saves (`:327-329`).
  - `_h_lora_add` refuses kind `style` with scope `beat` or `either` with 400 `scope must be global or null for a style LoRA` (`movie_ui_server.py:1249-1250`).
  - `_h_lora_scope` (`:1291-1298`) never reads the catalog and passes the request to `bin/lora-catalog scope`.
- **The readers.**
  - bin/ltx-movie loads the catalog once, in `_resolve_story_engine` (`bin/ltx-movie:1478-1486`).
  - bin/lora-catalog loads it in `add` (`:183`), `list` (`:251`), `remove` (`:284`), `scope` (`:311`) and `verify` (`:345`).
  - bin/lora-check loads it at `:355` and `:375`.
  - The movie UI reads it through `bin/lora-catalog list --json` (`_h_loras`, `movie_ui_server.py:1183-1197`). The server parses stdout only, and on exit 0 it ignores stderr (`tool_result`, `:1155-1161`).
- **L3** (`story_engine.py:2824-2827`): `beat <k>: L3 motion: <n> motion or physics LoRAs on this panel (<labels>); at most 1`. It is advisory, and it counts pins, global picks and per-beat picks whose kind is `motion` or `physics`.
- **The paragraph** (`LORA_PICK_PARAGRAPH`, `story_engine.py:586-596`) says that global holds `at most one style LoRA, plus motion or physics LoRAs that suit the whole movie`, and that `every beat may have at most one motion or physics LoRA in total, counting global`.
- **The hint** (`RECHECK_SCOPE_HINT`, `story_engine.py:617-621`) says `give a motion or physics LoRA the scope either`.

**Finding F-1 (not in the brief; it decides MB7).** After L3, Phase 3 builds each panel's list (`_catalog_panel_loras`, `bin/ltx-movie:2056-2092`), and then two more checks refuse a panel that holds more than one non-style catalog LoRA:
- `bin/ltx-story-manifest:272-274` exits 2 with `Error: --catalog-loras <path>: panel <k> has more than one style or motion/physics LoRA`;
- `bin/ltx-mlx-render:294-297` raises `panel <k>: catalog_loras has more than one style or motion/physics LoRA`.

L3 is only advisory, so today a plan with a global physics pick and a per-beat motion pick on the same beat passes the story checks. bin/ltx-movie writes `catalog_loras.json`, and bin/ltx-story-manifest then stops Phase 3. Relaxing L3 alone would remove the only early sign of this failure and leave the render broken. Both checks are therefore changed to "at most one LoRA of each kind" (MB7).

`build_units` (`bin/ltx-mlx-render:374-386`) already puts every motion and physics catalog entry first, in manifest order. The fuser sums the weights (robust-story spec, amendment at its LC17), so the order of two lead entries does not change the pixels.

### 0.2 Grounding: the pins this change must respect (verified at `4dacff2`)

- **`test_mut26`** (`tests/test_movie_ui_builder.py:272-302`, BASELINE `d87b6fe2e3523a09304b53c7d0b8bc448c6514f4` at `:293`, comment chain ending at `:291`). `PIPELINE_FILES` (`:223-228`) pins `bin/ltx-movie`, `bin/ltx-mlx-render`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-story-video`, `bin/ltx-chain`, `bin/ltx-generate`, `bin/ltx-host-prep`, `bin/ltx-host-restore`, `bin/character`, `bin/lora-catalog`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`, `bin/iterate-story`, `bin/qwen-agent`, `story_engine.py`, `character_lib.py`, `character_dataset.py`, `lora_catalog.py`, `pipeline_log.py`, `z_image_skill.py` and `ltx2_mlx_video_skill.py`.
  - This change edits six pinned files: `lora_catalog.py`, `bin/lora-catalog`, `story_engine.py`, `bin/ltx-movie`, `bin/ltx-story-manifest` and `bin/ltx-mlx-render`. So `test_mut26` fails from Task 1's commit until Task 3 moves BASELINE to Task 1's commit. Task 1 is the last commit that changes a pinned file; Task 2 changes only unpinned UI files.
  - `movie_ui_server.py` is not pinned. It is in `NEW_PY` (`:212`), so `test_mut25` compiles it with `/usr/bin/python3` and scans it. The new line uses none of the forbidden constructs.
  - `static/movie-ui/*` is in no pin list.
- **Merge commit only.** BASELINE names Task 1's commit, and a squash or rebase merge would orphan it.
- **Text pins that change.**
  - `LORA_PICK_PARAGRAPH` is pinned word for word by LST4 (`tests/test_lora_scope.py:100-109`) and PJT1 (`tests/test_per_beat_json.py:94-102`). PJT1's `CLAUSE` (`:30-32`, the per_beat clause) stays word for word, so PJT4 (`:176`) does not change.
  - `RECHECK_SCOPE_HINT` is pinned by the `HINT` literal of `tests/test_lora_scope.py:38-42` (LST8). LST15 reads the constant itself.
  - The L3 text is pinned by RST15 (`tests/test_story_engine.py:490-491`), RST31 (`:1481-1482`) and LCT28 (`:1518-1519`).
  - The UI note is pinned by LST13 (`tests/test_lora_scope_fix.py:173-176`). The `syncLoraScope` line is pinned by LST11 (`tests/test_lora_scope_ui.py:96-97`).
  - The manifest and render messages are pinned by LCT16 (`tests/test_lora_catalog.py:860-861`) and LCT19 (`:1025-1026`).
- **No sha or length pin covers the changed prompt text.**
  - The sha pins in `tests/test_chained_end_frames.py` cover `plan_reference` (CT2, `:409-416`) and `FORMAT_REFERENCE` (CT14, `:1126-1130`). Neither contains `LORA_PICK_PARAGRAPH`: `build_plan_prompt` inserts the paragraph separately (`story_engine.py:1277-1279`).
  - `test_pbt2` (`tests/test_plan_budget.py:113-130`) pins `plan_tokens`, which does not depend on the paragraph's length.
  - No golden fixture contains `counting global`, `suit the whole movie` or `motion or physics` (`git grep` over `tests/fixtures` and `scripts`).
- **Braces.** RST8, RST47 and LST4 forbid `{` and `}` in the plan prompt outside the chained format reference. The new texts have none.
- **Tests that use a motion entry scoped `either` or `global`** (`git grep -nE 'scope="(either|global)"|fast="(either|global)"' tests`). Under MB2 these entries are read as `beat`, so each test listed here is edited (Section 5):
  - RST15's `_lora_ctx` (`tests/test_story_engine.py:447`), `_lora_state` (`:1457`) used by RST31 and LCT28, and DLG18 (`tests/test_dialogue.py:1405`);
  - LST1, LST2 and LST3 (`tests/test_lora_scope_catalog.py:78`, `:111-115`, `:156-162`);
  - LST5 and LST8 (`tests/test_lora_scope.py:158-164`, `:262-277`);
  - LST15 (`tests/test_lora_scope_fix.py:265`);
  - LST10 (`tests/test_lora_scope_ui.py:42-53`; a motion add with `either` now gets 400).
  
  LST6 (`tests/test_lora_scope.py:178`) also gives fast-motion `either`, but it only normalizes plans and checks film-grain, so it passes unchanged.
- **Listed in the brief and checked; none needs a change:**
  - `tests/test_narrative_fidelity.py`, `tests/test_ltx_movie_offline.py`, `tests/test_ltx_movie_iterate_flags.py`, `tests/test_vlm_lifecycle.py` and `tests/test_location_lib.py` have no catalog scope, no L3 text, no `LORA_PICK_PARAGRAPH` and no manifest catalog limit.
  - `tests/test_location_story.py::test_ls10` (`:261-276`) only asserts that there is no L3, and it still gets none.
  - The RST50 and offline literal counts in bin/ltx-movie are not touched: the new lines hold none of the counted literals. No import is added (L7j).
  - The route count (`len(srv.ROUTES) == 64`) does not change.

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `lora_catalog.py` | **yes** | 1 | `validate_entry(entry, for_write=False)`, the `entry_scope` motion rule, `MOTION_SCOPE_WARNING`, `scope_warnings`, the comment (MB1-MB4) |
| D2 | `bin/lora-catalog` | **yes** | 1 | `add` and `scope` validate with `for_write=True`; `list` and `verify` print the warnings; docstring and help (MB3, MB4) |
| D3 | `story_engine.py` | **yes** | 1 | `LORA_PICK_PARAGRAPH`, `RECHECK_SCOPE_HINT` and its comment, L3 (MB5, MB6) |
| D4 | `bin/ltx-movie` | **yes** | 1 | `_resolve_story_engine` prints the warnings (MB4) |
| D5 | `bin/ltx-story-manifest` | **yes** | 1 | one LoRA of each kind per panel (MB7) |
| D6 | `bin/ltx-mlx-render` | **yes** | 1 | the same (MB7) |
| D7 | `tests/test_motion_beat_only.py` | no | 1 | new: MB-T1-MB-T6 |
| D8 | `tests/test_story_engine.py`, `tests/test_dialogue.py`, `tests/test_per_beat_json.py`, `tests/test_lora_scope.py`, `tests/test_lora_scope_catalog.py`, `tests/test_lora_scope_fix.py`, `tests/test_lora_catalog.py` | no | 1 | the edits of Section 5.2, including MB-T7 |
| D9 | `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js` | no | 2 | the motion 400, the warning box, the motion Scope cell, `syncLoraScope`, the note (MB4, MB8) |
| D10 | `tests/test_motion_beat_only_ui.py` | no | 2 | new: MB-T8, MB-T9 |
| D11 | `tests/test_lora_scope_ui.py`, `tests/test_lora_scope_fix.py` | no | 2 | LST10, LST11 and LST13 follow MB8 |
| D12 | `tests/test_movie_ui_builder.py` | no | 3 | only `test_mut26`'s BASELINE and comment chain |

Untouched: `bin/lora-check`, `bin/ltx-story-images`, `movie_ui_lib.py`, `character_lib.py`, `location_lib.py`, `scripts/deploy/*`, every other bin and every other test.

### 0.4 Out of scope

- Coercing a style entry's forbidden scope at load. A style video entry with `beat` or `either` still fails the catalog, exactly as today, because the user said style does not change (open question Q3).
- Rewriting catalog.json. No reader changes the file. A legacy motion scope stays in the file until the user runs `bin/lora-catalog scope ID default` (or `beat`), and it survives saves for other entries.
- Warnings in bin/lora-check (open question Q5).
- Re-normalizing a saved `plan.json`. A saved global motion pick is checked as it is (C2).
- A scope for pins (`--lora`), character LoRAs, location LoRAs, stills entries or `--stills-lora`. A pinned motion LoRA still applies to every panel, and it is counted by L3 motion.
- Changing the style refusals of `bin/lora-catalog` and the movie UI (open question Q4).
- The look of a panel with a motion and a physics LoRA stacked. That is a live A/B check (MB-LV4); the tests never render.
- Any model call, server, render or download in tests, and any access to the user's Mac.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| MBK1 | The full suite has no failure beyond the baseline. Every test that passes at `4dacff2` passes after Task 3, and the 9 new tests (MB-T1-MB-T6, MB-T8, MB-T9; MB-T7 is assertions in existing tests) pass | gate (Plan, "Verification") |
| MBK2 | A catalog.json with a motion video entry scoped `global` or `either` loads in every reader: `bin/ltx-movie` (auto LoRA), `bin/lora-catalog list`, `list --json`, `verify`, `add`, `remove` and `scope`, and `GET /api/loras` (200). bin/ltx-movie, `list`, `verify` and the LoRAs tab show exactly one warning line per such entry, with the exact text of Section 3 | MB-T1, MB-T2, MB-T6, MB-T9 |
| MBK3 | Every new write of a non-beat scope on a motion video entry is refused, and catalog.json stays byte-identical: `bin/lora-catalog add` and `scope` exit 2 with the exact message, and `POST /api/loras` answers the exact 400 and runs nothing | MB-T2, MB-T8 |
| MBK4 | A plan with a global physics pick and a per-beat motion pick on the same beat gets no L3 and no L8. Phase 3 writes `catalog_loras.json` with both on that panel, and bin/ltx-story-manifest and bin/ltx-mlx-render accept that panel | MB-T3, MB-T5, MB-T6, MB-T7 |
| MBK5 | A motion pick in `loras.global` is always the hard L8, whatever the entry's saved scope. The plan prompt lists every motion entry only under `May be per-beat picks` | MB-T3, MB-T6 |
| MBK6 | On the user's Mac: `bin/lora-catalog list` shows `beat` for every motion entry, and a warning for each legacy motion scope until it is cleared. A new plan for the fight story never has the fight LoRA in `loras.global`. A physics plus motion beat renders | MB-LV1-MB-LV6 |

Every MB requirement and every MB-T test is a must-have. There are no nice-to-haves.

---

## 1. Decisions

1. **A motion video entry's effective scope is always `beat` (the user's decision) [MB2].** `entry_scope` returns `beat` for it, before it reads `scope`. So `catalog_groups`, L8, `drop_duplicate_picks` and `bin/lora-catalog list` follow with no code change:
   - a motion entry is never listed under `May be global picks`;
   - its global pick is the hard `plan: L8 scope: '<id>' may only be a per-beat pick (its catalog scope is beat), ...`;
   - a global-and-per-beat duplicate keeps the per-beat copies (`LORA_DUPLICATE_GLOBAL`);
   - `list` shows `beat`.

   This mirrors A1, where `entry_scope` returns `global` for every style video entry. A stills motion entry still has no effective scope (`None`).

2. **Load-time coercion and write-time refusal share one validator through a flag [spec choice] [MB3].**
   - `validate_entry(entry, for_write=False)` keeps every rule it has today. Only with `for_write=True` does it also refuse a motion video entry whose `scope` is present and not `beat`. The message mirrors the style one: `entry <id>: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got <repr>`.
   - `validate_catalog`, and so `load_catalog` and `save_catalog`, keep calling `validate_entry(entry)` with the default `False`. A legacy motion scope therefore loads, and it survives a save that changes another entry: `remove`, an `add` of another entry, or `scope` on another entry. No reader or writer rewrites a value the user did not ask to change.
   - The two writers that build one new entry call `validate_entry(entry, for_write=True)` on that entry only: `bin/lora-catalog add` (at `:222`, in place of today's call) and `bin/lora-catalog scope` (a new call before its save).
   - **Why a flag, and not a separate check in each writer:** the brief requires the refusal to live in `validate_entry`. A flag keeps one rule and one message for both CLI writers, and it changes nothing for the six existing callers.
   - **Why not reject at load, as for style:** that is exactly the whole-catalog failure the user complained about.
   - **The refusal in `add` comes after the file checks [spec choice].** Like today's `validate_entry` call at `:222`, it runs after the header, rank, alpha and architecture checks. So its stderr starts with the `arch: ...` line that `add` already prints, and then the `Error:` line. An earlier, argparse-time check with its own wording would duplicate the rule, and the brief asks for the `validate_entry` message.
   - **The server mirrors the rule [spec choice].** `movie_ui_server.py` never imports lora_catalog (movie-ui GC7), so `_h_lora_add` gets its own 400 `scope must be beat or null for a motion LoRA`, mirroring `scope must be global or null for a style LoRA`, and runs nothing. `POST /api/loras/scope` does not change. The server never knows an entry's kind, so `bin/lora-catalog scope` refuses (exit 2), and the route returns that run with 200, as for every refused run (LS7). The UI never sends such a request, because a motion row has no select (MB8).

3. **The warning is one constant and one function in lora_catalog, printed by each reader [spec choice] [MB4].**
   - `MOTION_SCOPE_WARNING` is `catalog entry %s has the scope %s, but a motion LoRA is only ever a per-beat pick, so it is read as beat; clear it with bin/lora-catalog scope %s default`.
   - `scope_warnings(entries)` returns one string per motion video entry whose `scope` is set and is not `beat`, in the order of `entries`.
   - The readers print it as follows:
     - **bin/ltx-movie:** stderr, `Warning: <text>`, once per run, right after `_resolve_story_engine` loads the catalog. This covers Phase 1 (the planner), Phase 2, Phase 3 and the dry run, because each of them uses `args.story_catalog`. With `--no-auto-lora` the catalog is not loaded, so nothing is printed.
     - **bin/lora-catalog:** stderr, `warning: <text>` (lowercase, like its low-RAM `warning:` at `:181`), in `list` (table and `--json`) and in `verify`, right after the load and before any stdout line. `add`, `remove` and `scope` print none: they are writes, and `scope ID default` is the fix itself. `list --json` stdout stays pure JSON, so `GET /api/loras` is unaffected.
     - **The LoRAs tab:** a box `<div id="l-scope-warnings" class="warning" hidden>` above the catalog table holds one `<div>` per warning, `Warning: <text>`. `app.js` builds it from the raw entries that `GET /api/loras` returns: `list --json` returns raw entries, so the saved `scope` is visible. `motionScopeWarning(e)` mirrors `MOTION_SCOPE_WARNING`, and MB-T9 compares the two texts.
   - The text names the one command that clears it. `scope ID beat` also clears it, but `default` removes the key, which is what an entry without a legacy scope looks like.

4. **L3 counts motion and physics apart [spec choice for physics] [MB6].**
   - The user's rule: L3 counts only kind `motion`, giving `beat <k>: L3 motion: <n> motion LoRAs on this panel (<labels>); at most 1`.
   - **Physics proposal (minimal): at most one physics LoRA per panel too**, as a second L3 message, `beat <k>: L3 physics: <n> physics LoRAs on this panel (<labels>); at most 1`. It is advisory like L3 today. The reasons:
     - Today the per-panel cap for physics is already 1, because the combined motion-or-physics cap of L3, the manifest and the renderer includes physics. Counting the two kinds apart allows exactly the one new combination the user asked for (one motion with one physics) and loosens nothing else.
     - The manifest and the renderer have to change anyway (F-1). Capping each kind at one keeps their rule uniform ("one LoRA of each kind") instead of special-casing physics.
     - Two stacked physics LoRAs have never been rendered here. Allowing them would be a new, untested capability that nobody requested.
     - No new violation id: it is L3 with the name `physics`. `parse_violation` reads it unchanged, and no list of L ids needs editing.
   - The order is motion first, then physics, then L4, for each beat. Pins count by their `kind`, as today; character and location LoRAs are never counted.

5. **The paragraph says what the checks enforce [MB5].**
   - The global sentence becomes `at most one style LoRA, plus at most one physics LoRA that suits the whole movie`. Motion is gone from it, and "at most one" follows from Decision 4, because a global pick is on every beat. This differs from the brief's wording, "physics LoRAs that suit the whole movie": with a cap of one physics LoRA per beat counting global, a plural would invite an L3 physics advisory on every beat (open question Q1).
   - The per-beat sentence becomes `every beat may have at most one motion LoRA and at most one physics LoRA, counting global`.
   - The per_beat clause (PJT1's `CLAUSE`) and every other word stay.

6. **The re-check hint stops suggesting `either` for a motion LoRA [MB5].** It becomes: give a **physics** LoRA the scope either, or pass --force-story; a style LoRA is only ever global and a motion LoRA only ever per-beat, so a style LoRA picked for a beat or a motion LoRA picked globally needs `--force-story`. The re-check (`story_engine.py:5689-5690`) and `_catalog_checks_error` (`bin/ltx-movie:2025-2027`) print it unchanged.

7. **One of each kind per panel in Phase 3's two downstream checks [MB7].** bin/ltx-story-manifest and bin/ltx-mlx-render refuse a panel with more than one entry of the same kind (`style`, `motion` or `physics`). The message names the rule:
   - manifest: `panel <k> has more than one LoRA of the same kind (style, motion or physics)`;
   - renderer: `panel <k>: catalog_loras has more than one LoRA of the same kind (style, motion or physics)`.

   Two style entries and two non-style entries of the same kind stay refused. Only a motion entry with a physics entry is newly accepted. `build_units`, `_catalog_panel_loras` and `catalog_loras.json`'s shape do not change.

8. **The movie UI [MB8].**
   - A motion video row's Scope cell is the text `beat` with no select, as a style row shows `global`.
   - The add form's Scope select is enabled only when Target is `video` **and** Kind is `physics`; a disabled select sends `scope: null` (today's line).
   - The note under the field says this. `LORA_SCOPE_DEFAULTS` does not change.

9. **Three tasks [spec choice].** Task 1 is every pinned file plus their tests (one commit). Task 2 is the movie UI (one commit). Task 3 moves BASELINE to Task 1's commit (a test-only commit, never amended). Each code task has its own new test file, so its gate sees only the tests its code makes pass.

---

## 2. Requirements

- **MB1 (the rule).** A motion video entry is only ever a per-beat pick. Global picks come only from style entries and from physics entries whose effective scope is `global` or `either`. Physics keeps `SCOPES` and its default `beat`. Style stays as A1 left it. A stills entry's scope is accepted and ignored. `SCOPES`, `DEFAULT_SCOPES`, `OPTIONAL_ENTRY_KEYS`, `ENTRY_KEYS` and `SCHEMA_VERSION` do not change.
- **MB2 (`entry_scope`).** `lora_catalog.entry_scope(entry)`:
  - returns `None` when `entry["target"] != "video"` or the kind is not in `DEFAULT_SCOPES`;
  - else `"global"` for kind `style`;
  - else `"beat"` for kind `motion`;
  - else `entry.get("scope") or DEFAULT_SCOPES[kind]`.
- **MB3 (`validate_entry`).** `validate_entry(entry, for_write=False)`. With `for_write` true, after the style check: a video entry of kind `motion` whose `scope` is present and not `"beat"` raises `CatalogError("entry <id>: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got <repr>")`. A value outside `SCOPES` still gets the generic message first. With `for_write` false, nothing changes.
  - `bin/lora-catalog add` calls `validate_entry(entry, for_write=True)` at `:222`.
  - `bin/lora-catalog scope` calls `validate_entry(entry, for_write=True)` on the changed entry, inside the `try` before `save_catalog`. The `except lora_catalog.CatalogError` already there prints it with `Error: ` and returns 2, and nothing is written.
- **MB4 (the warning).**
  - `lora_catalog.MOTION_SCOPE_WARNING` and `lora_catalog.scope_warnings(entries)` are defined as in Decision 3. `scope_warnings` keeps an entry when `target == "video"`, `kind == "motion"` and `entry.get("scope", "beat") != "beat"`, and formats it with `(id, scope, id)`.
  - bin/ltx-movie's `_resolve_story_engine` prints `Warning: <text>` to stderr for each item of `scope_warnings(args.story_catalog["entries"])`, after a successful load.
  - `bin/lora-catalog list` and `verify` print `warning: <text>` to stderr for each item of `scope_warnings(entries)`, where `entries` is the whole loaded catalog (before `list --model` filters it), right after the load.
  - The LoRAs tab shows the box of Decision 3 after each successful `GET /api/loras`. The box is cleared and hidden at the start of every table load, and stays hidden when there is no warning or the request fails.
- **MB5 (the texts).** `LORA_PICK_PARAGRAPH` and `RECHECK_SCOPE_HINT` are the texts of Section 3.
- **MB6 (L3).** In `lora_checks`, for each beat k, the motion labels and the physics labels of `loras_k` are counted apart. For each of `("motion", "physics")` in that order, when there are more than 1, the advisory is `beat <k>: L3 <kind>: <n> <kind> LoRAs on this panel (<labels joined by ", ">); at most 1`. L4 and L6 follow as today.
- **MB7 (Phase 3).** bin/ltx-story-manifest's `_read_catalog_loras` and bin/ltx-mlx-render's `load_manifest` refuse a panel list with more than one entry of any one kind in `("style", "motion", "physics")`, with the messages of Decision 7.
- **MB8 (the movie UI).** `_h_lora_add`: after the style check, kind `motion` with scope `global` or `either` is 400 `scope must be beat or null for a motion LoRA`, and nothing runs. app.js and index.html as Section 3.
- **MB9 (nothing else changes).** L1, L2, L4-L8, `catalog_groups`, `drop_duplicate_picks`, `normalize_plan`, the critic, `apply_patches`, the plan budget, `catalog_loras.json`, `build_units`, pins, characters, locations, stills, `bin/lora-catalog remove`, `list --json` stdout, the route table and every exit code not named in Section 4 behave as today. A catalog without a legacy motion scope produces no warning anywhere and loads, lists and saves byte-identically.

## 3. Messages and text (exact)

| Constant or place | Text | Where |
|---|---|---|
| `lora_catalog.MOTION_SCOPE_WARNING` | `catalog entry %s has the scope %s, but a motion LoRA is only ever a per-beat pick, so it is read as beat; clear it with bin/lora-catalog scope %s default` (id, scope, id) | the base text of every warning |
| bin/ltx-movie | `Warning: ` + the text | stderr, once per entry per run |
| bin/lora-catalog `list`, `verify` | `warning: ` + the text | stderr, once per entry per command |
| LoRAs tab | `Warning: ` + the text, one `<div>` per entry in `#l-scope-warnings` | above the catalog table |
| `validate_entry(..., for_write=True)` | `entry %s: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got %r` (id, scope) | `CatalogError`; bin/lora-catalog prints `Error: ` + it, exit 2 |
| `_h_lora_add` | `scope must be beat or null for a motion LoRA` | 400 |
| L3 motion | `beat %d: L3 motion: %d motion LoRAs on this panel (%s); at most 1` | advisory |
| L3 physics | `beat %d: L3 physics: %d physics LoRAs on this panel (%s); at most 1` | advisory |
| `LORA_PICK_PARAGRAPH` | `an object with the keys global, per_beat and stills. Each pick is an object with the keys id and strength, taken from the LoRA catalog below; strength must lie inside that entry's range. The catalog lists each LoRA under the places where it may go. global is a list of picks applied to every panel, taken only from the LoRAs that may be global picks: at most one style LoRA, plus at most one physics LoRA that suits the whole movie. per_beat maps each beat number to a list of picks for that beat only, taken only from the LoRAs that may be per-beat picks, and each key is the beat number alone in double quotes: the key of beat 1 is "1"; a LoRA in global is never also in per_beat, and every beat may have at most one motion LoRA and at most one physics LoRA, counting global. stills is a list of at most one stills LoRA.` | the plan prompt's `loras:` line |
| `RECHECK_SCOPE_HINT` | `An L8 violation is a pick placed where its catalog scope does not allow: give a physics LoRA the scope either with bin/lora-catalog scope ID either (or the Scope select of its row in the movie UI's LoRAs tab), or pass --force-story to regenerate; a style LoRA is only ever a global pick and a motion LoRA only ever a per-beat pick, so a style LoRA picked for a beat or a motion LoRA picked globally needs --force-story.` | stderr: the re-check, and bin/ltx-movie's catalog-checks error after an L8 line |
| bin/ltx-story-manifest | `panel %d has more than one LoRA of the same kind (style, motion or physics)` | after `Error: --catalog-loras <path>: `, exit 2 |
| bin/ltx-mlx-render | `panel %d: catalog_loras has more than one LoRA of the same kind (style, motion or physics)` | `ValueError` from `load_manifest` |
| index.html note (replaces the note at `:419`) | `Where the story planner may put a physics video LoRA: global applies it to every panel, beat only to the beats it suits, either lets the planner choose; the default is beat. A style LoRA is always global, a motion LoRA is always per-beat, and a stills LoRA has no scope, so the select is off for all three.` | after the Scope select |

The L8 messages (`LORA_SCOPE_GLOBAL`, `LORA_SCOPE_BEAT`), the duplicate notes, the style messages and every other text do not change.

bin/lora-catalog examples. `<path>` is the catalog path. `fight-motion` has `"scope": "either"` saved, and `ARCH` is the `arch: ...` line that `add` already prints to stderr:

| Command | stdout | stderr | exit |
|---|---|---|---|
| `list` | the table, with `beat` in fight-motion's SCOPE cell | `warning: catalog entry fight-motion has the scope either, but a motion LoRA is only ever a per-beat pick, so it is read as beat; clear it with bin/lora-catalog scope fight-motion default` | 0 |
| `scope fight-motion global` | - | `Error: entry fight-motion: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got 'global'` | 2 |
| `scope fight-motion default` | `fight-motion: scope beat (the default for a motion LoRA) in <path>` | - | 0 |
| `add F --id new-motion --kind motion --target video --scope either ...` | - | `ARCH` then `Error: entry new-motion: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got 'either'` | 2 |
| `scope rain-physics either` | `rain-physics: scope either in <path>` | - | 0 |

## 4. What changes for existing catalogs and plans

| # | Before | After | How to get today's behaviour back |
|---|---|---|---|
| C1 | A motion entry scoped `global` or `either` may be a global pick and is listed under `May be global picks` | Read as `beat`: only listed under `May be per-beat picks`; a global pick is the hard L8; every reader of MB4 warns | none for motion (MB1); `bin/lora-catalog scope ID default` silences the warning |
| C2 | A saved `plan.json` with a global pick of such an entry re-checks clean and renders | Its re-check and Phase 2, Phase 3 and the dry run exit 2 with L8 and the new `RECHECK_SCOPE_HINT` | `--force-story` (or hand-edit plan.json to move the pick into `per_beat`) |
| C3 | `bin/lora-catalog add --kind motion --scope global|either` writes the scope | exit 2 (MB3), file unchanged | omit `--scope` or pass `beat` |
| C4 | `bin/lora-catalog scope <motion> global|either` writes it | exit 2 (MB3), file unchanged | - |
| C5 | `POST /api/loras` with kind motion and scope global or either runs `add` | 400, nothing runs | - |
| C6 | The LoRAs tab has a Scope select on a motion row, and the add form's select is enabled for motion | `beat` as text; the add select is off for motion; a warning box for legacy motion scopes | - |
| C7 | A global physics pick plus a per-beat motion pick on one beat: the advisory L3, then Phase 3 fails in bin/ltx-story-manifest (`panel <k> has more than one style or motion/physics LoRA`) | No L3; Phase 3 writes both on that panel; the manifest and the renderer accept it | - |
| C8 | Two motion LoRAs on one panel: `L3 motion: 2 motion or physics LoRAs ...`; the manifest refuses | `L3 motion: 2 motion LoRAs ...`; the manifest still refuses, with the new text | - |
| C9 | Two physics LoRAs on one panel: `L3 motion: 2 motion or physics LoRAs ...` | `L3 physics: 2 physics LoRAs ...` (same severity); the manifest still refuses, with the new text | - |
| C10 | The paragraph allows motion in global and one motion or physics LoRA per beat | Section 3's text | - |
| C11 | `RECHECK_SCOPE_HINT` suggests `either` for motion | Section 3's text | - |
| C12 | A hand-written manifest with two style entries on one panel: `more than one style or motion/physics LoRA` | `more than one LoRA of the same kind (style, motion or physics)` (still refused) | - |

**Unchanged for every catalog without a legacy motion scope:** the bytes of catalog.json, every warning (none), every prompt line except the paragraph, every check except L3's text, and every file and exit code. The exceptions are C7-C9 and C12, where the plan or the manifest has more than one non-style LoRA on a panel.

---

## 5. Tests

### 5.1 New tests

`tests/test_motion_beat_only.py` (Task 1) and `tests/test_motion_beat_only_ui.py` (Task 2):
- Same header style as `tests/test_lora_scope_fix.py` (docstring naming this spec and MB1-MB9, the run line, "No test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.").
- Same imports, `sys.path` lines and fixtures.
- `tests/test_motion_beat_only.py` loads story_engine and bin/ltx-movie under the module names `story_engine_for_motion_beat_only` and `ltx_movie_for_motion_beat_only`.

**Shared literals and helpers of `tests/test_motion_beat_only.py`:**
- `CLI`, `ARCH_UNVERIFIED`, `_cli`, `_read_bytes` and `_pick` are copied from `tests/test_lora_scope_catalog.py:27-29, 51-62` and `tests/test_lora_scope_fix.py:71-72`.
- `_Done`, `_movie_args`, `_write_plan`, `_story`, `P3` and `CHECKS_ERROR` are copied verbatim from `tests/test_lora_scope_fix.py:45-46, 214-251`.
- `W = lora_catalog.MOTION_SCOPE_WARNING`.
- `MOTION_GLOBAL_L8 = "plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog scope is beat), but it is a global pick; remove it from global and pick it for the beats that need it"`.
- `_entries(tmp_path)` returns, in this order:
  - `film-grain` (`seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style")`);
  - `fast-motion` (motion, `scope="either"`);
  - `slow-motion` (motion, no scope);
  - `rain-physics` (physics, `scope="either"`);
  - `mist-physics` (physics, `scope="either"`);
  - `ink-stills` (`kind="style", target="stills", base_models=[seu.STILLS_MODEL]`).
  
  `files = str(tmp_path / "files")`, and each file is named by its id's first word.
- `_ctx(ws, tmp_path, **kw)` is `seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": _entries(tmp_path)}, **kw)`. `_plan` and `_checks` are as in `tests/test_lora_scope.py:78-88`.

| Test | Task | Exact assertions |
|---|---|---|
| **MB-T1** `test_mbt1_a_motion_lora_is_read_as_beat_and_named` | 1 | **Constants:** `W == "catalog entry %s has the scope %s, but a motion LoRA is only ever a per-beat pick, so it is read as beat; clear it with bin/lora-catalog scope %s default"`, and `DEFAULT_SCOPES` and `SCOPES` are unchanged.<br>**Motion:** with `fast = dict(fast-motion entry); fast.pop("scope")`, for each `scope` in `(None, "global", "beat", "either")` and `e = fast if scope is None else dict(fast, scope=scope)`: `entry_scope(e) == "beat"`, and `validate_entry(e)` raises nothing.<br>**Write refusal:** for `scope` in `("global", "either")`, `validate_entry(dict(fast, scope=scope), for_write=True)` raises `CatalogError` with `str == "entry fast-motion: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got %r" % scope`. `validate_entry(dict(fast, scope="globl"), for_write=True)` raises the generic `entry fast-motion: scope must be one of global, beat, either, got 'globl'`.<br>**Accepted with `for_write=True`:** `fast`, `dict(fast, scope="beat")`, `rain-physics` with each of the three scopes (and `entry_scope` equals that scope), `dict(film-grain, scope="global")`, and the stills motion entry `dict(fast, target="stills", base_models=[seu.STILLS_MODEL], scope="global")` (whose `entry_scope` is `None`).<br>**`scope_warnings`** of `[film-grain, dict(fast, scope="either"), dict(fast, id="old-motion", scope="global"), dict(fast, id="new-motion", scope="beat"), fast, dict(rain-physics, scope="global"), <the stills motion entry>]` is `[W % ("fast-motion", "either", "fast-motion"), W % ("old-motion", "global", "old-motion")]`.<br>**Load and save:** `path = seu.make_catalog(story_env["catalog"], _entries(tmp_path))`, then `before = _read_bytes(path)`. `data = load_catalog(path)` raises nothing, and its fast-motion entry still has `"scope": "either"`. `save_catalog(path, data)` leaves `_read_bytes(path) == before` |
| **MB-T2** `test_mbt2_lora_catalog_warns_and_refuses_a_non_beat_motion_scope` | 1 | `path = seu.make_catalog(story_env["catalog"], _entries(tmp_path))` and `warn = "warning: " + W % ("fast-motion", "either", "fast-motion") + "\n"`.<br>**`list`:** exit 0, stderr `== warn`. With `row = "%-24s %-9s %-7s %-7s %-14s %-24s %s"`, the stdout lines include `row % ("fast-motion", "motion", "video", "beat", "0.8 (0.5-1.0)", "", seu.VIDEO_MODEL)` and `row % ("rain-physics", "physics", "video", "either", "0.8 (0.5-1.0)", "", seu.VIDEO_MODEL)`.<br>**`list --json`:** exit 0, stderr `== warn`, stdout parses as JSON, and the fast-motion entry's `scope == "either"`.<br>**`verify`:** stderr `== warn` and exit 0.<br>**Refusals,** with `before = _read_bytes(path)`:<br>- for `scope` in `("global", "either")`, `_cli("add", seu.lora_file(files, "new"), "--id", "new-motion", "--kind", "motion", "--target", "video", "--scope", scope, "--base-model", seu.VIDEO_MODEL, "--description", "a test LoRA", "--use-when", "a chase")` gives `(returncode, stdout, stderr) == (2, "", ARCH_UNVERIFIED + "Error: entry new-motion: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got %r\n" % scope)`;<br>- `_cli("scope", "fast-motion", scope)` gives `(2, "", "Error: entry fast-motion: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got %r\n" % scope)`;<br>- afterwards `_read_bytes(path) == before`.<br>**`remove` keeps a legacy scope:** `_cli("remove", "film-grain")` exits 0, and the loaded fast-motion entry still has `"scope": "either"` (it was not rewritten).<br>**Clearing:** `_cli("scope", "fast-motion", "beat")` gives `(0, "fast-motion: scope beat in %s\n" % path, "")`. `_cli("scope", "fast-motion", "default")` gives `(0, "fast-motion: scope beat (the default for a motion LoRA) in %s\n" % path, "")`, and the loaded fast-motion entry has no `scope` key.<br>**Physics may still be either:** `_cli("scope", "rain-physics", "global")` gives `(0, "rain-physics: scope global in %s\n" % path, "")`.<br>**Then quiet:** `_cli("list").stderr == ""`.<br>**`add --scope beat`:** `_cli("add", seu.lora_file(files, "beat"), "--id", "beat-motion", "--kind", "motion", "--target", "video", "--scope", "beat", <the same base flags>)` exits 0, and the new entry's `scope == "beat"` |
| **MB-T3** `test_mbt3_l3_counts_motion_and_physics_apart_and_motion_is_never_global` | 1 | With `ctx = _ctx(ws, tmp_path)`:<br>- `_checks(ctx, {"global": [_pick("film-grain"), _pick("rain-physics")], "per_beat": {"2": [_pick("fast-motion")]}}) == ([], [])`;<br>- `_checks(ctx, {"global": [_pick("fast-motion")]}) == ([MOTION_GLOBAL_L8], [])`;<br>- `_checks(ctx, {"per_beat": {"2": [_pick("fast-motion"), _pick("slow-motion")]}}) == ([], ["beat 2: L3 motion: 2 motion LoRAs on this panel (fast-motion, slow-motion); at most 1"])`;<br>- `_checks(ctx, {"global": [_pick("rain-physics")], "per_beat": {"2": [_pick("mist-physics")]}}) == ([], ["beat 2: L3 physics: 2 physics LoRAs on this panel (rain-physics, mist-physics); at most 1"])`;<br>- `_checks(ctx, {"global": [_pick("rain-physics")], "per_beat": {"2": [_pick("fast-motion"), _pick("slow-motion"), _pick("mist-physics")]}})[1]` is exactly those two L3 messages for beat 2, with physics labels `(rain-physics, mist-physics)`, motion first;<br>- with `pinned = ctx._replace(pinned=[{"path": "/p/m.safetensors", "strength": 1.0, "catalog_id": None, "kind": "motion"}])`, `_checks(pinned, {"per_beat": {"1": [_pick("fast-motion")]}}) == ([], ["beat 1: L3 motion: 2 motion LoRAs on this panel (pinned LoRA, fast-motion); at most 1"])`;<br>- `se.parse_violation("beat 2: L3 physics: 2 physics LoRAs on this panel (rain-physics, mist-physics); at most 1")` has `id == "L3"`, `name == "physics"`, `scope == "beat"` and `index == 2`.<br>**Groups:** `groups = se.catalog_groups(ctx, se.compatible_entries(ctx))` and `split = groups.index(se.LORA_BEAT_GROUP)`. For `m` in `("fast-motion", "slow-motion")`, `line[m] not in groups[:split]` and `line[m] in groups[split:]`. For `p` in `("rain-physics", "mist-physics")`, `line[p]` is in both. `line` maps each id to `se.catalog_line(e)`.<br>**Duplicate:** `plan = _plan(ctx, {"global": [_pick("fast-motion", 0.9)], "per_beat": {"1": [_pick("fast-motion", 0.7)]}})` gives `plan["loras"]["global"] == []`, `plan["loras"]["per_beat"] == {"1": [_pick("fast-motion", 0.7)]}` and `plan["lora_notes"] == ["plan: L6 duplicate: 'fast-motion' was picked both globally and for beat(s) 1; its catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global pick"]` |
| **MB-T4** `test_mbt4_the_paragraph_and_the_hint` | 1 | `se.LORA_PICK_PARAGRAPH` and `se.RECHECK_SCOPE_HINT` equal Section 3's texts word for word. `"motion or physics" not in` either text. Neither has `{` or `}`. For each mode in `("chained", "no_stills", "shots")`, `se.LORA_PICK_PARAGRAPH in se.build_plan_prompt(c, se.compatible_entries(c), [])`, where `c = _ctx(ws, tmp_path, mode=mode)` |
| **MB-T5** `test_mbt5_the_critic_can_put_physics_globally_and_motion_on_a_beat` | 1 | With `ctx = _ctx(ws, tmp_path)` and `patch(index, replacement)` as in LST14 (`reason "L3"`), and `patches = [patch(0, [_pick("rain-physics")]), patch(2, [_pick("fast-motion")])]`: for `order` in `(patches, patches[::-1])`, `state = {"plan": _plan(ctx, {}), "parts": []}` and `new, applied, rejected = se.apply_patches(ctx, state, order, lora_allowed=True)` give `sorted(p["index"] for p in applied) == [0, 2]`, `rejected == []`, `(new["plan"]["loras"]["global"], new["plan"]["loras"]["per_beat"]) == ([_pick("rain-physics")], {"2": [_pick("fast-motion")]})` and `_checks`-style `se.lora_checks(...)` of `new["plan"] == ([], [])`. Then `se.apply_patches(ctx, {"plan": _plan(ctx, {}), "parts": []}, [patch(0, [_pick("fast-motion")])], lora_allowed=True)` has `applied == []` and rejection reasons `["would break " + MOTION_GLOBAL_L8]` |
| **MB-T6** `test_mbt6_phase_3_warns_and_writes_a_global_physics_with_a_beat_motion` | 1 | `grain, fast, rain = [e for e in _entries(tmp_path) if e["id"] in ("film-grain", "fast-motion", "rain-physics")]` (fast is `either`, rain is `either`). `story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast, rain], {"global": [_pick("rain-physics", 0.7)], "per_beat": {"2": [_pick("fast-motion", 0.8)]}})`, `path = os.path.join(story_dir, "catalog_loras.json")`, `warn = "Warning: " + W % ("fast-motion", "either", "fast-motion") + "\n"`, then `capsys.readouterr()`.<br>**Success:** `ltx_movie.phase3_manifest(_movie_args(*P3)) == 0`, and `err.count(warn) == 1`. With `r = {"id": "rain-physics", "kind": "physics", "path": rain["path"], "sha256": rain["sha256"], "strength": 0.7, "triggers": []}` and `f = {"id": "fast-motion", "kind": "motion", "path": fast["path"], "sha256": fast["sha256"], "strength": 0.8, "triggers": []}`, `json.load(open(path))["panels"] == [[r], [r, f], [r]]`. Then `os.remove(path)`.<br>**A global motion pick:** `_write_plan(story_dir, {"global": [_pick("fast-motion", 0.7)]})` and `capsys.readouterr()`. `phase3_manifest(_movie_args(*P3)) == 2`, and `capsys.readouterr().err == warn + CHECKS_ERROR % MOTION_GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"`. `ltx_movie.main(P3 + ["--dry-run"]) == 2` with the same err. `not os.path.exists(path)`.<br>**`--no-auto-lora`:** `_movie_args(*(P3 + ["--no-auto-lora"]))` prints no `Warning: catalog entry` to stderr |
| **MB-T7** (added assertions in `tests/test_lora_catalog.py`; edits E33-E36) | 1 | **LCT16:** a panel list `[[rain, fast], [], []]` (`rain = _entry(tmp_path, "rain-physics", "physics", 0.6, [])`) makes `story_manifest.main(argv) == 0`. `[[fast, dict(fast, id="slow-motion")], [], []]` and `[[rain, dict(rain, id="mist-physics")], [], []]` give exit 2 with `Error: --catalog-loras <path>: panel 1 has more than one LoRA of the same kind (style, motion or physics)\n`.<br>**LCT19:** `[[rain, fast, grain], [], []]` loads, with that panel's `catalog_loras == [rain, fast, grain]`. `render.build_units(<its panels>, 0, str(tmp_path / "clips"))[0]["loras"]` has names `["rain-physics", "fast-motion", "film-grain"]`. `[fast, dict(fast, id="slow-motion")]` and `[rain, dict(rain, id="mist-physics")]` raise `ValueError("panel 1: catalog_loras has more than one LoRA of the same kind (style, motion or physics)")` |
| **MB-T8** `test_mbt8_the_movie_ui_refuses_a_non_beat_motion_scope` | 2 | Uses the `ui` fixture of `tests/test_lora_scope_fix.py:54-61` and LST13's `add` body with `"kind": "motion"`.<br>- For `scope` in `("global", "either")`: `mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (400, {"error": "scope must be beat or null for a motion LoRA"})`, and `mt.stub_calls(ws) == []`.<br>- `dict(add, scope="beat")` runs with argv tail `["--rank", "16", "--scope", "beat"]`.<br>- `dict(add, scope=None)` runs with no `--scope`.<br>- `dict(add, kind="physics", scope="either")` runs with tail `["--rank", "16", "--scope", "either"]`.<br>- `dict(add, kind="style", scope="either")` is still 400 `scope must be global or null for a style LoRA`.<br>- `POST /api/loras/scope` `{"ws": ws, "id": "fight", "scope": "global"}` is 200 with stub argv `["scope", "fight", "global"]` (the server passes it on; bin/lora-catalog refuses) |
| **MB-T9** `test_mbt9_the_loras_tab_shows_motion_as_beat_and_warns` | 2 | Reads `static/movie-ui/index.html` and `app.js`.<br>**HTML:** `html.count('id="l-scope-warnings"') == 1`; `'<div id="l-scope-warnings" class="warning" hidden></div>' in html`; `html.index('id="l-verify-all"') < html.index('id="l-scope-warnings"') < html.index('id="l-table"')`; the Section 3 note text `+ "</span>"` is in html.<br>**JS, each line exactly once:**<br>- `if (e.kind === "motion") { return el("td", {text: "beat"}); }`<br>- `$("#l-scope").disabled = $("#l-target").value !== "video" \|\| $("#l-kind").value !== "physics";`<br>- `const warnings = clear($("#l-scope-warnings"));`<br>- `warnings.hidden = true;`<br>- `if (e.target === "video" && e.kind === "motion" && e.scope && e.scope !== "beat") {`<br>- `warnings.appendChild(el("div", {text: "Warning: " + motionScopeWarning(e)}));`<br>- `warnings.hidden = false;`<br>**JS mirrors Python:** with `parts = lora_catalog.MOTION_SCOPE_WARNING.split("%s")` (4 parts), `('return "%s" + e.id + "%s" + e.scope + "%s" + e.id + "%s";' % tuple(parts)) in js`. `$("#l-kind").value === "style";` no longer occurs.<br>**`node --check app.js`** when node is installed (as LST11) |

### 5.2 Existing tests edited (all still pass; none is removed)

Each edit is an Edit-tool replacement whose Old text occurs exactly once.

**Task 1:**
- **E26 `tests/test_story_engine.py::_lora_ctx` (`:442-455`).** Replace `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),` with two lines: `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),` and `seu.catalog_entry(seu.lora_file(files, "slow"), "slow-motion"),`.
- **E27 RST15 (`:487-491`).** Replace the first assertion (global film-grain and fast-motion, per-beat rain-physics, L3) with:
  ```python
  assert lv({"global": [pick("film-grain"), pick("rain-physics")],
             "per_beat": {"2": [pick("fast-motion")]}, "stills": [pick("ink-stills")]}) == ([], [])
  assert lv({"global": [], "per_beat": {"2": [pick("fast-motion"), pick("slow-motion")]},
             "stills": []}) == (
      [], ["beat 2: L3 motion: 2 motion LoRAs on this panel (fast-motion, slow-motion); at "
           "most 1"])
  ```
- **E28 RST15 cases (`:517-522`).** In the two L5 cases, `pick("fast-motion", 1.4)` and `pick("fast-motion", 2.5)` become `pick("rain-physics", 1.4)` and `pick("rain-physics", 2.5)`, and `'fast-motion'` in their two messages becomes `'rain-physics'`.
- **E29 `_lora_state` (`:1454-1470`).**
  - `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),` becomes `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),` followed by `seu.catalog_entry(seu.lora_file(files, "slow"), "slow-motion"),`.
  - `seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]` becomes `seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics", scope="either")]` (wrapped to stay under 100 columns, as the file's style).
- **E30 RST31 (`:1473-1484`).** The body becomes:
  ```python
  ctx, state = _lora_state(ws, tmp_path, story_env)
  new, applied, rejected = se.apply_patches(ctx, state, [
      _patch("plan", 0, "lora", [{"id": "rain-physics", "strength": 0.9}]),
      _patch("plan", 2, "lora", [{"id": "fast-motion", "strength": 0.7},
                                 {"id": "slow-motion", "strength": 0.7}])])
  assert len(applied) == 1
  assert new["plan"]["loras"]["global"] == [{"id": "rain-physics", "strength": 0.9}]
  assert new["plan"]["loras"]["per_beat"] == {}
  assert _reasons(rejected) == ["would break beat 2: L3 motion: 2 motion LoRAs on this panel "
                                "(fast-motion, slow-motion); at most 1"]
  cleared, applied, _rj = se.apply_patches(ctx, new, [_patch("plan", 0, "lora", [])])
  assert cleared["plan"]["loras"]["global"] == [] and len(applied) == 1
  ```
- **E31 LCT28 (`:1514-1519`).** The patch list becomes `[{"id": "fast-motion", "strength": 0.7}, {"id": "slow-motion", "strength": 0.6}]`, and the reason becomes `"would break beat 2: L3 motion: 2 motion LoRAs on this panel (fast-motion, slow-motion); at most 1"`.
- **E32 `tests/test_dialogue.py::test_dlg18_reclassification` (`:1403-1429`).**
  - `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),` becomes `seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),` followed by `seu.catalog_entry(seu.lora_file(files, "slow"), "slow-motion"),`.
  - In both L5 asserts, `fast-motion` becomes `rain-physics`, in the pick and in the message.
  - The L3 tuple becomes `({"per_beat": {"2": [pick("fast-motion"), pick("slow-motion")]}}, "L3", lctx),`.
- **E33-E36 `tests/test_lora_catalog.py`.**
  - E33, LCT16's bad case (`:860-861`): the message becomes `"panel 1 has more than one LoRA of the same kind (style, motion or physics)"`.
  - E34, LCT16: add MB-T7's two refused cases to `bad_cases`. After the `bad_cases` loop, add the accepted `[[rain, fast], [], []]` case: write it as the loop does, then `assert story_manifest.main(argv) == 0` and `capsys.readouterr()`. `rain` is defined at the top of the test, after `grain`.
  - E35, LCT19's case (`:1025-1026`): the message becomes `"panel 1: catalog_loras has more than one LoRA of the same kind (style, motion or physics)"`.
  - E36, LCT19: add MB-T7's two refused cases, and before `cases`, the accepted load and `build_units` assertions. `rain` comes from `_entry`.
- **E37 `tests/test_per_beat_json.py::test_pjt1` (`:94-102`).** `"picks: at most one style LoRA, plus motion or physics LoRAs that suit the whole movie. "` becomes `"picks: at most one style LoRA, plus at most one physics LoRA that suits the whole movie. "`. The two literals after `CLAUSE` become `+ CLAUSE + " a LoRA in global is never also in per_beat, and every beat may have at " "most one motion LoRA and at most one physics LoRA, counting global. stills is a list of " "at most one stills LoRA.")`.
- **E38 `tests/test_lora_scope.py`.**
  - LST4's paragraph literal (`:100-109`) becomes Section 3's text, in the same wrapped-literal style.
  - The `HINT` literal (`:38-42`) becomes Section 3's `RECHECK_SCOPE_HINT`.
- **E39 LST5 (`:158-164`).** This becomes:
  ```python
  either = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="either"))
  assert _checks(either, {"global": [_pick("rain-physics")]}) == ([], [])
  assert _checks(either, {"per_beat": {"2": [_pick("rain-physics")]}}) == ([], [])
  swapped = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="global"))
  assert _checks(swapped, {"global": [_pick("rain-physics")]}) == ([], [])
  assert _checks(swapped, {"per_beat": {"2": [_pick("rain-physics")]}})[0] == [
      (BEAT_L8 % 2).replace("film-grain", "rain-physics")]
  ```
- **E40 LST8 (`:262-277`).**
  - `entries = _entries(tmp_path, fast="either")` becomes `entries = _entries(tmp_path, rain="either")`.
  - `raw["loras"] = {"global": [_pick("fast-motion")], ...}` becomes `{"global": [_pick("rain-physics")], "per_beat": {}, "stills": []}`.
  - `assert "  - " + GLOBAL_L8 + "\n" in err` becomes `assert "  - " + GLOBAL_L8.replace("fast-motion", "rain-physics") + "\n" in err`.
- **E41 `tests/test_lora_scope_catalog.py` LST1 (`:75-78`).** This becomes:
  ```python
  for scope in lora_catalog.SCOPES:
      for entry in ((grain, fast, rain, ink) if scope == "global" else (fast, rain, ink)):
          lora_catalog.validate_entry(dict(entry, scope=scope))
      assert lora_catalog.entry_scope(dict(rain, scope=scope)) == scope
      assert lora_catalog.entry_scope(dict(fast, scope=scope)) == "beat"
  ```
  LST1's `save_catalog` of `dict(fast, scope="either")` (`:96-100`) stays as it is: `save_catalog` validates without `for_write`, so a legacy motion scope survives a save, which is MB3's intent.
- **E42 LST2 (`:110-112`, `:141`).**
  - In the first `add`, `"fight-motion", "--kind", "motion"` becomes `"fight-physics", "--kind", "physics"`.
  - The row `row % ("fight-motion", "motion", "video", "either", ...)` becomes `row % ("fight-physics", "physics", "video", "either", ...)`. The sort order is unchanged, because `fight-physics` < `film-grain`.
- **E43 LST3 (`:156-166`).** Every `fast-motion` in this block becomes `rain-physics`:
  - `entries == [dict(fast, scope="global"), grain, ink, rain]` becomes `entries == [fast, grain, ink, dict(rain, scope="global")]`;
  - `load_catalog(path)["entries"][0] == dict(fast, scope="either")` becomes `["entries"][3] == dict(rain, scope="either")`;
  - the default line becomes `"rain-physics: scope beat (the default for a physics LoRA) in %s\n" % path`;
  - the closing assertion `== [fast, grain, ink, rain]` stays.
- **E44 `tests/test_lora_scope_fix.py` LST15 (`:265-268`).** This becomes:
  ```python
  rain = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "rain"), "rain-physics",
                           kind="physics", scope="either")
  seu.make_catalog(story_env["catalog"], [grain, fast, rain])
  _write_plan(story_dir, {"global": [_pick("rain-physics", 0.7)]})
  assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
  item = {"id": "rain-physics", "kind": "physics", "path": rain["path"],
          "sha256": rain["sha256"], "strength": 0.7, "triggers": []}
  ```
  The lines after it (`:269-271`) stay.

**Task 2:**
- **LST10 (`tests/test_lora_scope_ui.py:42-53`).** `"kind": "motion"` becomes `"kind": "physics"`, and `"--kind", "motion"` in the expected argv becomes `"--kind", "physics"`.
- **LST11 (`:96-97`).** The literal `'$("#l-scope").disabled = $("#l-target").value !== "video" || ' '$("#l-kind").value === "style";'` becomes `'$("#l-scope").disabled = $("#l-target").value !== "video" || ' '$("#l-kind").value !== "physics";'`. Add `'if (e.kind === "motion") { return el("td", {text: "beat"}); }',` after the style literal.
- **LST13 (`tests/test_lora_scope_fix.py:173-176`).** The note literal becomes Section 3's note text `+ "</span>"`.

**Task 3:** `tests/test_movie_ui_builder.py::test_mut26`. BASELINE becomes Task 1's full sha. The comment chain ends `..., then to d87b6fe2e3523a09304b53c7d0b8bc448c6514f4 (shots-zimage), then to <Task 1 sha> (motion-beat-only).`

### 5.3 Mutation check (run once before Task 3)

Each of these, applied to a copy of the Task 2 tree, makes at least one MB-T or edited test fail:
- `entry_scope` reading a motion entry's scope;
- `validate_entry` refusing a legacy motion scope without `for_write`;
- `validate_entry` accepting it with `for_write`;
- `cmd_scope` not calling `validate_entry(..., for_write=True)`;
- `cmd_add` calling it without the flag;
- `scope_warnings` warning for `beat`, for a physics entry, or for a stills entry;
- bin/ltx-movie not printing the warning, or printing it twice;
- `list` printing it on stdout;
- `verify` not printing it;
- L3 still counting motion and physics together;
- L3 without the physics count;
- the old paragraph;
- the old hint;
- the manifest or the renderer keeping the combined motion/physics limit;
- either of them allowing two entries of one kind;
- `_h_lora_add` without the motion 400;
- `scopeCell` with a select for a motion row;
- `syncLoraScope` enabling the select for motion;
- the warning box never shown;
- a JavaScript warning text that differs from `MOTION_SCOPE_WARNING`.

## 6. Live checks (the user runs these on their own Mac; the assistant never accesses it)

Run from the workspace root after merging. `<fight>` is the catalog id of the fight (motion) LoRA, `<phys>` a physics LoRA if one is cataloged, `<cmd>` the bin/ltx-movie command of the fight story (auto LoRA on) and `<id>` its `--story-id`. Run `export D=generated/stories/<id>` first.

- **MB-LV1 (the LoRAs tab, before clearing anything).** Open the movie UI's LoRAs tab.
  1. Every motion row's Scope cell reads `beat` with no select, every style row reads `global`, every physics row has a select, and every stills row reads `-`.
  2. If any motion entry was ever set to `global` or `either`, a warning box above the table lists one `Warning: catalog entry <id> has the scope <s>, but a motion LoRA is only ever a per-beat pick, ...` line per entry. Record them.
  3. In "Add a LoRA", with Target `video`: Kind `style` and Kind `motion` disable the Scope select, Kind `physics` enables it, and Target `stills` disables it.
- **MB-LV2 (the CLI).**
  1. `bin/lora-catalog list` exits 0. Every motion entry shows SCOPE `beat`, and stderr has the same warning lines as MB-LV1 step 2 (with `warning:`).
  2. `bin/lora-catalog scope <fight> global` exits 2 with `Error: entry <fight>: scope must be beat for a motion LoRA, which is only ever a per-beat pick, got 'global'`, and `bin/lora-catalog list` still shows the old state.
  3. For each warned entry, run `bin/lora-catalog scope <id> default`. Expected: `<id>: scope beat (the default for a motion LoRA) in .../catalog.json`. Then `bin/lora-catalog list` prints no warning, and after a reload the LoRAs tab shows no warning box.
- **MB-LV3 (the prompt).** `<cmd> --dry-run --no-review | sed -n '/^LoRA catalog (pick only from these):/,/^$/p'` lists `<fight>` only under `May be per-beat picks (applied to their beat only):`. `<cmd> --dry-run --no-review | grep -c 'at most one motion LoRA and at most one physics LoRA, counting global'` prints `1`.
- **MB-LV4 (physics with motion; only with a `<phys>`).**
  1. `bin/lora-catalog scope <phys> either`.
  2. Run `<cmd> --story-only --force-story`, then print the picks:
     ```bash
     python3 - <<'EOF'
     import json, os
     loras = json.load(open(os.path.join(os.environ["D"], "plan.json"), encoding="utf-8"))["loras"]
     print("global", [p["id"] for p in loras["global"]])
     print("per_beat", dict((k, [p["id"] for p in v]) for k, v in sorted(loras["per_beat"].items())))
     EOF
     ```
     Expected: `<fight>` is not in `global`.
  3. If `global` holds `<phys>` and a beat holds `<fight>`, `grep -c '"L3"' $D/story_checks.json` prints `0`. Render that story. Phase 3 passes (no `has more than one` error), and the A/B by eye of that beat's clip against a beat without `<fight>` shows both effects. Record the result.
- **MB-LV5 (saved stories with a global motion pick; C2).** List them. The script prints nothing when there are none; record the output.
  ```bash
  python3 - <<'EOF'
  import glob, json, lora_catalog
  entries = {e["id"]: e for e in lora_catalog.load_catalog(lora_catalog.catalog_path("."))["entries"]}
  for path in sorted(glob.glob("generated/stories/*/plan.json")):
      loras = json.load(open(path, encoding="utf-8")).get("loras") or {}
      found = [p["id"] for p in loras.get("global") or []
               if isinstance(p, dict) and entries.get(p.get("id"), {}).get("kind") == "motion"]
      if found:
          print(path, ", ".join(found))
  EOF
  ```
  For one listed story, rerun its command with `--story-only` (no `--force-story`). Expected: exit 2, the bullet `plan: L8 scope: '<lora>' may only be a per-beat pick ...`, then the line `An L8 violation is a pick placed where its catalog scope does not allow: give a physics LoRA ...`. `--force-story` regenerates it.
- **MB-LV6 (the movie UI add route).** In "Add a LoRA", set Kind to `physics` and Scope to `either`, and add a copy of a small LoRA file under a new id. Its row shows a select set to `either`. Remove it with its Remove button.

## 7. Risks (rulings), follow-ups and open questions

**Risks.**
- **R1 (a motion and a physics LoRA stacked on one panel, C7).** This was never rendered here before, because the manifest refused it. L4 still caps a panel at 4 LoRAs, and strengths are each entry's own. Ruling: accepted; MB-LV4 is the A/B.
- **R2 (saved stories fail their re-check, C2).** Expected, and named by the new hint. Ruling: accepted; MB-LV5 lists them.
- **R3 (the warning repeats).** It prints on every bin/ltx-movie run (and every `list` and `verify`) until the entry is cleared. bin/iterate-story runs bin/ltx-movie many times, so the line repeats in its log. Ruling: accepted; the text names the one-command fix.
- **R4 (the `add` refusal comes after the file checks).** A motion `add` with `--scope global` reads and hashes the file, prints its `arch:` line, then refuses. Ruling: accepted (Decision 2); the file is never written.
- **R5 (the JavaScript text drifts).** Ruling: MB-T9 derives the expected JavaScript line from `MOTION_SCOPE_WARNING`.

**Follow-ups (not fixed here).**
- **F1.** Make L3 hard when Phase 3 would refuse the panel anyway: two LoRAs of one kind fail the manifest after the story is accepted. This predates this change; today L3 is advisory and the manifest refuses.
- **F2.** Let bin/lora-check print the same warnings.
- **F3.** Coerce a style entry's forbidden scope at load the same way, if the user wants it (Q3).

**Open questions (the spec settles each one; confirm or overrule).**
- **Q1 (physics limit and wording).** This spec caps physics at one per panel, as a second L3 message, the manifest and the renderer. So the global sentence reads `plus at most one physics LoRA that suits the whole movie`, not the brief's `plus physics LoRAs that suit the whole movie`. The alternative is to allow any number of physics LoRAs per panel (manifest and renderer limit only style and motion; no physics L3; plural wording). Confirm the cap.
- **Q2 (F-1: relaxing bin/ltx-story-manifest and bin/ltx-mlx-render).** Required for the brief's "global physics plus per-beat motion" to reach the renderer. Confirm that changing these two pinned renderer-side files is in scope.
- **Q3 (style).** A style video entry scoped `beat` or `either` still fails the whole catalog (the user's "style unchanged"). Should it get the same load-time coercion and warning?
- **Q4 (the style refusal wording).** `bin/lora-catalog add --kind style --scope either` still says `--scope either applies only to motion and physics LoRAs; ...`. After this change, only a physics LoRA may be `either`. It is kept byte-identical because style does not change; say if it should read `applies only to physics LoRAs` for `either`.
- **Q5.** Should bin/lora-check print the warning (F2)?

---

## Plan

**House rules** (every task):
- Work only in `$S/mb-wt`, and never touch `/Users/reubenpatterson/local_agent_harness` directly.
- Never stash, reset, amend, rebase, push or open a PR.
- Never access the user's other Mac (no ssh, no scp, no reading its files). Never contact a server, render, run a model, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's Old text must occur exactly once in the file when it is applied; if it does not, stop and report.
- Every changed Python file must compile on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit. End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- The PR is merged with a merge commit only.

### Before Task 1 (controller)

1. `git -C $S/mb-wt rev-parse HEAD` is `4dacff2...`, and `git status --short` is empty.
2. Record the baseline: `cd $S/mb-wt/qwen-agent-workspace && python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors > $S/mb-base.txt 2>&1`. Record its summary line as P0, and its list of failing tests as F0.
3. Check that every Old text below occurs exactly once.

### Task 1: the pinned files and their tests (one commit)

Edits (Old -> New; indentation exactly as shown):

**E1 `lora_catalog.py:39-43`, the comment above `OPTIONAL_ENTRY_KEYS`.** Append after its last line (`# global (fix round A1): Phase 3 applies a style LoRA to every panel, never to one beat.`):
```python
# A motion video entry's scope is always beat (motion-beat-only spec MB1,
# docs/superpowers/specs/2026-11-12-motion-lora-beat-only-design.md): a saved global or either
# still loads, is read as beat and is named by scope_warnings; a new write of one is refused.
```

**E2 `lora_catalog.py:86-88`.** Old:
```python
def validate_entry(entry):
    """LC3 entry rules. Raises CatalogError("entry <id>: <field> <reason>"). File existence is
    not checked here (verify_entry does that)."""
```
New:
```python
def validate_entry(entry, for_write=False):
    """LC3 entry rules. Raises CatalogError("entry <id>: <field> <reason>"). File existence is
    not checked here (verify_entry does that). for_write (motion-beat-only spec MB3) is for an
    entry that bin/lora-catalog add or scope is about to write: it also refuses a motion video
    entry whose scope is not beat. A loaded or saved catalog keeps such an entry, which
    entry_scope reads as beat and scope_warnings names."""
```

**E3 `lora_catalog.py:120-124`.** Old:
```python
    if (entry["target"] == "video" and entry["kind"] == "style"
            and entry.get("scope", "global") != "global"):
        fail("scope", "must be global for a style LoRA, which applies to every panel, got %r; "
                      "edit catalog.json by hand: remove the scope key or set it to global"
             % (entry["scope"],))
```
New: the same five lines, then:
```python
    if (for_write and entry["target"] == "video" and entry["kind"] == "motion"
            and entry.get("scope", "beat") != "beat"):
        fail("scope", "must be beat for a motion LoRA, which is only ever a per-beat pick, got %r"
             % (entry["scope"],))
```

**E4 `lora_catalog.py:157-166`, `entry_scope`.** Old:
```python
def entry_scope(entry):
    """Where the story planner may place a catalog entry (LoRA scope spec LS2): its scope, else
    DEFAULT_SCOPES of its kind; always global for a style LoRA (fix round A1, also for an entry
    that never went through validate_entry); None for a stills LoRA and for a library
    character."""
    if entry.get("target") != "video" or entry.get("kind") not in DEFAULT_SCOPES:
        return None
    if entry["kind"] == "style":
        return "global"
    return entry.get("scope") or DEFAULT_SCOPES[entry["kind"]]
```
New:
```python
def entry_scope(entry):
    """Where the story planner may place a catalog entry (LoRA scope spec LS2): its scope, else
    DEFAULT_SCOPES of its kind; always global for a style LoRA (fix round A1) and always beat for
    a motion LoRA (motion-beat-only spec MB2), also for an entry that never went through
    validate_entry; None for a stills LoRA and for a library character."""
    if entry.get("target") != "video" or entry.get("kind") not in DEFAULT_SCOPES:
        return None
    if entry["kind"] == "style":
        return "global"
    if entry["kind"] == "motion":
        return "beat"
    return entry.get("scope") or DEFAULT_SCOPES[entry["kind"]]


# Motion-beat-only spec MB4: a motion video entry saved with the scope global or either (before
# MB1) still loads; it is read as beat, and bin/ltx-movie, bin/lora-catalog list and verify, and
# the movie UI's LoRAs tab (app.js motionScopeWarning) name it.
MOTION_SCOPE_WARNING = ("catalog entry %s has the scope %s, but a motion LoRA is only ever a "
                        "per-beat pick, so it is read as beat; clear it with bin/lora-catalog "
                        "scope %s default")


def scope_warnings(entries):
    """MOTION_SCOPE_WARNING for each motion video entry of entries whose scope is set and is not
    beat, in entries order (motion-beat-only spec MB4)."""
    return [MOTION_SCOPE_WARNING % (e["id"], e["scope"], e["id"]) for e in entries
            if e.get("target") == "video" and e.get("kind") == "motion"
            and e.get("scope", "beat") != "beat"]
```

**E5 `bin/lora-catalog:14-16`, the docstring.** Old:
```
each video entry's scope allows (a motion or physics LoRA's scope is global, beat or either, by
default beat; a style LoRA's scope is always global: LoRA scope spec LS1 and its fix round A1);
```
New:
```
each video entry's scope allows (a physics LoRA's scope is global, beat or either, by default
beat; a style LoRA's scope is always global and a motion LoRA's always beat: LoRA scope spec LS1,
its fix round A1 and motion-beat-only spec MB1);
```

**E6 `bin/lora-catalog:104-106`.** Old:
```python
                     help="where the story planner may place this motion or physics video "
                          "LoRA: global (every panel), beat (one beat) or either; default: "
                          "beat. A style LoRA is always global")
```
New:
```python
                     help="where the story planner may place this physics video LoRA: global "
                          "(every panel), beat (one beat) or either; default: beat. A style "
                          "LoRA is always global and a motion LoRA always beat")
```

**E7 `bin/lora-catalog:115-117`.** Old:
```python
    scope = sub.add_parser("scope", help="set where the story planner may place a catalog video "
                                         "LoRA (default: the default for its kind; a style LoRA "
                                         "may only be global)")
```
New:
```python
    scope = sub.add_parser("scope", help="set where the story planner may place a catalog video "
                                         "LoRA (default: the default for its kind; a style LoRA "
                                         "may only be global and a motion LoRA only beat)")
```

**E8 `bin/lora-catalog:222`.** Old: `            lora_catalog.validate_entry(entry)`. New: `            lora_catalog.validate_entry(entry, for_write=True)`.

**E9 `bin/lora-catalog:250-254`, `cmd_list`.** Old:
```python
    try:
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    characters = lora_catalog.fold_characters(WS)
```
New:
```python
    try:
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    for warning in lora_catalog.scope_warnings(entries):
        print("warning: %s" % warning, file=sys.stderr)
    characters = lora_catalog.fold_characters(WS)
```

**E10 `bin/lora-catalog:326-329`, `cmd_scope`.** Old:
```python
        entries = [entry if e["id"] == entry["id"] else e for e in catalog["entries"]]
        try:
            lora_catalog.save_catalog(path, {"schema_version": lora_catalog.SCHEMA_VERSION,
```
New:
```python
        entries = [entry if e["id"] == entry["id"] else e for e in catalog["entries"]]
        try:
            lora_catalog.validate_entry(entry, for_write=True)
            lora_catalog.save_catalog(path, {"schema_version": lora_catalog.SCHEMA_VERSION,
```

**E11 `bin/lora-catalog:345-348`, `cmd_verify`.** Old:
```python
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    by_id = {e["id"]: e for e in entries}
```
New:
```python
        entries = lora_catalog.load_catalog(path)["entries"]
    except lora_catalog.CatalogError as e:
        return _error(str(e))
    for warning in lora_catalog.scope_warnings(entries):
        print("warning: %s" % warning, file=sys.stderr)
    by_id = {e["id"]: e for e in entries}
```

**E12 `story_engine.py:586-596`, `LORA_PICK_PARAGRAPH`.** Old: the whole assignment. New:
```python
LORA_PICK_PARAGRAPH = (
    "an object with the keys global, per_beat and stills. Each pick is an object with the keys "
    "id and strength, taken from the LoRA catalog below; strength must lie inside that entry's "
    "range. The catalog lists each LoRA under the places where it may go. global is a list of "
    "picks applied to every panel, taken only from the LoRAs that may be global picks: at most "
    "one style LoRA, plus at most one physics LoRA that suits the whole movie. per_beat maps "
    "each beat number to a list of picks for that beat only, taken only from the LoRAs that may "
    "be per-beat picks, and each key is the beat number alone in double quotes: the key of beat "
    '1 is "1"; a LoRA in global is never also in per_beat, and every beat may have at most one '
    "motion LoRA and at most one physics LoRA, counting global. stills is a list of at most one "
    "stills LoRA.")
```
The comment above it (`:584-585`) gets one more line: `# Motion-beat-only spec MB5: no motion LoRA in global; one motion and one physics LoRA per beat.`

**E13 `story_engine.py:615-621`, the comment and `RECHECK_SCOPE_HINT`.** Old: from `# Fix round A1, A3: a style LoRA's scope is always global, so only a motion or physics LoRA's` to the end of the assignment. New:
```python
# Fix round A1, A3 and motion-beat-only spec MB5: a style LoRA's scope is always global and a
# motion LoRA's always beat, so only a physics LoRA's scope can make its pick allowed;
# bin/ltx-movie's Phase 2 and 3 errors print this hint too.
RECHECK_SCOPE_HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: "
                      "give a physics LoRA the scope either with bin/lora-catalog scope ID either "
                      "(or the Scope select of its row in the movie UI's LoRAs tab), or pass "
                      "--force-story to regenerate; a style LoRA is only ever a global pick and a "
                      "motion LoRA only ever a per-beat pick, so a style LoRA picked for a beat or "
                      "a motion LoRA picked globally needs --force-story.")
```

**E14 `story_engine.py:2824-2827`, L3.** Old:
```python
        motion = [label for label, kind, _i, _p in loras_k if kind in ("motion", "physics")]
        if len(motion) > 1:
            advisory.append("beat %d: L3 motion: %d motion or physics LoRAs on this panel (%s); at "
                        "most 1" % (k, len(motion), ", ".join(motion)))
```
New:
```python
        # Motion-beat-only spec MB6: one motion LoRA and one physics LoRA per panel, counted
        # apart, so a global physics LoRA and a per-beat motion LoRA may share a panel.
        for counted in ("motion", "physics"):
            labels = [label for label, kind, _i, _p in loras_k if kind == counted]
            if len(labels) > 1:
                advisory.append("beat %d: L3 %s: %d %s LoRAs on this panel (%s); at most 1"
                                % (k, counted, len(labels), counted, ", ".join(labels)))
```

**E15 `bin/ltx-movie:1486-1487`, `_resolve_story_engine`.** Old:
```python
            print("Error: invalid LoRA catalog %s: %s; run bin/lora-catalog verify" % (path, reason),
                  file=sys.stderr)
            return 2
    args.story_engine = "robust"
```
New:
```python
            print("Error: invalid LoRA catalog %s: %s; run bin/lora-catalog verify" % (path, reason),
                  file=sys.stderr)
            return 2
        # Motion-beat-only spec MB4: a motion LoRA saved with the scope global or either is read
        # as beat; say so once per run.
        for warning in catalog.scope_warnings(args.story_catalog["entries"]):
            print("Warning: %s" % warning, file=sys.stderr)
    args.story_engine = "robust"
```

**E16 `bin/ltx-story-manifest:272-274`.** Old:
```python
        if (sum(1 for e in entries if e["kind"] == "style") > 1
                or sum(1 for e in entries if e["kind"] != "style") > 1):
            return None, "panel %d has more than one style or motion/physics LoRA" % i
```
New:
```python
        # Motion-beat-only spec MB7: at most one LoRA of each kind per panel, so a global physics
        # LoRA and a per-beat motion LoRA may share one.
        if any(sum(1 for e in entries if e["kind"] == kind) > 1
               for kind in ("style", "motion", "physics")):
            return None, ("panel %d has more than one LoRA of the same kind (style, motion or "
                          "physics)" % i)
```

**E17 `bin/ltx-mlx-render:294-297`.** Old:
```python
            if (sum(1 for e in entries if e["kind"] == "style") > 1
                    or sum(1 for e in entries if e["kind"] != "style") > 1):
                raise ValueError("panel %d: catalog_loras has more than one style or "
                                 "motion/physics LoRA" % index)
```
New:
```python
            # Motion-beat-only spec MB7: at most one LoRA of each kind per panel.
            if any(sum(1 for e in entries if e["kind"] == kind) > 1
                   for kind in ("style", "motion", "physics")):
                raise ValueError("panel %d: catalog_loras has more than one LoRA of the same "
                                 "kind (style, motion or physics)" % index)
```

**E18-E25.** Create `tests/test_motion_beat_only.py` with MB-T1-MB-T6 as Section 5.1 specifies, in that order, with one `# --- MB-Tn (MBk): <title> ---` divider per test (the divider style of `tests/test_lora_scope_fix.py`).

**E26-E44.** The test edits of Section 5.2, Task 1.

**Steps.**
1. Apply E18-E25 first (the new test file only) and run `python3 -B -m pytest -q -p no:cacheprovider tests/test_motion_beat_only.py`. Expected: all six fail (red), because `MOTION_SCOPE_WARNING` does not exist.
2. Apply E1-E17 and E26-E44.
3. Run `python3 -B -m pytest -q -p no:cacheprovider tests/test_motion_beat_only.py tests/test_lora_scope.py tests/test_lora_scope_catalog.py tests/test_lora_scope_fix.py tests/test_lora_catalog.py tests/test_per_beat_json.py tests/test_story_engine.py tests/test_dialogue.py tests/test_location_story.py tests/test_plan_budget.py`. Expected: no failure except the ones in F0.
4. Compile on both Pythons: `py_compile` of `lora_catalog.py story_engine.py tests/test_motion_beat_only.py`, and `python3 -c "import ast,sys; [ast.parse(open(p).read()) for p in sys.argv[1:]]" bin/lora-catalog bin/ltx-movie bin/ltx-story-manifest bin/ltx-mlx-render`.
5. Run `python3 tests/test_ltx_movie_offline.py`. Expected: the same `OK n/n` as at the baseline.
6. Run the full suite. Expected: compared with F0, the only new failure is `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (fixed by Task 3), and the 6 new tests pass.
7. Stage exactly `lora_catalog.py bin/lora-catalog story_engine.py bin/ltx-movie bin/ltx-story-manifest bin/ltx-mlx-render tests/test_motion_beat_only.py tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py tests/test_lora_scope.py tests/test_lora_scope_catalog.py tests/test_lora_scope_fix.py tests/test_lora_catalog.py` (under `qwen-agent-workspace/`).
8. Commit: `git commit -m "lora_catalog, story_engine, ltx-movie, story-manifest, mlx-render: a motion video LoRA is only ever a per-beat pick (a saved global or either loads as beat with a warning; a new write is refused), L3 counts motion and physics apart, and a panel may hold one LoRA of each kind (motion-beat-only MB1-MB7)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Task 2: the movie UI (one commit)

**E45 `movie_ui_server.py:1249-1250`.** Old:
```python
    if kind == "style" and scope in ("beat", "either"):
        raise ApiError(400, "scope must be global or null for a style LoRA")
```
New: the same two lines, then:
```python
    if kind == "motion" and scope in ("global", "either"):
        raise ApiError(400, "scope must be beat or null for a motion LoRA")
```

**E46 `static/movie-ui/index.html:411`.** Old: `  <h3>Catalog <button id="l-verify-all" type="button">Verify all</button></h3>`. New: that line, then `  <div id="l-scope-warnings" class="warning" hidden></div>`.

**E47 `static/movie-ui/index.html:419`.** In the `<span class="muted">` after the Scope select, the old note (Section 0.2) becomes Section 3's note text.

**E48 `static/movie-ui/app.js:2911-2915`, `loadCatalogTable`.** Old:
```javascript
    const body = clear($("#l-table tbody"));
    if (res.status !== 200) {
      $("#l-output").textContent = (res.data && res.data.error) || ("http " + res.status);
      return;
    }
```
New:
```javascript
    const body = clear($("#l-table tbody"));
    const warnings = clear($("#l-scope-warnings"));
    warnings.hidden = true;
    if (res.status !== 200) {
      $("#l-output").textContent = (res.data && res.data.error) || ("http " + res.status);
      return;
    }
    // Motion-beat-only spec MB4: a motion LoRA saved with the scope global or either is read as beat.
    res.data.entries.forEach(function (e) {
      if (e.target === "video" && e.kind === "motion" && e.scope && e.scope !== "beat") {
        warnings.appendChild(el("div", {text: "Warning: " + motionScopeWarning(e)}));
        warnings.hidden = false;
      }
    });
```

**E49 `static/movie-ui/app.js:2937-2941`, the comment, `scopeCell`'s start and a new function before it.** Old:
```javascript
  // LoRA scope spec LS7: a video entry's scope is chosen in its row; "default" clears it. A style
  // LoRA's scope is always global (fix round A1), so its row has no select.
  function scopeCell(e) {
    if (e.target !== "video") { return el("td", {text: "-"}); }
    if (e.kind === "style") { return el("td", {text: "global"}); }
```
New:
```javascript
  // lora_catalog.MOTION_SCOPE_WARNING (motion-beat-only spec MB4).
  function motionScopeWarning(e) {
    return "catalog entry " + e.id + " has the scope " + e.scope + ", but a motion LoRA is only ever a per-beat pick, so it is read as beat; clear it with bin/lora-catalog scope " + e.id + " default";
  }

  // LoRA scope spec LS7: a video entry's scope is chosen in its row; "default" clears it. A style
  // LoRA's scope is always global (fix round A1) and a motion LoRA's always beat (motion-beat-only
  // spec MB8), so their rows have no select.
  function scopeCell(e) {
    if (e.target !== "video") { return el("td", {text: "-"}); }
    if (e.kind === "style") { return el("td", {text: "global"}); }
    if (e.kind === "motion") { return el("td", {text: "beat"}); }
```

**E50 `static/movie-ui/app.js:2955-2958`, `syncLoraScope`.** Old:
```javascript
  // Fix round A1: a stills LoRA has no scope and a style LoRA's is always global, so the add
  // form's Scope select is off for both.
  function syncLoraScope() {
    $("#l-scope").disabled = $("#l-target").value !== "video" || $("#l-kind").value === "style";
```
New:
```javascript
  // Fix round A1 and motion-beat-only spec MB8: a stills LoRA has no scope, a style LoRA's is
  // always global and a motion LoRA's always beat, so the add form's Scope select is on only for
  // a physics video LoRA.
  function syncLoraScope() {
    $("#l-scope").disabled = $("#l-target").value !== "video" || $("#l-kind").value !== "physics";
```

**E51.** Create `tests/test_motion_beat_only_ui.py` with MB-T8 and MB-T9. **E52.** The Task 2 edits of Section 5.2 (LST10, LST11, LST13).

**Steps.**
1. Apply E51 first. `pytest tests/test_motion_beat_only_ui.py` gives 2 failed.
2. Apply E45-E50 and E52.
3. Run `python3 -B -m pytest -q -p no:cacheprovider tests/test_motion_beat_only_ui.py tests/test_lora_scope_ui.py tests/test_lora_scope_fix.py tests/test_movie_ui_http.py tests/test_movie_ui_builder.py`. Expected: no failure except `test_mut26` and F0. Then run `node --check static/movie-ui/app.js` when node is installed, and compile `movie_ui_server.py` with `/usr/bin/python3`.
4. Stage exactly `movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_motion_beat_only_ui.py tests/test_lora_scope_ui.py tests/test_lora_scope_fix.py`.
5. Commit: `git commit -m "movie-ui: the LoRAs tab shows a motion LoRA's scope as beat, warns about a saved global or either, and the add route refuses one (motion-beat-only MB4, MB8)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Task 3: the `test_mut26` re-baseline (a test-only commit; never amend)

1. `T1=$(git -C $S/mb-wt log -n1 --format=%H -- qwen-agent-workspace/lora_catalog.py)`. It must be Task 1's commit.
2. Check: `git -C $S/mb-wt diff --name-only $T1 HEAD -- <every PIPELINE_FILES path under qwen-agent-workspace/>` prints nothing.
3. Edit `tests/test_movie_ui_builder.py:291`: the chain's last clause `then to d87b6fe2e3523a09304b53c7d0b8bc448c6514f4 (shots-zimage).` becomes `then to d87b6fe2e3523a09304b53c7d0b8bc448c6514f4 (shots-zimage), then to $T1 (motion-beat-only).` (the full 40-character sha written in).
4. Edit `:293`: `BASELINE = "$T1"`.
5. `pytest tests/test_movie_ui_builder.py -k mut26` passes. Stage only `tests/test_movie_ui_builder.py`, and commit with `-m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the motion-beat-only commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

### Verification (controller)

- **V1.** Run the full suite. Compared test by test with `$S/mb-base.txt`: no test changed from passed to failed or disappeared; the failures are exactly F0; the new tests are the 9 of MBK1 and all pass.
- **V2.** `git diff --name-only 4dacff2 HEAD` lists exactly the files of 0.3 (D1-D12) plus this spec.
- **V3.** Run the mutation check of 5.3 on copies of the tree.
- **V4.** An Opus design review of the three commits against this spec, before the PR.
