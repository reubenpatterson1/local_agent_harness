# Per-beat JSON: the plan prompt names the per_beat key of beat 1, a "string": "N": key is repaired, and a plan retry names the JSON parse error

Date: 2026-11-10

Status: design spec and implementation plan in one document.

**The user's report (confirmed from the pasted plan reply):** a shots-mode run with auto-lora and 15 panels fails Phase 1 with `Error: the story model did not return a usable plan after 2 call(s)` and the bullet `the reply is not one JSON object`. The reply is not cut off. Its `loras.per_beat` object has every key written as `"string": "1": [ {...} ],  "string": "2": [ ... ]`, which is not JSON. Python's `json.loads` stops at the second colon (`Expecting ',' delimiter`). An editor reports `end of file expected`.

**The cause:** the plan prompt describes per_beat only in words: `per_beat maps a beat index, written as a string, to a list of motion or physics picks for that beat only` (`LORA_PICK_PARAGRAPH`, `story_engine.py:539-546`). It names the type of the key instead of showing the key, and the model copied the word `string` into each key. `extract_json` returns `None`, the retry tells the model only `the reply is not one JSON object`, and the second reply has the same fault.

**This spec:**
- rewords the per_beat clause of `LORA_PICK_PARAGRAPH` so that it names the exact key of beat 1, `"1"`, in place of the words `written as a string` (PJ1);
- repairs exactly this malformation in `extract_json`, and only when the reply does not parse as it is (PJ2, PJ3);
- adds the JSON parser's message, line and column to the retry after a reply that is not one JSON object (PJ4, PJ5).

A reply that parses takes exactly the same path as today, byte for byte. Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

**Where.**
- Repository `/Users/reubenpatterson/local_agent_harness` is never touched by this plan.
- Worktree `$S/pj-wt`, branch `per-beat-json`, off `c58010e` (the plan-budget branch: `2b21e47` code, `c58010e` the `test_mut26` re-baseline). `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`.
- Every path is relative to `WS`, and every line number cites `c58010e`.
- At `c58010e`, every `PIPELINE_FILES` member is byte-identical to `2b21e47b935a44e708cbcde99b79c789947ff6e1`, the current `test_mut26` BASELINE (`tests/test_movie_ui_builder.py:293`). Between `2b21e47` and `c58010e` only `tests/test_movie_ui_builder.py` changes (`2 2`). Both facts were checked with `git diff`.

**IDs.** Requirements are **PJ1-PJ6**, tests **PJT1-PJT6**, KPIs **PJK1-PJK5**, live checks **L1-L4**. At `c58010e`, `git grep -nE "\bPJ[0-9]+\b|\bPJT[0-9]+\b|\bPJK[0-9]+\b"` finds nothing.

**Terms.**
- The **span** of a reply is what `extract_json` parses: the body of the first ``` fence when there is one, else the whole reply, cut from its first `{` to its last `}`.
- A **string key** is the malformation `"string"`, optional JSON whitespace, `:`, optional JSON whitespace, a run of ASCII digits either in double quotes or bare, optional JSON whitespace, `:`. Examples: `"string": "3":` and `"string": 3:`.

---

## 0. Scope

### 0.1 What happens today (verified at `c58010e`)

- **The prompt.** `build_plan_prompt` (`story_engine.py:1163`) puts `LORA_PICK_PARAGRAPH` in the `loras:` line of the plan prompt when auto LoRA is on and at least one catalog entry is compatible. Otherwise it puts `LORA_EMPTY_PARAGRAPH` there (`:1184-1192`, `:537-538`). The format reference plan (`PLAN_REFERENCE_PLAN`, `:2867-2906`) is shown only in chained mode, and its `per_beat` is `{}` (`:2905`). A shots plan therefore sees no per_beat JSON at all.
- **No braces in the prompt.** Outside the chained format reference, the plan prompt contains no `{` or `}` (robust story spec RS7, `docs/superpowers/specs/2026-10-17-robust-story-lora-catalog-design.md:408`). The reason is deploy gate X2, which fails a default dry run that prints a line with a brace (`scripts/deploy/build_pkg.py:1117-1136`).
- **`extract_json`** (`:314-336`) takes the span and returns `json.loads(span)` when that is a dict. Any exception gives `None`. Its callers are `plan_round` (`:4969`), `parse_panel_reply` (`:3254`), `parse_critic` (`:4406`) and `bin/seam-report:289`.
- **`plan_round`** (`:4948-5001`) checks a cut-off reply first (PR #17, `:4971-4982`): status `ok`, `extract_json` is `None` and `cut_off_json` is true. It then retries with `prompt + PLAN_CUT_OFF_RETRY % (budget, next budget)`. Any other reply that `extract_json` rejects gets the problem `the reply is not one JSON object` (`:4984`). The retry prompt is then `prompt + "\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n" + "- " + problem + "\nPrevious reply:\n" + answer[:20000] + "\n\nReply with the complete corrected JSON object only."` (`:4996-5000`).
- **`go`** (`:5197-5198`) prints `the reply is not one JSON object` (or the cut-off problem) when no plan call produced a parsable plan.
- **The rest of the per_beat path** expects string keys `"1"` to `"N"`: `normalize_plan` (`:1427-1431`), the L1 check (`:2646-2653`, `per_beat key %s is not a beat number from 1 to %d`) and critic patches (`:4626-4628`). None of them changes.

### 0.2 Grounding: the pins this change must respect (verified at `c58010e`)

- **RST1** (`tests/test_story_engine.py:63-67`) pins story_engine's top-level imports, and `re` is already one of them. This change adds no import.
- **`test_rst62_import_sets`** (`:2905-2925`) also asserts that story_engine's imports at any depth equal its top-level imports, so a function-level `import re` would break it. It fails in the baseline on another assertion, and it still fails the same way. The no-top-level-`import re` rule (L7j, `tests/test_ltx_movie_offline.py:433`) applies only to `bin/ltx-movie`, which this change does not touch.
- **RST8** (`tests/test_story_engine.py:223-240`) builds the plan prompt for every mode, cast, catalog state and seed, and asserts that it has no `{` or `}` outside `plan_reference(False)`. **RST47** (`:2643-2645`) asserts the same for every line of the real dry run. So the prompt cannot show a JSON object such as `{"1": [...]}`. A draft of this spec that did was replayed, and it failed both tests. The key sentence of PJ1 has no brace, and both tests pass unchanged.
- **RST7** (`:168-176`) pins `extract_json` on eight inputs. The refactor (PJ4) keeps all eight results.
- **RST10** (`:1588-1615`) pins the retry text for the reply `I think the story is about rain.` That reply has no `{`, so it has no span and keeps the bare problem (PJ5).
- **PBT7** (`tests/test_plan_budget.py:217-235`) pins the retry text for `{not json}` at `:224-226`. That reply has a span, so its problem line gains the parse error. This one assertion is updated (E5). The rest of PBT7, and PBT1-PBT6, PBT8 and PBT9, pass unchanged.
- **`tests/test_movie_ui_builder.py`.** `PIPELINE_FILES` (`:223-228`) includes `story_engine.py`. `test_mut26` (`:272-302`; the comment chain ends at `:291`, BASELINE is at `:293`) fails from the code commit until Task 2 moves BASELINE, exactly as `c58010e` did for plan-budget.
- **Merge commit only.** BASELINE will name Task 1's commit. A squash or rebase merge would orphan it, and `test_mut26` would then skip instead of guarding.

### 0.3 Deliverables

| # | File | Pinned | Task | Change |
|---|---|---|---|---|
| D1 | `story_engine.py` | **yes** | 1 | `PLAN_JSON_ERROR`; `_STRING_KEY_RE`, `repair_string_keys`, `_json_span`, `json_error`; `extract_json` on top of `_json_span` with the repair; the per_beat clause of `LORA_PICK_PARAGRAPH`; `plan_round`'s problem line (PJ1-PJ5) |
| D2 | `tests/test_per_beat_json.py` | no | 1 | new, PJT1-PJT6 (6 test IDs) |
| D3 | `tests/test_plan_budget.py` | no | 1 | PBT7's retry-text assertion only (E5) |
| D4 | `tests/test_movie_ui_builder.py` | no | 2 | only `test_mut26`'s BASELINE and comment chain |

Untouched: `bin/ltx-movie`, `bin/qwen-agent`, `bin/seam-report`, `character_dataset.py` (it has its own `extract_json`), every other bin, every other test, and the movie-ui.

### 0.4 Out of scope

- `go`'s final error text, stdout lines and `run.json` (Decision 6; follow-up F1).
- Saving the retry prompt to a file (follow-up F2).
- Other malformed keys, for example `"beat 1":`, `"integer": "1":` or unquoted keys. Only the reported string key is repaired (follow-up F3).
- The panel and critic retry prompts. Their callers get the repair through `extract_json`, but their retry text does not change (follow-up F4).
- `PLAN_REFERENCE_PLAN`, `LORA_EMPTY_PARAGRAPH` and every other prompt text.
- A JSON object example in the prompt. RS7, RST8, RST47 and deploy gate X2 forbid braces there (0.1, 0.2).
- Any model call, server, render or download in tests, and any agent access to macstudio.

### 0.5 Success criteria (KPIs)

| ID | Criterion | Verified by |
|---|---|---|
| PJK1 | The full suite has no failure beyond the baseline (`2 failed, 2728 passed, 2 skipped`, plan-budget Task 2). After Task 2 it is `2 failed, 2734 passed, 2 skipped`, with the gate line `lost 0 (listed 0, unexpected 0); new tests 6, not passing 0; baseline failures still failing 2 of 2` and `GATE PASS` | gate, V1 |
| PJK2 | Between `c58010e` and the final commit, the only pinned file that changes is `story_engine.py` (numstat `67 18`). The only other non-docs files are `tests/test_per_beat_json.py` (new, `229 0`), `tests/test_plan_budget.py` (`4 3`) and `tests/test_movie_ui_builder.py` (`2 2`) | V1 |
| PJK3 | A reply whose span parses gives the same value as today, and `repair_string_keys` is never called for it. A reply with no span keeps today's retry text byte for byte. A cut-off reply keeps PR #17's retry byte for byte | PJT3, PJT5, PJT6, RST7, RST10, PBT4, PBT5 |
| PJK4 | On macstudio, the saved reply of the failed run parses with the new `extract_json` and gives per_beat keys `1` to `15` (or however many beats it has) | L1 |
| PJK5 | On macstudio, a rerun of the failed command gets past the plan, and no plan call is rejected as `not one JSON object` | L3 |

Every PJ requirement and every PJT test is a must-have. There are no nice-to-haves.

---

## 1. Decisions

1. **The prompt names the key of beat 1, in words, with no braces [spec choice].**
   - The clause `per_beat maps a beat index, written as a string, to a list of motion or physics picks for that beat only;` becomes `per_beat maps each beat number to a list of motion or physics picks for that beat only, and each key is the beat number alone in double quotes: the key of beat 1 is "1";`.
   - The words `written as a string` go, because the model turned them into the key.
   - **Why not a JSON example such as `{"1": [{"id": "<catalog id>", "strength": 0.8}]}`.** The plan prompt must have no `{` or `}` outside the chained reference: RS7, deploy gate X2, RST8 and RST47 (0.1, 0.2). Allowing the example would mean widening two pinned tests, and it would add a brace line to every dry run with a compatible catalog, in every mode. The fault was one key, so the sentence shows that one key exactly: `"1"`, the beat number alone in double quotes. JSON's own syntax does the rest; the other keys of the plan are already written correctly in the reported reply.
   - **Why beat 1.** Beat 1 exists in every plan (`--panels` is at least 1, `bin/ltx-movie:4096`), so a literal copy never makes an invalid key, and it shows that beats count from 1.
   - The sentence does not mention the word `string`, so as not to put it in front of the model again.
   - Everything else in the paragraph, `LORA_EMPTY_PARAGRAPH` and every other prompt string stays byte-identical. A no-catalog prompt asks for an empty per_beat object, so it gets no key sentence.
2. **The repair lives in `extract_json`, so every caller gets it [spec choice].**
   - `parse_panel_reply`, `parse_critic` and `bin/seam-report` get the repair too. Their replies have no numeric keys, and a reply that parses is never repaired, so their behaviour changes only for a reply that would otherwise be rejected.
   - A plan-only repair would need a second parse entry point for one caller. That is more code with no gain.
3. **Try first, then repair once [spec choice].** `extract_json` parses the span as it is. Only when `json.loads` raises `ValueError` does it parse `repair_string_keys(span)` instead, once. A span that parses is never passed to the repair, so every reply that works today gives the same value. A repaired span that still does not parse gives `None`, as today.
4. **A regular expression, not a string-aware scanner [spec choice].**
   - The pattern is `"string"[ \t\r\n]*:[ \t\r\n]*(?:"([0-9]+)"|([0-9]+))[ \t\r\n]*:`, replaced with `"\1\2":`. Python 3.5 and later replace a group that did not match with an empty string, so the replacement is the digits in double quotes either way.
   - **It never matches valid JSON.** In valid JSON a value is followed by `,`, `}` or `]`, never by `:`. The pattern ends in `: <number> :`, so the `"1"` or `1` before its last colon would be a value followed by a colon.
   - **The quotes must balance.** With an optional quote on each side instead (`"?([0-9]+)"?`), the valid pair `"string": "12:30"` would match as `"string": "12:` and be rewritten whenever the reply also failed to parse elsewhere. The two alternatives rule that out. PJT2 pins it.
   - **It never matches the text of a well-formed JSON string.** Inside such a string every `"` is escaped as `\"`. The text `"string": "1":` therefore appears as `\"string\": \"1\":`, and there a backslash comes right after `string`, where the pattern needs `"`. A raw `"` can only follow `string` where a string token closes. If that token began inside a string, the reply was malformed already.
   - A scanner that tracks strings (like `cut_off_json`) could give the same guarantee, but it would be about 20 lines instead of 2. The regex is enough.
   - `re` is already a top-level import of story_engine (RST1). The pattern is compiled once at module level as `_STRING_KEY_RE`.
5. **The retry names the parser's complaint [spec choice].**
   - When `extract_json` rejects a reply that has a span, the problem line is `the reply is not one JSON object` followed by ` (the JSON parser stopped at line L, column C of the previous reply: MESSAGE)`. MESSAGE is `json.JSONDecodeError.msg`, for example `Expecting ',' delimiter`.
   - L and C count from 1, in the whole reply. That is the text the retry prompt shows under `Previous reply:`, so they also count in that block, fence and preamble included. They are not counted in the span alone.
   - The error is the one in the span as the model wrote it, not in the repaired span. That is the position the model can see.
   - A reply with no span (no `{`, or no `}` after it, or no answer) keeps the bare problem, byte for byte.
   - **How this combines with PR #17's cut-off retry.** The cut-off check runs first and is unchanged. A cut-off reply gets `PLAN_CUT_OFF_RETRY` with no parse error, because a cut-off reply's parse error only says that the text ended, which the cut-off message already says. Every other rejected reply gets the REJECTED text with the parse error. The two never combine in one prompt.
6. **No new messages and no `run.json` change [spec choice].**
   - A repaired reply is accepted silently. Its raw text stays in `plan_reply_N.txt`, so `grep '"string": "'` shows when the repair fired (L3).
   - `go`'s final bullet stays `the reply is not one JSON object`. Adding the parse error there would change the stderr that RST10, PBT7 and PBT8 pin, for a message the user cannot act on (follow-up F1).
7. **`json_error` never raises on model text.** `json.loads` raises `RecursionError` for a span nested more than about 1000 levels deep (for example a degenerate `[[[[...` reply). `extract_json` already returns `None` for it through its `except Exception`. `json_error` returns `None` for it, so the retry keeps the bare problem and `plan_round` does not crash.
8. **`extract_json` is split, without a change in behaviour.** `_json_span(text)` returns `(offset, span)` with the same fence and brace rules, and `extract_json` and `json_error` both use it. The offset is what lets `json_error` count lines in the whole reply.

---

## 2. Requirements

- **PJ1 (the prompt).** `LORA_PICK_PARAGRAPH` equals today's text with exactly one change: `per_beat maps a beat index, written as a string, to a list of motion or physics picks for that beat only;` is replaced by `per_beat maps each beat number to a list of motion or physics picks for that beat only, and each key is the beat number alone in double quotes: the key of beat 1 is "1";`. `LORA_EMPTY_PARAGRAPH` and every other prompt string are unchanged. No plan prompt contains `written as a string`, and the paragraph contains no `{` or `}`.
- **PJ2 (the repair).** `_STRING_KEY_RE = re.compile(r'"string"[ \t\r\n]*:[ \t\r\n]*(?:"([0-9]+)"|([0-9]+))[ \t\r\n]*:')`, and `repair_string_keys(span)` returns `_STRING_KEY_RE.sub(r'"\1\2":', span)`.
- **PJ3 (extract_json).** `extract_json(text)` returns `None` for `None` and for a text with no span. Otherwise it parses the span with `json.loads`. When that raises `ValueError`, it parses `repair_string_keys(span)` instead. Any exception from either step gives `None`, and a value that is not a dict gives `None`.
- **PJ4 (`_json_span` and `json_error`).**
  - `_json_span(text)` returns `(first, text[first:last + 1])`, where `first` and `last` are the first `{` and the last `}` in the body: `text[start:end]`, with `start` and `end` set by today's fence rule. It returns `None` when there is no `{`, or no `}` at or after it.
  - `json_error(text)` returns `None` when `text` is `None` or has no span. Otherwise it parses the span with `json.loads`.
    - On `json.JSONDecodeError` it returns `(line, column, msg)`, where `at = first + exc.pos`, `line = text.count("\n", 0, at) + 1` and `column = at - text.rfind("\n", 0, at)`.
    - On `RecursionError`, or when the span parses, it returns `None`.
- **PJ5 (the retry).**
  - In `plan_round`, a reply that is not cut off and that `extract_json` rejects gets the single problem `"the reply is not one JSON object" + (PLAN_JSON_ERROR % error if error else "")`, where `error = json_error(answer)`.
  - `PLAN_JSON_ERROR = " (the JSON parser stopped at line %d, column %d of the previous reply: %s)"`.
  - The cut-off branch, the REJECTED text around the problem and the retry budget do not change.
- **PJ6 (nothing else changes).** For a reply whose span parses, every printed line, prompt, file, `run.json` record, budget and exit code is today's. `go`'s fatal list, stdout, stderr and `run.json` never gain the parse error.

## 3. Messages (exact)

| Constant | Text (`%` arguments) | Where |
|---|---|---|
| `PLAN_JSON_ERROR` | ` (the JSON parser stopped at line %d, column %d of the previous reply: %s)` (line, column, `json` message) | appended to the problem `the reply is not one JSON object` in the plan retry prompt only |

The retry prompt after the reply `{not json}` ends with:
```
YOUR PREVIOUS REPLY WAS REJECTED. Problems:
- the reply is not one JSON object (the JSON parser stopped at line 1, column 2 of the previous reply: Expecting property name enclosed in double quotes)
Previous reply:
{not json}

Reply with the complete corrected JSON object only.
```

For the reported reply, if the repair had not applied, the problem line would be `- the reply is not one JSON object (the JSON parser stopped at line L, column C of the previous reply: Expecting ',' delimiter)`, with L the line of the first `"string": "1": [` and C the column of its second colon. With this fix the repair applies, the reply is accepted, and no retry is sent.

No stdout or stderr line and no `run.json` field is added or changed.

## 4. Tests (`tests/test_per_beat_json.py`, new; every test uses the fake bin/qwen-agent or no agent)

| Test | Pins |
|---|---|
| PJT1 `test_pjt1_the_lora_paragraph_names_the_per_beat_key` | PJ1: the whole `LORA_PICK_PARAGRAPH` word for word, with no brace; `LORA_EMPTY_PARAGRAPH` word for word. For chained, no_stills and shots, with a catalog, an empty catalog and `auto_lora=False`: the built plan prompt never contains `written as a string`, and contains the key sentence exactly when it does not contain the empty paragraph |
| PJT2 `test_pjt2_repair_string_keys` | PJ2: quoted and unquoted keys, whitespace and newlines; a string value holding `"string": "1":` (escaped), valid `"string"` pairs (`"1"`, `"12:30"`, `"7"`, `2`, `3`) are kept, also next to a string key that is repaired; valid JSON is returned unchanged |
| PJT3 `test_pjt3_extract_json_repairs_only_a_reply_that_does_not_parse` | PJ3: the reported 15-beat reply (fails `json.loads` with `Expecting ',' delimiter`) parses to the intended plan, also inside a fence, also with a title that quotes the malformation; another syntax error, and a non-numeric string key, still give `None`. With `repair_string_keys` replaced by a function that raises, every valid reply (plain and fenced) still parses to `json.loads`' value, and RST7's inputs keep their results |
| PJT4 `test_pjt4_the_reported_fifteen_beat_reply_is_used_on_the_first_call` | PJ1-PJ3 end to end: shots, 15 panels, one compatible catalog entry, the reported reply as the only plan reply. rc 0; one plan call; its prompt holds the key sentence; no `plan: call 2 of 2` and no cut-off line; `plan.json` per_beat keys `"1"`-`"15"` with the `fast-motion` pick; `plan_reply_1.txt` is the raw reply byte for byte |
| PJT5 `test_pjt5_the_retry_prompt_names_the_parse_error` | PJ4, PJ5: `json_error` positions in a fenced reply with a preamble (line 5, column 3, counted in the whole reply), `{not json}` and the reported reply. `None` for no text, no span, `[1, 2]`, a valid object, the reported reply without its string keys and a 100000-deep nesting. `PLAN_JSON_ERROR` word for word. The full retry prompt after the fenced reply, and after `nope` (bare problem, today's text) |
| PJT6 `test_pjt6_a_cut_off_reply_keeps_the_cut_off_retry` | PJ5: a cut-off reply that also has string keys gets exactly `prompt + PLAN_CUT_OFF_RETRY % (4096, 6144)`, with no `JSON parser` text |

**Mutation check** (replayed; see "Replay result"). Each of these mutations makes at least one test of `tests/test_per_beat_json.py` or `tests/test_plan_budget.py` fail:
- repairing before the first parse;
- dropping the repair;
- dropping the pattern's last colon;
- accepting only quoted digits;
- optional quotes that need not balance;
- counting the position in the span instead of the reply;
- a column off by one;
- dropping the `RecursionError` guard;
- dropping the parse error from the problem line;
- adding the parse error to the cut-off retry;
- keeping `written as a string`;
- dropping the key of beat 1 from the sentence.

## 5. Live checks on macstudio (the user runs these; the assistant never accesses macstudio)

Run these from the workspace root on macstudio after merging. `<cmd>` is the exact bin/ltx-movie command that failed (shots, auto-lora, 15 panels), `<id>` is its `--story-id`, and `R=generated/stories/<id>/story_rounds`.

- **L1 (the failed run's reply, before rerunning).** The failed run's rounds directory stays at `$R` until the next run moves it aside, so run this first.
  1. `grep -c '"string": "' $R/round_0/plan_reply_1.txt $R/round_0/plan_reply_2.txt` prints a count above 0 for each file.
  2. `python3 -c 'import json,sys; json.load(open(sys.argv[1]))' $R/round_0/plan_reply_1.txt` fails with `Expecting ',' delimiter`. This is today's failure.
  3. `python3 -c 'import story_engine as se,sys; p=se.extract_json(open(sys.argv[1]).read()); print(None if p is None else sorted(p["loras"]["per_beat"], key=int))' $R/round_0/plan_reply_1.txt` prints the beat keys, `['1', '2', ..., '15']` or the subset that got a pick, and not `None` (PJK4). Repeat for `plan_reply_2.txt`.
  4. If step 3 prints `None`, the reply has a second fault. `python3 -c 'import story_engine as se,sys; print(se.json_error(open(sys.argv[1]).read().replace("\"string\": ", "")))' $R/round_0/plan_reply_1.txt` prints its line, column and message with the string keys taken out. Report that output.
- **L2 (the dry run's prompt).**
  1. `<cmd> --dry-run --no-review | grep -q 'each key is the beat number alone in double quotes: the key of beat 1 is "1";' && echo NEW-WORDING` prints `NEW-WORDING`. If it prints nothing, the dry run found no compatible catalog entry (its prompt then holds the empty paragraph); check `bin/lora-catalog list` before going on.
  2. `<cmd> --dry-run --no-review | grep -q 'written as a string' || echo NO-OLD-WORDING` prints `NO-OLD-WORDING`.
- **L3 (the rerun).**
  1. Run `<cmd> --story-only`. This runs Phase 0 (when there is a seed image) and Phase 1, then stops. Run the full `<cmd>` afterwards.
  2. Expected: Phase 1 gets past the plan. You see `plan: call 1 of 2`, then panel lines (`panel 1/..: call 1`), and no `did not return a usable plan` (PJK5).
  3. Run `grep -c '"string": "' $R/round_0/plan_reply_*.txt` and record the counts. `0` means the new wording worked. Above `0` with a usable plan means the repair saved the reply.
  4. If `plan: call 2 of 2` appears, record `head -c 600 $R/round_0/plan_reply_1.txt` and report it.
- **L4 (only if L3 still fails).** Keep `$R/round_0/plan_reply_*.txt` and report the error lines and the L1 step 3 output for each reply. Do not rerun with other flags first.

## 6. Risks (rulings), follow-ups and open questions

**Risks.**
- **R1 (a silent repair).** A repaired reply is accepted with no message. Ruling: accepted. The raw reply stays in `plan_reply_N.txt` (L3 step 3), and the repaired keys are checked by L1 like any other.
- **R2 (a position the model cannot see).** The retry shows only the first 20000 characters of the previous reply, so a parse error past that point names a line the model does not see. Ruling: accepted. The message and the line number still tell the model what to fix, and the plan-budget spec puts the reported 15-panel reply at about 12000-17000 characters.
- **R3 (the key is copied).** A model may put picks on beat 1 because the sentence names it. Ruling: accepted. A pick on beat 1 is a valid plan, and the critic can move it (`per_beat` patches, `story_engine.py:4626-4628`).
- **R4 (other callers).** `parse_panel_reply`, `parse_critic` and `bin/seam-report` get the repair. Ruling: harmless, by Decision 4. Only a reply that would be rejected today can change.
- **R5 (a duplicate key).** Two string keys with the same number become one key, and `json.loads` keeps the last value. Ruling: accepted. This is what a reply with that duplicate written correctly gives today.
- **R6 (deploy gate X2).** X2 counts brace lines in a default dry run. The default mode is chained, and the chained format reference already prints brace lines in that dry run (RST47 exempts exactly those lines), so X2 looks unable to pass today (follow-up F6). This spec adds no brace, so it does not change X2's result.

**Follow-ups (not fixed here).**
- **F1.** Name the last parse error in `go`'s final bullet as well. This changes the stderr pinned by RST10, PBT7 and PBT8.
- **F2.** Save each retry prompt as `plan_prompt_N.txt`, so that a live check can read what the model was told.
- **F3.** If L3 shows other malformed keys (`"integer": "1":`, `"beat 1":`), widen the repair to the ones seen, with the same try-first rule.
- **F4.** Give the panel and critic retries the parse error too.
- **F5.** Show a short excerpt of the reply around the parse error in the retry, as well as the line and column.
- **F6.** Check deploy gate X2 against the chained format reference (R6). Found while writing this spec; not verified by running the gate, which needs the deploy machine.

**Open questions (none blocks implementation).**
- **Q1.** Should a repaired reply print a stdout note (for example `plan: reply 1 had 15 "string" keys; repaired`)? Not done here, to keep the output byte-identical (Decision 6).
- **Q2.** Should `PLAN_REFERENCE_PLAN` (chained only) show a filled per_beat, as JSON is allowed there? Not done, because it would change every chained prompt and the reference's P24 copy terms, and the key sentence covers every mode.

---

## Plan

**House rules** (every task):
- Work only in `$S/pj-wt`. Never touch `/Users/reubenpatterson/local_agent_harness` or `/Users/ailab1`.
- Never stash, reset, amend, push or open a PR. Never access macstudio (no ssh, no scp, no reading its files).
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool. Each Edit's Old text must occur exactly once in the file when the Edit is applied. If it does not, stop and report.
- `story_engine.py`, `tests/test_per_beat_json.py` and `tests/test_plan_budget.py` must compile on both `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- The PR is merged with a merge commit only (never squash or rebase), so the sha that Task 2 writes into BASELINE stays reachable.

**Replay.** Every step below was replayed in an rsync copy of the worktree at `c58010e`, without `.git` (`$S/pj-replay`, next to a symlinked `agent/`).
- A script extracted every block from this document and applied them in order to the copy. Each Old occurred exactly once.
- The result was byte-identical to the hand-built draft (`$S/pj-pre`).
- The results are in "Replay result" at the end.

### Before Task 1: the snapshot, the baseline and the gate files (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/pj-baseline; mkdir -p $D
cd $S/pj-wt/qwen-agent-workspace
git branch --show-current                                     # per-beat-json
git diff --stat c58010e HEAD -- . ':(exclude)docs' | tail -1  # no output (only this spec is committed)
git status --short                                            # no output
wc -l story_engine.py tests/test_plan_budget.py tests/test_movie_ui_builder.py   # 5567, 271, 302
ls -l $S/snapshot-pre-pj-c58010e.tgz || tar czf $S/snapshot-pre-pj-c58010e.tgz --exclude generated -C $S/pj-wt qwen-agent-workspace
df -g . | tail -1                                             # at least 5 GiB free
git -C $S/pb-wt rev-parse HEAD                                # c58010e80ff2db7049c63c6d8e5f6300d48dcac3
cp $S/pb-baseline/task-2-pytest.txt $D/baseline-pytest.txt
cp $S/pb-baseline/task-2-ok-lines.txt $D/baseline-ok-lines.txt
tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                     # record as P0
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
cat $D/baseline-ok-lines.txt
```

Expected:
- The baseline is the plan-budget Task 2 gate run (`$S/pb-baseline/task-2-pytest.txt`). It ran in `$S/pb-wt` on the tree that `c58010e` committed, and `c58010e` is the base of this branch. So no new baseline run is needed.
- The summary is `2 failed, 2728 passed, 2 skipped, ... warnings in ...` (so P0 is 2728).
- The only `FAILED` lines are `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`. There is no `ERROR` line, and `test_mut26` passes.
- `baseline-ok-lines.txt` holds `OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68` and `OK 205/205`.

For any other difference, stop and report.

Then write the gate files (scratch files, never staged), based on the plan-budget plan's:

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/pj-baseline
python3 - "$S/pb-baseline/gate.py" "$D/gate.py" <<'PYEOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
old = 'NEW_FILES = ("tests/test_plan_budget.py::",)'
assert s.count(old) == 1, old
s = s.replace(old, 'NEW_FILES = ("tests/test_per_beat_json.py::",)')
open(sys.argv[2], "w", encoding="utf-8").write(s)
PYEOF
sed -e 's#/pb-baseline#/pj-baseline#' -e 's#/pb-wt/#/pj-wt/#' $S/pb-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'TXTEOF'
# per-beat JSON plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged story_engine.py changes in Task 1; Task 2 moves BASELINE
1 2 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt46_post_spans_validation_cap_and_store flaky daemon start-up test; every gate block reruns it alone, where it must pass
TXTEOF
grep -c pj-baseline $D/gate-run.sh; grep -c /pj-wt/ $D/gate-run.sh; grep -c '"tests/test_per_beat_json.py::",' $D/gate.py; grep -c test_trt46 $D/gate-run.sh; grep -c pb- $D/gate-run.sh   # 1, 1, 1, 1, 0
```

**The gate** for task N is `zsh $S/pj-baseline/gate-run.sh N`. It is a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints `disk ok`, the pytest summary, the gate line, `GATE PASS`, `3 passed` for the flake rerun, and `ATK2 OK lines unchanged`. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids, with the output of `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the per_beat key sentence, the string-key repair and the parse error in `story_engine.py` (one commit)

**Files:** `story_engine.py` (pinned), `tests/test_per_beat_json.py` (new), `tests/test_plan_budget.py` (one assertion).

**Interfaces** (new or changed; everything else is unchanged):
- `story_engine.PLAN_JSON_ERROR` (Section 3).
- `story_engine._STRING_KEY_RE` and `story_engine.repair_string_keys(span) -> str` (PJ2).
- `story_engine._json_span(text) -> (int, str) or None` and `story_engine.json_error(text) -> (int, int, str) or None` (PJ4).
- `story_engine.extract_json(text)`: same signature and the same result for every span that parses (PJ3).
- `story_engine.LORA_PICK_PARAGRAPH`: the per_beat clause (PJ1).

- [ ] **Step 1: Write `tests/test_per_beat_json.py`** with the Write tool, exactly as below. The file ends with a single newline after the last line.

````python
"""Tests for the per_beat JSON fix (docs/superpowers/specs/2026-11-10-per-beat-json-design.md,
PJ1-PJ6: PJT1-PJT6): the plan prompt names the per_beat key of beat 1, extract_json repairs a
per_beat key written "string": "N": only when the reply does not parse, and the retry after a
reply that is not one JSON object names where the JSON parser stopped.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_per_beat_json.py

Every model call goes to the fake bin/qwen-agent of a temp workspace (story_engine_testutil
make_ws). No test reaches a model server, a daemon or the Anthropic API. Stdlib and pytest.
"""

import importlib.machinery
import json
import os
import re
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402

se = importlib.machinery.SourceFileLoader(
    "story_engine_for_per_beat_json", os.path.join(WS, "story_engine.py")).load_module()

PICK = {"id": "fast-motion", "strength": 0.8}
CLAUSE = ("per_beat maps each beat number to a list of motion or physics picks for that beat "
          "only, and each key is the beat number alone in double quotes: the key of beat 1 is "
          '"1";')
QUOTED = 'the old prompt made it write "string": "1": [ before every pick'


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _catalog(tmp_path):
    entry = seu.catalog_entry(seu.lora_file(str(tmp_path / "files"), "fast"), "fast-motion")
    return {"schema_version": 1, "entries": [entry]}


def _picked_plan(mode, n, **overrides):
    """seu.plan_json(mode, n) with one fast-motion pick on every beat."""
    loras = {"global": [], "per_beat": dict((str(k), [dict(PICK)]) for k in range(1, n + 1)),
             "stills": []}
    return seu.plan_json(mode, n, loras=loras, **overrides)


def _string_keyed(text):
    """text with every per_beat key "N": written "string": "N":, as in the reported reply."""
    head, tail = text.split('"per_beat": {', 1)
    body, rest = tail.split('"stills"', 1)
    return (head + '"per_beat": {' + re.sub(r'"([0-9]+)": \[', r'"string": "\1": [', body)
            + '"stills"' + rest)


def _reported(mode="shots", n=15):
    """The reported reply: an indented plan whose per_beat keys are all "string": "N":."""
    return _string_keyed(json.dumps(_picked_plan(mode, n), indent=2))


def _panel_script(mode, n):
    return dict((str(k), [seu.answer(seu.panel_json(mode, k))]) for k in range(1, n + 1))


def _run(ws, tmp_path, monkeypatch, plan, mode="chained", n=3, **ctx_kw):
    log = seu.script_agent(monkeypatch, tmp_path, plan=plan, panel=_panel_script(mode, n),
                           critic=[seu.answer(seu.critic_json())])
    ctx = seu.make_ctx(se, ws, mode=mode, panels=n, **ctx_kw)
    rc, _advisories = se.run(ctx)
    return rc, ctx, seu.agent_log(log)


def _rejected(problem, reply):
    return ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + problem
            + "\nPrevious reply:\n" + reply + "\n\nReply with the complete corrected JSON object "
            "only.")


# --- PJT1 (PJ1): the plan prompt names the per_beat key of beat 1 ------------------------------

def test_pjt1_the_lora_paragraph_names_the_per_beat_key(ws, tmp_path):
    old = ("per_beat maps a beat index, written as a string, to a list of motion or physics "
           "picks for that beat only;")
    assert se.LORA_PICK_PARAGRAPH == (
        "an object with the keys global, per_beat and stills. Each pick is an object with the "
        "keys id and strength, taken from the LoRA catalog below; strength must lie inside that "
        "entry's range. global is a list of picks applied to every panel: at most one style "
        "LoRA, plus motion or physics LoRAs that suit the whole movie. " + CLAUSE + " every beat "
        "may have at most one motion or physics LoRA in total, counting global. stills is a "
        "list of at most one stills LoRA.")
    assert old not in se.LORA_PICK_PARAGRAPH
    assert "{" not in se.LORA_PICK_PARAGRAPH and "}" not in se.LORA_PICK_PARAGRAPH
    assert se.LORA_EMPTY_PARAGRAPH == (
        "an object with the keys global, per_beat and stills, each empty: global and stills are "
        "empty lists and per_beat is an empty object.")
    catalog = _catalog(tmp_path)
    for mode in ("chained", "no_stills", "shots"):
        for kw, picks in ((dict(catalog=catalog), True), (dict(), False),
                          (dict(catalog=catalog, auto_lora=False), False)):
            ctx = seu.make_ctx(se, ws, mode=mode, panels=4, **kw)
            prompt = se.build_plan_prompt(ctx, se.compatible_entries(ctx), ctx.pinned)
            assert "written as a string" not in prompt, (mode, kw)
            assert (CLAUSE in prompt) == picks, (mode, kw)
            assert (se.LORA_EMPTY_PARAGRAPH in prompt) == (not picks), (mode, kw)


# --- PJT2 (PJ2): repair_string_keys rewrites only the malformed key ----------------------------

def test_pjt2_repair_string_keys():
    assert se.repair_string_keys('{"per_beat": {"string": "1": [], "string": 12: []}}') == (
        '{"per_beat": {"1": [], "12": []}}')
    assert se.repair_string_keys('{"string" :\n  "3"\t: [{"id": "a"}]}') == (
        '{"3": [{"id": "a"}]}')
    kept = ('{"title": "%s", "kind": {"string": "1"}, "string": 2, "per_beat": {"string": "4": '
            '[]}}' % QUOTED.replace('"', '\\"'))
    assert se.repair_string_keys(kept) == kept.replace('"string": "4":', '"4":')
    assert json.loads(se.repair_string_keys(kept)) == {
        "title": QUOTED, "kind": {"string": "1"}, "string": 2, "per_beat": {"4": []}}
    valid = json.dumps(_picked_plan("shots", 15, title=QUOTED), indent=2)
    assert se.repair_string_keys(valid) == valid
    for value in ({"string": "1", "lines": ["string", "2"]}, {"string": "12:30"},
                  {"string": "7", "a": 1}, {"string": 3}):
        assert se.repair_string_keys(json.dumps(value)) == json.dumps(value)
    assert se.repair_string_keys('{"string": "12:30", "per_beat": {"string": "1": []}}') == (
        '{"string": "12:30", "per_beat": {"1": []}}')


# --- PJT3 (PJ3, PJ6): extract_json repairs only a span that does not parse ---------------------

def test_pjt3_extract_json_repairs_only_a_reply_that_does_not_parse(monkeypatch):
    reported = _reported()
    assert reported.count('"string": "') == 15
    with pytest.raises(ValueError, match="Expecting ',' delimiter"):
        json.loads(reported)
    assert se.extract_json(reported) == _picked_plan("shots", 15)
    assert se.extract_json("```json\n" + reported + "\n```") == _picked_plan("shots", 15)
    quoted = _string_keyed(json.dumps(_picked_plan("shots", 15, title=QUOTED), indent=2))
    assert se.extract_json(quoted) == _picked_plan("shots", 15, title=QUOTED)
    assert se.extract_json('{"per_beat": {"string": "1": []} "stills": []}') is None
    assert se.extract_json('{"per_beat": {"string": "beat 1": []}}') is None

    def no_repair(span):
        raise AssertionError("repair_string_keys called for a reply that parses")

    monkeypatch.setattr(se, "repair_string_keys", no_repair)
    for value in (_picked_plan("shots", 15), _picked_plan("shots", 15, title=QUOTED),
                  {"string": "1"}, {"a": {"b": 2}}):
        text = json.dumps(value, indent=2)
        assert se.extract_json(text) == value == json.loads(text)
        assert se.extract_json("Sure!\n```json\n" + text + "\n```\nthanks") == value
    assert [se.extract_json(t) for t in ("[1, 2]", "{not json}", None, "no braces")] == [None] * 4
    assert se.extract_json("```{\"a\": 3}```") == {"a": 3}


# --- PJT4 (PJ1-PJ3, PJ6): the reported 15-beat reply is used by the first plan call ------------

def test_pjt4_the_reported_fifteen_beat_reply_is_used_on_the_first_call(ws, tmp_path,
                                                                       monkeypatch, capsys):
    reported = _reported()
    rc, ctx, log = _run(ws, tmp_path, monkeypatch, [{"answer": reported}], mode="shots", n=15,
                        catalog=_catalog(tmp_path))
    assert rc == 0
    assert [r["stage"] for r in log].count("plan") == 1
    assert CLAUSE in log[0]["argv"][-1]
    out = capsys.readouterr().out
    assert "plan: call 2 of 2" not in out and "was cut off" not in out
    with open(os.path.join(ctx.story_dir, "plan.json"), encoding="utf-8") as f:
        per_beat = json.load(f)["loras"]["per_beat"]
    assert sorted(per_beat, key=int) == [str(k) for k in range(1, 16)]
    assert all([p["id"] for p in picks] == ["fast-motion"] for picks in per_beat.values())
    with open(os.path.join(ctx.story_dir, "story_rounds", "round_0", "plan_reply_1.txt"),
              encoding="utf-8") as f:
        assert f.read() == reported


# --- PJT5 (PJ4, PJ5): the retry prompt names where the JSON parser stopped ---------------------

def test_pjt5_the_retry_prompt_names_the_parse_error(ws, tmp_path, monkeypatch):
    broken = ('Here is the plan:\n```json\n{\n  "title": "The Sealed Letter"\n  "logline": "x"\n}'
              '\n```')
    assert se.json_error(broken) == (5, 3, "Expecting ',' delimiter")
    assert se.json_error("{not json}") == (1, 2, "Expecting property name enclosed in double "
                                                 "quotes")
    reported = _reported()
    line, column, message = se.json_error(reported)
    assert message == "Expecting ',' delimiter"
    assert reported.splitlines()[line - 1] == '      "string": "1": ['
    assert column == len('      "string": "1"') + 1
    for text in (None, "", "nope", "[1, 2]", '{"a": 1}', reported.replace('"string": ', ""),
                 '{"a": ' + "[" * 100000 + "}"):
        assert se.json_error(text) is None, text[:20] if text else text
    assert se.PLAN_JSON_ERROR % (4, 3, "Expecting ',' delimiter") == (
        " (the JSON parser stopped at line 4, column 3 of the previous reply: Expecting ',' "
        "delimiter)")
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": broken}, seu.answer(seu.plan_json("chained", 3))])
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + _rejected(
        "the reply is not one JSON object (the JSON parser stopped at line 5, column 3 of the "
        "previous reply: Expecting ',' delimiter)", broken)
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": "nope"}, seu.answer(seu.plan_json("chained", 3))],
                        story_id="s2")
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + _rejected(
        "the reply is not one JSON object", "nope")


# --- PJT6 (PJ5): a cut-off reply keeps the cut-off retry, with no parse error ------------------

def test_pjt6_a_cut_off_reply_keeps_the_cut_off_retry(ws, tmp_path, monkeypatch):
    cut = _reported("chained", 3)[:-200]
    assert '"string": "1": [' in cut
    assert se.cut_off_json(cut) and se.extract_json(cut) is None
    rc, ctx, log = _run(ws, tmp_path, monkeypatch,
                        [{"answer": cut}, seu.answer(seu.plan_json("chained", 3))])
    assert rc == 0
    assert log[1]["argv"][-1] == log[0]["argv"][-1] + se.PLAN_CUT_OFF_RETRY % (4096, 6144)
    assert "JSON parser" not in log[1]["argv"][-1]
````

- [ ] **Step 2: Run the new tests; they must fail before the edits.**
```bash
cd /private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad/pj-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_per_beat_json.py 2>&1 | tail -1
```
Expected: `5 failed, 1 passed, ... warnings in ...s`. The one test that passes is PJT6, which pins PR #17's cut-off retry as it is today. PJT1 fails on the paragraph text, PJT2 and PJT5 with `AttributeError`s (no `repair_string_keys` or `json_error` yet), PJT3 on `None == {...}`, and PJT4 on `rc` (`1 == 0`: both plan calls are rejected, as in the report).

- [ ] **Step 3: Edit `story_engine.py` (E1, `PLAN_JSON_ERROR` after `PLAN_CUT_OFF_RETRY`).** Old:
```python
                      "indentation and no line breaks, so that it fits, and reply with the JSON "
                      "object only.")
```
New:
```python
                      "indentation and no line breaks, so that it fits, and reply with the JSON "
                      "object only.")
# Per-beat JSON spec PJ5 (docs/superpowers/specs/2026-11-10-per-beat-json-design.md): the retry
# after a reply that is not one JSON object says where the JSON parser stopped (json_error).
PLAN_JSON_ERROR = " (the JSON parser stopped at line %d, column %d of the previous reply: %s)"
```

- [ ] **Step 4: Edit `story_engine.py` (E2, `_STRING_KEY_RE`, `repair_string_keys`, `_json_span`, `extract_json` and `json_error`).** Old:
````python
def extract_json(text):
    """The JSON object in a model reply, or None (RS6): the body of the first ``` fence when
    there is one, then the span from the first { to the last }."""
    if text is None:
        return None
    try:
        if "```" in text:
            start = text.index("```") + 3
            newline = text.find("\n", start)
            if newline == -1:
                body = text[start:]
                if body.startswith("json"):
                    body = body[4:]
            else:
                body = text[newline + 1:]
            end = body.find("```")
            text = body if end == -1 else body[:end]
        first, last = text.find("{"), text.rfind("}")
        if first == -1 or last < first:
            return None
        value = json.loads(text[first:last + 1])
    except Exception:
        return None
    return value if isinstance(value, dict) else None
````
New:
````python
# Per-beat JSON spec PJ2: a key written "string": "N": (or "string": N:), which a model copied
# from the old per_beat wording. It never matches valid JSON or the text of a JSON string.
_STRING_KEY_RE = re.compile(r'"string"[ \t\r\n]*:[ \t\r\n]*(?:"([0-9]+)"|([0-9]+))[ \t\r\n]*:')


def repair_string_keys(span):
    """span with every "string": "N": key rewritten as "N": (per-beat JSON spec PJ2)."""
    return _STRING_KEY_RE.sub(r'"\1\2":', span)


def _json_span(text):
    """(offset, span) of the JSON object in a model reply, or None (RS6): span runs from the
    first { to the last } of the body of the first ``` fence when there is one, else of the
    whole text, and offset is where span starts in text (per-beat JSON spec PJ4)."""
    start, end = 0, len(text)
    if "```" in text:
        start = text.index("```") + 3
        newline = text.find("\n", start)
        if newline == -1:
            if text.startswith("json", start):
                start += 4
        else:
            start = newline + 1
        fence = text.find("```", start)
        if fence != -1:
            end = fence
    first, last = text.find("{", start, end), text.rfind("}", start, end)
    if first == -1 or last < first:
        return None
    return first, text[first:last + 1]


def extract_json(text):
    """The JSON object in a model reply, or None (RS6): the body of the first ``` fence when
    there is one, then the span from the first { to the last }. Per-beat JSON spec PJ3: only a
    span that json.loads rejects is parsed once more, after repair_string_keys."""
    if text is None:
        return None
    try:
        found = _json_span(text)
        if found is None:
            return None
        try:
            value = json.loads(found[1])
        except ValueError:
            value = json.loads(repair_string_keys(found[1]))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def json_error(text):
    """(line, column, message) of json.loads' complaint about the span of a reply, with line
    and column counted from 1 in text itself; None when text is None or has no span, when the
    span parses and when it nests too deeply for json (per-beat JSON spec PJ4)."""
    found = None if text is None else _json_span(text)
    if found is None:
        return None
    try:
        json.loads(found[1])
    except json.JSONDecodeError as exc:
        at = found[0] + exc.pos
        return text.count("\n", 0, at) + 1, at - text.rfind("\n", 0, at), exc.msg
    except RecursionError:
        return None
    return None
````

- [ ] **Step 5: Edit `story_engine.py` (E3, the per_beat clause of `LORA_PICK_PARAGRAPH`).** Old:
```python
    "motion or physics LoRAs that suit the whole movie. per_beat maps a beat index, written as a "
    "string, to a list of motion or physics picks for that beat only; every beat may have at "
```
New:
```python
    "motion or physics LoRAs that suit the whole movie. per_beat maps each beat number to a list "
    "of motion or physics picks for that beat only, and each key is the beat number alone in "
    'double quotes: the key of beat 1 is "1"; every beat may have at '
```

- [ ] **Step 6: Edit `story_engine.py` (E4, `plan_round`'s problem line).** Old:
```python
            if raw is None:
                problems = ["the reply is not one JSON object"]
```
New:
```python
            if raw is None:
                # Per-beat JSON spec PJ5: name the parser's complaint when the reply has a span.
                error = json_error(answer)
                problems = ["the reply is not one JSON object"
                            + (PLAN_JSON_ERROR % error if error else "")]
```

- [ ] **Step 7: Edit `tests/test_plan_budget.py` (E5, PBT7's retry text).** Old:
```python
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object\n"
            "Previous reply:\n{not json}\n\nReply with the complete corrected JSON object only."
            ) in log[1]["argv"][-1]
```
New:
```python
    assert ("\n\nYOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- the reply is not one JSON object"
            " (the JSON parser stopped at line 1, column 2 of the previous reply: Expecting "
            "property name enclosed in double quotes)\nPrevious reply:\n{not json}\n\nReply "
            "with the complete corrected JSON object only.") in log[1]["argv"][-1]
```

- [ ] **Step 8: Verify, gate and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pj-wt/qwen-agent-workspace
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do PYTHONPYCACHEPREFIX=$S/pj-baseline/pyc $py -m py_compile story_engine.py tests/test_per_beat_json.py tests/test_plan_budget.py && echo "$py compiled"; done
git diff --numstat -- story_engine.py tests/test_plan_budget.py   # 67 18 story_engine.py ; 4 3 tests/test_plan_budget.py
wc -l tests/test_per_beat_json.py                                 # 229
grep -c "written as a string" story_engine.py                     # 0
python3 -B -m pytest -q -p no:cacheprovider tests/test_per_beat_json.py tests/test_plan_budget.py tests/test_story_engine.py 2>&1 | tail -1
zsh $S/pj-baseline/gate-run.sh 1
git add story_engine.py tests/test_per_beat_json.py tests/test_plan_budget.py
git diff --cached --name-only    # exactly qwen-agent-workspace/story_engine.py, qwen-agent-workspace/tests/test_per_beat_json.py, qwen-agent-workspace/tests/test_plan_budget.py
git commit -m 'story_engine: the plan prompt names the per_beat key of beat 1, extract_json repairs a "string": "N": key only when the reply does not parse, and a plan retry names the JSON parse error (per-beat-json PJ1-PJ6)' -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected:
- Both Pythons print `compiled`.
- The three-file pytest line is `1 failed, 116 passed, ... warnings in ...s`. The one failure is the baseline's `test_rst62_import_sets`.
- The gate prints the summary `3 failed, 2733 passed, 2 skipped` (P0 - 1 + 6) and the gate line `lost 1 (listed 1, unexpected 0); new tests 6, not passing 0; baseline failures still failing 2 of 2`, with `LOST tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged listed`, then `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.

### Task 2: the `test_mut26` re-baseline (a test-only commit; never amend)

The baseline chain moves from `2b21e47` (plan-budget) to Task 1's commit, the last code commit. If a review fix (V2) adds another code commit, this task runs after that commit instead.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pj-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- story_engine.py); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only 2b21e47b935a44e708cbcde99b79c789947ff6e1 $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected: a 40-hex `SHA`; `SHA is HEAD`; exactly one path, `qwen-agent-workspace/story_engine.py`. The 23 paths are written out in full because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Wherever the word SHA appears below, type the 40 characters of `SHA`.
  - Replace `then to 2b21e47b935a44e708cbcde99b79c789947ff6e1 (plan-budget).` with `then to 2b21e47b935a44e708cbcde99b79c789947ff6e1 (plan-budget), then to SHA (per-beat-json).` This occurs once, at the end of the long comment line `:291`.
  - Replace `    BASELINE = "2b21e47b935a44e708cbcde99b79c789947ff6e1"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/pj-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                    # 1
grep -c "(plan-budget), then to $SHA (per-beat-json)\.$" tests/test_movie_ui_builder.py             # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/pj-baseline/gate-run.sh 2
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the per-beat-json commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output:
- The summary `2 failed, 2734 passed, 2 skipped` (P0 + 6).
- The gate line `lost 0 (listed 0, unexpected 0); new tests 6, not passing 0; baseline failures still failing 2 of 2`.
- `GATE PASS`, `3 passed` and `ATK2 OK lines unchanged`.
- `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/pj-baseline/task-2-pytest.txt` prints `1`.

### Verification (controller)

- **V1:** confirm PJK1 from Task 2's gate output, and PJK2 with:
  - `git diff --numstat c58010e HEAD -- story_engine.py tests/test_per_beat_json.py tests/test_plan_budget.py tests/test_movie_ui_builder.py`: `67 18 story_engine.py`, `2 2 tests/test_movie_ui_builder.py`, `229 0 tests/test_per_beat_json.py`, `4 3 tests/test_plan_budget.py`.
  - `git diff --name-only c58010e HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `4`.
  - `git diff c58010e HEAD -- bin/ tests/test_story_engine.py tests/story_engine_testutil.py character_dataset.py lora_catalog.py | wc -l`: `0`.
- **V2:** an Opus design review (the `design-reviewer` agent) of the two commits against this spec, focused on PJ2-PJ3 (the repair runs only after a failed parse and never touches valid JSON or string text), PJ4 (the line and column count in the whole reply) and PJ6 (nothing else changes). Each finding is fixed in a new commit. A fix that touches a pinned file is followed by another Task 2-style baseline commit, and V1 runs again.
- **V3:** live checks L1-L4 (Section 5). The user runs them on macstudio; the assistant never does.

### Replay result

The full suite ran on `$S/pj-replay` (an rsync copy of `WS` at `c58010e` with Task 1 applied from this document, next to a symlinked `agent/`) with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider`. The result was `3 failed, 2727 passed, 8 skipped`. Compared test by test with `$S/pb-baseline/task-2-pytest.txt` (`2 failed, 2728 passed, 2 skipped`):
- **New tests.** All 6 tests of `tests/test_per_beat_json.py` passed. All 10 tests of `tests/test_plan_budget.py` passed, PBT7 with its E5 assertion.
- **Failures.** The 2 baseline failures (`test_d2_copied_literals_match_the_spike`, `test_rst62_import_sets`) still fail. The third failure was the flaky `test_tr27_fanout_two_rounds_and_missing_reasons`; rerun alone with `test_trt45` and `test_trt46`, it gave `3 passed`.
- **Copy-layout artifacts.** 6 tests skip in a copy (`not a git checkout`): `test_mut26` and the 5 `d210c26` tests. In `$S/pj-wt` these run; `test_mut26` fails until Task 2. So 2727 = 2728 - 6 - 1 + 6.
- **Other checks.** The five ATK2 OK lines were unchanged (`OK 347/347`, `OK 25/25`, `OK 57/57`, `OK 68/68`, `OK 205/205`). Both Pythons compiled the three files, and Python 3.9 gave the same `repair_string_keys`, `json_error` and `extract_json` results as 3.13 on the PJT2 and PJT5 inputs.
- **Red step.** Before the edits, the new file gave `5 failed, 1 passed` on an untouched copy (`$S/pj-red`).
- **Mutations.** Each of the 12 mutations listed in Section 4 made at least 1 test fail, on copies of the replay.
- **Live-check commands.** L1 steps 1-4 and L2 steps 1-2 were run against a simulated rounds directory and an isolated catalog (`$S/pj-tools/live-sim`, never the real HOME). They printed `15`, `Expecting ',' delimiter`, `['1', ..., '15']`, a `(line, column, message)` triple, `NEW-WORDING` and `NO-OLD-WORDING`, and the dry run created no story directory.

**Found while writing and replaying, and fixed in this plan:**
1. The first draft put a JSON object example in the prompt, as the request suggested. RST8 and RST47 failed on it, because RS7 and deploy gate X2 keep the plan prompt free of braces. PJ1 now names the key of beat 1 in words.
2. The first draft's pattern had an optional quote on each side of the digits. That also matched the valid pair `"string": "12:30"`. The pattern now takes the digits either in double quotes or bare, and PJT2 pins the case.
3. `json.loads` raises `RecursionError`, not `JSONDecodeError`, for a deeply nested span, and that would have crashed `plan_round` through `json_error`. `json_error` now returns `None` for it (Decision 7).
