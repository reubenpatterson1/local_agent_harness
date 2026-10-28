# Speaker attribution: a quoted line keeps the speaker the narrative names

Date: 2026-10-28

Status: design spec. Every design choice is made here. Each choice the brief left open is marked **[spec choice]**, and Section 7 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`, branch `qwen-agent-redteam`, HEAD `e254e65`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `e254e65`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.

Specs this one builds on, cited by tag:
- **[PCP]** `docs/superpowers/specs/2026-10-27-pinned-cast-presence-design.md`. It covers P16 (D1, PC1, PC2), `LINES_PINNED_SENTENCE` (PC6) and Amendment A1-A4.
- **[NF]** `docs/superpowers/specs/2026-10-26-narrative-dialogue-fidelity-design.md`. It covers QL2/QL3 (`classify_quotes`, `spoken_lines`), QL7 (`coerce_speakers`), QL8/QL8b (plan Q1, `assign_missing_lines`) and QL13 (`q1_dialogue_patch`).

---

## 0. Purpose and scope

### 0.1 Problem

**E1. Live run on this Mac, at `e254e65`.** The command was `bin/ltx-movie "$N" --panels 2 --shots --story-id pin-sh2 --character kyra --character ronin --speech-only --story-only --no-review --force-story`. `N` is `LINES_NARRATIVE` (`tests/test_pinned_cast.py:66-69`):

> At dusk Kyra climbs the stone steps of a mountain temple, and the ronin walks one step behind her. Near the top Kyra turns and says, "We reach the gate before dark." They pass under the gate together, and Kyra says, "Stay close to me."

- The run exited 0 with `hard []` after one plan call (`$S/pinned/measure.txt`).
- The planner's own reply, `generated/stories/pin-sh2/story_rounds/round_0/plan_reply_1.txt`, has beat 1 `cast ["c1"]`, `speaker "c1"`, `lines [1]` and beat 2 `cast ["c2"]`, `speaker "c2"`, `lines [2]`. So Kyra's second line went to the ronin.
- `story.md` panel 2 reads `Dialogue: the ronin: Stay close to me.`
- The 3-panel chained runs (`pin-ch3-a`, `pin-ch3-b`) and the 4-panel shots runs (`pin-sh4-a`, `pin-sh4-b`) gave both lines to the woman in grey.

**E2. Offline probes at `e254e65` (this Mac).** The probes ran against scratch copies of `WS` under `$S/p17/`, with a temporary HOME and character library. `$S/p17/base` is the unchanged code and `$S/p17/ws` is a scratch implementation of Section 2.
- **`assign_missing_lines` (the [PCP] A2 limit).** The narrative is `LINES_NARRATIVE` in a 3-beat shots plan whose beats are `[c1] speaker c1 lines [1]`, `[c2]` and `[c1]`. The function gives line 2 to beat 2, which makes the ronin the speaker. Its note is `beat 2: P14 speaking beat: line 2 given to this beat by the pipeline, because the plan gave it to no beat`.
- **`q1_dialogue_patch`.** On that same plan, a critic patch `"the ronin: Stay close to me."` on panel 2 returns `(True, None)`, which means it is applied.
- **Scan of every existing `generated/stories/*/plan.json` with quoted lines** (11 plans, 22 lines), using the Section 2 extractor:
  - 10 lines are attributed. Every one is a `pin-*` line, and each is given to `c1`.
  - The 12 `hockey-*` lines are unattributed. Their narrative says "He skates ... and says", which uses a pronoun.
  - There is exactly one mismatch: `pin-sh2`, line 2, expected `c1`, given to `c2`.

### 0.2 Causes (each verified at `e254e65`)

- **C1. The pin-sh2 prompt contains rules that conflict in this shape** (2 beats, 2 lines, 2 pinned members, shots):
  - `LINES_RULE` (`story_engine.py:371-377`) says "Give each line its own beat whenever there are at least as many beats as lines".
  - `SPEAKER_RULE` says a speaking beat shows only the speaker.
  - `CAST_FIXED_INTRO` and P16 require the ronin to be on screen.
  - The only plan that meets all three gives line 2 to the ronin, and the model chose it.
  - A correct plan exists. Lines 1 and 2 total 10 words, and the prompt's cap for shared lines is 13 words ("at most 13 words" in `plan_prompt.txt`). So beat 1 can be `c1` saying `[1, 2]` and beat 2 can be the ronin, silent. `LINES_PINNED_SENTENCE` hints at this, but nothing says whose lines they are.
- **C2. The pipeline never keeps the attribution.**
  - `classify_quotes` (`:482-509`) finds the speech verb but throws away its subject.
  - `spoken_lines` (`:531-534`) keeps only the display text.
  - The spoken-lines block (`:542-548`) lists the lines without speakers.
  - `coerce_speakers` (`:998-1083`) accepts any cast id as a beat's speaker.
  - `plan_checks` (`:1364-1545`) has no rule that ties a line to a speaker.
- **C3. Two downstream paths can create the defect even from a correct plan** (E2):
  - `assign_missing_lines` (`:1096-1140`) uses the first eligible beat, whoever its speaker is.
  - `q1_dialogue_patch` (`:2887-2951`) takes the speaker from the patch's phrase.

### 0.3 Grounding (verified at `e254e65`)

**`story_engine.py` (3796 lines, stdlib only)**
- Imports at `:11-23`; `re` is already imported.
- Quote parsing:
  - `QUOTE_RE` `:413`, `_LINE_WORD_RE` `:414`, `_CLAUSE_BREAK_RE = re.compile(r"[.!?;,]")` `:415`, `_QUOTE_EDGE_CHARS` `:416`, `SPEECH_VERBS` `:419`;
  - `line_words` `:447`; `classify_quotes` `:482`. It pairs curly quotes as straight ones and returns one `(inner, spoken)` per `QUOTE_RE` match of the normalised text, in order;
  - `spoken_lines` `:531`; `required_lines` `:537`.
- Plan prompt:
  - `LINES_PINNED_SENTENCE` `:380-382`; `LORA_EMPTY_PARAGRAPH` `:383`;
  - `build_plan_prompt` `:762`, with `seed = ""` at `:785` and the `@@LINES_RULE@@` fragment at `:803-805`;
  - the template line `"@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"` followed by `"loras: ..."` (`:315-316`).
- Plan normalisation and checks:
  - `assign_missing_lines` `:1096`. Its `cast_ids` line is `:1109` and its eligibility `continue` is `:1122-1124`;
  - `speaker_phrase_of` `:1253`;
  - `plan_checks` `:1364`, with its docstring at `:1365-1368`. The P16 block ends just before `undeclared = undeclared_characters(ctx)` `:1514`.
- `q1_dialogue_patch` `:2887`. Its "never changes who speaks" return is `:2917-2919`.
- `_Run.plan_round` `:3273-3313` retries on `plan_checks` hard, `lora_checks` hard or `line_assignment_problems`.
- `_Run.go`: the fatal ids are at `:3498` and `assign_missing_lines` is called at `:3510`.
- `make_state` `:3328` runs `plan_checks` every round.
- `recheck` `:3707` never calls `plan_checks`, `assign_missing_lines` or `apply_patches`.
- The only callers of the changed functions are `plan_checks` (`:3294`, `:3334`), `assign_missing_lines` (`:3510`) and `q1_dialogue_patch` (`:3014`, inside `apply_patches`). No `bin/` script or `movie_ui_lib.py` calls them.

**Tests at `e254e65`**
- `tests/test_pinned_cast.py`. Its helpers are `story_env`/`ws` `:42-49`, `KYRA`/`RONIN`/`CAST2`/`LINES_NARRATIVE` `:62-69`, `_members` `:74`, `_raw` `:81`, `_read_json` `:305`, `_fatal_err` `:310` and `_pt16_run` `:631-656`.
- `tests/story_engine_testutil.py`. `plan_json` (`:363`) gives an uncast plan with c1 "the courier" and c2 "the old monk".

**Measured on `$S/p17/ws`** (the scratch implementation of Section 2 exactly as written), running `test_story_engine`, `test_dialogue`, `test_narrative_fidelity`, `test_writer_pacing`, `test_shots_mode`, `test_casting_regression`, `test_casting_pipeline`, `test_iterate_story`, `test_pinned_cast`, `test_judge_story`, `test_ltx_story_manifest_chain`, `test_character_lib` and `test_movie_ui_builder`:
- No existing test changed outcome. `test_rst62_import_sets` failed both before and after, on `bin/ltx-mlx-render`; it is pre-existing.
- `python3 tests/test_ltx_movie_offline.py` printed `OK 347/347`.
- `story_engine.py` compiled under `/usr/bin/python3` (3.9) and `python3` (3.13).
- The SAT2, SAT4-SAT8 and SAT10 expected values in Section 4 were read off that implementation.
- `test_mut26` was skipped there because the copy has no `.git`. In the repo it needs the G5 re-baseline.

### 0.4 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | SA1-SA6 (Section 2) |
| G2 | `tests/test_speaker_attribution.py` (new) | SAT1-SAT10 (Section 4.1) |
| G3 | `tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt` (new) | A byte-exact copy of `generated/stories/pin-sh2/story_rounds/round_0/plan_reply_1.txt`: 1897 bytes, sha256 `4bd4d603998cca92c44c4d59295fb33318df3c486cf85b3c860d020b62da1374`. Copy it **before** any live rerun overwrites `pin-sh2` |
| G4 | `tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged` | `BASELINE` re-baseline in a **separate test-only follow-up commit**, as in [PCP] G5. The comment gains `, then to <sha> (speaker attribution).` |

**Not changed:**
- `character_lib.py`, `bin/*`, `movie_ui_lib.py` and `static/*`.
- `classify_quotes`, `spoken_lines`, `spoken_lines_block`, `coerce_speakers`, `speaking_coercion`, `line_assignment_problems`, `recheck`, the critic prompt, `PLAN_MAX_CALLS`, `plan.json` schema and every other check id.
- `LINES_RULE`, `LINES_PINNED_SENTENCE` and `SPEAKER_RULE` keep their exact text.
- No existing test is edited.

### 0.5 Out of scope

- **Pronoun attribution** ("she says"). It is never resolved (D1).
- Attribution by a name the narrative gives an *invented* character that the planner does not reuse as the phrase (for example "Jiro says" when c2 is "the young fisherman").
- Rewording `LINES_RULE` to resolve C1. The new sentence (SA6) and P17 cover it.
- Re-checking old stories for attribution (D6).
- Giving the attribution to the critic prompt, or to `bin/judge-story`.
- Lip-sync attribution in render.

### 0.6 Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SK1 | `python3 -m pytest tests/ -q -rA` from `WS` gives the pass count recorded just before implementation plus every SAT test, with no lost pass. The pre-existing failures are unchanged in number and message. `python3 tests/test_ltx_movie_offline.py` prints `OK n/n` with the baseline `n`. Both are measured after the G4 commit. | full run |
| SK2 | `/usr/bin/python3` (3.9) and `python3` (3.13) both `py_compile` `story_engine.py`. | `test_rst61` |
| SK3 | `story_engine.py` gains no import. | `git diff` |
| SK4 | **Extraction is 100% on the SAT2 table** (39 narratives): every expected id, and every `None` for pronoun, ambiguous, object or unattributed lines. `len(line_speakers(n, cast)) == len(spoken_lines(n))` for every row. | SAT2 |
| SK5 | **Rejection, 100% offline.** For chained, shots and no_stills × narration `True` and `"speech"`, a plan that gives an attributed line to another cast member yields exactly one P17 hard message per such line. The corrected plan, `narration=False`, and an unattributed (pronoun) narrative yield zero. The pin-sh2 reply fixture yields exactly `[P17 beat 2 line 2]` as the whole hard list. | SAT3, SAT4 |
| SK6 | **Retry, then fatal.** pin-sh2 reply then a corrected reply ends with rc 0 after exactly 2 plan calls, with the P17 message in call 2's prompt and `Dialogue: the woman in grey: We reach the gate before dark. Stay close to me.` Two pin-sh2 replies end with rc 1, the exact existing fatal stderr, and no `story.md` or `plan.json`. | SAT5, SAT6 |
| SK7 | **The pipeline never misattributes.** `assign_missing_lines` and `q1_dialogue_patch` never give an attributed line to a speaker other than the attributed one. Unattributed lines behave exactly as at `e254e65`. | SAT7, SAT8 |
| SK8 | **Planner contract.** With members and at least one member-attributed line, the plan prompt carries `LINE_SPEAKERS_SENTENCE` filled with the exact list. Otherwise it is byte-identical to `e254e65`; the uncast fixtures of [PCP] PT2 still match. | SAT9, `test_pt2` |
| SK9 | **Old stories are unchanged.** `recheck` of a story whose `plan.json` misattributes a line gives rc 0, calls neither `plan_checks` nor `line_speakers`, and writes no P17. That is identical to `e254e65`. | SAT10 |
| SK10 | **Live, this Mac, post-merge, not a merge gate (Section 5).** No rerun ends with exit 0 and a `Dialogue:` speaker that differs from the line's narrative speaker. The four previously correct runs still exit 0. | Section 5 |

### 0.7 Must-have and nice-to-have

SA1-SA6 and SAT1-SAT10 are must-haves. Nothing else is built: no CLI flag, no new advisory, no critic-prompt change and no deterministic plan repair.

---

## 1. Design decisions

### D1. Attribution is extracted deterministically and conservatively; a pronoun gives no constraint **[spec choice]**

`line_speakers(narrative, cast)` returns one entry per `spoken_lines(narrative)` line: a cast id, or `None`. `None` means no constraint. It reuses `classify_quotes`' quote pairing, so the two lists line up by construction: it zips the `QUOTE_RE` matches of the same normalised text with `classify_quotes(narrative)` and keeps exactly the entries `spoken_lines` keeps.

Two clauses are inspected for each spoken quote. Words are compared with `line_words`, which lowercases them, and an apostrophe inside a word is kept, so `kyra's` never matches `kyra`.
- **Lead clause L.** Take the text from the previous quote's end (or the narrative start) to this quote's opening. Strip the trailing `_QUOTE_EDGE_CHARS` and keep the last piece after splitting on `_CLAUSE_BREAK_RE` (`[.!?;,]`).
- **Trail clause T.** Take the text from this quote's closing to the next quote's opening. Strip the leading edge chars and keep the first piece after the same split. T is inspected **only** when the quote continues its sentence: either the quoted text does not end with `.`, `!`, `?` or `…`, or the first non-space character after the closing quote is `a`-`z`.

An **attribution verb** is a finite form in `ATTRIBUTION_VERBS`, or `calls`/`called` immediately before `out`. Bare and `-ing` forms ("say", "saying", "tell") are never attribution verbs, so "Kyra hears the monk say" attributes nothing. A **mention** is the word sequence of a cast entry's name (D2).

| Form | Where | Shape (words) | Example → speaker |
|---|---|---|---|
| B1 | L | `... M GAP V ...`, where V is L's **last** attribution verb, M ends 0-3 words before V, and GAP is: empty; or one word ending in `ly`; or 2-3 words ending in `and`/`then`, none of them in `GAP_BLOCK_WORDS`, a mention word or `SPEECH_VERBS` | `Near the top Kyra turns and says,` → kyra; `Kyra asks the ronin,` → kyra; `The ronin nods as Kyra says,` → kyra |
| B2 | L | L is exactly `V M`, or `and V M` / `then V M` (a quote split around its attribution) | `"Go," says Kyra, "now."` → kyra for both lines; `Then says Kyra:` → kyra |
| A1 | T | `V M ...` | `"Go," says the ronin.` → ronin |
| A2 | T | `M V ...` or `M <word ending in ly> V ...` | `"Go," the ronin says.` → ronin |

**B1 searches outward from V**, trying the M that ends 0, 1, 2, then 3 words before it. The first position whose GAP is allowed and where some mention ends decides. B1 gives `None` (and no other form is tried) when any of these holds:
- **X1.** Mentions of two different ids end there.
- **X2.** The word before M is in `OBJECT_WORDS` ("The monk beside Kyra says" → None).
- **X3.** The word before M is `and`, `or` or `nor`, and it is not L's first word ("The ronin and Kyra said" → None). `", and Kyra says"` stays valid, because its `and` is L's first word.
- **X4.** GAP ends in `and`/`then` and a different id is mentioned earlier in L ("The ronin hands Kyra rice and says" → None).

B2 is tried only when B1 found nothing.

**Result.** If both a B form and an A form match and they disagree, the result is `None` (`Kyra says, "Go," the ronin says.`). Otherwise it is whichever matched, or `None`. So a pronoun is never a mention, and a pronoun inside GAP blocks B1 ("Kyra turns to the ronin, and she says" → None).

**Why conservative.** A false attribution turns a correct plan into a retry or an exit 1. A missed attribution only leaves today's behaviour in place. Pronoun resolution would need gender or antecedent inference from descriptors, which is neither deterministic nor safe ("the woman in grey" and an invented woman can both be "she").

### D2. A narrative name maps to a cast entry by exact word sequence **[spec choice]**

- **Mentions.** Each cast entry contributes its `phrase`. A pinned member (`cast_name` set) also contributes its library name. Both are taken as `line_words`, so a hyphenated slug `old-monk` becomes `old monk`.
- **Invented cast** contributes its phrase only. "The old monk says" maps to c2 "the old monk". "The monk says" maps to nothing.
- **The check (SA2) and the pipeline guards (SA3, SA4)** use the normalised `plan["cast"]`, which covers pinned and invented entries after group entries are dropped.
- **The plan prompt (SA5)** uses `ctx.members` only (`{"id": "c<i>", "phrase", "cast_name"}`), because invented ids do not exist before the planner replies.
- **Ambiguity.** When one position matches mentions of two different ids, the line gets `None`.

### D3. P17 "line speaker" is a hard plan check, retried, and fatal when the retries run out **[spec choice]**

**Rule.** P17 runs after normalisation and coercion, on the plan `plan_checks` receives. For every beat k and every line n in its `lines`: if `line_speakers(...)[n-1]` is an id and differs from the beat's speaker, a hard `beat k: P17 line speaker: ...` message is reported. After `coerce_speakers`, a beat with lines always has a speaker.

**Why the plan, and why fatal (exit 1) like P16 and not exit 2:**
- `plan_round` already retries every `plan_checks` hard message, so this reuses the planner repair loop with no new code.
- The critic cannot fix it. `q1_dialogue_patch` refuses to change an existing speaker ("a spoken-line patch never changes who speaks", `:2918`), and a dialogue patch on a beat that has lines is rejected (`apply_patches`). So an exit-2 story-end failure would only burn the critic budget. Its "Hand-edit story.md" advice is also wrong, because the misattributed beat's Image and Motion show the other character.

**Rejected: deterministic repair (re-speaker the beat).**
- In shots, the coercion has already reduced the beat's cast to the wrong speaker. Re-speakering it would put c1 alone on screen and drop the ronin from every beat, so P16 fires (pin-sh2).
- It would also contradict a beat action written for the other character ("The ronin passes under the gate and says ...").
- [PCP] D1 already rules that beat composition is the planner's decision.

**Rejected: demote the line to unassigned (the Q1 path).** The beat keeps an action written around speaking, and the coercion has already removed its other cast. It also adds a new repair stage, against [PCP] D1's no-repair rule.

**Rejected: a plan-only problem list like `line_assignment_problems`.** When the retries run out it lets the defect through, which is the reported bug.

**Message** (exact): `beat %d: P17 line speaker: the narrative gives spoken line %d "%s" to %s %s, but this beat's speaker is %s %s; put line %d in the lines of a beat whose speaker is %s (consecutive lines may share a beat), and never give it to another character`. The fields are k, n, the display line, the attributed id, its quoted phrase, the beat speaker id, its quoted phrase, n, and the attributed id.
- `_VIOLATION_RE` parses it as id `P17`, name `line speaker`, scope `beat`, index k.
- The parenthesis names the remedy that C1 hides. In pin-sh2 that remedy is beat 1 saying `[1, 2]`.

### D4. The pipeline never introduces a misattribution (closes [PCP] A2; guards the [PCP] A3-type path) **[spec choice]**

- `assign_missing_lines` skips a candidate beat whose speaker, or whose sole cast member when it has no speaker, is not the line's attributed id. An attributed line with no eligible beat stays unassigned, which leads to the existing story-level Q1 and the critic.
- `q1_dialogue_patch` rejects a patch that would give an attributed line to another speaker. The reason is: `the narrative gives spoken line %d to %s, so a spoken-line patch never gives it to %s`.
- Unattributed lines (`None`) follow today's code paths exactly.
- Together with D3, this means P17 never fires on an accepted plan, so `make_state` reports no P17 in any round.

### D5. The planner is told the attribution, once, only when a member has attributed lines **[spec choice]**

**The sentence.** `LINE_SPEAKERS_SENTENCE` is filled with `line <n> to <id>` items in line order, joined `a`, `a and b`, `a, b and c`. It is appended to the `@@LINES_RULE@@` fragment: after `LINES_PINNED_SENTENCE` in shots and no_stills, and after `LINES_RULE` in chained. For pin-sh2 it reads `... The narrative gives these lines to already-cast characters: line 1 to c1 and line 2 to c1. ...`.

**Why a separate sentence, rather than annotating the numbered spoken-lines block:**
- `spoken_lines_block` is shared with the critic prompt ([NF] QL11), so annotating it would change the critic prompt.
- Uncast prompts would also change.

**When it appears.** It appears only with members and at least one line attributed to a member. So uncast prompts, and pinned prompts with no member-attributed line, are byte-identical to `e254e65`. Invented-cast attributions are enforced by P17 and its retry feedback only, because their ids do not exist before the reply.

### D6. Old stories re-check exactly as before **[spec choice]**

`recheck` never calls `plan_checks`, so P17 cannot appear there, and SA1 adds no call of its own. An old misattributed story (for example the existing `pin-sh2`) keeps its re-check result, rc 0. Fixing it takes `--force-story`, or movie-ui "Regenerate". This matches [PCP] C4.

### D7. Ids and names **[spec choice]**

- The new check is `P17`, named `line speaker`; P1-P16 are taken.
- The new constants are `ATTRIBUTION_VERBS`, `CALL_OUT_VERBS`, `GAP_BLOCK_WORDS`, `OBJECT_WORDS` and `LINE_SPEAKERS_SENTENCE`.
- The new functions are `line_speakers` (public) and the private helpers `_attribution_verb_at`, `_mentions`, `_mentions_at`, `_speaker_before` and `_speaker_after`.

---

## 2. Requirements (normative)

### SA1. The extractor (`story_engine.py`)

Insert this block immediately after `spoken_lines` (`:531-534`), before `def required_lines` (`:537`), separated by two blank lines on each side:

```python
# Speaker attribution spec SA1, D1, D2: who the narrative says speaks each spoken line.
ATTRIBUTION_VERBS = frozenset("""
    says said asks asked replies replied answers answered shouts shouted yells yelled
    screams screamed cries cried whispers whispered murmurs murmured mutters muttered
    exclaims exclaimed announces announced declares declared tells told""".split())
CALL_OUT_VERBS = frozenset(("calls", "called"))     # an attribution verb only before "out"
GAP_BLOCK_WORDS = frozenset("""
    the a an this that these those his her its their my our your he she they it him them we
    you i who whom which whose someone somebody everyone everybody nobody one as while when
    whenever before after until because since if though although whereas""".split())
OBJECT_WORDS = frozenset("""
    to at toward towards beside behind with of for from near by past around under over like
    than without into onto upon about besides""".split())


def _attribution_verb_at(words, p):
    """The number of words of the attribution verb at words[p] (1, or 2 for "calls out"), or 0."""
    if p >= len(words):
        return 0
    if words[p] in ATTRIBUTION_VERBS:
        return 1
    return 2 if words[p] in CALL_OUT_VERBS and words[p + 1:p + 2] == ["out"] else 0


def _mentions(cast):
    """[(cast id, words)]: every entry's phrase, and a library character's name (SA1, D2)."""
    out = []
    for entry in cast:
        for name in (entry.get("phrase"), entry.get("cast_name")):
            words = line_words(name) if isinstance(name, str) else []
            if words and entry["id"]:
                out.append((entry["id"], words))
    return out


def _mentions_at(words, mentions, end=None, start=None):
    """{cast id: words in its longest mention} for the mentions that end just before index end,
    or begin at index start, of words."""
    hits = {}
    for cid, tokens in mentions:
        n = len(tokens)
        if end is not None:
            span = words[end - n:end] if n <= end else None
        else:
            span = words[start:start + n]
        if span == tokens:
            hits[cid] = max(hits.get(cid, 0), n)
    return hits


def _speaker_before(words, mentions):
    """The cast id the clause before a quote names as its speaker, or None (SA1 forms B1, B2)."""
    verbs = [p for p in range(len(words)) if _attribution_verb_at(words, p)]
    if verbs:
        v = verbs[-1]
        tokens = set(w for _cid, t in mentions for w in t)
        for e in range(v, max(1, v - 3) - 1, -1):
            gap = words[e:v]
            joined = len(gap) in (2, 3) and gap[-1] in ("and", "then") and not any(
                w in GAP_BLOCK_WORDS or w in tokens or w in SPEECH_VERBS for w in gap)
            if gap and not joined and not (len(gap) == 1 and gap[0].endswith("ly")):
                continue
            hits = _mentions_at(words, mentions, end=e)
            if not hits:
                continue
            if len(hits) > 1:
                return None
            cid, width = next(iter(hits.items()))
            start = e - width
            before = words[start - 1] if start else None
            if before in OBJECT_WORDS or (before in ("and", "or", "nor") and start > 1):
                return None
            if joined and any(c != cid for c, t in mentions
                              for q in range(len(t), start + 1) if words[q - len(t):q] == t):
                return None
            return cid
    lead = 1 if words[:1] in (["and"], ["then"]) else 0
    width = _attribution_verb_at(words, lead)
    if width:
        hits = _mentions_at(words, mentions, start=lead + width)
        if len(hits) == 1 and lead + width + next(iter(hits.values())) == len(words):
            return next(iter(hits))
    return None


def _speaker_after(words, mentions):
    """The cast id the clause after a quote names as its speaker, or None (SA1 forms A1, A2)."""
    width = _attribution_verb_at(words, 0)
    if width:
        hits = _mentions_at(words, mentions, start=width)
        return next(iter(hits)) if len(hits) == 1 else None
    hits = _mentions_at(words, mentions, start=0)
    if len(hits) != 1:
        return None
    cid, n = next(iter(hits.items()))
    rest = words[n:]
    if _attribution_verb_at(rest, 0) or (rest[:1] and rest[0].endswith("ly")
                                         and _attribution_verb_at(rest, 1)):
        return cid
    return None


def line_speakers(narrative, cast):
    """One entry per line of spoken_lines(narrative), in order (speaker attribution spec SA1):
    the id of the cast entry (plan cast entries, or {"id", "phrase", "cast_name"} dicts) that the
    narrative names as the line's speaker, or None when it names none, or not unambiguously."""
    mentions = _mentions(cast)
    text = narrative.replace("“", '"').replace("”", '"')
    matches = list(QUOTE_RE.finditer(text))
    out = []
    for i, (match, (inner, spoken)) in enumerate(zip(matches, classify_quotes(narrative))):
        if not (spoken and line_words(inner)):
            continue
        if not mentions:
            out.append(None)
            continue
        prev_end = matches[i - 1].end() if i > 0 else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        lead = text[prev_end:match.start()].rstrip(_QUOTE_EDGE_CHARS)
        before = _speaker_before(line_words(_CLAUSE_BREAK_RE.split(lead)[-1]), mentions)
        after_text = text[match.end():next_start]
        after = None
        if (not match.group(1).rstrip().endswith((".", "!", "?", "…"))
                or re.match(r"\s*[a-z]", after_text)):
            after = _speaker_after(line_words(_CLAUSE_BREAK_RE.split(
                after_text.lstrip(_QUOTE_EDGE_CHARS))[0]), mentions)
        out.append(None if before and after and before != after else before or after)
    return out
```

The literal characters `“`, `”` and `…` are written as in `classify_quotes` (`:488`), where `story_engine.py` is UTF-8.

### SA2. P17 in `plan_checks` (`story_engine.py`)

Insert this block after the P16 block, immediately before `undeclared = undeclared_characters(ctx)` (`:1514`):

```python
    # Speaker attribution spec SA2, D3: a spoken line keeps the speaker the narrative names.
    if plan["spoken_lines"]:
        said_by = line_speakers(ctx.narrative, plan["cast"])
        for k, beat in enumerate(beats, start=1):
            for n in beat["lines"]:
                want = said_by[n - 1]
                if want and beat["speaker"] != want:
                    hard.append(
                        "beat %d: P17 line speaker: the narrative gives spoken line %d \"%s\" to "
                        "%s %s, but this beat's speaker is %s %s; put line %d in the lines of a "
                        "beat whose speaker is %s (consecutive lines may share a beat), and never "
                        "give it to another character"
                        % (k, n, plan["spoken_lines"][n - 1], want,
                           _q(speaker_phrase_of(plan, want)), beat["speaker"],
                           _q(speaker_phrase_of(plan, beat["speaker"])), n, want))
```

In the docstring (`:1365-1368`), "and P16 (a library character in no beat's cast; pinned cast presence spec PC1)" becomes "P16 (a library character in no beat's cast; pinned cast presence spec PC1) and P17 (a spoken line given to a speaker other than the one the narrative names; speaker attribution spec SA2)". Nothing else in `plan_checks` changes.

### SA3. P17 is fatal after the plan retries (`story_engine.py:3497-3498`)

`("P1", "P2", "P16")` becomes `("P1", "P2", "P16", "P17")`. The one-line comment above it (`:3497`) is replaced by these two lines (8-space indent):

```python
        # Pinned cast presence spec PC2, speaker attribution spec SA3: a plan that drops a library
        # character or gives a spoken line to the wrong speaker is not usable.
```

The error lines, `finish(1)` and the kept `story_rounds/round_0` are unchanged.

### SA4. `assign_missing_lines` honours the attribution (`story_engine.py`)

- Immediately after `cast_ids = [c["id"] for c in plan["cast"]]` (`:1109`, 4-space indent), add the line `said_by = line_speakers(ctx.narrative, plan["cast"])` at the same 4-space indent.
- Immediately after the eligibility `continue` (`:1122-1124`), add these two lines. The `if` takes the same 16-space indent as the preceding `if not (beat["speaker"]`, and the `continue` takes 20 spaces:

```python
                if said_by[n - 1] and (beat["speaker"] or beat["cast"][0]) != said_by[n - 1]:
                    continue
```

  The eligibility test just before it guarantees that `beat["cast"][0]` exists whenever `beat["speaker"]` is empty.
- Append this sentence to the docstring: "A line the narrative gives to a named speaker (speaker attribution spec SA4) goes only to a beat whose speaker, or sole cast member, is that speaker."

### SA5. `q1_dialogue_patch` honours the attribution (`story_engine.py`)

Immediately after the `return True, ("panel %d's speaker is %s; a spoken-line patch never changes who speaks" ...)` statement (`:2917-2919`), add:

```python
    said_by = line_speakers(ctx.narrative, plan["cast"])
    for n in range(i, j + 1):
        if said_by[n - 1] and said_by[n - 1] != sid:
            return True, ("the narrative gives spoken line %d to %s, so a spoken-line patch never "
                          "gives it to %s" % (n, _q(speaker_phrase_of(plan, said_by[n - 1])),
                                              _q(speaker_phrase_of(plan, sid))))
```

Append this sentence to the docstring: "A patch that gives a line to a speaker other than the one the narrative names is rejected (speaker attribution spec SA5)."

### SA6. The plan prompt sentence (`story_engine.py`)

Add this immediately after `LINES_PINNED_SENTENCE` (`:380-382`):

```python
# Speaker attribution spec SA6, D5: the lines the narrative gives to already-cast characters.
LINE_SPEAKERS_SENTENCE = (" The narrative gives these lines to already-cast characters: %s. The "
                          "beat that holds one of these lines has that character as its speaker, "
                          "and no other character says it.")
```

In `build_plan_prompt`, immediately before `seed = ""` (`:785`), add:

```python
    said = ""
    if lines and ctx.members:
        fixed = [{"id": "c%d" % i, "phrase": m.phrase, "cast_name": m.name}
                 for i, m in enumerate(ctx.members, start=1)]
        items = ["line %d to %s" % (n, cid) for n, cid
                 in enumerate(line_speakers(ctx.narrative, fixed), start=1) if cid]
        if items:
            said = LINE_SPEAKERS_SENTENCE % (items[0] if len(items) == 1 else
                                             ", ".join(items[:-1]) + " and " + items[-1])
```

The fragment at `:803-805` becomes:

```python
        ("@@LINES_RULE@@", (LINES_RULE + (LINES_PINNED_SENTENCE
                                          if ctx.members and ctx.mode != "chained" else "")
                         + said)
         if lines else ""),
```

`said` contains no `@@` token, so `_fill` leaves it as is. With `said == ""` the fragment is byte-identical to `e254e65`.

---

## 3. Interactions (normative)

| Area | Behaviour after this change |
|---|---|
| Plan retry (`plan_round`) | P17 is one more hard problem in the existing "YOUR PREVIOUS REPLY WAS REJECTED" list. `PLAN_MAX_CALLS` stays 2. |
| Fatal plan exit | P17, P16, P1 or P2 after the last call gives exit 1, the existing three-part stderr, no panel call, and no `story.md` or `plan.json` written. |
| P16 together with P17 | Both are listed, in plan-check order (P16 first). In shots, the P16 suffix and the P17 parenthesis together describe the shared-line remedy. |
| `assign_missing_lines` ([PCP] A2) | It never gives an attributed line to another speaker. Unattributed lines behave as before. A line it cannot place remains for story Q1 and the critic. |
| Critic and `apply_patches` ([PCP] A3) | A Q1 dialogue patch that would make another character say an attributed line is rejected with the SA5 reason. Every other patch is unchanged. |
| `make_state` (every round) | It runs `plan_checks`. P17 never fires on an accepted plan (D4). |
| `recheck` | Unchanged. It calls neither `plan_checks` nor `line_speakers`. |
| Uncast runs | Plan prompts are byte-identical. P17, SA4 and SA5 apply where the narrative names an invented character by the phrase the planner chose ("the old monk says"). |
| Pinned runs with no member-attributed line (for example pronouns) | Plan prompt byte-identical; no P17 from members. |
| `--no-narration` | `spoken_lines` is `[]` in the plan, so there is no sentence and no P17. |
| `--story-legacy`, `bin/*`, movie-ui, `plan.json` schema, `story_checks.json` shape | Unchanged. movie-ui shows a P17 exhaustion as a failed job with the stderr above. |

---

## 4. Tests

### 4.1 New: `tests/test_speaker_attribution.py`

**Conventions** (as `tests/test_pinned_cast.py`):
- stdlib plus pytest;
- `story_engine.py` and `character_lib.py` loaded by path with `importlib.machinery.SourceFileLoader`, under the names `story_engine_for_attribution` and `character_lib_for_attribution`;
- the autouse `story_env` and the `ws` fixtures;
- the module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon or the Anthropic API.

**Copied verbatim from `tests/test_pinned_cast.py`:** `KYRA`, `RONIN`, `CAST2` and `LINES_NARRATIVE` (`:62-69`), `_members` (`:74-78`), `_raw` (`:81-90`), `_read_json` (`:305-307`), `_fatal_err` (`:310-314`) and `_pt16_run` (`:631-656`). The `FIX` path is `tests/fixtures/speaker_attribution/pin_sh2_plan_reply_1.txt`.

**Extra helpers:**
- `CAST3 = [{"id": "c1", "phrase": KYRA, "cast_name": "kyra"}, {"id": "c2", "phrase": RONIN, "cast_name": "ronin"}, {"id": "c3", "phrase": "the old monk", "cast_name": None}]`.
- `PRONOUN_NARRATIVE = LINES_NARRATIVE.replace("Near the top Kyra turns", "Near the top she turns").replace("and Kyra says", "and she says")`.
- `MONK_NARRATIVE = 'The courier reaches the temple gate, and the old monk says, "Enter."'`.
- `P17(k, n, line, want, want_phrase, got, got_phrase)` builds the SA2 message.
- `SENTENCE(items) = se.LINE_SPEAKERS_SENTENCE % items`.
- `_shots2(ws, story_env, **kw)` is `seu.make_ctx(se, ws, mode="shots", panels=2, members=_members(story_env), narration="speech", narrative=LINES_NARRATIVE, **kw)`.

| ID | Covers (exact assertions) |
|---|---|
| SAT1 | **Constants.** `se.ATTRIBUTION_VERBS`, `se.CALL_OUT_VERBS`, `se.GAP_BLOCK_WORDS`, `se.OBJECT_WORDS` and `se.LINE_SPEAKERS_SENTENCE` equal the SA1 and SA6 literals, written out in the test. `se.LINE_SPEAKERS_SENTENCE.count("%s") == 1`, and `re.findall(r"@@[A-Z_]+@@", se.LINE_SPEAKERS_SENTENCE) == []`. `se.ATTRIBUTION_VERBS <= se.SPEECH_VERBS` |
| SAT2 | **Extraction table (SK4).** For each row, `se.line_speakers(text, CAST3) == want` and `len(want) == len(se.spoken_lines(text))`. Rows (text → want): `LINES_NARRATIVE` → `["c1","c1"]`; `PRONOUN_NARRATIVE` → `[None,None]`; `'Kyra says, "Go."'` → `["c1"]`; `'"Go," says the ronin.'` → `["c2"]`; `'“Go,” says the ronin.'` → `["c2"]`; `'"Go," the ronin says.'` → `["c2"]`; `'"Go," Kyra said quietly.'` → `["c1"]`; `'"Go!" yells Kyra.'` → `["c1"]`; `'"Go!" Kyra yells.'` → `[None]`; `'She says, "Go."'` → `[None]`; `'Kyra turns to the ronin, and she says, "Go."'` → `[None]`; `'The ronin nods as Kyra says, "Go."'` → `["c1"]`; `'Kyra nods as the ronin says, "Go."'` → `["c2"]`; `'The ronin watches Kyra and says, "Go."'` → `[None]`; `'Kyra asks the ronin, "Ready?"'` → `["c1"]`; `'The ronin and Kyra said, "Go."'` → `[None]`; `'The monk beside Kyra says, "Go."'` → `[None]`; `"Kyra's brother says, \"Go.\""` → `[None]`; `'The old monk says, "Go."'` → `["c3"]`; `'The monk says, "Go."'` → `[None]`; `'"Go," says Kyra, "now."'` → `["c1","c1"]`; `'Kyra says, "Go." The ronin says, "Fine."'` → `["c1","c2"]`; `'Kyra says, "Go," and the ronin replies, "Fine."'` → `["c1","c2"]`; `'Kyra calls out, "Wait!"'` → `["c1"]`; `'Kyra quietly says, "Wait."'` → `["c1"]`; `'Kyra smiles and then says, "Wait."'` → `["c1"]`; `'Kyra waits and Jiro says, "Wait."'` → `[None]`; `'Kyra whispers to the ronin, "Wait."'` → `["c1"]`; `'The crowd shouts, "Kyra!"'` → `[]`; `'A sign reads "Closed".'` → `[]`; `'"Go," Kyra says to the ronin, who answers, "Fine."'` → `["c1",None]`; `'Kyra says, "Go," the ronin says.'` → `[None]`; `'They pass under the gate together and Kyra says, "Stay close to me."'` → `[None]`; `'The woman in grey says, "Go."'` → `["c1"]`; `'Ronin says, "Go."'` → `["c2"]`; `'"Go," Kyra says, "now."'` → `["c1","c1"]`; `'The ronin hands Kyra rice and says, "Eat."'` → `[None]`; `'Then says Kyra: "Go."'` → `["c1"]`; `'Kyra says, "Go."'` with cast `[]` → `[None]` |
| SAT3 | **P17 matrix (SK5).** For `mode` in chained, shots and no_stills, and `narration` in `True` and `"speech"`: `ctx = make_ctx(mode, panels=3, members, narration, narrative=LINES_NARRATIVE)`.<br>• Chained bad: `_raw("chained", 3, [["c1","c2"]]*3)` with beat 2 `speaker="c1"`, `lines=[1]` and beat 3 `speaker="c2"`, `lines=[2]`.<br>• Shots and no_stills bad: `_raw(mode, 3, [["c1"],["c1"],["c2"]], ["c1","","c2"])` with beat 1 `lines=[1]` and beat 3 `lines=[2]`.<br>For every bad plan, `[m for m in plan_checks(...)[0] if " P17 " in m] == [P17(3, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]`, and `parse_violation` gives `("P17", "line speaker", "beat", 3)`.<br>• Corrected: beat 3 speaker `"c1"` (chained), or `_raw(mode, 3, [["c1"],["c2"],["c1"]], ["c1","","c1"])` with lines `[1]`, `[]`, `[2]` (other modes). It gives no P17.<br>• The same bad plans give no P17 with `narration=False`, or with `narrative=PRONOUN_NARRATIVE`.<br>• Uncast, all modes: `MONK_NARRATIVE` with `seu.plan_json(mode, 3)`, beat 1 `speaker="c1"`, `lines=[1]` gives exactly `[P17(1, 1, "Enter.", "c2", "the old monk", "c1", "the courier")]`. With beat 1 `cast=["c2"]`, `speaker="c2"`, it gives none |
| SAT4 | **pin-sh2 fixture (SK5).** `ctx = _shots2(...)`; `plan, shape = se.normalize_plan(ctx, se.extract_json(<FIX text>))`; `se.plan_checks(ctx, plan, shape)[0] == [P17(2, 2, "Stay close to me.", "c1", KYRA, "c2", RONIN)]`, with that exact one-item list. The file's sha256 equals the G3 value |
| SAT5 | **E2E exhausted (SK6).** `seu.script_agent(plan=[answer(FIX text)] * 2)`; `ctx = _shots2(..., story_id="sa1")`; `rc, _ = se.run(ctx)`. Then rc 1; the log stages are `["plan", "plan"]`; stderr `== _fatal_err([P17(2, 2, ...)], ctx)`; and `story.md` and `plan.json` are absent from `ctx.story_dir` |
| SAT6 | **E2E retry (SK6).** `bad = json.loads(FIX text)`; `good` is a deepcopy with beat 1 `lines=[1, 2]` and beat 2 `speaker=""`, `lines=[]`. Plan replies are `[answer(bad), answer(good)]`. Panel replies are `{"1": [answer(seu.panel_json("shots", 1, KYRA))], "2": [answer(seu.panel_json("shots", 2, RONIN))]}`, and `story_id="sa2"`. Assertions: rc 0; the stages are exactly `["plan", "plan", "panel", "panel"]`; `log[1]["argv"][-1]` contains `"YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P17(2, 2, ...) + "\n"`; the `plan.json` beats `(cast, speaker, lines)` are `[(["c1"], "c1", [1, 2]), (["c2"], "", [])]`; the story.md `Dialogue: ` lines are exactly `["Dialogue: the woman in grey: We reach the gate before dark. Stay close to me."]`; `story_checks.json` `hard == []`; and `round_0/plan_prompt.txt` contains `se.LINES_PINNED_SENTENCE + SENTENCE("line 1 to c1 and line 2 to c1") + "\nloras: "`. If round 0 is not clean with these replies, the implementer stops and reports the message: it is a spec error |
| SAT7 | **`assign_missing_lines` (SK7, closes [PCP] A2).** Shots, 3 panels, members, `"speech"`. `raw = _raw("shots", 3, [["c1"],["c2"],["c1"]], ["c1","",""])` with beat 1 `lines=[1]`. With `LINES_NARRATIVE`: the notes equal `["beat 3: P14 speaking beat: line 2 given to this beat by the pipeline, because the plan gave it to no beat"]`, the beats `(speaker, lines)` are `[("c1",[1]),("",[]),("c1",[2])]`, and `plan_checks` hard has no P17. With `PRONOUN_NARRATIVE` (the `e254e65` behaviour, unchanged): the beats are `[("c1",[1]),("c2",[2]),("",[])]`, and the first note is `"beat 2: P14 speaking beat: line 2 given to this beat by the pipeline, because the plan gave it to no beat"` |
| SAT8 | **`q1_dialogue_patch` (SK7).** On SAT7's normalised plan (before `assign_missing_lines`), with `parts = [se.empty_parts("shots", k, plan, ctx) for k in (1, 2, 3)]`. With `LINES_NARRATIVE`: panel 2 with `"the ronin: Stay close to me."` returns `(True, "the narrative gives spoken line 2 to 'the woman in grey', so a spoken-line patch never gives it to 'the ronin'")`, and beat 2 is unchanged (`speaker ""`, `lines []`). On a fresh copy, panel 3 with `"the woman in grey: Stay close to me."` returns `(True, None)`. With `PRONOUN_NARRATIVE`, panel 2 with the ronin patch returns `(True, None)` (unchanged) |
| SAT9 | **Plan prompt (SK8).** `cap = str(lib.dialogue_word_cap(se.engine_seconds(ctx), 2))`; `F = se.LINES_RULE.replace("@@LINE_WORDS@@", cap)`. With members:<br>• shots + `LINES_NARRATIVE`: contains `F + se.LINES_PINNED_SENTENCE + SENTENCE("line 1 to c1 and line 2 to c1") + "\nloras: "`.<br>• chained + `LINES_NARRATIVE`: contains `F + SENTENCE("line 1 to c1 and line 2 to c1") + "\nloras: "`.<br>• shots + `PRONOUN_NARRATIVE`: contains `F + se.LINES_PINNED_SENTENCE + "\nloras: "`.<br>• chained + `PRONOUN_NARRATIVE`: contains `F + "\nloras: "`.<br>• Neither pronoun prompt contains `"The narrative gives these lines"`.<br>• Chained + `'Kyra climbs the steps, and the ronin follows. She says, "Wait." The ronin says, "Go."'`: contains `SENTENCE("line 2 to c2")`.<br>• Chained + `'Kyra says, "Go." The ronin says, "Why?" Kyra says, "Now."'`: contains `SENTENCE("line 1 to c1, line 2 to c2 and line 3 to c1")`.<br>• Uncast + `LINES_NARRATIVE`, and uncast + `MONK_NARRATIVE`: the prompts do not contain `"The narrative gives these lines"`.<br>• `narration=False` + members + `LINES_NARRATIVE`: no sentence |
| SAT10 | **Back-compat re-check (SK9).** `rc, ctx, _ = _pt16_run(...)` gives `rc == 0`. Rewrite `plan.json` with beat 3 `speaker="c2"`. Monkeypatch `se.plan_checks` and `se.line_speakers` to raise `AssertionError`. Then `rc, _ = se.recheck(ctx, lambda path, panels, no_stills=False: [])` gives rc 0; `story_checks.json` `hard == []`; and no message contains `" P17 "` |

### 4.2 Existing tests that must pass unchanged

- `tests/test_pinned_cast.py`, all of it. PT2's uncast byte-identity fixtures, PT5's containment checks, PT14-PT18 and `test_final_i1`.
- `tests/test_narrative_fidelity.py`, all of it. This includes NF tests of `assign_missing_lines`, Q1 and `q1_dialogue_patch`, whose narratives attribute nothing to a cast phrase. That was verified on `$S/p17/ws`.
- `tests/test_dialogue.py`, `test_story_engine.py` (except the pre-existing `test_rst62`), `test_writer_pacing.py`, `test_shots_mode.py`, `test_casting_regression.py`, `test_casting_pipeline.py`, `test_iterate_story.py`, `test_judge_story.py`, `test_ltx_story_manifest_chain.py`, `test_character_lib.py` and `test_ltx_movie_offline.py`.
- `test_movie_ui_builder.py::test_mut26` fails after G1 until the G4 commit. That is the expected re-baseline, exactly as in [PCP].

---

## 5. Live checks (SK10; this Mac only, post-merge, not a merge gate)

These are run on this Mac only, never on macstudio or any remote host. They are story-only, with no render. The runner is whoever is authorized to start the local story server; the spec author did not run them.

**Setup.**
- `R=$S/attrib` (new, empty) and `W=$WS`.
- **Before any rerun, archive the current artifacts:** `mkdir -p $R/pre && cp -Rp $W/generated/stories/pin-* $R/pre/`. The `pin-sh2` artifacts are the only record of the defect and the source of G3.
- Start the story server exactly as `start_llm` in `$S/pinned/run.sh` (vllm-metal `qwen38-6bit`, port 8177). Stop it with `bin/story-server stop` after the last run.
- `N` is `LINES_NARRATIVE`.

**Runs.** From `$W`, the five `$S/pinned/run.sh` commands with the same story ids and flags (`pin-ch3-a`, `pin-ch3-b`, `pin-sh4-a`, `pin-sh4-b`, `pin-sh2`). Each log goes to `$R/run-<id>.log`. Then one extra `pin-sh2-b`, with the `pin-sh2` command and only the story id changed.

**Measure.**
- Run `W=$W python3 -I $S/pinned/measure.py pin-ch3-a pin-ch3-b pin-sh4-a pin-sh4-b pin-sh2 pin-sh2-b > $R/measure.txt`.
- Then run this attribution measure, saved as `$R/measure_sa.py`, with `W=$W python3 -I $R/measure_sa.py <same ids> > $R/measure_sa.txt`:

```python
import importlib.machinery, json, os, sys
W = os.environ["W"]
se = importlib.machinery.SourceFileLoader("se_live", os.path.join(W, "story_engine.py")).load_module()
for sid in sys.argv[1:]:
    d = os.path.join(W, "generated", "stories", sid)
    run = json.load(open(os.path.join(d, "story_rounds", "run.json")))
    if not os.path.exists(os.path.join(d, "plan.json")) or run.get("exit") != 0:
        print(sid, "exit", run.get("exit"), "plan calls", len([c for c in run["calls"] if c["stage"] == "plan"]))
        continue
    plan = json.load(open(os.path.join(d, "plan.json")))
    want = se.line_speakers(plan["narrative"], plan["cast"])
    got = dict((n, b["speaker"]) for b in plan["beats"] for n in b["lines"])
    print(sid, "exit 0", "want", want, "got", [got.get(n) for n in range(1, len(want) + 1)],
          "plan calls", len([c for c in run["calls"] if c["stage"] == "plan"]))
```

**Pass criteria (gating for the live report):**

| # | Criterion |
|---|---|
| a | For every run that exits 0, `measure_sa.txt` shows `got == want`, and every `speakers` entry in `measure.txt` is `the woman in grey`. |
| b | `pin-ch3-a`, `pin-ch3-b`, `pin-sh4-a` and `pin-sh4-b` exit 0, with `hard []`, and both members have non-empty `beats` and `panels` ([PCP] PK10 b). |
| c | `pin-sh2` exits 0, with both lines in one beat spoken by `c1` and the ronin in a beat with no speaker. |
| d | Any run that exits 1 prints the existing fatal stderr, whose listed problems are P16 or P17 only. |

If `pin-sh2` or `pin-sh2-b` exits 1, criterion c is a KPI miss to report to the user, not a contract failure (R1).

A run that exits 1 writes no `plan.json` or `story.md`. So for such a run, `measure.py` still reads the previous story's files. Those lines are stale and are ignored; `measure_sa.txt` shows the exit code instead.

**Recorded, not gating:**
- each run's plan-call count, plus `plan_reply_1.txt` and the retry prompt of any retried run;
- whether the `pin-ch3`/`pin-sh4` prompts contain `LINE_SPEAKERS_SENTENCE`. They should: `line 1 to c1 and line 2 to c1`;
- a diff of new against old `pin-sh2` `plan_prompt.txt` (old from `$R/pre/pin-sh2/story_rounds/round_0/`). The diff must be exactly the inserted `LINE_SPEAKERS_SENTENCE` after `LINES_PINNED_SENTENCE`.

Put the exit codes, `measure.txt` and `measure_sa.txt` in the report.

---

## 6. Rollout

1. Take a compressed snapshot of the workspace before any edit (house rule): `tar czf $S/snapshot-pre-speaker-attribution-e254e65.tgz` of `WS`, excluding `generated/`.
2. Copy the G3 fixture from `generated/stories/pin-sh2/...` and verify its sha256. Record the full-suite pass count and the pre-existing failure list.
3. Implement G1, G2 and G3 in one feature commit.
4. Run SK1-SK9.
5. Opus design review of the diff against this spec.
6. Make the test-only follow-up commit G4 (`test_mut26`), then measure SK1.
7. Post-merge: run the live checks (Section 5) and record the results.
8. Add an amendment line to [PCP]: "A2 closed by speaker attribution spec SA4 for lines the narrative attributes; unattributed lines unchanged." This is a doc edit in the same feature commit.

PR note (required, in substance): "Phase 1 now refuses a plan that gives a quoted line to a different character than the narrative names (P17; retried once, then exit 1). The pipeline's own line placement and the critic's line patches respect the same attribution. Pronoun attributions ("she says") are not enforced. Existing stories re-check exactly as before; regenerate one with `--force-story` (movie-ui: Regenerate)."

---

## 7. Values chosen by the spec

1. **Extraction.** Forms B1, B2, A1 and A2 only, with exclusions X1-X4 and the sentence-continuation rule for A forms. Pronouns, ambiguity and conflicts give `None` (D1).
2. **Mapping.** Matching is by exact `line_words` sequence of the phrase, plus the library name for pinned members. Invented cast matches by phrase only (D2).
3. **Check.** P17 `line speaker` is a hard plan check with beat scope, after P16, retried by the existing feedback, and fatal (exit 1) after 2 calls. There is no deterministic repair (D3).
4. **Pipeline guards.** `assign_missing_lines` and `q1_dialogue_patch` never misattribute (D4).
5. **Planner text.** One `LINE_SPEAKERS_SENTENCE`, only for member-attributed lines, appended to the `@@LINES_RULE@@` fragment (D5).
6. **Old stories** are not re-checked (D6).
7. **Uncast runs.** Prompts are unchanged. P17 applies to phrase-matched invented speakers (D2, Section 3).

---

## 8. Risks and questions

### 8.1 Risks

- **R1. pin-sh2-shaped runs may now exit 1.** With 2 beats, 2 lines and 2 pinned members in shots, the only valid plans put both lines in one beat. A model that keeps one line per beat fails twice, where it used to "succeed" with the wrong speaker. That is intended. Section 5 records it, and the remedy is `--panels 3` or more.
- **R2. A false attribution makes a correct plan retry or fail.** The SAT2 table pins the conservative behaviour. The residual false-positive shape is a non-cast subject acting on a named cast member with a bare noun and then speaking: "The monk hands Kyra rice and says, ..." → kyra. X4 catches it only when the subject is itself a cast mention.
- **R3. Uncast behaviour changes** where the narrative names a speaker by the exact phrase the planner reuses. That run can now retry or exit 1 where it used to succeed with a misattribution.
- **R4. Missed attributions** ("Kyra says" with no comma before the quote is fine, but "they pass ... together and Kyra says" without a comma is rejected by X3). Such lines keep today's behaviour.

### 8.2 Decisions to confirm (each resolved by the spec; flagged because each narrows or extends the brief)

- **C1.** P17 exhaustion is **fatal, exit 1**, like P16, rather than exit 2 or a deterministic repair (D3).
- **C2.** **Pronouns are never resolved** (D1).
- **C3.** **Invented cast is enforced by phrase in uncast runs too**: behaviour changes, prompt bytes do not (D2, R3).

### 8.3 Open

None.


## Amendment 2026-10-28 (Task 1 review)

- **SA1-A1.** Two compound-subject shapes give no constraint, per D1: form A1 returns no speaker when the word after the mention is "and", "or" or "nor" ('"Go," says Kyra and the ronin.'), and form B1 gives none when the clause before the quote starts with "and", "or" or "nor" and the comma piece before it ends with a cast mention ('Kyra, the old monk, and the ronin said, "Go."'). "They pass under the gate together, and Kyra says," still attributes to Kyra. Residual (R2): a list whose earlier member is not a cast mention ("Maya, a stranger, and the ronin said") still attributes to its last member.


## Amendment 2026-10-28 (final whole-branch review)

- **SA1-A2.** Form B1 gives no speaker (X5) when the word before the mention is in `NON_SPEAKER_LEAD_WORDS` (`a an another other second one every each some any no among amid amongst between against opposite across along alongside beyond inside outside within below above beneath underneath except unlike including through throughout via facing following`), and (X6) when a word of `RELATIVE_WORDS` (`who whom whose that which`) comes before the mention in the clause. Such a mention is an object, one of a group, or inside a relative clause, so it is not the speaker: 'A second ronin says', 'The man facing Kyra says' and 'The stranger who saved Kyra says' all give None. `OBJECT_WORDS` keeps its exact text. SAT2 gains the 12 rows of the final review's probes, each `[None]`; every earlier row, `LINES_NARRATIVE` (`["c1", "c1"]`) included, is unchanged. Residual (R4): a clause that opens with "that" as a determiner ('That night Kyra says') now gives no constraint.

- **SA1-A3.** The SA1-A1 compound rule for form B1 applies only when the comma piece before the clause is exactly one cast mention, as a whole piece. 'Kyra, the old monk, and the ronin said' and 'The old monk, Kyra, and the ronin said' still give None. A piece that only ends with a mention no longer blocks the clause after it: '"Go," said Kyra, and the ronin replied, "Fine."' gives c1, c2, and 'Kyra nods to the ronin, and the old monk says, "Go."' gives c3. SAT2 gains these 3 rows (57 rows in all). Form A1's "and"/"or"/"nor" rule is unchanged, so '"Go," says Kyra and turns away.' still gives None. Residual (R2): a list whose earlier piece is not exactly one mention ('Kyra and the old monk, and the ronin said') attributes to its last member.

- **SA5-A1.** The SA5 guard in `q1_dialogue_patch` runs after the patch's lines are widened to the lines the panel keeps (`i, j = min(want), max(want)`), not before. It now checks every line the patched panel would say, including a line its `Dialogue:` already holds as free dialogue. A patch that adds an unattributed line to a panel whose free `Dialogue:` already says another character's attributed line is rejected with the SA5 reason for that line; before, it was applied, the panel's speaker got the attributed line, and P17 fired on the next state. The reason text is unchanged. Only one rejection order changes: a patch that fails both the adjacency rule and the attribution now gets the adjacency reason.

- **Q1-A1.** Story-scope Q1 is speaker-aware while a story is generated. `spoken_line_problems(ctx, lib, phrases, dialogues, speakers=None)` takes, for each required line, the referring phrase of the speaker `line_speakers` names (`speaker_phrase_of` on the plan cast), or None; `panel_checks` passes it, so it applies in every round. A line with a phrase counts as present only in a panel whose `Dialogue:` speaker is that phrase. A line with None, and every line when `speakers` is None, keeps the any-speaker rule. A line found only under other speakers gives the new `Q1_SPEAKER` message, `story: Q1 spoken line: the narrative's spoken line %d "%s" is spoken by %s in panel %d's Dialogue:, but the narrative gives it to %s; give it word for word to a panel whose Dialogue: speaker is %s (Dialogue: %s: <the line>)`, filled with n, the line, the quoted phrase of the first panel that says it, that panel's number, the quoted attributed phrase twice, and the bare attributed phrase. A line said by its speaker but out of order stays `Q1_ORDER`, and a line said nowhere stays `Q1_MISSING`. This closes the free-dialogue path only when no panel also says the line under the speaker the narrative names (corrected by Q1-A2): a beat with a speaker but no lines, whose writer says another character's attributed line, ended exit 0 with `Dialogue: the ronin: Stay very close to me now.`. In that 2-panel run no other panel can say the line, so it now ends exit 2 with the hard `Q1_SPEAKER` (and, after Q1-A2, the panel 2 N18). When another panel says the line under its own speaker, for instance because the pipeline gives it to a later beat (SA4), Q1 is satisfied and the free line stayed; Q1-A2 closes that case. The critic's Q1 dialogue patch that keeps the ronin as speaker is rejected by the SA5 guard, and one that names the woman in grey on the ronin's panel is rejected by "never changes who speaks". `recheck` passes no speakers and calls no `line_speakers`, so old stories re-check exactly as before (D6, SK9, SAT10). Recorded consequence: a story that ended exit 2 on `Q1_SPEAKER` and is rerun without a hand edit re-checks under the any-speaker rule and exits 0.

- **Q1-A2.** A panel's free dialogue never says another speaker's attributed line. While a story is generated, `panel_checks` also calls `free_line_problems(ctx, lib, plan, dialogues, speakers)` with the `dialogues` and `speakers` it passes to `spoken_line_problems`. A panel is checked when its beat has a speaker and no lines (its `Dialogue:` is the writer's free dialogue) and its `Dialogue:` names a cast phrase. It says required line n when the `line_words` of one or more consecutive whole sentences of its line (split with `_sentences`) equal line n's `line_words`; a line inside a longer sentence does not count, so Kyra's "Go." is not said by 'Let us go.' or 'Go, now.', but is by 'Go.' and 'Wait. Go!'. That is a hard, blocking, panel-scope N18, `panel %d: N18 dialogue: Dialogue: has %s say the narrative's spoken line %d "%s", which the narrative gives to %s; do not have %s say it: write a different line for this panel` (`N18_LINE_SPEAKER`: the panel number, the quoted panel speaker's phrase, n, the line, the quoted attributed phrase, the quoted panel speaker's phrase), when line n is attributed to a phrase other than the panel's `Dialogue:` speaker and no required line with the same words is unattributed or given to that speaker. Unattributed lines, a line said by its own speaker, uncast narratives and panels whose beat has lines are never flagged. N18 is the existing hard check of a panel's `Dialogue:`, and the critic may already patch the dialogue of a [hard] N18 panel, so no prompt text changes; Q1 routing could not repair it, because a Q1 dialogue patch only adds spoken lines and never rewrites other Dialogue words. Repair: the critic's dialogue patch replaces the free line (a replacement that is a run of the narrative's spoken lines still goes through `q1_dialogue_patch` when a story Q1 is present, so the SA5 guard still applies); `REPAIR_IDS` becomes `("N11", "N18", "T1", "T2", "T3")` and `merge_repair` takes the writer's new dialogue for T1 or N18, so a code-only round re-asks the panel's writer with the message in its fix block (a structural N18 is re-asked too, but only with panel budget left, which a panel whose two writer calls failed does not have). `GENERATION_CHECKS`, `NON_BLOCKING_IDS` and `RECHECK_IDS` are unchanged. The re-review's 3-panel run (beats c1 [1], c2 [], c1 []; panel 2's writer says Kyra's line 2; the pipeline gives line 2 to beat 3), which ended exit 0 with `Dialogue: the ronin: Stay very close to me now.`, now has the one hard N18 on panel 2 in round 0: a critic patch giving panel 2 another line ends exit 0 without the ronin saying it, a code-only round does the same through the writer, and with no repair the run ends exit 2. The 2-panel run of Q1-A1 ends exit 2 with `Q1_SPEAKER` and the panel 2 N18. `recheck` does not call `free_line_problems` (speaker-blind, O1), so a story that ended exit 2 on this N18 and is rerun without a hand edit re-checks exit 0. Residual (R5): an attributed line that is a common whole sentence ('Yes.') cannot be said by another speaker's free dialogue, even as their own words, unless the narrative also gives those words to that speaker.
