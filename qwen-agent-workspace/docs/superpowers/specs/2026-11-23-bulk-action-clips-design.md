# Bulk action-LoRA clip loading: one motion LoRA from a whole folder of clips, each captioned from its file name

Date: 2026-11-23

Status: design spec with a task-level implementation plan outline (end of document).

Extends `docs/superpowers/specs/2026-10-20-action-lora-motion-library-design.md` (the action
spec). Its identity-agnostic rule (action spec 3.2: >= 3 performers or `--force`, captions free of
appearance) is kept unchanged.

**Where.** Worktree `$S/bk-wt`, branch `bulk-action-clips`, off `qwen-agent-redteam` at `b6bcb9b`
(Merge PR #31). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
`WS` is `qwen-agent-workspace/`. Every path is relative to `WS` and every line number was checked
at `b6bcb9b`. Nobody accesses macstudio. The live checks (Section 7) are the user's to run.

Choices this spec makes beyond the approved design are marked **[spec choice]**. The implementer
makes no design decisions: names, messages, and code shapes in Sections 2 and 3 are exact.

---

## 0. Purpose and scope

### 0.1 Purpose
The user has several hundred short fight clips. Each file name lists the moves in the clip, for
example `006_00_high_kick-stance-front_kick.mp4`. Today every clip has to go in as its own
`--clip PATH` (CLI) or as one line of the Clips textarea (UI, at most 64). This feature trains
**one** action LoRA on a **whole folder**. Each clip's caption comes from its file name. The
trigger stays the single phrase the planner puts into Motion:.

### 0.2 Grounding (shipped code, read this session)

**`action_dataset.py`**
- `CONTACT_COLS = 4` (:38). `CREATE_MIN_FREE_GIB = 2.0` (:39) is a fixed threshold that does not
  depend on how many clips there are.
- `probe_clip` (:87-98) returns `nb_frames` at the **source** fps (:95).
- `normalize_clip` (:101-110) runs `fps=24,scale=W:H:force_original_aspect_ratio=increase,crop=W:H`
  (:104-105): scale to fill, then a centre crop.
- `write_contact_sheet` (:121-135) makes one thumbnail per frame it is given, with no limit.
- `build_dataset` (:154-222):
  - it validates the name, trigger, descriptor and geometry (:160-163), then the clips are
    readable (:165-167), then the performers gate (:169-173);
  - it creates the directories, then runs the free-space check (:179-182);
  - per clip (:186-199) it writes `clips/clip_%02d.mp4` and `captions/clip_%02d.txt`, and the
    caption is always the trigger (:192);
  - it extracts one frame from **every** clip for the sheet (:193-198);
  - it writes `action.json` through `lib.new_action` (:209-214), then `manifest.json` (:216-221)
    with `sources` but no caption for each clip.
- `PREPROCESS_TIMEOUT_S = 1800` (:241) is fixed. `TRAIN_TIMEOUT_S = 14400` (:242).
- `train_action` (:359-429):
  - it counts `clips/*.mp4` with `glob` (:370) and refuses fewer than `MIN_CLIPS`;
  - it runs preprocess with the fixed 1800 s timeout (:399-400);
  - it requires latents == clips (:404-408).
- `create` (:451-480) does not pass `fps=args.fps` to `build_dataset` (:463-465). This bug
  predates this feature (finding F4).
- `build_parser` (:488-505): `--clip` is `action="append"`. `--trigger` and `--descriptor` are
  required.

**`action_lib.py`** (stdlib only)
- `TRIGGER_RE` (:32) has no `:`, so a `:` in a caption can only be the separator added in 2.2.
- `MIN_CLIPS = 8` (:40), `MIN_PERFORMERS = 3` (:41).
- `validate_trigger` (:88-94).
- `source` must be `{"type": "clips", "paths": [abs, ...]}` (:165-171).
- `new_action` (:185-206).

**`bin/action`**
- It has its **own** `build_parser` (:33-55), separate from `action_dataset.build_parser`.
- `list` and `show` import only `action_lib`. `create` and `train` import `action_dataset`
  (:86-101).

**`movie_ui_server.py`**
- It imports only stdlib, `movie_ui_lib`, `fleet_lib` and its sibling UI modules (:10-33). It
  never imports `action_lib`: it copies `TRIGGER_RE` (:2314, comment) and calls `bin/action` as a
  subprocess (:2340, :2346).
- Routes:
  - `ROUTES` (:74-) holds the four action routes (:100-103);
  - `_ACTION` (:67) means `GET /api/actions/<name>` also matches the literal `preview`, but only
    for GET;
  - six tests pin `len(srv.ROUTES) == 66` (finding F7).
- Clips:
  - `ACTION_CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")` (:2315);
  - `ACTION_MAX_CLIPS = 64` (:2316);
  - `_h_action` (:2344-2362) lists `clips/*.mp4` with a plain `sorted` (:2357), so `clip_100`
    sorts between `clip_10` and `clip_11`.
- `action_create_errors` (:2365-2393) checks each clip path:
  - absolute (`os.path.isabs`);
  - `lib._argv_safe`;
  - extension in `ACTION_CLIP_EXTS`;
  - `os.path.isfile`.
- Jobs:
  - `create_action_job` (:2396-2401) queues a background job;
  - `_h_action_create` (:2404-2413) builds `fields` with `clips`;
  - `_fs_text` (:1168-1170) and `tool_result` (:1173-1179).

**`movie_ui_lib.py`**
- `job_vlm("action-create")` is `"any"` (:421-437). The job runner has no wall-clock timeout: a
  job stops only when it exits or is cancelled (`cancel_tree` :279-298).
- `action_argv` (:1230-1245) emits one `--clip` for each path.
- `run_light` (:1301) uses `LIGHT_TIMEOUT = 60` (:958). `tool_argv` (:1331-1333). `_argv_safe`
  (:1481-1489).
- The progress parser keeps each job's last log line (`ProgressParser`, :2386-). A plain stdout
  line therefore shows as the job's live status, with no parser change.

**The page**
- `static/movie-ui/index.html:392-414`: the Actions panel, with a Clips textarea `#a-clips` (:400),
  Performers, Force, and the row holding `#a-create` (:404).
- `static/movie-ui/app.js`:
  - helpers `el`/`clear`/`show` (:57-73);
  - `errorText` (:2770-2772);
  - `loadActions` (:2958), `openAction` (:2981-3006), which makes one `<video>` for **every**
    dataset clip (:2995);
  - `submitAction` (:3008-3017), `setupActions` (:3019-3041).
- Static hygiene pin: `tests/test_movie_ui_seed_loras.py:343` checks that both files have no
  `https?://`, `\son[a-z]+=`, `style=`, `\bconfirm\(` or `innerHTML`.

**Tests that touch this code**
- `tests/test_action_dataset.py:47-69` pins `clip_%02d` names and caption == trigger.
- `tests/test_action_train.py`.
- `tests/test_movie_ui_actions.py:31-38` (argv), `:54-71` (create field rules).
- `tests/test_vlm_lifecycle.py:100-145`.

**The trainer: ltx-2-mlx v0.15.4 (`~/ltx-2-mlx` at `461df21`, on this Mac)**
- `packages/ltx-trainer/src/ltx_trainer_mlx/preprocess.py`:
  - videos are `sorted(rglob)` (:93);
  - a caption is matched to its video **by file stem** (:160-173);
  - conditions are written as `condition_{i:04d}` (:194-195) and latents as `latent_{i:04d}`
    (:261), both indexed over the same sorted list;
  - a clip that fails to encode is logged and skipped (:278-280); `train_action`'s
    latent-count check then fails the run;
  - frames are trimmed to `8k+1` (:308-312);
  - the encoding of every **unique** caption is kept in memory until text encoding ends
    (:211-238).
- `datasets.py:214-217` pairs `latent_X` with `condition_X`.

**The sample clips (read-only)**
- `~/fight_clips/{005_01_punch-stance-high_kick, 006_00_high_kick-stance-front_kick, 006_01_punch-stance-front_kick}.mp4`.
- All three are h264 at 1728x1080, 60 fps: 2.72 s with 163 frames, and 3.02 s with 181 frames
  (twice). Sizes are 1.3-1.9 MB.
- Normalizing them with the production filter, written to the scratchpad: 0.12-0.18 s per clip,
  output 768x768 with **65 / 72 / 72** frames, 0.30-0.37 MB each.
- Free space on this Mac's data volume: 22 GiB (`df`, 2026-11-23).

### 0.3 The approved design (binding) and what this spec adds
Approved:
- folder ingestion;
- the grammar `<n>_<n>_<moves>.mp4`, where `-` separates moves and `_` inside a move becomes a
  space;
- files that do not match are listed as skipped and never dropped silently;
- the order is deterministic;
- caption = `"<trigger>: <m1>, then <m2>, then <m3>"`, with one trigger for the whole LoRA;
- `build_dataset` takes an optional captions list (`None` keeps today's behaviour);
- `manifest.json` records each clip's source and caption;
- one performers number, the same `MIN_PERFORMERS`/`--force` rule, and MIN_CLIPS stays 8;
- CLI `--dir`, plus a UI Folder field, a Preview button and a read-only preview endpoint;
- out of scope: per-move LoRAs, detecting performers from names, the training recipe, the
  normalize aspect handling.

This spec adds:
- the exact grammar rules;
- the parser's location and a `bin/action scan` subcommand;
- the endpoint shape;
- the scale constants (contact-sheet sample, disk estimate, clip cap, preprocess timeout);
- per-clip progress lines;
- stale-clip cleanup on rebuild;
- a cap on the UI gallery;
- natural sorting of the dataset clip list.

### 0.4 Deliverables
1. `action_lib.py`: the file-name parser, the folder scan, and the caption builder.
2. `action_dataset.py`:
   - `build_dataset(..., captions=None, source_dir=None, skipped=None)`;
   - a contact-sheet sample;
   - the scaled disk check;
   - per-clip progress;
   - stale-clip cleanup;
   - `create --dir`;
   - a scaled preprocess timeout.
3. `bin/action`: `create --dir DIR` and a new read-only `scan DIR [--trigger PHRASE]`.
4. `movie_ui_lib.py`: `action_argv` emits `--dir`.
5. `movie_ui_server.py`:
   - `POST /api/actions/preview`;
   - `dir` on `POST /api/actions`;
   - the folder path rules;
   - natural clip sort.
6. `static/movie-ui/index.html` and `app.js`: the Folder field, the Preview button and table, the
   Create body, the gallery cap.
7. Tests (Section 6). One new file, `tests/test_action_bulk.py`, plus edits to existing ones.

### 0.5 Out of scope
- LoRAs per move, or a LoRA per move sequence.
- Detecting performers from file names. `--performers N` is one number for the whole folder.
- The training recipe: rank 32, 1000 steps, the YAML template, the validation prompt (still the
  bare trigger, `action_dataset.py:413`).
- `normalize_clip`'s aspect handling and frame count (findings F2 and F3 are reported, not
  changed).
- The `--fps` pass-through bug (F4: reported, not changed).
- Recursive folder scans, and more than one folder per action.
- Any change to `action.json`'s schema. `schema_version` stays 1.
- A disk check on the train host (Q3).

### 0.6 Success criteria (KPIs)
1. `bin/action create NAME --dir D --trigger T --descriptor X --performers N` builds one dataset
   from every matching file in `D`:
   - `captions/clip_K.txt` is exactly `clip_caption(T, moves_K)`;
   - every non-matching entry is printed as `skipped: <name> (<reason>)`.
2. With `captions=None`, `build_dataset` writes byte-identical caption files and the same
   `action.json` as at `b6bcb9b`. The only differences are the intended ones in 2.4.5-2.4.8.
3. The UI Preview lists every matched clip with its moves and caption, plus every skipped entry
   with its reason, before any job exists. Create with a folder queues one `action-create` job
   whose argv holds `--dir D` and no `--clip`.
4. A 1000-clip folder creates its dataset with no change needed to the trainer's pairing, the
   contact sheet or the timeout (pairing and sorting are verified in 0.2; the live check BKL2
   measures time).
5. The full suite is green: `python3 -m pytest -q -p no:cacheprovider tests/`, with the new tests
   in Section 6.

### 0.7 Must-have vs nice-to-have
- **Must:**
  - the parser, scan and caption builder;
  - captions in `build_dataset`;
  - manifest entries for each clip;
  - CLI `--dir` and `scan`;
  - the Preview endpoint and UI;
  - the contact-sheet sample;
  - the scaled disk check;
  - the clip cap;
  - progress lines;
  - the preprocess timeout scaling;
  - stale-clip cleanup;
  - the gallery cap.
- **Nice (not in this spec):**
  - showing each clip's caption in the action detail view;
  - a train-host disk preflight;
  - a pre-flight Preview inside Create.

---

## 1. Findings (verified this session)

- **F1. The 64-clip cap applies to the clips list only.** `ACTION_MAX_CLIPS = 64`
  (`movie_ui_server.py:2316`) limits the Clips textarea. The folder path needs its own cap
  (2.5.7). The 64 stays as it is for the list.
- **F2. Frame count with 60 fps sources (not changed).**
  - `probe_clip` counts frames at the source fps: 181 for a 3.02 s, 60 fps clip. So
    `clip_frames = min(97, snap_frames(181) = 177) = 97` (`action_dataset.py:188`), and the
    `-frames:v 97` cap never applies.
  - After `fps=24`, the normalized clip has 72 frames (65 for the 2.72 s clip). That is not on
    the `8k+1` lattice, and `dataset.frames` records 97.
  - The trainer trims each clip to `((n-1)//8)*8+1` (`preprocess.py:308-312`), which is 65 frames
    (2.67 s) for all three samples. Training works.
  - Reported only.
- **F3. Aspect ratio (reported as asked, not changed).**
  - 1728x1080 is 1.6:1. `scale=768:768:force_original_aspect_ratio=increase` makes it 1229x768,
    then `crop=768:768` keeps the centre 768 columns.
  - So **37.5% of the horizontal field of view is cropped away**: about 324 source pixels from
    each side of 1728.
  - Lateral kicks and wide stances near the frame edge can leave the frame. Live check BKL3
    inspects this.
- **F4. `create --fps` is ignored (predates this feature, not changed).** `create` never passes
  `fps=args.fps` to `build_dataset` (`action_dataset.py:463-465`). Every dataset is 24 fps.
- **F5. A rebuild leaves stale clips (fixed here).** `build_dataset` overwrites
  `clip_00..clip_{n-1}` but never removes higher-numbered leftovers. `train_action` globs every
  `clips/*.mp4` (:370). A `--regenerate` that shrinks the dataset (300 clips, then 250) would
  train on 50 stale clips with stale captions. Folders make shrinking rebuilds common, so this
  spec deletes the old files first (2.4.6). This also changes the `--clip` path, deliberately (Q4).
- **F6. The fixed 1800 s preprocess timeout does not scale.** Preprocess VAE-encodes every clip
  and Gemma-encodes every unique caption. Hundreds of clips can go past 30 min. This spec scales
  the timeout (2.5.6).
- **F7. Six tests pin the route count.** `len(srv.ROUTES) == 66` appears in:
  - `tests/test_movie_ui_http.py:44`;
  - `tests/test_location_ui.py:66`;
  - `tests/test_movie_ui_seed_loras.py:129`;
  - `tests/test_movie_ui_seedfolder.py:923` and `:960`;
  - `tests/test_movie_ui_seedgen.py:629`.

  All six change to 67. The new route goes right after `POST /api/actions`. The neighbour pins in
  seedfolder (`/api/jobs`, `/api/characters`) and seedgen (`/api/uploads`, `/api/seeds/folders`)
  are unaffected.
- **F8. Preprocess memory and disk on the train host are not measured.**
  - Preprocess writes one `condition_XXXX.safetensors` for every clip (float32 video, audio and
    mask embeddings).
  - It holds the encoding of every unique caption in memory until text encoding ends
    (`preprocess.py:211-238`).
  - Unique captions are at most the number of distinct move sequences.
  - Size per clip is not measured on this Mac (no preprocessed dataset exists here). Live check
    BKL4 measures it. There is no code change (Q3).
- **F9. Caption shape in the action spec.** Action spec 3.3 describes captions as
  `"<trigger>, <shot>, <one motion clause>"`, but the shipped code writes the bare trigger
  (`action_dataset.py:192`). The `--clip` path keeps the bare trigger. The folder path uses the
  approved `"<trigger>: <m1>, then <m2>"`. Section 8 amends the action spec.
- **F10. The trainer's pairing works past 99 clips (no rename needed).**
  - `clip_%02d` gives `clip_100`, `clip_101`, ... for index >= 100, so the names stay unique.
  - Preprocess matches captions by stem.
  - Latents and conditions share the sorted-list index (4 digits, up to 9999).
  - So `clip_%02d` stays. The plain sort in `_h_action` (:2357) is only cosmetic, and this spec
    changes it to a natural sort (2.6.6).
- **F11. Nothing contradicts the approved design.** The only structural constraint is that the
  server must not import `action_lib` (0.2). The Preview endpoint therefore runs the new
  `bin/action scan`, the same way `list` and `show` work. There is one parser and no copy.

---

## 2. Design (normative)

### 2.1 The file-name grammar (`action_lib.py`)

Add these constants after `DEFAULT_ACTION_STRENGTH` (:42):

```python
CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")     # = movie_ui_server.ACTION_CLIP_EXTS
CLIP_NAME_RE = re.compile(r"([0-9]+)_([0-9]+)_([A-Za-z0-9_-]+)\.([A-Za-z0-9]+)")
MOVE_RE = re.compile(r"[a-z][a-z0-9]*(?: [a-z0-9]+)*")
MAX_MOVES = 8
MAX_MOVE_CHARS = 40
MAX_DIR_CLIPS = 1000            # = ACTION_STEPS at batch size 1: past it some clips are never seen
CLIP_NAME_HINT = "<n>_<n>_<moves>.<ext>"
```

`parse_clip_name(name)` takes a basename (str). It returns `(moves, None)`, where `moves` is a
non-empty list of str, or `(None, reason)`. The checks run in this order and the first failure
wins:

1. `name.startswith(".")` gives `"hidden file"`.
2. `os.path.splitext(name)[1].lower() not in CLIP_EXTS` gives
   `"not a video (.mp4, .mov, .m4v, .webm, .mkv)"`.
3. `CLIP_NAME_RE.fullmatch(name)` is None gives `"name does not match <n>_<n>_<moves>.<ext>"`.
   The regex is ASCII only, so non-ASCII letters, spaces, dots inside the stem and other
   punctuation all fail here.
4. `raw = m.group(3).lower().split("-")`. For each `r` in `raw`, in order:
   1. `move = " ".join(r.replace("_", " ").split())`. So `_` becomes a space, runs of spaces
      collapse, and leading or trailing spaces are dropped.
   2. If `move == ""`, the reason is `"empty move"`. This covers `--`, a leading or trailing `-`,
      and a move made only of `_`.
   3. If `len(move) > MAX_MOVE_CHARS`, the reason is `"move longer than 40 characters"`.
   4. If `not MOVE_RE.fullmatch(move)`, the reason is `"move '%s' must start with a letter" % move`.
5. If `len(moves) > MAX_MOVES`, the reason is `"more than 8 moves"`.

Rules **[spec choice]**:
- Moves are lowercased.
- Duplicates are **kept**: `jab-jab` gives `["jab", "jab"]`, a double jab. Order is the content.
- A malformed move skips the whole file and is never repaired, so a typo shows up in Preview
  instead of becoming a silently changed caption.
- The two number groups are not interpreted beyond sorting (2.1.1).

Worked examples (each one is a test case in BKT1/BKT2):

| name | result |
|---|---|
| `006_00_high_kick-stance-front_kick.mp4` | `["high kick", "stance", "front kick"]` |
| `005_01_punch-stance-high_kick.mp4` | `["punch", "stance", "high kick"]` |
| `6_0_Kick.MP4` | `["kick"]` |
| `010_02_jab-jab.mov` | `["jab", "jab"]` |
| `007_00_spinning__back_kick.mp4` | `["spinning back kick"]` |
| `007_00__kick_.mp4` | `["kick"]` |
| `notes.txt` | `not a video (...)` |
| `kick.mp4`, `006_kick.mp4`, `006_00_.mp4`, `006_00_kick kick.mp4`, `006_00_kíck.mp4` | `name does not match <n>_<n>_<moves>.<ext>` |
| `006_00_punch--kick.mp4`, `006_00_-kick.mp4` | `empty move` |
| `006_00_1st_kick.mp4` | `move '1st kick' must start with a letter` |
| `006_00_a-b-c-d-e-f-g-h-i.mp4` | `more than 8 moves` |
| `.006_00_kick.mp4`, `._006_00_kick.mp4` | `hidden file` |

#### 2.1.1 The folder scan
`scan_clip_dir(path)` returns
`{"dir": str, "clips": [{"name", "path", "moves"}], "skipped": [{"name", "reason"}]}` and raises
`ActionError`.

- `d = os.path.abspath(path)`. It is not realpath'd, which matches how `new_action` records
  sources.
- If `not (os.path.isdir(d) and os.access(d, os.R_OK | os.X_OK))`, raise
  `ActionError("folder %s is not a readable directory" % d)`.
- `names = os.listdir(d)`. On `OSError` raise the same message. The scan is **non-recursive**.
- For each `name` in `sorted(names)`, with `full = os.path.join(d, name)`, the checks run in this
  order:
  1. `name.startswith(".")` makes it skipped with `"hidden file"`.
  2. `os.path.isdir(full)` makes it skipped with `"folder (not scanned)"`.
  3. `not os.path.isfile(full)` makes it skipped with `"not a regular file"`. Symlinks that
     resolve to a regular file pass, the same as `--clip` accepts any readable path today.
  4. `parse_clip_name(name)` fails: skipped with that reason.
  5. `not os.access(full, os.R_OK)` makes it skipped with `"not readable"`.
  6. Otherwise it is a clip: `{"name": name, "path": full, "moves": moves}`.
- `clips` is sorted by the key `(int(a), int(b), name)`, from `CLIP_NAME_RE`'s groups 1 and 2.
  This is numeric, so `9_00_x` comes before `10_00_x`, and it is stable.
- `skipped` stays in `sorted(names)` order.
- A skipped `name` is stored as `name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")`
  so that JSON output is always valid UTF-8. Matched names are ASCII by the regex.
- The scan **opens no file**. It lists one directory and calls `stat`/`access` on its entries.

#### 2.1.2 Captions
`clip_caption(trigger, moves)` returns `trigger + ": " + ", then ".join(moves)`.
- One move: `"performs a fight combo: kick"`.
- Three moves: `"performs a fight combo: high kick, then stance, then front kick"`.

The trigger is validated by the caller. `TRIGGER_RE` has no `:`, so the separator is unambiguous.

### 2.2 Appearance-free captions
Moves come from operator-chosen file names. The parser does not try to detect appearance. A name
like `red_shirt_kick` would put "red shirt kick" into the caption. The Preview shows every
caption before Create, and the operator is responsible for keeping them free of appearance. That
matches today's descriptor rule, which checks only shape (`action_lib.py:97-109`).

### 2.3 Which surfaces use what
| Surface | Parser | Reads |
|---|---|---|
| `bin/action scan DIR [--trigger T]` | `action_lib.scan_clip_dir` + `clip_caption` | one directory listing and `stat`s |
| `bin/action create --dir DIR` | the same | the listing, then ffprobe/ffmpeg on matched files only |
| `POST /api/actions/preview` | runs `bin/action scan` through `lib.run_light` | the same as `scan` |
| `POST /api/actions` with `dir` | queues `bin/action create --dir` | the same as `create` |

### 2.4 `build_dataset` (`action_dataset.py:154`)

1. **Signature.**
   `build_dataset(name, trigger, descriptor, clip_paths, performers, *, width=..., height=..., frames=..., fps=..., force=False, captions=None, source_dir=None, skipped=None)`.
2. **Caption validation.** This runs right after `validate_geometry` (:163), before the clip
   readability check.
   - If `captions is not None` and it is not a list with `len(captions) == len(clip_paths)`,
     raise `DatasetError("captions: %d given for %d clips" % (n_given, len(clip_paths)))`. Here
     `n_given` is `len(captions)` for a list or tuple, else -1.
   - For each `k, c`: if `not (isinstance(c, str) and c.strip() and "\n" not in c and "\r" not in c)`,
     raise `DatasetError("captions: caption %d must be one non-empty line" % k)`.
3. **The caption written** for clip `i` is `captions[i]` when `captions is not None`, else
   `trigger`. The write call stays the same (no trailing newline, utf-8).
4. **Clip file names** stay `clip_%02d.mp4`, `clip_%02d.txt` and `_frame_%02d.png` (F10).
5. **Disk check** **[spec choice]**.
   - Add `CREATE_PER_CLIP_GIB = 0.005` (5 MiB per clip) after :39, and
     `def create_min_free_gib(n_clips): return CREATE_MIN_FREE_GIB + CREATE_PER_CLIP_GIB * n_clips`.
   - :181-182 becomes: `need = create_min_free_gib(len(clip_paths))`; if `_free_gib(adir) < need`,
     raise `DatasetError("less than %.1f GiB free at %s (needed for %d clips)" % (need, adir, len(clip_paths)))`.
   - Basis: normalized clips measured 0.30-0.37 MB. 5 MiB covers a 97-frame clip with heavy
     motion more than 10 times over.
   - 64 clips need 2.32 GiB and 1000 clips need 6.9 GiB. This Mac has 22 GiB free.
6. **Stale cleanup** **[spec choice]**. After the disk check and before the clip loop, delete
   every `glob(os.path.join(clips_dir, "clip_*.mp4"))` and
   `glob(os.path.join(captions_dir, "clip_*.txt"))` with `os.unlink`. Nothing else is touched.
   This applies to both paths (F5, Q4).
7. **Progress.** At the top of each loop iteration, run
   `print("clip %d/%d: %s" % (i + 1, len(clip_paths), os.path.basename(src)), flush=True)`. The
   movie-ui job shows it as the last line (0.2).
8. **Contact-sheet sample** **[spec choice]**.
   - Add `CONTACT_MAX = 48` after :38 and:

     ```python
     def contact_sample(n, limit=CONTACT_MAX):
         """The clip indices whose mid frame goes on the contact sheet: all of them up to limit,
         else limit evenly spaced indices from 0 to n - 1 (distinct because n - 1 >= limit)."""
         if n <= limit:
             return list(range(n))
         return [(k * (n - 1)) // (limit - 1) for k in range(limit)]
     ```
   - In the loop, `extract_frame` runs only when `i` is in `set(contact_sample(len(clip_paths)))`.
   - The order of `frame_pngs`, the failure handling (`except DatasetError: pass`) and
     `CONTACT_COLS = 4` stay as they are. At most 12 rows of 320 px.
   - For 48 clips or fewer the behaviour is identical to today.
9. **`action.json`** is unchanged: the same `new_action` call with all matched paths, and the same
   `dataset` keys.
10. **`manifest.json`.** Every existing key stays (including `sources`). Four keys are appended,
    in this order:
    - `"items": [{"clip": "clip_%02d.mp4" % i, "source": os.path.abspath(p), "caption": <caption written>} for each clip]`
    - `"source_dir": source_dir` (an absolute str, or None)
    - `"skipped": list(skipped or [])`
    - `"contact_sheet_clips": contact_sample(len(clip_paths))`

    Nothing in the repo reads the dataset `manifest.json` (grep shows only the unrelated smoke and
    story manifests).

### 2.5 Scale decisions (summary, with the constant that decides each one)
1. **Contact sheet:** at most `CONTACT_MAX = 48` evenly spaced clips (2.4.8). Frame extraction
   for the rest is skipped, which saves an ffprobe and an ffmpeg per clip.
2. **Clip naming:** `clip_%02d` is kept, because pairing by stem works past 99 (F10). The UI clip
   list is sorted naturally (2.6.6).
3. **Disk:** `2.0 + 0.005 x n` GiB (2.4.5).
4. **Geometry:** unchanged. F2 and F3 are reported only.
5. **Create job:** the measured cost is about 0.2 s of ffmpeg per 3 s clip, plus 2 ffprobes, so
   1000 clips take minutes. No timeout applies (0.2). Progress lines (2.4.7) show it is alive.
   Cancel works as today.
6. **Preprocess timeout** **[spec choice]**.
   - Add the function:

     ```python
     def preprocess_timeout_s(n_clips):
         """PREPROCESS_TIMEOUT_S for up to 80 clips, then 15 s more for each clip."""
         return max(PREPROCESS_TIMEOUT_S, 600 + 15 * n_clips)
     ```
   - In `train_action`, the `PREPROCESS_TIMEOUT_S` argument at :400 becomes
     `preprocess_timeout_s(n_vid)`.
   - The value is unchanged up to 80 clips. 300 clips get 5100 s and 1000 clips get 15600 s.
   - `TRAIN_TIMEOUT_S` is unchanged, because the step count is fixed.
   - BKL4 measures the real seconds per clip.
7. **Clip cap.** `action_lib.MAX_DIR_CLIPS = 1000` applies to `--dir` only.
   - Past 1000 clips, 1000 steps at batch size 1 never sees some clips.
   - `--clip` keeps no CLI cap, and the server keeps 64 for the list.
   - `MIN_CLIPS = 8` is unchanged: a folder with fewer than 8 matches builds the dataset and
     exits 3, as today.

### 2.6 CLI

1. **`--dir` on both parsers.** Add to `action_dataset.build_parser` and `bin/action`'s
   `build_parser`, right after the `--clip` line:
   `c.add_argument("--dir", dest="dir", default=None, metavar="DIR", help="a folder of clips named <n>_<n>_<moves>.<ext>; each is captioned from its name")`
2. **`action_dataset.create`.** These replace :460-465. The name check and the already-exists
   check run first, unchanged.

   ```python
   if args.clips and args.dir:
       return _error("give either --dir or --clip, not both")
   if not (args.clips or args.dir) or not args.trigger or not args.descriptor:
       return _error("create needs --trigger, --descriptor and --dir or at least one --clip")
   clips, captions, source_dir, skipped = args.clips, None, None, None
   if args.dir:
       try:
           lib.validate_trigger(args.trigger)
           scan = lib.scan_clip_dir(args.dir)
       except lib.ActionError as e:
           return _error(str(e))
       for s in scan["skipped"]:
           print("skipped: %s (%s)" % (s["name"], s["reason"]))
       print("folder: %d clip(s) matched, %d skipped in %s"
             % (len(scan["clips"]), len(scan["skipped"]), scan["dir"]))
       if not scan["clips"]:
           return _error("no file in %s matches %s" % (scan["dir"], lib.CLIP_NAME_HINT))
       if len(scan["clips"]) > lib.MAX_DIR_CLIPS:
           return _error("%s has %d matching clips; an action takes at most %d"
                         % (scan["dir"], len(scan["clips"]), lib.MAX_DIR_CLIPS))
       clips = [c["path"] for c in scan["clips"]]
       captions = [lib.clip_caption(args.trigger, c["moves"]) for c in scan["clips"]]
       source_dir, skipped = scan["dir"], scan["skipped"]
   try:
       data = build_dataset(args.name, args.trigger, args.descriptor, clips,
                            args.performers, width=args.width, height=args.height,
                            frames=args.frames, force=args.force, captions=captions,
                            source_dir=source_dir, skipped=skipped)
   ```

   The `except`, the output lines and the exit-3 branch (:466-480) stay as they are. In the
   exit-3 message, the text `add more --clip` becomes `add more clips`.
3. **`bin/action scan DIR [--trigger PHRASE]`.** This is new, imports `action_lib` only, and is
   read-only.
   - Parser: `s = sub.add_parser("scan", help="list a folder's clips and the captions their names give (read-only)")`,
     then `s.add_argument("dir")` and `s.add_argument("--trigger", default=None)`.
   - `main` dispatches `scan` before the `import action_dataset` line, next to `list` and `show`.
   - `cmd_scan(path, trigger)`:
     - if `trigger is not None`, call `action_lib.validate_trigger(trigger)`;
     - `scan = action_lib.scan_clip_dir(path)`;
     - print `json.dumps(out, indent=2)`, where
       `out = {"dir": scan["dir"], "matched": len(scan["clips"]), "max": action_lib.MAX_DIR_CLIPS, "clips": [{"name", "path", "moves", "caption": clip_caption(trigger, moves) if trigger is not None else None}], "skipped": scan["skipped"]}`;
     - return 0, even with 0 matches;
     - on `ActionError`, print `Error: <message>` to stderr and return 2.
4. **The `bin/action` docstring** (:4-8). Add the usage lines
   `bin/action create NAME --trigger PHRASE --descriptor TEXT --dir DIR [--performers N] ...` and
   `bin/action scan DIR [--trigger PHRASE]`, plus one sentence: "--dir replaces --clip: every
   file named <n>_<n>_<moves>.<ext> in DIR (not recursive) becomes a clip captioned
   '<trigger>: <move>, then <move>'; scan previews that without writing anything."
5. **Exit codes.**
   - 2: both `--dir` and `--clip`, neither, an unreadable dir, 0 matches, too many matches, a bad
     trigger, or any existing condition.
   - 3: fewer than 8 clips kept, as today.
6. **Natural sort (server, 2.7).** `_h_action`'s
   `sorted(os.path.join(clips_dir, n) for n ...)` (:2357) becomes
   `[os.path.join(clips_dir, n) for n in sorted((n for n in os.listdir(clips_dir) if n.endswith(".mp4")), key=lambda n: (len(n), n))]`.

### 2.7 Server (`movie_ui_server.py`, `movie_ui_lib.py`)

1. **The route.** Insert
   `("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview"),` right after
   the `POST /api/actions` line (:101). Bind `MovieUIHandler.h_action_preview = _h_action_preview`
   with the others (:2421-2424).
2. **The folder rule.** Add `action_dir_errors(path)` after `action_create_errors`. It returns a
   list, and the first failure wins (a one-element list):
   - if it is not `(isinstance(path, str) and os.path.isabs(path) and lib._argv_safe(path))`:
     `"folder must be an absolute path"`;
   - `".." in path.split("/")`: `"folder must not contain '..'"`;
   - `not os.path.isdir(path)`: `"folder %s not found" % _fs_text(path)`;
   - `not os.access(path, os.R_OK | os.X_OK)`: `"folder %s is not readable" % _fs_text(path)`.
3. **`action_create_errors`.** The clips branch (:2378-2387) is wrapped:

   ```python
   folder = body.get("dir")
   if folder is not None:
       if clips is not None:
           errors.append("give either clip paths or a folder, not both")
       else:
           errors += action_dir_errors(folder)
   elif not (isinstance(clips, list) and 1 <= len(clips) <= ACTION_MAX_CLIPS):
       ...   # the existing clips rule, unchanged
   ```

   The error order, and every existing message, are unchanged.
4. **`_h_action_create`.** `fields` is built in this key order: `ws, name, trigger, descriptor`,
   then **either** `"dir": body["dir"]` (when `body.get("dir") is not None`) **or**
   `"clips": list(body["clips"])`, then `performers, force, regenerate`.
5. **`lib.action_argv`.** The `for path in fields["clips"]` loop (:1237-1238) becomes:
   `if fields.get("dir") is not None: argv += ["--dir", fields["dir"]]`, `else:` the existing
   loop. The position (after `--descriptor`) is unchanged.
6. **`_h_action_preview(self, groups, query, body)`:**

   ```python
   real = self.ws(body.get("ws"))
   errors = action_dir_errors(body.get("dir"))
   trigger = body.get("trigger")
   if trigger is not None and not isinstance(trigger, str):
       errors.append("trigger must be a string")
   elif isinstance(trigger, str) and trigger.strip() and not ACTION_TRIGGER_RE.fullmatch(trigger.strip()):
       errors.append("trigger must be a Motion: phrase of 1-40 letters, digits, spaces, _ ' or -")
   if errors:
       raise ApiError(400, "invalid fields", errors=errors)
   args = ["scan", body["dir"]]
   if isinstance(trigger, str) and trigger.strip():
       args += ["--trigger", " ".join(trigger.split())]
   run = tool_result("action", lib.run_light(lib.tool_argv(real, "action", *args), real))
   try:
       data = json.loads(run["stdout"])
   except ValueError:
       raise ApiError(502, "action printed unparsable output", run=run)
   if not (isinstance(data, dict) and {"dir", "matched", "max", "clips", "skipped"} <= set(data)):
       raise ApiError(502, "action printed unparsable output", run=run)
   return 200, {k: data[k] for k in ("dir", "matched", "max", "clips", "skipped")}
   ```

   It creates no job and writes nothing. It does not require any minimum number of matches.
7. **The Python 3.9 rule.** Every line added to the server, `movie_ui_lib`, `action_lib`,
   `action_dataset` and `bin/action` must compile on `/usr/bin/python3` (3.9.6). That means no
   `match`, no `X | Y` types and no 3.10+ APIs.

### 2.8 The page

**`index.html`** (Actions panel, :392-414):

1. Replace the `<p class="muted">` text (:395) with:
   `One named move per action (e.g. a roundhouse kick), from at least 8 reference clips by at least 3 different performers, so the LoRA learns the motion and not a face. Or give one folder of clips named &lt;n&gt;_&lt;n&gt;_&lt;moves&gt;.mp4 (e.g. 006_00_high_kick-stance-front_kick.mp4): each clip is captioned with the trigger and its moves.`
2. Insert right after the Clips `<label>` line (:400):
   `    <label class="wide">Folder <input id="a-dir" type="text" size="70" spellcheck="false" placeholder="or one absolute folder path instead of clips: /Users/me/fight_clips"></label>`
3. Replace the row at :404 with:
   `  <div class="row"><button id="a-preview" type="button">Preview folder</button> <button id="a-create" type="button">Create dataset</button> <span id="a-create-status" class="muted"></span></div>`
4. Insert right after it:

   ```html
     <div id="a-preview-out" hidden>
       <p id="a-preview-summary" class="muted"></p>
       <table id="a-preview-clips" class="list"><thead><tr><th>File</th><th>Moves</th><th>Caption</th></tr></thead><tbody></tbody></table>
       <table id="a-preview-skipped" class="list"><thead><tr><th>Skipped file</th><th>Reason</th></tr></thead><tbody></tbody></table>
     </div>
   ```

**`app.js`**:

1. Add `  const ACTION_GALLERY_MAX = 24;   // bulk action clips spec 2.8: dataset clips shown as videos`
   right after `const SEEDS_MAX = 100; ...` (:12).
2. In `openAction` (:2995), replace the `res.data.clips.forEach(...)` line with:

   ```js
       res.data.clips.slice(0, ACTION_GALLERY_MAX).forEach(function (p) { gallery.appendChild(el("video", {src: fileUrl(p), controls: "", preload: "metadata"})); });
       if (res.data.clips.length > ACTION_GALLERY_MAX) {
         gallery.appendChild(el("p", {cls: "muted", text: "and " + (res.data.clips.length - ACTION_GALLERY_MAX) + " more clips in the dataset"}));
       }
   ```
3. Add these two functions right before `function setupActions() {`:

   ```js
     function actionPreviewSummary(data) {
       const parts = [data.matched + " clip(s) match in " + data.dir, data.skipped.length + " skipped"];
       if (data.matched > data.max) { parts.push("too many: an action takes at most " + data.max + " clips"); }
       else if (data.matched < 8) { parts.push("training needs at least 8 clips"); }
       return parts.join("; ");
     }

     function renderActionPreview(data) {
       $("#a-preview-summary").textContent = actionPreviewSummary(data);
       const clips = clear($("#a-preview-clips tbody"));
       data.clips.forEach(function (c) {
         clips.appendChild(el("tr", {}, [el("td", {text: c.name}), el("td", {text: c.moves.join(", ")}),
           el("td", {text: c.caption === null ? "(enter a trigger to see the caption)" : c.caption})]));
       });
       const skipped = clear($("#a-preview-skipped tbody"));
       data.skipped.forEach(function (s) {
         skipped.appendChild(el("tr", {}, [el("td", {text: s.name}), el("td", {text: s.reason})]));
       });
       show($("#a-preview-skipped"), data.skipped.length > 0);
       show($("#a-preview-out"), true);
     }
   ```
4. In `setupActions`, replace the `#a-create` listener (:3020-3027) with:

   ```js
       $("#a-create").addEventListener("click", function () {
         const clips = $("#a-clips").value.split("\n").map(function (l) { return l.trim(); })
           .filter(function (l) { return l; });
         const dir = $("#a-dir").value.trim();
         if (dir && clips.length) { $("#a-create-status").textContent = "give either clip paths or a folder, not both"; return; }
         const body = {name: $("#a-name").value.trim(), trigger: $("#a-trigger").value.trim(),
                       descriptor: $("#a-descriptor").value.trim(),
                       performers: numberOrNull("#a-performers") || 0, force: $("#a-force").checked,
                       regenerate: false};
         if (dir) { body.dir = dir; } else { body.clips = clips; }
         submitAction(body, $("#a-create-status"));
       });
       $("#a-preview").addEventListener("click", async function () {
         const dir = $("#a-dir").value.trim();
         if (!dir) { show($("#a-preview-out"), false); $("#a-create-status").textContent = "enter a folder path to preview"; return; }
         $("#a-create-status").textContent = "";
         const res = await api("POST", "/api/actions/preview", {ws: S.ws, dir: dir, trigger: $("#a-trigger").value.trim()});
         if (res.status !== 200) { show($("#a-preview-out"), false); $("#a-create-status").textContent = errorText(res); return; }
         renderActionPreview(res.data);
       });
   ```

   The Rebuild and Train listeners are unchanged. Rebuild re-sends `last_create_fields`, which
   now carries `dir` for a folder action, so the folder is scanned again.
   - Preview is **not** required before Create **[spec choice]**.
   - All server text goes in through `textContent` (`el`'s `text`).
   - The page adds no `confirm(`, `innerHTML`, inline handlers, `style=` or URLs.
5. `app.css` is unchanged. The new tables use the existing `table.list` class.

---

## 3. Exact messages

| Where | Text |
|---|---|
| `parse_clip_name` | `hidden file` · `not a video (.mp4, .mov, .m4v, .webm, .mkv)` · `name does not match <n>_<n>_<moves>.<ext>` · `empty move` · `move longer than 40 characters` · `move '<move>' must start with a letter` · `more than 8 moves` |
| `scan_clip_dir` | `folder (not scanned)` · `not a regular file` · `not readable` · ActionError `folder <abs> is not a readable directory` |
| `build_dataset` | `captions: <n> given for <m> clips` · `captions: caption <k> must be one non-empty line` · `less than <x.x> GiB free at <adir> (needed for <n> clips)` · progress `clip <i>/<n>: <basename>` |
| `create` | `give either --dir or --clip, not both` · `create needs --trigger, --descriptor and --dir or at least one --clip` · `skipped: <name> (<reason>)` · `folder: <n> clip(s) matched, <m> skipped in <dir>` · `no file in <dir> matches <n>_<n>_<moves>.<ext>` · `<dir> has <n> matching clips; an action takes at most 1000` · exit-3 text `... add more clips and run bin/action create <name> --regenerate.` |
| server | `folder must be an absolute path` · `folder must not contain '..'` · `folder <path> not found` · `folder <path> is not readable` · `give either clip paths or a folder, not both` · `trigger must be a string` |
| page | `give either clip paths or a folder, not both` · `enter a folder path to preview` · `(enter a trigger to see the caption)` · `and <n> more clips in the dataset` · summary parts as in 2.8 |

---

## 4. Safety
- **Path rules.** The UI folder path follows the same rules as the clip paths (absolute,
  `_argv_safe`, exists, readable), plus a `..` rejection **[spec choice]**. Because the path is
  absolute it begins with `/`, so it can never be read as a flag in `bin/action`'s argv.
- **What Preview reads.** It reads no more than Create would: a single directory listing plus
  `stat`/`access`, and no file contents. Create then hands ffprobe and ffmpeg only the matched
  regular files inside that folder. Subfolders are listed but never entered.
- **Disclosure.** Preview returns the file names in one folder the operator chose. The server
  listens only on loopback and requires a token (MU10/MU18; the token pin covers the new route
  through `test_mut18`). That disclosure is no larger than the create job log, which prints the
  same skipped names.
- **Identity-agnostic.** The rule itself is unchanged: one `performers` number, `MIN_PERFORMERS`
  and `--force` behave as today, and `identity_agnostic` is recorded as today. Captions are the
  trigger plus move words. Preview shows every caption so the operator can review it (2.2).
- **Repository content.** It is a public repo with no secrets. Tests use temporary folders and
  synthetic file names. No sample clip or user path goes in, except in placeholder text.

---

## 5. Alternatives considered and open questions (with defaults)
- **Alternative: copy the parser into the server.** Rejected. It would mean two grammars to keep
  in step, while `bin/action scan` follows the existing list/show subprocess pattern and keeps
  one implementation.
- **Alternative: rename to `clip_%04d`.** Rejected: it is not needed (F10), and it would
  invalidate the existing name pins (`tests/test_action_dataset.py:61-65`,
  `tests/test_action_train.py:49-50`).
- **Q1. Clip cap.** Default `MAX_DIR_CLIPS = 1000`, which equals the step count at batch size 1.
  Raise it only together with the step count, which is out of scope.
- **Q2. Preprocess timeout.** Default `max(1800, 600 + 15 * n)`. The 15 s per clip is an
  estimate. BKL4 measures it, and a later change can tune the constant.
- **Q3. Disk on the train host.** No new check by default. BKL4 measures the size of
  `train/video/preprocessed` per clip, and a follow-up adds a preflight if it is large.
- **Q4. Stale cleanup also changes the `--clip` path.** Yes by default: it fixes a real
  stale-data bug (F5). If the user wants the `--clip` path byte-for-byte unchanged, put the
  cleanup under `if source_dir is not None`.
- **Q5. Hidden files in Preview.** By default they are listed as `hidden file`, so nothing is
  dropped silently. On exFAT drives, `._*` AppleDouble files can double the skipped list. That
  is acceptable.

---

## 6. Tests

### 6.1 New: `tests/test_action_bulk.py` (Task 1)
It loads `action_dataset`/`action_lib` by path the way `tests/test_action_dataset.py:13-16` does.
Tests that need ffmpeg use the same `needs_ffmpeg` skip and the same `_make_clip` helper (copied).

- **BKT1. Matching names.** `parse_clip_name` on every "matching" row of the 2.1 table returns
  `(moves, None)` with those exact lists.
- **BKT2. Non-matching names.** Every "non-matching" row returns `(None, reason)` with the exact
  reason. Also: a move of 41 letters gives `move longer than 40 characters`, and
  `006_00_kick.mp4.part` gives `not a video ...`.
- **BKT3. `scan_clip_dir` on a temporary folder.**
  - The folder holds zero-byte files `9_00_kick.mp4`, `10_00_punch-kick.mp4`,
    `006_00_high_kick-stance-front_kick.mp4` and `notes.txt`, a hidden `.006_00_kick.mp4`, a
    subfolder `sub/` containing `001_00_kick.mp4`, and `011_00_jab.mp4` with mode 000. Skip the
    000 file's assertion when `os.geteuid() == 0`.
  - `clips` names in order: `["006_00_high_kick-stance-front_kick.mp4", "9_00_kick.mp4", "10_00_punch-kick.mp4"]`.
  - `skipped` holds exactly these, in sorted-name order: `.006_00_kick.mp4` (`hidden file`),
    `011_00_jab.mp4` (`not readable`), `notes.txt` (`not a video ...`), `sub`
    (`folder (not scanned)`).
  - `dir` is absolute, and a relative argument gives the same result.
  - A path to a file, and a missing path, both raise `ActionError` `folder ... is not a readable directory`.
- **BKT4. `clip_caption`.** One move gives `"performs a fight combo: kick"`. The 006_00 moves give
  `"performs a fight combo: high kick, then stance, then front kick"`.
- **BKT5. Captions on disk (ffmpeg).**
  - Build 3 synthetic clips (64x64, 9 frames) with
    `captions=["t: a", "t: b, then c", "t: d"]`, `source_dir="/x"` and
    `skipped=[{"name": "n.txt", "reason": "r"}]`.
  - Each `captions/clip_0K.txt` equals its caption.
  - In `manifest.json`: `items` lists clip, source and caption for each clip; `source_dir == "/x"`;
    `skipped` matches; `contact_sheet_clips == [0, 1, 2]`; every existing key is still present.
  - `captions` of length 2 for 3 clips raises `DatasetError("captions: 2 given for 3 clips")`,
    and no clip file is written (the check runs before ffmpeg).
  - The captions `""` and `"a\nb"` raise `captions: caption <k> must be one non-empty line`.
- **BKT6. The single-trigger path is unchanged (ffmpeg).**
  - `captions=None` with 3 clips: every caption file is exactly the trigger.
  - `action.json` has the same keys and values as `tests/test_action_dataset.py:55-57` asserts.
  - Manifest `items[*].caption` are all the trigger, `source_dir is None`, and `skipped == []`.
  - `tests/test_action_dataset.py` passes **unedited**.
- **BKT7. `contact_sample`.**
  - `0` gives `[]`, `5` gives `[0..4]`, `48` gives `list(range(48))`.
  - `49` gives 48 distinct values starting at 0 and ending at 48.
  - `1000` gives 48 distinct, strictly increasing values, starting at 0 and ending at 999.
- **BKT8. Stale cleanup (ffmpeg).** Build with 3 clips, then build again with 2. Only
  `clip_00`/`clip_01` `.mp4`/`.txt` remain.
- **BKT9. Disk scaling.**
  - `create_min_free_gib(0) == 2.0`, `(100) == 2.5`, `(1000) == 7.0` (`pytest.approx`).
  - With `monkeypatch.setattr(ad, "_free_gib", lambda p: 2.01)`, building 3 real clips raises
    `DatasetError` whose message starts with `less than 2.0 GiB free at` and ends with
    `(needed for 3 clips)`.
- **BKT10. `create` and the CLI.**
  1. `ad.main` with both `--dir` and `--clip` returns 2, and stderr holds
     `give either --dir or --clip, not both`.
  2. With neither, it returns 2 with the "create needs" message.
  3. `--dir` on a folder holding only `notes.txt` returns 2: `no file in <dir> matches <n>_<n>_<moves>.<ext>`.
  4. `--dir` on a folder holding `notes.txt` and 3 synthetic clips (ffmpeg) named
     `001_00_kick.mp4`, `002_00_punch-kick.mp4` and `003_00_high_kick-stance.mp4`, with
     `--width 64 --height 64 --frames 9 --performers 3`, returns 3, as today for fewer than 8
     clips:
     - stdout holds `skipped: notes.txt (not a video (.mp4, .mov, .m4v, .webm, .mkv))` and
       `folder: 3 clip(s) matched, 1 skipped in`;
     - the captions on disk are the `clip_caption` strings, in scan order;
     - stdout holds `clip 1/3:`.
  5. Cap: with `monkeypatch.setattr(al, "MAX_DIR_CLIPS", 2)` and
     `monkeypatch.setattr(ad, "_load_action_lib", lambda: al)`, a folder of 3 matching zero-byte
     files returns 2 with `has 3 matching clips; an action takes at most 2`.
  6. Load `bin/action` by path: `build_parser().parse_args(["create", "x", "--trigger", "t", "--descriptor", "d", "--dir", "/tmp"])`
     gives `.dir == "/tmp"` and `.clips == []`.
- **BKT11. `bin/action scan` as a subprocess.** Run `[sys.executable, WS/bin/action, "scan", d, "--trigger", "performs a fight combo"]`
  with `ACTION_LIBRARY_DIR` set to tmp.
  - It returns 0. The JSON keys are exactly `dir, matched, max, clips, skipped`. `max == 1000`.
    The captions are as in BKT4.
  - Without `--trigger`, every `caption` is null.
  - `--trigger "bad:trigger"` returns 2, and stderr starts with `Error: trigger:`.
  - A missing dir returns 2.
  - The folder's contents and mtimes are unchanged after the run (read-only).
- **BKT12. Preprocess timeout.**
  - `preprocess_timeout_s(8) == 1800`, `(80) == 1800`, `(300) == 5100`, `(1000) == 15600`.
  - Using `tests/test_action_train.py`'s stub pattern (copy `_STUB`, `_seed_action` and
    `_install_stub`), wrap `ad._run_logged` to record `timeout_s`. A run with 8 clips records
    1800 for preprocess and 14400 for train.

### 6.2 Extended: `tests/test_movie_ui_actions.py` (Task 2)
Add an `env` fixture on the same pattern as `tests/test_location_ui.py:38-47`, and set
`ACTION_LIBRARY_DIR` to tmp. Tests that hit the real tool copy `bin/action` to `<ws>/bin/action`
and `action_lib.py` to `<ws>/action_lib.py` with `shutil.copy2`.

- **BKT13. `action_argv` with `dir`.** It returns
  `["py", "/ws/bin/action", "create", "roundhouse-kick", "--trigger", T, "--descriptor", DESC, "--dir", "/c", "--performers", "3"]`.
  The existing `test_action_job_argv` is unchanged and passes.
- **BKT14. `action_create_errors` folder mode** (`good` is the existing `good` without `clips`,
  plus `dir=str(tmp_path)`).
  - `[]` for the good body.
  - With `clips` also given: `["give either clip paths or a folder, not both"]`.
  - `"rel/dir"` gives `["folder must be an absolute path"]`.
  - `str(tmp_path) + "/../x"` gives `["folder must not contain '..'"]`.
  - A missing path gives `["folder <p> not found"]`.
  - A file path gives `["folder <p> not found"]`.
  - Mode 000 gives `["folder <p> is not readable"]` (skipped as root).
  - The existing `test_action_create_errors` is unchanged and passes.
- **BKT15. Preview over HTTP (real `bin/action`).**
  - Set up a temporary folder with two matching zero-byte files and `notes.txt`.
  - `POST /api/actions/preview {"ws", "dir", "trigger": "performs a fight combo"}` returns 200:
    - `matched == 2`, `max == 1000`;
    - the captions are exact;
    - `skipped == [{"name": "notes.txt", "reason": "not a video (.mp4, .mov, .m4v, .webm, .mkv)"}]`.
  - With no trigger, the captions are null.
  - `dir="rel"` returns 400 with `errors == ["folder must be an absolute path"]`.
  - `trigger="bad:x"` returns 400 with the Motion: phrase message.
  - The queue is still empty afterwards: `lib.read_queue(state) == []` and `lib.list_job_ids(state)`
    is empty.
  - No token returns 401.
- **BKT16. Create with a folder over HTTP.**
  - `POST /api/actions` with `dir` returns 201.
  - The job's argv (`lib.read_job(...)["argv"]`) holds `["--dir", dir]` and no `--clip`.
  - The job's `fields` has `dir` and no `clips` key. It is not dispatched.
- **BKT17. Natural clip order.**
  - Write `<lib>/kick-set/action.json`. Use `al.new_action`, then set `dataset` with
    `contact_sheet` pointing at `<lib>/kick-set/dataset/contact_sheet.jpg`, then `al.write_action`.
  - Create `dataset/clips/clip_00.mp4 .. clip_100.mp4` as empty files.
  - `GET /api/actions/kick-set` returns `clips` whose basenames are `clip_00.mp4, ..., clip_99.mp4, clip_100.mp4`, in that order.
- **BKT18. Static pins.** Read `index.html` and `app.js`.
  - Each of these ids appears exactly once in the html: `a-dir`, `a-preview`, `a-preview-out`,
    `a-preview-summary`, `a-preview-clips`, `a-preview-skipped`.
  - `index('id="a-clips"') < index('id="a-dir"') < index('id="a-performers"')`.
  - app.js contains:
    - `'"/api/actions/preview"'`;
    - `"function renderActionPreview(data) {"`;
    - `"const ACTION_GALLERY_MAX = 24;"`;
    - `"give either clip paths or a folder, not both"`;
    - `"res.data.clips.slice(0, ACTION_GALLERY_MAX)"`.
  - Neither file matches `https?://`, `\son[a-z]+=`, `style=`, `\bconfirm\(` or `innerHTML`.
  - When `node` is on PATH, `node --check app.js` returns 0.

### 6.3 Existing tests edited (Task 2)
- Change `len(srv.ROUTES) == 66` to `67` at `tests/test_movie_ui_http.py:44`,
  `tests/test_location_ui.py:66`, `tests/test_movie_ui_seed_loras.py:129`,
  `tests/test_movie_ui_seedfolder.py:923` and `:960`, and `tests/test_movie_ui_seedgen.py:629`.
  Nothing else in those files changes.
- No other existing test is edited. `tests/test_action_dataset.py`, `tests/test_action_train.py`
  and `tests/test_vlm_lifecycle.py` pass unchanged.

---

## 7. Live checks (the user runs these on macstudio; the assistant never accesses it)
- **BKL1.** Run `bin/action scan <the full clip folder> --trigger "<trigger>"`.
  - `matched` and the skipped list are as expected.
  - Every `skipped` reason is real (no false skips of valid names).
  - Spot-check 10 captions.
- **BKL2.** In the UI, use Folder, then Preview, then Create.
  - The job log shows `clip i/N` lines.
  - Record wall time and the size of `dataset/clips`. Compare with 5 MiB per clip.
  - `contact_sheet.jpg` has at most 48 frames.
  - The action page shows 24 videos and the "more clips" line.
- **BKL3.** Look at the contact sheet and about 10 normalized clips for the 37.5% horizontal crop
  (F3): are kicks or feet leaving the frame? This only informs a future normalize change, which
  is out of scope here.
- **BKL4.** Run Train.
  - Record the preprocess wall time per clip against `preprocess_timeout_s(N)`.
  - Record the size per clip of `train/video/preprocessed/.precomputed/conditions` and `latents`.
  - Record the peak memory during caption encoding (F8).
  - Training completes and produces a LoRA that `bin/lora-check` passes.
- **BKL5.** Render a neutral subject with `--action <name>`, using the trigger alone. Then render
  with a Motion: that adds moves (`"<trigger>: high kick, then front kick"`). Note whether the
  order of moves can be controlled. This is an observation only; per-move control is out of
  scope.
- **BKL6.** Repeat the action spec's AC3/AC4: swap the subject or add a character LoRA and confirm
  identity does not leak from the performers.

---

## 8. Amended requirements of the action spec
- Action spec 3.1 (ingestion) adds: a folder source (`--dir`, non-recursive, the 2.1 grammar)
  with up to `MAX_DIR_CLIPS = 1000` clips.
- Action spec 3.3 (captioning) now says: with `--clip`, caption = the trigger (as shipped). With
  `--dir`, caption = `"<trigger>: <m1>, then <m2>, ..."`. Both stay appearance-free.
- Action spec 3.4 (review gate) adds: the contact sheet is at most 48 evenly spaced clips, and
  `manifest.json` lists each clip's source and caption.

---

## 9. Acceptance criteria
- **BK-AC1** The grammar, order and reasons follow 2.1 (BKT1-BKT3).
- **BK-AC2** Folder captions on disk equal `clip_caption(trigger, moves)`, and the manifest
  records `items`/`source_dir`/`skipped`/`contact_sheet_clips` (BKT4, BKT5, BKT10.4).
- **BK-AC3** `captions=None` writes trigger-only captions and an unchanged `action.json`, and
  `tests/test_action_dataset.py` passes unedited (BKT6).
- **BK-AC4** The contact sheet has at most 48 frames, the disk need is `2.0 + 0.005n` GiB, stale
  files are removed, progress lines are printed, and the preprocess timeout scales (BKT7-BKT9,
  BKT12).
- **BK-AC5** The CLI `--dir`/`--clip` exclusion, 0-match, cap and exit codes follow 2.6
  (BKT10), and `bin/action scan` is read-only JSON (BKT11).
- **BK-AC6** `POST /api/actions/preview` validates, runs `scan`, creates no job, and needs the
  token. `POST /api/actions` with `dir` queues `create --dir` (BKT13-BKT16).
- **BK-AC7** The page has the Folder field, Preview, the either/or rule and the gallery cap,
  with the hygiene pins green (BKT18). Dataset clips sort naturally (BKT17).
- **BK-AC8** The full suite is green, with 6 route-count pins at 67. Every changed Python file
  compiles on 3.9.
- **BK-AC9** Live checks BKL1-BKL6 are reported by the user.

---

## Plan (task-level outline)

### Task 1: parser, captions in `build_dataset`, CLI (one commit)
Files:
- `action_lib.py`: 2.1 constants, `parse_clip_name`, `scan_clip_dir`, `clip_caption`.
- `action_dataset.py`:
  - `CONTACT_MAX`, `contact_sample`;
  - `CREATE_PER_CLIP_GIB`, `create_min_free_gib`;
  - `preprocess_timeout_s`;
  - the `build_dataset` changes (2.4.1-2.4.10);
  - the `create` changes (2.6.2);
  - `--dir` in `build_parser`;
  - the `train_action` timeout argument.
- `bin/action`: `--dir`, the `scan` subcommand, the docstring.
- `tests/test_action_bulk.py` (new: BKT1-BKT12).

Verify:
- `python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py tests/test_action_dataset.py tests/test_action_train.py tests/test_action_lib.py`
- `/usr/bin/python3 -m py_compile action_lib.py action_dataset.py bin/action`

### Task 2: server Preview, Create `dir`, UI (one commit)
Files:
- `movie_ui_lib.py` (`action_argv`).
- `movie_ui_server.py`: route, `action_dir_errors`, `action_create_errors`, `_h_action_create`,
  `_h_action_preview`, natural sort in `_h_action`, binding.
- `static/movie-ui/index.html`, `static/movie-ui/app.js` (2.8).
- `tests/test_movie_ui_actions.py` (BKT13-BKT18).
- The six route-count pins (6.3).

Verify:
- `python3 -m pytest -q -p no:cacheprovider tests/` (full suite).
- `/usr/bin/python3 -m py_compile movie_ui_lib.py movie_ui_server.py`
- `node --check static/movie-ui/app.js` when node is present.

### Task 3: not needed
The work fits in two reviewable commits. The trainer needs no change (F10), and the job runner
needs no timeout change (0.2). A third task would only split Task 2's UI from its server half,
and those two are tested together (BKT15-BKT18).

### Verification (controller)
Design review of both commits, by the `design-reviewer` agent, before declaring done. Then hand
BKL1-BKL6 to the user.
