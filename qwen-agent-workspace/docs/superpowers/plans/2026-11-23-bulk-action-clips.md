# Bulk Action Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train one action (motion) LoRA from a whole folder of clips. Each clip's caption comes from its file name (`<n>_<n>_<moves>.<ext>`, giving `"<trigger>: <m1>, then <m2>, ..."`). This works from the CLI (`bin/action create --dir DIR`, `bin/action scan DIR`) and from the movie UI (a Folder field, a Preview button backed by a read-only `POST /api/actions/preview`, and Create with `dir`). At the scale of the user's several hundred clips, the contact sheet is sampled, the disk check scales, stale clips are cleaned up, progress lines are printed and the preprocess timeout scales.

**Architecture:**
- There is one parser, in `action_lib.py` (stdlib only): `parse_clip_name`, `scan_clip_dir` and `clip_caption`. Every surface reaches it through `bin/action`.
  - `create --dir` scans the folder in `action_dataset.create` and hands `build_dataset` a captions list, the source dir and the skipped list.
  - The new `bin/action scan` prints the scan as JSON.
- The server never imports `action_lib` (spec F11). Preview runs `bin/action scan` through `lib.run_light`, the same way `list` and `show` already work. Create queues `bin/action create --dir`.
- `build_dataset(captions=None)` keeps today's trigger-only captions byte for byte.

**Tech Stack:**
- `python3` = `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (3.13.0, pytest 8.3.4, PIL 12.3.0), run as `python3 -m pytest -q -p no:cacheprovider <files>` from `WS`. This is how every existing test file says it is run, and how the planning replay ran.
- `/usr/bin/python3` (3.9.6) for the 3.9 checks.
- ffmpeg/ffprobe at `/opt/homebrew/bin` (the ffmpeg tests skip without them).
- `node` at `/opt/homebrew/bin/node` for `node --check`.
- Stdlib, plus PIL through `action_dataset`. No new dependency.

**Spec:** `qwen-agent-workspace/docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md`, commit `7e4258a` on branch `bulk-action-clips` (base `b6bcb9b`). The user approved it with defaults Q1-Q5 kept:
- Q1: `MAX_DIR_CLIPS = 1000`.
- Q2: `max(1800, 600 + 15n)`.
- Q3: no train-host disk check.
- Q4: stale cleanup on both paths.
- Q5: hidden files are listed as skipped.

Every Edit below is located by its old text, never by a line number.

**Planning replay (done while writing this plan).** Every Edit and new file below was applied by script to a scratch copy of `7e4258a`, outside the worktree, and run:

| Stage | Result |
|---|---|
| Task 1 red | `19 failed` |
| Task 1 after `action_lib` + `action_dataset` | `3 failed, 16 passed` |
| Task 1 green | `19 passed`; the Task 1 relevant set gives `66 passed` |
| Task 2 red | `9 failed, 4 passed` |
| Task 2 after lib + server | `1 failed, 12 passed` |
| Task 2 green | `13 passed` |
| UI test set at the final state | `25 failed, 496 passed, 2 skipped` |

The 25 UI failures are exactly the set that fails at base in the real worktree: the `tests/test_movie_ui_http.py` batch-fork tests, which fail on the 20 GiB disk reserve at 19.4 GiB free. `/usr/bin/python3` and 3.13 both compile all seven changed Python files.

## Global Constraints

Exact values from the spec (section in brackets):

**Grammar and constants**
- [2.1] `action_lib` constants, added after `DEFAULT_ACTION_STRENGTH`:
  - `CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")`
  - `CLIP_NAME_RE = re.compile(r"([0-9]+)_([0-9]+)_([A-Za-z0-9_-]+)\.([A-Za-z0-9]+)")`
  - `MOVE_RE = re.compile(r"[a-z][a-z0-9]*(?: [a-z0-9]+)*")`
  - `MAX_MOVES = 8`, `MAX_MOVE_CHARS = 40`, `MAX_DIR_CLIPS = 1000`
  - `CLIP_NAME_HINT = "<n>_<n>_<moves>.<ext>"`
- [2.1] Parse order, first failure wins: hidden, extension, regex, then per move (empty, longer than 40, must start with a letter), then more than 8 moves. Moves are lowercased and duplicates are kept. A malformed move skips the file and is never repaired.
- [2.1.1] Scan:
  - `os.path.abspath`, not realpath. Non-recursive. Opens no file.
  - Skip order: hidden, folder, not a regular file, parse, not readable.
  - `clips` sort by `(int(a), int(b), name)`; `skipped` stay in `sorted(names)` order.
  - A skipped name is stored with `surrogateescape` → `replace`.
  - Raises `ActionError("folder %s is not a readable directory" % d)`.
- [2.1.2] `clip_caption(trigger, moves) = trigger + ": " + ", then ".join(moves)`.

**`action_dataset` scale constants**
- `CONTACT_MAX = 48`, `CREATE_MIN_FREE_GIB = 2.0` (unchanged), `CREATE_PER_CLIP_GIB = 0.005`.
- `create_min_free_gib(n) = 2.0 + 0.005 n`.
- `contact_sample(n)` as given in 2.4.8.
- `preprocess_timeout_s(n) = max(PREPROCESS_TIMEOUT_S, 600 + 15 * n)`. `PREPROCESS_TIMEOUT_S = 1800` and `TRAIN_TIMEOUT_S = 14400` are unchanged.
- `MIN_CLIPS = 8` and `MIN_PERFORMERS = 3` are unchanged. Server `ACTION_MAX_CLIPS = 64` is unchanged and applies to the list only.

**Behaviour**
- [2.4] File names stay `clip_%02d` (F10). `action.json` is unchanged and `schema_version` stays 1.
- [2.4] `manifest.json` keeps every existing key, then appends `items`, `source_dir`, `skipped`, `contact_sheet_clips`, in that order.
- [2.4.6] Stale cleanup deletes only `clips/clip_*.mp4` and `captions/clip_*.txt`, after the disk check and before the loop, on both paths (Q4).
- [2.4.7] Progress line: `clip %d/%d: <basename>`, with `flush=True`.
- [2.5.7] `MAX_DIR_CLIPS` applies to `--dir` only. `--clip` has no CLI cap.
- [2.6.5] Exit codes:
  - 2: both or neither of `--dir`/`--clip`, an unreadable dir, 0 matches, too many matches, a bad trigger, or any existing condition.
  - 3: fewer than 8 clips kept.

**Messages**
- [3] Every message in the spec's Section 3 table is byte-exact. The code blocks below carry them.

**Server and page**
- [2.7.1] Route `("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview")`, placed right after `POST /api/actions`. The six `len(srv.ROUTES) == 66` pins become `67`. Nothing else changes in those files.
- [2.7.6] Preview creates no job, writes nothing and requires no minimum number of matches.
- [F11] `movie_ui_server.py` never imports `action_lib` or `action_dataset`. `test_mut25_source_scan_of_new_python_files` already bans top-level imports outside its allow-list, and the strings `importlib`, `SourceFileLoader`, `exec(` and `__import__` in `movie_ui_server.py` and `movie_ui_lib.py`. None of the code below uses them.
- [2.7.7] Python 3.9: every added line in `action_lib.py`, `action_dataset.py`, `bin/action`, `movie_ui_lib.py` and `movie_ui_server.py` compiles on `/usr/bin/python3` 3.9.6. That means no `match`, no `X | Y`, no 3.10+ APIs, and `%` formatting. `tests/test_location_lib.py::test_ll1_*` already compiles `movie_ui_lib.py` and `movie_ui_server.py` on 3.9.
- [2.8, QET38] `index.html` and `app.js` must not contain:
  - `https?://`, `\son[a-z]+=`, `style=`, `\bconfirm\(`, `innerHTML` (`tests/test_movie_ui_seed_loras.py`);
  - `\balert\(`, `\bprompt\(`, `\beval\(`, `new Function` (`test_mut24`).

  All server text goes in through `textContent`. `app.css` is unchanged.

**Pinned files and safety**
- [Pinned files] Neither task touches a `PIPELINE_FILES` member (`tests/test_movie_ui_builder.py:223-228`). `test_mut26`'s `BASELINE = "a87e7992ff17c351aa75e47980977d81b1138e03"` is not bumped. **Task 1 touches:** `action_lib.py`, `action_dataset.py`, `bin/action`, `tests/test_action_bulk.py`. **Task 2 touches:** `movie_ui_lib.py`, `movie_ui_server.py`, `static/movie-ui/index.html`, `static/movie-ui/app.js`, `tests/test_movie_ui_actions.py`, and the five route-pin test files. None is pinned. If an implementer finds a pinned file must change, they stop and report.
- [4] The repository is public. No user path may appear in code or tests, except the existing placeholder style in `index.html` (`/Users/me/...`). Tests use `tmp_path` and synthetic file names only.
- [Where] Nobody accesses macstudio. Live checks BKL1-BKL6 are the user's to run.

House rules:
- **Checkout.** `S` = `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`, `WS` = `$S/bk-wt/qwen-agent-workspace`, git root = `$S/bk-wt`, branch `bulk-action-clips`. Shell variables do not persist, so every command block below starts with its own `cd`.
- **Git.** Never `git stash`, `reset`, `checkout`, `switch`, `amend`, `rebase` or `push`. Stage only the paths a task names, and check `git diff --cached --name-only` (paths carry the `qwen-agent-workspace/` prefix) before committing. Commits pass the trailer as a second `-m`.
- **Editing.** Change tracked files only with the Edit tool, or the Write tool for the one new file. An Edit's old text is whole lines and occurs exactly once, unless `replace_all` with a stated count is given. If it does not match, stop and report. Code blocks are copied byte for byte.
- **Existing assertions.** No existing assertion is edited except the six route pins. If any other existing test newly fails, stop and report.

## Review Focus

These are the five failure modes most likely to reach the user that the spec's BKT rows do not pin. Each has a test named `test_bk_review_focus_N_…` in the task that owns its code.

1. **A folder whose numbers sort differently as text and as numbers** (`9_00`, `9_01`, `10_00`, `100_00`: as text, `100_` < `10_` < `9_`). Every caption must stay with its own clip: `clip_K.txt`, manifest `items[K]` and `action.json` `source.paths[K]` all follow the numeric scan order, and so do the `clip i/N` progress lines. BKT10 uses `001/002/003`, which sort the same both ways, so it would not catch a mismatch. Test: `test_bk_review_focus_1_numeric_order_keeps_each_caption_with_its_clip` (Task 1). It needs no ffmpeg: probe, normalize and extract-frame are faked.
2. **Python 3.9.** The movie-ui server and its jobs may run under `/usr/bin/python3`. `bin/action scan` must actually run on 3.9 and print the same JSON as on 3.13. `action_lib.py`, `action_dataset.py` and `bin/action` must compile on 3.9; no existing test compiles these three. Test: `test_bk_review_focus_2_python_39_runs_scan_and_compiles_the_files` (Task 1).
3. **Rebuild of a folder action.** The page's Rebuild button re-POSTs `last_create_fields` with `regenerate: true`. For a folder job those fields carry `dir` and no `clips`. The request must pass validation and queue `create … --dir D --performers N --regenerate` with no `--clip`. A clips body with `"dir": null` must keep the clips path. Test: `test_bk_review_focus_3_rebuild_resends_the_folder` (Task 2).
4. **A trigger typed with extra spaces** (`"  performs   a fight combo "`). Preview must answer 200, not 502: `bin/action scan` rejects an un-normalized trigger, so the server must normalize it. The captions must equal what Create will write, because Create's argv carries the same normalized trigger. A blank trigger means null captions. Test: `test_bk_review_focus_4_preview_captions_use_the_normalized_trigger` (Task 2).
5. **Preview drags in `action_dataset`/PIL, or the server imports `action_lib`.** Preview must work in a workspace holding only `bin/action` and `action_lib.py`. The server source has no `import action_lib` or `import action_dataset` at any indentation (mut25 checks only column 0). An empty folder previews as 200 with `matched == 0`. Test: `test_bk_review_focus_5_preview_needs_only_action_lib` (Task 2).

---

## Step 0: snapshot and baseline (controller; no code)

- [ ] **Step 0.1: Compressed snapshot (house rule) and disk.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad && tar -czf bk-snapshot-7e4258a.tgz bk-wt && ls -l bk-snapshot-7e4258a.tgz && git -C bk-wt log -1 --format=%h && git -C bk-wt status --short | wc -l && df -h /System/Volumes/Data | tail -1
```

Expected:
- the archive exists (a few MB);
- `7e4258a`;
- `0`;
- the free-space line (16-23 GiB were seen during planning).

- [ ] **Step 0.2: Record the baseline failures of the relevant set.** About 4 minutes.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && mkdir -p ../../bk-baseline && python3 -m pytest -q -p no:cacheprovider tests/test_action_dataset.py tests/test_action_train.py tests/test_action_lib.py tests/test_action_compose.py tests/test_movie_ui_actions.py tests/test_vlm_lifecycle.py tests/test_clean_stop.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seed_loras.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py tests/test_lora_scope_ui.py tests/test_motion_beat_only_ui.py tests/test_movie_ui_extra_refs.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_builder.py tests/test_location_lib.py tests/test_movie_ui_seams.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_shots_zimage.py tests/test_soft_panel_count.py tests/test_lora_scope_fix.py tests/test_movie_ui_batch.py tests/test_movie_ui_jobs.py tests/test_movie_ui_progress.py 2>&1 | tee ../../bk-baseline/base.log | grep -E '^(FAILED|ERROR) ' | sed 's/ - .*//' | sort > ../../bk-baseline/base-failures.txt; tail -1 ../../bk-baseline/base.log; wc -l < ../../bk-baseline/base-failures.txt
```

Expected, if free space is under about 20 GiB: about 26 failures, all disk-reserve ones:
- the `tests/test_movie_ui_http.py` batch-fork tests (`test_bt16`…`test_bt35`, `test_batch_review_focus_1/3`, `test_batch_fix_*`), which fail with `not enough free space: … at least 20 GiB must stay free` or `copy failed`;
- `tests/test_vlm_lifecycle.py::test_bt30_fork_jobs_record_their_vlm_policy` (a `TypeError` from the refused fork).

With about 21 GiB or more free, the list is empty. **Either way, this file is the allowed-failure list for both tasks.** A failure not in it, after either task, is a stop-and-report. The full suite (`python3 -m pytest -q -p no:cacheprovider tests/`, about 20 minutes) is run the same way into `../../bk-baseline/full-base-failures.txt`. It may run in the background, and the controller compares against it after Task 2.

---

### Task 1: Parser, folder captions in `build_dataset`, CLI `--dir` and `scan` (spec 2.1-2.6; BKT1-BKT12; Review Focus 1-2)

**Files:**
- Modify `…/qwen-agent-workspace/action_lib.py`:
  - constants after `DEFAULT_ACTION_STRENGTH`;
  - `parse_clip_name`, `scan_clip_dir`, `clip_caption` appended after `registered_triggers`.
- Modify `…/qwen-agent-workspace/action_dataset.py`:
  - `CONTACT_MAX`, `CREATE_PER_CLIP_GIB`;
  - `create_min_free_gib`, `contact_sample` before `build_dataset`;
  - the `build_dataset` signature, caption validation, disk check, stale cleanup, progress, sample, captions and manifest;
  - `preprocess_timeout_s` after `TRAIN_TIMEOUT_S`, and the `train_action` timeout argument;
  - the `create` `--dir` branch and the exit-3 text;
  - `--dir` in `build_parser`.
- Modify `…/qwen-agent-workspace/bin/action`: the docstring, `--dir`, the `scan` parser, `cmd_scan`, and `main` dispatch before `import action_dataset`.
- Create `…/qwen-agent-workspace/tests/test_action_bulk.py`.
- Pinned files touched: **none**.

**Interfaces:**
- Consumes (existing):
  - `action_lib.ActionError`, `validate_trigger(trigger)`, `new_action(...)`, `action_dir(name)`, `action_json_path(name)`, `TRIGGER_RE`;
  - `action_dataset.DatasetError`, `probe_clip(path)`, `normalize_clip(src, dst, width, height, frames, fps)`, `extract_frame(clip, dst_png, at_frac=0.5)`, `write_contact_sheet(frame_pngs, out_path)`, `_free_gib(path)`, `_run_logged(cmd, log_path, cwd, env, timeout_s)`, `_load_action_lib()`, `_error(message)`.
- Produces (Task 2 relies on the `scan` output and `create --dir`):
  - `action_lib.parse_clip_name(name) -> (list of str, None) or (None, str)`.
  - `action_lib.scan_clip_dir(path) -> {"dir": str, "clips": [{"name": str, "path": str, "moves": [str]}], "skipped": [{"name": str, "reason": str}]}`. Raises `ActionError`.
  - `action_lib.clip_caption(trigger, moves) -> str`.
  - The constants `CLIP_EXTS`, `CLIP_NAME_RE`, `MOVE_RE`, `MAX_MOVES`, `MAX_MOVE_CHARS`, `MAX_DIR_CLIPS`, `CLIP_NAME_HINT`.
  - `action_dataset.CONTACT_MAX = 48`, `CREATE_PER_CLIP_GIB = 0.005`.
  - `create_min_free_gib(n_clips) -> float`, `contact_sample(n, limit=CONTACT_MAX) -> list of int`, `preprocess_timeout_s(n_clips) -> int`.
  - `build_dataset(name, trigger, descriptor, clip_paths, performers, *, width=..., height=..., frames=..., fps=..., force=False, captions=None, source_dir=None, skipped=None) -> dict`.
  - `bin/action scan DIR [--trigger PHRASE]`: stdout is `json.dumps({"dir", "matched", "max", "clips": [{"name", "path", "moves", "caption"}], "skipped"}, indent=2)`. Exit 0, or exit 2 with `Error: <msg>` on stderr.
  - `bin/action create NAME … --dir DIR`.

- [ ] **Step 1: Write the failing test file.** Create `tests/test_action_bulk.py` with exactly this content:

```python
"""Tests for bulk action-LoRA clip loading (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md,
Section 6.1: BKT1-BKT12, plus the plan's Review Focus 1 and 2): the file-name grammar, the folder
scan, folder captions in build_dataset, the contact-sheet sample, the scaled disk check, stale-clip
cleanup, create --dir, bin/action scan and the scaled preprocess timeout.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py
Stdlib, PIL (through action_dataset) and pytest. The ffmpeg tests build tiny synthetic clips and skip
when ffmpeg is missing; the others fake probe/normalize/extract-frame. Every folder and library is
under tmp_path.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.realpath(__file__))
WS = os.path.dirname(HERE)
ad = importlib.machinery.SourceFileLoader(
    "action_dataset", os.path.join(WS, "action_dataset.py")).load_module()
al = importlib.machinery.SourceFileLoader(
    "action_lib", os.path.join(WS, "action_lib.py")).load_module()

_HAVE_FFMPEG = os.path.exists(ad.FFMPEG) and os.path.exists(ad.FFPROBE)
needs_ffmpeg = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not available")
PY39 = "/usr/bin/python3"

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
TRIGGER = "performs a fight combo"
VIDEO_REASON = "not a video (.mp4, .mov, .m4v, .webm, .mkv)"
NO_MATCH = "name does not match <n>_<n>_<moves>.<ext>"
MANIFEST_KEYS = ["name", "trigger", "descriptor", "clips", "performers", "identity_agnostic", "width",
                 "height", "frames", "fps", "sources", "items", "source_dir", "skipped", "contact_sheet_clips"]

MATCHING = [
    ("006_00_high_kick-stance-front_kick.mp4", ["high kick", "stance", "front kick"]),
    ("005_01_punch-stance-high_kick.mp4", ["punch", "stance", "high kick"]),
    ("6_0_Kick.MP4", ["kick"]),
    ("010_02_jab-jab.mov", ["jab", "jab"]),
    ("007_00_spinning__back_kick.mp4", ["spinning back kick"]),
    ("007_00__kick_.mp4", ["kick"]),
]
NON_MATCHING = [
    ("notes.txt", VIDEO_REASON),
    ("006_00_kick.mp4.part", VIDEO_REASON),
    ("kick.mp4", NO_MATCH),
    ("006_kick.mp4", NO_MATCH),
    ("006_00_.mp4", NO_MATCH),
    ("006_00_kick kick.mp4", NO_MATCH),
    ("006_00_kíck.mp4", NO_MATCH),
    ("006_00_punch--kick.mp4", "empty move"),
    ("006_00_-kick.mp4", "empty move"),
    ("006_00_" + "a" * 41 + ".mp4", "move longer than 40 characters"),
    ("006_00_1st_kick.mp4", "move '1st kick' must start with a letter"),
    ("006_00_a-b-c-d-e-f-g-h-i.mp4", "more than 8 moves"),
    (".006_00_kick.mp4", "hidden file"),
    ("._006_00_kick.mp4", "hidden file"),
]


def _make_clip(path, color="red", size="100x80", dur=1):
    subprocess.run([ad.FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=%s:s=%s:d=%d" % (color, size, dur), "-r", "24", path],
                   capture_output=True, check=True)


def _touch(path):
    with open(path, "wb"):
        pass


def _folder(tmp_path, names):
    """<tmp>/clips (a realpath) holding a zero-byte file for each name."""
    d = os.path.join(os.path.realpath(str(tmp_path)), "clips")
    os.makedirs(d)
    for name in names:
        _touch(os.path.join(d, name))
    return d


def _clips(tmp_path, n):
    paths = []
    for i, color in enumerate(("red", "green", "blue")[:n]):
        p = os.path.join(os.path.realpath(str(tmp_path)), "ref_%d.mp4" % i)
        _make_clip(p, color=color)
        paths.append(p)
    return paths


def _read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def _manifest(name):
    with open(os.path.join(al.action_dir(name), "dataset", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _fake_ffmpeg(monkeypatch, extracted=None):
    """probe/normalize/extract-frame without ffmpeg: every clip is 24 frames, normalize writes a
    4-byte file, and extract-frame records the clip and fails (so the sheet is the placeholder)."""
    def probe(path):
        return 64, 64, 24, 1.0

    def normalize(src, dst, width, height, frames, fps=24):
        with open(dst, "wb") as f:
            f.write(b"clip")

    def extract(clip, dst_png, at_frac=0.5):
        if extracted is not None:
            extracted.append(os.path.basename(clip))
        raise ad.DatasetError("no frame in a fake clip")

    monkeypatch.setattr(ad, "probe_clip", probe)
    monkeypatch.setattr(ad, "normalize_clip", normalize)
    monkeypatch.setattr(ad, "extract_frame", extract)


def _main_create(*extra):
    return ad.main(["create", "combo-set", "--trigger", TRIGGER, "--descriptor", DESC] + list(extra))


def _bin_action():
    loader = importlib.machinery.SourceFileLoader("bin_action_for_bulk", os.path.join(WS, "bin", "action"))
    spec = importlib.util.spec_from_loader("bin_action_for_bulk", loader)
    tool = importlib.util.module_from_spec(spec)
    loader.exec_module(tool)
    return tool


def _scan(lib_dir, *args, python=None):
    env = dict(os.environ, ACTION_LIBRARY_DIR=lib_dir, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([python or sys.executable, os.path.join(WS, "bin", "action"), "scan"] + list(args),
                          capture_output=True, text=True, timeout=60, env=env)


def _snapshot(d):
    entries = []
    for name in sorted(os.listdir(d)):
        st = os.stat(os.path.join(d, name))
        entries.append((name, st.st_size, st.st_mtime_ns))
    return entries, os.stat(d).st_mtime_ns


# ---- copied from tests/test_action_train.py (the stub ltx-2-mlx) -------------------------------
_STUB = r"""#!/bin/bash
cmd="$1"; shift
if [ "$cmd" = "preprocess" ]; then
  videos=""; out=""
  while [ $# -gt 0 ]; do case "$1" in
    --videos|-v) videos="$2"; shift 2;;
    -o|--output) out="$2"; shift 2;;
    *) shift;; esac; done
  mkdir -p "$out/.precomputed/latents"
  i=0; for f in "$videos"/*.mp4; do touch "$out/.precomputed/latents/lat_$i.pt"; i=$((i+1)); done
elif [ "$cmd" = "train" ]; then
  cfg=""
  while [ $# -gt 0 ]; do case "$1" in --config|-c) cfg="$2"; shift 2;; *) shift;; esac; done
  outdir=$(grep '^output_dir:' "$cfg" | sed 's/output_dir: *//' | tr -d '"')
  mkdir -p "$outdir/checkpoints"
  echo "fake-lora-weights" > "$outdir/checkpoints/lora_weights_step_01000.safetensors"
fi
exit 0
"""


def _seed_action(lib_dir, name="roundhouse", clips=8):
    os.environ[al.LIBRARY_ENV] = str(lib_dir)
    os.makedirs(al.action_dir(name))
    cdir = os.path.join(al.action_dir(name), "dataset", "clips"); os.makedirs(cdir)
    pdir = os.path.join(al.action_dir(name), "dataset", "captions"); os.makedirs(pdir)
    for i in range(clips):
        open(os.path.join(cdir, "clip_%02d.mp4" % i), "w").write("x")
        open(os.path.join(pdir, "clip_%02d.txt" % i), "w").write("performs a roundhouse kick")
    data = al.new_action(name, "performs a roundhouse kick", DESC, ["/abs/ref0.mp4"], identity_agnostic=True)
    data["dataset"] = {"clips": clips, "performers": 3, "width": 64, "height": 64,
                       "frames": 9, "fps": 24, "contact_sheet": "x"}
    al.write_action(data)
    return name


def _install_stub(tmp_path, monkeypatch):
    stub = tmp_path / "ltx-2-mlx"
    stub.write_text(_STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR)
    model = tmp_path / "trainmodel"; model.mkdir()
    monkeypatch.setattr(ad, "LTX2_MLX_BIN", str(stub))
    monkeypatch.setattr(ad, "TRAIN_MODEL", str(model))
    monkeypatch.setattr(ad, "LTX2_MLX_DIR", str(tmp_path))
    monkeypatch.setattr(ad, "LTX2_MLX_HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(ad, "busy_process", lambda: None)
    monkeypatch.setattr(ad, "story_server_state", lambda: "STOPPED")


# ---- BKT1-BKT4: the grammar, the scan, the caption ---------------------------------------------

def test_bkt1_matching_names():
    for name, moves in MATCHING:
        assert al.parse_clip_name(name) == (moves, None), name
    assert al.parse_clip_name("006_00_" + "a" * 40 + ".mp4") == (["a" * 40], None)
    assert al.parse_clip_name("006_00_a-b-c-d-e-f-g-h.mp4") == (list("abcdefgh"), None)


def test_bkt2_non_matching_names():
    for name, reason in NON_MATCHING:
        assert al.parse_clip_name(name) == (None, reason), name


def test_bkt3_scan_clip_dir(tmp_path, monkeypatch):
    root = os.path.realpath(str(tmp_path))
    d = _folder(tmp_path, ["9_00_kick.mp4", "10_00_punch-kick.mp4", "006_00_high_kick-stance-front_kick.mp4",
                           "notes.txt", ".006_00_kick.mp4", "011_00_jab.mp4"])
    os.makedirs(os.path.join(d, "sub"))
    _touch(os.path.join(d, "sub", "001_00_kick.mp4"))
    locked = os.path.join(d, "011_00_jab.mp4")
    os.chmod(locked, 0)
    try:
        scan = al.scan_clip_dir(d)
        as_root = os.geteuid() == 0
        names = ["006_00_high_kick-stance-front_kick.mp4", "9_00_kick.mp4", "10_00_punch-kick.mp4"]
        if as_root:
            names.append("011_00_jab.mp4")
        assert scan["dir"] == d
        assert [c["name"] for c in scan["clips"]] == names
        assert scan["clips"][0] == {"name": names[0], "path": os.path.join(d, names[0]),
                                    "moves": ["high kick", "stance", "front kick"]}
        assert scan["clips"][2] == {"name": "10_00_punch-kick.mp4", "path": os.path.join(d, "10_00_punch-kick.mp4"),
                                    "moves": ["punch", "kick"]}
        skipped = [{"name": ".006_00_kick.mp4", "reason": "hidden file"}]
        if not as_root:
            skipped.append({"name": "011_00_jab.mp4", "reason": "not readable"})
        skipped += [{"name": "notes.txt", "reason": VIDEO_REASON}, {"name": "sub", "reason": "folder (not scanned)"}]
        assert scan["skipped"] == skipped
        monkeypatch.chdir(root)
        assert al.scan_clip_dir("clips") == scan
    finally:
        os.chmod(locked, 0o644)
    for bad in (os.path.join(d, "notes.txt"), os.path.join(root, "missing")):
        with pytest.raises(al.ActionError, match="^folder %s is not a readable directory$" % re.escape(bad)):
            al.scan_clip_dir(bad)


def test_bkt4_clip_caption():
    assert al.clip_caption(TRIGGER, ["kick"]) == "performs a fight combo: kick"
    assert al.clip_caption(TRIGGER, ["high kick", "stance", "front kick"]) == (
        "performs a fight combo: high kick, then stance, then front kick")


# ---- BKT5-BKT9: build_dataset ------------------------------------------------------------------

@needs_ffmpeg
def test_bkt5_captions_on_disk_and_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    captions = ["t: a", "t: b, then c", "t: d"]
    skipped = [{"name": "n.txt", "reason": "r"}]
    ad.build_dataset("combo-set", TRIGGER, DESC, clips, performers=3, width=64, height=64, frames=9,
                     captions=captions, source_dir="/x", skipped=skipped)
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i), "rb") == caption.encode("utf-8")
    manifest = _manifest("combo-set")
    assert list(manifest) == MANIFEST_KEYS
    assert manifest["sources"] == clips
    assert manifest["items"] == [{"clip": "clip_%02d.mp4" % i, "source": clips[i], "caption": captions[i]}
                                 for i in range(3)]
    assert manifest["source_dir"] == "/x"
    assert manifest["skipped"] == skipped
    assert manifest["contact_sheet_clips"] == [0, 1, 2]


def test_bkt5_caption_errors_come_before_any_file(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    paths = ["/nope/a.mp4", "/nope/b.mp4", "/nope/c.mp4"]
    with pytest.raises(ad.DatasetError, match=r"^captions: 2 given for 3 clips$"):
        ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                         captions=["t: a", "t: b"])
    with pytest.raises(ad.DatasetError, match=r"^captions: -1 given for 3 clips$"):
        ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                         captions="t: a")
    for bad in ("", "   ", "a\nb", "a\rb", None):
        with pytest.raises(ad.DatasetError, match=r"^captions: caption 1 must be one non-empty line$"):
            ad.build_dataset("combo-bad", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9,
                             captions=["t: a", bad, "t: d"])
    assert not os.path.exists(al.action_dir("combo-bad"))


@needs_ffmpeg
def test_bkt6_the_single_trigger_path_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    data = ad.build_dataset("roundhouse-kick", "performs a roundhouse kick", DESC, clips,
                            performers=3, width=64, height=64, frames=9)
    al.validate_action(data)
    assert data["status"] == "dataset" and data["identity_agnostic"] is True
    assert data["dataset"]["clips"] == 3 and data["dataset"]["width"] == 64
    assert list(data["dataset"]) == ["clips", "performers", "width", "height", "frames", "fps", "contact_sheet"]
    assert data["source"] == {"type": "clips", "paths": clips}
    base = os.path.join(al.action_dir("roundhouse-kick"), "dataset")
    for i in range(3):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i), "rb") == b"performs a roundhouse kick"
    manifest = _manifest("roundhouse-kick")
    assert list(manifest) == MANIFEST_KEYS
    assert [item["caption"] for item in manifest["items"]] == ["performs a roundhouse kick"] * 3
    assert manifest["source_dir"] is None and manifest["skipped"] == []
    assert al.load_action("roundhouse-kick") == data


def test_bkt7_contact_sample():
    assert ad.CONTACT_MAX == 48
    assert ad.contact_sample(0) == []
    assert ad.contact_sample(5) == [0, 1, 2, 3, 4]
    assert ad.contact_sample(48) == list(range(48))
    for n in (49, 1000):
        sample = ad.contact_sample(n)
        assert len(sample) == 48 and len(set(sample)) == 48 and sample == sorted(sample), n
        assert sample[0] == 0 and sample[-1] == n - 1, n


def test_bkt7_only_sampled_clips_reach_the_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    extracted = []
    _fake_ffmpeg(monkeypatch, extracted)
    d = _folder(tmp_path, ["src_%02d.mp4" % i for i in range(50)])
    paths = [os.path.join(d, "src_%02d.mp4" % i) for i in range(50)]
    ad.build_dataset("sample-set", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9)
    assert extracted == ["clip_%02d.mp4" % i for i in ad.contact_sample(50)]
    assert _manifest("sample-set")["contact_sheet_clips"] == ad.contact_sample(50)


@needs_ffmpeg
def test_bkt8_a_rebuild_removes_stale_clips(tmp_path, monkeypatch):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    clips = _clips(tmp_path, 3)
    ad.build_dataset("stale-set", TRIGGER, DESC, clips, performers=3, width=64, height=64, frames=9)
    base = os.path.join(al.action_dir("stale-set"), "dataset")
    _touch(os.path.join(base, "clips", "keep.md"))
    ad.build_dataset("stale-set", TRIGGER, DESC, clips[:2], performers=3, width=64, height=64, frames=9)
    assert sorted(os.listdir(os.path.join(base, "clips"))) == ["clip_00.mp4", "clip_01.mp4", "keep.md"]
    assert sorted(os.listdir(os.path.join(base, "captions"))) == ["clip_00.txt", "clip_01.txt"]


def test_bkt9_disk_scaling(tmp_path, monkeypatch):
    assert ad.CREATE_PER_CLIP_GIB == 0.005
    assert ad.create_min_free_gib(0) == pytest.approx(2.0)
    assert ad.create_min_free_gib(100) == pytest.approx(2.5)
    assert ad.create_min_free_gib(1000) == pytest.approx(7.0)
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    monkeypatch.setattr(ad, "_free_gib", lambda p: 2.01)
    d = _folder(tmp_path, ["z_0.mp4", "z_1.mp4", "z_2.mp4"])
    paths = [os.path.join(d, "z_%d.mp4" % i) for i in range(3)]
    with pytest.raises(ad.DatasetError) as e:
        ad.build_dataset("disk-set", TRIGGER, DESC, paths, performers=3, width=64, height=64, frames=9)
    message = str(e.value)
    assert message.startswith("less than 2.0 GiB free at ") and message.endswith("(needed for 3 clips)")
    assert message == "less than 2.0 GiB free at %s (needed for 3 clips)" % al.action_dir("disk-set")
    assert os.listdir(os.path.join(al.action_dir("disk-set"), "dataset", "clips")) == []


# ---- BKT10-BKT12: create --dir, bin/action scan, the preprocess timeout -----------------------

def test_bkt10_create_dir_argument_rules(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    d = _folder(tmp_path, ["notes.txt"])
    assert _main_create("--dir", d, "--clip", "/abs/a.mp4") == 2
    assert capsys.readouterr().err == "Error: give either --dir or --clip, not both\n"
    assert _main_create() == 2
    assert capsys.readouterr().err == (
        "Error: create needs --trigger, --descriptor and --dir or at least one --clip\n")
    assert _main_create("--dir", d) == 2
    out = capsys.readouterr()
    assert out.out == "skipped: notes.txt (%s)\nfolder: 0 clip(s) matched, 1 skipped in %s\n" % (VIDEO_REASON, d)
    assert out.err == "Error: no file in %s matches <n>_<n>_<moves>.<ext>\n" % d
    missing = os.path.join(os.path.realpath(str(tmp_path)), "missing")
    assert _main_create("--dir", missing) == 2
    assert capsys.readouterr().err == "Error: folder %s is not a readable directory\n" % missing
    assert _main_create("--dir", d, "--trigger", "bad:trigger") == 2
    assert capsys.readouterr().err.startswith("Error: trigger: ")
    assert not os.path.exists(al.action_dir("combo-set"))


@needs_ffmpeg
def test_bkt10_create_dir_captions_each_clip_from_its_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    d = _folder(tmp_path, ["notes.txt"])
    names = ["001_00_kick.mp4", "002_00_punch-kick.mp4", "003_00_high_kick-stance.mp4"]
    for name, color in zip(names, ("red", "green", "blue")):
        _make_clip(os.path.join(d, name), color=color)
    rc = _main_create("--dir", d, "--width", "64", "--height", "64", "--frames", "9", "--performers", "3")
    out = capsys.readouterr()
    assert rc == 3, out.err
    assert "skipped: notes.txt (%s)\n" % VIDEO_REASON in out.out
    assert "folder: 3 clip(s) matched, 1 skipped in %s\n" % d in out.out
    assert "clip 1/3: 001_00_kick.mp4\n" in out.out and "clip 3/3: 003_00_high_kick-stance.mp4\n" in out.out
    assert "add more clips and run bin/action create combo-set --regenerate." in out.err
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    captions = [al.clip_caption(TRIGGER, moves) for moves in (["kick"], ["punch", "kick"], ["high kick", "stance"])]
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i)) == caption
    manifest = _manifest("combo-set")
    assert manifest["source_dir"] == d
    assert manifest["skipped"] == [{"name": "notes.txt", "reason": VIDEO_REASON}]
    assert [item["source"] for item in manifest["items"]] == [os.path.join(d, n) for n in names]
    assert [item["caption"] for item in manifest["items"]] == captions
    assert al.load_action("combo-set")["source"]["paths"] == [os.path.join(d, n) for n in names]


def test_bkt10_the_folder_clip_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    monkeypatch.setattr(ad, "_load_action_lib", lambda: al)
    monkeypatch.setattr(al, "MAX_DIR_CLIPS", 2)
    d = _folder(tmp_path, ["001_00_kick.mp4", "002_00_kick.mp4", "003_00_kick.mp4"])
    assert _main_create("--dir", d) == 2
    assert capsys.readouterr().err == "Error: %s has 3 matching clips; an action takes at most 2\n" % d
    assert not os.path.exists(al.action_dir("combo-set"))


def test_bkt10_both_parsers_take_dir():
    argv = ["create", "x", "--trigger", "t", "--descriptor", "d", "--dir", "/tmp"]
    for parser in (_bin_action().build_parser(), ad.build_parser()):
        args = parser.parse_args(argv)
        assert args.dir == "/tmp" and args.clips == []
    args = _bin_action().build_parser().parse_args(["scan", "/tmp"])
    assert (args.command, args.dir, args.trigger) == ("scan", "/tmp", None)


def test_bkt11_bin_action_scan_is_read_only_json(tmp_path):
    lib_dir = os.path.join(os.path.realpath(str(tmp_path)), "lib")
    d = _folder(tmp_path, ["006_00_high_kick-stance-front_kick.mp4", "9_00_kick.mp4", "notes.txt"])
    before = _snapshot(d)
    run = _scan(lib_dir, d, "--trigger", TRIGGER)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert list(data) == ["dir", "matched", "max", "clips", "skipped"]
    assert (data["dir"], data["matched"], data["max"]) == (d, 2, 1000)
    assert data["clips"] == [
        {"name": "006_00_high_kick-stance-front_kick.mp4",
         "path": os.path.join(d, "006_00_high_kick-stance-front_kick.mp4"),
         "moves": ["high kick", "stance", "front kick"],
         "caption": "performs a fight combo: high kick, then stance, then front kick"},
        {"name": "9_00_kick.mp4", "path": os.path.join(d, "9_00_kick.mp4"), "moves": ["kick"],
         "caption": "performs a fight combo: kick"}]
    assert data["skipped"] == [{"name": "notes.txt", "reason": VIDEO_REASON}]
    run = _scan(lib_dir, d)
    assert run.returncode == 0, run.stderr
    assert [c["caption"] for c in json.loads(run.stdout)["clips"]] == [None, None]
    run = _scan(lib_dir, d, "--trigger", "bad:trigger")
    assert run.returncode == 2 and run.stdout == "" and run.stderr.startswith("Error: trigger:")
    missing = os.path.join(os.path.realpath(str(tmp_path)), "missing")
    run = _scan(lib_dir, missing)
    assert (run.returncode, run.stderr) == (2, "Error: folder %s is not a readable directory\n" % missing)
    assert _snapshot(d) == before
    assert not os.path.exists(lib_dir)


def test_bkt12_preprocess_timeout_scales(tmp_path, monkeypatch):
    assert [ad.preprocess_timeout_s(n) for n in (8, 80, 300, 1000)] == [1800, 1800, 5100, 15600]
    _install_stub(tmp_path, monkeypatch)
    seen = []
    real_run = ad._run_logged

    def recording(cmd, log_path, cwd, env, timeout_s):
        seen.append((os.path.basename(log_path), timeout_s))
        return real_run(cmd, log_path, cwd, env, timeout_s)

    monkeypatch.setattr(ad, "_run_logged", recording)
    for clips, lib_name, expected in ((8, "lib8", 1800), (100, "lib100", 2100)):
        monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / lib_name))
        name = _seed_action(tmp_path / lib_name, clips=clips)
        del seen[:]
        data, _lora = ad.train_action(name)
        assert data["status"] == "trained"
        assert seen == [("preprocess.log", expected), ("train.log", 14400)], clips


# ---- Review Focus 1 and 2 --------------------------------------------------------------------

def test_bk_review_focus_1_numeric_order_keeps_each_caption_with_its_clip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(al.LIBRARY_ENV, str(tmp_path / "lib"))
    _fake_ffmpeg(monkeypatch)
    d = _folder(tmp_path, ["100_00_jab-jab.mp4", "10_00_punch.mp4", "9_00_kick.mp4", "9_01_front_kick.mp4"])
    assert _main_create("--dir", d, "--performers", "3") == 3
    order = ["9_00_kick.mp4", "9_01_front_kick.mp4", "10_00_punch.mp4", "100_00_jab-jab.mp4"]
    captions = [al.clip_caption(TRIGGER, m) for m in (["kick"], ["front kick"], ["punch"], ["jab", "jab"])]
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if line.startswith("clip ")] == [
        "clip %d/4: %s" % (i + 1, n) for i, n in enumerate(order)]
    base = os.path.join(al.action_dir("combo-set"), "dataset")
    for i, caption in enumerate(captions):
        assert _read(os.path.join(base, "captions", "clip_%02d.txt" % i)) == caption
    assert [(os.path.basename(item["source"]), item["caption"]) for item in _manifest("combo-set")["items"]] == (
        list(zip(order, captions)))
    assert al.load_action("combo-set")["source"]["paths"] == [os.path.join(d, n) for n in order]


@pytest.mark.skipif(not os.path.isfile(PY39), reason="/usr/bin/python3 is not installed")
def test_bk_review_focus_2_python_39_runs_scan_and_compiles_the_files(tmp_path):
    lib_dir = os.path.join(os.path.realpath(str(tmp_path)), "lib")
    d = _folder(tmp_path, ["9_00_kick.mp4", "10_00_punch-kick.mp4", "notes.txt"])
    runs = [_scan(lib_dir, d, "--trigger", TRIGGER, python=py) for py in (PY39, sys.executable)]
    assert [r.returncode for r in runs] == [0, 0], [r.stderr for r in runs]
    assert runs[0].stdout == runs[1].stdout
    script = ("import py_compile, sys\n"
              "for k, path in enumerate(sys.argv[2:]):\n"
              "    py_compile.compile(path, cfile=sys.argv[1] + '/%d.pyc' % k, doraise=True)\n")
    files = [os.path.join(WS, rel) for rel in ("action_lib.py", "action_dataset.py", os.path.join("bin", "action"))]
    proc = subprocess.run([PY39, "-c", script, str(tmp_path)] + files, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py 2>&1 | tail -1`

Expected: `19 failed, …`:
- `AttributeError` for the new names;
- `SystemExit` for the `--dir` parsers;
- a non-zero `scan` exit, because the subcommand is missing.

No test passes. A pass means the test is wrong, so stop.

- [ ] **Step 3: `action_lib.py`, the constants (spec 2.1).** Edit. Old:

```python
MIN_PERFORMERS = 3              # identity-agnostic: varied performers (spec 3.2)
DEFAULT_ACTION_STRENGTH = 0.7
```

New:

```python
MIN_PERFORMERS = 3              # identity-agnostic: varied performers (spec 3.2)
DEFAULT_ACTION_STRENGTH = 0.7
# Folder ingestion (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, 2.1)
CLIP_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")     # = movie_ui_server.ACTION_CLIP_EXTS
CLIP_NAME_RE = re.compile(r"([0-9]+)_([0-9]+)_([A-Za-z0-9_-]+)\.([A-Za-z0-9]+)")
MOVE_RE = re.compile(r"[a-z][a-z0-9]*(?: [a-z0-9]+)*")
MAX_MOVES = 8
MAX_MOVE_CHARS = 40
MAX_DIR_CLIPS = 1000            # = ACTION_STEPS at batch size 1: past it some clips are never seen
CLIP_NAME_HINT = "<n>_<n>_<moves>.<ext>"
```

- [ ] **Step 4: `action_lib.py`, the parser, the scan and the caption (spec 2.1-2.1.2).** Edit. Old (the end of the file):

```python
        if data["status"] == "trained":
            triggers[data["trigger"]] = name
    return triggers
```

New:

```python
        if data["status"] == "trained":
            triggers[data["trigger"]] = name
    return triggers


# ---------------------------------------------------------------------------
# Folder ingestion: one action from a folder of clips named <n>_<n>_<moves>.<ext>
# (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, 2.1)
# ---------------------------------------------------------------------------

def parse_clip_name(name):
    """(moves, None) for a clip file name <n>_<n>_<moves>.<ext>, else (None, reason). Moves are
    split on "-"; "_" inside a move is a space; moves are lowercased and duplicates are kept. The
    first failing check gives the reason (spec 2.1)."""
    if name.startswith("."):
        return None, "hidden file"
    if os.path.splitext(name)[1].lower() not in CLIP_EXTS:
        return None, "not a video (%s)" % ", ".join(CLIP_EXTS)
    m = CLIP_NAME_RE.fullmatch(name)
    if m is None:
        return None, "name does not match %s" % CLIP_NAME_HINT
    moves = []
    for raw in m.group(3).lower().split("-"):
        move = " ".join(raw.replace("_", " ").split())
        if move == "":
            return None, "empty move"
        if len(move) > MAX_MOVE_CHARS:
            return None, "move longer than %d characters" % MAX_MOVE_CHARS
        if not MOVE_RE.fullmatch(move):
            return None, "move '%s' must start with a letter" % move
        moves.append(move)
    if len(moves) > MAX_MOVES:
        return None, "more than %d moves" % MAX_MOVES
    return moves, None


def scan_clip_dir(path):
    """One folder's clips, not recursive: {"dir": <abs>, "clips": [{"name", "path", "moves"}],
    "skipped": [{"name", "reason"}]}. clips sort by the two numbers, then the name; skipped stay
    in name order. It lists the folder and stats its entries; it opens no file. Raises
    ActionError when the folder cannot be listed (spec 2.1.1)."""
    d = os.path.abspath(path)
    unreadable = "folder %s is not a readable directory" % d
    if not (os.path.isdir(d) and os.access(d, os.R_OK | os.X_OK)):
        raise ActionError(unreadable)
    try:
        names = os.listdir(d)
    except OSError:
        raise ActionError(unreadable)
    found, skipped = [], []
    for name in sorted(names):
        full = os.path.join(d, name)
        moves = None
        if name.startswith("."):
            reason = "hidden file"
        elif os.path.isdir(full):
            reason = "folder (not scanned)"
        elif not os.path.isfile(full):
            reason = "not a regular file"
        else:
            moves, reason = parse_clip_name(name)
            if reason is None and not os.access(full, os.R_OK):
                reason = "not readable"
        if reason is not None:
            text = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
            skipped.append({"name": text, "reason": reason})
            continue
        m = CLIP_NAME_RE.fullmatch(name)
        found.append(((int(m.group(1)), int(m.group(2)), name), {"name": name, "path": full, "moves": moves}))
    found.sort(key=lambda item: item[0])
    return {"dir": d, "clips": [clip for _key, clip in found], "skipped": skipped}


def clip_caption(trigger, moves):
    """A folder clip's caption, "<trigger>: <m1>, then <m2>, ..." (spec 2.1.2). The caller has
    validated the trigger; TRIGGER_RE has no ":", so the separator is unambiguous."""
    return trigger + ": " + ", then ".join(moves)
```

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py::test_bkt1_matching_names tests/test_action_bulk.py::test_bkt2_non_matching_names tests/test_action_bulk.py::test_bkt3_scan_clip_dir tests/test_action_bulk.py::test_bkt4_clip_caption 2>&1 | tail -1`

Expected: `4 passed, …`.

- [ ] **Step 5: `action_dataset.py`, the constants (spec 2.4.5, 2.4.8).** Edit. Old:

```python
CONTACT_COLS = 4
CREATE_MIN_FREE_GIB = 2.0
```

New:

```python
CONTACT_COLS = 4
CONTACT_MAX = 48             # bulk action clips spec 2.4.8: the most clips on the contact sheet
CREATE_MIN_FREE_GIB = 2.0
CREATE_PER_CLIP_GIB = 0.005  # bulk action clips spec 2.4.5: 5 MiB more per clip
```

- [ ] **Step 6: `action_dataset.py`, the helpers, the signature and caption validation (spec 2.4.1-2.4.3, 2.4.5, 2.4.8).** Edit. Old:

```python
def build_dataset(name, trigger, descriptor, clip_paths, performers, *,
                  width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, frames=DEFAULT_FRAMES,
                  fps=DEFAULT_FPS, force=False):
    """Normalize clips, caption, contact-sheet, and write action.json. Returns the
    action.json dict. Raises DatasetError. Does not train."""
    lib = _load_action_lib()
    lib.validate_name(name)
    lib.validate_trigger(trigger)
    lib.validate_descriptor(descriptor)
    validate_geometry(width, height, frames)
```

New:

```python
def create_min_free_gib(n_clips):
    """The free space create needs for n_clips clips (bulk action clips spec 2.4.5)."""
    return CREATE_MIN_FREE_GIB + CREATE_PER_CLIP_GIB * n_clips


def contact_sample(n, limit=CONTACT_MAX):
    """The clip indices whose mid frame goes on the contact sheet: all of them up to limit,
    else limit evenly spaced indices from 0 to n - 1 (distinct because n - 1 >= limit)."""
    if n <= limit:
        return list(range(n))
    return [(k * (n - 1)) // (limit - 1) for k in range(limit)]


def build_dataset(name, trigger, descriptor, clip_paths, performers, *,
                  width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, frames=DEFAULT_FRAMES,
                  fps=DEFAULT_FPS, force=False, captions=None, source_dir=None, skipped=None):
    """Normalize clips, caption, contact-sheet, and write action.json. Returns the
    action.json dict. Raises DatasetError. Does not train. captions (one line per clip)
    replaces the trigger-only caption; source_dir and skipped are recorded in manifest.json
    (bulk action clips spec 2.4)."""
    lib = _load_action_lib()
    lib.validate_name(name)
    lib.validate_trigger(trigger)
    lib.validate_descriptor(descriptor)
    validate_geometry(width, height, frames)
    if captions is not None:
        if not (isinstance(captions, list) and len(captions) == len(clip_paths)):
            n_given = len(captions) if isinstance(captions, (list, tuple)) else -1
            raise DatasetError("captions: %d given for %d clips" % (n_given, len(clip_paths)))
        for k, c in enumerate(captions):
            if not (isinstance(c, str) and c.strip() and "\n" not in c and "\r" not in c):
                raise DatasetError("captions: caption %d must be one non-empty line" % k)
    texts = list(captions) if captions is not None else [trigger] * len(clip_paths)
```

- [ ] **Step 7: `action_dataset.py`, the disk check, stale cleanup, progress and sample (spec 2.4.3, 2.4.5-2.4.8).** Edit. Old:

```python
    if _free_gib(adir) < CREATE_MIN_FREE_GIB:
        raise DatasetError("less than %.0f GiB free at %s" % (CREATE_MIN_FREE_GIB, adir))

    frame_pngs = []
    kept = 0
    for i, src in enumerate(clip_paths):
        w, h, nb, dur = probe_clip(src)
        clip_frames = min(frames, snap_frames(nb)) if nb else frames
        dst = os.path.join(clips_dir, "clip_%02d.mp4" % i)
        normalize_clip(src, dst, width, height, clip_frames, fps)
        with open(os.path.join(captions_dir, "clip_%02d.txt" % i), "w", encoding="utf-8") as f:
            f.write(trigger)                      # appearance-free: the motion phrase only
        png = os.path.join(dataset_dir, "_frame_%02d.png" % i)
        try:
            extract_frame(dst, png)
            frame_pngs.append(png)
        except DatasetError:
            pass
        kept += 1
```

New:

```python
    need = create_min_free_gib(len(clip_paths))
    if _free_gib(adir) < need:
        raise DatasetError("less than %.1f GiB free at %s (needed for %d clips)"
                           % (need, adir, len(clip_paths)))
    # A rebuild with fewer clips must not train on the old ones (bulk action clips spec 2.4.6).
    for stale in (glob.glob(os.path.join(clips_dir, "clip_*.mp4"))
                  + glob.glob(os.path.join(captions_dir, "clip_*.txt"))):
        os.unlink(stale)

    sample = set(contact_sample(len(clip_paths)))
    frame_pngs = []
    kept = 0
    for i, src in enumerate(clip_paths):
        print("clip %d/%d: %s" % (i + 1, len(clip_paths), os.path.basename(src)), flush=True)
        w, h, nb, dur = probe_clip(src)
        clip_frames = min(frames, snap_frames(nb)) if nb else frames
        dst = os.path.join(clips_dir, "clip_%02d.mp4" % i)
        normalize_clip(src, dst, width, height, clip_frames, fps)
        with open(os.path.join(captions_dir, "clip_%02d.txt" % i), "w", encoding="utf-8") as f:
            f.write(texts[i])                     # appearance-free: the motion phrase (and the moves)
        if i in sample:
            png = os.path.join(dataset_dir, "_frame_%02d.png" % i)
            try:
                extract_frame(dst, png)
                frame_pngs.append(png)
            except DatasetError:
                pass
        kept += 1
```

- [ ] **Step 8: `action_dataset.py`, the manifest (spec 2.4.10).** Edit. Old:

```python
                "sources": [os.path.abspath(p) for p in clip_paths]}
```

New:

```python
                "sources": [os.path.abspath(p) for p in clip_paths],
                "items": [{"clip": "clip_%02d.mp4" % i, "source": os.path.abspath(p), "caption": texts[i]}
                          for i, p in enumerate(clip_paths)],
                "source_dir": source_dir,
                "skipped": list(skipped or []),
                "contact_sheet_clips": contact_sample(len(clip_paths))}
```

- [ ] **Step 9: `action_dataset.py`, the preprocess timeout (spec 2.5.6).** Two Edits.

(a) Old:

```python
PREPROCESS_TIMEOUT_S = 1800
TRAIN_TIMEOUT_S = 14400
```

New:

```python
PREPROCESS_TIMEOUT_S = 1800
TRAIN_TIMEOUT_S = 14400


def preprocess_timeout_s(n_clips):
    """PREPROCESS_TIMEOUT_S for up to 80 clips, then 15 s more for each clip."""
    return max(PREPROCESS_TIMEOUT_S, 600 + 15 * n_clips)
```

(b) Old:

```python
                     os.path.join(adir, "logs", "preprocess.log"), LTX2_MLX_DIR, env, PREPROCESS_TIMEOUT_S)
```

New:

```python
                     os.path.join(adir, "logs", "preprocess.log"), LTX2_MLX_DIR, env, preprocess_timeout_s(n_vid))
```

- [ ] **Step 10: `action_dataset.py`, `create`, the exit-3 text and `--dir` (spec 2.6.1, 2.6.2).** Three Edits.

(a) Old:

```python
    if not args.clips or not args.trigger or not args.descriptor:
        return _error("create needs --trigger, --descriptor and at least one --clip")
    try:
        data = build_dataset(args.name, args.trigger, args.descriptor, args.clips,
                             args.performers, width=args.width, height=args.height,
                             frames=args.frames, force=args.force)
```

New:

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

(b) Old:

```python
        print("Error: only %d clip(s); training needs >= %d. The dataset is kept; add more --clip "
              "and run bin/action create %s --regenerate." % (kept, lib.MIN_CLIPS, args.name),
```

New:

```python
        print("Error: only %d clip(s); training needs >= %d. The dataset is kept; add more clips "
              "and run bin/action create %s --regenerate." % (kept, lib.MIN_CLIPS, args.name),
```

(c) Old:

```python
    c.add_argument("--clip", dest="clips", action="append", default=[], metavar="PATH")
    c.add_argument("--performers", type=int, default=0, help="distinct performers across the clips")
```

New:

```python
    c.add_argument("--clip", dest="clips", action="append", default=[], metavar="PATH")
    c.add_argument("--dir", dest="dir", default=None, metavar="DIR", help="a folder of clips named <n>_<n>_<moves>.<ext>; each is captioned from its name")
    c.add_argument("--performers", type=int, default=0, help="distinct performers across the clips")
```

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py 2>&1 | tail -1`

Expected: `3 failed, 16 passed, …`. The three failures are `test_bkt10_both_parsers_take_dir`, `test_bkt11_bin_action_scan_is_read_only_json` and `test_bk_review_focus_2_python_39_runs_scan_and_compiles_the_files`, all of which need `bin/action`.

- [ ] **Step 11: `bin/action`, the docstring, `--dir`, `scan` (spec 2.6.1, 2.6.3, 2.6.4).** Four Edits.

(a) Old:

```python
  bin/action create NAME --trigger PHRASE --descriptor TEXT --clip PATH [--clip PATH ...]
                   [--performers N] [--width W] [--height H] [--frames F] [--force] [--regenerate]
  bin/action train NAME
  bin/action list
  bin/action show NAME

create normalizes operator-supplied reference clips of one action (by varied
performers) into a training dataset and stops for review (dataset/contact_sheet.jpg);
it needs ffmpeg. train trains the motion LoRA from that dataset with ltx-2-mlx; it
```

New:

```python
  bin/action create NAME --trigger PHRASE --descriptor TEXT --clip PATH [--clip PATH ...]
                   [--performers N] [--width W] [--height H] [--frames F] [--force] [--regenerate]
  bin/action create NAME --trigger PHRASE --descriptor TEXT --dir DIR [--performers N] ...
  bin/action train NAME
  bin/action list
  bin/action show NAME
  bin/action scan DIR [--trigger PHRASE]

create normalizes operator-supplied reference clips of one action (by varied
performers) into a training dataset and stops for review (dataset/contact_sheet.jpg);
it needs ffmpeg. --dir replaces --clip: every file named <n>_<n>_<moves>.<ext> in DIR
(not recursive) becomes a clip captioned '<trigger>: <move>, then <move>'; scan
previews that without writing anything. train trains the motion LoRA from that dataset
with ltx-2-mlx; it
```

(b) Old:

```python
    c.add_argument("--clip", dest="clips", action="append", default=[], metavar="PATH")
    c.add_argument("--performers", type=int, default=0, help="distinct performers across the clips (>=3)")
```

New:

```python
    c.add_argument("--clip", dest="clips", action="append", default=[], metavar="PATH")
    c.add_argument("--dir", dest="dir", default=None, metavar="DIR", help="a folder of clips named <n>_<n>_<moves>.<ext>; each is captioned from its name")
    c.add_argument("--performers", type=int, default=0, help="distinct performers across the clips (>=3)")
```

(c) Old:

```python
    s = sub.add_parser("show", help="print one action's record")
    s.add_argument("name")
    return parser
```

New:

```python
    s = sub.add_parser("show", help="print one action's record")
    s.add_argument("name")
    s = sub.add_parser("scan", help="list a folder's clips and the captions their names give (read-only)")
    s.add_argument("dir")
    s.add_argument("--trigger", default=None)
    return parser
```

(d) Old:

```python
    import json
    print(json.dumps(d, indent=2))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "show":
        return cmd_show(args.name)
```

New:

```python
    import json
    print(json.dumps(d, indent=2))
    return 0


def cmd_scan(path, trigger):
    """A folder's clips and the captions their names give, as JSON (read-only; bulk action
    clips spec 2.6.3). Exit 0 even with no match."""
    import json
    try:
        if trigger is not None:
            action_lib.validate_trigger(trigger)
        scan = action_lib.scan_clip_dir(path)
    except action_lib.ActionError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    out = {"dir": scan["dir"], "matched": len(scan["clips"]), "max": action_lib.MAX_DIR_CLIPS,
           "clips": [{"name": c["name"], "path": c["path"], "moves": c["moves"],
                      "caption": action_lib.clip_caption(trigger, c["moves"]) if trigger is not None else None}
                     for c in scan["clips"]],
           "skipped": scan["skipped"]}
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "show":
        return cmd_show(args.name)
    if args.command == "scan":
        return cmd_scan(args.dir, args.trigger)
```

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py 2>&1 | tail -1`

Expected: `19 passed, …`.

- [ ] **Step 12: Run the full relevant test files, the compile check and the pinned-file check.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py tests/test_action_dataset.py tests/test_action_train.py tests/test_action_lib.py tests/test_action_compose.py tests/test_movie_ui_actions.py tests/test_vlm_lifecycle.py tests/test_clean_stop.py 2>&1 | tail -1
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' action_lib.py action_dataset.py bin/action tests/test_action_bulk.py; done
git diff --quiet a87e7992ff17c351aa75e47980977d81b1138e03 -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pinned files unchanged"
python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_builder.py -k mut26 2>&1 | tail -1
```

Expected:
1. 122 tests ran. The only allowed failure is `tests/test_vlm_lifecycle.py::test_bt30_fork_jobs_record_their_vlm_policy`, and only when it is in `../../bk-baseline/base-failures.txt` (the disk reserve). `tests/test_action_dataset.py`, `tests/test_action_train.py` and `tests/test_vlm_lifecycle.py` pass **unedited** (BKT6, BK-AC3).
2. `compiled 4`, twice.
3. `pinned files unchanged`.
4. `1 passed, 11 deselected`.

- [ ] **Step 13: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && git add action_lib.py action_dataset.py bin/action tests/test_action_bulk.py && git diff --cached --name-only && git commit -m "action LoRA: bulk folder clips -- file-name parser, bin/action scan, create --dir with captions from names" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: the four names, each prefixed `qwen-agent-workspace/`, then one commit. `bin/action` keeps mode 100755; Edit does not change the mode.

---

### Task 2: Server Preview, Create with `dir`, the page, route-count pins (spec 2.6.6, 2.7, 2.8, 6.2, 6.3; BKT13-BKT18; Review Focus 3-5)

**Files:**
- Modify `…/qwen-agent-workspace/movie_ui_lib.py`: the `action_argv` clips loop.
- Modify `…/qwen-agent-workspace/movie_ui_server.py`:
  - the route after `POST /api/actions`;
  - the natural sort in `_h_action`;
  - the folder branch in `action_create_errors`;
  - `action_dir_errors` before `create_action_job`;
  - `_h_action_create` fields;
  - `_h_action_preview`;
  - the binding.
- Modify `…/qwen-agent-workspace/static/movie-ui/index.html` (Actions panel) and `…/qwen-agent-workspace/static/movie-ui/app.js`:
  - `ACTION_GALLERY_MAX`;
  - the `openAction` gallery;
  - `actionPreviewSummary` and `renderActionPreview`;
  - the `#a-create` and `#a-preview` listeners.
- Modify `…/qwen-agent-workspace/tests/test_movie_ui_actions.py` (header plus appended tests).
- Modify the route-count pins, `== 66` → `== 67`:
  - `tests/test_movie_ui_http.py`;
  - `tests/test_location_ui.py`;
  - `tests/test_movie_ui_seed_loras.py`;
  - `tests/test_movie_ui_seedfolder.py` (2 occurrences);
  - `tests/test_movie_ui_seedgen.py`.
- Pinned files touched: **none**.

**Interfaces:**
- Consumes (Task 1):
  - `bin/action scan DIR [--trigger PHRASE]`: JSON keys `dir, matched, max, clips[{name, path, moves, caption}], skipped[{name, reason}]`. Exit 2 with `Error: …` on a bad trigger or folder.
  - `bin/action create NAME --trigger T --descriptor D --dir DIR --performers N [--force] [--regenerate]`.
- Consumes (existing):
  - `lib.run_light(argv, cwd)`, `lib.tool_argv(ws_real, tool, *args)`, `lib._argv_safe(value)`;
  - `tool_result(tool, run)`, `_fs_text(name)`, `ApiError(status, message, **extra)`, `ACTION_TRIGGER_RE`, `create_action_job(server, kind, real, fields)`, `newest_job`;
  - the `el`/`clear`/`show`/`$`/`api`/`errorText`/`numberOrNull`/`fileUrl`/`submitAction` helpers in `app.js`;
  - `mt.set_home`, `mt.make_stub_workspace`, `mt.Running`, `mt.api`, `mt.kill_everything`, `mt.status_of`.
- Produces:
  - `movie_ui_server.action_dir_errors(path) -> list of str` ([] or one message).
  - `movie_ui_server._h_action_preview(self, groups, query, body) -> (200, {"dir", "matched", "max", "clips", "skipped"})`, or `ApiError` 400, 502 or 504.
  - The route `("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview")` and `MovieUIHandler.h_action_preview`.
  - Action-create job `fields` key order: `ws, name, trigger, descriptor, dir|clips, performers, force, regenerate`.
  - `lib.action_argv` emits `--dir DIR` instead of the `--clip` list when `fields.get("dir") is not None`.
  - Page ids `a-dir`, `a-preview`, `a-preview-out`, `a-preview-summary`, `a-preview-clips`, `a-preview-skipped`; JS `ACTION_GALLERY_MAX = 24`, `actionPreviewSummary(data)`, `renderActionPreview(data)`.

- [ ] **Step 1: Write the failing tests.** Two Edits to `tests/test_movie_ui_actions.py`.

(a) Old (the head of the file):

```python
"""movie-ui action (motion LoRA) support: the Compose action_loras field, its --action argv,
the bin/action create/train job argv, and the Actions tab's list parsing and field rules."""

import os

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import movie_ui_lib as lib
import movie_ui_server as srv

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
```

New:

```python
"""movie-ui action (motion LoRA) support: the Compose action_loras field, its --action argv,
the bin/action create/train job argv, and the Actions tab's list parsing and field rules.

Bulk action clips (docs/superpowers/specs/2026-11-23-bulk-action-clips-design.md, Section 6.2:
BKT13-BKT18, plus the plan's Review Focus 3-5): the folder field, POST /api/actions/preview, the
natural clip order and the page. The HTTP tests run an in-test movie-ui server on 127.0.0.1 under a
temporary HOME with a stub workspace; the real bin/action and action_lib.py are copied into it
where a test needs them, and no job is ever dispatched.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

import movie_ui_testutil as mt  # noqa: F401  (puts the workspace on sys.path)
import action_lib as al
import movie_ui_lib as lib
import movie_ui_server as srv

DESC = "a spinning kick delivered with the rear leg to head height in one motion"
TRIGGER = "performs a fight combo"
VIDEO_REASON = "not a video (.mp4, .mov, .m4v, .webm, .mkv)"
MOTION_MESSAGE = "trigger must be a Motion: phrase of 1-40 letters, digits, spaces, _ ' or -"
PREVIEW_ROUTE = ("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTION_LIBRARY_DIR", str(tmp_path / "actions"))
    state = mt.set_home(monkeypatch, tmp_path)
    ws = mt.make_stub_workspace(tmp_path)
    running = mt.Running(state)
    yield {"state": state, "ws": ws, "tmp": os.path.realpath(str(tmp_path)), "srv": running}
    running.close()
    mt.kill_everything(state)


def _real_action_tool(ws):
    """The real bin/action and action_lib.py in the stub workspace (scan and show run for real)."""
    shutil.copy2(os.path.join(mt.WS, "bin", "action"), os.path.join(ws, "bin", "action"))
    shutil.copy2(os.path.join(mt.WS, "action_lib.py"), os.path.join(ws, "action_lib.py"))


def _folder(tmp, names):
    """<tmp>/clips holding a zero-byte file for each name."""
    d = os.path.join(tmp, "clips")
    os.makedirs(d)
    for name in names:
        open(os.path.join(d, name), "wb").close()
    return d


def _job(state, payload):
    return lib.read_job(lib.job_dir(state, payload["job"]["id"]))


def _write_action(tmp, name, sources, clips):
    """<tmp>/actions/<name>/action.json (status dataset) and `clips` empty dataset clip files."""
    adir = os.path.join(tmp, "actions", name)
    clips_dir = os.path.join(adir, "dataset", "clips")
    os.makedirs(clips_dir)
    data = al.new_action(name, "performs a roundhouse kick", DESC, sources)
    data["dataset"] = {"clips": clips, "performers": 3, "width": 768, "height": 768, "frames": 97, "fps": 24,
                       "contact_sheet": os.path.join(adir, "dataset", "contact_sheet.jpg")}
    al.write_action(data)
    for i in range(clips):
        open(os.path.join(clips_dir, "clip_%02d.mp4" % i), "wb").close()
    return clips_dir
```

(b) Old (the last line of the file):

```python
    assert srv.action_create_errors(dict(good, clips=[])) == ["give 1 to 64 clip paths"]
```

New:

```python
    assert srv.action_create_errors(dict(good, clips=[])) == ["give 1 to 64 clip paths"]


# --- BKT13-BKT18: bulk action clips ------------------------------------------------------------

def test_bkt13_action_argv_with_a_folder():
    fields = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
              "dir": "/c", "performers": 3, "force": False, "regenerate": False}
    assert lib.action_argv("action-create", fields, "/ws", py="py") == [
        "py", "/ws/bin/action", "create", "roundhouse-kick", "--trigger", "performs a roundhouse kick",
        "--descriptor", DESC, "--dir", "/c", "--performers", "3"]
    assert lib.action_argv("action-create", dict(fields, regenerate=True), "/ws", py="py")[-5:] == [
        "--dir", "/c", "--performers", "3", "--regenerate"]
    assert lib.action_argv("action-create", dict(fields, dir=None, clips=["/c/a.mp4"]), "/ws", py="py")[8:12] == [
        "--clip", "/c/a.mp4", "--performers", "3"]


def test_bkt14_action_create_errors_folder_mode(tmp_path):
    folder = os.path.realpath(str(tmp_path))
    good = {"name": "roundhouse-kick", "trigger": "performs a roundhouse kick", "descriptor": DESC,
            "dir": folder, "performers": 3}
    assert srv.action_create_errors(good) == []
    clip = os.path.join(folder, "kick_01.mp4")
    open(clip, "wb").close()
    assert srv.action_create_errors(dict(good, clips=[clip])) == ["give either clip paths or a folder, not both"]
    assert srv.action_create_errors(dict(good, dir="rel/dir")) == ["folder must be an absolute path"]
    assert srv.action_create_errors(dict(good, dir=5)) == ["folder must be an absolute path"]
    assert srv.action_create_errors(dict(good, dir=folder + "/../x")) == ["folder must not contain '..'"]
    missing = os.path.join(folder, "missing")
    assert srv.action_create_errors(dict(good, dir=missing)) == ["folder %s not found" % missing]
    assert srv.action_create_errors(dict(good, dir=clip)) == ["folder %s not found" % clip]
    locked = os.path.join(folder, "locked")
    os.mkdir(locked)
    os.chmod(locked, 0)
    try:
        if os.geteuid() != 0:
            assert srv.action_create_errors(dict(good, dir=locked)) == ["folder %s is not readable" % locked]
    finally:
        os.chmod(locked, 0o755)
    assert srv.action_create_errors(dict(good, name="X", dir="rel", performers=-1)) == [
        "action name must match [a-z][a-z0-9-]{1,31}", "folder must be an absolute path",
        "performers must be an integer >= 0"]
    assert srv.action_create_errors(dict(good, dir=None, clips=[clip])) == []
    assert srv.action_dir_errors(folder) == []


def test_bkt15_preview_over_http(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    routes = list(srv.ROUTES)
    i = routes.index(("POST", r"/api/actions", "h_action_create", "/api/actions"))
    assert routes[i + 1] == PREVIEW_ROUTE
    assert srv.MovieUIHandler.h_action_preview is srv._h_action_preview
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4", "002_00_punch-high_kick.mp4", "notes.txt"])
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": TRIGGER})
    assert status == 200, data
    assert data == {"dir": d, "matched": 2, "max": 1000, "clips": [
        {"name": "001_00_kick.mp4", "path": os.path.join(d, "001_00_kick.mp4"), "moves": ["kick"],
         "caption": "performs a fight combo: kick"},
        {"name": "002_00_punch-high_kick.mp4", "path": os.path.join(d, "002_00_punch-high_kick.mp4"),
         "moves": ["punch", "high kick"], "caption": "performs a fight combo: punch, then high kick"}],
        "skipped": [{"name": "notes.txt", "reason": VIDEO_REASON}]}
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d})
    assert status == 200 and [c["caption"] for c in data["clips"]] == [None, None]
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": "rel"})[::2] == (
        400, {"error": "invalid fields", "errors": ["folder must be an absolute path"]})
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": "bad:x"})[::2] == (
        400, {"error": "invalid fields", "errors": [MOTION_MESSAGE]})
    assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": 5})[::2] == (
        400, {"error": "invalid fields", "errors": ["trigger must be a string"]})
    assert lib.read_queue(state) == [] and lib.list_job_ids(state) == []
    for token in (None, "wrong-token"):
        assert mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d}, token=token)[::2] == (
            401, {"error": "missing or invalid token"})


def test_bkt16_create_with_a_folder_over_http(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    body = {"ws": ws, "name": "combo-set", "trigger": TRIGGER, "descriptor": DESC, "dir": d, "performers": 3}
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=body)
    assert status == 201, payload
    job = _job(state, payload)
    assert job["kind"] == "action-create"
    assert job["argv"] == [sys.executable, os.path.join(ws, "bin", "action"), "create", "combo-set",
                           "--trigger", TRIGGER, "--descriptor", DESC, "--dir", d, "--performers", "3"]
    assert "--clip" not in job["argv"]
    assert list(job["fields"]) == ["ws", "name", "trigger", "descriptor", "dir", "performers", "force",
                                   "regenerate"]
    assert job["fields"]["dir"] == d and "clips" not in job["fields"]
    assert lib.read_queue(state) == [job["id"]] and mt.status_of(state, job["id"]) == {}
    status, _h, payload = mt.api(s, "POST", "/api/actions",
                                 body=dict(body, clips=[os.path.join(d, "001_00_kick.mp4")]))
    assert (status, payload["errors"]) == (400, ["give either clip paths or a folder, not both"])


def test_bkt17_dataset_clips_sort_naturally(env):
    s, ws = env["srv"], env["ws"]
    _real_action_tool(ws)
    clips_dir = _write_action(env["tmp"], "kick-set", ["/abs/ref0.mp4"], 101)
    status, _h, payload = mt.api(s, "GET", "/api/actions/kick-set?ws=" + ws)
    assert status == 200, payload
    assert [os.path.basename(p) for p in payload["clips"]] == ["clip_%02d.mp4" % i for i in range(101)]
    assert payload["clips"][100] == os.path.join(clips_dir, "clip_100.mp4")


def test_bkt18_the_page_folder_preview_and_gallery_cap():
    static = os.path.join(mt.WS, "static", "movie-ui")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(static, "app.js"), encoding="utf-8") as f:
        js = f.read()
    for element in ("a-dir", "a-preview", "a-preview-out", "a-preview-summary", "a-preview-clips",
                    "a-preview-skipped"):
        assert html.count('id="%s"' % element) == 1, element
    assert html.index('id="a-clips"') < html.index('id="a-dir"') < html.index('id="a-performers"')
    assert html.index('id="a-preview"') < html.index('id="a-create"') < html.index('id="a-preview-out"')
    for text in ('"/api/actions/preview"', "function renderActionPreview(data) {", "const ACTION_GALLERY_MAX = 24;",
                 "give either clip paths or a folder, not both", "res.data.clips.slice(0, ACTION_GALLERY_MAX)",
                 "enter a folder path to preview", "(enter a trigger to see the caption)",
                 '" more clips in the dataset"', "if (dir) { body.dir = dir; } else { body.clips = clips; }"):
        assert text in js, text
    assert js.count("res.data.clips.forEach(") == 1   # the Stories gallery's line; the Actions one is capped
    for name, text in (("index.html", html), ("app.js", js)):
        for pattern in (r"https?://", r"\son[a-z]+=", r"style=", r"\bconfirm\(", r"innerHTML"):
            assert not re.search(pattern, text), (name, pattern)
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", os.path.join(static, "app.js")], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, proc.stderr


# --- Review Focus 3-5 ----------------------------------------------------------------------------

def test_bk_review_focus_3_rebuild_resends_the_folder(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    body = {"ws": ws, "name": "combo-set", "trigger": TRIGGER, "descriptor": DESC, "dir": d, "performers": 3}
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=body)
    assert status == 201, payload
    first = _job(state, payload)
    _write_action(env["tmp"], "combo-set", [os.path.join(d, "001_00_kick.mp4")], 1)
    status, _h, detail = mt.api(s, "GET", "/api/actions/combo-set?ws=" + ws)
    assert status == 200, detail
    assert detail["last_create_fields"] == first["fields"]
    # app.js Rebuild: Object.assign({}, S.action.last_create_fields, {regenerate: true})
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=dict(detail["last_create_fields"], regenerate=True))
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[-5:] == ["--dir", d, "--performers", "3", "--regenerate"] and "--clip" not in argv
    clip = os.path.join(d, "001_00_kick.mp4")
    status, _h, payload = mt.api(s, "POST", "/api/actions", body=dict(body, name="clip-set", dir=None, clips=[clip]))
    assert status == 201, payload
    job = _job(state, payload)
    assert "--dir" not in job["argv"] and job["argv"][job["argv"].index("--clip") + 1] == clip
    assert "dir" not in job["fields"] and job["fields"]["clips"] == [clip]


def test_bk_review_focus_4_preview_captions_use_the_normalized_trigger(env):
    s, ws, state = env["srv"], env["ws"], env["state"]
    _real_action_tool(ws)
    d = _folder(env["tmp"], ["001_00_kick.mp4"])
    loose = "  performs   a fight combo "
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": loose})
    assert status == 200, data
    assert data["clips"][0]["caption"] == "performs a fight combo: kick"
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": "   "})
    assert status == 200 and data["clips"][0]["caption"] is None
    status, _h, payload = mt.api(s, "POST", "/api/actions", body={"ws": ws, "name": "combo-set", "trigger": loose,
                                                                  "descriptor": DESC, "dir": d, "performers": 3})
    assert status == 201, payload
    argv = _job(state, payload)["argv"]
    assert argv[argv.index("--trigger") + 1] == TRIGGER


def test_bk_review_focus_5_preview_needs_only_action_lib(env):
    s, ws = env["srv"], env["ws"]
    with open(os.path.join(mt.WS, "movie_ui_server.py"), encoding="utf-8") as f:
        source = f.read()
    assert not re.search(r"^\s*(import|from)\s+action_(lib|dataset)\b", source, re.M)
    _real_action_tool(ws)
    assert not os.path.exists(os.path.join(ws, "action_dataset.py"))
    d = _folder(env["tmp"], [])
    status, _h, data = mt.api(s, "POST", "/api/actions/preview", body={"ws": ws, "dir": d, "trigger": TRIGGER})
    assert (status, data) == (200, {"dir": d, "matched": 0, "max": 1000, "clips": [], "skipped": []})
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_actions.py 2>&1 | tail -1`

Expected: `9 failed, 4 passed, …`. The four existing tests pass. Review Focus 5 fails on a 405, because the POST route is missing.

- [ ] **Step 3: `movie_ui_lib.py`, `action_argv` (spec 2.7.5).** Edit. Old:

```python
    for path in fields["clips"]:
        argv += ["--clip", path]
```

New:

```python
    if fields.get("dir") is not None:
        argv += ["--dir", fields["dir"]]
    else:
        for path in fields["clips"]:
            argv += ["--clip", path]
```

- [ ] **Step 4: `movie_ui_server.py` (spec 2.6.6, 2.7.1-2.7.4, 2.7.6).** Six Edits.

(a) The route. Old:

```python
    ("POST", r"/api/actions", "h_action_create", "/api/actions"),
```

New:

```python
    ("POST", r"/api/actions", "h_action_create", "/api/actions"),
    ("POST", r"/api/actions/preview", "h_action_preview", "/api/actions/preview"),
```

(b) The natural sort. Old:

```python
            clips = sorted(os.path.join(clips_dir, n) for n in os.listdir(clips_dir) if n.endswith(".mp4"))
```

New:

```python
            clips = [os.path.join(clips_dir, n) for n in sorted((n for n in os.listdir(clips_dir) if n.endswith(".mp4")),
                                                                key=lambda n: (len(n), n))]
```

(c) The folder branch. Old:

```python
    if not (isinstance(clips, list) and 1 <= len(clips) <= ACTION_MAX_CLIPS):
        errors.append("give 1 to %d clip paths" % ACTION_MAX_CLIPS)
    else:
```

New:

```python
    folder = body.get("dir")
    if folder is not None:
        if clips is not None:
            errors.append("give either clip paths or a folder, not both")
        else:
            errors += action_dir_errors(folder)
    elif not (isinstance(clips, list) and 1 <= len(clips) <= ACTION_MAX_CLIPS):
        errors.append("give 1 to %d clip paths" % ACTION_MAX_CLIPS)
    else:
```

(d) The folder rule. Old:

```python
def create_action_job(server, kind, real, fields):
```

New:

```python
def action_dir_errors(path):
    """The folder rule of POST /api/actions and POST /api/actions/preview (bulk action clips spec
    2.7.2): [] when it passes, else a one-element list with the first failure."""
    if not (isinstance(path, str) and os.path.isabs(path) and lib._argv_safe(path)):
        return ["folder must be an absolute path"]
    if ".." in path.split("/"):
        return ["folder must not contain '..'"]
    if not os.path.isdir(path):
        return ["folder %s not found" % _fs_text(path)]
    if not os.access(path, os.R_OK | os.X_OK):
        return ["folder %s is not readable" % _fs_text(path)]
    return []


def create_action_job(server, kind, real, fields):
```

(e) The create fields and the Preview handler. Old:

```python
    fields = {"ws": real, "name": body["name"], "trigger": " ".join(body["trigger"].split()),
              "descriptor": " ".join(body["descriptor"].split()), "clips": list(body["clips"]),
              "performers": body["performers"], "force": body.get("force", False),
              "regenerate": body.get("regenerate", False)}
    return create_action_job(self.server, "action-create", real, fields)
```

New:

```python
    fields = {"ws": real, "name": body["name"], "trigger": " ".join(body["trigger"].split()),
              "descriptor": " ".join(body["descriptor"].split())}
    if body.get("dir") is not None:
        fields["dir"] = body["dir"]
    else:
        fields["clips"] = list(body["clips"])
    fields["performers"] = body["performers"]
    fields["force"] = body.get("force", False)
    fields["regenerate"] = body.get("regenerate", False)
    return create_action_job(self.server, "action-create", real, fields)


def _h_action_preview(self, groups, query, body):
    """A folder's clips, captions and skipped files from bin/action scan; creates no job and writes
    nothing (bulk action clips spec 2.7.6)."""
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

(f) The binding. Old:

```python
MovieUIHandler.h_action_create = _h_action_create
MovieUIHandler.h_action_train = _h_action_train
```

New:

```python
MovieUIHandler.h_action_create = _h_action_create
MovieUIHandler.h_action_preview = _h_action_preview
MovieUIHandler.h_action_train = _h_action_train
```

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_actions.py 2>&1 | tail -1`

Expected: `1 failed, 12 passed`. Only `test_bkt18_the_page_folder_preview_and_gallery_cap` fails; the page is still unchanged.

- [ ] **Step 5: The six route-count pins (spec 6.3, F7).**

Run first: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token tests/test_movie_ui_seed_loras.py::test_cl_t25_the_routes tests/test_movie_ui_seedfolder.py::test_sdt11_the_route_and_its_token tests/test_movie_ui_seedfolder.py::test_sdt29_the_characters_route_and_its_token tests/test_movie_ui_seedgen.py::test_sgt20_the_routes 2>&1 | tail -1`

Expected: `6 failed` (`assert 67 == 66`).

Then Edit, old `    assert len(srv.ROUTES) == 66` → new `    assert len(srv.ROUTES) == 67`:
- once in each of `tests/test_movie_ui_http.py`, `tests/test_location_ui.py`, `tests/test_movie_ui_seed_loras.py` and `tests/test_movie_ui_seedgen.py`;
- with `replace_all` (exactly 2 occurrences) in `tests/test_movie_ui_seedfolder.py`.

Nothing else in those files changes.

Rerun the same command. Expected: `6 passed`. Then `grep -rn "len(srv.ROUTES) == 6" tests/` prints exactly six lines, all `== 67`.

- [ ] **Step 6: `static/movie-ui/index.html` (spec 2.8).** Three Edits.

(a) Old:

```html
  <p class="muted">One named move per action (e.g. a roundhouse kick), from at least 8 reference clips by at least 3 different performers, so the LoRA learns the motion and not a face.</p>
```

New:

```html
  <p class="muted">One named move per action (e.g. a roundhouse kick), from at least 8 reference clips by at least 3 different performers, so the LoRA learns the motion and not a face. Or give one folder of clips named &lt;n&gt;_&lt;n&gt;_&lt;moves&gt;.mp4 (e.g. 006_00_high_kick-stance-front_kick.mp4): each clip is captioned with the trigger and its moves.</p>
```

(b) Old:

```html
    <label class="wide">Clips <textarea id="a-clips" rows="6" cols="70" spellcheck="false" placeholder="one absolute path per line: /Users/me/clips/kick_01.mp4"></textarea></label>
```

New:

```html
    <label class="wide">Clips <textarea id="a-clips" rows="6" cols="70" spellcheck="false" placeholder="one absolute path per line: /Users/me/clips/kick_01.mp4"></textarea></label>
    <label class="wide">Folder <input id="a-dir" type="text" size="70" spellcheck="false" placeholder="or one absolute folder path instead of clips: /Users/me/fight_clips"></label>
```

(c) Old:

```html
  <div class="row"><button id="a-create" type="button">Create dataset</button> <span id="a-create-status" class="muted"></span></div>
```

New:

```html
  <div class="row"><button id="a-preview" type="button">Preview folder</button> <button id="a-create" type="button">Create dataset</button> <span id="a-create-status" class="muted"></span></div>
  <div id="a-preview-out" hidden>
    <p id="a-preview-summary" class="muted"></p>
    <table id="a-preview-clips" class="list"><thead><tr><th>File</th><th>Moves</th><th>Caption</th></tr></thead><tbody></tbody></table>
    <table id="a-preview-skipped" class="list"><thead><tr><th>Skipped file</th><th>Reason</th></tr></thead><tbody></tbody></table>
  </div>
```

- [ ] **Step 7: `static/movie-ui/app.js` (spec 2.8).** Three Edits.

(a) Old:

```js
  const SEEDS_MAX = 100;   // seed-folder spec 1.1: the most seeds in one run
```

New:

```js
  const SEEDS_MAX = 100;   // seed-folder spec 1.1: the most seeds in one run
  const ACTION_GALLERY_MAX = 24;   // bulk action clips spec 2.8: dataset clips shown as videos
```

(b) The gallery cap. The `res.data.clips.forEach(...)` line also occurs in the Stories gallery, so the old text includes the unique next line. Old:

```js
    res.data.clips.forEach(function (p) { gallery.appendChild(el("video", {src: fileUrl(p), controls: "", preload: "metadata"})); });
    $("#a-status").textContent = "";
```

New:

```js
    res.data.clips.slice(0, ACTION_GALLERY_MAX).forEach(function (p) { gallery.appendChild(el("video", {src: fileUrl(p), controls: "", preload: "metadata"})); });
    if (res.data.clips.length > ACTION_GALLERY_MAX) {
      gallery.appendChild(el("p", {cls: "muted", text: "and " + (res.data.clips.length - ACTION_GALLERY_MAX) + " more clips in the dataset"}));
    }
    $("#a-status").textContent = "";
```

(c) The preview functions and the listeners. Old:

```js
  function setupActions() {
    $("#a-create").addEventListener("click", function () {
      const clips = $("#a-clips").value.split("\n").map(function (l) { return l.trim(); })
        .filter(function (l) { return l; });
      submitAction({name: $("#a-name").value.trim(), trigger: $("#a-trigger").value.trim(),
                    descriptor: $("#a-descriptor").value.trim(), clips: clips,
                    performers: numberOrNull("#a-performers") || 0, force: $("#a-force").checked,
                    regenerate: false}, $("#a-create-status"));
    });
```

New:

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

  function setupActions() {
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

The Rebuild and Train listeners that follow are unchanged.

Run: `cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_movie_ui_actions.py 2>&1 | tail -1`

Expected: `13 passed`.

- [ ] **Step 8: Run the full relevant test files and compare with the baseline.** About 4 minutes.

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && python3 -m pytest -q -p no:cacheprovider tests/test_action_bulk.py tests/test_action_dataset.py tests/test_action_train.py tests/test_action_lib.py tests/test_action_compose.py tests/test_movie_ui_actions.py tests/test_vlm_lifecycle.py tests/test_clean_stop.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seed_loras.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py tests/test_lora_scope_ui.py tests/test_motion_beat_only_ui.py tests/test_movie_ui_extra_refs.py tests/test_movie_ui_qwen_edit.py tests/test_movie_ui_builder.py tests/test_location_lib.py tests/test_movie_ui_seams.py tests/test_movie_ui_shots_seed.py tests/test_movie_ui_shots_zimage.py tests/test_soft_panel_count.py tests/test_lora_scope_fix.py tests/test_movie_ui_batch.py tests/test_movie_ui_jobs.py tests/test_movie_ui_progress.py 2>&1 | tee ../../bk-baseline/task2.log | grep -E '^(FAILED|ERROR) ' | sed 's/ - .*//' | sort > ../../bk-baseline/task2-failures.txt; tail -1 ../../bk-baseline/task2.log; comm -13 ../../bk-baseline/base-failures.txt ../../bk-baseline/task2-failures.txt
```

Expected: the summary line (about 640 tests), then **nothing** from `comm`, meaning no failure outside the Step 0 baseline list. At 19.4 GiB free during planning, the UI files gave `25 failed, 496 passed, 2 skipped`, with exactly the base `test_movie_ui_http.py` batch-fork set (`not enough free space … at least 20 GiB must stay free`). `comm` printing any line is a stop-and-report.

- [ ] **Step 9: Compile check, pinned-file check, and the BASELINE bump decision.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' movie_ui_lib.py movie_ui_server.py tests/test_movie_ui_actions.py; done
node --check static/movie-ui/app.js && echo "app.js ok"
git diff --name-only HEAD
git diff --quiet a87e7992ff17c351aa75e47980977d81b1138e03 -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py && echo "pinned files unchanged"
```

Expected:
1. `compiled 3`, twice.
2. `app.js ok`.
3. Exactly ten paths, each prefixed `qwen-agent-workspace/`: `movie_ui_lib.py`, `movie_ui_server.py`, `static/movie-ui/app.js`, `static/movie-ui/index.html`, `tests/test_location_ui.py`, `tests/test_movie_ui_actions.py`, `tests/test_movie_ui_http.py`, `tests/test_movie_ui_seed_loras.py`, `tests/test_movie_ui_seedfolder.py`, `tests/test_movie_ui_seedgen.py`.
4. `pinned files unchanged`.

**Bump nothing.** Neither task touched a `PIPELINE_FILES` member (`bin/ltx-movie`, `story_engine.py`, …), so `tests/test_movie_ui_builder.py` keeps `BASELINE = "a87e7992ff17c351aa75e47980977d81b1138e03"`. `movie_ui_lib.py` is not pinned by `test_mut26`. `test_mut25` compiles it and scans its imports, and Step 8 ran that. Only if `pinned files unchanged` is not printed: stop and report. Do not edit BASELINE.

- [ ] **Step 10: Commit.**

```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/bk-wt/qwen-agent-workspace && git add movie_ui_lib.py movie_ui_server.py static/movie-ui/index.html static/movie-ui/app.js tests/test_movie_ui_actions.py tests/test_movie_ui_http.py tests/test_location_ui.py tests/test_movie_ui_seed_loras.py tests/test_movie_ui_seedfolder.py tests/test_movie_ui_seedgen.py && git diff --cached --name-only && git commit -m "movie UI: Actions folder field, Preview (POST /api/actions/preview) and Create with dir; dataset clips sort naturally" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: the ten names, then one commit.

- [ ] **Step 11 (controller): full suite, review, live checks.**
  1. Run `python3 -m pytest -q -p no:cacheprovider tests/` into `../../bk-baseline/full-after-failures.txt`, in the same way as Step 0.2. `comm -13 full-base-failures.txt full-after-failures.txt` must be empty.
  2. A `design-reviewer` (Opus) reviews both commits before the feature is declared done.
  3. Hand live checks BKL1-BKL6 (spec Section 7) to the user. Nobody accesses macstudio.

---

## Risks and failure modes (not changed by this plan; for the reviewer)

- **Partial rebuilds.** A rebuild that fails part-way (a corrupt clip #150 of 300) has already deleted the old `clip_*` files. It leaves the new clips 0-149 and the old `action.json` (clip count 300), and `bin/action train` would train on the 150 clips present. This is the same class of failure as before: today it leaves a mix of new and old clips. It is reported, not fixed.
- **`GET /api/actions/preview`** still matches the GET `_ACTION` route as the action name `preview` and gives 502 `action exited 2`. This is existing behaviour (spec 0.2) and only POST is used.
- **Preview timeout.** Preview runs under `LIGHT_TIMEOUT = 60` s (504 past it). Listing and statting 1000 entries takes well under a second, even on the external HDD. A drive that is spinning up can add a few seconds.
- **Exact pins on wording.** The six route pins and the hygiene regexes are exact. A stray `onclick=` or `style=` in a new string would fail `test_mut24` and the seed-loras pin.
- **Disk reserve.** At about 16-22 GiB free, about 25 `test_movie_ui_http.py` batch-fork tests and `test_vlm_lifecycle.py::test_bt30` fail at base on the 20 GiB batch-fork reserve. Step 0.2's list is how they are told apart from regressions.

