# Location dataset yield: own-source scoring, indoor variants, top-up rounds

Date: 2026-11-02

Status: design spec. A user's NYC subway location kept 11 of 24 stills, one short of `MIN_KEEP` 12, and stayed untrainable (status `dataset`). The user approved option A: three yield fixes now, with no model changes. (1) Each photo-mode edit is scored against its own source photo. (2) Text mode gets indoor-aware variants. (3) A bounded top-up regenerates dropped generated stills. This document carries option A without reopening it. Every detail option A leaves open is decided here, marked **[spec choice]**, and listed in Section 9. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/locyield-wt`, branch `location-yield` off `qwen-agent-redteam` at `98e5f64`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `98e5f64`.

Builds on **[LOC]** `docs/superpowers/specs/2026-10-29-location-lora-design.md`. This spec amends its Sections 2.5 (text mode), 2.9 (the edit row of the check table), 2.10 (manifest), 2.11 (contact sheet) and 2.12 (create step 8). Everything else in [LOC] stands. The implementer does not edit [LOC].

Terms:
- A **round** is one image pass: render a set of stills with the image child, then score each one with the VLM. Round 1 is today's build. Rounds 2 and 3 are **top-up rounds**.
- A **regenerable** still is a still that is not kept and whose `source` is `"generated"` (text mode) or `"edit"` (photo mode). User photos (`source "photo"`) are never regenerable.
- The **indoor rule** is `indoor_word(description)` (LY3).

Requirement ids are LY1-LY16. Tests are LYD1-LYD13 (in `tests/test_location_dataset.py`) and LYU1 (in `tests/test_location_ui.py`). KPIs are LYK1-LYK8. A grep at `98e5f64` found no spec, plan, test or source file using `LY<n>`, `LYD<n>`, `LYU<n>` or `LYK<n>`.

---

## 0. Scope

### 0.1 Grounding (verified at `98e5f64`)

**`location_dataset.py` (924 lines).**
- `TIMES`/`WEATHERS`/`TIME_PHRASES`/`WEATHER_PHRASES` `:42-47`. `VARIANTS` (24 outdoor `(view, time, weather)` tuples: "under a clear sky", "in fog", "high vantage point") `:48-74`. `gen_prompt` `:77-79`.
- `EDIT_PROMPT` `:84-89`, `EDIT_CONDITIONS` `:90-102`, `EDIT_VIEWS` `:104-116`. `CHECK_PHOTO_PROMPT` ("The first image shows the reference place ...") `:152-159`.
- `write_contact_sheet` `:304-323` (banner `:311-313`). `cell_label` `:326-329`.
- `_with_story_server_stopped(min_gib, work)` `:336-361`: stop, memory wait, `work()`, restore in a `finally` (detached after an interrupt; otherwise `--wait` plus `wait_for_vlm`).
- `_plan(data, loc_dir)` `:364-389`. Every text job is seeded with `data["seed"]` (`:371-372`). Every edit job is too (`:382-384`). The edit spec's `"image"` is the first job's source (`:385`).
- `_check_entry` `:392-436`. **The defect of fix 1:** an edit is scored with `check_still(CHECK_PHOTO_PROMPT, [still_path(loc_dir, 1), png], True)` (`:404-405`), so an edit of photo 3 is compared against photo 1.
- `reason_counts` `:439-446`. `build_dataset` `:449-462` (exit 1 on `DatasetError`/`RuntimeError`/`OSError`, the abort message on `KeyboardInterrupt`/`EOFError`).
- `_build_dataset` `:465-526`. It fits the photos (`:469-472`). It renders once (`:473-480`) with step names `"generate"`/`"edit"`. It prints `=== check ===` and checks every planned still (`:482-483`). It writes the manifest (`:484-495`) with `"reference": "loc_01"` in photo mode (`:487`). It writes the contact sheet (`:496-497`). It records `dataset` and `status` (`:499-503`). It prints the table, `dataset:` and `contact sheet:` lines (`:505-512`). It prints the too-few message and exits 3 (`:513-524`), or prints `next:` (`:525-526`).
- `create` `:609-685` (seed default 0 `:634`). `_regenerate` `:688-755`: `--new-seed` is `seed + 1`, wrapping to 0 (`:725-730`); `stills/`, `captions/`, `videos/`, `manifest.json` and `contact_sheet.jpg` are deleted before the rebuild (`:748-753`).
- `_train_stills` reads only `items[*]["n"]` and `["kept"]` from `manifest.json` (`:827-828`).

**`location_lib.py`.** `MIN_SCORE = 7` `:36`, `MIN_KEEP = 12` `:37`, `TOTAL_STILLS = 24` `:38`. `_DATASET_KEYS` (exactly `kept`, `total`, `min_score`, `contact_sheet`) `:58`, enforced at `:243-251`. `_WORD_RE = [a-z0-9]+` `:61`. `description_words(description)` `:153-155`.

**`character_dataset.py`** (pinned: it is in `PIPELINE_FILES`, `tests/test_movie_ui_builder.py:220-225`, which `test_mut26` diffs against `38005c3`, `:269-299`, so **this change must not edit it**).
- `run_zimage_child(spec, char_dir, step)` `:1787-1803` and `run_edit_child` `:1806-1822`. Each writes `logs/<stamp>-<step>.{log,spec.json,report.json}` (`step_log_path` `:657-660`). Each raises `DatasetError` on a non-zero exit.
- Timeouts: `ZIMAGE_CHILD_TIMEOUT_S = 3600` `:217`, `EDIT_CHILD_TIMEOUT_S = 7200` `:181`, `AVAIL_WAIT_S = 600` `:199`, `VLM_WAIT_S = 600` `:198`. Memory floors: `GENERATE_MIN_AVAIL_GIB = 20.0` `:197`, `EDIT_MIN_AVAIL_GIB = 64.0` `:180`.
- `child_qwenedit` takes the source from `job.get("image", spec["image"])` (`:1858-1864`) and seeds each job with `job["seed"]` (`:1870`). A screened-out result is not saved (`:1873-1877`). `child_zimage` also seeds per job (`:1913`, `:1918`), and a blocked job writes no file (`:1921`; `z_image_skill.generate_image` screens before it saves, `z_image_skill.py:228-231`).

**movie-ui.** `_h_location` returns the manifest's `items` unchanged (`movie_ui_server.py:2008-2043`). `openLocation` renders one card per item, and its figcaption is built at `static/movie-ui/app.js:2333-2334`. `/files` sends `Cache-Control: no-store` (`movie_ui_server.py:2485`), so a still replaced in place is never shown stale. `location-create`/`location-regenerate` jobs need the VLM up at dispatch (`job_vlm`, `movie_ui_lib.py:421-438`). Their progress is `elapsed_s` + `last_line` (`ProgressParser.snapshot`, `movie_ui_lib.py:2339`). No job has a wall-clock limit.

**`bin/location`.** The docstring's exit-code paragraph is `:22-23`.

**Tests.** `tests/test_location_dataset.py`:
- `_Fakes` `:155-225`. Its replies are keyed by still number (`:177`); `skip` blocks by 1-based **job index** (`:190`).
- LD9 asserts that every edit is checked against `loc_01` (`:522-551`).
- LD13 asserts the manifest's exact top-level keys and item key order (`:606-638`).
- LD15 makes 11 kept with `skip=[21, 22]` (`:671-693`).

The fixture descriptions are `HARBOUR_DESC`, `TEMPLE_DESC` and `MILL_DESC` (`tests/location_testutil.py:17-23`), `CAFE_DESC` (`tests/test_location_tool.py:35-36`) and `DESC` (`tests/test_location_ui.py:30`).

### 0.2 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `location_dataset.py` | LY1-LY14 |
| G2 | `bin/location` | docstring only (LY15) |
| G3 | `static/movie-ui/app.js` | one expression (LY16) |
| G4 | `tests/test_location_dataset.py` | LYD1-LYD13; the `_Fakes`, LD9, LD13 and LD15 edits of Section 7.3 |
| G5 | `tests/test_location_ui.py` | LYU1 |

The following files are not touched: `character_dataset.py`, `location_lib.py`, `movie_ui_server.py`, `movie_ui_lib.py`, `static/movie-ui/index.html`, and every `PIPELINE_FILES` entry. `location.json`'s schema is unchanged (LY13).

### 0.3 Out of scope (queued for later)

- People-removal edits on user photos (a user photo with people is still dropped unless `--force`).
- An edit-model selection from the Seeds registry.
- Any change to `MIN_KEEP` (12) or `MIN_SCORE` (7).
- Any change to LoRA training.
- Indoor-aware photo-mode edits. `EDIT_PROMPT`, `EDIT_CONDITIONS` and `EDIT_VIEWS` are unchanged, and the indoor rule never applies in photo mode **[spec choice]**. Option A scoped fix 2 to text mode, and `EDIT_PROMPT` already says "If the place is indoors, show the time of day and the weather through any windows".
- A CLI flag or UI control to disable, extend or size the top-up.
- An explicit indoor/outdoor override field.

### 0.4 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| LYK1 | `python3 -m pytest tests/ -q -rA` from `WS` has no new failures. Before any edit, the implementer runs the suite at `98e5f64` and records the failing test ids with their messages. After the change, the failures are exactly that set, and the pass count is the baseline count plus every new test. | full run |
| LYK2 | **Outdoor byte-identity.** For an outdoor description whose round 1 keeps at least 12, the round-1 child spec, stdout, stderr, `contact_sheet.jpg` and `location.json` are identical to `98e5f64`. The manifest differs only by the added keys of LY12. | LD1, LD5 (unedited), LD14 (unedited), LYD9 |
| LYK3 | **Indoor rule.** `indoor_word(SUBWAY_DESC) == "underground"`. `indoor_word` is `None` for `HARBOUR_DESC`, `TEMPLE_DESC`, `MILL_DESC`, `CAFE_DESC` and `tests/test_location_ui.py`'s `DESC`. | LYD1 |
| LYK4 | **Bounded top-up.** At most 3 rounds and at most 3 story-server stop/restore cycles. Each top-up round renders exactly the regenerable stills, each with the LY7 seed. A user photo is never re-rendered. The rounds stop as soon as kept >= 12. | LYD6-LYD11 |
| LYK5 | **Own-source scoring.** An edit of photo k is checked with `[stills/loc_0k.png, the edit]`, in round 1 and in every top-up round. | LD9 (edited), LYD4, LYD8 |
| LYK6 | `/usr/bin/python3` (3.9) and `python3` both `py_compile` `location_dataset.py` and `bin/location`. No `match`, no PEP 604 unions, no walrus. | LYD1 (compile assertion) |
| LYK7 | `character_dataset.py` and every `PIPELINE_FILES` entry are unchanged. `test_mut26` passes with no re-baseline. | `git diff --quiet 98e5f64 -- character_dataset.py`; `test_mut26` |
| LYK8 | **Live (user-run, Section 8).** Re-creating the subway location records the kept count of every round. The target is a final kept of at least 12 (status `untrained`). The numbers are reported whether or not the target is met. | Section 8 |

### 0.5 Must-have and nice-to-have

Every LY requirement and every test in Section 7 is a must-have. Nothing else is built. None of the Section 0.3 items is built.

---

## 1. Fix 1: score each edit against its own source photo (LY1)

**LY1.** In `_check_entry`, the edit branch (`location_dataset.py:404-405`) becomes:

```python
    elif entry["source"] == "edit":
        check, unparseable = check_still(
            CHECK_PHOTO_PROMPT, [still_path(loc_dir, entry["photo"]), png], True)
```

`entry["photo"]` is the edit's 1-based source photo index, which `_plan` already sets to `((j - 1) % P) + 1` (`:377`). `CHECK_PHOTO_PROMPT` is unchanged; its "first image" is now the edit's own source. With P = 1 every edit's source is photo 1, so the checks are identical to `98e5f64`. This rule holds in every round (LY9).

---

## 2. Fix 2: indoor-aware text-mode variants (LY2-LY5)

### 2.1 The indoor rule (LY2, LY3)

**LY2.** The new constant, placed directly after `gen_prompt` (`:77-79`):

```python
# Yield spec LY2: a text location is indoors when its description has one of these words.
INDOOR_WORDS = frozenset([
    "atrium", "attic", "auditorium", "basement", "bathroom", "bedroom", "carpet", "carpeted",
    "cellar", "ceiling", "ceilings", "chandelier", "chandeliers", "classroom", "concourse",
    "corridor", "corridors", "crypt", "escalator", "escalators", "foyer", "hallway", "hallways",
    "indoor", "indoors", "interior", "interiors", "lobby", "room", "rooms", "subway", "tunnel",
    "tunnels", "underground", "wallpaper", "wallpapered"])
```
(36 words.)

**LY3.**
```python
def indoor_word(description):
    """The first word of description that is in INDOOR_WORDS (yield spec LY3), or None: a
    text location with one is drawn with INDOOR_VARIANTS."""
    for word in location_lib.description_words(description):
        if word in INDOOR_WORDS:
            return word
    return None
```

The rule compares whole words of `location_lib.description_words` (`[a-z0-9]+` on the lower-cased text). So `"ballroom"`, `"roomy"` and `"undergrounds"` never match, and `"Subway"` does. The first match in description order is returned (used in the LY5 line).

**Why this rule [spec choice].** Three candidates were weighed.
- (a) An `"indoors"` key in the VLM describe reply exists only in photo mode, and photo mode never uses `VARIANTS`. A text location has no VLM draft at all.
- (b) An explicit field or flag changes `location.json`'s exact key set (`location_lib.py:57`, `:188-283`), the CLI and the UI form.
- (c) A whole-word keyword rule on the description is deterministic and offline-testable. It needs no schema change and no extra VLM call, and it is evaluated wherever the description is.

(c) is the simplest rule that is reliable for the failing case: a subway description names "subway" or "underground". The list holds only strong interior signals. Words that often describe exteriors are left out on purpose: `station`, `platform`, `hall`, `office`, `kitchen`, `library`, `warehouse`, `garage`, `bar`, `inside`, `metro`, `door` and `window`. A miss or a false hit is fixed by rewording the description (`--regenerate --description TEXT`), which the user already controls.

**Byte-identity.** None of the five fixture descriptions contains an `INDOOR_WORDS` word (LYK3), so every existing test sees the outdoor path. Datasets already on disk are untouched until they are regenerated. An existing location whose description has an indoor word gets indoor variants on its next `--regenerate`. That is intended.

### 2.2 The indoor variants (LY4)

**LY4.** The new constants and function, placed after `indoor_word`:

```python
INDOOR_VIEWS = ("Wide establishing shot from one end", "Wide shot from a high corner",
                "Eye-level view looking along the length", "Low-angle view from near the floor",
                "Medium shot of a single detail", "Close-up of a surface texture or sign")
INDOOR_LIGHTS = ("overhead", "dim", "bright", "warm", "cool", "shadow")
INDOOR_LIGHT_PHRASES = {"overhead": "under its own overhead lights", "dim": "in dim low light",
                        "bright": "under bright even light", "warm": "in warm artificial light",
                        "cool": "in cool white light",
                        "shadow": "with deep shadows and pools of light"}
INDOOR_VARIANTS = [
    # (view, light), still n = position; view k (0-based) takes INDOOR_LIGHTS[(k + j) % 6], j 0-3
    ("Wide establishing shot from one end", "overhead"),
    ("Wide establishing shot from one end", "dim"),
    ("Wide establishing shot from one end", "bright"),
    ("Wide establishing shot from one end", "warm"),
    ("Wide shot from a high corner", "dim"),
    ("Wide shot from a high corner", "bright"),
    ("Wide shot from a high corner", "warm"),
    ("Wide shot from a high corner", "cool"),
    ("Eye-level view looking along the length", "bright"),
    ("Eye-level view looking along the length", "warm"),
    ("Eye-level view looking along the length", "cool"),
    ("Eye-level view looking along the length", "shadow"),
    ("Low-angle view from near the floor", "warm"),
    ("Low-angle view from near the floor", "cool"),
    ("Low-angle view from near the floor", "shadow"),
    ("Low-angle view from near the floor", "overhead"),
    ("Medium shot of a single detail", "cool"),
    ("Medium shot of a single detail", "shadow"),
    ("Medium shot of a single detail", "overhead"),
    ("Medium shot of a single detail", "dim"),
    ("Close-up of a surface texture or sign", "shadow"),
    ("Close-up of a surface texture or sign", "overhead"),
    ("Close-up of a surface texture or sign", "dim"),
    ("Close-up of a surface texture or sign", "bright"),
]
INDOOR_PROMPT = "%s of %s, %s, empty of people. %s."


def indoor_prompt(view, light, description):
    return INDOOR_PROMPT % (view, description, INDOOR_LIGHT_PHRASES[light], STYLE)
```

Coverage: each view appears 4 times with 4 distinct lights, and each light appears 4 times **[spec choice]**. Indoor stills carry no time of day and no weather, because an enclosed interior may show neither. The `STYLE` suffix ("photorealistic live-action film still, natural light") is kept unchanged, because the caption uses the same `STYLE` and changing it is a training change (out of scope). The check prompt (`CHECK_TEXT_PROMPT`) and the caption rule are unchanged: the VLM still tags `time_of_day` and `weather` from what it sees.

The exact prompts, with `D` the description:
- n 1: `"Wide establishing shot from one end of D, under its own overhead lights, empty of people. photorealistic live-action film still, natural light."`
- n 11: `"Eye-level view looking along the length of D, in cool white light, empty of people. photorealistic live-action film still, natural light."`
- n 24: `"Close-up of a surface texture or sign of D, under bright even light, empty of people. photorealistic live-action film still, natural light."`

### 2.3 Choosing the set (LY5)

**LY5.** In text mode, `_plan` computes `word = indoor_word(data["description"])`. It builds the 24 entries from `INDOOR_VARIANTS` with `indoor_prompt(view, light, description)` when `word` is not None. Otherwise it uses `VARIANTS` with `gen_prompt`, exactly as `:368-370`. When `word` is not None, `_build_dataset` prints this line to stdout before the first `=== generate:` line:

```
variants: indoor (the description has the word "<word>")
```

Nothing is printed for an outdoor place. The manifest records `"variant_set"` (LY12). Photo mode never calls `indoor_word`. Because the rule reads `data["description"]` at build time, `--regenerate --description TEXT` re-evaluates it.

---

## 3. Fix 3: bounded top-up rounds (LY6-LY11)

### 3.1 Constants and the seed (LY6, LY7)

**LY6.** `TOPUP_ROUNDS = 2`, placed with the other module constants after `DESCRIBE_PHOTOS` (`:39`). Rounds are numbered 1 to `1 + TOPUP_ROUNDS` (3).

**LY7. The seed formula [spec choice].** Round 1 seeds every job with `data["seed"]`, exactly as today (byte-identity). A top-up round r (2 or 3) seeds still n with:

```python
def topup_seed(seed, round_n, n):
    """The seed of still n in top-up round round_n (yield spec LY7): deterministic from the
    location seed, the round and the still, in 0..SEED_MAX."""
    digest = hashlib.sha256(("location-topup:%d:%d:%d" % (seed, round_n, n)).encode("ascii"))
    return int(digest.hexdigest()[:8], 16) & SEED_MAX
```

`SEED_MAX = 2147483647 = 0x7FFFFFFF` (`:36`), so the mask gives 0..SEED_MAX. A hash is used instead of arithmetic for two reasons. `--new-seed` is `seed + 1` (`:725-730`), so an arithmetic offset such as `seed + r` would make a top-up of seed s repeat round 1 of seed s + 1 for the same prompt. And every (round, still) pair gets an independent seed. The reference values (computed with the formula above, asserted in LYD5) are:

| seed, round, n | `topup_seed` |
|---|---|
| 0, 2, 12 | 526042623 |
| 0, 3, 12 | 543898680 |
| 0, 2, 13 | 972079275 |
| 1, 2, 12 | 1141495259 |
| 7, 2, 21 | 1210575679 |
| 2147483647, 3, 24 | 520239272 |

The prompt of a regenerated still is its round-1 prompt. Only the seed changes. An edit keeps its round-1 source photo.

### 3.2 Plan entries and the child spec (LY8)

**LY8.** `_plan(data, loc_dir)` now returns **only** the plan list. Each entry has the keys `{"n", "source", "photo", "prompt", "seed", "round"}`:
- a generated or edit entry has `"seed": data["seed"], "round": 1`;
- a photo entry has `"seed": None, "round": None`.

A new function builds the child spec for any list of generated or edit entries, from each entry's own seed:

```python
def _child_spec(data, loc_dir, entries):
    """("generate", spec), ("edit", spec) or (None, None) for the image jobs of entries."""
    if not entries:
        return None, None
    if data["source"] == "text":
        jobs = [{"prompt": e["prompt"], "output_path": still_path(loc_dir, e["n"]),
                 "seed": e["seed"], "width": WIDTH, "height": HEIGHT} for e in entries]
        return "generate", {"jobs": jobs, "loras": None}
    jobs = [{"image": still_path(loc_dir, e["photo"]), "prompt": e["prompt"],
             "output_path": still_path(loc_dir, e["n"]), "seed": e["seed"], "width": WIDTH,
             "height": HEIGHT} for e in entries]
    return "edit", {"image": jobs[0]["image"], "skill": "location_edit",
                    "model": character_dataset.EDIT_MODEL,
                    "lora_repo": character_dataset.EDIT_LORA_REPO,
                    "lora_file": character_dataset.EDIT_LORA_FILE,
                    "steps": character_dataset.EDIT_STEPS,
                    "true_cfg": character_dataset.EDIT_TRUE_CFG, "jobs": jobs}
```

Round 1 calls it with every non-photo entry in n order. The result is then key-for-key and value-for-value the spec `_plan` returns today (`:371-373`, `:382-389`), so `spec.json` bytes are unchanged.

A new function runs a round's child:

```python
def _render(child, spec, loc_dir, step):
    print("=== %s: %d stills ===" % (child, len(spec["jobs"])), flush=True)
    if child == "generate":
        _with_story_server_stopped(character_dataset.GENERATE_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_zimage_child(spec, loc_dir, step)))
    else:
        _with_story_server_stopped(character_dataset.EDIT_MIN_AVAIL_GIB, lambda: (
            character_dataset.run_edit_child(spec, loc_dir, step)))
```

Step names: round 1 is `child` (`"generate"`/`"edit"`, unchanged). Round r >= 2 is `"%s-round%d" % (child, r)`, for example `generate-round2` and `edit-round3`. The step names keep each round's log, spec and report files distinct (`step_log_path`, `character_dataset.py:657-660`).

### 3.3 The round loop (LY9, LY10)

**LY9.** `_build_dataset(data, force)` becomes the following, in this order. Lines not mentioned are unchanged.

1. `plan = _plan(data, loc_dir)`. Fit the photos exactly as `:469-472`.
2. `photo_mode = data["source"] == "photos"`. `word = None if photo_mode else indoor_word(data["description"])`. `variant_set = None if photo_mode else ("indoor" if word else "outdoor")`. When `word` is set, print the LY5 line.
3. **Round 1.** `made = [e for e in plan if e["source"] != "photo"]`. `child, spec = _child_spec(data, loc_dir, made)`. When `child` is not None, `_render(child, spec, loc_dir, child)`. Keep `generator_child = child` for the manifest's `"generator"`, computed as today at `:488-492`.
4. `print("=== check ===", flush=True)`. `items = [_check_entry(data, loc_dir, entry, force) for entry in plan]`. Items are in n order, so `items[n - 1]` is still n.
5. `rounds = [_round_summary(1, items, made)]`. `kept, sheet = _record(data, loc_dir, items, rounds, generator_child, variant_set)` (LY12).
6. **Top-up.** `for r in range(2, 2 + TOPUP_ROUNDS):`
   1. If `kept >= location_lib.MIN_KEEP`: stop the loop.
   2. `redo = [plan[k] for k, item in enumerate(items) if not item["kept"] and item["source"] != "photo"]` (n order).
   3. If `redo` is empty: print `top-up: not run; no generated or edited stills were dropped` and stop the loop.
   4. If `kept + len(redo) < location_lib.MIN_KEEP`: print `top-up: not run; %d kept + %d dropped generated or edited stills cannot reach %d` % (kept, len(redo), MIN_KEEP), and stop the loop **[spec choice: a round that cannot reach 12 is not run]**.
   5. Print `=== top-up round %d of %d: regenerating %d dropped stills with new seeds (kept %d, need %d) ===` % (r, 1 + TOPUP_ROUNDS, len(redo), kept, MIN_KEEP), with `flush=True`.
   6. For each `e` in `redo`: set `e["seed"] = topup_seed(data["seed"], r, e["n"])` and `e["round"] = r`. Delete `still_path(loc_dir, e["n"])` with `contextlib.suppress(FileNotFoundError)`. A dropped still has no caption or mp4, so nothing else is deleted. The delete matters because a job the content screen blocks writes no file (`character_dataset.py:1873-1877`, `:1921`). Without it, the old dropped image would be re-scored as if it were new.
   7. `child, spec = _child_spec(data, loc_dir, redo)`. `_render(child, spec, loc_dir, "%s-round%d" % (child, r))`.
   8. `print("=== check ===", flush=True)`. For each `e` in `redo`: `items[e["n"] - 1] = _check_entry(data, loc_dir, e, force)`.
   9. `rounds.append(_round_summary(r, items, redo))`. `kept, sheet = _record(...)` with the same arguments as step 5.
   10. Print `top-up round %d of %d: kept %d of %d (need %d)` % (r, 1 + TOPUP_ROUNDS, kept, TOTAL_STILLS, MIN_KEEP).
7. Print the table, the `dataset:` line and the `contact sheet:` line from the final `items`. Then print either the too-few message (exit 3) or the `next:` line (exit 0), exactly as `:505-526`, using `kept`, `sheet` and `reason_counts(items)`. The too-few message text is unchanged.

`_round_summary(r, items, entries)` returns `{"round": r, "made": [{"n": item["n"], "seed": item["seed"], "match_score": item["match_score"], "kept": item["kept"], "reason": item["reason"]} for each entry's item, in n order], "kept": <kept count over all 24 items>}`. Round 1's `made` lists every generated or edit still, and is `[]` for a photo location with 24 photos.

Every top-up round therefore re-renders all regenerable stills, not only as many as are missing **[spec choice]**. A round costs one story-server stop/restore cycle whatever its size, and the extras raise the chance of reaching 12. Every still that passes is kept, even when it pushes the total past 12.

**LY10. Flag interactions.**
- `--force` keeps user photos whose check shows people or is unparseable (unchanged, `:416-417`). Those count toward `kept`. `--force` does not disable or change the top-up, and a user photo is never in `redo`.
- `--regenerate` deletes the stills and rebuilds from round 1 (`:748-755`), so the top-up runs again from scratch in a regenerated build.
- `--new-seed` and `--seed N` change `data["seed"]`. Round 1 uses the new seed, and every top-up seed derives from it through LY7. The same seed reproduces the same top-up seeds.
- `--regenerate` on a trained location with `--force` is unchanged: the LoRAs are deleted before the build.

### 3.4 VLM lifecycle, time and failure (LY11)

**LY11.**
- **VLM.** Each round runs its child inside `_with_story_server_stopped`: stop the story server, wait for `GENERATE_MIN_AVAIL_GIB` (Z-Image) or `EDIT_MIN_AVAIL_GIB` (edits), run the child, restore with `--wait`, and `wait_for_vlm(VLM_WAIT_S)`. The VLM then scores that round's stills. A build with r rounds makes r stop/restore pairs (`["stop", "restore-wait"] * r` in the fakes). `vlm_ready()` is checked once, at the preflight (`_gates`, `:590-593`), as today.
- **Time budget.** No overall job budget is added **[spec choice]**. Each round's child keeps its own watchdog (`ZIMAGE_CHILD_TIMEOUT_S` 3600 s, `EDIT_CHILD_TIMEOUT_S` 7200 s), and each round's memory and VLM waits keep `AVAIL_WAIT_S`/`VLM_WAIT_S` (600 s each). In the worst case a build therefore takes about 3 times today's wall time, plus 2 VLM reloads. movie-ui jobs have no wall-clock limit, so nothing changes there.
- **Failure.** A `DatasetError`/`RuntimeError`/`OSError` in a top-up round exits 1 through `build_dataset` (`:455-457`). An interrupt prints the existing abort message and exits 1 (`:458-462`; 130 from a signal via `bin/location`), and `_with_story_server_stopped` restores the server detached. `manifest.json`, `contact_sheet.jpg` and `location.json` stay as `_record` last wrote them, at the end of the last completed round: status `dataset`, `dataset.kept` = that round's kept **[spec choice]**. The dropped stills that were deleted for the failed round may then be missing or hold an unchecked image. They are not kept, so they have no caption or mp4 and training never reads them; the remedy is `--regenerate`, as the abort message says.

---

## 4. Record (LY12, LY13)

**LY12. `_record` and the manifest.** A new function holds the writes of `:484-503`:

```python
def _record(data, loc_dir, items, rounds, child, variant_set):
    """Write manifest.json, contact_sheet.jpg and location.json for items after a round
    (yield spec LY12); return (kept, contact sheet path)."""
```

It writes `manifest.json` (`json.dump(manifest, f, indent=2)`, as today) with the top-level keys in this order:

`{"source", "trigger", "description", "seed", "min_score", "reference", "generator", "variant_set", "rounds", "items"}`

- `"reference"` is `"source photo"` in photo mode (each edit is checked against `stills/loc_%02d.png % item["photo"]`, LY1) and `None` in text mode **[spec choice; was "loc_01"]**. No code reads this key (`grep` at `98e5f64`).
- `"generator"` is computed exactly as `:488-492` from the round-1 child.
- `"variant_set"` is `"indoor"`, `"outdoor"` or `None` (photo mode).
- `"rounds"` is the list of `_round_summary` dicts, length 1-3.
- Each item has the 12 existing keys in their existing order, then `"seed"` (int, or `None` for a user photo), then `"round"` (1-3, or `None` for a user photo). Both describe the image on disk. `_check_entry`'s item literal (`:394-396`) gains `"seed": entry["seed"], "round": entry["round"]` after `"caption": None`; nothing else in `_check_entry` changes except LY1.

It then writes the contact sheet with `write_contact_sheet(items, os.path.join(loc_dir, "stills"), sheet, rounds=len(rounds))`. Finally it sets `data["dataset"] = {"kept", "total", "min_score", "contact_sheet"}` and `data["status"]` exactly as `:499-502`, and calls `location_lib.write_location(data)`.

**LY13. Backwards compatibility.**
- The `location.json` schema is unchanged. `dataset` keeps exactly its four keys (`location_lib.py:58`). The rounds are a build detail and belong in the manifest, while `location.json`'s exact-key validation (`:243-251`) would need a `schema_version` bump to hold them.
- An existing `manifest.json` without `variant_set`, `rounds`, `seed` or `round` stays valid for every reader. `_train_stills` reads only `n` and `kept` (`:827-828`). `_h_location` passes the items through (`movie_ui_server.py:2024-2026`). `cell_label` and `app.js` read `round` with a presence check (LY14, LY16).
- An existing dataset is not rebuilt. It changes only on `--regenerate`.

---

## 5. Contact sheet, CLI text and the Locations tab (LY14-LY16)

**LY14. Contact sheet.**
- `write_contact_sheet(items, stills_dir, out_path, rounds=1)`. The banner is `"kept %d of %d (need %d)" % (...)` as today, plus `" after %d rounds" % rounds` when `rounds > 1`. Example: `kept 12 of 24 (need 12) after 2 rounds`.
- `cell_label(item)` adds `round_text = " r%d" % item["round"] if isinstance(item.get("round"), int) and not isinstance(item.get("round"), bool) and item["round"] > 1 else ""` and returns `"%02d %s%s %s %s" % (item["n"], item["source"][0].upper(), round_text, score, verdict)`. Examples: `12 G r2 s8 kept`, and `12 G s8 kept` for round 1 or an item without `round`.
- Every cell shows the final image and verdict: the sheet is rewritten after every round (LY12).

**LY15. `bin/location` docstring.** Lines `:22-23` become:

```
Exit codes: 0 success, 1 runtime failure, 2 argument or precondition failure, 3 create kept fewer
than 12 stills. When fewer than 12 are kept, create regenerates the dropped generated or edited
stills (never your photos) with new seeds, for up to 2 more rounds.
```

The `location_dataset.py` module docstring gains this sentence directly after `... and a 1-frame mp4.` (`:8`): `When fewer than 12 are kept, the dropped generated or edited stills are regenerated with new seeds for up to 2 more rounds (docs/superpowers/specs/2026-11-02-location-yield-design.md).` The argparse help and descriptions are unchanged, so LT1 is unaffected.

**LY16. movie-ui Locations tab.** At `static/movie-ui/app.js:2333`, the first element of the figcaption array, `item.source`, becomes exactly:

```js
item.source + (typeof item.round === "number" && item.round > 1 ? " (round " + item.round + ")" : "")
```

A still from a top-up round then reads, for example, `generated (round 2); score 8; no people; ...; kept`. A round-1 still, and every item of an old manifest, reads as today. Nothing else changes:
- the Jobs table's `last_line` shows the LY9 progress lines as they stream;
- `/files` is `no-store`, so a replaced still is fetched fresh;
- the contact sheet image carries the LY14 banner.

---

## 6. Messages and exit codes

| Condition | Stream | Exact text | Exit |
|---|---|---|---|
| text location with an indoor word | stdout | `variants: indoor (the description has the word "W")` | - |
| round 1 kept >= 12 | - | no new line | 0 |
| a top-up round starts | stdout | `=== top-up round R of 3: regenerating D dropped stills with new seeds (kept K, need 12) ===`, then `=== generate: D stills ===` or `=== edit: D stills ===`, then `=== check ===` | - |
| a top-up round ends | stdout | `top-up round R of 3: kept K of 24 (need 12)` | - |
| kept < 12, no regenerable still | stdout | `top-up: not run; no generated or edited stills were dropped` | then 3 |
| kept + regenerable < 12 | stdout | `top-up: not run; K kept + D dropped generated or edited stills cannot reach 12` | then 3 |
| fewer than 12 after the last round | stderr | the unchanged [LOC] L5.1 too-few message, from the final items | 3 |
| 12 or more after a top-up round | stdout | the unchanged table, `dataset:`, `contact sheet:`, `next:` lines | 0 |
| child failure, timeout, memory or VLM wait in a top-up round | stderr | the unchanged [LOC] L5.1 texts | 1; the record of the last completed round |
| interrupt in a top-up round | stderr | the unchanged abort message | 1 (130 from a signal) |

The status rule (`untrained` when kept >= 12, else `dataset`) and the exit codes 0/1/2/3 are unchanged.

---

## 7. Tests

### 7.1 Rules

The rules are the ones `tests/test_location_dataset.py`'s docstring states (`:1-14`), via the existing `env` fixture (`seu.set_story_env`):
- pytest only;
- every library and `HOME` under `tmp_path`;
- never the real HOME;
- no real model, render or Z-Image/Qwen/VLM process, and no server contact;
- the children are stubbed at the process boundary (`character_dataset.run_zimage_child`/`run_edit_child`, `vlm_call`, `story_server`, `restore_story_server`, `wait_for_vlm`, `wait_for_avail`, `vlm_ready`, `busy_process`, `free_gib`, `edit_models_missing`) by `_Fakes`.

Real ffmpeg/ffprobe wrap kept stills, as today. `SUBWAY_DESC` is a module constant in `tests/test_location_dataset.py`:
```python
SUBWAY_DESC = ("a dimly lit underground new york subway platform with white tiled walls, green steel "
               "columns, mosaic station name signs, a yellow edge strip and dark track beds")
```
(27 words; it passes `validate_description`.) The new tests sit under the header `# --- LY: dataset yield (docs/superpowers/specs/2026-11-02-location-yield-design.md) ---` at the end of the file. The file docstring's first sentence gains `, and the yield spec LYD1-LYD13`.

### 7.2 `_Fakes` extension (backward compatible)

`_Fakes.__init__` gains three keyword arguments, `skip_n=(), rounds=None, child_error_at=None`, and one attribute `existed = []`. The defaults reproduce today's behaviour exactly.
- `skip_n`: still numbers whose job is blocked (no file written, status `"blocked"`) in **every** child call. The still number comes from the job's `output_path` with `re.search(r"loc_(\d+)\.png$", ...)`. `skip` keeps its job-index meaning.
- `rounds`: a list of reply dicts (each shaped like `replies`). A check call uses `rounds[min(max(len(fakes.child_specs), 1), len(rounds)) - 1]` instead of `replies`, so the replies follow the number of child calls made so far, and the last dict repeats. When `rounds` is None, `replies` is used as today.
- `child_error_at`: when not None, `child_error` is raised only on that 1-based child call. When None, it is raised on every call, as today.
- `existed`: each child call appends `[os.path.exists(job["output_path"]) for job in spec["jobs"]]` before writing anything.

### 7.3 Existing tests that change (only these)

| Test | Edit |
|---|---|
| LD9 (`:522-551`) | `ref` is per edit: the expected checks for n in `count+1..24` use `["file:" + os.path.join(stills, "loc_%02d.png" % (((n - count - 1) % count) + 1)), "file:" + os.path.join(stills, "loc_%02d.png" % n)]`; the separate `ref` variable is removed. All other assertions stay. |
| LD13 (`:606-638`) | Text part: the top-level comparison excludes `"items"` and `"rounds"` and adds `"variant_set": "outdoor"`; then assert `[r["round"] for r in manifest["rounds"]] == [1]` and `manifest["rounds"][0]["kept"] == 23`. `first` and `blocked` gain `"seed": 4, "round": 1`. Photo part: `(manifest["source"], manifest["reference"], manifest["generator"])` expects `"source photo"`; add `manifest["variant_set"] is None`; `photo["seed"], photo["round"]` are `None, None`; `edit["seed"], edit["round"]` are `0, 1`; the `list(edit)` order gains `"seed", "round"` at the end. |
| LD15 (`:671-693`) | `skip=[21, 22]` becomes `skip_n=[21, 22]` so that 21 and 22 stay blocked in every round. The expected message and every other assertion are unchanged (each round repeats the same failures, so the final reasons are the same). |

LD1, LD2, LD5, LD11, LD14, LD16, LD17 and LD24, and every test in the other `tests/test_location_*.py` files, pass unedited.

### 7.4 New tests

| ID | Covers (exact assertions) |
|---|---|
| LYD1 | **Indoor rule (LYK3, LYK6).** `ld.INDOOR_WORDS` equals the LY2 literal (36 words). `indoor_word(SUBWAY_DESC) == "underground"`. `indoor_word` is None for `lt.HARBOUR_DESC`, `lt.TEMPLE_DESC`, `lt.MILL_DESC`, the `CAFE_DESC` literal of `tests/test_location_tool.py:35-36` and the `DESC` of `tests/test_location_ui.py:30` (the last two copied into the test). For each word w in `INDOOR_WORDS`, `indoor_word("a quiet " + w + " with old fittings")` is w. `indoor_word` is None for `"a grand ballroom with gilded mirrors"`, `"a roomy yard with old sheds"` and `"an undergrounds market square"`. `indoor_word("a Subway entrance on a corner")` is `"subway"`. `py_compile` of `location_dataset.py` and `bin/location` under `/usr/bin/python3` (skipped when absent) and `sys.executable`. |
| LYD2 | **Indoor literals.** `INDOOR_VIEWS`, `INDOOR_LIGHTS`, `INDOOR_LIGHT_PHRASES` and `INDOOR_VARIANTS` equal the LY4 literals written out in the test. Each view appears 4 times with 4 distinct lights; each light appears 4 times. `indoor_prompt(*(ld.INDOOR_VARIANTS[k] + (SUBWAY_DESC,)))` for k 0, 10 and 23 equals the three LY4 example strings with D = `SUBWAY_DESC`. `ld.VARIANTS` is unchanged (LD1 covers it). |
| LYD3 | **Indoor create.** `ld.create(_create_args(name="nyc-subway", description=SUBWAY_DESC, seed=7))` with `_Fakes` → exit 0. The single child spec's jobs equal `[{"prompt": ld.indoor_prompt(view, light, SUBWAY_DESC), "output_path": .../loc_%02d.png % n, "seed": 7, "width": 1024, "height": 640} for n, (view, light) in enumerate(ld.INDOOR_VARIANTS, 1)]`, with step `"generate"`. stdout contains `variants: indoor (the description has the word "underground")\n` before `=== generate: 24 stills ===`. `manifest["variant_set"] == "indoor"`. The checks use `CHECK_TEXT_PROMPT` with `SUBWAY_DESC`. A second create with `lt.HARBOUR_DESC` has `variant_set "outdoor"` and no stdout line starting `variants:`. |
| LYD4 | **Own-source scoring (LYK5).** A photo create with P = 3, `lt.MILL_DESC`, all PASS: for every edit n in 4..24, the check images are `["file:" + stills/loc_%02d.png % (((n - 4) % 3) + 1), "file:" + stills/loc_%02d.png % n]`, so edit 5 is checked against photo 2 and edit 6 against photo 3. The prompt is `CHECK_PHOTO_PROMPT`. `manifest["reference"] == "source photo"`. |
| LYD5 | **Seed formula.** `ld.topup_seed` returns the six LY7 table values. For seed 0, the 48 values for r in (2, 3) and n in 1..24 are pairwise distinct and all in `0..2147483647`. `ld.TOPUP_ROUNDS == 2`. |
| LYD6 | **Top-up reaches 12 in round 2.** Text create `harbour-street`, `lt.HARBOUR_DESC`, seed 5, `rounds=[{n: score 3 for n in 12..24}, {n: score 3 for n in 13..24}]` → exit 0, status `untrained`, `dataset.kept == 12`. `[step for _s, step in fakes.child_specs] == ["generate", "generate-round2"]`. Round 2's jobs are `[{"prompt": <the round-1 prompt of n>, "output_path": loc_n, "seed": ld.topup_seed(5, 2, n), "width": 1024, "height": 640} for n in 12..24]`. `fakes.existed[1] == [False] * 13` (the dropped stills were deleted first). `fakes.server_calls == ["stop", "restore-wait", "stop", "restore-wait"]`. The checks are 24 round-1 checks, then 13 checks for n 12..24 in order. A wrapper around the round-2 child asserts `len(fakes.checks()) == 24` and `fakes.server_calls == ["stop", "restore-wait", "stop"]` when it starts (round 1 scored before round 2 rendered). stdout contains, in this order: `=== top-up round 2 of 3: regenerating 13 dropped stills with new seeds (kept 11, need 12) ===`, `=== generate: 13 stills ===`, `=== check ===`, `top-up round 2 of 3: kept 12 of 24 (need 12)`, then the `dataset: 12/24` line and the `next:` line. `manifest["rounds"]` equals the two `_round_summary` dicts written out (round 1: 24 `made`, n < 12 kept with score 9, n >= 12 `"score 3"`, `kept` 11; round 2: 13 `made` with the top-up seeds, n 12 kept, `kept` 12). Item 12 has `("seed", "round") == (ld.topup_seed(5, 2, 12), 2)`, item 13 has `(ld.topup_seed(5, 2, 13), 2)` and is not kept, item 1 has `(5, 1)`. `captions/` holds exactly `loc_01.txt`..`loc_12.txt`. |
| LYD7 | **Top-up exhausted.** As LYD6 with `rounds=[{n: score 3 for n in 12..24}]` (the dict repeats) → exit 3. Steps are `["generate", "generate-round2", "generate-round3"]`, and round 3 regenerates n 12..24 with `topup_seed(5, 3, n)`. `server_calls` is `["stop", "restore-wait"] * 3`. `[r["kept"] for r in manifest["rounds"]] == [11, 11, 11]`. The last stderr line is `Error: only 11/24 stills kept (need 12): 13 score below 7; the dataset is kept in <dir>; run bin/location create harbour-street --regenerate --new-seed, or --regenerate --description TEXT with a clearer description`. The contact-sheet banner (captured by patching `ImageDraw.ImageDraw.text`, as LD14) is `kept 11 of 24 (need 12) after 3 rounds`. No fourth child call happens. |
| LYD8 | **Photo-mode top-up.** P = 3, `lt.MILL_DESC`, seed 2, `rounds=[{1: people visible, n: score 5 for n in 4..15}, {1: people visible}]` → round 1 keeps 11 (photos 2 and 3, edits 16..24), and round 2 regenerates edits n 4..15 only (photo 1 is not regenerated) → kept 23, exit 0. Round 2's spec has step `"edit-round2"`, `skill "location_edit"` and `image` = `loc_01.png` (the first job's source). Its jobs are `[{"image": loc_%02d % (((n - 4) % 3) + 1), "prompt": ld.EDIT_PROMPT % ((ld.EDIT_VIEWS[n - 4],) + ld.EDIT_CONDITIONS[n - 4]), "output_path": loc_n, "seed": ld.topup_seed(2, 2, n), "width": 1024, "height": 640} for n in 4..15]`. Round-2 checks use `CHECK_PHOTO_PROMPT` with the own-source image. Item 1 is `kept False`, `round None`, `seed None`. Repeating the create with `force=True` (new name) → photo 1 kept by force, round 1 keeps 12, one child call, no `top-up` text in stdout. |
| LYD9 | **When no round runs (LYK2).** (a) P = 24 photos, `replies={n: people visible for n in 1..13}` → kept 11, no child call, `server_calls == []`, stdout has `top-up: not run; no generated or edited stills were dropped`, exit 3. (b) P = 20, `replies` people visible for n 1..14 and score 3 for n 21, 22 → kept 8, stdout has `top-up: not run; 8 kept + 2 dropped generated or edited stills cannot reach 12`, one child call, exit 3. (c) The LD5 create (20 kept): stdout contains no `top-up` and no `variants:`, and `manifest["rounds"]` has one entry. |
| LYD10 | **Blocked in a top-up round.** Text create, `skip_n=[12]`, `rounds=[{n: score 3 for n in 13..24}, {}]` → round 1: n 12 blocked, 13..24 score 3, kept 11; round 2: n 12 blocked again, 13..24 pass, kept 23, exit 0. Item 12: `kept False`, `reason "blocked by the content screen"`, `round 2`, `seed topup_seed(0, 2, 12)`. `stills/loc_12.png` does not exist. `fakes.existed[1]` is all False. |
| LYD11 | **Failure and interrupt in round 2.** (a) `rounds=[{n: score 3 for n in 12..24}]`, `child_error=DatasetError("Z-Image child process exited -9; log: /x/logs/g.log")`, `child_error_at=2` → exit 1. `server_calls == ["stop", "restore-wait", "stop", "restore-wait"]`. The last stderr line is `Error: Z-Image child process exited -9; log: /x/logs/g.log`. The record has status `dataset`, `dataset.kept == 11`, and `len(manifest["rounds"]) == 1`. (b) The same with `child_error=KeyboardInterrupt()` → exit 1. `server_calls` ends `["stop", "restore"]`, and the last stderr line is the abort message of LD17. |
| LYD12 | **Seeds follow `--seed`/`--new-seed`.** Text create, seed 5, `rounds=[{n: score 3 for n in 12..24}]` → round-2 seeds are `[topup_seed(5, 2, n) for n in 12..24]`. Then `ld.create(_create_args(regenerate=True, new_seed=True))` with the same reply shape → record seed 6, round-1 jobs seeded 6, round-2 seeds `[topup_seed(6, 2, n) ...]`, round-3 seeds `[topup_seed(6, 3, n) ...]`. Two creates with the same seed (different names) produce identical round-2 seed lists. |
| LYD13 | **Labels and banner.** `cell_label({"n": 12, "source": "generated", "match_score": 8, "kept": True, "reason": None, "round": 2}) == "12 G r2 s8 kept"`. With `"round": 1`, with `"round": None` and with no `round` key, it is `"12 G s8 kept"`. `write_contact_sheet(items, dir, out, rounds=3)` draws the banner `kept K of 24 (need 12) after 3 rounds`, and with `rounds=1` it draws `kept K of 24 (need 12)`. |
| LYU1 | **Locations tab.** `static/movie-ui/app.js` contains the LY16 expression exactly once (`app.count('item.source + (typeof item.round === "number" && item.round > 1 ? " (round " + item.round + ")" : "")') == 1`), and still contains `item.match_score === null ? "score -" : "score " + item.match_score` once. |

---

## 8. Live check (the user runs it on the macstudio host)

Agents never run this: it renders, and it needs the macstudio host, which agents must not touch. The user runs it after pushing `location-yield` and checking it out on macstudio. `<OLD>` is the user's subway location (11 kept); `<NEW>` is `subway-yield`.

1. **Record the baseline.** `bin/location show <OLD>` → note `source`, `description`, `seed`, `dataset.kept` (expected 11), and the photo paths (photo mode). Save the old manifest's kept count: `python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(sum(i['kept'] for i in m['items']))" generated/locations/<OLD>/manifest.json`.
2. **Re-create with the same inputs.**
   - Text mode: `bin/location create subway-yield --description "<the same description>" --seed <the same seed>`.
   - Photo mode: `bin/location create subway-yield --photo <p1> ... --photo <pK> --description "<the same description>" --seed <the same seed>`, with the photos in the original order. Passing the description skips a new VLM draft, so only the yield fixes differ.
   - Then run `echo "exit $?"`.
3. **Record from stdout.**
   - Text mode: whether the `variants: indoor (...)` line appears, and its word.
   - Each `=== top-up round R of 3 ... (kept K, need 12) ===` line.
   - Each `top-up round R of 3: kept K of 24` line.
   - Any `top-up: not run` line.
   - The final `dataset: K/24` line and the exit code.
   - The wall time of the command.
4. **Record from the manifest.** `python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(m['variant_set']); [print(r['round'], len(r['made']), r['kept']) for r in m['rounds']]" generated/locations/subway-yield/manifest.json` prints the variant set, then one `round made kept` line per round.
5. **Record each round's dropped edits (photo mode; checks LYA1).** `python3 -c "import json,sys; m=json.load(open(sys.argv[1])); it={i['n']: i for i in m['items']}; [print(r['round'], e['n'], it[e['n']]['photo'], e['reason'], it[it[e['n']]['photo']]['people_visible']) for r in m['rounds'] for e in r['made'] if not e['kept'] and it[e['n']]['source'] == 'edit']" generated/locations/subway-yield/manifest.json` prints one `round n photo reason source-people` line for every edit a round dropped. `reason` is that round's verdict. `source-people` is the `people_visible` that the photo check recorded for the edit's own source photo: `True`, `False`, or `None` when that check was unparseable. Report every line. After LYA1, a `people visible` drop should not track a source photo with `True`. If most `people visible` drops have source-people `True`, the reference photo is still steering the people check, and LYA1 has not fixed it. Text mode prints nothing.
6. **Attribute the gain.** Round 1's kept count measures fixes 1 and 2 against `<OLD>`'s 11. Each later round measures fix 3. In photo mode, also compare the scores of edits whose `photo` is not 1 between `<OLD>` and `<NEW>`, which isolates fix 1.
7. **Look.** Open `generated/locations/subway-yield/contact_sheet.jpg`. The banner says `after R rounds` when a top-up ran, and the regenerated cells are labelled `r2`/`r3`. The movie-ui Locations tab detail shows `generated (round 2)` (or `edit (round 2)`) on those cards.
8. **Pass bar (LYK8).** The run ends with exit 0, status `untrained` and kept >= 12, in at most 3 rounds. Report the per-round numbers either way. If the run ends 3, report the reason counts from the too-few line. They decide whether the queued work (people-removal edits, an edit-model choice) is next.
9. **Clean up (optional).** Keep `<NEW>` if it is better, or delete `generated/locations/subway-yield/`. Its trigger stays registered either way (triggers are never reused, [LOC] 2.4).

---

## 9. Decisions made by the spec author

1. Indoor rule: whole-word match of the description against the 36-word `INDOOR_WORDS` (LY2, LY3), text mode only. A VLM flag and an explicit field were rejected (Section 2.1).
2. Indoor variants: 6 views × 4 of 6 lighting phrases, with no time of day or weather in the prompt; `STYLE` unchanged (LY4).
3. A `variants: indoor (...)` stdout line, printed for indoor places only (LY5).
4. Photo-mode edits stay outdoor-agnostic (Section 0.3).
5. Seed: round 1 = `data["seed"]`; round r >= 2 = `sha256("location-topup:<seed>:<r>:<n>")[:8] & 0x7FFFFFFF` (LY7).
6. Regenerated stills keep their round-1 prompt and source photo; only the seed changes (LY7).
7. Each top-up round re-renders every regenerable still, not just the shortfall (LY9).
8. A round that cannot reach 12 (kept + regenerable < 12) is skipped with a line (LY9 step 6.4).
9. The dropped still's file is deleted before it is regenerated (LY9 step 6.6).
10. Step names `<child>-round<r>` (LY8).
11. The manifest, contact sheet and `location.json` are written after every round. A failure keeps the last completed round's record (LY11, LY12).
12. Manifest: `variant_set`, `rounds` (per-round `made` with seed, score, verdict, and the cumulative kept), per-item `seed` and `round`. `reference` becomes `"source photo"` in photo mode (LY12).
13. `location.json` schema unchanged (LY13).
14. Contact sheet: `" after R rounds"` banner suffix and an `rN` cell tag for rounds >= 2 (LY14).
15. Locations tab: `(round N)` after the source on top-up cards; nothing else (LY16).
16. No new CLI flag, no UI control, no overall time budget; `TOPUP_ROUNDS = 2` is a module constant (LY6, LY11).
17. The too-few message and all exit codes are unchanged (Section 6).

## 9a. Amendments from the final review

The whole-branch review of `98e5f64..9cf85ad` found no Critical issue, one Important issue and five minor ones. The user's ruling takes the Important issue and three minors into one fix wave. LYA1-LYA3 below are binding, and each one supersedes the sentences of this spec that it names. LYA4 was ruled conditionally and is dropped. Line numbers here cite `9cf85ad`.

**LYA1. The photo-mode check judges the four tags on the candidate alone (Important 1).**
- *Defect.* `CHECK_PHOTO_PROMPT` (`location_dataset.py:216-223`) sends two images: the edit's own source photo (LY1), then the candidate. It ends with the shared `_KEYS`, which asks whether a person is visible "anywhere in the image". With two images that is ambiguous. A subway source photo almost always shows people, so a clean edit can be dropped as `people visible` because of its reference photo. Such a failure does not depend on the seed, so the top-up rounds repeat it, at up to about 3 times the edit time.
- *Change.* A new constant `_PHOTO_KEYS` sits directly before `CHECK_PHOTO_PROMPT`. It judges `people_visible` on the second image (the candidate) only, and says that people in the first image (the reference) do not count. It also says that `shot`, `time_of_day` and `weather` describe the candidate **[spec choice]**. Those three feed the kept edit's caption, and they have the same two-image ambiguity. The allowed values are copied unchanged from `_KEYS`. `CHECK_PHOTO_PROMPT` ends with `+ _PHOTO_KEYS` instead of `+ _KEYS`. Everything before that is byte-identical, including the `match_score` comparison against the first image.
- *Unchanged.* `_KEYS`, `CHECK_TEXT_PROMPT`, `TAG_PROMPT`, `CHECK_RETRY`, `SCORE_RETRY_EXTRA`, `validate_location_check` and the reply format (five keys) are unchanged. A text-mode build therefore sends the same bytes as before, so LYK2 holds. A user photo is still tagged with the one-image `TAG_PROMPT`. The candidate is still checked for people, so no edit with people can be kept.
- *Supersedes.* LY1's sentence "`CHECK_PHOTO_PROMPT` is unchanged", and LD2's photo-prompt literal in the 7.3 sentence "LD2 ... pass[es] unedited".

**LYA2. A top-up round first re-checks for a running render (Minor 1).**
- *Defect.* `character_dataset.busy_process()` runs only at the preflight (`_gates`, `:743`). A top-up round can start tens of minutes later, after another job has started a render or a training run.
- *Change.* In LY9 step 6, after step 6.4 (the cannot-reach skip) and before step 6.5 (the round header), `_build_dataset` calls `character_dataset.busy_process()`. The function is reused, so there is no copy of its logic. When it returns `(pid, cmdline)`, `_build_dataset` prints `top-up: not run; a render or training process is running (pid PID: CMDLINE)` to stdout, with plain `print` like the other `top-up: not run` lines. Then it stops the loop. Nothing is deleted or rendered, and the record stays as `_record` last wrote it, exactly as for the other two skips. The build goes on to LY9 step 7, so the exit code is 3, from the too-few message. The check runs only when a round would otherwise start. A build whose round 1 keeps at least 12 calls `busy_process` once, at the preflight, as before.
- *Supersedes.* The new row is added to the Section 6 table: kept + regenerable >= 12, but a render or training process is running → stdout `top-up: not run; a render or training process is running (pid PID: CMDLINE)`, then exit 3.

**LYA3. The abort message is accurate (Minor 2).**
- *Defect.* The interrupt text "the stills made so far are kept in DIR" is no longer true in a top-up round. LY9 step 6.6 has already deleted that round's dropped stills, so some of them are missing, and others have been re-rendered but never checked.
- *Change.* `build_dataset`'s interrupt message becomes exactly `Error: aborted; the dataset in DIR is incomplete (a still of the unfinished round may be missing or unchecked); run bin/location create NAME --regenerate to start again`, on stderr with its leading newline, exit 1 as before (130 from a signal via `bin/location`). This one text is true in round 1 (stills not yet rendered or not yet checked) and in every top-up round.
- *Supersedes.* The Section 6 row "interrupt in a top-up round ... the unchanged abort message". It also supersedes the interrupt text of [LOC] Section 2.12 step 8 and of its Section 6.1 error table (L5.1), for every build this code makes. [LOC] itself is not edited. LD17 and LYD11(b) pin the new text.

**LYA4. Atomic manifest write (Minor 5): dropped.** The ruling was to use an existing atomic JSON writer that `location_dataset.py` can already import, and to drop the item if none exists. None exists. `location_lib.write_location` (`location_lib.py:300-313`) writes to a temporary file and then calls `os.replace`, but it hard-codes `location.json`'s path and validates the data as a location record, so it cannot write `manifest.json`. `character_dataset.py` has no JSON writer that uses `os.replace`. Its `os.replace` calls (`:1452`, `:1728`, `:1735`) move LoRA files. Adding a writer would touch `location_lib.py`, which Section 0.2 forbids. `manifest.json` therefore stays a plain `json.dump`, rewritten up to 3 times per build (open question 5).

**Tests.** LYD14 pins LYA1 and LYD15 pins LYA2. LD2 (the photo prompt), LD17 and LYD11(b) (the abort text) are re-baselined. The test file docstring's `LYD1-LYD13` becomes `LYD1-LYD15`. The suite gains 2 new test IDs, 21 over the `98e5f64` baseline.

**Parked by the final review, not changed:** the outdoor `TIMES`/`WEATHERS` tags of indoor stills (open question 3); no movie-ui warning that a job with a top-up runs longer; the Task 2 review's `INDOOR_WORDS` findings (open question 4).

## 10. Open questions

None block implementation. These are for after the live check:
1. If the subway location is a photo location, fix 2 does not touch it. Should a later change apply the indoor rule to `EDIT_CONDITIONS`, for example by replacing the weather and season conditions with lighting conditions for indoor places?
2. If the live check shows that the indoor rule misses a real indoor place (or hits an outdoor one), should `INDOOR_WORDS` grow, or should an explicit override field be added (a `location.json` schema bump)?
3. **Indoor stills get outdoor tags.** Every check, including a check of an `INDOOR_VARIANTS` still, demands `time_of_day` from `TIMES` and `weather` from `WEATHERS` (`_KEYS`). A windowless interior has neither. If the VLM answers `n/a`, `indoor` or `artificial light`, the reply fails `validate_location_check`. After `CHECK_ATTEMPTS` such replies the still is dropped as `unparseable` and counts against `MIN_KEEP`. Should indoor values be added, or should these keys be allowed empty for indoor places? Either way the caption format changes, so the choice is the user's. The live check's reason counts show whether this happens: look for `unparseable` drops on an indoor location.
4. **`INDOOR_WORDS` false hits and misses (from the Task 2 review).**
   - *False hits*: words that also occur in outdoor descriptions. The review listed `room`, `tunnel`, `subway entrance`, `underground station entrance`, `ceiling` ("a ceiling open to the sky"), `lobby` and `carpet`. Examples are a road tunnel mouth, a street-level subway entrance and "a carpet of moss".
   - *Misses*: indoor descriptions that do not match. Missing plurals such as `subways`, `lobbies` and `basements`. Hyphen splits: `description_words` splits on every non-alphanumeric character, so "sub-way" becomes `sub` and `way`. And `metro`/`tube` stations.
   - Should the list gain the plurals and the metro/tube words, and should some hits be removed? That would amend LY2 and LYD1's 36-word literal.
5. **Atomic manifest writes (LYA4, dropped).** Should `location_lib` gain a general atomic JSON writer, which `write_location` and `_record` would then share? It would lift Section 0.2's ban on touching `location_lib.py`. Until then, an interrupt or crash while `manifest.json` is being written can leave a truncated file. `--regenerate` deletes it and rebuilds.
