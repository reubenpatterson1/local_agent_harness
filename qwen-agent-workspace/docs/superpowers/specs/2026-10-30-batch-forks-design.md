# Batch forks: bulk re-run of stories to compare settings

Date: 2026-10-30

Status: design spec. The user approved every section of the design (scratchpad `bulk-rerun-design-notes.md`, Sections 1-4) on 2026-10-30. This document carries that design without reopening it. Every detail the notes leave open is decided here and marked **[spec choice]** with its reason. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`, branch `bulk-rerun`, HEAD `574303a` (`574303a05b457a287acce5a5791d37fe869aebcb`). `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `574303a`.

Builds on **[MUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md` (routes, jobs, V1-V6, `/files`) and **[VLM]** `docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md`.

Terms: an **original** is a story directory `<ws>/generated/stories/<id>`. A **variant** is one set of setting and prompt changes. A **cell** is one original × one variant. A **fork** is the new story a cell creates. Its **level** is `render`, `stills` or `replan` (UI labels `Render`, `New stills`, `Re-plan`). Requirement IDs are BF1-BF41, tests are BT1-BT35, and KPIs are BK1-BK8.

---

## 0. Scope

### 0.1 Grounding (verified at `574303a`)

- **Jobs.** `create_job` writes `jobs/<id>/job.json` with argv, fields and vlm, and appends to `queue.json` (`movie_ui_lib.py:174-186`). `create_compose_job` takes `STORE_LOCK` itself (`movie_ui_server.py:749-760`). `_h_job_create` runs `lib.run_checks` with no lock held, then calls `create_compose_job` (`:763-769`). `run_checks` is V1, then V2-V6, with V6 = `ltx-movie --dry-run` (`movie_ui_lib.py:2052-2076`, `DRY_RUN_TIMEOUT = 60` `:1839`). `checks_pass` fails only on status `fail` (`:1253-1254`).
- **Queue.** The queue is FIFO. `dispatch_tick` runs under `STORE_LOCK` every 1 s (`movie_ui_server.py:617-624`, `movie_ui_lib.py:748-785`). Other functions: `startup_recovery` `:788-802`, `job_state` `:805-810`, `cancel_job` `:813-826` (a queued job becomes `cancelled` at once, and a starting or running one gets the cancel marker), `move_job` `:829-840`, `delete_job` `:843-853`. A runner that finds the cancel marker before the child starts writes `cancelled` with no `started` (`:314-318`; `started` is first written at `:359-361`).
- **Fields.** `DEFAULT_FIELDS` (30 keys) is at `movie_ui_lib.py:892-905`. `compose_fields` fills the defaults and converts the old boolean narration (`:927-936`). `build_argv` is pure and always adds `--no-review` (`:966-1023`). `validate_fields` is V1 (`:1393-1499`): rule 17 refuses an existing `movie.mp4` (`:1490-1492`) and rule 18 uses the cached `help_flags` (`:1205-1227`). `resolved_panels` is at `:1274-1283`. `NARRATIVE_MAX = 20000` (`:1240`).
- **Story IDs.** `STORY_ID_RE = ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`, so the maximum is **80 characters** (`movie_ui_lib.py:37`). `valid_story_id` adds "no `..`" (`:1269-1271`), and the route pattern `_STORY` matches it (`movie_ui_server.py:56`).
- **Stories API.** `GET /api/stories` returns rows `{id, story_md, checks, stills, clips, movie, mtime}`, with no fields and no job state (`movie_ui_server.py:1682-1707`). `tests/test_movie_ui_http.py:801-803` asserts that row shape exactly. Only `GET /api/stories/<id>` returns `last_fields`: the fields of `newest_job(server, ("story", "movie"), ws, "story_id", id)` (`:1159-1165`, `:1756-1757`). The Stories tab builds rows in `loadStories` (`app.js:679-694`) and reuses `last_fields` in `storyFields` (`app.js:748-754`).
- **VLM.** `job_vlm` for a movie is `forbidden` when `story.md` exists and `required` otherwise (`movie_ui_lib.py:421-436`). The policy is recomputed at dispatch (`:439-445`). By default `bin/ltx-movie` stops the story server after Phase 1 (`bin/ltx-movie:448-458`, `:2647`).
- **Pipeline reuse.** Every existing-story decision keys on `story.md` (and `plan.json`), never on the directory: `bin/ltx-movie:891` (casting), `:971` (locations), `:1418` (legacy Phase 1), `:1584` (panel count), `:1662`, `:1795` (robust recheck) and `:2446` (dry run). `main` creates the directory with `exist_ok=True` (`:2736`). Stills are reused when the file exists (`bin/ltx-story-images:493-494`). Stills are made at **twice the video size** (`bin/ltx-movie:2010-2016`). The render refuses a still whose aspect differs from `--width x --height` (`bin/ltx-mlx-render:1336-1353`). Clip reuse needs an exact provenance match (`bin/ltx-mlx-render:558-591`, `:609-625`). The recheck applies `spoken_line_problems` with the current clip length (`story_engine.py:4982`, `engine_seconds` `:114-115`, fed by `bin/ltx-movie:1631`), and the dry run does not recheck (`bin/ltx-movie:2443-2447`).
- **UI.** `TABS` is at `app.js:285` and `showTab` at `:287-298`. `loraRow`/`collectLoras` append to the Compose containers (`:302-357`). `composeFields` is at `:365-391`, `fillCompose` at `:493-544` and `stopPolling` at `:66-72`. The jobs poll runs every 2000 ms (`:1688`). `index.html` has one `<script>`, which `tests/test_movie_ui_http.py:1040` asserts.
- **Tests.** `tests/movie_ui_testutil.py` provides `set_home`, `make_stub_workspace`, `Running` (no dispatcher thread), `api`, `make_job`, `dispatch`, `fields`, `stub_config`, `stub_calls` and `copy_ui` (`:459-469`, which copies a fixed file list). `tests/conftest.py:29-30` turns the VLM lifecycle off for every test.

### 0.2 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `movie_ui_batch.py` (new) | constants, request validation, merge, prompt edits, classification, fork IDs, copy plan, order, totals, batch-record field fallback check |
| G2 | `movie_ui_server.py` | 8 routes, `BATCH_LOCK`, submitter thread, recovery, reconcile, cancel hook, `stored_fields` |
| G3 | `movie_ui_lib.py` | `STATE_SUBDIRS` gains `"batches"` |
| G4 | `static/movie-ui/index.html`, `app.js`, `app.css` | Stories checkbox, Batches tab, editor, compare page |
| G5 | tests | Section 7 |

Untouched: every pipeline file, including `bin/ltx-movie`, `story_engine.py`, `bin/ltx-story-images`, `bin/ltx-story-manifest` and `bin/ltx-mlx-render`. `test_mut26` passes unedited.

### 0.3 Out of scope

- Batches across workspaces.
- Editing a submitted batch.
- Retrying refused cells automatically.
- Forking command-line stories.
- Diffing story.md between forks.
- Any VLM scheduling beyond the group order.
- Pipeline changes.

### 0.4 Must-haves and nice-to-haves

Every BF requirement and every BT test is a must-have. There are no nice-to-haves.

---

## 1. Architecture

```
Stories tab: tick rows -> "New batch (N)" -> editor (variants) -> POST /api/batches/preview (live)
Submit -> POST /api/batches -> batch.json (cells pending) -> 201 at once -> batch page polls
batch-submitter thread, one batch at a time, cells in submit order:
  pending -> forking: recompute -> space check -> mkdir + fork.json + copies -> busy re-check
          -> lib.run_checks (no lock) -> create_compose_job (STORE_LOCK inside) -> queued
          | refused (folder removed) | cancelled
dispatcher (unchanged) runs each fork as an ordinary movie job
```

- **BF1.** `movie_ui_batch.py` imports only `json`, `os`, `re`, `stat` and `movie_ui_lib`. It is Python 3.9-compatible and never writes. Its functions are pure, except `copy_plan`, which lists the original read-only. **[spec choice]** The listing belongs with the copy-plan logic the notes put here, while every write stays in the server.
- **BF2.** `movie_ui_server.py` adds `import movie_ui_batch as batch`. It gains `BATCH_LOCK = threading.Lock()`, and `MovieUIServer.__init__` gains `self.batch_queue = []` and `self.batch_thread = None`. **Lock rule [spec choice]:** `BATCH_LOCK` and `STORE_LOCK` are never held together, and `BATCH_LOCK` is held only for a `batch.json` read-modify-write and for the planning step of submit (BF24, so two submits cannot draw the same number). No nesting means no deadlock with the dispatcher.
- **BF3.** `<STATE>/batches/<batch-id>/batch.json` is written with `lib.write_json_atomic` (mode 0600), in directories made with `lib.make_dir` (mode 0700). `"batches"` is appended to `STATE_SUBDIRS`.

### 1.1 Constants (`movie_ui_batch.py`)

```python
BATCH_SCHEMA = "movie-ui.batch.v1"
FORK_SCHEMA = "movie-ui.fork.v1"
MAX_VARIANTS = 6
MAX_CELLS = 24
MAX_REPLACES = 10                      # [spec choice] bounds the request
LABEL_MAX = 24                         # [spec choice] fits a grid column header
PROMPT_MAX = lib.NARRATIVE_MAX         # 20000, the Compose narrative limit
STORY_ID_MAX = 80                      # STORY_ID_RE, movie_ui_lib.py:37
MIN_FREE_BYTES = 20 * 1024 ** 3        # 20 GiB left after the copy
LEVELS = ("render", "stills", "replan")            # rank order
LEVEL_LABELS = {"render": "Render", "stills": "New stills", "replan": "Re-plan"}
FIXED_KEYS = ("ws", "action", "story_id", "overwrite_movie", "redo")
GROUPS = (("panels", "length"), ("width", "height", "seed_upload"))
FORK_SUFFIX_RE = re.compile(r"-b([0-9]+)-v[0-9]+$")
```
`app.js`: `BATCH_POLL_MS = 2000` (the jobs poll interval).

---

## 2. Building a cell

### 2.1 Classification table (BF4; BK1)

This table covers every `DEFAULT_FIELDS` key (`movie_ui_lib.py:892-905`). It is `FIELD_LEVELS` in `movie_ui_batch.py`.

| Key | Level | Reason |
|---|---|---|
| `ws`, `action`, `story_id`, `overwrite_movie`, `redo` | not editable | Fixed per fork: `ws` = the batch workspace, `action` = `"movie"`, `story_id` = fork ID, `overwrite_movie` = `False`, `redo` = `[]` **[spec choice]**: a fork is a full movie run, has no `movie.mp4` to overwrite and no panels to redo |
| `model`, `gemma` | render | in the clip provenance only |
| `video_loras` | render | approved ("LoRAs or strengths") |
| `action_loras` | render | **[spec choice]** fused into the global video LoRAs at render (`bin/ltx-movie:1114-1125`), not used by stills |
| `frames` | render | approved; the stills size does not depend on it |
| `fps` | render | **[spec choice]** clip timing only, the same as frames |
| `no_low_ram` | render | **[spec choice]** a render-residency flag (`bin/ltx-movie:419-423`) |
| `panel_timeout` | render | **[spec choice]** used by Phase 4 only |
| `width`, `height` | stills | **user-confirmed 2026-10-30** the stills are made at 2× the video size (`bin/ltx-movie:2016`), and a copied still with another aspect fails the render (`bin/ltx-mlx-render:1349-1353`). So a resolution change is a stills-size change |
| `stills_loras` | stills | approved |
| `location_strength` | stills | **[spec choice]** passed to Phase 2 stills and to the manifest (`bin/ltx-movie:1243-1253`, `:2040`) |
| `narrative`, `goal` | replan | approved (§4 findings) |
| `panels`, `length` | replan | approved: any panel change |
| `seed_upload` | replan | approved: used in Phases 0-2 |
| `mode`, `characters`, `locations`, `narration` | replan | approved (§4 findings) |
| `story_model`, `story_legacy`, `judge` | replan | **[spec choice]** used only when Phase 1 generates, so a change has no effect on a copied story.md |
| `auto_lora` | replan | **[spec choice]** the planner makes the picks (plan.json `loras`), so turning picks on needs a new plan |

25 keys are editable and 5 are fixed, which together make all 30.

### 2.2 Merge (BF5)

`merge(last_fields, variant, story_id, fork_id, ws_real)` returns `(orig, fork, warnings)`:
1. `orig = lib.compose_fields(last_fields)`, then `orig.update(ws=ws_real, action="movie", story_id=story_id, overwrite_movie=False, redo=[])`.
2. `fork = json.loads(json.dumps(orig))`, then `fork["story_id"] = fork_id or story_id`.
3. Apply the variant's `settings` in key order, using a deep copy of each value. The groups are coupled **[spec choice]** so that V1 rules 4 and 7 hold:
   - setting `panels` sets `length = None`;
   - setting `length` sets `panels = None`;
   - setting `width`/`height` sets `seed_upload = None`;
   - setting a non-null `seed_upload` sets `width = height = None`.
4. `fork["narrative"], warnings = edit_prompt(orig["narrative"], variant["prompt"], story_id)` (§2.3).

### 2.3 Prompt-edit algorithm (BF6)

`edit_prompt(narrative, prompt, story_id)`:
1. `text = prompt["per_story"][story_id]` when that key exists, else `narrative`.
2. For each `{"find", "with"}` pair in order:
   - when `find in text`, `text = text.replace(find, with)` (every occurrence);
   - otherwise add the warning `find text not in this prompt: "<find>"`.
3. When `prompt["append"].strip()` is not empty, `text = text.rstrip() + "\n\n" + prompt["append"].strip()`. **[spec choice]** The appended text stays a separate, visible paragraph.
4. When `len(text) > PROMPT_MAX`, add the warning `edited prompt is N characters; the limit is 20000`. V1 then refuses the cell.

### 2.4 Classification and refusal (BF7-BF10)

Let `A(f) = lib.build_argv(dict(f, story_id=story_id), ws_real, state)` be the argv with the original's ID.
- **BF7 Identical.** When `A(fork) == A(orig)`, the cell is refused with `same settings and prompt as the original; nothing to compare`. **[spec choice]** Comparing argvs also catches no-op edits, such as a location strength with no locations, `goal` ending in `.`, or whitespace-only prompt edits.
- **BF8 Diff.** For every key `k` in `FIELD_LEVELS` with `fork[k] != orig[k]`:
  - build `probe = dict(orig)` with `k` and the rest of its `GROUPS` group copied from `fork`;
  - keep `k` only when `A(probe) != A(orig)`, as the entry `{"key": k, "from": orig[k], "to": fork[k]}`.

  The `diff` is in `DEFAULT_FIELDS` order. There is one extra entry, `{"key": "panels", "from": P0, "to": P1, "note": "resolved from length"}`, which is added when `fork["length"]` is not null, `panels` is not already in the diff, and `P1 = lib.resolved_panels(fork)` differs from `P0 = lib.resolved_panels(orig)`. **[spec choice]** A frames or fps change on a length-sized story changes its panel count (`bin/ltx-movie:520-533`).
- **BF9 Level.** The level is the highest-ranked `FIELD_LEVELS[key]` in the diff, with the extra `panels` entry counting as `replan`. When the original has no `story.md`, the level is `replan` and the cell gets the warning `the original has no story.md; this fork writes a new story`. **[spec choice]** The fork would need the VLM, and the group order depends on that.
- **BF10 Warnings.** When the level is `render` or `stills` and `fork frames/fps < orig frames/fps`, add the warning `shorter clips (X.XX s, was Y.YY s): the copied story.md is re-checked and can fail its spoken-line timing`, with both values to 2 decimals. **[spec choice]** This is risk R2: the dry run cannot catch it.
- **BF11 Duplicate variant.** A cell whose `A(fork)` equals that of an earlier `ok` cell of the same story (grid order) is refused with `same settings and prompt as variant M (<label>) for this story`.
- **BF12 Errors.** Any exception from `merge`, `A` or the classification refuses the cell (widened 2026-10-30 from KeyError/TypeError/ValueError, because malformed saved fields also raised AttributeError and ZeroDivisionError) with `the saved settings of story <id> cannot be used: <Type>: <message>`.

### 2.5 Fork IDs (BF13-BF15)

- **BF13.** `fork_id(story_id, n, m)` uses `suffix = "-b%d-v%d" % (n, m)`. When `len(story_id) + len(suffix) > 80`, the stem becomes `story_id[:80 - len(suffix)].rstrip("-._")` **[spec choice]**, so the ID never ends in `--b`. The result must pass `lib.valid_story_id`, or the cell is refused with `the fork ID would not be a valid story ID: <id>`. `m` is the 1-based variant index.
- **BF14.** `n = next_number(batch_records, story_names, ws_real)` is 1 plus the maximum of every `number` of a batch record whose `workspace == ws_real` and every `FORK_SUFFIX_RE` group in that workspace's story directory names (0 when there are none). **[spec choice]** Scanning the directories means a deleted batch's number is never reused.
- **BF15.** A fork ID that is case-insensitively equal to an earlier cell's fork ID in the same batch is refused with `fork ID <id> is also the fork ID of story <other> in this batch`. **[spec choice]** The macOS filesystem is case-insensitive. A fork ID whose directory exists (`os.path.lexists`) is refused with `fork ID <id> already exists; it is never overwritten`.

### 2.6 Copy plan (BF16-BF18)

`copy_plan(sdir, level)` returns `[(relpath, bytes)]` sorted by relpath. It lists only regular files: an `os.lstat` `S_ISREG` check skips symlinks **[spec choice]** so the copy never follows a link out of the story. The list is an allowlist, and anything not on it is never copied **[spec choice]**:

| Level | Copied (when present) |
|---|---|
| render | `story.md`, `plan.json`, `story_checks.json`, `story_prompt.txt`, `catalog_loras.json`, `manifest.json`; in `images/`, names matching `^panel_\d{2}\.png$` and `images.json`; in `clips/`, each `^panel_\d{2}\.mp4$` **with** its `<name>.provenance.json`, both or neither **[spec choice]**: a clip without provenance is never reused (`bin/ltx-mlx-render:611-612`) |
| stills | `story.md`, `plan.json`, `story_checks.json`, `story_prompt.txt` **[spec choice]**: Phase 3 rewrites `manifest.json` and `catalog_loras.json` (`bin/ltx-movie:2244-2247`) |
| replan | nothing |

- **BF17 Never copied** (asserted by BT8): `movie.mp4`, `.movie.lock`, `movie.log`, `iterate-story.log`, `runs/`, `redo/`, `story_rounds/`, `story_rounds-*/`, `*.bak*` (such as `story.md.bak-…`), `plan.stale-*.json`, `seed_downscaled.png`, `fork.json`, `clips/panel_NN.chainseed.png`, and any other file.
- **BF18 Copy execution (server).** `os.mkdir(fork_dir)` uses the default mode **[spec choice]**, the same as the pipeline's own story directories. Subdirectories are made with `os.makedirs(..., exist_ok=True)`. Each file is copied with `shutil.copy2`: a real copy, never a link, with the mtime kept.

### 2.7 `fork.json` (BF19; verification 1)

**Finding.** A directory that holds only `fork.json` is treated as a **new** story. `bin/ltx-movie` keys every existing-story decision on `story.md`/`plan.json` (`:891`, `:971`, `:1418`, `:1584`, `:1662`, `:1795`, `:2446`) and creates the directory with `exist_ok=True` (`:2736`). V1 looks only at `movie.mp4` (`movie_ui_lib.py:1490-1492`). `job_vlm` (`:432`) and `story_needed` (`:1609-1613`) look at `story.md`, and V6 is the same `bin/ltx-movie` code. Writing `fork.json` first is harmless.

**BF19.** `fork.json` is written right after `mkdir`, before any copy, with `lib.write_json_atomic`:
```json
{"schema": "movie-ui.fork.v1", "fork_id": "ronin-rescue-b3-v2", "source_story": "ronin-rescue",
 "batch": "20261030-120501-ab12", "variant": 2, "label": "v2", "level": "render",
 "diff": [{"key": "model", "from": "dgrauet/ltx-2.3-mlx-q8", "to": "/models/other"}],
 "created": "2026-10-30T12:05:09Z"}
```
`remove_fork(sdir, batch_id)` calls `shutil.rmtree(sdir)` only when `<sdir>/fork.json` parses with `batch == batch_id` and `fork_id == basename(sdir)`. Otherwise it leaves the directory and writes `movie-ui: batch <id>: not removing <sdir> (no matching fork.json)` to stderr. **[spec choice]** The server never deletes a directory it did not create.

---

## 3. Records and routes

### 3.1 `batch.json` (BF20)

```json
{"schema": "movie-ui.batch.v1", "id": "20261030-120501-ab12", "number": 3,
 "workspace": "/abs/ws", "created": "2026-10-30T12:05:01Z",
 "status": "waiting|submitting|submitted|cancelled|interrupted", "cancel_requested": false,
 "stories": ["ronin-rescue", "harbour-chase"],
 "variants": [{"label": "v1", "settings": {"model": "/models/other"},
               "prompt": {"append": "", "replace": [{"find": "dusk", "with": "dawn"}],
                          "per_story": {"harbour-chase": "full text"}}}],
 "order": [1, 3, 0, 2],
 "cells": [{"story_id": "ronin-rescue", "variant": 1, "fork_id": "ronin-rescue-b3-v1",
            "status": "pending|forking|queued|refused|interrupted|cancelled", "reason": null,
            "level": "render", "diff": [], "warnings": [], "fields": {}, "job_id": null,
            "copy_bytes": 0, "updated": "2026-10-30T12:05:01Z"}]}
```
- `cells` are in grid order: story-major, then variant.
- `order` lists cell indices in submit order (§4.2).
- `fields` holds the fork's full field object once the cell is built (`null` while it is pending), so deleting the job keeps the cell's settings.
- The batch ID uses the job-ID format, drawn by `new_batch_id(state)` the way `new_job_id` is (`movie_ui_lib.py:165-171`). **[spec choice]** This reuses `JOB_ID_RE` and the `_ID` route pattern.

### 3.2 Request body (preview and submit)

```json
{"ws": "/abs/ws", "stories": ["ronin-rescue", "harbour-chase"],
 "variants": [{"label": "v1", "settings": {"model": "/models/other"},
               "prompt": {"append": "", "replace": [], "per_story": {}}}]}
```
- Settings values use the `DEFAULT_FIELDS` shapes, for example `video_loras` `[{"id","path","strength","kind"}]` and `action_loras` `[{"name","strength"}]`.
- `prompt` and its three keys can be omitted (empty).
- `validate_request(body)` returns `(clean, errors)`. A body with errors gets 400 `{"error": "invalid batch", "errors": [...]}` (§6).

### 3.3 Routes (BF21)

They are appended to `ROUTES` after `/api/queue/move` (`movie_ui_server.py:103`). The count goes from 46 to 54.
```python
    ("GET", r"/api/batches", "h_batches", "/api/batches"),
    ("POST", r"/api/batches", "h_batch_create", "/api/batches"),
    ("POST", r"/api/batches/preview", "h_batch_preview", "/api/batches/preview"),
    ("GET", r"/api/batches/stories", "h_batch_stories", "/api/batches/stories"),
    ("GET", r"/api/batches/" + _ID, "h_batch", "/api/batches/" + _SAMPLE_ID),
    ("DELETE", r"/api/batches/" + _ID, "h_batch_delete", "/api/batches/" + _SAMPLE_ID),
    ("POST", r"/api/batches/" + _ID + r"/cancel", "h_batch_cancel", "/api/batches/" + _SAMPLE_ID + "/cancel"),
    ("POST", r"/api/batches/" + _ID + r"/resume", "h_batch_resume", "/api/batches/" + _SAMPLE_ID + "/resume"),
```
Every route goes through the token check (`_handle`, `:364-374`).

| Route | Response |
|---|---|
| `GET /api/batches?ws=` | 200 `{"batches": [{"id", "number", "created", "status", "cells": T, "done": D}]}`, newest first, this workspace only **[spec choice: tabs are per workspace]**. `D` counts cells whose job state is `done` |
| `GET /api/batches/stories?ws=` | 200 `{"stories": [{"id", "eligible", "reason", "busy_job", "fields_source", "fields_batch"}]}` over the same directories `_h_stories` lists (§3.4, §3.5) |
| `POST /api/batches/preview` | 200 `{"number": N, "rows": [{"story_id", "fields": <orig> or null, "fields_source", "fields_batch", "movie": path or null}], "cells": [{"story_id", "variant", "fork_id", "status": "ok"/"refused"/"invalid", "reason", "level", "diff", "warnings"}], "totals": {"jobs", "replan", "stills", "render", "refused", "text"}}` |
| `POST /api/batches` | 201 `{"batch": {"id", "number", "status": "waiting"}, "pending": P, "refused": R}`; 409 when `P == 0` (no record is written) |
| `GET /api/batches/<id>` | 200 `{"batch": <batch.json>, "view": {"originals": {sid: movie path or null}, "cells": [{"state", "job": <job_summary> or null, "movie": path or null, "dir": bool}]}}`, with `view.cells` parallel to `batch.cells` |
| `POST /api/batches/<id>/cancel` | 200 `{"status": "cancelled", "cancelled": [job IDs], "cancelling": [job IDs]}` |
| `POST /api/batches/<id>/resume` | 200 `{"status": "waiting", "pending": P}` |
| `DELETE /api/batches/<id>` | 200 `{"deleted": "<id>"}` |

`totals.text` is `"%d jobs: %d re-plan, %d new stills, %d render-only"`, with `"; %d refused"` appended when R > 0 **[spec choice]**. `jobs` counts `ok` cells, and `refused` counts `refused` plus `invalid` cells.

### 3.4 Eligibility (BF22; verification 4)

**Finding.** The Stories list carries neither fields nor job state (`movie_ui_server.py:1699-1705`), and its row shape is pinned by `tests/test_movie_ui_http.py:801-803`. So eligibility gets its own route, and `/api/stories` is unchanged **[spec choice]**.

`story_status(server, ws_real)` makes one pass over `sorted(lib.list_job_ids(state), reverse=True)` with `server.job(id)`:
- **has fields:** the first job of kind `story` or `movie` with `workspace == ws_real` and a dict `fields` defines `last_fields[story_id]`. This is the same rule as `newest_job` (`:1159-1165`).
- **busy:** any job with `workspace == ws_real`, that `story_id`, and `lib.job_state(state, id, queue)` in `("queued", "starting", "running")`. The first such ID is `busy_job`.
- **stored fields:** each listed story with no `last_fields` entry gets `stored_fields(server, ws_real, story_id)` (BF41, §3.5).

`reason` is one of (busy wins, then this order):
- `Job <id> is queued or running for this story`, when the story is busy;
- `Started from the command line: no saved Compose settings to fork`, when there is no `last_fields` and BF41 gives `none`;
- `Its job and its batch <batch> were deleted: no saved Compose settings to fork`, when BF41 gives `gone`;
- `Its job was deleted and batch <batch> has no matching record of this fork: no saved Compose settings to fork`, when BF41 gives `mismatch`;
- `null`.

`eligible` is `reason is null`. `fields_source` is `"job"` when `last_fields` has the story, `"batch"` when BF41 gives `ok`, and `null` otherwise. `fields_batch` is `{"id": <batch>, "number": <record number>}` when `fields_source == "batch"`, else `null`. These two keys are computed even for a busy story.

### 3.5 Batch-record field fallback (BF41)

**Finding.** A fork's job can be deleted (`DELETE /api/jobs/<id>`, `movie_ui_server.py:98`; `delete_job` `movie_ui_lib.py:843-853`). The fork then has no `last_fields`, but its cell in `batch.json` keeps the full fork fields that were passed to `create_compose_job` (§4.3 step 9). `fork.json` is never copied (BF17), so each fork directory holds only its own `fork.json`. `lib.read_json(path, default)` returns `default` for a missing or unparseable file (`movie_ui_lib.py:107-111`), and `lib.JOB_ID_RE` is at `:35`. The user confirmed this fallback on 2026-10-30.

- **BF41a Precedence.** `last_fields`, when present, always wins. The fallback runs only for a story with no `last_fields`, and its result is never compared with or merged into a job's fields.
- **BF41b Reading (server).** `stored_fields(server, ws_real, story_id)` returns `(code, fields, batch_id, number)`:
  1. `sdir = <ws_real>/generated/stories/<story_id>`. `fork_rec = lib.read_json(<sdir>/fork.json, None)` when `os.lstat(<sdir>/fork.json)` is `S_ISREG`, else `None` (a symlinked `fork.json` is ignored) **[spec choice]**, the same rule as `copy_plan`.
  2. `path = <STATE>/batches/<fork_rec["batch"]>/batch.json`, read only when `fork_rec` is a dict whose `batch` is a string matching `lib.JOB_ID_RE` (this keeps the path inside `batches/`). `batch_rec = lib.read_json(path, {})` when `os.path.isfile(path)`, else `None`. When `path` is not read, `batch_rec = None`.
  3. Return `batch.fork_fallback(fork_rec, batch_rec, story_id, ws_real)`.

  It takes no lock **[spec choice]**: both files are written with `write_json_atomic`, so a read sees a whole file.
- **BF41c Check (pure, `movie_ui_batch.py`).** `fork_fallback(fork_rec, batch_rec, story_id, ws_real)` returns `(code, fields, batch_id, number)`, with the first matching rule winning. Every key is read with `.get`, so a missing key fails its comparison:
  1. `none`: `fork_rec` is not a dict, or `fork_rec["schema"] != FORK_SCHEMA`, or `fork_rec["fork_id"] != story_id`, or `fork_rec["batch"]` is not a string matching `lib.JOB_ID_RE`. Returns `("none", None, None, None)`. **[spec choice]** Without a usable `fork.json` the story is treated like any story with no saved settings.
  2. `gone`: `batch_rec is None`. Returns `("gone", None, <batch>, None)`.
  3. `mismatch`: any of the following fails. Returns `("mismatch", None, <batch>, None)`.
     - `batch_rec` is a dict with `schema == BATCH_SCHEMA`, `id == fork_rec["batch"]`, `workspace == ws_real`, and `cells` a list;
     - exactly one cell is a dict whose `fork_id` equals `story_id` **case-insensitively** (BF15), and its `fork_id` equals `story_id` exactly;
     - that cell has `story_id == fork_rec["source_story"]`, `variant == fork_rec["variant"]`, `status == "queued"`, a string `job_id`, and a dict `fields` whose `story_id == story_id`.

     **[spec choice]** `status == "queued"` is the only cell status whose fork directory survives (refused, cancelled-before-start and interrupted cells have their folder removed), and it is the only status at which `fields` is set (§4.3 step 9).
  4. `ok`: returns `("ok", json.loads(json.dumps(cell["fields"])), <batch>, batch_rec["number"])`.
- **BF41d Field source.** The fallback fields are the cell's `fields` exactly as submitted: the fork's effective fields after merge, including the variant's settings and its edited `narrative`. `merge` treats them like `last_fields` (`compose_fields`, then the fixed keys of §2.2 step 1).
- **BF41e Where it applies.** Everywhere `last_fields` is read for a batch: `story_status` (§3.4), `plan_batch` step 2 (§3.6) and the per-cell recompute (§4.3 step 2). Preview `rows[].fields` holds the fallback fields when they are used, and `rows[].fields_source` / `rows[].fields_batch` follow §3.4.
- **BF41f Deleted batch.** `DELETE /api/batches/<id>` removes the only copy of the fallback fields. Afterwards every fork of that batch with no job is ineligible with the `gone` reason of §3.4. Nothing warns at delete time: the BF39 delete confirmation text is unchanged.

### 3.6 Planning (BF23)

`plan_batch(server, clean, number)` is the single function behind preview, submit and each cell's turn ("same code as submit"). For each cell in grid order, the steps run in this order and the first refusal wins:
1. A missing story directory → `story <id> no longer exists in this workspace`.
2. No fields. The original's fields are `last_fields` when present, else the BF41 fallback fields when `stored_fields` gives `ok`. Otherwise the cell is refused with the text for the BF41 code:
   - `none` → `story <id> has no saved Compose settings (it was started from the command line)`;
   - `gone` → `story <id> has no saved Compose settings (its job and its batch <batch> were deleted)`;
   - `mismatch` → `story <id> has no saved Compose settings (its job was deleted and batch <batch> has no matching record of it)`.
3. Busy → `story <id> has a job queued or running (job <job>)`.
4. Fork ID (BF13, BF15).
5. `merge`.
6. V1 `lib.validate_fields(fork, ws, state)`: a failure is status `invalid` in preview and `refused` at submit, with reason = the lines joined by `\n`.
7. BF7, BF11, BF12, then the level and warnings.

The preview runs no V2-V6. **[spec choice]** It runs V1 as Compose's own preview does (`movie_ui_server.py:728-732`): V1 is fast and must pass before `build_argv` is safe.

---

## 4. Submit and the queue

### 4.1 Submit (BF24-BF26)

- **BF24.** `POST /api/batches`:
  1. `validate_request`.
  2. Under `BATCH_LOCK`: `id = new_batch_id`, `number = next_number`, then `plan_batch` with that number. Cells refused at plan time get status `refused`, and the rest get `pending`.
  3. `order` per §4.2.
  4. Write the record (status `waiting`), append the ID to `server.batch_queue`, and start the submitter (`_batch_kick`: when `batch_thread` is `None` or not alive, start `threading.Thread(target=_batch_submitter, args=(server,), name="batch-submitter", daemon=True)`).
  5. Return 201.

  **[spec choice]** The thread starts on demand so that `mt.Running`, which runs no `start_threads`, works in tests.
- **BF25.** The submitter takes the first ID from `batch_queue` under `BATCH_LOCK`. When there is none, it sets `batch_thread = None` under the same lock and exits. It sets status `submitting`, then runs §4.3 for each index in `order`. Afterwards the status becomes `cancelled` when `cancel_requested` is set, else `submitted`. One batch submits at a time, and later batches wait as `waiting`.
- **BF26.** An exception in any cell refuses that cell with `internal error: <Type>: <message>` (the fork is removed when it was created), writes one stderr line, and the submitter moves on. A failed fork never stops the batch.

### 4.2 Queue order (BF27; BK4)

`order = sorted(indices of pending cells, key=(-rank(level), story index, variant index))`, where `rank` is the index in `LEVELS`. This gives Re-plan, then New stills, then Render, and within a group by story order and then variant order. Each job is appended to the end of the queue when it is accepted (`create_job`, `movie_ui_lib.py:185`). Compose jobs submitted meanwhile interleave. `move_job` still works on forks.

### 4.3 One cell (BF28; verification 2)

**Finding.** `run_checks` takes no lock. `create_compose_job` takes `STORE_LOCK` itself and must not be called while it is held: `threading.Lock` is not re-entrant (`movie_ui_server.py:33`, `:752`). Compose already runs checks unlocked (`:765`).

1. `BATCH_LOCK`: re-read. When `cancel_requested` is set, the cell becomes `cancelled` (reason `batch cancelled`). When its status is not `pending`, skip it. Otherwise set `forking` and write.
2. Recompute with `plan_batch` over the whole batch, from the **current** `last_fields` (or BF41 fallback fields) and the stored number, and take this cell's result **[spec choice: the latest settings at the cell's turn]**. A refusal ends the cell as `refused`.
3. `copy_bytes = sum(copy_plan)`. When `shutil.disk_usage(<ws>/generated/stories).free - copy_bytes < MIN_FREE_BYTES`, refuse with `not enough free space: F GiB free, this fork copies C GiB and at least 20 GiB must stay free` (1 decimal).
4. `os.mkdir`, `fork.json`, the copies (BF18). On `FileExistsError`, refuse with the BF15 "already exists" text. On another `OSError`, call `remove_fork` and refuse with `copy failed: <strerror>: <path>`.
5. Re-check busy (§3.4). When the original got a job, call `remove_fork` and refuse with `story <id> got a job (<job>) while it was being forked; fork it again later`.
6. `checks = lib.run_checks(fork, ws, state)` with **no lock held**. When `not lib.checks_pass(checks)`, call `remove_fork` and refuse with the lines `"<id> <name>: <detail>"` of every `fail` check, joined by `\n`.
7. `BATCH_LOCK`: when `cancel_requested` is set, call `remove_fork` and mark the cell `cancelled`.
8. `job_id = create_compose_job(server, fork)`, which takes `STORE_LOCK` inside.
9. `BATCH_LOCK`: set `job_id`, status `queued`, `fields`, `level`, `diff` and `warnings`. When `cancel_requested` was set meanwhile, release the lock, call `lib.cancel_job` under `STORE_LOCK`, then reconcile (§4.4).

### 4.4 Cancel, restart, delete (BF29-BF34)

- **BF29 Reconcile.** `reconcile(server, batch_id)` runs under `BATCH_LOCK`. Each `queued` cell whose job `status.json` has `state == "cancelled"` and no non-null `started` gets `remove_fork` and status `cancelled` with reason `cancelled before it started`. It runs from every `/api/batches/<id>*` handler, from `GET /api/batches`, and from the hook below. A job that started keeps its directory and partial output. The fork is kept (and the cell still becomes cancelled) while any other job of the workspace names the fork's story; every batch removal path uses this guard (remove_unused_fork; review fix 2026-10-30).
- **BF30 Job cancel hook.** After `_h_job_cancel` gets `"cancelled"` from `cancel_job`, it releases `STORE_LOCK`, finds the batch whose cells hold that `job_id` (a scan of `batches/*/batch.json`), and reconciles it.
- **BF31 Cancel batch.** Steps:
  1. Under `BATCH_LOCK`, take the batch out of `batch_queue`, set `cancel_requested`, and mark the `pending` cells `cancelled`.
  2. For each cell with a job, call `lib.cancel_job` under `STORE_LOCK`.
  3. Reconcile.
  4. Set status `cancelled`.

  It answers 409 when there is nothing to cancel: no pending or forking cell, and no queued, starting or running job. A `forking` cell stops at its next step (up to one `run_checks`, about 60 s).
- **BF32 Restart.** `batch_recovery(state)` is called in `main` right after `lib.startup_recovery(state)` (`movie_ui_server.py:682-683`). For each record with status `waiting` or `submitting`:
  - a `forking` cell with a movie job for `(workspace, fork_id)` created at or after the batch becomes `queued` with that `job_id`;
  - any other `forking` cell gets `remove_fork` and becomes `interrupted` (`the server stopped while this fork was being made`);
  - a `pending` cell becomes `interrupted` (`the server stopped before this fork was made`).

  The batch becomes `interrupted`. For each recovered batch it writes one stderr line, `movie-ui: batch <id>: interrupted (<n> cell(s) to submit again)`. It prints nothing when no batch needs recovery (`test_mut15` asserts an empty stderr).
- **BF33 Submit remaining.** This is only allowed when the status is `interrupted`. `interrupted` cells go back to `pending` (reason `null`), the status becomes `waiting`, the batch is enqueued and kicked, and the stored `order` is kept.
- **BF34 Delete batch.** It is refused while the status is `waiting` or `submitting`. Otherwise `shutil.rmtree(<STATE>/batches/<id>)`. The forks and their jobs are untouched.

### 4.5 Display state (BF35)

`view.cells[i].state` is:
- the cell status, unless it is `queued` with a `job_id`;
- for a queued cell, `lib.job_state(...)` (`queued`/`starting`/`running`/`done`/`failed`/`cancelled`/`lost`);
- `job deleted` when that job directory is gone.

`movie` is `<fork>/movie.mp4` when it is a file, and `dir` says whether the fork directory exists.

---

## 5. UI (BF36-BF40)

Rules: no inline handlers or styles, no `prompt(`/`alert(`/`confirm(`/`eval(` and no second `<script>` (`test_mut24`, `tests/test_movie_ui_http.py:1035-1040`). Confirmations go through `askConfirm`. The `Promise.all` line of `selectWorkspace` (`app.js:264`) is unchanged, because `test_lu13` pins it.

- **BF36 Stories tab** (`index.html:142-143`, `loadStories`):
  - Before `#s-list` add `<div class="row"><button id="s-new-batch" type="button" hidden>New batch (0)</button></div>`.
  - `#s-list` thead gains a first `<th>Pick</th>`.
  - Each row's first cell holds `<input type="checkbox" class="s-pick">`, filled from `GET /api/batches/stories`. It is disabled with `title` = the server's `reason` when it is not eligible. Its click calls `stopPropagation`, so it does not open the story.
  - When the row's `fields_source` is `"batch"`, the same cell also holds `<span class="s-pick-note muted">settings from batch b<N></span>`, where `N` is `fields_batch.number`, and the span's `title` is `This fork's job was deleted; its settings come from batch <id>`. Rows with `"job"` or `null` get no note.
  - `#s-new-batch` shows when at least 1 box is ticked, with the text `New batch (N)`. Clicking it opens the editor with the ticked IDs in list order.
- **BF37 Batches tab.** `<button id="tab-batches" type="button" class="tab">Batches</button>` goes right after `tab-stories`. `TABS` becomes `["compose", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"]`, and `showTab("batches")` calls `loadBatches()`. `<section id="panel-batches" class="panel" hidden>` holds three boxes, one shown at a time:
  - `#b-list-box`: `<table id="b-list" class="list">` with headers `Batch`, `Created`, `Done`, `Status`. Each row holds the ID, the local created time, `D/T` and the status, and a row click opens the batch page.
  - `#b-editor` (BF38) and `#b-page` (BF39).
- **BF38 Editor (`#b-editor`).**
  - `<h2>New batch</h2>`, then `<p id="b-editor-stories" class="muted">` (`Stories: a, b`).
  - `<button id="b-add-variant" type="button">Add variant</button>`, which is disabled at 6, with `<span id="b-variant-note" class="muted">` showing `at most 6 variants` when disabled.
  - `<div id="b-variants">` holds cards `div.b-variant`. Each card has:
    - `input.b-label`, defaulting to `v1`..`v6` (maxlength 24);
    - `select.b-add-setting`, whose first option `Add setting…` (value `""`) is followed by `<optgroup label="Render">` (Video model, Gemma, Video LoRAs, Actions, Frames per panel, FPS, No low-RAM mode, Panel timeout (s)), `<optgroup label="New stills">` (Resolution, Stills LoRAs, Location strength) and `<optgroup label="Re-plan">` (Size, Goal, Seed image, Mode, Story model, Auto-pick catalog LoRAs, Narration, Cast, Locations, Legacy story engine, Judge with Claude) **[spec choice: the menu shows each setting's cost]**. A setting already on the card is disabled in the menu;
    - `div.b-settings` lists only the added settings, as `div.b-setting` rows of a label, the control and a `Remove` button;
    - the prompt changes: `textarea.b-append` (placeholder `Append to every prompt`), `div.b-replaces` with `button.b-add-replace` `Add find → replace`, and rows `div.b-replace` (`input.b-find` placeholder `Find`, `input.b-with` placeholder `Replace with`, `Remove`; at most 10);
    - `button.b-remove-variant` `Remove variant` (hidden when only 1 card is left).
  - **Controls** are `cloneNode(true)` copies of the Compose controls with every `id` removed. The keys map to controls as follows:
    - `model` `#c-model`, with the `__download__` option removed;
    - `gemma` `#c-gemma`;
    - `action_loras` `#c-actions` + `#c-action-strength`;
    - `frames` `#c-frames`;
    - `fps` `#c-fps`;
    - `no_low_ram` `#c-no-low-ram`;
    - `panel_timeout` `#c-panel-timeout`;
    - Resolution `#c-res-preset` + `#c-width` + `#c-height`, where a preset sets both numbers;
    - `location_strength` `#c-location-strength`;
    - Size: `<select class="b-size-kind">` with `Panels` (`panels`) or `Seconds` (`length`), plus `#c-panels`;
    - `goal` `#c-goal`;
    - Seed image `#c-seed-file`, through the existing `uploadFile`;
    - `mode` `#c-mode`;
    - `story_model` `#c-story-model`;
    - `auto_lora` `#c-auto-lora`;
    - `narration` `#c-narration`;
    - `characters` `#c-characters`;
    - `locations` `#c-locations`;
    - `story_legacy` `#c-story-legacy`;
    - `judge` `#c-judge`.

    The LoRA lists use `loraRow(target, item, container)` and `collectLoras(target, container)`, where the new optional `container` defaults to the Compose container, so existing calls are unchanged. A control starts at `rows[0].fields[key]` from the preview.
  - `<table id="b-preview" class="list">` has a header row `Story` plus one column per variant label. The `Story` cell holds the story ID and, when that preview row's `fields_source` is `"batch"`, the same `span.s-pick-note` text and `title` as BF36. Each variant cell shows:
    - the fork ID;
    - `span.badge.level-render|level-stills|level-replan` with the `LEVEL_LABELS` text;
    - one diff line per entry (`key: from → to`, where LoRAs show their `id` or file name and `narrative` shows `prompt edited`);
    - `ul.warnings`;
    - the refusal reason when the cell is refused or invalid;
    - `button.b-edit-prompt` `Edit prompt`.
  - `<p id="b-totals">` shows `totals.text`.
  - `<button id="b-submit" type="button">Submit batch</button>` (disabled when `totals.jobs == 0`), `<button id="b-discard" type="button">Discard</button>` and `<span id="b-editor-status" class="muted">`.
  - Any input or change inside `#b-editor` re-posts the preview, debounced 300 ms with a sequence guard as in Compose's `preview` (`app.js:406-425`). On a 201, Submit opens the batch page.
  - The prompt dialog (after `#confirm`): `<div id="b-prompt-dialog" class="dialog" hidden><div class="dialog-box">` with `<h3 id="b-prompt-title">` (`Prompt for <story> in <label>`), `<textarea id="b-prompt-text" rows="12" cols="80">` (prefilled with the per-story text or the original narrative), `<p id="b-prompt-count" class="muted">` (`N / 20000 characters`), `<button id="b-prompt-save">Use this prompt</button>`, `<button id="b-prompt-original">Use the original</button>` (which deletes the key) and `<button id="b-prompt-close">Cancel</button>`.
- **BF39 Batch page (`#b-page`).**
  - `<h2 id="b-page-title">` reads `Batch <id> (<status>)`.
  - The actions are `<button id="b-back">All batches</button>`, `<button id="b-cancel">Cancel batch</button>` (confirm: `Cancel batch <id>? Queued forks are removed; running jobs stop and keep their partial output.`), `<button id="b-resume" hidden>Submit remaining</button>` (shown only for `interrupted`), `<button id="b-delete">Delete batch</button>` (confirm: `Delete the record of batch <id>? The forks stay as ordinary stories.`) and `<span id="b-page-status" class="muted">`.
  - `<table id="b-grid" class="list">` has the headers `Story`, `Original` and the variant labels.
  - The first cell of each row holds the story ID and `button.b-play-row` `Play row`.
  - The original cell holds `<video controls preload="metadata">` of the original's `movie.mp4`, or `no movie.mp4 yet`.
  - Each variant cell holds:
    - a video once `movie` is set;
    - `span.chip` with the state and progress (`Phase <phase>: <phase_title>, panels <panels_done>/<panels_total>` while active; `queued (#<queue_position>)`; `refused: <reason>`);
    - the level badge and the diff lines;
    - `button.b-open` `Open story` (when `dir`; it selects the batch workspace, then calls `openStory(fork_id)`);
    - `button.b-log` `Log` (with a job; it calls `selectJob(job_id)` and `showTab("jobs")`);
    - `button.b-cancel-cell` `Cancel` (when the job is queued, starting or running; it calls `POST /api/jobs/<id>/cancel`).
  - **Play row:** every video in the row is paused, gets `currentTime = 0` and `muted = true` except the original's (`muted = false`), then each `play()` is called in the same click handler.
  - **Polling:** `S.timers.batch = setInterval(pollBatch, BATCH_POLL_MS)` runs while `#b-page` is shown and is cleared on leaving it. `stopPolling` also clears `"batch"`.
  - **User-confirmed 2026-10-30:** the page is a section of `index.html` driven by `app.js`, not a second HTML document. It reuses the session token, workspace, `openStory`, `selectJob` and the poll loop, and keeps the single-script rule of `test_mut24`.
- **BF40 CSS.** `app.css` gains `.level-render`, `.level-stills`, `.level-replan` (three distinct border colours, with dark-mode variants inside the existing `@media (prefers-color-scheme: dark)`), `.chip` and `#b-grid video {max-width: 320px}`.

---

## 6. Errors

| Condition | Where | Message | HTTP / effect |
|---|---|---|---|
| no or bad token | every route | `missing or invalid token` | 401 |
| bad `ws` | all `?ws=`/body routes | the `resolve_ws` messages | 400 |
| stories not a list of 1-24 distinct valid IDs | preview, submit | `stories must be a list of 1 to 24 distinct story IDs` | 400 `invalid batch` |
| variants not 1-6 | preview, submit | `variants must be a list of 1 to 6 variants` | 400 |
| too many cells | preview, submit | `a batch has at most 24 cells; this one has N (S stories x V variants)` | 400 |
| bad label | preview, submit | `variant K: label must be 1 to 24 characters with no line breaks` | 400 |
| fixed or unknown key | preview, submit | `variant K: setting KEY cannot be changed in a variant` | 400 |
| narrative as a setting | preview, submit | `variant K: change the prompt with append, replace or per-story text` | 400 |
| panels and length | preview, submit | `variant K: give panels or length, not both` | 400 |
| width without height | preview, submit | `variant K: give width and height together` | 400 |
| seed and resolution | preview, submit | `variant K: give a seed image or a resolution, not both` | 400 |
| append | preview, submit | `variant K: append must be a string of at most 20000 characters` | 400 |
| replace list | preview, submit | `variant K: replace must be a list of at most 10 {find, with} pairs` | 400 |
| find | preview, submit | `variant K: replace pair J: find must be 1 to 20000 characters` | 400 |
| with | preview, submit | `variant K: replace pair J: with must be a string of at most 20000 characters` | 400 |
| per_story key | preview, submit | `variant K: per_story must map story IDs of this batch to text` | 400 |
| per_story text | preview, submit | `variant K: per-story prompt for ID must be 1 to 20000 characters` | 400 |
| every cell refused | submit | `every cell was refused` + `cells` | 409, no record |
| unknown batch | `/api/batches/<id>*` | `unknown batch <id>` | 404 |
| nothing to cancel | cancel | `batch <id> has nothing to cancel` | 409 |
| not interrupted | resume | `batch <id> was not interrupted` | 409 |
| still submitting | delete | `batch <id> is still submitting; cancel it first` | 409 |
| delete fails | delete | `cannot delete batch <id>: <strerror>` | 500 |
| no stored fields: batch deleted | `/api/batches/stories` `reason` (checkbox `title`) | `Its job and its batch <batch> were deleted: no saved Compose settings to fork` | ineligible |
| no stored fields: record mismatch | `/api/batches/stories` `reason` (checkbox `title`) | `Its job was deleted and batch <batch> has no matching record of this fork: no saved Compose settings to fork` | ineligible |
| no stored fields: batch deleted | preview, submit, cell turn | `story <id> has no saved Compose settings (its job and its batch <batch> were deleted)` | cell `refused` |
| no stored fields: record mismatch | preview, submit, cell turn | `story <id> has no saved Compose settings (its job was deleted and batch <batch> has no matching record of it)` | cell `refused` |
| cell refusals | cell `reason` | the texts of BF7, BF11-BF13, BF15, §3.6 and §4.3 | cell `refused`, no folder |

`K` and `J` are 1-based. Several 400 lines are returned together, in table order.

---

## 7. Tests

Rules:
- Every test uses `mt.set_home`, `mt.make_stub_workspace` and the in-test `mt.Running` server on 127.0.0.1.
- Originals are made with `make_job(..., status={"state": "done", ...})` so that they have `last_fields`.
- `lib.run_checks` is monkeypatched to return pass or a given failure, except in BT26, where it is wrapped.
- Batch HTTP tests post, then wait with `mt.wait_until(..., 30)` until `GET /api/batches/<id>` reports status `submitted` (or the state under test). The submitter thread started by the route does the work; tests never call `_batch_submitter` directly.
- Nothing renders, no test contacts a real server, and none touches port 8178. `conftest.py` keeps the VLM lifecycle off.

| ID | File | Covers |
|---|---|---|
| BT1 | `tests/test_movie_ui_batch.py` (new) | **BK1**: `set(FIELD_LEVELS) ∪ set(FIXED_KEYS) == set(DEFAULT_FIELDS)`, the two sets are disjoint, each level matches §2.1, and a one-key change per editable key (parametrised, 25 cases) gives that level |
| BT2 | same | merge: `compose_fields` defaults and old boolean narration; fixed keys forced; the four group couplings |
| BT3 | same | prompt edits: per-story text, then replace (every occurrence, pairs in order), then append with `\n\n`; per-story text also gets replace and append; the exact no-match warning; the over-length warning |
| BT4 | same | identical refusal: no change, location strength without locations, `goal` `"x."` vs `"x"`, whitespace-only edit; duplicate-variant refusal text |
| BT5 | same | a no-op key is dropped from the diff and the level (model + strength without locations → `render`) |
| BT6 | same | length-sized story: a frames change that moves the resolved count → `replan` with the `panels` entry; one that does not → `render`; the shorter-clips warning text |
| BT7 | same | fork IDs: plain; `next_number` from records and from `-b7-v1` directories; a 78-character ID shortened to exactly 80 with `-._` stripped and valid; case-insensitive in-batch collision; an existing directory |
| BT8 | same | `copy_plan` on a fixture with every file kind: the exact render, stills and replan lists; every BF17 item is absent; a symlink is skipped; a clip without provenance is skipped |
| BT9 | same | every 400 message of §6, exact and in order (7 variants, 5×5 cells, …) |
| BT10 | same | **BK4 (unit)**: `order` for 2 stories × {render, replan, stills} variants is `[s1v2, s2v2, s1v3, s2v3, s1v1, s2v1]` |
| BT11 | same | `totals.text` with and without refused cells |
| BT12 | same | an original without story.md → `replan` + warning |
| BT13 | same | static page: `node --check app.js` (when node exists); each §5 ID appears in `index.html` exactly once; the `TABS` string; labels `New batch (`, `Play row`, `Submit remaining`, `Use the original`, `Add setting…`, `settings from batch b`; no forbidden pattern of `test_mut24` |
| BT14 | `tests/test_movie_ui_http.py` | every batch route: 401 without or with a wrong token; 404 for an unknown batch; 405 for `PUT /api/batches` |
| BT15 | same | `/api/batches/stories`: CLI story ineligible with its exact reason; queued and running originals busy; UI story eligible |
| BT16 | same | preview equals submit: `fork_id`, `level`, `diff` and `warnings` of every preview cell equal the record's after the submitter runs |
| BT17 | same | **BK4 (HTTP)**: one unrelated job is already queued; after the batch, `queue.json` is that job, then the forks in BT10 order |
| BT18 | same | **BK5**: one cell fails V6 (patched): its reason is `V6 dry run: <detail>`, no folder remains, and the next cells are queued |
| BT19 | same | a job is queued for an original between preview and submit → that story's cells are refused with the busy text; the others are queued |
| BT20 | same | Cancel batch: pending cells cancelled; queued jobs cancelled with folders removed; a running job (`make_job` + a status `running` with a live lock holder) → `cancelling` and its folder kept; 409 on a second cancel |
| BT21 | same | delete: 409 while `submitting`; afterwards the record is gone and the fork dirs, `fork.json` files and jobs remain |
| BT22 | same | all cells identical → 409 `every cell was refused`, no `batches/` entry |
| BT23 | same | `shutil.disk_usage` patched to 20 GiB free → the exact space text, no folder |
| BT24 | same | **BK3**: Render fork (model change), `stub_config` `{"ltx-movie run": {"stdout": "=== Phase 1: story ===\n"}}`, `mt.dispatch` to `done`. The fork's copied files have the original's sha256, and the stub's recorded `argv` equals `lib.build_argv(<original fields as action movie>, ws, state)[2:]` with only the `--story-id` value and the `--model` value changed |
| BT25 | same | **BK2**: sha256 of every file under the original (relpath → digest) is identical before the batch and after both forks ran (stub) |
| BT26 | same | during the wrapped `run_checks`, a second thread acquires `srv.STORE_LOCK` within 1 s, and `STORE_LOCK.locked()` is `False` inside it |
| BT27 | same | **BK5**: cancel a queued fork through `/api/jobs/<id>/cancel` → folder removed, cell `cancelled`; a fork cancelled while `starting` (runner "cancelled before start") is removed by the next `GET` |
| BT28 | `tests/test_movie_ui_jobs.py` | **BK5**: `batch_recovery` on a record with a `forking` cell (folder, no job) → folder removed + `interrupted`; a `forking` cell with a job → `queued`; `pending` → `interrupted`; status `interrupted`; prints nothing when nothing needs recovery |
| BT29 | `tests/test_movie_ui_http.py` | after BT28's state, `resume` → 200 `waiting`, the cells are processed and queued; a second `resume` → 409 |
| BT30 | `tests/test_vlm_lifecycle.py` | Render and New-stills fork jobs record `vlm` `forbidden` and a Re-plan fork records `required`; `vlm_restore_wanted` after a Re-plan fork with a Render fork next → `(False, ...)` |
| BT31 | `tests/test_movie_ui_batch.py` | **BK8 (unit)**: `fork_fallback` on a matching pair → `ok`, the cell's `fields` (equal, not the same object) and the record's `number`; each BF41c `none` rule (not a dict, wrong schema, wrong `fork_id`, bad `batch`) → `none`; `batch_rec None` → `gone`; each BF41c `mismatch` rule (parametrised: wrong schema, wrong `id`, other `workspace`, no cell, two cells differing only in case, cell `fork_id` differing only in case, other `source_story`, other `variant`, status `cancelled`, `job_id` null, `fields` null, `fields.story_id` other) → `mismatch` |
| BT32 | `tests/test_movie_ui_http.py` | **BK8, fallback used**: submit a 1×1 Render batch (model change), `mt.dispatch` the fork job to `done`, then `DELETE /api/jobs/<id>`. `/api/batches/stories` gives the fork `eligible: true`, `reason: null`, `fields_source: "batch"`, `fields_batch: {"id": <batch>, "number": 1}`. A preview with the fork as the story gives `rows[0].fields_source == "batch"` and `rows[0].fields["model"]` = the first batch's variant model. Submitting a second batch (gemma change) queues a job whose `fields` keep that model, change `gemma`, and have `story_id` `<fork>-b2-v1` |
| BT33 | same | **BK8, last_fields wins**: after the first batch of BT32 with the fork job kept, the cell's `fields.model` in `batch.json` is rewritten on disk to another value. `/api/batches/stories` gives the fork `fields_source: "job"` and `fields_batch: null`, and the preview's `rows[0].fields["model"]` is the job's model |
| BT34 | same | **BK8, missing or mismatched record**: from BT32's state with the job deleted, (a) remove `fork.json` → ineligible with the `Started from the command line…` reason and `fields_source: null`; (b) parametrised, one edit per case with both files restored between cases: `batch.json` cell `status` to `cancelled`, `batch.json` `workspace` to another path, `fork.json` `variant` to 2 → each ineligible with the exact `mismatch` reason, and a preview cell refused with the exact `mismatch` refusal text |
| BT35 | same | **BK8, deleted batch**: from BT32's state, `DELETE /api/batches/<id>` → the fork is ineligible with `Its job and its batch <id> were deleted: no saved Compose settings to fork` and `fields_source: null`; a preview cell is refused with `story <fork> has no saved Compose settings (its job and its batch <id> were deleted)`; submitting only that story → 409 `every cell was refused` |

### 7.1 Existing tests to re-baseline (one test-only commit, after the feature commit)

| Test | Reason and exact edit |
|---|---|
| `tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token` (`:43`) | 8 new routes: `== 46` becomes `== 54` |
| `tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token` (`:66`) | the same route count: `== 46` becomes `== 54` |
| `tests/test_location_ui.py::test_lu13_the_static_page` (`:389-390`) | new tab: the asserted `TABS` string gains `"batches", ` after `"stories", ` |
| `tests/test_movie_ui_builder.py` `NEW_PY` (`:213-215`) | new module and test file: add `"movie_ui_batch.py"` and `"tests/test_movie_ui_batch.py"` at the end, so they are compiled and scanned |
| `tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files` (`:257-259`) | `movie_ui_server.py` now imports `movie_ui_batch`: the `allowed` set gains `"movie_ui_batch"` |
| `tests/movie_ui_testutil.py::copy_ui` (`:464`) | `test_mut15` starts a copied `bin/movie-ui`, whose import would fail: the copied list gains `"movie_ui_batch.py"` |

Checked and unaffected:
- `test_mu69` (`/api/stories` rows unchanged);
- `test_mut24` (one script, no forbidden patterns);
- `test_store_writes_atomically…` (iterates `STATE_SUBDIRS`);
- `test_mut15` (no new stdout, empty stderr);
- the `FIELD_FLAGS`/`DEFAULT_FIELDS` counts (unchanged);
- `test_lu13` string and ID counts (untouched lines);
- `test_mut26` (no pipeline file changes).

## 8. KPIs

| ID | Criterion | Verified by |
|---|---|---|
| BK1 | Every `DEFAULT_FIELDS` key is classified exactly as in §2.1 | BT1 |
| BK2 | An original story directory is byte-identical (sha256 of every file) before and after a batch whose forks ran on the stub | BT25 |
| BK3 | A Render fork's stub run sees the copied story and stills unchanged, and its argv differs from the original's only in the story ID and the changed flags | BT24 |
| BK4 | The queue order is Re-plan → New stills → Render, then by story and then by variant, after the existing queue | BT10, BT17 |
| BK5 | Refused, interrupted and cancelled-before-start cells leave no fork folder | BT18, BT23, BT27, BT28 |
| BK6 | `test_mut26_pipeline_files_are_unchanged` passes unedited | full run |
| BK7 | `python3 -m pytest tests/ -q -rA` from `WS` shows exactly the baseline failures recorded at `574303a` before any edit, and the pass count is the baseline plus every BT test. The only edits to existing tests are §7.1, in one test-only commit | full run before and after |
| BK8 | A fork with no job is eligible exactly when its `fork.json` and batch cell match (BF41c), and then uses the cell's submitted fields; `last_fields` always wins; a deleted batch or a mismatched record leaves it ineligible with the exact §6 texts | BT31, BT32, BT33, BT34, BT35 |

Live check after the merge (not a merge gate): 1 story × 2 Render variants on the user's machine, with both forks playing in the compare page and Play row starting them together. Never on macstudio.

## 9. Rollout

1. Snapshot `WS` (house rule): `tar czf <scratchpad>/snapshot-pre-batch-574303a.tgz`, excluding `generated/`.
2. At `574303a`, record the full-suite pass count and failure list.
3. Make the feature commit: G1-G4 plus the BT tests.
4. Make the test-only commit (§7.1).
5. Run BK1-BK8, then an Opus design review of the diff against this spec.

## 10. Risks

- **R1 VLM reloads.** Each Re-plan fork still stops the story server after its Phase 1 (`bin/ltx-movie:448-458`), so N Re-plan cells can cost up to N 5-14 min loads. Grouping only avoids the extra loads that interleaving would add.
- **R2 Run-time recheck.** A Render fork with shorter clips or new pinned video LoRAs is re-checked at Phase 1 (`story_engine.py:4982`, lora checks), but V6 does not recheck. Such a job can fail after it is queued, with the recheck's message. BF10 warns about the clip case.
- **R3 Copy size.** Render forks copy clips (gigabytes). The 20 GiB floor applies per cell, at that cell's turn.
- **R4 Visible half-forks.** A fork directory appears in the Stories list during its checks (about 60 s) and vanishes if the cell is refused.
- **R5 Settings drift.** `last_fields` may not match a story.md that was later hand-edited or regenerated from the command line. The fork copies the real files, so it inherits that drift.
- **R6 Preview drift.** `number` and `last_fields` can change between preview and submit, and between submit and a cell's turn (BF28 step 2).
- **R7 Cancel latency.** Cancel batch waits up to one `run_checks` for a forking cell.

## 11. Resolved questions

- **Q1 (2026-10-30).** A resolution change is New stills, not Render (§2.1): the user confirmed it.
- **Q2 (2026-10-30).** A batch fork whose job was deleted stays eligible through its batch record's cell fields; `last_fields` wins when present (BF41, §3.5).
- **Q3 (2026-10-30).** The compare page is a section of `index.html` and `app.js`, not a second HTML document (BF39): the user confirmed it.
