# bin/iterate-story Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `bin/iterate-story`, which repeats judge -> revise prompt -> regenerate -> re-judge on one story-id until a threshold, plateau, or max-rounds stop and then promotes the best-scoring archived round to the live files, together with the three `bin/ltx-movie` companion changes it depends on (`--story-prompt-override`, `--danger-auto-approve` passthrough under `--force-story --no-review`, and `--story-only` with an optional `narrative`).
**Architecture:** `bin/iterate-story` is one standalone stdlib-only script. It drives `bin/judge-story` and `bin/ltx-movie` purely as subprocesses through a single `subprocess.run` helper. Pure helpers (panel-count pin, prompt re-injection, version scan, stop rule, best-round rule) sit under a `main()` loop that archives each judged triple under the next free `.vN`, regenerates with `bin/ltx-movie --story-only --story-prompt-override`, detects no-op regenerations by sha256, and always promotes the best archived round. `bin/ltx-movie` gets three small, localized edits in `build_parser()`, `phase1_story()`, `_phase_sequence()` and `main()`, and nothing else in it changes.
**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), standard library only (`argparse`, `datetime`, `hashlib`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`), `pytest` 8.3.4. `bin/ltx-movie` must also still parse under Apple `/usr/bin/python3` 3.9.6, because it ships in the deploy package.
**Spec:** docs/superpowers/specs/2026-10-03-iterate-story-design.md

## Global Constraints

- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Every command below starts with `cd` into it. The git repo root is one level up, so `git diff --cached --name-only` prints paths with the `qwen-agent-workspace/` prefix.
- Exactly four files change (spec 0.3): create `bin/iterate-story` (`chmod +x`), create `tests/test_iterate_story.py`, create `tests/test_ltx_movie_iterate_flags.py`, and edit `bin/ltx-movie`. Nothing else is created or modified. In particular, `bin/judge-story`, `bin/qwen-agent`, `tests/test_ltx_movie_offline.py` and `tests/test_deploy_pkg.py` are not touched.
- `bin/ltx-movie` changes only as spec Sections 4.1, 4.2 and 4.3 specify. Across Tasks 1-3 that is 37 lines added and 4 removed. Do not touch the `cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),` lines, the `cmd += ["--user-prompt", prompt]` line, or anything in `_print_dry_run_plan()` (guards L19, L1z9, L1z14, L29f, L29g; G11). Do not add `import re` (guard L7j fails on it). Use only constructs that Python 3.9 parses (deploy package, spec 4.4).
- `bin/iterate-story` conventions (spec 1.1):
  - shebang `#!/usr/bin/env python3`, a module docstring, no file extension, executable bit set;
  - `def main(argv=None):` returns an `int`, and the file ends with `if __name__ == "__main__":` / `    sys.exit(main())`;
  - no import from any `bin/*` file and no shared module.
- Top-level imports of `bin/iterate-story` are exactly `argparse, datetime, hashlib, json, os, re, shutil, subprocess, sys, tempfile`. That is spec 1.1's list plus `hashlib`, which spec 1.6 and 3.5 require for `story_md_hash` (Appendix A, R1).
- Constants, verbatim (spec 1.6):
  - `SCORE_KEYS = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")`
  - `DEFAULT_MAX_ROUNDS = 5`
  - `STOP_THRESHOLD = "threshold met"`, `STOP_PLATEAU = "plateaued"`, `STOP_MAX_ROUNDS = "max-rounds reached"`
  - `TAIL_LINES = 40`
  - `VERSION_RE = re.compile(r"(?:story\.v(\d+)\.md|story_prompt\.v(\d+)\.txt|judgment\.v(\d+)\.json)")`
  - `PANEL_COUNT_DECLARATION_RE = re.compile(r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\.")`
- Spec 1.6's public names are used verbatim. This plan adds only four private helpers: `_run`, `_tail`, `_archive`, `_write_summary`.
- Every child call is exactly `subprocess.run(cmd, cwd=WS, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)`. No `timeout=`. The environment is inherited, and `ANTHROPIC_API_KEY` is never read, printed, or written.
- Judge argv: `[sys.executable, <WS>/bin/judge-story, "--story-id", id]`.
- Regeneration argv: `[sys.executable, <WS>/bin/ltx-movie, "--story-id", id, "--panels", str(pinned), "--force-story", "--no-review", "--story-only", "--story-prompt-override", <tmp path>]`. It never includes `narrative` or `--danger-auto-approve` (SC13).
- Exit codes: 0 for any stop, 1 for E5/E6/E6b, 2 for argparse, range checks, and E2-E4. Every error goes to stderr and starts with `Error: `. Exceptions outside the spec 6 table propagate as tracebacks.
- Stdout carries only the `Round N: ...` lines and the final `Stopped: ...` line (spec 5.1).
- `run-summary.json`: keys `stop_reason, best_round, rounds`; `json.dump(obj, f, indent=2, ensure_ascii=False)` plus `"\n"`; written on every run that reaches the round loop (spec 5.2).
- Archive suffix for round `r` is `v<find_version_base(story_dir) + r>`. An existing `.vN` file is never overwritten.
- Tests: pytest with plain `assert`; never the `check()` helper. Exactly **27** test functions, one per spec test ID, and multi-case IDs loop inside one function:
  - 16 in `tests/test_iterate_story.py`: T-P1 T-P2 T-P2b T-P3 T-P4 T-P5 T-M1 T-M2 T-M3 T-M4 T-M5 T-M6 T-M6b T-M7 T-M8 T-M9
  - 11 in `tests/test_ltx_movie_iterate_flags.py`: T-L1 to T-L11

  Extra coverage goes in as extra assertions inside those functions, never as new test functions, so A1's count stays exact.
- No real subprocess, API, or generation call in any test (SC9). Autouse fixtures make `subprocess.run` fail, and in D4 `subprocess.Popen` too. Every story dir lives under `tmp_path`.
- R1 baseline, measured 2026-10-03 before any change: `python3 tests/test_ltx_movie_offline.py` exits 0 and its last line is `OK 340/340`. Run it directly; under pytest it gives false greens. R2 baseline: `python3 -m pytest tests/test_judge_story.py` gives `18 passed`.
- Expected pytest noise:
  - one `DeprecationWarning` per test file for `SourceFileLoader.load_module()`, the loader spec 7.1 mandates (`1 warning` per file, `2 warnings` when both files run);
  - a `pytest_asyncio` `PytestDeprecationWarning` on stderr at startup.

  Neither is a failure.
- Mutation runners:
  - Give every pytest subprocess a fresh `PYTHONPYCACHEPREFIX`. Without it, a same-size mutation can load a stale `.pyc` and falsely survive (observed in the judge-story plan).
  - Each runner restores the file byte-for-byte and asserts the restore. Never commit with a mutation in place.
- Commit hygiene: the working tree has unrelated modified and untracked files (`bin/qwen-agent`, `bin/ltx-story-video`, `.gitignore`, and others).
  - Stage only by explicit path. Each commit command is guarded so that it runs only if `git diff --cached --name-only` lists exactly that task's files.
  - Commit on the current branch, `qwen-agent-redteam`, where the judge-story and spec commits landed. Do not push.
  - Trailer: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Provenance: every code block below was executed task-by-task in a throwaway `/tmp` sandbox copy of the workspace on 2026-10-03. Every Step 2 and Step 4 expectation held, all 19 mutation runs were CAUGHT, A1 gave `27 passed`, R1 gave `OK 340/340`, and R2 gave `18 passed`. If a step's real output differs from what this plan says, stop and report; do not adapt the code.

## Review Focus

1. **The regeneration call doesn't fit the real `bin/ltx-movie`.**
   - What goes wrong: without `--story-only`, each round stops the story server and runs Phases 2-4 (GPU stills and a full render). Without `--panels <pinned>`, a 20-panel story fails 15-panel validation. Without an optional `narrative`, every call dies in argparse. Without `--danger-auto-approve` under `--force-story --no-review`, the `write_file` overwrite is denied with `eof_stdin_unattended`.
   - The reverse failure: the bypass must not leak into a plain interactive `--force-story` run.
   - Tests: T-M2 (Task 7), T-L1-T-L4 (Task 2), T-L8, T-L10, T-L11 (Task 3).
2. **Panel-count drift.** The judge's `revised_prompt` asked for "EXACTLY 30 panel sections" on a 20-panel story (the observed incident). The prompt sent to regeneration must state the pinned count exactly once, last, with the conflicting sentence removed. Tests: T-P2, T-P2b (Task 4), T-M2's override-content check (Task 7).
3. **A silent no-op regeneration.** When `qwen-agent` fails but a stale `story.md` exists, `bin/ltx-movie` exits 0. The loop must not re-judge the unchanged story as if it were new: it must fail with E6b, promote, and exit 1. Test: T-M9 (Task 8).
4. **Overwriting the user's hand-made history.** `ronin-generalship` already has `.v1`/`.v2` of all three kinds. A stray `judgment.vN.json` or a two-digit `N` must also push the base up. Tests: T-P3 (Task 5), T-M3 (Task 7).
5. **A mid-loop failure that leaves the live files wrong.** Examples: a `GARBAGE` `story.md` from a failed regeneration, a regenerated story with no judgment, or `story_prompt.revised.txt` from a different round than `judgment.json`. Promotion must restore a consistent judged triple on every failure path, and must leave the files untouched when no round completed. Tests: T-M3's `story_prompt.revised.txt` check (Task 7), T-M5, T-M6, T-M6b (Task 8).

---

### Task 1: bin/ltx-movie `--story-prompt-override` (spec 4.1)

**Files:**
- Modify: `bin/ltx-movie`. Line numbers are as of the unmodified file.
  - `build_parser()`: insert 6 lines after line 263 (`--force-story`).
  - `phase1_story()`: replace lines 663-665 (`prompt = build_story_prompt(...)`) with 7 lines.
  - `main()`: insert 5 lines before line 1114 (`if args.dry_run:`).
  - Net `git diff --numstat`: `18	3`.
- Create: `tests/test_ltx_movie_iterate_flags.py` (the D4 scaffold plus T-L5, T-L6, T-L7).
- Test: `tests/test_ltx_movie_iterate_flags.py`

**Interfaces:**
- Consumes: existing `bin/ltx-movie` symbols:
  - `build_parser()`, `main(argv=None)`, `phase1_story(args)`
  - `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds)`, `_clip_seconds(args)`, `_story_dir(story_id)`
  - module globals `WS` and `subprocess`
- Produces:
  - CLI flag `--story-prompt-override PATH` -> `args.story_prompt_override` (`str` or `None`). `main()` returns 2 when PATH is not a regular file. `phase1_story()` sends PATH's content verbatim as `--user-prompt` and writes it to `story_prompt.txt`.
  - Test helpers used by Tasks 2 and 3: the `popen_calls` fixture, `_run_phase1(argv)`, `_phase1_with_narrative(flags)`, `_story_prompt_txt(tmp_path)`, `STORY_ID`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ltx_movie_iterate_flags.py` with the Write tool, with exactly this content. The file ends with a single newline.

```python
"""Tests for bin/ltx-movie's bin/iterate-story companion flags (spec D3/D4).

Spec: docs/superpowers/specs/2026-10-03-iterate-story-design.md (Sections 4 and 7.4).
Run from the workspace root: python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a real subprocess call: the autouse fixture below makes
subprocess.Popen and subprocess.run fail the test, and tests that reach Phase 1's
qwen-agent call install a recording fake over Popen first (the popen_calls fixture).
Exactly one test function per spec test ID, T-L1 through T-L11 (11 total).
"""

import importlib.machinery
import os

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ltx_movie = importlib.machinery.SourceFileLoader(
    "ltx_movie_iterate_flags", os.path.join(WS, "bin", "ltx-movie")).load_module()

STORY_ID = "iterate-flags"


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """SC9 guard for every test: any real subprocess call from bin/ltx-movie fails it."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test made a real subprocess call")
    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)


class _FakeProc(object):
    """Stands in for the qwen-agent child: exits 1 and writes no story.md, so
    phase1_story returns 1 right after building and recording its command."""
    returncode = 1

    def communicate(self, timeout=None):
        return "", None


@pytest.fixture
def popen_calls(tmp_path, monkeypatch):
    """Point ltx_movie.WS at tmp_path, create the story dir, and record every Popen cmd.
    Requested explicitly, so it runs after the autouse guard and overrides its Popen."""
    monkeypatch.setattr(ltx_movie, "WS", str(tmp_path))
    (tmp_path / "generated" / "stories" / STORY_ID).mkdir(parents=True)
    calls = []

    def _recording_popen(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(ltx_movie.subprocess, "Popen", _recording_popen)
    return calls


def _run_phase1(argv):
    args = ltx_movie.build_parser().parse_args(argv)
    ltx_movie.phase1_story(args)
    return args


def _phase1_with_narrative(flags):
    return _run_phase1(["a narrative", "--story-id", STORY_ID, "--panels", "1"] + list(flags))


def _story_prompt_txt(tmp_path):
    path = tmp_path / "generated" / "stories" / STORY_ID / "story_prompt.txt"
    return path.read_text(encoding="utf-8")


# --- T-L5..T-L7: --story-prompt-override (spec 4.1) -----------------------------------

def test_tl5_story_prompt_override_used_verbatim(tmp_path, popen_calls):
    override = tmp_path / "override.txt"
    content = "Override — prompt\nline 2\n"
    override.write_text(content, encoding="utf-8")
    _phase1_with_narrative(["--story-prompt-override", str(override)])
    assert len(popen_calls) == 1
    assert popen_calls[0][-2] == "--user-prompt"
    assert popen_calls[0][-1] == content
    assert _story_prompt_txt(tmp_path) == content


def test_tl6_default_prompt_unchanged_without_override(tmp_path, popen_calls):
    args = _phase1_with_narrative([])
    expected = ltx_movie.build_story_prompt("a narrative", STORY_ID, 1, False, False,
                                            seconds=ltx_movie._clip_seconds(args))
    assert len(popen_calls) == 1
    assert popen_calls[0][-1] == expected
    assert _story_prompt_txt(tmp_path) == expected


def test_tl7_missing_override_file_exits_2(tmp_path, popen_calls, capsys):
    rc = ltx_movie.main(["a narrative", "--story-id", STORY_ID,
                         "--story-prompt-override", str(tmp_path / "missing.txt")])
    assert rc == 2
    assert "--story-prompt-override file not found" in capsys.readouterr().err
    assert popen_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

First confirm the R1 baseline, then run the new tests.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/iterate_story_r1_before.txt 2>&1; echo "rc=$?"; tail -1 /tmp/iterate_story_r1_before.txt
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
```
Expected for R1: `rc=0` and `OK 340/340`. If the count differs, stop and report, because the baseline is stale.

Expected for pytest: `2 failed, 1 passed`.
- `test_tl5_story_prompt_override_used_verbatim` and `test_tl7_missing_override_file_exits_2` fail with `SystemExit: 2` (`ltx-movie: error: unrecognized arguments: --story-prompt-override ...`).
- `test_tl6_default_prompt_unchanged_without_override` passes. It pins today's default path, which this task must not change.

- [ ] **Step 3: Write minimal implementation**

Make three Edit-tool edits to `bin/ltx-movie`. Each `old_string` is unique in the file.

Edit 1 (`build_parser()`). old_string:
```python
    parser.add_argument("--force-story", dest="force_story", action="store_true", default=False)
```
new_string:
```python
    parser.add_argument("--force-story", dest="force_story", action="store_true", default=False)
    parser.add_argument("--story-prompt-override", dest="story_prompt_override",
                         metavar="PATH", default=None,
                         help="use the content of PATH verbatim as the Phase 1 story prompt "
                              "instead of building it from the narrative; it is still "
                              "persisted to story_prompt.txt. Only takes effect when Phase 1 "
                              "actually runs (story.md absent, or --force-story).")
```

Edit 2 (`phase1_story()`). The 8-space indentation makes this unique: `_print_dry_run_plan()`'s call at line 979 is indented 4 spaces, and you must not touch it. old_string:
```python
        prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                     bool(getattr(args, "seed_image", None)),
                                     seconds=_clip_seconds(args))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
```
new_string:
```python
        if args.story_prompt_override is not None:
            with open(args.story_prompt_override, encoding="utf-8") as f:
                prompt = f.read()
        else:
            prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                         bool(getattr(args, "seed_image", None)),
                                         seconds=_clip_seconds(args))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
```

Edit 3 (`main()`, after the `--seed-image`/`--no-stills` conflict check). old_string:
```python
    if args.dry_run:
        return _print_dry_run_plan(args)
```
new_string:
```python
    if args.story_prompt_override is not None and not os.path.isfile(args.story_prompt_override):
        print("Error: --story-prompt-override file not found: %s" % args.story_prompt_override,
              file=sys.stderr)
        return 2

    if args.dry_run:
        return _print_dry_run_plan(args)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/iterate_story_r1_t1.txt 2>&1; echo "rc=$?"; tail -1 /tmp/iterate_story_r1_t1.txt
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --numstat -- bin/ltx-movie
```
Expected:
- pytest: `3 passed, 1 warning`
- R1: `rc=0`, `OK 340/340`
- numstat: `18	3	qwen-agent-workspace/bin/ltx-movie`

Next, the negative controls (spec 7.5 rows "Override read but `build_story_prompt` result still used" and "Override missing-file check removed"). The script restores the file itself:
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 override read but build_story_prompt result still used", "bin/ltx-movie",
     [('        else:\n            prompt = build_story_prompt(args.narrative,', '        if True:\n            prompt = build_story_prompt(args.narrative,')],
     L, ['test_tl5_story_prompt_override_used_verbatim']),
    ("7.5 override missing-file check removed from main()", "bin/ltx-movie",
     [('    if args.story_prompt_override is not None and not os.path.isfile(args.story_prompt_override):\n', '    if False:\n')],
     L, ['test_tl7_missing_override_file_exits_2']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: two `... CAUGHT` lines, then `ALL 2 MUTATIONS CAUGHT; sources restored`. Afterwards `git diff --numstat -- bin/ltx-movie` still prints `18	3`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/ltx-movie tests/test_ltx_movie_iterate_flags.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/ltx-movie\nqwen-agent-workspace/tests/test_ltx_movie_iterate_flags.py')" && git commit -m "ltx-movie: add --story-prompt-override for bin/iterate-story" -m "Phase 1 can now take its story prompt verbatim from a file instead of
building it from the narrative; the override is still persisted to
story_prompt.txt. A missing override file exits 2 before any subprocess
runs. Spec: docs/superpowers/specs/2026-10-03-iterate-story-design.md
Section 4.1 (tests T-L5, T-L6, T-L7)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
If the `test` guard fails, nothing is committed. Run `git diff --cached --name-only`, unstage anything foreign with `git restore --staged <path>`, and rerun.

---

### Task 2: bin/ltx-movie passes `--danger-auto-approve` under `--force-story --no-review` (spec 4.2)

**Files:**
- Modify: `bin/ltx-movie`, `phase1_story()`. As of the end of Task 1, insert 2 lines between line 690 (`cmd += ["--image", args.seed_downscaled_path]`) and line 691 (`cmd += ["--user-prompt", prompt]`). Net numstat: `2	0`.
- Modify: `tests/test_ltx_movie_iterate_flags.py` (append T-L1 to T-L4).
- Test: `tests/test_ltx_movie_iterate_flags.py`

**Interfaces:**
- Consumes: Task 1's `popen_calls` fixture and `_phase1_with_narrative(flags)`; `bin/qwen-agent`'s existing, unchanged `--danger-auto-approve` flag (`bin/qwen-agent:3685`).
- Produces: `phase1_story()`'s qwen-agent `cmd` contains `"--danger-auto-approve"` exactly once, placed before the final `"--user-prompt", prompt` pair, if and only if `args.force_story and args.no_review`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ltx_movie_iterate_flags.py`. The heredoc body begins with two blank lines on purpose.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_ltx_movie_iterate_flags.py <<'PLAN_EOF'


# --- T-L1..T-L4: --danger-auto-approve only with --force-story + --no-review (spec 4.2) ---

def test_tl1_force_story_and_no_review_add_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--force-story", "--no-review"])
    assert len(popen_calls) == 1
    cmd = popen_calls[0]
    assert "--danger-auto-approve" in cmd
    assert cmd.count("--danger-auto-approve") == 1
    assert cmd[-2] == "--user-prompt"


def test_tl2_force_story_alone_omits_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--force-story"])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]


def test_tl3_no_review_alone_omits_danger_auto_approve(popen_calls):
    _phase1_with_narrative(["--no-review"])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]


def test_tl4_no_flags_omit_danger_auto_approve(popen_calls):
    _phase1_with_narrative([])
    assert len(popen_calls) == 1
    assert "--danger-auto-approve" not in popen_calls[0]
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
```
Expected: `1 failed, 6 passed`.
- `test_tl1_force_story_and_no_review_add_danger_auto_approve` fails on `assert "--danger-auto-approve" in cmd`.
- T-L2, T-L3 and T-L4 already pass. They pin the "not added" cases that the mutation below must break.

- [ ] **Step 3: Write minimal implementation**

Make one Edit-tool edit to `bin/ltx-movie`. old_string:
```python
            cmd += ["--image", args.seed_downscaled_path]
        cmd += ["--user-prompt", prompt]
```
new_string:
```python
            cmd += ["--image", args.seed_downscaled_path]
        if args.force_story and args.no_review:
            cmd += ["--danger-auto-approve"]
        cmd += ["--user-prompt", prompt]
```
This keeps `--user-prompt <prompt>` as the last two elements of `cmd`. The status line's `cmd[:-1]` redaction and guard L29f both depend on that.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/iterate_story_r1_t2.txt 2>&1; echo "rc=$?"; tail -1 /tmp/iterate_story_r1_t2.txt
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --numstat -- bin/ltx-movie
```
Expected:
- pytest: `7 passed, 1 warning`
- R1: `rc=0`, `OK 340/340`
- numstat: `2	0	qwen-agent-workspace/bin/ltx-movie`

Next, the negative control (spec 7.5 row "`--danger-auto-approve` condition reduced to `args.force_story`"):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 danger condition reduced to args.force_story", "bin/ltx-movie",
     [('        if args.force_story and args.no_review:\n', '        if args.force_story:\n')],
     L, ['test_tl2_force_story_alone_omits_danger_auto_approve']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: one `... CAUGHT` line, then `ALL 1 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/ltx-movie tests/test_ltx_movie_iterate_flags.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/ltx-movie\nqwen-agent-workspace/tests/test_ltx_movie_iterate_flags.py')" && git commit -m "ltx-movie: pass --danger-auto-approve under --force-story --no-review" -m "An unattended --force-story rerun hit qwen-agent's eof_stdin_unattended
denial on the story.md overwrite. --no-review already means no interactive
gates, so with --force-story it now also passes qwen-agent's existing
--danger-auto-approve. A plain --force-story or --no-review run is
unchanged. Spec Section 4.2 (tests T-L1 to T-L4); scope recorded as G16." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: bin/ltx-movie `--story-only` and optional `narrative` (spec 4.3, resolves G1)

**Files:**
- Modify: `bin/ltx-movie`. Line numbers are as of the end of Task 2.
  - `build_parser()`: replace line 181 (`narrative` positional) with 3 lines.
  - `build_parser()`: insert 7 lines between line 283 (the end of the `--story-server-stop-after-story` block) and line 284 (`--dry-run`).
  - `_phase_sequence()` (lines 1084-1094): insert 5 lines after the docstring, which ends at line 1086.
  - `main()`: insert 2 lines between line 1100 (`args = parser.parse_args(argv)`) and line 1101 (`_resolve_length(args, raw_argv)`).
  - Net numstat: `17	1`.
- Modify: `tests/test_ltx_movie_iterate_flags.py` (append T-L8 to T-L11).
- Test: `tests/test_ltx_movie_iterate_flags.py`

**Interfaces:**
- Consumes: Task 1's `args.story_prompt_override` and the test helpers `popen_calls`, `_run_phase1(argv)`, `_story_prompt_txt(tmp_path)`, `STORY_ID`.
- Produces:
  - CLI flag `--story-only` -> `args.story_only` (`bool`, default `False`).
  - `narrative` is optional: `args.narrative` is `None` when it is omitted.
  - `_phase_sequence(args)` returns `(phase1_story,)`, or `(phase0_seed, phase1_story)` with `--seed-image`, whenever `args.story_only` is set, regardless of `story_server_stop_after_story`.
  - `main()` raises `SystemExit(2)` through `parser.error` when neither `narrative` nor `--story-prompt-override` is given.
  - Task 7's `build_ltx_movie_cmd` relies on all of this at runtime.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ltx_movie_iterate_flags.py`. The heredoc body begins with two blank lines on purpose.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_ltx_movie_iterate_flags.py <<'PLAN_EOF'


# --- T-L8..T-L11: --story-only and optional narrative (spec 4.3) ------------------------

def test_tl8_story_only_runs_phase1_only():
    args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", STORY_ID,
                                                "--story-only"])
    assert args.story_server_stop_after_story is True
    names = tuple(f.__name__ for f in ltx_movie._phase_sequence(args))
    assert names == ("phase1_story",)


def test_tl9_story_only_with_seed_image_keeps_phase0():
    args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", STORY_ID,
                                                "--story-only", "--seed-image", "x.png"])
    names = tuple(f.__name__ for f in ltx_movie._phase_sequence(args))
    assert names == ("phase0_seed", "phase1_story")


def test_tl10_no_narrative_and_no_override_exits_2(popen_calls, capsys):
    with pytest.raises(SystemExit) as excinfo:
        ltx_movie.main(["--story-id", STORY_ID])
    assert excinfo.value.code == 2
    assert ("either a narrative argument or --story-prompt-override is required"
            in capsys.readouterr().err)
    assert popen_calls == []


def test_tl11_override_without_narrative_does_not_crash_phase1(tmp_path, popen_calls):
    override = tmp_path / "override.txt"
    override.write_text("Override only\n", encoding="utf-8")
    args = _run_phase1(["--story-id", STORY_ID, "--panels", "1",
                        "--story-prompt-override", str(override)])
    assert args.narrative is None
    assert len(popen_calls) == 1
    assert popen_calls[0][-1] == "Override only\n"
    assert _story_prompt_txt(tmp_path) == "Override only\n"
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
```
Expected: `4 failed, 7 passed`.
- `test_tl8_story_only_runs_phase1_only` and `test_tl9_story_only_with_seed_image_keeps_phase0` fail with `SystemExit: 2` (unrecognized `--story-only`).
- `test_tl10_no_narrative_and_no_override_exits_2` fails its stderr assertion. argparse exits 2, but with `the following arguments are required: narrative`.
- `test_tl11_override_without_narrative_does_not_crash_phase1` fails with `SystemExit: 2` (narrative required).

- [ ] **Step 3: Write minimal implementation**

Make four Edit-tool edits to `bin/ltx-movie`.

Edit 1 (`build_parser()`, the `narrative` positional). old_string:
```python
    parser.add_argument("narrative", help="the story narrative to adapt into panels")
```
new_string:
```python
    parser.add_argument("narrative", nargs="?", default=None,
                         help="the story narrative to adapt into panels; omit only when "
                              "--story-prompt-override is given")
```

Edit 2 (`build_parser()`, after the `--story-server-stop-after-story` block and before `--dry-run`). old_string:
```python
                              "(e.g. for rapid successive runs).")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
```
new_string:
```python
                              "(e.g. for rapid successive runs).")
    parser.add_argument("--story-only", dest="story_only", action="store_true", default=False,
                         help="run Phase 0 (if --seed-image) and Phase 1 only, then stop. "
                              "Skips phase_release_story_server as well as Phases 2-4, so a "
                              "caller that regenerates story.md repeatedly (e.g. "
                              "bin/iterate-story) keeps the story server resident across "
                              "calls, with no need to also pass "
                              "--no-story-server-stop-after-story.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
```

Edit 3 (`main()`). parser.error prints usage and raises `SystemExit(2)`. Giving both `narrative` and `--story-prompt-override` stays allowed. old_string:
```python
    args = parser.parse_args(argv)
    _resolve_length(args, raw_argv)
```
new_string:
```python
    args = parser.parse_args(argv)
    if args.narrative is None and args.story_prompt_override is None:
        parser.error("either a narrative argument or --story-prompt-override is required")
    _resolve_length(args, raw_argv)
```

Edit 4 (`_phase_sequence()`). This inserts the `--story-only` early return right after the existing docstring, which stays: the function is still pure. The rest of the body is textually unchanged. old_string:
```python
    for the --story-server-stop-after-story insertion point."""
    phases = ((phase1_story, phase3_manifest, phase4_render) if args.no_stills
```
new_string:
```python
    for the --story-server-stop-after-story insertion point."""
    if getattr(args, "story_only", False):
        phases = (phase1_story,)
        if getattr(args, "seed_image", None):
            phases = (phase0_seed,) + phases
        return phases
    phases = ((phase1_story, phase3_manifest, phase4_render) if args.no_stills
```
Do not change `_print_dry_run_plan()`. With no narrative, `--dry-run` renders the literal text `None` where the narrative goes. That is accepted in spec 4.3's audit (G11).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_ltx_movie_iterate_flags.py -v
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/iterate_story_r1_t3.txt 2>&1; echo "rc=$?"; tail -1 /tmp/iterate_story_r1_t3.txt
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --numstat -- bin/ltx-movie
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && /usr/bin/python3 -c "import ast,sys; ast.parse(open('bin/ltx-movie').read()); print('parses under', sys.version.split()[0])"
```
Expected:
- pytest: `11 passed, 1 warning`
- R1: `rc=0`, `OK 340/340`. Guard L41's eight `_phase_sequence` cases build `args` without `story_only`, so `getattr(..., False)` keeps them green.
- numstat: `17	1	qwen-agent-workspace/bin/ltx-movie`
- `parses under 3.9.6`

Next, the negative controls (spec 7.5 rows for `--story-only` and the narrative validation). The first mutation is the effect-equivalent form of the row "`--story-only` branch checked after the `story_server_stop_after_story` insertion": `phase_release_story_server` still ends up in the `--story-only` tuple.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 --story-only still inserts phase_release_story_server", "bin/ltx-movie",
     [('        phases = (phase1_story,)\n', '        phases = (phase1_story, phase_release_story_server)\n')],
     L, ['test_tl8_story_only_runs_phase1_only']),
    ("7.5 --story-only omits the phase0_seed prefix", "bin/ltx-movie",
     [('            phases = (phase0_seed,) + phases\n', '            pass\n')],
     L, ['test_tl9_story_only_with_seed_image_keeps_phase0']),
    ("7.5 neither-narrative-nor-override validation removed", "bin/ltx-movie",
     [('    if args.narrative is None and args.story_prompt_override is None:\n', '    if False:\n')],
     L, ['test_tl10_no_narrative_and_no_override_exits_2']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: three `... CAUGHT` lines, then `ALL 3 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/ltx-movie tests/test_ltx_movie_iterate_flags.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/ltx-movie\nqwen-agent-workspace/tests/test_ltx_movie_iterate_flags.py')" && git commit -m "ltx-movie: add --story-only and make narrative optional" -m "--story-only runs Phase 0 (if seeded) and Phase 1, then stops: no
phase_release_story_server and no Phases 2-4, so a caller that
regenerates story.md repeatedly keeps the story server resident. The
narrative positional is now optional; main() exits 2 only when neither it
nor --story-prompt-override is given. Resolves spec G1 (Section 4.3;
tests T-L8 to T-L11)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: bin/iterate-story scaffold, panel-count pin, and prompt re-injection (spec 1.1, 1.6, 3.1, 3.2, G19)

**Files:**
- Create: `bin/iterate-story` (70 lines; `chmod +x`).
- Create: `tests/test_iterate_story.py` (the D2 scaffold plus T-P1, T-P2, T-P2b).
- Test: `tests/test_iterate_story.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. It is independent of Tasks 1-3 and could run in parallel with them; it stays sequential here only for commit hygiene.
- Produces:
  - Module globals `WS`, `SCORE_KEYS`, `DEFAULT_MAX_ROUNDS`, `STOP_THRESHOLD`, `STOP_PLATEAU`, `STOP_MAX_ROUNDS`, `VERSION_RE`, `TAIL_LINES`, `PANEL_COUNT_DECLARATION_RE`.
  - `count_panels(story_md_text) -> int`, `build_reinjection(pinned_panel_count) -> str`, `build_next_prompt(revised_prompt, pinned_panel_count) -> str`.
  - Test scaffold: the module object `iterate_story` and the autouse `_no_real_subprocess` guard.

- [ ] **Step 1: Write the failing test**

Create `tests/test_iterate_story.py` with the Write tool, with exactly this content. The file ends with a single newline.

```python
"""Tests for bin/iterate-story.

Spec: docs/superpowers/specs/2026-10-03-iterate-story-design.md (Section 7).
Run from the workspace root: python3 -m pytest tests/test_iterate_story.py -v

Plain pytest asserts only -- no check() helper, which reports false greens under
pytest. No test makes a real subprocess, API, or generation call: the autouse
fixture below makes subprocess.run fail the test, and every test that reaches a
subprocess installs the recording FakeRun first. Story directories live under
tmp_path. Exactly one test function per spec test ID (16 total: T-P1, T-P2, T-P2b,
T-P3, T-P4, T-P5, T-M1..T-M9 and T-M6b); multi-case IDs loop inside one function.
"""

import importlib.machinery
import json
import os
import re
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
iterate_story = importlib.machinery.SourceFileLoader(
    "iterate_story", os.path.join(WS, "bin", "iterate-story")).load_module()


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    """SC9 guard for every test: a real subprocess.run from bin/iterate-story fails it."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("test made a real subprocess call")
    monkeypatch.setattr(iterate_story.subprocess, "run", _forbidden)


# --- T-P1, T-P2, T-P2b: pinned panel count and re-injection (spec 3.1, 3.2) ------------

def test_tp1_count_panels():
    twenty = "".join("## Panel %d — Beat %d\nMotion: m\nNarration: n\n\n" % (i, i)
                     for i in range(1, 21))
    assert iterate_story.count_panels(twenty) == 20
    mixed = ("## Panel 1 — a\nThe guard points at Panel 4 on the wall.\n"
             "### Panel 9 — sub-heading\n ## Panel 8 — leading space\n"
             "## Panel 2 — b\n## Panel 3 — c\n")
    assert iterate_story.count_panels(mixed) == 3


def test_tp2_build_reinjection_and_fallback_append():
    assert iterate_story.build_reinjection(20) == (
        "\n\nThe file must contain EXACTLY 20 panel sections, numbered 1 through 20 in order.")
    assert (iterate_story.build_next_prompt("ABC\n", 20)
            == "ABC\n" + iterate_story.build_reinjection(20))


def test_tp2b_build_next_prompt_replaces_conflicting_declaration():
    assert iterate_story.PANEL_COUNT_DECLARATION_RE.pattern == (
        r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\.")
    revised = ("Here is the revised prompt.\n\nThe file must contain EXACTLY 30 panel sections, "
               "numbered 1 through 30 in order.\n\nFocus more on pacing in the middle act.")
    result = iterate_story.build_next_prompt(revised, 20)
    assert "EXACTLY 30" not in result
    assert result.count("EXACTLY 20") == 1
    assert result == ("Here is the revised prompt.\n\n\n\nFocus more on pacing in the middle act."
                      + iterate_story.build_reinjection(20))
    # Every occurrence is removed, and the singular "section" form matches too.
    twice = ("The file must contain EXACTLY 30 panel sections, numbered 1 through 30 in order."
             " X The file must contain EXACTLY 1 panel section, numbered 1 through 1 in order.")
    assert (iterate_story.build_next_prompt(twice, 20)
            == " X " + iterate_story.build_reinjection(20))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: a collection error, `1 error`, exit code 2: `ERROR tests/test_iterate_story.py - FileNotFoundError: [Errno 2] No such file or directory: '.../bin/iterate-story'`.

- [ ] **Step 3: Write minimal implementation**

Create `bin/iterate-story` with the Write tool, with exactly this content (the file ends with a single newline). Then make it executable.

```python
#!/usr/bin/env python3
"""iterate-story -- automate the judge -> revise prompt -> regenerate -> re-judge loop.

Phase 2 of the story-pipeline self-improvement loop
(docs/superpowers/specs/2026-10-03-iterate-story-design.md). Each round runs
bin/judge-story against the live story.md, archives the judged story.md,
story_prompt.txt and judgment.json under the next free .vN suffix (never
overwriting an existing .vN file), and then -- unless a stopping condition is met
(threshold met, plateaued, max-rounds reached) -- regenerates story.md through
bin/ltx-movie --story-only, using the judge's revised prompt with the story's
original panel count re-pinned as its last sentence. At exit the best round
(highest per-dimension minimum, then highest average, then earliest) is promoted
back to the live story.md, story_prompt.txt and judgment.json, and
run-summary.json records every round. Text only: no stills, clips or renders.

Usage:
  bin/iterate-story --story-id <id> --threshold <N> [--max-rounds <N>]

Requires ANTHROPIC_API_KEY in the environment for bin/judge-story; this script
does not check it itself (an unset key fails round 1's judge call). Exit codes:
0 a stopping condition was met, 1 a judge-story or ltx-movie subprocess failed or
ltx-movie left story.md unchanged, 2 argument or precondition failure.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Same order as bin/judge-story's SCORE_KEYS: stdout round lines and run-summary.json.
SCORE_KEYS = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")
DEFAULT_MAX_ROUNDS = 5
STOP_THRESHOLD = "threshold met"
STOP_PLATEAU = "plateaued"
STOP_MAX_ROUNDS = "max-rounds reached"
# The three archived-file families; the highest N across all of them is the base (spec 1.4).
VERSION_RE = re.compile(r"(?:story\.v(\d+)\.md|story_prompt\.v(\d+)\.txt|judgment\.v(\d+)\.json)")
# Lines of captured child output shown on failure; bin/ltx-movie's splitlines()[-40:].
TAIL_LINES = 40
# The one panel-count sentence removed from the judge's revised_prompt (spec 3.2, G19).
PANEL_COUNT_DECLARATION_RE = re.compile(
    r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\.")


def count_panels(story_md_text):
    """Number of lines that start with '## Panel' (spec 3.1). Pure."""
    return len(re.findall(r"^## Panel", story_md_text, flags=re.MULTILINE))


def build_reinjection(pinned_panel_count):
    """The pinned panel-count sentence appended last to every regeneration prompt, in
    bin/ltx-movie STORY_PROMPT_TEMPLATE's own wording (spec 3.2). Pure."""
    return ("\n\nThe file must contain EXACTLY %d panel sections, numbered 1 through %d in order."
            % (pinned_panel_count, pinned_panel_count))


def build_next_prompt(revised_prompt, pinned_panel_count):
    """revised_prompt with every "EXACTLY N panel sections" declaration removed and the
    pinned one appended last, so the prompt states the panel count exactly once
    (spec 3.2). Zero matches leave revised_prompt unchanged before the append. Pure."""
    cleaned = PANEL_COUNT_DECLARATION_RE.sub("", revised_prompt)
    return cleaned + build_reinjection(pinned_panel_count)
```
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && chmod +x bin/iterate-story
```
`main()` and the `__main__` block arrive in Task 7. Until then the module only defines helpers.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && test -x bin/iterate-story && echo "executable OK" && head -1 bin/iterate-story && python3 - <<'EOF'
import ast
tree = ast.parse(open("bin/iterate-story", encoding="utf-8").read())
mods = sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names)
assert mods == ["argparse", "datetime", "hashlib", "json", "os", "re", "shutil", "subprocess",
                "sys", "tempfile"], mods
assert not [n for n in tree.body if isinstance(n, ast.ImportFrom)], "no from-imports allowed"
print("PASS stdlib-only imports:", " ".join(mods))
EOF
```
Expected:
- pytest: `3 passed, 1 warning`
- `executable OK`, then `#!/usr/bin/env python3`, then `PASS stdlib-only imports: argparse datetime hashlib json os re shutil subprocess sys tempfile`

Next, the negative controls (spec 7.5 rows "Re-injection prepended instead of appended" and "`PANEL_COUNT_DECLARATION_RE.sub` call removed"):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 re-injection prepended instead of appended", "bin/iterate-story",
     [('    return cleaned + build_reinjection(pinned_panel_count)\n', '    return build_reinjection(pinned_panel_count) + cleaned\n')],
     I, ['test_tp2_build_reinjection_and_fallback_append']),
    ("7.5 PANEL_COUNT_DECLARATION_RE.sub call removed", "bin/iterate-story",
     [('    cleaned = PANEL_COUNT_DECLARATION_RE.sub("", revised_prompt)\n', '    cleaned = revised_prompt\n')],
     I, ['test_tp2b_build_next_prompt_replaces_conflicting_declaration']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: two `... CAUGHT` lines, then `ALL 2 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/iterate-story tests/test_iterate_story.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/iterate-story\nqwen-agent-workspace/tests/test_iterate_story.py')" && git commit -m "iterate-story: add panel-count pinning and prompt re-injection" -m "New bin/iterate-story scaffold (stdlib only) with the pure text helpers:
count_panels pins story.md's '## Panel' header count, and
build_next_prompt removes every 'EXACTLY N panel sections' sentence
from the judge's revised_prompt before appending the pinned-count one
last, so the prompt never states two panel counts. Spec Sections 3.1,
3.2 and G19 (tests T-P1, T-P2, T-P2b)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
Confirm git recorded the executable bit: `git ls-files -s bin/iterate-story` starts with `100755`.

---

### Task 5: bin/iterate-story version-suffix scan (spec 1.4)

**Files:**
- Modify: `bin/iterate-story` (append `find_version_base` after line 70, the end of the file).
- Modify: `tests/test_iterate_story.py` (append T-P3).
- Test: `tests/test_iterate_story.py`

**Interfaces:**
- Consumes: `VERSION_RE` (Task 4).
- Produces: `find_version_base(story_dir) -> int`: the highest `N` across `story.vN.md`, `story_prompt.vN.txt` and `judgment.vN.json`, or 0.

- [ ] **Step 1: Write the failing test**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_iterate_story.py <<'PLAN_EOF'


# --- T-P3: version-suffix scan (spec 1.4) ---------------------------------------------

def test_tp3_find_version_base(tmp_path):
    def _dir(name, files):
        d = tmp_path / name
        d.mkdir()
        for f in files:
            (d / f).write_text("x", encoding="utf-8")
        return str(d)

    ronin_shape = _dir("a", ["story.v1.md", "story.v2.md", "story_prompt.v1.txt",
                             "story_prompt.v2.txt", "judgment.v1.json", "judgment.v2.json"])
    assert iterate_story.find_version_base(ronin_shape) == 2
    assert iterate_story.find_version_base(_dir("b", [])) == 0
    assert iterate_story.find_version_base(_dir("c", ["judgment.v7.json"])) == 7
    assert iterate_story.find_version_base(
        _dir("d", ["story.v2.md.bak", "story.vX.md", "story.v.md"])) == 0
    # Numeric, not lexicographic, maximum across families.
    assert iterate_story.find_version_base(
        _dir("e", ["story.v9.md", "story_prompt.v10.txt"])) == 10
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `1 failed, 3 passed`. `test_tp3_find_version_base` fails with `AttributeError: module 'iterate_story' has no attribute 'find_version_base'`.

- [ ] **Step 3: Write minimal implementation**

Append to `bin/iterate-story`. The heredoc body begins with two blank lines on purpose.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> bin/iterate-story <<'PLAN_EOF'


def find_version_base(story_dir):
    """Highest N among story.vN.md, story_prompt.vN.txt and judgment.vN.json in
    story_dir, or 0 if there are none (spec 1.4). Round r archives as v<base + r>."""
    highest = 0
    for name in os.listdir(story_dir):
        match = VERSION_RE.fullmatch(name)
        if match:
            highest = max(highest, int(next(g for g in match.groups() if g is not None)))
    return highest
PLAN_EOF
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `4 passed, 1 warning`.

Next, the negative control (spec 7.5 row "`find_version_base` returns 0 without scanning"; Task 8's sweep re-checks it against T-M3):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 find_version_base returns 0 without scanning", "bin/iterate-story",
     [('    return highest\n', '    return 0\n')],
     I, ['test_tp3_find_version_base']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: one `... CAUGHT` line, then `ALL 1 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/iterate-story tests/test_iterate_story.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/iterate-story\nqwen-agent-workspace/tests/test_iterate_story.py')" && git commit -m "iterate-story: add version-suffix scan" -m "find_version_base returns the highest N across story.vN.md,
story_prompt.vN.txt and judgment.vN.json (numeric max, full-name match),
so archives always continue above any hand-made or stray .vN file and
never overwrite one. Spec Section 1.4, G7 (test T-P3)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: bin/iterate-story stopping criteria and best-round selection (spec 3.3, 1.5)

**Files:**
- Modify: `bin/iterate-story` (append `evaluate_stop` and `select_best_round` after line 81, the end of the file).
- Modify: `tests/test_iterate_story.py` (append T-P4, T-P5).
- Test: `tests/test_iterate_story.py`

**Interfaces:**
- Consumes: `STOP_THRESHOLD`, `STOP_PLATEAU`, `STOP_MAX_ROUNDS` (Task 4).
- Produces:
  - `evaluate_stop(history, threshold, max_rounds) -> str | None`. `history` is a list of score 4-tuples, current round last.
  - `select_best_round(rounds) -> int | None`. `rounds` is a list of `(round_number, scores_tuple)` pairs. It returns `None` only for an empty list.

- [ ] **Step 1: Write the failing test**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_iterate_story.py <<'PLAN_EOF'


# --- T-P4, T-P5: stopping criteria and best-round selection (spec 3.3, 1.5) -----------

def test_tp4_evaluate_stop():
    assert (iterate_story.STOP_THRESHOLD, iterate_story.STOP_PLATEAU,
            iterate_story.STOP_MAX_ROUNDS) == ("threshold met", "plateaued",
                                               "max-rounds reached")
    cases = [
        ([(7, 7, 7, 7)], 7, 5, "threshold met"),
        ([(7, 7, 7, 6)], 7, 5, None),
        ([(5, 5, 5, 4), (5, 5, 5, 4)], 9, 5, "plateaued"),
        ([(5, 5, 5, 4), (6, 4, 4, 3)], 9, 5, None),
        ([(4, 4, 4, 4), (6, 6, 6, 6), (6, 6, 6, 6)], 9, 5, "plateaued"),
        ([(8, 8, 8, 8), (8, 8, 8, 8)], 7, 2, "threshold met"),
        ([(5, 5, 5, 4), (5, 5, 5, 4)], 9, 2, "plateaued"),
        ([(4, 4, 4, 4), (5, 4, 4, 4)], 9, 2, "max-rounds reached"),
        ([(4, 4, 4, 4)], 9, 1, "max-rounds reached"),
    ]
    for i, (history, threshold, max_rounds, expected) in enumerate(cases, 1):
        got = iterate_story.evaluate_stop(history, threshold, max_rounds)
        assert got == expected, "case %d: got %r, expected %r" % (i, got, expected)


def test_tp5_select_best_round():
    cases = [
        ([(1, (5, 4, 4, 3)), (2, (5, 5, 5, 4)), (3, (9, 9, 9, 3))], 2),
        ([(1, (4, 4, 4, 4)), (2, (9, 4, 4, 4))], 2),
        ([(1, (5, 5, 5, 4)), (2, (5, 5, 5, 4))], 1),
    ]
    for i, (rounds, expected) in enumerate(cases, 1):
        got = iterate_story.select_best_round(rounds)
        assert got == expected, "case %d: got %r, expected %r" % (i, got, expected)
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `2 failed, 4 passed`. `test_tp4_evaluate_stop` and `test_tp5_select_best_round` fail with `AttributeError` (`evaluate_stop` and `select_best_round` do not exist yet).

- [ ] **Step 3: Write minimal implementation**

Append to `bin/iterate-story`. The heredoc body begins with two blank lines on purpose.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> bin/iterate-story <<'PLAN_EOF'


def evaluate_stop(history, threshold, max_rounds):
    """Stop reason after the round just archived, or None (spec 3.3). history is the list
    of 4-tuples of scores for rounds 1..r, current round last. First match wins:
    threshold, then plateau (against the immediately previous round only; no dimension
    strictly improved), then max-rounds. Pure."""
    if all(s >= threshold for s in history[-1]):
        return STOP_THRESHOLD
    if len(history) >= 2 and not any(c > p for c, p in zip(history[-1], history[-2])):
        return STOP_PLATEAU
    if len(history) >= max_rounds:
        return STOP_MAX_ROUNDS
    return None


def select_best_round(rounds):
    """Round number with the highest minimum score, then the highest sum (the same order
    as the average, for 4 scores), then the earliest (spec 1.5). rounds is a list of
    (round_number, scores_tuple) pairs in round order. Pure."""
    best_round, best_key = None, None
    for round_number, scores in rounds:
        key = (min(scores), sum(scores))
        if best_key is None or key > best_key:
            best_round, best_key = round_number, key
    return best_round
PLAN_EOF
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `6 passed, 1 warning`.

Next, the negative controls (the five spec 7.5 rows for the stop rule and the best-round rule):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 threshold >= changed to >", "bin/iterate-story",
     [('    if all(s >= threshold for s in history[-1]):\n', '    if all(s > threshold for s in history[-1]):\n')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 plateau compares to history[0]", "bin/iterate-story",
     [('zip(history[-1], history[-2])', 'zip(history[-1], history[0])')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 plateau checked before threshold", "bin/iterate-story",
     [('    if all(s >= threshold for s in history[-1]):\n        return STOP_THRESHOLD\n    if len(history) >= 2 and not any(c > p for c, p in zip(history[-1], history[-2])):\n        return STOP_PLATEAU\n', '    if len(history) >= 2 and not any(c > p for c, p in zip(history[-1], history[-2])):\n        return STOP_PLATEAU\n    if all(s >= threshold for s in history[-1]):\n        return STOP_THRESHOLD\n')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 best round by average first, then minimum", "bin/iterate-story",
     [('        key = (min(scores), sum(scores))\n', '        key = (sum(scores), min(scores))\n')],
     I, ['test_tp5_select_best_round']),
    ("7.5 full tie picks the latest", "bin/iterate-story",
     [('        if best_key is None or key > best_key:\n', '        if best_key is None or key >= best_key:\n')],
     I, ['test_tp5_select_best_round']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: five `... CAUGHT` lines, then `ALL 5 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/iterate-story tests/test_iterate_story.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/iterate-story\nqwen-agent-workspace/tests/test_iterate_story.py')" && git commit -m "iterate-story: add stopping criteria and best-round selection" -m "evaluate_stop checks threshold (>=, all four scores), then plateau
(no dimension strictly improved over the immediately previous round),
then max-rounds. select_best_round prefers the highest minimum score,
then the highest sum, then the earliest round. Spec Sections 3.3 and
1.5, G8 (tests T-P4, T-P5)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: bin/iterate-story CLI, preconditions, and the judge/regenerate round loop (spec 1.2, 1.3, 1.5, 2, 3.2, 3.4, 5)

**Files:**
- Modify: `bin/iterate-story` (append the CLI, subprocess, archive, promotion, summary and `main()` code, plus the `__main__` block, after line 107, the end of the file; the file becomes 262 lines).
- Modify: `tests/test_iterate_story.py` (append the shared loop fixtures, `FakeRun`, and T-M1, T-M2, T-M3, T-M4, T-M7, T-M8).
- Test: `tests/test_iterate_story.py`

**Interfaces:**
- Consumes: `count_panels`, `build_next_prompt` (Task 4); `find_version_base` (Task 5); `evaluate_stop`, `select_best_round` (Task 6). At runtime it also relies on `bin/ltx-movie`'s `--story-only`, `--story-prompt-override` and optional `narrative` (Tasks 1-3) and on `bin/judge-story --story-id` writing `judgment.json` and `story_prompt.revised.txt` (shipped, unchanged).
- Produces:
  - `build_parser()`, `resolve_paths(story_id) -> (story_dir, story_md_path, story_prompt_path)`, `build_judge_cmd(story_id) -> list`, `build_ltx_movie_cmd(story_id, override_path, pinned_panel_count) -> list`
  - `_run(cmd) -> subprocess.CompletedProcess`, `_tail(output) -> str`, `_archive(story_dir, version)`, `promote(story_dir, version)`, `_write_summary(story_dir, stop_reason, best_round, records)`
  - `main(argv=None) -> int` (happy path; Task 8 adds the failure paths)
  - Test helpers used by Task 8: `FakeRun`, `_make_story`, `_summary`, `_read_bytes`, `_assert_live_equals_archive`, `STORY_ID`, `PINNED`

- [ ] **Step 1: Write the failing test**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_iterate_story.py <<'PLAN_EOF'


# --- Loop tests: shared fixtures and the recording subprocess fake (spec 7.1) ---------

SCORE_KEYS = ("pacing_progression", "action_plausibility", "visual_specificity", "continuity")
STORY_ID = "iterate-test"
PINNED = 4
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REGEN_1 = "## Panel 1 — regen 1\nMotion: m\nNarration: n\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _story_md(panels):
    return "".join("## Panel %d — Beat %d\nMotion: m%d\nNarration: n%d\n\n" % (i, i, i, i)
                   for i in range(1, panels + 1))


def _make_story(tmp_path, monkeypatch):
    """Point iterate_story.WS at tmp_path and create generated/stories/STORY_ID with a
    PINNED-panel story.md and a story_prompt.txt. Returns the story dir."""
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    story_dir = os.path.join(str(tmp_path), "generated", "stories", STORY_ID)
    os.makedirs(story_dir)
    _write(os.path.join(story_dir, "story.md"), _story_md(PINNED))
    _write(os.path.join(story_dir, "story_prompt.txt"), "ORIGINAL PROMPT\n")
    return story_dir


def _summary(story_dir):
    with open(os.path.join(story_dir, "run-summary.json"), encoding="utf-8") as f:
        return json.load(f)


def _assert_live_equals_archive(story_dir, version):
    for live, archive in (("story.md", "story.v%d.md"), ("story_prompt.txt",
                                                         "story_prompt.v%d.txt"),
                          ("judgment.json", "judgment.v%d.json")):
        assert (_read_bytes(os.path.join(story_dir, live))
                == _read_bytes(os.path.join(story_dir, archive % version))), live


class FakeRun(object):
    """Recording fake for iterate_story.subprocess.run(cmd, **kwargs) (spec 7.1).
    Records (cmd, kwargs) and dispatches on os.path.basename(cmd[1]).

    judge_script, one entry per judge-story call: a 4-tuple of scores means success
    (writes judgment.json with revised_prompt "REVISED-<k>" and story_prompt.revised.txt,
    rc 0); an int means fail with that rc (writes nothing, output "judge boom").
    ltx_script, one entry per ltx-movie call: 0 means success (story.md = regen <k>,
    story_prompt.txt = the override content); a nonzero int means fail with that rc after
    writing story.md = "GARBAGE"; "noop" means write nothing and return rc 0. Calls past
    the end of ltx_script succeed. k counts calls per tool, from 1.
    """

    def __init__(self, story_dir, judge_script, ltx_script=()):
        self.story_dir = story_dir
        self.judge_script = list(judge_script)
        self.ltx_script = list(ltx_script)
        self.calls = []
        self.overrides = []
        self.judge_calls = 0
        self.ltx_calls = 0

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        tool = os.path.basename(cmd[1])
        if tool == "judge-story":
            self.judge_calls += 1
            k = self.judge_calls
            entry = self.judge_script.pop(0)
            if isinstance(entry, int):
                return subprocess.CompletedProcess(cmd, entry, stdout="judge boom\n")
            judgment = {"scores": dict(zip(SCORE_KEYS, entry)), "critique": "c%d" % k,
                        "revised_prompt": "REVISED-%d" % k}
            _write(os.path.join(self.story_dir, "judgment.json"),
                   json.dumps(judgment, indent=2) + "\n")
            _write(os.path.join(self.story_dir, "story_prompt.revised.txt"), "REVISED-%d" % k)
            return subprocess.CompletedProcess(cmd, 0, stdout="judged %d\n" % k)
        if tool == "ltx-movie":
            self.ltx_calls += 1
            k = self.ltx_calls
            override_path = cmd[cmd.index("--story-prompt-override") + 1]
            with open(override_path, encoding="utf-8") as f:
                content = f.read()
            self.overrides.append((override_path, content))
            entry = self.ltx_script.pop(0) if self.ltx_script else 0
            if entry == "noop":
                return subprocess.CompletedProcess(cmd, 0, stdout="nothing written\n")
            if entry != 0:
                _write(os.path.join(self.story_dir, "story.md"), "GARBAGE")
                return subprocess.CompletedProcess(cmd, entry, stdout="ltx boom\n")
            _write(os.path.join(self.story_dir, "story.md"),
                   "## Panel 1 — regen %d\nMotion: m\nNarration: n\n" % k)
            _write(os.path.join(self.story_dir, "story_prompt.txt"), content)
            return subprocess.CompletedProcess(cmd, 0, stdout="regenerated %d\n" % k)
        raise AssertionError("unexpected subprocess call: %r" % (cmd,))


# --- T-M1..T-M4, T-M7, T-M8: happy-path loop, arguments, preconditions (spec 1-5) -----

def test_tm1_threshold_stop_happy_path(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(4, 4, 5, 2), (7, 7, 7, 7)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "7"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (2, 1)
    for v in (1, 2):
        for name in ("story.v%d.md", "story_prompt.v%d.txt", "judgment.v%d.json"):
            assert os.path.isfile(os.path.join(story_dir, name % v)), name % v
    assert not os.path.exists(os.path.join(story_dir, "story.v3.md"))
    assert capsys.readouterr().out == (
        "Round 1: pacing_progression=4 action_plausibility=4 visual_specificity=5 continuity=2\n"
        "Round 2: pacing_progression=7 action_plausibility=7 visual_specificity=7 continuity=7\n"
        "Stopped: threshold met. Best round: 2 (v2), promoted to story.md, story_prompt.txt, "
        "judgment.json.\n")
    _assert_live_equals_archive(story_dir, 2)
    with open(os.path.join(story_dir, "run-summary.json"), encoding="utf-8") as f:
        raw = f.read()
    assert raw.startswith('{\n  "stop_reason": ') and raw.endswith("}\n")
    summary = json.loads(raw)
    assert list(summary) == ["stop_reason", "best_round", "rounds"]
    assert summary["stop_reason"] == "threshold met"
    assert summary["best_round"] == 2
    assert [r["round"] for r in summary["rounds"]] == [1, 2]
    assert [r["version"] for r in summary["rounds"]] == ["v1", "v2"]
    for record, scores in zip(summary["rounds"], [(4, 4, 5, 2), (7, 7, 7, 7)]):
        assert list(record) == ["round", "version", "scores", "timestamp"]
        assert list(record["scores"]) == list(SCORE_KEYS)
        assert tuple(record["scores"].values()) == scores
        assert TIMESTAMP_RE.match(record["timestamp"]), record["timestamp"]


def test_tm2_subprocess_argv_and_override_file(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(4, 4, 5, 2), (7, 7, 7, 7)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "7"]) == 0
    assert ([os.path.basename(cmd[1]) for cmd, _ in fake.calls]
            == ["judge-story", "ltx-movie", "judge-story"])
    judge_cmd = [sys.executable, os.path.join(iterate_story.WS, "bin", "judge-story"),
                 "--story-id", STORY_ID]
    assert fake.calls[0][0] == judge_cmd
    assert fake.calls[2][0] == judge_cmd
    override_path, override_content = fake.overrides[0]
    assert fake.calls[1][0] == [sys.executable, os.path.join(iterate_story.WS, "bin", "ltx-movie"),
                                "--story-id", STORY_ID, "--panels", str(PINNED),
                                "--force-story", "--no-review", "--story-only",
                                "--story-prompt-override", override_path]
    assert "--danger-auto-approve" not in fake.calls[1][0]
    assert override_content == "REVISED-1" + iterate_story.build_reinjection(PINNED)
    assert not override_path.startswith(story_dir)
    assert not os.path.exists(override_path)
    for _, kwargs in fake.calls:
        assert kwargs == {"cwd": iterate_story.WS, "stdin": subprocess.DEVNULL,
                          "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                          "text": True}


def test_tm3_existing_versions_and_earliest_tie_promotion(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    old = {}
    for v in (1, 2):
        for name, text in (("story.v%d.md" % v, "OLD STORY v%d\n" % v),
                           ("story_prompt.v%d.txt" % v, "OLD PROMPT v%d\n" % v),
                           ("judgment.v%d.json" % v, '{"revised_prompt": "OLD-%d"}\n' % v)):
            _write(os.path.join(story_dir, name), text)
            old[name] = text.encode("utf-8")
    pre_loop_story = _read_bytes(os.path.join(story_dir, "story.md"))
    fake = FakeRun(story_dir, [(5, 4, 4, 3), (5, 5, 5, 4), (5, 5, 5, 4)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (3, 2)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "plateaued"
    assert [r["version"] for r in summary["rounds"]] == ["v3", "v4", "v5"]
    assert not os.path.exists(os.path.join(story_dir, "story.v6.md"))
    assert _read_bytes(os.path.join(story_dir, "story.v3.md")) == pre_loop_story
    assert _read_bytes(os.path.join(story_dir, "story.v4.md")) == REGEN_1.encode("utf-8")
    for name, data in old.items():
        assert _read_bytes(os.path.join(story_dir, name)) == data, name
    assert summary["best_round"] == 2
    _assert_live_equals_archive(story_dir, 4)
    with open(os.path.join(story_dir, "judgment.v4.json"), encoding="utf-8") as f:
        revised = json.load(f)["revised_prompt"]
    assert revised == "REVISED-2"
    with open(os.path.join(story_dir, "story_prompt.revised.txt"), encoding="utf-8") as f:
        assert f.read() == revised
    assert capsys.readouterr().out.endswith(
        "Stopped: plateaued. Best round: 2 (v4), promoted to story.md, story_prompt.txt, "
        "judgment.json.\n")


def test_tm4_max_rounds_stop(tmp_path, monkeypatch):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(3, 3, 3, 3), (4, 4, 4, 4)])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9",
                               "--max-rounds", "2"]) == 0
    assert (fake.judge_calls, fake.ltx_calls) == (2, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "max-rounds reached"
    assert summary["best_round"] == 2


def test_tm7_preconditions_exit_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(iterate_story, "WS", str(tmp_path))
    stories = os.path.join(str(tmp_path), "generated", "stories")
    os.makedirs(os.path.join(stories, "a"))
    _write(os.path.join(stories, "a", "story_prompt.txt"), "P\n")
    os.makedirs(os.path.join(stories, "b"))
    _write(os.path.join(stories, "b", "story.md"), _story_md(PINNED))
    os.makedirs(os.path.join(stories, "c"))
    _write(os.path.join(stories, "c", "story.md"),
           "# Title\n### Panel 1 — sub\n ## Panel 2 — indented\nPanel 4 in body text\n")
    _write(os.path.join(stories, "c", "story_prompt.txt"), "P\n")
    for story_id, expected in (("a", "story.md not found"),
                               ("b", "story_prompt.txt not found"),
                               ("c", 'no "## Panel" headers')):
        assert iterate_story.main(["--story-id", story_id, "--threshold", "7"]) == 2, story_id
        err = capsys.readouterr().err
        assert err.startswith("Error: "), err
        assert expected in err, err
        assert not os.path.exists(os.path.join(stories, story_id, "run-summary.json"))


def test_tm8_argument_errors_exit_2(capsys):
    for argv, message in ((["--story-id", "x", "--threshold", "0"],
                           "--threshold must be an integer from 1 to 10"),
                          (["--story-id", "x", "--threshold", "11"],
                           "--threshold must be an integer from 1 to 10"),
                          (["--story-id", "x", "--threshold", "7", "--max-rounds", "0"],
                           "--max-rounds must be at least 1"),
                          (["--story-id", "x"], "--threshold"),
                          (["--threshold", "7"], "--story-id")):
        with pytest.raises(SystemExit) as excinfo:
            iterate_story.main(argv)
        assert excinfo.value.code == 2, argv
        assert message in capsys.readouterr().err, argv
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `6 failed, 6 passed`. All six new tests (`test_tm1_...`, `test_tm2_...`, `test_tm3_...`, `test_tm4_...`, `test_tm7_...`, `test_tm8_...`) fail with `AttributeError: module 'iterate_story' has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

Append to `bin/iterate-story`. The heredoc body begins with two blank lines on purpose.

This `main()` deliberately has no failure handling yet: it ignores child exit codes, and Task 8 adds E5, E6 and E6b. The archive happens right after judging, before any regeneration, which is spec 1.2 step 3 and G5. The prompt temp file is removed in a `finally:` whether the child succeeds or fails.

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> bin/iterate-story <<'PLAN_EOF'


def build_parser():
    parser = argparse.ArgumentParser(
        prog="iterate-story",
        description="Judge, revise, regenerate and re-judge one story until a stopping "
                    "condition is met, then promote the best-scoring round.")
    parser.add_argument("--story-id", dest="story_id", metavar="ID", required=True,
                        help="iterate on generated/stories/ID/story.md")
    parser.add_argument("--threshold", dest="threshold", type=int, metavar="N", required=True,
                        help="the per-dimension bar (1-10) that all four scores must meet "
                             "or exceed")
    parser.add_argument("--max-rounds", dest="max_rounds", type=int, metavar="N",
                        default=DEFAULT_MAX_ROUNDS,
                        help="the maximum number of judged rounds (default: %(default)s)")
    return parser


def resolve_paths(story_id):
    """(story_dir, story_md_path, story_prompt_path) for story_id (spec 2.2). Reads WS
    at call time so tests can monkeypatch it."""
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    story_md_path = os.path.join(story_dir, "story.md")
    story_prompt_path = os.path.join(story_dir, "story_prompt.txt")
    return story_dir, story_md_path, story_prompt_path


def build_judge_cmd(story_id):
    """bin/judge-story argv (spec 3.4.1)."""
    return [sys.executable, os.path.join(WS, "bin", "judge-story"), "--story-id", story_id]


def build_ltx_movie_cmd(story_id, override_path, pinned_panel_count):
    """bin/ltx-movie regeneration argv (spec 3.4.2). Never passes narrative or
    --danger-auto-approve: bin/ltx-movie adds the latter itself because --force-story
    and --no-review are both present."""
    return [sys.executable, os.path.join(WS, "bin", "ltx-movie"),
            "--story-id", story_id, "--panels", str(pinned_panel_count), "--force-story",
            "--no-review", "--story-only", "--story-prompt-override", override_path]


def _run(cmd):
    """Run one child (spec 3.4): combined output captured, stdin closed, no timeout,
    environment inherited."""
    return subprocess.run(cmd, cwd=WS, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _tail(output):
    return "\n".join((output or "").splitlines()[-TAIL_LINES:])


def _archive(story_dir, version):
    """Copy the live judged triple to its .v<version> archive (spec 1.2 step 3)."""
    for live_name, archive_name in (("story.md", "story.v%d.md" % version),
                                    ("story_prompt.txt", "story_prompt.v%d.txt" % version),
                                    ("judgment.json", "judgment.v%d.json" % version)):
        shutil.copyfile(os.path.join(story_dir, live_name),
                        os.path.join(story_dir, archive_name))


def promote(story_dir, version):
    """Overwrite the live files from the .v<version> archive, and story_prompt.revised.txt
    from that judgment's revised_prompt with no added newline (spec 1.5, G6)."""
    for archive_name, live_name in (("story.v%d.md" % version, "story.md"),
                                    ("story_prompt.v%d.txt" % version, "story_prompt.txt"),
                                    ("judgment.v%d.json" % version, "judgment.json")):
        shutil.copyfile(os.path.join(story_dir, archive_name),
                        os.path.join(story_dir, live_name))
    with open(os.path.join(story_dir, "judgment.v%d.json" % version), encoding="utf-8") as f:
        revised_prompt = json.load(f)["revised_prompt"]
    with open(os.path.join(story_dir, "story_prompt.revised.txt"), "w", encoding="utf-8") as f:
        f.write(revised_prompt)


def _write_summary(story_dir, stop_reason, best_round, records):
    """run-summary.json (spec 5.2): keys in this order, judgment.json's formatting."""
    summary = {"stop_reason": stop_reason, "best_round": best_round, "rounds": records}
    with open(os.path.join(story_dir, "run-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.threshold <= 10:
        parser.error("--threshold must be an integer from 1 to 10")
    if args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1")

    story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id)
    if not os.path.isfile(story_md_path):
        print("Error: story.md not found: %s" % story_md_path, file=sys.stderr)
        return 2
    if not os.path.isfile(story_prompt_path):
        print("Error: story_prompt.txt not found: %s. iterate-story needs the original "
              "story-generation prompt to produce revised_prompt. This story may predate "
              "bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with "
              "--force-story)." % story_prompt_path, file=sys.stderr)
        return 2
    with open(story_md_path, encoding="utf-8") as f:
        pinned_panel_count = count_panels(f.read())
    if pinned_panel_count == 0:
        print('Error: no "## Panel" headers found in story.md: %s; cannot pin the panel '
              'count.' % story_md_path, file=sys.stderr)
        return 2

    version_base = find_version_base(story_dir)
    history = []
    rounds = []
    records = []
    stop_reason = None
    round_number = 0
    while True:
        round_number += 1
        _run(build_judge_cmd(args.story_id))
        with open(os.path.join(story_dir, "judgment.json"), encoding="utf-8") as f:
            judgment = json.load(f)
        scores = tuple(judgment["scores"][key] for key in SCORE_KEYS)
        version = version_base + round_number
        _archive(story_dir, version)
        history.append(scores)
        rounds.append((round_number, scores))
        records.append({
            "round": round_number,
            "version": "v%d" % version,
            "scores": dict(zip(SCORE_KEYS, scores)),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
        })
        print("Round %d: pacing_progression=%d action_plausibility=%d visual_specificity=%d "
              "continuity=%d" % ((round_number,) + scores))
        stop_reason = evaluate_stop(history, args.threshold, args.max_rounds)
        if stop_reason is not None:
            break
        fd, override_path = tempfile.mkstemp(prefix="iterate-story-prompt-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(build_next_prompt(judgment["revised_prompt"], pinned_panel_count))
            _run(build_ltx_movie_cmd(args.story_id, override_path, pinned_panel_count))
        finally:
            os.remove(override_path)

    best_round = select_best_round(rounds)
    best_version = version_base + best_round
    promote(story_dir, best_version)
    _write_summary(story_dir, stop_reason, best_round, records)
    print("Stopped: %s. Best round: %d (v%d), promoted to story.md, story_prompt.txt, "
          "judgment.json." % (stop_reason, best_round, best_version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
PLAN_EOF
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && bin/iterate-story --help | head -1; bin/iterate-story --story-id no-such-story-plancheck --threshold 7; echo "rc=$?"
```
Expected:
- pytest: `12 passed, 1 warning`
- `usage: iterate-story [-h] --story-id ID --threshold N [--max-rounds N]`
- `Error: story.md not found: /Users/reubenpatterson/local_model_harness/qwen-agent-workspace/generated/stories/no-such-story-plancheck/story.md`
- `rc=2`

This smoke check reads the real `generated/` tree, writes nothing, and starts no child process.

Next, the negative controls (spec 7.5 rows "Archive taken after regeneration instead of after judging" and "`build_ltx_movie_cmd` omits `--panels` or `--story-only`", the latter run as two separate mutations):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 archive taken after regeneration instead of after judging", "bin/iterate-story",
     [('        _archive(story_dir, version)\n', ''), ('            os.remove(override_path)\n', '            os.remove(override_path)\n        _archive(story_dir, version)\n')],
     I, ['test_tm3_existing_versions_and_earliest_tie_promotion']),
    ("7.5 build_ltx_movie_cmd omits --panels", "bin/iterate-story",
     [('"--panels", str(pinned_panel_count), ', '')],
     I, ['test_tm2_subprocess_argv_and_override_file']),
    ("7.5 build_ltx_movie_cmd omits --story-only", "bin/iterate-story",
     [('"--story-only", ', '')],
     I, ['test_tm2_subprocess_argv_and_override_file']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: three `... CAUGHT` lines, then `ALL 3 MUTATIONS CAUGHT; sources restored`.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/iterate-story tests/test_iterate_story.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/iterate-story\nqwen-agent-workspace/tests/test_iterate_story.py')" && git commit -m "iterate-story: add CLI and the judge/regenerate round loop" -m "main() validates --threshold/--max-rounds and the story.md,
story_prompt.txt and '## Panel' preconditions (exit 2), then runs rounds:
judge-story, archive the judged triple as the next free .vN, report,
stop check, and otherwise regenerate through ltx-movie --story-only
--panels <pinned> --story-prompt-override <tmp>. On a stop it promotes
the best round (story_prompt.revised.txt included) and writes
run-summary.json. Failure handling follows in the next commit. Spec
Sections 1-5 (tests T-M1 to T-M4, T-M7, T-M8)." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: bin/iterate-story failure paths and no-op regeneration detection (spec 3.5, 6, G2), plus final acceptance

**Files:**
- Modify: `bin/iterate-story`. Line numbers are as of the end of Task 7.
  - Insert `story_md_hash` before `def main(argv=None):` (line 191).
  - Add `failure = None` after line 220 (`stop_reason = None`).
  - Replace line 224 (the bare judge call).
  - Replace lines 244-250 (the regeneration block).
  - Replace lines 252-258 (the promotion and stop tail).
  - The file becomes 298 lines.
- Modify: `tests/test_iterate_story.py` (append T-M5, T-M6, T-M6b, T-M9).
- Test: `tests/test_iterate_story.py`; final acceptance across both new test files plus R1 and R2.

**Interfaces:**
- Consumes: everything from Task 7, in particular `_run`, `_tail`, `promote`, `_write_summary`, `select_best_round`, and the test helpers `FakeRun` and `_make_story`.
- Produces:
  - `story_md_hash(story_md_path) -> str`, the sha256 hex digest of the raw bytes.
  - The final `main()`: E5 (`judge-story` nonzero), E6 (`ltx-movie` nonzero) and E6b (`ltx-movie` exit 0 with `story.md` byte-identical) each return 1, after promoting the best archived round, or after printing `No round completed; live files left unchanged.` when nothing was archived. The summary's `stop_reason` is `"judge-story failed"`, `"ltx-movie failed"` or `"ltx-movie no-op"`.

- [ ] **Step 1: Write the failing test**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && cat >> tests/test_iterate_story.py <<'PLAN_EOF'


# --- T-M5, T-M6, T-M6b, T-M9: failure paths and no-op detection (spec 3.5, 6) ---------

def test_tm5_judge_failure_mid_loop_promotes_best_so_far(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(6, 6, 6, 6), (7, 3, 3, 3), 1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    out, err = capsys.readouterr()
    assert "round 3" in err
    assert "judge-story exited 1" in err
    assert "judge boom" in err
    assert ("Promoted best round 1 (v1) to story.md, story_prompt.txt, judgment.json."
            in err)
    assert "Stopped:" not in out
    assert (fake.judge_calls, fake.ltx_calls) == (3, 2)
    _assert_live_equals_archive(story_dir, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "judge-story failed"
    assert summary["best_round"] == 1
    assert len(summary["rounds"]) == 2


def test_tm6_ltx_movie_failure_restores_best_round(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(5, 5, 5, 5)], ltx_script=[1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "ltx-movie exited 1" in err
    assert "ltx boom" in err
    assert _read_bytes(os.path.join(story_dir, "story.md")) != b"GARBAGE"
    _assert_live_equals_archive(story_dir, 1)
    assert not os.path.exists(fake.overrides[0][0])
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "ltx-movie failed"
    assert summary["best_round"] == 1


def test_tm6b_round1_judge_failure_leaves_live_files(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    before = _read_bytes(os.path.join(story_dir, "story.md"))
    fake = FakeRun(story_dir, [1])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "judge-story exited 1" in err
    assert "No round completed; live files left unchanged." in err
    assert _read_bytes(os.path.join(story_dir, "story.md")) == before
    assert not os.path.exists(os.path.join(story_dir, "story.v1.md"))
    summary = _summary(story_dir)
    assert summary["best_round"] is None
    assert summary["rounds"] == []
    assert summary["stop_reason"] == "judge-story failed"


def test_tm9_noop_regeneration_is_failure(tmp_path, monkeypatch, capsys):
    story_dir = _make_story(tmp_path, monkeypatch)
    fake = FakeRun(story_dir, [(5, 4, 4, 3)], ltx_script=["noop"])
    monkeypatch.setattr(iterate_story.subprocess, "run", fake)
    assert iterate_story.main(["--story-id", STORY_ID, "--threshold", "9"]) == 1
    err = capsys.readouterr().err
    assert "round 1" in err
    assert "ltx-movie exited 0 but story.md was not regenerated" in err
    assert (fake.judge_calls, fake.ltx_calls) == (1, 1)
    _assert_live_equals_archive(story_dir, 1)
    summary = _summary(story_dir)
    assert summary["stop_reason"] == "ltx-movie no-op"
    assert summary["best_round"] == 1
    assert len(summary["rounds"]) == 1
PLAN_EOF
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `4 failed, 12 passed`.
- `test_tm5_...` fails on `assert ... == 1`. The judge failure is ignored, so the stale round-2 judgment is re-archived and reads as a plateau, which returns 0.
- `test_tm6_...` and `test_tm9_...` fail with `IndexError: pop from empty list`. The loop keeps going and asks the fake judge for a round it was never scripted.
- `test_tm6b_...` fails with `FileNotFoundError` on `judgment.json`.

- [ ] **Step 3: Write minimal implementation**

Make five Edit-tool edits to `bin/iterate-story`. Each `old_string` is unique.

Edit 1 (add `story_md_hash` before `main`). old_string:
```python
def main(argv=None):
    parser = build_parser()
```
new_string:
```python
def story_md_hash(story_md_path):
    """sha256 hex digest of story.md's raw bytes (spec 3.5). Not pure: reads the file."""
    with open(story_md_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(argv=None):
    parser = build_parser()
```

Edit 2 (track the failure). old_string:
```python
    stop_reason = None
    round_number = 0
```
new_string:
```python
    stop_reason = None
    failure = None
    round_number = 0
```

Edit 3 (E5: judge-story nonzero). old_string:
```python
        _run(build_judge_cmd(args.story_id))
```
new_string:
```python
        judge = _run(build_judge_cmd(args.story_id))
        if judge.returncode != 0:
            failure = ("judge-story failed",
                       "Error: round %d: judge-story exited %d; last output:\n%s"
                       % (round_number, judge.returncode, _tail(judge.stdout)))
            break
```

Edit 4 (E6 and E6b). The pre-hash is taken immediately before the call. The post-hash is compared only after a zero exit: a nonzero exit is E6 whatever the hash says, so no ltx-movie failure can turn into a traceback over a deleted `story.md`. See Appendix A, R4. old_string:
```python
        fd, override_path = tempfile.mkstemp(prefix="iterate-story-prompt-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(build_next_prompt(judgment["revised_prompt"], pinned_panel_count))
            _run(build_ltx_movie_cmd(args.story_id, override_path, pinned_panel_count))
        finally:
            os.remove(override_path)
```
new_string:
```python
        pre_hash = story_md_hash(story_md_path)
        fd, override_path = tempfile.mkstemp(prefix="iterate-story-prompt-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(build_next_prompt(judgment["revised_prompt"], pinned_panel_count))
            regen = _run(build_ltx_movie_cmd(args.story_id, override_path, pinned_panel_count))
        finally:
            os.remove(override_path)
        if regen.returncode != 0:
            failure = ("ltx-movie failed",
                       "Error: round %d: ltx-movie exited %d; last output:\n%s"
                       % (round_number, regen.returncode, _tail(regen.stdout)))
            break
        if story_md_hash(story_md_path) == pre_hash:
            failure = ("ltx-movie no-op",
                       "Error: round %d: ltx-movie exited 0 but story.md was not regenerated "
                       "(unchanged content); last output:\n%s"
                       % (round_number, _tail(regen.stdout)))
            break
```

Edit 5 (promote whenever any round was archived, on stops and failures alike; then summary; then report). old_string:
```python
    best_round = select_best_round(rounds)
    best_version = version_base + best_round
    promote(story_dir, best_version)
    _write_summary(story_dir, stop_reason, best_round, records)
    print("Stopped: %s. Best round: %d (v%d), promoted to story.md, story_prompt.txt, "
          "judgment.json." % (stop_reason, best_round, best_version))
    return 0
```
new_string:
```python
    best_round = None
    best_version = None
    if rounds:
        best_round = select_best_round(rounds)
        best_version = version_base + best_round
        promote(story_dir, best_version)
    _write_summary(story_dir, stop_reason if failure is None else failure[0], best_round,
                   records)
    if failure is None:
        print("Stopped: %s. Best round: %d (v%d), promoted to story.md, story_prompt.txt, "
              "judgment.json." % (stop_reason, best_round, best_version))
        return 0
    print(failure[1], file=sys.stderr)
    if best_round is None:
        print("No round completed; live files left unchanged.", file=sys.stderr)
    else:
        print("Promoted best round %d (v%d) to story.md, story_prompt.txt, judgment.json."
              % (best_round, best_version), file=sys.stderr)
    return 1
```

- [ ] **Step 4: Run test to verify it passes, then run the full acceptance gate**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py -v
```
Expected: `16 passed, 1 warning`.

Next, the task's own negative controls (spec 7.5 rows "Promotion skipped on the failure path" and "No-op detection removed"):
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 promotion skipped on the failure path", "bin/iterate-story",
     [('        promote(story_dir, best_version)\n', '        if failure is None:\n            promote(story_dir, best_version)\n')],
     I, ['test_tm5_judge_failure_mid_loop_promotes_best_so_far', 'test_tm6_ltx_movie_failure_restores_best_round']),
    ("7.5 no-op detection removed", "bin/iterate-story",
     [('        if story_md_hash(story_md_path) == pre_hash:\n', '        if False:\n')],
     I, ['test_tm9_noop_regeneration_is_failure']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: three `... CAUGHT` lines, one per named test, then `ALL 2 MUTATIONS CAUGHT; sources restored`.

**A1 (spec 7.6).** The main thread runs this itself; counts reported by an implementer are not accepted.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_iterate_story.py tests/test_ltx_movie_iterate_flags.py -v
```
Expected: `27 passed, 2 warnings`, with 16 `test_iterate_story.py::test_t*` lines and 11 `test_ltx_movie_iterate_flags.py::test_tl*` lines.

**A2 (spec 7.6): the full spec 7.5 sweep against the final code.** The script covers all 18 rows: the `--panels`/`--story-only` row runs as two mutations, so there are 19 mutations in total. Each runs against every named test that exists, so rows naming two tests are checked against both.
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 - <<'EOF'
import os, subprocess, tempfile

L = "tests/test_ltx_movie_iterate_flags.py"
I = "tests/test_iterate_story.py"
# (label, file, [(old, new), ...] applied in order, test file, tests that must each FAIL)
MUTATIONS = [
    ("7.5 threshold >= changed to >", "bin/iterate-story",
     [('    if all(s >= threshold for s in history[-1]):\n', '    if all(s > threshold for s in history[-1]):\n')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 plateau compares to history[0]", "bin/iterate-story",
     [('zip(history[-1], history[-2])', 'zip(history[-1], history[0])')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 plateau checked before threshold", "bin/iterate-story",
     [('    if all(s >= threshold for s in history[-1]):\n        return STOP_THRESHOLD\n    if len(history) >= 2 and not any(c > p for c, p in zip(history[-1], history[-2])):\n        return STOP_PLATEAU\n', '    if len(history) >= 2 and not any(c > p for c, p in zip(history[-1], history[-2])):\n        return STOP_PLATEAU\n    if all(s >= threshold for s in history[-1]):\n        return STOP_THRESHOLD\n')],
     I, ['test_tp4_evaluate_stop']),
    ("7.5 best round by average first, then minimum", "bin/iterate-story",
     [('        key = (min(scores), sum(scores))\n', '        key = (sum(scores), min(scores))\n')],
     I, ['test_tp5_select_best_round']),
    ("7.5 full tie picks the latest", "bin/iterate-story",
     [('        if best_key is None or key > best_key:\n', '        if best_key is None or key >= best_key:\n')],
     I, ['test_tp5_select_best_round', 'test_tm3_existing_versions_and_earliest_tie_promotion']),
    ("7.5 find_version_base returns 0 without scanning", "bin/iterate-story",
     [('    return highest\n', '    return 0\n')],
     I, ['test_tp3_find_version_base', 'test_tm3_existing_versions_and_earliest_tie_promotion']),
    ("7.5 re-injection prepended instead of appended", "bin/iterate-story",
     [('    return cleaned + build_reinjection(pinned_panel_count)\n', '    return build_reinjection(pinned_panel_count) + cleaned\n')],
     I, ['test_tp2_build_reinjection_and_fallback_append', 'test_tm2_subprocess_argv_and_override_file']),
    ("7.5 PANEL_COUNT_DECLARATION_RE.sub call removed", "bin/iterate-story",
     [('    cleaned = PANEL_COUNT_DECLARATION_RE.sub("", revised_prompt)\n', '    cleaned = revised_prompt\n')],
     I, ['test_tp2b_build_next_prompt_replaces_conflicting_declaration']),
    ("7.5 archive taken after regeneration instead of after judging", "bin/iterate-story",
     [('        _archive(story_dir, version)\n', ''), ('            os.remove(override_path)\n', '            os.remove(override_path)\n        _archive(story_dir, version)\n')],
     I, ['test_tm3_existing_versions_and_earliest_tie_promotion']),
    ("7.5 promotion skipped on the failure path", "bin/iterate-story",
     [('        promote(story_dir, best_version)\n', '        if failure is None:\n            promote(story_dir, best_version)\n')],
     I, ['test_tm5_judge_failure_mid_loop_promotes_best_so_far', 'test_tm6_ltx_movie_failure_restores_best_round']),
    ("7.5 danger condition reduced to args.force_story", "bin/ltx-movie",
     [('        if args.force_story and args.no_review:\n', '        if args.force_story:\n')],
     L, ['test_tl2_force_story_alone_omits_danger_auto_approve']),
    ("7.5 override read but build_story_prompt result still used", "bin/ltx-movie",
     [('        else:\n            prompt = build_story_prompt(args.narrative,', '        if True:\n            prompt = build_story_prompt(args.narrative,')],
     L, ['test_tl5_story_prompt_override_used_verbatim']),
    ("7.5 override missing-file check removed from main()", "bin/ltx-movie",
     [('    if args.story_prompt_override is not None and not os.path.isfile(args.story_prompt_override):\n', '    if False:\n')],
     L, ['test_tl7_missing_override_file_exits_2']),
    ("7.5 --story-only still inserts phase_release_story_server", "bin/ltx-movie",
     [('        phases = (phase1_story,)\n', '        phases = (phase1_story, phase_release_story_server)\n')],
     L, ['test_tl8_story_only_runs_phase1_only']),
    ("7.5 --story-only omits the phase0_seed prefix", "bin/ltx-movie",
     [('            phases = (phase0_seed,) + phases\n', '            pass\n')],
     L, ['test_tl9_story_only_with_seed_image_keeps_phase0']),
    ("7.5 neither-narrative-nor-override validation removed", "bin/ltx-movie",
     [('    if args.narrative is None and args.story_prompt_override is None:\n', '    if False:\n')],
     L, ['test_tl10_no_narrative_and_no_override_exits_2']),
    ("7.5 build_ltx_movie_cmd omits --panels", "bin/iterate-story",
     [('"--panels", str(pinned_panel_count), ', '')],
     I, ['test_tm2_subprocess_argv_and_override_file']),
    ("7.5 build_ltx_movie_cmd omits --story-only", "bin/iterate-story",
     [('"--story-only", ', '')],
     I, ['test_tm2_subprocess_argv_and_override_file']),
    ("7.5 no-op detection removed", "bin/iterate-story",
     [('        if story_md_hash(story_md_path) == pre_hash:\n', '        if False:\n')],
     I, ['test_tm9_noop_regeneration_is_failure']),
]

def run(test_file, name):
    # Fresh bytecode cache per run: a same-size mutation written in the same second as an
    # earlier compile would otherwise load the stale .pyc and falsely "survive".
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="iterate-story-pyc-"))
    return subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           "%s::%s" % (test_file, name)],
                          capture_output=True, text=True, env=env).returncode


for label, path, edits, test_file, tests in MUTATIONS:
    src = open(path, encoding="utf-8").read()
    for name in tests:
        assert run(test_file, name) == 0, "control: %s must pass unmutated" % name
    mutated = src
    for old, new in edits:
        assert mutated.count(old) == 1, "%s: anchor found %d times" % (label, mutated.count(old))
        mutated = mutated.replace(old, new)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(mutated)
        for name in tests:
            rc = run(test_file, name)
            print("%s | %s: %s" % (label, name, "CAUGHT" if rc == 1 else "NOT CAUGHT (rc=%d)" % rc))
            assert rc == 1, "mutation %r not caught by %s" % (label, name)
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    assert open(path, encoding="utf-8").read() == src, "restore failed: " + path
print("ALL %d MUTATIONS CAUGHT; sources restored" % len(MUTATIONS))

EOF
```
Expected: 23 `... CAUGHT` lines and `ALL 19 MUTATIONS CAUGHT; sources restored`.

**R1 and R2 (spec 7.6), plus the diff-shape check:**
```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 tests/test_ltx_movie_offline.py > /tmp/iterate_story_r1_final.txt 2>&1; echo "rc=$?"; tail -1 /tmp/iterate_story_r1_final.txt
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && python3 -m pytest tests/test_judge_story.py -q
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git diff --numstat -- bin/iterate-story && git status --short -- bin/judge-story bin/qwen-agent tests/test_ltx_movie_offline.py tests/test_deploy_pkg.py
```
Expected:
- R1: `rc=0`, `OK 340/340`
- R2: `18 passed`
- `bin/iterate-story` numstat: `45	9	qwen-agent-workspace/bin/iterate-story` (Task 8's five edits, relative to the Task 7 commit; measured in the sandbox).
- The `git status --short` line for `bin/qwen-agent` shows its pre-existing ` M`, unchanged from the start of this plan. The other three paths print nothing.

- [ ] **Step 5: Commit**

```bash
cd /Users/reubenpatterson/local_model_harness/qwen-agent-workspace && git add bin/iterate-story tests/test_iterate_story.py && test "$(git diff --cached --name-only)" = "$(printf 'qwen-agent-workspace/bin/iterate-story\nqwen-agent-workspace/tests/test_iterate_story.py')" && git commit -m "iterate-story: handle subprocess failures and no-op regenerations" -m "A nonzero judge-story (E5) or ltx-movie (E6) exit, or an ltx-movie
exit 0 that leaves story.md byte-identical by sha256 (E6b, closing G2),
now stops the loop, promotes the best archived round (or leaves the live
files untouched if none), writes run-summary.json with the failure
reason, prints the last 40 lines of child output, and exits 1. Spec
Sections 3.5 and 6 (tests T-M5, T-M6, T-M6b, T-M9); A1 27 passed, all
spec 7.5 mutations caught, R1 OK 340/340, R2 18 passed." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**After the plan (spec 7.6 M1, not a task).** This is a manual, user-run real end-to-end check. It needs `ANTHROPIC_API_KEY` and the story server up (`bin/story-server vision`, `GPU_MEM_UTIL=0.70`).
- Optional first step: copy `generated/stories/ronin-generalship/judgment.json` to an unused suffix if it should be kept, because round 1 overwrites it (G10).
- Command: `bin/iterate-story --story-id ronin-generalship --threshold <N>`.
- Pass:
  - exit 0;
  - the first new archive is one above the highest pre-existing `.vN` (`.v3` today);
  - every pre-existing `.vN` sha256 is unchanged;
  - every archived `story.v<N>.md` has exactly 20 `## Panel` lines;
  - `run-summary.json` is present, and the live files equal the `best_round` archive;
  - the story server is still up after the run.

---

## Appendix A: Spec readings this plan pins

Each item below resolves a place where two spec sentences pull in different directions, or where the spec left a detail open. None changes designed behavior.

- **R1. `hashlib` import.** Spec 1.1's import list omits `hashlib`, but 1.6 and 3.5 define `story_md_hash` as `hashlib.sha256(...)`. The plan imports it at top level alongside the other stdlib modules.
- **R2. T-L10 "Returns 2".** Spec 4.3 mandates `parser.error(...)`, which raises `SystemExit(2)` rather than returning. T-L10 therefore asserts `pytest.raises(SystemExit)` with `code == 2`, the same mechanism T-M8 uses.
- **R3. `_phase_sequence` docstring kept.** Spec 4.3 shows the new body without the existing docstring, and spec 4 says no other line changes. The plan inserts the `--story-only` branch right after the docstring and leaves the rest of the function textually unchanged.
- **R4. When the post-hash is taken.**
  - Spec 3.5 says "regardless of its exit code"; spec 1.2 step 6 orders "nonzero -> E6, otherwise compute post_hash".
  - The plan follows 1.2. Observable behavior is identical, because a nonzero exit is E6 either way.
  - It also avoids a traceback in place of E6 when a failed child deleted `story.md`.
- **R5. Failure-exit ordering.** Spec 1.3 orders promote, then write `run-summary.json`, then print. Spec 6 prints the error lines and then writes the summary. The plan follows 1.3. Nothing can observe the difference except a crash between the two.
- **R6. Unspecified wording.** These are plan choices:
  - the `--story-id` help text (`iterate on generated/stories/ID/story.md`);
  - the parser description sentence;
  - `--max-rounds` help ending `(default: %(default)s)`.
- **R7. Test-fake details spec 7.1 leaves open.**
  - The ltx-movie fake's `k` counts ltx-movie calls, and the judge's `k` counts judge calls.
  - Fake judge failures print `judge boom`; fake ltx-movie failures print `ltx boom`.
  - The fake writes `judgment.json` with `json.dumps(..., indent=2) + "\n"`.
  - Fixture stories have 4 panels (`PINNED = 4`), distinct from the 1-panel regenerated text, so a pin taken from the wrong file is caught.
- **R8. Extra assertions inside spec IDs.** These add coverage without changing the test count:
  - T-P2b: the regex pattern verbatim, multi-occurrence removal, and the singular `section` form.
  - T-P3: a numeric (not lexicographic) maximum.
  - T-M1: the raw `run-summary.json` formatting.
  - T-M2: the exact kwargs dict, and a temp file outside `story_dir`.
  - T-M6: the temp file is removed on failure, and the tail text reaches stderr.
  - T-M7: the `Error: ` prefix.
  - T-M8: the `parser.error` texts.
  - T-L1: exactly one `--danger-auto-approve`.
  - T-L8: `story_server_stop_after_story` is still `True`.
- **R9. Spec 7.5 mutation forms.**
  - "`--story-only` checked after the insertion" is applied in its effect-equivalent form: `phase_release_story_server` is still in the `--story-only` tuple.
  - "`build_ltx_movie_cmd` omits `--panels` or `--story-only`" runs as two mutations.
  - Every mutation runner asserts that each listed test fails, which is stricter than spec A2's "at least one".

## Appendix B: Coverage map

| Spec item | Task(s) |
|---|---|
| 0.3 D1 `bin/iterate-story` | 4, 5, 6, 7, 8 |
| 0.3 D2 `tests/test_iterate_story.py` | 4, 5, 6, 7, 8 |
| 0.3 D3 `bin/ltx-movie` (4.1 / 4.2 / 4.3) | 1 / 2 / 3 |
| 0.3 D4 `tests/test_ltx_movie_iterate_flags.py` | 1, 2, 3 |
| 1.1 script conventions | 4 (file, shebang, imports, chmod), 7 (`main`, `__main__`) |
| 1.2 round steps, 1.3 execution sequence | 7 (steps 1-8, happy path), 8 (E5/E6/E6b exits, step 8 on failure) |
| 1.4 version suffixes | 5 (`find_version_base`), 7 (`_archive`, `v<base+r>`) |
| 1.5 best round + promotion (incl. `story_prompt.revised.txt`) | 6 (`select_best_round`), 7 (`promote`), 8 (promotion on failure) |
| 1.6 internal names | 4-8 (all names verbatim) |
| 2.1-2.4 CLI, paths, preconditions, exit codes | 7 (exit 0/2), 8 (exit 1) |
| 3.1, 3.2 pinned count, re-injection, G19 removal, temp file | 4, 7 (temp file + `finally` removal) |
| 3.3 stopping criteria | 6 |
| 3.4 subprocess invocations (3.4.1, 3.4.2; G1 argv) | 7 |
| 3.5 no-op detection (G2) | 8 |
| 4.1 / 4.2 / 4.3 / 4.4 | 1 / 2 / 3 / 1-3 (guards, R1, Python 3.9 parse) |
| 5.1 stdout, 5.2 `run-summary.json`, 5.3 files | 7 (stop paths), 8 (failure paths) |
| 6 E1-E4 / E5, E6, E6b + promotion lines | 7 / 8 |
| 7.1 framework, autouse guards, fake | 1 (D4 guard), 4 (D2 guard), 7 (`FakeRun`), 8 (`"noop"`, failure entries) |
| 7.5 mutation checks (18 rows) | per-task runs in 1-8; full sweep in 8 |
| 7.6 A1, A2, R1, R2 | 8 (R1 also in 1, 2, 3) |
| 7.6 M1 | manual, after Task 8 |
| 8 G1 / G2 / G19 | 3 + 7 / 8 / 4 |

| Test ID | Task | Test ID | Task | Test ID | Task |
|---|---|---|---|---|---|
| T-P1 | 4 | T-M1 | 7 | T-L1 | 2 |
| T-P2 | 4 | T-M2 | 7 | T-L2 | 2 |
| T-P2b | 4 | T-M3 | 7 | T-L3 | 2 |
| T-P3 | 5 | T-M4 | 7 | T-L4 | 2 |
| T-P4 | 6 | T-M5 | 8 | T-L5 | 1 |
| T-P5 | 6 | T-M6 | 8 | T-L6 | 1 |
| | | T-M6b | 8 | T-L7 | 1 |
| | | T-M7 | 7 | T-L8 | 3 |
| | | T-M8 | 7 | T-L9 | 3 |
| | | T-M9 | 8 | T-L10 | 3 |
| | | | | T-L11 | 3 |

| Success criterion | Tests (task) |
|---|---|
| SC1 | T-M1, T-M2 (7) |
| SC2 | T-P4 (6) |
| SC3 | T-P5 (6), T-M3 (7), T-M5, T-M6 (8) |
| SC4 | T-P3 (5), T-M3 (7) |
| SC5 | T-M1, T-M4, T-M7, T-M8 (7), T-M5 (8) |
| SC6 | T-M1, T-M3 (7) |
| SC7 | T-L5 (1) |
| SC8 | T-L1-T-L4 (2) |
| SC9 | autouse guards (1, 4) |
| SC10 | R1 (1, 2, 3, 8) |
| SC11 | T-L8, T-L9 (3) |
| SC12 | T-L10, T-L11 (3) |
| SC13 | T-M2 (7) |
| SC14 | T-M9 (8) |
