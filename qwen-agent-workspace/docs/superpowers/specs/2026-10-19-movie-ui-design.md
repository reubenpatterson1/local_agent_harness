# qwen-agent harness -- Design Spec (movie UI, piece F, with the release-prune fix)

Date: 2026-10-19
Status: The user approved every design decision of piece F on 2026-10-19 in four sections: Section 1 (stdlib `ThreadingHTTPServer` on 127.0.0.1:8999 only, one instance per host, per-launch token, HTTP hardening, the host-wide STATE directory, detached job runners with on-disk state that survive a server restart, the single heavy-job FIFO queue, one command builder, the Select Stories Directory option that always defaults to `current`, version-aware forms); Section 2 (the single page and its six tabs, including the Trace Viewer); Section 3 (the JSON API, validation checks V1-V7, progress parsing); Section 4 (the release-prune fix that ships alongside F, the test plan, the rollout). This document writes those decisions down precisely enough to implement without reopening any. Every value they left open is marked **[spec choice]** and collected in Section 17. Where the shipped code contradicts the brief, the code wins and Section 18 records the discrepancy; Section 19 lists the questions the user must answer before implementation starts. Section 20 lists the amendments of 2026-10-20 that bring the spec in line with the rulings accepted during implementation.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`. `WS` is `qwen-agent-workspace/`; relative paths are relative to `WS`. Line numbers cite commit `22dc4a1`: `bin/ltx-movie` (2338 lines), `bin/ltx-mlx-render` (1382), `bin/character` (106), `bin/lora-catalog` (260), `bin/story-server` (692), `bin/qwen-agentd` (1877), `fleet_lib.py` (1936), `lora_catalog.py` (416), `character_lib.py` (1140), `character_dataset.py`, `ltx2_mlx_video_skill.py` (445), `z_image_skill.py` (242), `pipeline_log.py` (111).

Specs this one builds on (treated as implemented, cited by tag):

- **[FLEET]** `docs/superpowers/specs/2026-10-16-fleet-discovery-self-update-design.md` (F82 `release_version`, F86 unstage, F88a pruning).
- **[MULTI]** `docs/superpowers/specs/2026-10-17-fleet-multi-agent-hosts-design.md` (M2 `A(<id>)`, M7 ports, M8-M12 wrappers and the default agent, M24 `agent_port`, M30 status port).
- **[PREP]** `docs/superpowers/specs/2026-10-17-fleet-host-prep-design.md` (the host-wide `~/.local/share/qwen-agent/` base).
- **[TRACE]** `docs/superpowers/specs/2026-10-17-fleet-tracing-design.md` (TR4 record, TR17 tree, TR27 `/trace?id=`, TR28 `/traces/recent`, TR50 nothing secret in a trace).
- **[STORY]** `docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md` (2.2 `plan.json`, 2.5 `story_checks.json`, 2.8 `catalog_loras.json`, LC1-LC20 the catalog).
- **[CAST]** `docs/superpowers/specs/2026-10-05-character-library-design.md`; **[SHOTS]** `docs/superpowers/specs/2026-10-06-shots-mode-design.md`.

This spec edits no other spec file.

ID conventions: `MU<n>` is a movie-UI requirement (MU48-MU51 are unused; MU36 and MU52 sit in the section their subject belongs to), `MP<n>` a prune-fix requirement, `GC<n>` a global constraint, `MUT<n>`/`MPT<n>` a test, `MUK<n>` a success criterion, `MUR<n>` a rollout step, `MUX<n>` an accepted risk, `D<n>` a discrepancy with the brief, `Q<n>` an open question. `V1`-`V7` are the approved validation checks. None clashes with F, T, K, R, M, MT, P, H, S, V(T/K/R), TR, TRT, RS, LC.

---

## 0. Purpose and scope

### 0.1 Purpose

Today every movie, character and LoRA operation is a long command line typed into a terminal, and a render's progress is a scrolling log. Piece F adds `bin/movie-ui`, a locally hosted page that builds those command lines from forms, validates models, LoRAs and characters before any GPU time is spent, runs the commands as detached, queued jobs whose progress the page tracks, edits `story.md` between the story stage and the render, and shows fleet traces (piece D) as formatted waterfalls. Alongside it, the release-prune fix stops self-update from deleting older releases whose `generated/` directory holds stories, characters or catalogs.

### 0.2 Grounding (shipped code)

**`bin/ltx-movie`.** `WS` is the file's own workspace (`:118`). `build_parser` (`:280-457`): positional `narrative` (`nargs="?"`, `:292-294`), `--story-id` (required, `:295`), `--seed-image` (`:296-303`), `--panels` default 15 (`:304-306`), `--length` (`:307-310`), `--fps` 24 (`:311`), `--frames` 145 (`:312-314`), `--video-width/--video-height` (`:316-317`), `--model` default `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8` (`:318`), `--gemma` default `mlx-community/gemma-3-12b-it-4bit` (`:319-323`), `--lora` and `--stills-lora` repeatable `PATH[:STRENGTH]` (`:324-337`), `--character` (`:338-345`), `--shots` (`:360-367`), `--redo` (`:368-372`), `--story-model` (`:373-382`), `--no-low-ram` (`:395-398`), `--panel-timeout` default 7200 (`:406`), `--no-stills` (`:407-412`), `--no-review` (`:413`), `--force-story` (`:414`), `--force` (`:421`, "only ever means overwrite movie.mp4", `:517`), `--story-only` (`:435-441`), `--dry-run` (`:442`), `--story-legacy` (`:443-446`), `--no-auto-lora` (`:447-449`), `--judge` (`:450-453`), `--goal` (`:454-456`, parsed by `_parse_goal` `:262-277`: strip, drop one trailing `.`, non-empty, single line, at most `GOAL_MAX_CHARS = 300`). `main` (`:2233-2329`): a narrative or `--story-prompt-override` is required (`:2242-2243`); geometry defaults 704x448, multiples of 64 (`:2245-2260`); `--seed-image` excludes `--video-width/--video-height` (`:2246-2250`) and `--no-stills` (`:2263-2267`); `_resolve_shots` refuses `--shots` with `--no-stills` or `--seed-image`, and `--redo` without `--shots`, with `--force-story` or `--story-only`, out of range, or without `story.md` (`:920-966`); `_resolve_story_engine` refuses `--judge`, `--no-auto-lora`, `--goal` with `--story-legacy` and `--judge` without `ANTHROPIC_API_KEY` (`:883-917`); `--dry-run` returns `_print_dry_run_plan` before any story lock (`:2287-2288`); a review gate without a TTY exits 2 "review gates require an interactive terminal" unless `--no-review` (`:2313-2317`). Story paths (`_story_paths`, `:569-582`): `generated/stories/<id>/` (`_story_dir` `:565-566`, the brief's `:566`) holding `story.md`, `images/` (`panel_NN.png`), `manifest.json`, `movie.mp4`, `movie.log`, `.movie.lock`, `seed_downscaled.png`; plus `clips/panel_NN.mp4` (`:1780-1785`), `plan.json` and `story_checks.json` (`story_engine.py:2267-2268`), `story_rounds/` (`story_engine.py:1933`), `catalog_loras.json` (`:1418-1421`), `runs/<run>/story_summary.json` (`:1936-1939`), `redo/<stamp>-<pid>/` (`:1776-1790`), `iterate-story.log` (`pipeline_log.py:17`). Phase banners: `=== Phase 0: seed image ===` (`:1054`), `=== Phase 1: story ===` (`:1133`, `:1436`), `=== Phase 1: story (rewrite %d of %d) ===` (`:1595`), `=== Phase 2: stills ===` (`:1645`), `=== Phase 1b: release the story server ===` (`:1763`), `=== Redo: panels %s ===` (`:1799`), `=== Phase 3: manifest + dry-run ===` (`:1833`), `=== render summary (%s) ===` (`:1952`), `=== Phase 4: render ===` (`:1969`). Phase 4 refuses an existing `movie.mp4` without `--force` (`:1970-1972`). An existing `story.md` without `--force-story` is re-checked (robust engine, `:1430-1433`, no model call: `story_engine.recheck` `:2407`) or skipped (legacy, `:1129-1131`). `_phase_sequence` (`:2212-2230`). Chained Phase 2 renders only panel 1's still (`--only 1`, `:2149`). `_print_dry_run_plan` (`:2072-2209`) spawns no subprocess. `pipeline_log.run_logged` appends a record to `<story_dir>/iterate-story.log` whenever the story directory exists, unless `STORY_PIPELINE_LOGGED` is set (`pipeline_log.py:83-111`, `bin/ltx-movie:2332-2338`). `ltx-movie` installs no signal handler.

**`bin/ltx-mlx-render`.** `build_parser` (`:98-145`): `MANIFEST OUTPUT_MP4`, `--frames`, `--width`, `--height`, `--frame-rate`, `--model`, `--gemma`, `--lora` (repeatable), `--no-low-ram`, `--panel-timeout`, `--clips-dir` ("default: <story_dir>/clips"), `--resume`, `--force`. `load_manifest` (`:175-263`): non-empty `panels`, `index` contiguous from 1, `image_path` null or a readable file, schema 3 needs `conditioning` in `still|chain|t2v` (t2v needs `image_path` null), non-empty `panel_text`. `story_dir` comes from `manifest["story_id"]` (default `"story"`), never from the manifest path (`:1185-1187`); the run root is always `<story_dir>/runs/<run_id>/` (`:1267-1268`). Geometry: multiples of 64, frames on the 8k+1 lattice, at least 9 (`ltx2_mlx_video_skill.validate_geometry`, `:85-108`). Progress lines: `panels: %d` (`:807`, printed by the `--dry-run` plan only), `=== panel %d/%d (%s) ===` (`:1298`), `panel %d: reusing %s (--resume)` (`:1288`), `panel %d ok: %s (%.1fs)` (`:974`), `panel %d FAILED (<reason>): <detail>` on stderr (`:924`, `:940`, `:946`, `:968`, `:1304`, `:1315`). Every catalog motion/physics LoRA is placed ahead of the globals (`build_units` `:349-360`).

**`ltx2_mlx_video_skill.py`.** `LTX2_MLX_DIR` (env, default `~/ltx-2-mlx`, `:44`), `LTX2_MLX_BIN` (env, default `<dir>/.venv/bin/ltx-2-mlx`, `:45-46`), `LTX2_MLX_HF_HOME` (env, default `<dir>/hf_cache`, `:47-48`), `MODEL_ID`/`GEMMA_MODEL_ID` (`:50-51`), `parse_lora_spec` (`:111-127`, strength in (0, 2]), `_resolve_bin` (`:130-139`). The `ltx-2-mlx` child runs with `HF_HOME=LTX2_MLX_HF_HOME` **in its own session** (`start_new_session=True`, `:338-341`).

**`z_image_skill.py`.** Imports `torch`, `diffusers.ZImagePipeline`, `ZImageTransformer2DModel`, `transformers.Qwen3Model` at top level (`:46-48`); `BASE_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"`, `TEXT_ENCODER_ID = "BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1"` (`:52-53`); `_z_image_hf_home` (`Z_IMAGE_HF_HOME`, default `~/hf_home`, `:56-59`); `_cache_dir_for` uses `<scoped>/hub` only when `hub/models--<org>--<name>` exists, else the default HF cache (`:62-69`).

**`bin/lora-catalog`.** `list [--model M] [--json]` prints `{"catalog": <path>, "entries": [...], "characters": [...]}` (`:176-177`); entries carry `lora_catalog.ENTRY_KEYS` (`lora_catalog.py:36-38`): `id, kind, path, sha256, bytes, base_models, target, triggers, rank, alpha, default_strength, strength_range, description, use_when, avoid_when, added_at`; folded characters have `id "char:<name>"`, `kind "character"`, `strength_range null` (`lora_catalog.py:299-318`). `--model` filters with `compatible()` (exact string, or both absolute with the same realpath; `lora_catalog.py:343-352`). `verify [ID ...]` prints `OK <id>` / `FAIL <id>: <problem>` lines and `verified N entr(y|ies): P problem(s)`, exit 1 on problems, 2 on an unknown ID (`:218-249`). `add` flags (`:37-52`), `remove ID` (`:193-215`). `STILLS_BASE_MODEL = "Tongyi-MAI/Z-Image-Turbo"` (`lora_catalog.py:29`). `catalog_dir(ws)` honours `LORA_CATALOG_DIR` (`lora_catalog.py:66-67`).

**`bin/character`.** `create NAME --phrase P (--seed-image PATH | --descriptor TEXT --class NOUN) [--trigger W] [--seed N] [--force]`, `create NAME --regenerate`, `train NAME [--video] [--stills] [--force]`, `list`, `show NAME` (`:37-61`). `show` prints the character JSON (indent 2) **followed by a `files:` block** of `  ok       <path>` / `  MISSING  <path>` lines (`:70-91`). `list` prints `LIST_ROW_FORMAT = "%-16s %-16s %-9s %-5s %-6s %s"` rows `NAME TRIGGER STATUS VIDEO STILLS PHRASE`, `%-16s (invalid: <e>)` rows, or `no characters in <dir>` (`character_lib.py:1123-1140`). Names `[a-z][a-z0-9-]{1,23}`, triggers `[a-z][a-z0-9]{3,15}`, class nouns `[a-z]{3,12}` (`character_lib.py:30-32`). `library_dir()` honours `CHARACTER_LIBRARY_DIR`, else `<WS>/generated/characters` (`character_lib.py:249-250`). Dataset: `<lib>/<name>/dataset/{stills/char_NN.png, captions, videos, manifest.json, contact_sheet.jpg}` (`character_dataset.py:656-663`, `:739-740`). The face check refuses with `Error: ` + one of two texts and exit 2 **before** the character directory is created (`character_dataset.py:771-781`, `:882-887`, `_error` `:542-544`; directories are made at `:900-901`). A create that keeps fewer than 12 stills exits 3 (`:758-764`). `create` needs the vision model served (`:872-874`); `train` needs the story server `STOPPED` (`:1137-1140`). Training subprocesses also run in their own sessions (`run_logged`, `:495-532`). The video LoRA's `base_model` is always `TRAIN_MODEL_DIR = <LTX2_MLX_DIR>/models/ltx-2.3-mlx-q8-dev`, a local path (`:134`, `:1075`); the stills LoRA's is `Tongyi-MAI/Z-Image-Turbo` (`:1348`).

**`bin/story-server`** (bash). `status` prints `  state:          <SERVING <mode>|FOREIGN pid N|LOADING <mode>|STOPPED>` and exits 0 (`:484-555`); exits 4 when `/usr/sbin/lsof`, `/usr/bin/python3` or `/usr/bin/curl` is missing (`:668-678`), 2 on usage (`:655-660`). `character_dataset._STATE_RE = ^\s*state:\s*(.+?)\s*$` parses it (`:357`).

**`fleet_lib.py`.** `DEFAULT_PORT = 8190` (`:28`), `KEEP_RELEASES = 3` (`:52`), `WS_SUBDIR` (`:75`), `AGENTS_DIR` (`:77`), `TRACE_*` constants (`:94-118`, `TRACE_FANOUT_DEADLINE = 6`, `TRACE_QUERY_TIMEOUT = 20`, `TRACE_RECENT_MAX = 100`, `TRACE_KINDS`), `read_state` (`:1074-1081`), `releases_to_prune` (`:1096-1103`), `tag_key`, `agent_ids_on_disk` (`:1221-1235`), `agent_port` (`:1259-1287`), `default_command_path` (`:1216-1218`), `classify_command_path` (`:1327-1345`), trace record keys (`:1418-1430`), `valid_trace_id`, `valid_trace_result` (`:1564-1583`), `valid_recent_result` (`:1594-1613`), `fetch_trace`/`fetch_recent` (`http.client` loopback GETs with no `Origin`; errors `daemon not reachable at <url>`, `the daemon at <url> has no trace support (http N)`, `... answered http N`, `... returned an unrecognized trace response`; `:1636-1671`), `render_trace` (`:1866-1926`). Imports stdlib only (`:14-25`).

**`bin/qwen-agentd`.** `REPO_ROOT` is the workspace (`:50`). `_loopback_request_ok` (`:346-358`): `Host` must be `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`, no `Origin`, POST needs JSON. `_confirm_switch` (`:1213-1220`) prunes with `releases_to_prune` and `unstage_release` (`:1471-1484`: `git worktree unlock`, `remove -f -f`, `shutil.rmtree`, `prune`). `_status_port` (`:1303-1322`) reads `A(<id>)/current/qwen-agent-workspace/fleets` (else `REPO_ROOT/fleets`); `cmd_status` prints `daemon: not reachable at <url>` (`:1343`). `cmd_trace` writes `"\n".join(fleet_lib.render_trace(result)) + "\n"` (`:1426`). `state_path(d)` is `d/update-state.json` (`:1462-1463`). `qwen-agent-workspace/.gitignore:2` ignores `generated/`; no file under it is tracked.

**Tests.** `tests/conftest.py` sets `LORA_CATALOG_DIR` to a temp directory for every test (autouse). `tests/test_fleet_lib.py:1048-1053` pins today's `releases_to_prune`. `tests/test_fleet_self_update.py:352` (`test_t60_switch_gate_failure_and_crash_rollback`) is the pattern for a switch test.

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `bin/movie-ui` (new, executable) | CLI entry: arguments, STATE, server lock, bind, startup recovery, threads, serve (Section 2) |
| G2 | `bin/movie-ui-job` (new, executable) | the detached job runner (Section 5) |
| G3 | `movie_ui_lib.py` (new) | constants, STATE paths, atomic writes, job store, queue, runner core, command builder, field rules, checks V1-V7, help parser, HF cache checks, progress parser, workspace discovery (Sections 3-9) |
| G4 | `movie_ui_server.py` (new) | HTTP handler, route table, hardening, API endpoints, `/files`, dispatcher thread, capability probe, trace proxy (Sections 3, 10, 11) |
| G5 | `static/movie-ui/index.html`, `app.js`, `app.css` (new) | the page (Section 12) |
| G6 | `tests/movie_ui_testutil.py` (new) and `tests/fixtures/movie_ui/` (new) | stub workspace, fake daemon, canned outputs (Section 14.2) |
| G7 | `tests/test_movie_ui_builder.py`, `test_movie_ui_checks.py`, `test_movie_ui_jobs.py`, `test_movie_ui_progress.py`, `test_movie_ui_http.py`, `test_movie_ui_traces.py` (new) | MUT1-MUT26 |
| G8 | `fleet_lib.py` | `release_holds_data`; `releases_to_prune(..., protected=())` (MP1, MP2) |
| G9 | `bin/qwen-agentd` | `_confirm_switch` protects data-holding releases and logs them (MP3) |
| G10 | `tests/test_fleet_lib.py`, `tests/test_fleet_self_update.py` | MPT1-MPT3 (additions only) |

No other file changes. In particular these pipeline files have a zero diff: `bin/ltx-movie`, `bin/ltx-mlx-render`, `bin/ltx-story-images`, `bin/ltx-story-manifest`, `bin/ltx-story-video`, `bin/ltx-chain`, `bin/ltx-generate`, `bin/ltx-host-prep`, `bin/ltx-host-restore`, `bin/character`, `bin/lora-catalog`, `bin/judge-story`, `bin/judge-clips`, `bin/judge-stills`, `bin/iterate-story`, `bin/qwen-agent`, `story_engine.py`, `character_lib.py`, `character_dataset.py`, `lora_catalog.py`, `pipeline_log.py`, `z_image_skill.py`, `ltx2_mlx_video_skill.py`. (`character_dataset.py` is added to the brief's list **[spec choice: it is the library `bin/character` drives; F must not change it either]**.)

### 0.4 Goals and non-goals

Goals:

1. Create characters through their whole lifecycle (create, dataset review, accept/regenerate/force, train video and/or stills, castable).
2. Select and validate models and LoRAs: present and intact, compatible (including the pipeline's own `--dry-run`), optional smoke render.
3. Compose a movie from structured fields (panels or seconds, mode, models, LoRAs, cast), preview the exact command, write the story first, edit `story.md` in the page, then render; track progress.
4. Queue heavy jobs (one at a time), reorder and cancel them; jobs survive a server restart.
5. Work against any harness workspace the user selects (any installed release, `current` by default).
6. View, save and download fleet traces.
7. Keep data-holding releases when self-update prunes.

Non-goals: see Section 16.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| MUK1 | Every MUT and MPT test passes under `python3` (3.13); under `/usr/bin/python3` (3.9.6) every new or changed file compiles (`py_compile`, MUT25) and the runtime smoke passes (`bin/movie-ui` started under 3.9 from a copied UI with stub tools runs a story job to `done` through the 3.9 dispatcher and `bin/movie-ui-job`, then stops on SIGTERM). The suite is not run under 3.9: that would need pytest installed into the system interpreter, a host change the user did not ask for (amended 2026-10-20: ledger ruling MUK1 and plan decision 24 — 3.9 coverage is py_compile plus the runtime smoke, not pytest under 3.9) | MUT25, the 3.9 runtime smoke, a suite run under 3.13 |
| MUK2 | `python3 -m pytest tests/ -q -rA` from `WS` shows no new failure against the baseline: exactly 1 pre-existing failure (`tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike`) and 1 skip, plus every new test passing | full-suite run |
| MUK3 | `git diff --quiet 22dc4a1 -- <every pipeline file of 0.3>` exits 0 | MUT26 |
| MUK4 | A cancelled running job leaves no process of its tree (its process group and every process group of its descendants, D1) within `CANCEL_GRACE_S` + 2 s of the cancel request when `ps` answers promptly (typically about 16 s at the default 15 s grace). The worst case is the marker poll (1 s, MU22 step 6) + the `ps` timeout (5 s, MU23 step 1) + the grace (15 s) + the SIGKILL (amended 2026-10-20: final review item 9 / Task 3 parked m3 — the flat 16 s bound ignored marker latency and the `ps` timeout) | MUT11 |
| MUK5 | After a server restart, 100% of jobs whose runner is alive are reported `running` again, and every job whose runner died is reported `lost` | MUT13 |
| MUK6 | No `/api/*` route answers anything but 401, or 403 for a bad Host/Origin (MU10 steps 1-2), without the correct token (amended 2026-10-20: final review item 10 — Host and Origin are checked before the token, so a bad one answers 403 first) | MUT18 |
| MUK7 | Standard library only; no `cgi`, no `urllib`, no `shell=True`, no `match` statement, no `X \| Y` annotation in any new file | MUT25 |
| MUK8 | The Playwright E2E scenario of MUT27 passes and a screenshot is shown to the user | MUT27 |

### 0.6 Must-have vs nice-to-have

Every MU and MP requirement is a must-have. Nothing else is built. The smoke render (V7) is a must-have feature that the user runs optionally.

---

## 1. Global constraints

- **GC1. Interpreters.** Every new or changed Python file compiles and runs on Python 3.9.6 and 3.13, on macOS and Linux. Forbidden: `match` statements, `X | Y` type expressions, `zip(..., strict=...)`, parenthesised context managers, the `cgi` module (removed in 3.13), `importlib`'s `load_module` in new code.
- **GC2. Standard library only.** New files import only the standard library, `movie_ui_lib`, `movie_ui_server`, and (in `movie_ui_server.py` only) the UI's own workspace `fleet_lib` (GC7).
- **GC3. HTTP clients.** Every outbound HTTP request uses `http.client` (here: only through `fleet_lib.fetch_trace`/`fetch_recent`). `urllib` is never imported.
- **GC4. No network assets.** The page loads nothing from the network: no CDN, no font, no external URL. Every asset is served by movie-ui from `static/movie-ui/`.
- **GC5. Subprocesses.** Every command is an argv list; `shell=True` never appears; no client-supplied argv is ever executed (MU40).
- **GC6. Secrets.** movie-ui never reads, stores, logs or passes the fleet token and never opens any `fleet.env`. It reports only whether `ANTHROPIC_API_KEY` is set (a bool), and passes its own environment unchanged to jobs so `--judge` works. The per-launch UI token is printed once to the terminal, never written to disk, never logged (MU7).
- **GC7. No pipeline imports.** `movie_ui_lib.py` and `movie_ui_server.py` never import or load by path any pipeline module (`lora_catalog`, `character_lib`, `story_engine`, `z_image_skill`, `ltx2_mlx_video_skill`, `pipeline_log`, ...). Catalog, character and dry-run data come from the selected workspace's own `bin/` tools run as subprocesses. `movie_ui_server.py` imports the UI's own `fleet_lib` (`import fleet_lib` with the UI workspace on `sys.path`) and uses only these read-only names: `render_trace`, `fetch_trace`, `fetch_recent`, `valid_trace_id`, `valid_trace_result`, `agent_ids_on_disk`, `agent_port`, `default_command_path`, `classify_command_path`, `deploy_root`, `releases_to_prune`, `release_holds_data`, `read_state`, `tag_key`, `DEFAULT_PORT`, `WS_SUBDIR`, `TRACE_RECENT_MAX`, `TRACE_RECENT_DEFAULT` **[spec choice: the brief named only `render_trace`; reusing the registry reader, wire clients and validators avoids a second copy of their rules, and `fleet_lib` is stdlib-only]**.
- **GC8. Tests.** Tests never use the real `HOME`, never render, never contact a real server or the Anthropic API, and keep `tests/conftest.py`'s autouse `LORA_CATALOG_DIR` isolation working (no test unsets it except by its own `monkeypatch`).
- **GC9. Times.** Every timestamp written by movie-ui is UTC `YYYY-MM-DDTHH:MM:SSZ` (`time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`), called `utc_now()` below.
- **GC10. Atomic writes.** Every file movie-ui writes is written to `<path>.tmp-<pid>-<thread id>` in the same directory, closed, then `os.replace`d onto `<path>`; mode 0600. No `fsync` **[spec choice: losing the last status write on power loss costs one job record, never data]**. Directories movie-ui creates have mode 0700.

---

## 2. Server process (`bin/movie-ui`)

- **MU1. Command line.** `bin/movie-ui [--port N]`. `argparse` with `prog="movie-ui"`; `--port` default `8999`; a value that is not an integer in `1024..65535` exits 2 with `movie-ui: invalid --port <value> (1024 to 65535)` on stderr. There is no bind-address flag. The file starts with `#!/usr/bin/env python3`, sets `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`, inserts `WS` at `sys.path[0]`, imports `movie_ui_server` and calls `sys.exit(movie_ui_server.main(sys.argv[1:]))`.
- **MU2. STATE directory.** `STATE = os.path.expanduser("~/.local/share/qwen-agent/movie-ui")` (the base [PREP] uses, `scripts/fleet-host-prep.sh:43`). At startup `main` creates, mode 0700 with `exist_ok`, `STATE`, `STATE/jobs`, `STATE/uploads`, `STATE/traces`, `STATE/smoke`. It is host-wide, not per workspace. There is no environment override (tests set `HOME`).
- **MU3. Single instance.** `main` opens `STATE/server.lock` (`os.O_RDWR | os.O_CREAT`, 0600) and takes `fcntl.flock(fd, LOCK_EX | LOCK_NB)`, holding the descriptor for the process lifetime. On `BlockingIOError`/`OSError` it prints `movie-ui: another movie-ui is already running on this host (lock held: <STATE>/server.lock)` and exits 2. The lock is taken **before** binding.
- **MU4. Bind.** `movie_ui_server.make_server(port, state_dir, ui_ws, token)` returns a `MovieUIServer(http.server.ThreadingHTTPServer)` bound to `("127.0.0.1", port)` with `daemon_threads = True` and `allow_reuse_address = True` (the `HTTPServer` default). `port=0` is accepted (tests); the server's real port (`server.server_address[1]`) is used everywhere a port appears (Host/Origin checks, printed URL). An `OSError` with `errno.EADDRINUSE` prints `movie-ui: port <port> on 127.0.0.1 is in use; pass --port N` and exits 2; any other bind `OSError` prints `movie-ui: cannot listen on 127.0.0.1:<port>: <strerror>` and exits 2. There is no fallback port. Note: on macOS, `allow_reuse_address` lets `127.0.0.1:<port>` bind while another socket holds `0.0.0.0:<port>`, so the in-use message appears only when the port is held on `127.0.0.1` itself; MUT15 holds the port on `127.0.0.1` (amended 2026-10-20: Task 10 parked note, final review item 10 — record the macOS reuse behaviour the held-port test depends on).
- **MU5. Token.** `token = secrets.token_urlsafe(32)` per launch, kept only in memory (`server.token`).
- **MU6. Startup order.** (1) parse arguments (MU1); (2) STATE (MU2); (3) lock (MU3); (4) bind (MU4); (5) startup recovery (MU31); (6) start the dispatcher thread (MU30) and the capability-probe thread (MU60), both `daemon=True`; (7) print exactly two lines to stdout and flush: `movie-ui: http://127.0.0.1:<port>/?t=<token>` and `movie-ui: state <STATE>; Ctrl-C stops the server (running jobs keep running)`; (8) `serve_forever()`.
- **MU7. Stop.** `SIGTERM` is handled by a function that raises `KeyboardInterrupt` in the main thread. On `KeyboardInterrupt`, `main` calls `server.shutdown()` from a helper thread or `server.server_close()` after `serve_forever` returns, prints `movie-ui: stopped`, and returns 0. Stopping never signals a runner (runners are in their own sessions, MU21). The handler's `log_message` writes nothing for responses below 500; for a 5xx it writes `movie-ui: <METHOD> <path without query> -> <status>` to stderr **[spec choice: the default request log would print `?t=<token>` from `/files` URLs]**. Every 5xx log line (this one and MU10 step 7's) is passed through `_printable`: each character below U+0020 and U+007F is written as `\xNN` and every non-ASCII character is backslash-escaped, so no request text reaches the terminal raw; a request with no parsed method or path (for example `GET / HTTP/2.0`) logs empty fields instead of raising (amended 2026-10-20: ledger ruling Task 10 — control characters in a request line were written raw to stderr, a terminal escape injection, and a missing `self.path` crashed the logger).
- **MU8. Not a service.** movie-ui runs in the foreground (terminal or tmux). No launchd plist or systemd unit is created.

---

## 3. HTTP layer and security (`movie_ui_server.py`)

- **MU9. Handler basics.** `MovieUIHandler(http.server.BaseHTTPRequestHandler)`, `protocol_version = "HTTP/1.0"`, `timeout = 30`. `do_GET`, `do_POST`, `do_PUT`, `do_DELETE` all call `_handle()`, and every other `do_<METHOD>` attribute (OPTIONS, HEAD, unknown methods) resolves through `__getattr__` to `_handle`, so every method passes the full MU10 check order. `send_error` is overridden to answer `{"error": <the stdlib message>}` through `send_json` (a refused HTTP/0.9 request line still gets a status line and headers), so stdlib errors (400 bad request line, 414, 501) are JSON, never HTML. Every JSON response has `Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and body `json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")`. Every error body is `{"error": "<text>"}` plus the extra keys named in the requirement. CORS headers (`Access-Control-*`) are never sent. A write to the client that raises any `OSError` is dropped silently (amended 2026-10-20: ledger rulings Task 10 fix rounds 1-2 — unknown methods bypassed Host/Origin/token and answered stdlib HTML, and NaN could be emitted).
- **MU10. Check order.** `_handle` applies, in this order, stopping at the first failure:
  1. **Host.** The `Host` header must equal `127.0.0.1:<port>` or `localhost:<port>` exactly, else 403 `{"error": "forbidden host"}` (DNS rebinding).
  2. **Origin.** If an `Origin` header is present it must equal `http://127.0.0.1:<port>` or `http://localhost:<port>`, else 403 `{"error": "forbidden origin"}`.
  3. **Static.** `GET /` serves `static/movie-ui/index.html`; `GET /static/app.js` and `GET /static/app.css` serve those files (MU12). No token.
  4. **Token.** For a path starting with `/api/`, header `X-Movie-UI-Token` must be present and `hmac.compare_digest(value.encode("utf-8"), token.encode("utf-8"))` true, else 401 `{"error": "missing or invalid token"}`. For `GET /files`, the header **or** the query parameter `t` is accepted on the same test. This applies to unknown `/api/...` paths too (so they answer 401 without a token, 404 with one).
  5. **Route.** The path (without query) is matched against `ROUTES` (MU11) by `re.fullmatch`. No pattern matches: 404 `{"error": "not found"}`. A pattern matches but not for this method: 405 `{"error": "method not allowed"}`.
  6. **Body (POST and PUT; DELETE only when it sends a non-zero `Content-Length`, MU68).** No `Content-Length`: 411 `{"error": "Content-Length required"}`. A `Content-Length` that is not 1 to 15 ASCII digits (after strip): 400 `{"error": "invalid Content-Length"}`. `Content-Length` above `MAX_BODY = 26214400` (25 MiB): 413 `{"error": "request body too large"}` without reading the body. Content type (the media type before `;`, lower-cased, stripped) must be `application/json`, except `POST /api/uploads` (MU53), else 415 `{"error": "unsupported content type"}`. A JSON body that does not parse as UTF-8 JSON, uses a JSON constant (`NaN`, `Infinity`, `-Infinity`; rejected by `parse_constant`), holds a non-finite number (`1e999` parses to `inf`), or holds a string that cannot be re-encoded as UTF-8 (a lone surrogate escape) — checked by `json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")` on the parsed object — or nests deeply enough to raise `RecursionError`: 400 `{"error": "invalid JSON body"}`; one that is not an object: 400 `{"error": "body must be a JSON object"}` (amended 2026-10-20: ledger rulings Task 10 fix rounds 1-2 — NaN/Infinity/1e999 and lone surrogates crashed the reply with a traceback and an empty response; a non-numeric Content-Length raised).
  7. **Dispatch** to the route handler. An uncaught exception answers 500 `{"error": "internal error"}` and logs `movie-ui: <METHOD> <path> -> 500 (<ExceptionType>: <message>)` to stderr (escaped, MU7). The success reply is sent inside the same `try`. An `ApiError` reply whose body cannot be encoded (`ValueError` from `send_json`, for example a filesystem-derived message holding a lone surrogate) is re-sent as `{"error": <the error string encoded UTF-8 with errors "replace", decoded back>}` with the same status, dropping the extra keys (amended 2026-10-20: ledger ruling Task 10 and final review fix-now item 3 — an unencodable ApiError body gave a traceback and an empty reply).
- **MU11. Route table.** `movie_ui_server.ROUTES` is a list of `(method, regex, handler_name, sample_path)` tuples, in this order; `<ID>` is `[0-9]{8}-[0-9]{6}-[0-9a-f]{4}`, `<STORY>` is `[A-Za-z0-9][A-Za-z0-9._-]{0,79}`, `<NAME>` is `[a-z][a-z0-9-]{1,23}`, `<TRACE>` is `[0-9a-f]{32}`. `sample_path` is a concrete path matching the regex, used by MUT18.

  | Method | Path | Section |
  |---|---|---|
  | GET | `/api/host` | MU60 |
  | GET | `/api/workspaces` | MU45 |
  | GET | `/api/options` | MU47 |
  | GET | `/api/loras` | MU61 |
  | POST | `/api/loras` | MU62 |
  | POST | `/api/loras/remove` | MU62 |
  | POST | `/api/loras/verify` | MU62 |
  | GET | `/api/models` | MU63 |
  | GET | `/api/characters` | MU64 |
  | POST | `/api/characters` | MU65 |
  | GET | `/api/characters/<NAME>` | MU64 |
  | POST | `/api/characters/<NAME>/train` | MU65 |
  | POST | `/api/characters/<NAME>/regenerate` | MU65 |
  | POST | `/api/uploads` | MU53 |
  | POST | `/api/preview` | MU66 |
  | POST | `/api/validate` | MU66 |
  | GET | `/api/jobs` | MU67 |
  | POST | `/api/jobs` | MU66 |
  | GET | `/api/jobs/<ID>` | MU67 |
  | DELETE | `/api/jobs/<ID>` | MU68 |
  | GET | `/api/jobs/<ID>/log` | MU58 |
  | POST | `/api/jobs/<ID>/cancel` | MU68 |
  | POST | `/api/jobs/<ID>/kill-orphan` | MU68 |
  | POST | `/api/queue/move` | MU68 |
  | GET | `/api/stories` | MU69 |
  | GET | `/api/stories/<STORY>` | MU69 |
  | PUT | `/api/stories/<STORY>/story.md` | MU70 |
  | GET | `/api/traces/agents` | MU71 |
  | GET | `/api/traces/recent` | MU72 |
  | GET | `/api/traces/saved` | MU74 |
  | GET | `/api/traces/saved/<TRACE>` | MU74 |
  | DELETE | `/api/traces/saved/<TRACE>` | MU74 |
  | GET | `/api/traces/<TRACE>` | MU73 |
  | POST | `/api/traces/<TRACE>/save` | MU74 |
  | GET | `/files` | MU54 |

  The story-id regex in the URL is necessary but not sufficient: handlers also apply MU38's `..` rule. `GET /api/traces/saved/<TRACE>` is added to the brief's list **[spec choice: "saved traces still viewable" needs a read route]**.
- **MU12. Page headers.** `GET /`, `/static/app.js`, `/static/app.css` answer 200 with `Content-Type` `text/html; charset=utf-8`, `text/javascript; charset=utf-8`, `text/css; charset=utf-8`, plus `Content-Security-Policy: default-src 'self'; img-src 'self' blob:; media-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` **[spec choice: the brief's CSP plus `object-src`, `base-uri`, `frame-ancestors`, `form-action` and a no-referrer policy, because the first URL carries the token]**. The files are read from the UI's own `WS/static/movie-ui/` on every request.
- **MU13. Query parsing.** `urllib.parse` is not used (GC3 forbids `urllib` imports). Query strings are split by a local `parse_query(qs)`: split on `&`, each item on the first `=`, both sides decoded with a local `percent_decode` (`+` becomes a space, `%XX` hex pairs become bytes, the result decoded UTF-8 with `errors="strict"`; a decode error answers 400 `{"error": "invalid query string"}`). A repeated key keeps the last value **[spec choice: avoids the `urllib` import that GC3 bans]**.
- **MU14. Workspace parameter.** Every route that takes `ws` (query for GET, body key for POST/PUT) resolves it with `resolve_ws(value)`: missing or not a string: 400 `{"error": "missing ws"}`; not absolute: 400 `{"error": "ws must be an absolute path"}`; `real = os.path.realpath(value)`; `value` containing NUL (`\x00`, which makes `realpath`/`stat` raise `ValueError`), `real` not a directory or `real/bin/ltx-movie` not a regular file: 400 `{"error": "not a harness workspace (no bin/ltx-movie): <value>"}`. Handlers use `real` everywhere (amended 2026-10-20: ledger ruling Task 10 — a NUL in `ws` raised `ValueError` and answered 500).

---

## 4. On-disk formats (STATE)

- **MU15. `jobs/<id>/job.json`.** Written once by the server at job creation, never changed:

  ```json
  {
    "schema": "movie-ui.job.v1",
    "id": "20261019-142233-a1b2",
    "kind": "story",
    "workspace": "/Users/u/agents/mac-local/releases/v2026.10.19/qwen-agent-workspace",
    "story_id": "ronin-rescue",
    "character": null,
    "argv": ["/usr/bin/python3", "<workspace>/bin/ltx-movie", "<narrative>", "--story-id", "ronin-rescue", "..."],
    "fields": {"action": "story", "story_id": "ronin-rescue", "...": "the submitted fields of MU36, ws replaced by the realpath"},
    "created": "2026-10-19T14:22:33Z"
  }
  ```

  `kind` is one of `story` (action `story` or `regenerate`), `movie` (action `movie` or `redo`), `smoke`, `character-create`, `character-regenerate`, `character-train`. `story_id` is null for character jobs and for `smoke`; `character` is the name for character jobs, else null. `workspace` is the realpath at submit time (the brief's "records the realpath current resolved to").
- **MU16. `jobs/<id>/status.json`.** Absent while queued. Shapes (exactly these keys):

  | Writer | When | Object |
  |---|---|---|
  | server | at dispatch, before starting the runner | `{"state": "starting", "dispatched": T}` |
  | runner | child started | `{"state": "running", "dispatched": T, "runner_pid": P, "pgid": G, "started": T}` |
  | runner | child ended | the running object plus `"state"` (`"done"`, `"failed"` or `"cancelled"`), `"exit_code": <int>`, `"ended": T` |
  | runner | the job argv could not be started | `{"state": "failed", "dispatched": T, "runner_pid": P, "pgid": null, "started": null, "exit_code": null, "ended": T, "error": "cannot start: <strerror>"}` |
  | server | queued job cancelled | `{"state": "cancelled", "exit_code": null, "ended": T}` |
  | server | dispatch finds the workspace gone | `{"state": "failed", "exit_code": null, "ended": T, "error": "workspace no longer exists (removed by self-update)"}` |
  | server | the runner could not be launched | `{"state": "failed", "dispatched": T, "exit_code": null, "ended": T, "error": "cannot start runner: <strerror>"}` |
  | server | runner found dead (MU29) | the last object plus `"state": "lost"`, `"exit_code": null`, `"ended": null`, `"detected": T` |

  `done` means exit code 0; `failed` any other exit code; `cancelled` means the `cancel` marker existed when the child ended, whatever its exit code. `exit_code` is `Popen.returncode` (negative for a signal).
- **MU17. Other job files.** `log.txt`: child stdout and stderr merged, plus runner lines prefixed `[movie-ui] ` (MU24-MU26), opened append-binary. `lock`: the runner's exclusive `flock` target (0600). `cancel`: an empty marker the server creates to request cancellation. `manifest.json`: smoke jobs only (MU52).
- **MU18. `queue.json`.** A JSON array of queued job IDs in run order, e.g. `["20261019-142233-a1b2", "20261019-142301-0c9e"]`. Only the server writes it, always under `STORE_LOCK` (a module-level `threading.Lock` in `movie_ui_server.py` that also guards every server-side status write and every dispatch decision).
- **MU19. Uploads.** `uploads/<sha256 hex>.<ext>` with `ext` in `png`, `jpg`, `webp`. The upload ID is the file name; `UPLOAD_ID_RE = ^[0-9a-f]{64}\.(png|jpg|webp)$`.
- **MU20. Saved traces.** `traces/<trace_id>.json`:

  ```json
  {"schema": "movie-ui.saved-trace.v1", "trace_id": "<32 hex>", "agent": "mac-local",
   "saved_at": "2026-10-19T14:30:00Z",
   "result": {"schema": "qwen-agentd.trace.v1", "trace_id": "<32 hex>", "records": [], "missing": [], "truncated": []}}
  ```

  `result` is exactly the object `fleet_lib.fetch_trace` returned. A file whose `result` fails `fleet_lib.valid_trace_result(result, trace_id)` or whose JSON does not parse is listed with `"invalid": true` and is never rendered.

---

## 5. Job runner (`bin/movie-ui-job`, core in `movie_ui_lib.run_job`)

- **MU21. Launch.** The dispatcher (MU30) starts `[sys.executable, <UI WS>/bin/movie-ui-job, "--grace", repr(movie_ui_lib.CANCEL_GRACE_S), <job_dir>]` with `subprocess.Popen(..., start_new_session=True, stdin=subprocess.DEVNULL, stdout=<log.txt opened "ab">, stderr=subprocess.STDOUT, cwd=<job_dir>, env=dict(os.environ, PYTHONUNBUFFERED="1"), close_fds=True)`, then closes its copy of the log file and does not wait for it. `CANCEL_GRACE_S = 15.0`; tests set it lower. `bin/movie-ui-job` parses `--grace` (float, default 15.0) and `JOB_DIR`, inserts its own workspace on `sys.path`, and exits with `movie_ui_lib.run_job(job_dir, grace)`.
- **MU22. Steps.** `run_job`:
  1. Open `<job_dir>/lock` (`O_RDWR | O_CREAT`, 0600) and take a **blocking** `flock(LOCK_EX)` (the server holds it only for an instant during a liveness probe, MU29).
  2. Read `status.json`. If its `state` is not `starting`, print `[movie-ui] job is <state>; nothing to run` and return 3.
  3. If `<job_dir>/cancel` exists, write the server-cancel shape with `"state": "cancelled"` (exit_code null), print `[movie-ui] cancelled before start`, return 0.
  4. Read `job.json`. Open `log.txt` append-binary. `child = subprocess.Popen(job["argv"], cwd=job["workspace"], env=dict(os.environ, PYTHONUNBUFFERED="1"), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)`. An `OSError` writes the "cannot start" status (MU16) and returns 1. The runner's own environment is the server's, so `ANTHROPIC_API_KEY` reaches `--judge`.
  5. Write the running status with `runner_pid = os.getpid()`, `pgid = child.pid` (the child leads its own new session and group), `started = utc_now()`. Print `[movie-ui] started pid <pid>: <shlex.join(argv)>`.
  6. Loop: `child.wait(timeout=1)`; on `subprocess.TimeoutExpired`, if `cancel` exists, run MU23 once, then keep waiting.
  7. Write the final status (MU16). Print `[movie-ui] exit <code> (<state>)`. Return 0. The lock is released when the process exits.
- **MU23. Cancel and escalation.** On the first sight of the marker:
  1. Snapshot the process tree: run `["ps", "-A", "-o", "pid=,ppid=,pgid="]` (timeout 5 s); parse lines of three integers; compute the transitive descendants of `child.pid`; `groups = {child.pid} | {pgid of every descendant}`. If `ps` fails, `groups = {child.pid}` and the runner prints `[movie-ui] ps failed; signalling process group <pgid> only`. **This sweep is required by D1 and needs user confirmation (Q1).**
  2. For each group in sorted order: `os.killpg(g, signal.SIGTERM)`, ignoring `ProcessLookupError` and `PermissionError`. Print `[movie-ui] cancel: SIGTERM to process group(s) <g1> <g2> ...`.
  3. Every 0.2 s until `grace` seconds have passed: `child.poll()`; a group is gone when `os.killpg(g, 0)` raises `ProcessLookupError`. Stop early when the child has exited and every group is gone.
  4. For every group not gone: `os.killpg(g, signal.SIGKILL)` (same ignores); print `[movie-ui] cancel: SIGKILL to process group(s) ...` when any was sent. Then `child.wait()`.
  All signalling lives in the runner, so escalation completes while the server is down.
- **MU24. Exit codes of the runner.** 0 after writing a final status (any job outcome), 1 when the job could not start, 3 when the status was not `starting`.
- **MU25. No PID checks.** Liveness is decided only by the `lock` (MU29), never by `runner_pid` (PID reuse).
- **MU26. Orphans.** `orphan_info(status)`: a `lost` job whose `pgid` is an int (not bool) with `1 < pgid < 2**31`, not equal to the server's own process group (`os.getpgrp()`), and for which `os.killpg(pgid, 0)` succeeds (or raises `PermissionError`) reports `"orphan": {"pgid": G, "alive": true}`; any other job reports null. The page offers "Kill orphan" behind an in-page confirmation (MU68). Never automatic. A live orphan also blocks dispatch (MU30) (amended 2026-10-20: ledger ruling Task 12 fix — without the own-pgrp guard a reused pgid could name movie-ui itself; final review fix-now item 2 — a pgid >= 2**31 raised `OverflowError` and wedged the queue every tick).

## 6. Queue, dispatcher and recovery

- **MU27. Heavy and light.** Heavy (queued, one at a time): every `ltx-movie` run that is not `--dry-run` (story, regenerate, movie, redo), `character create`, `character create --regenerate`, `character train`, smoke. Light (inline in the request, MU59): `--help`, `--dry-run`, every `lora-catalog` subcommand, `character list`/`show`, `story-server status`, the stills import probe, trace proxy calls.
- **MU28. Job ID.** `time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)`; if `jobs/<id>` already exists, draw again. `JOB_ID_RE = ^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$`. Creating a job: `os.mkdir(jobs/<id>, 0o700)`, write `job.json` (MU15) and an empty `log.txt`, append the ID to `queue.json`, all under `STORE_LOCK`.
- **MU29. Liveness probe.** `job_alive(job_dir)` for a job whose status `state` is `starting` or `running`:
  1. Open `lock` (`O_RDWR | O_CREAT`, 0600), try `flock(LOCK_EX | LOCK_NB)`. `BlockingIOError` (held): close, return `True`.
  2. Acquired: re-read `status.json` **while holding the lock**. If it is now final (`done`, `failed`, `cancelled`), unlock, return `False` (finished normally). If `state` is `starting` and `now - dispatched < 10 s`, unlock, return `True` (runner not yet locked). Otherwise write the `lost` status (MU16) while holding the lock, unlock, return `False`.
- **MU30. Dispatcher.** A thread that, every 1 s, under `STORE_LOCK`:
  1. For every job whose status `state` is `starting` or `running`, run `job_alive`. If any returns `True`, stop this tick (a heavy job is active). Then, for every job, compute `orphan_info` (MU26) from its status; if any is non-null (a `lost` job still has a live orphan process group), stop this tick: the queue waits until that job's orphan is killed or the job is deleted (MU68). `GET /api/jobs` reports the blocker as `blocked_by` (MU67) and the page shows it (MU84).
  2. If `queue.json` is non-empty: pop its head. If that job already has a `status.json` (`os.path.lexists`), rewrite the queue without it and continue with the next head. If the job directory or `job.json` is missing, rewrite the queue without it and continue. If `os.path.isdir(job["workspace"])` is false, write the "workspace no longer exists" status, rewrite the queue, and continue. Otherwise write `{"state": "starting", "dispatched": utc_now()}` **first**, then rewrite the queue, then launch the runner (MU21); a launch `OSError` writes the "cannot start runner" status. At most one job is launched per tick.
  This guarantees at most one heavy job at a time, including jobs whose runner outlived a previous server and orphan renders of lost jobs (amended 2026-10-20: ledger ruling Task 4 fix (a)-(b) — the one-heavy-job rule exists for GPU memory and an orphan render still holds it; writing `starting` before the queue rewrite closes a window in which a job was neither queued nor started and so reported `unknown` and could not be cancelled; skipping heads that already have a status prevents re-dispatching a job a crash left in the queue).
- **MU31. Startup recovery.** Before serving: read `queue.json` (missing or invalid JSON: `[]`); drop every ID that does not match `JOB_ID_RE`, has no `job.json`, or already has a `status.json`; rewrite it. Then run `job_alive` on every job in `starting`/`running`: held locks are re-attached (reported `running`), acquirable ones become `lost`. No PID is consulted.
- **MU32. Job index.** Job lists are read from disk on each request: every directory in `STATE/jobs` whose name matches `JOB_ID_RE` and that has a readable `job.json`. `job.json` contents may be cached in memory by ID (immutable).

---

## 7. Workspaces and versions

- **MU33. Candidates.** `list_workspaces()` returns, in this order, de-duplicated by realpath (first occurrence wins, but `is_current` is OR-ed across duplicates):
  1. For each `id` in `fleet_lib.agent_ids_on_disk()`, with `A = fleet_lib.deploy_root(id)`: if `A/current/qwen-agent-workspace/bin/ltx-movie` is a file, the candidate `path = A/current/qwen-agent-workspace`, `agent = id`, `is_current = true`, `tag = basename(realpath(A/current))` when `fleet_lib.tag_key` accepts it, else null. Then for each name in `os.listdir(A/releases)` sorted by `tag_key` descending (names `tag_key` rejects are skipped) whose `A/releases/<name>/qwen-agent-workspace/bin/ltx-movie` is a file: `path` = that workspace, `agent = id`, `tag = name`, `is_current = (realpath == realpath of the current candidate)`.
  2. The UI's own workspace: `path = realpath(UI WS)`, `is_ui = true`; if not already listed, `agent = null`, `tag = null`, `commit` = stdout of `["git", "-C", path, "rev-parse", "--short", "HEAD"]` (timeout 5 s; any failure: null).
  Each entry: `{"path", "realpath", "label", "agent", "tag", "commit", "is_current", "is_ui", "stories", "prune", "data_bytes"}`. `label`: `"<agent> current (<tag>)"`, `"<agent> <tag>"`, or `"this checkout (<commit or 'unknown commit'>)"`. `stories`: the number of directories in `<realpath>/generated/stories` whose name passes MU38 and is not `movie-ui-smoke`. `prune` (release candidates only, else null): with `present = os.listdir(A/releases)`, `cur = basename(realpath(A/current))`, `state = fleet_lib.read_state(A/update-state.json)`, `doomed = set(fleet_lib.releases_to_prune(present, cur, state))`: `"kept_for_data"` when `tag in doomed` and `fleet_lib.release_holds_data(A/releases/<tag>)`, `"would_prune"` when `tag in doomed` otherwise, else `"kept"`. The value forecasts the next prune (MP3). `data_bytes`: for release candidates, the sum of `st_size` of every regular file (by `lstat`) under `<realpath>/generated` (`os.walk`, `followlinks=False`), else null.
- **MU34. Default workspace.** `default_workspace()`: let `ui = realpath(UI WS)` and `root = realpath(expanduser("~/agents"))`. If `ui` equals `root/<id>/releases/<tag>/qwen-agent-workspace` for some `<id>`, `<tag>` (an installed UI), let `d = default_agent()` (MU35) or `<id>` when that is null; return `deploy_root(d)/current/qwen-agent-workspace` if its `bin/ltx-movie` is a file, else `ui`. Otherwise return `ui`. The selection is never persisted: every page load starts at this value.
- **MU35. Default agent.** `default_agent()`: `kind, found = fleet_lib.classify_command_path(fleet_lib.default_command_path())`; if `kind == "wrapper"` and `found` is in `agent_ids_on_disk()`, return `found`; else if exactly one agent is on disk, return it; else null.
- **MU37. Version-aware forms.** `help_flags(ws_real)` runs `[sys.executable, ws_real/bin/ltx-movie, "--help"]` (cwd `ws_real`, MU59) and caches the result in a dict keyed `(ws_real, os.stat(ws_real/bin/ltx-movie).st_mtime_ns)`. Parse: for each stdout line that matches `^  -`, take `re.split(r"\s{2,}", line[2:], 1)[0]` and collect every `re.findall(r"--[a-z][a-z0-9-]*", that)`. A non-zero exit is cached as `None` with its stderr's last line. A timed-out run is never cached: it returns `None` with `cannot read bin/ltx-movie --help (timed out after 60 s)`, and the next call runs `--help` again (amended 2026-10-20: ledger ruling Task 5 — caching a timeout would disable every form control for that workspace until `bin/ltx-movie` changed). The field-to-flag map:

  | Field (MU36) | Flag |
  |---|---|
  | `story_id` | `--story-id` |
  | `panels` / `length` | `--panels` / `--length` |
  | `fps` / `frames` | `--fps` / `--frames` |
  | `width`, `height` | `--video-width`, `--video-height` |
  | `seed_upload` | `--seed-image` |
  | `model` / `gemma` / `story_model` | `--model` / `--gemma` / `--story-model` |
  | `goal` | `--goal` |
  | `mode` `shots` / `no_stills` | `--shots` / `--no-stills` |
  | `video_loras` / `stills_loras` | `--lora` / `--stills-lora` |
  | `characters` | `--character` |
  | `auto_lora` (false) | `--no-auto-lora` |
  | `story_legacy` / `judge` / `no_low_ram` / `panel_timeout` | `--story-legacy` / `--judge` / `--no-low-ram` / `--panel-timeout` |
  | `overwrite_movie` | `--force` |
  | action `regenerate` | `--force-story` |
  | action `redo`, `redo` | `--redo` |
  | action `story`, `regenerate` | `--story-only` |
  | (always) | `--no-review` |

  The page hides every form control whose flag is not supported and sends the field as null/false/empty.

## 8. Command builder

- **MU36. Compose fields.** The page sends exactly this object (POST bodies of `/api/preview`, `/api/validate`, `/api/jobs`); a missing key takes the default shown; an unknown key is ignored:

  ```json
  {"ws": "/abs/workspace", "action": "story",
   "story_id": "", "narrative": "", "goal": null,
   "panels": 15, "length": null, "fps": 24, "frames": 145,
   "width": null, "height": null, "seed_upload": null,
   "mode": "chained",
   "model": "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "gemma": "mlx-community/gemma-3-12b-it-4bit",
   "story_model": null,
   "auto_lora": true,
   "video_loras": [], "stills_loras": [],
   "characters": [],
   "story_legacy": false, "judge": false, "no_low_ram": false, "panel_timeout": null,
   "overwrite_movie": false, "redo": []}
  ```

  `action` is `story` (Write story), `regenerate` (Regenerate story), `movie` (Run all, and Render from the Stories tab), `redo` (shots per-panel Redo), or `smoke` (Smoke render). A LoRA item is `{"id": <catalog id or null>, "path": "<absolute path>", "strength": <number>, "kind": "style" | "motion" | "physics" | null}`; catalog items carry the catalog's `id`, `path` and `kind` (V5 re-checks them), free-path items have `id` and `kind` null. `mode` is `chained`, `shots` or `no_stills`.
- **MU38. Story ID rule.** `STORY_ID_RE = ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$` with `re.fullmatch`, and `".." not in story_id`; `movie-ui-smoke` is reserved (MU52). `bin/ltx-movie` joins the ID into a path without validating it (`:565-566`), so this rule is the only guard.
- **MU39. LoRA order.** `ordered(loras)` = the items whose `kind` is `motion` or `physics`, in submitted order, followed by every other item in submitted order (the user rule "motion/physics adapter listed first"). The page displays this order.
- **MU40. `build_argv(fields, ws_real, state_dir, py=sys.executable)`.** Pure (no I/O). For actions `story`, `regenerate`, `movie`, `redo`, the argv is, in this exact order (bracketed parts only when the condition holds):

  1. `py`, `ws_real/bin/ltx-movie`, `narrative.strip()`
  2. `--story-id`, `story_id`
  3. `--panels`, `str(panels)` when `panels` is not null, else `--length`, `repr(float(length))`
  4. `--fps`, `str(fps)`, `--frames`, `str(frames)`
  5. [`--seed-image`, `state_dir/uploads/<seed_upload>`] when `seed_upload`; else [`--video-width`, `str(width)`, `--video-height`, `str(height)`] when both are set
  6. [`--model`, `model`] when not null; [`--gemma`, `gemma`] when not null; [`--story-model`, `story_model`] when not null; [`--goal`, `goal_text`] when not null (`goal_text` per V1 rule 3)
  7. [`--shots`] for mode `shots`; [`--no-stills`] for mode `no_stills`
  8. for each item of `ordered(video_loras)`: `--lora`, `"%s:%s" % (path, repr(float(strength)))`; then the same for `ordered(stills_loras)` with `--stills-lora`
  9. for each name in `characters`: `--character`, `name`
  10. [`--no-auto-lora`] when `auto_lora` is false; [`--story-legacy`]; [`--judge`]; [`--no-low-ram`]; [`--panel-timeout`, `str(panel_timeout)`] when not null
  11. [`--force`] when `overwrite_movie`; [`--force-story`] for action `regenerate`; [`--redo`, `",".join(str(n) for n in sorted(set(redo)))`] for action `redo`; [`--story-only`] for actions `story` and `regenerate`
  12. `--no-review` (always: the runner's stdin is not a TTY, `bin/ltx-movie:2313-2317`)

  The V6 dry run is this argv plus `--dry-run`. Smoke argv: MU52. `command = shlex.join(argv)`. Preview and submit call this one function on the same fields, so the previewed argv is the executed argv (MUT2).
- **MU41. Character argv.** With `C = [py, ws_real/bin/character]`:
  - create: `C + ["create", name, "--phrase", phrase]`, then `["--seed-image", state_dir/uploads/<seed_upload>]` or `["--descriptor", descriptor]`, then `["--class", class_noun]` when set, `["--trigger", trigger]` when set, `["--seed", str(seed)]` when set, `["--force"]` when `force`.
  - regenerate: `C + ["create", name, "--regenerate"]`.
  - train: `C + ["train", name]` + `["--video"]` when `video` + `["--stills"]` when `stills` + `["--force"]` when `force`.

## 9. Validation (V1-V7)

- **MU42. Check record.** Every check is `{"id": "V<n>", "name": "<text>", "status": "pass" | "fail" | "skip", "detail": "<text>"}`. `detail` is at most 20000 characters (the tail is kept). A list passes when no item is `fail`.
- **MU43. Running order.** `run_checks(fields, server)` runs V1. If V1 fails, it returns V1 plus one `skip` per V2-V6 with detail `skipped: V1 failed`. Otherwise it runs V2, V3, V4, V5, V6 in order (no short circuit) and returns every record. Check names are exactly those in the bullets below. "Needed" sets:
  - `render_needed`: action in `movie`, `redo`, `smoke`.
  - `stills_needed`: action in `movie`, `redo` and mode is not `no_stills`.
  - `story_needed`: action in `story`, `regenerate`, or action `movie` and `<ws>/generated/stories/<id>/story.md` does not exist.
  A check that is not needed is one `skip` record with detail `not needed for this action`.
- **V1 fields** (one record, name `fields`; `detail` lists every failure, one per line, in this order; empty when it passes). For action `smoke`, only rules 9, 11 (video LoRAs only), 13 and 14 apply. `_argv_safe(value)` (in `movie_ui_lib`) is true when `value` is a `str`, contains no NUL (`\x00`) and `value.encode("utf-8")` succeeds (no lone surrogates): the strings `Popen` can pass as argv elements. V1 is the last gate before the queue, so every client string that reaches a compose argv passes it (rules 2, 3, 9, 11); MU62 and MU65 apply the same predicate to LoRA and character fields (amended 2026-10-20: ledger ruling Task 6 fix — one predicate for narrative, goal, models and LoRA paths).
  1. `story_id` fails MU38: `story id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ and must not contain '..'`; equals `movie-ui-smoke` compared case-insensitively (`story_id.lower() == "movie-ui-smoke"`): `story id movie-ui-smoke is reserved for smoke renders` (amended 2026-10-20: ledger ruling Task 6 fix — APFS is case-insensitive, so `Movie-UI-Smoke` names the same directory).
  2. `narrative`: not a string or empty after `strip()`: `narrative is required`; longer than 20000 characters: `narrative must be at most 20000 characters`; starts with `-` after strip: `narrative must not start with '-'` **[spec choice: argparse would read it as an option]**; otherwise not `_argv_safe` (below): `narrative contains invalid characters`. Only the first failing test of this list is reported (amended 2026-10-20: ledger ruling Task 6 fix — a NUL or lone surrogate passed V1 and failed in `Popen`).
  3. `goal` (null allowed): `goal_text = goal.strip()`, then one trailing `.` removed and `rstrip()`ed (as `_parse_goal`, `bin/ltx-movie:262-277`); empty, containing `\n` or `\r`, or longer than 300: `goal must be a single line of 1 to 300 characters`; otherwise `goal_text` starting with `-`: `goal must not start with '-'`; otherwise not `_argv_safe`: `goal contains invalid characters`. Only the first failing test is reported (amended 2026-10-20: ledger rulings Task 5 CARRY / Task 6 dispatch and fix — a leading `-` must fail early, not in V6 or the job log, and an unsafe string failed in `Popen`).
  4. Exactly one of `panels`, `length` non-null, else `give exactly one of panels or length`. `panels`: an int (not bool) in 1..200, else `panels must be an integer from 1 to 200`. `length`: a number (not bool) in (0, 3600], else `length must be a number of seconds in (0, 3600]`; `n = round(length / (frames / fps))` below 2: `length resolves to <n> panel(s); the minimum is 2`.
  5. `fps`: int in 1..120, else `fps must be an integer from 1 to 120`.
  6. `frames`: int with `(frames - 1) % 8 == 0` and `frames >= 9`, else `frames must satisfy (n-1)%8==0 and n>=9`.
  7. `seed_upload` non-null together with `width` or `height` non-null: `give a seed image or a resolution, not both`. `width`/`height`: both null or both ints that are multiples of 64 and at least 64, else `width and height must both be multiples of 64 (at least 64)`. `seed_upload`, when non-null, must match `UPLOAD_ID_RE` and exist as a file in `STATE/uploads`, else `seed image upload <value> not found`.
  8. `mode` not one of the three: `mode must be chained, shots or no_stills`. `seed_upload` with mode `no_stills`: `a seed image cannot be used with no-stills mode`; with mode `shots`: `a seed image cannot be used with shots mode`.
  9. `model`, `gemma`, `story_model` (null allowed): a string of 1..512 characters with no character below U+0020, not starting with `-` and `_argv_safe`, else `<field> must be a model name or an absolute path` (amended 2026-10-20: ledger ruling Task 6 fix — a lone surrogate passed and failed in `Popen`; the existing string is reused).
  10. (unused number, kept so later rule numbers stay stable)
  11. `video_loras`, `stills_loras`: lists of at most 8 items; each item an object with `path` an absolute string, `strength` a number (not bool) with `0 < strength <= 2`, `id` null or matching `^[a-z][a-z0-9-]{1,31}$`, `kind` null or one of `style`, `motion`, `physics`, and `kind` null exactly when `id` is null. Failures: `<video|stills> LoRA <k>: <reason>` with `<k>` 1-based and `<reason>` one of `path must be absolute`, `path contains invalid characters` (an absolute path that is not `_argv_safe`; checked before `realpath`, which raises on NUL), `strength must be in (0, 2]`, `bad catalog id`, `bad kind`, `must be an object` (the item is not an object). A value that is not a list of at most 8 items: `<video|stills> LoRAs must be a list of at most 8 items`. A realpath listed twice in one list: `<video|stills> LoRA <path> is listed twice` (amended 2026-10-20: ledger ruling Task 6 fix — `realpath` raised on NUL/lone surrogate on 3.13; plan decision 7 — the two list/object messages the spec did not give).
  12. `characters`: a list of at most 8 distinct names matching `^[a-z][a-z0-9-]{1,23}$`, else `characters must be distinct character names`.
  13. `auto_lora`, `story_legacy`, `judge`, `no_low_ram`, `overwrite_movie` are bools, else `<field> must be true or false`. `panel_timeout` null or int in 60..86400, else `panel_timeout must be an integer from 60 to 86400`.
  14. `action` not one of the five: `unknown action`.
  15. `story_legacy` with `judge`, `auto_lora` false, or `goal` non-null: `--story-legacy cannot be combined with --judge, --no-auto-lora or --goal` (`bin/ltx-movie:887-894`).
  16. Action `redo`: mode not `shots`: `redo needs shots mode`; `redo` not a non-empty list of ints: `redo needs at least one panel number`; a number outside `1..P` (P = `panels` or the `length` resolution): `redo panel <n> is out of range (1..<P>)`; no `story.md`: `redo needs an existing story.md`.
  17. Action `movie`, `movie.mp4` exists in the story directory and `overwrite_movie` is false: `movie.mp4 already exists; tick "Overwrite movie.mp4" (--force)` (`bin/ltx-movie:1970-1972`) **[spec choice: without it Phase 4 exits 2 after hours of stills]**.
  18. Flags: for every element of the built argv (MU40) that starts with `--`, it must be in `help_flags(ws)`, else `this workspace's bin/ltx-movie does not support <flag>`; when `help_flags` is `None`: its error (`cannot read bin/ltx-movie --help (exit <n>): <last stderr line>`, or the MU37 timeout text). Skipped for smoke, and runs only when rules 1-17 produced no failure, because the argv it inspects can only be built from valid fields (amended 2026-10-20: plan decision 7 and ledger ruling Task 5 — rule 18 needs a buildable argv; the timeout text is never cached).
- **V2 host can run it** (records named `render`, `stills`, `story server`, `judge key`):
  - `render` (needed: `render_needed`): `bin = os.environ.get("LTX2_MLX_BIN") or join(os.environ.get("LTX2_MLX_DIR") or expanduser("~/ltx-2-mlx"), ".venv", "bin", "ltx-2-mlx")`; if `os.sep not in bin`, `bin = shutil.which(bin) or bin` (`ltx2_mlx_video_skill.py:44-46`, `:130-139`). Pass when `bin` is a file with `os.X_OK` and `shutil.which("ffmpeg")` and `shutil.which("ffprobe")` are non-null. Failure details (joined by `; `): `ltx-2-mlx binary not found or not executable: <bin> (set LTX2_MLX_BIN)`, `ffmpeg not found on PATH`, `ffprobe not found on PATH`.
  - `stills` (needed: `stills_needed`): run `[sys.executable, "-c", "import torch; from diffusers import ZImagePipeline, ZImageTransformer2DModel; from transformers import Qwen3Model"]` (cwd = ws, MU59; the imports of `z_image_skill.py:46-48`). Pass on exit 0; else `stills dependencies not importable: <last non-empty stderr line>`; timeout: `stills dependency probe timed out after 60 s`.
  - `story server` (needed: `story_needed`): run `[ws/bin/story-server, "status"]` (cwd = ws). Parse the first line matching `^\s*state:\s*(.+?)\s*$`. Pass when exit 0 and the state starts with `SERVING `; detail `story server: <state>`. Fail details: `story server is <state>; start it with bin/story-server vision (or text)`, `bin/story-server status exited <n>: <last stderr line>`, or, on a timeout (60 s, MU59), `bin/story-server status timed out after 60 s` (amended 2026-10-20: ledger ruling Task 6 fix — a timeout was reported with a misleading exit detail).
  - `judge key` (needed: `judge` true): pass when `os.environ.get("ANTHROPIC_API_KEY")` is non-empty; else `--judge needs ANTHROPIC_API_KEY in movie-ui's environment`.
- **V3 models present and intact** (records named `video model <M>`, `gemma <G>`, `Z-Image <id>`, `Z-Image text encoder <id>`). `M` = `model` or the default `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8`, `G` = `gemma` or `mlx-community/gemma-3-12b-it-4bit` (`bin/ltx-movie:318-319`). Video model and gemma are needed when `render_needed`; the two Z-Image models (`z_image_skill.py:52-53`) when `stills_needed`.
  - Lookup: an absolute model path is checked in place (no blob or snapshot steps). Otherwise `repo_dir = <hub>/models--<org>--<name>` (the ID with `/` replaced by `--`). Video model and gemma: `hub = <LTX2_MLX_HF_HOME>/hub`, `LTX2_MLX_HF_HOME = os.environ.get("LTX2_MLX_HF_HOME") or <LTX2_MLX_DIR>/hf_cache` (`ltx2_mlx_video_skill.py:47-48`, the child's `HF_HOME`). Z-Image: `<Z_IMAGE_HF_HOME or ~/hf_home>/hub` when `repo_dir` exists there (`z_image_skill.py:56-69`), else `<HF_HOME or ~/.cache/huggingface>/hub`.
  - Snapshot: `rev = <repo_dir>/refs/main` (read as UTF-8, stripped) and `snapshots/<rev>`; without a readable `refs/main` (absent, an `OSError`, or bytes that do not decode as UTF-8), the only directory in `snapshots/`; with none or several: fail `cannot choose a snapshot of <id> (no refs/main)` (amended 2026-10-20: ledger ruling Task 7 fix — a non-UTF-8 `refs/main` raised `UnicodeDecodeError`).
  - `intact(snapshot, repo_dir)` collects problems: (a) repo absent: `<id> is not in <hub>`; (b) any `*.incomplete` file in `<repo_dir>/blobs`: `download incomplete: <n> partial blob(s)`; (c) walking the snapshot (`os.walk`, `followlinks=False`), every file entry must resolve (`os.path.realpath`) to an existing regular file: `broken file: <relpath>`; every `*.safetensors` entry must be non-empty: `empty file: <relpath>`; (d) at least one `*.safetensors` file: `no .safetensors file`; (e) every `*.safetensors.index.json`: parse JSON; every value of its `weight_map`, relative to the index's directory, must resolve to a non-empty regular file: `missing shard: <relpath>`; an unparsable index: `unreadable index: <relpath>`. **Stale index:** an index none of whose `weight_map` files exist (`os.path.lexists`), in a snapshot that has at least one other `*.safetensors` file, is ignored (rule (e) is skipped for it, the no-index rule applies) and the note `index lists none of the present shards; ignored` is appended to the pass detail. An absolute model path (checked in place) is walked for at most `MAX_MODEL_WALK_ENTRIES = 20000` entries (directories plus files); beyond that the only problem is `too many files under <path> (more than 20000)`. Pass when there is no problem; detail `<snapshot path>` on pass (followed by `; <note>` for each note), problems joined by `; ` on fail. The brief's `config.json` requirement is not applied (D3) (amended 2026-10-20: ledger ruling Task 7 fix, approved by the user 2026-10-19 "the stale index rule is fine, keep going" — the real gemma snapshot has a stale 5-shard index beside 2 intact shards and `mlx_lm` loads by glob, so rule (e) false-failed every movie submit; the walk cap stops a typed path such as `/` from walking the whole disk).
- **V4 LoRAs intact** (records `catalog verify`, `LoRA file <path>`):
  - `ids` = the `id` of every catalog item in `video_loras` and `stills_loras`, plus, when `auto_lora` is true, `story_legacy` is false and action is not `smoke`, the `id` of every entry of `list --model <M> --json` with `target` `video` and (mode not `no_stills`) of every entry of `list --model Tongyi-MAI/Z-Image-Turbo --json` with `target` `stills` (the planner's set, `story_engine.py:534-559`). When `ids` is empty: one `skip` record `catalog verify`, detail `no catalog LoRA chosen or pickable`. Otherwise run `[py, ws/bin/lora-catalog, "verify"] + sorted(ids)` with timeout `VERIFY_TIMEOUT = 300` s (hashing multi-GB LoRAs on an HDD exceeds 60 s): pass on exit 0, detail = stdout + stderr; a timeout fails with `bin/lora-catalog verify timed out after 300 s`. On any other exit, the `FAIL <id>` lines are split into chosen ids (the catalog items of `video_loras`/`stills_loras`) and auto-set ids: any chosen FAIL makes `catalog verify` fail with only the chosen FAIL lines as detail; auto-set FAILs alone leave `catalog verify` `pass` (detail stdout + stderr) and add a non-blocking `skip` record named `LoRAs auto set` with detail `the planner will skip these entries:` followed by those FAIL lines, one per line; a non-zero exit with no `FAIL` line at all fails with stdout + stderr (amended 2026-10-20: ledger rulings Task 8 fix — a 60 s verify timed out and was swallowed; spec deviation: `story_engine._catalog_filter` warns and skips a failing auto-pickable entry, so it cannot break a render and must not block the submit).
  - For each free-path item (id null): pass when the file is a regular readable file, its first 8 bytes unpack (`struct.unpack("<Q")`) to a length `n` with `0 < n <= 104857600`, the next `n` bytes are read fully and `json.loads` gives a dict; else fail `<path>: not a safetensors file` (or `<path> is not a readable file`). Implemented in `movie_ui_lib` with the standard library (the rule of `lora_catalog.read_safetensors_header`, `lora_catalog.py:234-254`, re-implemented, not imported).
- **V5 compatible** (records `catalog compatibility`, `character <name>`, `character <name> video base model`):
  - `catalog compatibility` (skip when no catalog item): `V = list --model <M> --json` entries by id, `S = list --model Tongyi-MAI/Z-Image-Turbo --json` entries by id. Each video item: `id` in `V` with `target` `video`, else `<id> is not a video LoRA compatible with <M>`; each stills item: in `S` with `target` `stills`, else `<id> is not a stills LoRA compatible with Tongyi-MAI/Z-Image-Turbo`. The item's `path` and `kind` must equal the entry's, else `<id>: path or kind differs from the catalog; reload the LoRA list`. `strength` must satisfy `lo <= strength <= hi` with `[lo, hi] = strength_range`, else `<id>: strength <s> is outside <lo>-<hi>`. At most one catalog `style` item per list, else `at most one style LoRA among the <video|stills> LoRAs`.
  - `character <name>` for each cast name (skip when none): run `character show <name>`; parse the stdout prefix with `json.JSONDecoder().raw_decode` (D6). Fail on a timeout (60 s, MU59) with `bin/character show <name> timed out after 60 s` (amended 2026-10-20: ledger ruling Task 8 fix — the timeout was swallowed and reported with a misleading detail); fail when exit is non-zero (`<stderr>`), `status` is not `trained` (`character <name> is not trained (status <s>)`), or `loras.stills` is set and its `base_model` is not `Tongyi-MAI/Z-Image-Turbo` (`character <name>'s stills LoRA is for <b>, not Tongyi-MAI/Z-Image-Turbo`).
  - `character <name> video base model`: `pass` when `loras.video.base_model == M`, or both are absolute paths with the same realpath; otherwise **`skip`** (never `fail`) with detail `video LoRA trained on <base_model>; bin/ltx-movie does not check this against --model <M>` (D2, Q2).
- **V6 dry run** (record `dry run`; skip for smoke): run `build_argv(fields) + ["--dry-run"]` with env `dict(os.environ, STORY_PIPELINE_LOGGED="1")` (so no `iterate-story.log` record is appended, D17), cwd = ws, timeout 60 s. Pass on exit 0. Detail = stdout + stderr (tail-limited). Timeout: fail `bin/ltx-movie --dry-run timed out after 60 s`.
- **V7 smoke render** (optional, heavy): the `smoke` action of `POST /api/jobs` (MU52). The page shows it as a check named `smoke render` whose status is `pass` when the smoke job is `done` and `progress.smoke.clip_ok` is true, `fail` when the job is final otherwise, and is not shown before a smoke job exists.
- **MU44. Submit.** `POST /api/jobs` re-runs MU43. Any `fail`: 409 `{"error": "validation failed", "checks": [...]}`. Else the job is created (MU28) and the response is 201 `{"job": <summary of MU67>, "checks": [...]}`.

## 10. Endpoints

### 10.1 Host, workspaces, options

- **MU45. `GET /api/workspaces`** → 200 `{"default": <default_workspace() path>, "workspaces": [<MU33 entries>]}`.
- **MU46. Typed path.** The page's typed-path control calls `GET /api/options?ws=<typed>`; MU14's 400 message is shown on failure, and on success the path is added to the selector as `label "typed path"`. No other endpoint is involved.
- **MU47. `GET /api/options?ws=`** → 200 `{"workspace": <real>, "help_ok": <bool>, "help_error": <text or null>, "flags": [<sorted flags>], "supported": {<field or action>: <bool>}, "defaults": {"panels": 15, "fps": 24, "frames": 145, "model": "MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8", "gemma": "mlx-community/gemma-3-12b-it-4bit", "panel_timeout": 7200}}`. `supported` has one key per row of MU37's table (keys: `story_id`, `panels`, `length`, `fps`, `frames`, `resolution`, `seed_upload`, `model`, `gemma`, `story_model`, `goal`, `shots`, `no_stills`, `video_loras`, `stills_loras`, `characters`, `auto_lora`, `story_legacy`, `judge`, `no_low_ram`, `panel_timeout`, `overwrite_movie`, `regenerate`, `redo`, `story_only`, `no_review`). `defaults` are constants copied from `bin/ltx-movie:304-319` and `:406` **[spec choice: defaults are not parsed from help text]**.

### 10.2 Uploads and files

- **MU53. `POST /api/uploads`.** Raw body (not JSON). `Content-Type` must be `image/png`, `image/jpeg` or `image/webp`, else 415. `Content-Length` above `UPLOAD_MAX = 20971520` (20 MiB): 413 `{"error": "upload larger than 20 MiB"}`. Magic bytes: PNG `\x89PNG\r\n\x1a\n`; JPEG `\xff\xd8\xff`; WebP bytes 0-3 `RIFF` and 8-11 `WEBP`; mismatch with the declared type: 400 `{"error": "file content is not <type>"}`. Stored at `STATE/uploads/<sha256>.<png|jpg|webp>` (atomic; an existing file of that name is kept). Response 201 `{"upload_id": "<sha256>.<ext>", "path": "<STATE>/uploads/<sha256>.<ext>", "bytes": <n>}`. No multipart.
- **MU54. `GET /files?ws=&path=&t=`.** `path` is absolute. `real = os.path.realpath(path)`; allowed roots are `realpath(<ws>/generated)` and `realpath(STATE/uploads)`; `real` must start with `root + os.sep` for one of them, else 403 `{"error": "path not allowed"}`; not a regular file (or a `path` containing NUL): 404. The file is opened and its size taken with `os.fstat` on the open descriptor **before any header is sent**; an `open` that fails with `EACCES` or `EPERM` (for example a macOS privacy denial on `/Volumes`) answers 403 `{"error": "path not allowed"}`, any other open or `fstat` `OSError` 404, so an error never arrives as a second response inside a 200 body. Once streaming has started, any `OSError` ends the response silently, and the file is closed in a `finally` (amended 2026-10-20: ledger ruling Task 14 fix — headers were sent before `open()`, so a TCC denial or mid-stream error wrote a second response into the body). `Content-Type` by lower-cased extension: `.png` `image/png`, `.jpg`/`.jpeg` `image/jpeg`, `.webp` `image/webp`, `.mp4` `video/mp4`, `.json` `application/json`, `.md`/`.txt`/`.log` `text/plain; charset=utf-8`, else `application/octet-stream`. Always `Accept-Ranges: bytes`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`. A `Range` header matching `^bytes=(\d*)-(\d*)$` with at least one number: `bytes=a-b` (b clamped to size-1), `bytes=a-`, `bytes=-n` (last n bytes, n > 0). Each number has its leading zeros stripped and, when it still has more than 18 digits, counts as `10**18` (so a huge number is clamped instead of building an unbounded int). `a > b`, `a >= size`, or `bytes=-0` (n = 0): 416 with `Content-Range: bytes */<size>` and an empty body (amended 2026-10-20: ledger ruling Task 14 fix — huge Range numbers clamped; `bytes=-0` named no byte and must be 416). Otherwise 206 with `Content-Range: bytes a-b/<size>` and `Content-Length: b-a+1`. Any other `Range` value is ignored (200, whole file). The body is streamed in 65536-byte chunks; a client disconnect (`BrokenPipeError`, `ConnectionResetError`) ends the response silently.

### 10.3 Progress and logs

- **MU55. Progress parser.** `ProgressParser(kind, fields)` in `movie_ui_lib`, fed bytes incrementally by `feed(data)`; the server keeps one per job ID with its byte offset and re-feeds only new bytes of `log.txt` (up to 1 MiB per call) on each `GET /api/jobs` or `GET /api/jobs/<id>`. Complete lines (ending `\n`) are decoded UTF-8 `errors="replace"`; the trailing incomplete bytes are kept for the next feed (a line split across reads is parsed once, whole). Every line is reduced with `collapse(line) = line.rstrip("\r").rsplit("\r", 1)[-1]` (`pipeline_log.collapse_cr`'s rule, `pipeline_log.py:32-35`). Regexes, applied to complete collapsed lines with `re.match`:

  | Name | Regex | Effect |
  |---|---|---|
  | PHASE | `^=== Phase (\d+b?): (.+?)(?: \(rewrite (\d+) of (\d+)\))? ===$` | `phase` = group 1, `phase_title` = group 2, `rewrite` = `[int(g3), int(g4)]` or null |
  | REDO | `^=== Redo: panels (.+) ===$` | `phase` = `"redo"`, `redo` = group 1 |
  | TOTAL | `^panels: (\d+)$` | `panels_total` |
  | PANEL_HDR | `^=== panel (\d+)/(\d+) \(` | `panels_total` = group 2; panel group 1 `running` |
  | RETRY | `^=== inline retry: panel (\d+) \(` | panel group 1 `running` (amended 2026-10-20: ledger ruling Task 9 — an inline retry after a FAILED line left the panel shown failed while it re-rendered) |
  | OK | `^panel (\d+) ok: ` | panel `ok` |
  | REUSE | `^panel (\d+): reusing ` | panel `ok` with `reused: true` |
  | FAILED | `^panel (\d+) FAILED \(([^)]*)\):? ?(.*)$` | panel `failed`, `reason` = group 2, `detail` = group 3 (at most 300 characters) |
  | SUMMARY | `^=== render summary \(` | `wrap_up` = true |
  | MOVIE | `^MOVIE \d+/\d+ panels` | `wrap_up` = true (amended 2026-10-20: ledger ruling Task 9 — SUMMARY alone fires only just before exit; the `MOVIE n/m panels` line starts the wrap-up) |
  | FACE | `^Error: (?:the vision model found no face in the seed image; pass --force to proceed anyway\.\|the main character's face fills only \d+% of the seed image's height \(minimum 15%\); a small face makes a weak identity reference\. Use a closer crop of the character, or pass --force to proceed anyway\.)$` | `face_problem` = true (`character_dataset.py:771-781`) |

  A later line for a panel replaces its earlier state (a retry's `ok` clears `failed`). `last_line` is the last non-empty collapsed line, including the incomplete tail, clipped to 300 characters. The incomplete tail is bounded: after each feed, when it exceeds 65536 bytes (64 KiB) and contains a `\r` before its trailing `\r`s, it is cut to start at that last `\r`, which leaves `collapse` of the eventual line unchanged (a `\r`-redrawn progress bar never grows the tail without bound). For `last_line`, an incomplete UTF-8 sequence at the end of the tail (a lead byte whose sequence needs more of the at most 3 trailing bytes than are present) is dropped before decoding, so a character split across reads never shows as U+FFFD (amended 2026-10-20: ledger ruling Task 9 — an unbounded tail and a split character in `last_line`; fixtures rewritten to the real failure tail, inline-retry and MOVIE lines).
- **MU56. Progress object.** For `story` and `movie` jobs:

  ```json
  {"phase": "4", "phase_title": "render", "rewrite": null,
   "phases": ["1", "1b", "2", "3", "4"], "redo": null,
   "panels_total": 6, "panels": {"1": {"state": "ok", "reused": false}, "2": {"state": "failed", "reason": "verification", "detail": "..."}, "3": {"state": "running"}},
   "panels_done": 1, "wrap_up": false,
   "stills": null, "last_line": "panel 3/6 ..."}
  ```

  `phases` mirrors `_phase_sequence` (`bin/ltx-movie:2212-2230`): `story` jobs: `["0"]` when `seed_upload`, then `["1"]`; `movie` jobs: `["0"]` when `seed_upload`, `"1"`, `"1b"`, `"redo"` for action `redo`, `"2"` unless mode `no_stills`, `"3"`, `"4"`. `panels_done` counts `ok` panels. `wrap_up` is set by the SUMMARY or MOVIE line and a panel's `running` state by PANEL_HDR or RETRY (MU55) (amended 2026-10-20: ledger ruling Task 9 — the MU55 extension). `stills` is non-null only while `phase == "2"`: `{"expected": E, "count": C}` with `E = 1` for chained and `P` for shots (chained Phase 2 renders only panel 1, `bin/ltx-movie:2149`), and `C` the number of files matching `^panel_\d{2}\.png$` in `<workspace>/generated/stories/<id>/images`. For character jobs: `{"kind": <kind>, "elapsed_s": <int seconds since started, or null>, "last_line": <text>, "face_problem": <bool>}`. For smoke jobs: `{"kind": "smoke", "elapsed_s": ..., "last_line": ..., "smoke": {"clip": "<STATE>/smoke/<id>/clips/panel_01.mp4", "clip_ok": <file exists and size > 0>}}`.
- **MU57. Page-side CR rule.** The page keeps, per job log view, the text after the last `\r` of each line, and an incomplete last line in a buffer until its `\n` arrives (the same rule as MU55).
- **MU58. `GET /api/jobs/<id>/log?offset=N`.** `N` must match `^[0-9]{1,15}$` (default 0), else 400 `{"error": "invalid offset"}`. Unknown job: 404. Reads up to `LOG_CHUNK = 262144` bytes from `N`. If the chunk ends inside a UTF-8 sequence (scan back at most 3 bytes for a lead byte whose sequence length exceeds the bytes present), those bytes are excluded so `next_offset` falls on a character boundary. Response 200 `{"offset": N, "next_offset": M, "size": <current file size>, "eof": M >= size, "text": <decoded utf-8, errors "replace">}`. `N >= size`: `text ""`, `next_offset = size`.
- **MU59. Light subprocesses.** `run_light(argv, cwd, env=None, timeout=None)` → `{"argv", "exit_code", "stdout", "stderr", "timed_out"}`; `timeout` None means `LIGHT_TIMEOUT = 60` s. It starts `subprocess.Popen(argv, cwd=cwd, env=env or dict(os.environ), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)` and calls `communicate(timeout=timeout)`; outputs are decoded UTF-8 `errors="replace"`. On `TimeoutExpired` it sends `SIGKILL` to the child's whole process group (`os.killpg(pid, SIGKILL)`, ignoring `ProcessLookupError`/`PermissionError`), drains with `communicate(timeout=5)` (if that also times out: `proc.kill()`, `proc.wait()`, empty outputs), and returns `exit_code` null, `timed_out` true and whatever output was drained. On `OSError` or `ValueError` from `Popen` (for example a NUL in an argv element), `exit_code` null and `stderr` `<ExceptionType>: <strerror or message>`. Because light children run in their own session, Ctrl-C in movie-ui's terminal no longer reaches them; each is still bounded by its timeout (amended 2026-10-20: ledger ruling Task 5 fix — `subprocess.run`'s timeout killed only the direct child, so grandchildren such as `ltx-movie`'s siblings and `sudo -n` survived; ruling Task 13 fix — `ValueError` caught as defence in depth). Every bin is run as `[sys.executable, <ws>/bin/<tool>, ...]` (as `bin/ltx-movie` runs its siblings, `:1156`), except `bin/story-server` (bash, run directly). Data endpoints that get a non-zero exit answer 502 `{"error": "<tool> exited <n>", "run": <run_light result>}`; a timeout answers 504 `{"error": "<tool> timed out after <timeout> s", "run": ...}` (60 s, or 300 s for the MU62 `lora-catalog` add and verify calls) **[spec choice]**.

### 10.4 Host

- **MU60. Capabilities and `GET /api/host`.** The probe thread computes, once at startup against the UI's own workspace, `render` and `stills` with V2's rules and `story_server` with V2's story rule; each `{"ok": <bool or null>, "reason": <text or null>, "checked": <utc or null>}` (`ok` null and reason `probing` until done). `GET /api/host?refresh=1` re-runs all three synchronously before answering **[spec choice: the story server starts and stops outside the UI]**. Response:

  ```json
  {"host": "<socket.gethostname()>", "platform": "<sys.platform>", "python": "<platform.python_version()>",
   "port": 8999, "state_dir": "<STATE>", "ui_workspace": "<realpath>",
   "default_workspace": "<default_workspace()>", "default_agent": "<id or null>",
   "api_key_present": true,
   "capabilities": {"render": {"ok": true, "reason": null, "checked": "..."},
                    "stills": {"ok": false, "reason": "stills dependencies not importable: ...", "checked": "..."},
                    "story_server": {"ok": true, "reason": "story server: SERVING vision", "checked": "..."}},
   "running_job": "<id or null>", "queue_length": 0}
  ```

### 10.5 LoRAs and models

- **MU61. `GET /api/loras?ws=[&model=M]`.** Runs `lora-catalog list --json` (with `--model M` when given). 200: the parsed object plus `"model": M or null`. Non-zero exit or unparsable stdout: 502 (MU59).
- **MU62. LoRA actions** (all answer 200 `{"run": <run_light result>}` whatever the exit code; timeouts 504 `{"error": "lora-catalog timed out after <n> s", "run": ...}`). `add` and `verify` run with `VERIFY_TIMEOUT = 300` s (`lora-catalog` hashes the LoRA file), `remove` with the 60 s default. Every client string that reaches the argv must be `_argv_safe` (V1), else 400 `{"error": "<key> contains invalid characters"}`, and must not start with `-`, else 400 `{"error": "<key> must not start with '-'"}`: `add`'s `path` (safe only; it is absolute), `id`, `kind`, `target`, `description`, `use_when`, `avoid_when`, every `base_models` and `triggers` item; `remove`'s `id`; every `verify` id (`ids` must be a list of strings, else 400 `{"error": "ids must be a list of strings"}`); and MU61's `?model=`. `add`'s `path` must start with `/`, else 400 `{"error": "path must be an absolute path"}` (amended 2026-10-20: ledger rulings Task 13 dispatch and fix — a NUL in a remove id, verify id or `?model=` reached `Popen` and answered 500, and a leading `-` would be read as a flag; final review fix-now item 4 — add and verify still used 60 s, contradicting the VERIFY_TIMEOUT ruling):
  - `POST /api/loras` body `{"ws", "path", "id", "kind", "target", "base_models": [str, ...], "triggers": [str, ...], "description", "use_when", "avoid_when", "default_strength", "strength_range": [lo, hi], "rank": int or null, "alpha": int or null}` → `lora-catalog add <path> --id <id> --kind <kind> --target <target>`, `--base-model M` per item, `--trigger T` per item, `--description D --use-when U`, `--avoid-when A` when non-empty, `--default-strength repr(float(s))`, `--strength-range "<lo>,<hi>"` (each `repr(float(...))`), `--rank N`/`--alpha N` when set. Body type errors: 400 `{"error": "<key> must be <type>"}`. `PATH` is a host path the user types; nothing is uploaded.
  - `POST /api/loras/remove` `{"ws", "id"}` → `lora-catalog remove <id>`.
  - `POST /api/loras/verify` `{"ws", "ids": [...]}` → `lora-catalog verify <ids...>` (no IDs: all). Adds `"results": [{"id", "ok": <bool>, "problems": [...]}]` parsed from `OK <id>` and `FAIL <id>: <problem>` lines.
- **MU63. `GET /api/models?ws=`.** `ws` is validated and otherwise unused (models are host-wide) **[spec choice]**. Lists every `models--*` directory of the three hubs of V3 (LTX `<LTX2_MLX_HF_HOME>/hub`, `<Z_IMAGE_HF_HOME or ~/hf_home>/hub`, `<HF_HOME or ~/.cache/huggingface>/hub`), each `{"repo": "<org>/<name>", "hub": "ltx" | "zimage" | "hf", "repo_dir", "intact": <bool>, "problems": [...], "bytes": <sum of blob sizes>}` with V3's `intact`. `repo` = the name after `models--`, split on its first `--` into org and name. Response `{"hubs": {"ltx": "<path>", "zimage": "<path>", "hf": "<path>"}, "models": [...]}` sorted by `(hub, repo)`. The Compose model and gemma dropdowns list the `ltx` repos plus free text; the story model is free text only **[spec choice: story models are served, not loaded from a cache]**.

### 10.6 Characters

- **MU64. Reads.** `GET /api/characters?ws=` runs `character list` and parses rows: header line (starting `NAME `) skipped; `no characters in ...` gives `[]`; rows matching `^(\S+)\s+\(invalid: (.*)\)$` give `{"name", "invalid": "<text>"}`; rows matching `^(\S+)\s+(\S+)\s+(dataset|untrained|trained)\s+(yes|no)\s+(yes|no)\s+(.+)$` give `{"name", "trigger", "status", "video": <bool>, "stills": <bool>, "phrase", "invalid": null}`. Response `{"characters": [...]}`. `GET /api/characters/<NAME>?ws=` runs `character show NAME`; 200 `{"character": <decoded JSON>, "files": [{"status": "ok" | "MISSING", "path"}], "dataset": {"contact_sheet": <path or null>, "stills": [<sorted paths of dirname(contact_sheet)/stills/<n> for every name n with STILL_FILE_RE.fullmatch(n) and os.path.isfile, STILL_FILE_RE = ^char_[0-9]{2}\.png$>]} | null, "face_problem": <bool>, "last_create_fields": <fields of the newest character-create job for (ws, name) or null>}`. `face_problem` is the MU55 FACE result of the newest `character-create` job for this `(ws, name)`. The stills rule (`STILL_FILE_RE` with ASCII `[0-9]`, not `\d`, plus a regular-file test) keeps Unicode digits and directories named like stills out of the gallery (amended 2026-10-20: ledger ruling Task 13 fix — `\d` matched non-ASCII digits and a directory named `char_01.png` was listed).
- **MU65. Character jobs** (all 201 `{"job": <summary>}`, field errors 400 `{"error": "invalid fields", "errors": [...]}`):
  - `POST /api/characters` `{"ws", "name", "phrase", "class_noun", "descriptor", "trigger", "seed", "seed_upload", "force"}`. Rules: `name` matches `^[a-z][a-z0-9-]{1,23}$` (`character name must match [a-z][a-z0-9-]{1,23}`); `phrase` a single-line string of 1..200 characters (`phrase is required`); exactly one of `seed_upload`, `descriptor` (`give exactly one of a seed image or a descriptor`); `descriptor` needs `class_noun` (`a descriptor needs a class noun`); `class_noun` null or `^[a-z]{3,12}$`; `trigger` null or `^[a-z][a-z0-9]{3,15}$`; `seed` null or an int >= 0; `seed_upload` per V1 rule 7; `force` bool. `phrase` and `descriptor` must also be `_argv_safe` (V1), else `phrase contains invalid characters` / `descriptor contains invalid characters`, and must not start with `-` after strip, else `phrase must not start with '-'` / `descriptor must not start with '-'`; `class_noun` and `trigger` are already confined by their regexes. An empty string `""` for `seed_upload`, `descriptor`, `class_noun` or `trigger` counts as null (in the rules and in the stored fields) (amended 2026-10-20: ledger rulings Task 6 CARRY / Task 13 dispatch — character strings reach `Popen` and argparse, so unsafe or flag-like values must fail early; the page sends `""` for an empty input). Kind `character-create`, argv MU41. Deeper rules stay with `bin/character` and appear in the job log.
  - `POST /api/characters/<NAME>/regenerate` `{"ws"}` → kind `character-regenerate`.
  - `POST /api/characters/<NAME>/train` `{"ws", "video", "stills", "force"}`; at least one of `video`, `stills` true (`choose video, stills or both`) → kind `character-train`.
  - Force: the page re-submits `POST /api/characters` with `last_create_fields` and `force: true`; it is shown only when `face_problem` is true. The face check refuses before the character directory exists (`character_dataset.py:882-887` vs `:900-901`), so the forced create is a fresh create.

### 10.7 Compose and jobs

- **MU66. Compose.** `POST /api/preview` (fields of MU36) → 200 `{"argv": <list or null>, "command": <shlex.join or null>, "errors": [<V1 failure lines>]}`; `argv` is null when V1 fails. `POST /api/validate` → 200 `{"ok": <bool>, "checks": [...], "argv", "command"}`. `POST /api/jobs` → MU44. For action `smoke`, the job is kind `smoke` (MU52).
- **MU67. Job reads.** Summary object: `{"id", "kind", "state", "workspace", "story_id", "character", "created", "started", "ended", "exit_code", "error", "queue_position", "command", "progress"}` with `state` from `status.json` or `"queued"` when absent and the ID is in `queue.json` (else `"unknown"`); `queue_position` 1-based or null; `command = shlex.join(argv)`; `progress` per MU56 for `starting`/`running` jobs, else null. `GET /api/jobs` → `{"running": <summary or null>, "queued": [<summaries in queue order>], "history": [<final or lost jobs, newest created first, at most 200>], "blocked_by": {"job": <lost job id>, "pgid": <int>} | null}`; `blocked_by` names the first job (in `list_job_ids` order) whose `orphan_info` (MU26) is non-null, the same scan that stops MU30's dispatch, else null (amended 2026-10-20: ledger rulings Task 4 fix (b) and Task 12 — a queue held by a live orphan must say why in the page). `GET /api/jobs/<id>` → `{"job": <job.json>, "status": <status.json or {"state": "queued"}>, "progress": <MU56 or null>, "orphan": <MU26 object or null>, "window": {"start": <started or null>, "end": <ended or null>}}`; unknown ID: 404.
- **MU68. Job actions.**
  - `POST /api/jobs/<id>/cancel` `{}`: queued → removed from the queue, status `cancelled` (MU16), 200 `{"state": "cancelled"}`; `starting`/`running` → `cancel` marker created, 202 `{"state": "cancelling"}`; else 409 `{"error": "job <id> is not queued or running"}`.
  - `POST /api/queue/move` `{"id", "direction": "up" | "down"}`: the job must be queued, else 409 `{"error": "job <id> is not queued"}`; swaps it with its neighbour (no-op at an end); 200 `{"queued": [...]}`. Bad direction: 400.
  - `DELETE /api/jobs/<id>`: unknown job 404. The body is optional: a missing `Content-Length` or `Content-Length: 0` counts as no body (`{}`); any other length is read under MU10 step 6's JSON rules. Under `STORE_LOCK`: when the job's `orphan_info` (MU26) is non-null, the body must be exactly `{"confirm": true}` (key set exactly `{"confirm"}`, value the JSON `true`, so `1` is refused), else 409 `{"error": "job <id> still has a live process group <pgid>; kill it first, or delete with confirm to unblock the queue anyway"}`. Then state `done`, `failed`, `cancelled` or `lost` → removes `smoke/<id>/` first (smoke jobs) and then `jobs/<id>/`, each with `shutil.rmtree` (errors not ignored), 200 `{"deleted": "<id>"}`; an `OSError` from either removal answers 500 `{"error": "cannot delete job <id>: <strerror>"}` and, when the smoke removal failed, the job record is kept; else 409 `{"error": "job <id> is not finished"}`. The server's job and progress caches for the ID are dropped only when `jobs/<id>/` is gone. Story outputs are never touched (amended 2026-10-20: ledger rulings Task 4 / Task 12 fix rounds 1-2 / Task 17 — deleting a lost job silently unblocked the dispatcher while its orphan still held the GPU, a confirm keeps an escape for a reused pgid without killing it, `rmtree(ignore_errors=True)` swallowed failures, and the smoke directory goes first so a failure never orphans it).
  - `POST /api/jobs/<id>/kill-orphan` `{"confirm": true}`: `confirm` must be the JSON value `true`, else 400 `{"error": "confirm must be true"}`; the job must be `lost` with an alive orphan group, else 409 `{"error": "job <id> has no live orphan process group"}`; then `os.killpg(pgid, signal.SIGKILL)` (a `ProcessLookupError` counts as killed) and 200 `{"killed": <pgid>}`. A `PermissionError` answers 409 `{"error": "cannot kill process group <pgid>: <strerror>"}` (amended 2026-10-20: ledger ruling Task 12 fix — `PermissionError` was swallowed and reported as success).
- **MU52. Smoke render.** Job kind `smoke`; V1 (smoke subset), V2 `render`, V3 video model and gemma, V4 (chosen video catalog items and free paths only), V5 `catalog compatibility` (video items only) run; every other record is `skip`. `stills_loras` and `characters` are ignored for smoke. At creation the server writes `STATE/smoke/<id>/` (0700) and `STATE/smoke/<id>/manifest.json`:

  ```json
  {"schema_version": 3, "story_id": "movie-ui-smoke",
   "panels": [{"index": 1, "conditioning": "t2v", "image_path": null,
               "panel_text": "A slow camera pan across a quiet forest clearing at golden hour, leaves moving gently in the wind."}]}
  ```

  argv: `[py, ws/bin/ltx-mlx-render, STATE/smoke/<id>/manifest.json, STATE/smoke/<id>/smoke.mp4, "--frames", "9", "--width", "512", "--height", "320", "--frame-rate", "24", "--clips-dir", STATE/smoke/<id>/clips]` + `["--model", M, "--gemma", G]` + `["--lora", "<path>:<repr(float(s))>"]` per item of `ordered(video_loras)` + `["--no-low-ram"]` when set + `["--panel-timeout", "1800"]`. The geometry is 512x320, not the brief's 512x288 (D4). Run records still land in `<ws>/generated/stories/movie-ui-smoke/runs/` (D5).

### 10.8 Stories

- **MU69. Reads.** `GET /api/stories?ws=` → `{"stories_dir": "<ws>/generated/stories", "stories": [...]}`, one entry per directory whose name passes MU38 and is not `movie-ui-smoke`, sorted by directory `st_mtime` descending: `{"id", "story_md": <bool>, "checks": {"source", "hard": <len hard>, "advisory": <len advisory>, "verdict"} | null (from story_checks.json, [STORY] 2.5; unreadable: null), "stills": <count of images/panel_NN.png>, "clips": <count of clips/panel_NN.mp4>, "movie": <movie.mp4 exists>, "mtime": <utc>}`. `GET /api/stories/<STORY>?ws=` (404 when the directory is missing) → `{"id", "dir", "files": [<sorted top-level names>], "story_md": {"text", "sha256"} | null, "checks": <story_checks.json or null>, "plan_loras": <plan.json "loras" or null>, "plan_mode": <plan.json "mode" or null>, "catalog_loras": <catalog_loras.json or null>, "stills": [<sorted abs paths images/panel_NN.png>], "clips": [<sorted abs paths clips/panel_NN.mp4>], "movie": <abs path or null>, "summary": <newest runs/*/story_summary.json by name or null>, "last_fields": <fields of the newest story/movie job for (ws real, id) or null>}`. `story.md` is read as bytes; `sha256` is of the bytes; `text` is the UTF-8 decode (`errors="replace"`). Containment and strictness: every story JSON file (`story_checks.json`, `plan.json`, `catalog_loras.json`, `story_summary.json`) is read strictly (UTF-8, `parse_constant` rejecting `NaN`/`Infinity`), and an unreadable, non-UTF-8 or non-strict file gives null, never a 500 (`ltx-story-video` writes with `json.dump`'s default `allow_nan`). The list skips a story directory whose realpath is not inside `realpath(<ws>/generated/stories)`, and a missing or unlistable `stories` directory gives `[]`; the detail answers 404 for such a directory. Inside a story directory, every file (story.md, the JSON files, stills, clips, `movie.mp4`, run summaries) counts only when its realpath is inside the story directory's realpath; an escaping symlink is treated as absent (amended 2026-10-20: ledger ruling Task 14 fix — NaN in pipeline-written JSON or an EACCES story directory gave 500 on detail and list, and symlinks could reach files outside the story).
- **MU70. `PUT /api/stories/<STORY>/story.md`** `{"ws", "text": <str>, "base_sha256": <64 hex or null>}`. Before the steps: `text` not a string: 400 `{"error": "text must be a string"}`; `base_sha256` neither null nor 64 lower-case hex: 400 `{"error": "base_sha256 must be 64 hex digits or null"}`; `text.encode("utf-8")` fails (a lone surrogate): 400 `{"error": "text must be encodable as UTF-8"}`; `story.md` exists (`lexists`) but its realpath is outside the story directory (an escaping symlink): 404 `{"error": "not found"}`. Steps 1-4 run under `STORE_LOCK` (amended 2026-10-20: ledger ruling Task 14 fix — a PUT through an escaping symlink wrote outside the story, and an unencodable text raised).
  1. A job in state `starting` or `running` with this workspace and `story_id`: 409 `{"error": "story <id> is in use by job <job id>"}` **[spec choice: editing under a running render would race it]**.
  2. `story.md` exists but cannot be read (for example mode 0): 409 `{"error": "story.md exists but cannot be read; fix its permissions and reload", "sha256": null}`, and nothing is written. `base_sha256` null requires that `story.md` does not exist; otherwise the current file's sha256 must equal it. Mismatch: 409 `{"error": "story.md changed since it was loaded; reload it", "sha256": <current or null>}` (amended 2026-10-20: final review fix-now item 1 — an unreadable story.md looked absent, so a null base overwrote it without a backup: data loss).
  3. If `story.md` exists, copy it (bytes, `shutil.copyfile`) to `story.md.bak-<%Y%m%dT%H%M%SZ>`; if that name exists, append `-2`, `-3`, ... until free.
  4. Atomically write `text.encode("utf-8")` (no newline normalisation) to `story.md`. The story directory must already exist (404 otherwise).
  5. 200 `{"sha256": <new>, "backup": <path or null>}`.

## 11. Traces

- **MU71. Agents.** `GET /api/traces/agents` → `{"default": <default_agent()>, "agents": [...]}`; one entry per `fleet_lib.agent_ids_on_disk()` ID: `fleets_dir` = `A/current/qwen-agent-workspace/fleets` when `A/current` exists, else `<UI WS>/fleets` (as `_status_port`, `bin/qwen-agentd:1303-1322`); `port, files = fleet_lib.agent_port(fleets_dir, id)`. No files: `port = fleet_lib.DEFAULT_PORT`, `port_source "default"`. Files with one port: `port_source "registry"`. Files that disagree: `port null`, `error "agent '<id>' has different ports in <files> in <fleets_dir>"`. Entry: `{"id", "port", "port_source", "url": "http://127.0.0.1:<port>" or null, "error": <text or null>}`. movie-ui reads only registry JSON (no token in it, `fleet_lib.py:151-152`) and never `fleet.env`.
- **MU72. Recent.** `GET /api/traces/recent?agent=<id or all>&n=<N>`: `n` matches `^[0-9]{1,3}$` and is 1..100 (`fleet_lib.TRACE_RECENT_MAX`), default 10 (`TRACE_RECENT_DEFAULT`), else 400 `{"error": "n must be 1 to 100"}`; `agent` default `all`; an unknown agent: 404. For each selected agent with a URL: `fleet_lib.fetch_recent(url, n)`. Error `daemon not reachable at <url>` is reported as `daemon: not reachable at <url>` (the `qwen-agentd status` wording, `bin/qwen-agentd:1343`, D9); other error strings verbatim. Merge: the responses' `traces` items, de-duplicated by `trace_id` keeping the item with the smallest `start` (ties: lowest agent ID), newest `start` first, cut to `n`. Each item gains `"seen_on": [<sorted agent IDs that returned it>]` and `"agents": sorted(set(seen_on) | {hop.rpartition("@")[2] for hop in delegated})`. Response `{"traces": [...], "errors": [{"agent", "error"}]}` (200 even when every agent failed). The page shows the columns start (local time), root span (`kind name`), agents, duration (`dur_ms`), status, span count (`spans`), and filters by agent (`agents` contains), status, kind (`TRACE_KINDS`), and name substring, client-side.
- **MU73. One trace.** `GET /api/traces/<TRACE>?agent=<id>[&format=text]`: `agent` defaults to `default_agent()`; missing or unknown: 404 `{"error": "unknown agent"}`. `fleet_lib.fetch_trace(url, trace_id)` (`http.client`, `Host: 127.0.0.1:<port>`, no `Origin`, timeout `TRACE_QUERY_TIMEOUT` = 20 s = 2 x `TRACE_FANOUT_DEADLINE` + 8 s). Error: 502 `{"error": <MU72 wording>}`. Strict post-check: a result `fetch_trace` accepted that `json.dumps(result, allow_nan=False)` refuses (it holds `NaN` or `Infinity`, which `fleet_lib`'s parser allows) is treated as an error: 502 `{"error": "the daemon at <url> returned an unrecognized trace response"}`; MU72 applies the same check to each `fetch_recent` result and MU74's save to the fetch it writes. movie-ui calls `fleet_lib.fetch_trace`/`fetch_recent` and never its own HTTP client (GC3, GC7) (amended 2026-10-20: ledger ruling Task 15 fix — strict JSON is enforced by a post-check, not by a duplicate loopback client). Success: 200 `{"agent", "result": <fetch result>, "skew": [<span_id of every record whose parent is present and whose start is below the parent's start>], "text": "\n".join(fleet_lib.render_trace(result)) + "\n"}` (`text` only with `format=text`). `text` is byte-for-byte what `qwen-agentd trace <id>` prints on the same host (`bin/qwen-agentd:1426`).
- **MU74. Saved traces.** `POST /api/traces/<TRACE>/save` `{"agent"}` fetches as MU73 and writes MU20 (overwriting), 200 `{"saved": "<id>", "path"}`. `GET /api/traces/saved` → `{"saved": [{"trace_id", "agent", "saved_at", "spans": <len records>, "start": <earliest record start or null>, "invalid": <bool>}]}` sorted by `saved_at` descending. `GET /api/traces/saved/<TRACE>` → MU73's success shape from the file (`text` always included), 404 when absent, 422 `{"error": "saved trace is invalid"}` when invalid. `DELETE /api/traces/saved/<TRACE>` → 200 `{"deleted": "<id>"}` or 404. Saved traces are viewable while every daemon is down.
- **MU75. Job association.** The Jobs detail lists traces from `GET /api/traces/recent?agent=all&n=100` whose `start` lies in `[window.start, window.end or now]` (MU67), compared as epoch seconds. Injecting a trace ID into jobs (`QWEN_AGENT_TRACE_ID`) is out of scope.

---

## 12. The page (`static/movie-ui/`)

- **MU76. Assets and rules.** `index.html` (one `<link rel="stylesheet" href="/static/app.css">`, one `<script src="/static/app.js" defer></script>`, no inline script, no `style=` attribute, no `on*=` attribute), `app.js` (vanilla ES2017, no modules loaded from elsewhere, no `eval`/`new Function`), `app.css` (light and dark via `@media (prefers-color-scheme: dark)`). No asset contains `http://` or `https://` (MUT24). No `alert`, `confirm` or `prompt`: every confirmation uses the in-page dialog `#confirm` (`#confirm-text`, `#confirm-yes`, `#confirm-no`).
- **MU77. Token.** On load, `app.js` reads `t` from `location.search`; if present, stores it in `sessionStorage["movie-ui-token"]` and calls `history.replaceState(null, "", "/")`. Every `fetch` to `/api/` sends `X-Movie-UI-Token`; media URLs append `&t=<token>` to `/files?...`. A 401 shows the banner `#banner` with `The token was rejected. Open the URL that movie-ui printed in its terminal.`
- **MU78. Header.** `#ws-select` (MU45 entries; label plus `kept for data (<size>)`/`would be pruned` tags; default `default`), `#ws-typed` + `#ws-typed-use` (MU46), badges `#badge-render`, `#badge-stills`, `#badge-story` (text `render: ok` or `render: unavailable` with the reason as visible text in `#badge-reasons`), `#badge-refresh` (`GET /api/host?refresh=1`), `#badge-apikey` (`ANTHROPIC_API_KEY: set|not set`), `#header-job` (running job ID, phase and `panels_done/panels_total`), `#header-queue` (`queue: N`). Polling: `GET /api/jobs` every 2 s.
- **MU79. Tabs.** Buttons `#tab-compose`, `#tab-stories`, `#tab-characters`, `#tab-loras`, `#tab-jobs`, `#tab-traces` show `#panel-<name>`. Changing `#ws-select` reloads options, LoRAs, characters and stories for that workspace.
- **MU80. Compose.** Controls: `#c-story-id`, `#c-narrative`, `#c-goal`, size radio `#c-size-panels`/`#c-size-length` with `#c-panels`/`#c-length`, `#c-fps`, `#c-frames` with `#c-frames-check` (live `(n-1)%8==0 and n>=9`) and `#c-seconds-per-panel` (`frames/fps`, two decimals), resolution radio `#c-res-size`/`#c-res-seed` with `#c-width`, `#c-height`, `#c-seed-file` (uploads via MU53 on change), `#c-mode` (`chained` default, `shots`, `no_stills`), `#c-model` and `#c-gemma` (input with a `datalist` of `ltx` repos), `#c-story-model`, `#c-auto-lora` (checked = auto picks on), `#c-video-loras` and `#c-stills-loras` (rows added by `#c-add-video-lora`/`#c-add-stills-lora`: a select of catalog entries from `GET /api/loras?model=<model>` filtered to `target` video, or the stills list from `?model=Tongyi-MAI/Z-Image-Turbo` filtered to `target` stills, plus a "path..." option for a free path; a range input bounded to the entry's `strength_range` with step 0.05, or (0, 2] for free paths; a remove button), `#c-lora-order` (the MU39 order), `#c-characters` (multi-select of `trained` characters), advanced `#c-story-legacy`, `#c-judge` (disabled when the API key is absent), `#c-no-low-ram`, `#c-panel-timeout`, `#c-overwrite`. Every change debounces 300 ms and calls `POST /api/preview`, showing `#c-command` and `#c-errors`; `#c-copy` copies the command (`navigator.clipboard.writeText`). `#c-validate` calls `POST /api/validate` and lists each check in `#c-checks` as `<status> <id> <name>: <detail>`. Buttons: `#c-write-story` (action `story`), `#c-smoke` (action `smoke`), `#c-run-all` (action `movie`); disabled with the visible reason when the needed capability is not ok (`#c-run-all` and `#c-smoke`: render, and stills unless mode `no_stills` for `#c-run-all`; `#c-write-story`: story_server). A 409 shows the returned checks.
- **MU81. Stories.** `#s-list` rows (`data-story-id`) with the MU69 columns; detail `#s-detail`: `#s-editor` (textarea of `story.md`), `#s-save` (MU70; a 409 shows its error in `#s-save-status` and offers `#s-reload`), `#s-checks` (hard and advisory message lists), `#s-picks` (plan LoRA picks, read-only), `#s-gallery` (stills as `<img>`, one `<video controls>` per clip, `movie.mp4`), `#s-render` (opens Compose prefilled from `last_fields` with action `movie`; when `last_fields` is null, prefilled with this `story_id`, `panels` from `story_checks.json` `panels`, else the defaults; the user must enter the narrative), `#s-regenerate` (in-page confirm, then action `regenerate` with `last_fields`), and for shots stories `#s-redo-panels` (comma list) + `#s-redo` (action `redo`).
- **MU82. Characters.** `#ch-list` (`data-character` rows: name, status, video, stills, phrase); new form `#ch-name`, `#ch-phrase`, `#ch-class`, `#ch-descriptor`, `#ch-trigger`, `#ch-seed`, `#ch-seed-file` (MU53), `#ch-create` (disabled unless stills is ok); detail `#ch-detail` with `#ch-gallery` (contact sheet then stills), `#ch-accept` (reveals `#ch-train-form`), `#ch-train-video`, `#ch-train-stills`, `#ch-train-force`, `#ch-train` (disabled unless render is ok, or when status is `dataset`, with the reason `fewer than 12 stills kept; regenerate the dataset`), `#ch-regenerate` (in-page confirm), `#ch-force` (only when `face_problem`).
- **MU83. LoRAs & Models.** `#l-table` (catalog entries: id, kind, target, strength and range, triggers, base models, verify result), `#l-verify-all`, add form `#l-path`, `#l-id`, `#l-kind`, `#l-target`, `#l-base-models` (comma list), `#l-triggers` (comma list), `#l-description`, `#l-use-when`, `#l-avoid-when`, `#l-default-strength`, `#l-range-lo`, `#l-range-hi`, `#l-rank`, `#l-alpha`, `#l-add`; per-row remove with in-page confirm; output in `#l-output`; `#m-table` (MU63 rows: hub, repo, intact, problems, size).
- **MU84. Jobs.** `#j-running` (summary, `#j-progress`: phase sequence with the current phase marked, rewrite, `panels_done/panels_total`, per-panel states, stills count), `#j-log` (live log; polls MU58 every 1 s from the last `next_offset`), `#j-cancel` (in-page confirm), `#j-queue` (rows with `data-job-id`, up/down/cancel buttons), `#j-history` (state, duration `ended - started`, exit code, story link opening the Stories detail, delete with in-page confirm, Kill orphan when `orphan.alive` with in-page confirm sending `{"confirm": true}`), `#j-traces` (MU75). `#j-blocked` (a `<p class="warning">`, hidden when `blocked_by` is null) shows, from `GET /api/jobs`'s `blocked_by` (MU67), the text `Queue waiting: lost job <job> still has a live process group <pgid>. Kill orphan or Delete that job to unblock the queue.` When Delete's DELETE answers MU68's live-orphan 409 (error matching `still has a live process group`), the page asks in `#confirm` `Its processes are still running and may hold GPU memory. Delete the record anyway and unblock the queue?` and, on yes, re-sends the DELETE with the body `{"confirm": true}` (amended 2026-10-20: ledger rulings Task 4 CARRY, Task 12 CARRY and Task 16 dispatch — a queue blocked by an orphan (MU30) must show its reason and both ways out).
- **MU85. Traces.** `#t-agent` (agents plus `all`, default `all` for recent), filters `#t-filter-status`, `#t-filter-kind`, `#t-filter-name`, `#t-refresh`, `#t-auto` (5 s auto-refresh, off by default), `#t-recent` (rows `data-trace-id`), `#t-errors` (per-agent errors), view `#t-view`: header (trace ID, start, duration, agents, `missing` with reasons, `truncated` agents, `clock skew: N span(s) start before their parent` when `skew` is non-empty), `#t-waterfall` (one row per span in `render_trace` order: depth-first from roots by `(start, span_id)`, indented by depth; bar left `= (start - t0) / total`, width `= max(dur_ms / 1000 / total, 0.002)`, where `t0` is the earliest start and `total = max(start + dur_ms/1000) - t0` (at least 0.001); colour class `agent-<i>` with `i` = the agent's index in the sorted agent list modulo 8; a status badge; skewed rows marked), `#t-attrs` (clicked span: every record field and `attrs` key/value), `#t-text` (the `text` field in a `<pre>`), `#t-save`, `#t-download` (a `Blob` of the result JSON via `URL.createObjectURL` and an `<a download="trace-<id>.json">`), `#t-saved` (list with view and delete). A trace opened from the recent list is fetched from the first agent in `seen_on`.

---

## 13. Release-prune fix

- **MP1. `fleet_lib.release_holds_data(release_dir)`.** Placed after `releases_to_prune`:

  ```python
  def release_holds_data(release_dir):
      """True iff <release_dir>/qwen-agent-workspace/generated/ holds a regular file at any depth (movie-ui spec MP1)."""
      top = os.path.join(release_dir, WS_SUBDIR, "generated")
      if os.path.islink(top) or not os.path.isdir(top):
          return False
      for dirpath, _dirnames, filenames in os.walk(top, followlinks=False):
          for name in filenames:
              try:
                  if stat.S_ISREG(os.lstat(os.path.join(dirpath, name)).st_mode):
                      return True
              except OSError:
                  continue
      return False
  ```

  `import stat` is added to `fleet_lib.py`'s import block in alphabetical position. Empty directories and symlinks do not count. `generated/` is git-ignored (`.gitignore:2`) and no file under it is tracked, so a freshly staged release returns `False`.
- **MP2. `releases_to_prune(present, current, state, protected=())`.** One added line after `keep.add(state["from"])`'s block: `keep.update(protected)`. Docstring: `"""Release names to unstage: never current, state["from"], the 3 newest, or a protected name (F88a, movie-ui spec MP2)."""`. With `protected` empty the result is identical to today's (`tests/test_fleet_lib.py:1048-1053` unchanged).
- **MP3. `_confirm_switch`** (`bin/qwen-agentd:1213-1220`) becomes:

  ```python
      def _confirm_switch(self):
          d = fleet_lib.deploy_root(self.host_id)
          st = fleet_lib.read_state(state_path(d))
          new = {"from": st["from"], "to": st["to"], "status": "ok", "attempts": 0, "bad_tags": st["bad_tags"]}
          fleet_lib.write_state(state_path(d), new)
          LOG.info("update: now running %s (from %s)" % (new["to"], new["from"]))
          releases = os.path.join(d, "releases")
          present = os.listdir(releases)
          protected = set(t for t in present if fleet_lib.release_holds_data(os.path.join(releases, t)))
          doomed = fleet_lib.releases_to_prune(present, self.version, new, protected)
          for tag in fleet_lib.releases_to_prune(present, self.version, new):
              if tag not in doomed:
                  LOG.info("update: keeping %s: generated/ holds data" % tag)
          for tag in doomed:
              unstage_release(d, tag, log_to_daemon)
  ```

  `unstage_release` is unchanged (failed-staging cleanup unaffected). The fix takes effect from the first update **into** the fixed release (pruning runs in the new daemon after the switch). Data-holding releases accumulate until the user removes them; movie-ui labels them "kept for data" with their size (MU33). A queued movie-ui job whose data-less release was pruned fails at dispatch with `workspace no longer exists (removed by self-update)` (MU30). There is no daemon-to-UI coupling.

---

## 14. Tests

### 14.1 Rules

GC8 holds. Every test that touches movie-ui sets `HOME` to a temp directory (`monkeypatch.setenv("HOME", ...)` in-process; an explicit `env` for subprocesses), creates STATE under it, and sets `movie_ui_lib.CANCEL_GRACE_S` (or `--grace`) to at most 1.0 s. In-process HTTP tests use `make_server(0, ...)` on a thread and `http.client` (never `urllib`). No test runs a real `bin/ltx-movie` beyond `--help` (MUT3) and never a real render. Child processes in runner tests are `sys.executable -c` scripts.

### 14.2 Helpers (`tests/movie_ui_testutil.py`, `tests/fixtures/movie_ui/`)

| Helper | Behaviour |
|---|---|
| `make_stub_workspace(tmp)` | creates `<tmp>/ws/bin/` with executable stubs `ltx-movie`, `lora-catalog`, `character`, `ltx-mlx-render` (Python, `#!<sys.executable>`) and `story-server` (`#!/bin/sh`), and `<tmp>/ws/generated/stories/`; each stub appends its argv as one JSON line to `<ws>/stub_calls.jsonl` and behaves per `<ws>/stub_config.json` (`{"<tool> <subcommand>": {"exit": n, "stdout": "...", "stderr": "...", "sleep": s, "write": {"<relpath>": "<text>"}}}`); `ltx-movie --help` prints `fixtures/movie_ui/ltx-movie-help-current.txt` unless configured |
| `fixtures/movie_ui/ltx-movie-help-current.txt` | the real `python3 bin/ltx-movie --help` output at the implementation commit |
| `fixtures/movie_ui/ltx-movie-help-old.txt` | the same with the option lines of `--story-only`, `--story-legacy`, `--no-auto-lora`, `--judge`, `--goal`, `--gemma` removed |
| `fixtures/movie_ui/render-chained.log`, `render-shots-redo.log`, `story-only.log`, `character-face.log` | canned logs using the real markers of MU55 (including `\r` progress bars and a FAILED-then-ok retry) |
| `make_hf_cache(root, repo, files, refs=True, incomplete=0, broken=())` | builds `hub/models--org--name/{blobs, snapshots/<rev>, refs/main}` with snapshot symlinks into `blobs` |
| `FakeDaemon(recent=..., traces=..., status=200)` | `http.server` on 127.0.0.1 port 0 answering `GET /traces/recent?n=` and `GET /trace?id=` with canned bodies; records every request's headers |
| `make_agents_home(home, agents)` | builds `~/agents/<id>/{current -> releases/<tag>, releases/<tag>/qwen-agent-workspace/bin/ltx-movie, current/qwen-agent-workspace/fleets/<f>.json, update-state.json}` and `~/.local/bin/qwen-agent` wrappers (`fleet_lib.wrapper_bytes`) |
| `api(server, method, path, body=None, token=..., headers=None)` | one `http.client` request; returns `(status, headers, parsed JSON or bytes)` |

### 14.3 Movie-UI tests

| ID | File | Covers | Pass condition |
|---|---|---|---|
| MUT1 | builder | MU39, MU40, MU41 | golden argv for at least 10 field sets: story; regenerate; movie with panels; movie with length; seed image; explicit resolution; shots + redo `[7,3,3]` -> `--redo 3,7`; no-stills; video LoRAs submitted as `[style, motion, free, physics]` emitted as `[motion, physics, style, free]` (MU39); stills LoRAs; characters; every advanced flag; `--no-review` last; character create/regenerate/train |
| MUT2 | http | MU40, MU44, MU66 | for 3 field sets, `POST /api/preview`'s `argv` equals the `argv` in the created job's `job.json` |
| MUT3 | builder | MU37, MU47, V1 rule 18 | `help_flags` on both fixtures; real `bin/ltx-movie --help` parses to a set containing every MU37 flag; the old fixture gives `supported.judge == false` and V1 fails `... does not support --judge` when `judge` is true; cache hit while mtime unchanged, miss after `os.utime` |
| MUT4 | checks | MU38, V1 | table: every V1 error string triggered alone; story IDs `../x`, `a/../b`, `a..b`, `.x`, 81 chars, `movie-ui-smoke` refused; `a.b-c_9` accepted; narrative `-x` refused |
| MUT5 | checks | V3 | complete cache passes; missing shard; `.incomplete` blob; broken snapshot symlink; empty `.safetensors`; absent repo; two snapshots without `refs/main`; absolute-path model checked in place; Z-Image scoped vs fallback hub |
| MUT6 | checks | V4 | stub `verify` exit 0 passes, exit 1 fails with its `FAIL` lines; auto set includes compatible video and stills entries and excludes stills in `no_stills`; legacy engine excludes auto; free path with a valid header passes; truncated header, zero length, non-JSON fail |
| MUT7 | checks | V5 | incompatible id; path/kind mismatch; strength outside range; two style LoRAs; untrained character fails; stills base model mismatch fails; video base model mismatch is `skip`, match is `pass` |
| MUT8 | checks | V6, D17 | stub dry run exit 0 passes, exit 2 fails with its stderr; a stub that sleeps past a monkeypatched 1 s timeout fails with the timeout text; the stub saw `STORY_PIPELINE_LOGGED=1` |
| MUT9 | checks | V2, MU60 | fake `LTX2_MLX_BIN` executable vs missing; `PATH` with and without stub `ffmpeg`/`ffprobe`; stills probe pass/fail via a stub interpreter path; story-server stub `SERVING vision` passes, `STOPPED` fails, exit 4 fails; judge key present/absent; `refresh=1` re-probes |
| MUT10 | jobs | MU16, MU21, MU22, MU24 | runner on real children: exit 0 -> `done`, exit 3 -> `failed`, unstartable argv -> `failed` with `cannot start:`; `log.txt` holds child output and `[movie-ui]` lines; status keys exactly MU16's |
| MUT11 | jobs | MU23, MUK4 | cancel a TERM-respecting child -> `cancelled` within grace; a TERM-ignoring child with grace 1 s -> SIGKILL, `cancelled` within 2 s; a grandchild in the same group is gone; a grandchild started with `start_new_session=True` (as `ltx2_mlx_video_skill.py:341`) is gone (D1) |
| MUT12 | jobs | MU22 | runner started directly with no server: final status written |
| MUT13 | jobs | MU29, MU31, MU26, MU68, MUK5 | restart with a live runner -> `running` (lock held); `kill -9` of the runner -> `lost` on the next tick and at startup; the orphan child's group reported `alive`; `kill-orphan` without `confirm` 400, with it kills the group |
| MUT14 | jobs | MU18, MU28, MU30, MU31, MU68 | FIFO order; move up/down and no-op at ends; cancel queued; with 3 sleeping jobs, sampling every 0.1 s never finds two locks held; queue survives restart; a removed workspace fails with the exact message; job ID regex |
| MUT15 | jobs | MU1, MU3, MU4, MU6 | subprocess `bin/movie-ui --port <free>` twice: second exits 2 naming the lock; a held port exits 2 with the port message; `--port 80` exits 2; first prints the two MU6 lines and the URL token works |
| MUT16 | progress | MU55, MU56 | each fixture log parses to its expected progress object; feeding in 7-byte slices equals one feed; CR collapse; a FAILED-then-ok panel ends `ok`; phases list per mode; stills count from files; FACE sets `face_problem` |
| MUT17 | http | MU58 | offsets chain to EOF; a 300 KiB log returns 262144 bytes first; a 3-byte character straddling the boundary is never split |
| MUT18 | http | MU10, MU11, MUK6 | for every `ROUTES` entry, `sample_path` with no token and with a wrong token answers 401; with the token, an unknown `/api/x` answers 404 and a wrong method 405; `Host: evil:port` 403; `Origin: http://evil` 403; `Origin: http://localhost:<port>` accepted; body over 25 MiB 413 (header only); `text/plain` 415; missing Content-Length 411; bad JSON 400 |
| MUT19 | http | MU54 | `..` traversal and a symlink pointing outside `generated/` both 403; `?t=` token accepted; Range `0-9`, `10-`, `-5` give 206 with exact bytes and headers; `size-` gives 416; bad Range form ignored (200) |
| MUT20 | http | MU70 | PUT with the loaded sha writes and creates `story.md.bak-<stamp>`; a stale sha 409 with the current sha; a second backup in the same second gets `-2`; a running job on the story 409 |
| MUT21 | http | MU53 | PNG, JPEG, WebP accepted with the exact `upload_id`; type/magic mismatch 400; 20 MiB + 1 413; re-upload of the same bytes returns the same ID |
| MUT22 | traces | MU71-MU74, D9 | against `FakeDaemon`: requests carry `Host: 127.0.0.1:<port>` and no `Origin`; recent merge dedups by trace ID and orders newest first with `agents`/`seen_on`; daemon down gives `daemon: not reachable at http://127.0.0.1:<port>`; save, list, load, delete; `text == "\n".join(fleet_lib.render_trace(result)) + "\n"`; `skew` lists a child that starts before its parent; registry port vs default port vs disagreeing registries |
| MUT23 | http | MU33-MU35, MU45, MU46 | with `make_agents_home`: candidates, labels, `is_current` merge, default `current` path, `kept_for_data` vs `would_prune` vs `kept`, `data_bytes`; a typed path without `bin/ltx-movie` 400 |
| MUT24 | http | MU12, MU76 | page headers exactly MU12; static files contain no `http://`, `https://`, `<script>` with content, `style=`, ` on[a-z]+=`, `alert(`, `confirm(`, `prompt(` |
| MUT25 | builder | GC1-GC5, MUK7 | `/usr/bin/python3 -m py_compile` and `python3 -m py_compile` on every new/changed file; a source scan of new Python files finds no `import cgi`, `urllib`, `shell=True`, line-initial `match `, and no `-> .* \| ` or `: .* \| None` annotation |
| MUT26 | builder | MUK3 | `git diff --quiet 22dc4a1 -- <the pipeline files of 0.3>` exits 0 (skipped when not in a git checkout) |
| MUT27 | (controller, Playwright, not pytest) | MU76-MU85, MUK8 | against a stub workspace and `FakeDaemon`: open the printed URL; compose; validate (all pass); Write story -> job done -> edit and save `story.md` -> Render -> progress reaches `done` with panels 1..N ok; queue a second job and cancel it; Traces tab shows the canned trace waterfall and text; screenshot to the user |

### 14.4 Prune tests

| ID | File | Covers | Pass condition |
|---|---|---|---|
| MPT1 | `tests/test_fleet_lib.py` | MP1 | missing `generated/` False; only empty dirs False; a symlinked file only False; `generated/` itself a symlink False; a file 3 levels deep True |
| MPT2 | `tests/test_fleet_lib.py` | MP2 | with `protected={"v2026.01.01"}`, the `:1048-1053` cases return `[]` and `["v2026.01.02"]`; with `protected=()` the existing expectations hold |
| MPT3 | `tests/test_fleet_self_update.py` | MP3 | following `test_t60`'s pattern: after a switch, an old release holding `generated/stories/x/story.md` is kept and the daemon log contains `update: keeping <tag>: generated/ holds data`; a data-less old release beyond the newest 3 is removed |

### 14.5 Requirement-to-test table

| Req | Tests |
|---|---|
| MU1-MU4, MU6 | MUT15 |
| MU5, MU7, MU77 | MUT18, MUT27 |
| MU8 | review |
| MU9-MU11 | MUT18 |
| MU12, MU76 | MUT24 |
| MU13, MU14 | MUT18, MUT23 |
| MU15-MU17 | MUT10, MUT2 |
| MU18, MU28, MU30-MU32 | MUT14 |
| MU19, MU53 | MUT21 |
| MU20, MU71-MU74 | MUT22 |
| MU21-MU25 | MUT10, MUT11, MUT12 |
| MU26, MU29 | MUT13 |
| MU27, MU59 | MUT8, MUT9 |
| MU33-MU35, MU45, MU46 | MUT23 |
| MU36-MU41 | MUT1, MUT2, MUT3 |
| MU42-MU44, V1-V6 | MUT4-MUT9, MUT2 |
| V7, MU52 | MUT1 (smoke argv), MUT14 (smoke job runs a stub `ltx-mlx-render`) |
| MU47 | MUT3 |
| MU54 | MUT19 |
| MU55-MU58 | MUT16, MUT17 |
| MU60-MU65 | MUT6, MUT7, MUT9, MUT22 (models via `make_hf_cache`), MUT27 |
| MU66-MU68 | MUT2, MUT13, MUT14 |
| MU69, MU70 | MUT20, MUT27 |
| MU75, MU78-MU85 | MUT27 |
| MP1-MP3 | MPT1-MPT3 |

---

## 15. Rollout

- **MUR1. Implement and review.** Subagent-driven implementation of Sections 2-13 and their tests; Opus-high review before each phase is declared done; push; ship in the next fleet tag together with MP1-MP3.
- **MUR2. Mac (.199).** Run `bin/movie-ui` in a terminal; open the printed URL. Pass: the badges show render ok, stills ok, story server state; `LoRAs & Models` lists the real caches and V3 reports the real video model and gemma intact or names the exact missing file (see MUX4); a smoke render passes V7; a 2-panel chained movie runs end to end (Write story, edit `story.md`, Render) and `movie.mp4` plays in the page.
- **MUR3. Cancel live.** Cancel a running render during Phase 4. Pass: within `CANCEL_GRACE_S` + 2 s (17 s at the default grace) when `ps` answers promptly (MUK4) (amended 2026-10-20: final review item 9 — the flat 16 s ignored marker latency and the `ps` timeout), `ps -A -o pid,pgid,command | grep -E 'ltx-2-mlx|ltx-mlx-render|ltx-movie|ffmpeg'` shows none of the job's processes.
- **MUR4. Linux (.168, after the fleet update installs the tag).** `ssh -L 8999:127.0.0.1:8999 ollama-168`, then run `~/agents/ollama-168/current/qwen-agent-workspace/bin/movie-ui` there. Pass: render and stills badges unavailable with reasons; Write story/Run all/Smoke/Create/Train disabled with reasons; Traces, LoRAs, Characters (list/show), dry-run validation work.
- **MUR5. Prune.** After the next self-update on any host, `grep 'keeping .*: generated/ holds data' ~/agents/<id>/logs/qwen-agentd.log` names every older release with data, and those directories still exist.

## 16. Out of scope

- Remote access other than an SSH tunnel; binding any address but 127.0.0.1; TLS; user accounts.
- Cross-host jobs; starting or stopping the story server, vision server or daemons from the page.
- Downloading missing models or LoRAs; uploading LoRA files (paths are typed).
- Editing `character.json` (the descriptor), `catalog.json` by hand, `plan.json`, or any file other than `story.md`.
- Server-sent events, WebSockets; a build step, frameworks, CDN assets.
- Injecting `QWEN_AGENT_TRACE_ID` into jobs; any trace collector.
- Running movie-ui as a launchd/systemd service.
- Changing any pipeline file (Section 0.3).
- Automatic cleanup of data-holding releases, job history or uploads.
- Persisting the selected workspace across page loads.

---

## 17. Spec-author choices

1. GC7: `movie_ui_server` uses `fleet_lib`'s read-only registry, wire-client and validator helpers, not only `render_trace`.
2. GC10: atomic writes without `fsync`; files 0600, directories 0700.
3. 0.3: `character_dataset.py` added to the zero-diff list.
4. MU6: two exact startup lines; MU7: no request log below 5xx (the token would appear).
5. MU9: HTTP/1.0, 30 s socket timeout (as the daemon).
6. MU10: check order Host, Origin, static, token (all `/api/*`, so unknown API paths also need the token), route, body; 411 for a missing Content-Length; exact error strings.
7. MU11: route regexes; `GET /api/traces/saved/<id>` added.
8. MU12: CSP extended with `object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'` and `Referrer-Policy: no-referrer`.
9. MU13: local query parser instead of `urllib.parse`.
10. MU15: job kinds `story`, `movie`, `smoke`, `character-create`, `character-regenerate`, `character-train`; `job.json` `schema` key.
11. MU16: a server-written `starting` state before the runner starts; final status keeps the running keys; `lost` adds `detected`.
12. MU18: `queue.json` is a bare JSON array.
13. MU20: saved-trace envelope `movie-ui.saved-trace.v1` wrapping the exact fetch result.
14. MU21: the runner is passed `--grace`; `CANCEL_GRACE_S` module constant for tests.
15. MU22: runner exit codes 0/1/3 and `[movie-ui] ` log lines.
16. MU23: process-tree sweep via `ps` (pending Q1).
17. MU29: a 10 s "starting" grace before a never-locked runner is declared lost.
18. MU33: candidate order, labels, `prune` values, `data_bytes`, commit via `git rev-parse --short HEAD`.
19. MU34/MU35: default agent = the `~/.local/bin/qwen-agent` wrapper's agent, else the only agent.
20. MU36: the compose field object, the five actions, LoRA items carrying path and kind so the builder is pure.
21. MU39: motion/physics first, then everything else in submitted order (free paths included).
22. MU40: narrative right after the bin path; `--model`/`--gemma` emitted only when non-null; strength as `repr(float(s))`; `--no-review` always last; run with `sys.executable`.
23. V1: all limits (panels 1..200, length (0, 3600], fps 1..120, panel_timeout 60..86400, 8 LoRAs per list, 8 characters, narrative 20000 characters, model names 512) and exact error strings; narrative must not start with `-`; `movie-ui-smoke` reserved.
24. V1 rule 17 and the `overwrite_movie` field (`--force`).
25. V2: story server needed only when Phase 1 will author; `SERVING ` prefix passes; a `judge key` sub-check.
26. V3: snapshot choice by `refs/main`; the intact rules without `config.json` (pending Q3).
27. V4: the auto set mirrors `story_engine._catalog_filter`; free-path header check re-implemented.
28. V5: at most one style LoRA per list (video and stills separately); video base-model mismatch is `skip` (pending Q2).
29. V6: `STORY_PIPELINE_LOGGED=1` for the dry run.
30. MU52: smoke manifest text, 512x320 at 9 frames, 1800 s panel timeout, `story_id` `movie-ui-smoke`, output `STATE/smoke/<id>/smoke.mp4`.
31. MU55: regexes, 300-character clips, incomplete-tail handling, 1 MiB per feed.
32. MU56: progress object shape; stills expected 1 (chained) or P (shots).
33. MU58: `next_offset` lands on a UTF-8 boundary.
34. MU59: 502/504 for failed or timed-out data subprocesses; bins run with `sys.executable`.
35. MU60: startup probe in a thread, `?refresh=1` re-probe.
36. MU62: action endpoints return the run result with 200 whatever the exit code.
37. MU63: `ws` validated but unused for models; story model free text only.
38. MU64: `face_problem` from the newest create job's log; `last_create_fields` for Force.
39. MU67: history capped at 200 entries.
40. MU68: kill-orphan sends SIGKILL directly; deleting a smoke job removes its `STATE/smoke/<id>/`.
41. MU69: stories sorted by directory mtime, newest first; `movie-ui-smoke` hidden.
42. MU70: refuse edits while a job on the story is running; backup suffix `-2`, `-3`.
43. MU72: dedup keeps the earliest-start item; `agents` = responders plus delegated hop agents.
44. MU77: token kept in `sessionStorage`, removed from the address bar.
45. MU78-MU85: element IDs; 2 s job polling, 1 s log polling, 300 ms preview debounce.
46. MU80: buttons disabled by capability (create needs stills, train needs render).
47. MU81: Render without `last_fields` prefills only the story ID and panels; the narrative must be re-entered.
48. MP3: keep lines logged before unstaging, one per kept tag, in prune order.

## 18. Discrepancies with the brief

- **D1. Process groups do not cover the render.** The brief says the job's process group "covers ltx-2-mlx and ffmpeg children" and that "none of the bins use start_new_session". The bins do not, but the modules they load do: `ltx2_mlx_video_skill.py:338-341` starts every `ltx-2-mlx` (and so its ffmpeg) with `start_new_session=True`, and `character_dataset.py:504-506` does the same for training and Z-Image children. `os.killpg(<job pgid>)` therefore kills `ltx-movie` and `ltx-mlx-render` but leaves `ltx-2-mlx` rendering (re-parented to init), which makes MUK4 impossible as briefed. MU23 adds the minimal fix inside the runner: snapshot the descendant tree with `ps -A -o pid=,ppid=,pgid=` at cancel time and signal every descendant process group with the same TERM-then-KILL rule. No pipeline file changes. Needs approval (Q1).
- **D2. Character video LoRAs never match `--model`.** `character_dataset.py:134`, `:1075` record `base_model = <LTX2_MLX_DIR>/models/ltx-2.3-mlx-q8-dev` (a local path) for every video LoRA, and `lora_catalog.compatible` (`:343-352`) compares exact strings or realpaths. "Each cast character's video LoRA base_model == --model" would fail every trained character under the default HF-ID model, so V5 reports that comparison as `skip` with a detail instead of `fail` (pending Q2). `bin/ltx-movie` itself never checks it. The stills check (`Tongyi-MAI/Z-Image-Turbo`) works as briefed.
- **D3. LTX model packs have no `config.json`.** The LTX pack on this Mac (`~/ltx-2-mlx/hf_cache/hub/models--dgrauet--ltx-2.5-mlx-q8`) has `embedded_config.json`, `split_model.json` and single-file `.safetensors`, no `config.json` and no index file, so "snapshot has config.json" would fail every video model. V3 drops that clause and keeps the other rules (pending Q3). The same snapshot has 3 `.incomplete` blobs, so V3 will report it incomplete. The default `MLXBits/ltx-2.3-10eros-v1.2-dmd-mlx-q8` is not present in the default `LTX2_MLX_HF_HOME` on this Mac at the time of writing (MUX4).
- **D4. 512x288 is not a valid render size.** `ltx2_mlx_video_skill.validate_geometry` (`:85-108`) requires multiples of 64; `bin/ltx-mlx-render` exits 2 on 288. The smoke render uses 512x320 (the size the character pipeline's validation renders use).
- **D5. A smoke render cannot be confined to `STATE/smoke/<id>/`.** `bin/ltx-mlx-render` takes its story directory from `manifest["story_id"]` (`:1185-1187`), not from the manifest path, and always writes `runs/<run_id>/story_summary.json` and panel logs under `<ws>/generated/stories/<story_id>/` (`:1267-1268`). With `--clips-dir` and the output path in STATE, the clip, movie and manifest live in `STATE/smoke/<id>/`, but run records go to `<ws>/generated/stories/movie-ui-smoke/runs/`. Consequence: after a smoke render, that release's `generated/` holds files, so MP1 keeps it from pruning. The ID `movie-ui-smoke` is reserved and hidden from the Stories list (Q4).
- **D6. `character show` is not pure JSON.** It prints the JSON object followed by a `files:` block (`bin/character:70-91`). movie-ui decodes the leading object with `json.JSONDecoder().raw_decode` and parses the file lines separately.
- **D7. `panels: N` appears only in the dry-run plan.** `bin/ltx-mlx-render:807` is inside `print_dry_run`, so it appears during Phase 3; the render prints `=== panel i/N (panel-i) ===` (`:1298`). The parser uses both for the total.
- **D8. Unattended runs need `--no-review`, Render needs the narrative, and an existing movie needs `--force`.** Without a TTY `bin/ltx-movie` exits 2 unless `--no-review` (`:2313-2317`), so the builder always adds it. `narrative` is required even when `story.md` exists (`:2242-2243`). Phase 4 refuses an existing `movie.mp4` without `--force` (`:1970-1972`), hence `overwrite_movie`.
- **D9. Recent traces carry summaries, not records, and the error wording differs.** `/traces/recent` returns `{schema, agent, traces: [{trace_id, start, dur_ms, status, kind, name, spans, delegated}]}` (`fleet_lib.py:1594-1613`): there is no per-trace agent list, so the "agents" column is derived from the responding agents and the `delegated` hops. `fleet_lib.fetch_*` reports `daemon not reachable at <url>` (`:1650-1651`); `qwen-agentd status` prints `daemon: not reachable at <url>` (`bin/qwen-agentd:1343`). movie-ui uses the status wording, as the brief asks.
- **D10. More mode conflicts than the brief lists.** Besides shots + no-stills and seed + no-stills, `bin/ltx-movie` refuses shots + seed image (`:933-936`) and `--judge`/`--no-auto-lora`/`--goal` with `--story-legacy` (`:887-894`). V1 enforces all of them.
- **D11. Chained Phase 2 renders one still.** Chained mode runs `ltx-story-images --only 1` (`:2149`), so "progress by counting panel_NN.png" expects 1 file in chained mode and P in shots mode.
- **D12. Character prerequisites beyond the badges.** `character create` needs the vision model served (`character_dataset.py:871-874`) and Z-Image; `train` needs the story server stopped (`:1137-1140`) and `ltx-2-mlx`. The page gates create on stills and train on render; the other preconditions surface as `bin/character` errors in the job log.
- **D13. `story-server` is Mac-specific.** It is a bash script with hard-coded `/usr/sbin/lsof`, `/usr/bin/python3` and a hard-coded default `WS` (`bin/story-server:35`, `:83-85`); on Linux `status` may exit 4, which V2 reports as a failure with the exit code.
- **D14. File/line drift in the brief.** `character_lib.library_dir` is at `:249-250`; `z_image_skill` cache selection at `:56-69`; host-prep's STATE base is `scripts/fleet-host-prep.sh:43`. No effect on behaviour.
- **D15. `--goal` exists** (`bin/ltx-movie:454-456`) with `_parse_goal`'s rules (`:262-277`), which V1 replicates.
- **D16. Help format.** On both 3.9.6 and 3.13, option lines start with exactly two spaces and a dash, and `BooleanOptionalAction` prints both forms on one line (`--story-server-stop-after-story, --no-story-server-stop-after-story`), which MU37's parser handles.
- **D17. A dry run can write a log record.** `pipeline_log.run_logged` appends to `<story_dir>/iterate-story.log` when the story directory exists, dry run or not (`pipeline_log.py:83-111`); V6 sets `STORY_PIPELINE_LOGGED=1` so validation leaves no trace.

## 19. Risks and open questions

**Accepted risks**

- **MUX1. Sweep race.** A process started between the `ps` snapshot and SIGTERM (a new panel's `ltx-2-mlx` exactly at cancel time) is missed. Its parent dies on SIGTERM, so it is at most one orphaned panel render; MUR3 checks for it.
- **MUX2. pgid reuse.** A lost job's recorded group ID can be reused by an unrelated process; kill-orphan is manual and confirmed for that reason.
- **MUX3. UI workspace pruned under itself.** A movie-ui started from a data-less release that self-update later prunes loses its static files and runner script; restart it from `current`.
- **MUX4. Real caches.** V3 may fail on .199 until the default video model is present in `LTX2_MLX_HF_HOME` (D3); that is the check working, not a defect.
- **MUX5. Long validations.** V2's stills probe and V6 can each take up to 60 s, and V4's `lora-catalog verify` up to 300 s, so Validate (and a submit, which re-runs the checks, MU44) can take about 5 min on a cold machine with large LoRAs on an HDD (amended 2026-10-20: ledger ruling Task 8 — VERIFY_TIMEOUT = 300 s).
- **MUX6. Environment test hooks.** `LORA_CATALOG_DIR` or `CHARACTER_LIBRARY_DIR` set in movie-ui's environment redirect every workspace's catalog/library (test-only variables, passed through unchanged).

**Open questions — resolved by the user 2026-10-19: Q1 yes (descendant sweep in); Q2 skip with the training base shown; Q3 yes (config.json clause dropped; intact = every index-listed shard resolves non-empty, or at least one non-empty .safetensors without an index, and no .incomplete blob); Q4 accept.**

- **Q1 (D1).** Approve the runner's descendant process-group sweep (MU23 step 1) so cancel really stops `ltx-2-mlx` and training children? Without it, MUK4 must be reduced to "the job's own process group is gone within 16 s" and a cancelled render's GPU process keeps running.
- **Q2 (D2).** Is a cast character's video-LoRA base model mismatch acceptable as a non-blocking `skip` (as specified), or should V5 compare against something else (for example the dev model directory as the known-good training base for every `ltx-2.3` pack)?
- **Q3 (D3).** Confirm dropping the `config.json` clause from "intact", or name the per-family file to require instead.
- **Q4 (D5).** Accept that a smoke render writes run records under `<ws>/generated/stories/movie-ui-smoke/runs/` and therefore marks that release as holding data, or drop V7 until `bin/ltx-mlx-render` can place its run root elsewhere (a pipeline change outside F)?

## 20. Implementation amendments (2026-10-20)

Rulings accepted during implementation (ledger `.superpowers/sdd/2026-10-19-movie-ui/progress.md`) and the final whole-branch review's amendment list. Each amended requirement carries an inline `(amended 2026-10-20: ...)` note; nothing was renumbered.

1. Orphan blocking: dispatch waits while any lost job has a live orphan group; `orphan_info` excludes the server's own pgrp and pgids outside `1 < g < 2**31`; `GET /api/jobs` gains `blocked_by`, shown in `#j-blocked`; dispatch writes `starting` before the queue rewrite and skips heads that already have a status — MU26, MU30, MU67, MU84.
2. Delete and kill-orphan: DELETE of a lost job with a live orphan needs exactly `{"confirm": true}` (else 409), `Content-Length: 0` is no body, a removal failure is 500 `cannot delete job <id>: <strerror>` with the smoke dir removed first, a kill-orphan `PermissionError` is 409 — MU10 (step 6), MU68, MU84.
3. Light subprocesses: `run_light` uses a new session + `communicate(timeout)` + `killpg` SIGKILL and also catches `ValueError` (Ctrl-C no longer reaches light children); `lora-catalog` add/verify use `VERIFY_TIMEOUT` 300 s; `help_flags` never caches a timeout — MU59, MU37, MU62, V1 rule 18.
4. V1 argv safety: `_argv_safe` with `narrative contains invalid characters`, `goal must not start with '-'`, `goal contains invalid characters`, LoRA `path contains invalid characters`; reserved smoke id compared case-insensitively; plan decision 7 strings and rule-18 gating — V1 (rules 1, 2, 3, 9, 11, 18).
5. V2-V5: timeout texts for story-server status, lora-catalog verify (300 s) and character show; the user-approved stale-index rule, `refs/main` decode errors and the 20000-entry walk cap; auto-set verify FAILs become the non-blocking `LoRAs auto set` skip; validation can take about 5 min — V2, V3, V4, V5, MUX5.
6. Progress parser: RETRY_RE marks a panel running, MOVIE_RE sets `wrap_up`, the tail is bounded at 64 KiB from the last `\r`, an incomplete trailing UTF-8 sequence is dropped from `last_line` — MU55, MU56.
7. HTTP hardening: JSON constants and non-finite numbers give 400 `invalid JSON body`, `allow_nan=False` on output; every `do_*` goes through `_handle` and stdlib errors are JSON; `invalid Content-Length` 400; NUL in `ws` gives MU14's 400; 5xx log lines escape non-printables; an unencodable ApiError body falls back to the sanitized error string — MU7, MU9, MU10, MU14.
8. Files, stories, characters, LoRAs, traces: `/files` opens before headers, EACCES 403, Range numbers over 18 digits clamped, `bytes=-0` 416; strict story JSON (NaN gives null) and story-dir containment; PUT 404 through an escaping symlink, 400 `text must be encodable as UTF-8`, 409 for an unreadable existing story.md; `STILL_FILE_RE` `[0-9]{2}` + isfile; character and LoRA fields `_argv_safe` + no leading `-`, LoRA add path absolute, `seed_upload ""` is null; strict trace post-check `returned an unrecognized trace response` — MU54, MU62, MU64, MU65, MU69, MU70, MU73.
9. Cancel budget: within `CANCEL_GRACE_S` + 2 s when `ps` answers promptly (typically about 16 s); worst case marker poll 1 s + `ps` 5 s + grace 15 s + KILL — MUK4, MUR3.
10. Criteria wording: MUK6 allows 403 for a bad Host/Origin; MU4 notes macOS `allow_reuse_address` binding `127.0.0.1:p` while `0.0.0.0:p` is held; MUK1 states 3.9 is covered by `py_compile` plus the runtime smoke, not pytest under 3.9 — MUK6, MU4, MUK1.
