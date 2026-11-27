# Image critic: the local VLM judges every Qwen seed edit for broken bodies and re-edits the failures

Date: 2026-11-27

Status: design spec with a task-level implementation plan outline (end of document).

**Where.** Worktree `$S/ic-wt`, branch `image-critic`, off `qwen-agent-redteam` at `0074122` (Merge PR #32).
`S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`.
`WS` is `qwen-agent-workspace/`. Every path is relative to `WS` and every line number was checked at `0074122`.
Nobody accesses macstudio. The live checks (Section 7) are the user's to run.

Choices this spec makes beyond the approved design are marked **[spec choice]**. The implementer makes no design
decisions: names, messages, constants and code shapes in Sections 2 and 3 are exact.

---

## 0. Purpose and scope

### 0.1 Purpose
Qwen-Image-Edit, editing a seed image into an action scene, sometimes morphs bodies: fused or extra limbs, melted
anatomy, warped faces and hands, a body merging into the background or another person. Today nothing looks at the
output. This feature adds an **image critic**: the local VLM scores each edit, the failures are re-edited with new
seeds, and the best attempt is kept. It is opt-in and changes nothing when it is off.

### 0.2 The approved design (binding; user decisions)

| Decision | Ruling |
|---|---|
| Judge | The **local 27B VLM**: `bin/story-server mlx-vision`, `127.0.0.1:8177`. |
| When it runs | **Between** Qwen batches. Qwen and the VLM are never resident together (Qwen floors 20-64 GiB, VLM ~27.5 GiB). |
| Scope v1 | The Seeds-tab generator (`bin/seed-edit` `run_qwen`) and the shots seed edit (`bin/ltx-movie` `_phase2_shots_seed`) **only**. |
| On exhaustion | Keep the **best-scored** attempt and **flag** it. Never stop the run, never drop the image. |
| Enablement | Opt-in, default **off**: CLI `--critic`, optional `--critic-rounds N` (default 2 redo rounds), a UI **Critic** checkbox in the Seeds and Shots forms. Flag off is byte-identical. |
| Module | New `image_critic.py`: `judge_image(path, seed_path=None) -> {"score", "defects", "reason"}` and `edit_with_critic(...)` wrapping `qwen_edit.run_jobs`. |
| Verdict | `score` is an int 1-10 (bools rejected), parsed with `extract_json`; a bad reply is retried once with the bad reply quoted. PASS when `score >= PASS_SCORE` (= 7, a named constant, calibrated live). |
| Prompt | Names the defects: extra/missing/fused limbs, melted or warped anatomy, distorted face or hands, bodies merging with the background or other people. Ignores style and composition. |
| Redo | Only the failed jobs, with a derived seed `sha256(seed, round, n)` (the `location_dataset.topup_seed` pattern); at most `--critic-rounds` redo rounds; the file at `output_path` is the best attempt at the end. |
| Records | Each image's entry gains `critic: {status: passed|flagged|unjudged, attempts: [{seed, score, defects}]}`. The reuse key stays on the **requested** seed; the seed used is stored separately. |
| Failure modes | VLM down or an unparseable reply: the image is kept, `unjudged`, and never redone on a guess. Exhaustion: best kept, `flagged`, run continues. |
| Log | `critic i/N: ok|redo|flagged|unjudged`, readable by `movie_ui_lib`'s log regexes. |
| Server | Runs `bin/*` as subprocesses and never imports `image_critic` (the same rule as the bulk-action spec F11 for `action_lib`). |
| Calibration | A `bin/image-critic score FILE...` CLI that prints score and defects, so the user can feed known-bad and known-good images. |

**Known unknown, stated honestly.** Nothing measures whether the abliterated 27B VLM can reliably see limb, face and
hand defects. `PASS_SCORE = 7` is a starting point. Live check ICL1 calibrates it and can conclude that the critic is
not reliable on this VLM (KPI K6). The feature is opt-in, so that outcome costs nothing.

### 0.3 Grounding (shipped code, read this session)

**`qwen_edit.py`**
- `run_jobs(model_id, loras, jobs, width, height, skill, work_dir, log_path=None, on_result=None, noun="job")`
  (:527-649) returns `(results, failure)`. Each result is `{"n", "output_path", "status": ok|blocked|failed, "seconds"}`.
- On `ok` it moves the staged file onto `output_path` with `os.replace` (:582 bf16 child, :622 mflux). The bf16 child
  maps result lines to jobs **by the stage file's basename** (`by_stage`). A failed job leaves no staged file (:643-645).
- The top-level import list is pinned by `tests/test_qwen_edit.py:385-390` (QET11). QET11 also pins the `NEW_PY` tail
  after `tests/test_movie_ui_seedgen.py` (:400-404).
- `wait_for_memory(floor, label, tag)` (:300-319) raises `Unavailable`. `memory_floor(model_id, references)` (:443),
  `label(model_id)` (:435).

**`bin/seed-edit`**
- `parse` (:99-107), `check_args` (:110-172), `new_record` (:311-327). Candidate `i` uses seed `opts["seed"] + i` (:323).
- `finish` (:352-364) writes `run.json`, then prints `candidate i/N <status> <s>s`. `run_qwen` (:423-435) builds one job
  per candidate and calls `qe.run_jobs(..., on_result=finish, noun="candidate")`.
- `main` converts SIGINT, SIGTERM and SIGHUP to `KeyboardInterrupt` (:506-512). SG7: every stdout line goes through `say`.
- Its top-level import list is pinned by `tests/test_movie_ui_seedgen.py:1335-1338` (SGT34). `character_dataset` is
  already imported inside a function (`preflight`, :277).

**`bin/ltx-movie`**
- `_qwen_edit()` (:1000-1003) loads `qwen_edit.py` by path, and only when it is needed. `sys.path` holds `WS` (:154).
- The shots reuse key (:2963-2975) includes `seed=args.image_seed`. A panel is reused only when the recorded entry
  matches every key item **and** `images/panel_NN.png` has the recorded `still_sha256`.
- `_phase2_shots_seed` (:2991-3103):
  - `record_entry` (:3042-3055);
  - `on_result` fits the edit into the still and writes `seed_edits.json` (:3057-3068);
  - one `qe.run_jobs` call (:3077-3078) inside `try/except qe.Unavailable`.
- `_resolve_seed_context` (:1288-1322); `main` calls the resolvers in order (:4470-4490). `phase2_stills` dispatches
  shots and seed to `_phase2_seed_context` or `_phase2_shots_seed` (:2564-2571). `_edit_references(jobs)` (:1473-1475).
- `bin/ltx-movie` installs **no** signal handler. `grep signal bin/ltx-movie pipeline_log.py` finds nothing, so a
  SIGTERM ends it without running any `finally` block.
- `phase_release_story_server` (Phase 1b, on by default) stops the story server before Phase 2 (:2759-2777).

**`character_dataset.py`**
- `extract_json` (:232-249).
- `image_data_url(path, max_side=768)` (:356-363).
- `vlm_call(content_parts, max_tokens=600)` (:366-391): temperature 0, thinking off. It raises `RuntimeError` on HTTP
  and transport errors. **But** it calls `resolve_vlm_model()` while it builds the payload, outside its `try`. A
  refused connection there raises `URLError`, which is an `OSError`, not a `RuntimeError` (finding F5).
- `score_still`'s retry quotes the rejected reply (:750-768), because at temperature 0 a bare retry repeats it.
- Lifecycle primitives: `vlm_ready` (:471), `story_server(cmd)` (:478-484), `restore_story_server(wait)` (:487-497),
  `story_server_state` (:500-515), `wait_for_vlm` (:518-525), `wait_for_avail` (:528-534). Constants: `STORY_SERVER`
  (:53), `VLM_SERVE_MODE` (:57), `VLM_WAIT_S`, `AVAIL_WAIT_S` (:200-201).
- The stop-around-work block is at :993-1022.

**`location_dataset.py`**
- `_with_story_server_stopped` (:418-443) is a copy of `character_dataset`'s block.
- `topup_seed` (:446-450) is `int(sha256("location-topup:%d:%d:%d")[:8], 16) & SEED_MAX`.
- The round loop is at :651-686.

**`bin/action-train-vlm`, `bin/seam-report`**
- `action-train-vlm` uses `story-server-restore` so that a cancel cannot kill the restarted server.
- `seam-report` (:206-305) strips `<think>` blocks before parsing (`THINK_RE`, :53) and validates an int, non-bool score.

**`movie_ui_lib.py`**
- `job_vlm` (:421-437): `seed-edit` is `"forbidden"`; `movie` is `"forbidden"` once `story.md` exists.
  `vlm_preflight` (:627-686) and `vlm_postflight` (:688-713) run only at job boundaries.
- Progress regexes (:2340-2356), `ProgressParser._line` (:2427-2475), `snapshot` (:2477-2513).
- `seed_edit_argv` (:1286-1301). `DEFAULT_FIELDS` (:942-955), `FIELD_FLAGS` (:961-976), `build_argv` (:1026-),
  `_rule_seed_edit` (:1138-1152), V1 rule list (:1638-1644).

**`movie_ui_seedgen.py`**: `_absent` (:128), `validate_run_request` (:201-240).

**`movie_ui_server.py`**: `_candidates` (:1757), `run_view` (:1810-1829), `_h_seed_run_create` (:1854-1902).

**`movie_ui_batch.py`**: `GROUPS` (:34-35), `FIELD_LEVELS` (:39-47).

**The page**
- `static/movie-ui/index.html`: the Compose seed-edit box (:90-106), and the Seeds panel `#se-qwen-box` (:196-201).
- `static/movie-ui/app.js`:
  - `composeFields` (:537-578), `updateComposeButtons` (:655-690), `fillCompose` (:940-);
  - `seedBody` (:2333-2345), `seedRow` (:2429-2470), `renderProgress` (:3353-3384).

### 0.4 Deliverables
1. `image_critic.py` (new): constants, `critic_seed`, `parse_verdict`, `judge_image`, `VLMSession`, `edit_with_critic`.
2. `bin/image-critic` (new, mode 100755): the calibration CLI.
3. `bin/seed-edit`: `--critic`, `--critic-rounds`, and the hook in `run_qwen`.
4. `bin/ltx-movie`: `--critic`, `--critic-rounds`, `_resolve_critic`, `_image_critic`, and the hook in
   `_phase2_shots_seed`.
5. `movie_ui_lib.py`: the `critic` compose field, flag, argv and V1 rule 12f; `CRITIC_RE` and the parser's `critic`
   summary; `--critic` in `seed_edit_argv`.
6. `movie_ui_seedgen.py`: `critic` in `validate_run_request`.
7. `movie_ui_server.py`: `critic` in the seed run's job fields and in the candidate view.
8. `movie_ui_batch.py`: the level and group of `critic`.
9. `static/movie-ui/index.html`, `app.js`: the two checkboxes, the per-candidate verdict, and the progress text.
10. Tests: Section 6.

### 0.5 Non-goals and future work
- **Out of scope (v1), each with its reason:**
  - `--seed-context` (still and frame). It chains stills: panel k+1 is edited from panel k's still. A redo of panel k
    would change the context picture of every later panel, so one redo cascades into re-editing the rest of the
    movie, and in frame mode into re-rendering clips.
  - `--cast-refs-model` edits. A different batch, record and reuse key (`cast_ref_edits.json`); future work on the
    same `edit_with_critic`.
  - Phase 1c (chained mode, one panel-1 edit). Future work; one job, so it is the cheapest to add next.
  - `character_dataset` and `location_dataset`. They already have their own VLM checks (`score_still`, the location
    check) with their own keep/drop and top-up rules.
  - Z-Image stills (Seeds `zimage`, shots without a seed or `as-is`). They are not Qwen edits.
- Re-judging **reused** shots panels. A panel reused by the reuse key is not judged, even when its entry has no
  `critic` block (Q1).
- A UI input for the number of rounds. The UI always sends the default (Q4).
- Showing critic verdicts in the Stories tab gallery. The Jobs tab progress line and `seed_edits.json` carry them.
- The deploy package (`scripts/deploy`). `ltx-movie` loads `image_critic.py` by path only with `--critic`, the same
  way `qwen_edit.py` stays out of the package.
- Any change to `job_vlm`, `vlm_preflight`, `vlm_postflight` or `recovery_restore`.

### 0.6 Success criteria (KPIs)
- **K1 Flag off is unchanged.**
  - Without `--critic`, `bin/seed-edit` and `bin/ltx-movie` print the same lines and write the same files and records
    as at `0074122`.
  - `image_critic` is never imported.
  - The movie-ui argv, snapshot and view dicts are unchanged for fields without `critic`.
  - The intended table changes are: one `DEFAULT_FIELDS` key (`critic: False`, so new movie `job.json` fields carry
    it), one `FIELD_FLAGS` entry, and the two tools' `--help` texts.
- **K2 Only failures are redone.**
  - Each ok image's newest attempt is judged once.
  - Only jobs whose best judged score is below `PASS_SCORE` go into a redo batch.
  - There are at most `rounds` redo batches.
  - At the end, `output_path` holds the highest-scored attempt, the earliest one on a tie.
- **K3 Never resident together.**
  - Every judge phase starts after a `run_jobs` call has returned.
  - Every redo `run_jobs` call comes after a successful `story-server stop` **and** `qe.wait_for_memory` (the call
    order is asserted in ICT5).
- **K4 The VLM is left as found.** After `edit_with_critic` returns or raises (exception, `KeyboardInterrupt`,
  SIGTERM), the story server is restored to the state it was in before the first judge phase (ICT8).
- **K5 Zero-failure overhead.** With every image passing, there is exactly one VLM start, one judge pass, one stop,
  and no redo batch (ICT4). The user measures the wall-clock cost in ICL3.
- **K6 Calibration** (ICL1). On the user's set of at least 10 known-bad and at least 10 known-good action edits:
  - there is a threshold `t` that catches at least 80% of the bad ones;
  - at the same `t`, it fails at most 20% of the good ones.
  - If no `t` does both, the report says "the critic is not reliable on this VLM", `PASS_SCORE` stays 7, and the
    feature stays opt-in.
- **K7** The full suite is green: `python3 -m pytest -q -p no:cacheprovider tests/`. Every changed Python file
  compiles on `/usr/bin/python3` (3.9.6).

### 0.7 Must-have vs nice-to-have
- **Must:** everything in 0.4, the tests in Section 6, and the calibration CLI.
- **Nice (not in this spec):** a rounds input in the UI; flagged badges in the Stories gallery; re-judging reused
  panels; a judge-with-seed default (Q2).

---

## 1. Findings (verified this session)

- **F1. `qwen_edit.py` is not changed.** `edit_with_critic` lives in `image_critic.py` and calls `qe.run_jobs` with
  the module passed in. The QET11 import pin (`tests/test_qwen_edit.py:385-390`) is unaffected. QET11's
  `NEW_PY`-tail pin (:400-404) **is** affected, because new files are appended to `NEW_PY`. Its expected list gains
  them (6.3).
- **F2. `bin/seed-edit`'s import pin (SGT34) is kept** by importing `image_critic` inside `run_qwen`, only on the
  critic path. That is the existing pattern for `character_dataset` (:277) and the docstring's rule (:44-46). The
  docstring sentence gains `image_critic`, and the pin list is unchanged.
- **F3. `test_mut26` pins `bin/ltx-movie` and `character_dataset.py`** (`tests/test_movie_ui_builder.py:223-229` `PIPELINE_FILES`,
  :281-291).
  - `git diff --stat a87e799 0074122 -- bin/ltx-movie character_dataset.py` is empty, so the pin is green at the base.
  - This spec changes `bin/ltx-movie` only. `character_dataset.py` is reused, not edited (F4).
  - The `bin/ltx-movie` commit therefore needs its own test-only re-baseline commit right after it (Plan).
- **F4. The existing stop/restore helpers are not reused, and they are not copied.**
  - `character_dataset.py:993-1022` and `location_dataset.py:418-443` stop the VLM **around** Qwen work. The critic
    needs the inverse: start it around judging, then return to the prior state. Neither helper fits.
  - Both helpers also have two defects that must not be copied:
    - they `raise DatasetError` inside `finally`, which masks an in-flight exception;
    - they restore the server unconditionally, whatever state it was in before.
  - Factoring a shared helper would edit `character_dataset.py`, a pinned pipeline file, which means a second
    re-baseline, plus `location_dataset.py`. That is rejected **[spec choice]**.
  - `image_critic.VLMSession` (2.3) is built on the **primitives**, called through `character_dataset` and never
    copied: `story_server`, `restore_story_server`, `story_server_state`, `wait_for_vlm`, `wait_for_avail`,
    `vlm_ready`, `vlm_call`, `extract_json`, `image_data_url`, `STORY_SERVER`, `VLM_SERVE_MODE`, `VLM_WAIT_S`,
    `AVAIL_WAIT_S`.
  - The only pin this constrains: `character_dataset.py` stays byte-identical (test_mut26).
- **F5. `vlm_call` can raise more than `RuntimeError`.** `resolve_vlm_model()` runs outside its `try`, so
  `judge_image` treats **any** `Exception` from `vlm_call` as "the VLM is unavailable" (2.2).
- **F6. A cancel would skip the critic's cleanup in `ltx-movie`.**
  - A movie-ui Cancel SIGTERMs every process group of the job (`cancel_tree`, `movie_ui_lib.py:279-298`).
    `ltx-movie` has no handler, so a SIGTERM during judging would leave the VLM running.
  - The VLM itself survives the sweep, because `story-server-restore` gives it a launchd parent.
  - So `edit_with_critic` installs a temporary handler (2.4.6).
- **F7. The VLM policy needs no change.**
  - Seed-edit jobs, and movie jobs with a `story.md`, are `"forbidden"`, so the preflight stops the VLM before Qwen
    round 0.
  - Phase 1b stops it in `ltx-movie` after a story phase.
  - The preflight and postflight run only before the child starts and after it ends, so they never run while the
    critic holds the VLM (Section 5).
- **F8. A redo cannot reuse `output_path`.** `run_jobs` replaces `output_path` on ok (:582, :622), so a redo into
  `output_path` would destroy the earlier attempt before it is compared. Redo jobs get their own output and stage
  paths under `<work_dir>/critic/` (2.4.3).
- **F9. The reuse key survives.** The entry's `seed` stays the requested `args.image_seed`, and `still_sha256` is
  recomputed whenever a better attempt replaces the still. A rerun therefore reuses every panel (ICT18).
- **F10. Equality pins on the movie-ui dicts.**
  - `tests/test_movie_ui_seedgen.py`:
    - :418 and :435 (snapshot keys);
    - :700-712 (the seed run record and the job fields);
    - :714 (the candidate view);
    - :106-113 (`validate_run_request`'s clean dict).
  - So every new key appears **only** when the critic is on (2.10).
- **F11. Table-count pins.**
  - `len(lib.FIELD_FLAGS) == 32`: `tests/test_location_ui.py:267`, `tests/test_movie_ui_extra_refs.py:63`,
    `tests/test_movie_ui_qwen_edit.py:116`, `tests/test_movie_ui_shots_seed.py:157`.
  - The `FLAGS` set: `tests/test_movie_ui_shots_seed.py:38-43`.
  - `len(lib.DEFAULT_FIELDS) == 33`: `tests/test_movie_ui_extra_refs.py:60`, `tests/test_movie_ui_batch.py:79` (as
    `(28, 5, 33)`).
  - `EXPECTED_LEVELS`: `tests/test_movie_ui_batch.py:29-38`.
  - `FIELD_FLAGS[-1]` and `[-2:]` stay valid because `critic` goes in **before** `extra_refs` (2.10.1).
- **F12. Source scans.** `test_mut25` forbids the word `urllib` and `load_module(` in every `NEW_PY` file
  (`tests/test_movie_ui_builder.py:242-249`). `image_critic.py`, `bin/image-critic` and both new test files must
  contain neither, including in docstrings and test stubs. Tests use `OSError(...)` for transport failures.

---

## 2. Design (normative)

### 2.1 `image_critic.py`: header and constants
Docstring: name the spec, say what the module does, and end with:
"Python 3.9 and 3.13. The top level imports only the standard library; character_dataset (PIL, psutil) is imported
inside the functions that call the VLM or bin/story-server. movie_ui_server never imports this module."

The top-level imports are exactly these, in this order: `glob`, `hashlib`, `os`, `re`, `shutil`, `signal`,
`subprocess`, `sys`, `threading`.

```python
PASS_SCORE = 7              # a score >= PASS_SCORE passes; calibrated live (spec ICL1)
DEFAULT_ROUNDS = 2          # redo rounds when --critic-rounds is not given
MAX_ROUNDS = 4
JUDGE_WITH_SEED = False     # edit_with_critic sends the edit alone (spec Q2); bin/image-critic --seed sends both
JUDGE_MAX_SIDE = 1024       # image_data_url's long side for a judged image
JUDGE_ATTEMPTS = 2          # one call, then one retry that quotes the rejected reply
JUDGE_MAX_TOKENS = 400
DEFECTS_MAX = 8
DEFECT_CHARS = 60
REASON_CHARS = 300
VLM_MIN_AVAIL_GIB = 28.0    # available memory awaited before the VLM starts
SEED_MAX = 2147483647
CRITIC_DIR = "critic"
THINK_RE = re.compile(r"(?s)<think>.*?</think>")          # bin/seam-report THINK_RE
LINE_STATES = {"passed": "ok", "flagged": "flagged", "unjudged": "unjudged"}
```

The prompts are exact. `JUDGE_PROMPT` is one string, written as concatenated literals:

> The picture to check was made by an AI image editor. Check only the bodies of the people and animals in it for
> anatomy errors. Defects to look for: extra, missing or fused arms, legs, hands or fingers; melted, stretched,
> twisted or warped bodies or limbs; a distorted, doubled or smeared face; malformed hands; a body merging into the
> background, an object or another person. Ignore the art style, lighting, composition, framing, clothing, setting,
> image quality, and whether the picture matches any description; a dynamic or unusual pose is not a defect when the
> body is anatomically possible. Reply with only a JSON object with three keys. "score": an integer from 1 to 10 for
> how anatomically correct every body is, where 10 means every body is natural and complete, 7 means only small flaws
> a viewer would not notice at a glance, and 4 or less means an obvious defect; a picture with no people or animals
> scores 10. "defects": a list of at most 8 short phrases, one per defect you see, such as "fused left hand" (an empty
> list when there is none). "reason": one sentence.

`JUDGE_SEED_PROMPT = SEED_PREFACE + JUDGE_PROMPT`, where `SEED_PREFACE` is:

> You get two images. The first is the photo the edit started from; the second is the picture to check. Use the first
> only to see what these people's bodies normally look like, and do not count differences in pose, setting, clothing
> or style. 

(It ends with one space.)

`JUDGE_RETRY` is `'Your previous reply was rejected: %s. Previous reply: %s\n'` followed by
`'Reply again with only the JSON object: "score" an integer from 1 to 10, "defects" a list of short phrases (empty when there is none) and "reason" one sentence.'`.

The exceptions: `class JudgeError(Exception)`, which means this image could not be judged, and
`class VLMUnavailable(JudgeError)`, which means the VLM is not usable for any further image.

`def _cd()`: `import character_dataset` inside the function, then return it. It is the **only** way the module
reaches `character_dataset`; tests replace it.

`def _say(text)`: `print(text, flush=True)`.

### 2.2 Seeds, verdicts and `judge_image`
1. **`critic_seed(seed, round_n, n)`** returns
   `int(hashlib.sha256(("image-critic:%d:%d:%d" % (seed, round_n, n)).encode("ascii")).hexdigest()[:8], 16) & SEED_MAX`.
2. **`parse_verdict(reply)`** returns `{"score", "defects", "reason"}` or raises `ValueError`. The checks run in this
   order:
   1. If `reply` is not a `str`: `ValueError("the reply has no text")`.
   2. `d = _cd().extract_json(THINK_RE.sub("", reply))`. Its `ValueError` propagates.
   3. `score = d.get("score")`. If `isinstance(score, bool) or not isinstance(score, int)`:
      `ValueError("score must be an integer, got %r" % (score,))`. If `not 1 <= score <= 10`:
      `ValueError("score must be 1-10, got %d" % score)`.
   4. If `"defects" not in d`: `ValueError("missing key: defects")`. If the value is not a list of `str`:
      `ValueError("defects must be a list of strings")`.
   5. Clean the defects: `[" ".join(x.split())[:DEFECT_CHARS] for x in defects]`, drop the empty ones, and keep the
      first `DEFECTS_MAX`.
   6. `reason`: `" ".join(r.split())[:REASON_CHARS]` when it is a `str`, else `""`. A missing or wrong-typed reason is
      **not** an error **[spec choice]**: it carries no decision.
3. **`judge_image(path, seed_path=None)`:**
   1. Build the parts:
      - `[{"type": "text", "text": JUDGE_SEED_PROMPT if seed_path else JUDGE_PROMPT}]`;
      - then, when `seed_path` is given, `{"type": "image_url", "image_url": {"url": cd.image_data_url(seed_path, JUDGE_MAX_SIDE)}}`;
      - then the same for `path`.
      - Any `Exception` while building raises `JudgeError("cannot read %s: %s: %s" % (p, type(e).__name__, e))`,
        where `p` is the file that failed.
   2. Loop `JUDGE_ATTEMPTS` times, starting with `reply, error = None, None`:
      - `content = parts` when `error is None`, else `parts + [{"type": "text", "text": JUDGE_RETRY % (error, reply)}]`;
      - `reply = cd.vlm_call(content, max_tokens=JUDGE_MAX_TOKENS)`. Any `Exception` raises
        `VLMUnavailable("VLM request failed: %s: %s" % (type(e).__name__, e))` (F5);
      - `return parse_verdict(reply)`. On `ValueError as e`, set `error = e` and loop.
   3. After the loop: `raise JudgeError("unparseable: %s" % error)`.
4. Thin wrappers for the CLI: `vlm_ready()` returns `_cd().vlm_ready()`, and `vlm_models_url()` returns `_cd().MODELS_URL`.

### 2.3 `VLMSession`: the lifecycle
`VLMSession(say)` has these attributes: `original = None`, `hands_off = None`, `serving = False`,
`maybe_up = False`, `say`. `mode` below is `cd.VLM_SERVE_MODE` (`"mlx-vision"`).

- **`up()`** returns `None` when the VLM can judge, else a reason string.
  1. On the first call only: `original = cd.story_server_state()`. If it is not one of `"STOPPED"`,
     `"SERVING " + mode`, `"LOADING " + mode`, set
     `hands_off = "the story server is %s; the image critic needs it stopped or serving %s" % (original, mode)`.
     This covers `UNKNOWN`, `FOREIGN pid N` and text mode.
  2. If `hands_off`, return it. The critic then never starts or stops anything.
  3. If `serving`, return `None`.
  4. If `original != "STOPPED"` and `cd.vlm_ready()`, set `serving = maybe_up = True` and return `None`.
  5. `say("critic: starting the VLM (bin/story-server-restore %s --wait)" % mode)`.
  6. If `not cd.wait_for_avail(VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S)`, return
     `"less than %g GiB available for the VLM after waiting %d s" % (VLM_MIN_AVAIL_GIB, cd.AVAIL_WAIT_S)`.
  7. Set `maybe_up = True`, then `rc = cd.restore_story_server(wait=True)`. If `rc != 0`, return
     `"bin/story-server-restore %s --wait exited %d" % (mode, rc)`.
  8. If `not cd.wait_for_vlm(cd.VLM_WAIT_S)`, return `"the VLM did not answer within %d s" % cd.VLM_WAIT_S`.
  9. Set `serving = True` and return `None`.
- **`down()`** returns `None` when the VLM is down, else a reason string.
  1. If `not maybe_up`, return `None`.
  2. `say("critic: stopping the VLM for the Qwen redo")`, `rc = cd.story_server("stop")`, `serving = False`.
  3. If `rc != 0`, return `"bin/story-server stop exited %d" % rc`.
  4. Set `maybe_up = False` and return `None`.
- **`restore(interrupted)`** never raises. Its whole body is wrapped in `try/except Exception as e`, which writes
  `"critic: warning: restoring the VLM failed: %s\n" % e` to stderr.
  1. If `original is None or hands_off`, do nothing.
  2. If `original == "STOPPED" and maybe_up`:
     - interrupted: write `"critic: interrupted; stopping the VLM in its own session\n"` to stderr, then
       `subprocess.Popen([cd.STORY_SERVER, "stop"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)`.
       Do not wait. The stop must outlive the cancel sweep, which is the mirror of the existing restore detach.
     - otherwise: `say("critic: stopping the VLM (it was stopped before the critic started)")`, then
       `rc = cd.story_server("stop")`. If `rc != 0`, write
       `"critic: warning: bin/story-server stop exited %d; the VLM may still hold its memory\n" % rc` to stderr.
  3. If `original` is `SERVING` or `LOADING` and `not serving` (the critic stopped it for a redo): run
     `cd.restore_story_server()` (detached, returns at once) in both cases **[spec choice]**, and
     `say("critic: restarting the VLM in the background (it was serving before the critic started)")`.

**Timeline** (the usual case: the job preflight or Phase 1b left the VLM `STOPPED`):

```
step  Qwen child                  VLM :8177                     critic
 0    round-0 batch (all jobs)    STOPPED                       -
 1    exited (run_jobs returned)  wait_for_avail(28) + restore --wait + wait_for_vlm
 2    -                           SERVING                       judge every ok image (round 0)
 3    -                           story-server stop             only when a job scored < PASS_SCORE
 4    wait_for_memory(floor), redo batch 1 (failed jobs only)   STOPPED
 5    exited                      start (as step 1)             judge redo-1 outputs
 6    ... steps 3-5 again for redo round 2 (at most `rounds` redo batches)
end   -                           story-server stop             restore(original = STOPPED)
```

With zero failures, only steps 0, 1, 2 and end happen: one start and one stop.

### 2.4 `edit_with_critic`
```python
def edit_with_critic(qe, model_id, loras, jobs, width, height, skill, work_dir, rounds=DEFAULT_ROUNDS, total=None,
                     on_result=None, on_verdict=None, on_best=None, noun="job", tag="seed-edit", say=None):
    """(results, failure) of round 0, exactly as qe.run_jobs returns them; ..."""
```
- `qe` is the caller's `qwen_edit` module. `ltx-movie` passes its by-path module, and tests pass a fake.
- `jobs` are the caller's `run_jobs` job dicts, unchanged.
- `total` is the `N` of the log lines (default `len(jobs)`).
- `on_result` is passed to the round-0 `run_jobs` only.
- `on_verdict(n, block)` is called whenever a job's block changes (2.4.5).
- `on_best(n, output_path)` is called after a better redo attempt replaces `output_path`.
- `say` defaults to `_say`.
- `plural(k)` below is `noun` when `k == 1`, else `noun + "s"`.

#### 2.4.1 Round 0
1. `results, failure = qe.run_jobs(model_id, loras, jobs, width, height, skill, work_dir, on_result=on_result, noun=noun)`.
   Its exceptions (`qe.Unavailable`, `KeyboardInterrupt`) propagate unchanged.
2. If `failure is not None`: `say("critic: not run; the %s batch failed" % noun)` and return `(results, failure)`.
   The VLM is not touched.
3. `ok = [r["n"] for r in results if r["status"] == "ok"]`. Blocked and failed jobs are **skipped, not judged**: no
   attempt, no block, no line. If `ok` is empty: `say("critic: not run; no %s produced an image" % noun)` and return.
4. `os.makedirs(<work_dir>/critic, exist_ok=True)`. For each `n` in `ok`, delete every
   `glob(<work_dir>/critic/<stem>.r*.png)`, where `stem = os.path.splitext(os.path.basename(job["output_path"]))[0]`.
   This removes stale attempts of an earlier run **[spec choice]**.
5. The state per `n` in `ok`:
   `{"attempts": [{"round": 0, "seed": job["seed"], "score": None, "defects": [], "note": None}], "best": None, "reason": None, "seed_used": job["seed"], "line": None}`.
   `best` is an index into `attempts`.

#### 2.4.2 The loop
Before the loop: `session = VLMSession(say)`, install the interrupt handlers (2.4.6), set `redo_runs = 0`.

```
r, phase, stop = 0, sorted(ok), False
while True:
    if phase: stop = judge_phase(r, phase) or stop
    active = sorted(n for n in state if best is not None and best score < PASS_SCORE)
    if stop or r == rounds or not active: break
    phase, stop = redo_phase(r + 1, active)      # phase None: the redo did not run -> break
    if phase is None: break
    r += 1
```

**`judge_phase(r, phase)`**: returns True when the loop must stop after this phase.
1. `say("critic: judging %d %s with the VLM (round %d)" % (len(phase), plural(len(phase)), r))`.
2. `reason = session.up()`. If it is set: for each `n` in `phase`, set its newest attempt's
   `note = "not judged: " + reason`, set `state.reason = reason` when `best is None`, and emit the not-judged line
   (2.6). Then call `on_verdict` for each job and return True.
3. Otherwise, for `n` in `phase`, in order:
   - `path` is `job["output_path"]` when `r == 0`, else the round-`r` attempt image (2.4.3).
   - `v = judge_image(path, job["source"] if JUDGE_WITH_SEED else None)`.
   - On `VLMUnavailable as e`: this job and every job after it in `phase` get
     `note = "not judged: " + str(e)` (and `state.reason = str(e)` when `best is None`), with no further VLM call.
     Emit their lines, call `on_verdict` for every job in `phase`, and return True.
   - On `JudgeError as e`: `note = "not judged: " + str(e)`, and `state.reason = str(e)` when `best is None`.
   - Otherwise set the attempt's `score` and `defects` from `v`. When `best is None` or `v["score"] >` the best score
     (**strictly** greater, so a tie keeps the earlier attempt):
     - when `r > 0`, install the attempt (2.4.3) and call `on_best(n, job["output_path"])` if it is given;
     - set `best` to this attempt's index, `seed_used` to its seed, and `state.reason = v["reason"]`.
   - Emit this job's line (2.6).
4. Call `on_verdict(n, block(n))` for every `n` in `phase`, then return False.

**`redo_phase(rr, active)`**: returns `(next_phase, stop)`, or `(None, True)` when the redo did not run.
1. `reason = session.down()`. If it is set: `say("critic: redo round %d of %d not run: %s" % (rr, rounds, reason))`
   and return `(None, True)`.
2. `qe.wait_for_memory(qe.memory_floor(model_id, refs), qe.label(model_id), tag=tag)`, where
   `refs = max(len(j.get("sources") or [j["source"]]) for j in redo_jobs)` (the `_edit_references` rule). On
   `qe.Unavailable as e`: the same "not run" line with `str(e)`, and return `(None, True)`.
3. For each `n` in `active` with `len(attempts) == 1`, copy round 0 for the record:
   `shutil.copyfile(job["output_path"], <round-0 attempt image>)`.
4. `redo_jobs = [dict(job, seed=critic_seed(job["seed"], rr, n), stage_path=<stage rr>, output_path=<image rr>) for n in active]`.
   It uses the caller's own job dict, so `run_jobs` adds the LoRA triggers exactly once, and `sources` (extra
   references) carry over. Append the attempt `{"round": rr, "seed": <that seed>, "score": None, "defects": [], "note": None}`.
5. `say("critic: redo round %d of %d: %s %s with new seeds" % (rr, rounds, plural(len(active)), ", ".join(str(n) for n in active)))`.
6. `res, fail = qe.run_jobs(model_id, loras, redo_jobs, width, height, skill, work_dir, noun=noun)`. On
   `qe.Unavailable as e`, use `res, fail = [], str(e)`. Then `redo_runs += 1`.
7. For each `n` in `active`:
   - status `ok`: `n` goes into `next_phase`;
   - `blocked`: `note = "blocked by the content screen"`;
   - anything else, or missing: `note = "the edit failed"`.
   - Call `on_verdict` for every job with a note.
8. If `fail is not None`: `say("critic: redo round %d failed: %s; keeping the best attempts" % (rr, fail))` and
   return `(next_phase, True)`. The ok outputs are still judged, then the loop stops. Otherwise return
   `(next_phase, False)`.

**After the loop** (still inside the `try`):
1. For every job whose `line` differs from `LINE_STATES[status]`, emit its final line (2.6).
2. Call `on_verdict(n, block(n))` for every job in the state, in `n` order.
3. `say("critic: done: %d passed, %d flagged, %d unjudged; %d redo round(s) run" % (...))`.
4. Return `(results, failure)`. These are round 0's results; `failure` is None.

#### 2.4.3 Attempt files
- For round `k`: the image is `<work_dir>/critic/<stem>.r<k>.png` and the stage is
  `<work_dir>/critic/<stem>.r<k>.pending.png`.
- Every stage basename in a batch is unique, which the bf16 child's `by_stage` map needs (0.3).
- **Installing** attempt `k` over `output_path`: `shutil.copyfile(image, output_path + ".critic-tmp")`, then
  `os.replace(output_path + ".critic-tmp", output_path)`. `output_path` is always a complete file.
- Attempts stay on disk for calibration **[spec choice]**: round 0 only when the job was redone, every redo attempt
  that ended ok. They are never served by the UI (seed runs' `work/` is refused by `_in_seed_work`).

#### 2.4.4 The block
`block(n)` returns, with keys in this order:

```json
{"status": "passed|flagged|unjudged", "score": 8, "defects": ["..."], "reason": "...", "seed_used": 123,
 "pass_score": 7, "attempts": [{"round": 0, "seed": 11, "score": 4, "defects": ["fused left hand"], "note": null}]}
```

- `status` is `"unjudged"` when `best is None`, `"passed"` when the best score is `>= PASS_SCORE`, else `"flagged"`.
  While a redo is pending, `flagged` means "the best attempt so far is below the pass score". A later pass changes it.
- `score` and `defects` are the best attempt's (`None` and `[]` when unjudged).
- `reason` is the best attempt's judge reason, or the not-judged reason.
- `seed_used` is the seed of the attempt now at `output_path`.
- `attempts` are copies.
- **[spec choice]** beyond the approved `{status, attempts: [{seed, score, defects}]}`: the keys `score`, `defects`,
  `reason`, `seed_used`, `pass_score`, and `round`/`note` on each attempt.

#### 2.4.5 Callbacks
`on_verdict` is called:
- after each judge phase, for the jobs in it;
- after each redo batch, for the jobs whose attempt has a note;
- once at the end, for every job.

The callers write their record on each call.

#### 2.4.6 Interrupts and cleanup
- Right after `session` is created, and only when `threading.current_thread() is threading.main_thread()`: for each
  of `signal.SIGTERM` and `signal.SIGHUP` whose current handler is `signal.SIG_DFL`, install a handler that raises
  `KeyboardInterrupt`. Keep the previous handlers.
  - `bin/seed-edit` already has its own handlers (not `SIG_DFL`), so they stay as they are.
  - `bin/ltx-movie` gets the temporary handler (F6).
- The loop and the after-loop steps run in `try: ... except KeyboardInterrupt: interrupted = True; raise` with a
  `finally:` block that, in order:
  1. removes `glob(<work_dir>/critic/*.pending.png)` and each `job["output_path"] + ".critic-tmp"` (each `os.remove`
     in `try/except OSError: pass`);
  2. runs `session.restore(interrupted)`;
  3. restores the saved signal handlers.
- Other exceptions (for example from `on_verdict`) propagate after the `finally`, with `interrupted` False, so the
  stop is synchronous.

### 2.5 Records
**`bin/seed-edit` `run.json`** (with `--critic` only):
- The top-level key `"critic": {"rounds": <rounds>, "pass_score": image_critic.PASS_SCORE}` is written by `run_qwen`
  before `edit_with_critic`.
- Each candidate entry gains `"critic": <block>` (2.4.4).
- Candidate `seed` stays `opts["seed"] + i`.

**`bin/ltx-movie` `seed_edits.json`** (with `--critic` only):
- A judged panel's entry gains `"critic": <block>`.
- `seed` stays `args.image_seed`.
- `still_sha256` always describes the current `images/panel_NN.png`.
- The reuse check (:2970-2973) is unchanged and ignores `critic`.

### 2.6 Log lines and `CRITIC_RE`

`D(attempt)` is `"; ".join(defects)` or `"no defect named"`. `A` is `round + 1`. `K` is `len(attempts)`.

| When | Line |
|---|---|
| Attempt judged, `score >= PASS_SCORE` | `critic n/N: ok (score S, attempt A)` |
| Attempt judged, `score < PASS_SCORE`, `r < rounds` | `critic n/N: redo (score S: D)` |
| Attempt judged, `score < PASS_SCORE`, `r == rounds` | `critic n/N: flagged (best score B of K attempts: D(best))` |
| Round-0 attempt not judged | `critic n/N: unjudged (<reason>)` |
| Redo attempt not judged or blocked | no line |
| Final, when `line != LINE_STATES[status]` | the ok form with the best attempt, the flagged form, or the unjudged form with `state.reason` |

Each emitted line sets `state.line` to its word.

Every other critic line starts with `critic: ` (with a colon), so it never matches `CRITIC_RE`.

**`movie_ui_lib.py`**: add this right after `SEED_CAND_RE` (:2356):
`CRITIC_RE = re.compile(r"^critic (\d+)/(\d+): (ok|redo|flagged|unjudged)(?: \((.*)\))?$")   # image critic spec 2.6`

- `ProgressParser.__init__`: `self.critic = {}            # image critic: {"<n>": "ok" | "redo" | "flagged" | "unjudged"}`.
- `_line`: right after the `last_line` update and **before** `if self.kind == "seed-edit":`, add
  `match = CRITIC_RE.match(line)`, then `if match: self.critic[match.group(1)] = match.group(3); return`.
- A new method:

  ```python
  def critic_summary(self):
      """{"ok", "redo", "flagged", "unjudged"}: the sorted int n of each job in its newest critic state."""
      return dict((state, sorted(int(n) for n, s in self.critic.items() if s == state))
                  for state in ("ok", "redo", "flagged", "unjudged"))
  ```
- `snapshot`: in the `seed-edit` dict, and in the final story/movie dict, add `"critic": self.critic_summary()`
  **only when** `self.critic` is non-empty (F10). The other kinds are unchanged.

### 2.7 `bin/image-critic` (new, mode 100755)
The docstring:

```
image-critic -- score images for broken bodies with the local VLM, to calibrate image_critic.PASS_SCORE
(docs/superpowers/specs/2026-11-27-image-critic-design.md, Section 2.7).

  bin/image-critic score FILE [FILE ...] [--seed PATH] [--pass-score N] [--json]

Needs the VLM serving (bin/story-server mlx-vision); it starts and stops nothing and writes nothing. --seed sends
that photo first, as the edit's source. Exit 0 every file judged; 1 at least one file not judged; 2 a usage error, a
missing file or the VLM not serving. Python 3.9 and 3.13.
```

- The top-level imports are exactly `argparse`, `json`, `os`, `sys`, then (after
  `WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` and `sys.path.insert(0, WS)`)
  `import image_critic as ic  # noqa: E402`.
- `main(argv=None)`:
  1. The parser: prog `image-critic`; `sub = add_subparsers(dest="cmd")`; `sub.required = True`.
  2. The subcommand `score`:
     - `files` (`nargs="+"`, metavar `FILE`);
     - `--seed` (default None, metavar `PATH`);
     - `--pass-score` (dest `pass_score`, `type=int`, default `ic.PASS_SCORE`, metavar `N`);
     - `--json` (`store_true`).
  3. If `not 1 <= pass_score <= 10`: print `Error: --pass-score must be an integer from 1 to 10` to stderr and
     return 2.
  4. For each path in `[seed] + files` (seed only when it is given): if `not os.path.isfile(p)`, print
     `Error: <p> is not a file` and return 2. This runs before any VLM call.
  5. If `not ic.vlm_ready()`: print
     `Error: the VLM is not serving at <ic.vlm_models_url()>; start it with bin/story-server mlx-vision` and return 2.
  6. For each file in order, call `ic.judge_image(file, seed)`:
     - On `JudgeError as e`: the file is unjudged with `error = str(e)`.
     - After a `VLMUnavailable`, every remaining file is unjudged with the same error, and no further call is made.
  7. Text output, one line per file:
     - judged: `"%s: score %d %s: %s -- %s" % (file, score, "PASS" if score >= pass_score else "FAIL", D, reason or "-")`;
     - not judged: `"%s: UNJUDGED: %s" % (file, error)`;
     - then `"pass score %d: %d pass, %d fail, %d unjudged"`.
  8. `--json`: instead, one `json.dumps(obj, sort_keys=True)` per file, with
     `obj = {"path", "score" (int or None), "verdict": "pass"|"fail"|"unjudged", "defects", "reason", "error" (None or str)}`.
     There is no summary line.
  9. Return 1 when any file is unjudged, else 0.
- The script ends with `if __name__ == "__main__": sys.exit(main())`.

### 2.8 `bin/seed-edit`
1. **Usage docstring** (:6-7). The usage line becomes `... [--candidates N] [--seed N] [--critic [--critic-rounds N]] --run-dir DIR`.
   Append to the paragraph ending "...and loads nothing." (:22):
   "--critic (Qwen models only) has the local VLM judge every ok candidate for broken bodies between Qwen batches and
   re-edit the failures with new seeds, at most --critic-rounds N (0 to 4, default 2) more times; the best attempt
   stays cand_NN.png and run.json records each candidate's critic verdict
   (docs/superpowers/specs/2026-11-27-image-critic-design.md)."
   In :45-46, the words "content_safety and" / "character_dataset are imported" become "content_safety," /
   "character_dataset and image_critic are imported" (the line break stays after the first part).
2. **`parse`**: after the `--probe` line, add `parser.add_argument("--critic", action="store_true")` and
   `parser.add_argument("--critic-rounds", type=str)`.
3. **`check_args`**:
   - `given` gains `args.critic_rounds, True if args.critic else None` at its end.
   - After the `--seed` rule (:166-169), add, in order:
     - `args.critic_rounds is not None and not args.critic` raises `Refusal("--critic-rounds needs --critic")`;
     - `args.critic and args.model != "qwen"` raises `Refusal("--critic is only for --model qwen")`;
     - `args.critic_rounds is not None and not (re.fullmatch(r"[0-9]+", args.critic_rounds) and int(args.critic_rounds) <= 4)`
       raises `Refusal("--critic-rounds must be an integer from 0 to 4")`.
   - The returned dict gains `"critic": bool(args.critic)` and
     `"critic_rounds": None if args.critic_rounds is None else int(args.critic_rounds)`.
4. **`run_qwen`**: the existing body is kept byte for byte under `if not opts["critic"]:`, which ends with
   `return failure`. The critic path:

   ```python
       import image_critic
       rounds = image_critic.DEFAULT_ROUNDS if opts["critic_rounds"] is None else opts["critic_rounds"]
       rec["critic"] = {"rounds": rounds, "pass_score": image_critic.PASS_SCORE}
       write_run(ctx)
       _results, failure = image_critic.edit_with_critic(
           qe, entry["id"], opts["loras"], jobs, ctx["width"], ctx["height"], SAFETY_SKILL, ctx["work"],
           rounds=rounds, total=len(rec["candidates"]),
           on_result=lambda r: finish(ctx, r["n"], r["status"], r["seconds"]),
           on_verdict=lambda n, block: critic_verdict(ctx, n, block), noun="candidate", tag="seed-edit", say=say)
       return failure
   ```

   `jobs` is built before the branch, as today.
5. **New `critic_verdict(ctx, n, block)`**, placed right after `finish`: it sets
   `ctx["record"]["candidates"][n - 1]["critic"] = block`, then calls `write_run(ctx)`.

### 2.9 `bin/ltx-movie`
1. **The flags**, inserted right after `--seed-edit-lora` (:447-450):

   ```python
       parser.add_argument("--critic", dest="critic", action="store_true",
                            help="with --shots, --seed-image and a Qwen --seed-edit-model ID: the local VLM (bin/story-server "
                                 "mlx-vision) judges every panel's seed edit for broken bodies between Qwen batches and "
                                 "re-edits the failures with new seeds; the best attempt is kept and flagged when none "
                                 "passes. See docs/superpowers/specs/2026-11-27-image-critic-design.md.")
       parser.add_argument("--critic-rounds", dest="critic_rounds", type=int, default=None, metavar="N",
                            help="with --critic: at most N redo rounds (0 to 4, default 2; 0 judges without redoing)")
   ```
2. **`_image_critic()`**, placed right after `_qwen_edit()`:
   `return importlib.machinery.SourceFileLoader("image_critic", os.path.join(WS, "image_critic.py")).load_module()`.
   Its docstring says it is loaded by path, and only with `--critic`.
3. **`_resolve_critic(args)`**, placed right after `_resolve_seed_context`. It returns 0, or 2 after one `Error:` line
   on stderr. In order:
   1. `args.critic_rounds is not None and not args.critic`: `Error: --critic-rounds needs --critic`.
   2. `not args.critic`: return 0.
   3. `not 0 <= args.critic_rounds <= 4` (when it is not None): `Error: --critic-rounds must be an integer from 0 to 4`.
   4. `getattr(args, "seed_context", None)`: `Error: --critic cannot be combined with --seed-context: a redone still would change every later panel's context picture`.
   5. `not (args.shots and getattr(args, "seed_image", None) and getattr(args, "seed_edit", None))`:
      `Error: --critic needs --shots with --seed-image and a Qwen --seed-edit-model ID: the image critic judges the shots seed edits only`.
   6. `os.path.join(WS, "image_critic.py")` missing: `Error: --critic needs <path>, which this workspace does not have`.
   7. Return 0. `args.critic_rounds` stays None for the default.

   In `main`, right after the `_resolve_seed_context` block (:4485-4487), add
   `rc = _resolve_critic(args)`, then `if rc: return rc`.
4. **`_phase2_shots_seed`**:
   - Add two closures after `on_result`:

     ```python
         def on_verdict(n, block):
             entries[n]["critic"] = block
             _write_shots_seed_record(files["record"], entries, total)

         def on_best(n, output_path):
             still = os.path.join(paths["images_dir"], "panel_%02d.png" % n)
             fit.fit_letterbox(fit.load_oriented_rgb(output_path), still_w, still_h).save(still + ".tmp", format="PNG")
             os.replace(still + ".tmp", still)
             entries[n]["still_sha256"] = _sha256_file(still)
             _write_shots_seed_record(files["record"], entries, total)
             print("panel %d -> %s (critic: a better attempt of the Qwen edit of the seed)" % (n, still))
     ```
   - Inside the existing `try`, the `qe.run_jobs(...)` statement (:3077-3078) becomes:

     ```python
         if getattr(args, "critic", False):
             ic = _image_critic()
             rounds = ic.DEFAULT_ROUNDS if args.critic_rounds is None else args.critic_rounds
             results, failure = ic.edit_with_critic(qe, model_id, loras, jobs, width, height, SHOTS_SEED_EDIT_SKILL,
                                                    files["work"], rounds=rounds, total=total, on_result=on_result,
                                                    on_verdict=on_verdict, on_best=on_best, noun="panel",
                                                    tag="ltx-movie")
         else:
             results, failure = qe.run_jobs(...)        # the existing call, unchanged
     ```
   - `getattr` keeps hand-built test namespaces working.
   - Nothing else in the phase changes. A blocked panel still fails the phase after the batch: the critic has judged
     the ok panels, so their stills, records and blocks are reused on the rerun.
5. **Module docstring**: append one paragraph after the seed-edit paragraph (:113-):
   "Image critic (docs/superpowers/specs/2026-11-27-image-critic-design.md): --critic with --shots, --seed-image and a
   Qwen --seed-edit-model ID judges every panel's seed edit with the local VLM between Qwen batches and re-edits the
   failures with new seeds (--critic-rounds, default 2); the best attempt is the still, and seed_edits.json records
   each panel's verdict. It loads image_critic.py by path, only with --critic."

### 2.10 The movie-ui
1. **`movie_ui_lib.py`**:
   - `DEFAULT_FIELDS`: insert `"critic": False,` right after `"extra_refs": [],` (:947).
   - `FIELD_FLAGS`: `("no_review", ("--no-review",)), ("extra_refs", ("--extra-ref",)),` (:974) becomes
     `("no_review", ("--no-review",)), ("critic", ("--critic",)), ("extra_refs", ("--extra-ref",)),`.
   - `build_argv`: inside `if fields["seed_upload"]:`, right after the `--extra-ref` loop (:1042-1043), add
     `if fields.get("critic") is True:` then `argv.append("--critic")   # image critic spec 2.10`.
   - New `_rule_critic(fields)`, right after `_rule_seed_edit`:

     ```python
     def _rule_critic(fields):
         """V1 rule 12f (image critic spec 2.10): critic is a bool, and true only on a shots seed edit run."""
         critic = fields.get("critic", False)
         if not isinstance(critic, bool):
             return ["critic must be true or false"]
         if critic and not (fields.get("mode") == "shots" and fields.get("seed_upload") is not None
                            and fields.get("seed_edit_model") not in (None, "as-is")):
             return ["the image critic needs shots mode with a seed image and a Qwen seed edit model"]
         return []
     ```

     Add `errors += _rule_critic(fields)                                       # 12f` right after the 12e line
     (:1642).
   - `seed_edit_argv`: right before the final `return`, add `if fields.get("critic") is True:` then
     `argv.append("--critic")`. The flag therefore comes after the model options and before `--candidates`.
   - `CRITIC_RE`, the parser and the snapshot: 2.6.
2. **`movie_ui_seedgen.validate_run_request`**:
   - After the `_qwen_fields` error check, add `critic = body.get("critic")`, then:
     - `if not _absent(body, "critic") and not isinstance(critic, bool)`: return
       `(None, "critic must be true or false")`;
     - `if critic is True and model != "qwen"`: return `(None, "critic is only for qwen")`.
   - After building the clean dict: `if critic is True: clean["critic"] = True`. Return it the same way as before.
3. **`movie_ui_server.py`**:
   - In `_h_seed_run_create`, after `fields = {...}` (:1897-1900), add `if clean.get("critic") is True:` then
     `fields["critic"] = True`. The record the server writes is unchanged; `bin/seed-edit` adds `"critic"`.
   - New `_cand_critic(entry)`, after `_cand_file`:
     - it returns None unless `entry.get("critic")` is a dict whose `status` is in `("passed", "flagged", "unjudged")`;
     - otherwise it returns `{"status", "score": <int or None (lib._is_int)>, "defects": <the str items of a list, else []>, "reason": <str clipped to 300, else None>, "attempts": <len of a list, else 0>}`.
   - `run_view`'s candidate comprehension becomes a loop that builds the same dict, then sets `item["critic"] = c2`
     only when `c2 = _cand_critic(c)` is not None.
4. **`movie_ui_batch.py`**:
   - `FIELD_LEVELS` gains `"critic": "stills",` after `"extra_refs": "stills",`.
   - The second `GROUPS` tuple gains `"critic"` at its end. The flag lives in the seed block of the argv.

### 2.11 The page
1. **`index.html`, Compose**: right after the `c-sq-shots-note` `<p>` (:96), insert:
   `          <label id="c-critic-box" hidden><input id="c-critic" type="checkbox"> Image critic: the local VLM checks every panel's still for broken bodies (extra, missing or fused limbs, warped faces or hands) and re-edits the failures with new seeds, up to 2 more times; the best attempt is kept, and flagged when none passes. Each round adds a VLM start.</label>`
2. **`index.html`, Seeds**: right after `<p id="se-qwen-note" class="muted"></p>` (:200), insert:
   `        <label id="se-critic-box"><input id="se-critic" type="checkbox"> Image critic: the local VLM checks each candidate for broken bodies and re-edits the failures with new seeds, up to 2 more times; the best attempt is kept, and flagged when none passes</label>`
   It is visible exactly when `#se-qwen-box` is.
3. **`app.js`**:
   - `composeFields`: right before `return out;`, add
     `out.critic = Boolean(seedEdit) && out.mode === "shots" && out.seed_edit_model !== "as-is" && supported.critic !== false && $("#c-critic").checked;`.
   - `updateComposeButtons`: right after `const zimageSeed = ...;`, add
     `show($("#c-critic-box"), shotsSeed && !zimageSeed && !(S.options && S.options.supported && S.options.supported.critic === false));`.
   - `fillCompose`: right after `$("#c-mode").value = f.mode || "chained";`, add `$("#c-critic").checked = f.critic === true;`.
   - `seedBody`: replace `return {...};` with `const body = {...};`, then
     `if (model === "qwen" && $("#se-critic").checked) { body.critic = true; }`, then `return body;`.
   - Add right before `function seedRow(view, cand) {`:

     ```js
       function criticText(c) {
         if (c.status === "passed") { return "critic: passed (score " + c.score + (c.attempts > 1 ? ", after " + c.attempts + " attempts" : "") + ")"; }
         if (c.status === "flagged") { return "critic: flagged — best score " + c.score + " of " + c.attempts + " attempts" + (c.defects.length ? ": " + c.defects.join("; ") : ""); }
         return "critic: not judged" + (c.reason ? " (" + c.reason + ")" : "");
       }

       function criticProgressText(c) {
         const parts = [c.ok.length + " ok"];
         if (c.redo.length) { parts.push(c.redo.length + " being redone"); }
         if (c.flagged.length) { parts.push("flagged " + c.flagged.join(", ")); }
         if (c.unjudged.length) { parts.push("not judged " + c.unjudged.join(", ")); }
         return "critic: " + parts.join(", ");
       }
     ```
   - `seedRow`:
     - the `key` gains `+ "|" + (cand.critic ? cand.critic.status + ":" + cand.critic.score + ":" + cand.critic.attempts : "")`;
     - right after `row.parts = [cell];`, add
       `if (cand.critic) { row.parts.push(el("div", {cls: "muted", text: criticText(cand.critic)})); }`.
     - Files are served `no-store`, so a re-render shows the replaced image.
   - `renderProgress`:
     - in the phases branch, right after the `p.stills` line, add `if (p.critic) { parts.push(criticProgressText(p.critic)); }`;
     - in the else branch, `counted` gains `+ (p.critic ? " - " + criticProgressText(p.critic) : "")` at its use.
   - All new text goes in through `textContent` (`el`'s `text`). There is no `innerHTML`, `style=`, inline handler,
     `confirm(` or URL.
4. `app.css` is unchanged.

**Where flagged images surface.**
- Seeds tab: each candidate's verdict line under its image (from `run.json`).
- Compose/Jobs: the job's progress line (from the log), for a running job and a finished one.
- On disk: `seed_edits.json`, plus the attempt files under `seed_edits/critic/` and `work/critic/`.

---

## 3. Exact messages

| Where | Text |
|---|---|
| `parse_verdict` | `the reply has no text` · `score must be an integer, got <repr>` · `score must be 1-10, got <n>` · `missing key: defects` · `defects must be a list of strings` |
| `judge_image` | `cannot read <path>: <Type>: <e>` · `VLM request failed: <Type>: <e>` · `unparseable: <error>` |
| `VLMSession` | `the story server is <state>; the image critic needs it stopped or serving mlx-vision` · `less than 28 GiB available for the VLM after waiting 600 s` · `bin/story-server-restore mlx-vision --wait exited <rc>` · `the VLM did not answer within 600 s` · `bin/story-server stop exited <rc>` · stdout `critic: starting the VLM (bin/story-server-restore mlx-vision --wait)` · `critic: stopping the VLM for the Qwen redo` · `critic: stopping the VLM (it was stopped before the critic started)` · `critic: restarting the VLM in the background (it was serving before the critic started)` · stderr `critic: interrupted; stopping the VLM in its own session` · `critic: warning: bin/story-server stop exited <rc>; the VLM may still hold its memory` · `critic: warning: restoring the VLM failed: <e>` |
| `edit_with_critic` | `critic: not run; the <noun> batch failed` · `critic: not run; no <noun> produced an image` · `critic: judging <k> <noun(s)> with the VLM (round <r>)` · `critic: redo round <r> of <R>: <noun(s)> <list> with new seeds` · `critic: redo round <r> of <R> not run: <reason>` · `critic: redo round <r> failed: <failure>; keeping the best attempts` · `critic: done: <p> passed, <f> flagged, <u> unjudged; <k> redo round(s) run` · the 2.6 lines · notes `not judged: <reason>` · `blocked by the content screen` · `the edit failed` |
| `bin/image-critic` | `Error: --pass-score must be an integer from 1 to 10` · `Error: <p> is not a file` · `Error: the VLM is not serving at <url>; start it with bin/story-server mlx-vision` · the 2.7 output lines |
| `bin/seed-edit` | `--critic-rounds needs --critic` · `--critic is only for --model qwen` · `--critic-rounds must be an integer from 0 to 4` · `--probe takes no other options` (existing) |
| `bin/ltx-movie` | the five `Error:` lines of 2.9.3 |
| movie-ui | `critic must be true or false` (V1 and seeds) · `the image critic needs shots mode with a seed image and a Qwen seed edit model` · `critic is only for qwen` |

---

## 4. Error handling

| Failure | Outcome |
|---|---|
| Round-0 batch failed (`failure` set) | The critic does not run and the VLM is untouched; the caller's existing failure path applies. |
| Round-0 jobs blocked or failed | Skipped, never judged, no block; the caller's existing handling applies (shots: the phase fails after the batch). |
| The story server is in another state (text, FOREIGN, UNKNOWN) | Every image is `unjudged` with the hands-off reason; nothing is started or stopped. |
| The VLM does not start (memory, restore exit, no answer) | Every image in the phase is `unjudged`; no redo; `restore` stops whatever start was attempted (`maybe_up`). |
| VLM transport error during a phase | That image and the rest of the phase are not judged, with no more calls, and the loop ends. Jobs with an earlier judged attempt keep their status; round-0 jobs become `unjudged`. |
| Unparseable twice | That attempt is not judged. In round 0 the job is `unjudged` and never redone; later, the earlier best stands. |
| `story-server stop` fails before a redo | The redo is not run; statuses are from the best attempts (`flagged`). |
| `wait_for_memory` times out before a redo | The same. |
| A redo batch fails or is `Unavailable` | Its ok outputs are judged, then the loop ends. Round-0 results are returned and the run is **not** failed. |
| A redo attempt is blocked | A note on the attempt; the best is unchanged; the job stays active while rounds remain. |
| Exhausted | The best attempt is at `output_path`, `flagged`; seed-edit exits 0 and the shots phase returns 0. |
| Exception, `KeyboardInterrupt` or SIGTERM | `finally`: pending files removed, the VLM restored (detached on an interrupt), handlers restored; the exception propagates. `output_path` is always a complete earlier-best file. |

---

## 5. The VLM lifecycle rule (server preflight vs. critic)
1. `job_vlm` is unchanged: `seed-edit` is `"forbidden"`, and `movie` is `"forbidden"` once `story.md` exists. The
   critic is **not** a reason for `"required"`, which would keep the VLM resident through Qwen round 0.
2. The preflight runs before the job's child starts, and the postflight after it ends. Neither runs while the critic
   holds the VLM, so they cannot fight it.
3. Inside the job, **only** `edit_with_critic` starts or stops the VLM, and only between Qwen batches. It returns the
   server to its state before the first judge phase: `STOPPED` for every UI-queued critic job.
4. The start goes through `story-server-restore`, which gives the server a launchd parent. The interrupt-path stop
   runs in a new session. Whatever a cancel leaves behind, the next job's preflight or postflight reconciles it.
5. `movie_ui_lib`'s `vlm_preflight`, `vlm_postflight` and `recovery_restore` are unchanged, and
   `tests/test_vlm_lifecycle.py` passes unedited.
6. Residual risk, which predates this feature and is not changed: a movie-ui **server restart** in the middle of a
   job runs `recovery_restore`. With an empty queue that can start the VLM under any running forbidden job, critic or
   not.
7. `movie_ui_server.py`, `movie_ui_lib.py`, `movie_ui_seedgen.py` and `movie_ui_batch.py` never import or name
   `image_critic` (ICT24).

---

## 6. Tests

### 6.1 New: `tests/test_image_critic.py` (Task 1)
Rules:
- `import image_critic as ic` (stdlib top level).
- `ic._cd` is monkeypatched to a `FakeCD` object that records every call, in order, in `fake.log`.
  - Its methods: `story_server_state`, `restore_story_server(wait=False)`, `story_server(cmd)`,
    `wait_for_vlm(timeout_s)`, `wait_for_avail(min_gib, timeout_s)`, `vlm_ready()`,
    `vlm_call(parts, max_tokens=600)`, and `image_data_url(path, max_side=768)`, which returns `"data:" + path` so
    replies can be scripted per file.
  - `extract_json` is the real `character_dataset.extract_json`.
  - Its constants: `STORY_SERVER`, `VLM_SERVE_MODE = "mlx-vision"`, `VLM_WAIT_S = 600`, `AVAIL_WAIT_S = 600`,
    `MODELS_URL`.
- `FakeQE` provides:
  - `run_jobs` with the real signature, which writes `b"img:%d:%d" % (n, seed)` to `output_path` for ok outcomes,
    with per-`(n, seed)` scripted outcomes;
  - `wait_for_memory`, `memory_floor(model_id, references=1)` returning 20.0, `label` returning "Fake", and
    `Unavailable`.
- Replies are scripted per `(path, call index)`.
- No test contacts a server, starts a process (`subprocess.Popen` in `ic` is monkeypatched where it is used) or uses
  the word `urllib` (F12).

The tests:
- **ICT1. Constants and seeds.**
  - `PASS_SCORE == 7`, `DEFAULT_ROUNDS == 2`, `MAX_ROUNDS == 4`, `JUDGE_WITH_SEED is False`.
  - `critic_seed(7, 1, 2)` equals the value the test computes with `hashlib.sha256(b"image-critic:7:1:2")`.
  - It differs for `(7, 2, 2)` and `(7, 1, 3)`, and is in `0..SEED_MAX` for 100 random inputs.
- **ICT2. `parse_verdict`.**
  - A plain reply, a fenced reply, and a `<think>{"score": 1}</think>{"score": 8, ...}` reply give score 8.
  - `True`, `8.0`, `"8"`, `0` and `11` are rejected with the exact messages.
  - A missing `defects`, and `defects: "x"`, are rejected.
  - Defects are cleaned: whitespace collapsed, the empty one dropped, cut to 60 characters, at most 8.
  - A missing `reason` gives `""`.
- **ICT3. `judge_image`.**
  - A bad reply then a good one returns the verdict. The second call's content ends with
    `JUDGE_RETRY % (error, bad_reply)`.
  - Two bad replies raise `JudgeError` starting `unparseable: `.
  - A `RuntimeError` or `OSError` from `vlm_call` raises `VLMUnavailable`.
  - With `seed_path`: the parts are `[JUDGE_SEED_PROMPT, seed image, image]`. Without it: `[JUDGE_PROMPT, image]`.
  - `max_tokens == 400`, and `image_data_url` is called with `max_side == 1024`.
- **ICT4. All pass, zero failures.**
  - 3 jobs all score 8. `run_jobs` is called once.
  - `fake.log` lifecycle calls are exactly `story_server_state`, `wait_for_avail`, `restore_story_server(wait=True)`,
    `wait_for_vlm`, then 3 `vlm_call`, then `story_server("stop")`.
  - Every block is `passed` with one attempt, and `critic/` holds no `.png`.
  - The lines `critic 1/3: ok (score 8, attempt 1)` .. `3/3` and
    `critic: done: 3 passed, 0 flagged, 0 unjudged; 0 redo round(s) run` are printed.
  - The return value is exactly the round-0 `run_jobs` return.
- **ICT5. Only the failed job is redone, and the call order holds** (K2, K3).
  - Job 2 scores 3, then 8. The second `run_jobs` call holds only job 2, with
    `seed == critic_seed(job_seed, 1, 2)`, `output_path == <work>/critic/<stem>.r1.png` and a `.r1.pending.png` stage.
  - These calls happen in this relative order: `vlm_call`s, `story_server("stop")`, `wait_for_memory`, `run_jobs`,
    `restore_story_server(wait=True)`, `vlm_call`, `story_server("stop")`.
  - The bytes at job 2's `output_path` equal the r1 attempt, and `critic/<stem>.r0.png` holds the round-0 bytes.
  - `on_best` is called once with `(2, output_path)`.
  - Block 2: `passed`, `score` 8, `seed_used` the derived seed, two attempts (rounds 0 and 1).
  - The caller's `jobs[1]["seed"]` is unchanged, and the lines read `redo (score 3: ...)`, then `ok (score 8, attempt 2)`.
- **ICT6. Flagged on exhaustion; the best attempt is kept.**
  - One job scoring 5, 3, 4 with `rounds=2`: three attempts, and `output_path` bytes equal round 0.
  - `flagged`, `score` 5, `seed_used` the job's seed.
  - The last per-job line is `critic 1/1: flagged (best score 5 of 3 attempts: <D>)`, and the return failure is None.
  - A tie (5, 5, 2) keeps round 0.
  - `rounds=0` judges once, never redoes, and flags.
- **ICT7. Unjudged when the VLM is down or the reply is unusable.**
  - (a) `restore_story_server` returns 1: every block is `unjudged` with reason `bin/story-server-restore mlx-vision --wait exited 1`,
    there is no redo, and `story_server("stop")` is still called at the end.
  - (b) `vlm_call` raises on image 2 of 3: image 3 gets no `vlm_call`. Image 1 (score 3) ends `flagged` with **no**
    redo batch. Images 2 and 3 are `unjudged`.
  - (c) Image 1 is unparseable twice and image 2 scores 3: image 1 is `unjudged` and absent from the redo batch, and
    image 2 is redone.
  - (d) `story_server_state` returns `"SERVING text"`: no lifecycle call after it, and every job is `unjudged` with the
    hands-off reason.
- **ICT8. The VLM is restored on an exception and on a signal** (K4).
  - (a) `on_verdict` raises `RuntimeError`: `story_server("stop")` is called synchronously and the error propagates.
  - (b) The redo `run_jobs` raises `KeyboardInterrupt`:
    - `subprocess.Popen` is called once with `[STORY_SERVER, "stop"]` and `start_new_session=True`, and there is no
      synchronous stop;
    - `critic/*.pending.png` files written by the fake before raising are removed;
    - `output_path` holds round 0;
    - `KeyboardInterrupt` propagates.
  - (c) With `SIGTERM` at `SIG_DFL`, the scripted `vlm_call` runs `os.kill(os.getpid(), signal.SIGTERM)`:
    `KeyboardInterrupt` is raised, the detached stop runs, and afterwards `signal.getsignal(SIGTERM) is SIG_DFL`.
  - (d) The original state is `"SERVING mlx-vision"`, with one redo: there is no `restore(wait=True)` before the
    first phase; a stop comes before the redo; a `restore_story_server(wait=True)` comes before the second phase;
    and there is no lifecycle call at the end. When the redo's only output is blocked (no second phase), the end
    calls `restore_story_server()` with no wait.
- **ICT9. Blocked outputs are skipped, not judged.**
  - Round-0 job 2 blocked: no `vlm_call` sees job 2's path, and `on_verdict` is never called for 2.
  - A redo attempt blocked: its note is `blocked by the content screen` and the best is unchanged.
- **ICT10. Nothing to judge.** A round-0 `failure` returns `(results, failure)` with an empty `fake.log`. With every
  job blocked, the same, and the line is `critic: not run; no job produced an image`.
- **ICT11. The redo is not run.**
  - `wait_for_memory` raises `Unavailable("x")`: the line is `critic: redo round 1 of 2 not run: x`, there is no
    second `run_jobs`, and the status is `flagged`.
  - `story_server("stop")` returns 3: `... not run: bin/story-server stop exited 3`.
- **ICT12. `bin/image-critic`.** It is loaded by path with `spec_from_loader`/`exec_module`, with `ic._cd` patched.
  - The text lines and the summary are exact.
  - `--json` gives one object per file, with exactly the keys in 2.7.
  - The exit code is 0 when all are judged and 1 when one is unparseable.
  - A missing file returns 2 with no `vlm_ready` call. `vlm_ready` False returns 2. `--pass-score 11` returns 2.
  - `--pass-score 9` turns a score of 8 into FAIL.
- **ICT13. Import hygiene.**
  - `image_critic.py`'s top-level imports are exactly the 2.1 list.
  - `python -X importtime -c "import image_critic"` (with `HOME=tmp`) imports none of `character_dataset`, `PIL`,
    `psutil`.
  - `bin/image-critic`'s top-level imports are exactly `argparse, json, os, sys, image_critic`.

### 6.2 Extended tests (Tasks 2 and 3)
**`tests/test_seed_edit_tool.py` (Task 2)**, using its `env` fixture and stubs:
- **ICT14. Option rules.**
  - `--critic` with `--model zimage` gives exit 2 and `--critic is only for --model qwen`.
  - `--critic-rounds 1` without `--critic` gives `--critic-rounds needs --critic`.
  - `--critic-rounds 5` and `--critic-rounds x` give the range message.
  - `--probe --critic` gives `--probe takes no other options`.
  - `check_args` with `--critic` gives `critic True`, `critic_rounds None`.
- **ICT15. Flag off is unchanged.** A qwen run through the existing mflux stub without `--critic`:
  - `run.json` has no `critic` key at any level;
  - each candidate's keys are exactly `n, seed, status, seconds`;
  - no stdout line starts with `critic`;
  - `"image_critic" not in sys.modules` afterwards (remove it from `sys.modules` before the run).
- **ICT16. The critic wiring.** `sys.modules["image_critic"]` is a fake module whose `edit_with_critic` records its
  arguments, calls `on_result` for each job as ok, then `on_verdict(1, {"status": "flagged"})`, and returns `([], None)`.
  - The fake is called with the same `jobs` that `run_jobs` would get, `rounds == 2`, `total == candidates`,
    `noun == "candidate"`, `tag == "seed-edit"`.
  - `run.json` has `critic == {"rounds": 2, "pass_score": 7}` and
    `candidates[0]["critic"] == {"status": "flagged"}`.
  - Each candidate's `seed` is `seed + i`, and the exit is 0.
  - `--critic-rounds 0` passes `rounds == 0`.

**`tests/test_ltx_movie_shots_seed.py` (Task 2)**, using `clean_env`, `_phase_args` and `_FakeShotsQwenEdit`:
- **ICT17. `_resolve_critic`.** Each of the five errors, in the 2.9.3 order. With shots, a seed and a Qwen ID it
  returns 0, `critic_rounds` stays None, and `--critic-rounds 3` is kept.
  `"--critic"` and `"--critic-rounds"` appear in `build_parser().format_help()`.
- **ICT18. Shots with the critic, end to end.**
  - Setup:
    - a subclass of the fake writes a 64x64 PNG whose colour is `(seed % 256, 0, 40 * n)`;
    - `movie._image_critic` returns the real `image_critic`, with `ic._cd` patched;
    - panel 2 scores 3, then 9, and panels 1 and 3 score 8;
    - `_phase_args(tmp, critic=True, critic_rounds=None)`.
  - The phase returns 0, and the second `run_jobs` call holds only panel 2.
  - `images/panel_02.png` is the fit of the r1 colour.
  - In `seed_edits.json` panel 2:
    - `seed == 3` (requested);
    - `critic.seed_used == critic_seed(3, 1, 2)`;
    - `critic.status == "passed"`;
    - `still_sha256 == sha(images/panel_02.png)`.
  - A second call to `_phase2_shots_seed` with the same args makes **no** `run_jobs` call and prints the reuse line
    (the reuse key is unchanged).
- **ICT19. Flag off.**
  - `_phase_args` without `critic`: `run_jobs` is called once, no entry has `critic`, no line starts with `critic`,
    and `movie._image_critic` (patched to raise) is never called.
  - `test_set1`-`test_set15` pass unedited.

**`tests/test_movie_ui_critic.py` (new, Task 3)**:
- **ICT20. The log regex and the snapshot.**
  - `CRITIC_RE` matches the four 2.6 forms and a line with no detail.
  - It does not match `critic: done: ...` or `candidate 1/4 ok 2.0s`.
  - A seed-edit parser fed candidate lines plus `critic 1/3: ok (...)`, `critic 2/3: redo (...)`,
    `critic 2/3: flagged (...)` and `critic 3/3: unjudged (...)` gives
    `snapshot(...)["critic"] == {"ok": [1], "redo": [], "flagged": [2], "unjudged": [3]}`.
  - Without critic lines there is no `critic` key.
  - The same for a `movie` parser.
- **ICT21. The compose field, flag, argv and V1.**
  - `DEFAULT_FIELDS["critic"] is False`, and it sits right after `extra_refs`.
  - `dict(FIELD_FLAGS)["critic"] == ("--critic",)`, and it sits right before `extra_refs`.
  - `build_argv` with `critic=True` (shots, seed upload, `qwen21-q4`) puts `--critic` right after the seed-edit flags;
    with `critic=False` the argv equals today's golden argv.
  - V1: `critic="yes"` gives `critic must be true or false`; `critic=True` in chained mode, without a seed, or with
    `as-is` gives the 12f message.
  - `batch.FIELD_LEVELS["critic"] == "stills"`, and `"critic"` is in the group with `"seed_edit_model"`.
- **ICT22a. Seeds, pure.**
  - `validate_run_request` with `critic: True, model: qwen` gives `clean["critic"] is True`; with `zimage`,
    `critic is only for qwen`; with `critic: 1`, `critic must be true or false`; absent or `None`, no `critic` key.
  - `seed_edit_argv` with `critic: True` has `"--critic"` right before `"--candidates"`.
  - `srv._cand_critic` returns None for a missing, non-dict or bad-status block, and the clean dict for a valid one.
- **ICT23. Static UI pins.**
  - `c-critic-box`, `c-critic`, `se-critic-box` and `se-critic` each appear exactly once in `index.html`.
  - `index('id="c-sq-shots-note"') < index('id="c-critic-box"')`.
  - `app.js` contains:
    - `"function criticText(c) {"`;
    - `"function criticProgressText(c) {"`;
    - `'$("#c-critic").checked'`;
    - `"body.critic = true;"`;
    - `"critic: flagged — best score "`.
  - The hygiene regexes of `tests/test_movie_ui_seed_loras.py:343`.
  - `node --check app.js` when `node` is on PATH.
- **ICT24. The server never imports the critic.** The sources of `movie_ui_server.py`, `movie_ui_lib.py`,
  `movie_ui_seedgen.py` and `movie_ui_batch.py` do not contain `image_critic`.

**`tests/test_movie_ui_seedgen.py` (Task 3)**:
- **ICT22b. Seeds over HTTP.** It uses the `env` fixture and the `_create`/`_body` helpers of SGT23 (:686-716).
  - A body with `"critic": True` and `model: qwen` gives a 201. The job's `fields["critic"] is True`, its `argv`
    contains `--critic`, and the server-written `run.json` has no `critic` key.
  - After the test writes `candidates[0]["critic"] = {"status": "flagged", "score": 5, "defects": ["fused hand"], "reason": "r", "attempts": [{}, {}]}`
    into `run.json`, `GET` of the run returns that candidate with
    `critic == {"status": "flagged", "score": 5, "defects": ["fused hand"], "reason": "r", "attempts": 2}`.
  - The other candidates have no `critic` key.

### 6.3 Existing tests edited (only these pins)
- **Task 1:**
  - `tests/test_movie_ui_builder.py` `NEW_PY`: append `"image_critic.py", "bin/image-critic", "tests/test_image_critic.py"`.
  - `tests/test_qwen_edit.py` QET11 (:401-404): append the same three to the expected tail.
- **Task 2:**
  - `tests/test_movie_ui_builder.py` `test_mut26` `BASELINE` becomes the full sha of commit C2, in its own commit C3
    (Plan).
  - Append to the comment chain: `then to <C2 sha> (image critic hooks)`.
- **Task 3:**
  - `NEW_PY` gains `"tests/test_movie_ui_critic.py"` at the end, and QET11's tail gains it too.
  - `len(lib.FIELD_FLAGS) == 32` becomes `33` at the four F11 sites.
  - `FLAGS` in `tests/test_movie_ui_shots_seed.py:38-43` gains `"--critic"`.
  - `len(lib.DEFAULT_FIELDS) == 33` becomes `34` (`tests/test_movie_ui_extra_refs.py:60`).
  - `(28, 5, 33)` becomes `(29, 5, 34)` (`tests/test_movie_ui_batch.py:79`).
  - `EXPECTED_LEVELS` gains `"critic": "stills"`.
  - Any other pre-existing test that fails **only** because `DEFAULT_FIELDS` or `FIELD_FLAGS` gained this one entry
    (a count, or a literal list or dict of the tables) gets that literal updated, and nothing else. Each such file is
    named in the commit message.
- No other existing test is edited. In particular `tests/test_vlm_lifecycle.py`, `tests/test_character_*`,
  `tests/test_location_*` and SGT34 pass unchanged.

---

## 7. Live checks (the user runs these on macstudio; the assistant never accesses it)
- **ICL1. Calibration (K6).**
  - Gather at least 10 Qwen action edits with visible body defects and at least 10 clean ones.
  - With `bin/story-server mlx-vision` serving, run `bin/image-critic score --json <bad...> > bad.jsonl` and the same
    for the good ones.
  - For each `t` in 1..10, compute the bad caught (`score < t`) and the good failed.
  - Report the best `t` against the K6 rule. Also run once with `--seed <source>` and report whether scores separate
    better.
  - The outcome, as a follow-up and not part of this spec's tasks: a one-line `PASS_SCORE` change with ICT1's pin,
    a `JUDGE_WITH_SEED` change, or "not reliable on this VLM".
- **ICL2. Determinism.** The same file judged 3 times gives the same score (temperature 0).
- **ICL3. Seeds tab with the critic** (an action prompt, 4 candidates, Qwen):
  - the job log shows `critic i/4` lines and the `done:` line;
  - `run.json` blocks match the grid's verdict lines;
  - `bin/story-server status` reports `STOPPED` (or `SERVING`, when the postflight restored it for an empty queue);
  - record the wall time with and without the critic (K5).
- **ICL4. Shots movie from Compose with Critic on.**
  - `seed_edits.json` blocks are present, and each panel still is its best attempt (compare with
    `seed_edits/critic/*.png`).
  - Phase 3 renders.
  - During Phase 3, `bin/story-server status` is `STOPPED`.
- **ICL5. Cancel during a judge phase, then during a redo.**
  - Within 1 minute, `bin/story-server status` is `STOPPED`, or `SERVING` from the postflight with an empty queue.
  - `ps` shows no `seed_edit_mflux_child` or `qwenedit` child.
  - Every `cand_NN.png` or panel still opens.
- **ICL6. Rerun reuses.** Rerun the ICL4 story without `--redo`: no Qwen child starts, and the log says every panel
  is reused.
- **ICL7. Never together.**
  - During a judge phase, `ps` shows no Qwen child.
  - During a redo, `ps` shows no `mlx_vlm.server`.
  - Note the minimum `memory_pressure` / available GiB in each phase.

---

## 8. Review Focus (the 5 edge cases most likely to bite)
1. **Zero failures.**
   - There must be exactly one start and one stop, with no redo, no `r0` copies and no `wait_for_memory`.
   - A bug that calls `down()` when `active` is empty, or copies round 0 before knowing about the redo, adds a VLM
     swap or files (ICT4).
2. **Every image fails, or the rounds run out.**
   - Each redo batch holds all active jobs, and the strict `>` keeps the earliest best.
   - `output_path` must never point at a worse or half-written attempt.
   - The run continues (exit 0 / return 0), and the final lines are `flagged` even when the last attempt was blocked
     or unparseable (ICT6, ICT9).
3. **The VLM does not start, or dies mid-phase.**
   - `maybe_up` must be set **before** `restore_story_server(wait=True)`, so that a half-started server is stopped at
     the end.
   - After a transport error, no further `vlm_call` may happen in that phase (a 300 s timeout each), and no redo may
     run on a guess (ICT7).
4. **An interrupted run in the middle of a redo, and `ltx-movie`'s missing SIGTERM handler.**
   - Pending stage files are removed, and `output_path` stays the earlier best.
   - The stop is detached so it survives the cancel sweep, and the temporary handlers are restored.
   - The shots record may have a `flagged` interim block for a panel whose still is the earlier best. That is
     consistent with its `still_sha256` (ICT8).
5. **One-job batches, and blocked outputs.**
   - `shots --redo 3` gives a single-job batch. Its derived seed uses `n = 3`, and its stage basename stays unique
     for the bf16 child.
   - Blocked round-0 outputs never reach the VLM and never get a block. A blocked redo attempt keeps the job active
     without changing the best (ICT9).
   - Note: `--redo N` re-edits with the **requested** seed, so it reproduces the same round-0 image and the same
     derived seeds. To get new pictures for a flagged panel, the user changes `--image-seed` (Q6).

---

## 9. Acceptance criteria
- **IC-AC1** `judge_image`/`parse_verdict` follow 2.2: int and non-bool score, one quoted retry, `<think>` stripped
  (ICT2, ICT3).
- **IC-AC2** `edit_with_critic`:
  - redoes only failures, with `critic_seed`, at most `rounds` times;
  - keeps the strict best at `output_path`;
  - records the blocks of 2.4.4 and prints the 2.6 lines (ICT4-ICT6, ICT9-ICT11).
- **IC-AC3** The VLM lifecycle: never with Qwen, restored as found on every exit path, hands-off for foreign states
  (ICT5, ICT7, ICT8).
- **IC-AC4** `bin/image-critic` follows 2.7 (ICT12).
- **IC-AC5** `bin/seed-edit` and `bin/ltx-movie` are wired as in 2.8/2.9, flag off is unchanged, and the reuse key is
  unchanged (ICT14-ICT19).
- **IC-AC6** The movie-ui field, flag, argv, V1, seeds validation, candidate view, progress summary and page follow
  2.10/2.11, and the server never imports the critic (ICT20-ICT24).
- **IC-AC7** The full suite is green, with only the 6.3 pins edited. `test_mut26` is green at C3 and at every later
  commit. Every changed Python file compiles on 3.9.
- **IC-AC8** The user reports live checks ICL1-ICL7. K6 is decided from ICL1.

---

## Plan (task-level outline; commit order is binding)

### Task 1: `image_critic.py`, `bin/image-critic`, unit tests (commit C1)
- Files:
  - `image_critic.py`;
  - `bin/image-critic` (`git update-index --chmod=+x` or `chmod 755` before `git add`);
  - `tests/test_image_critic.py` (ICT1-ICT13);
  - the `NEW_PY` and QET11 pin edits (6.3).
- Verify:
  - `python3 -m pytest -q -p no:cacheprovider tests/test_image_critic.py tests/test_qwen_edit.py tests/test_movie_ui_builder.py`;
  - `/usr/bin/python3 -m py_compile image_critic.py bin/image-critic`.

### Task 2: the tool hooks (commit C2, then the test-only commit C3)
- **C2.** Files:
  - `bin/seed-edit` (2.8);
  - `bin/ltx-movie` (2.9);
  - `tests/test_seed_edit_tool.py` (ICT14-ICT16);
  - `tests/test_ltx_movie_shots_seed.py` (ICT17-ICT19).
  - At C2 `test_mut26` fails by design. Every other test passes.
- **C3.** It changes only `tests/test_movie_ui_builder.py`: `BASELINE = "<full sha of C2>"` and the comment-chain
  entry. Its message is `tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the image-critic hooks commit`.
- Verify at C3: the full suite, and `/usr/bin/python3 -m py_compile bin/seed-edit bin/ltx-movie`.
- Rules:
  - Never amend, rebase or squash C2 after C3 exists.
  - Every later commit that changes `bin/ltx-movie` (review fixes included) is followed at once by its own
    `BASELINE` commit, with the message pattern `... moves to the image-critic <what> commit`.
  - The PR merges with a merge commit, as PR #32 did, so the sha survives.

### Task 3: the movie-ui (commit C4)
- Files:
  - `movie_ui_lib.py`, `movie_ui_seedgen.py`, `movie_ui_server.py`, `movie_ui_batch.py`;
  - `static/movie-ui/index.html`, `static/movie-ui/app.js`;
  - `tests/test_movie_ui_critic.py` (ICT20-ICT24);
  - ICT22b in `tests/test_movie_ui_seedgen.py`;
  - the 6.3 Task 3 pins.
- It touches no `PIPELINE_FILES`, so it needs no re-baseline.
- Verify:
  - the full suite;
  - `/usr/bin/python3 -m py_compile movie_ui_lib.py movie_ui_seedgen.py movie_ui_server.py movie_ui_batch.py`;
  - `node --check static/movie-ui/app.js` when `node` is present.

### Verification (controller)
The `design-reviewer` agent reviews C1, C2+C3 and C4 before the work is declared done. Then ICL1-ICL7 go to the user.

---

## Open questions (each has a default the implementation uses)
- **Q1. Reused panels are not judged.** Default: no. Reuse means "accepted before", and judging them could redo them.
  To judge an old story, use `--redo` with a new `--image-seed`.
- **Q2. Judge with the seed?** Default: `JUDGE_WITH_SEED = False`. A reference doubles the image tokens and invites
  "pose differs" penalties. ICL1 compares both, and a change is one constant.
- **Q3. `VLM_MIN_AVAIL_GIB = 28.0`** is the stated 27.5 GiB VLM footprint rounded up. ICL7 measures the margin.
- **Q4. No rounds input in the UI.** Default: the UI never sends `--critic-rounds`, so it gets 2. The CLI has the
  option.
- **Q5. Attempt files are kept** under `critic/` for calibration. They are at most `rounds + 1` PNGs per redone job.
  There is no cleanup beyond the per-job stale-attempt deletion of 2.4.1 step 4.
- **Q6. `--redo` reproduces the same pictures** (same requested seed, same derived seeds). Default: documented only.
  A seed salt for redo runs would change the reuse key, which the approved design keeps on the requested seed.
