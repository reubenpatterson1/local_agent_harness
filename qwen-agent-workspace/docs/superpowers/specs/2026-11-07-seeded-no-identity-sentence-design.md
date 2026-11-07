# Seeded no identity sentence: a seeded Image: stops repeating the seed's description

Date: 2026-11-07

Status: design spec and implementation plan in one document. Problem report (2026-11-07, user): when a seed image is attached in shots or chained mode, the story's Image: text keeps repeating the seed's description, so the stills do not move along with the storyline. The user confirmed the problem is in the seeded flow. **The user's decision:** when a seed is attached, the pipeline does not paste each cast member's identity sentence into the Image: field. This spec settles the mechanism and the checks that depend on it. Choices this spec makes are marked **[spec choice]**. The implementer makes no design decisions.

Repository `/Users/reubenpatterson/local_agent_harness`. Worktree `$S/si-wt`, branch `seeded-no-identity`, off `origin/qwen-agent-redteam` at `ba05cb9`. `S` is `/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad`. `WS` is `qwen-agent-workspace/`. Every path is relative to `WS`, and every line number cites `ba05cb9`. `story_engine.py` at `ba05cb9` is byte-identical to `1940d1b`, the current `test_mut26` BASELINE.

Requirement IDs are **SI1-SI7**, tests **SIT1-SIT10**, KPIs **SIK1-SIK5**, live checks **L1-L3**. At `ba05cb9`, `git grep -nE "\bSI[0-9]+\b|\bSIT[0-9]+\b|\bSIK[0-9]+\b"` finds nothing.

**Out of scope** (the user's follow-up macstudio runs will diagnose these):
- the setting sentence, which is still pasted into every Image:
- `PLAN_PROMPT_TEMPLATE`, the location rule and location pins
- the likely remaining cause: every beat at one seed location, so the same setting sentence repeats

None of these is touched.

---

## 1. Cause (verified at `ba05cb9`)

1. **The identity sentence is the seed's description.** With a seed attached, `SEED_PARAGRAPH` (`story_engine.py:384-388`) tells the planner to "Describe every person it shows faithfully in cast", so every cast descriptor is a description of the seed.
2. **`pasted_pieces` pastes it into every still's prompt.** `pasted_pieces` (`:2249-2270`) builds `identities = [identity(by_cast[c]) for c in beat["cast"] if c in by_cast]` (`:2259`). It then builds `pieces = [setting] + identities + facing + [shot]` (`:2263`), which becomes the Image: of chained panel 1 (`:2265-2266`) and of every shots panel (`:2270`).
3. **Each panel's still is made from that Image: text.**
   - Shots: every panel's still is a Qwen edit of the seed, prompted by `SHOTS_SEED_EDIT_PREFIX` plus that panel's Image: (`bin/ltx-movie:146-150`, `_shots_seed_prompts` `:2385-2396`).
   - Chained: panel 1's Phase 1c seed edit is prompted by panel 1's Image: (`_panel1_edit_prompt` `:2274-2281`, `phase_seed_edit` `:2297`).

   The identity sentence is up to 73 words per character (`validate_descriptor` caps a descriptor at 70 words, `character_lib.py:328`), repeated in every panel. That pulls every edit back toward the seed.

## 2. Requirements

**SI1 The condition [spec choice: a named helper].** New function in `story_engine.py`, placed directly above `pasted_pieces`:

```python
def seed_omits_identities(ctx):
    """True when a seed image is attached in chained or shots mode (seeded no identity spec SI1):
    the Image: of chained panel 1 and of every shots panel then leaves out the cast identity
    sentences, because the seed already shows the people. ctx.seed_image, set whenever
    --seed-image is given, decides; ctx.seed_agent_image does not."""
    return bool(ctx.seed_image) and ctx.mode in ("chained", "shots")
```

The reasons for this condition:
- `ctx.seed_image` is the abspath of `--seed-image`, set whenever the flag is given (`bin/ltx-movie:1706`, `:1724`). `ctx.seed_agent_image` is the downscaled copy, which can be `None` in a real seeded run (`:1714-1719`).
- Existing tests build "seeded" contexts with `seed_agent_image` only (`tests/test_pinned_cast.py:198`, `:221`, `:371`; `tests/test_no_default_crowd.py:101`). Keying on `seed_image` leaves all of them unchanged.
- The helper has three callers (SI2, SI3, SI4), so it is not a single-use abstraction.

no_stills is excluded. A seeded no_stills run cannot happen: `bin/ltx-movie:3171-3175` refuses `--seed-image` with `--no-stills`. Even so, the no_stills Prompt: keeps its identities.

**SI2 The single change point: `pasted_pieces`.** Replace `:2263`

```python
    pieces = [setting] + identities + facing + [shot]
```
with
```python
    pieces = [setting] + ([] if seed_omits_identities(ctx) else identities) + facing + [shot]
```

The no_stills branch (`:2268-2269`) still uses `identities` directly and is unchanged. The `pasted_pieces` docstring gains one sentence (Plan E2).

Everything else reads `pasted_pieces`, so it follows with no edit:

| Reader | Where | Effect for a seeded chained panel 1 or shots panel |
|---|---|---|
| `panel_fields` Image assembly | `:3254-3257` | The Image: is setting, writer image, facing, shot. `cut = len(image) - 1 - len(facing)` still puts the writer text between the setting and the facing sentence, because the identities only ever sat before the cut. |
| `writer_targets` | `:3137-3147` | The image range grows by the identity word count. Example (the test plan, one cast member): shots panel 1 goes from `(32, 122)` to `(54, 144)`, and chained panel 1 from `(72, 122)` to `(94, 144)`. The writer gets the freed words. `build_panel_prompt` puts them into the `image: W1 to W2 words` key line (`:4115-4116`). |
| `cleanup_pieces` → `clean_writer` | `:2277-2282`. Used by `parse_panel_reply` (`:3193`), the critic patch path (`:4600`) and `_recheck_writers` (`:5312`) | An identity sentence is no longer blanked from the writer's Image text. The writer is told not to describe appearance (`KEY_LINE_TEMPLATES` `:2926-2932`, `:2959-2966`), so it does not write one. |
| plan check P10 word budget | `:2432-2443` | Fewer pasted words, so fewer P10 advisories. |

The no_stills Prompt:, the Motion: pieces and every chained panel k >= 2 are unchanged.

**SI3 N6 is skipped for a seeded Image:.** N6 (`:3432-3438`) is advisory and says "lacks cX's description word for word". With the identity left out on purpose, N6 would fire on every seeded panel. Replace `:3432`

```python
            if "N6" in ids:
```
with
```python
            if "N6" in ids and not seed_omits_identities(ctx):   # seeded no identity spec SI3
```

This is enough because N6 runs only on a pasted field (`:3413-3415`). In chained and shots mode that field is always Image:, and the no_stills Prompt: never meets the condition. N6 is in `GENERATION_CHECKS` (`:3815`) and not in `RECHECK_IDS` (`:5254-5255`), so a re-check never runs it.

**SI4 S9 is dropped for a seeded shots story [spec choice: filter in `split_shots`, not in `character_lib.py`].** `character_lib.shots_violations` S9 (`character_lib.py:1302-1307`) reports every library character (`ctx.members`, from `--character`) whose phrase is in an Image: without its descriptor. Without the identity sentence, every seeded shots panel that names a library character gets an S9 advisory: "copy in this sentence: The woman in grey is …". The robust engine keeps only S1 and S3 hard (`SHOTS_HARD_RULES`, `:4028`), so S9 is advisory. It is still spurious, and it would reach `story_checks.json`, the `Warning:` lines and the critic prompt's violation list. So it is dropped.

Replace `split_shots` (`:4031-4035`) with:

```python
def split_shots(violations, ctx=None):
    """(the S1/S3 violations, the other S rules) of a character_lib.shots_violations list: in the
    robust engine only S1 and S3 are hard (dialogue spec 6.3). With a ctx for which
    seed_omits_identities holds, every S9 is left out, because a seeded Image: has no identity
    sentence (seeded no identity spec SI4)."""
    left_out = SHOTS_HARD_RULES + (("S9",) if ctx is not None and seed_omits_identities(ctx)
                                   else ())
    return ([v for v in violations if parse_violation(v)["id"] in SHOTS_HARD_RULES],
            [v for v in violations if parse_violation(v)["id"] not in left_out])
```

Three call sites pass `ctx`:
- `panel_checks` (`:4012-4014`)
- `recheck` with a plan (`:5421-5423`)
- `recheck` without a plan (`:5468-5470`)

`plan_free_report` (`:5357`) builds its own ctx with `seed_image=None` (`:5340-5341`). It stays as it is.

`character_lib.py` is not changed, because the legacy path still needs S9 as it is (see SI7).

**SI5 Unseeded runs are byte-identical.** With `ctx.seed_image` falsy, all of these are unchanged byte for byte: `pasted_pieces`, `writer_targets`, every panel and critic prompt, `panel_fields`, `assemble`, every check message and every fixture. This holds for any mode, and for any `seed_agent_image`.

**SI6 Unchanged on purpose.**
- The `## Characters` block that `assemble` writes in shots mode (`:3275-3278`). It is the roster that S2 (`character_lib.py:1246-1252`) and `bin/ltx-story-manifest:412` read.
- `SHOTS_SEED_EDIT_PREFIX` (`bin/ltx-movie:146-150`) and the Phase 1c prompt.
- Every writer key line, including the `shots_image` and `chained_image` sentence "the pipeline adds each character's description … to this field itself" (`:2931-2932`, `:2964-2966`). For a seeded run that clause is no longer literally true. Its instruction, "Do not describe any character's appearance or clothing", is still what a seeded run wants, because the seed supplies the appearance. Rewording it is not part of the user's decision (Section 7, item 2; Open questions).
- `SEED_PARAGRAPH`, `SEED_PANEL`, the setting sentence, the plan prompt and the locations (out of scope).

**SI7 Scope.**
- `story_engine.py` is the only pinned file that changes, with numstat `22 9`.
- `bin/ltx-movie`, `bin/ltx-story-manifest`, `bin/ltx-story-images` and `character_lib.py` are untouched.
- No new import, standard library only.
- Saved stories: a story.md written before this change keeps its identity sentences until `--force-story` or a new story id. A re-check of such a story with `--seed-image` passes. `_recheck_writers` then leaves the identity sentences in the writer Image text, but no `RECHECK_IDS` check reads the writer Image text for identity words. N4 sees only phrases already in the beat cast. N7, N9 and N10 see no dialogue, cut or template words in an identity sentence. N3 and N13 read Motion only.
- A seeded story re-checked **without** `--seed-image` gets S9 advisories, if it has library characters. These are advisory only (exit 0).

## 3. Audit: every reader of an identity sentence or descriptor in an Image: (SI3, SI4, SI7)

| Reader | Where | Verdict for a seeded chained or shots story |
|---|---|---|
| N6 description (advisory) | `story_engine.py:3432-3438` | **Changed (SI3).** Skipped. |
| S9 cast description (advisory in the robust engine) | `character_lib.py:1302-1307`, via `split_shots` | **Changed (SI4).** Dropped at the three call sites. |
| S9 repair `repair_cast_descriptions` | `character_lib.py:1413-1474`, called only by `bin/ltx-movie` `_shots_repair_s9` (`:1956-1986`) ← `_shots_check` (`:1989-2001`) ← `_phase1_shots_finish` (`:2004`) | Not reachable. `_phase1_shots_finish` runs only on the legacy branch (`:1564`), after `phase1_story` returns early for the robust engine (`:1510-1511`). `--shots --seed-image` refuses `--story-legacy` and `--story-prompt-override` (`:1273-1279`). Seeded chained runs no S rule. Unchanged. |
| S2 characters list | `character_lib.py:1246-1252` | Reads the `## Characters` roster, which is unchanged (SI6). No change in result. |
| S6 cast count, S7 cast and extra | `character_lib.py:1274-1290` | Read phrases with `cast_text` and `find_phrases`, not descriptors. The writer's phrases stay. Unchanged. |
| S10 extra in cast shot | `character_lib.py:1308-1322` | Removing text can only remove person references; the descriptors are still masked by the `descriptions` list. No new findings. |
| S12 setting sentence | `character_lib.py:1328-1333` | The setting sentence is still pasted. Unchanged. |
| W2 shot type (`shots_advisories`) | `character_lib.py:1361-1371` | Reads phrases and `The shot is …`, which is still pasted. Unchanged. |
| N5 setting sentence | `story_engine.py:3418-3431` | The setting is still pasted. Unchanged. |
| N4 stray cast, N15 undeclared, N16 and N17 speaker | `:3407-3412`, `:3474-3479`, `:3545-3606` | Read writer text and beat cast (`on_screen` is the beat cast, `:3542-3543`). Unchanged. |
| P16 cast presence, Q1 spoken lines, P10 | plan scope and Dialogue: | P10 follows `pasted_pieces` (SI2). The others do not read Image:. |
| legacy `_validate_story_md` | `bin/ltx-movie` | Checks that fields are present. Unchanged. |
| `bin/ltx-story-manifest` cast LoRA names | `:899-902`: shots `cast_text(panel_text = Image:)` ∪ Motion: | Reads phrases, not descriptors. Before, the identity sentence guaranteed every beat-cast phrase was in the Image:. Now the phrase must come from the writer's Image: or Motion:, or from the facing sentence. **Risk: Section 7, item 1.** No code change. |
| `bin/ltx-movie` `_shots_stills_groups` | `:2165-2190` | Stills LoRA groups. Seeded shots stills are Qwen edits (`phase2_stills` → `_phase2_shots_seed`, `:2121-2122`), and `--stills-lora` is refused with them (`:1284-1287`). Not affected. |
| `bin/seam-report` | `:274-277` | Reads plan.json descriptors, not story.md. Unchanged. |
| `FORMAT_REFERENCE` | `story_engine.py:2697` | Video prompts with no identity sentence. Unchanged. |

## 4. Tests

**New file `tests/test_seeded_no_identity.py`**, 11 tests (Plan Task 1, Step 1; the full text is in the Plan section). It uses `story_engine_testutil` (`make_ctx`, `plan_json`, `panel_json`, `kyra`, `ronin`, `script_agent`) in the same way as `tests/test_no_default_crowd.py` and `tests/test_pinned_cast.py`. A seeded ctx is `seed_image="/s/seed.png", seed_agent_image="/s/seed-agent.png"`.

- **SIT1:** truth table of `seed_omits_identities`.
  - True: shots + seed, chained + seed, shots + `seed_image` only.
  - False: no_stills + seed, `seed_agent_image` only (shots and chained), unseeded (shots and chained).
- **SIT2:** seeded shots.
  - `pasted_pieces(...,1)["image"] == [HARBOUR, "The courier faces the camera.", "The shot is a medium shot."]` on a speaking panel.
  - `pasted_pieces(...,2)["image"] == [HARBOUR, "The shot is a wide shot."]`.
  - Each assembled Image: is exactly setting + writer + (facing) + shot, with no descriptor and no "The courier is ".
- **SIT3:** seeded chained.
  - Panel 1's image pieces are `[HARBOUR, facing, shot]`, where unseeded has `[HARBOUR, COURIER_ID, facing, shot]`.
  - Motion pieces are equal.
  - Panels 2 and 3: `pasted_pieces` and `panel_fields` are equal seeded and unseeded.
- **SIT4:** unseeded image pieces of a two-person beat are `[HARBOUR, COURIER_ID, MONK_ID, shot]`, and a `seed_agent_image`-only ctx assembles the same story.md byte for byte (SI5).
- **SIT5:** no_stills with a seed: `pasted_pieces` and `writer_targets` equal unseeded, and the Prompt: pieces still open with the identity sentence.
- **SIT6:** what follows from `pasted_pieces` (SI2).
  - The identity sentence is 22 words.
  - The image targets are as in the SI2 table. The motion targets are equal. The panel prompt holds `image: 54 to 144 words` (shots) or `image: 94 to 144 words` (chained).
  - A writer image that copies the identity sentence keeps it when seeded and is blanked unseeded (cleanup).
  - Two 70-word descriptors on one shots beat give exactly one `beat 1: P10` unseeded and none seeded.
- **SIT7:** N6.
  - `_field_checks(..., ids=("N6",))` on an Image: without the descriptor gives `panel 1: N6 description: Image: lacks c1's description word for word` unseeded and nothing seeded, in chained and in shots.
  - A seeded two-person `panel_checks` has no N6.
  - Seeded no_stills still reports N6 on its Prompt:.
- **SIT8 (two tests):** S9, on a 4-panel seeded shots story with `--character kyra ronin`.
  - Raw `shots_violations` has S9 on panels 1 and 4.
  - `split_shots(raw, ctx)` drops them, while `split_shots(raw)` and an unseeded ctx keep them. The hard list is identical.
  - `panel_checks` has no S9 and no N6.
  - `recheck`, with plan.json and then without it (the plan-free path), returns 0 with no S9 advisory and nothing on stderr.
- **SIT9 (Section 7, item 1):** a seeded two-person shots panel whose writer image names both phrases has an Image: that is exactly setting + writer + shot. It names "the courier" and "the old monk" and holds neither identity sentence. Its panel prompt still holds `Characters on screen in this panel, named only by these exact referring phrases: "the courier"; "the old monk"` and the `shots_image` text "where each character stands and which way they face".
- **SIT10:** for shots and chained, the seeded story.md equals the unseeded story.md with every `" " + identity sentence` removed, with the same plan and writer parts (a golden-free assembled example). In shots it keeps the `## Characters` block unchanged, every Image: opens with the setting sentence, and the speaking panel's Image: ends with the facing and shot sentences.

Before the code change the file gives `8 failed, 3 passed`. SIT4, SIT5 and the SIT8 recheck test pin behaviour that does not change, so they pass before and after. After the change it gives `11 passed`. Each edit was mutation-checked in a scratch copy: reverting any one of the edits in Plan Step 3 makes at least one test fail. Reverting the `pasted_pieces` edit fails 6; reverting the N6 edit or any one of the three `split_shots` call sites fails 1.

**Existing tests and golden fixtures: no edit.** Each seeded fixture has a reason it is unchanged:
- `tests/fixtures/pinned_cast/uncast_chained_seed.txt` is a **plan prompt**, built with `seed_agent_image="/s/seed.png"` only (`tests/test_pinned_cast.py:198`). `build_plan_prompt` does not read `pasted_pieces`. Both reasons keep it byte-identical.
- The other fixtures under `tests/fixtures/pinned_cast/` and `tests/fixtures/location/` are unseeded plan prompts or plans (`"seed_image": null` in `normalized_plan_chained.json`).
- The `writer_pacing` and `narrative_fidelity` hockey fixtures have `"seed_image": null`.
- No test builds a story context with a non-`None` `seed_image` (`grep -rn "make_ctx(.*seed_image" tests/` finds nothing).

So **no fixture is regenerated**. The scratch replay ran every story test file with no failure (Plan, "Replay").

## 5. Success criteria

| ID | Criterion | Verified by |
|---|---|---|
| SIK1 | The full suite has no failure beyond the baseline recorded at `ba05cb9`. The final run is `2 failed, P0+11 passed, 2 skipped` (P0 = the baseline PASSED count, expected 2669) | gate, V1 |
| SIK2 | Between `ba05cb9` and the final commit, the only pinned file changed is `story_engine.py` (numstat `22 9`), and `bin/` and `character_lib.py` have no diff | V1 |
| SIK3 | L1: a seeded 12-panel shots story has 0 Image: lines that contain any plan cast descriptor. Its stills follow the beats (pose, framing and action differ panel to panel). The seed's person is kept in at least 10 of 12 stills | L1 (user) |
| SIK4 | L2: a seeded chained story's panel 1 Image: contains no cast descriptor, and panel 1's still is the seed (or its Phase 1c edit) with the person kept | L2 (user) |
| SIK5 | L3: an unseeded shots story still has each beat-cast member's identity sentence in each Image: | L3 (user) |

Every SI requirement and SIT test is a must-have. There are no nice-to-haves.

## 6. Live checks (the user runs these on macstudio; the assistant never accesses macstudio)

Each run uses the robust engine through Compose in the movie UI, or `bin/ltx-movie`, with a **new story id** so that no old story.md or plan.json is reused. In each run's `generated/stories/<id>/`, run this report:

```bash
python3 - <<'EOF'
import json
plan = json.load(open("plan.json"))
text = open("story.md", encoding="utf-8").read()
images = [l[len("Image: "):] for l in text.split("\n") if l.startswith("Image: ")]
descs = [c["descriptor"].lower() for c in plan["cast"]]
phrase = {c["id"]: c["phrase"].lower() for c in plan["cast"]}
print("panels", len(plan["beats"]), "image lines", len(images))
print("image lines with a descriptor", sum(any(d in i.lower() for d in descs) for i in images))
print("panels whose Image: misses a beat-cast phrase",
      [k for k, (b, i) in enumerate(zip(plan["beats"], images), 1)
       if any(phrase[c] not in i.lower() for c in b["cast"] if c in phrase)])
print("distinct locations", len(set(b["location"] for b in plan["beats"])),
      "distinct settings in Image:", len(set(l["setting"] for l in plan["locations"]
                                            if any(l["setting"] in i for i in images))))
EOF
```

- **L1, seeded shots (SIK3).** Use shots mode, 12 panels, `--seed-image` with one person, and a `--seed-edit-model`. Use a narrative that moves through several actions, such as `A courier runs through a rainy market, ducks under an awning, reads a letter, and sets off again toward the harbour.`
  - Expected from the report: `image lines 12`, `image lines with a descriptor 0`.
  - Then look at `images/panel_01.png` … `panel_12.png`. The stills differ in pose, framing and action and follow the beats. The seed's person is the same person in at least 10 of the 12 stills that show them.
  - Record the "misses a beat-cast phrase" list and the location counts. They are the input to the follow-up.
- **L2, seeded chained (SIK4).** Chained mode, 4 panels, the same seed. Expected: `image lines 1` and `image lines with a descriptor 0`, and panel 1's still keeps the seed's person.
- **L3, unseeded shots (SIK5).** Shots mode, 4 panels, no seed. Expected: `image lines with a descriptor` equals `image lines`. Every Image: still carries the identity sentences, exactly as before.

**If L1's stills still look alike**, the report shows whether the cause is the one the user expects: `distinct locations 1`, with the same setting sentence in all 12 Image: lines. That is the out-of-scope follow-up (setting sentence, plan prompt, locations) and needs its own spec. If instead the person is lost or swapped in more than 2 stills, or the "misses a beat-cast phrase" list is not empty, see Section 7, item 1 and the Open questions.

## 7. Review focus

1. **People are now named only by their referring phrase.** `SHOTS_SEED_EDIT_PREFIX` says "leave out anyone the new shot does not describe". Without identities, a person in a seeded shot is described only by the writer's referring phrase and, on a speaking panel, the facing sentence. Three things depend on that:
   - **The Qwen edit.** It must see each on-screen person's phrase, or it may drop them.
   - **Telling people apart.** In a seed with two people, the identity sentence also told the edit which person was which. Now only the phrase does that.
   - **LoRA names.** `bin/ltx-story-manifest:899-902` takes a library character's video-LoRA names from the phrase in Image: or Motion:.

   **Verified at `ba05cb9`:** the `shots_image` key line (`:2959-2966`) does **not** literally say "name each character by their referring phrase". It asks for "where each character stands and which way they face". The panel prompt's header line (`:2903-2904`) says "Characters on screen in this panel, named only by these exact referring phrases: …". The shots Motion line (`:2967-2972`) names exactly one character by phrase. So naming every person in a two-person Image: is implied, not required. SIT9 proves the pipeline keeps both phrases when the writer writes them. L1's "misses a beat-cast phrase" list measures whether the writer does.
2. **The stale key-line clause** (SI6). "the pipeline adds each character's description … to this field itself" is not true for seeded runs. It is kept because rewording the writer prompt is outside the user's decision. The instruction it carries, to write no appearance, is still right for a seeded run.
3. **Condition key.** The condition is `ctx.seed_image`, not `seed_agent_image` (SI1). SIT1 and SIT4 pin it, so every existing seeded-plan-prompt test stays byte-identical.
4. **S9 and N6 are suppressed only for seeded runs.** Unseeded shots with `--character` still get S9 (SIT8 `split_shots(raw, plain_ctx)`), and unseeded N6 still fires (SIT7).

---

## Plan

**House rules** (every task):
- Work only in `$S/si-wt`. Never touch `/Users/reubenpatterson/local_agent_harness`.
- Never stash, reset, amend, push or open a PR.
- Never contact a server, render, run a model, ssh to any host, or run tests against the real HOME.
- Edit tracked files with the Edit or Write tool.
- An Edit's old text occurs exactly once in the file. If it does not, stop and report.
- Every changed `.py` file compiles on `/usr/bin/python3` (3.9) and `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
- Stage only the paths the task names, and check `git diff --cached --name-only` before every commit.
- End each commit with a second `-m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.

**Replay.** The whole of Task 1 was replayed in a scratch copy of `ba05cb9` (`$S/si-replay`, from `git archive`).
- Before the code change, the new file gave `8 failed, 3 passed`. After the eight edits it gave `11 passed`.
- `git diff --no-index --numstat` of `story_engine.py` gave `22 9`.
- Both Pythons compiled both files.
- The full suite in the replay (not a git checkout, so `test_mut26` skips) is recorded in "Replay result" at the end of this section.

### Before Task 1: the baseline (controller)

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/si-baseline; mkdir -p $D
cd $S/si-wt/qwen-agent-workspace
git branch --show-current                                   # seeded-no-identity
git diff --stat ba05cb9 HEAD -- . ':(exclude)docs' | tail -1 # no output (only this spec is committed)
git status --short                                          # no output
wc -l story_engine.py tests/test_movie_ui_builder.py        # 5481, 302
df -g . | tail -1                                           # at least 5 GiB free
python3 -B -m pytest tests/ -q -rA -p no:cacheprovider > $D/baseline-pytest.txt 2>&1; tail -1 $D/baseline-pytest.txt
grep -E '^(FAILED|ERROR)' $D/baseline-pytest.txt
grep -c '^PASSED ' $D/baseline-pytest.txt                   # record as P0
for f in tests/test_ltx_movie_offline.py tests/test_qwen_agent_image_oneshot.py tests/test_qwen_agent_danger_auto_approve.py tests/test_qwen_agent_context_budget.py tests/test_qwen_agent_session_memory.py; do echo "$f $(python3 -B $f 2>&1 | tail -1)"; done > $D/baseline-ok-lines.txt
grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $D/baseline-pytest.txt   # 1
```

Expected:
- The summary is `2 failed, 2669 passed, 2 skipped`. That is the story-no-default-crowd Task 2 result, `$S/cr-baseline/task-2-pytest.txt`, on a tree identical to `ba05cb9`.
- The only `FAILED` lines are the 2 known failures, `tests/test_character_dataset.py::test_d2_copied_literals_match_the_spike` and `tests/test_story_engine.py::test_rst62_import_sets`.
- There is no `ERROR` line.
- `test_mut26` passes.

If `test_tr27_fanout_two_rounds_and_missing_reasons` or `test_trt45_query_endpoints_refuse_browsers_and_bad_queries` also fails, rerun the two alone. `2 passed` means the baseline stands. Any other difference: stop and report.

Then write the gate files. They are scratch files and never staged. They come from the crowd plan's files: `$S/cr-baseline/gate.py` still carries the tool-restriction wording, once in the docstring and twice as the file name.

```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
D=$S/si-baseline
python3 - "$S/cr-baseline/gate.py" "$D/gate.py" <<'EOF'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
for old, new, n in (("The task gate of the story agent tool restriction plan", "The task gate of the seeded no identity plan", 1),
                    ("tests/test_qwen_agent_tool_restriction.py", "tests/test_seeded_no_identity.py", 2)):
    assert s.count(old) == n, old
    s = s.replace(old, new)
open(sys.argv[2], "w", encoding="utf-8").write(s)
EOF
sed -e 's#/cr-baseline#/si-baseline#' -e 's#/cr-wt/#/si-wt/#' $S/cr-baseline/gate-run.sh > $D/gate-run.sh; chmod +x $D/gate-run.sh
cat > $D/expected-failures.txt <<'EOF'
# seeded no identity plan: baseline passes allowed to be lost. Columns: first task, last task, test id, note
1 1 tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged story_engine.py changes in Task 1; Task 2 moves BASELINE
1 2 tests/test_fleet_tracing.py::test_tr27_fanout_two_rounds_and_missing_reasons flaky timing test; every gate block reruns it alone, where it must pass
1 2 tests/test_fleet_tracing.py::test_trt45_query_endpoints_refuse_browsers_and_bad_queries flaky timing test; every gate block reruns it alone, where it must pass
EOF
grep -c si-baseline $D/gate-run.sh; grep -c /si-wt/ $D/gate-run.sh; grep -c test_seeded_no_identity $D/gate.py   # 1, 1, 2
```

**The gate** for task N is `zsh $S/si-baseline/gate-run.sh N`. It is a full `pytest -rA` run of about 20 minutes, compared test by test with the baseline. It prints:
- `disk ok`
- the pytest summary
- the gate line, then `GATE PASS`
- `2 passed` for the flake rerun
- `ATK2 OK lines unchanged`

The 2 known failures stay failing ("baseline failures still failing 2 of 2"). The only baseline pass allowed to be lost is the one in `expected-failures.txt` for that task. On `GATE STOP`, stop and report the `UNEXPECTED` or `NEW-TEST-FAIL` ids with `python3 -B -m pytest -q -p no:cacheprovider --tb=short <ids>`.

### Task 1: the code change and its tests (one commit)

**Files:**
- `story_engine.py` (pinned)
- `tests/test_seeded_no_identity.py` (new)

- [ ] **Step 1: Write `tests/test_seeded_no_identity.py`** with the Write tool, exactly:

```python
"""Tests for the seeded-no-identity change (docs/superpowers/specs/2026-11-07-seeded-no-identity-
sentence-design.md: SIT1-SIT10): with a seed image in chained or shots mode, the Image: of chained
panel 1 and of every shots panel leaves out the cast identity sentences, so the seed's
description is not repeated in every still's prompt.

Run from the workspace root: python3 -m pytest -q -p no:cacheprovider tests/test_seeded_no_identity.py
Stdlib plus pytest. No test reads the real HOME, renders or contacts a model server: every test
runs under the autouse story_env fixture (a temporary HOME, character library and LoRA catalog)
and builds prompts and story.md text in memory or under tmp_path.
"""

import importlib.machinery
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, WS)
sys.path.insert(0, os.path.join(WS, "tests"))

import story_engine_testutil as seu  # noqa: E402


def _load(name, rel):
    return importlib.machinery.SourceFileLoader(name, os.path.join(WS, rel)).load_module()


se = _load("story_engine_for_seeded_no_identity", "story_engine.py")
lib = _load("character_lib_for_seeded_no_identity", "character_lib.py")
ltx_movie = _load("ltx_movie_for_seeded_no_identity", os.path.join("bin", "ltx-movie"))

SEED = dict(seed_image="/s/seed.png", seed_agent_image="/s/seed-agent.png")
COURIER_ID = "The courier is " + seu.COURIER + "."
MONK_ID = "The old monk is " + seu.MONK + "."
MEDIUM = "The shot is a medium shot."
WIDE = "The shot is a wide shot."
FACING = "The courier faces the camera."


@pytest.fixture(autouse=True)
def story_env(monkeypatch, tmp_path):
    return seu.set_story_env(monkeypatch, tmp_path)


@pytest.fixture
def ws(tmp_path):
    return seu.make_ws(tmp_path)


def _ctx(ws, mode, seeded, n=3, **kw):
    fields = dict(SEED) if seeded else {}
    fields.update(kw)
    return seu.make_ctx(se, ws, mode=mode, panels=n, **fields)


def _plan(ctx, n=3, speaker_beat=None, two_cast_beat=None):
    raw = seu.plan_json(ctx.mode, n)
    if speaker_beat:
        raw["beats"][speaker_beat - 1]["speaker"] = raw["cast"][0]["id"]
    if two_cast_beat:
        raw["beats"][two_cast_beat - 1]["cast"] = ["c1", "c2"]
    return se.normalize_plan(ctx, raw)[0]


def _parts(ctx, plan, n=3, image=None):
    """Parsed writer parts of panel_json replies; image replaces every image reply."""
    parts = []
    for k in range(1, n + 1):
        reply = seu.panel_json(ctx.mode, k, plan["cast"][0]["phrase"])
        if image is not None and "image" in reply:
            reply["image"] = image
        if "dialogue" in se.panel_keys(ctx, plan, k):
            reply["dialogue"] = "The letter is here."
        parts.append(se.parse_panel_reply(ctx, plan, k, json.dumps(reply)))
    return parts


def _image(ctx, plan, parts, k):
    return dict(se.panel_fields(ctx, plan, parts, k))["Image"]


def _write(ctx, text, name="check.md"):
    path = os.path.join(ctx.story_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# --- SIT1: the condition (SI1) ------------------------------------------------------------------

def test_sit1_seed_omits_identities_only_for_a_seeded_chained_or_shots_movie(ws):
    cases = ((dict(mode="shots", **SEED), True), (dict(mode="chained", **SEED), True),
             (dict(mode="shots", seed_image="/s/seed.png"), True),
             (dict(mode="no_stills", **SEED), False),
             (dict(mode="shots", seed_agent_image="/s/seed-agent.png"), False),
             (dict(mode="chained", seed_agent_image="/s/seed-agent.png"), False),
             (dict(mode="shots"), False), (dict(mode="chained"), False))
    for kw, expected in cases:
        assert se.seed_omits_identities(seu.make_ctx(se, ws, **kw)) is expected, kw


# --- SIT2: a seeded shots Image: (SI1, SI2) -----------------------------------------------------

def test_sit2_seeded_shots_image_has_setting_facing_and_shot_but_no_identity(ws):
    ctx = _ctx(ws, "shots", True)
    plan = _plan(ctx, speaker_beat=1)
    assert se.pasted_pieces(ctx, plan, 1)["image"] == [seu.HARBOUR, FACING, MEDIUM]
    assert se.pasted_pieces(ctx, plan, 2)["image"] == [seu.HARBOUR, WIDE]
    parts = _parts(ctx, plan)
    for k, writer, tail in ((1, parts[0]["image"], FACING + " " + MEDIUM),
                            (2, parts[1]["image"], WIDE), (3, parts[2]["image"], MEDIUM)):
        image = _image(ctx, plan, parts, k)
        assert image == seu.HARBOUR + " " + writer + " " + tail, k
        assert seu.COURIER not in image and "The courier is " not in image, k


# --- SIT3: seeded chained panel 1, and later panels unchanged (SI1, SI2) ------------------------

def test_sit3_seeded_chained_panel_1_has_no_identity_and_later_panels_are_unchanged(ws):
    seeded, plain = _ctx(ws, "chained", True), _ctx(ws, "chained", False)
    splan, pplan = _plan(seeded, speaker_beat=1), _plan(plain, speaker_beat=1)
    assert se.pasted_pieces(seeded, splan, 1)["image"] == [seu.HARBOUR, FACING, MEDIUM]
    assert se.pasted_pieces(plain, pplan, 1)["image"] == [seu.HARBOUR, COURIER_ID, FACING, MEDIUM]
    assert (se.pasted_pieces(seeded, splan, 1)["motion"]
            == se.pasted_pieces(plain, pplan, 1)["motion"])
    for k in (2, 3):
        assert se.pasted_pieces(seeded, splan, k) == se.pasted_pieces(plain, pplan, k), k
    parts = _parts(seeded, splan)
    image = _image(seeded, splan, parts, 1)
    assert image == seu.HARBOUR + " " + parts[0]["image"] + " " + FACING + " " + MEDIUM
    for k in (2, 3):
        assert (se.panel_fields(seeded, splan, parts, k)
                == se.panel_fields(plain, pplan, parts, k)), k


# --- SIT4: unseeded and seed_agent_image-only runs are unchanged (SI5) --------------------------

def test_sit4_unseeded_images_keep_every_identity_sentence(ws):
    for mode in ("shots", "chained"):
        plain = _ctx(ws, mode, False)
        agent_only = _ctx(ws, mode, False, seed_agent_image="/s/seed-agent.png")
        plan = _plan(plain, two_cast_beat=1)
        assert se.pasted_pieces(plain, plan, 1)["image"] == [seu.HARBOUR, COURIER_ID, MONK_ID,
                                                             MEDIUM], mode
        parts = _parts(plain, plan)
        assert se.assemble(agent_only, plan, parts) == se.assemble(plain, plan, parts), mode
        assert COURIER_ID in _image(plain, plan, parts, 1), mode


# --- SIT5: no_stills keeps its identities, seeded or not (SI2) ----------------------------------

def test_sit5_no_stills_prompt_keeps_identities_even_with_a_seed(ws):
    seeded, plain = _ctx(ws, "no_stills", True), _ctx(ws, "no_stills", False)
    splan, pplan = _plan(seeded), _plan(plain)
    for k in (1, 2, 3):
        assert se.pasted_pieces(seeded, splan, k) == se.pasted_pieces(plain, pplan, k), k
        assert se.pasted_pieces(seeded, splan, k)["prompt"][0] == COURIER_ID, k
        assert se.writer_targets(seeded, splan, k) == se.writer_targets(plain, pplan, k), k


# --- SIT6: what follows from pasted_pieces (SI2) ------------------------------------------------

def test_sit6_writer_targets_cleanup_and_plan_budget_follow_pasted_pieces(ws):
    used = se._words(COURIER_ID)
    assert used == 22
    for mode, k, unseeded, seeded_targets in (("shots", 1, (32, 122), (54, 144)),
                                              ("chained", 1, (72, 122), (94, 144))):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        splan, pplan = _plan(seeded), _plan(plain)
        assert se.writer_targets(plain, pplan, k)["image"] == unseeded, mode
        assert se.writer_targets(seeded, splan, k)["image"] == seeded_targets, mode
        assert (se.writer_targets(seeded, splan, k)["motion"]
                == se.writer_targets(plain, pplan, k)["motion"]), mode
        assert "image: %d to %d words" % seeded_targets in se.build_panel_prompt(
            seeded, splan, _parts(seeded, splan), k), mode
        # cleanup_pieces: a writer image that copies the identity sentence keeps it when seeded.
        writer = COURIER_ID + " " + seu.panel_json(mode, k)["image"]
        assert COURIER_ID not in _parts(plain, pplan, image=writer)[0]["image"], mode
        assert _parts(seeded, splan, image=writer)[0]["image"].startswith(COURIER_ID), mode
    # Plan-scope P10: two long descriptors leave the writer too few image words unseeded only.
    long_desc = "a " + " ".join(["tall"] * 68) + " man"
    cast = [{"id": "c1", "phrase": "the courier", "descriptor": long_desc},
            {"id": "c2", "phrase": "the old monk", "descriptor": long_desc}]
    for seeded_run, expected in ((False, 1), (True, 0)):
        ctx = _ctx(ws, "shots", seeded_run)
        raw = seu.plan_json("shots", 3, cast=cast)
        raw["beats"][0]["cast"] = ["c1", "c2"]
        plan, shape = se.normalize_plan(ctx, raw)
        hard, advisory = se.plan_checks(ctx, plan, shape)
        assert len([m for m in hard + advisory if m.startswith("beat 1: P10 ")]) == expected


# --- SIT7: N6 is silent for a seeded Image: and still fires unseeded (SI3) ----------------------

def test_sit7_n6_skips_a_seeded_image(ws):
    bare = seu.HARBOUR + " The courier stands on the left of the frame. " + MEDIUM
    for mode in ("shots", "chained"):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        plan = _plan(plain)
        lib_ = se._character_lib(ws)
        args = (1, "t", [("Image", bare)], {"Image": bare}, ("N6",), ())
        assert se._field_checks(plain, lib_, plan, *args) == (
            [], ["panel 1: N6 description: Image: lacks c1's description word for word"]), mode
        assert se._field_checks(seeded, lib_, plan, *args) == ([], []), mode
        splan = _plan(seeded, two_cast_beat=1)
        parts = _parts(seeded, splan)
        text = se.assemble(seeded, splan, parts)
        hard, advisory = se.panel_checks(seeded, splan, parts, text, _write(seeded, text))
        assert [m for m in hard + advisory if " N6 " in m] == [], mode
    no_stills = _ctx(ws, "no_stills", True)
    plan = _plan(no_stills)
    prompt = seu.HARBOUR + " The courier pedals along the quay. " + MEDIUM
    assert se._field_checks(no_stills, se._character_lib(ws), plan, 1, "t", [("Prompt", prompt)],
                            {"Prompt": prompt}, ("N6",), ()) == (
        [], ["panel 1: N6 description: Prompt: lacks c1's description word for word"])


# --- SIT8: S9 is left out for a seeded shots story with library characters (SI4) ----------------

def _pinned_story(ws, story_env, seeded):
    seu.kyra(story_env["lib"])
    seu.ronin(story_env["lib"])
    members = lib.resolve_cast([(None, "kyra"), (None, "ronin")])
    ctx = _ctx(ws, "shots", seeded, n=4, members=members)
    raw = seu.plan_json("shots", 4)
    raw["cast"] = [{"id": "c1", "phrase": "the woman in grey", "descriptor": seu.DESC_K},
                   {"id": "c2", "phrase": "the ronin", "descriptor": seu.DESC_R}]
    raw["beats"][2]["cast"] = ["c2"]
    plan = se.normalize_plan(ctx, raw)[0]
    parts = [se.parse_panel_reply(ctx, plan, k, json.dumps(
        seu.panel_json("shots", k, "the woman in grey"))) for k in range(1, 5)]
    return ctx, plan, parts, se.assemble(ctx, plan, parts)


def test_sit8_s9_is_left_out_of_a_seeded_shots_story(ws, story_env):
    ctx, plan, parts, text = _pinned_story(ws, story_env, True)
    path = _write(ctx, text)
    assert "The woman in grey is " not in text and '- "the woman in grey": ' in text
    panels = se._story_manifest(ws)._parse_prompts_md(path)[1]
    raw = lib.shots_violations(text, panels, 4, ctx.members, True, ignore_facing=True,
                               speaking_actions=2)
    s9 = [v for v in raw if " S9 " in v]
    assert [v.split(":")[0] for v in s9] == ["panel 1", "panel 4"]
    assert [v for v in se.split_shots(raw, ctx)[1] if " S9 " in v] == []
    assert [v for v in se.split_shots(raw)[1] if " S9 " in v] == s9
    assert se.split_shots(raw, ctx)[0] == se.split_shots(raw)[0]
    hard, advisory = se.panel_checks(ctx, plan, parts, text, path)
    assert [m for m in hard + advisory if " S9 " in m or " N6 " in m] == []
    plain_ctx, _plain_plan, _plain_parts, plain_text = _pinned_story(ws, story_env, False)
    assert "The woman in grey is %s." % seu.DESC_K in plain_text
    assert [v for v in se.split_shots(raw, plain_ctx)[1] if " S9 " in v] == s9


def test_sit8_recheck_of_a_seeded_shots_story_reports_no_s9(ws, story_env, monkeypatch, tmp_path,
                                                             capsys):
    seu.script_agent(monkeypatch, tmp_path)
    monkeypatch.setattr(ltx_movie, "WS", ws)
    ctx, plan, _parts_, text = _pinned_story(ws, story_env, True)
    _write(ctx, text, "story.md")
    with open(os.path.join(ctx.story_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert [m for m in advisories if " S9 " in m] == []
    os.remove(os.path.join(ctx.story_dir, "plan.json"))     # the plan-free re-check path
    rc, advisories = se.recheck(ctx, ltx_movie._validate_story_md)
    assert rc == 0
    assert [m for m in advisories if " S9 " in m] == []
    assert capsys.readouterr().err == ""


# --- SIT9: a seeded two-person shot still names both people (Review Focus 1) --------------------

def test_sit9_seeded_two_person_shot_names_both_phrases(ws):
    ctx = _ctx(ws, "shots", True)
    plan = _plan(ctx, two_cast_beat=1)
    writer = ("The courier stands on the left of the frame and faces right toward the old monk. "
              "The old monk stands on the right of the frame and faces left. "
              + seu.panel_json("shots", 1)["image"])
    parts = _parts(ctx, plan, image=writer)
    image = _image(ctx, plan, parts, 1)
    assert image == seu.HARBOUR + " " + writer + " " + MEDIUM
    assert "the courier" in image.lower() and "the old monk" in image.lower()
    assert COURIER_ID not in image and MONK_ID not in image
    prompt = se.build_panel_prompt(ctx, plan, parts, 1)
    assert ('Characters on screen in this panel, named only by these exact referring phrases: '
            '"the courier"; "the old monk"\n') in prompt
    assert "where each character stands and which way they face" in prompt


# --- SIT10: a seeded story.md is the unseeded one without identity sentences (SI1, SI6) ---------

def test_sit10_seeded_story_md_is_unseeded_text_minus_identity_sentences(ws):
    for mode in ("shots", "chained"):
        seeded, plain = _ctx(ws, mode, True), _ctx(ws, mode, False)
        plan = _plan(plain, speaker_beat=2, two_cast_beat=1)
        parts = _parts(plain, plan)
        plain_text = se.assemble(plain, plan, parts)
        seeded_text = se.assemble(seeded, plan, parts)
        assert plain_text.count(" " + COURIER_ID) == (3 if mode == "shots" else 1), mode
        assert plain_text.count(" " + MONK_ID) == 1, mode
        assert seeded_text == plain_text.replace(" " + COURIER_ID, "").replace(" " + MONK_ID, "")
        if mode == "shots":
            assert ('## Characters\n- "the courier": %s.\n- "the old monk": %s.\n'
                    % (seu.COURIER, seu.MONK)) in seeded_text
            images = [l for l in seeded_text.split("\n") if l.startswith("Image: ")]
            assert len(images) == 3 and all(l.startswith("Image: " + seu.HARBOUR + " ")
                                            for l in images)
            assert images[1].endswith(" " + FACING + " " + se.shot_sentence(plan["beats"][1]))
```

The file ends with a single newline after the last line. It is 311 lines.

- [ ] **Step 2: Check that the new tests fail first.** `python3 -B -m pytest -q -p no:cacheprovider tests/test_seeded_no_identity.py | tail -1` prints `8 failed, 3 passed`. The three that pass are `test_sit4_…`, `test_sit5_…` and `test_sit8_recheck_…`, which pin behaviour that does not change.

- [ ] **Step 3: Edit `story_engine.py`, eight Edits.**

E1 (`:2249`, the helper; SI1). Old:
```python
def pasted_pieces(ctx, plan, k):
```
New:
```python
def seed_omits_identities(ctx):
    """True when a seed image is attached in chained or shots mode (seeded no identity spec SI1):
    the Image: of chained panel 1 and of every shots panel then leaves out the cast identity
    sentences, because the seed already shows the people. ctx.seed_image, set whenever
    --seed-image is given, decides; ctx.seed_agent_image does not."""
    return bool(ctx.seed_image) and ctx.mode in ("chained", "shots")


def pasted_pieces(ctx, plan, k):
```

E2 (`:2253-2254`, the `pasted_pieces` docstring). Old:
```python
    (shot prompt format spec SF6). The planned camera sentence is always listed, even when
    CM4 leaves it out of the assembled field."""
```
New:
```python
    (shot prompt format spec SF6). The planned camera sentence is always listed, even when
    CM4 leaves it out of the assembled field. When seed_omits_identities(ctx), the image pieces
    have no identity sentences (seeded no identity spec SI1); the no_stills prompt keeps them."""
```

E3 (`:2263`; SI2). Old:
```python
    pieces = [setting] + identities + facing + [shot]
```
New:
```python
    pieces = [setting] + ([] if seed_omits_identities(ctx) else identities) + facing + [shot]
```

E4 (`:3432`; SI3). Old:
```python
            if "N6" in ids:
```
New:
```python
            if "N6" in ids and not seed_omits_identities(ctx):   # seeded no identity spec SI3
```

E5 (`:4031-4035`; SI4). Old:
```python
def split_shots(violations):
    """(the S1/S3 violations, the other S rules) of a character_lib.shots_violations list: in the
    robust engine only S1 and S3 are hard (dialogue spec 6.3)."""
    return ([v for v in violations if parse_violation(v)["id"] in SHOTS_HARD_RULES],
            [v for v in violations if parse_violation(v)["id"] not in SHOTS_HARD_RULES])
```
New: the SI4 function text, exactly as in Section 2.

E6 (`:4014`, `panel_checks`). Old:
```python
            speaking_actions=2))
```
New:
```python
            speaking_actions=2), ctx)
```

E7 (`:5423-5424`, `recheck` with a plan). Old:
```python
                    ignore_facing=True))
                hard += shots_hard
```
New:
```python
                    ignore_facing=True), ctx)
                hard += shots_hard
```

E8 (`:5470-5471`, `recheck` without a plan). Old (the first line has 62 leading spaces):
```python
                                                              ignore_facing=True))
        advisories = others
```
New:
```python
                                                              ignore_facing=True), ctx)
        advisories = others
```

No other line of `story_engine.py` changes. In particular, `plan_free_report`'s `split_shots` call (`:5357`) and the `panel_fields` docstring stay as they are.

- [ ] **Step 4: Verify.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/si-wt/qwen-agent-workspace
python3 -B -m pytest -q -p no:cacheprovider tests/test_seeded_no_identity.py 2>&1 | tail -1   # 11 passed
python3 -B -m pytest -q -p no:cacheprovider tests/test_story_engine.py tests/test_pinned_cast.py tests/test_shot_format.py tests/test_dialogue.py tests/test_narrative_fidelity.py tests/test_location_story.py tests/test_writer_pacing.py tests/test_no_default_crowd.py tests/test_shots_mode.py 2>&1 | tail -1   # only test_rst62_import_sets fails (baseline)
git diff --numstat -- story_engine.py                                   # 22	9	qwen-agent-workspace/story_engine.py
grep -c "seed_omits_identities" story_engine.py                         # 6
git diff --stat -- bin/ character_lib.py tests/fixtures | wc -l         # 0
for py in /usr/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do $py -B -c 'import sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
print("compiled %d" % (len(sys.argv) - 1))' story_engine.py tests/test_seeded_no_identity.py; done   # compiled 2, twice
zsh $S/si-baseline/gate-run.sh 1
```
`seed_omits_identities` appears 6 times: the definition, the `pasted_pieces` docstring, E3, E4, and the `split_shots` docstring and body.

Expected gate output:
- the summary `3 failed, P0+10 passed, 2 skipped`
- `lost 1 (listed 1, unexpected 0); new tests 11, not passing 0; baseline failures still failing 2 of 2`
- `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`

The single loss is `test_mut26`, because `story_engine.py` now differs from BASELINE `1940d1b`.

- [ ] **Step 5: Commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/si-wt/qwen-agent-workspace
git add story_engine.py tests/test_seeded_no_identity.py
git diff --cached --name-only | wc -l    # 2
git commit -m "story_engine: with a seed image, the chained panel 1 and shots Image: leave out the cast identity sentences; N6 and S9 stay quiet for them (seeded-no-identity SI1-SI4, SIT1-SIT10)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: the `test_mut26` re-baseline (a test-only commit; never amend)

The baseline chain moves from `1940d1b` (story-no-default-crowd) to the Task 1 commit.

- [ ] **Step 1:**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/si-wt/qwen-agent-workspace
SHA=$(git log -1 --format=%H -- bin/qwen-agent story_engine.py bin/ltx-movie); echo $SHA
test "$SHA" = "$(git rev-parse HEAD)" && echo "SHA is HEAD"
git diff --name-only 1940d1ba1bbf40ea487cc9dcec59b4ac051e91ff $SHA -- bin/ltx-movie bin/ltx-mlx-render bin/ltx-story-images bin/ltx-story-manifest bin/ltx-story-video bin/ltx-chain bin/ltx-generate bin/ltx-host-prep bin/ltx-host-restore bin/character bin/lora-catalog bin/judge-story bin/judge-clips bin/judge-stills bin/iterate-story bin/qwen-agent story_engine.py character_lib.py character_dataset.py lora_catalog.py pipeline_log.py z_image_skill.py ltx2_mlx_video_skill.py
```
Expected:
- a 40-hex `SHA`
- `SHA is HEAD`
- exactly one path, `qwen-agent-workspace/story_engine.py`

The 23 paths are written out because zsh does not word-split a variable.

- [ ] **Step 2: Two Edits to `tests/test_movie_ui_builder.py`.** Type the 40 characters of `SHA` where the word SHA appears.
  - Replace `then to 1940d1ba1bbf40ea487cc9dcec59b4ac051e91ff (story-no-default-crowd).` with `then to 1940d1ba1bbf40ea487cc9dcec59b4ac051e91ff (story-no-default-crowd), then to SHA (seeded-no-identity).`. The old text occurs once, at the end of the long comment line `:291`.
  - Replace `    BASELINE = "1940d1ba1bbf40ea487cc9dcec59b4ac051e91ff"` (`:293`) with `    BASELINE = "SHA"`.

- [ ] **Step 3: Verify and commit.**
```bash
S=/private/tmp/claude-502/-Users-reubenpatterson/19c452c6-34f7-42df-83ac-562127f4caf9/scratchpad
cd $S/si-wt/qwen-agent-workspace
SHA=$(git rev-parse HEAD)
grep -c "    BASELINE = \"$SHA\"" tests/test_movie_ui_builder.py                                          # 1
grep -c "(story-no-default-crowd), then to $SHA (seeded-no-identity)\.$" tests/test_movie_ui_builder.py   # 1
git diff --stat -- tests/test_movie_ui_builder.py | tail -1        # 1 file changed, 2 insertions(+), 2 deletions(-)
zsh $S/si-baseline/gate-run.sh 2
git add tests/test_movie_ui_builder.py
git diff --cached --name-only    # exactly qwen-agent-workspace/tests/test_movie_ui_builder.py
git commit -m "tests/test_movie_ui_builder.py: test_mut26 BASELINE moves to the seeded-no-identity commit" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected gate output:
- the summary `2 failed, P0+11 passed, 2 skipped`
- `lost 0 (listed 0, unexpected 0); new tests 11, not passing 0; baseline failures still failing 2 of 2`
- `GATE PASS`, `2 passed` and `ATK2 OK lines unchanged`
- `grep -c '^PASSED tests/test_movie_ui_builder.py::test_mut26_pipeline_files_are_unchanged$' $S/si-baseline/task-2-pytest.txt` prints `1`

### Verification (controller)

- **V1:** confirm SIK1 and SIK2 from Task 2's gate output and these commands:
  - `git diff --numstat ba05cb9 HEAD -- story_engine.py`: `22 9`
  - `git diff --name-only ba05cb9 HEAD | grep -v '^qwen-agent-workspace/docs/' | wc -l`: `3`
  - `git diff ba05cb9 HEAD -- bin/ character_lib.py tests/fixtures | wc -l`: `0`
- **V2:** an Opus design review (the `design-reviewer` agent) of the two commits against this spec, using Section 7 as the focus. A finding is fixed in a new commit. If that commit touches `story_engine.py`, another Task 2-style baseline commit follows, and V1 runs again.
- **V3:** live checks L1-L3 (Section 6). The user runs them on macstudio; the assistant never does.

### Replay result

The full suite was run in `$S/si-replay` after the Task 1 edits, with `python3 -B -m pytest tests/ -q -rA -p no:cacheprovider --continue-on-collection-errors`. The result was `3 failed, 2666 passed, 8 skipped, 1 error`. All 11 tests of `tests/test_seeded_no_identity.py` passed. Every failure, error and extra skip comes from the replay being an archive copy and not a git worktree, and none touches this change:
- the 2 known failures, `test_d2_copied_literals_match_the_spike` and `test_rst62_import_sets`
- `tests/test_qwen_agent_fleet.py::test_t30_researcher_constants_and_prompt` and the collection error of `tests/test_researcher_think_off.py`. Both open `$S/agent/qwen-agent-unsafe`, which lives outside the workspace and is not in the archive copy.
- the 6 skip lines: `not a git checkout` (`test_mut26` and the `d210c26` tests), plus 2 host-only skips

No existing test needed an edit. The real gate runs in `$S/si-wt`, a git worktree, where these environment effects do not apply.

## Open questions

None block this plan. Two follow-ups depend on L1, and each would need its own spec:
1. If L1's "misses a beat-cast phrase" list is not empty, or the person is dropped or swapped in a seeded two-person shot: should the seeded `shots_image` and `chained_image` key lines say explicitly to name every on-screen character by their referring phrase, and drop the now-untrue "the pipeline adds each character's description" clause (Section 7, items 1-2)?
2. If L1's stills still look alike with `distinct locations 1`: the setting sentence, plan prompt and location follow-up that the user has already scoped out.
