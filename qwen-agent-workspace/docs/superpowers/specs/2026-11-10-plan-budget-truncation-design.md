# Plan token budget: a catalog plan gets a larger budget, and a plan reply cut off at its budget is named and retried with more tokens

Date: 2026-11-10

Status: design spec and implementation plan in one document.

**The user's report (confirmed):** a shots-mode run with auto-lora and 15 panels fails Phase 1 with `Error: the story model did not return a usable plan after 2 call(s)` and the bullet `the reply is not one JSON object`. Both plan calls report status `ok` after about 45 s each.

**The cause:** the plan reply is cut off at the plan token budget. Dialogue-heavy beats plus the `loras` object of an auto-lora plan make it longer than `plan_max_tokens` allows. bin/qwen-agent returns the partial text with status `ok`, the engine finds no JSON object, retries with the same budget, and then prints a message that hides the cause.

**This spec:**
- gives a catalog plan a larger first budget;
- recognises a cut-off reply, names it in the output and records it in `run.json`;
- retries a cut-off reply once with 1.5 times the budget.

A reply that is not cut off takes exactly the same path as today, byte for byte. Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Repository `/Users/reubenpatterson/local_agent_harness` is never touched by this plan.
- Worktree `$S/pb-wt`, branch `plan-budget`, off `599b1c7` (the merge of PR #16, seed-context). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`.
- Every path is relative to `WS`, and every line number cites `599b1c7`.
- At `599b1c7`, every `PIPELINE_FILES` member is byte-identical to `755d4c45ad6c33ebf68716ad04d357f1391f79f1`, the current `test_mut26` BASELINE (`tests/test_movie_ui_builder.py:293`). The tree of `599b1c7` equals the tree of `6e93fda`. Both facts were checked with `git diff --quiet`.

**IDs.** Requirements are **PB1-PB8**, tests **PBT1-PBT9**, KPIs **PBK1-PBK6**, live checks **L1-L4**. At `599b1c7`, `git grep -nE "\bPB[0-9]+\b|\bPBT[0-9]+\b|\bPBK[0-9]+\b"` finds nothing.

**Terms.**
- The **budget** of a plan call is the `--max-tokens` value it passes to bin/qwen-agent.
- A **catalog plan** is one whose plan prompt includes `LORA_PICK_PARAGRAPH`. That happens when auto LoRA is on and at least one catalog entry is compatible (`build_plan_prompt`, `story_engine.py:1128`).
- A **cut-off reply** is a plan reply with envelope status `ok` that contains a `{` whose object never closes (PB3).

---

## 0. Scope

### 0.1 What happens today (verified at `599b1c7`)

- **The budget.** `plan_max_tokens(n)` is `max(4096, n * 250)` (`story_engine.py:177-178`). `plan_round` calls it with `most_panels(ctx)`, which is the target plus `PANELS_EXTRA` = 2 (`:126-137`, `:4905`). So 15 panels get `17 * 250 = 4250` tokens on both plan calls, whether or not there is a catalog.
- **bin/qwen-agent.** For a reply with no tool calls, `run_turn` returns status `ok` with whatever text the model produced. When `finish_reason == "length"`, it only writes `[note: answer was cut off at max_tokens=N]` to stderr (`bin/qwen-agent:4113-4117`). The one-shot envelope has the keys `schema`, `status`, `answer`, `error`, `rounds` and `tool_calls`. It has no finish reason (`:4346-4353`).
- **`run_agent`** (`story_engine.py:252-281`) returns `(status, answer)`. It reads stderr only when there is no answer, so the note is lost.
- **`extract_json`** (`:284-305`) takes the span from the first `{` to the last `}`. On a cut-off reply `json.loads` fails, and it returns `None`.
- **`plan_round`** (`:4892-4930`) then records the problem `the reply is not one JSON object`. The retry prompt repeats the whole prompt, that problem and up to 20000 characters of the partial reply, with the SAME budget (`:4905`, `:4926-4930`). The second reply is cut off the same way.
- **`go`** (`:5125-5133`) prints `the reply is not one JSON object` whenever no plan call produced a parsable plan. It ends with `Rerun the same command to try again.`, which cannot help here.
- **The dry run.** bin/ltx-movie prints the plan command with `engine.plan_max_tokens(engine.most_panels(ctx))` (`bin/ltx-movie:3706-3709`).
- **Triggers** are not injected in Phase 1; only Phases 2 and 3 add them. Trigger handling is not part of this problem and is not changed.

### 0.2 Grounding: the pins this change must respect (verified at `599b1c7`)

- **`test_rs4_constants`** (`tests/test_story_engine.py:97`) pins `(se.plan_max_tokens(14), se.plan_max_tokens(30)) == (4096, 7500)`. The no-catalog formula does not change (PB1), so this line passes as it is and is not edited (Decision 8).
- **`test_rst47_robust_dry_run`** (`tests/test_story_engine.py:2594-2650`) runs dry runs with `--panels 4` and ONE compatible catalog entry, and asserts `--max-tokens 4096` (`:2636`). Under PB1 that is `max(4096, 6 * 400) = 4096`, so it does not change.
- **SPT17** (`tests/test_soft_panel_count.py:1104-1110`) asserts `--max-tokens 5500` for `--panels 20` with the suite's empty catalog (`tests/conftest.py`, `lora_catalog_isolation`). That is `22 * 250`, unchanged.
- **`story_engine_testutil.make_ctx`** defaults to `auto_lora=True` with an EMPTY catalog. Every existing engine test is therefore a no-catalog run and keeps today's budget.
- **RST1** (`tests/test_story_engine.py:52-67`) pins story_engine's top-level imports. This change adds none.
- **`bin/ltx-movie` literal pins.**
  - No top-level `import re` (`tests/test_ltx_movie_offline.py:433`, L7j).
  - The RST50 literal counts (`tests/test_story_engine.py:2420-2441`).
  - The one changed `bin/ltx-movie` line contains none of the counted literals and adds no import.
- **`tests/test_movie_ui_builder.py`.** `PIPELINE_FILES` (`:223-228`) includes `bin/ltx-movie`, `bin/qwen-agent` and `story_engine.py`. `test_mut26` (`:272-302`; the comment chain ends at `:291`, BASELINE is at `:293`) fails from the code commit until Task 2 moves BASELINE, exactly as `6e93fda` did.
- **Merge commit only.** BASELINE will name Task 1's commit. A squash or rebase merge would orphan that commit, and `test_mut26` would then skip ("baseline commit ... is not in this checkout") instead of guarding.

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `story_engine.py` | **yes** | 1 | constants, `plan_max_tokens(n, catalog=False)`, `plan_tokens`, `escalated_plan_tokens`, `cut_off_json`, `plan_round`'s budget and cut-off branch, `go`'s fatal list (PB1-PB7) |
| D2 | `bin/ltx-movie` | **yes** | 1 | one line: the dry run's plan budget comes from `engine.plan_tokens(ctx, compatible)` (PB2) |
| D3 | `tests/test_plan_budget.py` | no | 1 | new, PBT1-PBT9 (10 test IDs) |
| D4 | `tests/test_movie_ui_builder.py` | no | 2 | only `test_mut26`'s BASELINE and comment chain |

Untouched: `bin/qwen-agent` (Decision 2), `lora_catalog.py`, `character_lib.py`, every other bin, every existing test except D4, and the movie-ui.

### 0.4 Out of scope

- bin/qwen-agent's envelope and the shape of `run_agent`'s return value (follow-up F1).
- Panel calls (`PANEL_MAX_TOKENS` 1536) and critic calls (`CRITIC_MAX_TOKENS` 4096). They can also be cut off (follow-up F2).
- Trigger handling. It is not involved, because Phase 1 injects no triggers.
- The first plan call's prompt, the timeouts (`plan_timeout`, `REQUEST_TIMEOUT`), `PLAN_MAX_CALLS` and the wall-clock cap.
- A budget that adapts to the served context window (follow-up F5).
- Any model call, server, render or download in tests, and any agent access to macstudio.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| PBK1 | The full suite has no failure beyond the baseline recorded at `599b1c7` (`2 failed, 2718 passed, 2 skipped`). After Task 2 it is `2 failed, 2728 passed, 2 skipped`, with the gate line `lost 0; new tests 10, not passing 0` and `GATE PASS` | gate, V1 |
| PBK2 | Between `599b1c7` and the final commit, the only pinned files that change are `story_engine.py` (numstat `77 4`) and `bin/ltx-movie` (`1 1`). The only other non-docs files are `tests/test_plan_budget.py` (new, `271 0`) and `tests/test_movie_ui_builder.py` (`2 2`) | V1 |
| PBK3 | A reply that is not cut off takes today's path byte for byte: the no-catalog budget, the retry prompt, the messages and `run.json` are unchanged. No existing test is edited except the two lines of `test_mut26` | PBT1, PBT6, PBT7, the unchanged suites |
| PBK4 | On macstudio, the user's failing command (15 panels, shots, auto-lora) gets a usable plan in at most 2 plan calls | L3 |
| PBK5 | The dry run of that command prints `--max-tokens 6800`. With `--no-auto-lora` it prints `--max-tokens 4250` | L2 |
| PBK6 | Every plan call of L3 ends with status `ok` inside its subprocess timeout (680 s for 17 beats). Its seconds, and any `cut_off_at_tokens`, are recorded | L3 |

Every PB requirement and every PBT test is a must-have. There are no nice-to-haves.

---

## 1. Decisions

1. **The catalog budget is 400 tokens per beat [spec choice].**
   - `plan_max_tokens(n, catalog=False)` is `max(4096, n * (400 if catalog else 250))`.
   - Why a catalog plan needs more: it also writes the `loras` object (`global`; `per_beat`, with one entry per beat that gets a motion or physics pick; `stills`). Its beats also carry the speaker and lines keys of a dialogue-heavy narrative.
   - Why 400: the reported run (17 beats) gets `6800` tokens, 1.6 times the `4250` that cut it off. Every catalog run of at most 10 beats (8 target panels) keeps `4096`, so `test_rst47` (6 beats, one compatible entry) does not change.
   - The condition is the same test the plan prompt uses (`ctx.auto_lora and compatible`), so the budget grows exactly when the prompt asks for LoRA picks.
2. **Detection lives in story_engine, not in bin/qwen-agent [spec choice].**
   - A cut-off reply is recognised from its text (PB3): envelope status `ok`, no object found by `extract_json`, and a `{` whose object never closes.
   - Exposing `finish_reason` in the envelope was considered and rejected for this fix:
     - bin/qwen-agent is pinned;
     - its envelope is also read by `_envelope_to_result` and the fleet delegate path;
     - `run_agent`'s `(status, answer)` tuple is asserted by RST6 and used by every engine call.
   - The text test needs none of those changes, and it also works with remote endpoints that report no finish reason.
   - bin/qwen-agent's stderr note stays as it is (follow-up F1).
3. **Only status `ok` counts.** A forced summary (`max_rounds`, `context_budget`, `truncated`), or any other status, is never reported as a cut-off, even when its text has an unclosed `{`. Only an `ok` reply is the model's own attempt at the JSON.
4. **The retry after a cut-off gets 1.5 times the budget [spec choice].**
   - `escalated_plan_tokens(b) = max(b, min(16384, b * 3 // 2))`. Examples: `6800 -> 10200`, `4250 -> 6375`, `4096 -> 6144`.
   - 1.5 times covers a reply up to 50% over budget in one step, without doubling the time of a call that gets cut off again.
   - The 16384 cap limits the request size when the served context window is small (Risk R1).
   - The outer `max` stops a budget already above the cap (more than 40 catalog beats) from shrinking.
   - `PLAN_MAX_CALLS` stays 2, so there is exactly one increase.
5. **The retry prompt after a cut-off leaves out the partial reply [spec choice].**
   - It is the original prompt plus `PLAN_CUT_OFF_RETRY` (PB5): no problem list and no "Previous reply:" block.
   - Reasons: the partial reply holds no plan that can be checked; it would add up to 20000 characters to the request; and it invites the model to continue it rather than start again.
   - It asks for compact JSON (no indentation, no line breaks). That shortens the same plan without shortening any field the checks measure.
   - A retry after any other problem keeps today's text byte for byte.
6. **The final error names a cut-off only when the last call was cut off (PB6).**
   - `go` prints the cut-off problem when no call produced a parsable plan and the last call was cut off. Otherwise it prints today's list.
   - The hint names what the user can change: fewer panels (`--panels` or `--length`), plus `--no-auto-lora`, which is named only for a catalog plan.
7. **run.json gains one field, and only on a cut-off (PB7).** The plan call record of a cut-off reply gains `"cut_off_at_tokens": <budget>`. No other record changes, so the `run.json` of a run with no cut-off is byte-identical. No new `budgets` key is added **[spec choice]**.
8. **No dialogue term, and `test_rs4_constants` is not edited [spec choice].**
   - The plan's beats hold line NUMBERS (`"lines": [3]`) and a speaker id, never the spoken text. Dialogue therefore adds about 10-15 tokens per beat, which the catalog's extra 150 tokens per beat cover.
   - A separate dialogue term would also change the no-catalog budget, which must stay byte-identical.
   - A dialogue-heavy no-catalog plan that still overflows is caught by PB3-PB5.
   - `tests/test_story_engine.py:97` passes as it is and keeps pinning the no-catalog formula. PBT1 pins the catalog values.
9. **The dry run shows the first call's budget (PB2).** bin/ltx-movie's dry run calls the same `plan_tokens(ctx, compatible)` as `plan_round`, so the printed `--max-tokens` is the first call's real budget. The increased budget is not printed, because it exists only after a cut-off.

---

## 2. Requirements

- **PB1 (the formula).** `plan_max_tokens(n, catalog=False)` returns `max(4096, n * PLAN_CATALOG_TOKENS_PER_BEAT)` when `catalog` is true, and `max(4096, n * 250)` otherwise. `PLAN_CATALOG_TOKENS_PER_BEAT = 400`. Called with one argument, `plan_max_tokens(n)` returns exactly today's value for every `n`.
- **PB2 (the first budget).** `plan_tokens(ctx, compatible)` returns `plan_max_tokens(most_panels(ctx), catalog=bool(ctx.auto_lora and compatible))`. `plan_round`'s first call and the bin/ltx-movie dry run both use it. Their `compatible` is `self.compatible` and the dry run's `compatible` respectively; both come from `compatible_entries(ctx)`.
- **PB3 (detection).** `cut_off_json(text)` returns `True` exactly when all of these hold:
  - `text` is a non-empty string that contains `{`;
  - scanning from its first `{`, with `{` and `[` counting up and `}` and `]` counting down, the depth never returns to 0;
  - characters inside JSON strings are not counted: a `"` opens and closes a string, and inside one a backslash escapes the next character.

  A plan reply is a cut-off reply when `extract_json(answer) is None`, the envelope status is `"ok"`, and `cut_off_json(answer)` is true.
- **PB4 (the note).** On a cut-off reply to call `a` with budget `b`, `plan_round` prints `PLAN_CUT_OFF_NOTE % (a, b)` to stdout. When `a < PLAN_MAX_CALLS`, the same line continues with `PLAN_CUT_OFF_NEXT % (a + 1, escalated_plan_tokens(b))`.
- **PB5 (the retry).**
  - After a cut-off reply, the next call's prompt is `prompt + PLAN_CUT_OFF_RETRY % (b, escalated_plan_tokens(b))`, and its budget is `escalated_plan_tokens(b)`, with `PLAN_MAX_TOKENS_CAP = 16384`.
  - After any other rejected reply, the prompt is today's and the budget does not change. So a call that follows a cut-off and then a garbage reply keeps the increased budget.
  - The subprocess timeout stays `plan_timeout(most_panels(ctx))`.
- **PB6 (the final message).**
  - `self.plan_cut_off` is set on every plan call. For a cut-off reply it is `PLAN_CUT_OFF_PROBLEM % (b, a, " or --no-auto-lora" if ctx.auto_lora and self.compatible else "")`; otherwise it is `None`.
  - When the run has no parsable plan, `go`'s fatal list is `[self.plan_cut_off or "the reply is not one JSON object"]`. When it has one, the list is today's `plan_fatal(found)`.
- **PB7 (run.json).** The `calls` record of a cut-off plan call gains `"cut_off_at_tokens": b`, written immediately (`write_run`). No other record or key changes.
- **PB8 (nothing else changes).** For a reply that parses, or that does not meet PB3, every printed line, prompt, file and exit code is today's. So is every budget, apart from PB1's catalog budget.

## 3. Messages and run.json (exact)

| Constant | Text (`%` arguments) | Where |
|---|---|---|
| `PLAN_CUT_OFF_NOTE` | `plan: reply %d was cut off at %d tokens before its JSON object closed` (call, budget) | stdout, each cut-off call |
| `PLAN_CUT_OFF_NEXT` | `; call %d gets %d tokens` (next call, next budget) | added to the end of the note when another call follows |
| `PLAN_CUT_OFF_PROBLEM` | `the reply was cut off at %d tokens, the token budget of call %d, before its JSON object closed; fewer panels (--panels or --length)%s make the plan shorter` (budget, call, `" or --no-auto-lora"` or `""`) | stderr, the bullet under `Error: the story model did not return a usable plan after 2 call(s)` |
| `PLAN_CUT_OFF_RETRY` | `\n\nYOUR PREVIOUS REPLY WAS CUT OFF: it reached its limit of %d tokens before the JSON object closed, so it was discarded. This reply may use up to %d tokens. Write the complete JSON object compactly, with no indentation and no line breaks, so that it fits, and reply with the JSON object only.` (budget, next budget) | the retry prompt |

If the reported run is cut off twice, it ends like this (the `plan:` lines go to stdout, the last three lines to stderr):
```
plan: call 1 of 2
plan: reply 1 was cut off at 6800 tokens before its JSON object closed; call 2 gets 10200 tokens
plan: call 2 of 2
plan: reply 2 was cut off at 10200 tokens before its JSON object closed
Error: the story model did not return a usable plan after 2 call(s)
  - the reply was cut off at 10200 tokens, the token budget of call 2, before its JSON object closed; fewer panels (--panels or --length) or --no-auto-lora make the plan shorter
Raw replies are kept in <story>/story_rounds/round_0. Rerun the same command to try again.
```
Its `run.json` plan records are then `{"stage": "plan", "panel": null, "round": 0, "attempt": 1, "route": null, "status": "ok", "seconds": ..., "cut_off_at_tokens": 6800}`, and the same with `"attempt": 2` and `10200`.

## 4. Tests (`tests/test_plan_budget.py`, new; every test uses the fake bin/qwen-agent or no agent)

| Test | Pins |
|---|---|
| PBT1 `test_pbt1_the_budget_formulas_and_the_messages` | PB1 and PB5 formulas (`4096, 7500`; `4096, 4250`; catalog `4096, 6800, 18000`; increases `6144, 6375, 10200, 16384, 18000`) and the four message constants word for word |
| PBT2 `test_pbt2_plan_tokens_follows_the_lora_paragraph` | PB2 for 15 shots panels: `6800` with a compatible entry; `4250` with `auto_lora=False` or an empty catalog. `LORA_PICK_PARAGRAPH` is in the prompt exactly when the budget is the catalog one, also with `auto_lora=False` and an explicit compatible list. 4 panels with a catalog give `4096`. `panels_target` 15 with 17 panels gives `6800` |
| PBT3 `test_pbt3_cut_off_json` | PB3 on cut prefixes, fences, strings that contain braces, escaped quotes and backslashes, closed objects, `None`, empty text and text with no brace |
| PBT4 `test_pbt4_a_cut_off_reply_is_retried_with_more_tokens` | PB3-PB5 and PB7. The fake agent returns a cut-off JSON reply with status ok, then a valid plan. Budgets are `4096, 6144`. The retry prompt is exactly `prompt + PLAN_CUT_OFF_RETRY % (4096, 6144)`, with no "Previous reply:". The three `plan:` lines appear. `cut_off_at_tokens` 4096 is on record 1 only. `plan_reply_1.txt` holds the partial reply. The run completes (rc 0) |
| PBT5 `test_pbt5_fifteen_panel_auto_lora_cut_off_twice` | The reported case: shots, 15 panels, one compatible entry, two cut-off replies. Budgets are `6800, 10200`. Exact stderr with the `--no-auto-lora` hint; the four `plan:` lines; `cut_off_at_tokens` `[6800, 10200]`; rc 1; no panel call |
| PBT6 `test_pbt6_without_catalog_picks_the_budget_is_unchanged[True\|False]` | PB1 and PB6: shots, 15 panels, no catalog picks (an empty catalog, or a catalog with `auto_lora=False`). Budgets are `4250, 6375`; the stderr bullet has no hint |
| PBT7 `test_pbt7_complete_and_non_ok_replies_keep_todays_path` | PB8. `{not json}` then a valid plan keeps budgets `4096, 4096`, today's REJECTED retry text, no `cut_off_at_tokens` and no cut-off line. An unclosed reply with status `max_rounds`, twice, gives today's error |
| PBT8 `test_pbt8_a_cut_off_then_garbage_reply_keeps_the_generic_message` | PB5 and PB6. A cut-off reply, then `nope`: budgets `4096, 6144`, today's bullet, `cut_off_at_tokens` `[4096, None]` |
| PBT9 `test_pbt9_the_dry_run_prints_the_first_calls_budget` | PB2 through the real `bin/ltx-movie --dry-run --shots --panels 15`: `6800` with a compatible catalog, `4250` with `--no-auto-lora`, `4250` with no catalog; timeout `680s`; no story directory is created |

**Mutation check** (replayed; see "Replay result"). Each of these mutations makes at least one PBT fail:
- dropping the status-`ok` condition;
- dropping the budget increase;
- dropping `go`'s cut-off message;
- dropping the per-call reset of `plan_cut_off`;
- dropping the `run.json` field;
- dropping the backslash handling;
- dropping the `[` counting;
- dropping the outer `max`;
- dropping the `ctx.auto_lora` condition;
- reverting the dry-run line;
- dropping the "no next call" condition of the note.

## 5. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

Run these from the workspace root on macstudio after merging. `<cmd>` is the exact bin/ltx-movie command that failed (shots, auto-lora, 15 panels), `<id>` is its `--story-id`, and `R=generated/stories/<id>/story_rounds`.

- **L1 (the failed run's reply, before rerunning).** The failed run's rounds directory stays at `$R` until the next run moves it aside.
  1. Run `wc -c $R/round_0/plan_reply_1.txt $R/round_0/plan_reply_2.txt` and `tail -c 200 $R/round_0/plan_reply_1.txt`.
  2. Expected: the tail stops inside the JSON (no closing `}`). The size is roughly 3 to 4 characters per token of 4250, about 12000-17000 characters.
  3. Record both sizes.
  4. If the size is far below that (under about 8000 characters), hidden reasoning tokens are also using up the budget. This fix helps (there is more budget), but it does not remove the cause. Report it (follow-up F3).
- **L2 (the dry run).**
  1. `<cmd> --dry-run --no-review | grep -m1 '^Command (subprocess timeout' | grep -o -- '--max-tokens [0-9]*'` prints `--max-tokens 6800` for `--panels 15`. For another target T, the value is `max(4096, (T + 2) * 400)`.
  2. `<cmd> --dry-run --no-review --no-auto-lora | grep -m1 '^Command (subprocess timeout' | grep -o -- '--max-tokens [0-9]*'` prints `--max-tokens 4250` (PBK5).
- **L3 (the rerun).**
  1. Run `<cmd> --story-only`. This runs Phase 0 (when there is a seed image) and Phase 1, then stops. Run the full `<cmd>` afterwards; it re-checks the story.md that this step wrote instead of regenerating it.
  2. Expected: Phase 1 gets past the plan. You see `plan: call 1 of 2`, then panel lines (`panel 1/..: call 1`), and no `did not return a usable plan` (PBK4).
  3. If call 1 was cut off, the line `plan: reply 1 was cut off at 6800 tokens before its JSON object closed; call 2 gets 10200 tokens` appears, and call 2 succeeds.
  4. Record the plan calls with `python3 -c 'import json,sys; [print(c["attempt"], c["status"], c["seconds"], c.get("cut_off_at_tokens")) for c in json.load(open(sys.argv[1]))["calls"] if c["stage"] == "plan"]' $R/run.json`, and the reply sizes with `wc -c $R/round_0/plan_reply_*.txt`. PBK6 expects every status to be `ok` and every seconds value to be under 680.
- **L4 (only if L3 still fails).**
  - If both calls are cut off, the error now says so (`the reply was cut off at 10200 tokens, ...`). Record the two reply sizes and the `run.json` lines from L3 and report them. Do not rerun with other flags first.
  - If the error still has the old wording, `the reply is not one JSON object`, the reply was not cut off. Keep `$R/round_0/plan_reply_*.txt` and report.

## 6. Risks (rulings), follow-ups and open questions

**Risks.**
- **R1 (a small served context window).** bin/qwen-agent refuses a request whose estimated prompt, plus the budget, plus 1024 exceeds the served window (`context_budget`, `bin/qwen-agent:3246-3248`), and returns a forced summary instead. With the default 120000-token window this cannot happen. With a 16K window, a 10200-token retry could hit it and end with today's generic message. Ruling: accepted. The cap is 16384, and the retry prompt no longer includes the partial reply.
- **R2 (a false cut-off).** A model that stops by itself inside an unclosed object (status `ok`) is reported as cut off and retried with more tokens. Ruling: harmless, because a retry is what the user needs either way.
- **R3 (a clamped budget).** A server that clamps `max_tokens` to the remaining context (MTPLX does this) cuts the reply off before `b`, but the message still names `b`. Ruling: accepted.
- **R4 (time).** At the reported rate (about 4250 tokens in 45 s), a 10200-token call takes about 110 s, well inside the 600 s request timeout. On a 20 tokens/s endpoint, the retry of a catalog plan with more than about 23 target panels could exceed it (follow-up F4).
- **R5 (compact retry).** The retry reply is one long line in `plan_reply_2.txt`. `extract_json` and every check read it the same way as indented JSON.

**Follow-ups (not fixed here).**
- **F1.** Add `finish_reason` (or a `truncated` flag) to bin/qwen-agent's one-shot envelope, and have `run_agent` return it. Every engine call could then tell a cut-off reply from a malformed one with certainty.
- **F2.** Panel and critic calls have the same blind spot: a cut-off panel reply reads as "not one JSON object with the keys ...". Apply PB3-PB5 to them.
- **F3.** If L1 shows that hidden reasoning uses up the budget, size the plan budget for it, or turn reasoning off for plan calls.
- **F4.** Scale `plan_timeout` and the request timeout with the increased budget, for slow or remote endpoints.
- **F5.** When `--story-context-window` is known, also cap the increased budget by the served context window.
- **F6.** Tune `PLAN_CATALOG_TOKENS_PER_BEAT`, and decide on a dialogue term, from the reply sizes recorded in L1 and L3.

**Open questions (none blocks implementation).**
- **Q1.** If L3 shows call 2 still cut off at 10200, should the increase be 2x instead? (With 2x, the cap binds from a budget of 8192 up.) Decide from L4's sizes.
- **Q2.** Should the dry run also print the increased budget, for example `(10200 after a cut-off reply)`? Not done here, because it would change the pinned format of the `Command (...)` line.

---

## Plan

**House rules** (every task):
- Work only in `$S/pb-wt`. Never touch `/Users/reubenpatterson/local_agent_harness` or `/Users/ailab1`.
- Never stash, reset, amend, push or open a PR. Never access macstudio (no ssh, no scp, no reading its files).
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's Old text must occur exactly once in the file when the Edit is applied. If it does not, stop and report.
- `story_engine.py`, `bin/ltx-movie` and `tests/test_plan_budget.py` must compile on both `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- The PR is merged with a merge commit only (never squash or rebase), so the sha that Task 2 writes into BASELINE stays reachable.

**Replay.** Every step below was replayed in an rsync copy of the worktree at `599b1c7`, without `.git` (`$S/pb-replay`).
- The Old/New blocks of Task 1 were applied by script, in order, and each Old occurred exactly once.
- A second script extracted every block from this document, applied the blocks to a fresh copy (`$S/pb-check`), and found the result byte-identical to the replay.
- The results are in "Replay result" at the end.

### Before Task 1: the snapshot, the baseline and the gate files (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/pb-baseline; mkdir -p $D
cd $S/pb-wt/qwen-agent-workspace
git branch --show-current                                     # plan-budget
git diff --stat 599b1c7 HEAD -- . ':(exclude)docs' | tail -1  # no output (only this spec is committed)
git status --short                                            # no output
wc -l story_engine.py bin/ltx-movie tests/test_movie_ui_builder.py   # 5494, 4208, 302
ls -l $S/snapshot-pre-pb-599b1c7.tgz || tar czf $S/snapshot-pre-pb-599b1c7.tgz --exclude generated -C $S/pb-wt qwen-agent-workspace
df -g . | tail -1                                             # at least 5 GiB free
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                     # record as P0
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
```

Expected:
- The summary is `2 failed, 2718 passed, 2 skipped` (so P0 is 2718). That was the seeded-shots-context Task 3 result (`$S/sc-baseline/task-3-pytest.txt`), on a tree identical to `599b1c7` (`6e93fda` and `599b1c7` have no diff).
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. There is no `ERROR` line, and `test_mut26` passes.
- `baseline-ok-lines.txt` holds `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68` and `OK 205/205`.

If `test_tr27_fanout_two_rounds_and_missing_reasons`, `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` or `test_trt46_post_spans_validation_cap_and_store` also fails, rerun those three alone. `3 passed` means the baseline stands. For any other difference, stop and report.

Then write the gate files (scratch files, never staged), based on the seeded-shots-context plan's:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/pb-baseline
python3 - "$S/sc-baseline/gate.py" "$D/gate.py" <<'PYEOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
old = 'NEW_FILES = ("tests/test_ltx_movie_seed_context.py::", "tests/test_ltx_movie_seed_context_frame.py::")'
assert s.count(old) == 1, old
s = s.replace(old, 'NEW_FILES = ("tests/test_plan_budget.py::",)')
open(sys.argv[2], "w", encoding="utf-8").write(s)
PYEOF
sed -e 's#/sc-baseline#/pb-baseline#' -e 's#/sc-wt/#/pb-wt/#' $S/sc-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'TXTEOF'
# plan budget plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged story_engine.py and bin/ltx-movie change in Task 1; Task 2 moves BASELINE
1 2 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
TXTEOF
grep -c pb-baseline $D/gate-run.sh; grep -c /pb-wt/ $D/gate-run.sh; grep -c '"tests/test_plan_budget.py::",' $D/gate.py; grep -c test_trt46 $D/gate-run.sh   # 1, 1, 1, 1
```

**The gate** for task N is `zsh $S/pb-baseline/gate-run.sh N`. It is a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints `disk ok`, the pytest summary, the gate line, `GATE PASS`, `3 passed` for the flake rerun, and `ATK2 OK lines unchanged`. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids, with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the plan budget and cut-off replies in `story_engine.py` and the dry-run line in `bin/ltx-movie` (one commit)

**Files:** `story_engine.py` (pinned), `bin/ltx-movie` (pinned), `tests/test_plan_budget.py` (new).

**Interfaces** (new or changed; everything else is unchanged):
- `story_engine.PLAN_CATALOG_TOKENS_PER_BEAT = 400`, `story_engine.PLAN_MAX_TOKENS_CAP = 16384`, and the strings `PLAN_CUT_OFF_NOTE`, `PLAN_CUT_OFF_NEXT`, `PLAN_CUT_OFF_PROBLEM`, `PLAN_CUT_OFF_RETRY` (Section 3).
- `story_engine.plan_max_tokens(n, catalog=False) -> int` (was `plan_max_tokens(n)`; same value when `catalog` is false).
- `story_engine.plan_tokens(ctx, compatible) -> int`.
- `story_engine.escalated_plan_tokens(budget) -> int`.
- `story_engine.cut_off_json(text) -> bool`.
- `_Run.plan_cut_off`: a `str` or `None`, set by `plan_round` on every plan call and read by `go`.

- [ ] **Step 1: Write `tests/test_plan_budget.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for the plan token budget and cut-off replies (docs/superpowers/specs/2026-11-10-plan-
budget-truncation-design.md, PB1-PB8: PBT1-PBT9): a plan that picks catalog LoRAs gets a larger
first budget, a reply cut off inside its JSON object is named, recorded in run.json and retried
once with half as much budget again, and every complete reply takes today's path unchanged.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_plan_budget.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws); the dry-run test runs the real bin/ltx-movie --dry-run, which makes no model call. No
test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import importlib.machinery
import json
import os
import shlex
import subprocess
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_plan_budget", os.path.join(WS, "story_engine.py")).load_module()

NARRATIVE = "A courier carries a sealed letter across a rainy harbour town."
HEADER = "Error: the story model did not return a usable plan after 2 call(s)\n"
FOOTER = "Raw replies are kept in %s. Rerun the same command to try again.\n"


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _cut(mode, n, keep=300):
    """A plan reply cut off after keep characters (status ok, as bin/qwen-agent reports it)."""
    full = json.dumps(seu.plan_json(mode, n))
    assert len(full) > keep
    return {"answer": full[:keep]}


def _catalog(tmp_path):
    entry = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "fast"), "fast-motion")
    return {"schema_version": 1, "entries": [entry]}


def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _run(ws, tmp_path, monkeypatch, plan, mode="chained", n=3, panel=None, critic=(), **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=panel or {},
                           critic=list(critic))
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _budgets(log):
    return [r["argv"][r["argv"].index("--max-tokens") + 1] for r in log if r["stage"] == "plan"]


def _rounds0(ctx):
    return os.path.join(ctx.story_dir, "story_rounds", "round_0")


def _plan_calls(ctx):
    with open(os.path.join(ctx.story_dir, "story_rounds", "run.json"), encoding="utf-8") as f:
        return [c for c in json.load(f)["calls"] if c["stage"] == "plan"]


def _plan_lines(out):
    return [line for line in out.splitlines() if line.startswith("plan: ")]


# --- PBT1 (PB1, PB5, PB6): the budget formulas and the exact messages -------------------------

def test_pbt1_the_budget_formulas_and_the_messages():
    assert (se.plan_max_tokens(14), se.plan_max_tokens(30)) == (4096, 7500)
    assert (se.plan_max_tokens(5), se.plan_max_tokens(17)) == (4096, 4250)
    assert (se.plan_max_tokens(6, catalog=True), se.plan_max_tokens(17, catalog=True),
            se.plan_max_tokens(45, catalog=True)) == (4096, 6800, 18000)
    assert (se.PLAN_CATALOG_TOKENS_PER_BEAT, se.PLAN_MAX_TOKENS_CAP) == (400, 16384)
    assert [se.escalated_plan_tokens(b) for b in (4096, 4250, 6800, 12000, 18000)] == [
        6144, 6375, 10200, 16384, 18000]
    assert se.PLAN_CUT_OFF_NOTE % (1, 6800) == (
        "plan: reply 1 was cut off at 6800 tokens before its JSON object closed")
    assert se.PLAN_CUT_OFF_NEXT % (2, 10200) == "; call 2 gets 10200 tokens"
    assert se.PLAN_CUT_OFF_PROBLEM % (10200, 2, " or --no-auto-lora") == (
        "the reply was cut off at 10200 tokens, the token budget of call 2, before its JSON "
        "object closed; fewer panels (--panels or --length) or --no-auto-lora make the plan "
        "shorter")
    assert se.PLAN_CUT_OFF_RETRY % (6800, 10200) == (
        "\n\nYOUR PREVIOUS REPLY WAS CUT OFF: it reached its limit of 6800 tokens before the JSON "
        "object closed, so it was discarded. This reply may use up to 10200 tokens. Write the "
        "complete JSON object compactly, with no indentation and no line breaks, so that it "
        "fits, and reply with the JSON object only.")


# --- PBT2 (PB1, PB2): the first budget follows the plan prompt's LoRA paragraph ---------------

def test_pbt2_plan_tokens_follows_the_lora_paragraph(ws, tmp_path):
    catalog = _catalog(tmp_path)
    cases = [(dict(catalog=catalog), 6800, True),
             (dict(catalog=catalog, auto_lora=False), 4250, False),
             (dict(), 4250, False)]
    for kw, budget, picks in cases:
        ctx = seu.make_ctx(se, ws, mode="shots", panels=15, **kw)
        compatible = se.compatible_entries(ctx)
        assert se.plan_tokens(ctx, compatible) == budget, kw
        prompt = se.build_plan_prompt(ctx, compatible, ctx.pinned)
        assert (se.LORA_PICK_PARAGRAPH in prompt) == picks, kw
    off = seu.make_ctx(se, ws, mode="shots", panels=15, catalog=catalog, auto_lora=False)
    assert se.plan_tokens(off, catalog["entries"]) == 4250
    assert se.LORA_PICK_PARAGRAPH not in se.build_plan_prompt(off, catalog["entries"], off.pinned)
    ctx = seu.make_ctx(se, ws, mode="shots", panels=4, catalog=catalog)
    assert se.plan_tokens(ctx, se.compatible_entries(ctx)) == 4096
    target = seu.make_ctx(se, ws, mode="shots", panels=17, panels_target=15, catalog=catalog)
    assert se.plan_tokens(target, se.compatible_entries(target)) == 6800


# --- PBT3 (PB3): cut_off_json -------------------------------------------------------------------

def test_pbt3_cut_off_json():
    full = json.dumps(seu.plan_json("shots", 15))
    assert se.cut_off_json(full[:-1]) is True
    assert se.cut_off_json(full) is False
    assert se.cut_off_json("```json\n" + full[:2000]) is True
    assert se.cut_off_json("```json\n" + full + "\n```") is False
    assert se.cut_off_json('Sure! {"a": [1, 2') is True
    assert se.cut_off_json('{"a": "}"') is True
    assert se.cut_off_json('{"a": "x\\"}"') is True
    assert se.cut_off_json('{"a": "x\\"y"}') is False
    assert se.cut_off_json('{"a": "\\\\"}') is False
    assert se.cut_off_json("{not json}") is False
    for text in (None, "", "   ", "no braces at all", "[1, 2", "I think the story is about rain."):
        assert se.cut_off_json(text) is False, text


# --- PBT4 (PB3-PB5, PB7): a cut-off reply is retried with more tokens, then the run goes on -----

def test_pbt4_a_cut_off_reply_is_retried_with_more_tokens(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("chained", 3),
                                                    seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert _budgets(log) == ["4096", "6144"]
    first, second = log[0]["argv"][-1], log[1]["argv"][-1]
    assert second == first + se.PLAN_CUT_OFF_RETRY % (4096, 6144)
    assert "Previous reply:" not in second
    assert _plan_lines(capsys.readouterr().out) == [
        "plan: call 1 of 2",
        "plan: reply 1 was cut off at 4096 tokens before its JSON object closed; call 2 gets "
        "6144 tokens",
        "plan: call 2 of 2"]
    calls = _plan_calls(ctx)
    assert calls[0]["cut_off_at_tokens"] == 4096 and calls[0]["status"] == "ok"
    assert "cut_off_at_tokens" not in calls[1]
    with open(os.path.join(_rounds0(ctx), "plan_reply_1.txt"), encoding="utf-8") as f:
        assert f.read() == _cut("chained", 3)["answer"]


# --- PBT5 (PB1-PB7): the 15-panel auto-lora run of the report, cut off twice ---------------------

def test_pbt5_fifteen_panel_auto_lora_cut_off_twice(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("shots", 15, 2000),
                                                    _cut("shots", 15, 3000)],
                        mode="shots", n=15, catalog=_catalog(tmp_path))
    assert rc == 1
    assert _budgets(log) == ["6800", "10200"]
    assert [r["stage"] for r in log] == ["plan", "plan"]
    captured = capsys.readouterr()
    assert captured.err == (
        HEADER + "  - the reply was cut off at 10200 tokens, the token budget of call 2, before "
        "its JSON object closed; fewer panels (--panels or --length) or --no-auto-lora make the "
        "plan shorter\n" + FOOTER % _rounds0(ctx))
    assert _plan_lines(captured.out) == [
        "plan: call 1 of 2",
        "plan: reply 1 was cut off at 6800 tokens before its JSON object closed; call 2 gets "
        "10200 tokens",
        "plan: call 2 of 2",
        "plan: reply 2 was cut off at 10200 tokens before its JSON object closed"]
    assert [c.get("cut_off_at_tokens") for c in _plan_calls(ctx)] == [6800, 10200]
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + se.PLAN_CUT_OFF_RETRY % (6800, 10200)


# --- PBT6 (PB1, PB8): without catalog picks the budget is today's ------------------------------

@pytest.mark.parametrize("auto_lora", [True, False])
def test_pbt6_without_catalog_picks_the_budget_is_unchanged(ws, tmp_path, monkeypatch, capsys,
                                                            auto_lora):
    catalog = _catalog(tmp_path) if not auto_lora else {"schema_version": 1, "entries": []}
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("shots", 15), _cut("shots", 15)],
                        mode="shots", n=15, catalog=catalog, auto_lora=auto_lora)
    assert rc == 1
    assert _budgets(log) == ["4250", "6375"]
    assert capsys.readouterr().err == (
        HEADER + "  - the reply was cut off at 6375 tokens, the token budget of call 2, before "
        "its JSON object closed; fewer panels (--panels or --length) make the plan shorter\n"
        + FOOTER % _rounds0(ctx))


# --- PBT7 (PB8): a closed reply, or an unclosed one whose status is not ok, keeps today's path ----

def test_pbt7_complete_and_non_ok_replies_keep_todays_path(ws, tmp_path, monkeypatch, capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [{"answer": "{not json}"},
                                                    seu.answer(seu.plan_json("chained", 3))],
                        panel=_panel_script("chained", 3),
                        critic=[seu.answer(seu.critic_json())])
    assert rc == 0
    assert _budgets(log) == ["4096", "4096"]
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object\n"
            "Previous reply:\n{not json}\n\nReply with the complete corrected JSON object only."
            ) in log[1]["argv"][-1]
    assert not [c for c in _plan_calls(ctx) if "cut_off_at_tokens" in c]
    assert "was cut off" not in capsys.readouterr().out
    cut = dict(_cut("chained", 3), status="max_rounds")
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [cut, dict(cut)], story_id="s2")
    assert rc == 1
    assert _budgets(log) == ["4096", "4096"]
    assert capsys.readouterr().err == (HEADER + "  - the reply is not one JSON object\n"
                                       + FOOTER % _rounds0(ctx))
    assert not [c for c in _plan_calls(ctx) if "cut_off_at_tokens" in c]


# --- PBT8 (PB4, PB6): only the last call's cut-off is named --------------------------------------

def test_pbt8_a_cut_off_then_garbage_reply_keeps_the_generic_message(ws, tmp_path, monkeypatch,
                                                                      capsys):
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [_cut("chained", 3), {"answer": "nope"}])
    assert rc == 1
    assert _budgets(log) == ["4096", "6144"]
    assert capsys.readouterr().err == (HEADER + "  - the reply is not one JSON object\n"
                                       + FOOTER % _rounds0(ctx))
    assert [c.get("cut_off_at_tokens") for c in _plan_calls(ctx)] == [4096, None]


# --- PBT9 (PB2): the dry run prints the first call's budget ------------------------------------

def test_pbt9_the_dry_run_prints_the_first_calls_budget(tmp_path, story_env):
    seu.make_catalog(story_env["catalog"], _catalog(tmp_path)["entries"])
    story_dir = os.path.join(WS, "generated", "stories", "pbt9-%d" % os.getpid())
    assert not os.path.exists(story_dir)

    def budget(*flags):
        proc = subprocess.run([sys.executable, os.path.join(WS, "bin", "ltx-movie"), NARRATIVE,
                               "--story-id", os.path.basename(story_dir), "--dry-run",
                               "--no-review", "--shots", "--panels", "15"] + list(flags),
                              cwd=WS, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        argv = shlex.split(proc.stdout.split("Command (subprocess timeout 680s): ", 1)[1]
                           .split("\n\nRendered plan prompt:\n", 1)[0])
        return argv[argv.index("--max-tokens") + 1]

    assert budget() == "6800"
    assert budget("--no-auto-lora") == "4250"
    os.remove(os.path.join(story_env["catalog"], "catalog.json"))
    assert budget() == "4250"
    assert not os.path.exists(story_dir)
````

- [ ] **Step 2: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/pb-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_plan_budget.py 2>&1 | tail -1
```
Expected: `9 failed, 1 passed, ... warnings in ...s`. The one test that passes is PBT7, which pins today's behaviour. PBT1 fails with a `TypeError` (`plan_max_tokens` has no `catalog` argument yet), PBT2 and PBT3 with `AttributeError`s (no `plan_tokens` or `cut_off_json` yet), and the other six on their budgets (for example `['4096', '4096'] == ['4096', '6144']`).

- [ ] **Step 3: Edit `story_engine.py` (E1, the budget).** Old:
```python
def plan_max_tokens(n):
    return max(4096, n * 250)
```
New:
```python
# Plan token budget spec PB1, PB2 (docs/superpowers/specs/2026-11-10-plan-budget-truncation-
# design.md): a plan that picks catalog LoRAs also writes the loras object, so it gets
# PLAN_CATALOG_TOKENS_PER_BEAT tokens per beat instead of 250. PB5: the call after a reply cut off
# at its budget gets half as much again, at most PLAN_MAX_TOKENS_CAP and never less than before.
PLAN_CATALOG_TOKENS_PER_BEAT = 400
PLAN_MAX_TOKENS_CAP = 16384
PLAN_CUT_OFF_NOTE = "plan: reply %d was cut off at %d tokens before its JSON object closed"
PLAN_CUT_OFF_NEXT = "; call %d gets %d tokens"
PLAN_CUT_OFF_PROBLEM = ("the reply was cut off at %d tokens, the token budget of call %d, before "
                        "its JSON object closed; fewer panels (--panels or --length)%s make the "
                        "plan shorter")
PLAN_CUT_OFF_RETRY = ("\n\nYOUR PREVIOUS REPLY WAS CUT OFF: it reached its limit of %d tokens "
                      "before the JSON object closed, so it was discarded. This reply may use up "
                      "to %d tokens. Write the complete JSON object compactly, with no "
                      "indentation and no line breaks, so that it fits, and reply with the JSON "
                      "object only.")


def plan_max_tokens(n, catalog=False):
    return max(4096, n * (PLAN_CATALOG_TOKENS_PER_BEAT if catalog else 250))


def plan_tokens(ctx, compatible):
    """The first plan call's max_tokens (PB1, PB2): the catalog budget exactly when the plan
    prompt asks for LoRA picks, that is auto LoRA is on and the compatible set is not empty (the
    test build_plan_prompt makes)."""
    return plan_max_tokens(most_panels(ctx), catalog=bool(ctx.auto_lora and compatible))


def escalated_plan_tokens(budget):
    """The max_tokens of the plan call after a reply cut off at budget (PB5)."""
    return max(budget, min(PLAN_MAX_TOKENS_CAP, budget * 3 // 2))
```

- [ ] **Step 4: Edit `story_engine.py` (E2, `cut_off_json` after `extract_json`).** Old:
```python
    return value if isinstance(value, dict) else None


def parse_violation(text):
```
New:
```python
    return value if isinstance(value, dict) else None


def cut_off_json(text):
    """True when text holds a JSON object that never closes (plan token budget spec PB3): from
    the first {, counting { [ against } ] outside JSON strings (with backslash escapes), the
    depth never returns to 0. False for None, for text without a { and for any closed object."""
    if not text or "{" not in text:
        return False
    depth, in_string, escaped = 0, False, False
    for ch in text[text.index("{"):]:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return False
    return True


def parse_violation(text):
```

- [ ] **Step 5: Edit `story_engine.py` (E3, `plan_round`).** Old:
```python
        text, found, fallback, problems = prompt, None, None, []
        for attempt in range(1, PLAN_MAX_CALLS + 1):
            if self.expired():
                return (fallback, None) if fallback else (None, "timeout")
            print("plan: call %d of %d" % (attempt, PLAN_MAX_CALLS))
            started = _now()
            status, answer = self.agent(text, plan_max_tokens(most_panels(ctx)),
                                        plan_timeout(most_panels(ctx)), image=ctx.seed_agent_image)
            self.record("plan", None, 0, attempt, None, status, started)
            _write_text(os.path.join(rdir, "plan_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            raw = extract_json(answer)
            if raw is None:
```
New:
```python
        text, found, fallback, problems = prompt, None, None, []
        # Plan token budget spec PB2-PB7: budget is this call's max_tokens; plan_cut_off is the
        # problem of the last call when its reply was cut off at its budget, else None.
        budget = plan_tokens(ctx, self.compatible)
        for attempt in range(1, PLAN_MAX_CALLS + 1):
            if self.expired():
                return (fallback, None) if fallback else (None, "timeout")
            print("plan: call %d of %d" % (attempt, PLAN_MAX_CALLS))
            started = _now()
            status, answer = self.agent(text, budget,
                                        plan_timeout(most_panels(ctx)), image=ctx.seed_agent_image)
            self.record("plan", None, 0, attempt, None, status, started)
            _write_text(os.path.join(rdir, "plan_reply_%d.txt" % attempt),
                        _reply_text(status, answer))
            raw = extract_json(answer)
            self.plan_cut_off = None
            if raw is None and status == "ok" and cut_off_json(answer):
                following = escalated_plan_tokens(budget)
                self.plan_cut_off = PLAN_CUT_OFF_PROBLEM % (
                    budget, attempt, " or --no-auto-lora" if ctx.auto_lora and self.compatible
                    else "")
                self.doc["calls"][-1]["cut_off_at_tokens"] = budget
                self.write_run()
                print(PLAN_CUT_OFF_NOTE % (attempt, budget)
                      + (PLAN_CUT_OFF_NEXT % (attempt + 1, following)
                         if attempt < PLAN_MAX_CALLS else ""))
                text, budget = prompt + PLAN_CUT_OFF_RETRY % (budget, following), following
                continue
            if raw is None:
```

- [ ] **Step 6: Edit `story_engine.py` (E4, `go`'s fatal list).** Old:
```python
        fatal = self.plan_fatal(found) if found else ["the reply is not one JSON object"]
```
New:
```python
        fatal = (self.plan_fatal(found) if found
                 else [self.plan_cut_off or "the reply is not one JSON object"])
```

- [ ] **Step 7: Edit `bin/ltx-movie` (E5, the dry run's budget).** Old:
```python
    argv = engine.agent_cmd(ctx, prompt, max_tokens=engine.plan_max_tokens(engine.most_panels(ctx)),
```
New:
```python
    argv = engine.agent_cmd(ctx, prompt, max_tokens=engine.plan_tokens(ctx, compatible),
```

- [ ] **Step 8: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pb-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/pb-baseline/pyc $py -m py_compile story_engine.py bin/ltx-movie tests/test_plan_budget.py && echo "$py compiled"; done
git diff --numstat -- story_engine.py bin/ltx-movie        # 77 4 story_engine.py ; 1 1 bin/ltx-movie
wc -l tests/test_plan_budget.py                            # 271
grep -c "^import re$" bin/ltx-movie                        # 0
python3 -B -m pytest -q -p no:cacheprovider tests/test_plan_budget.py tests/test_story_engine.py tests/test_soft_panel_count.py 2>&1 | tail -1
zsh $S/pb-baseline/gate-run.sh 1
git add story_engine.py bin/ltx-movie tests/test_plan_budget.py
git diff --cached --name-only    # exactly qwen-agent-workspace/bin/ltx-movie, qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_plan_budget.py
git commit -m "story_engine: a catalog plan gets 400 tokens per beat, and a plan reply cut off at its budget is named, recorded in run.json and retried with 1.5x the budget (plan-budget PB1-PB8)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`.
- The three-file pytest line is `1 failed, 166 passed, ... warnings in ...s`. The one failure is the baseline's `test_rst62_import_sets`.
- The gate prints the summary `3 failed, 2727 passed, 2 skipped` (P0 - 1 + 10) and the gate line `lost 1 (listed 1, unexpected 0); new tests 10, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.

### Task 2: the `test_mut26` re-baseline (a test-only commit; never amend)

The baseline chain moves from `755d4c4` (seeded-shots-context) to Task 1's commit, the last code commit. If a review fix (V2) adds another code commit, this task runs after that commit instead.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pb-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- story_engine.py); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only 755d4c45ad6c33ebf68716ad04d357f1391f79f1 $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected: a 40-hex `SHA`; `SHA is HEAD`; exactly two paths, `qwen-agent-workspace/bin/ltx-movie` and `qwen-agent-workspace/story_engine.py`. The 23 paths are written out in full because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Wherever the word SHA appears below, type the 40 characters of `SHA`.
  - Replace `then to 755d4c45ad6c33ebf68716ad04d357f1391f79f1 (seeded-shots-context).` with `then to 755d4c45ad6c33ebf68716ad04d357f1391f79f1 (seeded-shots-context), then to SHA (plan-budget).` This occurs once, at the end of the long comment line `:291`.
  - Replace `    BASELINE = "755d4c45ad6c33ebf68716ad04d357f1391f79f1"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pb-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                         # 1
grep -c "(seeded-shots-context), then to $SHA (plan-budget)\.$" tests/test_movie_ui_builder.py          # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/pb-baseline/gate-run.sh 2
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the plan-budget commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output:
- The summary `2 failed, 2728 passed, 2 skipped` (P0 + 10).
- The gate line `lost 0 (listed 0, unexpected 0); new tests 10, not passing 0; baseline failures still failing 2 of 2`.
- `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.
- `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/pb-baseline/task-2-pytest.txt` prints `1`.

### Verification (controller)

- **V1:** confirm PBK1 from Task 2's gate output, and PBK2 with:
  - `git diff --numstat 599b1c7 HEAD -- story_engine.py bin/ltx-movie tests/test_plan_budget.py tests/test_movie_ui_builder.py`: `1 1 bin/ltx-movie`, `77 4 story_engine.py`, `271 0 tests/test_plan_budget.py`, `2 2 tests/test_movie_ui_builder.py`.
  - `git diff --name-only 599b1c7 HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `4`.
  - `git diff 599b1c7 HEAD -- bin/qwen-agent lora_catalog.py character_lib.py tests/test_story_engine.py tests/test_soft_panel_count.py tests/story_engine_testutil.py | wc -l`: `0`.
- **V2:** an Opus design review (the `design-reviewer` agent) of the two commits against this spec, focused on PB3 (the scan), PB5 (the retry prompt and budget) and PB8 (nothing else changes). Each finding is fixed in a new commit. A fix that touches a pinned file is followed by another Task 2-style baseline commit, and V1 runs again.
- **V3:** live checks L1-L4 (Section 5). The user runs them on macstudio; the assistant never does.

### Replay result

The full suite ran on `$S/pb-replay`, an rsync copy of `WS` at `599b1c7` with Task 1 applied, with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors`. The result was `3 failed, 2714 passed, 8 skipped, 1 error`. Compared test by test with `$S/sc-baseline/task-3-pytest.txt` (the `599b1c7` tree in its git worktree, `2 failed, 2718 passed, 2 skipped`):
- **New tests.** All 10 test IDs of `tests/test_plan_budget.py` passed.
- **Failures.** The 2 baseline failures (`test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`) still fail, and no other story test changed.
- **Copy-layout artifacts.** Everything else that differs comes from the copy's layout, not from this change. 2714 = 2718 - 1 - 5 - 8 + 10:
  - 6 skips (`not a git checkout`): `test_mut26` and the 5 `d210c26` tests. In `$S/pb-wt` these run; `test_mut26` fails until Task 2.
  - 8 tests that read the sibling `../agent/qwen-agent-unsafe`, which a copy of `WS` alone lacks: the error of `tests/test_researcher_think_off.py` (7 tests) and the failure of `tests/test_qwen_agent_fleet.py::test_t30_researcher_constants_and_prompt`.
- **Layout rerun.** In `$S/pb-layout` (the same copy next to a symlinked `agent/`), those 8 tests plus `test_plan_budget.py`, `test_story_engine.py` and `test_soft_panel_count.py` gave `1 failed, 174 passed` (the 1 is `test_rst62_import_sets`).
- **Other checks.** `python3 -B tests/test_ltx_movie_offline.py` printed `OK 347/347`. Both Pythons compiled the three files.
- **Red step.** Before the edits, the new file gave `9 failed, 1 passed` on an untouched copy (`$S/pb-red`).
- **Mutations.** Each of the 11 mutations listed in Section 4 makes at least 1 of the 10 tests fail, on a copy of the replay (`$S/pb-mut`). The `ctx.auto_lora` mutation survived the first version of PBT2, so PBT2 now also calls `plan_tokens` and `build_plan_prompt` with `auto_lora=False` and an explicit compatible list.

**Found while writing and replaying the tests, and fixed in this plan:**
1. The suite's 15-beat fixture plan is only 3839 characters as compact JSON, far below the 4250 tokens that cut the real reply off. The real reply's size is therefore unknown here, and L1 measures it before anything else, because hidden reasoning tokens would change the remedy (F3).
2. `compatible_entries` already returns `[]` when auto LoRA is off, so `ctx.auto_lora` in `plan_tokens` only matters for a caller that passes its own list. PB2 keeps it anyway, to match `build_plan_prompt`'s own test, and PBT2 pins it.
