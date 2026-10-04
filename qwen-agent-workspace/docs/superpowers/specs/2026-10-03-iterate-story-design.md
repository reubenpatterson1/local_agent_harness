# bin/iterate-story -- Design Spec (Phase 2 of the self-improvement loop: text-level orchestration)

Date: 2026-10-03
Status: The design was approved section by section with the user in brainstorming, and this document transcribes it. Choices made while writing this document to remove ambiguity are marked **[spec choice]**. Items the brainstorm did not settle are listed in Section 8 (Known gaps / open questions). **G1 and G2 are RESOLVED** (Sections 4.3 and 3.5 respectively; see Section 8 for pointers). **G19 is RESOLVED, partially** (Section 3.2's conflicting-declaration removal; see Section 8 for the residual uncertainty that remains open). Nothing in this spec is blocked. G3 through G18 remain documented spec choices / known limitations, unchanged.

Workspace root (`WS`): `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace/`

---

## 0. Purpose and scope

### 0.1 Purpose

This is Phase 2 of the self-improvement-loop project. Phase 1 shipped `bin/judge-story` (`docs/superpowers/specs/2026-10-02-judge-story-design.md`), which lets a human judge one `story.md` by hand and get back a revised prompt. Phase 2 automates the cycle that the manual Phase 1 exercise proved out:

judge -> revise prompt -> regenerate -> re-judge

It repeats this until a stopping condition is met, then leaves the best-scoring version of the story as the live `story.md`.

This spec covers only the **text-level orchestration loop**. Judging or fine-tuning panels, stills, or video clips, and LoRA training with `ltx-trainer`, are out of scope. Each will be designed as a separate future sub-project.

### 0.2 Grounding evidence (transcribed from the brainstorm; not re-derived here)

The user ran three rounds of judge -> revise -> regenerate -> re-judge by hand, against a real 20-panel story (story-id `ronin-generalship`) on this 48 GB M1 host. The rounds used `bin/judge-story` and direct `bin/qwen-agent` calls.

Scores are listed in the order pacing_progression, action_plausibility, visual_specificity, continuity.

| Step | Scores | Finding |
|---|---|---|
| Round 1 -> 2 (prompt-only revision) | 4,4,5,2 -> 5,4,4,3 | Marginal gain. The regenerated story broke the prior round's explicit hard rule ("the ronin must not be in the clearing during the attack"). |
| Judge-prompt-only change (rule-by-rule compliance checklist added to `bin/judge-story`'s `SYSTEM_PROMPT`, commit `a7a2c5c`), re-judging the same v2 story | 5,4,4,3 -> 5,5,5,4 | A sharper judge alone changed the measured critique without touching generation. |
| Round 2 -> 3 (regenerated with the sharper judge's revised prompt) | plateau at 5,5,5,4 | No further movement. The judge's own `revised_prompt` also **drifted out of scope** without being asked: it expanded the story from the user's 20 panels to 30, apparently to make room to enforce "one motion per panel." This is the motivating incident for the drift guardrail (Section 3.1-3.2). |

Observed pattern across the rounds:

- Each critique found new, more granular violations instead of converging.
- Each revised prompt was longer and more prescriptive than the last.
- The generation model did not reliably follow the explicit rules from its own previous round. The model was `qwen38-6bit`, served by `bin/story-server vision` at this host's standard `GPU_MEM_UTIL=0.70`.

On-disk state of `generated/stories/ronin-generalship/`, observed 2026-10-03 while writing this spec:

- `story.v1.md`, `story_prompt.v1.txt`, `judgment.v1.json` (scores 4,4,5,2)
- `story.v2.md`, `story_prompt.v2.txt`, `judgment.v2.json` (scores 5,5,5,4)
- Live `story.md` (20 `## Panel` headers) and `story_prompt.txt` (asks for "EXACTLY 20 panel sections")
- Live `judgment.json` (scores 5,5,5,4, timestamp `2026-10-03T05:18:49Z`) and `story_prompt.revised.txt`. The revised prompt asks for "EXACTLY 30 panel sections"; this is the drift incident.

The brief described the live `judgment.json` as deleted. On disk it is present (see G10). `bin/iterate-story` must not collide with or overwrite any existing `.vN` file (Section 1.4).

Approval-gate facts from `bin/qwen-agent`, confirmed by direct source investigation:

- When `write_file` targets an existing path in one-shot mode with no answer available on stdin, the call is denied immediately with `deny_reason: "eof_stdin_unattended"`. Nothing waits for an answer.
  - `_prompt_line` is at `bin/qwen-agent:232-247`.
  - `confirm()` is at `:1003-1033`.
  - The EOFError-to-`deny_reason` mapping is at `:1009-1014`.
  - `should_auto_approve()` is at `:874-881`. It auto-approves `write_file` only when the target does not exist.
- `--danger-auto-approve` already exists (`bin/qwen-agent:3685-3690`, dispatch at `:1696-1700`). It skips confirmation for every tool call except `promote`, which is hard-excluded. It is not limited to `write_file` overwrites.
  - Choosing one broad bypass flag over fine-grained per-tool approval is an established risk-tolerance decision; a prior session accepted it.
- `bin/ltx-movie`'s `phase1_story()` (`bin/ltx-movie:654-744`) never passes `--danger-auto-approve` to its `qwen-agent` subprocess.
  - The command built at `:671-681` does not include it.
  - `Popen` at `:686-687` does not redirect stdin.
  - So an unattended `--force-story` rerun would hit the same `eof_stdin_unattended` denial today. Section 4.2 closes this gap.

### 0.3 In scope (the whole deliverable)

| # | Item | File |
|---|---|---|
| D1 | New standalone script | `bin/iterate-story` (new) |
| D2 | Tests for D1 | `tests/test_iterate_story.py` (new) |
| D3 | Three companion changes: `--story-prompt-override` (Section 4.1), `--danger-auto-approve` passed when `--force-story` and `--no-review` are both given (Section 4.2), and `--story-only` plus optional `narrative` (Section 4.3, resolving G1) | `bin/ltx-movie` (edit) |
| D4 | Tests for D3 **[spec choice: new file; see G12]** | `tests/test_ltx_movie_iterate_flags.py` (new) |

No other file is created or modified.

### 0.4 Out of scope

- Judging or fine-tuning panels, stills, or video clips; LoRA training with `ltx-trainer`. These are separate future sub-projects.
- Any change to `bin/judge-story`, including its `SYSTEM_PROMPT`, schema, or outputs. D1 invokes it unchanged.
- Any change to `bin/qwen-agent`.
- Pinned fields other than the panel count (Section 3.1). The design leaves room to add more later but defines none.
- A `--story-md` path mode. `bin/ltx-movie` operates only by story-id.
- Retrying a failed `judge-story` or `ltx-movie` subprocess call.
- Running rounds in parallel, or running several story-ids in one invocation.
- Wiring `bin/iterate-story` into `bin/ltx-movie`'s `_phase_sequence`.
- Adding `bin/iterate-story` to the deploy package (`tests/test_deploy_pkg.py`). It is a dev-machine tool, like `bin/judge-story`.
- A shared Python module. Path logic is duplicated inline, following repo convention.
- Handling Ctrl-C / SIGINT (G14).
- Passing `--no-stills`, `--seed-image`, `--story-model`, or `--story-context-window` through from `bin/iterate-story` to `bin/ltx-movie`. This version of `bin/iterate-story` supports only the plain text-generation regeneration path (no seed image), matching how Phase 1 was manually exercised in Section 0.2. A host that needs one of these passed through is a follow-up, not part of this spec.

### 0.5 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SC1 | Each round runs `bin/judge-story` and archives the judged triple under the next free version suffix. If the run does not stop, the round then regenerates through `bin/ltx-movie` with the pinned-panel instruction appended last | T-M1, T-M2 |
| SC2 | The three stopping criteria are evaluated in the order threshold, plateau, max-rounds. Plateau compares only against the immediately previous round | T-P4 |
| SC3 | At exit, the live `story.md`, `story_prompt.txt`, and `judgment.json` hold the best round's content (highest per-dimension minimum, then highest average, then earliest). This also holds after a mid-loop subprocess failure | T-P5, T-M3, T-M5, T-M6 |
| SC4 | Existing `.vN` files are never overwritten. Given `story.v1.md` and `story.v2.md`, the first archive is `.v3` | T-P3, T-M3 |
| SC5 | Exit codes: 0 for any stopping reason, 1 for a subprocess failure, 2 for argument or precondition failure | T-M1, T-M4, T-M5, T-M7, T-M8 |
| SC6 | `run-summary.json` and the stdout lines match Section 5 exactly | T-M1, T-M3 |
| SC7 | `bin/ltx-movie --story-prompt-override PATH` sends the file's content verbatim as `--user-prompt` and persists it to `story_prompt.txt` | T-L5 |
| SC8 | `bin/ltx-movie` adds `--danger-auto-approve` only when `--force-story` and `--no-review` are both given | T-L1 to T-L4 |
| SC9 | No test makes a real subprocess, API, or generation call | Autouse guards (Section 7.1); review of the test files |
| SC10 | D3 does not break the existing `bin/ltx-movie` suite | R1 |
| SC11 | `bin/ltx-movie --story-only` runs Phase 0 (if `--seed-image`) and Phase 1 only; `phase_release_story_server` and Phases 2-4 never run, regardless of `--story-server-stop-after-story`'s own value | T-L8, T-L9 |
| SC12 | `bin/ltx-movie` requires exactly one source of the story prompt: if neither `narrative` nor `--story-prompt-override` is given, it exits 2 before any subprocess runs; `narrative` being absent does not crash Phase 1 or `main()` when `--story-prompt-override` is given | T-L10, T-L11 |
| SC13 | Every `bin/iterate-story` regeneration call passes `--panels <pinned_panel_count>` and `--story-only`, and never passes `--danger-auto-approve` directly | T-M2 |
| SC14 | `bin/iterate-story` treats an unchanged `story.md` after a `bin/ltx-movie` regeneration call as a round failure, even when the call exited 0 | T-M9 |

### 0.6 Must-have vs nice-to-have

Every requirement in Sections 1-7 is a must-have. This phase has no nice-to-haves. Nothing beyond these sections is to be built.

### 0.7 Implementation sequencing

G1 and G2 are resolved (Sections 4.3 and 3.5). Nothing in this spec is blocked: D1-D4 and all of Sections 1-7, including the final Section 3.4.2 regeneration argv and its T-M2 assertion, can be implemented in one pass. The only remaining future step is M1 (Section 7.6), a manual, real end-to-end run against an actual story-id, which is inherently something that happens after implementation rather than something blocking it.

---

## 1. Architecture

### 1.1 Script conventions

`bin/iterate-story` follows the existing `bin/*` convention, exactly as `bin/judge-story` does:

- Plain executable script with shebang `#!/usr/bin/env python3`, a module docstring, no file extension, and the executable bit set (`chmod +x`).
- `def main(argv=None):` returns an `int`. The file ends with:
  ```python
  if __name__ == "__main__":
      sys.exit(main())
  ```
- It imports nothing from another `bin/*` file and introduces no shared module. `bin/judge-story` and `bin/ltx-movie` are invoked as subprocesses only.
- Top-level imports are standard library only: `argparse`, `datetime`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`.
- The docstring states the following, in prose of the implementer's choosing:
  - the purpose (Section 0.1)
  - the usage line (Section 2.1)
  - the exit codes (Section 2.4)
  - that it requires `ANTHROPIC_API_KEY`, which it does not check itself (Section 2.3)

### 1.2 Round definition and numbering **[spec choice]**

A **round** is one call to `bin/judge-story` against the current live `story.md`, plus everything that follows before the next judge call. Rounds are numbered 1, 2, 3, ... within a run.

- **Round 1 judges the unmodified pre-loop `story.md`.** The brief calls the original pre-loop state "round 0" and includes it in best-round selection "if it was judged". In this spec that state is round 1. It is always judged when round 1's judge call succeeds, and it is always a best-round candidate.
- Why round 1 and not round 0: three other approved statements hold literally only under this numbering:
  - "Round 1 has no previous round to compare against, so plateau can only trigger starting at round 2."
  - "Before archiving round 1, scan..."
  - "Each round: 1. run `bin/judge-story` against the current `story.md`."

  See G3.
- `--max-rounds` counts judged rounds. The default of 5 means at most 5 `judge-story` calls and at most 4 regenerations. The run never ends on an unjudged regenerated story. See G4.

A round has these steps, in this exact order:

1. **Judge.** Run `bin/judge-story --story-id <id>` (Section 3.4.1). It writes the live `judgment.json` (and `story_prompt.revised.txt`).
2. **Read.** Load the live `judgment.json`. Extract the four scores in `SCORE_KEYS` order and `revised_prompt`.
3. **Archive.** Copy the live `story.md`, `story_prompt.txt`, and `judgment.json` to `story.v<N>.md`, `story_prompt.v<N>.txt`, and `judgment.v<N>.json`, where `N = version_base + round` (Section 1.4).
   - **[spec choice: the archive is taken right after judging, not after regeneration.]** The brief lists archiving as step 5, after the regeneration call. At that point the live `story.md` and `story_prompt.txt` have already been replaced by the next story, while `judgment.json` still judges the previous one. That archived triple would be inconsistent, and the best-round promotion (Section 1.5) needs consistent triples. The set of archived files is unchanged; only the timing moved. See G5.
4. **Report.** Append the round's record (Section 5.2) and print the round line (Section 5.1).
5. **Stop check.** Evaluate the stopping criteria (Section 3.3). If a criterion matches, end the loop.
6. **Regenerate.**
   - Record `pre_hash = story_md_hash(story_md_path)` (Section 3.5).
   - Build the next prompt: `revised_prompt` with the pinned-panel instruction appended (Section 3.2).
   - Write it to a temp file.
   - Run `bin/ltx-movie` with `--panels`, `--story-only`, and `--story-prompt-override` (Section 3.4.2).
   - Delete the temp file.
   - If the subprocess exited nonzero: E6 (Section 6).
   - Otherwise, compute `post_hash = story_md_hash(story_md_path)`. If it equals `pre_hash`, the regeneration was a no-op despite the zero exit code: E6b (Section 3.5, Section 6).
   - Otherwise, the next round judges the regenerated `story.md`.

### 1.3 Execution sequence

`main(argv)` performs these steps in this exact order:

1. Parse arguments (Section 2.1). argparse errors and the range checks exit 2 via `SystemExit(2)`.
2. `story_dir, story_md_path, story_prompt_path = resolve_paths(args.story_id)` (Section 2.2).
3. If `story_md_path` is not a regular file (`os.path.isfile`), print E2 to stderr and return 2.
4. If `story_prompt_path` is not a regular file, print E3 to stderr and return 2.
5. Read `story.md` as UTF-8 and compute `pinned_panel_count = count_panels(text)` (Section 3.1). If it is 0, print E4 to stderr and return 2.
6. `version_base = find_version_base(story_dir)` (Section 1.4).
7. Run rounds 1, 2, ... as defined in Section 1.2 until one of these happens:
   - a stopping criterion matches (`stop_reason` is set);
   - a subprocess fails, or `bin/ltx-movie` exits 0 but leaves `story.md` unchanged (Section 3.5) (`failure = (tool_name, round)`, where `tool_name` is `"judge-story"` or `"ltx-movie"`).
8. If at least one round was archived, run `best = select_best_round(...)` (Section 1.5) and `promote(story_dir, best_version)`. If no round was archived, leave the live files untouched.
9. Write `run-summary.json` (Section 5.2). This happens on every path that reaches step 7, including failures.
10. On a stop: print the final line (Section 5.1) to stdout and return 0. On a failure: print the failure messages (Section 6) to stderr and return 1.

### 1.4 Version-suffix numbering (collision avoidance)

Before round 1, `find_version_base(story_dir)` scans the story directory and returns the highest existing version number `N`, or 0 if there is none. Round `r` archives under suffix `v<version_base + r>`. Numbering always continues from the highest number found; it is never hardcoded.

- The brief's required match is `story\.v(\d+)\.md`.
- **[spec choice] The scan also matches `story_prompt\.v(\d+)\.txt` and `judgment\.v(\d+)\.json`, and takes the maximum across all three families.** This keeps the brief's mechanism and guarantees that no `.vN` file of any of the three archived kinds can be overwritten, even when a family is incomplete (for example a stray `judgment.v3.json` with no `story.v3.md`; see G7 and G10).
- Implementation:
  - Use `os.listdir(story_dir)`.
  - Match each name with `VERSION_RE.fullmatch(name)`, where:
    ```python
    VERSION_RE = re.compile(r"(?:story\.v(\d+)\.md|story_prompt\.v(\d+)\.txt|judgment\.v(\d+)\.json)")
    ```
  - Take the non-None group as `int`.
  - Names that do not fully match are ignored, for example `story.v2.md.bak`, `story.vX.md`, and `story.v.md`.
- Concrete case: `ronin-generalship` currently has `.v1` and `.v2` of all three kinds, so `version_base == 2` and round 1 archives as `.v3`. If more manual versions exist when the tool is first run, the first archive moves up accordingly.
- Archive copies use `shutil.copyfile(src, dst)`. `dst` cannot already exist, because `N > version_base`.

### 1.5 Best-round selection and promotion

`select_best_round(rounds)` takes a list of `(round_number, scores_tuple)` pairs in round order and returns the `round_number` with:

1. the highest `min(scores_tuple)`;
2. then the highest average of the four scores. Compare `sum(scores_tuple)` rather than a float average; the order is the same because there are always 4 scores.
3. **[spec choice] then the earliest round** (see G8).

The best round is not necessarily the last round run.

`promote(story_dir, version)` overwrites the live files from the best round's archive:

| Source (archive) | Destination (live) |
|---|---|
| `story.v<N>.md` | `story.md` |
| `story_prompt.v<N>.txt` | `story_prompt.txt` |
| `judgment.v<N>.json` | `judgment.json` |
| the `revised_prompt` field of `judgment.v<N>.json` | `story_prompt.revised.txt` **[spec choice; see G6]** |

- Use `shutil.copyfile` for the first three.
- Write `story_prompt.revised.txt` as UTF-8 with the exact `revised_prompt` string and no trailing newline added, the same format `bin/judge-story` writes.
- Why the fourth row: `bin/judge-story` rewrites `story_prompt.revised.txt` on every judge call. Without this row, after the run it would belong to the last judged round instead of the promoted one.
- Promotion runs even when the best round is the last round (the copy is then a no-op).
- Promotion runs on a failure exit too (Section 6), using the rounds archived so far.

### 1.6 Internal names [spec choice]

The implementer must use these names so tests can target them:

| Name | Kind | Responsibility |
|---|---|---|
| `WS` | module global | `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` |
| `SCORE_KEYS` | module constant | `("pacing_progression", "action_plausibility", "visual_specificity", "continuity")`. Same order as `bin/judge-story` |
| `DEFAULT_MAX_ROUNDS` | module constant | `5` |
| `STOP_THRESHOLD` / `STOP_PLATEAU` / `STOP_MAX_ROUNDS` | module constants | `"threshold met"` / `"plateaued"` / `"max-rounds reached"` |
| `VERSION_RE` | module constant | Section 1.4 |
| `TAIL_LINES` | module constant | `40`. Matches `bin/ltx-movie`'s `splitlines()[-40:]` convention |
| `build_parser()` | function | Returns the `argparse.ArgumentParser` (Section 2.1) |
| `resolve_paths(story_id)` | function | Returns `(story_dir, story_md_path, story_prompt_path)`. Reads `WS` at call time so tests can monkeypatch it |
| `count_panels(story_md_text)` | function | Section 3.1 |
| `PANEL_COUNT_DECLARATION_RE` | module constant | Compiled `re.compile(r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\.")` (Section 3.2) |
| `build_reinjection(pinned_panel_count)` | function | Returns the exact appended string (Section 3.2) |
| `build_next_prompt(revised_prompt, pinned_panel_count)` | function | `PANEL_COUNT_DECLARATION_RE.sub("", revised_prompt) + build_reinjection(pinned_panel_count)` (Section 3.2) |
| `find_version_base(story_dir)` | function | Section 1.4 |
| `evaluate_stop(history, threshold, max_rounds)` | function | Section 3.3. `history` is the list of 4-tuples of scores for rounds 1..r in order, with the current round last. Returns one of the three `STOP_*` strings, or `None` |
| `select_best_round(rounds)` | function | Section 1.5 |
| `promote(story_dir, version)` | function | Section 1.5. `version` is the integer `N` |
| `build_judge_cmd(story_id)` | function | Section 3.4.1 |
| `build_ltx_movie_cmd(story_id, override_path, pinned_panel_count)` | function | Section 3.4.2 |
| `story_md_hash(story_md_path)` | function | Section 3.5. `hashlib.sha256(data).hexdigest()` over the file's raw bytes. Not pure (does I/O) |
| `main(argv=None)` | function | Section 1.3. Returns the exit code |

All of `count_panels`, `build_reinjection`, `build_next_prompt`, `evaluate_stop`, and `select_best_round` are pure: no I/O and no globals.

---

## 2. CLI

### 2.1 Synopsis

```
bin/iterate-story --story-id <id> --threshold <N> [--max-rounds <N>]
```

`build_parser()`:

- `argparse.ArgumentParser(prog="iterate-story", description=<one-line description>)`
- `--story-id`, `dest="story_id"`, `metavar="ID"`, `required=True`
- `--threshold`, `dest="threshold"`, `type=int`, `metavar="N"`, `required=True`. Help text: the per-dimension bar (1-10) that all four scores must meet or exceed.
- `--max-rounds`, `dest="max_rounds"`, `type=int`, `metavar="N"`, `default=DEFAULT_MAX_ROUNDS` (5). Help text: the maximum number of judged rounds.
- No other arguments.

Range checks run in `main()` immediately after `parse_args`, using `parser.error(...)`, which prints usage and raises `SystemExit(2)` **[spec choice: wording]**:

- If `not 1 <= args.threshold <= 10`: `parser.error("--threshold must be an integer from 1 to 10")`.
- If `args.max_rounds < 1`: `parser.error("--max-rounds must be at least 1")`.

There is no `--story-md` mode. This tool writes back through `bin/ltx-movie`, which works only by story-id.

### 2.2 Path resolution

This is the same inline pattern as `bin/judge-story`'s `--story-id` branch (its Section 3.2):

```python
story_dir = os.path.join(WS, "generated", "stories", story_id)
story_md_path = os.path.join(story_dir, "story.md")
story_prompt_path = os.path.join(story_dir, "story_prompt.txt")
```

### 2.3 Preconditions

- `story.md` and `story_prompt.txt` must exist in the story directory (E2, E3; Section 6). These are the same file checks `bin/judge-story` makes.
- `story.md` must contain at least one `## Panel` header line (E4) **[spec choice: a 0-panel pin would produce the nonsensical instruction "EXACTLY 0 panel sections"; see G15]**.
- `ANTHROPIC_API_KEY` is **not** checked by `bin/iterate-story`. If it is unset, round 1's `bin/judge-story` subprocess fails its own check and exits 1. `bin/iterate-story` reports that as a `judge-story` failure in round 1 and exits 1 (E5). The `judge-story` error text reaches the user through the output tail.

### 2.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | A legitimate stop: `threshold met`, `plateaued`, or `max-rounds reached`. None of these is a failure; the stop reason is shown in the report (Section 5), not in the exit code. |
| 1 | Runtime failure: a `bin/judge-story` or `bin/ltx-movie` subprocess exited nonzero (E5, E6), or `bin/ltx-movie` exited 0 but left `story.md` unchanged (E6b, Section 3.5). |
| 2 | Argument or precondition failure: argparse errors, the range checks, E2, E3, E4. This matches `bin/judge-story`'s convention. |

Any nonzero exit code from a subprocess maps to 1. This includes a subprocess exit 2, such as `bin/ltx-movie`'s lock-held exit **[spec choice]**. E6b is the one exit-1 case that is not keyed on a nonzero subprocess exit code at all; it is keyed on the no-op content check instead (Section 3.5).

---

## 3. Round mechanics

### 3.1 Pinned-field extraction

`count_panels(story_md_text)` returns:

```python
len(re.findall(r"^## Panel", story_md_text, flags=re.MULTILINE))
```

- It is computed once, in Section 1.3 step 5, from the `story.md` present when `bin/iterate-story` starts. That value is the pinned panel count for the whole run.
- It is deliberately not parsed from `story_prompt.txt`'s prose. That would be fragile; `story.md`'s own structure is a direct and reliable source.
- Panel count is the only pinned field. It is the one real drift incident observed (Section 0.2).
- The match is anchored at line start and is case-sensitive. `### Panel`, ` ## Panel` (leading space), and `Panel 4` inside body text do not count.
- This is a header count. It is not `bin/ltx-story-manifest`'s stricter `_PANEL_HEADER_RE` (`^##\s*Panel\s*(\d+)\s*[—–-]\s*(.*)$`).

### 3.2 Re-injection

Before each regeneration call, the prompt is `build_next_prompt(revised_prompt, pinned_panel_count)`.

**Conflicting declaration removal `[spec choice]`.** Every real `revised_prompt` observed in this session (three samples, two different pinned counts: 20 and 30) contains this exact sentence, verbatim except for the number, matching the project's own `STORY_PROMPT_TEMPLATE` phrasing convention:

```
The file must contain EXACTLY {N} panel sections, numbered 1 through {N} in order.
```

Left untouched, that sentence states whatever panel count the judge's `revised_prompt` asked for, which can differ from `pinned_panel_count` (the live `ronin-generalship` example: the judge's text asks for 30, the pinned count is 20). Appending the pinned-count sentence after it, as a prior version of this spec did, leaves two contradictory panel-count instructions in the same prompt and relies on recency/salience for the correct one to win. Instead, `build_next_prompt` removes any such declaration before appending its own:

```python
PANEL_COUNT_DECLARATION_RE = re.compile(
    r"The file must contain EXACTLY \d+ panel sections?, numbered 1 through \d+ in order\."
)

def build_next_prompt(revised_prompt, pinned_panel_count):
    cleaned = PANEL_COUNT_DECLARATION_RE.sub("", revised_prompt)
    return cleaned + build_reinjection(pinned_panel_count)
```

- The `s?` handles a possible singular/plural edge case; all three real samples used "sections" (plural).
- **If the pattern matches one or more times** in `revised_prompt`, every match is removed (`.sub` replaces all occurrences, not just the first -- defensive, since one occurrence is the expected case), and the pinned-count sentence is appended at the end, exactly as in the prior design. Net effect: the final prompt contains the sentence exactly once, stating the pinned count, never two contradicting counts.
- **If the pattern does not match** -- the judge omitted the sentence, or phrased it differently than expected -- `.sub` is a no-op and the function falls back to the original behavior: `revised_prompt` unmodified, with the pinned-count sentence appended. This is the defensive fallback, not the expected common case.
- Because `.sub` on zero matches returns the input unchanged, both cases are implemented by the same unconditional call; there is no separate `if` branch for "pattern found" versus "not found".
- This is a textual removal only. No whitespace cleanup runs afterward, so removing a match from the middle of the text can leave adjacent blank lines where the sentence used to be. That is accepted: the spec only fixes the one structural, mechanically-parseable declaration, not surrounding prose.
- This does not touch anything else in `revised_prompt` -- in particular, it does not detect or fix a beat plan that still internally lists a different number of beats than the pinned count. That is a secondary consistency the generation model has to reconcile on its own; only the "EXACTLY N panel sections" sentence is corrected, because it is the one instruction simple enough to find-and-replace reliably without risking a bad edit to freeform prose.

The pinned-count string appended by `build_reinjection(n)`:

```python
"\n\nThe file must contain EXACTLY %d panel sections, numbered 1 through %d in order." % (n, n)
```

- `n` is `pinned_panel_count`. Python escape sequences apply: two real newline characters, then the sentence.
- No trailing newline follows the period.
- The sentence matches `bin/ltx-movie`'s own `STORY_PROMPT_TEMPLATE` wording at `bin/ltx-movie:101`.
- It is always the **last** text in the prompt. That is the highest-salience position, read most recently by the model. With the conflicting-declaration removal above, it is now also the **only** panel-count declaration in the prompt, not merely the most recent of two.

The prompt is written to a temp file:

- `fd, path = tempfile.mkstemp(prefix="iterate-story-prompt-", suffix=".txt")`
- `with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(prompt)`
- The path is passed as `--story-prompt-override <path>` (Section 4.1).
- The file is removed with `os.remove(path)` in a `finally:` after the `bin/ltx-movie` call returns, whether it succeeded or failed **[spec choice]**.
- Nothing is lost by removing it: `bin/ltx-movie` persists the same content to `story_prompt.txt`, and the next round archives that file.

### 3.3 Stopping criteria

`evaluate_stop(history, threshold, max_rounds)` runs after each round's judgment is archived and reported. `history[-1]` is the current round and `history[-2]`, if present, is the immediately previous round. Checks run in this exact order and the first match wins:

1. **Threshold.** If `all(s >= threshold for s in history[-1])`, return `"threshold met"`.
2. **Plateau.** If `len(history) >= 2` and `not any(c > p for c, p in zip(history[-1], history[-2]))`, return `"plateaued"`.
   - The comparison is strictly against the immediately previous round, never round 1 or any earlier round.
   - "Improved" means strictly increased.
   - Plateau triggers only when no dimension improved. If any dimension improved, even while others dropped, it is not a plateau.
   - Round 1 has no previous round, so plateau can trigger only from round 2 on.
3. **Max rounds.** If `len(history) >= max_rounds`, return `"max-rounds reached"`.
4. Otherwise return `None`.

Consequences:

- With `--max-rounds 1`, round 1 is judged, archived, and promoted, and no regeneration happens.
- If round 1 already meets the threshold, there are zero regenerations and the exit is 0.

### 3.4 Subprocess invocations

Both calls go through one helper with these fixed keyword arguments **[spec choice]**:

```python
subprocess.run(cmd, cwd=WS, stdin=subprocess.DEVNULL,
               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
```

- **Output is captured, not streamed.** `bin/iterate-story`'s stdout is exactly the lines in Section 5.1. On failure, the last `TAIL_LINES` lines of the captured combined output go to stderr (Section 6). See G13.
- **`stdin=subprocess.DEVNULL`.** No prompt in either child can block waiting for input. Any residual `qwen-agent` confirmation that `--danger-auto-approve` does not cover (only `promote`) gets an immediate EOF denial instead of a hang. `bin/ltx-movie --no-review` and `bin/judge-story` never read stdin. See G18.
- **No `timeout=`.** `bin/ltx-movie` Phase 1 enforces its own `_phase1_timeout(panels)`, and `bin/judge-story` relies on the SDK's timeouts.
- **The environment is inherited**, including `ANTHROPIC_API_KEY`. Its value is never read, printed, or written by `bin/iterate-story`.
- Tests monkeypatch `iterate_story.subprocess.run` (Section 7.1).

#### 3.4.1 Judge call

```python
[sys.executable, os.path.join(WS, "bin", "judge-story"), "--story-id", story_id]
```

`sys.executable` matches how `bin/ltx-movie` invokes `bin/qwen-agent`.

#### 3.4.2 Regeneration call

```python
[sys.executable, os.path.join(WS, "bin", "ltx-movie"),
 "--story-id", story_id, "--panels", str(pinned_panel_count), "--force-story", "--no-review",
 "--story-only", "--story-prompt-override", override_path]
```

`build_ltx_movie_cmd(story_id, override_path, pinned_panel_count)` returns exactly this list, in this order. `bin/iterate-story` always passes `--story-id`, `--panels <pinned_panel_count>`, `--force-story`, `--no-review`, `--story-only`, and `--story-prompt-override <override_path>` together, on every regeneration call. `narrative` is never passed: `--story-prompt-override` is always given, so Section 4.3's "exactly one" validation is satisfied without it. `--danger-auto-approve` is never passed directly by `bin/iterate-story` either; `bin/ltx-movie` adds it internally, on its own, because `--force-story` and `--no-review` are both present (Section 4.2).

This is the resolution of G1 (Section 8):

- `--panels <pinned_panel_count>` matches `story.md`'s real panel count (Section 3.1), so Phase 1's own validation (`bin/ltx-movie:717`) passes instead of defaulting to 15 and rejecting a story with a different panel count.
- `--story-only` (Section 4.3) makes the call run Phase 0 (if applicable) and Phase 1 only; `phase_release_story_server` and Phases 2-4 never run, so the story server stays resident across rounds.
- `narrative` being optional (Section 4.3) means the missing positional no longer causes an argparse exit.
- `--no-stills`, `--seed-image`, `--story-model`, and `--story-context-window` passthrough remains out of scope (Section 0.4); this version's regeneration path is plain text generation only.

### 3.5 No-op regeneration detection [G2]

Before each `bin/ltx-movie` regeneration call (Section 3.4.2), `bin/iterate-story` computes `pre_hash = story_md_hash(story_md_path)`. After the subprocess call returns -- **regardless of its exit code** -- it computes `post_hash = story_md_hash(story_md_path)`.

- **[spec choice: content hash, not mtime.]** A hash compares what actually matters -- did the bytes change -- and is immune to filesystem mtime-resolution coarseness or a write that happens to reuse the same timestamp. `story_md_hash(path)` is `hashlib.sha256(data).hexdigest()` over the file's raw bytes, read with `open(path, "rb")`.
- If `post_hash == pre_hash` (the file is byte-identical to its state immediately before the call), this is a no-op regeneration: `bin/ltx-movie` returned without actually rewriting `story.md`. It is treated exactly like any other `bin/ltx-movie` subprocess failure for round `r` (Section 6): stop the loop, report that round `r`'s regeneration did not actually change `story.md`, promote the best round found so far (`1..r`, since round `r` was already judged and archived before regenerating), write `run-summary.json`, and return 1. **This applies even when `bin/ltx-movie` itself exited 0.** This is E6b (Section 6), distinct from E6 (which is keyed on a nonzero exit code).
- If `bin/ltx-movie` exits nonzero, the existing E6 path (Section 6) applies regardless of the hash comparison. The hash check only adds a new way to fail when the exit code says success; it never suppresses the existing nonzero-exit failure path.
- The check runs whether or not Phase 1 actually ran inside `bin/ltx-movie` (for example if `story.md` already existed and `--force-story` had no effect for some other reason): an unchanged file is an unchanged file, whatever the internal cause.
- This closes the real gap behind G2 (Section 8): a failed `qwen-agent` call inside `bin/ltx-movie`'s `phase1_story()` can leave `story.md` untouched while `phase1_story()` itself returns 0 (`bin/ltx-movie:698-711`, which this spec does not modify). Checking the file's own content, rather than trusting `bin/ltx-movie`'s exit code, is entirely within `bin/iterate-story`'s own control and is sufficient to catch it.

---

## 4. `bin/ltx-movie` companion changes

These are three changes, all to `bin/ltx-movie`. No other line of the file changes.

### 4.1 `--story-prompt-override <path>`

**Parser.** In `build_parser()`, immediately after the `--force-story` line (`bin/ltx-movie:263`), add:

```python
    parser.add_argument("--story-prompt-override", dest="story_prompt_override",
                         metavar="PATH", default=None,
                         help="use the content of PATH verbatim as the Phase 1 story prompt "
                              "instead of building it from the narrative; it is still "
                              "persisted to story_prompt.txt. Only takes effect when Phase 1 "
                              "actually runs (story.md absent, or --force-story).")
```

**Precondition.** In `main()`, after the `--seed-image`/`--no-stills` conflict check (`bin/ltx-movie:1108-1112`) and before `if args.dry_run:` (`:1114`), add **[spec choice: fail early with exit 2, not a traceback inside Phase 1]**:

```python
    if args.story_prompt_override is not None and not os.path.isfile(args.story_prompt_override):
        print("Error: --story-prompt-override file not found: %s" % args.story_prompt_override,
              file=sys.stderr)
        return 2
```

**Phase 1.** In `phase1_story()`, replace the `prompt = build_story_prompt(...)` statement (`bin/ltx-movie:663-665`) with:

```python
        if args.story_prompt_override is not None:
            with open(args.story_prompt_override, encoding="utf-8") as f:
                prompt = f.read()
        else:
            prompt = build_story_prompt(args.narrative, args.story_id, args.panels, args.no_stills,
                                         bool(getattr(args, "seed_image", None)),
                                         seconds=_clip_seconds(args))
```

What stays the same:

- This is the only change to prompt construction in `phase1_story()`.
- The existing `story_prompt.txt` write (`:666-668`) still runs and writes `prompt`. The override therefore becomes the new recorded prompt for the story, exactly as if `build_story_prompt()` had produced it.
- `_phase1_max_tokens`, `_phase1_timeout`, the qwen-agent command, validation, and the review gates are unchanged.
- The override content is used verbatim: no stripping, and no `SEED_IMAGE_PREFACE`/`POSTFACE` wrapping. An empty override file is sent as-is.

### 4.2 `--force-story` with `--no-review` also passes `--danger-auto-approve`

In `phase1_story()`, after the `--image` block (`bin/ltx-movie:679-680`) and immediately before `cmd += ["--user-prompt", prompt]` (`:681`), insert:

```python
        if args.force_story and args.no_review:
            cmd += ["--danger-auto-approve"]
```

- `--no-review` already means "no interactive gates wanted for this run". Extending that meaning to `qwen-agent`'s `write_file` overwrite confirmation is a natural reading of the existing flag's intent. No new flag is added.
- **`--danger-auto-approve` must NOT be added when `--no-review` is absent.** A plain `--force-story` rerun in normal interactive use keeps today's confirmation-gate behavior exactly. It is also not added for `--no-review` alone.
- The insertion keeps `--user-prompt <prompt>` as the last two elements of `cmd`. The status line's `cmd[:-1]` redaction (`:682-684`) depends on that, and so do source-guard check L29f.
- The status line shows `--danger-auto-approve` automatically, because it is part of `cmd[:-1]`.

### 4.3 `--story-only` flag, and `narrative` becomes optional [resolves G1]

**Parser -- `--story-only`.** In `build_parser()`, immediately after the `--story-server-stop-after-story` block (`bin/ltx-movie:267-277`) and before `--dry-run` (`:278`), add:

```python
    parser.add_argument("--story-only", dest="story_only", action="store_true", default=False,
                         help="run Phase 0 (if --seed-image) and Phase 1 only, then stop. "
                              "Skips phase_release_story_server as well as Phases 2-4, so a "
                              "caller that regenerates story.md repeatedly (e.g. "
                              "bin/iterate-story) keeps the story server resident across "
                              "calls, with no need to also pass "
                              "--no-story-server-stop-after-story.")
```

**`_phase_sequence()`.** Replace the body of `_phase_sequence()` (`bin/ltx-movie:1072-1082`) with a `--story-only` branch checked first, before the existing `story_server_stop_after_story` logic:

```python
def _phase_sequence(args):
    if getattr(args, "story_only", False):
        phases = (phase1_story,)
        if getattr(args, "seed_image", None):
            phases = (phase0_seed,) + phases
        return phases
    phases = ((phase1_story, phase3_manifest, phase4_render) if args.no_stills
              else (phase1_story, phase2_stills, phase3_manifest, phase4_render))
    if getattr(args, "story_server_stop_after_story", False):
        cut = 1
        phases = phases[:cut] + (phase_release_story_server,) + phases[cut:]
    if getattr(args, "seed_image", None):
        phases = (phase0_seed,) + phases
    return phases
```

- `--story-only` is checked first and returns early, so `phase_release_story_server` is never inserted when `--story-only` is set, regardless of `--story-server-stop-after-story`'s own value (default `True`). This is the "must not run `phase_release_story_server`" requirement: it is `--story-only`'s own behavior, not something the caller must additionally remember to disable with a second flag.
- `phase3_manifest` and `phase4_render` are unreachable through the `--story-only` branch.
- The non-`--story-only` branch is textually unchanged from today; only its entry point (now reached via an `if`/early-return instead of being the whole function body) moves.
- `main()` is unaffected: it still calls each `phase_fn` returned by `_phase_sequence(args)` in order and stops on the first nonzero return (`:1146-1150`).

**Parser -- optional `narrative`.** Change the positional at `bin/ltx-movie:181` from:

```python
    parser.add_argument("narrative", help="the story narrative to adapt into panels")
```

to:

```python
    parser.add_argument("narrative", nargs="?", default=None,
                         help="the story narrative to adapt into panels; omit only when "
                              "--story-prompt-override is given")
```

**Validation.** In `main()`, immediately after `args = parser.parse_args(argv)` (`:1088`) and before `_resolve_length(args, raw_argv)` (`:1089`), add:

```python
    if args.narrative is None and args.story_prompt_override is None:
        parser.error("either a narrative argument or --story-prompt-override is required")
```

`parser.error(...)` prints usage and raises `SystemExit(2)` -- the same argparse-level mechanism `bin/iterate-story` itself uses for its own range checks (Section 2.1). **[spec choice: only the "neither given" case is an error.]** Giving both `narrative` and `--story-prompt-override` remains allowed and behaves exactly as Section 4.1 already specifies: the override fully replaces `build_story_prompt()`'s output and `narrative` is ignored for prompt-building. This reading is deliberate: the brief's "exactly one of the two must be provided" is implemented as the one concrete rule the brief actually gives (neither provided is an error); it does not ask for a new error when both are given, and adding one would change pre-existing `--story-prompt-override` behavior from Section 4.1 that this gap was not about.

**`args.narrative is None` audit.** The only two reads of `args.narrative` in the file are the two `build_story_prompt(args.narrative, ...)` calls, at `:663` (`phase1_story`) and `:979` (`_print_dry_run_plan`):

- `:663` is already inside the `else` branch of Section 4.1's `if args.story_prompt_override is not None:` check, so it is reached only when `args.story_prompt_override is None` -- which, by the validation above, means `args.narrative` is not `None` either. No change needed.
- `:979` (`_print_dry_run_plan`) is unconditional and not guarded by `--story-prompt-override`, per G11 ("`--dry-run` does not reflect D3," left as documented and unchanged by this spec). With `args.narrative is None`, `template.format(narrative=None, ...)` does not raise -- `str.format` renders `None` as the literal text `"None"` -- so `--dry-run --story-prompt-override X` with no narrative still exits 0 and prints a plan, just one whose "Rendered story prompt" section shows `None` where the narrative would go, instead of the override's content. This is the same pre-existing class of gap as G11, not a new crash, and fixing it is out of scope here: `--dry-run` never runs Phase 1 or writes any file, so nothing downstream depends on this prompt being sensible. No code change is made at `:979`.

### 4.4 Constraints

- Do not modify the `cmd = [sys.executable, os.path.join(WS, "bin", "qwen-agent"),` lines, the `cmd += ["--user-prompt", prompt]` line, or the `phase1_cmd` construction in `_print_dry_run_plan()`. These existing source-guard checks in `tests/test_ltx_movie_offline.py` assert on that exact text:
  - L19 (`:779-790`)
  - L1z9 and L1z14, which each count exactly 2 sites
  - L29f and L29g (`:1242-1245`)
- `_print_dry_run_plan()` is unchanged **[spec choice; see G11]**. `--dry-run` does not show the override prompt, `--danger-auto-approve`, or any effect of `--story-only`.
- `_phase_sequence()`'s existing source-guard test, `test_phase_sequence_ordering` in `tests/test_ltx_movie_offline.py`, builds its `args` fixtures without a `story_only` attribute; `getattr(args, "story_only", False)` then defaults to `False`, so every existing case in that test is unaffected by the 4.3 change (R1).
- `bin/ltx-movie` ships in the deploy package (`PIPELINE` in `tests/test_deploy_pkg.py:308-310`). The added code uses only constructs already present in the file, so it adds no new interpreter-version requirement.

### 4.5 Consequences (not additional requirements)

- `--story-prompt-override` has no effect when Phase 1 is skipped, that is, when `story.md` exists and `--force-story` is absent. No warning is printed **[spec choice]**.
- With `--force-story --no-review`, every `qwen-agent` tool call in Phase 1 except `promote` is auto-approved. That includes `bash` and `run_python`, which are not sandboxed. This applies to any user who runs that flag combination, not only to `bin/iterate-story`. It is the accepted risk described in Section 0.2 (see G16).
- When `--story-prompt-override` is used with `--seed-image`, the seed image is still attached through `--image`. The override replaces the whole prompt, including the seed preface and postface.
- `--story-only` and `--no-stills`/`--seed-image` are not mutually exclusive at the parser level; `--story-only` simply stops the phase sequence after Phase 1 (and Phase 0, if seeded), so any combination that is otherwise valid for Phase 0/1 alone works the same with `--story-only` added.

---

## 5. Output and reporting

### 5.1 Stdout

After each round's archive (step 4 of Section 1.2), print exactly:

```
Round N: pacing_progression=X action_plausibility=X visual_specificity=X continuity=X
```

- Format: `"Round %d: pacing_progression=%d action_plausibility=%d visual_specificity=%d continuity=%d"`.
- `N` is the run-local round number (1, 2, ...), not the version suffix.
- The dimension names are `bin/judge-story`'s, verbatim.

On a stop (exit 0), print one final line **[spec choice: exact wording]**:

```
Stopped: <reason>. Best round: <R> (v<N>), promoted to story.md, story_prompt.txt, judgment.json.
```

`<reason>` is one of `threshold met`, `plateaued`, or `max-rounds reached`.

Nothing else goes to stdout: no progress lines and no subprocess output.

### 5.2 `run-summary.json`

Written to `<story_dir>/run-summary.json`, a sibling of `story.md`:

- written at the end of every run that reaches Section 1.3 step 7, including failure exits;
- an existing file is overwritten **[spec choice]**;
- UTF-8, `json.dump(obj, f, indent=2, ensure_ascii=False)` plus a trailing `"\n"`, the same formatting as `bin/judge-story`'s `judgment.json`;
- keys in this order:

```json
{
  "stop_reason": "plateaued",
  "best_round": 2,
  "rounds": [
    {
      "round": 1,
      "version": "v3",
      "scores": {"pacing_progression": 5, "action_plausibility": 5, "visual_specificity": 5, "continuity": 4},
      "timestamp": "2026-10-03T14:03:11Z"
    }
  ]
}
```

| Field | Rule |
|---|---|
| `rounds` | Every archived round, in order (required by the brief). |
| `round` | The run-local round number. |
| `version` | The suffix string used, `"v%d" % N`. |
| `scores` | The four `SCORE_KEYS`, in order. |
| `timestamp` | UTC time captured when the round was archived, `datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. |
| `best_round` | The round number promoted to the live files, or `null` if no round was archived (round 1's judge call failed). Required by the brief. |
| `stop_reason` | **[spec choice: added]** One of `"threshold met"`, `"plateaued"`, `"max-rounds reached"`, `"judge-story failed"`, `"ltx-movie failed"`, `"ltx-movie no-op"` (Section 3.5). The exit code does not distinguish the stop reasons, so this records them on disk, including for failure runs. |

### 5.3 Files written per run (summary)

| File | When |
|---|---|
| `judgment.json`, `story_prompt.revised.txt` | By `bin/judge-story`, every round; then overwritten by promotion |
| `story.md`, `story_prompt.txt` | By `bin/ltx-movie`, every regeneration; then overwritten by promotion |
| `story.v<N>.md`, `story_prompt.v<N>.txt`, `judgment.v<N>.json` | Every archived round, new files only |
| `run-summary.json` | End of run |
| Temp override file (outside `story_dir`) | Created before and removed after each `bin/ltx-movie` call |

Anything else `bin/ltx-movie` writes (`.movie.lock`, taken and released within each `--story-only` call) is not managed by this tool. Because every regeneration call passes `--story-only` (Section 3.4.2), Phases 2-4 never run during a `bin/iterate-story` loop, so `images/`, `manifest.json`, `movie.mp4`, and `movie.log` are not produced by it either; a user who later runs `bin/ltx-movie` without `--story-only` against the same story-id produces those separately.

---

## 6. Error handling

All error messages go to stderr and begin with `Error: `.

| # | Condition | Detected at (Section 1.3 step) | Message to stderr [spec choice: wording unless noted] | Exit | Promotion |
|---|---|---|---|---|---|
| E1 | argparse error, or a range check failure (Section 2.1) | 1 | argparse usage plus the `parser.error` text | 2 | none |
| E2 | `story.md` missing | 3 | `Error: story.md not found: <story_md_path>` (identical to `bin/judge-story`) | 2 | none |
| E3 | `story_prompt.txt` missing | 4 | `Error: story_prompt.txt not found: <story_prompt_path>. iterate-story needs the original story-generation prompt to produce revised_prompt. This story may predate bin/ltx-movie's story_prompt.txt persistence (re-run its Phase 1 with --force-story).` (`bin/judge-story`'s E3 wording with the tool name changed and the `--story-md` clause dropped) | 2 | none |
| E4 | `story.md` has no `## Panel` header line | 5 | `Error: no "## Panel" headers found in story.md: <story_md_path>; cannot pin the panel count.` | 2 | none |
| E5 | `bin/judge-story` exits nonzero in round `r` (including an unset `ANTHROPIC_API_KEY`) | 7 | `Error: round <r>: judge-story exited <rc>; last output:` followed by the last `TAIL_LINES` lines of its combined output | 1 | best of rounds `1..r-1`; none if `r == 1` |
| E6 | `bin/ltx-movie` exits nonzero during round `r`'s regeneration | 7 | `Error: round <r>: ltx-movie exited <rc>; last output:` followed by the last `TAIL_LINES` lines | 1 | best of rounds `1..r` (round `r` was judged and archived before regenerating) |
| E6b | `bin/ltx-movie` exits 0 during round `r`'s regeneration, but `story.md`'s content hash is unchanged from immediately before the call (Section 3.5) | 7 | `Error: round <r>: ltx-movie exited 0 but story.md was not regenerated (unchanged content); last output:` followed by the last `TAIL_LINES` lines | 1 | best of rounds `1..r` (round `r` was judged and archived before regenerating) |

After E5, E6, or E6b, immediately after the error message, print one of these to stderr **[spec choice]**:

- `Promoted best round <R> (v<N>) to story.md, story_prompt.txt, judgment.json.`
- `No round completed; live files left unchanged.` (when no round was archived)

Then write `run-summary.json` and return 1. A failure partway through must never erase or leave inconsistent the progress already made: the promotion restores the live files to a consistent, archived, judged triple.

Consequences of the E5/E6/E6b rules (not additional requirements):

- On E6, any partial or invalid `story.md` that `qwen-agent` wrote is replaced by the promoted round's content.
- On E6b, `story.md` is by construction identical to what it was before the call, so there is nothing invalid to replace; promotion still runs, for the same reason it runs on E6: to restore `story_prompt.revised.txt` and the other live files to the promoted round's consistent, archived, judged triple.
- On E5 at round `r >= 2`, the regenerated but unjudged story from round `r-1`'s regeneration is overwritten by promotion and is not archived (G9).
- E6b can never occur at round 1's own judge call (it is specific to the regeneration step, which always follows an archived, judged round), so `r >= 1` always has at least one archived round and promotion is never the "no round completed" case for E6b.

Python exceptions outside this table propagate as tracebacks **[spec choice; same rule as `bin/judge-story` Section 6]**. Examples: `OSError` on a copy, or a `judgment.json` that will not parse. The live files may then be in a mid-round state. The archives are intact.

---

## 7. Testing

### 7.1 Framework and style

- Files: `tests/test_iterate_story.py` (D2) and `tests/test_ltx_movie_iterate_flags.py` (D4).
- Use pytest with plain `assert`. Do not use the `check()` helper from `tests/test_ltx_movie_offline.py`; it reports false greens under pytest.
- Load each script as a module, exactly as `tests/test_judge_story.py:26-28` does:
  ```python
  WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
  iterate_story = importlib.machinery.SourceFileLoader(
      "iterate_story", os.path.join(WS, "bin", "iterate-story")).load_module()
  ltx_movie = importlib.machinery.SourceFileLoader(
      "ltx_movie_iterate_flags", os.path.join(WS, "bin", "ltx-movie")).load_module()
  ```
- **No real subprocess, API, or generation calls, anywhere.** This follows the spirit of `tests/test_judge_story.py`'s `_no_real_client` autouse fixture, adapted to the subprocess boundary:
  - D2 has an autouse fixture `_no_real_subprocess(monkeypatch)`. It sets `iterate_story.subprocess.run` to a function that raises `AssertionError("test made a real subprocess call")`. Tests that reach a subprocess install a recording fake over it.
  - D4 has the same kind of autouse fixture over `ltx_movie.subprocess.Popen` and `ltx_movie.subprocess.run`.
- **Story directories live under `tmp_path`.** `monkeypatch.setattr(iterate_story, "WS", str(tmp_path))`, then create `tmp_path/generated/stories/<id>/`. Nothing is written to the real `generated/` tree.
- **The recording fake for `iterate_story.subprocess.run(cmd, **kwargs)`.** It records `(cmd, kwargs)` and dispatches on `os.path.basename(cmd[1])`:
  - **`judge-story`.** It pops the next scripted entry. An `int` entry means "fail with this rc": return `subprocess.CompletedProcess(cmd, rc, stdout="judge boom\n")`. A 4-tuple entry means success:
    - write `<story_dir>/judgment.json` containing `{"scores": {<SCORE_KEYS mapped to the tuple>}, "critique": "c<k>", "revised_prompt": "REVISED-<k>"}`, where `k` is the call count;
    - write `<story_dir>/story_prompt.revised.txt` = `"REVISED-<k>"`;
    - return a `CompletedProcess` with rc 0.
  - **`ltx-movie`.**
    - Read the file at the element after `"--story-prompt-override"` and record its content and path.
    - Write `<story_dir>/story.md` = `"## Panel 1 — regen <k>\nMotion: m\nNarration: n\n"`.
    - Write `<story_dir>/story_prompt.txt` = the override content.
    - Return rc 0, or the scripted failure rc. In the failure case, still write a garbage `story.md` = `"GARBAGE"` first, to prove that promotion restores the live file.
    - A scripted entry of `"noop"` means: do not write `story.md` or `story_prompt.txt` at all -- leave both exactly as they were before the call -- and return rc 0. This exercises Section 3.5's no-op detection (T-M9).
- Fixture `story.md` texts are synthesized in the test. They do not depend on `generated/stories/ronin-generalship/`, which is not guaranteed present.

### 7.2 Real (unmocked, pure-function) tests -- D2

| ID | Test | Assertion |
|---|---|---|
| T-P1 | `count_panels` on a 20-header synthesized story, and on a text with 3 `## Panel` lines plus one `### Panel 9`, one ` ## Panel 8` (leading space), and body text containing `Panel 4` | `== 20`; `== 3` |
| T-P2 | `build_reinjection(20)`; `build_next_prompt("ABC\n", 20)` -- fallback-append path, the pattern is absent | `== "\n\nThe file must contain EXACTLY 20 panel sections, numbered 1 through 20 in order."`; `== "ABC\n" + build_reinjection(20)` (verbatim prefix, appended last) |
| T-P2b | `build_next_prompt("Here is the revised prompt.\n\nThe file must contain EXACTLY 30 panel sections, numbered 1 through 30 in order.\n\nFocus more on pacing in the middle act.", 20)` -- find-and-replace path, the pattern is present with a conflicting count (paraphrase of a real `revised_prompt` observed this session) | Result does not contain the substring `"EXACTLY 30"`. Result contains the substring `"EXACTLY 20"` exactly once (`result.count("EXACTLY 20") == 1`). Result `== "Here is the revised prompt.\n\n\n\nFocus more on pacing in the middle act." + build_reinjection(20)` (the matched sentence is deleted in place, leaving the surrounding blank lines untouched per Section 3.2; the pinned sentence is still appended last) |
| T-P3 | `find_version_base` on: (a) a `tmp_path` dir with `story.v1.md`, `story.v2.md`, `story_prompt.v1.txt`, `story_prompt.v2.txt`, `judgment.v1.json`, `judgment.v2.json` (the `ronin-generalship` shape); (b) an empty dir; (c) a dir with only `judgment.v7.json`; (d) a dir with only `story.v2.md.bak`, `story.vX.md`, `story.v.md` | (a) `== 2`, so the next archive is `.v3`; (b) `== 0`; (c) `== 7`; (d) `== 0` |
| T-P4 | `evaluate_stop` cases, listed below the table | each returns exactly the listed value |
| T-P5 | `select_best_round` cases, listed below the table | each returns exactly the listed value |

T-P4 cases, in the form `history, threshold, max_rounds -> expected`:

1. `[(7,7,7,7)], 7, 5 -> "threshold met"` (threshold uses `>=`)
2. `[(7,7,7,6)], 7, 5 -> None` (round 1 never plateaus)
3. `[(5,5,5,4),(5,5,5,4)], 9, 5 -> "plateaued"`
4. `[(5,5,5,4),(6,4,4,3)], 9, 5 -> None` (one dimension improved)
5. `[(4,4,4,4),(6,6,6,6),(6,6,6,6)], 9, 5 -> "plateaued"` (compares only to the immediately previous round, not round 1)
6. `[(8,8,8,8),(8,8,8,8)], 7, 2 -> "threshold met"` (threshold beats plateau and max)
7. `[(5,5,5,4),(5,5,5,4)], 9, 2 -> "plateaued"` (plateau beats max)
8. `[(4,4,4,4),(5,4,4,4)], 9, 2 -> "max-rounds reached"`
9. `[(4,4,4,4)], 9, 1 -> "max-rounds reached"`

T-P5 cases:

1. `[(1,(5,4,4,3)),(2,(5,5,5,4)),(3,(9,9,9,3))] -> 2` (minimum first, despite round 3's higher average)
2. `[(1,(4,4,4,4)),(2,(9,4,4,4))] -> 2` (average breaks the tie on minimum)
3. `[(1,(5,5,5,4)),(2,(5,5,5,4))] -> 1` (a full tie goes to the earliest)

### 7.3 Mocked loop tests -- D2

| ID | Scenario | Assertions |
|---|---|---|
| T-M1 | Empty version history. Judge script `[(4,4,5,2),(7,7,7,7)]`, ltx-movie succeeds. `main(["--story-id", id, "--threshold", "7"])` | Returns 0. Judge called 2x, ltx-movie 1x. `story.v1.md` and `story.v2.md` (and the matching prompt and judgment files) exist. Stdout is exactly the two Round lines plus `Stopped: threshold met. Best round: 2 (v2), promoted to story.md, story_prompt.txt, judgment.json.` Live `story.md`, `story_prompt.txt`, and `judgment.json` are byte-equal to the `v2` archives. `run-summary.json` has keys in Section 5.2 order, `stop_reason == "threshold met"`, `best_round == 2`, 2 rounds with versions `v1`, `v2`, and timestamps matching `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`. |
| T-M2 | Same setup as T-M1. Inspect the recorded ltx-movie call | `cmd == [sys.executable, os.path.join(iterate_story.WS, "bin", "ltx-movie"), "--story-id", id, "--panels", str(pinned), "--force-story", "--no-review", "--story-only", "--story-prompt-override", <recorded path>]`, where `pinned` is the fixture's panel count. The recorded override content equals `"REVISED-1" + build_reinjection(pinned)`. The temp file no longer exists after `main` returns. Both calls used `stdin=subprocess.DEVNULL` and `cwd=iterate_story.WS`. The judge cmd equals `[sys.executable, os.path.join(iterate_story.WS, "bin", "judge-story"), "--story-id", id]`. |
| T-M3 | `ronin-generalship` shape: the dir has `.v1`/`.v2` of all three kinds with known contents. Judge script `[(5,4,4,3),(5,5,5,4),(5,5,5,4)]`, `--threshold 9` | Returns 0. Stop is `plateaued` after round 3. Archives are `v3`, `v4`, `v5`. `story.v3.md` is byte-equal to the fixture's pre-loop `story.md`, and `story.v4.md` is byte-equal to the story the first ltx-movie fake call wrote (`regen 1`). This pins the archive-after-judging timing. The original `.v1`/`.v2` files are byte-unchanged. Best round is 2 (`v4`, the earliest on a full tie). Live `story.md` equals `story.v4.md`, not the last round. Live `story_prompt.revised.txt` equals `judgment.v4.json`'s `revised_prompt`. |
| T-M4 | Judge script `[(3,3,3,3),(4,4,4,4)]`, `--threshold 9 --max-rounds 2` | Returns 0. Judge 2x, ltx-movie 1x. `stop_reason == "max-rounds reached"`. Best round is 2. |
| T-M5 | Judge script `[(6,6,6,6),(7,3,3,3),1]` (round 3's judge fails), `--threshold 9`. Round 2 improves `pacing_progression`, so it is not a plateau, but its minimum (3) is below round 1's (6) | Returns 1. Stderr contains `round 3` and `judge-story exited 1` and `judge boom`. Live `story.md` equals `story.v1.md` (round 1, the best so far). `run-summary.json` has `stop_reason == "judge-story failed"`, `best_round == 1`, and 2 rounds. Stdout has no `Stopped:` line. |
| T-M6 | Judge script `[(5,5,5,5)]`, `--threshold 9`. ltx-movie fails with rc 1 after writing `GARBAGE` | Returns 1. Stderr contains `round 1` and `ltx-movie exited 1`. Live `story.md` equals `story.v1.md`, not `GARBAGE`. `stop_reason == "ltx-movie failed"`. |
| T-M6b | Judge script `[1]` (round 1's judge fails), `--threshold 9` | Returns 1. Stderr contains `No round completed; live files left unchanged.` Live `story.md` is byte-unchanged from the fixture. `run-summary.json` has `best_round` null and `rounds == []`. |
| T-M9 | Judge script `[(5,4,4,3)]`, ltx-movie scripted `"noop"` (round 1's regeneration returns rc 0 without touching `story.md`), `--threshold 9` | Returns 1. Stderr contains `round 1` and `ltx-movie exited 0 but story.md was not regenerated`. Live `story.md` equals `story.v1.md` (round 1, the only round archived). `run-summary.json` has `stop_reason == "ltx-movie no-op"`, `best_round == 1`, and 1 round. Judge called 1x, ltx-movie 1x. |
| T-M7 | Preconditions: (a) no `story.md`; (b) `story.md` present but no `story_prompt.txt`; (c) `story.md` with no `## Panel` line | Each returns 2. Stderr contains, respectively, `story.md not found`, `story_prompt.txt not found`, `no "## Panel" headers`. The subprocess fake was never called (the autouse guard would raise). No `run-summary.json` is written. |
| T-M8 | Argument errors: `--threshold 0`; `--threshold 11`; `--max-rounds 0`; `--threshold` missing; `--story-id` missing | Each raises `SystemExit` with `code == 2` |

### 7.4 Tests for D3 -- `tests/test_ltx_movie_iterate_flags.py` (D4)

Setup for each test (T-L1 through T-L7, T-L11):

- `monkeypatch.setattr(ltx_movie, "WS", str(tmp_path))` and create `tmp_path/generated/stories/<id>/` (`_story_dir` reads `WS` at call time).
- Replace `ltx_movie.subprocess.Popen` with a recorder. It stores `cmd` and returns an object whose `communicate(timeout=...)` returns `("", None)` and whose `returncode` is `1`. With no `story.md` on disk, `phase1_story` then returns 1 after building and recording the command. Its return value is not asserted.
- Build `args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", id, "--panels", "1", *flags])` and call `ltx_movie.phase1_story(args)`.

T-L8 through T-L10 test `_phase_sequence()` and `main()`'s argument validation directly; they do not need the `Popen` recorder, since neither reaches a subprocess call.

| ID | Flags | Assertion on the recorded `cmd` (and files) |
|---|---|---|
| T-L1 | `--force-story --no-review` | `"--danger-auto-approve" in cmd`; `cmd[-2] == "--user-prompt"` |
| T-L2 | `--force-story` | `"--danger-auto-approve" not in cmd` |
| T-L3 | `--no-review` | `"--danger-auto-approve" not in cmd` |
| T-L4 | (none) | `"--danger-auto-approve" not in cmd` |
| T-L5 | `--story-prompt-override <tmp file>`, where the file contains `"Override — prompt\nline 2\n"` (non-ASCII and a trailing newline, to prove verbatim); positional `narrative` also given, per the setup above | `cmd[-1]` equals the file content exactly; `story_prompt.txt` in the story dir equals the file content exactly |
| T-L6 | (none) | `cmd[-1] == ltx_movie.build_story_prompt("a narrative", id, 1, False, False, seconds=ltx_movie._clip_seconds(args))`; `story_prompt.txt` equals that string |
| T-L7 | `ltx_movie.main(["a narrative", "--story-id", id, "--story-prompt-override", str(tmp_path / "missing.txt")])` | Returns 2; stderr contains `--story-prompt-override file not found`; `ltx_movie.subprocess.Popen` was never called |
| T-L8 | `args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", id, "--story-only"])`; call `ltx_movie._phase_sequence(args)` directly (no `Popen`, no narrative-optional precondition involved) | `tuple(f.__name__ for f in ltx_movie._phase_sequence(args)) == ("phase1_story",)` -- proves `phase_release_story_server` and Phases 2-4 are skipped even though `--story-server-stop-after-story` defaults to `True` |
| T-L9 | `args = ltx_movie.build_parser().parse_args(["a narrative", "--story-id", id, "--story-only", "--seed-image", "x.png"])`; call `ltx_movie._phase_sequence(args)` directly | `tuple(f.__name__ for f in ltx_movie._phase_sequence(args)) == ("phase0_seed", "phase1_story")` |
| T-L10 | `ltx_movie.main(["--story-id", id])` (no positional `narrative`, no `--story-prompt-override`) | Returns 2; stderr contains `either a narrative argument or --story-prompt-override is required`; `ltx_movie.subprocess.Popen` was never called |
| T-L11 | No positional `narrative`: `args = ltx_movie.build_parser().parse_args(["--story-id", id, "--panels", "1", "--story-prompt-override", <tmp file containing "Override only\n">])`; call `ltx_movie.phase1_story(args)` with the same `Popen` recorder as T-L1-T-L7 | Does not raise; `cmd[-1]` equals the override file's content exactly; `story_prompt.txt` equals that content. Proves `args.narrative is None` does not crash Phase 1 when `--story-prompt-override` is given (Section 4.3's audit) |

### 7.5 Mutation checks (negative controls)

Before declaring D2 and D4 complete, the implementer applies each mutation below, one at a time, runs the suites, confirms that at least one named test fails, and reverts the mutation.

| Mutation | Must fail |
|---|---|
| Threshold `>=` changed to `>` | T-P4 case 1 |
| Plateau compares to `history[0]` instead of `history[-2]` | T-P4 case 5 |
| Plateau checked before threshold | T-P4 case 6 |
| Best round chosen by average first, then minimum | T-P5 case 1 |
| Full tie picks the latest instead of the earliest | T-P5 case 3, T-M3 |
| `find_version_base` returns 0 without scanning | T-P3, T-M3 |
| Re-injection prepended instead of appended | T-P2, T-M2 |
| `PANEL_COUNT_DECLARATION_RE.sub` call removed (old append-only behavior restored, conflicting declaration left in place) | T-P2b |
| Archive taken after regeneration instead of after judging | T-M3 |
| Promotion skipped on the failure path | T-M5, T-M6 |
| `--danger-auto-approve` condition reduced to `args.force_story` | T-L2 |
| Override read but `build_story_prompt` result still used | T-L5 |
| Override missing-file check removed from `main()` | T-L7 |
| `--story-only` branch checked after (instead of before) the `story_server_stop_after_story` insertion, so `phase_release_story_server` is still inserted | T-L8 |
| `--story-only` omits the `phase0_seed` prefix | T-L9 |
| The neither-narrative-nor-override validation removed from `main()` | T-L10 |
| `build_ltx_movie_cmd` omits `--panels` or `--story-only` | T-M2 |
| No-op detection removed (the hash comparison is skipped and a zero exit is always treated as success) | T-M9 |

### 7.6 Acceptance

| ID | Check | Pass condition |
|---|---|---|
| A1 | `python3 -m pytest tests/test_iterate_story.py tests/test_ltx_movie_iterate_flags.py -v`, run from `WS` by the main thread (counts reported by the implementer are not accepted) | Every test in Sections 7.2-7.4 passes, and the count matches the tests defined there |
| A2 | Mutation checks, Section 7.5 | Each mutation makes at least one named test fail |
| R1 | `python3 tests/test_ltx_movie_offline.py`, run directly (its `check()` style gives false greens under pytest) | Same pass/fail result as before D3 |
| R2 | `python3 -m pytest tests/test_judge_story.py` | Unchanged result (D1 does not modify `bin/judge-story`) |
| M1 | Manual, once implemented: a real `bin/iterate-story --story-id ronin-generalship --threshold <N>` run | Exit 0. The first new archive is one above the highest pre-existing `.vN` (`.v3` if nothing was added; see G10). Every pre-existing `.vN` file's sha256 is unchanged. Every archived `story.v<N>.md` has exactly the pinned number of `## Panel` lines (20). `run-summary.json` is present. Live files equal the `best_round` archive. The story server stays up across rounds (confirms `--story-only`, Section 4.3). |

---

## 8. Known gaps / open questions

G1 and G2 are RESOLVED. G19 is RESOLVED, partially (a residual uncertainty remains open; see its entry below). Every other item has a spec choice recorded above, which the user may override.

- **G1 -- RESOLVED.** Resolution: Section 4.3 (`--story-only` and optional `narrative`) plus Section 3.4.2's final argv (`--panels <pinned_panel_count>`, `--story-only`). The analysis below is left in place for traceability; it describes the problem this resolved, not current behavior.
  - **Originally: the approved regeneration command could not run against the then-current `bin/ltx-movie`.** Confirmed against the source on 2026-10-03:
  - **(a) Required positional.** `narrative` is a required positional argument (`bin/ltx-movie:181`). The approved argv omits it, so every regeneration exits 2 in argparse. With `--story-prompt-override`, Phase 1 never uses `narrative`; its only consumers are the two `build_story_prompt` calls at `:663` and `:979`. It still must be supplied.
  - **(b) Full pipeline.** `bin/ltx-movie` has no stop-after-Phase-1 mode; `_phase_sequence` (`:1072-1082`) always continues past Phase 1. Each regeneration would therefore run:
    - Phase 1b `bin/story-server stop` plus a wait for 25 GiB available. This is on by default (`:267-277`). It stops the story model, so the next round's Phase 1 has no server to talk to.
    - Phase 2 stills (z_image GPU work).
    - Phase 3 manifest.
    - A full Phase 4 GPU render of the whole movie.

    The manual rounds in Section 0.2 avoided this by calling `bin/qwen-agent` directly.
  - **(c) Panel count.** `--panels` defaults to 15. `phase1_story` validates the new `story.md` against exactly `args.panels` (`:717`), so a 20-panel story fails validation (exit 1). `_phase1_max_tokens` and `_phase1_timeout` also scale to 15 instead of the pinned count.
  - **(d) Story mode.** A `--no-stills` story (`Prompt:` format) would be validated in stills mode and fail. A `--seed-image` story would lose its image attachment. A host that needs `--story-model` or `--story-context-window` would not get them. `bin/iterate-story` has no CLI to carry any of these.
  - **Recommended resolution, for the user to decide:**
    - Add a third companion flag to `bin/ltx-movie`, for example `--story-only`. It runs Phase 0 (if seeded) and Phase 1 only, skipping Phase 1b and Phases 2-4.
    - Have `bin/iterate-story` pass `--panels <pinned_panel_count>`.
    - Either pass a fixed placeholder narrative, or make `narrative` optional (`nargs="?"`) only when `--story-prompt-override` is given.
    - Defer `--no-stills`, `--seed-image`, `--story-model`, and `--story-context-window` passthrough. One option is to have `bin/iterate-story` reject `Prompt:`-format stories up front.
    - Alternative: call `bin/qwen-agent` directly, as the manual rounds did. Then `bin/iterate-story` would have to replicate the `story_prompt.txt` persistence and validation that `bin/ltx-movie` provides, and Section 4.1 would become unnecessary.
- **G2 -- RESOLVED.** Resolution: Section 3.5 (no-op regeneration detection) plus E6b (Section 6). `bin/ltx-movie` itself is not touched; `bin/iterate-story` detects the symptom on its own side. The analysis below is left in place for traceability; it describes the problem this resolved, not current behavior.
  - **Originally: stale `story.md` reported as success.** When `qwen-agent` exits nonzero but a `story.md` exists, `phase1_story` validates that file and returns 0 (`bin/ltx-movie:698-711`). Under `--force-story`, that file can be the previous round's story, never overwritten (for example on a `context_budget` failure). `bin/iterate-story` would then re-judge an unchanged story as if it were new. Recommendation, not specified: `bin/iterate-story` compares `story.md` bytes before and after the `bin/ltx-movie` call, and treats unchanged bytes as an E6 failure.
- **G3: "round 0" naming.** The brief calls the original pre-loop state "round 0". This spec numbers it round 1 (Section 1.2), so that "plateau only from round 2", "before archiving round 1", and "each round starts by judging the current `story.md`" all hold literally. Behavior is the same either way: the original is always judged and is always a best-round candidate.
- **G4: `--max-rounds` counts judged rounds.** The default of 5 means at most 5 judge calls and 4 regenerations. Alternative: count regenerations, which means up to 6 judge calls. That would require one extra judge call after the last regeneration, so that no unjudged story is left on disk.
- **G5: archive timing.** The brief lists archiving after regeneration (its step 5). This spec archives right after judging (Section 1.2, step 3), because archiving after regeneration pairs a judgment with the wrong story. The set of archived files is unchanged.
- **G6: `story_prompt.revised.txt` on promotion.** `bin/judge-story` rewrites this file every round, and the brief's promotion list names only the three archived files. This spec also rewrites it from the promoted judgment's `revised_prompt`, so that it matches `judgment.json`. Alternative: leave it holding the last judged round's revised prompt.
- **G7: version scan breadth.** The brief scans `story\.v(\d+)\.md`. This spec takes the maximum across `story.vN.md`, `story_prompt.vN.txt`, and `judgment.vN.json` (Section 1.4), so an incomplete family can never be overwritten.
- **G8: full tie in best-round selection.** The brief defines minimum, then average. This spec breaks a remaining tie toward the earliest round, which is closest to the user's original prompt and had less exposure to the observed prompt drift.
- **G9: unjudged story lost on a mid-loop judge failure.** On E5 at round `r >= 2`, the story regenerated at the end of round `r-1` was never judged. Promotion overwrites it, and it is not archived. This follows the brief's "promote the best round found so far". If the user wants it kept, archive it under the next suffix without a judgment, which would be a fourth file shape.
- **G10: live `judgment.json` exists for `ronin-generalship`.** The brief says it was deleted. On 2026-10-03 it is present (scores 5,5,5,4, `2026-10-03T05:18:49Z`), with a `story_prompt.revised.txt` asking for 30 panels. Neither is archived. Round 1's `bin/judge-story` call will overwrite both with a fresh judgment of the same `story.md`. If the user wants to keep that judgment, they should copy it to an unused suffix first, for example `judgment.v3.json`. G7's scan then starts the run's archives at `.v4`.
- **G11: `--dry-run` does not reflect D3.** `_print_dry_run_plan()` is unchanged, so `bin/ltx-movie --dry-run --story-prompt-override X` prints the `build_story_prompt` prompt, and its preview command lacks `--danger-auto-approve`. Mirroring D3 there would touch the `phase1_cmd` lines that tests L1z9, L1z14, L19, and L29g pin.
- **G12: D3 tests go in a new file.** D3 is tested in `tests/test_ltx_movie_iterate_flags.py` with pytest asserts, not in `tests/test_ltx_movie_offline.py`. That keeps the deploy package's gate G1 suite (`tests/test_deploy_pkg.py:339`, which records an `OK n/n` line) unchanged and avoids the `check()` false-green style. Alternative: add the tests to `tests/test_ltx_movie_offline.py` and re-baseline the deploy gate.
- **G13: subprocess output is captured, not streamed.** No output is shown while a `bin/ltx-movie` Phase 1 runs, which can take up to `max(900, panels*90)` seconds (1800 s for 20 panels). On failure, only the last 40 lines are shown. Alternatives: stream child output to stderr, or save full per-round logs.
- **G14: Ctrl-C is not handled.** A `KeyboardInterrupt` propagates. No promotion happens and no `run-summary.json` is written. The archives taken so far are intact.
- **G15: zero-panel precondition (E4).** Added so that a pin of 0 cannot occur. It was not in the brief.
- **G16: scope of the Section 4.2 bypass.** It applies to every `bin/ltx-movie --force-story --no-review` invocation, not only those from `bin/iterate-story`, and it covers every `qwen-agent` tool except `promote`. This is per the approved design and recorded here for visibility.
- **G17: no cost guard.** Each round makes one Opus judging call, or two on `bin/judge-story`'s internal retry. The only cap is `--max-rounds`.
- **G18: `stdin=subprocess.DEVNULL` for both children.** This prevents hangs (Section 3.4). It means any prompt in a child that was not anticipated is answered with EOF (denied) rather than surfaced to the user.
- **G19 -- RESOLVED (partially).** Resolution: Section 3.2's conflicting-declaration removal. `build_next_prompt` now finds and deletes any `"The file must contain EXACTLY N panel sections..."` sentence already present in the judge's `revised_prompt` (via `PANEL_COUNT_DECLARATION_RE`) before appending the pinned-count version, so the final prompt states the panel count exactly once, not twice with contradicting numbers. This removes the stated-instruction contradiction this gap originally described. It does not fully close the gap: a `revised_prompt` can still contain a beat-by-beat plan that lists, say, 30 distinct beats while the pinned count is 20, and nothing in Section 3.2 detects or reconciles that -- only the single mechanically-parseable "EXACTLY N panel sections" sentence is corrected. Whether `qwen38-6bit` nonetheless drifts toward a beat plan's implied count, even with the contradictory declaration removed, is unverified until a real run (M1). If G1's resolution passes `--panels <pinned>`, `bin/ltx-movie`'s validation will still reject any drifted output as an E6 failure.


---

## Amendments (post-implementation)

This spec describes the design as originally approved. The following real changes were
made after implementation, during real-hardware use, and are NOT reflected in the sections
above (including Section 3.4.1's judge argv and Section 3.4.2's `build_ltx_movie_cmd`
signature) -- treat the commits below as the current source of truth where they conflict
with this document's original text:

- **The judge argv now includes `--target-panels`.** Section 3.4.1's command list is
  missing `--target-panels <pinned_count>`, added so the judge builds its own beat plan for
  the correct count from the start (see the judge-story spec's own amendments). Every
  judge call `bin/iterate-story` makes, round 1 included, passes this flag. Commit `ce886cd`.
- **`build_ltx_movie_cmd` gained two more optional parameters.** Section 3.4.2's signature
  (`story_id, override_path, pinned_panel_count`) is missing `story_model=None,
  story_context_window=None`, added after a real run hit `qwen-agent`'s own
  `context_budget`/`context_length` exhaustion because nothing told `bin/ltx-movie` which
  model was actually serving or its real context window. Both are appended to the argv
  only when given, so a caller that omits them reproduces the prior exact command.
  `bin/iterate-story`'s own CLI gained matching `--story-model`/`--story-context-window`
  passthrough flags. Commit `845a0f2`.
- **G1 and G2 resolutions (already in Section 8) were real-hardware-validated**, not just
  designed: two full live runs of `bin/iterate-story` against a real Claude API and a real
  local vLLM vision server completed, one hitting both E6 and E6b for real (a genuine
  `qwen-agent` `context_length` failure correctly caught as a no-op regeneration) and the
  second completing cleanly across 4 real rounds to a threshold-met stop.
