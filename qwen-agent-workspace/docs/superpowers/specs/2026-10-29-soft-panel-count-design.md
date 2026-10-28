# Soft panel count: `--panels` is a target, and the planner may add up to 2 panels

Date: 2026-10-29 (design-review fixes applied the same day)

Status: design spec. The user approved the design brief (Section 0.0). Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 8.2 lists them for confirmation. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `6f16063`. The code at `6f16063` is byte-identical to `3970e96`: `6f16063` only adds the shot prompt format spec. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `6f16063`.

**Order of work.** This spec is implemented **after** the shot prompt format spec ([SF]), which is implemented first. [SF] moves lines, so the implementer locates each cited place by its symbol name. Names that [SF] introduces are cited by their [SF] requirement:

| [SF] requirement | Names |
|---|---|
| SF1 | `max_static` |
| SF2 | `CAMERA_RULE`, `@@MAX_STATIC@@` |
| SF3 | `SPEAKING_BEAT_SENTENCE` |
| SF5 | `cap_static_cameras`, `P18_NOTE` |
| SF10 | `EXIT_RE` |
| Amendment SF-A1 | `P19_NOTE`, `narrative_exit_after_last_line`, `exit_left_out_notes` |

Specs this one builds on, cited by tag:
- **[SF]** `docs/superpowers/specs/2026-10-28-shot-prompt-format-design.md` (committed `6f16063`, not yet implemented). This spec uses its SF1-SF3, SF5, SF-A1, SFT1, SFT24, SFT25 and K8.
- **[NF]** `docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`. QL5 is the spoken-lines pre-flight (`spoken_lines_problem`, `panels_needed`).
- **[PCP]** `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md`. PC6 says a pinned character with no line needs a beat with no speaker (`LINES_PINNED_SENTENCE`).
- **[SA]** `docs/superpowers/specs/2026-10-28-speaker-attribution-design.md`. `line_speakers`; P17 keeps the narrative's speaker for each line.

---

## 0. Purpose and scope

### 0.0 The approved design (binding summary)

1. **`--panels N` is a target, not a fixed count.** The story planner chooses the actual count to fit the content, within `[N, N+2]`: never fewer than N, at most 2 more. The count is soft in the same way a word range is soft. The cases that call for more panels are:
   - an exit after the last line gets its own silent panel;
   - lines that don't fit get more panels;
   - one speaker per panel.
2. **After planning, the effective count is the plan's beat count, and everything downstream uses it.** That covers:
   - the panel loops;
   - the budgets and timeouts;
   - the stills;
   - the manifest;
   - the movie UI display and estimates;
   - `story_checks`;
   - recheck.
3. **The user is told, with the reason, whenever the count differs from the target.**
4. **This spec stays consistent with [SF].**
   - Amendment SF-A1 (P19) is revisited in SPC12.
   - The `story_engine.py:755-760` hard error becomes automatic inside the +2 cap and stays hard beyond it (SPC3).

### 0.1 Problem (verified at `6f16063`)

- **E1. The planner must return exactly N beats.**
  - The prompt says so: `PLAN_PROMPT_TEMPLATE` `story_engine.py:306-307`.
  - P1 is hard (`:1544-1545`) and fatal (`:3760`) when `len(beats) != ctx.panels`.
- **E2. Content that needs one more panel is lost.** Under [SF], a speaking beat never shows its speaker leave (SF3, SF10). So the hockey skate-away is left out at `--panels 2` and at `--panels 1` ([SF] Section 0.5, SF-A1).
- **E3. A narrative whose lines need N+1 panels exits 2 before any call** (`:754-760`).
- **E4. The pre-flight ignores speakers.** `panels_needed` (`:719-728`) packs consecutive lines by words only. Lines the narrative gives to different speakers can never share a beat (one `speaker` per beat; P17, `:1686-1699`), so the pre-flight can under-count.
- **E5. Two prompt sentences assume a fixed count.**
  - `LINES_RULE` (`:376-377`): "Give each line its own beat whenever there are at least as many beats as lines."
  - `LINES_PINNED_SENTENCE` (`:380-382`): "... even when two consecutive lines must then share a beat."
- **E6. Every consumer of the count is fixed.** Section 0.3 lists them.

### 0.2 Approach in one paragraph

- **What the planner is told.** The planner gets a range `[lo, hi]`:
  - `lo` is `max(N, lines_needed)`, where `lines_needed` is the fewest panels that speak the lines with one speaker per panel;
  - `hi` is `N + PANELS_EXTRA`, where `PANELS_EXTRA = 2`;
  - it is told to use `lo` beats unless the narrative needs more.
- **P1** accepts any count in `[lo, hi]`.
- **The effective count.** When a plan is accepted, the engine swaps its `StoryContext` for one whose `panels` is the plan's beat count and whose new `panels_target` is N. Every downstream use of `ctx.panels` then sees the effective count with no per-site edit.
- **What `plan.json` records.**
  - The effective count, in the existing `panels` field.
  - The target, in a new `panels_target` field.
- **How `bin/ltx-movie` adopts the count.** It adopts `plan.json`'s `panels` into `args.panels`:
  - after Phase 1;
  - and before Phase 1, when it will re-check an existing story whose `story.md` has that many panels.
- **How the user is told.**
  - A new advisory, P20 "panel count", gives the reason.
  - `bin/ltx-movie` prints a `note:` line with that reason on every run, including the re-check and render path.

### 0.3 Grounding: every use of the panel count (verified at `6f16063`)

**`story_engine.py`**

| Line | Use | After this spec |
|---|---|---|
| `:82-86` | `StoryContext` fields, `defaults=(True, None)` | gains `panels_target` (SPC1) |
| `:130-139` | `plan_max_tokens(n)`, `plan_timeout(n)`, `wall_clock_cap(n)` | unchanged functions; callers pass the right count (SPC9) |
| `:306-307` | template `EXACTLY @@PANELS@@ ... index runs from 1 to @@PANELS@@` | range text (SPC4) |
| `:309`, `:788-794`, `:958` | `@@ARC_RULE@@` = `_arc_rule(ctx.panels)` | `_plan_arc_rule(lo, hi)` (SPC5) |
| `:371-377` | `LINES_RULE`, "at least as many beats as lines" (`:376-377`) | reworded to the target (SPC2) |
| `:380-382` | `LINES_PINNED_SENTENCE`, "even when two consecutive lines must then share a beat" | reworded to the range (SPC2) |
| `:656-689` | `line_speakers(narrative, cast)` | used for `lines_needed` (SPC1) |
| `:719-728` | `panels_needed` | unchanged; summed over speaker runs (SPC1) |
| `:731-761` | `spoken_lines_problem`; the count error at `:754-760` | `lines_needed`, error only beyond N+2 (SPC3) |
| `:940-945` | declared members as `{"id": "c%d", "phrase", "cast_name"}` for `line_speakers` | factored into `declared_speakers` (SPC1) |
| `:976` | scalar `@@PANELS@@` = `str(ctx.panels)` | removed; `@@MIN_BEATS@@` added (SPC4) |
| `:1086` | `normalize_plan` `"panels": ctx.panels` | `len(beats)`, plus `panels_target` (SPC6) |
| `:1542-1549` | `plan_checks` `n = ctx.panels`, P1 | range P1, `n = len(beats)` (SPC7) |
| `:1620-1621`, `:1629`, `:1650` | P5 required arcs, P6 `n >= 2`, P10 `k <= n` | `n = len(beats)` (SPC7) |
| `:1747`, `:1789-1791` | `lora_checks` `n = ctx.panels`, per_beat key range | `n = len(plan["beats"])` (SPC7) |
| `:2734-2736` | `panel_checks` → `shots_violations(..., ctx.panels, ...)` | effective via the swapped ctx |
| `:2850` | writer `@@PANELS@@` ("panel @@K@@ of @@PANELS@@", `:1902`) | effective via the swapped ctx (unchanged code) |
| `:3069` | `patch_ranges` `n = ctx.panels` | effective via the swapped ctx |
| `:3458-3465` | `_checks_doc` `"panels": ctx.panels` | plus `panels_target` (SPC8) |
| `:3475`, `:3478`, `:3484` | `_Run.__init__` cap, `panel_calls`, run.json `panels` | SPC9 |
| `:3545-3546` | plan call `plan_max_tokens(ctx.panels)`, `plan_timeout(ctx.panels)` | `most_panels(ctx)` (SPC9) |
| `:3575` | `"panel %d/%d: call %d"` | effective via the swapped ctx |
| `:3674` | code-only critic loop `range(1, ctx.panels + 1)` | effective via the swapped ctx |
| `:3771-3775` | plan accepted → `assign_missing_lines` → `parts` and the round-0 loop | ctx swap inserted (SPC9) |
| `:3873-3891` | `load_plan`: `plan.get("panels") != ctx.panels` (`:3881`) | range acceptance (SPC10) |
| `:3928-3942` | `plan_free_report` builds a ctx with no target | unchanged (`panels_target` defaults to None) |
| `:3969-4058` | `recheck`: `legacy_validate(story_md, ctx.panels, ...)` (`:3981`), `shots_violations(..., ctx.panels, ...)` (`:3999`, `:4045`) | adopts the plan's count (SPC10) |

**`bin/ltx-movie` (2540 lines)**

| Line | Use | After this spec |
|---|---|---|
| `:307-309` | `--panels` help | gains the target sentence (SPC13 h) |
| `:490-519` | `_resolve_length` sets `args.panels` | unchanged; the result is the target |
| `:522-527` | `_target_seconds` = `args.panels * frames / fps`, used for the manifest `--target-seconds` | effective after adoption |
| `:701-718` | `_load_story_panels(story_md)` (`[]` when unreadable) | used by `_plan_panels` (SPC13 b) |
| `:1073-1118` | `_resolve_shots`: `--redo` range `1 <= n <= args.panels` (`:1109-1113`) | effective; the resolver runs first (SPC13 c) |
| `:1420-1450` | `_story_context` `panels=args.panels` (`:1440`) | plus `panels_target` (SPC13 d) |
| `:1459-1480` | `_catalog_plan`: `plan.get("panels") != args.panels` (`:1472`) | unchanged; holds after adoption |
| `:1488-1530` | `_catalog_pick`: a catalog file whose size differs from `entry["bytes"]` is an error (`:1517-1524`) | unchanged; tests must use real-size fixtures (SPT16) |
| `:1534-1570` | `_catalog_panel_loras`: `range(1, args.panels + 1)` (`:1565`) | effective after adoption |
| `:1603-1645` | `_phase1_robust`; `story_prompt.txt` written from `build_story_prompt(..., args.panels, ...)` (`:1618-1625`) | rewrites `story_prompt.txt` with the effective count, adopts, and prints the note (SPC13 f, g) |
| `:2003-2009` | `_shots_image_flags` 1..`args.panels` | effective after adoption |
| `:2201-2232` | `_print_robust_phase1`: `plan_max_tokens(args.panels)`, `plan_timeout(args.panels)` (`:2225-2228`) | `most_panels(ctx)` and a `Panel count:` line (SPC13 e) |
| `:2443`, `:2473`, `:2485`, `:2489` | `main`: `_resolve_length`, `_resolve_shots`, `_resolve_story_engine`, dry run | resolver inserted before `_resolve_shots` (SPC13 c) |
| `:136-215`, `:228-232` | the `STORY_PROMPT_TEMPLATE*` "EXACTLY {panels} panel sections" and `build_story_prompt` | unchanged; called with the effective count after the run (SPC13 g) |
| `:582-588`, `:1290-1393` | legacy engine: `_phase1_max_tokens(args.panels)`, `_validate_story_md(..., args.panels)` | **unchanged**: `--story-legacy` and `--story-prompt-override` keep an exact count |

**`story_prompt.txt` and the judge.** The robust engine's judge gate runs `bin/judge-story --patches` (`story_engine.py:3829-3870`, `run_judge`). The `--patches` path returns through `main_patches` (`bin/judge-story:449-450`) before it ever reads `story_prompt.txt` (`:452-462`). Only a standalone `bin/judge-story --story-id` and the legacy `bin/iterate-story` path read it. SPC13 (g) keeps it consistent with `story.md` for them.

**Stills, manifest, render** (no change needed):
- **Stills.** `bin/ltx-story-images` takes its panels from `story.md` (`:227-245`). Chained Phase 2 is `--only 1`. Shots groups come from `story.md` (`bin/ltx-movie:1866-1886`).
- **Manifest.** `bin/ltx-story-manifest` takes `n_panels` from `story.md` (`:700`) and exits 2 when `--target-seconds` does not fit `n_panels × frames` (`:743-751`). That is why the effective count must be adopted before Phase 3. `_casting_plan` needs `len(beats) == n_panels` (`:425-427`), which holds.
- **Render.** `bin/ltx-mlx-render`'s estimate counts manifest units (`:848`, `:871`).

**movie UI**

Unchanged:
- `build_argv` passes the form's `--panels` (`movie_ui_lib.py:969-970`), which is the target.
- Run All submits the compose fields (`static/movie-ui/app.js:566`).
- `panels_total` comes from the render's `panels: N` line and the `=== panel k/N (` headers (`movie_ui_lib.py:1989-2088`), so it is already effective.
- No UI estimate uses the count (`app.js:399` shows only s per panel).

Changed:
- Shots stills `expected` (`movie_ui_lib.py:2132`) and the `redo` range check (`:1385`) use `resolved_panels(fields)`, which is the target.
- `storyFields` falls back to `st.checks.panels` (`app.js:737`).
- `movie_ui_lib.py` never loads a pipeline module (`:5`). Its `MODES` (`:887`) equal the plan modes.

**`bin/iterate-story`.** `build_engine_cmd` passes `--panels str(plan["panels"])` (`:265`). That would ratchet the target upward.

**Fixtures.** The hockey narrative is `tests/fixtures/narrative_fidelity/narrative.txt`. `tests/test_narrative_fidelity.py:23` sets `FIXTURES` and `:186-187` reads it as `HOCKEY`.

### 0.4 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | SPC1-SPC12 |
| G2 | `bin/ltx-movie` | SPC13 |
| G3 | `movie_ui_lib.py`, `static/movie-ui/app.js`, `static/movie-ui/index.html` | SPC14, SPC16 |
| G4 | `bin/iterate-story` | SPC15 |
| G5 | `tests/test_soft_panel_count.py` (new) | SPT1-SPT27 (Section 4.1) |
| G6 | Existing tests and fixtures | The re-baselines of Section 4.2, in a separate test-only commit whose body explains each changed file ([SF] Section 4.2 rule) |
| G7 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baselined in its own follow-up commit; the comment gains `, then to <sha> (soft panel count).` |

**Changed prompt sentences (no longer frozen):** `LINES_RULE` and `LINES_PINNED_SENTENCE` (SPC2). They supersede [NF] and [PCP]'s wording for these two constants.

**Not changed:**
- **Files:** `character_lib.py`, `bin/ltx-story-manifest`, `bin/ltx-story-images`, `bin/ltx-mlx-render`, `movie_ui_server.py`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`, and the legacy engine path of `bin/ltx-movie`.
- **Schemas and budgets:** `PLAN_SCHEMA`, `CHECKS_SCHEMA` and `RUN_SCHEMA` (the strings stay `v1`; only fields are added), `PLAN_MAX_CALLS` and `PANEL_MAX_CALLS`.
- **Prompt texts:** `LINE_SPEAKERS_SENTENCE`, `MODE_PARAGRAPHS`, `MODE_RULES` and the writer prompt templates.
- **Critic:** its patch targets. The critic never adds or removes beats.

### 0.5 Out of scope and known limits

- **The extra is fixed.** `PANELS_EXTRA` is a constant (2). There is no CLI flag and no movie-UI field for it.
- **`--length` is a target too.** It resolves to `--panels`, so a `--length` movie can run up to 2 clips (about 12 s at the defaults) longer than asked.
- **The legacy engine keeps an exact count.** `--story-legacy` and `--story-prompt-override` are unchanged.
- **A dry run of a story that does not exist yet** prints Phase 2-4 commands for the target count. The `Panel count:` line says the plan may change it (SPC13 e).
- **A rerun outside the range is refused as today.** If `--panels` changes so that the saved story's count is outside `[N, N+2]`, the re-check fails with the existing message `expected exactly N panels, found M`. Fix it with `--force-story`, or with a `--panels` that brackets the story. Conversely, a lower `--panels` whose range still contains the story's count **reuses** the story (C13).
- **The P20 reason is a deterministic best guess** (SPC11), with a generic fallback.
- **When the planner keeps the last line in the last beat although there was room,** the pipeline does not retry the plan and does not write an exit beat. P19 says so (SPC12).
- **Uncast and invented-character speakers do not raise `lo`.** `lo` uses only the speakers of declared characters (`--character`), the same speakers the plan prompt names in `LINE_SPEAKERS_SENTENCE`. P20 names a speaker reason from the plan's full cast after the fact.
- **Cost.** Each added panel is one more writer call and one more render clip. In shots mode it is also one more still.
- **[SF] amendment.** [SF] SF-A1's own P19 hint (`use --panels %d to keep it`) is amended the same way as SPC12: every hint says `rerun with --force-story --panels %d`. The coordinator patches the [SF] spec text to match. This spec's SPC12 is the code that ships.

### 0.6 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SPK1 | From `WS`, `python3 -m pytest tests/ -q -rA` passes after G5-G7. The only failures allowed are those recorded before implementation (same tests, same messages). `python3 tests/test_ltx_movie_offline.py` prints `OK n/n`. | full run |
| SPK2 | `/usr/bin/python3` (3.9) and `python3` both `py_compile` `story_engine.py`, `bin/ltx-movie`, `bin/iterate-story` and `movie_ui_lib.py`. None gains an import. | SPT1, `git diff` |
| SPK3 | **Range.** A plan with `lo..hi` beats is accepted. Any other count is a hard, fatal P1 with the SPC7 text. `lo = max(N, lines_needed)` (one speaker per panel) and `hi = N + 2`. | SPT2, SPT6, SPT10, SPT24 |
| SPK4 | **Effective count everywhere.** In an `se.run` whose plan has N+1 beats: N+1 panel calls; `story.md` has N+1 panels; `plan.json`, `story_checks.json` and `run.json` have `panels == N+1` and `panels_target == N`. In `bin/ltx-movie`, after Phase 1, `args.panels == N+1`. So `_target_seconds`, `_shots_image_flags`, `_catalog_panel_loras` and `--redo` use N+1, and `story_prompt.txt` asks for N+1. | SPT8, SPT15, SPT16, SPT25 |
| SPK5 | **The user is told, every time.** When the count differs from the target, three things happen. (1) Exactly one P20 advisory with its reason is printed right after the plan, saved in `plan.json` `speech_notes`, and returned among `se.run`'s advisories (`Warning: plan: P20 ...`). (2) On every `bin/ltx-movie` run (generate, re-check or render), `note: story.md has N panels for a target of T (because ...)` carries the saved P20 reason. (3) With the count equal to the target, neither appears. | SPT8, SPT9, SPT11, SPT16 |
| SPK6 | **Lines.** When `N < lines_needed <= N+2`, the plan prompt asks for at least `lines_needed` beats. When `lines_needed > N+2`, the run exits 2 before any call, with the SPC3 message. | SPT3, SPT4 |
| SPK7 | **Reuse.** `load_plan`, `recheck` and the `bin/ltx-movie` resolver accept a saved plan whose `panels` is in `[N, N+2]` and adopt its count. The resolver and the movie UI also require that the plan's mode matches and that `story.md` has that many panels. `--force-story` always re-plans for target N. | SPT14, SPT15, SPT20 |
| SPK8 | **[SF] consistency.** `@@MAX_STATIC@@` uses the target, P18 uses the effective count, and P19 carries the SPC12 hint. | SPT13, SPT19 |
| SPK9 | **movie UI.** Shots stills `expected` and the redo range use the story's count when its plan matches the mode, is in range, and matches `story.md`. A story opened with no earlier job pre-fills `panels_target`. The Size fieldset shows the target note. | SPT20 |
| SPK10 | **Live, this Mac, post-merge, not a merge gate.** Section 5 KPIs L1-L7. | Section 5 |
| SPK11 | **Regenerate with a new target.** The Stories view has `#s-regen-panels`. An empty value regenerates with the original sizing (today's argv). A value N gives the argv `--panels N` (no `--length`) `... --force-story --story-only --no-review`, and the confirm text names N. | SPT26, SPT27 |

### 0.7 Must-haves and nice-to-haves

- **Must-haves:** SPC1-SPC16 and SPT1-SPT27.
- **Nice-to-haves:** none.
- **Explicitly not built:**
  - a flag for the extra;
  - a plan retry for a dropped exit;
  - a pipeline-written exit beat;
  - a planner-written reason field.

---

## 1. Design decisions

### D1. The effective count travels in `StoryContext.panels`; the target gets a new field **[spec choice]**

- **The new field.** `StoryContext` gains `panels_target`, default `None`, which means "equal to `panels`".
- **The swap.** Until the plan is accepted, `ctx.panels` is the target. On acceptance, `_Run.go` sets `self.ctx = ctx._replace(panels=len(plan["beats"]), panels_target=N)`.
- **Why.** Writer prompts, panel loops, shots checks, `patch_ranges`, the code-only critic loop, `_checks_doc` and the progress lines all become effective without edits.
- **The few target-only uses** call `target_panels(ctx)`: the plan prompt, P1, the pre-flight and the plan budgets.
- **Rejected: a separate `beats` field.** That needs about 20 call-site edits, and each missed site silently uses the wrong count.

### D2. Range bounds: `lo = max(N, lines_needed)`, `hi = N + 2`; one speaker per panel **[spec choice]**

- **`lines_needed`** is the fewest panels that speak the lines in order, with one speaker per panel.
- **Speaker runs.** The lines are split into runs that one beat could hold by speaker (`speaker_runs`). A line starts a new run when its speaker is known and differs from a known speaker earlier in the current run. A line with no known speaker joins the current run, because it may be the same speaker. This keeps `lo` a true lower bound.
- **The sum.** `panels_needed` (word and fragment packing, unchanged) is summed over the runs.
- **Which speakers count.**
  - Speakers come from `line_speakers` against the declared members only, mapped exactly as `build_plan_prompt` maps them (`:940-945`). These are the speakers the planner is told about (`LINE_SPEAKERS_SENTENCE`), and P17 enforces them.
  - An uncast narrative gives all-`None` speakers, so its `lines_needed` equals today's `panels_needed`.
- **When `N < lines_needed <= N+2`,** `lo` rises, the planner is told the minimum, and P1 rejects a plan that cannot hold the lines. This makes the `:755` error automatic inside the cap.
- **When `lines_needed > N+2`,** the pre-flight still exits 2 before any call.

### D3. The planner prefers the target, as with word ranges **[spec choice]**

- **The count request.** The prompt asks for `lo` to `hi` beats: use `lo` beats when the narrative fits them, and add a beat only for something no other beat can hold.
- **`PANEL_COUNT_LINES_SENTENCE`** is added when the narrative has spoken lines. It says that a line which cannot share a beat gets its own beat.
- **`LINES_RULE`**
  - It is tied to the lower bound: give each line its own beat whenever the `lo` target beats are at least as many as the lines.
  - It says never to add a beat only to separate lines that fit together.
  - Lines may share a beat only when one character says them all.
- **`LINES_PINNED_SENTENCE`** says to add a beat for an unspoken pinned character when the count allows it, and only otherwise to let two consecutive lines share one.
- **The exit case** is carried by [SF]'s `SPEAKING_BEAT_SENTENCE`, reworded in SPC12.

### D4. The reason is deterministic **[spec choice]**

P20 names every reason that applies, in this order:
1. the lines need more panels than the target by words;
2. the lines need more panels than that because of speaker changes (speakers from the plan's own cast);
3. the narrative's exit after its last line has a later beat.

With none of these, it gives a fixed generic reason.

**Rejected: a planner-written `panels_reason` key.** It would add an eighth key to the "exactly these seven keys" contract, its text is unverifiable, and a missing key would need its own handling path.

### D5. P19 stays advisory and is never retried; its hint depends on the room left **[spec choice]**

- **What fires it.** The SF-A1 condition is unchanged: the last spoken line is in the last beat, and the narrative has an exit after it.
- **Room left** (`beats < N+2`). The hint says to rerun with `--force-story`, or with `--force-story --panels beats+1`.
- **No room.** The hint says to rerun with `--force-story --panels beats+1`.
- **Every count hint names `--force-story`.** Without it, an existing `story.md` is re-checked instead of re-planned. The SPC3 pre-flight hint says the same.
- **Rejected: a plan retry.** It costs a full plan call and can regress lines, speakers and cast. This is the same reasoning as [SF] D3 for P18.

### D6. Plan reuse accepts any count in the target's range **[spec choice]**

- **The rule.** A saved plan is reused when `N <= plan["panels"] <= N + 2`. `load_plan`, the `bin/ltx-movie` resolver and the movie UI apply the same rule.
- **Two extra checks in the resolver and the movie UI.** They also require that the plan's mode matches and that `story.md` parses to exactly `plan["panels"]` panels. This catches a stale `plan.json`, for example one left next to a `story.md` that a later `--story-legacy` or `--story-prompt-override` run kept or hand edits changed.
- **Older plans** have no `panels_target` and `panels == N`. They are accepted.
- **A lower `--panels` can reuse a bigger story** whose count is inside its range. For example, `--panels 2` on a saved 4-panel story reuses it, where `6f16063` errors (C13).

### D7. `bin/ltx-movie` adopts the effective count in two places, and always says why **[spec choice]**

- **Before Phase 1.** This applies only to the robust engine, with no `--force-story` and an existing `story.md`.
  - `main` calls `_resolve_story_panels(args)` before `_resolve_shots`, so `--redo` is range-checked against the real story.
- **After Phase 1 returns 0,** in both its generate and re-check paths, `_phase1_robust` does three things:
  1. adopts `plan.json`'s count into `args.panels`;
  2. rewrites `story_prompt.txt` with that count, when the run generated the story and the count differs from the target;
  3. prints `PANEL_COUNT_NOTE` with the saved P20 reason. This is the one place the reason reaches the re-check and render path.
- **The "Phases 2-4 use all N" clause** is printed only when Phases 2-4 will run, that is, not under `--story-only`.
- **Rejected: return the count from `engine.run`.** About 150 test call sites unpack `rc, advisories = se.run(ctx)`.

### D8. Budgets **[spec choice]**

- **The plan call.** `plan_max_tokens` and `plan_timeout` use `most_panels(ctx)` (N+2), because the count is not yet known.
- **The wall-clock cap.** `_Run.__init__` uses N+2, because the cap must cover the plan stage. Right after the plan is accepted, the cap becomes `wall_clock_cap(effective)`, and run.json `budgets.wall_clock_s` is updated.
- **Effect.** `max(2400, n*180)` differs between the two counts only from 12 panels up.

### D9. `@@MAX_STATIC@@` uses the target; the P18 cap uses the effective count

- **The prompt** says "at most `max_static(N)`", the stricter of the two caps, so a plan that obeys the prompt is never coerced.
- **`cap_static_cameras`** runs after the ctx swap, so P18 caps at `max_static(effective)`.

### D10. Chained mode treats extra panels like any other panel

- **Chained.** An added panel is one more continuation clip from the previous clip's last frame. The take gets one clip longer, Phase 2 still renders only panel 1, and `MODE_PARAGRAPHS["chained"]` already describes the take without a count.
- **Shots** adds one still and one clip per added panel.
- **`no_stills`** adds one clip.
- **The same range** applies in all three modes **[spec choice]**.

### D11. The movie UI needs four small changes **[spec choice]**

1. Shots stills `expected` uses the story's count.
2. The redo range uses the story's count.
3. The `storyFields` fallback prefers `checks.panels_target`, so a story opened from the list does not ratchet its target upward.
4. A static hint goes in the Size fieldset.

Nothing changes in the job queue or Run All: they pass the target, and `bin/ltx-movie` resolves the rest.

`movie_ui_lib.py` never loads a pipeline module. So it repeats `PANELS_EXTRA = 2` and the manifest's panel-header regex, and a test pins both equal to the originals.

### D12. `story_prompt.txt` carries the effective count **[spec choice]**

- **When it is rewritten.** After a generate run whose count differs from the target, `_phase1_robust` rewrites `story_prompt.txt` from `build_story_prompt(..., args.panels, ...)` with the adopted count.
- **Why.** A standalone `bin/judge-story --story-id` then sees `EXACTLY <effective> panel sections`, which matches `story.md`, so its compliance check cannot fail on the count. The legacy `bin/iterate-story` path sees the same.
- **The engine's own `--patches` judge gate** never reads the file (Section 0.3).
- **Rejected: document the mismatch.** A judge given "EXACTLY 2" and a 3-panel story would rightly report a violation.

---

## 2. Requirements (normative)

### SPC1. Context field and helpers (`story_engine.py`)

**`StoryContext` (`:82-86`)** becomes:

```python
StoryContext = collections.namedtuple("StoryContext", [
    "ws", "story_id", "story_dir", "mode", "panels", "seconds", "narrative", "goal", "members",
    "seed_image", "seed_agent_image", "story_model", "context_window", "video_model",
    "auto_lora", "catalog", "pinned", "stills_pinned", "judge", "narration", "clip_seconds",
    "panels_target"],
    defaults=(True, None, None))
```

After the comment block below it (`:87-91`), add:

```python
# Soft panel count spec SPC1, D1: panels is the movie's panel count -- the --panels target until
# the plan is accepted, the plan's beat count after; panels_target is --panels (None: panels).
```

Immediately after `engine_seconds` (`:94-96`), add:

```python
# Soft panel count spec SPC1, D2: the planner may add up to PANELS_EXTRA beats to the target.
PANELS_EXTRA = 2


def target_panels(ctx):
    """The --panels target (soft panel count spec SPC1)."""
    return ctx.panels if ctx.panels_target is None else ctx.panels_target


def most_panels(ctx):
    """The most beats a plan may have: the target plus PANELS_EXTRA (SPC1)."""
    return target_panels(ctx) + PANELS_EXTRA
```

Immediately after `panels_needed` (`:719-728`), add:

```python
def speaker_runs(lines, speakers):
    """The spoken lines split into the runs one beat could hold by speaker (soft panel count spec
    SPC1, D2): a line starts a new run when its speaker is known and differs from a known speaker
    earlier in the current run; a line with no known speaker (None) joins the current run."""
    runs, current, who = [], [], None
    for line, cid in zip(lines, speakers):
        if current and cid is not None and who is not None and cid != who:
            runs.append(current)
            current, who = [], None
        current.append(line)
        if cid is not None:
            who = cid
    if current:
        runs.append(current)
    return runs


def lines_needed(lib, seconds, lines, speakers):
    """The fewest panels that speak lines in order with one speaker each (SPC1): panels_needed
    summed over speaker_runs."""
    return sum(panels_needed(lib, seconds, run) for run in speaker_runs(lines, speakers))


def declared_speakers(ctx):
    """line_speakers of the narrative against the declared members, as c1, c2, ... in
    --character order (the mapping build_plan_prompt gives the planner); one None per line when
    nothing is declared (SPC1)."""
    fixed = [{"id": "c%d" % i, "phrase": m.phrase, "cast_name": m.name}
             for i, m in enumerate(ctx.members, start=1)]
    return line_speakers(ctx.narrative, fixed)
```

In `build_plan_prompt` (`:940-943`), the local `fixed = [...]` and `line_speakers(ctx.narrative, fixed)` become `declared_speakers(ctx)`. The `items` comprehension then reads `in enumerate(declared_speakers(ctx), start=1) if cid`. The output is byte-identical.

Immediately after `spoken_lines_problem` (`:731-761`), add:

```python
def panel_range(ctx):
    """(fewest, most) beats a plan may have (soft panel count spec SPC1, D2): the target, or the
    panels the narrative's spoken lines need with one speaker each when that is more; and the
    target plus PANELS_EXTRA. character_lib is loaded only when the narrative quotes spoken
    lines."""
    lines = required_lines(ctx)
    needed = (lines_needed(_character_lib(ctx.ws), engine_seconds(ctx), lines,
                           declared_speakers(ctx)) if lines else 0)
    return max(target_panels(ctx), needed), most_panels(ctx)
```

### SPC2. Constants and the reworded line rules (`story_engine.py`)

**`LINES_RULE` (`:371-377`)** becomes exactly the following (the comment above it is kept, with `; soft panel count spec SPC2` appended):

```python
LINES_RULE = (" lines is the list of the numbers of the spoken lines above that the speaker says "
              "aloud during the beat, in order, or an empty list. Every spoken line belongs to "
              "exactly one beat, in the narrative's order: give each line to the beat whose action "
              "surrounds it in the narrative, and give a speaker to every beat with lines and to no "
              "other beat. A beat may hold two or more consecutive lines only when one character "
              "says them all and together they are at most @@LINE_WORDS@@ words. Give each line its "
              "own beat whenever there are at least as many target beats (@@MIN_BEATS@@) as lines; "
              "never add a beat only to separate lines that fit together.")
```

**`LINES_PINNED_SENTENCE` (`:380-382`)** becomes exactly the following (the comment above it is kept, with `; soft panel count spec SPC2` appended):

```python
LINES_PINNED_SENTENCE = (" A beat with a speaker shows only the speaker, so every already-cast "
                         "character who says none of the lines still needs a beat with no "
                         "speaker: add a beat for it when the beat count allows it, else let two "
                         "consecutive lines share one.")
```

**New constants.** Add immediately after `LINE_SPEAKERS_SENTENCE` (`:384-386`):

```python
# Soft panel count spec SPC2, D3: the beat count is a target the planner may exceed by up to
# PANELS_EXTRA, like a word range.
PANEL_COUNT_RULE = (" This movie's target length is %d beats%s, and like a word range it is "
                    "soft: use %d beats when the narrative fits them, and add a beat, up to %d "
                    "beats in all, only for something the narrative needs that no other beat can "
                    "hold.")
PANEL_COUNT_MIN_CLAUSE = ", but its spoken lines need at least %d"
PANEL_COUNT_LINES_SENTENCE = (" A spoken line that cannot share a beat with the line beside it "
                              "gets a beat of its own.")
# Soft panel count spec SPC5: the arc rule for each beat count the range allows.
ARC_COUNT_CLAUSES = {
    1: "with 1 beat, use climax",
    2: "with 2 beats, the first beat is introduction and the last is resolution",
    3: ("with 3 or more beats, the first beat is introduction, the last is resolution, and at "
        "least one beat is climax"),
}
```

### SPC3. The spoken-lines pre-flight (`story_engine.py:754-760`)

Replace the `needed` block of `spoken_lines_problem` with:

```python
    needed = lines_needed(lib, secs, lines, declared_speakers(ctx))
    most = most_panels(ctx)
    if needed > most:
        return ("the narrative quotes %d spoken lines, which need at least %d panels of %s seconds "
                "(one panel has one speaker and speaks at most %d words), but this movie has at "
                "most %d (--panels %d plus up to %d more); rerun with --force-story --panels %d "
                "or more, or with longer clips (a larger --frames)"
                % (len(lines), needed, ctx.seconds, lib.dialogue_word_cap(secs, 1), most,
                   target_panels(ctx), PANELS_EXTRA, needed - PANELS_EXTRA))
    return None
```

- **Docstring.** "or more lines than the panels can hold" becomes "or more lines than the target plus PANELS_EXTRA panels can hold, one speaker per panel (soft panel count spec SPC3)".
- **When `target < needed <= most`,** the function returns `None`, and `panel_range` raises the plan's lower bound.

**Example.** Four 8-word lines, 6-second clips, uncast, `--panels 1`:

`the narrative quotes 4 spoken lines, which need at least 4 panels of 6 seconds (one panel has one speaker and speaks at most 14 words), but this movie has at most 3 (--panels 1 plus up to 2 more); rerun with --force-story --panels 2 or more, or with longer clips (a larger --frames)`

### SPC4. The plan prompt (`story_engine.py`)

**Template (`:306-308`).** These template lines:

```
    "beats: a list of EXACTLY @@PANELS@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to @@PANELS@@. arc "
    "is one of "
```

become:

```
    "beats: a list of @@BEAT_COUNT@@ objects, one per panel in order, with the keys index, "
    "arc, action, shot, camera, location, @@BEAT_KEYS@@. index runs from 1 to the number of "
    "beats.@@PANEL_COUNT_RULE@@ arc is one of "
```

After this, `PLAN_PROMPT_TEMPLATE` contains no `@@PANELS@@`.

**`build_plan_prompt` (`:917-979`).**
- Immediately after `lines = required_lines(ctx)`, add:

  ```python
      lo, hi = panel_range(ctx)
      target = target_panels(ctx)
  ```

- **Fragments.**
  - The `@@ARC_RULE@@` entry (`:958`) becomes `("@@ARC_RULE@@", _plan_arc_rule(lo, hi)),`.
  - Insert immediately after it:

  ```python
          ("@@BEAT_COUNT@@", "EXACTLY %d" % lo if lo == hi else "%d to %d" % (lo, hi)),
          ("@@PANEL_COUNT_RULE@@", "" if lo >= hi else (
              PANEL_COUNT_RULE % (target, PANEL_COUNT_MIN_CLAUSE % lo if lo > target else "", lo,
                                  hi)
              + (PANEL_COUNT_LINES_SENTENCE if lines else ""))),
  ```

- **Scalars (`:976-978`).**
  - Remove `("@@PANELS@@", str(ctx.panels))`. No fragment or template text uses `@@PANELS@@` any more. A narrative containing `@@PANELS@@` stays verbatim, because the narrative is inserted last (`test_rst9`).
  - Add `("@@MIN_BEATS@@", str(lo))`, which `LINES_RULE` uses.
  - The [SF] SF2 scalar `("@@MAX_STATIC@@", str(max_static(ctx.panels)))` becomes `("@@MAX_STATIC@@", str(max_static(target)))` (D9).
- **Docstring.** It gains `Soft panel count spec SPC4: the beat count is lo to hi of panel_range; @@MIN_BEATS@@ is lo.`

**Example: uncast default narrative, `--panels 3` (`lo, hi = 3, 5`).** The planner sees:

`beats: a list of 3 to 5 objects, one per panel in order, with the keys index, arc, action, shot, camera, location, cast and speaker. index runs from 1 to the number of beats. This movie's target length is 3 beats, and like a word range it is soft: use 3 beats when the narrative fits them, and add a beat, up to 5 beats in all, only for something the narrative needs that no other beat can hold. arc is one of introduction, rising, climax, falling, resolution, in story order; the first beat is introduction, the last is resolution, and at least one beat is climax. action is ...`

**Other cases.**

| Case | Count text | Count rule |
|---|---|---|
| `N < M < N+2`, where M is what the lines need | `M to N+2` | the sentence reads `This movie's target length is N beats, but its spoken lines need at least M, and like a word range it is soft: use M beats ...` |
| `M == N+2`, so `lo == hi` | `EXACTLY M` | none |
| `lo > hi` | `lo to hi`, as computed | none |

The `lo > hi` case is unreachable in a run, because SPC3 exits first; it can only appear when `build_plan_prompt` is called directly.

### SPC5. The arc rule for a range (`story_engine.py`)

Add immediately after `_arc_rule` (`:788-794`, unchanged):

```python
def _plan_arc_rule(lo, hi):
    """The plan prompt's arc rule for a movie of lo to hi beats (soft panel count spec SPC5):
    _arc_rule(lo) from 3 beats up, else one ARC_COUNT_CLAUSES clause per count from lo up to 3."""
    if lo >= 3:
        return _arc_rule(lo)
    return "; ".join(ARC_COUNT_CLAUSES[k] for k in range(lo, min(hi, 3) + 1)) + "."
```

| target (no lines) | `lo, hi` | `@@ARC_RULE@@` |
|---|---|---|
| 1 | 1, 3 | `with 1 beat, use climax; with 2 beats, the first beat is introduction and the last is resolution; with 3 or more beats, the first beat is introduction, the last is resolution, and at least one beat is climax.` |
| 2 | 2, 4 | `with 2 beats, the first beat is introduction and the last is resolution; with 3 or more beats, the first beat is introduction, the last is resolution, and at least one beat is climax.` |
| >= 3 | N, N+2 | `the first beat is introduction, the last is resolution, and at least one beat is climax.` (byte-identical to `6f16063`) |

### SPC6. `normalize_plan` (`story_engine.py:1079-1146`)

- In the plan literal (`:1085-1089`), `"panels": ctx.panels,` becomes `"panels": ctx.panels, "panels_target": target_panels(ctx),`.
- Immediately after `plan["beats"] = beats` (`:1131`), add `plan["panels"] = len(beats)`.
- `plan.json` keys therefore begin `schema, story_id, mode, panels, panels_target, seconds, ...`.
- The docstring gains: `plan["panels"] is the beat count and plan["panels_target"] the --panels target (soft panel count spec SPC6).`

### SPC7. P1 and the beat-range checks (`story_engine.py`)

**`plan_checks` (`:1542-1549`)** becomes:

```python
    beats = plan["beats"]
    n = len(beats)
    lo, hi = panel_range(ctx)
    if not lo <= n <= hi:
        hard.append("plan: P1 beat count: expected exactly %d beats, found %d" % (lo, n)
                    if lo == hi else
                    "plan: P1 beat count: expected %d to %d beats, found %d" % (lo, hi, n))
    for i, beat in enumerate(beats):
        if beat["index"] != i + 1:
            hard.append("plan: P1 beat count: beat %d has index %r; beats must be numbered 1 to %d "
                        "in order" % (i + 1, beat["index"], n))
```

- **Later uses of `n` in `plan_checks`** now mean `len(beats)`, with no other edit: P5 required roles (`:1620-1621`), P6 (`:1629`) and P10 `k <= n` (`:1650`).
- **P17's loop** `for n in beat["lines"]` (`:1690`) shadows `n` after its last use above, so it is left as is.
- **Docstring.** It gains: `P1 accepts lo to hi beats of panel_range (soft panel count spec SPC7).`

**`lora_checks` (`:1747`).** `n = ctx.panels` becomes `n = len(plan["beats"])`. The L1 per_beat message keeps its text.

### SPC8. `story_checks.json` (`story_engine.py:3458-3465`)

`_checks_doc`'s `"panels": ctx.panels,` becomes `"panels": ctx.panels, "panels_target": target_panels(ctx),`. The keys begin `schema, story_id, mode, panels, panels_target, checked_at, ...`.

### SPC9. The run: ctx swap, budgets and notes (`story_engine.py`)

**`_Run.__init__` (`:3471-3497`):**
- `self.cap = wall_clock_cap(ctx.panels)` becomes `self.cap = wall_clock_cap(most_panels(ctx))`.
- In `self.doc`, `"panels": ctx.panels,` becomes `"panels": ctx.panels, "panels_target": target_panels(ctx),`.

**`plan_round` (`:3545-3546`).** `plan_max_tokens(ctx.panels)` and `plan_timeout(ctx.panels)` become `plan_max_tokens(most_panels(ctx))` and `plan_timeout(most_panels(ctx))`.

**`go` (`:3771-3772`).** The code after `plan, self.shape, _hard = found` must be exactly this, in this order. It replaces `:3772` and the two notes lines [SF] adds after it.

```python
        plan, self.shape, _hard = found
        # Soft panel count spec SPC9, D1: from here on the movie has the plan's beat count.
        ctx = self.ctx = ctx._replace(panels=len(plan["beats"]), panels_target=target_panels(ctx))
        self.cap = wall_clock_cap(ctx.panels)
        self.doc["panels"] = ctx.panels
        self.doc["budgets"]["wall_clock_s"] = self.cap
        self.panel_calls = dict((k, 0) for k in range(1, ctx.panels + 1))
        self.write_run()
        plan["speech_notes"] += assign_missing_lines(ctx, plan)
        plan["speech_notes"] += cap_static_cameras(ctx, plan)
        plan["speech_notes"] += exit_left_out_notes(ctx, plan)
        count_notes = panel_count_notes(ctx, plan)
        plan["speech_notes"] += count_notes
        for note in count_notes:
            print(note)
```

The `parts` list and the round-0 loop (`:3773-3775`) read the rebound local `ctx`.

### SPC10. Plan reuse and recheck (`story_engine.py`)

**`load_plan` (`:3873-3891`).**
- Add immediately before it:

  ```python
  def _count_in_range(panels, target):
      """True when panels is an int (not a bool) from target to target + PANELS_EXTRA (SPC10)."""
      return (isinstance(panels, int) and not isinstance(panels, bool)
              and target <= panels <= target + PANELS_EXTRA)
  ```

- **Docstring.** It becomes `"""<story_dir>/plan.json when it is a valid plan for ctx's mode whose panels lie in the target's range (soft panel count spec SPC10), else None."""`.
- **Condition.** `or plan.get("mode") != ctx.mode or plan.get("panels") != ctx.panels` becomes `or plan.get("mode") != ctx.mode or not _count_in_range(plan.get("panels"), target_panels(ctx))`. No other condition changes.

**`recheck` (`:3969`).** Immediately after `plan = load_plan(ctx)`, add:

```python
    if plan is not None:
        # Soft panel count spec SPC10: re-check against the plan's panel count; the saved target
        # comes from plan.json (an older plan has none: the current target).
        saved = plan.get("panels_target")
        ctx = ctx._replace(panels=plan["panels"], panels_target=(
            saved if isinstance(saved, int) and not isinstance(saved, bool)
            else target_panels(ctx)))
```

- **What reads the replaced `ctx`:** everything after this point, including `legacy_validate(story_md, ctx.panels, ...)`, `shots_violations(..., ctx.panels, ...)`, `_checks_doc` (so `story_checks.json` `panels_target` is the saved target) and the malformed-plan fallback.
- **With `plan is None`,** the ctx is untouched.
- **What recheck never produces:** P18, P19 or P20.

### SPC11. P20 "panel count" (`story_engine.py`)

Add immediately after [SF] SF-A1's `exit_left_out_notes`:

```python
# Soft panel count spec SPC11, D4: tell the user when the movie has more panels than its target,
# and why.
P20_NOTE = ("plan: P20 panel count: this movie has %d panels, %d more than its target of %d, "
            "because %s")
P20_LINES_REASON = "the narrative's %d spoken lines need at least %d panels of %s seconds"
P20_SPEAKER_REASON = ("the narrative's spoken lines come in %d runs by different speakers, which "
                      "need at least %d panels with one speaker each")
P20_EXIT_REASON = "the narrative's exit after its last spoken line (%s) has a later beat"
P20_OTHER_REASON = "the story planner needed them for the narrative's action"


def panel_count_notes(ctx, plan):
    """[P20_NOTE] when the plan has more beats than the target, else [] (SPC11). Reasons, in order
    and joined with " and ": the lines need more panels than the target by words; the lines need
    more panels than that because of speaker changes (speakers from plan["cast"]); the narrative's
    exit after its last spoken line follows the beat that says that line. With none,
    P20_OTHER_REASON."""
    n, target = len(plan["beats"]), target_panels(ctx)
    if n <= target:
        return []
    reasons = []
    lines = plan.get("spoken_lines") or []
    if lines:
        lib, secs = _character_lib(ctx.ws), engine_seconds(ctx)
        by_words = panels_needed(lib, secs, lines)
        if by_words > target:
            reasons.append(P20_LINES_REASON % (len(lines), by_words, ctx.seconds))
        speakers = line_speakers(ctx.narrative, plan["cast"])
        by_speaker = lines_needed(lib, secs, lines, speakers)
        if by_speaker > max(target, by_words):
            reasons.append(P20_SPEAKER_REASON % (len(speaker_runs(lines, speakers)), by_speaker))
        found = narrative_exit_after_last_line(ctx.narrative)
        said = [k for k, beat in enumerate(plan["beats"], start=1)
                if len(lines) in beat.get("lines", [])]
        if found is not None and said and said[0] < n:
            reasons.append(P20_EXIT_REASON % _q(found))
    if not reasons:
        reasons.append(P20_OTHER_REASON)
    return [P20_NOTE % (n, n - target, target, " and ".join(reasons))]
```

**Where the note goes.**
- `parse_violation` reads it as `("P20", "panel count", "plan", None)`.
- It goes into `plan["speech_notes"]`, and from there into:
  - `plan.json`;
  - every state's advisories (`plan_checks`, `:1730`);
  - `story_checks.json`;
  - `se.run`'s advisories, which `bin/ltx-movie` prints as `Warning: plan: P20 ...` (`:1634-1635`).
- `go` also prints it right after the plan (SPC9).
- It is advisory everywhere: never hard, never retried, never blocking.

**Example.** Hockey narrative, `--panels 2`, 3 beats with lines `[1]`, `[2]`, `[]`:

`plan: P20 panel count: this movie has 3 panels, 1 more than its target of 2, because the narrative's exit after its last spoken line ('skates away') has a later beat`

### SPC12. [SF] amendments: P19 hint and the speaking-beat sentence (`story_engine.py`)

**(a) SF-A1's P19.** [SF] SF-A1's `P19_NOTE` is replaced by these three constants. The comment above it is kept, with `; soft panel count spec SPC12` appended.

```python
P19_NOTE = ("plan: P19 exit left out: the narrative's exit after its last spoken line (%s) was "
            "left out, because that line is in the last beat and a speaking beat never shows its "
            "speaker leave; %s")
P19_ROOM_HINT = ("the planner could have added a beat for it (this movie may have up to %d), so "
                 "rerun with --force-story, or rerun with --force-story --panels %d to keep it")
P19_CAP_HINT = ("this movie already has the %d panels a target of %d allows, so rerun with "
                "--force-story --panels %d to keep it")
```

The last statement of `exit_left_out_notes`, `return [P19_NOTE % (_q(found), ctx.panels + 1)]`, becomes:

```python
    n, most = len(plan["beats"]), most_panels(ctx)
    hint = (P19_ROOM_HINT % (most, n + 1) if n < most
            else P19_CAP_HINT % (most, target_panels(ctx), n + 1))
    return [P19_NOTE % (_q(found), hint)]
```

- **When P19 fires** is unchanged.
- **Docstring.** It gains `; the hint says whether the movie had room for one more beat, and always names --force-story (soft panel count spec SPC12)`.
- **Examples.**
  - Room left (hockey, `--panels 2`, 2 beats): `...; the planner could have added a beat for it (this movie may have up to 4), so rerun with --force-story, or rerun with --force-story --panels 3 to keep it`.
  - At the cap (`--panels 1`, 3 beats, last line in beat 3): `...; this movie already has the 3 panels a target of 1 allows, so rerun with --force-story --panels 4 to keep it`.

**(b) SF3's `SPEAKING_BEAT_SENTENCE`** becomes exactly:

```python
SPEAKING_BEAT_SENTENCE = (" Write a speaking beat's action as what the speaker physically does, "
                          "never as speaking, and end it with the speaker still in frame: nobody "
                          "else acts after the line, and when the narrative has the speaker "
                          "leave, or another character act, after a line, give that a later beat "
                          "with no speaker, adding that beat when the beat count allows it, and "
                          "leave it out only when it does not.")
```

`SPEAKER_RULE` and `SPEAKER_RULE_KEEP_CAST` embed it, so they change by the same tail.

**(c) [SF] Section 0.5 "The hockey skate-away"** no longer describes a fixed limit. The exit is kept whenever the planner adds the beat, and P19 is the notice when it does not.

### SPC13. `bin/ltx-movie`

**(a) Constants.** Add immediately before `_story_context` (`:1420`):

```python
# Soft panel count spec SPC13, D7: the user is told when the story has more panels than its target,
# and why, on every run.
PANEL_COUNT_NOTE = "note: story.md has %d panels for a target of %d (%s)"
PANEL_COUNT_PHASES = "; Phases 2-4 use all %d"
PANEL_COUNT_NO_REASON = "plan.json records no reason"
DRY_PANELS_RANGE = ("Panel count: a target of %d; the plan may have %d to %d beats, and Phases 2-4 "
                    "use the plan's count.")
DRY_PANELS_STORY = ("Panel count: plan.json and story.md have %d panels for a target of %d; Phases "
                    "2-4 would use all %d.")
DRY_PANELS_STOP = "Panel count: Phase 1 would stop: %s"
```

**(b) Helpers.** Add immediately after them:

```python
def _plan_panels(args):
    """(panels, reason) of plan.json when it is the plan of this story.md (soft panel count spec
    SPC13, D6): a JSON object with schema ltx-movie.plan.v1, this run's mode, an int panels from
    the target (args.panels_target, else args.panels) to the target plus
    story_engine.PANELS_EXTRA, and story.md parsing to exactly that many panels; else None.
    reason is "because <the text after 'because '>" of the first speech_notes entry that starts
    "plan: P20 panel count: ", else PANEL_COUNT_NO_REASON."""
    target = getattr(args, "panels_target", None) or args.panels
    paths = _story_paths(args.story_id)
    try:
        with open(os.path.join(paths["story_dir"], "plan.json"), encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        return None
    panels = plan.get("panels") if isinstance(plan, dict) else None
    if (not isinstance(plan, dict) or plan.get("schema") != "ltx-movie.plan.v1"
            or plan.get("mode") != _story_mode(args) or not isinstance(panels, int)
            or isinstance(panels, bool)
            or not target <= panels <= target + _story_engine().PANELS_EXTRA
            or len(_load_story_panels(paths["story_md"])) != panels):
        return None
    notes = plan.get("speech_notes") if isinstance(plan.get("speech_notes"), list) else []
    saved = [m for m in notes if isinstance(m, str) and m.startswith("plan: P20 panel count: ")
             and ", because " in m]
    reason = ("because " + saved[0].split(", because ", 1)[1]) if saved else PANEL_COUNT_NO_REASON
    return panels, reason


def _resolve_story_panels(args):
    """Soft panel count spec SPC13, D7: args.panels_target is --panels; with the default story
    engine, no --force-story and an existing story.md whose plan.json is its plan for this run,
    args.panels becomes the plan's panel count. Prints nothing; never fails."""
    args.panels_target = args.panels
    if (args.story_legacy or args.story_prompt_override is not None or args.force_story
            or not os.path.isfile(_story_paths(args.story_id)["story_md"])):
        return
    found = _plan_panels(args)
    if found is not None:
        args.panels = found[0]


def _write_story_prompt(args, story_dir):
    """<story_dir>/story_prompt.txt: build_story_prompt for args.panels (soft panel count spec
    SPC13, D12)."""
    prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                bool(getattr(args, "seed_image", None)),
                                seconds=_clip_seconds(args),
                                cast_block=getattr(args, "cast_block", None),
                                shots=getattr(args, "shots", False))
    with open(os.path.join(story_dir, "story_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)
```

**(c) `main`.** Immediately before `rc = _resolve_shots(args)` (`:2473`), add `_resolve_story_panels(args)`.

**(d) `_story_context` (`:1438-1450`).** After `clip_seconds=args.frames / float(args.fps)`, add the argument `panels_target=getattr(args, "panels_target", None)`.

**(e) `_print_robust_phase1` (`:2224-2228`).**
- `engine.plan_max_tokens(args.panels)` becomes `engine.plan_max_tokens(engine.most_panels(ctx))`.
- `engine.plan_timeout(args.panels)` becomes `engine.plan_timeout(engine.most_panels(ctx))`.
- Immediately after the `print("Command (subprocess timeout %ds): %s" ...)` statement, add:

```python
    problem = engine.spoken_lines_problem(ctx)
    lo, hi = engine.panel_range(ctx)
    target = engine.target_panels(ctx)
    if problem:
        print(DRY_PANELS_STOP % problem)
    elif ctx.panels != target:
        print(DRY_PANELS_STORY % (ctx.panels, target, ctx.panels))
    else:
        print(DRY_PANELS_RANGE % (target, lo, hi))
```

The new line comes before the existing blank line, so `test_rst47`'s `block[:4]` and command-index assertions are unaffected.

**(f) `_phase1_robust` (`:1603-1645`).**
- **Generate branch.** The inline `prompt = build_story_prompt(...)` and the `with open(... "story_prompt.txt" ...)` block (`:1618-1625`) become `_write_story_prompt(args, paths["story_dir"])`. The branch records `generated = True`; the re-check branch sets `generated = False`.
- **After the advisories loop.** Immediately after `for advisory in advisories: print("Warning: %s" % advisory)` (`:1634-1635`), add:

```python
    target = getattr(args, "panels_target", None) or args.panels
    found = _plan_panels(args)
    if found is not None:
        args.panels = found[0]
        if args.panels != target:
            if generated:
                _write_story_prompt(args, paths["story_dir"])
            print(PANEL_COUNT_NOTE % (args.panels, target, found[1])
                  + ("" if args.story_only else PANEL_COUNT_PHASES % args.panels))
```

- **Order.** `target` is computed before `args.panels` is changed. This block runs after `if rc != 0: return rc`, in both branches.
- **`test_rst50b`.** Its count of `open(story_md, encoding="utf-8")` in `_phase1_robust` stays 2; the new opens live in the helpers.

**(g) Why the rewrite.** The rewritten `story_prompt.txt` says `EXACTLY <effective> panel sections`, which matches `story.md`. That keeps a standalone `bin/judge-story --story-id` compliance check, and the legacy `bin/iterate-story` path, consistent (D12).

**(h) `--panels` help (`:308-309`)** becomes:

`"number of chained clips; panel 1 also gets the movie's one still image; mutually exclusive with --length. With the default story engine it is a target: the plan may add up to 2 panels to fit the narrative, and Phases 2-4 use the plan's count."`

**Downstream.** After (c) or (f), `args.panels` is effective. These follow with no other edit: `_target_seconds`, `_shots_image_flags`, `_catalog_panel_loras`, `_catalog_plan`, the `--redo` range, and the Phase 3/4 dry-run commands of an existing story.

### SPC14. movie UI

**(a) `movie_ui_lib.py`.** Add immediately after `resolved_panels` (`:1214-1221`):

```python
# Soft panel count spec SPC14, D11: story_engine.PANELS_EXTRA and bin/ltx-story-manifest's
# _PANEL_HEADER_RE (this module never loads a pipeline module, so both are repeated here and
# pinned equal by a test).
PANELS_EXTRA = 2
STORY_PANEL_RE = re.compile(r"^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$", re.MULTILINE)


def plan_panels(sdir, mode):
    """<sdir>/plan.json's "panels" when the file is a JSON object with schema ltx-movie.plan.v1,
    "mode" equal to mode, an int "panels" of at least 1, and <sdir>/story.md has exactly that
    many STORY_PANEL_RE headers; else None (SPC14)."""
    plan = read_json(os.path.join(sdir, "plan.json"))
    if not (isinstance(plan, dict) and plan.get("schema") == "ltx-movie.plan.v1"
            and plan.get("mode") == mode and _is_int(plan.get("panels")) and plan["panels"] >= 1):
        return None
    try:
        with open(os.path.join(sdir, "story.md"), "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    return plan["panels"] if len(STORY_PANEL_RE.findall(text)) == plan["panels"] else None


def effective_panels(fields, sdir):
    """The story's panel count for fields (SPC14): plan_panels(sdir, fields["mode"]) when it lies
    in [resolved_panels(fields), resolved_panels(fields) + PANELS_EXTRA], else
    resolved_panels(fields). sdir None means no story directory."""
    target = resolved_panels(fields)
    planned = plan_panels(sdir, fields.get("mode")) if sdir is not None else None
    if target is not None and planned is not None and target <= planned <= target + PANELS_EXTRA:
        return planned
    return target
```

- **Rule 16 (`:1385`).** `total = resolved_panels(fields)` becomes `total = effective_panels(fields, sdir)`.
- **`snapshot` (`:2132`).** It becomes `expected = (effective_panels(self.fields, story_dir(job["workspace"], job["story_id"])) if self.fields.get("mode") == "shots" else 1)`.

**(b) `static/movie-ui/app.js` `storyFields` (`:737`).** The line

```js
    const panels = st.checks && st.checks.panels ? st.checks.panels : (S.options ? S.options.defaults.panels : 15);
```

becomes:

```js
    const saved = st.checks ? (st.checks.panels_target || st.checks.panels) : null;
    const panels = saved ? saved : (S.options ? S.options.defaults.panels : 15);
```

**(c) `static/movie-ui/index.html`.** Immediately after the `length` label's closing `</label>` in the Size fieldset (`:52-53`), add:

```html
      <span id="c-size-note" class="muted">Panels is a target: the default story engine may add up to 2 panels to fit the narrative.</span>
```

### SPC15. `bin/iterate-story` (`:265`)

`"--panels", str(plan["panels"])` becomes `"--panels", str(plan.get("panels_target", plan["panels"]))`.

### SPC16. movie UI: a panel target for "Regenerate story" (user-approved addendum)

**Problem (verified at `6f16063`).**
- The Stories view's "Regenerate story" button (`static/movie-ui/index.html:150`, handler `static/movie-ui/app.js:748-753`) submits `storyFields("regenerate")`. That is the story's `last_fields` with `action` set to `"regenerate"` (`app.js:734-739`), so it always reuses the original `--panels` or `--length`.
- `build_argv` (`movie_ui_lib.py:963-1015`) appends `--force-story` and `--story-only` for `regenerate` (`:1006-1012`).
- The UI therefore has no way to regenerate a story with a different panel target.

**Design (binding).**
- A number input "Panels (target)" goes beside the Regenerate button.
- **Prefill.**
  - It is prefilled with `last_fields.panels` when that is not null.
  - Otherwise it is left empty, with a placeholder showing the story's effective count.
- **Empty input** keeps the original sizing, which is today's behaviour.
- **A value N** submits `panels: N` and `length: null`.
- **The confirm text** names the target.
- **Server.** There is no new server field. The existing V1 validation of `panels` (rule 4, `movie_ui_lib.py:1326-1334`: exactly one of `panels`/`length`, integer 1..200) applies unchanged.
- **Interaction with C4/C13 (plan reuse).** Not relevant here: `regenerate` always passes `--force-story`, so the story is re-planned for target N.

**(a) `static/movie-ui/index.html` (`:150`).** The line

```html
      <button id="s-regenerate" type="button">Regenerate story</button>
```

becomes

```html
      <label>Panels (target) <input id="s-regen-panels" type="number" min="1" max="200" step="1" size="4"></label>
      <button id="s-regenerate" type="button">Regenerate story</button>
```

`max="200"` mirrors V1's limit. The server still enforces V1.

**(b) `static/movie-ui/app.js`, story detail.**
- In `openStory`, immediately after `show($("#s-redo-box"), Boolean(shots));` (`:716`), add:

```js
    const regen = $("#s-regen-panels");
    const lastPanels = res.data.last_fields ? res.data.last_fields.panels : null;
    regen.value = lastPanels !== null && lastPanels !== undefined ? String(lastPanels) : "";
    regen.placeholder = res.data.checks && res.data.checks.panels ? String(res.data.checks.panels) : "";
```

- `res.data.checks.panels` is the effective count (SPC8).

**(c) `static/movie-ui/app.js`, the Regenerate handler (`:748-753`).** It becomes:

```js
    $("#s-regenerate").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before regenerating it"; return; }
      const target = numberOrNull("#s-regen-panels");
      const question = target === null
        ? "Regenerate story.md of " + S.story.id + "? The current one is replaced."
        : "Regenerate story.md of " + S.story.id + " with a target of " + target + " panels? The current one is replaced.";
      if (!(await askConfirm(question))) { return; }
      const fields = storyFields("regenerate");
      const res = await submit(target === null ? fields : Object.assign(fields, {panels: target, length: null}));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
```

- `numberOrNull` is the existing helper (`app.js:135-138`).
- A non-integer or out-of-range value reaches the server and is refused by V1 with `"panels must be an integer from 1 to 200"`. The handler's existing `"refused; see Compose checks"` status covers it.

**(d) `movie_ui_lib.py`.** No change. With `action="regenerate"`, `panels=N` and `length=None`, `build_argv` yields:

`[py, <ws>/bin/ltx-movie, <narrative>, "--story-id", <id>, "--panels", "N", "--fps", ..., "--force-story", "--story-only", "--no-review"]`

The `--length` flag is absent.

---

## 3. Interactions (normative)

| Area | Behaviour after this change |
|---|---|
| Pre-flight | Exits 2 only when the lines need more than N+2 panels, one speaker each. Between N and N+2, `lo` rises (SPC3, SPC1). |
| Plan prompt | Count text `lo to hi`, plus `PANEL_COUNT_RULE` unless `lo == hi`. `LINES_RULE` uses `@@MIN_BEATS@@`. `@@MAX_STATIC@@` uses the target, and `@@PANELS@@` is gone (SPC2, SPC4, D9). |
| Plan retry | P1 out of range is hard, and fatal after `PLAN_MAX_CALLS` (`:3760`). P19 and P20 never retry. |
| After the plan | ctx swap → `assign_missing_lines` → `cap_static_cameras` (effective) → `exit_left_out_notes` (SPC12 hint) → `panel_count_notes` (P20, printed) (SPC9). |
| Round 0, critic, code-only, judge | Run over the effective count through `self.ctx`. The critic never changes the beat count. The `--patches` judge never reads `story_prompt.txt`. |
| Chained | Extra panels are extra continuation clips of the one take; Phase 2 renders panel 1 only (D10). |
| Shots / `no_stills` | Shots adds one still and one clip per added panel; `no_stills` adds one clip. |
| `--no-narration` | `lo = N`. No `LINES_RULE`, no lines sentence. P19 never fires; P20 gives `P20_OTHER_REASON`. |
| `recheck` / reuse | A plan with `panels` in `[N, N+2]` is reused and adopted. `story_checks.json` `panels_target` comes from `plan.json`. The resolver also needs the mode and the `story.md` count to match (SPC10, SPC13). |
| Re-check and render runs | `PANEL_COUNT_NOTE` repeats the saved P20 reason (SPC13 f). |
| `--force-story` | Always re-plans for target N. |
| `--redo` (shots) | Range-checked against the adopted count. |
| Manifest / render | No change; they follow `story.md` and the adopted `args.panels`. |
| movie UI | Queue and Run All are unchanged. Stills expected, the redo range, the `storyFields` fallback and the size note change (SPC14). "Regenerate story" takes an optional panel target (SPC16). |
| `bin/iterate-story` | Regenerates with `panels_target` (SPC15). |
| `--story-legacy` / `--story-prompt-override` | Exact count, no resolver, no adoption. A plan.json left next to their `story.md` is adopted only if its count equals the `story.md` count (D6). |

---

## 4. Tests

### 4.1 New: `tests/test_soft_panel_count.py`

**Conventions** (as `tests/test_shot_format.py`, [SF] 4.1):
- **Dependencies.** stdlib plus pytest.
- **Modules.** `story_engine.py`, `bin/ltx-movie`, `bin/iterate-story`, `bin/ltx-story-manifest` and `movie_ui_lib.py` are loaded by path with `importlib.machinery.SourceFileLoader`, under the names `story_engine_for_soft_count`, `ltx_movie_for_soft_count`, `iterate_story_for_soft_count`, `ltx_story_manifest_for_soft_count` and `movie_ui_lib_for_soft_count`.
- **Fixtures.** The autouse `story_env` and the `ws` fixtures come from `tests/story_engine_testutil.py` (`seu`).
- **The `movie` fixture.** It is copied from `tests/test_story_engine.py`, with `ltx_movie.WS` patched.
- **Module docstring.** It states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API.

**Helpers:**
- `HOCKEY`: the text of `tests/fixtures/narrative_fidelity/narrative.txt`, read and `.strip()`ped exactly as `tests/test_narrative_fidelity.py:186-187` does.
- `EIGHT = 'The courier says "Keep moving along the wet harbour road now." Then he says "The temple gate is close to us now." He says "Can you see the lanterns by the gate?" At the gate he says "We made it here before the rain came."'`
- `TURNS = 'Kyra says, "Go now." The ronin says, "Wait here." Kyra says, "Come on." The ronin says, "Not yet."'`. With members kyra and ronin (`seu.kyra`, `seu.ronin` via `story_env`), its declared speakers are `["c1", "c2", "c1", "c2"]`.
- `panel_script(mode, n)`: `tests/test_story_engine.py::_panel_script`, copied.
- `save_story(ws, story_id, mode, target, beats)`:
  1. `seu.script_agent` with the plan reply `seu.plan_json(mode, beats)` and `panel_script(mode, beats)`;
  2. `se.run(seu.make_ctx(se, ws, story_id=story_id, mode=mode, panels=target))`;
  3. assert rc 0;
  4. return the ctx.

| ID | Covers (exact assertions) |
|---|---|
| SPT1 | **Constants.** Each of these equals its SPC literal, written out in the test. From `se`: `PANELS_EXTRA == 2`, `LINES_RULE`, `LINES_PINNED_SENTENCE`, `PANEL_COUNT_RULE`, `PANEL_COUNT_MIN_CLAUSE`, `PANEL_COUNT_LINES_SENTENCE`, `ARC_COUNT_CLAUSES`, `P20_NOTE`, `P20_LINES_REASON`, `P20_SPEAKER_REASON`, `P20_EXIT_REASON`, `P20_OTHER_REASON`, `P19_NOTE`, `P19_ROOM_HINT`, `P19_CAP_HINT`, `SPEAKING_BEAT_SENTENCE`. From `ltx_movie`: `PANEL_COUNT_NOTE`, `PANEL_COUNT_PHASES`, `PANEL_COUNT_NO_REASON`, `DRY_PANELS_RANGE`, `DRY_PANELS_STORY`, `DRY_PANELS_STOP`. Also: `se.StoryContext._fields[-1] == "panels_target"`; `se.StoryContext._field_defaults == {"narration": True, "clip_seconds": None, "panels_target": None}`; `movie_ui_lib.PANELS_EXTRA == se.PANELS_EXTRA`; `movie_ui_lib.STORY_PANEL_RE.pattern == manifest._PANEL_HEADER_RE.pattern`; `"@@PANELS@@" not in se.PLAN_PROMPT_TEMPLATE`. Every P19 hint contains `"--force-story --panels %d"`. `/usr/bin/python3 -m py_compile` passes for `story_engine.py`, `bin/ltx-movie`, `bin/iterate-story` and `movie_ui_lib.py` when that interpreter exists (else skip) |
| SPT2 | **`target_panels`, `most_panels`, `panel_range`.** Rows (ctx → `(lo, hi)`): default `make_ctx` → `(3, 5)`; `panels=1` → `(1, 3)`; `panels=1, narrative=SIX_WORD_LINES` (written out from `tests/test_narrative_fidelity.py`) → `(2, 3)`; `panels=2, narrative=EIGHT` → `(4, 4)`; the same with `narration=False` → `(2, 4)`; `panels=5, panels_target=3` → `(3, 5)`, with `target_panels == 3` and `most_panels == 5`; `TURNS` uncast, `panels=1` → `(1, 3)`; `TURNS` with members kyra and ronin, `panels=2` → `(4, 4)`. Preconditions asserted: `len(se.spoken_lines(EIGHT)) == 4`, `se.panels_needed(lib, 6.0, se.spoken_lines(EIGHT)) == 4`, and `se.declared_speakers(<TURNS members ctx>) == ["c1", "c2", "c1", "c2"]` |
| SPT3 | **Pre-flight.** `spoken_lines_problem`: `EIGHT`, `panels=1` → the SPC3 example. `EIGHT`, `panels=2` → `None`. `SIX_WORD_LINES`, `panels=1` → `None`. `TURNS` with members, `panels=1` → `"the narrative quotes 4 spoken lines, which need at least 4 panels of 6 seconds (one panel has one speaker and speaks at most 14 words), but this movie has at most 3 (--panels 1 plus up to 2 more); rerun with --force-story --panels 2 or more, or with longer clips (a larger --frames)"`. The same ctx uncast → `None`. E2E: `se.run` of `EIGHT`, `panels=1` → rc 2; stderr is `"Error: " + <SPC3 example> + "\n"`; no agent call; run.json `exit == 2` |
| SPT4 | **Plan prompt.** (a) Uncast default, `panels=3`: contains the SPC4 example up to `"... at least one beat is climax."`. (b) `EIGHT`, `panels=2`: contains `"beats: a list of EXACTLY 4 objects"` and `"index runs from 1 to the number of beats. arc is one of"`, and does not contain `"target length"`. (c) `HOCKEY`, chained, `panels=2`, `"speech"`: contains `PANEL_COUNT_RULE % (2, "", 2, 4) + PANEL_COUNT_LINES_SENTENCE + " arc is one of"`, and contains `LINES_RULE.replace("@@LINE_WORDS@@", <line cap>).replace("@@MIN_BEATS@@", "2")`. (d) The same with `narration=False`: contains `PANEL_COUNT_RULE % (2, "", 2, 4) + " arc is one of"`. (e) `panels=1, narrative=SIX_WORD_LINES`: contains `PANEL_COUNT_RULE % (1, PANEL_COUNT_MIN_CLAUSE % 2, 2, 3)` and `"at least as many target beats (2) as lines"`. (f) Shots, members kyra only, a two-line narrative: contains `LINES_PINNED_SENTENCE`. (g) Shots `panels=3`: contains `se.CAMERA_RULE.replace("@@MAX_STATIC@@", "1")`. (h) No prompt contains `"@@"` or `"EXACTLY 3 objects"`. (i) The prompt with `TURNS` and members is byte-identical whether `build_plan_prompt` uses `declared_speakers` or the old inline mapping (assert the `LINE_SPEAKERS_SENTENCE` text `"line 1 to c1, line 2 to c2, line 3 to c1 and line 4 to c2"` is present) |
| SPT5 | **Arc rule.** `_plan_arc_rule` rows `(1, 3)`, `(2, 4)` and `(3, 5)` give the SPC5 table texts. `(4, 4)` gives `_arc_rule(4)`. `(2, 2)` gives `ARC_COUNT_CLAUSES[2] + "."` |
| SPT6 | **P1 and the range checks.** `plan_checks` on normalized `seu.plan_json("chained", n)`, ctx `panels=3`: for `n` in `(3, 4, 5)`, no P1, P5 or P6; `n=2` → hard contains `"plan: P1 beat count: expected 3 to 5 beats, found 2"`; `n=6` → `"... expected 3 to 5 beats, found 6"`. `EIGHT`, `panels=2`, 3 beats → `"plan: P1 beat count: expected exactly 4 beats, found 3"`. A 4-beat plan with beat 4 `index=7` → `"plan: P1 beat count: beat 4 has index 7; beats must be numbered 1 to 4 in order"`. `lora_checks` (catalog `fast-motion`) on a 5-beat plan with target 3: per_beat key `"5"` gives no L1; key `"6"` gives `"plan: L1 catalog id: per_beat key '6' is not a beat number from 1 to 5"` |
| SPT7 | **`normalize_plan`.** ctx `panels=3`, raw 4 beats: `plan["panels"] == 4`, `plan["panels_target"] == 3`, and `list(plan)[:6] == ["schema", "story_id", "mode", "panels", "panels_target", "seconds"]`. ctx `panels=4, panels_target=3` → `panels_target == 3` |
| SPT8 | **E2E, one beat added** (chained, uncast, `panels=3`, 4-beat plan, 4 panel replies) → rc 0. Agent stages begin `["plan", "panel", "panel", "panel", "panel"]`. `round_0/panel_04_prompt_1.txt` contains `"You are writing panel 4 of 4 "`. `story.md` parses to 4 panels. `plan.json` has `panels == 4`, `panels_target == 3`, and `speech_notes` contains `P20_NOTE % (4, 1, 3, P20_OTHER_REASON)`. `story_checks.json` has `panels == 4`, `panels_target == 3`, and that message exactly once. run.json has `panels == 4` and `panels_target == 3`. The returned advisories contain the message once. stdout contains `"\n" + <the message> + "\n"` before `"panel 1/4: call 1"` |
| SPT9 | **E2E, target met.** The same run with a 3-beat plan: `panels == panels_target == 3` in all three files, and no `" P20 "` in stdout, advisories or `speech_notes` |
| SPT10 | **E2E, out of range.** Two 6-beat plan replies, `panels=3` → rc 1. stderr line 2 is `"  - plan: P1 beat count: expected 3 to 5 beats, found 6"`. The retry prompt (`log[1]` argv) contains that line's message |
| SPT11 | **E2E, hockey exit** (chained, `panels=2`, `"speech"`, uncast). (a) A 3-beat plan: beat 1 speaker `c1`, lines `[1]`; beat 2 speaker `c1`, lines `[2]`; beat 3 speaker `""`, lines `[]`, action `"the hockey player skates away across the ice toward the far boards"`. With 3 panel replies → rc 0; exactly one P20, equal to `P20_NOTE % (3, 1, 2, P20_EXIT_REASON % "'skates away'")`; no P19. (b) A 2-beat plan with lines `[1]`, `[2]` → no P20, and exactly one P19, equal to `P19_NOTE % ("'skates away'", P19_ROOM_HINT % (4, 3))` |
| SPT12 | **`panel_count_notes` reasons** (normalized plans, no run). (a) `EIGHT`, `panels=3`, 4 beats of one line each → `[P20_NOTE % (4, 1, 3, P20_LINES_REASON % (4, 4, "6"))]`. (b) `HOCKEY`, `panels=1`, `clip_seconds=145 / 24.0`, 3 beats with lines `[1, 2]`, `[]`, `[]` → `[P20_NOTE % (3, 2, 1, P20_EXIT_REASON % "'skates away'")]`; `needed == 1`, as `test_nf5` pins for `hockey-2x145` at 1 panel. (c) `EIGHT + " He walks off."`, `panels=3`, 5 beats with lines `[1]`..`[4]`, `[]` → `[P20_NOTE % (5, 2, 3, P20_LINES_REASON % (4, 4, "6") + " and " + P20_EXIT_REASON % "'walks off'")]`. (d) `TURNS` with members, `panels=2`, 4 beats with speakers `c1, c2, c1, c2` and one line each → `[P20_NOTE % (4, 2, 2, P20_SPEAKER_REASON % (4, 4))]`. (e) A 3-beat plan for target 3 → `[]`. (f) `parse_violation(P20_NOTE % (4, 1, 3, "x"))` is `("P20", "panel count", "plan", None)` |
| SPT13 | **P19 hints** (`exit_left_out_notes`, `HOCKEY`, chained). Target 2, 2 beats, lines `[1]`, `[2]` → `[P19_NOTE % ("'skates away'", P19_ROOM_HINT % (4, 3))]`. Target 1, 3 beats, lines `[1]`, `[]`, `[2]` → `[P19_NOTE % ("'skates away'", P19_CAP_HINT % (3, 1, 4))]`. Target 2, 3 beats, lines `[1]`, `[2]`, `[]` → `[]`. Every [SF] SFT24 row holds when its expected string is rewritten as `P19_NOTE % (exit, P19_ROOM_HINT % (target + 2, beats + 1))` |
| SPT14 | **`load_plan` and `recheck`.** `save_story(ws, "s1", "chained", 3, 4)`. `load_plan` with ctx `panels` 2, 3 or 4 returns the plan; 1 or 5 → `None`; `"panels": True` → `None`. An old-style plan (no `panels_target`, `panels == 3`, 3 beats) loads for ctx `panels=3`. `se.recheck(ctx(panels=2), spy)`, where `spy` records `expected_panels` and returns `[]` → rc 0; spy saw `4`; `story_checks.json` has `panels == 4`, `panels_target == 3` (from plan.json, not 2) and `source == "recheck"`. With ctx `panels=1` → spy saw `1` (no plan adopted) |
| SPT15 | **`bin/ltx-movie` resolver.** In the `movie` workspace: `save_story(movie, "m1", "chained", 3, 4)`. Then `args = build_parser().parse_args([NARRATIVE, "--story-id", "m1", "--panels", P] + flags)` and `_resolve_story_panels(args)`. Rows (P, flags → `args.panels`, `args.panels_target`): `3, []` → `4, 3`; `2, []` → `4, 2`; `4, []` → `4, 4`; `1, []` → `1, 1`; `3, ["--force-story"]` → `3, 3`; `3, ["--story-legacy"]` → `3, 3`; `3, ["--shots"]` (mode mismatch) → `3, 3`. With `story.md` replaced by a 3-panel file (a stale plan) → `3, 3`. With no `story.md` → `3, 3`. **Shots story:** `save_story(movie, "m1s", "shots", 3, 4)`; `args` for `[NARRATIVE, "--story-id", "m1s", "--panels", "3", "--shots", "--redo", "4"]` after `_resolve_story_panels` → `_resolve_shots(args) == 0` and `args.redo_panels == [4]`; with `--redo 5` → 2, and stderr `"Error: --redo panel 5 is out of range (1..4)\n"` |
| SPT16 | **`bin/ltx-movie` adoption and downstream.** (a) `ltx_movie.main([NARRATIVE, "--story-id", "m2", "--panels", "3", "--story-only", "--no-review"])` with the fake agent scripted as in SPT8 → rc 0. stdout contains `"Warning: " + P20_NOTE % (4, 1, 3, P20_OTHER_REASON)`, then `PANEL_COUNT_NOTE % (4, 3, "because " + P20_OTHER_REASON)` with no `"; Phases 2-4"`. `story_prompt.txt` contains `"EXACTLY 4 panel sections"`. (b) Re-check path: build `args` as `tests/test_lora_catalog.py::_movie_args` does (`_resolve_shots`, `_resolve_casting`, `_resolve_global_loras`, `_resolve_story_engine`, each 0), with `_resolve_story_panels` first, for `[NARRATIVE, "--story-id", "m2", "--panels", "3", "--no-review"]`. Then `ltx_movie._phase1_robust(args) == 0`, `args.panels == 4`, and stdout has the note plus `PANEL_COUNT_PHASES % 4`. Then `_target_seconds(args) == 4 * 145 / 24.0`. (c) Catalog: build the story as `tests/test_lora_catalog.py::_catalog_story` (`:589-612`) does, with real fake files from `seu.lora_file` and `seu.catalog_entry`, so `bytes` match the files (`bin/ltx-movie:1517-1524`). It is a 4-beat chained story with target 3; its `plan.json` has `panels 4`, `panels_target 3`, `per_beat {"4": [fast-motion 0.7]}`, and its `story.md` has 4 panels. After adoption, `_catalog_panel_loras(args)` returns `(None, lists)` with `len(lists) == 4` and `lists[3]` starting with the fast-motion item. (d) Shots: `save_story(movie, "m2s", "shots", 3, 4)` plus adoption → `len(_shots_image_flags(args)) == 8`. (e) The same story with `--panels 4` prints no `PANEL_COUNT_NOTE` |
| SPT17 | **Dry run.** `bin/ltx-movie --dry-run` as a subprocess, as `test_rst47` runs it. `--panels 20`, no story: the Phase 1 block contains `DRY_PANELS_RANGE % (20, 20, 22)`, `--max-tokens` is `"5500"`, and the timeout is `880s`. `EIGHT` with `--panels 1` → a line starting `"Panel count: Phase 1 would stop: the narrative quotes 4 spoken lines"`. With the SPT15 `m1` story and `--panels 3` → `DRY_PANELS_STORY % (4, 3, 4)`. `test_rst47`'s assertions still hold |
| SPT18 | **Why adoption matters.** `bin/ltx-story-manifest --chain --prompts-md <4-panel story.md> --image <fake png> --fps 24 --min-frames 145 --max-frames 145 --pace equal --force --story-id x`. With `--target-seconds` `4*145/24` → rc 0 and 4 panels. With `3*145/24` → rc 2, and stderr contains `"not achievable"` |
| SPT19 | **[SF] interplay.** E2E, shots, `panels=3`, a 4-beat plan with every camera `static` → `plan.json` cameras `["slow push-in", "slow push-in", "static", "static"]` and notes `P18_NOTE % (1, 2, 4)` and `P18_NOTE % (2, 2, 4)`. The plan prompt contains `"so at most 1 in this movie"` |
| SPT20 | **movie UI.** `plan_panels(sdir, "chained")` → 4 on the SPT14 `s1` directory; `None` when: no plan.json; schema `"x"`; `panels` 0, `"4"` or `True`; mode `"shots"` asked; `story.md` with 3 headers. `effective_panels` rows (fields → result, using `s1` with mode chained): `panels 3` → 4; `panels 2` → 4; `panels 1` → 1; `panels 3`, mode shots → 3; `sdir None` → 3; `{"length": 30, "frames": 145, "fps": 24, "mode": "chained"}` with a 6-panel plan and story → 6 (resolved 5). `validate_fields` redo on a shots story directory with a 4-panel plan and `story.md`, fields `panels 3`: `redo=[4]` gives no range error; `redo=[5]` → `"redo panel 5 is out of range (1..4)"`. `ProgressParser("movie", {"mode": "shots", "panels": 3, "action": "movie", "seed_upload": None}).snapshot` in Phase 2 on that directory → `stills["expected"] == 4`. `index.html` contains `'id="c-size-note"'` and `"Panels is a target"`. `app.js` contains `"st.checks.panels_target || st.checks.panels"` |
| SPT21 | **iterate-story.** `build_engine_cmd("s", plan)` with `panels` 4 and `panels_target` 3 → the argv item after `"--panels"` is `"3"`; with no `panels_target` → `"4"` |
| SPT22 | **No server, no HOME.** `seu.script_agent` for every E2E. `os.path.expanduser("~")` is never the real HOME (`story_env`) |
| SPT23 | **`speaker_runs` and `lines_needed`.** `speaker_runs(["a", "b", "c", "d"], speakers)` rows: `[None] * 4` → `[["a", "b", "c", "d"]]`; `["c1", "c2", "c1", "c2"]` → four single runs; `["c1", None, "c1", "c2"]` → `[["a", "b", "c"], ["d"]]`; `[None, "c2", None, "c1"]` → `[["a", "b", "c"], ["d"]]`; `["c1", "c1", "c2", "c2"]` → `[["a", "b"], ["c", "d"]]`. `lines_needed(lib, 6.0, se.spoken_lines(TURNS), ["c1", "c2", "c1", "c2"]) == 4`, and with all `None` → 1 |
| SPT24 | **Range E2E with speakers.** `TURNS`, members, shots, `panels=2` (`lo == hi == 4`). A 3-beat plan replied twice → rc 1, with `"plan: P1 beat count: expected exactly 4 beats, found 3"`. A 4-beat plan (speakers `c1, c2, c1, c2`, one line each, cast = speaker) → rc 0, with P20 `P20_NOTE % (4, 2, 2, P20_SPEAKER_REASON % (4, 4))` |
| SPT25 | **`story_prompt.txt`.** After SPT16 (a), the file equals `build_story_prompt(NARRATIVE, "m2", 4, False, False, seconds=_clip_seconds(args), cast_block=None, shots=False)`. A run where the count equals the target leaves it with the target count. A re-check run never rewrites it (its mtime is unchanged) |
| SPT26 | **Regenerate argv** (`tests/test_movie_ui_builder.py` style: `_f` with `lib.compose_fields`, `PY`, `LTX`, `defaults` as in `test_mut1_golden_argv`). `lib.build_argv(_f(action="regenerate", panels=4, length=None), WS, STATE, py=PY) == base + ["--panels", "4"] + defaults + ["--force-story", "--story-only", "--no-review"]`. A story whose `last_fields` had `panels=None, length=30`, overridden with `panels=4, length=None`, gives the same argv: `--panels 4` and no `"--length"`. `lib.validate_fields(<those fields>, ws, state)` gives no panels error. With `panels=0` its errors contain `"panels must be an integer from 1 to 200"`, and with `panels=4, length=30` they contain `"give exactly one of panels or length"` (the existing V1 messages). An HTTP check in `tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv` style (`mt.api(s, "POST", "/api/preview", body=_compose(env, action="regenerate", panels=4))`) returns status 200, `errors == []`, and an argv containing `"--panels", "4"` and `"--force-story"` |
| SPT27 | **Static wiring** (in `tests/test_movie_ui_http.py` style, next to `test_regenerate_seed_field_is_wired_in_the_static_ui`, `:1141-1148`). `index.html` contains `'id="s-regen-panels"'`, `'min="1"'` and `"Panels (target)"`, and `html.index('id="s-regen-panels"') < html.index('id="s-regenerate"')`. `app.js` contains `'#s-regen-panels'`, `"with a target of "`, `"{panels: target, length: null}"` and `"res.data.last_fields.panels"` |

### 4.2 Existing tests and fixtures to re-baseline

**Rule (mandatory, as [SF] 4.2).**
- Run the full suite after [SF] lands, and again after G1-G5.
- Every outcome change must be explained by a code below and updated in G6. The G6 commit body has one paragraph per file.
- An unexplained failure is a defect in the code, not the test.
- No test is deleted, and no assertion is weakened beyond the new behaviour.

| Code | Cause |
|---|---|
| RB1 | Plan prompt count text (SPC4): `EXACTLY N` → `N to N+2`, `index runs from 1 to the number of beats.`, and the `PANEL_COUNT_RULE` insertion |
| RB2 | Arc rule for targets 1 and 2 (SPC5) |
| RB3 | P1 messages (SPC7) |
| RB4 | `plan.json` key order: `panels_target` after `panels` (SPC6) |
| RB5 | `story_checks.json` key order (SPC8) |
| RB6 | Pre-flight: no error at N+1 or N+2; new message text, including `--force-story` (SPC3) |
| RB7 | [SF] constants (SPC12): `SPEAKING_BEAT_SENTENCE`, `SPEAKER_RULE` and `SPEAKER_RULE_KEEP_CAST`; `P19_NOTE`'s second argument |
| RB8 | `--panels` help (SPC13 h) |
| RB9 | `LINES_RULE` and `LINES_PINNED_SENTENCE` text (SPC2) |

**Expected to change** (found by grepping the pinned wording at `6f16063`; the implementer confirms each by running the suite):

- **`tests/test_story_engine.py`**
  - `test_rst8_plan_prompt_matrix`:
    - `:260` → `"beats: a list of 14 to 16 objects"` (RB1);
    - `:269` and `:271` → the SPC5 target-2 and target-1 texts (RB2).
  - `test_rst9` `:281` → `"3 to 5 objects"` (RB1).
  - `test_rst13_normalization` `:309` → `["schema", "story_id", "mode", "panels", "panels_target", "seconds", "narrative", "goal", "seed_image", "video_model"]` (RB4).
  - `test_rst14_plan_checks` `:358` → `"plan: P1 beat count: expected 6 to 8 beats, found 5"`. `:359-360` keeps `numbered 1 to 6` (RB3).
  - `test_rst11_short_plan_is_fatal` `:1567-1568` → `"expected 6 to 8 beats, found 5"` (RB3).
  - `test_rst39_outputs_and_layout` `:1759` and `:1765` (RB4, RB5).
  - Whole-prompt byte comparisons (RB1, RB2, RB9).
- **`tests/test_narrative_fidelity.py`**
  - `PANELS_PROBLEM` and `test_nf5_spoken_lines_problem` (`SIX_WORD_LINES`, `panels=1` → `None`) (RB6).
  - `test_nf31_an_infeasible_line_set_exits_2_before_any_call` uses an `EIGHT`-style four-line narrative and the SPC3 text (RB6).
  - `:678` → `"... speaker and lines. index runs from 1 to the number of beats."` (RB1).
  - `test_nf12_the_plan_prompt` and the `SPEAKER_RULE`/`LINES_RULE` literals (RB7, RB9).
- **`tests/test_pinned_cast.py`**
  - `:384` → `"plan: P1 beat count: expected 3 to 5 beats, found 2"` (RB3).
  - `SPEAKER_RULE_KEEP_CAST`, `UNCHANGED`, `test_pt4_speaker_rule_variants` and `test_pt5_lines_sentence_variants` (RB7, RB9).
  - Plan-prompt fixtures `tests/fixtures/pinned_cast/uncast_shots_lines.txt`, `uncast_chained_seed.txt`, `uncast_chained_lines.txt` and any other `uncast_*.txt` plan prompt (RB1, RB2, RB7, RB9). Regenerate each from the new `build_plan_prompt` and diff it. The diff must be exactly the count text, the count rule, the arc rule (targets 1-2 only), the `LINES_RULE`/`LINES_PINNED_SENTENCE` text and the `SPEAKING_BEAT_SENTENCE` tail.
- **`tests/test_dialogue.py`**: `test_dlg12_plan_prompt_speaker_rule` (RB7).
- **`tests/test_speaker_attribution.py`**: plan-prompt tests, only if they compare whole prompt bytes or the `LINES_RULE` literal (RB1, RB9).
- **`tests/test_shot_format.py`** ([SF])
  - SFT1's `SPEAKING_BEAT_SENTENCE`, `SPEAKER_RULE` and `SPEAKER_RULE_KEEP_CAST` literals (RB7).
  - SFT24's expected strings → `P19_NOTE % (exit, P19_ROOM_HINT % (target + 2, beats + 1))` (RB7).
  - SFT25's suffix `"use --panels 3 to keep it"` → `"rerun with --force-story --panels 3 to keep it"` (RB7).
- **`tests/test_ltx_movie_offline.py`**: the L1 `--panels` help substring still holds (RB8 only if a check is byte-exact).
- **Must not change**
  - `test_mut16_stills_count_during_phase_2` (no plan.json);
  - `tests/test_movie_ui_checks.py:108` (no plan.json);
  - `tests/test_iterate_story.py` (no `panels_target`);
  - `test_rst47_robust_dry_run` (`--panels 4` gives `plan_max_tokens(6) == 4096` and `plan_timeout(6) == 600`; the new line follows the command line);
  - `test_rst46_review_gate` (count equals target, so no note);
  - `test_rst50b` (the opens are in the helpers).
- **`tests/test_movie_ui_builder.py::test_mut26`**: G7.

### 4.3 Must pass unchanged

- `tests/test_ltx_story_manifest_chain.py`
- `tests/test_ltx_mlx_render.py`
- `tests/test_ltx_story_images.py`
- `tests/test_character_lib.py`
- `tests/test_casting_regression.py`
- `tests/test_judge_story.py`
- `tests/test_judge_clips.py`
- `tests/test_lora_catalog.py`. Its `_catalog_story` plan has no `panels_target`, `panels 3` and a one-panel `story.md`, and it never goes through `_resolve_story_panels`.
- Every `se.run` E2E whose scripted plan has exactly `ctx.panels` beats, apart from RB1-RB5, RB7 and RB9.

---

## 5. Live acceptance (SPK10; this Mac only, story-only plus one render, post-merge, not a merge gate)

These run on this Mac only, never on macstudio or another host. The runner is whoever is authorized to start the local story server; the spec author ran nothing.

**Preconditions.**
- [SF] and this spec are merged into WS.
- No render is running: `pgrep -f ltx-mlx-render` prints nothing.

### 5.1 Setup and runs

- **Paths.** `W=$WS`. `R` is a new, empty output directory outside WS (for example `/private/tmp/claude-502/softcount-live`). Every narrative and goal comes from the repo:
  - `NH="$(cat $W/tests/fixtures/narrative_fidelity/narrative.txt)"`;
  - `NP` is `LINES_NARRATIVE`, copied from `tests/test_pinned_cast.py:66-69`;
  - `G` is the `goal` of `$W/tests/fixtures/writer_pacing/hockey-2x145-f/case.json`.
- **Story server.** Start it exactly as [SF] Section 5.1 starts it (vllm-metal `qwen38-6bit`, port 8177). Stop it with `bin/story-server stop` after the last story run and before the render.
- **Hockey flags.** `HK` is `--model ~/ltx-2-mlx/models/ltx-2.5-mlx-q8 --speech-only --goal "$G" --story-only --no-review --force-story`.
- **Running.** Every run starts from `$W`, logs to `$R/run-<id>.log`, then runs `echo "<id> exit $?"`.

| id | target | command |
|---|---|---|
| spc-hk2-a | 2 | `bin/ltx-movie "$NH" --panels 2 --frames 145 --story-id spc-hk2-a $HK` |
| spc-hk2-b | 2 | as spc-hk2-a with `--story-id spc-hk2-b` |
| spc-hk1-a | 1 | `bin/ltx-movie "$NH" --panels 1 --frames 241 --story-id spc-hk1-a $HK` |
| spc-hk1-b | 1 | as spc-hk1-a with `--story-id spc-hk1-b` |
| spc-hk3s | 3 | `bin/ltx-movie "$NH" --panels 3 --frames 145 --shots --story-id spc-hk3s $HK` |
| spc-ch3 | 3 | `bin/ltx-movie "$NP" --panels 3 --story-id spc-ch3 --character kyra --character ronin --speech-only --story-only --no-review --force-story` |
| spc-sh4 | 4 | as spc-ch3 with `--panels 4 --shots --story-id spc-sh4` |
| spc-sh2 | 2 | as spc-ch3 with `--panels 2 --shots --story-id spc-sh2` |
| spc-sil3 | 3 | `bin/ltx-movie "A courier carries a sealed letter across a rainy harbour town." --panels 3 --story-id spc-sil3 --no-narration --story-only --no-review --force-story` |

**Render** (one run, after `bin/story-server stop`):

`bin/ltx-movie "$NH" --panels 2 --frames 145 --story-id spc-hk2-a --model ~/ltx-2-mlx/models/ltx-2.5-mlx-q8 --speech-only --goal "$G" --no-review > $R/render-spc-hk2-a.log 2>&1`

It has no `--story-only` and no `--force-story`. Phase 1 re-checks and adopts the story's count, then Phases 2-4 render it.

### 5.2 Measure

Save this as `$R/measure_spc.py`. Run `W=$W R=$R python3 -I $R/measure_spc.py spc-hk2-a:2 spc-hk2-b:2 spc-hk1-a:1 spc-hk1-b:1 spc-hk3s:3 spc-ch3:3 spc-sh4:4 spc-sh2:2 spc-sil3:3 > $R/measure.txt`.

```python
import importlib.machinery, json, os, sys
W, R = os.environ["W"], os.environ["R"]
def load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(W, rel)).load_module()
se, lib = load("se_spc", "story_engine.py"), load("cl_spc", "character_lib.py")
man = load("man_spc", os.path.join("bin", "ltx-story-manifest"))
for arg in sys.argv[1:]:
    sid, target = arg.split(":")
    target = int(target)
    d = os.path.join(W, "generated", "stories", sid)
    run = json.load(open(os.path.join(d, "story_rounds", "run.json")))
    if run.get("exit") != 0:
        print(sid, "exit", run.get("exit"))
        continue
    plan = json.load(open(os.path.join(d, "plan.json")))
    panels = man._parse_prompts_md(os.path.join(d, "story.md"))[1]
    checks = json.load(open(os.path.join(d, "story_checks.json")))
    log = open(os.path.join(R, "run-%s.log" % sid), encoding="utf-8", errors="replace").read()
    n = len(plan["beats"])
    lines = plan.get("spoken_lines") or []
    said = [k for k, b in enumerate(plan["beats"], start=1) if len(lines) in b.get("lines", [])]
    found = se.narrative_exit_after_last_line(plan["narrative"]) if lines else None
    seq = []
    phrases = [c["phrase"] for c in plan["cast"] if c.get("phrase")]
    for p in panels:
        if p.get("dialogue", "").strip():
            phrase, line, _problem = lib.parse_dialogue(p["dialogue"], phrases)
            seq.append(((phrase or "").lower(), se.line_words(line)))
    want = se.line_speakers(plan["narrative"], plan["cast"])
    ok, pos = True, 0
    for i, spoken in enumerate(lines):
        t = se.line_words(spoken)
        who = se.speaker_phrase_of(plan, want[i]).lower() if want[i] else None
        while pos < len(seq) and not ((who is None or seq[pos][0] == who) and any(
                seq[pos][1][j:j + len(t)] == t for j in range(len(seq[pos][1]) - len(t) + 1))):
            pos += 1
        ok = ok and pos < len(seq)
    print(sid, "target", target, "plan.panels", plan["panels"], "beats", n, "story.md", len(panels),
          "panels_target", plan.get("panels_target"), "checks", checks.get("panels"),
          checks.get("panels_target"),
          "in_range", target <= n <= target + se.PANELS_EXTRA,
          "exit_words", found, "exit_beat", bool(found and said and said[0] < n),
          "P19", len([a for a in checks["advisory"] if a["id"] == "P19"]),
          "P20", len([a for a in checks["advisory"] if a["id"] == "P20"]),
          "P20_warned", log.count("Warning: plan: P20 "),
          "count_note", log.count("note: story.md has "),
          "static", sum(1 for b in plan["beats"] if b["camera"] == "static"),
          "static_cap", se.max_static(n), "lines_ok", ok)
```

**Render record.** Write these to `$R/render.txt`:
- the `manifest.json` panel count of `spc-hk2-a`;
- `plan.json` `panels`;
- the `panels: N` line of `$R/render-spc-hk2-a.log`;
- the count of `note: story.md has ` lines in that log, and the line itself;
- `ffprobe -v error -show_entries format=duration -of csv=p=0 $W/generated/stories/spc-hk2-a/movie.mp4`;
- the `images/` file names.

### 5.3 KPIs (gating for the live report)

| # | KPI | Target |
|---|---|---|
| L1 | Exit and range | All 9 story runs exit 0. For each: `plan.panels == beats == story.md` count; `in_range True`; `panels_target == target`; `checks == (plan.panels, target)` |
| L2 | Hockey exit filmed | `exit_beat True` in at least 3 of `spc-hk2-a`, `spc-hk2-b`, `spc-hk1-a` and `spc-hk1-b`. `P19 0` in every run with `exit_beat True` |
| L3 | The user is told, with the reason | Story runs: when `plan.panels != target`, `P20 == 1`, `P20_warned >= 1` and `count_note == 1`, and the note line contains `(because `. Otherwise all three counts are 0. **Render log:** when `spc-hk2-a` has `plan.panels != target`, `$R/render-spc-hk2-a.log` has exactly one `note: story.md has ` line, containing the same `because ...` text as that story's P20 and ending `; Phases 2-4 use all <plan.panels>`. Otherwise it has none |
| L4 | No inflation | At most 1 of `spc-ch3`, `spc-sh4` and `spc-sil3` has `plan.panels > target`, and none has `target + 2` |
| L5 | Lines | `lines_ok True` for every run with spoken lines |
| L6 | Static cap (D9) | `static <= static_cap` for every run |
| L7 | Render uses the effective count | `spc-hk2-a`: manifest panels == `plan.panels` == the `panels: N` line. The movie duration is within 0.25 s of `plan.panels * 145 / 24`. `images/` holds `panel_01.png` only |

**Recorded, not gating:**
- `plan.panels - target` for each run;
- the P20 reasons;
- for L2 misses, the P19 text;
- the plan and panel call counts.

---

## 6. Rollout

1. **Snapshot** (house rule). `tar czf <scratchpad>/snapshot-pre-soft-panels-<sha>.tgz -C /Users/reubenpatterson/local_agent_harness --exclude 'qwen-agent-workspace/generated' qwen-agent-workspace`, where `<sha>` is WS HEAD after [SF] lands. Record the full-suite pass count and the pre-existing failures.
2. **Implement** in a git worktree of `qwen-agent-redteam` at that HEAD.
   - Commit 1 (feature): G1-G5.
   - Commit 2 (tests only): G6, with the Section 4.2 explanations.
   - Commit 3 (tests only): G7.
   - Run SPK1-SPK2.
3. **Review.** An Opus design review of the diff against this spec. Fix what it finds, then re-run SPK1.
4. **Merge.** Fast-forward WS.
5. **Live.** Run Section 5, then report L1-L7 with `measure.txt` and `render.txt`.

**PR note (required, in substance).**

> `--panels` is now a target. The story planner may use up to 2 more panels when the narrative needs them, and never fewer. Examples: an exit after the last line, a spoken line that cannot share a panel, or a change of speaker.
>
> The warning `plan: P20 panel count: ...` says when and why, and every later run of the story prints `note: story.md has N panels for a target of T (because ...)`.
>
> Stills, the manifest, the render, `--redo`, `story_prompt.txt` and the movie UI follow the story's real panel count. Existing stories re-check as before. `--story-legacy` keeps an exact count.

---

## 7. Values chosen by the spec

1. `PANELS_EXTRA = 2`, with no flag (SPC1).
2. The effective count is carried in `ctx.panels` after a ctx swap; the target is in `panels_target` (D1).
3. Range bounds (D2, SPC3):
   - `lo = max(N, lines_needed)`, where `lines_needed` uses speaker runs from the declared members;
   - `hi = N + 2`;
   - the pre-flight hint is `--force-story --panels needed-2`.
4. Planner wording (D3, SPC2, SPC4):
   - prefer `lo`, and add only for something no other beat can hold;
   - the lines sentence;
   - `LINES_RULE` tied to `@@MIN_BEATS@@`, with one speaker for shared lines;
   - `LINES_PINNED_SENTENCE` adds a beat when allowed.
5. The arc rule lists the clause for each beat count up to 3 for targets 1-2 (SPC5).
6. `plan.json` `panels` is the beat count, plus `panels_target`. The same fields go into `story_checks.json` and run.json. The schemas stay `v1`. Recheck's `panels_target` comes from `plan.json` (SPC6, SPC8, SPC9, SPC10).
7. The P20 reasons are deterministic: words, speakers, exit, or a generic fallback (D4, SPC11).
8. P19 is never retried and gives a room or cap hint. Every count hint names `--force-story` (D5, SPC12).
9. Plan reuse accepts `[N, N+2]`. The resolver and the movie UI also require a matching mode and `story.md` count (D6).
10. `bin/ltx-movie` adopts the count before and after Phase 1, and prints the saved reason on every run (D7).
11. Budgets: the plan call and the initial cap use N+2; the cap is reset after the plan (D8).
12. `@@MAX_STATIC@@` uses the target and P18 the effective count. `@@PANELS@@` is removed from the plan prompt (D9, SPC4).
13. The same rule applies in every mode (D10).
14. The movie UI gets four changes, with `PANELS_EXTRA` and the header regex repeated and pinned (D11).
15. `story_prompt.txt` is rewritten with the effective count after a generate run (D12).
16. `bin/iterate-story` uses `panels_target` (SPC15).
17. "Regenerate story" takes an optional panel target; empty keeps the original sizing (SPC16).
18. Live: 9 story runs plus one render (Section 5).

---

## 8. Risks and questions

### 8.1 Risks

- **R1. Inflation.** Mitigations: the prompt prefers the target, P20 shows every addition, and L4 measures it. A follow-up could make `P20_OTHER_REASON` hard. That is not done here.
- **R2. The planner keeps the exit out despite room.** P19 tells the user and gives the hint. L2 measures it.
- **R3. Longer renders.** Each added panel costs one more clip, and in shots mode one more still.
- **R4. Prompt length.** About 80 more plan-prompt tokens, which is negligible.
- **R5. Re-baselining.** Plan-prompt fixtures change in several files. The fixture-diff rule of Section 4.2 keeps each change auditable.
- **R6. Speaker runs use declared members only.** A narrative whose alternating speakers are all invented can get a too-low `lo`. If its plan gives two speakers' lines to one beat, the plan then fails P17 or Q1 as it does today. P20 still reports the speaker reason when the planner added beats.

### 8.2 Decisions to confirm (the brief did not settle these)

- **C1. Lower bound.** It rises to `lines_needed`, one speaker per panel, from declared speakers. A story whose lines need N+1 or N+2 panels is then planned automatically instead of exiting 2 (D2).
- **C2. The P20 reason.** It is deterministic (words, speakers, exit, or generic), not written by the planner (D4).
- **C3. P19.** It is not retried. Its hints distinguish room left from cap reached, and both say `rerun with --force-story --panels N` (D5).
- **C4. Plan reuse.** Any saved count inside the target's range is reused, not only an exact `panels_target` match. The resolver and the UI also need the mode and the `story.md` count to match (D6).
- **C5. `plan.json` `panels`.** It changes meaning to the effective count; `panels_target` is new (also in `story_checks.json` and run.json). The schemas stay `v1`.
- **C6. `--length`.** It is a target too, so a movie may be up to 2 clips longer.
- **C7. The legacy engine.** It keeps an exact count.
- **C8. Static caps.** `@@MAX_STATIC@@` uses the target (stricter), and P18 the effective count.
- **C9. The movie UI.** It gets four changes, including a static size note.
- **C10. `bin/iterate-story`.** It regenerates with the target.
- **C11. [SF]'s wording.** [SF]'s `SPEAKING_BEAT_SENTENCE` tail is reworded. SF-A1's hint gets the same `--force-story` wording (the coordinator patches the [SF] text).
- **C12. Out-of-range reruns.** A rerun whose range excludes the saved story's count keeps today's exact-count error.
- **C13 (flag for the user).** Because of C4, a **lower** `--panels` now reuses a **bigger** saved story when the story's count is inside the lower target's range. Example: `--panels 2` on a saved 4-panel story reuses it, where `6f16063` errors with `expected exactly 2 panels, found 4`.
- **C14. `LINES_RULE` and `LINES_PINNED_SENTENCE`.** Both are reworded (SPC2): shared lines need one character, the lines tie to the `lo` target, and a pinned character's beat is added when allowed.
- **C15. `story_prompt.txt`.** It is rewritten with the effective count after a generate run, rather than the mismatch being documented (D12).
- **C16 (user-approved).** "Regenerate story" gets an optional "Panels (target)" input (SPC16). Empty keeps the original sizing; a value N sends `panels: N, length: null` through the existing V1 validation, with no new server field.

### 8.3 Open

None, beyond confirming C1-C15. C16 is user-approved.
