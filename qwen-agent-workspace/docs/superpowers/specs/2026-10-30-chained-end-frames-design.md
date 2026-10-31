# Chained end frames: planned end frames, landed camera clauses, and a seam report

Date: 2026-10-30

Status: design spec. The user approved the design section by section on 2026-10-30 (Section 0.0). Every design choice is made here. Each choice the approved notes left open is marked **[spec choice]** with a one-line reason, and Section 11 lists them all. The implementer makes no design decisions.

Repository: `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/chain-wt`, branch `chain-endframes`, HEAD `574303a`. `WS` is `qwen-agent-workspace/`. Every relative path is relative to `WS`, and every line number cites the code at `574303a`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.

Input (binding): `$S/chain-endframes-design-notes.md`.

Specs this one builds on, cited by tag:
- **[SF]** `docs/superpowers/specs/2026-10-28-shot-prompt-format-design.md`: `CAMERA_SENTENCES`, `CAMERA_WRITER_FORMS`, `FORMAT_REFERENCE`, N20-N22, SF15 (`panel_prompt` order), SFT13.
- **[SPC]** `docs/superpowers/specs/2026-10-29-soft-panel-count-design.md`: a plan may have up to 2 more beats than the target.
- **[VLM]** `docs/superpowers/specs/2026-10-25-vlm-lifecycle-design.md`: `job_vlm`, preflight, postflight.
- **[MUI]** `docs/superpowers/specs/2026-10-19-movie-ui-design.md`: routes, jobs, the Stories tab.
- **[BF]** `docs/superpowers/specs/2026-10-30-batch-forks-design.md` (branch `bulk-rerun`, `$S/bulk-wt`). It merges first and adds 8 routes and a Batches tab.

---

## 0. Purpose and scope

### 0.0 The approved design (binding summary)

1. **Stored end frames.** In chained mode the planner writes an `end_frame` for every beat. Writer k is told it opens on end frame k-1 and must land its camera clause on end frame k. The video prompt never restates the start. `plan.json` is the single source of truth.
2. **Camera.** Five keys join the fixed list: `slow tracking left`, `slow tracking right`, `slow crane up`, `slow crane down`, `slow orbit`. Plain `tracking` stays legal (old plans) but is no longer offered. The P18 static cap is unchanged.
3. **Length.** The 6 s default (145 frames) stays; 241 frames stays a per-run choice. No code changes for length.
4. **Seam check.** A report after the render (`bin/seam-report`), never retries during it.
5. **One-shot templates.** A new `PLAN_REFERENCE` (the fishmonger movie as a planner reply), and `FORMAT_REFERENCE` rewritten as the finished shots of those beats, with "opens on / ends on" labels.
6. **Checks.** P22 (end frame present and 8-30 words; hard, re-ask, then drop), P23 (end frame content; advisory), P24 (plan copies the plan reference; hard, re-ask), N23 (camera clause lands on the end frame; one re-ask, then advisory).
7. **M1 fix.** Static words after "as the move completes" or "holding" no longer make a camera sentence "mixed".
8. **Quotes.** Double quotes in the final video prompt are reserved for spoken lines; other double quotes in the writer's action text become single quotes when `story.md` is written.
9. **Movie UI.** A "Check seams" button, a Compose option "Check seams after render" (on by default for chained movies) and the report in the Stories tab.
10. **Out of scope:** automatic re-render of missed panels, the "[SEED FROM PREVIOUS CLIP LAST FRAME: …]" prefix, resolution boilerplate and "motion bucket" (all rejected by the user).

### 0.1 Problem (verified at `574303a`)

- **E1. Nobody says where a chained panel ends.** The beat schema (`story_engine.py:1307-1315`) has no end composition. Writer k sees only the previous panel's Motion (`:3661-3664`). Its "as the move completes, …" clause ([SF] D4) is free text, so panel k+1's seed pixels and panel k+1's action can disagree.
- **E2. M1, "standing still".** `_mixed_camera` (`:1735-1739`) reads every `CAMERA_MOTION_RE` word of the whole sentence. "The camera pushes in — as the move completes, the ronin stands still at the right edge." has `pushes in` and `still`, so N20 calls it mixed, and `repair_action_text` (`:2028-2046`) drops the writer's end-framed sentence for the bare fallback.
- **E3. No tracking direction, crane or orbit.** `CAMERA_SENTENCES` (`:46-56`) has `tracking` only, without a direction.
- **E4. No seam measurement.** `bin/judge-clips` scores `seam_continuity` once per movie through Claude (`bin/judge-clips:76`, `:134`). Nothing scores a panel's last frame against a plan.
- **E5. Stray double quotes.** A writer Motion like `reads the "urgent" note` reaches LTX with double quotes that are not speech (`tests/test_dialogue.py:1444`); N7 only advises.

### 0.2 Grounding (verified at `574303a`)

**`story_engine.py` (5046 lines, stdlib only; `copy`, `json`, `re` imported at `:11-23`).**
- Camera: `CAMERA_SENTENCES` `:46-56`, `CAMERA_KEYS` `:57`, `CAMERA_RULE` `:407-409`, `CAMERA_SPEAKING_SENTENCE` `:410-412`, `SPEAKING_CAMERAS` `:1345`, `speaking_camera` `:1348`, `CAMERA_MOTION_RE` `:1665`, `STATIC_CAMERA_WORDS`/`CAMERA_MOVE_WORDS` `:1694-1706`, `CAMERA_CLAUSE_RE` `:1707`, `_camera_words` `:1716`, `camera_directions` `:1721`, `_mixed_camera` `:1735`, `_names_camera` `:1742`, `camera_problem` `:1746`, `repair_action_text` `:2007-2049`, `panel_camera` `:2052`, `CAMERA_WRITER_SENTENCE`/`CAMERA_WRITER_FORMS` `:2741-2764`.
- Plan: `PLAN_PROMPT_TEMPLATE` `:317-357` (beat keys `:346`, rules `:354`, end `:357`), `MODE_RULES` `:381`, `build_plan_prompt` `:1074-1149` (fragments `:1116-1141`), `normalize_plan` `:1250-1340` (beat dict `:1307-1315`), `line_assignment_problems` `:1442` (re-asks, never in a state), `plan_checks` `:2124-2333` (P12 block ends `:2267`, `speech_notes` `:2332`).
- Retry: `_Run.plan_round` `:4461-4492` (`PLAN_MAX_CALLS` = 2, `problems = hard + line_assignment_problems(plan)` `:4485`); `_Run.go` fatal ids `:4688-4699`, `plan, self.shape, _hard = found` `:4700`, round-0 format re-ask `:4730-4738`.
- Writer: `REFERENCE_TERMS`/`REFERENCE_COPY_SEGMENTS`/`REFERENCE_SIX_GRAMS`/`reference_copies` `:2537-2591` (N22, mirrored for P24), `FORMAT_REFERENCE` `:2506-2535`, `PANEL_PROMPT_TEMPLATE` `:2596-2616`, `panel_fields` `:2915-2945` (the action field is written at `:2938`, and `assemble` `:2948-2959` writes `story.md` from it), `build_panel_prompt` `:3643-3747` (previous line `:3661-3664`).
- Checks: `_field_checks` `:3034-3341` (N22 `:3334-3340`), `GENERATION_CHECKS` `:3485-3487`, `FORMAT_IDS`/`format_problems` `:3491-3501`, `trim_format` `:3504`, `panel_checks` `:3569`, `RECHECK_IDS` `:4819-4820`, `load_plan` `:4831`, `recheck` `:4939` (runs no plan step and never calls `panel_fields`).
- Helpers: `line_words` `:523`, `_mentions` `:645`, `_mentions_at` `:656`, `_q` `:1625`, `speaker_phrase_of` `:1634`, `_sentences` `:1675`, `cast_phrases` `:2978`, `_first` `:3019`, `_APPEARANCE_RE` `:2475` (N3), `DIALOGUE_RE` `:2482`.

**`character_lib.py`.** `clean_line` `:777-788` turns every inner double quote into an apostrophe; `speech_text` `:826-844` writes the line in straight double quotes; `compose_motion` `:860-871`; `panel_prompt` `:874-886`; `_is_camera_sentence` `:1028`; `_blank` `:1041`; `_passage_spans` `:1049`. **Unchanged.**

**`bin/ltx-mlx-render`.** `build_units` `:339-375` (a chained unit's seed is `clips/panel_%02d.chainseed.png`, the exact last frame of clip i-1); `extract_last_frame` `:647-667`. **Unchanged.**

**`bin/judge-clips`** imports `anthropic` and `jsonschema` at module top (`:42-43`). `probe_clip` `:291-318` and `extract_frames` `:328-351` run ffprobe/ffmpeg. **Unchanged.**

**`movie_ui_lib.py`.** `create_job` `:174-189` appends to `queue.json`; `job_vlm` `:421-436`; `effective_vlm` `:439-445`; `vlm_port` `:416`; `job_state` `:805`; `read_json` `:107`. Non-story, non-movie kinds get a generic progress snapshot (`:2219-2221`).

**`movie_ui_server.py`.** `ROUTES` `:64-111` (46 at `574303a`; [BF] makes 54), dispatch by handler name `:375-397`, `create_compose_job` `:749-760`, `_h_job_create` `:763-769`, `_story_dir` `:1709`, `_h_story` `:1726-1757`, `MovieUIHandler.h_story = _h_story` `:1877`.

**`static/movie-ui/`.** `index.html` (`c-run-all` `:135`, `s-regenerate` `:155`, `s-checks` `:160`), `app.js` (`updateComposeButtons` `:465-470`, Run all `:576`, `openStory` `:696-732`, `setupStories` `:756-782`), `app.css`.

**Tests.** `tests/story_engine_testutil.py`: `make_ctx` defaults to `mode="chained"` (`:297-311`); `plan_json` beats carry no `end_frame` (`:366-391`); the fake agent exits 9 with no envelope when its queue is empty (`:224-225`).

### 0.3 Deliverables

| # | File | Change |
|---|---|---|
| G1 | `story_engine.py` | CE1-CE12 |
| G2 | `bin/seam-report` (new, executable, stdlib only) | CE13 |
| G3 | `movie_ui_lib.py`, `movie_ui_server.py` | CE14 |
| G4 | `static/movie-ui/index.html`, `app.js`, `app.css` | CE15 |
| G5 | `tests/test_chained_end_frames.py`, `tests/test_seam_report.py`, `tests/test_movie_ui_seams.py` (new) | CT1-CT30 |
| G6 | Existing tests and fixtures | Section 7, in ONE test-only commit |

**Not changed:** `character_lib.py`, `bin/ltx-story-manifest`, `bin/ltx-mlx-render`, `bin/judge-clips`, `bin/ltx-movie`, `bin/story-server`, the `story.md` labels, `PLAN_MAX_CALLS`, `PANEL_MAX_CALLS`, `REPAIR_IDS`, `FORMAT_IDS`, `merge_repair`, `apply_patches`, `trim_format`, `DEFAULT_FIELDS`, `build_argv`, the `story_checks.json` shape, shots and no_stills planning (apart from the shared camera list, D2).

### 0.4 Out of scope and known limits

- Automatic re-render of missed panels.
- Batch-fork jobs ([BF]) queue no seams job (they are not created through `POST /api/jobs`).
- The seams job needs the VLM, so after a render the runner restores it (5-14 min, [VLM]). Accepted by the user.
- `bin/seam-report` judges one still per panel; it cannot see motion inside a clip.
- Old chained stories (no end frames) get no seam report and no new advisory (D10).

### 0.5 Must-haves and nice-to-haves

CE1-CE15 and CT1-CT30 are must-haves. Nothing else is built: no CLI flag on `bin/ltx-movie`, no threshold flag on `bin/seam-report`, no re-render.

---

## 1. Design decisions

### D1. End frames live in `plan.json`, chained beats only
- `normalize_plan` keeps a beat's `end_frame` in chained mode only. **The key is present only when the planner wrote a non-empty string [spec choice]**: plans without end frames (old, dropped, or test fixtures) keep their exact `plan.json` bytes.
- Every reader uses `beat.get("end_frame", "")`.

### D2. Camera keys
- The 5 new keys go into `CAMERA_SENTENCES` in move order; static stays last.
- **The plan prompt lists every key except plain `tracking` (`PLAN_CAMERA_KEYS`) [spec choice]**: removing it from the offered list is how new plans are told to give a direction. `CAMERA_KEYS` keeps it, so P8 stays quiet on old plans.
- **The list is shared by all modes [spec choice]**: the keys are generic moves, and one list keeps one P8 rule.
- **`slow tracking left` and `slow tracking right` join `SPEAKING_CAMERAS`; crane and orbit do not [spec choice]**: a crane or an orbit sweeps the face like a tilt or pan, so P14 turns them into a slow push-in.
- **The orbit fallback is "The camera arcs around the subject in a partial orbit." [spec choice]**: the notes' "The camera slowly arcs …" breaks the [WP] no-"slowly" rule (`tests/test_story_engine.py:2986-3006`), and "arcs" and "orbit" are the `CAMERA_MOTION_RE` words that make N20 recognise it (`arcs?` added by the final review, I3).

### D3. P22, P24 re-ask inside the existing budget; never in a state
- Both are computed in `plan_round` only and join `problems`, exactly as `line_assignment_problems` does (`:1442-1449`). They are **not** in `plan_checks`, so a state never holds them.
- **Exhaustion.** After the last call: if P22 still fails, or P24 hits only end frames, every end frame is dropped and `Warning: end frames dropped after N attempts; this story has no seam report` is printed (N = plan calls made). The story continues.
- **P24 hits outside the end frames after the last call are fatal (exit 1) [spec choice]**: a plan that copies the reference's people or places would make N22 exempt those words in every writer call (N22 exempts plan text), so the movie would reuse the reference; this is the existing P16/P17 exit path.

### D4. P23 is advisory, in `plan_checks`
P23 runs only on beats that have an end frame. It reports five kinds, at most one message each: a character outside the beat's cast, a camera word, an appearance/lighting/colour/style word (the N3 rule), a speaking verb, a double quote.
- **The style test is exactly the N3 rule (`_APPEARANCE_RE` with cast phrases and prop names blanked) [spec choice]**: writer k copies end frame k into its Motion, and N3 checks chained Motion for k ≥ 2, so a P23-clean end frame never trips N3.
- **The camera test ignores the static words and "follow(s)" [spec choice]**: an end frame is all "after the boundary" text (the M1 rule), and "stands still", "holds the cloth", "follows the gull" describe the subject.

### D5. Writer k is told where it opens and ends
- The opens-on and ends-on lines go into the `@@PREVIOUS@@` fragment, after the "previous panel's Motion" line, so `PANEL_PROMPT_TEMPLATE` is unchanged.
- **A static panel's ends-on line names "holding" instead of "as the move completes," [spec choice]**: the static writer form is "The camera stays static, holding <…>" ([SF] SF7).

### D6. M1: the end clause is not camera language
`END_CLAUSE_RE` matches "as the move completes" or "holding". `camera_head(sentence)` is the text before the first match.
- `_mixed_camera` takes both its static and its move words from `camera_head` only.
- **`_names_camera` also reads only `camera_head` [spec choice]**: otherwise a push-in whose clause says "she holds still" would pass as `static`.

### D7. N23: one re-ask through the round-0 repair path, then advisory
- **Clause.** The text after `END_CLAUSE_RE` in the first camera sentence of the assembled Motion that has one.
- **Names.** Every cast entry the end frame names (`_mentions`: phrase or library name) must be named in the clause. A pronoun does not count.
- **Words.** The clause must share at least `(n + 1) // 2` of the end frame's `n` content words.
- **Tokenisation.** `line_words`, with no stemming [spec choice]: deterministic, and the writer is told to describe this exact frame.
- **Stopwords.** `END_FRAME_STOP_WORDS` (CE9). Every word of every cast mention is also removed.
- **Severity.** `end_frame_landing_problems` (hard) is added to the round-0 `problems` next to `format_problems`, so it uses the existing single re-ask. In every state and on recheck, N23 is advisory (`_field_checks`). N23 is not in `FORMAT_IDS` or `REPAIR_IDS`, so patches, `merge_repair` and `trim_format` behave exactly as before.

### D8. Quote conversion where `story.md` is written
`panel_fields` (`:2938`) applies `reserve_quotes` to the writer's action text (Motion, or Prompt in no_stills) before the pasted pieces are joined. That single place feeds `assemble` (`story.md`), the "previous panel's Motion" line and every check that reads the assembled field.
- **All three modes [spec choice]**: the user's rule is about the final video prompt, and no_stills' Prompt is its final video prompt.
- Recheck never calls `panel_fields`, so old stories are untouched.
- The N7 "contains a double quote" advisory still reads the raw writer text and keeps firing.

### D9. The references
- `FORMAT_REFERENCE` becomes the finished shots of `PLAN_REFERENCE`'s beats (CE11). It is still one text for chained and shots writers.
- **Its shots keep their "The shot is …" sentences [spec choice]**: shots prompts have them; chained writers never write them, and the label says so.
- **Shot 1 is labelled "ends on" as well [spec choice]**: every writer is told its end frame, so the reference shows it for every shot.
- **Beat 1 is a medium shot, not wide [spec choice]**: `--speech-only` plans may not open wide (P7), and the reference must not teach a forbidden shot.
- **`PLAN_REFERENCE` is shown only in chained plan prompts with narration not False [spec choice]**: this mirrors [SF] D9 (no speaking example for a silent movie).
- **Its `lines` keys and its spoken-lines sentence are left out when the plan prompt has no `lines` key [spec choice]**: the reference must match the exact keys the prompt asks for.
- **P24's six-word runs count only when they hold a `PLAN_REFERENCE_KEY_WORDS` word [spec choice]**: the reference's descriptor, setting and positional phrases ("pale skin and short grey hair", "at frame centre, facing forward") are words every plan uses, not copies. N22 keeps its [SF] rule.
- **N22's segments leave out the three end-frame clauses and the "lifting her face to the camera" tail [spec choice]**: the clauses restate plan end frames, which writers must copy, and the tail is how every speaking first sentence ends.
- **`reference_copies` also exempts the plan's end frames [spec choice]**: writer k is told to copy end frame k into its clause.
- **"half-open shutter" joins `REFERENCE_TERMS` [spec choice]**: it is the reference's one distinctive prop that no other term covers.

### D10. Old stories
Recheck runs N23 only for beats with an end frame, and it runs no plan step. So an old story re-checks with the same rc, hard list and advisories, and composes the same manifest.
- **Conflict resolved:** the notes ask both for an advisory "this plan has no end frames; no seam report" on old plans and for old stories to re-check byte-identically. Recheck stays byte-identical. The note is shown instead by `bin/seam-report` (exit 0) and by the Stories tab (CE15) **[spec choice]**.

### D11. `bin/seam-report` talks to the story server directly
- **Loopback HTTP via `http.client`, not `bin/qwen-agent` [spec choice]**: qwen-agent's preflight auto-starts the local server through qwen-serve-guard when it is down (`bin/qwen-agent:2782-2820`), and the contract is "server down: exit 2, nothing changes".
- **It does not import `bin/judge-clips` [spec choice]**: judge-clips imports `anthropic` at module top. seam-report copies its ffprobe/ffmpeg argv instead, and judge-clips is untouched.
- **A chainseed counts only when it is not older than its clip [spec choice]**: a stale seed must never stand in for a re-rendered clip.
- **A transport failure after the probe aborts with exit 2 and writes nothing [spec choice]**: the same contract as a down server, so a half-finished report never replaces a good one.
- **"No clips to check" is exit 0 and writes nothing [spec choice]**: a failed movie must not be followed by a second failed job.

### D12. Movie UI
- **The Compose option is a `POST /api/jobs` body key, `check_seams`, outside `DEFAULT_FIELDS` [spec choice]**: [BF] pins `FIELD_LEVELS ∪ FIXED_KEYS == DEFAULT_FIELDS`, and a seams check is not a `bin/ltx-movie` field.
- Its API default is `false`, and only Compose's Run all sends it.
- **The seams job is created under the same `STORE_LOCK` hold as the movie job [spec choice]**: that is what keeps it directly behind the movie job in `queue.json`.
- **A second seams job for the same story is refused while one is queued or running [spec choice]**: a double click must not queue two VLM reloads.
- **A check_seams job runs only after its movie ended done [fix round 1, review I1]**: a cancelled, failed or lost movie would otherwise cost a VLM reload (5-14 minutes) before scoring stale or partial clips and replacing a current `seam_report.json`. Its `after` link makes the dispatcher cancel it with the reason instead. Checks queued by `POST /api/stories/<id>/seams` have no `after` and always run.

---

## 2. Requirements: planner (normative, `story_engine.py`)

### CE1. Camera keys and sentences

Replace `:44-57` (the comment, `CAMERA_SENTENCES` and `CAMERA_KEYS`) with:

```python
# Shot prompt format spec SF1, D1; chained end frames spec CE1, D2: moves first, static last; the
# pasted sentence is the fallback when the writer writes no camera sentence (SF6).
CAMERA_SENTENCES = (
    ("slow push-in", "The camera pushes in."),
    ("slow pull-back", "The camera pulls back."),
    ("tracking", "The camera tracks alongside the movement."),
    ("slow tracking left", "The camera tracks left alongside the movement."),
    ("slow tracking right", "The camera tracks right alongside the movement."),
    ("handheld", "The camera is handheld, with slight natural movement."),
    ("slow pan left", "The camera pans left."),
    ("slow pan right", "The camera pans right."),
    ("slow tilt up", "The camera tilts up."),
    ("slow tilt down", "The camera tilts down."),
    ("slow crane up", "The camera cranes up."),
    ("slow crane down", "The camera cranes down."),
    ("slow orbit", "The camera arcs around the subject in a partial orbit."),
    ("static", "The camera stays static."),
)
CAMERA_KEYS = tuple(key for key, _ in CAMERA_SENTENCES)
# Chained end frames spec CE1, D2: the plan prompt offers every key but plain "tracking", so a
# new plan names the tracking direction; "tracking" stays valid for P8 and old plans.
PLAN_CAMERA_KEYS = tuple(key for key in CAMERA_KEYS if key != "tracking")
```

So `@@CAMERA_LIST@@` becomes: `slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static`.

- In `build_plan_prompt` (`:1130`), `("@@CAMERA_LIST@@", ", ".join(CAMERA_KEYS))` becomes `("@@CAMERA_LIST@@", ", ".join(PLAN_CAMERA_KEYS))`.
- `CAMERA_SPEAKING_SENTENCE` (`:410-412`) becomes (exact):
  ```python
  CAMERA_SPEAKING_SENTENCE = (" On a beat with a speaker, prefer slow push-in, slow pull-back, "
                              "slow tracking left, slow tracking right or handheld, and never use a "
                              "pan, a tilt, a crane or an orbit, which sweep the speaker's face out "
                              "of the frame.")
  ```
- `SPEAKING_CAMERAS` (`:1345`) becomes `("slow push-in", "slow pull-back", "tracking", "slow tracking left", "slow tracking right", "handheld", "static")`. `speaking_camera`, `speaking_coercion` and their notes are unchanged.
- `CAMERA_MOVE_WORDS` (`:1695-1706`) becomes:
  ```python
  CAMERA_MOVE_WORDS = {
      "slow push-in": ("push in", "pushes in", "push-in", "dolly", "dollies", "zoom", "zooms"),
      "slow pull-back": ("pull back", "pulls back", "pull-back", "dolly", "dollies", "zoom",
                         "zooms"),
      "tracking": ("track", "tracks", "tracking", "follow", "follows", "dolly", "dollies"),
      "slow tracking left": ("track", "tracks", "tracking", "follow", "follows", "dolly",
                             "dollies"),
      "slow tracking right": ("track", "tracks", "tracking", "follow", "follows", "dolly",
                              "dollies"),
      "handheld": ("handheld",),
      "slow pan left": ("pan", "pans"),
      "slow pan right": ("pan", "pans"),
      "slow tilt up": ("tilt", "tilts"),
      "slow tilt down": ("tilt", "tilts"),
      "slow crane up": ("crane", "cranes"),
      "slow crane down": ("crane", "cranes"),
      "slow orbit": ("orbit", "orbits", "arc", "arcs"),
      "static": ("static", "still", "hold", "holds", "locked-off"),
  }
  ```
- `CAMERA_WRITER_FORMS` (`:2746-2764`) gains these five entries. Insert the tracking pair after `"tracking"` and the crane/orbit entries after `"slow tilt down"`; every existing entry is unchanged:
  ```python
      "slow tracking left": ("tracks left", "'The camera tracks left alongside <whom it follows> — "
                                           "as the move completes, <where the frame ends>.'"),
      "slow tracking right": ("tracks right", "'The camera tracks right alongside <whom it "
                                              "follows> — as the move completes, <where the frame "
                                              "ends>.'"),
      "slow crane up": ("cranes up", "'The camera cranes up — as the move completes, <what the "
                                     "frame ends on>.'"),
      "slow crane down": ("cranes down", "'The camera cranes down — as the move completes, <what "
                                         "the frame ends on>.'"),
      "slow orbit": ("arcs around the subject in a partial orbit", "'The camera arcs around <whom "
                     "it circles> in a partial orbit — as the move completes, <where the frame "
                     "ends>.'"),
  ```
- `CAMERA_MOTION_RE` gains `arcs?` right after `orbits?` (final review I3), so a writer's `The camera arcs around … — as the move completes, …` is a camera move: `_moves_camera` leaves out the pasted orbit sentence, and N20 checks the writer's one. `STILL_CAMERA_MOVES`, `CAMERA_CLAUSE_RE`, `CAMERA_RULE` and P18 are unchanged. Cost: an end frame with `arcs` ("the ball arcs over the net") gets the P23 camera-word advisory.

### CE2. The M1 boundary rule

Add immediately after `_camera_words` (`:1716-1718`):

```python
# Chained end frames spec CE2, D6 (M1): the words after "as the move completes" or "holding"
# describe the subject at the end frame, not the camera.
END_CLAUSE_RE = re.compile(r"\bas\s+the\s+move\s+completes\b|\bholding\b", re.IGNORECASE)


def camera_head(sentence):
    """The part of a camera sentence before its first END_CLAUSE_RE match, or the whole sentence
    when it has none (CE2)."""
    match = END_CLAUSE_RE.search(sentence)
    return sentence[:match.start()] if match else sentence


def end_clause(sentence):
    """The words of a camera sentence after its first END_CLAUSE_RE match, stripped of the
    characters " ,;:—–-.!?" at both ends, or "" when it has none (CE2, CE9)."""
    match = END_CLAUSE_RE.search(sentence)
    return sentence[match.end():].strip(" ,;:—–-.!?") if match else ""
```

`_mixed_camera` and `_names_camera` change only their first line:
- in `_mixed_camera` (`:1737`), `words = _camera_words(sentence)` becomes `words = _camera_words(camera_head(sentence))`;
- `_names_camera` (`:1742-1743`) becomes `return any(w in CAMERA_MOVE_WORDS[key] for w in _camera_words(camera_head(sentence)))`.

The `_mixed_camera` docstring gains ` Only the words before the end clause count (CE2, M1).`

Results:
- `"The camera pushes in — as the move completes, the ronin stands still at the right edge."` is not mixed and names `slow push-in`.
- `"The camera stays still and pushes in."` is still mixed.
- `"The camera stays static, holding the ronin as he stands still at the right edge."` names `static` and is not mixed.

`camera_directions` is unchanged (a camera sentence is still found by its whole text).

### CE3. `normalize_plan` keeps the end frame

Inside the beats loop (`:1306-1315`), immediately after the `beats.append({...})` call, at the same indent:

```python
        # Chained end frames spec CE3, D1: a chained beat keeps its end frame; the key is present
        # only when the planner wrote one.
        end_frame = _clean_str(item.get("end_frame")) if ctx.mode == "chained" else ""
        if end_frame:
            beats[-1]["end_frame"] = end_frame
```

`load_plan` is unchanged (old plans have no key; readers use `.get`).

### CE4. The plan prompt

**Template.**
- `:354` `"@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@\n"` becomes `"@@MAX_CAST@@.@@SPEAKER_RULE@@@@LINES_RULE@@@@END_FRAME_RULE@@\n"`.
- `:357` `"@@MODE_RULES@@" + NO_TOOL_SENTENCE)` becomes `"@@MODE_RULES@@@@PLAN_REFERENCE@@" + NO_TOOL_SENTENCE)`.

**Constant.** Add immediately after `CAMERA_SPEAKING_SENTENCE`:

```python
# Chained end frames spec CE4, D1: the planner's end frame of every chained beat.
END_FRAME_RULE = (" end_frame is one sentence of 8 to 30 words, in the present tense, of the "
                  "frame the beat ends on: who or what is in frame, where each one is (left, "
                  "centre or right; foreground or background), which way they face and how tight "
                  "the shot is. It never names a camera move, the lighting, a colour or a style, "
                  "has no spoken words and no double quotes, and names only characters in the "
                  "beat's cast. Beat k's end frame is exactly where beat k+1 begins; write beat "
                  "k+1's action so it starts from that composition. The last beat's end frame "
                  "closes the story.")
```

**`build_plan_prompt`.**
- Before `fragments = [` (`:1116`), add:
  ```python
  beat_keys = "cast, speaker and lines" if lines else "cast and speaker"
  if ctx.mode == "chained":
      beat_keys = "cast, speaker, lines and end_frame" if lines else "cast, speaker and end_frame"
  ```
- `("@@BEAT_KEYS@@", "cast, speaker and lines" if lines else "cast and speaker")` (`:1137`) becomes `("@@BEAT_KEYS@@", beat_keys)`.
- Append these two fragments at the end of the list (after `@@LINES_RULE@@`):
  ```python
  ("@@END_FRAME_RULE@@", END_FRAME_RULE if ctx.mode == "chained" else ""),
  ("@@PLAN_REFERENCE@@", plan_reference(bool(lines))
   if ctx.mode == "chained" and ctx.narration is not False else ""),
  ```

Shots and no_stills prompts change only in the camera list and `CAMERA_SPEAKING_SENTENCE`.

### CE5. The plan reference

Add immediately after `reference_copies` (`:2568-2591`):

```python
# Chained end frames spec CE5, D9: a complete three-beat planner reply of the FORMAT_REFERENCE
# movie, shown to the chained planner for its format only.
PLAN_REFERENCE_INTRO = ("FORMAT REFERENCE ONLY — never reuse its people, places, objects or "
                        "words. This is the complete plan of a three-beat movie made as one "
                        "continuous take, a different story from this one.%s It shows the format "
                        "of every plan: each beat's end_frame says exactly where the beat ends, "
                        "the next beat's action starts from that end frame, and the last end "
                        "frame closes the story.\n")
PLAN_REFERENCE_LINES_CLAUSE = (' Its narrative quoted two spoken lines: 1 "Forty years of '
                               'mornings." and 2 "Not one more."')
PLAN_REFERENCE_PLAN = {
    "title": "The Last Morning at the Market",
    "logline": ("At dawn an old fishmonger closes her market hall for the last time and says "
                "goodbye to forty years of work."),
    "cast": [{"id": "c1", "phrase": "the old fishmonger",
              "descriptor": ("an old woman with a stooped build, weathered pale skin and short "
                             "grey hair under a knitted cap, wearing a rubber apron over a thick "
                             "wool jumper and tall rubber boots")}],
    "locations": [{"id": "l1", "setting": (
        "The setting is a covered fish market hall in a northern harbour town at dawn, wet "
        "concrete underfoot, rows of bare zinc counters behind, under grey first light from the "
        "harbour doors.")}],
    "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
    "beats": [
        {"index": 1, "arc": "introduction",
         "action": ("The old fishmonger drags a tall stack of empty herring crates across the wet "
                    "market hall to the half-open shutter."),
         "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"],
         "speaker": "", "lines": [],
         "end_frame": ("The old fishmonger stands beside the half-open shutter at frame centre, "
                       "facing left toward the hall, seen from the knees up, the empty crates at "
                       "her feet.")},
        {"index": 2, "arc": "climax",
         "action": ("From the shutter, the old fishmonger turns back into the hall and walks to "
                    "the zinc counter, laying her folded cloth on it."),
         "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"],
         "speaker": "c1", "lines": [1, 2],
         "end_frame": ("The old fishmonger stands behind the zinc counter at frame centre, "
                       "facing forward, her face filling the frame from chin to brow.")},
        {"index": 3, "arc": "resolution",
         "action": ("The old fishmonger lowers her forehead onto her folded hands on the cold "
                    "zinc counter and closes her eyes."),
         "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"],
         "speaker": "", "lines": [],
         "end_frame": ("The old fishmonger rests her forehead on her folded hands at frame "
                       "centre, eyes closed, her head and hands filling the frame in a "
                       "close-up.")},
    ],
    "loras": {"global": [], "per_beat": {}, "stills": []},
}


def _plan_reference_json(plan):
    """The reference plan as JSON (CE5): title and logline on the first line, then one line each
    for cast, locations and props, one line per beat, and loras; json.dumps defaults with
    ensure_ascii=False, keys in dict order."""
    def dump(value):
        return json.dumps(value, ensure_ascii=False)
    lines = ['{"title": %s, "logline": %s,' % (dump(plan["title"]), dump(plan["logline"]))]
    lines += [' "%s": %s,' % (key, dump(plan[key])) for key in ("cast", "locations", "props")]
    lines.append(' "beats": [')
    last = len(plan["beats"]) - 1
    lines += ["  " + dump(beat) + ("," if i < last else "],") for i, beat in enumerate(plan["beats"])]
    lines.append(' "loras": %s}' % dump(plan["loras"]))
    return "\n".join(lines)


def plan_reference(lines):
    """The @@PLAN_REFERENCE@@ text (CE5): with lines, the plan as written; without, every beat's
    "lines" key and the spoken-lines sentence are left out, matching a prompt with no lines key."""
    plan = copy.deepcopy(PLAN_REFERENCE_PLAN)
    if not lines:
        for beat in plan["beats"]:
            del beat["lines"]
    return ((PLAN_REFERENCE_INTRO % (PLAN_REFERENCE_LINES_CLAUSE if lines else ""))
            + _plan_reference_json(plan) + "\n\n")


# Chained end frames spec CE6, D9: P24 counts a six-word run only when it holds one of these.
PLAN_REFERENCE_KEY_WORDS = frozenset(("fishmonger", "fishmongers", "herring", "herrings",
                                      "crates", "zinc", "shutter", "cloth"))
PLAN_REFERENCE_SEGMENTS = tuple(
    [PLAN_REFERENCE_PLAN["title"], PLAN_REFERENCE_PLAN["logline"]]
    + [c["descriptor"] for c in PLAN_REFERENCE_PLAN["cast"]]
    + [l["setting"] for l in PLAN_REFERENCE_PLAN["locations"]]
    + [p["name"] for p in PLAN_REFERENCE_PLAN["props"]]
    + [b["action"] for b in PLAN_REFERENCE_PLAN["beats"]]
    + [b["end_frame"] for b in PLAN_REFERENCE_PLAN["beats"]])
PLAN_REFERENCE_SIX_GRAMS = frozenset(g for s in PLAN_REFERENCE_SEGMENTS
                                     for g in _six_grams(line_words(s))
                                     if set(g) & PLAN_REFERENCE_KEY_WORDS)
```

Pinned values (CT2 asserts them; a transcription slip fails loudly):

| Value | sha256 | chars | words |
|---|---|---|---|
| `_plan_reference_json(PLAN_REFERENCE_PLAN)` | `e3329d43c6049b5d7e727531d37cd14b0a19fda8d3055f79c9298e5280123a53` | 2103 | 322 |
| `plan_reference(True)` | `f01c845181417fa7a3d77f112786e52efb05c029716c141e3999c6f2c1a87fb3` | 2562 | 403 |
| `plan_reference(False)` | `571591dffb3a354b21569a171420b6e762268787854d9b1c22dbd496482c1eff` | 2429 | 380 |

`len(PLAN_REFERENCE_SIX_GRAMS) == 68`.

The JSON part of `plan_reference(True)` (informative; the hash binds):

```json
{"title": "The Last Morning at the Market", "logline": "At dawn an old fishmonger closes her market hall for the last time and says goodbye to forty years of work.",
 "cast": [{"id": "c1", "phrase": "the old fishmonger", "descriptor": "an old woman with a stooped build, weathered pale skin and short grey hair under a knitted cap, wearing a rubber apron over a thick wool jumper and tall rubber boots"}],
 "locations": [{"id": "l1", "setting": "The setting is a covered fish market hall in a northern harbour town at dawn, wet concrete underfoot, rows of bare zinc counters behind, under grey first light from the harbour doors."}],
 "props": [{"id": "p1", "name": "the herring crates"}, {"id": "p2", "name": "the folded cloth"}],
 "beats": [
  {"index": 1, "arc": "introduction", "action": "The old fishmonger drags a tall stack of empty herring crates across the wet market hall to the half-open shutter.", "shot": "medium shot", "camera": "slow tracking right", "location": "l1", "cast": ["c1"], "speaker": "", "lines": [], "end_frame": "The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet."},
  {"index": 2, "arc": "climax", "action": "From the shutter, the old fishmonger turns back into the hall and walks to the zinc counter, laying her folded cloth on it.", "shot": "medium shot", "camera": "slow push-in", "location": "l1", "cast": ["c1"], "speaker": "c1", "lines": [1, 2], "end_frame": "The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow."},
  {"index": 3, "arc": "resolution", "action": "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter and closes her eyes.", "shot": "close-up", "camera": "static", "location": "l1", "cast": ["c1"], "speaker": "", "lines": [], "end_frame": "The old fishmonger rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame in a close-up."}],
 "loras": {"global": [], "per_beat": {}, "stills": []}}
```

Verified on `574303a` code with the narrative `REF_NARRATIVE` (CT2), chained, 3 panels, `clip_seconds` 145/24, narration `"speech"` and `True`:
- `normalize_plan` + `plan_checks` give hard `[]`.
- The only advisory was P8 for `slow tracking right`, which CE1 removes.
- Q1 gives `[]`, and no P14 coercion happens.

The reference contains no `@@` and no "slowly". It costs about 650 prompt tokens per chained plan call.

### CE6. P22, P23 and P24

Add `_named_ids` immediately after `_mentions_at` (`:656-668`):

```python
def _named_ids(words, mentions):
    """The cast ids, in mention order without repeats, whose mention ([(cast id, words)], as
    _mentions) occurs as consecutive words of words (chained end frames spec CE6, CE9)."""
    out = []
    for cid, tokens in mentions:
        n = len(tokens)
        if cid not in out and any(words[i:i + n] == tokens for i in range(len(words) - n + 1)):
            out.append(cid)
    return out
```

Add immediately after `line_assignment_problems` (`:1442-1449`):

```python
# Chained end frames spec CE6, D3, D4: the end frame checks. P22 and P24 make the plan call
# retry and never enter a state; P23 is a plan_checks advisory.
END_FRAME_WORDS = (8, 30)
P22_MISSING = ("beat %d: P22 end frame: end_frame is missing or empty; write one sentence of 8 "
               "to 30 words of the frame this beat ends on: who or what is in frame, where (left, "
               "centre or right; foreground or background), which way they face and how tight "
               "the shot is")
P22_LENGTH = "beat %d: P22 end frame: end_frame is %d words; write one sentence of 8 to 30 words"
P24_MESSAGE = ("plan: P24 reference copy: %s copies the plan reference (%s); write only this "
               "movie's own people, places, objects and words")
END_FRAMES_DROPPED = ("Warning: end frames dropped after %d attempts; this story has no seam "
                      "report")


def plan_end_frame_problems(ctx, plan):
    """The P22 messages of a chained plan, in beat order (CE6): a beat with no end frame, or one
    whose word count (_words) is outside END_FRAME_WORDS. [] in shots and no_stills."""
    if ctx.mode != "chained":
        return []
    out = []
    for k, beat in enumerate(plan["beats"], start=1):
        text = beat.get("end_frame", "")
        if not text:
            out.append(P22_MISSING % k)
        elif not END_FRAME_WORDS[0] <= _words(text) <= END_FRAME_WORDS[1]:
            out.append(P22_LENGTH % (k, _words(text)))
    return out


def end_frame_advisories(ctx, lib, plan):
    """The P23 advisories of a chained plan's end frames, in beat order, at most one of each kind
    per beat (CE6, D4): a cast entry outside the beat's cast; a camera word (a CAMERA_CLAUSE_RE
    match, else a CAMERA_MOTION_RE word other than the static words and follow/follows); an N3
    word (_APPEARANCE_RE with the cast phrases and prop names blanked); a speaking verb
    (DIALOGUE_RE); a straight or curly double quote."""
    if ctx.mode != "chained":
        return []
    still = CAMERA_MOVE_WORDS["static"] + ("follow", "follows")
    mentions = _mentions(plan["cast"])
    names = cast_phrases(ctx, plan) + [p["name"] for p in plan["props"] if p.get("name")]
    out = []
    for k, beat in enumerate(plan["beats"], start=1):
        text = beat.get("end_frame", "")
        if not text:
            continue
        prefix = "beat %d: P23 end frame content:" % k
        stray = [c for c in _named_ids(line_words(text), mentions) if c not in beat["cast"]]
        if stray:
            out.append("%s names %s, who is not in beat %d's cast"
                       % (prefix, _q(speaker_phrase_of(plan, stray[0])), k))
        clause = CAMERA_CLAUSE_RE.search(text)
        word = (" ".join(clause.group(0).lower().split()) if clause else
                next((w for w in _camera_words(text) if w not in still), None))
        if word:
            out.append("%s says %s; an end frame describes the frame, never a camera move"
                       % (prefix, _q(word)))
        word = _first(_APPEARANCE_RE, lib._blank(text, lib._passage_spans(text, names)))
        if word:
            out.append("%s says %s; an end frame never describes appearance, clothing, setting, "
                       "lighting, colour or style" % (prefix, _q(word)))
        word = _first(DIALOGUE_RE, text)
        if word:
            out.append("%s says %s; an end frame has no spoken words" % (prefix, _q(word)))
        if any(q in text for q in _DOUBLE_QUOTES):
            out.append("%s contains a double quote; double quotes are kept for spoken lines"
                       % prefix)
    return out


def plan_copy_problems(ctx, plan, end_frames=True):
    """The P24 messages of a chained plan shown PLAN_REFERENCE (CE6): every model-written field
    (title, logline, a non-library cast entry's phrase and descriptor, a non-library location's
    setting, prop names, beat actions and, with end_frames, beat end frames) that contains a
    REFERENCE_TERMS term or a PLAN_REFERENCE_SIX_GRAMS run, leaving out any the narrative, the
    goal, a library character's phrase or descriptor or a library location's description already
    has. [] unless ctx.mode is chained and ctx.narration is not False."""
    if ctx.mode != "chained" or ctx.narration is False:
        return []
    own = ([ctx.narrative or "", ctx.goal or ""] + [m.phrase for m in ctx.members]
           + [m.descriptor for m in ctx.members] + [pin.description for pin in ctx.locations])
    own_words = [line_words(t) for t in own]
    own_line = " " + " | ".join(" ".join(w) for w in own_words) + " "
    own_grams = set(g for w in own_words for g in _six_grams(w))
    texts = [("the title", plan["title"]), ("the logline", plan["logline"])]
    for c in plan["cast"]:
        if not c.get("cast_name"):
            texts += [("%s's phrase" % c["id"], c["phrase"]),
                      ("%s's descriptor" % c["id"], c["descriptor"])]
    texts += [("%s's setting" % l["id"], l["setting"]) for l in plan["locations"]
              if not l.get("location_name")]
    texts += [("%s's name" % p["id"], p["name"]) for p in plan["props"]]
    texts += [("beat %d's action" % k, b["action"]) for k, b in enumerate(plan["beats"], start=1)]
    if end_frames:
        texts += [("beat %d's end frame" % k, b.get("end_frame", ""))
                  for k, b in enumerate(plan["beats"], start=1)]
    out = []
    for where, text in texts:
        words = line_words(text or "")
        line = " " + " ".join(words) + " "
        hits = [t for t in REFERENCE_TERMS
                if (" %s " % " ".join(line_words(t))) in line
                and (" %s " % " ".join(line_words(t))) not in own_line]
        hits += [" ".join(g) for g in sorted((_six_grams(words) & PLAN_REFERENCE_SIX_GRAMS)
                                             - own_grams)]
        if hits:
            out.append(P24_MESSAGE % (where, ", ".join(_q(h) for h in hits[:3])))
    return out


def drop_end_frames(plan):
    """Remove every beat's end frame, in place (CE7)."""
    for beat in plan["beats"]:
        beat.pop("end_frame", None)
```

`CAMERA_MOVE_WORDS`, `CAMERA_CLAUSE_RE`, `_camera_words`, `_APPEARANCE_RE`, `DIALOGUE_RE`, `cast_phrases`, `_first`, `_DOUBLE_QUOTES`, `REFERENCE_TERMS`, `_six_grams` and `PLAN_REFERENCE_SIX_GRAMS` are module names defined later. They are read only at call time.

**P23 in `plan_checks`.** Immediately after the chained P11/P12 block (it ends at `:2267`), before the `# Pinned cast presence spec PC1` comment, add at function-body indent:

```python
    # Chained end frames spec CE6, D4: P23, the end frame content (advisory).
    advisory += end_frame_advisories(ctx, lib, plan)
```

`lib` is already bound at `:2181`.

### CE7. Plan retry and exhaustion (`_Run`)

**`plan_round` (`:4485`).** `problems = hard + line_assignment_problems(plan)` becomes:

```python
                problems = (hard + plan_end_frame_problems(ctx, plan)
                            + plan_copy_problems(ctx, plan) + line_assignment_problems(plan))
```

`found` keeps its 3-tuple shape `(plan, shape, hard)`.

**The fallback (Task 2 fix round 1, review finding I1).** A P22 or P24 re-ask never turns a usable call 1 into an exit 1, and a timeout never discards one. `_Run` gains `plan_fatal`, the one fatal list that `go` and `plan_round` share:

```python
    def plan_fatal(self, found):
        """The problems that make found = (plan, shape, hard) unusable even with its end frames
        dropped (chained end frames spec CE7): its P1, P2, P16, P17 and P21 hard problems and a
        P24 copy outside the end frames. go and plan_round's fallback share this one list."""
        return ([h for h in found[2]
                 if parse_violation(h)["id"] in ("P1", "P2", "P16", "P17", "P21")]
                + plan_copy_problems(self.ctx, found[0], end_frames=False))
```

- In chained mode `plan_round` keeps `fallback`: the most recent parsed reply whose `plan_fatal` is empty. End-frame problems (P22, and P24 in the end frames) are not in `plan_fatal`, so they never disqualify a fallback.
- `plan_round` returns `fallback or found`: a fatal last reply never replaces an earlier usable one. With no usable reply it returns `found`, as before, and `go` exits 1.
- When `self.expired()` is true before a call and `fallback` is set, `plan_round` returns `(fallback, None)` instead of `(None, "timeout")`. The run then reaches round 0, whose panel checks apply the same wall-clock cap.
- `go`'s drop below removes the fallback's failing end frames; `END_FRAMES_DROPPED`'s N is still the number of plan calls made.
- In shots and no_stills `fallback` stays `None`, so both modes behave exactly as before. `PLAN_MAX_CALLS` stays 2; the fallback makes no model call.

**`go` (`:4688-4700`).** The `fatal = ...` statement becomes:

```python
        fatal = self.plan_fatal(found) if found else ["the reply is not one JSON object"]
```

The comment above it gains `; chained end frames spec CE7: a P24 copy outside the end frames too`.

Immediately after `plan, self.shape, _hard = found` (`:4700`), add:

```python
        # Chained end frames spec CE7, D3: end frames that still fail after the last plan call
        # are dropped; the story never fails because of them.
        if plan_end_frame_problems(ctx, plan) or plan_copy_problems(ctx, plan):
            drop_end_frames(plan)
            print(END_FRAMES_DROPPED % len([c for c in self.doc["calls"] if c["stage"] == "plan"]))
```

- The warning goes to stdout, like the other `Warning:` lines.
- No advisory is added (D10). `plan.json` then has no `end_frame` keys.

**Paths:**
- A plan valid on call 1 makes one call.
- A P22 or P24 failure on call 1 re-asks with those messages in the existing "YOUR PREVIOUS REPLY WAS REJECTED" block.
- After call 2, the plan either drops its end frames (P22, or P24 in end frames only) or exits 1 (P24 elsewhere, listed with the other fatal problems).
- A fatal call 2 after a usable call 1 (one with no `plan_fatal` problem) uses call 1, whose failing end frames are then dropped. A timeout before call 2 uses a usable call 1 the same way.

### CE8. What writer k is told

Add immediately after `SPEAKING_STAY_SENTENCE` (`:2774-2775`):

```python
# Chained end frames spec CE8, D5: writer k starts from end frame k-1 and lands on end frame k.
OPENS_ON_LINE = ("This panel opens on: %s Start the action from exactly this composition; do "
                 "not describe it.\n")
ENDS_ON_LINE = ("This panel ends on: %s The clause after 'as the move completes,' in your camera "
                "sentence must describe this end frame.\n")
ENDS_ON_STATIC_LINE = ("This panel ends on: %s The words after 'holding' in your camera "
                       "sentence must describe this end frame.\n")
```

In `build_panel_prompt`, immediately after the `previous` block (`:3661-3664`), add:

```python
    if ctx.mode == "chained":
        opens = plan["beats"][k - 2].get("end_frame", "") if k >= 2 else ""
        ends = beat.get("end_frame", "")
        if opens:
            previous += OPENS_ON_LINE % _sentence(opens)
        if ends:
            previous += ((ENDS_ON_STATIC_LINE if panel_camera(ctx, plan, k) == "static"
                          else ENDS_ON_LINE) % _sentence(ends))
```

- Panel 2 of the reference movie sees: `The previous panel's Motion: <Motion 1>\nThis panel opens on: The old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet. Start the action from exactly this composition; do not describe it.\nThis panel ends on: The old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow. The clause after 'as the move completes,' in your camera sentence must describe this end frame.\n\n` and then `FORMAT_REFERENCE`.
- A plan without end frames gives exactly the `574303a` prompt, apart from the `FORMAT_REFERENCE` text.
- The `CAMERA_WRITER_SENTENCE` key-line sentence is unchanged.

### CE9. N23 "end frame landing"

Add immediately after `trim_format` (`:3504-3566`):

```python
# Chained end frames spec CE9, D7: N23, the camera sentence lands on the planned end frame.
END_FRAME_STOP_WORDS = frozenset("""
    a an the and or but nor of to in on at by for from with without into onto off over under up
    down out about across along around through toward towards behind beside between near past
    against as is are be being it its he she they him her them his hers their theirs this that
    these those there here who whom which what while where when one each both all every
    some""".split())


def end_frame_words(text, mention_words):
    """The content words of text (N23): its line_words that are neither END_FRAME_STOP_WORDS nor
    in mention_words (every word of every cast mention), as a set."""
    return set(w for w in line_words(text) if w not in END_FRAME_STOP_WORDS
               and w not in mention_words)


def end_frame_detail(lib, plan, k, text, phrases):
    """The N23 detail of panel k's assembled Motion text, or None (CE9). None when beat k has no
    end frame. The clause is end_clause of the first camera sentence (lib._is_camera_sentence with
    phrases) that has one. It fails when there is no such clause; when it does not name every cast
    entry the end frame names (_named_ids over _mentions); or when it shares fewer than
    (n + 1) // 2 of the end frame's n content words (end_frame_words)."""
    end_frame = plan["beats"][k - 1].get("end_frame", "")
    if not end_frame:
        return None
    clause = next((end_clause(s) for s in _sentences(text)
                   if lib._is_camera_sentence(s, phrases) and end_clause(s)), "")
    if not clause:
        return ("has no camera sentence whose words after 'as the move completes,' (or after "
                "'holding' for a static camera) describe the planned end frame %s"
                % _q(end_frame))
    mentions = _mentions(plan["cast"])
    named = _named_ids(line_words(clause), mentions)
    missing = [c for c in _named_ids(line_words(end_frame), mentions) if c not in named]
    if missing:
        return ("the camera sentence ends %s, which does not name %s, whom the planned end frame "
                "%s names" % (_q(clause), " and ".join(_q(speaker_phrase_of(plan, c))
                                                      for c in missing), _q(end_frame)))
    mention_words = set(w for _cid, words in mentions for w in words)
    want = end_frame_words(end_frame, mention_words)
    shared = len(want & end_frame_words(clause, mention_words))
    need = (len(want) + 1) // 2
    if shared < need:
        return ("the camera sentence ends %s, which shares %d of the %d content words of the "
                "planned end frame %s; it needs at least %d"
                % (_q(clause), shared, len(want), _q(end_frame), need))
    return None


def end_frame_landing_problems(ctx, plan, part, k):
    """[the hard N23 message] of panel k with writer parts part, or [] (CE9; round 0 only)."""
    if ctx.mode != "chained" or not plan["beats"][k - 1].get("end_frame"):
        return []
    parts = [{}] * (k - 1) + [part]
    motion = dict(panel_fields(ctx, plan, parts, k)).get("Motion", "")
    detail = end_frame_detail(_character_lib(ctx.ws), plan, k, motion, cast_phrases(ctx, plan))
    return ["panel %d: N23 end frame landing: Motion: %s" % (k, detail)] if detail else []
```

**Advisory in `_field_checks`.** Inside the `if plan and beat is not None and action_label in dict(fields):` block, after the N22 block (`:3334-3340`) and at the same indent as `if "N22" in ids:`:

```python
        if "N23" in ids and ctx.mode == "chained":
            detail = end_frame_detail(lib, plan, k, dict(fields)[action_label], known)
            if detail:
                advisory.append("%s N23 end frame landing: %s: %s"
                                % (prefix, action_label, detail))
```

The docstring's hard list is unchanged; append `N23 is always advisory here (chained end frames spec CE9).`

**Round 0 (`go`, `:4730-4736`).** Replace the two `format_problems` uses:

```python
                problems = (format_problems(ctx, plan, new, k)
                            + end_frame_landing_problems(ctx, plan, new, k))
                if (problems and self.panel_calls[k] < PANEL_MAX_CALLS
                        and not self.expired()):
                    again = self.panel_call(plan, parts, k, 0, problems)
                    if (again is not None
                            and len(format_problems(ctx, plan, again, k)
                                    + end_frame_landing_problems(ctx, plan, again, k))
                            <= len(problems)
                            and (ctx.mode != "chained"
                                 or len(panel_hard_problems(ctx, plan, again, k))
                                 <= len(panel_hard_problems(ctx, plan, new, k)))):
                        parts[k - 1] = again
                parts[k - 1] = trim_format(ctx, plan, k, parts[k - 1])
```

The comment above gains `; chained end frames spec CE9: N23 joins the same single re-ask, and a chained reply to it is kept only when it also adds no hard problem to the panel`.

**The acceptance (Task 3 fix round 1, review finding I1).** The re-ask spends the panel's last call (`PANEL_MAX_CALLS` is 2), so a kept reply that adds a hard problem leaves the critic as the only fix, and a critic with no valid patch ends the story at exit 2. A chained re-asked reply is therefore kept only when both hold:
- its format and N23 messages are no more than the first reply's (the SF13 rule, unchanged);
- its `panel_hard_problems` list is no longer than the first reply's.

`panel_hard_problems` is added after `end_frame_landing_problems`:

```python
def panel_hard_problems(ctx, plan, part, k):
    """The hard _field_checks messages of panel k with writer parts part, with the ids and
    undeclared characters panel_checks uses (GENERATION_CHECKS, generating): the panel's hard
    problems a round-0 state would hold. A chained round-0 re-ask keeps its reply only when this
    list does not grow (chained end frames spec CE9)."""
    parts = [{}] * (k - 1) + [part]
    writers = {LABELS[key]: part.get(key, "") for key in panel_keys(ctx, plan, k)
               if key != "title"}
    return _field_checks(ctx, _character_lib(ctx.ws), plan, k, part.get("title", ""),
                         panel_fields(ctx, plan, parts, k), writers, GENERATION_CHECKS,
                         undeclared_characters(ctx), generating=True)[0]
```

- The list already holds the panel's hard N7, N20, N21 and N22 messages (the `format_problems` ids), and N23 is advisory in `_field_checks`. So a reply that trades an N23 miss for a hard T1 is rejected: its format and N23 count falls from 1 to 0, but its hard list grows from 0 to 1. A reply that lands the clause and keeps the same hard count is kept.
- Shots and no_stills keep the SF13 rule alone: `panel_hard_problems` is never called there.
- No model call is added.

So N23 is hard only for the round-0 re-ask decision. After that one re-ask, or when the panel has no call left, the panel is kept and N23 is an advisory in every state and on recheck.

The reference: for its three Motion fields, `end_frame_detail` is None (shared 14/14, 11/11 and 10/11 content words).

### CE10. Quotes reserved for spoken lines

Add immediately before `panel_fields` (`:2915`):

```python
# Chained end frames spec CE10, D8: double quotes in a final video prompt are kept for the
# spoken line, so the writer's action text is written with apostrophes.
_DOUBLE_QUOTES = ('"', "“", "”")


def reserve_quotes(text):
    """text with every straight or curly double quote turned into an apostrophe (CE10)."""
    for quote in _DOUBLE_QUOTES:
        text = text.replace(quote, "'")
    return text
```

`panel_fields` (`:2938`): `fields.append((LABELS[key], join([p.get(key, "")] + pieces)))` becomes `fields.append((LABELS[key], join([reserve_quotes(p.get(key, ""))] + pieces)))`. Its docstring gains `; the writer's action text has its double quotes turned into apostrophes (chained end frames spec CE10)`.

- `p.get(key)` in the CM4 test (`:2936`) is unchanged.
- Image, Dialogue and Narration are untouched. Spoken lines reach LTX only through `speech_text` in `bin/ltx-story-manifest`, in straight double quotes.

### CE11. The format reference and N22

`FORMAT_REFERENCE` (`:2506-2535`) becomes (exact; `—` is U+2014; the comment above it gains `; chained end frames spec CE11: the finished shots of PLAN_REFERENCE's beats, with opens-on and ends-on labels`):

```python
FORMAT_REFERENCE = (
    "FORMAT REFERENCE ONLY — never reuse its people, places, objects or words. These are the "
    "finished video prompts of three shots from a different movie. They show the order of "
    "every finished shot: the shot type; the action; when someone speaks, the spoken line and "
    "then one short reaction by the speaker; the one camera sentence, which says where the "
    "move ends; and the audio last. The pipeline wrote the sentences that start 'The shot "
    "is', the sentence 'The old fishmonger faces the camera.', the spoken line and the "
    "audio sentence; the writer wrote every other sentence. Each label names the frame its "
    "shot opens on and the frame it ends on: the action starts from the opening frame without "
    "describing it, and the words after 'as the move completes,' or 'holding' in the camera "
    "sentence describe the end frame. Double quotes appear only around the spoken line.\n"
    "Shot 1 (silent; the camera tracks right; ends on: The old fishmonger stands beside the "
    "half-open shutter at frame centre, facing left toward the hall, seen from the knees up, "
    "the empty crates at her feet): The shot is a medium shot. The old fishmonger drags a tall "
    "stack of empty herring crates across the wet concrete of the market hall toward the "
    "half-open shutter at real-time speed, her heavy steps splashing through shallow puddles "
    "that hold the first glow from the harbour doors. The camera tracks right alongside her — "
    "as the move completes, the old fishmonger stands beside the half-open shutter at frame "
    "centre, facing left toward the hall, seen from the knees up, the empty crates at her "
    "feet. The audio is the natural ambient sound of the place, with no music.\n"
    "Shot 2 (speaking; the camera pushes in; opens on: The old fishmonger stands beside the "
    "half-open shutter at frame centre, facing left toward the hall, seen from the knees up, "
    "the empty crates at her feet; ends on: The old fishmonger stands behind the zinc counter "
    "at frame centre, facing forward, her face filling the frame from chin to brow): The shot "
    "is a medium shot. The old fishmonger turns back from the shutter and walks to the zinc "
    "counter at real-time speed, laying her folded cloth beside the empty ice trays and "
    "lifting her face to the camera. The old fishmonger faces the camera. The old fishmonger "
    "says, \"Forty years of mornings.\" After a breath, \"Not one more.\" The old fishmonger "
    "presses both palms flat on the folded cloth, her shoulders sinking. The camera pushes in "
    "— as the move completes, the old fishmonger stands behind the zinc counter at frame "
    "centre, facing forward, her face filling the frame from chin to brow. The audio is clear "
    "close-mic dialogue with a subtle natural room tone; the dialogue takes priority over the "
    "quiet ambience, and there is no music.\n"
    "Shot 3 (silent; the movie's one deliberate static hold; opens on: The old fishmonger "
    "stands behind the zinc counter at frame centre, facing forward, her face filling the "
    "frame from chin to brow; ends on: The old fishmonger rests her forehead on her folded "
    "hands at frame centre, eyes closed, her head and hands filling the frame in a close-up): "
    "The shot is a close-up. The old fishmonger lowers her forehead onto her folded hands on "
    "the cold zinc counter at real-time speed, her breath fogging the metal as a thin trickle "
    "of meltwater runs past her knuckles and drips to the wet floor. The camera stays static, "
    "holding the old fishmonger as she rests her forehead on her folded hands at frame centre, "
    "eyes closed, her head and hands filling the frame. The audio is the natural ambient sound "
    "of the place, with no music.\n"
    "\n")
```

It is 618 words and 3538 characters, with sha256 `fec731a3cedadf6578a511e10d93698039ad075729b208bed2903061faa8b12b`. Its preamble single-quotes the pipeline's sentences, so its only double-quoted spans are the two spoken lines (final review F1).
- It costs about 280 more prompt tokens than the `574303a` text (2406 characters) per chained or shots writer call.
- It has no `@@`, no `{`, no "slowly", one `ACOUSTIC_SENTENCE` and two `AMBIENCE_SENTENCE`.

**Its parts.** Each `Shot N` text (after `"): "`) equals `character_lib.panel_prompt(motion, shot, speaker, line, "beats", ["the old fishmonger"])`, computed on `574303a`'s `character_lib.py`:

| Shot | `shot` | `motion` (the `story.md` Motion field) | `speaker` | `line` |
|---|---|---|---|---|
| 1 | `The shot is a medium shot.` | `The old fishmonger drags a tall stack of empty herring crates across the wet concrete of the market hall toward the half-open shutter at real-time speed, her heavy steps splashing through shallow puddles that hold the first glow from the harbour doors. The camera tracks right alongside her — as the move completes, the old fishmonger stands beside the half-open shutter at frame centre, facing left toward the hall, seen from the knees up, the empty crates at her feet.` | `None` | `""` |
| 2 | `The shot is a medium shot.` | `The old fishmonger turns back from the shutter and walks to the zinc counter at real-time speed, laying her folded cloth beside the empty ice trays and lifting her face to the camera. The old fishmonger presses both palms flat on the folded cloth, her shoulders sinking. The camera pushes in — as the move completes, the old fishmonger stands behind the zinc counter at frame centre, facing forward, her face filling the frame from chin to brow. The old fishmonger faces the camera.` | `"the old fishmonger"` | `"Forty years of mornings. Not one more."` |
| 3 | `The shot is a close-up.` | `The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter at real-time speed, her breath fogging the metal as a thin trickle of meltwater runs past her knuckles and drips to the wet floor. The camera stays static, holding the old fishmonger as she rests her forehead on her folded hands at frame centre, eyes closed, her head and hands filling the frame.` | `None` | `""` |

The Motion fields are 80, 83 and 68 words, inside `WORD_RANGES` (55, 105). Verified on `574303a`:
- `camera_problem` is None for keys `slow push-in` (shot 2) and `static` (shot 3); CE1 adds `slow tracking right` for shot 1.
- `post_line_sentences` of shot 2 is exactly the reaction sentence.
- No sentence matches `EXIT_RE` or `DIALOGUE_RE`.
- N3 finds nothing in shots 2 and 3.

**N22 constants.**
- `REFERENCE_TERMS` gains `"half-open shutter"` as its last item.
- `REFERENCE_COPY_SEGMENTS` becomes:
  ```python
  REFERENCE_COPY_SEGMENTS = (
      "The old fishmonger drags a tall stack of empty herring crates across the wet concrete of "
      "the market hall toward the half-open shutter",
      "her heavy steps splashing through shallow puddles that hold the first glow from the "
      "harbour doors",
      "The old fishmonger turns back from the shutter and walks to the zinc counter",
      "laying her folded cloth beside the empty ice trays",
      "The old fishmonger presses both palms flat on the folded cloth, her shoulders sinking",
      "The old fishmonger lowers her forehead onto her folded hands on the cold zinc counter",
      "her breath fogging the metal as a thin trickle of meltwater runs past her knuckles and "
      "drips to the wet floor",
      "Forty years of mornings. Not one more.",
  )
  ```
- `REFERENCE_SIX_GRAMS` keeps its formula, which now gives 80 runs.
- Every segment but the last is a substring of `FORMAT_REFERENCE`. On `574303a`, no `REFERENCE_SIX_GRAMS` or `PLAN_REFERENCE_SIX_GRAMS` run, and no `REFERENCE_TERMS` term, occurs in any file under `tests/fixtures/` (also none of the runs in any other `tests/` file except `tests/test_shot_format.py`).

**`reference_copies` (`:2574-2578`).**
- Its `own` list gains `+ [b.get("end_frame") or "" for b in plan["beats"]]` after the beat actions.
- Its docstring's `beat actions)` becomes `beat actions and end frames; chained end frames spec CE11)`.

### CE12. Check ids

- `GENERATION_CHECKS` (`:3485-3487`) becomes `(..., "T3", "N20", "N21", "N22", "N23", "Q1", "N19")`. The slices `[16:20]`, `[-2:]` and `[-1]` are unchanged.
- `RECHECK_IDS` (`:4819-4820`) becomes `("N1", "N2", "N3", "N4", "N7", "N8", "N9", "N10", "N11", "N12", "N14", "N15", "N16", "N17", "N18", "T1", "T2", "T3", "N23", "Q1", "N19")`. `[14:18]` and `[-2:]` are unchanged.
- `PLAN_FREE_IDS`, `FORMAT_IDS` and `REPAIR_IDS` are unchanged.

---

## 3. `bin/seam-report` (CE13)

**File.** `bin/seam-report`, mode 0755, `#!/usr/bin/env python3`, stdlib only, compiles under `/usr/bin/python3` (3.9). `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))`. It loads `story_engine.py` by path (`importlib.machinery.SourceFileLoader("story_engine_for_seam_report", ...)`) lazily, on the first reply it parses, and only for `extract_json`; the nothing-to-check, no-clips and precondition paths never load it. It writes nothing except the two report files.

**CLI.** `bin/seam-report STORY_ID [--port N]`.
- `STORY_ID` must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$` and contain no `..`; otherwise exit 2 with `Error: invalid story id: <id>`.
- `--port` defaults to `STORY_SERVER_PORT`, else 8177 **[spec choice: the variable `bin/story-server` reads]**. Its type is `_port`, an int; any other text raises `argparse.ArgumentTypeError("%r is not an integer (from --port or STORY_SERVER_PORT)" % text)`. The default is the string `os.environ.get("STORY_SERVER_PORT") or "8177"`, and argparse applies the type to a string default, so a non-integer `STORY_SERVER_PORT` is a usage error when `--port` is not given (Task 5 fix round 1, M3).
- Argparse usage errors exit 2.
- **The embed port.** A port equal to `EMBED_PORT` (8178), from either source, is refused before anything else, with no connection: exit 2 `Error: port 8178 is the embed server's port, not the story server's; nothing was changed. Pass --port with the story server's port (8177 by default) or unset STORY_SERVER_PORT.` This follows `movie_ui_lib.py:617-618` (fix round 1, I2).

**Constants.**
```python
SCHEMA = "ltx-movie.seam-report.v1"
MISS_BELOW = 6          # a score below 6 is "missed" (notes, Section 3)
ATTEMPTS = 3            # VLM calls per panel before "unparseable"
MAX_TOKENS = 600         # character_dataset.vlm_call's value, with thinking switched off
TEMPERATURE = 0
CALL_TIMEOUT_S = 300
MODELS_TIMEOUT_S = 10
MAX_BODY = 1048576
VERDICTS = ("ok", "missed", "no clip", "unparseable")
EMBED_PORT = 8178       # the embed server's port: never contacted (movie_ui_lib.py:617-618)
TEXT_MODEL_ID = "qwen38-6bit"   # bin/story-server:41 MODEL_ID, served by its text mode (:493)
```

**Order of work** (the first exit wins):
1. Resolve `story_dir = WS/generated/stories/<id>`, `clips_dir = <story_dir>/clips`, `plan.json`. No story directory: exit 2 `Error: no story <id> in <WS>/generated/stories`.
2. Read `plan.json`. It must be a dict with `schema == "ltx-movie.plan.v1"`, a string `mode` and a list `beats`. Otherwise exit 2 with `Error: <path> is not a plan.json written by bin/ltx-movie's default story engine`.
3. `mode != "chained"`: print `seam-report: nothing to check: <id> is a <mode> story; seams are checked only in chained stories` and exit 0.
4. No beat has a non-empty string `end_frame`: print `seam-report: nothing to check: this plan has no end frames; no seam report` and exit 0.
5. **Frame sources.** For every beat k (1-based, N beats) with an end frame:
   - `seed = clips/panel_%02d.chainseed.png % (k + 1)` when k < N, and `clip = clips/panel_%02d.mp4 % k`.
   - The source is the **chainseed** when the seed is a non-empty file and (the clip is missing, or `mtime(seed) >= mtime(clip)`).
   - Else it is the **clip** when the clip is a non-empty file.
   - Else there is none, and the verdict is `no clip` with reason `clips/panel_%02d.mp4 does not exist`.
   - The last panel always comes from its clip.
   - No panel has a source: print `seam-report: no clips to check in <clips_dir>` and exit 0. No server is contacted and no file is written.
6. A clip source exists but `shutil.which("ffmpeg")` or `shutil.which("ffprobe")` is None: exit 2 `Error: ffmpeg and ffprobe must be on PATH to read the clips in <clips_dir>`.
7. **Probe.** `vlm_models(port)` is `GET /v1/models`, with timeout `MODELS_TIMEOUT_S`.
   - It needs a 200 reply whose `data` is a list.
   - **The loaded model** (fix round 1, C1). `mlx_vlm.server` lists every cached model and flags the active one `"loaded": true`. When any `data` entry has a `loaded` key, `model` is the string `id` of the first entry whose `loaded` is `True` (`bin/story-server:130-139`). When none is, `<what>` is `no model loaded`.
   - When no entry has a `loaded` key, `data` must be non-empty with a string `data[0]["id"]`, and `model = data[0]["id"]`.
   - Anything else: exit 2 with `Error: the story server is not answering at 127.0.0.1:<port> (<what>); nothing was changed. Start it with bin/story-server mlx-vision and rerun bin/seam-report <id>.`
   - `<what>` is `HTTP <n>`, `invalid JSON`, `no model listed`, `no model loaded`, or the exception class name.
   - **The text model** (fix round 1, I1). `model == TEXT_MODEL_ID` is refused with exit 2: `Error: the story server at 127.0.0.1:<port> serves qwen38-6bit, the text model, not a vision model; nothing was changed. Switch it with bin/story-server stop, then bin/story-server mlx-vision, and rerun bin/seam-report <id>.`
     - `TEXT_MODEL_ID` is `bin/story-server`'s `MODEL_ID` default (`:41`), which its `text` mode serves (`--model-id`, `:493`), and `bin/qwen-agent`'s `DEFAULT_MODEL` (`:52`).
     - Its vLLM `vision` mode serves the same alias (`--served-model-name`, `:475`), so `/v1/models` cannot tell the two modes apart and both are refused. `mlx-vision` serves its model path (`:812`) and passes. It is the mode every seam-report message names, and the movie UI's `VLM_MODE` (`movie_ui_lib.py:388`).
     - No other process is run and no other connection is made.
8. **Per panel**, in panel order:
   - **Frame.** A chainseed's bytes are read directly; an `OSError` while opening or reading a frame gives the verdict `no clip`, with reason `cannot read <frame>: <exception class name>` and attempts 0 (fix round 1, M2). A clip is read with `last_frame_png(clip, out_png)` into `tempfile.mkdtemp(prefix="seam-report-")`, which is removed in a `finally`.
   - **Extraction.** `last_frame_png` runs `ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of json <clip>` (count n from `nb_read_frames`), then `ffmpeg -v error -nostdin -y -i <clip> -vf select=eq(n\,<n-1>) -fps_mode passthrough -frames:v 1 <out_png>`. Both use `capture_output=True` and timeout 120.
   - **Bad clip.** A non-zero exit, unreadable output, n < 1 or no output file raises `SeamError(detail)`. The panel's verdict is then `no clip`, with reason `cannot read the last frame of clips/panel_%02d.mp4: <detail>`.
   - **Call.** `vlm_complete(port, model, prompt, png_bytes)` is called up to `ATTEMPTS` times. Each call is one `POST /v1/chat/completions` with timeout `CALL_TIMEOUT_S`, reading at most `MAX_BODY` bytes. Its body is:
     ```json
     {"model": "<model>", "max_tokens": 600, "temperature": 0,
      "chat_template_kwargs": {"enable_thinking": false},
      "messages": [{"role": "user", "content": [
        {"type": "text", "text": "<prompt>"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,<b64>"}}]}]}
     ```
   - **Transport failure.** `OSError`, `http.client.HTTPException` or a non-200 status: stop at once and exit 2 with `Error: the story server stopped answering at 127.0.0.1:<port> (<what>) while checking panel <k>; nothing was written. Start it with bin/story-server mlx-vision and rerun bin/seam-report <id>.`
   - **Reply.** A 200 reply gives `content = choices[0]["message"]["content"]`. A body that is not JSON, or a missing or non-string content, counts as an unparseable attempt. `parse_reply(content)`:
     - removes every `(?s)<think>.*?</think>`;
     - runs `extract_json`;
     - accepts the object only when `score` is an int (not bool) in 1..10, `reason` is a string that is non-empty after `" ".join(reason.split())`, and `missing` is a list of strings;
     - stores the whitespace-collapsed reason and the stripped non-empty `missing` items.
     - Else the attempt is unparseable.
   - **Verdict.** `ok` when the score is ≥ `MISS_BELOW`, else `missed`. After `ATTEMPTS` unparseable attempts the verdict is `unparseable`, with score null, reason `the model gave no valid reply in 3 attempts` and missing `[]`.
9. `write_reports` writes the pair (fix round 1, M1):
   - it writes `seam_report.json` and then `seam_report.md`, each to `<path>.tmp`;
   - then, after checking that neither path is a directory (else `IsADirectoryError("<path> is a directory")`), it `os.replace`s each `.tmp` into place;
   - a failure before the replaces leaves the old pair byte for byte. An `OSError` or `ValueError` (a lone surrogate in a reply: final review F2) at any step removes every `.tmp` this run created and still present, then exits 1 with `Error: cannot write <path>: <e>`, naming the path that failed.
10. Print one line per panel, then the summary line (below), and exit 0.

**VLM prompt** (`seam_prompt(plan, k)`; `@@K@@`, `@@END_FRAME@@` and `@@CHARACTERS@@` replaced in that order with `str.replace`):

```python
SEAM_PROMPT = (
    "This image is the last frame of panel @@K@@ of a movie. The story plan says the panel ends "
    "on this frame:\n@@END_FRAME@@\n@@CHARACTERS@@\n"
    "Score how well the image matches the planned end frame, from 1 (nothing matches) to 10 "
    "(everything matches). Judge only who or what is in frame, where each one is (left, centre "
    "or right; foreground or background), which way they face and how tight the shot is; ignore "
    "image quality, lighting, colour and style.\n"
    "Reply with one JSON object only, with exactly these keys: score (an integer from 1 to 10), "
    "reason (one sentence of at most 25 words) and missing (a list of the short phrases of the "
    "planned end frame that the image does not show, or an empty list).")
```

- `@@CHARACTERS@@` is `Characters in this panel: ` + `"; ".join("'%s' is %s" % (phrase, descriptor) …)` (each phrase in single quotes: double quotes are kept for spoken lines; final review I2) + `.` over the plan cast entries whose id is in the beat's cast, in cast order, or `""` when there are none **[spec choice: the VLM cannot map a referring phrase to a person without its description]**.

**`seam_report.json`:**
```json
{"schema": "ltx-movie.seam-report.v1", "story_id": "<id>", "created": "<UTC %Y-%m-%dT%H:%M:%SZ>",
 "model": "<model>", "threshold": 6,
 "panels": [{"panel": 1, "end_frame": "<text>", "source": "chainseed" | "clip" | null,
             "frame": "clips/panel_02.chainseed.png" | "clips/panel_01.mp4" | null,
             "score": 8 | null, "verdict": "ok" | "missed" | "no clip" | "unparseable",
             "reason": "<text>", "missing": ["<text>"], "attempts": 0..3}],
 "summary": {"panels": 3, "scored": 2, "ok": 1, "missed": 1, "no_clip": 1, "unparseable": 0,
             "mean_score": 6.5 | null}}
```
- `panels` lists every beat with an end frame, in order.
- `attempts` is 0 for `no clip`.
- `mean_score` is `round(mean of the scored panels' scores, 2)`, or null when none is scored.
- The file is written with `json.dumps(doc, indent=2, ensure_ascii=False) + "\n"`.
- `created` comes from a module-level `_utc` function (tests replace it).

**`seam_report.md`** (every table cell has `|` replaced with `\|` and its whitespace collapsed; a null score or empty `missing` is `-`; `<mean>` is `str(mean_score)`, or `n/a` when it is null):

```
# Seam report: <id>

Created <created> with <model>. A score below 6 is missed.

| Panel | Score | Verdict | Reason | Missing |
|---|---|---|---|---|
| 1 | 8 | ok | <reason> | - |
| 2 | 4 | missed | <reason> | <missing joined with "; "> |

Mean score <mean> over <scored> scored panel(s); <missed> missed, <no_clip> without a clip, <unparseable> unparseable.

## Planned end frames

- panel 1: <end frame>
- panel 2: <end frame>
```

**stdout.**
- One line per panel:
  - `panel <k>: ok (<s>/10): <reason>`
  - `panel <k>: missed (<s>/10): <reason>; missing: <a; b>` (the `; missing: …` part only when the list is non-empty)
  - `panel <k>: no clip: <reason>`
  - `panel <k>: unparseable: <reason>`
- Then: `seam-report: wrote <json path> and <md path>: <missed> of <panels> panel(s) missed, mean score <mean or n/a>`.

**Exit codes:**
- 0: report written, nothing to check, or no clips to check.
- 1: a report file cannot be written.
- 2: usage error, invalid story id, no story, invalid plan, ffmpeg or ffprobe missing, or the story server not answering (probe or mid-run).

**Module functions (tests call them):** `main(argv=None)`, `build_parser()`, `frame_sources(plan, clips_dir)` (→ `[(k, end_frame, source, path)]`), `last_frame_png(clip, out_png)`, `vlm_models(port)` (→ `(model, None)` or `(None, what)`), `vlm_complete(port, model, prompt, png)` (→ the reply's content string, or None when a 200 reply has none or is not JSON; raises `TransportError(what)` on a transport failure), `seam_prompt(plan, k)`, `parse_reply(content)` (→ dict or None), `render_md(doc)`, `_utc()`, `SeamError`, `TransportError`. `if __name__ == "__main__": sys.exit(main())`.

---

## 4. Movie UI (CE14, CE15)

### CE14. `movie_ui_lib.py` and `movie_ui_server.py`

**`movie_ui_lib.py`.**
- `job_vlm` (`:424`): the first tuple gains `"seams"`, so `job_vlm("seams", …) == "required"`. This is the existing VLM-needed policy: the preflight restores the VLM before the job, and the postflight follows [VLM].
- Add immediately after `effective_vlm`:
  ```python
  # Chained end frames spec CE14: the seams job and the plans that have something to check.
  def seams_argv(ws_real, story_id, py=sys.executable):
      """The bin/seam-report argv of a seams job, on the port the VLM preflight checks."""
      return [py, os.path.join(ws_real, "bin", "seam-report"), story_id, "--port", str(vlm_port())]


  def plan_has_end_frames(plan):
      """True when plan (a parsed plan.json, or None) is chained and a beat has a non-empty string
      end_frame. Pure."""
      beats = plan.get("beats") if isinstance(plan, dict) else None
      return (isinstance(plan, dict) and plan.get("mode") == "chained" and isinstance(beats, list)
              and any(isinstance(b, dict) and isinstance(b.get("end_frame"), str)
                      and b["end_frame"].strip() for b in beats))
  ```
- The kind is `"seams"`. Its `fields` are `{"ws": <ws_real>, "story_id": <id>}`, plus `"after": <movie job ID>` when Compose's `check_seams` created it (Task 6 fix round 1, review I1). `DEFAULT_FIELDS` is unchanged ([BF] BT1). Its progress is the generic snapshot (`:2219-2221`); `job_phases` is not used for it.
- **The `after` rule** (fix round 1). `seams_skip_reason(state, job, queue)`, placed after `plan_has_end_frames`, reads only status files, the queue and the story's `plan.json`. It returns None unless `job` is a seams job whose `fields["after"]` is a string, and also None when that job's `job_state` is `done` and the story's `plan.json` (read with `read_json`) has end frames (`plan_has_end_frames`; final review I1). Otherwise it returns the reason:
  - `skipped: movie <id> has not run yet` (queued);
  - `skipped: movie <id> no longer exists` (unknown);
  - `skipped: movie <id> ended <state>` (failed, cancelled or lost);
  - `skipped: story <id> has no end frames to check` (the movie ended done, but its plan has no end frames: an old story re-rendered, end frames dropped, or a workspace whose engine predates end frames and has no `bin/seam-report`). No lock, subprocess or VLM step is added.
- **`dispatch_tick`**, after its workspace check and before the `starting` status, cancels such a job:
  - it appends `[movie-ui] <reason>` to its `log.txt`;
  - it writes `{"state": "cancelled", "exit_code": null, "ended": <now>, "error": <reason>}`;
  - it drops the job from the queue and goes on to the next queued job in the same tick.

  No runner, preflight, VLM step or subprocess starts for it. A job cannot be running when dispatch reaches the seams job, because the tick returns early while one is active. So `after` is then finished, missing, or still queued behind it: a user moved the seams job up, and the job is skipped rather than run ahead of its movie.
- **`next_queued_job`** passes over a job that `seams_skip_reason` skips, so `vlm_restore_wanted` and the postflight never restore the VLM for a seams job that will not run.
- Both read job records the way the dispatcher already does, under `STORE_LOCK` (the dispatcher) or lock-free from the runner (the postflight). `BATCH_LOCK` is never taken.

**`movie_ui_server.py`.**
- **Route.** Append right after the `PUT …/story\.md` route (`:106`): `("POST", r"/api/stories/" + _STORY + r"/seams", "h_story_seams", "/api/stories/ronin-rescue/seams")`. Register `MovieUIHandler.h_story_seams = _h_story_seams` next to `h_story_save` (`:1878`). The route count is the merged base's count plus one; it is read from the merged base at implementation time (54 + 1 = 55 if [BF] lands as specified). No tab is added.
- **Helper** (caller holds `STORE_LOCK`):
  ```python
  def _create_seams_job(state, real, story_id, after=None):
      """Create and queue the seams job of story_id; returns its ID (CE14). after, the ID of the
      movie job it checks (Compose's check_seams), joins its fields; dispatch_tick skips the job
      unless that movie ended done (lib.seams_skip_reason)."""
      job_id = lib.new_job_id(state)
      fields = {"ws": real, "story_id": story_id}
      if after is not None:
          fields["after"] = after
      lib.create_job(state, job_id, "seams", real, story_id, None, lib.seams_argv(real, story_id),
                     fields)
      return job_id
  ```
- **`create_compose_job(server, fields, seams=False)`.** The signature gains `seams=False`. In the non-smoke branch, inside the same `with STORE_LOCK:` and right after the compose job is created, it calls `_create_seams_job(state, real, fields["story_id"], after=job_id)` (`job_id`: the movie's; Task 6 fix round 1) when `seams and fields["action"] == "movie" and fields["mode"] == "chained"`. It still returns the compose job's ID, so other callers ([BF]) are unchanged.
- **`_h_job_create`.** `create_compose_job(self.server, fields)` becomes `create_compose_job(self.server, fields, seams=isinstance(body, dict) and body.get("check_seams") is True)`. The response shape is unchanged.
- **`_h_story_seams(self, groups, query, body)`:**
  1. `real, story_id, sdir = _story_dir(self, groups, body.get("ws"))` (404 `no story <id> in <dir>`).
  2. If `not lib.plan_has_end_frames(_json_in(sdir, os.path.join(sdir, "plan.json")))`, raise `ApiError(409, "story %s has no end frames to check" % story_id)`.
  3. Under `STORE_LOCK`: if some job has kind `seams`, `workspace == real`, `story_id == story_id` and `lib.job_state(state, job_id, queue)` in `("queued",) + lib.ACTIVE_STATES`, raise `ApiError(409, "a seams check of %s is already queued as job %s" % (story_id, job_id))`. Otherwise `job_id = _create_seams_job(...)`.
  4. Return `201, {"job": job_summary(self.server, job_id, lib.read_queue(self.server.state))}`.
- **`_h_story`** gains two keys: `"end_frames": lib.plan_has_end_frames(plan)` (`plan` is the dict it already reads) and `"seams": _json_in(sdir, os.path.join(sdir, "seam_report.json"))`.

### CE15. `static/movie-ui/`

**`index.html`:**
- After the `c-run-all` line (`:135`): `    <label id="c-check-seams-box"><input id="c-check-seams" type="checkbox" checked> Check seams after render</label>`
- After the `s-regenerate` line (`:155`): `      <button id="s-seams" type="button" hidden>Check seams</button>`
- After `<div id="s-checks"></div>` (`:160`):
  ```html
      <div id="s-seams-box" hidden>
        <h3>Seams</h3>
        <p id="s-seams-summary" class="muted"></p>
        <table id="s-seams-table" class="list"><thead><tr><th>Panel</th><th>Score</th><th>Verdict</th><th>Reason</th></tr></thead><tbody></tbody></table>
      </div>
  ```

**`app.js`:**
- `updateComposeButtons` gains, as its last line: `show($("#c-check-seams-box"), mode === "chained");`.
- The Run all handler (`:576`) becomes:
  ```js
  $("#c-run-all").addEventListener("click", function () {
    S.composeAction = "movie";
    submit(Object.assign(composeFields("movie"),
                         {check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked}));
  });
  ```
- New function, placed right before `openStory`:
  ```js
  function showSeams(data) {
    const chained = data.plan_mode === "chained";
    show($("#s-seams"), Boolean(data.end_frames));
    show($("#s-seams-box"), chained);
    const body = clear($("#s-seams-table tbody"));
    const report = data.end_frames ? data.seams : null;
    show($("#s-seams-table"), Boolean(report));
    if (!chained) { return; }
    if (!data.end_frames) { $("#s-seams-summary").textContent = "This plan has no end frames; no seam report."; return; }
    if (!report) { $("#s-seams-summary").textContent = "No seam report yet: press Check seams."; return; }
    const s = report.summary || {};
    $("#s-seams-summary").textContent = "Mean score " + (s.mean_score === null || s.mean_score === undefined ? "n/a" : s.mean_score)
      + " over " + s.scored + " scored panel(s); " + s.missed + " missed (a score below " + report.threshold + ").";
    (Array.isArray(report.panels) ? report.panels : []).forEach(function (p) {
      if (!p || typeof p !== "object") { return; }
      body.appendChild(el("tr", {cls: p.verdict === "missed" ? "seam-missed" : ""}, [
        el("td", {text: String(p.panel)}), el("td", {text: p.score === null ? "-" : String(p.score)}),
        el("td", {text: p.verdict}), el("td", {text: p.reason})]));
    });
  }
  ```
- The last line of `openStory` is followed by `showSeams(res.data);`.
- `setupStories` gains:
  ```js
  $("#s-seams").addEventListener("click", async function () {
    const res = await api("POST", "/api/stories/" + enc(S.story.id) + "/seams", {ws: S.ws});
    $("#s-action-status").textContent = res.status === 201 ? "seams check queued as job " + res.data.job.id
      : ((res.data && res.data.error) || ("http " + res.status));
    if (res.status === 201) { pollJobs(); }
  });
  ```

**`app.css`:** add `.seam-missed td { background: var(--warn-bg); }`.

The [MUI] page rules still hold: no inline handlers or styles, no `prompt(`/`alert(`/`confirm(`/`eval(`, one `<script>`, and the `TABS` line is unchanged.

---

## 5. Errors and messages

| ID / where | Severity | Exact text | Effect |
|---|---|---|---|
| P22 missing (plan retry block) | hard, re-ask | `beat K: P22 end frame: end_frame is missing or empty; write one sentence of 8 to 30 words of the frame this beat ends on: who or what is in frame, where (left, centre or right; foreground or background), which way they face and how tight the shot is` | plan call 2; never in a state |
| P22 length | hard, re-ask | `beat K: P22 end frame: end_frame is W words; write one sentence of 8 to 30 words` | as above |
| P22/P24 exhaustion (stdout) | warning | `Warning: end frames dropped after N attempts; this story has no seam report` | end frames removed; run continues |
| P23 cast | advisory | `beat K: P23 end frame content: names 'P', who is not in beat K's cast` | `story_checks.json` |
| P23 camera | advisory | `beat K: P23 end frame content: says 'W'; an end frame describes the frame, never a camera move` | same |
| P23 style | advisory | `beat K: P23 end frame content: says 'W'; an end frame never describes appearance, clothing, setting, lighting, colour or style` | same |
| P23 speech | advisory | `beat K: P23 end frame content: says 'W'; an end frame has no spoken words` | same |
| P23 quote | advisory | `beat K: P23 end frame content: contains a double quote; double quotes are kept for spoken lines` | same |
| P24 | hard, re-ask | `plan: P24 reference copy: WHERE copies the plan reference ('h1', 'h2', 'h3'); write only this movie's own people, places, objects and words` | call 2; after it, end frames only: drop; elsewhere: exit 1 with the usual "did not return a usable plan" block |
| N23, round 0 | hard (one re-ask) | `panel K: N23 end frame landing: Motion: DETAIL` | the re-ask's fix block |
| N23, states and recheck | advisory | same text | never blocks |
| N23 details | — | (a) `has no camera sentence whose words after 'as the move completes,' (or after 'holding' for a static camera) describe the planned end frame 'E'`; (b) `the camera sentence ends 'C', which does not name 'P', whom the planned end frame 'E' names`; (c) `the camera sentence ends 'C', which shares S of the N content words of the planned end frame 'E'; it needs at least M` | first that applies |
| seam-report | exit 0 | `seam-report: nothing to check: ID is a MODE story; seams are checked only in chained stories` | no write |
| seam-report | exit 0 | `seam-report: nothing to check: this plan has no end frames; no seam report` | no write |
| seam-report | exit 0 | `seam-report: no clips to check in CLIPS` | no write, no server contact |
| seam-report | exit 2 | `Error: invalid story id: ID` / `Error: no story ID in DIR` / `Error: PATH is not a plan.json written by bin/ltx-movie's default story engine` / `Error: ffmpeg and ffprobe must be on PATH to read the clips in CLIPS` | no write |
| seam-report | exit 2 | `Error: the story server is not answering at 127.0.0.1:PORT (WHAT); nothing was changed. Start it with bin/story-server mlx-vision and rerun bin/seam-report ID.` | no write |
| seam-report | exit 2 | `Error: the story server stopped answering at 127.0.0.1:PORT (WHAT) while checking panel K; nothing was written. Start it with bin/story-server mlx-vision and rerun bin/seam-report ID.` | no write |
| seam-report | exit 2 | `Error: port 8178 is the embed server's port, not the story server's; nothing was changed. Pass --port with the story server's port (8177 by default) or unset STORY_SERVER_PORT.` | no connection, no write |
| seam-report | exit 2 | `Error: the story server at 127.0.0.1:PORT serves qwen38-6bit, the text model, not a vision model; nothing was changed. Switch it with bin/story-server stop, then bin/story-server mlx-vision, and rerun bin/seam-report ID.` | no write |
| seam-report | exit 2 | `seam-report: error: argument --port: 'TEXT' is not an integer (from --port or STORY_SERVER_PORT)` (after the usage line) | no write |
| seam-report | exit 1 | `Error: cannot write PATH: E` | the old pair unchanged, no `.tmp` of this run left |
| seam-report verdicts | — | `no clip` reasons `clips/panel_NN.mp4 does not exist` / `cannot read the last frame of clips/panel_NN.mp4: D` / `cannot read FRAME: EXCEPTION`; `unparseable` reason `the model gave no valid reply in 3 attempts` | in the report |
| a check_seams job at dispatch | cancelled | `skipped: movie J has not run yet` / `skipped: movie J no longer exists` / `skipped: movie J ended STATE` / `skipped: story ID has no end frames to check` | status `error` and one `[movie-ui] ` log line; no runner |
| `POST /api/stories/<id>/seams` | 404 / 409 / 409 | `no story ID in DIR` / `story ID has no end frames to check` / `a seams check of ID is already queued as job J` | — |
| Stories tab | text | `seams check queued as job J`, `This plan has no end frames; no seam report.`, `No seam report yet: press Check seams.`, `Mean score X over N scored panel(s); M missed (a score below 6).` | — |

---

## 6. Tests

**Conventions** (as `tests/test_shot_format.py`):
- stdlib plus pytest;
- modules loaded by path with `SourceFileLoader` under `story_engine_for_chained_end_frames`, `character_lib_for_chained_end_frames`, `ltx_story_manifest_for_chained_end_frames`, `seam_report_for_tests`;
- the autouse `story_env` and `ws` fixtures; `seu.script_agent` for every E2E; `movie_ui_testutil` (`set_home`, `make_stub_workspace`, `Running`, `api`) for the UI, with `MOVIE_UI_VLM_LIFECYCLE=0`.

Each module docstring states that no test renders, reads the real HOME, or contacts a model server, a daemon, ffmpeg or the Anthropic API. The only server is the in-test 127.0.0.1 movie-UI server. The VLM, the LLM and ffmpeg are stubbed by monkeypatching `vlm_models`, `vlm_complete`, `last_frame_png` and `shutil.which`.

**Test data:**
- `REF_NARRATIVE = 'At dawn the old fishmonger drags her empty herring crates to the shutter of the market hall. At the zinc counter she says, "Forty years of mornings." After a breath she says, "Not one more." She rests her head on her folded hands.'`
- `ref_ctx(ws, **kw)` = `seu.make_ctx(se, ws, mode="chained", panels=3, narration="speech", clip_seconds=145 / 24.0, narrative=REF_NARRATIVE, auto_lora=False, **kw)`.
- `EF_PLAN(n)` = `seu.plan_json("chained", n)` with beat k's `end_frame` = `"The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up, beat %d."` (20 words; its content words are those 11 of CT10).

| ID | File | Covers (exact assertions) |
|---|---|---|
| CT1 | `tests/test_chained_end_frames.py` | **Constants.** `CAMERA_SENTENCES`, `CAMERA_KEYS`, `PLAN_CAMERA_KEYS`, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS`, `CAMERA_MOVE_WORDS`, the 5 new `CAMERA_WRITER_FORMS` entries, `END_FRAME_RULE`, `OPENS_ON_LINE`, `ENDS_ON_LINE`, `ENDS_ON_STATIC_LINE`, `PLAN_REFERENCE_INTRO`, `PLAN_REFERENCE_LINES_CLAUSE`, `PLAN_REFERENCE_KEY_WORDS`, `END_FRAME_STOP_WORDS`, `END_FRAME_WORDS`, `P22_MISSING`, `P22_LENGTH`, `P24_MESSAGE`, `END_FRAMES_DROPPED`, `REFERENCE_TERMS[-1] == "half-open shutter"`, `REFERENCE_COPY_SEGMENTS`, `GENERATION_CHECKS`, `RECHECK_IDS` equal the CE literals written out in the test. `set(CAMERA_WRITER_FORMS) == set(CAMERA_KEYS) == set(CAMERA_MOVE_WORDS)`. For every key, its sentence and its form (`<…>` → `x`) are camera sentences, `_names_camera` holds and `_mixed_camera` does not. `"slowly"` is in no new or changed string, including `plan_reference(True)` and `FORMAT_REFERENCE`. `py_compile` of `story_engine.py`, `bin/seam-report`, `movie_ui_lib.py` and `movie_ui_server.py` under `sys.executable` and `/usr/bin/python3` (skip when absent) |
| CT2 | same | **PLAN_REFERENCE.** The three sha256/char/word rows of CE5; `len(PLAN_REFERENCE_SIX_GRAMS) == 68`. `json.loads(plan_reference(True).split("\n", 1)[1]) == PLAN_REFERENCE_PLAN`; the `False` variant equals the plan with every beat's `lines` deleted. `normalize_plan(ref_ctx(ws), …)` + `plan_checks` give hard `[]` and an advisory list with no P8, P22, P23 or P24 (narration `"speech"` and `True`); `plan_end_frame_problems == []`; `line_assignment_problems == []`. Failing case: `plan_copy_problems(ref_ctx(ws, narrative="A courier delivers a letter."), plan)` is non-empty, every message starts with `"plan: P24 reference copy: "`, and the first is for `the logline` (the title has no term and no key-word run) |
| CT3 | same | **Plan prompt.** Chained, `LINES_NARRATIVE`, `"speech"`: contains `"with the keys index, arc, action, shot, camera, location, cast, speaker, lines and end_frame."`, `LINES_RULE` text immediately followed by `END_FRAME_RULE + "\n"`, `"camera is exactly one of: slow push-in, slow pull-back, slow tracking left, slow tracking right, handheld, slow pan left, slow pan right, slow tilt up, slow tilt down, slow crane up, slow crane down, slow orbit, static."`, and ends with `plan_reference(True) + NO_TOOL_SENTENCE`. Chained, no quoted lines: `"cast, speaker and end_frame."` and `plan_reference(False)`. Chained, `narration=False`: `END_FRAME_RULE` present, `"FORMAT REFERENCE ONLY"` absent. Shots and no_stills: no `end_frame`, no `"FORMAT REFERENCE ONLY"`, the same camera list. Every prompt: no `"@@"`; with `plan_reference(...)` removed, no `{` or `}`. The two chained prompts with a reference hold `"FORMAT REFERENCE ONLY"` exactly once; no chained prompt holds `"8K"` |
| CT4 | same | **normalize_plan.** Chained: `"  The courier  stands …  "` → `beat["end_frame"]` collapsed; `""`, `None`, `7`, a list → no `end_frame` key. Shots and no_stills replies with `end_frame` → no key. `list(plan)` keys unchanged |
| CT5 | same | **P22.** `plan_end_frame_problems` on `EF_PLAN(3)` → `[]`; beat 2 deleted → `[P22_MISSING % 2]`; 7 words → `[P22_LENGTH % (k, 7)]`; 31 words → `P22_LENGTH % (k, 31)`; exactly 8 and 30 words pass; a shots plan → `[]` |
| CT6 | same | **P23 rows** (exact messages): `"… the old monk …"` with beat cast `["c1"]` → cast; `"The camera pushes in on the courier at frame centre facing left."` → camera `'camera pushes'`; `"The courier pans the quay …"` → camera `'pans'`; `"… lit by a lamp …"` → style `'lit'`; `"… says goodbye …"` → speech `'says'`; `'… the "closed" sign …'` → quote. Not flagged (M1 rule): `"The courier stands still at frame centre, facing left, holding the sealed letter, seen from the waist up."` and `"The old monk follows the courier …"` (old monk in cast). `PLAN_REFERENCE_PLAN`'s end frames → none |
| CT7 | same | **P24 rows.** On `EF_PLAN(3)` → `[]`. Beat 1 action `"The courier drags a tall stack of empty herring crates past the boats."` → one message for `beat 1's action` naming `'herring'` and a six-gram. Beat 2 end frame `"The courier leans on the zinc counter, facing the camera, seen from the waist up."` → one `beat 2's end frame` message naming `'zinc'`; with `end_frames=False` → `[]`; with a narrative containing `"a zinc counter"` → `[]`. A pinned member whose descriptor contains `"herring"` → exempt. `"The courier turns back into the hall and walks to the gate."` → `[]` (key-word filter). Shots ctx and `narration=False` → `[]` |
| CT8 | same | **Plan retry E2E (CK1).** (a) `plan=[answer(plan_json("chained", 3)), answer(EF_PLAN(3))]` → stages start `["plan", "plan", "panel"]`; `log[1]["argv"][-1]` contains `"YOUR PREVIOUS REPLY WAS REJECTED. Problems:\n- " + P22_MISSING % 1 + "\n"`; `plan.json` beats all have their end frames; `END_FRAMES_DROPPED` not in stdout. (b) Two replies without end frames → rc 0; stdout has `END_FRAMES_DROPPED % 2 + "\n"`; no `plan.json` beat has `end_frame`; no advisory contains `P22`. (c) Two `EF_PLAN(3)` replies whose beat 1 action is CT7's herring-crates action → rc 1; stderr contains `"  - plan: P24 reference copy: beat 1's action copies the plan reference ("`. (d) Two `EF_PLAN(3)` replies whose beat 2 end frame is CT7's zinc-counter end frame → rc 0, the warning, no end frames. (e) `EF_PLAN(3)` once → exactly one plan call. (f) `plan_json("chained", 3)`, then `EF_PLAN(3)` with beat 1 at the undefined location `l9` (P2, fatal) → rc 0; stages start `["plan", "plan", "panel"]`; stdout has `END_FRAMES_DROPPED % 2 + "\n"`; the saved plan is call 1's (every beat at `l1`) with no end frames. (g) `_Run.expired` true only at its second check (before plan call 2), replies `plan_json("chained", 3)` then `EF_PLAN(3)` → rc 0; stages start `["plan", "panel"]`; stdout has `END_FRAMES_DROPPED % 1 + "\n"`; no end frames. Every beat of every saved plan with end frames passes P22 (CK1: 100%) |
| CT9 | same | **Writer prompt.** `EF_PLAN(3)` after `cap_static_cameras` (cameras push-in, tracking, static): panel 1 contains `ENDS_ON_LINE % <ef1>` and no `"This panel opens on:"`; panel 2 contains `"The previous panel's Motion: " + <Motion 1> + "\n" + OPENS_ON_LINE % <ef1> + ENDS_ON_LINE % <ef2> + "\n" + FORMAT_REFERENCE`; panel 3 (static) contains `ENDS_ON_STATIC_LINE % <ef3>`. A plan without end frames: no `"This panel opens on:"` or `"This panel ends on:"`, and `prompt.count(FORMAT_REFERENCE) == 1`. No prompt contains `"@@"` |
| CT10 | same | **N23 detection** (`end_frame_detail`, plan `EF_PLAN(3)`, phrases `["the courier"]`), beat 2 end frame E = `"The courier stands at frame centre on the wet quay, facing the camera, seen from the waist up, beat 2."` (content words: 2, beat, camera, centre, facing, frame, quay, seen, stands, waist, wet → n 11, need 6). Rows, each prefixed `"The courier runs. "`: `"The camera tracks the movement."` → (a); `"The camera tracks him — as the move completes, he stands at frame centre on the wet quay."` → (b) naming `'the courier'`; `"The camera tracks him — as the move completes, the courier waits by a lamp."` → (c) `shares 0 of the 11 … at least 6`; `"… the courier stands at frame centre on the wet quay, facing left."` (6 shared) → None; `"… the courier stands at frame centre on the wet quay."` (5 shared) → (c); `"The camera stays static, holding the courier at frame centre on the wet quay, facing the camera."` → None; beat without end frame → None, and `end_frame_landing_problems` → `[]` for it and, with an end frame set, in shots and no_stills. The three reference Motions against `PLAN_REFERENCE_PLAN` → None |
| CT11 | same | **N23 round 0 (CK2).** Chained 2 panels, `EF_PLAN(2)`. (a) Panel 1 replies `[miss, land]`: `miss` is `seu.panel_json`'s motion; `land` is that motion plus the panel's `CAMERA_WRITER_FORMS` sentence (panel 1 is `static`, so `"The camera stays static, holding " + E1 lower-cased first letter, without its full stop + "."`), and panel 2 replies `[land2]` (its motion plus `"The camera tracks the courier — as the move completes, " + E2 lower-cased first letter, without its full stop + "."`; beat 2 is `tracking`) → stages `["plan", "panel", "panel", "panel"]`; `panel_01_prompt_2.txt` has `"- panel 1: N23 end frame landing: Motion: "`; no N23 in `story_checks.json`. (b) Panel 1 `[miss, miss]`, panel 2 `[land2]` → rc 0, panel 1 kept, advisory has `"panel 1: N23 end frame landing: Motion: "`, hard has no N23. (c) An unparseable first reply then `miss` → no third call (budget), N23 advisory. (d) `se.recheck` of the saved (b) story → rc 0, advisory N23 present, hard unchanged. (e) Writers that land on every panel → zero N23 messages (CK2). (f) Beat 1 speaks; panel 1 `[miss with "Keep moving.", land with a 15-word line (hard T1)]` → reply 1 kept: rc 0, no T1 message, one N23 advisory. (g) Panel 2 `[a 3-action Motion (hard T2), the same plus the landing sentence]` → reply 2 kept (equal hard count): no N23, T2 unresolved, the landing sentence in `story.md`. (h) Panel 2 `[a 3-action Motion (hard T2, N23), miss plus "Herring crates line the quay." (hard N22, N23)]` → reply 1 kept (more format and N23 messages at an equal hard count): one N23 advisory, T2 unresolved, no "Herring crates" in `story.md` |
| CT12 | same | **M1 (CK4).** Planned `slow push-in`: `repair_action_text(… "The ronin runs to the wall. The camera pushes in — as the move completes, the ronin stands still at the right edge.")` returns the text unchanged with no notes; `camera_problem(...)` None. `"The camera stays still and pushes in."` → `camera_problem` contains `"has the camera both stay still and move"` and the repair drops it. Static: `"The camera stays static, holding the ronin as he stands still at the right edge."` → None. A push-in whose clause says `"she holds still"` with planned `static` → `"does not move the camera the planned way"` (`_names_camera` head rule). Planned `slow orbit`, `"The ronin turns to the boats. The camera arcs around the ronin — as the move completes, …"` → `_moves_camera` and `_names_camera` true, one camera direction, `camera_problem` None, no repair, and the assembled Motion is the writer text with no second orbit sentence (final review I3) |
| CT13 | same | **Quotes (CK5).** `panel_fields` of a chained, a shots and a no_stills panel whose writer action text is `'The courier reads the "urgent" note and the “closed” sign.'` → field contains `'urgent'`, `'closed'` and no `"`, `“`, `”`; Dialogue unchanged; `panel_checks` advisory still has `"N7 dialogue and text: Motion: contains a double quote"`. Manifest E2E: a 2-panel chained speech story (panel 2 `Dialogue: the courier: Go now.`) written by `assemble` from such a writer Motion → every `motion_prompt` has exactly the double quotes of `speech_text` (`count('"') == 2` on panel 2, `0` on panel 1). For each `tests/fixtures/**/parts.json` with a sibling chained or shots `plan.json` (the four hockey fixtures), `assemble` of those parts gives Motion fields with no double quote |
| CT14 | same | **FORMAT_REFERENCE.** sha256 and `(3538, 618)` of CE11. `ref_shots()` equals `panel_prompt` of the CE11 parts table. Each shot's Motion passes `camera_problem` with keys `slow tracking right`, `slow push-in`, `static` and `end_frame_detail` against `PLAN_REFERENCE_PLAN` beats 1-3. Shot 2 and 3 labels contain the previous and this beat's end frame without its full stop. Every segment but the last is a substring; `len(REFERENCE_SIX_GRAMS) == 80`. **Corpus guard:** no `REFERENCE_SIX_GRAMS` or `PLAN_REFERENCE_SIX_GRAMS` run and no `REFERENCE_TERMS` term in any file under `tests/fixtures/`. The only double-quoted spans of `FORMAT_REFERENCE` are `"Forty years of mornings."` and `"Not one more."` (final review F1) |
| CT15 | same | **Old stories (CK3).** Copy `tests/fixtures/writer_pacing/hockey-2x145-f` into tmp, and save a chained 3-panel story assembled from `seu.plan_json` and `seu.panel_json` (no end frames). Monkeypatch `se.end_frame_words`, `se.plan_end_frame_problems`, `se.plan_copy_problems` and `se.end_frame_advisories` to raise `AssertionError`. `se.recheck` returns the same rc and the same hard and advisory lists as the same call with `"N23"` removed from `se.RECHECK_IDS`, and leaves `story.md` byte-unchanged; so the manifest, which `bin/ltx-story-manifest` (unchanged) builds from `story.md`, is unchanged too (`test_v2_golden_byte_identical` must pass unchanged) |
| CT16 | same | **Soft panel count.** Target 3, a 4-beat reply whose beat 4 has no end frame → call 2 re-asks with `P22_MISSING % 4`; a 4-beat reply with 4 end frames → one call |
| CT17 | `tests/test_seam_report.py` | **Nothing to check.** Shots plan → exit 0, the mode message; chained plan without end frames → exit 0, the no-end-frames message; chained with end frames and an empty `clips/` → exit 0, `seam-report: no clips to check in <clips>`, and `vlm_models` (patched to raise) never called; no report file in any case. Also run as a subprocess (real script in a tmp WS with `story_engine.py` symlinked) for the no-clips case: stdout exact, rc 0 |
| CT18 | same | **Preconditions.** `bad/../id` → 2; unknown story → 2; missing, non-JSON and wrong-schema `plan.json` → 2 with the message; a clip source with `shutil.which` → None → 2; no file written. Port 8178 by `--port` or `STORY_SERVER_PORT` → 2, the embed message, before the story is read; `STORY_SERVER_PORT=abc` → usage exit 2 naming `STORY_SERVER_PORT` |
| CT19 | same | **Server down.** `vlm_models` → `(None, "ConnectionRefusedError")` → exit 2, stderr exact, an existing `seam_report.json` unchanged (bytes). `vlm_complete` raising `TransportError("HTTP 503")` on panel 2 → exit 2, the stopped-answering message, nothing written. A `/v1/models` that lists only `qwen38-6bit` → 2, the text-model message, after one GET; one whose entries have `loaded` keys but none `true` → 2, the not-answering message with `no model loaded` |
| CT20 | same | **Verdicts (CK6).** 3-beat chained plan with end frames; `panel_02.chainseed.png` and `panel_03.chainseed.png` newer than clips 1-2, `panel_03.mp4` present, `last_frame_png` stubbed; replies score 8, 5, 6 → `ok`, `missed`, `ok`; sources chainseed, chainseed, clip; `seam_report.json` equals the expected dict (with `_utc` patched); `seam_report.md` equals the expected text; stdout lines exact; rc 0. A chainseed older than its clip → source `clip`. A panel with no clip and no seed → `no clip`, attempts 0. `last_frame_png` raising `SeamError("x")` → `no clip` with the reason. A chainseed that cannot be opened → `no clip`, `cannot read clips/panel_02.chainseed.png: FileNotFoundError`, no VLM call. An `.md.tmp` in the way, or `seam_report.md` a directory → exit 1 naming `seam_report.md`, the old `seam_report.json` unchanged, no `.tmp` of the run left. A reply whose reason holds a lone surrogate → exit 1 naming `seam_report.json`, the old pair unchanged, no `.tmp` left (final review F2) |
| CT21 | same | **Unparseable.** Replies `["garbage"] * 3` → `unparseable`, attempts 3; `["garbage", valid]` → `ok`, attempts 2; score 11, score `True`, empty reason, `missing` not a list → each retried; `"<think>{\"score\": 1}</think>{\"score\": 7, \"reason\": \"ok\", \"missing\": []}"` → 7 |
| CT22 | same | **Prompt and request.** `seam_prompt(plan, 2)` equals the expected text, including the `Characters in this panel: "the courier" is <COURIER>.` line; a beat with empty cast → no characters line. `vlm_complete` with `http.client.HTTPConnection` monkeypatched to a fake records `POST /v1/chat/completions`, the body keys of Section 3, `max_tokens == 600`, `temperature == 0`, `chat_template_kwargs == {"enable_thinking": false}`, and an image URL starting `data:image/png;base64,`. `vlm_models` picks the first `loaded: true` string id, answers `no model loaded` when entries carry `loaded` but none is `true`, and takes `data[0]` when no entry has the key. The characters line single-quotes each phrase, and the prompt holds no double quote (final review I2) |
| CT23 | `tests/test_movie_ui_seams.py` | `lib.job_vlm("seams", {}, ws, "s1") == "required"`; `lib.seams_argv(ws, "s1") == [sys.executable, ws + "/bin/seam-report", "s1", "--port", "8177"]` (and `MOVIE_UI_VLM_PORT=9001` → `"9001"`); `plan_has_end_frames` true for a chained plan with one end frame, false for shots, none, `None`, blank strings |
| CT24 | same | `POST /api/stories/<id>/seams`: 201 with `job.kind == "seams"`, `job.command` ending `seam-report <id> --port 8177`, and the job's `job.json` `vlm` is `"required"`; unknown story 404; a chained plan without end frames 409 `story <id> has no end frames to check`; a second POST while queued 409 `a seams check of <id> is already queued as job <id>`; 401 without the token |
| CT25 | same | `POST /api/jobs` with valid chained movie fields and `"check_seams": true` → `queue.json` ends `[<movie id>, <seams id>]`, the seams job's argv as CT23; `check_seams` absent, `false` or `"true"` → no seams job; mode shots or action story → no seams job. Fix round 1: the seams job's `fields` are `{"ws", "story_id", "after": <movie id>}` and the 201 body keeps its keys; a movie cancelled while queued, or one that failed → at dispatch its seams job is `cancelled` with `error` and log `skipped: movie <id> ended cancelled|failed`, with no runner launched and no VLM tool called (the lifecycle on, recording stubs); with a failed movie, `vlm_restore_wanted` names the job after the seams job, and the same tick dispatches that job; a done movie's seams job runs; a seams job moved ahead of its movie → `skipped: movie <id> has not run yet`, and the movie is dispatched; a missing movie → `no longer exists`; a lost one → `ended lost`; no `after` → never skipped; a done movie whose plan has no end frames (or no `plan.json`) → `skipped: story <id> has no end frames to check`, no runner, no VLM tool, and the next job dispatches (final review I1) |
| CT26 | same | `GET /api/stories/<id>` → `end_frames` true/false and `seams` equal to the saved `seam_report.json` (or null) |
| CT27 | same | **Static page.** `index.html` contains the three CE15 snippets exactly; `app.js` contains `"/seams"`, `check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked`, `"seam-missed"`, `"This plan has no end frames; no seam report."`, `showSeams(res.data);`; `app.css` contains `.seam-missed td { background: var(--warn-bg); }`; the [MUI] page rules hold; `showSeams` iterates `Array.isArray(report.panels) ? report.panels : []` and returns on an entry that is not an object (fix round 1, Minor 5) |
| CT28 | same | **Failed movie.** A queued chained movie job followed by its seams job created as `POST /api/stories/<id>/seams` creates it (no `after`), both dispatched with `mt.dispatch` in a stub workspace whose movie stub exits 1 and writes no clips, and whose `bin/seam-report` is a copy of the real script (it loads nothing else on this path) → the seams job ends `done`, its log's last line is `seam-report: no clips to check in <clips>` |
| CT29 | `tests/test_chained_end_frames.py` | **No server, no HOME.** Every E2E uses `seu.script_agent`; `os.path.expanduser("~")` is never the real HOME |
| CT30 | `tests/test_seam_report.py` | `bin/seam-report` is executable, starts with `#!/usr/bin/env python3`, imports only stdlib modules (AST check: `argparse base64 http.client importlib.machinery json os re shutil subprocess sys tempfile time`) |

---

## 7. Re-baseline (the ONE test-only commit)

**Rule (mandatory).**
- Run the full suite on the rebased base before G1 and record the failures.
- After G1-G5, every existing test that changes outcome must be explained by a code below. Its assertions are updated to the new behaviour in the single test-only commit, whose body has one paragraph per changed file naming the tests and codes.
- A failure that no code explains is an implementation defect: fix the code, not the test.
- No test is deleted, and no assertion is weakened beyond the new behaviour. Recorded fixture artifacts under `tests/fixtures/writer_pacing/` are not edited.

| Code | Cause |
|---|---|
| CR1 | Camera keys (CE1): 14 sentences, the plan camera list without plain `tracking`, the longer P8 key list, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS`, `CAMERA_MOVE_WORDS`, `CAMERA_WRITER_FORMS` |
| CR2 | `FORMAT_REFERENCE`, its segments and terms (CE11): hash, length, `REF_PARTS`, six-gram count, the shot-1 camera key |
| CR3 | Chained plan prompt (CE4): `END_FRAME_RULE`, `end_frame` in the beat keys, `PLAN_REFERENCE` (which has braces) |
| CR4 | `N23` in `GENERATION_CHECKS` and `RECHECK_IDS` (CE12) |
| CR5 | P22 re-ask (CE7): a chained E2E whose scripted plan has no end frames makes a second plan call, which the fake agent answers with no envelope when its queue is empty; it also prints `plan: call 2 of 2` and the drop warning and writes `plan_reply_2.txt` |
| CR6 | `test_mut26` `BASELINE`: `story_engine.py` changes. The comment gains `, then to <feature sha> (chained end frames).` |
| CR7 | Route count: the merged base's count + 1 |

**Expected to change** (found by reading the tests at `574303a`; the implementer confirms each by running the suite):
- **`tests/test_story_engine.py`:**
  - `test_rs4_constants` (CR1: key list);
  - `test_rst8_plan_prompt_matrix` (CR3: the `"{" not in prompt` assertion must strip `plan_reference(...)` first; CR1);
  - `test_rst14_plan_checks` P8 row (CR1);
  - `test_pacing_camera_sentences_classify_as_before` (CR1: `len == 14`, plus "old" entries equal to the new sentences for the 5 keys);
  - `test_rst10_plan_retry_and_fatal_plan` second half and `test_rst39_outputs_and_layout` (CR5: the `calls` list, the round-0 file list with `plan_reply_2.txt`);
  - `test_rst51_e2e_chained`, `test_rst55b_p13_forces_plan_call_2`, `test_rst37_budgets_and_the_wall_clock` and every other chained `_run`/`_main_run` E2E that asserts stages, call counts, stdout or the round-0 file list (CR5).
- **`tests/test_shot_format.py`:**
  - `test_sft1a_planner_constants` (CR1, CR4: `CAMERA_SENTENCES`, `CAMERA_SPEAKING_SENTENCE`, `SPEAKING_CAMERAS`, `RECHECK_IDS_3970E96` becomes the CE12 tuple, renamed `RECHECK_IDS_CE`);
  - `test_sft2_the_plan_prompt` (CR1: `CAMERA_LIST`);
  - the SFT1 writer-constant tests at `:427-495` and `:627-669` (CR1, CR2, CR4: `CAMERA_WRITER_FORMS`, hash, `(3538, 618)`, `REFERENCE_TERMS`, `REFERENCE_COPY_SEGMENTS`, `GENERATION_CHECKS`, `len(REFERENCE_SIX_GRAMS) == 80`);
  - SFT12 rows at `:890-923` (CR2: the `"looks up from the empty ice trays"` row becomes a CE11 segment row);
  - `test_sft13_the_composition_and_the_reference` and `REF_PARTS` (CR2: the CE11 parts table; key `slow tracking right`);
  - `test_sft21` (CR2: 2406 → 3538);
  - unchanged: `test_sft3a_*` (it reads `se.SPEAKING_CAMERAS`), `test_sft25_p19_end_to_end` (no stage or stdout assertion; its single plan reply is reused as call 1) and the shots E2Es `test_sft11_*` and `test_review_focus_2_*`.
- **`tests/test_narrative_fidelity.py`:**
  - `test_nf16_the_speaking_coercion_table` (CR1: the local `kept` tuple gains the two tracking keys);
  - `test_nf32_no_narration_keeps_the_movie_silent`, `test_nf33_default_narration_with_the_fixed_plan` (CR5);
  - `test_nf28`/`test_nf29` (CR5: stdout only; their stage lists already have two plan calls).
- **`tests/test_dialogue.py`:** `test_dlg21_an_advisory_only_round_0_passes_untouched`, chained case (CR5). Its `'urgent'` advisory still holds (CE10 keeps the writer text).
- **`tests/test_pinned_cast.py`:**
  - `test_pt2_fixed_cast_block_and_uncast_byte_identity` and the fixtures `tests/fixtures/pinned_cast/uncast_chained_lines.txt`, `uncast_chained_seed.txt` (CR1, CR3) and `uncast_shots_lines.txt` (CR1). Regenerate each from the new `build_plan_prompt` and diff it: the diff must be exactly the camera list, `CAMERA_SPEAKING_SENTENCE`, and for chained the beat keys, `END_FRAME_RULE` and `PLAN_REFERENCE`;
  - `test_pt16_two_pinned_chained_every_line_spoken_by_c1` (CR5).
- **`tests/test_location_story.py`:** `test_ls1_without_locations_plan_prompts_and_plans_are_byte_identical` and `tests/fixtures/location/plan_prompt_chained.txt`, `plan_prompt_chained_cast.txt` (CR1, CR3) and `plan_prompt_shots.txt` (CR1). Its plan.json half is unchanged (D1).
- **`tests/test_soft_panel_count.py`:** `test_spt8_e2e_one_beat_added` and every other chained `_run_story` E2E that asserts stages or stdout (CR5).
- **`tests/test_speaker_attribution.py`, `tests/test_location_story.py` retry tests** (`test_sat6_e2e_retry`, `test_ls7_*`, `test_ls9_*`, `test_pt14_e2e_retry`): expected **unchanged**. Their containment assertions on the retry block still hold, and their second reply also lacks end frames, so no third call happens; only stdout gains the drop warning.
- **`tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged`** (CR6).
- **`tests/test_movie_ui_http.py::test_mut18_every_api_route_needs_the_token`** and **`tests/test_location_ui.py::test_lu1_the_location_routes_need_the_token`** (CR7).

**Must pass unchanged:**
- `tests/test_ltx_story_manifest_chain.py` (including `test_v2_golden_byte_identical`), `tests/test_judge_clips.py`, `tests/test_character_lib.py`, `tests/test_ltx_mlx_render.py`, `tests/test_vlm_lifecycle.py::test_vl1_job_vlm`, `tests/test_location_ui.py::test_lu9_job_vlm_policy`, `test_lu13` (no tab is added), `tests/test_dialogue.py::test_dlg15_assembly_goldens_and_dedupe`, `test_rst16_panel_prompt`, `test_rst18_assembly_goldens`.
- Every recheck test (D10), and `python3 tests/test_ltx_movie_offline.py`.
- The [BF] tests, in particular BT1 (no `DEFAULT_FIELDS` key is added).

---

## 8. KPIs

| # | KPI | Target | Verified by |
|---|---|---|---|
| CK1 | Newly planned chained beats with a valid end frame (stubbed planner that returns them on call 1 or 2) | 100% of beats in every saved plan with end frames; exhaustion leaves none, prints the warning, and rc is 0 | CT5, CT8, CT16 |
| CK2 | Chained panels whose camera clause covers the end frame (stubbed writer that lands) | 100%, zero N23 messages; a non-landing writer gets exactly one re-ask and then an advisory | CT10, CT11 |
| CK3 | Old stories | re-check with the same rc, hard and advisory lists, and the same manifest bytes | CT15, the CR "must pass unchanged" set |
| CK4 | The "standing still" end frame | survives the repair; "stays still and pushes in" is still N20 | CT12 |
| CK5 | Non-speech double quotes in any assembled prompt across the fixtures | 0 | CT13 |
| CK6 | seam-report verdicts and error cases | every row of CT17-CT22 | CT17-CT22 |
| CK7 | Full suite | same pre-existing failures (same tests, same messages); only the Section 7 re-baselines change, in ONE test-only commit | full run |

---

## 9. Risks

- **R1. More plan calls.** The chained plan prompt grows by about 650 (reference) + 110 (rule) tokens, and any P22/P24 miss costs a second plan call (minutes on the local Qwen). The live A/B records plan calls and drops.
- **R2. N23 strictness.** Pronoun-only clauses and paraphrases fail N23 and cost one re-ask per panel. After that it is only an advisory, so nothing blocks. The live A/B records the N23 advisory count.
- **R3. P24 false positives.** These are limited by the key-word filter and the narrative/pin exemptions. A user story about a fish market is exempt through its narrative.
- **R4. The planner copies the reference's beat shapes** (three beats, a closing static hold). The "FORMAT REFERENCE ONLY" label and P24 limit wording, not structure. The P18 cap and the soft panel count still govern.
- **R5. VLM judgement noise.** One still per panel, a 1-10 score, threshold 6. The report is advisory and never re-renders.
- **R6. A seams job costs a VLM reload** after every chained Run all (5-14 min). It is on by default as approved, and the user can untick it.
- **R7. Re-baseline volume (CR5).** Every chained E2E with a scripted plan lacking end frames gains a plan call. This is mechanical and confined to stages, stdout and file lists; the "must pass unchanged" set guards the rest.

---

## 10. Rollout

1. **Order.** Wait until batch forks ([BF], branch `bulk-rerun`) is merged into `qwen-agent-redteam`. Rebase `chain-endframes` (`$S/chain-wt`, from `574303a`) onto the merged base. Re-read the route count (`len(srv.ROUTES)`) and `TABS` from that base, and re-verify the line numbers of Section 0.2. If any differs, the CE text still binds, and only the citations move.
2. **Snapshot** (house rule): `tar czf $S/snapshot-pre-chained-end-frames.tgz -C /Users/reubenpatterson/local_agent_harness --exclude 'qwen-agent-workspace/generated' qwen-agent-workspace`. Record the full-suite pass count and pre-existing failures on the rebased base.
3. **Plan, then implement via SDD**, with no separate plan review.
   - Commit 1 (feature): G1-G5.
   - Commit 2 (tests only): G6, including `test_mut26` `BASELINE` = commit 1's sha.
   - Run CK7 and the `/usr/bin/python3` compile checks.
4. **Opus review** of the diff against this spec; fix; re-run CK7.
5. **Secret scan before any push:** `git diff <merged base>..HEAD | grep -nE '(api[_-]?key|secret|token|password|BEGIN [A-Z ]*PRIVATE KEY|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})'`. Review every hit by hand; any real credential stops the rollout.
6. **Push** `chain-endframes`, merge into `qwen-agent-redteam` and push.
7. **Live A/B** (this Mac only, post-merge, not a merge gate; never two renders at once, never the story server during a render, never port 8178):
   - `R=$S/chain-live` (new). Configurations: `ch3-a` and `ch3-b` (`LINES_NARRATIVE`, `--panels 3`, `--character kyra --character ronin --speech-only`) and `hk2` (hockey narrative, `--panels 2 --frames 145`, as in [SF] 5.1). Use story ids `ce1-<name>`.
   - **Arm B (with end frames):** `bin/ltx-movie … --story-id ce1-<name> --force-story --no-review` (plan, write, render).
   - **Arm A (same plan, no end frame in the video prompt):** `cp -Rp` each `ce1-<name>` story dir to `ce0-<name>` without `clips/`, `movie.mp4` and `manifest.json`. In `ce0-<name>/story.md`, replace each panel's Motion camera sentence (the `camera_directions` sentence) with that panel's `CAMERA_SENTENCES` fallback, using a script `$R/strip_clauses.py` that loads `story_engine.py` by path and edits only those sentences. Then render with `bin/ltx-movie … --story-id ce0-<name> --no-review` (Phase 1 re-checks the existing `story.md`; N23 is advisory).
   - **Score:** start the story server (`bin/story-server mlx-vision`), run `bin/seam-report` on all six stories, then stop it.
   - **Report:**
     - per configuration, mean score B vs A and the missed counts;
     - plan calls, P22 drops and N23 advisories of the B runs;
     - `$R/ab.html` with both `movie.mp4`s per configuration and the two `seam_report.md` tables.
   - **Expectation, not a gate:** mean B > mean A.

PR note (required in substance): "Chained plans now give every beat an end frame, writers land each panel's camera clause on it and start from the previous one, and five camera moves are added (tracking left/right, crane up/down, orbit). A 'standing still' end frame no longer trips the mixed-camera check, and only spoken lines keep double quotes. `bin/seam-report` (and the movie UI's Check seams) scores each panel's last frame against its planned end frame after the render. Old stories re-check and render exactly as before."

---

## 11. Values chosen by the spec

1. `end_frame` key present only when non-empty (D1).
2. Plan camera list omits plain `tracking`; shared by all modes (D2).
3. Tracking left/right are speaking cameras; crane/orbit coerce to slow push-in (D2).
4. Orbit fallback "The camera arcs around the subject in a partial orbit." (D2).
5. P24 outside end frames is fatal after the last call (D3).
6. P23 style test is the N3 rule; its camera test ignores static words and follow(s) (D4).
7. Static ends-on line names "holding" (D5).
8. `_names_camera` also reads the head (D6).
9. N23 uses no stemming (D7).
10. Quote conversion in all three modes (D8).
11. Shots keep their "The shot is" sentences; shot 1 has "ends on"; beat 1 is a medium shot (D9).
12. `PLAN_REFERENCE` shown only in chained, narration not False; no `lines` keys when the prompt has none (D9).
13. P24 key-word filter; N22 segments drop the end-frame clauses and the face-to-camera tail; `reference_copies` exempts end frames; "half-open shutter" term (D9).
14. No recheck advisory for old plans; the note comes from seam-report and the Stories tab (D10).
15. seam-report uses loopback HTTP, not qwen-agent; it does not import judge-clips; stale chainseeds lose to their clip; a mid-run transport failure exits 2 with nothing written; no clips is exit 0 (D11).
16. `--port` defaults to `STORY_SERVER_PORT` or 8177 (CE13).
17. The prompt lists the panel's characters with descriptors (CE13).
18. The Compose option is a `check_seams` body key outside `DEFAULT_FIELDS`, defaulting to false in the API; the seams job is created under the same lock; duplicate seams jobs are refused (D12).
19. Live A/B arms share one plan; arm A strips the camera clauses (Section 10).

## 12. Conflicts with the notes and open questions

- **C1 (resolved, D10).** The "no end frames" advisory vs byte-identical recheck: recheck stays byte-identical, and the note is shown by seam-report and the UI.
- **C2 (resolved, D2).** The notes' orbit example says "slowly", which the [WP] test forbids; the fallback drops it.
- **C3 (resolved, D1/CE5).** The notes' beat-2 example has `"lines": ["Forty years of mornings.", "Not one more."]`; the real schema takes line numbers, so it is `[1, 2]` plus an intro sentence naming the lines.
- **C4 (resolved, CR5).** The notes expected re-baselines only for `test_mut26`, the prompt literals and the route counts. Because P22 is hard for every newly planned chained story, every chained E2E whose scripted plan lacks end frames also gains a plan call. These are listed under CR5 rather than hidden by changing `tests/story_engine_testutil.py::plan_json`. That alternative would make every chained panel fail N23 and add even more calls.
- **Open:** none.
