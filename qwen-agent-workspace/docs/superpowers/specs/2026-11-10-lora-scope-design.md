# Catalog LoRA scope: a catalog video LoRA says whether the story planner may pick it for every panel, for one beat or for either; a pick in a place its scope forbids is the hard violation L8, and a LoRA picked both globally and for a beat keeps one copy

Date: 2026-11-10

Status: design spec and implementation plan in one document.

**The user's problem (confirmed):** in a story plan, a catalog LoRA is picked either in `loras.global` (applied to every panel) or in `loras.per_beat` (applied to one beat). The catalog does not say where a LoRA may go. So a fight LoRA can land in `global` and change every non-fight scene, and the same LoRA can be picked in `global` and again for a beat. Today the second case is the hard violation L6, reported once per LoRA at its first beat only, and it costs a critic round.

**The user's decisions:**
- A catalog entry gets an optional `scope`: `global`, `beat` or `either`.
- An entry without a scope gets a default from its kind: `style` is `global`, `motion` and `physics` are `beat`.
- The plan prompt shows the catalog split into a group that may be global and a group that may be per-beat.
- A pick in a place its scope forbids is a hard violation with a new id, so the critic repairs it.
- A LoRA picked both globally and for a beat is repaired by dropping the per-beat copy, on every beat that has it.
- The movie UI page that adds catalog LoRAs lets the user give a LoRA its scope, and so does bin/lora-catalog.

**This spec:**
- adds the optional `scope` key to the catalog and the effective-scope rule (LS1, LS2);
- adds `bin/lora-catalog add --scope`, a `bin/lora-catalog scope ID SCOPE` command and a SCOPE column to `bin/lora-catalog list` (LS3);
- groups the plan prompt's catalog (and the critic's) by scope (LS4);
- adds the hard violation **L8 scope** (LS5);
- keeps one copy of a global and per-beat duplicate in `normalize_plan`, on every beat (LS6);
- adds a scope field, a per-row scope select and `POST /api/loras/scope` to the movie UI's LoRAs tab (LS7);
- makes a re-check name the fix for L8 (LS8);
- in its fix round (Task 5, amendments A1-A4 of "Fix round (review findings)" at the end), allows a style LoRA only the scope `global`, keeps one copy of a LoRA the critic moves in either patch order, prints the L8 hint in Phase 2, Phase 3 and the dry run, and guards a hand-edited `lora_notes`.

Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Repository `/Users/reubenpatterson/local_agent_harness` is never touched by this plan, except through the worktree below.
- Worktree `$S/ls-wt`, branch `lora-scope`, off `c58010e` (plan-budget). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`.
- **This feature is implemented after the sibling branch `per-beat-json` merges.** That branch (spec `docs/superpowers/specs/2026-11-10-per-beat-json-design.md`, in `$S/pj-wt`) rewrites the per_beat clause of `LORA_PICK_PARAGRAPH`, splits `extract_json` and adds tests. This plan's blocks are written against the tree that branch's spec produces: `c58010e` plus per-beat-json Task 1, replayed as `$S/ls-base`. Every line number in this document cites `$S/ls-base`, and every code location is also named by its function or constant.
- **The implementer re-verifies every anchor against the then-current base** before Task 1 ("Before Task 1" runs this document's blocks against a copy of the merged tree and stops on the first Old that does not occur exactly once).
- This plan touches nothing that per-beat-json changes except `LORA_PICK_PARAGRAPH` (its per_beat clause is kept word for word inside the new sentence) and two literals of `tests/test_per_beat_json.py` (PJT1's paragraph and its `CLAUSE`).

**IDs.** Requirements are **LS1-LS9**, tests **LST1-LST11** (and **LST12-LST16** in the fix round), KPIs **LSK1-LSK6**, live checks **LV1-LV5**, fix-round amendments **A1-A4** (edits E58-E80). The new violation is **L8**. At `c58010e` and in the per-beat-json spec, `git grep -nE "\bL8\b|\bLS[0-9]+\b|\bLST[0-9]+\b|\bLSK[0-9]+\b|\bLV[0-9]+\b"` finds nothing.

**Terms.**
- A **video entry** is a catalog entry with `target` `video`; a **stills entry** has `target` `stills`.
- The **effective scope** of a video entry is its `scope` when it has one, else `global` for kind `style` and `beat` for kinds `motion` and `physics` (LS2). **(A1)** A style video entry's scope may only be `global`, and its effective scope is always `global`. A stills entry and a library character (`char:<name>`, kind `character`) have no effective scope.
- A LoRA **may be global** when its effective scope is `global` or `either`, and **may be per-beat** when it is `beat` or `either`.

---

## 0. Scope

### 0.1 What happens today (verified at `$S/ls-base`)

- **The catalog file.** `lora_catalog.validate_entry` (`lora_catalog.py:78-139`) requires exactly the 16 `ENTRY_KEYS` (`:36-38`) and rejects any other key with `entry <id>: unexpected keys <keys>`. A hand-added `"scope"` therefore makes `load_catalog` fail. Every `bin/ltx-movie` run with auto LoRA then stops in `_resolve_story_engine` with `Error: invalid LoRA catalog <path>: entry <id>: unexpected keys scope; run bin/lora-catalog verify` (`bin/ltx-movie:1470`). **If the user has already hand-edited a scope into catalog.json, every auto-LoRA run fails until this change merges** (or the key is removed).
- **The plan prompt.** `build_plan_prompt` (`story_engine.py:1209`) puts `LORA_PICK_PARAGRAPH` (`:584-592`) in the `loras:` line, then `LoRA catalog (pick only from these):` and one `catalog_line` (`:1040`) per compatible entry in one flat list (`:1239`). The paragraph says global holds "at most one style LoRA, plus motion or physics LoRAs that suit the whole movie".
- **The checks.** `lora_checks` (`:2643-2762`) reports L1 (bad id, wrong target, model), L5 (strength), L6 (duplicate), L7 (stills) as hard, and L2-L4 as advisory. L2 includes `beat <k>: L2 style: style LoRA <id> can only be a global pick` (advisory, `:2711-2715`). L6 is reported once per LoRA id, at the first beat where it repeats (`reported_dupes`, `:2717-2752`), so a LoRA in global and on beats 2-9 gives one message.
- **Repair.** `plan_round` (`:4994`) retries a plan whose hard problems include any L violation, with the problems in the retry prompt. `critic_round` (`:5095`) allows lora patches only when the judged round has an L1, L5, L6 or L7 (`:5101-5102`), and lists the compatible video entries flat (`self.catalog_lines`, `:4945`). `apply_patches` (`:4629`) rejects a lora patch that adds a hard L violation ("would break ...").
- **Phase 3.** `_catalog_panel_loras` (`bin/ltx-movie:2035`) adds `global + per_beat[k]` with no de-duplication, but first `_catalog_checks_error` (`:1993`) refuses any hard L violation, so a duplicate never reaches `catalog_loras.json`. `recheck` (`story_engine.py:5509`) exits 2 on any blocking L violation.
- **bin/lora-catalog** has `add`, `list`, `remove` and `verify`; nothing edits an entry. `list` prints the columns ID, KIND, TARGET, STRENGTH, TRIGGERS, BASE_MODELS (`ROW_FORMAT`, `bin/lora-catalog:34`).
- **The movie UI.** The LoRAs tab (`static/movie-ui/index.html:409-431`) has the catalog table (ID, Kind, Target, Strength, Triggers, Base models, Verify, Remove) and the "Add a LoRA" form. `movie_ui_server.py` serves `GET/POST /api/loras`, `POST /api/loras/remove` and `POST /api/loras/verify` (`ROUTES`, `:78-81`); each runs the workspace's own `bin/lora-catalog` (`_h_lora_add` `:1230`, `_lora_action`). The Compose page's LoRA rows (`app.js` `loadCatalog`) pass `--lora PATH:STRENGTH` flags, which the engine sees as pins.
- **Other LoRAs.** `--lora` flags become pins (`_story_pins`, `bin/ltx-movie:1828`) that apply to every panel and are listed in the prompt as "Already applied to every panel by the user". Character LoRAs come from the cast (`fold_characters` pseudo-entries, kind `character`); location LoRAs come from `--location`. Stills picks use stills entries; `--stills-lora` is separate.

### 0.2 Grounding: the pins this change must respect (verified at `$S/ls-base`)

- **LCT1** (`tests/test_lora_catalog.py:65`) pins `len(lora_catalog.ENTRY_KEYS) == 16`, and **LCT3** pins `unexpected keys extra`. So `scope` is a separate `OPTIONAL_ENTRY_KEYS`, never part of `ENTRY_KEYS`, and `SCHEMA_VERSION` stays 1 **[spec choice]**.
- **`_CATALOG_ENTRY_KEYS`** of `bin/ltx-mlx-render:309` and `bin/ltx-story-manifest:227` pin the six keys of a `catalog_loras.json` item. `_catalog_pick` (`bin/ltx-movie:2014`) builds those items field by field, so `scope` never reaches them. Neither file changes.
- **RST8** (`tests/test_story_engine.py:223-262`) and **RST47** (`:2594-2648`) assert that the plan prompt and every dry-run line have no `{` or `}` outside the chained format reference, that `LoRA catalog (pick only from these):` appears exactly when there is a catalog, and that two `catalog_line` texts appear. The group headings have no brace, the header stays, and `catalog_line` does not change.
- **PJT1 and PJT4** (`tests/test_per_beat_json.py`, per-beat-json) pin `LORA_PICK_PARAGRAPH` word for word and its per_beat `CLAUSE`. Both literals are updated (E39, E40); the key sentence `each key is the beat number alone in double quotes: the key of beat 1 is "1";` stays word for word.
- **RST15** (`tests/test_story_engine.py:474-552`), **RST31** (`:1470-1481`) and **DLG18** (`tests/test_dialogue.py:1325`, its LoRA cases at `:1400-1439`) pick the motion fixture `fast-motion` (and `rain-physics`) globally to test L3, L5 and L6. Under the new default they would also get L8. Their fixtures give those two entries `scope="either"`, which keeps what they test (E32, E35, E36). Their per-beat style case becomes the L8 it now is (E34, E37, E38).
- **LCT9** (`tests/test_lora_catalog.py:338-379`) pins the `list` table; it gains the SCOPE column (E16-E18).
- **The route count.** `test_mut18_every_api_route_needs_the_token` (`tests/test_movie_ui_http.py:44`), `test_lu1_the_location_routes_need_the_token` (`tests/test_location_ui.py:66`) and `test_sgt20_the_routes` (`tests/test_movie_ui_seedgen.py:625`), `test_sdt11_the_route_and_its_token` and `test_sdt29_the_characters_route_and_its_token` (`tests/test_movie_ui_seedfolder.py:922`, `:959`) pin `len(srv.ROUTES) == 63`. The new route makes it 64 (E53-E57). `test_mut18` then also checks that the new route needs the token.
- **RST1 and RST62** pin story_engine's imports; this change adds none (it reuses `_lora_catalog(ws)`). **L7j** (no top-level `import re` in bin/ltx-movie) and the **RST50** literal counts are not affected: the one bin/ltx-movie line is a docstring.
- **`tests/test_movie_ui_builder.py`.** `PIPELINE_FILES` (`:223-228`) includes `lora_catalog.py`, `bin/lora-catalog`, `story_engine.py` and `bin/ltx-movie`, so `test_mut26` (`:272-302`; the comment chain ends at `:291`, BASELINE is at `:293`) fails from Task 1's commit until Task 4 moves BASELINE. **(A1-A4)** Task 5 changes all four of those pinned files again, so Task 4 runs after Task 5 and moves BASELINE to Task 5's commit, the last commit that changes a pinned file. **The movie UI files are not pinned**: `movie_ui_server.py` is in `NEW_PY` (`:212`), so `test_mut25` compiles it with `/usr/bin/python3` and scans it for `cgi`, `urllib`, `shell=True`, `match`, `X | Y` annotations, `zip(strict=)` and `load_module(`; the new code has none of them. `static/movie-ui/*` is in no pin list.
- **Merge commit only.** BASELINE will name Task 5's commit (A1-A4; before the fix round it was to name Task 2's). A squash or rebase merge would orphan it, and `test_mut26` would then skip instead of guarding.

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `lora_catalog.py` | **yes** | 1 | `OPTIONAL_ENTRY_KEYS`, `SCOPES`, `DEFAULT_SCOPES`, `entry_scope`; `validate_entry` accepts and checks `scope` (LS1, LS2) |
| D2 | `bin/lora-catalog` | **yes** | 1 | `add --scope`, `scope ID SCOPE`, the SCOPE column of `list`, the docstring (LS3) |
| D3 | `tests/story_engine_testutil.py` | no | 1 | `catalog_entry(..., scope=None)` |
| D4 | `tests/test_lora_catalog.py` | no | 1 | LCT9's table gains the SCOPE column |
| D5 | `tests/test_lora_scope_catalog.py` | no | 1 | new, LST1-LST3 |
| D6 | `story_engine.py` | **yes** | 2 | `LORA_PICK_PARAGRAPH` and the new constants, `catalog_groups`, `drop_duplicate_picks`, `normalize_plan`, `lora_checks` (L8, the notes, no per-beat L2), the critic's grouped catalog, `critic_round`'s L8, `recheck`'s hint (LS4-LS6, LS8) |
| D7 | `bin/ltx-movie` | **yes** | 2 | `_catalog_checks_error`'s docstring says L1-L8 |
| D8 | `tests/test_story_engine.py`, `tests/test_dialogue.py`, `tests/test_per_beat_json.py` | no | 2 | fixtures and the literals the new behaviour changes (0.2) |
| D9 | `tests/test_lora_scope.py` | no | 2 | new, LST4-LST9 |
| D10 | `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js` | no | 3 | the scope route, field, column and select (LS7) |
| D11 | `tests/test_movie_ui_http.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_seedgen.py`, `tests/test_movie_ui_seedfolder.py` | no | 3 | the route count 63 -> 64 (five asserts) |
| D12 | `tests/test_lora_scope_ui.py` | no | 3 | new, LST10-LST11 |
| D13 | `tests/test_movie_ui_builder.py` | no | 4 (after 5) | only `test_mut26`'s BASELINE and comment chain |
| D14 | `lora_catalog.py` | **yes** | 5 | A1: `validate_entry` refuses a style scope other than `global`; `entry_scope` is `global` for every style entry |
| D15 | `bin/lora-catalog` | **yes** | 5 | A1: `add` and `scope` refuse `beat` and `either` for a style LoRA; the docstring and help |
| D16 | `story_engine.py` | **yes** | 5 | A1, A3: `RECHECK_SCOPE_HINT`; A2: `apply_patches` retries a breaking lora patch; A4: `lora_checks` guards `lora_notes` |
| D17 | `bin/ltx-movie` | **yes** | 5 | A3: `_catalog_checks_error` adds the hint after an L8 line |
| D18 | `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js` | no | 5 | A1: 400 for a style add with `beat` or `either`; `syncLoraScope`; a style row shows `global`; the note |
| D19 | `tests/test_lora_scope_catalog.py`, `tests/test_lora_scope.py`, `tests/test_lora_scope_ui.py` | no | 5 | LST1, LST5, LST6, LST8 and LST11 follow A1 and A3 |
| D20 | `tests/test_lora_scope_fix.py` | no | 5 | new, LST12-LST16 |

Untouched: `bin/ltx-mlx-render`, `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/qwen-agent`, `character_lib.py`, `location_lib.py`, `movie_ui_lib.py`, `scripts/deploy/*`, every other bin, every other test.

### 0.4 Out of scope

- A scope for pins (`--lora`), character LoRAs, location LoRAs, stills entries and `--stills-lora` (Decision 9).
- Any other duplicate: a pick that repeats a pin, or a LoRA listed twice in the same list. These stay L6 hard, reported once per id as today (follow-up F1).
- Two style LoRAs on one panel when one of them is a per-beat pick of a style entry scoped `beat` or `either` (follow-up F2). **(A1)** This case no longer exists: a style entry's scope may only be `global`, so every per-beat style pick is the hard L8.
- **(A1)** Rendering a per-beat style pick. Phase 3 applies style LoRAs from `global` only, and `bin/ltx-story-manifest` refuses two style LoRAs on one panel; neither changes.
- Automatic repair of an L8 that is not a duplicate. The planner retry and the critic repair it (Decision 5; follow-up F4).
- Re-normalizing a saved `plan.json`. A saved plan is checked as it is (Decision 7).
- Editing any other catalog field from the UI or the CLI.
- Any model call, server, render or download in tests, and any agent access to macstudio.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| LSK1 | The full suite has no failure beyond the baseline (expected `2 failed, 2734 passed, 2 skipped`, per-beat-json PJK1; P0 is whatever "Before Task 1" records). After Task 4 (which runs after Task 5) it is `2 failed, P0 + 16 passed, 2 skipped`, with the gate line `lost 0 (listed 0, unexpected 0); new tests 16, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS` | gate, V1 |
| LSK2 | Between the merged base and the final commit, the pinned files that change are `lora_catalog.py` (numstat `27 1`), `bin/lora-catalog` (`72 9`), `story_engine.py` (`140 35`) and `bin/ltx-movie` (`6 2`) (with Task 5; before it, `18 1`, `64 9`, `106 16` and `1 1`); the other non-docs files are exactly those of 0.3 with the numstats of V1 | V1 |
| LSK3 | A catalog without any `scope` loads and saves byte-identically; a plan with no global-and-per-beat duplicate gives a byte-identical `plan.json`; every behaviour change is one of Section 4's rows C1-C12, and each is pinned by a test | LST1, LST4-LST8, LST12-LST16, the unchanged suites |
| LSK4 | On macstudio, a new plan for the user's fight story never puts the fight LoRA (scope `beat`, by default or by hand) in `loras.global` of the final `plan.json`, and a LoRA picked both ways leaves one copy and a `lora_notes` line | LV3, LV4 |
| LSK5 | On macstudio, every saved story that a default scope now forbids is listed, its re-check names L8 and the hint, and for a motion or physics LoRA `bin/lora-catalog scope ID either` makes the same re-check pass (A1: a style LoRA picked for a beat needs `--force-story`) | LV2 |
| LSK6 | On macstudio, the movie UI sets, shows and clears a scope, and `bin/lora-catalog list` shows the same value | LV5 |

Every LS requirement and every LST test is a must-have. There are no nice-to-haves.

---

## 1. Decisions

1. **`scope` is one optional key, outside `ENTRY_KEYS` [spec choice].**
   - `OPTIONAL_ENTRY_KEYS = ("scope",)`, `SCOPES = ("global", "beat", "either")`. `ENTRY_KEYS` (16 keys) and `SCHEMA_VERSION` (1) do not change, so every existing catalog.json stays valid, and `save_catalog` writes the key back when it is there.
   - **A value outside `SCOPES` is a catalog error**, like a bad `kind`: `entry <id>: scope must be one of global, beat, either, got <repr>`. That includes `null`, `""` and `"Beat"`. To use the default, remove the key (or run `bin/lora-catalog scope ID default`). A typo must not silently become the default.
   - **(A1) A style video entry's scope may only be `global`**: `beat` or `either` there is the catalog error `entry <id>: scope must be global for a style LoRA, which applies to every panel, got <repr>`. Phase 3 never renders a per-beat style pick.
   - **A stills entry may carry a scope; it is accepted and ignored** [spec choice]. A stills LoRA is only ever the `stills` pick, so the field means nothing there. Rejecting it would make a user's hand edit of "every entry" break every run. `bin/lora-catalog` and the UI never write a scope on a stills entry (LS3, LS7).
   - The sha256, bytes and file checks are about the LoRA file, not about catalog.json, so they do not change.
2. **The defaults are `style` -> `global`, `motion` -> `beat`, `physics` -> `beat` (the user's decision).**
   - `DEFAULT_SCOPES` holds them in one place, `lora_catalog.py`. story_engine reads them through `entry_scope`, and the movie UI's JavaScript mirrors them in `LORA_SCOPE_DEFAULTS`, which LST11 compares with `DEFAULT_SCOPES`.
   - Today a motion or physics LoRA may go in either place. Under the default it may only be per-beat. Section 4 lists exactly what that changes. **To restore a global motion or physics LoRA, give it the scope `either` (the planner may still put it on one beat) or `global` (only for the whole movie):** `bin/lora-catalog scope ID either`, or the row select in the movie UI.
3. **`entry_scope(entry)` is the one rule [spec choice].** It returns the entry's `scope`, else `DEFAULT_SCOPES[kind]`, for a video entry (**A1**: `global` for every style video entry, whatever its scope); `None` for a stills entry and for a kind with no default (a folded `char:` entry). Everything that needs a scope calls it: `catalog_groups`, `lora_checks`, `drop_duplicate_picks` and `bin/lora-catalog list`.
4. **The prompt lists each LoRA under the places where it may go.**
   - Under the existing header `LoRA catalog (pick only from these):` come `May be global picks (applied to every panel):` with every video entry that may be global, then `May be per-beat picks (applied to their beat only):` with every video entry that may be per-beat, then, only when there is one, `Stills LoRAs (only for the stills pick):` with the stills entries. These are the two groups the user asked for, plus the stills entries, which belong in neither.
   - **An `either` entry is listed in both groups** [spec choice]. That is what "either" means, and it keeps two groups. It costs one extra catalog line per `either` entry.
   - **An empty group says so** with `- none, so global stays empty` or `- none, so per_beat stays empty` [spec choice], so the model never reads a heading with nothing under it as "anything goes".
   - Each line is the unchanged `catalog_line`, and the order inside a group is today's (compatible entries sorted by id). No line has a brace (RST8, RST47, deploy gate X2).
   - `LORA_PICK_PARAGRAPH` says it in words: "The catalog lists each LoRA under the places where it may go", global picks are "taken only from the LoRAs that may be global picks", per_beat picks "taken only from the LoRAs that may be per-beat picks", and "a LoRA in global is never also in per_beat". per_beat is no longer limited to "motion or physics picks", because a style entry scoped `beat` or `either` may now be one. **(A1)** That reason is withdrawn: a style entry is always global, so the per-beat group never lists a style LoRA, and "taken only from the LoRAs that may be per-beat picks" now means motion or physics picks. The paragraph keeps its Task 2 text, because it agrees with Phase 3 as it is and a change would re-touch PJT1, PJT4 and LST4 for no change in behaviour. per-beat-json's key sentence stays word for word.
   - **The critic gets the same groups** [spec choice]. When lora patches are allowed, its catalog lines are `catalog_groups` of the compatible video entries (so no stills group), and its `index 0 ... or a beat number` instruction is unchanged.
5. **L8 is hard and repaired by the planner retry and the critic.**
   - `lora_checks` reports `plan: L8 scope: <id> may only be a per-beat pick (its catalog scope is beat), but it is a global pick; remove it from global and pick it for the beats that need it` for a global pick whose effective scope is `beat`. It reports `beat <k>: L8 scope: <id> may only be a global pick (its catalog scope is global), but it is a pick for this beat; remove it from this beat, or move it to global if it suits the whole movie` for each beat k whose pick has effective scope `global`.
   - **One message per misplaced pick, and for every beat** [spec choice]. A global-scope LoRA on beats 2-9 gives eight messages, unlike L6's one. Each names its own beat, so the critic patches each beat.
   - L8 is checked only for picks that passed L1 (a known, compatible video entry), so a bad id never gives a second message.
   - **L8 is the next free id**: L1-L7 exist and `git grep` finds no L8. `parse_violation` (`story_engine.py:411`) already reads it through `_VIOLATION_RE`'s `[A-Z]+\d+` (`:149`), so it needs no change; the places that list L ids by name are `critic_round`'s lora ids, `lora_checks`' docstring, `_catalog_checks_error`'s docstring (`L1-L7`) and RST15's comment, and all four are updated.
   - L8 is blocking (it is not in `NON_BLOCKING_IDS`). `plan_round` already retries a plan with any hard L violation and lists it in the retry prompt. `critic_round` gains L8 in the ids that allow lora patches. `apply_patches` already rejects any patch that would add an L8 (`would break plan: L8 scope: ...`), so the critic can never move a LoRA into a forbidden place. **(A2)** A move takes two patches, and the order that adds the new copy first breaks L6 until the old copy goes, so `apply_patches` tries a lora patch that would break the plan again after the others; both orders give the same plan.
6. **The per-beat L2 advisory is removed [spec choice].** `beat <k>: L2 style: style LoRA <id> can only be a global pick` would now be either a duplicate report (a default-scoped style per-beat pick is L8) or wrong (a style entry the user scoped `beat` or `either` may be per-beat). **(A1)** It stays removed: a style entry can no longer be scoped `beat` or `either`, so every per-beat style pick is the hard L8 on the same beat, and the advisory would only report that pick a second time at a weaker severity. The other L2 advisory, `plan: L2 style: <n> style LoRAs for every panel (...); at most 1`, does not change.
7. **A global-and-per-beat duplicate is normalized in `normalize_plan`, not repaired by the critic [spec choice].**
   - **Why normalization.** The repair is deterministic and loses nothing: a global pick already applies the LoRA to that panel. It costs no model call. It fixes every beat at once: the critic has at most 8 patches per round and 2 rounds, so a LoRA on 15 beats could not be repaired. And critic lora patches only start after a hard L violation, which costs a round.
   - **Which copy goes.** When the LoRA may be global (effective scope `global` or `either`), the per-beat copies go, on every beat 1 to N that has one, as the user decided. A beat whose list becomes empty loses its key. **When the effective scope is `beat`, the global copy goes instead, and the per-beat picks stay** [spec choice; open question Q1]. Dropping the per-beat copies there would leave a global pick that is itself L8, and lose the beats the planner chose for the LoRA. Dropping the global copy leaves the plan a beat-scoped LoRA is meant to have.
   - **The plan records it.** Each normalized LoRA gives one note, `plan: L6 duplicate: <id> was picked both globally and for beat(s) <k, ...>; the pipeline kept the global pick and dropped the per-beat copies` (or `...; its catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global pick`). The notes are stored in `plan["lora_notes"]`, a key that exists only when there is a note, so every other `plan.json` is byte-identical. `lora_checks` adds them to the advisories, so they reach `story_checks.json`, the critic's advisory list and the re-check, like `speech_notes`.
   - Only beat keys `"1"` to `"N"` (N beats) count; an out-of-range key stays for L1. Only picks of a known video entry count; anything else is left for L1. Strengths are not compared: the kept copy keeps its own strength.
   - **A saved plan is not normalized**: `load_plan` reads plan.json as it is, so a saved duplicate stays L6 hard on a re-check and in Phase 3, exactly as today.
8. **Phase 3 does not change [spec choice].** `_catalog_panel_loras` still adds `global + per_beat[k]`, but `_catalog_checks_error` runs first and refuses any hard L6 or L8. So a duplicate can never reach `catalog_loras.json`, and a de-duplication there would be dead code.
   - **(A1)** `_catalog_panel_loras` takes style LoRAs from `global` only, so a per-beat style pick would be dropped without a message. Under A1 every such pick is the hard L8, which `_catalog_checks_error` refuses first, so Phase 3 still needs no change.
   - **(A3)** `_catalog_checks_error` adds `RECHECK_SCOPE_HINT` on a line of its own when its first hard violation is an L8. That is the one change to Phase 2, Phase 3 and the dry run.
9. **What has no scope.**
   - **Pins (`--lora`)**: the user's explicit choice, applied to every panel whatever the entry's scope. L8 never names a pin, and L6 for a pick that repeats a pin does not change.
   - **Character and location LoRAs** are cast with `--character` and `--location`, never picked from the catalog, and still count for L3 and L4.
   - **Stills entries and `--stills-lora`**: the `stills` pick and L7 do not change; a stills entry's scope is ignored (Decision 1).
   - **The dry run** prints the rendered plan prompt, which now holds the groups. No other dry-run line changes; `Catalog LoRAs: N compatible entries in <path>` stays.
10. **bin/lora-catalog** [spec choice]:
    - `add` takes `--scope {global,beat,either}`. Without it, no `scope` key is written. With `--target stills` it is refused (exit 2) before anything is read. The key is written after `added_at`. The `added ...` line does not change.
    - `scope ID {global,beat,either,default}` sets the scope, or removes the key for `default`, under the catalog lock, and prints `<id>: scope <scope> in <path>` or `<id>: scope <effective> (the default for a <kind> LoRA) in <path>`. It refuses a `char:` id, a stills entry and an unknown id (exit 2).
    - **(A1)** `add --kind style --scope beat|either` (for a video LoRA) exits 2 before anything is read, and `scope ID beat|either` for a style entry exits 2 and writes nothing; `global` and `default` stay allowed for a style entry.
    - `list` gains a SCOPE column after TARGET with the effective scope, and `-` for a stills entry and a character. `list --json` does not change: its entries are the raw catalog entries, so the UI can tell a set scope from a default.
11. **The movie UI** [spec choice]:
    - The add form gets a Scope select after Target (`default for the kind`, `global`, `beat`, `either`). It is disabled when the target is stills, and the body then sends `scope: null`.
    - The catalog table gets a Scope column after Target. A video row has a select `default (<kind default>)`, `global`, `beat`, `either`, showing the entry's scope or `default`; changing it posts `POST /api/loras/scope` and reloads the table and the Compose LoRA list. A stills row shows `-`.
    - The server checks the value (400 `scope must be global, beat, either or null` for add, 400 `scope must be global, beat, either or default` for the new route) and passes `--scope X` or `scope ID X` to the workspace's bin/lora-catalog, which writes the file. The server does not import lora_catalog (movie-ui GC7); `LORA_SCOPES` mirrors `SCOPES`, and LST10 compares them.
    - **(A1)** The add form's Scope select is also disabled when Kind is `style` (`syncLoraScope`, run on a Target or Kind change and once at setup), and a disabled select sends `scope: null`. A style row's Scope cell is the text `global`, with no select. `_h_lora_add` answers 400 `scope must be global or null for a style LoRA` for kind `style` with scope `beat` or `either`. `POST /api/loras/scope` does not change: the server never reads the catalog, so it does not know an entry's kind; bin/lora-catalog refuses (exit 2) and the route returns that run with 200, like every other refusal of a run (LS7). The UI never sends it, because a style row has no select.
12. **A re-check names the fix for L8.** When a blocking L8 stops a re-check, `recheck` prints `RECHECK_SCOPE_HINT` after the existing L line, because the existing line ("restore or re-add the LoRA files ...") does not help with a scope. **(A1, A3)** The hint gets the text of Section 3, which no longer suggests `either` for a style LoRA, and bin/ltx-movie prints it too when its catalog-checks error names an L8.
13. **Four tasks [spec choice].** Task 1 is the catalog and the CLI (inert for stories), Task 2 the story engine, Task 3 the movie UI, Task 4 the BASELINE move. Each task has its own new test file, so every gate sees only tests that its code makes pass. **(A1-A4)** The fix round adds Task 5, one code commit with its own new test file, run after Task 3; Task 4 then runs after Task 5.

---

## 2. Requirements

- **LS1 (the catalog field).** `lora_catalog.OPTIONAL_ENTRY_KEYS == ("scope",)`, `SCOPES == ("global", "beat", "either")`, `DEFAULT_SCOPES == {"style": "global", "motion": "beat", "physics": "beat"}`. `validate_entry` accepts the keys `ENTRY_KEYS` plus, optionally, `scope`; any other key is still `unexpected keys`. When `scope` is present and not in `SCOPES`, it raises `CatalogError("entry <id>: scope must be one of global, beat, either, got <repr>")`. This holds for video and stills entries. **(A1)** Then, for a video entry of kind `style` whose `scope` is present and not `global`, it raises `CatalogError("entry <id>: scope must be global for a style LoRA, which applies to every panel, got <repr>")`. `ENTRY_KEYS`, `SCHEMA_VERSION`, `load_catalog` and `save_catalog` do not change, so a catalog without a scope loads and saves byte-identically, and a scope survives a save.
- **LS2 (the effective scope).** `lora_catalog.entry_scope(entry)` returns `None` when `entry["target"] != "video"` or `entry["kind"]` is not in `DEFAULT_SCOPES`; else `entry.get("scope") or DEFAULT_SCOPES[entry["kind"]]`. **(A1)** Before that last rule, it returns `"global"` when `entry["kind"] == "style"`.
- **LS3 (bin/lora-catalog).**
  - `add --scope S` with `S` in `SCOPES` writes `"scope": S` as the entry's last key; without `--scope` no key is written. With `--scope` and `--target stills` it exits 2 with `Error: --scope applies only to video LoRAs; a stills LoRA is only ever the stills pick` and the catalog is unchanged. Another value is an argparse error (exit 2).
  - `scope ID S` with `S` in `SCOPES + ("default",)`:
    - with `char:` in front of ID: exit 2, `Error: <ID> is a library character; it is cast with bin/ltx-movie --character and has no scope`;
    - with no such entry (also when the catalog directory is missing): exit 2, `Error: no catalog entry <ID>`;
    - for a stills entry: exit 2, `Error: <ID> is a stills LoRA; scope applies only to video LoRAs`;
    - an invalid catalog: exit 2 with load_catalog's error;
    - else, under the catalog lock, it sets `"scope": S` (as the last key) or, for `default`, removes the key, saves, exits 0 and prints `<ID>: scope <S> in <path>` or `<ID>: scope <effective> (the default for a <kind> LoRA) in <path>`.
  - **(A1)** `add --kind style --scope S` with `S` `beat` or `either` exits 2 with `Error: --scope <S> applies only to motion and physics LoRAs; a style LoRA is only ever a global pick` (checked after the stills refusal), and the catalog is unchanged. `scope ID S` with `S` `beat` or `either` for a style entry exits 2 with `Error: <ID> is a style LoRA; a style LoRA is only ever a global pick, so its scope is global or default` (checked after the stills refusal), and nothing is written.
  - `list` prints `ROW_FORMAT = "%-24s %-9s %-7s %-7s %-14s %-24s %s"` with the header cell `SCOPE` after `TARGET` and the cell `entry_scope(entry) or "-"`. `list --json` is unchanged.
- **LS4 (the grouped catalog).** `LORA_PICK_PARAGRAPH` is the text of Section 3. `catalog_groups(ctx, entries)` returns `[LORA_GLOBAL_GROUP]`, the `catalog_line`s of the video entries whose effective scope is `global` or `either` (or `[LORA_GLOBAL_NONE]`), `LORA_BEAT_GROUP`, the lines of those whose effective scope is `beat` or `either` (or `[LORA_BEAT_NONE]`), then `[LORA_STILLS_GROUP]` plus the stills lines when there is a stills entry. Entries keep their order. `build_plan_prompt` joins `catalog_groups(ctx, compatible)` with `\n` where it joined the `catalog_line`s. `_Run.catalog_lines` is `catalog_groups(ctx, <compatible video entries>)` when lora patches are allowed, else `None`.
- **LS5 (L8).** In `lora_checks`, after the picks are resolved: for each resolved global pick whose `entry_scope` is `beat`, the hard `LORA_SCOPE_GLOBAL % _q(id)`; then for each beat k in ascending order and each resolved pick of that beat whose `entry_scope` is `global`, the hard `LORA_SCOPE_BEAT % (k, _q(id))`. Pins are never checked for scope. The per-beat L2 advisory is gone. `critic_round` allows lora patches when the judged round has an L1, L5, L6, L7 or L8. **(A2)** `apply_patches` applies the lora patches in order; one that would break the plan is put back and tried again after the others, in passes, until all are applied or a pass applies none; those left are rejected with the reason of their last try.
- **LS6 (duplicates).** `drop_duplicate_picks(ctx, picks, by_id, n)` runs in `normalize_plan` right after the picks are built (auto LoRA on, `loras` an object). For each distinct id, in global order, of a global pick that is a pick (`_is_pick`) of a known video entry, let B be the sorted beats k in 1..n whose per_beat list holds a pick with that id. When B is empty, nothing happens. When the entry's effective scope is `beat`, every global pick with that id is removed and the note is `LORA_DUPLICATE_GLOBAL % (_q(id), _nums(B))`. Otherwise every pick with that id is removed from those beats, a beat left empty loses its key, and the note is `LORA_DUPLICATE_BEATS % (_q(id), _nums(B))`. `plan["lora_notes"]` is the list of notes, set (after `plan["loras"]`) only when it is not empty. `lora_checks` adds `plan.get("lora_notes", [])` to its advisories, after the L5 advisories and before L2. **(A4)** Only when `lora_notes` is a list, and only its strings. Recorded: the normalization removes every copy of the id from a list it changes (a per-beat list, or global for scope `beat`), so a list holding the id twice loses both; and `by_id` is the whole catalog, so an incompatible video entry picked both ways is normalized too (its pick is L1 anyway). Both are harmless.
- **LS7 (the movie UI).**
  - `ROUTES` gains `("POST", r"/api/loras/scope", "h_lora_scope", "/api/loras/scope")` after the verify route (64 routes).
  - `_h_lora_add` reads `scope` (absent or `null`: none); any other value outside `LORA_SCOPES = ("global", "beat", "either")` is 400 `scope must be global, beat, either or null`; a scope adds `--scope <scope>` after `--alpha` (and before `--no-arch-check`).
  - `_h_lora_scope` takes `{"ws", "id", "scope"}`: `id` must be a string (400 `id must be a string`), safe and not start with `-` (`_check_arg`); `scope` must be one of `LORA_SCOPES + ("default",)` (400 `scope must be global, beat, either or default`). It runs `bin/lora-catalog scope <id> <scope>` with the light timeout and returns 200 `{"run": ...}`, whatever the exit code, like remove.
  - **(A1)** `_h_lora_add`: after the scope value check, kind `style` with scope `beat` or `either` is 400 `scope must be global or null for a style LoRA`, and nothing runs.
  - The HTML and JavaScript of Section 3 (with Task 5's A1 changes).
- **LS8 (the re-check hint).** When `recheck`'s blocking list has an L8, it prints `RECHECK_SCOPE_HINT` to stderr after the existing L-violation line, then returns 2 as today. **(A3)** bin/ltx-movie's `_catalog_checks_error` (Phase 2, Phase 3 and the dry run) ends its line with `"\n" + RECHECK_SCOPE_HINT` when `parse_violation(hard[0])["id"] == "L8"`. Only `hard[0]` counts, because that line names only `hard[0]`.
- **LS9 (nothing else changes).** Phase 3 (except A3's hint line), `catalog_loras.json`, the renderers, pins, `--stills-lora`, character and location LoRAs, plan budgets, the dry run's lines other than the rendered prompt, `bin/lora-catalog remove` and `verify`, and `list --json` behave as today. For a catalog and a plan that Section 4 does not name, every check, file and exit code is today's.

## 3. Messages and text (exact)

| Constant | Text (`%` arguments) | Where |
|---|---|---|
| `LORA_PICK_PARAGRAPH` | `an object with the keys global, per_beat and stills. Each pick is an object with the keys id and strength, taken from the LoRA catalog below; strength must lie inside that entry's range. The catalog lists each LoRA under the places where it may go. global is a list of picks applied to every panel, taken only from the LoRAs that may be global picks: at most one style LoRA, plus motion or physics LoRAs that suit the whole movie. per_beat maps each beat number to a list of picks for that beat only, taken only from the LoRAs that may be per-beat picks, and each key is the beat number alone in double quotes: the key of beat 1 is "1"; a LoRA in global is never also in per_beat, and every beat may have at most one motion or physics LoRA in total, counting global. stills is a list of at most one stills LoRA.` | the plan prompt's `loras:` line |
| `LORA_GLOBAL_GROUP` | `May be global picks (applied to every panel):` | plan and critic catalog |
| `LORA_GLOBAL_NONE` | `- none, so global stays empty` | an empty global group |
| `LORA_BEAT_GROUP` | `May be per-beat picks (applied to their beat only):` | plan and critic catalog |
| `LORA_BEAT_NONE` | `- none, so per_beat stays empty` | an empty per-beat group |
| `LORA_STILLS_GROUP` | `Stills LoRAs (only for the stills pick):` | plan catalog, only with a stills entry |
| `LORA_SCOPE_GLOBAL` | `plan: L8 scope: %s may only be a per-beat pick (its catalog scope is beat), but it is a global pick; remove it from global and pick it for the beats that need it` (`_q(id)`) | hard |
| `LORA_SCOPE_BEAT` | `beat %d: L8 scope: %s may only be a global pick (its catalog scope is global), but it is a pick for this beat; remove it from this beat, or move it to global if it suits the whole movie` (beat, `_q(id)`) | hard |
| `LORA_DUPLICATE_BEATS` | `plan: L6 duplicate: %s was picked both globally and for beat(s) %s; the pipeline kept the global pick and dropped the per-beat copies` (`_q(id)`, `_nums(beats)`) | `plan["lora_notes"]`, advisory |
| `LORA_DUPLICATE_GLOBAL` | `plan: L6 duplicate: %s was picked both globally and for beat(s) %s; its catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global pick` | `plan["lora_notes"]`, advisory |
| `RECHECK_SCOPE_HINT` | **(A1, A3; Task 5's text)** `An L8 violation is a pick placed where its catalog scope does not allow: give a motion or physics LoRA the scope either with bin/lora-catalog scope ID either (or the Scope select of its row in the movie UI's LoRAs tab), or pass --force-story to regenerate; a style LoRA is only ever a global pick, so a style LoRA picked for a beat needs --force-story.` (Tasks 2-3's text was `An L8 violation is a pick placed where its catalog scope does not allow: set the LoRA's scope to either with bin/lora-catalog scope ID either (or in the movie UI's LoRA catalog), or pass --force-story to regenerate.`) | stderr: the re-check, and (A3) bin/ltx-movie's catalog-checks error after an L8 line |
| (A1) `validate_entry` | `entry %s: scope must be global for a style LoRA, which applies to every panel, got %r` (id, scope) | `CatalogError` |
| (A1) `_h_lora_add` | `scope must be global or null for a style LoRA` | 400 |
| (A3) `_catalog_checks_error` | `Error: plan.json LoRA picks fail the catalog checks (%s); rerun with --force-story or --no-auto-lora` (`hard[0]`), then, when `hard[0]` is an L8, a newline and `RECHECK_SCOPE_HINT` | stderr, Phase 2, Phase 3 and the dry run |

`_q(id)` is `'<id>'`, and `_nums([1, 3])` is `1, 3`.

The catalog block of a plan prompt with film-grain (style), fast-motion (motion), rain-physics (physics, scope either) and ink-stills (stills), and no pins:
```
LoRA catalog (pick only from these):
May be global picks (applied to every panel):
- film-grain: style LoRA for video, default strength 0.8, ...
- rain-physics: physics LoRA for video, default strength 0.8, ...
May be per-beat picks (applied to their beat only):
- fast-motion: motion LoRA for video, default strength 0.8, ...
- rain-physics: physics LoRA for video, default strength 0.8, ...
Stills LoRAs (only for the stills pick):
- ink-stills: style LoRA for stills, default strength 0.8, ...
```

bin/lora-catalog (stdout for success, stderr after `Error: ` for exit 2):

| Case | Output |
|---|---|
| `scope fight-motion beat` | `fight-motion: scope beat in <catalog path>` |
| `scope fight-motion default` | `fight-motion: scope beat (the default for a motion LoRA) in <catalog path>` |
| `scope char:kyra beat` | `Error: char:kyra is a library character; it is cast with bin/ltx-movie --character and has no scope` |
| `scope ink-stills beat` | `Error: ink-stills is a stills LoRA; scope applies only to video LoRAs` |
| `scope nope beat` | `Error: no catalog entry nope` |
| `add ... --target stills --scope global` | `Error: --scope applies only to video LoRAs; a stills LoRA is only ever the stills pick` |
| (A1) `add ... --kind style --target video --scope beat` | `Error: --scope beat applies only to motion and physics LoRAs; a style LoRA is only ever a global pick` |
| (A1) `scope film-grain either` (a style entry) | `Error: film-grain is a style LoRA; a style LoRA is only ever a global pick, so its scope is global or default` |
| (A1) `scope film-grain default` | `film-grain: scope global (the default for a style LoRA) in <catalog path>` |
| (A1) catalog.json with `"scope": "either"` on a style video entry | `Error: <path>: entry <id>: scope must be global for a style LoRA, which applies to every panel, got 'either'` |
| catalog.json with `"scope": "globl"` | `Error: <path>: entry <id>: scope must be one of global, beat, either, got 'globl'` (any command that loads the catalog; bin/ltx-movie prints its own `Error: invalid LoRA catalog ...` around it) |

The movie UI:
- the form field `<label>Scope <select id="l-scope"><option value="">default for the kind</option><option>global</option><option>beat</option><option>either</option></select></label>`, followed by a `muted` note;
- the column header `<th>Scope</th>` after `<th>Target</th>`;
- the row select `default (<default>)`, `global`, `beat`, `either` (class `l-row-scope`);
- **(A1)** a style video row has no select: its Scope cell is the text `global`. The form's Scope select is disabled when Target is `stills` or Kind is `style`, and its note reads `Where the story planner may put a motion or physics video LoRA: global applies it to every panel, beat only to the beats it suits, either lets the planner choose; the default is beat. A style LoRA is always global, and a stills LoRA has no scope, so the select is off for both.`

## 4. What changes for existing catalogs and plans

| # | Before | After | How to get today's behaviour back |
|---|---|---|---|
| C1 | A hand-added `"scope"` makes every auto-LoRA run fail (`unexpected keys scope`) | Accepted; a bad value is a catalog error | - |
| C2 | A motion or physics LoRA may be a global pick | Without a scope it may only be per-beat; a new plan that picks it globally gets L8, which the plan retry or the critic repairs | `bin/lora-catalog scope ID either` (or `global`), or the row select |
| C3 | A saved `plan.json` with a global motion or physics pick re-checks clean and renders | Its re-check (any rerun without `--force-story`) exits 2 with `L8` and `RECHECK_SCOPE_HINT`; Phase 3 (and Phase 2 and the dry run) refuses it with `Error: plan.json LoRA picks fail the catalog checks (plan: L8 scope: ...); rerun with --force-story or --no-auto-lora` and, on the next line (A3), `RECHECK_SCOPE_HINT` | as C2, then rerun; or `--force-story` |
| C4 | A per-beat style pick is the advisory `L2 style: ... can only be a global pick` (and Phase 3 drops it without a message) | **(A1)** Always the hard L8 (a style LoRA's scope is always global), repaired by the plan retry or the critic; a saved plan with one fails its re-check and Phase 3 (C3) | `--force-story` (or hand-edit plan.json to move the pick to `global`); no scope makes it allowed |
| C5 | A LoRA picked globally and for a beat is the hard L6 at its first beat | A new plan keeps one copy (Decision 7) and records an advisory `lora_notes` line; a saved plan is still L6 | - |
| C6 | The plan prompt lists the catalog flat, and its paragraph says per_beat holds motion or physics picks | The paragraph of Section 3 and the grouped catalog, in every mode, whenever the catalog paragraph is shown (also for a style-only catalog) | - |
| C7 | The critic's lora instruction lists the video entries flat | Grouped (LS4) | - |
| C8 | `bin/lora-catalog list` has 6 columns | 7 (SCOPE) | - |
| C9 | The movie UI's catalog table has no Scope column, the form no Scope field | Both, and `POST /api/loras/scope` (64 routes); (A1) a style row shows `global` with no select, and the form's Scope select is off for a style or stills LoRA | - |
| C10 | (A1; only this branch could write it) A style video entry with `"scope": "beat"` or `"either"` | A catalog error: every command that loads the catalog, and every auto-LoRA run, stops with `... entry <id>: scope must be global for a style LoRA, which applies to every panel, got ...`; `bin/lora-catalog add` and `scope`, and the movie UI's add route, refuse to write it | remove the key or set it to `global` in catalog.json by hand (bin/lora-catalog cannot load the catalog to do it) |
| C11 | (A2) The critic's two patches that move a LoRA between global and a beat lose it when the patch that adds the new copy comes first (it breaks L6 and is rejected, the other is applied) | The rejected patch is tried again after the others, so both orders move the LoRA; a patch that breaks the plan in every order is still rejected | - |
| C12 | (A4) A plan.json whose `lora_notes` is `null` makes Phase 3 report malformed picks; a string adds one advisory per character | Ignored unless it is a list, and then only its strings count | - |

**Unchanged** for every catalog: catalog.json bytes (nothing rewrites the file unless `add`, `remove` or `scope` runs), the plan budget, every check of a plan that has no misplaced pick and no duplicate, `catalog_loras.json`, the renders, pins, characters, locations and stills.

**For a catalog whose entries are all style and have no scope:** the rows that apply are C1, C4 (a per-beat style pick, in a new plan or a saved one), C5 (a style duplicate), C6, C7 and C8 (and C9-C12); C2 and C3, which are about motion and physics LoRAs, do not, except that a saved per-beat style pick is refused as C3 describes.

## 5. Tests

**New tests** (every model call goes to the fake bin/qwen-agent; bin/lora-catalog and bin/ltx-movie --dry-run run as subprocesses under the temp catalog; the UI tests use movie_ui_testutil's stub workspace):

| Test | File | Pins |
|---|---|---|
| LST1 `test_lst1_the_scope_field_and_its_defaults` | `tests/test_lora_scope_catalog.py` | LS1, LS2: the constants; `entry_scope` for every kind, an explicit scope, a stills entry and a `char:` entry; every scope valid on video and stills entries; `globl`, `None`, `["beat"]`, `""`, `Beat` rejected with the exact message; `unexpected keys extra` still; a scope-less catalog loads and saves byte-identically; a scope survives a save as the last key |
| LST2 `test_lst2_add_scope_and_the_list_column` | same | LS3: `add --scope either` writes the key last; no `--scope`, no key; the stills refusal (exact stderr, catalog unchanged); a bad value is an argparse error; the exact `list` table with `either`, `global`, `-` and `beat`; `list --json` entries are raw |
| LST3 `test_lst3_the_scope_subcommand` | same | LS3: `scope` on an empty catalog, set (exact stdout, the entry otherwise unchanged), change, `default` (exact stdout, the key removed, the entries equal the originals); the three refusals with exact stderr; a bad value; an invalid catalog; nothing written on an error |
| LST4 `test_lst4_the_plan_prompt_groups_the_catalog` | `tests/test_lora_scope.py` | LS4: `LORA_PICK_PARAGRAPH` word for word, no brace; the exact block for four entries (an either entry in both groups); no_stills with a pin; the two empty-group lines; no brace in any mode |
| LST5 `test_lst5_a_pick_its_scope_does_not_allow_is_l8` | same | LS5: the exact global and per-beat L8 (one per beat); allowed picks; `parse_violation` of both; `either` allows both places; `beat` on a style and `global` on a motion swap them; a pin is exempt; L2's global count unchanged; nothing without auto LoRA |
| LST6 `test_lst6_a_global_and_per_beat_duplicate_keeps_one_copy` | same | LS6: for scope global and either, the per-beat copies of beats 1-3 go (an emptied key goes, another pick stays) with the exact note, and `lora_checks` gives no L6 and the note as an advisory; scope beat keeps the per-beat picks and drops the global one; out-of-range keys and unknown ids are untouched and give no `lora_notes`; a plan with no duplicate still ends with `speech_notes`; nothing without auto LoRA |
| LST7 `test_lst7_the_critic_moves_a_per_beat_lora_out_of_global` | same | LS4, LS5: a shots run whose plan picks fast-motion globally: the plan retry names L8, the critic prompt has the L8 line and the grouped catalog (no stills line), two lora patches apply, round 1's plan has fast-motion on beat 2 only, rc 0; a patch that puts it in global is rejected as `would break plan: L8 ...` |
| LST8 `test_lst8_recheck_names_l8_and_either_restores_a_saved_plan` | same | C3, LS8: a story saved under scope either re-checks with the default catalog: exit 2, the L8 bullet, the existing L line then `RECHECK_SCOPE_HINT`, story_checks.json hard `[L8]`; with scope either again: 0; a missing entry (L1): exit 2 and no hint |
| LST9 `test_lst9_the_dry_run_prints_the_grouped_catalog` | same | LS4, LS9: the real `bin/ltx-movie --dry-run --shots` prints the grouped block and today's `Catalog LoRAs:` line, and creates no story directory |
| LST10 `test_lst10_the_scope_endpoints` | `tests/test_lora_scope_ui.py` | LS7: the route; `LORA_SCOPES == lora_catalog.SCOPES`; the exact add argv with and without a scope; four bad add scopes give 400; the four scope values give `["scope", "fight", <scope>]`; four bad scope bodies give the exact 400 and run nothing; no token gives 401 |
| LST11 `test_lst11_the_static_page_sets_the_scope` | same | LS7: the form select (once, after Target, before Add), the column header, `LORA_SCOPE_DEFAULTS == DEFAULT_SCOPES`, the five JavaScript lines (once each; nine after Task 5, A1), `node --check` when node is installed |
| LST12 `test_lst12_a_style_lora_is_only_ever_global` | `tests/test_lora_scope_fix.py` (Task 5) | A1: `beat` and `either` on a style video entry are the exact catalog error, and `entry_scope` is still `global`; `global` and a stills style entry's scope are valid; `load_catalog` names the path; `add` and `scope` refuse with the exact stderr and leave the file byte-identical; `scope ... global` and `default` print the exact lines; `add --scope global` on a style writes it; a style entry with an unvalidated `either` is listed only in the global group, and its per-beat pick is L8 |
| LST13 `test_lst13_the_movie_ui_gives_a_style_lora_no_per_beat_scope` | same | A1: a style add with `beat` or `either` is the exact 400 and runs nothing; a style add with `global` or no scope, and a motion add with `beat`, pass the right argv; the form note |
| LST14 `test_lst14_a_moved_lora_keeps_one_copy_in_either_patch_order` | same | A2: a global-scope style on beat 2 moved to global, and a beat-scope motion in global moved to beat 2, each in both patch orders: both patches applied, the moved plan, no check, no `lora_notes`, the input state untouched; a patch that breaks the plan in every order is rejected with `would break plan: L8 ...` while the other is applied |
| LST15 `test_lst15_phase_3_and_the_dry_run_name_the_l8_fix` | same | A3, C3: Phase 3 and the dry run with a saved plan holding a global motion pick exit 2 with the exact error line and `RECHECK_SCOPE_HINT`, and write no `catalog_loras.json`; scope `either` makes Phase 3 write the pick on every panel; a per-beat style pick gives the beat L8 and the hint; an L5 gives the line without the hint |
| LST16 `test_lst16_lora_notes_that_are_not_a_list_of_strings_add_no_advisory` | same | A4: Phase 3 passes with `lora_notes` null; a string, null, a number and an object add nothing; a list adds only its strings |

**Existing tests edited** (all still pass; none is removed):
- `tests/test_lora_catalog.py::test_lct9_list` (E16-E18): the SCOPE column.
- `tests/test_story_engine.py::test_rst15_lora_checks` (E32-E34): `_lora_ctx` gives fast-motion and rain-physics scope either; the per-beat style case expects L8; the comment names L8.
- `tests/test_story_engine.py::test_rst31_lora_patch` and `test_lct28_lora_limits_with_a_cast_character` (E35, through `_lora_state`): fast-motion has scope either.
- `tests/test_dialogue.py::test_dlg18_reclassification` (E36-E38): the same fixture change, and the per-beat style case moves from the advisory loop to `_only(..., "L8")`.
- `tests/test_per_beat_json.py::test_pjt1_the_lora_paragraph_names_the_per_beat_key` and `test_pjt4_...` (E39, E40): the new paragraph and `CLAUSE`.
- `tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token`, `tests/test_location_ui.py::test_lu1_...`, `tests/test_movie_ui_seedgen.py::test_sgt20_the_routes`, `tests/test_movie_ui_seedfolder.py::test_sdt11_the_route_and_its_token` and `::test_sdt29_the_characters_route_and_its_token` (E53-E57): 64 routes.
- `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` (Task 4): BASELINE.
- **(Task 5)** `tests/test_lora_scope_catalog.py::test_lst1_...` (E76): `beat` and `either` are valid on the motion and stills entries only. `tests/test_lora_scope.py`: the `HINT` literal (E77, used by LST8); LST5 gives `either` and `global` to the motion entry only (E78); LST6's style entry has no scope or `global` (E79). `tests/test_lora_scope_ui.py::test_lst11_...` (E80): the new JavaScript lines.

**Mutation check** (replayed; see "Replay result"). Each of these makes at least one of the new or edited tests fail:
- dropping the scope value check of `validate_entry`;
- not accepting `OPTIONAL_ENTRY_KEYS`;
- `entry_scope` ignoring an explicit scope;
- `motion` defaulting to `either`;
- giving a stills entry an effective scope;
- listing an `either` entry only in the global group;
- dropping the empty-group line;
- dropping the global L8;
- dropping the per-beat L8;
- keeping the per-beat L2 advisory;
- not adding the duplicate notes to the advisories;
- dropping the duplicate normalization;
- normalizing a beat-scoped duplicate like the others;
- keeping a beat key that the normalization emptied;
- normalizing only the first beat;
- normalizing every per_beat key, also one outside 1 to N;
- never writing `lora_notes`;
- always writing `lora_notes`;
- leaving L8 out of `critic_round`'s lora ids;
- a flat critic catalog;
- a flat plan catalog;
- the paragraph without `a LoRA in global is never also in per_beat`;
- dropping the re-check hint;
- printing the hint for any L violation;
- `add` accepting `--scope` for a stills LoRA;
- `add` not writing the scope;
- `scope ... default` keeping the key;
- `scope` changing a stills entry;
- `list` showing the raw scope instead of the effective one;
- the server not passing `--scope`;
- the server accepting any add scope;
- the scope route accepting any string;
- the add form not sending the scope;
- a JavaScript default that differs from `DEFAULT_SCOPES`;
- (Task 5) `validate_entry` accepting `beat` or `either` on a style entry;
- `validate_entry` refusing a scope on a stills style entry;
- `entry_scope` returning a style entry's own scope;
- `add` accepting `--scope beat` for a style LoRA;
- `scope` changing a style entry to `either`;
- the server accepting a style add with `beat`;
- `apply_patches` without the retry;
- `apply_patches` dropping, instead of rejecting, the patches left after a pass that applies none;
- `_catalog_checks_error` without the hint;
- the hint after any L violation, not only an L8;
- `lora_checks` adding a non-list `lora_notes`;
- `lora_checks` adding a non-string item of `lora_notes`;
- a style row with a Scope select;
- a Kind change that does not update the form's Scope select.

## 6. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

Run from the workspace root on macstudio after merging. `<fight>` is the catalog id of the fight LoRA, `<cmd>` the bin/ltx-movie command of the story that should use it (auto LoRA on), and `<id>` its `--story-id`. Run `export D=generated/stories/<id>` first.

- **LV1 (the catalog).**
  1. `bin/lora-catalog list` exits 0 and shows the SCOPE column. Every motion and physics entry without a scope shows `beat`, every style entry without one `global`, every stills entry `-`. An entry you hand-edited shows your value.
  2. If it fails with `scope must be one of global, beat, either`, or (A1) with `scope must be global for a style LoRA`, fix that value in catalog.json (or remove the key) and repeat.
  3. `bin/lora-catalog verify` reports no new problem.
- **LV2 (saved stories the scopes now forbid; C3, C4; LSK5).**
  1. List them (it prints nothing when there are none; record the output):
```bash
python3 - <<'EOF'
import glob, json, lora_catalog
entries = {e["id"]: e for e in lora_catalog.load_catalog(lora_catalog.catalog_path("."))["entries"]}
for path in sorted(glob.glob("generated/stories/*/plan.json")):
    loras = json.load(open(path, encoding="utf-8")).get("loras") or {}
    found = ["global " + p["id"] for p in loras.get("global") or []
             if isinstance(p, dict) and lora_catalog.entry_scope(entries.get(p.get("id"), {})) == "beat"]
    found += ["beat %s %s" % (k, p["id"]) for k, picks in sorted((loras.get("per_beat") or {}).items())
              for p in picks or [] if isinstance(p, dict)
              and lora_catalog.entry_scope(entries.get(p.get("id"), {})) == "global"]
    if found:
        print(path, ", ".join(found))
EOF
```
  2. For one listed story, rerun its command with `--story-only` (no `--force-story`). Expected: exit 2, a bullet `plan: L8 scope: '<lora>' may only be a per-beat pick ...` (or `beat <k>: L8 scope: ...`), then the line `An L8 violation is a pick placed where its catalog scope does not allow: ...`.
  3. Run `bin/lora-catalog scope <that lora> either` and rerun the same command. Expected: the re-check passes. Afterwards `bin/lora-catalog scope <that lora> default` restores the default. (A1) When the listed pick is a style LoRA on a beat, `scope <that lora> either` exits 2 with `... is a style LoRA; a style LoRA is only ever a global pick, so its scope is global or default`; that story needs `--force-story`.
  4. (A3) For the same story, `<cmd> --dry-run --no-review` exits 2 and prints the `Error: plan.json LoRA picks fail the catalog checks (... L8 scope: ...); rerun with --force-story or --no-auto-lora` line followed by the `An L8 violation is ...` line.
- **LV3 (a new plan for the fight story; LSK4).**
  1. `bin/lora-catalog list` shows `<fight>` with SCOPE `beat`. If it shows `either` or `global` (set by hand), run `bin/lora-catalog scope <fight> beat`; it prints `<fight>: scope beat in .../catalog.json`.
  2. `<cmd> --dry-run --no-review | sed -n '/^LoRA catalog (pick only from these):/,/^$/p'` prints the groups, with `<fight>` only under `May be per-beat picks (applied to their beat only):`.
  3. Run `<cmd> --story-only --force-story`, then:
```bash
python3 - <<'EOF'
import json, os
loras = json.load(open(os.path.join(os.environ["D"], "plan.json"), encoding="utf-8"))["loras"]
print("global", [p["id"] for p in loras["global"]])
print("per_beat", dict((k, [p["id"] for p in v]) for k, v in sorted(loras["per_beat"].items())))
EOF
```
Expected: `<fight>` is not in `global`, and is on the fight beats only.
  4. Record which rounds had an L8 (`grep -l '"L8"' $D/story_rounds/round_*/story_checks.json`) and the `plan: call` and `critic round` lines the run printed. Report a final `$D/story_checks.json` whose `hard` still has an L8.
- **LV4 (duplicates).** After a few auto-LoRA runs, `grep -h -A3 '"lora_notes"' generated/stories/*/plan.json` shows each normalized duplicate; record them. A story with a `lora_notes` line has no L6 in the `hard` list of its `story_checks.json`.
- **LV5 (the movie UI; LSK6).**
  1. Open the movie UI, LoRAs tab. The catalog table has a Scope column after Target. Every motion and physics row has a select showing `default (beat)` or the value set; (A1) every style video row shows the text `global` with no select; every stills row shows `-`.
  2. Change `<fight>` to `either`. The output box shows `<fight>: scope either in .../catalog.json`, and after the reload the row shows `either`. `bin/lora-catalog list` shows `either`.
  3. Change it back to `default (beat)`. The output ends with `(the default for a motion LoRA) in .../catalog.json`, and `bin/lora-catalog list --json` shows no `scope` key for `<fight>`.
  4. In "Add a LoRA", set Target to `stills`: the Scope select is disabled. Set it back to `video`: with Kind `style` (A1) the select stays disabled. Set Kind to `motion`: it is enabled. Choose Scope `global`, and add a copy of a small LoRA file under a new id. Its row shows `global`, and `bin/lora-catalog list` agrees. Remove it with its Remove button.
  5. On the Compose page, the LoRA picker still lists every catalog entry as before.

## 7. Risks (rulings), follow-ups and open questions

**Risks.**
- **R1 (saved stories fail their re-check; C3).** Expected, and named by the hint. Ruling: accepted; LV2 lists the stories and the fix.
- **R2 (an L8 the repairs cannot finish).** A global-scope LoRA on more than 8 beats needs more patches than one critic round allows, and the plan retry may repeat it. The run then ends with a blocking L8 (exit 2), like any unrepaired hard violation. Ruling: accepted. Only a misconfigured catalog or a stubborn model gets there, and the message says what to change (follow-up F4).
- **R3 (prompt length).** Each `either` entry is listed twice, and two or three headings are added. With a handful of entries that is well inside the catalog plan budget (plan-budget PB1, 400 tokens per beat). Ruling: accepted.
- **R4 (a stills scope is ignored silently).** Ruling: accepted (Decision 1); `list` shows `-` for it.
- **R5 (the JavaScript defaults drift).** `LORA_SCOPE_DEFAULTS` copies `DEFAULT_SCOPES`. Ruling: LST11 compares them.
- **R6 (two styles on one panel).** An `either` or `beat` style picked for a beat, plus a global style, is not reported (L2 counts global and pinned styles only). Ruling: accepted (follow-up F2). **(A1) Resolved:** a style entry's scope may only be `global`, so a per-beat style pick is always the hard L8 and never reaches Phase 3.
- **R7 (a pinned beat-scoped LoRA).** `--lora` with a motion entry applies it to every panel, as today. Ruling: the user's explicit choice (Decision 9; follow-up F3).
- **R8 (a dropped global copy).** For a beat-scoped duplicate, the panels without a per-beat copy lose that LoRA. Ruling: intended, because the global pick was forbidden (Q1).
- **R9 (A1: a hand-written style scope breaks every auto-LoRA run).** Ruling: accepted (C10); only this branch could write one, the error names the entry and the fix, and LV1 checks it.
- **R10 (A2: the retry costs lora_checks calls).** At most 8 lora patches, one per index, so at most 8 passes and 72 `lora_checks` calls, which are pure and fast. Ruling: accepted.

**Follow-ups (not fixed here).**
- **F1.** Report L6 on every beat it applies to, and normalize a pick that repeats a pin the same way.
- **F2.** Count style LoRAs per panel (global, pinned and per-beat) for L2. **(A1) Withdrawn:** no per-beat style pick can pass the checks.
- **F3.** In the Compose page, note when a pinned LoRA's scope is `beat`.
- **F4.** Repair an L8 automatically when it is unambiguous, for example a global-scope LoRA picked for every beat.
- **F5.** Show the scope in the Compose page's LoRA picker labels.
- **F6.** Add the effective scope to `bin/lora-catalog list --json`.

**Open questions (none blocks implementation).**
- **Q1.** For a duplicate whose scope is `beat`, this spec drops the global copy and keeps the per-beat picks, where the user's rule says to drop the per-beat copy. Dropping the per-beat copies there would leave a forbidden global pick (L8) and lose the beats the planner chose. Confirm, or say to drop the per-beat copies in every case (then L8 asks the critic to move the global pick).
- **Q2.** Should a stills entry's scope be rejected instead of ignored?
- **Q3.** Should a default-scoped per-beat style pick stay advisory (as L2 was) instead of the hard L8? **(A1) Answered by the ruling:** it is the hard L8, because Phase 3 would drop it.
- **Q4.** Should an `either` entry be listed once, in a third group, instead of in both groups?

---

## Plan

**House rules** (every task):
- Work only in `$S/ls-wt`. Never touch `/Users/reubenpatterson/local_agent_harness` directly or `/Users/ailab1`.
- Never stash, reset, amend, rebase, push or open a PR. Never access macstudio (no ssh, no scp, no reading its files).
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's Old text must occur exactly once in the file when the Edit is applied. If it does not, stop and report.
- Every Python file a task changes must compile on both `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- The PR is merged with a merge commit only (never squash or rebase), so the sha that Task 4 writes into BASELINE stays reachable.

**Replay.** Every block below was replayed in rsync copies of `$S/ls-base`, without `.git` and next to a symlinked `agent/`. `$S/ls-base` is a copy of `$S/pj-replay`: `c58010e` with the per-beat-json spec's Task 1 blocks applied (byte-identical to that branch's own draft, `$S/pj-pre`).
- The blocks of Tasks 1-3 were applied by script, in order, and each Old occurred exactly once (`$S/ls-replay3`).
- A second script read every block back from this document, applied it to a fresh copy and found the result byte-identical to the replay.
- The results are in "Replay result" at the end.

### Before Task 1: the merged base, the anchors, the baseline and the gate files (controller)

**Step A: bring the merged per-beat-json work into this branch.** Let `B` be the commit that holds it: the merge commit of its PR, or, when the branches are merged locally, the last commit of `per-beat-json` (its Task 2 BASELINE commit, or a later review-fix commit).

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
git branch --show-current                                   # lora-scope
git status --short                                          # no output
B=<the 40-hex sha described above>
git merge-base --is-ancestor c58010e $B && echo "B contains plan-budget"
git cat-file -e $B:qwen-agent-workspace/tests/test_per_beat_json.py && echo "B has per-beat-json"
git merge --no-ff $B -m "Merge per-beat-json into lora-scope" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git diff --stat $B HEAD -- . ':(exclude)docs' | tail -1   # no output
grep -c 'the key of beat 1 is "1"' story_engine.py                              # 1
grep -o 'BASELINE = "[0-9a-f]*"' tests/test_movie_ui_builder.py                  # per-beat-json's code commit
grep -c '(per-beat-json)\.$' tests/test_movie_ui_builder.py                      # 1
ls -l $S/snapshot-pre-ls-$(git rev-parse --short HEAD).tgz || tar czf $S/snapshot-pre-ls-$(git rev-parse --short HEAD).tgz --exclude generated -C $S/ls-wt qwen-agent-workspace
df -g . | tail -1                                           # at least 5 GiB free
```
Expected: the merge succeeds with no conflict (this branch holds only this document); every check prints what its comment says. On a conflict, or any other output, stop and report.

**Step B: re-verify every anchor of this plan against the merged tree.** This applies every block of Tasks 1-3, read from this document, to a scratch copy and stops at the first Old that does not occur exactly once:

````bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
mkdir -p $S/ls-anchors
cat > $S/ls-anchors/extract.py <<'PYEOF'
"""Apply this plan's Task 1-3 blocks, read from the spec (argv[1]), to a copy of the WS in argv[2];
keep the copy in argv[3] when given. Every Old must occur exactly once when it is applied."""
import os, re, shutil, sys, tempfile
doc, ws = sys.argv[1], sys.argv[2]
lines = open(doc, encoding="utf-8").read().split("\n")
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(tempfile.mkdtemp(prefix="ls-anchors-"), "ws")
if os.path.exists(out):
    shutil.rmtree(out)
shutil.copytree(ws, out, symlinks=True,
                ignore=shutil.ignore_patterns("generated", "__pycache__", ".pytest_cache"))


def block(i):
    """(text, next line index) of the fenced block that opens at lines[i]."""
    fence = re.match(r"^(`{3,})[a-z]*$", lines[i])
    assert fence, (i + 1, lines[i])
    j = i + 1
    while lines[j] != fence.group(1):
        j += 1
    return "".join(line + "\n" for line in lines[i + 1:j]), j + 1


task, i, n = None, 0, 0
while i < len(lines):
    head = re.match(r"^### Task (\d+):", lines[i])
    if head:
        task = int(head.group(1))
    write = re.match(r"^- \[ \] \*\*Step \d+: Write `([^`]+)`\*\*", lines[i])
    edit = re.match(r"^- \[ \] \*\*Step \d+: Edit `([^`]+)` \(E\d+, .*\)\.\*\* Old:$", lines[i])
    if task in (1, 2, 3) and write:
        i += 1
        while not lines[i].startswith("```"):
            i += 1
        text, i = block(i)
        with open(os.path.join(out, write.group(1)), "w", encoding="utf-8") as f:
            f.write(text)
        n += 1
        continue
    if task in (1, 2, 3) and edit:
        old, i = block(i + 1)
        assert lines[i] == "New:", (i + 1, lines[i])
        new, i = block(i + 1)
        path = os.path.join(out, edit.group(1))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.count(old) != 1:
            sys.exit("ANCHOR FAIL: %s: %d matches for the Old block of line %d"
                     % (edit.group(1), text.count(old), i))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))
        n += 1
        continue
    i += 1
print("anchors ok: %d blocks applied to %s" % (n, out))
PYEOF
cd $S/ls-wt/qwen-agent-workspace
python3 -B $S/ls-anchors/extract.py docs/superpowers/specs/2026-11-10-lora-scope-design.md . $S/ls-anchors/ws
````
Expected: `anchors ok: 60 blocks applied to .../ls-anchors/ws`. On `ANCHOR FAIL`, stop and report the file and block: the merged per-beat-json work differs from its spec there, and the block must be re-derived before any task runs. Delete `$S/ls-anchors` afterwards.

**Step C: the baseline.** When the tree is the one the last per-beat-json gate ran on, that gate's output is the baseline; otherwise run it.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/ls-baseline; mkdir -p $D
cd $S/ls-wt/qwen-agent-workspace
PJ=$S/pj-baseline
N=$(ls $PJ/task-*-pytest.txt | sed 's/.*task-\([0-9]*\)-pytest\.txt/\1/' | sort -n | tail -1); echo "last per-beat-json gate: task $N"
PJ_HEAD=$(git -C $S/pj-wt rev-parse HEAD); echo $PJ_HEAD
git diff --quiet $PJ_HEAD HEAD -- . ':(exclude)docs' && echo "SAME TREE"
```
- When it prints `SAME TREE` (and `$PJ/task-$N-pytest.txt` was written after `$S/pj-wt`'s last commit), reuse it: `cp $PJ/task-$N-pytest.txt $D/baseline-pytest.txt; cp $PJ/task-$N-ok-lines.txt $D/baseline-ok-lines.txt`.
- Otherwise run it here:
  ```bash
  python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1
  for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
  ```
Then, either way:
```bash
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                     # record as P0
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
cat $D/baseline-ok-lines.txt
```
Expected:
- The summary is `2 failed, 2734 passed, 2 skipped, ... warnings in ...` (per-beat-json PJK1), so P0 is 2734. If per-beat-json landed with another count, P0 is that count, and every expected count below is written as P0 plus a number.
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. There is no `ERROR` line, and `test_mut26` passes.
- `baseline-ok-lines.txt` holds `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68` and `OK 205/205`.

If `test_tr27_fanout_two_rounds_and_missing_reasons`, `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` or `test_trt46_post_spans_validation_cap_and_store` also fails, rerun those three alone. `3 passed` means the baseline stands. For any other difference, stop and report.

**Step D: the gate files** (scratch files, never staged), based on the plan-budget plan's:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/ls-baseline
python3 - "$S/pb-baseline/gate.py" "$D/gate.py" <<'PYEOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
old = 'NEW_FILES = ("tests/test_plan_budget.py::",)'
assert s.count(old) == 1, old
s = s.replace(old, 'NEW_FILES = ("tests/test_lora_scope_catalog.py::", "tests/test_lora_scope.py::", '
                   '"tests/test_lora_scope_ui.py::")')
open(sys.argv[2], "w", encoding="utf-8").write(s)
PYEOF
sed -e 's#/pb-baseline#/ls-baseline#' -e 's#/pb-wt/#/ls-wt/#' $S/pb-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'TXTEOF'
# lora scope plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 3 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged pinned files change in Tasks 1 and 2; Task 4 moves BASELINE
1 4 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 4 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 4 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
TXTEOF
grep -c ls-baseline $D/gate-run.sh; grep -c /ls-wt/ $D/gate-run.sh; grep -c '"tests/test_lora_scope_ui.py::")' $D/gate.py; grep -c test_trt46 $D/gate-run.sh; grep -c pb- $D/gate-run.sh   # 1, 1, 1, 1, 0
```

**The gate** for task N is `zsh $S/ls-baseline/gate-run.sh N`. It is a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints `disk ok`, the pytest summary, the gate line, `GATE PASS`, `3 passed` for the flake rerun, and `ATK2 OK lines unchanged`. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids, with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the scope field in `lora_catalog.py`, and `add --scope`, `scope` and the SCOPE column of `bin/lora-catalog` (one commit)

**Files:** `lora_catalog.py` (pinned), `bin/lora-catalog` (pinned), `tests/story_engine_testutil.py`, `tests/test_lora_catalog.py`, `tests/test_lora_scope_catalog.py` (new).

**Interfaces** (new or changed; everything else is unchanged):
- `lora_catalog.OPTIONAL_ENTRY_KEYS`, `lora_catalog.SCOPES`, `lora_catalog.DEFAULT_SCOPES` (LS1).
- `lora_catalog.entry_scope(entry) -> str or None` (LS2).
- `bin/lora-catalog`: `add --scope {global,beat,either}`; `scope ID {global,beat,either,default}` (`cmd_scope(args) -> int`); `ROW_FORMAT` with 7 columns (LS3).
- `story_engine_testutil.catalog_entry(..., scope=None)`: a scope other than `None` becomes the entry's last key.

- [ ] **Step 1: Write `tests/test_lora_scope_catalog.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for catalog LoRA scopes in lora_catalog.py and bin/lora-catalog
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS1-LS3: LST1-LST3): a catalog entry's
optional scope (global, beat or either; by default global for style and beat for motion and
physics), bin/lora-catalog add --scope, the scope subcommand and the SCOPE column of list.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_catalog.py

LoRA files are a few bytes under tmp_path; bin/lora-catalog runs as a subprocess with
LORA_CATALOG_DIR under tmp_path. Nothing renders and no server is contacted. Stdlib and pytest.
"""

import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

CLI = os.path.join(WS, "bin", "lora-catalog")
ARCH_UNVERIFIED = ("arch: architecture UNVERIFIED: none of the declared base models are on disk "
                   "yet; run bin/lora-check once the base is installed\n")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


def _entries(tmp_path, **scopes):
    """film-grain (style), fast-motion (motion), rain-physics (physics) and ink-stills (stills),
    each with the scope scopes[<first word of its id>] when given."""
    files = str(tmp_path / "files")
    return [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                          scope=scopes.get("film")),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope=scopes.get("fast")),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                          scope=scopes.get("rain")),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]


def _cli(*argv):
    return subprocess.run([sys.executable, CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True)


def _catalog_file(story_env):
    return os.path.join(story_env["catalog"], "catalog.json")


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# --- LST1 (LS1, LS2): the scope field in lora_catalog.py --------------------------------------

def test_lst1_the_scope_field_and_its_defaults(tmp_path, story_env):
    assert lora_catalog.SCOPES == ("global", "beat", "either")
    assert lora_catalog.DEFAULT_SCOPES == {"style": "global", "motion": "beat", "physics": "beat"}
    assert lora_catalog.OPTIONAL_ENTRY_KEYS == ("scope",)
    assert len(lora_catalog.ENTRY_KEYS) == 16 and "scope" not in lora_catalog.ENTRY_KEYS
    grain, fast, rain, ink = _entries(tmp_path)
    assert [lora_catalog.entry_scope(e) for e in (grain, fast, rain, ink)] == [
        "global", "beat", "beat", None]
    for scope in lora_catalog.SCOPES:
        for entry in (grain, fast, ink):
            lora_catalog.validate_entry(dict(entry, scope=scope))
        assert lora_catalog.entry_scope(dict(fast, scope=scope)) == scope
    assert lora_catalog.entry_scope(dict(ink, scope="beat")) is None
    for character in (dict(fast, id="char:kyra", kind="character"),):
        assert lora_catalog.entry_scope(character) is None
    for bad in ("globl", None, ["beat"], "", "Beat"):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(dict(fast, scope=bad))
        assert str(exc.value) == ("entry fast-motion: scope must be one of global, beat, either, "
                                  "got %r" % (bad,))
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.validate_entry(dict(fast, extra=1))
    assert str(exc.value) == "entry fast-motion: unexpected keys extra"
    path = seu.make_catalog(story_env["catalog"], [grain, fast, rain, ink])
    before = _read_bytes(path)
    data = lora_catalog.load_catalog(path)
    assert all("scope" not in e for e in data["entries"])
    lora_catalog.save_catalog(path, data)
    assert _read_bytes(path) == before
    scoped = dict(fast, scope="either")
    lora_catalog.save_catalog(path, {"schema_version": 1, "entries": [grain, scoped, rain, ink]})
    saved = lora_catalog.load_catalog(path)["entries"]
    assert [e["id"] for e in saved] == ["fast-motion", "film-grain", "ink-stills", "rain-physics"]
    assert saved[0] == scoped and list(saved[0])[-1] == "scope"


# --- LST2 (LS3): bin/lora-catalog add --scope and the SCOPE column of list ---------------------

def test_lst2_add_scope_and_the_list_column(tmp_path, story_env):
    files = str(tmp_path / "files")
    path = _catalog_file(story_env)
    base = ["--base-model", seu.VIDEO_MODEL, "--description", "a test LoRA",
            "--use-when", "a chase"]
    fight = seu.lora_file(files, "fight")
    result = _cli("add", fight, "--id", "fight-motion", "--kind", "motion", "--target", "video",
                  "--scope", "either", *base)
    assert (result.returncode, result.stderr) == (0, ARCH_UNVERIFIED), result.stderr
    entry = lora_catalog.load_catalog(path)["entries"][0]
    assert entry["scope"] == "either" and list(entry)[-1] == "scope"
    plain = seu.lora_file(files, "plain")
    assert _cli("add", plain, "--id", "plain-motion", "--kind", "motion", "--target", "video",
                *base).returncode == 0
    assert "scope" not in lora_catalog.load_catalog(path)["entries"][1]
    before = _read_bytes(path)
    ink = seu.lora_file(files, "ink")
    result = _cli("add", ink, "--id", "ink-stills", "--kind", "style", "--target", "stills",
                  "--scope", "global", "--base-model", seu.STILLS_MODEL, "--description", "ink",
                  "--use-when", "ink")
    assert (result.returncode, result.stdout, result.stderr) == (
        2, "", "Error: --scope applies only to video LoRAs; a stills LoRA is only ever the "
               "stills pick\n")
    result = _cli("add", ink, "--id", "ink-motion", "--kind", "motion", "--target", "video",
                  "--scope", "anywhere", *base)
    assert result.returncode == 2 and "invalid choice: 'anywhere'" in result.stderr
    assert _read_bytes(path) == before
    assert _cli("add", ink, "--id", "ink-stills", "--kind", "style", "--target", "stills",
                "--base-model", seu.STILLS_MODEL, "--description", "ink",
                "--use-when", "ink").returncode == 0
    grain = seu.lora_file(files, "grain")
    assert _cli("add", grain, "--id", "film-grain", "--kind", "style", "--target", "video",
                *base).returncode == 0
    row = "%-24s %-9s %-7s %-7s %-14s %-24s %s"
    assert _cli("list").stdout.splitlines() == [
        row % ("ID", "KIND", "TARGET", "SCOPE", "STRENGTH", "TRIGGERS", "BASE_MODELS"),
        row % ("fight-motion", "motion", "video", "either", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL),
        row % ("film-grain", "style", "video", "global", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL),
        row % ("ink-stills", "style", "stills", "-", "1.0 (0.5-1.0)", "", seu.STILLS_MODEL),
        row % ("plain-motion", "motion", "video", "beat", "1.0 (0.5-1.0)", "", seu.VIDEO_MODEL)]
    listed = json.loads(_cli("list", "--json").stdout)["entries"]
    assert [e.get("scope") for e in listed] == ["either", None, None, None]


# --- LST3 (LS3): bin/lora-catalog scope ID SCOPE -------------------------------------------------

def test_lst3_the_scope_subcommand(tmp_path, story_env):
    path = _catalog_file(story_env)
    assert _cli("scope", "fast-motion", "beat").stderr == "Error: no catalog entry fast-motion\n"
    grain, fast, rain, ink = _entries(tmp_path)
    seu.make_catalog(story_env["catalog"], [grain, fast, rain, ink])
    result = _cli("scope", "fast-motion", "global")
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "fast-motion: scope global in %s\n" % path, "")
    entries = lora_catalog.load_catalog(path)["entries"]
    assert entries == [dict(fast, scope="global"), grain, ink, rain]
    assert _cli("scope", "fast-motion", "either").returncode == 0
    assert lora_catalog.load_catalog(path)["entries"][0] == dict(fast, scope="either")
    result = _cli("scope", "fast-motion", "default")
    assert (result.returncode, result.stdout) == (
        0, "fast-motion: scope beat (the default for a motion LoRA) in %s\n" % path)
    assert lora_catalog.load_catalog(path)["entries"] == [fast, grain, ink, rain]
    before = _read_bytes(path)
    for argv, stderr in (
            (["scope", "nope", "beat"], "Error: no catalog entry nope\n"),
            (["scope", "ink-stills", "beat"],
             "Error: ink-stills is a stills LoRA; scope applies only to video LoRAs\n"),
            (["scope", "char:kyra", "beat"],
             "Error: char:kyra is a library character; it is cast with bin/ltx-movie "
             "--character and has no scope\n")):
        result = _cli(*argv)
        assert (result.returncode, result.stdout, result.stderr) == (2, "", stderr), argv
    result = _cli("scope", "fast-motion", "anywhere")
    assert result.returncode == 2 and "invalid choice: 'anywhere'" in result.stderr
    assert _read_bytes(path) == before
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]")
    result = _cli("scope", "fast-motion", "beat")
    assert result.returncode == 2 and result.stderr.startswith("Error: %s: top level" % path)
````

- [ ] **Step 2: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ls-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_catalog.py 2>&1 | tail -1
```
Expected: `3 failed` (the summary line may also count warnings). LST1 fails with `AttributeError: module 'lora_catalog' has no attribute 'SCOPES'`. LST2 and LST3 fail on bin/lora-catalog's usage error, because it has no `--scope` option and no `scope` command yet.

- [ ] **Step 3: Edit `lora_catalog.py` (E1, the scope constants after ENTRY_KEYS).** Old:
```python
ENTRY_KEYS = ("id", "kind", "path", "sha256", "bytes", "base_models", "target", "triggers",
              "rank", "alpha", "default_strength", "strength_range", "description", "use_when",
              "avoid_when", "added_at")
```
New:
```python
ENTRY_KEYS = ("id", "kind", "path", "sha256", "bytes", "base_models", "target", "triggers",
              "rank", "alpha", "default_strength", "strength_range", "description", "use_when",
              "avoid_when", "added_at")
# LoRA scope spec LS1 (docs/superpowers/specs/2026-11-10-lora-scope-design.md): an entry may also
# have a scope, where the story planner may place it: global (every panel), beat (one beat's own
# picks) or either. An entry without one gets the default for its kind. Only video LoRAs have a
# scope; a stills entry's scope is accepted and ignored.
OPTIONAL_ENTRY_KEYS = ("scope",)
SCOPES = ("global", "beat", "either")
DEFAULT_SCOPES = {"style": "global", "motion": "beat", "physics": "beat"}
```

- [ ] **Step 4: Edit `lora_catalog.py` (E2, validate_entry accepts the optional key).** Old:
```python
    extra = sorted(set(entry) - set(ENTRY_KEYS))
```
New:
```python
    extra = sorted(set(entry) - set(ENTRY_KEYS) - set(OPTIONAL_ENTRY_KEYS))
```

- [ ] **Step 5: Edit `lora_catalog.py` (E3, validate_entry checks the scope value).** Old:
```python
    if entry["target"] not in TARGETS:
        fail("target", "must be one of %s, got %r" % (", ".join(TARGETS), entry["target"]))
```
New:
```python
    if entry["target"] not in TARGETS:
        fail("target", "must be one of %s, got %r" % (", ".join(TARGETS), entry["target"]))
    if "scope" in entry and entry["scope"] not in SCOPES:
        fail("scope", "must be one of %s, got %r" % (", ".join(SCOPES), entry["scope"]))
```

- [ ] **Step 6: Edit `lora_catalog.py` (E4, entry_scope before validate_catalog).** Old:
```python
def validate_catalog(data):
```
New:
```python
def entry_scope(entry):
    """Where the story planner may place a catalog entry (LoRA scope spec LS2): its scope, else
    DEFAULT_SCOPES of its kind; None for a stills LoRA and for a library character."""
    if entry.get("target") != "video" or entry.get("kind") not in DEFAULT_SCOPES:
        return None
    return entry.get("scope") or DEFAULT_SCOPES[entry["kind"]]


def validate_catalog(data):
```

- [ ] **Step 7: Edit `bin/lora-catalog` (E5, the usage and the docstring).** Old:
```python
                   [--default-strength S] [--strength-range LO,HI] [--rank N] [--alpha N]
                   [--no-arch-check]
  bin/lora-catalog list [--model M] [--json]
  bin/lora-catalog remove ID
  bin/lora-catalog verify [ID ...]

bin/ltx-movie's story planner may pick catalog entries per panel (style LoRAs only for the
whole movie); trained library characters are listed and verified here but are cast only with
bin/ltx-movie --character. `add` runs bin/lora-check's architecture gate against each declared
--base-model found on disk and refuses a LoRA whose tensors don't match (override with
--no-arch-check; an unlocatable base is a warning, not a refusal). The catalog lives in
$LORA_CATALOG_DIR when set (tests only), else
generated/loras/. add and remove hold the catalog lock for their whole read-modify-write.
```
New:
```python
                   [--default-strength S] [--strength-range LO,HI] [--rank N] [--alpha N]
                   [--scope {global,beat,either}] [--no-arch-check]
  bin/lora-catalog list [--model M] [--json]
  bin/lora-catalog remove ID
  bin/lora-catalog scope ID {global,beat,either,default}
  bin/lora-catalog verify [ID ...]

bin/ltx-movie's story planner may pick catalog entries for the whole movie or for one beat, as
each video entry's scope allows (global, beat or either; without a scope, style LoRAs are global
and motion and physics LoRAs are per-beat: LoRA scope spec LS1); trained library characters are
listed and verified here but are cast only with bin/ltx-movie --character. `add` runs
bin/lora-check's architecture gate against each declared
--base-model found on disk and refuses a LoRA whose tensors don't match (override with
--no-arch-check; an unlocatable base is a warning, not a refusal). The catalog lives in
$LORA_CATALOG_DIR when set (tests only), else
generated/loras/. add, remove and scope hold the catalog lock for their whole read-modify-write.
```

- [ ] **Step 8: Edit `bin/lora-catalog` (E6, ROW_FORMAT gains the SCOPE column).** Old:
```python
ROW_FORMAT = "%-24s %-9s %-7s %-14s %-24s %s"
```
New:
```python
ROW_FORMAT = "%-24s %-9s %-7s %-7s %-14s %-24s %s"
```

- [ ] **Step 9: Edit `bin/lora-catalog` (E7, add --scope).** Old:
```python
    add.add_argument("--alpha", type=int, default=None)
```
New:
```python
    add.add_argument("--alpha", type=int, default=None)
    add.add_argument("--scope", choices=lora_catalog.SCOPES, default=None,
                     help="where the story planner may place this video LoRA: global (every "
                          "panel), beat (one beat) or either; default: global for style, beat "
                          "for motion and physics")
```

- [ ] **Step 10: Edit `bin/lora-catalog` (E8, the scope subcommand's parser).** Old:
```python
    ver = sub.add_parser("verify", help="check catalog entries against their files")
```
New:
```python
    scope = sub.add_parser("scope", help="set where the story planner may place a catalog video "
                                         "LoRA (default: the default for its kind)")
    scope.add_argument("entry_id", metavar="ID")
    scope.add_argument("scope", choices=lora_catalog.SCOPES + ("default",))
    ver = sub.add_parser("verify", help="check catalog entries against their files")
```

- [ ] **Step 11: Edit `bin/lora-catalog` (E9, add refuses --scope for a stills LoRA).** Old:
```python
        return _error("--strength-range must be LO,HI, got %r" % args.strength_range)
    with lora_catalog.catalog_lock(path):
```
New:
```python
        return _error("--strength-range must be LO,HI, got %r" % args.strength_range)
    if args.scope is not None and args.target != "video":
        return _error("--scope applies only to video LoRAs; a stills LoRA is only ever the "
                      "stills pick")
    with lora_catalog.catalog_lock(path):
```

- [ ] **Step 12: Edit `bin/lora-catalog` (E10, add writes the scope last).** Old:
```python
                 "added_at": lora_catalog.utc_now()}
```
New:
```python
                 "added_at": lora_catalog.utc_now()}
        if args.scope is not None:
            entry["scope"] = args.scope
```

- [ ] **Step 13: Edit `bin/lora-catalog` (E11, list rows show the effective scope).** Old:
```python
def _row(entry):
    return ROW_FORMAT % (entry["id"], entry["kind"], entry["target"], _strength_text(entry),
                         ",".join(entry["triggers"]), ",".join(entry["base_models"]))
```
New:
```python
def _row(entry):
    return ROW_FORMAT % (entry["id"], entry["kind"], entry["target"],
                         lora_catalog.entry_scope(entry) or "-", _strength_text(entry),
                         ",".join(entry["triggers"]), ",".join(entry["base_models"]))
```

- [ ] **Step 14: Edit `bin/lora-catalog` (E12, the list header).** Old:
```python
    header = ROW_FORMAT % ("ID", "KIND", "TARGET", "STRENGTH", "TRIGGERS", "BASE_MODELS")
```
New:
```python
    header = ROW_FORMAT % ("ID", "KIND", "TARGET", "SCOPE", "STRENGTH", "TRIGGERS", "BASE_MODELS")
```

- [ ] **Step 15: Edit `bin/lora-catalog` (E13, cmd_scope before cmd_verify).** Old:
```python
def cmd_verify(args):
```
New:
```python
def cmd_scope(args):
    """Set or clear one video entry's scope (LoRA scope spec LS3) under the catalog lock."""
    path = lora_catalog.catalog_path(WS)
    if args.entry_id.startswith("char:"):
        return _error("%s is a library character; it is cast with bin/ltx-movie --character and "
                      "has no scope" % args.entry_id)
    if not os.path.isdir(os.path.dirname(path)):
        return _error("no catalog entry %s" % args.entry_id)
    with lora_catalog.catalog_lock(path):
        try:
            catalog = lora_catalog.load_catalog(path)
        except lora_catalog.CatalogError as e:
            return _error(str(e))
        found = [e for e in catalog["entries"] if e["id"] == args.entry_id]
        if not found:
            return _error("no catalog entry %s" % args.entry_id)
        entry = dict(found[0])
        if entry["target"] != "video":
            return _error("%s is a stills LoRA; scope applies only to video LoRAs" % entry["id"])
        entry.pop("scope", None)
        if args.scope != "default":
            entry["scope"] = args.scope
        entries = [entry if e["id"] == entry["id"] else e for e in catalog["entries"]]
        try:
            lora_catalog.save_catalog(path, {"schema_version": lora_catalog.SCHEMA_VERSION,
                                             "entries": entries})
        except lora_catalog.CatalogError as e:
            return _error(str(e))
        except OSError as e:
            return _error("cannot write %s: %s" % (path, e.strerror or e))
    if args.scope == "default":
        print("%s: scope %s (the default for a %s LoRA) in %s"
              % (entry["id"], lora_catalog.entry_scope(entry), entry["kind"], path))
    else:
        print("%s: scope %s in %s" % (entry["id"], args.scope, path))
    return 0


def cmd_verify(args):
```

- [ ] **Step 16: Edit `bin/lora-catalog` (E14, main dispatches scope).** Old:
```python
    return {"add": cmd_add, "list": cmd_list, "remove": cmd_remove,
            "verify": cmd_verify}[args.command](args)
```
New:
```python
    return {"add": cmd_add, "list": cmd_list, "remove": cmd_remove, "scope": cmd_scope,
            "verify": cmd_verify}[args.command](args)
```

- [ ] **Step 17: Edit `tests/story_engine_testutil.py` (E15, catalog_entry takes a scope).** Old:
```python
                  description="a test LoRA", use_when="a test fits", avoid_when=""):
    """A valid catalog entry for the existing file at path (sha256 and bytes from the file)."""
    return {"id": entry_id, "kind": kind, "path": os.path.abspath(path),
            "sha256": sha256_file(path), "bytes": os.path.getsize(path),
            "base_models": list(base_models), "target": target, "triggers": list(triggers),
            "rank": rank, "alpha": rank, "default_strength": default_strength,
            "strength_range": list(strength_range), "description": description,
            "use_when": use_when, "avoid_when": avoid_when, "added_at": "2026-10-17T12:00:00Z"}
```
New:
```python
                  description="a test LoRA", use_when="a test fits", avoid_when="", scope=None):
    """A valid catalog entry for the existing file at path (sha256 and bytes from the file); a
    scope other than None is written as the entry's scope (LoRA scope spec LS1)."""
    entry = {"id": entry_id, "kind": kind, "path": os.path.abspath(path),
             "sha256": sha256_file(path), "bytes": os.path.getsize(path),
             "base_models": list(base_models), "target": target, "triggers": list(triggers),
             "rank": rank, "alpha": rank, "default_strength": default_strength,
             "strength_range": list(strength_range), "description": description,
             "use_when": use_when, "avoid_when": avoid_when, "added_at": "2026-10-17T12:00:00Z"}
    if scope is not None:
        entry["scope"] = scope
    return entry
```

- [ ] **Step 18: Edit `tests/test_lora_catalog.py` (E16, LCT9's header and character row).** Old:
```python
    header = lora_catalog_row("ID", "KIND", "TARGET", "STRENGTH", "TRIGGERS", "BASE_MODELS")
    kyra_row = lora_catalog_row("char:kyra", "character", "video", "0.8", "kyrawmn",
                                seu.CHARACTER_BASE_MODEL)
```
New:
```python
    header = lora_catalog_row("ID", "KIND", "TARGET", "SCOPE", "STRENGTH", "TRIGGERS",
                              "BASE_MODELS")
    kyra_row = lora_catalog_row("char:kyra", "character", "video", "-", "0.8", "kyrawmn",
                                seu.CHARACTER_BASE_MODEL)
```

- [ ] **Step 19: Edit `tests/test_lora_catalog.py` (E17, LCT9's entry rows).** Old:
```python
        lora_catalog_row("fast-motion", "motion", "video", "0.8 (0.5-1.0)", "fastmo",
                         seu.VIDEO_MODEL),
        lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                         seu.STILLS_MODEL),
        kyra_row]
    filtered = _cli("list", "--model", seu.STILLS_MODEL)
    assert filtered.stdout.splitlines() == [
        header, lora_catalog_row("ink-stills", "style", "stills", "0.9 (0.6-1.2)", "",
                                 seu.STILLS_MODEL)]
```
New:
```python
        lora_catalog_row("fast-motion", "motion", "video", "beat", "0.8 (0.5-1.0)", "fastmo",
                         seu.VIDEO_MODEL),
        lora_catalog_row("ink-stills", "style", "stills", "-", "0.9 (0.6-1.2)", "",
                         seu.STILLS_MODEL),
        kyra_row]
    filtered = _cli("list", "--model", seu.STILLS_MODEL)
    assert filtered.stdout.splitlines() == [
        header, lora_catalog_row("ink-stills", "style", "stills", "-", "0.9 (0.6-1.2)", "",
                                 seu.STILLS_MODEL)]
```

- [ ] **Step 20: Edit `tests/test_lora_catalog.py` (E18, LCT9's row format).** Old:
```python
def lora_catalog_row(*cells):
    return "%-24s %-9s %-7s %-14s %-24s %s" % cells
```
New:
```python
def lora_catalog_row(*cells):
    return "%-24s %-9s %-7s %-7s %-14s %-24s %s" % cells
```

- [ ] **Step 21: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/ls-baseline/pyc $py -m py_compile lora_catalog.py bin/lora-catalog tests/story_engine_testutil.py tests/test_lora_catalog.py tests/test_lora_scope_catalog.py && echo "$py compiled"; done
git diff --numstat -- lora_catalog.py bin/lora-catalog tests/story_engine_testutil.py tests/test_lora_catalog.py
wc -l tests/test_lora_scope_catalog.py                     # 183
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_catalog.py tests/test_lora_catalog.py tests/test_story_engine.py tests/test_dialogue.py 2>&1 | tail -1
zsh $S/ls-baseline/gate-run.sh 1
git add lora_catalog.py bin/lora-catalog tests/story_engine_testutil.py tests/test_lora_catalog.py tests/test_lora_scope_catalog.py
git diff --cached --name-only    # exactly the five paths above, each under qwen-agent-workspace/
git commit -m "lora_catalog, bin/lora-catalog: a catalog video LoRA's optional scope (global, beat or either; by default global for style, beat for motion and physics), add --scope, scope ID SCOPE and a SCOPE column (lora-scope LS1-LS3)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`.
- The numstat lines are `64 9 bin/lora-catalog`, `18 1 lora_catalog.py`, `12 8 tests/story_engine_testutil.py` and `7 6 tests/test_lora_catalog.py`.
- The four-file pytest line is `1 failed, 210 passed, 1 skipped, ... warnings in ...s`. The one failure is the baseline's `test_rst62_import_sets`.
- The gate prints the summary `3 failed, P0 + 2 passed, 2 skipped` (2736 passed when P0 is 2734) and the gate line `lost 1 (listed 1, unexpected 0); new tests 3, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.


### Task 2: the grouped catalog, L8 and the duplicate normalization in `story_engine.py` (one commit)

**Files:** `story_engine.py` (pinned), `bin/ltx-movie` (pinned, one docstring line), `tests/test_story_engine.py`, `tests/test_dialogue.py`, `tests/test_per_beat_json.py`, `tests/test_lora_scope.py` (new).

**Interfaces** (new or changed; everything else is unchanged):
- `story_engine.LORA_PICK_PARAGRAPH` (new text), `LORA_GLOBAL_GROUP`, `LORA_GLOBAL_NONE`, `LORA_BEAT_GROUP`, `LORA_BEAT_NONE`, `LORA_STILLS_GROUP`, `LORA_SCOPE_GLOBAL`, `LORA_SCOPE_BEAT`, `LORA_DUPLICATE_BEATS`, `LORA_DUPLICATE_GLOBAL`, `RECHECK_SCOPE_HINT` (Section 3).
- `story_engine.catalog_groups(ctx, entries) -> list of str` (LS4).
- `story_engine.drop_duplicate_picks(ctx, picks, by_id, n) -> list of str`, which changes `picks` in place (LS6).
- `normalize_plan`: `plan["lora_notes"]` when there is a note (LS6). `lora_checks`: L8, the notes, no per-beat L2 (LS5, LS6). `_Run.catalog_lines` grouped; `critic_round` allows lora patches for L8 (LS4, LS5). `recheck`: the hint (LS8).

- [ ] **Step 1: Write `tests/test_lora_scope.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for catalog LoRA scopes in the story engine
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS4-LS6, LS8, LS9: LST4-LST9): the plan
prompt groups the catalog by scope, a pick its scope does not allow is the hard violation L8
that the planner retry and the critic repair, a LoRA picked both globally and for some beats
keeps one copy, and a re-check names L8 and how to restore a saved plan.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws); the dry-run test runs the real bin/ltx-movie --dry-run, which makes no model call. No
test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_lora_scope", os.path.join(WS, "story_engine.py")).load_module()

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
GLOBAL_L8 = ("plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog scope is "
             "beat), but it is a global pick; remove it from global and pick it for the beats "
             "that need it")
BEAT_L8 = ("beat %d: L8 scope: 'film-grain' may only be a global pick (its catalog scope is "
           "global), but it is a pick for this beat; remove it from this beat, or move it to "
           "global if it suits the whole movie")
HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: set the LoRA's "
        "scope to either with bin/lora-catalog scope ID either (or in the movie UI's LoRA "
        "catalog), or pass --force-story to regenerate.")


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _entries(tmp_path, **scopes):
    """film-grain (style), fast-motion (motion), rain-physics (physics) and ink-stills (stills),
    each with the scope scopes[<first word of its id>] when given."""
    files = str(tmp_path / "files")
    return [
        seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style",
                          scope=scopes.get("film")),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope=scopes.get("fast")),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                          scope=scopes.get("rain")),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
                          target="stills", base_models=[seu.STILLS_MODEL])]


def _ctx(ws, tmp_path, entries=None, **kw):
    entries = _entries(tmp_path) if entries is None else entries
    return seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries}, **kw)


def _pick(entry_id, strength=0.8):
    return {"id": entry_id, "strength": strength}


def _plan(ctx, loras):
    raw = seu.plan_json(ctx.mode, ctx.panels)
    raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
    return se.normalize_plan(ctx, raw)[0]


def _checks(ctx, loras):
    plan = _plan(ctx, loras)
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    return se.lora_checks(ctx, plan, compatible, catalog)


def _catalog_file(story_env):
    return os.path.join(story_env["catalog"], "catalog.json")


# --- LST4 (LS4): the plan prompt groups the catalog by scope -----------------------------------

def test_lst4_the_plan_prompt_groups_the_catalog(ws, tmp_path):
    line = dict((e["id"], se.catalog_line(e)) for e in _entries(tmp_path))
    assert "{" not in se.LORA_PICK_PARAGRAPH and "}" not in se.LORA_PICK_PARAGRAPH
    assert se.LORA_PICK_PARAGRAPH == (
        "an object with the keys global, per_beat and stills. Each pick is an object with the "
        "keys id and strength, taken from the LoRA catalog below; strength must lie inside that "
        "entry's range. The catalog lists each LoRA under the places where it may go. global is "
        "a list of picks applied to every panel, taken only from the LoRAs that may be global "
        "picks: at most one style LoRA, plus motion or physics LoRAs that suit the whole movie. "
        "per_beat maps each beat number to a list of picks for that beat only, taken only from "
        "the LoRAs that may be per-beat picks, and each key is the beat number alone in double "
        'quotes: the key of beat 1 is "1"; a LoRA in global is never also in per_beat, and '
        "every beat may have at most one motion or physics LoRA in total, counting global. "
        "stills is a list of at most one stills LoRA.")
    ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, rain="either"))
    prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
    block = ("\n\nLoRA catalog (pick only from these):\n"
             "May be global picks (applied to every panel):\n" + line["film-grain"] + "\n"
             + line["rain-physics"] + "\nMay be per-beat picks (applied to their beat only):\n"
             + line["fast-motion"] + "\n" + line["rain-physics"]
             + "\nStills LoRAs (only for the stills pick):\n" + line["ink-stills"] + "\n\n")
    assert block in prompt
    pins = [{"path": "/p/a.safetensors", "strength": 1.0, "catalog_id": None, "kind": None}]
    stills_off = _ctx(ws, tmp_path, mode="no_stills")
    prompt = se.build_plan_prompt(stills_off, se.compatible_entries(stills_off), pins)
    assert ("May be per-beat picks (applied to their beat only):\n" + line["fast-motion"] + "\n"
            + line["rain-physics"] + "\nAlready applied to every panel by the user, not to be "
            "picked again:\n- a LoRA outside the catalog at strength 1.0\n\n") in prompt
    assert "Stills LoRAs" not in prompt
    files = str(tmp_path / "files")
    motion_only = _ctx(ws, tmp_path, entries=[
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")])
    assert se.catalog_groups(motion_only, motion_only.catalog["entries"]) == [
        "May be global picks (applied to every panel):", "- none, so global stays empty",
        "May be per-beat picks (applied to their beat only):", line["fast-motion"]]
    style_only = _ctx(ws, tmp_path, entries=[_entries(tmp_path)[0]])
    assert se.catalog_groups(style_only, style_only.catalog["entries"]) == [
        "May be global picks (applied to every panel):", line["film-grain"],
        "May be per-beat picks (applied to their beat only):", "- none, so per_beat stays empty"]
    for mode in ("chained", "no_stills", "shots"):
        ctx = _ctx(ws, tmp_path, mode=mode)
        prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), [])
        rest = prompt.replace(se.plan_reference(False), "")
        assert "{" not in rest and "}" not in rest, mode
        assert prompt.count("May be global picks (applied to every panel):") == 1, mode


# --- LST5 (LS5): L8 for a pick its catalog scope does not allow ---------------------------------

def test_lst5_a_pick_its_scope_does_not_allow_is_l8(ws, tmp_path):
    ctx = _ctx(ws, tmp_path)
    assert _checks(ctx, {"global": [_pick("fast-motion")]}) == ([GLOBAL_L8], [])
    assert _checks(ctx, {"global": [_pick("rain-physics")]})[0] == [
        GLOBAL_L8.replace("fast-motion", "rain-physics")]
    assert _checks(ctx, {"per_beat": {"1": [_pick("film-grain")], "3": [_pick("film-grain")]}}) == (
        [BEAT_L8 % 1, BEAT_L8 % 3], [])
    assert _checks(ctx, {"global": [_pick("film-grain")],
                         "per_beat": {"2": [_pick("fast-motion")]}}) == ([], [])
    assert [se.parse_violation(m) for m in (GLOBAL_L8, BEAT_L8 % 3)] == [
        {"id": "L8", "name": "scope", "scope": "plan", "index": None, "message": GLOBAL_L8},
        {"id": "L8", "name": "scope", "scope": "beat", "index": 3, "message": BEAT_L8 % 3}]
    either = _ctx(ws, tmp_path, entries=_entries(tmp_path, film="either", fast="either"))
    assert _checks(either, {"global": [_pick("fast-motion")],
                            "per_beat": {"2": [_pick("film-grain")]}}) == ([], [])
    swapped = _ctx(ws, tmp_path, entries=_entries(tmp_path, film="beat", fast="global"))
    assert _checks(swapped, {"global": [_pick("fast-motion")],
                             "per_beat": {"2": [_pick("film-grain")]}}) == ([], [])
    assert _checks(swapped, {"global": [_pick("film-grain")]})[0] == [
        GLOBAL_L8.replace("fast-motion", "film-grain")]
    fast = dict((e["id"], e) for e in ctx.catalog["entries"])["fast-motion"]
    pinned = ctx._replace(pinned=[{"path": fast["path"], "strength": 0.8,
                                   "catalog_id": "fast-motion", "kind": "motion"}])
    assert _checks(pinned, {}) == ([], [])
    assert _checks(ctx, {"global": [_pick("film-grain"), _pick("film-grain", 0.7)]})[1] == [
        "plan: L2 style: 2 style LoRAs for every panel (film-grain, film-grain); at most 1"]
    assert _checks(ctx._replace(auto_lora=False), {"global": [_pick("fast-motion")]}) == ([], [])


# --- LST6 (LS6): one copy of a LoRA picked both globally and for some beats ---------------------

def test_lst6_a_global_and_per_beat_duplicate_keeps_one_copy(ws, tmp_path):
    for scope in (None, "either"):
        ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, film=scope, fast="either"))
        plan = _plan(ctx, {"global": [_pick("film-grain"), _pick("fast-motion")],
                           "per_beat": {"1": [_pick("film-grain", 0.6)],
                                        "2": [_pick("film-grain"), _pick("rain-physics")],
                                        "3": [_pick("film-grain")]}})
        assert plan["loras"]["global"] == [_pick("film-grain"), _pick("fast-motion")]
        assert plan["loras"]["per_beat"] == {"2": [_pick("rain-physics")]}
        assert plan["lora_notes"] == [
            "plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 1, 2, 3; "
            "the pipeline kept the global pick and dropped the per-beat copies"]
        hard, advisory = _checks(ctx, {"global": [_pick("film-grain")],
                                       "per_beat": {"2": [_pick("film-grain")]}})
        assert hard == [] and advisory == [
            "plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 2; the "
            "pipeline kept the global pick and dropped the per-beat copies"]
    ctx = _ctx(ws, tmp_path)
    plan = _plan(ctx, {"global": [_pick("fast-motion", 0.9), _pick("film-grain")],
                       "per_beat": {"3": [_pick("fast-motion", 0.6)],
                                    "1": [_pick("fast-motion", 0.7)]}})
    assert plan["loras"]["global"] == [_pick("film-grain")]
    assert plan["loras"]["per_beat"] == {"3": [_pick("fast-motion", 0.6)],
                                         "1": [_pick("fast-motion", 0.7)]}
    assert plan["lora_notes"] == [
        "plan: L6 duplicate: 'fast-motion' was picked both globally and for beat(s) 1, 3; its "
        "catalog scope is beat, so the pipeline kept the per-beat picks and dropped the global "
        "pick"]
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    assert se.lora_checks(ctx, plan, compatible, catalog) == ([], plan["lora_notes"])
    untouched = {"global": [_pick("film-grain"), _pick("nope")],
                 "per_beat": {"9": [_pick("film-grain")], "2": [_pick("nope")]}}
    plan = _plan(ctx, untouched)
    assert plan["loras"]["per_beat"] == untouched["per_beat"] and "lora_notes" not in plan
    assert list(_plan(ctx, {"global": [_pick("film-grain")]}))[-1] == "speech_notes"
    assert "lora_notes" not in _plan(ctx._replace(auto_lora=False), {
        "global": [_pick("film-grain")], "per_beat": {"2": [_pick("film-grain")]}})


# --- LST7 (LS5, LS8): the critic repairs an L8 pick --------------------------------------------

def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def test_lst7_the_critic_moves_a_per_beat_lora_out_of_global(ws, tmp_path, monkeypatch, capsys):
    ctx = _ctx(ws, tmp_path, mode="shots")
    raw = seu.plan_json("shots", 3)
    raw["loras"] = {"global": [_pick("fast-motion")], "per_beat": {}, "stills": []}
    patches = [{"target": "plan", "index": 0, "field": "lora", "reason": "L8",
                "replacement": []},
               {"target": "plan", "index": 2, "field": "lora", "reason": "L8",
                "replacement": [_pick("fast-motion")]}]
    log = seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw), seu.answer(raw)],
                           panel=_panel_script("shots", 3),
                           critic=[seu.answer(seu.critic_json(verdict="revise", patches=patches))])
    rc, _advisories = se.run(ctx)
    assert rc == 0
    calls = seu.agent_log(log)
    assert [r["stage"] for r in calls] == ["plan", "plan", "panel", "panel", "panel", "critic"]
    assert ("YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + GLOBAL_L8 + "\n") in (
        calls[1]["argv"][calls[1]["argv"].index("--user-prompt") + 1])
    critic = calls[-1]["argv"][calls[-1]["argv"].index("--user-prompt") + 1]
    assert "- [hard] " + GLOBAL_L8 + "\n" in critic
    line = dict((e["id"], se.catalog_line(e)) for e in ctx.catalog["entries"])
    assert ("from this catalog:\nMay be global picks (applied to every panel):\n"
            + line["film-grain"] + "\nMay be per-beat picks (applied to their beat only):\n"
            + line["fast-motion"] + "\n" + line["rain-physics"] + "\n- target") in critic
    assert line["ink-stills"] not in critic
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_1", "plan.json"),
              encoding="utf-8") as f:
        loras = json.load(f)["loras"]
    assert (loras["global"], loras["per_beat"]) == ([], {"2": [_pick("fast-motion")]})
    assert "critic round 1 (local): continuity=8 story=8 renderability=8 verdict=revise; 2 " \
           "patch(es): 2 applied, 0 rejected" in capsys.readouterr().out
    state = {"plan": dict(_plan(ctx, {}), panels=3), "parts": []}
    _new, applied, rejected = se.apply_patches(ctx, state, [dict(patches[1], index=0)],
                                               lora_allowed=True)
    assert applied == [] and [r["reason"] for r in rejected] == ["would break " + GLOBAL_L8]


# --- LST8 (LS8): a saved plan the new defaults forbid, and how its scope restores it ------------

def test_lst8_recheck_names_l8_and_either_restores_a_saved_plan(ws, tmp_path, monkeypatch,
                                                                capsys):
    entries = _entries(tmp_path, fast="either")
    ctx = _ctx(ws, tmp_path, entries=entries, mode="shots")
    raw = seu.plan_json("shots", 3)
    raw["loras"] = {"global": [_pick("fast-motion")], "per_beat": {}, "stills": []}
    seu.script_agent(monkeypatch, tmp_path, plan=[seu.answer(raw)],
                     panel=_panel_script("shots", 3))
    assert se.run(ctx)[0] == 0
    capsys.readouterr()

    def never(*args):
        raise AssertionError("a shots re-check with a plan never runs the legacy validator")

    default = ctx._replace(catalog={"schema_version": 1, "entries": _entries(tmp_path)})
    assert se.recheck(default, never)[0] == 2
    err = capsys.readouterr().err
    assert "  - " + GLOBAL_L8 + "\n" in err
    assert err.endswith("rerun with --no-auto-lora, or pass --force-story to regenerate.\n"
                        + HINT + "\n")
    with open(os.path.join(ctx.story_dir, "story_checks.json"), encoding="utf-8") as f:
        assert [v["id"] for v in json.load(f)["hard"]] == ["L8"]
    assert se.recheck(ctx, never)[0] == 0
    assert HINT not in capsys.readouterr().err
    gone = ctx._replace(catalog={"schema_version": 1, "entries": []})
    assert se.recheck(gone, never)[0] == 2
    assert HINT not in capsys.readouterr().err


# --- LST9 (LS4, LS9): the dry run prints the grouped catalog -----------------------------------

def test_lst9_the_dry_run_prints_the_grouped_catalog(tmp_path, story_env):
    entries = _entries(tmp_path)
    seu.make_catalog(story_env["catalog"], entries[:2])
    story_dir = os.path.join(WS, "generated", "stories", "lst9-%d" % os.getpid())
    proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                           "--story-id", os.path.basename(story_dir), "--dry-run", "--no-review",
                           "--shots", "--panels", "4"], cwd=WS, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert ("LoRA catalog (pick only from these):\nMay be global picks (applied to every "
            "panel):\n" + se.catalog_line(entries[0]) + "\nMay be per-beat picks (applied to "
            "their beat only):\n" + se.catalog_line(entries[1]) + "\n\n") in proc.stdout
    assert "Catalog LoRAs: 2 compatible entries in %s" % _catalog_file(story_env) in proc.stdout
    assert not os.path.exists(story_dir)
````

- [ ] **Step 2: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ls-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope.py 2>&1 | tail -1
```
Expected: `6 failed, ... warnings in ...s`. LST4 fails on the paragraph text; LST5 on `([], []) == (['plan: L8 scope: ...'], [])`; LST6 on the per_beat picks (no copy is dropped yet); LST7 on the call stages, `['plan', 'panel', 'panel', 'panel']` (without L8 the plan is accepted at once and no critic runs); LST8 on `0 == 2` (the re-check passes); LST9 because the dry run prints the flat catalog.

- [ ] **Step 3: Edit `story_engine.py` (E19, LORA_PICK_PARAGRAPH and the scope messages).** Old:
```python
LORA_PICK_PARAGRAPH = (
    "an object with the keys global, per_beat and stills. Each pick is an object with the keys "
    "id and strength, taken from the LoRA catalog below; strength must lie inside that entry's "
    "range. global is a list of picks applied to every panel: at most one style LoRA, plus "
    "motion or physics LoRAs that suit the whole movie. per_beat maps each beat number to a list "
    "of motion or physics picks for that beat only, and each key is the beat number alone in "
    'double quotes: the key of beat 1 is "1"; every beat may have at '
    "most one motion or physics LoRA in total, counting global. stills is a list of at most one "
    "stills LoRA.")
```
New:
```python
# LoRA scope spec LS4 (docs/superpowers/specs/2026-11-10-lora-scope-design.md): the catalog
# below the paragraph lists each video LoRA under the places its scope allows (catalog_groups).
LORA_PICK_PARAGRAPH = (
    "an object with the keys global, per_beat and stills. Each pick is an object with the keys "
    "id and strength, taken from the LoRA catalog below; strength must lie inside that entry's "
    "range. The catalog lists each LoRA under the places where it may go. global is a list of "
    "picks applied to every panel, taken only from the LoRAs that may be global picks: at most "
    "one style LoRA, plus motion or physics LoRAs that suit the whole movie. per_beat maps each "
    "beat number to a list of picks for that beat only, taken only from the LoRAs that may be "
    "per-beat picks, and each key is the beat number alone in double quotes: the key of beat 1 "
    'is "1"; a LoRA in global is never also in per_beat, and every beat may have at most one '
    "motion or physics LoRA in total, counting global. stills is a list of at most one stills "
    "LoRA.")
LORA_GLOBAL_GROUP = "May be global picks (applied to every panel):"
LORA_GLOBAL_NONE = "- none, so global stays empty"
LORA_BEAT_GROUP = "May be per-beat picks (applied to their beat only):"
LORA_BEAT_NONE = "- none, so per_beat stays empty"
LORA_STILLS_GROUP = "Stills LoRAs (only for the stills pick):"
# LS5: a pick placed where its catalog scope does not allow it (hard, so the critic repairs it).
LORA_SCOPE_GLOBAL = ("plan: L8 scope: %s may only be a per-beat pick (its catalog scope is "
                     "beat), but it is a global pick; remove it from global and pick it for the "
                     "beats that need it")
LORA_SCOPE_BEAT = ("beat %d: L8 scope: %s may only be a global pick (its catalog scope is "
                   "global), but it is a pick for this beat; remove it from this beat, or move it "
                   "to global if it suits the whole movie")
# LS6: normalize_plan keeps one copy of a LoRA picked both globally and for some beats.
LORA_DUPLICATE_BEATS = ("plan: L6 duplicate: %s was picked both globally and for beat(s) %s; the "
                        "pipeline kept the global pick and dropped the per-beat copies")
LORA_DUPLICATE_GLOBAL = ("plan: L6 duplicate: %s was picked both globally and for beat(s) %s; its "
                         "catalog scope is beat, so the pipeline kept the per-beat picks and "
                         "dropped the global pick")
RECHECK_SCOPE_HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: "
                      "set the LoRA's scope to either with bin/lora-catalog scope ID either (or "
                      "in the movie UI's LoRA catalog), or pass --force-story to regenerate.")
```

- [ ] **Step 4: Edit `story_engine.py` (E20, catalog_groups after catalog_line).** Old:
```python
        _sentence(entry["avoid_when"]) if entry["avoid_when"] else "nothing listed.")


def _pins_block(pins):
```
New:
```python
        _sentence(entry["avoid_when"]) if entry["avoid_when"] else "nothing listed.")


def catalog_groups(ctx, entries):
    """The catalog lines of the plan prompt and the critic prompt (LoRA scope spec LS4): every
    video entry whose scope allows global under LORA_GLOBAL_GROUP, every one whose scope allows a
    beat under LORA_BEAT_GROUP (an either entry is in both; an empty group says so), then the
    stills entries, when there are any, under LORA_STILLS_GROUP. Entries keep their order."""
    scope_of = _lora_catalog(ctx.ws).entry_scope
    video = [e for e in entries if e["target"] == "video"]
    stills = [catalog_line(e) for e in entries if e["target"] != "video"]
    lines = [LORA_GLOBAL_GROUP]
    lines += ([catalog_line(e) for e in video if scope_of(e) in ("global", "either")]
              or [LORA_GLOBAL_NONE])
    lines.append(LORA_BEAT_GROUP)
    lines += ([catalog_line(e) for e in video if scope_of(e) in ("beat", "either")]
              or [LORA_BEAT_NONE])
    return lines + ([LORA_STILLS_GROUP] + stills if stills else [])


def _pins_block(pins):
```

- [ ] **Step 5: Edit `story_engine.py` (E21, build_plan_prompt lists the groups).** Old:
```python
        lora += "\n".join(catalog_line(e) for e in compatible) + _pins_block(pins)
```
New:
```python
        lora += "\n".join(catalog_groups(ctx, compatible)) + _pins_block(pins)
```

- [ ] **Step 6: Edit `story_engine.py` (E22, drop_duplicate_picks before normalize_plan).** Old:
```python
def normalize_plan(ctx, raw):
```
New:
```python
def drop_duplicate_picks(ctx, picks, by_id, n):
    """LoRA scope spec LS6: for each catalog video LoRA that picks["global"] and the per_beat
    picks of beats 1 to n both hold, keep one copy, in place: drop the global copies when the
    entry's scope is beat, else the per-beat copies (a beat key left empty is removed). Returns
    one LORA_DUPLICATE_BEATS or LORA_DUPLICATE_GLOBAL note per such LoRA, in global order."""
    scope_of = _lora_catalog(ctx.ws).entry_scope
    keys = [str(k) for k in range(1, n + 1)]
    notes, seen = [], set()
    for pick in list(picks["global"]):
        entry = by_id.get(pick.get("id")) if _is_pick(pick) else None
        if entry is None or entry["target"] != "video" or entry["id"] in seen:
            continue
        seen.add(entry["id"])

        def same(p):
            return _is_pick(p) and p["id"] == entry["id"]

        beats = [int(key) for key in keys if isinstance(picks["per_beat"].get(key), list)
                 and any(same(p) for p in picks["per_beat"][key])]
        if not beats:
            continue
        if scope_of(entry) == "beat":
            picks["global"] = [p for p in picks["global"] if not same(p)]
            notes.append(LORA_DUPLICATE_GLOBAL % (_q(entry["id"]), _nums(beats)))
            continue
        for k in beats:
            kept = [p for p in picks["per_beat"][str(k)] if not same(p)]
            if kept:
                picks["per_beat"][str(k)] = kept
            else:
                del picks["per_beat"][str(k)]
        notes.append(LORA_DUPLICATE_BEATS % (_q(entry["id"]), _nums(beats)))
    return notes


def normalize_plan(ctx, raw):
```

- [ ] **Step 7: Edit `story_engine.py` (E23, normalize_plan starts with no notes).** Old:
```python
    loras = raw.get("loras")
    if not ctx.auto_lora or not isinstance(loras, dict):
        picks = _empty_loras()
```
New:
```python
    loras = raw.get("loras")
    notes = []
    if not ctx.auto_lora or not isinstance(loras, dict):
        picks = _empty_loras()
```

- [ ] **Step 8: Edit `story_engine.py` (E24, normalize_plan drops the duplicates and keeps the notes).** Old:
```python
                 "stills": _normalize_picks(loras.get("stills"), by_id)}
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
```
New:
```python
                 "stills": _normalize_picks(loras.get("stills"), by_id)}
        notes = drop_duplicate_picks(ctx, picks, by_id, len(beats))
    picks["pinned"] = [dict(pin) for pin in ctx.pinned]
    plan["loras"] = picks
    if notes:
        plan["lora_notes"] = notes
```

- [ ] **Step 9: Edit `story_engine.py` (E25, lora_checks' docstring).** Old:
```python
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA. Hard:
    L1, L6, L7 and a strength outside (0, 2], which the renderer refuses; L2-L4 and a strength
    outside the entry's own range are advisory (dialogue spec 6.3, Q4)."""
```
New:
```python
    """(hard, advisory) LoRA violations of a plan (RS11, LC12). Not run without auto LoRA. Hard:
    L1, L6, L7, L8 (LoRA scope spec LS5) and a strength outside (0, 2], which the renderer
    refuses; L2-L4, a strength outside the entry's own range and normalize_plan's duplicate
    notes (LS6) are advisory (dialogue spec 6.3, Q4)."""
```

- [ ] **Step 10: Edit `story_engine.py` (E26, L8 and the duplicate notes in lora_checks).** Old:
```python
    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"
```
New:
```python
    # LoRA scope spec LS5: L8 for a pick its catalog scope does not allow; LS6's notes.
    for e in global_picks:
        if lora_catalog.entry_scope(e) == "beat":
            hard.append(LORA_SCOPE_GLOBAL % _q(e["id"]))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if lora_catalog.entry_scope(e) == "global":
                hard.append(LORA_SCOPE_BEAT % (k, _q(e["id"])))
    advisory += plan.get("lora_notes", [])

    def pin_label(pin):
        return pin["catalog_id"] or "pinned LoRA"
```

- [ ] **Step 11: Edit `story_engine.py` (E27, the per-beat L2 advisory goes).** Old:
```python
                    % (len(styles), ", ".join(styles)))
    for k in sorted(per_beat):
        for e in per_beat[k]:
            if e["kind"] == "style":
                advisory.append("beat %d: L2 style: style LoRA %s can only be a global pick"
                            % (k, _q(e["id"])))
    by_cast = {c["id"]: c for c in plan["cast"]}
```
New:
```python
                    % (len(styles), ", ".join(styles)))
    by_cast = {c["id"]: c for c in plan["cast"]}
```

- [ ] **Step 12: Edit `story_engine.py` (E28, the critic's catalog lines are grouped).** Old:
```python
        self.catalog_lines = ([catalog_line(e) for e in compatible if e["target"] == "video"]
                              if lora_patches_allowed(ctx) else None)
```
New:
```python
        self.catalog_lines = (catalog_groups(ctx, [e for e in compatible
                                                   if e["target"] == "video"])
                              if lora_patches_allowed(ctx) else None)
```

- [ ] **Step 13: Edit `story_engine.py` (E29, critic_round allows lora patches for L8).** Old:
```python
            parse_violation(m)["id"] in ("L1", "L5", "L6", "L7") for m in prev["hard"])
```
New:
```python
            parse_violation(m)["id"] in ("L1", "L5", "L6", "L7", "L8") for m in prev["hard"])
```

- [ ] **Step 14: Edit `story_engine.py` (E30, recheck names how to restore an L8 pick).** Old:
```python
                          "rerun with --no-auto-lora, or pass --force-story to regenerate.",
                          file=sys.stderr)
                return 2, advisory
```
New:
```python
                          "rerun with --no-auto-lora, or pass --force-story to regenerate.",
                          file=sys.stderr)
                if any(parse_violation(m)["id"] == "L8" for m in blocking_list):
                    print(RECHECK_SCOPE_HINT, file=sys.stderr)
                return 2, advisory
```

- [ ] **Step 15: Edit `bin/ltx-movie` (E31, _catalog_checks_error's docstring names L8).** Old:
```python
    """The LC13 Error line when the plan's LoRA picks fail the engine's catalog checks (L1-L7)."""
```
New:
```python
    """The LC13 Error line when the plan's LoRA picks fail the engine's catalog checks (L1-L8)."""
```

- [ ] **Step 16: Edit `tests/test_story_engine.py` (E32, _lora_ctx's motion and physics entries may be either).** Old:
```python
        seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
```
New:
```python
        seu.catalog_entry(seu.lora_file(files, "big"), "big-style", kind="style"),
        seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),
        seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                          scope="either"),
        seu.catalog_entry(seu.lora_file(files, "ink"), "ink-stills", kind="style",
```

- [ ] **Step 17: Edit `tests/test_story_engine.py` (E33, RST15's comment).** Old:
```python
    # L1, L6, L7 and an L5 strength outside (0, 2] are hard; L2-L4 and an L5 strength outside
```
New:
```python
    # L1, L6, L7, L8 and an L5 strength outside (0, 2] are hard; L2-L4 and an L5 strength outside
```

- [ ] **Step 18: Edit `tests/test_story_engine.py` (E34, RST15: a per-beat style pick is L8).** Old:
```python
        ({"per_beat": {"2": [pick("film-grain")]}}, [],
         ["beat 2: L2 style: style LoRA 'film-grain' can only be a global pick"]),
```
New:
```python
        ({"per_beat": {"2": [pick("film-grain")]}},
         ["beat 2: L8 scope: 'film-grain' may only be a global pick (its catalog scope is "
          "global), but it is a pick for this beat; remove it from this beat, or move it to "
          "global if it suits the whole movie"], []),
```

- [ ] **Step 19: Edit `tests/test_story_engine.py` (E35, _lora_state's motion entry may be either).** Old:
```python
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    kw = {"catalog": {"schema_version": 1, "entries": entries}}
```
New:
```python
    entries = [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    kw = {"catalog": {"schema_version": 1, "entries": entries}}
```

- [ ] **Step 20: Edit `tests/test_dialogue.py` (E36, DLG18's motion and physics entries may be either).** Old:
```python
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics")]
    lctx = seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries})
```
New:
```python
               seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion", scope="either"),
               seu.catalog_entry(seu.lora_file(files, "rain"), "rain-physics", kind="physics",
                                 scope="either")]
    lctx = seu.make_ctx(se, ws, catalog={"schema_version": 1, "entries": entries})
```

- [ ] **Step 21: Edit `tests/test_dialogue.py` (E37, DLG18: the per-beat style case leaves the advisory loop).** Old:
```python
            ({"per_beat": {"2": [pick("film-grain")]}}, "L2", lctx),
            ({"global": [pick("fast-motion")], "per_beat": {"2": [pick("rain-physics")]}}, "L3",
```
New:
```python
            ({"global": [pick("fast-motion")], "per_beat": {"2": [pick("rain-physics")]}}, "L3",
```

- [ ] **Step 22: Edit `tests/test_dialogue.py` (E38, DLG18: a per-beat style pick is L8).** Old:
```python
    assert _only(lora({"stills": [pick("nope"), pick("nope-two")]})[0], "L7")
```
New:
```python
    assert _only(lora({"stills": [pick("nope"), pick("nope-two")]})[0], "L7")
    assert _only(lora({"per_beat": {"2": [pick("film-grain")]}})[0], "L8")
```

- [ ] **Step 23: Edit `tests/test_per_beat_json.py` (E39, PJT1's per_beat clause).** Old:
```python
CLAUSE = ("per_beat maps each beat number to a list of motion or physics picks for that beat "
          "only, and each key is the beat number alone in double quotes: the key of beat 1 is "
          '"1";')
```
New:
```python
CLAUSE = ("per_beat maps each beat number to a list of picks for that beat only, taken only "
          "from the LoRAs that may be per-beat picks, and each key is the beat number alone in "
          'double quotes: the key of beat 1 is "1";')
```

- [ ] **Step 24: Edit `tests/test_per_beat_json.py` (E40, PJT1's paragraph).** Old:
```python
        "entry's range. global is a list of picks applied to every panel: at most one style "
        "LoRA, plus motion or physics LoRAs that suit the whole movie. " + CLAUSE + " every beat "
        "may have at most one motion or physics LoRA in total, counting global. stills is a "
        "list of at most one stills LoRA.")
```
New:
```python
        "entry's range. The catalog lists each LoRA under the places where it may go. global "
        "is a list of picks applied to every panel, taken only from the LoRAs that may be global "
        "picks: at most one style LoRA, plus motion or physics LoRAs that suit the whole movie. "
        + CLAUSE + " a LoRA in global is never also in per_beat, and every beat may have at "
        "most one motion or physics LoRA in total, counting global. stills is a list of at most "
        "one stills LoRA.")
```

- [ ] **Step 25: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/ls-baseline/pyc $py -m py_compile story_engine.py bin/ltx-movie tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py tests/test_lora_scope.py && echo "$py compiled"; done
git diff --numstat -- story_engine.py bin/ltx-movie tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py
wc -l tests/test_lora_scope.py                             # 302
grep -c "L2 style: style LoRA" story_engine.py              # 0
grep -c "^import re$" bin/ltx-movie                         # 0
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope.py tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py tests/test_plan_budget.py tests/test_lora_catalog.py 2>&1 | tail -1
zsh $S/ls-baseline/gate-run.sh 2
git add story_engine.py bin/ltx-movie tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py tests/test_lora_scope.py
git diff --cached --name-only    # exactly the six paths above, each under qwen-agent-workspace/
git commit -m "story_engine: the plan prompt lists catalog LoRAs under the places their scope allows, a pick its scope forbids is the hard violation L8, and a LoRA picked globally and for a beat keeps one copy (lora-scope LS4-LS6, LS8)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`.
- The numstat lines are `1 1 bin/ltx-movie`, `106 16 story_engine.py`, `4 3 tests/test_dialogue.py`, `9 7 tests/test_per_beat_json.py` and `9 6 tests/test_story_engine.py`.
- The six-file pytest line is `1 failed, 229 passed, 1 skipped, ... warnings in ...s`. The one failure is the baseline's `test_rst62_import_sets`.
- The gate prints the summary `3 failed, P0 + 8 passed, 2 skipped` (2742 passed when P0 is 2734) and the gate line `lost 1 (listed 1, unexpected 0); new tests 9, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.


### Task 3: the scope field, column and route of the movie UI's LoRAs tab (one commit)

**Files:** `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js`, `tests/test_movie_ui_http.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_seedgen.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_lora_scope_ui.py` (new). None is pinned by `test_mut26`.

**Interfaces** (new or changed; everything else is unchanged):
- `movie_ui_server.ROUTES` gains `("POST", r"/api/loras/scope", "h_lora_scope", "/api/loras/scope")`; `movie_ui_server.LORA_SCOPES`; `_h_lora_scope(self, groups, query, body)`, bound as `MovieUIHandler.h_lora_scope`; `_h_lora_add` reads `scope` (LS7).
- `index.html`: `#l-scope` and the Scope column. `app.js`: `LORA_SCOPE_DEFAULTS`, `scopeCell(e)` (LS7).

- [ ] **Step 1: Write `tests/test_lora_scope_ui.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for catalog LoRA scopes in the movie UI
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, LS7: LST10, LST11): the scope of the
add form, the per-row scope select and POST /api/loras/scope.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_ui.py

The server runs against the stub workspace of movie_ui_testutil (its bin/lora-catalog is a stub
that records argv), under a temporary HOME on a free 127.0.0.1 port. Stdlib and pytest.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import movie_ui_server as srv  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402


@pytest.fixture
def ui(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    workspace = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"ws": workspace, "srv": running}
    running.close()
    mt.kill_everything(state)


def test_lst10_the_scope_endpoints(ui):
    s, ws = ui["srv"], ui["ws"]
    assert ("POST", r"/api/loras/scope", "h_lora_scope", "/api/loras/scope") in srv.ROUTES
    assert srv.LORA_SCOPES == lora_catalog.SCOPES
    add = {"ws": ws, "path": "/l/fight.safetensors", "id": "fight", "kind": "motion",
           "target": "video", "base_models": ["M1"], "triggers": [], "description": "a fight",
           "use_when": "fights", "avoid_when": "", "default_strength": 0.8,
           "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    for scope, tail in (("either", ["--rank", "16", "--scope", "either"]),
                        (None, ["--rank", "16"])):
        status, _h, payload = mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))
        assert status == 200, payload
        assert mt.stub_calls(ws)[-1]["argv"] == [
            "add", "/l/fight.safetensors", "--id", "fight", "--kind", "motion", "--target",
            "video", "--base-model", "M1", "--description", "a fight", "--use-when", "fights",
            "--default-strength", "0.8", "--strength-range", "0.5,1.0"] + tail
    for scope in ("default", "anywhere", 3, ["beat"]):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (
            400, {"error": "scope must be global, beat, either or null"}), scope
    for scope in ("global", "beat", "either", "default"):
        status, _h, payload = mt.api(s, "POST", "/api/loras/scope",
                                     body={"ws": ws, "id": "fight", "scope": scope})
        assert status == 200 and payload["run"]["exit_code"] == 0
        assert mt.stub_calls(ws)[-1]["argv"] == ["scope", "fight", scope]
    calls = len(mt.stub_calls(ws))
    for body, error in (({"id": "fight", "scope": None}, "scope must be global, beat, either or "
                                                         "default"),
                        ({"id": "fight", "scope": "Beat"}, "scope must be global, beat, either "
                                                           "or default"),
                        ({"id": "-x", "scope": "beat"}, "id must not start with '-'"),
                        ({"id": 5, "scope": "beat"}, "id must be a string")):
        assert mt.api(s, "POST", "/api/loras/scope", body=dict(body, ws=ws))[::2] == (
            400, {"error": error}), body
    assert len(mt.stub_calls(ws)) == calls
    assert mt.api(s, "POST", "/api/loras/scope", body={"ws": ws, "id": "fight", "scope": "beat"},
                  token=None)[::2] == (401, {"error": "missing or invalid token"})


def test_lst11_the_static_page_sets_the_scope():
    static = os.path.join(WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert html.count('id="l-scope"') == 1
    assert ('<select id="l-scope"><option value="">default for the kind</option><option>global'
            '</option><option>beat</option><option>either</option></select>') in html
    assert "<th>Target</th><th>Scope</th><th>Strength</th>" in html
    assert html.index('id="l-target"') < html.index('id="l-scope"') < html.index('id="l-add"')
    defaults = re.search(r"const LORA_SCOPE_DEFAULTS = \{style: \"(\w+)\", motion: \"(\w+)\", "
                         r"physics: \"(\w+)\"\};", js)
    assert defaults and dict(zip(("style", "motion", "physics"), defaults.groups())) == (
        lora_catalog.DEFAULT_SCOPES)
    for text in ('scope: $("#l-target").value === "video" && $("#l-scope").value ? '
                 '$("#l-scope").value : null,',
                 'api("POST", "/api/loras/scope", {ws: S.ws, id: e.id, scope: select.value})',
                 'select.value = e.scope || "default";',
                 'scopeCell(e), el("td", {text: strength}),',
                 '$("#l-scope").disabled = $("#l-target").value !== "video";'):
        assert js.count(text) == 1, text
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
````

- [ ] **Step 2: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ls-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_ui.py 2>&1 | tail -1
```
Expected: `2 failed` (the summary line may also count warnings). LST10 fails because `/api/loras/scope` is not in `ROUTES`, LST11 on `0 == 1` (no `id="l-scope"` yet).

- [ ] **Step 3: Edit `movie_ui_server.py` (E41, the scope route).** Old:
```python
    ("POST", r"/api/loras/verify", "h_lora_verify", "/api/loras/verify"),
```
New:
```python
    ("POST", r"/api/loras/verify", "h_lora_verify", "/api/loras/verify"),
    ("POST", r"/api/loras/scope", "h_lora_scope", "/api/loras/scope"),
```

- [ ] **Step 4: Edit `movie_ui_server.py` (E42, _h_lora_add reads the scope).** Old:
```python
    alpha = _typed(body, "alpha", "int", "an integer or null", optional=True)
    no_arch_check = body.get("no_arch_check", False)
```
New:
```python
    alpha = _typed(body, "alpha", "int", "an integer or null", optional=True)
    scope = body.get("scope")
    if scope is not None and scope not in LORA_SCOPES:
        raise ApiError(400, "scope must be global, beat, either or null")
    no_arch_check = body.get("no_arch_check", False)
```

- [ ] **Step 5: Edit `movie_ui_server.py` (E43, _h_lora_add passes --scope).** Old:
```python
    if alpha is not None:
        args += ["--alpha", str(alpha)]
    if no_arch_check:
```
New:
```python
    if alpha is not None:
        args += ["--alpha", str(alpha)]
    if scope is not None:
        args += ["--scope", scope]
    if no_arch_check:
```

- [ ] **Step 6: Edit `movie_ui_server.py` (E44, LORA_SCOPES and _h_lora_scope before _h_lora_remove).** Old:
```python
def _h_lora_remove(self, groups, query, body):
```
New:
```python
# LoRA scope spec LS7 (docs/superpowers/specs/2026-11-10-lora-scope-design.md): lora_catalog.SCOPES.
LORA_SCOPES = ("global", "beat", "either")


def _h_lora_scope(self, groups, query, body):
    real = self.ws(body.get("ws"))
    entry_id = _typed(body, "id", "str", "a string")
    _check_arg("id", entry_id)
    scope = body.get("scope")
    if scope not in LORA_SCOPES + ("default",):
        raise ApiError(400, "scope must be global, beat, either or default")
    return 200, {"run": _lora_action(real, ["scope", entry_id, scope])}


def _h_lora_remove(self, groups, query, body):
```

- [ ] **Step 7: Edit `movie_ui_server.py` (E45, the handler binding).** Old:
```python
MovieUIHandler.h_lora_verify = _h_lora_verify
```
New:
```python
MovieUIHandler.h_lora_verify = _h_lora_verify
MovieUIHandler.h_lora_scope = _h_lora_scope
```

- [ ] **Step 8: Edit `static/movie-ui/index.html` (E46, the Scope column).** Old:
```html
  <table id="l-table" class="list"><thead><tr><th>ID</th><th>Kind</th><th>Target</th><th>Strength</th><th>Triggers</th><th>Base models</th><th>Verify</th><th></th></tr></thead><tbody></tbody></table>
```
New:
```html
  <table id="l-table" class="list"><thead><tr><th>ID</th><th>Kind</th><th>Target</th><th>Scope</th><th>Strength</th><th>Triggers</th><th>Base models</th><th>Verify</th><th></th></tr></thead><tbody></tbody></table>
```

- [ ] **Step 9: Edit `static/movie-ui/index.html` (E47, the Scope field of the add form).** Old:
```html
    <label>Target <select id="l-target"><option>video</option><option>stills</option></select></label>
```
New:
```html
    <label>Target <select id="l-target"><option>video</option><option>stills</option></select></label>
    <label>Scope <select id="l-scope"><option value="">default for the kind</option><option>global</option><option>beat</option><option>either</option></select></label> <span class="muted">Where the story planner may put a video LoRA: global applies it to every panel, beat only to the beats it suits, either lets the planner choose. The default is global for style and beat for motion and physics. A stills LoRA has no scope.</span>
```

- [ ] **Step 10: Edit `static/movie-ui/app.js` (E48, LORA_SCOPE_DEFAULTS).** Old:
```javascript
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
```
New:
```javascript
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
  const LORA_SCOPE_DEFAULTS = {style: "global", motion: "beat", physics: "beat"};  // lora_catalog.DEFAULT_SCOPES (LoRA scope spec LS7)
```

- [ ] **Step 11: Edit `static/movie-ui/app.js` (E49, the scope cell of a catalog row).** Old:
```javascript
        el("td", {text: strength}), el("td", {text: (e.triggers || []).join(", ")}),
```
New:
```javascript
        scopeCell(e), el("td", {text: strength}), el("td", {text: (e.triggers || []).join(", ")}),
```

- [ ] **Step 12: Edit `static/movie-ui/app.js` (E50, scopeCell before splitList).** Old:
```javascript
  function splitList(selector) {
```
New:
```javascript
  // LoRA scope spec LS7: a video entry's scope is chosen in its row; "default" clears it.
  function scopeCell(e) {
    if (e.target !== "video") { return el("td", {text: "-"}); }
    const select = el("select", {cls: "l-row-scope"}, [el("option", {value: "default", text: "default (" + LORA_SCOPE_DEFAULTS[e.kind] + ")"}),
      el("option", {value: "global", text: "global"}), el("option", {value: "beat", text: "beat"}),
      el("option", {value: "either", text: "either"})]);
    select.value = e.scope || "default";
    select.addEventListener("change", async function () {
      const out = await api("POST", "/api/loras/scope", {ws: S.ws, id: e.id, scope: select.value});
      $("#l-output").textContent = out.data && out.data.run ? runText(out.data.run) : (out.data && out.data.error);
      loadCatalogTable();
      loadCatalog();
    });
    return el("td", {}, [select]);
  }

  function splitList(selector) {
```

- [ ] **Step 13: Edit `static/movie-ui/app.js` (E51, a stills target disables the scope field).** Old:
```javascript
    $("#l-target").addEventListener("change", fillLoraBaseModels);
```
New:
```javascript
    $("#l-target").addEventListener("change", fillLoraBaseModels);
    $("#l-target").addEventListener("change", function () { $("#l-scope").disabled = $("#l-target").value !== "video"; });
```

- [ ] **Step 14: Edit `static/movie-ui/app.js` (E52, the add body carries the scope).** Old:
```javascript
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha"),
        no_arch_check: $("#l-no-arch-check").checked};
```
New:
```javascript
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha"),
        scope: $("#l-target").value === "video" && $("#l-scope").value ? $("#l-scope").value : null,
        no_arch_check: $("#l-no-arch-check").checked};
```

- [ ] **Step 15: Edit `tests/test_movie_ui_http.py` (E53, the route count).** Old:
```python
    assert len(srv.ROUTES) == 63
```
New:
```python
    assert len(srv.ROUTES) == 64
```

- [ ] **Step 16: Edit `tests/test_location_ui.py` (E54, the route count).** Old:
```python
    assert len(srv.ROUTES) == 63
```
New:
```python
    assert len(srv.ROUTES) == 64
```

- [ ] **Step 17: Edit `tests/test_movie_ui_seedgen.py` (E55, the route count).** Old:
```python
    assert len(srv.ROUTES) == 63
```
New:
```python
    assert len(srv.ROUTES) == 64
```

- [ ] **Step 18: Edit `tests/test_movie_ui_seedfolder.py` (E56, SDT11's route count).** Old:
```python
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 63
```
New:
```python
    assert routes[i + 1] == ("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")
    assert len(srv.ROUTES) == 64
```

- [ ] **Step 19: Edit `tests/test_movie_ui_seedfolder.py` (E57, SDT29's route count).** Old:
```python
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 63
```
New:
```python
                             "/api/characters/seed-folder")
    assert len(srv.ROUTES) == 64
```

- [ ] **Step 20: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/ls-baseline/pyc $py -m py_compile movie_ui_server.py tests/test_lora_scope_ui.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py && echo "$py compiled"; done
if command -v node >/dev/null; then node --check static/movie-ui/app.js && echo "node ok"; fi
git diff --numstat -- movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py
wc -l tests/test_lora_scope_ui.py                          # 102
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_ui.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
zsh $S/ls-baseline/gate-run.sh 3
git add movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py tests/test_lora_scope_ui.py
git diff --cached --name-only    # exactly the eight paths above, each under qwen-agent-workspace/
git commit -m "movie-ui: the LoRAs tab sets a catalog video LoRA's scope in the add form and in each catalog row, through POST /api/loras/scope (lora-scope LS7)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`, and `node ok` is printed when node is installed.
- The numstat lines are `21 0 movie_ui_server.py`, `20 1 static/movie-ui/app.js`, `2 1 static/movie-ui/index.html`, `1 1 tests/test_location_ui.py`, `1 1 tests/test_movie_ui_http.py`, `2 2 tests/test_movie_ui_seedfolder.py` and `1 1 tests/test_movie_ui_seedgen.py`.
- The five-file pytest line is `281 passed` (and possibly a warnings count) `in ...s`.
- The gate prints the summary `3 failed, P0 + 10 passed, 2 skipped` (2744 passed when P0 is 2734) and the gate line `lost 1 (listed 1, unexpected 0); new tests 11, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.


### Task 4: the `test_mut26` re-baseline (a test-only commit; never amend)

**This task runs after Task 5** (the fix round, at the end of this document), not after Task 3. Task 5's commit is the last code commit and changes all four pinned files (`lora_catalog.py`, `bin/lora-catalog`, `story_engine.py`, `bin/ltx-movie`), so the baseline chain moves from per-beat-json's code commit to Task 5's commit. (Task 2's commit also changed pinned files, and Task 3's changed none; neither is named.) If a later review fix adds another commit that changes a pinned file, this task runs after that one and names it instead. Its gate is `gate-run.sh 4`, run after `gate-run.sh 5`.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- story_engine.py lora_catalog.py bin/lora-catalog bin/ltx-movie); echo $SHA
git log -1 --format=%s $SHA          # Task 5's subject: lora-scope fix round: a style LoRA's scope may only be global, ...
OLD=$(grep -o 'BASELINE = "[0-9a-f]*"' tests/test_movie_ui_builder.py | cut -d'"' -f2); echo $OLD
grep -c "then to $OLD (per-beat-json)\.$" tests/test_movie_ui_builder.py      # 1
git diff --quiet $SHA HEAD -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "no pinned file changed after SHA"
git diff --name-only $OLD $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected:
- a 40-hex `SHA` whose subject is Task 5's (if it is Task 2's, Task 5 has not run: stop);
- `OLD` is the 40-hex per-beat-json code commit, and the comment chain ends with it;
- `no pinned file changed after SHA`;
- exactly four paths: `qwen-agent-workspace/bin/lora-catalog`, `qwen-agent-workspace/bin/ltx-movie`, `qwen-agent-workspace/lora_catalog.py` and `qwen-agent-workspace/story_engine.py`.

The 23 paths are written out in full because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Wherever OLD or SHA appears below, type the 40 characters of `OLD` or `SHA`.
  - Replace `then to OLD (per-beat-json).` with `then to OLD (per-beat-json), then to SHA (lora-scope).` This occurs once, at the end of the long comment line (`:291`).
  - Replace `    BASELINE = "OLD"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- story_engine.py lora_catalog.py bin/lora-catalog bin/ltx-movie)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                     # 1
grep -c "(per-beat-json), then to $SHA (lora-scope)\.$" tests/test_movie_ui_builder.py  # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/ls-baseline/gate-run.sh 4
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the lora-scope commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output (after Task 5):
- The summary `2 failed, P0 + 16 passed, 2 skipped` (2750 passed when P0 is 2734).
- The gate line `lost 0 (listed 0, unexpected 0); new tests 16, not passing 0; baseline failures still failing 2 of 2`.
- `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.
- `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/ls-baseline/task-4-pytest.txt` prints `1`.

### Verification (controller)

- **V1:** confirm LSK1 from Task 4's gate output (Task 4 runs after Task 5), and LSK2 with (`B` from "Before Task 1", Step A; `152e6ab` when per-beat-json's PR merge commit was used):
  - `git diff --numstat $B HEAD -- . ':(exclude)docs'` prints exactly these 21 lines (in git's path order): `72 9 bin/lora-catalog`, `6 2 bin/ltx-movie`, `27 1 lora_catalog.py`, `23 0 movie_ui_server.py`, `30 1 static/movie-ui/app.js`, `2 1 static/movie-ui/index.html`, `140 35 story_engine.py`, `12 8 tests/story_engine_testutil.py`, `4 3 tests/test_dialogue.py`, `1 1 tests/test_location_ui.py`, `7 6 tests/test_lora_catalog.py`, `303 0 tests/test_lora_scope.py`, `183 0 tests/test_lora_scope_catalog.py`, `297 0 tests/test_lora_scope_fix.py`, `107 0 tests/test_lora_scope_ui.py`, `2 2 tests/test_movie_ui_builder.py`, `1 1 tests/test_movie_ui_http.py`, `2 2 tests/test_movie_ui_seedfolder.py`, `1 1 tests/test_movie_ui_seedgen.py`, `9 7 tests/test_per_beat_json.py`, `9 6 tests/test_story_engine.py` (each path under `qwen-agent-workspace/`). These counts hold when every block of Tasks 1-3 and 5 applied as written (Tasks 1-3 did, at `7dd24ac`); a re-derived block may change its file's count.
  - `git diff $B HEAD -- bin/ltx-mlx-render bin/ltx-story-manifest bin/ltx-story-images bin/qwen-agent character_lib.py location_lib.py movie_ui_lib.py scripts | wc -l` prints `0`.
- **V2:** an Opus design review (the `design-reviewer` agent) of the four commits against this spec, focused on LS5 (L8 only for resolved picks, never for pins), LS6 (which copy goes, only beats 1 to N, the notes), LS7 (the server's checks and argv) and LS9 (nothing else changes). Each finding is fixed in a new commit. A fix that touches a pinned file is followed by another Task 4-style baseline commit, and V1 runs again. **Done:** the review of Tasks 1-3 (at `7dd24ac`) gave one must-fix, two should-fixes and a nit; they are amendments A1-A4, implemented by Task 5, after which Task 4 runs once. Then a second Opus review of Task 5's commit, focused on A1 (every place a style scope can be set or read), A2 (both patch orders, and that a patch that breaks the plan in every order is still rejected) and A3 (the exact two-line error, and no new literal in bin/ltx-movie that RST50, L17 or L46 count).
- **V3:** live checks LV1-LV5 (Section 6). The user runs them on macstudio; the assistant never does. LV5 is the UI check.

### Replay result

The full suite ran on `$S/ls-replay3` (`$S/ls-base` with the blocks of Tasks 1-3 applied) with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors`. The result was `2 failed, 2739 passed, 8 skipped`. Compared test by test with the same run on `$S/ls-base` (`2 failed, 2728 passed, 8 skipped`):
- **New tests.** All 11 test IDs of the three new files passed.
- **Lost.** None. The 2 baseline failures (`test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`) still fail, and no test ID disappeared.
- **Edited tests.** LCT9, RST15, RST31, LCT28, DLG18, PJT1, PJT4, MUT18, LU1, SGT20, SDT11 and SDT29 pass, and so do RST8 and RST47, which are not edited.
- **Copy-layout artifacts.** Both runs have the same 8 skips; 6 of them come from the copies having no `.git` (`test_mut26` and the 5 `d210c26` tests). In `$S/ls-wt` these run, and `test_mut26` fails from Task 1 until Task 4. In the worktree the expected summary is therefore `2 failed, P0 + 11 passed, 2 skipped` after Task 4.
- **The task trees.** On `$S/ls-red2` (Task 1 only) Task 1's four-file run gave `1 failed, 210 passed, 1 skipped`; on `$S/ls-red3` (Tasks 1 and 2) Task 2's six-file run gave `1 failed, 229 passed, 1 skipped`; on the full replay Task 3's five-file run gave `281 passed`. The one failure is `test_rst62_import_sets`.
- **Red steps.** Before their task's edits, the new files gave `3 failed`, `6 failed` and `2 failed`, with the reasons listed in the tasks.
- **Other checks.** Both Pythons compiled every Python file the plan changes, `node --check` passed on `app.js`, and the five script-mode runs printed `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68` and `OK 205/205`.
- **Mutations.** Each of the 34 mutations of Section 5 made at least one of the new or edited tests fail, on copies of the replay (`$S/ls-mut`).
- **The document.** `extract.py` (the script of "Before Task 1", Step B) applied all 60 blocks of this document to a fresh copy of `$S/ls-base`, and the result was byte-identical to the replay (`$S/ls-check`).

**Found while replaying, and fixed in this plan:**
1. Two more route-count pins, `test_sdt11` and `test_sdt29` in `tests/test_movie_ui_seedfolder.py`, failed the first full run (`64 == 63`); E56 and E57 update them. Each Old there carries the line above the count, because `    assert len(srv.ROUTES) == 63` occurs twice in that file.
2. The first draft of LST7 expected one plan call. `plan_round` already retries a plan whose hard problems include L8, and the retry prompt names it, so the test now scripts two plan replies and checks the retry text.
3. `save_catalog` sorts entries by id, so LST1 and LST3 compare entries in id order.

---

## Fix round (review findings)

The V2 review (an Opus design review of Tasks 1-3's commits, `b3303ab`, `f9f7c7d` and `7dd24ac`) found one must-fix, two should-fixes and a nit. Each was re-verified against the code at `7dd24ac` before this section was written. They are amendments A1-A4 below, and Task 5 implements all four in one code commit. Task 4 then runs after Task 5. Earlier sections carry an "(A1)"-style marker where an amendment changes them; where a marker and older text disagree, the amendment wins. The blocks of Tasks 1-3 are left as they were committed.

**A1 (must-fix 1): a style LoRA's scope may only be `global`.**
- **The finding.** `_catalog_panel_loras` (`bin/ltx-movie:2035-2071`) builds each panel's list from the motion and physics picks of `global + per_beat[k]` and the style picks of `global` only. So a per-beat style pick is dropped without a message. `bin/ltx-story-manifest:272-274` also refuses a panel with two style LoRAs. Yet after Tasks 1-3 a style entry may have the scope `beat` or `either` (CLI and UI), the prompt lists it under `May be per-beat picks`, L8 lets its per-beat pick pass, and Decision 6 removed the per-beat L2 advisory. A per-beat style pick is therefore never rendered.
- **The ruling (decided; implemented here).** A style entry's scope may only be `global`. Rendering per-beat style picks is out of scope (0.4).
- **Where it is enforced:**
  - `lora_catalog.validate_entry`: for a video entry of kind `style`, a `scope` other than `global` raises `CatalogError("entry <id>: scope must be global for a style LoRA, which applies to every panel, got <repr>")`. No scope, or `global`, is valid. A value outside `SCOPES` still gets LS1's message first. A stills entry's scope stays accepted and ignored (Decision 1), also when its kind is `style`.
  - `lora_catalog.entry_scope` returns `"global"` for every video entry of kind `style`, whatever its `scope`. Validation already guarantees that for a loaded catalog. Putting the rule in `entry_scope` too covers an entry that never passed `validate_entry` (an in-memory catalog, as `make_ctx` builds), so `catalog_groups`, L8, `drop_duplicate_picks` and `bin/lora-catalog list` can never disagree with Phase 3.
  - `bin/lora-catalog add --kind style --scope beat|either` exits 2 before anything is read, with `Error: --scope <S> applies only to motion and physics LoRAs; a style LoRA is only ever a global pick`. The stills refusal comes first, so it still wins for a stills LoRA. `--scope global` on a style LoRA is accepted and written.
  - `bin/lora-catalog scope ID beat|either` for a style entry exits 2 with `Error: <ID> is a style LoRA; a style LoRA is only ever a global pick, so its scope is global or default` and writes nothing (after the stills refusal). `global` and `default` work as before; `default` prints `<ID>: scope global (the default for a style LoRA) in <path>`.
  - The docstring and both help texts of bin/lora-catalog say a style LoRA is always global.
  - The movie UI: `syncLoraScope()` disables the form's Scope select when Target is `stills` or Kind is `style`. It runs on a Target change, on a Kind change, and once in `setupLoras` (the Kind select starts at `style`). The add body sends `scope: null` whenever the select is disabled. A style row's Scope cell is the text `global`, with no select. The note under the field is rewritten. `LORA_SCOPE_DEFAULTS` does not change (it still mirrors `DEFAULT_SCOPES`, which keeps `style: global`; LST11).
  - The server: `_h_lora_add` answers 400 `scope must be global or null for a style LoRA` for kind `style` with scope `beat` or `either`, and runs nothing. `POST /api/loras/scope` does not change. The server never reads the catalog (movie-ui GC7), so it does not know an entry's kind; bin/lora-catalog refuses with exit 2, and the route returns that run with 200, as for every other refused run (LS7). The UI never sends such a request, because a style row has no select.
- **The prompt and L8 for a style LoRA (no code change).** `catalog_groups` uses `entry_scope`, so a style entry is listed only under `May be global picks (applied to every panel):`. `LORA_PICK_PARAGRAPH` keeps its Task 2 text: its per_beat clause, "taken only from the LoRAs that may be per-beat picks", now never includes a style LoRA, which is what Phase 3 renders. Changing it again would re-touch PJT1, PJT4 and LST4 for no change in behaviour. Every per-beat pick of a style video entry is the hard `beat <k>: L8 scope: <id> may only be a global pick (its catalog scope is global), but it is a pick for this beat; remove it from this beat, or move it to global if it suits the whole movie`. The plan retry and the critic repair it in a new plan; Phase 3 and the re-check refuse it in a saved plan (C3, C4).
- **The per-beat L2 advisory stays removed.** A per-beat style pick is now always the hard L8 on the same beat, so the advisory would report the same pick a second time at a weaker severity. Decision 6's first reason now holds for every style entry, and its second reason (a style entry scoped `beat` or `either`) no longer exists.
- **The hint.** `RECHECK_SCOPE_HINT` said "set the LoRA's scope to either", which bin/lora-catalog now refuses for a style LoRA. Its new text (Section 3) names `either` for a motion or physics LoRA and `--force-story` for a style LoRA picked for a beat.
- **Effect on catalogs (C10).** A catalog.json with `"scope": "beat"` or `"either"` on a style video entry fails to load, so every auto-LoRA run stops with `Error: invalid LoRA catalog <path>: entry <id>: scope must be global for a style LoRA, ...`. The fix is to remove the key or set it to `global` by hand; bin/lora-catalog cannot do it, because it cannot load the catalog. Before this branch merges, only this branch could write such a value.
- R6 is resolved, F2 is withdrawn, and Q3 is answered (a per-beat style pick is the hard L8).

**A2 (should-fix 2): a LoRA the critic moves keeps one copy in either patch order.**
- **The finding (reproduced at `7dd24ac`).** `apply_patches` (`story_engine.py:4750-4768`) checks each lora patch alone, against the state the patches before it left. Moving a LoRA takes two patches: set the new place, clear the old one. In the order that adds the new copy first, the LoRA is briefly in both places, which is a new L6, so that patch is rejected; the clearing patch is then applied, and the LoRA is gone. With the global-scope `film-grain` on beat 2, the patches `[index 0 = [film-grain], index 2 = []]` gave global `[]`, per_beat `{}` and the rejection `would break beat 2: L6 duplicate: 'film-grain' is applied twice on this panel`. With the beat-scope `fast-motion` in global, `[index 2 = [fast-motion], index 0 = []]` did the same.
- **The fix (decided): try a breaking lora patch again after the others.** The lora patches are applied in order, as today. A patch that would break the plan (it adds a message, hard or advisory, that the state before it did not have) is put back and kept for the next pass. Passes repeat until every patch is applied, or a pass applies none; the patches left are then rejected, each with the reason of its last try (`would break <message>`). Panel patches run after them, unchanged.
- **Why this fix.** Both orders give the same plan. Every applied patch is still checked against a real state, so a patch that breaks the plan in every order is still rejected exactly as today (RST31 and LST7 are unchanged). No critic output is rewritten behind the critic's back. The alternatives were rejected:
  - Checking once after all lora patches: one bad patch would reject the good ones with it, or the code would have to search for the largest good subset.
  - Applying clearing patches first: a replacement that drops one LoRA and keeps or adds another is neither clearing nor adding, so the order is not well defined.
  - Running `drop_duplicate_picks` after each patch: it would silently undo a critic patch that puts a beat-scoped LoRA in global and still count it as applied, and it would turn today's L6 rejection into a normalization the critic never asked for.
- **It terminates.** Each pass applies at least one patch or ends the loop. There are at most 8 patches (`MAX_PATCHES`), and the `seen` check allows one patch per index, so there are at most 8 passes and 72 `lora_checks` calls, which are pure and fast (R10).
- `applied` lists the patches in the order they were applied, so a retried patch comes after the ones it waited for. The critic line `N patch(es): A applied, R rejected` counts the same either way. No `lora_notes` is written by a patch.

**A3 (should-fix 3): Phase 2, Phase 3 and the dry run print the L8 hint.**
- **The finding.** `_catalog_checks_error` (`bin/ltx-movie:1993-2007`) prints `Error: plan.json LoRA picks fail the catalog checks (plan: L8 scope: ...); rerun with --force-story or --no-auto-lora` and no hint, unlike `recheck` (LS8), and C3 had no test.
- **The fix.** When `hard[0]` is an L8 (`engine.parse_violation(hard[0])["id"] == "L8"`), the returned text is that line, a newline and `engine.RECHECK_SCOPE_HINT`. It is the same constant the re-check prints, so the wording is identical. Every caller prints the text with `print(error, file=sys.stderr)`, so the user sees two lines. Only `hard[0]` is checked, because the error line shows only `hard[0]`; a hint about an L8 the line does not show would mislead. (The re-check lists every blocking violation, so it checks all of them.)
- **bin/ltx-movie's constraints.** No import is added (no top-level `import re`, L7j), and no literal that L17b, L17d, L17f, L46e, L46f or RST50 count is added or removed. The edit uses `engine.parse_violation` and `engine.RECHECK_SCOPE_HINT` through the existing `engine = _story_engine()`.
- **Tests (LST15).** A saved plan with a global motion pick (default scope `beat`): Phase 3 and the dry run exit 2 with the exact two lines and write no `catalog_loras.json`; with the scope `either`, Phase 3 writes the pick on all three panels. A per-beat style pick gives the beat L8 and the hint. An L5 gives the line without the hint.

**A4 (nit 4): a hand-edited `lora_notes`.**
- `advisory += plan.get("lora_notes", [])` raised `TypeError` for `null` (Phase 3 then reported `plan.json has malformed LoRA picks`) and added one advisory per character for a string. Now only a list counts, and only its strings (LST16).
- **Recorded, unchanged.** `drop_duplicate_picks` removes every copy of the id from a list it changes (a per-beat list under scope `global` or `either`, or global under scope `beat`), so a list that holds the id twice loses both copies. It looks ids up in the whole catalog (`normalize_plan`'s `by_id`), not only in the compatible entries, so an incompatible video entry picked both ways is normalized too. Both are harmless: the kept copy still applies the LoRA to those panels, and an incompatible pick is the hard L1 anyway.

**The pinned files and BASELINE.** Task 5 changes `lora_catalog.py`, `bin/lora-catalog`, `story_engine.py` and `bin/ltx-movie`, all four in `PIPELINE_FILES` of `tests/test_movie_ui_builder.py`. `movie_ui_server.py` is not pinned. It is in `NEW_PY`, so `test_mut25` compiles it with `/usr/bin/python3` and scans it, and the new lines use none of the constructs it forbids. `static/movie-ui/*` is in no pin list. So `test_mut26` keeps failing through Task 5's commit, and Task 4, run after Task 5, moves BASELINE to Task 5's commit, the last code commit. Task 5 Step 27 extends the scratch gate's expected-failures lines to Task 5.

**Fix-round replay.** Every block of Task 5 was replayed by its own Step 1 script, reading this document (`anchors ok: 24 blocks`), on `$S/ls-fix5h`, an rsync copy of the worktree at `7dd24ac` without `.git` and next to a symlinked `agent/`; the result is `$S/ls-fix5a`.
- **Red step.** With only the new test file added, `tests/test_lora_scope_fix.py` gave `5 failed`, for the reasons Task 5 Step 3 gives.
- **Task 5's checks.** The thirteen-file pytest run of Step 28 gave `1 failed, 518 passed, 1 skipped` (the failure is the baseline's `test_rst62_import_sets`; the skip is `tests/test_dialogue.py`'s unrecorded KPI corpus). `tests/test_ltx_movie_offline.py` printed `OK 347/347`, both Pythons compiled every changed Python file, and `node --check` passed on `app.js`.
- **The full suite.** `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors` gave `2 failed, 2744 passed, 8 skipped` on `$S/ls-fix5a` and `2 failed, 2739 passed, 8 skipped` on `$S/ls-fix5h`. Compared test by test, the only difference is the 5 new tests, all passing: no test changed status and none disappeared. The 8 skips are the copy-layout skips of the first "Replay result"; in the worktree the expected counts are those of Task 5 Step 28 and Task 4.
- **Mutations.** Each of the 14 fix-round mutations of Section 5 made at least one of LST1, LST7, LST11 and LST12-LST16 fail, on copies of `$S/ls-fix5a` (`$S/ls-fix5m`).
- **Numstats.** Task 5 Step 28's numstats compare `$S/ls-fix5a` with `7dd24ac`, and V1's compare it (plus Task 4's `2 2`) with `152e6ab`.

### Task 5: fix round (one code commit)

Runs after Task 3 and before Task 4. It implements amendments A1-A4 of "Fix round (review findings)" above; this task holds every edit, so nothing else needs reading.

**Files:** `lora_catalog.py` (pinned), `bin/lora-catalog` (pinned), `story_engine.py` (pinned), `bin/ltx-movie` (pinned), `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js`, `tests/test_lora_scope_catalog.py`, `tests/test_lora_scope.py`, `tests/test_lora_scope_ui.py`, `tests/test_lora_scope_fix.py` (new). `movie_ui_server.py` and `static/movie-ui/*` are not pinned by `test_mut26`.

**Interfaces** (changed; everything else is unchanged):
- `lora_catalog.validate_entry`: a video entry of kind `style` with a scope other than `global` is a `CatalogError` (A1). `lora_catalog.entry_scope`: `"global"` for every video entry of kind `style` (A1).
- `bin/lora-catalog add --kind style --scope beat|either` and `bin/lora-catalog scope ID beat|either` for a style entry exit 2 (A1).
- `movie_ui_server._h_lora_add`: 400 for kind `style` with scope `beat` or `either` (A1). `app.js`: `syncLoraScope()`; a style row's Scope cell is the text `global` (A1).
- `story_engine.RECHECK_SCOPE_HINT` (new text, A1, A3); `apply_patches` retries a lora patch that would break the plan after the others (A2); `lora_checks` adds only the strings of a list `lora_notes` (A4).
- `bin/ltx-movie` `_catalog_checks_error`: an L8 line is followed by `RECHECK_SCOPE_HINT` (A3).

- [ ] **Step 1: Check this task's anchors.** This applies every block of Task 5, read from this document, to a scratch copy of the tree and stops at the first Old that does not occur exactly once:

````bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
git log -1 --format=%s -- . ':(exclude)docs'     # Task 3's subject: movie-ui: the LoRAs tab sets a catalog video LoRA's scope ...
git status --short         # no output
mkdir -p $S/ls-anchors5
cat > $S/ls-anchors5/extract5.py <<'PYEOF'
"""Apply this plan's Task 5 blocks, read from the spec (argv[1]), to a copy of the WS in argv[2];
keep the copy in argv[3] when given. Every Old must occur exactly once when it is applied."""
import os, re, shutil, sys, tempfile
doc, ws = sys.argv[1], sys.argv[2]
lines = open(doc, encoding="utf-8").read().split("\n")
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(tempfile.mkdtemp(prefix="ls-anchors5-"), "ws")
if os.path.exists(out):
    shutil.rmtree(out)
shutil.copytree(ws, out, symlinks=True,
                ignore=shutil.ignore_patterns("generated", "__pycache__", ".pytest_cache"))


def block(i):
    """(text, next line index) of the fenced block that opens at lines[i]."""
    fence = re.match(r"^(`{3,})[a-z]*$", lines[i])
    assert fence, (i + 1, lines[i])
    j = i + 1
    while lines[j] != fence.group(1):
        j += 1
    return "".join(line + "\n" for line in lines[i + 1:j]), j + 1


task, i, n = None, 0, 0
while i < len(lines):
    head = re.match(r"^### Task (\d+):", lines[i])
    if head:
        task = int(head.group(1))
    write = re.match(r"^- \[ \] \*\*Step \d+: Write `([^`]+)`\*\*", lines[i])
    edit = re.match(r"^- \[ \] \*\*Step \d+: Edit `([^`]+)` \(E\d+, .*\)\.\*\* Old:$", lines[i])
    if task == 5 and write:
        i += 1
        while not lines[i].startswith("```"):
            i += 1
        text, i = block(i)
        with open(os.path.join(out, write.group(1)), "w", encoding="utf-8") as f:
            f.write(text)
        n += 1
        continue
    if task == 5 and edit:
        old, i = block(i + 1)
        assert lines[i] == "New:", (i + 1, lines[i])
        new, i = block(i + 1)
        path = os.path.join(out, edit.group(1))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.count(old) != 1:
            sys.exit("ANCHOR FAIL: %s: %d matches for the Old block of line %d"
                     % (edit.group(1), text.count(old), i))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))
        n += 1
        continue
    i += 1
print("anchors ok: %d blocks applied to %s" % (n, out))
PYEOF
python3 -B $S/ls-anchors5/extract5.py docs/superpowers/specs/2026-11-10-lora-scope-design.md . $S/ls-anchors5/ws
````
Expected: Task 3's subject, no status output, and `anchors ok: 24 blocks applied to .../ls-anchors5/ws`. On `ANCHOR FAIL`, stop and report the file and block. Delete `$S/ls-anchors5` afterwards.

- [ ] **Step 2: Write `tests/test_lora_scope_fix.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for the lora-scope fix round
(docs/superpowers/specs/2026-11-10-lora-scope-design.md, "Fix round (review findings)", A1-A4:
LST12-LST16): a style LoRA's scope may only be global, a LoRA the critic moves between global
and a beat keeps one copy in either patch order, Phase 3 and the dry run name the fix for an
L8, and a lora_notes value that is not a list of strings adds no advisory.

Run from the workspace root:
python3 -m pytest -q -p no:cacheprovider tests/test_lora_scope_fix.py

bin/lora-catalog runs as a subprocess with LORA_CATALOG_DIR under tmp_path; story_engine and
bin/ltx-movie are loaded as modules, and bin/ltx-movie's subprocess.run is recorded; the movie
UI server runs against the stub workspace of movie_ui_testutil under a temporary HOME. No test
reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import copy
import importlib.machinery
import json
import os
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import lora_catalog  # noqa: E402
import movie_ui_testutil as mt  # noqa: E402
import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_lora_scope_fix", os.path.join(WS, "story_engine.py")).load_module()
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_for_lora_scope_fix", os.path.join(WS, "bin", "ltx-movie")).load_module()

CLI = os.path.join(WS, "bin", "lora-catalog")
GLOBAL_L8 = ("plan: L8 scope: 'fast-motion' may only be a per-beat pick (its catalog scope is "
             "beat), but it is a global pick; remove it from global and pick it for the beats "
             "that need it")
BEAT_L8 = ("beat 2: L8 scope: 'film-grain' may only be a global pick (its catalog scope is "
           "global), but it is a pick for this beat; remove it from this beat, or move it to "
           "global if it suits the whole movie")
CHECKS_ERROR = ("Error: plan.json LoRA picks fail the catalog checks (%s); rerun with "
                "--force-story or --no-auto-lora\n")


@pytest.fixture
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ui(monkeypatch, tmp_path):
    state = mt.set_home(monkeypatch, tmp_path)
    workspace = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"ws": workspace, "srv": running}
    running.close()
    mt.kill_everything(state)


def _entries(tmp_path):
    """film-grain (style) and fast-motion (motion), with no scope."""
    files = str(tmp_path / "files")
    return [seu.catalog_entry(seu.lora_file(files, "grain"), "film-grain", kind="style"),
            seu.catalog_entry(seu.lora_file(files, "fast"), "fast-motion")]


def _pick(entry_id, strength=0.8):
    return {"id": entry_id, "strength": strength}


def _cli(*argv):
    return subprocess.run([sys.executable, CLI] + list(argv), cwd=WS, capture_output=True,
                          text=True)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _plan(ctx, loras):
    raw = seu.plan_json(ctx.mode, ctx.panels)
    raw["loras"] = dict({"global": [], "per_beat": {}, "stills": []}, **loras)
    return se.normalize_plan(ctx, raw)[0]


def _checks(ctx, plan):
    compatible = dict((e["id"], e) for e in se.compatible_entries(ctx))
    catalog = dict((e["id"], e) for e in ctx.catalog["entries"])
    return se.lora_checks(ctx, plan, compatible, catalog)


# --- LST12 (A1): a style LoRA's scope is only ever global -------------------------------------

def test_lst12_a_style_lora_is_only_ever_global(tmp_path, story_env):
    grain, fast = _entries(tmp_path)
    for scope in ("beat", "either"):
        with pytest.raises(lora_catalog.CatalogError) as exc:
            lora_catalog.validate_entry(dict(grain, scope=scope))
        assert str(exc.value) == ("entry film-grain: scope must be global for a style LoRA, "
                                  "which applies to every panel, got %r" % scope)
        assert lora_catalog.entry_scope(dict(grain, scope=scope)) == "global"
    lora_catalog.validate_entry(dict(grain, scope="global"))
    lora_catalog.validate_entry(dict(grain, target="stills", base_models=[seu.STILLS_MODEL],
                                     scope="beat"))
    path = seu.make_catalog(story_env["catalog"], [dict(grain, scope="either"), fast])
    with pytest.raises(lora_catalog.CatalogError) as exc:
        lora_catalog.load_catalog(path)
    assert str(exc.value) == ("%s: entry film-grain: scope must be global for a style LoRA, "
                              "which applies to every panel, got 'either'" % path)
    seu.make_catalog(story_env["catalog"], [grain, fast])
    before = _read_bytes(path)
    ink = seu.lora_file(str(tmp_path / "files"), "ink")
    base = ["--target", "video", "--base-model", seu.VIDEO_MODEL, "--description", "ink",
            "--use-when", "ink"]
    for scope in ("beat", "either"):
        result = _cli("add", ink, "--id", "ink-style", "--kind", "style", "--scope", scope, *base)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", "Error: --scope %s applies only to motion and physics LoRAs; a style LoRA is "
                   "only ever a global pick\n" % scope)
        result = _cli("scope", "film-grain", scope)
        assert (result.returncode, result.stdout, result.stderr) == (
            2, "", "Error: film-grain is a style LoRA; a style LoRA is only ever a global pick, "
                   "so its scope is global or default\n")
    assert _read_bytes(path) == before
    result = _cli("scope", "film-grain", "global")
    assert (result.returncode, result.stdout) == (0, "film-grain: scope global in %s\n" % path)
    result = _cli("scope", "film-grain", "default")
    assert (result.returncode, result.stdout) == (
        0, "film-grain: scope global (the default for a style LoRA) in %s\n" % path)
    assert _read_bytes(path) == before
    assert _cli("add", ink, "--id", "ink-style", "--kind", "style", "--scope", "global",
                *base).returncode == 0
    added = [e for e in lora_catalog.load_catalog(path)["entries"] if e["id"] == "ink-style"]
    assert added[0]["scope"] == "global"
    ctx = seu.make_ctx(se, seu.make_ws(tmp_path), catalog={
        "schema_version": 1, "entries": [dict(grain, scope="either"), fast]})
    assert se.catalog_groups(ctx, ctx.catalog["entries"]) == [
        se.LORA_GLOBAL_GROUP, se.catalog_line(grain), se.LORA_BEAT_GROUP, se.catalog_line(fast)]
    assert _checks(ctx, _plan(ctx, {"per_beat": {"2": [_pick("film-grain")]}})) == (
        [BEAT_L8], [])


# --- LST13 (A1): the movie UI never sends a per-beat scope for a style LoRA ---------------------

def test_lst13_the_movie_ui_gives_a_style_lora_no_per_beat_scope(ui):
    s, ws = ui["srv"], ui["ws"]
    add = {"ws": ws, "path": "/l/grain.safetensors", "id": "grain", "kind": "style",
           "target": "video", "base_models": ["M1"], "triggers": [], "description": "a look",
           "use_when": "always", "avoid_when": "", "default_strength": 0.8,
           "strength_range": [0.5, 1], "rank": 16, "alpha": None}
    for scope in ("beat", "either"):
        assert mt.api(s, "POST", "/api/loras", body=dict(add, scope=scope))[::2] == (
            400, {"error": "scope must be global or null for a style LoRA"}), scope
    assert mt.stub_calls(ws) == []
    for body, tail in ((dict(add, scope="global"), ["--rank", "16", "--scope", "global"]),
                       (dict(add, scope=None), ["--kind", "style"]),
                       (dict(add, kind="motion", scope="beat"),
                        ["--rank", "16", "--scope", "beat"])):
        status, _h, payload = mt.api(s, "POST", "/api/loras", body=body)
        assert status == 200, payload
        argv = mt.stub_calls(ws)[-1]["argv"]
        assert argv[argv.index(tail[0]):argv.index(tail[0]) + len(tail)] == tail
    assert "--scope" not in mt.stub_calls(ws)[1]["argv"]
    with open(os.path.join(WS, "static", "movie-ui", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert ("Where the story planner may put a motion or physics video LoRA: global applies it to "
            "every panel, beat only to the beats it suits, either lets the planner choose; the "
            "default is beat. A style LoRA is always global, and a stills LoRA has no scope, so "
            "the select is off for both.</span>") in html


# --- LST14 (A2): a LoRA the critic moves keeps one copy, in either patch order -------------------

def test_lst14_a_moved_lora_keeps_one_copy_in_either_patch_order(tmp_path, story_env):
    ctx = seu.make_ctx(se, seu.make_ws(tmp_path),
                       catalog={"schema_version": 1, "entries": _entries(tmp_path)})

    def patch(index, replacement):
        return {"target": "plan", "index": index, "field": "lora", "reason": "L8",
                "replacement": replacement}

    for start, patches, want in (
            ({"per_beat": {"2": [_pick("film-grain")]}},
             [patch(0, [_pick("film-grain")]), patch(2, [])], ([_pick("film-grain")], {})),
            ({"global": [_pick("fast-motion")]},
             [patch(2, [_pick("fast-motion")]), patch(0, [])],
             ([], {"2": [_pick("fast-motion")]}))):
        for order in (patches, patches[::-1]):
            state = {"plan": _plan(ctx, start), "parts": []}
            kept = copy.deepcopy(state)
            new, applied, rejected = se.apply_patches(ctx, state, order, lora_allowed=True)
            loras = new["plan"]["loras"]
            assert (loras["global"], loras["per_beat"]) == want, order
            assert sorted(p["index"] for p in applied) == [0, 2] and rejected == [], order
            assert _checks(ctx, new["plan"]) == ([], []) and "lora_notes" not in new["plan"]
            assert state == kept
    state = {"plan": _plan(ctx, {}), "parts": []}
    new, applied, rejected = se.apply_patches(
        ctx, state, [patch(0, [_pick("fast-motion")]), patch(3, [])], lora_allowed=True)
    assert [p["index"] for p in applied] == [3]
    assert [r["reason"] for r in rejected] == ["would break " + GLOBAL_L8]
    assert new["plan"]["loras"]["global"] == []


# --- LST15 (A3): Phase 3 and the dry run name the fix for an L8 ---------------------------------

class _Done(object):
    returncode = 0


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    for resolve in (ltx_movie._resolve_shots, ltx_movie._resolve_casting,
                    ltx_movie._resolve_global_loras, ltx_movie._resolve_story_engine):
        assert resolve(args) == 0
    return args


def _write_plan(story_dir, loras, **extra):
    plan = {"schema": "ltx-movie.plan.v1", "mode": "chained", "panels": 3, "title": "T",
            "logline": "x", "cast": [], "locations": [], "props": [], "beats": [],
            "loras": dict({"global": [], "per_beat": {}, "stills": []}, **loras)}
    with open(os.path.join(story_dir, "plan.json"), "w") as f:
        json.dump(dict(plan, **extra), f)


def _story(tmp_path, monkeypatch, story_env, entries, loras, **extra):
    """A temp workspace (ltx_movie.WS) whose 3-panel chained story c1 has these picks; returns
    its story directory. bin/ltx-movie's subprocess.run is recorded, never run."""
    ws = seu.make_ws(tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    monkeypatch.setattr(ltx_movie.subprocess, "run", lambda cmd, **kw: _Done())
    seu.make_catalog(story_env["catalog"], entries)
    story_dir = os.path.join(ws, "generated", "stories", "c1")
    os.makedirs(story_dir)
    _write_plan(story_dir, loras, **extra)
    with open(os.path.join(story_dir, "story.md"), "w") as f:
        f.write("# T\n\n## Panel 1 — A\nImage: The woman in grey waits.\nMotion: x\n"
                "Narration: y\n")
    return story_dir


P3 = ["n", "--story-id", "c1", "--panels", "3", "--no-review"]


def test_lst15_phase_3_and_the_dry_run_name_the_l8_fix(tmp_path, monkeypatch, story_env, capsys):
    grain, fast = _entries(tmp_path)
    story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast],
                       {"global": [_pick("fast-motion", 0.7)]})
    path = os.path.join(story_dir, "catalog_loras.json")
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"
    assert ltx_movie.main(P3 + ["--dry-run"]) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % GLOBAL_L8 + se.RECHECK_SCOPE_HINT + "\n"
    assert not os.path.exists(path)
    seu.make_catalog(story_env["catalog"], [grain, dict(fast, scope="either")])
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
    item = {"id": "fast-motion", "kind": "motion", "path": fast["path"],
            "sha256": fast["sha256"], "strength": 0.7, "triggers": []}
    with open(path) as f:
        assert json.load(f)["panels"] == [[item], [item], [item]]
    os.remove(path)
    _write_plan(story_dir, {"per_beat": {"2": [_pick("film-grain")]}})
    capsys.readouterr()
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % BEAT_L8 + se.RECHECK_SCOPE_HINT + "\n"
    _write_plan(story_dir, {"global": [_pick("film-grain", 99)]})
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 2
    assert capsys.readouterr().err == CHECKS_ERROR % (
        "plan: L5 strength: 'film-grain' strength 99.0 is outside (0, 2], which the renderer "
        "refuses")
    assert not os.path.exists(path)


# --- LST16 (A4): lora_notes that are not a list of strings add no advisory -----------------------

def test_lst16_lora_notes_that_are_not_a_list_of_strings_add_no_advisory(tmp_path, monkeypatch,
                                                                          story_env):
    grain, fast = _entries(tmp_path)
    story_dir = _story(tmp_path, monkeypatch, story_env, [grain, fast],
                       {"global": [_pick("film-grain")]}, lora_notes=None)
    assert ltx_movie.phase3_manifest(_movie_args(*P3)) == 0
    assert os.path.exists(os.path.join(story_dir, "catalog_loras.json"))
    ctx = seu.make_ctx(se, ltx_movie.WS, catalog={"schema_version": 1, "entries": [grain, fast]})
    plan = _plan(ctx, {"global": [_pick("film-grain")]})
    note = ("plan: L6 duplicate: 'film-grain' was picked both globally and for beat(s) 2; the "
            "pipeline kept the global pick and dropped the per-beat copies")
    for notes, advisory in (("a note", []), (None, []), (3, []), ({"a": "b"}, []),
                            ([1, None, note], [note]), ([note], [note])):
        assert _checks(ctx, dict(plan, lora_notes=notes)) == ([], advisory), notes
````

- [ ] **Step 3: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/ls-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_fix.py 2>&1 | tail -1
```
Expected: `5 failed` (the summary line may also count warnings). LST12 fails with `DID NOT RAISE` (validate_entry accepts a style scope beat); LST13 on `(200, ...) == (400, ...)`; LST14 on the first case's picks, `([], {}) == ([{'id': 'film-grain', 'strength': 0.8}], {})`; LST15 on the error text (no hint line yet); LST16 on `2 == 0` (a `lora_notes` of `null` makes `lora_checks` raise, and Phase 3 reports malformed picks).

- [ ] **Step 4: Edit `lora_catalog.py` (E58, the scope comment names the style rule).** Old:
```python
# picks) or either. An entry without one gets the default for its kind. Only video LoRAs have a
# scope; a stills entry's scope is accepted and ignored.
```
New:
```python
# picks) or either. An entry without one gets the default for its kind. Only video LoRAs have a
# scope; a stills entry's scope is accepted and ignored. A style video entry's scope may only be
# global (fix round A1): Phase 3 applies a style LoRA to every panel, never to one beat.
```

- [ ] **Step 5: Edit `lora_catalog.py` (E59, validate_entry refuses a per-beat style scope).** Old:
```python
    if "scope" in entry and entry["scope"] not in SCOPES:
        fail("scope", "must be one of %s, got %r" % (", ".join(SCOPES), entry["scope"]))
```
New:
```python
    if "scope" in entry and entry["scope"] not in SCOPES:
        fail("scope", "must be one of %s, got %r" % (", ".join(SCOPES), entry["scope"]))
    if (entry["target"] == "video" and entry["kind"] == "style"
            and entry.get("scope", "global") != "global"):
        fail("scope", "must be global for a style LoRA, which applies to every panel, got %r"
             % (entry["scope"],))
```

- [ ] **Step 6: Edit `lora_catalog.py` (E60, entry_scope is global for every style entry).** Old:
```python
    """Where the story planner may place a catalog entry (LoRA scope spec LS2): its scope, else
    DEFAULT_SCOPES of its kind; None for a stills LoRA and for a library character."""
    if entry.get("target") != "video" or entry.get("kind") not in DEFAULT_SCOPES:
        return None
    return entry.get("scope") or DEFAULT_SCOPES[entry["kind"]]
```
New:
```python
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

- [ ] **Step 7: Edit `bin/lora-catalog` (E61, the docstring names the style rule).** Old:
```python
bin/ltx-movie's story planner may pick catalog entries for the whole movie or for one beat, as
each video entry's scope allows (global, beat or either; without a scope, style LoRAs are global
and motion and physics LoRAs are per-beat: LoRA scope spec LS1); trained library characters are
listed and verified here but are cast only with bin/ltx-movie --character. `add` runs
```
New:
```python
bin/ltx-movie's story planner may pick catalog entries for the whole movie or for one beat, as
each video entry's scope allows (a motion or physics LoRA's scope is global, beat or either, by
default beat; a style LoRA's scope is always global: LoRA scope spec LS1 and its fix round A1);
trained library characters are listed and verified here but are cast only with
bin/ltx-movie --character. `add` runs
```

- [ ] **Step 8: Edit `bin/lora-catalog` (E62, the help of add --scope).** Old:
```python
                     help="where the story planner may place this video LoRA: global (every "
                          "panel), beat (one beat) or either; default: global for style, beat "
                          "for motion and physics")
```
New:
```python
                     help="where the story planner may place this motion or physics video "
                          "LoRA: global (every panel), beat (one beat) or either; default: "
                          "beat. A style LoRA is always global")
```

- [ ] **Step 9: Edit `bin/lora-catalog` (E63, the help of the scope subcommand).** Old:
```python
    scope = sub.add_parser("scope", help="set where the story planner may place a catalog video "
                                         "LoRA (default: the default for its kind)")
```
New:
```python
    scope = sub.add_parser("scope", help="set where the story planner may place a catalog video "
                                         "LoRA (default: the default for its kind; a style LoRA "
                                         "may only be global)")
```

- [ ] **Step 10: Edit `bin/lora-catalog` (E64, add refuses a per-beat style scope).** Old:
```python
        return _error("--scope applies only to video LoRAs; a stills LoRA is only ever the "
                      "stills pick")
```
New:
```python
        return _error("--scope applies only to video LoRAs; a stills LoRA is only ever the "
                      "stills pick")
    if args.kind == "style" and args.scope in ("beat", "either"):
        return _error("--scope %s applies only to motion and physics LoRAs; a style LoRA is only "
                      "ever a global pick" % args.scope)
```

- [ ] **Step 11: Edit `bin/lora-catalog` (E65, scope refuses a per-beat style scope).** Old:
```python
            return _error("%s is a stills LoRA; scope applies only to video LoRAs" % entry["id"])
```
New:
```python
            return _error("%s is a stills LoRA; scope applies only to video LoRAs" % entry["id"])
        if entry["kind"] == "style" and args.scope in ("beat", "either"):
            return _error("%s is a style LoRA; a style LoRA is only ever a global pick, so its "
                          "scope is global or default" % entry["id"])
```

- [ ] **Step 12: Edit `story_engine.py` (E66, the hint names the fix that is left for a style LoRA).** Old:
```python
RECHECK_SCOPE_HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: "
                      "set the LoRA's scope to either with bin/lora-catalog scope ID either (or "
                      "in the movie UI's LoRA catalog), or pass --force-story to regenerate.")
```
New:
```python
# Fix round A1, A3: a style LoRA's scope is always global, so only a motion or physics LoRA's
# scope can make its pick allowed; bin/ltx-movie's Phase 2 and 3 errors print this hint too.
RECHECK_SCOPE_HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: "
                      "give a motion or physics LoRA the scope either with bin/lora-catalog "
                      "scope ID either (or the Scope select of its row in the movie UI's LoRAs "
                      "tab), or pass --force-story to regenerate; a style LoRA is only ever a "
                      "global pick, so a style LoRA picked for a beat needs --force-story.")
```

- [ ] **Step 13: Edit `story_engine.py` (E67, lora_checks adds only the strings of a list lora_notes).** Old:
```python
    advisory += plan.get("lora_notes", [])
```
New:
```python
    # Fix round A4: a hand-edited plan.json's lora_notes may be anything; only its strings count.
    notes = plan.get("lora_notes")
    advisory += [m for m in notes if isinstance(m, str)] if isinstance(notes, list) else []
```

- [ ] **Step 14: Edit `story_engine.py` (E68, apply_patches tries a breaking lora patch again after the others).** Old:
```python
    for patch in accepted:
        if patch["target"] != "plan":
            continue
        index = patch["index"]
        before = sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
        saved = copy.deepcopy(plan["loras"])
        if index == 0:
            plan["loras"]["global"] = patch["replacement"]
        elif patch["replacement"]:
            plan["loras"]["per_beat"][str(index)] = patch["replacement"]
        else:
            plan["loras"]["per_beat"].pop(str(index), None)
        broken = [h for h in sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
                  if h not in before]
        if broken:
            plan["loras"] = saved
            rejected.append({"patch": patch, "reason": "would break " + broken[0]})
            continue
        applied.append(patch)
```
New:
```python
    # LoRA scope fix round A2: moving a LoRA between global and a beat takes two patches, and the
    # order that adds the new copy first breaks L6 until the old copy goes. So a lora patch that
    # would break the plan is tried again after the others; the ones still breaking it after a
    # pass that applies none are rejected, each with the reason of its last try.
    pending = [patch for patch in accepted if patch["target"] == "plan"]
    while pending:
        failed = []
        for patch in pending:
            index = patch["index"]
            before = sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
            saved = copy.deepcopy(plan["loras"])
            if index == 0:
                plan["loras"]["global"] = patch["replacement"]
            elif patch["replacement"]:
                plan["loras"]["per_beat"][str(index)] = patch["replacement"]
            else:
                plan["loras"]["per_beat"].pop(str(index), None)
            broken = [h for h in sum(lora_checks(ctx, plan, compatible_by_id, catalog_by_id), [])
                      if h not in before]
            if broken:
                plan["loras"] = saved
                failed.append({"patch": patch, "reason": "would break " + broken[0]})
                continue
            applied.append(patch)
        if len(failed) == len(pending):
            rejected += failed
            break
        pending = [item["patch"] for item in failed]
```

- [ ] **Step 15: Edit `bin/ltx-movie` (E69, the catalog-checks error of an L8 ends with the hint).** Old:
```python
    if hard:
        return ("Error: plan.json LoRA picks fail the catalog checks (%s); rerun with "
                "--force-story or --no-auto-lora" % hard[0])
```
New:
```python
    if hard:
        # LoRA scope fix round A3: an L8 line is followed by the re-check's hint, on a line of its
        # own.
        hint = ("\n" + engine.RECHECK_SCOPE_HINT
                if engine.parse_violation(hard[0])["id"] == "L8" else "")
        return ("Error: plan.json LoRA picks fail the catalog checks (%s); rerun with "
                "--force-story or --no-auto-lora%s" % (hard[0], hint))
```

- [ ] **Step 16: Edit `movie_ui_server.py` (E70, _h_lora_add refuses a per-beat style scope).** Old:
```python
        raise ApiError(400, "scope must be global, beat, either or null")
```
New:
```python
        raise ApiError(400, "scope must be global, beat, either or null")
    if kind == "style" and scope in ("beat", "either"):
        raise ApiError(400, "scope must be global or null for a style LoRA")
```

- [ ] **Step 17: Edit `static/movie-ui/index.html` (E71, the note under the Scope field).** Old:
```html
    <label>Scope <select id="l-scope"><option value="">default for the kind</option><option>global</option><option>beat</option><option>either</option></select></label> <span class="muted">Where the story planner may put a video LoRA: global applies it to every panel, beat only to the beats it suits, either lets the planner choose. The default is global for style and beat for motion and physics. A stills LoRA has no scope.</span>
```
New:
```html
    <label>Scope <select id="l-scope"><option value="">default for the kind</option><option>global</option><option>beat</option><option>either</option></select></label> <span class="muted">Where the story planner may put a motion or physics video LoRA: global applies it to every panel, beat only to the beats it suits, either lets the planner choose; the default is beat. A style LoRA is always global, and a stills LoRA has no scope, so the select is off for both.</span>
```

- [ ] **Step 18: Edit `static/movie-ui/app.js` (E72, a style row shows global and no select).** Old:
```javascript
  // LoRA scope spec LS7: a video entry's scope is chosen in its row; "default" clears it.
  function scopeCell(e) {
    if (e.target !== "video") { return el("td", {text: "-"}); }
```
New:
```javascript
  // LoRA scope spec LS7: a video entry's scope is chosen in its row; "default" clears it. A style
  // LoRA's scope is always global (fix round A1), so its row has no select.
  function scopeCell(e) {
    if (e.target !== "video") { return el("td", {text: "-"}); }
    if (e.kind === "style") { return el("td", {text: "global"}); }
```

- [ ] **Step 19: Edit `static/movie-ui/app.js` (E73, syncLoraScope before splitList).** Old:
```javascript
  function splitList(selector) {
```
New:
```javascript
  // Fix round A1: a stills LoRA has no scope and a style LoRA's is always global, so the add
  // form's Scope select is off for both.
  function syncLoraScope() {
    $("#l-scope").disabled = $("#l-target").value !== "video" || $("#l-kind").value === "style";
  }

  function splitList(selector) {
```

- [ ] **Step 20: Edit `static/movie-ui/app.js` (E74, the target and the kind both set the Scope select).** Old:
```javascript
    $("#l-target").addEventListener("change", function () { $("#l-scope").disabled = $("#l-target").value !== "video"; });
```
New:
```javascript
    $("#l-target").addEventListener("change", syncLoraScope);
    $("#l-kind").addEventListener("change", syncLoraScope);
    syncLoraScope();
```

- [ ] **Step 21: Edit `static/movie-ui/app.js` (E75, the add body sends no scope from a disabled select).** Old:
```javascript
        scope: $("#l-target").value === "video" && $("#l-scope").value ? $("#l-scope").value : null,
```
New:
```javascript
        scope: !$("#l-scope").disabled && $("#l-scope").value ? $("#l-scope").value : null,
```

- [ ] **Step 22: Edit `tests/test_lora_scope_catalog.py` (E76, LST1: beat and either are valid on a motion and a stills entry, not on a style entry).** Old:
```python
        for entry in (grain, fast, ink):
            lora_catalog.validate_entry(dict(entry, scope=scope))
```
New:
```python
        for entry in ((grain, fast, ink) if scope == "global" else (fast, ink)):
            lora_catalog.validate_entry(dict(entry, scope=scope))
```

- [ ] **Step 23: Edit `tests/test_lora_scope.py` (E77, the new hint).** Old:
```python
HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: set the LoRA's "
        "scope to either with bin/lora-catalog scope ID either (or in the movie UI's LoRA "
        "catalog), or pass --force-story to regenerate.")
```
New:
```python
HINT = ("An L8 violation is a pick placed where its catalog scope does not allow: give a motion "
        "or physics LoRA the scope either with bin/lora-catalog scope ID either (or the Scope "
        "select of its row in the movie UI's LoRAs tab), or pass --force-story to regenerate; a "
        "style LoRA is only ever a global pick, so a style LoRA picked for a beat needs "
        "--force-story.")
```

- [ ] **Step 24: Edit `tests/test_lora_scope.py` (E78, LST5: either and global scopes on the motion entry only).** Old:
```python
    either = _ctx(ws, tmp_path, entries=_entries(tmp_path, film="either", fast="either"))
    assert _checks(either, {"global": [_pick("fast-motion")],
                            "per_beat": {"2": [_pick("film-grain")]}}) == ([], [])
    swapped = _ctx(ws, tmp_path, entries=_entries(tmp_path, film="beat", fast="global"))
    assert _checks(swapped, {"global": [_pick("fast-motion")],
                             "per_beat": {"2": [_pick("film-grain")]}}) == ([], [])
    assert _checks(swapped, {"global": [_pick("film-grain")]})[0] == [
        GLOBAL_L8.replace("fast-motion", "film-grain")]
```
New:
```python
    either = _ctx(ws, tmp_path, entries=_entries(tmp_path, fast="either"))
    assert _checks(either, {"global": [_pick("fast-motion")]}) == ([], [])
    assert _checks(either, {"per_beat": {"2": [_pick("fast-motion")]}}) == ([], [])
    swapped = _ctx(ws, tmp_path, entries=_entries(tmp_path, fast="global"))
    assert _checks(swapped, {"global": [_pick("fast-motion")]}) == ([], [])
    assert _checks(swapped, {"per_beat": {"2": [_pick("fast-motion")]}})[0] == [
        (BEAT_L8 % 2).replace("film-grain", "fast-motion")]
```

- [ ] **Step 25: Edit `tests/test_lora_scope.py` (E79, LST6: a style entry's scope is none or global).** Old:
```python
    for scope in (None, "either"):
        ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, film=scope, fast="either"))
```
New:
```python
    for scope in (None, "global"):
        ctx = _ctx(ws, tmp_path, entries=_entries(tmp_path, film=scope, fast="either"))
```

- [ ] **Step 26: Edit `tests/test_lora_scope_ui.py` (E80, LST11: the JavaScript of the style rule).** Old:
```python
    for text in ('scope: $("#l-target").value === "video" && $("#l-scope").value ? '
                 '$("#l-scope").value : null,',
                 'api("POST", "/api/loras/scope", {ws: S.ws, id: e.id, scope: select.value})',
                 'select.value = e.scope || "default";',
                 'scopeCell(e), el("td", {text: strength}),',
                 '$("#l-scope").disabled = $("#l-target").value !== "video";'):
```
New:
```python
    for text in ('scope: !$("#l-scope").disabled && $("#l-scope").value ? $("#l-scope").value : '
                 'null,',
                 'api("POST", "/api/loras/scope", {ws: S.ws, id: e.id, scope: select.value})',
                 'select.value = e.scope || "default";',
                 'scopeCell(e), el("td", {text: strength}),',
                 '$("#l-scope").disabled = $("#l-target").value !== "video" || '
                 '$("#l-kind").value === "style";',
                 'if (e.kind === "style") { return el("td", {text: "global"}); }',
                 '$("#l-target").addEventListener("change", syncLoraScope);',
                 '$("#l-kind").addEventListener("change", syncLoraScope);',
                 '\n    syncLoraScope();\n'):
```

- [ ] **Step 27: Update the scratch gate's expected failures (never staged).** `test_mut26` now stays lost through Task 5, and the flaky lines cover Task 5:
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/ls-baseline
sed -i '' -e 's#^1 3 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged pinned files change in Tasks 1 and 2; Task 4 moves BASELINE$#1 5 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged pinned files change in Tasks 1, 2 and 5; Task 4 (after Task 5) moves BASELINE#' -e 's#^1 4 tests/test_fleet_tracing.py::#1 5 tests/test_fleet_tracing.py::#' $D/expected-failures.txt
grep -c '^1 5 ' $D/expected-failures.txt          # 4
grep -c '^1 [34] ' $D/expected-failures.txt       # 0
```

- [ ] **Step 28: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/ls-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/ls-baseline/pyc $py -m py_compile lora_catalog.py bin/lora-catalog story_engine.py bin/ltx-movie movie_ui_server.py tests/test_lora_scope_catalog.py tests/test_lora_scope.py tests/test_lora_scope_ui.py tests/test_lora_scope_fix.py && echo "$py compiled"; done
if command -v node >/dev/null; then node --check static/movie-ui/app.js && echo "node ok"; fi
git diff --numstat -- lora_catalog.py bin/lora-catalog story_engine.py bin/ltx-movie movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_lora_scope_catalog.py tests/test_lora_scope.py tests/test_lora_scope_ui.py
wc -l tests/test_lora_scope_fix.py                         # 297
grep -c "^import re$" bin/ltx-movie                         # 0
python3 -B -m pytest -q -p no:cacheprovider tests/test_lora_scope_fix.py tests/test_lora_scope_catalog.py tests/test_lora_scope.py tests/test_lora_scope_ui.py tests/test_lora_catalog.py tests/test_story_engine.py tests/test_dialogue.py tests/test_per_beat_json.py tests/test_plan_budget.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seedgen.py tests/test_movie_ui_seedfolder.py 2>&1 | tail -1
python3 -B tests/test_ltx_movie_offline.py 2>&1 | tail -1      # OK 347/347
zsh $S/ls-baseline/gate-run.sh 5
git add lora_catalog.py bin/lora-catalog story_engine.py bin/ltx-movie movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_lora_scope_catalog.py tests/test_lora_scope.py tests/test_lora_scope_ui.py tests/test_lora_scope_fix.py
git diff --cached --name-only    # exactly the eleven paths above, each under qwen-agent-workspace/
git commit -m "lora-scope fix round: a style LoRA's scope may only be global, a LoRA the critic moves between global and a beat keeps one copy in either patch order, Phase 3 and the dry run print the L8 hint, and a hand-edited lora_notes is guarded (lora-scope A1-A4)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`, and `node ok` is printed when node is installed.
- The numstat lines are `15 7 bin/lora-catalog`, `5 1 bin/ltx-movie`, `11 2 lora_catalog.py`, `2 0 movie_ui_server.py`, `13 3 static/movie-ui/app.js`, `1 1 static/movie-ui/index.html`, `37 22 story_engine.py`, `1 1 tests/test_lora_scope_catalog.py`, `13 12 tests/test_lora_scope.py` and `8 3 tests/test_lora_scope_ui.py`.
- The thirteen-file pytest line is `1 failed, 518 passed, 1 skipped, ... warnings in ...s`. The one failure is the baseline's `test_rst62_import_sets`.
- The gate prints the summary `3 failed, P0 + 15 passed, 2 skipped` (2749 passed when P0 is 2734) and the gate line `lost 1 (listed 1, unexpected 0); new tests 16, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.
- Then run Task 4.
