# ltx-movie: composition tightening — stop later panels re-stating appearance

Date: 2026-09-13
Branch: `ltx2-mlx-video-pipeline`
Status: ready for `code-executor`
Follows: `docs/superpowers/specs/2026-09-13-ltx-movie-panel-drift-fix.md` ("Step 1"), which is
implemented, tested (118/118) and validated end-to-end. This spec **extends** Step 1's
`SEED_IMAGE_PREFACE` and leaves every Step 1 code path intact. It supersedes nothing.

---

## 1. Problem and success criteria

### 1.1 What the real run found

`bin/ltx-movie "a young woman with curly red hair looks into the camera, then turns and walks
away down a quiet street at dusk" --story-id drift_red_test --seed-image ~/Downloads/red.jpg
--panels 6 --force-story` produced
`generated/stories/drift_red_test/story.md`, which is the evidence base for this spec.
Three observations, measured not guessed:

**O1 — identity is fixed.** Step 1 worked. The `Style:` mechanism carries the reference's
subject identity to every panel. Independently eyeball-confirmed. Nothing in this spec
weakens it.

**O2 — every later panel's `Image:` field re-states the full appearance list.** Panels 2-6
each open `A <shot type> of a young woman with voluminous, tightly curled auburn-red hair,
warm light-brown skin with scattered freckles across her nose and cheeks, groomed dark arched
eyebrows, brown eyes, and glossy pink lips, seen from behind as she ...`. Measured overlap
between each later panel's `Image:` content words and Panel 1's `Style:` content words
(3+ letters, glue words removed):

| Panel | `Style:` words recovered | of 42 | words in `Image:` |
|---|---|---|---|
| 2 | 37 | 88% | 89 |
| 3 | 34 | 81% | 85 |
| 4 | 34 | 81% | 89 |
| 5 | 34 | 81% | 93 |
| 6 | 34 | 81% | 96 |

Phase 2 then appends the 44-word `Style:` text on top, so panel 4's composed txt2img prompt
is 133 words carrying the appearance attribute list **twice** and roughly 34 words of actual
composition — a 26% composition share.

**O3 — composition collapsed in the pixels.** Panels 4 and 6 are written as
`a wide shot ... seen from behind ... receding into the distance` and `an extreme wide shot
... a tiny distant figure at the end of the street`. The stills actually generated for both
are close-up front-facing portraits nearly indistinguishable from panel 1. The volume of
repeated identity language out-weighs the shot-type / camera-angle / distance language in the
txt2img model's attention.

**O4 — `Style:` was emitted in all six panels**, not once. Mechanically harmless
(`_style_text` in `bin/ltx-story-images` reads `panels[0]["style"]` only; Step 1 §10 already
documents a stray `Style:` in panels 2..N as parsed-never-read and not a validation error),
but it is the same underlying behaviour as O2: the model treats each panel as a
self-contained restatement of the movie's look.

### 1.2 Root cause (three mechanisms, all addressed below)

**R1 — the ban was on *copying*, not on *restating*.** The current preface says
`Do NOT copy Panel 1's Image: description into the later panels`. The model complied with the
letter: it did not copy, it re-derived the same content in slightly varied words. The
codebase already contains a ban the *same model demonstrably obeys* — the `Motion:` field's
(`STORY_PROMPT_TEMPLATE`, line 103): "the appearance, wardrobe, setting and lighting are
already fixed by that image and must not be described again in Motion: -- **not word for word
and not reworded**". Every `Motion:` field in the failing story.md is appearance-free. The
"and not reworded" clause is the difference, and this spec copies it.

**R2 — no positive substitute was offered.** The `Motion:` rule works partly because it
supplies a replacement construction: "Refer to each recurring character by one short referring
phrase of at most five words ... (for example 'the woman in grey')". The model used
"the curly-haired woman" consistently in all six `Motion:` fields. The preface told later
`Image:` fields what not to write and never told them what to write instead, so the model fell
back on its default noun-phrase grammar: `A <shot> of <fully-described subject>, <action>`.
That grammar is what buries composition behind appearance.

**R3 — the override is 1000 words upstream of the rule it overrides.** `STORY_PROMPT_TEMPLATE`
line 101 ("... must repeat that exact description VERBATIM -- word for word, not paraphrased")
is concrete and imperative and sits *after* the preface, because
`build_story_prompt` assembles `SEED_IMAGE_PREFACE + "\n\n" + rendered`. The preface's
abstract conditional override ("This replaces the verbatim-repetition rule below for
everything that is visible in the attached image") loses to the later concrete rule. The model
obeyed the rules at the bottom of the prompt (`Motion:` constraints) and disobeyed the ones at
the top.

### 1.3 Success criteria (binding unless marked NON-BINDING)

- **SC1** `python3 tests/test_ltx_movie_offline.py` exits 0. Every pre-existing check passes,
  except the two deliberately updated in §7.1 (`L25d`, `L30e`), which pass in their new form.
- **SC2** `python3 tests/test_ltx_story_images.py`, `python3 tests/test_ltx_story_video.py`,
  `python3 tests/test_ltx_chain.py`, `python3 tests/test_ltx_mlx_render.py` each exit 0,
  unchanged and unedited.
- **SC3** Every mutation in §7.6 makes the named check FAIL when applied and the file returns
  to green when reverted.
- **SC4** On the re-run of the real end-to-end command (§8 A3), every panel 2..N `Image:`
  field recovers **fewer than 50%** of Panel 1's `Style:` content words, measured by the
  script in §8 A3.2 — i.e. `bin/ltx-movie` prints **zero** `Warning: panel N: Image: restates`
  lines during Phase 1.
- **SC5** On that same re-run, every panel 2..N `Image:` field is 45-70 words (measured;
  §8 A3.2 reports the counts. Tolerance: at most one panel outside the band, and no panel
  above 85 words).
- **SC6** Human eyeball on the re-run's stills: a panel whose `Image:` says *wide shot* /
  *extreme wide shot* / *seen from behind* / *receding into the distance* renders as an actual
  wide, back-facing, receding shot, not as a close-up front-facing portrait. At least three
  visibly distinct camera distances across the six panels. Explicitly a human judgement, not a
  machine check.
- **SC7** Human eyeball on that same re-run: identity is **still** held — the subject in
  panels 2..6 is recognisably the person in `~/Downloads/red.jpg` (hair, skin tone, freckles,
  palette, render style). This is the Step 1 win and it must not regress. If SC6 passes and
  SC7 fails, report that and stop; do not change anything further.
- **SC8 (NON-BINDING, report-only)** `grep -c '^Style: ' generated/stories/drift_red_test/story.md`
  is `1`. See §3.4 for why this is deliberately not a pass/fail gate.

### 1.4 Must-have vs nice-to-have

Must-have: §4 (preface rewrite), §5 (postface), §7 (tests), §8 (acceptance).
Nice-to-have: §6 (the advisory echo warning). It is specified completely and **is** to be
implemented — "nice-to-have" only in the sense that the pipeline is correct without it. Do not
skip it; SC4's machine check depends on it.

---

## 2. Scope

### 2.1 In scope

- `bin/ltx-movie` only: `import re` comment (line 74), `SEED_IMAGE_PREFACE` (lines 141-153),
  a new `SEED_IMAGE_POSTFACE` constant, `build_story_prompt` (lines 156-161), three new
  module-level helpers, and four printed lines in `phase1_story`.
- `tests/test_ltx_movie_offline.py`: two updated checks, four new test functions.

### 2.2 Explicitly OUT of scope

- **img2img / pixel conditioning of panels 2..N remains out of scope.** Do not add
  `ZImageImg2ImgPipeline`, `image=`/`strength=` parameters, any panel-to-panel or
  panel-to-reference pixel conditioning, or any TODO, hook, flag, config key or comment
  anticipating one.
- **`_compose_prompt`, `_panel_seed`, `_style_text` and every other line of
  `bin/ltx-story-images` are correct and validated. Do not edit that file.** Do not edit
  `tests/test_ltx_story_images.py`.
- **`bin/ltx-story-manifest` (the parser) is not edited.** `p["style"]` already exists.
- **`STORY_PROMPT_TEMPLATE` and `STORY_PROMPT_TEMPLATE_NO_STILLS` are not edited.** Check
  `L25a` asserts the unseeded prompt is byte-identical to
  `STORY_PROMPT_TEMPLATE.format(...)`; the non-seeded path must stay bit-for-bit identical.
  Every new instruction lives in the preface or the postface, both of which are used only on
  seeded, non-`--no-stills` runs.
- **`_validate_story_md` gains no new violation.** Its signature, its return contract and all
  five `L32` checks are unchanged. Rationale in §3.5.
- **Do not touch** the pre-existing dirty files `bin/ltx-story-video`, `ltx_ceiling.json`,
  `ltx_video_skill.py`, `z_image_skill.py`.
- **Do not change the string `"Review story.md above. Enter to continue, Ctrl-C to abort: "`.**
  The `pexpect` acceptance driver (§8 A3.1) matches on it exactly.
- **Do not change the `Style:` field's 40-70 word budget.** It is the mechanism that fixed
  identity (O1). Shrinking it to buy prompt headroom trades a solved problem for an unsolved
  one. Headroom comes from the later panels' `Image:` budget instead (§3.2).
- No drift metric, no CLIP similarity, no retry loop, no new CLI flag.

---

## 3. Design decisions (made here; the executor makes none)

### 3.1 Decision C1 — the ban becomes "not reworded", and it names the attribute classes

The replacement wording lifts the exact clause the model already obeys in `Motion:`
("must not be described again ... -- not word for word and not reworded") and additionally
**enumerates the banned attribute classes** ("appearance, wardrobe, hair, skin, face, build,
materials, colour palette, lighting character and rendering style"). Enumeration matters
because the failing output shows the model reasoning at the level of *which noun phrases a
subject needs*, not at the level of *whose description this is*. It also states the mechanical
reason ("the Style: text is already appended automatically"), which the failing run's prompt
never gave.

### 3.2 Decision C2 — later panels' `Image:` budget drops to 45-70 words

`STORY_PROMPT_TEMPLATE` asks for 70-90 words; the current preface repeats "its own 70-90 word
description". With appearance removed, 70-90 words of pure composition is more than a single
still needs, and the model will refill the budget with the thing it just deleted. Both the
preface and the postface therefore state **45-70 words, for panels 2 onward only**, and both
say explicitly that this replaces the 70-90 figure elsewhere in the prompt. Panel 1 keeps
70-90: it is the literal description of the attached reference and its text never drives a
txt2img call (Phase 2 copies the reference for panel 1).

Effect on the composed prompt: 45-70 words of composition + 40-70 words of `Style:` = 85-140
words, with composition leading and roughly 55-60% composition share, against the observed
133 words at 26% composition share. The ratio is the fix; the absolute length is secondary.

### 3.3 Decision C3 — later `Image:` fields get a positive construction: shot type first, then a short referring phrase

Two instructions, both modelled on rules the same model already follows:

1. **Field order**: "shot type first, then camera viewpoint and height, then the subject's
   short referring phrase, then the action and placement in frame, then the setting." This
   front-loads exactly the tokens that O3 shows being drowned out.
2. **Referring phrase**: "at most five words ... the same phrase the Motion: fields use,
   chosen the first time that subject appears and reused word for word in every later Image:
   and Motion: field -- for example 'the woman in grey' or 'the red car'. That phrase is the
   only appearance detail a later Image: field may carry."

Reusing the *same* phrase the `Motion:` fields already use is deliberate: it is one convention
instead of two, it is already demonstrated working in the failing run ("the curly-haired
woman" in all six `Motion:` fields), and it keeps `Image:` and `Motion:` naming the subject
identically, which the manifest and the video layer both benefit from.

### 3.4 Decision C4 — the stray `Style:` problem is attacked by prompt wording, but is NOT a pass/fail gate

Attacked, because O2 and O4 share a root cause: the model builds one per-panel template from
Panel 1's shape and repeats it. A sentence that states the exact field list a later panel has
("A later panel has exactly three fields, in this order: Image:, Motion:, Narration: -- and no
Style: line."), placed in the *later-panels* paragraph where the model decides a panel's
contents rather than in the *Style:* paragraph where it decides the field's text, is one
sentence and plausibly fixes both. The postface repeats the field list as a final checklist.
The existing sentence "Emit the Style: line exactly once, in Panel 1, and never in any other
panel." is kept verbatim (check `L30b` pins it) and gains a following sentence giving the
mechanical reason.

Not a gate, because: (a) it is mechanically inert — Step 1 §10 already classifies a stray
`Style:` as parsed-never-read, and `_style_text` provably reads `panels[0]` only; (b) the
current, already-emphatic wording failed once, so a second round of emphasis has real odds of
failing again, and a binding SC that we expect might fail turns a successful composition fix
into a reported failure; (c) making it a hard validation error would abort a completed 27B
multimodal generation over dead text. It is therefore **SC8, report-only**: §6's advisory
warning surfaces it automatically, and the completion report states whether it landed.

### 3.5 Decision C5 — the "restated appearance" check is an advisory WARNING, not a `_validate_story_md` violation

The check is a word-overlap heuristic. `_validate_story_md`'s violations are **fatal**:
`phase1_story` prints them and returns 1, and on re-run without `--force-story` Phase 1 is
skipped but the same file is re-validated and fails again. There is no override flag. A false
positive would therefore strand a legitimate story behind a word counter with no escape but
hand-editing prose until a counter is satisfied. That is the wrong failure mode for a
heuristic.

Instead: a new pure function `_style_echo_warnings(panels)` returns human-readable strings,
`phase1_story` prints them as `Warning: ...` on stdout immediately above the existing review
prompt (so the human sees them at the exact moment they decide whether to continue), and the
return code is untouched. Under `--no-review` they still print, into `movie.log`, which makes
SC4 a grep.

The margin justifies the heuristic. Measured on the real failing story.md and on a
hand-written compliant panel, using the exact implementation in §6:

| Case | `Style:` words | threshold | overlap | verdict |
|---|---|---|---|---|
| failing run, panels 2-6 | 42 | 22 | 34-37 | warns (correct) |
| compliant composition-only panel (§7.4 fixture) | 29 | 15 | 4 | silent (correct) |

A 4-vs-15-vs-34 separation is not a marginal signal. Panel 1 is exempt by construction: it is
the literal description of the reference image, so ~95% `Style:` overlap is *correct* there.

**The three constants, and which of them carries the short-`Style:`-line rule.** Added
2026-09-13 after the §7.7 N-12 mutation came back green; see §6.2.1 for the proof and §7.7's
N-12 row for the verification transcript. The short-`Style:`-line exemption is enforced by
`_ECHO_MIN_OVERLAP`, the floor inside `threshold`'s `max()` — **not** by the
`if len(style_words) >= _ECHO_MIN_STYLE_WORDS:` guard, which is inert at the constants this
spec ships. `len(shared) <= len(style_words)` always (`shared` is a subset), and
`threshold >= _ECHO_MIN_OVERLAP` always, so with `_ECHO_MIN_STYLE_WORDS == _ECHO_MIN_OVERLAP ==
12` every story the guard would skip is already unflaggable. The guard is retained as a
statement of intent and a cheap early-out; it is **not** a second, tighter floor.

The 12-word figure is not tuned to a fixture. `SEED_IMAGE_PREFACE` (§4, the rendered template
at `bin/ltx-movie:151`) asks for `Style: <40-70 words on a single line ...>`, and the one real
seeded run measured 42 content words. A `Style:` line below 12 *content* words is therefore
roughly 3x under the bottom of the requested range — degenerate output, not a case the check
is meant to adjudicate. Both constants stay at 12: that is the smallest `_ECHO_MIN_OVERLAP`
that keeps the `L36e` boundary (11-of-20 silent, 12-of-20 warns) and the largest
`_ECHO_MIN_STYLE_WORDS` that never narrows coverage below that floor.

| Constant | Value | What it decides | Load-bearing? |
|---|---|---|---|
| `_ECHO_MIN_OVERLAP` | 12 | absolute floor on shared words before anything is flagged; this is what exempts short `Style:` lines | yes — `N-8`, `N-9`, `L36e` |
| `_ECHO_FRACTION` | 0.5 | the proportional half of the threshold, which dominates for `Style:` lines over 22 content words (the real range) | yes — `N-8`, `N-9`, `L36j` |
| `_ECHO_MIN_STYLE_WORDS` | 12 | early-out for `Style:` lines the floor already covers | no — provably inert while `<= _ECHO_MIN_OVERLAP` (§6.2.1) |

### 3.6 Decision C6 — a `SEED_IMAGE_POSTFACE`, appended after the rendered template

R3 is the highest-leverage single change: put the override **after** the rule it overrides.
`build_story_prompt` becomes
`SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE`.

- `STORY_PROMPT_TEMPLATE` is still untouched, so `L25a` (byte-identical unseeded prompt) and
  every non-seeded behaviour are unaffected.
- The postface is a short numbered checklist, not a restatement of the preface. It carries
  only the two overrides (VERBATIM scope, word budget) plus the per-panel field list.
- It ends with `Do not verify the file with run_python or any other tool. Emit no other text.`
  — the same terminator `STORY_PROMPT_TEMPLATE` ends with — so the last thing the model reads
  is still a clean stop instruction rather than an override rule.
- Cost: two existing checks (`L25d`, `L30e`) assert `p_on.endswith(p_off)` and must be
  updated. This is deliberate, is listed in §7.1, and both are strengthened rather than
  weakened (they move from `endswith` to an exact whole-assembly equality).

### 3.7 Decision C7 — `import re`'s `noqa` comment is corrected

`bin/ltx-movie:74` reads
`import re  # noqa: F401 -- kept for parity with the workspace's stdlib-only import convention`.
§6 makes `re` genuinely used, so the comment becomes false. Change the line to bare
`import re`. This is an orphan created by this change, not unrelated cleanup.

---

## 4. Change 1 of 5 — replace `SEED_IMAGE_PREFACE`

`bin/ltx-movie`, lines 141-153. Replace the entire assignment with exactly the following.
Paragraphs 1, 2, 5, 6 and 8 are byte-identical to the current text except for the one added
sentence in paragraph 6 noted below. Paragraphs 3, 4 and 7 are new or rewritten.

```python
SEED_IMAGE_PREFACE = """An image is attached to this message. It is the movie's literal opening frame: Panel 1's still will NOT be rendered from your text -- the attached image IS Panel 1's still, exactly as it is.

Before you write anything, look at the attached image and describe what it actually shows. Panel 1's Image: field must be a faithful, literal description of that attached image and nothing else -- its subject, pose, framing, setting, lighting, colour palette and visual style as they really appear -- not a generative prompt, not an embellishment, and not an invention. Do not add people, objects, actions or scenery that are not visible in the attached image, and do not omit the ones that are.

Panel 1's Motion: and Narration: fields are written normally, and Panel 2 onward continue the narrative as usual -- but every later panel's Image: field must stay visually consistent with what you actually observed in the attached image: the same characters, wardrobe, setting, lighting and style. That consistency is already handled for you: the Style: line described below is appended word for word to the end of every panel's image prompt by the pipeline, before the panel is rendered. So: Do NOT copy Panel 1's Image: description into the later panels, and do not restate its content in your own words either. Appearance, wardrobe, hair, skin, face, build, materials, colour palette, lighting character and rendering style must not be described again in any Image: field after Panel 1 -- not word for word and not reworded. Writing them a second time puts the same attribute list into the image prompt twice and crowds out the shot type, camera angle and framing that are the only things making that panel different from its neighbours.

Each later panel's Image: field is 45-70 words -- shorter than the 70-90 words asked for below, which applies to Panel 1 only, because the appearance words are gone -- and carries ONLY that panel's own composition: the shot type, the camera viewpoint and height, where the subject sits in the frame and which way it faces, the action or pose at that instant, the distance between camera and subject, and the setting and background elements in view. Write it in that order: shot type first, then camera viewpoint, then the subject's short referring phrase, then the action and placement, then the setting. Refer to each recurring subject by one short referring phrase of at most five words -- the same phrase the Motion: fields use, chosen the first time that subject appears and reused word for word in every later Image: and Motion: field, for example "the woman in grey" or "the red car". That phrase is the only appearance detail a later Image: field may carry. A later panel has exactly three fields, in this order: Image:, Motion:, Narration: -- and no Style: line.

Panel 1, and only Panel 1, carries one extra field, written as its LAST line, after Narration:, in exactly this form:

Style: <40-70 words on a single line describing ONLY what is identical in every panel of this movie, taken from the attached image: the recurring subjects and their fixed appearance (wardrobe, colours, markings, distinguishing features), the materials and textures, the colour palette, the lighting character, and the rendering style, medium and lens character>

Write the Style: line as a plain comma-separated list of attributes with no sentence subject: it is appended word for word to the end of every panel's image prompt, so it must read correctly after any panel's Image: text. It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action, or where anything sits in the frame -- those change from panel to panel and each panel's own Image: field sets them. Emit the Style: line exactly once, in Panel 1, and never in any other panel. The pipeline reads that line from Panel 1 alone, so a Style: line written under Panel 2 or later is dead text that is never read.

This replaces the verbatim-repetition rule below for everything that is visible in the attached image: describe those elements once, in Panel 1's Image: field, name their fixed attributes in the Style: line, and do not repeat either description in later panels. The verbatim-repetition rule below still applies to any NEW recurring character or visual element you introduce later that is not visible in the attached image."""
```

### 4.1 Substrings preserved deliberately (do not paraphrase them)

Pinned by existing checks; all are present above, unchanged:

| Substring | Pinned by |
|---|---|
| `An image is attached to this message.` | `L25b`, `L27e` |
| `Panel 1's still will NOT be rendered from your text` | `L25e` |
| `faithful, literal description of that attached image` | `L25e` |
| `not a generative prompt` | `L25e` |
| `must stay visually consistent with what you actually observed` | `L25e` |
| `Panel 1, and only Panel 1, carries one extra field` | `L30b` |
| `40-70 words on a single line` | `L30b` |
| `appended word for word to the end of every panel's image prompt` | `L30b` |
| `Emit the Style: line exactly once, in Panel 1, and never in any other panel.` | `L30b` — note the trailing **period**; the new reason sentence follows as a separate sentence and must not turn this into a colon |
| `It must not mention composition, framing, shot type, camera angle, viewpoint, pose, action` | `L30c` |
| `Do NOT copy Panel 1's Image: description into the later panels` | `L31b` — still present, now followed by `, and do not restate its content in your own words either.` |
| `This replaces the verbatim-repetition rule below for everything that is visible in the attached image` | `L31c` |
| `The verbatim-repetition rule below still applies to any NEW recurring character` | `L31d` |

### 4.2 Removed deliberately

The old paragraph-3 tail
`each later panel's Image: field is its own 70-90 word description of that panel's own composition, and the shared look is carried forward by the Style: field described next instead of by repetition.`
is gone: the 70-90 figure is wrong for later panels now (C2), and "its own ... description of
that panel's own composition" was too weak to displace the model's default grammar (R2).
No existing check asserts that sentence.

---

## 5. Change 2 of 5 — add `SEED_IMAGE_POSTFACE` and assemble it

### 5.1 Edit — new constant

Insert immediately after the `SEED_IMAGE_PREFACE` assignment (i.e. between it and the blank
lines preceding `def build_story_prompt`), verbatim:

```python
SEED_IMAGE_POSTFACE = """Two of the rules above are overridden for this movie, because an image is attached and Panel 1's still IS that image:

1. The VERBATIM-repetition rule applies only to a new recurring character or element you introduce later that is NOT visible in the attached image. For everything that IS visible in it, write the description once, in Panel 1's Image: field, put its fixed attributes in Panel 1's Style: line, and never describe it again -- not word for word and not reworded. No Image: field after Panel 1 may carry hair, skin, face, build, wardrobe, colour-palette, lighting-character or rendering-style words; those panels name their subject with the short referring phrase and nothing else.
2. The 70-90 word length applies to Panel 1's Image: field. Every later panel's Image: field is 45-70 words of composition only, in this order: shot type, camera viewpoint and height, the subject's referring phrase, the action and placement in frame, the setting and background.

Panel 1 has four fields, in this order: Image:, Motion:, Narration:, Style:. Every other panel has exactly three, in this order: Image:, Motion:, Narration: -- and no Style: line.

Do not verify the file with run_python or any other tool. Emit no other text."""
```

### 5.2 Edit — `build_story_prompt` (lines 156-161)

Before:
```python
def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
    rendered = template.format(narrative=narrative, story_id=story_id, panels=panels)
    if seed_image and not no_stills:
        return SEED_IMAGE_PREFACE + "\n\n" + rendered
    return rendered
```
After:
```python
def build_story_prompt(narrative, story_id, panels, no_stills=False, seed_image=False):
    template = STORY_PROMPT_TEMPLATE_NO_STILLS if no_stills else STORY_PROMPT_TEMPLATE
    rendered = template.format(narrative=narrative, story_id=story_id, panels=panels)
    if seed_image and not no_stills:
        # The postface goes AFTER the rendered template on purpose. The template's
        # VERBATIM-repetition rule and its 70-90 word Image: budget are concrete and
        # imperative; a preface-only override of them sits ~1000 words upstream and lost
        # to them in the 2026-09-13 drift_red_test run, where every later panel re-typed
        # the full appearance list. Restating the two overrides last is the fix.
        return SEED_IMAGE_PREFACE + "\n\n" + rendered + "\n\n" + SEED_IMAGE_POSTFACE
    return rendered
```

The `no_stills` branch is unchanged, so `L25f` (`--no-stills` wins over `--seed-image`) and
`L25a` (unseeded prompt byte-identical) still hold.

---

## 6. Change 3 of 5 — the advisory echo warning

### 6.1 Edit — line 74

Before:
```python
import re  # noqa: F401 -- kept for parity with the workspace's stdlib-only import convention
```
After:
```python
import re
```

### 6.2 Edit — three module-level helpers

Insert immediately **after** `_validate_story_md`'s `return violations` (line 419) and before
the `# ---` banner at line 422, verbatim:

```python
# Glue words dropped before comparing a panel's Image: text with Panel 1's Style:
# text. Deliberately minimal: the Style: line is a bare comma-separated attribute
# list, so nearly every word in it is signal, and a longer stop-list would only
# shrink an already 4-vs-15-vs-34 separation (see the docstring below).
_ECHO_STOPWORDS = frozenset(
    "and are its that the their they them this with without".split()
)

# A later panel is flagged when it recovers more than half of Panel 1's Style:
# words AND at least _ECHO_MIN_OVERLAP of them. Both conditions, so a very short
# Style: line cannot be tripped by a handful of incidental matches. Stories whose
# Style: line has fewer than _ECHO_MIN_STYLE_WORDS content words are not checked
# at all.
_ECHO_MIN_STYLE_WORDS = 12
_ECHO_MIN_OVERLAP = 12
_ECHO_FRACTION = 0.5


def _content_words(text):
    """Lowercased alphabetic words of 3+ characters, minus _ECHO_STOPWORDS."""
    return set(
        w for w in re.findall(r"[a-z]+", text.lower())
        if len(w) > 2 and w not in _ECHO_STOPWORDS
    )


def _load_story_panels(story_md_path):
    """Panel dicts from story_md_path via bin/ltx-story-manifest's parser, or []
    when the file cannot be read.

    Deliberately separate from _validate_story_md rather than a second return
    value from it: that function's return contract is "the list of FATAL
    violations" and three checks pin its signature, while this feeds an advisory
    warning that must never change a return code.
    """
    manifest_tool_path = os.path.join(WS, "bin", "ltx-story-manifest")
    try:
        story_manifest = importlib.machinery.SourceFileLoader(
            "ltx_story_manifest_for_movie", manifest_tool_path
        ).load_module()
        _narrative, panels = story_manifest._parse_prompts_md(story_md_path)
    except OSError:
        return []
    return panels


def _style_echo_warnings(panels):
    """Advisory warnings about a seeded story.md, as a list of strings ([] == clean).

    Two things are reported, neither of them fatal:

    1. A panel after the first whose Image: field re-states the appearance that
       Panel 1's Style: line already carries. Phase 2 appends the Style: text to
       every panel's image prompt mechanically, so restating it puts the same
       attribute list in the prompt twice and crowds out the shot type, camera
       angle and framing -- which is exactly how the 2026-09-13 drift_red_test
       run ended up rendering "extreme wide shot ... receding into the distance"
       as a close-up portrait. Measured on that run, later panels recovered 34-37
       of Panel 1's 42 Style: words against a threshold of 22; a compliant
       composition-only panel recovers about 4 of 29 against a threshold of 15.
       Panel 1 is exempt: it is the literal description of the reference image,
       so a near-total Style: overlap there is correct.
    2. A Style: line under any panel but the first. Harmless -- the pipeline
       reads Panel 1's alone -- but it means the prompt's once-only rule did not
       land, which is worth seeing.

    This is a warning and not a _validate_story_md violation on purpose: item 1
    is a word-overlap heuristic, violations are fatal with no override flag, and
    a false positive must not be able to strand a legitimate story behind a word
    counter.
    """
    if not panels:
        return []

    warnings = []
    style_words = _content_words(panels[0].get("style", ""))
    if len(style_words) >= _ECHO_MIN_STYLE_WORDS:
        threshold = max(_ECHO_MIN_OVERLAP,
                        int(_ECHO_FRACTION * len(style_words)) + 1)
        for p in panels[1:]:
            shared = _content_words(p.get("image", "")) & style_words
            if len(shared) >= threshold:
                warnings.append(
                    "panel %s: Image: restates %d of Panel 1's %d Style: attribute words "
                    "(%s ...) -- the Style: text is appended to every panel's image prompt "
                    "automatically, so repeating appearance here doubles it and crowds out "
                    "this panel's shot type, camera angle and framing"
                    % (p.get("number"), len(shared), len(style_words),
                       ", ".join(sorted(shared)[:8]))
                )

    stray = [str(p.get("number")) for p in panels[1:] if p.get("style", "").strip()]
    if stray:
        warnings.append(
            "panels %s: carry a Style: line; only Panel 1's is read, so these are ignored "
            "-- harmless, but it means the story prompt's once-only rule did not land"
            % ", ".join(stray)
        )

    return warnings
```

### 6.2.1 The `_ECHO_MIN_STYLE_WORDS` guard is inert — deliberately, and not to be "fixed"

Added 2026-09-13. **The code block above is correct and final; nothing in this subsection
changes it.** It exists so the next reader does not mistake the guard for dead code and delete
it, or mistake it for the short-`Style:`-line rule and retune it.

`if len(style_words) >= _ECHO_MIN_STYLE_WORDS:` cannot change `_style_echo_warnings`' output
for any input, at the constants this spec ships. Proof:

1. `threshold = max(_ECHO_MIN_OVERLAP, int(_ECHO_FRACTION * len(style_words)) + 1)`, so
   `threshold >= _ECHO_MIN_OVERLAP = 12` for every input.
2. `shared = _content_words(image) & style_words` is a subset of `style_words`, so
   `len(shared) <= len(style_words)` for every input.
3. The guard only suppresses work when `len(style_words) < _ECHO_MIN_STYLE_WORDS = 12`. In
   that branch, (2) gives `len(shared) < 12` and (1) gives `threshold >= 12`, so
   `len(shared) >= threshold` is false for every panel regardless.

The guard therefore changes behaviour only for `Style:` lines whose content-word count `n`
satisfies `_ECHO_MIN_OVERLAP <= n < _ECHO_MIN_STYLE_WORDS`. That interval is empty whenever
`_ECHO_MIN_STYLE_WORDS <= _ECHO_MIN_OVERLAP`, which is the shipped configuration (`12 <= 12`).

**Invariant for future edits:** keep `_ECHO_MIN_STYLE_WORDS <= _ECHO_MIN_OVERLAP`. While that
holds, the guard is a readability early-out and the floor in `max()` is the single place the
short-`Style:`-line rule lives. If a later change lowers `_ECHO_MIN_OVERLAP` below
`_ECHO_MIN_STYLE_WORDS`, the guard silently becomes a second, *tighter* suppression rule and
both the comment at `bin/ltx-movie:446-450` and §7.7's N-12 row must be re-derived.

Note the direction: **lowering** `_ECHO_MIN_STYLE_WORDS` (to 8, 6, 4 ...) does not make the
guard load-bearing, it makes it more inert. Only raising it above `_ECHO_MIN_OVERLAP` would,
and that is rejected in §3.5 — it would stop checking `Style:` lines of 12-14 content words
that are flagged today, trading real coverage for a red mutation.

### 6.3 Edit — print them in `phase1_story` (lines 629-634)

Before:
```python
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")

    return 0
```
After:
```python
    if not args.no_review:
        with open(story_md) as f:
            content = f.read()
        print("=== story.md ===")
        print(content)

    # Advisory only -- never changes the return code (see _style_echo_warnings).
    # Printed after the story dump so a human reviewing it sees these immediately
    # above the prompt they are about to answer, and printed under --no-review too
    # so they land in movie.log.
    for warning in _style_echo_warnings(_load_story_panels(story_md)):
        print("Warning: %s" % warning)

    if not args.no_review:
        input("Review story.md above. Enter to continue, Ctrl-C to abort: ")

    return 0
```

The `if not args.no_review:` block is deliberately split in two so the warnings land between
the dump and the prompt. The prompt string is unchanged.

The call is not gated on `require_style`: an unseeded story.md has no `Style:` field, so
`style_words` is empty, `len(style_words) >= 12` is False and `stray` is empty — the function
returns `[]` and nothing prints. One code path, no branch to get wrong, and a hand-written
grounded story.md gets checked too.

---

## 7. Change 4 of 5 — `tests/test_ltx_movie_offline.py`

**Run mode: direct script invocation only. Never `pytest`.** `check()` records failures and
`__main__` sets the exit code; under pytest every one of these reports "passed" no matter what
fails. Capture `rc` **before** any pipe.

### 7.1 Two existing checks updated (the only pre-existing checks this spec changes)

Both break solely because of the postface (C6). Both are strengthened.

**`L25d`**, `tests/test_ltx_movie_offline.py:739-740`. Before:
```python
    check("L25d seeded prompt ends with the unseeded template appended intact",
          p_on.endswith(p_off))
```
After:
```python
    check("L25d seeded prompt is preface + unseeded template + postface, exactly",
          p_on == (ltx_movie.SEED_IMAGE_PREFACE + "\n\n" + p_off + "\n\n"
                   + ltx_movie.SEED_IMAGE_POSTFACE),
          "got tail %r" % p_on[-400:])
```

**`L30e`**, `tests/test_ltx_movie_offline.py:1018`. Before:
```python
    check("L30e p_on ends with p_off (unchanged assembly)", p_on.endswith(p_off))
```
After:
```python
    check("L30e p_on ends with the postface and still contains p_off intact",
          p_on.endswith(ltx_movie.SEED_IMAGE_POSTFACE)
          and ("\n\n" + p_off + "\n\n") in p_on,
          "got tail %r" % p_on[-400:])
```

No other pre-existing check changes. `L25a`, `L25b`, `L25c`, `L25e`, `L25f`, `L27e`, `L30a`-`L30d`,
`L31a`-`L31e`, `L32a`-`L32e`, `L33a`, `L33b` and `L2` all pass unmodified — verified against the
§4/§5 text in §4.1.

### 7.2 New test `L34` — the postface exists, overrides last, and says the right things

Insert after `test_require_style_call_site_guard` (ends line 1118), with the usual banner
comment block:

```python
# ---------------------------------------------------------------------------
# L34: SEED_IMAGE_POSTFACE -- the two overrides are restated AFTER the template
# ---------------------------------------------------------------------------

def test_seed_postface_overrides_last():
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True)
    p_off = ltx_movie.build_story_prompt("n", "sid", 5)
    post = ltx_movie.SEED_IMAGE_POSTFACE

    check("L34a postface present only when seeded",
          post in p_on and post not in p_off)
    check("L34b postface is the tail of the seeded prompt", p_on.endswith(post))
    check("L34c the VERBATIM rule it overrides appears BEFORE it",
          p_on.index("must repeat that exact description VERBATIM") < p_on.index(post),
          "postface must come after the rule it overrides")
    for phrase in (
        "Two of the rules above are overridden for this movie",
        "The VERBATIM-repetition rule applies only to a new recurring character or element "
        "you introduce later that is NOT visible in the attached image.",
        "not word for word and not reworded",
        "The 70-90 word length applies to Panel 1's Image: field.",
        "Every later panel's Image: field is 45-70 words of composition only",
        "Every other panel has exactly three, in this order: Image:, Motion:, Narration: "
        "-- and no Style: line.",
    ):
        check("L34d postface contains %r" % phrase[:60], phrase in post,
              "missing from postface")
    check("L34e postface ends with the template's own terminator",
          post.endswith("Do not verify the file with run_python or any other tool. "
                        "Emit no other text."))
    check("L34f --no-stills still wins over --seed-image",
          ltx_movie.build_story_prompt("n", "sid", 5, True, True)
          == ltx_movie.build_story_prompt("n", "sid", 5, True, False))
```

### 7.3 New test `L35` — the preface bans restatement and specifies the replacement construction

```python
# ---------------------------------------------------------------------------
# L35: preface bans RESTATING appearance (not just copying) and gives later
# panels a positive construction to use instead
# ---------------------------------------------------------------------------

def test_seed_preface_bans_restated_appearance():
    p_on = ltx_movie.build_story_prompt("n", "sid", 5, False, True)
    pre = ltx_movie.SEED_IMAGE_PREFACE

    for phrase in (
        "and do not restate its content in your own words either",
        "not word for word and not reworded",
        "Appearance, wardrobe, hair, skin, face, build, materials, colour palette, "
        "lighting character and rendering style must not be described again in any "
        "Image: field after Panel 1",
        "Each later panel's Image: field is 45-70 words",
        "shot type first, then camera viewpoint, then the subject's short referring "
        "phrase, then the action and placement, then the setting",
        "one short referring phrase of at most five words",
        "That phrase is the only appearance detail a later Image: field may carry.",
        "A later panel has exactly three fields, in this order: Image:, Motion:, "
        "Narration: -- and no Style: line.",
        "The pipeline reads that line from Panel 1 alone, so a Style: line written "
        "under Panel 2 or later is dead text that is never read.",
    ):
        check("L35a preface contains %r" % phrase[:60], phrase in pre, "missing from preface")

    check("L35b the old 70-90-words-per-later-panel wording is gone",
          "its own 70-90 word description" not in pre)
    check("L35c 45-70 appears in both preface and postface",
          "45-70 words" in pre and "45-70 words" in ltx_movie.SEED_IMAGE_POSTFACE)
    check("L35d none of this leaks into the unseeded prompt",
          "45-70 words" not in ltx_movie.build_story_prompt("n", "sid", 5))
    # Three occurrences, not two: STORY_PROMPT_TEMPLATE already uses this exact
    # clause for the Motion: field (the ban the model demonstrably obeys, which is
    # why the preface and postface borrow its wording). Verified 2026-09-13:
    # build_story_prompt("n","sid",5).count(...) == 1.
    check("L35e assembled seeded prompt carries the ban three times "
          "(template Motion: rule + preface + postface)",
          p_on.count("not word for word and not reworded") == 3
          and ltx_movie.build_story_prompt("n", "sid", 5)
              .count("not word for word and not reworded") == 1,
          "got %d" % p_on.count("not word for word and not reworded"))
```

### 7.4 New test `L36` — `_style_echo_warnings`

```python
# ---------------------------------------------------------------------------
# L36: _style_echo_warnings -- the advisory appearance-echo heuristic
# ---------------------------------------------------------------------------

_ECHO_STYLE = ("young woman with tightly curled auburn-red hair, warm light-brown skin with "
               "scattered freckles, brown eyes, glossy pink lips, soft even diffused "
               "lighting, clean high-resolution photographic rendering, shallow depth of "
               "field")
# Reproduces the drift_red_test defect: shot type, then the whole appearance list.
_ECHO_BAD_IMAGE = ("A wide shot of a young woman with tightly curled auburn-red hair, warm "
                   "light-brown skin with scattered freckles, brown eyes and glossy pink "
                   "lips, seen from behind as she walks away down a quiet street at dusk, "
                   "rendered in a clean high-resolution photographic style with a shallow "
                   "depth of field.")
# Compliant: composition only, referring phrase, and a few incidental shared words
# ("woman", "soft", "even", "light") so the check is not passing trivially.
_ECHO_GOOD_IMAGE = ("A wide shot from behind, the camera at knee height on the crown of the "
                    "road, the curly-haired woman small in the centre of the frame walking "
                    "away down a quiet residential street at dusk, low houses and parked cars "
                    "on either side, soft even dusk light on the pavement, perspective lines "
                    "converging at a distant intersection.")
_ECHO_GREEK = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda omicron rho "
               "sigma tau upsilon phi chi psi omega")


def _echo_panels(style, images, styles=None):
    """panels list for _style_echo_warnings: panel 1 carries `style`, panels
    2..N carry images[0..] (panel 1's own Image: text is irrelevant to the check)."""
    panels = [{"number": 1, "image": "panel one image text", "style": style}]
    for idx, img in enumerate(images, start=2):
        panels.append({"number": idx, "image": img,
                       "style": (styles or {}).get(idx, "")})
    return panels


def test_style_echo_warnings():
    check("L36k _content_words drops glue words and 1-2 letter tokens",
          ltx_movie._content_words("The warm 35mm lens and its soft, even light")
          == {"warm", "lens", "soft", "even", "light"},
          "got %r" % ltx_movie._content_words(
              "The warm 35mm lens and its soft, even light"))

    w = ltx_movie._style_echo_warnings(_echo_panels(_ECHO_STYLE, [_ECHO_BAD_IMAGE]))
    check("L36a a restating panel is flagged", len(w) == 1, "got %r" % w)
    check("L36a the warning names the panel and the mechanism",
          w and w[0].startswith("panel 2: Image: restates ")
          and "crowds out" in w[0], "got %r" % w)

    check("L36b a composition-only panel is silent",
          ltx_movie._style_echo_warnings(_echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE])) == [],
          "got %r" % ltx_movie._style_echo_warnings(
              _echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE])))

    mixed = ltx_movie._style_echo_warnings(
        _echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE, _ECHO_BAD_IMAGE, _ECHO_GOOD_IMAGE]))
    check("L36c only the offending panel is flagged, by its number",
          len(mixed) == 1 and mixed[0].startswith("panel 3: "), "got %r" % mixed)

    # Panel 1 is exempt: its Image: IS the literal description of the reference,
    # so near-total Style: overlap there is correct, not a defect.
    p1 = _echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE])
    p1[0]["image"] = _ECHO_BAD_IMAGE
    check("L36d panel 1 is never flagged",
          ltx_movie._style_echo_warnings(p1) == [], "got %r" % ltx_movie._style_echo_warnings(p1))

    # Threshold boundary. 20 distinct content words -> threshold 12.
    greek = _ECHO_GREEK.split()
    below = _echo_panels(_ECHO_GREEK,
                         ["A wide shot of the road, " + " ".join(greek[:11]) + ", camera static."])
    at = _echo_panels(_ECHO_GREEK,
                      ["A wide shot of the road, " + " ".join(greek[:12]) + ", camera static."])
    check("L36e 11 of 20 shared words is below threshold",
          ltx_movie._style_echo_warnings(below) == [], "got %r" % ltx_movie._style_echo_warnings(below))
    check("L36e 12 of 20 shared words trips it",
          len(ltx_movie._style_echo_warnings(at)) == 1, "got %r" % ltx_movie._style_echo_warnings(at))

    # A very short Style: line is not checked at all.
    short = _echo_panels("teal palette, matte grain", ["teal palette, matte grain everywhere"])
    check("L36f a Style: line under 12 content words is skipped",
          ltx_movie._style_echo_warnings(short) == [],
          "got %r" % ltx_movie._style_echo_warnings(short))

    # Stray Style: lines -- reported, and separately from the echo warnings.
    stray = ltx_movie._style_echo_warnings(
        _echo_panels(_ECHO_STYLE, [_ECHO_GOOD_IMAGE, _ECHO_GOOD_IMAGE],
                     styles={2: _ECHO_STYLE, 3: _ECHO_STYLE}))
    check("L36g stray Style: lines are reported once, listing the panels",
          len(stray) == 1 and stray[0].startswith("panels 2, 3: carry a Style: line"),
          "got %r" % stray)

    check("L36h empty panel list returns [] and does not raise",
          ltx_movie._style_echo_warnings([]) == [])
    check("L36i panels with no style key at all return []",
          ltx_movie._style_echo_warnings([{"number": 1, "image": "x"},
                                          {"number": 2, "image": "y"}]) == [])

    # Reproduces the real defect's exact proportions -- 34 of 42 Style: words
    # recovered, against a threshold of 22. Synthesised from 42 distinct nonsense
    # tokens ("qzwaa", "qzwab", ...), deliberately NOT read from
    # generated/stories/drift_red_test/story.md: that file is regenerated by the
    # acceptance rerun (A3) and generated/ is not version-controlled, so a test
    # reading it would flip red the moment the fix is validated.
    big_tokens = ["qzw" + chr(97 + n // 26) + chr(97 + n % 26) for n in range(42)]
    big_style = " ".join(big_tokens)
    check("L36j fixture really has 42 distinct content words",
          len(ltx_movie._content_words(big_style)) == 42,
          "got %d" % len(ltx_movie._content_words(big_style)))
    real_shape = _echo_panels(big_style,
                              ["A wide shot down the street, " + " ".join(big_tokens[:34])])
    check("L36j the real run's 34-of-42 proportion is flagged",
          len(ltx_movie._style_echo_warnings(real_shape)) == 1,
          "got %r" % ltx_movie._style_echo_warnings(real_shape))
```

`_load_story_panels` is covered by `L37d`/`L37e`.

### 7.5 New test `L37` — the call site

```python
# ---------------------------------------------------------------------------
# L37: phase1_story prints the warnings and _load_story_panels works
# ---------------------------------------------------------------------------

def test_style_echo_call_site_guard():
    with open(_SCRIPT_PATH) as f:
        text = f.read()
    check("L37a phase1_story prints the advisory warnings exactly once",
          text.count(
              '    for warning in _style_echo_warnings(_load_story_panels(story_md)):\n'
              '        print("Warning: %s" % warning)\n') == 1)
    check("L37b the warning loop is not inside an `if not args.no_review` block",
          '        for warning in _style_echo_warnings(' not in text,
          "the loop must be at function indent, so --no-review runs still log it")
    check("L37c _validate_story_md still returns only fatal violations",
          'def _validate_story_md(story_md_path, expected_panels, no_stills=False, '
          'require_style=False):' in text
          and "_style_echo_warnings" not in text.split("def _validate_story_md")[1]
              .split("return violations")[0])

    with tempfile.TemporaryDirectory() as td:
        md = os.path.join(td, "story.md")
        with open(md, "w") as f:
            f.write(
                "# Story\n\n"
                "## Panel 1 — First\n"
                "Image: a scene one\n"
                "Motion: camera pans\n"
                "Narration: narration one\n"
                "Style: teal palette, matte grain\n\n"
                "## Panel 2 — Second\n"
                "Image: a scene two\n"
                "Motion: camera pans again\n"
                "Narration: narration two\n"
            )
        panels = ltx_movie._load_story_panels(md)
        check("L37d _load_story_panels parses a real file",
              len(panels) == 2 and panels[0]["style"] == "teal palette, matte grain",
              "got %r" % panels)
        check("L37e _load_story_panels returns [] for a missing file",
              ltx_movie._load_story_panels(os.path.join(td, "nope.md")) == [])
```

### 7.6 `__main__` registration

Append, in this order, immediately after `test_require_style_call_site_guard()`:

```python
    test_seed_postface_overrides_last()
    test_seed_preface_bans_restated_appearance()
    test_style_echo_warnings()
    test_style_echo_call_site_guard()
```

### 7.7 Mutation table (SC3) — each must turn the named check RED

Apply one at a time to `bin/ltx-movie`, run `python3 tests/test_ltx_movie_offline.py`
directly, confirm a FAIL line **naming the listed check** and a non-zero exit, then revert.

| # | Mutation | Must fail |
|---|---|---|
| N-1 | `build_story_prompt` drops `+ "\n\n" + SEED_IMAGE_POSTFACE` | `L25d`, `L30e`, `L34a`, `L34b` |
| N-2 | `build_story_prompt` returns `SEED_IMAGE_POSTFACE + "\n\n" + SEED_IMAGE_PREFACE + "\n\n" + rendered` (postface first) | `L25d`, `L34b`, `L34c` |
| N-3 | Delete `, and do not restate its content in your own words either.` from the preface | `L35a` |
| N-4 | Change the preface's `45-70 words` back to `70-90 words` | `L35a`, `L35c` |
| N-5 | Delete `A later panel has exactly three fields, in this order: Image:, Motion:, Narration: -- and no Style: line.` from the preface | `L35a` |
| N-6 | Delete item 2 (the word-budget override) from the postface | `L34d`, `L35c` |
| N-7 | `_style_echo_warnings` returns `[]` as its first statement | `L36a`, `L36c`, `L36e`, `L36g`, `L36j` |
| N-8 | `threshold = max(_ECHO_MIN_OVERLAP, int(_ECHO_FRACTION * len(style_words)) + 1) * 2` | `L36a`, `L36c`, `L36e` |
| N-9 | Set `_ECHO_FRACTION = 0.02` **and** `_ECHO_MIN_OVERLAP = 1` **and** `_ECHO_MIN_STYLE_WORDS = 1` together, so the threshold collapses to 1 | `L36b`, `L36e` (the 11-word case now warns), `L36f` |
| N-10 | Loop over `panels` instead of `panels[1:]` in the echo loop | `L36d` |
| N-11 | Delete the `stray` block | `L36g` |
| N-12 | Drop the `if len(style_words) >= _ECHO_MIN_STYLE_WORDS:` guard (dedent its body) | **NOTHING — this row is a verified no-op, not a failure to fix.** See §7.7.1. |
| N-13 | Delete the two-line warning-print loop from `phase1_story` | `L37a` |
| N-14 | Move the warning-print loop inside the first `if not args.no_review:` block (indent it) | `L37a`, `L37b` |
| N-15 | `_load_story_panels` returns `[]` unconditionally | `L37d` |
| N-16 | `_content_words` drops the `len(w) > 2` filter and the stopword filter (`return set(re.findall(r"[a-z]+", text.lower()))`) | `L36k` — and `L36k` only. Verified 2026-09-13: this mutation does **not** move any other `L36` verdict, because the 4-vs-15-vs-34 separation is far wider than the filters' contribution. The filters are a robustness margin, not load-bearing, and `L36k` pins them directly rather than through the heuristic's output. |

### 7.7.1 N-12 — reclassified as a verified no-op (resolved 2026-09-13)

**The original row was wrong.** It required N-12 to turn `L36f` ("a Style: line under 12
content words is skipped") red. It cannot: §6.2.1 proves the guard cannot change
`_style_echo_warnings`' output for *any* input while `_ECHO_MIN_STYLE_WORDS <=
_ECHO_MIN_OVERLAP`, so `L36f`'s fixture (`"teal palette, matte grain"`, 4 content words) is
not a gap in the test, it is one point inside a provably empty behaviour window. Same
treatment as N-16: the construct is documented as non-load-bearing rather than the mutation
being faked red by retuning a shipped constant.

**Executor instruction: apply N-12, confirm the suite stays at `OK 290/290` with rc=0, revert,
and record that as the row's pass condition.** A FAIL here means a constant drifted and §6.2.1's
invariant is broken — stop and escalate rather than editing a fixture.

`L36f` is retained unchanged. It no longer claims to pin the guard; it pins the *behaviour*
(short `Style:` line ⇒ no warning), which is real, which `N-9` does turn red, and which the
`_ECHO_MIN_OVERLAP` floor implements.

**Verification run, 2026-09-13, against this repo with §4-§7 fully applied.** Run from a
mirror tree (`bin/` and `tests/` copied, siblings symlinked) so the working copy is never
mutated; the mirror reproduced the unmutated baseline `OK 290/290` first.

1. Suite under N-12: `rc=0`, `OK 290/290`, `PASS L36f ...`. A line-by-line diff of all 290
   `PASS`/`FAIL` verdicts against the unmutated baseline was **empty** — not one check moved.
2. Differential over the whole input space, guarded build vs dedented build:
   - exhaustive `n = 0..60` `Style:` content words x `k = 0..n` recovered words x 3 filler
     lengths = **5,673 input points, 0 divergences**;
   - randomised fuzz over real vocabulary, 2-5 panels, stray `Style:` lines and missing keys =
     **20,000 stories, 0 divergences**;
   - enumerating `n` where the guard could change the verdict (`_ECHO_MIN_OVERLAP <= n <
     _ECHO_MIN_STYLE_WORDS`, `n = 0..199`) = **empty set**.
3. Real-data check: the only seeded `story.md` on disk (`generated/stories/drift_red_test`)
   has 42 `Style:` content words, threshold 22, later-panel overlap `[37, 34, 34, 34, 34]` —
   matching §3.5's table exactly and sitting far outside the guard's window.
4. Both option-(b) alternatives were run and rejected on evidence:
   `_ECHO_MIN_OVERLAP = 8` (guard intact) breaks a currently-green check —
   `FAIL L36e 11 of 20 shared words is below threshold`, `OK 289/290`, rc=1.
   `_ECHO_MIN_STYLE_WORDS = 15` keeps `OK 290/290` and *would* make N-12 red at `n = 12, 13,
   14`, but only by no longer flagging those stories at all — buying a red mutation with real
   coverage, against a `Style:` range the prompt specifies as 40-70 words. Rejected.

Re-derivation harness — paste into a mirror tree if a constant ever changes:

```python
# usage: python3 harness.py <path to guarded ltx-movie> <path to dedented copy>
import importlib.machinery, random, sys
a = importlib.machinery.SourceFileLoader("g", sys.argv[1]).load_module()
b = importlib.machinery.SourceFileLoader("n", sys.argv[2]).load_module()
tok = lambda i: "qzw" + chr(97 + i // 26) + chr(97 + i % 26)
diffs = 0
for n in range(61):
    style = " ".join(tok(i) for i in range(n))
    for k in range(n + 1):
        for j in (0, 5, 40):
            img = (" ".join(tok(i) for i in range(k)) + " "
                   + " ".join("zzz" + tok(i) for i in range(j)))
            p = [{"number": 1, "image": "panel one image text", "style": style},
                 {"number": 2, "image": img, "style": ""}]
            diffs += a._style_echo_warnings(p) != b._style_echo_warnings(p)
print("divergences:", diffs)
print("guard window:", [n for n in range(200)
                        if n < a._ECHO_MIN_STYLE_WORDS
                        and n >= max(a._ECHO_MIN_OVERLAP, int(a._ECHO_FRACTION * n) + 1)])
```
Expected output while §6.2.1's invariant holds: `divergences: 0` and `guard window: []`.

### 7.8 Regression set that must stay green, unedited

`python3 tests/test_ltx_story_images.py`, `python3 tests/test_ltx_story_video.py`,
`python3 tests/test_ltx_chain.py`, `python3 tests/test_ltx_mlx_render.py`.

---

## 8. Change 5 of 5 is none — acceptance checks

Run from `/Users/reubenpatterson/local_model_harness/qwen-agent-workspace`. `SCRATCH` means
the session scratchpad directory.

### A0 — archive the evidence BEFORE anything else

The failing story.md is the only record of the defect and `generated/` is not version
controlled. Before editing any file:

```
mkdir -p "$SCRATCH/prefix_evidence"
cp generated/stories/drift_red_test/story.md "$SCRATCH/prefix_evidence/story_BEFORE.md"
cp -R generated/stories/drift_red_test/images "$SCRATCH/prefix_evidence/images_BEFORE"
```
Report the two paths and `wc -l` of the copied story.md.

### A1 — offline suites (SC1, SC2)

```
python3 tests/test_ltx_movie_offline.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_story_images.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_story_video.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_chain.py; rc=$?; echo "rc=$rc"
python3 tests/test_ltx_mlx_render.py; rc=$?; echo "rc=$rc"
```
Capture `rc` **before** any pipe — `... | tail` reports tail's status, not the suite's.
Report each `rc` and each `OK n/n` line.

### A2 — mutation table (SC3)

Walk every row of §7.7 one at a time. Report, per row: the mutation applied, the exact FAIL
check names observed, the non-zero rc, and confirmation that the suite returned to `OK n/n`
after revert.

### A3 — the real end-to-end rerun. **Do not run without the user's go-ahead.**

Requires the 27B server (`ailexleon/Huihui-Qwen3.8-27B-abliterated-mlx-6Bit` via `mlx_vlm.server`
at 127.0.0.1:8177) and the Z-Image stack. Phase 4 is hours of GPU time and proves nothing here
— the driver aborts before it.

#### A3.1 — the driver

Write this to `"$SCRATCH/run_a3.py"` verbatim (it is the already-proven A4 driver from the
Step 1 run, with only the log path changed), then `python3 "$SCRATCH/run_a3.py"`:

```python
#!/usr/bin/env python3
"""Drive bin/ltx-movie interactively: answer the Phase 1 story-review prompt
with Enter, then send Ctrl-C at the Phase 4 render-confirmation prompt
(before any GPU render time is spent)."""
import os
import pexpect
import sys

WS = "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "movie_a3.log")

cmd = (
    'python3 bin/ltx-movie "a young woman with curly red hair looks into the camera, '
    'then turns and walks away down a quiet street at dusk" '
    "--story-id drift_red_test --seed-image /Users/reubenpatterson/Downloads/red.jpg "
    "--panels 6 --force-story"
)

child = pexpect.spawn("/bin/bash", ["-c", cmd], cwd=WS, timeout=1800, encoding="utf-8")
logfile = open(LOG, "w")
child.logfile = logfile

try:
    idx = child.expect([
        "Review story.md above. Enter to continue, Ctrl-C to abort:",
        pexpect.EOF,
        pexpect.TIMEOUT,
    ])
    if idx != 0:
        print("DID NOT REACH story.md REVIEW PROMPT (idx=%d)" % idx)
        sys.exit(1)
    child.sendline("")

    idx = child.expect([
        "Review the plan and the estimated render time above. Enter to render, Ctrl-C to abort:",
        pexpect.EOF,
        pexpect.TIMEOUT,
    ])
    if idx != 0:
        print("DID NOT REACH PHASE 4 CONFIRMATION PROMPT (idx=%d)" % idx)
        sys.exit(1)

    print("REACHED PHASE 4 CONFIRMATION PROMPT -- sending SIGINT now")
    child.sendintr()  # Ctrl-C
    child.expect(pexpect.EOF, timeout=30)
    print("PROCESS EXITED AFTER SIGINT, status:", child.exitstatus, child.signalstatus)
finally:
    logfile.close()
```

The command is byte-for-byte the one that produced the defect, including `--force-story`
(which is what makes Phase 1 regenerate over the archived story.md).

#### A3.2 — machine checks on the new `generated/stories/drift_red_test/story.md`

```
grep -c 'Warning: panel .*: Image: restates' "$SCRATCH/movie_a3.log"   # SC4: must be 0
grep -c 'Warning: panels .*: carry a Style: line' "$SCRATCH/movie_a3.log"  # SC8: report only
grep -c '^Style: ' generated/stories/drift_red_test/story.md           # SC8: 1 is the goal
```

Then this measurement script (write to `"$SCRATCH/measure_a3.py"`, run with `python3`), which
prints the before/after table the report must contain:

```python
import importlib.machinery, os, sys
WS = "/Users/reubenpatterson/local_model_harness/qwen-agent-workspace"
ltx = importlib.machinery.SourceFileLoader(
    "ltx_movie", os.path.join(WS, "bin", "ltx-movie")).load_module()

for label, path in (("BEFORE", sys.argv[1]), ("AFTER", sys.argv[2])):
    panels = ltx._load_story_panels(path)
    sw = ltx._content_words(panels[0].get("style", "")) if panels else set()
    thr = max(ltx._ECHO_MIN_OVERLAP, int(ltx._ECHO_FRACTION * len(sw)) + 1)
    print("%s  %s   style_words=%d threshold=%d" % (label, path, len(sw), thr))
    for p in panels[1:]:
        shared = ltx._content_words(p["image"]) & sw
        print("   panel %s: overlap %2d/%d (%3.0f%%)  image_words=%d  style_line=%s"
              % (p["number"], len(shared), len(sw),
                 100.0 * len(shared) / max(len(sw), 1), len(p["image"].split()),
                 bool(p.get("style", "").strip())))
    print()
```
```
python3 "$SCRATCH/measure_a3.py" "$SCRATCH/prefix_evidence/story_BEFORE.md" \
        generated/stories/drift_red_test/story.md
```

Pass conditions:
- **SC4**: every AFTER panel's overlap percentage is **< 50%** (equivalently: zero
  `Image: restates` warnings in the log). BEFORE shows 81-88% — the table must show both, side
  by side, as the evidence the fix landed.
- **SC5**: every AFTER `image_words` is in 45-70; at most one outside, none above 85.
- Each AFTER `Image:` field begins with a shot type (`wide shot`, `extreme wide shot`,
  `medium shot`, `medium close-up`, `close-up`, `extreme close-up`) — read the file and
  confirm by eye.
- Each AFTER later `Image:` field names the subject with a referring phrase of ≤5 words and
  carries no hair/skin/freckle/eyebrow/lip/eye words — read the file and confirm by eye.
- **SC8 (report only)**: `style_line=False` on every AFTER panel 2..6, and
  `grep -c '^Style: '` is 1. Report the actual numbers whether or not they are 1 and False.
  A miss here is **not** a failure of this spec.

#### A3.3 — human eyeball on the new stills (SC6, SC7)

`generated/stories/drift_red_test/images/panel_0{1..6}.png`, side by side with
`~/Downloads/red.jpg` and with `"$SCRATCH/prefix_evidence/images_BEFORE"`. This is a human
judgement; the executor presents the images and the verdict text, it does not decide.

- **SC6 PASS**: the panels whose `Image:` field says *wide shot* / *extreme wide shot* /
  *seen from behind* / *receding* actually render that way — the subject is small in frame,
  back-facing, at a distance — and at least three visibly distinct camera distances appear
  across the six panels. The BEFORE set, where panels 4 and 6 are close-up front-facing
  portraits despite saying "extreme wide shot", is the control.
- **SC6 FAIL**: panels 4-6 are still close-up front-facing portraits. Report it, attach the
  new story.md and the overlap table, and stop. Do not iterate on the wording a third time
  without the user; if the overlap table shows SC4 passing while the pixels still ignore the
  shot type, the remaining cause is the txt2img model, not the story prompt, and that is a
  different investigation.
- **SC7 PASS**: the subject in panels 2-6 is still recognisably the person in
  `~/Downloads/red.jpg`. **SC7 FAIL**: identity has walked away — report it immediately and
  stop; that would mean the referring-phrase substitution starved the prompt of identity and
  the `Style:` budget needs revisiting, which is a user decision.

---

## 9. Edge cases

| Case | Required behaviour |
|---|---|
| Unseeded run (`no --seed-image`) | Prompt byte-identical to today (`L25a`, `L35d`). No preface, no postface, no `Style:`, and `_style_echo_warnings` returns `[]` because the story has no `Style:` field, so nothing prints. |
| `--seed-image` + `--no-stills` | Already a hard error in `bin/ltx-movie` (line 876). `build_story_prompt`'s `no_stills` branch is unchanged, so no postface either (`L34f`). |
| `--no-review` | Warnings still print (they are outside the review block, `L37b`), so they land in `movie.log`. |
| Story.md unreadable at the warning call site | `_load_story_panels` returns `[]` on `OSError`, `_style_echo_warnings([])` returns `[]`. Cannot happen in practice — `_validate_story_md` already read the same file and returned before this point — and costs one `try`. |
| `Style:` line present but under 12 content words | Echo check skipped entirely (`_ECHO_MIN_STYLE_WORDS`); the stray-`Style:` check still runs. |
| `Style:` line whitespace-only | `require_style` already fails the run fatally (Step 1 §6.2) before the warnings are reached. |
| `Style:` in panels 2..N | Reported as an advisory warning, still not a validation error, still parsed-never-read by `bin/ltx-story-images`. Unchanged behaviour, new visibility. |
| A panel legitimately shares many `Style:` words (e.g. a macro shot of the subject's hair) | Warned, not blocked. The human sees one `Warning:` line above the review prompt and presses Enter. This is the whole reason C5 chose a warning. |
| Panel dicts missing the `style` or `number` key | `.get()` throughout; `L36i` covers it. |
| Composed prompt length | 45-70 (`Image:`) + 40-70 (`Style:`) = 85-140 words, down from the observed 133 with the attribute list duplicated. No new length logic anywhere. |

---

## 10. Executor checklist

1. Run A0 (archive the pre-fix story.md and images) **before** editing anything.
2. Apply §4 (preface), §5 (postface + `build_story_prompt`), §6 (import comment, three
   helpers, `phase1_story` print block).
3. Apply §7.1 (two updated checks), §7.2-§7.5 (four new tests), §7.6 (registration).
4. Run A1 with `rc` captured before any pipe, then walk the full §7.7 mutation table (A2).
5. Report: each suite's `rc` and `OK n/n`; the mutation table with the observed failing check
   names per row; the A0 archive paths.
6. **Do NOT run A3** unless the user asks — it needs the 27B server and the Z-Image stack.
   Hand back the exact commands and the driver file instead.
7. Do not commit. Do not push. Do not modify `bin/ltx-story-images`,
   `bin/ltx-story-manifest`, `bin/ltx-story-video`, `ltx_ceiling.json`, `ltx_video_skill.py`,
   `z_image_skill.py`, `tests/test_ltx_story_images.py`, `STORY_PROMPT_TEMPLATE` or
   `STORY_PROMPT_TEMPLATE_NO_STILLS`.
8. If anything here is ambiguous, stop and return the question. Make no design call.

---

## 11. Open questions

None. Every design choice — ban wording, attribute enumeration, the 45-70 word budget, the
referring-phrase construction, postface vs preface-only, warning vs fatal violation, the
overlap threshold and its two constants, panel-1 exemption, the stray-`Style:` demotion to
report-only, and which two existing checks to update — is resolved above.
