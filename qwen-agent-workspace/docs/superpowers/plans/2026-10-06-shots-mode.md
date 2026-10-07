# Shots mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code block that goes into a file is applied with the block applier (Global Constraints), never retyped.

**Goal:** Add `bin/ltx-movie --shots`: every panel is an independent single-action shot with its own `Image:` still, and every clip renders from its own still (no chaining):
- Phase 1 uses `STORY_PROMPT_TEMPLATE_SHOTS` (plus the shots Cast block when cast), validates the shot rules S1-S7 in `character_lib.shots_violations`, and asks the story model for exactly one rewrite of a draft it wrote in this run (the draft is moved aside, never overwritten);
- Phase 2 renders a still for every panel, one `bin/ltx-story-images --only <group> --shots` process per stills-LoRA group, skipping a group whose stills all exist;
- Phase 3 builds a schema-3 `--shots` manifest in which every panel is `conditioning: "still"`; Phase 4 renders it with `--on-panel-failure skip` through the unchanged render tool;
- every cast character LoRA, lone or paired, is 0.8 by default in shots mode;
- `--shots --redo N[,M]` moves (never deletes) those panels' still, clip and provenance plus `movie.mp4` into `<story>/redo/<stamp>-<pid>/`, so only they re-render;
- without `--shots`, every existing output stays byte-identical (SC9).

**Architecture:** `character_lib.py` (stdlib only, already shipped) owns every shot rule: the roster parser, the Motion: heuristics, the validator, the advisories and the rewrite block, because `bin/ltx-movie` may not `import re` (pin L7j). `bin/ltx-movie` loads it with the existing `_character_lib()` only on the `--shots` or casting path, and computes the stills groups with bin/ltx-story-images' own `_style_text`/`_compose_prompt` (loaded by path), so each group is exactly one LoRA set and E-P16 cannot fire. `bin/ltx-story-manifest --shots` and `bin/ltx-story-images --shots` each gain one flag; `bin/ltx-mlx-render` is unchanged (a shots manifest is a schema-3 manifest whose panels are all `still`).

**Tech Stack:** Python 3.13.0 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), pytest 8.3.4, Pillow, ffmpeg/ffprobe (S66 uses the real ffprobe), Apple `/usr/bin/python3` 3.9.6 (deploy unittest gate only). torch/diffusers/LTX only behind fakes in tests.

**Spec:** `docs/superpowers/specs/2026-10-06-shots-mode-design.md`, user-approved, commit `c7309e1` on branch `qwen-agent-redteam`. Spec decisions are not reopened. Where the spec is mechanically inexact, the reading this plan implements is listed under "Decisions" with the observed evidence; the coordinator may overrule any of them.

**How this plan was validated (2026-10-06):** every code block and edit below was built in a scratch copy of the workspace (`/tmp/shotsplan/dev`, a `git archive` export of `c7309e1`). Every block that transcribes spec code was spliced in from the spec file by a generator, byte for byte. The plan text was then replayed, task by task, onto a fresh `git archive` export of `c7309e1` that was made a git repository with the same `qwen-agent-workspace/` layout (`/tmp/shotsplan/sim`): every block applied with the block applier from this file, every red and green run, every regression block, every commit command, the A1 coverage check, the B-goldens, the 63-row mutation runner and the deploy suites under both interpreters. Every "Expected:" count below is an observation from that replay. The export lacks the gitignored `generated/charlora/tools/` that `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` reads, so the replay symlinked that one directory from the real workspace (on the real tree the file exists and D2 passes; nothing else was needed).

## Global Constraints

**Workspace and scope**
- Workspace root `WS` = `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`. Run every command from `WS`. The git repo root is one level up, so `git diff --name-only` prints `qwen-agent-workspace/`-prefixed paths. Branch `qwen-agent-redteam`; base commit for the scope check: `c7309e1`.
- `$PLAN` is the absolute path of this plan file. Set it once per shell (for example `export PLAN=/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/docs/superpowers/plans/2026-10-06-shots-mode.md` if the orchestrator saved it there, or `/tmp/shotsplan/plan.md`).
- The working tree has unrelated modified files (`bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, `.gitignore`, `qwen-agent-workspace/.gitignore`) and many untracked files. Never stage them. Every commit stages files by explicit path and checks `git diff --cached --name-only` first. Every file this plan edits (`character_lib.py`, `bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/ltx-story-images`) was verified clean against `HEAD` before planning; before each task, `git diff --quiet HEAD -- <that task's existing files>` must succeed.
- Commit messages start with a component prefix (`character_lib: `, `ltx-movie: `, `ltx-story-manifest: `, `ltx-story-images: `, `ltx-mlx-render: `) and end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push (pushing is gated by a design review).
- GPU work (Z-Image, LTX renders), story-server control and the real story model happen only in the live gates that the orchestrator runs (Final Acceptance, L-S1 and L-S2). Every implementer step is offline: fakes and mocks, no network, no GPU, no server. The Phase 2 tests make any real subprocess call from `bin/ltx-movie` fail (Decision 15). Do not run implementer tasks while a live gate is running.
- `rm` is blocked in this environment. Where a step needs a fresh path, use a new path or move the old one aside with `mv`; never delete.
- Spec text quoted "verbatim" is spliced from the spec file byte for byte, except that a spec heading inside a quoted excerpt is demoted one level (`### 5.9` appears as `#### 5.9`) so that it cannot be mistaken for a task heading.
- Every edit anchor in this plan occurs exactly once in its file at the moment it is applied (the applier refuses otherwise). Edits within one step are applied in document order.

**The block applier.** Every code block that an implementer must write into a file carries a machine-readable opening fence: four backticks followed by, for example, `python plan=T2.S1.1 op=create path=tests/test_shots_mode.py`. Implementers never retype or copy-paste such a block: they apply it with this tool, which writes the bytes exactly as they are in this file (the previous execution lost U+2019 and U+2014 characters by retyping) and refuses any `replace` anchor that does not occur exactly once. Bootstrap it once per session with this exact command (ASCII only, safe to type), where `$PLAN` is the absolute path of this plan file:

````bash
mkdir -p /tmp/shotsplan-tools && python3 -c 'import re,sys; t=open(sys.argv[1],encoding="utf-8").read(); m=re.search(r"^(`{4,})python plan=TOOL\.apply op=create path=\S+\n(.*?)^\1$", t, re.S | re.M); open("/tmp/shotsplan-tools/apply_plan.py","w",encoding="utf-8").write(m.group(2))' "$PLAN" && python3 /tmp/shotsplan-tools/apply_plan.py --self-check "$PLAN"
````

Expected last line: `apply_plan: self-check ok (<N> blocks, ids unique)`. Then apply a step's blocks, from `WS`, with `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" <ID>` (for example `T2.S1`). It prints one `ok <id> <op> <path>` line per block, and writes nothing at all if any block of the selection fails its check.

````python plan=TOOL.apply op=create path=/tmp/shotsplan-tools/apply_plan.py
#!/usr/bin/env python3
"""Apply this plan's code blocks byte for byte (shots-mode plan, Global Constraints).

usage: python3 apply_plan.py PLAN_MD ID [ID ...]
       python3 apply_plan.py --self-check PLAN_MD

Every code block whose opening fence carries plan=<id> is addressable. An ID selects every
block whose id equals it or starts with it followed by "."; the selected blocks are applied
in document order. A block's text is the lines between its fences, each followed by "\n".
Operations (op=):
  create   write path, which must not exist yet
  append   append to path, which must exist and end with "\n"
  replace  text that must occur exactly once in path; the next block must be op=with
  with     the replacement text for the preceding replace block
Relative paths are resolved against the current directory (run it from WS). Nothing is
written unless every selected block passes its check.
"""
import os
import re
import sys

FENCE = re.compile(r"^(`{4,})(\S*)((?: +\S+=\S+)*) *$")


def parse(plan_path):
    with open(plan_path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    found, i = [], 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        ticks = m.group(1)
        attrs = dict(kv.split("=", 1) for kv in m.group(3).split())
        j = i + 1
        while j < len(lines) and lines[j] != ticks:
            j += 1
        if j == len(lines):
            sys.exit("apply_plan: unterminated fence at line %d" % (i + 1))
        if "plan" in attrs:
            found.append((attrs, "".join(line + "\n" for line in lines[i + 1:j])))
        i = j + 1
    ids = [a["plan"] for a, _ in found]
    dupes = sorted(set(x for x in ids if ids.count(x) > 1))
    if dupes:
        sys.exit("apply_plan: duplicate block ids: %s" % ", ".join(dupes))
    return found


def main(argv):
    if argv[:1] == ["--self-check"]:
        found = parse(argv[1])
        print("apply_plan: self-check ok (%d blocks, ids unique)" % len(found))
        return 0
    if len(argv) < 2:
        sys.exit(__doc__)
    plan, wanted = argv[0], argv[1:]
    chosen = [(a, t) for a, t in parse(plan)
              if any(a["plan"] == w or a["plan"].startswith(w + ".") for w in wanted)]
    if not chosen:
        sys.exit("apply_plan: no block matches %s" % " ".join(wanted))
    files = {}

    def current(path):
        if path in files:
            return files[path]
        if not os.path.isfile(path):
            sys.exit("apply_plan: %s does not exist" % path)
        with open(path, encoding="utf-8") as f:
            return f.read()

    k = 0
    while k < len(chosen):
        attrs, text = chosen[k]
        op, path = attrs.get("op"), attrs.get("path")
        if op == "create":
            if path in files or os.path.lexists(path):
                sys.exit("apply_plan: %s: %s already exists" % (attrs["plan"], path))
            files[path] = text
        elif op == "append":
            body = current(path)
            if not body.endswith("\n"):
                sys.exit("apply_plan: %s: %s does not end with a newline" % (attrs["plan"], path))
            files[path] = body + text
        elif op == "replace":
            if (k + 1 >= len(chosen) or chosen[k + 1][0].get("op") != "with"
                    or chosen[k + 1][0].get("path") != path):
                sys.exit("apply_plan: %s: not followed by its op=with block" % attrs["plan"])
            body = current(path)
            count = body.count(text)
            if count != 1:
                sys.exit("apply_plan: %s: anchor occurs %d times in %s (must be exactly 1)"
                         % (attrs["plan"], count, path))
            files[path] = body.replace(text, chosen[k + 1][1], 1)
            print("ok %s %s %s" % (attrs["plan"], op, path))
            k += 1
            attrs = chosen[k][0]
            op = "with"
        else:
            sys.exit("apply_plan: %s: unknown op %r" % (attrs["plan"], op))
        print("ok %s %s %s" % (attrs["plan"], op, path))
        k += 1
    for path, text in files.items():
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
````

**Deliverables (spec 0.3, verbatim)**

| # | Item | File | Action |
|---|---|---|---|
| D1 | Shots strength, shots Cast block, phrase finder, roster parser, shot-rule validator, advisories, rewrite block | `character_lib.py` | edit (additions only, plus a `shots=` keyword on two functions) |
| D2 | `--shots`, `--redo`, shots template, validation and rewrite, stills groups, redo phase, shots manifest flags, skip policy, dry run | `bin/ltx-movie` | edit |
| D3 | `--shots` manifest mode (schema 3, every panel `still`, cast from Image: ∪ Motion:) | `bin/ltx-story-manifest` | edit |
| D4 | `--shots` strength rule and pinned seed | `bin/ltx-story-images` | edit |
| D5 | Tests | `tests/test_shots_mode.py` | new |

`bin/ltx-mlx-render`, `ltx2_mlx_video_skill.py`, `z_image_skill.py`, `bin/qwen-agent`, the judges, `bin/iterate-story`, the deploy tooling and **every existing test file** are unchanged.

No other tracked file changes, and no existing test file is edited (spec 0.2: "None of these test files is edited").

**Out of scope (spec 0.4, verbatim)**

- `--shots` with `--seed-image` (refused, E-S2) or with `--no-stills` (refused, E-S1).
- Changing judges. `seam_continuity` still assumes one continuous take (G4).
- Merging `images/images.json` across stills groups (G5).
- A seed-varying "new take" for `--redo` (G6).
- Validating semantic composition rules (framing, background placement, contact). They are prompt rules with non-fatal advisories (4.4, G2).
- A panel-count cap (9.1).
- Changing continuous mode in any observable way.

**Success criteria (spec 0.5, verbatim)**

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | `--shots` builds its Phase 1 prompt from `STORY_PROMPT_TEMPLATE_SHOTS` (5.2), and a cast run uses the shots Cast block (3.3), both byte-exact | S3, S30-S32, S34 |
| SC2 | Each shot rule S1-S7 (4.3) has a passing case and a failing case with the exact message. Advisories W1-W2 never fail a run | S5-S19, S40 |
| SC3 | A draft that Phase 1 wrote this run and that breaks the rules is moved aside and rewritten exactly once, with the violations listed. A second failure exits 2, naming each panel and rule. A pre-existing story.md that breaks the rules exits 2 without a rewrite | S35-S39 |
| SC4 | Phase 2 renders a still for every panel. Panels are grouped by stills-LoRA set; each group is one `bin/ltx-story-images --only <group> --shots` process, whose `--only` list is exactly that group; a group whose stills all exist is skipped. E-P16 never fires | S42-S45 |
| SC5 | The shots manifest is schema 3. Every panel is `conditioning: "still"` with its own `image_path`; there is no `chain` | S46, S60, S66 |
| SC6 | In shots mode every character LoRA (video and stills, lone or paired) is 0.8 by default; `character.json` strength and then `--character-strength` override it. Continuous mode keeps 1.0 for a lone character | S2, S61, S62, S70, C36 (existing) |
| SC7 | `--shots --redo N[,M]` moves, and never deletes, only those panels' still, clip and clip provenance plus `movie.mp4`. Only those panels re-render; every other still and clip is byte-unchanged | S48, S49, S51, L-S2 |
| SC8 | Every 7.1 argument error exits 2 before any phase, lockfile or GPU work | S33 |
| SC9 | Without `--shots`, every existing argv, prompt, manifest, still prompt, provenance and dry-run is byte-identical. Every 0.2 suite passes at its 0.2 count, and B1-B3 pass | R1, S52 |
| SC10 | The deploy package file set is unchanged. `tests/test_deploy_pkg.py` stays at 165 under both interpreters | R2 |
| SC11 | Live gates L-S1 and L-S2 pass (10.8) | L-S1, L-S2 |

**Module boundaries and new names (spec 1.2, 1.3, verbatim)**

- **`character_lib.py` owns every shot rule** (the roster parser, the Motion: heuristics, the validator, the advisories and the rewrite block). There are three reasons:
  - it is the existing stdlib-only owner of phrase matching;
  - bin/ltx-movie may not `import re` (pin L7j);
  - `character_lib.py` already ships in the deploy package.
- bin/ltx-movie loads it with the existing `_character_lib()` helper, only on the `--shots` path or the casting path. P49 still holds: an uncast run without `--shots` never loads it.
- bin/ltx-movie gets the stills-prompt composition from bin/ltx-story-images itself. It loads that file with `importlib.machinery.SourceFileLoader("ltx_story_images_for_movie", …)` and calls `_style_text` and `_compose_prompt`. The group computation therefore matches what bin/ltx-story-images will do. That file imports only stdlib at import time.
- Panels are still parsed only by `bin/ltx-story-manifest::_parse_prompts_md`, through the existing `_load_story_panels`. The `## Characters` roster is a separate section that this parser ignores by construction (0.2). `character_lib.parse_character_roster` reads only that section, so the "one story.md parser" rule (`bin/ltx-story-images:203-207`) is kept for panels.
- `bin/ltx-mlx-render` needs no change. A shots manifest is a schema-3 manifest whose panels are all `still`, which it already renders, verifies and resumes.

#### 1.3 New names [spec choice]

- **`character_lib.py`:**
  - constants: `SHOTS_CHARACTER_STRENGTH`, `SHOTS_MOTION_MIN_WORDS`, `SHOTS_MOTION_MAX_WORDS`, `SHOTS_MAX_CAST_PER_PANEL`, `SHOTS_REWRITE_MAX_LISTED`, `SHOTS_CLOSE_SHOT_TYPES`, `SHOTS_CAST_BLOCK_RULES`, `SHOTS_REWRITE_TEMPLATE`;
  - private regexes: `_ROSTER_HEADER_RE`, `_ROSTER_ENTRY_RE`, `_SENTENCE_SPLIT_RE`, `_CAMERA_SENTENCE_RE`, `_CHAIN_WORD_RE`, `_COMMA_AND_RE`, `_SHOT_TYPE_RE`;
  - functions: `find_phrases`, `parse_character_roster`, `motion_problems`, `shots_violations`, `shots_advisories`, `shots_rewrite_block`.
- **`bin/ltx-movie`:**
  - constant: `STORY_PROMPT_TEMPLATE_SHOTS`;
  - functions: `_resolve_shots`, `_run_story_agent`, `_shots_check`, `_phase1_shots_finish`, `_panel_list`, `_shots_stills_groups`, `_shots_missing_stills`, `_phase2_shots`, `_print_shots_stills_plan`, `_shots_image_flags`, `_redo_moves`, `phase_redo_shots`.
- **Files written per story:**
  - `story.rejected-<UTC %Y%m%dT%H%M%SZ>-<pid>.md`;
  - `story_prompt.rewrite.txt`;
  - `images/stills-group-<KK>.log`;
  - `redo/<UTC %Y%m%dT%H%M%SZ>-<pid>/{images,clips}/…` and `redo/<…>/movie.mp4`.

**Source-text pins the implementation must keep green (spec 0.2, verbatim)**

| Pin | File:line | Constraint on the edit |
|---|---|---|
| L1z5 | `test_ltx_movie_offline.py:124-128` | `'["--lora", args.stills_lora_path]'` occurs exactly **2** times in bin/ltx-movie, so shots Phase 2 must reuse the already-built Phase 2 `cmd` |
| L1z9, L1z14 | `:150-186` | `'["--model", args.story_model]'` and `'["--context-window", str(args.story_context_window)]'` each occur exactly 2 times, so the rewrite reuses Phase 1's `cmd` |
| L7i | `:426-428` | the 3-line `    if not args.no_stills:\n        for w in _chain_image_warnings(…` block occurs exactly once, unchanged, so the shots path branches off **before** it |
| L7j | `:432-434` | `"\nimport re\n"` must not appear in bin/ltx-movie, so **all shot-rule regexes live in `character_lib.py`** |
| L17b | `:713-715` | `phase2_stills`'s body never mentions `no_stills` |
| L17c | `:716-719` | `'"--chain", "--image", os.path.join(paths["images_dir"], "panel_01.png")'` stays, and `'"--glob"'` never appears |
| L19a-c | `:800-811` | `'"--workspace", WS,'` occurs exactly 2 times, with both literal `cmd = [...]` / `phase1_cmd = [...]` openings unchanged |
| L24, L51, L41 | `:873`, `:1354-1368`, `:1414-1442` | an uncast dry run prints `ltx-mlx-render` twice; `_phase4_flags` keeps stop/skip for stills/no-stills; `_phase_sequence` on an object without `redo_panels` is unchanged |
| L1, P56 | `:50-63` | existing help substrings stay |
| `_render_flags(args)` ×4, `os.path.join(WS, "bin", "ltx-mlx-render")` ×4, `os.path.join(WS, "bin", "story-server")` ×2 | `:722-729`, `:1567-1574` | new code never writes these literals |
| I20, I21 | `test_ltx_story_images.py:581-592` | `_panel_seed(args.seed, i, grounded)` ×2, `_compose_prompt(` ×3, the substring `grounded = bool(style)`, and `lora_path=args.lora_path` all stay |
| P22, P23 | `test_casting_pipeline.py:756`, `:769` | the chained E-P14 warning text is byte-identical; `"--cast requires --chain"` stays a **substring** of the manifest's error |
| `:531` | `test_ltx_movie_offline.py` | the substring `qwen-agent exited %d but story.md exists` stays in bin/ltx-movie |

**Error handling (spec Section 7, verbatim; the exact message templates are in the code blocks of Tasks 3, 6, 8, 9 and 10)**

`Error:` lines go to stderr. `Warning:` lines and `WARNING:` lines go to stdout.

#### 7.1 `bin/ltx-movie` argument errors (exit 2, before any phase, lockfile or GPU work)

| # | Condition | Message |
|---|---|---|
| E-S1 | `--shots` + `--no-stills` | `Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills` |
| E-S2 | `--shots` + `--seed-image` | `Error: --shots is not supported with --seed-image: the seed image can be only panel 1's still, and the seed-image story preface describes the chained flow` |
| E-S3 | `--redo` without `--shots` | `Error: --redo requires --shots` |
| E-S4 | `--redo` value with no int, a non-int, or empty | `Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; got '<v>'` |
| E-S5 | `--redo` panel < 1 or > `--panels` | `Error: --redo panel <n> is out of range (1..<panels>)` |
| E-S6 | `--redo` + `--force-story` | `Error: --redo cannot be combined with --force-story: --force-story writes a new story.md, so every panel changes` |
| E-S7 | `--redo` + `--story-only` | `Error: --redo cannot be combined with --story-only: --story-only stops before the stills and clips that --redo re-renders` |
| E-S8 | `--redo` with no story.md | `Error: --redo needs an existing story.md: <path>` |

Checks run in the order of the 5.1 `_resolve_shots` code: E-S3, E-S1, E-S2, E-S6, E-S7, E-S4, E-S5, E-S8. `_resolve_shots` runs after the existing `main` checks, so the existing `--seed-image` + `--no-stills` error still wins when all three flags are given.

#### 7.2 Runtime

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-S9 | ltx-movie | `--shots`, story.md pre-existed, S-violations | 2. `Error: story.md breaks the shot rules:` plus one `  - <violation>` line each, plus the hand-edit hint (5.4). No file changes |
| E-S10 | ltx-movie | first draft (this run) violates | `Warning:` plus the list (stdout); the draft moves to `story.rejected-<stamp>-<pid>.md`; one rewrite. If the rewrite also violates: 2, with `Error: story.md still breaks the shot rules after one rewrite:`, the list, and the kept-draft hint |
| E-S11 | ltx-movie | qwen-agent fails during the rewrite (rc 1 path: timeout, or nonzero with no story.md) | 1. The existing qwen-agent error, then `Error: the shots rewrite failed; the rejected first draft is kept at <path>` |
| E-S12 | ltx-movie | a stills group exits nonzero | 1. `Error: ltx-story-images exited <rc> for stills group <k>/<n> (<names or "no character LoRAs">; panels <list>); log: <story>/images/stills-group-<KK>.log. Stills already written are kept; rerun the same command to continue -- every existing panel_NN.png is reused.` Later groups are not run |
| E-S13 | ltx-movie | `--redo` move fails (OSError) | 1. `Error: --redo could not move <src> to <dst>: <e>`. Earlier moves stay in the archive (printed) |
| E-S14 | ltx-movie | W1/W2 advisories | `Warning: <text>` (stdout), continues |
| E-S15 | ltx-story-manifest | `--shots` with `--chain`/`--glob`/`--no-images`; or without `--prompts-md` | 2 (`parser.error`, 5.9 messages) |
| E-S16 | ltx-story-manifest | `--shots`: count mismatch; a panel without Image: or Motion:; a `Prompt:` field | 2, the 5.9 / existing messages. No manifest written |
| E-S17 | ltx-story-manifest | `--cast` without `--chain` or `--shots` | 2, `--cast requires --chain or --shots` |
| E-S18 | ltx-mlx-render | a shots panel fails to render | today's skip policy: the other panels render; one retry pass; exit 1 if incomplete, so ltx-movie returns 1. A rerun resumes |

**Tests (spec 10.1, verbatim)**

- **One new file, `tests/test_shots_mode.py`.**
  - It uses pytest with plain `assert` and **no `check()` helper**. Run it as `python3 -m pytest tests/test_shots_mode.py` from `WS`.
  - It loads scripts with `importlib.machinery.SourceFileLoader`: `bin/ltx-movie` as `ltx_movie_shots`, `bin/ltx-story-manifest` as `ltx_story_manifest_shots`, `bin/ltx-story-images` as `ltx_story_images_shots`, `bin/ltx-mlx-render` as `ltx_mlx_render_shots`.
  - No network, GPU, VLM, Z-Image or LTX.
- **`lib_dir` fixture** sets `CHARACTER_LIBRARY_DIR` to `tmp_path / "lib"`. It is a fresh copy of `tests/test_casting_pipeline.py:47-51`.
- **`make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True, strength=None)`** is a fresh copy of `test_casting_pipeline.py:54-92`, with a `descriptor` parameter added. The fixtures are:
  - kyra: `("kyra", "kyrawmn", "the woman in grey", "woman", DESC_K)`;
  - ronin: `("ronin", "roninmn", "the ronin", "man", DESC_R)`;
  - monk (S15 only): `("monk", "monkmn", "the monk", "man", DESC_M)`.
- **Descriptors:**
  - `DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"`;
  - `DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"`;
  - `DESC_M = "an old bald man with a white beard wearing a saffron robe and wooden prayer beads"`.
- **Members** are always obtained with `character_lib.resolve_cast([(None, "kyra"), (None, "ronin")])`.
- **Fake qwen-agent:** `monkeypatch.setattr(ltx_movie.subprocess, "Popen", fake)`.
  - `fake(cmd, **kw)` records `list(cmd)`, plus `os.path.exists(story_md)` at call time.
  - It writes the next queued story text to `story_md` (an empty queue entry `None` writes nothing).
  - It returns an object with `returncode` (queued, default 0) and `communicate(timeout=None) -> ("", None)`.
  - `ltx_movie.WS` is monkeypatched to `tmp_path`, as in `tests/test_ltx_movie_iterate_flags.py:44-57`.
- **Fake stills runner:** `monkeypatch.setattr(ltx_movie, "_stream_and_tee", fake)`. It records `(list(cmd), log_path)`, creates a 1x1 PNG for each `--only` panel when the queued rc is 0, and returns the queued rc.
- **Fake Z-Image modules** for bin/ltx-story-images are a fresh copy of the P30 harness (`test_casting_pipeline.py`): fake `torch`, `z_image_skill` and `content_safety` in `sys.modules`; the fake `generate_image` records its kwargs, and `torch.Generator("cpu").manual_seed(n)` records `n`.

Plan rules on top of 10.1:
- Exactly one test function per spec test ID (S1-S20, S30-S53, S60-S66, S70-S72: 54 functions), named `test_s<N>_<description>`; multi-case IDs loop inside one function. Every ID lives in the task that introduces its code; S66 (no code) is Task 5.
- The helpers are fresh copies inside `tests/test_shots_mode.py`; there is no `conftest.py`.
- `ltx_movie.WS` is patched through the `movie_ws` fixture (Decision 2), `bin/ltx-story-manifest`'s `WS` through `_shots_manifest_env` (the P20 pattern, with `character_lib.py` symlinked in).
- Test-run output: pytest prints a `pytest_asyncio` `PytestDeprecationWarning` at startup and `DeprecationWarning`s for `SourceFileLoader.load_module()`. The warning count varies by file and run. Neither is a failure. Gate on the `N passed` / `N failed` counts and on pytest's return code (printed as `rc=`), never on `$?` after a pipe to `tail`.

**Regression baselines (spec 0.2, verbatim; re-measured on a clean export of `c7309e1` at planning time, identical)**

| Suite | Invocation | Result |
|---|---|---|
| `tests/test_ltx_movie_offline.py` | `python3 tests/test_ltx_movie_offline.py` (direct; **never pytest**, which false-greens it) | `OK 344/344` |
| `tests/test_ltx_story_images.py` | direct | `OK 101/101` |
| `tests/test_ltx_mlx_render.py` | direct | `OK 443/443` |
| `tests/test_ltx2_mlx_video_skill.py` | direct | `OK 146/146` |
| `tests/test_ltx_story_manifest_chain.py` | direct | `OK 32/32` |
| `tests/test_ltx_image_fit.py` | direct | `OK 77/77` |
| `tests/check_ltx2_mlx_no_forbidden_imports.py` | direct | `RESULT: ok` |
| `tests/test_casting_pipeline.py`, `test_casting_regression.py`, `test_character_lib.py`, `test_character_dataset.py`, `test_character_tool.py`, `test_z_image_skill_multi_lora.py` | `python3 -m pytest` (together) | `178 passed` (63 + 3 + 46 + 41 + 18 + 7) |
| `tests/test_z_image_skill_cache.py` | `python3 -m pytest` | `13 passed` |
| `tests/test_ltx_movie_iterate_flags.py` | `python3 -m pytest` | `13 passed` (it drives `phase1_story` through a fake Popen) |
| `tests/test_pipeline_log.py` | `python3 -m pytest` | `17 passed` |
| `tests/test_deploy_pkg.py` | `python3 -m pytest` (3.13) | `165 passed` |
| `tests/test_deploy_pkg.py` | `/usr/bin/python3 -m unittest tests.test_deploy_pkg` (3.9.6) | `Ran 165 tests … OK` |

**Mutation runner rules (Final Acceptance A3)**
- Each mutation is applied alone and judged by return code only: `python3 -m pytest -q --color=no -p no:cacheprovider <node id>` returns 1 = CAUGHT, 0 = survived, anything else (2 collection error, 4 usage error, 5 no tests) = broken. A direct-run target (`R1:<file>`, run as `python3 <file>`) returns non-zero = CAUGHT.
- Before mutating, the runner asserts each anchor's exact occurrence count and that each target passes unmutated (control). It restores every file in `finally`.
- Every run gets a fresh `PYTHONPYCACHEPREFIX` and `TMPDIR`: a same-size mutation written in the same second as an earlier compile could otherwise load a stale `.pyc` and falsely survive.

## Decisions this plan makes where the spec is silent or inexact

These were decided while writing the plan and verified in the replay. Do not re-decide them; the coordinator may overrule any of them, in which case the named tasks change.

1. **Blocks are applied, never retyped.** Every file block carries `plan=<id> op=<create|append|replace|with> path=<path>` on its opening fence, and implementers apply it with `/tmp/shotsplan-tools/apply_plan.py` (Global Constraints). The previous execution lost U+2019 and U+2014 characters by retyping; this plan's blocks contain both U+2014 (every `## Panel N —` header) and the curly quotes U+201C/U+201D (`_ROSTER_ENTRY_RE`, S5). The applier refuses an anchor that does not occur exactly once and writes nothing on any failure.
2. **`ltx_movie.WS` is patched to `tmp_path/ws`, not to `tmp_path` itself, and `tmp_path/ws/bin` and `tmp_path/ws/character_lib.py` are symlinks to the real files** (fixture `movie_ws`, Task 6). Spec 10.1 says "`ltx_movie.WS` is monkeypatched to `tmp_path`", but `bin/ltx-movie` loads `character_lib.py`, `bin/ltx-story-manifest` (the story.md parser) and, with this feature, `bin/ltx-story-images` by `os.path.join(WS, ...)`. A literal patch would make every one of those loads fail. The symlinks keep the loaders on the real files while every story dir lands under `tmp_path/ws/generated/stories`; the loaded tools compute their own `WS` from `realpath(__file__)`, so they still see the real workspace. The library stays at `tmp_path/lib` (`lib_dir`).
3. **`character_lib.py`'s "first paragraph"** (spec 3 preamble) is the paragraph that starts `Stdlib only.` (line 1 is the docstring's one-line summary). The sentence is appended after `an uncast run never reads this file.`, wrapped at the file's width.
4. **"Docstring. Append: ..." in spec 5.9 item 9 and 5.10 item 5** is a new paragraph placed directly after each tool's casting paragraph (before `Dependencies:`), word-wrapped at 88 columns with the words unchanged. The `bin/ltx-movie` paragraph (spec 5.1) is placed after the casting paragraph, wrapped at 90 columns (the casting paragraph's width). The `_phase4_flags` docstring sentence (spec 5.7) is appended to the docstring's last sentence. The `bin/ltx-story-images` comment line (spec 5.10 item 4) is the line `    # --shots pins the seed the same way (shots spec 5.10).` directly after the existing comment block, so `grounded = bool(style)` stays a substring (pin I20).
5. **Spec 3.1 is placed as one unit** directly after `SINGLE_CHARACTER_STRENGTH = 1.0`: the six constants, a blank line, the seven private regexes, a blank line, then the existing `TRIGGER_REGISTRY`. `SHOTS_CAST_BLOCK_RULES` and then `SHOTS_REWRITE_TEMPLATE` follow `CAST_BLOCK_RULES` with no blank line between them (as `CAST_BLOCK_HEADER`/`CAST_BLOCK_RULES` sit today); the six functions follow `build_cast_block` in spec order 3.4-3.9, two blank lines apart.
6. **Placement of the new `bin/ltx-movie` functions** (spec 1.3 lists them; 5.x places only some): `_run_story_agent` directly above `phase1_story` (spec); `_shots_check` and `_phase1_shots_finish` directly after `phase1_story`; `_panel_list`, `_shots_stills_groups`, `_shots_missing_stills` and `_phase2_shots` directly after `phase2_stills`; `_redo_moves` and `phase_redo_shots` directly after `phase_release_story_server`; `_shots_image_flags` directly before `phase3_manifest` (after its section banner); `_print_shots_stills_plan` directly before `_print_dry_run_plan` (after its banner); `_resolve_shots` after `_resolve_global_loras` (spec). Pin L17b slices the text from `def phase2_stills(args):` to `def phase3_manifest`; every function placed in that slice was checked to contain no `no_stills`.
7. **Task 7 lands all of spec 5.4 (a)**, including `authored = None` and `authored = {...}`, although `authored` is first read in Task 8. The refactor checkpoint is therefore exactly the spec's text.
8. **S61's "Every `panel_text` is byte-identical to S60's"** is read as "byte-identical to an uncast `--shots` run of the same 4-panel story": S60 runs `SHOTS_OK` (3 panels), so a literal comparison is impossible. This mirrors P20's "byte-identical to an uncast run".
9. **Guards that pass before their implementation step:** S20 (Task 2: the import set is unchanged), S66 (Task 5: no code), S41 (Task 8: continuous mode), S52 and S53 (Task 10: non-shots identity and the uncast loading rule). Each task's red count accounts for them.
10. **Test strengthenings inside the rows' stated intent** (each was needed for a spec mutation row to have the catcher the spec names, or is a byte-level form of the row's own wording):
    - S32 also compares `build_story_prompt(...)` with `STORY_PROMPT_TEMPLATE.format(...)`. Comparing `shots=False` with the call without `shots` alone cannot catch "shots template used without `--shots`" (both sides change).
    - S34 also checks that the cast block ends with `SHOTS_CAST_BLOCK_RULES`, for the same reason with "`build_cast_block` ignores `shots`".
    - S11 asserts the exact three-item list; S13-S16 assert exact lists; S36 checks the `story.rejected-<UTC %Y%m%dT%H%M%SZ>-<pid>.md` name; S49 checks the `<stamp>-<pid>` archive name; S33 checks that the two OK cases print nothing.
    - S61 compares the trigger substrings case-insensitively: the story's sentences start with a capital (`The kyrawmn woman in grey ...`), and the spec row quotes the lower-case phrase.
11. **Fixture texts the spec leaves open** are in the test blocks: `S61_STORY` (4 panels), `GROUP_STORY` (5 panels, Image: casts {kyra}, {ronin}, {kyra, ronin}, {}, {kyra}; panel 4's Motion: names the ronin, the "Motion:-only mentions" case), `CHAINED_STORY` (S41), the third character `mira` with phrase `the woman` and no stills LoRA (S42 nested case), `TEN_WORDS`/`TWENTY_FIVE_WORDS`. The S7 chain-word sentences are 14 words plus the chain word (15 for one-word words, 16 for `followed  by`, 17 for `as soon as`); the spec's "otherwise valid 15-word sentence" cannot hold for the multi-word phrases. The S5 header-after-panels case changes the summary line to `Three characters meet on a forest trail.` so that the "first line containing Characters" mutation has a line to latch onto.
12. **S66 runs the render with `--width 512 --height 512`**, so the 64x64 PNG stills (spec 10.5) pass the render's schema-3 still-aspect preflight, which uses the real `ffprobe`. `--retry-failed 0` keeps the 120 s retry idle out of the test.
13. **S45 records the group commands with a stills runner that writes no PNGs.** Otherwise bin/ltx-story-images would skip every existing still and `generate_image` would never run.
14. **S50 sets `STORY_PIPELINE_LOGGED=1`** in the subprocess environment, exactly as B1 does, so `pipeline_log` can never create the fresh story dir the test asserts is absent. S53 keeps the spec's story id `x`.
15. **The Phase 2 tests forbid real subprocesses.** `_StillsRunner` makes `ltx_movie.subprocess.run` and `Popen` raise. Before Task 9's implementation, `phase2_stills` with `--shots` falls through to the continuous path and would launch the real bin/ltx-story-images, which loads Z-Image (observed in the scratch build: a 69 s red run). With the guard, the red run fails fast and offline.
16. **S52 also compares B1, B2 and B3** through `tests/test_casting_regression.py`'s own `b1_text`/`b2_text`/`b3_text` (the P70 pattern), so the shots suite itself proves SC9's goldens.
17. **Mutation definitions the spec leaves open** (A3 lists the exact edits):
    - "S4 bounds `<` instead of `<=` (either end)" is two rows, one per end; that makes 63 rows for the spec's 62.
    - "advisories appended to violations" is applied in `character_lib.shots_violations` (`return out + shots_advisories(panels, members)`).
    - "a second rewrite is allowed" moves the second draft aside and calls `_run_story_agent` once more when the rewrite still violates; S37's fake agent has no third story, so the extra call raises.
    - "rewrite rebuilds `cmd`" builds a 6-element command that contains the literal `"--workspace", WS,`, so R1:L19a also catches it.
    - "redo phase inserted when `redo_panels == []`" is the condition `is not None`; "`--redo` accepted without `--shots`" disables only the E-S3 test; "dry-run `--redo` moves files" replaces the `Would move` print with `os.makedirs` + `os.replace`.
    - "roster parse starts at the first line containing 'Characters' anywhere" is `"characters" in line.lower()`.
    - "shots Phase 2 builds its own `--lora` line" adds a dead `["--lora", args.stills_lora_path]` literal to `_phase2_shots`, which pin L1z5 counts.
    - "`_run_story_agent` drops the `--danger-auto-approve` print" targets `tests/test_ltx_movie_iterate_flags.py::test_danger_auto_approve_trace_reaches_stdout_on_success` (the C1 test).
    - "shots template used without `--shots`" names B1 as `tests/test_casting_regression.py::test_b1_ltx_movie_dry_run_is_unchanged`.
18. **Spec mutation rows whose named catcher does not catch** (observed in the replay; each row still has at least one catcher, which is the spec's rule): "S2 enforced without members" and "advisories appended to violations" (S9 passes; S11 and S40 catch), "shots branch placed after `_validate_story_md`" (S36 passes; S35 catches), "groups insert triggers for members without stills" (S45 passes, since every S45 member has a stills LoRA; S42 catches), "manifest shots writes schema 2" (S66 passes, since the render derives `still` for a schema-2 panel with an image; S60 catches), "redo phase inserted when `redo_panels == []`" (R1:L41 passes, since its objects have no `redo_panels`; S48 catches), "camera sentence counted as an action sentence" (the row's "S43's fixture via S9" is read as S9; S6 and S9 catch).
19. **The existing `--cast` help text of `bin/ltx-story-manifest` still says "--chain only"**, and the existing docstring lines "an uncast run never reads this file" (`character_lib.py`) and "character_lib.py is loaded by path only when casting is used, so an uncast run never reads it" (`bin/ltx-movie`) stay as they are: the spec changes none of them (it only appends text), although `--shots` now loads `character_lib.py` uncast (spec 8). Reported, not fixed (the "don't fix unrelated text" rule).
20. **Every task's regression block runs every spec 0.2 suite** (not a subset), because each task's edit can break a pin in a suite it does not touch (for example Task 9 against L1z5/L17b, Task 4 against I20).

## Review Focus

Spec Section 13, verbatim:

These are the five failure modes most likely to matter that the offline tests cannot fully cover:

1. **Rewrite flow on the real host.**
   - Confirm that the moved-aside draft makes the rewrite's `write_file` a NEW file (no approval prompt under `--no-review`).
   - Confirm that the reused `cmd` carries `--danger-auto-approve` only when it did before.
   - Confirm that a qwen-agent nonzero exit after writing still validates the file.
   - A wrong call here hangs an unattended run or loses the first draft.
2. **Group equality with bin/ltx-story-images' own plan.** `_shots_stills_groups` must compute exactly the names that bin/ltx-story-images' `cast_text(_compose_prompt(Image:, Style:), members, insert=stills members)` computes, including nested phrases and members without stills. Otherwise E-P16 fires mid-Phase 2, after paid stills. S45 runs them together, but only on fixtures.
3. **`--redo` and provenance.**
   - Moving, not deleting.
   - Only the named panels.
   - `movie.mp4` moved, so Phase 4 needs no `--force`.
   - Every other clip reused, because its provenance (image bytes, prompt, seed, LoRAs) is unchanged.
   - Confirm nothing else in Phase 3 changes the other panels' render prompts. For example, a trigger inserted differently would change `prompt_sha256` and cascade re-renders.
4. **Byte identity without `--shots`.** Every edit is guarded by `shots` or `redo_panels`. Review each changed line of the four files against the pins in 0.2 and against B1-B3, especially the `_run_story_agent` move (`len(cmd[-1])`) and the manifest's E-P14 wording.
5. **Heuristic strictness against the story model.** The 10-25-word band is far below what the model wrote in the rescue (45-71). Review whether the rewrite text (3.9) gives the model enough guidance to comply in one pass. If L-S1 shows routine double failures, the follow-up is a prompt change, not a looser validator. That is a user decision.

Plan-specific additions:
6. **The test fixture's `WS` (Decision 2).** Confirm that no ltx-movie test can write under the real `generated/` (every story dir comes from `movie_ws` or is asserted absent, as in S50), and that the symlinked `bin/` cannot hide a path bug that only shows when `WS` really is the workspace (S50 and S53 run the real script in the real workspace).
7. **The source-text pins (spec 0.2).** L1z5, L7i, L7j, L17b, L19a-c, L12 and `_render_flags(args)` x4 in `tests/test_ltx_movie_offline.py`; I13, I20 and I21 in `tests/test_ltx_story_images.py`; P22/P23 in `tests/test_casting_pipeline.py`. Confirm every count still holds and that no new comment or docstring reintroduces a pinned literal (Decisions 4 and 6).
8. **Group equality in practice.** `_shots_stills_groups` uses `cast_text(..., insert=<members with a stills LoRA>)`, exactly as bin/ltx-story-images does (Review Focus 2); confirm it also matches when a global `--stills-lora` is given (globals are identical for every panel, so a group stays one LoRA set) and when `--seed-image` is refused (E-S2 makes the seed-image panel-1 exception unreachable in shots mode).

## Task map

| Task | Owner | Adds | New tests | Cumulative new tests | Files |
|---|---|---|---|---|---|
| 1 | orchestrator or implementer (offline) | R1/R2 baseline on the untouched tree | none | 0 | none |
| 2 | implementer | `character_lib.py` shots additions (spec 3) | S1-S20 (20) | 20 | `character_lib.py` (741 lines), `tests/test_shots_mode.py` (462 lines) |
| 3 | implementer | `bin/ltx-story-manifest --shots` (5.9) | S60-S65 (6) | 26 | `bin/ltx-story-manifest` (684 lines), `tests/test_shots_mode.py` (649 lines) |
| 4 | implementer | `bin/ltx-story-images --shots` (5.10) | S70-S72 (3) | 29 | `bin/ltx-story-images` (475 lines), `tests/test_shots_mode.py` (734 lines) |
| 5 | implementer | render: no code | S66 (1) | 30 | `tests/test_shots_mode.py` (818 lines) |
| 6 | implementer | ltx-movie: `--shots`/`--redo`, `_resolve_shots`, template, `build_story_prompt`, `_resolve_casting` (5.1-5.3) | S30-S34 (5) | 35 | `bin/ltx-movie` (1558 lines), `tests/test_shots_mode.py` (962 lines) |
| 7 | implementer | ltx-movie: `_run_story_agent` extraction (5.4 a; refactor checkpoint) | none | 35 | `bin/ltx-movie` (1571 lines) |
| 8 | implementer | ltx-movie: `_shots_check`, `_phase1_shots_finish` (5.4 b) | S35-S41 (7) | 42 | `bin/ltx-movie` (1648 lines), `tests/test_shots_mode.py` (1118 lines) |
| 9 | implementer | ltx-movie: stills groups, `_phase2_shots` (5.5) | S42-S45 (4) | 46 | `bin/ltx-movie` (1715 lines), `tests/test_shots_mode.py` (1291 lines) |
| 10 | implementer | ltx-movie: `--redo`, Phase 3/4 flags, dry run (5.6-5.8) | S46-S53 (8) | 54 | `bin/ltx-movie` (1807 lines), `tests/test_shots_mode.py` (1521 lines) |
| FA | orchestrator | A1-A6: suite counts and ID coverage, B-goldens, 63 mutations, R1/R2, scope, design review; live gates L-S1, L-S2 | - | 54 | none |

Order and dependencies (spec Section 11): Task 1 first. Tasks 2-5 follow in the order 2, 3, 4, 5 (3, 4 and 5 consume Task 2's `character_lib` names and test fixtures; 5 consumes Task 3's manifest helpers). Tasks 6-10 depend on Task 2 and run in order (7 must be committed alone before 8 starts). Execute every task sequentially, one at a time: each appends to `tests/test_shots_mode.py`, and each task's red and green counts assume this order.

---

### Task 1: Baseline -- R1 and R2 on the untouched tree (no code, no commit)

Spec Section 11 item 1: "**Baseline.** Rerun R1 (and record it), with no code changes." Run it from `WS` and paste the output into the task log. A deviation from the expected lines stops the plan: report it to the user before Task 2.

Precondition: `git diff --quiet HEAD -- character_lib.py bin/ltx-movie bin/ltx-story-manifest bin/ltx-story-images bin/ltx-mlx-render tests/ && test ! -e tests/test_shots_mode.py && echo clean` prints `clean`.

- [ ] **Step 1: Bootstrap the block applier** (Global Constraints) and check it: the last line is `apply_plan: self-check ok (99 blocks, ids unique)`.

- [ ] **Step 2: Run the R1 suites** (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 3: Run the R2 suites:**

````bash
python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r2.log 2>&1; echo "deploy rc=$? $(tail -1 /tmp/shotsplan-r2.log)"
/usr/bin/python3 -m unittest tests.test_deploy_pkg > /tmp/shotsplan-r2u.log 2>&1; echo "unittest rc=$?"; tail -3 /tmp/shotsplan-r2u.log
````

Expected: `deploy rc=0 165 passed in <t>s`; then `unittest rc=0`, `Ran 165 tests in <t>s`, a blank line, `OK`.

---

### Task 2: `character_lib.py` -- shots strength, shots Cast block, roster parser, shot rules, advisories, rewrite block

**Files:**
- Modify: `character_lib.py` (4 edits below)
- Test: create `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: nothing new (stdlib only; `character_lib`'s existing `normalize_phrase`, `_phrase_regex`, `phrase_occurs`, `cast_text`, `CharacterError`, `CAST_BLOCK_HEADER`, `CAST_BLOCK_RULES`, `SINGLE_CHARACTER_STRENGTH`).
- Produces (spec 1.3, 3), used by Tasks 3, 4, 6, 8, 9 and 10:
  - constants `SHOTS_CHARACTER_STRENGTH = 0.8`, `SHOTS_MOTION_MIN_WORDS = 10`, `SHOTS_MOTION_MAX_WORDS = 25`, `SHOTS_MAX_CAST_PER_PANEL = 2`, `SHOTS_REWRITE_MAX_LISTED = 40`, `SHOTS_CLOSE_SHOT_TYPES`, `SHOTS_CAST_BLOCK_RULES`, `SHOTS_REWRITE_TEMPLATE`; private regexes `_ROSTER_HEADER_RE`, `_ROSTER_ENTRY_RE`, `_SENTENCE_SPLIT_RE`, `_CAMERA_SENTENCE_RE`, `_CHAIN_WORD_RE`, `_COMMA_AND_RE`, `_SHOT_TYPE_RE`;
  - `panel_strengths(names, members, character_strength, shots=False) -> dict`, `build_cast_block(members, shots=False) -> str`;
  - `find_phrases(text, phrases) -> [phrase]`, `parse_character_roster(text) -> ([(phrase, description)], [problem])`, `motion_problems(motion) -> [(rule, detail)]`, `shots_violations(text, panels, expected_panels, members) -> [str]`, `shots_advisories(panels, members) -> [str]`, `shots_rewrite_block(violations, panels) -> str`.
- The test file produces the shared fixtures every later task reuses: `DESC_K`, `DESC_R`, `DESC_M`, `lib_dir`, `make_character`, `_kyra`, `_ronin`, `_monk`, `_members`, `SHOTS_OK`, `ROSTER_BLOCK`, `_variant`, `_panels`.

Spec 3 preamble, verbatim:

`panel_strengths` and `build_cast_block` are replaced in place by the 3.2 and 3.3 versions. `SHOTS_CAST_BLOCK_RULES` goes directly after `CAST_BLOCK_RULES`, and `SHOTS_REWRITE_TEMPLATE` directly after it. The other 3.1 constants go after `SINGLE_CHARACTER_STRENGTH`. The new functions go after `build_cast_block` and before `usable_characters`, in the order 3.4-3.9. The module docstring's first paragraph gains this sentence at its end: `It also owns the shots-mode story rules (shot-rule validation, advisories and the rewrite block; docs/superpowers/specs/2026-10-06-shots-mode-design.md).` No import is added (C41 still passes).

Spec 10.3 test table (S1-S20), verbatim:

| ID | Test | Assertion |
|---|---|---|
| S1 | constants | `SHOTS_CHARACTER_STRENGTH == 0.8`, `SHOTS_MOTION_MIN_WORDS == 10`, `SHOTS_MOTION_MAX_WORDS == 25`, `SHOTS_MAX_CAST_PER_PANEL == 2`, `SHOTS_REWRITE_MAX_LISTED == 40`, `SHOTS_CLOSE_SHOT_TYPES == ("medium shot", "medium close-up", "close-up", "extreme close-up")` |
| S2 | `panel_strengths` with members kyra (strength None) and ronin (strength 0.6) | `(["kyra"], m, 0.8, shots=True) == {"kyra": 0.8}`; `(["kyra"], m, 0.7, shots=True) == {"kyra": 0.7}`; `(["ronin"], m, 0.8, shots=True) == {"ronin": 0.6}`; `(["kyra", "ronin"], m, 0.8, shots=True) == {"kyra": 0.8, "ronin": 0.6}`; `(["kyra"], m, 0.8) == {"kyra": 1.0}` (continuous unchanged); `([], m, 0.8, shots=True) == {}` |
| S3 | `build_cast_block([kyra, ronin], shots=True)` | `== CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n" + '- "the ronin": ' + DESC_R + "." + "\n" + SHOTS_CAST_BLOCK_RULES`. `build_cast_block(m)` and `build_cast_block(m, shots=False)` both equal the C39 form (`CAST_BLOCK_RULES`). `SHOTS_CAST_BLOCK_RULES` has no `{`, `}` or `%`, `.count("word for word") == 2`, and contains `"at most two of these characters"`, `"a medium shot or closer"`, `"never within arm's reach"`, `"show it by cutting"`, `"an offered hand or a hand on an arm"`, `"has none of these extra rules"` |
| S4 | `find_phrases` | `("The woman in grey nods to the woman.", ["the woman", "the woman in grey"]) == ["the woman in grey", "the woman"]`; `("THE RONIN bows.", ["the ronin"]) == ["the ronin"]`; `("the ronin's blade", ["the ronin"]) == ["the ronin"]`; `("the ronin-like man", ["the ronin"]) == []`; `("the bearded robber grabs the ronin; the ronin", ["the ronin", "the bearded robber"]) == ["the bearded robber", "the ronin"]` (first-occurrence order, once each); `("", ["the ronin"]) == []` |
| S5 | `parse_character_roster` | on `SHOTS_OK`: three entries in order, with problems `[]`. Curly quotes `- “the ronin”: a man` and a `* "the ronin": a man` bullet each parse. No header gives `([], ['no "## Characters" section'])`. A line `- the ronin: a man` gives problem `'line \'- the ronin: a man\' is not - "<referring phrase>": <description>'`. A 7-word phrase gives the `normalize_phrase` message. `"The Ronin"` after `"the ronin"` gives `"phrase 'The Ronin' is listed more than once"`. Blank lines inside the section are skipped. The section ends at `## Panel 1` (a later `- "x y": z` line after the panels is not read). A header with no entries gives `['the "## Characters" section lists no characters']`. A header placed after the panels is found |
| S6 | `motion_problems` pass cases | `[]` for: each `SHOTS_OK` Motion:; `"The ronin draws his katana from its scabbard in one smooth motion. The camera stays static."`; `"The woman in grey swings the cedar branch at the robber's knife hand."` (no camera sentence); a text of exactly 10 words; a text of exactly 25 words; `"Camera holds. The ronin kneels beside the fallen branch on the trail."` (camera sentence first) |
| S7 | `motion_problems` fail cases (one each, exact list; every case text is otherwise clean: one sentence, no chain word, unless the case is about that) | 9 words → `[("S4 motion length", "Motion: is 9 words; it must be 10-25")]`. 26 words → the same with 26. `"The ronin draws his sword. The ronin strikes the bearded robber hard."` → `[("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally followed by a camera sentence")]`. `"The ronin draws his sword; he strikes the bearded robber across the arm."` → `[("S5 one action", "Motion: contains a semicolon")]`. Each of `then`, `While`, `meanwhile`, `simultaneously`, `afterwards`, `followed  by` (two spaces), `as soon as`, placed in an otherwise valid 15-word sentence → `[("S5 one action", "Motion: chains actions with '<word lowercased, single-spaced>'")]`. `"The ronin sprints in, and he draws his katana toward the robber."` → `[("S5 one action", "Motion: chains actions with ', and'")]`. `"The camera pans slowly across the empty clearing toward the cedar trees."` → `[("S5 one action", "Motion: has 0 action sentences; …")]` |
| S8 | negative controls | `[]` for: `"The ronin crosses the strengthened rope bridge above the river gorge slowly."` (`then` inside a word); `"The woman in grey kneels before the shrine and lowers her head."` (bare `and`, `before`: the known G1 false negative, pinned so that a future tightening is a deliberate change) |
| S9 | `shots_violations(SHOTS_OK, panels, 3, [kyra, ronin])` | `[]`. `shots_violations(SHOTS_OK, panels, 3, [])` is also `[]` |
| S10 | S1 | `expected_panels=4` → first item `"story: S1 panel count: expected exactly 4 panels, found 3"` |
| S11 | S2 roster presence | `SHOTS_OK` with the `## Characters` section removed: with members → contains `'story: S2 characters list: no "## Characters" section'` and two `cast phrase … is not listed` items; with `[]` members → `[]` |
| S12 | S2 cast phrase missing | roster without the `"the ronin"` line → exactly `["story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]` |
| S13 | S3 | panel 2's `Image: …` line removed → `["panel 2: S3 fields: missing/empty Image: field"]`. Panel 3 gains `Prompt: x` → `"panel 3: S3 fields: has a Prompt: field; shots mode expects Image:, Motion: and Narration:"` |
| S14 | S4/S5 numbering | panel 3's Motion: replaced with `"The ronin offers his hand then pulls the woman in grey to her feet on the trail."` → `["panel 3: S5 one action: Motion: chains actions with 'then'"]` |
| S15 | S6 | members kyra, ronin, monk; the roster gains `- "the monk": ` + `DESC_M` (directly before the bearded-robber line, so S2 stays silent); panel 3's Image: gains `" The monk, an old bald man with a white beard wearing a saffron robe and wooden prayer beads, stands behind them."` → `["panel 3: S6 cast count: the shot names 3 cast characters (kyra, monk, ronin); at most 2"]`. The same with the monk named only in Motion: (Motion: `"The monk raises his hand toward the ronin and the woman in grey."`) also gives S6, which proves the Image: ∪ Motion: union. `SHOTS_OK` (2 cast) gives no S6 |
| S16 | S7 | panel 1's Motion: replaced with `"The woman in grey pushes the bearded robber away from her with both hands."` → `["panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded robber'; show the other character's action in its own shot, then cut to the cast character's reaction"]`. Panel 1 as in `SHOTS_OK` (robber in Image: only) gives no S7. Panel 2 (extra only) gives no S7. Panel 3 (two cast) gives no S7 |
| S17 | S7 overlap | the roster gains `- "the woman": an old woman in a straw hat`, and panel 1's Motion: is `"The woman in grey bows her head to the trail shrine slowly. The camera stays static."` → no S7 (the longest phrase claims the span) |
| S18 | `shots_advisories` | on `SHOTS_OK` → `[]`. Panel 1's descriptor paraphrased by replacing the unique string `"grey kimono, standing in the centre"` with `"grey robe, standing in the centre"` (verified unique; a first-occurrence replace of the descriptor itself would hit the roster line instead) → exactly `["panel 1: Image: names 'the woman in grey' but does not repeat character kyra's Cast description word for word; that still relies on the phrase and the stills LoRA alone"]`. Panel 1's `"hairpins wearing a grey kimono, standing in the centre"` → `"hairpins   WEARING a grey kimono, standing in the centre"` (whitespace and case) → no W1. Panel 1's `"A medium shot"` → `"A wide shot"` → `["panel 1: shows cast character(s) kyra but its Image: shot type is wide shot; a shot with a cast character should be a medium shot or closer"]`. Shot type removed → `"… shot type is not stated; …"`. Panel 2 (no cast) with `"wide shot"` → no W2. Empty members → `[]` |
| S19 | `shots_rewrite_block` | `(["a", "b", "c"], 14) == SHOTS_REWRITE_TEMPLATE % ("- a\n- b\n- c", 14)`, contains `"Keep EXACTLY 14 panel sections."`. 45 violations → 40 `"- v<i>"` lines then `"- ... and 5 more"`. `SHOTS_REWRITE_TEMPLATE.count("%") == 2` |
| S20 | `character_lib.py` ast | top-level imports still exactly `{collections, datetime, json, os, re, uuid}` (C41 unchanged) |

Precondition: `git diff --quiet HEAD -- character_lib.py && test ! -e tests/test_shots_mode.py && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T2.S1` creates `tests/test_shots_mode.py` with exactly this content:

````python plan=T2.S1.1 op=create path=tests/test_shots_mode.py
"""Tests for shots mode (spec docs/superpowers/specs/2026-10-06-shots-mode-design.md
Section 10, S1-S72).

Run from the workspace root: python3 -m pytest tests/test_shots_mode.py
Plain pytest asserts only (no check() helper). No network, GPU, VLM, Z-Image or LTX: the
story model is a fake subprocess.Popen, the stills runner a fake _stream_and_tee, Z-Image
runs against fake torch/z_image_skill/content_safety modules, the render goes through a
stubbed generate_video, and every character library lives under tmp_path through
$CHARACTER_LIBRARY_DIR.
"""

import ast
import contextlib
import glob
import hashlib
import importlib.machinery
import io
import json
import os
import re
import string
import subprocess
import sys
import types

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)

import character_lib  # noqa: E402
import ltx2_mlx_video_skill as SKILL  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


ltx_movie = _load("ltx_movie_shots", "bin/ltx-movie")
story_manifest = _load("ltx_story_manifest_shots", "bin/ltx-story-manifest")
story_images = _load("ltx_story_images_shots", "bin/ltx-story-images")
render = _load("ltx_mlx_render_shots", "bin/ltx-mlx-render")

# The character_lib exception classes are looked up on the module at call time, never bound
# with "from character_lib import ...": the pipeline tools load character_lib.py by path into
# the same sys.modules entry, which re-creates its classes.

# --- shared fixtures (spec 10.1, 10.2) -------------------------------------------------
DESC_K = "a young woman with long black hair pinned up with jade hairpins wearing a grey kimono"
DESC_R = "a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori"
DESC_M = "an old bald man with a white beard wearing a saffron robe and wooden prayer beads"
VIDEO_BYTES = b"fake-video-lora!"
STILLS_BYTES = b"fake-stills-lora"


@pytest.fixture
def lib_dir(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("CHARACTER_LIBRARY_DIR", str(lib))
    return str(lib)


def make_character(lib, name, trigger, phrase, class_noun, descriptor, stills=True, strength=None):
    """Write a valid trained character.json (casting spec 2.2 shape) under lib/name and return
    the dict: a 16-byte lora/video.safetensors, plus a 16-byte lora/stills.safetensors when
    stills is true; each entry carries the real sha256."""
    cdir = os.path.join(lib, name)
    os.makedirs(os.path.join(cdir, "lora"), exist_ok=True)
    dataset = {"reference": "char_00", "kept": 24, "total": 25, "min_score": 7,
               "face_height": 0.38,
               "contact_sheet": os.path.join(cdir, "dataset", "contact_sheet.jpg")}
    video_path = os.path.join(cdir, "lora", "video.safetensors")
    with open(video_path, "wb") as f:
        f.write(VIDEO_BYTES)
    video = {"path": video_path, "sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
             "base_model": "/models/ltx-2.3-mlx-q8-dev", "rank": 32, "alpha": 32,
             "steps": 1000, "trained_at": "2026-10-06T02:00:00Z",
             "sample_path": None, "control_path": None}
    stills_entry = None
    if stills:
        stills_path = os.path.join(cdir, "lora", "stills.safetensors")
        with open(stills_path, "wb") as f:
            f.write(STILLS_BYTES)
        stills_entry = {"path": stills_path,
                        "sha256": hashlib.sha256(STILLS_BYTES).hexdigest(),
                        "base_model": "Tongyi-MAI/Z-Image-Turbo", "rank": 16, "alpha": 16,
                        "steps": 2400, "trained_at": "2026-10-06T03:00:00Z",
                        "sample_path": None, "control_path": None}
    data = {"schema_version": 1, "name": name, "trigger": trigger, "class_noun": class_noun,
            "referring_phrase": phrase, "descriptor": descriptor, "seed": 0,
            "source": {"type": "seed_image", "path": "/fixtures/seed.png"},
            "strength": strength, "status": "trained", "created_at": "2026-10-06T01:02:03Z",
            "dataset": dataset, "loras": {"video": video, "stills": stills_entry},
            "stills_skip_reason": None}
    with open(os.path.join(cdir, "character.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _kyra(lib, **kw):
    return make_character(lib, "kyra", "kyrawmn", "the woman in grey", "woman", DESC_K, **kw)


def _ronin(lib, **kw):
    return make_character(lib, "ronin", "roninmn", "the ronin", "man", DESC_R, **kw)


def _monk(lib, **kw):
    return make_character(lib, "monk", "monkmn", "the monk", "man", DESC_M, **kw)


def _members(*names):
    return character_lib.resolve_cast([(None, n) for n in names])


SHOTS_OK = """# Forest Rescue

A ronin saves a woman from a robber on a forest trail.

## Characters
- "the woman in grey": a young woman with long black hair pinned up with jade hairpins wearing a grey kimono
- "the ronin": a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori
- "the bearded robber": a stocky man with a black beard in a ragged brown jacket

## Panel 1 — The Trail
Image: A medium shot of the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing in the centre of a mossy cedar trail and facing right. Far behind her on the left, small in the frame, the bearded robber watches from the ferns. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The woman in grey turns her head slowly toward the ferns on her right. The camera stays static.
Narration: She senses she is not alone.

## Panel 2 — The Robber
Image: A medium close-up of the bearded robber, a stocky man with a black beard in a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing left. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The bearded robber lunges forward out of the ferns with his short knife raised. The camera stays static.
Narration: A robber springs from cover.

## Panel 3 — The Ronin
Image: A medium shot of the ronin, a lean man in his late thirties with a topknot and a scarred brow wearing an indigo haori, and the woman in grey, a young woman with long black hair pinned up with jade hairpins wearing a grey kimono, standing an arm's length apart on the mossy cedar trail, the ronin on the left facing right. Soft overcast light, muted green palette, eye-level camera, photorealistic film still.
Motion: The ronin offers his open hand to the woman in grey. The camera stays static.
Narration: Help arrives.
"""
ROSTER_BLOCK = SHOTS_OK[SHOTS_OK.index("## Characters\n"):SHOTS_OK.index("## Panel 1")]


def _variant(old, new, text=None):
    """SHOTS_OK (or text) with the unique string old replaced by new."""
    text = SHOTS_OK if text is None else text
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _panels(tmp_path, text):
    """bin/ltx-story-manifest _parse_prompts_md panels for text."""
    path = tmp_path / "parse-me.md"
    path.write_text(text, encoding="utf-8")
    return story_manifest._parse_prompts_md(str(path))[1]


# --- S1-S20: character_lib (spec 3, 4) --------------------------------------------------
def test_s1_constants():
    assert character_lib.SHOTS_CHARACTER_STRENGTH == 0.8
    assert character_lib.SHOTS_MOTION_MIN_WORDS == 10
    assert character_lib.SHOTS_MOTION_MAX_WORDS == 25
    assert character_lib.SHOTS_MAX_CAST_PER_PANEL == 2
    assert character_lib.SHOTS_REWRITE_MAX_LISTED == 40
    assert character_lib.SHOTS_CLOSE_SHOT_TYPES == (
        "medium shot", "medium close-up", "close-up", "extreme close-up")


def test_s2_panel_strengths_in_shots_mode(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir, strength=0.6)
    m = _members("kyra", "ronin")
    strengths = character_lib.panel_strengths
    assert strengths(["kyra"], m, 0.8, shots=True) == {"kyra": 0.8}
    assert strengths(["kyra"], m, 0.7, shots=True) == {"kyra": 0.7}
    assert strengths(["ronin"], m, 0.8, shots=True) == {"ronin": 0.6}
    assert strengths(["kyra", "ronin"], m, 0.8, shots=True) == {"kyra": 0.8, "ronin": 0.6}
    assert strengths(["kyra"], m, 0.8) == {"kyra": 1.0}
    assert strengths([], m, 0.8, shots=True) == {}


def test_s3_shots_cast_block(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    m = _members("kyra", "ronin")
    lib = character_lib
    assert lib.build_cast_block(m, shots=True) == (
        lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
        + '- "the ronin": ' + DESC_R + "." + "\n" + lib.SHOTS_CAST_BLOCK_RULES)
    continuous = (lib.CAST_BLOCK_HEADER + "\n" + '- "the woman in grey": ' + DESC_K + "." + "\n"
                  + '- "the ronin": ' + DESC_R + "." + "\n" + lib.CAST_BLOCK_RULES)
    assert lib.build_cast_block(m) == continuous
    assert lib.build_cast_block(m, shots=False) == continuous
    rules = lib.SHOTS_CAST_BLOCK_RULES
    assert "{" not in rules and "}" not in rules and "%" not in rules
    assert rules.count("word for word") == 2
    for fragment in ("at most two of these characters", "a medium shot or closer",
                     "never within arm's reach", "show it by cutting",
                     "an offered hand or a hand on an arm", "has none of these extra rules"):
        assert fragment in rules, fragment


def test_s4_find_phrases():
    find = character_lib.find_phrases
    assert find("The woman in grey nods to the woman.", ["the woman", "the woman in grey"]) == [
        "the woman in grey", "the woman"]
    assert find("THE RONIN bows.", ["the ronin"]) == ["the ronin"]
    assert find("the ronin's blade", ["the ronin"]) == ["the ronin"]
    assert find("the ronin-like man", ["the ronin"]) == []
    assert find("the bearded robber grabs the ronin; the ronin",
                ["the ronin", "the bearded robber"]) == ["the bearded robber", "the ronin"]
    assert find("", ["the ronin"]) == []


def _roster(*lines):
    """A minimal story whose Characters section holds lines, then one panel."""
    return ("# T\n\nA summary.\n\n## Characters\n" + "".join(l + "\n" for l in lines)
            + "\n## Panel 1 — A\nImage: x\n")


def test_s5_parse_character_roster():
    parse = character_lib.parse_character_roster
    entries = [("the woman in grey", DESC_K), ("the ronin", DESC_R),
               ("the bearded robber", "a stocky man with a black beard in a ragged brown jacket")]
    assert parse(SHOTS_OK) == (entries, [])
    assert parse(_roster("- “the ronin”: a man")) == ([("the ronin", "a man")], [])
    assert parse(_roster('* "the ronin": a man')) == ([("the ronin", "a man")], [])
    assert parse("# T\n\nA summary.\n\n## Panel 1 — A\nImage: x\n") == (
        [], ['no "## Characters" section'])
    assert parse(_roster('- "the monk": a man', "- the ronin: a man")) == (
        [("the monk", "a man")],
        ['line \'- the ronin: a man\' is not - "<referring phrase>": <description>'])
    with pytest.raises(character_lib.CharacterError) as info:
        character_lib.normalize_phrase("a b c d e f g")
    assert parse(_roster('- "the ronin": a man', '- "a b c d e f g": x')) == (
        [("the ronin", "a man")], [str(info.value)])
    assert parse(_roster('- "the ronin": a man', '- "The Ronin": a tall man')) == (
        [("the ronin", "a man")], ["phrase 'The Ronin' is listed more than once"])
    assert parse(_roster('- "the ronin": a man', "", '- "the monk": an old man')) == (
        [("the ronin", "a man"), ("the monk", "an old man")], [])
    assert parse(_roster('- "the ronin": a man') + '\n- "x y": z\n') == (
        [("the ronin", "a man")], [])
    assert parse("# T\n\nA summary.\n\n## Characters\n\n## Panel 1 — A\nImage: x\n") == (
        [], ['the "## Characters" section lists no characters'])
    late = _variant("A ronin saves a woman from a robber on a forest trail.",
                    "Three characters meet on a forest trail.",
                    SHOTS_OK.replace(ROSTER_BLOCK, "")) + "\n" + ROSTER_BLOCK
    assert late.index("## Characters") > late.index("## Panel 3")
    assert parse(late) == (entries, [])


TEN_WORDS = "The ronin slowly lowers his katana toward the mossy ground."
TWENTY_FIVE_WORDS = ("The ronin slowly lowers his curved katana toward the soft mossy ground beside "
                     "the old stone lantern near the quiet shrine at the trail's end.")


def test_s6_motion_problems_pass(tmp_path):
    assert len(TEN_WORDS.split()) == 10 and len(TWENTY_FIVE_WORDS.split()) == 25
    texts = [p["motion"] for p in _panels(tmp_path, SHOTS_OK)] + [
        "The ronin draws his katana from its scabbard in one smooth motion. The camera stays "
        "static.",
        "The woman in grey swings the cedar branch at the robber's knife hand.",
        TEN_WORDS,
        TWENTY_FIVE_WORDS,
        "Camera holds. The ronin kneels beside the fallen branch on the trail."]
    assert len(texts) == 8
    for text in texts:
        assert character_lib.motion_problems(text) == [], text


def test_s7_motion_problems_fail():
    problems = character_lib.motion_problems
    nine = "The ronin slowly lowers his katana toward the ground."
    twenty_six = TWENTY_FIVE_WORDS.replace("his curved", "his long curved")
    assert len(nine.split()) == 9 and len(twenty_six.split()) == 26
    assert problems(nine) == [("S4 motion length", "Motion: is 9 words; it must be 10-25")]
    assert problems(twenty_six) == [("S4 motion length", "Motion: is 26 words; it must be 10-25")]
    assert problems("The ronin draws his sword. The ronin strikes the bearded robber hard.") == [
        ("S5 one action", "Motion: has 2 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]
    assert problems("The ronin draws his sword; he strikes the bearded robber across the arm.") == [
        ("S5 one action", "Motion: contains a semicolon")]
    for word, shown in (("then", "then"), ("While", "while"), ("meanwhile", "meanwhile"),
                        ("simultaneously", "simultaneously"), ("afterwards", "afterwards"),
                        ("followed  by", "followed by"), ("as soon as", "as soon as")):
        if word == "While":
            text = ("While the ronin raises his katana the bearded robber stumbles back across "
                    "the mossy trail.")
        else:
            text = ("The ronin raises his katana %s the bearded robber stumbles back across the "
                    "mossy trail." % word)
        assert len(text.split()) == 14 + len(word.split()), text
        assert problems(text) == [("S5 one action", "Motion: chains actions with '%s'" % shown)], text
    assert problems("The ronin sprints in, and he draws his katana toward the robber.") == [
        ("S5 one action", "Motion: chains actions with ', and'")]
    assert problems("The camera pans slowly across the empty clearing toward the cedar trees.") == [
        ("S5 one action", "Motion: has 0 action sentences; it must have exactly one, optionally "
                          "followed by a camera sentence")]


def test_s8_motion_negative_controls():
    for text in ("The ronin crosses the strengthened rope bridge above the river gorge slowly.",
                 "The woman in grey kneels before the shrine and lowers her head."):
        assert character_lib.motion_problems(text) == [], text


def _cast_kyra_ronin(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    return _members("kyra", "ronin")


def _violations(tmp_path, text, members, expected_panels=3):
    return character_lib.shots_violations(text, _panels(tmp_path, text), expected_panels, members)


def test_s9_shots_ok_is_valid(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, SHOTS_OK, members) == []
    assert _violations(tmp_path, SHOTS_OK, []) == []


def test_s10_s1_panel_count(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, SHOTS_OK, members, expected_panels=4) == [
        "story: S1 panel count: expected exactly 4 panels, found 3"]


def test_s11_s2_roster_presence(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = SHOTS_OK.replace(ROSTER_BLOCK, "")
    assert "## Characters" not in text
    assert _violations(tmp_path, text, members) == [
        'story: S2 characters list: no "## Characters" section',
        "story: S2 characters list: cast phrase 'the woman in grey' (character kyra) is not listed",
        "story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]
    assert _violations(tmp_path, text, []) == []


def test_s12_s2_cast_phrase_missing(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant('- "the ronin": ' + DESC_R + "\n", "")
    assert _violations(tmp_path, text, members) == [
        "story: S2 characters list: cast phrase 'the ronin' (character ronin) is not listed"]


PANEL_2_IMAGE = ("Image: A medium close-up of the bearded robber, a stocky man with a black beard in "
                 "a ragged brown jacket, crouching among ferns on a mossy cedar trail and facing "
                 "left. Soft overcast light, muted green palette, eye-level camera, photorealistic "
                 "film still.\n")


def test_s13_s3_fields(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    assert _violations(tmp_path, _variant(PANEL_2_IMAGE, ""), members) == [
        "panel 2: S3 fields: missing/empty Image: field"]
    text = _variant("Narration: Help arrives.\n", "Narration: Help arrives.\nPrompt: x\n")
    assert _violations(tmp_path, text, members) == [
        "panel 3: S3 fields: has a Prompt: field; shots mode expects Image:, Motion: and "
        "Narration:"]


PANEL_3_MOTION = "Motion: The ronin offers his open hand to the woman in grey. The camera stays static."


def test_s14_violations_name_panel_and_rule(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_3_MOTION, "Motion: The ronin offers his hand then pulls the woman in "
                                    "grey to her feet on the trail.")
    assert _violations(tmp_path, text, members) == [
        "panel 3: S5 one action: Motion: chains actions with 'then'"]


def test_s15_s6_cast_count(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    _monk(lib_dir)
    three = _members("kyra", "ronin", "monk")
    roster = _variant('- "the bearded robber":',
                      '- "the monk": ' + DESC_M + '\n- "the bearded robber":')
    in_image = _variant("eye-level camera, photorealistic film still.\nMotion: The ronin offers",
                        "eye-level camera, photorealistic film still. The monk, an old bald man "
                        "with a white beard wearing a saffron robe and wooden prayer beads, stands "
                        "behind them.\nMotion: The ronin offers", roster)
    s6 = ["panel 3: S6 cast count: the shot names 3 cast characters (kyra, monk, ronin); at most 2"]
    assert _violations(tmp_path, in_image, three) == s6
    in_motion = _variant(PANEL_3_MOTION, "Motion: The monk raises his hand toward the ronin and "
                                         "the woman in grey.", roster)
    assert _violations(tmp_path, in_motion, three) == s6
    assert _violations(tmp_path, SHOTS_OK, members) == []


PANEL_1_MOTION = ("Motion: The woman in grey turns her head slowly toward the ferns on her right. "
                  "The camera stays static.")


def test_s16_s7_cast_and_extra(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant(PANEL_1_MOTION, "Motion: The woman in grey pushes the bearded robber away from "
                                    "her with both hands.")
    assert _violations(tmp_path, text, members) == [
        "panel 1: S7 cast and extra: Motion: names 'the woman in grey' together with 'the bearded "
        "robber'; show the other character's action in its own shot, then cut to the cast "
        "character's reaction"]
    assert _violations(tmp_path, SHOTS_OK, members) == []


def test_s17_s7_longest_phrase_claims_the_span(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)
    text = _variant('- "the bearded robber": a stocky man with a black beard in a ragged brown '
                    'jacket\n',
                    '- "the bearded robber": a stocky man with a black beard in a ragged brown '
                    'jacket\n- "the woman": an old woman in a straw hat\n')
    text = _variant(PANEL_1_MOTION, "Motion: The woman in grey bows her head to the trail shrine "
                                    "slowly. The camera stays static.", text)
    assert character_lib.parse_character_roster(text)[0][-1] == (
        "the woman", "an old woman in a straw hat")
    assert _violations(tmp_path, text, members) == []


def test_s18_shots_advisories(tmp_path, lib_dir):
    members = _cast_kyra_ronin(lib_dir)

    def advise(text, cast=members):
        return character_lib.shots_advisories(_panels(tmp_path, text), cast)

    assert advise(SHOTS_OK) == []
    assert advise(_variant("grey kimono, standing in the centre", "grey robe, standing in the centre")) == [
        "panel 1: Image: names 'the woman in grey' but does not repeat character kyra's Cast "
        "description word for word; that still relies on the phrase and the stills LoRA alone"]
    assert advise(_variant("hairpins wearing a grey kimono, standing in the centre",
                           "hairpins   WEARING a grey kimono, standing in the centre")) == []
    assert advise(_variant("A medium shot of the woman in grey", "A wide shot of the woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is wide shot; a shot with "
        "a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium shot of the woman in grey", "The woman in grey")) == [
        "panel 1: shows cast character(s) kyra but its Image: shot type is not stated; a shot "
        "with a cast character should be a medium shot or closer"]
    assert advise(_variant("A medium close-up of the bearded robber",
                           "A wide shot of the bearded robber")) == []
    assert advise(SHOTS_OK, cast=[]) == []


def test_s19_shots_rewrite_block():
    lib = character_lib
    block = lib.shots_rewrite_block(["a", "b", "c"], 14)
    assert block == lib.SHOTS_REWRITE_TEMPLATE % ("- a\n- b\n- c", 14)
    assert "Keep EXACTLY 14 panel sections." in block
    many = ["v%d" % i for i in range(1, 46)]
    listed = "\n".join(["- v%d" % i for i in range(1, 41)] + ["- ... and 5 more"])
    assert lib.shots_rewrite_block(many, 3) == lib.SHOTS_REWRITE_TEMPLATE % (listed, 3)
    assert lib.SHOTS_REWRITE_TEMPLATE.count("%") == 2


def test_s20_character_lib_imports():
    with open(os.path.join(WS, "character_lib.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names == {"collections", "datetime", "json", "os", "re", "uuid"}
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `19 failed, 1 passed, <w> warnings in <t>s`, `rc=1`. S20 passes before the implementation (the import set is unchanged; it is a guard); every other test fails on a missing `character_lib` name.

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T2.S3` applies these four edits to `character_lib.py`.

**Edit 1** (module docstring, spec 3 preamble). Replace this exact text, which occurs exactly once:

````python plan=T2.S3.1 op=replace path=character_lib.py
and bin/ltx-story-images load it by path, and only inside their casting branch, so
an uncast run never reads this file.
````

with:

````python plan=T2.S3.2 op=with path=character_lib.py
and bin/ltx-story-images load it by path, and only inside their casting branch, so
an uncast run never reads this file. It also owns the shots-mode story rules (shot-rule
validation, advisories and the rewrite block;
docs/superpowers/specs/2026-10-06-shots-mode-design.md).
````

**Edit 2** (spec 3.1, after `SINGLE_CHARACTER_STRENGTH`). Replace this exact text, which occurs exactly once:

````python plan=T2.S3.3 op=replace path=character_lib.py
SINGLE_CHARACTER_STRENGTH = 1.0
TRIGGER_REGISTRY = ".triggers"
````

with:

````python plan=T2.S3.4 op=with path=character_lib.py
SINGLE_CHARACTER_STRENGTH = 1.0
SHOTS_CHARACTER_STRENGTH = 0.8
SHOTS_MOTION_MIN_WORDS = 10
SHOTS_MOTION_MAX_WORDS = 25
SHOTS_MAX_CAST_PER_PANEL = 2
SHOTS_REWRITE_MAX_LISTED = 40
SHOTS_CLOSE_SHOT_TYPES = ("medium shot", "medium close-up", "close-up", "extreme close-up")

_ROSTER_HEADER_RE = re.compile(r"##\s*Characters", re.IGNORECASE)
_ROSTER_ENTRY_RE = re.compile(r'[-*]\s*["“]([^"“”]+)["”]\s*:\s*(\S.*)')
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CAMERA_SENTENCE_RE = re.compile(r"(?:the\s+)?camera\b", re.IGNORECASE)
_CHAIN_WORD_RE = re.compile(r"\b(?:then|while|meanwhile|simultaneously|afterwards?|whereupon|"
                            r"followed\s+by|as\s+soon\s+as)\b", re.IGNORECASE)
_COMMA_AND_RE = re.compile(r",\s+and\b", re.IGNORECASE)
_SHOT_TYPE_RE = re.compile(r"(?<![\w-])(extreme wide shot|extreme close-up|medium close-up|"
                           r"medium shot|wide shot|close-up)(?![\w-])", re.IGNORECASE)

TRIGGER_REGISTRY = ".triggers"
````

**Edit 3** (spec 3.3 and 3.9 constants, directly after `CAST_BLOCK_RULES`). Replace this exact text, which occurs exactly once:

````python plan=T2.S3.5 op=replace path=character_lib.py
    "Every other character still gets a referring phrase of your own, under the rules below.")

_TOP_LEVEL_KEYS = frozenset([
````

with:

````python plan=T2.S3.6 op=with path=character_lib.py
    "Every other character still gets a referring phrase of your own, under the rules below.")
SHOTS_CAST_BLOCK_RULES = (
    "Use each quoted phrase above, word for word, as that character's referring phrase "
    "everywhere in the file, even when it is longer than four words, and list each of them in "
    "the Characters section with exactly the description given above. In every panel's Image: "
    "field where one of these characters is on screen, name them by that phrase and then give "
    "exactly the description given above, word for word. Shots that show these characters "
    "follow four extra rules. One: at most two of these characters appear in any one shot. "
    "Two: a shot that shows one of them is composed around them -- a medium shot or closer, "
    "with them in the centre or the foreground of the frame. Three: any other character may "
    "appear in such a shot only far in the background, small in the frame, never touching them "
    "and never within arm's reach of them, and that shot's Motion: names none of the other "
    "characters; when one of these characters and another character act on each other at close "
    "range -- a grab, a blow, a shove -- show it by cutting: first a shot of the other character "
    "performing the action, then a separate shot of this character's reaction. Four: when two "
    "of these characters share a shot they stay apart or touch only lightly, such as an offered "
    "hand or a hand on an arm; they never grapple, embrace or overlap. A shot that shows none of "
    "these characters has none of these extra rules. Bring a cast member on screen only where "
    "the narrative calls for them. Every other character still gets a referring phrase of your "
    "own, under the rules below.")
SHOTS_REWRITE_TEMPLATE = (
    "REWRITE REQUIRED. Your previous draft of this file was rejected because it broke these "
    "rules:\n"
    "%s\n"
    "Write the complete file again from the beginning, following every instruction above and "
    "fixing every listed problem. Keep EXACTLY %d panel sections. Where a Motion: held more than "
    "one action, keep only its single most important action and give the other beats their own "
    "panels instead, merging or dropping minor beats so that the panel count stays the same.")

_TOP_LEVEL_KEYS = frozenset([
````

**Edit 4** (spec 3.2 and 3.3 replace `panel_strengths` and `build_cast_block` in place; spec 3.4-3.9 functions follow, before `usable_characters`). Replace this exact text, which occurs exactly once:

````python plan=T2.S3.7 op=replace path=character_lib.py
def panel_strengths(names, members, character_strength):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named; else each
    character's own character.json strength if set, otherwise character_strength (spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}


def build_cast_block(members):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(CAST_BLOCK_RULES)
    return "\n".join(lines)


def usable_characters():
````

with:

````python plan=T2.S3.8 op=with path=character_lib.py
def panel_strengths(names, members, character_strength, shots=False):
    """{name: strength} for one panel: 1.0 when exactly one cast character is named (continuous
    mode only); else -- and always in shots mode -- each character's own character.json strength
    if set, otherwise character_strength (casting spec 6; shots spec 6)."""
    by_name = {m.name: m for m in members}
    if len(names) == 1 and not shots:
        return {names[0]: SINGLE_CHARACTER_STRENGTH}
    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)
            for n in names}


def build_cast_block(members, shots=False):
    lines = [CAST_BLOCK_HEADER]
    for m in members:
        lines.append('- "%s": %s.' % (m.phrase, m.descriptor))
    lines.append(SHOTS_CAST_BLOCK_RULES if shots else CAST_BLOCK_RULES)
    return "\n".join(lines)


def find_phrases(text, phrases):
    """The given phrases that occur in text, matched exactly like cast_text (case-insensitive,
    whitespace-tolerant, hyphen counts as a word character), longest phrase first, a match
    overlapping an already-claimed span ignored. Each phrase is returned once, as given, in the
    order of its first claimed occurrence (shots spec 3.4). Phrases must already be valid
    (normalize_phrase)."""
    claimed = []
    for phrase in sorted(set(phrases), key=lambda p: (-len(p), p.lower(), p)):
        for match in _phrase_regex(normalize_phrase(phrase)).finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e, _ in claimed):
                continue
            claimed.append((start, end, phrase))
    ordered = []
    for _start, _end, phrase in sorted(claimed):
        if phrase not in ordered:
            ordered.append(phrase)
    return ordered


def parse_character_roster(text):
    """([(phrase, description)], [problem]) from a shots story's "## Characters" section: the
    lines after the first line that is exactly "## Characters" (case-insensitive, any spacing
    after the hashes), up to the next line starting with "#". Blank lines are skipped; every
    other line must be - "<phrase>": <description> (straight or curly double quotes, "-" or
    "*" bullet). Phrases are normalized; a duplicate (case-insensitive) is a problem (spec 3.5)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _ROSTER_HEADER_RE.fullmatch(line.strip()):
            start = i + 1
            break
    if start is None:
        return [], ['no "## Characters" section']
    entries, problems = [], []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped:
            continue
        match = _ROSTER_ENTRY_RE.fullmatch(stripped)
        if not match:
            problems.append('line %r is not - "<referring phrase>": <description>'
                            % stripped[:80])
            continue
        try:
            phrase = normalize_phrase(match.group(1))
        except CharacterError as e:
            problems.append(str(e))
            continue
        if phrase.lower() in [p.lower() for p, _ in entries]:
            problems.append("phrase %r is listed more than once" % phrase)
            continue
        entries.append((phrase, match.group(2).strip()))
    if not entries:
        problems.append('the "## Characters" section lists no characters')
    return entries, problems


def motion_problems(motion):
    """[(rule, detail)] for one shots-mode Motion: text (spec 4.3 S4, S5). A sentence that starts
    with "camera" or "the camera" is a camera sentence and is not an action sentence."""
    problems = []
    words = len(motion.split())
    if not SHOTS_MOTION_MIN_WORDS <= words <= SHOTS_MOTION_MAX_WORDS:
        problems.append(("S4 motion length", "Motion: is %d words; it must be %d-%d"
                         % (words, SHOTS_MOTION_MIN_WORDS, SHOTS_MOTION_MAX_WORDS)))
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(motion.strip()) if s.strip()]
    actions = [s for s in sentences if not _CAMERA_SENTENCE_RE.match(s)]
    if len(actions) != 1:
        problems.append(("S5 one action", "Motion: has %d action sentences; it must have exactly "
                         "one, optionally followed by a camera sentence" % len(actions)))
    if ";" in motion:
        problems.append(("S5 one action", "Motion: contains a semicolon"))
    chain = _CHAIN_WORD_RE.search(motion)
    if chain:
        problems.append(("S5 one action", "Motion: chains actions with %r"
                         % " ".join(chain.group(0).lower().split())))
    if _COMMA_AND_RE.search(motion):
        problems.append(("S5 one action", "Motion: chains actions with ', and'"))
    return problems


def shots_violations(text, panels, expected_panels, members):
    """Every shot-rule violation of a shots-mode story.md (spec 4.3), in this order: S1, S2, then
    per panel S3, S4, S5, S6, S7. text is the whole file; panels are bin/ltx-story-manifest
    _parse_prompts_md dicts; members are CastMember (may be empty: then S2, S6, S7 are skipped)."""
    out = []
    if len(panels) != expected_panels:
        out.append("story: S1 panel count: expected exactly %d panels, found %d"
                   % (expected_panels, len(panels)))
    roster = []
    if members:
        roster, problems = parse_character_roster(text)
        out += ["story: S2 characters list: %s" % p for p in problems]
        listed = [p.lower() for p, _ in roster]
        for m in members:
            if m.phrase.lower() not in listed:
                out.append("story: S2 characters list: cast phrase %r (character %s) is not listed"
                           % (m.phrase, m.name))
    cast_phrases = {m.phrase.lower() for m in members}
    extras = [p for p, _ in roster if p.lower() not in cast_phrases]
    for p in panels:
        num = p["number"]
        for label, key in (("Image", "image"), ("Motion", "motion"), ("Narration", "narration")):
            if not p[key].strip():
                out.append("panel %d: S3 fields: missing/empty %s: field" % (num, label))
        if p["prompt"].strip():
            out.append("panel %d: S3 fields: has a Prompt: field; shots mode expects Image:, "
                       "Motion: and Narration:" % num)
        if p["motion"].strip():
            out += ["panel %d: %s: %s" % (num, rule, detail)
                    for rule, detail in motion_problems(p["motion"])]
        if not members:
            continue
        names = sorted(set(cast_text(p["image"], members)[1])
                       | set(cast_text(p["motion"], members)[1]))
        if len(names) > SHOTS_MAX_CAST_PER_PANEL:
            out.append("panel %d: S6 cast count: the shot names %d cast characters (%s); at most %d"
                       % (num, len(names), ", ".join(names), SHOTS_MAX_CAST_PER_PANEL))
        found = find_phrases(p["motion"], [m.phrase for m in members] + extras)
        cast_found = [f for f in found if f.lower() in cast_phrases]
        extra_found = [f for f in found if f.lower() not in cast_phrases]
        if cast_found and extra_found:
            out.append("panel %d: S7 cast and extra: Motion: names %s together with %s; show the "
                       "other character's action in its own shot, then cut to the cast "
                       "character's reaction"
                       % (num, ", ".join(repr(f) for f in cast_found),
                          ", ".join(repr(f) for f in extra_found)))
    return out


def shots_advisories(panels, members):
    """Non-fatal shots-mode warnings (spec 4.4), per panel in order: W1 for each cast member
    named in Image: whose descriptor is not repeated there (whitespace- and case-insensitive),
    then W2 when the shot names a cast character but its Image: states no shot type, or a wide
    one. [] when members is empty."""
    out = []
    if not members:
        return out
    for p in panels:
        num = p["number"]
        image_norm = " ".join(p["image"].split()).lower()
        for m in members:
            if (phrase_occurs(p["image"], m.phrase)
                    and " ".join(m.descriptor.split()).lower() not in image_norm):
                out.append("panel %d: Image: names %r but does not repeat character %s's Cast "
                           "description word for word; that still relies on the phrase and the "
                           "stills LoRA alone" % (num, m.phrase, m.name))
        names = sorted(set(cast_text(p["image"], members)[1])
                       | set(cast_text(p["motion"], members)[1]))
        if names:
            types = [t.lower() for t in _SHOT_TYPE_RE.findall(p["image"])]
            if not types or any(t not in SHOTS_CLOSE_SHOT_TYPES for t in types):
                out.append("panel %d: shows cast character(s) %s but its Image: shot type is %s; a "
                           "shot with a cast character should be a medium shot or closer"
                           % (num, ", ".join(names), ", ".join(types) or "not stated"))
    return out


def shots_rewrite_block(violations, panels):
    """The text appended to the Phase 1 prompt for the one rewrite (spec 5.4): at most
    SHOTS_REWRITE_MAX_LISTED violations as "- <violation>" lines, then "- ... and N more"."""
    listed = violations[:SHOTS_REWRITE_MAX_LISTED]
    lines = ["- " + v for v in listed]
    if len(violations) > len(listed):
        lines.append("- ... and %d more" % (len(violations) - len(listed)))
    return SHOTS_REWRITE_TEMPLATE % ("\n".join(lines), panels)


def usable_characters():
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `20 passed, <w> warnings in <t>s`, `rc=0`. Then the casting set, which includes `tests/test_character_lib.py` (C36, C39 and C41 pin the unchanged continuous behaviour): `python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider; echo "rc=$?"` -> `178 passed`, `rc=0`. Then `wc -l character_lib.py tests/test_shots_mode.py` prints `741 character_lib.py` and `462 tests/test_shots_mode.py`.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add character_lib.py tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/character_lib.py
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
character_lib: shots-mode strength, Cast block, roster parser, shot rules and rewrite block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 3: `bin/ltx-story-manifest --shots` -- schema 3, every panel `still`, cast from Image: and Motion:

**Files:**
- Modify: `bin/ltx-story-manifest` (10 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: `character_lib` (Task 2), loaded by path: `SHOTS_CHARACTER_STRENGTH`, `DEFAULT_CHARACTER_STRENGTH`, `cast_text`, `panel_strengths(..., shots=)`, `resolve_cast`, `parse_cast_arg`, `CharacterError`.
- Produces: the CLI flag `--shots` (one `--image` per panel, in order; requires `--prompts-md`; mutually exclusive with `--chain`, `--glob`, `--no-images`); a schema-3 manifest whose every panel is `conditioning: "still"` with its own `image_path`, `panel_text` = Image:, `motion_prompt` = Motion: (with triggers when cast); with `--cast`, `characters` = the cast names found in Image: ∪ Motion:, each at its `character.json` strength or `--character-strength` (default 0.8). Task 10's Phase 3 passes `--shots --image ... --image ...`. Task 5 renders this manifest.
- The test section produces `S61_STORY`, `_shots_manifest_env`, `_shots_manifest_argv`, `_shots_manifest` (Task 5 reuses them).

Spec 5.9, verbatim:

#### 5.9 `bin/ltx-story-manifest --shots`

1. **Argument**, directly after `--chain`:

```python
    parser.add_argument("--shots", action="store_true", default=False,
                         help="shots flow (bin/ltx-movie --shots): every panel is its own shot "
                              "conditioned on its own still; give one --image per panel, in "
                              "panel order. Requires --prompts-md; mutually exclusive with "
                              "--chain, --glob and --no-images. With --cast, a panel's "
                              "characters are those its Image: or Motion: names, each at its "
                              "character.json strength or --character-strength (default 0.8), "
                              "alone or not.")
```

2. **Validation.** Directly **before** the first `    if args.chain:` in `main` (the argument-validation block at `:351`), insert the block below. Then replace `    if args.cast and not args.chain:\n        parser.error("--cast requires --chain")` with `    if args.cast and not (args.chain or args.shots):\n        parser.error("--cast requires --chain or --shots")`. P23's substring holds.

```python
    if args.shots:
        if args.chain or args.no_images or args.glob:
            parser.error("--shots is mutually exclusive with --chain, --glob and --no-images")
        if not args.prompts_md:
            parser.error("--shots requires --prompts-md")
```

3. **Field checks.** Directly after the `if args.chain: … elif not args.no_images and len(parsed_panels) != len(matched): …` block (`:404-426`, before the "both a Prompt: field and an Image:/Motion:" loop), insert the block below. The count check (`Error: prompts.md has %d panels but %d images were selected`) already applies to `--shots`, because it is not `--chain`.

```python
        if args.shots:
            for i, pt in enumerate(parsed_panels, start=1):
                if not pt["image"].strip():
                    print("Error: --shots requires every panel to have a non-empty Image: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if not pt["motion"].strip():
                    print("Error: --shots requires every panel to have a non-empty Motion: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if pt["prompt"].strip():
                    print("Error: --shots does not accept Prompt: fields; panel %d has one" % i,
                          file=sys.stderr)
                    return 2
```

4. **Default strength:** `strength = (args.character_strength if args.character_strength is not None else (lib.SHOTS_CHARACTER_STRENGTH if args.shots else lib.DEFAULT_CHARACTER_STRENGTH))`.
5. **Panel loop** (`:517-574`). Insert an `elif args.shots:` branch between that loop's `if args.chain:` branch and its `else:`:

```python
        elif args.shots:
            title = pt["title"]
            narration = pt["narration"]
            motion_prompt = pt["motion"]
            image_path = matched[i - 1]
            conditioning = "still"
            panel_text = pt["image"]
```

6. **Cast application.** Inside `if members:`, after `p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)`, add:

```python
            if args.shots:
                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))
```

   - `panel_strengths(...)` gets `shots=args.shots`.
   - The E-P14 warning becomes `"WARNING: cast phrase %r (character %s) occurs in no panel's %s text; that character gets no LoRA" % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:")`. The chained output is byte-identical (P22).
   - **The video character set is Image: ∪ Motion: [spec choice].** In shots mode the Image: is the panel's own conditioning frame, so it is the authoritative list of who is on screen, and a pronoun-only Motion: ("She bows") no longer drops the LoRA (casting gap G5).
   - Triggers are still inserted only into `motion_prompt`, where the phrase occurs. `panel_text` is left as authored.
7. `_prompt_length_warning(p["index"], p["motion_prompt"] if (args.chain or args.shots) else p["panel_text"])`.
8. `"schema_version": 3 if (args.chain or args.shots) else 2`.
9. **Docstring.** Append: `--shots (bin/ltx-movie --shots) writes schema_version 3 with every panel conditioning "still": one --image per panel, in order; panel_text is the Image: text and motion_prompt the Motion: text. With --cast, a panel's characters are the cast phrases its Image: or Motion: names, each at its character.json strength or --character-strength (default 0.8), alone or not.`

Spec 10.5 rows S60-S65, verbatim (S66 is Task 5):

All use `WS` patched to `tmp_path` and 64x64 PNGs made at runtime.

| ID | Test | Assertion |
|---|---|---|
| S60 | `--shots`, uncast, `SHOTS_OK` + 3 images | rc 0. `schema_version == 3`. Each panel has `conditioning == "still"`, `image_path ==` the abspath of its own image, `panel_text ==` its Image:, `motion_prompt ==` its Motion:. No `characters` key. No `"(chained)"` in stdout |
| S61 | `--shots --cast "the woman in grey=kyra" --cast "the ronin=ronin" --character-strength 0.8` on a 4-panel story: P1 Image+Motion kyra; P2 Image kyra+ronin, Motion ronin only; P3 Image kyra, Motion `"She bows her head low to the shrine on the trail."`; P4 nobody | characters `[kyra@0.8]`, `[kyra@0.8, ronin@0.8]`, `[kyra@0.8]`, `[]`. `motion_prompt`s: P1 has `the kyrawmn woman in grey`; P2 has `the roninmn ronin` and no `kyrawmn`; P3 is unchanged (no trigger). Every `panel_text` is byte-identical to S60's. stdout has `cast: panel 1: kyra@0.8` |
| S62 | strength overrides | `--character-strength 0.6` → P1 `[kyra@0.6]`. Ronin `character.json` `strength 0.5` → P2 `[kyra@0.6, ronin@0.5]`. No `--character-strength` → 0.8 (the `SHOTS_CHARACTER_STRENGTH` default). The same story with `--chain` (and one image) still gives a lone 1.0 (continuous unchanged) |
| S63 | errors | each exits 2 and writes no manifest: `--shots --chain`; `--shots --no-images`; `--shots --glob 'panel_*.png'` (`SystemExit` 2, the E-S15 message); `--shots` without `--prompts-md`; 2 images for 3 panels (`"Error: prompts.md has 3 panels but 2 images were selected"`); panel 2 without Image: (`"Error: --shots requires every panel to have a non-empty Image: field; panel 2 has none"`); panel 3 without Motion:; panel 1 with `Prompt:` (`"Error: --shots does not accept Prompt: fields; panel 1 has one"`) |
| S64 | `--cast` without `--chain`/`--shots` | `SystemExit` 2, stderr contains `"--cast requires --chain or --shots"` (and therefore P23's substring) |
| S65 | E-P14, shots | cast phrase in no Image: or Motion: → stdout `"WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Image: or Motion: text; that character gets no LoRA"`. The `--chain` wording is unchanged (P22) |

Precondition: `git diff --quiet HEAD -- bin/ltx-story-manifest && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T3.S1` appends exactly this content to the end of `tests/test_shots_mode.py` (the block starts with two blank lines):

````python plan=T3.S1.1 op=append path=tests/test_shots_mode.py


# --- S60-S65: bin/ltx-story-manifest --shots (spec 5.9) ---------------------------------
S61_STORY = """# Shots cast test

The woman in grey meets the ronin on a forest trail.

## Characters
- "the woman in grey": %s
- "the ronin": %s

## Panel 1 — One
Image: A medium shot of the woman in grey standing on a mossy cedar trail and facing right.
Motion: The woman in grey turns her head slowly toward the ferns on her right.
Narration: She listens.

## Panel 2 — Two
Image: A medium shot of the woman in grey and the ronin standing apart on the mossy trail.
Motion: The ronin bows his head slowly to her across the mossy trail.
Narration: He greets her.

## Panel 3 — Three
Image: A medium close-up of the woman in grey kneeling beside a small trail shrine.
Motion: She bows her head low to the shrine on the trail.
Narration: She prays.

## Panel 4 — Four
Image: A wide shot of the empty mossy cedar trail under grey clouds.
Motion: Leaves drift slowly across the empty trail in the cold wind.
Narration: The forest is quiet.
""" % (DESC_K, DESC_R)


def _shots_manifest_env(tmp_path, monkeypatch, text=SHOTS_OK, images=None):
    """A workspace root under tmp_path for bin/ltx-story-manifest (its module WS is patched),
    with character_lib.py symlinked in so _character_lib() loads the real module, the
    story.md, and one 64x64 PNG per panel (or images PNGs). Returns (story_md, [image], ws)."""
    from PIL import Image
    ws = tmp_path / "ws"
    ws.mkdir()
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(story_manifest, "WS", str(ws))
    story_md = tmp_path / "story.md"
    story_md.write_text(text, encoding="utf-8")
    count = images if images is not None else len(_panels(tmp_path, text))
    paths = []
    for i in range(1, count + 1):
        path = str(tmp_path / ("panel_%02d.png" % i))
        Image.new("RGB", (64, 64), (20 * i, 90, 90)).save(path)
        paths.append(path)
    return str(story_md), paths, str(ws)


def _shots_manifest_argv(story_id, story_md, images, *extra):
    argv = ["--story-id", story_id, "--prompts-md", story_md, "--shots"]
    for image in images:
        argv += ["--image", image]
    return argv + ["--fps", "24", "--target-seconds", repr(145 * len(images) / 24.0),
                   "--min-frames", "145", "--max-frames", "145", "--force"] + list(extra)


def _shots_manifest(ws, story_id):
    path = os.path.join(ws, "generated", "stories", story_id, "manifest.json")
    with open(path) as f:
        return json.load(f)


def _names_strengths(panel):
    return [(c["name"], c["strength"]) for c in panel["characters"]]


def test_s60_shots_manifest_uncast(tmp_path, monkeypatch, capsys):
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_shots_manifest_argv("s60", story_md, images)) == 0
    out = capsys.readouterr().out
    manifest = _shots_manifest(ws, "s60")
    parsed = _panels(tmp_path, SHOTS_OK)
    assert manifest["schema_version"] == 3
    assert len(manifest["panels"]) == 3
    for panel, image, pt in zip(manifest["panels"], images, parsed):
        assert panel["conditioning"] == "still"
        assert panel["image_path"] == os.path.abspath(image)
        assert panel["panel_text"] == pt["image"]
        assert panel["motion_prompt"] == pt["motion"]
        assert "characters" not in panel
    assert "(chained)" not in out


def test_s61_shots_cast_names_come_from_image_and_motion(tmp_path, monkeypatch, capsys, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    assert story_manifest.main(_shots_manifest_argv("uncast", story_md, images)) == 0
    capsys.readouterr()
    assert story_manifest.main(_shots_manifest_argv(
        "cast", story_md, images, "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8")) == 0
    out = capsys.readouterr().out
    cast, uncast = _shots_manifest(ws, "cast")["panels"], _shots_manifest(ws, "uncast")["panels"]
    assert [_names_strengths(p) for p in cast] == [
        [("kyra", 0.8)], [("kyra", 0.8), ("ronin", 0.8)], [("kyra", 0.8)], []]
    assert "the kyrawmn woman in grey" in cast[0]["motion_prompt"].lower()
    assert "the roninmn ronin" in cast[1]["motion_prompt"].lower()
    assert "kyrawmn" not in cast[1]["motion_prompt"]
    assert cast[2]["motion_prompt"] == "She bows her head low to the shrine on the trail."
    assert [p["panel_text"] for p in cast] == [p["panel_text"] for p in uncast]
    assert "cast: panel 1: kyra@0.8" in out.splitlines()


def test_s62_shots_strength_overrides(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir, strength=0.5)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    cast = ["--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin"]
    assert story_manifest.main(_shots_manifest_argv(
        "s06", story_md, images, *(cast + ["--character-strength", "0.6"]))) == 0
    panels = _shots_manifest(ws, "s06")["panels"]
    assert _names_strengths(panels[0]) == [("kyra", 0.6)]
    assert _names_strengths(panels[1]) == [("kyra", 0.6), ("ronin", 0.5)]
    assert story_manifest.main(_shots_manifest_argv("default", story_md, images, *cast)) == 0
    assert _names_strengths(_shots_manifest(ws, "default")["panels"][0]) == [("kyra", 0.8)]
    chain = ["--story-id", "chain", "--prompts-md", story_md, "--chain", "--image", images[0],
             "--fps", "24", "--target-seconds", repr(145 * 4 / 24.0), "--min-frames", "145",
             "--max-frames", "145", "--force"] + cast
    assert story_manifest.main(chain) == 0
    assert _names_strengths(_shots_manifest(ws, "chain")["panels"][0]) == [("kyra", 1.0)]


def test_s63_shots_manifest_errors(tmp_path, monkeypatch, capsys):
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    manifest = os.path.join(ws, "generated", "stories", "bad", "manifest.json")
    exclusive = "--shots is mutually exclusive with --chain, --glob and --no-images"
    for extra in (["--chain"], ["--no-images"], ["--glob", "panel_*.png"]):
        with pytest.raises(SystemExit) as info:
            story_manifest.main(_shots_manifest_argv("bad", story_md, images, *extra))
        assert info.value.code == 2
        assert exclusive in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--shots", "--image", images[0]])
    assert info.value.code == 2
    assert "--shots requires --prompts-md" in capsys.readouterr().err
    assert story_manifest.main(_shots_manifest_argv("bad", story_md, images[:2])) == 2
    assert capsys.readouterr().err == (
        "Error: prompts.md has 3 panels but 2 images were selected\n")
    cases = [
        (_variant(PANEL_2_IMAGE, ""),
         "Error: --shots requires every panel to have a non-empty Image: field; panel 2 has none\n"),
        (_variant(PANEL_3_MOTION + "\n", ""),
         "Error: --shots requires every panel to have a non-empty Motion: field; panel 3 has none\n"),
        (_variant("Narration: She senses she is not alone.\n",
                  "Narration: She senses she is not alone.\nPrompt: x\n"),
         "Error: --shots does not accept Prompt: fields; panel 1 has one\n"),
    ]
    for text, message in cases:
        with open(story_md, "w", encoding="utf-8") as f:
            f.write(text)
        assert story_manifest.main(_shots_manifest_argv("bad", story_md, images)) == 2
        assert capsys.readouterr().err == message
    assert not os.path.exists(manifest)


def test_s64_cast_requires_chain_or_shots(tmp_path, monkeypatch, capsys, lib_dir):
    _kyra(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as info:
        story_manifest.main(["--story-id", "bad", "--prompts-md", story_md, "--image", images[0],
                             "--cast", "the woman in grey=kyra"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "--cast requires --chain or --shots" in err
    assert "--cast requires --chain" in err


def test_s65_unused_cast_phrase_warning_names_image_and_motion(tmp_path, monkeypatch, capsys,
                                                               lib_dir):
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch)
    assert story_manifest.main(_shots_manifest_argv(
        "s65", story_md, images, "--cast", "the stranger=ronin")) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Image: or "
            "Motion: text; that character gets no LoRA") in capsys.readouterr().out
    chain = ["--story-id", "s65c", "--prompts-md", story_md, "--chain", "--image", images[0],
             "--fps", "24", "--target-seconds", "18.125", "--min-frames", "145",
             "--max-frames", "145", "--force", "--cast", "the stranger=ronin"]
    assert story_manifest.main(chain) == 0
    assert ("WARNING: cast phrase 'the stranger' (character ronin) occurs in no panel's Motion: "
            "text; that character gets no LoRA") in capsys.readouterr().out
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `6 failed, 20 passed, <w> warnings in <t>s`, `rc=1`.

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T3.S3` applies these ten edits to `bin/ltx-story-manifest`.

**Edit 1** (spec 5.9 item 9, the docstring; appended as a new paragraph after the `--cast` paragraph, Decision 4). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.1 op=replace path=bin/ltx-story-manifest
schema_version stays 3, because the key is optional. character_lib.py is loaded by path
only when --cast is given.
````

with:

````python plan=T3.S3.2 op=with path=bin/ltx-story-manifest
schema_version stays 3, because the key is optional. character_lib.py is loaded by path
only when --cast is given.

--shots (bin/ltx-movie --shots) writes schema_version 3 with every panel conditioning
"still": one --image per panel, in order; panel_text is the Image: text and
motion_prompt the Motion: text. With --cast, a panel's characters are the cast phrases
its Image: or Motion: names, each at its character.json strength or --character-strength
(default 0.8), alone or not.
````

**Edit 2** (spec 5.9 item 1, the argument directly after `--chain`). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.3 op=replace path=bin/ltx-story-manifest
                              "exclusive with --glob and --no-images.")
    parser.add_argument("--images-dir", dest="images_dir", default=None,
````

with:

````python plan=T3.S3.4 op=with path=bin/ltx-story-manifest
                              "exclusive with --glob and --no-images.")
    parser.add_argument("--shots", action="store_true", default=False,
                         help="shots flow (bin/ltx-movie --shots): every panel is its own shot "
                              "conditioned on its own still; give one --image per panel, in "
                              "panel order. Requires --prompts-md; mutually exclusive with "
                              "--chain, --glob and --no-images. With --cast, a panel's "
                              "characters are those its Image: or Motion: names, each at its "
                              "character.json strength or --character-strength (default 0.8), "
                              "alone or not.")
    parser.add_argument("--images-dir", dest="images_dir", default=None,
````

**Edit 3** (spec 5.9 item 2, the validation block directly before the first `    if args.chain:`). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.5 op=replace path=bin/ltx-story-manifest
    if args.chain:
        if args.no_images or args.glob:
````

with:

````python plan=T3.S3.6 op=with path=bin/ltx-story-manifest
    if args.shots:
        if args.chain or args.no_images or args.glob:
            parser.error("--shots is mutually exclusive with --chain, --glob and --no-images")
        if not args.prompts_md:
            parser.error("--shots requires --prompts-md")
    if args.chain:
        if args.no_images or args.glob:
````

**Edit 4** (spec 5.9 item 2, the `--cast` check). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.7 op=replace path=bin/ltx-story-manifest
    if args.cast and not args.chain:
        parser.error("--cast requires --chain")
````

with:

````python plan=T3.S3.8 op=with path=bin/ltx-story-manifest
    if args.cast and not (args.chain or args.shots):
        parser.error("--cast requires --chain or --shots")
````

**Edit 5** (spec 5.9 item 3, the field checks, before the "both a Prompt: field and an Image:/Motion:" loop). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.9 op=replace path=bin/ltx-story-manifest
            return 2
        # A panel must use one form or the other: the assembly below silently
````

with:

````python plan=T3.S3.10 op=with path=bin/ltx-story-manifest
            return 2
        if args.shots:
            for i, pt in enumerate(parsed_panels, start=1):
                if not pt["image"].strip():
                    print("Error: --shots requires every panel to have a non-empty Image: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if not pt["motion"].strip():
                    print("Error: --shots requires every panel to have a non-empty Motion: field; "
                          "panel %d has none" % i, file=sys.stderr)
                    return 2
                if pt["prompt"].strip():
                    print("Error: --shots does not accept Prompt: fields; panel %d has one" % i,
                          file=sys.stderr)
                    return 2
        # A panel must use one form or the other: the assembly below silently
````

**Edit 6** (spec 5.9 item 4, the default strength). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.11 op=replace path=bin/ltx-story-manifest
        strength = (args.character_strength if args.character_strength is not None
                    else lib.DEFAULT_CHARACTER_STRENGTH)
````

with:

````python plan=T3.S3.12 op=with path=bin/ltx-story-manifest
        strength = (args.character_strength if args.character_strength is not None
                    else (lib.SHOTS_CHARACTER_STRENGTH if args.shots
                          else lib.DEFAULT_CHARACTER_STRENGTH))
````

**Edit 7** (spec 5.9 item 5, the panel-loop branch between `if args.chain:` and `else:`). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.13 op=replace path=bin/ltx-story-manifest
                panel_text = pt["motion"]
        else:
````

with:

````python plan=T3.S3.14 op=with path=bin/ltx-story-manifest
                panel_text = pt["motion"]
        elif args.shots:
            title = pt["title"]
            narration = pt["narration"]
            motion_prompt = pt["motion"]
            image_path = matched[i - 1]
            conditioning = "still"
            panel_text = pt["image"]
        else:
````

**Edit 8** (spec 5.9 item 6, cast application, the `shots=` keyword and the E-P14 wording). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.15 op=replace path=bin/ltx-story-manifest
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)
            strengths = lib.panel_strengths(names, members, strength)
````

with:

````python plan=T3.S3.16 op=with path=bin/ltx-story-manifest
            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)
            if args.shots:
                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))
            strengths = lib.panel_strengths(names, members, strength, shots=args.shots)
````

and replace this exact text, which occurs exactly once:

````python plan=T3.S3.17 op=replace path=bin/ltx-story-manifest
                print("WARNING: cast phrase %r (character %s) occurs in no panel's Motion: text; "
                      "that character gets no LoRA" % (m.phrase, m.name))
````

with:

````python plan=T3.S3.18 op=with path=bin/ltx-story-manifest
                print("WARNING: cast phrase %r (character %s) occurs in no panel's %s text; "
                      "that character gets no LoRA"
                      % (m.phrase, m.name, "Image: or Motion:" if args.shots else "Motion:"))
````

**Edit 9** (spec 5.9 item 7). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.19 op=replace path=bin/ltx-story-manifest
        _prompt_length_warning(p["index"], p["motion_prompt"] if args.chain else p["panel_text"])
````

with:

````python plan=T3.S3.20 op=with path=bin/ltx-story-manifest
        _prompt_length_warning(p["index"], p["motion_prompt"] if (args.chain or args.shots) else p["panel_text"])
````

**Edit 10** (spec 5.9 item 8). Replace this exact text, which occurs exactly once:

````python plan=T3.S3.21 op=replace path=bin/ltx-story-manifest
        "schema_version": 3 if args.chain else 2,
````

with:

````python plan=T3.S3.22 op=with path=bin/ltx-story-manifest
        "schema_version": 3 if (args.chain or args.shots) else 2,
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `26 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-story-manifest tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-story-manifest: --shots manifests, every panel conditioned on its own still

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 4: `bin/ltx-story-images --shots` -- the shots strength rule and the pinned seed

**Files:**
- Modify: `bin/ltx-story-images` (5 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: `character_lib` (Task 2): `SHOTS_CHARACTER_STRENGTH`, `panel_strengths(..., shots=)`.
- Produces: the CLI flag `--shots`: every generated panel uses `--seed` exactly (`grounded = bool(style) or args.shots`), and every cast character's stills LoRA, alone or paired, uses its `character.json` strength or `--character-strength` (default 0.8). Task 9 appends `--shots` to every stills-group command.
- The test section produces `_fake_zimage_shots` (Task 9's S45 reuses it).

Spec 5.10, verbatim:

#### 5.10 `bin/ltx-story-images --shots`

1. **Argument**, directly after `--character-strength`:

```python
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                        help="shots mode (bin/ltx-movie --shots): every generated panel uses --seed "
                             "exactly (pinned, as in grounded mode), and every cast character's "
                             "stills LoRA, alone or with another, uses its character.json strength "
                             "or --character-strength (default 0.8)")
```

2. **Default strength:** `(args.character_strength if args.character_strength is not None else (lib.SHOTS_CHARACTER_STRENGTH if args.shots else lib.DEFAULT_CHARACTER_STRENGTH))`.
3. `strengths = lib.panel_strengths(names, stills_members, strength, shots=args.shots)`.
4. `grounded = bool(style)` becomes `grounded = bool(style) or args.shots`.
   - **[interpretation]** The approved "pinned seed grounded mode as today" means every shots still uses the grounded-mode seed rule: `--seed` exactly for every panel, not `--seed + i`. That favours the matching setting and palette that the cuts rely on.
   - Style text is still appended only when Panel 1 has a `Style:` field.
   - The comment above that line gains: `--shots pins the seed the same way (shots spec 5.10).`
   - Pin I20 holds, because it checks the substring `grounded = bool(style)`.
5. **Docstring.** Append: `--shots (bin/ltx-movie --shots) pins every generated panel's seed to --seed and gives every cast character's stills LoRA, alone or paired, its character.json strength or --character-strength (default 0.8).`
6. `--shots` without `--cast` is accepted. It only pins the seed.

Spec 10.6 (S70-S72), verbatim:

| ID | Test | Assertion |
|---|---|---|
| S70 | `--cast "the woman in grey=kyra" --only 1 --shots` (kyra has stills) | the `generate_image` call has `loras == [(stills, 0.8)]`, and `images.json` panel `loras[0]["strength"] == 0.8`. The same without `--shots` → 1.0 (P30 unchanged) |
| S71 | pinned seed | ungrounded story (no Style:), `--only 2,3 --seed 0 --shots` → `manual_seed` called with `0`, `0`. Without `--shots` → `2`, `3` |
| S72 | `--shots` without `--cast` | rc 0. No `loras` kwarg. `images.json` has no `loras` key. Pinned seeds |

Precondition: `git diff --quiet HEAD -- bin/ltx-story-images && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T4.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T4.S1.1 op=append path=tests/test_shots_mode.py


# --- S70-S72: bin/ltx-story-images --shots (spec 5.10) ----------------------------------
class _FakeContentSafetyError(Exception):
    pass


def _fake_zimage_shots(monkeypatch):
    """Fake torch, z_image_skill and content_safety modules in sys.modules (a fresh copy of
    the tests/test_casting_pipeline.py P30 harness). Returns (calls, seeds): the
    (prompt, kwargs) of every generate_image call and every manual_seed(n) value."""
    calls, seeds = [], []

    class _Generator(object):
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            seeds.append(seed)
            return self

    fake_torch = types.ModuleType("torch")
    fake_torch.Generator = _Generator
    fake_zimage = types.ModuleType("z_image_skill")
    fake_zimage.generate_image = lambda prompt, **kwargs: calls.append((prompt, kwargs))
    fake_safety = types.ModuleType("content_safety")
    fake_safety.ContentSafetyError = _FakeContentSafetyError
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "z_image_skill", fake_zimage)
    monkeypatch.setitem(sys.modules, "content_safety", fake_safety)
    return calls, seeds


def _images_story(tmp_path):
    story_md = tmp_path / "story.md"
    story_md.write_text(SHOTS_OK, encoding="utf-8")
    return str(story_md)


def _images_json(out_dir):
    with open(os.path.join(out_dir, "images.json")) as f:
        return json.load(f)


def test_s70_lone_stills_lora_is_0_8_in_shots_mode(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    calls, _seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    stills = os.path.join(lib_dir, "kyra", "lora", "stills.safetensors")
    out_dir = str(tmp_path / "shots")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra", "--shots"]) == 0
    assert len(calls) == 1
    assert calls[0][1]["loras"] == [(stills, 0.8)]
    assert _images_json(out_dir)["panels"][0]["loras"][0]["strength"] == 0.8
    out_dir = str(tmp_path / "chained")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1",
                              "--cast", "the woman in grey=kyra"]) == 0
    assert calls[1][1]["loras"] == [(stills, 1.0)]
    assert _images_json(out_dir)["panels"][0]["loras"][0]["strength"] == 1.0


def test_s71_shots_pins_the_seed(tmp_path, monkeypatch):
    _calls, seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    assert _panels(tmp_path, SHOTS_OK)[0]["style"] == ""
    assert story_images.main(["--story-md", story_md, "--out-dir", str(tmp_path / "a"),
                              "--only", "2,3", "--seed", "0", "--shots"]) == 0
    assert seeds == [0, 0]
    del seeds[:]
    assert story_images.main(["--story-md", story_md, "--out-dir", str(tmp_path / "b"),
                              "--only", "2,3", "--seed", "0"]) == 0
    assert seeds == [2, 3]


def test_s72_shots_without_cast(tmp_path, monkeypatch):
    calls, seeds = _fake_zimage_shots(monkeypatch)
    story_md = _images_story(tmp_path)
    out_dir = str(tmp_path / "images")
    assert story_images.main(["--story-md", story_md, "--out-dir", out_dir, "--only", "1,2",
                              "--seed", "7", "--shots"]) == 0
    assert len(calls) == 2
    assert all("loras" not in kwargs for _prompt, kwargs in calls)
    assert all("loras" not in p for p in _images_json(out_dir)["panels"])
    assert seeds == [7, 7]
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `3 failed, 26 passed, <w> warnings in <t>s`, `rc=1`.

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T4.S3` applies these five edits to `bin/ltx-story-images`.

**Edit 1** (spec 5.10 item 5, the docstring; appended as a new paragraph after the Casting paragraph, Decision 4). Replace this exact text, which occurs exactly once:

````python plan=T4.S3.1 op=replace path=bin/ltx-story-images
process, so the selected panels must all need the same set. character_lib.py is loaded by
path only when --cast is given.
````

with:

````python plan=T4.S3.2 op=with path=bin/ltx-story-images
process, so the selected panels must all need the same set. character_lib.py is loaded by
path only when --cast is given.

--shots (bin/ltx-movie --shots) pins every generated panel's seed to --seed and gives
every cast character's stills LoRA, alone or paired, its character.json strength or
--character-strength (default 0.8).
````

**Edit 2** (spec 5.10 item 1, the argument directly after `--character-strength`). Replace this exact text, which occurs exactly once:

````python plan=T4.S3.3 op=replace path=bin/ltx-story-images
                             "always uses 1.0")
    return parser
````

with:

````python plan=T4.S3.4 op=with path=bin/ltx-story-images
                             "always uses 1.0")
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                        help="shots mode (bin/ltx-movie --shots): every generated panel uses --seed "
                             "exactly (pinned, as in grounded mode), and every cast character's "
                             "stills LoRA, alone or with another, uses its character.json strength "
                             "or --character-strength (default 0.8)")
    return parser
````

**Edit 3** (spec 5.10 item 2, the default strength). Replace this exact text, which occurs exactly once:

````python plan=T4.S3.5 op=replace path=bin/ltx-story-images
        strength = (args.character_strength if args.character_strength is not None
                    else lib.DEFAULT_CHARACTER_STRENGTH)
````

with:

````python plan=T4.S3.6 op=with path=bin/ltx-story-images
        strength = (args.character_strength if args.character_strength is not None
                    else (lib.SHOTS_CHARACTER_STRENGTH if args.shots
                          else lib.DEFAULT_CHARACTER_STRENGTH))
````

**Edit 4** (spec 5.10 item 3). Replace this exact text, which occurs exactly once:

````python plan=T4.S3.7 op=replace path=bin/ltx-story-images
            strengths = lib.panel_strengths(names, stills_members, strength)
````

with:

````python plan=T4.S3.8 op=with path=bin/ltx-story-images
            strengths = lib.panel_strengths(names, stills_members, strength, shots=args.shots)
````

**Edit 5** (spec 5.10 item 4, the pinned seed and its comment line). Replace this exact text, which occurs exactly once:

````python plan=T4.S3.9 op=replace path=bin/ltx-story-images
    # single-panel rerun reproduces the batch exactly.
    style = _style_text(panels)
    grounded = bool(style)
````

with:

````python plan=T4.S3.10 op=with path=bin/ltx-story-images
    # single-panel rerun reproduces the batch exactly.
    # --shots pins the seed the same way (shots spec 5.10).
    style = _style_text(panels)
    grounded = bool(style) or args.shots
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `29 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly); `tests/test_ltx_story_images.py` (I13, I20, I21) is the one this task can break:

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-story-images tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-story-images: --shots pins the seed and uses the shots strength rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 5: `bin/ltx-mlx-render` -- no code; S66 proves it renders a shots manifest

**Files:**
- Test: append to `tests/test_shots_mode.py`
- No production file changes (spec 1.2: "`bin/ltx-mlx-render` needs no change").

**Interfaces:**
- Consumes: Task 3's `--shots` manifest (`S61_STORY`, `_shots_manifest_env`, `_shots_manifest_argv`, `_shots_manifest`); `render.load_manifest`, `render.build_units`, `render.main`.
- Produces: `_ShotsRenderHarness` (used only here).

Spec 10.5 row S66, verbatim:

| S66 | render accepts the shots manifest | the S61 manifest through `render.load_manifest` → ok. `build_units` → every unit `conditioning == "still"`, `chain_source is None`, `image_path ==` that panel's image. The render harness (fresh copy of the P9 `_Harness`) with panel 2's `generate_video` raising `Ltx2MlxError` and `--on-panel-failure skip --retry-failed 0` → panels 1, 3 and 4 render, and the summary has panel 2 `error` (no `chain_broken` stop) |

Precondition: Task 4 is committed (`git log --oneline -1` names it) and `git status --short -- bin/` lists no shots file (nothing in `bin/` is modified).

- [ ] **Step 1: Write the test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T5.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T5.S1.1 op=append path=tests/test_shots_mode.py


# --- S66: bin/ltx-mlx-render renders a shots manifest unchanged (spec 1.2) ---------------
class _ShotsRenderHarness(object):
    """render.main() in-process with generate_video, probe_streams, assert_clips_uniform,
    build_concat_command and clip_frame_count stubbed and the story dir under tmp_path (a
    fresh copy of the tests/test_casting_pipeline.py P9 harness). generate_video raises
    Ltx2MlxError for every panel in fail; every other stub render writes 128 bytes unique to
    that call."""

    def __init__(self, monkeypatch, directory, manifest, fail=()):
        self.dir = str(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.manifest = manifest
        self.received = []
        self.renders = [0]
        self.model = os.path.join(self.dir, "model-fixture")
        os.makedirs(self.model, exist_ok=True)
        with open(os.path.join(self.model, "split_model.json"), "w") as f:
            json.dump({"recipe": "ltx-2.5"}, f)
        self.clips = os.path.join(self.dir, "clips")
        os.makedirs(self.clips, exist_ok=True)
        self.out = os.path.join(self.dir, "movie.mp4")
        fake_bin = os.path.join(self.dir, "fake-ltx")
        with open(fake_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fake_bin, 0o755)
        harness = self

        def _gen(prompt, output_path, image_path=None, **kw):
            harness.renders[0] += 1
            index = int(os.path.basename(output_path)[len("panel_"):-len(".mp4")])
            harness.received.append((index, image_path, kw))
            if index in fail:
                raise SKILL.Ltx2MlxError("stub failure for panel %d" % index, returncode=1)
            with open(output_path, "wb") as f:
                f.write(("render %d" % harness.renders[0]).encode().ljust(128, b"\0"))
            return os.path.abspath(output_path)

        monkeypatch.setattr(render.SKILL, "generate_video", _gen)
        monkeypatch.setattr(render.SKILL, "LTX2_MLX_BIN", fake_bin)
        monkeypatch.setattr(render, "probe_streams", lambda p: {"streams": []})
        monkeypatch.setattr(render, "assert_clips_uniform", lambda pairs, w, h, fr: None)
        monkeypatch.setattr(render, "build_concat_command", lambda lp, out: [
            sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'MOVIE')", out])
        monkeypatch.setattr(render, "clip_frame_count", lambda p: 241)
        monkeypatch.setattr(render, "story_dir_for",
                            lambda sid: os.path.join(harness.dir, "stories", sid))

    def run(self, *extra):
        return render.main([self.manifest, self.out, "--clips-dir", self.clips,
                            "--skip-input-screen", "--model", self.model, "--width", "512",
                            "--height", "512"] + list(extra))

    def newest_summary(self, story_id):
        paths = glob.glob(os.path.join(self.dir, "stories", story_id, "runs", "*",
                                       "story_summary.json"))
        with open(max(paths, key=os.path.getmtime)) as f:
            return json.load(f)


def test_s66_render_accepts_the_shots_manifest(tmp_path, monkeypatch, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_md, images, ws = _shots_manifest_env(tmp_path, monkeypatch, text=S61_STORY)
    assert story_manifest.main(_shots_manifest_argv(
        "cast", story_md, images, "--cast", "the woman in grey=kyra", "--cast", "the ronin=ronin",
        "--character-strength", "0.8")) == 0
    path = os.path.join(ws, "generated", "stories", "cast", "manifest.json")
    manifest = render.load_manifest(path)
    units = render.build_units(manifest["panels"], 0, str(tmp_path / "clips"))
    assert [u["conditioning"] for u in units] == ["still"] * 4
    assert [u["chain_source"] for u in units] == [None] * 4
    assert [u["image_path"] for u in units] == [os.path.abspath(i) for i in images]
    h = _ShotsRenderHarness(monkeypatch, tmp_path / "run", path, fail=(2,))
    assert h.run("--on-panel-failure", "skip", "--retry-failed", "0") == 1
    assert [index for index, _image, _kw in h.received] == [1, 2, 3, 4]
    assert [image for _index, image, _kw in h.received] == [os.path.abspath(i) for i in images]
    summary = h.newest_summary("cast")
    assert [u["status"] for u in summary["units"]] == ["ok", "error", "ok", "ok"]
    assert summary["stopped_reason"] is None
    assert summary["skipped_panels"] == [2]
    assert [os.path.basename(c) for c in summary["clips"]] == [
        "panel_01.mp4", "panel_03.mp4", "panel_04.mp4"]
````

- [ ] **Step 2: Run:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `30 passed, <w> warnings in <t>s`, `rc=0`. S66 passes as soon as it is written: it pins behaviour the render tool already has (Decision 9). No production file changed, so no regression run is needed (`git status --short -- bin/` must list nothing).

- [ ] **Step 3: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-mlx-render: test that a shots manifest renders unchanged (S66)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 6: `bin/ltx-movie` -- `--shots`/`--redo`, `_resolve_shots`, the shots template, `build_story_prompt`, `_resolve_casting`

**Files:**
- Modify: `bin/ltx-movie` (9 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: `character_lib` (Task 2): `SHOTS_CHARACTER_STRENGTH`, `build_cast_block(members, shots=)`.
- Produces (used by Tasks 7-10):
  - CLI flags `--shots` (`args.shots`) and `--redo N[,M...]` (`args.redo`);
  - `_resolve_shots(args) -> 0 | 2`, which always sets `args.redo_panels` (sorted, de-duplicated ints; `[]` without `--redo`);
  - `STORY_PROMPT_TEMPLATE_SHOTS`; `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds, cast_block=None, shots=False)`;
  - `_resolve_casting` sets `args.character_strength` to 0.8 by default in shots mode and `args.cast_block` to the shots Cast block.
- The test section produces the `movie_ws` fixture and `_story_dir_with`, `_movie_args`, `_shots_args`, `_all_files`, `ANCHOR` (Tasks 8-10 reuse them).

Spec 5.1-5.3, verbatim:

#### 5.1 `bin/ltx-movie` arguments and `_resolve_shots`

**Arguments.** Add these two directly after `--list-characters` in `build_parser`. No existing help string changes.

```python
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                         help="shots mode: every panel is its own shot with its own Image: still "
                              "and is rendered from that still (no chaining; cuts between "
                              "panels). Phase 1 uses the shots story template and enforces the "
                              "shot rules (one action per Motion:, at most two cast characters "
                              "per shot), Phase 2 renders a still for every panel, and every "
                              "cast character LoRA defaults to 0.8. See docs/superpowers/specs/"
                              "2026-10-06-shots-mode-design.md.")
    parser.add_argument("--redo", dest="redo", default=None, metavar="N[,M...]",
                         help="with --shots and an existing story.md: move panels N,M...'s "
                              "stills and clips (and movie.mp4) aside into "
                              "<story>/redo/<stamp>/ and re-render only those panels; every "
                              "other panel is reused")
```

**`_resolve_shots(args)`.** Add it after `_resolve_global_loras`. `main` calls it directly after the `--story-prompt-override` file-existence check and **before** `rc = _resolve_casting(args)`, using the same `rc = …; if rc: return rc` pattern.

```python
def _resolve_shots(args):
    """Validate --shots/--redo (shots spec 5.1). Sets args.redo_panels to the sorted, de-duplicated
    panel numbers ([] without --redo). Returns 0, or 2 after one Error: line. Touches nothing."""
    args.redo_panels = []
    if not args.shots:
        if args.redo is not None:
            print("Error: --redo requires --shots", file=sys.stderr)
            return 2
        return 0
    if args.no_stills:
        print("Error: --shots needs Phase 2's per-panel stills; it cannot be combined with "
              "--no-stills", file=sys.stderr)
        return 2
    if getattr(args, "seed_image", None):
        print("Error: --shots is not supported with --seed-image: the seed image can be only "
              "panel 1's still, and the seed-image story preface describes the chained flow",
              file=sys.stderr)
        return 2
    if args.redo is None:
        return 0
    if args.force_story:
        print("Error: --redo cannot be combined with --force-story: --force-story writes a new "
              "story.md, so every panel changes", file=sys.stderr)
        return 2
    if args.story_only:
        print("Error: --redo cannot be combined with --story-only: --story-only stops before the "
              "stills and clips that --redo re-renders", file=sys.stderr)
        return 2
    try:
        panels = sorted({int(x) for x in args.redo.split(",") if x.strip()})
    except ValueError:
        panels = []
    if not panels:
        print("Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; "
              "got %r" % args.redo, file=sys.stderr)
        return 2
    for n in panels:
        if not 1 <= n <= args.panels:
            print("Error: --redo panel %d is out of range (1..%d)" % (n, args.panels),
                  file=sys.stderr)
            return 2
    story_md = _story_paths(args.story_id)["story_md"]
    if not os.path.isfile(story_md):
        print("Error: --redo needs an existing story.md: %s" % story_md, file=sys.stderr)
        return 2
    args.redo_panels = panels
    return 0
```

- The range is checked against `--panels` **[spec choice]**. That is the count the validator enforces (S1), so `--redo` needs the same `--panels` as the original run.
- Duplicates are de-duplicated silently.
- `--shots` with `--story-prompt-override` is allowed **[spec choice]**. The override is used verbatim, as today, and the shot rules and the one rewrite still apply.
- `--shots` without any cast is allowed **[spec choice]**. Only S1 and S3-S5 apply, and there is one stills group.

**`_resolve_casting` (two edits).**

1. The default-strength expression becomes:

```python
    strength = (args.character_strength if args.character_strength is not None
                else (lib.SHOTS_CHARACTER_STRENGTH if getattr(args, "shots", False)
                      else lib.DEFAULT_CHARACTER_STRENGTH))
```

2. `args.cast_block = lib.build_cast_block(members)` becomes `args.cast_block = lib.build_cast_block(members, shots=getattr(args, "shots", False))`.

**Module docstring.** Append this paragraph after the casting paragraph:

> Shots mode (docs/superpowers/specs/2026-10-06-shots-mode-design.md): --shots makes every panel its own shot. Phase 1 uses STORY_PROMPT_TEMPLATE_SHOTS (a Characters list, an Image: field on every panel, one action per Motion:) and enforces the shot rules in character_lib.shots_violations, asking the story model for one rewrite of a draft it wrote in this run; Phase 2 renders a still for every panel, one bin/ltx-story-images run per stills-LoRA group (z_image_skill holds one LoRA set per process); Phase 3 builds a --shots manifest in which every panel is conditioned on its own still; Phase 4 renders independent clips (--on-panel-failure skip). Every cast character LoRA defaults to 0.8, alone or paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into <story>/redo/<stamp>-<pid>/ so that only they re-render.

#### 5.2 `STORY_PROMPT_TEMPLATE_SHOTS` (exact text) and `build_story_prompt`

Place this constant directly after `STORY_PROMPT_TEMPLATE_NO_STILLS`:

```python
STORY_PROMPT_TEMPLATE_SHOTS = """You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

How this movie is made: it is a sequence of separate shots joined by cuts, {seconds} seconds each. Every panel is one shot. Its Image: field is rendered as a single still picture, that picture becomes the shot's first frame, and a {seconds}-second clip is animated from it. Nothing carries over from one shot to the next except what you write, so every Image: field must describe its whole shot. Cuts between panels are expected. Make the cuts read as one scene by stating the continuity in every Image: field: the same setting, the same time of day, lighting and colour palette, and consistent screen direction -- who is on the left and who is on the right, and which way each character faces or moves.

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file starts with a title line, a one-sentence summary and a Characters section, and then has EXACTLY {panels} panel sections, numbered 1 through {panels} in order:

# <title>

<one sentence summarising the story>

## Characters
- "<referring phrase>": <full visual description>

The Characters section has one line per character who appears anywhere in the file, in exactly that format, with the phrase in double quotes. A full visual description covers apparent age group, build, skin tone, hair colour, length and style, and clothing and accessories. Give each character a referring phrase of at most four words built only from details in their description or stated by the narrative, and use that exact phrase for them everywhere else in the file. Never add a colour, garment or trait just to make the phrase.

Every panel has exactly three fields, in this order:

## Panel N — <short title>
Image: <80-170 words describing this shot's first frame as one still picture: every character who is on screen, each named by their referring phrase and then given their full description from the Characters section, word for word; where each one stands and which way they face; the setting and background; the lighting and colour palette; the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up); the camera viewpoint; and the rendering style.>
Motion: <10-25 words: one sentence naming ONE character by their referring phrase and the ONE physical action they perform during these {seconds} seconds, then a separate short sentence about the camera, for example "The camera stays static.">
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

One action per shot. {seconds} seconds is enough for one gesture, a few steps, one swing or one turn of the head -- not for a sequence. The Motion: action sentence gives one character one action: never chain actions with "then", "while", "meanwhile", "simultaneously", "afterwards", "followed by" or ", and", never use a semicolon, and never write a second action sentence. When the story needs a sequence -- for example a charge, a draw and a strike -- give each beat its own panel, so a fight or a chase takes several panels. Do not describe appearance, clothing, setting or lighting in Motion: -- that belongs in Image:.

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from shot to shot and by the narration. Each panel should move the action forward instead of repeating the previous panel's action.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls."""
```

Its only braces are `{story_id}`, `{narrative}`, `{seconds}` and `{panels}` (verified). The anchor `\n\nHow this movie is made:` occurs exactly once, so the existing Cast-block insertion in `build_story_prompt` works unchanged. The template is 642 words.

**`build_story_prompt`.**

- The signature becomes `build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *, seconds, cast_block=None, shots=False)`.
- The template line becomes:

```python
    template = (STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills
                else STORY_PROMPT_TEMPLATE_SHOTS if shots else STORY_PROMPT_TEMPLATE)
```

- Both call sites (`phase1_story`, `_print_dry_run_plan`) add `shots=getattr(args, "shots", False)` after `cast_block=…`.
- With `shots=False`, every call is byte-identical to today (S32, B1).

#### 5.3 Strengths downstream

`_cast_flags(args)` is unchanged. It always forwards `--character-strength <resolved>`, which is `0.8` by default in shots mode. The sub-tools receive `--shots` (5.5, 5.7), which switches the lone-character rule (Section 6).

Spec 7.1, verbatim:

#### 7.1 `bin/ltx-movie` argument errors (exit 2, before any phase, lockfile or GPU work)

| # | Condition | Message |
|---|---|---|
| E-S1 | `--shots` + `--no-stills` | `Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills` |
| E-S2 | `--shots` + `--seed-image` | `Error: --shots is not supported with --seed-image: the seed image can be only panel 1's still, and the seed-image story preface describes the chained flow` |
| E-S3 | `--redo` without `--shots` | `Error: --redo requires --shots` |
| E-S4 | `--redo` value with no int, a non-int, or empty | `Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; got '<v>'` |
| E-S5 | `--redo` panel < 1 or > `--panels` | `Error: --redo panel <n> is out of range (1..<panels>)` |
| E-S6 | `--redo` + `--force-story` | `Error: --redo cannot be combined with --force-story: --force-story writes a new story.md, so every panel changes` |
| E-S7 | `--redo` + `--story-only` | `Error: --redo cannot be combined with --story-only: --story-only stops before the stills and clips that --redo re-renders` |
| E-S8 | `--redo` with no story.md | `Error: --redo needs an existing story.md: <path>` |

Checks run in the order of the 5.1 `_resolve_shots` code: E-S3, E-S1, E-S2, E-S6, E-S7, E-S4, E-S5, E-S8. `_resolve_shots` runs after the existing `main` checks, so the existing `--seed-image` + `--no-stills` error still wins when all three flags are given.

Spec 10.4 rows S30-S34, verbatim:

| ID | Test | Assertion |
|---|---|---|
| S30 | parser | `parse_args(["n", "--story-id", "x"])`: `shots is False`, `redo is None`. `--shots --redo 3,1` → `shots is True`, `redo == "3,1"`. `format_help()` contains `--shots` and `--redo`. The L1 help substrings still hold |
| S31 | `build_story_prompt("N", "sid", 14, seconds="6", shots=True)` | `== STORY_PROMPT_TEMPLATE_SHOTS.format(narrative="N", story_id="sid", panels=14, seconds="6")`. With `cast_block="CAST"`, `"\n\nCAST"` sits immediately before `"\n\nHow this movie is made:"`. The template's brace set is exactly `{story_id, narrative, seconds, panels}`, it has 1 anchor, and it contains `"sequence of separate shots joined by cuts"`, `"## Characters"`, `"10-25 words"`, `"ONE physical action"`, `"never use a semicolon"`, `"EXACTLY {panels} panel sections"` |
| S32 | non-shots identity | `build_story_prompt(…, shots=False)` equals the call without `shots`, for `no_stills` False/True and `seed_image` False/True |
| S33 | `_resolve_shots` | rc 2 with exactly the one 7.1 stderr line, and `redo_panels == []`, for: E-S3; E-S1; E-S2 (seed file exists); E-S4 for `"x"`, `"3.0"`, `""`, `","`; E-S5 for `"0"`, `"15"` with `--panels 14`, `"-1"`; E-S6; E-S7; E-S8 (no story.md). OK: `--shots --redo "3, 1,3"` with story.md present → rc 0, `redo_panels == [1, 3]`. `--shots` alone → rc 0, `[]`. No file is created under `tmp_path` by any case |
| S34 | `_resolve_casting` with `--shots --character kyra`, no story.md | rc 0, `character_strength == 0.8`, `cast_block == build_cast_block(members, shots=True)`. Without `--shots`, `cast_block` is the continuous block (P43 unchanged) |

Precondition: `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T6.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T6.S1.1 op=append path=tests/test_shots_mode.py


# --- S30-S34: bin/ltx-movie arguments, _resolve_shots, the template (spec 5.1-5.3) -------
ANCHOR = "\n\nHow this movie is made:"


@pytest.fixture
def movie_ws(tmp_path, monkeypatch):
    """ltx_movie.WS -> tmp_path/ws (spec 10.1). bin/ and character_lib.py are symlinked to the
    real workspace, so every by-path loader in bin/ltx-movie still reads the real files while
    every story dir lands under tmp_path/ws/generated/stories."""
    ws = tmp_path / "ws"
    (ws / "generated" / "stories").mkdir(parents=True)
    os.symlink(os.path.join(WS, "bin"), str(ws / "bin"))
    os.symlink(os.path.join(WS, "character_lib.py"), str(ws / "character_lib.py"))
    monkeypatch.setattr(ltx_movie, "WS", str(ws))
    return ws


def _story_dir_with(movie_ws, story_id, text=None):
    """<ws>/generated/stories/<story_id>, created, with story.md = text when given."""
    directory = movie_ws / "generated" / "stories" / story_id
    directory.mkdir(parents=True, exist_ok=True)
    if text is not None:
        (directory / "story.md").write_text(text, encoding="utf-8")
    return directory


def _movie_args(*argv):
    args = ltx_movie.build_parser().parse_args(list(argv))
    args.video_width, args.video_height = 704, 448
    return args


def _shots_args(*argv):
    """parse_args, then _resolve_shots and _resolve_casting exactly as main() runs them (both
    must return 0), with main()'s default 704x448 geometry."""
    args = _movie_args(*argv)
    assert ltx_movie._resolve_shots(args) == 0
    assert ltx_movie._resolve_casting(args) == 0
    return args


def _all_files(root):
    return sorted(os.path.join(d, f) for d, _dirs, files in os.walk(str(root)) for f in files)


def test_s30_parser_flags():
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x"])
    assert args.shots is False
    assert args.redo is None
    args = ltx_movie.build_parser().parse_args(["n", "--story-id", "x", "--shots", "--redo", "3,1"])
    assert args.shots is True
    assert args.redo == "3,1"
    helptext = " ".join(ltx_movie.build_parser().format_help().split())
    assert "--shots" in helptext and "--redo" in helptext
    for fragment in ("145 frames @ 24 fps = 6.04s per clip.", "6.04s per panel at the defaults",
                     "number of chained clips; panel 1 also gets the movie's one still image; "
                     "mutually exclusive with --length",
                     "every clip after the first continues from the previous clip's last frame"):
        assert fragment in helptext, fragment


def test_s31_shots_story_prompt():
    template = ltx_movie.STORY_PROMPT_TEMPLATE_SHOTS
    plain = ltx_movie.build_story_prompt("N", "sid", 14, seconds="6", shots=True)
    assert plain == template.format(narrative="N", story_id="sid", panels=14, seconds="6")
    cast = ltx_movie.build_story_prompt("N", "sid", 14, seconds="6", cast_block="CAST", shots=True)
    assert cast == plain.replace(ANCHOR, "\n\nCAST" + ANCHOR)
    assert "\n\nCAST" + ANCHOR in cast
    fields = {f for _text, f, _spec, _conv in string.Formatter().parse(template) if f is not None}
    assert fields == {"story_id", "narrative", "seconds", "panels"}
    assert template.count(ANCHOR) == 1
    for fragment in ("sequence of separate shots joined by cuts", "## Characters", "10-25 words",
                     "ONE physical action", "never use a semicolon",
                     "EXACTLY {panels} panel sections"):
        assert fragment in template, fragment


def test_s32_non_shots_prompts_are_unchanged():
    build = ltx_movie.build_story_prompt
    for no_stills in (False, True):
        for seed_image in (False, True):
            assert build("N", "sid", 14, no_stills, seed_image, seconds="6", shots=False) == build(
                "N", "sid", 14, no_stills, seed_image, seconds="6")
    assert build("N", "sid", 14, seconds="6") == ltx_movie.STORY_PROMPT_TEMPLATE.format(
        narrative="N", story_id="sid", panels=14, seconds="6")


def test_s33_resolve_shots_errors(tmp_path, movie_ws, capsys):
    seed = tmp_path / "seed.png"
    seed.write_bytes(b"png")
    _story_dir_with(movie_ws, "has-story", SHOTS_OK)
    missing = os.path.join(str(movie_ws), "generated", "stories", "no-story", "story.md")
    base = ["n", "--story-id", "has-story", "--panels", "14"]
    malformed = "Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; got %r"
    cases = [
        (base + ["--redo", "3"], "Error: --redo requires --shots"),
        (base + ["--shots", "--no-stills"],
         "Error: --shots needs Phase 2's per-panel stills; it cannot be combined with --no-stills"),
        (base + ["--shots", "--seed-image", str(seed)],
         "Error: --shots is not supported with --seed-image: the seed image can be only panel 1's "
         "still, and the seed-image story preface describes the chained flow"),
        (base + ["--shots", "--redo", "x"], malformed % "x"),
        (base + ["--shots", "--redo", "3.0"], malformed % "3.0"),
        (base + ["--shots", "--redo", ""], malformed % ""),
        (base + ["--shots", "--redo", ","], malformed % ","),
        (base + ["--shots", "--redo", "0"], "Error: --redo panel 0 is out of range (1..14)"),
        (base + ["--shots", "--redo", "15"], "Error: --redo panel 15 is out of range (1..14)"),
        (base + ["--shots", "--redo", "-1"], "Error: --redo panel -1 is out of range (1..14)"),
        (base + ["--shots", "--redo", "2", "--force-story"],
         "Error: --redo cannot be combined with --force-story: --force-story writes a new "
         "story.md, so every panel changes"),
        (base + ["--shots", "--redo", "2", "--story-only"],
         "Error: --redo cannot be combined with --story-only: --story-only stops before the "
         "stills and clips that --redo re-renders"),
        (["n", "--story-id", "no-story", "--panels", "14", "--shots", "--redo", "2"],
         "Error: --redo needs an existing story.md: %s" % missing),
    ]
    before = _all_files(tmp_path)
    for argv, message in cases:
        args = _movie_args(*argv)
        assert ltx_movie._resolve_shots(args) == 2, argv
        assert capsys.readouterr().err == message + "\n", argv
        assert args.redo_panels == []
    args = _movie_args(*(base + ["--shots", "--redo", "3, 1,3"]))
    assert ltx_movie._resolve_shots(args) == 0
    assert args.redo_panels == [1, 3]
    args = _movie_args(*(base + ["--shots"]))
    assert ltx_movie._resolve_shots(args) == 0
    assert args.redo_panels == []
    assert capsys.readouterr().err == ""
    assert _all_files(tmp_path) == before


def test_s34_resolve_casting_in_shots_mode(movie_ws, lib_dir):
    _kyra(lib_dir)
    members = _members("kyra")
    args = _shots_args("n", "--story-id", "new", "--shots", "--character", "kyra")
    assert args.character_strength == 0.8
    assert args.cast_block == character_lib.build_cast_block(members, shots=True)
    assert args.cast_block.endswith("\n" + character_lib.SHOTS_CAST_BLOCK_RULES)
    args = _shots_args("n", "--story-id", "new", "--character", "kyra")
    assert args.cast_block == character_lib.build_cast_block(members)
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `5 failed, 30 passed, <w> warnings in <t>s`, `rc=1`.

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T6.S3` applies these nine edits to `bin/ltx-movie`.

**Edit 1** (spec 5.1, the module docstring paragraph after the casting paragraph). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.1 op=replace path=bin/ltx-movie
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
loaded by path only when casting is used, so an uncast run never reads it.
"""
````

with:

````python plan=T6.S3.2 op=with path=bin/ltx-movie
two or more). Every casting problem exits 2 before any phase runs. character_lib.py is
loaded by path only when casting is used, so an uncast run never reads it.

Shots mode (docs/superpowers/specs/2026-10-06-shots-mode-design.md): --shots makes every
panel its own shot. Phase 1 uses STORY_PROMPT_TEMPLATE_SHOTS (a Characters list, an Image:
field on every panel, one action per Motion:) and enforces the shot rules in
character_lib.shots_violations, asking the story model for one rewrite of a draft it wrote
in this run; Phase 2 renders a still for every panel, one bin/ltx-story-images run per
stills-LoRA group (z_image_skill holds one LoRA set per process); Phase 3 builds a --shots
manifest in which every panel is conditioned on its own still; Phase 4 renders independent
clips (--on-panel-failure skip). Every cast character LoRA defaults to 0.8, alone or
paired. --redo N[,M] moves those panels' stills and clips, and movie.mp4, into
<story>/redo/<stamp>-<pid>/ so that only they re-render.
"""
````

**Edit 2** (spec 5.2, the template directly after `STORY_PROMPT_TEMPLATE_NO_STILLS`). Replace this exact text (the last line of `STORY_PROMPT_TEMPLATE_NO_STILLS` and the blank line after it), which occurs exactly once:

````python plan=T6.S3.3 op=replace path=bin/ltx-movie
Do not emit an Image: or Motion: field. Do not verify the file with run_python or any other tool. Emit no other text."""

````

with:

````python plan=T6.S3.4 op=with path=bin/ltx-movie
Do not emit an Image: or Motion: field. Do not verify the file with run_python or any other tool. Emit no other text."""

STORY_PROMPT_TEMPLATE_SHOTS = """You are authoring the shot list for a short narrated movie (story-id "{story_id}").

Narrative to adapt:
{narrative}

How this movie is made: it is a sequence of separate shots joined by cuts, {seconds} seconds each. Every panel is one shot. Its Image: field is rendered as a single still picture, that picture becomes the shot's first frame, and a {seconds}-second clip is animated from it. Nothing carries over from one shot to the next except what you write, so every Image: field must describe its whole shot. Cuts between panels are expected. Make the cuts read as one scene by stating the continuity in every Image: field: the same setting, the same time of day, lighting and colour palette, and consistent screen direction -- who is on the left and who is on the right, and which way each character faces or moves.

Write the complete story to generated/stories/{story_id}/story.md using the write_file tool. The file starts with a title line, a one-sentence summary and a Characters section, and then has EXACTLY {panels} panel sections, numbered 1 through {panels} in order:

# <title>

<one sentence summarising the story>

## Characters
- "<referring phrase>": <full visual description>

The Characters section has one line per character who appears anywhere in the file, in exactly that format, with the phrase in double quotes. A full visual description covers apparent age group, build, skin tone, hair colour, length and style, and clothing and accessories. Give each character a referring phrase of at most four words built only from details in their description or stated by the narrative, and use that exact phrase for them everywhere else in the file. Never add a colour, garment or trait just to make the phrase.

Every panel has exactly three fields, in this order:

## Panel N — <short title>
Image: <80-170 words describing this shot's first frame as one still picture: every character who is on screen, each named by their referring phrase and then given their full description from the Characters section, word for word; where each one stands and which way they face; the setting and background; the lighting and colour palette; the shot type (exactly one of: extreme wide shot, wide shot, medium shot, medium close-up, close-up, extreme close-up); the camera viewpoint; and the rendering style.>
Motion: <10-25 words: one sentence naming ONE character by their referring phrase and the ONE physical action they perform during these {seconds} seconds, then a separate short sentence about the camera, for example "The camera stays static.">
Narration: <one sentence of voice-over narration; vary the sentence length across panels rather than repeating a similar length every time>

One action per shot. {seconds} seconds is enough for one gesture, a few steps, one swing or one turn of the head -- not for a sequence. The Motion: action sentence gives one character one action: never chain actions with "then", "while", "meanwhile", "simultaneously", "afterwards", "followed by" or ", and", never use a semicolon, and never write a second action sentence. When the story needs a sequence -- for example a charge, a draw and a strike -- give each beat its own panel, so a fight or a chase takes several panels. Do not describe appearance, clothing, setting or lighting in Motion: -- that belongs in Image:.

Give the story a narrative arc -- an introduction, a middle, a climax and a conclusion -- carried by what the characters do from shot to shot and by the narration. Each panel should move the action forward instead of repeating the previous panel's action.

Write the file in a single write_file call. Trust your first draft: do NOT read the file back, do NOT run run_python or any other tool to check it, and do NOT count or recount words. Once the write_file call returns, stop immediately and emit no further text or tool calls."""

````

**Edit 3** (spec 5.2, `build_story_prompt`'s signature and template line). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.5 op=replace path=bin/ltx-movie
def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *,
                       seconds, cast_block=None):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
````

with:

````python plan=T6.S3.6 op=with path=bin/ltx-movie
def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False, *,
                       seconds, cast_block=None, shots=False):
    template = (STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills
                else STORY_PROMPT_TEMPLATE_SHOTS if shots else STORY_PROMPT_TEMPLATE)
````

**Edit 4** (spec 5.1, the two arguments directly after `--list-characters`). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.7 op=replace path=bin/ltx-movie
                              "list) and exit; must be the only argument")
````

with:

````python plan=T6.S3.8 op=with path=bin/ltx-movie
                              "list) and exit; must be the only argument")
    parser.add_argument("--shots", dest="shots", action="store_true", default=False,
                         help="shots mode: every panel is its own shot with its own Image: still "
                              "and is rendered from that still (no chaining; cuts between "
                              "panels). Phase 1 uses the shots story template and enforces the "
                              "shot rules (one action per Motion:, at most two cast characters "
                              "per shot), Phase 2 renders a still for every panel, and every "
                              "cast character LoRA defaults to 0.8. See docs/superpowers/specs/"
                              "2026-10-06-shots-mode-design.md.")
    parser.add_argument("--redo", dest="redo", default=None, metavar="N[,M...]",
                         help="with --shots and an existing story.md: move panels N,M...'s "
                              "stills and clips (and movie.mp4) aside into "
                              "<story>/redo/<stamp>/ and re-render only those panels; every "
                              "other panel is reused")
````

**Edit 5** (spec 5.1, `_resolve_shots` after `_resolve_global_loras`). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.9 op=replace path=bin/ltx-movie
        setattr(args, out_attr, resolved)
    return 0


def _list_characters(raw_argv):
````

with:

````python plan=T6.S3.10 op=with path=bin/ltx-movie
        setattr(args, out_attr, resolved)
    return 0


def _resolve_shots(args):
    """Validate --shots/--redo (shots spec 5.1). Sets args.redo_panels to the sorted, de-duplicated
    panel numbers ([] without --redo). Returns 0, or 2 after one Error: line. Touches nothing."""
    args.redo_panels = []
    if not args.shots:
        if args.redo is not None:
            print("Error: --redo requires --shots", file=sys.stderr)
            return 2
        return 0
    if args.no_stills:
        print("Error: --shots needs Phase 2's per-panel stills; it cannot be combined with "
              "--no-stills", file=sys.stderr)
        return 2
    if getattr(args, "seed_image", None):
        print("Error: --shots is not supported with --seed-image: the seed image can be only "
              "panel 1's still, and the seed-image story preface describes the chained flow",
              file=sys.stderr)
        return 2
    if args.redo is None:
        return 0
    if args.force_story:
        print("Error: --redo cannot be combined with --force-story: --force-story writes a new "
              "story.md, so every panel changes", file=sys.stderr)
        return 2
    if args.story_only:
        print("Error: --redo cannot be combined with --story-only: --story-only stops before the "
              "stills and clips that --redo re-renders", file=sys.stderr)
        return 2
    try:
        panels = sorted({int(x) for x in args.redo.split(",") if x.strip()})
    except ValueError:
        panels = []
    if not panels:
        print("Error: --redo must be a comma-separated list of panel numbers, e.g. 3 or 3,7; "
              "got %r" % args.redo, file=sys.stderr)
        return 2
    for n in panels:
        if not 1 <= n <= args.panels:
            print("Error: --redo panel %d is out of range (1..%d)" % (n, args.panels),
                  file=sys.stderr)
            return 2
    story_md = _story_paths(args.story_id)["story_md"]
    if not os.path.isfile(story_md):
        print("Error: --redo needs an existing story.md: %s" % story_md, file=sys.stderr)
        return 2
    args.redo_panels = panels
    return 0


def _list_characters(raw_argv):
````

**Edit 6** (spec 5.1, `_resolve_casting` edit 1: the default strength). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.11 op=replace path=bin/ltx-movie
    strength = (args.character_strength if args.character_strength is not None
                else lib.DEFAULT_CHARACTER_STRENGTH)
````

with:

````python plan=T6.S3.12 op=with path=bin/ltx-movie
    strength = (args.character_strength if args.character_strength is not None
                else (lib.SHOTS_CHARACTER_STRENGTH if getattr(args, "shots", False)
                      else lib.DEFAULT_CHARACTER_STRENGTH))
````

**Edit 7** (spec 5.1, `_resolve_casting` edit 2: the shots Cast block). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.13 op=replace path=bin/ltx-movie
        args.cast_block = lib.build_cast_block(members)
````

with:

````python plan=T6.S3.14 op=with path=bin/ltx-movie
        args.cast_block = lib.build_cast_block(members, shots=getattr(args, "shots", False))
````

**Edit 8** (spec 5.2, both `build_story_prompt` call sites). Replace this exact text (in `phase1_story`), which occurs exactly once:

````python plan=T6.S3.15 op=replace path=bin/ltx-movie
                                         cast_block=getattr(args, "cast_block", None))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
````

with:

````python plan=T6.S3.16 op=with path=bin/ltx-movie
                                         cast_block=getattr(args, "cast_block", None),
                                         shots=getattr(args, "shots", False))
        with open(os.path.join(_story_dir(args.story_id), "story_prompt.txt"), "w",
````

and replace this exact text (in `_print_dry_run_plan`), which occurs exactly once:

````python plan=T6.S3.17 op=replace path=bin/ltx-movie
                                 cast_block=getattr(args, "cast_block", None))

    print("=== DRY RUN: ltx-movie phase plan (story-id=%s) ===" % args.story_id)
````

with:

````python plan=T6.S3.18 op=with path=bin/ltx-movie
                                 cast_block=getattr(args, "cast_block", None),
                                 shots=getattr(args, "shots", False))

    print("=== DRY RUN: ltx-movie phase plan (story-id=%s) ===" % args.story_id)
````

**Edit 9** (spec 5.1, `main` calls `_resolve_shots` directly before `_resolve_casting`). Replace this exact text, which occurs exactly once:

````python plan=T6.S3.19 op=replace path=bin/ltx-movie
    rc = _resolve_casting(args)
    if rc:
        return rc
````

with:

````python plan=T6.S3.20 op=with path=bin/ltx-movie
    rc = _resolve_shots(args)
    if rc:
        return rc
    rc = _resolve_casting(args)
    if rc:
        return rc
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `35 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: --shots/--redo arguments, the shots story template and the shots Cast block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 7: `bin/ltx-movie` -- extract `_run_story_agent` (refactor checkpoint, behaviour-preserving)

**Files:**
- Modify: `bin/ltx-movie` (2 edits below)
- No test changes: the existing suites are the checkpoint (spec Section 11 item 7: "the `_run_story_agent` extraction **alone first**").

**Interfaces:**
- Produces: `_run_story_agent(cmd, timeout, story_md) -> 0 | 1` (prints the command, waits, applies Phase 1's exit-code rules; returns 0 when story.md may be validated); in `phase1_story`, `authored` is `None` when Phase 1 is skipped and `{"cmd": cmd, "timeout": timeout, "prompt": prompt}` after a successful authoring call. Task 8 reuses both.

Spec 5.4 (a), verbatim:

**(a) Extract `_run_story_agent`** (a refactor, behavior-preserving). Add a module-level function directly above `phase1_story`. Its body is the block of `phase1_story` that runs from the line `print("Running (timeout %ds): %s" % (` through the end of the `if proc.returncode != 0:` block. Move it verbatim, dedented by 4 spaces, with exactly two changes:

1. `len(prompt)` becomes `len(cmd[-1])`. The last element of `cmd` is the prompt, so the output is byte-identical.
2. `return 0` is appended at the end.

```python
def _run_story_agent(cmd, timeout, story_md):
    """Run one bin/qwen-agent story-authoring call: print the command, wait up to timeout
    seconds, and apply Phase 1's exit-code rules. Returns 0 when story.md may be validated
    (including qwen-agent exiting nonzero after writing it), else 1. Moved verbatim out of
    phase1_story so the shots rewrite reuses it (shots spec 5.4)."""
    print("Running (timeout %ds): %s" % (
        timeout, shlex.join(cmd[:-1] + ["--user-prompt", "<%d chars>" % len(cmd[-1])])
    ))
    ... (the moved lines, unchanged, through the final "return 1") ...
    return 0
```

In `phase1_story`:

- add `authored = None` directly after `story_md = paths["story_md"]`;
- replace the moved block with:

```python
        rc = _run_story_agent(cmd, timeout, story_md)
        if rc:
            return rc
        authored = {"cmd": cmd, "timeout": timeout, "prompt": prompt}
```

- directly before `    violations = _validate_story_md(story_md, args.panels, args.no_stills)`, insert:

```python
    if getattr(args, "shots", False):
        return _phase1_shots_finish(args, story_md, authored)
```

The chained path after that line is untouched, so pins L7i, L19 and `:531` hold.

Precondition: Task 6 is committed (`git log --oneline -1` names it) and `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T7.S1` applies these two edits to `bin/ltx-movie`. The function body is `phase1_story`'s former lines from `print("Running (timeout %ds): %s" % (` through the end of the `if proc.returncode != 0:` block, dedented by 4 spaces, with exactly the two spec changes (`len(prompt)` became `len(cmd[-1])`; `return 0` appended). Its comments are moved verbatim (G13: the `--user-prompt --user-prompt` display quirk is kept).

**Edit 1** (the moved block in `phase1_story` becomes the call). Replace this exact text, which occurs exactly once:

````python plan=T7.S1.1 op=replace path=bin/ltx-movie
        print("Running (timeout %ds): %s" % (
            timeout, shlex.join(cmd[:-1] + ["--user-prompt", "<%d chars>" % len(prompt)])
        ))

        proc = subprocess.Popen(cmd, cwd=WS, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            tail = "\n".join((out or "").splitlines()[-40:])
            print("Error: qwen-agent timed out after %ds writing story.md (known hang mode: "
                  "attempting to self-verify, which the prompt forbids); log tail:\n%s"
                  % (timeout, tail), file=sys.stderr)
            return 1
        if "--danger-auto-approve" in cmd:
            # Every tool call qwen-agent ran unconfirmed under this flag traces as
            # [danger-auto]; print the full output (not just the failure-path tail
            # below) regardless of exit code, so that trail actually reaches whatever
            # captures this process's stdout -- a human's terminal, or bin/iterate-story's
            # own per-round log (tiered-approval spec SS1.4.1). Silently discarding it on
            # success would make the audit-trail property that flag's acceptance depends
            # on false exactly when nothing went wrong.
            print(out or "")
        if proc.returncode != 0:
            tail = "\n".join((out or "").splitlines()[-40:])
            if os.path.isfile(story_md):
                # qwen-agent can finish writing story.md and STILL exit
                # nonzero (e.g. it hits its round/tool limit after the
                # write -- observed 2026-08-27, story sisters_sorrow: 30
                # valid panels on disk, rc != 0, and this branch killed the
                # run). The file on disk, validated below, is the evidence
                # that matters; the exit code is not. Same lesson as
                # qwen-serve-guard's restart rc: never trust an exit code
                # over a direct check of the outcome.
                print("Warning: qwen-agent exited %d but story.md exists -- "
                      "validating the file instead of failing. Log tail:\n%s"
                      % (proc.returncode, tail))
            else:
                print("Error: qwen-agent exited %d while authoring story.md\n%s"
                      % (proc.returncode, tail), file=sys.stderr)
                return 1
````

with:

````python plan=T7.S1.2 op=with path=bin/ltx-movie
        rc = _run_story_agent(cmd, timeout, story_md)
        if rc:
            return rc
        authored = {"cmd": cmd, "timeout": timeout, "prompt": prompt}
````

**Edit 2** (`_run_story_agent` directly above `phase1_story`, and `authored = None`). Replace this exact text, which occurs exactly once:

````python plan=T7.S1.3 op=replace path=bin/ltx-movie
# ---------------------------------------------------------------------------
# phase 1: story
# ---------------------------------------------------------------------------

def phase1_story(args):
    paths = _story_paths(args.story_id)
    story_md = paths["story_md"]
````

with:

````python plan=T7.S1.4 op=with path=bin/ltx-movie
# ---------------------------------------------------------------------------
# phase 1: story
# ---------------------------------------------------------------------------

def _run_story_agent(cmd, timeout, story_md):
    """Run one bin/qwen-agent story-authoring call: print the command, wait up to timeout
    seconds, and apply Phase 1's exit-code rules. Returns 0 when story.md may be validated
    (including qwen-agent exiting nonzero after writing it), else 1. Moved verbatim out of
    phase1_story so the shots rewrite reuses it (shots spec 5.4)."""
    print("Running (timeout %ds): %s" % (
        timeout, shlex.join(cmd[:-1] + ["--user-prompt", "<%d chars>" % len(cmd[-1])])
    ))

    proc = subprocess.Popen(cmd, cwd=WS, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        tail = "\n".join((out or "").splitlines()[-40:])
        print("Error: qwen-agent timed out after %ds writing story.md (known hang mode: "
              "attempting to self-verify, which the prompt forbids); log tail:\n%s"
              % (timeout, tail), file=sys.stderr)
        return 1
    if "--danger-auto-approve" in cmd:
        # Every tool call qwen-agent ran unconfirmed under this flag traces as
        # [danger-auto]; print the full output (not just the failure-path tail
        # below) regardless of exit code, so that trail actually reaches whatever
        # captures this process's stdout -- a human's terminal, or bin/iterate-story's
        # own per-round log (tiered-approval spec SS1.4.1). Silently discarding it on
        # success would make the audit-trail property that flag's acceptance depends
        # on false exactly when nothing went wrong.
        print(out or "")
    if proc.returncode != 0:
        tail = "\n".join((out or "").splitlines()[-40:])
        if os.path.isfile(story_md):
            # qwen-agent can finish writing story.md and STILL exit
            # nonzero (e.g. it hits its round/tool limit after the
            # write -- observed 2026-08-27, story sisters_sorrow: 30
            # valid panels on disk, rc != 0, and this branch killed the
            # run). The file on disk, validated below, is the evidence
            # that matters; the exit code is not. Same lesson as
            # qwen-serve-guard's restart rc: never trust an exit code
            # over a direct check of the outcome.
            print("Warning: qwen-agent exited %d but story.md exists -- "
                  "validating the file instead of failing. Log tail:\n%s"
                  % (proc.returncode, tail))
        else:
            print("Error: qwen-agent exited %d while authoring story.md\n%s"
                  % (proc.returncode, tail), file=sys.stderr)
            return 1
    return 0


def phase1_story(args):
    paths = _story_paths(args.story_id)
    story_md = paths["story_md"]
    authored = None
````

- [ ] **Step 2: Run the refactor checkpoint** (run from `WS`):

````bash
python3 tests/test_ltx_movie_offline.py > /tmp/shotsplan-t7-offline.log 2>&1; echo "rc=$? $(tail -1 /tmp/shotsplan-t7-offline.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider; echo "rc=$?"
python3 -m pytest tests/test_casting_regression.py tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"
grep -c 'len(prompt)' bin/ltx-movie
````

Expected: `rc=0 OK 344/344`; `13 passed` then `rc=0`; `38 passed, <w> warnings in <t>s` then `rc=0`; and `0` (grep prints the count 0 and exits 1). `tests/test_ltx_movie_iterate_flags.py` drives `phase1_story` through a fake Popen, including the two `[danger-auto]` trail tests, so it is the behavioural check of the move; the offline suite holds the L12/L19 source pins.

- [ ] **Step 3: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: extract _run_story_agent from phase1_story (no behaviour change)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 8: `bin/ltx-movie` -- shots Phase 1: `_shots_check`, `_phase1_shots_finish`, the one rewrite

**Files:**
- Modify: `bin/ltx-movie` (2 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: Task 2's `shots_violations`, `shots_advisories`, `shots_rewrite_block`, `phrase_occurs`; Task 7's `_run_story_agent` and `authored`; Task 6's `movie_ws`, `_shots_args`, `_story_dir_with`.
- Produces: `_shots_check(lib, story_md, expected_panels, members) -> (violations, advisories)` and `_phase1_shots_finish(args, story_md, authored) -> 0 | 1 | 2`; files `story.rejected-<UTC %Y%m%dT%H%M%SZ>-<pid>.md` and `story_prompt.rewrite.txt`.
- The test section produces `BAD`, `BAD_VIOLATIONS`, `PARAPHRASED`, `_FakeStoryAgent`, `SHOTS_ARGV`, `_phase1_env`, `_rejected`.

Spec 4.1-4.4, verbatim:

#### 4.1 When validation runs

| Situation | Rules | On violations |
|---|---|---|
| `--shots`, Phase 1 wrote story.md in **this** run | S1-S7 (S2, S6, S7 only with cast) | first time: warning (stdout), move the draft aside, one rewrite (5.4). Second time: exit 2 (E-S10) |
| `--shots`, story.md already existed (Phase 1 skipped, including every `--redo` run) | S1-S7 | exit 2, no rewrite (E-S9) **[spec choice]**: the file may hold hand edits, and the story model must never overwrite user data |
| no `--shots` | today's `_validate_story_md` only | unchanged |

#### 4.2 Violation string format

`"story: <rule>: <detail>"` or `"panel <N>: <rule>: <detail>"`. `<N>` is the number in the `## Panel N` header. `<rule>` is one of `S1 panel count`, `S2 characters list`, `S3 fields`, `S4 motion length`, `S5 one action`, `S6 cast count`, `S7 cast and extra`. Each printed line therefore names the panel and the rule (the approved error behavior).

#### 4.3 Rules

| Rule | Check (exact) | Message detail(s) |
|---|---|---|
| S1 | `len(panels) == --panels` | `expected exactly <n> panels, found <m>` |
| S2 (cast only) | `parse_character_roster` (3.5) problems, then each cast phrase is listed (case-insensitive) | `no "## Characters" section` / `line '<…>' is not - "<referring phrase>": <description>` / `<normalize_phrase message>` / `phrase '<p>' is listed more than once` / `the "## Characters" section lists no characters` / `cast phrase '<p>' (character <name>) is not listed` |
| S3 | `Image:`, `Motion:`, `Narration:` non-empty; no `Prompt:` | `missing/empty <Label>: field` / `has a Prompt: field; shots mode expects Image:, Motion: and Narration:` |
| S4 | `10 <= len(motion.split()) <= 25` (the whole field, camera sentence included) | `Motion: is <w> words; it must be 10-25` |
| S5 | (a) exactly 1 non-camera sentence after splitting on `(?<=[.!?])\s+`; (b) no `;`; (c) no `_CHAIN_WORD_RE` match; (d) no `,\s+and\b` | (a) `Motion: has <k> action sentences; it must have exactly one, optionally followed by a camera sentence`; (b) `Motion: contains a semicolon`; (c) `Motion: chains actions with '<word>'` (lowercased, whitespace-collapsed); (d) `Motion: chains actions with ', and'` |
| S6 (cast only) | the cast names found by `cast_text` in `Image:` ∪ `Motion:` number at most 2 | `the shot names <k> cast characters (<names sorted>); at most 2` |
| S7 (cast only) | `find_phrases(Motion:, cast phrases + extra phrases)` must not contain a cast phrase together with an extra phrase | `Motion: names '<cast>'[, …] together with '<extra>'[, …]; show the other character's action in its own shot, then cut to the cast character's reaction` |

#### 4.4 Advisories (never fatal; printed as `Warning: <text>` to stdout)

| ID | Condition | Text |
|---|---|---|
| W1 | a cast phrase occurs in a panel's Image:, and that member's descriptor (whitespace-collapsed, lowercased) is not a substring of the whitespace-collapsed, lowercased Image: | `panel <N>: Image: names '<phrase>' but does not repeat character <name>'s Cast description word for word; that still relies on the phrase and the stills LoRA alone` |
| W2 | the shot names a cast character (Image: ∪ Motion:), and its Image: has no `_SHOT_TYPE_RE` match, or any match is not in `SHOTS_CLOSE_SHOT_TYPES` | `panel <N>: shows cast character(s) <names> but its Image: shot type is <types or "not stated">; a shot with a cast character should be a medium shot or closer` |


Spec 5.4 (b), verbatim:

**(b) `_shots_check` and `_phase1_shots_finish`.**

```python
def _shots_check(lib, story_md, expected_panels, members):
    """(violations, advisories) for a shots-mode story.md (shots spec 4)."""
    try:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return ["story: cannot read story.md: %s" % e], []
    panels = _load_story_panels(story_md)
    return (lib.shots_violations(text, panels, expected_panels, members),
            lib.shots_advisories(panels, members))


def _phase1_shots_finish(args, story_md, authored):
    """Shots-mode Phase 1 after story.md exists (shots spec 5.4): validate; a draft the story
    model wrote in this run gets exactly one rewrite; then the story dump, the advisories, the
    cast-phrase warnings and the review gate. authored is None when Phase 1 was skipped."""
    lib = _character_lib()
    members = getattr(args, "cast_members", None) or []
    violations, advisories = _shots_check(lib, story_md, args.panels, members)
    if violations and authored is None:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to have "
              "the story model write a new one." % story_md, file=sys.stderr)
        return 2
    if violations:
        story_dir = os.path.dirname(story_md)
        rejected = os.path.join(story_dir, "story.rejected-%s-%d.md"
                                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
        print("Warning: the story model's draft broke the shot rules; moving it to %s and asking "
              "for one rewrite:" % rejected)
        for v in violations:
            print("  - %s" % v)
        os.replace(story_md, rejected)
        rewrite = authored["prompt"] + "\n\n" + lib.shots_rewrite_block(violations, args.panels)
        with open(os.path.join(story_dir, "story_prompt.rewrite.txt"), "w", encoding="utf-8") as f:
            f.write(rewrite)
        cmd = list(authored["cmd"])
        cmd[-1] = rewrite
        print("=== Phase 1: story (rewrite) ===")
        rc = _run_story_agent(cmd, authored["timeout"], story_md)
        if rc:
            print("Error: the shots rewrite failed; the rejected first draft is kept at %s"
                  % rejected, file=sys.stderr)
            return rc
        violations, advisories = _shots_check(lib, story_md, args.panels, members)
        if violations:
            print("Error: story.md still breaks the shot rules after one rewrite:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("The rejected first draft is kept at %s. Hand-edit %s to fix the violations "
                  "above and rerun (Phase 1 is skipped while story.md exists), or rerun with "
                  "--force-story." % (rejected, story_md), file=sys.stderr)
            return 2
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)
    for a in advisories:
        print("Warning: %s" % a)
    if members:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    for m in members:
        if not lib.phrase_occurs(text, m.phrase):
            print("Warning: story.md does not use cast phrase %r; character %s gets no LoRA in "
                  "this story" % (m.phrase, m.name))
    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")
    return 0
```

Why it works this way:

- **The draft is moved aside, never overwritten or deleted [spec choice].** Two reasons:
  1. It keeps the rejected draft for diagnosis.
  2. It makes the rewrite's `write_file` a **new** file, which qwen-agent auto-approves (0.2), so an unattended `--no-review` run never hangs on an overwrite prompt.
- The name carries a UTC stamp and the pid, so no earlier rejected draft is ever replaced.
- The rewrite reuses Phase 1's `cmd` object, with only the prompt replaced. `--max-tokens` and the timeout are the same, and the source-count pins hold.
- `story_prompt.rewrite.txt` is the audit record of the second prompt. `story_prompt.txt` keeps the first prompt, unchanged.

Spec 7.2 rows E-S9 to E-S11 and E-S14, verbatim:

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-S9 | ltx-movie | `--shots`, story.md pre-existed, S-violations | 2. `Error: story.md breaks the shot rules:` plus one `  - <violation>` line each, plus the hand-edit hint (5.4). No file changes |
| E-S10 | ltx-movie | first draft (this run) violates | `Warning:` plus the list (stdout); the draft moves to `story.rejected-<stamp>-<pid>.md`; one rewrite. If the rewrite also violates: 2, with `Error: story.md still breaks the shot rules after one rewrite:`, the list, and the kept-draft hint |
| E-S11 | ltx-movie | qwen-agent fails during the rewrite (rc 1 path: timeout, or nonzero with no story.md) | 1. The existing qwen-agent error, then `Error: the shots rewrite failed; the rejected first draft is kept at <path>` |
| E-S14 | ltx-movie | W1/W2 advisories | `Warning: <text>` (stdout), continues |

Spec 10.4 rows S35-S41, verbatim:

| ID | Test | Assertion |
|---|---|---|
| S35 | Phase 1, valid first draft | fake qwen-agent queue `[SHOTS_OK]`, `--shots --character kyra --character ronin --panels 3 --no-review` → rc 0. Popen called once. No `story.rejected-*` file. stdout has no `"has an Image: field, which is ignored"` |
| S36 | Phase 1, one rewrite | queue `[BAD, SHOTS_OK]`, where `BAD` = `SHOTS_OK` with panel 2's Motion: replaced by `"The bearded robber lunges then slashes."` → rc 0. Popen called twice. At the 2nd call story.md did not exist. The 2nd `cmd[-1] == first_cmd[-1] + "\n\n" + character_lib.shots_rewrite_block(viol, 3)`, where `viol == ["panel 2: S4 motion length: Motion: is 6 words; it must be 10-25", "panel 2: S5 one action: Motion: chains actions with 'then'"]`. Exactly one `story.rejected-*.md`, byte-identical to `BAD`. `story_prompt.rewrite.txt == second cmd[-1]`. `story_prompt.txt` holds the first prompt. stdout lists both violations under the `Warning:` line. All `cmd` elements except the last are equal between the two calls |
| S37 | Phase 1, second failure | queue `[BAD, BAD]` → rc 2. Popen exactly twice. stderr has `"Error: story.md still breaks the shot rules after one rewrite:"`, both `  - panel 2: …` lines, and the rejected path. story.md (the second `BAD`) is still in place |
| S38 | Phase 1 skipped, story.md pre-exists as `BAD` | rc 2. Popen never called. story.md byte-unchanged. No rejected file. stderr starts `"Error: story.md breaks the shot rules:"` and contains `"pass --force-story"` |
| S39 | rewrite agent failure | queue `[BAD, None]`, with the 2nd returncode 1 → rc 1. stderr has the existing `"Error: qwen-agent exited 1 while authoring story.md"` and `"Error: the shots rewrite failed; the rejected first draft is kept at "`. The rejected file exists |
| S40 | advisories are not fatal | queue `[SHOTS_OK with the S18 paraphrase]` → rc 0. stdout contains `"Warning: panel 1: Image: names 'the woman in grey' but does not repeat"` |
| S41 | continuous mode unaffected | no `--shots`, story.md = a 2-panel chained story (panel 1 with Image:/Motion:/Narration:, panel 2 with Motion:/Narration:) whose panel 2 Motion: is `"She draws then strikes; then he falls."` → `phase1_story` rc 0 (only `_validate_story_md` applies) |

Precondition: Task 7 is committed and `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T8.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T8.S1.1 op=append path=tests/test_shots_mode.py


# --- S35-S41: shots-mode Phase 1 and the one rewrite (spec 5.4) --------------------------
BAD = _variant("Motion: The bearded robber lunges forward out of the ferns with his short knife "
               "raised. The camera stays static.", "Motion: The bearded robber lunges then slashes.")
BAD_VIOLATIONS = ["panel 2: S4 motion length: Motion: is 6 words; it must be 10-25",
                  "panel 2: S5 one action: Motion: chains actions with 'then'"]
PARAPHRASED = _variant("grey kimono, standing in the centre", "grey robe, standing in the centre")
SHOTS_ARGV = ["n", "--story-id", "shots", "--shots", "--character", "kyra", "--character",
              "ronin", "--panels", "3", "--no-review"]


class _FakeStoryAgent(object):
    """subprocess.Popen stand-in for bin/qwen-agent (spec 10.1): records each cmd and whether
    story.md existed at call time, writes the next queued story text to story.md (None writes
    nothing), and exits with the next queued return code (default 0). An unexpected extra
    call pops an empty queue and raises IndexError."""

    def __init__(self, monkeypatch, story_md, stories, returncodes=()):
        self.story_md = story_md
        self.stories = list(stories)
        self.returncodes = list(returncodes)
        self.calls = []
        monkeypatch.setattr(ltx_movie.subprocess, "Popen", self)

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), "existed": os.path.exists(self.story_md)})
        text = self.stories.pop(0)
        if text is not None:
            with open(self.story_md, "w", encoding="utf-8") as f:
                f.write(text)
        proc = types.SimpleNamespace(
            returncode=self.returncodes.pop(0) if self.returncodes else 0,
            communicate=lambda timeout=None: ("", None))
        return proc


def _phase1_env(movie_ws, lib_dir, story=None):
    """kyra and ronin in the library and the story dir "shots" (with story.md = story when
    given). Returns (story dir, story.md path)."""
    _kyra(lib_dir)
    _ronin(lib_dir)
    directory = _story_dir_with(movie_ws, "shots", story)
    return directory, str(directory / "story.md")


def _rejected(directory):
    return sorted(glob.glob(os.path.join(str(directory), "story.rejected-*.md")))


def test_s35_valid_first_draft(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert _rejected(directory) == []
    assert "has an Image: field, which is ignored" not in capsys.readouterr().out


def test_s36_one_rewrite(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, SHOTS_OK])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    out = capsys.readouterr().out
    assert len(agent.calls) == 2
    first, second = agent.calls[0]["cmd"], agent.calls[1]["cmd"]
    assert agent.calls[1]["existed"] is False
    assert second[-1] == first[-1] + "\n\n" + character_lib.shots_rewrite_block(BAD_VIOLATIONS, 3)
    assert second[:-1] == first[:-1]
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert re.fullmatch(r"story\.rejected-\d{8}T\d{6}Z-%d\.md" % os.getpid(),
                        os.path.basename(rejected[0]))
    with open(rejected[0], encoding="utf-8") as f:
        assert f.read() == BAD
    assert (directory / "story_prompt.rewrite.txt").read_text(encoding="utf-8") == second[-1]
    assert (directory / "story_prompt.txt").read_text(encoding="utf-8") == first[-1]
    lines = out.splitlines()
    warning = next(i for i, line in enumerate(lines)
                   if line.startswith("Warning: the story model's draft broke the shot rules; "
                                      "moving it to %s and asking for one rewrite:" % rejected[0]))
    assert lines[warning + 1:warning + 3] == ["  - " + v for v in BAD_VIOLATIONS]


def test_s37_second_failure_exits_2(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, BAD])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: story.md still breaks the shot rules after one rewrite:" in err
    for v in BAD_VIOLATIONS:
        assert "  - " + v in err.splitlines()
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert rejected[0] in err
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == BAD


def test_s38_existing_story_is_never_rewritten(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir, story=BAD)
    agent = _FakeStoryAgent(monkeypatch, story_md, [])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 2
    err = capsys.readouterr().err
    assert agent.calls == []
    with open(story_md, encoding="utf-8") as f:
        assert f.read() == BAD
    assert _rejected(directory) == []
    assert err.startswith("Error: story.md breaks the shot rules:\n")
    assert "pass --force-story" in err


def test_s39_rewrite_agent_failure(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [BAD, None], returncodes=[0, 1])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 1
    err = capsys.readouterr().err
    assert len(agent.calls) == 2
    assert "Error: qwen-agent exited 1 while authoring story.md" in err
    assert "Error: the shots rewrite failed; the rejected first draft is kept at " in err
    rejected = _rejected(directory)
    assert len(rejected) == 1
    assert os.path.isfile(rejected[0])


def test_s40_advisories_are_not_fatal(monkeypatch, movie_ws, lib_dir, capsys):
    directory, story_md = _phase1_env(movie_ws, lib_dir)
    agent = _FakeStoryAgent(monkeypatch, story_md, [PARAPHRASED])
    assert ltx_movie.phase1_story(_shots_args(*SHOTS_ARGV)) == 0
    assert len(agent.calls) == 1
    assert ("Warning: panel 1: Image: names 'the woman in grey' but does not repeat"
            in capsys.readouterr().out)


CHAINED_STORY = """# Chained

A continuous take.

## Panel 1 — One
Image: A medium shot of a woman standing on a forest trail and facing right.
Motion: She turns her head slowly toward the trees.
Narration: She listens.

## Panel 2 — Two
Motion: She draws then strikes; then he falls.
Narration: It is over.
"""


def test_s41_continuous_mode_unaffected(monkeypatch, movie_ws):
    directory = _story_dir_with(movie_ws, "chained", CHAINED_STORY)
    agent = _FakeStoryAgent(monkeypatch, str(directory / "story.md"), [])
    args = _shots_args("n", "--story-id", "chained", "--panels", "2", "--no-review")
    assert ltx_movie.phase1_story(args) == 0
    assert agent.calls == []
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `6 failed, 36 passed, <w> warnings in <t>s`, `rc=1`. S41 passes before the implementation: it pins the unchanged continuous path (a guard).

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T8.S3` applies these two edits to `bin/ltx-movie`.

**Edit 1** (spec 5.4 (a), the shots branch directly before `_validate_story_md`). Replace this exact text, which occurs exactly once:

````python plan=T8.S3.1 op=replace path=bin/ltx-movie
    violations = _validate_story_md(story_md, args.panels, args.no_stills)
````

with:

````python plan=T8.S3.2 op=with path=bin/ltx-movie
    if getattr(args, "shots", False):
        return _phase1_shots_finish(args, story_md, authored)

    violations = _validate_story_md(story_md, args.panels, args.no_stills)
````

**Edit 2** (spec 5.4 (b), `_shots_check` and `_phase1_shots_finish`, directly after `phase1_story`; Decision 6). Replace this exact text, which occurs exactly once:

````python plan=T8.S3.3 op=replace path=bin/ltx-movie
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")

    return 0


# ---------------------------------------------------------------------------
# phase 2: stills
````

with:

````python plan=T8.S3.4 op=with path=bin/ltx-movie
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")

    return 0


def _shots_check(lib, story_md, expected_panels, members):
    """(violations, advisories) for a shots-mode story.md (shots spec 4)."""
    try:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return ["story: cannot read story.md: %s" % e], []
    panels = _load_story_panels(story_md)
    return (lib.shots_violations(text, panels, expected_panels, members),
            lib.shots_advisories(panels, members))


def _phase1_shots_finish(args, story_md, authored):
    """Shots-mode Phase 1 after story.md exists (shots spec 5.4): validate; a draft the story
    model wrote in this run gets exactly one rewrite; then the story dump, the advisories, the
    cast-phrase warnings and the review gate. authored is None when Phase 1 was skipped."""
    lib = _character_lib()
    members = getattr(args, "cast_members", None) or []
    violations, advisories = _shots_check(lib, story_md, args.panels, members)
    if violations and authored is None:
        print("Error: story.md breaks the shot rules:", file=sys.stderr)
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        print("Hand-edit %s to fix the violations above and rerun, or pass --force-story to have "
              "the story model write a new one." % story_md, file=sys.stderr)
        return 2
    if violations:
        story_dir = os.path.dirname(story_md)
        rejected = os.path.join(story_dir, "story.rejected-%s-%d.md"
                                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
        print("Warning: the story model's draft broke the shot rules; moving it to %s and asking "
              "for one rewrite:" % rejected)
        for v in violations:
            print("  - %s" % v)
        os.replace(story_md, rejected)
        rewrite = authored["prompt"] + "\n\n" + lib.shots_rewrite_block(violations, args.panels)
        with open(os.path.join(story_dir, "story_prompt.rewrite.txt"), "w", encoding="utf-8") as f:
            f.write(rewrite)
        cmd = list(authored["cmd"])
        cmd[-1] = rewrite
        print("=== Phase 1: story (rewrite) ===")
        rc = _run_story_agent(cmd, authored["timeout"], story_md)
        if rc:
            print("Error: the shots rewrite failed; the rejected first draft is kept at %s"
                  % rejected, file=sys.stderr)
            return rc
        violations, advisories = _shots_check(lib, story_md, args.panels, members)
        if violations:
            print("Error: story.md still breaks the shot rules after one rewrite:", file=sys.stderr)
            for v in violations:
                print("  - %s" % v, file=sys.stderr)
            print("The rejected first draft is kept at %s. Hand-edit %s to fix the violations "
                  "above and rerun (Phase 1 is skipped while story.md exists), or rerun with "
                  "--force-story." % (rejected, story_md), file=sys.stderr)
            return 2
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)
    for a in advisories:
        print("Warning: %s" % a)
    if members:
        with open(story_md, encoding="utf-8") as f:
            text = f.read()
    for m in members:
        if not lib.phrase_occurs(text, m.phrase):
            print("Warning: story.md does not use cast phrase %r; character %s gets no LoRA in "
                  "this story" % (m.phrase, m.name))
    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")
    return 0


# ---------------------------------------------------------------------------
# phase 2: stills
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `42 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: shots-mode Phase 1 validation and the one rewrite

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 9: `bin/ltx-movie` -- shots Phase 2: stills groups, one `bin/ltx-story-images` run per LoRA set

**Files:**
- Modify: `bin/ltx-movie` (2 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: Task 4's `bin/ltx-story-images --shots` (`_style_text`, `_compose_prompt`, loaded by path); Task 2's `cast_text(..., insert=)`; `_stream_and_tee`, `_load_story_panels`, `_story_paths`, `_cast_flags` (existing).
- Produces: `_panel_list(panels) -> "1,5"`, `_shots_stills_groups(story_md_path, members) -> [(names, [panel numbers])]`, `_shots_missing_stills(args, panels) -> [panel]`, `_phase2_shots(args, cmd) -> 0 | 1`; files `images/stills-group-<KK>.log`. Task 10's dry run reuses `_panel_list`, `_shots_stills_groups` and `_shots_missing_stills`.
- The test section produces `GROUP_STORY`, `_StillsRunner`, `_group_args`, `_plain_phase2_cmd`, `_stills_path`.

Spec 5.5, verbatim:

#### 5.5 Phase 2: stills groups

**Grouping.**

```python
def _panel_list(panels):
    return ",".join(str(i) for i in panels)


def _shots_stills_groups(story_md_path, members):
    """[(names, [panel numbers])]: shots-mode panels grouped by the cast characters whose stills
    LoRAs bin/ltx-story-images will load for them -- the same _compose_prompt(Image:, Style:) +
    cast_text(insert=members with a stills LoRA) match it performs, so every group is one LoRA
    set (shots spec 5.5). Sorted by (len(names), names); panels ascending, 1-based by position.
    Uncast: one group of every panel."""
    panels = _load_story_panels(story_md_path)
    by_panel = {i: () for i in range(1, len(panels) + 1)}
    if members:
        lib = _character_lib()
        images = importlib.machinery.SourceFileLoader(
            "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
        style = images._style_text(panels)
        insert = {m.name for m in members if m.stills_lora}
        for i, p in enumerate(panels, start=1):
            by_panel[i] = tuple(lib.cast_text(images._compose_prompt(p["image"], style), members,
                                              insert=insert)[1])
    groups = {}
    for i, names in sorted(by_panel.items()):
        groups.setdefault(names, []).append(i)
    return sorted(groups.items(), key=lambda g: (len(g[0]), g[0]))


def _shots_missing_stills(args, panels):
    """The panels of one group whose still must be generated: those being redone, and those
    with no images/panel_NN.png."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]
```

Two facts make "one group = one LoRA set" hold, so E-P16 can never fire on a group:

- the global stills LoRAs are identical for every panel;
- the shots strength rule (Section 6) depends only on the character, not on how many are present.

**`phase2_stills` edit.** Directly after `    cmd += _cast_flags(args)`, insert:

```python
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
```

So the existing command construction, which carries the `["--lora", args.stills_lora_path]` literal (pin L1z5), is reused. The E-P11 panel-1 warning is not printed in shots mode, because stills are reused by existence and `--redo` is the regeneration mechanism.

```python
def _phase2_shots(args, cmd):
    """Phase 2 in shots mode (shots spec 5.5): one bin/ltx-story-images run per stills-LoRA group,
    each the Phase 2 cmd with --only <the group's panels> and --shots appended, teed to
    images/stills-group-KK.log. A group with no missing still is skipped. Stops at the first
    failing group; stills already written are kept."""
    paths = _story_paths(args.story_id)
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [])
    os.makedirs(paths["images_dir"], exist_ok=True)
    for k, (names, panels) in enumerate(groups, start=1):
        label = "%s; panels %s" % (", ".join(names) or "no character LoRAs", _panel_list(panels))
        if not _shots_missing_stills(args, panels):
            print("stills group %d/%d (%s): every still exists; skipped" % (k, len(groups), label))
            continue
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        log_path = os.path.join(paths["images_dir"], "stills-group-%02d.log" % k)
        print("stills group %d/%d (%s); log: %s" % (k, len(groups), label, log_path))
        print("Running: %s" % shlex.join(group_cmd))
        rc = _stream_and_tee(group_cmd, log_path)
        if rc != 0:
            print("Error: ltx-story-images exited %d for stills group %d/%d (%s); log: %s. "
                  "Stills already written are kept; rerun the same command to continue -- every "
                  "existing panel_NN.png is reused." % (rc, k, len(groups), label, log_path),
                  file=sys.stderr)
            return 1
    return 0
```

- `--only` lists the whole group, not only its missing panels **[spec choice]**. bin/ltx-story-images skips existing stills itself, and the log shows the full group.
- **Skipping a fully rendered group [spec choice]** avoids a process start plus the torch import, and leaves `images.json` as it was.
- Seeds come from bin/ltx-story-images `--shots` (5.7): every still uses `--image-seed` exactly.
- Group order is by size, then by names: `()`, then single characters alphabetically, then pairs. For the rescue cast that is at most 4 groups: `()`, `(kyra,)`, `(ronin,)`, `(kyra, ronin)`.

Spec 7.2 row E-S12, verbatim:

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-S12 | ltx-movie | a stills group exits nonzero | 1. `Error: ltx-story-images exited <rc> for stills group <k>/<n> (<names or "no character LoRAs">; panels <list>); log: <story>/images/stills-group-<KK>.log. Stills already written are kept; rerun the same command to continue -- every existing panel_NN.png is reused.` Later groups are not run |

Spec 10.4 rows S42-S45, verbatim:

| ID | Test | Assertion |
|---|---|---|
| S42 | `_shots_stills_groups` | a 5-panel story whose Image: fields name {kyra}, {ronin}, {kyra, ronin}, {}, {kyra}, with both members having stills → `[((), [4]), (("kyra",), [1, 5]), (("ronin",), [2]), (("kyra", "ronin"), [3])]`. Uncast → `[((), [1, 2, 3, 4, 5])]`. Ronin without a stills LoRA → ronin names drop: `[((), [2, 4]), (("kyra",), [1, 3, 5])]`. A nested phrase (cast `"the woman"` without stills, and kyra `"the woman in grey"` with stills, Image: `"the woman in grey"`) → `(("kyra",), …)` (the I3 rule). Motion:-only mentions do not affect groups |
| S43 | `phase2_stills` shots | the S42 story (all stills absent), fake stills runner (rc 0 each) → rc 0. Exactly 4 runs, in S42 group order. Each `cmd` equals the non-shots Phase 2 `cmd` (built by the same args) with the `--only` value replaced by `"4"`, `"1,5"`, `"2"`, `"3"` (the S42 group lists, in that order) and `"--shots"` as the last element, after the `--cast …` and `--character-strength 0.8` flags. `log_path`s are `images/stills-group-01.log` … `-04.log`. Rerun with every still present → 0 runs, and 4 `"every still exists; skipped"` lines. With only panel 2's still absent → exactly 1 run (group `ronin`) |
| S44 | stills group failure | runner rc queue `[0, 1]` → rc 1. Exactly 2 runs (the third group not run). stderr has `"for stills group 2/4"`, `"stills-group-02.log"` and `"rerun the same command to continue"`. Group 1's PNGs still exist |
| S45 | one LoRA set per process, end to end | for each S43-recorded group `cmd` (S42 story; members with stills), call `story_images.main(cmd[2:])` under the fake Z-Image modules → each rc 0 (E-P16 never fires). Every `generate_image` call in a group has `loras == [(stills_path(n), 0.8) for n in group names]` (sorted by name), or no `loras` key for the `()` group |

Precondition: Task 8 is committed and `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T9.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T9.S1.1 op=append path=tests/test_shots_mode.py


# --- S42-S45: shots-mode Phase 2 stills groups (spec 5.5) ---------------------------------
GROUP_STORY = """# Groups

Five shots on a forest trail.

## Characters
- "the woman in grey": %s
- "the ronin": %s

## Panel 1 — One
Image: A medium shot of the woman in grey standing on the mossy trail.
Motion: The woman in grey turns her head slowly toward the ferns on her right.
Narration: One.

## Panel 2 — Two
Image: A medium shot of the ronin standing under a tall cedar.
Motion: The ronin turns his head slowly toward the ferns on his left side.
Narration: Two.

## Panel 3 — Three
Image: A medium shot of the woman in grey and the ronin standing apart on the trail.
Motion: The ronin offers his open hand to the woman in grey on the trail.
Narration: Three.

## Panel 4 — Four
Image: A wide shot of the empty mossy trail under grey clouds.
Motion: The ronin walks slowly along the empty trail toward the distant shrine.
Narration: Four.

## Panel 5 — Five
Image: A close-up of the woman in grey under the cedars.
Motion: The woman in grey closes her eyes slowly and lowers her chin a little.
Narration: Five.
""" % (DESC_K, DESC_R)
GROUPS = [((), [4]), (("kyra",), [1, 5]), (("ronin",), [2]), (("kyra", "ronin"), [3])]


class _StillsRunner(object):
    """ltx_movie._stream_and_tee stand-in (spec 10.1): records (cmd, log_path), writes a 1x1
    PNG for every --only panel when the queued rc is 0 and write_pngs is true, and returns
    the next queued rc (default 0). It also makes any real subprocess call from bin/ltx-movie
    fail the test, so no Z-Image process can ever start."""

    def __init__(self, monkeypatch, returncodes=(), write_pngs=True):
        self.returncodes = list(returncodes)
        self.write_pngs = write_pngs
        self.runs = []

        def _forbidden(*args, **kwargs):
            raise AssertionError("Phase 2 made a real subprocess call")

        monkeypatch.setattr(ltx_movie.subprocess, "run", _forbidden)
        monkeypatch.setattr(ltx_movie.subprocess, "Popen", _forbidden)
        monkeypatch.setattr(ltx_movie, "_stream_and_tee", self)

    def __call__(self, cmd, log_path):
        from PIL import Image
        self.runs.append((list(cmd), log_path))
        rc = self.returncodes.pop(0) if self.returncodes else 0
        if rc == 0 and self.write_pngs:
            out_dir = cmd[cmd.index("--out-dir") + 1]
            os.makedirs(out_dir, exist_ok=True)
            for i in cmd[cmd.index("--only") + 1].split(","):
                Image.new("RGB", (1, 1), (0, 0, 0)).save(
                    os.path.join(out_dir, "panel_%02d.png" % int(i)))
        return rc


def _group_args(movie_ws, lib_dir, story_id="groups"):
    """kyra and ronin (both with stills LoRAs), the GROUP_STORY story dir, and resolved args for
    --shots --character kyra --character ronin --panels 5."""
    _kyra(lib_dir)
    _ronin(lib_dir)
    _story_dir_with(movie_ws, story_id, GROUP_STORY)
    return _shots_args("n", "--story-id", story_id, "--shots", "--character", "kyra",
                       "--character", "ronin", "--panels", "5", "--no-review")


def _plain_phase2_cmd(monkeypatch, args):
    """The non-shots Phase 2 command for the same args (spec S43), recorded from
    phase2_stills with args.shots False and subprocess.run stubbed."""
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0))
    args.shots = False
    try:
        assert ltx_movie.phase2_stills(args) == 0
    finally:
        args.shots = True
    assert len(runs) == 1
    return runs[0]


def _stills_path(lib_dir, name):
    return os.path.join(lib_dir, name, "lora", "stills.safetensors")


def test_s42_stills_groups(tmp_path, movie_ws, lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story = _story_dir_with(movie_ws, "groups", GROUP_STORY) / "story.md"
    assert ltx_movie._shots_stills_groups(str(story), _members("kyra", "ronin")) == GROUPS
    assert ltx_movie._shots_stills_groups(str(story), []) == [((), [1, 2, 3, 4, 5])]
    _ronin(lib_dir, stills=False)
    assert ltx_movie._shots_stills_groups(str(story), _members("kyra", "ronin")) == [
        ((), [2, 4]), (("kyra",), [1, 3, 5])]
    make_character(lib_dir, "mira", "miragrl", "the woman", "girl",
                   "an old woman with grey hair in a straw hat and a brown travelling cloak",
                   stills=False)
    nested = _story_dir_with(movie_ws, "nested", (
        "# Nested\n\nTwo shots.\n\n## Panel 1 — One\nImage: A medium shot of the woman in grey.\n"
        "Motion: The woman in grey turns her head slowly toward the ferns on her right.\n"
        "Narration: One.\n\n## Panel 2 — Two\nImage: A medium shot of the woman.\n"
        "Motion: The woman turns her head slowly toward the ferns on her right side.\n"
        "Narration: Two.\n")) / "story.md"
    assert ltx_movie._shots_stills_groups(str(nested), _members("kyra", "mira")) == [
        ((), [2]), (("kyra",), [1])]


def test_s43_phase2_runs_one_process_per_group(monkeypatch, movie_ws, lib_dir, capsys):
    args = _group_args(movie_ws, lib_dir)
    base = _plain_phase2_cmd(monkeypatch, args)
    assert base[-4:] == ["--cast", "the ronin=ronin", "--character-strength", "0.8"]
    runner = _StillsRunner(monkeypatch)
    assert ltx_movie.phase2_stills(args) == 0
    at = base.index("--only") + 1
    images_dir = os.path.join(str(movie_ws), "generated", "stories", "groups", "images")
    assert [cmd for cmd, _log in runner.runs] == [
        base[:at] + [only] + base[at + 1:] + ["--shots"] for only in ("4", "1,5", "2", "3")]
    assert [log for _cmd, log in runner.runs] == [
        os.path.join(images_dir, "stills-group-%02d.log" % k) for k in (1, 2, 3, 4)]
    capsys.readouterr()
    del runner.runs[:]
    assert ltx_movie.phase2_stills(args) == 0
    assert runner.runs == []
    assert capsys.readouterr().out.count("every still exists; skipped") == 4
    os.remove(os.path.join(images_dir, "panel_02.png"))
    assert ltx_movie.phase2_stills(args) == 0
    assert len(runner.runs) == 1
    cmd = runner.runs[0][0]
    assert cmd[cmd.index("--only") + 1] == "2"


def test_s44_failing_group_stops_phase2(monkeypatch, movie_ws, lib_dir, capsys):
    args = _group_args(movie_ws, lib_dir)
    runner = _StillsRunner(monkeypatch, returncodes=[0, 1])
    assert ltx_movie.phase2_stills(args) == 1
    err = capsys.readouterr().err
    assert len(runner.runs) == 2
    assert "for stills group 2/4" in err
    assert "stills-group-02.log" in err
    assert "rerun the same command to continue" in err
    assert os.path.isfile(os.path.join(str(movie_ws), "generated", "stories", "groups", "images",
                                       "panel_04.png"))


def test_s45_each_group_is_one_lora_set_end_to_end(monkeypatch, movie_ws, lib_dir):
    args = _group_args(movie_ws, lib_dir)
    runner = _StillsRunner(monkeypatch, write_pngs=False)
    assert ltx_movie.phase2_stills(args) == 0
    assert len(runner.runs) == 4
    calls, _seeds = _fake_zimage_shots(monkeypatch)
    for (cmd, _log), (names, panels) in zip(runner.runs, GROUPS):
        del calls[:]
        assert story_images.main(cmd[2:]) == 0, names
        assert len(calls) == len(panels)
        for _prompt, kwargs in calls:
            if names:
                assert kwargs["loras"] == [(_stills_path(lib_dir, n), 0.8) for n in names]
            else:
                assert "loras" not in kwargs
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `4 failed, 42 passed, <w> warnings in <t>s`, `rc=1`.

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T9.S3` applies these two edits to `bin/ltx-movie`.

**Edit 1** (spec 5.5, the `phase2_stills` branch directly after `    cmd += _cast_flags(args)`). Replace this exact text, which occurs exactly once:

````python plan=T9.S3.1 op=replace path=bin/ltx-movie
    cmd += _cast_flags(args)
    panel_01 = os.path.join(paths["images_dir"], "panel_01.png")
````

with:

````python plan=T9.S3.2 op=with path=bin/ltx-movie
    cmd += _cast_flags(args)
    if getattr(args, "shots", False):
        return _phase2_shots(args, cmd)
    panel_01 = os.path.join(paths["images_dir"], "panel_01.png")
````

**Edit 2** (spec 5.5, the grouping helpers and `_phase2_shots`, directly after `phase2_stills`; Decision 6). Replace this exact text, which occurs exactly once:

````python plan=T9.S3.3 op=replace path=bin/ltx-movie
        return 1
    return 0


def phase_release_story_server(args):
````

with:

````python plan=T9.S3.4 op=with path=bin/ltx-movie
        return 1
    return 0


def _panel_list(panels):
    return ",".join(str(i) for i in panels)


def _shots_stills_groups(story_md_path, members):
    """[(names, [panel numbers])]: shots-mode panels grouped by the cast characters whose stills
    LoRAs bin/ltx-story-images will load for them -- the same _compose_prompt(Image:, Style:) +
    cast_text(insert=members with a stills LoRA) match it performs, so every group is one LoRA
    set (shots spec 5.5). Sorted by (len(names), names); panels ascending, 1-based by position.
    Uncast: one group of every panel."""
    panels = _load_story_panels(story_md_path)
    by_panel = {i: () for i in range(1, len(panels) + 1)}
    if members:
        lib = _character_lib()
        images = importlib.machinery.SourceFileLoader(
            "ltx_story_images_for_movie", os.path.join(WS, "bin", "ltx-story-images")).load_module()
        style = images._style_text(panels)
        insert = {m.name for m in members if m.stills_lora}
        for i, p in enumerate(panels, start=1):
            by_panel[i] = tuple(lib.cast_text(images._compose_prompt(p["image"], style), members,
                                              insert=insert)[1])
    groups = {}
    for i, names in sorted(by_panel.items()):
        groups.setdefault(names, []).append(i)
    return sorted(groups.items(), key=lambda g: (len(g[0]), g[0]))


def _shots_missing_stills(args, panels):
    """The panels of one group whose still must be generated: those being redone, and those
    with no images/panel_NN.png."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    redo = set(getattr(args, "redo_panels", None) or [])
    return [i for i in panels if i in redo
            or not os.path.exists(os.path.join(images_dir, "panel_%02d.png" % i))]


def _phase2_shots(args, cmd):
    """Phase 2 in shots mode (shots spec 5.5): one bin/ltx-story-images run per stills-LoRA group,
    each the Phase 2 cmd with --only <the group's panels> and --shots appended, teed to
    images/stills-group-KK.log. A group with no missing still is skipped. Stops at the first
    failing group; stills already written are kept."""
    paths = _story_paths(args.story_id)
    groups = _shots_stills_groups(paths["story_md"], getattr(args, "cast_members", None) or [])
    os.makedirs(paths["images_dir"], exist_ok=True)
    for k, (names, panels) in enumerate(groups, start=1):
        label = "%s; panels %s" % (", ".join(names) or "no character LoRAs", _panel_list(panels))
        if not _shots_missing_stills(args, panels):
            print("stills group %d/%d (%s): every still exists; skipped" % (k, len(groups), label))
            continue
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        log_path = os.path.join(paths["images_dir"], "stills-group-%02d.log" % k)
        print("stills group %d/%d (%s); log: %s" % (k, len(groups), label, log_path))
        print("Running: %s" % shlex.join(group_cmd))
        rc = _stream_and_tee(group_cmd, log_path)
        if rc != 0:
            print("Error: ltx-story-images exited %d for stills group %d/%d (%s); log: %s. "
                  "Stills already written are kept; rerun the same command to continue -- every "
                  "existing panel_NN.png is reused." % (rc, k, len(groups), label, log_path),
                  file=sys.stderr)
            return 1
    return 0


def phase_release_story_server(args):
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `46 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly; L1z5 and L17b in the offline suite pin this task's edit):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: shots-mode Phase 2, one stills run per LoRA-set group

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

### Task 10: `bin/ltx-movie` -- `--redo`, shots Phase 3 and Phase 4, and the dry run

**Files:**
- Modify: `bin/ltx-movie` (8 edits below)
- Test: append to `tests/test_shots_mode.py`

**Interfaces:**
- Consumes: Task 9's `_panel_list`, `_shots_stills_groups`, `_shots_missing_stills`; Task 6's `_resolve_shots` (`args.redo_panels`); Task 3's `bin/ltx-story-manifest --shots`.
- Produces: `_shots_image_flags(args) -> ["--image", <images>/panel_01.png, ...]`; `_redo_moves(args, archive) -> [(src, dst)]`; `phase_redo_shots(args) -> 0 | 1`, inserted by `_phase_sequence` directly before `phase2_stills` when `args.redo_panels` is non-empty; `_print_shots_stills_plan(args, cmd)`; Phase 3 passes `--shots` plus one `--image` per panel; Phase 4 passes `--on-panel-failure skip` in shots mode; the dry run shows the redo moves and the stills groups.

Spec 5.6-5.8, verbatim:

#### 5.6 `--redo`: moving panels aside

**Choice and justification [spec choice].** `--redo` invalidates by **moving** files into a per-run archive, and never deletes. Moving is chosen for three reasons:

1. **Missing file is the one invalidation signal both tools already honor.** bin/ltx-story-images regenerates a missing `panel_NN.png`. bin/ltx-mlx-render's `clip_is_reusable` returns False for a missing clip. No tool gains a per-panel force flag.
2. **Nothing the user made is lost.** The previous take stays next to the new one for an A/B. bin/ltx-story-images `--force` would overwrite the old still in place, and there is no per-panel clip force at all.
3. **No cascade.** Shots panels are independent (`still` conditioning), so the other panels' provenance (image bytes, prompt, seed, LoRAs) is unchanged and `--resume` reuses them.

`movie.mp4` is moved too. That keeps the previous cut for comparison, and lets Phase 4's existing "already exists; pass --force" guard pass without `--force`.

```python
def _redo_moves(args, archive):
    """[(src, dst)] for every existing file --redo moves aside (shots spec 5.6), in order: per redo
    panel its still, clip and clip provenance; then movie.mp4. Reads only os.path state."""
    paths = _story_paths(args.story_id)
    clips_dir = os.path.join(paths["story_dir"], "clips")
    moves = []
    for n in args.redo_panels:
        for src, sub in ((os.path.join(paths["images_dir"], "panel_%02d.png" % n), "images"),
                         (os.path.join(clips_dir, "panel_%02d.mp4" % n), "clips"),
                         (os.path.join(clips_dir, "panel_%02d.mp4.provenance.json" % n), "clips")):
            if os.path.lexists(src):
                moves.append((src, os.path.join(archive, sub, os.path.basename(src))))
    if os.path.lexists(paths["movie_path"]):
        moves.append((paths["movie_path"], os.path.join(archive, "movie.mp4")))
    return moves


def phase_redo_shots(args):
    """--redo (shots spec 5.6): move the named panels' still, clip and clip provenance, and
    movie.mp4, into <story>/redo/<UTC stamp>-<pid>/, so Phase 2 regenerates only those stills
    and Phase 4 (--resume) re-renders only those clips. Never deletes anything."""
    paths = _story_paths(args.story_id)
    panels = _panel_list(args.redo_panels)
    print("=== Redo: panels %s ===" % panels)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d"
                           % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
    moves = _redo_moves(args, archive)
    for src, dst in moves:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
        except OSError as e:
            print("Error: --redo could not move %s to %s: %s" % (src, dst, e), file=sys.stderr)
            return 1
        print("redo: moved %s -> %s" % (src, dst))
    if not moves:
        print("redo: nothing to move (no still, clip or movie exists yet for panels %s)" % panels)
    print("redo: panels %s re-render; every other panel's still and clip is reused (stills by "
          "existence, clips by --resume provenance)" % panels)
    return 0
```

**`_phase_sequence`.** After the `--story-server-stop-after-story` insertion and before the `--seed-image` prefix:

```python
    if getattr(args, "redo_panels", None):
        cut = phases.index(phase2_stills)
        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]
```

- The redo phase runs after Phase 1's validation (an invalid story exits 2 before anything moves), and before Phase 2.
- `--redo` requires `--shots`, which excludes `--no-stills`, so `phase2_stills` is always present.
- Objects without `redo_panels` (test L41) get today's sequences.

**Seeds.** `--redo` re-renders with the same seeds: the stills use the pinned `--image-seed`, and the render uses `--seed + i`. So `--redo` is meant to follow an edit of that panel's `Image:` and/or `Motion:` in story.md. An unedited redo reproduces the same take (G6).

#### 5.7 Phase 3 and Phase 4

```python
def _shots_image_flags(args):
    """--image <images>/panel_NN.png for every panel 1..--panels, in order (shots spec 5.7)."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    flags = []
    for i in range(1, args.panels + 1):
        flags += ["--image", os.path.join(images_dir, "panel_%02d.png" % i)]
    return flags
```

- **`phase3_manifest`.** Between `if args.no_stills: cmd_manifest += ["--no-images"]` and its `else:`, insert `elif getattr(args, "shots", False): cmd_manifest += ["--shots"] + _shots_image_flags(args)`.
- **`_print_dry_run_plan`.** Insert the identical `elif` into its `phase3_manifest_cmd` block. The rest of each command (`--fps … --force`, then `_cast_flags(args)`) is unchanged.
- **`_phase4_flags`.** The failure-policy line becomes `"--on-panel-failure", "skip" if (args.no_stills or getattr(args, "shots", False)) else "stop",` **[spec choice]**. Shots clips are independent, like `--no-stills` clips, so one failed panel must not stop the rest. bin/ltx-mlx-render's end-of-run retry pass (one retry after 120 s) applies, because the manifest has no chain units. The docstring gains: `--shots renders independent clips too and passes skip.`
- **Phase 4** is otherwise unchanged. The render tool is unchanged.

#### 5.8 Dry run

In `_print_dry_run_plan` (every addition is conditional, so an uncast dry run without `--shots` is byte-identical, B1):

1. The rendered prompt uses `shots=` (5.2).
2. After the Phase 1b block and before the `if args.no_stills:` Phase 2 block, insert:

```python
    if getattr(args, "redo_panels", None):
        print("--- Redo: panels %s ---" % _panel_list(args.redo_panels))
        for src, dst in _redo_moves(args, os.path.join(paths["story_dir"], "redo",
                                                       "<UTC stamp>-<pid>")):
            print("Would move %s -> %s" % (src, dst))
        print("Then only those panels' stills and clips re-render; every other panel is reused.")
        print()
```

3. In the Phase 2 block, replace `        print("Command: %s" % shlex.join(phase2_cmd))` with:

```python
        if getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
        else:
            print("Command: %s" % shlex.join(phase2_cmd))
```

```python
def _print_shots_stills_plan(args, cmd):
    """Phase 2's dry-run lines in shots mode (shots spec 5.8). Touches nothing."""
    story_md = _story_paths(args.story_id)["story_md"]
    if args.force_story or not os.path.exists(story_md):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = "<PANELS>"
        group_cmd.append("--shots")
        print("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of "
              "cast stills LoRAs, each with --only <PANELS> (that group's panels):")
        print("Command: %s" % shlex.join(group_cmd))
        return
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        skip = "" if _shots_missing_stills(args, panels) else " -- would be skipped: every still exists"
        print("stills group %d/%d (%s; panels %s)%s"
              % (k, len(groups), ", ".join(names) or "no character LoRAs", _panel_list(panels), skip))
        print("Command: %s" % shlex.join(group_cmd))
```

4. The Phase 3 manifest command uses the 5.7 `elif`. The Phase 4 command shows `--on-panel-failure skip`.

Spec 7.2 row E-S13, verbatim:

| # | Tool | Condition | Exit / effect |
|---|---|---|---|
| E-S13 | ltx-movie | `--redo` move fails (OSError) | 1. `Error: --redo could not move <src> to <dst>: <e>`. Earlier moves stay in the archive (printed) |

Spec 10.4 rows S46-S53, verbatim:

| ID | Test | Assertion |
|---|---|---|
| S46 | `phase3_manifest` shots | `subprocess.run` patched to record → the manifest `cmd` has `"--shots"` directly followed by `--image <images>/panel_01.png … --image <images>/panel_14.png` (`--panels 14`) and no `"--chain"`. The `_print_dry_run_plan` Phase 3 line is the same command |
| S47 | `_phase4_flags` | `--shots` → `--on-panel-failure skip`. Default → `stop`. `--no-stills` → `skip` (L51 unchanged) |
| S48 | `_phase_sequence` | an object with `no_stills=False`, `story_server_stop_after_story=True`, `redo_panels=[3]` → `("phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills", "phase3_manifest", "phase4_render")`. `redo_panels=[]` → no redo phase. Every L41 case is unchanged |
| S49 | `phase_redo_shots` | story dir with `images/panel_0{1,2,3}.png`, `clips/panel_0{1,2,3}.mp4` (+ `.provenance.json`) and `movie.mp4`, each with distinct bytes; `redo_panels=[2]` → rc 0. `redo/<stamp>-<pid>/images/panel_02.png`, `…/clips/panel_02.mp4`, `…/clips/panel_02.mp4.provenance.json` and `…/movie.mp4` hold the original bytes. Those source paths are gone. Panels 1 and 3 are byte- and mtime-unchanged. The total file count under the story dir is unchanged (nothing deleted). `redo_panels=[3]` with no clip for 3 moves only what exists, and prints one line per move |
| S50 | dry run, shots, new story | subprocess `bin/ltx-movie "n" --story-id <fresh> --shots --panels 4 --dry-run --no-review --character kyra --character ronin` (`CHARACTER_LIBRARY_DIR` set) → rc 0. stdout contains the shots template text (`"sequence of separate shots joined by cuts"`) and the shots Cast rules (`"at most two of these characters"`), `"Stills groups: computed from story.md after Phase 1"`, a Phase 2 `Command:` with `--only '<PANELS>'` and ending in `--shots`, the Phase 3 manifest command with `--shots` and 4 `--image`s, and `--on-panel-failure skip`. `generated/stories/<fresh>` is not created |
| S51 | dry run, existing story, `--redo 2` | `WS` patched to `tmp_path`, with the S49 tree and `SHOTS_OK` as story.md (3 panels) → `main([... "--dry-run" ...])` rc 0. stdout has `"--- Redo: panels 2 ---"`, one `"Would move …"` line per existing file, and per-group `Command:` lines. Panel 2's group is not marked skipped, and other fully-present groups are marked `"would be skipped"`. Every file is byte- and mtime-unchanged, and no `redo/` dir exists |
| S52 | non-shots byte identity | B1 (its golden holds the full rendered prompt and the Phase 2, 3 and 4 commands of an uncast dry run), B2, B3, P46 (cast dry run) and L51 pass unchanged. Additionally, for a default `parse_args(["n", "--story-id", "x"])` namespace: no `"--shots"` token in `_phase4_flags(args)`, `_render_flags(args)` or the dry-run output; `--on-panel-failure stop`; and `"--chain"` present in the Phase 3 manifest command |
| S53 | uncast non-shots run never loads `character_lib` | P49 unchanged. Additionally `main(["n", "--story-id", "x", "--dry-run", "--no-review", "--shots"])` with no cast does not load `character_lib`: the dry run needs no validation, and the grouping is uncast |

Precondition: Task 9 is committed and `git diff --quiet HEAD -- bin/ltx-movie && echo clean` prints `clean`.

- [ ] **Step 1: Write the failing test.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T10.S1` appends exactly this content to the end of `tests/test_shots_mode.py`:

````python plan=T10.S1.1 op=append path=tests/test_shots_mode.py


# --- S46-S53: --redo, Phase 3, Phase 4 and the dry run (spec 5.6-5.8) --------------------
def _record_runs(monkeypatch):
    runs = []
    monkeypatch.setattr(ltx_movie.subprocess, "run",
                        lambda cmd, **kw: runs.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0))
    return runs


def test_s46_phase3_passes_shots_and_every_still(monkeypatch, movie_ws, capsys):
    _story_dir_with(movie_ws, "s46")
    args = _shots_args("n", "--story-id", "s46", "--shots", "--panels", "14", "--no-review")
    runs = _record_runs(monkeypatch)
    assert ltx_movie.phase3_manifest(args) == 0
    manifest_cmd = runs[0]
    assert "ltx-story-manifest" in manifest_cmd[1]
    images = os.path.join(str(movie_ws), "generated", "stories", "s46", "images")
    expected = []
    for i in range(1, 15):
        expected += ["--image", os.path.join(images, "panel_%02d.png" % i)]
    at = manifest_cmd.index("--shots")
    assert manifest_cmd[at + 1:at + 29] == expected
    assert manifest_cmd.count("--image") == 14
    assert "--chain" not in manifest_cmd
    capsys.readouterr()
    assert ltx_movie.main(["n", "--story-id", "s46", "--shots", "--panels", "14", "--dry-run",
                           "--no-review"]) == 0
    assert "Command: %s" % ltx_movie.shlex.join(manifest_cmd) in capsys.readouterr().out.splitlines()


def test_s47_phase4_failure_policy():
    def policy(*extra):
        flags = ltx_movie._phase4_flags(_movie_args("n", "--story-id", "x", *extra))
        return flags[flags.index("--on-panel-failure") + 1]

    assert policy("--shots") == "skip"
    assert policy() == "stop"
    assert policy("--no-stills") == "skip"


def test_s48_phase_sequence_with_redo():
    def names(**kwargs):
        return tuple(f.__name__ for f in ltx_movie._phase_sequence(types.SimpleNamespace(**kwargs)))

    assert names(no_stills=False, story_server_stop_after_story=True, redo_panels=[3]) == (
        "phase1_story", "phase_release_story_server", "phase_redo_shots", "phase2_stills",
        "phase3_manifest", "phase4_render")
    assert names(no_stills=False, story_server_stop_after_story=True, redo_panels=[]) == (
        "phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
        "phase4_render")
    l41 = [
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase2_stills", "phase3_manifest",
          "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image=None),
         ("phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image=None),
         ("phase1_story", "phase_release_story_server", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase2_stills", "phase3_manifest", "phase4_render")),
        (dict(no_stills=False, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server", "phase2_stills",
          "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=False, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase3_manifest", "phase4_render")),
        (dict(no_stills=True, story_server_stop_after_story=True, seed_image="x.png"),
         ("phase0_seed", "phase1_story", "phase_release_story_server", "phase3_manifest",
          "phase4_render")),
    ]
    for kwargs, expected in l41:
        assert names(**kwargs) == expected, kwargs


def _redo_tree(movie_ws, story_id, clip_panels=(1, 2, 3)):
    """A shots story dir: SHOTS_OK as story.md, images/panel_0{1,2,3}.png, clips/panel_0N.mp4
    (+ .provenance.json) for clip_panels, and movie.mp4, each with distinct bytes."""
    directory = _story_dir_with(movie_ws, story_id, SHOTS_OK)
    (directory / "images").mkdir()
    (directory / "clips").mkdir()
    for i in (1, 2, 3):
        (directory / "images" / ("panel_%02d.png" % i)).write_bytes(b"still %d" % i)
        if i in clip_panels:
            (directory / "clips" / ("panel_%02d.mp4" % i)).write_bytes(b"clip %d" % i)
            (directory / "clips" / ("panel_%02d.mp4.provenance.json" % i)).write_bytes(
                b"provenance %d" % i)
    (directory / "movie.mp4").write_bytes(b"movie")
    return str(directory)


def _snapshot(directory):
    out = {}
    for path in _all_files(directory):
        with open(path, "rb") as f:
            out[path] = (f.read(), os.stat(path).st_mtime_ns)
    return out


def _redo_pairs(directory, archive, panel, clip=True):
    j = os.path.join
    pairs = [(j(directory, "images", "panel_%02d.png" % panel),
              j(archive, "images", "panel_%02d.png" % panel))]
    if clip:
        pairs += [(j(directory, "clips", "panel_%02d.mp4" % panel),
                   j(archive, "clips", "panel_%02d.mp4" % panel)),
                  (j(directory, "clips", "panel_%02d.mp4.provenance.json" % panel),
                   j(archive, "clips", "panel_%02d.mp4.provenance.json" % panel))]
    return pairs + [(j(directory, "movie.mp4"), j(archive, "movie.mp4"))]


def test_s49_redo_moves_only_the_named_panels(movie_ws, capsys):
    directory = _redo_tree(movie_ws, "s49")
    before = _snapshot(directory)
    args = _shots_args("n", "--story-id", "s49", "--shots", "--redo", "2", "--panels", "3")
    assert ltx_movie.phase_redo_shots(args) == 0
    archives = glob.glob(os.path.join(directory, "redo", "*"))
    assert len(archives) == 1
    assert re.fullmatch(r"\d{8}T\d{6}Z-%d" % os.getpid(), os.path.basename(archives[0]))
    pairs = _redo_pairs(directory, archives[0], 2)
    for src, dst in pairs:
        assert not os.path.lexists(src)
        with open(dst, "rb") as f:
            assert f.read() == before[src][0]
    after = _snapshot(directory)
    moved = {src for src, _dst in pairs}
    for path, value in before.items():
        if path not in moved:
            assert after[path] == value, path
    assert len(after) == len(before)
    assert [l for l in capsys.readouterr().out.splitlines() if l.startswith("redo: moved ")] == [
        "redo: moved %s -> %s" % pair for pair in pairs]
    directory = _redo_tree(movie_ws, "s49b", clip_panels=(1, 2))
    args = _shots_args("n", "--story-id", "s49b", "--shots", "--redo", "3", "--panels", "3")
    assert ltx_movie.phase_redo_shots(args) == 0
    archives = glob.glob(os.path.join(directory, "redo", "*"))
    assert len(archives) == 1
    assert [l for l in capsys.readouterr().out.splitlines() if l.startswith("redo: moved ")] == [
        "redo: moved %s -> %s" % pair for pair in _redo_pairs(directory, archives[0], 3,
                                                               clip=False)]


def test_s50_dry_run_new_shots_story(lib_dir):
    _kyra(lib_dir)
    _ronin(lib_dir)
    story_id = "shots-s50-%d" % os.getpid()
    story_dir = os.path.join(WS, "generated", "stories", story_id)
    assert not os.path.exists(story_dir)
    proc = subprocess.run(
        [sys.executable, "bin/ltx-movie", "n", "--story-id", story_id, "--shots", "--panels", "4",
         "--dry-run", "--no-review", "--character", "kyra", "--character", "ronin"],
        cwd=WS, env=dict(os.environ, CHARACTER_LIBRARY_DIR=lib_dir, STORY_PIPELINE_LOGGED="1"),
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    lines = out.splitlines()
    assert "sequence of separate shots joined by cuts" in out
    assert "at most two of these characters" in out
    assert any(l.startswith("Stills groups: computed from story.md after Phase 1") for l in lines)
    phase2 = [l for l in lines if l.startswith("Command: ") and "ltx-story-images" in l]
    assert len(phase2) == 1
    assert "--only '<PANELS>'" in phase2[0] and phase2[0].endswith(" --shots")
    manifest = [l for l in lines if l.startswith("Command: ") and "ltx-story-manifest" in l]
    assert len(manifest) == 1
    assert "--shots" in manifest[0].split() and manifest[0].split().count("--image") == 4
    assert "--on-panel-failure skip" in out
    assert not os.path.exists(story_dir)


def test_s51_dry_run_existing_story_with_redo(movie_ws, lib_dir, capsys):
    _kyra(lib_dir)
    _ronin(lib_dir)
    directory = _redo_tree(movie_ws, "s51")
    before = _snapshot(directory)
    assert ltx_movie.main(["n", "--story-id", "s51", "--shots", "--redo", "2", "--panels", "3",
                           "--dry-run", "--no-review", "--character", "kyra",
                           "--character", "ronin"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "--- Redo: panels 2 ---" in lines
    archive = os.path.join(directory, "redo", "<UTC stamp>-<pid>")
    assert [l for l in lines if l.startswith("Would move ")] == [
        "Would move %s -> %s" % pair for pair in _redo_pairs(directory, archive, 2)]
    groups = [i for i, l in enumerate(lines) if l.startswith("stills group ")]
    assert [lines[i] for i in groups] == [
        "stills group 1/3 (no character LoRAs; panels 2)",
        "stills group 2/3 (kyra; panels 1) -- would be skipped: every still exists",
        "stills group 3/3 (kyra, ronin; panels 3) -- would be skipped: every still exists"]
    for i, only in zip(groups, ("2", "1", "3")):
        assert lines[i + 1].startswith("Command: ") and "ltx-story-images" in lines[i + 1]
        assert " --only %s " % only in lines[i + 1] and lines[i + 1].endswith(" --shots")
    assert _snapshot(directory) == before
    assert not os.path.exists(os.path.join(directory, "redo"))


def test_s52_non_shots_outputs_are_byte_identical(tmp_path, movie_ws, capsys):
    regression = _load("casting_regression_for_s52", "tests/test_casting_regression.py")
    for text, golden in ((regression.b1_text(), regression.GOLDEN_B1),
                         (regression.b2_text(str(tmp_path)), regression.GOLDEN_B2),
                         (regression.b3_text(), regression.GOLDEN_B3)):
        with open(golden, encoding="utf-8") as f:
            assert text == f.read(), golden
    args = _movie_args("n", "--story-id", "x")
    flags = ltx_movie._phase4_flags(args)
    assert "--shots" not in flags
    assert "--shots" not in ltx_movie._render_flags(args)
    assert flags[flags.index("--on-panel-failure") + 1] == "stop"
    assert ltx_movie.main(["n", "--story-id", "x", "--dry-run", "--no-review"]) == 0
    out = capsys.readouterr().out
    assert "--shots" not in out.split()
    manifest = next(l for l in out.splitlines()
                    if l.startswith("Command: ") and "ltx-story-manifest" in l)
    assert "--chain" in manifest.split()


def test_s53_uncast_shots_dry_run_never_loads_character_lib():
    script = (
        "import contextlib, io, sys\n"
        "sys.path.insert(0, %r)\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader('ltx_movie', %r).load_module()\n"
        "with contextlib.redirect_stdout(io.StringIO()):\n"
        "    rc = m.main(['n', '--story-id', 'x', '--dry-run', '--no-review', '--shots'])\n"
        "print('RC=%%d' %% rc)\n"
        "print('CHARACTER_LIB_LOADED=%%s' %% ('character_lib' in sys.modules))\n"
    ) % (WS, os.path.join(WS, "bin", "ltx-movie"))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    lines = proc.stdout.splitlines()
    assert "RC=0" in lines, proc.stderr
    assert "CHARACTER_LIB_LOADED=False" in lines
````

- [ ] **Step 2: Run to fail:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `6 failed, 48 passed, <w> warnings in <t>s`, `rc=1`. S52 and S53 pass before the implementation: they pin the unchanged non-shots outputs and the uncast loading rule (guards).

- [ ] **Step 3: Implement.** `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" T10.S3` applies these eight edits to `bin/ltx-movie`.

**Edit 1** (spec 5.7, `_phase4_flags`: the failure policy and the docstring sentence). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.1 op=replace path=bin/ltx-movie
    retry, a 120 s idle before it and the 3-consecutive circuit breaker (which the
    render tool does not consult for a chained manifest)."""
    flags = _render_flags(args) + [
        "--panel-timeout", str(args.panel_timeout),
        "--on-panel-failure", "skip" if args.no_stills else "stop",
````

with:

````python plan=T10.S3.2 op=with path=bin/ltx-movie
    retry, a 120 s idle before it and the 3-consecutive circuit breaker (which the
    render tool does not consult for a chained manifest). --shots renders independent clips
    too and passes skip."""
    flags = _render_flags(args) + [
        "--panel-timeout", str(args.panel_timeout),
        "--on-panel-failure", "skip" if (args.no_stills or getattr(args, "shots", False)) else "stop",
````

**Edit 2** (spec 5.6, `_redo_moves` and `phase_redo_shots`, directly after `phase_release_story_server`; Decision 6). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.3 op=replace path=bin/ltx-movie
    if not _wait_for_avail(args.min_avail_gib, args.avail_timeout):
        return 1
    return 0


# ---------------------------------------------------------------------------
# phase 3: manifest + dry-run
# ---------------------------------------------------------------------------

def phase3_manifest(args):
````

with:

````python plan=T10.S3.4 op=with path=bin/ltx-movie
    if not _wait_for_avail(args.min_avail_gib, args.avail_timeout):
        return 1
    return 0


def _redo_moves(args, archive):
    """[(src, dst)] for every existing file --redo moves aside (shots spec 5.6), in order: per redo
    panel its still, clip and clip provenance; then movie.mp4. Reads only os.path state."""
    paths = _story_paths(args.story_id)
    clips_dir = os.path.join(paths["story_dir"], "clips")
    moves = []
    for n in args.redo_panels:
        for src, sub in ((os.path.join(paths["images_dir"], "panel_%02d.png" % n), "images"),
                         (os.path.join(clips_dir, "panel_%02d.mp4" % n), "clips"),
                         (os.path.join(clips_dir, "panel_%02d.mp4.provenance.json" % n), "clips")):
            if os.path.lexists(src):
                moves.append((src, os.path.join(archive, sub, os.path.basename(src))))
    if os.path.lexists(paths["movie_path"]):
        moves.append((paths["movie_path"], os.path.join(archive, "movie.mp4")))
    return moves


def phase_redo_shots(args):
    """--redo (shots spec 5.6): move the named panels' still, clip and clip provenance, and
    movie.mp4, into <story>/redo/<UTC stamp>-<pid>/, so Phase 2 regenerates only those stills
    and Phase 4 (--resume) re-renders only those clips. Never deletes anything."""
    paths = _story_paths(args.story_id)
    panels = _panel_list(args.redo_panels)
    print("=== Redo: panels %s ===" % panels)
    archive = os.path.join(paths["story_dir"], "redo", "%s-%d"
                           % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
    moves = _redo_moves(args, archive)
    for src, dst in moves:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
        except OSError as e:
            print("Error: --redo could not move %s to %s: %s" % (src, dst, e), file=sys.stderr)
            return 1
        print("redo: moved %s -> %s" % (src, dst))
    if not moves:
        print("redo: nothing to move (no still, clip or movie exists yet for panels %s)" % panels)
    print("redo: panels %s re-render; every other panel's still and clip is reused (stills by "
          "existence, clips by --resume provenance)" % panels)
    return 0


# ---------------------------------------------------------------------------
# phase 3: manifest + dry-run
# ---------------------------------------------------------------------------

def _shots_image_flags(args):
    """--image <images>/panel_NN.png for every panel 1..--panels, in order (shots spec 5.7)."""
    images_dir = _story_paths(args.story_id)["images_dir"]
    flags = []
    for i in range(1, args.panels + 1):
        flags += ["--image", os.path.join(images_dir, "panel_%02d.png" % i)]
    return flags


def phase3_manifest(args):
````

**Edit 3** (spec 5.7, the Phase 3 `elif`). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.5 op=replace path=bin/ltx-movie
    if args.no_stills:
        cmd_manifest += ["--no-images"]
    else:
````

with:

````python plan=T10.S3.6 op=with path=bin/ltx-movie
    if args.no_stills:
        cmd_manifest += ["--no-images"]
    elif getattr(args, "shots", False):
        cmd_manifest += ["--shots"] + _shots_image_flags(args)
    else:
````

**Edit 4** (spec 5.8, `_print_shots_stills_plan` directly before `_print_dry_run_plan`). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.7 op=replace path=bin/ltx-movie
# dry-run plan
# ---------------------------------------------------------------------------

def _print_dry_run_plan(args):
````

with:

````python plan=T10.S3.8 op=with path=bin/ltx-movie
# dry-run plan
# ---------------------------------------------------------------------------

def _print_shots_stills_plan(args, cmd):
    """Phase 2's dry-run lines in shots mode (shots spec 5.8). Touches nothing."""
    story_md = _story_paths(args.story_id)["story_md"]
    if args.force_story or not os.path.exists(story_md):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = "<PANELS>"
        group_cmd.append("--shots")
        print("Stills groups: computed from story.md after Phase 1 -- one run per distinct set of "
              "cast stills LoRAs, each with --only <PANELS> (that group's panels):")
        print("Command: %s" % shlex.join(group_cmd))
        return
    groups = _shots_stills_groups(story_md, getattr(args, "cast_members", None) or [])
    for k, (names, panels) in enumerate(groups, start=1):
        group_cmd = list(cmd)
        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)
        group_cmd.append("--shots")
        skip = "" if _shots_missing_stills(args, panels) else " -- would be skipped: every still exists"
        print("stills group %d/%d (%s; panels %s)%s"
              % (k, len(groups), ", ".join(names) or "no character LoRAs", _panel_list(panels), skip))
        print("Command: %s" % shlex.join(group_cmd))


def _print_dry_run_plan(args):
````

**Edit 5** (spec 5.8 item 2, the redo block after the Phase 1b block). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.9 op=replace path=bin/ltx-movie
        print()

    if args.no_stills:
        print("--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)")
````

with:

````python plan=T10.S3.10 op=with path=bin/ltx-movie
        print()

    if getattr(args, "redo_panels", None):
        print("--- Redo: panels %s ---" % _panel_list(args.redo_panels))
        for src, dst in _redo_moves(args, os.path.join(paths["story_dir"], "redo",
                                                       "<UTC stamp>-<pid>")):
            print("Would move %s -> %s" % (src, dst))
        print("Then only those panels' stills and clips re-render; every other panel is reused.")
        print()

    if args.no_stills:
        print("--- Phase 2: stills --- SKIPPED (--no-stills: no anchor stills are generated)")
````

**Edit 6** (spec 5.8 item 3, the Phase 2 command line). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.11 op=replace path=bin/ltx-movie
        phase2_cmd += _cast_flags(args)
        print("Command: %s" % shlex.join(phase2_cmd))
````

with:

````python plan=T10.S3.12 op=with path=bin/ltx-movie
        phase2_cmd += _cast_flags(args)
        if getattr(args, "shots", False):
            _print_shots_stills_plan(args, phase2_cmd)
        else:
            print("Command: %s" % shlex.join(phase2_cmd))
````

**Edit 7** (spec 5.8 item 4 / 5.7, the identical `elif` in the dry run's Phase 3 block). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.13 op=replace path=bin/ltx-movie
    if args.no_stills:
        phase3_manifest_cmd += ["--no-images"]
    else:
````

with:

````python plan=T10.S3.14 op=with path=bin/ltx-movie
    if args.no_stills:
        phase3_manifest_cmd += ["--no-images"]
    elif getattr(args, "shots", False):
        phase3_manifest_cmd += ["--shots"] + _shots_image_flags(args)
    else:
````

**Edit 8** (spec 5.6, `_phase_sequence`: the redo phase after the story-server insertion and before the `--seed-image` prefix). Replace this exact text, which occurs exactly once:

````python plan=T10.S3.15 op=replace path=bin/ltx-movie
        phases = phases[:cut] + (phase_release_story_server,) + phases[cut:]
    if getattr(args, "seed_image", None):
````

with:

````python plan=T10.S3.16 op=with path=bin/ltx-movie
        phases = phases[:cut] + (phase_release_story_server,) + phases[cut:]
    if getattr(args, "redo_panels", None):
        cut = phases.index(phase2_stills)
        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]
    if getattr(args, "seed_image", None):
````

- [ ] **Step 4: Run to pass:** `python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider; echo "rc=$?"`

Expected: `54 passed, <w> warnings in <t>s`, `rc=0`. Then the regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

- [ ] **Step 5: Commit**

Stage by explicit path only (the working tree has unrelated modified files: `bin/qwen-agent`, `bin/ltx-story-video`, `ltx_video_skill.py`, `ltx_ceiling.json`, and both `.gitignore` files; none may be staged). Run from `WS`:

````bash
git add bin/ltx-movie tests/test_shots_mode.py
git diff --cached --name-only
````

The second command must print exactly these lines (any order), and nothing else:

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/tests/test_shots_mode.py
````

If anything else is listed, run `git restore --staged <that path>` and re-check. Then:

````bash
git commit -q -F - <<'EOF'
ltx-movie: --redo, shots Phase 3/4 flags and the shots dry run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git log --oneline -1
````

Do not push (pushing is gated by a design review).

---

## Final Acceptance (orchestrator, after Task 10; spec 10.7 and Section 11 item 9)

The orchestrator runs every step itself. Counts an implementer reports are not accepted (spec R1).

### A1: new-suite count and test-ID coverage

````bash
python3 -m pytest tests/test_shots_mode.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-a1.log 2>&1; echo "shots rc=$? $(tail -1 /tmp/shotsplan-a1.log)"
python3 -m pytest tests/test_shots_mode.py tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-a1b.log 2>&1; echo "one session rc=$? $(tail -1 /tmp/shotsplan-a1b.log)"
````

Expected: `shots rc=0 54 passed, <w> warnings in <t>s`, then `one session rc=0 232 passed, <w> warnings in <t>s` (the shots suite and the casting set in one pytest session, which reloads `character_lib` by path from several tools; 54 + 178).

Then write the coverage check with `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" FA.A1` (it creates `/tmp/shotsplan-accept/coverage.py`; move an older copy aside with `mv` first) and run `python3 /tmp/shotsplan-accept/coverage.py "$PLAN"` from `WS`:

````python plan=FA.A1.1 op=create path=/tmp/shotsplan-accept/coverage.py
#!/usr/bin/env python3
"""Shots-mode test-ID coverage (plan Final Acceptance A1): every spec 10.3-10.6 ID has
exactly one test function in tests/test_shots_mode.py, and each ID's function is added by
exactly one task block of the plan.  usage: python3 coverage.py PLAN_MD  (run from WS)"""
import re
import sys

WANT = ["s%d" % i for i in list(range(1, 21)) + list(range(30, 54)) + list(range(60, 67))
        + list(range(70, 73))]
with open("tests/test_shots_mode.py", encoding="utf-8") as f:
    names = re.findall(r"^def test_(s\d+)_", f.read(), re.M)
assert sorted(names) == sorted(WANT), (sorted(set(WANT) - set(names)),
                                       sorted(set(names) - set(WANT)))
assert len(names) == len(set(names)) == 54
with open(sys.argv[1], encoding="utf-8") as f:
    plan = f.read()
owner = {}
for task, body in re.findall(r"^````python plan=(T\d+)\.S1\.1 op=(?:create|append) "
                             r"path=tests/test_shots_mode\.py\n(.*?)^````$", plan, re.S | re.M):
    for test_id in re.findall(r"^def test_(s\d+)_", body, re.M):
        assert test_id not in owner, (test_id, owner.get(test_id), task)
        owner[test_id] = task
assert sorted(owner) == sorted(WANT), sorted(set(WANT) - set(owner))
by_task = {}
for test_id, task in owner.items():
    by_task.setdefault(task, []).append(test_id)
for task in sorted(by_task, key=lambda t: int(t[1:])):
    print("%s: %d tests" % (task, len(by_task[task])))
print("test IDs: 54, one function each, each added by exactly one task")
````

Expected output, exactly:

````
T2: 20 tests
T3: 6 tests
T4: 3 tests
T5: 1 tests
T6: 5 tests
T8: 7 tests
T9: 4 tests
T10: 8 tests
test IDs: 54, one function each, each added by exactly one task
````

### A2: B-goldens (SC9)

`python3 -m pytest tests/test_casting_regression.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-a2.log 2>&1; echo "rc=$? $(tail -1 /tmp/shotsplan-a2.log)"` -> `rc=0 3 passed, 1 warning in <t>s`. And `git diff --stat c7309e1 HEAD -- tests/fixtures/ tests/test_casting_regression.py` prints nothing: the uncast goldens were never re-captured. (B1 holds the full rendered prompt and the Phase 2, 3 and 4 commands of an uncast dry run; B2 the chained manifest; B3 the ltx-2-mlx argv.)

### A3: the full mutation table (self-restoring)

Write the runner with `python3 /tmp/shotsplan-tools/apply_plan.py "$PLAN" FA.A3` (it creates `/tmp/shotsplan-accept/mutations.py`, outside the repo; if that file exists from an earlier attempt, move it aside with `mv` first) and run `python3 /tmp/shotsplan-accept/mutations.py` from `WS`. It edits tracked files temporarily and restores them in `finally`; nothing else may run against the tree meanwhile. Afterwards `git status --short -- character_lib.py bin/` must list none of this feature's files. If the runner is killed, restore with `git checkout -- <file>`: every target is committed by then.

````python plan=FA.A3.1 op=create path=/tmp/shotsplan-accept/mutations.py
#!/usr/bin/env python3
"""Self-restoring mutation runner for shots mode (plan Final Acceptance A3; spec 10.7).

Run from the workspace root:  python3 /tmp/shotsplan-accept/mutations.py
Each row is applied alone. For every row: (1) each anchor's exact occurrence count is
asserted, (2) every target passes on the unmutated tree (control), (3) the mutation is
written, (4) each target runs; a pytest target returns 1 = CAUGHT, 0 = survived, anything
else = broken; a direct-run target ("R1:<file>") returns non-zero = CAUGHT, 0 = survived.
A row passes when at least one target is CAUGHT and none is broken. Files are restored in
finally. Every run gets a fresh PYTHONPYCACHEPREFIX and TMPDIR (a stale .pyc written in
the same second as the mutation can otherwise falsely survive). pytest runs as
python3 -m pytest -q --color=no -p no:cacheprovider <node id>.
"""
import os
import shutil
import subprocess
import sys
import tempfile

WS = os.getcwd()
LIB = "character_lib.py"
MO = "bin/ltx-movie"
MA = "bin/ltx-story-manifest"
IM = "bin/ltx-story-images"
T = "tests/test_shots_mode.py::"
R1_OFFLINE = "R1:tests/test_ltx_movie_offline.py"
R1_IMAGES = "R1:tests/test_ltx_story_images.py"
ITERATE_C1 = "tests/test_ltx_movie_iterate_flags.py::test_danger_auto_approve_trace_reaches_stdout_on_success"
B1 = "tests/test_casting_regression.py::test_b1_ltx_movie_dry_run_is_unchanged"

S = {
    1: "test_s1_constants", 2: "test_s2_panel_strengths_in_shots_mode",
    3: "test_s3_shots_cast_block", 4: "test_s4_find_phrases",
    5: "test_s5_parse_character_roster", 6: "test_s6_motion_problems_pass",
    7: "test_s7_motion_problems_fail", 8: "test_s8_motion_negative_controls",
    9: "test_s9_shots_ok_is_valid", 11: "test_s11_s2_roster_presence",
    12: "test_s12_s2_cast_phrase_missing", 15: "test_s15_s6_cast_count",
    16: "test_s16_s7_cast_and_extra", 17: "test_s17_s7_longest_phrase_claims_the_span",
    18: "test_s18_shots_advisories", 31: "test_s31_shots_story_prompt",
    32: "test_s32_non_shots_prompts_are_unchanged", 33: "test_s33_resolve_shots_errors",
    34: "test_s34_resolve_casting_in_shots_mode", 35: "test_s35_valid_first_draft",
    36: "test_s36_one_rewrite", 37: "test_s37_second_failure_exits_2",
    38: "test_s38_existing_story_is_never_rewritten", 40: "test_s40_advisories_are_not_fatal",
    42: "test_s42_stills_groups", 43: "test_s43_phase2_runs_one_process_per_group",
    44: "test_s44_failing_group_does_not_stop_phase2",
    45: "test_s45_each_group_is_one_lora_set_end_to_end",
    46: "test_s46_phase3_passes_shots_and_every_still", 47: "test_s47_phase4_failure_policy",
    48: "test_s48_phase_sequence_with_redo", 49: "test_s49_redo_moves_only_the_named_panels",
    51: "test_s51_dry_run_existing_story_with_redo", 60: "test_s60_shots_manifest_uncast",
    61: "test_s61_shots_cast_names_come_from_image_and_motion",
    62: "test_s62_shots_strength_overrides", 66: "test_s66_render_accepts_the_shots_manifest",
    70: "test_s70_lone_stills_lora_is_0_8_in_shots_mode", 71: "test_s71_shots_pins_the_seed",
}


def t(*ids):
    return [T + S[i] for i in ids]


GROUP_TAIL = ('        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)\n'
              '        group_cmd.append("--shots")\n        log_path = ')

# (label, [(file, old, new, expected count of old)], [targets])
MUTATIONS = [
    ("panel_strengths ignores shots (lone -> 1.0)",
     [(LIB, "    if len(names) == 1 and not shots:", "    if len(names) == 1:", 1)],
     t(2, 61, 70)),
    ("shots strength ignores the character.json override",
     [(LIB, "    return {n: (by_name[n].strength if by_name[n].strength is not None else character_strength)\n",
       "    return {n: (character_strength if shots else (by_name[n].strength if by_name[n].strength is not None else character_strength))\n", 1)],
     t(2, 62)),
    ("SHOTS_CHARACTER_STRENGTH = 1.0",
     [(LIB, "SHOTS_CHARACTER_STRENGTH = 0.8\n", "SHOTS_CHARACTER_STRENGTH = 1.0\n", 1)],
     t(1, 34, 62)),
    ("build_cast_block ignores shots",
     [(LIB, "    lines.append(SHOTS_CAST_BLOCK_RULES if shots else CAST_BLOCK_RULES)",
       "    lines.append(CAST_BLOCK_RULES)", 1)],
     t(3, 34)),
    ("find_phrases sorts shortest first",
     [(LIB, "key=lambda p: (-len(p), p.lower(), p)", "key=lambda p: (len(p), p.lower(), p)", 1)],
     t(4, 17)),
    ("find_phrases overlap check removed",
     [(LIB, "            if any(start < e and s < end for s, e, _ in claimed):\n                continue\n", "", 1)],
     t(4, 17)),
    ("find_phrases returns sorted phrases, not first-occurrence order",
     [(LIB, "    return ordered\n", "    return sorted(ordered)\n", 1)],
     t(4)),
    ("roster entry regex accepts unquoted phrases",
     [(LIB, "_ROSTER_ENTRY_RE = re.compile(r'[-*]\\s*[\"“]([^\"“”]+)[\"”]\\s*:\\s*(\\S.*)')",
       "_ROSTER_ENTRY_RE = re.compile(r'[-*]\\s*[\"“]?([^\"“”:]+)[\"”]?\\s*:\\s*(\\S.*)')", 1)],
     t(5)),
    ("roster duplicate check removed",
     [(LIB, "        if phrase.lower() in [p.lower() for p, _ in entries]:", "        if False:", 1)],
     t(5)),
    ("roster section ends at a blank line instead of the next # line",
     [(LIB, '        if stripped.startswith("#"):\n            break\n        if not stripped:\n            continue\n',
       '        if stripped.startswith("#") or not stripped:\n            break\n', 1)],
     t(5)),
    ("roster parse starts at the first line containing 'Characters' anywhere",
     [(LIB, "        if _ROSTER_HEADER_RE.fullmatch(line.strip()):",
       '        if "characters" in line.lower():', 1)],
     t(5)),
    ("S4 lower bound < instead of <=",
     [(LIB, "    if not SHOTS_MOTION_MIN_WORDS <= words <= SHOTS_MOTION_MAX_WORDS:",
       "    if not SHOTS_MOTION_MIN_WORDS < words <= SHOTS_MOTION_MAX_WORDS:", 1)],
     t(6)),
    ("S4 upper bound < instead of <=",
     [(LIB, "    if not SHOTS_MOTION_MIN_WORDS <= words <= SHOTS_MOTION_MAX_WORDS:",
       "    if not SHOTS_MOTION_MIN_WORDS <= words < SHOTS_MOTION_MAX_WORDS:", 1)],
     t(6)),
    ("S4 bounds widened to 9-26",
     [(LIB, "SHOTS_MOTION_MIN_WORDS = 10\nSHOTS_MOTION_MAX_WORDS = 25\n",
       "SHOTS_MOTION_MIN_WORDS = 9\nSHOTS_MOTION_MAX_WORDS = 26\n", 1)],
     t(7)),
    ("camera sentence counted as an action sentence",
     [(LIB, "    actions = [s for s in sentences if not _CAMERA_SENTENCE_RE.match(s)]",
       "    actions = list(sentences)", 1)],
     t(6, 9)),
    ("sentence count check >= 1",
     [(LIB, "    if len(actions) != 1:", "    if len(actions) < 1:", 1)],
     t(7)),
    ("semicolon check removed",
     [(LIB, '    if ";" in motion:', "    if False:", 1)],
     t(7)),
    ("_CHAIN_WORD_RE without \\b",
     [(LIB, '_CHAIN_WORD_RE = re.compile(r"\\b(?:then|', '_CHAIN_WORD_RE = re.compile(r"(?:then|', 1),
      (LIB, 'r"followed\\s+by|as\\s+soon\\s+as)\\b", re.IGNORECASE)',
       'r"followed\\s+by|as\\s+soon\\s+as)", re.IGNORECASE)', 1)],
     t(8)),
    (", and check removed",
     [(LIB, "    if _COMMA_AND_RE.search(motion):", "    if False:", 1)],
     t(7)),
    ("chain-word list drops while",
     [(LIB, 'r"\\b(?:then|while|meanwhile|', 'r"\\b(?:then|meanwhile|', 1)],
     t(7)),
    ("S2 enforced without members",
     [(LIB, "    roster = []\n    if members:\n", "    roster = []\n    if True:\n", 1)],
     t(11, 9)),
    ("S2 skipped with members",
     [(LIB, "    roster = []\n    if members:\n", "    roster = []\n    if False:\n", 1)],
     t(11, 12)),
    ("S6 counts Motion: only",
     [(LIB, '        names = sorted(set(cast_text(p["image"], members)[1])\n'
            '                       | set(cast_text(p["motion"], members)[1]))\n'
            '        if len(names) > SHOTS_MAX_CAST_PER_PANEL:',
       '        names = sorted(set(cast_text(p["motion"], members)[1]))\n'
       '        if len(names) > SHOTS_MAX_CAST_PER_PANEL:', 1)],
     t(15)),
    ("S6 limit 3",
     [(LIB, "SHOTS_MAX_CAST_PER_PANEL = 2\n", "SHOTS_MAX_CAST_PER_PANEL = 3\n", 1)],
     t(15)),
    ("S7 checks Image: instead of Motion:",
     [(LIB, '        found = find_phrases(p["motion"], [m.phrase for m in members] + extras)',
       '        found = find_phrases(p["image"], [m.phrase for m in members] + extras)', 1)],
     t(16)),
    ("S7 ignores extras (cast-only matching)",
     [(LIB, '        found = find_phrases(p["motion"], [m.phrase for m in members] + extras)',
       '        found = find_phrases(p["motion"], [m.phrase for m in members])', 1)],
     t(16)),
    ("advisories appended to violations",
     [(LIB, "    return out\n\n\ndef shots_advisories(",
       "    return out + shots_advisories(panels, members)\n\n\ndef shots_advisories(", 1)],
     t(40, 9)),
    ("W1 compares case/whitespace-sensitively",
     [(LIB, '        image_norm = " ".join(p["image"].split()).lower()', '        image_norm = p["image"]', 1),
      (LIB, '                    and " ".join(m.descriptor.split()).lower() not in image_norm):',
       "                    and m.descriptor not in image_norm):", 1)],
     t(18)),
    ("W2 accepts wide shot",
     [(LIB, 'SHOTS_CLOSE_SHOT_TYPES = ("medium shot", ', 'SHOTS_CLOSE_SHOT_TYPES = ("wide shot", "medium shot", ', 1)],
     t(18)),
    ("rewrite also runs for a pre-existing story.md",
     [(MO, "    if violations and authored is None:", "    if False:", 1)],
     t(38)),
    ("a second rewrite is allowed",
     [(MO, "        violations, advisories = _shots_check(lib, story_md, args.panels, members)\n        if violations:\n"
           '            print("Error: story.md still breaks the shot rules after one rewrite:", file=sys.stderr)',
       "        violations, advisories = _shots_check(lib, story_md, args.panels, members)\n        if violations:\n"
       '            os.replace(story_md, rejected + ".2")\n'
       '            _run_story_agent(cmd, authored["timeout"], story_md)\n'
       "            violations, advisories = _shots_check(lib, story_md, args.panels, members)\n        if violations:\n"
       '            print("Error: story.md still breaks the shot rules after one rewrite:", file=sys.stderr)', 1)],
     t(37)),
    ("rejected draft deleted instead of moved",
     [(MO, "        os.replace(story_md, rejected)\n", "        os.remove(story_md)\n", 1)],
     t(36)),
    ("rewrite prompt omits the violations",
     [(MO, "lib.shots_rewrite_block(violations, args.panels)", "lib.shots_rewrite_block([], args.panels)", 1)],
     t(36)),
    ("rewrite rebuilds cmd instead of reusing it (a different flag set)",
     [(MO, '        cmd = list(authored["cmd"])\n',
       '        cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"), "--workspace", WS, "--user-prompt", ""]\n', 1)],
     t(36) + [R1_OFFLINE]),
    ("_run_story_agent drops the --danger-auto-approve print",
     [(MO, '        print(out or "")\n', "        pass\n", 1)],
     [ITERATE_C1]),
    ("len(cmd[-1]) left as len(prompt)",
     [(MO, "len(cmd[-1])])", "len(prompt)])", 1)],
     t(36)),
    ("shots branch placed after _validate_story_md",
     [(MO, '    if getattr(args, "shots", False):\n        return _phase1_shots_finish(args, story_md, authored)\n\n'
           "    violations = _validate_story_md(", "    violations = _validate_story_md(", 1),
      (MO, '            print("Warning: %s" % w)\n\n    members = getattr(args, "cast_members", None) or []\n',
       '            print("Warning: %s" % w)\n\n    if getattr(args, "shots", False):\n'
       "        return _phase1_shots_finish(args, story_md, authored)\n"
       '    members = getattr(args, "cast_members", None) or []\n', 1)],
     t(35, 36)),
    ("groups computed from Motion: instead of Image:",
     [(MO, 'images._compose_prompt(p["image"], style)', 'images._compose_prompt(p["motion"], style)', 1)],
     t(42)),
    ("groups insert triggers for members without stills",
     [(MO, "        insert = {m.name for m in members if m.stills_lora}", "        insert = {m.name for m in members}", 1)],
     t(42, 45)),
    ("groups not sorted",
     [(MO, "    return sorted(groups.items(), key=lambda g: (len(g[0]), g[0]))", "    return list(groups.items())", 1)],
     t(43)),
    ("--only not replaced",
     [(MO, GROUP_TAIL, '        group_cmd.append("--shots")\n        log_path = ', 1)],
     t(43)),
    ("--shots not appended to group commands",
     [(MO, GROUP_TAIL, '        group_cmd[group_cmd.index("--only") + 1] = _panel_list(panels)\n        log_path = ', 1)],
     t(43, 45)),
    ("a fully rendered group is still run",
     [(MO, "        if not _shots_missing_stills(args, panels):\n"
           '            print("stills group %d/%d (%s): every still exists; skipped"',
       "        if False:\n"
       '            print("stills group %d/%d (%s): every still exists; skipped"', 1)],
     t(43)),
    ("a failing group stops Phase 2 (return 1 inside the loop)",
     [(MO, "                          % (k, len(groups), label, rc, log_path))\n    if failed:\n",
       "                          % (k, len(groups), label, rc, log_path))\n            return 1\n    if failed:\n", 1)],
     t(44)),
    ("Phase 3 shots passes --chain",
     [(MO, '        cmd_manifest += ["--shots"] + _shots_image_flags(args)',
       '        cmd_manifest += ["--chain"] + _shots_image_flags(args)', 1)],
     t(46)),
    ("manifest shots panels 2+ chain",
     [(MA, '            image_path = matched[i - 1]\n            conditioning = "still"\n',
       '            image_path = matched[i - 1]\n            conditioning = "still" if i == 1 else "chain"\n', 1)],
     t(60, 66)),
    ("manifest shots names from Motion: only",
     [(MA, '            if args.shots:\n                names = sorted(set(names) | set(lib.cast_text(p["panel_text"], members)[1]))\n', "", 1)],
     t(61)),
    ("manifest inserts triggers into panel_text",
     [(MA, '            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)\n',
       '            p["motion_prompt"], names = lib.cast_text(p["motion_prompt"], members)\n'
       '            p["panel_text"] = lib.cast_text(p["panel_text"], members)[0]\n', 1)],
     t(61)),
    ("manifest shots writes schema 2",
     [(MA, '        "schema_version": 3 if (args.chain or args.shots) else 2,',
       '        "schema_version": 3 if args.chain else 2,', 1)],
     t(60, 66)),
    ("_phase4_flags keeps stop for shots",
     [(MO, '"skip" if (args.no_stills or getattr(args, "shots", False)) else "stop",',
       '"skip" if args.no_stills else "stop",', 1)],
     t(47)),
    ("redo deletes instead of moving",
     [(MO, "            os.replace(src, dst)\n", "            os.remove(src)\n", 1)],
     t(49)),
    ("redo moves other panels' files",
     [(MO, "    for n in args.redo_panels:\n", "    for n in range(1, args.panels + 1):\n", 1)],
     t(49)),
    ("redo phase placed after phase2_stills",
     [(MO, "        phases = phases[:cut] + (phase_redo_shots,) + phases[cut:]",
       "        phases = phases[:cut + 1] + (phase_redo_shots,) + phases[cut + 1:]", 1)],
     t(48)),
    ("redo phase inserted when redo_panels == []",
     [(MO, '    if getattr(args, "redo_panels", None):\n        cut = phases.index(phase2_stills)',
       '    if getattr(args, "redo_panels", None) is not None:\n        cut = phases.index(phase2_stills)', 1)],
     t(48) + [R1_OFFLINE]),
    ("--redo accepted without --shots",
     [(MO, "    if not args.shots:\n        if args.redo is not None:", "    if not args.shots:\n        if False:", 1)],
     t(33)),
    ("--redo 0 accepted",
     [(MO, "        if not 1 <= n <= args.panels:", "        if not 0 <= n <= args.panels:", 1)],
     t(33)),
    ("dry-run --redo moves files",
     [(MO, '            print("Would move %s -> %s" % (src, dst))',
       "            os.makedirs(os.path.dirname(dst), exist_ok=True); os.replace(src, dst)", 1)],
     t(51)),
    ("bin/ltx-story-images --shots does not pin the seed",
     [(IM, "    grounded = bool(style) or args.shots\n", "    grounded = bool(style)\n", 1)],
     t(71)),
    ("seed pinned always (grounded = True)",
     [(IM, "    grounded = bool(style) or args.shots\n", "    grounded = True\n", 1)],
     t(71) + [R1_IMAGES]),
    ("build_story_prompt ignores shots",
     [(MO, "                else STORY_PROMPT_TEMPLATE_SHOTS if shots else STORY_PROMPT_TEMPLATE)",
       "                else STORY_PROMPT_TEMPLATE)", 1)],
     t(31)),
    ("shots template used without --shots",
     [(MO, "                else STORY_PROMPT_TEMPLATE_SHOTS if shots else STORY_PROMPT_TEMPLATE)",
       "                else STORY_PROMPT_TEMPLATE_SHOTS)", 1)],
     t(32) + [B1]),
    ("ltx-movie gains import re",
     [(MO, "import os\nimport shlex\n", "import os\nimport re\nimport shlex\n", 1)],
     [R1_OFFLINE]),
    ("shots Phase 2 builds its own --lora line",
     [(MO, "        group_cmd = list(cmd)\n" + GROUP_TAIL,
       '        group_cmd = list(cmd) + ([] if True else ["--lora", args.stills_lora_path])\n' + GROUP_TAIL, 1)],
     [R1_OFFLINE]),
]


def run_target(target, root):
    env = dict(os.environ, PYTHONPYCACHEPREFIX=os.path.join(root, "pyc"),
               TMPDIR=os.path.join(root, "tmp"))
    os.makedirs(env["TMPDIR"], exist_ok=True)
    if target.startswith("R1:"):
        cmd = [sys.executable, target[3:]]
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider", target]
    return subprocess.run(cmd, cwd=WS, env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def fresh_run(target):
    root = tempfile.mkdtemp(prefix="shots-mut-")
    try:
        return run_target(target, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    failures = 0
    for number, (label, edits, targets) in enumerate(MUTATIONS, 1):
        originals = {}
        for path, old, _new, count in edits:
            text = originals.setdefault(path, open(os.path.join(WS, path), encoding="utf-8").read())
            found = text.count(old)
            assert found == count, "M%d %s: anchor count %d != %d in %s: %r" % (
                number, label, found, count, path, old[:60])
        for target in targets:
            rc = fresh_run(target)
            assert rc == 0, "M%d %s: control run of %s returned %d" % (number, label, target, rc)
        mutated = dict(originals)
        for path, old, new, _count in edits:
            mutated[path] = mutated[path].replace(old, new)
        try:
            for path, text in mutated.items():
                with open(os.path.join(WS, path), "w", encoding="utf-8") as f:
                    f.write(text)
            results = [(t, fresh_run(t)) for t in targets]
        finally:
            for path, text in originals.items():
                with open(os.path.join(WS, path), "w", encoding="utf-8") as f:
                    f.write(text)
        broken = [t for t, rc in results
                  if not t.startswith("R1:") and rc not in (0, 1)]
        caught = [t for t, rc in results if rc != 0 and t not in broken]
        verdict = "CAUGHT" if caught and not broken else ("BROKEN" if broken else "SURVIVED")
        if verdict != "CAUGHT":
            failures += 1
        print("M%02d %-8s %s  <- %s" % (number, verdict, label,
                                        ", ".join("%s=%d" % (t.split("::")[-1], rc) for t, rc in results)))
        sys.stdout.flush()
    print("RESULT: %d/%d caught" % (len(MUTATIONS) - failures, len(MUTATIONS)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
````

Expected: 63 lines `Mxx CAUGHT ...` and a final `RESULT: 63/63 caught` (observed in the replay; about 7 minutes). The 63 rows are the spec's 62 below with "S4 bounds `<` instead of `<=` (either end)" split into one row per end (Decision 17); Decision 18 lists the rows whose spec-named catcher passes while another catcher fails. The spec's mutation table, verbatim:

**Mutation checks.** Apply each mutation alone, run the named file, confirm at least one named test fails, revert. "R1:x" names an existing-suite pin.

| Mutation | Must fail |
|---|---|
| `panel_strengths` ignores `shots` (lone → 1.0) | S2, S61, S70 |
| shots strength ignores the `character.json` override | S2, S62 |
| `SHOTS_CHARACTER_STRENGTH = 1.0` | S1, S34, S62 |
| `build_cast_block` ignores `shots` | S3, S34 |
| `find_phrases` sorts shortest first | S4, S17 |
| `find_phrases` overlap check removed | S4, S17 |
| `find_phrases` returns sorted phrases, not first-occurrence order | S4 |
| roster entry regex accepts unquoted phrases | S5 |
| roster duplicate check removed | S5 |
| roster section ends at a blank line instead of the next `#` line | S5 |
| roster parse starts at the first line containing "Characters" anywhere | S5 (header-after-panels case reads a panel line) |
| S4 bounds `<` instead of `<=` (either end) | S6 (10- and 25-word cases) |
| S4 bounds widened to 9-26 | S7 |
| camera sentence counted as an action sentence | S6, S43's fixture via S9 |
| sentence count check `>= 1` | S7 |
| semicolon check removed | S7 |
| `_CHAIN_WORD_RE` without `\b` | S8 (`strengthened`) |
| `, and` check removed | S7 |
| chain-word list drops `while` | S7 |
| S2 enforced without members | S11, S9 |
| S2 skipped with members | S11, S12 |
| S6 counts Motion: only | S15 (Image: case) |
| S6 limit 3 | S15 |
| S7 checks Image: instead of Motion: | S16 (`SHOTS_OK` panel 1 would fail) |
| S7 ignores extras (cast-only matching) | S16 |
| advisories appended to violations | S40, S9 |
| W1 compares case/whitespace-sensitively | S18 |
| W2 accepts `wide shot` | S18 |
| rewrite also runs for a pre-existing story.md | S38 |
| a second rewrite is allowed | S37 |
| rejected draft overwritten or deleted instead of moved | S36 |
| rewrite prompt omits the violations | S36 |
| rewrite rebuilds `cmd` instead of reusing it (a different flag set) | S36, R1:L19a |
| `_run_story_agent` drops the `--danger-auto-approve` print | R1 (iterate-flags C1 tests) |
| `len(cmd[-1])` left as `len(prompt)` | S36 (NameError) |
| shots branch placed after `_validate_story_md` | S35 (chain-image warning text), S36 |
| groups computed from Motion: instead of Image: | S42 |
| groups insert triggers for members without stills | S42, S45 |
| groups not sorted | S43 |
| `--only` not replaced | S43 |
| `--shots` not appended to group commands | S43, S45 (strength 1.0) |
| a fully rendered group is still run | S43 |
| a failing group stops Phase 2 (`return 1` inside the loop) | S44 |
| Phase 3 shots passes `--chain` | S46 |
| manifest shots panels 2+ `chain` | S60, S66 |
| manifest shots names from Motion: only | S61 (panel 3) |
| manifest inserts triggers into `panel_text` | S61 |
| manifest shots writes schema 2 | S60, S66 |
| `_phase4_flags` keeps `stop` for shots | S47 |
| redo deletes instead of moving | S49 |
| redo moves other panels' files | S49 |
| redo phase placed after `phase2_stills` | S48 |
| redo phase inserted when `redo_panels == []` | S48, R1:L41 |
| `--redo` accepted without `--shots` | S33 |
| `--redo 0` accepted | S33 |
| dry-run `--redo` moves files | S51 |
| bin/ltx-story-images `--shots` does not pin the seed | S71 |
| seed pinned always (`grounded = True`) | S71 (no-`--shots` case), R1:I-suite |
| `build_story_prompt` ignores `shots` | S31 |
| shots template used without `--shots` | S32, B1 |
| ltx-movie gains `import re` | R1:L7j |
| shots Phase 2 builds its own `--lora` line | R1:L1z5 |

### A4: regression suites (R1, R2)

Regression check (run from `WS`; each line must match exactly):

````bash
for t in test_ltx_movie_offline test_ltx_story_images test_ltx_mlx_render test_ltx2_mlx_video_skill test_ltx_story_manifest_chain test_ltx_image_fit; do python3 tests/$t.py > /tmp/shotsplan-r1-$t.log 2>&1; echo "$t rc=$? $(tail -1 /tmp/shotsplan-r1-$t.log)"; done
python3 tests/check_ltx2_mlx_no_forbidden_imports.py > /tmp/shotsplan-r1-forbidden.log 2>&1; echo "forbidden_imports rc=$? $(tail -1 /tmp/shotsplan-r1-forbidden.log)"
python3 -m pytest tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-casting.log 2>&1; echo "casting rc=$? $(tail -1 /tmp/shotsplan-r1-casting.log)"
python3 -m pytest tests/test_z_image_skill_cache.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-zcache.log 2>&1; echo "z_image_skill_cache rc=$? $(tail -1 /tmp/shotsplan-r1-zcache.log)"
python3 -m pytest tests/test_ltx_movie_iterate_flags.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-iterate.log 2>&1; echo "iterate_flags rc=$? $(tail -1 /tmp/shotsplan-r1-iterate.log)"
python3 -m pytest tests/test_pipeline_log.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r1-plog.log 2>&1; echo "pipeline_log rc=$? $(tail -1 /tmp/shotsplan-r1-plog.log)"
````

Expected (`<w>` and `<t>` are the warning count and the time, which vary):

````
test_ltx_movie_offline rc=0 OK 344/344
test_ltx_story_images rc=0 OK 101/101
test_ltx_mlx_render rc=0 OK 443/443
test_ltx2_mlx_video_skill rc=0 OK 146/146
test_ltx_story_manifest_chain rc=0 OK 32/32
test_ltx_image_fit rc=0 OK 77/77
forbidden_imports rc=0 RESULT: ok
casting rc=0 178 passed, <w> warnings in <t>s
z_image_skill_cache rc=0 13 passed, 1 warning in <t>s
iterate_flags rc=0 13 passed, <w> warnings in <t>s
pipeline_log rc=0 17 passed, <w> warnings in <t>s
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

````bash
python3 -m pytest tests/test_deploy_pkg.py -q --color=no -p no:cacheprovider > /tmp/shotsplan-r2.log 2>&1; echo "deploy rc=$? $(tail -1 /tmp/shotsplan-r2.log)"
/usr/bin/python3 -m unittest tests.test_deploy_pkg > /tmp/shotsplan-r2u.log 2>&1; echo "unittest rc=$?"; tail -3 /tmp/shotsplan-r2u.log
````

Expected: `deploy rc=0 165 passed in <t>s`; then `unittest rc=0`, `Ran 165 tests in <t>s`, a blank line, `OK` (SC10: the package file set is unchanged, spec 8). Then this must print nothing (R1: none of those files changed):

````bash
git diff --stat c7309e1 HEAD -- tests/test_ltx_movie_offline.py tests/test_ltx_story_images.py tests/test_ltx_mlx_render.py tests/test_ltx2_mlx_video_skill.py tests/test_ltx_story_manifest_chain.py tests/test_ltx_image_fit.py tests/check_ltx2_mlx_no_forbidden_imports.py tests/test_casting_pipeline.py tests/test_casting_regression.py tests/test_character_lib.py tests/test_character_dataset.py tests/test_character_tool.py tests/test_z_image_skill_multi_lora.py tests/test_z_image_skill_cache.py tests/test_ltx_movie_iterate_flags.py tests/test_pipeline_log.py tests/test_deploy_pkg.py scripts/ bin/ltx-mlx-render ltx2_mlx_video_skill.py z_image_skill.py bin/qwen-agent bin/iterate-story
````

`tests/test_ltx_movie_offline.py` and `tests/test_ltx_story_images.py` are run with `python3` directly, never with pytest: under pytest their `check()` helper reports a false green.

### A5: scope check

````bash
git diff --name-only c7309e1 HEAD | sort
git log --format=%s c7309e1..HEAD
````

Expected, the first command exactly (if the orchestrator committed this plan under `docs/superpowers/plans/`, that one path is added):

````
qwen-agent-workspace/bin/ltx-movie
qwen-agent-workspace/bin/ltx-story-images
qwen-agent-workspace/bin/ltx-story-manifest
qwen-agent-workspace/character_lib.py
qwen-agent-workspace/tests/test_shots_mode.py
````

The second lists the nine task commits (Tasks 2-10), newest first, each with its component prefix:

````
ltx-movie: --redo, shots Phase 3/4 flags and the shots dry run
ltx-movie: shots-mode Phase 2, one stills run per LoRA-set group
ltx-movie: shots-mode Phase 1 validation and the one rewrite
ltx-movie: extract _run_story_agent from phase1_story (no behaviour change)
ltx-movie: --shots/--redo arguments, the shots story template and the shots Cast block
ltx-mlx-render: test that a shots manifest renders unchanged (S66)
ltx-story-images: --shots pins the seed and uses the shots strength rule
ltx-story-manifest: --shots manifests, every panel conditioned on its own still
character_lib: shots-mode strength, Cast block, roster parser, shot rules and rewrite block
````

`git show --stat <commit>` of each touches only that task's files (the Files list of the task).

### A6: design review

Dispatch the `design-reviewer` (Opus, high effort) on the commit range `c7309e1..HEAD`. Give it the spec path, this plan, the Review Focus above, and Decisions 1-20, and state that no work is in flight. Require a per-finding disposition table (accept, reject with evidence, or defer). If the verdict is NEEDS-FIX, the reviewer writes the verbatim patch and the executor only applies it; then rerun A1-A5. Pushing remains gated by this review.

### Live gates (orchestrator or user, on hardware, one at a time, no concurrent renders)

Spec 10.8, verbatim:

#### 10.8 Live gates (main thread or user, on hardware, one at a time, no concurrent renders)

Before each gate, record `bin/story-server status` and `psutil.virtual_memory().available / 2**30`. Phase 1 needs the story server `SERVING vision` (qwen38-6bit). Phase 1b stops it.

**L-S1. The rescue as a shots story.**

```
bin/ltx-movie "Deep in a cedar forest, three robbers corner the Shogun's daughter, the woman in grey: a stocky bearded robber in a ragged brown jacket with a short knife, a tall gaunt shaved-head robber in a patched blue tunic with a wooden club, and a young wiry spear robber bare-chested under a straw cape with a bamboo spear. They grab at her jade hairpins and kimono; she fights back with a fallen cedar branch, striking the club robber's forearm, until the spear robber drives the butt of his spear into her ribs and she drops to her knees. The ronin sprints in along the trail, shoulder-charges the bearded robber off her, draws his katana and knocks the spear aside, drives the pommel into the spear robber's jaw, and slips the club robber's swing with a cut across his forearm. The three robbers scramble up and flee into the ferns. The ronin sheathes his sword and helps her to her feet. Relatively little dialogue; focus on realistic, physically grounded action." --story-id ronin-rescue-shots-ls1 --shots --panels 14 --no-review --model /Users/reubenpatterson/ltx-2-mlx/models/ltx-2.5-mlx-q8 --character kyra --character ronin
bin/judge-clips --story-id ronin-rescue-shots-ls1
```

The narrative is the rescue's verbatim (`ronin-rescue-cast-20261006/iterate-story.log:28`). `ronin-rescue-shots-ls1` must not exist beforehand; if it does, use `-ls1b`. Pass conditions, all required:

1. Exit 0. 14 clips. `story.md` passes `shots_violations`. Record whether a `story.rejected-*.md` exists, its violation count, and the rewrite's count (9.2).
2. `manifest.json`:
   - `schema_version 3`;
   - every panel `conditioning "still"` with its own `images/panel_NN.png`;
   - every `characters` strength 0.8;
   - at most 2 characters per panel;
   - for every panel, the `characters` names equal `sorted(set(cast_text(Image:)) | set(cast_text(Motion:)))`, computed in a REPL from story.md.
3. Every `clips/panel_NN.mp4.provenance.json` has `conditioning "still"` and LoRA strengths 0.8. The `images/stills-group-KK.log` files number at most 4, and each shows `fused <n> LoRA adapter(s)` equal to its group size (or no fuse line for the `()` group).
4. **Eyeball (decisive):**
   - in every shot whose `characters` include kyra, her still and her clip's first, middle and last frames show her trained identity (face, three jade hairpins, pale grey kimono with silver obi), with no male or ronin traits;
   - in every ronin shot, topknot, scarred brow and indigo haori, with no female, kimono or hairpin traits;
   - **in every extras-only shot, the robbers stay robbers**: no kimono, no topknot or samurai restyle, no second woman in grey. These are the specific `ronin-rescue-cast-20261006` failures;
   - no cast character vanishes from a shot whose Image: places them (the solo07 0.7 failure).
5. Record, side by side with `ronin-rescue-cast-20261006` (means: motion_fidelity 4.25, physical_realism 4.625, temporal_stability 3.5, narrative_clarity 3) and `-solo07` (4.125 / 5.125 / 3.875 / 3):
   - this run's per-clip and mean motion_fidelity, physical_realism and temporal_stability, and narrative_clarity;
   - `seam_continuity` is recorded but not compared (cuts by design, G4).
   - **KPI K1:** mean motion_fidelity > 4.25. K1 does not gate. If it fails, record "single-action hypothesis not confirmed" for the user.
6. Record the Phase 2 wall-clock (from `stills-group-*.log` timings) against the 9.3 estimate.

**L-S2. `--redo` one panel.** Run after L-S1, on the same story.

1. Record sha256 of every `images/panel_NN.png` and `clips/panel_NN.mp4`.
2. Choose `K` = the lowest panel whose `characters` has exactly one entry. In story.md, change that panel's shot-type words in `Image:` (`medium shot` ↔ `medium close-up`) so that its still must change. Leave everything else as it is. Record the edit.
3. Run the L-S1 `bin/ltx-movie` command with `--redo K` appended.

Pass conditions:

- exit 0;
- `redo/<stamp>-<pid>/` holds the old `images/panel_KK.png`, `clips/panel_KK.mp4`, its provenance and `movie.mp4`, all byte-identical to the step-1 hashes;
- the new `panel_KK.png` and `panel_KK.mp4` hashes differ from the old ones;
- **every other `panel_NN.png` and `panel_NN.mp4` sha256 is unchanged**;
- `movie.log` shows `reusing` for every other panel;
- exactly one stills group ran: the others print `every still exists; skipped`.

Before **every** gate, record `bin/story-server status`, `vm_stat | head -8`, and available GiB (`python3 -c "import psutil; print(psutil.virtual_memory().available / 2**30)"`). Run each long command with `run_in_background` and no `nohup`, and judge it by its exit code and its files, not by a log match. Order: L-S1, then L-S2.

- [ ] **L-S1 (the rescue as a shots story).**
  1. `bin/story-server status` must show `SERVING vision` (qwen38-6bit); if not, start it with `bin/story-server vision` and wait for `SERVING vision`.
  2. `ls -d generated/stories/ronin-rescue-shots-ls1` must fail (no such directory). If it exists, use the story id `ronin-rescue-shots-ls1b` in every command below.
  3. Run the spec's two L-S1 commands above, verbatim and in order (the first is about 14 x (still + clip) of GPU time; Phase 1b stops the story server itself).
  4. Check pass conditions 1-3 with this script (run from `WS`; set `D` to the story dir actually used):

````bash
python3 - <<'EOF'
import glob, importlib.machinery, json, sys
sys.path.insert(0, ".")
import character_lib as L
D = "generated/stories/ronin-rescue-shots-ls1"
sm = importlib.machinery.SourceFileLoader("sm_ls1", "bin/ltx-story-manifest").load_module()
text = open(D + "/story.md", encoding="utf-8").read()
_narrative, panels = sm._parse_prompts_md(D + "/story.md")
members = L.resolve_cast([(None, "kyra"), (None, "ronin")])
print("violations:", L.shots_violations(text, panels, 14, members))
print("advisories:", L.shots_advisories(panels, members))
print("rejected drafts:", sorted(glob.glob(D + "/story.rejected-*.md")))
print("clips:", len(glob.glob(D + "/clips/panel_*.mp4")))
m = json.load(open(D + "/manifest.json"))
assert m["schema_version"] == 3, m["schema_version"]
for p, pt in zip(m["panels"], panels):
    assert p["conditioning"] == "still", p["index"]
    assert p["image_path"].endswith("/images/panel_%02d.png" % p["index"]), p["image_path"]
    names = [c["name"] for c in p["characters"]]
    want = sorted(set(L.cast_text(pt["image"], members)[1]) | set(L.cast_text(pt["motion"], members)[1]))
    assert names == want, (p["index"], names, want)
    assert len(names) <= 2 and all(c["strength"] == 0.8 for c in p["characters"]), p["index"]
    print("panel %2d: %s" % (p["index"], names))
for f in sorted(glob.glob(D + "/clips/panel_*.mp4.provenance.json")):
    prov = json.load(open(f))
    assert prov["conditioning"] == "still", f
    assert all(l["strength"] == 0.8 for l in prov.get("loras", []) if l["kind"] == "character"), f
logs = sorted(glob.glob(D + "/images/stills-group-*.log"))
assert len(logs) <= 4, logs
for log in logs:
    fused = [l.strip() for l in open(log, encoding="utf-8", errors="replace") if "LoRA adapter(s)" in l]
    print(log, fused or "no fuse line")
print("L-S1 mechanical checks passed")
EOF
````

  Pass conditions 1-3: the script prints `violations: []` and ends with `L-S1 mechanical checks passed`; `clips: 14`; the first command exited 0; each group log's `[z_image_skill] fused <n> LoRA adapter(s)` count equals that group's number of names in its `stills group k/n (...)` line in the run's stdout, which `pipeline_log` also appends to `<story>/iterate-story.log` (no fuse line for the `no character LoRAs` group). Record the rejected-draft list and, if one exists, its violation count and the rewrite's (from the stdout of the run: the `Warning:` list, and any `Error:` list).
  5. Pass condition 4 (decisive): the user eyeballs every still and the first, middle and last frame of every clip against spec L-S1 item 4. Extract frames with `ffmpeg -v error -i <clip> -vf "select=eq(n\,0)+eq(n\,120)+eq(n\,240)" -vsync 0 /tmp/ls1-frames/panel_NN_%d.png` (into a new `/tmp/ls1-frames/` directory).
  6. Pass condition 5: from `generated/stories/<id>/clips_judgment.json`, record per-clip and mean motion_fidelity, physical_realism, temporal_stability, and narrative_clarity, side by side with `ronin-rescue-cast-20261006` (4.25 / 4.625 / 3.5 / 3) and `-solo07` (4.125 / 5.125 / 3.875 / 3). Record seam_continuity without comparing it. KPI K1: mean motion_fidelity > 4.25; it does not gate; if it fails, record "single-action hypothesis not confirmed" for the user.
  7. Pass condition 6: record the Phase 2 wall-clock (the first and last timestamps of each `stills-group-*.log`, or the `panel N -> ... (seed S, Ts)` seconds it prints) against spec 9.3's 22-27 min estimate.

- [ ] **L-S2 (`--redo` one panel; after L-S1, same story).**
  1. Record hashes: `shasum -a 256 generated/stories/<id>/images/panel_*.png generated/stories/<id>/clips/panel_*.mp4 generated/stories/<id>/movie.mp4 > /tmp/ls2-before.sha256`.
  2. K = the lowest panel whose `characters` in `manifest.json` has exactly one entry (`python3 -c "import json; print(next(p['index'] for p in json.load(open('generated/stories/<id>/manifest.json'))['panels'] if len(p['characters']) == 1))"`). In `story.md`, in panel K's `Image:` field only, change `medium shot` to `medium close-up` (or `medium close-up` to `medium shot`). Change nothing else, and record the edit (`git diff --no-index` against a copy saved first, or a before/after quote).
  3. Run the L-S1 `bin/ltx-movie` command with `--redo K` appended.
  4. Pass conditions (spec L-S2): exit 0; `redo/<stamp>-<pid>/` holds `images/panel_KK.png`, `clips/panel_KK.mp4`, `clips/panel_KK.mp4.provenance.json` and `movie.mp4`, each matching `/tmp/ls2-before.sha256`; the new `panel_KK.png` and `panel_KK.mp4` hashes differ; every other `panel_NN.png` and `panel_NN.mp4` hash is unchanged (`shasum -a 256 -c /tmp/ls2-before.sha256` fails only for panel KK's two files and `movie.mp4`); `movie.log` has `panel N: reusing` for every N != K; and exactly one `stills group` line in the run's stdout (and in the newest `iterate-story.log` record) lacks `every still exists; skipped`.

## Provenance of this document

Generated on 2026-10-06 against the spec at `c7309e1` by a generator that spliced every spec code block, spec table and base-file anchor byte for byte, from a scratch build in `/tmp/shotsplan/dev`. The plan text was then replayed task by task (Tasks 1-10 and Final Acceptance A1-A5) onto a fresh `git archive` export of `c7309e1` set up as a git repository at `/tmp/shotsplan/sim`, applying every block with the block applier from this file and running every command shown; every count above is from that replay. The test IDs of spec 10.3-10.6 each map to exactly one test function and one task, which the A1 check confirms. Live gates L-S1 and L-S2 have not been run.
