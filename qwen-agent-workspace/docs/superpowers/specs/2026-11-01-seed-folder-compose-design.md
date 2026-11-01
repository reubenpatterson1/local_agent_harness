# Seed-folder Compose and Characters: one job per seed image, from a picked folder

Date: 2026-11-01

Status: design spec. The user approved the design (scratchpad `seed-folder-design-notes.md`, Sections 1-4) on 2026-11-01, and the Characters addendum (scratchpad `seed-folder-characters-notes.md`) the same day. This document carries that design without reopening it. Each detail the notes leave open is decided here and marked **[spec choice]**, and Section 10 lists them all. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/seedf-wt`, branch `seed-folder`, HEAD `e94ebb0`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `e94ebb0`.

Builds on **[MUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md` (routes, jobs, V1-V6), **[BF]** `docs/superpowers/specs/2026-10-30-batch-forks-design.md` (module style, `job_index`) and **[CE]** `docs/superpowers/specs/2026-10-30-chained-end-frames-design.md` (`check_seams`, CE14).

Terms: a **seed** is one image in the picked folder. A **run** is one queue request of either new endpoint. A **row** is one seed's result. Requirement IDs are SD1-SD50 and tests are SDT1-SDT37 (the Characters addendum is SD36-SD50 and SDT26-SDT37). No existing spec, test or source file uses `SD<n>` or `SDT<n>` IDs (checked with grep at `e94ebb0`).

---

## 0. Scope

### 0.0 The approved design (binding summary)

1. In Compose, the Resolution fieldset gets a third choice, "Seed folder". Every seed becomes its own job, with the Compose narrative and settings shared by all of them. Only the image and the story ID differ.
2. The browser picks the folder (`webkitdirectory`) and uploads each image through the existing `POST /api/uploads`. The server never reads a typed path.
3. The story ID is the cleaned file stem. The Compose Story ID field becomes an optional prefix. Collisions get a suffix (`beach`, `beach-2`, …), and nothing that exists is touched.
4. A confirm table lists every seed (file, story ID, OK or reason). Queue submits only the OK seeds.
5. The jobs are plain queued story or movie jobs, in file-name order, with a "seed folder" tag on the Jobs page. There is no Batches entry.
6. A new endpoint, `POST /api/jobs/seed-folder`, does the work (approach 1).
7. **Characters addendum.** The Characters tab gets the same folder mode. Each seed becomes one `character-create` job, and the character is named from the file name. Every character shares the form's referring phrase and seed (user decisions). It uses the same picker, confirm table, preview/queue pattern, run ID, tag, auto-suffix and "queue the valid ones" policy, through `POST /api/characters/seed-folder` (§2.4, §3.5, §4.1). The controller's defaults in the addendum notes are decided in §10 items 27-39.

### 0.1 Grounding (verified at `e94ebb0`)

- **Routes and handlers.** `ROUTES` is at `movie_ui_server.py:69-121`, with `POST /api/jobs` at `:100`. It has 55 entries, which `tests/test_movie_ui_http.py:44` and `tests/test_location_ui.py:66` assert. Handlers are attached as `MovieUIHandler.h_* = _h_*` (`:955-964`). `ApiError(status, message)` answers `{"error": message}` (`:131-136`). `STORE_LOCK` is a plain, non-reentrant `threading.Lock` (`:35`).
- **Compose path.** `_fields_body` is `compose_fields` plus `resolve_ws` (`:738-741`). `_h_validate` runs `lib.run_checks` (`:757-762`). `_create_seams_job` needs the caller to hold `STORE_LOCK` (`:765-776`). `create_compose_job` takes `STORE_LOCK` itself and queues a seams job behind a chained movie when `seams` is true (`:779-795`). `_h_job_create` runs checks with no lock, then calls `create_compose_job` with `seams=body.get("check_seams") is True` (`:798-805`).
- **Job summary.** `job_summary` returns 14 keys (`:723-735`), and `test_mut2_preview_argv_is_the_job_argv` asserts that exact key set (`tests/test_movie_ui_http.py:342-344`).
- **Uploads.** `_h_upload` stores `<STATE>/uploads/<sha256>.<ext>` and answers `{"upload_id", "path", "bytes"}` (`:985-995`). Its refusals are `upload larger than 20 MiB` (413), `unsupported content type` (415) and `file content is not <type>` (400) (`:458-464`, `:988-989`). The same bytes always give the same `upload_id`.
- **Busy stories.** `job_index(server, ws_real)` returns `(last_fields, busy)`, where `busy` maps the story ID of every queued, starting or running job of `ws_real` to a job ID (`:2000-2017`).
- **Library.** `UPLOAD_ID_RE` `movie_ui_lib.py:36`. `STORY_ID_RE` (at most 80 characters) `:37`. `SMOKE_STORY_ID = "movie-ui-smoke"` `:40`. `new_job_id` (UTC `%Y%m%d-%H%M%S` + 4 hex) `:165-171`. `create_job` writes `job.json` atomically, then `log.txt`, then appends to `queue.json`, with the caller holding `STORE_LOCK` (`:174-190`). `DEFAULT_FIELDS` `:942-955`. `compose_fields` keeps only `DEFAULT_FIELDS` keys (`:977-986`). `build_argv` adds `--seed-image <STATE>/uploads/<id>` for `seed_upload` (`:1016-1073`, seed `:1027-1028`). `last_line` `:1234-1237`. `check`/`checks_pass` `:1298-1304`. `valid_story_id` `:1319-1321`. `validate_fields` (V1) is at `:1443-1549`: rule 1 refuses `movie-ui-smoke` case-insensitively (`:1450-1454`), rule 7 gives `seed image upload <id> not found` and does nothing for a `None` seed (`:1492-1501`), and rule 8 refuses a seed with `shots` or `no_stills` (`:1502-1508`). `host_checks` `:1666`, `model_checks` `:1815`, `lora_checks` `:1939`, `compat_checks` `:2013`. `DRY_RUN_TIMEOUT = 60` `:1889`. `dry_run_check` gives detail `bin/ltx-movie --dry-run timed out after 60 s` on a timeout, else stdout + stderr (`:2102-2108`). `run_checks` `:2115-2126`.
- **Dry run.** `bin/ltx-movie --dry-run` validates the seed before printing anything: it reports a missing, unreadable or degenerate image (`SEED_MIN_EDGE = 64`, `:129`) on stderr as `Error: --seed-image …` and exits 2, writing nothing (`_seed_geometry` `:1270-1293`, `_print_dry_run_plan` `:2478-2496`).
- **UI.** In `index.html`, the Story ID label is at `:47`, the Resolution fieldset at `:65-84` (seed image `:81-83`) and the Compose buttons at `:133-139`, followed by `c-checks` `:140` and `c-smoke-check` `:141`. In `app.js`: `S` `:11-15`, `el` `:21-33` (string children become text nodes), `askConfirm` `:105-125`, `composeFields` `:370-401`, `preview` `:411-430`, `showChecks` `:432-437`, `validate` `:439-444`, `submit` `:446-460`, `gate` `:462-468`, `updateComposeButtons` `:470-476`, `uploadFile` `:478-483`, `onSeedFile` `:485-497`, `fillCompose` `:499-550`, `setupCompose` `:552-588`, `jobLabel` `:1935-1937`, `selectJob` `:2017`, `pollJobs` `:2029`, `pollJobsOnce` `:2043-2095`. `loadOptions` hides every `[data-field]` node whose flag is unsupported (`:275-278`).
- **Characters.** `CHARACTER_NAME_RE` `movie_ui_lib.py:38`. `character_argv` `:1167-1197`. `character_create_errors` `movie_ui_server.py:1242-1281`, `create_character_job` (takes `STORE_LOCK`, job `story_id` `None`, `character` = name) `:1284-1289`, `_h_character_create` `:1292-1302`. The library is `$CHARACTER_LIBRARY_DIR` or `<ws>/generated/characters` (`character_lib.py:258-259`). `bin/character create` refuses an existing `<library>/<name>` (`character_dataset.py:1158-1160`), derives a unique trigger when none is given (`:1273-1274`, `character_lib.py:526-539`) and refuses a missing or small face unless `--force` (`character_dataset.py:1255-1263`). In `index.html` the Characters form is at `:210-219`. In `app.js`, `updateCharacterButtons` is at `:1508-1516` and `createCharacter` at `:1518-1544`.
- **Static-page rules.** `test_mut24` and `test_ct27` forbid `https?://`, `\son[a-z]+=`, `style=`, `\balert\(`, `\bconfirm\(`, `\bprompt\(`, `\beval\(` and `new Function` in `index.html`, `app.js` and `app.css` (`tests/test_movie_ui_seams.py:364-374`). `test_ct27` pins the `c-run-all`/`c-check-seams-box` lines (`:329-332`).
- **Tests.** `tests/movie_ui_testutil.py`: `set_home`, `make_stub_workspace` (its `ltx-movie --dry-run` exits 0 unless `stub_config` says otherwise), `Running` (no dispatcher or probe threads), `api`, `make_job`, `PNG`, and `copy_ui` with a fixed file list (`:459-469`). `tests/test_movie_ui_builder.py`: `NEW_PY` (`:213-216`) is compiled on Python 3.9 and scanned for forbidden patterns, and the import allow-list for `movie_ui_lib.py`/`movie_ui_server.py` is at `:258-260`. `conftest.py` turns the VLM lifecycle off.

### 0.2 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `movie_ui_seedfolder.py` (new) | constants, `first_free`, story-ID and character-name rules, taken sets, request validation, row reasons, run ID, tag (§1.1, §2, §3) |
| G2 | `movie_ui_lib.py` | `shared_checks` extracted from `run_checks` (SD2) |
| G3 | `movie_ui_server.py` | 2 routes, `_h_seed_folder`, `seed_taken`, `seed_rows`, `_dry_runs`, `_compose_job_locked`, `job_summary` key; `_h_character_seed_folder`, `character_taken`, `_character_job_locked`, `_phrase_errors`, `_seed_number_errors` (§3.5) |
| G4 | `static/movie-ui/index.html`, `app.js` | shared folder code (`FOLDER_BOXES`), Compose Seed folder radio, Characters Seed folder checkbox, lists, confirm tables, Jobs tag (§4, §4.1). `app.css` is unchanged |
| G5 | tests | §6 |

Untouched: every pipeline file (`bin/ltx-movie`, `bin/character`, `character_lib.py`, `character_dataset.py` and the rest of `PIPELINE_FILES`), `movie_ui_batch.py`, the behaviour of `/api/preview`, `/api/validate`, `/api/jobs` and `/api/characters`, and the Batches page. `test_mut26` passes unedited.

### 0.3 Out of scope

- The seed generator tab (prompt + seed → edited seed, Z-Image img2img or Qwen-Image-Edit). It is a separate later spec.
- A `--seed-dir` CLI flag.
- Any Batches-page entry or batch record for a run.
- Subfolders, typed paths, and reading a folder on the server.
- In Characters folder mode: a per-run `--force`, a shared class noun, descriptor or trigger, and a command preview.

### 0.4 Must-haves and nice-to-haves

Every SD requirement and every SDT test is a must-have. There are no nice-to-haves.

---

## 1. Architecture

```
Compose, "Seed folder": pick folder -> filter + natural sort -> upload one by one (POST /api/uploads)
Run all | Write story -> POST /api/jobs/seed-folder {preview: true}  -> confirm table
Queue N jobs          -> POST /api/jobs/seed-folder {preview: false, OK seeds only}
server, per request:  1 provisional IDs (no lock) -> 2 V1 per seed -> 3 V2-V5 once
                      -> 4 V6 per seed, 4 at a time (no lock) -> 5 preview: answer
                      -> 6 queue: STORE_LOCK { final IDs -> create jobs in seed order } -> answer
dispatcher (unchanged) runs each job as an ordinary story or movie job
```

- **SD1.** `movie_ui_seedfolder.py` imports only `re`, `secrets`, `time`, `unicodedata` and `movie_ui_lib as lib`. It is Python 3.9-compatible, never writes, and never starts a process. All its functions are pure except `new_run_id` (clock and random). The server imports it as `import movie_ui_seedfolder as seedfolder`. **[spec choice]** A module of its own, like `movie_ui_batch.py`, keeps `movie_ui_lib.py` unchanged apart from SD2.
- **SD2.** `movie_ui_lib.py` gains, directly above `run_checks`:
  ```python
  def shared_checks(fields, ws_real, py=sys.executable):
      """V2-V5 of run_checks for fields that passed V1 (seed-folder spec SD2, SD16)."""
      cache = {}
      return (host_checks(fields, ws_real, py) + model_checks(fields, ws_real)
              + lora_checks(fields, ws_real, cache) + compat_checks(fields, ws_real, cache))
  ```
  The last statement of `run_checks` becomes `return [v1] + shared_checks(fields, ws_real, py) + [dry_run_check(fields, ws_real, state)]`. The records and their order are unchanged, so `/api/validate` and `/api/jobs` are unchanged. The V1 and smoke branches are untouched.
- **SD3.** The body of `create_compose_job` below its docstring moves into `_compose_job_locked(server, fields, seams=False)` (same docstring, plus "The caller holds STORE_LOCK."). `create_compose_job` becomes `with STORE_LOCK: return _compose_job_locked(server, fields, seams)`. **[spec choice]** `STORE_LOCK` is not reentrant, and a run creates many jobs in one hold.
- **SD4.** Nothing new is stored: no state file, no state subdirectory, no queue type, no job kind. A run's only trace is the `seed_folder` key in each job's fields (SD20).

### 1.1 Constants (`movie_ui_seedfolder.py`)

```python
SEEDS_MAX = 100
PREFIX_MAX = 40
ID_MAX = 80                                   # STORY_ID_RE, movie_ui_lib.py:37
DRY_RUN_WORKERS = 4
RUN_ID_RE = re.compile(r"^sf-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_OUTSIDE = re.compile(r"[^A-Za-z0-9._-]+")
```
`app.js`: `const SEEDS_MAX = 100;`, `const SEED_TYPES = ["image/png", "image/jpeg", "image/webp"];`, `const SEED_COLLATOR = new Intl.Collator("en", {numeric: true});`.

---

## 2. Story IDs

### 2.1 The rules as code (SD5-SD8)

- **SD5.** `seed_stem(name)` applies rules 1-4 of the notes. **[spec choice]** The extension is what follows the last `.` at an index above 0, so `.png` keeps its whole name as the stem. That keeps a leading-dot name from becoming empty before rule 4.
  ```python
  def seed_stem(name):
      """Rules 1-4: the cleaned stem of a seed's file name; never empty."""
      dot = name.rfind(".")
      stem = name[:dot] if dot > 0 else name                                    # 1
      stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")   # 2
      stem = _OUTSIDE.sub("-", stem)                                            # 3
      stem = re.sub(r"\.{2,}", ".", stem)
      stem = re.sub(r"-{2,}", "-", stem)
      stem = re.sub(r"^[^A-Za-z0-9]+", "", stem).rstrip("-._")                  # 4
      return stem or "seed"
  ```
- **SD6.** `valid_prefix(prefix)` is `prefix == "" or (lib.valid_story_id(prefix) and len(prefix) <= PREFIX_MAX)`. The prefix is used exactly as typed (no case change, no cleaning).
- **SD7.** `first_free(head, stem, taken, limit, trim)` is the candidate loop that story IDs and character names (SD38) share. `story_id_for(stem, prefix, taken)` applies rules 5-7 through it. `stem` is a `seed_stem` result, `prefix` passes `valid_prefix`, and `taken` is a set of lower-case names, which neither function modifies.
  ```python
  def first_free(head, stem, taken, limit, trim):
      """The first free head + cut stem [+ "-k"] of at most limit characters (SD7, SD38)."""
      def candidate(suffix):
          room = limit - len(head) - len(suffix)
          return head + stem[:room].rstrip(trim) + suffix

      first = candidate("")
      if first.lower() not in taken:
          return first
      for k in range(2, 12 * (len(taken) + 1) + 10):
          name = candidate("-%d" % k)
          if name.lower() not in taken:
              return name
      raise AssertionError("no free name")      # unreachable (bound below)


  def story_id_for(stem, prefix, taken):
      """Rules 5-7: the first free story ID for one stem (SD7)."""
      return first_free(prefix + "-" if prefix else "", stem, taken, ID_MAX, "-._")
  ```
  - **Truncation [spec choice].** The room is computed for each candidate. The unsuffixed ID keeps the longest stem, and only a suffixed candidate gives up stem characters to make room. The prefix is never cut. The trailing trim is applied again after the cut.
  - **Never empty, always valid.** `len(head) <= 41`, so `room >= 1` for every suffix shorter than 39 characters. The stem starts with a letter or digit, so the cut stem keeps at least that character. A candidate starts with a letter or digit, uses only `[A-Za-z0-9._-]`, has at most 80 characters, and has no `..`. Neither part contains `..`, and the stem's first character is never `.`.
  - **Loop bound.** The candidates whose `k` has the same number of digits share one cut stem, so they are pairwise distinct, even case-folded. Let `n = len(taken) + 1`. The smallest digit group whose size `9·10^(d-1)` is at least `n` (or the group 2-9 when `n <= 8`) ends below `12·n + 10`. So a free candidate always exists inside the loop's range, and the `AssertionError` cannot be reached. **[spec choice]** An explicit bound instead of an endless loop.
  - **Case.** Comparison is case-insensitive (`.lower()`; every candidate is ASCII). The returned ID keeps the file's case.
- **SD8.** `assign_story_ids(names, prefix, taken)` returns the list of IDs for `names`, in order:
  ```python
  def assign_story_ids(names, prefix, taken):
      """Rules 1-7 for every name in order; taken is not modified (SD8)."""
      seen = set(taken)
      out = []
      for name in names:
          story_id = story_id_for(seed_stem(name), prefix, seen)
          seen.add(story_id.lower())
          out.append(story_id)
      return out
  ```
  An earlier seed of the same call takes its ID for the later seeds, so the same name (or the same image) twice gets two IDs.

### 2.2 The taken set (SD9)

- **SD9.** `taken_names(listing, busy_story_ids)` returns `{n.lower() for n in listing} | {s.lower() for s in busy_story_ids if isinstance(s, str)} | {lib.SMOKE_STORY_ID}`. The server computes it with `seed_taken(server, ws_real)`:
  ```python
  def seed_taken(server, ws_real):
      """SD9: the lower-case names a seed's story ID must avoid."""
      try:
          names = os.listdir(os.path.join(ws_real, "generated", "stories"))
      except OSError:
          names = []
      return seedfolder.taken_names(names, job_index(server, ws_real)[1])
  ```
  - `os.listdir` lists directories, files and symlinks, including dangling ones. Lower-casing the listing makes the test "anything exists at `<ws>/generated/stories/<name>` (lexists), case-insensitive" exact on any file system. **[spec choice]** One listing instead of one `lexists` per candidate and per case variant.
  - The busy IDs are `job_index`'s `busy` keys: every queued, starting or running job of this workspace, whatever its kind. **[spec choice]** `job_index` already defines "busy" for batch forks, so the two features agree.
  - **[spec choice]** `movie-ui-smoke` is always taken. V1 rule 1 would refuse that ID, and a suffix fits the "collisions get a suffix" rule better than a refused row.

### 2.3 Examples (SD10; SDT1)

- **SD10.** `assign_story_ids` gives exactly these results. Rows 1-7 are the notes' examples.

| # | names (in order) | prefix | taken | result |
|---|---|---|---|---|
| 1 | `beach.png` | `""` | `{}` | `beach` |
| 2 | `beach.png`, `beach.jpg` | `""` | `{}` | `beach`, `beach-2` |
| 3 | `Beach Day!.webp` | `temple` | `{}` | `temple-Beach-Day` |
| 4 | `__01.png` | `""` | `{}` | `01` |
| 5 | `日本.png` | `""` | `{}` | `seed` |
| 6 | `beach.png` | `""` | `{beach, beach-2}` | `beach-3` |
| 7 | `Beach.png` | `""` | `{beach}` | `Beach-2` |
| 8 | `Beach Day.final.png` | `""` | `{}` | `Beach-Day.final` |
| 9 | `Café.png` | `""` | `{}` | `Cafe` |
| 10 | `a..b.png`, `a -- b.png` | `""` | `{}` | `a.b`, `a-b` |
| 11 | `.png` | `""` | `{}` | `png` |
| 12 | `Beach.png`, `beach.jpg` | `""` | `{}` | `Beach`, `beach-2` |
| 13 | `movie-ui-smoke.png` | `""` | `taken_names([], [])` | `movie-ui-smoke-2` |
| 14 | `"a"*100 + ".png"` | `"p"*40` | `{}` | `"p"*40 + "-" + "a"*39` (80 characters) |
| 15 | `"a"*100 + ".png"` | `"p"*40` | `{("p"*40 + "-" + "a"*39).lower()}` | `"p"*40 + "-" + "a"*37 + "-2"` (80) |
| 16 | `"a"*77 + "-bc.png"` | `""` | `{("a"*77 + "-bc").lower()}` | `"a"*77 + "-2"` (the cut leaves `"a"*77 + "-"`, which the trim cleans) |
| 17 | `x.png` | `""` | `{x} ∪ {x-2 … x-999}` | `x-1000` |

### 2.4 Character names (SD36-SD40)

The Characters folder mode (addendum, §0.0 item 7) names one character per seed. The rules map the Compose rules onto `CHARACTER_NAME_RE = ^[a-z][a-z0-9-]{1,23}$` (`movie_ui_lib.py:38`; `character_lib.NAME_RE`, `character_lib.py:30`). Constants in `movie_ui_seedfolder.py`: `CHAR_MAX = 24` and `CHAR_PREFIX_MAX = 12`.

- **SD36.** `character_stem(name)`:
  ```python
  def character_stem(name):
      """Character name rules 1-6 (SD36): lower case, at least 2 characters."""
      dot = name.rfind(".")
      stem = name[:dot] if dot > 0 else name                                    # 1 (as SD5)
      stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii").lower()   # 2, 3
      stem = re.sub(r"[^a-z0-9]+", "-", stem)                                   # 4
      stem = re.sub(r"^[^a-z]+", "", stem).rstrip("-")                          # 5
      if len(stem) < 2:                                                         # 6
          stem = stem + "-char" if stem else "char"
      return stem
  ```
  Rule 4 turns every run of other characters, `.` and `_` included, into one `-`, so a stem never has `--`. Rule 5 strips leading digits as well, because a name must start with a letter. **[spec choice]** Rule 6 keeps a single letter as `<letter>-char` (so `a.png` and `b.png` stay told apart) and uses `char` for an empty stem.
- **SD37.** `valid_character_prefix(prefix)` is `prefix == "" or (isinstance(prefix, str) and lib.CHARACTER_NAME_RE.fullmatch(prefix) is not None and len(prefix) <= CHAR_PREFIX_MAX)`. The prefix is used as typed. **[spec choice]** At most 12 characters: with the `-`, that leaves 11 of the 24 for the image's part and any suffix.
- **SD38.** `character_name_for(stem, prefix, taken)` is `first_free(prefix + "-" if prefix else "", stem, taken, CHAR_MAX, "-")` (SD7's shared helper), and `assign_character_names(names, prefix, taken)` is SD8's loop with `character_stem` and `character_name_for` in place of `seed_stem` and `story_id_for`. Every result matches `CHARACTER_NAME_RE`:
  - The head has at most 13 characters, so the room is at least 1 for any suffix of up to 10 characters (k < 10^9).
  - The stem starts with a letter, so the cut keeps at least that letter.
  - Without a suffix or prefix the name is the stem: at least 2 characters, and a cut at 24 drops at most one trailing `-`. With a suffix or a prefix it has at least 3.
  - SD7's loop bound holds while `len(taken) < 83,000,000`.
- **SD39. Taken.** `character_taken_names(listing, busy_names)` returns `{n.lower() for n in listing} | {s.lower() for s in busy_names if isinstance(s, str)}`. The server computes it with:
  ```python
  def character_taken(server, ws_real):
      """SD39: the names a seed's character must avoid."""
      library = os.environ.get("CHARACTER_LIBRARY_DIR") or os.path.join(ws_real, "generated", "characters")
      try:
          names = os.listdir(library)
      except OSError:
          names = []
      state, queue = server.state, lib.read_queue(server.state)
      busy = [job["character"] for job in (server.job(i) for i in lib.list_job_ids(state))
              if job is not None and job.get("workspace") == ws_real and isinstance(job.get("character"), str)
              and lib.job_state(state, job["id"], queue) in ("queued", "starting", "running")]
      return seedfolder.character_taken_names(names, busy)
  ```
  - `library` mirrors `character_lib.library_dir()` (`character_lib.py:258-259`), the library `bin/character` uses. The runner inherits the server's environment (`movie_ui_lib.py:212`), so both see the same directory. **[spec choice]** A filesystem listing needs no `bin/character list` subprocess.
  - `bin/character create` refuses any existing path at `<library>/<name>` (`character_dataset.py:1158-1160`). The lower-cased listing covers that, case-insensitive file systems, and dangling symlinks. The library's own entries (`.triggers`, `.lock`) cannot collide, because names start with a letter.
  - The busy names are those of every queued, starting or running job of the workspace with a string `character`. **[spec choice]** All character job kinds, not only `character-create`: a regenerate or train job names a character that exists anyway, so the wider set is the same or safer.
- **SD40. Examples.** `assign_character_names` gives exactly these results (SDT26):

| # | names (in order) | prefix | taken | result |
|---|---|---|---|---|
| 1 | `Kyra.png` | `""` | `{}` | `kyra` |
| 2 | `Kyra.png`, `kyra.jpg` | `""` | `{}` | `kyra`, `kyra-2` |
| 3 | `Old Man #2.webp` | `temple` | `{}` | `temple-old-man-2` |
| 4 | `01_hero.png` | `""` | `{}` | `hero` |
| 5 | `日本.png` | `""` | `{}` | `char` |
| 6 | `a.png` | `""` | `{}` | `a-char` |
| 7 | `kyra.png` | `""` | `{kyra, kyra-2}` | `kyra-3` |
| 8 | `Café Owner.png` | `""` | `{}` | `cafe-owner` |
| 9 | `"x"*30 + ".png"` | `""` | `{}` | `"x"*24` |
| 10 | `"x"*30 + ".png"` | `""` | `{"x"*24}` | `"x"*22 + "-2"` |
| 11 | `abcdefghij-klm.png` | `"p"*12` | `{}` | `"p"*12 + "-abcdefghij"` (the cut leaves `abcdefghij-`, which the trim cleans) |
| 12 | `2049.png` | `""` | `{}` | `char` |
| 13 | `shot_01.png`, `Shot 01.png` | `""` | `{}` | `shot-01`, `shot-01-2` |

---

## 3. The endpoint

### 3.1 Route and body (SD11-SD13)

- **SD11.** `("POST", r"/api/jobs/seed-folder", "h_seed_folder", "/api/jobs/seed-folder")` is inserted directly after the `POST /api/jobs` entry (`movie_ui_server.py:100`). The route count goes from 55 to 56. `_ID` cannot match `seed-folder`, so no other route changes. `GET /api/jobs/seed-folder` answers 405. `MovieUIHandler.h_seed_folder = _h_seed_folder` joins the block at `:955-964`.
- **SD12.** The body is the usual Compose field object plus:
  ```json
  {"story_id": "temple", "action": "movie",
   "seeds": [{"name": "Beach Day!.webp", "upload_id": "<64 hex>.webp"}],
   "preview": true, "check_seams": true}
  ```
  - `story_id` is the prefix. An absent key, `null` or `""` means no prefix **[spec choice]**.
  - `seeds` holds 1 to 100 items, in page order. The server never re-sorts them.
  - `preview` must be a boolean. **[spec choice]** A body without it is refused, so a malformed request can never queue.
  - `check_seams` follows `/api/jobs`: only `true` turns it on, and any other value means off **[spec choice]**.
  - `seed_upload`, `width` and `height` are ignored: they are forced to `null`, and the seed sets the geometry.
  - Other fields go through `lib.compose_fields` as in `/api/jobs`.
  - Item keys other than `name` and `upload_id` are ignored.
- **SD13.** `seedfolder.validate_request(body)` returns `(clean, None)` or `(None, error)`, where `clean = {"prefix", "action", "seeds": [{"name", "upload_id"}], "preview", "check_seams"}` (`upload_id` is the item's value, or `None` when absent). The handler first runs `_fields_body(body)` (the `resolve_ws` 400s), then this function, and answers the **first** failing rule as `ApiError(400, <message>)` **[spec choice: single `error`, like every Compose route]**:

| # | Rule | Message |
|---|---|---|
| 1 | `ws` missing, not absolute, or not a workspace | the existing `resolve_ws` messages |
| 2 | `body.get("action", "story")` not `"movie"` or `"story"` | `action must be movie or story` |
| 3 | prefix (SD12) not a string, or fails `valid_prefix` | `story ID prefix must be a valid story ID of at most 40 characters` |
| 4 | `seeds` not a list, empty, or longer than 100 | `seeds must be a list of 1 to 100 items` |
| 5 | item K (1-based) not an object | `seed K must be an object` |
| 6 | item K's `name` not a string, or contains `/` | `seed K: name must be a string without '/'` |
| 7 | `preview` absent or not a boolean | `preview must be true or false` |

  Rows 4-7 are checked by `_seeds_and_preview(body)`, which returns `(seeds, preview, None)` or `(None, None, error)` and is shared with `validate_character_request` (SD43). A missing, malformed or unknown `upload_id` is not a 400: that row is refused (SD15). A name has no length rule beyond the 25 MiB body limit, because the notes' 400 list is complete.

### 3.2 Steps (SD14-SD18)

`_h_seed_folder` sets `fields = _fields_body(body)`, validates (SD13), then sets `fields["seed_upload"] = fields["width"] = fields["height"] = None`. It then calls `seed_rows(server, fields, clean)`, which does steps 1-4 with **no lock held**:

- **SD14. Step 1, provisional IDs.** `ids = seedfolder.assign_story_ids([s["name"] for s in seeds], prefix, seed_taken(server, ws))`, covering every seed.
- **SD15. Step 2, V1 per seed.** Each seed gets `f = dict(fields, story_id=<its ID>, seed_upload=<its upload_id>)`. If `upload_id` is not a non-empty string, `errors = ["seed image upload missing"]` **[spec choice: V1 lets a `None` seed through, so the server says it]**. Otherwise `errors = lib.validate_fields(f, ws, state)`. The V1 record is `lib.check("V1", "fields", "fail" if errors else "pass", "\n".join(errors))`. A setting that is wrong for every seed (for example mode `shots`) gives the same reason on every row.
- **SD16. Step 3, shared checks once.** If at least one seed passed V1, `shared = lib.shared_checks(<fields of the first passing seed>, ws)`. Otherwise `shared = []`, and `shared_checks` is not called. The shared checks pass when `lib.checks_pass(shared)` is true (only `fail` fails, as in `/api/jobs`).
- **SD17. Step 4, V6 per seed.** When the shared checks pass, `_dry_runs(server, rows)` runs `lib.dry_run_check(f, ws, state)` for every V1-passing seed. It uses at most `seedfolder.DRY_RUN_WORKERS` (4) `threading.Thread` workers, which take the next seed index from a shared counter guarded by a local `threading.Lock`, and joins them all. **[spec choice]** Plain threads add no import to `movie_ui_server.py`, whose imports `test_mut25` pins. If `dry_run_check` raises, that seed's V6 record is `lib.check("V6", "dry run", "fail", "dry run error: %s: %s" % (type(e).__name__, e))`. Neither `STORE_LOCK` nor `BATCH_LOCK` is held. A seed that does not reach V6 gets `lib.check("V6", "dry run", "skip", d)`, where `d` is `"skipped: V1 failed"` after a V1 failure and `"skipped: shared checks failed"` after a shared failure.
- **SD18. Status and reason.** `status` and `reason` come from `seedfolder.row_reason(v1, v6)`, in this order:

| Case | `status` | `reason` |
|---|---|---|
| V1 failed | `refused` | the V1 detail with `"\n"` replaced by `"; "` |
| V6 skipped after a shared failure | `skipped` | `skipped: shared checks failed` |
| V6 failed with detail `bin/ltx-movie --dry-run timed out after <DRY_RUN_TIMEOUT> s` | `refused` | `dry run timed out after 60 s` (the number is `lib.DRY_RUN_TIMEOUT`) |
| V6 failed otherwise | `refused` | `dry run failed: ` + `lib.last_line(detail)`, or `dry run failed` when that line is empty |
| otherwise | `ok` | `null` |

  `row_reason` returns `(status, reason)`. A bad seed fails the dry run with its `Error: --seed-image …` line (exit 2), so its reason reads, for example, `dry run failed: Error: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)`.

### 3.3 Preview and queue (SD19-SD22)

- **SD19. Preview.** With `preview: true` the handler answers **200** with the body of SD21, with `queued: 0` and `run: null`, and creates nothing: no job, no queue entry, no directory, no upload.
- **SD20. Queue.** With `preview: false`:
  1. Steps 1-4 run again, server-side.
  2. If no row is `ok`, the answer is **409** with the SD21 body (`queued: 0`, `run: null`), and nothing is created or locked.
  3. Otherwise `run = seedfolder.new_run_id()`. Then, **under one `STORE_LOCK` hold**: `final = seedfolder.assign_story_ids(<names of the ok rows, in seed order>, prefix, seed_taken(server, ws))`. For each ok row in seed order, `f = dict(<its step-2 fields>, story_id=final[i], seed_folder={"run": run, "name": <its name>})` and `job_id = _compose_job_locked(server, f, seams=clean["check_seams"])`. The lock is then released.
  4. After the lock: `queue = lib.read_queue(state)`. Each queued row's `story_id` becomes its final ID and its `job` becomes `job_summary(server, job_id, queue)`. The answer is **201**.
  - **[spec choice]** Only the ok rows draw final IDs, so a refused seed does not push a later seed to a suffix. A final ID can differ from the ID V1 and V6 used. Both name a story folder that did not exist, and the response shows the final ID.
  - Jobs are created in seed order, so the queue holds them in file-name order. A chained movie with `check_seams` gets its seams job right behind it, as in `/api/jobs` ([CE] CE14). The seams job's fields stay `{"ws", "story_id", "after"}`, with no tag **[spec choice: the existing path, unchanged]**.
  - Steps 1-4 never run under `STORE_LOCK`. The lock covers only the listing, `job_index`, ID assignment and job creation.
- **SD21. Response.** Every answer of SD19 and SD20 has this shape (409 has the same body, with no `error` key):

| Key | Type | Value |
|---|---|---|
| `ok` | bool | at least one row has status `ok` |
| `shared_checks` | list of check records | V2-V5 from SD16; `[]` when no seed passed V1 |
| `queued` | int | movie or story jobs created (seams jobs not counted); 0 for a preview or a 409 |
| `refused` | int | rows with status `refused` or `skipped` |
| `run` | str or null | the run ID when `queued >= 1`, else `null` |
| `seeds` | list, one per request seed, in order | `{"name": str, "upload_id": <as sent, null when absent>, "story_id": str, "status": "ok"/"refused"/"skipped", "reason": str or null, "checks": [<V1 record>, <V6 record>], "job": <job_summary> or null}` |

  `story_id` is the provisional ID, except for a queued row, which shows its final ID. `job` is non-null only for a queued row.
- **SD22. Run ID.** `new_run_id()` returns `"sf-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)`, which matches `RUN_ID_RE`. **[spec choice]** There is no uniqueness loop: no state records a run, and the ID is a display tag only.

### 3.4 Jobs and other routes (SD23-SD25)

- **SD23.** `seedfolder.seed_tag(fields)` returns `{"run": v["run"], "name": v["name"]}` when `fields` is a dict whose `"seed_folder"` value `v` is a dict with string `run` and `name`, else `None`. `job_summary` gains the key `"seed_folder": seedfolder.seed_tag(job.get("fields"))`, giving 15 keys. **[spec choice]** The Jobs page needs the tag, and `GET /api/jobs` returns summaries only.
- **SD24.** `lib.compose_fields` is unchanged and drops `seed_folder` (it keeps only `DEFAULT_FIELDS` keys). So reload-into-Compose, `last_fields` and batch forks see a seed-folder job as a single-seed job with `seed_upload` set. `/api/preview`, `/api/validate` and `/api/jobs` behave exactly as before (SD2, SD3), including for a body that carries `seeds` or `seed_folder`.
- **SD25.** Each job is created by `lib.create_job`, which writes `job.json` atomically before it touches `queue.json`. If creation stops partway (server killed, or an exception), every earlier job of the run stays whole, queued and visible on Jobs. A later seed has no `job.json`, so `list_job_ids` and `startup_recovery` ignore it. An exception inside the lock leaves through the `with` block (`STORE_LOCK` is released) and answers the existing 500 `internal error`. No rollback is attempted.

### 3.5 Characters endpoint (SD41-SD46)

Character create has no V2-V6. Per-seed validation is `character_create_errors` (`movie_ui_server.py:1242-1281`).

- **SD41. Route.** `("POST", r"/api/characters/seed-folder", "h_character_seed_folder", "/api/characters/seed-folder")` is inserted directly after the `POST /api/characters` entry. The route count goes from 56 to 57. `_NAME` also matches `seed-folder`, but the router keeps looking after a method mismatch (`:390-396`), so `GET /api/characters/seed-folder` still reaches `h_character` (a character named `seed-folder` stays viewable). `POST /api/characters/<name>` had no route before. `MovieUIHandler.h_character_seed_folder = _h_character_seed_folder` joins the block at `:1332-1343`.
- **SD42. Body.**
  ```json
  {"ws": "/abs/ws", "name": "temple", "phrase": "the stranger", "seed": 7,
   "seeds": [{"name": "Kyra.png", "upload_id": "<64 hex>.png"}], "preview": true}
  ```
  - `name` is the prefix. An absent key, `null` or `""` means no prefix.
  - `phrase` and `seed` are shared by every character (user decision).
  - `class_noun`, `descriptor`, `trigger` and `force` are ignored and forced to `null`, `null`, `null` and `false`, and `seed_upload` is set per seed. **[spec choice: ignored, not refused, like Compose's `width`/`height`]**
    - With no trigger, `bin/character` derives one per character from its name and class noun, unique against the trigger registry (`character_dataset.py:1273-1274`, `character_lib.py:526-539`, registered at `character_dataset.py:1292`). Jobs run one at a time, so each create sees the earlier ones' triggers.
    - With no class noun, the vision model supplies it per image (`:1266-1267`).
    - `force` is not an overwrite switch: it lets a seed through a missing or small face (`:1107`, `:1261`). **[spec choice]** Folder mode never forces. A face-refused seed's job fails with the tool's message and creates nothing (the face check runs before any directory is made, `:1261` vs `:1279`), so its name stays free. A per-run force would skip the face check for every image.
- **SD43. 400s.** The handler checks in this order and answers the first failure as `ApiError(400, <message>)`:

| # | Rule | Message |
|---|---|---|
| 1 | `ws` | the existing `resolve_ws` messages |
| 2 | `phrase` | the first message of `_phrase_errors(body.get("phrase"))`: `phrase is required`, `phrase contains invalid characters` or `phrase must not start with '-'` |
| 3 | `seed` | the message of `_seed_number_errors(body.get("seed"))`: `seed must be an integer from 0 to 2147483647` |
| 4 | prefix not `null`/`""` and not a string, or fails `valid_character_prefix` | `character name prefix must match [a-z][a-z0-9-]{1,23} and be at most 12 characters` |
| 5-8 | as SD13 rows 4-7 | the same messages |

  - `_phrase_errors(phrase)` and `_seed_number_errors(seed_n)` are the phrase block and the seed-number check of `character_create_errors`, moved out unchanged. `character_create_errors` calls them at the same positions, so `POST /api/characters` gives the same errors in the same order.
  - Rows 4-8 are `seedfolder.validate_character_request(body)`, which returns `(clean, None)` or `(None, error)` with `clean = {"prefix", "seeds", "preview"}`. It shares `_seeds_and_preview(body)` with `validate_request` (SD13).
- **SD44. Steps.**
  1. With no lock held, `names = seedfolder.assign_character_names(<seed names>, prefix, character_taken(server, real))`.
  2. Each seed gets `b = {"name": <its name>, "phrase": phrase, "seed": seed, "seed_upload": <its upload_id>, "class_noun": None, "descriptor": None, "trigger": None, "force": False}`. If `upload_id` is not a non-empty string, `errors = ["seed image upload missing"]`. Otherwise `errors = character_create_errors(b, state)`, which here can only report the upload (`seed image upload <id> not found`), because steps 2-4 of SD43 already passed. The row's V1 record is `lib.check("V1", "fields", "fail" if errors else "pass", "\n".join(errors))`. Its status is `refused` with reason `"; ".join(errors)`, or `ok`.
  3. `preview: true` → 200 (SD46), with nothing created.
  4. `preview: false` → steps 1-2 run again. With no ok row → 409 (SD46). Otherwise `run = seedfolder.new_run_id()`. Then, under one `STORE_LOCK` hold: `final = assign_character_names(<names of the ok rows>, prefix, character_taken(server, real))`. For each ok row in seed order, `fields = {"name": final[i], "phrase": phrase, "class_noun": None, "descriptor": None, "trigger": None, "seed": seed, "seed_upload": <its upload_id>, "force": False, "ws": real, "seed_folder": {"run": run, "name": <its file name>}}` and `job_id = _character_job_locked(server, "character-create", real, fields)`. After the lock, the answer is 201. These are `_h_character_create`'s keys (`:1292-1302`) plus `seed_folder`. The argv is `lib.character_argv("character-create", fields, real, state)`: `create <name> --phrase <phrase> --seed-image <STATE>/uploads/<id> [--seed N] --no-review`.
- **SD45.** The body of `create_character_job` up to and including `lib.create_job(...)` moves into `_character_job_locked(server, kind, real, fields)`, which returns the job ID ("The caller holds STORE_LOCK."). `create_character_job` becomes `with STORE_LOCK: job_id = _character_job_locked(server, kind, real, fields)`, followed by its unchanged `return 201, {...}`.
- **SD46. Response and jobs.** The response is SD21's shape and status codes, with three differences:
  - Each row has `character` (str) where Compose has `story_id`.
  - `checks` is `[<V1 record>]`.
  - `shared_checks` is always `[]`, and no row is `skipped`. **[spec choice]** Keeping the key keeps one response shape, so the page shares one renderer.

  `queued` counts `character-create` jobs. `job_summary`'s `seed_folder` (SD23) works unchanged, and `jobLabel` shows the character name. `last_create_fields` of a seed-folder character includes `seed_folder`. The detail page's "Create anyway (--force)" posts those fields to `POST /api/characters`, whose handler copies only its own keys, so the tag is dropped there.

---

## 4. UI (SD26-SD35)

- **SD26. HTML.** In `index.html`:
  - Line 47 becomes `<label data-field="story_id"><span id="c-story-id-label">Story ID</span> <input id="c-story-id" type="text" size="30"></label>`.
  - Directly after `<span id="c-seed-status" class="muted"></span>` (`:83`), inside the Resolution fieldset:
    ```html
          <label data-field="seed_upload"><input id="c-res-folder" type="radio" name="c-res" value="folder"> Seed folder
            <button id="c-folder-choose" type="button">Choose folder…</button>
            <input id="c-folder-file" type="file" webkitdirectory hidden></label>
          <span id="c-folder-status" class="muted"></span>
          <ul id="c-folder-list" class="muted" hidden></ul>
    ```
    **[spec choice]** A hidden input behind a "Choose folder…" button, because a file input's own button text is set by the browser.
  - Directly after `<div id="c-smoke-check" hidden></div>` (`:141`):
    ```html
      <div id="c-folder-confirm" hidden>
        <h3>Seed folder</h3>
        <ul id="c-folder-shared" class="checks"></ul>
        <p id="c-folder-summary" class="muted"></p>
        <table id="c-folder-table" class="list"><thead><tr><th>File</th><th>Story ID</th><th>Result</th><th>Job</th></tr></thead><tbody></tbody></table>
        <div class="row">
          <button id="c-folder-queue" type="button" disabled>Queue 0 jobs</button>
          <button id="c-folder-cancel" type="button">Cancel</button>
        </div>
      </div>
    ```
  - The lines that `test_ct27` pins are unchanged.
- **SD27. Shared folder code; pick.** One set of functions serves the Compose and Characters folder modes. Each function takes a `box` from this table, placed directly after `S` in `app.js` (`S` itself gains no folder fields):
  ```js
  const FOLDER_BOXES = {
    compose: {ids: "c-folder", endpoint: "/api/jobs/seed-folder", idKey: "story_id", shared: true,
              mode: function () { return $("#c-res-folder").checked; },
              select: function () { $("#c-res-folder").checked = true; },
              refresh: function () { updateComposeButtons(); preview(); },
              folder: null, seq: 0, body: null, rows: null, busy: false},
    characters: {ids: "ch-folder", endpoint: "/api/characters/seed-folder", idKey: "character", shared: false,
                 mode: function () { return $("#ch-folder-mode").checked; },
                 select: function () { $("#ch-folder-mode").checked = true; },
                 refresh: function () { updateCharacterButtons(); },
                 folder: null, seq: 0, body: null, rows: null, busy: false}
  };
  function part(box, name) { return $("#" + box.ids + "-" + name); }
  ```
  `setupCompose` (for `compose`) and `setupCharacters` (for `characters`) wire the same four listeners: a click on `part(box, "choose")` calls `part(box, "file").click()`, a `change` on `part(box, "file")` calls `onFolderPick(box)`, `part(box, "queue")` calls `queueFolder(box)`, and `part(box, "cancel")` calls `closeFolderConfirm(box)`. `onFolderPick(box)` works in this order:
  1. It sets `box.seq += 1` (an older upload loop stops, SD28), copies `Array.from(part(box, "file").files)`, then sets the input's `value = ""` (so picking the same folder again fires `change`).
  2. It keeps a file only when `(f.webkitRelativePath.match(/\//g) || []).length === 1`, `SEED_TYPES.indexOf(f.type) >= 0` and `!f.name.startsWith(".")`.
  3. It sorts by `SEED_COLLATOR.compare(a.name, b.name)` (`shot2` before `shot10`).
  4. With 0 files, `part(box, "status")` = `no PNG, JPEG or WebP images directly in this folder`, `box.folder = null`, stop.
  5. With more than `SEEDS_MAX` files, `part(box, "status")` = `found N images; at most 100 per run — pick a smaller folder` (N = the count), `box.folder = null`, stop.
  6. Otherwise `box.folder = {files: [{name, file, state: "waiting", upload_id: null, reason: null}], uploading: true}`, `box.select()` runs, `closeFolderConfirm(box)` runs, and the upload loop of SD28 starts.

  After step 4, 5 or 6 it calls `renderFolderList(box)` and `box.refresh()`.
- **SD28. Upload.** The loop uploads the files one at a time, in list order, with the existing `uploadFile(file)`. Before each file it sets `part(box, "status")` = `uploading I of N…` (I is 1-based) and the file's state to `uploading`. On success the state becomes `uploaded` with its `upload_id`. On failure the state becomes `failed` with `reason = err.message.replace(/^upload failed: /, "")`, and the loop goes on. After each file it calls `renderFolderList(box)` and `box.refresh()`. If `box.seq` changed (a new pick), the old loop stops at once without touching the page. At the end, `box.folder.uploading = false` and the status reads `uploaded U of N images`, plus ` (F failed)` when F > 0. `renderFolderList(box)` fills `part(box, "list")` with one `<li>` per file: `<name> — <state text>`, where the state text is `waiting`, `uploading…`, `uploaded` or `upload failed: <reason>`. It shows the list only when `box.mode()` is true and `box.folder` is set. `uploadedSeeds(box)` returns the `uploaded` files in list order.
- **SD29. Compose folder mode.** Here `box` is `FOLDER_BOXES.compose`, and `folderMode()` is `box.mode()`. `updateComposeButtons()` keeps its current four statements, then:
  - `#c-story-id-label` = `Story ID prefix (optional)` in folder mode, else `Story ID`.
  - `#c-validate.disabled = folderMode()` **[spec choice: the confirm table is the folder's validation]**.
  - It calls `renderFolderList(box)`.
  - Outside folder mode it calls `closeFolderConfirm(box)` and stops. `box.folder` is kept, so switching back restores the list.
  - In folder mode `#c-smoke.disabled = true` and `#c-smoke-reason` = `not available for a seed folder`.
  - `folderBlock(box)` gives the block text: `pick a seed folder` (no `box.folder`), `uploading seeds…` (uploading), `no seed uploaded` (no file `uploaded`), else `null`. With a block, `#c-run-all` and `#c-write-story` are disabled, and the block text is added to each reason span (after `; ` when the span already has text).

  `composeFields` gains `const byFolder = $("#c-res-folder").checked;`, and `width`/`height` are `null` when `bySeed || byFolder`. `seed_upload` stays `bySeed ? S.seedUpload : null`.
- **SD30. Command preview.** In folder mode, `preview()` changes the fields before `POST /api/preview`. The first file of `uploadedSeeds(FOLDER_BOXES.compose)` sets `seed_upload` (else `null`), and `story_id = sampleStoryId(<its name, or "seed">, <the prefix field>)`. `#c-command-for` reads `(<action>, first seed <name>, sample story ID)`, or `(<action>, no seed uploaded yet)`. `sampleStoryId` applies rules 1-6 (no suffix). It is the JS form of SD5 plus the first candidate of SD7:
  ```js
  function sampleStoryId(name, prefix) {
    const dot = name.lastIndexOf(".");
    let stem = (dot > 0 ? name.slice(0, dot) : name).normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
    stem = stem.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/\.{2,}/g, ".").replace(/-{2,}/g, "-");
    stem = stem.replace(/^[^A-Za-z0-9]+/, "").replace(/[-._]+$/, "") || "seed";
    const head = prefix ? prefix + "-" : "";
    return head + stem.slice(0, Math.max(1, 80 - head.length)).replace(/[-._]+$/, "");
  }
  ```
  The preview is a sample. The real IDs come from the server. The Characters tab has no command preview.
- **SD31. Opening the confirm table.** In Compose folder mode, Write story sets `S.composeAction = "story"` and calls `openFolderConfirm(FOLDER_BOXES.compose, Object.assign(composeFields("story"), {check_seams: false}))`. Run all sets `S.composeAction = "movie"` and calls `openFolderConfirm(FOLDER_BOXES.compose, Object.assign(composeFields("movie"), {check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked}))`. Outside folder mode both buttons do what they do today. (Characters: SD49.) `openFolderConfirm(box, base)`:
  1. `seeds` = `uploadedSeeds(box)` as `{name, upload_id}`.
  2. `body = Object.assign(base, {seeds: seeds, preview: true})`. For Compose, `story_id` already holds the trimmed prefix.
  3. `box.body = body`. This freezes the request **[spec choice]**, so the Queue click sends what the table showed, even after later form edits.
  4. `box.rows` gets one row per listed file: an uploaded file gets `{name, id: null, status: null, result: "checking…", job: null, sent: <its index in seeds>}`, and a failed upload gets `{name, id: null, status: null, result: "upload failed: <reason>", job: null, sent: -1}`.
  5. It shows `part(box, "confirm")`, empties `part(box, "shared")` when `box.shared`, sets `part(box, "summary")` = `checking N seeds…` (N = `seeds.length`), disables `part(box, "queue")`, renders the table, and posts the body to `box.endpoint`. If `box.body !== body` when the answer arrives, the answer is dropped.
  6. On 200: rows with `sent >= 0` are filled from `d = data.seeds[row.sent]`: `id = d[box.idKey]`, `status = d.status`, and `result` = `OK` for status `ok`, else `d.reason`. When `box.shared`, `part(box, "shared")` is filled like `showChecks` (`<status> <id> <name>: <detail>` per record), or with one `<li>` reading `shared checks not run: no seed passed its field checks` when the list is empty. The summary reads `shared checks failed: nothing can be queued` when `box.shared` and any shared record failed, else `K of M seeds can be queued` (K = ok rows, M = all listed files). `part(box, "queue")` reads `Queue K jobs` (`Queue 1 job` when K = 1 **[spec choice]**) and is enabled only when K > 0.
  7. On any other status, the summary = `data.error`, or `http <status>` when there is no error text, and every `checking…` result becomes `—`.
- **SD32. Table.** `renderFolderTable(box)` fills `part(box, "table")`'s `tbody`, one `<tr>` per `box.rows` entry, with cells `name`, `id || "—"`, `result` and `job || ""`, all set as text. No new CSS.
- **SD33. Queue and Cancel.**
  - **Queue.** `queueFolder(box)` takes the rows with `sent >= 0` and `status === "ok"`, in table order. It posts `Object.assign({}, box.body, {seeds: <box.body.seeds[row.sent] for those rows>, preview: false})` to `box.endpoint`. While the request runs, `box.busy = true`, the Queue and Cancel buttons are disabled, and the summary reads `checking and queueing N seeds…`. On 201 or 409, the i-th sent row is updated from `data.seeds[i]` (`id`, `status`, `result` as in SD31, `job` = `job.id` or `""`), and `box.body = null` (Queue stays disabled).
    - On 201: the summary reads `queued Q jobs` (`queued 1 job` when Q = 1). Then `selectJob(<first job id>)`, `await pollJobs()` and `showTab("jobs")`, for both boxes **[spec choice: one behaviour for both tabs]**.
    - On 409: the summary reads `nothing was queued`.
    - On any other status: the summary shows the error as in SD31 step 7, and Queue is enabled again.
    - Afterwards `box.busy = false`, and Cancel is enabled again.
  - **Cancel.** `closeFolderConfirm(box)` hides `part(box, "confirm")`, empties the shared list (when `box.shared`), the summary and the table body, and sets `box.body = box.rows = null`. It sends nothing. It does nothing while `box.busy` is true.
- **SD34. Jobs tag.** `seedTag(job)` returns `el("span", {cls: "badge", text: "seed folder " + sf.run + " · " + sf.name})` for `sf = job.seed_folder`, or `null`. The "Story / character" cell of each `#j-queue` and `#j-history` row becomes `el("td", {}, tag ? [jobLabel(job), " ", tag] : [jobLabel(job)])`. After `#j-running`'s text is set, the tag, when present, is appended after a space. The `·` is U+00B7.
- **SD35. Unchanged.** The Size and Seed image options, `onSeedFile`, `fillCompose` (selecting another radio unchecks Seed folder, and `updateComposeButtons` then leaves folder mode), the rest of Compose, and the Batches page. Every new identifier passes the `test_mut24` patterns (no `confirm(`, no `on…=`, no `style=`).

### 4.1 Characters folder mode (SD47-SD50)

- **SD47. HTML.** In the Characters form (`index.html:210-219`):
  - `<label>Name <input id="ch-name" type="text" size="24"></label>` becomes `<label><span id="ch-name-label">Name</span> <input id="ch-name" type="text" size="24"></label>`.
  - Directly after the Seed image label (`:217`):
    ```html
        <label><input id="ch-folder-mode" type="checkbox"> Seed folder (one character per image)
          <button id="ch-folder-choose" type="button">Choose folder…</button>
          <input id="ch-folder-file" type="file" webkitdirectory hidden></label>
        <span id="ch-folder-status" class="muted"></span>
        <ul id="ch-folder-list" class="muted" hidden></ul>
    ```
  - Directly after the `ch-create` row (`:219`):
    ```html
      <div id="ch-folder-confirm" hidden>
        <h3>Seed folder</h3>
        <p id="ch-folder-summary" class="muted"></p>
        <table id="ch-folder-table" class="list"><thead><tr><th>File</th><th>Character</th><th>Result</th><th>Job</th></tr></thead><tbody></tbody></table>
        <div class="row">
          <button id="ch-folder-queue" type="button" disabled>Queue 0 jobs</button>
          <button id="ch-folder-cancel" type="button">Cancel</button>
        </div>
      </div>
    ```
  - **[spec choice]** A checkbox, because the Characters form has no radio group to extend. There is no `ch-folder-shared` element (`shared: false`).
- **SD48. Folder mode.** With `box = FOLDER_BOXES.characters`, `updateCharacterButtons()` keeps its current statements, then:
  - `#ch-name-label` = `Name prefix (optional)` when `box.mode()`, else `Name`.
  - `#ch-class`, `#ch-descriptor`, `#ch-trigger` and `#ch-seed-file` get `disabled = box.mode()`. `#ch-phrase` and `#ch-seed` stay enabled.
  - It calls `renderFolderList(box)`.
  - Outside folder mode it calls `closeFolderConfirm(box)` and stops. `box.folder` is kept.
  - In folder mode, a `folderBlock(box)` text (SD29) disables `#ch-create` and is added to `#ch-create-status` (after `; ` when it already has text).

  `setupCharacters` adds `$("#ch-folder-mode").addEventListener("change", updateCharacterButtons)` and the SD27 listeners. Picking a folder ticks the box (`box.select()`).
- **SD49. Create.** `createCharacter(force)` begins with `if (!force && FOLDER_BOXES.characters.mode()) { openFolderConfirm(FOLDER_BOXES.characters, {ws: S.ws, name: $("#ch-name").value.trim(), phrase: $("#ch-phrase").value.trim(), seed: numberOrNull("#ch-seed")}); return; }`. The rest of the function, including the force path, is unchanged. Table, Queue and Cancel are SD31-SD33 with this box.
- **SD50. Shared and unchanged.**
  - Shared with Compose: `FOLDER_BOXES`, `part`, `onFolderPick`, the upload loop, `renderFolderList`, `uploadedSeeds`, `folderBlock`, `openFolderConfirm`, `renderFolderTable`, `queueFolder` and `closeFolderConfirm` (SD27-SD33), `SEEDS_MAX`, `SEED_TYPES`, `SEED_COLLATOR`, `seedTag` (SD34), and on the server `first_free`, `_seeds_and_preview`, `new_run_id`, `seed_tag` and the SD21 shape.
  - Characters-only: `character_stem`, `valid_character_prefix`, `character_name_for`, `assign_character_names`, `character_taken_names`, `validate_character_request`, `character_taken`, `_h_character_seed_folder`, `_character_job_locked`, `_phrase_errors` and `_seed_number_errors`.
  - The Jobs tag (SD34) appears on `character-create` rows unchanged.
  - Unchanged: the character list, detail, Accept, Regenerate, Train and "Create anyway (--force)", and single-image Create outside folder mode.

---

## 5. Errors

| Condition | Where | Text | Effect |
|---|---|---|---|
| no or bad token | route | `missing or invalid token` | 401 |
| malformed request | route | the SD13 table | 400, nothing run |
| a file the browser skips (subfolder, other type, leading dot) | page | not listed | — |
| 0 images | page | `no PNG, JPEG or WebP images directly in this folder` | no list |
| more than 100 images | page | `found N images; at most 100 per run — pick a smaller folder` | pick refused |
| upload refused (over 20 MiB, wrong content, other) | page row | `upload failed: <reason>` (`image is larger than 20 MiB`, `upload larger than 20 MiB`, `file content is not image/jpeg`, …) | never sent to the server |
| `upload_id` not a non-empty string | row (both endpoints) | `seed image upload missing` | refused |
| unknown or malformed `upload_id` | row (both endpoints) | `seed image upload <id> not found` | refused |
| any other V1 failure | row | the V1 lines joined by `; ` | refused |
| a shared check fails | every V1-passing row | `skipped: shared checks failed` | skipped; nothing queueable |
| dry run timed out | row | `dry run timed out after 60 s` | refused |
| dry run failed (unreadable or too-small image, …) | row | `dry run failed: <last output line>` | refused |
| dry-run worker raised | row | `dry run failed: dry run error: <type>: <message>` | refused |
| nothing queueable on Queue | route | SD21 body | 409 |
| same image twice | rows | the same `upload_id`, separate IDs and jobs | both queued |
| server stops mid-queue | jobs | earlier jobs whole and queued (SD25) | no half-written job |
| Characters: malformed request | `/api/characters/seed-folder` | the SD43 table | 400, nothing run |
| Characters: nothing queueable on Queue | `/api/characters/seed-folder` | SD46 body | 409 |
| Characters: a seed's face missing or too small | the job, at run time | `bin/character`'s face message in the job log | job `failed`; no character directory; the name stays free |
| Characters: two folder characters cast in one story | `bin/ltx-movie` casting | `cast phrase … is used for both … and …` (`character_lib.py:586-588`) | casting refused (R5) |

---

## 6. Tests

Rules:
- New file `tests/test_movie_ui_seedfolder.py`. Its docstring states the rules below and the run command `python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_seedfolder.py`.
- The HTTP tests use an `env` fixture like `tests/test_movie_ui_seams.py:41-48`: `mt.set_home`, `mt.make_stub_workspace` and the in-test `mt.Running` server on 127.0.0.1. Uploads go through `POST /api/uploads` with `mt.PNG + bytes([i])` (distinct IDs) or `mt.PNG` (the same ID).
- `lib.shared_checks` is monkeypatched to `lambda fields, ws_real, py=None: [lib.check("V2", "render", "pass", "stub")]` in every HTTP test except where a test patches it otherwise. V1 runs for real (stub workspace, current help fixture). V6 runs the stub `ltx-movie --dry-run` (exit 0) unless the test monkeypatches `lib.dry_run_check`.
- The Characters tests (SDT26-SDT37) use the same file and fixture, `monkeypatch.delenv("CHARACTER_LIBRARY_DIR", raising=False)` unless a test sets it, and the stub `bin/character` (never run, because no test dispatches a job).
- No test uses the real HOME, renders, or contacts a real server. None touches port 8177 or 8178. The VLM lifecycle is off (`conftest.py`). No test ever starts a job.

| ID | Covers | Test |
|---|---|---|
| SDT1 | SD5, SD7, SD8, SD10 | §2.3's 17 rows, parametrised, exact |
| SDT2 | SD5 | `seed_stem`: `""` → `seed`, `"..."` → `seed`, `"-_-.png"` → `seed`, `"a\tb.png"` → `a-b`, `"x.tar.gz"` → `x.tar` |
| SDT3 | SD6, SD7 | `valid_prefix`: `""` yes; `"temple"` yes; 40 characters yes; 41 no; `"-x"`, `"a..b"`, `"a/b"`, `5` no. A 120-character stem with no prefix → exactly 80 characters |
| SDT4 | SD7, SD9 | case: `taken_names(["BEACH"], [])` with `beach.png` → `beach-2`; `BEACH.png` with taken `{beach}` → `BEACH-2` |
| SDT5 | SD9 | under `tmp_path/generated/stories`, a directory `d1`, a file `f1`, a dangling symlink `l1` and a symlink to a directory `l2`; `taken_names(os.listdir(...), {"Busy": "j", None: "k"})` == `{d1, f1, l1, l2, busy, movie-ui-smoke}` |
| SDT6 | SD7, SD8 | `assign_story_ids` leaves its `taken` argument unchanged; `story_id_for` with row 17's set returns `x-1000`; `first_free("", "ab", {"ab"}, 4, "-")` == `"ab-2"` and `first_free("p-", "abcdef", set(), 6, "-")` == `"p-abcd"` |
| SDT7 | SD5-SD8 | random property check (`random.Random(20261101)`, 3000 cases; names of 0-120 characters drawn from ASCII letters, digits, `" ._-!/\t"`, `é`, `日`, `ß`, `ﬁ`; prefix `""` or a valid prefix of 1-40 characters; taken a random set of earlier outputs): every ID passes `lib.valid_story_id`, has no `..`, has at most 80 characters, is not in `taken` case-folded, starts with `prefix + "-"` when there is a prefix; the IDs of one call are distinct case-folded |
| SDT8 | SD12, SD13 | `validate_request`: every SD13 row 2-7 message, exact; first-failure order (bad action and bad seeds → the action message); accepted: prefix absent, `null` or `""` → `""`; exactly 100 items; `check_seams` `"yes"` → `False`; `upload_id` absent → `None` |
| SDT9 | SD1, SD18, SD22, SD23 | the module's import lines name exactly `re`, `secrets`, `time`, `unicodedata` and `movie_ui_lib`; `row_reason` for each SD18 row (timeout detail built from `lib.DRY_RUN_TIMEOUT`; a two-line failure detail gives its last line; an empty detail gives `dry run failed`); `new_run_id()` matches `RUN_ID_RE`; `seed_tag` on a good dict, `None`, a non-dict, and a missing or non-string `run` or `name` |
| SDT10 | SD2 | with `host_checks`, `model_checks`, `lora_checks`, `compat_checks` and `dry_run_check` monkeypatched to return one tagged record each, `run_checks(<valid fields>)` == `[V1 pass, h, m, l, c, d]` and `shared_checks` == `[h, m, l, c]`; with a V1 failure, `run_checks` is unchanged (V1 fail plus 5 skips) |
| SDT11 | SD11 | the route is in `ROUTES` right after `POST /api/jobs`; `len(srv.ROUTES) == 57` (with SD41); 401 without or with a wrong token; `GET /api/jobs/seed-folder` → 405 |
| SDT12 | SD13 | over HTTP: each 400 of SD13 (bad `ws`, then rows 2-7) with its exact `error`; afterwards no job directory exists and `queue.json` is unchanged |
| SDT13 | SD14, SD19, SD21 | preview of 3 seeds → 200; `ok` true, `queued` 0, `run` null, `refused` 0; `seeds` in request order with provisional IDs, `checks` ids `["V1", "V6"]`, `job` null; afterwards there are no job directories, `queue.json` is unchanged, and `generated/stories` is still empty |
| SDT14 | SD14, SD15, SD20, SD21 | queue with action `story`, prefix `temple`, and seeds sent as `Beach Day!.webp`, `shot2.png`, `shot10.png` → 201, `queued` 3; `queue.json` holds the three job IDs in that order; each `job.json` has kind `story`, `story_id` `temple-Beach-Day` / `temple-shot2` / `temple-shot10`, and argv with `--story-id <id>`, `--seed-image <STATE>/uploads/<upload_id>` and `--story-only`; `fields.seed_upload` is the upload ID and `width`/`height` are null; each row's `job.id` equals its job; the stub recorded 3 `--dry-run` calls whose argv carry the matching `--seed-image` |
| SDT15 | SD15, SD18, SD20 | 6 seeds: an unknown well-formed `upload_id` → refused `seed image upload <id> not found`; `upload_id` 7 and `upload_id` `""` → refused `seed image upload missing`; `lib.dry_run_check` patched to fail one story with detail `"plan\nError: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)\n"` → refused `dry run failed: Error: --seed-image is degenerate: 8x8 (each edge must be at least 64 px)`, and another with the timeout detail → refused `dry run timed out after 60 s`; the sixth is queued → 201, `queued` 1, `refused` 5, one job |
| SDT16 | SD16, SD20, SD21 | `lib.shared_checks` patched to return a `fail` record: preview → 200, `ok` false, every row `skipped` with `skipped: shared checks failed`, `shared_checks` == the patched list; queue → 409 with the same shape, `run` null, nothing created; a patched `lib.dry_run_check` was never called |
| SDT17 | SD15, SD16, SD20 | mode `shots`, action `movie`: every row refused with `a seed image cannot be used with shots mode`, `shared_checks` == `[]`, and a patched `shared_checks` was never called; queue → 409, no job |
| SDT18 | SD20 | action `movie`, mode `chained`, `check_seams` true, 2 seeds → `queue.json` == `[m1, s1, m2, s2]` with each seams job's `fields.after` naming its movie; `check_seams` false → `[m1, m2]`; action `story` with `check_seams` true → no seams job |
| SDT19 | SD20, SD23, SD24 | after SDT14's queue: every `job.json` has `fields.seed_folder == {"run": <response run>, "name": <its name>}` with one shared `run` matching `RUN_ID_RE`; `GET /api/jobs` queued summaries carry the same `seed_folder`; a job made with `mt.make_job` has `seed_folder: null`; `lib.compose_fields(job fields)` has no `seed_folder` key and equals `lib.compose_fields(<job fields without seed_folder>)` |
| SDT20 | SD9, SD14, SD20 | (a) preview gives `beach`, then `os.makedirs(<ws>/generated/stories/beach)`, then queue → story `beach-2`; (b) `lib.dry_run_check` patched to create `<ws>/generated/stories/Beach` during the queue's step 4 and pass → the patched call saw `fields["story_id"] == "beach"`, and the job's story is `beach-2`; (c) `mt.make_job(..., story_id="BEACH")` (queued) → `beach-2`, and `mt.make_job(..., story_id="shore", status={"state": "running", "dispatched": lib.utc_now()})` with `shore.png` → `shore-2` |
| SDT21 | SD17 | 10 seeds, `lib.dry_run_check` patched to count running calls under a lock, sleep 0.3 s and pass: the maximum concurrent count is exactly 4, all 10 ran, and inside the call another thread acquires `srv.STORE_LOCK` and `srv.BATCH_LOCK` within 1 s |
| SDT22 | SD8, SD20 | two seeds `a.png`, `a.png` with the same `upload_id` → stories `a` and `a-2`, two jobs, both argv with the same `--seed-image` |
| SDT23 | SD25 | `lib.create_job` wrapped to raise `OSError` on its 2nd call, 3 ok seeds → 500 `{"error": "internal error"}`; the 1st job's `job.json` is readable and its ID is the only one in `queue.json`; `srv.STORE_LOCK.acquire(timeout=1)` succeeds afterwards |
| SDT24 | SD24 | `POST /api/jobs` with a valid single-seed body plus `"seeds": [...]` and `"seed_folder": {...}` → 201, and the job's `fields` have neither key; `/api/validate` on that body equals `/api/validate` on the body without them |
| SDT25 | SD26-SD35, SD50 | static page: each new ID (`c-story-id-label`, `c-res-folder`, `c-folder-choose`, `c-folder-file`, `c-folder-status`, `c-folder-list`, `c-folder-confirm`, `c-folder-shared`, `c-folder-summary`, `c-folder-table`, `c-folder-queue`, `c-folder-cancel`) appears in `index.html` exactly once; `c-story-id-label` and `c-res-folder` appear as `"#<id>` in `app.js` (the `c-folder-*` elements are reached through `part`), and `"c-folder"` and `"ch-folder"` appear as box `ids`; `webkitdirectory` and `<th>File</th><th>Story ID</th><th>Result</th><th>Job</th>` are in the HTML; these strings are in `app.js`: `"/api/jobs/seed-folder"`, `new Intl.Collator("en", {numeric: true})`, `function sampleStoryId(name, prefix)`, `"Story ID prefix (optional)"`, `"not available for a seed folder"`, `"upload failed: "`, `"seed folder "`, `" · "`, `"Queue "`, `const FOLDER_BOXES = {`, `function part(box, name)`; each of `onFolderPick`, `openFolderConfirm`, `queueFolder`, `closeFolderConfirm`, `renderFolderTable`, `renderFolderList` is defined exactly once, as `function <name>(box` (one shared copy); the `test_mut24` forbidden patterns are absent; `node --check app.js` passes when `node` exists |
| SDT26 | SD36, SD38, SD40 | §2.4's 13 rows, parametrised, exact |
| SDT27 | SD36-SD38 | `valid_character_prefix`: `""` yes; `"temple"` yes; 12 characters yes; 13 no; `"a"`, `"1ab"`, `"Ab"`, `"a_b"`, `5` no. Random property check (`random.Random(20261102)`, 3000 cases; SDT7's name alphabet plus upper case; prefix `""` or a valid prefix of 2-12 characters; taken a random set of earlier outputs): every name matches `lib.CHARACTER_NAME_RE`, is not in `taken`, starts with `prefix + "-"` when there is a prefix, and the names of one call are distinct |
| SDT28 | SD39 | `character_taken_names(["Kyra", ".triggers"], ["Zed", None])` == `{kyra, .triggers, zed}`; `character_taken` with `CHARACTER_LIBRARY_DIR` unset reads `<ws>/generated/characters` (a directory `kyra`, a file `nova`, a dangling symlink `ghost`) and with it set to `tmp_path/lib` reads that directory instead; busy (jobs made with `lib.create_job(state, lib.new_job_id(state), <kind>, <ws>, None, <name>, ["true"], {})`, plus `lib.write_status` for the running and done ones, with the job removed from the queue as `mt.make_job` does): a queued `character-create` job for `zed` and a running `character-train` job for `yon` are taken, a `done` job for `old` is not, and a queued job of another workspace is not |
| SDT29 | SD41 | the route is in `ROUTES` right after `POST /api/characters`; `len(srv.ROUTES) == 57`; 401 without or with a wrong token; `GET /api/characters/seed-folder?ws=<ws>` reaches `h_character` (the stub `character show` prints nothing, so the answer is 502 `character printed unparsable output`, not 405) |
| SDT30 | SD43 | over HTTP: each 400 of SD43 (bad `ws`; empty phrase; seed `-1`; prefix `Temple`, 13-character prefix; then SD13 rows 4-7) with its exact `error`; order: an empty phrase with bad `seeds` gives the phrase message; afterwards no job exists |
| SDT31 | SD44, SD46 | preview of 3 seeds → 200: `ok` true, `queued` 0, `run` null, `shared_checks` `[]`; rows have `character` and no `story_id`, `checks` ids `["V1"]`, `job` null; no job directory, `queue.json` unchanged, no character library directory created |
| SDT32 | SD42, SD44, SD45 | queue with no prefix, phrase `the stranger`, seed 7, seeds sent as `Kyra.png`, `Old Man #2.webp`, `01_hero.png`, and the body also carrying `class_noun` `woman`, `descriptor` `x`, `trigger` `kyrax`, `force` true → 201, `queued` 3; `queue.json` holds the 3 jobs in that order; each `job.json` has kind `character-create`, `story_id` null and `character` `kyra` / `old-man-2` / `hero`; its `fields` keys are exactly `name, phrase, class_noun, descriptor, trigger, seed, seed_upload, force, ws, seed_folder`, with `class_noun`, `descriptor`, `trigger` null and `force` false; its argv equals `lib.character_argv("character-create", fields, ws, state)` and contains `--phrase the stranger`, `--seed-image <STATE>/uploads/<id>`, `--seed 7` and no `--class`, `--descriptor`, `--trigger` or `--force` |
| SDT33 | SD44, SD46 | an unknown well-formed `upload_id` → refused `seed image upload <id> not found`; `upload_id` `""` and 7 → refused `seed image upload missing`; with one good seed → 201, `refused` 3; with only the bad ones → 409, `run` null, no job |
| SDT34 | SD39, SD44 | (a) preview gives `kyra`, then `os.makedirs(<ws>/generated/characters/kyra)`, then queue → `kyra-2`; (b) a queued `character-create` job for `nova` (made with `lib.create_job` as in SDT28) → `nova.png` gives `nova-2`; (c) two seeds `kyra.png` with the same `upload_id` → `kyra`, `kyra-2`, two jobs |
| SDT35 | SD23, SD46 | after SDT32's queue: every `job.json` has `fields.seed_folder == {"run": <run>, "name": <file name>}` with one shared `run`; `GET /api/jobs` queued summaries carry it, and their `character` is the name |
| SDT36 | SD43, SD45, SD46 | regressions: `POST /api/characters` with `{"ws": <ws>, "name": "kyra", "phrase": "", "seed": -1, "descriptor": "a tall man", "class_noun": "man"}` answers 400 `invalid fields` with `errors` == `["phrase is required", "seed must be an integer from 0 to 2147483647"]`; the same body with phrase `the stranger` and seed 7 answers 201 with one `character-create` job; posting a seed-folder job's `fields` plus `force: true` to `POST /api/characters` → 201, and the new job's `fields` have no `seed_folder` and `force` true |
| SDT37 | SD47-SD50 | static page: each Characters ID (`ch-name-label`, `ch-folder-mode`, `ch-folder-choose`, `ch-folder-file`, `ch-folder-status`, `ch-folder-list`, `ch-folder-confirm`, `ch-folder-summary`, `ch-folder-table`, `ch-folder-queue`, `ch-folder-cancel`) appears in `index.html` exactly once; `ch-folder-mode` and `ch-name-label` appear as `"#<id>` in `app.js` (the rest are reached through `part`); `ch-folder-shared` does not appear; `<th>File</th><th>Character</th><th>Result</th><th>Job</th>` is in the HTML; `"/api/characters/seed-folder"`, `"Name prefix (optional)"` and `"Seed folder (one character per image)"` are in `index.html` + `app.js` |

### 6.1 Existing tests to change (one test-only commit, after the feature commit)

| Test | Exact edit |
|---|---|
| `tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token` (`:44`) | 2 new routes (SD11, SD41): `== 55` becomes `== 57` |
| `tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token` (`:66`) | `== 55` becomes `== 57` |
| `tests/test_movie_ui_http.py::test_mut2_preview_argv_is_the_job_argv` (`:342-344`) | the key set gains `"seed_folder"` |
| `tests/test_movie_ui_builder.py` `NEW_PY` (`:213-216`) | append `"movie_ui_seedfolder.py"` and `"tests/test_movie_ui_seedfolder.py"` |
| `tests/test_movie_ui_builder.py::test_mut25_source_scan_of_new_python_files` (`:258-260`) | the `allowed` set gains `"movie_ui_seedfolder"` |
| `tests/movie_ui_testutil.py::copy_ui` (`:464-465`) | the copied list gains `"movie_ui_seedfolder.py"` (`test_mut15` starts a copied `bin/movie-ui`) |

No other existing test pins the Characters form, `character_create_errors` or `create_character_job` (checked with grep at `e94ebb0`); SDT36 guards their behaviour.

Because of `NEW_PY`, the new module and test file must contain none of `test_mut25`'s patterns anywhere, docstrings and comments included: no `urllib`, no `X | None` text, and no line that starts with `match ` and ends with `:`.

### 6.2 Browser check (before the merge; not pytest)

A throwaway demo server, written under `$S/sfdemo/` and never committed:
- `demo.py` first sets `HOME=$S/sfdemo/home`, `MOVIE_UI_VLM_LIFECYCLE=0`, `MOVIE_UI_VLM_TOOLS=$S/sfdemo/no-tools` and `MOVIE_UI_VLM_PORT=9`, then imports `tests/movie_ui_testutil` and `movie_ui_server`.
- It builds `ws = mt.make_stub_workspace("$S/sfdemo")` and sets `lib.shared_checks` to the §6 pass stub.
- It calls `srv.make_server(0, state, ws, <random token>)` (an OS-chosen port, never 8177, 8178 or 8999), sets all three `server.capabilities` to `{"ok": True, "reason": None, "checked": lib.utc_now()}`, prints the URL with its token and runs `serve_forever()`.
- It never calls `start_threads`, so there is no dispatcher, no probe, and no job ever runs.

Folders:
- `$S/sfdemo/seeds/` holds `shot10.png`, `shot2.png`, `Beach Day!.webp` (magic bytes only), `bad.jpg` (PNG bytes), `.hidden.png`, `notes.txt` and `sub/inner.png`.
- `$S/sfdemo/seeds101/` holds 101 PNGs.

Pass when all of these hold in a browser:
1. Picking `seeds101` shows `found 101 images; at most 100 per run — pick a smaller folder`.
2. Picking `seeds` lists exactly `bad.jpg`, `Beach Day!.webp`, `shot2.png`, `shot10.png`, in that order. `bad.jpg` is marked `upload failed: file content is not image/jpeg`, and the status ends `uploaded 3 of 4 images (1 failed)`.
3. The label reads `Story ID prefix (optional)`. Smoke render is disabled with `not available for a seed folder`. Validate is disabled.
4. With prefix `demo`, the command shows `--story-id demo-Beach-Day` and the `Beach Day!.webp` upload path.
5. Write story opens the table with the rows `bad.jpg | — | upload failed: file content is not image/jpeg`, `Beach Day!.webp | demo-Beach-Day | OK`, `shot2.png | demo-shot2 | OK` and `shot10.png | demo-shot10 | OK`. The shared check `pass V2 render: stub` is shown, and the button reads `Queue 3 jobs`.
6. Queue fills the Job column, switches to Jobs, and shows 3 queued story jobs in that order, each tagged `seed folder sf-… · <file name>`.
7. Cancel on a fresh table hides it and creates nothing.
8. Choosing Size again restores `Story ID` and the normal buttons.
9. On the Characters tab, picking `seeds` ticks `Seed folder (one character per image)` and gives the same list and status as step 2. The label reads `Name prefix (optional)`, and Class noun, Descriptor, Trigger and Seed image are disabled.
10. With prefix `demo` and phrase `the stranger`, Create opens the table with the rows `bad.jpg | — | upload failed: file content is not image/jpeg`, `Beach Day!.webp | demo-beach-day | OK`, `shot2.png | demo-shot2 | OK` and `shot10.png | demo-shot10 | OK`, no shared-check list, and `Queue 3 jobs`.
11. Queue switches to Jobs and shows 3 queued `character-create` jobs (`demo-beach-day`, `demo-shot2`, `demo-shot10`, in that order), each tagged `seed folder sf-… · <file name>`.
12. Unticking the box restores `Name`, re-enables the four inputs and hides the table. The Compose folder list from step 2 is still there (each box keeps its own state).

### 6.3 Live checks (after the feature commit)

Done by the coordinator on this Mac's movie-ui, never on macstudio, with no render. Pick a real folder of 3 PNG or JPEG images (each edge at least 64 px) through Compose → Seed folder, then use Write story. Pass when exactly 3 story jobs are queued, in file-name order, with the IDs the confirm table predicted, each argv carrying its seed's `--seed-image`. Rendering happens only on the user's go.

**Characters live check** (SD44): it starts GPU work (the dataset edit), so the coordinator runs it only after the user's explicit go. Use a real folder of 2 face images (each face at least 15% of the image height) through Characters → Seed folder → Create → Queue. Pass when exactly 2 `character-create` jobs are queued, in file-name order, with the names the table predicted, each argv carrying its seed's `--seed-image` and the shared `--phrase`. Without the go, record it as "not run (awaiting the user's go)" in the merge report.

---

## 7. Pass bar

1. Every new test (SDT1-SDT37) passes.
2. `python3 -m pytest tests/ -q -rA` from `WS` has no new failures beyond the 2 known baseline failures: `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`.
3. `python3 tests/test_ltx_movie_offline.py` prints `OK 347/347`.
4. The Compose live check (§6.3) passes.
5. The Characters live check (§6.3) passes when the user gives the go. Without the go it is recorded as not run, and that does not block the merge.

The browser check (§6.2) is part of the testing, run before the merge (§8 step 5).

## 8. Rollout

1. Snapshot `WS` (house rule): `tar czf $S/snapshot-pre-seedfolder-e94ebb0.tgz`, excluding `generated/`.
2. At `e94ebb0`, record the full-suite counts and failure list, and the offline line.
3. Feature commit: G1-G4 plus `tests/test_movie_ui_seedfolder.py`.
4. Test-only commit: §6.1.
5. Run §7 items 1-3 and the browser check (steps 1-12), then an Opus design review of the diff against this spec, then the Compose live check, then the Characters live check if the user gives the go.

## 9. Risks

- **R1 Long requests.** Each dry run may take up to 60 s. 100 seeds at 4 at a time can hold a request for up to 25 minutes in the worst case, and Queue repeats the dry runs. The page shows `checking N seeds…` until the answer arrives. A typical dry run takes seconds.
- **R2 Moving IDs.** The provisional ID shown in the table can change at Queue time (SD20). The table then shows the final ID.
- **R3 One shared check.** V2-V5 run on the first V1-passing seed only. Their story-ID dependence (`story_needed`) is the same for every new ID, so the result holds for all seeds.
- **R4 Story-server cost.** Every seed job needs the VLM (a new story), which `job_vlm` already handles per job.
- **R5 Shared phrase.** Every character of a folder run has the same referring phrase (user decision). Casting two of them into one story is refused (`cast phrase … is used for both …`, `character_lib.py:586-588`). Each one can be cast alone, or its phrase changed later in its `character.json`.
- **R6 GPU queue length.** Each `character-create` job edits a dataset on the GPU, so a 100-seed Characters run is a long queue. Jobs still run one at a time.
- **R7 Face refusals at run time.** The face check runs inside the job, not at preview. A refused seed fails its job, and the rest of the queue continues.

## 10. Decisions made in the spec

1. **Module:** a new `movie_ui_seedfolder.py` (pure, like `movie_ui_batch.py`) holds the ID rules, request validation, reasons, run ID and tag (SD1).
2. **Check reuse:** `lib.shared_checks` is extracted from `run_checks`, which keeps the same records in the same order, so `/api/validate` and `/api/jobs` are unchanged (SD2).
3. **Lock-free create path:** `_compose_job_locked` is split out of `create_compose_job`, because `STORE_LOCK` is not reentrant and a run makes many jobs in one hold (SD3).
4. **Stem:** only a `.` at index > 0 starts an extension, so `.png` becomes `png` and not an empty stem (SD5).
5. **Truncation:** room is computed per candidate, so an unsuffixed ID keeps its full stem (SD7).
6. **Loop bound:** `k < 12·(|taken|+1) + 10`, which is proven sufficient; the `AssertionError` after it is unreachable (SD7).
7. **Taken set:** one lower-cased `os.listdir` (case-insensitive lexists on any file system) plus `job_index`'s busy IDs (SD9).
8. **Reserved ID:** `movie-ui-smoke` counts as taken, so it gets a suffix instead of a V1 refusal (SD9).
9. **Final IDs:** only ok rows draw final IDs at Queue, so refused seeds do not push later seeds to suffixes (SD20).
10. **Missing upload:** an `upload_id` that is not a non-empty string makes the row refused with `seed image upload missing`, because V1 lets a null seed through (SD15).
11. **Prefix:** `story_id` absent, null or `""` means no prefix (SD12).
12. **`preview` required:** a body without a boolean `preview` gets a 400 and never queues. `check_seams` uses `is True`, like `/api/jobs` (SD12, SD13).
13. **400 shape:** the first failing rule only, as a single `error`, matching the other Compose routes (SD13).
14. **Response:** per-seed rows sit under `seeds`. `run` is null for a preview or a 409. `queued` counts story or movie jobs, not seams jobs. A 409 has the same body with no `error` key (SD21).
15. **Reasons:** V1 lines joined by `; `; `dry run timed out after 60 s`; `dry run failed: <last line>`; `skipped: shared checks failed`. `checks` is always `[V1, V6]`, with skip records (SD17, SD18).
16. **Dry-run pool:** 4 plain `threading.Thread` workers, with no new server import. A raising worker gives a V6 fail (SD17).
17. **Run ID:** `sf-` + UTC `%Y%m%d-%H%M%S` + `-` + 4 hex digits, with no uniqueness loop, because nothing stores runs (SD22).
18. **Tag transport:** `job_summary` gains `seed_folder`. Seams jobs behind seed-folder movies are not tagged (SD20, SD23).
19. **Folder control:** a hidden `webkitdirectory` input behind a `Choose folder…` button (SD26).
20. **Natural sort:** `Intl.Collator("en", {numeric: true})` (SD27).
21. **Command preview:** uses the first uploaded seed and a client-side `sampleStoryId` (rules 1-6, no suffix) (SD30).
22. **Validate:** disabled in folder mode (SD29).
23. **Frozen confirm body:** Queue sends the body frozen when the table opened, with only the OK seeds and `preview: false` (SD31, SD33).
24. **Button text:** `Queue 1 job` and `queued 1 job` in the singular (SD31, SD33).
25. **Folder-mode buttons:** Run all and Write story are disabled while uploading or with no seed uploaded, with a reason. Leaving folder mode closes the table and keeps the list (SD29).
26. **Name length:** names have no length cap; the notes' 400 list is complete (SD13).
27. **Shared candidate loop:** `first_free(head, stem, taken, limit, trim)` serves story IDs (80, trim `-._`) and character names (24, trim `-`) (SD7, SD38).
28. **Character stem:** rules 1-5 as in the addendum. A one-letter stem becomes `<letter>-char`, and an empty one `char` (SD36).
29. **Character prefix:** must match `CHARACTER_NAME_RE` and be at most 12 characters, leaving 11 for the image's part and a suffix (SD37).
30. **Character taken set:** a lower-cased listing of `$CHARACTER_LIBRARY_DIR` or `<ws>/generated/characters`, the directory `bin/character` uses, with no subprocess, plus every queued, starting or running job of the workspace that names a character (any character kind) (SD39).
31. **Ignored form fields:** `class_noun`, `descriptor` and `trigger` are forced to null and `force` to false, not refused. The tool derives a unique trigger and the vision model a class noun per image (SD42).
32. **No force:** `--force` bypasses the face check and is not an overwrite switch, so folder mode never sends it. A face-refused seed fails its job and leaves its name free (SD42).
33. **Character 400 order:** `ws`, phrase, seed, prefix, then the shared seeds/preview rules, each as a single `error`. `_phrase_errors` and `_seed_number_errors` are moved out of `character_create_errors` unchanged (SD43).
34. **Character checks:** per seed, only `character_create_errors` (the upload). `checks` is `[V1]`, and `shared_checks` stays in the response as `[]`, so both endpoints share one shape and one renderer (SD44, SD46).
35. **Lock-free character create:** `_character_job_locked` is split out of `create_character_job` (SD45).
36. **Characters toggle:** a `Seed folder (one character per image)` checkbox, since the form has no radio group. Name becomes `Name prefix (optional)`, and class noun, descriptor, trigger and seed image are disabled (SD47, SD48).
37. **One JS copy:** the picker, upload loop, confirm table, Queue and Cancel are box-parameterised functions (`FOLDER_BOXES`), each with its own state. After a Characters queue the page switches to Jobs, as Compose does (SD27-SD33, SD50).
38. **Characters live check:** it runs only on the user's go. Without it, it is recorded as not run and does not block the merge (§6.3, §7).
39. **Missing upload, both endpoints:** an empty-string `upload_id` also counts as missing (SD15, SD44).

## 11. Open questions

None. Every point the notes left open is decided in Section 10.
